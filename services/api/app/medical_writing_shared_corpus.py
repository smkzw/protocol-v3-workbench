from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.contracts.workbench_contracts import (
    MedicalWritingSharedCorpusAdmissionRequest,
    MedicalWritingSharedCorpusCandidate,
    MedicalWritingSharedCorpusCatalog,
    MedicalWritingSharedCorpusReviewRequest,
)


ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets/medical_writing_corpus"
PHASE1_ASSET_PATH = ASSET_ROOT / "phase1_autoimmune_mnc_candidates_v1.json"
PHASE1_MANIFEST_PATH = ASSET_ROOT / "phase1_autoimmune_mnc_candidates_v1.manifest.json"
TENANT_ID = "kangzhe_local"


class MedicalWritingSharedCorpusConflictError(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _phase1_project(value: str) -> bool:
    normalized = str(value or "").strip().upper().replace(" ", "")
    normalized = normalized.replace("Ⅰ", "I").replace("一期", "I期")
    return normalized in {
        "1",
        "I",
        "1期",
        "I期",
        "PHASE1",
        "PHASEI",
        "PHASE1期",
        "PHASEI期",
        "1A",
        "1B",
        "IA",
        "IB",
        "I期/II期",
        "I/II期",
    } or normalized.startswith(("PHASE1/", "PHASEI/", "I期/"))


def _features(value: str) -> set[str]:
    normalized = str(value or "").casefold()
    latin = set(re.findall(r"[a-z0-9][a-z0-9._/-]{1,}", normalized))
    cjk = re.findall(r"[\u4e00-\u9fff]+", normalized)
    return latin | {
        sequence[index : index + size]
        for sequence in cjk
        for size in (2, 3)
        for index in range(max(0, len(sequence) - size + 1))
    }


class MedicalWritingSharedCorpusService:
    """Tenant-level reviewed references that stay separate from project facts."""

    def __init__(
        self,
        db_path: Path,
        *,
        asset_path: Path = PHASE1_ASSET_PATH,
        manifest_path: Path = PHASE1_MANIFEST_PATH,
    ) -> None:
        self.db_path = Path(db_path)
        self.asset_path = Path(asset_path)
        self.manifest_path = Path(manifest_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._asset, self._items = self._load_asset()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _load_asset(self) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        observed_asset_sha256 = _file_sha256(self.asset_path)
        if observed_asset_sha256 != manifest.get("asset_sha256"):
            raise ValueError("shared medical-writing corpus asset hash does not match its manifest")
        asset = json.loads(self.asset_path.read_text(encoding="utf-8"))
        if asset.get("item_count") != len(asset.get("items") or []):
            raise ValueError("shared medical-writing corpus item count is inconsistent")
        if asset.get("item_count") != manifest.get("item_count"):
            raise ValueError("shared medical-writing corpus manifest count is inconsistent")
        items: dict[str, dict[str, Any]] = {}
        for raw in asset["items"]:
            candidate = dict(raw)
            candidate_sha256 = candidate.pop("candidate_sha256", "")
            if candidate_sha256 != _payload_hash(candidate):
                raise ValueError(f"shared corpus candidate hash mismatch: {raw.get('segment_id')}")
            if hashlib.sha256(raw["source_text"].encode("utf-8")).hexdigest() != raw["source_text_sha256"]:
                raise ValueError(f"shared corpus source text hash mismatch: {raw.get('segment_id')}")
            if hashlib.sha256(raw["translated_text"].encode("utf-8")).hexdigest() != raw["translated_text_sha256"]:
                raise ValueError(f"shared corpus translation hash mismatch: {raw.get('segment_id')}")
            segment_id = str(raw["segment_id"])
            if segment_id in items:
                raise ValueError(f"duplicate shared corpus segment: {segment_id}")
            items[segment_id] = raw
        return {**asset, "asset_sha256": observed_asset_sha256}, items

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS medical_writing_shared_corpus_schema (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS medical_writing_shared_corpus_review_records (
                    tenant_id TEXT NOT NULL,
                    segment_id TEXT NOT NULL,
                    candidate_sha256 TEXT NOT NULL,
                    review_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    decision TEXT NOT NULL CHECK (decision IN ('approved', 'returned', 'rejected')),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, review_id),
                    UNIQUE (tenant_id, segment_id, candidate_sha256, revision)
                );
                CREATE TABLE IF NOT EXISTS medical_writing_shared_corpus_review_state (
                    tenant_id TEXT NOT NULL,
                    segment_id TEXT NOT NULL,
                    candidate_sha256 TEXT NOT NULL,
                    review_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    decision TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, segment_id),
                    FOREIGN KEY (tenant_id, review_id)
                    REFERENCES medical_writing_shared_corpus_review_records(tenant_id, review_id)
                );
                CREATE TABLE IF NOT EXISTS medical_writing_shared_corpus_admission_records (
                    tenant_id TEXT NOT NULL,
                    segment_id TEXT NOT NULL,
                    candidate_sha256 TEXT NOT NULL,
                    admission_id TEXT NOT NULL,
                    medical_review_id TEXT NOT NULL,
                    review_revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, admission_id),
                    UNIQUE (tenant_id, segment_id, candidate_sha256, medical_review_id)
                );
                CREATE TABLE IF NOT EXISTS medical_writing_shared_corpus_admission_state (
                    tenant_id TEXT NOT NULL,
                    segment_id TEXT NOT NULL,
                    candidate_sha256 TEXT NOT NULL,
                    admission_id TEXT NOT NULL,
                    medical_review_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('admitted', 'invalidated')),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, segment_id),
                    FOREIGN KEY (tenant_id, admission_id)
                    REFERENCES medical_writing_shared_corpus_admission_records(tenant_id, admission_id)
                );
                CREATE TABLE IF NOT EXISTS medical_writing_shared_corpus_idempotency (
                    tenant_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, operation, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS medical_writing_shared_corpus_audit_chain (
                    tenant_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, sequence_no),
                    UNIQUE (tenant_id, event_id)
                );
                CREATE TRIGGER IF NOT EXISTS trg_shared_corpus_review_record_no_update
                BEFORE UPDATE ON medical_writing_shared_corpus_review_records BEGIN
                    SELECT RAISE(ABORT, 'shared corpus review records are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_shared_corpus_admission_record_no_update
                BEFORE UPDATE ON medical_writing_shared_corpus_admission_records BEGIN
                    SELECT RAISE(ABORT, 'shared corpus admission records are immutable');
                END;
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO medical_writing_shared_corpus_schema(version, applied_at) VALUES (1, ?)",
                (_utc_now().isoformat(),),
            )

    def catalog(
        self,
        *,
        query: str = "",
        status: str = "all",
        modality: str = "all",
    ) -> MedicalWritingSharedCorpusCatalog:
        items = [self._project_item(item) for item in self._items.values()]
        if query.strip():
            query_features = _features(query)
            items = [
                item
                for item in items
                if query_features
                & _features(
                    " ".join(
                        [
                            item.nct_id,
                            item.sponsor,
                            *item.conditions,
                            item.modality,
                            item.compound,
                            item.corpus_function,
                            item.applicability,
                            item.translated_text,
                        ]
                    )
                )
            ]
        if status != "all":
            items = [
                item
                for item in items
                if item.medical_review_status == status or item.admission_status == status
            ]
        if modality != "all":
            items = [item for item in items if item.modality == modality]
        items.sort(key=lambda item: (item.medical_review_status != "not_reviewed", item.nct_id, item.segment_id))
        all_items = [self._project_item(item) for item in self._items.values()]
        return MedicalWritingSharedCorpusCatalog(
            layer_id=self._asset["layer_id"],
            asset_version=self._asset["asset_version"],
            asset_sha256=self._asset["asset_sha256"],
            item_count=len(all_items),
            pending_review_count=sum(item.medical_review_status == "not_reviewed" for item in all_items),
            approved_count=sum(item.medical_review_status == "approved" for item in all_items),
            admitted_count=sum(item.admission_status == "admitted" for item in all_items),
            items=items,
        )

    def review(
        self,
        segment_id: str,
        request: MedicalWritingSharedCorpusReviewRequest,
    ) -> MedicalWritingSharedCorpusCandidate:
        raw = self._candidate(segment_id)
        candidate_sha256 = raw["candidate_sha256"]
        semantic = {
            "segment_id": segment_id,
            "candidate_sha256": candidate_sha256,
            **request.model_dump(mode="json"),
        }
        request_hash = _payload_hash(semantic)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(
                connection, "medical_review", request.idempotency_key, request_hash
            )
            if replay:
                connection.rollback()
                return self._project_item(raw)
            state = connection.execute(
                "SELECT * FROM medical_writing_shared_corpus_review_state WHERE tenant_id=? AND segment_id=?",
                (TENANT_ID, segment_id),
            ).fetchone()
            actual_revision = (
                int(state["revision"])
                if state is not None and state["candidate_sha256"] == candidate_sha256
                else 0
            )
            if request.expected_revision != actual_revision:
                connection.rollback()
                raise MedicalWritingSharedCorpusConflictError(
                    f"stale shared corpus review revision: expected={request.expected_revision}, actual={actual_revision}"
                )
            revision = actual_revision + 1
            now = _utc_now()
            review_id = "shared_review_" + _payload_hash({**semantic, "revision": revision})[:24]
            payload = {
                "review_id": review_id,
                "segment_id": segment_id,
                "candidate_sha256": candidate_sha256,
                "revision": revision,
                "decision": request.decision,
                "comment": request.comment,
                "actor": request.actor,
                "created_at": now.isoformat(),
            }
            connection.execute(
                "INSERT INTO medical_writing_shared_corpus_review_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    TENANT_ID,
                    segment_id,
                    candidate_sha256,
                    review_id,
                    revision,
                    request.decision,
                    _canonical_json(payload),
                    now.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO medical_writing_shared_corpus_review_state
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, segment_id) DO UPDATE SET
                    candidate_sha256=excluded.candidate_sha256,
                    review_id=excluded.review_id,
                    revision=excluded.revision,
                    decision=excluded.decision,
                    updated_at=excluded.updated_at
                """,
                (
                    TENANT_ID,
                    segment_id,
                    candidate_sha256,
                    review_id,
                    revision,
                    request.decision,
                    now.isoformat(),
                ),
            )
            invalidated = 0
            if request.decision != "approved":
                invalidated = connection.execute(
                    """
                    UPDATE medical_writing_shared_corpus_admission_state
                    SET status='invalidated', updated_at=?
                    WHERE tenant_id=? AND segment_id=? AND candidate_sha256=? AND status='admitted'
                    """,
                    (now.isoformat(), TENANT_ID, segment_id, candidate_sha256),
                ).rowcount
            self._record_idempotency(
                connection,
                "medical_review",
                request.idempotency_key,
                request_hash,
                review_id,
            )
            self._append_audit(
                connection,
                event_type="shared_corpus_translation_medically_reviewed",
                target_id=segment_id,
                actor=request.actor,
                detail={
                    "review_id": review_id,
                    "revision": revision,
                    "decision": request.decision,
                    "candidate_sha256": candidate_sha256,
                    "invalidated_admission_count": invalidated,
                },
            )
            connection.commit()
        return self._project_item(raw)

    def admit(
        self,
        segment_id: str,
        request: MedicalWritingSharedCorpusAdmissionRequest,
    ) -> MedicalWritingSharedCorpusCandidate:
        raw = self._candidate(segment_id)
        candidate_sha256 = raw["candidate_sha256"]
        semantic = {
            "segment_id": segment_id,
            "candidate_sha256": candidate_sha256,
            **request.model_dump(mode="json"),
        }
        request_hash = _payload_hash(semantic)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(
                connection, "admission", request.idempotency_key, request_hash
            )
            if replay:
                connection.rollback()
                return self._project_item(raw)
            review = connection.execute(
                """
                SELECT * FROM medical_writing_shared_corpus_review_state
                WHERE tenant_id=? AND segment_id=?
                """,
                (TENANT_ID, segment_id),
            ).fetchone()
            if (
                review is None
                or review["candidate_sha256"] != candidate_sha256
                or review["decision"] != "approved"
                or review["review_id"] != request.medical_review_id
                or int(review["revision"]) != request.expected_review_revision
            ):
                connection.rollback()
                raise MedicalWritingSharedCorpusConflictError(
                    "current approved medical review is required for shared corpus admission"
                )
            now = _utc_now()
            admission_id = "shared_admission_" + _payload_hash(semantic)[:24]
            existing = connection.execute(
                """
                SELECT admission_id, medical_review_id, status
                FROM medical_writing_shared_corpus_admission_state
                WHERE tenant_id=? AND segment_id=? AND candidate_sha256=?
                """,
                (TENANT_ID, segment_id, candidate_sha256),
            ).fetchone()
            if existing and existing["status"] == "admitted":
                if existing["medical_review_id"] != request.medical_review_id:
                    connection.rollback()
                    raise MedicalWritingSharedCorpusConflictError(
                        "shared corpus candidate is already admitted under another review"
                    )
                admission_id = str(existing["admission_id"])
            else:
                payload = {
                    "admission_id": admission_id,
                    "segment_id": segment_id,
                    "candidate_sha256": candidate_sha256,
                    "medical_review_id": request.medical_review_id,
                    "review_revision": request.expected_review_revision,
                    "actor": request.actor,
                    "created_at": now.isoformat(),
                }
                connection.execute(
                    "INSERT INTO medical_writing_shared_corpus_admission_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        TENANT_ID,
                        segment_id,
                        candidate_sha256,
                        admission_id,
                        request.medical_review_id,
                        request.expected_review_revision,
                        _canonical_json(payload),
                        now.isoformat(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO medical_writing_shared_corpus_admission_state
                    VALUES (?, ?, ?, ?, ?, 'admitted', ?)
                    ON CONFLICT(tenant_id, segment_id) DO UPDATE SET
                        candidate_sha256=excluded.candidate_sha256,
                        admission_id=excluded.admission_id,
                        medical_review_id=excluded.medical_review_id,
                        status='admitted',
                        updated_at=excluded.updated_at
                    """,
                    (
                        TENANT_ID,
                        segment_id,
                        candidate_sha256,
                        admission_id,
                        request.medical_review_id,
                        now.isoformat(),
                    ),
                )
                self._append_audit(
                    connection,
                    event_type="shared_corpus_translation_admitted",
                    target_id=segment_id,
                    actor=request.actor,
                    detail={
                        "admission_id": admission_id,
                        "medical_review_id": request.medical_review_id,
                        "review_revision": request.expected_review_revision,
                        "candidate_sha256": candidate_sha256,
                    },
                )
            self._record_idempotency(
                connection,
                "admission",
                request.idempotency_key,
                request_hash,
                admission_id,
            )
            connection.commit()
        return self._project_item(raw)

    def search(
        self,
        query: str,
        *,
        project_phase: str,
        project_indication: str = "",
        section_heading: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not _phase1_project(project_phase):
            return []
        if limit < 1 or limit > 20:
            raise ValueError("shared phase-I corpus search limit must be between 1 and 20")
        query_features = _features(f"{query} {section_heading}")
        if not query_features:
            return []
        indication_features = _features(project_indication)
        scored: list[tuple[float, MedicalWritingSharedCorpusCandidate]] = []
        for raw in self._items.values():
            candidate = self._project_item(raw)
            if candidate.admission_status != "admitted" or candidate.medical_review_status != "approved":
                continue
            candidate_features = _features(
                " ".join(
                    [
                        candidate.translated_text,
                        candidate.corpus_function,
                        candidate.applicability,
                        *candidate.conditions,
                        candidate.modality,
                    ]
                )
            )
            overlap = len(query_features & candidate_features)
            if not overlap:
                continue
            condition_features = _features(" ".join(candidate.conditions))
            indication_match = len(indication_features & condition_features)
            score = overlap / max(1, len(query_features)) + min(0.35, indication_match * 0.05)
            scored.append((score, candidate))
        scored.sort(key=lambda item: (-item[0], item[1].nct_id, item[1].segment_id))
        return [
            {
                **candidate.model_dump(mode="json"),
                "selection": {
                    "score": round(score, 6),
                    "project_phase_gate": "phase1_matched",
                    "reuse_policy": "structure_and_language_reference_only",
                    "project_fact_policy": "never_import_from_shared_corpus",
                },
            }
            for score, candidate in scored[:limit]
        ]

    def health_report(self) -> dict[str, Any]:
        with self._connect() as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        audit_errors = self.verify_audit_chain()
        return {
            "status": "ok" if integrity == "ok" and not foreign_keys and not audit_errors else "error",
            "integrity_check": integrity,
            "foreign_key_violations": len(foreign_keys),
            "audit_chain_violations": len(audit_errors),
            "asset_sha256": self._asset["asset_sha256"],
            "item_count": len(self._items),
        }

    def verify_audit_chain(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM medical_writing_shared_corpus_audit_chain WHERE tenant_id=? ORDER BY sequence_no",
                (TENANT_ID,),
            ).fetchall()
        errors: list[str] = []
        previous_hash = ""
        for expected_sequence, row in enumerate(rows, start=1):
            if int(row["sequence_no"]) != expected_sequence:
                errors.append(f"sequence:{row['sequence_no']}")
            if row["previous_hash"] != previous_hash:
                errors.append(f"previous_hash:{row['sequence_no']}")
            event = {
                "tenant_id": TENANT_ID,
                "sequence_no": int(row["sequence_no"]),
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "target_id": row["target_id"],
                "actor": row["actor"],
                "detail_json": row["detail_json"],
                "previous_hash": row["previous_hash"],
                "created_at": row["created_at"],
            }
            observed = _payload_hash(event)
            if observed != row["event_hash"]:
                errors.append(f"event_hash:{row['sequence_no']}")
            previous_hash = str(row["event_hash"])
        return errors

    def _candidate(self, segment_id: str) -> dict[str, Any]:
        try:
            return self._items[segment_id]
        except KeyError as exc:
            raise KeyError(f"shared corpus segment not found: {segment_id}") from exc

    def _project_item(self, raw: dict[str, Any]) -> MedicalWritingSharedCorpusCandidate:
        segment_id = str(raw["segment_id"])
        candidate_sha256 = str(raw["candidate_sha256"])
        review: sqlite3.Row | None
        admission: sqlite3.Row | None
        with self._connect() as connection:
            review = connection.execute(
                """
                SELECT state.*, record.payload_json
                FROM medical_writing_shared_corpus_review_state AS state
                JOIN medical_writing_shared_corpus_review_records AS record
                  ON record.tenant_id=state.tenant_id AND record.review_id=state.review_id
                WHERE state.tenant_id=? AND state.segment_id=?
                """,
                (TENANT_ID, segment_id),
            ).fetchone()
            admission = connection.execute(
                """
                SELECT state.*, record.created_at AS admitted_at
                FROM medical_writing_shared_corpus_admission_state AS state
                JOIN medical_writing_shared_corpus_admission_records AS record
                  ON record.tenant_id=state.tenant_id AND record.admission_id=state.admission_id
                WHERE state.tenant_id=? AND state.segment_id=?
                """,
                (TENANT_ID, segment_id),
            ).fetchone()
        review_current = review is not None and review["candidate_sha256"] == candidate_sha256
        admission_current = (
            admission is not None
            and admission["candidate_sha256"] == candidate_sha256
            and admission["status"] == "admitted"
            and review_current
            and review["decision"] == "approved"
            and admission["medical_review_id"] == review["review_id"]
        )
        review_payload = json.loads(review["payload_json"]) if review_current else {}
        return MedicalWritingSharedCorpusCandidate(
            **raw,
            layer_id=self._asset["layer_id"],
            asset_version=self._asset["asset_version"],
            asset_sha256=self._asset["asset_sha256"],
            medical_review_status=review["decision"] if review_current else "not_reviewed",
            medical_review_revision=int(review["revision"]) if review_current else 0,
            medical_review_id=str(review["review_id"]) if review_current else "",
            medical_review_comment=str(review_payload.get("comment") or ""),
            medical_review_actor=str(review_payload.get("actor") or ""),
            medical_reviewed_at=review_payload.get("created_at"),
            admission_status=(
                "admitted"
                if admission_current
                else "invalidated"
                if admission is not None and admission["candidate_sha256"] == candidate_sha256
                else "not_admitted"
            ),
            admission_id=str(admission["admission_id"]) if admission_current else "",
            admitted_at=str(admission["admitted_at"]) if admission_current else None,
        )

    def _idempotent_result(
        self,
        connection: sqlite3.Connection,
        operation: str,
        key: str,
        request_hash: str,
    ) -> str | None:
        row = connection.execute(
            """
            SELECT request_hash, result_id
            FROM medical_writing_shared_corpus_idempotency
            WHERE tenant_id=? AND operation=? AND idempotency_key=?
            """,
            (TENANT_ID, operation, key),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise MedicalWritingSharedCorpusConflictError(
                "shared corpus idempotency key was reused with another request"
            )
        return str(row["result_id"])

    def _record_idempotency(
        self,
        connection: sqlite3.Connection,
        operation: str,
        key: str,
        request_hash: str,
        result_id: str,
    ) -> None:
        connection.execute(
            "INSERT INTO medical_writing_shared_corpus_idempotency VALUES (?, ?, ?, ?, ?, ?)",
            (TENANT_ID, operation, key, request_hash, result_id, _utc_now().isoformat()),
        )

    def _append_audit(
        self,
        connection: sqlite3.Connection,
        *,
        event_type: str,
        target_id: str,
        actor: str,
        detail: dict[str, Any],
    ) -> None:
        previous = connection.execute(
            """
            SELECT sequence_no, event_hash
            FROM medical_writing_shared_corpus_audit_chain
            WHERE tenant_id=? ORDER BY sequence_no DESC LIMIT 1
            """,
            (TENANT_ID,),
        ).fetchone()
        sequence_no = int(previous["sequence_no"]) + 1 if previous else 1
        previous_hash = str(previous["event_hash"]) if previous else ""
        created_at = _utc_now().isoformat()
        detail_json = _canonical_json(detail)
        event_id = f"shared_audit_{sequence_no:08d}_{_payload_hash([event_type, target_id, created_at])[:12]}"
        event = {
            "tenant_id": TENANT_ID,
            "sequence_no": sequence_no,
            "event_id": event_id,
            "event_type": event_type,
            "target_id": target_id,
            "actor": actor,
            "detail_json": detail_json,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
        connection.execute(
            "INSERT INTO medical_writing_shared_corpus_audit_chain VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                TENANT_ID,
                sequence_no,
                event_id,
                event_type,
                target_id,
                actor,
                detail_json,
                previous_hash,
                _payload_hash(event),
                created_at,
            ),
        )
