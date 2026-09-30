"""
Módulo de Autenticação e Gestão de Usuários.
"""

from .database import init_db
from .router import router as auth_router

__all__ = ["init_db", "auth_router"]
