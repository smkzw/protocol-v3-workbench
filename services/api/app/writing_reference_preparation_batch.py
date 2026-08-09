from __future__ import annotations

import json
import inspect
import logging
import urllib.error
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Callable, Iterable

from packages.contracts.workbench_contracts.models import (
    WritingReferenceDocumentIngestRequest,
    WritingReferencePreparationBatch,
    WritingReferencePreparationBatchCreateRequest,
    WritingReferencePreparationBatchStageAdvanceRequest,
    WritingReferencePreparationBatchItem,
    WritingReferencePreparationProgress,
    WritingReferencePreparationBatchRetryRequest,
    WritingReferencePreparationStageState,
)

from .paddle_ocr_adapter import PADDLE_OCR_MODEL, PaddleOcrOutcomeUnknownError
from .writing_reference_repository import (
    TENANT_ID,
    WritingReferenceRepository,
)


# Competitor corpus preparation accepts Protocol documents only.
# Standalone SAP is excluded because the corpus builder needs protocol wording
# sources, not statistical analysis plans. ``protocol_sap`` remains eligible
# because it contains a Protocol section.
ALLOWED_DOCUMENT_TYPES = {"protocol", "protocol_sap"}
# The broader set (including standalone SAP) is retained for non-corpus
# preparation paths that may still need SAP for non-corpus purposes.
ALLOWED_DOCUMENT_TYPES_INCLUDING_SAP = {"protocol", "sap", "protocol_sap"}
TERMINAL_STAGE_STATUSES = {"succeeded", "review_required", "not_applicable"}
# The preparation worker is synchronous today.  Keep each admission bounded
# to the OCR-side shared admission ceiling and require an explicit, durable
# stage transition before the next group is submitted.
DEFAULT_PREPARATION_STAGE_SIZE = 8
MAX_PREPARATION_STAGE_SIZE = 32
PreparationProgressCallback = Callable[[WritingReferencePreparationBatch], None]

_PROGRESS_PHASE_RANGES = {
    "downloading": (0, 12),
    "native_extracting": (12, 22),
    "ocr_rendering": (22, 32),
    "ocr_completing": (32, 82),
    "extraction_persisting": (82, 90),
    "content_validating": (90, 100),
    "completed": (100, 100),
    "failed": (0, 100),
}
logger = logging.getLogger(__name__)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class WritingReferencePreparationItemError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WritingReferencePreparationBatchService:
    """Durable orchestration for public Protocol (研究方案) download and preparation.

    The competitor corpus builder accepts Protocol documents only. Standalone
    SAP is excluded from preparation scope; ``protocol_sap`` is eligible because
    it contains a Protocol section.
    """

    def __init__(
        self,
        repository: WritingReferenceRepository,
        journey_service: Any,
        document_service: Any,
        extraction_service: Any,
        ocr_consistency_service: Any = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.repository = repository
        self.journey_service = journey_service
        self.document_service = document_service
        self.extraction_service = extraction_service
        self.ocr_consistency_service = ocr_consistency_service
        self.clock = clock
        self._initialize()
        self._recover_interrupted_items()

    def _initialize(self) -> None:
        with self.repository._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS writing_reference_preparation_schema (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS writing_reference_preparation_batches (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    scope_sha256 TEXT NOT NULL,
                    retained_candidate_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL CHECK (attempt >= 1),
                    admission_plan_id TEXT NOT NULL DEFAULT '',
                    admission_stage_index INTEGER NOT NULL DEFAULT 1,
                    admission_stage_size INTEGER NOT NULL DEFAULT 8,
                    deferred_item_count INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, batch_id),
                    FOREIGN KEY (tenant_id, project_id, snapshot_id)
                    REFERENCES writing_reference_search_snapshots(tenant_id, project_id, snapshot_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_preparation_items (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    item_kind TEXT NOT NULL,
                    nct_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    source_scope_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL CHECK (attempt >= 0),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, item_id),
                    UNIQUE (tenant_id, project_id, batch_id, nct_id, document_id, item_kind),
                    FOREIGN KEY (tenant_id, project_id, batch_id)
                    REFERENCES writing_reference_preparation_batches(tenant_id, project_id, batch_id)
                );

                CREATE TRIGGER IF NOT EXISTS trg_wref_preparation_batch_scope_immutable
                BEFORE UPDATE ON writing_reference_preparation_batches
                WHEN OLD.snapshot_id <> NEW.snapshot_id
                  OR OLD.scope_sha256 <> NEW.scope_sha256
                  OR OLD.retained_candidate_ids_json <> NEW.retained_candidate_ids_json
                BEGIN
                    SELECT RAISE(ABORT, 'writing reference preparation scope is immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_wref_preparation_batch_no_delete
                BEFORE DELETE ON writing_reference_preparation_batches BEGIN
                    SELECT RAISE(ABORT, 'writing reference preparation batches are auditable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_wref_preparation_item_no_delete
                BEFORE DELETE ON writing_reference_preparation_items BEGIN
                    SELECT RAISE(ABORT, 'writing reference preparation items are auditable');
                END;
                """
            )
            self._ensure_batch_columns(connection)
            connection.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS trg_wref_preparation_batch_plan_immutable
                BEFORE UPDATE ON writing_reference_preparation_batches
                WHEN OLD.admission_plan_id <> NEW.admission_plan_id
                  OR OLD.admission_stage_size <> NEW.admission_stage_size
                BEGIN
                    SELECT RAISE(ABORT, 'writing reference preparation admission plan is immutable');
                END;
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO writing_reference_preparation_schema(version, applied_at) VALUES (1, ?)",
                (self.clock().isoformat(),),
            )

    @staticmethod
    def _ensure_batch_columns(connection: Any) -> None:
        """Add stage metadata to databases created by the pre-stage schema."""

        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(writing_reference_preparation_batches)"
            ).fetchall()
        }
        migrations = (
            ("admission_plan_id", "TEXT NOT NULL DEFAULT ''"),
            ("admission_stage_index", "INTEGER NOT NULL DEFAULT 1"),
            ("admission_stage_size", "INTEGER NOT NULL DEFAULT 8"),
            ("deferred_item_count", "INTEGER NOT NULL DEFAULT 0"),
        )
        for name, definition in migrations:
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE writing_reference_preparation_batches "
                    f"ADD COLUMN {name} {definition}"
                )

    def create(
        self,
        project_id: str,
        request: WritingReferencePreparationBatchCreateRequest,
    ) -> WritingReferencePreparationBatch:
        stage_size = min(
            MAX_PREPARATION_STAGE_SIZE,
            max(1, int(request.stage_size or DEFAULT_PREPARATION_STAGE_SIZE)),
        )
        request_hash = _payload_hash(
            {"snapshot_id": request.snapshot_id, "stage_size": stage_size}
        )
        replay = self._idempotent_batch(
            project_id,
            "create_preparation_batch",
            request.idempotency_key,
            request_hash,
        )
        if replay:
            return self.get(project_id, replay)

        retained_ids, scope_entries = self._frozen_scope(project_id, request.snapshot_id)
        scope_sha256 = _payload_hash(
            {
                "project_id": project_id,
                "snapshot_id": request.snapshot_id,
                "retained_candidate_ids": retained_ids,
                "entries": scope_entries,
            }
        )
        admission_plan_id = "wref_prep_plan_" + _payload_hash(
            {
                "project_id": project_id,
                "snapshot_id": request.snapshot_id,
                "scope_sha256": scope_sha256,
                "stage_size": stage_size,
            }
        )[:24]
        batch_id = "wref_prep_" + _payload_hash(
            {
                "project_id": project_id,
                "snapshot_id": request.snapshot_id,
                "scope_sha256": scope_sha256,
                "idempotency_key": request.idempotency_key,
                "stage_size": stage_size,
            }
        )[:24]
        now = self.clock()
        public_index = 0
        items = []
        for entry in scope_entries:
            item = self._new_item(project_id, request.snapshot_id, batch_id, entry, now)
            if item.item_kind == "public_document":
                if public_index >= stage_size:
                    item = item.model_copy(
                        update={
                            "status": "deferred",
                            "progress": WritingReferencePreparationProgress(
                                phase="queued",
                                current_substep="等待下一阶段准入",
                                completed=0,
                                total=1,
                                percent=0,
                                unit="file",
                                context={
                                    "admission_plan_id": admission_plan_id,
                                    "admission_stage_index": 1,
                                    "deferred": True,
                                },
                            ),
                        },
                        deep=True,
                    )
                public_index += 1
            items.append(item)
        deferred_item_count = sum(item.status == "deferred" for item in items)
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self.repository._idempotent_result(
                connection,
                project_id,
                "create_preparation_batch",
                request.idempotency_key,
                request_hash,
            )
            if replay:
                connection.commit()
                return self.get(project_id, replay)
            connection.execute(
                """
                INSERT INTO writing_reference_preparation_batches(
                    tenant_id, project_id, batch_id, snapshot_id, scope_sha256,
                    retained_candidate_ids_json, status, attempt,
                    admission_plan_id, admission_stage_index, admission_stage_size,
                    deferred_item_count, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'accepted', 1, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    project_id,
                    batch_id,
                    request.snapshot_id,
                    scope_sha256,
                    _canonical_json(retained_ids),
                    admission_plan_id,
                    stage_size,
                    deferred_item_count,
                    request.actor,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            for item in items:
                self._insert_item_with(connection, item)
            self.repository._record_idempotency(
                connection,
                project_id,
                "create_preparation_batch",
                request.idempotency_key,
                request_hash,
                batch_id,
            )
            self.repository._append_audit(
                connection,
                project_id,
                "preparation_batch_created",
                batch_id,
                request.actor,
                {
                    "snapshot_id": request.snapshot_id,
                    "scope_sha256": scope_sha256,
                    "admission_plan_id": admission_plan_id,
                    "admission_stage_index": 1,
                    "admission_stage_size": stage_size,
                    "retained_candidate_ids": retained_ids,
                    "document_item_count": sum(item.item_kind == "public_document" for item in items),
                    "deferred_item_count": deferred_item_count,
                    "manual_upload_required_count": sum(
                        item.item_kind == "study_manual_upload_required" for item in items
                    ),
                },
            )
            connection.commit()
        if not any(item.item_kind == "public_document" for item in items):
            self._refresh_batch_status(project_id, batch_id)
        return self.get(project_id, batch_id)

    def run_pending(
        self,
        project_id: str,
        batch_id: str,
        actor: str,
        *,
        progress_callback: PreparationProgressCallback | None = None,
    ) -> None:
        item_ids = self._item_ids_with_status(project_id, batch_id, "pending")
        self._run_items(
            project_id,
            batch_id,
            item_ids,
            actor,
            allowed_statuses={"pending"},
            progress_callback=progress_callback,
        )

    def run_failed(
        self,
        project_id: str,
        batch_id: str,
        actor: str,
        *,
        progress_callback: PreparationProgressCallback | None = None,
    ) -> None:
        item_ids = self._item_ids_with_status(project_id, batch_id, "failed")
        self._run_items(
            project_id,
            batch_id,
            item_ids,
            actor,
            allowed_statuses={"failed"},
            progress_callback=progress_callback,
        )

    def get(self, project_id: str, batch_id: str) -> WritingReferencePreparationBatch:
        with self.repository._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM writing_reference_preparation_batches
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchone()
            if row is None:
                raise KeyError(batch_id)
            item_rows = connection.execute(
                """
                SELECT payload_json FROM writing_reference_preparation_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                ORDER BY nct_id, item_kind, document_type, document_id, item_id
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchall()
        items = [
            WritingReferencePreparationBatchItem.model_validate_json(item["payload_json"])
            for item in item_rows
        ]
        retained_candidate_ids = json.loads(row["retained_candidate_ids_json"])
        counts = self._counts(items)
        counts["deferred_item_count"] = int(
            row["deferred_item_count"]
            if row["deferred_item_count"] is not None
            else counts.get("deferred_item_count", 0)
        )
        return WritingReferencePreparationBatch(
            batch_id=str(row["batch_id"]),
            project_id=str(row["project_id"]),
            snapshot_id=str(row["snapshot_id"]),
            scope_sha256=str(row["scope_sha256"]),
            retained_candidate_ids=retained_candidate_ids,
            retained_candidate_count=len(retained_candidate_ids),
            status=str(row["status"]),
            attempt=int(row["attempt"]),
            admission_plan_id=str(row["admission_plan_id"] or ""),
            admission_stage_index=int(row["admission_stage_index"] or 1),
            admission_stage_size=int(row["admission_stage_size"] or DEFAULT_PREPARATION_STAGE_SIZE),
            items=items,
            created_by=str(row["created_by"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            **counts,
        )

    def latest(self, project_id: str, snapshot_id: str) -> WritingReferencePreparationBatch:
        with self.repository._connect() as connection:
            row = connection.execute(
                """
                SELECT batch_id FROM writing_reference_preparation_batches
                WHERE tenant_id=? AND project_id=? AND snapshot_id=?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (TENANT_ID, project_id, snapshot_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"{project_id}/{snapshot_id}")
        return self.get(project_id, str(row["batch_id"]))

    def retry(
        self,
        project_id: str,
        batch_id: str,
        request: WritingReferencePreparationBatchRetryRequest,
    ) -> WritingReferencePreparationBatch:
        self.get(project_id, batch_id)
        request_hash = _payload_hash({"batch_id": batch_id})
        replay = self._idempotent_batch(
            project_id,
            "retry_preparation_batch",
            request.idempotency_key,
            request_hash,
        )
        if replay:
            return self.get(project_id, replay)
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self.repository._idempotent_result(
                connection,
                project_id,
                "retry_preparation_batch",
                request.idempotency_key,
                request_hash,
            )
            if replay:
                connection.commit()
                return self.get(project_id, replay)
            # Select failed items for retry.
            # review_required items whose validation was user_overridden are
            # reconciled to "prepared" via _apply_validation, not via retry.
            failed_rows = connection.execute(
                """
                SELECT item_id FROM writing_reference_preparation_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND item_kind='public_document'
                  AND status='failed'
                  AND COALESCE(
                    json_extract(payload_json, '$.error_code'),
                    ''
                  )!='paddle_ocr_outcome_unknown'
                ORDER BY item_id
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchall()
            failed_ids = [str(row["item_id"]) for row in failed_rows]
            outcome_unknown_rows = connection.execute(
                """
                SELECT item_id FROM writing_reference_preparation_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND item_kind='public_document'
                  AND status='failed'
                  AND json_extract(
                    payload_json,
                    '$.error_code'
                  )='paddle_ocr_outcome_unknown'
                ORDER BY item_id
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchall()
            outcome_unknown_ids = [
                str(row["item_id"]) for row in outcome_unknown_rows
            ]
            if failed_ids:
                connection.execute(
                    """
                    UPDATE writing_reference_preparation_batches
                    SET status='running', attempt=attempt+1, updated_at=?
                    WHERE tenant_id=? AND project_id=? AND batch_id=?
                    """,
                    (self.clock().isoformat(), TENANT_ID, project_id, batch_id),
                )
            self.repository._record_idempotency(
                connection,
                project_id,
                "retry_preparation_batch",
                request.idempotency_key,
                request_hash,
                batch_id,
            )
            self.repository._append_audit(
                connection,
                project_id,
                "preparation_batch_retry_requested",
                batch_id,
                request.actor,
                {
                    "failed_item_ids": failed_ids,
                    "outcome_unknown_item_ids_not_retried": outcome_unknown_ids,
                },
            )
            connection.commit()
        return self.get(project_id, batch_id)

    def _item_ids_with_status(
        self,
        project_id: str,
        batch_id: str,
        status: str,
    ) -> list[str]:
        with self.repository._connect() as connection:
            rows = connection.execute(
                """
                SELECT item_id FROM writing_reference_preparation_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND item_kind='public_document' AND status=?
                ORDER BY item_id
                """,
                (TENANT_ID, project_id, batch_id, status),
            ).fetchall()
        return [str(row["item_id"]) for row in rows]

    def _frozen_scope(self, project_id: str, snapshot_id: str) -> tuple[list[str], list[dict[str, Any]]]:
        journey = self.journey_service.get(project_id)
        triage = journey.corpus_triage

        # Authority path A (legacy, post-PICOS): finalized corpus triage
        corpus_finalized = triage.status == "finalized" and triage.snapshot_id == snapshot_id

        # Authority path B (pre-PICOS): authoritative discovery basket projection
        discovery = getattr(journey, "discovery_basket_projection", None)
        discovery_confirmed = (
            discovery is not None
            and discovery.confirmation_id
            and discovery.snapshot_id == snapshot_id
            and journey.search_plan is not None
            and journey.search_plan.latest_snapshot_id == snapshot_id
        )

        if not corpus_finalized and not discovery_confirmed:
            raise ValueError(
                "preparation requires either finalized corpus triage or a "
                "confirmed discovery basket projection for the locked snapshot"
            )

        if (
            journey.search_plan is None
            or journey.search_plan.latest_snapshot_id != snapshot_id
        ):
            raise ValueError("batch preparation must use the locked search snapshot")

        # Retained IDs: prefer finalized corpus triage, fall back to discovery
        if corpus_finalized:
            retained_ids = sorted(dict.fromkeys(triage.retained_candidate_ids))
        elif discovery is not None:
            retained_ids = sorted(dict.fromkeys(discovery.retained_nct_ids))
        else:
            retained_ids = []

        if not retained_ids:
            raise ValueError("confirmed basket has no retained candidates")

        snapshot = self.repository.search_snapshot(project_id, snapshot_id)
        candidates = {candidate.nct_id: candidate for candidate in snapshot.candidates}
        missing = sorted(set(retained_ids) - set(candidates))
        if missing:
            raise ValueError("retained candidates are absent from the locked snapshot: " + ", ".join(missing))
        decisions = {
            decision.nct_id: decision
            for decision in self.repository.relevance_decisions_for_snapshot(project_id, snapshot_id)
        }
        invalid = [
            nct_id
            for nct_id in retained_ids
            if decisions.get(nct_id) is None
            or decisions[nct_id].relevance_status not in {"direct_competitor", "indirect_reference"}
        ]
        if invalid:
            raise ValueError("retained candidates lack a current related decision: " + ", ".join(invalid))

        entries: list[dict[str, Any]] = []
        for nct_id in retained_ids:
            candidate = candidates[nct_id]
            documents = sorted(
                (
                    document
                    for document in candidate.public_documents
                    if document.document_type.strip().casefold() in ALLOWED_DOCUMENT_TYPES
                ),
                key=lambda document: (document.document_type, document.document_id),
            )
            if not documents:
                entries.append(
                    {
                        "item_kind": "study_manual_upload_required",
                        "nct_id": nct_id,
                        "document_id": "",
                        "document_type": "",
                        "filename": "",
                    }
                )
                continue
            for document in documents:
                entries.append(
                    {
                        "item_kind": "public_document",
                        "nct_id": nct_id,
                        "document_id": document.document_id,
                        "document_type": document.document_type.strip().casefold(),
                        "filename": document.filename,
                        "document_date": document.document_date,
                        "upload_date": document.upload_date,
                        "declared_size": document.declared_size,
                        "download_url": document.download_url,
                    }
                )
        return retained_ids, entries

    def _new_item(
        self,
        project_id: str,
        snapshot_id: str,
        batch_id: str,
        scope_entry: dict[str, Any],
        now: datetime,
    ) -> WritingReferencePreparationBatchItem:
        scope_hash = _payload_hash(scope_entry)
        item_id = "wref_prep_item_" + _payload_hash(
            {"batch_id": batch_id, "source_scope_sha256": scope_hash}
        )[:24]
        if scope_entry["item_kind"] == "study_manual_upload_required":
            not_applicable = WritingReferencePreparationStageState(status="not_applicable")
            return WritingReferencePreparationBatchItem(
                item_id=item_id,
                batch_id=batch_id,
                project_id=project_id,
                snapshot_id=snapshot_id,
                item_kind="study_manual_upload_required",
                nct_id=scope_entry["nct_id"],
                source_scope_sha256=scope_hash,
                status="manual_upload_required",
                error_code="no_public_protocol",
                error_detail="No public Protocol (研究方案) is present in the locked snapshot; manual upload is required.",
                ingest=not_applicable,
                extraction=not_applicable,
                validation=not_applicable,
                created_at=now,
                updated_at=now,
            )
        return WritingReferencePreparationBatchItem(
            item_id=item_id,
            batch_id=batch_id,
            project_id=project_id,
            snapshot_id=snapshot_id,
            item_kind="public_document",
            nct_id=scope_entry["nct_id"],
            document_id=scope_entry["document_id"],
            document_type=scope_entry["document_type"],
            filename=scope_entry["filename"],
            source_scope_sha256=scope_hash,
            created_at=now,
            updated_at=now,
        )

    def _run_items(
        self,
        project_id: str,
        batch_id: str,
        item_ids: Iterable[str],
        actor: str,
        *,
        allowed_statuses: set[str],
        progress_callback: PreparationProgressCallback | None,
    ) -> None:
        ids = list(item_ids)
        if ids:
            self._set_batch_status(project_id, batch_id, "running")
        self._emit_progress(project_id, batch_id, progress_callback)
        for item_id in ids:
            item = self._claim_item(project_id, batch_id, item_id, allowed_statuses)
            if item is not None:
                self._emit_progress(project_id, batch_id, progress_callback)
                self._process_claimed_item(
                    item,
                    actor,
                    progress_callback=progress_callback,
                )
                self._emit_progress(project_id, batch_id, progress_callback)
        self._refresh_batch_status(project_id, batch_id)
        self._emit_progress(project_id, batch_id, progress_callback)

    def admit_next_stage(
        self,
        project_id: str,
        batch_id: str,
        request: WritingReferencePreparationBatchStageAdvanceRequest,
    ) -> WritingReferencePreparationBatch:
        """Atomically move one bounded deferred stage into ``pending``.

        The transition is deliberately separate from ``run_pending``.  A
        duplicate click, duplicate worker, or restart therefore cannot submit
        the same document twice, and a stage boundary remains visible and
        auditable before any new download/OCR call is made.
        """

        current = self.get(project_id, batch_id)
        current_stage = int(current.admission_stage_index or 1)
        request_hash = _payload_hash(
            {
                "batch_id": batch_id,
                "admission_plan_id": current.admission_plan_id,
                "admission_stage_size": current.admission_stage_size,
            }
        )
        replay = self._idempotent_batch(
            project_id,
            "advance_preparation_stage",
            request.idempotency_key,
            request_hash,
        )
        if replay:
            return self.get(project_id, replay)

        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self.repository._idempotent_result(
                connection,
                project_id,
                "advance_preparation_stage",
                request.idempotency_key,
                request_hash,
            )
            if replay:
                connection.commit()
                return self.get(project_id, replay)

            deferred_rows = connection.execute(
                """
                SELECT item_id, payload_json
                FROM writing_reference_preparation_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND item_kind='public_document' AND status='deferred'
                ORDER BY nct_id, item_kind, document_type, document_id, item_id
                LIMIT ?
                """,
                (
                    TENANT_ID,
                    project_id,
                    batch_id,
                    max(1, int(current.admission_stage_size or DEFAULT_PREPARATION_STAGE_SIZE)),
                ),
            ).fetchall()
            if not deferred_rows:
                connection.rollback()
                raise ValueError(
                    "当前原文准备批次没有可准入的延后阶段"
                )
            admitted_item_ids: list[str] = []
            now = self.clock()
            for row in deferred_rows:
                item = WritingReferencePreparationBatchItem.model_validate_json(
                    row["payload_json"]
                )
                item = item.model_copy(
                    update={
                        "status": "pending",
                        "error_code": "",
                        "error_detail": "",
                        "progress": WritingReferencePreparationProgress(
                            phase="queued",
                            current_substep="已准入本阶段，等待处理",
                            completed=0,
                            total=1,
                            percent=0,
                            unit="file",
                            context={
                                "admission_plan_id": current.admission_plan_id,
                                "admission_stage_index": current_stage + 1,
                                "deferred": False,
                            },
                        ),
                        "updated_at": now,
                    },
                    deep=True,
                )
                self._write_item_with(connection, item)
                admitted_item_ids.append(item.item_id)

            remaining_row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM writing_reference_preparation_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND status='deferred'
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchone()
            remaining = int(remaining_row["count"] if remaining_row else 0)
            next_stage = current_stage + 1 if admitted_item_ids else current_stage
            if admitted_item_ids:
                connection.execute(
                    """
                    UPDATE writing_reference_preparation_batches
                    SET status='accepted', admission_stage_index=?,
                        deferred_item_count=?, updated_at=?
                    WHERE tenant_id=? AND project_id=? AND batch_id=?
                    """,
                    (
                        next_stage,
                        remaining,
                        now.isoformat(),
                        TENANT_ID,
                        project_id,
                        batch_id,
                    ),
                )
            self.repository._record_idempotency(
                connection,
                project_id,
                "advance_preparation_stage",
                request.idempotency_key,
                request_hash,
                batch_id,
            )
            self.repository._append_audit(
                connection,
                project_id,
                "preparation_stage_admitted",
                batch_id,
                request.actor,
                {
                    "batch_id": batch_id,
                    "admission_plan_id": current.admission_plan_id,
                    "from_stage_index": current_stage,
                    "to_stage_index": next_stage,
                    "stage_size": current.admission_stage_size,
                    "item_ids": admitted_item_ids,
                    "remaining_deferred_item_count": remaining,
                    "idempotency_key": request.idempotency_key,
                },
            )
            connection.commit()
        return self.get(project_id, batch_id)

    def _emit_progress(
        self,
        project_id: str,
        batch_id: str,
        progress_callback: PreparationProgressCallback | None,
    ) -> None:
        if progress_callback is not None:
            try:
                progress_callback(self.get(project_id, batch_id))
            except Exception:  # noqa: BLE001
                # Progress observers are non-authoritative. A rendering or
                # parent-projection failure must never strand durable document
                # work before the batch receives its terminal status.
                logger.exception(
                    "writing-reference preparation progress callback failed "
                    "for project=%s batch=%s",
                    project_id,
                    batch_id,
                )

    def _process_claimed_item(
        self,
        item: WritingReferencePreparationBatchItem,
        actor: str,
        *,
        progress_callback: PreparationProgressCallback | None = None,
    ) -> None:
        stage_name = "ingest"
        current_item = item

        def report(event: dict[str, Any]) -> None:
            nonlocal current_item
            event_context = {
                "item_id": current_item.item_id,
                "artifact_id": current_item.artifact_id,
                "nct_id": current_item.nct_id,
                "document_id": current_item.document_id,
                "document_label": current_item.filename or current_item.document_id,
                **dict(event.get("context") or {}),
            }
            current_item = self._record_progress(
                current_item,
                {**event, "context": event_context},
            )
            self._write_item(current_item)
            self._emit_progress(current_item.project_id, current_item.batch_id, progress_callback)

        try:
            if item.ingest.status != "succeeded":
                current_item = self._start_stage(current_item, "ingest")
                report(
                    {
                        "phase": "downloading",
                        "current_substep": "正在下载公开 Protocol（研究方案）",
                        "completed": 0,
                        "total": 1,
                        "unit": "file",
                    }
                )
                artifact = self._call_with_optional_progress(
                    self.document_service.ingest,
                    item.project_id,
                    WritingReferenceDocumentIngestRequest(
                        snapshot_id=item.snapshot_id,
                        nct_id=item.nct_id,
                        document_id=item.document_id,
                        actor=actor,
                        idempotency_key=f"prep:{item.batch_id}:{item.item_id}:ingest",
                    ),
                    progress_callback=report,
                )
                report(
                    {
                        "phase": "downloading",
                        "current_substep": "公开 Protocol（研究方案）下载完成",
                        "completed": 1,
                        "total": 1,
                        "unit": "file",
                    }
                )
                current_item = current_item.model_copy(
                    update={"artifact_id": artifact.artifact_id, "updated_at": self.clock()},
                    deep=True,
                )
                self._write_item(current_item)
                if not artifact.source_current:
                    raise WritingReferencePreparationItemError(
                        "source_artifact_invalidated",
                        "The existing public-document artifact has been invalidated and cannot be extracted.",
                    )
                current_item = self._finish_stage(
                    current_item,
                    "ingest",
                    "succeeded",
                    {"artifact_id": artifact.artifact_id},
                )
            stage_name = "extraction"
            if current_item.extraction.status != "succeeded":
                current_item = self._pin_ocr_model(current_item, actor)
                current_item = self._start_stage(current_item, "extraction")
                current_artifact = self.repository.document_artifact(
                    current_item.project_id,
                    current_item.artifact_id,
                )
                if not current_artifact.source_current:
                    raise WritingReferencePreparationItemError(
                        "source_artifact_invalidated",
                        "The public-document artifact was invalidated before extraction.",
                    )
                extraction = self._call_with_optional_progress(
                    self.extraction_service.extract,
                    current_item.project_id,
                    current_item.artifact_id,
                    actor=actor,
                    extraction_idempotency_key=f"prep:{current_item.batch_id}:{current_item.item_id}:extract",
                    ocr_model_override=current_item.ocr_model_pin,
                    progress_callback=report,
                )
                if (
                    self.ocr_consistency_service is not None
                    and extraction.ocr_consistency_qc.get("triggered")
                ):
                    report(
                        {
                            "phase": "extraction_persisting",
                            "current_substep": "正在复核不同 OCR 模型的衔接结果",
                            "completed": 0,
                            "total": 1,
                            "unit": "file",
                        }
                    )
                    self.ocr_consistency_service.recheck(
                        current_item.project_id,
                        current_item.artifact_id,
                        idempotency_key=(
                            f"prep:{current_item.batch_id}:{current_item.item_id}:"
                            "ocr-consistency-recheck"
                        ),
                    )
                    report(
                        {
                            "phase": "extraction_persisting",
                            "current_substep": "OCR 衔接复核完成",
                            "completed": 1,
                            "total": 1,
                            "unit": "file",
                        }
                    )
                current_item = self._finish_stage(
                    current_item,
                    "extraction",
                    "succeeded",
                    {"extraction_revision": extraction.extraction_revision},
                )
            stage_name = "validation"
            if current_item.validation.status not in {"succeeded", "review_required"}:
                current_item = self._start_stage(current_item, "validation")
                report(
                    {
                        "phase": "content_validating",
                        "current_substep": "正在校验文件内容与当前研究上下文",
                        "completed": 0,
                        "total": 1,
                        "unit": "file",
                    }
                )
                validation = self.repository.document_validation(
                    current_item.project_id,
                    current_item.artifact_id,
                )
                if validation.status in {"confirmed", "user_overridden"}:
                    validation_stage_status = "succeeded"
                elif validation.status in {"needs_review", "mismatch"}:
                    validation_stage_status = "review_required"
                else:
                    raise WritingReferencePreparationItemError(
                        "validation_status_unsupported",
                        f"Unsupported document validation status: {validation.status}",
                    )
                report(
                    {
                        "phase": "content_validating",
                        "current_substep": "文件内容校验已完成",
                        "completed": 1,
                        "total": 1,
                        "unit": "file",
                    }
                )
                current_item = self._finish_stage(
                    current_item,
                    "validation",
                    validation_stage_status,
                    {
                        "validation_id": validation.validation_id,
                        "validation_status": validation.status,
                    },
                )
            final_status = (
                "prepared"
                if current_item.validation.status == "succeeded"
                else "review_required"
            )
            self._complete_item(current_item, final_status, actor)
        except Exception as exc:
            self._fail_item(current_item, stage_name, exc, actor)

    @staticmethod
    def _call_with_optional_progress(
        method: Callable[..., Any],
        *args: Any,
        progress_callback: Callable[[dict[str, Any]], None],
        **kwargs: Any,
    ) -> Any:
        """Pass the new observer only to compatible services and test fakes."""

        parameters: tuple[inspect.Parameter, ...] = ()
        try:
            parameters = tuple(inspect.signature(method).parameters.values())
            supports_keyword = any(
                parameter.name == "progress_callback"
                or parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
        except (TypeError, ValueError):
            supports_keyword = False
        if supports_keyword:
            kwargs["progress_callback"] = progress_callback
        if (
            "ocr_model_override" in kwargs
            and not any(
                parameter.name == "ocr_model_override"
                or parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
        ):
            kwargs.pop("ocr_model_override")
        return method(*args, **kwargs)

    def _pin_ocr_model(
        self,
        item: WritingReferencePreparationBatchItem,
        actor: str,
    ) -> WritingReferencePreparationBatchItem:
        """Persist the per-document OCR model before any extraction call.

        A failed-only retry or service restart reuses this immutable pin
        instead of resolving the then-current OCR role.
        """
        if item.ocr_model_pin:
            return item
        resolver = getattr(self.extraction_service, "resolve_ocr_model", None)
        if callable(resolver):
            model = str(resolver() or "").strip()
        else:
            model_resolver = getattr(
                self.extraction_service,
                "ocr_model_resolver",
                None,
            )
            model = str(
                model_resolver()
                if callable(model_resolver)
                else getattr(self.extraction_service, "ocr_model", "")
            ).strip()
        if not model:
            # Deterministic extraction fakes and native-only services may not
            # configure OCR. They retain the legacy empty pin.
            return item
        now = self.clock()
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT payload_json FROM writing_reference_preparation_items
                WHERE tenant_id=? AND project_id=? AND batch_id=? AND item_id=?
                """,
                (TENANT_ID, item.project_id, item.batch_id, item.item_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(item.item_id)
            current = WritingReferencePreparationBatchItem.model_validate_json(
                row["payload_json"]
            )
            if current.ocr_model_pin:
                connection.commit()
                return current
            if current.status != "running" or current.attempt != item.attempt:
                connection.rollback()
                raise WritingReferencePreparationItemError(
                    "ocr_model_pin_stale_item",
                    "Preparation item changed before OCR model pin was committed.",
                )
            pinned = current.model_copy(
                update={
                    "ocr_model_pin": model,
                    "ocr_model_pin_source": "ocr_role_at_extraction_start",
                    "ocr_model_pinned_at": now,
                    "updated_at": now,
                },
                deep=True,
            )
            self._write_item_with(connection, pinned)
            self.repository._append_audit(
                connection,
                item.project_id,
                "preparation_item_ocr_model_pinned",
                item.item_id,
                actor,
                {
                    "batch_id": item.batch_id,
                    "attempt": item.attempt,
                    "ocr_model": model,
                    "pin_source": pinned.ocr_model_pin_source,
                    "pinned_at": now.isoformat(),
                },
            )
            connection.commit()
        return pinned

    @staticmethod
    def _record_progress(
        item: WritingReferencePreparationBatchItem,
        event: dict[str, Any],
    ) -> WritingReferencePreparationBatchItem:
        phase = str(event.get("phase") or item.progress.phase)
        if phase not in _PROGRESS_PHASE_RANGES:
            phase = item.progress.phase
        completed = max(0, int(event.get("completed") or 0))
        total = max(0, int(event.get("total") or 0))
        if total:
            completed = min(completed, total)
            ratio = completed / total
        else:
            ratio = 0.0
        phase_range = _PROGRESS_PHASE_RANGES.get(phase)
        percent = (
            round(phase_range[0] + (phase_range[1] - phase_range[0]) * ratio)
            if phase_range
            else item.progress.percent
        )
        if phase == "completed":
            percent = 100
        percent = max(item.progress.percent, min(100, percent))
        progress = WritingReferencePreparationProgress(
            phase=phase,
            current_substep=str(event.get("current_substep") or ""),
            completed=completed,
            total=total,
            percent=percent,
            unit=str(event.get("unit") or ""),
            context=dict(event.get("context") or {}),
        )
        updated = item.model_copy(
            update={"progress": progress, "updated_at": datetime.now(timezone.utc)},
            deep=True,
        )
        return updated

    def _claim_item(
        self,
        project_id: str,
        batch_id: str,
        item_id: str,
        allowed_statuses: set[str],
    ) -> WritingReferencePreparationBatchItem | None:
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT payload_json FROM writing_reference_preparation_items
                WHERE tenant_id=? AND project_id=? AND batch_id=? AND item_id=?
                """,
                (TENANT_ID, project_id, batch_id, item_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(item_id)
            item = WritingReferencePreparationBatchItem.model_validate_json(row["payload_json"])
            if item.status not in allowed_statuses or item.item_kind != "public_document":
                connection.commit()
                return None
            if (
                item.status == "failed"
                and item.error_code == "paddle_ocr_outcome_unknown"
            ):
                # The remote provider may still have accepted this page. A
                # generic failed-item worker must not submit the same page
                # again; recovery requires reconciliation of the original job.
                connection.commit()
                return None
            restarting_failed_item = item.status == "failed"
            item = item.model_copy(
                update={
                    "status": "running",
                    "attempt": item.attempt + 1,
                    "error_code": "",
                    "error_detail": "",
                    "progress": (
                        WritingReferencePreparationProgress(
                            phase="queued",
                            current_substep="正在开始本次重试",
                            completed=0,
                            total=1,
                            percent=0,
                            unit="file",
                        )
                        if restarting_failed_item
                        else item.progress
                    ),
                    "updated_at": self.clock(),
                },
                deep=True,
            )
            self._write_item_with(connection, item)
            connection.commit()
            return item

    def _start_stage(
        self,
        item: WritingReferencePreparationBatchItem,
        stage_name: str,
    ) -> WritingReferencePreparationBatchItem:
        stage = getattr(item, stage_name)
        now = self.clock()
        stage = stage.model_copy(
            update={
                "status": "running",
                "attempt": stage.attempt + 1,
                "error_code": "",
                "error_detail": "",
                "started_at": now,
                "completed_at": None,
            }
        )
        updated = item.model_copy(update={stage_name: stage, "updated_at": now}, deep=True)
        self._write_item(updated)
        return updated

    def _finish_stage(
        self,
        item: WritingReferencePreparationBatchItem,
        stage_name: str,
        status: str,
        associations: dict[str, str],
    ) -> WritingReferencePreparationBatchItem:
        now = self.clock()
        stage = getattr(item, stage_name).model_copy(
            update={"status": status, "completed_at": now}
        )
        updated = item.model_copy(
            update={stage_name: stage, "updated_at": now, **associations},
            deep=True,
        )
        self._write_item(updated)
        return updated

    def _complete_item(
        self,
        item: WritingReferencePreparationBatchItem,
        status: str,
        actor: str,
    ) -> None:
        item = self._record_progress(
            item,
            {
                "phase": "completed",
                "current_substep": (
                    "文件准备完成"
                    if status == "prepared"
                    else "文件已准备，等待人工内容确认"
                ),
                "completed": 1,
                "total": 1,
                "unit": "file",
            },
        )
        item = item.model_copy(
            update={"status": status, "error_code": "", "error_detail": "", "updated_at": self.clock()},
            deep=True,
        )
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._write_item_with(connection, item)
            self.repository._append_audit(
                connection,
                item.project_id,
                "preparation_item_completed",
                item.item_id,
                actor,
                {
                    "batch_id": item.batch_id,
                    "status": item.status,
                    "attempt": item.attempt,
                    "artifact_id": item.artifact_id,
                    "extraction_revision": item.extraction_revision,
                    "validation_id": item.validation_id,
                    "validation_status": item.validation_status,
                    "ocr_model_pin": item.ocr_model_pin,
                    "ocr_model_pin_source": item.ocr_model_pin_source,
                    "ocr_model_pinned_at": (
                        item.ocr_model_pinned_at.isoformat()
                        if item.ocr_model_pinned_at
                        else ""
                    ),
                },
            )
            connection.commit()

    def _fail_item(
        self,
        item: WritingReferencePreparationBatchItem,
        stage_name: str,
        error: Exception,
        actor: str,
    ) -> None:
        now = self.clock()
        error_code = self._error_code(stage_name, error)
        error_detail = str(error)[:1000] or error.__class__.__name__
        stage = getattr(item, stage_name).model_copy(
            update={
                "status": "failed",
                "error_code": error_code,
                "error_detail": error_detail,
                "completed_at": now,
            }
        )
        failed = item.model_copy(
            update={
                stage_name: stage,
                "status": "failed",
                "error_code": error_code,
                "error_detail": error_detail,
                "updated_at": now,
                "progress": item.progress.model_copy(
                    update={
                        "phase": "failed",
                        "current_substep": f"{stage_name}失败：{error_detail}",
                    }
                ),
            },
            deep=True,
        )
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._write_item_with(connection, failed)
            self.repository._append_audit(
                connection,
                item.project_id,
                "preparation_item_failed",
                item.item_id,
                actor,
                {
                    "batch_id": item.batch_id,
                    "stage": stage_name,
                    "attempt": item.attempt,
                    "error_code": error_code,
                    "ocr_model_pin": failed.ocr_model_pin,
                    "ocr_model_pin_source": failed.ocr_model_pin_source,
                    "ocr_model_pinned_at": (
                        failed.ocr_model_pinned_at.isoformat()
                        if failed.ocr_model_pinned_at
                        else ""
                    ),
                },
            )
            connection.commit()

    @staticmethod
    def _error_code(stage_name: str, error: Exception) -> str:
        if isinstance(error, WritingReferencePreparationItemError):
            return error.code
        if isinstance(error, PaddleOcrOutcomeUnknownError):
            return "paddle_ocr_outcome_unknown"
        message = str(error).casefold()
        if (
            "paddle ocr" in message
            and (
                "outcome is unknown" in message
                or "poll request failed" in message
                or "result download failed" in message
                or "timed out" in message
                or "returned an invalid result" in message
                or "returned empty result" in message
                or "completed with unusable text" in message
            )
        ):
            return "paddle_ocr_outcome_unknown"
        if "pdf validation failed" in message:
            return "public_document_content_invalid"
        if "no extractable text" in message:
            return "document_has_no_extractable_text"
        if "outside the clinicaltrials.gov allowlist" in message:
            return "public_document_redirect_not_allowed"
        if "exceeds size limit" in message:
            return "public_document_download_failed"
        if "download failure" in message or "download failed" in message:
            return "public_document_download_failed"
        if "retry loop ended unexpectedly" in message:
            return "public_document_download_failed"
        if "current source document is required for extraction" in message:
            return "source_artifact_invalidated"
        if "unavailable" in message:
            return "registered_artifact_unavailable"
        if isinstance(
            error,
            (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                ConnectionResetError,
            ),
        ):
            return "public_document_download_failed"
        if isinstance(error, KeyError):
            return f"{stage_name}_lineage_missing"
        return f"{stage_name}_failed"

    def _refresh_batch_status(self, project_id: str, batch_id: str) -> None:
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._refresh_batch_status_with(connection, project_id, batch_id)
            connection.commit()

    def _refresh_batch_status_with(self, connection: Any, project_id: str, batch_id: str) -> None:
        rows = connection.execute(
            """
            SELECT payload_json FROM writing_reference_preparation_items
            WHERE tenant_id=? AND project_id=? AND batch_id=?
            """,
            (TENANT_ID, project_id, batch_id),
        ).fetchall()
        items = [
            WritingReferencePreparationBatchItem.model_validate_json(row["payload_json"])
            for row in rows
        ]
        statuses = {item.status for item in items}
        counts = self._counts(items)
        if "running" in statuses:
            status = "running"
        elif "pending" in statuses:
            status = "accepted"
        elif counts["failed_count"]:
            terminal_nonfailures = (
                counts["prepared_count"]
                + counts["review_required_count"]
                + counts["manual_upload_required_count"]
                + counts["excluded_count"]
            )
            status = "partial_failure" if terminal_nonfailures else "failed"
        elif counts["deferred_item_count"]:
            status = "awaiting_stage_admission"
        elif counts["manual_upload_required_count"]:
            status = "completed_with_manual_upload_required"
        elif counts["review_required_count"]:
            status = "completed_with_review_required"
        else:
            status = "completed"
        connection.execute(
            """
            UPDATE writing_reference_preparation_batches
            SET status=?, deferred_item_count=?, updated_at=?
            WHERE tenant_id=? AND project_id=? AND batch_id=?
            """,
            (
                status,
                counts["deferred_item_count"],
                self.clock().isoformat(),
                TENANT_ID,
                project_id,
                batch_id,
            ),
        )

    @staticmethod
    def _counts(items: list[WritingReferencePreparationBatchItem]) -> dict[str, Any]:
        public_documents = [
            item for item in items if item.item_kind == "public_document"
        ]
        progress, current = WritingReferencePreparationBatchService._progress_projection(
            public_documents
        )
        return {
            "item_count": len(items),
            "document_item_count": len(public_documents),
            "pending_document_count": sum(
                item.status == "pending" for item in public_documents
            ),
            "running_document_count": sum(
                item.status == "running" for item in public_documents
            ),
            "completed_document_count": sum(
                item.status in {"prepared", "review_required", "failed", "excluded"}
                for item in public_documents
            ),
            "prepared_count": sum(item.status == "prepared" for item in items),
            "review_required_count": sum(item.status == "review_required" for item in items),
            "manual_upload_required_count": sum(
                item.status == "manual_upload_required" for item in items
            ),
            "failed_count": sum(item.status == "failed" for item in items),
            "excluded_count": sum(item.status == "excluded" for item in items),
            "deferred_item_count": sum(item.status == "deferred" for item in items),
            "current_item_id": current.item_id if current else "",
            "current_nct_id": current.nct_id if current else "",
            "current_document_label": (
                current.filename or current.document_id if current else ""
            ),
            "progress": progress,
        }

    @staticmethod
    def _progress_projection(
        public_documents: list[WritingReferencePreparationBatchItem],
    ) -> tuple[WritingReferencePreparationProgress, WritingReferencePreparationBatchItem | None]:
        running_items = [
            item for item in public_documents if item.status == "running"
        ]
        current = (
            max(running_items, key=lambda item: item.updated_at)
            if running_items
            else None
        ) or next(
            (item for item in public_documents if item.status == "pending"),
            None,
        ) or next(
            (item for item in public_documents if item.status == "failed"),
            None,
        )
        total_files = len(public_documents)
        finished_before_current = sum(
            item.status in {"prepared", "review_required", "failed", "excluded"}
            for item in public_documents
        )
        if current is None:
            deferred_count = sum(
                item.status == "deferred" for item in public_documents
            )
            if deferred_count:
                finished = total_files - deferred_count
                return (
                    WritingReferencePreparationProgress(
                        phase="queued",
                        current_substep=(
                            f"本阶段已完成，等待下一阶段准入（剩余 {deferred_count} 份）"
                        ),
                        completed=finished,
                        total=total_files,
                        percent=round((finished / total_files) * 100)
                        if total_files
                        else 0,
                        unit="file",
                    ),
                    None,
                )
            return (
                WritingReferencePreparationProgress(
                    phase="completed" if total_files else "queued",
                    current_substep="全部文件准备完成" if total_files else "等待公开文件",
                    completed=total_files,
                    total=total_files,
                    percent=100 if total_files else 0,
                    unit="file",
                ),
                None,
            )
        if current.status in {"prepared", "review_required", "failed", "excluded"}:
            finished_before_current -= 1
        percent = round(
            ((finished_before_current + current.progress.percent / 100) / total_files) * 100
        ) if total_files else 0
        return (
            current.progress.model_copy(
                update={"percent": max(0, min(100, percent))}
            ),
            current,
        )

    def _set_batch_status(self, project_id: str, batch_id: str, status: str) -> None:
        with self.repository._connect() as connection:
            connection.execute(
                """
                UPDATE writing_reference_preparation_batches SET status=?, updated_at=?
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                """,
                (status, self.clock().isoformat(), TENANT_ID, project_id, batch_id),
            )

    def _write_item(self, item: WritingReferencePreparationBatchItem) -> None:
        with self.repository._connect() as connection:
            self._write_item_with(connection, item)

    @staticmethod
    def _write_item_with(connection: Any, item: WritingReferencePreparationBatchItem) -> None:
        connection.execute(
            """
            UPDATE writing_reference_preparation_items
            SET status=?, attempt=?, payload_json=?, updated_at=?
            WHERE tenant_id=? AND project_id=? AND batch_id=? AND item_id=?
            """,
            (
                item.status,
                item.attempt,
                _canonical_json(item.model_dump(mode="json")),
                item.updated_at.isoformat(),
                TENANT_ID,
                item.project_id,
                item.batch_id,
                item.item_id,
            ),
        )

    @staticmethod
    def _insert_item_with(connection: Any, item: WritingReferencePreparationBatchItem) -> None:
        connection.execute(
            """
            INSERT INTO writing_reference_preparation_items(
                tenant_id, project_id, batch_id, item_id, item_kind, nct_id,
                document_id, document_type, source_scope_sha256, status, attempt,
                payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_ID,
                item.project_id,
                item.batch_id,
                item.item_id,
                item.item_kind,
                item.nct_id,
                item.document_id,
                item.document_type,
                item.source_scope_sha256,
                item.status,
                item.attempt,
                _canonical_json(item.model_dump(mode="json")),
                item.created_at.isoformat(),
                item.updated_at.isoformat(),
            ),
        )

    def _idempotent_batch(
        self,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> str | None:
        with self.repository._connect() as connection:
            return self.repository._idempotent_result(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_hash,
            )

    def _recover_interrupted_items(self) -> None:
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            legacy_sap_rows = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_preparation_items
                WHERE tenant_id=?
                  AND item_kind='public_document'
                  AND LOWER(TRIM(document_type))='sap'
                  AND status IN ('pending', 'running', 'failed')
                """,
                (TENANT_ID,),
            ).fetchall()
            affected: set[tuple[str, str]] = set()
            for row in legacy_sap_rows:
                item = WritingReferencePreparationBatchItem.model_validate_json(
                    row["payload_json"]
                )
                now = self.clock()
                terminal_stages = {}
                for stage_name in ("ingest", "extraction", "validation"):
                    stage = getattr(item, stage_name)
                    terminal_stages[stage_name] = (
                        stage
                        if stage.status in {"succeeded", "review_required"}
                        else stage.model_copy(
                            update={
                                "status": "not_applicable",
                                "error_code": "",
                                "error_detail": "",
                                "completed_at": now,
                            }
                        )
                    )
                item = item.model_copy(
                    update={
                        **terminal_stages,
                        "status": "excluded",
                        "error_code": "standalone_sap_out_of_scope",
                        "error_detail": (
                            "Standalone SAP is outside the Protocol-only "
                            "competitor corpus scope and was not processed."
                        ),
                        "progress": WritingReferencePreparationProgress(
                            phase="completed",
                            current_substep="独立 SAP 已按 Protocol-only 范围排除",
                            completed=1,
                            total=1,
                            percent=100,
                            unit="file",
                        ),
                        "updated_at": now,
                    },
                    deep=True,
                )
                self._write_item_with(connection, item)
                self.repository._append_audit(
                    connection,
                    item.project_id,
                    "preparation_item_excluded_after_scope_migration",
                    item.item_id,
                    "system_recovery",
                    {
                        "batch_id": item.batch_id,
                        "document_type": item.document_type,
                        "reason": "standalone_sap_out_of_scope",
                    },
                )
                affected.add((item.project_id, item.batch_id))
            rows = connection.execute(
                """
                SELECT item.payload_json
                FROM writing_reference_preparation_items AS item
                JOIN writing_reference_preparation_batches AS batch
                  ON batch.tenant_id=item.tenant_id
                 AND batch.project_id=item.project_id
                 AND batch.batch_id=item.batch_id
                WHERE item.tenant_id=?
                  AND batch.status IN ('accepted', 'running')
                  AND item.item_kind='public_document'
                  AND item.status IN ('pending', 'running')
                """,
                (TENANT_ID,),
            ).fetchall()
            active_batch_rows = connection.execute(
                """
                SELECT project_id, batch_id
                FROM writing_reference_preparation_batches
                WHERE tenant_id=? AND status IN ('accepted', 'running')
                """,
                (TENANT_ID,),
            ).fetchall()
            affected.update({
                (str(row["project_id"]), str(row["batch_id"]))
                for row in active_batch_rows
            })
            for row in rows:
                item = WritingReferencePreparationBatchItem.model_validate_json(row["payload_json"])
                stage_name = next(
                    (
                        name
                        for name in ("ingest", "extraction", "validation")
                        if getattr(item, name).status == "running"
                    ),
                    next(
                        (
                            name
                            for name in ("ingest", "extraction", "validation")
                            if getattr(item, name).status not in TERMINAL_STAGE_STATUSES
                        ),
                        "validation",
                    ),
                )
                now = self.clock()
                paddle_extraction_may_have_been_accepted = (
                    stage_name == "extraction"
                    and item.ocr_model_pin == PADDLE_OCR_MODEL
                    and getattr(item, stage_name).status == "running"
                )
                recovery_error_code = (
                    "paddle_ocr_outcome_unknown"
                    if paddle_extraction_may_have_been_accepted
                    else "service_restart_interrupted"
                )
                recovery_error_detail = (
                    "Paddle OCR extraction was interrupted after the document "
                    "route was pinned; remote acceptance is unknown and generic "
                    "retry is disabled pending job reconciliation."
                    if paddle_extraction_may_have_been_accepted
                    else "Preparation was interrupted before completion and is "
                    "eligible for failed-only retry."
                )
                stage = getattr(item, stage_name).model_copy(
                    update={
                        "status": "failed",
                        "error_code": recovery_error_code,
                        "error_detail": recovery_error_detail,
                        "completed_at": now,
                    }
                )
                item = item.model_copy(
                    update={
                        stage_name: stage,
                        "status": "failed",
                        "error_code": recovery_error_code,
                        "error_detail": stage.error_detail,
                        "updated_at": now,
                    },
                    deep=True,
                )
                self._write_item_with(connection, item)
                self.repository._append_audit(
                    connection,
                    item.project_id,
                    "preparation_item_recovered_after_restart",
                    item.item_id,
                    "system_recovery",
                    {
                        "batch_id": item.batch_id,
                        "stage": stage_name,
                        "error_code": recovery_error_code,
                        "ocr_model_pin": item.ocr_model_pin,
                    },
                )
                affected.add((item.project_id, item.batch_id))
            for project_id, batch_id in affected:
                self._refresh_batch_status_with(connection, project_id, batch_id)
            connection.commit()
