"""Agente 1: Interpretador de regras de negócio e intenções."""

from __future__ import annotations

import re
from typing import Optional
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

from src.sql_agent.config import get_llm
from src.sql_agent.database.schema import TableSchema
from src.sql_agent.prompts.interpreter_prompt import prompt_interpretador


class InterpreterAgent:
    """Interpreta perguntas em linguagem natural e traduz em especificações de negócio."""

    def __init__(self, llm: Optional[BaseChatModel] = None) -> None:
        self.llm = llm or get_llm(temperature=0.0)
        self.chain = prompt_interpretador | self.llm | StrOutputParser()

    def interpret(self, question: str, table_schema: TableSchema, history: str = "") -> str:
        """Executa a interpretação de negócio para a pergunta fornecida considerando o histórico."""
        response = self.chain.invoke({
            "pergunta": question,
            "tabela": table_schema.name,
            "colunas": table_schema.get_columns_text(),
            "historico": history or "Nenhum histórico anterior disponível."
        })
        cleaned = response.strip()
        # Remove eventuais marcações de markdown do retorno
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)
        return cleaned.strip()
