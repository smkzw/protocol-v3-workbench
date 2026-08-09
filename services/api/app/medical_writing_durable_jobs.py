"""Durable medical-writing job store and local worker lifecycle.

This module implements one shared SQLite-backed durable-job contract for all
medical-writing long-running tasks (competitor triage, section AI candidates,
reference translation). It reuses the synopsis-proven semantics:

- Stable idempotent ``job_id`` scoped by project + job type + business key + request hash.
- Claim-token lease with heartbeat renewal; CAS complete/fail/cancel.
- Stale owners and late provider responses cannot overwrite a newer or terminal state.
- Monotonic progress (percent/step never move backward).
- Cold-startup recovery: queued / retry_wait / running-with-expired-lease are requeued.
- Graceful bounded worker shutdown (single overall deadline).
- Strict project isolation: every query requires ``project_id``.

FastAPI ``BackgroundTasks`` may wake the local worker, but the SQLite store is
the persistent truth.  A future Celery adapter can replace the thread-based
executor via the :class:`DurableJobExecutor` protocol without changing the HTTP
or persisted job/artifact contracts.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from packages.contracts.workbench_contracts import (
    DurableJobCancelResult,
    DurableJobClaimResult,
    DurableJobCreateRequest,
    DurableJobNotFound,
    DurableJobProgressPayload,
    DurableJobRecord,
    DurableJobRequestConflict,
    DurableJobRetryResult,
    DurableJobStartResponse,
)

SCHEMA_VERSION = 1
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_ACTIVE_STATES = frozenset({"queued", "running", "retry_wait"})
DEFAULT_LEASE_SECONDS = 600.0
DEFAULT_HEARTBEAT_INTERVAL = 30.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_SWEEPER_INTERVAL_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _lease_is_expired(lease_expires_at: str, now: datetime) -> bool:
    """Return True if the lease string is empty, malformed, or <= *now*."""
    if not lease_expires_at:
        return True
    expires_at = _parse_iso(lease_expires_at)
    if expires_at is None:
        return True
    return expires_at <= now


def _stable_job_id(project_id: str, job_type: str, business_key: str, request_hash: str) -> str:
    raw = f"{project_id}|{job_type}|{business_key}|{request_hash}".encode("utf-8")
    return "mwjob_" + hashlib.sha256(raw).hexdigest()[:24]


def _row_to_record(row: sqlite3.Row) -> DurableJobRecord:
    progress_dict: Dict[str, Any] = {}
    raw_progress = row["progress_json"]
    if raw_progress:
        try:
            progress_dict = json.loads(raw_progress)
        except (json.JSONDecodeError, TypeError):
            progress_dict = {}
    return DurableJobRecord(
        job_id=row["job_id"],
        project_id=row["project_id"],
        job_type=row["job_type"],
        business_key=row["business_key"],
        request_hash=row["request_hash"],
        status=row["status"],
        claim_token=row["claim_token"] or "",
        lease_expires_at=row["lease_expires_at"] or "",
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        progress=DurableJobProgressPayload(**progress_dict),
        error_summary=row["error_summary"] or "",
        input_hash=row["input_hash"] or "",
        output_hash=row["output_hash"] or "",
        artifact_locator=row["artifact_locator"] or "",
        provider=row["provider"] or "",
        model=row["model"] or "",
        schema_version=int(row["schema_version"]),
        payload_json=row["payload_json"] or "",
        created_at=_parse_iso(row["created_at"]) or _utcnow(),
        updated_at=_parse_iso(row["updated_at"]) or _utcnow(),
        started_at=_parse_iso(row["started_at"]) if "started_at" in row.keys() else None,
        finished_at=_parse_iso(row["finished_at"]) if "finished_at" in row.keys() else None,
        cancelled_at=_parse_iso(row["cancelled_at"]) if "cancelled_at" in row.keys() else None,
        created_by=row["created_by"] or "system",
    )


def _is_newer_progress(current: DurableJobProgressPayload, candidate: DurableJobProgressPayload) -> bool:
    """Return True only if *candidate* represents forward progress.

    ``percent`` and ``step`` must never decrease.  ``phase``/``message`` may
    change freely as long as the numeric dimensions are not regressing.
    """
    if candidate.percent < current.percent - 1e-9:
        return False
    if candidate.step < current.step:
        return False
    return True


# ---------------------------------------------------------------------------
# Executor protocol
# ---------------------------------------------------------------------------

class DurableJobResult:
    """Concrete container returned by executors."""

    def __init__(
        self,
        *,
        output_hash: str = "",
        artifact_locator: str = "",
        provider: str = "",
        model: str = "",
        progress: Optional[DurableJobProgressPayload] = None,
        error: str = "",
        retryable: bool = False,
    ) -> None:
        self.output_hash = output_hash
        self.artifact_locator = artifact_locator
        self.provider = provider
        self.model = model
        self.progress = progress
        self.error = error
        self.retryable = retryable


class DurableJobExecutor(Protocol):
    """Future Celery/RQ adapter boundary.

    A local thread-based executor and a future Celery task both implement this
    protocol.  The HTTP API and persisted job/artifact contracts must not change
    when the execution backend is swapped.
    """

    job_type: str

    def execute(
        self,
        job: DurableJobRecord,
        claim_token: str,
        cancel_check: Callable[[], bool],
        heartbeat: Callable[[DurableJobProgressPayload], bool],
    ) -> DurableJobResult:
        ...


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class DurableJobStore:
    """SQLite-backed durable-job store with claim/lease/CAS/cancel/recovery.

    Concurrency model: every mutating operation opens a ``BEGIN IMMEDIATE``
    transaction so competing claims are serialized at the SQLite level.  The
    claim_token + lease-expiry + CAS guard ensures that a stale owner or a late
    provider response can never overwrite a newer or terminal state.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("durable job lease_seconds must be positive")
        if heartbeat_interval_seconds <= 0:
            raise ValueError("durable job heartbeat_interval_seconds must be positive")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lease_seconds = float(lease_seconds)
        self.heartbeat_interval_seconds = float(heartbeat_interval_seconds)
        self._lock = threading.Lock()
        self._init_schema()

    # -- schema -----------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS durable_mw_jobs (
                    job_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    business_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    claim_token TEXT NOT NULL DEFAULT '',
                    lease_expires_at TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    progress_json TEXT NOT NULL DEFAULT '{}',
                    error_summary TEXT NOT NULL DEFAULT '',
                    input_hash TEXT NOT NULL DEFAULT '',
                    output_hash TEXT NOT NULL DEFAULT '',
                    artifact_locator TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    payload_json TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT '',
                    finished_at TEXT NOT NULL DEFAULT '',
                    cancelled_at TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT 'system',
                    claim_incremented_attempt INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            # Backward-compatible migration for existing DBs created before
            # the claim_incremented_attempt column existed.  ALTER TABLE ADD
            # COLUMN is additive and never drops or recreates rows.
            existing_cols = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(durable_mw_jobs)"
                ).fetchall()
            }
            if "claim_incremented_attempt" not in existing_cols:
                connection.execute(
                    "ALTER TABLE durable_mw_jobs "
                    "ADD COLUMN claim_incremented_attempt INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_durable_mw_business
                ON durable_mw_jobs(project_id, job_type, business_key)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_durable_mw_status
                ON durable_mw_jobs(status, lease_expires_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_durable_mw_project
                ON durable_mw_jobs(project_id, status)
                """
            )
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError("durable mw job SQLite integrity check failed")

    # -- create / dedupe --------------------------------------------------

    def create_or_reuse(self, request: DurableJobCreateRequest) -> DurableJobStartResponse:
        """Create a new job or reuse an existing one with the same identity.

        Raises :class:`DurableJobRequestConflict` if the same business key is
        reused with a *different* ``request_hash``.
        """
        job_id = _stable_job_id(
            request.project_id,
            request.job_type,
            request.business_key,
            request.request_hash,
        )
        now = _utcnow()
        now_iso = _iso(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT job_id, request_hash, status
                FROM durable_mw_jobs
                WHERE project_id = ? AND job_type = ? AND business_key = ?
                """,
                (request.project_id, request.job_type, request.business_key),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request.request_hash:
                    connection.rollback()
                    raise DurableJobRequestConflict(
                        f"business key {request.business_key!r} reused with a different request hash"
                    )
                connection.commit()
                return DurableJobStartResponse(
                    job_id=existing["job_id"],
                    project_id=request.project_id,
                    status=existing["status"],
                    reused=True,
                )
            connection.execute(
                """
                INSERT INTO durable_mw_jobs(
                    job_id, project_id, job_type, business_key, request_hash,
                    status, claim_token, lease_expires_at, attempt_count,
                    max_attempts, progress_json, error_summary, input_hash,
                    output_hash, artifact_locator, provider, model,
                    schema_version, payload_json, created_at, updated_at,
                    created_by
                ) VALUES (?, ?, ?, ?, ?, 'queued', '', '', 1, ?, '{}', '', ?, '', '', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    request.project_id,
                    request.job_type,
                    request.business_key,
                    request.request_hash,
                    request.max_attempts,
                    request.input_hash,
                    request.provider,
                    request.model,
                    SCHEMA_VERSION,
                    request.payload_json,
                    now_iso,
                    now_iso,
                    request.created_by,
                ),
            )
            connection.commit()
        return DurableJobStartResponse(
            job_id=job_id,
            project_id=request.project_id,
            status="queued",
            reused=False,
        )

    # -- read -------------------------------------------------------------

    def get(self, project_id: str, job_id: str) -> DurableJobRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM durable_mw_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
        if row is None:
            raise DurableJobNotFound(
                f"durable job not found: project={project_id} job={job_id}"
            )
        return _row_to_record(row)

    def get_by_business_key(
        self, project_id: str, job_type: str, business_key: str
    ) -> DurableJobRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM durable_mw_jobs
                WHERE project_id = ? AND job_type = ? AND business_key = ?
                """,
                (project_id, job_type, business_key),
            ).fetchone()
        if row is None:
            raise DurableJobNotFound(
                f"durable job not found: project={project_id} "
                f"type={job_type} key={business_key}"
            )
        return _row_to_record(row)

    def list_by_project(
        self,
        project_id: str,
        *,
        job_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[DurableJobRecord]:
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if job_type is not None:
            clauses.append("job_type = ?")
            params.append(job_type)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        sql = (
            "SELECT * FROM durable_mw_jobs WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at ASC"
        )
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_row_to_record(r) for r in rows]

    def check_ownership(
        self, project_id: str, job_id: str, claim_token: str
    ) -> bool:
        """Return True if *claim_token* still owns a live lease on *job_id*.

        Ownership is false when status is not ``running``, the token differs,
        or the lease has expired.  This is the transactional ownership probe
        used by the worker's cooperative cancel_check.
        """
        now = _utcnow()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT status, claim_token, lease_expires_at
                FROM durable_mw_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
        if row is None:
            return False
        if row["status"] != "running":
            return False
        if row["claim_token"] != claim_token:
            return False
        return not _lease_is_expired(row["lease_expires_at"], now)

    # -- claim / lease / heartbeat ---------------------------------------

    def claim(
        self, project_id: str, job_id: str, *, claim_token: Optional[str] = None
    ) -> DurableJobClaimResult:
        """Atomically claim a queued/retry_wait/expired-lease job.

        Returns ``claimed=False`` if another owner holds a live lease or the
        job is terminal.  The caller should detach and let the current owner
        finish.
        """
        token = claim_token or uuid.uuid4().hex
        now = _utcnow()
        lease_expires = now + timedelta(seconds=self.lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, claim_token, lease_expires_at, attempt_count,
                       max_attempts
                FROM durable_mw_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise DurableJobNotFound(
                    f"durable job not found: project={project_id} job={job_id}"
                )
            status = row["status"]
            if status in TERMINAL_STATES:
                connection.commit()
                return DurableJobClaimResult(
                    claimed=False,
                    claim_token="",
                    job=self._fetch_record_unlocked(connection, project_id, job_id),
                )
            if status == "running" and not _lease_is_expired(
                row["lease_expires_at"], now
            ):
                connection.commit()
                return DurableJobClaimResult(
                    claimed=False,
                    claim_token="",
                    job=self._fetch_record_unlocked(connection, project_id, job_id),
                )
            # Claimable: queued, retry_wait, or running-with-expired-lease.
            next_attempt = int(row["attempt_count"])
            incremented = 0
            if status == "retry_wait":
                next_attempt = next_attempt + 1
                incremented = 1
            connection.execute(
                """
                UPDATE durable_mw_jobs
                SET status = 'running', claim_token = ?,
                    lease_expires_at = ?, attempt_count = ?,
                    claim_incremented_attempt = ?,
                    error_summary = '',
                    started_at = CASE WHEN started_at = '' THEN ? ELSE started_at END,
                    updated_at = ?
                WHERE project_id = ? AND job_id = ?
                """,
                (
                    token,
                    _iso(lease_expires),
                    next_attempt,
                    incremented,
                    _iso(now),
                    _iso(now),
                    project_id,
                    job_id,
                ),
            )
            connection.commit()
        return DurableJobClaimResult(
            claimed=True,
            claim_token=token,
            job=self.get(project_id, job_id),
        )

    def heartbeat(
        self,
        project_id: str,
        job_id: str,
        claim_token: str,
        progress: Optional[DurableJobProgressPayload] = None,
    ) -> bool:
        """Renew the lease and optionally advance monotonic progress.

        Returns False if the caller no longer owns the claim (lost lease,
        terminal state, or expired lease even though no replacement has
        claimed yet), so the executor should detach.
        """
        now = _utcnow()
        lease_expires = now + timedelta(seconds=self.lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, claim_token, lease_expires_at, progress_json
                FROM durable_mw_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise DurableJobNotFound(
                    f"durable job not found: project={project_id} job={job_id}"
                )
            # Lease-expiry invalidation: reject even when token matches.
            if (
                row["status"] != "running"
                or row["claim_token"] != claim_token
                or _lease_is_expired(row["lease_expires_at"], now)
            ):
                connection.commit()
                return False
            # Monotonic progress guard.
            set_clause = "lease_expires_at = ?, updated_at = ?"
            params: list[Any] = [_iso(lease_expires), _iso(now)]
            if progress is not None:
                try:
                    current = DurableJobProgressPayload(
                        **json.loads(row["progress_json"] or "{}")
                    )
                except (json.JSONDecodeError, TypeError, Exception):
                    current = DurableJobProgressPayload()
                if _is_newer_progress(current, progress):
                    set_clause = (
                        "progress_json = ?, lease_expires_at = ?, updated_at = ?"
                    )
                    params = [
                        json.dumps(progress.model_dump(mode="json")),
                        _iso(lease_expires),
                        _iso(now),
                    ]
                # If progress would regress, we still renew the lease
                # (set_clause stays "lease_expires_at, updated_at" only).
            connection.execute(
                f"""
                UPDATE durable_mw_jobs
                SET {set_clause}
                WHERE project_id = ? AND job_id = ?
                  AND status = 'running' AND claim_token = ?
                """,
                (*params, project_id, job_id, claim_token),
            )
            connection.commit()
        return True

    # -- CAS complete / fail ---------------------------------------------

    def complete(
        self,
        project_id: str,
        job_id: str,
        claim_token: str,
        *,
        output_hash: str = "",
        artifact_locator: str = "",
        provider: str = "",
        model: str = "",
        final_progress: Optional[DurableJobProgressPayload] = None,
    ) -> bool:
        """CAS-complete: only the current running owner with a live lease may complete.

        Stale owners (expired lease), cancelled jobs, and late provider
        responses are rejected — no state/progress/artifact mutation occurs.
        """
        now = _utcnow()
        now_iso = _iso(now)
        if final_progress is not None:
            progress_json = json.dumps(final_progress.model_dump(mode="json"))
        else:
            progress_json = ""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, claim_token, lease_expires_at, progress_json
                FROM durable_mw_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise DurableJobNotFound(
                    f"durable job not found: project={project_id} job={job_id}"
                )
            # Lease-expiry invalidation: reject even when token matches.
            if (
                row["status"] != "running"
                or row["claim_token"] != claim_token
                or _lease_is_expired(row["lease_expires_at"], now)
            ):
                connection.commit()
                return False
            # Monotonic guard: final progress must not regress.
            effective_progress = progress_json
            if progress_json:
                try:
                    current = DurableJobProgressPayload(
                        **json.loads(row["progress_json"] or "{}")
                    )
                    candidate = final_progress  # type: ignore[assignment]
                    if candidate is not None and not _is_newer_progress(current, candidate):
                        effective_progress = ""  # skip regression
                except Exception:
                    pass
            connection.execute(
                """
                UPDATE durable_mw_jobs
                SET status = 'completed', claim_token = '', lease_expires_at = '',
                    output_hash = ?, artifact_locator = ?, provider = ?, model = ?,
                    progress_json = CASE WHEN ? != '' THEN ? ELSE progress_json END,
                    claim_incremented_attempt = 0,
                    finished_at = ?, updated_at = ?
                WHERE project_id = ? AND job_id = ?
                  AND status = 'running' AND claim_token = ?
                """,
                (
                    output_hash, artifact_locator, provider, model,
                    effective_progress, effective_progress,
                    now_iso, now_iso,
                    project_id, job_id, claim_token,
                ),
            )
            connection.commit()
        return True

    def fail(
        self,
        project_id: str,
        job_id: str,
        claim_token: str,
        *,
        error_summary: str,
        retryable: bool = True,
    ) -> bool:
        """CAS-fail: mark the job failed or retry_wait depending on attempts.

        Returns True only if the caller still owns a live claim.
        """
        now = _utcnow()
        now_iso = _iso(now)
        truncated_error = error_summary[:4_000]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, claim_token, lease_expires_at, attempt_count,
                       max_attempts
                FROM durable_mw_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise DurableJobNotFound(
                    f"durable job not found: project={project_id} job={job_id}"
                )
            # Lease-expiry invalidation: reject even when token matches.
            if (
                row["status"] != "running"
                or row["claim_token"] != claim_token
                or _lease_is_expired(row["lease_expires_at"], now)
            ):
                connection.commit()
                return False
            attempts = int(row["attempt_count"])
            max_attempts = int(row["max_attempts"])
            if retryable and attempts < max_attempts:
                new_status = "retry_wait"
            else:
                new_status = "failed"
            connection.execute(
                """
                UPDATE durable_mw_jobs
                SET status = ?, claim_token = '', lease_expires_at = '',
                    error_summary = ?, claim_incremented_attempt = 0,
                    finished_at = CASE WHEN ? = 'failed' THEN ? ELSE finished_at END,
                    updated_at = ?
                WHERE project_id = ? AND job_id = ?
                  AND status = 'running' AND claim_token = ?
                """,
                (
                    new_status,
                    truncated_error,
                    new_status,
                    now_iso,
                    now_iso,
                    project_id,
                    job_id,
                    claim_token,
                ),
            )
            connection.commit()
        return True

    # -- cancel / retry --------------------------------------------------

    def cancel(self, project_id: str, job_id: str) -> DurableJobCancelResult:
        now_iso = _iso(_utcnow())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, cancelled_at
                FROM durable_mw_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise DurableJobNotFound(
                    f"durable job not found: project={project_id} job={job_id}"
                )
            already_cancelled = bool(row["cancelled_at"])
            if not already_cancelled:
                connection.execute(
                    """
                    UPDATE durable_mw_jobs
                    SET status = 'cancelled', cancelled_at = ?,
                        claim_token = '', lease_expires_at = '',
                        claim_incremented_attempt = 0,
                        finished_at = CASE WHEN finished_at = '' THEN ? ELSE finished_at END,
                        updated_at = ?
                    WHERE project_id = ? AND job_id = ?
                      AND status NOT IN ('completed', 'cancelled')
                    """,
                    (now_iso, now_iso, now_iso, project_id, job_id),
                )
            final_status_row = connection.execute(
                "SELECT status FROM durable_mw_jobs WHERE project_id = ? AND job_id = ?",
                (project_id, job_id),
            ).fetchone()
            connection.commit()
        final_status = final_status_row["status"] if final_status_row else "cancelled"
        return DurableJobCancelResult(
            job_id=job_id,
            status=final_status,
            cancelled=final_status == "cancelled",
        )

    def retry(self, project_id: str, job_id: str) -> DurableJobRetryResult:
        """Requeue a failed/retry_wait/cancelled job for a fresh attempt.

        ``queued``, ``running``, and ``completed`` are rejected to prevent
        duplicate execution or stealing a live claim.
        """
        now_iso = _iso(_utcnow())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, attempt_count, max_attempts
                FROM durable_mw_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise DurableJobNotFound(
                    f"durable job not found: project={project_id} job={job_id}"
                )
            status = row["status"]
            if status in ("queued", "running", "completed"):
                connection.commit()
                return DurableJobRetryResult(
                    job_id=job_id, status=status, requeued=False
                )
            attempts = int(row["attempt_count"])
            max_attempts = int(row["max_attempts"])
            new_attempts = attempts if attempts < max_attempts else 1
            connection.execute(
                """
                UPDATE durable_mw_jobs
                SET status = 'queued', claim_token = '', lease_expires_at = '',
                    error_summary = '', finished_at = '',
                    cancelled_at = '', attempt_count = ?,
                    claim_incremented_attempt = 0,
                    updated_at = ?
                WHERE project_id = ? AND job_id = ?
                """,
                (new_attempts, now_iso, project_id, job_id),
            )
            connection.commit()
        return DurableJobRetryResult(
            job_id=job_id, status="queued", requeued=True
        )

    # -- graceful release (lifecycle shutdown) ---------------------------

    def release_claim(
        self, project_id: str, job_id: str, claim_token: str
    ) -> bool:
        """CAS release: transition a *running* job back to *queued* so a new
        process can reclaim it immediately without waiting for lease expiry.

        This is the graceful-shutdown counterpart of lease-expiry recovery.
        Unlike :meth:`requeue_expired_leases`, it does **not** require the
        lease to have expired — the owner voluntarily releases it.  However,
        the lease MUST still be live at the transactional CAS boundary: an
        expired, malformed, or empty lease returns False without mutation.

        Fail-closed for:
        - token mismatch (wrong/lost owner)
        - expired/malformed/empty lease (lost ownership)
        - terminal or cancelled state
        - any replacement owner already running

        Attempt accounting: decrements ``attempt_count`` by 1 (floor 1) **only
        if** the current claim originated from ``retry_wait`` and therefore
        incremented it.  Claims from ``queued`` or expired ``running`` did not
        increment, so release preserves the count.  The private
        ``claim_incremented_attempt`` column records this origin atomically at
        claim time and is cleared on release.
        """
        now = _utcnow()
        now_iso = _iso(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, claim_token, lease_expires_at, attempt_count,
                       claim_incremented_attempt
                FROM durable_mw_jobs
                WHERE project_id = ? AND job_id = ?
                """,
                (project_id, job_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise DurableJobNotFound(
                    f"durable job not found: project={project_id} job={job_id}"
                )
            # Require running, exact token, AND a still-live valid lease.
            # Expired/malformed/empty lease → False without mutation.
            if (
                row["status"] != "running"
                or row["claim_token"] != claim_token
                or _lease_is_expired(row["lease_expires_at"], now)
            ):
                connection.commit()
                return False
            current_attempt = int(row["attempt_count"])
            incremented = int(row["claim_incremented_attempt"]) if row["claim_incremented_attempt"] is not None else 0
            # Only undo the attempt increment if this claim actually incremented.
            if incremented:
                restored_attempt = max(1, current_attempt - 1)
            else:
                restored_attempt = current_attempt
            connection.execute(
                """
                UPDATE durable_mw_jobs
                SET status = 'queued', claim_token = '', lease_expires_at = '',
                    attempt_count = ?, claim_incremented_attempt = 0,
                    error_summary = '',
                    updated_at = ?
                WHERE project_id = ? AND job_id = ?
                  AND status = 'running' AND claim_token = ?
                """,
                (restored_attempt, now_iso, project_id, job_id, claim_token),
            )
            connection.commit()
        return True

    # -- recovery --------------------------------------------------------

    def requeue_expired_leases(self) -> int:
        """Reset running jobs whose leases have expired back to queued.

        Stale owners that later try to complete will fail the CAS + lease guard.
        """
        now_iso = _iso(_utcnow())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE durable_mw_jobs
                SET status = 'queued', claim_token = '', lease_expires_at = '',
                    claim_incremented_attempt = 0,
                    updated_at = ?
                WHERE status = 'running'
                  AND lease_expires_at != ''
                  AND lease_expires_at <= ?
                """,
                (now_iso, now_iso),
            )
            connection.commit()
            return cursor.rowcount

    def recover_on_startup(self) -> int:
        """Cold-recovery: requeue queued/retry_wait/expired-running jobs.

        Called on service startup.  Returns the count of jobs left in a
        recoverable (non-terminal) state.
        """
        now_iso = _iso(_utcnow())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Running-with-expired-lease → queued.
            connection.execute(
                """
                UPDATE durable_mw_jobs
                SET status = 'queued', claim_token = '', lease_expires_at = '',
                    claim_incremented_attempt = 0,
                    updated_at = ?
                WHERE status = 'running'
                  AND lease_expires_at != ''
                  AND lease_expires_at <= ?
                """,
                (now_iso, now_iso),
            )
            cursor = connection.execute(
                """
                SELECT COUNT(*) as cnt FROM durable_mw_jobs
                WHERE status IN ('queued', 'retry_wait')
                """
            )
            recoverable = int(cursor.fetchone()["cnt"])
            connection.commit()
        return recoverable

    # -- internal helpers ------------------------------------------------

    def _fetch_record_unlocked(
        self, connection: sqlite3.Connection, project_id: str, job_id: str
    ) -> DurableJobRecord:
        row = connection.execute(
            "SELECT * FROM durable_mw_jobs WHERE project_id = ? AND job_id = ?",
            (project_id, job_id),
        ).fetchone()
        if row is None:
            raise DurableJobNotFound(
                f"durable job not found: project={project_id} job={job_id}"
            )
        return _row_to_record(row)


# ---------------------------------------------------------------------------
# Local worker / executor registry
# ---------------------------------------------------------------------------

class DurableJobWorker:
    """Thread-based local executor that drives registered :class:`DurableJobExecutor` instances.

    ``DurableJobWorker.wake`` is the single entry point that FastAPI
    ``BackgroundTasks`` (or a future Celery adapter) may call.  The worker
    claims the job, runs the executor under a heartbeat, and CAS-completes or
    CAS-fails the result.

    A periodic recovery sweeper daemon requeues jobs whose leases have expired
    so a service restart while a prior process's lease is still nominally live
    does not leave a job stuck forever.  The sweeper does not immediately steal
    live leases — it waits for expiry before requeuing.
    """

    def __init__(
        self,
        store: DurableJobStore,
        *,
        poll_interval_seconds: float = 0.05,
        sweeper_interval_seconds: float = DEFAULT_SWEEPER_INTERVAL_SECONDS,
        enable_sweeper: bool = True,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if sweeper_interval_seconds <= 0:
            raise ValueError("sweeper_interval_seconds must be positive")
        self.store = store
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.sweeper_interval_seconds = float(sweeper_interval_seconds)
        self._executors: Dict[str, DurableJobExecutor] = {}
        self._executor_lock = threading.Lock()
        self._threads: List[threading.Thread] = []
        self._threads_lock = threading.Lock()
        self._shutdown_requested = False
        self._sweeper_thread: Optional[threading.Thread] = None
        self._sweeper_stop = threading.Event()
        # Active claims owned by this worker's executors: set of (project_id,
        # job_id, claim_token) tuples.  Used only for graceful shutdown release.
        self._active_claims: set[tuple[str, str, str]] = set()
        self._active_claims_lock = threading.Lock()
        if enable_sweeper:
            self._start_sweeper()

    def register_executor(self, executor: DurableJobExecutor) -> None:
        with self._executor_lock:
            self._executors[executor.job_type] = executor

    def get_executor(self, job_type: str) -> Optional[DurableJobExecutor]:
        with self._executor_lock:
            return self._executors.get(job_type)

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown_requested

    def wake(self, project_id: str, job_id: str) -> None:
        """Wake the worker for a single job. Non-blocking: spawns a daemon thread."""
        if self._shutdown_requested:
            return
        try:
            record = self.store.get(project_id, job_id)
        except DurableJobNotFound:
            return
        executor = self.get_executor(record.job_type)
        if executor is None:
            return  # No executor registered; recovery/sweeper may pick it up later.
        if record.status in TERMINAL_STATES:
            return
        thread = threading.Thread(
            target=self._run_safe,
            kwargs={
                "project_id": project_id,
                "job_id": job_id,
                "executor": executor,
            },
            name=f"durable-mw-{job_id[:16]}",
            daemon=True,
        )
        with self._threads_lock:
            self._threads.append(thread)
        thread.start()

    def _run_safe(self, **kwargs: Any) -> None:
        current = threading.current_thread()
        try:
            self._run(**kwargs)
        except Exception:
            pass
        finally:
            with self._threads_lock:
                if current in self._threads:
                    self._threads.remove(current)

    def _run(
        self,
        *,
        project_id: str,
        job_id: str,
        executor: DurableJobExecutor,
    ) -> None:
        claim = self.store.claim(project_id, job_id)
        if not claim.claimed or claim.claim_token == "" or claim.job is None:
            return
        claim_token = claim.claim_token
        job = claim.job
        claim_key = (project_id, job_id, claim_token)

        # Register active claim for graceful shutdown release.
        with self._active_claims_lock:
            self._active_claims.add(claim_key)

        worker_self = self

        # Cooperative cancel check: returns True when shutdown is requested,
        # status is not running, token differs, or lease expired.
        def cancel_check() -> bool:
            if worker_self._shutdown_requested:
                return True
            return not worker_self.store.check_ownership(
                project_id, job_id, claim_token
            )

        # Heartbeat helper.
        def heartbeat(progress: DurableJobProgressPayload) -> bool:
            return self.store.heartbeat(project_id, job_id, claim_token, progress)

        # Background heartbeat thread (lease renewal).
        hb_stop = threading.Event()
        hb_thread = threading.Thread(
            target=self._heartbeat_loop,
            kwargs={
                "project_id": project_id,
                "job_id": job_id,
                "claim_token": claim_token,
                "stop_event": hb_stop,
            },
            name=f"durable-mw-hb-{job_id[:12]}",
            daemon=True,
        )
        hb_thread.start()

        try:
            result = executor.execute(job, claim_token, cancel_check, heartbeat)
        except Exception as exc:
            result = DurableJobResult(
                error=f"{type(exc).__name__}: {exc}",
                retryable=True,
            )
        finally:
            hb_stop.set()
            hb_thread.join(timeout=2.0)

        # If shutdown was requested, leave the claim registered so shutdown()
        # releases it.  We do NOT attempt complete/fail — shutdown owns the
        # lifecycle.
        if self._shutdown_requested:
            return  # shutdown() will release via release_claim CAS

        # Attempt finalization (complete or fail).  The claim stays in
        # _active_claims during the CAS so shutdown() can still see it if it
        # starts concurrently.  Both release_claim and complete/fail use SQLite
        # BEGIN IMMEDIATE so exactly one CAS wins:
        #   - If finalize wins: row becomes terminal; release_claim returns False.
        #   - If release wins: row becomes queued; complete/fail returns False.
        # In neither order can a live orphan remain.
        try:
            if not self.store.check_ownership(project_id, job_id, claim_token):
                return  # lost ownership (lease expired / takeover)
            if result.error:
                self.store.fail(
                    project_id,
                    job_id,
                    claim_token,
                    error_summary=result.error,
                    retryable=result.retryable,
                )
            else:
                self.store.complete(
                    project_id,
                    job_id,
                    claim_token,
                    output_hash=result.output_hash,
                    artifact_locator=result.artifact_locator,
                    provider=result.provider,
                    model=result.model,
                    final_progress=result.progress,
                )
        finally:
            # Now that finalize CAS has committed (or lost ownership), remove
            # from active claims.  If shutdown() already released this claim,
            # the CAS above returned False and this discard is a no-op cleanup.
            with self._active_claims_lock:
                self._active_claims.discard(claim_key)

    def _heartbeat_loop(
        self,
        *,
        project_id: str,
        job_id: str,
        claim_token: str,
        stop_event: threading.Event,
    ) -> None:
        interval = min(
            5.0,
            max(0.01, self.store.heartbeat_interval_seconds),
            max(0.01, self.store.lease_seconds / 3.0),
        )
        while not stop_event.wait(interval):
            if self._shutdown_requested:
                return
            try:
                if not self.store.heartbeat(project_id, job_id, claim_token):
                    return  # lost lease
            except sqlite3.Error:
                continue

    # -- sweeper (periodic lease recovery) --------------------------------

    def _start_sweeper(self) -> None:
        """Start a daemon thread that periodically requeues expired leases."""
        if self._sweeper_thread is not None:
            return

        def sweep_loop() -> None:
            while not self._sweeper_stop.wait(self.sweeper_interval_seconds):
                if self._shutdown_requested:
                    return
                try:
                    self.store.requeue_expired_leases()
                except sqlite3.Error:
                    continue
                # Wake recoverable jobs that now have registered executors.
                try:
                    with self.store._connect() as connection:
                        rows = connection.execute(
                            """
                            SELECT DISTINCT project_id, job_id, job_type
                            FROM durable_mw_jobs
                            WHERE status IN ('queued', 'retry_wait')
                            """
                        ).fetchall()
                except sqlite3.Error:
                    continue
                for row in rows:
                    if self.get_executor(row["job_type"]) is not None:
                        self.wake(row["project_id"], row["job_id"])

        self._sweeper_thread = threading.Thread(
            target=sweep_loop,
            name="durable-mw-sweeper",
            daemon=True,
        )
        self._sweeper_thread.start()

    def shutdown(self, timeout: float = 30.0) -> None:
        """Signal all workers to stop and join them within one overall deadline.

        *timeout* is the single total deadline for joining all worker threads,
        not per-thread.  The cooperative cancel_check also becomes True on
        shutdown so well-behaved executors exit promptly.

        Every still-owned claim is released exactly once via
        :meth:`DurableJobStore.release_claim` so a new process can reclaim
        immediately without waiting for lease expiry.  This is idempotent:
        repeated ``shutdown()`` calls are safe and claims already released by
        the executor's own return path are skipped.
        """
        if timeout < 0:
            raise ValueError("shutdown timeout must not be negative")
        deadline = time.monotonic() + timeout
        self._shutdown_requested = True
        # Stop the sweeper.
        self._sweeper_stop.set()
        if self._sweeper_thread is not None:
            self._sweeper_thread.join(
                timeout=min(max(0.0, deadline - time.monotonic()), 2.0)
            )
        # Release all still-owned claims.  Each release is a single CAS write;
        # the total cost is O(N_claims) with no per-claim thread wait.
        with self._active_claims_lock:
            claims_to_release = list(self._active_claims)
        for pid, jid, token in claims_to_release:
            try:
                self.store.release_claim(pid, jid, token)
            except (sqlite3.Error, DurableJobNotFound):
                pass  # best-effort; sweeper/lease-expiry will catch stragglers
            with self._active_claims_lock:
                self._active_claims.discard((pid, jid, token))
        # Join all worker threads within one overall deadline.
        with self._threads_lock:
            threads = list(self._threads)
        for t in threads:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                break
            t.join(timeout=remaining)

    # -- recovery entry point -------------------------------------------

    def recover(self) -> int:
        """Recover on startup: requeue expired leases, then wake recoverable jobs.

        The private store-level ``_connect`` scan is intentional and bounded:
        recovery is system-wide (not project-scoped), and the durable job table
        is the authoritative set of all jobs across all projects.  The scan
        reads only job_id/project_id/job_type for non-terminal jobs.
        """
        self.store.requeue_expired_leases()
        recoverable = self.store.recover_on_startup()
        if recoverable > 0:
            with self.store._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT DISTINCT project_id, job_id, job_type
                    FROM durable_mw_jobs
                    WHERE status IN ('queued', 'retry_wait')
                    """
                ).fetchall()
            for row in rows:
                if self.get_executor(row["job_type"]) is not None:
                    self.wake(row["project_id"], row["job_id"])
        return recoverable
