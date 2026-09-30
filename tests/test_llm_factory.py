"""Testes unitários para a fábrica get_llm e mecanismo de fallback."""

import os
import pytest
from unittest.mock import patch
from src.sql_agent.config.settings import Settings, get_llm


def test_settings_validation_no_keys():
    """Valida que Settings.validate levanta ValueError se nenhuma chave for fornecida."""
    with patch.dict(os.environ, {}, clear=True):
        s = Settings(groq_api_key="", github_token="", openai_api_key="")
        with pytest.raises(ValueError, match="Nenhuma chave de API de LLM"):
            s.validate()


def test_settings_validation_with_groq():
    """Valida que Settings.validate passa com chave Groq."""
    s = Settings(groq_api_key="gsk_test", github_token="", openai_api_key="")
    # Não deve levantar exceção
    s.validate()


def test_settings_validation_with_github():
    """Valida que Settings.validate passa com token GitHub."""
    s = Settings(groq_api_key="", github_token="ghp_test", openai_api_key="")
    # Não deve levantar exceção
    s.validate()


def test_get_llm_both_providers():
    """Valida instanciação com fallback quando ambos provedores estão configurados."""
    env = {
        "GROQ_API_KEY": "gsk_test_key",
        "GROQ_MODEL": "llama-3.3-70b-versatile",
        "GITHUB_TOKEN": "ghp_test_token",
        "GITHUB_MODEL": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env, clear=True):
        llm = get_llm(temperature=0.0)
        assert hasattr(llm, "fallbacks")
        assert len(llm.fallbacks) == 1
        assert llm.fallbacks[0].model_name == "gpt-4o-mini"


def test_get_llm_only_groq():
    """Valida instanciação somente com Groq quando GitHub token não está configurado."""
    env = {
        "GROQ_API_KEY": "gsk_test_key",
        "GROQ_MODEL": "llama-3.3-70b-versatile",
        "GITHUB_TOKEN": "",
        "OPENAI_API_KEY": "",
    }
    with patch.dict(os.environ, env, clear=True):
        llm = get_llm(temperature=0.0)
        assert hasattr(llm, "model_name")
        assert llm.model_name == "llama-3.3-70b-versatile"
        assert not hasattr(llm, "fallbacks")


def test_get_llm_only_github():
    """Valida instanciação somente com GitHub Models quando Groq não está configurado."""
    env = {
        "GROQ_API_KEY": "",
        "GITHUB_TOKEN": "ghp_test_token",
        "GITHUB_MODEL": "gpt-4o-mini",
        "OPENAI_API_KEY": "",
    }
    with patch.dict(os.environ, env, clear=True):
        llm = get_llm(temperature=0.0)
        assert hasattr(llm, "model_name")
        assert llm.model_name == "gpt-4o-mini"
        assert not hasattr(llm, "fallbacks")


def test_get_llm_raises_when_no_credentials():
    """Valida que get_llm levanta ValueError quando nenhuma chave está configurada."""
    env = {
        "GROQ_API_KEY": "",
        "GITHUB_TOKEN": "",
        "OPENAI_API_KEY": "",
    }
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValueError, match="Nenhuma chave de API de LLM"):
            get_llm(temperature=0.0)
