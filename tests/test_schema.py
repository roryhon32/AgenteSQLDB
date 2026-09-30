"""Testes unitários para o catálogo de schemas."""

from src.sql_agent.database.schema import SchemaCatalog, TableSchema, ColumnInfo, default_catalog


def test_default_catalog_has_usuarios():
    table = default_catalog.get_table("usuarios")
    assert table is not None
    assert table.name == "usuarios"
    assert "id" in table.get_columns_text()
    assert "Cliente" in table.get_columns_text()
    assert "faturamento" in table.get_columns_text()


def test_custom_table_registration():
    catalog = SchemaCatalog()
    tabela_pedidos = TableSchema(
        name="pedidos",
        columns=[
            ColumnInfo(name="id_pedido"),
            ColumnInfo(name="valor_total"),
            ColumnInfo(name="data_pedido")
        ]
    )
    catalog.register_table(tabela_pedidos)
    retrieved = catalog.get_table("pedidos")
    assert retrieved is not None
    assert "id_pedido" in retrieved.get_columns_text()


if __name__ == "__main__":
    test_default_catalog_has_usuarios()
    test_custom_table_registration()
    print("Todos os testes de schema passaram com sucesso!")

