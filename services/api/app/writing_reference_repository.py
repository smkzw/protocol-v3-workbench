from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - local production targets are macOS/Linux.
    fcntl = None

from packages.contracts.workbench_contracts import (
    ChapterIntegrationResult,
    CompositePipelineRun,
    CompetitorTriageConfirmationRecord,
    CompetitorTriageRun,
    DocumentStructurePlan,
    WritingReferenceDocumentArtifact,
    WritingReferenceDocumentValidationRecord,
    WritingReferenceEvidenceBrief,
    WritingReferenceExtractionResult,
    WritingReferenceExtractionReviewDecision,
    WritingReferenceMedicalReviewDecision,
    WritingReferenceRelevanceDecision,
    WritingReferenceSearchSnapshot,
    WritingReferenceTranslationRevision,
    WritingReferenceUpperLayerEscalation,
    WritingReferenceUpperLayerStageRun,
    TranslationChunkRecord,
)
from packages.contracts.workbench_contracts.models import (
    WritingReferenceOcrConsistencyBatchMedicalDispositionResult,
    WritingReferenceOcrConsistencyEffectiveProjection,
    WritingReferenceOcrConsistencyMedicalDisposition,
    WritingReferenceOcrConsistencyMedicalDispositionOutcome,
    WritingReferenceOcrConsistencyMedicalDispositionTarget,
    WritingReferenceOcrConsistencyQcRecheck,
    WritingReferenceTranslationBatchReviewItemOutcome,
)


SCHEMA_VERSION = 8
TENANT_ID = "kangzhe_local"
RELEVANCE_STATUSES = {"direct_competitor", "indirect_reference", "excluded"}
# The only upper-layer run statuses that count as idempotent results
# (86fe7ea).  Must stay literally in sync with the executor's replay
# fall-through and fingerprint checks in
# writing_reference_upper_layer_execution.py execute().
UPPER_LAYER_SUCCESSFUL_RUN_STATUSES = frozenset(
    {"succeeded", "completed_degraded"}
)


class WritingReferenceRepositoryError(ValueError):
    pass


class WritingReferenceConflictError(WritingReferenceRepositoryError):
    pass


class WritingReferenceStaleStateError(WritingReferenceRepositoryError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


_VOLATILE_PAYLOAD_KEYS = frozenset({"created_at", "updated_at"})


def _strip_volatile_payload_fields(value: Any) -> Any:
    """Drop wall-clock fields so immutable retries share one request hash."""
    if isinstance(value, dict):
        return {
            key: _strip_volatile_payload_fields(item)
            for key, item in value.items()
            if key not in _VOLATILE_PAYLOAD_KEYS
        }
    if isinstance(value, list):
        return [_strip_volatile_payload_fields(item) for item in value]
    if isinstance(value, tuple):
        return [_strip_volatile_payload_fields(item) for item in value]
    return value


def _semantic_payload_hash(value: Any) -> str:
    return _payload_hash(_strip_volatile_payload_fields(value))


@contextmanager
def _repository_initialization_lock(db_path: Path):
    """Serialize additive schema initialization across local worker processes."""
    lock_path = Path(f"{db_path}.init.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _migrate_upper_layer_route_identity_v6(
    connection: sqlite3.Connection,
) -> None:
    """Remove the historical DeepSeek-only model CHECK without mutating rows."""
    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("PRAGMA legacy_alter_table = ON")
    connection.execute("BEGIN IMMEDIATE")
    current_version = int(
        connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
    )
    if current_version >= 6:
        connection.rollback()
        connection.execute("PRAGMA legacy_alter_table = OFF")
        connection.execute("PRAGMA foreign_keys = ON")
        return
    table_sql_row = connection.execute(
        """
        SELECT sql FROM sqlite_master
        WHERE type='table' AND name='writing_reference_upper_layer_stage_runs'
        """
    ).fetchone()
    if table_sql_row is None:
        connection.rollback()
        connection.execute("PRAGMA legacy_alter_table = OFF")
        connection.execute("PRAGMA foreign_keys = ON")
        raise WritingReferenceRepositoryError(
            "upper-layer stage-run table is missing during v6 migration"
        )
    table_sql = str(table_sql_row["sql"] or "")
    try:
        if "'deepseek-v4-flash'" in table_sql:
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_wref_upper_layer_run_no_update"
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_wref_upper_layer_run_no_delete"
            )
            connection.execute(
                "DROP INDEX IF EXISTS idx_wref_upper_layer_pro_escalation"
            )
            connection.execute(
                """
                ALTER TABLE writing_reference_upper_layer_stage_runs
                RENAME TO writing_reference_upper_layer_stage_runs_v5
                """
            )
            connection.execute(
                """
                CREATE TABLE writing_reference_upper_layer_stage_runs (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    stage_run_id TEXT NOT NULL,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    extraction_revision TEXT NOT NULL,
                    stage TEXT NOT NULL CHECK (
                        stage IN (
                            'document_planning',
                            'post_hy_mt2_integration_qc',
                            'corpus_selection_support'
                        )
                    ),
                    requested_model TEXT NOT NULL CHECK (
                        length(trim(requested_model)) BETWEEN 1 AND 200
                    ),
                    status TEXT NOT NULL,
                    execution_fingerprint TEXT NOT NULL,
                    prompt_sha256 TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    input_payload_json TEXT NOT NULL,
                    output_hash TEXT NOT NULL,
                    output_payload_json TEXT NOT NULL,
                    hy_mt2_target_map_sha256 TEXT NOT NULL,
                    parent_stage_run_id TEXT NOT NULL,
                    escalation_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, stage_run_id),
                    UNIQUE (tenant_id, project_id, execution_fingerprint)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO writing_reference_upper_layer_stage_runs(
                    tenant_id, project_id, stage_run_id, owner_type, owner_id,
                    artifact_id, extraction_revision, stage, requested_model,
                    status, execution_fingerprint, prompt_sha256, prompt_text,
                    input_hash, input_payload_json, output_hash,
                    output_payload_json, hy_mt2_target_map_sha256,
                    parent_stage_run_id, escalation_id, payload_json,
                    created_at, completed_at
                )
                SELECT
                    tenant_id, project_id, stage_run_id, owner_type, owner_id,
                    artifact_id, extraction_revision, stage, requested_model,
                    status, execution_fingerprint, prompt_sha256, prompt_text,
                    input_hash, input_payload_json, output_hash,
                    output_payload_json, hy_mt2_target_map_sha256,
                    parent_stage_run_id, escalation_id, payload_json,
                    created_at, completed_at
                FROM writing_reference_upper_layer_stage_runs_v5
                """
            )
            connection.execute(
                "DROP TABLE writing_reference_upper_layer_stage_runs_v5"
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX idx_wref_upper_layer_pro_escalation
                ON writing_reference_upper_layer_stage_runs(
                    tenant_id, project_id, escalation_id
                )
                WHERE escalation_id <> ''
                """
            )
            connection.execute(
                """
                CREATE TRIGGER trg_wref_upper_layer_run_no_update
                BEFORE UPDATE ON writing_reference_upper_layer_stage_runs BEGIN
                    SELECT RAISE(
                        ABORT,
                        'writing reference upper-layer stage runs are immutable'
                    );
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER trg_wref_upper_layer_run_no_delete
                BEFORE DELETE ON writing_reference_upper_layer_stage_runs BEGIN
                    SELECT RAISE(
                        ABORT,
                        'writing reference upper-layer stage runs are immutable'
                    );
                END
                """
            )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise WritingReferenceRepositoryError(
                f"sqlite integrity check failed during v6 migration: {integrity}"
            )
        foreign_key_issue = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchone()
        if foreign_key_issue is not None:
            raise WritingReferenceRepositoryError(
                "sqlite foreign key check failed during v6 migration"
            )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (6, _utc_now().isoformat()),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA legacy_alter_table = OFF")
        connection.execute("PRAGMA foreign_keys = ON")


def _migrate_workspace_query_indexes_v7(
    connection: sqlite3.Connection,
) -> None:
    """Add snapshot/workspace indexes under one cross-process SQLite lock."""
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    try:
        current_version = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )
        if current_version >= 7:
            connection.rollback()
            return
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_wref_extractions_latest
            ON writing_reference_extractions(
                tenant_id,
                project_id,
                artifact_id,
                created_at DESC,
                extraction_revision DESC
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_wref_source_spans_artifact_revision
            ON writing_reference_source_spans(
                tenant_id,
                project_id,
                artifact_id,
                extraction_revision
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_wref_documents_snapshot
            ON writing_reference_document_artifacts(
                tenant_id,
                project_id,
                snapshot_id,
                artifact_id
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (7, _utc_now().isoformat()),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _migrate_ocr_consistency_qc_v8(
    connection: sqlite3.Connection,
) -> None:
    """Add immutable mixed-OCR rechecks and medical-disposition projections."""
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    try:
        current_version = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )
        if current_version >= 8:
            connection.rollback()
            return
        if current_version != 7:
            connection.rollback()
            raise WritingReferenceRepositoryError(
                f"cannot apply v8 OCR QC migration from schema {current_version}"
            )

        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS writing_reference_ocr_consistency_qc_recheck_records (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                recheck_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                extraction_revision TEXT NOT NULL,
                base_qc_identity_hash TEXT NOT NULL,
                stage_version TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                models_json TEXT NOT NULL,
                physical_pages_json TEXT NOT NULL,
                verdict TEXT NOT NULL CHECK (verdict IN ('pass', 'review_required', 'fail')),
                notes_json TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                output_hash TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, recheck_id),
                UNIQUE (tenant_id, project_id, recheck_id, revision),
                UNIQUE (tenant_id, project_id, artifact_id, extraction_revision, revision),
                FOREIGN KEY (tenant_id, project_id, artifact_id, extraction_revision)
                REFERENCES writing_reference_extractions(
                    tenant_id, project_id, artifact_id, extraction_revision
                )
            );

            CREATE TABLE IF NOT EXISTS writing_reference_ocr_consistency_qc_recheck_state (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                extraction_revision TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                recheck_id TEXT NOT NULL,
                verdict TEXT NOT NULL CHECK (verdict IN ('pass', 'review_required', 'fail')),
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, artifact_id, extraction_revision),
                FOREIGN KEY (tenant_id, project_id, recheck_id)
                REFERENCES writing_reference_ocr_consistency_qc_recheck_records(
                    tenant_id, project_id, recheck_id
                )
            );

            CREATE TABLE IF NOT EXISTS writing_reference_ocr_consistency_medical_disposition_records (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                disposition_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                extraction_revision TEXT NOT NULL,
                recheck_id TEXT NOT NULL,
                recheck_revision INTEGER NOT NULL CHECK (recheck_revision >= 1),
                decision TEXT NOT NULL CHECK (decision IN ('confirmed', 'returned')),
                comment TEXT NOT NULL,
                actor TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, disposition_id),
                UNIQUE (
                    tenant_id, project_id, artifact_id, extraction_revision,
                    recheck_id, recheck_revision, revision
                ),
                FOREIGN KEY (tenant_id, project_id, recheck_id, recheck_revision)
                REFERENCES writing_reference_ocr_consistency_qc_recheck_records(
                    tenant_id, project_id, recheck_id, revision
                )
            );

            CREATE TABLE IF NOT EXISTS writing_reference_ocr_consistency_medical_disposition_state (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                extraction_revision TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                disposition_id TEXT NOT NULL,
                recheck_id TEXT NOT NULL,
                recheck_revision INTEGER NOT NULL CHECK (recheck_revision >= 1),
                decision TEXT NOT NULL CHECK (decision IN ('confirmed', 'returned')),
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, artifact_id, extraction_revision),
                FOREIGN KEY (tenant_id, project_id, disposition_id)
                REFERENCES writing_reference_ocr_consistency_medical_disposition_records(
                    tenant_id, project_id, disposition_id
                )
            );

            CREATE INDEX IF NOT EXISTS idx_wref_ocr_recheck_latest
            ON writing_reference_ocr_consistency_qc_recheck_state(
                tenant_id, project_id, artifact_id, extraction_revision, revision DESC
            );
            CREATE INDEX IF NOT EXISTS idx_wref_ocr_recheck_artifact
            ON writing_reference_ocr_consistency_qc_recheck_records(
                tenant_id, project_id, artifact_id, extraction_revision, created_at DESC
            );
            CREATE INDEX IF NOT EXISTS idx_wref_ocr_disposition_current
            ON writing_reference_ocr_consistency_medical_disposition_state(
                tenant_id, project_id, artifact_id, extraction_revision, updated_at DESC
            );

            CREATE TRIGGER IF NOT EXISTS trg_wref_ocr_recheck_no_update
            BEFORE UPDATE ON writing_reference_ocr_consistency_qc_recheck_records BEGIN
                SELECT RAISE(ABORT, 'writing reference OCR consistency rechecks are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_wref_ocr_recheck_no_delete
            BEFORE DELETE ON writing_reference_ocr_consistency_qc_recheck_records BEGIN
                SELECT RAISE(ABORT, 'writing reference OCR consistency rechecks are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_wref_ocr_disposition_no_update
            BEFORE UPDATE ON writing_reference_ocr_consistency_medical_disposition_records BEGIN
                SELECT RAISE(ABORT, 'writing reference OCR consistency dispositions are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_wref_ocr_disposition_no_delete
            BEFORE DELETE ON writing_reference_ocr_consistency_medical_disposition_records BEGIN
                SELECT RAISE(ABORT, 'writing reference OCR consistency dispositions are immutable');
            END;
            """
        )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise WritingReferenceRepositoryError(
                f"sqlite integrity check failed during v8 migration: {integrity}"
            )
        foreign_key_issue = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchone()
        if foreign_key_issue is not None:
            raise WritingReferenceRepositoryError(
                "sqlite foreign key check failed during v8 migration"
            )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (8, _utc_now().isoformat()),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


class WritingReferenceRepository:
    """Domain-owned durable store for competitor-protocol writing references."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with _repository_initialization_lock(self.db_path):
            self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            return connection
        except Exception:
            connection.close()
            raise

    def _initialize(self) -> None:
        with self._connect() as connection:
            current_journal_mode = str(
                connection.execute("PRAGMA journal_mode").fetchone()[0]
            ).lower()
            if current_journal_mode != "wal":
                connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS writing_reference_search_snapshots (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, snapshot_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_relevance_records (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    nct_id TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    relevance_status TEXT NOT NULL CHECK (
                        relevance_status IN ('direct_competitor', 'indirect_reference', 'excluded')
                    ),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, decision_id),
                    UNIQUE (tenant_id, project_id, snapshot_id, nct_id, revision),
                    FOREIGN KEY (tenant_id, project_id, snapshot_id)
                    REFERENCES writing_reference_search_snapshots(tenant_id, project_id, snapshot_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_relevance_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    nct_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    decision_id TEXT NOT NULL,
                    relevance_status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, snapshot_id, nct_id),
                    FOREIGN KEY (tenant_id, project_id, decision_id)
                    REFERENCES writing_reference_relevance_records(tenant_id, project_id, decision_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_idempotency (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, operation, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS writing_reference_audit_chain (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, sequence_no),
                    UNIQUE (tenant_id, project_id, event_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_document_artifacts (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    nct_id TEXT NOT NULL,
                    source_document_id TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    storage_relpath TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, artifact_id),
                    UNIQUE (tenant_id, project_id, snapshot_id, nct_id, source_document_id, content_sha256),
                    FOREIGN KEY (tenant_id, project_id, snapshot_id)
                    REFERENCES writing_reference_search_snapshots(tenant_id, project_id, snapshot_id)
                );
                CREATE TABLE IF NOT EXISTS writing_reference_document_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    source_current INTEGER NOT NULL CHECK (source_current IN (0, 1)),
                    invalidation_reason TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, artifact_id),
                    FOREIGN KEY (tenant_id, project_id, artifact_id)
                    REFERENCES writing_reference_document_artifacts(tenant_id, project_id, artifact_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_security_scan_records (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    scan_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    verdict TEXT NOT NULL CHECK (verdict IN ('passed', 'blocked', 'error')),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, scan_id),
                    UNIQUE (tenant_id, project_id, artifact_id, revision),
                    FOREIGN KEY (tenant_id, project_id, artifact_id)
                    REFERENCES writing_reference_document_artifacts(tenant_id, project_id, artifact_id)
                );
                CREATE TABLE IF NOT EXISTS writing_reference_security_scan_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    scan_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, artifact_id),
                    FOREIGN KEY (tenant_id, project_id, scan_id)
                    REFERENCES writing_reference_security_scan_records(tenant_id, project_id, scan_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_extractions (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    extraction_revision TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, artifact_id, extraction_revision),
                    FOREIGN KEY (tenant_id, project_id, artifact_id)
                    REFERENCES writing_reference_document_artifacts(tenant_id, project_id, artifact_id)
                );
                CREATE TABLE IF NOT EXISTS writing_reference_source_spans (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    span_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    extraction_revision TEXT NOT NULL,
                    ich_m11_anchor TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, span_id),
                    FOREIGN KEY (tenant_id, project_id, artifact_id, extraction_revision)
                    REFERENCES writing_reference_extractions(tenant_id, project_id, artifact_id, extraction_revision)
                );
                CREATE TABLE IF NOT EXISTS writing_reference_extraction_review_records (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    extraction_revision TEXT NOT NULL,
                    review_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    decision TEXT NOT NULL CHECK (decision IN ('approved', 'returned')),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, review_id),
                    UNIQUE (tenant_id, project_id, artifact_id, extraction_revision, revision),
                    FOREIGN KEY (tenant_id, project_id, artifact_id, extraction_revision)
                    REFERENCES writing_reference_extractions(tenant_id, project_id, artifact_id, extraction_revision)
                );
                CREATE TABLE IF NOT EXISTS writing_reference_extraction_review_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    extraction_revision TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    review_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, artifact_id, extraction_revision),
                    FOREIGN KEY (tenant_id, project_id, review_id)
                    REFERENCES writing_reference_extraction_review_records(tenant_id, project_id, review_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_document_validation_records (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    validation_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    status TEXT NOT NULL CHECK (
                        status IN ('confirmed', 'needs_review', 'mismatch', 'user_overridden')
                    ),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, validation_id),
                    UNIQUE (tenant_id, project_id, artifact_id, revision),
                    FOREIGN KEY (tenant_id, project_id, artifact_id)
                    REFERENCES writing_reference_document_artifacts(tenant_id, project_id, artifact_id)
                );
                CREATE TABLE IF NOT EXISTS writing_reference_document_validation_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    validation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, artifact_id),
                    FOREIGN KEY (tenant_id, project_id, validation_id)
                    REFERENCES writing_reference_document_validation_records(tenant_id, project_id, validation_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_translation_records (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    translation_id TEXT NOT NULL,
                    span_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    fidelity_status TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, translation_id, revision),
                    FOREIGN KEY (tenant_id, project_id, span_id)
                    REFERENCES writing_reference_source_spans(tenant_id, project_id, span_id)
                );
                CREATE TABLE IF NOT EXISTS writing_reference_translation_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    translation_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    span_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, translation_id),
                    FOREIGN KEY (tenant_id, project_id, translation_id, revision)
                    REFERENCES writing_reference_translation_records(tenant_id, project_id, translation_id, revision)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_medical_review_records (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    review_id TEXT NOT NULL,
                    translation_id TEXT NOT NULL,
                    translation_revision INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    decision TEXT NOT NULL CHECK (decision IN ('approved', 'returned', 'rejected')),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, review_id),
                    UNIQUE (tenant_id, project_id, translation_id, translation_revision, revision),
                    FOREIGN KEY (tenant_id, project_id, translation_id, translation_revision)
                    REFERENCES writing_reference_translation_records(tenant_id, project_id, translation_id, revision)
                );
                CREATE TABLE IF NOT EXISTS writing_reference_medical_review_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    translation_id TEXT NOT NULL,
                    translation_revision INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    review_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, translation_id, translation_revision),
                    FOREIGN KEY (tenant_id, project_id, review_id)
                    REFERENCES writing_reference_medical_review_records(tenant_id, project_id, review_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_evidence_briefs (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    brief_id TEXT NOT NULL,
                    nct_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    span_id TEXT NOT NULL,
                    translation_id TEXT NOT NULL,
                    translation_revision INTEGER NOT NULL,
                    ich_m11_anchor TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, brief_id),
                    UNIQUE (tenant_id, project_id, translation_id, translation_revision)
                );

                -- Round 7: document-level structure plan, translation chunks,
                -- and chapter integration results.  These are immutable,
                -- migration-safe additive tables that carry the full lineage
                -- of the new document-plan/chunk/chapter-integration contract.
                CREATE TABLE IF NOT EXISTS writing_reference_document_structure_plans (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    extraction_revision TEXT NOT NULL,
                    document_sha256 TEXT NOT NULL,
                    document_role TEXT NOT NULL,
                    planner_model TEXT NOT NULL,
                    planner_prompt_version TEXT NOT NULL,
                    planner_input_hash TEXT NOT NULL,
                    planner_output_hash TEXT NOT NULL,
                    planner_contract_fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, plan_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_document_structure_plan_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    extraction_revision TEXT NOT NULL,
                    planner_contract_fingerprint TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, artifact_id, extraction_revision, planner_contract_fingerprint)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_translation_chunks (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    chunk_order INTEGER NOT NULL,
                    chunk_fingerprint TEXT NOT NULL,
                    source_span_ids_json TEXT NOT NULL,
                    source_text_sha256 TEXT NOT NULL,
                    adjacent_context_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, chunk_id),
                    UNIQUE (tenant_id, project_id, plan_id, chunk_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_translation_chunk_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, chunk_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_chapter_integration_results (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    integration_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    integrated_text_sha256 TEXT NOT NULL,
                    flash_model TEXT NOT NULL,
                    flash_prompt_version TEXT NOT NULL,
                    fidelity_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, integration_id),
                    UNIQUE (tenant_id, project_id, plan_id, chapter_id)
                );

                -- Round 8: auditable composite pipeline run ledger (not a fabricated
                -- provider run).  Queryable by run_id; immutable.
                CREATE TABLE IF NOT EXISTS writing_reference_composite_pipeline_runs (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, run_id)
                );

                -- Upper-layer DeepSeek execution ledger. Stage runs are
                -- immutable terminal facts. Escalations are server-owned
                -- state projections with a durable lease for restart recovery.
                CREATE TABLE IF NOT EXISTS writing_reference_upper_layer_stage_runs (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    stage_run_id TEXT NOT NULL,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    extraction_revision TEXT NOT NULL,
                    stage TEXT NOT NULL CHECK (
                        stage IN (
                            'document_planning',
                            'post_hy_mt2_integration_qc',
                            'corpus_selection_support'
                        )
                    ),
                    requested_model TEXT NOT NULL CHECK (
                        length(trim(requested_model)) > 0
                    ),
                    status TEXT NOT NULL,
                    execution_fingerprint TEXT NOT NULL,
                    prompt_sha256 TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    input_payload_json TEXT NOT NULL,
                    output_hash TEXT NOT NULL,
                    output_payload_json TEXT NOT NULL,
                    hy_mt2_target_map_sha256 TEXT NOT NULL,
                    parent_stage_run_id TEXT NOT NULL,
                    escalation_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, stage_run_id),
                    UNIQUE (tenant_id, project_id, execution_fingerprint)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_wref_upper_layer_pro_escalation
                    ON writing_reference_upper_layer_stage_runs(
                        tenant_id, project_id, escalation_id
                    )
                    WHERE escalation_id <> '';

                CREATE TABLE IF NOT EXISTS writing_reference_upper_layer_escalations (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    escalation_id TEXT NOT NULL,
                    source_stage_run_id TEXT NOT NULL,
                    target_stage_run_id TEXT NOT NULL,
                    stage TEXT NOT NULL CHECK (
                        stage IN (
                            'document_planning',
                            'post_hy_mt2_integration_qc'
                        )
                    ),
                    trigger_status TEXT NOT NULL CHECK (
                        trigger_status IN (
                            'failed_escalatable',
                            'completed_degraded'
                        )
                    ),
                    status TEXT NOT NULL CHECK (
                        status IN (
                            'queued',
                            'running',
                            'completed',
                            'failed_retryable',
                            'failed_terminal'
                        )
                    ),
                    request_fingerprint TEXT NOT NULL,
                    lineage_hash TEXT NOT NULL,
                    claim_token TEXT NOT NULL,
                    lease_expires_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, escalation_id),
                    UNIQUE (tenant_id, project_id, source_stage_run_id),
                    UNIQUE (tenant_id, project_id, target_stage_run_id),
                    FOREIGN KEY (tenant_id, project_id, source_stage_run_id)
                    REFERENCES writing_reference_upper_layer_stage_runs(
                        tenant_id, project_id, stage_run_id
                    )
                );

                CREATE TRIGGER IF NOT EXISTS trg_wref_search_no_update
                BEFORE UPDATE ON writing_reference_search_snapshots BEGIN
                    SELECT RAISE(ABORT, 'writing reference search snapshots are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_search_no_delete
                BEFORE DELETE ON writing_reference_search_snapshots BEGIN
                    SELECT RAISE(ABORT, 'writing reference search snapshots are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_relevance_record_no_update
                BEFORE UPDATE ON writing_reference_relevance_records BEGIN
                    SELECT RAISE(ABORT, 'writing reference relevance records are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_relevance_record_no_delete
                BEFORE DELETE ON writing_reference_relevance_records BEGIN
                    SELECT RAISE(ABORT, 'writing reference relevance records are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_document_artifact_no_update
                BEFORE UPDATE ON writing_reference_document_artifacts BEGIN
                    SELECT RAISE(ABORT, 'writing reference document artifacts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_document_artifact_no_delete
                BEFORE DELETE ON writing_reference_document_artifacts BEGIN
                    SELECT RAISE(ABORT, 'writing reference document artifacts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_security_record_no_update
                BEFORE UPDATE ON writing_reference_security_scan_records BEGIN
                    SELECT RAISE(ABORT, 'writing reference security records are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_extraction_no_update
                BEFORE UPDATE ON writing_reference_extractions BEGIN
                    SELECT RAISE(ABORT, 'writing reference extractions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_source_span_no_update
                BEFORE UPDATE ON writing_reference_source_spans BEGIN
                    SELECT RAISE(ABORT, 'writing reference source spans are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_extraction_review_no_update
                BEFORE UPDATE ON writing_reference_extraction_review_records BEGIN
                    SELECT RAISE(ABORT, 'writing reference extraction reviews are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_document_validation_no_update
                BEFORE UPDATE ON writing_reference_document_validation_records BEGIN
                    SELECT RAISE(ABORT, 'writing reference document validations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_translation_no_update
                BEFORE UPDATE ON writing_reference_translation_records BEGIN
                    SELECT RAISE(ABORT, 'writing reference translations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_medical_review_no_update
                BEFORE UPDATE ON writing_reference_medical_review_records BEGIN
                    SELECT RAISE(ABORT, 'writing reference medical reviews are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_doc_plan_no_update
                BEFORE UPDATE ON writing_reference_document_structure_plans BEGIN
                    SELECT RAISE(ABORT, 'writing reference document structure plans are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_doc_plan_no_delete
                BEFORE DELETE ON writing_reference_document_structure_plans BEGIN
                    SELECT RAISE(ABORT, 'writing reference document structure plans are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_chunk_no_update
                BEFORE UPDATE ON writing_reference_translation_chunks BEGIN
                    SELECT RAISE(ABORT, 'writing reference translation chunks are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_chunk_no_delete
                BEFORE DELETE ON writing_reference_translation_chunks BEGIN
                    SELECT RAISE(ABORT, 'writing reference translation chunks are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_integration_no_update
                BEFORE UPDATE ON writing_reference_chapter_integration_results BEGIN
                    SELECT RAISE(ABORT, 'writing reference chapter integration results are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_integration_no_delete
                BEFORE DELETE ON writing_reference_chapter_integration_results BEGIN
                    SELECT RAISE(ABORT, 'writing reference chapter integration results are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_composite_run_no_update
                BEFORE UPDATE ON writing_reference_composite_pipeline_runs BEGIN
                    SELECT RAISE(ABORT, 'writing reference composite pipeline runs are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_composite_run_no_delete
                BEFORE DELETE ON writing_reference_composite_pipeline_runs BEGIN
                    SELECT RAISE(ABORT, 'writing reference composite pipeline runs are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_upper_layer_run_no_update
                BEFORE UPDATE ON writing_reference_upper_layer_stage_runs BEGIN
                    SELECT RAISE(ABORT, 'writing reference upper-layer stage runs are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_upper_layer_run_no_delete
                BEFORE DELETE ON writing_reference_upper_layer_stage_runs BEGIN
                    SELECT RAISE(ABORT, 'writing reference upper-layer stage runs are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_upper_layer_escalation_no_delete
                BEFORE DELETE ON writing_reference_upper_layer_escalations BEGIN
                    SELECT RAISE(ABORT, 'writing reference upper-layer escalations cannot be deleted');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_audit_no_update
                BEFORE UPDATE ON writing_reference_audit_chain BEGIN
                    SELECT RAISE(ABORT, 'writing reference audit chain is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_audit_no_delete
                BEFORE DELETE ON writing_reference_audit_chain BEGIN
                    SELECT RAISE(ABORT, 'writing reference audit chain is immutable');
                END;

                CREATE TABLE IF NOT EXISTS competitor_triage_runs (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    journey_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, run_id),
                    FOREIGN KEY (tenant_id, project_id, snapshot_id)
                    REFERENCES writing_reference_search_snapshots(tenant_id, project_id, snapshot_id)
                );
                CREATE INDEX IF NOT EXISTS idx_ct_runs_snapshot
                    ON competitor_triage_runs(tenant_id, project_id, snapshot_id);

                CREATE TABLE IF NOT EXISTS competitor_triage_confirmations (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    confirmation_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    confirmation_hash TEXT NOT NULL,
                    projection_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, confirmation_id),
                    FOREIGN KEY (tenant_id, project_id, run_id)
                    REFERENCES competitor_triage_runs(tenant_id, project_id, run_id)
                );
                COMMIT;
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            try:
                version = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                    ).fetchone()[0]
                )
                if version > SCHEMA_VERSION:
                    raise WritingReferenceRepositoryError(
                        f"writing reference schema {version} is newer than supported {SCHEMA_VERSION}"
                    )
                for marker in range(1, 6):
                    if version < marker:
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO schema_migrations(version, applied_at)
                            VALUES (?, ?)
                            """,
                            (marker, _utc_now().isoformat()),
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            version = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()[0]
            )
            if version < 6:
                _migrate_upper_layer_route_identity_v6(connection)
            _migrate_workspace_query_indexes_v7(connection)
            version = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()[0]
            )
            if version < 8:
                _migrate_ocr_consistency_qc_v8(connection)
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise WritingReferenceRepositoryError(f"sqlite integrity check failed: {integrity}")
            foreign_key_issue = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchone()
            if foreign_key_issue is not None:
                raise WritingReferenceRepositoryError(
                    "sqlite foreign key check failed after schema migration"
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO writing_reference_document_state(
                    tenant_id, project_id, artifact_id, revision,
                    source_current, invalidation_reason, updated_at
                )
                SELECT tenant_id, project_id, artifact_id, 1, 1, '', created_at
                FROM writing_reference_document_artifacts
                """
            )

    def save_search_snapshot(
        self,
        snapshot: WritingReferenceSearchSnapshot,
        *,
        idempotency_key: str,
    ) -> WritingReferenceSearchSnapshot:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        payload = snapshot.model_dump(mode="json")
        payload_hash = _payload_hash(payload)
        request_hash = _payload_hash(
            snapshot.model_dump(mode="json", exclude={"created_at"})
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT result_id FROM writing_reference_idempotency
                WHERE tenant_id=? AND project_id=? AND operation='save_search_snapshot'
                  AND idempotency_key=?
                """,
                (TENANT_ID, snapshot.project_id, idempotency_key),
            ).fetchone()
            if replay is not None:
                existing_snapshot = self._search_snapshot_with(
                    connection, snapshot.project_id, str(replay["result_id"])
                )
                existing_request_hash = _payload_hash(
                    existing_snapshot.model_dump(mode="json", exclude={"created_at"})
                )
                if existing_request_hash != request_hash:
                    connection.rollback()
                    raise WritingReferenceConflictError(
                        "idempotency key reused with different request"
                    )
                connection.rollback()
                return existing_snapshot
            existing = connection.execute(
                """
                SELECT payload_hash, payload_json
                FROM writing_reference_search_snapshots
                WHERE tenant_id = ? AND project_id = ? AND snapshot_id = ?
                """,
                (TENANT_ID, snapshot.project_id, snapshot.snapshot_id),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_hash"]) != payload_hash:
                    connection.rollback()
                    raise WritingReferenceConflictError("immutable search snapshot payload changed")
                result = WritingReferenceSearchSnapshot.model_validate_json(existing["payload_json"])
            else:
                connection.execute(
                    """
                    INSERT INTO writing_reference_search_snapshots(
                        tenant_id, project_id, snapshot_id, payload_hash, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        TENANT_ID,
                        snapshot.project_id,
                        snapshot.snapshot_id,
                        payload_hash,
                        _canonical_json(payload),
                        snapshot.created_at.isoformat(),
                    ),
                )
                result = snapshot
            self._record_idempotency(
                connection,
                snapshot.project_id,
                "save_search_snapshot",
                idempotency_key,
                request_hash,
                snapshot.snapshot_id,
            )
            self._append_audit(connection, snapshot.project_id, "search_snapshot_saved", snapshot.snapshot_id, snapshot.created_by, {"total_count": snapshot.total_count, "returned_count": snapshot.returned_count})
            connection.commit()
            return result

    def search_snapshot(self, project_id: str, snapshot_id: str) -> WritingReferenceSearchSnapshot:
        with self._connect() as connection:
            return self._search_snapshot_with(connection, project_id, snapshot_id)

    def latest_search_snapshot(self, project_id: str) -> WritingReferenceSearchSnapshot:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM writing_reference_search_snapshots WHERE tenant_id=? AND project_id=? ORDER BY created_at DESC, snapshot_id DESC LIMIT 1",
                (TENANT_ID, project_id),
            ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return WritingReferenceSearchSnapshot.model_validate_json(row["payload_json"])

    def relevance_decisions_for_snapshot(self, project_id: str, snapshot_id: str) -> list[WritingReferenceRelevanceDecision]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record.payload_json
                FROM writing_reference_relevance_state AS state
                JOIN writing_reference_relevance_records AS record
                  ON record.tenant_id=state.tenant_id AND record.project_id=state.project_id
                 AND record.decision_id=state.decision_id
                WHERE state.tenant_id=? AND state.project_id=? AND state.snapshot_id=?
                ORDER BY state.nct_id
                """,
                (TENANT_ID, project_id, snapshot_id),
            ).fetchall()
        return [WritingReferenceRelevanceDecision.model_validate_json(row["payload_json"]) for row in rows]

    def _search_snapshot_with(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        snapshot_id: str,
    ) -> WritingReferenceSearchSnapshot:
        row = connection.execute(
            """
            SELECT payload_json FROM writing_reference_search_snapshots
            WHERE tenant_id = ? AND project_id = ? AND snapshot_id = ?
            """,
            (TENANT_ID, project_id, snapshot_id),
        ).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        return WritingReferenceSearchSnapshot.model_validate_json(row["payload_json"])

    def record_relevance_decision(
        self,
        *,
        project_id: str,
        snapshot_id: str,
        nct_id: str,
        relevance_status: str,
        reason: str,
        actor: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> WritingReferenceRelevanceDecision:
        if relevance_status not in RELEVANCE_STATUSES:
            raise ValueError("invalid relevance_status")
        if not reason.strip():
            raise ValueError("medical relevance reason is required")
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        snapshot = self.search_snapshot(project_id, snapshot_id)
        if nct_id not in {item.nct_id for item in snapshot.candidates}:
            raise ValueError("candidate does not belong to search snapshot")
        semantic_request = {
            "project_id": project_id,
            "snapshot_id": snapshot_id,
            "nct_id": nct_id,
            "relevance_status": relevance_status,
            "reason": reason.strip(),
            "actor": actor,
            "expected_revision": expected_revision,
        }
        request_hash = _payload_hash(semantic_request)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay_id = self._idempotent_result(
                connection,
                project_id,
                "record_relevance_decision",
                idempotency_key,
                request_hash,
            )
            if replay_id is not None:
                row = connection.execute(
                    """
                    SELECT payload_json FROM writing_reference_relevance_records
                    WHERE tenant_id = ? AND project_id = ? AND decision_id = ?
                    """,
                    (TENANT_ID, project_id, replay_id),
                ).fetchone()
                connection.rollback()
                if row is None:
                    raise WritingReferenceRepositoryError("idempotency result is missing")
                return WritingReferenceRelevanceDecision.model_validate_json(row["payload_json"])
            state = connection.execute(
                """
                SELECT revision FROM writing_reference_relevance_state
                WHERE tenant_id = ? AND project_id = ? AND snapshot_id = ? AND nct_id = ?
                """,
                (TENANT_ID, project_id, snapshot_id, nct_id),
            ).fetchone()
            actual_revision = int(state["revision"]) if state is not None else 0
            if actual_revision != expected_revision:
                connection.rollback()
                raise WritingReferenceStaleStateError(
                    f"stale relevance revision: expected={expected_revision}, actual={actual_revision}"
                )
            revision = actual_revision + 1
            created_at = _utc_now()
            decision_id = "wref_rel_" + _payload_hash(
                {**semantic_request, "revision": revision}
            )[:20]
            decision = WritingReferenceRelevanceDecision(
                decision_id=decision_id,
                project_id=project_id,
                snapshot_id=snapshot_id,
                nct_id=nct_id,
                relevance_status=relevance_status,
                reason=reason.strip(),
                revision=revision,
                actor=actor,
                created_at=created_at,
            )
            connection.execute(
                """
                INSERT INTO writing_reference_relevance_records(
                    tenant_id, project_id, snapshot_id, nct_id, decision_id,
                    revision, relevance_status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    project_id,
                    snapshot_id,
                    nct_id,
                    decision_id,
                    revision,
                    relevance_status,
                    _canonical_json(decision.model_dump(mode="json")),
                    created_at.isoformat(),
                ),
            )
            if state is None:
                connection.execute(
                    """
                    INSERT INTO writing_reference_relevance_state(
                        tenant_id, project_id, snapshot_id, nct_id, revision,
                        decision_id, relevance_status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        TENANT_ID, project_id, snapshot_id, nct_id, revision,
                        decision_id, relevance_status, created_at.isoformat(),
                    ),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE writing_reference_relevance_state
                    SET revision = ?, decision_id = ?, relevance_status = ?, updated_at = ?
                    WHERE tenant_id = ? AND project_id = ? AND snapshot_id = ?
                      AND nct_id = ? AND revision = ?
                    """,
                    (
                        revision, decision_id, relevance_status, created_at.isoformat(),
                        TENANT_ID, project_id, snapshot_id, nct_id, expected_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise WritingReferenceStaleStateError("relevance state changed concurrently")
            self._record_idempotency(
                connection,
                project_id,
                "record_relevance_decision",
                idempotency_key,
                request_hash,
                decision_id,
            )
            self._append_audit(connection, project_id, "medical_relevance_decided", decision_id, actor, {"snapshot_id": snapshot_id, "nct_id": nct_id, "relevance_status": relevance_status, "revision": revision})
            connection.commit()
            return decision

    def relevance_decision(
        self,
        project_id: str,
        snapshot_id: str,
        nct_id: str,
    ) -> WritingReferenceRelevanceDecision:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT record.payload_json
                FROM writing_reference_relevance_state AS state
                JOIN writing_reference_relevance_records AS record
                  ON record.tenant_id = state.tenant_id
                 AND record.project_id = state.project_id
                 AND record.decision_id = state.decision_id
                WHERE state.tenant_id = ? AND state.project_id = ?
                  AND state.snapshot_id = ? AND state.nct_id = ?
                """,
                (TENANT_ID, project_id, snapshot_id, nct_id),
            ).fetchone()
        if row is None:
            raise KeyError(nct_id)
        return WritingReferenceRelevanceDecision.model_validate_json(row["payload_json"])

    def save_document_artifact(
        self,
        artifact: WritingReferenceDocumentArtifact,
        *,
        storage_relpath: str,
        idempotency_key: str,
    ) -> WritingReferenceDocumentArtifact:
        if not storage_relpath or storage_relpath.startswith("/") or ".." in Path(storage_relpath).parts:
            raise ValueError("artifact storage path must be a safe relative path")
        payload = artifact.model_dump(mode="json")
        semantic_payload = dict(payload)
        semantic_payload.pop("created_at", None)
        request_hash = _payload_hash(
            {
                "artifact": semantic_payload,
                "storage_relpath": storage_relpath,
            }
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay_id = self._idempotent_result(
                connection,
                artifact.project_id,
                "save_document_artifact",
                idempotency_key,
                request_hash,
            )
            if replay_id is not None:
                connection.rollback()
                return self._document_artifact_with(connection, artifact.project_id, replay_id)
            existing = connection.execute(
                """
                SELECT payload_hash, payload_json
                FROM writing_reference_document_artifacts
                WHERE tenant_id = ? AND project_id = ? AND artifact_id = ?
                """,
                (TENANT_ID, artifact.project_id, artifact.artifact_id),
            ).fetchone()
            if existing is not None:
                existing_payload = json.loads(str(existing["payload_json"]))
                existing_semantic_payload = dict(existing_payload)
                existing_semantic_payload.pop("created_at", None)
                if _payload_hash(existing_semantic_payload) != _payload_hash(semantic_payload):
                    connection.rollback()
                    raise WritingReferenceConflictError("immutable document artifact changed")
                result = self._artifact_from_payload(existing["payload_json"])
            else:
                connection.execute(
                    """
                    INSERT INTO writing_reference_document_artifacts(
                        tenant_id, project_id, artifact_id, snapshot_id, nct_id,
                        source_document_id, content_sha256, storage_relpath,
                        payload_hash, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        TENANT_ID,
                        artifact.project_id,
                        artifact.artifact_id,
                        artifact.snapshot_id,
                        artifact.nct_id,
                        artifact.source_document_id,
                        artifact.content_sha256,
                        storage_relpath,
                        _payload_hash(payload),
                        _canonical_json(payload),
                        artifact.created_at.isoformat(),
                    ),
                )
                connection.execute(
                    "INSERT INTO writing_reference_document_state VALUES (?, ?, ?, 1, 1, '', ?)",
                    (TENANT_ID, artifact.project_id, artifact.artifact_id, artifact.created_at.isoformat()),
                )
                result = artifact
            self._record_idempotency(
                connection,
                artifact.project_id,
                "save_document_artifact",
                idempotency_key,
                request_hash,
                artifact.artifact_id,
            )
            event_type = (
                "manual_document_uploaded"
                if artifact.source_status == "user_uploaded"
                else "public_document_ingested"
            )
            self._append_audit(connection, artifact.project_id, event_type, artifact.artifact_id, artifact.created_by, {"snapshot_id": artifact.snapshot_id, "nct_id": artifact.nct_id, "content_sha256": artifact.content_sha256, "document_type": artifact.document_type})
            connection.commit()
            return result

    def document_artifact(
        self,
        project_id: str,
        artifact_id: str,
    ) -> WritingReferenceDocumentArtifact:
        with self._connect() as connection:
            return self._document_artifact_with(connection, project_id, artifact_id)

    def document_artifacts(self, project_id: str, snapshot_id: Optional[str] = None) -> list[WritingReferenceDocumentArtifact]:
        query = """
            SELECT artifact.payload_json, state.revision AS state_revision,
                   state.source_current, state.invalidation_reason
            FROM writing_reference_document_artifacts AS artifact
            JOIN writing_reference_document_state AS state
              ON state.tenant_id=artifact.tenant_id
             AND state.project_id=artifact.project_id
             AND state.artifact_id=artifact.artifact_id
            WHERE artifact.tenant_id=? AND artifact.project_id=?
        """
        params: list[Any] = [TENANT_ID, project_id]
        if snapshot_id:
            query += " AND artifact.snapshot_id=?"
            params.append(snapshot_id)
        query += " ORDER BY artifact.created_at, artifact.artifact_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._artifact_projection(row) for row in rows]

    def artifact_storage_relpath(self, project_id: str, artifact_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT storage_relpath FROM writing_reference_document_artifacts WHERE tenant_id=? AND project_id=? AND artifact_id=?",
                (TENANT_ID, project_id, artifact_id),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return str(row["storage_relpath"])

    def invalidate_artifact(
        self, *, project_id: str, artifact_id: str, reason: str, actor: str,
        expected_revision: int, idempotency_key: str,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("invalidation reason is required")
        self.document_artifact(project_id, artifact_id)
        semantic = {"artifact_id": artifact_id, "reason": reason.strip(), "actor": actor, "expected_revision": expected_revision}
        request_hash = _payload_hash(semantic)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(connection, project_id, "invalidate_artifact", idempotency_key, request_hash)
            if replay:
                row = connection.execute("SELECT revision, source_current, invalidation_reason FROM writing_reference_document_state WHERE tenant_id=? AND project_id=? AND artifact_id=?", (TENANT_ID, project_id, artifact_id)).fetchone()
                connection.rollback()
                return {"artifact_id": artifact_id, "revision": int(row["revision"]), "source_current": bool(row["source_current"]), "invalidation_reason": str(row["invalidation_reason"]), "replayed": True}
            state = connection.execute("SELECT revision, source_current FROM writing_reference_document_state WHERE tenant_id=? AND project_id=? AND artifact_id=?", (TENANT_ID, project_id, artifact_id)).fetchone()
            if state is None:
                connection.rollback()
                raise KeyError(artifact_id)
            actual = int(state["revision"])
            if actual != expected_revision:
                connection.rollback()
                raise WritingReferenceStaleStateError(f"stale artifact revision: expected={expected_revision}, actual={actual}")
            if not bool(state["source_current"]):
                connection.rollback()
                raise WritingReferenceConflictError("artifact is already invalidated")
            revision = actual + 1
            now = _utc_now().isoformat()
            cursor = connection.execute(
                "UPDATE writing_reference_document_state SET revision=?, source_current=0, invalidation_reason=?, updated_at=? WHERE tenant_id=? AND project_id=? AND artifact_id=? AND revision=? AND source_current=1",
                (revision, reason.strip(), now, TENANT_ID, project_id, artifact_id, expected_revision),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise WritingReferenceStaleStateError("artifact state changed concurrently")
            translation_cursor = connection.execute(
                """
                UPDATE writing_reference_translation_state
                SET status='invalidated_source', updated_at=?
                WHERE tenant_id=? AND project_id=? AND span_id IN (
                    SELECT span_id FROM writing_reference_source_spans
                    WHERE tenant_id=? AND project_id=? AND artifact_id=?
                )
                """,
                (now, TENANT_ID, project_id, TENANT_ID, project_id, artifact_id),
            )
            brief_cursor = connection.execute(
                "UPDATE writing_reference_evidence_briefs SET status='invalidated_source' WHERE tenant_id=? AND project_id=? AND artifact_id=? AND status='approved_current'",
                (TENANT_ID, project_id, artifact_id),
            )
            self._record_idempotency(connection, project_id, "invalidate_artifact", idempotency_key, request_hash, artifact_id)
            self._append_audit(connection, project_id, "source_artifact_invalidated", artifact_id, actor, {"reason": reason.strip(), "revision": revision, "translation_count": translation_cursor.rowcount, "brief_count": brief_cursor.rowcount})
            connection.commit()
            return {"artifact_id": artifact_id, "revision": revision, "source_current": False, "invalidation_reason": reason.strip(), "invalidated_translation_count": translation_cursor.rowcount, "invalidated_brief_count": brief_cursor.rowcount, "replayed": False}

    @staticmethod
    def _document_artifact_with(
        connection: sqlite3.Connection,
        project_id: str,
        artifact_id: str,
    ) -> WritingReferenceDocumentArtifact:
        row = connection.execute(
            """
            SELECT artifact.payload_json, state.revision AS state_revision,
                   state.source_current, state.invalidation_reason
            FROM writing_reference_document_artifacts AS artifact
            JOIN writing_reference_document_state AS state
              ON state.tenant_id=artifact.tenant_id
             AND state.project_id=artifact.project_id
             AND state.artifact_id=artifact.artifact_id
            WHERE artifact.tenant_id = ? AND artifact.project_id = ?
              AND artifact.artifact_id = ?
            """,
            (TENANT_ID, project_id, artifact_id),
        ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return WritingReferenceRepository._artifact_projection(row)

    @staticmethod
    def _artifact_from_payload(payload_json: str) -> WritingReferenceDocumentArtifact:
        payload = json.loads(payload_json)
        payload.pop("security_status", None)
        payload.setdefault("file_integrity_status", "verified")
        return WritingReferenceDocumentArtifact.model_validate(payload)

    @staticmethod
    def _artifact_projection(row: sqlite3.Row) -> WritingReferenceDocumentArtifact:
        return WritingReferenceRepository._artifact_from_payload(row["payload_json"]).model_copy(
            update={
                "source_current": bool(row["source_current"]),
                "state_revision": int(row["state_revision"]),
                "invalidation_reason": str(row["invalidation_reason"] or ""),
            }
        )

    def save_extraction(self, result: WritingReferenceExtractionResult, *, idempotency_key: str) -> WritingReferenceExtractionResult:
        with self._connect() as connection:
            artifact = self._document_artifact_with(connection, result.project_id, result.artifact_id)
            if not artifact.source_current:
                raise ValueError("current source document is required for extraction")
            payload = result.model_dump(mode="json")
            request_hash = _payload_hash(payload)
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(connection, result.project_id, "save_extraction", idempotency_key, request_hash)
            if replay:
                row = connection.execute(
                    "SELECT payload_json FROM writing_reference_extractions WHERE tenant_id=? AND project_id=? AND artifact_id=? AND extraction_revision=?",
                    (TENANT_ID, result.project_id, result.artifact_id, replay),
                ).fetchone()
                connection.rollback()
                return WritingReferenceExtractionResult.model_validate_json(row["payload_json"])
            existing = connection.execute(
                "SELECT payload_hash, payload_json FROM writing_reference_extractions WHERE tenant_id=? AND project_id=? AND artifact_id=? AND extraction_revision=?",
                (TENANT_ID, result.project_id, result.artifact_id, result.extraction_revision),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_hash"]) != request_hash:
                    connection.rollback()
                    raise WritingReferenceConflictError("immutable document extraction changed")
                self._record_idempotency(
                    connection,
                    result.project_id,
                    "save_extraction",
                    idempotency_key,
                    request_hash,
                    result.extraction_revision,
                )
                connection.commit()
                return WritingReferenceExtractionResult.model_validate_json(existing["payload_json"])
            now = _utc_now().isoformat()
            connection.execute(
                "INSERT INTO writing_reference_extractions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (TENANT_ID, result.project_id, result.artifact_id, result.extraction_revision, request_hash, _canonical_json(payload), now),
            )
            for span in result.spans:
                if span.project_id != result.project_id or span.artifact_id != result.artifact_id or span.extraction_revision != result.extraction_revision:
                    connection.rollback()
                    raise ValueError("extraction span lineage mismatch")
                connection.execute(
                    "INSERT INTO writing_reference_source_spans VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (TENANT_ID, result.project_id, span.span_id, result.artifact_id, result.extraction_revision, span.ich_m11_anchor, _canonical_json(span.model_dump(mode="json")), now),
                )
            invalidated_translation_count = connection.execute(
                """
                UPDATE writing_reference_translation_state
                SET status='invalidated_extraction', updated_at=?
                WHERE tenant_id=? AND project_id=? AND span_id IN (
                    SELECT span_id FROM writing_reference_source_spans
                    WHERE tenant_id=? AND project_id=? AND artifact_id=?
                      AND extraction_revision<>?
                ) AND status<>'invalidated_source'
                """,
                (
                    now,
                    TENANT_ID,
                    result.project_id,
                    TENANT_ID,
                    result.project_id,
                    result.artifact_id,
                    result.extraction_revision,
                ),
            ).rowcount
            invalidated_brief_count = connection.execute(
                """
                UPDATE writing_reference_evidence_briefs
                SET status='invalidated_extraction'
                WHERE tenant_id=? AND project_id=? AND status='approved_current'
                  AND translation_id IN (
                    SELECT state.translation_id
                    FROM writing_reference_translation_state AS state
                    JOIN writing_reference_source_spans AS span
                      ON span.tenant_id=state.tenant_id
                     AND span.project_id=state.project_id
                     AND span.span_id=state.span_id
                    WHERE state.tenant_id=? AND state.project_id=?
                      AND span.artifact_id=? AND span.extraction_revision<>?
                  )
                """,
                (
                    TENANT_ID,
                    result.project_id,
                    TENANT_ID,
                    result.project_id,
                    result.artifact_id,
                    result.extraction_revision,
                ),
            ).rowcount
            self._record_idempotency(connection, result.project_id, "save_extraction", idempotency_key, request_hash, result.extraction_revision)
            self._append_audit(connection, result.project_id, "document_extraction_saved", result.extraction_revision, "system_extractor", {"artifact_id": result.artifact_id, "span_count": len(result.spans), "status": result.status, "invalidated_translation_count": invalidated_translation_count, "invalidated_brief_count": invalidated_brief_count})
            connection.commit()
            return result

    def saved_extraction_for_idempotency(
        self,
        project_id: str,
        artifact_id: str,
        *,
        idempotency_key: str,
    ) -> Optional[WritingReferenceExtractionResult]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT extraction.artifact_id, extraction.payload_json
                FROM writing_reference_idempotency AS replay
                JOIN writing_reference_extractions AS extraction
                  ON extraction.tenant_id = replay.tenant_id
                 AND extraction.project_id = replay.project_id
                 AND extraction.extraction_revision = replay.result_id
                WHERE replay.tenant_id = ?
                  AND replay.project_id = ?
                  AND replay.operation = 'save_extraction'
                  AND replay.idempotency_key = ?
                """,
                (TENANT_ID, project_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        if str(row["artifact_id"]) != artifact_id:
            raise WritingReferenceConflictError(
                "extraction idempotency key belongs to a different artifact"
            )
        return WritingReferenceExtractionResult.model_validate_json(
            row["payload_json"]
        )

    def source_span(self, project_id: str, span_id: str):
        from packages.contracts.workbench_contracts import WritingReferenceExtractedSpan
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM writing_reference_source_spans WHERE tenant_id=? AND project_id=? AND span_id=?",
                (TENANT_ID, project_id, span_id),
            ).fetchone()
        if row is None:
            raise KeyError(span_id)
        return WritingReferenceExtractedSpan.model_validate_json(row["payload_json"])

    def latest_extraction_revision(self, project_id: str, artifact_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT extraction_revision
                FROM writing_reference_extractions
                WHERE tenant_id=? AND project_id=? AND artifact_id=?
                ORDER BY created_at DESC, extraction_revision DESC
                LIMIT 1
                """,
                (TENANT_ID, project_id, artifact_id),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return str(row["extraction_revision"])

    def extraction_result(
        self,
        project_id: str,
        artifact_id: str,
        extraction_revision: str,
    ):
        from packages.contracts.workbench_contracts import (
            WritingReferenceExtractionResult,
        )

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_extractions
                WHERE tenant_id=? AND project_id=? AND artifact_id=?
                  AND extraction_revision=?
                """,
                (
                    TENANT_ID,
                    project_id,
                    artifact_id,
                    extraction_revision,
                ),
            ).fetchone()
        if row is None:
            raise KeyError(extraction_revision)
        return WritingReferenceExtractionResult.model_validate_json(
            row["payload_json"]
        )

    def source_spans(
        self,
        project_id: str,
        artifact_id: Optional[str] = None,
        *,
        extraction_revision: Optional[str] = None,
        ich_m11_anchor: Optional[str] = None,
    ) -> list[Any]:
        from packages.contracts.workbench_contracts import WritingReferenceExtractedSpan
        if extraction_revision and not artifact_id:
            raise ValueError("artifact_id is required when extraction_revision is specified")
        query = "SELECT payload_json FROM writing_reference_source_spans WHERE tenant_id=? AND project_id=?"
        params: list[Any] = [TENANT_ID, project_id]
        if artifact_id:
            query += " AND artifact_id=?"
            params.append(artifact_id)
        if extraction_revision:
            query += " AND extraction_revision=?"
            params.append(extraction_revision)
        if ich_m11_anchor:
            query += " AND ich_m11_anchor=?"
            params.append(ich_m11_anchor)
        query += " ORDER BY artifact_id, extraction_revision, span_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        spans = [WritingReferenceExtractedSpan.model_validate_json(row["payload_json"]) for row in rows]
        return sorted(
            spans,
            key=lambda item: (item.artifact_id, item.physical_page, item.block_index, item.span_id),
        )

    def source_span_counts(
        self,
        project_id: str,
        snapshot_id: Optional[str] = None,
    ) -> dict[str, int]:
        snapshot_filter = ""
        params: list[Any] = [TENANT_ID, project_id]
        if snapshot_id:
            snapshot_filter = " AND artifact.snapshot_id=?"
            params.append(snapshot_id)
        params.extend([TENANT_ID, project_id])
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                WITH latest_extractions AS (
                    SELECT artifact_id, extraction_revision
                    FROM (
                        SELECT extraction.artifact_id,
                               extraction.extraction_revision,
                               ROW_NUMBER() OVER (
                                   PARTITION BY extraction.artifact_id
                                   ORDER BY extraction.created_at DESC,
                                            extraction.extraction_revision DESC
                               ) AS position
                        FROM writing_reference_extractions AS extraction
                        JOIN writing_reference_document_artifacts AS artifact
                          ON artifact.tenant_id=extraction.tenant_id
                         AND artifact.project_id=extraction.project_id
                         AND artifact.artifact_id=extraction.artifact_id
                        WHERE extraction.tenant_id=?
                          AND extraction.project_id=?
                          {snapshot_filter}
                    )
                    WHERE position=1
                )
                SELECT span.artifact_id, COUNT(*) AS span_count
                FROM writing_reference_source_spans AS span
                JOIN latest_extractions AS latest
                  ON latest.artifact_id=span.artifact_id
                 AND latest.extraction_revision=span.extraction_revision
                WHERE span.tenant_id=? AND span.project_id=?
                GROUP BY span.artifact_id
                """,
                params,
            ).fetchall()
        return {str(row["artifact_id"]): int(row["span_count"]) for row in rows}

    @staticmethod
    def _base_ocr_verdict(extraction_payload: str) -> str:
        payload = json.loads(extraction_payload)
        verdict = str((payload.get("ocr_consistency_qc") or {}).get("verdict") or "pass")
        return verdict if verdict in {"pass", "review_required", "fail"} else "review_required"

    @staticmethod
    def _ocr_recheck_from_row(row: sqlite3.Row) -> WritingReferenceOcrConsistencyQcRecheck:
        return WritingReferenceOcrConsistencyQcRecheck.model_validate_json(row["payload_json"])

    def save_ocr_consistency_qc_recheck(
        self,
        recheck: WritingReferenceOcrConsistencyQcRecheck,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> WritingReferenceOcrConsistencyQcRecheck:
        if expected_revision < 0 or recheck.revision < 1:
            raise ValueError("recheck revision must be positive")
        if not idempotency_key.strip() or not recheck.base_qc_identity_hash.strip():
            raise ValueError("recheck idempotency and base identity are required")
        payload = recheck.model_dump(mode="json")
        request_hash = _semantic_payload_hash({"recheck": payload, "expected_revision": expected_revision})
        operation = "save_ocr_consistency_qc_recheck"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(connection, recheck.project_id, operation, idempotency_key, request_hash)
            if replay is not None:
                row = connection.execute(
                    "SELECT payload_json FROM writing_reference_ocr_consistency_qc_recheck_records WHERE tenant_id=? AND project_id=? AND recheck_id=?",
                    (TENANT_ID, recheck.project_id, replay),
                ).fetchone()
                connection.rollback()
                if row is None:
                    raise WritingReferenceRepositoryError("OCR recheck idempotency result is missing")
                return self._ocr_recheck_from_row(row)
            artifact = self._document_artifact_with(connection, recheck.project_id, recheck.artifact_id)
            if not artifact.source_current:
                connection.rollback()
                raise ValueError("current source document is required for OCR recheck")
            extraction_row = connection.execute(
                "SELECT payload_json FROM writing_reference_extractions WHERE tenant_id=? AND project_id=? AND artifact_id=? AND extraction_revision=?",
                (TENANT_ID, recheck.project_id, recheck.artifact_id, recheck.extraction_revision),
            ).fetchone()
            if extraction_row is None:
                connection.rollback()
                raise KeyError(recheck.extraction_revision)
            latest_row = connection.execute(
                "SELECT extraction_revision FROM writing_reference_extractions WHERE tenant_id=? AND project_id=? AND artifact_id=? ORDER BY created_at DESC, extraction_revision DESC LIMIT 1",
                (TENANT_ID, recheck.project_id, recheck.artifact_id),
            ).fetchone()
            if latest_row is None or str(latest_row["extraction_revision"]) != recheck.extraction_revision:
                connection.rollback()
                raise WritingReferenceStaleStateError("OCR recheck must target the latest extraction revision")
            base_qc = json.loads(str(extraction_row["payload_json"])).get("ocr_consistency_qc") or {}
            base_identity_hash = str(base_qc.get("identity_hash") or _payload_hash(base_qc))
            if recheck.base_qc_identity_hash != base_identity_hash:
                connection.rollback()
                raise WritingReferenceConflictError("OCR recheck base QC identity does not match extraction")
            existing = connection.execute(
                "SELECT payload_json FROM writing_reference_ocr_consistency_qc_recheck_records WHERE tenant_id=? AND project_id=? AND recheck_id=?",
                (TENANT_ID, recheck.project_id, recheck.recheck_id),
            ).fetchone()
            if existing is not None:
                stored = self._ocr_recheck_from_row(existing)
                if _semantic_payload_hash(stored.model_dump(mode="json")) != _semantic_payload_hash(payload):
                    connection.rollback()
                    raise WritingReferenceConflictError("immutable OCR recheck changed")
                self._record_idempotency(connection, recheck.project_id, operation, idempotency_key, request_hash, recheck.recheck_id)
                connection.commit()
                return stored
            state = connection.execute(
                "SELECT revision FROM writing_reference_ocr_consistency_qc_recheck_state WHERE tenant_id=? AND project_id=? AND artifact_id=? AND extraction_revision=?",
                (TENANT_ID, recheck.project_id, recheck.artifact_id, recheck.extraction_revision),
            ).fetchone()
            actual_revision = int(state["revision"]) if state else 0
            if actual_revision != expected_revision:
                connection.rollback()
                raise WritingReferenceStaleStateError(f"stale OCR recheck revision: expected={expected_revision}, actual={actual_revision}")
            if recheck.revision != actual_revision + 1:
                connection.rollback()
                raise WritingReferenceStaleStateError(
                    f"stale OCR recheck target revision: expected={actual_revision + 1}, actual={recheck.revision}"
                )
            now = recheck.created_at.isoformat()
            connection.execute(
                """
                INSERT INTO writing_reference_ocr_consistency_qc_recheck_records(
                    tenant_id, project_id, recheck_id, artifact_id, extraction_revision,
                    base_qc_identity_hash, stage_version, schema_version, provider, model,
                    prompt_version, models_json, physical_pages_json, verdict, notes_json,
                    input_hash, output_hash, revision, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (TENANT_ID, recheck.project_id, recheck.recheck_id, recheck.artifact_id, recheck.extraction_revision,
                 recheck.base_qc_identity_hash, recheck.stage_version, recheck.schema_version, recheck.provider,
                 recheck.model, recheck.prompt_version, _canonical_json(recheck.models), _canonical_json(recheck.physical_pages),
                 recheck.verdict, _canonical_json(recheck.notes), recheck.input_hash, recheck.output_hash, recheck.revision,
                 _canonical_json(payload), now),
            )
            if state is None:
                connection.execute(
                    "INSERT INTO writing_reference_ocr_consistency_qc_recheck_state VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (TENANT_ID, recheck.project_id, recheck.artifact_id, recheck.extraction_revision, recheck.revision, recheck.recheck_id, recheck.verdict, now),
                )
            else:
                cursor = connection.execute(
                    "UPDATE writing_reference_ocr_consistency_qc_recheck_state SET revision=?, recheck_id=?, verdict=?, updated_at=? WHERE tenant_id=? AND project_id=? AND artifact_id=? AND extraction_revision=? AND revision=?",
                    (recheck.revision, recheck.recheck_id, recheck.verdict, now, TENANT_ID, recheck.project_id, recheck.artifact_id, recheck.extraction_revision, expected_revision),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise WritingReferenceStaleStateError("OCR recheck state changed concurrently")
            self._record_idempotency(connection, recheck.project_id, operation, idempotency_key, request_hash, recheck.recheck_id)
            self._append_audit(connection, recheck.project_id, "ocr_consistency_qc_recheck_saved", recheck.recheck_id, "system_ocr_qc", {"artifact_id": recheck.artifact_id, "extraction_revision": recheck.extraction_revision, "revision": recheck.revision, "verdict": recheck.verdict})
            connection.commit()
            return recheck

    def latest_ocr_consistency_qc_recheck(
        self, project_id: str, artifact_id: str, extraction_revision: Optional[str] = None
    ) -> Optional[WritingReferenceOcrConsistencyQcRecheck]:
        with self._connect() as connection:
            if extraction_revision is None:
                row = connection.execute(
                    "SELECT extraction_revision FROM writing_reference_extractions WHERE tenant_id=? AND project_id=? AND artifact_id=? ORDER BY created_at DESC, extraction_revision DESC LIMIT 1",
                    (TENANT_ID, project_id, artifact_id),
                ).fetchone()
                if row is None:
                    raise KeyError(artifact_id)
                extraction_revision = str(row["extraction_revision"])
            row = connection.execute(
                """
                SELECT record.payload_json FROM writing_reference_ocr_consistency_qc_recheck_state AS state
                JOIN writing_reference_ocr_consistency_qc_recheck_records AS record
                  ON record.tenant_id=state.tenant_id AND record.project_id=state.project_id
                 AND record.recheck_id=state.recheck_id AND record.revision=state.revision
                WHERE state.tenant_id=? AND state.project_id=? AND state.artifact_id=? AND state.extraction_revision=?
                """,
                (TENANT_ID, project_id, artifact_id, extraction_revision),
            ).fetchone()
        return self._ocr_recheck_from_row(row) if row else None

    def _effective_ocr_consistency_projection(
        self, connection: sqlite3.Connection, project_id: str, artifact_id: str, extraction_revision: str
    ) -> WritingReferenceOcrConsistencyEffectiveProjection:
        artifact = self._document_artifact_with(connection, project_id, artifact_id)
        if not artifact.source_current:
            raise ValueError("current source document is required for OCR QC projection")
        extraction_row = connection.execute(
            "SELECT payload_json FROM writing_reference_extractions WHERE tenant_id=? AND project_id=? AND artifact_id=? AND extraction_revision=?",
            (TENANT_ID, project_id, artifact_id, extraction_revision),
        ).fetchone()
        if extraction_row is None:
            raise KeyError(extraction_revision)
        base_verdict = self._base_ocr_verdict(str(extraction_row["payload_json"]))
        recheck_row = connection.execute(
            """
            SELECT record.payload_json
            FROM writing_reference_ocr_consistency_qc_recheck_state AS state
            JOIN writing_reference_ocr_consistency_qc_recheck_records AS record
              ON record.tenant_id=state.tenant_id AND record.project_id=state.project_id
             AND record.recheck_id=state.recheck_id AND record.revision=state.revision
            WHERE state.tenant_id=? AND state.project_id=? AND state.artifact_id=?
              AND state.extraction_revision=?
            """,
            (TENANT_ID, project_id, artifact_id, extraction_revision),
        ).fetchone()
        recheck = self._ocr_recheck_from_row(recheck_row) if recheck_row else None
        disposition_row = connection.execute(
            """
            SELECT record.payload_json FROM writing_reference_ocr_consistency_medical_disposition_state AS state
            JOIN writing_reference_ocr_consistency_medical_disposition_records AS record
              ON record.tenant_id=state.tenant_id AND record.project_id=state.project_id AND record.disposition_id=state.disposition_id
            WHERE state.tenant_id=? AND state.project_id=? AND state.artifact_id=? AND state.extraction_revision=?
            """,
            (TENANT_ID, project_id, artifact_id, extraction_revision),
        ).fetchone()
        disposition = WritingReferenceOcrConsistencyMedicalDisposition.model_validate_json(disposition_row["payload_json"]) if disposition_row else None
        exact = bool(recheck and disposition and disposition.recheck_id == recheck.recheck_id and disposition.recheck_revision == recheck.revision)
        if base_verdict == "pass":
            status = "pass"
        elif base_verdict == "fail":
            status = "blocked"
        elif recheck is None or recheck.verdict == "review_required":
            status = "medical_confirmed_with_residual_issue" if exact and disposition.decision == "confirmed" else "pending_medical_confirmation"
        elif recheck.verdict == "fail":
            status = "blocked"
        else:
            status = "pass"
        return WritingReferenceOcrConsistencyEffectiveProjection(
            project_id=project_id, artifact_id=artifact_id, extraction_revision=extraction_revision,
            base_verdict=base_verdict, effective_status=status,
            recheck_id=recheck.recheck_id if recheck else "", recheck_revision=recheck.revision if recheck else 0,
            recheck_verdict=recheck.verdict if recheck else "", recheck_notes=recheck.notes if recheck else "",
            disposition_id=disposition.disposition_id if exact else "", disposition_revision=disposition.revision if exact else 0,
            disposition_decision=disposition.decision if exact else "", disposition_comment=disposition.comment if exact else "",
        )

    def ocr_consistency_qc_reviews(
        self, project_id: str, *, artifact_id: Optional[str] = None
    ) -> list[WritingReferenceOcrConsistencyEffectiveProjection]:
        query = """
            SELECT extraction.artifact_id, extraction.extraction_revision
            FROM writing_reference_extractions AS extraction
            JOIN writing_reference_document_state AS state
              ON state.tenant_id=extraction.tenant_id AND state.project_id=extraction.project_id AND state.artifact_id=extraction.artifact_id
            WHERE extraction.tenant_id=? AND extraction.project_id=? AND state.source_current=1
        """
        params: list[Any] = [TENANT_ID, project_id]
        if artifact_id:
            query += " AND extraction.artifact_id=?"
            params.append(artifact_id)
        query += """
            AND NOT EXISTS (SELECT 1 FROM writing_reference_extractions AS newer
                WHERE newer.tenant_id=extraction.tenant_id AND newer.project_id=extraction.project_id
                  AND newer.artifact_id=extraction.artifact_id
                  AND (newer.created_at > extraction.created_at OR (newer.created_at=extraction.created_at AND newer.extraction_revision>extraction.extraction_revision)))
            ORDER BY extraction.artifact_id
        """
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
            return [self._effective_ocr_consistency_projection(connection, project_id, str(row["artifact_id"]), str(row["extraction_revision"])) for row in rows]

    def effective_ocr_consistency_qc(
        self,
        project_id: str,
        artifact_id: str,
        extraction_revision: Optional[str] = None,
    ) -> WritingReferenceOcrConsistencyEffectiveProjection:
        """Return one current effective projection for callers needing a direct lookup."""
        with self._connect() as connection:
            if extraction_revision is None:
                row = connection.execute(
                    "SELECT extraction_revision FROM writing_reference_extractions WHERE tenant_id=? AND project_id=? AND artifact_id=? ORDER BY created_at DESC, extraction_revision DESC LIMIT 1",
                    (TENANT_ID, project_id, artifact_id),
                ).fetchone()
                if row is None:
                    raise KeyError(artifact_id)
                extraction_revision = str(row["extraction_revision"])
            return self._effective_ocr_consistency_projection(
                connection, project_id, artifact_id, extraction_revision
            )

    def record_ocr_consistency_medical_disposition(
        self,
        *,
        project_id: str,
        artifact_id: str,
        extraction_revision: str,
        recheck_id: str,
        recheck_revision: int,
        decision: str,
        comment: str,
        actor: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> WritingReferenceOcrConsistencyMedicalDisposition:
        if decision not in {"confirmed", "returned"}:
            raise ValueError("OCR medical disposition must be confirmed or returned")
        if not comment.strip() or not actor.strip():
            raise ValueError("OCR medical disposition comment and actor are required")
        if expected_revision < 0:
            raise ValueError("expected_revision must be non-negative")
        semantic = {
            "artifact_id": artifact_id,
            "extraction_revision": extraction_revision,
            "recheck_id": recheck_id,
            "recheck_revision": recheck_revision,
            "decision": decision,
            "comment": comment.strip(),
            "actor": actor.strip(),
            "expected_revision": expected_revision,
        }
        request_hash = _payload_hash(semantic)
        operation = "record_ocr_consistency_medical_disposition"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(connection, project_id, operation, idempotency_key, request_hash)
            if replay is not None:
                row = connection.execute(
                    "SELECT payload_json FROM writing_reference_ocr_consistency_medical_disposition_records WHERE tenant_id=? AND project_id=? AND disposition_id=?",
                    (TENANT_ID, project_id, replay),
                ).fetchone()
                connection.rollback()
                if row is None:
                    raise WritingReferenceRepositoryError("OCR disposition idempotency result is missing")
                return WritingReferenceOcrConsistencyMedicalDisposition.model_validate_json(row["payload_json"])
            artifact = self._document_artifact_with(connection, project_id, artifact_id)
            if not artifact.source_current:
                connection.rollback()
                raise ValueError("current source document is required for OCR disposition")
            latest = connection.execute(
                "SELECT extraction_revision FROM writing_reference_extractions WHERE tenant_id=? AND project_id=? AND artifact_id=? ORDER BY created_at DESC, extraction_revision DESC LIMIT 1",
                (TENANT_ID, project_id, artifact_id),
            ).fetchone()
            if latest is None or str(latest["extraction_revision"]) != extraction_revision:
                connection.rollback()
                raise WritingReferenceStaleStateError("OCR disposition must target the latest extraction revision")
            recheck_row = connection.execute(
                """
                SELECT record.payload_json
                FROM writing_reference_ocr_consistency_qc_recheck_state AS state
                JOIN writing_reference_ocr_consistency_qc_recheck_records AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.recheck_id=state.recheck_id
                 AND record.revision=state.revision
                WHERE state.tenant_id=? AND state.project_id=?
                  AND state.artifact_id=? AND state.extraction_revision=?
                  AND state.recheck_id=? AND state.revision=?
                """,
                (
                    TENANT_ID,
                    project_id,
                    artifact_id,
                    extraction_revision,
                    recheck_id,
                    recheck_revision,
                ),
            ).fetchone()
            if recheck_row is None:
                connection.rollback()
                raise WritingReferenceStaleStateError("OCR recheck is missing or no longer current")
            recheck = self._ocr_recheck_from_row(recheck_row)
            if recheck.verdict != "review_required":
                connection.rollback()
                raise ValueError(
                    "only the current review_required OCR recheck accepts a medical disposition"
                )
            state = connection.execute(
                "SELECT revision, recheck_id, recheck_revision FROM writing_reference_ocr_consistency_medical_disposition_state WHERE tenant_id=? AND project_id=? AND artifact_id=? AND extraction_revision=?",
                (TENANT_ID, project_id, artifact_id, extraction_revision),
            ).fetchone()
            state_matches = bool(state and str(state["recheck_id"]) == recheck_id and int(state["recheck_revision"]) == recheck_revision)
            actual_revision = int(state["revision"]) if state_matches else 0
            if actual_revision != expected_revision:
                connection.rollback()
                raise WritingReferenceStaleStateError(f"stale OCR disposition revision: expected={expected_revision}, actual={actual_revision}")
            revision = expected_revision + 1
            disposition = WritingReferenceOcrConsistencyMedicalDisposition(
                disposition_id="wref_ocr_disposition_" + _payload_hash({**semantic, "revision": revision})[:24],
                project_id=project_id, artifact_id=artifact_id, extraction_revision=extraction_revision,
                recheck_id=recheck_id, recheck_revision=recheck_revision, decision=decision,
                comment=comment.strip(), actor=actor.strip(), revision=revision, created_at=_utc_now(),
            )
            payload = disposition.model_dump(mode="json")
            now = disposition.created_at.isoformat()
            connection.execute(
                "INSERT INTO writing_reference_ocr_consistency_medical_disposition_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (TENANT_ID, project_id, disposition.disposition_id, artifact_id, extraction_revision, recheck_id, recheck_revision, decision, comment.strip(), actor.strip(), revision, _canonical_json(payload), now),
            )
            if state is None:
                connection.execute(
                    "INSERT INTO writing_reference_ocr_consistency_medical_disposition_state VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (TENANT_ID, project_id, artifact_id, extraction_revision, revision, disposition.disposition_id, recheck_id, recheck_revision, decision, now),
                )
            else:
                cursor = connection.execute(
                    "UPDATE writing_reference_ocr_consistency_medical_disposition_state SET revision=?, disposition_id=?, recheck_id=?, recheck_revision=?, decision=?, updated_at=? WHERE tenant_id=? AND project_id=? AND artifact_id=? AND extraction_revision=?",
                    (revision, disposition.disposition_id, recheck_id, recheck_revision, decision, now, TENANT_ID, project_id, artifact_id, extraction_revision),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise WritingReferenceStaleStateError("OCR disposition state changed concurrently")
            self._record_idempotency(connection, project_id, operation, idempotency_key, request_hash, disposition.disposition_id)
            self._append_audit(connection, project_id, "ocr_consistency_medical_disposition_recorded", disposition.disposition_id, actor, {"artifact_id": artifact_id, "extraction_revision": extraction_revision, "recheck_id": recheck_id, "recheck_revision": recheck_revision, "decision": decision, "revision": revision})
            connection.commit()
            return disposition

    def record_batch_ocr_consistency_medical_disposition(
        self,
        *,
        project_id: str,
        targets: list[WritingReferenceOcrConsistencyMedicalDispositionTarget | dict[str, Any]],
        decision: str,
        comment: str,
        actor: str,
        idempotency_key: str,
    ) -> WritingReferenceOcrConsistencyBatchMedicalDispositionResult:
        normalized = [target if isinstance(target, WritingReferenceOcrConsistencyMedicalDispositionTarget) else WritingReferenceOcrConsistencyMedicalDispositionTarget.model_validate(target) for target in targets]
        if not normalized:
            raise ValueError("OCR disposition targets are required")
        if decision not in {"confirmed", "returned"}:
            raise ValueError("OCR medical disposition must be confirmed or returned")
        if not comment.strip() or not actor.strip():
            raise ValueError("OCR medical disposition comment and actor are required")
        request_hash = _payload_hash({"targets": [item.model_dump(mode="json") for item in normalized], "decision": decision, "comment": comment.strip(), "actor": actor.strip()})
        operation = "record_batch_ocr_consistency_medical_disposition"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(connection, project_id, operation, idempotency_key, request_hash)
            if replay is None:
                connection.rollback()
            else:
                audit_row = connection.execute(
                    """
                    SELECT detail_json
                    FROM writing_reference_audit_chain
                    WHERE tenant_id=? AND project_id=?
                      AND event_type='ocr_consistency_medical_disposition_batch_recorded'
                      AND target_id=?
                    ORDER BY sequence_no DESC
                    LIMIT 1
                    """,
                    (TENANT_ID, project_id, replay),
                ).fetchone()
                connection.rollback()
        if replay is not None:
            if audit_row is not None:
                detail = json.loads(str(audit_row["detail_json"]))
                stored_result = detail.get("result")
                if isinstance(stored_result, dict):
                    return WritingReferenceOcrConsistencyBatchMedicalDispositionResult.model_validate(
                        stored_result
                    )
            # Legacy v8 batches did not persist the result body. Reconstruct a
            # truthful current projection instead of reporting every row as
            # skipped, while preserving the immutable historical records.
            reconstructed: list[
                WritingReferenceOcrConsistencyMedicalDispositionOutcome
            ] = []
            for target in normalized:
                projection = self.effective_ocr_consistency_qc(
                    project_id,
                    target.artifact_id,
                    target.extraction_revision,
                )
                if (
                    projection.recheck_id == target.recheck_id
                    and projection.recheck_revision == target.recheck_revision
                    and projection.disposition_id
                ):
                    reconstructed.append(
                        WritingReferenceOcrConsistencyMedicalDispositionOutcome(
                            artifact_id=target.artifact_id,
                            extraction_revision=target.extraction_revision,
                            recheck_id=target.recheck_id,
                            recheck_revision=target.recheck_revision,
                            outcome=projection.disposition_decision,
                            disposition_id=projection.disposition_id,
                            reason="reconstructed from current immutable disposition",
                        )
                    )
                else:
                    reconstructed.append(
                        WritingReferenceOcrConsistencyMedicalDispositionOutcome(
                            artifact_id=target.artifact_id,
                            extraction_revision=target.extraction_revision,
                            recheck_id=target.recheck_id,
                            recheck_revision=target.recheck_revision,
                            outcome="stale",
                            reason="batch result predates persisted result bodies and is no longer current",
                        )
                    )
            return WritingReferenceOcrConsistencyBatchMedicalDispositionResult(
                project_id=project_id,
                outcomes=reconstructed,
                created_at=_utc_now(),
            )
        outcomes: list[WritingReferenceOcrConsistencyMedicalDispositionOutcome] = []
        for index, target in enumerate(normalized):
            try:
                result = self.record_ocr_consistency_medical_disposition(
                    project_id=project_id, artifact_id=target.artifact_id,
                    extraction_revision=target.extraction_revision, recheck_id=target.recheck_id,
                    recheck_revision=target.recheck_revision, decision=decision,
                    comment=comment, actor=actor, expected_revision=target.expected_revision,
                    idempotency_key=f"{idempotency_key}:{index}:{target.artifact_id}:{target.recheck_id}:{target.recheck_revision}",
                )
                outcomes.append(WritingReferenceOcrConsistencyMedicalDispositionOutcome(
                    artifact_id=target.artifact_id, extraction_revision=target.extraction_revision,
                    recheck_id=target.recheck_id, recheck_revision=target.recheck_revision,
                    outcome=decision, disposition_id=result.disposition_id,
                ))
            except WritingReferenceStaleStateError as exc:
                outcomes.append(WritingReferenceOcrConsistencyMedicalDispositionOutcome(
                    artifact_id=target.artifact_id, extraction_revision=target.extraction_revision,
                    recheck_id=target.recheck_id, recheck_revision=target.recheck_revision,
                    outcome="stale", reason=str(exc),
                ))
            except (WritingReferenceConflictError, KeyError, ValueError) as exc:
                outcomes.append(WritingReferenceOcrConsistencyMedicalDispositionOutcome(
                    artifact_id=target.artifact_id, extraction_revision=target.extraction_revision,
                    recheck_id=target.recheck_id, recheck_revision=target.recheck_revision,
                    outcome="failed", reason=str(exc),
                ))
        result = WritingReferenceOcrConsistencyBatchMedicalDispositionResult(project_id=project_id, outcomes=outcomes, created_at=_utc_now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(connection, project_id, operation, idempotency_key, request_hash)
            if replay is None:
                batch_id = "wref_ocr_batch_" + _payload_hash({"project_id": project_id, "request_hash": request_hash})[:24]
                self._record_idempotency(connection, project_id, operation, idempotency_key, request_hash, batch_id)
                counts = {key: sum(item.outcome == key for item in outcomes) for key in {item.outcome for item in outcomes}}
                self._append_audit(
                    connection,
                    project_id,
                    "ocr_consistency_medical_disposition_batch_recorded",
                    batch_id,
                    actor,
                    {
                        "target_count": len(normalized),
                        "outcome_counts": counts,
                        "result": result.model_dump(mode="json"),
                    },
                )
                connection.commit()
            else:
                connection.rollback()
        return result

    def record_extraction_review(
        self,
        *,
        project_id: str,
        artifact_id: str,
        extraction_revision: str,
        decision: str,
        confirmed_anchor_coverage: list[str],
        unresolved_structure_issues: list[str],
        comment: str,
        actor: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> WritingReferenceExtractionReviewDecision:
        if decision not in {"approved", "returned"}:
            raise ValueError("extraction review decision must be approved or returned")
        if len(comment.strip()) < 10:
            raise ValueError("extraction review comment must explain the medical structure conclusion")
        anchors = sorted({item.strip() for item in confirmed_anchor_coverage if item.strip()})
        issues = [item.strip() for item in unresolved_structure_issues if item.strip()]
        semantic = {
            "artifact_id": artifact_id,
            "extraction_revision": extraction_revision,
            "decision": decision,
            "confirmed_anchor_coverage": anchors,
            "unresolved_structure_issues": issues,
            "comment": comment.strip(),
            "actor": actor,
            "expected_revision": expected_revision,
        }
        request_hash = _payload_hash(semantic)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(
                connection,
                project_id,
                "record_extraction_review",
                idempotency_key,
                request_hash,
            )
            if replay:
                row = connection.execute(
                    "SELECT payload_json FROM writing_reference_extraction_review_records "
                    "WHERE tenant_id=? AND project_id=? AND review_id=?",
                    (TENANT_ID, project_id, replay),
                ).fetchone()
                connection.rollback()
                if row is None:
                    raise WritingReferenceRepositoryError("idempotency result is missing")
                return WritingReferenceExtractionReviewDecision.model_validate_json(
                    row["payload_json"]
                )

            artifact = self._document_artifact_with(connection, project_id, artifact_id)
            if not artifact.source_current:
                connection.rollback()
                raise ValueError("current source document is required for extraction review")
            extraction_row = connection.execute(
                "SELECT payload_json FROM writing_reference_extractions "
                "WHERE tenant_id=? AND project_id=? AND artifact_id=? AND extraction_revision=?",
                (TENANT_ID, project_id, artifact_id, extraction_revision),
            ).fetchone()
            if extraction_row is None:
                connection.rollback()
                raise KeyError(extraction_revision)
            extraction = WritingReferenceExtractionResult.model_validate_json(
                extraction_row["payload_json"]
            )
            actual_anchors = sorted(
                {
                    span.ich_m11_anchor
                    for span in extraction.spans
                    if span.ich_m11_anchor and span.ich_m11_anchor != "unmapped"
                }
            )
            unknown_anchors = sorted(set(anchors) - set(actual_anchors))
            if unknown_anchors:
                connection.rollback()
                raise ValueError(
                    "confirmed anchor coverage is not present in the extraction: "
                    + ", ".join(unknown_anchors)
                )
            if decision == "approved":
                if issues:
                    connection.rollback()
                    raise ValueError("approved extraction review cannot retain unresolved structure issues")
                if anchors != actual_anchors:
                    connection.rollback()
                    raise ValueError("approved extraction review must confirm all mapped M11 anchors")
            elif not issues:
                connection.rollback()
                raise ValueError("returned extraction review must record at least one structure issue")

            state = connection.execute(
                "SELECT revision FROM writing_reference_extraction_review_state "
                "WHERE tenant_id=? AND project_id=? AND artifact_id=? AND extraction_revision=?",
                (TENANT_ID, project_id, artifact_id, extraction_revision),
            ).fetchone()
            actual_revision = int(state["revision"]) if state else 0
            if actual_revision != expected_revision:
                connection.rollback()
                raise WritingReferenceStaleStateError(
                    f"stale extraction review revision: expected={expected_revision}, actual={actual_revision}"
                )
            revision = actual_revision + 1
            now = _utc_now()
            review_id = "wref_structure_review_" + _payload_hash(
                {**semantic, "revision": revision}
            )[:20]
            review = WritingReferenceExtractionReviewDecision(
                review_id=review_id,
                project_id=project_id,
                artifact_id=artifact_id,
                extraction_revision=extraction_revision,
                decision=decision,
                confirmed_anchor_coverage=anchors,
                unresolved_structure_issues=issues,
                comment=comment.strip(),
                actor=actor,
                revision=revision,
                created_at=now,
            )
            connection.execute(
                "INSERT INTO writing_reference_extraction_review_records "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    TENANT_ID,
                    project_id,
                    artifact_id,
                    extraction_revision,
                    review_id,
                    revision,
                    decision,
                    _canonical_json(review.model_dump(mode="json")),
                    now.isoformat(),
                ),
            )
            if state:
                cursor = connection.execute(
                    "UPDATE writing_reference_extraction_review_state "
                    "SET revision=?, review_id=?, decision=?, updated_at=? "
                    "WHERE tenant_id=? AND project_id=? AND artifact_id=? "
                    "AND extraction_revision=? AND revision=?",
                    (
                        revision,
                        review_id,
                        decision,
                        now.isoformat(),
                        TENANT_ID,
                        project_id,
                        artifact_id,
                        extraction_revision,
                        expected_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise WritingReferenceStaleStateError("extraction review changed concurrently")
            else:
                connection.execute(
                    "INSERT INTO writing_reference_extraction_review_state "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        TENANT_ID,
                        project_id,
                        artifact_id,
                        extraction_revision,
                        revision,
                        review_id,
                        decision,
                        now.isoformat(),
                    ),
                )
            self._record_idempotency(
                connection,
                project_id,
                "record_extraction_review",
                idempotency_key,
                request_hash,
                review_id,
            )
            self._append_audit(
                connection,
                project_id,
                "extraction_structure_medically_reviewed",
                review_id,
                actor,
                {
                    "artifact_id": artifact_id,
                    "extraction_revision": extraction_revision,
                    "decision": decision,
                    "revision": revision,
                    "confirmed_anchor_coverage": anchors,
                    "unresolved_issue_count": len(issues),
                },
            )
            connection.commit()
            return review

    def extraction_reviews(
        self,
        project_id: str,
        *,
        artifact_id: Optional[str] = None,
    ) -> list[WritingReferenceExtractionReviewDecision]:
        query = """
            SELECT record.payload_json
            FROM writing_reference_extraction_review_state AS state
            JOIN writing_reference_extraction_review_records AS record
              ON record.tenant_id=state.tenant_id
             AND record.project_id=state.project_id
             AND record.review_id=state.review_id
            WHERE state.tenant_id=? AND state.project_id=?
        """
        params: list[Any] = [TENANT_ID, project_id]
        if artifact_id:
            query += " AND state.artifact_id=?"
            params.append(artifact_id)
        query += " ORDER BY state.updated_at, state.artifact_id, state.extraction_revision"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            WritingReferenceExtractionReviewDecision.model_validate_json(row["payload_json"])
            for row in rows
        ]

    def save_document_validation(
        self,
        validation: WritingReferenceDocumentValidationRecord,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> WritingReferenceDocumentValidationRecord:
        if validation.status not in {"confirmed", "needs_review", "mismatch", "user_overridden"}:
            raise ValueError("invalid document validation status")
        if validation.revision != expected_revision + 1:
            raise ValueError("document validation revision mismatch")
        self.document_artifact(validation.project_id, validation.artifact_id)
        payload = validation.model_dump(mode="json")
        request_hash = _payload_hash(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(
                connection,
                validation.project_id,
                "save_document_validation",
                idempotency_key,
                request_hash,
            )
            if replay:
                row = connection.execute(
                    "SELECT payload_json FROM writing_reference_document_validation_records WHERE tenant_id=? AND project_id=? AND validation_id=?",
                    (TENANT_ID, validation.project_id, replay),
                ).fetchone()
                connection.rollback()
                return WritingReferenceDocumentValidationRecord.model_validate_json(row["payload_json"])
            state = connection.execute(
                "SELECT revision FROM writing_reference_document_validation_state WHERE tenant_id=? AND project_id=? AND artifact_id=?",
                (TENANT_ID, validation.project_id, validation.artifact_id),
            ).fetchone()
            actual = int(state["revision"]) if state else 0
            if actual != expected_revision:
                connection.rollback()
                raise WritingReferenceStaleStateError(
                    f"stale document validation revision: expected={expected_revision}, actual={actual}"
                )
            connection.execute(
                "INSERT INTO writing_reference_document_validation_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    TENANT_ID,
                    validation.project_id,
                    validation.artifact_id,
                    validation.validation_id,
                    validation.revision,
                    validation.status,
                    _canonical_json(payload),
                    validation.created_at.isoformat(),
                ),
            )
            if state:
                cursor = connection.execute(
                    "UPDATE writing_reference_document_validation_state SET revision=?, validation_id=?, status=?, updated_at=? WHERE tenant_id=? AND project_id=? AND artifact_id=? AND revision=?",
                    (
                        validation.revision,
                        validation.validation_id,
                        validation.status,
                        validation.created_at.isoformat(),
                        TENANT_ID,
                        validation.project_id,
                        validation.artifact_id,
                        expected_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise WritingReferenceStaleStateError("document validation changed concurrently")
            else:
                connection.execute(
                    "INSERT INTO writing_reference_document_validation_state VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        TENANT_ID,
                        validation.project_id,
                        validation.artifact_id,
                        validation.revision,
                        validation.validation_id,
                        validation.status,
                        validation.created_at.isoformat(),
                    ),
                )
            self._record_idempotency(
                connection,
                validation.project_id,
                "save_document_validation",
                idempotency_key,
                request_hash,
                validation.validation_id,
            )
            event_type = (
                "document_validation_overridden"
                if validation.status == "user_overridden"
                else "document_content_validated"
            )
            self._append_audit(
                connection,
                validation.project_id,
                event_type,
                validation.validation_id,
                validation.actor,
                {
                    "artifact_id": validation.artifact_id,
                    "status": validation.status,
                    "revision": validation.revision,
                    "warning_codes": validation.acknowledged_warning_codes,
                },
            )
            connection.commit()
            return validation

    def document_validation(
        self,
        project_id: str,
        artifact_id: str,
    ) -> WritingReferenceDocumentValidationRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT record.payload_json
                FROM writing_reference_document_validation_state AS state
                JOIN writing_reference_document_validation_records AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.validation_id=state.validation_id
                WHERE state.tenant_id=? AND state.project_id=? AND state.artifact_id=?
                """,
                (TENANT_ID, project_id, artifact_id),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return WritingReferenceDocumentValidationRecord.model_validate_json(row["payload_json"])

    def document_validations(self, project_id: str) -> list[WritingReferenceDocumentValidationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record.payload_json
                FROM writing_reference_document_validation_state AS state
                JOIN writing_reference_document_validation_records AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.validation_id=state.validation_id
                WHERE state.tenant_id=? AND state.project_id=?
                ORDER BY state.updated_at, state.artifact_id
                """,
                (TENANT_ID, project_id),
            ).fetchall()
        return [WritingReferenceDocumentValidationRecord.model_validate_json(row["payload_json"]) for row in rows]

    def override_document_validation(
        self,
        *,
        project_id: str,
        artifact_id: str,
        reason: str,
        acknowledged_warning_codes: list[str],
        actor: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> WritingReferenceDocumentValidationRecord:
        if len(reason.strip()) < 10:
            raise ValueError("override reason must explain why the document is appropriate")
        current = self.document_validation(project_id, artifact_id)
        if current.revision != expected_revision:
            raise WritingReferenceStaleStateError(
                f"stale document validation revision: expected={expected_revision}, actual={current.revision}"
            )
        if current.status not in {"needs_review", "mismatch"}:
            raise ValueError("only a document with current validation warnings can be explicitly confirmed")
        artifact = self.document_artifact(project_id, artifact_id)
        if not artifact.source_current:
            raise WritingReferenceStaleStateError("document source is no longer current")
        if current.document_sha256 != artifact.content_sha256:
            raise WritingReferenceStaleStateError("document validation hash is no longer current")
        if current.source_state_revision != artifact.state_revision:
            raise WritingReferenceStaleStateError("document source revision changed after validation")
        try:
            latest_extraction_revision = self.latest_extraction_revision(project_id, artifact_id)
        except KeyError as exc:
            raise WritingReferenceStaleStateError("document has no current extraction") from exc
        if current.extraction_revision != latest_extraction_revision:
            raise WritingReferenceStaleStateError("document extraction changed after validation")
        from .writing_reference import DOCUMENT_CONTENT_VALIDATOR_VERSION

        if current.validator_version != DOCUMENT_CONTENT_VALIDATOR_VERSION:
            raise WritingReferenceStaleStateError("document validator version changed after validation")
        warning_codes = sorted(
            check.check_code for check in current.checks if check.outcome in {"warning", "mismatch"}
        )
        if not warning_codes:
            raise ValueError("document validation has no current warnings to acknowledge")
        acknowledged = sorted(set(acknowledged_warning_codes))
        if acknowledged != warning_codes:
            raise ValueError("all current document validation warnings must be acknowledged")
        now = _utc_now()
        revision = current.revision + 1
        validation = current.model_copy(
            update={
                "validation_id": "wref_validation_" + _payload_hash(
                    {
                        "artifact_id": artifact_id,
                        "revision": revision,
                        "reason": reason.strip(),
                        "actor": actor,
                    }
                )[:20],
                "revision": revision,
                "status": "user_overridden",
                "summary": "医学专业人员已确认沿用当前文件，并接受系统提示。",
                "actor": actor,
                "override_reason": reason.strip(),
                "acknowledged_warning_codes": acknowledged,
                "created_at": now,
            }
        )
        return self.save_document_validation(
            validation,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )

    def translations(self, project_id: str, span_id: Optional[str] = None) -> list[WritingReferenceTranslationRevision]:
        query = """
            SELECT record.payload_json, state.status AS current_status
            FROM writing_reference_translation_state AS state
            JOIN writing_reference_translation_records AS record
              ON record.tenant_id=state.tenant_id AND record.project_id=state.project_id
             AND record.translation_id=state.translation_id AND record.revision=state.revision
            WHERE state.tenant_id=? AND state.project_id=?
        """
        params: list[Any] = [TENANT_ID, project_id]
        if span_id:
            query += " AND state.span_id=?"
            params.append(span_id)
        query += " ORDER BY state.updated_at, state.translation_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            WritingReferenceTranslationRevision.model_validate_json(row["payload_json"]).model_copy(
                update={"status": str(row["current_status"])}
            )
            for row in rows
        ]

    def save_translation(
        self,
        translation: WritingReferenceTranslationRevision,
        *,
        idempotency_key: str,
        expected_revision: int = 0,
        required_current_medical_review_id: str = "",
    ) -> WritingReferenceTranslationRevision:
        span = self.source_span(translation.project_id, translation.span_id)
        if translation.source_span_revision != f"{span.span_id}_r1":
            raise ValueError("translation source span revision mismatch")
        payload = translation.model_dump(mode="json")
        request_hash = _semantic_payload_hash(
            {
                "translation": payload,
                "required_current_medical_review_id": required_current_medical_review_id,
            }
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            artifact = self._document_artifact_with(
                connection, translation.project_id, span.artifact_id
            )
            if not artifact.source_current:
                connection.rollback()
                raise ValueError("current source artifact is required for translation")
            if translation.document_sha256 != artifact.content_sha256:
                connection.rollback()
                raise ValueError("translation document hash does not match source artifact")
            structure_review = connection.execute(
                """
                SELECT decision FROM writing_reference_extraction_review_state
                WHERE tenant_id=? AND project_id=? AND artifact_id=?
                  AND extraction_revision=?
                """,
                (
                    TENANT_ID,
                    translation.project_id,
                    span.artifact_id,
                    span.extraction_revision,
                ),
            ).fetchone()
            if structure_review is None or str(structure_review["decision"]) != "approved":
                connection.rollback()
                raise ValueError("approved medical structure review is required before translation")
            validation_row = connection.execute(
                """
                SELECT record.payload_json, state.status AS current_status
                FROM writing_reference_document_validation_state AS state
                JOIN writing_reference_document_validation_records AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.validation_id=state.validation_id
                WHERE state.tenant_id=? AND state.project_id=? AND state.artifact_id=?
                """,
                (TENANT_ID, translation.project_id, span.artifact_id),
            ).fetchone()
            if validation_row is None:
                connection.rollback()
                raise ValueError(
                    "current document content validation is required before translation"
                )
            validation = WritingReferenceDocumentValidationRecord.model_validate_json(
                validation_row["payload_json"]
            ).model_copy(update={"status": str(validation_row["current_status"])})
            if (
                validation.status not in {"confirmed", "user_overridden"}
                or validation.document_sha256 != artifact.content_sha256
                or validation.source_state_revision != artifact.state_revision
            ):
                connection.rollback()
                raise ValueError(
                    "document content validation must be current and confirmed before translation"
                )
            if expected_revision > 0:
                if not required_current_medical_review_id:
                    connection.rollback()
                    raise ValueError(
                        "current returned medical review is required before translation revision"
                    )
                review_state = connection.execute(
                    """
                    SELECT review_id, decision
                    FROM writing_reference_medical_review_state
                    WHERE tenant_id=? AND project_id=? AND translation_id=?
                      AND translation_revision=?
                    """,
                    (
                        TENANT_ID,
                        translation.project_id,
                        translation.translation_id,
                        expected_revision,
                    ),
                ).fetchone()
                if (
                    review_state is None
                    or str(review_state["review_id"]) != required_current_medical_review_id
                    or str(review_state["decision"]) != "returned"
                ):
                    connection.rollback()
                    raise WritingReferenceConflictError(
                        "supplied returned medical review is no longer current for this translation revision"
                    )
            try:
                replay = self._idempotent_result(connection, translation.project_id, "save_translation", idempotency_key, request_hash)
            except WritingReferenceConflictError:
                prior = connection.execute(
                    """
                    SELECT result_id FROM writing_reference_idempotency
                    WHERE tenant_id=? AND project_id=? AND operation=? AND idempotency_key=?
                    """,
                    (
                        TENANT_ID,
                        translation.project_id,
                        "save_translation",
                        idempotency_key,
                    ),
                ).fetchone()
                if prior is None:
                    raise
                row = connection.execute(
                    """
                    SELECT payload_json FROM writing_reference_translation_records
                    WHERE tenant_id=? AND project_id=? AND translation_id=? AND revision=?
                    """,
                    (
                        TENANT_ID,
                        translation.project_id,
                        translation.translation_id,
                        translation.revision,
                    ),
                ).fetchone()
                if row is None:
                    # result_id may encode translation_id; fall back to prior result_id
                    row = connection.execute(
                        """
                        SELECT payload_json FROM writing_reference_translation_records
                        WHERE tenant_id=? AND project_id=? AND translation_id=?
                        ORDER BY revision DESC LIMIT 1
                        """,
                        (TENANT_ID, translation.project_id, str(prior["result_id"])),
                    ).fetchone()
                if row is None:
                    raise
                existing = WritingReferenceTranslationRevision.model_validate_json(
                    row["payload_json"]
                )
                if _semantic_payload_hash(existing.model_dump(mode="json")) != (
                    _semantic_payload_hash(payload)
                ):
                    raise
                connection.rollback()
                return existing
            if replay:
                row = connection.execute(
                    "SELECT payload_json FROM writing_reference_translation_records WHERE tenant_id=? AND project_id=? AND translation_id=? AND revision=?",
                    (TENANT_ID, translation.project_id, translation.translation_id, translation.revision),
                ).fetchone()
                connection.rollback()
                return WritingReferenceTranslationRevision.model_validate_json(row["payload_json"])
            state = connection.execute(
                "SELECT revision, span_id FROM writing_reference_translation_state WHERE tenant_id=? AND project_id=? AND translation_id=?",
                (TENANT_ID, translation.project_id, translation.translation_id),
            ).fetchone()
            actual = int(state["revision"]) if state else 0
            if actual != expected_revision or translation.revision != expected_revision + 1:
                connection.rollback()
                raise WritingReferenceStaleStateError(
                    f"stale translation revision: expected={expected_revision}, actual={actual}"
                )
            if state is not None and str(state["span_id"]) != translation.span_id:
                connection.rollback()
                raise WritingReferenceConflictError("translation source span cannot change")
            now = translation.created_at.isoformat()
            connection.execute(
                "INSERT INTO writing_reference_translation_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (TENANT_ID, translation.project_id, translation.translation_id, translation.span_id, translation.revision, translation.fidelity_status, translation.status, _canonical_json(payload), now),
            )
            if state is None:
                connection.execute(
                    "INSERT INTO writing_reference_translation_state VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (TENANT_ID, translation.project_id, translation.translation_id, translation.revision, translation.span_id, translation.status, now),
                )
            else:
                cursor = connection.execute(
                    "UPDATE writing_reference_translation_state SET revision=?, status=?, updated_at=? WHERE tenant_id=? AND project_id=? AND translation_id=? AND revision=?",
                    (
                        translation.revision,
                        translation.status,
                        now,
                        TENANT_ID,
                        translation.project_id,
                        translation.translation_id,
                        expected_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise WritingReferenceStaleStateError("translation changed concurrently")
                connection.execute(
                    """
                    UPDATE writing_reference_evidence_briefs
                    SET status='invalidated_review'
                    WHERE tenant_id=? AND project_id=? AND translation_id=?
                      AND translation_revision<=? AND status='approved_current'
                    """,
                    (
                        TENANT_ID,
                        translation.project_id,
                        translation.translation_id,
                        expected_revision,
                    ),
                )
            self._record_idempotency(connection, translation.project_id, "save_translation", idempotency_key, request_hash, translation.translation_id)
            self._append_audit(connection, translation.project_id, "regulatory_translation_saved", translation.translation_id, translation.created_by, {"span_id": translation.span_id, "revision": translation.revision, "fidelity_status": translation.fidelity_status})
            connection.commit()
            return translation

    def medical_review(
        self,
        project_id: str,
        review_id: str,
    ) -> WritingReferenceMedicalReviewDecision:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM writing_reference_medical_review_records WHERE tenant_id=? AND project_id=? AND review_id=?",
                (TENANT_ID, project_id, review_id),
            ).fetchone()
        if row is None:
            raise KeyError(review_id)
        return WritingReferenceMedicalReviewDecision.model_validate_json(row["payload_json"])

    def current_medical_review(
        self,
        project_id: str,
        translation_id: str,
        translation_revision: int,
    ) -> WritingReferenceMedicalReviewDecision:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT record.payload_json
                FROM writing_reference_medical_review_state AS state
                JOIN writing_reference_medical_review_records AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.review_id=state.review_id
                WHERE state.tenant_id=? AND state.project_id=?
                  AND state.translation_id=? AND state.translation_revision=?
                """,
                (TENANT_ID, project_id, translation_id, translation_revision),
            ).fetchone()
        if row is None:
            raise KeyError(f"{translation_id}/r{translation_revision}")
        return WritingReferenceMedicalReviewDecision.model_validate_json(row["payload_json"])

    def translation(self, project_id: str, translation_id: str, revision: int) -> WritingReferenceTranslationRevision:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM writing_reference_translation_records WHERE tenant_id=? AND project_id=? AND translation_id=? AND revision=?",
                (TENANT_ID, project_id, translation_id, revision),
            ).fetchone()
        if row is None:
            raise KeyError(translation_id)
        return WritingReferenceTranslationRevision.model_validate_json(row["payload_json"])

    def record_medical_review(
        self, *, project_id: str, translation_id: str, translation_revision: int,
        decision: str, comment: str, actor: str, expected_revision: int,
        idempotency_key: str,
    ) -> WritingReferenceMedicalReviewDecision:
        if decision not in {"approved", "returned", "rejected"} or not comment.strip():
            raise ValueError("valid author confirmation decision and comment are required")
        semantic = {"translation_id": translation_id, "translation_revision": translation_revision, "decision": decision, "comment": comment, "actor": actor, "expected_revision": expected_revision}
        request_hash = _payload_hash(semantic)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_translation = connection.execute(
                """
                SELECT revision
                FROM writing_reference_translation_state
                WHERE tenant_id=? AND project_id=? AND translation_id=?
                """,
                (TENANT_ID, project_id, translation_id),
            ).fetchone()
            if current_translation is None:
                connection.rollback()
                raise KeyError(translation_id)
            current_translation_revision = int(current_translation["revision"])
            if current_translation_revision != translation_revision:
                connection.rollback()
                raise WritingReferenceStaleStateError(
                    "translation revision is no longer current: "
                    f"requested={translation_revision}, current={current_translation_revision}"
                )
            replay = self._idempotent_result(connection, project_id, "record_medical_review", idempotency_key, request_hash)
            if replay:
                row = connection.execute("SELECT payload_json FROM writing_reference_medical_review_records WHERE tenant_id=? AND project_id=? AND review_id=?", (TENANT_ID, project_id, replay)).fetchone()
                connection.rollback()
                return WritingReferenceMedicalReviewDecision.model_validate_json(row["payload_json"])
            state = connection.execute(
                """
                SELECT state.revision, state.decision, state.review_id,
                       record.payload_json
                FROM writing_reference_medical_review_state AS state
                JOIN writing_reference_medical_review_records AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.review_id=state.review_id
                WHERE state.tenant_id=? AND state.project_id=?
                  AND state.translation_id=? AND state.translation_revision=?
                """,
                (TENANT_ID, project_id, translation_id, translation_revision),
            ).fetchone()
            actual = int(state["revision"]) if state else 0
            if actual != expected_revision:
                connection.rollback()
                raise WritingReferenceStaleStateError(f"stale medical review revision: expected={expected_revision}, actual={actual}")
            previous_review = (
                WritingReferenceMedicalReviewDecision.model_validate_json(
                    state["payload_json"]
                )
                if state is not None
                else None
            )
            legacy_approved_migration = bool(
                decision == "approved"
                and previous_review is not None
                and previous_review.decision == "approved"
                and (
                    previous_review.decision_type != "author_confirmation"
                    or previous_review.admission_status != "admitted"
                )
            )
            revision = actual + 1
            now = _utc_now()
            review_id = "wref_review_" + _payload_hash({**semantic, "revision": revision})[:20]
            evidence_brief_id = (
                "wref_brief_"
                + _payload_hash(
                    {
                        "translation_id": translation_id,
                        "revision": translation_revision,
                        "review_id": review_id,
                    }
                )[:20]
                if decision == "approved"
                else ""
            )
            review = WritingReferenceMedicalReviewDecision(
                review_id=review_id, project_id=project_id, translation_id=translation_id,
                translation_revision=translation_revision, decision=decision,
                comment=comment.strip(), actor=actor, revision=revision,
                decision_type="author_confirmation",
                admission_status="admitted" if decision == "approved" else "not_admitted",
                evidence_brief_id=evidence_brief_id,
                created_at=now,
            )
            connection.execute("INSERT INTO writing_reference_medical_review_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (TENANT_ID, project_id, review_id, translation_id, translation_revision, revision, decision, _canonical_json(review.model_dump(mode="json")), now.isoformat()))
            if state:
                cursor = connection.execute("UPDATE writing_reference_medical_review_state SET revision=?, review_id=?, decision=?, updated_at=? WHERE tenant_id=? AND project_id=? AND translation_id=? AND translation_revision=? AND revision=?", (revision, review_id, decision, now.isoformat(), TENANT_ID, project_id, translation_id, translation_revision, expected_revision))
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise WritingReferenceStaleStateError("medical review changed concurrently")
            else:
                connection.execute("INSERT INTO writing_reference_medical_review_state VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (TENANT_ID, project_id, translation_id, translation_revision, revision, review_id, decision, now.isoformat()))
            invalidated_brief_count = 0
            if state is not None and str(state["decision"]) == "approved" and decision != "approved":
                invalidated_brief_count = connection.execute(
                    "UPDATE writing_reference_evidence_briefs SET status='invalidated_review' "
                    "WHERE tenant_id=? AND project_id=? AND translation_id=? "
                    "AND translation_revision=? AND status='approved_current'",
                    (TENANT_ID, project_id, translation_id, translation_revision),
                ).rowcount
            self._append_audit(
                connection,
                project_id,
                "translation_author_confirmed"
                if decision == "approved"
                else "translation_author_confirmation_recorded",
                review_id,
                actor,
                {
                    "translation_id": translation_id,
                    "translation_revision": translation_revision,
                    "decision": decision,
                    "revision": revision,
                    "evidence_brief_id": evidence_brief_id,
                    "invalidated_brief_count": invalidated_brief_count,
                },
            )
            if legacy_approved_migration:
                self._append_audit(
                    connection,
                    project_id,
                    "legacy_translation_author_confirmation_migrated",
                    review_id,
                    actor,
                    {
                        "translation_id": translation_id,
                        "translation_revision": translation_revision,
                        "legacy_review_id": previous_review.review_id,
                        "legacy_review_revision": previous_review.revision,
                        "author_confirmation_id": review_id,
                    },
                )
            brief = None
            if decision == "approved":
                brief = self.admit_translation(
                    project_id=project_id,
                    translation_id=translation_id,
                    expected_translation_revision=translation_revision,
                    medical_review_id=review_id,
                    idempotency_key=f"author-confirm-admit:{review_id}",
                    _connection=connection,
                    _actor=actor,
                )
                if brief.brief_id != evidence_brief_id:
                    connection.rollback()
                    raise WritingReferenceRepositoryError(
                        "author confirmation admission id is not deterministic"
                    )
            else:
                cursor = connection.execute(
                    """
                    UPDATE writing_reference_translation_state
                    SET status='pending_author_confirmation', updated_at=?
                    WHERE tenant_id=? AND project_id=? AND translation_id=?
                      AND revision=?
                    """,
                    (
                        now.isoformat(),
                        TENANT_ID,
                        project_id,
                        translation_id,
                        translation_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise WritingReferenceStaleStateError(
                        "translation revision is no longer current"
                    )
            self._record_idempotency(connection, project_id, "record_medical_review", idempotency_key, request_hash, review_id)
            connection.commit()
            return review

    def record_batch_medical_review(
        self, *, project_id: str, batch_id: str,
        targets: list[tuple[str, int]],
        comment: str, actor: str, idempotency_key: str,
    ) -> list[WritingReferenceTranslationBatchReviewItemOutcome]:
        """Approve pre-validated eligible candidates one revision at a time.

        Each target reuses the single-item optimistic-concurrency and
        idempotency path (``record_medical_review``); one stale or failing row
        is reported and never conceals the outcome of the remaining rows.
        Per-item idempotency keys derive from the batch idempotency key, so a
        retry of the same batch action replays instead of duplicating.
        """
        outcomes: list[WritingReferenceTranslationBatchReviewItemOutcome] = []
        for translation_id, translation_revision in targets:
            try:
                review = self.record_medical_review(
                    project_id=project_id,
                    translation_id=translation_id,
                    translation_revision=translation_revision,
                    decision="approved",
                    comment=comment,
                    actor=actor,
                    expected_revision=0,
                    idempotency_key=f"{idempotency_key}:{translation_id}",
                )
                outcomes.append(
                    WritingReferenceTranslationBatchReviewItemOutcome(
                        translation_id=translation_id,
                        translation_revision=translation_revision,
                        outcome="approved",
                        review_id=review.review_id,
                    )
                )
            except WritingReferenceStaleStateError as exc:
                outcomes.append(
                    WritingReferenceTranslationBatchReviewItemOutcome(
                        translation_id=translation_id,
                        translation_revision=translation_revision,
                        outcome="stale",
                        reason=str(exc),
                    )
                )
            except KeyError:
                outcomes.append(
                    WritingReferenceTranslationBatchReviewItemOutcome(
                        translation_id=translation_id,
                        translation_revision=translation_revision,
                        outcome="stale",
                        reason="translation is no longer current",
                    )
                )
            except (WritingReferenceConflictError, ValueError) as exc:
                outcomes.append(
                    WritingReferenceTranslationBatchReviewItemOutcome(
                        translation_id=translation_id,
                        translation_revision=translation_revision,
                        outcome="failed",
                        reason=str(exc),
                    )
                )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._append_audit(
                connection,
                project_id,
                "translation_batch_medical_review",
                batch_id,
                actor,
                {
                    "batch_id": batch_id,
                    "target_count": len(targets),
                    "approved_count": sum(
                        item.outcome == "approved" for item in outcomes
                    ),
                    "stale_count": sum(item.outcome == "stale" for item in outcomes),
                    "failed_count": sum(
                        item.outcome == "failed" for item in outcomes
                    ),
                    "idempotency_key": idempotency_key,
                },
            )
            connection.commit()
        return outcomes

    def admit_translation(
        self, *, project_id: str, translation_id: str,
        expected_translation_revision: int, medical_review_id: str,
        idempotency_key: str,
        _connection: Any = None,
        _actor: str = "system_admission",
    ) -> WritingReferenceEvidenceBrief:
        admission_semantic = {
            "translation_id": translation_id,
            "revision": expected_translation_revision,
            "review_id": medical_review_id,
        }
        request_hash = _payload_hash(admission_semantic)
        manage_transaction = _connection is None
        connection_context = self._connect() if manage_transaction else nullcontext(_connection)
        with connection_context as connection:
            if manage_transaction:
                connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(
                connection,
                project_id,
                "admit_translation",
                idempotency_key,
                request_hash,
            )

            translation_row = connection.execute(
                """
                SELECT record.payload_json, state.revision AS current_revision,
                       state.status AS current_status, state.span_id AS current_span_id
                FROM writing_reference_translation_state AS state
                JOIN writing_reference_translation_records AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.translation_id=state.translation_id
                 AND record.revision=state.revision
                WHERE state.tenant_id=? AND state.project_id=?
                  AND state.translation_id=?
                """,
                (TENANT_ID, project_id, translation_id),
            ).fetchone()
            if translation_row is None:
                connection.rollback()
                raise KeyError(translation_id)
            current_translation_revision = int(translation_row["current_revision"])
            if current_translation_revision != expected_translation_revision:
                connection.rollback()
                raise WritingReferenceStaleStateError(
                    "translation is no longer at the expected revision: "
                    f"expected={expected_translation_revision}, actual={current_translation_revision}"
                )
            translation = WritingReferenceTranslationRevision.model_validate_json(
                translation_row["payload_json"]
            ).model_copy(update={"status": str(translation_row["current_status"])})
            if str(translation_row["current_span_id"]) != translation.span_id:
                connection.rollback()
                raise ValueError("current translation source span does not match its stored revision")

            span_row = connection.execute(
                """
                SELECT span.payload_json AS span_payload_json,
                       extraction.payload_json AS extraction_payload_json
                FROM writing_reference_source_spans AS span
                JOIN writing_reference_extractions AS extraction
                  ON extraction.tenant_id=span.tenant_id
                 AND extraction.project_id=span.project_id
                 AND extraction.artifact_id=span.artifact_id
                 AND extraction.extraction_revision=span.extraction_revision
                WHERE span.tenant_id=? AND span.project_id=? AND span.span_id=?
                """,
                (TENANT_ID, project_id, translation.span_id),
            ).fetchone()
            if span_row is None:
                connection.rollback()
                raise ValueError("current extraction lineage is required for corpus admission")
            from packages.contracts.workbench_contracts import WritingReferenceExtractedSpan

            span = WritingReferenceExtractedSpan.model_validate_json(
                span_row["span_payload_json"]
            )
            extraction = WritingReferenceExtractionResult.model_validate_json(
                span_row["extraction_payload_json"]
            )
            if (
                extraction.artifact_id != span.artifact_id
                or extraction.extraction_revision != span.extraction_revision
                or not any(item.span_id == span.span_id for item in extraction.spans)
                or extraction.status in {"failed", "blocked", "invalidated"}
            ):
                connection.rollback()
                raise ValueError("current extraction lineage is required for corpus admission")
            extraction_review_row = connection.execute(
                """
                SELECT record.payload_json, state.decision AS current_decision
                FROM writing_reference_extraction_review_state AS state
                JOIN writing_reference_extraction_review_records AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.review_id=state.review_id
                WHERE state.tenant_id=? AND state.project_id=?
                  AND state.artifact_id=? AND state.extraction_revision=?
                """,
                (
                    TENANT_ID,
                    project_id,
                    span.artifact_id,
                    span.extraction_revision,
                ),
            ).fetchone()
            if extraction_review_row is None:
                connection.rollback()
                raise ValueError("approved medical structure review is required for corpus admission")
            extraction_review = WritingReferenceExtractionReviewDecision.model_validate_json(
                extraction_review_row["payload_json"]
            )
            if (
                str(extraction_review_row["current_decision"]) != "approved"
                or extraction_review.decision != "approved"
            ):
                connection.rollback()
                raise ValueError("approved medical structure review is required for corpus admission")
            artifact = self._document_artifact_with(
                connection,
                project_id,
                span.artifact_id,
            )
            if not artifact.source_current:
                connection.rollback()
                raise ValueError("current source artifact is required for corpus admission")
            ocr_projection = self._effective_ocr_consistency_projection(
                connection,
                project_id,
                span.artifact_id,
                span.extraction_revision,
            )
            if ocr_projection.effective_status not in {
                "pass",
                "medical_confirmed_with_residual_issue",
            }:
                connection.rollback()
                raise ValueError(
                    "current OCR consistency disposition is required for corpus admission"
                )

            if translation.document_sha256 != artifact.content_sha256:
                connection.rollback()
                raise ValueError("translation document hash does not match the current source artifact")

            validation_row = connection.execute(
                """
                SELECT record.payload_json, state.status AS current_status
                FROM writing_reference_document_validation_state AS state
                JOIN writing_reference_document_validation_records AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.validation_id=state.validation_id
                WHERE state.tenant_id=? AND state.project_id=? AND state.artifact_id=?
                """,
                (TENANT_ID, project_id, artifact.artifact_id),
            ).fetchone()
            if validation_row is None:
                connection.rollback()
                raise ValueError("current document content validation is required for corpus admission")
            validation = WritingReferenceDocumentValidationRecord.model_validate_json(
                validation_row["payload_json"]
            ).model_copy(update={"status": str(validation_row["current_status"])})
            if validation.artifact_id != artifact.artifact_id:
                connection.rollback()
                raise ValueError("current document validation does not match the source artifact")
            if validation.status not in {"confirmed", "user_overridden"}:
                connection.rollback()
                raise ValueError(
                    "document content validation must be confirmed or explicitly overridden before corpus admission"
                )
            if validation.document_sha256 != artifact.content_sha256:
                connection.rollback()
                raise ValueError("document content validation does not match the current file hash")

            review_row = connection.execute(
                """
                SELECT record.payload_json, state.review_id AS current_review_id,
                       state.decision AS current_decision
                FROM writing_reference_medical_review_state AS state
                JOIN writing_reference_medical_review_records AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.review_id=state.review_id
                WHERE state.tenant_id=? AND state.project_id=?
                  AND state.translation_id=? AND state.translation_revision=?
                """,
                (TENANT_ID, project_id, translation_id, expected_translation_revision),
            ).fetchone()
            if review_row is None:
                connection.rollback()
                raise KeyError(medical_review_id)
            if str(review_row["current_review_id"]) != medical_review_id:
                connection.rollback()
                raise WritingReferenceConflictError(
                    "supplied medical review is no longer the current review for this translation revision"
                )
            review = WritingReferenceMedicalReviewDecision.model_validate_json(
                review_row["payload_json"]
            )
            if (
                str(review_row["current_decision"]) != "approved"
                or review.translation_id != translation_id
                or review.translation_revision != expected_translation_revision
                or review.decision != "approved"
            ):
                connection.rollback()
                raise ValueError("current approved medical review is required")
            if (
                translation.fidelity_status != "passed"
                or translation.status
                not in {
                    "pending_author_confirmation",
                    "author_confirmed_admitted",
                    "pending_medical_approval",
                }
            ):
                connection.rollback()
                raise ValueError("translation is not eligible for corpus admission")

            if replay is not None:
                row = connection.execute(
                    "SELECT payload_json FROM writing_reference_evidence_briefs "
                    "WHERE tenant_id=? AND project_id=? AND brief_id=?",
                    (TENANT_ID, project_id, replay),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    raise WritingReferenceRepositoryError("idempotency result is missing")
                if manage_transaction:
                    connection.rollback()
                return WritingReferenceEvidenceBrief.model_validate_json(row["payload_json"])

            existing_row = connection.execute(
                """
                SELECT payload_json FROM writing_reference_evidence_briefs
                WHERE tenant_id=? AND project_id=?
                  AND translation_id=? AND translation_revision=?
                """,
                (TENANT_ID, project_id, translation_id, expected_translation_revision),
            ).fetchone()
            if existing_row is not None:
                existing = WritingReferenceEvidenceBrief.model_validate_json(
                    existing_row["payload_json"]
                )
                if existing.medical_review_id != medical_review_id:
                    connection.rollback()
                    raise WritingReferenceConflictError(
                        "translation revision is already admitted under a different medical review"
                    )
                self._record_idempotency(
                    connection,
                    project_id,
                    "admit_translation",
                    idempotency_key,
                    request_hash,
                    existing.brief_id,
                )
                if manage_transaction:
                    connection.commit()
                return existing

            brief_id = "wref_brief_" + _payload_hash(admission_semantic)[:20]
            now = _utc_now()
            brief = WritingReferenceEvidenceBrief(
                brief_id=brief_id, project_id=project_id, nct_id=artifact.nct_id,
                artifact_id=artifact.artifact_id, span_id=span.span_id,
                translation_id=translation_id, translation_revision=expected_translation_revision,
                ich_m11_anchor=span.ich_m11_anchor, approved_zh_text=translation.translated_text,
                source_locator=span.source_locator, source_text_sha256=span.source_text_sha256,
                document_sha256=artifact.content_sha256, glossary_version=translation.glossary_version,
                medical_review_id=medical_review_id,
                confirmation_type=(
                    "medical_author_confirmation"
                    if review.decision_type == "author_confirmation"
                    else "legacy_medical_review"
                ),
                author_confirmation_id=(
                    medical_review_id
                    if review.decision_type == "author_confirmation"
                    else ""
                ),
                created_at=now,
            )
            connection.execute("INSERT INTO writing_reference_evidence_briefs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (TENANT_ID, project_id, brief.brief_id, brief.nct_id, brief.artifact_id, brief.span_id, brief.translation_id, brief.translation_revision, brief.ich_m11_anchor, brief.status, _canonical_json(brief.model_dump(mode="json")), now.isoformat()))
            self._record_idempotency(connection, project_id, "admit_translation", idempotency_key, request_hash, brief.brief_id)
            connection.execute(
                """
                UPDATE writing_reference_translation_state
                SET status='author_confirmed_admitted', updated_at=?
                WHERE tenant_id=? AND project_id=? AND translation_id=? AND revision=?
                """,
                (
                    now.isoformat(),
                    TENANT_ID,
                    project_id,
                    translation_id,
                    expected_translation_revision,
                ),
            )
            self._append_audit(
                connection,
                project_id,
                "translation_admitted_to_corpus",
                brief.brief_id,
                _actor,
                {
                    "translation_id": translation_id,
                    "translation_revision": expected_translation_revision,
                    "author_confirmation_id": medical_review_id,
                },
            )
            if manage_transaction:
                connection.commit()
            return brief

    def evidence_briefs(self, project_id: str, *, ich_m11_anchor: Optional[str] = None) -> list[WritingReferenceEvidenceBrief]:
        query = "SELECT payload_json FROM writing_reference_evidence_briefs WHERE tenant_id=? AND project_id=? AND status='approved_current'"
        params: list[Any] = [TENANT_ID, project_id]
        if ich_m11_anchor:
            query += " AND ich_m11_anchor=?"
            params.append(ich_m11_anchor)
        query += " ORDER BY created_at, brief_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [WritingReferenceEvidenceBrief.model_validate_json(row["payload_json"]) for row in rows]

    def medical_reviews(self, project_id: str) -> list[WritingReferenceMedicalReviewDecision]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record.payload_json
                FROM writing_reference_medical_review_state AS state
                JOIN writing_reference_medical_review_records AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.review_id=state.review_id
                WHERE state.tenant_id=? AND state.project_id=?
                ORDER BY state.updated_at, state.translation_id
                """,
                (TENANT_ID, project_id),
            ).fetchall()
        return [
            WritingReferenceMedicalReviewDecision.model_validate_json(row["payload_json"])
            for row in rows
        ]

    def evidence_brief_history(self, project_id: str) -> list[WritingReferenceEvidenceBrief]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json, status
                FROM writing_reference_evidence_briefs
                WHERE tenant_id=? AND project_id=?
                ORDER BY created_at, brief_id
                """,
                (TENANT_ID, project_id),
            ).fetchall()
        return [
            WritingReferenceEvidenceBrief.model_validate_json(row["payload_json"]).model_copy(
                update={"status": str(row["status"])}
            )
            for row in rows
        ]

    def health_report(self) -> dict[str, Any]:
        with self._connect() as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            version = int(
                connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                or 0
            )
        return {
            "status": "ok" if integrity == "ok" and not foreign_keys else "error",
            "schema_version": version,
            "integrity_check": integrity,
            "foreign_key_violations": len(foreign_keys),
        }

    def verify_audit_chain(self, project_id: str) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM writing_reference_audit_chain WHERE tenant_id=? AND project_id=? ORDER BY sequence_no",
                (TENANT_ID, project_id),
            ).fetchall()
        errors = []
        previous_hash = ""
        expected_sequence = 1
        for row in rows:
            if int(row["sequence_no"]) != expected_sequence:
                errors.append(f"audit sequence gap at {expected_sequence}")
            if str(row["previous_hash"]) != previous_hash:
                errors.append(f"audit previous hash mismatch at {row['sequence_no']}")
            material = {
                "tenant_id": TENANT_ID,
                "project_id": project_id,
                "sequence_no": int(row["sequence_no"]),
                "event_id": str(row["event_id"]),
                "event_type": str(row["event_type"]),
                "target_id": str(row["target_id"]),
                "actor": str(row["actor"]),
                "detail": json.loads(row["detail_json"]),
                "previous_hash": str(row["previous_hash"]),
                "created_at": str(row["created_at"]),
            }
            calculated = _payload_hash(material)
            if calculated != str(row["event_hash"]):
                errors.append(f"audit event hash mismatch at {row['sequence_no']}")
            previous_hash = str(row["event_hash"])
            expected_sequence += 1
        return errors

    # ------------------------------------------------------------------
    # Round 7: document-level plan, chunk, and chapter-integration
    # persistence methods.  These follow the same immutable-record +
    # state-projection pattern as the existing translation/review records.
    # ------------------------------------------------------------------

    def save_document_structure_plan(
        self,
        plan: DocumentStructurePlan,
        *,
        idempotency_key: str,
    ) -> DocumentStructurePlan:
        """Persist an immutable document structure plan.

        Returns the existing plan if this idempotency key has already been
        used.  The plan table is immutable — no update or delete is allowed.
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = self.save_document_structure_plan_with_connection(
                connection,
                plan,
                idempotency_key=idempotency_key,
            )
            connection.commit()
        return result

    def save_document_structure_plan_with_connection(
        self,
        connection: sqlite3.Connection,
        plan: DocumentStructurePlan,
        *,
        idempotency_key: str,
    ) -> DocumentStructurePlan:
        """Persist a plan inside the caller's active transaction.

        This is used by the batch contract-transition transaction so the new
        immutable migration plan, its bounded audit record, item lineage,
        batch attempt, and retry idempotency commit or roll back together.
        The method never begins, commits, or rolls back the supplied
        connection.
        """
        payload = plan.model_dump(mode="json")
        request_hash = _payload_hash(
            {"plan": payload, "idempotency_key": idempotency_key}
        )
        replay = self._idempotent_result(
            connection,
            plan.project_id,
            "save_document_structure_plan",
            idempotency_key,
            request_hash,
        )
        if replay is not None:
            row = connection.execute(
                """
                SELECT payload_json FROM writing_reference_document_structure_plans
                WHERE tenant_id=? AND project_id=? AND plan_id=?
                """,
                (TENANT_ID, plan.project_id, replay),
            ).fetchone()
            if row is None:
                raise WritingReferenceRepositoryError(
                    "document-plan idempotency points to a missing plan"
                )
            return DocumentStructurePlan.model_validate_json(
                row["payload_json"]
            )
        connection.execute(
            """
            INSERT INTO writing_reference_document_structure_plans(
                tenant_id, project_id, plan_id, artifact_id,
                extraction_revision, document_sha256, document_role,
                planner_model, planner_prompt_version, planner_input_hash,
                planner_output_hash, planner_contract_fingerprint,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_ID,
                plan.project_id,
                plan.plan_id,
                plan.artifact_id,
                plan.extraction_revision,
                plan.document_sha256,
                plan.document_role,
                plan.planner_model,
                plan.planner_prompt_version,
                plan.planner_input_hash,
                plan.planner_output_hash,
                plan.planner_contract_fingerprint,
                _canonical_json(payload),
                plan.created_at.isoformat(),
            ),
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO writing_reference_document_structure_plan_state(
                tenant_id, project_id, artifact_id, extraction_revision,
                planner_contract_fingerprint, plan_id, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_ID,
                plan.project_id,
                plan.artifact_id,
                plan.extraction_revision,
                plan.planner_contract_fingerprint,
                plan.plan_id,
                plan.status,
                _utc_now().isoformat(),
            ),
        )
        self._record_idempotency(
            connection,
            plan.project_id,
            "save_document_structure_plan",
            idempotency_key,
            request_hash,
            plan.plan_id,
        )
        self._append_audit(
            connection,
            plan.project_id,
            "document_structure_plan_saved",
            plan.plan_id,
            (
                "system_contract_migration"
                if plan.contract_migration_namespace
                else "system_planner"
            ),
            {
                "artifact_id": plan.artifact_id,
                "extraction_revision": plan.extraction_revision,
                "planner_model": plan.planner_model,
                "planner_contract_fingerprint": (
                    plan.planner_contract_fingerprint
                ),
            },
        )
        if plan.contract_migration_namespace:
            self._append_audit(
                connection,
                plan.project_id,
                "document_structure_plan_contract_migrated",
                plan.plan_id,
                "system_contract_migration",
                {
                    "artifact_id": plan.artifact_id,
                    "extraction_revision": plan.extraction_revision,
                    "migration_namespace": (
                        plan.contract_migration_namespace
                    ),
                    "transition_version": plan.contract_transition_version,
                    "source_plan_id": plan.contract_source_plan_id,
                    "source_fingerprint": (
                        plan.contract_source_fingerprint
                    ),
                    "target_fingerprint": (
                        plan.contract_target_fingerprint
                    ),
                    "source_prompt_version": (
                        plan.contract_source_prompt_version
                    ),
                    "target_prompt_version": (
                        plan.contract_target_prompt_version
                    ),
                    "source_payload_sha256": (
                        plan.contract_source_payload_sha256
                    ),
                    "target_payload_sha256": (
                        plan.contract_target_payload_sha256
                    ),
                    "chapter_count": len(plan.chapters),
                    "status": plan.status,
                },
            )
        return plan

    def any_document_structure_plan(
        self,
        project_id: str,
        artifact_id: str,
        extraction_revision: str,
    ) -> Optional[DocumentStructurePlan]:
        """Return any current plan for artifact/extraction (fingerprint-agnostic)."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT record.payload_json
                FROM writing_reference_document_structure_plan_state AS state
                JOIN writing_reference_document_structure_plans AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.plan_id=state.plan_id
                WHERE state.tenant_id=? AND state.project_id=?
                  AND state.artifact_id=? AND state.extraction_revision=?
                ORDER BY state.updated_at DESC, state.plan_id DESC
                LIMIT 1
                """,
                (TENANT_ID, project_id, artifact_id, extraction_revision),
            ).fetchone()
        if row is None:
            return None
        return DocumentStructurePlan.model_validate_json(row["payload_json"])

    def current_document_structure_plan(
        self,
        project_id: str,
        artifact_id: str,
        extraction_revision: str,
        planner_contract_fingerprint: str,
    ) -> Optional[DocumentStructurePlan]:
        """Return the current plan for the given contract fingerprint, or None."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT state.plan_id, record.payload_json
                FROM writing_reference_document_structure_plan_state AS state
                JOIN writing_reference_document_structure_plans AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.plan_id=state.plan_id
                WHERE state.tenant_id=? AND state.project_id=?
                  AND state.artifact_id=? AND state.extraction_revision=?
                  AND state.planner_contract_fingerprint=?
                """,
                (
                    TENANT_ID,
                    project_id,
                    artifact_id,
                    extraction_revision,
                    planner_contract_fingerprint,
                ),
            ).fetchone()
        if row is None:
            return None
        return DocumentStructurePlan.model_validate_json(row["payload_json"])

    def save_translation_chunk(
        self,
        chunk: TranslationChunkRecord,
        *,
        idempotency_key: str,
    ) -> TranslationChunkRecord:
        """Persist an immutable translation chunk."""
        payload = chunk.model_dump(mode="json")
        request_hash = _semantic_payload_hash(
            {"chunk": payload, "idempotency_key": idempotency_key}
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._idempotent_result(
                    connection,
                    chunk.project_id,
                    "save_translation_chunk",
                    idempotency_key,
                    request_hash,
                )
            except WritingReferenceConflictError:
                # Legacy rows hashed created_at; accept semantic replay.
                prior = connection.execute(
                    """
                    SELECT result_id FROM writing_reference_idempotency
                    WHERE tenant_id=? AND project_id=? AND operation=? AND idempotency_key=?
                    """,
                    (
                        TENANT_ID,
                        chunk.project_id,
                        "save_translation_chunk",
                        idempotency_key,
                    ),
                ).fetchone()
                if prior is None:
                    raise
                row = connection.execute(
                    """
                    SELECT payload_json FROM writing_reference_translation_chunks
                    WHERE tenant_id=? AND project_id=? AND chunk_id=?
                    """,
                    (TENANT_ID, chunk.project_id, str(prior["result_id"])),
                ).fetchone()
                if row is None:
                    raise
                existing = TranslationChunkRecord.model_validate_json(row["payload_json"])
                if _semantic_payload_hash(existing.model_dump(mode="json")) != (
                    _semantic_payload_hash(payload)
                ):
                    raise
                connection.commit()
                return existing
            if replay is not None:
                row = connection.execute(
                    """
                    SELECT payload_json FROM writing_reference_translation_chunks
                    WHERE tenant_id=? AND project_id=? AND chunk_id=?
                    """,
                    (TENANT_ID, chunk.project_id, replay),
                ).fetchone()
                connection.commit()
                return TranslationChunkRecord.model_validate_json(row["payload_json"])
            try:
                connection.execute(
                    """
                    INSERT INTO writing_reference_translation_chunks(
                        tenant_id, project_id, chunk_id, plan_id, artifact_id,
                        chapter_id, chunk_order, chunk_fingerprint,
                        source_span_ids_json, source_text_sha256,
                        adjacent_context_sha256, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        TENANT_ID,
                        chunk.project_id,
                        chunk.chunk_id,
                        chunk.plan_id,
                        chunk.artifact_id,
                        chunk.chapter_id,
                        chunk.chunk_order,
                        chunk.chunk_fingerprint,
                        _canonical_json(chunk.source_span_ids),
                        chunk.source_text_sha256,
                        chunk.adjacent_context_sha256,
                        _canonical_json(payload),
                        chunk.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT payload_json FROM writing_reference_translation_chunks
                    WHERE tenant_id=? AND project_id=? AND chunk_id=?
                    """,
                    (TENANT_ID, chunk.project_id, chunk.chunk_id),
                ).fetchone()
                if row is None:
                    raise
                existing = TranslationChunkRecord.model_validate_json(row["payload_json"])
                if existing.chunk_fingerprint != chunk.chunk_fingerprint:
                    connection.rollback()
                    raise WritingReferenceConflictError(
                        "translation chunk_id reused with different fingerprint "
                        f"(chunk_id={chunk.chunk_id})"
                    )
                connection.commit()
                return existing
            connection.execute(
                """
                INSERT OR REPLACE INTO writing_reference_translation_chunk_state(
                    tenant_id, project_id, chunk_id, plan_id, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    chunk.project_id,
                    chunk.chunk_id,
                    chunk.plan_id,
                    chunk.status,
                    _utc_now().isoformat(),
                ),
            )
            self._record_idempotency(
                connection,
                chunk.project_id,
                "save_translation_chunk",
                idempotency_key,
                request_hash,
                chunk.chunk_id,
            )
            self._append_audit(
                connection,
                chunk.project_id,
                "translation_chunk_saved",
                chunk.chunk_id,
                "system_pipeline",
                {
                    "plan_id": chunk.plan_id,
                    "chapter_id": chunk.chapter_id,
                    "chunk_fingerprint": chunk.chunk_fingerprint,
                },
            )
            connection.commit()
        return chunk

    def translation_chunks_for_plan(
        self,
        project_id: str,
        plan_id: str,
    ) -> list[TranslationChunkRecord]:
        """Return all persisted chunks for a plan, ordered by chapter then order."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_translation_chunks
                WHERE tenant_id=? AND project_id=? AND plan_id=?
                ORDER BY chapter_id, chunk_order
                """,
                (TENANT_ID, project_id, plan_id),
            ).fetchall()
        return [
            TranslationChunkRecord.model_validate_json(row["payload_json"])
            for row in rows
        ]

    def save_chapter_integration_result(
        self,
        result: ChapterIntegrationResult,
        *,
        idempotency_key: str,
    ) -> ChapterIntegrationResult:
        """Persist an immutable chapter integration result."""
        payload = result.model_dump(mode="json")
        request_hash = _semantic_payload_hash(
            {"integration": payload, "idempotency_key": idempotency_key}
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._idempotent_result(
                    connection,
                    result.project_id,
                    "save_chapter_integration_result",
                    idempotency_key,
                    request_hash,
                )
            except WritingReferenceConflictError:
                prior = connection.execute(
                    """
                    SELECT result_id FROM writing_reference_idempotency
                    WHERE tenant_id=? AND project_id=? AND operation=? AND idempotency_key=?
                    """,
                    (
                        TENANT_ID,
                        result.project_id,
                        "save_chapter_integration_result",
                        idempotency_key,
                    ),
                ).fetchone()
                if prior is None:
                    raise
                row = connection.execute(
                    """
                    SELECT payload_json FROM writing_reference_chapter_integration_results
                    WHERE tenant_id=? AND project_id=? AND integration_id=?
                    """,
                    (TENANT_ID, result.project_id, str(prior["result_id"])),
                ).fetchone()
                if row is None:
                    raise
                existing = ChapterIntegrationResult.model_validate_json(row["payload_json"])
                if _semantic_payload_hash(existing.model_dump(mode="json")) != (
                    _semantic_payload_hash(payload)
                ):
                    raise
                connection.commit()
                return existing
            if replay is not None:
                row = connection.execute(
                    """
                    SELECT payload_json FROM writing_reference_chapter_integration_results
                    WHERE tenant_id=? AND project_id=? AND integration_id=?
                    """,
                    (TENANT_ID, result.project_id, replay),
                ).fetchone()
                connection.commit()
                return ChapterIntegrationResult.model_validate_json(row["payload_json"])
            try:
                connection.execute(
                    """
                    INSERT INTO writing_reference_chapter_integration_results(
                        tenant_id, project_id, integration_id, plan_id, artifact_id,
                        chapter_id, integrated_text_sha256, flash_model,
                        flash_prompt_version, fidelity_status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        TENANT_ID,
                        result.project_id,
                        result.integration_id,
                        result.plan_id,
                        result.artifact_id,
                        result.chapter_id,
                        result.integrated_text_sha256,
                        result.flash_model,
                        result.flash_prompt_version,
                        result.fidelity_status,
                        _canonical_json(payload),
                        result.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError:
                # Immutable row already occupies plan_id+chapter_id — reuse it.
                row = connection.execute(
                    """
                    SELECT payload_json FROM writing_reference_chapter_integration_results
                    WHERE tenant_id=? AND project_id=? AND plan_id=? AND chapter_id=?
                    """,
                    (
                        TENANT_ID,
                        result.project_id,
                        result.plan_id,
                        result.chapter_id,
                    ),
                ).fetchone()
                if row is None:
                    raise
                existing = ChapterIntegrationResult.model_validate_json(
                    row["payload_json"]
                )
                if (
                    existing.translation_contract_fingerprint
                    != result.translation_contract_fingerprint
                ):
                    raise WritingReferenceConflictError(
                        "chapter integration identity reused with a different "
                        "translation contract fingerprint"
                    )
                connection.commit()
                return existing
            self._record_idempotency(
                connection,
                result.project_id,
                "save_chapter_integration_result",
                idempotency_key,
                request_hash,
                result.integration_id,
            )
            self._append_audit(
                connection,
                result.project_id,
                "chapter_integration_saved",
                result.integration_id,
                "system_pipeline",
                {
                    "plan_id": result.plan_id,
                    "chapter_id": result.chapter_id,
                    "fidelity_status": result.fidelity_status,
                },
            )
            connection.commit()
        return result

    def chapter_integration_result(
        self,
        project_id: str,
        plan_id: str,
        chapter_id: str,
        *,
        translation_contract_fingerprint: str = "",
    ) -> Optional[ChapterIntegrationResult]:
        """Return the integration result for a chapter, or None.

        When ``translation_contract_fingerprint`` is given, only a row
        produced under that exact downstream translation contract is
        returned.  Rows written under older contracts remain immutable on
        disk but are never silently reused as current output.
        """
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_chapter_integration_results
                WHERE tenant_id=? AND project_id=? AND plan_id=? AND chapter_id=?
                ORDER BY created_at DESC
                """,
                (TENANT_ID, project_id, plan_id, chapter_id),
            ).fetchall()
        if not rows:
            return None
        if not translation_contract_fingerprint:
            return ChapterIntegrationResult.model_validate_json(rows[0]["payload_json"])
        for row in rows:
            result = ChapterIntegrationResult.model_validate_json(row["payload_json"])
            if result.translation_contract_fingerprint == translation_contract_fingerprint:
                return result
        return None

    def save_composite_pipeline_run(
        self,
        run: CompositePipelineRun,
        *,
        idempotency_key: str,
    ) -> CompositePipelineRun:
        """Persist an immutable composite pipeline run ledger entry."""
        payload = run.model_dump(mode="json")
        request_hash = _semantic_payload_hash(
            {"run": payload, "idempotency_key": idempotency_key}
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._idempotent_result(
                    connection,
                    run.project_id,
                    "save_composite_pipeline_run",
                    idempotency_key,
                    request_hash,
                )
            except WritingReferenceConflictError:
                prior = connection.execute(
                    """
                    SELECT result_id FROM writing_reference_idempotency
                    WHERE tenant_id=? AND project_id=? AND operation=? AND idempotency_key=?
                    """,
                    (
                        TENANT_ID,
                        run.project_id,
                        "save_composite_pipeline_run",
                        idempotency_key,
                    ),
                ).fetchone()
                if prior is None:
                    raise
                row = connection.execute(
                    """
                    SELECT payload_json FROM writing_reference_composite_pipeline_runs
                    WHERE tenant_id=? AND project_id=? AND run_id=?
                    """,
                    (TENANT_ID, run.project_id, str(prior["result_id"])),
                ).fetchone()
                if row is None:
                    raise
                existing = CompositePipelineRun.model_validate_json(row["payload_json"])
                if _semantic_payload_hash(existing.model_dump(mode="json")) != (
                    _semantic_payload_hash(payload)
                ):
                    raise
                connection.commit()
                return existing
            if replay is not None:
                row = connection.execute(
                    """
                    SELECT payload_json FROM writing_reference_composite_pipeline_runs
                    WHERE tenant_id=? AND project_id=? AND run_id=?
                    """,
                    (TENANT_ID, run.project_id, replay),
                ).fetchone()
                connection.commit()
                return CompositePipelineRun.model_validate_json(row["payload_json"])
            connection.execute(
                """
                INSERT INTO writing_reference_composite_pipeline_runs(
                    tenant_id, project_id, run_id, plan_id, chapter_id,
                    artifact_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    run.project_id,
                    run.run_id,
                    run.plan_id,
                    run.chapter_id,
                    run.artifact_id,
                    _canonical_json(payload),
                    run.created_at.isoformat(),
                ),
            )
            self._record_idempotency(
                connection,
                run.project_id,
                "save_composite_pipeline_run",
                idempotency_key,
                request_hash,
                run.run_id,
            )
            self._append_audit(
                connection,
                run.project_id,
                "composite_pipeline_run_saved",
                run.run_id,
                "system_pipeline",
                {
                    "plan_id": run.plan_id,
                    "chapter_id": run.chapter_id,
                    "stage_count": len(run.stages),
                },
            )
            connection.commit()
        return run

    def composite_pipeline_run(
        self, project_id: str, run_id: str
    ) -> Optional[CompositePipelineRun]:
        """Return a composite pipeline run by ID, or None."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_composite_pipeline_runs
                WHERE tenant_id=? AND project_id=? AND run_id=?
                """,
                (TENANT_ID, project_id, run_id),
            ).fetchone()
        if row is None:
            return None
        return CompositePipelineRun.model_validate_json(row["payload_json"])

    # ------------------------------------------------------------------
    # Server-owned upper-layer Flash/Pro execution and escalation lineage.
    # ------------------------------------------------------------------

    def save_upper_layer_stage_run(
        self,
        run: WritingReferenceUpperLayerStageRun,
        *,
        execution_fingerprint: str,
        prompt_text: str,
        input_payload: Any,
        output_payload: Any,
        hy_mt2_target_map_sha256: str = "",
    ) -> WritingReferenceUpperLayerStageRun:
        if len(execution_fingerprint) != 64:
            raise ValueError("upper-layer execution fingerprint must be SHA-256")
        input_payload_json = _canonical_json(input_payload)
        if _payload_hash(input_payload) != run.input_hash:
            raise ValueError("upper-layer input hash does not match payload")
        prompt_sha256 = sha256(prompt_text.encode("utf-8")).hexdigest()
        if run.stage == "post_hy_mt2_integration_qc":
            if (
                len(hy_mt2_target_map_sha256) != 64
                or any(
                    char not in "0123456789abcdef"
                    for char in hy_mt2_target_map_sha256
                )
            ):
                raise ValueError(
                    "post-Hy-MT2 upper-layer run requires target-map SHA-256"
                )
        if run.status in {"succeeded", "completed_degraded"}:
            if output_payload is None:
                raise ValueError("successful upper-layer run requires output payload")
            if _payload_hash(output_payload) != run.output_hash:
                raise ValueError("upper-layer output hash does not match payload")
        elif output_payload is not None or run.output_hash:
            raise ValueError("failed upper-layer run cannot persist accepted output")
        output_payload_json = (
            _canonical_json(output_payload) if output_payload is not None else ""
        )
        payload = run.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT execution_fingerprint, prompt_sha256, input_payload_json,
                       output_payload_json, payload_json
                FROM writing_reference_upper_layer_stage_runs
                WHERE tenant_id=? AND project_id=? AND stage_run_id=?
                """,
                (TENANT_ID, run.project_id, run.stage_run_id),
            ).fetchone()
            if existing is not None:
                expected = (
                    execution_fingerprint,
                    prompt_sha256,
                    input_payload_json,
                    output_payload_json,
                    _canonical_json(payload),
                )
                actual = (
                    str(existing["execution_fingerprint"]),
                    str(existing["prompt_sha256"]),
                    str(existing["input_payload_json"]),
                    str(existing["output_payload_json"]),
                    str(existing["payload_json"]),
                )
                if actual == expected:
                    return run
                # 0924V2 §5: a previously FAILED run may be superseded by a
                # new attempt under the same immutable stage_run_id when the
                # input identity matches (idempotent redrive). The prior
                # payload is preserved in the run's own audit trail; the new
                # state replaces only terminal-failed rows.
                import json as _json

                try:
                    prior_status = str(
                        (json.loads(existing["payload_json"]) or {}).get(
                            "status",
                            "",
                        )
                    )
                except (ValueError, TypeError):
                    prior_status = ""
                if prior_status in {"failed_retryable", "failed"}:
                    connection.execute(
                        """
                        UPDATE writing_reference_upper_layer_stage_runs
                        SET execution_fingerprint=?, prompt_sha256=?,
                            input_payload_json=?, output_payload_json=?,
                            payload_json=?
                        WHERE tenant_id=? AND project_id=? AND stage_run_id=?
                        """,
                        (
                            execution_fingerprint,
                            prompt_sha256,
                            input_payload_json,
                            output_payload_json,
                            _canonical_json(payload),
                            TENANT_ID,
                            run.project_id,
                            run.stage_run_id,
                        ),
                    )
                    return run
                connection.rollback()
                raise WritingReferenceConflictError(
                    "upper-layer stage run identity reused with different payload"
                )
            connection.execute(
                """
                INSERT INTO writing_reference_upper_layer_stage_runs(
                    tenant_id, project_id, stage_run_id, owner_type, owner_id,
                    artifact_id, extraction_revision, stage, requested_model,
                    status, execution_fingerprint, prompt_sha256, prompt_text,
                    input_hash, input_payload_json, output_hash,
                    output_payload_json, hy_mt2_target_map_sha256,
                    parent_stage_run_id, escalation_id, payload_json,
                    created_at, completed_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    TENANT_ID,
                    run.project_id,
                    run.stage_run_id,
                    run.owner_type,
                    run.owner_id,
                    run.artifact_id,
                    run.extraction_revision,
                    run.stage,
                    run.requested_model,
                    run.status,
                    execution_fingerprint,
                    prompt_sha256,
                    prompt_text,
                    run.input_hash,
                    input_payload_json,
                    run.output_hash,
                    output_payload_json,
                    hy_mt2_target_map_sha256,
                    run.parent_stage_run_id,
                    run.escalation_id,
                    _canonical_json(payload),
                    run.created_at.isoformat(),
                    run.completed_at.isoformat(),
                ),
            )
            self._append_audit(
                connection,
                run.project_id,
                "upper_layer_stage_run_saved",
                run.stage_run_id,
                "system_upper_layer_orchestrator",
                {
                    "stage": run.stage,
                    "requested_model": run.requested_model,
                    "response_model": run.response_model,
                    "status": run.status,
                    "failure_code": run.failure_code,
                    "provider_call_count": run.provider_call_count,
                    "planner_attempt_count": run.planner_attempt_count,
                    "provider_call_attempts": [
                        {
                            "call_index": attempt.call_index,
                            "planner_attempt": attempt.planner_attempt,
                            "retry_kind": attempt.retry_kind,
                            "status": attempt.status,
                            "failure_code": attempt.failure_code,
                            "input_hash": attempt.input_hash,
                            "prompt_version": attempt.prompt_version,
                            "correction_instruction_sha256": (
                                attempt.correction_instruction_sha256
                            ),
                        }
                        for attempt in run.provider_call_attempts
                    ],
                    "execution_fingerprint": execution_fingerprint,
                    "retry_generation": run.retry_generation,
                    "retry_parent_stage_run_id": (
                        run.retry_parent_stage_run_id
                    ),
                    "contract_supersession_generation": (
                        run.contract_supersession_generation
                    ),
                    "contract_supersession_transition_version": (
                        run.contract_supersession_transition_version
                    ),
                    "contract_supersession_source_stage_run_id": (
                        run.contract_supersession_source_stage_run_id
                    ),
                    "contract_supersession_source_execution_fingerprint": (
                        run.contract_supersession_source_execution_fingerprint
                    ),
                    "contract_supersession_source_prompt_version": (
                        run.contract_supersession_source_prompt_version
                    ),
                    "contract_supersession_target_prompt_version": (
                        run.contract_supersession_target_prompt_version
                    ),
                    "parent_stage_run_id": run.parent_stage_run_id,
                    "escalation_id": run.escalation_id,
                },
            )
            if run.contract_supersession_generation:
                self._append_audit(
                    connection,
                    run.project_id,
                    "upper_layer_contract_supersession_recorded",
                    run.stage_run_id,
                    "system_upper_layer_orchestrator",
                    {
                        "artifact_id": run.artifact_id,
                        "batch_id": run.batch_id,
                        "item_id": run.item_id,
                        "extraction_revision": run.extraction_revision,
                        "generation": (
                            run.contract_supersession_generation
                        ),
                        "transition_version": (
                            run.contract_supersession_transition_version
                        ),
                        "source_stage_run_id": (
                            run.contract_supersession_source_stage_run_id
                        ),
                        "source_execution_fingerprint": (
                            run.contract_supersession_source_execution_fingerprint
                        ),
                        "source_prompt_version": (
                            run.contract_supersession_source_prompt_version
                        ),
                        "target_prompt_version": (
                            run.contract_supersession_target_prompt_version
                        ),
                        "target_execution_fingerprint": (
                            execution_fingerprint
                        ),
                        "requested_model": run.requested_model,
                        "status": run.status,
                        "failure_code": run.failure_code,
                    },
                )
            connection.commit()
        return run

    def optional_upper_layer_stage_run(
        self,
        project_id: str,
        stage_run_id: str,
    ) -> Optional[WritingReferenceUpperLayerStageRun]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_upper_layer_stage_runs
                WHERE tenant_id=? AND project_id=? AND stage_run_id=?
                """,
                (TENANT_ID, project_id, stage_run_id),
            ).fetchone()
        if row is None:
            return None
        return WritingReferenceUpperLayerStageRun.model_validate_json(
            row["payload_json"]
        )

    def upper_layer_stage_run(
        self,
        project_id: str,
        stage_run_id: str,
    ) -> WritingReferenceUpperLayerStageRun:
        run = self.optional_upper_layer_stage_run(project_id, stage_run_id)
        if run is None:
            raise KeyError(stage_run_id)
        return run

    def latest_failed_upper_layer_source_stage_run(
        self,
        project_id: str,
        *,
        owner_type: str,
        owner_id: str,
        artifact_id: str,
        extraction_revision: str,
        requested_model: str,
        connection: Any | None = None,
    ) -> Optional[WritingReferenceUpperLayerStageRun]:
        """Return the latest exact failed parentless planning run for a model.

        The optional existing connection lets a batch retry resolve legacy
        lineage inside its own ``BEGIN IMMEDIATE`` transaction.
        """

        def _lookup(active_connection: Any) -> Any:
            return active_connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_upper_layer_stage_runs
                WHERE tenant_id=? AND project_id=?
                  AND owner_type=? AND owner_id=?
                  AND artifact_id=? AND extraction_revision=?
                  AND stage='document_planning'
                  AND requested_model=?
                  AND parent_stage_run_id=''
                  AND escalation_id=''
                  AND status IN (
                    'failed_retryable',
                    'failed_escalatable',
                    'failed_terminal',
                    'interrupted'
                  )
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (
                    TENANT_ID,
                    project_id,
                    owner_type,
                    owner_id,
                    artifact_id,
                    extraction_revision,
                    requested_model,
                ),
            ).fetchone()

        if connection is not None:
            row = _lookup(connection)
        else:
            with self._connect() as active_connection:
                row = _lookup(active_connection)
        if row is None:
            return None
        return WritingReferenceUpperLayerStageRun.model_validate_json(
            row["payload_json"]
        )

    def upper_layer_stage_run_execution(
        self,
        project_id: str,
        stage_run_id: str,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT execution_fingerprint, prompt_sha256, prompt_text,
                       input_hash, input_payload_json, output_hash,
                       output_payload_json, hy_mt2_target_map_sha256
                FROM writing_reference_upper_layer_stage_runs
                WHERE tenant_id=? AND project_id=? AND stage_run_id=?
                """,
                (TENANT_ID, project_id, stage_run_id),
            ).fetchone()
        if row is None:
            raise KeyError(stage_run_id)
        input_payload = json.loads(str(row["input_payload_json"]))
        output_payload_json = str(row["output_payload_json"])
        output_payload = (
            json.loads(output_payload_json) if output_payload_json else None
        )
        if _payload_hash(input_payload) != str(row["input_hash"]):
            raise WritingReferenceRepositoryError(
                "upper-layer input payload hash mismatch"
            )
        if sha256(str(row["prompt_text"]).encode("utf-8")).hexdigest() != str(
            row["prompt_sha256"]
        ):
            raise WritingReferenceRepositoryError("upper-layer prompt hash mismatch")
        if output_payload_json and _payload_hash(output_payload) != str(
            row["output_hash"]
        ):
            raise WritingReferenceRepositoryError(
                "upper-layer output payload hash mismatch"
            )
        return {
            "execution_fingerprint": str(row["execution_fingerprint"]),
            "prompt_text": str(row["prompt_text"]),
            "input_payload": input_payload,
            "output_payload": output_payload,
            "hy_mt2_target_map_sha256": str(
                row["hy_mt2_target_map_sha256"]
            ),
        }

    def upper_layer_stage_run_output(
        self,
        project_id: str,
        stage_run_id: str,
    ) -> Any:
        return self.upper_layer_stage_run_execution(
            project_id,
            stage_run_id,
        )["output_payload"]

    def save_upper_layer_escalation(
        self,
        escalation: WritingReferenceUpperLayerEscalation,
        *,
        request_fingerprint: str,
    ) -> WritingReferenceUpperLayerEscalation:
        if escalation.status != "queued":
            raise ValueError("new upper-layer escalation must be queued")
        if len(request_fingerprint) != 64:
            raise ValueError("upper-layer escalation fingerprint must be SHA-256")
        source = self.upper_layer_stage_run(
            escalation.project_id,
            escalation.source_stage_run_id,
        )
        if (
            source.requested_model != escalation.source_model
            or source.status != escalation.trigger_status
            or source.stage != escalation.stage
        ):
            raise ValueError("upper-layer escalation source lineage mismatch")
        expected_lineage_hash = _payload_hash(
            {
                "project_id": escalation.project_id,
                "stage": escalation.stage,
                "source_stage_run_id": escalation.source_stage_run_id,
                "target_stage_run_id": escalation.target_stage_run_id,
                "source_model": escalation.source_model,
                "target_model": escalation.target_model,
                "trigger_status": escalation.trigger_status,
                "trigger_code": source.failure_code,
                "request_fingerprint": request_fingerprint,
            }
        )
        if escalation.lineage_hash != expected_lineage_hash:
            raise ValueError("upper-layer escalation lineage hash mismatch")
        payload = escalation.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT request_fingerprint, payload_json
                FROM writing_reference_upper_layer_escalations
                WHERE tenant_id=? AND project_id=? AND source_stage_run_id=?
                """,
                (
                    TENANT_ID,
                    escalation.project_id,
                    escalation.source_stage_run_id,
                ),
            ).fetchone()
            if existing is not None:
                stored = WritingReferenceUpperLayerEscalation.model_validate_json(
                    existing["payload_json"]
                )
                connection.rollback()
                if (
                    str(existing["request_fingerprint"]) != request_fingerprint
                    or stored.escalation_id != escalation.escalation_id
                    or stored.target_stage_run_id
                    != escalation.target_stage_run_id
                ):
                    raise WritingReferenceConflictError(
                        "upper-layer source run already has another escalation"
                    )
                return stored
            connection.execute(
                """
                INSERT INTO writing_reference_upper_layer_escalations(
                    tenant_id, project_id, escalation_id, source_stage_run_id,
                    target_stage_run_id, stage, trigger_status, status,
                    request_fingerprint, lineage_hash, claim_token,
                    lease_expires_at, payload_json, created_at, updated_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, ?, '')
                """,
                (
                    TENANT_ID,
                    escalation.project_id,
                    escalation.escalation_id,
                    escalation.source_stage_run_id,
                    escalation.target_stage_run_id,
                    escalation.stage,
                    escalation.trigger_status,
                    escalation.status,
                    request_fingerprint,
                    escalation.lineage_hash,
                    _canonical_json(payload),
                    escalation.created_at.isoformat(),
                    escalation.updated_at.isoformat(),
                ),
            )
            self._append_audit(
                connection,
                escalation.project_id,
                "upper_layer_pro_escalation_queued",
                escalation.escalation_id,
                "system_upper_layer_orchestrator",
                {
                    "stage": escalation.stage,
                    "source_stage_run_id": escalation.source_stage_run_id,
                    "target_stage_run_id": escalation.target_stage_run_id,
                    "trigger_status": escalation.trigger_status,
                    "trigger_code": escalation.trigger_code,
                    "lineage_hash": escalation.lineage_hash,
                },
            )
            connection.commit()
        return escalation

    def upper_layer_escalation(
        self,
        project_id: str,
        escalation_id: str,
    ) -> WritingReferenceUpperLayerEscalation:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_upper_layer_escalations
                WHERE tenant_id=? AND project_id=? AND escalation_id=?
                """,
                (TENANT_ID, project_id, escalation_id),
            ).fetchone()
        if row is None:
            raise KeyError(escalation_id)
        return WritingReferenceUpperLayerEscalation.model_validate_json(
            row["payload_json"]
        )

    def upper_layer_escalation_for_source(
        self,
        project_id: str,
        source_stage_run_id: str,
    ) -> Optional[WritingReferenceUpperLayerEscalation]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_upper_layer_escalations
                WHERE tenant_id=? AND project_id=? AND source_stage_run_id=?
                """,
                (TENANT_ID, project_id, source_stage_run_id),
            ).fetchone()
        if row is None:
            return None
        return WritingReferenceUpperLayerEscalation.model_validate_json(
            row["payload_json"]
        )

    def upper_layer_escalation_request_fingerprint(
        self,
        project_id: str,
        escalation_id: str,
    ) -> str:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT request_fingerprint
                FROM writing_reference_upper_layer_escalations
                WHERE tenant_id=? AND project_id=? AND escalation_id=?
                """,
                (TENANT_ID, project_id, escalation_id),
            ).fetchone()
        if row is None:
            raise KeyError(escalation_id)
        return str(row["request_fingerprint"])

    def claim_upper_layer_escalation(
        self,
        project_id: str,
        escalation_id: str,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> Optional[tuple[WritingReferenceUpperLayerEscalation, str]]:
        if lease_expires_at <= now:
            raise ValueError("upper-layer escalation lease must expire in the future")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, lease_expires_at, payload_json
                FROM writing_reference_upper_layer_escalations
                WHERE tenant_id=? AND project_id=? AND escalation_id=?
                """,
                (TENANT_ID, project_id, escalation_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(escalation_id)
            status = str(row["status"])
            lease_value = str(row["lease_expires_at"])
            eligible = status in {"queued", "failed_retryable"}
            if status == "running" and lease_value:
                eligible = datetime.fromisoformat(lease_value) <= now
            if not eligible:
                connection.rollback()
                return None
            current = WritingReferenceUpperLayerEscalation.model_validate_json(
                row["payload_json"]
            )
            claimed = current.model_copy(
                update={"status": "running", "updated_at": now}
            )
            claim_token = "wref_ulclaim_" + uuid4().hex
            connection.execute(
                """
                UPDATE writing_reference_upper_layer_escalations
                SET status='running', claim_token=?, lease_expires_at=?,
                    payload_json=?, updated_at=?
                WHERE tenant_id=? AND project_id=? AND escalation_id=?
                """,
                (
                    claim_token,
                    lease_expires_at.isoformat(),
                    _canonical_json(claimed.model_dump(mode="json")),
                    now.isoformat(),
                    TENANT_ID,
                    project_id,
                    escalation_id,
                ),
            )
            self._append_audit(
                connection,
                project_id,
                "upper_layer_pro_escalation_claimed",
                escalation_id,
                "system_upper_layer_orchestrator",
                {
                    "source_stage_run_id": claimed.source_stage_run_id,
                    "target_stage_run_id": claimed.target_stage_run_id,
                },
            )
            connection.commit()
        return claimed, claim_token

    def finish_upper_layer_escalation(
        self,
        project_id: str,
        escalation_id: str,
        *,
        claim_token: str,
        target_run: WritingReferenceUpperLayerStageRun,
        status: str,
        now: datetime,
    ) -> WritingReferenceUpperLayerEscalation:
        if status not in {"completed", "failed_retryable", "failed_terminal"}:
            raise ValueError("invalid terminal upper-layer escalation status")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, claim_token, target_stage_run_id, payload_json
                FROM writing_reference_upper_layer_escalations
                WHERE tenant_id=? AND project_id=? AND escalation_id=?
                """,
                (TENANT_ID, project_id, escalation_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(escalation_id)
            if (
                str(row["status"]) != "running"
                or str(row["claim_token"]) != claim_token
            ):
                connection.rollback()
                current = WritingReferenceUpperLayerEscalation.model_validate_json(
                    row["payload_json"]
                )
                if (
                    current.status == status
                    and current.target_stage_run_id == target_run.stage_run_id
                ):
                    return current
                raise WritingReferenceConflictError(
                    "upper-layer escalation claim is no longer current"
                )
            if str(row["target_stage_run_id"]) != target_run.stage_run_id:
                connection.rollback()
                raise WritingReferenceConflictError(
                    "upper-layer escalation target run mismatch"
                )
            current = WritingReferenceUpperLayerEscalation.model_validate_json(
                row["payload_json"]
            )
            self._validate_upper_layer_escalation_target(current, target_run)
            persisted_target = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_upper_layer_stage_runs
                WHERE tenant_id=? AND project_id=? AND stage_run_id=?
                """,
                (TENANT_ID, project_id, target_run.stage_run_id),
            ).fetchone()
            if persisted_target is None:
                connection.rollback()
                raise WritingReferenceConflictError(
                    "upper-layer escalation target run is not persisted"
                )
            completed_at = now if status in {"completed", "failed_terminal"} else None
            updated = current.model_copy(
                update={
                    "status": status,
                    "updated_at": now,
                    "completed_at": completed_at,
                }
            )
            connection.execute(
                """
                UPDATE writing_reference_upper_layer_escalations
                SET status=?, claim_token='', lease_expires_at='',
                    payload_json=?, updated_at=?, completed_at=?
                WHERE tenant_id=? AND project_id=? AND escalation_id=?
                """,
                (
                    status,
                    _canonical_json(updated.model_dump(mode="json")),
                    now.isoformat(),
                    completed_at.isoformat() if completed_at else "",
                    TENANT_ID,
                    project_id,
                    escalation_id,
                ),
            )
            self._append_audit(
                connection,
                project_id,
                "upper_layer_pro_escalation_finished",
                escalation_id,
                "system_upper_layer_orchestrator",
                {
                    "target_stage_run_id": target_run.stage_run_id,
                    "target_run_status": target_run.status,
                    "escalation_status": status,
                },
            )
            connection.commit()
        return updated

    def finalize_upper_layer_escalation_from_existing_run(
        self,
        project_id: str,
        escalation_id: str,
        target_run: WritingReferenceUpperLayerStageRun,
        *,
        now: datetime,
    ) -> WritingReferenceUpperLayerEscalation:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT target_stage_run_id, status, payload_json
                FROM writing_reference_upper_layer_escalations
                WHERE tenant_id=? AND project_id=? AND escalation_id=?
                """,
                (TENANT_ID, project_id, escalation_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(escalation_id)
            current = WritingReferenceUpperLayerEscalation.model_validate_json(
                row["payload_json"]
            )
            if str(row["target_stage_run_id"]) != target_run.stage_run_id:
                connection.rollback()
                raise WritingReferenceConflictError(
                    "upper-layer persisted target run mismatch"
                )
            self._validate_upper_layer_escalation_target(current, target_run)
            status = (
                "completed"
                if target_run.status == "succeeded"
                else "failed_retryable"
                if target_run.status in {"failed_retryable", "interrupted"}
                else "failed_terminal"
            )
            if current.status == status:
                connection.rollback()
                return current
            if current.status in {"completed", "failed_terminal"}:
                connection.rollback()
                return current
            completed_at = now if status in {"completed", "failed_terminal"} else None
            updated = current.model_copy(
                update={
                    "status": status,
                    "updated_at": now,
                    "completed_at": completed_at,
                }
            )
            connection.execute(
                """
                UPDATE writing_reference_upper_layer_escalations
                SET status=?, claim_token='', lease_expires_at='',
                    payload_json=?, updated_at=?, completed_at=?
                WHERE tenant_id=? AND project_id=? AND escalation_id=?
                """,
                (
                    status,
                    _canonical_json(updated.model_dump(mode="json")),
                    now.isoformat(),
                    completed_at.isoformat() if completed_at else "",
                    TENANT_ID,
                    project_id,
                    escalation_id,
                ),
            )
            self._append_audit(
                connection,
                project_id,
                "upper_layer_pro_escalation_recovered",
                escalation_id,
                "system_upper_layer_orchestrator",
                {
                    "target_stage_run_id": target_run.stage_run_id,
                    "target_run_status": target_run.status,
                    "escalation_status": status,
                },
            )
            connection.commit()
        return updated

    def recoverable_upper_layer_escalations(
        self,
        *,
        project_id: Optional[str] = None,
        now: datetime,
    ) -> list[WritingReferenceUpperLayerEscalation]:
        query = """
            SELECT payload_json
            FROM writing_reference_upper_layer_escalations
            WHERE tenant_id=?
              AND (
                  status='queued'
                  OR (
                      status='running'
                      AND lease_expires_at <> ''
                      AND lease_expires_at <= ?
                  )
              )
        """
        params: list[Any] = [TENANT_ID, now.isoformat()]
        if project_id is not None:
            query += " AND project_id=?"
            params.append(project_id)
        query += " ORDER BY created_at, escalation_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            WritingReferenceUpperLayerEscalation.model_validate_json(
                row["payload_json"]
            )
            for row in rows
        ]

    @staticmethod
    def _validate_upper_layer_escalation_target(
        escalation: WritingReferenceUpperLayerEscalation,
        target_run: WritingReferenceUpperLayerStageRun,
    ) -> None:
        if (
            target_run.project_id != escalation.project_id
            or target_run.stage_run_id != escalation.target_stage_run_id
            or target_run.requested_model != escalation.target_model
            or target_run.parent_stage_run_id != escalation.source_stage_run_id
            or target_run.escalation_id != escalation.escalation_id
            or target_run.stage != escalation.stage
        ):
            raise WritingReferenceConflictError(
                "upper-layer escalation target lineage mismatch"
            )

    def upper_layer_execution_replay(
        self,
        project_id: str,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> Optional[str]:
        with self._connect() as connection:
            return self._idempotent_result(
                connection,
                project_id,
                "execute_upper_layer_stage",
                idempotency_key,
                request_hash,
            )

    def record_upper_layer_execution_idempotency(
        self,
        project_id: str,
        *,
        idempotency_key: str,
        request_hash: str,
        result_id: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(
                connection,
                project_id,
                "execute_upper_layer_stage",
                idempotency_key,
                request_hash,
            )
            if replay is not None:
                if replay == result_id:
                    connection.rollback()
                    return
                row = connection.execute(
                    """
                    SELECT status FROM writing_reference_upper_layer_stage_runs
                    WHERE tenant_id=? AND project_id=? AND stage_run_id=?
                    """,
                    (TENANT_ID, project_id, replay),
                ).fetchone()
                replayed_status = str(row["status"]) if row is not None else ""
                if replayed_status in UPPER_LAYER_SUCCESSFUL_RUN_STATUSES:
                    # Divergent successful results remain a hard conflict.
                    connection.rollback()
                    raise WritingReferenceConflictError(
                        "upper-layer idempotency result changed"
                    )
                # 0926 fix: the pointer references a FAILED run, which
                # 86fe7ea defines as not-a-result — the executor's replay
                # fall-through re-dispatches a fresh run each round, so the
                # strict conflict here discarded every fresh result
                # (including real completed_degraded ones) and re-burned a
                # model call per retry.  Advance the pointer in-transaction;
                # the audit chain keeps the advance traceable.
                connection.execute(
                    """
                    UPDATE writing_reference_idempotency
                    SET result_id=?
                    WHERE tenant_id=? AND project_id=? AND operation=?
                      AND idempotency_key=?
                    """,
                    (
                        result_id,
                        TENANT_ID,
                        project_id,
                        "execute_upper_layer_stage",
                        idempotency_key,
                    ),
                )
                self._append_audit(
                    connection,
                    project_id,
                    "upper_layer_idempotency_pointer_advanced",
                    result_id,
                    "upper_layer_executor",
                    {
                        "operation": "execute_upper_layer_stage",
                        "idempotency_key": idempotency_key,
                        "previous_result_id": replay,
                        "previous_status": replayed_status,
                        "new_result_id": result_id,
                    },
                )
                connection.commit()
                return
            self._record_idempotency(
                connection,
                project_id,
                "execute_upper_layer_stage",
                idempotency_key,
                request_hash,
                result_id,
            )
            connection.commit()

    def current_translation_by_id(
        self, project_id: str, translation_id: str
    ) -> Optional[WritingReferenceTranslationRevision]:
        """Return the current revision of a translation_id, or None."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT record.payload_json, state.status AS current_status
                FROM writing_reference_translation_state AS state
                JOIN writing_reference_translation_records AS record
                  ON record.tenant_id=state.tenant_id
                 AND record.project_id=state.project_id
                 AND record.translation_id=state.translation_id
                 AND record.revision=state.revision
                WHERE state.tenant_id=? AND state.project_id=?
                  AND state.translation_id=?
                """,
                (TENANT_ID, project_id, translation_id),
            ).fetchone()
        if row is None:
            return None
        return WritingReferenceTranslationRevision.model_validate_json(
            row["payload_json"]
        ).model_copy(update={"status": str(row["current_status"])})

    # ------------------------------------------------------------------
    # Competitor triage run / confirmation persistence.
    # ------------------------------------------------------------------

    def store_triage_run(self, run: CompetitorTriageRun) -> CompetitorTriageRun:
        with self._connect() as connection:
            now = _utc_now().isoformat()
            connection.execute(
                """
                INSERT INTO competitor_triage_runs(
                    tenant_id, project_id, run_id, journey_id, snapshot_id,
                    status, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, project_id, run_id) DO UPDATE SET
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    TENANT_ID,
                    run.project_id,
                    run.run_id,
                    run.journey_id,
                    run.snapshot_id,
                    run.status.value,
                    _canonical_json(run.model_dump(mode="json")),
                    run.created_at.isoformat(),
                    now,
                ),
            )
            connection.commit()
        return run

    def triage_run(self, project_id: str, run_id: str) -> Optional[CompetitorTriageRun]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM competitor_triage_runs
                WHERE tenant_id=? AND project_id=? AND run_id=?
                """,
                (TENANT_ID, project_id, run_id),
            ).fetchone()
        if row is None:
            return None
        return CompetitorTriageRun.model_validate_json(row["payload_json"])

    def latest_triage_run_for_snapshot(
        self, project_id: str, snapshot_id: str
    ) -> Optional[CompetitorTriageRun]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM competitor_triage_runs
                WHERE tenant_id=? AND project_id=? AND snapshot_id=?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (TENANT_ID, project_id, snapshot_id),
            ).fetchone()
        if row is None:
            return None
        return CompetitorTriageRun.model_validate_json(row["payload_json"])

    def store_triage_confirmation(
        self, confirmation: CompetitorTriageConfirmationRecord
    ) -> CompetitorTriageConfirmationRecord:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO competitor_triage_confirmations(
                    tenant_id, project_id, confirmation_id, run_id, snapshot_id,
                    confirmation_hash, projection_status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, project_id, confirmation_id) DO UPDATE SET
                    projection_status = excluded.projection_status,
                    payload_json = excluded.payload_json
                """,
                (
                    TENANT_ID,
                    confirmation.project_id,
                    confirmation.confirmation_id,
                    confirmation.run_id,
                    confirmation.snapshot_id,
                    confirmation.confirmation_hash,
                    confirmation.projection_status,
                    _canonical_json(confirmation.model_dump(mode="json")),
                    confirmation.created_at.isoformat(),
                ),
            )
            connection.commit()
        return confirmation

    def triage_confirmation(
        self, project_id: str, confirmation_id: str
    ) -> Optional[CompetitorTriageConfirmationRecord]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM competitor_triage_confirmations
                WHERE tenant_id=? AND project_id=? AND confirmation_id=?
                """,
                (TENANT_ID, project_id, confirmation_id),
            ).fetchone()
        if row is None:
            return None
        return CompetitorTriageConfirmationRecord.model_validate_json(row["payload_json"])

    def triage_confirmation_for_run(
        self, project_id: str, run_id: str
    ) -> Optional[CompetitorTriageConfirmationRecord]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM competitor_triage_confirmations
                WHERE tenant_id=? AND project_id=? AND run_id=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (TENANT_ID, project_id, run_id),
            ).fetchone()
        if row is None:
            return None
        return CompetitorTriageConfirmationRecord.model_validate_json(row["payload_json"])

    def triage_idempotent_replay(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> Optional[str]:
        return self._idempotent_result(
            connection, project_id, operation, idempotency_key, request_hash
        )

    def triage_record_idempotency(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        result_id: str,
    ) -> None:
        self._record_idempotency(
            connection,
            project_id,
            operation,
            idempotency_key,
            request_hash,
            result_id,
        )

    @staticmethod
    def _append_audit(
        connection: sqlite3.Connection,
        project_id: str,
        event_type: str,
        target_id: str,
        actor: str,
        detail: dict[str, Any],
    ) -> None:
        row = connection.execute(
            "SELECT sequence_no, event_hash FROM writing_reference_audit_chain WHERE tenant_id=? AND project_id=? ORDER BY sequence_no DESC LIMIT 1",
            (TENANT_ID, project_id),
        ).fetchone()
        sequence = int(row["sequence_no"]) + 1 if row else 1
        previous_hash = str(row["event_hash"]) if row else ""
        created_at = _utc_now().isoformat()
        event_id = "wref_audit_" + _payload_hash(
            {"project_id": project_id, "sequence": sequence, "event_type": event_type, "target_id": target_id, "created_at": created_at}
        )[:24]
        material = {
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "sequence_no": sequence,
            "event_id": event_id,
            "event_type": event_type,
            "target_id": target_id,
            "actor": actor,
            "detail": detail,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
        event_hash = _payload_hash(material)
        connection.execute(
            "INSERT INTO writing_reference_audit_chain VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (TENANT_ID, project_id, sequence, event_id, event_type, target_id, actor, _canonical_json(detail), previous_hash, event_hash, created_at),
        )

    @staticmethod
    def _idempotent_result(
        connection: sqlite3.Connection,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> Optional[str]:
        row = connection.execute(
            """
            SELECT request_hash, result_id FROM writing_reference_idempotency
            WHERE tenant_id = ? AND project_id = ? AND operation = ? AND idempotency_key = ?
            """,
            (TENANT_ID, project_id, operation, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if str(row["request_hash"]) != request_hash:
            raise WritingReferenceConflictError(
                "idempotency key reused with different request "
                f"(operation={operation}, key={idempotency_key})"
            )
        return str(row["result_id"])

    @staticmethod
    def _record_idempotency(
        connection: sqlite3.Connection,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        result_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO writing_reference_idempotency(
                tenant_id, project_id, operation, idempotency_key,
                request_hash, result_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_ID, project_id, operation, idempotency_key,
                request_hash, result_id, _utc_now().isoformat(),
            ),
        )
