"""Testes unitários para o validador de segurança SQL."""

from src.sql_agent.utils.validators import SQLSecurityValidator


def test_valid_select_query():
    query = "SELECT id, Cliente, faturamento FROM usuarios WHERE faturamento > 10000;"
    result = SQLSecurityValidator.validate(query)
    assert result.is_valid is True
    assert result.error_message is None
    assert result.cleaned_query.startswith("SELECT")


def test_valid_cte_query():
    query = "WITH ativos AS (SELECT * FROM usuarios WHERE ultima_compra >= CURRENT_DATE - INTERVAL '90 days') SELECT * FROM ativos;"
    result = SQLSecurityValidator.validate(query)
    assert result.is_valid is True
    assert result.error_message is None


def test_markdown_cleaning():
    raw_markdown = "```sql\nSELECT * FROM usuarios;\n```"
    result = SQLSecurityValidator.validate(raw_markdown)
    assert result.is_valid is True
    assert result.cleaned_query == "SELECT * FROM usuarios;"


def test_forbidden_drop_command():
    query = "DROP TABLE usuarios;"
    result = SQLSecurityValidator.validate(query)
    assert result.is_valid is False
    assert "DROP" in result.error_message or "SELECT" in result.error_message


def test_sql_injection_multiple_statements():
    query = "SELECT * FROM usuarios; DROP TABLE usuarios;"
    result = SQLSecurityValidator.validate(query)
    assert result.is_valid is False
    assert "múltiplas instruções" in result.error_message.lower()


def test_sql_error_token():
    result = SQLSecurityValidator.validate("SQL_ERROR")
    assert result.is_valid is False
    assert "SQL_ERROR" in result.error_message


if __name__ == "__main__":
    test_valid_select_query()
    test_valid_cte_query()
    test_markdown_cleaning()
    test_forbidden_drop_command()
    test_sql_injection_multiple_statements()
    test_sql_error_token()
    print("Todos os testes de validação passaram com sucesso!")

