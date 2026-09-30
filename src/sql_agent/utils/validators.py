"""Validador de segurança para consultas SQL geradas por LLM."""

import re
from dataclasses import dataclass
from typing import Optional, Set


@dataclass
class ValidationResult:
    """Resultado da validação de segurança de uma query SQL."""
    is_valid: bool
    cleaned_query: str
    error_message: Optional[str] = None


class SQLSecurityValidator:
    """Validador de defesa em profundidade para garantir que apenas consultas READ-ONLY sejam executadas."""

    # Palavras-chave proibidas que realizam escrita, alteração de esquema ou operações de sistema
    FORBIDDEN_KEYWORDS: Set[str] = {
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
        "CREATE", "REPLACE", "MERGE", "GRANT", "REVOKE", "ATTACH",
        "DETACH", "COPY", "EXPORT", "IMPORT", "EXEC", "EXECUTE",
        "PRAGMA", "CALL", "LOAD", "INSTALL"
    }

    @classmethod
    def clean_markdown_and_whitespace(cls, raw_sql: str) -> str:
        """Remove blocos markdown (ex: ```sql ... ```) e espaços extras."""
        text = raw_sql.strip()

        # Remove formatação markdown se o modelo tiver incluído
        if text.startswith("```"):
            lines = text.splitlines()
            # Remove a primeira linha ``` ou ```sql
            if len(lines) > 1 and lines[0].startswith("```"):
                lines = lines[1:]
            # Remove a última linha ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        return text

    @classmethod
    def validate(cls, raw_sql: str) -> ValidationResult:
        """Valida se a consulta SQL gerada é segura e exclusiva para leitura."""
        if not raw_sql or not raw_sql.strip():
            return ValidationResult(
                is_valid=False,
                cleaned_query="",
                error_message="A consulta SQL gerada está vazia."
            )

        cleaned = cls.clean_markdown_and_whitespace(raw_sql)

        if cleaned.upper() == "SQL_ERROR":
            return ValidationResult(
                is_valid=False,
                cleaned_query=cleaned,
                error_message="O agente SQL identificou impossibilidade de gerar a consulta conforme as regras (SQL_ERROR)."
            )

        # 1. Deve iniciar estritamente com SELECT ou WITH (para CTEs)
        first_word_match = re.match(r"^\s*([A-Za-z]+)", cleaned)
        if not first_word_match:
            return ValidationResult(
                is_valid=False,
                cleaned_query=cleaned,
                error_message="Não foi possível identificar o comando inicial da consulta."
            )

        first_word = first_word_match.group(1).upper()
        if first_word not in {"SELECT", "WITH"}:
            return ValidationResult(
                is_valid=False,
                cleaned_query=cleaned,
                error_message=f"Operação proibida: a consulta deve iniciar com SELECT ou WITH, mas iniciou com '{first_word}'."
            )

        # 2. Verificar múltiplos statements separados por ponto e vírgula
        # Remove ponto e vírgula final se houver
        normalized_stmt = cleaned.rstrip("; \t\r\n")
        if ";" in normalized_stmt:
            return ValidationResult(
                is_valid=False,
                cleaned_query=cleaned,
                error_message="Segurança violada: múltiplas instruções SQL detectadas (separador ';')."
            )

        # 3. Varredura por tokens proibidos
        tokens = re.findall(r"\b[A-Za-z_]+\b", cleaned)
        for token in tokens:
            token_upper = token.upper()
            if token_upper in cls.FORBIDDEN_KEYWORDS:
                return ValidationResult(
                    is_valid=False,
                    cleaned_query=cleaned,
                    error_message=f"Segurança violada: palavra-chave proibida detectada na query: '{token_upper}'."
                )

        return ValidationResult(
            is_valid=True,
            cleaned_query=cleaned,
            error_message=None
        )

