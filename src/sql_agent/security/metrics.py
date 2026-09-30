"""
metrics.py — Coletor de Métricas e Observabilidade (Padrão Prometheus / OpenTelemetry).

Exporta métricas analíticas e de segurança em formato padrão Prometheus:
- Contadores de queries por status e Unidade de Negócio.
- Taxa de rejeição por tipo de instrução/bloqueio (DDL/DML, Allowlist, Complexidade).
- Histogramas de latência de execução.
- Disparos de Circuit Breaker e queries próximas ao timeout.
- Monitoramento de anomalias com baseline de alerta configurável.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class RejectionEvent:
    timestamp: float
    reason_type: str


class MetricsCollector:
    """Coletor thread-safe de métricas para exportação no endpoint /metrics."""

    def __init__(self, rejection_rate_baseline: float = 0.20):
        self._lock = threading.RLock()
        self.rejection_rate_baseline = rejection_rate_baseline

        # Contadores de queries
        self._queries_total: Dict[Tuple[str, str], int] = defaultdict(int)  # (status, user_bu) -> count
        self._rejections_by_type: Dict[str, int] = defaultdict(int)          # reason_type -> count
        self._circuit_breaker_trips: int = 0
        self._queries_near_timeout: int = 0                                  # queries > 80% do timeout (24s)

        # Histograma de latência (buckets em ms)
        self._latency_buckets = [10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0, 20000.0, 30000.0]
        self._latency_counts: Dict[float, int] = {b: 0 for b in self._latency_buckets}
        self._latency_sum: float = 0.0
        self._latency_count: int = 0

        # Histórico recente para cálculo da taxa de rejeição da janela (últimos 15 min)
        self._recent_events: List[Tuple[float, bool, str]] = []  # (ts, is_success, reason_type)

    def record_query(
        self,
        status: str,              # 'success', 'blocked', 'error'
        user_bu: str,
        latency_ms: float,
        reason_type: Optional[str] = None
    ) -> None:
        """Registra a conclusão de uma consulta no pipeline."""
        now = time.time()
        is_success = status == "success"

        with self._lock:
            self._queries_total[(status, user_bu)] += 1

            if not is_success and reason_type:
                self._rejections_by_type[reason_type] += 1

            # Latência e histograma
            self._latency_sum += latency_ms
            self._latency_count += 1
            for b in self._latency_buckets:
                if latency_ms <= b:
                    self._latency_counts[b] += 1

            # Queries próximas de timeout (> 24 segundos)
            if latency_ms >= 24000.0:
                self._queries_near_timeout += 1

            # Janela recente de 15 minutos para baseline
            self._recent_events.append((now, is_success, reason_type or "unknown"))
            window_start = now - 900.0
            self._recent_events = [e for e in self._recent_events if e[0] > window_start]

    def record_circuit_breaker_trip(self) -> None:
        """Registra ativação do circuit breaker."""
        with self._lock:
            self._circuit_breaker_trips += 1

    def get_rejection_rate_ratio(self) -> float:
        """Calcula a taxa de rejeição observada na janela recente."""
        with self._lock:
            if not self._recent_events:
                return 0.0
            rejections = sum(1 for e in self._recent_events if not e[1])
            return round(rejections / len(self._recent_events), 4)

    def is_baseline_exceeded(self) -> Tuple[bool, float, float]:
        """
        Retorna se a taxa de rejeição atual ultrapassou o baseline configurado.
        (excedido: bool, taxa_atual: float, baseline: float)
        """
        ratio = self.get_rejection_rate_ratio()
        return (ratio > self.rejection_rate_baseline and len(self._recent_events) >= 5), ratio, self.rejection_rate_baseline

    def generate_prometheus_exposition(self) -> str:
        """Gera o payload em formato texto plano oficial do Prometheus."""
        lines: List[str] = []

        with self._lock:
            # 1. Total de consultas
            lines.append("# HELP sql_agent_queries_total Total de consultas recebidas pelo Agente SQL.")
            lines.append("# TYPE sql_agent_queries_total counter")
            for (status, bu), val in sorted(self._queries_total.items()):
                lines.append(f'sql_agent_queries_total{{status="{status}",bu="{bu}"}} {val}')

            # 2. Total de rejeições por tipo de violação
            lines.append("")
            lines.append("# HELP sql_agent_blocked_rejections_total Total de rejeições agrupadas por causa.")
            lines.append("# TYPE sql_agent_blocked_rejections_total counter")
            for reason, val in sorted(self._rejections_by_type.items()):
                clean_reason = reason.lower().replace(" ", "_")
                lines.append(f'sql_agent_blocked_rejections_total{{reason_type="{clean_reason}"}} {val}')

            # 3. Disparos do Circuit Breaker
            lines.append("")
            lines.append("# HELP sql_agent_circuit_breaker_tripped_total Número de suspensões de usuários pelo circuit breaker.")
            lines.append("# TYPE sql_agent_circuit_breaker_tripped_total counter")
            lines.append(f"sql_agent_circuit_breaker_tripped_total {self._circuit_breaker_trips}")

            # 4. Queries perto do timeout
            lines.append("")
            lines.append("# HELP sql_agent_queries_near_timeout_total Consultas executadas com tempo superior a 80% do timeout.")
            lines.append("# TYPE sql_agent_queries_near_timeout_total counter")
            lines.append(f"sql_agent_queries_near_timeout_total {self._queries_near_timeout}")

            # 5. Histograma de Latência
            lines.append("")
            lines.append("# HELP sql_agent_execution_latency_ms Latência de execução das queries em milissegundos.")
            lines.append("# TYPE sql_agent_execution_latency_ms histogram")
            for b in self._latency_buckets:
                lines.append(f'sql_agent_execution_latency_ms_bucket{{le="{b}"}} {self._latency_counts[b]}')
            lines.append(f'sql_agent_execution_latency_ms_bucket{{le="+Inf"}} {self._latency_count}')
            lines.append(f"sql_agent_execution_latency_ms_sum {self._latency_sum:.2f}")
            lines.append(f"sql_agent_execution_latency_ms_count {self._latency_count}")

            # 6. Gauge da taxa de rejeição atual
            ratio = self.get_rejection_rate_ratio()
            lines.append("")
            lines.append("# HELP sql_agent_rejection_rate_ratio Proporção de consultas rejeitadas na janela recente.")
            lines.append("# TYPE sql_agent_rejection_rate_ratio gauge")
            lines.append(f"sql_agent_rejection_rate_ratio {ratio}")

        return "\n".join(lines) + "\n"


# Singleton do Coletor
metrics_collector = MetricsCollector(rejection_rate_baseline=0.20)
