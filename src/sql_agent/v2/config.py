"""
config.py — Configurações centralizadas via config.yaml + .env

Prioridade de leitura (menor para maior):
  1. Valores padrão hardcoded
  2. config.yaml na raiz do projeto
  3. Variáveis de ambiente (.env ou sistema)
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Localiza a raiz do projeto (3 níveis acima deste arquivo: v2/sql_agent/src -> AgenteSQL)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_FILE = _PROJECT_ROOT / "config.yaml"
_ENV_FILE = _PROJECT_ROOT / ".env"


def _load_yaml() -> dict:
    """Carrega config.yaml se existir, retornando dicionário vazio caso contrário."""
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


_yaml = _load_yaml()
_db = _yaml.get("database", {})
_llm = _yaml.get("llm", {})
_sec = _yaml.get("security", {})


class Settings(BaseSettings):
    """Configurações centralizadas lidas do .env com fallback para config.yaml."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Banco de Dados ---
    db_path: str = Field(default=_db.get("db_path", ":memory:"))
    max_rows_context: int = Field(default=_db.get("max_rows_context", 15))
    query_timeout: int = Field(default=_db.get("query_timeout", 30))

    # --- LLM ---
    llm_backend: Literal["ollama", "openai", "groq"] = Field(
        default=_llm.get("backend", "groq")
    )
    ollama_model: str = Field(default=_llm.get("ollama_model", "qwen2.5-coder:7b"))
    ollama_base_url: str = Field(
        default=_llm.get("ollama_base_url", "http://localhost:11434")
    )
    openai_model: str = Field(default=_llm.get("openai_model", "gpt-4o-mini"))
    openai_api_key: str = Field(default="")
    temperature: float = Field(default=float(_llm.get("temperature", 0.0)))
    max_retries: int = Field(default=int(_llm.get("max_retries", 2)))

    # --- Segurança e Governança ---
    read_only_connection: bool = Field(default=bool(_sec.get("read_only_connection", True)))
    max_joins: int = Field(default=int(_sec.get("max_joins", 3)))
    max_subqueries: int = Field(default=int(_sec.get("max_subqueries", 2)))
    max_explain_cost: int = Field(default=int(_sec.get("max_explain_cost", 5000)))
    max_result_bytes: int = Field(default=int(_sec.get("max_result_bytes", 5242880)))
    auto_limit: int = Field(default=int(_sec.get("auto_limit", 100)))

    # Rate Limiting & Circuit Breaker
    rate_limit_per_minute: int = Field(default=int(_sec.get("rate_limit_per_minute", 30)))
    circuit_breaker_failures: int = Field(default=int(_sec.get("circuit_breaker_failures", 3)))
    circuit_breaker_window_seconds: int = Field(default=int(_sec.get("circuit_breaker_window_seconds", 300)))
    circuit_breaker_cooldown_seconds: int = Field(default=int(_sec.get("circuit_breaker_cooldown_seconds", 900)))

    # Observabilidade e Baseline
    rejection_rate_baseline: float = Field(default=float(_sec.get("rejection_rate_baseline", 0.20)))
    timeout_warning_threshold_ms: float = Field(default=float(_sec.get("timeout_warning_threshold_ms", 24000)))

    # Allowlist de tabelas e colunas
    allowlist: dict = Field(default=_sec.get("allowlist", {}))


# Singleton exportado para uso em toda a aplicação
settings = Settings()

