"""
test_advanced_security.py — Suite completa de testes automatizados para as 6 camadas de
segurança, governança e observabilidade do Agente SQL.

Camadas testadas:
  1. Defesa em Profundidade (Conexão Read-Only + Parametrização)
  2. Controle de Complexidade (AST JOINs, Subqueries, EXPLAIN Cost, Byte Cap, Auto LIMIT)
  3. Controle de Acesso a Dados Sensíveis (Allowlist AST + Redação PII)
  4. Rate Limiting & Circuit Breaker Adaptativo
  5. Trilha de Auditoria Imutável (Hash Encadeado SHA-256 + Triggers SQLite + Verificação de Adulteração)
  6. Observabilidade & Prometheus Metrics (/metrics + Alerta de Baseline)
"""

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# Garante que o diretório raiz esteja no path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
from src.sql_agent.guardrails.sql_guardrail import SQLGuardrail
from src.sql_agent.security import (
    RateLimiter,
    SecurityCircuitBreaker,
    ImmutableAuditService,
    MetricsCollector,
    PIIRedactor,
)
from src.sql_agent.v2.database import DatabaseManager


# ===========================================================================
# 1. Defesa em Profundidade
# ===========================================================================

def test_read_only_database_connection():
    """Valida que uma conexão DuckDB com read_only=True rejeita comandos DML/DDL no motor."""
    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as f:
        db_path = f.name
    if os.path.exists(db_path):
        os.remove(db_path)

    try:
        # 1. Admin cria e popula a base
        admin_conn = duckdb.connect(db_path)
        admin_conn.execute("CREATE TABLE usuarios (id INT, Cliente VARCHAR);")
        admin_conn.execute("INSERT INTO usuarios VALUES (1, 'Carlos Silva');")
        admin_conn.close()

        # 2. Conexão dedicada de Leitura (Read-Only)
        ro_conn = duckdb.connect(db_path, read_only=True)
        rows = ro_conn.execute("SELECT * FROM usuarios").fetchall()
        assert len(rows) == 1, "Deveria conseguir ler dados na conexão read-only"

        # 3. Tenta mutação de escrita — deve falhar no nível de permissão do motor
        write_blocked = False
        try:
            ro_conn.execute("INSERT INTO usuarios VALUES (2, 'Hacker');")
        except Exception as exc:
            write_blocked = True
            assert "read-only mode" in str(exc).lower() or "cannot execute statement" in str(exc).lower()

        assert write_blocked, "O motor de banco deveria ter bloqueado INSERT na conexão read-only"
        ro_conn.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_parameterized_execution():
    """Valida prepared statements / execução parametrizada contra injeção SQL."""
    db = DatabaseManager(":memory:", auto_seed=True)
    try:
        # Execução parametrizada legítima
        res = db.execute_safe("SELECT id, Cliente, bu FROM usuarios WHERE bu = ?", params=["Varejo"])
        assert res.success is True
        assert res.row_count > 0

        # Tentativa de injeção passada como parâmetro é tratada como valor literal, não executável
        malicious_input = "' OR '1'='1"
        res_inject = db.execute_safe("SELECT id, Cliente, bu FROM usuarios WHERE bu = ?", params=[malicious_input])
        assert res_inject.success is True
        assert res_inject.row_count == 0, "Parametrização não deve permitir injeção lógica"
    finally:
        db.close()


# ===========================================================================
# 2. Controle de Complexidade
# ===========================================================================

def test_ast_max_joins_limit():
    """Valida que queries com mais de 3 JOINs são rejeitadas pela AST."""
    query_ok = "SELECT * FROM usuarios u1 JOIN usuarios u2 ON u1.id = u2.id"
    res_ok = SQLGuardrail.validate(query_ok, max_joins=3)
    assert res_ok.is_allowed is True

    query_too_many_joins = (
        "SELECT * FROM usuarios u1 "
        "JOIN usuarios u2 ON u1.id = u2.id "
        "LEFT JOIN usuarios u3 ON u2.id = u3.id "
        "INNER JOIN usuarios u4 ON u3.id = u4.id "
        "JOIN usuarios u5 ON u4.id = u5.id"
    )
    res_fail = SQLGuardrail.validate(query_too_many_joins, max_joins=3)
    assert res_fail.is_allowed is False
    assert res_fail.risk_type == "Complexidade Excessiva"
    assert "JOINs" in res_fail.reason


def test_ast_max_subqueries_limit():
    """Valida que queries com mais de 2 subqueries aninhadas são rejeitadas."""
    query_ok = "SELECT * FROM (SELECT id, bu FROM usuarios WHERE id > 0)"
    res_ok = SQLGuardrail.validate(query_ok, max_subqueries=2)
    assert res_ok.is_allowed is True

    query_too_many_subqueries = (
        "SELECT * FROM ("
        "  SELECT * FROM ("
        "    SELECT * FROM ("
        "      SELECT id FROM usuarios"
        "    )"
        "  )"
        ")"
    )
    res_fail = SQLGuardrail.validate(query_too_many_subqueries, max_subqueries=2)
    assert res_fail.is_allowed is False
    assert res_fail.risk_type == "Complexidade Excessiva"
    assert "subqueries" in res_fail.reason


def test_explain_cost_rejection():
    """Valida que o EXPLAIN detecta e rejeita planos com produto cartesiano e custo alto."""
    db = DatabaseManager(":memory:", auto_seed=True)
    try:
        # Query normal: custo baixo (~20)
        c_ok, err_ok, cost = db.check_query_cost("SELECT * FROM usuarios WHERE bu = 'Varejo'", max_cost=500)
        assert c_ok is True
        assert cost < 500

        # Query de produto cartesiano pesado: custo alto (>600)
        cartesian_sql = "SELECT * FROM usuarios a, usuarios b, usuarios c"
        c_fail, err_fail, cost_high = db.check_query_cost(cartesian_sql, max_cost=500)
        assert c_fail is False
        assert "custo" in err_fail.lower() or "cartesiano" in err_fail.lower()

        # Na execução segura, a query deve ser abortada antes da execução
        res = db.execute_safe(cartesian_sql, max_explain_cost=500)
        assert res.success is False
        assert "plano" in res.error.lower() or "custo" in res.error.lower()
    finally:
        db.close()


def test_byte_size_cap():
    """Valida que resultados gigantes que excedem o teto em bytes são rejeitados."""
    db = DatabaseManager(":memory:", auto_seed=True)
    try:
        # Com cap muito restrito (ex: 200 bytes), uma busca normal de 10 linhas estoura
        res = db.execute_safe("SELECT * FROM usuarios", max_result_bytes=200)
        assert res.success is False
        assert "excedeu o limite" in res.error
        assert "bytes" in res.error
    finally:
        db.close()


def test_auto_limit_100_enforcement():
    """Valida que queries sem LIMIT recebem LIMIT 100 e LIMIT 500 é reduzido para 100."""
    q1 = "SELECT * FROM usuarios WHERE bu = 'Varejo'"
    capped1 = SQLGuardrail.enforce_limit(q1, max_limit=100)
    assert "LIMIT 100" in capped1

    q2 = "SELECT * FROM usuarios LIMIT 500"
    capped2 = SQLGuardrail.enforce_limit(q2, max_limit=100)
    assert "LIMIT 100" in capped2
    assert "LIMIT 500" not in capped2

    q3 = "SELECT * FROM usuarios LIMIT 50"
    capped3 = SQLGuardrail.enforce_limit(q3, max_limit=100)
    assert "LIMIT 50" in capped3


# ===========================================================================
# 3. Controle de Acesso a Dados Sensíveis
# ===========================================================================

def test_ast_allowlist_tables_and_columns():
    """Valida que apenas tabelas e colunas autorizadas podem ser consultadas."""
    # Tabela não autorizada (ex: users do auth interno ou sqlite_master)
    query_unauthorized_table = "SELECT * FROM users"
    res_tbl = SQLGuardrail.validate(query_unauthorized_table)
    assert res_tbl.is_allowed is False
    assert res_tbl.risk_type == "Acesso a Objeto Não Autorizado"

    # Coluna sensível proibida (ex: password ou cpf)
    query_sensitive_column = "SELECT password FROM usuarios"
    res_col = SQLGuardrail.validate(query_sensitive_column)
    assert res_col.is_allowed is False
    assert res_col.risk_type == "Acesso a Coluna Sensível"


def test_pii_redactor():
    """Valida a redação de CPFs, emails, telefones, cartões e segredos."""
    raw_text = (
        "O cliente João tem CPF 123.456.789-00, email joao.silva@empresa.com.br, "
        "telefone (11) 98765-4321, cartão 4532-1234-5678-9012 e token: 'sec_abc12345'."
    )
    redacted = PIIRedactor.redact_text(raw_text)

    # Verifica que dados brutos foram todos eliminados
    assert "123.456.789-00" not in redacted
    assert "joao.silva@empresa.com.br" not in redacted
    assert "98765-4321" not in redacted
    assert "4532-1234-5678-9012" not in redacted
    assert "sec_abc12345" not in redacted

    # Verifica que máscaras padronizadas foram aplicadas
    assert "***.***.***-**" in redacted
    assert "@***" in redacted
    assert "(**) *****-****" in redacted
    assert "****-****-****-****" in redacted
    assert "token=***" in redacted


# ===========================================================================
# 4. Rate Limiting & Circuit Breaker
# ===========================================================================

def test_rate_limiter_sliding_window():
    """Valida que o RateLimiter permite até N req/min e bloqueia requisições excedentes."""
    rl = RateLimiter(max_requests_per_minute=5)
    user_key = "user_test_rl"

    for i in range(5):
        allowed, count = rl.check_rate_limit(user_key)
        assert allowed is True, f"Requisição {i+1} deveria ser permitida"

    # 6ª requisição deve ser bloqueada
    allowed_6, count_6 = rl.check_rate_limit(user_key)
    assert allowed_6 is False
    assert count_6 == 5


def test_security_circuit_breaker_trip():
    """Valida que 3 violações de segurança disparam o Circuit Breaker, suspendendo o usuário."""
    cb = SecurityCircuitBreaker(failure_threshold=3, window_seconds=10, cooldown_seconds=60)
    user_key = "user_attacker"

    # Inicialmente permitido
    allowed, _, _ = cb.is_allowed(user_key)
    assert allowed is True

    # 1ª e 2ª violações
    t1 = cb.record_violation(user_key, "Tentativa DDL")
    assert t1 is False
    t2 = cb.record_violation(user_key, "Tentativa Injeção")
    assert t2 is False

    # 3ª violação dispara o trip
    t3 = cb.record_violation(user_key, "Tentativa DDL")
    assert t3 is True, "Circuit Breaker deveria ter disparado na 3ª falha"

    # Agora o usuário está suspenso
    is_blocked, msg, remaining = cb.is_allowed(user_key)
    assert is_blocked is False
    assert "Circuit Breaker Ativado" in msg
    assert remaining > 0


# ===========================================================================
# 5. Trilha de Auditoria Imutável (Hash Encadeado SHA-256 + Triggers)
# ===========================================================================

def test_immutable_audit_log_and_tamper_detection():
    """Valida o hash encadeado, proteção de triggers e detecção de adulteração."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    if db_path.exists():
        os.remove(db_path)

    ImmutableAuditService.set_db_path(db_path)

    try:
        # 1. Registra 3 entradas legítimas
        e1 = ImmutableAuditService.record_entry(
            user_id=1, username="carlos", user_bu="Varejo",
            query_proposed="SELECT * FROM usuarios", guardrail_status="ACCEPTED",
            execution_time_ms=15.2, rows_returned=10
        )
        assert e1["previous_hash"] == "0" * 64, "Primeiro bloco deve apontar para gênese"

        e2 = ImmutableAuditService.record_entry(
            user_id=1, username="carlos", user_bu="Varejo",
            query_proposed="DROP TABLE usuarios", guardrail_status="REJECTED",
            rejection_reason="DDL Proibido", risk_type="Tentativa de Escrita",
            execution_time_ms=1.1, rows_returned=0
        )
        assert e2["previous_hash"] == e1["entry_hash"], "Segundo bloco deve conter hash do primeiro"

        e3 = ImmutableAuditService.record_entry(
            user_id=2, username="mariana", user_bu="Fiscal",
            query_proposed="SELECT bu, sum(faturamento) FROM usuarios GROUP BY bu",
            guardrail_status="ACCEPTED", execution_time_ms=18.5, rows_returned=4
        )
        assert e3["previous_hash"] == e2["entry_hash"], "Terceiro bloco deve conter hash do segundo"

        # 2. Verifica a integridade da cadeia intacta
        is_valid, count, errors = ImmutableAuditService.verify_chain_integrity()
        assert is_valid is True
        assert count == 3
        assert len(errors) == 0

        # 3. Testa proteção de triggers SQLite (Proibido UPDATE e DELETE)
        conn = sqlite3.connect(db_path)
        update_blocked = False
        try:
            conn.execute("UPDATE immutable_audit_log SET guardrail_status = 'ACCEPTED' WHERE id = 2")
            conn.commit()
        except sqlite3.DatabaseError as exc:
            update_blocked = True
            assert "VIOLAÇÃO DE AUDITORIA" in str(exc)

        assert update_blocked, "O trigger deveria ter bloqueado UPDATE em registro imutável"

        delete_blocked = False
        try:
            conn.execute("DELETE FROM immutable_audit_log WHERE id = 1")
            conn.commit()
        except sqlite3.DatabaseError as exc:
            delete_blocked = True
            assert "VIOLAÇÃO DE AUDITORIA" in str(exc)

        assert delete_blocked, "O trigger deveria ter bloqueado DELETE em registro imutável"
        conn.close()

        # 4. Simulação de adulteração forçada direta (desabilitando triggers para teste)
        conn = sqlite3.connect(db_path)
        conn.execute("DROP TRIGGER trg_immutable_audit_no_update")
        conn.execute("UPDATE immutable_audit_log SET query_proposed = 'SELECT 1' WHERE id = 1")
        conn.commit()
        conn.close()

        # 5. Verificação da cadeia após adulteração — deve acusar quebra imediatamente
        tampered_valid, _, tampered_errors = ImmutableAuditService.verify_chain_integrity()
        assert tampered_valid is False
        assert len(tampered_errors) > 0
        assert "Adulteração detectada" in tampered_errors[0] or "Quebra de encadeamento" in tampered_errors[0]
    finally:
        if db_path.exists():
            os.remove(db_path)


# ===========================================================================
# 6. Observabilidade & Prometheus Metrics
# ===========================================================================

def test_prometheus_metrics_and_baseline_alert():
    """Valida o formato de exposição do Prometheus e o detector de anomalia de baseline."""
    collector = MetricsCollector(rejection_rate_baseline=0.20)

    # Registra 8 queries de sucesso e 2 bloqueadas (taxa de 20%)
    for _ in range(8):
        collector.record_query("success", "Varejo", latency_ms=45.0)

    collector.record_query("blocked", "Varejo", latency_ms=12.0, reason_type="sql_guardrail")
    collector.record_query("blocked", "Fiscal", latency_ms=14.0, reason_type="ast_complexity")

    # Verifica baseline
    is_exceeded, current_ratio, baseline = collector.is_baseline_exceeded()
    assert current_ratio == 0.20
    assert is_exceeded is False, "Não deve alertar quando taxa <= baseline"

    # Adiciona mais 2 rejeições para ultrapassar o baseline (> 30%)
    collector.record_query("blocked", "Corporativo", latency_ms=8.0, reason_type="circuit_breaker")
    collector.record_query("blocked", "Contabil", latency_ms=9.0, reason_type="ddl_injection")

    is_exceeded_now, new_ratio, _ = collector.is_baseline_exceeded()
    assert is_exceeded_now is True
    assert new_ratio > 0.20

    # Gera payload Prometheus
    payload = collector.generate_prometheus_exposition()
    assert "# HELP sql_agent_queries_total" in payload
    assert 'sql_agent_queries_total{status="success",bu="Varejo"} 8' in payload
    assert "# HELP sql_agent_execution_latency_ms" in payload
    assert "sql_agent_rejection_rate_ratio" in payload


# ===========================================================================
# Execução Principal
# ===========================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Executando Suite de Testes de Segurança Avançada & Observabilidade...")
    print("=" * 70)

    test_read_only_database_connection()
    print(" [1.1] Conexão Read-Only em Defesa em Profundidade: APROVADO")

    test_parameterized_execution()
    print(" [1.2] Prepared Statements e Parametrização Segura: APROVADO")

    test_ast_max_joins_limit()
    print(" [2.1] Limite AST de JOINs (máx 3): APROVADO")

    test_ast_max_subqueries_limit()
    print(" [2.2] Limite AST de Subqueries Aninhadas (máx 2): APROVADO")

    test_explain_cost_rejection()
    print(" [2.3] EXPLAIN Pre-execution Cost Check & Cartesian Detection: APROVADO")

    test_byte_size_cap()
    print(" [2.4] Cap de Memória em Tamanho de Resultado (Bytes): APROVADO")

    test_auto_limit_100_enforcement()
    print(" [2.5] Auto LIMIT 100 Enforcement (Injeção e Capping): APROVADO")

    test_ast_allowlist_tables_and_columns()
    print(" [3.1] Allowlist AST de Tabelas e Colunas Restritas: APROVADO")

    test_pii_redactor()
    print(" [3.2] Redação de PII (CPF, Cartões, Emails, Telefones, Secrets): APROVADO")

    test_rate_limiter_sliding_window()
    print(" [4.1] Rate Limiting (Janela Deslizante de 60s): APROVADO")

    test_security_circuit_breaker_trip()
    print(" [4.2] Security Circuit Breaker (Trip em 3 violações): APROVADO")

    test_immutable_audit_log_and_tamper_detection()
    print(" [5.1] Trilha de Auditoria Imutável (SHA-256 Hash Chain + Triggers): APROVADO")

    test_prometheus_metrics_and_baseline_alert()
    print(" [6.1] Métricas Prometheus (/metrics) e Alerta de Baseline: APROVADO")

    print("=" * 70)
    print(" TODOS OS TESTES PASSARAM COM 100% DE SUCESSO!")
    print("=" * 70)
