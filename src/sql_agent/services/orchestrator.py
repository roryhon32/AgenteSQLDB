"""Orquestrador do pipeline de agentes Text-to-SQL."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.sql_agent.database.executor import DuckDBExecutor
from src.sql_agent.database.schema import SchemaCatalog, TableSchema, default_catalog
from src.sql_agent.memory.conversation_memory import ConversationMemory
from src.sql_agent.services.interpreter_agent import InterpreterAgent
from src.sql_agent.services.sql_generator_agent import SQLGeneratorAgent
from src.sql_agent.utils.validators import SQLSecurityValidator


@dataclass
class QueryResult:
    """Resultado completo do pipeline de processamento."""
    question: str
    interpretation: str
    sql: Optional[str]
    is_valid_sql: bool
    success: bool
    error: Optional[str] = None
    execution_result: Optional[Dict[str, Any]] = None


class SQLAgentOrchestrator:
    """Coordena o fluxo completo entre o interpretador de negócio e o gerador de SQL com suporte a memória."""

    def __init__(
        self,
        catalog: Optional[SchemaCatalog] = None,
        execute_queries: bool = False,
        memory: Optional[ConversationMemory] = None
    ) -> None:
        self.catalog = catalog or default_catalog
        self.interpreter = InterpreterAgent()
        self.sql_generator = SQLGeneratorAgent()
        self.execute_queries = execute_queries
        self.executor = DuckDBExecutor() if execute_queries else None
        self.memory = memory if memory is not None else ConversationMemory()

    def clear_memory(self) -> None:
        """Limpa o histórico de interações da memória conversacional."""
        self.memory.clear()

    @property
    def memory_turns_count(self) -> int:
        """Retorna o número de turnos atualmente armazenados na memória."""
        return len(self.memory)

    def process_query(self, question: str, table_name: str = "usuarios") -> QueryResult:
        """Executa o pipeline completo: interpretação -> validação -> geração SQL -> validação de segurança -> execução opcional."""
        table_schema: Optional[TableSchema] = self.catalog.get_table(table_name)
        if not table_schema:
            return QueryResult(
                question=question,
                interpretation="",
                sql=None,
                is_valid_sql=False,
                success=False,
                error=f"Tabela '{table_name}' não encontrada no catálogo de schemas."
            )

        history = self.memory.get_history_text()

        # -------------------------------------------------------------
        # ETAPA 1: Interpretação das regras de negócio
        # -------------------------------------------------------------
        try:
            interpretation = self.interpreter.interpret(question, table_schema, history=history)
        except Exception as e:
            return QueryResult(
                question=question,
                interpretation="",
                sql=None,
                is_valid_sql=False,
                success=False,
                error=f"Erro ao executar o agente interpretador: {str(e)}"
            )

        # Guard clause para falha de interpretação
        if "INTERPRETACAO_ERROR" in interpretation.upper():
            return QueryResult(
                question=question,
                interpretation=interpretation,
                sql=None,
                is_valid_sql=False,
                success=False,
                error="O agente interpretador não conseguiu associar a pergunta às regras de negócio disponíveis."
            )

        # -------------------------------------------------------------
        # ETAPA 2: Geração da consulta SQL DuckDB
        # -------------------------------------------------------------
        try:
            raw_sql = self.sql_generator.generate_sql(question, interpretation, table_schema, history=history)
        except Exception as e:
            return QueryResult(
                question=question,
                interpretation=interpretation,
                sql=None,
                is_valid_sql=False,
                success=False,
                error=f"Erro ao executar o agente gerador de SQL: {str(e)}"
            )

        # -------------------------------------------------------------
        # ETAPA 3: Validação de Segurança (Defesa em Profundidade)
        # -------------------------------------------------------------
        validation = SQLSecurityValidator.validate(raw_sql)
        if not validation.is_valid:
            return QueryResult(
                question=question,
                interpretation=interpretation,
                sql=raw_sql,
                is_valid_sql=False,
                success=False,
                error=validation.error_message
            )

        cleaned_sql = validation.cleaned_query

        # -------------------------------------------------------------
        # ETAPA 4: Registro do Turno na Memória Conversacional
        # -------------------------------------------------------------
        self.memory.add_turn(
            question=question,
            interpretation=interpretation,
            sql=cleaned_sql
        )

        # -------------------------------------------------------------
        # ETAPA 5: Execução Opcional em DuckDB
        # -------------------------------------------------------------
        execution_data = None
        if self.execute_queries and self.executor:
            execution_data = self.executor.execute_query(cleaned_sql)

        return QueryResult(
            question=question,
            interpretation=interpretation,
            sql=cleaned_sql,
            is_valid_sql=True,
            success=True,
            execution_result=execution_data
        )

