"""
Rotas e Endpoints de Autenticação, Cadastro de Usuários e Gestão com Aprovação (FastAPI).
Inclui validação estrita de permissões com middleware / dependency para Tag ADM (HTTP 403 Forbidden).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .models import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserResponse,
    UpdateProfileRequest,
    UserCreate,
    UpdateUserTagRequest,
    UpdateUserStatusRequest,
    ApproveUserRequest,
    ResetPasswordRequest,
    SecurityAlertCreate,
    SecurityAlertResponse,
    TAG_ADM
)
from .security import create_access_token, decode_access_token
from .service import AuthService, SecurityAlertService

router = APIRouter(prefix="/api", tags=["Autenticação e Usuários"])
security_scheme = HTTPBearer(auto_error=False)


def to_user_response(u: dict[str, Any]) -> UserResponse:
    """Converte dicionário de usuário para UserResponse com BU, Tags e Global Access."""
    raw_tags = u.get("tags")
    if isinstance(raw_tags, list):
        tags_list = raw_tags
    elif isinstance(raw_tags, str):
        tags_list = [t.strip() for t in raw_tags.split(",") if t.strip()]
    else:
        tags_list = [u.get("tag", "Varejo")]

    if not tags_list:
        tags_list = [u.get("tag", "Varejo")]

    has_global = u.get("has_global_access")
    if has_global is None:
        has_global = {"fiscal", "contabil", "adm"}.issubset({t.lower() for t in tags_list})

    return UserResponse(
        id=u["id"],
        name=u["name"],
        username=u["username"],
        email=u["email"],
        tag=u["tag"],
        bu=u.get("bu") or "Varejo",
        tags=tags_list,
        has_global_access=has_global,
        is_active=bool(u["is_active"]),
        approval_status=u.get("approval_status", "approved"),
        last_login_at=u.get("last_login_at"),
        created_at=u["created_at"]
    )


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme)
) -> dict[str, Any]:
    """Dependency que valida o Token JWT do cabeçalho Authorization: Bearer ou Cookies de Sessão/Remember Me."""
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif "milia_remember_token" in request.cookies:
        token = request.cookies["milia_remember_token"]
    elif "milia_session" in request.cookies:
        token = request.cookies["milia_session"]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado. Forneça o token Bearer ou cookie de sessão válido.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload["sub"]
    user = AuthService.get_by_id(int(user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário associado ao token não encontrado."
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conta de usuário inativa."
        )

    return dict(user)


def require_adm(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """
    Middleware / Dependency de autorização:
    Garante que APENAS usuários com a tag ADM tenham permissão para prosseguir.
    Retorna HTTP 403 Forbidden caso o usuário não possua privilégios de ADM.
    """
    is_adm = (current_user.get("tag") or "").upper() == TAG_ADM
    if not is_adm:
        raw_tags = current_user.get("tags") or []
        if isinstance(raw_tags, str):
            tags_list = [t.strip().upper() for t in raw_tags.split(",")]
        else:
            tags_list = [str(t).strip().upper() for t in raw_tags]
        is_adm = TAG_ADM in tags_list

    if not is_adm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado. Apenas usuários com a tag ADM possuem permissão para realizar esta operação."
        )
    return current_user


# ---------------------------------------------------------------------------
# 1. Rotas de Autenticação e Cadastro Público
# ---------------------------------------------------------------------------

@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest):
    """
    Criação de conta pelo colaborador.
    A conta é criada com status 'pending' e aguarda aprovação do ADM.
    """
    try:
        new_user = AuthService.register_user(
            name=req.name,
            username=req.username,
            email=req.email,
            password=req.password,
            tag=req.tag
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return {
        "message": "Solicitação de cadastro enviada! Sua conta está aguardando aprovação pelo administrador.",
        "username": new_user["username"],
        "approval_status": "pending"
    }


@router.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, response: Response):
    """Realiza autenticação com login case-insensitive e senha. Suporta Remember Me via cookies HttpOnly/SameSite."""
    try:
        user = AuthService.authenticate(req.username, req.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos."
        )

    is_https = request.url.scheme == "https"

    if req.remember_me:
        # Sessão estendida de 30 dias com cookie persistente
        delta_30d = timedelta(days=30)
        token = create_access_token(
            data={"sub": str(user["id"]), "username": user["username"], "tag": user["tag"]},
            expires_delta=delta_30d
        )
        response.delete_cookie(key="milia_session", path="/")
        response.set_cookie(
            key="milia_remember_token",
            value=token,
            max_age=30 * 24 * 3600,
            expires=30 * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=is_https,
            path="/"
        )
    else:
        # Sessão padrão descartada ao fechar o navegador
        token = create_access_token(
            data={"sub": str(user["id"]), "username": user["username"], "tag": user["tag"]}
        )
        response.delete_cookie(key="milia_remember_token", path="/")
        response.set_cookie(
            key="milia_session",
            value=token,
            httponly=True,
            samesite="lax",
            secure=is_https,
            path="/"
        )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=to_user_response(user)
    )


@router.get("/auth/session", response_model=LoginResponse)
def verify_session(request: Request, response: Response):
    """Verifica e restaura a sessão ativa via cookies seguros (Remember Me). Renova cookies válidos."""
    token = request.cookies.get("milia_remember_token") or request.cookies.get("milia_session")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nenhuma sessão ativa.")

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão expirada ou inválida.")

    user = AuthService.get_by_id(int(payload["sub"]))
    if not user or not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário inativo ou inexistente.")

    # Se cookie persistente de Remember Me presente, renova para mais 30 dias (sliding expiration)
    if "milia_remember_token" in request.cookies:
        response.set_cookie(
            key="milia_remember_token",
            value=token,
            max_age=30 * 24 * 3600,
            expires=30 * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/"
        )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=to_user_response(user)
    )


@router.post("/auth/logout")
def logout(response: Response):
    """Encerra a sessão e expira todos os cookies de autenticação (Remember Me e Session)."""
    response.delete_cookie(key="milia_remember_token", path="/")
    response.delete_cookie(key="milia_session", path="/")
    return {"message": "Sessão encerrada com sucesso."}


@router.get("/auth/me", response_model=UserResponse)
def get_me(current_user: dict[str, Any] = Depends(get_current_user)):
    """Retorna os dados cadastrais do próprio usuário autenticado."""
    return to_user_response(current_user)


@router.put("/auth/profile", response_model=UserResponse)
def update_profile(req: UpdateProfileRequest, current_user: dict[str, Any] = Depends(get_current_user)):
    """Permite ao usuário autenticado alterar seu próprio Nome e/ou Senha."""
    if req.new_password:
        if not req.confirm_password or req.new_password != req.confirm_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A confirmação da nova senha não confere."
            )

    try:
        updated = AuthService.update_profile(
            user_id=current_user["id"],
            name=req.name,
            current_password=req.current_password,
            new_password=req.new_password
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return to_user_response(updated)


# ---------------------------------------------------------------------------
# 2. Painel Administrativo de Gestão e Aprovação de Usuários (Exclusivo ADM)
# ---------------------------------------------------------------------------

@router.get("/admin/users", response_model=list[UserResponse])
def admin_list_users(_: dict[str, Any] = Depends(require_adm)):
    """Lista todos os usuários cadastrados (Requer tag ADM)."""
    users = AuthService.list_users()
    return [to_user_response(u) for u in users]


@router.put("/admin/users/{user_id}/approve", response_model=UserResponse)
def admin_approve_user(user_id: int, req: ApproveUserRequest = None, _: dict[str, Any] = Depends(require_adm)):
    """Aprova a criação de conta do usuário (Requer tag ADM)."""
    tag_val = req.tag if req else None
    try:
        updated = AuthService.approve_user(user_id, tag_val)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return to_user_response(updated)


@router.put("/admin/users/{user_id}/reject", response_model=UserResponse)
def admin_reject_user(user_id: int, _: dict[str, Any] = Depends(require_adm)):
    """Rejeita a solicitação de criação de conta (Requer tag ADM)."""
    try:
        updated = AuthService.reject_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return to_user_response(updated)


@router.post("/admin/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def admin_create_user(req: UserCreate, _: dict[str, Any] = Depends(require_adm)):
    """Cria um novo usuário diretamente pelo ADM (Já ativo e aprovado)."""
    try:
        new_user = AuthService.create_user(
            name=req.name,
            username=req.username,
            email=req.email,
            password=req.password,
            tag=req.tag,
            is_active=req.is_active,
            approval_status="approved"
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return to_user_response(new_user)


@router.put("/admin/users/{user_id}/tag", response_model=UserResponse)
def admin_update_user_tag(user_id: int, req: UpdateUserTagRequest, current_user: dict[str, Any] = Depends(require_adm)):
    """Altera a tag de permissão do usuário (Requer tag ADM, bloqueado para si próprio)."""
    if current_user["id"] == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O administrador não pode alterar sua própria tag de permissão."
        )
    try:
        updated = AuthService.update_tag(user_id, req.tag, operator_id=current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return to_user_response(updated)


@router.put("/admin/users/{user_id}/status", response_model=UserResponse)
def admin_update_user_status(user_id: int, req: UpdateUserStatusRequest, _: dict[str, Any] = Depends(require_adm)):
    """Ativa ou desativa o status de uma conta (Requer tag ADM)."""
    try:
        updated = AuthService.update_status(user_id, req.is_active)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return to_user_response(updated)


@router.put("/admin/users/{user_id}/reset-password")
def admin_reset_password(user_id: int, req: ResetPasswordRequest, _: dict[str, Any] = Depends(require_adm)):
    """Força a redefinição de senha de um usuário (Requer tag ADM)."""
    try:
        AuthService.reset_password(user_id, req.new_password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return {"message": "Senha redefinida com sucesso pelo administrador."}


# ---------------------------------------------------------------------------
# 3. Notificações e Alertas de Segurança (Violações de Políticas e Comandos Proibidos)
# ---------------------------------------------------------------------------

@router.get("/admin/security/alerts", response_model=list[SecurityAlertResponse])
def admin_get_security_alerts(_: dict[str, Any] = Depends(require_adm)):
    """Lista todos os incidentes de segurança registrados (Requer tag ADM)."""
    alerts = SecurityAlertService.list_alerts()
    return [SecurityAlertResponse(**a) for a in alerts]


@router.post("/security/report-incident", response_model=SecurityAlertResponse, status_code=status.HTTP_201_CREATED)
def report_security_incident(req: SecurityAlertCreate):
    """Registra uma tentativa de violação de segurança detectada no chat ou validação de query."""
    alert = SecurityAlertService.create_alert(
        user_name=req.user_name,
        username=req.username,
        user_tag=req.user_tag,
        threat_type=req.threat_type,
        detected_content=req.detected_content,
        severity=req.severity
    )
    return SecurityAlertResponse(**alert)


@router.put("/admin/security/alerts/{alert_id}/dismiss")
def admin_dismiss_security_alert(alert_id: int, _: dict[str, Any] = Depends(require_adm)):
    """Arquiva um alerta de segurança (Requer tag ADM)."""
    ok = SecurityAlertService.dismiss_alert(alert_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerta não localizado.")
    return {"message": "Alerta arquivado com sucesso."}


@router.put("/admin/security/alerts/{alert_id}/block-user")
def admin_block_user_from_alert(alert_id: int, _: dict[str, Any] = Depends(require_adm)):
    """Bloqueia a conta do usuário infrator imediatamente (Requer tag ADM)."""
    try:
        res = SecurityAlertService.block_user_from_alert(alert_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return res

