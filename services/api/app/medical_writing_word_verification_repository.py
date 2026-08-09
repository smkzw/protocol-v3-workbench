from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from packages.contracts.workbench_contracts import MedicalWritingWordVerificationReceipt


TENANT_PLACEHOLDER = "kangzhe_local"


class WordVerificationReceiptError(ValueError):
    """Base error for the isolated Word receipt store."""


class WordVerificationReceiptIdempotencyConflict(WordVerificationReceiptError):
    pass


class WordVerificationReceiptStaleError(WordVerificationReceiptError):
    pass


@dataclass(frozen=True)
class MedicalWritingWordVerificationCommitResult:
    receipt: MedicalWritingWordVerificationReceipt
    request_id: str
    audit_id: str
    replayed: bool = False


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class MedicalWritingWordVerificationRepository:
    """Isolated append-only receipt persistence.

    This repository intentionally owns a separate SQLite file from the shared
    medical-writing runtime store. It can therefore be proved with a temporary
    database without changing shared schema migrations or concurrent subsystem
    state.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS medical_writing_word_verification_receipts (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    verification_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    source_snapshot_sha256 TEXT NOT NULL,
                    docx_sha256 TEXT NOT NULL,
                    pdf_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status = 'word_verified'),
                    audit_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, verification_id),
                    UNIQUE (tenant_id, project_id, document_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_mw_word_receipt_document
                    ON medical_writing_word_verification_receipts(
                        tenant_id, project_id, document_id, created_at
                    );
                CREATE TABLE IF NOT EXISTS medical_writing_word_verification_audit (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    verification_id TEXT NOT NULL,
                    audit_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, audit_id),
                    FOREIGN KEY (tenant_id, project_id, verification_id)
                    REFERENCES medical_writing_word_verification_receipts(
                        tenant_id, project_id, verification_id
                    )
                );
                CREATE INDEX IF NOT EXISTS idx_mw_word_receipt_audit_document
                    ON medical_writing_word_verification_audit(
                        tenant_id, project_id, document_id, created_at
                    );
                CREATE TRIGGER IF NOT EXISTS trg_mw_word_receipt_no_update
                BEFORE UPDATE ON medical_writing_word_verification_receipts BEGIN
                    SELECT RAISE(ABORT, 'Word verification receipts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_mw_word_receipt_no_delete
                BEFORE DELETE ON medical_writing_word_verification_receipts BEGIN
                    SELECT RAISE(ABORT, 'Word verification receipts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_mw_word_receipt_audit_no_update
                BEFORE UPDATE ON medical_writing_word_verification_audit BEGIN
                    SELECT RAISE(ABORT, 'Word verification receipt audits are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_mw_word_receipt_audit_no_delete
                BEFORE DELETE ON medical_writing_word_verification_audit BEGIN
                    SELECT RAISE(ABORT, 'Word verification receipt audits are immutable');
                END;
                """
            )

    @staticmethod
    def _request_hash(receipt: MedicalWritingWordVerificationReceipt) -> str:
        return _payload_hash(receipt.model_dump(mode="json"))

    def save(
        self,
        receipt: MedicalWritingWordVerificationReceipt,
        *,
        expected_source_snapshot_sha256: str,
        expected_docx_sha256: str,
        actor: str,
        canonical_page_hash_metadata: Optional[Dict[str, Any]] = None,
    ) -> MedicalWritingWordVerificationCommitResult:
        if receipt.source_snapshot_sha256 != expected_source_snapshot_sha256:
            raise WordVerificationReceiptStaleError(
                "Word verification receipt source snapshot is stale"
            )
        if receipt.docx_sha256 != expected_docx_sha256:
            raise WordVerificationReceiptStaleError(
                "Word verification receipt DOCX hash is not current"
            )
        actor = str(actor or "").strip()
        if not actor:
            raise ValueError("Word verification receipt actor is required")
        request_hash = self._request_hash(receipt)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM medical_writing_word_verification_receipts
                WHERE tenant_id = ? AND project_id = ? AND document_id = ?
                  AND idempotency_key = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    receipt.project_id,
                    receipt.document_id,
                    receipt.idempotency_key,
                ),
            ).fetchone()
            if existing is not None:
                if str(existing["request_hash"]) != request_hash:
                    raise WordVerificationReceiptIdempotencyConflict(
                        "Word verification idempotency key reused with a different payload"
                    )
                connection.rollback()
                return MedicalWritingWordVerificationCommitResult(
                    receipt=MedicalWritingWordVerificationReceipt.model_validate(
                        json.loads(existing["payload_json"])
                    ),
                    request_id=str(existing["verification_id"]),
                    audit_id=str(existing["audit_id"]),
                    replayed=True,
                )
            existing_id = connection.execute(
                """
                SELECT verification_id FROM medical_writing_word_verification_receipts
                WHERE tenant_id = ? AND project_id = ? AND verification_id = ?
                """,
                (TENANT_PLACEHOLDER, receipt.project_id, receipt.verification_id),
            ).fetchone()
            if existing_id is not None:
                raise WordVerificationReceiptIdempotencyConflict(
                    "Word verification id already exists with a different idempotency key"
                )
            audit_id = f"audit_word_verification_{uuid4().hex}"
            created_at = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                INSERT INTO medical_writing_word_verification_receipts(
                    tenant_id, project_id, document_id, verification_id,
                    idempotency_key, request_hash, source_snapshot_sha256,
                    docx_sha256, pdf_sha256, status, audit_id, created_at,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    receipt.project_id,
                    receipt.document_id,
                    receipt.verification_id,
                    receipt.idempotency_key,
                    request_hash,
                    receipt.source_snapshot_sha256,
                    receipt.docx_sha256,
                    receipt.pdf_sha256,
                    receipt.status,
                    audit_id,
                    created_at,
                    _canonical_json(receipt.model_dump(mode="json")),
                ),
            )
            connection.execute(
                """
                INSERT INTO medical_writing_word_verification_audit(
                    tenant_id, project_id, document_id, verification_id,
                    audit_id, action, actor, created_at, detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    receipt.project_id,
                    receipt.document_id,
                    receipt.verification_id,
                    audit_id,
                    "word_verification_receipt_committed",
                    actor,
                    created_at,
                    _canonical_json(
                        {
                            "source_snapshot_sha256": receipt.source_snapshot_sha256,
                            "docx_sha256": receipt.docx_sha256,
                            "pdf_sha256": receipt.pdf_sha256,
                            "evidence_manifest_sha256": receipt.evidence_manifest_sha256,
                            "idempotency_key": receipt.idempotency_key,
                            "canonical_pdf_page_hash": (
                                dict(canonical_page_hash_metadata)
                                if canonical_page_hash_metadata
                                else None
                            ),
                        }
                    ),
                ),
            )
            connection.commit()
            return MedicalWritingWordVerificationCommitResult(
                receipt=receipt,
                request_id=receipt.verification_id,
                audit_id=audit_id,
                replayed=False,
            )
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise WordVerificationReceiptError(
                f"Word verification receipt persistence conflict: {exc}"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(
        self,
        project_id: str,
        document_id: str,
        *,
        verification_id: Optional[str] = None,
        expected_source_snapshot_sha256: str = "",
    ) -> Optional[MedicalWritingWordVerificationReceipt]:
        query = """
            SELECT payload_json FROM medical_writing_word_verification_receipts
            WHERE tenant_id = ? AND project_id = ? AND document_id = ?
        """
        params: List[Any] = [TENANT_PLACEHOLDER, project_id, document_id]
        if verification_id:
            query += " AND verification_id = ?"
            params.append(verification_id)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        if row is None:
            return None
        receipt = MedicalWritingWordVerificationReceipt.model_validate(
            json.loads(row["payload_json"])
        )
        if (
            expected_source_snapshot_sha256
            and receipt.source_snapshot_sha256 != expected_source_snapshot_sha256
        ):
            raise WordVerificationReceiptStaleError(
                "stored Word verification receipt is stale for the current snapshot"
            )
        return receipt

    def audit_events(self, project_id: str, document_id: str) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT verification_id, audit_id, action, actor, created_at, detail_json
                FROM medical_writing_word_verification_audit
                WHERE tenant_id = ? AND project_id = ? AND document_id = ?
                ORDER BY created_at, rowid
                """,
                (TENANT_PLACEHOLDER, project_id, document_id),
            ).fetchall()
        return [
            {
                "verification_id": row["verification_id"],
                "audit_id": row["audit_id"],
                "action": row["action"],
                "actor": row["actor"],
                "created_at": row["created_at"],
                "detail": json.loads(row["detail_json"]),
            }
            for row in rows
        ]
