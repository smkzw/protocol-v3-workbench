from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from uuid import uuid4

from packages.contracts.workbench_contracts import (
    ApprovalDecisionRecord,
    ApprovalGate,
    ApprovalState,
    AuditEvent,
    EvidenceAiRevisionThread,
    EvidencePicosDecisionRecord,
    EvidencePicosSnapshot,
    EvidencePicosWorkingState,
    EvidencePicosWritingHandoff,
    EvidenceReviewRecord,
    MedicalWritingContentDispositionRecord,
    MedicalWritingWorkingCopy,
    RevisionThread,
    RuxRiskDispositionRecord,
    SafetyReviewRecord,
)


TENANT_PLACEHOLDER = "kangzhe_local"
CURRENT_SCHEMA_VERSION = 16
IDENTITY_ASSURANCE = "unverified_client_claim"


class RuntimeStoreError(ValueError):
    pass


class IdempotencyConflictError(RuntimeStoreError):
    pass


class StaleRuntimeStateError(RuntimeStoreError):
    pass


class RuntimeStoreIntegrityError(RuntimeStoreError):
    pass


@dataclass(frozen=True)
class RuntimeCommitResult:
    request_id: str
    replayed: bool = False


@dataclass(frozen=True)
class EligibilityReviewCommitResult:
    request_id: str
    record_id: str
    state_revision: int
    replayed: bool = False


@dataclass(frozen=True)
class EligibilityAiBatchCommitResult:
    request_id: str
    state_revisions: Dict[str, int]
    replayed: bool = False


@dataclass(frozen=True)
class EligibilityVisualQcCommitResult:
    request_id: str
    qc_record_id: str
    qc_revision: int
    result: str
    replayed: bool = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _execute_sql_script_in_transaction(
    connection: sqlite3.Connection, script: str
) -> None:
    statement = ""
    for line in script.splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeStoreIntegrityError("incomplete SQLite migration statement")


def dump_sqlite_database(db_path: Path) -> Dict[str, Any]:
    """Return a portable, integrity-checked logical dump of a SQLite database."""

    path = Path(db_path)
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeStoreIntegrityError(f"sqlite database does not exist: {path}")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                raise RuntimeStoreIntegrityError(
                    f"sqlite integrity_check failed before dump: {integrity}"
                )
            statements = list(connection.iterdump())
    except sqlite3.DatabaseError as exc:
        raise RuntimeStoreIntegrityError(
            f"sqlite database cannot be dumped: {exc}"
        ) from exc
    payload = {
        "format": "sqlite_iterdump_v1",
        "statements": statements,
    }
    payload["content_sha256"] = _payload_hash(payload)
    return payload


def load_sqlite_database(
    db_path: Path,
    payload: Dict[str, Any],
    *,
    replace: bool = False,
) -> None:
    """Validate and atomically restore a logical SQLite dump."""

    if payload.get("format") != "sqlite_iterdump_v1":
        raise RuntimeStoreIntegrityError("unsupported sqlite dump format")
    statements = payload.get("statements")
    if not isinstance(statements, list) or not statements or not all(
        isinstance(statement, str) for statement in statements
    ):
        raise RuntimeStoreIntegrityError("sqlite dump statements are invalid")
    expected_hash = payload.get("content_sha256")
    actual_hash = _payload_hash(
        {"format": payload["format"], "statements": statements}
    )
    if expected_hash != actual_hash:
        raise RuntimeStoreIntegrityError("sqlite dump content hash mismatch")

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0 and not replace:
        raise RuntimeStoreIntegrityError(
            f"sqlite database already exists and replace is false: {path}"
        )

    restore_path = path.with_name(f".{path.name}.{uuid4().hex}.restore")
    try:
        with sqlite3.connect(restore_path, timeout=30.0) as connection:
            connection.executescript("\n".join(statements))
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                raise RuntimeStoreIntegrityError(
                    f"sqlite integrity_check failed after restore: {integrity}"
                )
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{path}{suffix}")
            if sidecar.exists():
                sidecar.unlink()
        os.replace(restore_path, path)
    except sqlite3.DatabaseError as exc:
        raise RuntimeStoreIntegrityError(
            f"sqlite dump cannot be restored: {exc}"
        ) from exc
    finally:
        if restore_path.exists():
            restore_path.unlink()


class SqliteRuntimeStore:
    """Transactional runtime persistence for the first migrated medical workflow.

    Actor values are compatibility claims from the current unauthenticated client.
    They are intentionally labelled as unverified and are not electronic signatures.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        fault_injector: Optional[Callable[[str], None]] = None,
        legacy_gate_path: Optional[Path] = None,
        legacy_decision_path: Optional[Path] = None,
        legacy_audit_path: Optional[Path] = None,
        legacy_disposition_path: Optional[Path] = None,
        controlled_artifact_policy_resolver: Optional[
            Callable[[str, str, Dict[str, Any]], Dict[str, Any]]
        ] = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.fault_injector = fault_injector
        self.controlled_artifact_policy_resolver = controlled_artifact_policy_resolver
        self._legacy_report = {"valid_lines": 0, "malformed_lines": 0, "invalid_records": 0}
        try:
            self._initialize()
            self._import_legacy(
                gate_path=legacy_gate_path,
                decision_path=legacy_decision_path,
                audit_path=legacy_audit_path,
                disposition_path=legacy_disposition_path,
            )
        except sqlite3.DatabaseError as exc:
            raise RuntimeStoreIntegrityError(
                f"sqlite runtime database is unavailable or invalid: {exc}"
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        needs_backup = self.db_path.exists() and self.db_path.stat().st_size > 0
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            migration_versions = [
                int(row["version"])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()
            ]
            current_version = migration_versions[-1] if migration_versions else 0
            expected_versions = list(range(1, current_version + 1))
            if migration_versions != expected_versions:
                missing_versions = sorted(set(expected_versions) - set(migration_versions))
                contiguous_version = 0
                for version in migration_versions:
                    if version != contiguous_version + 1:
                        break
                    contiguous_version = version
                if needs_backup:
                    self._backup_before_migration(connection, contiguous_version)
                raise RuntimeStoreIntegrityError(
                    "non-contiguous schema migration history; missing versions: "
                    + ", ".join(str(version) for version in missing_versions)
                )
            if current_version > CURRENT_SCHEMA_VERSION:
                raise RuntimeStoreIntegrityError(
                    f"database schema {current_version} is newer than supported {CURRENT_SCHEMA_VERSION}"
                )
            if current_version < CURRENT_SCHEMA_VERSION and needs_backup:
                self._backup_before_migration(connection, current_version)
            if current_version < 1:
                self._apply_v1(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, _utc_now().isoformat()),
                )
                current_version = 1
            if current_version < 2:
                self._apply_v2(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (2, _utc_now().isoformat()),
                )
                current_version = 2
            if current_version < 3:
                self._apply_v3(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (3, _utc_now().isoformat()),
                )
                current_version = 3
            if current_version < 4:
                self._apply_v4(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (4, _utc_now().isoformat()),
                )
                current_version = 4
            if current_version < 5:
                self._apply_v5(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (5, _utc_now().isoformat()),
                )
                current_version = 5
            if current_version < 6:
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._apply_v6(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (6, _utc_now().isoformat()),
                    )
                    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise RuntimeStoreIntegrityError(
                            f"sqlite integrity_check failed during v6 migration: {result}"
                        )
                    foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
                    if foreign_key_rows:
                        raise RuntimeStoreIntegrityError(
                            "sqlite foreign_key_check failed during v6 migration"
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                current_version = 6
            if current_version < 7:
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._apply_v7(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (7, _utc_now().isoformat()),
                    )
                    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise RuntimeStoreIntegrityError(
                            f"sqlite integrity_check failed during v7 migration: {result}"
                        )
                    foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
                    if foreign_key_rows:
                        raise RuntimeStoreIntegrityError(
                            "sqlite foreign_key_check failed during v7 migration"
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                current_version = 7
            if current_version < 8:
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._apply_v8(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (8, _utc_now().isoformat()),
                    )
                    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise RuntimeStoreIntegrityError(
                            f"sqlite integrity_check failed during v8 migration: {result}"
                        )
                    foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
                    if foreign_key_rows:
                        raise RuntimeStoreIntegrityError(
                            "sqlite foreign_key_check failed during v8 migration"
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                current_version = 8
            if current_version < 9:
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._apply_v9(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (9, _utc_now().isoformat()),
                    )
                    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise RuntimeStoreIntegrityError(
                            f"sqlite integrity_check failed during v9 migration: {result}"
                        )
                    foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
                    if foreign_key_rows:
                        raise RuntimeStoreIntegrityError(
                            "sqlite foreign_key_check failed during v9 migration"
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                current_version = 9
            if current_version < 10:
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._apply_v10(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (10, _utc_now().isoformat()),
                    )
                    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise RuntimeStoreIntegrityError(
                            f"sqlite integrity_check failed during v10 migration: {result}"
                        )
                    foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
                    if foreign_key_rows:
                        raise RuntimeStoreIntegrityError(
                            "sqlite foreign_key_check failed during v10 migration"
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                current_version = 10
            if current_version < 11:
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._apply_v11(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (11, _utc_now().isoformat()),
                    )
                    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise RuntimeStoreIntegrityError(
                            f"sqlite integrity_check failed during v11 migration: {result}"
                        )
                    foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
                    if foreign_key_rows:
                        raise RuntimeStoreIntegrityError(
                            "sqlite foreign_key_check failed during v11 migration"
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                current_version = 11
            if current_version < 12:
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._apply_v12(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (12, _utc_now().isoformat()),
                    )
                    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise RuntimeStoreIntegrityError(
                            f"sqlite integrity_check failed during v12 migration: {result}"
                        )
                    foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
                    if foreign_key_rows:
                        raise RuntimeStoreIntegrityError(
                            "sqlite foreign_key_check failed during v12 migration"
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                current_version = 12
            if current_version < 13:
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._apply_v13(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (13, _utc_now().isoformat()),
                    )
                    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise RuntimeStoreIntegrityError(
                            f"sqlite integrity_check failed during v13 migration: {result}"
                        )
                    foreign_key_rows = connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchall()
                    if foreign_key_rows:
                        raise RuntimeStoreIntegrityError(
                            "sqlite foreign_key_check failed during v13 migration"
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                current_version = 13
            if current_version < 14:
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._apply_v14(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (14, _utc_now().isoformat()),
                    )
                    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise RuntimeStoreIntegrityError(
                            f"sqlite integrity_check failed during v14 migration: {result}"
                        )
                    foreign_key_rows = connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchall()
                    if foreign_key_rows:
                        raise RuntimeStoreIntegrityError(
                            "sqlite foreign_key_check failed during v14 migration"
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                current_version = 14
            if current_version < 15:
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._apply_v15(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (15, _utc_now().isoformat()),
                    )
                    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise RuntimeStoreIntegrityError(
                            f"sqlite integrity_check failed during v15 migration: {result}"
                        )
                    foreign_key_rows = connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchall()
                    if foreign_key_rows:
                        raise RuntimeStoreIntegrityError(
                            "sqlite foreign_key_check failed during v15 migration"
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                current_version = 15
            if current_version < 16:
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._apply_v16(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (16, _utc_now().isoformat()),
                    )
                    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise RuntimeStoreIntegrityError(
                            f"sqlite integrity_check failed during v16 migration: {result}"
                        )
                    foreign_key_rows = connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchall()
                    if foreign_key_rows:
                        raise RuntimeStoreIntegrityError(
                            "sqlite foreign_key_check failed during v16 migration"
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeStoreIntegrityError(f"sqlite integrity_check failed: {result}")

    def _backup_before_migration(
        self, source_connection: sqlite3.Connection, version: int
    ) -> None:
        stamp = _utc_now().strftime("%Y%m%d%H%M%S")
        backup_path = self.db_path.with_suffix(self.db_path.suffix + f".v{version}.{stamp}.bak")
        with sqlite3.connect(backup_path) as backup_connection:
            source_connection.backup(backup_connection)

    def _apply_v1(self, connection: sqlite3.Connection) -> None:
        _execute_sql_script_in_transaction(
            connection,
            """
            CREATE TABLE IF NOT EXISTS rux_disposition_records (
                tenant_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                source_version TEXT NOT NULL,
                new_state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, record_id)
            );
            CREATE INDEX IF NOT EXISTS idx_rux_disposition_latest
                ON rux_disposition_records(tenant_id, project_id, item_id, source_version, created_at);

            CREATE TABLE IF NOT EXISTS approval_gates (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                approval_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, approval_id)
            );

            CREATE TABLE IF NOT EXISTS approval_decisions (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                approval_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, decision_id)
            );

            CREATE TABLE IF NOT EXISTS approval_audit_events (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                audit_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, audit_id)
            );

            CREATE TABLE IF NOT EXISTS runtime_audit_chain (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                sequence_no INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                operation TEXT NOT NULL,
                actor TEXT NOT NULL,
                identity_assurance TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, sequence_no),
                UNIQUE (tenant_id, project_id, event_id)
            );

            CREATE TABLE IF NOT EXISTS idempotency_records (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                request_id TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, operation, idempotency_key)
            );
            """,
        )
    def _apply_v2(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS medical_writing_revision_threads (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                section_id TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, thread_id)
            );
            CREATE INDEX IF NOT EXISTS idx_medical_writing_threads_section
                ON medical_writing_revision_threads(
                    tenant_id, project_id, document_id, section_id, updated_at
                );

            CREATE TABLE IF NOT EXISTS medical_writing_revision_snapshots (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, snapshot_id)
            );
            CREATE INDEX IF NOT EXISTS idx_medical_writing_snapshots_thread
                ON medical_writing_revision_snapshots(
                    tenant_id, project_id, thread_id, created_at
                );

            CREATE TABLE IF NOT EXISTS workflow_audit_events (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                audit_id TEXT NOT NULL,
                workflow_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, audit_id)
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_audit_events_type
                ON workflow_audit_events(tenant_id, project_id, workflow_type, created_at);
            """
        )

    def _apply_v3(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS medical_writing_working_copies (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                working_copy_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                section_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                approval_state TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, working_copy_id),
                UNIQUE (tenant_id, project_id, document_id, section_id)
            );
            CREATE INDEX IF NOT EXISTS idx_medical_writing_working_copy_section
                ON medical_writing_working_copies(
                    tenant_id, project_id, document_id, section_id, revision
                );

            CREATE TABLE IF NOT EXISTS medical_writing_working_copy_snapshots (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                working_copy_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                snapshot_type TEXT NOT NULL,
                audit_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, snapshot_id)
            );
            CREATE INDEX IF NOT EXISTS idx_medical_writing_working_copy_snapshots
                ON medical_writing_working_copy_snapshots(
                    tenant_id, project_id, working_copy_id, created_at
                );

            CREATE TRIGGER IF NOT EXISTS trg_medical_writing_working_copy_snapshot_no_update
            BEFORE UPDATE ON medical_writing_working_copy_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'medical writing working copy snapshots are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_medical_writing_working_copy_snapshot_no_delete
            BEFORE DELETE ON medical_writing_working_copy_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'medical writing working copy snapshots are immutable');
            END;
            """
        )

    def _apply_v4(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS evidence_review_records (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                package_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                action TEXT NOT NULL,
                previous_revision INTEGER NOT NULL CHECK (previous_revision >= 0),
                new_revision INTEGER NOT NULL CHECK (new_revision = previous_revision + 1),
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, record_id),
                UNIQUE (tenant_id, project_id, package_id, evidence_id, new_revision)
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_review_latest
                ON evidence_review_records(
                    tenant_id, project_id, package_id, evidence_id,
                    new_revision DESC, created_at DESC
                );
            CREATE INDEX IF NOT EXISTS idx_evidence_review_package_action
                ON evidence_review_records(
                    tenant_id, project_id, package_id, action, created_at
                );

            CREATE TABLE IF NOT EXISTS evidence_picos_working_states (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                working_state_id TEXT NOT NULL,
                package_id TEXT NOT NULL,
                evidence_package_hash TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 0),
                approval_state TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, working_state_id),
                UNIQUE (tenant_id, project_id, package_id)
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_picos_working_state_package
                ON evidence_picos_working_states(
                    tenant_id, project_id, package_id, revision DESC
                );

            CREATE TABLE IF NOT EXISTS evidence_picos_decision_records (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                package_id TEXT NOT NULL,
                working_state_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                action TEXT NOT NULL,
                previous_revision INTEGER NOT NULL CHECK (previous_revision >= 0),
                new_revision INTEGER NOT NULL CHECK (new_revision = previous_revision + 1),
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, record_id),
                UNIQUE (tenant_id, project_id, package_id, new_revision)
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_picos_decisions_package
                ON evidence_picos_decision_records(
                    tenant_id, project_id, package_id, new_revision, created_at
                );
            CREATE INDEX IF NOT EXISTS idx_evidence_picos_decisions_question
                ON evidence_picos_decision_records(
                    tenant_id, project_id, package_id, question_id, created_at
                );

            CREATE TABLE IF NOT EXISTS evidence_picos_working_state_snapshots (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                package_id TEXT NOT NULL,
                working_state_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                snapshot_type TEXT NOT NULL,
                approval_id TEXT NOT NULL DEFAULT '',
                audit_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, snapshot_id)
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_picos_snapshots_state
                ON evidence_picos_working_state_snapshots(
                    tenant_id, project_id, working_state_id, revision, created_at
                );
            CREATE INDEX IF NOT EXISTS idx_evidence_picos_snapshots_approval
                ON evidence_picos_working_state_snapshots(
                    tenant_id, project_id, approval_id, snapshot_id
                );

            CREATE TABLE IF NOT EXISTS evidence_picos_writing_handoffs (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                handoff_id TEXT NOT NULL,
                package_id TEXT NOT NULL,
                working_state_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                approval_id TEXT NOT NULL,
                approved_revision INTEGER NOT NULL CHECK (approved_revision >= 1),
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, handoff_id)
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_picos_handoffs_package
                ON evidence_picos_writing_handoffs(
                    tenant_id, project_id, package_id, created_at
                );
            CREATE INDEX IF NOT EXISTS idx_evidence_picos_handoffs_approval
                ON evidence_picos_writing_handoffs(
                    tenant_id, project_id, approval_id, snapshot_id
                );

            CREATE TRIGGER IF NOT EXISTS trg_evidence_review_record_no_update
            BEFORE UPDATE ON evidence_review_records
            BEGIN
                SELECT RAISE(ABORT, 'evidence review records are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_evidence_review_record_no_delete
            BEFORE DELETE ON evidence_review_records
            BEGIN
                SELECT RAISE(ABORT, 'evidence review records are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_evidence_picos_decision_record_no_update
            BEFORE UPDATE ON evidence_picos_decision_records
            BEGIN
                SELECT RAISE(ABORT, 'evidence PICOS decision records are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_evidence_picos_decision_record_no_delete
            BEFORE DELETE ON evidence_picos_decision_records
            BEGIN
                SELECT RAISE(ABORT, 'evidence PICOS decision records are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_evidence_picos_snapshot_no_update
            BEFORE UPDATE ON evidence_picos_working_state_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'evidence PICOS snapshots are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_evidence_picos_snapshot_no_delete
            BEFORE DELETE ON evidence_picos_working_state_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'evidence PICOS snapshots are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_evidence_picos_handoff_no_update
            BEFORE UPDATE ON evidence_picos_writing_handoffs
            BEGIN
                SELECT RAISE(ABORT, 'evidence PICOS writing handoffs are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_evidence_picos_handoff_no_delete
            BEFORE DELETE ON evidence_picos_writing_handoffs
            BEGIN
                SELECT RAISE(ABORT, 'evidence PICOS writing handoffs are immutable');
            END;
            """
        )

    def _apply_v5(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS evidence_ai_revision_threads (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                package_id TEXT NOT NULL,
                anchor_type TEXT NOT NULL,
                anchor_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, thread_id)
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_ai_revision_threads_package
                ON evidence_ai_revision_threads(
                    tenant_id, project_id, package_id, updated_at, thread_id
                );
            CREATE INDEX IF NOT EXISTS idx_evidence_ai_revision_threads_anchor
                ON evidence_ai_revision_threads(
                    tenant_id, project_id, package_id, anchor_id, updated_at, thread_id
                );

            CREATE TABLE IF NOT EXISTS evidence_ai_revision_snapshots (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                package_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                action TEXT NOT NULL,
                audit_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, snapshot_id),
                UNIQUE (tenant_id, project_id, thread_id, revision)
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_ai_revision_snapshots_thread
                ON evidence_ai_revision_snapshots(
                    tenant_id, project_id, thread_id, revision, created_at
                );
            CREATE INDEX IF NOT EXISTS idx_evidence_ai_revision_snapshots_package
                ON evidence_ai_revision_snapshots(
                    tenant_id, project_id, package_id, created_at
                );

            CREATE TRIGGER IF NOT EXISTS trg_evidence_ai_revision_snapshot_no_update
            BEFORE UPDATE ON evidence_ai_revision_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'evidence AI revision snapshots are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_evidence_ai_revision_snapshot_no_delete
            BEFORE DELETE ON evidence_ai_revision_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'evidence AI revision snapshots are immutable');
            END;
            """
        )

    def _apply_v6(self, connection: sqlite3.Connection) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS eligibility_source_revisions (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                subject_source_revision TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                media_class TEXT NOT NULL,
                is_current INTEGER NOT NULL CHECK (is_current IN (0, 1)),
                created_at TEXT NOT NULL,
                PRIMARY KEY (
                    tenant_id, project_id, subject_id, source_id, source_revision
                )
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_eligibility_source_revisions_current
            ON eligibility_source_revisions(
                tenant_id, project_id, subject_id, is_current,
                subject_source_revision, source_id
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS eligibility_rule_revisions (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                rule_revision TEXT NOT NULL,
                criterion_uid TEXT NOT NULL,
                criterion_kind TEXT NOT NULL
                    CHECK (criterion_kind IN ('inclusion', 'exclusion')),
                source_rule_label TEXT,
                source_locator_json TEXT NOT NULL,
                normalized_text_hash TEXT NOT NULL,
                display_order INTEGER NOT NULL CHECK (display_order >= 0),
                is_current INTEGER NOT NULL CHECK (is_current IN (0, 1)),
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, rule_revision, criterion_uid)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_eligibility_rule_revisions_current
            ON eligibility_rule_revisions(
                tenant_id, project_id, is_current, rule_revision,
                criterion_kind, display_order
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS eligibility_evidence_spans (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                extraction_revision TEXT NOT NULL,
                locator_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                media_class TEXT NOT NULL,
                processing_state TEXT NOT NULL CHECK (
                    processing_state IN (
                        'not_started', 'queued', 'running', 'partial', 'completed',
                        'failed', 'needs_visual_qc', 'not_applicable'
                    )
                ),
                quality_state TEXT NOT NULL,
                extraction_confidence REAL,
                medical_verification_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (
                    tenant_id, project_id, subject_id, evidence_id, source_revision
                ),
                FOREIGN KEY (
                    tenant_id, project_id, subject_id, source_id, source_revision
                ) REFERENCES eligibility_source_revisions(
                    tenant_id, project_id, subject_id, source_id, source_revision
                )
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_eligibility_evidence_spans_source
            ON eligibility_evidence_spans(
                tenant_id, project_id, subject_id, source_id, source_revision,
                processing_state
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS eligibility_review_records (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                criterion_uid TEXT NOT NULL,
                record_id TEXT NOT NULL,
                criterion_kind TEXT NOT NULL
                    CHECK (criterion_kind IN ('inclusion', 'exclusion')),
                record_type TEXT NOT NULL
                    CHECK (record_type IN ('ai_draft', 'medical_action')),
                action TEXT NOT NULL CHECK (
                    action IN (
                        'save_ai_draft', 'accept_ai_draft', 'revise_decision',
                        'request_evidence', 'defer_review',
                        'reset_after_source_change'
                    )
                ),
                action_decision TEXT,
                ai_draft_decision TEXT,
                medical_decision TEXT,
                evidence_processing_state TEXT NOT NULL CHECK (
                    evidence_processing_state IN (
                        'not_started', 'queued', 'running', 'partial', 'completed',
                        'failed', 'needs_visual_qc', 'not_applicable'
                    )
                ),
                rule_revision TEXT NOT NULL,
                subject_source_revision TEXT NOT NULL,
                previous_state_revision INTEGER NOT NULL
                    CHECK (previous_state_revision >= 0),
                new_state_revision INTEGER NOT NULL
                    CHECK (new_state_revision = previous_state_revision + 1),
                evidence_ids_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                actor TEXT NOT NULL,
                identity_assurance TEXT NOT NULL,
                ai_draft_record_id TEXT,
                medical_record_id TEXT,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                request_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                CHECK (
                    action_decision IS NULL OR
                    (criterion_kind = 'inclusion' AND action_decision IN (
                        'met', 'not_met', 'insufficient_evidence',
                        'not_applicable', 'requires_investigator_judgment'
                    )) OR
                    (criterion_kind = 'exclusion' AND action_decision IN (
                        'absent', 'present', 'insufficient_evidence',
                        'not_applicable', 'requires_investigator_judgment'
                    ))
                ),
                PRIMARY KEY (tenant_id, project_id, record_id),
                UNIQUE (
                    tenant_id, project_id, subject_id, criterion_uid,
                    new_state_revision
                ),
                UNIQUE (
                    tenant_id, project_id, subject_id, criterion_uid,
                    idempotency_key
                ),
                FOREIGN KEY (
                    tenant_id, project_id, rule_revision, criterion_uid
                ) REFERENCES eligibility_rule_revisions(
                    tenant_id, project_id, rule_revision, criterion_uid
                )
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_eligibility_review_records_subject
            ON eligibility_review_records(
                tenant_id, project_id, subject_id, criterion_uid,
                new_state_revision, created_at
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS eligibility_review_state (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                criterion_uid TEXT NOT NULL,
                criterion_kind TEXT NOT NULL
                    CHECK (criterion_kind IN ('inclusion', 'exclusion')),
                rule_revision TEXT NOT NULL,
                subject_source_revision TEXT NOT NULL,
                state_revision INTEGER NOT NULL CHECK (state_revision >= 1),
                evidence_processing_state TEXT NOT NULL CHECK (
                    evidence_processing_state IN (
                        'not_started', 'queued', 'running', 'partial', 'completed',
                        'failed', 'needs_visual_qc', 'not_applicable'
                    )
                ),
                ai_draft_decision TEXT,
                medical_decision TEXT,
                latest_action TEXT NOT NULL,
                reason TEXT NOT NULL,
                evidence_ids_json TEXT NOT NULL,
                ai_draft_record_id TEXT,
                medical_record_id TEXT,
                latest_record_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (
                    (ai_draft_decision IS NULL OR
                        (criterion_kind = 'inclusion' AND ai_draft_decision IN (
                            'met', 'not_met', 'insufficient_evidence',
                            'not_applicable', 'requires_investigator_judgment'
                        )) OR
                        (criterion_kind = 'exclusion' AND ai_draft_decision IN (
                            'absent', 'present', 'insufficient_evidence',
                            'not_applicable', 'requires_investigator_judgment'
                        ))) AND
                    (medical_decision IS NULL OR
                        (criterion_kind = 'inclusion' AND medical_decision IN (
                            'met', 'not_met', 'insufficient_evidence',
                            'not_applicable', 'requires_investigator_judgment'
                        )) OR
                        (criterion_kind = 'exclusion' AND medical_decision IN (
                            'absent', 'present', 'insufficient_evidence',
                            'not_applicable', 'requires_investigator_judgment'
                        )))
                ),
                PRIMARY KEY (tenant_id, project_id, subject_id, criterion_uid),
                FOREIGN KEY (
                    tenant_id, project_id, rule_revision, criterion_uid
                ) REFERENCES eligibility_rule_revisions(
                    tenant_id, project_id, rule_revision, criterion_uid
                )
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_eligibility_review_state_subject
            ON eligibility_review_state(
                tenant_id, project_id, subject_id, criterion_kind, criterion_uid
            )
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_review_record_no_update
            BEFORE UPDATE ON eligibility_review_records
            BEGIN
                SELECT RAISE(ABORT, 'eligibility review records are immutable');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_review_record_no_delete
            BEFORE DELETE ON eligibility_review_records
            BEGIN
                SELECT RAISE(ABORT, 'eligibility review records are immutable');
            END
            """,
        )
        for statement in statements:
            connection.execute(statement)

    def _apply_v7(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS eligibility_evidence_jobs (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                job_kind TEXT NOT NULL CHECK (
                    job_kind IN (
                        'media_classification', 'pdf_text_extraction',
                        'pdf_page_render', 'ocr', 'vlm'
                    )
                ),
                source_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                subject_source_revision TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'queued', 'running', 'retry_wait', 'succeeded',
                        'failed', 'cancelled'
                    )
                ),
                priority INTEGER NOT NULL DEFAULT 0,
                attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
                max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
                lease_owner TEXT,
                lease_expires_at TEXT,
                next_run_at TEXT,
                progress_current INTEGER NOT NULL DEFAULT 0 CHECK (progress_current >= 0),
                progress_total INTEGER NOT NULL DEFAULT 0 CHECK (progress_total >= 0),
                error_code TEXT,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                request_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                PRIMARY KEY (tenant_id, project_id, job_id),
                UNIQUE (tenant_id, project_id, subject_id, idempotency_key),
                UNIQUE (tenant_id, project_id, subject_id, cache_key),
                FOREIGN KEY (
                    tenant_id, project_id, subject_id, source_id, source_revision
                ) REFERENCES eligibility_source_revisions(
                    tenant_id, project_id, subject_id, source_id, source_revision
                )
            );
            CREATE INDEX IF NOT EXISTS idx_eligibility_evidence_jobs_claim
            ON eligibility_evidence_jobs(
                tenant_id, status, next_run_at, priority DESC, created_at, job_id
            );
            CREATE INDEX IF NOT EXISTS idx_eligibility_evidence_jobs_subject
            ON eligibility_evidence_jobs(
                tenant_id, project_id, subject_id, updated_at, job_id
            );

            CREATE TABLE IF NOT EXISTS eligibility_evidence_job_attempts (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
                worker_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                outcome TEXT CHECK (
                    outcome IS NULL OR outcome IN (
                        'succeeded', 'retry_wait', 'failed', 'cancelled',
                        'lease_expired'
                    )
                ),
                error_code TEXT,
                PRIMARY KEY (
                    tenant_id, project_id, job_id, attempt_number
                ),
                FOREIGN KEY (tenant_id, project_id, job_id)
                REFERENCES eligibility_evidence_jobs(
                    tenant_id, project_id, job_id
                )
            );

            CREATE TABLE IF NOT EXISTS eligibility_evidence_artifacts (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                artifact_kind TEXT NOT NULL,
                storage_key TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                media_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                extraction_revision TEXT NOT NULL,
                locator_json TEXT NOT NULL,
                quality_state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, artifact_id),
                UNIQUE (tenant_id, project_id, job_id, storage_key),
                FOREIGN KEY (tenant_id, project_id, job_id)
                REFERENCES eligibility_evidence_jobs(
                    tenant_id, project_id, job_id
                )
            );
            CREATE INDEX IF NOT EXISTS idx_eligibility_evidence_artifacts_job
            ON eligibility_evidence_artifacts(
                tenant_id, project_id, job_id, created_at, artifact_id
            );

            CREATE TRIGGER IF NOT EXISTS trg_eligibility_evidence_artifact_no_update
            BEFORE UPDATE ON eligibility_evidence_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'eligibility evidence artifacts are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_evidence_artifact_no_delete
            BEFORE DELETE ON eligibility_evidence_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'eligibility evidence artifacts are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_evidence_attempt_no_update
            BEFORE UPDATE ON eligibility_evidence_job_attempts
            WHEN OLD.finished_at IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'completed eligibility evidence attempts are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_evidence_span_no_update
            BEFORE UPDATE ON eligibility_evidence_spans
            BEGIN
                SELECT RAISE(ABORT, 'eligibility evidence spans are immutable');
            END;
            """
        )

    def _apply_v8(self, connection: sqlite3.Connection) -> None:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(eligibility_evidence_jobs)"
            ).fetchall()
        }
        if "profile_version" not in columns:
            connection.execute(
                """
                ALTER TABLE eligibility_evidence_jobs
                ADD COLUMN profile_version TEXT NOT NULL
                DEFAULT 'legacy_profile_unknown'
                """
            )

    def _apply_v9(self, connection: sqlite3.Connection) -> None:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(eligibility_evidence_jobs)"
            ).fetchall()
        }
        additions = {
            "parent_job_id": "TEXT",
            "input_artifact_id": "TEXT",
            "page_index": "INTEGER CHECK (page_index IS NULL OR page_index >= 1)",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE eligibility_evidence_jobs ADD COLUMN {name} {definition}"
                )
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_eligibility_evidence_jobs_parent
            ON eligibility_evidence_jobs(
                tenant_id, project_id, parent_job_id, page_index, profile_version
            );
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_evidence_job_parent_immutable
            BEFORE UPDATE OF parent_job_id, input_artifact_id, page_index
            ON eligibility_evidence_jobs
            WHEN OLD.parent_job_id IS NOT NEW.parent_job_id
              OR OLD.input_artifact_id IS NOT NEW.input_artifact_id
              OR OLD.page_index IS NOT NEW.page_index
            BEGIN
                SELECT RAISE(ABORT, 'eligibility evidence job parent relation is immutable');
            END;
            """
        )

    def _apply_v10(self, connection: sqlite3.Connection) -> None:
        from .ocr_gateway import ocr_profile_digest

        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(eligibility_evidence_jobs)"
            ).fetchall()
        }
        if "profile_digest" not in columns:
            connection.execute(
                "ALTER TABLE eligibility_evidence_jobs ADD COLUMN profile_digest TEXT"
            )
        for profile_version in ("ocr-glm-v1", "ocr-paddle-v1"):
            connection.execute(
                """
                UPDATE eligibility_evidence_jobs
                SET profile_digest = ?
                WHERE job_kind = 'ocr' AND profile_version = ?
                  AND profile_digest IS NULL
                """,
                (ocr_profile_digest(profile_version), profile_version),
            )
        connection.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_evidence_job_profile_digest_immutable
            BEFORE UPDATE OF profile_digest ON eligibility_evidence_jobs
            WHEN OLD.profile_digest IS NOT NEW.profile_digest
            BEGIN
                SELECT RAISE(ABORT, 'eligibility evidence job profile digest is immutable');
            END;
            """
        )

    def _apply_v11(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_eligibility_evidence_span_extraction_identity
            ON eligibility_evidence_spans(
                tenant_id, project_id, subject_id, evidence_id,
                source_revision, extraction_revision
            );

            CREATE TABLE IF NOT EXISTS eligibility_evidence_visual_qc_records (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                extraction_revision TEXT NOT NULL,
                qc_record_id TEXT NOT NULL,
                previous_qc_revision INTEGER NOT NULL CHECK (previous_qc_revision >= 0),
                new_qc_revision INTEGER NOT NULL CHECK (
                    new_qc_revision = previous_qc_revision + 1
                ),
                result TEXT NOT NULL CHECK (
                    result IN ('sampled_pass', 'sampled_fail', 'manual_review_required')
                ),
                reason_code TEXT NOT NULL,
                user_reason TEXT NOT NULL,
                sample_plan_id TEXT,
                sample_unit_json TEXT,
                policy_version TEXT NOT NULL,
                actor TEXT NOT NULL,
                identity_assurance TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                request_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, qc_record_id),
                UNIQUE (
                    tenant_id, project_id, subject_id, evidence_id,
                    source_revision, extraction_revision, new_qc_revision
                ),
                UNIQUE (
                    tenant_id, project_id, subject_id, evidence_id,
                    source_revision, extraction_revision, idempotency_key
                ),
                UNIQUE (
                    tenant_id, project_id, subject_id, evidence_id,
                    source_revision, extraction_revision, qc_record_id
                ),
                FOREIGN KEY (
                    tenant_id, project_id, subject_id, evidence_id,
                    source_revision, extraction_revision
                ) REFERENCES eligibility_evidence_spans(
                    tenant_id, project_id, subject_id, evidence_id,
                    source_revision, extraction_revision
                )
            );

            CREATE TABLE IF NOT EXISTS eligibility_evidence_visual_qc_state (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                extraction_revision TEXT NOT NULL,
                qc_revision INTEGER NOT NULL CHECK (qc_revision >= 1),
                effective_result TEXT NOT NULL CHECK (
                    effective_result IN (
                        'sampled_pass', 'sampled_fail', 'manual_review_required'
                    )
                ),
                latest_qc_record_id TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                user_reason TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (
                    tenant_id, project_id, subject_id, evidence_id,
                    source_revision, extraction_revision
                ),
                FOREIGN KEY (
                    tenant_id, project_id, subject_id, evidence_id,
                    source_revision, extraction_revision, latest_qc_record_id
                )
                REFERENCES eligibility_evidence_visual_qc_records(
                    tenant_id, project_id, subject_id, evidence_id,
                    source_revision, extraction_revision, qc_record_id
                )
            );

            CREATE INDEX IF NOT EXISTS idx_eligibility_visual_qc_subject
            ON eligibility_evidence_visual_qc_state(
                tenant_id, project_id, subject_id, evidence_id,
                source_revision, extraction_revision
            );

            CREATE TRIGGER IF NOT EXISTS trg_eligibility_evidence_span_no_delete
            BEFORE DELETE ON eligibility_evidence_spans
            BEGIN
                SELECT RAISE(ABORT, 'eligibility evidence spans are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_eligibility_visual_qc_record_no_update
            BEFORE UPDATE ON eligibility_evidence_visual_qc_records
            BEGIN
                SELECT RAISE(ABORT, 'eligibility visual QC records are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_eligibility_visual_qc_record_no_delete
            BEFORE DELETE ON eligibility_evidence_visual_qc_records
            BEGIN
                SELECT RAISE(ABORT, 'eligibility visual QC records are immutable');
            END;
            """
        )

    def _apply_v12(self, connection: sqlite3.Connection) -> None:
        job_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(eligibility_evidence_jobs)"
            ).fetchall()
        }
        if "lease_token" not in job_columns:
            connection.execute(
                "ALTER TABLE eligibility_evidence_jobs ADD COLUMN lease_token TEXT"
            )
        attempt_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(eligibility_evidence_job_attempts)"
            ).fetchall()
        }
        if "lease_token" not in attempt_columns:
            connection.execute(
                "ALTER TABLE eligibility_evidence_job_attempts ADD COLUMN lease_token TEXT"
            )
        _execute_sql_script_in_transaction(
            connection,
            """
            CREATE TABLE IF NOT EXISTS eligibility_vlm_profile_revisions (
                tenant_id TEXT NOT NULL,
                profile_version TEXT NOT NULL,
                profile_digest TEXT NOT NULL CHECK (
                    length(profile_digest) = 64
                    AND profile_digest NOT GLOB '*[^0-9a-f]*'
                ),
                profile_payload_hash TEXT NOT NULL CHECK (length(profile_payload_hash) = 64),
                max_attempts_limit INTEGER NOT NULL CHECK (
                    max_attempts_limit >= 1 AND max_attempts_limit <= 10
                ),
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, profile_version, profile_digest)
            );

            CREATE TABLE IF NOT EXISTS eligibility_vlm_profile_state (
                tenant_id TEXT NOT NULL,
                profile_version TEXT NOT NULL,
                profile_digest TEXT NOT NULL,
                state_revision INTEGER NOT NULL CHECK (state_revision >= 1),
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, profile_version),
                FOREIGN KEY (tenant_id, profile_version, profile_digest)
                REFERENCES eligibility_vlm_profile_revisions(
                    tenant_id, profile_version, profile_digest
                )
            );

            CREATE TABLE IF NOT EXISTS eligibility_controlled_artifact_records (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                artifact_revision_token TEXT NOT NULL,
                governance_revision INTEGER NOT NULL CHECK (governance_revision >= 1),
                data_class TEXT NOT NULL CHECK (
                    data_class IN ('synthetic_fixture', 'clinical_restricted')
                ),
                authorization_state TEXT NOT NULL CHECK (
                    authorization_state IN ('authorized', 'denied')
                ),
                authorization_ref TEXT NOT NULL,
                retention_policy_id TEXT NOT NULL,
                legal_hold INTEGER NOT NULL DEFAULT 0 CHECK (legal_hold IN (0, 1)),
                source_revision TEXT NOT NULL,
                extraction_revision TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (
                    tenant_id, project_id, artifact_id, governance_revision
                ),
                UNIQUE (
                    tenant_id, project_id, artifact_id,
                    artifact_revision_token, governance_revision
                ),
                FOREIGN KEY (tenant_id, project_id, artifact_id)
                REFERENCES eligibility_evidence_artifacts(
                    tenant_id, project_id, artifact_id
                )
            );

            CREATE TABLE IF NOT EXISTS eligibility_controlled_artifact_state (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                artifact_revision_token TEXT NOT NULL,
                governance_revision INTEGER NOT NULL CHECK (governance_revision >= 1),
                data_class TEXT NOT NULL,
                authorization_state TEXT NOT NULL,
                authorization_ref TEXT NOT NULL,
                retention_policy_id TEXT NOT NULL,
                legal_hold INTEGER NOT NULL CHECK (legal_hold IN (0, 1)),
                source_revision TEXT NOT NULL,
                extraction_revision TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, artifact_id),
                FOREIGN KEY (
                    tenant_id, project_id, artifact_id,
                    artifact_revision_token, governance_revision
                ) REFERENCES eligibility_controlled_artifact_records(
                    tenant_id, project_id, artifact_id,
                    artifact_revision_token, governance_revision
                )
            );

            CREATE TABLE IF NOT EXISTS eligibility_vlm_job_bindings (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                artifact_revision_token TEXT NOT NULL,
                governance_revision INTEGER NOT NULL CHECK (governance_revision >= 1),
                profile_version TEXT NOT NULL,
                profile_digest TEXT NOT NULL CHECK (
                    length(profile_digest) = 64
                    AND profile_digest NOT GLOB '*[^0-9a-f]*'
                ),
                source_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                extraction_revision TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, job_id),
                FOREIGN KEY (tenant_id, project_id, job_id)
                REFERENCES eligibility_evidence_jobs(tenant_id, project_id, job_id),
                FOREIGN KEY (
                    tenant_id, project_id, artifact_id,
                    artifact_revision_token, governance_revision
                ) REFERENCES eligibility_controlled_artifact_records(
                    tenant_id, project_id, artifact_id,
                    artifact_revision_token, governance_revision
                ),
                FOREIGN KEY (tenant_id, profile_version, profile_digest)
                REFERENCES eligibility_vlm_profile_revisions(
                    tenant_id, profile_version, profile_digest
                )
            );

            CREATE TABLE IF NOT EXISTS eligibility_vlm_descriptor_records (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                descriptor_record_id TEXT NOT NULL,
                attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
                schema_version TEXT NOT NULL CHECK (
                    schema_version = 'eligibility_visual_descriptor_v1'
                ),
                media_class TEXT NOT NULL,
                primary_document_type TEXT NOT NULL,
                capture_quality_overall TEXT NOT NULL,
                capture_quality_flags_json TEXT NOT NULL,
                orientation TEXT NOT NULL,
                human_attention_json TEXT NOT NULL,
                gateway_outcome TEXT NOT NULL CHECK (
                    gateway_outcome IN ('descriptor_valid', 'manual_review_required')
                ),
                profile_version TEXT NOT NULL,
                profile_digest TEXT NOT NULL CHECK (length(profile_digest) = 64),
                artifact_id TEXT NOT NULL,
                artifact_revision_token TEXT NOT NULL,
                governance_revision INTEGER NOT NULL,
                normalized_width INTEGER NOT NULL CHECK (normalized_width >= 1),
                normalized_height INTEGER NOT NULL CHECK (normalized_height >= 1),
                duration_ms REAL NOT NULL CHECK (duration_ms >= 0),
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, descriptor_record_id),
                UNIQUE (tenant_id, project_id, job_id),
                FOREIGN KEY (tenant_id, project_id, job_id)
                REFERENCES eligibility_vlm_job_bindings(tenant_id, project_id, job_id)
            );

            CREATE TABLE IF NOT EXISTS eligibility_vlm_current_state (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                state_revision INTEGER NOT NULL CHECK (state_revision = 1),
                descriptor_record_id TEXT NOT NULL,
                effective_outcome TEXT NOT NULL CHECK (
                    effective_outcome IN ('descriptor_valid', 'manual_review_required')
                ),
                visual_qc_status TEXT NOT NULL CHECK (visual_qc_status = 'not_reviewed'),
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, job_id),
                FOREIGN KEY (tenant_id, project_id, descriptor_record_id)
                REFERENCES eligibility_vlm_descriptor_records(
                    tenant_id, project_id, descriptor_record_id
                )
            );

            CREATE TABLE IF NOT EXISTS eligibility_vlm_audit_events (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                audit_event_id TEXT NOT NULL,
                attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
                event_type TEXT NOT NULL CHECK (
                    event_type IN ('vlm_descriptor_committed', 'vlm_attempt_failed')
                ),
                gateway_outcome TEXT NOT NULL CHECK (
                    gateway_outcome IN (
                        'rejected', 'descriptor_valid',
                        'manual_review_required', 'runtime_failed'
                    )
                ),
                error_code TEXT,
                data_class TEXT NOT NULL,
                profile_version TEXT NOT NULL,
                profile_digest TEXT NOT NULL CHECK (length(profile_digest) = 64),
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, audit_event_id),
                UNIQUE (tenant_id, project_id, job_id, attempt_number, event_type)
            );

            CREATE TRIGGER IF NOT EXISTS trg_eligibility_vlm_profile_revision_no_update
            BEFORE UPDATE ON eligibility_vlm_profile_revisions BEGIN
                SELECT RAISE(ABORT, 'VLM profile revisions are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_vlm_profile_revision_no_delete
            BEFORE DELETE ON eligibility_vlm_profile_revisions BEGIN
                SELECT RAISE(ABORT, 'VLM profile revisions are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_controlled_artifact_record_no_update
            BEFORE UPDATE ON eligibility_controlled_artifact_records BEGIN
                SELECT RAISE(ABORT, 'controlled artifact records are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_controlled_artifact_record_no_delete
            BEFORE DELETE ON eligibility_controlled_artifact_records BEGIN
                SELECT RAISE(ABORT, 'controlled artifact records are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_vlm_job_binding_no_update
            BEFORE UPDATE ON eligibility_vlm_job_bindings BEGIN
                SELECT RAISE(ABORT, 'VLM job bindings are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_vlm_job_binding_no_delete
            BEFORE DELETE ON eligibility_vlm_job_bindings BEGIN
                SELECT RAISE(ABORT, 'VLM job bindings are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_vlm_descriptor_no_update
            BEFORE UPDATE ON eligibility_vlm_descriptor_records BEGIN
                SELECT RAISE(ABORT, 'VLM descriptor records are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_vlm_descriptor_no_delete
            BEFORE DELETE ON eligibility_vlm_descriptor_records BEGIN
                SELECT RAISE(ABORT, 'VLM descriptor records are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_vlm_audit_no_update
            BEFORE UPDATE ON eligibility_vlm_audit_events BEGIN
                SELECT RAISE(ABORT, 'VLM audit events are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_vlm_audit_no_delete
            BEFORE DELETE ON eligibility_vlm_audit_events BEGIN
                SELECT RAISE(ABORT, 'VLM audit events are immutable');
            END;
            """,
        )

    def _apply_v13(self, connection: sqlite3.Connection) -> None:
        job_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(eligibility_evidence_jobs)"
            ).fetchall()
        }
        if "provider_attempt_count" not in job_columns:
            connection.execute(
                """
                ALTER TABLE eligibility_evidence_jobs
                ADD COLUMN provider_attempt_count INTEGER NOT NULL DEFAULT 0
                CHECK (provider_attempt_count >= 0)
                """
            )
        _execute_sql_script_in_transaction(
            connection,
            """
            CREATE TABLE IF NOT EXISTS eligibility_vlm_circuit_state (
                tenant_id TEXT NOT NULL,
                profile_digest TEXT NOT NULL CHECK (length(profile_digest) = 64),
                state TEXT NOT NULL CHECK (state IN ('closed', 'open', 'half_open')),
                generation INTEGER NOT NULL CHECK (generation >= 0),
                opened_at TEXT,
                half_open_permit_token TEXT,
                half_open_expires_at TEXT,
                next_sample_sequence INTEGER NOT NULL CHECK (next_sample_sequence >= 1),
                minimum_sample_size INTEGER NOT NULL CHECK (minimum_sample_size >= 1),
                rolling_window_size INTEGER NOT NULL CHECK (
                    rolling_window_size >= minimum_sample_size
                ),
                failure_threshold_numerator INTEGER NOT NULL CHECK (
                    failure_threshold_numerator >= 1
                ),
                failure_threshold_denominator INTEGER NOT NULL CHECK (
                    failure_threshold_denominator >= failure_threshold_numerator
                ),
                cooldown_seconds INTEGER NOT NULL CHECK (cooldown_seconds >= 1),
                closed_permit_lease_seconds INTEGER NOT NULL CHECK (
                    closed_permit_lease_seconds >= 1
                ),
                probe_lease_seconds INTEGER NOT NULL CHECK (probe_lease_seconds >= 1),
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, profile_digest),
                CHECK (
                    (state = 'closed' AND opened_at IS NULL AND half_open_permit_token IS NULL AND half_open_expires_at IS NULL)
                    OR (state = 'open' AND opened_at IS NOT NULL AND half_open_permit_token IS NULL AND half_open_expires_at IS NULL)
                    OR (state = 'half_open' AND opened_at IS NOT NULL AND half_open_permit_token IS NOT NULL AND half_open_expires_at IS NOT NULL)
                )
            );

            CREATE TABLE IF NOT EXISTS eligibility_vlm_circuit_samples (
                tenant_id TEXT NOT NULL,
                profile_digest TEXT NOT NULL,
                sample_sequence INTEGER NOT NULL CHECK (sample_sequence >= 1),
                generation INTEGER NOT NULL CHECK (generation >= 0),
                permit_token TEXT NOT NULL,
                half_open_probe INTEGER NOT NULL CHECK (half_open_probe IN (0, 1)),
                failed INTEGER NOT NULL CHECK (failed IN (0, 1)),
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, profile_digest, sample_sequence),
                UNIQUE (tenant_id, profile_digest, permit_token),
                FOREIGN KEY (tenant_id, profile_digest)
                REFERENCES eligibility_vlm_circuit_state(tenant_id, profile_digest)
                ON DELETE CASCADE,
                FOREIGN KEY (tenant_id, profile_digest, permit_token)
                REFERENCES eligibility_vlm_circuit_permits(
                    tenant_id, profile_digest, permit_token
                )
            );

            CREATE TABLE IF NOT EXISTS eligibility_vlm_circuit_permits (
                tenant_id TEXT NOT NULL,
                profile_digest TEXT NOT NULL,
                permit_token TEXT NOT NULL,
                generation INTEGER NOT NULL CHECK (generation >= 0),
                half_open_probe INTEGER NOT NULL CHECK (half_open_probe IN (0, 1)),
                issued_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, profile_digest, permit_token),
                FOREIGN KEY (tenant_id, profile_digest)
                REFERENCES eligibility_vlm_circuit_state(tenant_id, profile_digest)
                ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_eligibility_vlm_circuit_samples_window
            ON eligibility_vlm_circuit_samples(
                tenant_id, profile_digest, sample_sequence DESC
            );

            CREATE TRIGGER IF NOT EXISTS trg_eligibility_vlm_circuit_sample_no_update
            BEFORE UPDATE ON eligibility_vlm_circuit_samples BEGIN
                SELECT RAISE(ABORT, 'VLM circuit samples are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_vlm_circuit_sample_no_delete
            BEFORE DELETE ON eligibility_vlm_circuit_samples BEGIN
                SELECT RAISE(ABORT, 'VLM circuit samples are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_vlm_circuit_permit_no_update
            BEFORE UPDATE ON eligibility_vlm_circuit_permits BEGIN
                SELECT RAISE(ABORT, 'VLM circuit permits are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_vlm_circuit_permit_no_delete
            BEFORE DELETE ON eligibility_vlm_circuit_permits BEGIN
                SELECT RAISE(ABORT, 'VLM circuit permits are immutable');
            END;
            """,
        )
        expected_columns = {
            "eligibility_vlm_circuit_state": {
                "tenant_id", "profile_digest", "state", "generation",
                "opened_at", "half_open_permit_token", "half_open_expires_at",
                "next_sample_sequence", "minimum_sample_size",
                "rolling_window_size", "failure_threshold_numerator",
                "failure_threshold_denominator", "cooldown_seconds",
                "closed_permit_lease_seconds",
                "probe_lease_seconds", "updated_at",
            },
            "eligibility_vlm_circuit_permits": {
                "tenant_id", "profile_digest", "permit_token", "generation",
                "half_open_probe", "issued_at", "expires_at",
            },
            "eligibility_vlm_circuit_samples": {
                "tenant_id", "profile_digest", "sample_sequence", "generation",
                "permit_token", "half_open_probe", "failed", "recorded_at",
            },
        }
        for table_name, expected in expected_columns.items():
            actual = {
                str(row[1])
                for row in connection.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
            }
            if actual != expected:
                raise RuntimeStoreIntegrityError(
                    f"unexpected v13 circuit schema for {table_name}"
                )

    def _apply_v14(self, connection: sqlite3.Connection) -> None:
        source_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(eligibility_source_revisions)"
            ).fetchall()
        }
        if "processing_unit_kind" not in source_columns:
            connection.execute(
                """
                ALTER TABLE eligibility_source_revisions
                ADD COLUMN processing_unit_kind TEXT NOT NULL
                DEFAULT 'legacy_unknown'
                """
            )
        if "expected_unit_count" not in source_columns:
            connection.execute(
                """
                ALTER TABLE eligibility_source_revisions
                ADD COLUMN expected_unit_count INTEGER NOT NULL DEFAULT 0
                CHECK (expected_unit_count >= 0)
                """
            )
        _execute_sql_script_in_transaction(
            connection,
            """
            CREATE TABLE IF NOT EXISTS eligibility_source_processing_unit_records (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                subject_source_revision TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                unit_index INTEGER NOT NULL CHECK (unit_index >= 1),
                record_id TEXT NOT NULL,
                previous_state_revision INTEGER NOT NULL CHECK (
                    previous_state_revision >= 0
                ),
                new_state_revision INTEGER NOT NULL CHECK (
                    new_state_revision = previous_state_revision + 1
                ),
                processing_status TEXT NOT NULL CHECK (
                    processing_status IN (
                        'evidence_extracted',
                        'processed_no_relevant_evidence',
                        'manual_review_required',
                        'failed'
                    )
                ),
                artifact_id TEXT,
                extraction_revision TEXT,
                evidence_ids_json TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                actor TEXT NOT NULL,
                identity_assurance TEXT NOT NULL,
                request_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, record_id),
                UNIQUE (
                    tenant_id, project_id, subject_id, subject_source_revision,
                    source_id, source_revision, unit_index, new_state_revision
                ),
                FOREIGN KEY (
                    tenant_id, project_id, subject_id, source_id, source_revision
                ) REFERENCES eligibility_source_revisions(
                    tenant_id, project_id, subject_id, source_id, source_revision
                )
            );

            CREATE TABLE IF NOT EXISTS eligibility_source_processing_unit_state (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                subject_source_revision TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                unit_index INTEGER NOT NULL CHECK (unit_index >= 1),
                state_revision INTEGER NOT NULL CHECK (state_revision >= 1),
                processing_status TEXT NOT NULL,
                artifact_id TEXT,
                extraction_revision TEXT,
                evidence_ids_json TEXT NOT NULL,
                latest_record_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (
                    tenant_id, project_id, subject_id, subject_source_revision,
                    source_id, source_revision, unit_index
                ),
                FOREIGN KEY (tenant_id, project_id, latest_record_id)
                REFERENCES eligibility_source_processing_unit_records(
                    tenant_id, project_id, record_id
                )
            );

            CREATE INDEX IF NOT EXISTS idx_eligibility_source_unit_state_subject
            ON eligibility_source_processing_unit_state(
                tenant_id, project_id, subject_id, source_id, source_revision,
                processing_status, unit_index
            );

            CREATE TRIGGER IF NOT EXISTS trg_eligibility_source_unit_record_no_update
            BEFORE UPDATE ON eligibility_source_processing_unit_records BEGIN
                SELECT RAISE(ABORT, 'eligibility source unit records are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_eligibility_source_unit_record_no_delete
            BEFORE DELETE ON eligibility_source_processing_unit_records BEGIN
                SELECT RAISE(ABORT, 'eligibility source unit records are immutable');
            END;
            """,
        )
        expected_columns = {
            "eligibility_source_processing_unit_records": {
                "tenant_id", "project_id", "subject_id",
                "subject_source_revision", "source_id", "source_revision",
                "unit_index", "record_id", "previous_state_revision",
                "new_state_revision", "processing_status", "artifact_id",
                "extraction_revision", "evidence_ids_json", "reason_code",
                "actor", "identity_assurance", "request_id", "created_at",
            },
            "eligibility_source_processing_unit_state": {
                "tenant_id", "project_id", "subject_id",
                "subject_source_revision", "source_id", "source_revision",
                "unit_index", "state_revision", "processing_status",
                "artifact_id", "extraction_revision", "evidence_ids_json",
                "latest_record_id", "updated_at",
            },
        }
        for table_name, expected in expected_columns.items():
            actual = {
                str(row[1])
                for row in connection.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
            }
            if actual != expected:
                raise RuntimeStoreIntegrityError(
                    f"unexpected v14 source processing-unit schema for {table_name}"
                )

    def _apply_v15(self, connection: sqlite3.Connection) -> None:
        _execute_sql_script_in_transaction(
            connection,
            """
            CREATE TABLE IF NOT EXISTS medical_writing_content_disposition_records (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                finding_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                section_id TEXT NOT NULL,
                detector_version TEXT NOT NULL,
                content_fingerprint TEXT NOT NULL,
                content_revision INTEGER NOT NULL CHECK (content_revision >= 0),
                revision INTEGER NOT NULL CHECK (revision >= 1),
                status TEXT NOT NULL CHECK (
                    status IN ('open', 'confirmed_source_text', 'correction_required')
                ),
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, record_id),
                UNIQUE (tenant_id, project_id, finding_id, revision)
            );

            CREATE TABLE IF NOT EXISTS medical_writing_content_disposition_state (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                finding_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                section_id TEXT NOT NULL,
                detector_version TEXT NOT NULL,
                content_fingerprint TEXT NOT NULL,
                content_revision INTEGER NOT NULL CHECK (content_revision >= 0),
                revision INTEGER NOT NULL CHECK (revision >= 1),
                status TEXT NOT NULL,
                latest_record_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, finding_id),
                FOREIGN KEY (tenant_id, project_id, latest_record_id)
                REFERENCES medical_writing_content_disposition_records(
                    tenant_id, project_id, record_id
                )
            );

            CREATE INDEX IF NOT EXISTS idx_medical_writing_content_state_section
            ON medical_writing_content_disposition_state(
                tenant_id, project_id, document_id, section_id, status
            );

            CREATE TRIGGER IF NOT EXISTS trg_medical_writing_content_record_no_update
            BEFORE UPDATE ON medical_writing_content_disposition_records BEGIN
                SELECT RAISE(ABORT, 'medical writing content disposition records are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_medical_writing_content_record_no_delete
            BEFORE DELETE ON medical_writing_content_disposition_records BEGIN
                SELECT RAISE(ABORT, 'medical writing content disposition records are immutable');
            END;
            """,
        )
        expected_columns = {
            "medical_writing_content_disposition_records": {
                "tenant_id", "project_id", "record_id", "finding_id",
                "document_id", "section_id", "detector_version",
                "content_fingerprint", "content_revision", "revision",
                "status", "created_at", "payload_json",
            },
            "medical_writing_content_disposition_state": {
                "tenant_id", "project_id", "finding_id", "document_id",
                "section_id", "detector_version", "content_fingerprint",
                "content_revision", "revision", "status",
                "latest_record_id", "updated_at",
            },
        }
        for table_name, expected in expected_columns.items():
            actual = {
                str(row[1])
                for row in connection.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
            }
            if actual != expected:
                raise RuntimeStoreIntegrityError(
                    f"unexpected v15 medical writing content schema for {table_name}"
                )

    def _apply_v16(self, connection: sqlite3.Connection) -> None:
        _execute_sql_script_in_transaction(
            connection,
            """
            CREATE TABLE IF NOT EXISTS safety_pv_review_records (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                package_id TEXT NOT NULL,
                signal_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                action TEXT NOT NULL,
                previous_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, record_id),
                UNIQUE (tenant_id, project_id, package_id, signal_id, revision)
            );

            CREATE TABLE IF NOT EXISTS safety_pv_review_state (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                package_id TEXT NOT NULL,
                signal_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                status TEXT NOT NULL,
                latest_record_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, package_id, signal_id),
                FOREIGN KEY (tenant_id, project_id, latest_record_id)
                REFERENCES safety_pv_review_records(
                    tenant_id, project_id, record_id
                )
            );

            CREATE INDEX IF NOT EXISTS idx_safety_pv_review_records_signal
            ON safety_pv_review_records(
                tenant_id, project_id, package_id, signal_id, revision
            );

            CREATE TRIGGER IF NOT EXISTS trg_safety_pv_review_record_no_update
            BEFORE UPDATE ON safety_pv_review_records BEGIN
                SELECT RAISE(ABORT, 'safety PV review records are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_safety_pv_review_record_no_delete
            BEFORE DELETE ON safety_pv_review_records BEGIN
                SELECT RAISE(ABORT, 'safety PV review records are immutable');
            END;
            """,
        )
        expected_columns = {
            "safety_pv_review_records": {
                "tenant_id", "project_id", "record_id", "package_id",
                "signal_id", "revision", "action", "previous_status",
                "new_status", "created_at", "payload_json",
            },
            "safety_pv_review_state": {
                "tenant_id", "project_id", "package_id", "signal_id",
                "revision", "status", "latest_record_id", "updated_at",
            },
        }
        for table_name, expected in expected_columns.items():
            actual = {
                str(row[1])
                for row in connection.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
            }
            if actual != expected:
                raise RuntimeStoreIntegrityError(
                    f"unexpected v16 Safety/PV review schema for {table_name}"
                )

    @staticmethod
    def _issue_vlm_circuit_permit(
        connection: sqlite3.Connection,
        *,
        profile_digest: str,
        generation: int,
        half_open_probe: bool,
        current: datetime,
        lease_seconds: int,
    ) -> str:
        permit_token = uuid4().hex
        connection.execute(
            """
            INSERT INTO eligibility_vlm_circuit_permits(
                tenant_id, profile_digest, permit_token, generation,
                half_open_probe, issued_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_PLACEHOLDER,
                profile_digest,
                permit_token,
                generation,
                int(half_open_probe),
                current.isoformat(),
                (current + timedelta(seconds=lease_seconds)).isoformat(),
            ),
        )
        return permit_token

    @staticmethod
    def _vlm_circuit_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("VLM circuit time must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _validate_vlm_circuit_policy(
        *,
        minimum_sample_size: int,
        rolling_window_size: int,
        failure_threshold: float,
        cooldown_seconds: int,
        closed_permit_lease_seconds: int,
        probe_lease_seconds: int,
    ) -> None:
        if minimum_sample_size < 1:
            raise ValueError("VLM circuit minimum sample must be positive")
        if rolling_window_size < minimum_sample_size:
            raise ValueError("VLM circuit rolling window is invalid")
        if not 0 < failure_threshold <= 1:
            raise ValueError("VLM circuit failure threshold is invalid")
        if cooldown_seconds < 1:
            raise ValueError("VLM circuit cooldown must be positive")
        if closed_permit_lease_seconds < 1:
            raise ValueError("VLM circuit closed permit lease must be positive")
        if probe_lease_seconds < 1:
            raise ValueError("VLM circuit probe lease must be positive")

    @staticmethod
    def _vlm_circuit_policy_matches(
        row: sqlite3.Row,
        *,
        minimum_sample_size: int,
        rolling_window_size: int,
        failure_threshold: float,
        cooldown_seconds: int,
        closed_permit_lease_seconds: int,
        probe_lease_seconds: int,
    ) -> bool:
        return (
            int(row["minimum_sample_size"]) == minimum_sample_size
            and int(row["rolling_window_size"]) == rolling_window_size
            and (
                int(row["failure_threshold_numerator"]),
                int(row["failure_threshold_denominator"]),
            )
            == failure_threshold.as_integer_ratio()
            and int(row["cooldown_seconds"]) == cooldown_seconds
            and int(row["closed_permit_lease_seconds"])
            == closed_permit_lease_seconds
            and int(row["probe_lease_seconds"]) == probe_lease_seconds
        )

    def acquire_eligibility_vlm_circuit_permit(
        self,
        profile_digest: str,
        *,
        minimum_sample_size: int,
        rolling_window_size: int,
        failure_threshold: float,
        cooldown_seconds: int,
        closed_permit_lease_seconds: int,
        probe_lease_seconds: int,
        now: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        if len(profile_digest) != 64:
            raise ValueError("VLM circuit profile digest is invalid")
        self._validate_vlm_circuit_policy(
            minimum_sample_size=minimum_sample_size,
            rolling_window_size=rolling_window_size,
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
            closed_permit_lease_seconds=closed_permit_lease_seconds,
            probe_lease_seconds=probe_lease_seconds,
        )
        current = self._vlm_circuit_utc(now or _utc_now())
        current_iso = current.isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM eligibility_vlm_circuit_state
                WHERE tenant_id = ? AND profile_digest = ?
                """,
                (TENANT_PLACEHOLDER, profile_digest),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO eligibility_vlm_circuit_state(
                        tenant_id, profile_digest, state, generation, opened_at,
                        half_open_permit_token, half_open_expires_at,
                        next_sample_sequence,
                        minimum_sample_size, rolling_window_size,
                        failure_threshold_numerator,
                        failure_threshold_denominator, cooldown_seconds,
                        closed_permit_lease_seconds, probe_lease_seconds,
                        updated_at
                    ) VALUES (?, ?, 'closed', 0, NULL, NULL, NULL, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        profile_digest,
                        minimum_sample_size,
                        rolling_window_size,
                        *failure_threshold.as_integer_ratio(),
                        cooldown_seconds,
                        closed_permit_lease_seconds,
                        probe_lease_seconds,
                        current_iso,
                    ),
                )
                permit_token = self._issue_vlm_circuit_permit(
                    connection,
                    profile_digest=profile_digest,
                    generation=0,
                    half_open_probe=False,
                    current=current,
                    lease_seconds=closed_permit_lease_seconds,
                )
                connection.commit()
                return {
                    "generation": 0,
                    "half_open_probe": False,
                    "permit_token": permit_token,
                }
            if not self._vlm_circuit_policy_matches(
                row,
                minimum_sample_size=minimum_sample_size,
                rolling_window_size=rolling_window_size,
                failure_threshold=failure_threshold,
                cooldown_seconds=cooldown_seconds,
                closed_permit_lease_seconds=closed_permit_lease_seconds,
                probe_lease_seconds=probe_lease_seconds,
            ):
                raise RuntimeStoreIntegrityError(
                    "VLM circuit policy does not match persisted profile state"
                )
            updated_at = datetime.fromisoformat(str(row["updated_at"]))
            if current < updated_at:
                raise RuntimeStoreIntegrityError(
                    "VLM circuit clock moved backwards"
                )
            if row["state"] == "closed":
                permit_token = self._issue_vlm_circuit_permit(
                    connection,
                    profile_digest=profile_digest,
                    generation=int(row["generation"]),
                    half_open_probe=False,
                    current=current,
                    lease_seconds=closed_permit_lease_seconds,
                )
                connection.commit()
                return {
                    "generation": int(row["generation"]),
                    "half_open_probe": False,
                    "permit_token": permit_token,
                }
            if row["state"] == "half_open":
                expires_at = datetime.fromisoformat(str(row["half_open_expires_at"]))
                if current < expires_at:
                    connection.commit()
                    return None
                connection.execute(
                    """
                    UPDATE eligibility_vlm_circuit_state
                    SET state = 'open', generation = generation + 1,
                        opened_at = ?, half_open_permit_token = NULL,
                        half_open_expires_at = NULL, updated_at = ?
                    WHERE tenant_id = ? AND profile_digest = ?
                      AND state = 'half_open' AND generation = ?
                    """,
                    (
                        current_iso,
                        current_iso,
                        TENANT_PLACEHOLDER,
                        profile_digest,
                        int(row["generation"]),
                    ),
                )
                connection.commit()
                return None
            opened_at = datetime.fromisoformat(str(row["opened_at"]))
            if current < opened_at + timedelta(seconds=cooldown_seconds):
                connection.commit()
                return None
            permit_token = self._issue_vlm_circuit_permit(
                connection,
                profile_digest=profile_digest,
                generation=int(row["generation"]),
                half_open_probe=True,
                current=current,
                lease_seconds=probe_lease_seconds,
            )
            permit_expires_at = (
                current + timedelta(seconds=probe_lease_seconds)
            ).isoformat()
            cursor = connection.execute(
                """
                UPDATE eligibility_vlm_circuit_state
                SET state = 'half_open', half_open_permit_token = ?,
                    half_open_expires_at = ?, updated_at = ?
                WHERE tenant_id = ? AND profile_digest = ?
                  AND state = 'open' AND generation = ?
                """,
                (
                    permit_token,
                    permit_expires_at,
                    current_iso,
                    TENANT_PLACEHOLDER,
                    profile_digest,
                    int(row["generation"]),
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
            return {
                "generation": int(row["generation"]),
                "half_open_probe": True,
                "permit_token": permit_token,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record_eligibility_vlm_circuit_outcome(
        self,
        profile_digest: str,
        *,
        generation: int,
        half_open_probe: bool,
        permit_token: Optional[str],
        failed: bool,
        now: Optional[datetime] = None,
    ) -> bool:
        if not permit_token:
            raise ValueError("VLM circuit permit token is required")
        current = self._vlm_circuit_utc(now or _utc_now())
        current_iso = current.isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            receipt = connection.execute(
                """
                SELECT generation, half_open_probe, failed
                FROM eligibility_vlm_circuit_samples
                WHERE tenant_id = ? AND profile_digest = ? AND permit_token = ?
                """,
                (TENANT_PLACEHOLDER, profile_digest, permit_token),
            ).fetchone()
            if receipt is not None:
                identical = (
                    int(receipt["generation"]) == generation
                    and bool(receipt["half_open_probe"]) == half_open_probe
                    and bool(receipt["failed"]) == failed
                )
                connection.commit()
                return identical
            permit = connection.execute(
                """
                SELECT generation, half_open_probe, expires_at
                FROM eligibility_vlm_circuit_permits
                WHERE tenant_id = ? AND profile_digest = ? AND permit_token = ?
                """,
                (TENANT_PLACEHOLDER, profile_digest, permit_token),
            ).fetchone()
            if (
                permit is None
                or int(permit["generation"]) != generation
                or bool(permit["half_open_probe"]) != half_open_probe
            ):
                connection.commit()
                return False
            row = connection.execute(
                """
                SELECT * FROM eligibility_vlm_circuit_state
                WHERE tenant_id = ? AND profile_digest = ?
                """,
                (TENANT_PLACEHOLDER, profile_digest),
            ).fetchone()
            if row is None:
                connection.commit()
                return False
            updated_at = datetime.fromisoformat(str(row["updated_at"]))
            if current < updated_at:
                raise RuntimeStoreIntegrityError(
                    "VLM circuit clock moved backwards"
                )
            if int(row["generation"]) != generation:
                connection.commit()
                return False
            sequence = int(row["next_sample_sequence"])
            permit_expires_at = datetime.fromisoformat(str(permit["expires_at"]))
            if half_open_probe:
                if (
                    row["state"] != "half_open"
                    or not permit_token
                    or row["half_open_permit_token"] != permit_token
                ):
                    connection.commit()
                    return False
                expires_at = datetime.fromisoformat(str(row["half_open_expires_at"]))
                if current >= expires_at or current >= permit_expires_at:
                    connection.execute(
                        """
                        UPDATE eligibility_vlm_circuit_state
                        SET state = 'open', generation = generation + 1,
                            opened_at = ?, half_open_permit_token = NULL,
                            half_open_expires_at = NULL, updated_at = ?
                        WHERE tenant_id = ? AND profile_digest = ?
                          AND generation = ? AND state = 'half_open'
                          AND half_open_permit_token = ?
                        """,
                        (
                            current_iso,
                            current_iso,
                            TENANT_PLACEHOLDER,
                            profile_digest,
                            generation,
                            permit_token,
                        ),
                    )
                    connection.commit()
                    return False
                connection.execute(
                    """
                    INSERT INTO eligibility_vlm_circuit_samples(
                        tenant_id, profile_digest, sample_sequence,
                        generation, permit_token, half_open_probe,
                        failed, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        profile_digest,
                        sequence,
                        generation,
                        permit_token,
                        int(failed),
                        current_iso,
                    ),
                )
                next_state = "open" if failed else "closed"
                opened_at = current_iso if failed else None
                connection.execute(
                    """
                    UPDATE eligibility_vlm_circuit_state
                    SET state = ?, generation = generation + 1,
                        opened_at = ?, half_open_permit_token = NULL,
                        half_open_expires_at = NULL,
                        next_sample_sequence = ?, updated_at = ?
                    WHERE tenant_id = ? AND profile_digest = ?
                      AND generation = ? AND state = 'half_open'
                      AND half_open_permit_token = ?
                    """,
                    (
                        next_state,
                        opened_at,
                        sequence + 1,
                        current_iso,
                        TENANT_PLACEHOLDER,
                        profile_digest,
                        generation,
                        permit_token,
                    ),
                )
                connection.commit()
                return True
            if row["state"] != "closed":
                connection.commit()
                return False
            if current >= permit_expires_at:
                connection.commit()
                return False
            connection.execute(
                """
                INSERT INTO eligibility_vlm_circuit_samples(
                    tenant_id, profile_digest, sample_sequence,
                    generation, permit_token, half_open_probe,
                    failed, recorded_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    profile_digest,
                    sequence,
                    generation,
                    permit_token,
                    int(failed),
                    current_iso,
                ),
            )
            sample = connection.execute(
                """
                SELECT COUNT(*) AS sample_count, COALESCE(SUM(failed), 0) AS failure_count
                FROM (
                    SELECT failed FROM eligibility_vlm_circuit_samples
                    WHERE tenant_id = ? AND profile_digest = ? AND generation = ?
                    ORDER BY sample_sequence DESC
                    LIMIT ?
                )
                """,
                (
                    TENANT_PLACEHOLDER,
                    profile_digest,
                    generation,
                    int(row["rolling_window_size"]),
                ),
            ).fetchone()
            sample_count = int(sample["sample_count"])
            failure_count = int(sample["failure_count"])
            should_open = (
                sample_count >= int(row["minimum_sample_size"])
                and failure_count * int(row["failure_threshold_denominator"])
                >= sample_count * int(row["failure_threshold_numerator"])
            )
            connection.execute(
                """
                UPDATE eligibility_vlm_circuit_state
                SET state = ?, generation = generation + ?, opened_at = ?,
                    next_sample_sequence = ?, updated_at = ?
                WHERE tenant_id = ? AND profile_digest = ?
                  AND generation = ? AND state = 'closed'
                """,
                (
                    "open" if should_open else "closed",
                    int(should_open),
                    current_iso if should_open else None,
                    sequence + 1,
                    current_iso,
                    TENANT_PLACEHOLDER,
                    profile_digest,
                    generation,
                ),
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def eligibility_vlm_circuit_state(
        self, profile_digest: str
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT state, generation, opened_at, half_open_expires_at, updated_at
                FROM eligibility_vlm_circuit_state
                WHERE tenant_id = ? AND profile_digest = ?
                """,
                (TENANT_PLACEHOLDER, profile_digest),
            ).fetchone()
        return dict(row) if row is not None else None

    def replace_eligibility_rule_revision(
        self,
        project_id: str,
        rule_revision: str,
        criteria: Iterable[Dict[str, Any]],
        *,
        created_at: Optional[datetime] = None,
    ) -> None:
        rows = list(criteria)
        if not project_id or not rule_revision or not rows:
            raise ValueError("project_id, rule_revision and criteria are required")
        normalized_rows = []
        seen = set()
        for row in rows:
            criterion_uid = str(row.get("criterion_uid") or "")
            criterion_kind = str(row.get("criterion_kind") or "")
            if not criterion_uid or criterion_uid in seen:
                raise ValueError("criterion_uid must be non-empty and unique")
            if criterion_kind not in {"inclusion", "exclusion"}:
                raise ValueError("criterion_kind must be inclusion or exclusion")
            seen.add(criterion_uid)
            normalized_rows.append(
                (
                    rule_revision,
                    criterion_uid,
                    criterion_kind,
                    row.get("source_rule_label"),
                    _canonical_json(row.get("source_locator") or {}),
                    str(row.get("normalized_text_hash") or ""),
                    int(row.get("display_order") or 0),
                )
            )
        normalized_rows.sort(key=lambda item: (item[6], item[1]))
        timestamp = (created_at or _utc_now()).isoformat()
        connection = self._connect()
        try:
            current_rows = [
                tuple(row)
                for row in connection.execute(
                    """
                    SELECT rule_revision, criterion_uid, criterion_kind,
                           source_rule_label, source_locator_json,
                           normalized_text_hash, display_order
                    FROM eligibility_rule_revisions
                    WHERE tenant_id = ? AND project_id = ? AND is_current = 1
                    ORDER BY display_order, criterion_uid
                    """,
                    (TENANT_PLACEHOLDER, project_id),
                ).fetchall()
            ]
            if current_rows == normalized_rows:
                return
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE eligibility_rule_revisions SET is_current = 0
                WHERE tenant_id = ? AND project_id = ? AND is_current = 1
                """,
                (TENANT_PLACEHOLDER, project_id),
            )
            for row in rows:
                criterion_uid = str(row.get("criterion_uid") or "")
                criterion_kind = str(row.get("criterion_kind") or "")
                connection.execute(
                    """
                    INSERT INTO eligibility_rule_revisions(
                        tenant_id, project_id, rule_revision, criterion_uid,
                        criterion_kind, source_rule_label, source_locator_json,
                        normalized_text_hash, display_order, is_current, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(tenant_id, project_id, rule_revision, criterion_uid)
                    DO UPDATE SET
                        criterion_kind=excluded.criterion_kind,
                        source_rule_label=excluded.source_rule_label,
                        source_locator_json=excluded.source_locator_json,
                        normalized_text_hash=excluded.normalized_text_hash,
                        display_order=excluded.display_order,
                        is_current=1
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        rule_revision,
                        criterion_uid,
                        criterion_kind,
                        row.get("source_rule_label"),
                        _canonical_json(row.get("source_locator") or {}),
                        str(row.get("normalized_text_hash") or ""),
                        int(row.get("display_order") or 0),
                        timestamp,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def replace_eligibility_subject_sources(
        self,
        project_id: str,
        subject_id: str,
        subject_source_revision: str,
        sources: Iterable[Dict[str, Any]],
        *,
        created_at: Optional[datetime] = None,
    ) -> None:
        rows = list(sources)
        if not project_id or not subject_id or not subject_source_revision or not rows:
            raise ValueError(
                "project_id, subject_id, subject_source_revision and sources are required"
            )
        normalized_rows = []
        seen = set()
        allowed_unit_kinds = {
            "page",
            "image",
            "document",
            "file",
            "archive_container",
            "legacy_unknown",
        }
        for row in rows:
            source_id = str(row.get("source_id") or "")
            source_revision = str(row.get("source_revision") or "")
            key = (source_id, source_revision)
            if not all(key) or key in seen:
                raise ValueError("source identity must be non-empty and unique")
            processing_unit_kind = str(
                row.get("processing_unit_kind") or "legacy_unknown"
            )
            expected_unit_count = int(row.get("expected_unit_count") or 0)
            if (
                expected_unit_count < 0
                or processing_unit_kind not in allowed_unit_kinds
            ):
                raise ValueError("source processing-unit contract is invalid")
            seen.add(key)
            normalized_rows.append(
                (
                    source_id,
                    source_revision,
                    subject_source_revision,
                    str(row.get("content_hash") or ""),
                    int(row.get("size_bytes") or 0),
                    str(row.get("media_class") or "unknown"),
                    processing_unit_kind,
                    expected_unit_count,
                )
            )
        normalized_rows.sort(key=lambda item: (item[0], item[1]))
        timestamp = (created_at or _utc_now()).isoformat()
        connection = self._connect()
        try:
            current_rows = [
                tuple(row)
                for row in connection.execute(
                    """
                    SELECT source_id, source_revision, subject_source_revision,
                           content_hash, size_bytes, media_class,
                           processing_unit_kind, expected_unit_count
                    FROM eligibility_source_revisions
                    WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                      AND is_current = 1
                    ORDER BY source_id, source_revision
                    """,
                    (TENANT_PLACEHOLDER, project_id, subject_id),
                ).fetchall()
            ]
            if current_rows == normalized_rows:
                return
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE eligibility_source_revisions SET is_current = 0
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND is_current = 1
                """,
                (TENANT_PLACEHOLDER, project_id, subject_id),
            )
            for row in rows:
                source_id = str(row.get("source_id") or "")
                source_revision = str(row.get("source_revision") or "")
                connection.execute(
                    """
                    INSERT INTO eligibility_source_revisions(
                        tenant_id, project_id, subject_id, source_id,
                        source_revision, subject_source_revision, content_hash,
                        size_bytes, media_class, processing_unit_kind,
                        expected_unit_count, is_current, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(
                        tenant_id, project_id, subject_id, source_id, source_revision
                    ) DO UPDATE SET
                        subject_source_revision=excluded.subject_source_revision,
                        content_hash=excluded.content_hash,
                        size_bytes=excluded.size_bytes,
                        media_class=excluded.media_class,
                        processing_unit_kind=excluded.processing_unit_kind,
                        expected_unit_count=excluded.expected_unit_count,
                        is_current=1
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        subject_id,
                        source_id,
                        source_revision,
                        subject_source_revision,
                        str(row.get("content_hash") or ""),
                        int(row.get("size_bytes") or 0),
                        str(row.get("media_class") or "unknown"),
                        str(row.get("processing_unit_kind") or "legacy_unknown"),
                        int(row.get("expected_unit_count") or 0),
                        timestamp,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def eligibility_current_subject_source_revision(
        self,
        project_id: str,
        subject_id: str,
    ) -> Optional[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT subject_source_revision
                FROM eligibility_source_revisions
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND is_current = 1
                """,
                (TENANT_PLACEHOLDER, project_id, subject_id),
            ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise RuntimeStoreIntegrityError(
                "current eligibility sources have inconsistent subject revisions"
            )
        return str(rows[0]["subject_source_revision"])

    @staticmethod
    def _eligibility_evidence_job_payload(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            key: row[key]
            for key in (
                "project_id", "subject_id", "job_id", "job_kind", "profile_version", "source_id",
                "source_revision", "subject_source_revision", "cache_key", "status",
                "priority", "attempt_count", "max_attempts", "lease_owner",
                "provider_attempt_count",
                "lease_expires_at", "next_run_at", "progress_current",
                "progress_total", "error_code", "created_at", "updated_at",
                "completed_at", "parent_job_id", "input_artifact_id", "page_index",
                "profile_digest", "lease_token",
            )
        }

    def register_eligibility_vlm_profile(
        self,
        profile_version: str,
        profile_digest: str,
        *,
        status: str = "approved",
        profile_payload_hash: Optional[str] = None,
        max_attempts_limit: int = 3,
        created_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if (
            not profile_version
            or len(profile_digest) != 64
            or any(character not in "0123456789abcdef" for character in profile_digest)
        ):
            raise ValueError("VLM profile identity is invalid")
        if status not in {"approved", "disabled"}:
            raise ValueError("VLM profile status is invalid")
        if not 1 <= max_attempts_limit <= 10:
            raise ValueError("VLM profile max attempts limit is invalid")
        payload_hash = profile_payload_hash or profile_digest
        if (
            len(payload_hash) != 64
            or any(character not in "0123456789abcdef" for character in payload_hash)
        ):
            raise ValueError("VLM profile payload hash is invalid")
        timestamp = (created_at or _utc_now()).isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT OR IGNORE INTO eligibility_vlm_profile_revisions(
                    tenant_id, profile_version, profile_digest,
                    profile_payload_hash, max_attempts_limit, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER, profile_version, profile_digest,
                    payload_hash, max_attempts_limit, timestamp,
                ),
            )
            persisted_revision = connection.execute(
                """
                SELECT profile_payload_hash, max_attempts_limit
                FROM eligibility_vlm_profile_revisions
                WHERE tenant_id = ? AND profile_version = ? AND profile_digest = ?
                """,
                (TENANT_PLACEHOLDER, profile_version, profile_digest),
            ).fetchone()
            if (
                persisted_revision is None
                or persisted_revision["profile_payload_hash"] != payload_hash
                or persisted_revision["max_attempts_limit"] != max_attempts_limit
            ):
                raise RuntimeStoreIntegrityError(
                    "VLM profile digest is already bound to different payload"
                )
            revision = connection.execute(
                """
                SELECT state_revision FROM eligibility_vlm_profile_state
                WHERE tenant_id = ? AND profile_version = ?
                """,
                (TENANT_PLACEHOLDER, profile_version),
            ).fetchone()
            state_revision = int(revision["state_revision"]) + 1 if revision else 1
            connection.execute(
                """
                INSERT INTO eligibility_vlm_profile_state(
                    tenant_id, profile_version, profile_digest,
                    state_revision, enabled, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, profile_version) DO UPDATE SET
                    profile_digest=excluded.profile_digest,
                    state_revision=excluded.state_revision,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    TENANT_PLACEHOLDER, profile_version, profile_digest,
                    state_revision, 1 if status == "approved" else 0, timestamp,
                ),
            )
            connection.commit()
            return {
                "profile_version": profile_version,
                "profile_digest": profile_digest,
                "state_revision": state_revision,
                "enabled": status == "approved",
                "updated_at": timestamp,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def register_eligibility_controlled_artifact(
        self,
        *,
        project_id: str,
        subject_id: str,
        artifact_id: str,
        artifact_revision_token: str,
        data_class: str,
        authorization_ref: str,
        retention_policy_id: str,
        authorization_state: str = "authorized",
        legal_hold: bool = False,
        governance_revision: Optional[int] = None,
        created_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if not all((project_id, subject_id, artifact_id, artifact_revision_token,
                    authorization_ref, retention_policy_id)):
            raise ValueError("controlled artifact governance is incomplete")
        if self.controlled_artifact_policy_resolver is None:
            raise RuntimeStoreIntegrityError(
                "controlled artifact policy resolver is not configured"
            )
        timestamp = (created_at or _utc_now()).isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            artifact = connection.execute(
                """
                SELECT * FROM eligibility_evidence_artifacts
                WHERE tenant_id = ? AND project_id = ? AND artifact_id = ?
                """,
                (TENANT_PLACEHOLDER, project_id, artifact_id),
            ).fetchone()
            if artifact is None or artifact["subject_id"] != subject_id:
                raise ValueError("controlled artifact does not belong to subject")
            artifact_payload = dict(artifact)
            policy = self.controlled_artifact_policy_resolver(
                project_id, subject_id, artifact_payload
            )
            if not isinstance(policy, dict):
                raise RuntimeStoreIntegrityError(
                    "controlled artifact policy resolution failed"
                )
            required_policy = {
                "data_class", "authorization_state", "authorization_ref",
                "retention_policy_id", "legal_hold",
            }
            if required_policy.difference(policy):
                raise RuntimeStoreIntegrityError(
                    "controlled artifact policy is incomplete"
                )
            derived_token = self._controlled_artifact_revision_token(
                project_id, subject_id, artifact_payload
            )
            supplied_policy = {
                "data_class": data_class,
                "authorization_state": authorization_state,
                "authorization_ref": authorization_ref,
                "retention_policy_id": retention_policy_id,
                "legal_hold": bool(legal_hold),
            }
            normalized_policy = {
                "data_class": str(policy["data_class"]),
                "authorization_state": str(policy["authorization_state"]),
                "authorization_ref": str(policy["authorization_ref"]),
                "retention_policy_id": str(policy["retention_policy_id"]),
                "legal_hold": bool(policy["legal_hold"]),
            }
            if supplied_policy != normalized_policy:
                raise ValueError("controlled artifact governance is not server-authoritative")
            if artifact_revision_token != derived_token:
                raise ValueError("controlled artifact revision token is not server-derived")
            data_class = normalized_policy["data_class"]
            authorization_state = normalized_policy["authorization_state"]
            authorization_ref = normalized_policy["authorization_ref"]
            retention_policy_id = normalized_policy["retention_policy_id"]
            legal_hold = normalized_policy["legal_hold"]
            if data_class not in {"synthetic_fixture", "clinical_restricted"}:
                raise RuntimeStoreIntegrityError("controlled artifact data class is invalid")
            if authorization_state not in {"authorized", "denied"}:
                raise RuntimeStoreIntegrityError(
                    "controlled artifact authorization state is invalid"
                )
            source = connection.execute(
                """
                SELECT 1 FROM eligibility_source_revisions
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND source_id = ? AND source_revision = ? AND is_current = 1
                """,
                (
                    TENANT_PLACEHOLDER, project_id, subject_id,
                    artifact["source_id"], artifact["source_revision"],
                ),
            ).fetchone()
            if source is None:
                raise ValueError("controlled artifact source revision is not current")
            current = connection.execute(
                """
                SELECT governance_revision FROM eligibility_controlled_artifact_state
                WHERE tenant_id = ? AND project_id = ? AND artifact_id = ?
                """,
                (TENANT_PLACEHOLDER, project_id, artifact_id),
            ).fetchone()
            expected_revision = int(current["governance_revision"]) + 1 if current else 1
            if governance_revision is not None and governance_revision != expected_revision:
                raise StaleRuntimeStateError("controlled artifact governance revision is stale")
            governance_revision = expected_revision
            values = (
                TENANT_PLACEHOLDER, project_id, subject_id, artifact_id,
                artifact_revision_token, governance_revision, data_class,
                authorization_state, authorization_ref, retention_policy_id,
                1 if legal_hold else 0, artifact["source_revision"],
                artifact["extraction_revision"], timestamp,
            )
            connection.execute(
                """
                INSERT INTO eligibility_controlled_artifact_records(
                    tenant_id, project_id, subject_id, artifact_id,
                    artifact_revision_token, governance_revision, data_class,
                    authorization_state, authorization_ref, retention_policy_id,
                    legal_hold, source_revision, extraction_revision, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            connection.execute(
                """
                INSERT INTO eligibility_controlled_artifact_state(
                    tenant_id, project_id, subject_id, artifact_id,
                    artifact_revision_token, governance_revision, data_class,
                    authorization_state, authorization_ref, retention_policy_id,
                    legal_hold, source_revision, extraction_revision, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, project_id, artifact_id) DO UPDATE SET
                    subject_id=excluded.subject_id,
                    artifact_revision_token=excluded.artifact_revision_token,
                    governance_revision=excluded.governance_revision,
                    data_class=excluded.data_class,
                    authorization_state=excluded.authorization_state,
                    authorization_ref=excluded.authorization_ref,
                    retention_policy_id=excluded.retention_policy_id,
                    legal_hold=excluded.legal_hold,
                    source_revision=excluded.source_revision,
                    extraction_revision=excluded.extraction_revision,
                    updated_at=excluded.updated_at
                """,
                values,
            )
            connection.commit()
            return {
                "project_id": project_id,
                "subject_id": subject_id,
                "artifact_id": artifact_id,
                "artifact_revision_token": artifact_revision_token,
                "governance_revision": governance_revision,
                "data_class": data_class,
                "authorization_state": authorization_state,
                "authorization_ref": authorization_ref,
                "retention_policy_id": retention_policy_id,
                "legal_hold": legal_hold,
                "source_revision": artifact["source_revision"],
                "extraction_revision": artifact["extraction_revision"],
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _controlled_artifact_revision_token(
        project_id: str, subject_id: str, artifact: Dict[str, Any]
    ) -> str:
        return "eligartrev_" + _payload_hash(
            {
                "project_id": project_id,
                "subject_id": subject_id,
                "artifact_id": artifact["artifact_id"],
                "content_hash": artifact["content_hash"],
                "size_bytes": artifact["size_bytes"],
                "source_id": artifact["source_id"],
                "source_revision": artifact["source_revision"],
                "extraction_revision": artifact["extraction_revision"],
            }
        )[:32]

    def eligibility_controlled_artifact_revision_token(
        self, project_id: str, artifact_id: str
    ) -> str:
        artifact = self.eligibility_evidence_artifact(project_id, artifact_id)
        if artifact is None:
            raise ValueError("controlled artifact is not in the current project")
        return self._controlled_artifact_revision_token(
            project_id, str(artifact["subject_id"]), artifact
        )

    def create_eligibility_evidence_job(
        self,
        job: Dict[str, Any],
        *,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Dict[str, Any]:
        required = {
            "project_id", "subject_id", "job_id", "job_kind", "profile_version", "source_id",
            "source_revision", "subject_source_revision", "cache_key",
            "max_attempts",
        }
        missing = sorted(required.difference(job))
        if missing:
            raise ValueError(f"eligibility evidence job missing fields: {missing}")
        if not idempotency_key or not request_fingerprint:
            raise ValueError("eligibility evidence job idempotency is required")
        project_id = str(job["project_id"])
        subject_id = str(job["subject_id"])
        operation = f"eligibility_evidence_job_create:{subject_id}"
        request_id = f"req_{uuid4().hex}"
        timestamp = str(job.get("created_at") or _utc_now().isoformat())
        relation = (
            job.get("parent_job_id"),
            job.get("input_artifact_id"),
            job.get("page_index"),
        )
        if any(value is not None for value in relation) and not all(
            value is not None for value in relation
        ):
            raise ValueError("eligibility evidence parent relation must be complete")
        profile_digest = job.get("profile_digest")
        job_kind = str(job["job_kind"])
        vlm_binding = job.get("vlm_binding")
        if job_kind == "ocr":
            from .ocr_gateway import ocr_profile_digest

            expected_digest = ocr_profile_digest(str(job["profile_version"]))
            if profile_digest != expected_digest:
                raise ValueError("OCR evidence job profile digest does not match profile")
        elif job_kind == "vlm":
            if not isinstance(profile_digest, str) or len(profile_digest) != 64:
                raise ValueError("VLM evidence job requires an exact profile digest")
            if not isinstance(vlm_binding, dict):
                raise ValueError("VLM evidence job requires a controlled artifact binding")
            if not all(value is not None for value in relation):
                raise ValueError("VLM evidence job requires a complete artifact relation")
        elif profile_digest is not None:
            raise ValueError("profile digest is only supported for OCR or VLM jobs")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if job_kind == "ocr" and all(value is not None for value in relation):
                self._validate_pdf_page_ocr_child(
                    connection,
                    job,
                    parent_job_id=str(relation[0]),
                    input_artifact_id=str(relation[1]),
                    page_index=int(relation[2]),
                )
            elif job_kind == "vlm":
                self._validate_vlm_job_binding(connection, job, vlm_binding)
            replay_request_id = self._idempotency_result(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay_request_id is not None:
                row = connection.execute(
                    """
                    SELECT * FROM eligibility_evidence_jobs
                    WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                      AND idempotency_key = ? AND request_id = ?
                    """,
                    (
                        TENANT_PLACEHOLDER, project_id, subject_id,
                        idempotency_key, replay_request_id,
                    ),
                ).fetchone()
                if row is None:
                    raise RuntimeStoreIntegrityError(
                        "eligibility evidence job idempotency record is orphaned"
                    )
                connection.rollback()
                return {"job": self._eligibility_evidence_job_payload(row), "replayed": True}
            connection.execute(
                """
                INSERT INTO eligibility_evidence_jobs(
                    tenant_id, project_id, subject_id, job_id, job_kind, profile_version,
                    source_id, source_revision, subject_source_revision,
                    cache_key, status, priority, attempt_count, max_attempts,
                    progress_current, progress_total, idempotency_key,
                    request_hash, request_id, created_at, updated_at,
                    parent_job_id, input_artifact_id, page_index, profile_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, 0, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER, project_id, subject_id, str(job["job_id"]),
                    str(job["job_kind"]), str(job["profile_version"]), str(job["source_id"]),
                    str(job["source_revision"]), str(job["subject_source_revision"]),
                    str(job["cache_key"]), int(job.get("priority") or 0),
                    int(job["max_attempts"]), idempotency_key, request_fingerprint,
                    request_id, timestamp, timestamp,
                    relation[0], relation[1], relation[2], profile_digest,
                ),
            )
            if job_kind == "vlm":
                connection.execute(
                    """
                    INSERT INTO eligibility_vlm_job_bindings(
                        tenant_id, project_id, subject_id, job_id,
                        artifact_id, artifact_revision_token, governance_revision,
                        profile_version, profile_digest, source_id, source_revision,
                        extraction_revision, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        TENANT_PLACEHOLDER, project_id, subject_id,
                        str(job["job_id"]), str(vlm_binding["artifact_id"]),
                        str(vlm_binding["artifact_revision_token"]),
                        int(vlm_binding["governance_revision"]),
                        str(job["profile_version"]), str(profile_digest),
                        str(job["source_id"]),
                        str(job["source_revision"]),
                        str(vlm_binding["extraction_revision"]), timestamp,
                    ),
                )
            self._insert_idempotency(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            row = connection.execute(
                "SELECT * FROM eligibility_evidence_jobs WHERE tenant_id = ? AND project_id = ? AND job_id = ?",
                (TENANT_PLACEHOLDER, project_id, str(job["job_id"])),
            ).fetchone()
            connection.commit()
            return {"job": self._eligibility_evidence_job_payload(row), "replayed": False}
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise IdempotencyConflictError(
                "eligibility evidence job identity or cache key already exists"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_eligibility_vlm_bound_job(
        self,
        job: Dict[str, Any],
        *,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Dict[str, Any]:
        if str(job.get("job_kind") or "") != "vlm":
            raise ValueError("bound VLM job must use job_kind=vlm")
        project_id = str(job.get("project_id") or "")
        artifact_id = str(job.get("artifact_id") or job.get("input_artifact_id") or "")
        if not project_id or not artifact_id:
            raise ValueError("bound VLM job artifact identity is required")
        artifact = self.eligibility_evidence_artifact(project_id, artifact_id)
        if artifact is None:
            raise ValueError("bound VLM job artifact is not in the current project")
        locator = artifact.get("locator") or {}
        page_index = int(locator.get("page") or 1)
        prepared = {
            **job,
            "parent_job_id": artifact["job_id"],
            "input_artifact_id": artifact_id,
            "page_index": page_index,
            "vlm_binding": {
                "artifact_id": artifact_id,
                "artifact_revision_token": job.get("artifact_revision_token"),
                "governance_revision": job.get("governance_revision"),
                "extraction_revision": artifact["extraction_revision"],
            },
        }
        return self.create_eligibility_evidence_job(
            prepared,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )

    def _validate_vlm_job_binding(
        self,
        connection: sqlite3.Connection,
        job: Dict[str, Any],
        binding: Dict[str, Any],
    ) -> None:
        required = {
            "artifact_id", "artifact_revision_token",
            "governance_revision", "extraction_revision",
        }
        missing = sorted(required.difference(binding))
        if missing:
            raise ValueError(f"VLM artifact binding missing fields: {missing}")
        project_id = str(job["project_id"])
        subject_id = str(job["subject_id"])
        artifact_id = str(binding["artifact_id"])
        if artifact_id != str(job.get("input_artifact_id") or ""):
            raise ValueError("VLM input artifact identity does not match binding")
        profile = connection.execute(
            """
            SELECT s.*, r.max_attempts_limit
            FROM eligibility_vlm_profile_state s
            JOIN eligibility_vlm_profile_revisions r
              ON r.tenant_id = s.tenant_id
             AND r.profile_version = s.profile_version
             AND r.profile_digest = s.profile_digest
            WHERE s.tenant_id = ? AND s.profile_version = ?
              AND s.profile_digest = ? AND s.enabled = 1
            """,
            (
                TENANT_PLACEHOLDER, str(job["profile_version"]),
                str(job["profile_digest"]),
            ),
        ).fetchone()
        if profile is None:
            raise ValueError("VLM profile is not currently approved")
        if int(job["max_attempts"]) > int(profile["max_attempts_limit"]):
            raise ValueError("VLM job max attempts exceeds approved profile limit")
        artifact = connection.execute(
            """
            SELECT a.*, s.artifact_revision_token, s.governance_revision,
                   s.data_class, s.authorization_state, s.authorization_ref,
                   s.retention_policy_id, s.legal_hold,
                   s.source_revision AS governed_source_revision,
                   s.extraction_revision AS governed_extraction_revision
            FROM eligibility_evidence_artifacts a
            JOIN eligibility_controlled_artifact_state s
              ON s.tenant_id = a.tenant_id
             AND s.project_id = a.project_id
             AND s.artifact_id = a.artifact_id
            WHERE a.tenant_id = ? AND a.project_id = ? AND a.artifact_id = ?
            """,
            (TENANT_PLACEHOLDER, project_id, artifact_id),
        ).fetchone()
        if artifact is None or artifact["subject_id"] != subject_id:
            raise ValueError("VLM controlled artifact does not belong to subject")
        if artifact["source_id"] != str(job["source_id"]):
            raise ValueError("VLM controlled artifact source does not match job")
        if artifact["authorization_state"] != "authorized":
            raise ValueError("VLM controlled artifact is not authorized")
        if artifact["legal_hold"]:
            raise ValueError("VLM controlled artifact is under legal hold")
        expected = (
            artifact["artifact_revision_token"],
            int(artifact["governance_revision"]),
            artifact["governed_extraction_revision"],
            artifact["source_revision"],
        )
        supplied = (
            str(binding["artifact_revision_token"]),
            int(binding["governance_revision"]),
            str(binding["extraction_revision"]),
            str(job["source_revision"]),
        )
        if supplied != expected:
            raise ValueError("VLM controlled artifact binding is stale")
        source = connection.execute(
            """
            SELECT 1 FROM eligibility_source_revisions
            WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
              AND source_id = ? AND source_revision = ?
              AND subject_source_revision = ? AND is_current = 1
            """,
            (
                TENANT_PLACEHOLDER, project_id, subject_id,
                str(job["source_id"]), str(job["source_revision"]),
                str(job["subject_source_revision"]),
            ),
        ).fetchone()
        if source is None:
            raise ValueError("VLM source revision is not current")

    def _validate_pdf_page_ocr_child(
        self,
        connection: sqlite3.Connection,
        job: Dict[str, Any],
        *,
        parent_job_id: str,
        input_artifact_id: str,
        page_index: int,
    ) -> None:
        if (
            str(job["job_kind"]) != "ocr"
            or str(job["profile_version"]) not in {"ocr-glm-v1", "ocr-paddle-v1"}
            or page_index < 1
        ):
            raise ValueError("PDF page child must be an allowlisted OCR profile")
        project_id = str(job["project_id"])
        parent = connection.execute(
            """
            SELECT * FROM eligibility_evidence_jobs
            WHERE tenant_id = ? AND project_id = ? AND job_id = ?
            """,
            (TENANT_PLACEHOLDER, project_id, parent_job_id),
        ).fetchone()
        if (
            parent is None
            or parent["status"] != "succeeded"
            or parent["job_kind"] != "pdf_page_render"
            or parent["profile_version"] != "pdf-render-200dpi-v1"
        ):
            raise ValueError("completed PDF render parent job is required")
        identity_fields = (
            "subject_id", "source_id", "source_revision", "subject_source_revision"
        )
        if any(str(parent[field]) != str(job[field]) for field in identity_fields):
            raise ValueError("PDF render parent identity does not match OCR child")
        artifact = connection.execute(
            """
            SELECT * FROM eligibility_evidence_artifacts
            WHERE tenant_id = ? AND project_id = ? AND artifact_id = ?
            """,
            (TENANT_PLACEHOLDER, project_id, input_artifact_id),
        ).fetchone()
        if artifact is None:
            raise ValueError("PDF page input artifact is not in the current project")
        try:
            locator = json.loads(artifact["locator_json"])
        except (TypeError, ValueError):
            raise RuntimeStoreIntegrityError("PDF page artifact locator is invalid") from None
        artifact_hash = str(artifact["content_hash"])
        try:
            valid_full_hash = (
                len(artifact_hash) == 64
                and len(bytes.fromhex(artifact_hash)) == 32
            )
        except ValueError:
            valid_full_hash = False
        if (
            artifact["job_id"] != parent_job_id
            or artifact["subject_id"] != parent["subject_id"]
            or artifact["source_id"] != parent["source_id"]
            or artifact["source_revision"] != parent["source_revision"]
            or artifact["artifact_kind"] != "pdf_page_image"
            or artifact["media_type"] != "image/png"
            or locator.get("page") != page_index
            or not valid_full_hash
        ):
            raise ValueError("PDF page artifact does not match completed render parent")

    def eligibility_evidence_job(self, project_id: str, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM eligibility_evidence_jobs WHERE tenant_id = ? AND project_id = ? AND job_id = ?",
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()
        return self._eligibility_evidence_job_payload(row) if row else None

    def eligibility_evidence_job_by_cache(
        self, project_id: str, subject_id: str, cache_key: str
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM eligibility_evidence_jobs
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND cache_key = ?
                """,
                (TENANT_PLACEHOLDER, project_id, subject_id, cache_key),
            ).fetchone()
        return self._eligibility_evidence_job_payload(row) if row else None

    def eligibility_subject_evidence_jobs(
        self, project_id: str, subject_id: str
    ) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM eligibility_evidence_jobs
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                ORDER BY created_at DESC, job_id DESC
                """,
                (TENANT_PLACEHOLDER, project_id, subject_id),
            ).fetchall()
        return [self._eligibility_evidence_job_payload(row) for row in rows]

    def claim_next_eligibility_evidence_job(
        self,
        worker_id: str,
        *,
        now: Optional[datetime] = None,
        lease_seconds: int = 300,
        job_kind: Optional[str] = None,
        profile_version: Optional[str] = None,
        profile_digest: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not worker_id or lease_seconds < 1:
            raise ValueError("worker_id and positive lease_seconds are required")
        current = now or _utc_now()
        current_iso = current.isoformat()
        lease_iso = (current + timedelta(seconds=lease_seconds)).isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            filters = [
                "tenant_id = ?",
                "(job_kind = 'vlm' OR attempt_count < max_attempts)",
                "(status = 'queued' OR (status = 'retry_wait' AND next_run_at <= ?) OR (status = 'running' AND lease_expires_at <= ?))",
            ]
            parameters: List[Any] = [TENANT_PLACEHOLDER, current_iso, current_iso]
            if job_kind is not None:
                filters.append("job_kind = ?")
                parameters.append(job_kind)
            else:
                filters.append("job_kind <> 'vlm'")
            if profile_version is not None:
                filters.append("profile_version = ?")
                parameters.append(profile_version)
            if profile_digest is not None:
                filters.append("profile_digest = ?")
                parameters.append(profile_digest)
            if job_kind == "vlm":
                filters.append("provider_attempt_count < max_attempts")
                filters.append(
                    """EXISTS (
                        SELECT 1
                        FROM eligibility_vlm_job_bindings b
                        JOIN eligibility_vlm_profile_state p
                          ON p.tenant_id = b.tenant_id
                         AND p.profile_version = b.profile_version
                         AND p.profile_digest = b.profile_digest
                         AND p.enabled = 1
                        JOIN eligibility_controlled_artifact_state g
                          ON g.tenant_id = b.tenant_id
                         AND g.project_id = b.project_id
                         AND g.artifact_id = b.artifact_id
                         AND g.artifact_revision_token = b.artifact_revision_token
                         AND g.governance_revision = b.governance_revision
                         AND g.authorization_state = 'authorized'
                         AND g.legal_hold = 0
                        JOIN eligibility_source_revisions s
                          ON s.tenant_id = eligibility_evidence_jobs.tenant_id
                         AND s.project_id = eligibility_evidence_jobs.project_id
                         AND s.subject_id = eligibility_evidence_jobs.subject_id
                         AND s.source_id = eligibility_evidence_jobs.source_id
                         AND s.source_revision = eligibility_evidence_jobs.source_revision
                         AND s.subject_source_revision = eligibility_evidence_jobs.subject_source_revision
                         AND s.is_current = 1
                        WHERE b.tenant_id = eligibility_evidence_jobs.tenant_id
                          AND b.project_id = eligibility_evidence_jobs.project_id
                          AND b.job_id = eligibility_evidence_jobs.job_id
                    )"""
                )
            row = connection.execute(
                f"""
                SELECT * FROM eligibility_evidence_jobs
                WHERE {' AND '.join(filters)}
                ORDER BY priority DESC, created_at, job_id
                LIMIT 1
                """,
                tuple(parameters),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            if row["status"] == "running":
                connection.execute(
                    """
                    UPDATE eligibility_evidence_job_attempts
                    SET finished_at = ?, outcome = 'lease_expired', error_code = 'lease_expired'
                    WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                      AND attempt_number = ? AND finished_at IS NULL
                    """,
                    (
                        current_iso, TENANT_PLACEHOLDER, row["project_id"],
                        row["job_id"], row["attempt_count"],
                    ),
                )
            attempt_number = int(row["attempt_count"]) + 1
            lease_token = f"lease_{uuid4().hex}"
            connection.execute(
                """
                UPDATE eligibility_evidence_jobs
                SET status = 'running', attempt_count = ?, lease_owner = ?,
                    lease_expires_at = ?, lease_token = ?,
                    next_run_at = NULL, error_code = NULL,
                    updated_at = ?
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                """,
                (
                    attempt_number, worker_id, lease_iso, lease_token, current_iso,
                    TENANT_PLACEHOLDER, row["project_id"], row["job_id"],
                ),
            )
            connection.execute(
                """
                INSERT INTO eligibility_evidence_job_attempts(
                    tenant_id, project_id, job_id, attempt_number, worker_id,
                    lease_token, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER, row["project_id"], row["job_id"],
                    attempt_number, worker_id, lease_token, current_iso,
                ),
            )
            claimed = connection.execute(
                "SELECT * FROM eligibility_evidence_jobs WHERE tenant_id = ? AND project_id = ? AND job_id = ?",
                (TENANT_PLACEHOLDER, row["project_id"], row["job_id"]),
            ).fetchone()
            connection.commit()
            return self._eligibility_evidence_job_payload(claimed)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def start_eligibility_vlm_provider_attempt(
        self,
        project_id: str,
        job_id: str,
        *,
        worker_id: str,
        attempt_number: int,
        lease_token: str,
        now: Optional[datetime] = None,
    ) -> int:
        current_iso = (now or _utc_now()).isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE eligibility_evidence_jobs
                SET provider_attempt_count = provider_attempt_count + 1,
                    updated_at = ?
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                  AND job_kind = 'vlm' AND status = 'running'
                  AND lease_owner = ? AND attempt_count = ? AND lease_token = ?
                  AND lease_expires_at > ?
                  AND provider_attempt_count < max_attempts
                """,
                (
                    current_iso,
                    TENANT_PLACEHOLDER,
                    project_id,
                    job_id,
                    worker_id,
                    attempt_number,
                    lease_token,
                    current_iso,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleRuntimeStateError(
                    "VLM provider attempt cannot start for stale or exhausted job"
                )
            count = connection.execute(
                """
                SELECT provider_attempt_count FROM eligibility_evidence_jobs
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                """,
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()[0]
            connection.commit()
            return int(count)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def defer_eligibility_vlm_job_for_circuit(
        self,
        project_id: str,
        job_id: str,
        *,
        worker_id: str,
        attempt_number: int,
        lease_token: str,
        retry_at: datetime,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        current = now or _utc_now()
        if retry_at <= current:
            raise ValueError("VLM circuit retry time must be in the future")
        current_iso = current.isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            attempt = connection.execute(
                """
                UPDATE eligibility_evidence_job_attempts
                SET finished_at = ?, outcome = 'retry_wait',
                    error_code = 'vlm_circuit_open'
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                  AND attempt_number = ? AND worker_id = ?
                  AND lease_token = ? AND finished_at IS NULL
                """,
                (
                    current_iso,
                    TENANT_PLACEHOLDER,
                    project_id,
                    job_id,
                    attempt_number,
                    worker_id,
                    lease_token,
                ),
            )
            if attempt.rowcount != 1:
                raise StaleRuntimeStateError("VLM circuit defer attempt is stale")
            job = connection.execute(
                """
                UPDATE eligibility_evidence_jobs
                SET status = 'retry_wait', lease_owner = NULL,
                    lease_expires_at = NULL, lease_token = NULL,
                    next_run_at = ?, error_code = 'vlm_circuit_open',
                    updated_at = ?, completed_at = NULL
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                  AND job_kind = 'vlm' AND status = 'running'
                  AND lease_owner = ? AND attempt_count = ? AND lease_token = ?
                  AND lease_expires_at > ?
                """,
                (
                    retry_at.isoformat(),
                    current_iso,
                    TENANT_PLACEHOLDER,
                    project_id,
                    job_id,
                    worker_id,
                    attempt_number,
                    lease_token,
                    current_iso,
                ),
            )
            if job.rowcount != 1:
                raise StaleRuntimeStateError("VLM circuit defer lease is stale")
            updated = connection.execute(
                """
                SELECT * FROM eligibility_evidence_jobs
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                """,
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()
            connection.commit()
            return self._eligibility_evidence_job_payload(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def heartbeat_eligibility_evidence_job(
        self,
        project_id: str,
        job_id: str,
        *,
        worker_id: str,
        progress_current: int,
        progress_total: int,
        lease_token: Optional[str] = None,
        now: Optional[datetime] = None,
        lease_seconds: int = 300,
    ) -> Dict[str, Any]:
        current = now or _utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE eligibility_evidence_jobs
                SET lease_expires_at = ?, progress_current = ?, progress_total = ?, updated_at = ?
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                  AND status = 'running' AND lease_owner = ?
                  AND lease_expires_at > ?
                  AND (? IS NULL OR lease_token = ?)
                """,
                (
                    (current + timedelta(seconds=lease_seconds)).isoformat(),
                    progress_current, progress_total, current.isoformat(),
                    TENANT_PLACEHOLDER, project_id, job_id, worker_id,
                    current.isoformat(), lease_token, lease_token,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleRuntimeStateError("eligibility evidence job lease is stale")
            row = connection.execute(
                "SELECT * FROM eligibility_evidence_jobs WHERE tenant_id = ? AND project_id = ? AND job_id = ?",
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()
            connection.commit()
            return self._eligibility_evidence_job_payload(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _finish_eligibility_evidence_job(
        self,
        project_id: str,
        job_id: str,
        *,
        worker_id: str,
        status: str,
        error_code: Optional[str],
        retry_at: Optional[datetime],
        now: Optional[datetime],
        lease_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        current = now or _utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM eligibility_evidence_jobs WHERE tenant_id = ? AND project_id = ? AND job_id = ?",
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()
            if (
                row is None
                or row["status"] != "running"
                or row["lease_owner"] != worker_id
                or row["lease_expires_at"] is None
                or datetime.fromisoformat(str(row["lease_expires_at"])) <= current
                or (
                    lease_token is not None
                    and str(row["lease_token"] or "") != lease_token
                )
            ):
                raise StaleRuntimeStateError("eligibility evidence job worker does not own current lease")
            final_status = status
            next_run_at = None
            completed_at = current.isoformat()
            if status == "failed" and retry_at is not None and row["attempt_count"] < row["max_attempts"]:
                final_status = "retry_wait"
                next_run_at = retry_at.isoformat()
                completed_at = None
            cursor = connection.execute(
                """
                UPDATE eligibility_evidence_job_attempts
                SET finished_at = ?, outcome = ?, error_code = ?
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                  AND attempt_number = ? AND finished_at IS NULL
                """,
                (
                    current.isoformat(), final_status, error_code,
                    TENANT_PLACEHOLDER, project_id, job_id, row["attempt_count"],
                ),
            )
            connection.execute(
                """
                UPDATE eligibility_evidence_jobs
                SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                    lease_token = NULL, next_run_at = ?, error_code = ?,
                    updated_at = ?, completed_at = ?
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                  AND status = 'running' AND lease_owner = ?
                  AND lease_expires_at > ?
                  AND (? IS NULL OR lease_token = ?)
                """,
                (
                    final_status, next_run_at, error_code, current.isoformat(),
                    completed_at, TENANT_PLACEHOLDER, project_id, job_id,
                    worker_id, current.isoformat(), lease_token, lease_token,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleRuntimeStateError(
                    "eligibility evidence job lease changed during finalization"
                )
            updated = connection.execute(
                "SELECT * FROM eligibility_evidence_jobs WHERE tenant_id = ? AND project_id = ? AND job_id = ?",
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()
            connection.commit()
            return self._eligibility_evidence_job_payload(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete_eligibility_evidence_job(
        self, project_id: str, job_id: str, *, worker_id: str,
        lease_token: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        job = self.eligibility_evidence_job(project_id, job_id)
        if job is not None and job["job_kind"] == "pdf_page_render":
            raise ValueError(
                "PDF render jobs require atomic OCR child finalization"
            )
        if job is not None and job["job_kind"] == "vlm":
            raise ValueError("VLM jobs require atomic descriptor finalization")
        return self._finish_eligibility_evidence_job(
            project_id, job_id, worker_id=worker_id, status="succeeded",
            error_code=None, retry_at=None, now=now, lease_token=lease_token,
        )

    def _vlm_runtime_binding_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        job_id: str,
    ) -> Optional[sqlite3.Row]:
        return connection.execute(
            """
            SELECT j.*, b.artifact_id AS bound_artifact_id,
                   b.artifact_revision_token, b.governance_revision,
                   b.extraction_revision AS bound_extraction_revision,
                   a.storage_key, a.content_hash, a.size_bytes, a.media_type,
                   a.artifact_kind, g.data_class, g.authorization_state,
                   g.authorization_ref, g.retention_policy_id, g.legal_hold,
                   p.enabled AS profile_enabled,
                   p.profile_digest AS active_profile_digest
            FROM eligibility_evidence_jobs j
            JOIN eligibility_vlm_job_bindings b
              ON b.tenant_id = j.tenant_id
             AND b.project_id = j.project_id
             AND b.job_id = j.job_id
            JOIN eligibility_evidence_artifacts a
              ON a.tenant_id = b.tenant_id
             AND a.project_id = b.project_id
             AND a.artifact_id = b.artifact_id
             AND a.source_id = b.source_id
            JOIN eligibility_controlled_artifact_state g
              ON g.tenant_id = b.tenant_id
             AND g.project_id = b.project_id
             AND g.artifact_id = b.artifact_id
             AND g.artifact_revision_token = b.artifact_revision_token
             AND g.governance_revision = b.governance_revision
            JOIN eligibility_vlm_profile_state p
              ON p.tenant_id = b.tenant_id
             AND p.profile_version = b.profile_version
             AND p.profile_digest = b.profile_digest
            JOIN eligibility_source_revisions s
              ON s.tenant_id = j.tenant_id
             AND s.project_id = j.project_id
             AND s.subject_id = j.subject_id
             AND s.source_id = j.source_id
             AND b.source_id = j.source_id
             AND s.source_revision = j.source_revision
             AND s.subject_source_revision = j.subject_source_revision
             AND s.is_current = 1
            WHERE j.tenant_id = ? AND j.project_id = ? AND j.job_id = ?
              AND j.job_kind = 'vlm'
            """,
            (TENANT_PLACEHOLDER, project_id, job_id),
        ).fetchone()

    def eligibility_vlm_inference_input(
        self,
        project_id: str,
        job_id: str,
        *,
        worker_id: str,
        profile_digest: str,
        attempt_number: int,
        lease_token: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        current = now or _utc_now()
        with self._connect() as connection:
            row = self._vlm_runtime_binding_row(connection, project_id, job_id)
        if (
            row is None
            or row["status"] != "running"
            or row["lease_owner"] != worker_id
            or row["attempt_count"] != attempt_number
            or row["lease_token"] != lease_token
            or row["lease_expires_at"] <= current.isoformat()
        ):
            raise StaleRuntimeStateError("VLM job lease or binding is stale")
        if (
            row["profile_digest"] != profile_digest
            or row["active_profile_digest"] != profile_digest
            or not row["profile_enabled"]
        ):
            raise RuntimeStoreIntegrityError("VLM profile binding is not active")
        if row["authorization_state"] != "authorized" or row["legal_hold"]:
            raise RuntimeStoreIntegrityError("VLM artifact is not authorized")
        return {
            key: row[key]
            for key in (
                "project_id", "subject_id", "job_id", "source_id",
                "source_revision", "subject_source_revision", "profile_version",
                "profile_digest", "bound_artifact_id", "artifact_revision_token",
                "governance_revision", "bound_extraction_revision", "storage_key",
                "content_hash", "size_bytes", "media_type", "artifact_kind",
                "data_class", "authorization_ref", "retention_policy_id",
                "attempt_count",
            )
        }

    def finalize_eligibility_vlm_job(
        self,
        project_id: str,
        job_id: str,
        *,
        worker_id: str,
        descriptor: Dict[str, Any],
        outcome: str,
        profile_digest: str,
        normalized_width: int,
        normalized_height: int,
        duration_ms: float,
        attempt_number: int,
        lease_token: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        from packages.contracts.workbench_contracts.models import EligibilityVlmDescriptor

        parsed = EligibilityVlmDescriptor.model_validate(descriptor)
        if outcome not in {"descriptor_valid", "manual_review_required"}:
            raise ValueError("VLM descriptor outcome is invalid")
        if min(normalized_width, normalized_height) < 1 or duration_ms < 0:
            raise ValueError("VLM descriptor technical metadata is invalid")
        current = now or _utc_now()
        current_iso = current.isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._vlm_runtime_binding_row(connection, project_id, job_id)
            if (
                row is None
                or row["status"] != "running"
                or row["lease_owner"] != worker_id
                or row["attempt_count"] != attempt_number
                or row["lease_token"] != lease_token
                or row["lease_expires_at"] <= current_iso
            ):
                raise StaleRuntimeStateError("VLM job lease or binding is stale")
            if (
                row["profile_digest"] != profile_digest
                or row["active_profile_digest"] != profile_digest
                or not row["profile_enabled"]
                or row["authorization_state"] != "authorized"
                or row["legal_hold"]
            ):
                raise RuntimeStoreIntegrityError("VLM runtime governance changed")
            descriptor_payload = parsed.model_dump(mode="json")
            descriptor_record_id = "vlmdesc_" + _payload_hash(
                {
                    "project_id": project_id,
                    "job_id": job_id,
                    "attempt_number": row["attempt_count"],
                    "profile_digest": profile_digest,
                    "descriptor": descriptor_payload,
                }
            )[:24]
            audit_event_id = "vlmaudit_" + _payload_hash(
                {
                    "project_id": project_id,
                    "job_id": job_id,
                    "attempt_number": row["attempt_count"],
                    "event_type": "vlm_descriptor_committed",
                }
            )[:24]
            connection.execute(
                """
                INSERT INTO eligibility_vlm_descriptor_records(
                    tenant_id, project_id, subject_id, job_id,
                    descriptor_record_id, attempt_number, schema_version,
                    media_class, primary_document_type, capture_quality_overall,
                    capture_quality_flags_json, orientation, human_attention_json,
                    gateway_outcome, profile_version, profile_digest,
                    artifact_id, artifact_revision_token, governance_revision,
                    normalized_width, normalized_height, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER, project_id, row["subject_id"], job_id,
                    descriptor_record_id, row["attempt_count"],
                    descriptor_payload["schema_version"],
                    descriptor_payload["media_class"],
                    descriptor_payload["primary_document_type"],
                    descriptor_payload["capture_quality"]["overall"],
                    _canonical_json(descriptor_payload["capture_quality"]["flags"]),
                    descriptor_payload["orientation"],
                    _canonical_json(descriptor_payload["requires_human_attention"]),
                    outcome, row["profile_version"], profile_digest,
                    row["bound_artifact_id"], row["artifact_revision_token"],
                    row["governance_revision"], normalized_width,
                    normalized_height, float(duration_ms), current_iso,
                ),
            )
            self._inject("eligibility_vlm_after_descriptor")
            connection.execute(
                """
                INSERT INTO eligibility_vlm_current_state(
                    tenant_id, project_id, subject_id, job_id, state_revision,
                    descriptor_record_id, effective_outcome,
                    visual_qc_status, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, 'not_reviewed', ?)
                """,
                (
                    TENANT_PLACEHOLDER, project_id, row["subject_id"], job_id,
                    descriptor_record_id, outcome, current_iso,
                ),
            )
            self._inject("eligibility_vlm_after_state")
            connection.execute(
                """
                INSERT INTO eligibility_vlm_audit_events(
                    tenant_id, project_id, subject_id, job_id, audit_event_id,
                    attempt_number, event_type, gateway_outcome, error_code,
                    data_class, profile_version, profile_digest, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'vlm_descriptor_committed', ?, NULL, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER, project_id, row["subject_id"], job_id,
                    audit_event_id, row["attempt_count"], outcome,
                    row["data_class"], row["profile_version"], profile_digest,
                    current_iso,
                ),
            )
            self._inject("eligibility_vlm_after_audit")
            attempt = connection.execute(
                """
                UPDATE eligibility_evidence_job_attempts
                SET finished_at = ?, outcome = 'succeeded', error_code = NULL
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                  AND attempt_number = ? AND worker_id = ?
                  AND lease_token = ? AND finished_at IS NULL
                """,
                (
                    current_iso, TENANT_PLACEHOLDER, project_id, job_id,
                    attempt_number, worker_id, lease_token,
                ),
            )
            if attempt.rowcount != 1:
                raise StaleRuntimeStateError("VLM attempt is no longer current")
            job_cursor = connection.execute(
                """
                UPDATE eligibility_evidence_jobs
                SET status = 'succeeded', lease_owner = NULL,
                    lease_expires_at = NULL, lease_token = NULL, next_run_at = NULL,
                    error_code = NULL, progress_current = 1,
                    progress_total = 1, updated_at = ?, completed_at = ?
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                  AND status = 'running' AND lease_owner = ?
                  AND attempt_count = ? AND lease_token = ?
                  AND lease_expires_at > ?
                """,
                (
                    current_iso, current_iso, TENANT_PLACEHOLDER, project_id,
                    job_id, worker_id, attempt_number, lease_token, current_iso,
                ),
            )
            if job_cursor.rowcount != 1:
                raise StaleRuntimeStateError("VLM job lease expired during finalize")
            completed = connection.execute(
                """
                SELECT * FROM eligibility_evidence_jobs
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                """,
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()
            connection.commit()
            return self._eligibility_evidence_job_payload(completed)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreIntegrityError(
                "VLM descriptor finalization conflicts with current state"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fail_eligibility_vlm_job(
        self,
        project_id: str,
        job_id: str,
        *,
        worker_id: str,
        gateway_outcome: str,
        error_code: str,
        attempt_number: int,
        lease_token: str,
        retry_at: Optional[datetime] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if gateway_outcome not in {"rejected", "runtime_failed"}:
            raise ValueError("VLM failure outcome is invalid")
        if not error_code:
            raise ValueError("VLM failure error code is required")
        current = now or _utc_now()
        current_iso = current.isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT j.*, b.profile_digest AS bound_profile_digest,
                       r.data_class
                FROM eligibility_evidence_jobs j
                JOIN eligibility_vlm_job_bindings b
                  ON b.tenant_id = j.tenant_id
                 AND b.project_id = j.project_id
                 AND b.job_id = j.job_id
                JOIN eligibility_controlled_artifact_records r
                  ON r.tenant_id = b.tenant_id
                 AND r.project_id = b.project_id
                 AND r.artifact_id = b.artifact_id
                 AND r.artifact_revision_token = b.artifact_revision_token
                 AND r.governance_revision = b.governance_revision
                WHERE j.tenant_id = ? AND j.project_id = ? AND j.job_id = ?
                  AND j.job_kind = 'vlm'
                """,
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()
            if (
                row is None
                or row["status"] != "running"
                or row["lease_owner"] != worker_id
                or row["attempt_count"] != attempt_number
                or row["lease_token"] != lease_token
                or row["lease_expires_at"] <= current_iso
            ):
                raise StaleRuntimeStateError("VLM failure lease is stale")
            final_status = "failed"
            next_run_at = None
            completed_at = current_iso
            if (
                retry_at is not None
                and row["provider_attempt_count"] < row["max_attempts"]
            ):
                final_status = "retry_wait"
                next_run_at = retry_at.isoformat()
                completed_at = None
            audit_event_id = "vlmaudit_" + _payload_hash(
                {
                    "project_id": project_id,
                    "job_id": job_id,
                    "attempt_number": row["attempt_count"],
                    "event_type": "vlm_attempt_failed",
                    "gateway_outcome": gateway_outcome,
                    "error_code": error_code,
                }
            )[:24]
            connection.execute(
                """
                INSERT INTO eligibility_vlm_audit_events(
                    tenant_id, project_id, subject_id, job_id, audit_event_id,
                    attempt_number, event_type, gateway_outcome, error_code,
                    data_class, profile_version, profile_digest, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'vlm_attempt_failed', ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER, project_id, row["subject_id"], job_id,
                    audit_event_id, row["attempt_count"], gateway_outcome,
                    error_code, row["data_class"], row["profile_version"],
                    row["bound_profile_digest"], current_iso,
                ),
            )
            attempt = connection.execute(
                """
                UPDATE eligibility_evidence_job_attempts
                SET finished_at = ?, outcome = ?, error_code = ?
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                  AND attempt_number = ? AND worker_id = ?
                  AND lease_token = ? AND finished_at IS NULL
                """,
                (
                    current_iso, final_status, error_code,
                    TENANT_PLACEHOLDER, project_id, job_id,
                    attempt_number, worker_id, lease_token,
                ),
            )
            if attempt.rowcount != 1:
                raise StaleRuntimeStateError("VLM failure attempt is no longer current")
            job_cursor = connection.execute(
                """
                UPDATE eligibility_evidence_jobs
                SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                    lease_token = NULL, next_run_at = ?, error_code = ?,
                    updated_at = ?, completed_at = ?
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                  AND status = 'running' AND lease_owner = ?
                  AND attempt_count = ? AND lease_token = ?
                  AND lease_expires_at > ?
                """,
                (
                    final_status, next_run_at, error_code, current_iso,
                    completed_at, TENANT_PLACEHOLDER, project_id, job_id,
                    worker_id, attempt_number, lease_token, current_iso,
                ),
            )
            if job_cursor.rowcount != 1:
                raise StaleRuntimeStateError("VLM failure lease expired during finalize")
            updated = connection.execute(
                """
                SELECT * FROM eligibility_evidence_jobs
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                """,
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()
            connection.commit()
            return self._eligibility_evidence_job_payload(updated)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreIntegrityError(
                "VLM failure audit conflicts with current attempt"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def eligibility_vlm_descriptors(
        self, project_id: str, job_id: str
    ) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM eligibility_vlm_descriptor_records
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                ORDER BY created_at, descriptor_record_id
                """,
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchall()
        return [
            {
                "project_id": project_id,
                "job_id": row["job_id"],
                "descriptor_record_id": row["descriptor_record_id"],
                "attempt_number": row["attempt_number"],
                "descriptor": {
                    "schema_version": row["schema_version"],
                    "media_class": row["media_class"],
                    "primary_document_type": row["primary_document_type"],
                    "capture_quality": {
                        "overall": row["capture_quality_overall"],
                        "flags": json.loads(row["capture_quality_flags_json"]),
                    },
                    "orientation": row["orientation"],
                    "requires_human_attention": json.loads(row["human_attention_json"]),
                },
                "gateway_outcome": row["gateway_outcome"],
                "profile_version": row["profile_version"],
                "visual_qc_status": "not_reviewed",
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def eligibility_vlm_audit_events(
        self, project_id: str, job_id: str
    ) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT job_id, audit_event_id, attempt_number,
                       event_type, gateway_outcome, error_code, data_class,
                       profile_version, created_at
                FROM eligibility_vlm_audit_events
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                ORDER BY created_at, audit_event_id
                """,
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchall()
        return [{"project_id": project_id, **dict(row)} for row in rows]

    def finalize_pdf_render_with_ocr_children(
        self,
        project_id: str,
        job_id: str,
        *,
        worker_id: str,
        profile_versions: Iterable[str],
        lease_token: Optional[str] = None,
        child_priority: int = 0,
        child_max_attempts: int = 3,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        from .ocr_gateway import ocr_profile_digest

        profiles = tuple(dict.fromkeys(str(item) for item in profile_versions))
        if not profiles:
            raise ValueError("at least one OCR child profile is required")
        if child_max_attempts < 1:
            raise ValueError("child_max_attempts must be positive")
        profile_digests = {
            profile: ocr_profile_digest(profile) for profile in profiles
        }
        current = now or _utc_now()
        current_iso = current.isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            parent = connection.execute(
                """
                SELECT * FROM eligibility_evidence_jobs
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                """,
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()
            if (
                parent is None
                or parent["status"] != "running"
                or parent["lease_owner"] != worker_id
                or (
                    lease_token is not None
                    and str(parent["lease_token"] or "") != lease_token
                )
                or parent["job_kind"] != "pdf_page_render"
                or parent["profile_version"] != "pdf-render-200dpi-v1"
            ):
                raise StaleRuntimeStateError(
                    "PDF render worker does not own the current parent lease"
                )
            try:
                lease_expires_at = datetime.fromisoformat(parent["lease_expires_at"])
            except (TypeError, ValueError):
                raise StaleRuntimeStateError("PDF render parent lease is invalid") from None
            if lease_expires_at <= current:
                raise StaleRuntimeStateError("PDF render parent lease has expired")
            progress_total = int(parent["progress_total"])
            if progress_total < 1 or int(parent["progress_current"]) != progress_total:
                raise RuntimeStoreIntegrityError(
                    "PDF render parent progress is incomplete"
                )
            artifact_rows = connection.execute(
                """
                SELECT * FROM eligibility_evidence_artifacts
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                ORDER BY artifact_id
                """,
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchall()
            page_artifacts: Dict[int, sqlite3.Row] = {}
            for artifact in artifact_rows:
                try:
                    locator = json.loads(artifact["locator_json"])
                    page_index = int(locator["page"])
                    content_hash = str(artifact["content_hash"])
                    valid_hash = (
                        len(content_hash) == 64
                        and len(bytes.fromhex(content_hash)) == 32
                    )
                except (KeyError, TypeError, ValueError):
                    raise RuntimeStoreIntegrityError(
                        "PDF render page artifact metadata is invalid"
                    ) from None
                if (
                    page_index in page_artifacts
                    or artifact["subject_id"] != parent["subject_id"]
                    or artifact["source_id"] != parent["source_id"]
                    or artifact["source_revision"] != parent["source_revision"]
                    or artifact["artifact_kind"] != "pdf_page_image"
                    or artifact["media_type"] != "image/png"
                    or not valid_hash
                ):
                    raise RuntimeStoreIntegrityError(
                        "PDF render page artifacts are inconsistent"
                    )
                page_artifacts[page_index] = artifact
            expected_pages = set(range(1, progress_total + 1))
            if set(page_artifacts) != expected_pages:
                raise RuntimeStoreIntegrityError(
                    "PDF render page artifacts do not cover progress_total"
                )

            created_at = current_iso
            child_rows = []
            for profile_version in profiles:
                profile_digest = profile_digests[profile_version]
                for page_index in range(1, progress_total + 1):
                    artifact = page_artifacts[page_index]
                    cache_payload = {
                        "project_id": project_id,
                        "subject_id": parent["subject_id"],
                        "source_id": parent["source_id"],
                        "source_revision": parent["source_revision"],
                        "subject_source_revision": parent["subject_source_revision"],
                        "parent_job_id": job_id,
                        "input_artifact_hash": artifact["content_hash"],
                        "page_index": page_index,
                        "job_kind": "ocr",
                        "profile_version": profile_version,
                        "profile_digest": profile_digest,
                    }
                    cache_digest = _payload_hash(
                        {"contract": "eligibility-pdf-page-ocr-cache-v2", **cache_payload}
                    )
                    job_digest = _payload_hash(
                        {"contract": "eligibility-pdf-page-ocr-job-v2", **cache_payload}
                    )
                    child_job_id = f"eligjob_{job_digest[:20]}"
                    cache_key = f"eligcache_{cache_digest[:32]}"
                    idempotency_key = (
                        f"atomic:{job_id}:{page_index}:{profile_version}:{profile_digest[:16]}"
                    )
                    request_hash = _payload_hash(
                        {
                            **cache_payload,
                            "input_artifact_id": artifact["artifact_id"],
                            "priority": child_priority,
                            "max_attempts": child_max_attempts,
                        }
                    )
                    request_id = f"req_{uuid4().hex}"
                    connection.execute(
                        """
                        INSERT INTO eligibility_evidence_jobs(
                            tenant_id, project_id, subject_id, job_id, job_kind,
                            profile_version, source_id, source_revision,
                            subject_source_revision, cache_key, status, priority,
                            attempt_count, max_attempts, progress_current,
                            progress_total, idempotency_key, request_hash,
                            request_id, created_at, updated_at, parent_job_id,
                            input_artifact_id, page_index, profile_digest
                        ) VALUES (
                            ?, ?, ?, ?, 'ocr', ?, ?, ?, ?, ?, 'queued', ?,
                            0, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            TENANT_PLACEHOLDER, project_id, parent["subject_id"],
                            child_job_id, profile_version, parent["source_id"],
                            parent["source_revision"], parent["subject_source_revision"],
                            cache_key, child_priority, child_max_attempts,
                            idempotency_key, request_hash, request_id, created_at,
                            created_at, job_id, artifact["artifact_id"], page_index,
                            profile_digest,
                        ),
                    )
                    child_rows.append(child_job_id)

            self._inject("eligibility_pdf_render_after_children_insert")
            attempt_cursor = connection.execute(
                """
                UPDATE eligibility_evidence_job_attempts
                SET finished_at = ?, outcome = 'succeeded', error_code = NULL
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                  AND attempt_number = ? AND worker_id = ? AND finished_at IS NULL
                """,
                (
                    current_iso, TENANT_PLACEHOLDER, project_id, job_id,
                    parent["attempt_count"], worker_id,
                ),
            )
            if attempt_cursor.rowcount != 1:
                raise StaleRuntimeStateError("PDF render attempt is no longer current")
            parent_cursor = connection.execute(
                """
                UPDATE eligibility_evidence_jobs
                SET status = 'succeeded', lease_owner = NULL,
                    lease_expires_at = NULL, lease_token = NULL,
                    next_run_at = NULL, error_code = NULL,
                    updated_at = ?, completed_at = ?
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                  AND status = 'running' AND lease_owner = ?
                  AND lease_expires_at > ?
                  AND (? IS NULL OR lease_token = ?)
                """,
                (
                    current_iso, current_iso, TENANT_PLACEHOLDER, project_id,
                    job_id, worker_id, current_iso, lease_token, lease_token,
                ),
            )
            if parent_cursor.rowcount != 1:
                raise StaleRuntimeStateError("PDF render parent lease expired during finalize")
            finalized_parent = connection.execute(
                """
                SELECT * FROM eligibility_evidence_jobs
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                """,
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()
            children = connection.execute(
                f"""
                SELECT * FROM eligibility_evidence_jobs
                WHERE tenant_id = ? AND project_id = ?
                  AND job_id IN ({','.join('?' for _ in child_rows)})
                ORDER BY profile_version, page_index, job_id
                """,
                (TENANT_PLACEHOLDER, project_id, *child_rows),
            ).fetchall()
            connection.commit()
            return {
                "parent": self._eligibility_evidence_job_payload(finalized_parent),
                "children": [
                    self._eligibility_evidence_job_payload(row) for row in children
                ],
            }
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreIntegrityError(
                "PDF render atomic child batch conflicts with existing state"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def eligibility_pdf_render_ocr_children(
        self,
        project_id: str,
        parent_job_id: str,
        *,
        profile_versions: Iterable[str] = (),
    ) -> List[Dict[str, Any]]:
        profiles = tuple(dict.fromkeys(str(item) for item in profile_versions))
        filters = [
            "tenant_id = ?", "project_id = ?", "parent_job_id = ?",
            "job_kind = 'ocr'",
        ]
        params: List[Any] = [TENANT_PLACEHOLDER, project_id, parent_job_id]
        if profiles:
            filters.append(f"profile_version IN ({','.join('?' for _ in profiles)})")
            params.extend(profiles)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM eligibility_evidence_jobs
                WHERE {' AND '.join(filters)}
                ORDER BY profile_version, page_index, job_id
                """,
                tuple(params),
            ).fetchall()
        return [self._eligibility_evidence_job_payload(row) for row in rows]

    def fail_eligibility_evidence_job(
        self, project_id: str, job_id: str, *, worker_id: str,
        error_code: str, retry_at: Optional[datetime] = None,
        lease_token: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        return self._finish_eligibility_evidence_job(
            project_id, job_id, worker_id=worker_id, status="failed",
            error_code=error_code, retry_at=retry_at, now=now,
            lease_token=lease_token,
        )

    def cancel_eligibility_evidence_job(
        self, project_id: str, job_id: str, *, actor: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if not actor:
            raise ValueError("actor is required")
        current = now or _utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM eligibility_evidence_jobs WHERE tenant_id = ? AND project_id = ? AND job_id = ?",
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()
            if row is None or row["status"] not in {"queued", "running", "retry_wait"}:
                raise StaleRuntimeStateError("eligibility evidence job cannot be cancelled")
            if row["status"] == "running":
                connection.execute(
                    """
                    UPDATE eligibility_evidence_job_attempts
                    SET finished_at = ?, outcome = 'cancelled', error_code = 'cancelled_by_user'
                    WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                      AND attempt_number = ? AND finished_at IS NULL
                    """,
                    (
                        current.isoformat(), TENANT_PLACEHOLDER, project_id,
                        job_id, row["attempt_count"],
                    ),
                )
            connection.execute(
                """
                UPDATE eligibility_evidence_jobs
                SET status = 'cancelled', lease_owner = NULL, lease_expires_at = NULL,
                    lease_token = NULL, next_run_at = NULL,
                    error_code = 'cancelled_by_user',
                    updated_at = ?, completed_at = ?
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                """,
                (
                    current.isoformat(), current.isoformat(), TENANT_PLACEHOLDER,
                    project_id, job_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM eligibility_evidence_jobs WHERE tenant_id = ? AND project_id = ? AND job_id = ?",
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchone()
            connection.commit()
            return self._eligibility_evidence_job_payload(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def add_eligibility_evidence_artifact(self, artifact: Dict[str, Any]) -> None:
        required = {
            "project_id", "subject_id", "job_id", "artifact_id",
            "artifact_kind", "storage_key", "content_hash", "size_bytes",
            "media_type", "source_id", "source_revision",
            "extraction_revision", "locator", "quality_state",
        }
        missing = sorted(required.difference(artifact))
        if missing:
            raise ValueError(f"eligibility evidence artifact missing fields: {missing}")
        storage_key = str(artifact["storage_key"])
        if Path(storage_key).is_absolute() or ".." in Path(storage_key).parts:
            raise ValueError("eligibility evidence artifact storage_key must be relative")
        values = (
            TENANT_PLACEHOLDER, str(artifact["project_id"]),
            str(artifact["subject_id"]), str(artifact["job_id"]),
            str(artifact["artifact_id"]), str(artifact["artifact_kind"]),
            storage_key, str(artifact["content_hash"]), int(artifact["size_bytes"]),
            str(artifact["media_type"]), str(artifact["source_id"]),
            str(artifact["source_revision"]), str(artifact["extraction_revision"]),
            _canonical_json(artifact["locator"]), str(artifact["quality_state"]),
            str(artifact.get("created_at") or _utc_now().isoformat()),
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM eligibility_evidence_artifacts WHERE tenant_id = ? AND project_id = ? AND artifact_id = ?",
                (TENANT_PLACEHOLDER, artifact["project_id"], artifact["artifact_id"]),
            ).fetchone()
            if existing is not None:
                existing_values = tuple(existing[key] for key in (
                    "tenant_id", "project_id", "subject_id", "job_id",
                    "artifact_id", "artifact_kind", "storage_key", "content_hash",
                    "size_bytes", "media_type", "source_id", "source_revision",
                    "extraction_revision", "locator_json", "quality_state", "created_at",
                ))
                comparable_existing = existing_values if artifact.get("created_at") else existing_values[:-1]
                comparable_values = values if artifact.get("created_at") else values[:-1]
                if comparable_existing != comparable_values:
                    raise ValueError("eligibility evidence artifact is immutable")
                connection.rollback()
                return
            connection.execute(
                """
                INSERT INTO eligibility_evidence_artifacts(
                    tenant_id, project_id, subject_id, job_id, artifact_id,
                    artifact_kind, storage_key, content_hash, size_bytes,
                    media_type, source_id, source_revision, extraction_revision,
                    locator_json, quality_state, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def eligibility_evidence_artifacts(self, project_id: str, job_id: str) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT subject_id, job_id, artifact_id, artifact_kind,
                       storage_key, content_hash, size_bytes, media_type,
                       source_id, source_revision, extraction_revision,
                       locator_json, quality_state, created_at
                FROM eligibility_evidence_artifacts
                WHERE tenant_id = ? AND project_id = ? AND job_id = ?
                ORDER BY created_at, artifact_id
                """,
                (TENANT_PLACEHOLDER, project_id, job_id),
            ).fetchall()
        return [
            {
                "project_id": project_id,
                **{key: row[key] for key in (
                    "subject_id", "job_id", "artifact_id", "artifact_kind",
                    "storage_key", "content_hash", "size_bytes", "media_type",
                    "source_id", "source_revision", "extraction_revision",
                    "quality_state", "created_at",
                )},
                "locator": json.loads(row["locator_json"]),
            }
            for row in rows
        ]

    def eligibility_evidence_artifact(
        self, project_id: str, artifact_id: str
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT subject_id, job_id, artifact_id, artifact_kind,
                       storage_key, content_hash, size_bytes, media_type,
                       source_id, source_revision, extraction_revision,
                       locator_json, quality_state, created_at
                FROM eligibility_evidence_artifacts
                WHERE tenant_id = ? AND project_id = ? AND artifact_id = ?
                """,
                (TENANT_PLACEHOLDER, project_id, artifact_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "project_id": project_id,
            **{key: row[key] for key in (
                "subject_id", "job_id", "artifact_id", "artifact_kind",
                "storage_key", "content_hash", "size_bytes", "media_type",
                "source_id", "source_revision", "extraction_revision",
                "quality_state", "created_at",
            )},
            "locator": json.loads(row["locator_json"]),
        }

    def add_eligibility_evidence_span(self, span: Dict[str, Any]) -> None:
        required = {
            "project_id", "subject_id", "evidence_id", "source_id",
            "source_revision", "extraction_revision", "locator",
            "media_class", "processing_state", "quality_state",
            "medical_verification_status",
        }
        missing = sorted(required.difference(span))
        if missing:
            raise ValueError(f"eligibility evidence span missing fields: {missing}")
        values = (
            TENANT_PLACEHOLDER,
            span["project_id"],
            span["subject_id"],
            span["evidence_id"],
            span["source_id"],
            span["source_revision"],
            span["extraction_revision"],
            _canonical_json(span["locator"]),
            _canonical_json(span.get("metadata") or {}),
            span["media_class"],
            span["processing_state"],
            span["quality_state"],
            span.get("extraction_confidence"),
            span["medical_verification_status"],
            str(span.get("created_at") or _utc_now().isoformat()),
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM eligibility_evidence_spans
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND evidence_id = ? AND source_revision = ?
                """,
                (
                    TENANT_PLACEHOLDER, span["project_id"], span["subject_id"],
                    span["evidence_id"], span["source_revision"],
                ),
            ).fetchone()
            if existing is not None:
                existing_values = tuple(existing[key] for key in (
                    "tenant_id", "project_id", "subject_id", "evidence_id",
                    "source_id", "source_revision", "extraction_revision",
                    "locator_json", "metadata_json", "media_class",
                    "processing_state", "quality_state", "extraction_confidence",
                    "medical_verification_status", "created_at",
                ))
                comparable_existing = existing_values if span.get("created_at") else existing_values[:-1]
                comparable_values = values if span.get("created_at") else values[:-1]
                if comparable_existing != comparable_values:
                    raise ValueError(
                        "eligibility evidence span is immutable; use a new evidence_id"
                    )
                connection.rollback()
                return
            connection.execute(
                """
                INSERT INTO eligibility_evidence_spans(
                    tenant_id, project_id, subject_id, evidence_id, source_id,
                    source_revision, extraction_revision, locator_json,
                    metadata_json, media_class, processing_state, quality_state,
                    extraction_confidence, medical_verification_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _visual_qc_sample_unit(value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, dict) or not value:
            raise ValueError("sample_unit must be a non-empty object")
        return _canonical_json(value)

    def commit_eligibility_evidence_visual_qc(
        self,
        *,
        project_id: str,
        subject_id: str,
        evidence_id: str,
        expected_qc_revision: int,
        expected_source_revision: str,
        expected_extraction_revision: str,
        idempotency_key: str,
        result: str,
        reason_code: str,
        user_reason: str,
        sample_plan_id: Optional[str],
        sample_unit: Optional[Dict[str, Any]],
        policy_version: str,
        actor: str,
    ) -> EligibilityVisualQcCommitResult:
        allowed_results = {
            "sampled_pass", "sampled_fail", "manual_review_required"
        }
        if result not in allowed_results:
            raise ValueError("unsupported eligibility visual QC result")
        if expected_qc_revision < 0:
            raise ValueError("expected_qc_revision must be non-negative")
        required_text = {
            "project_id": project_id,
            "subject_id": subject_id,
            "evidence_id": evidence_id,
            "expected_source_revision": expected_source_revision,
            "expected_extraction_revision": expected_extraction_revision,
            "idempotency_key": idempotency_key,
            "reason_code": reason_code,
            "user_reason": user_reason,
            "policy_version": policy_version,
            "actor": actor,
        }
        if any(not str(value).strip() for value in required_text.values()):
            raise ValueError("eligibility visual QC identity and reasons are required")
        sample_unit_json = self._visual_qc_sample_unit(sample_unit)
        normalized_sample_plan_id = str(sample_plan_id or "").strip() or None
        if result in {"sampled_pass", "sampled_fail"}:
            if normalized_sample_plan_id is None or sample_unit_json is None:
                raise ValueError(
                    "sampled visual QC requires sample_plan_id and sample_unit"
                )

        operation = f"eligibility_visual_qc:{subject_id}:{evidence_id}"
        request_payload = {
            "subject_id": subject_id,
            "evidence_id": evidence_id,
            "expected_qc_revision": expected_qc_revision,
            "expected_source_revision": expected_source_revision,
            "expected_extraction_revision": expected_extraction_revision,
            "result": result,
            "reason_code": reason_code.strip(),
            "user_reason": user_reason.strip(),
            "sample_plan_id": normalized_sample_plan_id,
            "sample_unit": sample_unit,
            "policy_version": policy_version.strip(),
            "actor": actor.strip(),
        }
        request_hash = _payload_hash(request_payload)
        request_id = f"req_{uuid4().hex}"
        qc_record_id = f"eligqc_{uuid4().hex}"
        created_at = _utc_now().isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay_request_id = self._idempotency_result(
                connection, project_id, operation, idempotency_key, request_hash
            )
            if replay_request_id is not None:
                replay = connection.execute(
                    """
                    SELECT qc_record_id, new_qc_revision, result
                    FROM eligibility_evidence_visual_qc_records
                    WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                      AND evidence_id = ? AND request_id = ?
                    """,
                    (
                        TENANT_PLACEHOLDER, project_id, subject_id,
                        evidence_id, replay_request_id,
                    ),
                ).fetchone()
                if replay is None:
                    raise RuntimeStoreIntegrityError(
                        "visual QC idempotency record has no QC record"
                    )
                connection.rollback()
                return EligibilityVisualQcCommitResult(
                    request_id=replay_request_id,
                    qc_record_id=str(replay["qc_record_id"]),
                    qc_revision=int(replay["new_qc_revision"]),
                    result=str(replay["result"]),
                    replayed=True,
                )

            span = connection.execute(
                """
                SELECT e.source_revision, e.extraction_revision, e.processing_state
                FROM eligibility_evidence_spans e
                JOIN eligibility_source_revisions s
                  ON s.tenant_id=e.tenant_id AND s.project_id=e.project_id
                 AND s.subject_id=e.subject_id AND s.source_id=e.source_id
                 AND s.source_revision=e.source_revision
                WHERE e.tenant_id = ? AND e.project_id = ? AND e.subject_id = ?
                  AND e.evidence_id = ? AND e.source_revision = ?
                  AND e.extraction_revision = ? AND s.is_current = 1
                LIMIT 1
                """,
                (
                    TENANT_PLACEHOLDER, project_id, subject_id, evidence_id,
                    expected_source_revision, expected_extraction_revision,
                ),
            ).fetchone()
            if span is None:
                raise StaleRuntimeStateError(
                    "eligibility evidence source or extraction revision is stale"
                )
            if str(span["processing_state"]) not in {"completed", "needs_visual_qc"}:
                raise ValueError("eligibility evidence is not in a visual-QC-able state")

            current = connection.execute(
                """
                SELECT qc_revision, effective_result
                FROM eligibility_evidence_visual_qc_state
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND evidence_id = ? AND source_revision = ?
                  AND extraction_revision = ?
                """,
                (
                    TENANT_PLACEHOLDER, project_id, subject_id, evidence_id,
                    expected_source_revision, expected_extraction_revision,
                ),
            ).fetchone()
            actual_revision = int(current["qc_revision"]) if current else 0
            if actual_revision != expected_qc_revision:
                raise StaleRuntimeStateError(
                    "stale eligibility visual QC state: "
                    f"expected={expected_qc_revision}, actual={actual_revision}"
                )
            new_revision = actual_revision + 1
            connection.execute(
                """
                INSERT INTO eligibility_evidence_visual_qc_records(
                    tenant_id, project_id, subject_id, evidence_id,
                    source_revision, extraction_revision, qc_record_id,
                    previous_qc_revision, new_qc_revision, result, reason_code,
                    user_reason, sample_plan_id, sample_unit_json, policy_version,
                    actor, identity_assurance, idempotency_key, request_hash,
                    request_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER, project_id, subject_id, evidence_id,
                    expected_source_revision, expected_extraction_revision,
                    qc_record_id, actual_revision, new_revision, result,
                    reason_code.strip(), user_reason.strip(), normalized_sample_plan_id,
                    sample_unit_json, policy_version.strip(), actor.strip(),
                    IDENTITY_ASSURANCE, idempotency_key, request_hash, request_id,
                    created_at,
                ),
            )
            self._inject("after_eligibility_visual_qc_record")
            connection.execute(
                """
                INSERT INTO eligibility_evidence_visual_qc_state(
                    tenant_id, project_id, subject_id, evidence_id,
                    source_revision, extraction_revision, qc_revision,
                    effective_result, latest_qc_record_id, reason_code,
                    user_reason, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    tenant_id, project_id, subject_id, evidence_id,
                    source_revision, extraction_revision
                ) DO UPDATE SET
                    qc_revision=excluded.qc_revision,
                    effective_result=excluded.effective_result,
                    latest_qc_record_id=excluded.latest_qc_record_id,
                    reason_code=excluded.reason_code,
                    user_reason=excluded.user_reason,
                    updated_at=excluded.updated_at
                """,
                (
                    TENANT_PLACEHOLDER, project_id, subject_id, evidence_id,
                    expected_source_revision, expected_extraction_revision,
                    new_revision, result, qc_record_id, reason_code.strip(),
                    user_reason.strip(), created_at,
                ),
            )
            self._inject("after_eligibility_visual_qc_state")
            self._append_runtime_audit(
                connection,
                project_id=project_id,
                event_type="eligibility_evidence_visual_qc_committed",
                operation=operation,
                actor=actor.strip(),
                detail={
                    "subject_id": subject_id,
                    "evidence_id": evidence_id,
                    "source_revision": expected_source_revision,
                    "extraction_revision": expected_extraction_revision,
                    "previous_qc_revision": actual_revision,
                    "new_qc_revision": new_revision,
                    "result": result,
                    "reason_code": reason_code.strip(),
                    "identity_assurance": IDENTITY_ASSURANCE,
                },
            )
            self._inject("after_eligibility_visual_qc_audit")
            self._insert_idempotency(
                connection, project_id, operation, idempotency_key,
                request_hash, request_id,
            )
            self._inject("after_eligibility_visual_qc_idempotency")
            connection.commit()
            return EligibilityVisualQcCommitResult(
                request_id=request_id,
                qc_record_id=qc_record_id,
                qc_revision=new_revision,
                result=result,
            )
        except StaleRuntimeStateError as exc:
            connection.rollback()
            self._record_rejection(
                project_id,
                event_type="eligibility_visual_qc_stale_write_rejected",
                operation=operation,
                actor=actor.strip(),
                detail={
                    "subject_id": subject_id,
                    "evidence_id": evidence_id,
                    "expected_qc_revision": expected_qc_revision,
                    "expected_source_revision": expected_source_revision,
                    "expected_extraction_revision": expected_extraction_revision,
                    "reason_code": "stale_runtime_state",
                },
            )
            raise exc
        except IdempotencyConflictError as exc:
            connection.rollback()
            self._record_rejection(
                project_id,
                event_type="eligibility_visual_qc_idempotency_conflict_rejected",
                operation=operation,
                actor=actor.strip(),
                detail={
                    "subject_id": subject_id,
                    "evidence_id": evidence_id,
                    "expected_source_revision": expected_source_revision,
                    "expected_extraction_revision": expected_extraction_revision,
                    "reason_code": "idempotency_conflict",
                },
            )
            raise exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _evidence_is_valid_for_decisive_review(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        subject_id: str,
        evidence_id: str,
        subject_source_revision: str,
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM eligibility_evidence_spans e
            JOIN eligibility_source_revisions s
              ON s.tenant_id=e.tenant_id AND s.project_id=e.project_id
             AND s.subject_id=e.subject_id AND s.source_id=e.source_id
             AND s.source_revision=e.source_revision
            JOIN eligibility_evidence_visual_qc_state q
              ON q.tenant_id=e.tenant_id AND q.project_id=e.project_id
             AND q.subject_id=e.subject_id AND q.evidence_id=e.evidence_id
             AND q.source_revision=e.source_revision
             AND q.extraction_revision=e.extraction_revision
            WHERE e.tenant_id = ? AND e.project_id = ? AND e.subject_id = ?
              AND e.evidence_id = ? AND s.subject_source_revision = ?
              AND s.is_current = 1
              AND e.processing_state IN ('completed', 'needs_visual_qc')
              AND q.effective_result = 'sampled_pass'
            LIMIT 1
            """,
            (
                TENANT_PLACEHOLDER, project_id, subject_id, evidence_id,
                subject_source_revision,
            ),
        ).fetchone()
        return row is not None

    def commit_eligibility_source_processing_unit(
        self,
        *,
        project_id: str,
        subject_id: str,
        source_id: str,
        source_revision: str,
        subject_source_revision: str,
        unit_index: int,
        expected_state_revision: int,
        processing_status: str,
        artifact_id: Optional[str],
        extraction_revision: Optional[str],
        evidence_ids: Iterable[str],
        reason_code: str,
        actor: str,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        allowed_statuses = {
            "evidence_extracted",
            "processed_no_relevant_evidence",
            "manual_review_required",
            "failed",
        }
        evidence_id_rows = tuple(str(item) for item in evidence_ids)
        if not all(
            (
                project_id,
                subject_id,
                source_id,
                source_revision,
                subject_source_revision,
                reason_code.strip(),
                actor.strip(),
                idempotency_key,
            )
        ):
            raise ValueError("eligibility source processing-unit identity is required")
        if unit_index < 1 or expected_state_revision < 0:
            raise ValueError("eligibility source processing-unit revision is invalid")
        if processing_status not in allowed_statuses:
            raise ValueError("eligibility source processing-unit status is invalid")
        if len(evidence_id_rows) != len(set(evidence_id_rows)):
            raise ValueError("eligibility source processing-unit evidence IDs must be unique")
        resolved = processing_status in {
            "evidence_extracted",
            "processed_no_relevant_evidence",
        }
        if processing_status == "evidence_extracted" and not evidence_id_rows:
            raise ValueError("evidence_extracted requires evidence IDs")
        if processing_status == "processed_no_relevant_evidence" and evidence_id_rows:
            raise ValueError("processed_no_relevant_evidence cannot reference evidence IDs")
        if resolved and (not artifact_id or not extraction_revision):
            raise ValueError("resolved processing unit requires a controlled artifact")

        operation = (
            f"eligibility_source_processing_unit:{subject_id}:"
            f"{source_id}:{source_revision}:{unit_index}"
        )
        request_payload = {
            "project_id": project_id,
            "subject_id": subject_id,
            "source_id": source_id,
            "source_revision": source_revision,
            "subject_source_revision": subject_source_revision,
            "unit_index": unit_index,
            "expected_state_revision": expected_state_revision,
            "processing_status": processing_status,
            "artifact_id": artifact_id,
            "extraction_revision": extraction_revision,
            "evidence_ids": list(evidence_id_rows),
            "reason_code": reason_code.strip(),
            "actor": actor.strip(),
        }
        request_hash = _payload_hash(request_payload)
        request_id = f"req_{uuid4().hex}"
        record_id = f"eligunitrec_{uuid4().hex}"
        created_at = _utc_now().isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay_request_id = self._idempotency_result(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_hash,
            )
            if replay_request_id is not None:
                replay = connection.execute(
                    """
                    SELECT new_state_revision, processing_status, record_id
                    FROM eligibility_source_processing_unit_records
                    WHERE tenant_id = ? AND project_id = ? AND request_id = ?
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        replay_request_id,
                    ),
                ).fetchone()
                if replay is None:
                    raise RuntimeStoreIntegrityError(
                        "processing-unit idempotency record is orphaned"
                    )
                connection.rollback()
                return {
                    "request_id": replay_request_id,
                    "record_id": str(replay["record_id"]),
                    "state_revision": int(replay["new_state_revision"]),
                    "processing_status": str(replay["processing_status"]),
                    "replayed": True,
                }

            source = connection.execute(
                """
                SELECT processing_unit_kind, expected_unit_count
                FROM eligibility_source_revisions
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND source_id = ? AND source_revision = ?
                  AND subject_source_revision = ? AND is_current = 1
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    source_id,
                    source_revision,
                    subject_source_revision,
                ),
            ).fetchone()
            if source is None:
                raise StaleRuntimeStateError(
                    "eligibility source processing unit is not current"
                )
            expected_unit_count = int(source["expected_unit_count"] or 0)
            unit_kind = str(source["processing_unit_kind"])
            if expected_unit_count < 1 or unit_index > expected_unit_count:
                raise StaleRuntimeStateError(
                    "eligibility source processing-unit contract is incomplete"
                )
            if unit_kind == "archive_container" and resolved:
                raise ValueError(
                    "archive container cannot be resolved before safe member extraction"
                )

            current = connection.execute(
                """
                SELECT state_revision
                FROM eligibility_source_processing_unit_state
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND subject_source_revision = ? AND source_id = ?
                  AND source_revision = ? AND unit_index = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    subject_source_revision,
                    source_id,
                    source_revision,
                    unit_index,
                ),
            ).fetchone()
            actual_revision = int(current["state_revision"]) if current else 0
            if actual_revision != expected_state_revision:
                raise StaleRuntimeStateError(
                    "stale eligibility source processing-unit state"
                )

            if resolved:
                artifact = connection.execute(
                    """
                    SELECT a.source_id, a.source_revision,
                           a.extraction_revision, a.locator_json,
                           a.quality_state, j.status AS job_status
                    FROM eligibility_evidence_artifacts a
                    JOIN eligibility_evidence_jobs j
                      ON j.tenant_id=a.tenant_id AND j.project_id=a.project_id
                     AND j.job_id=a.job_id
                    WHERE a.tenant_id = ? AND a.project_id = ?
                      AND a.subject_id = ? AND a.artifact_id = ?
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        subject_id,
                        artifact_id,
                    ),
                ).fetchone()
                if artifact is None or any(
                    str(artifact[key]) != expected
                    for key, expected in (
                        ("source_id", source_id),
                        ("source_revision", source_revision),
                        ("extraction_revision", str(extraction_revision)),
                    )
                ):
                    raise RuntimeStoreIntegrityError(
                        "processing unit controlled artifact is missing or stale"
                    )
                if (
                    processing_status == "processed_no_relevant_evidence"
                    and str(artifact["quality_state"]) != "sampled_pass"
                ):
                    raise StaleRuntimeStateError(
                        "processing unit without evidence has not passed quality control"
                    )
                if str(artifact["job_status"]) != "succeeded":
                    raise StaleRuntimeStateError(
                        "processing unit extraction job is not durably completed"
                    )
                locator = json.loads(str(artifact["locator_json"]))
                if unit_kind == "page" and (
                    not isinstance(locator, dict)
                    or int(locator.get("page") or 0) != unit_index
                ):
                    raise RuntimeStoreIntegrityError(
                        "processing unit artifact does not match the expected page"
                    )
                for evidence_id in evidence_id_rows:
                    if not self._evidence_is_valid_for_decisive_review(
                        connection,
                        project_id=project_id,
                        subject_id=subject_id,
                        evidence_id=evidence_id,
                        subject_source_revision=subject_source_revision,
                    ):
                        raise StaleRuntimeStateError(
                            "processing unit evidence is not current and QC-passed"
                        )
                    evidence = connection.execute(
                        """
                        SELECT source_id, source_revision, extraction_revision,
                               metadata_json
                        FROM eligibility_evidence_spans
                        WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                          AND evidence_id = ? AND source_revision = ?
                        """,
                        (
                            TENANT_PLACEHOLDER,
                            project_id,
                            subject_id,
                            evidence_id,
                            source_revision,
                        ),
                    ).fetchone()
                    if (
                        evidence is None
                        or str(evidence["source_id"]) != source_id
                        or str(evidence["extraction_revision"])
                        != str(extraction_revision)
                    ):
                        raise RuntimeStoreIntegrityError(
                            "processing unit evidence is not bound to its artifact"
                        )
                    metadata = json.loads(str(evidence["metadata_json"]))
                    if (
                        not isinstance(metadata, dict)
                        or str(metadata.get("artifact_id") or "") != artifact_id
                    ):
                        raise RuntimeStoreIntegrityError(
                            "processing unit evidence is not bound to its artifact"
                        )

            new_revision = actual_revision + 1
            connection.execute(
                """
                INSERT INTO eligibility_source_processing_unit_records(
                    tenant_id, project_id, subject_id, subject_source_revision,
                    source_id, source_revision, unit_index, record_id,
                    previous_state_revision,
                    new_state_revision, processing_status, artifact_id,
                    extraction_revision, evidence_ids_json, reason_code, actor,
                    identity_assurance, request_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    subject_source_revision,
                    source_id,
                    source_revision,
                    unit_index,
                    record_id,
                    actual_revision,
                    new_revision,
                    processing_status,
                    artifact_id,
                    extraction_revision,
                    _canonical_json(list(evidence_id_rows)),
                    reason_code.strip(),
                    actor.strip(),
                    IDENTITY_ASSURANCE,
                    request_id,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO eligibility_source_processing_unit_state(
                    tenant_id, project_id, subject_id, subject_source_revision,
                    source_id, source_revision, unit_index, state_revision,
                    processing_status, artifact_id, extraction_revision,
                    evidence_ids_json, latest_record_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    tenant_id, project_id, subject_id, subject_source_revision,
                    source_id, source_revision, unit_index
                ) DO UPDATE SET
                    state_revision=excluded.state_revision,
                    processing_status=excluded.processing_status,
                    artifact_id=excluded.artifact_id,
                    extraction_revision=excluded.extraction_revision,
                    evidence_ids_json=excluded.evidence_ids_json,
                    latest_record_id=excluded.latest_record_id,
                    updated_at=excluded.updated_at
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    subject_source_revision,
                    source_id,
                    source_revision,
                    unit_index,
                    new_revision,
                    processing_status,
                    artifact_id,
                    extraction_revision,
                    _canonical_json(list(evidence_id_rows)),
                    record_id,
                    created_at,
                ),
            )
            self._append_runtime_audit(
                connection,
                project_id=project_id,
                event_type="eligibility_source_processing_unit_committed",
                operation=operation,
                actor=actor.strip(),
                detail={
                    "subject_id": subject_id,
                    "source_id": source_id,
                    "source_revision": source_revision,
                    "unit_index": unit_index,
                    "previous_state_revision": actual_revision,
                    "new_state_revision": new_revision,
                    "processing_status": processing_status,
                    "artifact_id": artifact_id,
                    "extraction_revision": extraction_revision,
                    "evidence_ids": list(evidence_id_rows),
                    "reason_code": reason_code.strip(),
                    "identity_assurance": IDENTITY_ASSURANCE,
                },
            )
            self._insert_idempotency(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_hash,
                request_id,
            )
            connection.commit()
            return {
                "request_id": request_id,
                "record_id": record_id,
                "state_revision": new_revision,
                "processing_status": processing_status,
                "replayed": False,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def eligibility_source_processing_units(
        self,
        project_id: str,
        subject_id: str,
        subject_source_revision: str,
    ) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT u.source_id, u.source_revision, u.unit_index,
                       u.state_revision, u.processing_status, u.artifact_id,
                       u.extraction_revision, u.evidence_ids_json,
                       u.latest_record_id, u.updated_at
                FROM eligibility_source_processing_unit_state u
                JOIN eligibility_source_revisions s
                  ON s.tenant_id=u.tenant_id AND s.project_id=u.project_id
                 AND s.subject_id=u.subject_id AND s.source_id=u.source_id
                 AND s.source_revision=u.source_revision
                WHERE u.tenant_id = ? AND u.project_id = ? AND u.subject_id = ?
                  AND u.subject_source_revision = ?
                  AND s.subject_source_revision = u.subject_source_revision
                  AND s.is_current = 1
                ORDER BY u.source_id, u.unit_index
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    subject_source_revision,
                ),
            ).fetchall()
        return [
            {
                **dict(row),
                "evidence_ids": json.loads(str(row["evidence_ids_json"])),
            }
            for row in rows
        ]

    @staticmethod
    def _subject_evidence_processing_state(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        subject_id: str,
        subject_source_revision: str,
    ) -> str:
        source_rows = connection.execute(
            """
            SELECT source_id, source_revision, expected_unit_count
            FROM eligibility_source_revisions
            WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
              AND subject_source_revision = ? AND is_current = 1
            ORDER BY source_id, source_revision
            """,
            (
                TENANT_PLACEHOLDER,
                project_id,
                subject_id,
                subject_source_revision,
            ),
        ).fetchall()
        declared_unit_contract = any(
            int(row["expected_unit_count"] or 0) > 0 for row in source_rows
        )
        if declared_unit_contract:
            if not source_rows or any(
                int(row["expected_unit_count"] or 0) < 1 for row in source_rows
            ):
                return "not_started"
            expected_units = sum(
                int(row["expected_unit_count"]) for row in source_rows
            )
            unit_row = connection.execute(
                """
                SELECT COUNT(*) AS state_units,
                       SUM(CASE WHEN u.processing_status IN (
                           'evidence_extracted',
                           'processed_no_relevant_evidence'
                       ) THEN 1 ELSE 0 END) AS resolved_units,
                       SUM(CASE WHEN u.processing_status = 'manual_review_required'
                           THEN 1 ELSE 0 END) AS manual_units,
                       SUM(CASE WHEN u.processing_status = 'failed'
                           THEN 1 ELSE 0 END) AS failed_units
                FROM eligibility_source_processing_unit_state u
                JOIN eligibility_source_revisions s
                  ON s.tenant_id=u.tenant_id AND s.project_id=u.project_id
                 AND s.subject_id=u.subject_id AND s.source_id=u.source_id
                 AND s.source_revision=u.source_revision
                WHERE u.tenant_id = ? AND u.project_id = ? AND u.subject_id = ?
                  AND u.subject_source_revision = ?
                  AND s.subject_source_revision = u.subject_source_revision
                  AND s.is_current = 1
                  AND u.unit_index <= s.expected_unit_count
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    subject_source_revision,
                ),
            ).fetchone()
            state_units = int(unit_row["state_units"] or 0)
            resolved_units = int(unit_row["resolved_units"] or 0)
            manual_units = int(unit_row["manual_units"] or 0)
            failed_units = int(unit_row["failed_units"] or 0)
            unresolved_span_row = connection.execute(
                """
                SELECT COUNT(*) AS unresolved_spans
                FROM eligibility_evidence_spans e
                JOIN eligibility_source_revisions s
                  ON s.tenant_id=e.tenant_id AND s.project_id=e.project_id
                 AND s.subject_id=e.subject_id AND s.source_id=e.source_id
                 AND s.source_revision=e.source_revision
                LEFT JOIN eligibility_evidence_visual_qc_state q
                  ON q.tenant_id=e.tenant_id AND q.project_id=e.project_id
                 AND q.subject_id=e.subject_id AND q.evidence_id=e.evidence_id
                 AND q.source_revision=e.source_revision
                 AND q.extraction_revision=e.extraction_revision
                WHERE e.tenant_id = ? AND e.project_id = ? AND e.subject_id = ?
                  AND s.subject_source_revision = ? AND s.is_current = 1
                  AND NOT (
                      e.processing_state IN ('completed', 'needs_visual_qc')
                      AND COALESCE(q.effective_result, '') = 'sampled_pass'
                  )
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    subject_source_revision,
                ),
            ).fetchone()
            unresolved_spans = int(unresolved_span_row["unresolved_spans"] or 0)
            if unresolved_spans:
                return "needs_visual_qc" if not resolved_units else "partial"
            if state_units == expected_units and resolved_units == expected_units:
                return "completed"
            if failed_units:
                return "failed"
            if manual_units:
                return "needs_visual_qc"
            if state_units or resolved_units:
                return "partial"
            return "not_started"

        # Compatibility only for pre-v14 callers that have no declared unit contract.
        span_row = connection.execute(
            """
            SELECT COUNT(*) AS total_spans,
                   SUM(CASE WHEN e.processing_state IN ('completed', 'needs_visual_qc')
                                  AND q.effective_result = 'sampled_pass'
                            THEN 1 ELSE 0 END) AS resolved_spans,
                   COUNT(DISTINCT CASE
                       WHEN e.processing_state IN ('completed', 'needs_visual_qc')
                            AND q.effective_result = 'sampled_pass'
                       THEN e.source_id END) AS resolved_sources
            FROM eligibility_evidence_spans e
            JOIN eligibility_source_revisions s
              ON s.tenant_id=e.tenant_id AND s.project_id=e.project_id
             AND s.subject_id=e.subject_id AND s.source_id=e.source_id
             AND s.source_revision=e.source_revision
            LEFT JOIN eligibility_evidence_visual_qc_state q
              ON q.tenant_id=e.tenant_id AND q.project_id=e.project_id
             AND q.subject_id=e.subject_id AND q.evidence_id=e.evidence_id
             AND q.source_revision=e.source_revision
             AND q.extraction_revision=e.extraction_revision
            WHERE e.tenant_id = ? AND e.project_id = ? AND e.subject_id = ?
              AND s.subject_source_revision = ? AND s.is_current = 1
            """,
            (
                TENANT_PLACEHOLDER, project_id, subject_id,
                subject_source_revision,
            ),
        ).fetchone()
        total_sources = len(source_rows)
        total_spans = int(span_row["total_spans"] or 0)
        resolved_spans = int(span_row["resolved_spans"] or 0)
        resolved_sources = int(span_row["resolved_sources"] or 0)
        if total_sources == 0 or total_spans == 0:
            return "not_started"
        if (
            resolved_sources == total_sources
            and resolved_spans == total_spans
        ):
            return "completed"
        if resolved_spans:
            return "partial"
        return "needs_visual_qc"

    def commit_eligibility_review_action(
        self,
        record: Dict[str, Any],
        *,
        expected_state_revision: int,
        expected_rule_revision: str,
        expected_subject_source_revision: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> EligibilityReviewCommitResult:
        project_id = str(record.get("project_id") or "")
        subject_id = str(record.get("subject_id") or "")
        criterion_uid = str(record.get("criterion_uid") or "")
        criterion_kind = str(record.get("criterion_kind") or "")
        operation = f"eligibility_review_action:{subject_id}:{criterion_uid}"
        if not all((project_id, subject_id, criterion_uid, idempotency_key)):
            raise ValueError("eligibility review identity and idempotency key are required")
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay_request_id = self._idempotency_result(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay_request_id is not None:
                replay = connection.execute(
                    """
                    SELECT record_id, new_state_revision
                    FROM eligibility_review_records
                    WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                      AND criterion_uid = ? AND request_id = ?
                    """,
                    (
                        TENANT_PLACEHOLDER, project_id, subject_id,
                        criterion_uid, replay_request_id,
                    ),
                ).fetchone()
                if replay is None:
                    raise RuntimeStoreIntegrityError(
                        "eligibility idempotency record has no review record"
                    )
                connection.rollback()
                return EligibilityReviewCommitResult(
                    request_id=replay_request_id,
                    record_id=str(replay["record_id"]),
                    state_revision=int(replay["new_state_revision"]),
                    replayed=True,
                )

            rule = connection.execute(
                """
                SELECT criterion_kind FROM eligibility_rule_revisions
                WHERE tenant_id = ? AND project_id = ? AND rule_revision = ?
                  AND criterion_uid = ? AND is_current = 1
                """,
                (
                    TENANT_PLACEHOLDER, project_id, expected_rule_revision,
                    criterion_uid,
                ),
            ).fetchone()
            if rule is None or str(rule["criterion_kind"]) != criterion_kind:
                raise StaleRuntimeStateError("eligibility rule revision is stale")
            source = connection.execute(
                """
                SELECT 1 FROM eligibility_source_revisions
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND subject_source_revision = ? AND is_current = 1
                LIMIT 1
                """,
                (
                    TENANT_PLACEHOLDER, project_id, subject_id,
                    expected_subject_source_revision,
                ),
            ).fetchone()
            if source is None:
                raise StaleRuntimeStateError("eligibility subject source revision is stale")

            current = connection.execute(
                """
                SELECT * FROM eligibility_review_state
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND criterion_uid = ?
                """,
                (TENANT_PLACEHOLDER, project_id, subject_id, criterion_uid),
            ).fetchone()
            actual_state_revision = int(current["state_revision"]) if current else 0
            if actual_state_revision != expected_state_revision:
                raise StaleRuntimeStateError(
                    "stale eligibility review state: "
                    f"expected={expected_state_revision}, actual={actual_state_revision}"
                )
            if record.get("rule_revision") != expected_rule_revision:
                raise StaleRuntimeStateError("record rule revision does not match expected")
            if record.get("subject_source_revision") != expected_subject_source_revision:
                raise StaleRuntimeStateError(
                    "record subject source revision does not match expected"
                )
            if int(record.get("previous_state_revision", -1)) != expected_state_revision:
                raise StaleRuntimeStateError("record previous state revision is stale")
            new_state_revision = expected_state_revision + 1
            if int(record.get("new_state_revision", -1)) != new_state_revision:
                raise ValueError("record new state revision must increment by one")

            action = str(record.get("action") or "")
            record_type = str(record.get("record_type") or "")
            action_decision = record.get("action_decision")
            # This compatibility field is never trusted. The authoritative value is
            # derived from current evidence and immutable visual-QC state below.
            processing_state = "not_started"
            allowed_decisions = {
                "inclusion": {
                    "met", "not_met", "insufficient_evidence", "not_applicable",
                    "requires_investigator_judgment",
                },
                "exclusion": {
                    "absent", "present", "insufficient_evidence", "not_applicable",
                    "requires_investigator_judgment",
                },
            }
            if action_decision is not None and action_decision not in allowed_decisions.get(
                criterion_kind, set()
            ):
                raise ValueError("decision is invalid for criterion kind")
            previous_ai = str(current["ai_draft_decision"]) if current and current["ai_draft_decision"] is not None else None
            previous_medical = str(current["medical_decision"]) if current and current["medical_decision"] is not None else None
            ai_decision = previous_ai
            medical_decision = previous_medical
            ai_record_id = str(current["ai_draft_record_id"]) if current and current["ai_draft_record_id"] else None
            medical_record_id = str(current["medical_record_id"]) if current and current["medical_record_id"] else None
            record_id = str(record.get("record_id") or f"eligreview_{uuid4().hex}")
            if action == "save_ai_draft":
                if record_type != "ai_draft" or action_decision is None:
                    raise ValueError("save_ai_draft requires an AI decision")
                ai_decision = action_decision
                ai_record_id = record_id
            elif action == "accept_ai_draft":
                if record_type != "medical_action" or previous_ai is None:
                    raise ValueError("accept_ai_draft requires an existing AI draft")
                medical_decision = previous_ai
                action_decision = previous_ai
                medical_record_id = record_id
            elif action == "revise_decision":
                if record_type != "medical_action" or action_decision is None:
                    raise ValueError("revise_decision requires a medical decision")
                medical_decision = action_decision
                medical_record_id = record_id
            elif action in {"request_evidence", "defer_review"}:
                if record_type != "medical_action":
                    raise ValueError("medical review action requires medical_action record")
            elif action == "reset_after_source_change":
                if record_type != "medical_action" or current is None:
                    raise ValueError(
                        "reset_after_source_change requires an existing review state"
                    )
                if (
                    str(current["rule_revision"]) == expected_rule_revision
                    and str(current["subject_source_revision"])
                    == expected_subject_source_revision
                ):
                    raise ValueError(
                        "reset_after_source_change requires rule or source revision drift"
                    )
                if record.get("action_decision") is not None or record.get("evidence_ids"):
                    raise ValueError(
                        "reset_after_source_change cannot carry a decision or evidence"
                    )
                ai_decision = None
                medical_decision = None
                ai_record_id = None
                medical_record_id = None
            else:
                raise ValueError("unsupported eligibility review action")

            evidence_ids = list(record.get("evidence_ids") or [])
            if action_decision in {"met", "not_met", "absent", "present"} and not evidence_ids:
                raise ValueError("decisive eligibility review requires evidence_ids")
            for evidence_id in evidence_ids:
                evidence = connection.execute(
                    """
                    SELECT 1 FROM eligibility_evidence_spans e
                    JOIN eligibility_source_revisions s
                      ON s.tenant_id=e.tenant_id AND s.project_id=e.project_id
                     AND s.subject_id=e.subject_id AND s.source_id=e.source_id
                     AND s.source_revision=e.source_revision
                    WHERE e.tenant_id = ? AND e.project_id = ? AND e.subject_id = ?
                      AND e.evidence_id = ? AND s.subject_source_revision = ?
                      AND s.is_current = 1
                    LIMIT 1
                    """,
                    (
                        TENANT_PLACEHOLDER, project_id, subject_id, evidence_id,
                        expected_subject_source_revision,
                    ),
                ).fetchone()
                if evidence is None:
                    raise StaleRuntimeStateError(
                        f"eligibility evidence is missing or stale: {evidence_id}"
                    )
                if (
                    action_decision in {"met", "not_met", "absent", "present"}
                    and not self._evidence_is_valid_for_decisive_review(
                        connection,
                        project_id=project_id,
                        subject_id=subject_id,
                        evidence_id=evidence_id,
                        subject_source_revision=expected_subject_source_revision,
                    )
                ):
                    raise ValueError(
                        "evidence_not_valid_for_decisive_review: " + evidence_id
                    )
            processing_state = self._subject_evidence_processing_state(
                connection,
                project_id=project_id,
                subject_id=subject_id,
                subject_source_revision=expected_subject_source_revision,
            )
            if (
                action_decision == "insufficient_evidence"
                and processing_state != "completed"
            ):
                raise ValueError(
                    "insufficient_evidence requires completed evidence processing "
                    "derived by the server"
                )

            created_at = str(record.get("created_at") or _utc_now().isoformat())
            reason = str(record.get("reason") or "")
            connection.execute(
                """
                INSERT INTO eligibility_review_records(
                    tenant_id, project_id, subject_id, criterion_uid, record_id,
                    criterion_kind, record_type, action, action_decision,
                    ai_draft_decision, medical_decision,
                    evidence_processing_state, rule_revision,
                    subject_source_revision, previous_state_revision,
                    new_state_revision, evidence_ids_json, reason, actor,
                    identity_assurance, ai_draft_record_id, medical_record_id,
                    idempotency_key, request_hash, request_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER, project_id, subject_id, criterion_uid,
                    record_id, criterion_kind, record_type, action,
                    action_decision, ai_decision, medical_decision,
                    processing_state, expected_rule_revision,
                    expected_subject_source_revision, expected_state_revision,
                    new_state_revision, _canonical_json(evidence_ids), reason,
                    str(record.get("actor") or ""), IDENTITY_ASSURANCE,
                    ai_record_id, medical_record_id, idempotency_key,
                    request_fingerprint, request_id, created_at,
                ),
            )
            self._inject("after_eligibility_review_record")
            connection.execute(
                """
                INSERT INTO eligibility_review_state(
                    tenant_id, project_id, subject_id, criterion_uid,
                    criterion_kind, rule_revision, subject_source_revision,
                    state_revision, evidence_processing_state,
                    ai_draft_decision, medical_decision, latest_action, reason,
                    evidence_ids_json, ai_draft_record_id, medical_record_id,
                    latest_record_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, project_id, subject_id, criterion_uid)
                DO UPDATE SET
                    criterion_kind=excluded.criterion_kind,
                    rule_revision=excluded.rule_revision,
                    subject_source_revision=excluded.subject_source_revision,
                    state_revision=excluded.state_revision,
                    evidence_processing_state=excluded.evidence_processing_state,
                    ai_draft_decision=excluded.ai_draft_decision,
                    medical_decision=excluded.medical_decision,
                    latest_action=excluded.latest_action,
                    reason=excluded.reason,
                    evidence_ids_json=excluded.evidence_ids_json,
                    ai_draft_record_id=excluded.ai_draft_record_id,
                    medical_record_id=excluded.medical_record_id,
                    latest_record_id=excluded.latest_record_id,
                    updated_at=excluded.updated_at
                """,
                (
                    TENANT_PLACEHOLDER, project_id, subject_id, criterion_uid,
                    criterion_kind, expected_rule_revision,
                    expected_subject_source_revision, new_state_revision,
                    processing_state, ai_decision, medical_decision, action,
                    reason, _canonical_json(evidence_ids), ai_record_id,
                    medical_record_id, record_id, created_at,
                ),
            )
            self._inject("after_eligibility_review_state")
            self._append_runtime_audit(
                connection,
                project_id=project_id,
                event_type="eligibility_review_action_committed",
                operation=operation,
                actor=str(record.get("actor") or ""),
                detail={
                    "record_id": record_id,
                    "subject_id": subject_id,
                    "criterion_uid": criterion_uid,
                    "action": action,
                    "previous_state_revision": expected_state_revision,
                    "new_state_revision": new_state_revision,
                    "rule_revision": expected_rule_revision,
                    "subject_source_revision": expected_subject_source_revision,
                    "evidence_ids": evidence_ids,
                },
            )
            self._inject("after_eligibility_runtime_audit")
            self._insert_idempotency(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            connection.commit()
            return EligibilityReviewCommitResult(
                request_id=request_id,
                record_id=record_id,
                state_revision=new_state_revision,
            )
        except StaleRuntimeStateError as exc:
            connection.rollback()
            self._record_rejection(
                project_id,
                event_type="eligibility_stale_write_rejected",
                operation=operation,
                actor=str(record.get("actor") or ""),
                detail={
                    "subject_id": subject_id,
                    "criterion_uid": criterion_uid,
                    "expected_state_revision": expected_state_revision,
                    "expected_rule_revision": expected_rule_revision,
                    "expected_subject_source_revision": (
                        expected_subject_source_revision
                    ),
                    "request_hash": request_fingerprint,
                    "reason_code": "stale_runtime_state",
                },
            )
            raise exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def eligibility_subject_evidence_spans(
        self,
        project_id: str,
        subject_id: str,
    ) -> List[Dict[str, Any]]:
        rows = self._rows(
            """
            SELECT e.evidence_id, e.source_id, e.source_revision,
                   e.extraction_revision, e.locator_json, e.media_class,
                   e.processing_state, e.quality_state,
                   e.extraction_confidence, e.medical_verification_status,
                   e.created_at, q.qc_revision, q.effective_result AS qc_result,
                   q.reason_code AS qc_reason_code,
                   q.user_reason AS qc_user_reason,
                   r.sample_plan_id, r.sample_unit_json, r.policy_version,
                   r.actor AS qc_actor,
                   r.identity_assurance AS qc_identity_assurance
            FROM eligibility_evidence_spans e
            JOIN eligibility_source_revisions s
              ON s.tenant_id=e.tenant_id AND s.project_id=e.project_id
             AND s.subject_id=e.subject_id AND s.source_id=e.source_id
             AND s.source_revision=e.source_revision
            LEFT JOIN eligibility_evidence_visual_qc_state q
              ON q.tenant_id=e.tenant_id AND q.project_id=e.project_id
             AND q.subject_id=e.subject_id AND q.evidence_id=e.evidence_id
             AND q.source_revision=e.source_revision
             AND q.extraction_revision=e.extraction_revision
            LEFT JOIN eligibility_evidence_visual_qc_records r
              ON r.tenant_id=q.tenant_id AND r.project_id=q.project_id
             AND r.qc_record_id=q.latest_qc_record_id
            WHERE e.tenant_id = ? AND e.project_id = ? AND e.subject_id = ?
              AND s.is_current = 1
            ORDER BY e.source_id, e.evidence_id
            """,
            (TENANT_PLACEHOLDER, project_id, subject_id),
        )
        payloads = []
        for row in rows:
            payload = dict(row)
            payload["locator"] = json.loads(payload.pop("locator_json"))
            stored_processing = str(payload["processing_state"])
            stored_quality = str(payload["quality_state"])
            qc_result = payload.pop("qc_result")
            qc_revision = payload.pop("qc_revision")
            sample_unit_json = payload.pop("sample_unit_json")
            valid = (
                stored_processing in {"completed", "needs_visual_qc"}
                and qc_result == "sampled_pass"
            )
            if qc_result == "sampled_pass":
                effective_processing = "completed"
                effective_quality = "sampled_pass"
            elif qc_result == "sampled_fail":
                effective_processing = "failed"
                effective_quality = "sampled_fail"
            elif qc_result == "manual_review_required":
                effective_processing = "needs_visual_qc"
                effective_quality = "manual_review_required"
            else:
                effective_processing = (
                    "needs_visual_qc"
                    if stored_processing in {"completed", "needs_visual_qc"}
                    else stored_processing
                )
                effective_quality = stored_quality
            payload["stored_state"] = {
                "processing_state": stored_processing,
                "quality_state": stored_quality,
                "medical_verification_status": payload["medical_verification_status"],
            }
            payload["effective_state"] = {
                "processing_state": effective_processing,
                "quality_state": effective_quality,
                "valid_for_decisive_review": valid,
            }
            payload["valid_for_decisive_review"] = valid
            payload["visual_qc"] = {
                "qc_revision": int(qc_revision or 0),
                "result": qc_result,
                "reason_code": payload.pop("qc_reason_code"),
                "reason_summary": (
                    str(payload.pop("qc_user_reason") or "")[:240] or None
                ),
                "sample_plan_id": payload.pop("sample_plan_id"),
                "sample_unit": (
                    json.loads(sample_unit_json) if sample_unit_json else None
                ),
                "policy_version": payload.pop("policy_version"),
                "actor": payload.pop("qc_actor"),
                "identity_assurance": payload.pop("qc_identity_assurance"),
                "is_electronic_signature": False,
            }
            payloads.append(payload)
        return payloads

    def validate_eligibility_ai_inputs(
        self,
        *,
        project_id: str,
        subject_id: str,
        rule_revision: str,
        subject_source_revision: str,
        criteria: Iterable[Dict[str, Any]],
        evidence_ids: Iterable[str],
    ) -> str:
        """Fail closed before eligibility content is disclosed to an AI provider."""
        criterion_rows = list(criteria)
        evidence_id_rows = list(evidence_ids)
        if not all((project_id, subject_id, rule_revision, subject_source_revision)):
            raise ValueError("eligibility AI input identity is required")
        if not criterion_rows:
            raise ValueError("eligibility AI input criteria are required")
        if len(evidence_id_rows) != len(set(evidence_id_rows)):
            raise ValueError("eligibility AI input evidence IDs must be unique")

        connection = self._connect()
        try:
            source = connection.execute(
                """
                SELECT 1 FROM eligibility_source_revisions
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND subject_source_revision = ? AND is_current = 1
                LIMIT 1
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    subject_source_revision,
                ),
            ).fetchone()
            if source is None:
                raise StaleRuntimeStateError(
                    "eligibility AI input subject source revision is stale"
                )

            seen = set()
            for criterion in criterion_rows:
                criterion_uid = str(criterion.get("criterion_uid") or "")
                if not criterion_uid or criterion_uid in seen:
                    raise ValueError(
                        "eligibility AI input criterion identities must be unique"
                    )
                seen.add(criterion_uid)
                stored = connection.execute(
                    """
                    SELECT criterion_kind, source_locator_json,
                           normalized_text_hash, display_order
                    FROM eligibility_rule_revisions
                    WHERE tenant_id = ? AND project_id = ? AND rule_revision = ?
                      AND criterion_uid = ? AND is_current = 1
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        rule_revision,
                        criterion_uid,
                    ),
                ).fetchone()
                if stored is None:
                    raise StaleRuntimeStateError(
                        "eligibility AI input rule revision is stale"
                    )
                locator = json.loads(str(stored["source_locator_json"]))
                stored_locator = (
                    str(locator.get("locator") or "")
                    if isinstance(locator, dict)
                    else ""
                )
                if (
                    str(stored["criterion_kind"])
                    != str(criterion.get("criterion_kind") or "")
                    or stored_locator != str(criterion.get("source_locator") or "")
                    or str(stored["normalized_text_hash"])
                    != str(criterion.get("normalized_text_hash") or "")
                    or int(stored["display_order"])
                    != int(criterion.get("display_order") or 0)
                ):
                    raise StaleRuntimeStateError(
                        "eligibility AI input criterion payload is not canonical"
                    )

            for evidence_id in evidence_id_rows:
                if not self._evidence_is_valid_for_decisive_review(
                    connection,
                    project_id=project_id,
                    subject_id=subject_id,
                    evidence_id=evidence_id,
                    subject_source_revision=subject_source_revision,
                ):
                    raise StaleRuntimeStateError(
                        "eligibility AI input evidence is missing, stale or not visual-QC passed"
                    )
            return self._subject_evidence_processing_state(
                connection,
                project_id=project_id,
                subject_id=subject_id,
                subject_source_revision=subject_source_revision,
            )
        finally:
            connection.close()

    def eligibility_ai_source_unit_contract_state(
        self,
        *,
        project_id: str,
        subject_id: str,
        subject_source_revision: str,
    ) -> str:
        """AI packets never use the pre-v14 span-only compatibility path."""
        with self._connect() as connection:
            sources = connection.execute(
                """
                SELECT processing_unit_kind, expected_unit_count
                FROM eligibility_source_revisions
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND subject_source_revision = ? AND is_current = 1
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    subject_source_revision,
                ),
            ).fetchall()
            if not sources or any(
                str(row["processing_unit_kind"]) == "legacy_unknown"
                or int(row["expected_unit_count"] or 0) < 1
                for row in sources
            ):
                return "not_started"
            return self._subject_evidence_processing_state(
                connection,
                project_id=project_id,
                subject_id=subject_id,
                subject_source_revision=subject_source_revision,
            )

    def eligibility_ai_evidence_artifact_bindings(
        self,
        *,
        project_id: str,
        subject_id: str,
        subject_source_revision: str,
    ) -> List[Dict[str, Any]]:
        """Return private, integrity-bound artifacts eligible for AI packet assembly."""
        connection = self._connect()
        try:
            spans = connection.execute(
                """
                SELECT e.evidence_id, e.source_id, e.source_revision,
                       e.extraction_revision, e.locator_json, e.metadata_json,
                       e.media_class
                FROM eligibility_evidence_spans e
                JOIN eligibility_source_revisions s
                  ON s.tenant_id=e.tenant_id AND s.project_id=e.project_id
                 AND s.subject_id=e.subject_id AND s.source_id=e.source_id
                 AND s.source_revision=e.source_revision
                JOIN eligibility_evidence_visual_qc_state q
                  ON q.tenant_id=e.tenant_id AND q.project_id=e.project_id
                 AND q.subject_id=e.subject_id AND q.evidence_id=e.evidence_id
                 AND q.source_revision=e.source_revision
                 AND q.extraction_revision=e.extraction_revision
                WHERE e.tenant_id = ? AND e.project_id = ? AND e.subject_id = ?
                  AND s.subject_source_revision = ? AND s.is_current = 1
                  AND e.processing_state IN ('completed', 'needs_visual_qc')
                  AND q.effective_result = 'sampled_pass'
                ORDER BY e.source_id, e.evidence_id
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    subject_source_revision,
                ),
            ).fetchall()
            bindings: List[Dict[str, Any]] = []
            for span in spans:
                metadata = json.loads(str(span["metadata_json"]))
                artifact_id = (
                    str(metadata.get("artifact_id") or "")
                    if isinstance(metadata, dict)
                    else ""
                )
                if not artifact_id:
                    raise RuntimeStoreIntegrityError(
                        "eligibility AI evidence span has no controlled artifact binding"
                    )
                artifact = connection.execute(
                    """
                    SELECT artifact_id, artifact_kind, storage_key, content_hash,
                           size_bytes, media_type, source_id, source_revision,
                           extraction_revision
                    FROM eligibility_evidence_artifacts
                    WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                      AND artifact_id = ?
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        subject_id,
                        artifact_id,
                    ),
                ).fetchone()
                if artifact is None or any(
                    str(artifact[key]) != str(span[key])
                    for key in (
                        "source_id",
                        "source_revision",
                        "extraction_revision",
                    )
                ):
                    raise RuntimeStoreIntegrityError(
                        "eligibility AI evidence artifact binding is missing or inconsistent"
                    )
                bindings.append(
                    {
                        "project_id": project_id,
                        "subject_id": subject_id,
                        "evidence_id": str(span["evidence_id"]),
                        "source_id": str(span["source_id"]),
                        "source_revision": str(span["source_revision"]),
                        "extraction_revision": str(span["extraction_revision"]),
                        "locator": json.loads(str(span["locator_json"])),
                        "media_class": str(span["media_class"]),
                        **{key: artifact[key] for key in (
                            "artifact_id",
                            "artifact_kind",
                            "storage_key",
                            "content_hash",
                            "size_bytes",
                            "media_type",
                        )},
                    }
                )
            return bindings
        finally:
            connection.close()

    def commit_eligibility_ai_draft_batch(
        self,
        records: Iterable[Dict[str, Any]],
        *,
        batch_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> EligibilityAiBatchCommitResult:
        rows = list(records)
        if not rows or not batch_id or not idempotency_key:
            raise ValueError("eligibility AI batch identity and records are required")
        project_id = str(rows[0].get("project_id") or "")
        subject_id = str(rows[0].get("subject_id") or "")
        rule_revision = str(rows[0].get("rule_revision") or "")
        subject_source_revision = str(
            rows[0].get("subject_source_revision") or ""
        )
        operation = f"eligibility_ai_draft_batch:{subject_id}:{batch_id}"
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay_request_id = self._idempotency_result(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay_request_id is not None:
                replay_rows = connection.execute(
                    """
                    SELECT criterion_uid, new_state_revision
                    FROM eligibility_review_records
                    WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                      AND request_id = ? AND action = 'save_ai_draft'
                    ORDER BY criterion_uid
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        subject_id,
                        replay_request_id,
                    ),
                ).fetchall()
                if len(replay_rows) != len(rows):
                    raise RuntimeStoreIntegrityError(
                        "eligibility AI batch idempotency record is incomplete"
                    )
                connection.rollback()
                return EligibilityAiBatchCommitResult(
                    request_id=replay_request_id,
                    state_revisions={
                        str(row["criterion_uid"]): int(row["new_state_revision"])
                        for row in replay_rows
                    },
                    replayed=True,
                )

            if not all(
                (
                    project_id,
                    subject_id,
                    rule_revision,
                    subject_source_revision,
                )
            ):
                raise ValueError("eligibility AI batch revisions are required")
            source = connection.execute(
                """
                SELECT 1 FROM eligibility_source_revisions
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND subject_source_revision = ? AND is_current = 1
                LIMIT 1
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    subject_source_revision,
                ),
            ).fetchone()
            if source is None:
                raise StaleRuntimeStateError(
                    "eligibility AI batch subject source revision is stale"
                )

            seen_criteria = set()
            seen_record_ids = set()
            prepared = []
            for row in rows:
                if any(
                    str(row.get(key) or "") != expected
                    for key, expected in (
                        ("project_id", project_id),
                        ("subject_id", subject_id),
                        ("rule_revision", rule_revision),
                        ("subject_source_revision", subject_source_revision),
                    )
                ):
                    raise ValueError(
                        "eligibility AI batch rows must share project, subject and revisions"
                    )
                criterion_uid = str(row.get("criterion_uid") or "")
                criterion_kind = str(row.get("criterion_kind") or "")
                record_id = str(row.get("record_id") or "")
                if (
                    not criterion_uid
                    or criterion_uid in seen_criteria
                    or not record_id
                    or record_id in seen_record_ids
                ):
                    raise ValueError(
                        "eligibility AI batch criterion and record identities must be unique"
                    )
                seen_criteria.add(criterion_uid)
                seen_record_ids.add(record_id)
                if row.get("record_type") != "ai_draft" or row.get("action") != "save_ai_draft":
                    raise ValueError("eligibility AI batch accepts AI draft records only")
                rule = connection.execute(
                    """
                    SELECT criterion_kind FROM eligibility_rule_revisions
                    WHERE tenant_id = ? AND project_id = ? AND rule_revision = ?
                      AND criterion_uid = ? AND is_current = 1
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        rule_revision,
                        criterion_uid,
                    ),
                ).fetchone()
                if rule is None or str(rule["criterion_kind"]) != criterion_kind:
                    raise StaleRuntimeStateError(
                        "eligibility AI batch rule revision is stale"
                    )
                current = connection.execute(
                    """
                    SELECT * FROM eligibility_review_state
                    WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                      AND criterion_uid = ?
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        subject_id,
                        criterion_uid,
                    ),
                ).fetchone()
                actual_revision = int(current["state_revision"]) if current else 0
                expected_revision = int(row.get("previous_state_revision", -1))
                if actual_revision != expected_revision:
                    raise StaleRuntimeStateError(
                        "eligibility AI batch criterion state is stale"
                    )
                if current is not None and current["medical_decision"] is not None:
                    raise StaleRuntimeStateError(
                        "eligibility AI draft cannot replace a medical decision"
                    )
                new_revision = expected_revision + 1
                if int(row.get("new_state_revision", -1)) != new_revision:
                    raise ValueError(
                        "eligibility AI batch state revision must increment by one"
                    )
                decision = str(row.get("action_decision") or "")
                allowed_decisions = {
                    "inclusion": {
                        "met",
                        "not_met",
                        "insufficient_evidence",
                        "not_applicable",
                        "requires_investigator_judgment",
                    },
                    "exclusion": {
                        "absent",
                        "present",
                        "insufficient_evidence",
                        "not_applicable",
                        "requires_investigator_judgment",
                    },
                }
                if decision not in allowed_decisions.get(criterion_kind, set()):
                    raise ValueError(
                        "eligibility AI batch decision is invalid for criterion kind"
                    )
                processing_state = self._subject_evidence_processing_state(
                    connection,
                    project_id=project_id,
                    subject_id=subject_id,
                    subject_source_revision=subject_source_revision,
                )
                evidence_ids = list(row.get("evidence_ids") or [])
                if decision == "insufficient_evidence" and processing_state != "completed":
                    raise ValueError(
                        "insufficient_evidence requires completed evidence processing"
                    )
                if decision in {"met", "not_met", "absent", "present"} and not evidence_ids:
                    raise ValueError(
                        "decisive eligibility review requires evidence_ids"
                    )
                if len(evidence_ids) != len(set(evidence_ids)):
                    raise ValueError("eligibility AI batch evidence_ids must be unique")
                for evidence_id in evidence_ids:
                    if not self._evidence_is_valid_for_decisive_review(
                        connection,
                        project_id=project_id,
                        subject_id=subject_id,
                        evidence_id=evidence_id,
                        subject_source_revision=subject_source_revision,
                    ):
                        raise StaleRuntimeStateError(
                            "eligibility AI batch evidence is missing, stale or not visual-QC passed"
                        )
                prepared.append(
                    {
                        "row": row,
                        "criterion_uid": criterion_uid,
                        "criterion_kind": criterion_kind,
                        "record_id": record_id,
                        "decision": decision,
                        "processing_state": processing_state,
                        "evidence_ids": evidence_ids,
                        "previous_revision": expected_revision,
                        "new_revision": new_revision,
                    }
                )

            created_at = _utc_now().isoformat()
            for item in prepared:
                row = item["row"]
                current = connection.execute(
                    """
                    SELECT medical_decision, medical_record_id
                    FROM eligibility_review_state
                    WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                      AND criterion_uid = ?
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        subject_id,
                        item["criterion_uid"],
                    ),
                ).fetchone()
                medical_decision = (
                    str(current["medical_decision"])
                    if current is not None and current["medical_decision"] is not None
                    else None
                )
                medical_record_id = (
                    str(current["medical_record_id"])
                    if current is not None and current["medical_record_id"]
                    else None
                )
                connection.execute(
                    """
                    INSERT INTO eligibility_review_records(
                        tenant_id, project_id, subject_id, criterion_uid, record_id,
                        criterion_kind, record_type, action, action_decision,
                        ai_draft_decision, medical_decision,
                        evidence_processing_state, rule_revision,
                        subject_source_revision, previous_state_revision,
                        new_state_revision, evidence_ids_json, reason, actor,
                        identity_assurance, ai_draft_record_id, medical_record_id,
                        idempotency_key, request_hash, request_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'ai_draft', 'save_ai_draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        subject_id,
                        item["criterion_uid"],
                        item["record_id"],
                        item["criterion_kind"],
                        item["decision"],
                        item["decision"],
                        medical_decision,
                        item["processing_state"],
                        rule_revision,
                        subject_source_revision,
                        item["previous_revision"],
                        item["new_revision"],
                        _canonical_json(item["evidence_ids"]),
                        str(row.get("reason") or ""),
                        str(row.get("actor") or "workbench_ai_gateway"),
                        IDENTITY_ASSURANCE,
                        item["record_id"],
                        medical_record_id,
                        idempotency_key,
                        request_fingerprint,
                        request_id,
                        str(row.get("created_at") or created_at),
                    ),
                )
            self._inject("after_eligibility_ai_batch_records")
            for item in prepared:
                row = item["row"]
                connection.execute(
                    """
                    INSERT INTO eligibility_review_state(
                        tenant_id, project_id, subject_id, criterion_uid,
                        criterion_kind, rule_revision, subject_source_revision,
                        state_revision, evidence_processing_state,
                        ai_draft_decision, medical_decision, latest_action, reason,
                        evidence_ids_json, ai_draft_record_id, medical_record_id,
                        latest_record_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'save_ai_draft', ?, ?, ?, NULL, ?, ?)
                    ON CONFLICT(tenant_id, project_id, subject_id, criterion_uid)
                    DO UPDATE SET
                        criterion_kind=excluded.criterion_kind,
                        rule_revision=excluded.rule_revision,
                        subject_source_revision=excluded.subject_source_revision,
                        state_revision=excluded.state_revision,
                        evidence_processing_state=excluded.evidence_processing_state,
                        ai_draft_decision=excluded.ai_draft_decision,
                        latest_action=excluded.latest_action,
                        reason=excluded.reason,
                        evidence_ids_json=excluded.evidence_ids_json,
                        ai_draft_record_id=excluded.ai_draft_record_id,
                        latest_record_id=excluded.latest_record_id,
                        updated_at=excluded.updated_at
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        subject_id,
                        item["criterion_uid"],
                        item["criterion_kind"],
                        rule_revision,
                        subject_source_revision,
                        item["new_revision"],
                        item["processing_state"],
                        item["decision"],
                        str(row.get("reason") or ""),
                        _canonical_json(item["evidence_ids"]),
                        item["record_id"],
                        item["record_id"],
                        str(row.get("created_at") or created_at),
                    ),
                )
            self._inject("after_eligibility_ai_batch_states")
            self._append_runtime_audit(
                connection,
                project_id=project_id,
                event_type="eligibility_ai_batch_committed",
                operation=operation,
                actor="workbench_ai_gateway",
                detail={
                    "batch_id": batch_id,
                    "subject_id": subject_id,
                    "criterion_uids": sorted(seen_criteria),
                    "criterion_count": len(prepared),
                    "rule_revision": rule_revision,
                    "subject_source_revision": subject_source_revision,
                    "evidence_reference_count": sum(
                        len(item["evidence_ids"]) for item in prepared
                    ),
                },
            )
            self._inject("after_eligibility_ai_batch_audit")
            self._insert_idempotency(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            connection.commit()
            return EligibilityAiBatchCommitResult(
                request_id=request_id,
                state_revisions={
                    item["criterion_uid"]: item["new_revision"]
                    for item in prepared
                },
            )
        except StaleRuntimeStateError as exc:
            connection.rollback()
            self._record_rejection(
                project_id,
                event_type="eligibility_ai_batch_rejected",
                operation=operation,
                actor="workbench_ai_gateway",
                detail={
                    "batch_id": batch_id,
                    "subject_id": subject_id,
                    "rule_revision": rule_revision,
                    "subject_source_revision": subject_source_revision,
                    "criterion_count": len(rows),
                    "request_hash": request_fingerprint,
                    "reason_code": "stale_runtime_state",
                },
            )
            raise exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def eligibility_ai_batch_replay(
        self,
        *,
        project_id: str,
        subject_id: str,
        batch_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Optional[EligibilityAiBatchCommitResult]:
        """Return a committed business batch before another provider call is made."""
        operation = f"eligibility_ai_draft_batch:{subject_id}:{batch_id}"
        connection = self._connect()
        try:
            request_id = self._idempotency_result(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if request_id is None:
                return None
            rows = connection.execute(
                """
                SELECT criterion_uid, new_state_revision
                FROM eligibility_review_records
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND request_id = ? AND action = 'save_ai_draft'
                ORDER BY criterion_uid
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    request_id,
                ),
            ).fetchall()
            if not rows:
                raise RuntimeStoreIntegrityError(
                    "eligibility AI batch idempotency record has no draft rows"
                )
            return EligibilityAiBatchCommitResult(
                request_id=request_id,
                state_revisions={
                    str(row["criterion_uid"]): int(row["new_state_revision"])
                    for row in rows
                },
                replayed=True,
            )
        finally:
            connection.close()

    def eligibility_review_records(
        self,
        project_id: str,
        subject_id: str,
        criterion_uid: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT * FROM eligibility_review_records
            WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
        """
        params: List[Any] = [TENANT_PLACEHOLDER, project_id, subject_id]
        if criterion_uid is not None:
            query += " AND criterion_uid = ?"
            params.append(criterion_uid)
        query += " ORDER BY criterion_uid, new_state_revision, created_at, rowid"
        return [self._eligibility_record_dict(row) for row in self._rows(query, params)]

    def eligibility_review_state(
        self,
        project_id: str,
        subject_id: str,
        criterion_uid: str,
    ) -> Optional[Dict[str, Any]]:
        rows = self._rows(
            """
            SELECT * FROM eligibility_review_state
            WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
              AND criterion_uid = ?
            """,
            (TENANT_PLACEHOLDER, project_id, subject_id, criterion_uid),
        )
        return self._eligibility_state_dict(rows[-1]) if rows else None

    def eligibility_subject_review_states(
        self,
        project_id: str,
        subject_id: str,
    ) -> List[Dict[str, Any]]:
        return [
            self._eligibility_state_dict(row)
            for row in self._rows(
                """
                SELECT * FROM eligibility_review_state
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                ORDER BY criterion_kind, criterion_uid
                """,
                (TENANT_PLACEHOLDER, project_id, subject_id),
            )
        ]

    def eligibility_rule_revision_rows(
        self,
        project_id: str,
        rule_revision: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT project_id, rule_revision, criterion_uid, criterion_kind,
                   source_rule_label, source_locator_json,
                   normalized_text_hash, display_order, is_current, created_at
            FROM eligibility_rule_revisions
            WHERE tenant_id = ? AND project_id = ?
        """
        params: List[Any] = [TENANT_PLACEHOLDER, project_id]
        if rule_revision is None:
            query += " AND is_current = 1"
        else:
            query += " AND rule_revision = ?"
            params.append(rule_revision)
        query += " ORDER BY criterion_kind, display_order, criterion_uid"
        payloads = []
        for row in self._rows(query, params):
            payload = dict(row)
            payload["source_locator"] = json.loads(
                payload.pop("source_locator_json")
            )
            payloads.append(payload)
        return payloads

    @staticmethod
    def _eligibility_record_dict(row: sqlite3.Row) -> Dict[str, Any]:
        payload = dict(row)
        payload.pop("tenant_id", None)
        payload["evidence_ids"] = json.loads(payload.pop("evidence_ids_json"))
        return payload

    @staticmethod
    def _eligibility_state_dict(row: sqlite3.Row) -> Dict[str, Any]:
        payload = dict(row)
        payload.pop("tenant_id", None)
        payload["evidence_ids"] = json.loads(payload.pop("evidence_ids_json"))
        return payload

    def commit_evidence_ai_revision_submission(
        self,
        thread: EvidenceAiRevisionThread,
        audit_event: AuditEvent,
        *,
        idempotency_key: Optional[str] = None,
        request_fingerprint: Optional[str] = None,
    ) -> RuntimeCommitResult:
        if thread.project_id != audit_event.project_id:
            raise ValueError("evidence AI revision thread and audit event project ids must match")
        if audit_event.target_type != "evidence_ai_revision_thread":
            raise ValueError("evidence AI revision audit target type is invalid")
        if audit_event.target_id != thread.thread_id:
            raise ValueError("evidence AI revision audit target must match thread id")
        if thread.revision != 1:
            raise ValueError("evidence AI revision submission must start at revision 1")

        operation = "evidence_ai_revision_submission"
        request_payload = {
            "thread": thread.model_dump(mode="json"),
            "audit_event": audit_event.model_dump(mode="json"),
        }
        request_hash = request_fingerprint or _payload_hash(request_payload)
        key = idempotency_key or f"auto:{request_hash}"
        request_id = f"req_{uuid4().hex}"
        snapshot_id = audit_event.audit_id
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection,
                thread.project_id,
                operation,
                key,
                request_hash,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            connection.execute(
                """
                INSERT INTO evidence_ai_revision_threads(
                    tenant_id, project_id, thread_id, package_id, anchor_type,
                    anchor_id, revision, status, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    thread.project_id,
                    thread.thread_id,
                    thread.package_id,
                    thread.anchor_type,
                    thread.anchor_id,
                    thread.revision,
                    thread.status,
                    thread.updated_at.isoformat(),
                    _canonical_json(thread.model_dump(mode="json")),
                ),
            )
            self._inject("after_evidence_ai_revision_thread")
            self._insert_evidence_ai_revision_snapshot(
                connection,
                thread,
                snapshot_id=snapshot_id,
                action=audit_event.action,
                audit_id=audit_event.audit_id,
                created_at=audit_event.created_at,
            )
            self._inject("after_evidence_ai_revision_snapshot")
            self._insert_workflow_audit(connection, audit_event, "evidence_ai_revision")
            self._inject("after_workflow_audit")
            self._append_runtime_audit(
                connection,
                project_id=thread.project_id,
                event_type="evidence_ai_revision_submitted",
                operation=operation,
                actor=audit_event.actor,
                detail={
                    "thread_id": thread.thread_id,
                    "package_id": thread.package_id,
                    "revision": thread.revision,
                    "action": audit_event.action,
                    "thread_snapshot_id": snapshot_id,
                    "thread_payload_hash": _payload_hash(thread.model_dump(mode="json")),
                    "audit_id": audit_event.audit_id,
                    "audit_payload_hash": _payload_hash(audit_event.model_dump(mode="json")),
                },
            )
            self._insert_idempotency(
                connection,
                thread.project_id,
                operation,
                key,
                request_hash,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(f"evidence AI revision submission conflict: {exc}") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_evidence_ai_revision_action(
        self,
        previous_thread: EvidenceAiRevisionThread,
        updated_thread: EvidenceAiRevisionThread,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
        idempotency_key: Optional[str] = None,
        request_fingerprint: Optional[str] = None,
    ) -> RuntimeCommitResult:
        if len(
            {
                previous_thread.project_id,
                updated_thread.project_id,
                audit_event.project_id,
            }
        ) != 1:
            raise ValueError("evidence AI revision action records must target one project")
        if previous_thread.thread_id != updated_thread.thread_id:
            raise ValueError("evidence AI revision action records must target one thread")
        if audit_event.target_type != "evidence_ai_revision_thread":
            raise ValueError("evidence AI revision audit target type is invalid")
        if audit_event.target_id != updated_thread.thread_id:
            raise ValueError("evidence AI revision audit target must match thread id")
        if previous_thread.revision != expected_revision:
            raise ValueError("previous evidence AI revision must equal expected_revision")
        if updated_thread.revision != expected_revision + 1:
            raise ValueError("updated evidence AI revision must equal expected_revision + 1")
        previous_identity = (
            previous_thread.package_id,
            previous_thread.anchor_type,
            previous_thread.anchor_id,
            previous_thread.base_picos_revision,
            previous_thread.evidence_package_hash,
            previous_thread.created_by,
        )
        updated_identity = (
            updated_thread.package_id,
            updated_thread.anchor_type,
            updated_thread.anchor_id,
            updated_thread.base_picos_revision,
            updated_thread.evidence_package_hash,
            updated_thread.created_by,
        )
        if previous_identity != updated_identity:
            raise ValueError("evidence AI revision action cannot change thread identity")

        operation = "evidence_ai_revision_action"
        request_payload = {
            "previous_thread": previous_thread.model_dump(mode="json"),
            "updated_thread": updated_thread.model_dump(mode="json"),
            "audit_event": audit_event.model_dump(mode="json"),
            "expected_revision": expected_revision,
        }
        request_hash = request_fingerprint or _payload_hash(request_payload)
        key = idempotency_key or f"auto:{request_hash}"
        request_id = f"req_{uuid4().hex}"
        snapshot_id = audit_event.audit_id
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection,
                updated_thread.project_id,
                operation,
                key,
                request_hash,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            row = connection.execute(
                """
                SELECT revision
                FROM evidence_ai_revision_threads
                WHERE tenant_id = ? AND project_id = ? AND thread_id = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    updated_thread.project_id,
                    updated_thread.thread_id,
                ),
            ).fetchone()
            if row is None:
                raise KeyError(f"evidence AI revision thread not found: {updated_thread.thread_id}")
            actual_revision = int(row["revision"])
            if actual_revision != expected_revision:
                connection.rollback()
                self._record_rejection(
                    updated_thread.project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=audit_event.actor,
                    detail={
                        "thread_id": updated_thread.thread_id,
                        "package_id": updated_thread.package_id,
                        "expected_revision": expected_revision,
                        "actual_revision": actual_revision,
                        "audit_id": audit_event.audit_id,
                    },
                )
                raise StaleRuntimeStateError(
                    "stale evidence AI revision thread: "
                    f"expected={expected_revision}, actual={actual_revision}"
                )

            updated = connection.execute(
                """
                UPDATE evidence_ai_revision_threads
                SET revision = ?, status = ?, updated_at = ?, payload_json = ?
                WHERE tenant_id = ? AND project_id = ? AND thread_id = ? AND revision = ?
                """,
                (
                    updated_thread.revision,
                    updated_thread.status,
                    updated_thread.updated_at.isoformat(),
                    _canonical_json(updated_thread.model_dump(mode="json")),
                    TENANT_PLACEHOLDER,
                    updated_thread.project_id,
                    updated_thread.thread_id,
                    expected_revision,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                self._record_rejection(
                    updated_thread.project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=audit_event.actor,
                    detail={
                        "thread_id": updated_thread.thread_id,
                        "package_id": updated_thread.package_id,
                        "expected_revision": expected_revision,
                        "actual_revision": actual_revision,
                        "audit_id": audit_event.audit_id,
                    },
                )
                raise StaleRuntimeStateError(
                    f"stale evidence AI revision thread: {updated_thread.thread_id}"
                )
            self._inject("after_evidence_ai_revision_thread")
            self._insert_evidence_ai_revision_snapshot(
                connection,
                updated_thread,
                snapshot_id=snapshot_id,
                action=audit_event.action,
                audit_id=audit_event.audit_id,
                created_at=audit_event.created_at,
            )
            self._inject("after_evidence_ai_revision_snapshot")
            self._insert_workflow_audit(connection, audit_event, "evidence_ai_revision")
            self._inject("after_workflow_audit")
            self._append_runtime_audit(
                connection,
                project_id=updated_thread.project_id,
                event_type="evidence_ai_revision_action_committed",
                operation=operation,
                actor=audit_event.actor,
                detail={
                    "thread_id": updated_thread.thread_id,
                    "package_id": updated_thread.package_id,
                    "revision": updated_thread.revision,
                    "action": audit_event.action,
                    "thread_snapshot_id": snapshot_id,
                    "thread_payload_hash": _payload_hash(updated_thread.model_dump(mode="json")),
                    "audit_id": audit_event.audit_id,
                    "audit_payload_hash": _payload_hash(audit_event.model_dump(mode="json")),
                },
            )
            self._insert_idempotency(
                connection,
                updated_thread.project_id,
                operation,
                key,
                request_hash,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(f"evidence AI revision action conflict: {exc}") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_evidence_review_action(
        self,
        record: EvidenceReviewRecord,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> RuntimeCommitResult:
        if record.project_id != audit_event.project_id:
            raise ValueError("evidence review record and audit event project ids must match")
        if audit_event.target_id != record.evidence_id:
            raise ValueError("evidence review audit target must match evidence id")
        if record.previous_revision != expected_revision:
            raise ValueError("evidence review previous_revision must equal expected_revision")
        if record.new_revision != expected_revision + 1:
            raise ValueError("evidence review new_revision must equal expected_revision + 1")

        operation = "evidence_review_action"
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection,
                record.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            row = connection.execute(
                """
                SELECT new_revision
                FROM evidence_review_records
                WHERE tenant_id = ? AND project_id = ? AND package_id = ? AND evidence_id = ?
                ORDER BY new_revision DESC, created_at DESC, rowid DESC
                LIMIT 1
                """,
                (
                    TENANT_PLACEHOLDER,
                    record.project_id,
                    record.package_id,
                    record.evidence_id,
                ),
            ).fetchone()
            actual_revision = int(row["new_revision"]) if row is not None else 0
            if actual_revision != expected_revision:
                connection.rollback()
                self._record_rejection(
                    record.project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=audit_event.actor,
                    detail={
                        "record_id": record.record_id,
                        "package_id": record.package_id,
                        "evidence_id": record.evidence_id,
                        "expected_revision": expected_revision,
                        "actual_revision": actual_revision,
                    },
                )
                raise StaleRuntimeStateError(
                    "stale evidence review revision: "
                    f"expected={expected_revision}, actual={actual_revision}"
                )

            connection.execute(
                """
                INSERT INTO evidence_review_records(
                    tenant_id, project_id, record_id, package_id, evidence_id,
                    action, previous_revision, new_revision, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    record.project_id,
                    record.record_id,
                    record.package_id,
                    record.evidence_id,
                    record.action.value,
                    record.previous_revision,
                    record.new_revision,
                    record.created_at.isoformat(),
                    _canonical_json(record.model_dump(mode="json")),
                ),
            )
            self._inject("after_evidence_review_record")
            self._insert_workflow_audit(connection, audit_event, "evidence_review")
            self._inject("after_workflow_audit")
            self._append_runtime_audit(
                connection,
                project_id=record.project_id,
                event_type="evidence_review_action_committed",
                operation=operation,
                actor=audit_event.actor,
                detail={
                    "record_id": record.record_id,
                    "package_id": record.package_id,
                    "evidence_id": record.evidence_id,
                    "revision": record.new_revision,
                    "review_payload_hash": _payload_hash(record.model_dump(mode="json")),
                    "audit_id": audit_event.audit_id,
                    "audit_payload_hash": _payload_hash(audit_event.model_dump(mode="json")),
                },
            )
            self._insert_idempotency(
                connection,
                record.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(f"evidence review action conflict: {exc}") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_evidence_picos_action(
        self,
        previous_state: EvidencePicosWorkingState,
        updated_state: EvidencePicosWorkingState,
        record: EvidencePicosDecisionRecord,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> RuntimeCommitResult:
        project_ids = {
            previous_state.project_id,
            updated_state.project_id,
            record.project_id,
            audit_event.project_id,
        }
        if len(project_ids) != 1:
            raise ValueError("PICOS action records must target one project")
        if len({previous_state.package_id, updated_state.package_id, record.package_id}) != 1:
            raise ValueError("PICOS action records must target one evidence package")
        if len(
            {
                previous_state.working_state_id,
                updated_state.working_state_id,
                record.working_state_id,
            }
        ) != 1:
            raise ValueError("PICOS action records must target one working state")
        if audit_event.target_id != updated_state.working_state_id:
            raise ValueError("PICOS action audit target must match working state id")
        if previous_state.revision != expected_revision:
            raise ValueError("PICOS previous state revision must equal expected_revision")
        if updated_state.revision != expected_revision + 1:
            raise ValueError("PICOS updated state revision must equal expected_revision + 1")
        if record.previous_revision != expected_revision or record.new_revision != updated_state.revision:
            raise ValueError("PICOS decision record revisions must match working state revisions")

        operation = "evidence_picos_action"
        request_id = f"req_{uuid4().hex}"
        snapshot_id = f"picos_state_snapshot:{audit_event.audit_id}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection,
                updated_state.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            row = connection.execute(
                """
                SELECT working_state_id, revision
                FROM evidence_picos_working_states
                WHERE tenant_id = ? AND project_id = ? AND package_id = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    updated_state.project_id,
                    updated_state.package_id,
                ),
            ).fetchone()
            actual_revision = int(row["revision"]) if row is not None else 0
            if actual_revision != expected_revision:
                connection.rollback()
                self._record_rejection(
                    updated_state.project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=audit_event.actor,
                    detail={
                        "record_id": record.record_id,
                        "package_id": updated_state.package_id,
                        "working_state_id": updated_state.working_state_id,
                        "expected_revision": expected_revision,
                        "actual_revision": actual_revision,
                    },
                )
                raise StaleRuntimeStateError(
                    "stale evidence PICOS working state revision: "
                    f"expected={expected_revision}, actual={actual_revision}"
                )
            if row is not None and row["working_state_id"] != updated_state.working_state_id:
                raise RuntimeStoreError("PICOS working state identity conflicts with package")

            connection.execute(
                """
                INSERT INTO evidence_picos_working_states(
                    tenant_id, project_id, working_state_id, package_id,
                    evidence_package_hash, revision, approval_state, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, project_id, package_id) DO UPDATE SET
                    evidence_package_hash = excluded.evidence_package_hash,
                    revision = excluded.revision,
                    approval_state = excluded.approval_state,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (
                    TENANT_PLACEHOLDER,
                    updated_state.project_id,
                    updated_state.working_state_id,
                    updated_state.package_id,
                    updated_state.evidence_package_hash,
                    updated_state.revision,
                    updated_state.approval_state.value,
                    updated_state.updated_at.isoformat(),
                    _canonical_json(updated_state.model_dump(mode="json")),
                ),
            )
            self._inject("after_evidence_picos_working_state")
            connection.execute(
                """
                INSERT INTO evidence_picos_decision_records(
                    tenant_id, project_id, record_id, package_id, working_state_id,
                    question_id, action, previous_revision, new_revision,
                    created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    record.project_id,
                    record.record_id,
                    record.package_id,
                    record.working_state_id,
                    record.question_id,
                    record.action.value,
                    record.previous_revision,
                    record.new_revision,
                    record.created_at.isoformat(),
                    _canonical_json(record.model_dump(mode="json")),
                ),
            )
            self._inject("after_evidence_picos_decision")
            self._insert_evidence_picos_snapshot(
                connection,
                snapshot_id=snapshot_id,
                project_id=updated_state.project_id,
                package_id=updated_state.package_id,
                working_state_id=updated_state.working_state_id,
                revision=updated_state.revision,
                snapshot_type="decision_action",
                approval_id="",
                audit_id=audit_event.audit_id,
                created_at=audit_event.created_at,
                payload=updated_state.model_dump(mode="json"),
            )
            self._inject("after_evidence_picos_snapshot")
            self._insert_workflow_audit(connection, audit_event, "evidence_picos")
            self._inject("after_workflow_audit")
            self._append_runtime_audit(
                connection,
                project_id=updated_state.project_id,
                event_type="evidence_picos_action_committed",
                operation=operation,
                actor=audit_event.actor,
                detail={
                    "record_id": record.record_id,
                    "package_id": updated_state.package_id,
                    "working_state_id": updated_state.working_state_id,
                    "revision": updated_state.revision,
                    "decision_payload_hash": _payload_hash(record.model_dump(mode="json")),
                    "working_state_snapshot_id": snapshot_id,
                    "working_state_payload_hash": _payload_hash(
                        updated_state.model_dump(mode="json")
                    ),
                    "audit_id": audit_event.audit_id,
                    "audit_payload_hash": _payload_hash(audit_event.model_dump(mode="json")),
                },
            )
            self._insert_idempotency(
                connection,
                updated_state.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(f"evidence PICOS action conflict: {exc}") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_evidence_picos_snapshot(
        self,
        snapshot: EvidencePicosSnapshot,
        approval: ApprovalGate,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> RuntimeCommitResult:
        if len({snapshot.project_id, approval.project_id, audit_event.project_id}) != 1:
            raise ValueError("PICOS snapshot records must target one project")
        if snapshot.approval_id != approval.approval_id:
            raise ValueError("PICOS snapshot approval id must match approval gate")
        if approval.target_type != "evidence_picos_snapshot":
            raise ValueError("PICOS snapshot approval gate target type is invalid")
        if approval.target_id != snapshot.snapshot_id or audit_event.target_id != snapshot.snapshot_id:
            raise ValueError("PICOS snapshot target ids must match")
        if approval.target_revision != snapshot.revision:
            raise ValueError("PICOS snapshot approval target revision must match snapshot")
        if snapshot.revision != expected_revision:
            raise ValueError("PICOS snapshot revision must equal expected_revision")

        operation = "evidence_picos_snapshot"
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection,
                snapshot.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            row = connection.execute(
                """
                SELECT working_state_id, revision, payload_json
                FROM evidence_picos_working_states
                WHERE tenant_id = ? AND project_id = ? AND package_id = ?
                """,
                (TENANT_PLACEHOLDER, snapshot.project_id, snapshot.package_id),
            ).fetchone()
            actual_revision = int(row["revision"]) if row is not None else 0
            if actual_revision != expected_revision:
                connection.rollback()
                self._record_rejection(
                    snapshot.project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=audit_event.actor,
                    detail={
                        "snapshot_id": snapshot.snapshot_id,
                        "package_id": snapshot.package_id,
                        "working_state_id": snapshot.working_state_id,
                        "expected_revision": expected_revision,
                        "actual_revision": actual_revision,
                    },
                )
                raise StaleRuntimeStateError(
                    "stale evidence PICOS snapshot revision: "
                    f"expected={expected_revision}, actual={actual_revision}"
                )
            if row is None or row["working_state_id"] != snapshot.working_state_id:
                raise RuntimeStoreError("PICOS snapshot working state does not match stored state")
            stored_state = EvidencePicosWorkingState.model_validate(json.loads(row["payload_json"]))
            if stored_state.evidence_package_hash != snapshot.evidence_package_hash:
                raise RuntimeStoreError("PICOS snapshot evidence package hash is stale")
            if stored_state.question_states != snapshot.question_states:
                raise RuntimeStoreError("PICOS snapshot questions do not match stored state")

            self._insert_evidence_picos_snapshot(
                connection,
                snapshot_id=snapshot.snapshot_id,
                project_id=snapshot.project_id,
                package_id=snapshot.package_id,
                working_state_id=snapshot.working_state_id,
                revision=snapshot.revision,
                snapshot_type=snapshot.snapshot_type,
                approval_id=snapshot.approval_id,
                audit_id=audit_event.audit_id,
                created_at=snapshot.created_at,
                payload=snapshot.model_dump(mode="json"),
            )
            self._inject("after_evidence_picos_snapshot")
            self._upsert_gate(connection, approval)
            self._inject("after_gate")
            self._insert_workflow_audit(connection, audit_event, "evidence_picos_snapshot")
            self._inject("after_workflow_audit")
            self._append_runtime_audit(
                connection,
                project_id=snapshot.project_id,
                event_type="evidence_picos_snapshot_committed",
                operation=operation,
                actor=audit_event.actor,
                detail={
                    "snapshot_id": snapshot.snapshot_id,
                    "package_id": snapshot.package_id,
                    "working_state_id": snapshot.working_state_id,
                    "revision": snapshot.revision,
                    "approval_id": approval.approval_id,
                    "snapshot_payload_hash": _payload_hash(snapshot.model_dump(mode="json")),
                    "audit_id": audit_event.audit_id,
                    "audit_payload_hash": _payload_hash(audit_event.model_dump(mode="json")),
                },
            )
            self._insert_idempotency(
                connection,
                snapshot.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(f"evidence PICOS snapshot conflict: {exc}") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_evidence_picos_handoff(
        self,
        handoff: EvidencePicosWritingHandoff,
        audit_event: AuditEvent,
        *,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> RuntimeCommitResult:
        if handoff.project_id != audit_event.project_id:
            raise ValueError("PICOS handoff and audit event project ids must match")
        if audit_event.target_id != handoff.handoff_id:
            raise ValueError("PICOS handoff audit target must match handoff id")

        operation = "evidence_picos_handoff"
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection,
                handoff.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            gate_row = connection.execute(
                """
                SELECT payload_json
                FROM approval_gates
                WHERE tenant_id = ? AND project_id = ? AND approval_id = ?
                """,
                (TENANT_PLACEHOLDER, handoff.project_id, handoff.approval_id),
            ).fetchone()
            snapshot_row = connection.execute(
                """
                SELECT package_id, working_state_id, revision, approval_id, payload_json
                FROM evidence_picos_working_state_snapshots
                WHERE tenant_id = ? AND project_id = ? AND snapshot_id = ?
                """,
                (TENANT_PLACEHOLDER, handoff.project_id, handoff.snapshot_id),
            ).fetchone()
            state_row = connection.execute(
                """
                SELECT working_state_id, revision, payload_json
                FROM evidence_picos_working_states
                WHERE tenant_id = ? AND project_id = ? AND package_id = ?
                """,
                (TENANT_PLACEHOLDER, handoff.project_id, handoff.package_id),
            ).fetchone()

            rejection_reason = ""
            gate: Optional[ApprovalGate] = None
            snapshot: Optional[EvidencePicosSnapshot] = None
            stored_state: Optional[EvidencePicosWorkingState] = None
            try:
                if gate_row is not None:
                    gate = ApprovalGate.model_validate(json.loads(gate_row["payload_json"]))
                if snapshot_row is not None:
                    snapshot = EvidencePicosSnapshot.model_validate(
                        json.loads(snapshot_row["payload_json"])
                    )
                if state_row is not None:
                    stored_state = EvidencePicosWorkingState.model_validate(
                        json.loads(state_row["payload_json"])
                    )
            except (ValueError, TypeError, json.JSONDecodeError):
                rejection_reason = "stored approval, snapshot, or working state is invalid"

            approved_states = {
                ApprovalState.MEDICALLY_APPROVED,
                ApprovalState.LOCKED_FOR_SUBMISSION,
            }
            if not rejection_reason and gate is None:
                rejection_reason = "approval gate not found"
            elif not rejection_reason and gate.state not in approved_states:
                rejection_reason = "approval gate is not medically approved"
            elif not rejection_reason and (
                gate.target_type != "evidence_picos_snapshot"
                or gate.target_id != handoff.snapshot_id
                or gate.target_revision != handoff.approved_revision
            ):
                rejection_reason = "approval gate target snapshot or revision does not match"
            elif not rejection_reason and snapshot is None:
                rejection_reason = "approved PICOS snapshot not found"
            elif not rejection_reason and (
                snapshot.project_id != handoff.project_id
                or snapshot.package_id != handoff.package_id
                or snapshot.working_state_id != handoff.working_state_id
                or snapshot.snapshot_id != handoff.snapshot_id
                or snapshot.approval_id != handoff.approval_id
                or snapshot.revision != handoff.approved_revision
            ):
                rejection_reason = "handoff does not match approved PICOS snapshot"
            elif not rejection_reason and stored_state is None:
                rejection_reason = "PICOS working state not found"
            elif not rejection_reason and (
                stored_state.working_state_id != handoff.working_state_id
                or stored_state.revision != handoff.approved_revision
                or stored_state.evidence_package_hash != snapshot.evidence_package_hash
            ):
                rejection_reason = "PICOS working state changed after approval"

            if rejection_reason:
                connection.rollback()
                self._record_rejection(
                    handoff.project_id,
                    event_type="workflow_transition_rejected",
                    operation=operation,
                    actor=audit_event.actor,
                    detail={
                        "handoff_id": handoff.handoff_id,
                        "package_id": handoff.package_id,
                        "snapshot_id": handoff.snapshot_id,
                        "approval_id": handoff.approval_id,
                        "approved_revision": handoff.approved_revision,
                        "reason": rejection_reason,
                    },
                )
                raise RuntimeStoreError(f"evidence PICOS handoff rejected: {rejection_reason}")

            existing_row = connection.execute(
                """
                SELECT payload_json
                FROM evidence_picos_writing_handoffs
                WHERE tenant_id = ? AND project_id = ? AND handoff_id = ?
                """,
                (TENANT_PLACEHOLDER, handoff.project_id, handoff.handoff_id),
            ).fetchone()
            if existing_row is not None:
                existing = EvidencePicosWritingHandoff.model_validate(
                    json.loads(existing_row["payload_json"])
                )
                business_identity = (
                    "project_id",
                    "package_id",
                    "working_state_id",
                    "snapshot_id",
                    "approval_id",
                    "approved_revision",
                    "target_module",
                    "target_document_type",
                )
                if any(
                    getattr(existing, field) != getattr(handoff, field)
                    for field in business_identity
                ):
                    connection.rollback()
                    raise RuntimeStoreError(
                        "evidence PICOS handoff business identity conflict"
                    )
                self._insert_idempotency(
                    connection,
                    handoff.project_id,
                    operation,
                    idempotency_key,
                    request_fingerprint,
                    request_id,
                )
                connection.commit()
                return RuntimeCommitResult(request_id=request_id, replayed=True)

            connection.execute(
                """
                INSERT INTO evidence_picos_writing_handoffs(
                    tenant_id, project_id, handoff_id, package_id, working_state_id,
                    snapshot_id, approval_id, approved_revision, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    handoff.project_id,
                    handoff.handoff_id,
                    handoff.package_id,
                    handoff.working_state_id,
                    handoff.snapshot_id,
                    handoff.approval_id,
                    handoff.approved_revision,
                    handoff.created_at.isoformat(),
                    _canonical_json(handoff.model_dump(mode="json")),
                ),
            )
            self._inject("after_evidence_picos_handoff")
            self._insert_workflow_audit(connection, audit_event, "evidence_picos_handoff")
            self._inject("after_workflow_audit")
            self._append_runtime_audit(
                connection,
                project_id=handoff.project_id,
                event_type="evidence_picos_handoff_committed",
                operation=operation,
                actor=audit_event.actor,
                detail={
                    "handoff_id": handoff.handoff_id,
                    "package_id": handoff.package_id,
                    "snapshot_id": handoff.snapshot_id,
                    "approval_id": handoff.approval_id,
                    "approved_revision": handoff.approved_revision,
                    "approval_state": gate.state.value,
                    "handoff_payload_hash": _payload_hash(handoff.model_dump(mode="json")),
                    "snapshot_payload_hash": _payload_hash(snapshot.model_dump(mode="json")),
                    "audit_id": audit_event.audit_id,
                    "audit_payload_hash": _payload_hash(audit_event.model_dump(mode="json")),
                },
            )
            self._insert_idempotency(
                connection,
                handoff.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(f"evidence PICOS handoff conflict: {exc}") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_rux_disposition(
        self,
        disposition: RuxRiskDispositionRecord,
        approval: Optional[ApprovalGate] = None,
        idempotency_key: Optional[str] = None,
        request_fingerprint: Optional[str] = None,
        operation: str = "rux_disposition",
    ) -> RuntimeCommitResult:
        request_payload = {
            "disposition": disposition.model_dump(mode="json"),
            "approval": approval.model_dump(mode="json") if approval else None,
        }
        request_hash = request_fingerprint or _payload_hash(request_payload)
        key = idempotency_key or f"auto:{request_hash}"
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection, disposition.project_id, operation, key, request_hash
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            actual_state = self._latest_disposition_state(
                connection,
                disposition.project_id,
                disposition.item_id,
                disposition.source_version,
            )
            if disposition.previous_state != actual_state:
                connection.rollback()
                self._record_rejection(
                    disposition.project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=disposition.actor,
                    detail={
                        "item_id": disposition.item_id,
                        "source_version": disposition.source_version,
                        "expected_state": disposition.previous_state,
                        "actual_state": actual_state,
                    },
                )
                raise StaleRuntimeStateError(
                    f"stale disposition state: expected={disposition.previous_state}, actual={actual_state}"
                )

            if approval is not None:
                self._upsert_gate(connection, approval)
                self._inject("after_gate")
            connection.execute(
                """
                INSERT INTO rux_disposition_records(
                    tenant_id, record_id, project_id, item_id, source_version,
                    new_state, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    disposition.record_id,
                    disposition.project_id,
                    disposition.item_id,
                    disposition.source_version,
                    disposition.new_state,
                    disposition.created_at.isoformat(),
                    _canonical_json(disposition.model_dump(mode="json")),
                ),
            )
            self._inject("after_disposition")
            self._append_runtime_audit(
                connection,
                project_id=disposition.project_id,
                event_type="rux_disposition_committed",
                operation=operation,
                actor=disposition.actor,
                detail={
                    "record_id": disposition.record_id,
                    "item_id": disposition.item_id,
                    "risk_key": disposition.risk_key,
                    "risk_instance_id": disposition.risk_instance_id,
                    "snapshot_id": disposition.snapshot_id,
                    "previous_state": disposition.previous_state,
                    "new_state": disposition.new_state,
                    "approval_id": approval.approval_id if approval else "",
                    "disposition_payload_hash": _payload_hash(
                        disposition.model_dump(mode="json")
                    ),
                },
            )
            self._insert_idempotency(
                connection,
                disposition.project_id,
                operation,
                key,
                request_hash,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_medical_writing_content_disposition(
        self,
        record: MedicalWritingContentDispositionRecord,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_fingerprint: str,
        operation: str = "medical_writing_content_disposition",
    ) -> RuntimeCommitResult:
        if record.revision != expected_revision + 1:
            raise ValueError("content disposition revision must equal expected revision + 1")
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection,
                record.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            state_row = connection.execute(
                """
                SELECT revision, status
                FROM medical_writing_content_disposition_state
                WHERE tenant_id = ? AND project_id = ? AND finding_id = ?
                """,
                (TENANT_PLACEHOLDER, record.project_id, record.finding_id),
            ).fetchone()
            actual_revision = int(state_row["revision"]) if state_row is not None else 0
            actual_status = (
                str(state_row["status"])
                if state_row is not None
                else "open"
            )
            if actual_revision != expected_revision:
                connection.rollback()
                self._record_rejection(
                    record.project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=record.actor,
                    detail={
                        "finding_id": record.finding_id,
                        "expected_revision": expected_revision,
                        "actual_revision": actual_revision,
                        "expected_status": record.previous_status.value,
                        "actual_status": actual_status,
                    },
                )
                raise StaleRuntimeStateError(
                    "stale medical writing content disposition: "
                    f"expected revision={expected_revision}, actual={actual_revision}"
                )

            connection.execute(
                """
                INSERT INTO medical_writing_content_disposition_records(
                    tenant_id, project_id, record_id, finding_id, document_id,
                    section_id, detector_version, content_fingerprint,
                    content_revision, revision, status, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    record.project_id,
                    record.record_id,
                    record.finding_id,
                    record.document_id,
                    record.section_id,
                    record.detector_version,
                    record.content_fingerprint,
                    record.content_revision,
                    record.revision,
                    record.status.value,
                    record.created_at.isoformat(),
                    _canonical_json(record.model_dump(mode="json")),
                ),
            )
            self._inject("after_medical_writing_content_disposition")
            connection.execute(
                """
                INSERT INTO medical_writing_content_disposition_state(
                    tenant_id, project_id, finding_id, document_id, section_id,
                    detector_version, content_fingerprint, content_revision,
                    revision, status, latest_record_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, project_id, finding_id) DO UPDATE SET
                    document_id = excluded.document_id,
                    section_id = excluded.section_id,
                    detector_version = excluded.detector_version,
                    content_fingerprint = excluded.content_fingerprint,
                    content_revision = excluded.content_revision,
                    revision = excluded.revision,
                    status = excluded.status,
                    latest_record_id = excluded.latest_record_id,
                    updated_at = excluded.updated_at
                """,
                (
                    TENANT_PLACEHOLDER,
                    record.project_id,
                    record.finding_id,
                    record.document_id,
                    record.section_id,
                    record.detector_version,
                    record.content_fingerprint,
                    record.content_revision,
                    record.revision,
                    record.status.value,
                    record.record_id,
                    record.created_at.isoformat(),
                ),
            )
            self._append_runtime_audit(
                connection,
                project_id=record.project_id,
                event_type="medical_writing_content_disposition_committed",
                operation=operation,
                actor=record.actor,
                detail={
                    "record_id": record.record_id,
                    "finding_id": record.finding_id,
                    "document_id": record.document_id,
                    "section_id": record.section_id,
                    "detector_version": record.detector_version,
                    "content_fingerprint": record.content_fingerprint,
                    "content_revision": record.content_revision,
                    "previous_status": record.previous_status.value,
                    "status": record.status.value,
                    "revision": record.revision,
                    "reason": record.reason,
                    "record_payload_hash": _payload_hash(record.model_dump(mode="json")),
                },
            )
            self._insert_idempotency(
                connection,
                record.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(
                f"medical writing content disposition conflict: {exc}"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def lookup_idempotent_replay(
        self,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Optional[RuntimeCommitResult]:
        with self._connect() as connection:
            request_id = self._idempotency_result(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
        if request_id is None:
            return None
        return RuntimeCommitResult(request_id=request_id, replayed=True)

    def commit_safety_review(
        self,
        record: SafetyReviewRecord,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_fingerprint: str,
        operation: str = "safety_pv_review",
    ) -> RuntimeCommitResult:
        if record.previous_revision != expected_revision:
            raise ValueError("Safety/PV review previous revision must equal expected revision")
        if record.revision != record.previous_revision + 1:
            raise ValueError("Safety/PV review revision must equal expected revision + 1")
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection,
                record.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            state_row = connection.execute(
                """
                SELECT revision, status
                FROM safety_pv_review_state
                WHERE tenant_id = ? AND project_id = ?
                  AND package_id = ? AND signal_id = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    record.project_id,
                    record.package_id,
                    record.signal_id,
                ),
            ).fetchone()
            actual_revision = int(state_row["revision"]) if state_row is not None else 0
            actual_status = str(state_row["status"]) if state_row is not None else "待医学/PV确认"
            if actual_revision != expected_revision:
                connection.rollback()
                self._record_rejection(
                    record.project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=record.actor,
                    detail={
                        "package_id": record.package_id,
                        "signal_id": record.signal_id,
                        "expected_revision": expected_revision,
                        "actual_revision": actual_revision,
                        "expected_status": record.previous_status,
                        "actual_status": actual_status,
                    },
                )
                raise StaleRuntimeStateError(
                    "stale Safety/PV review: "
                    f"expected revision={expected_revision}, actual={actual_revision}"
                )
            if record.previous_status != actual_status:
                connection.rollback()
                self._record_rejection(
                    record.project_id,
                    event_type="stale_status_rejected",
                    operation=operation,
                    actor=record.actor,
                    detail={
                        "package_id": record.package_id,
                        "signal_id": record.signal_id,
                        "expected_revision": expected_revision,
                        "expected_status": record.previous_status,
                        "actual_status": actual_status,
                    },
                )
                raise StaleRuntimeStateError(
                    "stale Safety/PV review status: "
                    f"expected={record.previous_status}, actual={actual_status}"
                )

            connection.execute(
                """
                INSERT INTO safety_pv_review_records(
                    tenant_id, project_id, record_id, package_id, signal_id,
                    revision, action, previous_status, new_status,
                    created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    record.project_id,
                    record.record_id,
                    record.package_id,
                    record.signal_id,
                    record.revision,
                    record.action.value,
                    record.previous_status,
                    record.new_status,
                    record.created_at.isoformat(),
                    _canonical_json(record.model_dump(mode="json")),
                ),
            )
            self._inject("after_safety_pv_review_record")
            connection.execute(
                """
                INSERT INTO safety_pv_review_state(
                    tenant_id, project_id, package_id, signal_id, revision,
                    status, latest_record_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, project_id, package_id, signal_id) DO UPDATE SET
                    revision = excluded.revision,
                    status = excluded.status,
                    latest_record_id = excluded.latest_record_id,
                    updated_at = excluded.updated_at
                """,
                (
                    TENANT_PLACEHOLDER,
                    record.project_id,
                    record.package_id,
                    record.signal_id,
                    record.revision,
                    record.new_status,
                    record.record_id,
                    record.created_at.isoformat(),
                ),
            )
            self._inject("after_safety_pv_review_state")
            record_payload_hash = _payload_hash(record.model_dump(mode="json"))
            self._append_runtime_audit(
                connection,
                project_id=record.project_id,
                event_type="safety_pv_review_committed",
                operation=operation,
                actor=record.actor,
                detail={
                    "record_id": record.record_id,
                    "package_id": record.package_id,
                    "signal_id": record.signal_id,
                    "action": record.action.value,
                    "previous_status": record.previous_status,
                    "new_status": record.new_status,
                    "revision": record.revision,
                    "source_validation_bindings": [
                        item.model_dump(mode="json")
                        for item in record.source_validation_bindings
                    ],
                    "record_payload_hash": record_payload_hash,
                },
            )
            self._inject("after_safety_pv_review_audit")
            self._insert_idempotency(
                connection,
                record.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            self._inject("after_safety_pv_review_idempotency")
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(f"Safety/PV review conflict: {exc}") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def safety_review_records(
        self,
        project_id: str,
        package_id: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> List[SafetyReviewRecord]:
        clauses = ["tenant_id = ?", "project_id = ?"]
        params: List[Any] = [TENANT_PLACEHOLDER, project_id]
        if package_id:
            clauses.append("package_id = ?")
            params.append(package_id)
        if signal_id:
            clauses.append("signal_id = ?")
            params.append(signal_id)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT payload_json
                FROM safety_pv_review_records
                WHERE {' AND '.join(clauses)}
                ORDER BY package_id, signal_id, revision
                """,
                tuple(params),
            ).fetchall()
        records: List[SafetyReviewRecord] = []
        for row in rows:
            record = SafetyReviewRecord.model_validate(json.loads(row["payload_json"]))
            if record.previous_revision != record.revision - 1:
                record = record.model_copy(
                    update={"previous_revision": record.revision - 1}
                )
            records.append(record)
        return records

    def ensure_medical_writing_approval_gate(
        self,
        approval: ApprovalGate,
        previous_working_copy: MedicalWritingWorkingCopy,
        updated_working_copy: MedicalWritingWorkingCopy,
    ) -> ApprovalGate:
        if approval.project_id != previous_working_copy.project_id:
            raise ValueError("approval and working copy project ids must match")
        if approval.target_id != previous_working_copy.working_copy_id:
            raise ValueError("approval target must match working copy id")
        if approval.target_revision != previous_working_copy.revision:
            raise ValueError("approval target revision must match working copy revision")
        if updated_working_copy.approval_state != ApprovalState.IN_MEDICAL_REVIEW:
            raise ValueError("submitted working copy must enter medical review")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            gate_row = connection.execute(
                """
                SELECT payload_json FROM approval_gates
                WHERE tenant_id = ? AND project_id = ? AND approval_id = ?
                """,
                (TENANT_PLACEHOLDER, approval.project_id, approval.approval_id),
            ).fetchone()
            result = approval
            if gate_row is not None:
                existing = ApprovalGate.model_validate(json.loads(gate_row["payload_json"]))
                if (
                    existing.target_type != approval.target_type
                    or existing.target_id != approval.target_id
                    or existing.target_revision != approval.target_revision
                ):
                    raise RuntimeStoreError(
                        f"approval gate identity conflict: {approval.approval_id}"
                    )
                if existing.state != ApprovalState.IN_MEDICAL_REVIEW:
                    raise RuntimeStoreError(
                        "working copy approval was already decided; save a new revision before resubmission"
                    )
                result = existing

            working_copy_row = connection.execute(
                """
                SELECT payload_json FROM medical_writing_working_copies
                WHERE tenant_id = ? AND project_id = ? AND working_copy_id = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    approval.project_id,
                    previous_working_copy.working_copy_id,
                ),
            ).fetchone()
            if working_copy_row is None:
                raise KeyError(
                    f"working copy not found: {previous_working_copy.working_copy_id}"
                )
            stored_copy = MedicalWritingWorkingCopy.model_validate(
                json.loads(working_copy_row["payload_json"])
            )
            if stored_copy.revision != previous_working_copy.revision:
                raise StaleRuntimeStateError(
                    "medical writing working copy changed before approval submission"
                )
            if stored_copy.approval_state not in {
                ApprovalState.AI_DRAFT,
                ApprovalState.RETURNED_FOR_REVISION,
                ApprovalState.IN_MEDICAL_REVIEW,
            }:
                raise RuntimeStoreError(
                    f"working copy cannot enter review from: {stored_copy.approval_state.value}"
                )

            if gate_row is None:
                self._upsert_gate(connection, approval)
            if stored_copy.approval_state != ApprovalState.IN_MEDICAL_REVIEW:
                connection.execute(
                    """
                    UPDATE medical_writing_working_copies
                    SET approval_state = ?, updated_at = ?, payload_json = ?
                    WHERE tenant_id = ? AND project_id = ? AND working_copy_id = ?
                    """,
                    (
                        updated_working_copy.approval_state.value,
                        updated_working_copy.updated_at.isoformat(),
                        _canonical_json(updated_working_copy.model_dump(mode="json")),
                        TENANT_PLACEHOLDER,
                        approval.project_id,
                        updated_working_copy.working_copy_id,
                    ),
                )
                snapshot_id = f"snapshot_{approval.approval_id}"
                snapshot_exists = connection.execute(
                    """
                    SELECT 1 FROM medical_writing_working_copy_snapshots
                    WHERE tenant_id = ? AND project_id = ? AND snapshot_id = ?
                    """,
                    (TENANT_PLACEHOLDER, approval.project_id, snapshot_id),
                ).fetchone()
                if snapshot_exists is None:
                    self._insert_working_copy_snapshot(
                        connection,
                        updated_working_copy,
                        snapshot_id=snapshot_id,
                        snapshot_type="approval_submission",
                        audit_id=f"audit_{approval.approval_id}",
                    )
            if gate_row is None or stored_copy.approval_state != ApprovalState.IN_MEDICAL_REVIEW:
                self._append_runtime_audit(
                    connection,
                    project_id=approval.project_id,
                    event_type="medical_writing_approval_gate_created",
                    operation="medical_writing_approval_gate",
                    actor=approval.requested_by,
                    detail={
                        "approval_id": approval.approval_id,
                        "target_type": approval.target_type,
                        "target_id": approval.target_id,
                        "target_revision": approval.target_revision,
                        "working_copy_state": updated_working_copy.approval_state.value,
                    },
                )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_approval_action(
        self,
        approval: Optional[ApprovalGate],
        audit_event: AuditEvent,
        decision: ApprovalDecisionRecord,
        idempotency_key: Optional[str] = None,
        request_fingerprint: Optional[str] = None,
    ) -> RuntimeCommitResult:
        if audit_event.project_id != decision.project_id:
            raise ValueError("audit event and decision project ids must match")
        if approval is not None and approval.project_id != decision.project_id:
            raise ValueError("approval and decision project ids must match")
        operation = "approval_action"
        request_payload = {
            "approval": approval.model_dump(mode="json") if approval else None,
            "audit_event": audit_event.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
        }
        request_hash = request_fingerprint or _payload_hash(request_payload)
        key = idempotency_key or f"auto:{request_hash}"
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection, decision.project_id, operation, key, request_hash
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            if approval is not None:
                self._upsert_gate(connection, approval)
                self._inject("after_gate")
            connection.execute(
                """
                INSERT INTO approval_audit_events(
                    tenant_id, project_id, audit_id, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    audit_event.project_id,
                    audit_event.audit_id,
                    audit_event.created_at.isoformat(),
                    _canonical_json(audit_event.model_dump(mode="json")),
                ),
            )
            self._inject("after_audit")
            connection.execute(
                """
                INSERT INTO approval_decisions(
                    tenant_id, project_id, decision_id, approval_id, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    decision.project_id,
                    decision.decision_id,
                    decision.approval_id,
                    decision.created_at.isoformat(),
                    _canonical_json(decision.model_dump(mode="json")),
                ),
            )
            self._inject("after_decision")
            self._append_runtime_audit(
                connection,
                project_id=decision.project_id,
                event_type="approval_action_committed",
                operation=operation,
                actor=decision.actor,
                detail={
                    "approval_id": decision.approval_id,
                    "decision_id": decision.decision_id,
                    "audit_id": audit_event.audit_id,
                    "action": decision.action.value,
                    "blocked": decision.blocked,
                    "gate_updated": approval is not None,
                    "audit_payload_hash": _payload_hash(
                        audit_event.model_dump(mode="json")
                    ),
                    "decision_payload_hash": _payload_hash(
                        decision.model_dump(mode="json")
                    ),
                },
            )
            self._insert_idempotency(
                connection,
                decision.project_id,
                operation,
                key,
                request_hash,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_medical_writing_revision_submission(
        self,
        thread: RevisionThread,
        audit_event: AuditEvent,
        *,
        idempotency_key: Optional[str] = None,
        request_fingerprint: Optional[str] = None,
    ) -> RuntimeCommitResult:
        if thread.project_id != audit_event.project_id:
            raise ValueError("revision thread and audit event project ids must match")
        # WorkbenchModel permits in-memory assignment. Revalidate at the
        # submission boundary so a selected_text/selected_hash mismatch cannot
        # be persisted and only discovered after a cold restart.
        thread = RevisionThread.model_validate(thread.model_dump(mode="json"))
        operation = "medical_writing_revision_submission"
        request_payload = {
            "thread": thread.model_dump(mode="json"),
            "audit_event": audit_event.model_dump(mode="json"),
        }
        request_hash = request_fingerprint or _payload_hash(request_payload)
        key = idempotency_key or f"auto:{request_hash}"
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection, thread.project_id, operation, key, request_hash
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)
            connection.execute(
                """
                INSERT INTO medical_writing_revision_threads(
                    tenant_id, project_id, thread_id, document_id, section_id,
                    status, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    thread.project_id,
                    thread.thread_id,
                    thread.document_id,
                    thread.section_id,
                    thread.status,
                    thread.created_at.isoformat(),
                    _canonical_json(thread.model_dump(mode="json")),
                ),
            )
            self._inject("after_revision_thread")
            self._insert_revision_snapshot(connection, thread, audit_event.audit_id)
            self._inject("after_revision_snapshot")
            self._insert_workflow_audit(connection, audit_event, "medical_writing_revision")
            self._inject("after_workflow_audit")
            self._append_runtime_audit(
                connection,
                project_id=thread.project_id,
                event_type="medical_writing_revision_submitted",
                operation=operation,
                actor=audit_event.actor,
                detail={
                    "thread_id": thread.thread_id,
                    "thread_snapshot_id": audit_event.audit_id,
                    "audit_id": audit_event.audit_id,
                    "thread_payload_hash": _payload_hash(thread.model_dump(mode="json")),
                    "audit_payload_hash": _payload_hash(audit_event.model_dump(mode="json")),
                },
            )
            self._insert_idempotency(
                connection,
                thread.project_id,
                operation,
                key,
                request_hash,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(f"medical writing revision submission conflict: {exc}") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_medical_writing_revision_action(
        self,
        previous_thread: RevisionThread,
        updated_thread: RevisionThread,
        audit_event: AuditEvent,
        approval: Optional[ApprovalGate] = None,
        *,
        idempotency_key: Optional[str] = None,
        request_fingerprint: Optional[str] = None,
    ) -> RuntimeCommitResult:
        project_ids = {
            previous_thread.project_id,
            updated_thread.project_id,
            audit_event.project_id,
        }
        if approval is not None:
            project_ids.add(approval.project_id)
        if len(project_ids) != 1 or previous_thread.thread_id != updated_thread.thread_id:
            raise ValueError("revision action records must target one project and thread")
        # Service code mutates revision models in memory and WorkbenchModel does
        # not validate assignment. Revalidate at the persistence boundary so an
        # inconsistent adoption state can never be committed.
        previous_thread = RevisionThread.model_validate(
            previous_thread.model_dump(mode="json")
        )
        updated_thread = RevisionThread.model_validate(
            updated_thread.model_dump(mode="json")
        )
        operation = "medical_writing_revision_action"
        request_payload = {
            "previous_thread": previous_thread.model_dump(mode="json"),
            "updated_thread": updated_thread.model_dump(mode="json"),
            "audit_event": audit_event.model_dump(mode="json"),
            "approval": approval.model_dump(mode="json") if approval else None,
        }
        request_hash = request_fingerprint or _payload_hash(request_payload)
        key = idempotency_key or f"auto:{request_hash}"
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection, updated_thread.project_id, operation, key, request_hash
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)
            row = connection.execute(
                """
                SELECT payload_json
                FROM medical_writing_revision_threads
                WHERE tenant_id = ? AND project_id = ? AND thread_id = ?
                """,
                (TENANT_PLACEHOLDER, updated_thread.project_id, updated_thread.thread_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"revision thread not found: {updated_thread.thread_id}")
            expected_hash = _payload_hash(previous_thread.model_dump(mode="json"))
            # Older thread JSON legitimately lacks additive contract fields.
            # Normalize both sides through the current model before optimistic
            # concurrency comparison so defaults do not masquerade as a stale write.
            actual_thread = RevisionThread.model_validate(
                json.loads(row["payload_json"])
            )
            actual_hash = _payload_hash(actual_thread.model_dump(mode="json"))
            if actual_hash != expected_hash:
                connection.rollback()
                self._record_rejection(
                    updated_thread.project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=audit_event.actor,
                    detail={
                        "thread_id": updated_thread.thread_id,
                        "expected_payload_hash": expected_hash,
                        "actual_payload_hash": actual_hash,
                    },
                )
                raise StaleRuntimeStateError(
                    f"stale medical writing revision thread: {updated_thread.thread_id}"
                )
            if approval is not None:
                self._upsert_gate(connection, approval)
                self._inject("after_gate")
            connection.execute(
                """
                UPDATE medical_writing_revision_threads
                SET status = ?, updated_at = ?, payload_json = ?
                WHERE tenant_id = ? AND project_id = ? AND thread_id = ?
                """,
                (
                    updated_thread.status,
                    _utc_now().isoformat(),
                    _canonical_json(updated_thread.model_dump(mode="json")),
                    TENANT_PLACEHOLDER,
                    updated_thread.project_id,
                    updated_thread.thread_id,
                ),
            )
            self._inject("after_revision_thread")
            self._insert_revision_snapshot(connection, updated_thread, audit_event.audit_id)
            self._inject("after_revision_snapshot")
            self._insert_workflow_audit(connection, audit_event, "medical_writing_revision")
            self._inject("after_workflow_audit")
            self._append_runtime_audit(
                connection,
                project_id=updated_thread.project_id,
                event_type="medical_writing_revision_action_committed",
                operation=operation,
                actor=audit_event.actor,
                detail={
                    "thread_id": updated_thread.thread_id,
                    "thread_snapshot_id": audit_event.audit_id,
                    "audit_id": audit_event.audit_id,
                    "approval_id": approval.approval_id if approval else "",
                    "thread_payload_hash": _payload_hash(updated_thread.model_dump(mode="json")),
                    "audit_payload_hash": _payload_hash(audit_event.model_dump(mode="json")),
                },
            )
            self._insert_idempotency(
                connection,
                updated_thread.project_id,
                operation,
                key,
                request_hash,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_medical_writing_working_copy_save(
        self,
        working_copy: MedicalWritingWorkingCopy,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_fingerprint: str,
        operation: str = "medical_writing_working_copy_save",
        snapshot_type: str = "save",
        quarantine_previous: bool = False,
    ) -> RuntimeCommitResult:
        if working_copy.project_id != audit_event.project_id:
            raise ValueError("working copy and audit event project ids must match")
        if audit_event.target_id != working_copy.working_copy_id:
            raise ValueError("working copy audit target must match working copy id")
        if working_copy.revision != expected_revision + 1:
            raise ValueError("working copy revision must equal expected_revision + 1")
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection,
                working_copy.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            row = connection.execute(
                """
                SELECT working_copy_id, revision, payload_json
                FROM medical_writing_working_copies
                WHERE tenant_id = ? AND project_id = ? AND document_id = ? AND section_id = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    working_copy.project_id,
                    working_copy.document_id,
                    working_copy.section_id,
                ),
            ).fetchone()
            actual_revision = int(row["revision"]) if row is not None else 0
            if actual_revision != expected_revision:
                connection.rollback()
                self._record_rejection(
                    working_copy.project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=audit_event.actor,
                    detail={
                        "working_copy_id": working_copy.working_copy_id,
                        "document_id": working_copy.document_id,
                        "section_id": working_copy.section_id,
                        "expected_revision": expected_revision,
                        "actual_revision": actual_revision,
                    },
                )
                raise StaleRuntimeStateError(
                    f"stale medical writing working copy revision: expected={expected_revision}, actual={actual_revision}"
                )
            if row is not None and row["working_copy_id"] != working_copy.working_copy_id:
                raise RuntimeStoreError("working copy identity conflicts with existing section")

            if quarantine_previous and row is not None:
                previous = MedicalWritingWorkingCopy.model_validate(
                    json.loads(row["payload_json"])
                ).model_copy(
                    update={
                        "content_authority_state": "historical_quarantined",
                        "quarantined_revision": actual_revision,
                        "quarantine_reason": str(
                            audit_event.detail.get("quarantine_reason", "")
                        ),
                    },
                    deep=True,
                )
                self._insert_working_copy_snapshot(
                    connection,
                    previous,
                    snapshot_id=(
                        f"snapshot_{audit_event.audit_id}_quarantine_r{actual_revision}"
                    ),
                    snapshot_type="historical_quarantine",
                    audit_id=audit_event.audit_id,
                )
                self._inject("after_working_copy_quarantine_snapshot")

            connection.execute(
                """
                INSERT INTO medical_writing_working_copies(
                    tenant_id, project_id, working_copy_id, document_id, section_id,
                    revision, approval_state, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, project_id, document_id, section_id) DO UPDATE SET
                    revision = excluded.revision,
                    approval_state = excluded.approval_state,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (
                    TENANT_PLACEHOLDER,
                    working_copy.project_id,
                    working_copy.working_copy_id,
                    working_copy.document_id,
                    working_copy.section_id,
                    working_copy.revision,
                    working_copy.approval_state.value,
                    working_copy.updated_at.isoformat(),
                    _canonical_json(working_copy.model_dump(mode="json")),
                ),
            )
            self._inject("after_working_copy")
            snapshot_id = f"snapshot_{audit_event.audit_id}"
            self._insert_working_copy_snapshot(
                connection,
                working_copy,
                snapshot_id=snapshot_id,
                snapshot_type=snapshot_type,
                audit_id=audit_event.audit_id,
            )
            self._inject("after_working_copy_snapshot")
            self._insert_workflow_audit(
                connection,
                audit_event,
                "medical_writing_working_copy",
            )
            self._inject("after_workflow_audit")
            self._append_runtime_audit(
                connection,
                project_id=working_copy.project_id,
                event_type=audit_event.action,
                operation=operation,
                actor=audit_event.actor,
                detail={
                    "working_copy_id": working_copy.working_copy_id,
                    "revision": working_copy.revision,
                    "working_copy_snapshot_id": snapshot_id,
                    "working_copy_payload_hash": _payload_hash(
                        working_copy.model_dump(mode="json")
                    ),
                    "audit_id": audit_event.audit_id,
                    "audit_payload_hash": _payload_hash(
                        audit_event.model_dump(mode="json")
                    ),
                },
            )
            self._insert_idempotency(
                connection,
                working_copy.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(f"medical writing working copy save conflict: {exc}") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_medical_writing_atomic_accept_and_apply(
        self,
        *,
        previous_thread: RevisionThread,
        updated_thread: RevisionThread,
        accept_audit_event: AuditEvent,
        previous_working_copy: MedicalWritingWorkingCopy,
        updated_working_copy: MedicalWritingWorkingCopy,
        apply_audit_event: AuditEvent,
        expected_working_copy_revision: int,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> RuntimeCommitResult:
        """Atomically commit candidate acceptance and working-copy application.

        All effects persist in one ``BEGIN IMMEDIATE`` transaction:
        revision-thread CAS update, accept audit + snapshot, working-copy CAS
        upsert + snapshot, apply audit, runtime audit chain, and idempotency
        record.  Any validation failure or injected exception before COMMIT
        rolls back **all** of them, leaving thread and working copy in their
        pre-action state.
        """
        if previous_thread.project_id != updated_thread.project_id:
            raise ValueError("thread project ids must match")
        if updated_thread.project_id != accept_audit_event.project_id:
            raise ValueError("accept audit project must match thread project")
        if updated_working_copy.project_id != updated_thread.project_id:
            raise ValueError("working copy project must match thread project")
        if apply_audit_event.project_id != updated_thread.project_id:
            raise ValueError("apply audit project must match thread project")
        if previous_thread.thread_id != updated_thread.thread_id:
            raise ValueError("thread ids must match")
        if updated_working_copy.revision != expected_working_copy_revision + 1:
            raise ValueError(
                "working copy revision must equal expected_working_copy_revision + 1"
            )

        # Revalidate models at the persistence boundary.
        previous_thread = RevisionThread.model_validate(
            previous_thread.model_dump(mode="json")
        )
        updated_thread = RevisionThread.model_validate(
            updated_thread.model_dump(mode="json")
        )
        previous_working_copy = MedicalWritingWorkingCopy.model_validate(
            previous_working_copy.model_dump(mode="json")
        )
        updated_working_copy = MedicalWritingWorkingCopy.model_validate(
            updated_working_copy.model_dump(mode="json")
        )

        operation = "medical_writing_atomic_accept_and_apply"
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")

            # --- Idempotency replay (shared key) ---
            replay = self._idempotency_result(
                connection,
                updated_thread.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            # --- CAS: revision thread ---
            self._inject("atomic_before_thread_read")
            thread_row = connection.execute(
                """
                SELECT payload_json
                FROM medical_writing_revision_threads
                WHERE tenant_id = ? AND project_id = ? AND thread_id = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    updated_thread.project_id,
                    updated_thread.thread_id,
                ),
            ).fetchone()
            if thread_row is None:
                raise KeyError(
                    f"revision thread not found: {updated_thread.thread_id}"
                )
            expected_thread_hash = _payload_hash(
                previous_thread.model_dump(mode="json")
            )
            actual_thread = RevisionThread.model_validate(
                json.loads(thread_row["payload_json"])
            )
            actual_thread_hash = _payload_hash(
                actual_thread.model_dump(mode="json")
            )
            if actual_thread_hash != expected_thread_hash:
                connection.rollback()
                self._record_rejection(
                    updated_thread.project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=accept_audit_event.actor,
                    detail={
                        "thread_id": updated_thread.thread_id,
                        "expected_payload_hash": expected_thread_hash,
                        "actual_payload_hash": actual_thread_hash,
                    },
                )
                raise StaleRuntimeStateError(
                    f"stale medical writing revision thread: "
                    f"{updated_thread.thread_id}"
                )
            self._inject("atomic_after_thread_cas_check")

            # --- CAS: working copy ---
            wc_row = connection.execute(
                """
                SELECT working_copy_id, revision, payload_json
                FROM medical_writing_working_copies
                WHERE tenant_id = ? AND project_id = ? AND document_id = ? AND section_id = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    updated_working_copy.project_id,
                    updated_working_copy.document_id,
                    updated_working_copy.section_id,
                ),
            ).fetchone()
            actual_wc_revision = int(wc_row["revision"]) if wc_row is not None else 0
            if actual_wc_revision != expected_working_copy_revision:
                connection.rollback()
                self._record_rejection(
                    updated_working_copy.project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=apply_audit_event.actor,
                    detail={
                        "working_copy_id": updated_working_copy.working_copy_id,
                        "section_id": updated_working_copy.section_id,
                        "expected_revision": expected_working_copy_revision,
                        "actual_revision": actual_wc_revision,
                    },
                )
                raise StaleRuntimeStateError(
                    f"stale medical writing working copy revision: "
                    f"expected={expected_working_copy_revision}, "
                    f"actual={actual_wc_revision}"
                )
            if wc_row is not None and (
                wc_row["working_copy_id"] != updated_working_copy.working_copy_id
            ):
                raise RuntimeStoreError(
                    "working copy identity conflicts with existing section"
                )
            self._inject("atomic_after_wc_cas_check")

            # --- Write: revision thread update ---
            connection.execute(
                """
                UPDATE medical_writing_revision_threads
                SET status = ?, updated_at = ?, payload_json = ?
                WHERE tenant_id = ? AND project_id = ? AND thread_id = ?
                """,
                (
                    updated_thread.status,
                    _utc_now().isoformat(),
                    _canonical_json(updated_thread.model_dump(mode="json")),
                    TENANT_PLACEHOLDER,
                    updated_thread.project_id,
                    updated_thread.thread_id,
                ),
            )
            self._inject("atomic_after_thread_write")

            # --- Write: accept audit + revision snapshot ---
            self._insert_revision_snapshot(
                connection, updated_thread, accept_audit_event.audit_id
            )
            self._inject("atomic_after_thread_snapshot")
            self._insert_workflow_audit(
                connection, accept_audit_event, "medical_writing_revision"
            )
            self._inject("atomic_after_accept_audit")

            # --- Write: working copy upsert ---
            connection.execute(
                """
                INSERT INTO medical_writing_working_copies(
                    tenant_id, project_id, working_copy_id, document_id, section_id,
                    revision, approval_state, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, project_id, document_id, section_id) DO UPDATE SET
                    revision = excluded.revision,
                    approval_state = excluded.approval_state,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (
                    TENANT_PLACEHOLDER,
                    updated_working_copy.project_id,
                    updated_working_copy.working_copy_id,
                    updated_working_copy.document_id,
                    updated_working_copy.section_id,
                    updated_working_copy.revision,
                    updated_working_copy.approval_state.value,
                    updated_working_copy.updated_at.isoformat(),
                    _canonical_json(
                        updated_working_copy.model_dump(mode="json")
                    ),
                ),
            )
            self._inject("atomic_after_wc_write")

            # --- Write: working copy snapshot ---
            wc_snapshot_id = f"snapshot_{apply_audit_event.audit_id}"
            self._insert_working_copy_snapshot(
                connection,
                updated_working_copy,
                snapshot_id=wc_snapshot_id,
                snapshot_type="apply_approved_ai_revision",
                audit_id=apply_audit_event.audit_id,
            )
            self._inject("atomic_after_wc_snapshot")

            # --- Write: apply audit ---
            self._insert_workflow_audit(
                connection,
                apply_audit_event,
                "medical_writing_working_copy",
            )
            self._inject("atomic_after_apply_audit")

            # --- Runtime audit chain entries ---
            self._append_runtime_audit(
                connection,
                project_id=updated_thread.project_id,
                event_type="medical_writing_revision_action_committed",
                operation=operation,
                actor=accept_audit_event.actor,
                detail={
                    "thread_id": updated_thread.thread_id,
                    "thread_snapshot_id": accept_audit_event.audit_id,
                    "audit_id": accept_audit_event.audit_id,
                    "approval_id": "",
                    "thread_payload_hash": _payload_hash(
                        updated_thread.model_dump(mode="json")
                    ),
                },
            )
            self._inject("atomic_after_thread_runtime_audit")

            self._append_runtime_audit(
                connection,
                project_id=updated_working_copy.project_id,
                event_type=apply_audit_event.action,
                operation=operation,
                actor=apply_audit_event.actor,
                detail={
                    "working_copy_id": updated_working_copy.working_copy_id,
                    "revision": updated_working_copy.revision,
                    "working_copy_snapshot_id": wc_snapshot_id,
                    "working_copy_payload_hash": _payload_hash(
                        updated_working_copy.model_dump(mode="json")
                    ),
                    "audit_id": apply_audit_event.audit_id,
                },
            )
            self._inject("atomic_after_wc_runtime_audit")

            # --- Idempotency record ---
            self._insert_idempotency(
                connection,
                updated_thread.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            self._inject("atomic_after_idempotency")

            connection.commit()
            self._inject("atomic_after_commit")
            return RuntimeCommitResult(request_id=request_id)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_medical_writing_section_freeze(
        self,
        previous_working_copy: MedicalWritingWorkingCopy,
        updated_working_copy: MedicalWritingWorkingCopy,
        audit_event: AuditEvent,
        *,
        snapshot_id: str,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> RuntimeCommitResult:
        if action not in {"freeze_current_version", "unfreeze"}:
            raise ValueError("unsupported medical writing section freeze action")
        if (
            previous_working_copy.project_id != updated_working_copy.project_id
            or previous_working_copy.project_id != audit_event.project_id
            or previous_working_copy.working_copy_id
            != updated_working_copy.working_copy_id
            or previous_working_copy.document_id != updated_working_copy.document_id
            or previous_working_copy.section_id != updated_working_copy.section_id
        ):
            raise ValueError("section freeze records must target one working copy")
        if previous_working_copy.revision != updated_working_copy.revision:
            raise ValueError("section freeze metadata must not change content revision")
        if previous_working_copy.content_blocks != updated_working_copy.content_blocks:
            raise ValueError("section freeze metadata must not change chapter content")
        if action == "freeze_current_version":
            if (
                updated_working_copy.freeze_status != "frozen"
                or updated_working_copy.frozen_revision
                != updated_working_copy.revision
                or updated_working_copy.frozen_snapshot_id != snapshot_id
                or not snapshot_id
            ):
                raise ValueError("section freeze target metadata is incomplete")
        elif snapshot_id or updated_working_copy.freeze_status != "editable":
            raise ValueError("section unfreeze must clear the active freeze metadata")

        operation = (
            "medical_writing_section_freeze"
            if action == "freeze_current_version"
            else "medical_writing_section_unfreeze"
        )
        project_id = updated_working_copy.project_id
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            row = connection.execute(
                """
                SELECT payload_json FROM medical_writing_working_copies
                WHERE tenant_id = ? AND project_id = ? AND working_copy_id = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    previous_working_copy.working_copy_id,
                ),
            ).fetchone()
            if row is None:
                raise KeyError(previous_working_copy.working_copy_id)
            stored_copy = MedicalWritingWorkingCopy.model_validate(
                json.loads(row["payload_json"])
            )
            if _payload_hash(stored_copy.model_dump(mode="json")) != _payload_hash(
                previous_working_copy.model_dump(mode="json")
            ):
                raise StaleRuntimeStateError(
                    "working copy changed before section freeze metadata was committed"
                )

            connection.execute(
                """
                UPDATE medical_writing_working_copies
                SET approval_state = ?, updated_at = ?, payload_json = ?
                WHERE tenant_id = ? AND project_id = ? AND working_copy_id = ?
                """,
                (
                    ApprovalState.AI_DRAFT.value,
                    updated_working_copy.updated_at.isoformat(),
                    _canonical_json(updated_working_copy.model_dump(mode="json")),
                    TENANT_PLACEHOLDER,
                    project_id,
                    updated_working_copy.working_copy_id,
                ),
            )
            self._inject("after_section_freeze_working_copy")

            if action == "freeze_current_version":
                self._insert_working_copy_snapshot(
                    connection,
                    updated_working_copy,
                    snapshot_id=snapshot_id,
                    snapshot_type="author_freeze",
                    audit_id=audit_event.audit_id,
                )
                self._inject("after_section_freeze_snapshot")

            retired_gate_ids: list[str] = []
            gate_rows = connection.execute(
                """
                SELECT payload_json FROM approval_gates
                WHERE tenant_id = ? AND project_id = ?
                """,
                (TENANT_PLACEHOLDER, project_id),
            ).fetchall()
            for gate_row in gate_rows:
                gate = ApprovalGate.model_validate(json.loads(gate_row["payload_json"]))
                if (
                    gate.target_type
                    not in {
                        "medical_writing_revision_thread",
                        "medical_writing_working_copy",
                    }
                    or gate.state in {ApprovalState.SUPERSEDED, ApprovalState.ARCHIVED}
                ):
                    continue
                retired = gate.model_copy(
                    update={
                        "state": ApprovalState.SUPERSEDED,
                        "approved_by": None,
                        "reviewed_by": audit_event.actor,
                        "review_comments": (
                            (gate.review_comments + "\n") if gate.review_comments else ""
                        )
                        + "医学写作同角色审批流程已停用；历史记录保留审计，当前章节改用作者版本冻结。",
                        "updated_at": audit_event.created_at,
                    },
                    deep=True,
                )
                self._upsert_gate(connection, retired)
                retired_gate_ids.append(gate.approval_id)
            self._inject("after_section_freeze_legacy_gate_retirement")

            self._insert_workflow_audit(
                connection,
                audit_event,
                "medical_writing_section_freeze",
            )
            self._inject("after_section_freeze_audit")
            self._append_runtime_audit(
                connection,
                project_id=project_id,
                event_type="medical_writing_section_freeze_committed",
                operation=operation,
                actor=audit_event.actor,
                detail={
                    "action": action,
                    "audit_id": audit_event.audit_id,
                    "working_copy_id": updated_working_copy.working_copy_id,
                    "working_copy_revision": updated_working_copy.revision,
                    "working_copy_payload_hash": _payload_hash(
                        updated_working_copy.model_dump(mode="json")
                    ),
                    "snapshot_id": snapshot_id,
                    "snapshot_payload_hash": (
                        _payload_hash(updated_working_copy.model_dump(mode="json"))
                        if snapshot_id
                        else ""
                    ),
                    "retired_legacy_approval_ids": retired_gate_ids,
                    "audit_payload_hash": _payload_hash(
                        audit_event.model_dump(mode="json")
                    ),
                },
            )
            self._inject("after_section_freeze_runtime_audit")
            self._insert_idempotency(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(
                f"medical writing section freeze conflict: {exc}"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_medical_writing_study_rebind_reset(
        self,
        previous_working_copies: List[MedicalWritingWorkingCopy],
        updated_working_copies: List[MedicalWritingWorkingCopy],
        audit_event: AuditEvent,
        *,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> RuntimeCommitResult:
        if len(previous_working_copies) != len(updated_working_copies):
            raise ValueError("study rebind working-copy pairs must have equal length")
        previous_by_id = {item.working_copy_id: item for item in previous_working_copies}
        updated_by_id = {item.working_copy_id: item for item in updated_working_copies}
        if set(previous_by_id) != set(updated_by_id):
            raise ValueError("study rebind working-copy identities must match")
        if any(item.project_id != audit_event.project_id for item in previous_working_copies):
            raise ValueError("study rebind working copies must target one project")
        operation = "medical_writing_study_definition_rebind_reset"
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection,
                audit_event.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            reset_snapshot_ids = []
            for index, previous in enumerate(previous_working_copies, start=1):
                updated = updated_by_id[previous.working_copy_id]
                if updated.revision != previous.revision + 1:
                    raise ValueError("study rebind must advance each working-copy revision")
                if updated.content_blocks != previous.content_blocks:
                    raise ValueError("study rebind must preserve working-copy content")
                row = connection.execute(
                    """
                    SELECT payload_json FROM medical_writing_working_copies
                    WHERE tenant_id = ? AND project_id = ? AND working_copy_id = ?
                    """,
                    (TENANT_PLACEHOLDER, audit_event.project_id, previous.working_copy_id),
                ).fetchone()
                if row is None:
                    raise KeyError(previous.working_copy_id)
                stored_previous = MedicalWritingWorkingCopy.model_validate(
                    json.loads(row["payload_json"])
                )
                if _payload_hash(
                    stored_previous.model_dump(mode="json")
                ) != _payload_hash(previous.model_dump(mode="json")):
                    raise StaleRuntimeStateError(
                        f"stale medical writing working copy during study rebind: {previous.working_copy_id}"
                    )
                connection.execute(
                    """
                    UPDATE medical_writing_working_copies
                    SET revision = ?, approval_state = ?, updated_at = ?, payload_json = ?
                    WHERE tenant_id = ? AND project_id = ? AND working_copy_id = ?
                    """,
                    (
                        updated.revision,
                        updated.approval_state.value,
                        updated.updated_at.isoformat(),
                        _canonical_json(updated.model_dump(mode="json")),
                        TENANT_PLACEHOLDER,
                        audit_event.project_id,
                        updated.working_copy_id,
                    ),
                )
                self._inject("after_study_rebind_working_copy")
                snapshot_id = f"snapshot_{audit_event.audit_id}_{index}"
                self._insert_working_copy_snapshot(
                    connection,
                    updated,
                    snapshot_id=snapshot_id,
                    snapshot_type="study_definition_rebind",
                    audit_id=audit_event.audit_id,
                )
                self._inject("after_study_rebind_snapshot")
                reset_snapshot_ids.append(snapshot_id)

            gates = connection.execute(
                """
                SELECT payload_json FROM approval_gates
                WHERE tenant_id = ? AND project_id = ?
                """,
                (TENANT_PLACEHOLDER, audit_event.project_id),
            ).fetchall()
            superseded_approval_ids = []
            for row in gates:
                gate = ApprovalGate.model_validate(json.loads(row["payload_json"]))
                if (
                    gate.target_type != "medical_writing_working_copy"
                    or gate.target_id not in updated_by_id
                    or gate.state in {ApprovalState.SUPERSEDED, ApprovalState.ARCHIVED}
                ):
                    continue
                updated_gate = gate.model_copy(
                    update={
                        "state": ApprovalState.SUPERSEDED,
                        "approved_by": None,
                        "reviewed_by": audit_event.actor,
                        "review_comments": (
                            (gate.review_comments + "\n") if gate.review_comments else ""
                        )
                        + "StudyDefinition更新后，该审批仅保留为历史记录；受影响章节须重新发起医学审阅。",
                        "updated_at": audit_event.created_at,
                    },
                    deep=True,
                )
                self._upsert_gate(connection, updated_gate)
                self._inject("after_study_rebind_gate")
                superseded_approval_ids.append(gate.approval_id)

            self._insert_workflow_audit(
                connection,
                audit_event,
                "medical_writing_study_definition_rebind",
            )
            self._inject("after_study_rebind_workflow_audit")
            self._append_runtime_audit(
                connection,
                project_id=audit_event.project_id,
                event_type=audit_event.action,
                operation=operation,
                actor=audit_event.actor,
                detail={
                    "audit_id": audit_event.audit_id,
                    "working_copy_ids": sorted(updated_by_id),
                    "snapshot_ids": reset_snapshot_ids,
                    "superseded_approval_ids": superseded_approval_ids,
                    "audit_payload_hash": _payload_hash(
                        audit_event.model_dump(mode="json")
                    ),
                },
            )
            self._insert_idempotency(
                connection,
                audit_event.project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(
                f"medical writing study-definition rebind conflict: {exc}"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_medical_writing_approval_action(
        self,
        approval: Optional[ApprovalGate],
        audit_event: AuditEvent,
        decision: ApprovalDecisionRecord,
        *,
        previous_thread: Optional[RevisionThread] = None,
        updated_thread: Optional[RevisionThread] = None,
        previous_working_copy: Optional[MedicalWritingWorkingCopy] = None,
        updated_working_copy: Optional[MedicalWritingWorkingCopy] = None,
        target_snapshot_id: str = "",
        idempotency_key: str,
        request_fingerprint: str,
    ) -> RuntimeCommitResult:
        records = [audit_event.project_id, decision.project_id]
        if approval is not None:
            records.append(approval.project_id)
        for target in (
            previous_thread,
            updated_thread,
            previous_working_copy,
            updated_working_copy,
        ):
            if target is not None:
                records.append(target.project_id)
        if len(set(records)) != 1:
            raise ValueError("medical writing approval records must target one project")
        if (previous_thread is None) != (updated_thread is None):
            raise ValueError("thread approval requires previous and updated thread states")
        if (previous_working_copy is None) != (updated_working_copy is None):
            raise ValueError("working copy approval requires previous and updated states")
        if previous_thread is not None and previous_working_copy is not None:
            raise ValueError("one approval transaction may update only one target type")
        if previous_thread is not None and updated_thread is not None:
            # Normalize additive thread fields (including selected_hash) before
            # the transaction so legacy JSON and current callers share one CAS
            # payload shape without rewriting the old immutable row.
            previous_thread = RevisionThread.model_validate(
                previous_thread.model_dump(mode="json")
            )
            updated_thread = RevisionThread.model_validate(
                updated_thread.model_dump(mode="json")
            )
        operation = "medical_writing_final_approval"
        project_id = decision.project_id
        request_id = f"req_{uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotency_result(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                connection.rollback()
                return RuntimeCommitResult(request_id=replay, replayed=True)

            gate_row = connection.execute(
                """
                SELECT payload_json FROM approval_gates
                WHERE tenant_id = ? AND project_id = ? AND approval_id = ?
                """,
                (TENANT_PLACEHOLDER, project_id, decision.approval_id),
            ).fetchone()
            if gate_row is None:
                raise KeyError(f"approval not found: {project_id}/{decision.approval_id}")
            stored_gate = ApprovalGate.model_validate(json.loads(gate_row["payload_json"]))
            if stored_gate.state != decision.previous_state:
                connection.rollback()
                self._record_rejection(
                    project_id,
                    event_type="stale_write_rejected",
                    operation=operation,
                    actor=decision.actor,
                    detail={
                        "approval_id": decision.approval_id,
                        "expected_state": decision.previous_state.value,
                        "actual_state": stored_gate.state.value,
                    },
                )
                raise StaleRuntimeStateError(
                    f"stale medical writing approval state: expected={decision.previous_state.value}, actual={stored_gate.state.value}"
                )

            if approval is not None:
                self._upsert_gate(connection, approval)
                self._inject("after_gate")

            target_snapshot_table = ""
            target_snapshot_hash = ""
            if previous_thread is not None and updated_thread is not None:
                row = connection.execute(
                    """
                    SELECT payload_json FROM medical_writing_revision_threads
                    WHERE tenant_id = ? AND project_id = ? AND thread_id = ?
                    """,
                    (TENANT_PLACEHOLDER, project_id, previous_thread.thread_id),
                ).fetchone()
                if row is None:
                    raise KeyError(f"revision thread not found: {previous_thread.thread_id}")
                actual_thread = RevisionThread.model_validate(
                    json.loads(row["payload_json"])
                )
                if _payload_hash(actual_thread.model_dump(mode="json")) != _payload_hash(
                    previous_thread.model_dump(mode="json")
                ):
                    raise StaleRuntimeStateError(
                        f"stale medical writing revision thread: {previous_thread.thread_id}"
                    )
                connection.execute(
                    """
                    UPDATE medical_writing_revision_threads
                    SET status = ?, updated_at = ?, payload_json = ?
                    WHERE tenant_id = ? AND project_id = ? AND thread_id = ?
                    """,
                    (
                        updated_thread.status,
                        _utc_now().isoformat(),
                        _canonical_json(updated_thread.model_dump(mode="json")),
                        TENANT_PLACEHOLDER,
                        project_id,
                        updated_thread.thread_id,
                    ),
                )
                self._inject("after_revision_thread")
                self._insert_revision_snapshot(
                    connection,
                    updated_thread,
                    target_snapshot_id,
                )
                target_snapshot_table = "medical_writing_revision_snapshots"
                target_snapshot_hash = _payload_hash(updated_thread.model_dump(mode="json"))
                self._inject("after_target_snapshot")
            elif previous_working_copy is not None and updated_working_copy is not None:
                row = connection.execute(
                    """
                    SELECT payload_json FROM medical_writing_working_copies
                    WHERE tenant_id = ? AND project_id = ? AND working_copy_id = ?
                    """,
                    (TENANT_PLACEHOLDER, project_id, previous_working_copy.working_copy_id),
                ).fetchone()
                if row is None:
                    raise KeyError(
                        f"working copy not found: {previous_working_copy.working_copy_id}"
                    )
                stored_previous = MedicalWritingWorkingCopy.model_validate(
                    json.loads(row["payload_json"])
                )
                if _payload_hash(
                    stored_previous.model_dump(mode="json")
                ) != _payload_hash(previous_working_copy.model_dump(mode="json")):
                    raise StaleRuntimeStateError(
                        f"stale medical writing working copy: {previous_working_copy.working_copy_id}"
                    )
                connection.execute(
                    """
                    UPDATE medical_writing_working_copies
                    SET approval_state = ?, updated_at = ?, payload_json = ?
                    WHERE tenant_id = ? AND project_id = ? AND working_copy_id = ?
                    """,
                    (
                        updated_working_copy.approval_state.value,
                        updated_working_copy.updated_at.isoformat(),
                        _canonical_json(updated_working_copy.model_dump(mode="json")),
                        TENANT_PLACEHOLDER,
                        project_id,
                        updated_working_copy.working_copy_id,
                    ),
                )
                self._inject("after_working_copy")
                self._insert_working_copy_snapshot(
                    connection,
                    updated_working_copy,
                    snapshot_id=target_snapshot_id,
                    snapshot_type="approval",
                    audit_id=audit_event.audit_id,
                )
                target_snapshot_table = "medical_writing_working_copy_snapshots"
                target_snapshot_hash = _payload_hash(
                    updated_working_copy.model_dump(mode="json")
                )
                self._inject("after_target_snapshot")

            connection.execute(
                """
                INSERT INTO approval_audit_events(
                    tenant_id, project_id, audit_id, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    audit_event.audit_id,
                    audit_event.created_at.isoformat(),
                    _canonical_json(audit_event.model_dump(mode="json")),
                ),
            )
            self._inject("after_audit")
            connection.execute(
                """
                INSERT INTO approval_decisions(
                    tenant_id, project_id, decision_id, approval_id, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    decision.decision_id,
                    decision.approval_id,
                    decision.created_at.isoformat(),
                    _canonical_json(decision.model_dump(mode="json")),
                ),
            )
            self._inject("after_decision")
            self._insert_workflow_audit(
                connection,
                audit_event,
                "medical_writing_final_approval",
            )
            self._inject("after_workflow_audit")
            self._append_runtime_audit(
                connection,
                project_id=project_id,
                event_type="medical_writing_final_approval_committed",
                operation=operation,
                actor=decision.actor,
                detail={
                    "approval_id": decision.approval_id,
                    "decision_id": decision.decision_id,
                    "audit_id": audit_event.audit_id,
                    "action": decision.action.value,
                    "blocked": decision.blocked,
                    "target_type": stored_gate.target_type,
                    "target_id": stored_gate.target_id,
                    "target_revision": stored_gate.target_revision,
                    "target_snapshot_table": target_snapshot_table,
                    "target_snapshot_id": target_snapshot_id,
                    "target_snapshot_hash": target_snapshot_hash,
                    "audit_payload_hash": _payload_hash(
                        audit_event.model_dump(mode="json")
                    ),
                    "decision_payload_hash": _payload_hash(
                        decision.model_dump(mode="json")
                    ),
                },
            )
            self._insert_idempotency(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
                request_id,
            )
            connection.commit()
            return RuntimeCommitResult(request_id=request_id)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeStoreError(f"medical writing approval conflict: {exc}") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _insert_workflow_audit(
        self,
        connection: sqlite3.Connection,
        event: AuditEvent,
        workflow_type: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO workflow_audit_events(
                tenant_id, project_id, audit_id, workflow_type, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_PLACEHOLDER,
                event.project_id,
                event.audit_id,
                workflow_type,
                event.created_at.isoformat(),
                _canonical_json(event.model_dump(mode="json")),
            ),
        )

    def _insert_revision_snapshot(
        self,
        connection: sqlite3.Connection,
        thread: RevisionThread,
        snapshot_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO medical_writing_revision_snapshots(
                tenant_id, project_id, snapshot_id, thread_id, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_PLACEHOLDER,
                thread.project_id,
                snapshot_id,
                thread.thread_id,
                _utc_now().isoformat(),
                _canonical_json(thread.model_dump(mode="json")),
            ),
        )

    def _insert_working_copy_snapshot(
        self,
        connection: sqlite3.Connection,
        working_copy: MedicalWritingWorkingCopy,
        *,
        snapshot_id: str,
        snapshot_type: str,
        audit_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO medical_writing_working_copy_snapshots(
                tenant_id, project_id, snapshot_id, working_copy_id, revision,
                snapshot_type, audit_id, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_PLACEHOLDER,
                working_copy.project_id,
                snapshot_id,
                working_copy.working_copy_id,
                working_copy.revision,
                snapshot_type,
                audit_id,
                _utc_now().isoformat(),
                _canonical_json(working_copy.model_dump(mode="json")),
            ),
        )

    def _insert_evidence_picos_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        snapshot_id: str,
        project_id: str,
        package_id: str,
        working_state_id: str,
        revision: int,
        snapshot_type: str,
        approval_id: str,
        audit_id: str,
        created_at: datetime,
        payload: Dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO evidence_picos_working_state_snapshots(
                tenant_id, project_id, snapshot_id, package_id, working_state_id,
                revision, snapshot_type, approval_id, audit_id, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_PLACEHOLDER,
                project_id,
                snapshot_id,
                package_id,
                working_state_id,
                revision,
                snapshot_type,
                approval_id,
                audit_id,
                created_at.isoformat(),
                _canonical_json(payload),
            ),
        )

    def _insert_evidence_ai_revision_snapshot(
        self,
        connection: sqlite3.Connection,
        thread: EvidenceAiRevisionThread,
        *,
        snapshot_id: str,
        action: str,
        audit_id: str,
        created_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO evidence_ai_revision_snapshots(
                tenant_id, project_id, snapshot_id, thread_id, package_id,
                revision, action, audit_id, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_PLACEHOLDER,
                thread.project_id,
                snapshot_id,
                thread.thread_id,
                thread.package_id,
                thread.revision,
                action,
                audit_id,
                created_at.isoformat(),
                _canonical_json(thread.model_dump(mode="json")),
            ),
        )

    def _upsert_gate(self, connection: sqlite3.Connection, approval: ApprovalGate) -> None:
        connection.execute(
            """
            INSERT INTO approval_gates(tenant_id, project_id, approval_id, updated_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, project_id, approval_id) DO UPDATE SET
                updated_at=excluded.updated_at,
                payload_json=excluded.payload_json
            """,
            (
                TENANT_PLACEHOLDER,
                approval.project_id,
                approval.approval_id,
                approval.updated_at.isoformat(),
                _canonical_json(approval.model_dump(mode="json")),
            ),
        )

    def _latest_disposition_state(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        item_id: str,
        source_version: str,
    ) -> str:
        row = connection.execute(
            """
            SELECT new_state
            FROM rux_disposition_records
            WHERE tenant_id = ? AND project_id = ? AND item_id = ? AND source_version = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (TENANT_PLACEHOLDER, project_id, item_id, source_version),
        ).fetchone()
        return str(row["new_state"]) if row is not None else "pending_review"

    def _idempotency_result(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        operation: str,
        key: str,
        request_hash: str,
    ) -> Optional[str]:
        row = connection.execute(
            """
            SELECT request_hash, request_id
            FROM idempotency_records
            WHERE tenant_id = ? AND project_id = ? AND operation = ? AND idempotency_key = ?
            """,
            (TENANT_PLACEHOLDER, project_id, operation, key),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise IdempotencyConflictError(
                f"idempotency key reused with different payload: {project_id}/{operation}/{key}"
            )
        return str(row["request_id"])

    def _insert_idempotency(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        operation: str,
        key: str,
        request_hash: str,
        request_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO idempotency_records(
                tenant_id, project_id, operation, idempotency_key,
                request_hash, request_id, result_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_PLACEHOLDER,
                project_id,
                operation,
                key,
                request_hash,
                request_id,
                _canonical_json({"request_id": request_id}),
                _utc_now().isoformat(),
            ),
        )

    def _record_rejection(
        self,
        project_id: str,
        *,
        event_type: str,
        operation: str,
        actor: str,
        detail: Dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._append_runtime_audit(
                connection,
                project_id=project_id,
                event_type=event_type,
                operation=operation,
                actor=actor,
                detail=detail,
            )
            connection.commit()

    def record_rejection(
        self,
        project_id: str,
        *,
        event_type: str,
        operation: str,
        actor: str,
        detail: Dict[str, Any],
    ) -> None:
        self._record_rejection(
            project_id,
            event_type=event_type,
            operation=operation,
            actor=actor,
            detail=detail,
        )

    def _append_runtime_audit(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        event_type: str,
        operation: str,
        actor: str,
        detail: Dict[str, Any],
    ) -> None:
        previous = connection.execute(
            """
            SELECT sequence_no, event_hash
            FROM runtime_audit_chain
            WHERE tenant_id = ? AND project_id = ?
            ORDER BY sequence_no DESC
            LIMIT 1
            """,
            (TENANT_PLACEHOLDER, project_id),
        ).fetchone()
        sequence_no = int(previous["sequence_no"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else ""
        created_at = _utc_now().isoformat()
        event_id = f"runtime_event_{uuid4().hex}"
        event_body = {
            "tenant_id": TENANT_PLACEHOLDER,
            "project_id": project_id,
            "sequence_no": sequence_no,
            "event_id": event_id,
            "event_type": event_type,
            "operation": operation,
            "actor": actor,
            "identity_assurance": IDENTITY_ASSURANCE,
            "detail": detail,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
        event_hash = _payload_hash(event_body)
        connection.execute(
            """
            INSERT INTO runtime_audit_chain(
                tenant_id, project_id, sequence_no, event_id, event_type,
                operation, actor, identity_assurance, detail_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_PLACEHOLDER,
                project_id,
                sequence_no,
                event_id,
                event_type,
                operation,
                actor,
                IDENTITY_ASSURANCE,
                _canonical_json(detail),
                previous_hash,
                event_hash,
                created_at,
            ),
        )

    def records(self, project_id: str) -> List[RuxRiskDispositionRecord]:
        rows = self._rows(
            """
            SELECT payload_json FROM rux_disposition_records
            WHERE tenant_id = ? AND project_id = ?
            ORDER BY created_at, rowid
            """,
            (TENANT_PLACEHOLDER, project_id),
        )
        return [RuxRiskDispositionRecord.model_validate(json.loads(row["payload_json"])) for row in rows]

    def gates(self, project_id: Optional[str] = None) -> List[ApprovalGate]:
        query = "SELECT payload_json FROM approval_gates WHERE tenant_id = ?"
        params: List[Any] = [TENANT_PLACEHOLDER]
        if project_id is not None:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY project_id, approval_id"
        return [ApprovalGate.model_validate(json.loads(row["payload_json"])) for row in self._rows(query, params)]

    def decisions(self, project_id: Optional[str] = None) -> List[ApprovalDecisionRecord]:
        query = "SELECT payload_json FROM approval_decisions WHERE tenant_id = ?"
        params: List[Any] = [TENANT_PLACEHOLDER]
        if project_id is not None:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY created_at, rowid"
        return [
            ApprovalDecisionRecord.model_validate(json.loads(row["payload_json"]))
            for row in self._rows(query, params)
        ]

    def audit_events(self, project_id: Optional[str] = None) -> List[AuditEvent]:
        query = "SELECT payload_json FROM approval_audit_events WHERE tenant_id = ?"
        params: List[Any] = [TENANT_PLACEHOLDER]
        if project_id is not None:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY created_at, rowid"
        return [AuditEvent.model_validate(json.loads(row["payload_json"])) for row in self._rows(query, params)]

    def evidence_review_records(
        self,
        project_id: str,
        package_id: str,
        evidence_id: Optional[str] = None,
    ) -> List[EvidenceReviewRecord]:
        query = """
            SELECT payload_json
            FROM evidence_review_records
            WHERE tenant_id = ? AND project_id = ? AND package_id = ?
        """
        params: List[Any] = [TENANT_PLACEHOLDER, project_id, package_id]
        if evidence_id is not None:
            query += " AND evidence_id = ?"
            params.append(evidence_id)
        query += " ORDER BY new_revision, created_at, rowid"
        return [
            EvidenceReviewRecord.model_validate(json.loads(row["payload_json"]))
            for row in self._rows(query, params)
        ]

    def evidence_picos_working_state(
        self,
        project_id: str,
        package_id: str,
    ) -> EvidencePicosWorkingState:
        rows = self._rows(
            """
            SELECT payload_json
            FROM evidence_picos_working_states
            WHERE tenant_id = ? AND project_id = ? AND package_id = ?
            """,
            (TENANT_PLACEHOLDER, project_id, package_id),
        )
        if not rows:
            raise KeyError(f"{project_id}/{package_id}")
        return EvidencePicosWorkingState.model_validate(json.loads(rows[-1]["payload_json"]))

    def evidence_picos_decision_records(
        self,
        project_id: str,
        package_id: str,
        question_id: Optional[str] = None,
    ) -> List[EvidencePicosDecisionRecord]:
        query = """
            SELECT payload_json
            FROM evidence_picos_decision_records
            WHERE tenant_id = ? AND project_id = ? AND package_id = ?
        """
        params: List[Any] = [TENANT_PLACEHOLDER, project_id, package_id]
        if question_id is not None:
            query += " AND question_id = ?"
            params.append(question_id)
        query += " ORDER BY new_revision, created_at, rowid"
        return [
            EvidencePicosDecisionRecord.model_validate(json.loads(row["payload_json"]))
            for row in self._rows(query, params)
        ]

    def evidence_picos_working_state_snapshots(
        self,
        project_id: str,
        working_state_id: str,
    ) -> List[Dict[str, Any]]:
        rows = self._rows(
            """
            SELECT snapshot_id, package_id, revision, snapshot_type, approval_id,
                   audit_id, created_at, payload_json
            FROM evidence_picos_working_state_snapshots
            WHERE tenant_id = ? AND project_id = ? AND working_state_id = ?
            ORDER BY revision, created_at, rowid
            """,
            (TENANT_PLACEHOLDER, project_id, working_state_id),
        )
        snapshots: List[Dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            item: Dict[str, Any] = {
                "snapshot_id": row["snapshot_id"],
                "package_id": row["package_id"],
                "revision": int(row["revision"]),
                "snapshot_type": row["snapshot_type"],
                "approval_id": row["approval_id"],
                "audit_id": row["audit_id"],
                "created_at": row["created_at"],
            }
            if row["snapshot_type"] == "decision_action":
                model = EvidencePicosWorkingState.model_validate(payload)
                item["working_state"] = model
            else:
                model = EvidencePicosSnapshot.model_validate(payload)
                item["snapshot"] = model
            item["payload"] = model
            snapshots.append(item)
        return snapshots

    def evidence_picos_handoffs(
        self,
        project_id: str,
        package_id: str,
    ) -> List[EvidencePicosWritingHandoff]:
        rows = self._rows(
            """
            SELECT payload_json
            FROM evidence_picos_writing_handoffs
            WHERE tenant_id = ? AND project_id = ? AND package_id = ?
            ORDER BY created_at, rowid
            """,
            (TENANT_PLACEHOLDER, project_id, package_id),
        )
        return [
            EvidencePicosWritingHandoff.model_validate(json.loads(row["payload_json"]))
            for row in rows
        ]

    def evidence_ai_revision_threads(
        self,
        project_id: str,
        package_id: str,
        anchor_id: Optional[str] = None,
    ) -> List[EvidenceAiRevisionThread]:
        query = """
            SELECT payload_json
            FROM evidence_ai_revision_threads
            WHERE tenant_id = ? AND project_id = ? AND package_id = ?
        """
        params: List[Any] = [TENANT_PLACEHOLDER, project_id, package_id]
        if anchor_id is not None:
            query += " AND anchor_id = ?"
            params.append(anchor_id)
        query += " ORDER BY updated_at, rowid"
        return [
            EvidenceAiRevisionThread.model_validate(json.loads(row["payload_json"]))
            for row in self._rows(query, params)
        ]

    def evidence_ai_revision_thread(
        self,
        project_id: str,
        thread_id: str,
    ) -> EvidenceAiRevisionThread:
        rows = self._rows(
            """
            SELECT payload_json
            FROM evidence_ai_revision_threads
            WHERE tenant_id = ? AND project_id = ? AND thread_id = ?
            """,
            (TENANT_PLACEHOLDER, project_id, thread_id),
        )
        if not rows:
            raise KeyError(f"{project_id}/{thread_id}")
        return EvidenceAiRevisionThread.model_validate(json.loads(rows[-1]["payload_json"]))

    def medical_writing_revision_threads(self, project_id: str) -> List[RevisionThread]:
        rows = self._rows(
            """
            SELECT payload_json
            FROM medical_writing_revision_threads
            WHERE tenant_id = ? AND project_id = ?
            ORDER BY updated_at, rowid
            """,
            (TENANT_PLACEHOLDER, project_id),
        )
        return [RevisionThread.model_validate(json.loads(row["payload_json"])) for row in rows]

    def medical_writing_revision_thread(
        self,
        project_id: str,
        thread_id: str,
    ) -> RevisionThread:
        rows = self._rows(
            """
            SELECT payload_json
            FROM medical_writing_revision_threads
            WHERE tenant_id = ? AND project_id = ? AND thread_id = ?
            """,
            (TENANT_PLACEHOLDER, project_id, thread_id),
        )
        if not rows:
            raise KeyError(f"{project_id}/{thread_id}")
        return RevisionThread.model_validate(json.loads(rows[-1]["payload_json"]))

    def medical_writing_working_copy(
        self,
        project_id: str,
        document_id: str,
        section_id: str,
    ) -> MedicalWritingWorkingCopy:
        rows = self._rows(
            """
            SELECT payload_json
            FROM medical_writing_working_copies
            WHERE tenant_id = ? AND project_id = ? AND document_id = ? AND section_id = ?
            """,
            (TENANT_PLACEHOLDER, project_id, document_id, section_id),
        )
        if not rows:
            raise KeyError(f"{project_id}/{document_id}/{section_id}")
        return MedicalWritingWorkingCopy.model_validate(json.loads(rows[-1]["payload_json"]))

    def medical_writing_working_copies_for_document(
        self,
        project_id: str,
        document_id: str,
    ) -> List[MedicalWritingWorkingCopy]:
        rows = self._rows(
            """
            SELECT payload_json
            FROM medical_writing_working_copies
            WHERE tenant_id = ? AND project_id = ? AND document_id = ?
            ORDER BY updated_at, rowid
            """,
            (TENANT_PLACEHOLDER, project_id, document_id),
        )
        return [
            MedicalWritingWorkingCopy.model_validate(json.loads(row["payload_json"]))
            for row in rows
        ]

    def medical_writing_working_copy_by_id(
        self,
        project_id: str,
        working_copy_id: str,
    ) -> MedicalWritingWorkingCopy:
        rows = self._rows(
            """
            SELECT payload_json
            FROM medical_writing_working_copies
            WHERE tenant_id = ? AND project_id = ? AND working_copy_id = ?
            """,
            (TENANT_PLACEHOLDER, project_id, working_copy_id),
        )
        if not rows:
            raise KeyError(f"{project_id}/{working_copy_id}")
        return MedicalWritingWorkingCopy.model_validate(json.loads(rows[-1]["payload_json"]))

    def medical_writing_working_copy_snapshots(
        self,
        project_id: str,
        working_copy_id: str,
    ) -> List[Dict[str, Any]]:
        rows = self._rows(
            """
            SELECT snapshot_id, revision, snapshot_type, audit_id, created_at, payload_json
            FROM medical_writing_working_copy_snapshots
            WHERE tenant_id = ? AND project_id = ? AND working_copy_id = ?
            ORDER BY created_at, rowid
            """,
            (TENANT_PLACEHOLDER, project_id, working_copy_id),
        )
        return [
            {
                "snapshot_id": row["snapshot_id"],
                "revision": int(row["revision"]),
                "snapshot_type": row["snapshot_type"],
                "audit_id": row["audit_id"],
                "created_at": row["created_at"],
                "working_copy": MedicalWritingWorkingCopy.model_validate(
                    json.loads(row["payload_json"])
                ),
            }
            for row in rows
        ]

    def current_medical_writing_content_disposition(
        self,
        project_id: str,
        finding_id: str,
    ) -> Optional[MedicalWritingContentDispositionRecord]:
        rows = self._rows(
            """
            SELECT record.payload_json
            FROM medical_writing_content_disposition_state AS state
            JOIN medical_writing_content_disposition_records AS record
              ON record.tenant_id = state.tenant_id
             AND record.project_id = state.project_id
             AND record.record_id = state.latest_record_id
            WHERE state.tenant_id = ? AND state.project_id = ? AND state.finding_id = ?
            """,
            (TENANT_PLACEHOLDER, project_id, finding_id),
        )
        if not rows:
            return None
        return MedicalWritingContentDispositionRecord.model_validate(
            json.loads(rows[-1]["payload_json"])
        )

    def workflow_audit_events(
        self,
        project_id: str,
        workflow_type: Optional[str] = None,
    ) -> List[AuditEvent]:
        query = """
            SELECT payload_json
            FROM workflow_audit_events
            WHERE tenant_id = ? AND project_id = ?
        """
        params: List[Any] = [TENANT_PLACEHOLDER, project_id]
        if workflow_type is not None:
            query += " AND workflow_type = ?"
            params.append(workflow_type)
        query += " ORDER BY created_at, rowid"
        return [
            AuditEvent.model_validate(json.loads(row["payload_json"]))
            for row in self._rows(query, params)
        ]

    def medical_writing_document_binding_sidecar(
        self,
        project_id: str,
        document_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the latest additive StudyDefinition binding for an imported document.

        The sidecar is an immutable workflow audit committed atomically with an
        explicit accept/revert recovery revision. Source DOCX and source-derived
        ProtocolDocument payloads remain untouched.
        """

        events = self.workflow_audit_events(project_id)
        for event in reversed(events):
            if event.action == "medical_writing_study_definition_rebound":
                binding = event.detail.get("current_binding")
            elif event.action in {
                "medical_writing_working_copy_accepted_and_bound",
                "medical_writing_working_copy_reverted_to_authoritative_baseline",
            }:
                binding = event.detail.get("study_definition_binding")
            else:
                continue
            if str(event.detail.get("document_id", "")) != document_id:
                if event.target_id != document_id:
                    continue
            if not isinstance(binding, dict):
                continue
            definition_id = str(binding.get("definition_id", "")).strip()
            definition_sha256 = str(binding.get("definition_sha256", "")).strip()
            try:
                definition_revision = int(binding.get("definition_revision"))
            except (TypeError, ValueError):
                continue
            if (
                not definition_id
                or definition_revision < 1
                or len(definition_sha256) != 64
                or any(character not in "0123456789abcdef" for character in definition_sha256)
            ):
                continue
            return {
                "definition_id": definition_id,
                "definition_revision": definition_revision,
                "definition_sha256": definition_sha256,
                "audit_id": event.audit_id,
                "created_at": event.created_at,
            }
        return None

    def runtime_audit_records(self, project_id: str) -> List[Dict[str, Any]]:
        rows = self._rows(
            """
            SELECT sequence_no, event_id, event_type, operation, actor,
                   identity_assurance, detail_json, previous_hash, event_hash, created_at
            FROM runtime_audit_chain
            WHERE tenant_id = ? AND project_id = ?
            ORDER BY sequence_no
            """,
            (TENANT_PLACEHOLDER, project_id),
        )
        return [
            {
                "sequence_no": row["sequence_no"],
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "operation": row["operation"],
                "actor": row["actor"],
                "identity_assurance": row["identity_assurance"],
                "detail": json.loads(row["detail_json"]),
                "previous_hash": row["previous_hash"],
                "event_hash": row["event_hash"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def verify_audit_chain(self, project_id: str) -> List[str]:
        violations: List[str] = []
        expected_previous_hash = ""
        events = self.runtime_audit_records(project_id)
        latest_medical_writing_approvals: Dict[str, Dict[str, Any]] = {}
        for event in events:
            if event["previous_hash"] != expected_previous_hash:
                violations.append(f"sequence {event['sequence_no']}: previous hash mismatch")
            event_body = {
                "tenant_id": TENANT_PLACEHOLDER,
                "project_id": project_id,
                "sequence_no": event["sequence_no"],
                "event_id": event["event_id"],
                "event_type": event["event_type"],
                "operation": event["operation"],
                "actor": event["actor"],
                "identity_assurance": event["identity_assurance"],
                "detail": event["detail"],
                "previous_hash": event["previous_hash"],
                "created_at": event["created_at"],
            }
            actual_hash = _payload_hash(event_body)
            if event["event_hash"] != actual_hash:
                violations.append(f"sequence {event['sequence_no']}: event hash mismatch")
            if event["event_type"] == "rux_disposition_committed":
                linked_hash = self._linked_payload_hash(
                    "rux_disposition_records",
                    "record_id",
                    event["detail"].get("record_id", ""),
                    project_id,
                )
                expected_hash = event["detail"].get("disposition_payload_hash")
                if expected_hash and linked_hash != expected_hash:
                    violations.append(
                        f"sequence {event['sequence_no']}: disposition payload mismatch"
                    )
            if event["event_type"] == "approval_action_committed":
                audit_hash = self._linked_payload_hash(
                    "approval_audit_events",
                    "audit_id",
                    event["detail"].get("audit_id", ""),
                    project_id,
                )
                expected_audit_hash = event["detail"].get("audit_payload_hash")
                if expected_audit_hash and audit_hash != expected_audit_hash:
                    violations.append(
                        f"sequence {event['sequence_no']}: approval audit payload mismatch"
                    )
                decision_hash = self._linked_payload_hash(
                    "approval_decisions",
                    "decision_id",
                    event["detail"].get("decision_id", ""),
                    project_id,
                )
                expected_decision_hash = event["detail"].get("decision_payload_hash")
                if expected_decision_hash and decision_hash != expected_decision_hash:
                    violations.append(
                        f"sequence {event['sequence_no']}: approval decision payload mismatch"
                    )
            if event["event_type"] == "evidence_review_action_committed":
                review_hash = self._linked_payload_hash(
                    "evidence_review_records",
                    "record_id",
                    event["detail"].get("record_id", ""),
                    project_id,
                )
                if event["detail"].get("review_payload_hash") and review_hash != event[
                    "detail"
                ].get("review_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: evidence review payload mismatch"
                    )
                workflow_audit_hash = self._linked_payload_hash(
                    "workflow_audit_events",
                    "audit_id",
                    event["detail"].get("audit_id", ""),
                    project_id,
                )
                if event["detail"].get(
                    "audit_payload_hash"
                ) and workflow_audit_hash != event["detail"].get("audit_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: evidence review audit payload mismatch"
                    )
            if event["event_type"] == "evidence_picos_action_committed":
                decision_hash = self._linked_payload_hash(
                    "evidence_picos_decision_records",
                    "record_id",
                    event["detail"].get("record_id", ""),
                    project_id,
                )
                if event["detail"].get(
                    "decision_payload_hash"
                ) and decision_hash != event["detail"].get("decision_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: evidence PICOS decision payload mismatch"
                    )
                snapshot_hash = self._linked_payload_hash(
                    "evidence_picos_working_state_snapshots",
                    "snapshot_id",
                    event["detail"].get("working_state_snapshot_id", ""),
                    project_id,
                )
                if event["detail"].get(
                    "working_state_payload_hash"
                ) and snapshot_hash != event["detail"].get("working_state_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: evidence PICOS working state payload mismatch"
                    )
                workflow_audit_hash = self._linked_payload_hash(
                    "workflow_audit_events",
                    "audit_id",
                    event["detail"].get("audit_id", ""),
                    project_id,
                )
                if event["detail"].get(
                    "audit_payload_hash"
                ) and workflow_audit_hash != event["detail"].get("audit_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: evidence PICOS action audit payload mismatch"
                    )
            if event["event_type"] == "evidence_picos_snapshot_committed":
                snapshot_hash = self._linked_payload_hash(
                    "evidence_picos_working_state_snapshots",
                    "snapshot_id",
                    event["detail"].get("snapshot_id", ""),
                    project_id,
                )
                if event["detail"].get(
                    "snapshot_payload_hash"
                ) and snapshot_hash != event["detail"].get("snapshot_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: evidence PICOS snapshot payload mismatch"
                    )
                workflow_audit_hash = self._linked_payload_hash(
                    "workflow_audit_events",
                    "audit_id",
                    event["detail"].get("audit_id", ""),
                    project_id,
                )
                if event["detail"].get(
                    "audit_payload_hash"
                ) and workflow_audit_hash != event["detail"].get("audit_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: evidence PICOS snapshot audit payload mismatch"
                    )
            if event["event_type"] == "evidence_picos_handoff_committed":
                handoff_hash = self._linked_payload_hash(
                    "evidence_picos_writing_handoffs",
                    "handoff_id",
                    event["detail"].get("handoff_id", ""),
                    project_id,
                )
                if event["detail"].get(
                    "handoff_payload_hash"
                ) and handoff_hash != event["detail"].get("handoff_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: evidence PICOS handoff payload mismatch"
                    )
                snapshot_hash = self._linked_payload_hash(
                    "evidence_picos_working_state_snapshots",
                    "snapshot_id",
                    event["detail"].get("snapshot_id", ""),
                    project_id,
                )
                if event["detail"].get(
                    "snapshot_payload_hash"
                ) and snapshot_hash != event["detail"].get("snapshot_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: evidence PICOS handoff snapshot payload mismatch"
                    )
                workflow_audit_hash = self._linked_payload_hash(
                    "workflow_audit_events",
                    "audit_id",
                    event["detail"].get("audit_id", ""),
                    project_id,
                )
                if event["detail"].get(
                    "audit_payload_hash"
                ) and workflow_audit_hash != event["detail"].get("audit_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: evidence PICOS handoff audit payload mismatch"
                    )
            if event["event_type"] in {
                "evidence_ai_revision_submitted",
                "evidence_ai_revision_action_committed",
            }:
                thread_hash = self._linked_payload_hash(
                    "evidence_ai_revision_snapshots",
                    "snapshot_id",
                    event["detail"].get("thread_snapshot_id", ""),
                    project_id,
                )
                expected_thread_hash = event["detail"].get("thread_payload_hash")
                if expected_thread_hash and thread_hash != expected_thread_hash:
                    violations.append(
                        f"sequence {event['sequence_no']}: evidence AI revision thread payload mismatch"
                    )
                workflow_audit_hash = self._linked_payload_hash(
                    "workflow_audit_events",
                    "audit_id",
                    event["detail"].get("audit_id", ""),
                    project_id,
                )
                expected_workflow_audit_hash = event["detail"].get("audit_payload_hash")
                if (
                    expected_workflow_audit_hash
                    and workflow_audit_hash != expected_workflow_audit_hash
                ):
                    violations.append(
                        f"sequence {event['sequence_no']}: evidence AI revision audit payload mismatch"
                    )
            if event["event_type"] in {
                "medical_writing_revision_submitted",
                "medical_writing_revision_action_committed",
            }:
                thread_hash = self._linked_payload_hash(
                    "medical_writing_revision_snapshots",
                    "snapshot_id",
                    event["detail"].get("thread_snapshot_id", ""),
                    project_id,
                )
                expected_thread_hash = event["detail"].get("thread_payload_hash")
                if expected_thread_hash and thread_hash != expected_thread_hash:
                    violations.append(
                        f"sequence {event['sequence_no']}: medical writing thread payload mismatch"
                    )
                workflow_audit_hash = self._linked_payload_hash(
                    "workflow_audit_events",
                    "audit_id",
                    event["detail"].get("audit_id", ""),
                    project_id,
                )
                expected_workflow_audit_hash = event["detail"].get("audit_payload_hash")
                if expected_workflow_audit_hash and workflow_audit_hash != expected_workflow_audit_hash:
                    violations.append(
                        f"sequence {event['sequence_no']}: workflow audit payload mismatch"
                    )
            if event["event_type"] in {
                "medical_writing_working_copy_saved",
                "medical_writing_working_copy_accepted_and_bound",
                "medical_writing_working_copy_reverted_to_authoritative_baseline",
            }:
                working_copy_hash = self._linked_payload_hash(
                    "medical_writing_working_copy_snapshots",
                    "snapshot_id",
                    event["detail"].get("working_copy_snapshot_id", ""),
                    project_id,
                )
                expected_working_copy_hash = event["detail"].get(
                    "working_copy_payload_hash"
                )
                if (
                    expected_working_copy_hash
                    and working_copy_hash != expected_working_copy_hash
                ):
                    violations.append(
                        f"sequence {event['sequence_no']}: medical writing working copy payload mismatch"
                    )
                workflow_audit_hash = self._linked_payload_hash(
                    "workflow_audit_events",
                    "audit_id",
                    event["detail"].get("audit_id", ""),
                    project_id,
                )
                expected_workflow_audit_hash = event["detail"].get("audit_payload_hash")
                if (
                    expected_workflow_audit_hash
                    and workflow_audit_hash != expected_workflow_audit_hash
                ):
                    violations.append(
                        f"sequence {event['sequence_no']}: working copy audit payload mismatch"
                    )
            if event["event_type"] == "safety_pv_review_committed":
                record_hash = self._linked_payload_hash(
                    "safety_pv_review_records",
                    "record_id",
                    event["detail"].get("record_id", ""),
                    project_id,
                )
                expected_record_hash = event["detail"].get("record_payload_hash")
                if expected_record_hash and record_hash != expected_record_hash:
                    violations.append(
                        f"sequence {event['sequence_no']}: Safety/PV review record payload mismatch"
                    )
            if event["event_type"] == "medical_writing_final_approval_committed":
                latest_medical_writing_approvals[
                    str(event["detail"].get("approval_id", ""))
                ] = event
                audit_hash = self._linked_payload_hash(
                    "approval_audit_events",
                    "audit_id",
                    event["detail"].get("audit_id", ""),
                    project_id,
                )
                if event["detail"].get("audit_payload_hash") and audit_hash != event[
                    "detail"
                ].get("audit_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: medical writing approval audit payload mismatch"
                    )
                workflow_audit_hash = self._linked_payload_hash(
                    "workflow_audit_events",
                    "audit_id",
                    event["detail"].get("audit_id", ""),
                    project_id,
                )
                if event["detail"].get(
                    "audit_payload_hash"
                ) and workflow_audit_hash != event["detail"].get("audit_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: medical writing approval workflow audit payload mismatch"
                    )
                decision_hash = self._linked_payload_hash(
                    "approval_decisions",
                    "decision_id",
                    event["detail"].get("decision_id", ""),
                    project_id,
                )
                if event["detail"].get("decision_payload_hash") and decision_hash != event[
                    "detail"
                ].get("decision_payload_hash"):
                    violations.append(
                        f"sequence {event['sequence_no']}: medical writing approval decision payload mismatch"
                    )
                snapshot_table = event["detail"].get("target_snapshot_table", "")
                snapshot_id = event["detail"].get("target_snapshot_id", "")
                expected_snapshot_hash = event["detail"].get("target_snapshot_hash", "")
                if snapshot_table and snapshot_id and expected_snapshot_hash:
                    snapshot_hash = self._linked_payload_hash(
                        snapshot_table,
                        "snapshot_id",
                        snapshot_id,
                        project_id,
                    )
                    if snapshot_hash != expected_snapshot_hash:
                        violations.append(
                            f"sequence {event['sequence_no']}: medical writing approval target payload mismatch"
                        )
            if event["event_type"] == "medical_writing_section_freeze_committed":
                workflow_audit_hash = self._linked_payload_hash(
                    "workflow_audit_events",
                    "audit_id",
                    event["detail"].get("audit_id", ""),
                    project_id,
                )
                expected_audit_hash = event["detail"].get("audit_payload_hash", "")
                if expected_audit_hash and workflow_audit_hash != expected_audit_hash:
                    violations.append(
                        f"sequence {event['sequence_no']}: section freeze audit payload mismatch"
                    )
                snapshot_id = event["detail"].get("snapshot_id", "")
                expected_snapshot_hash = event["detail"].get(
                    "snapshot_payload_hash", ""
                )
                if snapshot_id and expected_snapshot_hash:
                    snapshot_hash = self._linked_payload_hash(
                        "medical_writing_working_copy_snapshots",
                        "snapshot_id",
                        snapshot_id,
                        project_id,
                    )
                    if snapshot_hash != expected_snapshot_hash:
                        violations.append(
                            f"sequence {event['sequence_no']}: section freeze snapshot payload mismatch"
                        )
            expected_previous_hash = event["event_hash"]
        for approval_id, event in latest_medical_writing_approvals.items():
            if not approval_id:
                continue
            gate_rows = self._rows(
                """
                SELECT payload_json FROM approval_gates
                WHERE tenant_id = ? AND project_id = ? AND approval_id = ?
                """,
                (TENANT_PLACEHOLDER, project_id, approval_id),
            )
            decision_rows = self._rows(
                """
                SELECT payload_json FROM approval_decisions
                WHERE tenant_id = ? AND project_id = ? AND decision_id = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    event["detail"].get("decision_id", ""),
                ),
            )
            if not gate_rows or not decision_rows:
                violations.append(
                    f"sequence {event['sequence_no']}: medical writing approval state record missing"
                )
                continue
            try:
                gate = ApprovalGate.model_validate(json.loads(gate_rows[-1]["payload_json"]))
                decision = ApprovalDecisionRecord.model_validate(
                    json.loads(decision_rows[-1]["payload_json"])
                )
            except (ValueError, TypeError, json.JSONDecodeError):
                violations.append(
                    f"sequence {event['sequence_no']}: medical writing approval state record invalid"
                )
                continue
            if gate.state != decision.new_state:
                violations.append(
                    f"sequence {event['sequence_no']}: medical writing approval gate state mismatch"
                )
            if event["detail"].get("target_type") and gate.target_type != event[
                "detail"
            ].get("target_type"):
                violations.append(
                    f"sequence {event['sequence_no']}: medical writing approval gate target type mismatch"
                )
            if event["detail"].get("target_id") and gate.target_id != event["detail"].get(
                "target_id"
            ):
                violations.append(
                    f"sequence {event['sequence_no']}: medical writing approval gate target id mismatch"
                )
            if gate.target_revision != event["detail"].get("target_revision"):
                violations.append(
                    f"sequence {event['sequence_no']}: medical writing approval gate target revision mismatch"
                )
            if decision.comment and gate.review_comments != decision.comment:
                violations.append(
                    f"sequence {event['sequence_no']}: medical writing approval gate comment mismatch"
                )
            if not decision.blocked and decision.action.value != "view_quality_gate":
                if gate.reviewed_by != decision.actor:
                    violations.append(
                        f"sequence {event['sequence_no']}: medical writing approval reviewer mismatch"
                    )
                expected_approver = (
                    decision.actor if decision.action.value == "approve" else None
                )
                if gate.approved_by != expected_approver:
                    violations.append(
                        f"sequence {event['sequence_no']}: medical writing approval approver mismatch"
                    )
        return violations

    def _linked_payload_hash(
        self,
        table: str,
        id_column: str,
        record_id: str,
        project_id: str,
    ) -> Optional[str]:
        allowed = {
            ("rux_disposition_records", "record_id"),
            ("approval_audit_events", "audit_id"),
            ("approval_decisions", "decision_id"),
            ("medical_writing_revision_snapshots", "snapshot_id"),
            ("medical_writing_working_copy_snapshots", "snapshot_id"),
            ("medical_writing_content_disposition_records", "record_id"),
            ("safety_pv_review_records", "record_id"),
            ("evidence_review_records", "record_id"),
            ("evidence_picos_decision_records", "record_id"),
            ("evidence_picos_working_state_snapshots", "snapshot_id"),
            ("evidence_picos_writing_handoffs", "handoff_id"),
            ("evidence_ai_revision_snapshots", "snapshot_id"),
            ("workflow_audit_events", "audit_id"),
        }
        if (table, id_column) not in allowed or not record_id:
            return None
        rows = self._rows(
            f"""
            SELECT payload_json FROM {table}
            WHERE tenant_id = ? AND project_id = ? AND {id_column} = ?
            """,
            (TENANT_PLACEHOLDER, project_id, record_id),
        )
        if not rows:
            return None
        try:
            payload = json.loads(rows[-1]["payload_json"])
        except json.JSONDecodeError:
            return "invalid_json"
        return _payload_hash(payload)

    def health_report(self) -> Dict[str, Any]:
        with self._connect() as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
            version = int(
                connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
            )
            audit_projects = [
                str(row["project_id"])
                for row in connection.execute(
                    """
                    SELECT DISTINCT project_id
                    FROM runtime_audit_chain
                    WHERE tenant_id = ?
                    ORDER BY project_id
                    """,
                    (TENANT_PLACEHOLDER,),
                ).fetchall()
            ]
        audit_chain_violation_count = 0
        for project_id in audit_projects:
            try:
                audit_chain_violation_count += len(self.verify_audit_chain(project_id))
            except (ValueError, TypeError, json.JSONDecodeError):
                audit_chain_violation_count += 1
        return {
            "status": "ok" if integrity == "ok" and not foreign_keys and not audit_chain_violation_count else "error",
            "integrity_check": integrity,
            "foreign_key_violations": len(foreign_keys),
            "schema_version": version,
            "audit_chain_projects": len(audit_projects),
            "audit_chain_violation_count": audit_chain_violation_count,
            "legacy_import": self.legacy_import_report(),
        }

    def legacy_import_report(self) -> Dict[str, int]:
        return dict(self._legacy_report)

    def _rows(self, query: str, params: Iterable[Any]) -> List[sqlite3.Row]:
        with self._connect() as connection:
            return list(connection.execute(query, tuple(params)).fetchall())

    def _inject(self, checkpoint: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(checkpoint)

    def _import_legacy(
        self,
        *,
        gate_path: Optional[Path],
        decision_path: Optional[Path],
        audit_path: Optional[Path],
        disposition_path: Optional[Path],
    ) -> None:
        specs = (
            (gate_path, ApprovalGate, self._import_gate),
            (decision_path, ApprovalDecisionRecord, self._import_decision),
            (audit_path, AuditEvent, self._import_audit),
            (disposition_path, RuxRiskDispositionRecord, self._import_disposition),
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            for path, model_type, importer in specs:
                if path is None or not Path(path).exists():
                    continue
                for payload in self._read_legacy_jsonl(Path(path)):
                    try:
                        record = model_type.model_validate(payload)
                    except Exception:
                        self._legacy_report["invalid_records"] += 1
                        continue
                    importer(connection, record)
                    self._legacy_report["valid_lines"] += 1
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _read_legacy_jsonl(self, path: Path) -> Iterable[Dict[str, Any]]:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    self._legacy_report["malformed_lines"] += 1
                    continue
                if not isinstance(payload, dict):
                    self._legacy_report["invalid_records"] += 1
                    continue
                yield payload

    def _import_gate(self, connection: sqlite3.Connection, approval: ApprovalGate) -> None:
        self._upsert_gate(connection, approval)

    def _import_decision(
        self, connection: sqlite3.Connection, decision: ApprovalDecisionRecord
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO approval_decisions(
                tenant_id, project_id, decision_id, approval_id, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_PLACEHOLDER,
                decision.project_id,
                decision.decision_id,
                decision.approval_id,
                decision.created_at.isoformat(),
                _canonical_json(decision.model_dump(mode="json")),
            ),
        )

    def _import_audit(self, connection: sqlite3.Connection, event: AuditEvent) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO approval_audit_events(
                tenant_id, project_id, audit_id, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                TENANT_PLACEHOLDER,
                event.project_id,
                event.audit_id,
                event.created_at.isoformat(),
                _canonical_json(event.model_dump(mode="json")),
            ),
        )

    def _import_disposition(
        self, connection: sqlite3.Connection, disposition: RuxRiskDispositionRecord
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO rux_disposition_records(
                tenant_id, record_id, project_id, item_id, source_version,
                new_state, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_PLACEHOLDER,
                disposition.record_id,
                disposition.project_id,
                disposition.item_id,
                disposition.source_version,
                disposition.new_state,
                disposition.created_at.isoformat(),
                _canonical_json(disposition.model_dump(mode="json")),
            ),
        )
