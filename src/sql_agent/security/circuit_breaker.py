"""
circuit_breaker.py — Rate Limiting e Circuit Breaker Adaptativo por Usuário/Sessão.

Protege o sistema contra:
1. Ataques de negação de serviço e sobrecarga de requisições (Rate Limiter).
2. Tentativas repetidas de injeção DDL/DML ou violação de segurança (Circuit Breaker).
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class CircuitState(str, Enum):
    CLOSED = "CLOSED"      # Normal: todas as requisições fluem
    OPEN = "OPEN"          # Disparado: usuário suspenso temporariamente
    HALF_OPEN = "HALF_OPEN" # Testando recuperação


class CircuitBreakerOpenException(Exception):
    """Exceção levantada quando o usuário atinge o limite de violações e está suspenso."""
    def __init__(self, message: str, retry_after_seconds: int):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


# ---------------------------------------------------------------------------
# Rate Limiter (Janela Deslizante de 60 segundos)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Rate limiter por usuário com algoritmo de janela deslizante (sliding window)."""

    def __init__(self, max_requests_per_minute: int = 30):
        self.max_requests_per_minute = max_requests_per_minute
        self._user_timestamps: Dict[str, List[float]] = defaultdict(list)

    def check_rate_limit(self, user_key: str) -> Tuple[bool, int]:
        """
        Verifica se a requisição está dentro do limite permitido.
        Retorna (permitido: bool, requisições_atuais_na_janela: int).
        """
        now = time.time()
        window_start = now - 60.0

        # Remove requisições mais antigas que 60 segundos
        timestamps = [t for t in self._user_timestamps[user_key] if t > window_start]
        self._user_timestamps[user_key] = timestamps

        if len(timestamps) >= self.max_requests_per_minute:
            return False, len(timestamps)

        # Registra a requisição atual
        self._user_timestamps[user_key].append(now)
        return True, len(self._user_timestamps[user_key])

    def get_remaining_requests(self, user_key: str) -> int:
        """Retorna o número de requisições restantes na janela atual."""
        now = time.time()
        window_start = now - 60.0
        timestamps = [t for t in self._user_timestamps.get(user_key, []) if t > window_start]
        return max(0, self.max_requests_per_minute - len(timestamps))


# ---------------------------------------------------------------------------
# Circuit Breaker de Segurança
# ---------------------------------------------------------------------------

@dataclass
class UserCircuitData:
    failures: List[float] = field(default_factory=list)
    state: CircuitState = CircuitState.CLOSED
    opened_at: Optional[float] = None


class SecurityCircuitBreaker:
    """
    Circuit Breaker que suspende usuários que acumulam violações de segurança
    (DDL/DML, injeção de prompt ou violação de escopo) em uma janela curta de tempo.
    """

    def __init__(
        self,
        failure_threshold: int = 3,       # 3 violações
        window_seconds: int = 300,        # em 5 minutos
        cooldown_seconds: int = 900       # suspensão de 15 minutos
    ):
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._circuits: Dict[str, UserCircuitData] = defaultdict(UserCircuitData)

    def is_allowed(self, user_key: str) -> Tuple[bool, Optional[str], int]:
        """
        Verifica se o usuário pode executar queries ou está em cooldown.
        Retorna: (permitido: bool, motivo_bloqueio: Optional[str], segundos_restantes: int)
        """
        circuit = self._circuits[user_key]
        now = time.time()

        if circuit.state == CircuitState.OPEN:
            elapsed = now - (circuit.opened_at or now)
            remaining = int(self.cooldown_seconds - elapsed)

            if remaining > 0:
                return (
                    False,
                    f"Circuit Breaker Ativado: Usuário temporariamente suspenso devido a {self.failure_threshold} "
                    f"tentativas de violação de segurança. Tente novamente em {remaining} segundos.",
                    remaining
                )
            else:
                # Transiciona para HALF-OPEN após expirar o cooldown
                circuit.state = CircuitState.HALF_OPEN
                circuit.failures.clear()
                return True, None, 0

        return True, None, 0

    def record_violation(self, user_key: str, risk_type: str = "Segurança") -> bool:
        """
        Registra uma violação grave de segurança (ex: tentativa DDL/DML).
        Retorna True se o Circuit Breaker acabou de ser disparado (trip).
        """
        now = time.time()
        circuit = self._circuits[user_key]
        window_start = now - self.window_seconds

        # Limpa falhas fora da janela
        circuit.failures = [t for t in circuit.failures if t > window_start]
        circuit.failures.append(now)

        if len(circuit.failures) >= self.failure_threshold:
            circuit.state = CircuitState.OPEN
            circuit.opened_at = now
            return True

        return False

    def record_success(self, user_key: str) -> None:
        """Registra uma execução bem-sucedida, reestabelecendo CLOSED se em HALF-OPEN."""
        circuit = self._circuits[user_key]
        if circuit.state == CircuitState.HALF_OPEN:
            circuit.state = CircuitState.CLOSED
            circuit.failures.clear()
            circuit.opened_at = None

    def reset_user(self, user_key: str) -> None:
        """Reseta administrativamente o estado do circuit breaker para o usuário."""
        if user_key in self._circuits:
            del self._circuits[user_key]


# Singletons globais
rate_limiter = RateLimiter(max_requests_per_minute=30)
circuit_breaker = SecurityCircuitBreaker(failure_threshold=3, window_seconds=300, cooldown_seconds=900)
