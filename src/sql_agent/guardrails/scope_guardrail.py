"""
scope_guardrail.py — Guardrail de Validação de Escopo Estrito e Proteção contra Prompt Injection.

Regras Obrigatórias:
1. Bloqueia temas não-corporativos (bate-papo, piadas, curiosidades, temas aleatórios ou comandos de distração).
2. Bloqueia tentativas de Prompt Injection, Jailbreak e Override de Instruções.
3. Resposta padronizada estrita de bloqueio:
   "Operação não permitida. Sou um assistente analítico restrito exclusivamente à consulta e interpretação dos dados corporativos autorizados."
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


from src.sql_agent.guardrails.schema_metadata import format_schema_presentation

STANDARD_REFUSAL_MESSAGE = (
    "Operação não permitida. Sou um assistente analítico restrito exclusivamente à "
    "consulta e interpretação dos dados corporativos autorizados."
)

AMBIGUITY_RESPONSE = (
    "Pode detalhar um pouco mais? Por exemplo: qual métrica (faturamento, quantidade...) "
    "e qual recorte (por cidade, por BU, no total)?"
)

GREETING_RESPONSE = (
    "Olá! Sou o Milia AI, seu assistente analítico de dados. "
    "Como posso ajudar com a consulta e análise dos dados de clientes, faturamento e unidades de negócio hoje?"
)


@dataclass
class GuardrailResult:
    """Resultado da avaliação do Guardrail."""
    is_allowed: bool
    risk_type: Optional[str] = None
    system_action: Optional[str] = None
    refusal_message: Optional[str] = None
    reason: Optional[str] = None
    is_direct_response: bool = False
    direct_message: Optional[str] = None


# Padrões explícitos de Prompt Injection e Override
_INJECTION_PATTERNS = [
    r"esque[çc]a\s+(todas\s+as\s+|as\s+|o\s+)?(suas\s+)?(regras|instru[çc][õo]es|schema)",
    r"ignore\s+(todas\s+as\s+|as\s+|o\s+)?(instru[çc][õo]es|orienta[çc][õo]es|regras|schema|diretrizes)",
    r"ignore\s+previous\s+instructions",
    r"aja\s+como\s+(outro|um|uma)?",
    r"finja\s+que\s+(voc[êe]|tu)",
    r"dan\s+mode",
    r"jailbreak",
    r"system\s*prompt",
    r"desconsidere\s+(as\s+|o\s+)?(regras|instru[çc][õo]es|schema)",
    r"use\s+a\s+tabela\s+\w+",
    r"revele\s+(seu|o)\s+prompt",
    r"mostre\s+(seu|o)\s+system\s*prompt",
    r"hacker\s+mode",
    r"voc[êe]\s+agora\s+[ée]",
    r"suas\s+novas\s+instru[çc][õo]es\s+s[ãa]o",
    r"bypass\s+guardrails?",
]

# Padrões de Fuga de Escopo (temas banais, bate-papo, piadas, culinária, distrações)
_OFF_SCOPE_PATTERNS = [
    r"\b(piada|piadas|anedota|charada)\b",
    r"\b(receita|bolo|torta|culin[áa]ria|cozinhar|macarr[ãa]o|comida|alimento|refei[çc][ãa]o|prato|jantar|almo[çc]o|pizza|lanche|restaurante|ingredientes?|modo de preparo|temperos?|molho)\b",
    r"\b(como\s+fazer\s+(um|uma|o|a)?\s*(macarr[ãa]o|comida|bolo|torta|pizza|caf[ée]|doce|sobremesa|almo[çc]o|jantar))\b",
    r"\b(como\s+(fazer|preparar|cozinhar))\b",
    r"\b(carro|carros|autom[óo]vel|ve[íi]culos|futebol|campeonato|copa do mundo|time|jogo)\b",
    r"\b(clima|tempo|previs[ãa]o do tempo|chover|temperatura amanh[ãa])\b",
    r"\b(filme|cinema|ator|atriz|novela|s[ée]rie)\b",
    r"\b(m[úu]sica|cantor|banda|show)\b",
    r"\b(como\s+fazer\s+amigos|conquistar|namorar|hor[óo]scopo|signo)\b",
    r"\bresponda\s+sobre\s+.*e\s+depois\b",
    r"\bfale\s+sobre\s+.*e\s+(depois|calcule|mostre)\b",
    r"\b(quem\s+descobriu\s+o\s+brasil|quem\s+foi\s+napole[ãa]o)\b",
    r"\b(poema|poesia|conto|hist[óo]ria infantil)\b",
    r"\b(sal[áa]rio|salarios?|remunera[çc][ãa]o|contracheque|holerite)\b",
    r"\b(cargos?|fun[çc][ãa]o|profiss[ãa]o|departamentos?)\b"
]

GREETING_PATTERNS = [
    r"^(oi|ol[áa]|ola|bom\s+dia|boa\s+tarde|boa\s+noite|tudo\s+bem|e\s+a[íi]|opa)[\!\?\.]*$"
]

SCHEMA_INTENT_PATTERNS = [
    r"\b(quais|quais\s+s[ãa]o|quais\s+as|quais\s+os)\s+(tabelas|colunas|campos|dados|schemas?|informa[çc][õo]es\s+dispon[íi]veis)\b",
    r"\b(que\s+dados|o\s+que\s+voc[êe]\s+sabe|o\s+que\s+tem\s+no\s+banco|me\s+mostre\s+as\s+tabelas|quais\s+tabelas\s+existem|quais\s+colunas\s+dispon[íi]veis|estrutura\s+do\s+banco|schema\s+do\s+banco|descubra\s+o\s+banco|descobrir\s+o\s+banco)\b",
    r"^(schema|tabelas|colunas)[\?\.]*$",
    r"\b(information_schema|show\s+tables|describe\s+(faturamento|usuarios))\b"
]

SCHEMA_CONFIRMATION_PATTERNS = [
    r"^(sim|s|quero\s+ver|mostre|mostra|mostre\s+me|por\s+favor|com\s+certeza|claro|pode\s+ser|manda|ok|beleza|yes|yep)[\!\?\.]*$",
    r"^(quais\s+colunas|quais\s+s[ãa]o\s+as\s+colunas|quais\s+dados|quais\s+tabelas|que\s+colunas|o\s+que\s+tem)[\?\.]*$",
    r"\b(sim|quero|pode\s+mostrar|gostaria\s+de\s+ver|mostre|mostra)\b\s+(ver\s+)?(as\s+|os\s+)?(colunas|tabelas|dados|schema|metadados)\b"
]

# Entidades e métricas reconhecidas para validação de ambiguidade
_RECOGNIZED_ENTITIES = [
    "cliente", "clientes", "cidade", "cidades", "municipio", "município", "municipios", "municípios",
    "estado", "estados", "uf", "filial", "filiais", "bu", "unidade", "unidades",
    "faturamento", "receita", "venda", "vendas", "vendedor", "vendedores", "comercial",
    "idade", "cadastro", "compra", "compras", "varejo", "fiscal", "contabil", "contábil",
    "corporativo", "servicos", "serviços", "pme", "plataformas", "ger7", "tas",
    "usuarios", "usuários", "faturamento", "produto", "produtos", "item", "itens", "linha", "linhas",
    "ano", "mes", "mês", "periodo", "período", "recente", "nota", "emissão"
]

_RECOGNIZED_METRICS = [
    "total", "totais", "média", "media", "médio", "medio", "soma", "quantidade",
    "quantos", "quantas", "quanto", "maior", "maiores", "menor", "menores",
    "ranking", "top", "ticket", "margem", "margem bruta", "lucro", "rentabilidade", "lucratividade",
    "faturado", "faturados", "vendido", "vendidos", "líquido", "liquido", "bruto"
]


class ScopeGuardrail:
    """Valida se a entrada do usuário pertence ao escopo corporativo permitido."""

    @classmethod
    def validate(cls, text: str) -> GuardrailResult:
        if not text or not text.strip():
            return GuardrailResult(
                is_allowed=False,
                risk_type="Fuga de Escopo",
                system_action="Bloqueado pelo Guardrail",
                refusal_message=STANDARD_REFUSAL_MESSAGE,
                reason="Entrada vazia ou sem caracteres válidos."
            )

        clean_text = text.strip()
        lower_text = clean_text.lower()

        # 0. Checagem de Tentativa de Escrita/Destruição SQL no Prompt (DROP, DELETE, TRUNCATE, ALTER, INSERT, UPDATE, etc.)
        _DESTRUCTIVE_SQL = [
            r"\b(drop\s+(table|database|view|schema))\b",
            r"\b(delete\s+from|truncate\s+table|truncate)\b",
            r"\b(alter\s+table|create\s+table|insert\s+into|update\s+\w+\s+set)\b",
            r"\b(attach|detach|pragma|exec|execute|grant|revoke)\b",
            r"(apague|apagar|apaga|delete|deletar|destrua|destruir|limpar|zerar)\s+(o\s+|os\s+|todas?\s+as?\s+)?(bancos?|database|tabelas?|registros?|dados?)",
            r"(como\s+apagar|como\s+deletar|como\s+dropar).*(banco|tabela|dados)"
        ]
        for pat in _DESTRUCTIVE_SQL:
            if re.search(pat, lower_text, re.IGNORECASE):
                return GuardrailResult(
                    is_allowed=False,
                    risk_type="Tentativa de Escrita SQL",
                    system_action="AST Guardrail Blocked",
                    refusal_message=STANDARD_REFUSAL_MESSAGE,
                    reason=f"Comando ou instrução de escrita/destruição detectada: '{pat}'"
                )

        # 1. Checagem de Prompt Injection / Override de Instruções
        for pat in _INJECTION_PATTERNS:
            if re.search(pat, lower_text, re.IGNORECASE):
                return GuardrailResult(
                    is_allowed=False,
                    risk_type="Tentativa de Prompt Injection",
                    system_action="Bloqueado pelo Guardrail",
                    refusal_message=STANDARD_REFUSAL_MESSAGE,
                    reason=f"Padrão de injeção/override detectado: '{pat}'"
                )

        # 2. Interceptação Determinística de Saudação (Sem chamada LLM/DuckDB)
        if any(re.match(p, clean_text, re.IGNORECASE) for p in GREETING_PATTERNS):
            return GuardrailResult(
                is_allowed=False,
                is_direct_response=True,
                direct_message=GREETING_RESPONSE,
                risk_type="Saudação",
                system_action="Resposta Direta de Boas-Vindas",
                refusal_message=GREETING_RESPONSE,
                reason="Saudação atendida deterministicamente."
            )

        # 3. Interceptação Determinística de Descoberta de Schema ou Confirmação Sim/Não (Sem chamada LLM/DuckDB)
        if (
            any(re.search(p, lower_text, re.IGNORECASE) for p in SCHEMA_INTENT_PATTERNS)
            or any(re.match(p, clean_text, re.IGNORECASE) for p in SCHEMA_CONFIRMATION_PATTERNS)
        ):
            schema_text = format_schema_presentation()
            return GuardrailResult(
                is_allowed=False,
                is_direct_response=True,
                direct_message=schema_text,
                risk_type="Apresentação de Schema",
                system_action="Apresentação Curada de Metadados",
                refusal_message=schema_text,
                reason="Descoberta de schema atendida deterministicamente sem tocar no banco."
            )

        # 4. Checagem de Fuga Explícita de Escopo (piadas, carros, receitas, salários, cargos, etc.)
        for pat in _OFF_SCOPE_PATTERNS:
            if re.search(pat, lower_text, re.IGNORECASE):
                return GuardrailResult(
                    is_allowed=False,
                    risk_type="Fuga de Escopo",
                    system_action="Bloqueado pelo Guardrail",
                    refusal_message=STANDARD_REFUSAL_MESSAGE,
                    reason=f"Padrão de desvio de escopo corporativo detectado: '{pat}'"
                )

        # 5. Detecção de Ambiguidade (Perguntas curtas/vagas sem entidade nem métrica definida)
        has_entity = any(re.search(rf"\b{e}\b", lower_text) for e in _RECOGNIZED_ENTITIES)
        has_metric = any(re.search(rf"\b{m}\b", lower_text) for m in _RECOGNIZED_METRICS)

        # Se não tem entidade corporativa nem métrica definida (ex: "Qual o melhor?", "Quanto deu?", "Qual o maior?")
        if not has_entity and (not has_metric or len(clean_text.split()) <= 3):
            # Se for menção a nome próprio de cliente (ex: "Carlos da Silva"), permite
            has_client_name = bool(re.search(r'\b[A-ZÀ-Ú][a-zà-ú]{2,}\b', clean_text)) and not any(re.search(p, lower_text) for p in _OFF_SCOPE_PATTERNS)
            if not has_client_name:
                return GuardrailResult(
                    is_allowed=False,
                    risk_type="Pergunta Ambígua",
                    system_action="Solicitação de Esclarecimento",
                    refusal_message=AMBIGUITY_RESPONSE,
                    reason="Pergunta ambígua sem entidade ou métrica definida."
                )

        # 6. Validação de Pertinência Analítica Estrita
        has_analytical_context = has_entity or has_metric
        has_client_name = bool(re.search(r'\b[A-ZÀ-Ú][a-zà-ú]{2,}\b', clean_text)) and not any(re.search(p, lower_text) for p in _OFF_SCOPE_PATTERNS)

        if not has_analytical_context and not has_client_name:
            return GuardrailResult(
                is_allowed=False,
                risk_type="Fuga de Escopo",
                system_action="Bloqueado pelo Guardrail",
                refusal_message=STANDARD_REFUSAL_MESSAGE,
                reason=f"Pergunta fora do escopo corporativo/analítico: '{text}'"
            )

        return GuardrailResult(is_allowed=True)
