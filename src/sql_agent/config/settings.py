"""Gerenciamento de configurações e variáveis de ambiente com suporte a Fallback de LLM."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

# Carrega o .env a partir da raiz do projeto
load_dotenv()


@dataclass
class Settings:
    """Configurações centralizadas da aplicação."""

    groq_api_key: Optional[str] = None
    groq_model: Optional[str] = None
    github_token: Optional[str] = None
    github_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    temperature: float = 0.0

    def __post_init__(self) -> None:
        if self.groq_api_key is None:
            self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        if self.groq_model is None:
            self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        if self.github_token is None:
            self.github_token = os.getenv("GITHUB_TOKEN", "")
        if self.github_model is None:
            self.github_model = os.getenv("GITHUB_MODEL", "gpt-4o-mini")
        if self.openai_api_key is None:
            self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        if self.openai_model is None:
            self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def validate(self) -> None:
        """Verifica se pelo menos um dos provedores de LLM suportados está configurado."""
        groq_key = os.getenv("GROQ_API_KEY", self.groq_api_key)
        github_token = os.getenv("GITHUB_TOKEN", self.github_token)
        openai_key = os.getenv("OPENAI_API_KEY", self.openai_api_key)

        if not groq_key and not github_token and not openai_key:
            raise ValueError(
                "Nenhuma chave de API de LLM encontrada nas variáveis de ambiente.\n"
                "Por favor, configure GROQ_API_KEY, GITHUB_TOKEN ou OPENAI_API_KEY no arquivo .env."
            )


settings = Settings()


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """
    Fábrica centralizada de LLM com suporte a Fallback (Failover) nativo via LangChain.

    1. Primário: GroqCloud (llama-3.3-70b-versatile) via ChatGroq
    2. Fallback: GitHub Models (gpt-4o-mini) via ChatOpenAI (Azure AI)
    3. Fallback legado: OpenAI (gpt-4o-mini) se configurado
    """
    settings.validate()

    groq_key = os.getenv("GROQ_API_KEY", settings.groq_api_key)
    github_token = os.getenv("GITHUB_TOKEN", settings.github_token)
    openai_key = os.getenv("OPENAI_API_KEY", settings.openai_api_key)

    groq_model = os.getenv("GROQ_MODEL", settings.groq_model or "llama-3.3-70b-versatile")
    github_model = os.getenv("GITHUB_MODEL", settings.github_model or "gpt-4o-mini")
    openai_model = os.getenv("OPENAI_MODEL", settings.openai_model or "gpt-4o-mini")

    primary_llm: Optional[BaseChatModel] = None
    if groq_key:
        primary_llm = ChatGroq(
            model_name=groq_model,
            groq_api_key=groq_key,
            temperature=temperature
        )

    fallback_llm: Optional[BaseChatModel] = None
    if github_token:
        fallback_llm = ChatOpenAI(
            model=github_model,
            api_key=github_token,
            base_url="https://models.inference.ai.azure.com",
            temperature=temperature
        )
    elif openai_key:
        fallback_llm = ChatOpenAI(
            model=openai_model,
            api_key=openai_key,
            temperature=temperature
        )

    if primary_llm and fallback_llm:
        return primary_llm.with_fallbacks([fallback_llm])
    elif primary_llm:
        return primary_llm
    elif fallback_llm:
        return fallback_llm
    else:
        raise ValueError(
            "Nenhuma chave de API de LLM configurada (GROQ_API_KEY, GITHUB_TOKEN ou OPENAI_API_KEY).\n"
            "Por favor, configure suas credenciais no arquivo .env antes de executar."
        )
