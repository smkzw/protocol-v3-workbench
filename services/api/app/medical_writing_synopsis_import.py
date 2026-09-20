from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    AiTaskRequest,
    AiTaskSourceRef,
    MedicalWritingInstrumentRightsState,
    MedicalWritingInstrumentSourceBinding,
    MedicalWritingInstrumentTranslationState,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyFraming,
    MedicalWritingSynopsisEvidenceSpan,
    MedicalWritingSynopsisImport,
    MedicalWritingSynopsisSource,
    SynopsisImportJobCancelResponse,
    SynopsisImportJobProgress,
    SynopsisImportJobStartResponse,
    SynopsisImportJobStatusResponse,
    WritingReferenceDocumentArtifact,
)

from .writing_reference import extract_pdf_sections
from .writing_reference_docx import extract_docx_sections

MAX_SYNOPSIS_BYTES = 30 * 1024 * 1024
MAX_AI_SOURCE_CHUNKS = 40
MAX_AI_SOURCE_CHARS = 6_000
MAX_SYNOPSIS_CHUNK_CHARS = 30_000
MAX_SYNOPSIS_JOB_ATTEMPTS = 3
ROUTE_SNAPSHOT_FIELDS = (
    "schema_version",
    "role_id",
    "profile_id",
    "profile_revision",
    "provider",
    "model",
    "base_url",
    "transport",
    "expected_response_model",
    "deployment_profile",
)


def _normalize_route_snapshot(candidate: Any) -> tuple[dict[str, Any], str]:
    """Keep only the policy's credential-free route identity fields."""
    if not isinstance(candidate, dict):
        raise TypeError("synopsis import route snapshot is missing")
    missing = [field for field in ROUTE_SNAPSHOT_FIELDS if field not in candidate]
    if missing:
        raise RuntimeError(
            "synopsis import route snapshot is incomplete: " + ", ".join(missing)
        )
    snapshot = {field: candidate[field] for field in ROUTE_SNAPSHOT_FIELDS}
    base_url = str(snapshot["base_url"] or "")
    parsed_base_url = urlsplit(base_url)
    credential_query_names = {"api_key", "apikey", "key", "secret", "token"}
    if parsed_base_url.username or parsed_base_url.password or any(
        name.casefold() in credential_query_names
        for name, _ in parse_qsl(parsed_base_url.query, keep_blank_values=True)
    ):
        raise RuntimeError("synopsis import route snapshot contains credential material")
    try:
        snapshot["profile_revision"] = int(snapshot["profile_revision"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("synopsis import route profile revision is invalid") from exc
    identity_hash = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    supplied_hash = str(candidate.get("identity_sha256") or "")
    if supplied_hash and supplied_hash != identity_hash:
        raise RuntimeError("synopsis import route snapshot identity hash is invalid")
    return {**snapshot, "identity_sha256": identity_hash}, identity_hash


def _route_snapshot_json(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class MedicalWritingSynopsisImportService:
    """Persist a project synopsis and produce a source-bound study-definition candidate."""

    def __init__(
        self,
        artifact_root: Path,
        ai_task_runner: Any,
        db_path: Path | None = None,
        *,
        claim_timeout_seconds: float = 360.0,
        poll_interval_seconds: float = 0.05,
        chunk_lease_seconds: float = 900.0,
        heartbeat_interval_seconds: float = 60.0,
    ):
        if claim_timeout_seconds <= 0:
            raise ValueError("synopsis import claim timeout must be positive")
        if poll_interval_seconds <= 0:
            raise ValueError("synopsis import poll interval must be positive")
        if chunk_lease_seconds <= 0:
            raise ValueError("synopsis import chunk lease must be positive")
        if heartbeat_interval_seconds <= 0:
            raise ValueError("synopsis import heartbeat interval must be positive")
        self.artifact_root = Path(artifact_root)
        self.ai_task_runner = ai_task_runner
        self.claim_timeout_seconds = float(claim_timeout_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.chunk_lease_seconds = float(chunk_lease_seconds)
        self.heartbeat_interval_seconds = float(heartbeat_interval_seconds)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path or self.artifact_root.parent / "medical_writing_synopsis_import.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Thread tracking for bounded shutdown.
        self._worker_threads: list[threading.Thread] = []
        self._threads_lock = threading.Lock()
        self._shutdown_requested = False
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS medical_writing_synopsis_imports (
                    project_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'completed',
                    payload_json TEXT NOT NULL DEFAULT '',
                    claim_token TEXT NOT NULL DEFAULT '',
                    lease_expires_at TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, idempotency_key)
                )
                """
            )
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(medical_writing_synopsis_imports)"
                ).fetchall()
            }
            migrations = {
                "status": "TEXT NOT NULL DEFAULT 'completed'",
                "claim_token": "TEXT NOT NULL DEFAULT ''",
                "lease_expires_at": "TEXT NOT NULL DEFAULT ''",
                "attempt_count": "INTEGER NOT NULL DEFAULT 1",
                "error_message": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
                "phase": "TEXT NOT NULL DEFAULT 'completed'",
                "chunk_index": "INTEGER NOT NULL DEFAULT 0",
                "chunk_total": "INTEGER NOT NULL DEFAULT 0",
                "progress_json": "TEXT NOT NULL DEFAULT ''",
                "source_sha256": "TEXT NOT NULL DEFAULT ''",
                "source_filename": "TEXT NOT NULL DEFAULT ''",
                "cancelled_at": "TEXT NOT NULL DEFAULT ''",
                "result_json": "TEXT NOT NULL DEFAULT ''",
                # --- v2 additive columns for real chunk execution / cold recovery ---
                "job_id": "TEXT NOT NULL DEFAULT ''",
                "media_type": "TEXT NOT NULL DEFAULT ''",
                "expected_indication": "TEXT NOT NULL DEFAULT ''",
                "actor": "TEXT NOT NULL DEFAULT ''",
                # --- v3: persist full source JSON for exact reconstruction ---
                "source_json": "TEXT NOT NULL DEFAULT ''",
                # --- v4: frozen route identity for durable execution ---
                "route_snapshot_json": "TEXT NOT NULL DEFAULT ''",
                "route_identity_hash": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in migrations.items():
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE medical_writing_synopsis_imports "
                        f"ADD COLUMN {column} {definition}"
                    )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS medical_writing_synopsis_import_chunks (
                    project_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    provider_output_hash TEXT NOT NULL DEFAULT '',
                    validation_error TEXT NOT NULL DEFAULT '',
                    evidence_span_ids_json TEXT NOT NULL DEFAULT '[]',
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (project_id, idempotency_key, chunk_index)
                )
                """
            )
            # --- v2 additive columns for chunk claim/lease/output ---
            chunk_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(medical_writing_synopsis_import_chunks)"
                ).fetchall()
            }
            chunk_migrations = {
                "claim_token": "TEXT NOT NULL DEFAULT ''",
                "lease_expires_at": "TEXT NOT NULL DEFAULT ''",
                "output_json": "TEXT NOT NULL DEFAULT ''",
                "chunk_sources_json": "TEXT NOT NULL DEFAULT '[]'",
                "provider": "TEXT NOT NULL DEFAULT ''",
                "model_name": "TEXT NOT NULL DEFAULT ''",
                # --- v4: per-chunk route and AI execution audit ---
                "route_identity_hash": "TEXT NOT NULL DEFAULT ''",
                "ai_run_id": "TEXT NOT NULL DEFAULT ''",
                "actual_response_model": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in chunk_migrations.items():
                if column not in chunk_columns:
                    connection.execute(
                        f"ALTER TABLE medical_writing_synopsis_import_chunks "
                        f"ADD COLUMN {column} {definition}"
                    )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_synopsis_import_chunks_status
                ON medical_writing_synopsis_import_chunks(project_id, idempotency_key, status)
                """
            )
            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET updated_at = created_at
                WHERE updated_at = ''
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_medical_writing_synopsis_import_status
                ON medical_writing_synopsis_imports(status, lease_expires_at)
                """
            )
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("medical-writing synopsis import SQLite integrity check failed")

    def _capture_route_snapshot(self) -> tuple[dict[str, Any], str]:
        """Read the effective route once; never persist credentials."""
        owners = [
            getattr(self.ai_task_runner, "policy_resolver", None),
            self.ai_task_runner,
        ]
        for owner in owners:
            snapshot_reader = getattr(owner, "route_identity_snapshot", None)
            if callable(snapshot_reader):
                return _normalize_route_snapshot(snapshot_reader(refresh=True))
        raise RuntimeError(
            "synopsis import requires an AI runner with a route identity snapshot"
        )

    def _assert_current_route_matches(self, expected_hash: str) -> None:
        _, current_hash = self._capture_route_snapshot()
        if current_hash != expected_hash:
            raise RuntimeError(
                "synopsis import route configuration changed after task start"
            )

    @staticmethod
    def _validate_ai_run_route(run: Any, expected_hash: str) -> tuple[str, str, str]:
        actual_hash = str(getattr(run, "route_identity_hash", "") or "")
        if not actual_hash:
            raise RuntimeError("AiTaskRun.route_identity_hash is missing")
        if actual_hash != expected_hash:
            raise RuntimeError(
                "AiTaskRun.route_identity_hash does not match the frozen synopsis route"
            )
        run_id = str(getattr(run, "run_id", "") or "")
        actual_response_model = str(
            getattr(run, "actual_response_model", "") or ""
        )
        provider = str(getattr(run, "provider", "") or "")
        model_name = str(getattr(run, "model_name", "") or "")
        return run_id, actual_response_model, provider or model_name

    def _load_frozen_route(
        self, connection: sqlite3.Connection, project_id: str, idempotency_key: str
    ) -> tuple[dict[str, Any], str]:
        row = connection.execute(
            "SELECT route_snapshot_json, route_identity_hash "
            "FROM medical_writing_synopsis_imports "
            "WHERE project_id = ? AND idempotency_key = ?",
            (project_id, idempotency_key),
        ).fetchone()
        if row is None or not row["route_snapshot_json"] or not row["route_identity_hash"]:
            raise RuntimeError("cold recovery requires a persisted frozen route snapshot")
        try:
            snapshot = json.loads(row["route_snapshot_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("persisted synopsis route snapshot is invalid") from exc
        normalized, computed_hash = _normalize_route_snapshot(snapshot)
        if computed_hash != row["route_identity_hash"]:
            raise RuntimeError("persisted synopsis route identity hash does not match snapshot")
        return normalized, computed_hash

    def import_and_structure(
        self,
        project_id: str,
        *,
        filename: str,
        content_type: str,
        payload: bytes,
        expected_indication: str,
        actor: str,
        idempotency_key: str = "",
    ) -> MedicalWritingSynopsisImport:
        if not payload:
            raise ValueError("protocol synopsis file is empty")
        if len(payload) > MAX_SYNOPSIS_BYTES:
            raise ValueError("protocol synopsis file exceeds 30 MiB")
        actor = actor.strip()
        idempotency_key = idempotency_key.strip() or (
            "synopsis-import-" + hashlib.sha256(payload).hexdigest()
        )
        if not actor:
            raise ValueError("synopsis import actor must not be blank")
        media_type, suffix = _detect_media_type(filename, content_type, payload)
        content_sha256 = hashlib.sha256(payload).hexdigest()
        request_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "filename": Path(filename).name,
                    "media_type": media_type,
                    "content_sha256": content_sha256,
                    "expected_indication": expected_indication.strip(),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        claim_token = uuid.uuid4().hex
        observed_attempt: int | None = None
        while True:
            decision = self._claim_once(
                project_id=project_id,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                claim_token=claim_token,
                observed_attempt=observed_attempt,
            )
            if decision["action"] == "completed":
                return MedicalWritingSynopsisImport.model_validate_json(
                    decision["payload_json"]
                )
            if decision["action"] == "claimed":
                break
            if decision["action"] == "failed":
                detail = decision["error_message"] or "unknown technical failure"
                raise RuntimeError(
                    f"protocol synopsis import attempt failed before completion: {detail}"
                )
            observed_attempt = int(decision["attempt_count"])
            time.sleep(self.poll_interval_seconds)

        route_identity_hash = decision["route_identity_hash"]

        heartbeat_stop, heartbeat_thread = self._start_claim_heartbeat(
            project_id, idempotency_key, claim_token
        )
        try:
            result = self._run_import(
                project_id=project_id,
                filename=filename,
                media_type=media_type,
                suffix=suffix,
                payload=payload,
                content_sha256=content_sha256,
                expected_indication=expected_indication,
                actor=actor,
                route_identity_hash=route_identity_hash,
            )
            return self._complete_claim(
                project_id=project_id,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                claim_token=claim_token,
                result=result,
            )
        except Exception as exc:
            try:
                self._fail_claim(
                    project_id=project_id,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    claim_token=claim_token,
                    error_message=f"{type(exc).__name__}: {exc}"[:2000],
                )
            except sqlite3.Error:
                pass
            raise
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1.0)

    def _run_import(
        self,
        *,
        project_id: str,
        filename: str,
        media_type: str,
        suffix: str,
        payload: bytes,
        content_sha256: str,
        expected_indication: str,
        actor: str,
        route_identity_hash: str,
    ) -> MedicalWritingSynopsisImport:
        source_id = "mwsynopsis_" + hashlib.sha256(
            f"{project_id}|{content_sha256}".encode("utf-8")
        ).hexdigest()[:24]
        project_token = re.sub(r"[^a-z0-9]+", "_", project_id.lower()).strip("_")
        storage_dir = self.artifact_root / project_token / content_sha256[:2]
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / f"{source_id}{suffix}"
        if storage_path.exists():
            if hashlib.sha256(storage_path.read_bytes()).hexdigest() != content_sha256:
                raise RuntimeError("existing synopsis artifact hash does not match")
        else:
            try:
                with storage_path.open("xb") as output:
                    output.write(payload)
            except FileExistsError:
                if hashlib.sha256(storage_path.read_bytes()).hexdigest() != content_sha256:
                    raise RuntimeError("concurrent synopsis artifact hash does not match")

        now = datetime.now(timezone.utc)
        artifact = WritingReferenceDocumentArtifact(
            artifact_id=source_id,
            project_id=project_id,
            snapshot_id="project_synopsis",
            nct_id=project_id,
            source_document_id=source_id,
            document_type="study_synopsis",
            filename=Path(filename).name,
            requested_url="",
            final_url="",
            content_type=media_type,
            declared_size=len(payload),
            actual_size=len(payload),
            content_sha256=content_sha256,
            source_status="user_uploaded",
            created_by=actor,
            created_at=now,
        )
        if suffix == ".pdf":
            extracted = extract_pdf_sections(payload, artifact)
        else:
            extracted = extract_docx_sections(payload, artifact)
        if not extracted.spans:
            raise ValueError("protocol synopsis contains no extractable text")

        source_text = "\n".join(span.source_text for span in extracted.spans)
        source_role_status, role_warnings = _assess_source_role(source_text)
        indication_status, indication_warnings = _assess_indication(
            source_text, expected_indication
        )
        warnings = [*role_warnings, *indication_warnings]
        source = MedicalWritingSynopsisSource(
            source_id=source_id,
            original_filename=Path(filename).name,
            media_type=media_type,
            actual_size=len(payload),
            content_sha256=content_sha256,
            extraction_revision=extracted.extraction_revision,
            parser_name=extracted.parser_name,
            source_role_status=source_role_status,
            indication_status=indication_status,
            validation_warnings=warnings,
            imported_at=now,
            imported_by=actor,
        )
        ai_sources = _ai_sources(project_id, source_id, extracted.spans)
        ai_request = AiTaskRequest(
            module="medical_writing",
            task_type="protocol_synopsis_structuring",
            prompt_version="protocol_synopsis_structuring_v0_9",
            allowed_sources=ai_sources,
            forbidden_source_ids=[
                "competitor_protocol",
                "previous_ai_summary",
                "previous_study_definition",
            ],
            user_instruction=_synopsis_structuring_instruction(expected_indication),
        )
        self._assert_current_route_matches(route_identity_hash)
        run = self.ai_task_runner.submit_internal(project_id, ai_request)
        self._validate_ai_run_route(run, route_identity_hash)
        status = getattr(run.status, "value", run.status)
        if status != "completed":
            detail = "; ".join(run.validation_errors) or run.error_message or status
            raise RuntimeError(f"protocol synopsis structuring AI task did not complete: {detail}")
        provider_payload = next(
            (
                artifact.payload
                for artifact in run.artifacts
                if artifact.artifact_type == "provider_output"
            ),
            None,
        )
        if not isinstance(provider_payload, dict):
            raise TypeError("validated protocol synopsis structuring output is missing")
        definition = provider_payload.get("study_definition")
        if not isinstance(definition, dict):
            raise TypeError("validated protocol synopsis study_definition is missing")
        picos_payload = _sanitize_synopsis_instrument_candidates(
            definition.get("picos"), source_id=source_id
        )
        try:
            framing = MedicalWritingStudyFraming.model_validate(definition["framing"])
            picos = MedicalWritingPicosDefinition.model_validate(picos_payload)
        except (KeyError, TypeError, ValidationError) as exc:
            raise RuntimeError(
                "validated protocol synopsis output does not match the study-definition contract"
            ) from exc
        evidence_spans = [
            MedicalWritingSynopsisEvidenceSpan(
                span_id=item["span_id"],
                source_id=item["source_id"],
                locator=item["locator"],
                source_text=item["quote"],
                source_text_sha256=hashlib.sha256(
                    item["quote"].encode("utf-8")
                ).hexdigest(),
            )
            for item in provider_payload.get("evidence_spans", [])
        ]
        picos = _bind_synopsis_instrument_sources(
            picos,
            source=source,
            field_evidence_span_ids=definition.get("field_evidence_span_ids", {}),
            evidence_spans=evidence_spans,
        )
        result = MedicalWritingSynopsisImport(
            status="review_pending",
            source=source,
            proposed_framing=framing,
            proposed_picos=picos,
            proposed_synopsis_text=definition["synopsis_text"],
            missing_fields=list(definition["missing_fields"]),
            conflict_notes=list(definition["conflict_notes"]),
            field_evidence_span_ids={
                str(key): list(value)
                for key, value in definition["field_evidence_span_ids"].items()
            },
            evidence_spans=evidence_spans,
            ai_run_id=run.run_id,
        )
        return result

    def _claim_once(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        request_sha256: str,
        claim_token: str,
        observed_attempt: int | None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        lease_expires_at = now + timedelta(seconds=self.claim_timeout_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT request_sha256, status, payload_json, claim_token,
                       lease_expires_at, attempt_count, error_message,
                       route_snapshot_json, route_identity_hash
                FROM medical_writing_synopsis_imports
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if row is None:
                route_snapshot, route_identity_hash = self._capture_route_snapshot()
                connection.execute(
                    """
                    INSERT INTO medical_writing_synopsis_imports(
                        project_id, idempotency_key, request_sha256, status,
                        payload_json, claim_token, lease_expires_at, attempt_count,
                        error_message, created_at, updated_at,
                        route_snapshot_json, route_identity_hash
                    ) VALUES (?, ?, ?, 'pending', '', ?, ?, 1, '', ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        idempotency_key,
                        request_sha256,
                        claim_token,
                        lease_expires_at.isoformat(),
                        now.isoformat(),
                        now.isoformat(),
                        _route_snapshot_json(route_snapshot),
                        route_identity_hash,
                    ),
                )
                connection.commit()
                return {
                    "action": "claimed",
                    "attempt_count": 1,
                    "route_snapshot": route_snapshot,
                    "route_identity_hash": route_identity_hash,
                }
            if row["request_sha256"] != request_sha256:
                connection.rollback()
                raise ValueError(
                    "synopsis import idempotency key was reused with different content"
                )
            status = row["status"]
            if status == "completed":
                connection.commit()
                return {
                    "action": "completed",
                    "payload_json": row["payload_json"],
                }
            if not row["route_snapshot_json"] or not row["route_identity_hash"]:
                connection.commit()
                return {
                    "action": "failed",
                    "attempt_count": int(row["attempt_count"]),
                    "error_message": "frozen route identity is missing; retry is not allowed",
                }
            try:
                frozen_snapshot, frozen_hash = _normalize_route_snapshot(
                    json.loads(row["route_snapshot_json"])
                )
            except (RuntimeError, TypeError, json.JSONDecodeError) as exc:
                connection.commit()
                return {
                    "action": "failed",
                    "attempt_count": int(row["attempt_count"]),
                    "error_message": f"persisted frozen route is invalid; retry is not allowed: {exc}",
                }
            if frozen_hash != row["route_identity_hash"]:
                connection.commit()
                return {
                    "action": "failed",
                    "attempt_count": int(row["attempt_count"]),
                    "error_message": "persisted frozen route identity hash is invalid; retry is not allowed",
                }
            attempt_count = int(row["attempt_count"])
            if status == "failed" and observed_attempt == attempt_count:
                connection.commit()
                return {
                    "action": "failed",
                    "attempt_count": attempt_count,
                    "error_message": row["error_message"],
                }
            if status == "pending" and not _lease_is_expired(
                row["lease_expires_at"], now
            ):
                connection.commit()
                return {"action": "wait", "attempt_count": attempt_count}
            if status not in {"pending", "failed"}:
                connection.rollback()
                raise RuntimeError(f"unknown synopsis import state: {status}")
            next_attempt = attempt_count + 1
            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET status = 'pending', payload_json = '', claim_token = ?,
                    lease_expires_at = ?, attempt_count = ?, error_message = '',
                    updated_at = ?
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (
                    claim_token,
                    lease_expires_at.isoformat(),
                    next_attempt,
                    now.isoformat(),
                    project_id,
                    idempotency_key,
                ),
            )
            connection.commit()
            return {
                "action": "claimed",
                "attempt_count": next_attempt,
                "route_snapshot": frozen_snapshot,
                "route_identity_hash": frozen_hash,
            }

    def _start_claim_heartbeat(
        self, project_id: str, idempotency_key: str, claim_token: str
    ) -> tuple[threading.Event, threading.Thread]:
        stop = threading.Event()
        interval = min(5.0, max(0.01, self.claim_timeout_seconds / 3.0))

        def renew_until_stopped() -> None:
            while not stop.wait(interval):
                try:
                    self._renew_claim(project_id, idempotency_key, claim_token)
                except sqlite3.Error:
                    continue

        thread = threading.Thread(
            target=renew_until_stopped,
            name=f"synopsis-import-lease-{claim_token[:8]}",
            daemon=True,
        )
        thread.start()
        return stop, thread

    def _renew_claim(
        self, project_id: str, idempotency_key: str, claim_token: str
    ) -> None:
        now = datetime.now(timezone.utc)
        lease_expires_at = now + timedelta(seconds=self.claim_timeout_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET lease_expires_at = ?, updated_at = ?
                WHERE project_id = ? AND idempotency_key = ?
                  AND status = 'pending' AND claim_token = ?
                """,
                (
                    lease_expires_at.isoformat(),
                    now.isoformat(),
                    project_id,
                    idempotency_key,
                    claim_token,
                ),
            )
            connection.commit()

    def _complete_claim(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        request_sha256: str,
        claim_token: str,
        result: MedicalWritingSynopsisImport,
    ) -> MedicalWritingSynopsisImport:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT request_sha256, status, payload_json, claim_token
                FROM medical_writing_synopsis_imports
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if row is None or row["request_sha256"] != request_sha256:
                connection.rollback()
                raise RuntimeError("synopsis import claim disappeared before completion")
            if row["status"] == "completed":
                connection.commit()
                return MedicalWritingSynopsisImport.model_validate_json(
                    row["payload_json"]
                )
            if row["status"] != "pending" or row["claim_token"] != claim_token:
                connection.rollback()
                raise RuntimeError("synopsis import claim ownership was lost")
            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET status = 'completed', payload_json = ?, claim_token = '',
                    lease_expires_at = '', error_message = '', updated_at = ?
                WHERE project_id = ? AND idempotency_key = ?
                  AND status = 'pending' AND claim_token = ?
                """,
                (
                    result.model_dump_json(),
                    now,
                    project_id,
                    idempotency_key,
                    claim_token,
                ),
            )
            connection.commit()
        return result

    def _fail_claim(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        request_sha256: str,
        claim_token: str,
        error_message: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET status = 'failed', payload_json = '', claim_token = '',
                    lease_expires_at = '', error_message = ?, updated_at = ?
                WHERE project_id = ? AND idempotency_key = ?
                  AND request_sha256 = ? AND status = 'pending'
                  AND claim_token = ?
                """,
                (
                    error_message,
                    now,
                    project_id,
                    idempotency_key,
                    request_sha256,
                    claim_token,
                ),
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    # ------------------------------------------------------------------
    # Async job lifecycle (202 + polling)
    # ------------------------------------------------------------------

    def start_job(
        self,
        project_id: str,
        *,
        filename: str,
        content_type: str,
        payload: bytes,
        expected_indication: str,
        actor: str,
        idempotency_key: str = "",
    ) -> SynopsisImportJobStartResponse:
        """Synchronously parse and store bytes, create a job row with real chunk
        rows, spawn the background per-chunk AI worker, and return 202
        immediately.  AI never blocks the response."""
        if not payload:
            raise ValueError("protocol synopsis file is empty")
        if len(payload) > MAX_SYNOPSIS_BYTES:
            raise ValueError("protocol synopsis file exceeds 30 MiB")
        actor = actor.strip()
        if not actor:
            raise ValueError("synopsis import actor must not be blank")
        idempotency_key = idempotency_key.strip() or (
            "synopsis-import-" + hashlib.sha256(payload).hexdigest()
        )
        media_type, suffix = _detect_media_type(filename, content_type, payload)
        content_sha256 = hashlib.sha256(payload).hexdigest()
        request_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "filename": Path(filename).name,
                    "media_type": media_type,
                    "content_sha256": content_sha256,
                    "expected_indication": expected_indication.strip(),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        # Stable job_id derived deterministically from project + content.
        job_id = "mwjob_" + hashlib.sha256(
            f"{project_id}|{content_sha256}".encode("utf-8")
        ).hexdigest()[:24]
        now = datetime.now(timezone.utc)

        # --- idempotent job row creation / reuse ---
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT request_sha256, status, phase, source_sha256, job_id,
                       chunk_total
                FROM medical_writing_synopsis_imports
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    connection.rollback()
                    raise ValueError(
                        "synopsis import idempotency key was reused with different content"
                    )
                # Reuse existing job — return current state.
                connection.commit()
                return SynopsisImportJobStartResponse(
                    job_id=existing["job_id"] or job_id,
                    idempotency_key=idempotency_key,
                    status="reused",
                    phase=existing["phase"] or "chunking",
                    content_sha256=existing["source_sha256"] or content_sha256,
                    span_count=existing["chunk_total"] or 0,
                    media_type=media_type,
                    warnings=[],
                )
            route_snapshot, route_identity_hash = self._capture_route_snapshot()
            connection.execute(
                """
                INSERT INTO medical_writing_synopsis_imports(
                    project_id, idempotency_key, request_sha256, status,
                    payload_json, claim_token, lease_expires_at, attempt_count,
                    error_message, created_at, updated_at, phase, chunk_index,
                    chunk_total, progress_json, source_sha256, source_filename,
                    cancelled_at, result_json, job_id, media_type,
                    expected_indication, actor, source_json,
                    route_snapshot_json, route_identity_hash
                ) VALUES (?, ?, ?, 'pending', '', '', '', 1, '', ?, ?,
                          'parsing', 0, 0, '', ?, ?, '', '', ?, ?, ?, ?, '', ?, ?)
                """,
                (
                    project_id,
                    idempotency_key,
                    request_sha256,
                    now.isoformat(),
                    now.isoformat(),
                    content_sha256,
                    Path(filename).name,
                    job_id,
                    media_type,
                    expected_indication.strip(),
                    actor,
                    _route_snapshot_json(route_snapshot),
                    route_identity_hash,
                ),
            )
            connection.commit()

        # --- deterministic parse OFF the response path (T17 会商#2) ---
        # A 1.3MB PDF blocked this request for minutes with no progress and
        # no way to cancel: the job row (and its id) only existed after the
        # parse finished.  The row is now created first with phase='parsing',
        # the request returns immediately, and a detached thread finishes
        # parse → chunk persistence → AI worker spawn.  cancel_job works
        # from the first second because the job id exists up front.
        def _finish_import_start():
            if self._import_cancelled(project_id, idempotency_key):
                return
            try:
                self._finish_import_start_locked(
                    project_id=project_id,
                    idempotency_key=idempotency_key,
                    filename=filename,
                    media_type=media_type,
                    suffix=suffix,
                    payload=payload,
                    content_sha256=content_sha256,
                    expected_indication=expected_indication,
                    actor=actor,
                    route_snapshot=route_snapshot,
                    route_identity_hash=route_identity_hash,
                    job_id=job_id,
                )
            except Exception:
                # The job row stays in phase='parsing'; the status route
                # reports the failure instead of hanging forever.
                self._mark_import_failed(project_id, idempotency_key)

        threading.Thread(target=_finish_import_start, daemon=True).start()

        return SynopsisImportJobStartResponse(
            job_id=job_id,
            idempotency_key=idempotency_key,
            status="parsing",
            phase="parsing",
            content_sha256=content_sha256,
            span_count=0,
            media_type=media_type,
            warnings=[],
        )

    def _import_cancelled(self, project_id: str, idempotency_key: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM medical_writing_synopsis_imports "
                "WHERE project_id = ? AND idempotency_key = ?",
                (project_id, idempotency_key),
            ).fetchone()
        return bool(row and row["status"] == "cancelled")

    def _mark_import_failed(self, project_id: str, idempotency_key: str) -> None:
        import traceback
        with self._connect() as connection:
            connection.execute(
                "UPDATE medical_writing_synopsis_imports SET status = 'failed', "
                "error_message = ?, updated_at = ? WHERE project_id = ? AND idempotency_key = ?",
                (traceback.format_exc(limit=3)[:1800], datetime.now(timezone.utc).isoformat(),
                 project_id, idempotency_key),
            )
            connection.commit()

    def _finish_import_start_locked(
        self, *, project_id, idempotency_key, filename, media_type, suffix,
        payload, content_sha256, expected_indication, actor,
        route_snapshot, route_identity_hash, job_id,
    ):
        parse_result = self._deterministic_parse(
            project_id=project_id,
            filename=filename,
            media_type=media_type,
            suffix=suffix,
            payload=payload,
            content_sha256=content_sha256,
            expected_indication=expected_indication,
            actor=actor,
        )
        if self._import_cancelled(project_id, idempotency_key):
            return

        # Persist chunk rows + update job with real chunk metadata.
        now = datetime.now(timezone.utc)
        chunks = parse_result["chunks"]
        chunk_total = max(1, len(chunks))
        if not chunks:
            chunks = [parse_result["ai_sources"]]  # single chunk fallback

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source_json_str = parse_result["source"].model_dump_json()
            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET phase = 'chunking', status = 'pending', chunk_total = ?,
                    progress_json = ?,
                    source_filename = ?, media_type = ?,
                    expected_indication = ?, actor = ?, source_json = ?,
                    route_identity_hash = ?,
                    updated_at = ?
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (
                    chunk_total,
                    json.dumps(
                        {
                            "phase": "chunking",
                            "chunk_total": chunk_total,
                            "anchor_count": parse_result["anchor_count"],
                        },
                        ensure_ascii=False,
                    ),
                    Path(filename).name,
                    media_type,
                    expected_indication.strip(),
                    actor,
                    source_json_str,
                    route_identity_hash,
                    now.isoformat(),
                    project_id,
                    idempotency_key,
                ),
            )
            # Delete any old chunk rows and recreate fresh ones.
            connection.execute(
                """
                DELETE FROM medical_writing_synopsis_import_chunks
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            )
            for chunk_idx, chunk_sources in enumerate(chunks):
                chunk_sources_json = json.dumps(
                    [
                        {
                            "source_id": s.source_id,
                            "source_type": s.source_type,
                            "title": s.title,
                            "locator": s.locator,
                            "text_preview": s.text_preview,
                            "project_id": s.project_id,
                            "module": s.module,
                            "source_entry_id": s.source_entry_id,
                        }
                        for s in chunk_sources
                    ],
                    ensure_ascii=False,
                )
                connection.execute(
                    """
                    INSERT INTO medical_writing_synopsis_import_chunks(
                        project_id, idempotency_key, chunk_index, status,
                        attempt_count, started_at, chunk_sources_json,
                        route_identity_hash
                    ) VALUES (?, ?, ?, 'pending', 0, '', ?, ?)
                    """,
                    (
                        project_id,
                        idempotency_key,
                        chunk_idx,
                        chunk_sources_json,
                        route_identity_hash,
                    ),
                )
            connection.commit()

        # --- spawn background AI worker ---
        self._spawn_chunked_worker(
            project_id=project_id,
            idempotency_key=idempotency_key,
            source_id=parse_result["source_id"],
            source=parse_result["source"],
            actor=actor,
            expected_indication=expected_indication,
            route_identity_hash=route_identity_hash,
        )

        return SynopsisImportJobStartResponse(
            job_id=job_id,
            idempotency_key=idempotency_key,
            status="chunking",
            phase="chunking",
            content_sha256=content_sha256,
            span_count=parse_result["span_count"],
            media_type=media_type,
            warnings=parse_result["warnings"],
        )

    def _deterministic_parse(
        self,
        *,
        project_id: str,
        filename: str,
        media_type: str,
        suffix: str,
        payload: bytes,
        content_sha256: str,
        expected_indication: str,
        actor: str,
    ) -> dict[str, Any]:
        """Run the deterministic parser + source-role/indication checks and
        build chunk boundaries.  No AI is invoked."""
        source_id = "mwsynopsis_" + hashlib.sha256(
            f"{project_id}|{content_sha256}".encode("utf-8")
        ).hexdigest()[:24]
        project_token = re.sub(r"[^a-z0-9]+", "_", project_id.lower()).strip("_")
        storage_dir = self.artifact_root / project_token / content_sha256[:2]
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / f"{source_id}{suffix}"
        if storage_path.exists():
            if hashlib.sha256(storage_path.read_bytes()).hexdigest() != content_sha256:
                raise RuntimeError("existing synopsis artifact hash does not match")
        else:
            try:
                with storage_path.open("xb") as output:
                    output.write(payload)
            except FileExistsError:
                if hashlib.sha256(storage_path.read_bytes()).hexdigest() != content_sha256:
                    raise RuntimeError("concurrent synopsis artifact hash does not match")

        now = datetime.now(timezone.utc)
        artifact = WritingReferenceDocumentArtifact(
            artifact_id=source_id,
            project_id=project_id,
            snapshot_id="project_synopsis",
            nct_id=project_id,
            source_document_id=source_id,
            document_type="study_synopsis",
            filename=Path(filename).name,
            requested_url="",
            final_url="",
            content_type=media_type,
            declared_size=len(payload),
            actual_size=len(payload),
            content_sha256=content_sha256,
            source_status="user_uploaded",
            created_by=actor,
            created_at=now,
        )
        if suffix == ".pdf":
            extracted = extract_pdf_sections(payload, artifact)
        else:
            extracted = extract_docx_sections(payload, artifact)
        if not extracted.spans:
            raise ValueError("protocol synopsis contains no extractable text")

        source_text = "\n".join(span.source_text for span in extracted.spans)
        source_role_status, role_warnings = _assess_source_role(source_text)
        indication_status, indication_warnings = _assess_indication(
            source_text, expected_indication
        )
        warnings = [*role_warnings, *indication_warnings]
        source = MedicalWritingSynopsisSource(
            source_id=source_id,
            original_filename=Path(filename).name,
            media_type=media_type,
            actual_size=len(payload),
            content_sha256=content_sha256,
            extraction_revision=extracted.extraction_revision,
            parser_name=extracted.parser_name,
            source_role_status=source_role_status,
            indication_status=indication_status,
            validation_warnings=warnings,
            imported_at=now,
            imported_by=actor,
        )

        ai_sources = _ai_sources(project_id, source_id, extracted.spans)
        chunks = _chunk_ai_sources(ai_sources, MAX_SYNOPSIS_CHUNK_CHARS)
        chunk_total = max(1, len(chunks))

        # Count deterministic anchors for progress reporting.
        try:
            from .ai_task_runner import _protocol_synopsis_row_anchors
            anchors = _protocol_synopsis_row_anchors(ai_sources)
            anchor_count = sum(len(items) for items in anchors.values())
        except Exception:
            anchor_count = 0

        return {
            "source_id": source_id,
            "source": source,
            "ai_sources": ai_sources,
            "chunks": chunks,
            "chunk_total": chunk_total,
            "anchor_count": anchor_count,
            "span_count": len(extracted.spans),
            "warnings": warnings,
            "progress": SynopsisImportJobProgress(
                phase="chunking",
                chunk_total=chunk_total,
            ).model_dump(mode="json"),
        }

    def _load_source_from_db(
        self, connection: sqlite3.Connection, project_id: str, idempotency_key: str
    ) -> MedicalWritingSynopsisSource:
        """Reconstruct the exact MedicalWritingSynopsisSource from persisted JSON."""
        row = connection.execute(
            "SELECT source_json FROM medical_writing_synopsis_imports "
            "WHERE project_id = ? AND idempotency_key = ?",
            (project_id, idempotency_key),
        ).fetchone()
        if row and row["source_json"]:
            return MedicalWritingSynopsisSource.model_validate_json(row["source_json"])
        # Fallback for pre-v3 rows: derive from stored fields.
        row2 = connection.execute(
            "SELECT source_sha256, source_filename, media_type "
            "FROM medical_writing_synopsis_imports "
            "WHERE project_id = ? AND idempotency_key = ?",
            (project_id, idempotency_key),
        ).fetchone()
        content_sha256 = row2["source_sha256"] if row2 else ""
        source_id = "mwsynopsis_" + hashlib.sha256(
            f"{project_id}|{content_sha256}".encode("utf-8")
        ).hexdigest()[:24]
        now = datetime.now(timezone.utc)
        return MedicalWritingSynopsisSource(
            source_id=source_id,
            original_filename=(row2["source_filename"] if row2 else "") or "study-synopsis",
            media_type=(row2["media_type"] if row2 else "")
            or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            actual_size=1,
            content_sha256=content_sha256,
            extraction_revision="recovered",
            parser_name="recovered",
            source_role_status="matched",
            indication_status="not_assessed",
            validation_warnings=[],
            imported_at=now,
            imported_by="system",
        )

    def _spawn_chunked_worker(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        source_id: str,
        source: MedicalWritingSynopsisSource,
        actor: str,
        expected_indication: str,
        route_identity_hash: str,
    ) -> None:
        """Spawn the background per-chunk AI synthesis worker thread."""
        if self._shutdown_requested:
            return
        thread = threading.Thread(
            target=self._run_chunked_worker_safe,
            kwargs={
                "project_id": project_id,
                "idempotency_key": idempotency_key,
                "source_id": source_id,
                "source": source,
                "actor": actor,
                "expected_indication": expected_indication,
                "route_identity_hash": route_identity_hash,
            },
            name=f"synopsis-chunked-{idempotency_key[:12]}",
            daemon=True,
        )
        with self._threads_lock:
            self._worker_threads.append(thread)
        thread.start()

    def _run_chunked_worker_safe(self, **kwargs: Any) -> None:
        """Wrapper that removes the thread from tracking on exit."""
        current = threading.current_thread()
        try:
            self._run_chunked_worker(**kwargs)
        finally:
            with self._threads_lock:
                if current in self._worker_threads:
                    self._worker_threads.remove(current)

    def shutdown(self, timeout: float = 30.0) -> None:
        """Signal all workers to stop and join them within a bounded timeout."""
        self._shutdown_requested = True
        with self._threads_lock:
            threads = list(self._worker_threads)
        for t in threads:
            t.join(timeout=timeout)

    def _is_cancelled(self, project_id: str, idempotency_key: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cancelled_at FROM medical_writing_synopsis_imports "
                "WHERE project_id = ? AND idempotency_key = ?",
                (project_id, idempotency_key),
            ).fetchone()
        return bool(row and row["cancelled_at"])

    def _claim_chunk(
        self, project_id: str, idempotency_key: str, chunk_index: int
    ) -> str | None:
        """Atomically claim a pending/failed chunk. Returns opaque claim token
        if claimed, None if already owned or done."""
        claim_token = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        lease_expires_at = now + timedelta(seconds=self.chunk_lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, lease_expires_at, attempt_count
                FROM medical_writing_synopsis_import_chunks
                WHERE project_id = ? AND idempotency_key = ? AND chunk_index = ?
                """,
                (project_id, idempotency_key, chunk_index),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            status = row["status"]
            lease_expired = _lease_is_expired(row["lease_expires_at"], now)
            if status == "done":
                connection.commit()
                return None
            if status == "running" and not lease_expired:
                connection.commit()
                return None
            next_attempt = (
                int(row["attempt_count"]) + 1
                if status == "failed"
                else max(1, int(row["attempt_count"]))
            )
            connection.execute(
                """
                UPDATE medical_writing_synopsis_import_chunks
                SET status = 'running', claim_token = ?,
                    lease_expires_at = ?, attempt_count = ?,
                    started_at = COALESCE(NULLIF(started_at, ''), ?)
                WHERE project_id = ? AND idempotency_key = ? AND chunk_index = ?
                """,
                (
                    claim_token,
                    lease_expires_at.isoformat(),
                    next_attempt,
                    now.isoformat(),
                    project_id,
                    idempotency_key,
                    chunk_index,
                ),
            )
            connection.commit()
        return claim_token

    def _renew_chunk_lease(
        self, project_id: str, idempotency_key: str, chunk_index: int,
        claim_token: str,
    ) -> bool:
        """Renew the lease on a claimed chunk. Returns True if renewed."""
        now = datetime.now(timezone.utc)
        lease_expires_at = now + timedelta(seconds=self.chunk_lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE medical_writing_synopsis_import_chunks
                SET lease_expires_at = ?
                WHERE project_id = ? AND idempotency_key = ? AND chunk_index = ?
                  AND status = 'running' AND claim_token = ?
                """,
                (lease_expires_at.isoformat(), project_id, idempotency_key, chunk_index, claim_token),
            )
            if cursor.rowcount > 0:
                connection.execute(
                    """
                    UPDATE medical_writing_synopsis_imports
                    SET updated_at = ?
                    WHERE project_id = ? AND idempotency_key = ?
                      AND status NOT IN ('cancelled', 'completed', 'failed')
                    """,
                    (now.isoformat(), project_id, idempotency_key),
                )
            connection.commit()
            return cursor.rowcount > 0

    def _start_chunk_heartbeat(
        self, project_id: str, idempotency_key: str, chunk_index: int,
        claim_token: str,
    ) -> tuple[threading.Event, threading.Thread]:
        """Start a heartbeat thread that renews the chunk lease periodically."""
        stop_event = threading.Event()

        def renew_loop() -> None:
            while (
                not self._shutdown_requested
                and not stop_event.wait(self.heartbeat_interval_seconds)
            ):
                try:
                    if not self._renew_chunk_lease(
                        project_id, idempotency_key, chunk_index, claim_token
                    ):
                        break  # lost ownership
                except sqlite3.Error:
                    continue

        thread = threading.Thread(
            target=renew_loop,
            name=f"synopsis-heartbeat-{idempotency_key[:8]}-{chunk_index}",
            daemon=True,
        )
        thread.start()
        return stop_event, thread

    def _fail_chunk(
        self, project_id: str, idempotency_key: str, chunk_index: int,
        error_message: str, claim_token: str,
    ) -> bool:
        """CAS fail: only succeeds if claim_token still owns the running chunk."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE medical_writing_synopsis_import_chunks
                SET status = 'failed', validation_error = ?,
                    finished_at = ?, lease_expires_at = '', claim_token = ''
                WHERE project_id = ? AND idempotency_key = ? AND chunk_index = ?
                  AND status = 'running' AND claim_token = ?
                """,
                (error_message[:4000], now, project_id, idempotency_key, chunk_index, claim_token),
            )
            connection.commit()
            return cursor.rowcount > 0

    def _complete_chunk(
        self, project_id: str, idempotency_key: str, chunk_index: int,
        output_json: str, output_hash: str, evidence_ids: list[str],
        provider: str, model_name: str, ai_run_id: str,
        actual_response_model: str, route_identity_hash: str, claim_token: str,
    ) -> bool:
        """CAS complete: only succeeds if claim_token still owns the running chunk."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE medical_writing_synopsis_import_chunks
                SET status = 'done', output_json = ?, provider_output_hash = ?,
                    evidence_span_ids_json = ?, provider = ?, model_name = ?,
                    ai_run_id = ?, actual_response_model = ?, route_identity_hash = ?,
                    finished_at = ?, lease_expires_at = '', claim_token = '',
                    validation_error = ''
                WHERE project_id = ? AND idempotency_key = ? AND chunk_index = ?
                  AND status = 'running' AND claim_token = ?
                """,
                (
                    output_json, output_hash,
                    json.dumps(evidence_ids, ensure_ascii=False),
                    provider, model_name, ai_run_id, actual_response_model,
                    route_identity_hash, now,
                    project_id, idempotency_key, chunk_index, claim_token,
                ),
            )
            connection.commit()
            return cursor.rowcount > 0

    def _run_chunked_worker(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        source_id: str,
        source: MedicalWritingSynopsisSource,
        actor: str,
        expected_indication: str,
        route_identity_hash: str,
    ) -> None:
        """Background worker: process each pending chunk via direct product AI,
        then deterministically merge all chunk outputs and persist the final
        result. Detaches (without merge/fail) if another worker owns a chunk."""
        active_chunk_index: int | None = None
        active_claim_token: str | None = None
        try:
            with self._connect() as connection:
                job = connection.execute(
                    """
                    SELECT chunk_total, route_identity_hash
                    FROM medical_writing_synopsis_imports
                    WHERE project_id = ? AND idempotency_key = ?
                    """,
                    (project_id, idempotency_key),
                ).fetchone()
            if job is None:
                return
            if job["route_identity_hash"] != route_identity_hash:
                raise RuntimeError("worker route identity differs from frozen parent route")
            chunk_total = int(job["chunk_total"])
            if chunk_total <= 0:
                chunk_total = 1

            for chunk_idx in range(chunk_total):
                if self._shutdown_requested or self._is_cancelled(project_id, idempotency_key):
                    return

                # Skip already-completed chunks.
                with self._connect() as connection:
                    existing = connection.execute(
                        "SELECT status FROM medical_writing_synopsis_import_chunks "
                        "WHERE project_id = ? AND idempotency_key = ? AND chunk_index = ?",
                        (project_id, idempotency_key, chunk_idx),
                    ).fetchone()
                if existing and existing["status"] == "done":
                    self._sync_progress(project_id, idempotency_key, chunk_total)
                    continue

                # Claim this chunk.
                claim_token = self._claim_chunk(project_id, idempotency_key, chunk_idx)
                if claim_token is None:
                    # Another worker owns it or it's done. Detach — let owner finish.
                    return
                active_chunk_index = chunk_idx
                active_claim_token = claim_token

                # Read chunk sources.
                with self._connect() as connection:
                    chunk_row = connection.execute(
                        "SELECT chunk_sources_json, route_identity_hash FROM medical_writing_synopsis_import_chunks "
                        "WHERE project_id = ? AND idempotency_key = ? AND chunk_index = ?",
                        (project_id, idempotency_key, chunk_idx),
                    ).fetchone()
                if chunk_row is None:
                    if self._fail_chunk(
                        project_id,
                        idempotency_key,
                        chunk_idx,
                        "claimed chunk source payload is missing",
                        claim_token,
                    ):
                        self._fail_job(
                            project_id=project_id,
                            idempotency_key=idempotency_key,
                            error_message=f"chunk {chunk_idx}: source payload is missing",
                        )
                    return
                if chunk_row["route_identity_hash"] != route_identity_hash:
                    raise RuntimeError(
                        f"chunk {chunk_idx} route identity differs from frozen parent route"
                    )
                chunk_sources_data = json.loads(chunk_row["chunk_sources_json"])
                chunk_sources = [AiTaskSourceRef(**s) for s in chunk_sources_data]
                if not chunk_sources:
                    completed = self._complete_chunk(
                        project_id, idempotency_key, chunk_idx,
                        "{}", hashlib.sha256(b"{}").hexdigest(), [], "", "", "", "", route_identity_hash,
                        claim_token,
                    )
                    if not completed:
                        return
                    active_chunk_index = None
                    active_claim_token = None
                    self._sync_progress(project_id, idempotency_key, chunk_total)
                    continue

                self._sync_progress(project_id, idempotency_key, chunk_total)

                # Start heartbeat for long provider calls.
                hb_stop, hb_thread = self._start_chunk_heartbeat(
                    project_id, idempotency_key, chunk_idx, claim_token,
                )

                try:
                    ai_request = AiTaskRequest(
                        module="medical_writing",
                        task_type="protocol_synopsis_structuring",
                        prompt_version="protocol_synopsis_structuring_v0_9",
                        allowed_sources=chunk_sources,
                        forbidden_source_ids=[
                            "competitor_protocol",
                            "previous_ai_summary",
                            "previous_study_definition",
                        ],
                        user_instruction=_synopsis_structuring_instruction(expected_indication),
                    )
                    try:
                        self._assert_current_route_matches(route_identity_hash)
                        run = self.ai_task_runner.submit_internal(project_id, ai_request)
                        run_id, actual_response_model, provider_name = (
                            self._validate_ai_run_route(run, route_identity_hash)
                        )
                    except Exception as exc:
                        failed_by_owner = self._fail_chunk(
                            project_id, idempotency_key, chunk_idx,
                            f"{type(exc).__name__}: {exc}"[:4000], claim_token,
                        )
                        if failed_by_owner:
                            self._fail_job(
                                project_id=project_id, idempotency_key=idempotency_key,
                                error_message=f"chunk {chunk_idx} AI call failed: {exc}"[:4000],
                            )
                        return

                    if self._is_cancelled(project_id, idempotency_key):
                        return

                    status_val = getattr(run.status, "value", run.status)
                    if status_val != "completed":
                        detail = "; ".join(run.validation_errors) or run.error_message or status_val
                        failed_by_owner = self._fail_chunk(
                            project_id, idempotency_key, chunk_idx, detail[:4000], claim_token,
                        )
                        if failed_by_owner:
                            self._fail_job(
                                project_id=project_id, idempotency_key=idempotency_key,
                                error_message=f"chunk {chunk_idx} validation failed: {detail}"[:4000],
                            )
                        return

                    provider_payload = next(
                        (a.payload for a in run.artifacts if a.artifact_type == "provider_output"),
                        None,
                    )
                    if not isinstance(provider_payload, dict):
                        failed_by_owner = self._fail_chunk(
                            project_id, idempotency_key, chunk_idx,
                            "missing provider_output", claim_token,
                        )
                        if failed_by_owner:
                            self._fail_job(
                                project_id=project_id, idempotency_key=idempotency_key,
                                error_message=f"chunk {chunk_idx}: missing provider output",
                            )
                        return

                    output_json = json.dumps(provider_payload, ensure_ascii=False)
                    output_hash = hashlib.sha256(output_json.encode("utf-8")).hexdigest()
                    evidence_ids = [
                        str(item.get("span_id", ""))
                        for item in provider_payload.get("evidence_spans", [])
                        if isinstance(item, dict)
                    ]
                    model_name = getattr(run, "model_name", "") or ""
                    if not actual_response_model:
                        raise RuntimeError("AiTaskRun.actual_response_model is missing")

                    # CAS complete — if claim was lost, detach.
                    if not self._complete_chunk(
                        project_id, idempotency_key, chunk_idx,
                        output_json, output_hash, evidence_ids,
                        provider_name, model_name, run_id, actual_response_model,
                        route_identity_hash, claim_token,
                    ):
                        return  # lost ownership to recovery; let new owner finish

                    active_chunk_index = None
                    active_claim_token = None
                    self._sync_progress(project_id, idempotency_key, chunk_total)
                finally:
                    hb_stop.set()
                    hb_thread.join(timeout=2.0)

            # Readiness check: exactly chunk_total contiguous done indices.
            if not self._all_chunks_done(project_id, idempotency_key, chunk_total):
                return  # not all done — another worker may still be running

            if self._is_cancelled(project_id, idempotency_key):
                return

            self._sync_progress(project_id, idempotency_key, chunk_total, phase="validating")

            merged_result = self._merge_chunks(
                project_id=project_id,
                idempotency_key=idempotency_key,
                source_id=source_id,
                source=source,
                expected_indication=expected_indication,
                chunk_total=chunk_total,
            )
            if self._is_cancelled(project_id, idempotency_key):
                return

            self._complete_job(
                project_id=project_id,
                idempotency_key=idempotency_key,
                result=merged_result,
                chunk_total=chunk_total,
            )
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"[:4000]
            if active_claim_token is not None and active_chunk_index is not None:
                if self._fail_chunk(
                    project_id,
                    idempotency_key,
                    active_chunk_index,
                    error_message,
                    active_claim_token,
                ):
                    self._fail_job(
                        project_id=project_id,
                        idempotency_key=idempotency_key,
                        error_message=error_message,
                    )
            else:
                self._fail_job(
                    project_id=project_id,
                    idempotency_key=idempotency_key,
                    error_message=error_message,
                )

    def _all_chunks_done(
        self, project_id: str, idempotency_key: str, chunk_total: int
    ) -> bool:
        """Verify exactly chunk_total contiguous done chunks, none pending/running/failed."""
        with self._connect() as connection:
            parent = connection.execute(
                "SELECT route_identity_hash FROM medical_writing_synopsis_imports "
                "WHERE project_id = ? AND idempotency_key = ?",
                (project_id, idempotency_key),
            ).fetchone()
            rows = connection.execute(
                "SELECT chunk_index, status, route_identity_hash "
                "FROM medical_writing_synopsis_import_chunks "
                "WHERE project_id = ? AND idempotency_key = ? ORDER BY chunk_index",
                (project_id, idempotency_key),
            ).fetchall()
        parent_hash = str(parent["route_identity_hash"] or "") if parent else ""
        if not parent_hash or any(row["route_identity_hash"] != parent_hash for row in rows):
            raise RuntimeError("chunk route identities are missing or mixed before merge")
        if len(rows) != chunk_total:
            return False
        for idx, row in enumerate(rows):
            if row["chunk_index"] != idx or row["status"] != "done":
                return False
        return True

    def _sync_progress(
        self, project_id: str, idempotency_key: str, chunk_total: int,
        *, phase: str = "ai_synthesis",
    ) -> bool:
        """Derive progress monotonically from committed done-chunk count."""
        with self._connect() as connection:
            done_count = connection.execute(
                "SELECT COUNT(*) as cnt FROM medical_writing_synopsis_import_chunks "
                "WHERE project_id = ? AND idempotency_key = ? AND status = 'done'",
                (project_id, idempotency_key),
            ).fetchone()["cnt"]
            current_idx = connection.execute(
                "SELECT chunk_index FROM medical_writing_synopsis_imports "
                "WHERE project_id = ? AND idempotency_key = ?",
                (project_id, idempotency_key),
            ).fetchone()
        # Only write if the new done_count is >= current (monotonic).
        current_chunk_index = int(current_idx["chunk_index"]) if current_idx else 0
        effective_index = max(done_count, current_chunk_index)
        now = datetime.now(timezone.utc).isoformat()
        progress = SynopsisImportJobProgress(
            phase=phase,
            chunk_index=effective_index,
            chunk_total=chunk_total,
            provider_status="streaming" if phase == "ai_synthesis" else "done",
        ).model_dump(mode="json")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET phase = ?, chunk_index = ?, chunk_total = ?,
                    progress_json = ?, updated_at = ?
                WHERE project_id = ? AND idempotency_key = ?
                  AND status NOT IN ('cancelled', 'completed')
                  AND chunk_index <= ?
                """,
                (phase, effective_index, chunk_total,
                 json.dumps(progress, ensure_ascii=False),
                 now, project_id, idempotency_key, effective_index),
            )
            connection.commit()

    def _merge_chunks(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        source_id: str,
        source: MedicalWritingSynopsisSource,
        expected_indication: str,
        chunk_total: int,
    ) -> MedicalWritingSynopsisImport:
        """Deterministically merge all completed chunk outputs. Requires exactly
        chunk_total contiguous done indices (caller must verify)."""
        with self._connect() as connection:
            parent = connection.execute(
                "SELECT route_identity_hash FROM medical_writing_synopsis_imports "
                "WHERE project_id = ? AND idempotency_key = ?",
                (project_id, idempotency_key),
            ).fetchone()
            chunk_rows = connection.execute(
                "SELECT chunk_index, output_json, route_identity_hash "
                "FROM medical_writing_synopsis_import_chunks "
                "WHERE project_id = ? AND idempotency_key = ? AND status = 'done' "
                "ORDER BY chunk_index ASC",
                (project_id, idempotency_key),
            ).fetchall()
        parent_hash = str(parent["route_identity_hash"] or "") if parent else ""
        if not parent_hash or any(row["route_identity_hash"] != parent_hash for row in chunk_rows):
            raise RuntimeError("chunk route identities are missing or mixed before merge")
        if len(chunk_rows) != chunk_total:
            raise RuntimeError(
                f"merge requires {chunk_total} done chunks, got {len(chunk_rows)}"
            )

        merged_study_definition: dict[str, Any] = {"framing": {}, "picos": {}}
        merged_evidence: list[dict[str, Any]] = []
        merged_field_evidence: dict[str, list[str]] = {}
        merged_missing_fields: list[str] = []
        merged_conflict_notes: list[str] = []
        seen_evidence_keys: set[tuple[str, str, str]] = set()
        merged_synopsis_parts: list[str] = []

        for row in chunk_rows:
            try:
                output = json.loads(row["output_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(output, dict):
                continue
            sd = output.get("study_definition", {})
            if not isinstance(sd, dict):
                continue

            framing = sd.get("framing", {})
            if isinstance(framing, dict):
                for key, val in framing.items():
                    if key not in merged_study_definition["framing"]:
                        merged_study_definition["framing"][key] = val
                    elif merged_study_definition["framing"][key] != val:
                        merged_conflict_notes.append(
                            f"framing.{key}: chunk conflict — first value retained"
                        )

            picos = sd.get("picos", {})
            if isinstance(picos, dict):
                for key, val in picos.items():
                    if isinstance(val, list):
                        existing = merged_study_definition["picos"].setdefault(key, [])
                        for item in val:
                            canonical = _canonical_text(item)
                            if canonical not in {_canonical_text(e) for e in existing}:
                                existing.append(item)
                    elif key not in merged_study_definition["picos"]:
                        merged_study_definition["picos"][key] = val
                    elif merged_study_definition["picos"][key] != val:
                        merged_conflict_notes.append(
                            f"picos.{key}: chunk conflict — first value retained"
                        )

            for span in output.get("evidence_spans", []):
                if not isinstance(span, dict):
                    continue
                key = (
                    str(span.get("source_id", "")),
                    str(span.get("locator", "")),
                    _canonical_text(span.get("quote", "")),
                )
                if key not in seen_evidence_keys:
                    seen_evidence_keys.add(key)
                    merged_evidence.append(span)

            fe = sd.get("field_evidence_span_ids", {})
            if isinstance(fe, dict):
                for field, ids in fe.items():
                    if isinstance(ids, list):
                        existing = merged_field_evidence.setdefault(str(field), [])
                        for eid in ids:
                            if str(eid) not in existing:
                                existing.append(str(eid))

            for mf in sd.get("missing_fields", []):
                if str(mf) not in merged_missing_fields:
                    merged_missing_fields.append(str(mf))
            for cn in sd.get("conflict_notes", []):
                if str(cn) not in merged_conflict_notes:
                    merged_conflict_notes.append(str(cn))

            synopsis_text = sd.get("synopsis_text", "")
            if synopsis_text and synopsis_text not in merged_synopsis_parts:
                merged_synopsis_parts.append(synopsis_text)

        merged_study_definition["synopsis_text"] = "\n".join(merged_synopsis_parts)
        merged_study_definition["missing_fields"] = merged_missing_fields
        merged_study_definition["conflict_notes"] = merged_conflict_notes
        merged_study_definition["field_evidence_span_ids"] = merged_field_evidence

        # Re-apply deterministic normalization after cross-chunk merge. A
        # completed chunk may have been produced by an older runner revision,
        # and merge must not reintroduce unresolved typed design fields.
        # Failures must propagate — no broad exception swallowing.
        from .ai_gateway import AiTaskType
        from .ai_task_runner import (
            bind_protocol_synopsis_source_quotes,
            materialize_anchored_synopsis_fields,
            materialize_protocol_synopsis_structured_design,
            normalize_protocol_synopsis_design_enums,
        )
        all_ai_sources: list[AiTaskSourceRef] = []
        with self._connect() as connection:
            for crow in connection.execute(
                "SELECT chunk_sources_json FROM medical_writing_synopsis_import_chunks "
                "WHERE project_id = ? AND idempotency_key = ? ORDER BY chunk_index ASC",
                (project_id, idempotency_key),
            ).fetchall():
                for s in json.loads(crow["chunk_sources_json"]):
                    all_ai_sources.append(AiTaskSourceRef(**s))
        merged_output = {"study_definition": merged_study_definition, "evidence_spans": merged_evidence}
        merged_output = normalize_protocol_synopsis_design_enums(merged_output)
        merged_output = materialize_protocol_synopsis_structured_design(merged_output)
        merged_output = materialize_anchored_synopsis_fields(merged_output, all_ai_sources)
        merged_output = bind_protocol_synopsis_source_quotes(
            AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
            merged_output,
            all_ai_sources,
        )
        merged_study_definition = merged_output["study_definition"]
        merged_evidence = merged_output.get("evidence_spans", merged_evidence)
        merged_field_evidence = dict(
            merged_study_definition.get("field_evidence_span_ids") or {}
        )

        # Cross-chunk merge is a separate trust boundary from each completed
        # chunk. Re-check evidence identity and literal source membership after
        # deterministic materialization and exact-quote rebinding.
        source_by_id = {source.source_id: source for source in all_ai_sources}
        seen_span_ids: set[str] = set()
        evidence_errors: list[str] = []
        for span in merged_evidence:
            span_id = str(span.get("span_id") or "")
            source_id = str(span.get("source_id") or "")
            if not span_id:
                evidence_errors.append("merged evidence span_id is required")
            elif span_id in seen_span_ids:
                evidence_errors.append(f"duplicate evidence span_id: {span_id}")
            seen_span_ids.add(span_id)
            ai_source = source_by_id.get(source_id)
            if ai_source is None:
                evidence_errors.append(
                    f"merged evidence references unknown source_id: {source_id}"
                )
                continue
            if str(span.get("locator") or "") != str(ai_source.locator):
                evidence_errors.append(
                    f"merged evidence locator mismatch for {source_id}"
                )
            compact_quote = re.sub(r"\s+", " ", str(span.get("quote") or "")).strip()
            compact_source = re.sub(
                r"\s+", " ", str(ai_source.text_preview or "")
            ).strip()
            if not compact_quote or compact_quote not in compact_source:
                evidence_errors.append(
                    f"merged evidence quote is not present in source {source_id}"
                )
        if evidence_errors:
            raise RuntimeError(
                "merged output failed evidence validation: "
                + "; ".join(evidence_errors[:3])
            )

        # Run strict field-level source-fidelity validation on the merged result.
        from .ai_task_runner import validate_protocol_synopsis_source_fidelity
        fidelity_errors = validate_protocol_synopsis_source_fidelity(merged_output, all_ai_sources)
        if fidelity_errors:
            raise RuntimeError(
                "merged output failed source-fidelity validation: "
                + "; ".join(fidelity_errors[:3])
            )

        picos_payload = _sanitize_synopsis_instrument_candidates(
            merged_study_definition.get("picos"), source_id=source_id
        )
        framing = MedicalWritingStudyFraming.model_validate(
            merged_study_definition["framing"]
        )
        picos = MedicalWritingPicosDefinition.model_validate(picos_payload)
        evidence_spans = [
            MedicalWritingSynopsisEvidenceSpan(
                span_id=item["span_id"],
                source_id=item["source_id"],
                locator=item["locator"],
                source_text=item["quote"],
                source_text_sha256=hashlib.sha256(
                    item["quote"].encode("utf-8")
                ).hexdigest(),
            )
            for item in merged_evidence
        ]
        picos = _bind_synopsis_instrument_sources(
            picos,
            source=source,
            field_evidence_span_ids=merged_field_evidence,
            evidence_spans=evidence_spans,
        )
        return MedicalWritingSynopsisImport(
            status="review_pending",
            source=source,
            proposed_framing=framing,
            proposed_picos=picos,
            proposed_synopsis_text=merged_study_definition.get("synopsis_text", ""),
            missing_fields=merged_missing_fields,
            conflict_notes=merged_conflict_notes,
            field_evidence_span_ids=merged_field_evidence,
            evidence_spans=evidence_spans,
            ai_run_id=f"merged_{idempotency_key[:16]}",
        )

    def recover_stale_jobs(self) -> int:
        """Cold-recovery: detect incomplete jobs with expired leases, reset
        their stale chunks, and re-spawn workers. Done chunks are never
        replayed. Source is reconstructed from persisted source_json."""
        now = datetime.now(timezone.utc)
        requeued = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE medical_writing_synopsis_import_chunks
                SET status = 'pending', lease_expires_at = '', claim_token = ''
                WHERE status = 'running'
                  AND lease_expires_at != ''
                  AND lease_expires_at <= ?
                """,
                (now.isoformat(),),
            )
            stale_jobs = connection.execute(
                """
                SELECT DISTINCT i.project_id, i.idempotency_key, i.job_id,
                       i.expected_indication, i.actor
                FROM medical_writing_synopsis_imports i
                INNER JOIN medical_writing_synopsis_import_chunks c
                  ON i.project_id = c.project_id
                 AND i.idempotency_key = c.idempotency_key
                WHERE i.status NOT IN ('completed', 'cancelled', 'failed')
                  AND c.status IN ('pending', 'running', 'failed')
                """,
            ).fetchall()
            for row in stale_jobs:
                connection.execute(
                    """
                    UPDATE medical_writing_synopsis_imports
                    SET phase = 'recoverable', updated_at = ?
                    WHERE project_id = ? AND idempotency_key = ?
                      AND status NOT IN ('completed', 'cancelled', 'failed')
                    """,
                    (now.isoformat(), row["project_id"], row["idempotency_key"]),
                )
            connection.commit()

        for row in stale_jobs:
            try:
                with self._connect() as conn:
                    _, route_identity_hash = self._load_frozen_route(
                        conn, row["project_id"], row["idempotency_key"]
                    )
                    source = self._load_source_from_db(
                        conn, row["project_id"], row["idempotency_key"]
                    )
                # Recovery verifies the current configuration but never uses it
                # to construct a replacement route.
                self._assert_current_route_matches(route_identity_hash)
            except (
                KeyError,
                RuntimeError,
                TypeError,
                ValueError,
                sqlite3.Error,
                ValidationError,
            ) as exc:
                self._fail_job(
                    project_id=row["project_id"],
                    idempotency_key=row["idempotency_key"],
                    error_message=f"cold recovery blocked; retry is not allowed: {exc}"[:4000],
                )
                continue
            self._spawn_chunked_worker(
                project_id=row["project_id"],
                idempotency_key=row["idempotency_key"],
                source_id=source.source_id,
                source=source,
                actor=row["actor"] or "system",
                expected_indication=row["expected_indication"] or "",
                route_identity_hash=route_identity_hash,
            )
            requeued += 1
        return requeued

    def _complete_job(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        result: MedicalWritingSynopsisImport,
        chunk_total: int,
    ) -> None:
        """Set status='completed', phase='review_ready', and persist the final
        merged result."""
        now = datetime.now(timezone.utc).isoformat()
        progress = SynopsisImportJobProgress(
            phase="review_ready",
            chunk_total=chunk_total,
            chunk_index=chunk_total,
            provider_status="done",
        ).model_dump(mode="json")
        result_json = result.model_dump_json()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            chunk_rows = connection.execute(
                "SELECT chunk_index, status FROM medical_writing_synopsis_import_chunks "
                "WHERE project_id = ? AND idempotency_key = ? ORDER BY chunk_index",
                (project_id, idempotency_key),
            ).fetchall()
            if (
                len(chunk_rows) != chunk_total
                or any(
                    row["chunk_index"] != index or row["status"] != "done"
                    for index, row in enumerate(chunk_rows)
                )
            ):
                connection.rollback()
                return False
            cursor = connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET status = 'completed', phase = 'review_ready',
                    result_json = ?, payload_json = ?,
                    progress_json = ?, chunk_index = ?,
                    error_message = '', updated_at = ?
                WHERE project_id = ? AND idempotency_key = ?
                  AND status NOT IN ('cancelled', 'completed', 'failed')
                """,
                (
                    result_json,
                    result_json,
                    json.dumps(progress, ensure_ascii=False),
                    chunk_total,
                    now,
                    project_id,
                    idempotency_key,
                ),
            )
            connection.commit()
            return cursor.rowcount > 0

    def _fail_job(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        error_message: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        progress = SynopsisImportJobProgress(
            phase="failed",
            provider_status="failed",
            error_message=error_message,
        ).model_dump(mode="json")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET status = 'failed', phase = 'failed',
                    progress_json = ?, error_message = ?, updated_at = ?
                WHERE project_id = ? AND idempotency_key = ?
                  AND status NOT IN ('cancelled', 'completed')
                """,
                (
                    json.dumps(progress, ensure_ascii=False),
                    error_message,
                    now,
                    project_id,
                    idempotency_key,
                ),
            )
            connection.commit()

    def _update_job_phase(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        phase: str,
        status: str,
        chunk_index: int = 0,
        chunk_total: int = 0,
        progress: Any = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        progress_json = (
            json.dumps(progress, ensure_ascii=False)
            if isinstance(progress, dict)
            else ""
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET phase = ?, status = ?, chunk_index = ?, chunk_total = ?,
                    progress_json = CASE WHEN ? != '' THEN ? ELSE progress_json END,
                    updated_at = ?
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (
                    phase,
                    status,
                    chunk_index,
                    chunk_total,
                    progress_json,
                    progress_json,
                    now,
                    project_id,
                    idempotency_key,
                ),
            )
            connection.commit()

    def _build_start_response(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        job_id: str,
        content_sha256: str,
        media_type: str,
        filename: str,
    ) -> SynopsisImportJobStartResponse:
        return SynopsisImportJobStartResponse(
            job_id=job_id,
            idempotency_key=idempotency_key,
            status="reused",
            phase="reused",
            content_sha256=content_sha256,
            span_count=0,
            media_type=media_type,
            warnings=[],
        )

    def get_job(
        self, project_id: str, idempotency_key: str
    ) -> SynopsisImportJobStatusResponse:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT status, phase, chunk_index, chunk_total, progress_json,
                       source_sha256, source_filename, error_message, cancelled_at,
                       result_json, payload_json, job_id, created_at, updated_at
                FROM medical_writing_synopsis_imports
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
        if row is None:
            raise KeyError(f"synopsis import job not found: {idempotency_key}")
        progress = {}
        if row["progress_json"]:
            try:
                progress = json.loads(row["progress_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        cancellation_state = "cancelled" if row["cancelled_at"] else "none"
        raw_status = row["status"] or ""
        raw_phase = row["phase"] or raw_status
        if cancellation_state == "cancelled":
            public_status = "cancelled"
            public_phase = "cancelled"
        elif raw_status == "completed" or raw_phase == "review_ready":
            public_status = "review_ready"
            public_phase = "review_ready"
        elif raw_status == "failed":
            public_status = "failed"
            public_phase = "failed"
        else:
            public_status = raw_phase or "pending"
            public_phase = raw_phase or "pending"
        result_ref = None
        if (row["result_json"] or row["payload_json"]) and public_status == "review_ready":
            result_ref = idempotency_key
        now = datetime.now(timezone.utc)
        started_at = _parse_datetime(row["created_at"])
        heartbeat_at = _parse_datetime(row["updated_at"])
        return SynopsisImportJobStatusResponse(
            job_id=row["job_id"] or idempotency_key,
            status=public_status,
            phase=public_phase,
            chunk_index=row["chunk_index"],
            chunk_total=row["chunk_total"],
            provider_status=progress.get("provider_status", "queued"),
            content_sha256=row["source_sha256"] or "",
            source_filename=row["source_filename"] or "",
            warnings=[],
            cancellation_state=cancellation_state,
            error_message=row["error_message"] or "",
            repair_count=progress.get("repair_count", 0),
            anchor_count=progress.get("anchor_count", 0),
            result_ref=result_ref,
            started_at=started_at,
            heartbeat_at=heartbeat_at,
            elapsed_seconds=(
                max(0, int((now - started_at).total_seconds()))
                if started_at is not None
                else 0
            ),
            heartbeat_age_seconds=(
                max(0, int((now - heartbeat_at).total_seconds()))
                if heartbeat_at is not None
                else 0
            ),
        )

    def latest_job_for_source(
        self,
        project_id: str,
        source_sha256: str,
    ) -> str:
        """Return the latest durable job for the current immutable source."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT idempotency_key
                FROM medical_writing_synopsis_imports
                WHERE project_id = ?
                  AND source_sha256 = ?
                  AND cancelled_at = ''
                  AND status IN ('pending', 'processing', 'completed', 'failed')
                ORDER BY created_at DESC, updated_at DESC, idempotency_key DESC
                LIMIT 1
                """,
                (project_id, source_sha256),
            ).fetchone()
        return str(row["idempotency_key"]) if row is not None else ""

    def get_job_result(
        self, project_id: str, idempotency_key: str
    ) -> MedicalWritingSynopsisImport:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT status, result_json, payload_json
                FROM medical_writing_synopsis_imports
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
        if row is None:
            raise KeyError(f"synopsis import job not found: {idempotency_key}")
        if row["status"] != "completed":
            raise RuntimeError(
                f"synopsis import job result not ready: status={row['status']}"
            )
        # The existing _complete_claim stores result in payload_json.
        result_text = row["result_json"] or row["payload_json"]
        if not result_text:
            raise RuntimeError("synopsis import job result payload is empty")
        result = MedicalWritingSynopsisImport.model_validate_json(result_text)
        upgraded = self._upgrade_completed_result(result)
        upgraded_text = upgraded.model_dump_json()
        if upgraded_text != result.model_dump_json():
            now = datetime.now(timezone.utc).isoformat()
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    UPDATE medical_writing_synopsis_imports
                    SET result_json = ?, payload_json = ?, updated_at = ?
                    WHERE project_id = ? AND idempotency_key = ?
                      AND status = 'completed'
                    """,
                    (
                        upgraded_text,
                        upgraded_text,
                        now,
                        project_id,
                        idempotency_key,
                    ),
                )
                connection.commit()
        return upgraded

    @staticmethod
    def _upgrade_completed_result(
        result: MedicalWritingSynopsisImport,
    ) -> MedicalWritingSynopsisImport:
        """Apply deterministic schema projections to earlier completed jobs.

        This migration does not call AI or add external facts. It only projects
        source-bound framing/PICOS values already present in the completed
        result, making old and newly merged jobs obey the same typed contract.
        """
        from .ai_task_runner import (
            materialize_protocol_synopsis_structured_design,
            normalize_protocol_synopsis_design_enums,
        )

        output = {
            "study_definition": {
                "framing": result.proposed_framing.model_dump(mode="json"),
                "picos": result.proposed_picos.model_dump(mode="json"),
                "synopsis_text": result.proposed_synopsis_text,
                "missing_fields": list(result.missing_fields),
                "conflict_notes": list(result.conflict_notes),
                "field_evidence_span_ids": {
                    key: list(value)
                    for key, value in result.field_evidence_span_ids.items()
                },
            },
            "evidence_spans": [
                {
                    "span_id": span.span_id,
                    "source_id": span.source_id,
                    "locator": span.locator,
                    "quote": span.source_text,
                }
                for span in result.evidence_spans
            ],
        }
        normalized = normalize_protocol_synopsis_design_enums(output)
        normalized = materialize_protocol_synopsis_structured_design(normalized)
        definition = normalized["study_definition"]
        framing = MedicalWritingStudyFraming.model_validate(definition["framing"])
        picos = MedicalWritingPicosDefinition.model_validate(definition["picos"])
        field_evidence = {
            str(key): list(value)
            for key, value in definition["field_evidence_span_ids"].items()
        }
        if (
            framing == result.proposed_framing
            and picos == result.proposed_picos
            and field_evidence == result.field_evidence_span_ids
        ):
            return result
        return result.model_copy(
            update={
                "proposed_framing": framing,
                "proposed_picos": picos,
                "field_evidence_span_ids": field_evidence,
            }
        )

    def cancel_job(
        self, project_id: str, idempotency_key: str
    ) -> SynopsisImportJobCancelResponse:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, cancelled_at, chunk_index, job_id
                FROM medical_writing_synopsis_imports
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(f"synopsis import job not found: {idempotency_key}")
            already_cancelled = bool(row["cancelled_at"])
            if not already_cancelled:
                connection.execute(
                    """
                    UPDATE medical_writing_synopsis_imports
                    SET cancelled_at = ?, status = 'cancelled', phase = 'cancelled',
                        updated_at = ?
                    WHERE project_id = ? AND idempotency_key = ?
                      AND status NOT IN ('completed', 'cancelled')
                    """,
                    (now, now, project_id, idempotency_key),
                )
            # Flatten partial evidence IDs from done chunks.
            raw_evidence = [
                r["evidence_span_ids_json"]
                for r in connection.execute(
                    """
                    SELECT evidence_span_ids_json
                    FROM medical_writing_synopsis_import_chunks
                    WHERE project_id = ? AND idempotency_key = ?
                      AND status = 'done'
                    """,
                    (project_id, idempotency_key),
                ).fetchall()
            ]
            done_chunks = connection.execute(
                """
                SELECT COUNT(*) as cnt
                FROM medical_writing_synopsis_import_chunks
                WHERE project_id = ? AND idempotency_key = ?
                  AND status = 'done'
                """,
                (project_id, idempotency_key),
            ).fetchone()
            connection.commit()
        # Flatten JSON lists into a single list of IDs.
        flat_evidence: list[str] = []
        for raw in raw_evidence:
            try:
                ids = json.loads(raw)
                if isinstance(ids, list):
                    flat_evidence.extend(str(eid) for eid in ids if str(eid))
            except (json.JSONDecodeError, TypeError):
                pass
        # Deduplicate preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for eid in flat_evidence:
            if eid not in seen:
                seen.add(eid)
                deduped.append(eid)
        return SynopsisImportJobCancelResponse(
            job_id=(row["job_id"] if row and row["job_id"] else idempotency_key),
            status="cancelled",
            cancellation_state="cancelled",
            last_completed_chunk=done_chunks["cnt"] if done_chunks else -1,
            partial_evidence_span_ids=deduped,
        )

    def resume_job(
        self, project_id: str, idempotency_key: str, *, actor: str
    ) -> SynopsisImportJobStatusResponse:
        """Re-enter from RECOVERABLE/FAILED: re-spawn the chunked worker which
        will skip already-completed chunks and only process pending/failed ones."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, source_sha256, source_filename, media_type,
                       expected_indication, chunk_total
                FROM medical_writing_synopsis_imports
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(f"synopsis import job not found: {idempotency_key}")
            if row["status"] not in ("recoverable", "failed"):
                connection.commit()
                return self.get_job(project_id, idempotency_key)
            try:
                _, route_identity_hash = self._load_frozen_route(
                    connection, project_id, idempotency_key
                )
            except RuntimeError:
                connection.rollback()
                raise
            connection.commit()
        self._assert_current_route_matches(route_identity_hash)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Reset failed chunks to pending so the worker will retry them.
            connection.execute(
                """
                UPDATE medical_writing_synopsis_import_chunks
                SET status = 'pending', lease_expires_at = '', claim_token = '',
                    validation_error = '', attempt_count = attempt_count + 1
                WHERE project_id = ? AND idempotency_key = ?
                  AND status = 'failed'
                """,
                (project_id, idempotency_key),
            )
            # Mark job as recoverable for re-processing.
            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET status = 'pending', phase = 'recoverable',
                    error_message = '', updated_at = ?
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    project_id,
                    idempotency_key,
                ),
            )
            connection.commit()

        with self._connect() as conn:
            source = self._load_source_from_db(conn, project_id, idempotency_key)
        self._spawn_chunked_worker(
            project_id=project_id,
            idempotency_key=idempotency_key,
            source_id=source.source_id,
            source=source,
            actor=actor,
            expected_indication=row["expected_indication"] or "",
            route_identity_hash=route_identity_hash,
        )
        return self.get_job(project_id, idempotency_key)


def _lease_is_expired(value: str, now: datetime) -> bool:
    if not value:
        return True
    try:
        expires_at = datetime.fromisoformat(value)
    except ValueError:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= now


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _detect_media_type(
    filename: str, content_type: str, payload: bytes
) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    if payload.startswith(b"%PDF-") and suffix == ".pdf":
        return "application/pdf", ".pdf"
    if payload.startswith(b"PK") and suffix == ".docx":
        return (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".docx",
        )
    raise ValueError(
        "protocol synopsis must be an actual PDF or DOCX matching its filename extension"
    )


def _assess_source_role(source_text: str) -> tuple[str, list[str]]:
    normalized = source_text.casefold()
    synopsis_tokens = ("方案摘要", "研究摘要", "protocol synopsis", "study synopsis")
    protocol_title_tokens = ("临床试验方案", "临床研究方案", "protocol title")
    protocol_structure_tokens = (
        "试验设计",
        "研究设计",
        "入选标准",
        "排除标准",
        "评价标准",
        "统计方法",
        "schedule of activities",
    )
    publication_tokens = ("abstract", "methods", "results", "conclusion", "参考文献")
    if any(token in normalized for token in synopsis_tokens):
        return "matched", []
    if any(token in normalized for token in protocol_title_tokens) and sum(
        token in normalized for token in protocol_structure_tokens
    ) >= 2:
        return "matched", []
    if sum(token in normalized for token in publication_tokens) >= 3:
        return "mismatch", ["未识别到方案摘要结构，文件内容更接近publication。"]
    return "warning", ["未识别到明确的“方案摘要/Protocol Synopsis”标题，请确认文件角色。"]


def _assess_indication(
    source_text: str, expected_indication: str
) -> tuple[str, list[str]]:
    expected = expected_indication.strip()
    if not expected:
        return "not_assessed", []
    if re.sub(r"\s+", "", expected.casefold()) in re.sub(
        r"\s+", "", source_text.casefold()
    ):
        return "matched", []
    return "warning", [f"原文中未直接识别到当前项目适应症“{expected}”，请确认项目归属。"]


def _canonical_text(value: Any) -> str:
    """Canonicalise text for merge deduplication (strip + casefold)."""
    import unicodedata
    text = str(value or "").strip()
    return unicodedata.normalize("NFKC", text).casefold()


def _chunk_ai_sources(
    sources: list[AiTaskSourceRef], max_chars: int = MAX_SYNOPSIS_CHUNK_CHARS
) -> list[list[AiTaskSourceRef]]:
    """Group AI source refs into bounded chunks without splitting an
    individual source (each source = one table row or section span)."""
    if not sources:
        return []
    chunks: list[list[AiTaskSourceRef]] = []
    current: list[AiTaskSourceRef] = []
    current_chars = 0
    for source in sources:
        text = str(source.text_preview or "")
        source_chars = len(text)
        if current and current_chars + source_chars > max_chars:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(source)
        current_chars += source_chars
    if current:
        chunks.append(current)
    return chunks


def _ai_sources(project_id: str, source_id: str, spans: list[Any]) -> list[AiTaskSourceRef]:
    instrument_pattern = re.compile(
        r"量表|问卷|评分范围|回顾期|回忆|生活质量|患者报告结局|"
        r"\b(?:NRS|VAS|PRO|PROMIS|QoL|DLQI|CDLQI|EASI|PASI|IGA|PGA|BSA|SCORAD|"
        r"ACR\d*|DAS28|CDAI|SDAI|HAQ(?:-DI)?|FACIT|EQ-5D|SF-36|CTCAE)\b",
        re.IGNORECASE,
    )
    front_matter = list(spans[:10])
    objectives_endpoints = [
        span for span in spans if span.ich_m11_anchor == "objectives_endpoints"
    ]
    schedule = [span for span in spans if span.ich_m11_anchor == "schedule"]
    eligibility = [span for span in spans if span.ich_m11_anchor == "eligibility"]
    statistics = [span for span in spans if span.ich_m11_anchor == "statistics"]

    def span_identity(span: Any) -> tuple[str, str]:
        return (
            str(getattr(span, "source_locator", "")),
            str(getattr(span, "source_text", "")),
        )

    # Reserve one non-empty representative for every critical extraction
    # category before lower-priority buckets consume the 40-span budget.
    reserved: set[tuple[str, str]] = set()
    for bucket in (
        front_matter,
        objectives_endpoints,
        eligibility,
        statistics,
        schedule,
    ):
        for span in bucket:
            if str(getattr(span, "source_text", "") or "").strip():
                reserved.add(span_identity(span))
                break

    # Cover/front-matter spans carry the document identity. Keep them first and
    # reserve capacity for them; otherwise a long synopsis or instrument table
    # can consume the entire 40-span budget before protocol number, title, and
    # version ever reach the independent AI.
    buckets = (
        (front_matter, 10),
        ([span for span in spans if span.ich_m11_anchor == "synopsis"], 12),
        (objectives_endpoints, 8),
        ([span for span in spans if instrument_pattern.search(str(span.source_text or ""))], 8),
        (schedule, 4),
        (eligibility, 4),
        (statistics, 4),
        (list(spans[:40]), 40),
    )
    prioritized: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for bucket, limit in buckets:
        added = 0
        for span in bucket:
            identity = span_identity(span)
            if identity in seen:
                continue
            unselected_reserved = reserved - seen
            remaining_slots = MAX_AI_SOURCE_CHUNKS - len(prioritized)
            if identity not in reserved and remaining_slots <= len(unselected_reserved):
                continue
            prioritized.append(span)
            seen.add(identity)
            added += 1
            if added >= limit or len(prioritized) >= MAX_AI_SOURCE_CHUNKS:
                break
        if len(prioritized) >= MAX_AI_SOURCE_CHUNKS:
            break
    chunks: list[AiTaskSourceRef] = []
    for span in prioritized:
        text = str(span.source_text or "").strip()
        if not text:
            continue
        if len(text) > MAX_AI_SOURCE_CHARS:
            text = text[:MAX_AI_SOURCE_CHARS]
        if len(chunks) >= MAX_AI_SOURCE_CHUNKS:
            break
        index = len(chunks) + 1
        chunks.append(
            AiTaskSourceRef(
                source_id=f"{source_id}_span_{index}",
                source_type="project_protocol_synopsis",
                title=f"项目方案/摘要原文片段 {index}",
                locator=f"synopsis:{source_id}:{span.source_locator}",
                text_preview=text,
                project_id=project_id,
                module="medical_writing",
            )
        )
    if not chunks:
        raise ValueError("protocol synopsis has no AI-readable text chunks")
    return chunks


def _synopsis_structuring_instruction(expected_indication: str) -> str:
    framing_template = MedicalWritingStudyFraming().model_dump(mode="json")
    picos_template = MedicalWritingPicosDefinition().model_dump(mode="json")
    instrument_template = {
        "instrument_id": "short-stable-key",
        "canonical_name_zh": "原文中的中文名称；原文仅有英文时保留英文名称",
        "canonical_name_en": "原文中的英文全称或空字符串",
        "acronym": "原文中的缩写或空字符串",
        "version_label": "原文明示版本或空字符串",
        "instrument_kind": "other",
        "administration_mode": "原文明示的评估/填写方式或空字符串",
        "respondent": "原文明示的评估者/填写者或空字符串",
        "recall_period": "原文明示的回顾期或空字符串",
        "scoring_range": "原文明示的评分范围或空字符串",
        "scoring_direction": "原文明示的分值高低所代表的临床含义或空字符串；应答/临床意义改善阈值不得写入此字段",
        "scoring_summary": "原文明示的计分方法、应答定义或临床意义改善阈值摘要或空字符串",
        "study_purpose": "本研究中原文明示的用途",
        "endpoint_paths": [],
        "visit_labels": [],
        "soa_activity_ids": [],
        "appendix_locator": "原文明示的附件定位或空字符串",
        "protocol_modified": False,
        "source_synopsis_only": True,
        "evidence_span_ids": [],
        "source_bindings": [],
        "rights": MedicalWritingInstrumentRightsState().model_dump(mode="json"),
        "translation": MedicalWritingInstrumentTranslationState().model_dump(mode="json"),
        "confirmation_status": "candidate",
        "confirmed_by": "",
        "confirmed_at": None,
        "notes": "",
    }
    return (
        "从项目方案摘要原文提取研究定义候选。framing和picos必须逐键复制以下JSON模板，"
        "保留全部键、值类型和默认值；仅用原文明确支持的内容替换对应默认值，不得猜测，"
        "不得把字符串写成数组或把数组写成字符串。"
        f"\nframing_template={json.dumps(framing_template, ensure_ascii=False, separators=(',', ':'))}"
        f"\npicos_template={json.dumps(picos_template, ensure_ascii=False, separators=(',', ':'))}"
        f"\nassessment_instrument_item_template={json.dumps(instrument_template, ensure_ascii=False, separators=(',', ':'))}"
        f"\ncurrent_project_indication={expected_indication or '未预置'}"
        "\nfield_evidence_span_ids的键使用framing.<field>或picos.<field>。"
        "不得为没有证据的字段生成空数组映射；任何不同于模板默认值的候选都必须绑定至少一个来源证据。"
        "结构化抽取不是摘要改写：每个字段必须保留原文陈述的全部事实从句、限定条件、时间点、人群、"
        "剂量或组别、终点定义以及目的/依据，不得用更短的概括句替代。表格同一行的不同单元格必须按"
        "字段语义分别抽取，但不得丢弃任一单元格中的实质内容。方案正文中的主要、次要、探索性研究目的"
        "必须分别写入picos.primary_objectives、picos.secondary_objectives、"
        "picos.exploratory_objectives；framing.intrinsic_objectives仅用于FIH、PoC、PoM、"
        "剂量探索、确证性等研发内在目的，不得用来替代方案研究目的。上述目的字段以及所有"
        "PICOS列表字段必须与原文项目一一对应并保持顺序；不得把多个原文项目合成一项，也不得把一个"
        "含完整定义的项目截短。主要目的中如同时写明不同剂量水平、治疗时长、改善目标、推荐剂量或"
        "后续确证性研究依据，必须全部保留。终点中的应答、输血、阈值、时间窗及定义性括注必须完整保留。"
        "synopsis_text同样不得写成信息压缩版，只能按源文档顺序组织已抽取的完整事实。"
        "若原文明示量表、评分工具、临床结局评估、诊断标准或安全性分级工具，必须逐项写入"
        "picos.assessment_instruments，并逐键复制assessment_instrument_item_template；不得只把名称埋在终点文本中。"
        "本注册表只纳入临床结局评估、疾病严重程度评分、疾病诊断/分类标准和安全性分级系统；"
        "疾病范围/受累面积等命名临床评估（例如BSA）属于候选，不得因其计算简单而遗漏。"
        "常规实验室检查（包括Hb、LDH）、影像、ECG/心电图、生命体征、微生物/结核筛查、"
        "妊娠检查、PK浓度、其他PK/PD检测和生物标志物均不得作为量表候选。"
        "diagnostic_criterion仅用于界定目标疾病的命名诊断/分类标准，不得把单项检查或入排筛查方法归入该类型。"
        "同一工具在多处重复出现时应合并证据；但名称、版本、适用人群、回忆期或填写频率不同的工具必须拆成独立候选，"
        "例如成人DLQI与儿童CDLQI、PROMIS 8a与8b不得用斜杠或合并名称压缩为一项。"
        "量表名称、研究用途、终点关系、访视、回顾期、评分范围/方向和方案修改状态均只能提取原文明示内容。"
        "endpoint_paths仅可使用picos.primary_endpoint、picos.key_secondary_endpoints、picos.other_secondary_endpoints、"
        "picos.exploratory_endpoints、picos.safety_endpoints、picos.inclusion_modules或picos.exclusion_modules。"
        "endpoint_paths中的值必须保留完整picos.前缀，不得使用key_secondary_endpoints等别名。"
        "只有原文明示为关键次要终点时才可使用picos.key_secondary_endpoints；原文仅称次要终点时必须使用"
        "picos.other_secondary_endpoints，不得把普通次要终点升级为关键次要终点。"
        "若原文未明确量表与终点或入排标准的关系，endpoint_paths必须返回空数组，不得猜测绑定。"
        "随机研究如原文明示不同剂量组、阳性对照组或安慰剂组，comparator_summary必须准确写明实际比较组；"
        "开放标签、多剂量探索不得改写成双盲或安慰剂对照。原文未提供估量策略时estimand_strategy保持空字符串，"
        "不得生成治疗策略、假想策略或缺失数据处理模板句。"
        "每个量表候选的evidence_span_ids必须包含1至5个仅直接支持该候选的evidence_spans.span_id，"
        "使用能够证明名称、研究用途和关键用法的最小充分证据集；"
        "这些ID还必须纳入field_evidence_span_ids的picos.assessment_instruments字段，禁止把整个量表字段的全部证据复制给每个候选。"
        "不得推断量表版权、许可、官方中文版本或翻译有效性；rights、translation、source_bindings、confirmation_status、"
        "confirmed_by和confirmed_at必须保持模板默认值。"
        "来源text_preview不超过500字时，evidence_spans.quote必须完整逐字复制该text_preview。"
        "design_archetype只能使用randomized_confirmatory、randomized_exploratory、single_arm_early_phase、"
        "open_label_extension、other或空字符串。randomized_confirmatory仅用于原文明示确证性、关键性、"
        "注册性或验证预设治疗效应假设的随机研究；randomized_exploratory用于原文明示随机分配且研究目的"
        "为剂量探索、剂量-反应、PoC、PoM或其他探索性比较的研究。不得仅凭II期判为探索性，也不得仅凭"
        "开放标签判为open_label_extension；开放标签只是盲法属性，只有原文明示为母研究后的延展或长期"
        "随访研究时才使用open_label_extension。证据不足时保持空字符串，不得猜测。所有结果均须由医学经理逐项复核。"
    )


def _normalize_instrument_kind(candidate: dict[str, Any]) -> str:
    current = str(candidate.get("instrument_kind") or "other").strip()
    if current != "other":
        return current
    identity = " ".join(
        str(candidate.get(key) or "").strip().casefold()
        for key in ("acronym", "canonical_name_en", "canonical_name_zh")
    )
    if re.search(r"\bctcae\b|不良事件通用术语标准", identity, re.IGNORECASE):
        return "safety_grading"
    if re.search(
        r"\b(?:dlqi|cdlqi|promis|nrs|vas)\b|患者报告|生活质量|问卷",
        identity,
        re.IGNORECASE,
    ):
        return "patient_reported"
    if re.search(
        r"\b(?:iga|pga|easi|pasi|scorad|bsa)\b|研究者整体|医生整体",
        identity,
        re.IGNORECASE,
    ):
        return "clinician_reported"
    return current


def _sanitize_synopsis_instrument_candidates(
    picos_payload: Any,
    *,
    source_id: str,
) -> dict[str, Any]:
    if not isinstance(picos_payload, dict):
        return picos_payload
    normalized = dict(picos_payload)
    candidates = normalized.get("assessment_instruments")
    if not isinstance(candidates, list):
        return normalized
    sanitized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(candidates, start=1):
        if not isinstance(item, dict):
            continue
        candidate = dict(item)
        name = str(
            candidate.get("canonical_name_zh")
            or candidate.get("canonical_name_en")
            or candidate.get("acronym")
            or ""
        ).strip()
        if not name:
            continue
        identity_text = "|".join(
            str(candidate.get(key) or "").strip().casefold()
            for key in ("acronym", "canonical_name_en", "canonical_name_zh", "version_label")
        )
        digest = hashlib.sha256(f"{source_id}|{identity_text}".encode("utf-8")).hexdigest()[:16]
        instrument_id = f"instrument_{digest}"
        if instrument_id in seen_ids:
            instrument_id = f"{instrument_id}_{index}"
        seen_ids.add(instrument_id)
        candidate.update(
            {
                "instrument_id": instrument_id,
                "canonical_name_zh": name,
                "instrument_kind": _normalize_instrument_kind(candidate),
                "source_synopsis_only": True,
                "source_bindings": [],
                "rights": MedicalWritingInstrumentRightsState().model_dump(mode="json"),
                "translation": MedicalWritingInstrumentTranslationState().model_dump(mode="json"),
                "confirmation_status": "candidate",
                "confirmed_by": "",
                "confirmed_at": None,
            }
        )
        evidence_span_ids = candidate.get("evidence_span_ids")
        candidate["evidence_span_ids"] = (
            list(dict.fromkeys(str(item).strip() for item in evidence_span_ids if str(item).strip()))
            if isinstance(evidence_span_ids, list)
            else []
        )
        sanitized.append(candidate)
    normalized["assessment_instruments"] = sanitized
    return normalized


def _bind_synopsis_instrument_sources(
    picos: MedicalWritingPicosDefinition,
    *,
    source: MedicalWritingSynopsisSource,
    field_evidence_span_ids: Any,
    evidence_spans: list[MedicalWritingSynopsisEvidenceSpan],
) -> MedicalWritingPicosDefinition:
    if not picos.assessment_instruments:
        return picos
    field_evidence_ids: list[str] = []
    if isinstance(field_evidence_span_ids, dict):
        candidate_ids = field_evidence_span_ids.get("picos.assessment_instruments")
        if isinstance(candidate_ids, list):
            field_evidence_ids = [str(item) for item in candidate_ids]
    evidence_by_id = {item.span_id: item for item in evidence_spans}
    updated = []
    for item in picos.assessment_instruments:
        evidence_ids = item.evidence_span_ids or field_evidence_ids
        bindings = [
            MedicalWritingInstrumentSourceBinding(
                source_kind="project_protocol",
                source_id=source.source_id,
                title=source.original_filename,
                locator=evidence_by_id[evidence_id].locator,
                artifact_id=source.source_id,
                evidence_sha256=evidence_by_id[evidence_id].source_text_sha256,
                accessed_at=source.imported_at,
            )
            for evidence_id in evidence_ids
            if evidence_id in evidence_by_id
        ]
        updated.append(item.model_copy(update={"source_bindings": bindings}, deep=True))
    return picos.model_copy(update={"assessment_instruments": updated}, deep=True)
