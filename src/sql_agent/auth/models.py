"""
Modelos e esquemas de dados de Autenticação e Usuários.
Tags permitidas: ADM, Varejo, Fiscal, Contabil.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal, Any
from pydantic import BaseModel, Field

TAG_ADM = "ADM"
TAG_VAREJO = "Varejo"
TAG_FISCAL = "Fiscal"
TAG_CONTABIL = "Contabil"

ALLOWED_TAGS = [TAG_ADM, TAG_VAREJO, TAG_FISCAL, TAG_CONTABIL]
TagType = Literal["ADM", "Varejo", "Fiscal", "Contabil"]
ApprovalStatus = Literal["pending", "approved", "rejected"]


class UserBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=5, max_length=150)
    tag: TagType
    is_active: bool = True
    approval_status: ApprovalStatus = "approved"


class UserCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=5, max_length=150)
    password: str = Field(..., min_length=6, max_length=100)
    tag: TagType
    is_active: bool = True
    approval_status: ApprovalStatus = "approved"


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=5, max_length=150)
    password: str = Field(..., min_length=6, max_length=100)
    tag: TagType = "Varejo"


class UserResponse(BaseModel):
    id: int
    name: str
    username: str
    email: str
    tag: str
    bu: str = "Varejo"
    tags: list[str] = Field(default_factory=lambda: ["Varejo"])
    has_global_access: bool = False
    is_active: bool
    approval_status: str = "approved"
    last_login_at: Optional[str] = None
    created_at: str


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    remember_me: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    current_password: Optional[str] = None
    new_password: Optional[str] = Field(None, min_length=6, max_length=100)
    confirm_password: Optional[str] = None


class UpdateUserTagRequest(BaseModel):
    tag: TagType


class UpdateUserStatusRequest(BaseModel):
    is_active: bool


class ApproveUserRequest(BaseModel):
    tag: Optional[TagType] = None


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=100)


class SecurityAlertCreate(BaseModel):
    user_name: str
    username: str
    user_tag: str
    threat_type: str
    detected_content: str
    severity: str = "CRITICAL"


class SecurityAlertResponse(BaseModel):
    id: int
    user_name: str
    username: str
    user_tag: str
    threat_type: str
    detected_content: str
    severity: str
    status: str
    created_at: str


class UpdateUserAccessRequest(BaseModel):
    bu: str = Field(..., min_length=1, max_length=50)
    tags: list[str] = Field(..., min_items=1)


class AuditIncidentResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    username: str
    user_email: str
    user_bu: str
    user_tags: str
    risk_type: str
    raw_input: str
    response_message: str
    system_action: str
    severity: str = "CRITICAL"
    status: str = "active"
    created_at: str


class TelemetryResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    username: str
    user_email: str
    user_bu: str
    user_tags: str
    question: str
    generated_sql: Optional[str] = None
    execution_success: bool
    row_count: int = 0
    latency_ms: float
    tokens_consumed: int = 0
    error_message: Optional[str] = None
    created_at: str


class MonitoringMetricsResponse(BaseModel):
    daily_queries_count: int
    total_queries_count: int
    avg_latency_ms: float
    success_rate_percent: float
    total_tokens_consumed: int
    active_threats_count: int
    daily_queries: Optional[int] = None
    total_tokens: Optional[int] = None
    active_incidents: Optional[int] = None


class UserActivityResponse(BaseModel):
    user: UserResponse
    total_queries: int
    avg_latency_ms: float
    success_rate_percent: float
    incidents_count: int
    recent_queries: list[TelemetryResponse]
    incidents: list[AuditIncidentResponse]
    metrics: Optional[dict[str, Any]] = None


class ChatQueryRequest(BaseModel):
    question: Optional[str] = None
    query: Optional[str] = None
    prompt: Optional[str] = None

    def get_prompt(self) -> str:
        text = self.question or self.query or self.prompt or ""
        return text.strip()


class ChatQueryResponse(BaseModel):
    success: bool
    status: Optional[str] = "success"
    question: str
    sql: Optional[str] = None
    analysis: str
    execution_result: Optional[dict[str, Any]] = None
    blocked: bool = False
    risk_type: Optional[str] = None
    system_action: Optional[str] = None
    latency_ms: float
    tokens_consumed: int = 0
    user_context: dict[str, Any]

