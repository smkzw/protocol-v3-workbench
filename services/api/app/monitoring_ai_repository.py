from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiConversationTurn,
    MonitoringAiInputRevision,
    MonitoringAiJob,
    MonitoringAiJobCreate,
    MonitoringAiJobStatus,
    MonitoringAiTaskType,
    canonical_json,
    content_sha256,
    stable_job_id,
    validate_candidates_for_job,
)
from .monitoring_deterministic_metadata_mapping import (
    LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION,
)
from .monitoring_protocol_preparation_contract import (
    PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
    PROTOCOL_PREPARATION_CONTRACT_VERSION,
)

_LEGACY_CONTRACT_RETIREMENT_FAILURE_CODES = frozenset(
    {
        "superseded_job_contract",
        "superseded_prompt_contract",
        "superseded_workflow_contract",
    }
)


class MonitoringAiRepositoryError(ValueError):
    pass


class MonitoringAiStateConflictError(MonitoringAiRepositoryError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _datetime(value: str) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _sqlite_bool(value: Any, field: str) -> bool:
    """Read a SQLite INTEGER boolean without accepting arbitrary truthiness."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return value == 1
    raise MonitoringAiRepositoryError(f"{field} must be SQLite boolean 0 or 1")


def _sqlite_int(value: Any, field: str, *, minimum: int) -> int:
    """Read a SQLite INTEGER counter without truncating malformed values."""

    if type(value) is not int or value < minimum:
        raise MonitoringAiRepositoryError(
            f"{field} must be an integer >= {minimum}"
        )
    return value


def _required_datetime(value: Any, field: str) -> datetime:
    try:
        parsed = _datetime(value)
    except (TypeError, ValueError) as exc:
        raise MonitoringAiRepositoryError(
            f"{field} must be an ISO datetime"
        ) from exc
    if parsed is None:
        raise MonitoringAiRepositoryError(f"{field} must be an ISO datetime")
    return parsed


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MonitoringAiRepositoryError(f"{field} must be non-empty text")
    return value.strip()


def _required_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MonitoringAiRepositoryError(f"{field} must be non-empty text")
    if (
        value != value.lower()
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise MonitoringAiRepositoryError(f"{field} must be a lowercase SHA-256")
    return value


def _optional_sha256(value: Any, field: str) -> str:
    if value == "":
        return ""
    return _required_sha256(value, field)


class MonitoringAiRepository:
    """Monitoring-owned durable AI state; no medical-writing table is reused."""

    def __init__(
        self,
        path: Path,
        *,
        lease_seconds: int = 300,
        clock=_utc_now,
    ):
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lease_seconds = lease_seconds
        self.clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS monitoring_ai_jobs (
                    job_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    business_key TEXT NOT NULL,
                    input_revision_json TEXT NOT NULL,
                    input_revision_sha256 TEXT NOT NULL,
                    input_payload_json TEXT NOT NULL,
                    input_payload_sha256 TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    requested_model TEXT NOT NULL,
                    response_model TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    lease_owner TEXT NOT NULL DEFAULT '',
                    lease_expires_at TEXT NOT NULL DEFAULT '',
                    output_sha256 TEXT NOT NULL DEFAULT '',
                    failure_code TEXT NOT NULL DEFAULT '',
                    failure_message TEXT NOT NULL DEFAULT '',
                    retryable INTEGER NOT NULL DEFAULT 0,
                    contract_retirement_code TEXT NOT NULL DEFAULT '',
                    contract_retirement_reason TEXT NOT NULL DEFAULT '',
                    contract_retired_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(
                        project_id, task_type, business_key,
                        input_revision_sha256, input_payload_sha256,
                        prompt_version, profile_id, requested_model
                    )
                );

                CREATE TABLE IF NOT EXISTS monitoring_ai_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    owner TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    request_json TEXT NOT NULL DEFAULT '',
                    response_sha256 TEXT NOT NULL DEFAULT '',
                    response_json TEXT NOT NULL DEFAULT '',
                    response_model TEXT NOT NULL DEFAULT '',
                    outcome TEXT NOT NULL,
                    failure_code TEXT NOT NULL DEFAULT '',
                    failure_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES monitoring_ai_jobs(job_id),
                    UNIQUE(job_id, attempt_number)
                );

                CREATE TABLE IF NOT EXISTS monitoring_ai_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_revision_sha256 TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decided_at TEXT NOT NULL DEFAULT '',
                    decided_by TEXT NOT NULL DEFAULT '',
                    decision_reason TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(job_id) REFERENCES monitoring_ai_jobs(job_id)
                );

                CREATE TABLE IF NOT EXISTS monitoring_ai_conversation_turns (
                    turn_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    message TEXT NOT NULL,
                    input_revision_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES monitoring_ai_jobs(job_id)
                );

                CREATE TABLE IF NOT EXISTS monitoring_ai_deterministic_repairs (
                    repair_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    job_id TEXT NOT NULL UNIQUE,
                    candidate_id TEXT NOT NULL UNIQUE,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    original_status TEXT NOT NULL,
                    original_failure_code TEXT NOT NULL,
                    original_failure_message TEXT NOT NULL,
                    original_attempt_count INTEGER NOT NULL,
                    output_sha256 TEXT NOT NULL,
                    raw_output_json TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES monitoring_ai_jobs(job_id),
                    FOREIGN KEY(candidate_id)
                        REFERENCES monitoring_ai_candidates(candidate_id),
                    UNIQUE(project_id, idempotency_key)
                );

                CREATE INDEX IF NOT EXISTS idx_monitoring_ai_jobs_queue
                ON monitoring_ai_jobs(status, lease_expires_at, created_at);
                CREATE INDEX IF NOT EXISTS idx_monitoring_ai_jobs_project
                ON monitoring_ai_jobs(project_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_monitoring_ai_candidates_job
                ON monitoring_ai_candidates(job_id, status, created_at);
                CREATE INDEX IF NOT EXISTS idx_monitoring_ai_turns_job
                ON monitoring_ai_conversation_turns(job_id, created_at);

                CREATE TRIGGER IF NOT EXISTS
                    trg_monitoring_ai_deterministic_repair_no_update
                BEFORE UPDATE ON monitoring_ai_deterministic_repairs
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'monitoring AI deterministic repair is immutable'
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS
                    trg_monitoring_ai_deterministic_repair_no_delete
                BEFORE DELETE ON monitoring_ai_deterministic_repairs
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'monitoring AI deterministic repair is immutable'
                    );
                END;
                """
            )
            attempt_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(monitoring_ai_attempts)"
                ).fetchall()
            }
            if "request_json" not in attempt_columns:
                connection.execute(
                    "ALTER TABLE monitoring_ai_attempts "
                    "ADD COLUMN request_json TEXT NOT NULL DEFAULT ''"
                )
            if "response_json" not in attempt_columns:
                connection.execute(
                    "ALTER TABLE monitoring_ai_attempts "
                    "ADD COLUMN response_json TEXT NOT NULL DEFAULT ''"
                )
            repair_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(monitoring_ai_deterministic_repairs)"
                ).fetchall()
            }
            if "raw_output_json" not in repair_columns:
                connection.execute(
                    "ALTER TABLE monitoring_ai_deterministic_repairs "
                    "ADD COLUMN raw_output_json TEXT NOT NULL DEFAULT ''"
                )
            job_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(monitoring_ai_jobs)"
                ).fetchall()
            }
            if "contract_retirement_code" not in job_columns:
                connection.execute(
                    "ALTER TABLE monitoring_ai_jobs "
                    "ADD COLUMN contract_retirement_code TEXT NOT NULL DEFAULT ''"
                )
            if "contract_retirement_reason" not in job_columns:
                connection.execute(
                    "ALTER TABLE monitoring_ai_jobs "
                    "ADD COLUMN contract_retirement_reason TEXT NOT NULL DEFAULT ''"
                )
            if "contract_retired_at" not in job_columns:
                connection.execute(
                    "ALTER TABLE monitoring_ai_jobs "
                    "ADD COLUMN contract_retired_at TEXT NOT NULL DEFAULT ''"
                )
            legacy_retirement_codes = ",".join(
                "?" for _ in _LEGACY_CONTRACT_RETIREMENT_FAILURE_CODES
            )
            connection.execute(
                f"""
                UPDATE monitoring_ai_jobs
                SET contract_retirement_code = failure_code,
                    contract_retirement_reason = CASE
                        WHEN failure_message != '' THEN failure_message
                        ELSE 'legacy contract retirement migrated from failure code'
                    END,
                    contract_retired_at = CASE
                        WHEN updated_at != '' THEN updated_at
                        ELSE created_at
                    END
                WHERE contract_retirement_code = ''
                  AND failure_code IN ({legacy_retirement_codes})
                """,
                tuple(_LEGACY_CONTRACT_RETIREMENT_FAILURE_CODES),
            )
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise RuntimeError("monitoring AI repository integrity check failed")

    def create_or_get(
        self,
        request: MonitoringAiJobCreate,
    ) -> MonitoringAiJob:
        now = self.clock()
        job_id = stable_job_id(request)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM monitoring_ai_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO monitoring_ai_jobs(
                        job_id, project_id, task_type, status, business_key,
                        input_revision_json, input_revision_sha256,
                        input_payload_json, input_payload_sha256,
                        prompt_version, profile_id, provider, requested_model,
                        max_attempts, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        request.project_id,
                        request.task_type.value,
                        MonitoringAiJobStatus.QUEUED.value,
                        request.business_key,
                        canonical_json(request.input_revision),
                        request.input_revision_sha256,
                        canonical_json(request.input_payload),
                        request.input_payload_sha256,
                        request.prompt_version,
                        request.profile_id,
                        request.provider,
                        request.requested_model,
                        request.max_attempts,
                        _iso(now),
                        _iso(now),
                    ),
                )
                existing = connection.execute(
                    "SELECT * FROM monitoring_ai_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
            connection.commit()
        return self._job(existing)

    def get(self, project_id: str, job_id: str) -> MonitoringAiJob:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_ai_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
        if row is None:
            raise MonitoringAiRepositoryError("monitoring AI job not found")
        return self._job(row)

    def input_payload(self, project_id: str, job_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_ai_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
        if row is None:
            raise MonitoringAiRepositoryError("monitoring AI job not found")
        _, payload = self._validated_job_inputs(row)
        return payload

    def list_jobs(
        self,
        project_id: str,
        *,
        task_type: str = "",
        business_key_prefix: str = "",
    ) -> tuple[MonitoringAiJob, ...]:
        clauses = ["project_id = ?"]
        parameters: list[Any] = [project_id]
        if task_type.strip():
            clauses.append("task_type = ?")
            parameters.append(task_type.strip())
        if business_key_prefix.strip():
            clauses.append("business_key LIKE ?")
            parameters.append(f"{business_key_prefix.strip()}%")
        query = (
            "SELECT * FROM monitoring_ai_jobs WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at, job_id"
        )
        with self._connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        # Status/list views must retain the persisted revision token so callers
        # can exclude deliberately stale jobs; execution reads use the strict
        # identity path in ``get``/``input_payload``.
        return tuple(self._job(row, strict_input_identity=False) for row in rows)

    def claim_next(self, owner: str) -> MonitoringAiJob | None:
        owner = owner.strip()
        if not owner:
            raise ValueError("claim owner is required")
        now = self.clock()
        lease_expires = now + timedelta(seconds=self.lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT candidate.* FROM monitoring_ai_jobs AS candidate
                WHERE (
                    candidate.status = ?
                    OR (
                        candidate.status = ?
                        AND candidate.lease_expires_at != ''
                        AND candidate.lease_expires_at < ?
                    )
                )
                AND candidate.attempt_count < candidate.max_attempts
                ORDER BY (
                    SELECT COUNT(*)
                    FROM monitoring_ai_jobs AS active
                    WHERE active.project_id = candidate.project_id
                      AND active.status = ?
                      AND (
                          active.lease_expires_at = ''
                          OR active.lease_expires_at >= ?
                      )
                ),
                candidate.created_at,
                candidate.job_id
                LIMIT 1
                """,
                (
                    MonitoringAiJobStatus.QUEUED.value,
                    MonitoringAiJobStatus.RUNNING.value,
                    _iso(now),
                    MonitoringAiJobStatus.RUNNING.value,
                    _iso(now),
                ),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            updated = connection.execute(
                """
                UPDATE monitoring_ai_jobs
                SET status = ?, attempt_count = attempt_count + 1,
                    lease_owner = ?, lease_expires_at = ?, updated_at = ?,
                    failure_code = '', failure_message = '', retryable = 0
                WHERE job_id = ? AND status = ?
                """,
                (
                    MonitoringAiJobStatus.RUNNING.value,
                    owner,
                    _iso(lease_expires),
                    _iso(now),
                    row["job_id"],
                    row["status"],
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise MonitoringAiStateConflictError("monitoring AI claim lost CAS")
            current = connection.execute(
                "SELECT * FROM monitoring_ai_jobs WHERE job_id = ?",
                (row["job_id"],),
            ).fetchone()
            connection.commit()
        return self._job(current)

    def expire_exhausted_leases(self, *, project_id: str = "") -> int:
        """Move expired final-attempt leases to a retryable terminal state.

        A worker can disappear after claiming its last allowed attempt. Such a
        row cannot be reclaimed by ``claim_next`` and must not remain
        ``running`` forever. The explicit terminal transition keeps the lost
        attempt auditable and lets the normal user-triggered retry path decide
        whether to grant additional attempts.
        """

        self.supersede_payload_workflows_except(
            task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
            business_key_prefix=PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
            current_workflow=PROTOCOL_PREPARATION_CONTRACT_VERSION,
            project_id=project_id,
            reason=(
                "方案监查准备合同已升级为 "
                f"{PROTOCOL_PREPARATION_CONTRACT_VERSION}；"
                "旧作业与候选仅保留审计，不得在启动恢复中重新执行。"
            ),
        )
        now = self.clock()
        clauses = [
            "status = ?",
            "lease_expires_at != ''",
            "lease_expires_at < ?",
            "attempt_count >= max_attempts",
        ]
        parameters: list[Any] = [
            MonitoringAiJobStatus.RUNNING.value,
            _iso(now),
        ]
        if project_id.strip():
            clauses.append("project_id = ?")
            parameters.append(project_id.strip())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """
                UPDATE monitoring_ai_jobs
                SET status = ?, lease_owner = '', lease_expires_at = '',
                    failure_code = ?, failure_message = ?, retryable = 1,
                    updated_at = ?
                WHERE
                """
                + " AND ".join(clauses),
                (
                    MonitoringAiJobStatus.FAILED.value,
                    "worker_lease_expired",
                    (
                        "AI worker lease expired during the final allowed "
                        "attempt; retry requires an explicit product action."
                    ),
                    _iso(now),
                    *parameters,
                ),
            )
            connection.commit()
        return int(updated.rowcount)

    def heartbeat(self, project_id: str, job_id: str, owner: str) -> MonitoringAiJob:
        now = self.clock()
        lease_expires = now + timedelta(seconds=self.lease_seconds)
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE monitoring_ai_jobs
                SET lease_expires_at = ?, updated_at = ?
                WHERE project_id = ? AND job_id = ? AND status = ?
                  AND lease_owner = ? AND lease_expires_at >= ?
                """,
                (
                    _iso(lease_expires),
                    _iso(now),
                    project_id,
                    job_id,
                    MonitoringAiJobStatus.RUNNING.value,
                    owner,
                    _iso(now),
                ),
            )
            if updated.rowcount != 1:
                raise MonitoringAiStateConflictError(
                    "monitoring AI heartbeat lost lease"
                )
        return self.get(project_id, job_id)

    def record_attempt(
        self,
        job: MonitoringAiJob,
        *,
        owner: str,
        request_payload: Any,
        response_payload: Any | None,
        response_model: str = "",
        outcome: str,
        failure_code: str = "",
        failure_message: str = "",
    ) -> str:
        if job.status != MonitoringAiJobStatus.RUNNING:
            raise MonitoringAiStateConflictError("attempt requires running job")
        attempt_id = f"monattempt_{uuid4().hex}"
        with self._connect() as connection:
            current = connection.execute(
                """
                SELECT status, lease_owner, lease_expires_at, attempt_count
                FROM monitoring_ai_jobs WHERE job_id = ?
                """,
                (job.job_id,),
            ).fetchone()
            if (
                current is None
                or current["status"] != MonitoringAiJobStatus.RUNNING.value
                or current["lease_owner"] != owner
                or current["lease_expires_at"] < _iso(self.clock())
                or int(current["attempt_count"]) != job.attempt_count
            ):
                raise MonitoringAiStateConflictError("attempt record lost lease or CAS")
            connection.execute(
                """
                INSERT INTO monitoring_ai_attempts(
                    attempt_id, job_id, attempt_number, owner,
                    request_sha256, request_json,
                    response_sha256, response_json, response_model,
                    outcome, failure_code, failure_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    job.job_id,
                    job.attempt_count,
                    owner,
                    content_sha256(request_payload),
                    canonical_json(request_payload),
                    (
                        content_sha256(response_payload)
                        if response_payload is not None
                        else ""
                    ),
                    (
                        canonical_json(response_payload)
                        if response_payload is not None
                        else ""
                    ),
                    response_model,
                    outcome,
                    failure_code,
                    failure_message[:4_000],
                    _iso(self.clock()),
                ),
            )
        return attempt_id

    def attempts(
        self,
        project_id: str,
        job_id: str,
    ) -> tuple[dict[str, Any], ...]:
        job = self.get(project_id, job_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT attempt_id, job_id, attempt_number, owner,
                       request_sha256, request_json,
                       response_sha256, response_json, response_model,
                       outcome, failure_code, failure_message, created_at
                FROM monitoring_ai_attempts
                WHERE job_id = ?
                ORDER BY attempt_number, attempt_id
                """,
                (job_id,),
            ).fetchall()
        result = []
        for row in rows:
            result.append(
                self._attempt_from_row(row, expected_job_id=job.job_id)
            )
        return tuple(result)

    @staticmethod
    def _attempt_from_row(
        row: sqlite3.Row,
        *,
        expected_job_id: str,
    ) -> dict[str, Any]:
        try:
            attempt_id = _required_text(row["attempt_id"], "attempt_id")
            job_id = _required_text(row["job_id"], "job_id")
            if job_id != expected_job_id:
                raise MonitoringAiRepositoryError(
                    "persisted monitoring AI attempt parent binding mismatch"
                )
            attempt_number = _sqlite_int(
                row["attempt_number"],
                "attempt_number",
                minimum=1,
            )
            owner = _required_text(row["owner"], "owner")
            response_model = row["response_model"]
            outcome = _required_text(row["outcome"], "outcome")
            failure_code = row["failure_code"]
            failure_message = row["failure_message"]
            if not isinstance(response_model, str):
                raise MonitoringAiRepositoryError(
                    "response_model must be text"
                )
            if not isinstance(failure_code, str) or not isinstance(
                failure_message, str
            ):
                raise MonitoringAiRepositoryError(
                    "attempt failure metadata must be text"
                )
            created_at = _required_datetime(row["created_at"], "created_at")
            request = MonitoringAiRepository._attempt_payload_from_row(
                row["request_json"],
                row["request_sha256"],
                "request",
            )
            response = MonitoringAiRepository._attempt_payload_from_row(
                row["response_json"],
                row["response_sha256"],
                "response",
            )
            return {
                "attempt_id": attempt_id,
                "attempt_number": attempt_number,
                "owner": owner,
                "request_sha256": row["request_sha256"],
                "request": request,
                "response_sha256": row["response_sha256"],
                "response": response,
                "response_model": response_model,
                "outcome": outcome,
                "failure_code": failure_code,
                "failure_message": failure_message,
                "created_at": _iso(created_at),
            }
        except MonitoringAiRepositoryError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI attempt root is invalid"
            ) from exc

    @staticmethod
    def _attempt_payload_from_row(
        raw_json: Any,
        raw_sha256: Any,
        field: str,
    ) -> Any:
        # Empty payload columns are retained for attempts created before the
        # JSON audit columns were added. Modern writes always persist both the
        # canonical JSON and its digest, including JSON ``null``.
        if not raw_json:
            if raw_sha256:
                raise MonitoringAiRepositoryError(
                    f"persisted monitoring AI attempt {field} payload hash mismatch"
                )
            return None
        try:
            payload = json.loads(raw_json)
        except (TypeError, ValueError) as exc:
            raise MonitoringAiRepositoryError(
                f"persisted monitoring AI attempt {field} payload is invalid"
            ) from exc
        try:
            expected_sha256 = _required_sha256(
                raw_sha256,
                f"{field}_sha256",
            )
        except MonitoringAiRepositoryError as exc:
            raise MonitoringAiRepositoryError(
                f"{field} payload hash mismatch"
            ) from exc
        if content_sha256(payload) != expected_sha256:
            raise MonitoringAiRepositoryError(
                f"persisted monitoring AI attempt {field} payload hash mismatch"
            )
        return payload

    def deterministic_repair_by_idempotency(
        self,
        project_id: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_ai_deterministic_repairs
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if row is None:
                return None
            repair = self._deterministic_repair(
                row,
                expected_project_id=project_id,
            )
            job_row = connection.execute(
                "SELECT project_id FROM monitoring_ai_jobs WHERE job_id = ?",
                (repair["job_id"],),
            ).fetchone()
            candidate_row = connection.execute(
                """
                SELECT project_id, job_id
                FROM monitoring_ai_candidates
                WHERE candidate_id = ?
                """,
                (repair["candidate_id"],),
            ).fetchone()
        if (
            job_row is None
            or job_row["project_id"] != repair["project_id"]
            or candidate_row is None
            or candidate_row["project_id"] != repair["project_id"]
            or candidate_row["job_id"] != repair["job_id"]
        ):
            raise MonitoringAiRepositoryError(
                "persisted deterministic repair parent binding mismatch"
            )
        return repair

    def complete_failed_v7_deterministic_mapping(
        self,
        job: MonitoringAiJob,
        *,
        candidate: MonitoringAiCandidate,
        response_model: str,
        raw_output: Any,
        provenance: dict[str, Any],
        actor: str,
        reason: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> tuple[MonitoringAiJob, dict[str, Any]]:
        validate_candidates_for_job(job, (candidate,))
        actor = actor.strip()
        reason = reason.strip()
        idempotency_key = idempotency_key.strip()
        response_model = response_model.strip()
        if not actor or not reason or not idempotency_key or not response_model:
            raise ValueError(
                "deterministic repair requires actor, reason, idempotency and model"
            )
        now = self.clock()
        output_sha256 = content_sha256(raw_output)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM monitoring_ai_deterministic_repairs
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (job.project_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if (
                    existing["request_sha256"] != request_sha256
                    or existing["job_id"] != job.job_id
                ):
                    connection.rollback()
                    raise MonitoringAiStateConflictError(
                        "deterministic repair idempotency key has different meaning"
                    )
                repaired_job = connection.execute(
                    "SELECT * FROM monitoring_ai_jobs WHERE job_id = ?",
                    (existing["job_id"],),
                ).fetchone()
                candidate_row = connection.execute(
                    """
                    SELECT candidate_id, project_id, job_id
                    FROM monitoring_ai_candidates
                    WHERE job_id = ? AND candidate_id = ?
                    """,
                    (existing["job_id"], existing["candidate_id"]),
                ).fetchone()
                if (
                    repaired_job is None
                    or repaired_job["project_id"] != job.project_id
                    or repaired_job["status"]
                    != MonitoringAiJobStatus.COMPLETED.value
                    or candidate_row is None
                    or candidate_row["project_id"] != job.project_id
                ):
                    connection.rollback()
                    raise MonitoringAiStateConflictError(
                        "deterministic repair replay found inconsistent persisted state"
                    )
                connection.commit()
                return (
                    self._job(repaired_job),
                    self._deterministic_repair(
                        existing,
                        expected_project_id=job.project_id,
                        expected_job_id=job.job_id,
                    ),
                )

            row = connection.execute(
                "SELECT * FROM monitoring_ai_jobs WHERE job_id = ?",
                (job.job_id,),
            ).fetchone()
            if (
                row is None
                or row["project_id"] != job.project_id
                or row["task_type"]
                != MonitoringAiTaskType.LISTING_FIELD_MAPPING.value
                or row["status"] != MonitoringAiJobStatus.FAILED.value
                or row["failure_code"] != "invalid_ai_output"
                or row["prompt_version"]
                != LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION
                or row["input_revision_sha256"]
                != job.input_revision_sha256
                or row["input_payload_sha256"]
                != job.input_payload_sha256
                or int(row["attempt_count"]) != job.attempt_count
            ):
                connection.rollback()
                raise MonitoringAiStateConflictError(
                    "monitoring AI job is not the exact repairable v7 failure"
                )
            current_job = self._job(row)
            validate_candidates_for_job(current_job, (candidate,))
            candidate_count = connection.execute(
                """
                SELECT COUNT(*) AS candidate_count
                FROM monitoring_ai_candidates WHERE job_id = ?
                """,
                (job.job_id,),
            ).fetchone()
            if candidate_count is None or int(candidate_count["candidate_count"]):
                connection.rollback()
                raise MonitoringAiStateConflictError(
                    "deterministic repair requires a job with no candidates"
                )

            connection.execute(
                """
                INSERT INTO monitoring_ai_candidates(
                    candidate_id, job_id, project_id, task_type, status,
                    input_revision_sha256, candidate_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_id,
                    candidate.job_id,
                    candidate.project_id,
                    candidate.task_type.value,
                    candidate.status.value,
                    candidate.input_revision_sha256,
                    canonical_json(candidate),
                    _iso(candidate.created_at),
                ),
            )
            updated = connection.execute(
                """
                UPDATE monitoring_ai_jobs
                SET status = ?, response_model = ?, output_sha256 = ?,
                    lease_owner = '', lease_expires_at = '', updated_at = ?,
                    failure_code = '', failure_message = '', retryable = 0
                WHERE job_id = ? AND project_id = ? AND task_type = ?
                  AND status = ? AND failure_code = ? AND prompt_version = ?
                  AND input_revision_sha256 = ? AND input_payload_sha256 = ?
                  AND attempt_count = ?
                """,
                (
                    MonitoringAiJobStatus.COMPLETED.value,
                    response_model,
                    output_sha256,
                    _iso(now),
                    job.job_id,
                    job.project_id,
                    MonitoringAiTaskType.LISTING_FIELD_MAPPING.value,
                    MonitoringAiJobStatus.FAILED.value,
                    "invalid_ai_output",
                    LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION,
                    job.input_revision_sha256,
                    job.input_payload_sha256,
                    job.attempt_count,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise MonitoringAiStateConflictError(
                    "deterministic repair lost job state CAS"
                )

            repair_seed = {
                "project_id": job.project_id,
                "job_id": job.job_id,
                "candidate_id": candidate.candidate_id,
                "request_sha256": request_sha256,
            }
            repair_id = "monrepair_" + content_sha256(repair_seed)[:28]
            connection.execute(
                """
                INSERT INTO monitoring_ai_deterministic_repairs(
                    repair_id, project_id, job_id, candidate_id,
                    idempotency_key, request_sha256,
                    original_status, original_failure_code,
                    original_failure_message, original_attempt_count,
                    output_sha256, raw_output_json, provenance_json,
                    actor, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    repair_id,
                    job.project_id,
                    job.job_id,
                    candidate.candidate_id,
                    idempotency_key,
                    request_sha256,
                    row["status"],
                    row["failure_code"],
                    row["failure_message"],
                    int(row["attempt_count"]),
                    output_sha256,
                    canonical_json(raw_output),
                    canonical_json(provenance),
                    actor,
                    reason,
                    _iso(now),
                ),
            )
            repaired_job = connection.execute(
                "SELECT * FROM monitoring_ai_jobs WHERE job_id = ?",
                (job.job_id,),
            ).fetchone()
            repair_row = connection.execute(
                """
                SELECT * FROM monitoring_ai_deterministic_repairs
                WHERE repair_id = ?
                """,
                (repair_id,),
            ).fetchone()
            connection.commit()
        return (
            self._job(repaired_job),
            self._deterministic_repair(
                repair_row,
                expected_project_id=job.project_id,
                expected_job_id=job.job_id,
            ),
        )

    def complete(
        self,
        job: MonitoringAiJob,
        *,
        owner: str,
        response_model: str,
        raw_output: Any,
        candidates: Iterable[MonitoringAiCandidate],
    ) -> MonitoringAiJob:
        candidate_tuple = tuple(candidates)
        validate_candidates_for_job(job, candidate_tuple)
        if response_model.strip() != job.requested_model:
            raise MonitoringAiStateConflictError(
                "monitoring AI response model does not match requested model"
            )
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM monitoring_ai_jobs WHERE job_id = ?",
                (job.job_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] != MonitoringAiJobStatus.RUNNING.value
                or row["lease_owner"] != owner
                or row["lease_expires_at"] < _iso(now)
                or int(row["attempt_count"]) != job.attempt_count
            ):
                connection.rollback()
                raise MonitoringAiStateConflictError(
                    "late monitoring AI completion lost lease or CAS"
                )
            for candidate in candidate_tuple:
                connection.execute(
                    """
                    INSERT INTO monitoring_ai_candidates(
                        candidate_id, job_id, project_id, task_type, status,
                        input_revision_sha256, candidate_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate.candidate_id,
                        candidate.job_id,
                        candidate.project_id,
                        candidate.task_type.value,
                        candidate.status.value,
                        candidate.input_revision_sha256,
                        canonical_json(candidate),
                        _iso(candidate.created_at),
                    ),
                )
            updated = connection.execute(
                """
                UPDATE monitoring_ai_jobs
                SET status = ?, response_model = ?, output_sha256 = ?,
                    lease_owner = '', lease_expires_at = '', updated_at = ?,
                    failure_code = '', failure_message = '', retryable = 0
                WHERE job_id = ? AND status = ? AND lease_owner = ?
                  AND attempt_count = ?
                """,
                (
                    MonitoringAiJobStatus.COMPLETED.value,
                    response_model,
                    content_sha256(raw_output),
                    _iso(now),
                    job.job_id,
                    MonitoringAiJobStatus.RUNNING.value,
                    owner,
                    job.attempt_count,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise MonitoringAiStateConflictError(
                    "monitoring AI completion lost CAS"
                )
            connection.commit()
        return self.get(job.project_id, job.job_id)

    def fail(
        self,
        job: MonitoringAiJob,
        *,
        owner: str,
        failure_code: str,
        failure_message: str,
        retryable: bool,
    ) -> MonitoringAiJob:
        now = self.clock()
        next_status = (
            MonitoringAiJobStatus.QUEUED
            if retryable and job.attempt_count < job.max_attempts
            else MonitoringAiJobStatus.FAILED
        )
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE monitoring_ai_jobs
                SET status = ?, lease_owner = '', lease_expires_at = '',
                    failure_code = ?, failure_message = ?, retryable = ?,
                    updated_at = ?
                WHERE project_id = ? AND job_id = ? AND status = ?
                  AND lease_owner = ? AND attempt_count = ?
                """,
                (
                    next_status.value,
                    failure_code[:160],
                    failure_message[:4_000],
                    int(retryable),
                    _iso(now),
                    job.project_id,
                    job.job_id,
                    MonitoringAiJobStatus.RUNNING.value,
                    owner,
                    job.attempt_count,
                ),
            )
            if updated.rowcount != 1:
                raise MonitoringAiStateConflictError(
                    "monitoring AI failure update lost CAS"
                )
        return self.get(job.project_id, job.job_id)

    def retry_terminal(
        self,
        project_id: str,
        job_id: str,
        *,
        current_input_revision_sha256: str,
    ) -> MonitoringAiJob:
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, input_revision_sha256, attempt_count, failure_code,
                       contract_retirement_code
                FROM monitoring_ai_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise MonitoringAiRepositoryError("monitoring AI job not found")
            if row["status"] not in {
                MonitoringAiJobStatus.FAILED.value,
                MonitoringAiJobStatus.BLOCKED.value,
                MonitoringAiJobStatus.STALE_INPUT.value,
            }:
                connection.rollback()
                raise MonitoringAiStateConflictError(
                    "only failed, blocked or stale monitoring AI jobs can be retried"
                )
            if (
                row["contract_retirement_code"]
                or row["failure_code"]
                in _LEGACY_CONTRACT_RETIREMENT_FAILURE_CODES
            ):
                connection.rollback()
                raise MonitoringAiStateConflictError(
                    "superseded contract cannot be retried"
                )
            if row["input_revision_sha256"] != current_input_revision_sha256:
                connection.rollback()
                raise MonitoringAiStateConflictError(
                    "monitoring AI job input changed and cannot be retried"
                )
            candidate_count = connection.execute(
                """
                SELECT COUNT(*) AS candidate_count
                FROM monitoring_ai_candidates
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
            restore_completed = (
                row["status"] == MonitoringAiJobStatus.STALE_INPUT.value
                and candidate_count is not None
                and int(candidate_count["candidate_count"]) > 0
            )
            next_max_attempts = int(row["attempt_count"]) + 2
            updated = connection.execute(
                """
                UPDATE monitoring_ai_jobs
                SET status = ?, max_attempts = ?, retryable = 0,
                    failure_code = '', failure_message = '',
                    lease_owner = '', lease_expires_at = '', updated_at = ?
                WHERE project_id = ? AND job_id = ?
                  AND status IN (?, ?, ?)
                  AND input_revision_sha256 = ?
                """,
                (
                    (
                        MonitoringAiJobStatus.COMPLETED.value
                        if restore_completed
                        else MonitoringAiJobStatus.QUEUED.value
                    ),
                    next_max_attempts,
                    _iso(now),
                    project_id,
                    job_id,
                    MonitoringAiJobStatus.FAILED.value,
                    MonitoringAiJobStatus.BLOCKED.value,
                    MonitoringAiJobStatus.STALE_INPUT.value,
                    current_input_revision_sha256,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise MonitoringAiStateConflictError(
                    "monitoring AI retry lost CAS"
                )
            if restore_completed:
                connection.execute(
                    """
                    UPDATE monitoring_ai_candidates
                    SET status = ?, decided_at = '', decided_by = '',
                        decision_reason = ''
                    WHERE project_id = ? AND job_id = ?
                      AND status = ? AND decided_by = 'system'
                      AND decision_reason IN (?, ?)
                    """,
                    (
                        MonitoringAiCandidateStatus.PROPOSED.value,
                        project_id,
                        job_id,
                        MonitoringAiCandidateStatus.SUPERSEDED.value,
                        "input revision changed",
                        (
                            "任务输入、提示词、产品模型或执行配置已有更新，"
                            "旧候选不再代表当前合同。"
                        ),
                    ),
                )
            connection.commit()
        return self.get(project_id, job_id)

    def stale_claimed(
        self,
        job: MonitoringAiJob,
        *,
        owner: str,
        reason: str,
    ) -> MonitoringAiJob:
        now = self.clock()
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE monitoring_ai_jobs
                SET status = ?, lease_owner = '', lease_expires_at = '',
                    failure_code = ?, failure_message = ?, retryable = 0,
                    updated_at = ?
                WHERE project_id = ? AND job_id = ? AND status = ?
                  AND lease_owner = ? AND attempt_count = ?
                  AND lease_expires_at >= ?
                """,
                (
                    MonitoringAiJobStatus.STALE_INPUT.value,
                    "stale_input_revision",
                    reason[:4_000],
                    _iso(now),
                    job.project_id,
                    job.job_id,
                    MonitoringAiJobStatus.RUNNING.value,
                    owner,
                    job.attempt_count,
                    _iso(now),
                ),
            )
            if updated.rowcount != 1:
                raise MonitoringAiStateConflictError(
                    "monitoring AI stale-input update lost lease or CAS"
                )
        return self.get(job.project_id, job.job_id)

    def mark_stale(
        self,
        project_id: str,
        *,
        business_key: str,
        current_input_revision_sha256: str,
    ) -> int:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT job_id FROM monitoring_ai_jobs
                WHERE project_id = ? AND business_key = ?
                  AND input_revision_sha256 != ?
                  AND status IN (?, ?, ?)
                """,
                (
                    project_id,
                    business_key,
                    current_input_revision_sha256,
                    MonitoringAiJobStatus.QUEUED.value,
                    MonitoringAiJobStatus.COMPLETED.value,
                    MonitoringAiJobStatus.BLOCKED.value,
                ),
            ).fetchall()
            job_ids = [row["job_id"] for row in rows]
            if job_ids:
                placeholders = ",".join("?" for _ in job_ids)
                connection.execute(
                    f"""
                    UPDATE monitoring_ai_jobs
                    SET status = ?, updated_at = ?
                    WHERE job_id IN ({placeholders})
                    """,
                    (
                        MonitoringAiJobStatus.STALE_INPUT.value,
                        _iso(self.clock()),
                        *job_ids,
                    ),
                )
                connection.execute(
                    f"""
                    UPDATE monitoring_ai_candidates
                    SET status = ?, decided_at = ?, decided_by = ?,
                        decision_reason = ?
                    WHERE job_id IN ({placeholders}) AND status = ?
                    """,
                    (
                        MonitoringAiCandidateStatus.SUPERSEDED.value,
                        _iso(self.clock()),
                        "system",
                        "input revision changed",
                        *job_ids,
                        MonitoringAiCandidateStatus.PROPOSED.value,
                    ),
                )
            connection.commit()
        return len(job_ids)

    def supersede_business_key_except(
        self,
        project_id: str,
        *,
        business_key: str,
        current_job_id: str,
        reason: str,
    ) -> int:
        """Retire obsolete queued/terminal contracts for one business key.

        A prompt, model/profile, or payload revision can change while the
        source revision remains identical. Those older jobs must not consume
        product-AI capacity or leave proposed candidates looking current.
        Running jobs are also made stale. Their in-flight provider calls may
        return, but completion then loses CAS and cannot persist obsolete
        candidates or be reclaimed after lease expiry.

        Completed and failed rows that already carry an immutable
        contract-retirement marker keep their terminal status, failure
        evidence, timestamps and candidates: their retirement is already
        durably recorded and cannot be revived, so business-key supersession
        only retains the marker for them. Unmarked terminal rows and every
        queued, running or blocked row are still retired exactly as before.
        """
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """
                SELECT prompt_version, profile_id, provider, requested_model
                FROM monitoring_ai_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, current_job_id),
            ).fetchone()
            if current is None:
                connection.rollback()
                raise MonitoringAiRepositoryError(
                    "current monitoring AI job not found"
                )
            rows = connection.execute(
                """
                SELECT job_id, status, prompt_version, profile_id, provider,
                       requested_model, failure_code, contract_retirement_code
                FROM monitoring_ai_jobs
                WHERE project_id = ? AND business_key = ? AND job_id != ?
                  AND status IN (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    business_key,
                    current_job_id,
                    MonitoringAiJobStatus.QUEUED.value,
                    MonitoringAiJobStatus.RUNNING.value,
                    MonitoringAiJobStatus.COMPLETED.value,
                    MonitoringAiJobStatus.BLOCKED.value,
                    MonitoringAiJobStatus.FAILED.value,
                    MonitoringAiJobStatus.STALE_INPUT.value,
                ),
            ).fetchall()
            execution_contract_fields = (
                "prompt_version",
                "profile_id",
                "provider",
                "requested_model",
            )
            job_ids = [
                row["job_id"]
                for row in rows
                if (
                    row["status"] != MonitoringAiJobStatus.STALE_INPUT.value
                    or row["failure_code"]
                    in _LEGACY_CONTRACT_RETIREMENT_FAILURE_CODES
                    or any(
                        row[field] != current[field]
                        for field in execution_contract_fields
                    )
                )
            ]
            retired_ids = [
                row["job_id"]
                for row in rows
                if (
                    row["status"]
                    != MonitoringAiJobStatus.STALE_INPUT.value
                    and not (
                        row["status"]
                        in {
                            MonitoringAiJobStatus.COMPLETED.value,
                            MonitoringAiJobStatus.FAILED.value,
                        }
                        and row["contract_retirement_code"]
                    )
                )
            ]
            self._apply_contract_supersession(
                connection,
                job_ids=job_ids,
                retired_ids=retired_ids,
                failure_code="superseded_job_contract",
                reason=reason,
                now=now,
            )
            connection.commit()
        return len(retired_ids)

    def _apply_contract_supersession(
        self,
        connection: sqlite3.Connection,
        *,
        job_ids: list[str],
        retired_ids: list[str],
        failure_code: str,
        reason: str,
        now: datetime,
    ) -> None:
        """Mark obsolete rows as durably contract-retired and retire active ones.

        Every contract-obsolete row receives the immutable retirement marker,
        retaining the first marker already present. Rows that are not yet
        stale are additionally transitioned to STALE_INPUT with the
        supersession failure code, and their proposed candidates are
        superseded. Already stale and preserved terminal rows keep their
        status, failure text and candidates untouched. The marker-only update
        writes only the three retirement fields and preserves updated_at;
        only rows actually transitioned to STALE_INPUT record the retirement
        time in updated_at. A business-key row already made stale solely by an
        input-revision change is deliberately not marked when its execution
        contract still matches the current job; verified compatibility
        migrations may restore that audit result.
        """

        if not job_ids:
            return
        placeholders = ",".join("?" for _ in job_ids)
        connection.execute(
            f"""
            UPDATE monitoring_ai_jobs
            SET contract_retirement_code = CASE
                    WHEN contract_retirement_code = '' THEN ?
                    ELSE contract_retirement_code END,
                contract_retirement_reason = CASE
                    WHEN contract_retirement_reason = '' THEN ?
                    ELSE contract_retirement_reason END,
                contract_retired_at = CASE
                    WHEN contract_retired_at = '' THEN ?
                    ELSE contract_retired_at END
            WHERE job_id IN ({placeholders})
            """,
            (failure_code, reason[:2_000], _iso(now), *job_ids),
        )
        if not retired_ids:
            return
        retired_placeholders = ",".join("?" for _ in retired_ids)
        connection.execute(
            f"""
            UPDATE monitoring_ai_jobs
            SET status = ?, failure_code = ?, failure_message = ?,
                retryable = 0, lease_owner = '', lease_expires_at = '',
                updated_at = ?
            WHERE job_id IN ({retired_placeholders})
            """,
            (
                MonitoringAiJobStatus.STALE_INPUT.value,
                failure_code,
                reason[:4_000],
                _iso(now),
                *retired_ids,
            ),
        )
        connection.execute(
            f"""
            UPDATE monitoring_ai_candidates
            SET status = ?, decided_at = ?, decided_by = ?,
                decision_reason = ?
            WHERE job_id IN ({retired_placeholders}) AND status = ?
            """,
            (
                MonitoringAiCandidateStatus.SUPERSEDED.value,
                _iso(now),
                "system",
                reason[:2_000],
                *retired_ids,
                MonitoringAiCandidateStatus.PROPOSED.value,
            ),
        )

    def supersede_payload_workflows_except(
        self,
        *,
        task_type: MonitoringAiTaskType,
        business_key_prefix: str,
        current_workflow: str,
        project_id: str = "",
        reason: str = "",
    ) -> int:
        """Retire obsolete workflow contracts without deleting audit history."""

        prefix = business_key_prefix.strip()
        workflow = current_workflow.strip()
        if not prefix or not workflow:
            raise MonitoringAiRepositoryError(
                "business key prefix and current workflow are required"
            )
        scoped_project = project_id.strip()
        decision_reason = (
            reason.strip()
            or (
                f"任务工作流合同已升级为 {workflow}，"
                "旧候选仅保留审计，不再代表当前合同。"
            )
        )
        clauses = [
            "task_type = ?",
            "business_key LIKE ?",
            "status IN (?, ?, ?, ?, ?, ?)",
        ]
        parameters: list[Any] = [
            task_type.value,
            f"{prefix}%",
            MonitoringAiJobStatus.QUEUED.value,
            MonitoringAiJobStatus.RUNNING.value,
            MonitoringAiJobStatus.COMPLETED.value,
            MonitoringAiJobStatus.BLOCKED.value,
            MonitoringAiJobStatus.FAILED.value,
            MonitoringAiJobStatus.STALE_INPUT.value,
        ]
        if scoped_project:
            clauses.append("project_id = ?")
            parameters.append(scoped_project)

        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT job_id, status, input_payload_json
                FROM monitoring_ai_jobs
                WHERE
                """
                + " AND ".join(clauses),
                parameters,
            ).fetchall()
            job_ids = []
            retired_ids = []
            for row in rows:
                try:
                    payload = json.loads(row["input_payload_json"])
                except (TypeError, ValueError):
                    payload = {}
                context = payload.get("context")
                persisted_workflow = (
                    str(context.get("workflow") or "").strip()
                    if isinstance(context, dict)
                    else ""
                )
                if persisted_workflow == workflow:
                    continue
                job_ids.append(row["job_id"])
                if row["status"] != MonitoringAiJobStatus.STALE_INPUT.value:
                    retired_ids.append(row["job_id"])
            self._apply_contract_supersession(
                connection,
                job_ids=job_ids,
                retired_ids=retired_ids,
                failure_code="superseded_workflow_contract",
                reason=decision_reason,
                now=now,
            )
            connection.commit()
        return len(retired_ids)

    def supersede_prompt_versions_except(
        self,
        *,
        task_type: MonitoringAiTaskType,
        current_prompt_version: str,
        project_id: str = "",
        reason: str = "",
        legacy_terminal_prompt_versions: Iterable[str] = (),
    ) -> int:
        """Retire persisted jobs whose prompt contract is no longer current.

        Startup recovery must never wake queued work produced by an older
        prompt deployment. Running rows are retired as well, so a provider
        response arriving from a superseded process cannot persist obsolete
        candidates after a restart.

        ``legacy_terminal_prompt_versions`` is an explicit immutable collection
        of prompt versions whose terminal audit evidence survives the cutover:
        only completed and failed jobs (and their proposed candidates) are
        preserved for those versions. Queued, running and blocked jobs are
        still retired even when their prompt version is listed, because they
        must fail closed and cannot wake after restart. An empty collection
        preserves the default behavior and retires every obsolete row.
        Every obsolete row, preserved terminal jobs and already-stale rows
        included, receives the durable contract retirement marker so it can
        never be revived through a same-revision retry.
        """

        current_prompt_version = current_prompt_version.strip()
        if not current_prompt_version:
            raise MonitoringAiRepositoryError(
                "current prompt version is required"
            )
        project_id = project_id.strip()
        legacy_versions = frozenset(
            str(item).strip()
            for item in legacy_terminal_prompt_versions
            if str(item).strip()
        )
        decision_reason = (
            reason.strip()
            or (
                "任务提示词合同已升级为 "
                f"{current_prompt_version}，旧候选不再代表当前合同。"
            )
        )
        clauses = [
            "task_type = ?",
            "prompt_version != ?",
        ]
        parameters: list[Any] = [
            task_type.value,
            current_prompt_version,
        ]
        if project_id:
            clauses.append("project_id = ?")
            parameters.append(project_id)

        preserved_statuses = (
            MonitoringAiJobStatus.COMPLETED.value,
            MonitoringAiJobStatus.FAILED.value,
        )
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT job_id, status, prompt_version FROM monitoring_ai_jobs
                WHERE
                """
                + " AND ".join(clauses),
                parameters,
            ).fetchall()
            job_ids = []
            retired_ids = []
            for row in rows:
                status = row["status"]
                job_ids.append(row["job_id"])
                if status == MonitoringAiJobStatus.STALE_INPUT.value:
                    continue
                if (
                    legacy_versions
                    and status in preserved_statuses
                    and row["prompt_version"] in legacy_versions
                ):
                    continue
                retired_ids.append(row["job_id"])
            self._apply_contract_supersession(
                connection,
                job_ids=job_ids,
                retired_ids=retired_ids,
                failure_code="superseded_prompt_contract",
                reason=decision_reason,
                now=now,
            )
            connection.commit()
        return len(retired_ids)

    def candidates(
        self,
        project_id: str,
        job_id: str,
    ) -> tuple[MonitoringAiCandidate, ...]:
        job = self.get(project_id, job_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT candidate_id, project_id, job_id, task_type, status,
                       input_revision_sha256, candidate_json, created_at
                FROM monitoring_ai_candidates
                WHERE project_id = ? AND job_id = ?
                ORDER BY created_at, candidate_id
                """,
                (project_id, job_id),
            ).fetchall()
        return tuple(self._candidate_from_row(row, job) for row in rows)

    def _candidate_from_row(
        self,
        row: sqlite3.Row,
        job: MonitoringAiJob,
        *,
        status_override: MonitoringAiCandidateStatus | str | None = None,
    ) -> MonitoringAiCandidate:
        """Rehydrate one candidate and verify every persisted parent binding."""

        try:
            payload = json.loads(row["candidate_json"])
            payload["status"] = (
                status_override.value
                if isinstance(status_override, MonitoringAiCandidateStatus)
                else status_override
                if status_override is not None
                else row["status"]
            )
            candidate = MonitoringAiCandidate.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI candidate is invalid"
            ) from exc

        row_candidate_id = _required_text(row["candidate_id"], "candidate_id")
        row_project_id = _required_text(row["project_id"], "candidate.project_id")
        row_job_id = _required_text(row["job_id"], "candidate.job_id")
        row_task_type = _required_text(row["task_type"], "candidate.task_type")
        row_input_revision = _required_sha256(
            row["input_revision_sha256"],
            "candidate.input_revision_sha256",
        )
        row_created_at = _required_datetime(row["created_at"], "candidate.created_at")
        if (
            candidate.candidate_id != row_candidate_id
            or candidate.project_id != row_project_id
            or candidate.job_id != row_job_id
        ):
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI candidate row binding mismatch"
            )
        if (
            candidate.job_id != job.job_id
            or candidate.project_id != job.project_id
            or candidate.task_type != job.task_type
            or candidate.input_revision_sha256 != job.input_revision_sha256
            or candidate.prompt_version != job.prompt_version
        ):
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI candidate parent binding mismatch"
            )
        if (
            candidate.task_type.value != row_task_type
            or candidate.input_revision_sha256 != row_input_revision
            or candidate.created_at != row_created_at
        ):
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI candidate row binding mismatch"
            )
        allowed_pairs = job.input_revision.source_pairs
        if any(
            (item.source_entry_id, item.source_content_sha256) not in allowed_pairs
            for item in candidate.evidence
        ):
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI candidate evidence binding mismatch"
            )
        return candidate

    def job_for_candidate(
        self,
        project_id: str,
        candidate_id: str,
    ) -> MonitoringAiJob:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT job_id FROM monitoring_ai_candidates
                WHERE project_id = ? AND candidate_id = ?
                """,
                (project_id, candidate_id),
            ).fetchone()
        if row is None:
            raise MonitoringAiRepositoryError("monitoring AI candidate not found")
        return self.get(project_id, row["job_id"])

    def decide_candidate(
        self,
        project_id: str,
        candidate_id: str,
        *,
        decision: MonitoringAiCandidateStatus,
        actor: str,
        reason: str,
        current_input_revision_sha256: str,
    ) -> MonitoringAiCandidate:
        if decision not in {
            MonitoringAiCandidateStatus.ACCEPTED,
            MonitoringAiCandidateStatus.REJECTED,
        }:
            raise ValueError("candidate decision must be accepted or rejected")
        job = self.job_for_candidate(project_id, candidate_id)
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT candidate_id, project_id, job_id, task_type, status,
                       input_revision_sha256, candidate_json, created_at
                FROM monitoring_ai_candidates
                WHERE project_id = ? AND candidate_id = ?
                """,
                (project_id, candidate_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise MonitoringAiRepositoryError("monitoring AI candidate not found")
            candidate = self._candidate_from_row(row, job)
            if (
                row["status"] != MonitoringAiCandidateStatus.PROPOSED.value
                or row["input_revision_sha256"] != current_input_revision_sha256
            ):
                connection.rollback()
                raise MonitoringAiStateConflictError(
                    "candidate is stale or no longer proposed"
                )
            updated = connection.execute(
                """
                UPDATE monitoring_ai_candidates
                SET status = ?, decided_at = ?, decided_by = ?,
                    decision_reason = ?
                WHERE project_id = ? AND candidate_id = ? AND status = ?
                  AND input_revision_sha256 = ?
                """,
                (
                    decision.value,
                    _iso(now),
                    actor[:160],
                    reason[:2_000],
                    project_id,
                    candidate_id,
                    MonitoringAiCandidateStatus.PROPOSED.value,
                    current_input_revision_sha256,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise MonitoringAiStateConflictError("candidate decision lost CAS")
            connection.commit()
        return candidate.model_copy(update={"status": decision})

    def decide_candidate_idempotent_exclusive(
        self,
        project_id: str,
        candidate_id: str,
        *,
        decision: MonitoringAiCandidateStatus,
        actor: str,
        reason: str,
        current_input_revision_sha256: str,
    ) -> tuple[MonitoringAiCandidate, bool]:
        """Record one durable decision and allow at most one accepted sibling."""

        if decision not in {
            MonitoringAiCandidateStatus.ACCEPTED,
            MonitoringAiCandidateStatus.REJECTED,
        }:
            raise ValueError("candidate decision must be accepted or rejected")
        job = self.job_for_candidate(project_id, candidate_id)
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT candidate_id, project_id, job_id, task_type, status,
                       input_revision_sha256, candidate_json, created_at
                FROM monitoring_ai_candidates
                WHERE project_id = ? AND candidate_id = ?
                """,
                (project_id, candidate_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise MonitoringAiRepositoryError("monitoring AI candidate not found")
            candidate = self._candidate_from_row(row, job)
            if row["input_revision_sha256"] != current_input_revision_sha256:
                connection.rollback()
                raise MonitoringAiStateConflictError(
                    "candidate input revision is stale"
                )
            current_status = MonitoringAiCandidateStatus(row["status"])
            if current_status == decision:
                connection.commit()
                return candidate, True
            if current_status != MonitoringAiCandidateStatus.PROPOSED:
                connection.rollback()
                raise MonitoringAiStateConflictError(
                    "candidate already has the opposite or terminal decision"
                )
            if decision == MonitoringAiCandidateStatus.ACCEPTED:
                accepted = connection.execute(
                    """
                    SELECT candidate_id FROM monitoring_ai_candidates
                    WHERE project_id = ? AND job_id = ? AND status = ?
                    LIMIT 1
                    """,
                    (
                        project_id,
                        row["job_id"],
                        MonitoringAiCandidateStatus.ACCEPTED.value,
                    ),
                ).fetchone()
                if accepted is not None:
                    connection.rollback()
                    raise MonitoringAiStateConflictError(
                        "another candidate from this recommendation is accepted"
                    )
            updated = connection.execute(
                """
                UPDATE monitoring_ai_candidates
                SET status = ?, decided_at = ?, decided_by = ?,
                    decision_reason = ?
                WHERE project_id = ? AND candidate_id = ? AND status = ?
                  AND input_revision_sha256 = ?
                """,
                (
                    decision.value,
                    _iso(now),
                    actor[:160],
                    reason[:2_000],
                    project_id,
                    candidate_id,
                    MonitoringAiCandidateStatus.PROPOSED.value,
                    current_input_revision_sha256,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise MonitoringAiStateConflictError("candidate decision lost CAS")
            if decision == MonitoringAiCandidateStatus.ACCEPTED:
                connection.execute(
                    """
                    UPDATE monitoring_ai_candidates
                    SET status = ?, decided_at = ?, decided_by = ?,
                        decision_reason = ?
                    WHERE project_id = ? AND job_id = ? AND candidate_id != ?
                      AND status = ? AND input_revision_sha256 = ?
                    """,
                    (
                        MonitoringAiCandidateStatus.REJECTED.value,
                        _iso(now),
                        "system_exclusive_selection",
                        "同组另一规则模板建议已由用户选择。",
                        project_id,
                        row["job_id"],
                        candidate_id,
                        MonitoringAiCandidateStatus.PROPOSED.value,
                        current_input_revision_sha256,
                    ),
                )
            connection.commit()
        return candidate.model_copy(update={"status": decision}), False

    def append_turn(
        self,
        project_id: str,
        job_id: str,
        *,
        actor: str,
        message: str,
        current_input_revision_sha256: str,
    ) -> MonitoringAiConversationTurn:
        job = self.get(project_id, job_id)
        if job.input_revision_sha256 != current_input_revision_sha256:
            raise MonitoringAiStateConflictError("conversation input revision is stale")
        turn = MonitoringAiConversationTurn(
            turn_id=f"monturn_{uuid4().hex}",
            project_id=project_id,
            job_id=job_id,
            actor=actor.strip(),
            message=message.strip(),
            input_revision_sha256=current_input_revision_sha256,
            created_at=self.clock(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO monitoring_ai_conversation_turns(
                    turn_id, project_id, job_id, actor, message,
                    input_revision_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn.turn_id,
                    turn.project_id,
                    turn.job_id,
                    turn.actor,
                    turn.message,
                    turn.input_revision_sha256,
                    _iso(turn.created_at),
                ),
            )
        return turn

    def turns(
        self,
        project_id: str,
        job_id: str,
    ) -> tuple[MonitoringAiConversationTurn, ...]:
        job = self.get(project_id, job_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM monitoring_ai_conversation_turns
                WHERE project_id = ? AND job_id = ?
                ORDER BY created_at, turn_id
                """,
                (project_id, job_id),
            ).fetchall()
        return tuple(self._turn_from_row(row, job) for row in rows)

    @staticmethod
    def _turn_from_row(
        row: sqlite3.Row,
        job: MonitoringAiJob,
    ) -> MonitoringAiConversationTurn:
        """Rehydrate one conversation turn with strict row/parent bindings."""

        row_project_id = _required_text(row["project_id"], "turn.project_id")
        row_job_id = _required_text(row["job_id"], "turn.job_id")
        row_input_revision = _required_sha256(
            row["input_revision_sha256"],
            "turn.input_revision_sha256",
        )
        if (
            row_project_id != job.project_id
            or row_job_id != job.job_id
            or row_input_revision != job.input_revision_sha256
        ):
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI conversation turn parent binding mismatch"
            )
        try:
            row_created_at = _required_datetime(row["created_at"], "turn.created_at")
        except MonitoringAiRepositoryError as exc:
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI conversation turn is invalid"
            ) from exc
        try:
            turn = MonitoringAiConversationTurn(
                turn_id=_required_text(row["turn_id"], "turn.turn_id"),
                project_id=row_project_id,
                job_id=row_job_id,
                actor=_required_text(row["actor"], "turn.actor"),
                message=_required_text(row["message"], "turn.message"),
                input_revision_sha256=row_input_revision,
                created_at=row_created_at,
            )
        except MonitoringAiRepositoryError:
            raise
        except (TypeError, ValueError) as exc:
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI conversation turn is invalid"
            ) from exc
        if turn.created_at != row_created_at:
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI conversation turn row binding mismatch"
            )
        return turn

    @staticmethod
    def _validated_job_inputs(
        row: sqlite3.Row,
        *,
        strict_input_identity: bool = True,
    ) -> tuple[MonitoringAiInputRevision, dict[str, Any]]:
        try:
            input_revision = MonitoringAiInputRevision.model_validate_json(
                row["input_revision_json"]
            )
            payload = json.loads(row["input_payload_json"])
        except (TypeError, ValueError) as exc:
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI job input is invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI input payload must be an object"
            )
        if (
            strict_input_identity
            and input_revision.revision_sha256 != row["input_revision_sha256"]
        ):
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI input revision hash mismatch"
            )
        if content_sha256(payload) != row["input_payload_sha256"]:
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI input payload hash mismatch"
            )
        if strict_input_identity:
            expected_job_id = "monai_" + content_sha256(
                {
                    "project_id": row["project_id"],
                    "task_type": row["task_type"],
                    "business_key": row["business_key"],
                    "input_revision_sha256": row["input_revision_sha256"],
                    "input_payload_sha256": row["input_payload_sha256"],
                    "prompt_version": row["prompt_version"],
                    "profile_id": row["profile_id"],
                    "provider": row["provider"],
                    "requested_model": row["requested_model"],
                }
            )[:28]
            if row["job_id"] != expected_job_id:
                raise MonitoringAiRepositoryError(
                    "persisted monitoring AI job identity mismatch"
                )
        return input_revision, payload

    @staticmethod
    def _job(
        row: sqlite3.Row,
        *,
        strict_input_identity: bool = True,
    ) -> MonitoringAiJob:
        try:
            job_id = _required_text(row["job_id"], "job_id")
            project_id = _required_text(row["project_id"], "project_id")
            business_key = _required_text(row["business_key"], "business_key")
            input_revision_sha256 = _required_sha256(
                row["input_revision_sha256"],
                "input_revision_sha256",
            )
            input_payload_sha256 = _required_sha256(
                row["input_payload_sha256"],
                "input_payload_sha256",
            )
            prompt_version = _required_text(row["prompt_version"], "prompt_version")
            profile_id = _required_text(row["profile_id"], "profile_id")
            provider = _required_text(row["provider"], "provider")
            requested_model = _required_text(
                row["requested_model"],
                "requested_model",
            )
            output_sha256 = _optional_sha256(row["output_sha256"], "output_sha256")
            input_revision, _ = MonitoringAiRepository._validated_job_inputs(
                row,
                strict_input_identity=strict_input_identity,
            )
            task_type = MonitoringAiTaskType(row["task_type"])
            status = MonitoringAiJobStatus(row["status"])
            attempt_count = _sqlite_int(
                row["attempt_count"],
                "attempt_count",
                minimum=0,
            )
            max_attempts = _sqlite_int(
                row["max_attempts"],
                "max_attempts",
                minimum=1,
            )
            lease_expires_at = _datetime(row["lease_expires_at"])
            contract_retired_at = _datetime(row["contract_retired_at"])
            created_at = _required_datetime(row["created_at"], "created_at")
            updated_at = _required_datetime(row["updated_at"], "updated_at")
            retryable = _sqlite_bool(row["retryable"], "retryable")
            return MonitoringAiJob(
                job_id=job_id,
                project_id=project_id,
                task_type=task_type,
                status=status,
                business_key=business_key,
                input_revision=input_revision,
                input_revision_sha256=input_revision_sha256,
                input_payload_sha256=input_payload_sha256,
                prompt_version=prompt_version,
                profile_id=profile_id,
                provider=provider,
                requested_model=requested_model,
                response_model=row["response_model"],
                attempt_count=attempt_count,
                max_attempts=max_attempts,
                lease_owner=row["lease_owner"],
                lease_expires_at=lease_expires_at,
                output_sha256=output_sha256,
                failure_code=row["failure_code"],
                failure_message=row["failure_message"],
                retryable=retryable,
                contract_retirement_code=row["contract_retirement_code"],
                contract_retirement_reason=row["contract_retirement_reason"],
                contract_retired_at=contract_retired_at,
                created_at=created_at,
                updated_at=updated_at,
            )
        except MonitoringAiRepositoryError:
            raise
        except (TypeError, ValueError) as exc:
            raise MonitoringAiRepositoryError(
                "persisted monitoring AI job root is invalid"
            ) from exc

    @staticmethod
    def _deterministic_repair(
        row: sqlite3.Row,
        *,
        expected_project_id: str = "",
        expected_job_id: str = "",
    ) -> dict[str, Any]:
        repair_id = _required_text(row["repair_id"], "repair_id")
        project_id = _required_text(row["project_id"], "project_id")
        job_id = _required_text(row["job_id"], "job_id")
        candidate_id = _required_text(row["candidate_id"], "candidate_id")
        idempotency_key = _required_text(
            row["idempotency_key"], "idempotency_key"
        )
        request_sha256 = _required_sha256(row["request_sha256"], "request_sha256")
        original_status = _required_text(row["original_status"], "original_status")
        original_failure_code = _required_text(
            row["original_failure_code"], "original_failure_code"
        )
        original_failure_message = _required_text(
            row["original_failure_message"], "original_failure_message"
        )
        original_attempt_count = _sqlite_int(
            row["original_attempt_count"],
            "original_attempt_count",
            minimum=1,
        )
        output_sha256 = _required_sha256(row["output_sha256"], "output_sha256")
        actor = _required_text(row["actor"], "actor")
        reason = _required_text(row["reason"], "reason")
        created_at = _required_datetime(row["created_at"], "created_at")
        if expected_project_id and project_id != expected_project_id:
            raise MonitoringAiRepositoryError(
                "persisted deterministic repair project binding mismatch"
            )
        if expected_job_id and job_id != expected_job_id:
            raise MonitoringAiRepositoryError(
                "persisted deterministic repair job binding mismatch"
            )
        raw_output_json = row["raw_output_json"]
        if raw_output_json:
            try:
                raw_output = json.loads(raw_output_json)
            except (TypeError, ValueError) as exc:
                raise MonitoringAiRepositoryError(
                    "persisted deterministic repair raw output is invalid"
                ) from exc
            if content_sha256(raw_output) != output_sha256:
                raise MonitoringAiRepositoryError(
                    "persisted deterministic repair raw output hash mismatch"
                )
        else:
            # Preserve repair rows created before raw_output_json was added;
            # those rows have no payload available to revalidate.
            raw_output = None
        try:
            provenance = json.loads(row["provenance_json"])
        except (TypeError, ValueError) as exc:
            raise MonitoringAiRepositoryError(
                "persisted deterministic repair provenance is invalid"
            ) from exc
        if not isinstance(provenance, dict):
            raise MonitoringAiRepositoryError(
                "persisted deterministic repair provenance must be an object"
            )
        return {
            "repair_id": repair_id,
            "project_id": project_id,
            "job_id": job_id,
            "candidate_id": candidate_id,
            "idempotency_key": idempotency_key,
            "request_sha256": request_sha256,
            "original_status": original_status,
            "original_failure_code": original_failure_code,
            "original_failure_message": original_failure_message,
            "original_attempt_count": original_attempt_count,
            "output_sha256": output_sha256,
            "raw_output": raw_output,
            "provenance": provenance,
            "actor": actor,
            "reason": reason,
            "created_at": _iso(created_at),
        }
