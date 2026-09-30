"""
rls_enforcer.py — Governança de Acesso e Isolamento por BU (Row-Level Security).

Regras de Permissão:
1. Acesso Global: Usuários cujas tags sejam 'fiscal', 'contabil' E 'adm' simultaneamente
   possuem acesso irrestrito para consultar métricas e dados de qualquer BU.
2. Acesso Restrito por BU: Usuários que NÃO possuam o conjunto completo de tags
   só podem visualizar registros de sua própria BU (registro.bu == usuario.bu).
3. Injeção de RLS: Intercepta a query SQL e injeta o predicado limitador de BU antes da execução.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Set
from .scope_guardrail import GuardrailResult


@dataclass
class RLSResult:
    """Resultado da aplicação de Row-Level Security."""
    is_allowed: bool
    modified_sql: str
    has_global_access: bool
    user_bu: str
    risk_type: Optional[str] = None
    system_action: Optional[str] = None
    refusal_message: Optional[str] = None
    reason: Optional[str] = None


class RLSEnforcer:
    """Aplica e valida as políticas de Row-Level Security em tempo de execução."""

    REQUIRED_GLOBAL_TAGS = {"fiscal", "contabil", "adm"}

    @classmethod
    def has_global_access(cls, user_tags: list[str] | str) -> bool:
        """Verifica se o usuário possui simultaneamente as 3 tags: fiscal, contabil e adm."""
        if isinstance(user_tags, str):
            tags_list = [t.strip().lower() for t in user_tags.split(",") if t.strip()]
        else:
            tags_list = [t.strip().lower() for t in user_tags if t.strip()]

        tags_set = set(tags_list)
        return cls.REQUIRED_GLOBAL_TAGS.issubset(tags_set)

    KNOWN_BUS = {"varejo", "fiscal", "contabil", "corporativo", "servicos"}

    @classmethod
    def enforce(cls, sql: str, user_bu: str, user_tags: list[str] | str, question: str = "") -> RLSResult:
        """
        Aplica as regras de RLS sobre a query SQL.
        - Se Global: executa a query original sem restrição de BU.
        - Se Restrito:
          * Bloqueia se a pergunta ou query tentar referenciar explicitamente uma BU não autorizada.
          * Injeta o filtro bu = 'user_bu' de forma transparente.
        """
        is_global = cls.has_global_access(user_tags)
        clean_bu = (user_bu or "Varejo").strip()

        if is_global:
            return RLSResult(
                is_allowed=True,
                modified_sql=sql,
                has_global_access=True,
                user_bu=clean_bu
            )

        # Usuário restrito por BU: checa se há tentativa de consultar outra BU explicitamente
        combined_text = f"{question} {sql}".lower()
        bu_filter_match = re.search(r"\bbu\s*=\s*['\"]?([a-zA-Z]+)['\"]?", combined_text)
        if bu_filter_match:
            target_bu = bu_filter_match.group(1).strip()
            if target_bu.lower() != clean_bu.lower():
                return RLSResult(
                    is_allowed=False,
                    modified_sql=sql,
                    has_global_access=False,
                    user_bu=clean_bu,
                    risk_type="Violação de BU",
                    system_action="Query Interceptada no RLS",
                    refusal_message=(
                        f"Operação não permitida. Acesso restrito exclusivamente aos dados da sua "
                        f"Unidade de Negócio ({clean_bu}). Consulta bloqueada para BU '{target_bu.capitalize()}'."
                    ),
                    reason=f"Usuário restrito à BU '{clean_bu}' tentou acessar dados da BU '{target_bu}'."
                )

        # Checa menções diretas de outras BUs na pergunta ou SQL
        for other_bu in cls.KNOWN_BUS - {clean_bu.lower()}:
            pattern = rf"\b(bu|unidade(\s+de\s+neg[óo]cio)?)\s+{other_bu}\b"
            if re.search(pattern, combined_text):
                return RLSResult(
                    is_allowed=False,
                    modified_sql=sql,
                    has_global_access=False,
                    user_bu=clean_bu,
                    risk_type="Violação de BU",
                    system_action="Query Interceptada no RLS",
                    refusal_message=(
                        f"Operação não permitida. Acesso restrito exclusivamente aos dados da sua "
                        f"Unidade de Negócio ({clean_bu}). Consulta bloqueada para BU '{other_bu.capitalize()}'."
                    ),
                    reason=f"Usuário restrito à BU '{clean_bu}' tentou acessar dados da BU '{other_bu}'."
                )

        # Injeção segura do predicado de BU sobre a tabela usuarios
        # Substitui referências à tabela 'usuarios' por uma subquery estritamente isolada pela BU
        # Padrão: FROM usuarios ou JOIN usuarios
        safe_subquery = f"(SELECT * FROM usuarios WHERE LOWER(bu) = LOWER('{clean_bu}')) AS usuarios"
        
        # Substitui ocorrências da tabela usuarios quando não for precedida por subquery inline
        # Verifica se já está encapsulado
        if "WHERE LOWER(bu) = LOWER(" not in sql:
            # Substitui 'FROM usuarios' por 'FROM (SELECT * FROM usuarios WHERE LOWER(bu) = LOWER('{clean_bu}')) AS usuarios'
            modified = re.sub(
                r"\bFROM\s+usuarios\b",
                f"FROM {safe_subquery}",
                sql,
                flags=re.IGNORECASE
            )
            # Substitui 'JOIN usuarios' por 'JOIN (SELECT * FROM usuarios WHERE LOWER(bu) = LOWER('{clean_bu}')) AS usuarios'
            modified = re.sub(
                r"\bJOIN\s+usuarios\b",
                f"JOIN {safe_subquery}",
                modified,
                flags=re.IGNORECASE
            )
        else:
            modified = sql

        return RLSResult(
            is_allowed=True,
            modified_sql=modified,
            has_global_access=False,
            user_bu=clean_bu
        )
