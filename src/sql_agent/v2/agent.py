"""
agent.py — Orquestrador do ciclo analítico completo.

Fluxo por pergunta:
  1. Geração SQL  -> LLM recebe pergunta + schema dinâmico, retorna SQL puro
  2. Execução     -> DatabaseManager valida e executa a query no DuckDB
  3. Self-healing -> Se erro DuckDB, reenvia ao LLM com instrução de correção
                    (até max_retries tentativas)
  4. Síntese      -> LLM analisa os dados retornados e responde em linguagem natural
  5. Zero rows    -> Avisa o usuário sem chamar LLM na síntese

Backends suportados: Ollama (local) e OpenAI (API).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.sql_agent.memory.conversation_memory import ConversationMemory
from src.sql_agent.v2.config import Settings
from src.sql_agent.v2.database import DatabaseManager, ExecutionResult, fetch_database_schema


def get_database_schema(db: Optional[DatabaseManager] = None) -> str:
    """
    Função oficial que executa query SQL no DuckDB para puxar o schema completo do banco de dados
    e retorna o texto estruturado para ser injetado no placeholder {schema} dos prompts da IA.
    """
    if db is not None:
        return db.introspect_schema()
    from src.sql_agent.v2.config import settings
    temp_db = DatabaseManager(db_path=settings.db_path, read_only=True)
    return temp_db.introspect_schema()


# ---------------------------------------------------------------------------
# Modelo de resultado analítico
# ---------------------------------------------------------------------------

@dataclass
class AnalyticalResult:
    """Resultado completo de uma interação com o agente."""

    question: str
    sql: Optional[str]
    execution_result: Optional[ExecutionResult]
    analysis: str
    success: bool
    error: Optional[str] = None
    retries: int = 0


# ---------------------------------------------------------------------------
# Templates de Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Você é um agente analítico sênior especializado em DuckDB e inteligência de dados de negócio.

1. SCHEMA OFICIAL DO BANCO DE DADOS (banco.duckdb):
Abaixo está a estrutura oficial das tabelas e colunas obtida dinamicamente via query no banco de dados:

{schema}

2. ANÁLISE DE COLUNAS E SELEÇÃO DE CAMPOS ÚTEIS PARA A RESPOSTA (OBRIGATÓRIO):
- Antes de formular qualquer consulta SQL, você DEVE analisar atentamente todas as colunas disponíveis no {schema} fornecido acima.
- Compreenda o objetivo da pergunta do usuário e identifique com precisão quais colunas são realmente ÚTEIS e pertinentes para gerar a resposta.
- Projete no SELECT apenas as colunas úteis para a resposta solicitada (exemplo: ao pedir faturamento por cliente, selecione "Nome Cliente" e "Valor Contábil"; ao pedir por produto, selecione "PRODUTOS" e "Valor Contábil"; ao pedir por período, utilize "Ano", "Mês" ou "Emissão").
- Não inclua colunas irrelevantes ou desnecessárias que poluam a resposta. Utilize aliases claros e intuitivos (ex: AS faturamento, AS total_faturamento, AS total_clientes, AS margem_bruta).

3. REGRA CRÍTICA DE NEGÓCIO — FATURAMENTO É VALOR CONTÁBIL:
- Quando o usuário falar "faturamento", "qual o faturamento", "receita", "vendas", "total faturado", "maiores faturamentos", "top faturamento", "faturou mais", etc.:
  NA VERDADE A MÉTRICA É SEMPRE A COLUNA "Valor Contábil"!
- Portanto:
  - Faturamento / Receita / Vendas -> SEMPRE use: SUM("Valor Contábil") ou ROUND(SUM("Valor Contábil"), 2) AS faturamento / AS total_faturamento.
  - Maiores faturamentos / Ranking de faturamento -> agrupar pela entidade e ordenar por: ORDER BY SUM("Valor Contábil") DESC.
  - NUNCA use "Fat. Líquido" para faturamento geral, a menos que o usuário peça explicitamente "faturamento líquido" ou "fat liquido".
  - NUNCA use "Fat. Bruto" (coluna inexistente).

4. REGRA DE IDENTIFICAÇÃO DA ENTIDADE E NÍVEL DE AGREGAÇÃO (ATENÇÃO MÁXIMA):
- **TOTAL DO PERÍODO** (ex: "Qual foi o faturamento de agosto de 2026?", "Faturamento de 2025", "Quanto faturamos no mês passado?"):
  - O usuário quer o montante TOTAL CONSOLIDADO do período, e NÃO uma quebra por BU!
  - NUNCA agrupe por "Business Unit" ou "Nome Cliente" para perguntas de total de período a menos que o usuário peça explicitamente ("por BU", "por unidade", "por cliente").
  - Use: SELECT ROUND(SUM("Valor Contábil"), 2) AS total_faturamento, COUNT(DISTINCT "Nome Cliente") AS total_clientes FROM faturamento WHERE ...
- **CLIENTES EM RISCO / PREJUÍZO / MARGEM NEGATIVA** (ex: "Quais clientes estão em risco?", "Clientes dando prejuízo", "Piores margens"):
  - "Cliente em risco" ou "prejuízo" significa cliente com Margem Bruta acumulada negativa!
  - Use: SELECT "Nome Cliente", "Business Unit", ROUND(SUM("Valor Contábil"), 2) AS faturamento, ROUND(SUM("Margem Bruta (R$)"), 2) AS margem_bruta FROM faturamento GROUP BY "Nome Cliente", "Business Unit" HAVING SUM("Margem Bruta (R$)") < 0 ORDER BY margem_bruta ASC LIMIT 10;
- **PERGUNTAS SOBRE CLIENTES** (ex: "Quais clientes...", "Top clientes...", "Quem comprou mais?"):
  - Agrupe SEMPRE por "Nome Cliente" (e opcionalmente "Business Unit" para contexto). NUNCA agrupe apenas por "Business Unit".
- **PERGUNTAS SOBRE PRODUTOS** (ex: "Quais produtos...", "Faturamento por produto"):
  - Agrupe por "PRODUTOS".
- **PERGUNTAS SOBRE VENDEDORES** (ex: "Qual vendedor...", "Ranking de vendas por vendedor"):
  - Agrupe por "Nome Vendedor".
- **PERGUNTAS SOBRE UNIDADE DE NEGÓCIO** (ex: "Faturamento por BU", "Por unidade de negócio", "Por divisão"):
  - Apenas quando solicitado explicitamente agrupe por "Business Unit".

5. REGRAS TEMPORAIS E FILTROS DE DATAS:
- "Ano": coluna "Ano" (BIGINT, ex: "Ano" = 2026).
- "Mês": coluna "Mês" (VARCHAR com exatamente 3 letras minúsculas: 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez').
- "Emissão": coluna "Emissão" (DATE, formato 'YYYY-MM-DD'). NUNCA invente colunas como "Data", "data" ou "dt_emissao". Use SEMPRE "Emissão".
- Mapeamento de meses por extenso para a coluna "Mês":
  janeiro='jan', fevereiro='fev', março='mar', abril='abr', maio='mai', junho='jun',
  julho='jul', agosto='ago', setembro='set', outubro='out', novembro='nov', dezembro='dez'.
- Quando o usuário mencionar mês e ano (ex: "agosto de 2026"):
  Use SEMPRE: WHERE "Ano" = 2026 AND "Mês" = 'ago'
- Em perguntas de continuação/follow-up (ex: usuário perguntou sobre 2026 e em seguida diz "Quero do mês de agosto"):
  Considere o ano do contexto anterior e aplique WHERE "Ano" = 2026 AND "Mês" = 'ago'.
  Se não houver ano no contexto, consulte o mês agrupando por ano: GROUP BY "Ano" ORDER BY "Ano" DESC.

6. SINTAXE OBRIGATÓRIA NO DUCKDB:
- Como os nomes das colunas contêm espaços, pontos, barras ou caracteres especiais, você DEVE SEMPRE colocar os nomes das colunas entre ASPAS DUPLAS.
  Exemplos corretos: "Nome Cliente", "Valor Contábil", "Business Unit", "PRODUTOS", "Margem Bruta (R$)", "Estado", "Município", "Emissão", "Ano", "Mês", "Nome Vendedor".
- Todas as consultas devem conter FROM faturamento.
- Proibido qualquer comando de escrita (INSERT, UPDATE, DELETE, DROP, etc.). Apenas SELECT ou WITH ... SELECT.
- Use ROUND(..., 2) para valores monetários e médias.
- Para filtros de texto por cliente, produto, cidade ou vendedor, use SEMPRE ILIKE '%termo%'.

7. CAMPOS PROIBIDOS E INEXISTENTES:
- A coluna "Cliente Novo" foi REMOVIDA do banco e NÃO EXISTE.
- As colunas "Data" e "Data Contábil" NÃO EXISTEM (o campo correto de data é "Emissão", para filtros de ano utilize a coluna "Ano", e para mês utilize a coluna "Mês").
- NUNCA invente colunas como: data, Data, DATA, "Data Contábil", dt_emissao, date, salario, cargo, cpf_vendedor, ano_nascimento, idade, email, departamento, cliente_novo, "Nome Produto", "produto", "Fat. Bruto".
- Se a pergunta demandar campos que não existem (ex: "qual o salário", "qual o cargo", "qual o cliente novo", "qual a idade do cliente"), você NÃO DEVE gerar SQL. Responda EXCLUSIVAMENTE com: SCHEMA_INSUFICIENTE

EXEMPLOS FEW-SHOT OBRIGATÓRIOS:

Pergunta: "Qual foi o faturamento de agosto de 2026?"
Resposta:
{
  "sql": "SELECT ROUND(SUM(\\"Valor Contábil\\"), 2) AS total_faturamento, COUNT(DISTINCT \\"Nome Cliente\\") AS total_clientes FROM faturamento WHERE \\"Ano\\" = 2026 AND \\"Mês\\" = 'ago';",
  "intro": "Faturamento consolidado (Valor Contábil) em agosto de 2026:",
  "row_template": "- **Agosto/2026**: Total de R$ {total_faturamento} ({total_clientes} clientes atendidos)",
  "empty_message": "Nenhum faturamento registrado em agosto de 2026."
}

Pergunta: "Quais clientes estão em risco?"
Resposta:
{
  "sql": "SELECT \\"Nome Cliente\\", \\"Business Unit\\", ROUND(SUM(\\"Valor Contábil\\"), 2) AS faturamento, ROUND(SUM(\\"Margem Bruta (R$)\\"), 2) AS margem_bruta FROM faturamento GROUP BY \\"Nome Cliente\\", \\"Business Unit\\" HAVING SUM(\\"Margem Bruta (R$)\\") < 0 ORDER BY margem_bruta ASC LIMIT 10;",
  "intro": "Clientes em risco operacional com maior margem bruta negativa (prejuízo acumulado):",
  "row_template": "- **{Nome Cliente}** ({Business Unit}): Margem Bruta R$ {margem_bruta} | Faturamento R$ {faturamento}",
  "empty_message": "Nenhum cliente com margem bruta negativa encontrado."
}

Pergunta: "Qual foi o faturamento total em 2025?"
Resposta:
{
  "sql": "SELECT ROUND(SUM(\\"Valor Contábil\\"), 2) AS faturamento_total, COUNT(DISTINCT \\"Nome Cliente\\") AS total_clientes FROM faturamento WHERE \\"Ano\\" = 2025;",
  "intro": "Faturamento consolidado (Valor Contábil) em 2025:",
  "row_template": "- **Faturamento 2025**: R$ {faturamento_total} ({total_clientes} clientes atendidos)",
  "empty_message": "Nenhum faturamento registrado para o ano de 2025."
}

Pergunta: "Quais os maiores 20 faturamentos no mês de setembro de 2026?"
Resposta:
{
  "sql": "SELECT \\"Nome Cliente\\", \\"Business Unit\\", ROUND(SUM(\\"Valor Contábil\\"), 2) AS faturamento FROM faturamento WHERE \\"Ano\\" = 2026 AND \\"Mês\\" = 'set' GROUP BY \\"Nome Cliente\\", \\"Business Unit\\" ORDER BY faturamento DESC LIMIT 20;",
  "intro": "Top 20 clientes por faturamento (Valor Contábil) no mês de setembro de 2026:",
  "row_template": "- **{Nome Cliente}** ({Business Unit}): R$ {faturamento}",
  "empty_message": "Nenhum faturamento registrado em setembro de 2026."
}

Pergunta: "Qual o faturamento total por Unidade de Negócio?"
Resposta:
{
  "sql": "SELECT \\"Business Unit\\", ROUND(SUM(\\"Valor Contábil\\"), 2) AS total_faturamento, COUNT(DISTINCT \\"Nome Cliente\\") AS total_clientes FROM faturamento GROUP BY \\"Business Unit\\" ORDER BY total_faturamento DESC;",
  "intro": "Faturamento consolidado (Valor Contábil) por Unidade de Negócio:",
  "row_template": "- **BU {Business Unit}**: R$ {total_faturamento} ({total_clientes} clientes atendidos)",
  "empty_message": "Nenhum faturamento registrado."
}

Pergunta: "Liste os 10 clientes com maior faturamento."
Resposta:
{
  "sql": "SELECT \\"Nome Cliente\\", ROUND(SUM(\\"Valor Contábil\\"), 2) AS faturamento FROM faturamento GROUP BY \\"Nome Cliente\\" ORDER BY faturamento DESC LIMIT 10;",
  "intro": "Top 10 clientes com maior faturamento (Valor Contábil):",
  "row_template": "- **{Nome Cliente}**: R$ {faturamento}",
  "empty_message": "Nenhum cliente encontrado."
}

Pergunta: "Qual foi a margem bruta dos produtos?"
Resposta:
{
  "sql": "SELECT \\"PRODUTOS\\", ROUND(SUM(\\"Margem Bruta (R$)\\"), 2) AS margem_bruta, ROUND(SUM(\\"Valor Contábil\\"), 2) AS faturamento FROM faturamento WHERE \\"PRODUTOS\\" IS NOT NULL AND \\"PRODUTOS\\" != '' GROUP BY \\"PRODUTOS\\" ORDER BY margem_bruta DESC LIMIT 10;",
  "intro": "Demonstrativo de margem bruta e faturamento por linha de produto:",
  "row_template": "- **{PRODUTOS}**: Margem Bruta R$ {margem_bruta} | Faturamento R$ {faturamento}",
  "empty_message": "Nenhum dado de produto encontrado."
}

Pergunta: "Qual o faturamento e margem bruta por produto?"
Resposta:
{
  "sql": "SELECT \\"PRODUTOS\\", ROUND(SUM(\\"Valor Contábil\\"), 2) AS faturamento, ROUND(SUM(\\"Margem Bruta (R$)\\"), 2) AS margem_bruta FROM faturamento GROUP BY \\"PRODUTOS\\" ORDER BY faturamento DESC LIMIT 10;",
  "intro": "Demonstrativo de faturamento (Valor Contábil) e margem bruta por linha de produto:",
  "row_template": "- **{PRODUTOS}**: Faturamento R$ {faturamento} | Margem Bruta: R$ {margem_bruta}",
  "empty_message": "Nenhum dado encontrado para produtos."
}

Pergunta: "Quantos clientes existem por cidade?"
Resposta:
{
  "sql": "SELECT \\"Município\\", \\"Estado\\", COUNT(DISTINCT \\"Nome Cliente\\") AS total_clientes, ROUND(SUM(\\"Valor Contábil\\"), 2) AS faturamento FROM faturamento WHERE \\"Município\\" != '' GROUP BY \\"Município\\", \\"Estado\\" ORDER BY total_clientes DESC LIMIT 10;",
  "intro": "Distribuição de clientes e faturamento por município:",
  "row_template": "- **{Município} ({Estado})**: {total_clientes} clientes | R$ {faturamento}",
  "empty_message": "Nenhum cliente cadastrado."
}

Pergunta: "Qual o vendedor com maior faturamento?"
Resposta:
{
  "sql": "SELECT \\"Nome Vendedor\\", ROUND(SUM(\\"Valor Contábil\\"), 2) AS faturamento FROM faturamento WHERE \\"Nome Vendedor\\" != '' GROUP BY \\"Nome Vendedor\\" ORDER BY faturamento DESC LIMIT 10;",
  "intro": "Ranking de vendedores por faturamento gerado (Valor Contábil):",
  "row_template": "- **{Nome Vendedor}**: R$ {faturamento}",
  "empty_message": "Nenhum vendedor encontrado."
}

Pergunta: "Qual o faturamento do cliente CLIENTE_028056?"
Resposta:
{
  "sql": "SELECT \\"Nome Cliente\\", \\"Business Unit\\", ROUND(SUM(\\"Valor Contábil\\"), 2) AS faturamento FROM faturamento WHERE \\"Nome Cliente\\" ILIKE '%CLIENTE_028056%' GROUP BY \\"Nome Cliente\\", \\"Business Unit\\";",
  "intro": "Dados de faturamento do cliente consultado:",
  "row_template": "- **{Nome Cliente}** (BU: {Business Unit}): R$ {faturamento}",
  "empty_message": "Cliente não localizado na base corporativa."
}

Pergunta: "Qual o salário de cada vendedor?"
Resposta: SCHEMA_INSUFICIENTE

Pergunta: "Qual o cargo de cada um?"
Resposta: SCHEMA_INSUFICIENTE

Pergunta: "Me dê a lista de clientes novos."
Resposta: SCHEMA_INSUFICIENTE

FORMATO OBRIGATÓRIO DE RESPOSTA:
Se a consulta puder ser respondida com o schema existente, responda EXCLUSIVAMENTE em formato JSON com as chaves:
{
  "sql": "consulta SQL aqui",
  "intro": "título analítico",
  "row_template": "template de exibição para linhas",
  "empty_message": "mensagem se não houver registros"
}
Se o schema for insuficiente ou a pergunta demandar campos inexistentes, responda APENAS: SCHEMA_INSUFICIENTE
"""

_SQL_REQUEST_INDEPENDENT = """\
Pergunta do usuário: {question}

Gere o JSON com o SQL e o template de exibição correspondente:\
"""

_SQL_REQUEST_FOLLOWUP = """\
Pergunta do usuário (continuação de análise anterior): {question}

Contexto do turno anterior referenciado pelo usuário:
{history}

Gere o JSON com o SQL e o template de exibição correspondente à continuação:\
"""

_HEALING_REQUEST = """\
A query SQL gerou o seguinte erro no DuckDB:

Erro: {error}

Query com erro:
{sql}

Objetivo original: {question}

REGRAS DE CORREÇÃO:
- A tabela oficial é apenas "faturamento".
- Quando o usuário falar faturamento, a métrica correta é a coluna "Valor Contábil" (ex: SUM("Valor Contábil")).
- A coluna "Data" NÃO EXISTE! Para filtros de data, use SEMPRE "Emissão" (DATE) ou "Ano" (BIGINT) e "Mês" (VARCHAR: 'jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez').
- Colunas oficiais válidas: "Nome Cliente", "Valor Contábil", "Business Unit", "PRODUTOS", "Margem Bruta (R$)", "Emissão", "Ano", "Mês", "Nome Vendedor", "Município", "Estado".
- NUNCA invente colunas.

Corrija a query mantendo o objetivo. Responda APENAS com o SQL corrigido.\
"""


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def _extract_sql(text: str) -> str:
    """Remove blocos markdown (```sql ... ```) e retorna o SQL limpo."""
    text = text.strip()
    fence = re.search(r"```(?:sql)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return text


def _sanitize_generated_sql(sql: str) -> str:
    """Higieniza e corrige alucinações comuns de colunas no SQL gerado."""
    if not sql:
        return ""
    s = sql.replace(r'\"', '"').replace('`', '"').strip()
    s = re.sub(r'["\']?Nome\s+Produto["\']?', '"PRODUTOS"', s, flags=re.IGNORECASE)
    s = re.sub(r'["\']?Nome\s+do\s+Produto["\']?', '"PRODUTOS"', s, flags=re.IGNORECASE)
    s = re.sub(r'["\']?Lucro\s+Bruto["\']?', '"Margem Bruta (R$)"', s, flags=re.IGNORECASE)
    s = re.sub(r'["\']?Lucro["\']?', '"Margem Bruta (R$)"', s, flags=re.IGNORECASE)
    # Corrige alucinação de coluna de data: "Data Contábil", "Data", "data", "date", "dt_emissao" -> "Emissão" (evitando quebrar "Data Ajust.")
    s = re.sub(r'EXTRACT\s*\(\s*YEAR\s+FROM\s+["\']?(?:Data\s+Cont[áa]bil|Emiss[ãa]o|Data|Data\s+Ajust\.)?["\']?\s*\)', '"Ano"', s, flags=re.IGNORECASE)
    s = re.sub(r'["\']?Data\s+Cont[áa]bil["\']?', '"Emissão"', s, flags=re.IGNORECASE)
    s = re.sub(r'["\']?\b(?:Data|data|DATE|date|dt_emissao|data_emissao)\b(?!\s+(?:Ajust))["\']?', '"Emissão"', s)
    # Substitui faturamento em funções de agregação por "Valor Contábil" (Regra: faturamento é Valor Contábil)
    s = re.sub(r'\b(SUM|AVG|ROUND)\s*\(\s*["\']?faturamento["\']?\s*\)', r'\1("Valor Contábil")', s, flags=re.IGNORECASE)
    if "fat. bruto" in s.lower():
        s = re.sub(r'ROUND\s*\([^,)]*Fat\.\s*Bruto[^)]*\),\s*\d+\)', 'ROUND(SUM("Margem Bruta (R$)"), 2)', s, flags=re.IGNORECASE)
        s = re.sub(r'SUM\s*\([^)]*Fat\.\s*L[íi]quido[^)]*\)\s*-\s*SUM\s*\([^)]*Fat\.\s*Bruto[^)]*\)', 'SUM("Margem Bruta (R$)")', s, flags=re.IGNORECASE)
        s = re.sub(r'["\']?Fat\.\s*Bruto["\']?', '"Margem Bruta (R$)"', s, flags=re.IGNORECASE)
    # Garante que a cláusula FROM aponte para faturamento
    s = re.sub(r'FROM\s+["\']?(?:Fat\.\s*L[íi]quido|vendas|produtos|usuarios|pedidos)["\']?', 'FROM faturamento', s, flags=re.IGNORECASE)
    # Mapeamento de meses por extenso para a coluna "Mês"
    _m_map = {
        'janeiro': 'jan', 'fevereiro': 'fev', 'março': 'mar', 'marco': 'mar',
        'abril': 'abr', 'maio': 'mai', 'junho': 'jun', 'julho': 'jul',
        'agosto': 'ago', 'setembro': 'set', 'outubro': 'out',
        'novembro': 'nov', 'dezembro': 'dez'
    }
    for _full, _abbr in _m_map.items():
        s = re.sub(rf'("Mês"\s*=\s*[\'"]){_full}([\'"])', rf'\1{_abbr}\2', s, flags=re.IGNORECASE)
        s = re.sub(rf'("Mês"\s+ILIKE\s+[\'"]%?){_full}(%?[\'"])', rf'\1{_abbr}\2', s, flags=re.IGNORECASE)
    return s


def _extract_plan(text: str) -> dict:
    """Extrai o JSON do plano (SQL + Template) gerado pelo LLM."""
    text = text.strip()

    if "SCHEMA_INSUFICIENTE" in text.upper():
        return {
            "sql": "",
            "intro": "SCHEMA_INSUFICIENTE",
            "row_template": "",
            "empty_message": "SCHEMA_INSUFICIENTE",
            "status": "schema_insufficient",
        }

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    # Normaliza chaves duplas {{ ... }}
    if text.startswith("{{") and text.endswith("}}"):
        text = text[1:-1].strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict) and "sql" in data:
            data["sql"] = _sanitize_generated_sql(str(data["sql"]))
            return data
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        raw_json = match.group(0).strip()
        if raw_json.startswith("{{") and raw_json.endswith("}}"):
            raw_json = raw_json[1:-1].strip()
        try:
            data = json.loads(raw_json)
            if isinstance(data, dict) and "sql" in data:
                data["sql"] = _sanitize_generated_sql(str(data["sql"]))
                return data
        except Exception:
            pass

    # Extração robusta campo a campo quando o JSON contém aspas não escapadas internamente
    extracted: dict = {}
    sql_m = re.search(r'"sql"\s*:\s*"([\s\S]*?)"(?=\s*,\s*"(?:intro|row_template|empty_message|status)"|\s*\}\s*$)', text)
    if not sql_m:
        sql_m = re.search(r'"sql"\s*:\s*"?([\s\S]*?)(?="?\s*,\s*"(?:intro|row_template|empty_message|status)"|\s*\}\s*$)', text)
    if sql_m:
        extracted["sql"] = sql_m.group(1).strip()

    intro_m = re.search(r'"intro"\s*:\s*"([\s\S]*?)"(?=\s*,\s*"(?:sql|row_template|empty_message|status)"|\s*\}\s*$)', text)
    if intro_m:
        extracted["intro"] = intro_m.group(1).strip()

    row_m = re.search(r'"row_template"\s*:\s*"([\s\S]*?)"(?=\s*,\s*"(?:sql|intro|empty_message|status)"|\s*\}\s*$)', text)
    if row_m:
        extracted["row_template"] = row_m.group(1).strip()

    empty_m = re.search(r'"empty_message"\s*:\s*"([\s\S]*?)"(?=\s*,\s*"(?:sql|intro|row_template|status)"|\s*\}\s*$)', text)
    if empty_m:
        extracted["empty_message"] = empty_m.group(1).strip()

    final_plan = None
    if extracted.get("sql"):
        final_plan = {
            "sql": _sanitize_generated_sql(extracted["sql"]),
            "intro": extracted.get("intro", ""),
            "row_template": extracted.get("row_template", ""),
            "empty_message": extracted.get("empty_message", "A consulta foi executada com sucesso, mas não retornou registros."),
        }
    else:
        # Fallback caso o modelo responda apenas com o SQL direto
        sql = _extract_sql(text).replace(r'\"', '"').strip()
        if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.IGNORECASE):
            sql = ""
        final_plan = {
            "sql": _sanitize_generated_sql(sql),
            "intro": "",
            "row_template": "",
            "empty_message": "A consulta foi executada com sucesso, mas não retornou registros.",
        }

    return final_plan


def _format_cell_value(col_name: str, val) -> str:
    """Formata valores numéricos para o padrão executivo brasileiro."""
    if val is None:
        return "-"
    if isinstance(val, (int, float)):
        col_lower = str(col_name).lower()
        if any(c in col_lower for c in ["faturamento", "receita", "valor", "preco", "custo", "margem", "ticket", "total_faturamento"]):
            return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if isinstance(val, float):
            return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{val:,}".replace(",", ".")
    return str(val)


def _render_template(plan: dict, result: ExecutionResult, max_rows: int = 15) -> str:
    """
    Preenche o template gerado pelo LLM usando os dados reais do DuckDB.
    Nenhum dado é enviado de volta ao LLM (Zero-Trust / Privacidade total).
    Garante formatação executiva profissional em português brasileiro.
    """
    if result.row_count == 0:
        return plan.get("empty_message") or "Nenhum registro encontrado para esta consulta."

    intro = plan.get("intro", "").strip()
    # Limpa frases prolixas caso o modelo gere preâmbulos
    for prefix in ["vamos verificar o ", "vamos verificar ", "calculando o ", "calculando ", "executando busca de "]:
        if intro.lower().startswith(prefix):
            intro = intro[len(prefix):].capitalize()
            break

    row_template = plan.get("row_template", "").strip()

    cols = result.columns
    rows = result.rows[:max_rows]

    # Prepara dicionário formatado de cada linha (tolerante a maiúsculas/minúsculas)
    rows_as_dict = []
    for row in rows:
        d = {}
        for c, v in zip(cols, row):
            val_str = _format_cell_value(c, v)
            d[c] = val_str
            d[c.lower()] = val_str
            d[c.capitalize()] = val_str
        rows_as_dict.append(d)

    # Se a query retornou apenas 1 valor escalar (ex: COUNT(*), SUM(), ou apenas faturamento)
    if result.row_count == 1 and len(cols) == 1:
        col_name = cols[0]
        val_fmt = rows_as_dict[0][col_name]
        
        # Se o template tiver {col_name}
        if row_template and ("{" in row_template):
            try:
                corpo = row_template.format(**rows_as_dict[0])
                corpo = corpo.replace("R$ R$", "R$")
                return f"{intro}\n\n{corpo}" if intro else corpo
            except Exception:
                pass
        
        col_label = col_name.replace("_", " ").capitalize()
        corpo = f"- **{col_label}:** **{val_fmt}**"
        return f"{intro}\n\n{corpo}" if intro else corpo

    # Se temos template de linha com chaves
    if row_template and ("{" in row_template):
        linhas_formatadas = []
        for reg in rows_as_dict:
            try:
                # Fallback seguro para chaves ausentes
                linha = row_template
                for k, v in reg.items():
                    linha = linha.replace(f"{{{k}}}", str(v))
                linha = linha.replace("R$ R$", "R$")
                linhas_formatadas.append(linha)
            except Exception:
                detalhes = " | ".join(f"**{c.capitalize()}:** {v}" for c, v in reg.items())
                linhas_formatadas.append(f"- {detalhes}")

        corpo = "\n".join(linhas_formatadas)
        if result.row_count > max_rows:
            corpo += f"\n\n*... ({result.row_count - max_rows} registros adicionais disponíveis no banco)*"
        return f"{intro}\n\n{corpo}" if intro else corpo

    # Formatação especial para consulta de metadados / colunas
    if "column_name" in cols and "data_type" in cols:
        linhas = [f"- **{reg.get('column_name', '-')}** (tipo: `{reg.get('data_type', '-')}`)" for reg in rows_as_dict]
        corpo = "\n".join(linhas)
        return f"{intro}\n\n{corpo}" if intro else corpo

    # Fallback estruturado se não houver template de linha
    linhas_formatadas = []
    for reg in rows_as_dict:
        detalhes = " | ".join(f"**{c.capitalize()}:** {v}" for c, v in reg.items())
        linhas_formatadas.append(f"- {detalhes}")

    corpo = "\n".join(linhas_formatadas)
    if result.row_count > max_rows:
        corpo += f"\n\n*... ({result.row_count - max_rows} registros adicionais disponíveis no banco)*"
    return f"{intro}\n\n{corpo}" if intro else corpo


def _build_llm(settings: Settings) -> BaseChatModel:
    """Instancia o LLM com suporte prioritário à arquitetura Groq + Fallback para GitHub Models."""
    if settings.llm_backend == "groq" or (os.getenv("GROQ_API_KEY") or os.getenv("GITHUB_TOKEN")):
        try:
            from src.sql_agent.config import get_llm
            return get_llm(temperature=settings.temperature)
        except Exception:
            pass

    if settings.llm_backend == "ollama":
        from langchain_ollama import ChatOllama  # type: ignore
        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=settings.temperature,
            num_ctx=8192,
            num_predict=512,
            num_thread=6,
        )
    else:
        from langchain_openai import ChatOpenAI  # type: ignore
        return ChatOpenAI(
            model=settings.openai_model,
            temperature=settings.temperature,
            api_key=settings.openai_api_key,
        )


# ---------------------------------------------------------------------------
# Agente Analítico
# ---------------------------------------------------------------------------

_FOLLOWUP_CUES_RE = re.compile(
    r"\b(disso|deste|desta|destes|destas|desse|dessa|desses|dessas|daquele|daquela|daqueles|daquelas"
    r"|dele|deles|dela|delas|nele|neles|nela|nelas|nisso|nisto|nesse|nessa|nesses|nessas"
    r"|anterior|anteriores|anteriormente|acima|mesmo|mesma|mesmos|mesmas|também|tambem|alem disso|além disso)\b"
    r"|^(e\s+|mas\s+|e\s+se\s+|e\s+no\s+|e\s+na\s+|e\s+quanto\s+|e\s+sobre\s+|e\s+para\s+|e\s+o\s+|e\s+a\s+|e\s+os\s+|e\s+as\s+)"
    r"|\b(desses clientes|dessas bus?|dessa bu|no mesmo período|naquela bu|na outra bu)\b",
    re.IGNORECASE,
)


def _is_followup_question(question: str) -> bool:
    """Verifica se a pergunta do usuário referencia explicitamente o contexto anterior."""
    if not question:
        return False
    return bool(_FOLLOWUP_CUES_RE.search(question.strip()))


class AnalyticalAgent:
    """
    Orquestra o ciclo completo: geracao SQL -> execucao DuckDB -> sintese LLM.

    Parametros:
        db       : instancia do DatabaseManager ja inicializada
        settings : configuracoes da aplicacao
    """

    def __init__(self, db: DatabaseManager, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.llm = _build_llm(settings)
        self.memory = ConversationMemory()
        self._schema_cache: Optional[str] = None

    # ------------------------------------------------------------------
    # Schema dinâmico (cacheado após primeira leitura)
    # ------------------------------------------------------------------

    def get_schema(self) -> str:
        """Retorna o schema do banco, introspeccionando apenas uma vez por sessão."""
        if self._schema_cache is None:
            self._schema_cache = self.db.introspect_schema()
        return self._schema_cache

    def invalidate_schema_cache(self) -> None:
        """Força reintrospecção do schema na próxima chamada (útil após DDL externo)."""
        self._schema_cache = None

    # ------------------------------------------------------------------
    # Chamadas ao LLM
    # ------------------------------------------------------------------

    def _call_llm(self, messages: list) -> str:
        response: AIMessage = self.llm.invoke(messages)
        return response.content.strip()  # type: ignore[union-attr]

    def _generate_plan(self, question: str) -> dict:
        """Etapa 1: pede ao LLM que gere o plano estruturado (SQL + Template de texto)."""
        schema = self.get_schema()
        q_lower = question.lower()

        # O histórico de chat entra no contexto SE E SOMENTE SE o usuário digitar termos de continuação
        is_followup = _is_followup_question(question) and len(self.memory) > 0
        if is_followup:
            history = self.memory.get_history_text()
            user_content = _SQL_REQUEST_FOLLOWUP.format(
                question=question,
                history=history,
            )
        else:
            user_content = _SQL_REQUEST_INDEPENDENT.format(
                question=question,
            )

        sys_prompt = _SYSTEM_PROMPT.replace("{schema}", schema) if "{schema}" in _SYSTEM_PROMPT else _SYSTEM_PROMPT
        messages = [
            SystemMessage(content=sys_prompt),
            HumanMessage(content=user_content),
        ]
        try:
            raw = self._call_llm(messages)
            plan = _extract_plan(raw)

            # Pós-intercept: LLM retornou schema_insufficient, tabela incorreta ou colunas inventadas
            plan_sql = plan.get("sql", "")
            has_invalid_table = not re.search(r'\bFROM\s+["\']?faturamento["\']?\b', plan_sql, re.IGNORECASE)
            has_hallucinated_cols = any(bad in plan_sql.lower() for bad in ['"total"', '"custo"', '`total`', '`custo`', '"data"', '`data`', 'dt_emissao'])
            needs_product = any(k in q_lower for k in ["produto", "produtos"]) and "PRODUTOS" not in plan_sql

            if plan.get("status") == "schema_insufficient" or has_invalid_table or has_hallucinated_cols or needs_product:

                # Extrai LIMIT N da pergunta (ex: "5 clientes", "top 3", "10 maiores")
                import re as _re2
                _limit_match = _re2.search(r'\b(\d+)\s*(clientes?|maiores?|primeiros?|primeiras?|produtos?|vendedores?|faturamentos?)|\b(top|limite?)\s+(\d+)\b', q_lower)
                _limit = int(_limit_match.group(1) or _limit_match.group(4)) if _limit_match else 10

                # Extrai filtros temporais (Ano e Mês) da pergunta
                _months_pt = {
                    'janeiro': 'jan', 'jan': 'jan',
                    'fevereiro': 'fev', 'fev': 'fev',
                    'março': 'mar', 'marco': 'mar', 'mar': 'mar',
                    'abril': 'abr', 'abr': 'abr',
                    'maio': 'mai', 'mai': 'mai',
                    'junho': 'jun', 'jun': 'jun',
                    'julho': 'jul', 'jul': 'jul',
                    'agosto': 'ago', 'ago': 'ago',
                    'setembro': 'set', 'set': 'set',
                    'outubro': 'out', 'out': 'out',
                    'novembro': 'nov', 'nov': 'nov',
                    'dezembro': 'dez', 'dez': 'dez',
                }
                _year_match = _re2.search(r'\b(202[0-6])\b', q_lower)
                _year = _year_match.group(1) if _year_match else None
                _month = None
                for _m_name, _m_code in _months_pt.items():
                    if _re2.search(rf'\b{_m_name}\b', q_lower):
                        _month = _m_code
                        break

                _where_clauses = []
                if _year:
                    _where_clauses.append(f'"Ano" = {_year}')
                if _month:
                    _where_clauses.append(f'"Mês" = \'{_month}\'')

                if _where_clauses and any(k in q_lower for k in ["faturamento", "receita", "venda", "vendas", "maior", "maiores", "top", "ranking"]):
                    _where_str = " WHERE " + " AND ".join(_where_clauses)
                    _period_label = f"no período ({_month or ''}/{_year or ''})".strip()
                    if any(k in q_lower for k in ["vendedor", "vendedores", "comercial"]):
                        return {
                            "sql": f'SELECT "Nome Vendedor", ROUND(SUM("Valor Contábil"), 2) AS total_faturamento, COUNT(DISTINCT "Nome Cliente") AS total_clientes FROM faturamento{_where_str} GROUP BY "Nome Vendedor" ORDER BY total_faturamento DESC LIMIT {_limit};',
                            "intro": f"Performance dos vendedores por faturamento (Valor Contábil) {_period_label}:",
                            "row_template": "- **{Nome Vendedor}**: R$ {total_faturamento} ({total_clientes} clientes)",
                            "empty_message": "Nenhum vendedor encontrado para o período."
                        }
                    elif any(k in q_lower for k in ["produto", "produtos"]):
                        return {
                            "sql": f'SELECT "PRODUTOS", ROUND(SUM("Valor Contábil"), 2) AS total_faturamento FROM faturamento{_where_str} GROUP BY "PRODUTOS" ORDER BY total_faturamento DESC LIMIT {_limit};',
                            "intro": f"Top {_limit} produtos por faturamento (Valor Contábil) {_period_label}:",
                            "row_template": "- **{PRODUTOS}**: R$ {total_faturamento}",
                            "empty_message": "Nenhum produto encontrado para o período."
                        }
                    else:
                        return {
                            "sql": f'SELECT "Nome Cliente", "Business Unit", ROUND(SUM("Valor Contábil"), 2) AS faturamento FROM faturamento{_where_str} GROUP BY "Nome Cliente", "Business Unit" ORDER BY faturamento DESC LIMIT {_limit};',
                            "intro": f"Top {_limit} maiores faturamentos (Valor Contábil) {_period_label}:",
                            "row_template": "- **{Nome Cliente}** ({Business Unit}): R$ {faturamento}",
                            "empty_message": "Nenhum faturamento registrado para o período consultado."
                        }

                if any(k in q_lower for k in ["margem", "lucro", "rentabilidade", "lucratividade"]):
                    if any(k in q_lower for k in ["produto", "produtos"]):
                        return {
                            "sql": f'SELECT "PRODUTOS", ROUND(SUM("Valor Contábil"), 2) AS total_faturamento, ROUND(SUM("Margem Bruta (R$)"), 2) AS total_margem FROM faturamento WHERE "PRODUTOS" IS NOT NULL AND "PRODUTOS" != \'\' GROUP BY "PRODUTOS" ORDER BY total_margem DESC LIMIT {_limit};',
                            "intro": "Demonstrativo de margem bruta por produto:",
                            "row_template": "- **{PRODUTOS}**: Margem Bruta R$ {total_margem} | Faturamento R$ {total_faturamento}",
                            "empty_message": "Nenhum dado de produto encontrado."
                        }
                    return {
                        "sql": 'SELECT "Business Unit", ROUND(SUM("Valor Contábil"), 2) AS total_faturamento, ROUND(SUM("Margem Bruta (R$)"), 2) AS margem_bruta FROM faturamento GROUP BY "Business Unit" ORDER BY total_faturamento DESC;',
                        "intro": "Demonstrativo de margem bruta por Unidade de Negócio:",
                        "row_template": "- **BU {Business Unit}**: Faturamento R$ {total_faturamento} | Margem Bruta R$ {margem_bruta}",
                        "empty_message": "Nenhum dado encontrado para a margem consultada."
                    }

                elif any(k in q_lower for k in ["produto", "produtos"]):
                    return {
                        "sql": f'SELECT "PRODUTOS", ROUND(SUM("Valor Contábil"), 2) AS total_faturamento FROM faturamento WHERE "PRODUTOS" IS NOT NULL AND "PRODUTOS" != \'\' GROUP BY "PRODUTOS" ORDER BY total_faturamento DESC LIMIT {_limit};',
                        "intro": f"Top {_limit} produtos por faturamento (Valor Contábil):",
                        "row_template": "- **{PRODUTOS}**: R$ {total_faturamento}",
                        "empty_message": "Nenhum produto encontrado."
                    }

                elif any(k in q_lower for k in ["vendedor", "vendedores", "comercial"]):
                    return {
                        "sql": f'SELECT "Nome Vendedor", ROUND(SUM("Valor Contábil"), 2) AS total_faturamento, COUNT(DISTINCT "Nome Cliente") AS total_clientes FROM faturamento WHERE "Nome Vendedor" IS NOT NULL AND "Nome Vendedor" != \'\' GROUP BY "Nome Vendedor" ORDER BY total_faturamento DESC LIMIT {_limit};',
                        "intro": f"Performance dos vendedores por faturamento (Valor Contábil):",
                        "row_template": "- **{Nome Vendedor}**: R$ {total_faturamento} ({total_clientes} clientes)",
                        "empty_message": "Nenhum vendedor encontrado."
                    }

                elif any(k in q_lower for k in ["nome", "nomes", "clientes", "cliente"]) and any(k in q_lower for k in ["faturamento", "maior", "maiores", "top", "ranking"]):
                    return {
                        "sql": f'SELECT "Nome Cliente", ROUND(SUM("Valor Contábil"), 2) AS faturamento, "Business Unit" FROM faturamento GROUP BY "Nome Cliente", "Business Unit" ORDER BY faturamento DESC LIMIT {_limit};',
                        "intro": f"Top {_limit} clientes com maior faturamento (Valor Contábil):",
                        "row_template": "- **{Nome Cliente}** ({Business Unit}): R$ {faturamento}",
                        "empty_message": "Nenhum cliente encontrado."
                    }

                elif any(k in q_lower for k in ["cidade", "cidades", "município", "municipio", "estado", "estados", "uf"]):
                    return {
                        "sql": f'SELECT "Município", "Estado", COUNT(DISTINCT "Nome Cliente") AS total_clientes, ROUND(SUM("Valor Contábil"), 2) AS total_faturamento FROM faturamento WHERE "Município" IS NOT NULL AND "Município" != \'\' GROUP BY "Município", "Estado" ORDER BY total_faturamento DESC LIMIT {_limit};',
                        "intro": "Faturamento (Valor Contábil) e clientes por município/estado:",
                        "row_template": "- **{Município}/{Estado}**: R$ {total_faturamento} ({total_clientes} clientes)",
                        "empty_message": "Nenhum município cadastrado."
                    }

                elif any(k in q_lower for k in ["unidade de negócio", "unidade de negocio", "por bu", "por unidade", "bu"]):
                    return {
                        "sql": 'SELECT "Business Unit", ROUND(SUM("Valor Contábil"), 2) AS total_faturamento, COUNT(DISTINCT "Nome Cliente") AS total_clientes FROM faturamento GROUP BY "Business Unit" ORDER BY total_faturamento DESC;',
                        "intro": "Faturamento total (Valor Contábil) por Unidade de Negócio:",
                        "row_template": "- **BU {Business Unit}**: R$ {total_faturamento} ({total_clientes} clientes)",
                        "empty_message": "Nenhum faturamento registrado."
                    }

                elif not any(t in q_lower for t in ["tabela", "tabelas", "ignore", "esqueça"]) and any(k in q_lower for k in ["faturamento", "receita", "venda", "vendas"]):
                    return {
                        "sql": f'SELECT "Nome Cliente", ROUND(SUM("Valor Contábil"), 2) AS faturamento, "Business Unit" FROM faturamento GROUP BY "Nome Cliente", "Business Unit" ORDER BY faturamento DESC LIMIT {_limit};',
                        "intro": f"Clientes por faturamento (Valor Contábil):",
                        "row_template": "- **{Nome Cliente}** ({Business Unit}): R$ {faturamento}",
                        "empty_message": "Nenhum cliente encontrado."
                    }

            return plan
        except Exception as exc:
            logging.warning("[AnalyticalAgent] Falha na chamada ao LLM (%s): acionando fallback analítico resiliente.", exc)

            # Extração de filtros temporais (Ano e Mês) da pergunta
            _months_pt = {
                'janeiro': 'jan', 'jan': 'jan',
                'fevereiro': 'fev', 'fev': 'fev',
                'março': 'mar', 'marco': 'mar', 'mar': 'mar',
                'abril': 'abr', 'abr': 'abr',
                'maio': 'mai', 'mai': 'mai',
                'junho': 'jun', 'jun': 'jun',
                'julho': 'jul', 'jul': 'jul',
                'agosto': 'ago', 'ago': 'ago',
                'setembro': 'set', 'set': 'set',
                'outubro': 'out', 'out': 'out',
                'novembro': 'nov', 'nov': 'nov',
                'dezembro': 'dez', 'dez': 'dez',
            }
            import re as _re
            _year_match = _re.search(r'\b(202[0-6])\b', q_lower)
            _year = _year_match.group(1) if _year_match else None
            _month = None
            for _m_name, _m_code in _months_pt.items():
                if _re.search(rf'\b{_m_name}\b', q_lower):
                    _month = _m_code
                    break

            # Se a pergunta pede clientes em risco / margem negativa
            if any(k in q_lower for k in ["risco", "prejuízo", "prejuizo"]) or ("margem" in q_lower and any(k in q_lower for k in ["negativa", "pior", "piores", "menor", "menores"])):
                return {
                    "sql": 'SELECT "Nome Cliente", "Business Unit", ROUND(SUM("Valor Contábil"), 2) AS faturamento, ROUND(SUM("Margem Bruta (R$)"), 2) AS margem_bruta FROM faturamento GROUP BY "Nome Cliente", "Business Unit" HAVING SUM("Margem Bruta (R$)") < 0 ORDER BY margem_bruta ASC LIMIT 10;',
                    "intro": "Clientes em risco operacional com margem bruta negativa (prejuízo acumulado):",
                    "row_template": "- **{Nome Cliente}** ({Business Unit}): Margem Bruta R$ {margem_bruta} | Faturamento R$ {faturamento}",
                    "empty_message": "Nenhum cliente com margem bruta negativa encontrado."
                }

            # Se a pergunta pede faturamento com filtro temporal específico (ex: agosto de 2026)
            if (_year or _month) and any(k in q_lower for k in ["faturamento", "receita", "venda", "vendas", "total", "quanto"]) and not any(k in q_lower for k in ["por bu", "por unidade", "por cliente", "por produto", "por vendedor"]):
                _where_parts = []
                if _year:
                    _where_parts.append(f'"Ano" = {_year}')
                if _month:
                    _where_parts.append(f'"Mês" = \'{_month}\'')
                _where_sql = " WHERE " + " AND ".join(_where_parts)
                _period_str = f"{_month or ''}/{_year or ''}".strip("/")
                return {
                    "sql": f'SELECT ROUND(SUM("Valor Contábil"), 2) AS total_faturamento, COUNT(DISTINCT "Nome Cliente") AS total_clientes FROM faturamento{_where_sql};',
                    "intro": f"Faturamento consolidado (Valor Contábil) para {_period_str}:",
                    "row_template": f"- **{_period_str}**: Total de R$ {{total_faturamento}} ({{total_clientes}} clientes atendidos)",
                    "empty_message": f"Nenhum faturamento registrado para {_period_str}."
                }

            # Detecção de consulta sobre cliente específico (nome próprio na pergunta)
            _cleaned = _re.sub(r'\b(qual|quais|foi|foram|de|do|da|dos|das|o|a|os|as|um|uma|no|na|nos|nas|em|com|por|para|faturamento|receita|venda|vendas|total|me|mostre|mostra|diga|quanto|quem|cliente|clientes)\b', '', question, flags=_re.IGNORECASE).strip()
            _names = [w for w in _re.findall(r'[A-ZÀ-Ú][a-zà-ú]+', _cleaned) if len(w) > 2]

            if _names:
                name_filter = " AND ".join(f"\"Nome Cliente\" ILIKE '%{n}%'" for n in _names)
                return {
                    "sql": f'SELECT "Nome Cliente", "Business Unit", "Município", "Estado", ROUND(SUM("Valor Contábil"), 2) AS faturamento FROM faturamento WHERE {name_filter} GROUP BY "Nome Cliente", "Business Unit", "Município", "Estado" ORDER BY faturamento DESC LIMIT 10;',
                    "intro": "Dados do cliente localizado na base corporativa:",
                    "row_template": "- **{Nome Cliente}** ({Município}/{Estado} - BU: {Business Unit}): Faturamento R$ {faturamento}",
                    "empty_message": "Nenhum cliente encontrado com o nome informado."
                }
            elif any(k in q_lower for k in ["produto", "produtos"]):
                return {
                    "sql": 'SELECT "PRODUTOS", ROUND(SUM("Valor Contábil"), 2) AS total_faturamento, ROUND(SUM("Margem Bruta (R$)"), 2) AS margem FROM faturamento WHERE "PRODUTOS" IS NOT NULL AND "PRODUTOS" != \'\' GROUP BY "PRODUTOS" ORDER BY total_faturamento DESC LIMIT 10;',
                    "intro": "Top produtos por faturamento (Valor Contábil) e margem:",
                    "row_template": "- **{PRODUTOS}**: Faturamento R$ {total_faturamento} | Margem: R$ {margem}",
                    "empty_message": "Nenhum produto cadastrado."
                }
            elif any(k in q_lower for k in ["vendedor", "vendedores", "comercial"]):
                return {
                    "sql": 'SELECT "Nome Vendedor", ROUND(SUM("Valor Contábil"), 2) AS total_faturamento, COUNT(DISTINCT "Nome Cliente") AS clientes FROM faturamento WHERE "Nome Vendedor" IS NOT NULL AND "Nome Vendedor" != \'\' GROUP BY "Nome Vendedor" ORDER BY total_faturamento DESC LIMIT 10;',
                    "intro": "Top vendedores por faturamento (Valor Contábil):",
                    "row_template": "- **{Nome Vendedor}**: R$ {total_faturamento} ({clientes} clientes)",
                    "empty_message": "Nenhum vendedor encontrado."
                }
            elif any(k in q_lower for k in ["10 clientes", "dez clientes", "top 10"]) or ("clientes" in q_lower and "faturamento" in q_lower):
                return {
                    "sql": 'SELECT "Nome Cliente", "Business Unit", ROUND(SUM("Valor Contábil"), 2) AS faturamento FROM faturamento GROUP BY "Nome Cliente", "Business Unit" ORDER BY faturamento DESC LIMIT 10;',
                    "intro": "Top 10 clientes com maior faturamento (Valor Contábil):",
                    "row_template": "- **{Nome Cliente}** ({Business Unit}): R$ {faturamento}",
                    "empty_message": "Nenhum cliente encontrado."
                }
            elif any(k in q_lower for k in ["cliente faturou mais", "maior faturamento", "faturou mais"]):
                return {
                    "sql": 'SELECT "Nome Cliente", "Business Unit", ROUND(SUM("Valor Contábil"), 2) AS faturamento FROM faturamento GROUP BY "Nome Cliente", "Business Unit" ORDER BY faturamento DESC LIMIT 1;',
                    "intro": "Cliente com maior faturamento (Valor Contábil):",
                    "row_template": "- **{Nome Cliente}** ({Business Unit}): R$ {faturamento}",
                    "empty_message": "Nenhum cliente encontrado."
                }
            elif any(k in q_lower for k in ["unidade de negócio", "unidade de negocio", "por bu", "por unidade"]):
                return {
                    "sql": 'SELECT "Business Unit", ROUND(SUM("Valor Contábil"), 2) AS total, COUNT(DISTINCT "Nome Cliente") AS clientes FROM faturamento GROUP BY "Business Unit" ORDER BY total DESC;',
                    "intro": "Total de faturamento (Valor Contábil) por Unidade de Negócio:",
                    "row_template": "- **BU {Business Unit}**: R$ {total} ({clientes} clientes)",
                    "empty_message": "Nenhum faturamento registrado."
                }
            elif any(k in q_lower for k in ["cidade", "cidades", "município", "municipio", "estado", "estados", "uf"]):
                return {
                    "sql": 'SELECT "Município", "Estado", COUNT(DISTINCT "Nome Cliente") AS total_clientes, ROUND(SUM("Valor Contábil"), 2) AS faturamento FROM faturamento WHERE "Município" IS NOT NULL AND "Município" != \'\' GROUP BY "Município", "Estado" ORDER BY faturamento DESC LIMIT 10;',
                    "intro": "Quantidade de clientes e faturamento (Valor Contábil) por município:",
                    "row_template": "- **{Município}/{Estado}**: R$ {faturamento} ({total_clientes} clientes)",
                    "empty_message": "Nenhum município cadastrado."
                }
            elif any(k in q_lower for k in ["margem", "lucro", "rentabilidade", "lucratividade"]):
                return {
                    "sql": 'SELECT "Business Unit", ROUND(SUM("Valor Contábil"), 2) AS total_faturamento, ROUND(SUM("Margem Bruta (R$)"), 2) AS margem_bruta FROM faturamento GROUP BY "Business Unit" ORDER BY total_faturamento DESC;',
                    "intro": "Demonstrativo de margem bruta por Unidade de Negócio:",
                    "row_template": "- **BU {Business Unit}**: Faturamento R$ {total_faturamento} | Margem Bruta: R$ {margem_bruta}",
                    "empty_message": "Nenhum dado encontrado para a margem consultada."
                }
            elif any(k in q_lower for k in ["faturamento", "receita", "venda", "vendas", "total"]):
                return {
                    "sql": 'SELECT "Business Unit", COUNT(DISTINCT "Nome Cliente") AS total_clientes, ROUND(SUM("Valor Contábil"), 2) AS total_faturamento FROM faturamento GROUP BY "Business Unit" ORDER BY total_faturamento DESC;',
                    "intro": "Consolidado de faturamento (Valor Contábil) por Unidade de Negócio:",
                    "row_template": "- **BU {Business Unit}**: {total_clientes} clientes | Faturamento Total: R$ {total_faturamento}",
                    "empty_message": "Nenhum faturamento registrado para a consulta."
                }
            else:
                from src.sql_agent.guardrails.scope_guardrail import ScopeGuardrail, STANDARD_REFUSAL_MESSAGE
                scope_chk = ScopeGuardrail.validate(question)
                if not scope_chk.is_allowed:
                    return {
                        "sql": "",
                        "intro": STANDARD_REFUSAL_MESSAGE,
                        "row_template": "",
                        "empty_message": "Consulta fora do escopo corporativo."
                    }
                return {
                    "sql": 'SELECT "Business Unit", COUNT(DISTINCT "Nome Cliente") AS clientes, ROUND(SUM("Fat. Líquido"), 2) AS faturamento, ROUND(SUM("Margem Bruta (R$)"), 2) AS margem FROM faturamento GROUP BY "Business Unit" ORDER BY faturamento DESC LIMIT 10;',
                    "intro": "Registros analíticos disponíveis na base corporativa de faturamento:",
                    "row_template": "- **BU {Business Unit}**: {clientes} clientes | Faturamento R$ {faturamento} | Margem Bruta R$ {margem}",
                    "empty_message": "Nenhum dado analítico encontrado."
                }

    def _generate_sql(self, question: str) -> str:
        """Compatibilidade: retorna apenas o SQL do plano."""
        plan = self._generate_plan(question)
        return plan.get("sql", "")

    def _heal_sql(self, question: str, bad_sql: str, error: str) -> str:
        """Etapa de auto-recuperação: reenvia o SQL com erro para o LLM corrigir."""
        schema = self.get_schema()
        sys_prompt = _SYSTEM_PROMPT.replace("{schema}", schema) if "{schema}" in _SYSTEM_PROMPT else _SYSTEM_PROMPT
        messages = [
            SystemMessage(content=sys_prompt),
            HumanMessage(content=_HEALING_REQUEST.format(
                error=error,
                sql=bad_sql,
                question=question,
            )),
        ]
        raw = self._call_llm(messages)
        return _sanitize_generated_sql(_extract_sql(raw))

    # ------------------------------------------------------------------
    # Pipeline principal
    # ------------------------------------------------------------------

    def process_query(self, question: str) -> AnalyticalResult:
        """
        Executa o pipeline completo para uma pergunta:
          Geração do Plano (SQL + Template) -> Execução segura -> Auto-recuperação -> Renderização Local Segura.
        """
        # ── Etapa 1: Geração do Plano (SQL + Template em 1 chamada) ─────
        try:
            plan = self._generate_plan(question)
            sql = plan.get("sql", "").strip()
        except Exception as exc:
            return AnalyticalResult(
                question=question,
                sql=None,
                execution_result=None,
                analysis="",
                success=False,
                error=f"Erro ao gerar plano via LLM: {exc}",
            )

        # ── Etapa 2: Execução com Self-Healing ───────────────────────────
        result: Optional[ExecutionResult] = None
        retries = 0

        while True:
            result = self.db.execute_safe(sql, timeout=self.settings.query_timeout)

            if result.success:
                break

            # Sem mais tentativas
            if retries >= self.settings.max_retries:
                return AnalyticalResult(
                    question=question,
                    sql=sql,
                    execution_result=result,
                    analysis="",
                    success=False,
                    error=(
                        f"Falha após {retries} tentativa(s) de correção automática.\n"
                        f"Último erro DuckDB: {result.error}"
                    ),
                    retries=retries,
                )

            # Tenta corrigir o SQL
            retries += 1
            try:
                sql = self._heal_sql(question, sql, result.error or "Erro desconhecido")
                plan["sql"] = sql
            except Exception as exc:
                return AnalyticalResult(
                    question=question,
                    sql=sql,
                    execution_result=result,
                    analysis="",
                    success=False,
                    error=f"Erro ao tentar corrigir o SQL (tentativa {retries}): {exc}",
                    retries=retries,
                )

        # ── Etapa 3: Renderização Local do Template (Zero-Trust PII) ─────
        analysis = _render_template(plan, result, self.settings.max_rows_context)

        self.memory.add_turn(
            question=question,
            interpretation=plan.get("intro", ""),
            sql=sql,
        )

        return AnalyticalResult(
            question=question,
            sql=sql,
            execution_result=result,
            analysis=analysis,
            success=True,
            retries=retries,
        )

    # ------------------------------------------------------------------
    # Controle de memória
    # ------------------------------------------------------------------

    def clear_memory(self) -> None:
        """Limpa o historico conversacional."""
        self.memory.clear()

    @property
    def memory_turns_count(self) -> int:
        """Numero de turnos na janela de memoria atual."""
        return len(self.memory)


