"""
pii_redactor.py — Mascaramento e Redação de Dados Sensíveis (LGPD / PII).
Garante que nenhum dado pessoal identificável (emails, CPFs, telefones, cartões, senhas)
seja exposto em logs de auditoria, telemetria ou saídas não autorizadas.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union


class PIIRedactor:
    """Mecanismo de redação e anonimização de dados pessoais identificáveis (PII)."""

    # Regex para e-mail
    _EMAIL_RE = re.compile(
        r"\b([a-zA-Z0-9_.+-])[a-zA-Z0-9_.+-]*@([a-zA-Z0-9-]+)(\.[a-zA-Z0-9-.]+)\b",
        re.IGNORECASE
    )

    # Regex para CPF (formatado ou apenas dígitos)
    _CPF_FORMATTED_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
    _CPF_RAW_RE = re.compile(r"\b(?:\d{11})\b")

    # Regex para cartões de crédito (13 a 19 dígitos com ou sem separador)
    _CARD_RE = re.compile(r"\b(?:\d{4}[ -]?){3}\d{1,4}\b")

    # Regex para telefones brasileiros (fixo e celular com DDD)
    _PHONE_RE = re.compile(r"\(?\b\d{2}\)?\s*(?:9\s*)?\d{4}[-.\s]?\d{4}\b")

    # Regex para credenciais / tokens em queries ou strings
    _SECRET_RE = re.compile(
        r"(?i)\b(password|passwd|senha|secret|token|api[_-]?key|bearer)\s*[:=]\s*['\"]?([^'\"\s,;]+)['\"]?"
    )

    @classmethod
    def redact_text(cls, text: Optional[str]) -> str:
        """Anonimiza todas as entidades PII presentes em um texto livre ou query."""
        if not text:
            return ""

        result = str(text)

        # 1. Redação de Segredos e Senhas
        result = cls._SECRET_RE.sub(r"\1=***", result)

        # 2. Redação de Cartões de Crédito
        result = cls._CARD_RE.sub("****-****-****-****", result)

        # 3. Redação de CPFs formatados
        result = cls._CPF_FORMATTED_RE.sub("***.***.***-**", result)

        # 4. Redação de E-mails (mantém inicial e domínio genérico para contexto)
        result = cls._EMAIL_RE.sub(r"\1***@***\3", result)

        # 5. Redação de Telefones
        result = cls._PHONE_RE.sub("(**) *****-****", result)

        return result

    @classmethod
    def redact_row_dict(cls, row_dict: Dict[str, Any], pii_columns: Optional[List[str]] = None) -> Dict[str, Any]:
        """Aplica redação a um dicionário de linha de resultado."""
        if pii_columns is None:
            pii_columns = ["email", "cpf", "documento", "telefone", "celular", "senha", "cartao", "rg"]

        redacted = {}
        for col, val in row_dict.items():
            col_lower = str(col).lower()
            if any(p in col_lower for p in pii_columns):
                redacted[col] = cls.redact_text(str(val))
            elif isinstance(val, str):
                redacted[col] = cls.redact_text(val)
            else:
                redacted[col] = val
        return redacted

    @classmethod
    def redact_user_identifier(cls, name_or_email: Optional[str]) -> str:
        """Censura/anonimiza nomes e e-mails de usuários para conformidade com LGPD na auditoria."""
        if not name_or_email:
            return "u*****"
        s = str(name_or_email).strip()
        if "@" in s:
            user_part, domain_part = s.split("@", 1)
            if len(user_part) <= 2:
                masked_user = user_part[0] + "***"
            else:
                masked_user = user_part[0] + "***" + user_part[-1]
            return f"{masked_user}@{domain_part}"
        parts = s.split(" ")
        if len(parts) > 1:
            masked_parts = []
            for p in parts:
                if len(p) <= 2:
                    masked_parts.append(p[0] + "***")
                else:
                    masked_parts.append(p[0] + "***" + p[-1])
            return " ".join(masked_parts)
        if len(s) <= 2:
            return s[0] + "***"
        return s[0] + "***" + s[-1]
