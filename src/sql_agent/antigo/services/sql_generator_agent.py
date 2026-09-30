"""Agente 2: Gerador de consultas SQL DuckDB a partir da interpretação de negócio."""

from __future__ import annotations

import re
from typing import Optional
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

from src.sql_agent.config import get_llm
from src.sql_agent.database.schema import TableSchema
from src.sql_agent.prompts.sql_prompt import prompt_sql


class SQLGeneratorAgent:
    """Traduz uma especificação de negócio em uma consulta SQL válida para DuckDB."""

    def __init__(self, llm: Optional[BaseChatModel] = None) -> None:
        self.llm = llm or get_llm(temperature=0.0)
        self.chain = prompt_sql | self.llm | StrOutputParser()

    def generate_sql(self, question: str, interpretation: str, table_schema: TableSchema, history: str = "") -> str:
        """Gera a instrução SQL com base na pergunta, interpretação estruturada e histórico recente."""
        response = self.chain.invoke({
            "pergunta": question,
            "interpretacao": interpretation,
            "tabela": table_schema.name,
            "colunas": table_schema.get_columns_text(),
            "historico": history or "Nenhum histórico anterior disponível."
        })
        cleaned = response.strip()
        # Remove blocos markdown (ex: ```sql ... ``` ou ``` ...)
        match = re.search(r"```(?:sql)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()
        elif cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned).strip()

        return cleaned
