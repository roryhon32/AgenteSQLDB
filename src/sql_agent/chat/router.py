"""
router.py — Endpoints da Esteira Analítica do Chatbot, Guardrails, RLS e Central de Monitoramento.

Fluxo Síncrono da Requisição de Chat:
  1. Input Guardrail (validação de escopo e prompt injection)
  2. Text-to-SQL Agent (geração da consulta pelo AnalyticalAgent)
  3. RLS Enforcement (injeção/validação compulsória do isolamento por BU)
  4. SQL Sanitizer (verificação estrita de leitura read-only)
  5. DuckDB Execution (execução segura em modo isolado)
  6. Audit Logger (telemetria e registro de incidentes reais no SQLite)
  7. Chat Response (resposta estruturada em markdown e tabela para o front-end)
"""

from __future__ import annotations

import time
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status

from src.sql_agent.auth.models import (
    ChatQueryRequest,
    ChatQueryResponse,
    MonitoringMetricsResponse,
    AuditIncidentResponse,
    TelemetryResponse,
    UserActivityResponse,
    UpdateUserAccessRequest,
    UserResponse
)
from src.sql_agent.auth.router import get_current_user, require_adm
from src.sql_agent.auth.service import (
    AuthService,
    TelemetryService,
    AuditIncidentService,
    UserActivityService
)
from src.sql_agent.guardrails import ScopeGuardrail, SQLGuardrail, RLSEnforcer
from src.sql_agent.security import (
    rate_limiter,
    circuit_breaker,
    ImmutableAuditService,
    metrics_collector,
    PIIRedactor
)
from src.sql_agent.v2.agent import AnalyticalAgent, _render_template, _sanitize_generated_sql
from src.sql_agent.v2.config import settings
from src.sql_agent.v2.database import DatabaseManager

router = APIRouter(prefix="/api", tags=["Chat Analítico & Monitoramento"])

# Singleton do DatabaseManager e AnalyticalAgent para o ciclo de vida da API
_db_manager = DatabaseManager(db_path=settings.db_path, read_only=settings.read_only_connection)
_analytical_agent = AnalyticalAgent(db=_db_manager, settings=settings)


# ---------------------------------------------------------------------------
# 1. Pipeline Síncrono de Chat Text-to-SQL com Guardrails e RLS
# ---------------------------------------------------------------------------

@router.post("/chat/query", response_model=ChatQueryResponse)
def execute_chat_query(
    req: ChatQueryRequest,
    current_user: dict[str, Any] = Depends(get_current_user)
):
    """
    Executa o pipeline completo:
    Autenticação JWT → Input Guardrail → Text-to-SQL → RLS Enforcement →
    SQL Guardrail → DuckDB Execution → Telemetria/Auditoria → Resposta.
    """
    start_time = time.perf_counter()
    question = req.get_prompt()
    if not question:
        raise HTTPException(status_code=400, detail="A pergunta não pode ser vazia.")

    user_id = current_user["id"]
    username = current_user["username"]
    user_email = current_user["email"]
    user_bu = current_user.get("bu", "Varejo")
    user_tags = current_user.get("tags", ["Varejo"])
    tags_str = ",".join(user_tags) if isinstance(user_tags, list) else str(user_tags)
    has_global = current_user.get("has_global_access", False)

    user_ctx = {
        "id": user_id,
        "username": username,
        "email": user_email,
        "bu": user_bu,
        "tags": user_tags,
        "has_global_access": has_global
    }

    user_key = str(user_id)

    # ── ESTEIRA 0: Rate Limiting & Circuit Breaker (Proteção Perimetral) ─────
    # 0.1 Circuit Breaker: Verifica se o usuário está suspenso por violações repetidas
    is_cb_allowed, cb_msg, cb_remaining = circuit_breaker.is_allowed(user_key)
    if not is_cb_allowed:
        metrics_collector.record_query(
            status="blocked",
            user_bu=user_bu,
            latency_ms=0.0,
            reason_type="circuit_breaker"
        )
        return ChatQueryResponse(
            success=False,
            status="blocked",
            question=question,
            sql=None,
            analysis=cb_msg or "Usuário temporariamente suspenso por violações consecutivas de segurança.",
            execution_result=None,
            blocked=True,
            risk_type="Circuit Breaker Ativado",
            system_action="Suspensão Temporária de Conta",
            latency_ms=0.0,
            tokens_consumed=0,
            user_context=user_ctx
        )

    # 0.2 Rate Limiter: Janela deslizante de 60s (limite de 30 req/min)
    is_rl_allowed, cur_req_count = rate_limiter.check_rate_limit(user_key)
    if not is_rl_allowed:
        metrics_collector.record_query(
            status="blocked",
            user_bu=user_bu,
            latency_ms=0.0,
            reason_type="rate_limit"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Limite de requisições excedido (máximo 30 req/min). Aguarde alguns instantes."
        )

    # ── ESTEIRA 1: Input Guardrail (Validação de Escopo e Prompt Injection) ──
    scope_res = ScopeGuardrail.validate(question)

    # Respostas determinísticas diretas (Saudação, Descoberta de Schema, Esclarecimento de Ambiguidade)
    if getattr(scope_res, "is_direct_response", False):
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        TelemetryService.record_query(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            question=question,
            generated_sql=None,
            execution_success=True,
            row_count=0,
            latency_ms=elapsed_ms,
            tokens_consumed=len(question) // 4,
            error_message=None
        )
        metrics_collector.record_query(
            status="success",
            user_bu=user_bu,
            latency_ms=elapsed_ms,
            reason_type="direct_response"
        )
        return ChatQueryResponse(
            success=True,
            status="success",
            question=question,
            sql=None,
            analysis=scope_res.direct_message or "",
            execution_result=None,
            blocked=False,
            latency_ms=round(elapsed_ms, 2),
            tokens_consumed=len(question) // 4,
            user_context=user_ctx
        )

    if not scope_res.is_allowed:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        # Perguntas ambíguas são solicitações conversacionais normais de esclarecimento, não incidentes de segurança
        if scope_res.risk_type == "Pergunta Ambígua":
            TelemetryService.record_query(
                user_id=user_id,
                username=username,
                user_email=user_email,
                user_bu=user_bu,
                user_tags=tags_str,
                question=question,
                generated_sql=None,
                execution_success=True,
                row_count=0,
                latency_ms=elapsed_ms,
                tokens_consumed=len(question) // 4,
                error_message=None
            )
            return ChatQueryResponse(
                success=True,
                status="clarification_needed",
                question=question,
                sql=None,
                analysis=scope_res.refusal_message or "Pode detalhar um pouco mais? Por exemplo: qual métrica (faturamento, quantidade...) e qual recorte (por cidade, por BU, no total)?",
                execution_result=None,
                blocked=False,
                latency_ms=round(elapsed_ms, 2),
                tokens_consumed=len(question) // 4,
                user_context=user_ctx
            )

        # Dispara violação no Circuit Breaker para incidentes reais (Prompt Injection, Ataques)
        tripped = circuit_breaker.record_violation(user_key, risk_type=scope_res.risk_type or "Fuga de Escopo")
        if tripped:
            metrics_collector.record_circuit_breaker_trip()

        # Gravação no Logger de Auditoria de Incidentes Reais
        AuditIncidentService.record_incident(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            risk_type=scope_res.risk_type or "Fuga de Escopo",
            raw_input=question,
            response_message=scope_res.refusal_message or "",
            system_action=scope_res.system_action or "Bloqueado pelo Guardrail",
            severity="CRITICAL" if scope_res.risk_type == "Tentativa de Prompt Injection" else "HIGH"
        )

        # Gravação na Trilha de Auditoria Imutável (com Hash Encadeado e Redação PII)
        ImmutableAuditService.record_entry(
            user_id=user_id,
            username=username,
            user_bu=user_bu,
            query_proposed=question,
            guardrail_status="REJECTED",
            rejection_reason=scope_res.reason,
            risk_type=scope_res.risk_type,
            execution_time_ms=elapsed_ms,
            rows_returned=0
        )

        # Gravação na Telemetria Analítica
        TelemetryService.record_query(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            question=question,
            generated_sql=None,
            execution_success=False,
            row_count=0,
            latency_ms=elapsed_ms,
            tokens_consumed=len(question) // 4,
            error_message=scope_res.reason
        )

        metrics_collector.record_query(
            status="blocked",
            user_bu=user_bu,
            latency_ms=elapsed_ms,
            reason_type=scope_res.risk_type or "input_guardrail"
        )

        return ChatQueryResponse(
            success=False,
            status="blocked",
            question=question,
            sql=None,
            analysis=scope_res.refusal_message or "",
            execution_result=None,
            blocked=True,
            risk_type=scope_res.risk_type,
            system_action=scope_res.system_action,
            latency_ms=round(elapsed_ms, 2),
            tokens_consumed=len(question) // 4,
            user_context=user_ctx
        )

    # ── ESTEIRA 2: Text-to-SQL Agent (Geração do Plano e SQL) ─────────────────
    try:
        plan = _analytical_agent._generate_plan(question)
        raw_sql = plan.get("sql", "").strip()
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        err_msg = f"Falha na geração analítica: {exc}"

        ImmutableAuditService.record_entry(
            user_id=user_id,
            username=username,
            user_bu=user_bu,
            query_proposed=question,
            guardrail_status="REJECTED",
            rejection_reason=err_msg,
            risk_type="Falha de Geração LLM",
            execution_time_ms=elapsed_ms,
            rows_returned=0
        )

        AuditIncidentService.record_incident(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            risk_type="Falha de Geração LLM",
            raw_input=question,
            response_message=err_msg,
            system_action="Interrompido na Compilação",
            severity="LOW"
        )

        TelemetryService.record_query(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            question=question,
            generated_sql=None,
            execution_success=False,
            row_count=0,
            latency_ms=elapsed_ms,
            tokens_consumed=0,
            error_message=err_msg
        )

        metrics_collector.record_query(
            status="error",
            user_bu=user_bu,
            latency_ms=elapsed_ms,
            reason_type="llm_generation_error"
        )

        return ChatQueryResponse(
            success=False,
            status="blocked",
            question=question,
            sql=None,
            analysis=f"Não foi possível processar a consulta analítica: {exc}",
            execution_result=None,
            blocked=False,
            latency_ms=round(elapsed_ms, 2),
            tokens_consumed=0,
            user_context=user_ctx
        )

    SCHEMA_INSUFFICIENT_MSG = "Não encontrei esse dado no schema disponível. Quer ver quais colunas eu tenho?"

    if (
        raw_sql.upper() == "SCHEMA_INSUFICIENTE"
        or "SCHEMA_INSUFICIENTE" in (plan.get("intro") or "").upper()
        or plan.get("status") == "schema_insufficient"
    ):
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        TelemetryService.record_query(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            question=question,
            generated_sql=None,
            execution_success=False,
            row_count=0,
            latency_ms=elapsed_ms,
            tokens_consumed=len(question) // 4,
            error_message="Schema insuficiente para atender à pergunta."
        )
        metrics_collector.record_query(
            status="schema_insufficient",
            user_bu=user_bu,
            latency_ms=elapsed_ms,
            reason_type="schema_insufficient"
        )
        return ChatQueryResponse(
            success=False,
            status="schema_insufficient",
            question=question,
            sql=None,
            analysis=SCHEMA_INSUFFICIENT_MSG,
            execution_result=None,
            blocked=False,
            latency_ms=round(elapsed_ms, 2),
            tokens_consumed=len(question) // 4,
            user_context=user_ctx
        )

    if not raw_sql:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        refusal_msg = plan.get("intro") or STANDARD_REFUSAL_MESSAGE

        AuditIncidentService.record_incident(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            risk_type="Fuga de Escopo",
            raw_input=question,
            response_message=refusal_msg,
            system_action="Bloqueado pelo Agente Analítico",
            severity="MEDIUM"
        )

        ImmutableAuditService.record_entry(
            user_id=user_id,
            username=username,
            user_bu=user_bu,
            query_proposed=question,
            guardrail_status="REJECTED",
            rejection_reason="Query fora do escopo corporativo autorizada.",
            risk_type="Fuga de Escopo",
            execution_time_ms=elapsed_ms,
            rows_returned=0
        )

        return ChatQueryResponse(
            success=False,
            status="blocked",
            question=question,
            sql=None,
            analysis=refusal_msg,
            execution_result=None,
            blocked=True,
            risk_type="Fuga de Escopo",
            system_action="Bloqueado pelo Agente Analítico",
            latency_ms=round(elapsed_ms, 2),
            tokens_consumed=0,
            user_context=user_ctx
        )

    # ── ESTEIRA 3: RLS Enforcement (Isolamento por Unidade de Negócio) ─────────
    rls_res = RLSEnforcer.enforce(raw_sql, user_bu=user_bu, user_tags=user_tags, question=question)
    if not rls_res.is_allowed:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        tripped = circuit_breaker.record_violation(user_key, risk_type=rls_res.risk_type or "Violação de BU")
        if tripped:
            metrics_collector.record_circuit_breaker_trip()

        AuditIncidentService.record_incident(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            risk_type=rls_res.risk_type or "Violação de BU",
            raw_input=question,
            response_message=rls_res.refusal_message or "",
            system_action=rls_res.system_action or "Query Interceptada no RLS",
            severity="HIGH"
        )

        ImmutableAuditService.record_entry(
            user_id=user_id,
            username=username,
            user_bu=user_bu,
            query_proposed=raw_sql,
            guardrail_status="REJECTED",
            rejection_reason=rls_res.reason,
            risk_type=rls_res.risk_type,
            execution_time_ms=elapsed_ms,
            rows_returned=0
        )

        TelemetryService.record_query(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            question=question,
            generated_sql=raw_sql,
            execution_success=False,
            row_count=0,
            latency_ms=elapsed_ms,
            tokens_consumed=len(question + raw_sql) // 4,
            error_message=rls_res.reason
        )

        metrics_collector.record_query(
            status="blocked",
            user_bu=user_bu,
            latency_ms=elapsed_ms,
            reason_type="rls_violation"
        )

        return ChatQueryResponse(
            success=False,
            status="blocked",
            question=question,
            sql=raw_sql,
            analysis=rls_res.refusal_message or "",
            execution_result=None,
            blocked=True,
            risk_type=rls_res.risk_type,
            system_action=rls_res.system_action,
            latency_ms=round(elapsed_ms, 2),
            tokens_consumed=len(question + raw_sql) // 4,
            user_context=user_ctx
        )

    raw_sql_to_execute = _sanitize_generated_sql(rls_res.modified_sql)

    # ── ESTEIRA 4: Auto LIMIT 100 Enforcement & SQL Guardrail ────────────────
    # Garante teto máximo de 100 linhas mesmo se não especificado pelo compilador
    sql_to_execute = SQLGuardrail.enforce_limit(raw_sql_to_execute, max_limit=settings.auto_limit)

    sql_check = SQLGuardrail.validate(
        sql_to_execute,
        max_joins=settings.max_joins,
        max_subqueries=settings.max_subqueries
    )

    if not sql_check.is_allowed:
        if "Coluna Inexistente" in (sql_check.risk_type or ""):
            # Tenta auto-recuperar a query antes de declarar schema_insufficient
            try:
                healed = _analytical_agent._heal_sql(question, sql_to_execute, sql_check.reason or "")
                if healed and healed.strip() != sql_to_execute.strip():
                    healed = _sanitize_generated_sql(healed)
                    healed_limit = SQLGuardrail.enforce_limit(healed, max_limit=settings.auto_limit)
                    chk_healed = SQLGuardrail.validate(
                        healed_limit,
                        max_joins=settings.max_joins,
                        max_subqueries=settings.max_subqueries
                    )
                    if chk_healed.is_allowed:
                        sql_to_execute = healed_limit
                        sql_check = chk_healed
            except Exception:
                pass

    if not sql_check.is_allowed:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        if "Coluna Inexistente" in (sql_check.risk_type or ""):
            TelemetryService.record_query(
                user_id=user_id,
                username=username,
                user_email=user_email,
                user_bu=user_bu,
                user_tags=tags_str,
                question=question,
                generated_sql=None,
                execution_success=False,
                row_count=0,
                latency_ms=elapsed_ms,
                tokens_consumed=len(question) // 4,
                error_message=sql_check.reason
            )
            metrics_collector.record_query(
                status="schema_insufficient",
                user_bu=user_bu,
                latency_ms=elapsed_ms,
                reason_type="coluna_inexistente"
            )
            return ChatQueryResponse(
                success=False,
                status="schema_insufficient",
                question=question,
                sql=None,
                analysis=SCHEMA_INSUFFICIENT_MSG,
                execution_result=None,
                blocked=False,
                latency_ms=round(elapsed_ms, 2),
                tokens_consumed=len(question) // 4,
                user_context=user_ctx
            )

        tripped = circuit_breaker.record_violation(user_key, risk_type=sql_check.risk_type or "Tentativa de Escrita SQL")
        if tripped:
            metrics_collector.record_circuit_breaker_trip()

        AuditIncidentService.record_incident(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            risk_type=sql_check.risk_type or "Tentativa de Escrita SQL",
            raw_input=question,
            response_message=sql_check.refusal_message or "",
            system_action=sql_check.system_action or "Bloqueado pelo Guardrail",
            severity="CRITICAL"
        )

        ImmutableAuditService.record_entry(
            user_id=user_id,
            username=username,
            user_bu=user_bu,
            query_proposed=sql_to_execute,
            guardrail_status="REJECTED",
            rejection_reason=sql_check.reason,
            risk_type=sql_check.risk_type,
            execution_time_ms=elapsed_ms,
            rows_returned=0
        )

        TelemetryService.record_query(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            question=question,
            generated_sql=sql_to_execute,
            execution_success=False,
            row_count=0,
            latency_ms=elapsed_ms,
            tokens_consumed=len(question + sql_to_execute) // 4,
            error_message=sql_check.reason
        )

        metrics_collector.record_query(
            status="blocked",
            user_bu=user_bu,
            latency_ms=elapsed_ms,
            reason_type=sql_check.risk_type or "sql_guardrail"
        )

        return ChatQueryResponse(
            success=False,
            status="blocked",
            question=question,
            sql=sql_to_execute,
            analysis=sql_check.refusal_message or "",
            execution_result=None,
            blocked=True,
            risk_type=sql_check.risk_type,
            system_action=sql_check.system_action,
            latency_ms=round(elapsed_ms, 2),
            tokens_consumed=len(question + sql_to_execute) // 4,
            user_context=user_ctx
        )

    # ── ESTEIRA 5: Database Execution (Execução Segura no DuckDB) ──────────────
    exec_res = _db_manager.execute_safe(
        sql_to_execute,
        timeout=settings.query_timeout,
        max_explain_cost=settings.max_explain_cost,
        max_result_bytes=settings.max_result_bytes
    )

    # Auto-recuperação (Self-Healing) se ocorrer erro sintático/binder no DuckDB
    if not exec_res.success and "custo" not in str(exec_res.error).lower() and "bytes" not in str(exec_res.error).lower():
        try:
            healed_sql = _analytical_agent._heal_sql(question, sql_to_execute, exec_res.error or "")
            if healed_sql and healed_sql.strip() != sql_to_execute.strip():
                healed_sql = SQLGuardrail.enforce_limit(healed_sql, max_limit=settings.auto_limit)
                sql_check_healed = SQLGuardrail.validate(
                    healed_sql,
                    max_joins=settings.max_joins,
                    max_subqueries=settings.max_subqueries
                )
                if sql_check_healed.is_allowed:
                    exec_res_healed = _db_manager.execute_safe(
                        healed_sql,
                        timeout=settings.query_timeout,
                        max_explain_cost=settings.max_explain_cost,
                        max_result_bytes=settings.max_result_bytes
                    )
                    if exec_res_healed.success:
                        sql_to_execute = healed_sql
                        exec_res = exec_res_healed
        except Exception:
            pass

    if not exec_res.success:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        err_msg = f"Erro de execução DuckDB: {exec_res.error}"

        reason_type = "explain_cost" if "custo" in str(exec_res.error).lower() else (
            "result_bytes" if "bytes" in str(exec_res.error).lower() else "database_execution"
        )

        ImmutableAuditService.record_entry(
            user_id=user_id,
            username=username,
            user_bu=user_bu,
            query_proposed=sql_to_execute,
            guardrail_status="REJECTED",
            rejection_reason=exec_res.error,
            risk_type="Erro de Execução / Complexidade",
            execution_time_ms=elapsed_ms,
            rows_returned=0
        )

        AuditIncidentService.record_incident(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            risk_type="Erro de Execução / Complexidade",
            raw_input=question,
            response_message=str(exec_res.error),
            system_action="Interrompido pelo Sandbox DuckDB",
            severity="MEDIUM"
        )

        TelemetryService.record_query(
            user_id=user_id,
            username=username,
            user_email=user_email,
            user_bu=user_bu,
            user_tags=tags_str,
            question=question,
            generated_sql=sql_to_execute,
            execution_success=False,
            row_count=0,
            latency_ms=elapsed_ms,
            tokens_consumed=len(question + sql_to_execute) // 4,
            error_message=err_msg
        )

        metrics_collector.record_query(
            status="blocked",
            user_bu=user_bu,
            latency_ms=elapsed_ms,
            reason_type=reason_type
        )

        err_str = str(exec_res.error or "").lower()
        if "binder error" in err_str or "does not exist" in err_str or "referenciada" in err_str:
            return ChatQueryResponse(
                success=False,
                status="schema_insufficient",
                question=question,
                sql=None,
                analysis=SCHEMA_INSUFFICIENT_MSG,
                execution_result={"columns": [], "rows": [], "row_count": 0},
                blocked=False,
                latency_ms=round(elapsed_ms, 2),
                tokens_consumed=len(question + sql_to_execute) // 4,
                user_context=user_ctx
            )

        return ChatQueryResponse(
            success=False,
            status="blocked",
            question=question,
            sql=sql_to_execute,
            analysis=f"A consulta encontrou um problema durante a execução: {exec_res.error}",
            execution_result={"columns": [], "rows": [], "row_count": 0},
            blocked=False,
            latency_ms=round(elapsed_ms, 2),
            tokens_consumed=len(question + sql_to_execute) // 4,
            user_context=user_ctx
        )

    # ── ESTEIRA 6: Renderização e Síntese Analítica Local (Zero-Trust) ─────────
    analysis = _render_template(plan, exec_res, settings.max_rows_context)
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
    tokens_consumed = max(35, len(question + sql_to_execute + analysis) // 4)

    # Registra sucesso no Circuit Breaker para normalizar estado
    circuit_breaker.record_success(user_key)

    # ── ESTEIRA 7: Audit Logger (Gravação da Telemetria e Trilha Imutável) ────
    ImmutableAuditService.record_entry(
        user_id=user_id,
        username=username,
        user_bu=user_bu,
        query_proposed=sql_to_execute,
        guardrail_status="ACCEPTED",
        rejection_reason=None,
        risk_type=None,
        execution_time_ms=elapsed_ms,
        rows_returned=exec_res.row_count
    )

    AuditIncidentService.record_incident(
        user_id=user_id,
        username=username,
        user_email=user_email,
        user_bu=user_bu,
        user_tags=tags_str,
        risk_type="Consulta Analítica (Auditada)",
        raw_input=question,
        response_message=sql_to_execute,
        system_action=f"Executado no DuckDB (RLS {user_bu} • {exec_res.row_count} linhas)",
        severity="INFO"
    )

    TelemetryService.record_query(
        user_id=user_id,
        username=username,
        user_email=user_email,
        user_bu=user_bu,
        user_tags=tags_str,
        question=question,
        generated_sql=sql_to_execute,
        execution_success=True,
        row_count=exec_res.row_count,
        latency_ms=elapsed_ms,
        tokens_consumed=tokens_consumed,
        error_message=None
    )

    metrics_collector.record_query(
        status="success",
        user_bu=user_bu,
        latency_ms=elapsed_ms
    )

    # Atualiza a memória de turnos conversacionais
    _analytical_agent.memory.add_turn(
        question=question,
        interpretation=plan.get("intro", ""),
        sql=sql_to_execute,
    )

    return ChatQueryResponse(
        success=True,
        status="success",
        question=question,
        sql=sql_to_execute,
        analysis=analysis,
        execution_result={
            "columns": exec_res.columns,
            "rows": exec_res.rows[:30],
            "row_count": exec_res.row_count
        },
        blocked=False,
        latency_ms=round(elapsed_ms, 2),
        tokens_consumed=tokens_consumed,
        user_context=user_ctx
    )


# ---------------------------------------------------------------------------
# 2. Central de Monitoramento: Métricas Gerais & Auditoria de Incidentes
# ---------------------------------------------------------------------------

@router.get("/monitoring/metrics", response_model=MonitoringMetricsResponse)
def get_monitoring_metrics(current_user: dict[str, Any] = Depends(get_current_user)):
    """Retorna as métricas consolidadas em tempo real do banco de dados SQLite."""
    metrics = TelemetryService.get_metrics()
    return MonitoringMetricsResponse(**metrics)


@router.get("/monitoring/incidents", response_model=list[AuditIncidentResponse])
def get_monitoring_incidents(
    status: Optional[str] = None,
    current_user: dict[str, Any] = Depends(get_current_user)
):
    """Retorna os incidentes reais da Central de Monitoramento. Para ADM retorna nome e dados reais; para não-ADM censura PII."""
    incidents = AuditIncidentService.list_incidents(status=status, limit=100)
    
    is_adm = (current_user.get("tag") or "").upper() == "ADM"
    if not is_adm:
        raw_tags = current_user.get("tags") or []
        if isinstance(raw_tags, str):
            tags_list = [t.strip().upper() for t in raw_tags.split(",")]
        else:
            tags_list = [str(t).strip().upper() for t in raw_tags]
        is_adm = "ADM" in tags_list

    sanitized = []
    for inc in incidents:
        item = dict(inc)
        if not is_adm:
            item["username"] = PIIRedactor.redact_user_identifier(item.get("username"))
            item["user_email"] = PIIRedactor.redact_user_identifier(item.get("user_email"))
            if item.get("user_name"):
                item["user_name"] = PIIRedactor.redact_user_identifier(item.get("user_name"))
        sanitized.append(AuditIncidentResponse(**item))
    return sanitized


@router.put("/monitoring/incidents/{incident_id}/dismiss")
def dismiss_incident(
    incident_id: int,
    current_user: dict[str, Any] = Depends(require_adm)
):
    """Arquiva um incidente de auditoria após revisão do Administrador."""
    ok = AuditIncidentService.dismiss_incident(incident_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incidente não encontrado."
        )
    return {"message": "Incidente arquivado com sucesso pelo Administrador."}


# ---------------------------------------------------------------------------
# 3. Gestão de Usuários Modular: Aba 2 (Acesso & BU) e Aba 3 (Atividade)
# ---------------------------------------------------------------------------

@router.put("/admin/users/{user_id}/access", response_model=UserResponse)
def update_user_access(
    user_id: int,
    req: UpdateUserAccessRequest,
    current_user: dict[str, Any] = Depends(require_adm)
):
    """
    Aba 2: Controle de Acesso — Associa a Unidade de Negócio (BU) e
    atualiza as tags de permissão do usuário de forma imediata.
    """
    try:
        updated = AuthService.update_user_access(user_id, req.bu, req.tags)
        return UserResponse(**updated)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/admin/users/{user_id}/activity", response_model=UserActivityResponse)
def get_user_activity(
    user_id: int,
    current_user: dict[str, Any] = Depends(require_adm)
):
    """
    Aba 3: Histórico de Atividade — Retorna o histórico de consultas analíticas
    e incidentes de risco associados ao usuário selecionado.
    """
    try:
        activity = UserActivityService.get_user_activity(user_id)
        return UserActivityResponse(**activity)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ---------------------------------------------------------------------------
# 4. Trilha Imutável e Observabilidade de Segurança
# ---------------------------------------------------------------------------

@router.get("/admin/audit/verify")
def verify_audit_chain_integrity(current_user: dict[str, Any] = Depends(require_adm)):
    """
    Verifica matematicamente o encadeamento de hashes (SHA-256) da trilha de auditoria imutável.
    Detecta qualquer alteração, injeção ou deleção de registros históricos.
    """
    is_valid, total_records, errors = ImmutableAuditService.verify_chain_integrity()
    return {
        "is_valid": is_valid,
        "total_records": total_records,
        "errors": errors,
        "status": "INTEGRITY_VERIFIED" if is_valid else "TAMPERING_DETECTED"
    }


@router.get("/admin/security/metrics")
def get_security_metrics_status(current_user: dict[str, Any] = Depends(require_adm)):
    """
    Retorna o status consolidado de observabilidade, alertas de anomalia de rejeição
    e payload formatado para Prometheus.
    """
    is_alert, current_rate, baseline = metrics_collector.is_baseline_exceeded()
    return {
        "rejection_rate_ratio": current_rate,
        "rejection_rate_baseline": baseline,
        "baseline_exceeded_alert": is_alert,
        "prometheus_payload": metrics_collector.generate_prometheus_exposition()
    }
