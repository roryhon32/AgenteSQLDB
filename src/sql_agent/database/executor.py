"""Executor seguro para consultas em DuckDB."""

from typing import Any, Dict, List, Optional


class DuckDBExecutor:
    """Executa consultas SQL de forma segura em uma base DuckDB (em memória ou arquivo)."""

    def __init__(self, database_path: str = ":memory:", auto_seed_sample_data: bool = True) -> None:
        self.database_path = database_path
        self.auto_seed_sample_data = auto_seed_sample_data
        self._conn = None

    def _get_connection(self):
        """Retorna uma conexão ativa com o DuckDB, se a biblioteca estiver instalada."""
        if self._conn is not None:
            return self._conn

        try:
            import duckdb
        except ImportError:
            return None

        self._conn = duckdb.connect(self.database_path)
        if self.auto_seed_sample_data:
            self._seed_usuarios_table(self._conn)
        return self._conn

    @staticmethod
    def _seed_usuarios_table(conn) -> None:
        """Cria e popula uma tabela de exemplo de usuários para testes locais."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY,
                Cliente VARCHAR,
                idade INTEGER,
                cidade VARCHAR,
                faturamento DOUBLE,
                data_cadastro DATE,
                ultima_compra DATE
            );
        """)
        # Verifica se a tabela já possui dados
        count = conn.execute("SELECT count(*) FROM usuarios").fetchone()[0]
        if count == 0:
            conn.execute("""
                INSERT INTO usuarios VALUES
                (1, 'Carlos Silva', 42, 'São Paulo', 12500.50, '2023-01-15', CURRENT_DATE - INTERVAL '200 days'),
                (2, 'Mariana Souza', 31, 'Rio de Janeiro', 8900.00, '2023-03-10', CURRENT_DATE - INTERVAL '120 days'),
                (3, 'Fernando Castro', 55, 'Belo Horizonte', 34200.00, '2022-11-05', CURRENT_DATE - INTERVAL '210 days'),
                (4, 'Beatriz Lima', 28, 'Curitiba', 5400.00, '2024-02-01', CURRENT_DATE - INTERVAL '30 days'),
                (5, 'Lucas Oliveira', 39, 'Porto Alegre', 19800.75, '2023-08-20', CURRENT_DATE - INTERVAL '95 days'),
                (6, 'Juliana Mendes', 47, 'Salvador', 27600.00, '2022-07-14', CURRENT_DATE - INTERVAL '45 days');
            """)

    def execute_query(self, query: str) -> Dict[str, Any]:
        """Executa a consulta SQL e retorna as colunas e linhas resultantes."""
        conn = self._get_connection()
        if conn is None:
            return {
                "success": False,
                "error": "DuckDB não está instalado no ambiente. Para executar consultas reais, instale com: uv add duckdb",
                "columns": [],
                "rows": []
            }

        try:
            result = conn.execute(query)
            columns = [desc[0] for desc in result.description] if result.description else []
            rows = result.fetchall()
            return {
                "success": True,
                "columns": columns,
                "rows": rows,
                "error": None
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Erro na execução da consulta DuckDB: {str(e)}",
                "columns": [],
                "rows": []
            }

