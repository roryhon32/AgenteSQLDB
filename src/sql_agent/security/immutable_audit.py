"""
immutable_audit.py — Trilha de Auditoria Imutável com Hash Encadeado (Hash Chain / Merkle-like).

Garante conformidade com o princípio de integridade e não-repúdio:
- Cada registro armazena o SHA-256 do registro anterior (hash encadeado).
- Tabela append-only com triggers no SQLite proibindo UPDATE e DELETE.
- Método de verificação matemática da cadeia para detecção de qualquer adulteração retroativa.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .pii_redactor import PIIRedactor

GENESIS_HASH = "0" * 64
DEFAULT_AUDIT_DB = Path(__file__).resolve().parent.parent.parent.parent / "data" / "users.db"


class ImmutableAuditService:
    """Serviço de gravação e verificação de integridade da trilha de auditoria com hash encadeado."""

    _db_path: Path = DEFAULT_AUDIT_DB

    @classmethod
    def set_db_path(cls, path: Path) -> None:
        cls._db_path = path

    @classmethod
    def _init_db(cls, conn: sqlite3.Connection) -> None:
        """Cria a tabela imutável e triggers de proteção contra deleção ou alteração."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS immutable_audit_log (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp          TEXT NOT NULL,
                user_id            INTEGER NOT NULL,
                username           TEXT NOT NULL,
                user_session       TEXT,
                user_bu            TEXT NOT NULL,
                query_proposed     TEXT NOT NULL,
                guardrail_status   TEXT NOT NULL, -- 'ACCEPTED' ou 'REJECTED'
                rejection_reason   TEXT,
                risk_type          TEXT,
                execution_time_ms  REAL NOT NULL,
                rows_returned      INTEGER DEFAULT 0,
                previous_hash      TEXT NOT NULL,
                entry_hash         TEXT NOT NULL UNIQUE
            );
        """)

        # Trigger para garantir que a tabela seja ESTRITAMENTE APPEND-ONLY (Proibido UPDATE)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_immutable_audit_no_update
            BEFORE UPDATE ON immutable_audit_log
            BEGIN
                SELECT RAISE(FAIL, 'VIOLAÇÃO DE AUDITORIA: Registros imutáveis não podem ser modificados.');
            END;
        """)

        # Trigger para garantir que nenhum registro seja apagado (Proibido DELETE)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_immutable_audit_no_delete
            BEFORE DELETE ON immutable_audit_log
            BEGIN
                SELECT RAISE(FAIL, 'VIOLAÇÃO DE AUDITORIA: Registros imutáveis não podem ser removidos.');
            END;
        """)
        conn.commit()

    @classmethod
    def _compute_hash(
        cls,
        previous_hash: str,
        timestamp: str,
        user_id: int,
        username: str,
        user_bu: str,
        query_proposed: str,
        guardrail_status: str,
        rejection_reason: Optional[str],
        execution_time_ms: float,
        rows_returned: int
    ) -> str:
        """Calcula o hash SHA-256 do registro encadeado ao hash anterior."""
        payload = (
            f"{previous_hash}|"
            f"{timestamp}|"
            f"{user_id}|"
            f"{username}|"
            f"{user_bu}|"
            f"{query_proposed.strip()}|"
            f"{guardrail_status.upper()}|"
            f"{rejection_reason or ''}|"
            f"{execution_time_ms:.2f}|"
            f"{rows_returned}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def record_entry(
        cls,
        user_id: int,
        username: str,
        user_bu: str,
        query_proposed: str,
        guardrail_status: str,  # 'ACCEPTED' ou 'REJECTED'
        execution_time_ms: float,
        rejection_reason: Optional[str] = None,
        risk_type: Optional[str] = None,
        rows_returned: int = 0,
        user_session: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Adiciona um novo registro à trilha imutável com mascaramento de PII e hash encadeado.
        """
        cls._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(cls._db_path)
        cls._init_db(conn)

        try:
            # 1. Pega o hash do registro mais recente para encadear
            cursor = conn.cursor()
            cursor.execute("SELECT entry_hash FROM immutable_audit_log ORDER BY id DESC LIMIT 1")
            last_row = cursor.fetchone()
            previous_hash = last_row[0] if last_row else GENESIS_HASH

            # 2. Redige PII da query proposta antes de gravar na auditoria
            redacted_query = PIIRedactor.redact_text(query_proposed)
            timestamp = datetime.now(timezone.utc).isoformat()

            # 3. Calcula o hash da entrada
            entry_hash = cls._compute_hash(
                previous_hash=previous_hash,
                timestamp=timestamp,
                user_id=user_id,
                username=username,
                user_bu=user_bu,
                query_proposed=redacted_query,
                guardrail_status=guardrail_status,
                rejection_reason=rejection_reason,
                execution_time_ms=execution_time_ms,
                rows_returned=rows_returned
            )

            # 4. Grava no banco imutável
            cursor.execute("""
                INSERT INTO immutable_audit_log (
                    timestamp, user_id, username, user_session, user_bu,
                    query_proposed, guardrail_status, rejection_reason, risk_type,
                    execution_time_ms, rows_returned, previous_hash, entry_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp, user_id, username, user_session or f"sess_{user_id}_{int(time.time())}", user_bu,
                redacted_query, guardrail_status.upper(), rejection_reason, risk_type,
                round(execution_time_ms, 2), rows_returned, previous_hash, entry_hash
            ))
            conn.commit()

            return {
                "id": cursor.lastrowid,
                "timestamp": timestamp,
                "previous_hash": previous_hash,
                "entry_hash": entry_hash,
                "status": guardrail_status.upper()
            }
        finally:
            conn.close()

    @classmethod
    def verify_chain_integrity(cls) -> Tuple[bool, int, List[str]]:
        """
        Percorre toda a trilha do bloco gênese ao topo e valida cada elo da cadeia de hash.
        Retorna: (valido: bool, total_registros: int, erros: List[str])
        """
        if not cls._db_path.exists():
            return True, 0, []

        conn = sqlite3.connect(cls._db_path)
        cls._init_db(conn)

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, timestamp, user_id, username, user_bu,
                       query_proposed, guardrail_status, rejection_reason,
                       execution_time_ms, rows_returned, previous_hash, entry_hash
                FROM immutable_audit_log
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()

            if not rows:
                return True, 0, []

            expected_prev_hash = GENESIS_HASH
            errors: List[str] = []

            for row in rows:
                (row_id, ts, u_id, uname, u_bu, q, status, reason, exec_time, rows_count, prev_h, curr_h) = row

                # 1. Valida encadeamento com o bloco anterior
                if prev_h != expected_prev_hash:
                    errors.append(
                        f"Quebra de encadeamento no Registro #{row_id}: previous_hash esperado '{expected_prev_hash}', "
                        f"encontrado '{prev_h}'."
                    )

                # 2. Recalcula o hash do bloco com base nos dados brutos
                recalculated_hash = cls._compute_hash(
                    previous_hash=prev_h,
                    timestamp=ts,
                    user_id=u_id,
                    username=uname,
                    user_bu=u_bu,
                    query_proposed=q,
                    guardrail_status=status,
                    rejection_reason=reason,
                    execution_time_ms=exec_time,
                    rows_returned=rows_count
                )

                if recalculated_hash != curr_h:
                    errors.append(
                        f"Adulteração detectada no Registro #{row_id}: hash armazenado '{curr_h}' "
                        f"não coincide com hash recalculado '{recalculated_hash}'."
                    )

                expected_prev_hash = curr_h

            is_valid = len(errors) == 0
            return is_valid, len(rows), errors
        finally:
            conn.close()
