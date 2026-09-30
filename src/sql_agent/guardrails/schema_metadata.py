"""
schema_metadata.py — Metadados descritivos e apresentação curada do schema analítico.
Uso exclusivo para respostas informativas de apresentação ao usuário.
A validação de segurança de queries continua utilizando a allowlist estrita do SQLGuardrail.
"""

from typing import Dict, Any, List

TABLE_DESCRIPTIONS: Dict[str, Dict[str, Any]] = {
    "faturamento": {
        "description": "Base analítica de faturamento e inteligência de vendas (324.908 registros).",
        "key_columns": [
            {"column": "Nome Cliente", "description": "Nome ou identificador do cliente"},
            {"column": "Cód. Cliente", "description": "Código identificador do cliente"},
            {"column": "CNPJ/CPF", "description": "Documento cadastral do cliente"},
            {"column": "Fat. Líquido", "description": "Valor monetário do faturamento líquido faturado (R$)"},
            {"column": "Valor Contábil", "description": "Valor contábil total da operação (R$)"},
            {"column": "Margem Bruta (R$)", "description": "Margem bruta em reais (R$)"},
            {"column": "Margem Bruta (%)", "description": "Margem bruta percentual da venda"},
            {"column": "PRODUTOS", "description": "Linha ou modelo de produto"},
            {"column": "Desc. Produto", "description": "Descrição detalhada do produto faturado"},
            {"column": "Business Unit", "description": "Unidade de Negócio ('CORPORATIVO', 'VAREJO', 'SERVIÇOS', 'PME', 'PLATAFORMAS', etc.)"},
            {"column": "Estado", "description": "UF de faturamento (ex: 'SP', 'RS', 'RJ')"},
            {"column": "Município", "description": "Nome da cidade/município"},
            {"column": "Nome Vendedor", "description": "Nome do vendedor ou executivo comercial responsável"},
            {"column": "Emissão", "description": "Data de emissão/faturamento (DATE)"},
            {"column": "Ano", "description": "Ano do faturamento (BIGINT)"},
            {"column": "Mês", "description": "Mês de referência"}
        ]
    },
    "usuarios": {
        "description": "Base de usuários de demonstração.",
        "key_columns": [
            {"column": "Cliente", "description": "Nome do cliente"},
            {"column": "bu", "description": "Unidade de Negócio"},
            {"column": "faturamento", "description": "Faturamento"}
        ]
    }
}

def format_schema_presentation() -> str:
    """Retorna uma apresentação formatada e amigável da estrutura do banco para o usuário."""
    lines = [
        "**Estrutura de Dados disponível no Milia AI (`banco.duckdb`):**",
        "",
        "**Tabela Principal:** `faturamento` — Base analítica com mais de 324 mil registros.",
        "",
        "**Principais dimensões autorizadas para análise:**",
        "- **Clientes:** `\"Nome Cliente\"`, `\"Cód. Cliente\"`, `\"CNPJ/CPF\"`",
        "- **Receita & Margem:** `\"Fat. Líquido\"` (Faturamento Líquido R$), `\"Margem Bruta (R$)\"`, `\"Margem Bruta (%)\"`, `\"Valor Contábil\"`, `\"Custo Médio Total\"`",
        "- **Produtos:** `\"PRODUTOS\"` (Linha do produto), `\"Desc. Produto\"`, `\"Desc. Familia\"`, `\"FAT - Quant.\"`",
        "- **Unidades de Negócio (BU):** `\"Business Unit\"` (`CORPORATIVO`, `VAREJO`, `SERVIÇOS`, `PME`, `PLATAFORMAS`, etc.)",
        "- **Geografia:** `\"Estado\"` (UF: SP, RS, RJ, MG...), `\"Município\"`, `\"Filial\"`",
        "- **Comercial:** `\"Nome Vendedor\"`, `\"Canal de Venda\"`, `\"Tipo de Venda\"`",
        "- **Temporal:** `\"Emissão\"` (Data), `\"Ano\"` (2020 a 2026), `\"Mês\"`, `\"Trimestre\"`",
        "",
        "*Exemplos de perguntas que posso responder:*",
        "- *'Qual o faturamento total por Unidade de Negócio?'*",
        "- *'Liste os 10 clientes com maior faturamento líquido.'*",
        "- *'Qual o total de faturamento e margem bruta por produto?'*",
        "- *'Quais estados têm maior volume de vendas?'*",
        "- *'Qual o faturamento do vendedor X?'*"
    ]
    return "\n".join(lines)
