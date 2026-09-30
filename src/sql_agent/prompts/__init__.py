"""Módulo de prompts especializados para os agentes de SQL."""

from src.sql_agent.prompts.interpreter_prompt import prompt_interpretador
from src.sql_agent.prompts.sql_prompt import prompt_sql

__all__ = ["prompt_interpretador", "prompt_sql"]

