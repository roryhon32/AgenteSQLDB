"""Catálogo e representação de schemas de banco de dados para os agentes."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ColumnInfo:
    """Metadados de uma coluna do banco de dados."""
    name: str
    data_type: str = "TEXT"
    description: str = ""


@dataclass
class TableSchema:
    """Representação de uma tabela e suas colunas."""
    name: str
    description: str = ""
    columns: List[ColumnInfo] = field(default_factory=list)

    def get_columns_text(self) -> str:
        """Retorna as colunas formatadas em texto para injeção nos prompts."""
        return "\n".join(col.name for col in self.columns)


class SchemaCatalog:
    """Repositório de schemas de tabelas disponíveis para consulta."""

    def __init__(self) -> None:
        self._tables: Dict[str, TableSchema] = {}

    def register_table(self, table: TableSchema) -> None:
        """Registra uma nova tabela no catálogo."""
        self._tables[table.name.lower()] = table

    def get_table(self, table_name: str) -> Optional[TableSchema]:
        """Obtém os metadados de uma tabela pelo nome."""
        return self._tables.get(table_name.lower())

    def list_tables(self) -> List[str]:
        """Lista todos os nomes de tabelas registradas."""
        return list(self._tables.keys())


# Catálogo padrão com a tabela 'usuarios'
default_catalog = SchemaCatalog()
default_catalog.register_table(
    TableSchema(
        name="usuarios",
        description="Tabela contendo os dados cadastrais e histórico financeiro dos clientes.",
        columns=[
            ColumnInfo(name="id", data_type="INTEGER", description="Identificador único do usuário"),
            ColumnInfo(name="Cliente", data_type="VARCHAR", description="Nome do cliente"),
            ColumnInfo(name="idade", data_type="INTEGER", description="Idade do cliente em anos"),
            ColumnInfo(name="cidade", data_type="VARCHAR", description="Cidade de residência"),
            ColumnInfo(name="faturamento", data_type="DOUBLE", description="Faturamento financeiro total gerado"),
            ColumnInfo(name="data_cadastro", data_type="DATE", description="Data do cadastro inicial"),
            ColumnInfo(name="ultima_compra", data_type="DATE", description="Data da última compra realizada"),
        ]
    )
)

