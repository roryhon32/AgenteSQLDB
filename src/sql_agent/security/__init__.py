"""
Módulo de Segurança Avançada, Auditoria Imutável e Observabilidade.
Contém:
- Redator e mascarador de PII
- Rate Limiter e Circuit Breaker
- Trilha de Auditoria Imutável com Hash Encadeado (SHA-256)
- Coletor de Métricas Prometheus / OpenTelemetry
"""

from .pii_redactor import PIIRedactor
from .circuit_breaker import (
    RateLimiter,
    SecurityCircuitBreaker,
    rate_limiter,
    circuit_breaker,
    CircuitBreakerOpenException
)
from .immutable_audit import ImmutableAuditService
from .metrics import MetricsCollector, metrics_collector

__all__ = [
    "PIIRedactor",
    "RateLimiter",
    "SecurityCircuitBreaker",
    "rate_limiter",
    "circuit_breaker",
    "CircuitBreakerOpenException",
    "ImmutableAuditService",
    "MetricsCollector",
    "metrics_collector",
]
