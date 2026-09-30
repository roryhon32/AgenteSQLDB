"""
database.py — Gerenciamento de conexão DuckDB, introspecção de schema e execução segura.

Responsabilidades:
  - Abrir e manter conexão com DuckDB (in-memory ou arquivo)
  - Popular dados de exemplo em banco vazio
  - Introspectar schema dinamicamente via information_schema
  - Executar queries com validação de segurança e timeout
  - Formatar resultados como tabela Markdown
"""

from __future__ import annotations

import json
import re
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import duckdb


# ---------------------------------------------------------------------------
# Modelo de resultado de execução
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    """Resultado de uma execução de query no DuckDB."""

    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    error: Optional[str] = None
    cost: int = 0
    total_bytes: int = 0

    @property
    def row_count(self) -> int:
        return len(self.rows)


# ---------------------------------------------------------------------------
# Validação de segurança
# ---------------------------------------------------------------------------

_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|MERGE"
    r"|GRANT|REVOKE|ATTACH|DETACH|COPY|EXPORT|IMPORT|EXEC|EXECUTE"
    r"|PRAGMA|CALL|LOAD|INSTALL)\b",
    re.IGNORECASE,
)

_ALLOWED_START_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def _validate_sql(sql: str) -> Optional[str]:
    """
    Retorna mensagem de erro se o SQL não for seguro, ou None se for válido.
    """
    stripped = sql.strip().rstrip(";").strip()

    if not stripped:
        return "A query está vazia."

    if not _ALLOWED_START_RE.match(stripped):
        first = re.match(r"\s*(\w+)", stripped)
        word = first.group(1) if first else "?"
        return f"A query deve começar com SELECT ou WITH. Recebido: '{word}'."

    match = _FORBIDDEN_RE.search(stripped)
    if match:
        return f"Operação proibida detectada: '{match.group(1).upper()}'. Apenas leitura é permitida."

    # Múltiplos statements
    body = stripped.rstrip(";")
    if ";" in body:
        return "Múltiplas instruções SQL detectadas (';' interno). Apenas uma query por vez."

    return None


# ---------------------------------------------------------------------------
# Função oficial para puxar o Schema do Banco de Dados via Query SQL
# ---------------------------------------------------------------------------

def fetch_database_schema(conn: duckdb.DuckDBPyConnection) -> str:
    """
    Executa uma query no banco de dados para puxar o schema oficial das tabelas,
    colunas e tipos de dados, estruturando as colunas mais importantes de negócio
    por dimensões analíticas para máxima precisão do LLM.
    """
    query = """
        SELECT 
            table_name,
            column_name,
            data_type
        FROM information_schema.columns
        WHERE table_schema = 'main'
        ORDER BY table_name, ordinal_position
    """
    rows = conn.execute(query).fetchall()
    if not rows:
        return "(Nenhuma tabela encontrada no banco de dados.)"

    schema_by_table: dict[str, dict[str, str]] = {}
    for table_name, col_name, data_type in rows:
        schema_by_table.setdefault(table_name, {})[col_name] = data_type

    parts = []
    for table_name, col_dict in schema_by_table.items():
        if table_name == "faturamento":
            curated_schema = """TABELA "faturamento" (Base Analítica de Faturamento e Inteligência de Vendas):

1. MÉTRICAS DE FATURAMENTO E RENTABILIDADE (Use sempre para valores, receita e lucro):
  - "Valor Contábil" (DOUBLE) [MÉTRICA OFICIAL DE FATURAMENTO / RECEITA / VENDAS. Use SUM("Valor Contábil")]
  - "Fat. Líquido" (DOUBLE) [Faturamento líquido deduzido. Usar SOMENTE se o usuário pedir 'líquido']
  - "Margem Bruta (R$)" (DOUBLE) [Margem em reais. Valores negativos (< 0) indicam prejuízo/clientes em risco]
  - "Margem Bruta (%)" (DOUBLE) [Margem percentual]
  - "Custo Médio Total" (DOUBLE) [Custo total da mercadoria]

2. DIMENSÃO TEMPORAL E DATAS (Use SEMPRE para filtros de período, mês e ano):
  - "Ano" (BIGINT) [Ano da venda: 2020 a 2026. Ex: "Ano" = 2026]
  - "Mês" (VARCHAR) [Mês com 3 letras minúsculas: 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'. Ex: "Mês" = 'ago' para agosto]
  - "Emissão" (DATE) [Data da emissão da NF no formato 'YYYY-MM-DD']
  - "Trimestre" (VARCHAR) [Trimestre do ano: '1T', '2T', '3T', '4T']

3. DIMENSÃO CLIENTE E UNIDADE DE NEGÓCIO (BU):
  - "Nome Cliente" (VARCHAR) [Razão social / nome do cliente. Use SEMPRE que a pergunta for sobre clientes]
  - "Cód. Cliente" (VARCHAR) [Código identificador do cliente]
  - "CNPJ/CPF" (VARCHAR) [Documento cadastral]
  - "Business Unit" (VARCHAR) [Unidade de Negócio: 'CORPORATIVO', 'SERVIÇOS', 'VAREJO', 'PME', 'GER7', 'TAS', 'PLATAFORMAS', 'VENDA DIRETA', 'GERUN', 'LATAM']

4. DIMENSÃO PRODUTO:
  - "PRODUTOS" (VARCHAR) [Linha / Família de produtos. Ex: GERUN, MP5, PPC930, etc.]
  - "Desc. Produto" (VARCHAR) [Descrição detalhada do item]
  - "FAT - Quant." (DOUBLE) [Volume / Quantidade física faturada]

5. DIMENSÃO COMERCIAL E GEOGRÁFICA:
  - "Nome Vendedor" (VARCHAR) [Nome do vendedor / executivo comercial]
  - "Canal de Venda" (VARCHAR) [Canal de venda]
  - "Estado" (VARCHAR) [UF do estado: 'SP', 'RJ', 'MG', 'RS', etc.]
  - "Município" (VARCHAR) [Cidade do cliente]
  - "Filial" (VARCHAR) [Filial de faturamento]

6. OUTRAS COLUNAS SECUNDÁRIAS DISPONÍVEIS:
  - "CFOP", "TES", "Segmento do Produto", "Tipo de Venda", "Tipo de Estoque"."""
            parts.append(curated_schema)
        else:
            col_lines = [f'  - "{col}" ({dtype})' for col, dtype in col_dict.items()]
            parts.append(f'TABELA "{table_name}":\n' + "\n".join(col_lines))

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# DatabaseManager
# ---------------------------------------------------------------------------

class DatabaseManager:
    """Gerencia a conexão DuckDB e fornece introspecção de schema e execução segura."""

    def __init__(
        self,
        db_path: str = ":memory:",
        auto_seed: bool = True,
        read_only: bool = False
    ) -> None:
        self.db_path = db_path
        self.read_only = read_only

        if auto_seed and db_path != ":memory:":
            try:
                check_conn = duckdb.connect(db_path, read_only=True)
                existing_tables = [t[0].lower() for t in check_conn.execute("SHOW TABLES").fetchall()]
                check_conn.close()
            except Exception:
                existing_tables = []

            if "faturamento" not in existing_tables and "usuarios" not in existing_tables:
                admin_conn = duckdb.connect(db_path, read_only=False)
                self._seed_sample_data(admin_conn)
                admin_conn.close()
            self._conn = duckdb.connect(db_path, read_only=read_only)
        elif auto_seed and db_path == ":memory:":
            self._conn = duckdb.connect(db_path)
            self._seed_sample_data(self._conn)
        else:
            self._conn = duckdb.connect(
                db_path,
                read_only=(read_only if db_path != ":memory:" else False)
            )

    # ------------------------------------------------------------------
    # Dados de exemplo
    # ------------------------------------------------------------------

    def _seed_sample_data(self, conn: Optional[duckdb.DuckDBPyConnection] = None) -> None:
        """Cria e popula a tabela de exemplo 'usuarios' em bancos vazios com suporte a BU (RLS)."""
        target_conn = conn or self._conn
        target_conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id            INTEGER PRIMARY KEY,
                Cliente       VARCHAR,
                idade         INTEGER,
                cidade        VARCHAR,
                bu            VARCHAR,
                faturamento   DOUBLE,
                data_cadastro DATE,
                ultima_compra DATE
            )
        """)
        # Migração se a tabela já existisse sem a coluna 'bu'
        try:
            cols = [r[1] for r in target_conn.execute("PRAGMA table_info('usuarios')").fetchall()]
            if "bu" not in cols:
                target_conn.execute("ALTER TABLE usuarios ADD COLUMN bu VARCHAR DEFAULT 'Varejo';")
        except Exception:
            pass

        count = target_conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        if count == 0:
            target_conn.execute("""
                INSERT INTO usuarios VALUES
                (1,  'Carlos Silva',    42, 'São Paulo',      'Varejo',       12500.50, '2023-01-15', CURRENT_DATE - INTERVAL '200 days'),
                (2,  'Mariana Souza',   31, 'Rio de Janeiro', 'Fiscal',        8900.00, '2023-03-10', CURRENT_DATE - INTERVAL '120 days'),
                (3,  'Fernando Castro', 55, 'Belo Horizonte', 'Corporativo',  34200.00, '2022-11-05', CURRENT_DATE - INTERVAL '210 days'),
                (4,  'Beatriz Lima',    28, 'Curitiba',       'Varejo',        5400.00, '2024-02-01', CURRENT_DATE - INTERVAL '30 days'),
                (5,  'Lucas Oliveira',  39, 'Porto Alegre',   'Contabil',     19800.75, '2023-08-20', CURRENT_DATE - INTERVAL '95 days'),
                (6,  'Juliana Mendes',  47, 'Salvador',       'Corporativo',  27600.00, '2022-07-14', CURRENT_DATE - INTERVAL '45 days'),
                (7,  'Rodrigo Alves',   35, 'Campinas',       'Varejo',       15400.00, '2023-05-18', CURRENT_DATE - INTERVAL '20 days'),
                (8,  'Patricia Santos', 41, 'Recife',         'Fiscal',       22100.00, '2023-09-01', CURRENT_DATE - INTERVAL '15 days'),
                (9,  'Gabriel Duarte',  50, 'Brasília',       'Contabil',     11300.00, '2022-12-10', CURRENT_DATE - INTERVAL '60 days'),
                (10, 'Camila Rocha',    29, 'Fortaleza',      'Servicos',      9800.00, '2024-01-12', CURRENT_DATE - INTERVAL '10 days')
            """)

    # ------------------------------------------------------------------
    # Introspecção de schema
    # ------------------------------------------------------------------

    def introspect_schema(self) -> str:
        """
        Inspeciona o banco em tempo de execução via query SQL e retorna o schema
        compacto pronto para injeção no System Prompt do LLM ({schema}).
        """
        return fetch_database_schema(self._conn)

    # ------------------------------------------------------------------
    # Controle de Complexidade via EXPLAIN
    # ------------------------------------------------------------------

    def check_query_cost(self, sql: str, max_cost: int = 5000) -> Tuple[bool, Optional[str], int]:
        """
        Executa EXPLAIN (FORMAT JSON) para inspecionar o plano físico gerado.
        Rejeita planos que excedem o limiar de complexidade ou produtos cartesianos indesejados.
        """
        try:
            plan_rows = self._conn.execute(f"EXPLAIN (FORMAT JSON) {sql}").fetchall()
            if not plan_rows:
                return True, None, 10

            plan_json_str = plan_rows[0][1]
            plan_tree = json.loads(plan_json_str)

            cost = 0
            has_cartesian = False

            def _traverse(node: Dict[str, Any]) -> None:
                nonlocal cost, has_cartesian
                name = str(node.get("name", "")).upper()
                cost += 10  # Custo base de cada operador

                if "CROSS_PRODUCT" in name:
                    has_cartesian = True
                    cost += 300

                extra = node.get("extra_info", {})
                if isinstance(extra, dict):
                    card_str = str(extra.get("Estimated Cardinality", "0")).replace("~", "").strip()
                    try:
                        cardinality = int(card_str)
                        if cardinality > 5000:
                            cost += 100
                    except (ValueError, TypeError):
                        pass

                for child in node.get("children", []):
                    if isinstance(child, dict):
                        _traverse(child)

            if isinstance(plan_tree, list):
                for root in plan_tree:
                    if isinstance(root, dict):
                        _traverse(root)
            elif isinstance(plan_tree, dict):
                _traverse(plan_tree)

            if has_cartesian and cost > max_cost:
                return False, f"Plano rejeitado por complexidade: Produto Cartesiano detectado (custo {cost} > {max_cost}).", cost

            if cost > max_cost:
                return False, f"Plano de execução rejeitado: custo estimado ({cost}) excedeu o limite ({max_cost}).", cost

            return True, None, cost
        except Exception:
            # Em caso de falha de parsing do EXPLAIN, continua para a execução capturar o erro
            return True, None, 0

    # ------------------------------------------------------------------
    # Execução segura
    # ------------------------------------------------------------------

    def execute_safe(
        self,
        sql: str,
        params: Optional[list | tuple | dict] = None,
        timeout: int = 30,
        max_explain_cost: int = 5000,
        max_result_bytes: int = 5242880  # 5 MB
    ) -> ExecutionResult:
        """
        Valida e executa uma query SQL de forma estritamente segura.

        - Rejeita comandos de escrita/mutação (AST Guardrail).
        - Avalia o custo do plano com EXPLAIN antes da execução física.
        - Executa de forma parametrizada em thread separada com timeout.
        - Valida o cap de memória em bytes dos resultados.
        - Retorna ExecutionResult com sucesso ou mensagem de erro.
        """
        # 1. Validação de segurança de sintaxe básica
        error_msg = _validate_sql(sql)
        if error_msg:
            return ExecutionResult(success=False, error=error_msg)

        cleaned = sql.strip().rstrip(";").strip()

        # 2. Avaliação de complexidade via EXPLAIN pré-execução
        cost_ok, cost_err, estimated_cost = self.check_query_cost(cleaned, max_cost=max_explain_cost)
        if not cost_ok:
            return ExecutionResult(success=False, error=cost_err, cost=estimated_cost)

        # 3. Execução parametrizada com timeout via thread
        result_holder: list[Optional[tuple]] = [None]
        error_holder: list[Optional[str]] = [None]

        def _run() -> None:
            try:
                # Executa com prepared statement / parâmetros se fornecidos
                if params is not None:
                    cursor = self._conn.execute(cleaned, params)
                else:
                    cursor = self._conn.execute(cleaned)

                cols = [desc[0] for desc in cursor.description] if cursor.description else []
                rows = cursor.fetchall()
                result_holder[0] = (cols, rows)
            except Exception as exc:
                error_holder[0] = str(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            return ExecutionResult(
                success=False,
                error=f"Timeout: a query excedeu {timeout}s de execução.",
                cost=estimated_cost
            )

        if error_holder[0] is not None:
            return ExecutionResult(success=False, error=error_holder[0], cost=estimated_cost)

        cols, rows = result_holder[0]  # type: ignore[misc]

        # 4. Cap de tamanho de resultado em bytes (Memória)
        total_bytes = sum(sys.getsizeof(col) for col in cols)
        for row in rows:
            total_bytes += sum(sys.getsizeof(val) for val in row)

        if total_bytes > max_result_bytes:
            return ExecutionResult(
                success=False,
                error=f"Tamanho do resultado ({total_bytes} bytes) excedeu o limite configurado de {max_result_bytes} bytes.",
                cost=estimated_cost,
                total_bytes=total_bytes
            )

        return ExecutionResult(
            success=True,
            columns=cols,
            rows=rows,
            cost=estimated_cost,
            total_bytes=total_bytes
        )

    # ------------------------------------------------------------------
    # Formatação de resultados
    # ------------------------------------------------------------------

    @staticmethod
    def format_as_markdown(result: ExecutionResult, max_rows: int = 15) -> str:
        """Converte o resultado de uma query em tabela Markdown."""
        if not result.success or not result.columns:
            return ""

        rows = result.rows[:max_rows]

        header = "| " + " | ".join(result.columns) + " |"
        separator = "| " + " | ".join(["---"] * len(result.columns)) + " |"
        data_lines = [
            "| " + " | ".join(str(v) for v in row) + " |"
            for row in rows
        ]

        table = "\n".join([header, separator, *data_lines])

        if result.row_count > max_rows:
            table += f"\n\n_(Mostrando {max_rows} de {result.row_count} registros)_"

        return table

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Fecha a conexão com o DuckDB."""
        self._conn.close()

