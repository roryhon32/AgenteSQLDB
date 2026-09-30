"""
sql_guardrail.py — Sanitizador SQL e Blindagem contra Comandos DDL/DML e Multi-statements.

Garante que apenas consultas analíticas de leitura (SELECT / WITH ... SELECT) sejam executadas.
Bloqueia categoricamente: INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, EXEC, EXECUTE,
CREATE, REPLACE, MERGE, GRANT, REVOKE, PRAGMA, COPY ou múltiplos statements.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set
from .scope_guardrail import GuardrailResult, STANDARD_REFUSAL_MESSAGE

_FORBIDDEN_SQL_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|MERGE"
    r"|GRANT|REVOKE|ATTACH|DETACH|COPY|EXPORT|IMPORT|EXEC|EXECUTE"
    r"|PRAGMA|CALL|LOAD|INSTALL)\b",
    re.IGNORECASE,
)

_ALLOWED_START_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

_JOIN_RE = re.compile(
    r"\b(?:(LEFT|RIGHT|FULL|INNER|CROSS)\s+)?JOIN\b",
    re.IGNORECASE,
)

_SELECT_RE = re.compile(r"\bSELECT\b", re.IGNORECASE)

_FROM_JOIN_TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+([a-zA-Z0-9_\.]+)",
    re.IGNORECASE,
)

_SENSITIVE_COLUMN_PATTERNS = re.compile(
    r"\b(password|senha|hash|secret|token|bearer|cpf|ssn|cartao|credit_card)\b",
    re.IGNORECASE,
)

_METADATA_DISCOVERY_RE = re.compile(
    r"\b(information_schema|pg_catalog|duckdb_\w+|pragma_\w+|sqlite_master)\b",
    re.IGNORECASE,
)

DEFAULT_ALLOWLIST = {
    "faturamento": {
        "concatenado", "month", "filial", "mês/ano", "origem", "setor", "emissão",
        "num. docto.", "série", "cód. cliente", "nome cliente", "cnpj/cpf", "estado",
        "município", "cód. vend.", "nome vendedor", "tes", "cfop", "item", "cód. prod.",
        "desc. produto", "cod. familia", "desc. familia", "cód. custo", "desc. c custo",
        "grupo", "tipo", "fat - quant.", "dev - quant.", "liq - quant.", "vlr. produtos",
        "vlr. mercadoria (bruto)", "desconto", "cód. condição", "desconto vd", "servicos vd",
        "valor contábil", "vlr.ipi", "vlr.icms", "vlr. iss", "pis", "cofins",
        "icms difal origem", "icms difal destino", "icms fundo de pobreza", "fat. líquido",
        "custo médio total", "custo médio unitário", "origem custo médio", "margem bruta (%)",
        "margem bruta (r$)", "vendedor ajustado", "data ajust.", "valor contábil ajustado",
        "fat. líquido ajustado", "custo total ajustado", "margem bruta ajustada",
        "preço médio", "preço serv. vd", "custo médio", "custo serv. vd", "cnpj aj.",
        "no. nf aj.", "cod. prod. aj.", "nf + prod.", "roadmap", "linha (família + bu)",
        "familia ajustada", "bu família", "bu prod.", "bu cliente", "business unit",
        "top 10", "produtos", "cliente real", "forçar bu", "cut-off", "dia", "mês",
        "semana", "ano", "bu centro de custo", "dif bus", "bu - vendedor", "codigo/descrição",
        "dia semana", "trimestre", "semestre", "ml%", "tipo de estoque", "fat - vend.interno",
        "fat - nome vend.int", "tx moeda", "empresa", "moeda", "conversao", "vlr negociado",
        "fat - estado-ent", "fat - município-ent", "campanha", "produtocamp",
        "classificação ccusto", "mês-ano", "ecomerce", "ajustar mb",
        "liq - margem bruta (r$)- produtos mb <15%", "liq - custo medio total- produtos mb <15%",
        "mb% produtos mb <15%", "liq - custo medio total- produtos mb >15%",
        "liq - custo medio total- ajustado", "liq - custo medio unit.- ajustado",
        "custo total- ajustado", "liq - mb (r$)- aju", "sistema operacional",
        "segmento do produto", "canal de venda", "tipo de venda", "mês/ano c/ cutoff",
        "ano c/ cutoff", "emissão c/ cutoff", "loja virtual", "projetos", "vendas em dólar",
        "subfamília", "status", "raiz cnpj", "e-comerce", "odm"
    },
    "usuarios": {
        "id", "cliente", "idade", "cidade", "bu",
        "faturamento", "data_cadastro", "ultima_compra"
    }
}

import duckdb
from pathlib import Path

_DB_FILE = Path("data/banco.duckdb")
_BINDER_CHECK_CONN = duckdb.connect(':memory:')
if _DB_FILE.exists():
    try:
        _BINDER_CHECK_CONN.execute(f"ATTACH '{_DB_FILE.as_posix()}' AS banco (READ_ONLY);")
        _BINDER_CHECK_CONN.execute("CREATE VIEW IF NOT EXISTS faturamento AS SELECT * FROM banco.faturamento;")
    except Exception:
        pass

try:
    _BINDER_CHECK_CONN.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER,
            Cliente VARCHAR,
            idade INTEGER,
            cidade VARCHAR,
            bu VARCHAR,
            faturamento DOUBLE,
            data_cadastro DATE,
            ultima_compra DATE
        )
    """)
except Exception:
    pass


class SQLGuardrail:
    """
    Valida se a query gerada é estritamente segura, analítica (Read-Only)
    e cumpre os limites de complexidade e governança de dados.
    """

    @classmethod
    def enforce_limit(cls, sql: str, max_limit: int = 100) -> str:
        """
        Garante que a query possua cláusula LIMIT, não excedendo o teto configurado.
        - Se não tiver LIMIT, anexa LIMIT max_limit.
        - Se tiver LIMIT N com N > max_limit, reduz para LIMIT max_limit.
        """
        stripped = sql.strip().rstrip(";").strip()
        limit_match = re.search(r"\bLIMIT\s+(\d+)\b", stripped, re.IGNORECASE)

        if limit_match:
            current_limit = int(limit_match.group(1))
            if current_limit > max_limit:
                stripped = re.sub(
                    r"\bLIMIT\s+\d+\b",
                    f"LIMIT {max_limit}",
                    stripped,
                    flags=re.IGNORECASE
                )
        else:
            stripped = f"{stripped} LIMIT {max_limit}"

        return stripped

    @classmethod
    def validate(
        cls,
        sql: str,
        allowlist: Optional[Dict[str, Set[str]]] = None,
        max_joins: int = 3,
        max_subqueries: int = 2
    ) -> GuardrailResult:
        """
        Validação em múltiplas camadas da query SQL (AST & Regras de Governança).
        """
        if not sql or not sql.strip():
            return GuardrailResult(
                is_allowed=False,
                risk_type="Tentativa de Escrita SQL",
                system_action="Bloqueado pelo Guardrail",
                refusal_message=STANDARD_REFUSAL_MESSAGE,
                reason="Query SQL vazia."
            )

        stripped = sql.strip().rstrip(";").strip()

        # 1. Deve iniciar estritamente com SELECT ou WITH
        if not _ALLOWED_START_RE.match(stripped):
            return GuardrailResult(
                is_allowed=False,
                risk_type="Tentativa de Escrita SQL",
                system_action="Bloqueado pelo Guardrail",
                refusal_message=STANDARD_REFUSAL_MESSAGE,
                reason="A instrução SQL não inicia com SELECT ou WITH."
            )

        # 1.1 Blocklist de Descoberta de Metadados do Banco (Hardcoded)
        if _METADATA_DISCOVERY_RE.search(stripped):
            return GuardrailResult(
                is_allowed=False,
                risk_type="Descoberta de Schema Proibida",
                system_action="Bloqueado por Proteção de Metadados",
                refusal_message="Consulta de metadados do banco não é permitida.",
                reason="Tentativa de consulta aos metadados do banco de dados (information_schema/catalog/pragma)."
            )

        # 2. Bloqueia operações de escrita/mutação/destruição (DDL/DML/Admin)
        match = _FORBIDDEN_SQL_RE.search(stripped)
        if match:
            op = match.group(1).upper()
            return GuardrailResult(
                is_allowed=False,
                risk_type="Tentativa de Escrita SQL",
                system_action="Bloqueado pelo Guardrail",
                refusal_message=STANDARD_REFUSAL_MESSAGE,
                reason=f"Operação proibida detectada na query: '{op}'."
            )

        # 3. Bloqueia múltiplos statements (';' interno)
        body = stripped.rstrip(";")
        if ";" in body:
            return GuardrailResult(
                is_allowed=False,
                risk_type="Tentativa de Escrita SQL",
                system_action="Bloqueado pelo Guardrail",
                refusal_message=STANDARD_REFUSAL_MESSAGE,
                reason="Múltiplas instruções SQL detectadas (ponto e vírgula interno)."
            )

        # 4. AST Complexity: Limite de JOINs
        joins_found = _JOIN_RE.findall(stripped)
        if len(joins_found) > max_joins:
            return GuardrailResult(
                is_allowed=False,
                risk_type="Complexidade Excessiva",
                system_action="Bloqueado por Limite de JOINs",
                refusal_message=STANDARD_REFUSAL_MESSAGE,
                reason=f"A query excede o número máximo permitido de JOINs ({len(joins_found)} > {max_joins})."
            )

        # 5. AST Complexity: Limite de Subqueries aninhadas
        selects_found = _SELECT_RE.findall(stripped)
        subqueries_count = max(0, len(selects_found) - 1)
        if subqueries_count > max_subqueries:
            return GuardrailResult(
                is_allowed=False,
                risk_type="Complexidade Excessiva",
                system_action="Bloqueado por Limite de Subqueries",
                refusal_message=STANDARD_REFUSAL_MESSAGE,
                reason=f"A query excede o número máximo de subqueries aninhadas ({subqueries_count} > {max_subqueries})."
            )

        # 6. Governança e Acesso: Obrigatoriedade de Cláusula FROM e Allowlist de Tabelas
        tables_allowed = allowlist.keys() if allowlist else DEFAULT_ALLOWLIST.keys()
        tables_in_query = _FROM_JOIN_TABLE_RE.findall(stripped)
        
        # Consultas analíticas devem obrigatoriamente referenciar tabelas corporativas válidas
        if not tables_in_query:
            return GuardrailResult(
                is_allowed=False,
                risk_type="Fuga de Escopo",
                system_action="Bloqueado por Ausência de Tabela Autorizada",
                refusal_message=STANDARD_REFUSAL_MESSAGE,
                reason="A consulta SQL gerada não referencia nenhuma tabela corporativa autorizada (cláusula FROM ausente)."
            )

        for tbl in tables_in_query:
            clean_tbl = tbl.lower().strip()
            # Ignora subqueries em parênteses ou aliases comuns
            if clean_tbl in ("(", "select", "as"):
                continue
            if not any(clean_tbl == allowed.lower() or clean_tbl.endswith(f".{allowed.lower()}") for allowed in tables_allowed):
                return GuardrailResult(
                    is_allowed=False,
                    risk_type="Acesso a Objeto Não Autorizado",
                    system_action="Bloqueado por Allowlist de Tabelas",
                    refusal_message=STANDARD_REFUSAL_MESSAGE,
                    reason=f"Acesso à tabela '{tbl}' não autorizado pelas políticas de governança."
                )

        # 7. Governança e Acesso: Bloqueio de Colunas Sensíveis (PII / Credenciais)
        sensitive_match = _SENSITIVE_COLUMN_PATTERNS.search(stripped)
        if sensitive_match:
            sens_col = sensitive_match.group(1)
            return GuardrailResult(
                is_allowed=False,
                risk_type="Acesso a Coluna Sensível",
                system_action="Bloqueado por Proteção de PII",
                refusal_message=STANDARD_REFUSAL_MESSAGE,
                reason=f"Tentativa de consulta a campo sensível ou restrito: '{sens_col}'."
            )

        # 8. Validação Estrita de Colunas Referenciadas (Anti-Binder Error)
        # Compara cada identificador de coluna contra o schema autorizado da tabela
        target_table = "faturamento" if "faturamento" in stripped.lower() else "usuarios"
        valid_cols = sorted(DEFAULT_ALLOWLIST.get(target_table, set()))
        valid_cols_str = ", ".join(f"'{c}'" for c in valid_cols)

        try:
            _BINDER_CHECK_CONN.execute("EXPLAIN " + stripped)
        except Exception as binder_err:
            err_str = str(binder_err)
            match_col = re.search(r'Referenced column "([^"]+)" not found', err_str, re.IGNORECASE)
            bad_col = match_col.group(1) if match_col else "desconhecida"
            return GuardrailResult(
                is_allowed=False,
                risk_type="Coluna Inexistente no Schema",
                system_action="Bloqueado por Validação Estrita de Colunas",
                refusal_message=f"A coluna '{bad_col}' não existe no schema disponível. Colunas válidas para '{target_table}': {valid_cols_str}.",
                reason=f"A coluna '{bad_col}' não existe no schema da tabela '{target_table}'."
            )

        return GuardrailResult(is_allowed=True)
