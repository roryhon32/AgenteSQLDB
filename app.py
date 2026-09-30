"""
app.py — Servidor Web FastAPI do Milia AI com Autenticação e Gestão de Usuários.
Execução:
    uvicorn app:app --port 8000 --reload
    ou
    python app.py
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse

from src.sql_agent.auth import init_db, auth_router
from src.sql_agent.auth.security import decode_access_token
from src.sql_agent.auth.service import AuthService
from src.sql_agent.chat.router import router as chat_router
from src.sql_agent.security import metrics_collector

# Inicializa o banco de dados SQLite com as tabelas, migrações e dados padrão
init_db()

app = FastAPI(
    title="Milia AI — Agente SQL & Plataforma Analítica",
    description="Sistema Text-to-SQL com Guardrails de Escopo, Auditoria e Gestão de Usuários.",
    version="2.0.0"
)

# Configuração de CORS para permitir requisições locais com credenciais (cookies)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Endpoint oficial de observabilidade do Prometheus
@app.get("/metrics", response_class=PlainTextResponse, tags=["Observabilidade"])
def get_prometheus_metrics():
    """Retorna métricas em formato oficial do Prometheus para raspagem contínua."""
    return metrics_collector.generate_prometheus_exposition()

# Registra as rotas de autenticação, administração e chat analítico
app.include_router(auth_router)
app.include_router(chat_router)

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "Assets"
FRONTEND_DIR = BASE_DIR / "frontend"

if ASSETS_DIR.exists():
    app.mount("/Assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


def get_session_user(request: Request) -> Optional[dict]:
    """
    Verifica se a requisição possui credenciais de autenticação válidas:
    - Cookie HttpOnly 'milia_remember_token' (sessão persistente de 30 dias)
    - Cookie HttpOnly 'milia_session' (sessão padrão de navegador)
    - Cabeçalho 'Authorization: Bearer <token>'
    Valida assinatura do JWT, expiração e se o usuário está ativo no banco SQLite.
    """
    token = request.cookies.get("milia_remember_token") or request.cookies.get("milia_session")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        return None

    try:
        payload = decode_access_token(token)
        if not payload or "sub" not in payload:
            return None
        user = AuthService.get_by_id(int(payload["sub"]))
        if not user or not user["is_active"]:
            return None
        return dict(user)
    except Exception:
        return None


def _serve_spa_file():
    """Entrega a aplicação frontend com headers de segurança anti-cache para evitar bfcache."""
    frontend_login = FRONTEND_DIR / "login.html"
    target_file = frontend_login if frontend_login.exists() else (BASE_DIR / "login.html")
    return FileResponse(
        target_file,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


@app.get("/")
def serve_root(request: Request):
    """
    Rota raiz:
    - Usuário autenticado -> Redireciona para /home
    - Usuário não autenticado -> Redireciona para /login
    """
    user = get_session_user(request)
    if user:
        return RedirectResponse(url="/home", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@app.get("/login")
def serve_login(request: Request):
    """
    Rota de login:
    - Se o usuário já estiver autenticado, redireciona diretamente para /home
    - Se não estiver autenticado, entrega a tela de login
    """
    user = get_session_user(request)
    if user:
        return RedirectResponse(url="/home", status_code=status.HTTP_302_FOUND)
    return _serve_spa_file()


@app.get("/home")
def serve_home(request: Request):
    """
    Área autenticada do Milia AI:
    - Acesso ESTRITAMENTE restrito a usuários autenticados.
    - Se NÃO autenticado, bloqueia o acesso e redireciona (HTTP 302) para /login.
    - Se autenticado, entrega a aplicação autenticada.
    """
    user = get_session_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return _serve_spa_file()


@app.get("/login.html")
@app.get("/frontend/login.html")
def protect_direct_html(request: Request):
    """Impede acesso direto aos arquivos .html brutos, canalizando pelas rotas /login e /home."""
    return serve_root(request)


@app.get("/documentation")
@app.get("/docs-web")
def serve_documentation():
    """Entrega a documentação técnica oficial interativa no padrão LangChain."""
    docs_file = FRONTEND_DIR / "docs.html"
    if docs_file.exists():
        return FileResponse(
            docs_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            }
        )
    fallback_docs = BASE_DIR / "docs" / "index.html"
    return FileResponse(fallback_docs)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)

