"""PostgreSQL 18 candidate adapter for the Protocol v3 storage PoC — Task 1.8.

This module implements the storage-neutral repository and unit-of-work ports
defined in ``app.protocol_workflow.ports`` plus the database-neutral
:class:`Backend` control protocol consumed by ``contract_suite.py``.  It is a
PoC candidate for the isolated local PostgreSQL 18 cluster — NOT a product
module (Worker 03 / Codex own selection and any product ``postgres.py``).

Architecture for the 8-independent-writer proof: each :class:`PgUnitOfWork`
opens its OWN ``psycopg`` connection to the same database.  There is no
application-side serialization (no shared lock held across a transaction).
Writer contention is resolved at the database layer by PostgreSQL's MVCC /
unique-key enforcement plus bounded retry on CAS conflicts.  CAS correctness
is enforced by the composite PRIMARY KEY ``(aggregate_kind, project_id,
aggregate_id, revision)`` and the optimistic read of ``MAX(revision)`` inside
the transaction; the event chain is enforced by
``PRIMARY KEY (project_id, stream_id, sequence)`` and
``UNIQUE (project_id, stream_id, domain_event_id)``.  Transaction + outbox
atomicity is enforced by committing the CAS save and the outbox enqueue in the
ONE PostgreSQL transaction (design section 18).

Durability / concurrency configuration (official PostgreSQL references):

* MVCC supports concurrent readers and writers
  (https://www.postgresql.org/docs/current/mvcc.html).
* ``pg_dump`` online backup and ``pg_restore`` restore are the native
  mechanisms (https://www.postgresql.org/docs/current/backup-dump.html).
* License: PostgreSQL (licence), psycopg 3.3.4 (LGPL-3.0-only) — recorded in
  the task report.

The cluster is a disposable ``initdb`` under ``mktemp -d`` with data checksums,
local trust on a task-local Unix socket only, no external listener and no
LaunchAgent.  It is stopped via ``pg_ctl -m fast`` in a finally/cleanup path.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg
from psycopg import sql as psql
from psycopg.rows import dict_row

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    DomainEvent,
    ExecutionReservation,
    ExecutionTerminalState,
    ProtocolV3Model,
    ReservationStatus,
    SemanticDocumentRevision,
    StudyDefinitionV3,
    WorkflowRunStatus,
)

from app.protocol_workflow.ports.repositories import (
    AggregateNotFoundError,
    ChapterCoverageRecord,
    DecisionGraphRecord,
    EventSequenceConflictError,
    IdempotencyConflictError,
    InboxResult,
    InboxStatus,
    OutboxMessage,
    OutboxStatus,
    RepositoryStateTransitionError,
    RevisionConflictError,
    StreamHead,
    UnknownOutcomeConflictError,
    WorkflowRunStatusRecord,
)
from app.protocol_workflow.ports.unit_of_work import (
    UnitOfWorkClosedError,
)

from pocs.protocol_v3.storage.contract_suite import (
    Backend,
    CheckpointRecord,
    CheckpointStore,
    QuarantineRecord,
    QuarantineStore,
    RetryableStorageError,
    _crash_child_commit,
)
from pocs.protocol_v3.storage.postgres_migrations import MIGRATION_STEPS, SCHEMA_VERSION

# ---------------------------------------------------------------------------
# Connection / config
# ---------------------------------------------------------------------------


@dataclass
class PostgresConfig:
    """Connection configuration for a :class:`PostgresBackend`."""

    host: str
    port: int
    dbname: str
    user: str
    #: Optional maintenance database used to create/drop task databases.
    maintenance_db: str = "postgres"

    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.dbname} "
            f"user={self.user}"
        )

    def dsn_for(self, dbname: str) -> str:
        return (
            f"host={self.host} port={self.port} dbname={dbname} "
            f"user={self.user}"
        )


#: PostgreSQL binary directory (Homebrew postgresql@18 keg).
PG_BIN_DIR = "/opt/homebrew/opt/postgresql@18/bin"


def _pg_bin(name: str) -> str:
    """Return the absolute path to a PostgreSQL binary."""
    return os.path.join(PG_BIN_DIR, name)


# ---------------------------------------------------------------------------
# Retryable-error translation
# ---------------------------------------------------------------------------


def _translate_retryable(exc: BaseException) -> None:
    """Re-raise *exc* as :class:`RetryableStorageError` if it is a known
    PostgreSQL retryable serialization/lock/deadlock failure; otherwise
    re-raise unchanged.

    Genuine contention (serialization failure, deadlock, lock-not-available)
    is surfaced as retryable so the contract-suite CAS worker retries only on
    real contention.  Programming, assertion and validation errors propagate
    and fail the invariant immediately.
    """
    if isinstance(exc, psycopg.errors.SerializationFailure):
        raise RetryableStorageError(str(exc)) from exc
    if isinstance(exc, psycopg.errors.DeadlockDetected):
        raise RetryableStorageError(str(exc)) from exc
    if isinstance(exc, psycopg.errors.LockNotAvailable):
        raise RetryableStorageError(str(exc)) from exc
    raise exc


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _dt_to_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _dt_from_iso(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _model_to_json(model: ProtocolV3Model) -> str:
    """Canonical JSON for an aggregate/event body."""
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _json_to_model(json_str: str, model_cls: type) -> ProtocolV3Model:
    return model_cls.model_validate_json(json_str)


def _connect(config: PostgresConfig) -> psycopg.Connection:
    """Open an independent connection with manual transaction control."""
    conn = psycopg.connect(config.dsn(), row_factory=dict_row)
    conn.autocommit = True  # explicit BEGIN/COMMIT/ROLLBACK
    return conn


# ---------------------------------------------------------------------------
# Migration guard
# ---------------------------------------------------------------------------


class _Guard:
    """Per-UoW open/closed guard shared by all repository handles."""

    __slots__ = ("closed",)

    def __init__(self) -> None:
        self.closed = False

    def ensure_open(self) -> None:
        if self.closed:
            raise UnitOfWorkClosedError("unit of work is closed")


# ---------------------------------------------------------------------------
# Repository implementations
# ---------------------------------------------------------------------------


class _PgCurrentAggregateRepo:
    def __init__(self, conn: psycopg.Connection, aggregate_kind: str, identity_field: str, model_cls: type, guard: _Guard) -> None:
        self._conn = conn
        self._kind = aggregate_kind
        self._identity_field = identity_field
        self._model_cls = model_cls
        self._guard = guard

    def _row_to_model(self, body_json: str):
        return _json_to_model(body_json, self._model_cls)

    def get_current(self, project_id: str, aggregate_id: str):
        cur = self._conn.execute(
            "SELECT body_json FROM aggregate_revision "
            "WHERE aggregate_kind=%s AND project_id=%s AND aggregate_id=%s "
            "ORDER BY revision DESC LIMIT 1",
            (self._kind, project_id, aggregate_id),
        )
        row = cur.fetchone()
        return self._row_to_model(row["body_json"]) if row else None

    def get_current_required(self, project_id: str, aggregate_id: str):
        record = self.get_current(project_id, aggregate_id)
        if record is None:
            raise AggregateNotFoundError(project_id, aggregate_id=aggregate_id)
        return record

    def get_at_revision(self, project_id: str, aggregate_id: str, revision: int):
        cur = self._conn.execute(
            "SELECT body_json FROM aggregate_revision "
            "WHERE aggregate_kind=%s AND project_id=%s AND aggregate_id=%s AND revision=%s",
            (self._kind, project_id, aggregate_id, revision),
        )
        row = cur.fetchone()
        return self._row_to_model(row["body_json"]) if row else None

    def get_current_revision(self, project_id: str, aggregate_id: str) -> Optional[int]:
        cur = self._conn.execute(
            "SELECT MAX(revision) AS r FROM aggregate_revision "
            "WHERE aggregate_kind=%s AND project_id=%s AND aggregate_id=%s",
            (self._kind, project_id, aggregate_id),
        )
        row = cur.fetchone()
        return row["r"] if row and row["r"] is not None else None


class _PgCasRepo:
    def __init__(self, conn: psycopg.Connection, aggregate_kind: str, identity_field: str, model_cls: type, guard: _Guard) -> None:
        self._conn = conn
        self._kind = aggregate_kind
        self._identity_field = identity_field
        self._model_cls = model_cls
        self._guard = guard

    def save_with_expected_revision(self, project_id: str, record, expected_revision: int):
        self._guard.ensure_open()
        aggregate_id = getattr(record, self._identity_field)
        new_revision = getattr(record, "revision", None)
        cur = self._conn.execute(
            "SELECT MAX(revision) AS r FROM aggregate_revision "
            "WHERE aggregate_kind=%s AND project_id=%s AND aggregate_id=%s",
            (self._kind, project_id, aggregate_id),
        )
        row = cur.fetchone()
        actual = row["r"] if row and row["r"] is not None else None
        if expected_revision == 0:
            if actual is not None:
                raise RevisionConflictError(project_id, aggregate_id, expected_revision, actual)
            if new_revision != 1:
                raise RevisionConflictError(project_id, aggregate_id, expected_revision, actual)
        else:
            if actual is None or actual != expected_revision:
                raise RevisionConflictError(project_id, aggregate_id, expected_revision, actual)
            if new_revision != expected_revision + 1:
                raise RevisionConflictError(project_id, aggregate_id, expected_revision, actual)
        try:
            self._conn.execute(
                "INSERT INTO aggregate_revision "
                "(aggregate_kind, project_id, aggregate_id, revision, body_json, previous_revision_sha256) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    self._kind,
                    project_id,
                    aggregate_id,
                    new_revision,
                    _model_to_json(record),
                    getattr(record, "previous_revision_sha256", None),
                ),
            )
        except psycopg.errors.UniqueViolation as exc:
            # A concurrent writer already persisted this revision — a CAS
            # conflict, not a generic retryable error.  The suite retries on
            # RevisionConflictError.
            raise RevisionConflictError(
                project_id, aggregate_id, expected_revision, actual
            ) from exc
        except psycopg.Error as exc:
            _translate_retryable(exc)
        return record

    def get_current_revision(self, project_id: str, aggregate_id: str) -> Optional[int]:
        cur = self._conn.execute(
            "SELECT MAX(revision) AS r FROM aggregate_revision "
            "WHERE aggregate_kind=%s AND project_id=%s AND aggregate_id=%s",
            (self._kind, project_id, aggregate_id),
        )
        row = cur.fetchone()
        return row["r"] if row and row["r"] is not None else None

    def get_current(self, project_id: str, aggregate_id: str):
        cur = self._conn.execute(
            "SELECT body_json FROM aggregate_revision "
            "WHERE aggregate_kind=%s AND project_id=%s AND aggregate_id=%s "
            "ORDER BY revision DESC LIMIT 1",
            (self._kind, project_id, aggregate_id),
        )
        row = cur.fetchone()
        return _json_to_model(row["body_json"], self._model_cls) if row else None


class _PgEventStreamRepo:
    def __init__(self, conn: psycopg.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def append_events(self, project_id: str, stream_id: str, events: Sequence[DomainEvent]) -> Tuple[DomainEvent, ...]:
        self._guard.ensure_open()
        if not events:
            return ()
        cur = self._conn.execute(
            "SELECT sequence, event_sha256, domain_event_id FROM event_stream "
            "WHERE project_id=%s AND stream_id=%s ORDER BY sequence DESC LIMIT 1",
            (project_id, stream_id),
        )
        head_row = cur.fetchone()
        last_seq = head_row["sequence"] if head_row else 0
        last_sha: Optional[str] = head_row["event_sha256"] if head_row else None
        seen_ids_cur = self._conn.execute(
            "SELECT domain_event_id FROM event_stream WHERE project_id=%s AND stream_id=%s",
            (project_id, stream_id),
        )
        seen_ids = {r["domain_event_id"] for r in seen_ids_cur.fetchall()}
        pending: List[DomainEvent] = []
        for evt in events:
            if evt.stream_id != stream_id:
                raise EventSequenceConflictError(
                    project_id, stream_id,
                    expected_sequence=last_seq + 1 + len(pending),
                    actual_sequence=evt.sequence,
                    detail=f"event stream_id={evt.stream_id!r} does not match append target {stream_id!r}",
                )
            expected_prev = None if (last_seq == 0 and not pending) else (pending[-1].event_sha256 if pending else last_sha)
            if evt.domain_event_id in seen_ids:
                raise EventSequenceConflictError(
                    project_id, stream_id, expected_sequence=None, actual_sequence=None,
                    detail=f"duplicate domain_event_id={evt.domain_event_id}",
                )
            if evt.previous_event_sha256 != expected_prev:
                raise EventSequenceConflictError(
                    project_id, stream_id, expected_sequence=last_seq + 1, actual_sequence=evt.sequence,
                    detail="previous_event_sha256 chain mismatch",
                )
            if evt.sequence != last_seq + 1 + len(pending):
                raise EventSequenceConflictError(
                    project_id, stream_id,
                    expected_sequence=last_seq + 1 + len(pending),
                    actual_sequence=evt.sequence,
                    detail="sequence gap",
                )
            seen_ids.add(evt.domain_event_id)
            try:
                self._conn.execute(
                    "INSERT INTO event_stream "
                    "(project_id, stream_id, sequence, domain_event_id, body_json, previous_event_sha256, event_sha256) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (project_id, stream_id, evt.sequence, evt.domain_event_id, _model_to_json(evt),
                     evt.previous_event_sha256, evt.event_sha256),
                )
            except psycopg.errors.UniqueViolation as exc:
                raise EventSequenceConflictError(
                    project_id, stream_id, expected_sequence=None, actual_sequence=None,
                    detail=f"unique constraint violated appending event {evt.domain_event_id}",
                ) from exc
            except psycopg.Error as exc:
                _translate_retryable(exc)
            pending.append(evt)
        return tuple(pending)

    def read_events(self, project_id: str, stream_id: str, *, from_sequence: int = 1) -> Tuple[DomainEvent, ...]:
        cur = self._conn.execute(
            "SELECT body_json FROM event_stream "
            "WHERE project_id=%s AND stream_id=%s AND sequence >= %s ORDER BY sequence",
            (project_id, stream_id, from_sequence),
        )
        return tuple(_json_to_model(r["body_json"], DomainEvent) for r in cur.fetchall())  # type: ignore[arg-type]

    def get_stream_head(self, project_id: str, stream_id: str) -> Optional[StreamHead]:
        cur = self._conn.execute(
            "SELECT sequence, event_sha256, (SELECT COUNT(*) FROM event_stream "
            "WHERE project_id=%s AND stream_id=%s) AS cnt FROM event_stream "
            "WHERE project_id=%s AND stream_id=%s ORDER BY sequence DESC LIMIT 1",
            (project_id, stream_id, project_id, stream_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return StreamHead(
            stream_id=stream_id, last_sequence=row["sequence"],
            last_event_sha256=row["event_sha256"], event_count=row["cnt"],
        )


class _PgOutboxRepo:
    def __init__(self, conn: psycopg.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def _row_to_msg(self, row: Dict[str, Any]) -> OutboxMessage:
        return OutboxMessage(
            outbox_message_id=row["outbox_message_id"],
            project_id=row["project_id"],
            workflow_run_id=row["workflow_run_id"],
            side_effect_kind=row["side_effect_kind"],
            logical_key=row["logical_key"],
            payload_sha256=row["payload_sha256"],
            status=OutboxStatus(row["status"]),
            created_at=_dt_from_iso(row["created_at"]),  # type: ignore[arg-type]
            dispatched_at=_dt_from_iso(row["dispatched_at"]),
            completed_at=_dt_from_iso(row["completed_at"]),
            attempt=row["attempt"],
            error_detail=row["error_detail"],
        )

    def enqueue(self, project_id: str, workflow_run_id: str, side_effect_kind, logical_key: str,
                payload_sha256: str, created_at: datetime) -> OutboxMessage:
        self._guard.ensure_open()
        cur = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=%s AND logical_key=%s",
            (project_id, logical_key),
        )
        row = cur.fetchone()
        if row is not None:
            if row["payload_sha256"] == payload_sha256:
                return self._row_to_msg(row)
            raise IdempotencyConflictError(project_id, logical_key, row["payload_sha256"], payload_sha256)
        nxt = int(self._conn.execute(
            "SELECT COALESCE(MAX(CAST(SPLIT_PART(outbox_message_id, '-', 2) AS INTEGER)), 0) + 1 "
            "FROM outbox_message"
        ).fetchone()["?column?"])
        message_id = f"ob-{nxt}-{logical_key}"
        self._conn.execute(
            "INSERT INTO outbox_message "
            "(outbox_message_id, project_id, workflow_run_id, side_effect_kind, logical_key, payload_sha256, status, created_at, attempt) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)",
            (message_id, project_id, workflow_run_id, str(side_effect_kind), logical_key,
             payload_sha256, OutboxStatus.PENDING.value, _dt_to_iso(created_at)),
        )
        got = self._conn.execute(
            "SELECT * FROM outbox_message WHERE outbox_message_id=%s", (message_id,)
        )
        return self._row_to_msg(got.fetchone())

    def claim_pending(self, project_id: str, *, limit: int, claimed_at: datetime) -> Tuple[OutboxMessage, ...]:
        self._guard.ensure_open()
        cur = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=%s AND status=%s "
            "ORDER BY created_at, outbox_message_id LIMIT %s",
            (project_id, OutboxStatus.PENDING.value, limit),
        )
        rows = cur.fetchall()
        claimed = []
        for row in rows:
            self._conn.execute(
                "UPDATE outbox_message SET status=%s, dispatched_at=%s, attempt=attempt+1 "
                "WHERE outbox_message_id=%s",
                (OutboxStatus.DISPATCHED.value, _dt_to_iso(claimed_at), row["outbox_message_id"]),
            )
            got = self._conn.execute(
                "SELECT * FROM outbox_message WHERE outbox_message_id=%s", (row["outbox_message_id"],)
            )
            claimed.append(self._row_to_msg(got.fetchone()))
        return tuple(claimed)

    def mark_completed(self, project_id: str, outbox_message_id: str, completed_at: datetime) -> OutboxMessage:
        self._guard.ensure_open()
        cur = self._conn.execute(
            "SELECT * FROM outbox_message WHERE outbox_message_id=%s AND project_id=%s",
            (outbox_message_id, project_id),
        )
        row = cur.fetchone()
        if row is None:
            raise AggregateNotFoundError(project_id, aggregate_id=outbox_message_id)
        if row["status"] != OutboxStatus.DISPATCHED.value:
            raise RepositoryStateTransitionError(project_id, outbox_message_id, from_status=row["status"], to_status=OutboxStatus.COMPLETED.value)
        self._conn.execute(
            "UPDATE outbox_message SET status=%s, completed_at=%s WHERE outbox_message_id=%s",
            (OutboxStatus.COMPLETED.value, _dt_to_iso(completed_at), outbox_message_id),
        )
        got = self._conn.execute("SELECT * FROM outbox_message WHERE outbox_message_id=%s", (outbox_message_id,))
        return self._row_to_msg(got.fetchone())

    def mark_failed(self, project_id: str, outbox_message_id: str, error_detail: str, failed_at: datetime) -> OutboxMessage:
        self._guard.ensure_open()
        cur = self._conn.execute(
            "SELECT * FROM outbox_message WHERE outbox_message_id=%s AND project_id=%s",
            (outbox_message_id, project_id),
        )
        row = cur.fetchone()
        if row is None:
            raise AggregateNotFoundError(project_id, aggregate_id=outbox_message_id)
        if row["status"] != OutboxStatus.DISPATCHED.value:
            raise RepositoryStateTransitionError(project_id, outbox_message_id, from_status=row["status"], to_status=OutboxStatus.FAILED.value)
        self._conn.execute(
            "UPDATE outbox_message SET status=%s, completed_at=%s, error_detail=%s WHERE outbox_message_id=%s",
            (OutboxStatus.FAILED.value, _dt_to_iso(failed_at), error_detail, outbox_message_id),
        )
        got = self._conn.execute("SELECT * FROM outbox_message WHERE outbox_message_id=%s", (outbox_message_id,))
        return self._row_to_msg(got.fetchone())

    def get(self, project_id: str, outbox_message_id: str) -> Optional[OutboxMessage]:
        cur = self._conn.execute(
            "SELECT * FROM outbox_message WHERE outbox_message_id=%s AND project_id=%s",
            (outbox_message_id, project_id),
        )
        row = cur.fetchone()
        return self._row_to_msg(row) if row else None

    def find_by_logical_key(self, project_id: str, logical_key: str) -> Optional[OutboxMessage]:
        cur = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=%s AND logical_key=%s",
            (project_id, logical_key),
        )
        row = cur.fetchone()
        return self._row_to_msg(row) if row else None

    def list_dispatched(self, project_id: str, *, limit: int) -> Tuple[OutboxMessage, ...]:
        cur = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=%s AND status=%s "
            "ORDER BY created_at, outbox_message_id LIMIT %s",
            (project_id, OutboxStatus.DISPATCHED.value, limit),
        )
        return tuple(self._row_to_msg(r) for r in cur.fetchall())


class _PgInboxRepo:
    def __init__(self, conn: psycopg.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def _row_to_result(self, row: Dict[str, Any]) -> InboxResult:
        return InboxResult(
            inbox_result_id=row["inbox_result_id"], project_id=row["project_id"],
            logical_key=row["logical_key"], result_sha256=row["result_sha256"],
            status=InboxStatus(row["status"]), received_at=_dt_from_iso(row["received_at"]),  # type: ignore[arg-type]
            consumed_at=_dt_from_iso(row["consumed_at"]),
        )

    def record_result(self, project_id: str, logical_key: str, result_sha256: str, received_at: datetime) -> InboxResult:
        self._guard.ensure_open()
        cur = self._conn.execute(
            "SELECT * FROM inbox_result WHERE project_id=%s AND logical_key=%s",
            (project_id, logical_key),
        )
        row = cur.fetchone()
        if row is not None:
            if row["result_sha256"] == result_sha256:
                return self._row_to_result(row)
            raise IdempotencyConflictError(project_id, logical_key, row["result_sha256"], result_sha256)
        nxt = int(self._conn.execute(
            "SELECT COALESCE(MAX(CAST(SPLIT_PART(inbox_result_id, '-', 2) AS INTEGER)), 0) + 1 "
            "FROM inbox_result"
        ).fetchone()["?column?"])
        result_id = f"ib-{nxt}-{logical_key}"
        self._conn.execute(
            "INSERT INTO inbox_result (inbox_result_id, project_id, logical_key, result_sha256, status, received_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (result_id, project_id, logical_key, result_sha256, InboxStatus.RECEIVED.value, _dt_to_iso(received_at)),
        )
        got = self._conn.execute("SELECT * FROM inbox_result WHERE inbox_result_id=%s", (result_id,))
        return self._row_to_result(got.fetchone())

    def get_result(self, project_id: str, logical_key: str) -> Optional[InboxResult]:
        cur = self._conn.execute(
            "SELECT * FROM inbox_result WHERE project_id=%s AND logical_key=%s",
            (project_id, logical_key),
        )
        row = cur.fetchone()
        return self._row_to_result(row) if row else None

    def was_processed(self, project_id: str, logical_key: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM inbox_result WHERE project_id=%s AND logical_key=%s",
            (project_id, logical_key),
        )
        return cur.fetchone() is not None

    def mark_consumed(self, project_id: str, logical_key: str, consumed_at: datetime) -> InboxResult:
        self._guard.ensure_open()
        cur = self._conn.execute(
            "SELECT * FROM inbox_result WHERE project_id=%s AND logical_key=%s",
            (project_id, logical_key),
        )
        row = cur.fetchone()
        if row is None:
            raise AggregateNotFoundError(project_id, aggregate_id=logical_key)
        if row["status"] != InboxStatus.RECEIVED.value:
            raise RepositoryStateTransitionError(project_id, logical_key, from_status=row["status"], to_status=InboxStatus.CONSUMED.value)
        self._conn.execute(
            "UPDATE inbox_result SET status=%s, consumed_at=%s WHERE inbox_result_id=%s",
            (InboxStatus.CONSUMED.value, _dt_to_iso(consumed_at), row["inbox_result_id"]),
        )
        got = self._conn.execute("SELECT * FROM inbox_result WHERE inbox_result_id=%s", (row["inbox_result_id"],))
        return self._row_to_result(got.fetchone())


class _PgReservationRepo:
    def __init__(self, conn: psycopg.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def _row_to_reservation(self, row: Dict[str, Any]) -> ExecutionReservation:
        return ExecutionReservation.model_validate({
            "execution_reservation_id": row["execution_reservation_id"],
            "node_execution_contract_id": row["node_execution_contract_id"],
            "logical_call_id": row["logical_call_id"],
            "idempotency_key": row["idempotency_key"],
            "input_sha256": row["input_sha256"],
            "attempt": row["attempt"],
            "transport_attempts": row["transport_attempts"],
            "provider_session_id": row["provider_session_id"],
            "status": ReservationStatus(row["status"]),
            "terminal_state": ExecutionTerminalState(row["terminal_state"]) if row["terminal_state"] else None,
            "output_sha256": row["output_sha256"],
            "error_code": row["error_code"],
            "reserved_at": _dt_from_iso(row["reserved_at"]),  # type: ignore[arg-type]
            "updated_at": _dt_from_iso(row["updated_at"]),  # type: ignore[arg-type]
        })

    def reserve(self, project_id: str, reservation: ExecutionReservation) -> ExecutionReservation:
        self._guard.ensure_open()
        cur = self._conn.execute(
            "SELECT * FROM execution_reservation WHERE project_id=%s AND logical_call_id=%s AND idempotency_key=%s",
            (project_id, reservation.logical_call_id, reservation.idempotency_key),
        )
        row = cur.fetchone()
        if row is not None:
            existing = self._row_to_reservation(row)
            if existing.input_sha256 != reservation.input_sha256:
                raise IdempotencyConflictError(project_id, reservation.logical_call_id, existing.input_sha256, reservation.input_sha256)
            if existing.status is ReservationStatus.UNKNOWN_OUTCOME:
                raise UnknownOutcomeConflictError(project_id, aggregate_id=reservation.logical_call_id,
                                                  detail="unknown-outcome reservation must be resolved before re-dispatch")
            return existing
        try:
            self._conn.execute(
                "INSERT INTO execution_reservation "
                "(execution_reservation_id, project_id, node_execution_contract_id, logical_call_id, idempotency_key, "
                " input_sha256, attempt, transport_attempts, provider_session_id, status, terminal_state, "
                " output_sha256, error_code, reserved_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (reservation.execution_reservation_id, project_id, reservation.node_execution_contract_id,
                 reservation.logical_call_id, reservation.idempotency_key, reservation.input_sha256,
                 reservation.attempt, reservation.transport_attempts, reservation.provider_session_id,
                 reservation.status.value,
                 reservation.terminal_state.value if reservation.terminal_state else None,
                 reservation.output_sha256, reservation.error_code,
                 _dt_to_iso(reservation.reserved_at), _dt_to_iso(reservation.updated_at)),
            )
        except psycopg.errors.UniqueViolation as exc:
            raise IdempotencyConflictError(
                project_id, reservation.logical_call_id, reservation.input_sha256, reservation.input_sha256
            ) from exc
        return reservation

    def get(self, project_id: str, execution_reservation_id: str) -> Optional[ExecutionReservation]:
        cur = self._conn.execute(
            "SELECT * FROM execution_reservation WHERE project_id=%s AND execution_reservation_id=%s",
            (project_id, execution_reservation_id),
        )
        row = cur.fetchone()
        return self._row_to_reservation(row) if row else None

    def find_by_logical_call(self, project_id: str, logical_call_id: str, idempotency_key: str) -> Optional[ExecutionReservation]:
        cur = self._conn.execute(
            "SELECT * FROM execution_reservation WHERE project_id=%s AND logical_call_id=%s AND idempotency_key=%s",
            (project_id, logical_call_id, idempotency_key),
        )
        row = cur.fetchone()
        return self._row_to_reservation(row) if row else None

    def transition(self, project_id: str, execution_reservation_id: str, *, to_status: ReservationStatus,
                   terminal_state: Optional[ExecutionTerminalState] = None, output_sha256: Optional[str] = None,
                   error_code: Optional[str] = None, provider_session_id: Optional[str] = None,
                   transport_attempts: Optional[int] = None, updated_at: datetime) -> ExecutionReservation:
        self._guard.ensure_open()
        cur = self._conn.execute(
            "SELECT * FROM execution_reservation WHERE project_id=%s AND execution_reservation_id=%s",
            (project_id, execution_reservation_id),
        )
        row = cur.fetchone()
        if row is None:
            raise AggregateNotFoundError(project_id, aggregate_id=execution_reservation_id)
        existing = self._row_to_reservation(row)
        allowed = {
            ReservationStatus.RESERVED: {ReservationStatus.RUNNING, ReservationStatus.FAILED},
            ReservationStatus.RUNNING: {ReservationStatus.COMPLETED, ReservationStatus.FAILED, ReservationStatus.UNKNOWN_OUTCOME},
            ReservationStatus.UNKNOWN_OUTCOME: {ReservationStatus.COMPLETED},
            ReservationStatus.COMPLETED: set(),
            ReservationStatus.FAILED: set(),
        }
        if to_status not in allowed[existing.status]:
            raise RepositoryStateTransitionError(project_id, execution_reservation_id, from_status=existing.status.value, to_status=to_status.value)
        next_transport = existing.transport_attempts if transport_attempts is None else transport_attempts
        if next_transport < existing.transport_attempts:
            raise RepositoryStateTransitionError(project_id, execution_reservation_id, from_status=existing.status.value, to_status=to_status.value)
        if existing.status is ReservationStatus.RESERVED:
            expected_attempts = existing.transport_attempts + 1 if to_status is ReservationStatus.RUNNING else existing.transport_attempts
            if next_transport != expected_attempts:
                raise RepositoryStateTransitionError(project_id, execution_reservation_id, from_status=existing.status.value, to_status=to_status.value)
        elif next_transport != existing.transport_attempts:
            raise RepositoryStateTransitionError(project_id, execution_reservation_id, from_status=existing.status.value, to_status=to_status.value)
        next_session = provider_session_id if provider_session_id is not None else existing.provider_session_id
        if existing.status is ReservationStatus.UNKNOWN_OUTCOME and provider_session_id is not None and provider_session_id != existing.provider_session_id:
            raise RepositoryStateTransitionError(project_id, execution_reservation_id, from_status=existing.status.value, to_status=to_status.value)
        updated = ExecutionReservation.model_validate({
            **existing.model_dump(),
            "status": to_status, "terminal_state": terminal_state, "output_sha256": output_sha256,
            "error_code": error_code, "provider_session_id": next_session,
            "transport_attempts": next_transport, "updated_at": updated_at,
        })
        self._conn.execute(
            "UPDATE execution_reservation SET status=%s, terminal_state=%s, output_sha256=%s, error_code=%s, "
            "provider_session_id=%s, transport_attempts=%s, updated_at=%s WHERE execution_reservation_id=%s",
            (updated.status.value, updated.terminal_state.value if updated.terminal_state else None,
             updated.output_sha256, updated.error_code, updated.provider_session_id,
             updated.transport_attempts, _dt_to_iso(updated.updated_at), execution_reservation_id),
        )
        return updated

    def list_attempts(self, project_id: str, logical_call_id: str) -> Tuple[ExecutionReservation, ...]:
        cur = self._conn.execute(
            "SELECT * FROM execution_reservation WHERE project_id=%s AND logical_call_id=%s ORDER BY attempt, execution_reservation_id",
            (project_id, logical_call_id),
        )
        return tuple(self._row_to_reservation(r) for r in cur.fetchall())

    def find_unknown_outcome(self, project_id: str) -> Tuple[ExecutionReservation, ...]:
        cur = self._conn.execute(
            "SELECT * FROM execution_reservation WHERE project_id=%s AND status=%s ORDER BY logical_call_id, attempt",
            (project_id, ReservationStatus.UNKNOWN_OUTCOME.value),
        )
        return tuple(self._row_to_reservation(r) for r in cur.fetchall())

    def find_unresolved(self, project_id: str) -> Tuple[ExecutionReservation, ...]:
        cur = self._conn.execute(
            "SELECT * FROM execution_reservation WHERE project_id=%s AND status IN (%s, %s, %s) "
            "ORDER BY logical_call_id, attempt, execution_reservation_id",
            (project_id, ReservationStatus.RESERVED.value, ReservationStatus.RUNNING.value, ReservationStatus.UNKNOWN_OUTCOME.value),
        )
        return tuple(self._row_to_reservation(r) for r in cur.fetchall())


class _PgReadModelRepo:
    def __init__(self, conn: psycopg.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def get_chapter_coverage(self, project_id: str, semantic_document_revision_id: str) -> Tuple[ChapterCoverageRecord, ...]:
        cur = self._conn.execute(
            "SELECT * FROM read_chapter_coverage WHERE project_id=%s AND semantic_document_revision_id=%s ORDER BY semantic_node_id",
            (project_id, semantic_document_revision_id),
        )
        return tuple(
            ChapterCoverageRecord(
                project_id=r["project_id"], semantic_node_id=r["semantic_node_id"],
                chapter_contract_sha256=r["chapter_contract_sha256"],
                substantive_content_contract_sha256=r["substantive_content_contract_sha256"],
                semantic_block_sha256=r["semantic_block_sha256"], is_locked=bool(r["is_locked"]),
                has_substantive_content=bool(r["has_substantive_content"]), evidence_admitted=bool(r["evidence_admitted"]),
            )
            for r in cur.fetchall()
        )

    def get_decision_graph(self, project_id: str, study_definition_id: str) -> Tuple[DecisionGraphRecord, ...]:
        cur = self._conn.execute(
            "SELECT * FROM read_decision_graph WHERE project_id=%s AND study_definition_id=%s ORDER BY decision_key",
            (project_id, study_definition_id),
        )
        return tuple(
            DecisionGraphRecord(
                project_id=r["project_id"], decision_key=r["decision_key"], decision_record_id=r["decision_record_id"],
                state_revision=r["state_revision"], selected_option_id=r["selected_option_id"],
                canonical_state=CanonicalState(r["canonical_state"]) if r["canonical_state"] else None,
            )
            for r in cur.fetchall()
        )

    def get_workflow_run_status(self, project_id: str, workflow_run_id: str) -> Optional[WorkflowRunStatusRecord]:
        cur = self._conn.execute(
            "SELECT * FROM read_workflow_run_status WHERE project_id=%s AND workflow_run_id=%s",
            (project_id, workflow_run_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return WorkflowRunStatusRecord(
            project_id=row["project_id"], workflow_run_id=row["workflow_run_id"],
            status=WorkflowRunStatus(row["status"]), display_progress=row["display_progress"],
            journey_counter=row["journey_counter"],
        )

    def upsert_chapter_coverage(self, project_id: str, revision_id: str, record: ChapterCoverageRecord) -> None:
        self._guard.ensure_open()
        self._conn.execute(
            "INSERT INTO read_chapter_coverage "
            "(project_id, semantic_document_revision_id, semantic_node_id, chapter_contract_sha256, "
            " substantive_content_contract_sha256, semantic_block_sha256, is_locked, has_substantive_content, evidence_admitted) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (project_id, semantic_document_revision_id, semantic_node_id) DO UPDATE SET "
            "chapter_contract_sha256=EXCLUDED.chapter_contract_sha256, "
            "substantive_content_contract_sha256=EXCLUDED.substantive_content_contract_sha256, "
            "semantic_block_sha256=EXCLUDED.semantic_block_sha256, "
            "is_locked=EXCLUDED.is_locked, has_substantive_content=EXCLUDED.has_substantive_content, "
            "evidence_admitted=EXCLUDED.evidence_admitted",
            (project_id, revision_id, record.semantic_node_id, record.chapter_contract_sha256,
             record.substantive_content_contract_sha256, record.semantic_block_sha256,
             int(record.is_locked), int(record.has_substantive_content), int(record.evidence_admitted)),
        )

    def upsert_decision_graph(self, project_id: str, study_definition_id: str, record: DecisionGraphRecord) -> None:
        self._guard.ensure_open()
        self._conn.execute(
            "INSERT INTO read_decision_graph "
            "(project_id, study_definition_id, decision_key, decision_record_id, state_revision, selected_option_id, canonical_state) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (project_id, study_definition_id, decision_key) DO UPDATE SET "
            "decision_record_id=EXCLUDED.decision_record_id, state_revision=EXCLUDED.state_revision, "
            "selected_option_id=EXCLUDED.selected_option_id, canonical_state=EXCLUDED.canonical_state",
            (project_id, study_definition_id, record.decision_key, record.decision_record_id,
             record.state_revision, record.selected_option_id,
             record.canonical_state.value if record.canonical_state else None),
        )

    def upsert_workflow_run_status(self, record: WorkflowRunStatusRecord) -> None:
        self._guard.ensure_open()
        self._conn.execute(
            "INSERT INTO read_workflow_run_status "
            "(project_id, workflow_run_id, status, display_progress, journey_counter) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (project_id, workflow_run_id) DO UPDATE SET "
            "status=EXCLUDED.status, display_progress=EXCLUDED.display_progress, journey_counter=EXCLUDED.journey_counter",
            (record.project_id, record.workflow_run_id, record.status.value, record.display_progress, record.journey_counter),
        )


# ---------------------------------------------------------------------------
# Unit of work — one independent connection per UoW
# ---------------------------------------------------------------------------


class PgUnitOfWork:
    """PostgreSQL implementation of :class:`UnitOfWork`.

    Each instance opens its own connection to the database.  ``__enter__``
    issues ``BEGIN``; ``commit``/``rollback`` issue ``COMMIT``/``ROLLBACK`` and
    close the connection.  There is no application-side lock; independent
    writers race through PostgreSQL's MVCC with unique-key CAS enforcement.
    Nested ``with`` blocks use SAVEPOINTs so the outer transaction stays
    intact.
    """

    def __init__(self, config: PostgresConfig) -> None:
        self._config = config
        self._conn = _connect(config)
        self._guard = _Guard()
        self._depth = 0
        self._closed = False
        self._conn_identity = str(self._conn.info.backend_pid)
        self._sd_repo = _PgCurrentAggregateRepo(self._conn, "study_definition", "study_definition_id", StudyDefinitionV3, self._guard)
        self._sd_cas = _PgCasRepo(self._conn, "study_definition", "study_definition_id", StudyDefinitionV3, self._guard)
        self._sdr_repo = _PgCurrentAggregateRepo(self._conn, "semantic_document", "semantic_document_revision_id", SemanticDocumentRevision, self._guard)
        self._sdr_cas = _PgCasRepo(self._conn, "semantic_document", "semantic_document_revision_id", SemanticDocumentRevision, self._guard)
        self._events = _PgEventStreamRepo(self._conn, self._guard)
        self._outbox = _PgOutboxRepo(self._conn, self._guard)
        self._inbox = _PgInboxRepo(self._conn, self._guard)
        self._reservations = _PgReservationRepo(self._conn, self._guard)
        self._read_models = _PgReadModelRepo(self._conn, self._guard)

    @property
    def connection_identity(self) -> str:
        return self._conn_identity

    @property
    def study_definition_repository(self):
        return self._sd_repo

    @property
    def study_definition_cas_repository(self):
        return self._sd_cas

    @property
    def semantic_document_repository(self):
        return self._sdr_repo

    @property
    def semantic_document_cas_repository(self):
        return self._sdr_cas

    @property
    def event_stream_repository(self):
        return self._events

    @property
    def outbox_repository(self):
        return self._outbox

    @property
    def inbox_repository(self):
        return self._inbox

    @property
    def reservation_repository(self):
        return self._reservations

    @property
    def read_model_repository(self):
        return self._read_models

    @property
    def artifact_store(self):
        return None

    @property
    def is_active(self) -> bool:
        return not self._closed and self._depth > 0

    def _close_conn(self) -> None:
        """Close the underlying connection if present, then drop the reference."""
        conn = self._conn
        self._conn = None  # type: ignore[assignment]
        if conn is not None and not conn.closed:
            conn.close()

    def commit(self) -> None:
        if self._closed or self._conn is None:
            return
        if self._depth > 1:
            try:
                self._conn.execute(f"RELEASE SAVEPOINT sp_{self._depth}")
            except psycopg.Error:
                pass
            self._depth -= 1
            return
        try:
            try:
                self._conn.execute("COMMIT")
            except psycopg.Error as exc:
                _translate_retryable(exc)
        finally:
            self._closed = True
            self._depth = 0
            self._guard.closed = True
            self._close_conn()

    def rollback(self) -> None:
        if self._closed or self._conn is None:
            return
        if self._depth > 1:
            try:
                self._conn.execute(f"ROLLBACK TO SAVEPOINT sp_{self._depth}")
                self._conn.execute(f"RELEASE SAVEPOINT sp_{self._depth}")
            except psycopg.Error:
                pass
            self._depth -= 1
            return
        try:
            self._conn.execute("ROLLBACK")
        except psycopg.Error:
            pass
        finally:
            self._closed = True
            self._depth = 0
            self._guard.closed = True
            self._close_conn()

    def __enter__(self) -> "PgUnitOfWork":
        if self._closed or self._conn is None:
            raise RuntimeError("unit of work is closed")
        if self._depth == 0:
            try:
                self._conn.execute("BEGIN")
            except Exception as exc:
                self._closed = True
                self._guard.closed = True
                self._close_conn()
                _translate_retryable(exc)
        else:
            try:
                self._conn.execute(f"SAVEPOINT sp_{self._depth + 1}")
            except psycopg.Error:
                pass
        self._depth += 1
        return self

    def close(self) -> None:
        """Explicitly close the underlying connection (idempotent)."""
        if not self._closed and self._conn is not None:
            try:
                self._conn.execute("ROLLBACK")
            except psycopg.Error:
                pass
        self._closed = True
        self._depth = 0
        self._guard.closed = True
        self._close_conn()

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._depth <= 0:
            return
        if exc is not None:
            self.rollback()
            return
        if self._depth == 1:
            self.commit()
        else:
            self._depth -= 1


# ---------------------------------------------------------------------------
# Checkpoint + quarantine stores
# ---------------------------------------------------------------------------


class _PgCheckpointStore(CheckpointStore):
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def _record_from_row(self, row: Dict[str, Any]) -> CheckpointRecord:
        return _PgCheckpointRecord(
            project_id=row["project_id"], run_id=row["run_id"], stream_id=row["stream_id"],
            checkpoint_seq=row["checkpoint_seq"], checkpoint_sha=row["checkpoint_sha"],
        )

    def create(self, project_id: str, run_id: str, stream_id: str, checkpoint_seq: int,
               checkpoint_sha: str, *, state: int) -> CheckpointRecord:
        self._conn.execute(
            "INSERT INTO checkpoint_record "
            "(project_id, run_id, stream_id, checkpoint_seq, checkpoint_sha, state) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (project_id, run_id) DO UPDATE SET "
            "stream_id=EXCLUDED.stream_id, checkpoint_seq=EXCLUDED.checkpoint_seq, "
            "checkpoint_sha=EXCLUDED.checkpoint_sha, state=EXCLUDED.state",
            (project_id, run_id, stream_id, checkpoint_seq, checkpoint_sha, state),
        )
        cur = self._conn.execute(
            "SELECT * FROM checkpoint_record WHERE project_id=%s AND run_id=%s",
            (project_id, run_id),
        )
        return self._record_from_row(cur.fetchone())

    def update(self, project_id: str, run_id: str, checkpoint_seq: int, checkpoint_sha: str) -> CheckpointRecord:
        self._conn.execute(
            "UPDATE checkpoint_record SET checkpoint_seq=%s, checkpoint_sha=%s WHERE project_id=%s AND run_id=%s",
            (checkpoint_seq, checkpoint_sha, project_id, run_id),
        )
        cur = self._conn.execute(
            "SELECT * FROM checkpoint_record WHERE project_id=%s AND run_id=%s",
            (project_id, run_id),
        )
        return self._record_from_row(cur.fetchone())

    def delete(self, project_id: str, run_id: str) -> None:
        self._conn.execute(
            "DELETE FROM checkpoint_record WHERE project_id=%s AND run_id=%s",
            (project_id, run_id),
        )

    def get(self, project_id: str, run_id: str) -> Optional[CheckpointRecord]:
        cur = self._conn.execute(
            "SELECT * FROM checkpoint_record WHERE project_id=%s AND run_id=%s",
            (project_id, run_id),
        )
        row = cur.fetchone()
        return self._record_from_row(row) if row else None

    def list_runs(self, project_id: str) -> Tuple[str, ...]:
        cur = self._conn.execute(
            "SELECT run_id FROM checkpoint_record WHERE project_id=%s ORDER BY run_id",
            (project_id,),
        )
        return tuple(r["run_id"] for r in cur.fetchall())

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS c FROM checkpoint_record")
        return int(cur.fetchone()["c"])

    def close(self) -> None:
        if not self._conn.closed:
            self._conn.close()


@dataclass
class _PgCheckpointRecord:
    project_id: str
    run_id: str
    stream_id: str
    checkpoint_seq: int
    checkpoint_sha: str


class _PgQuarantineStore(QuarantineStore):
    """PostgreSQL implementation of the neutral :class:`QuarantineStore`."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def quarantine(self, family: str, source_key: str, reason_code: str, body: str) -> QuarantineRecord:
        body_hash = sha256(body.encode("utf-8")).hexdigest()
        self._conn.execute(
            "INSERT INTO quarantine_record (family, source_key, reason_code, body_hash, body) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (family, source_key) DO UPDATE SET "
            "reason_code=EXCLUDED.reason_code, body_hash=EXCLUDED.body_hash, body=EXCLUDED.body",
            (family, source_key, reason_code, body_hash, body),
        )
        return _PgQuarantineRecord(
            family=family, source_key=source_key, reason_code=reason_code, body_hash=body_hash, body=body
        )

    def list_quarantined(self, family: str) -> Tuple[QuarantineRecord, ...]:
        cur = self._conn.execute(
            "SELECT family, source_key, reason_code, body_hash, body FROM quarantine_record "
            "WHERE family=%s ORDER BY source_key",
            (family,),
        )
        return tuple(
            _PgQuarantineRecord(
                family=r["family"], source_key=r["source_key"], reason_code=r["reason_code"],
                body_hash=r["body_hash"], body=r["body"],
            )
            for r in cur.fetchall()
        )

    def close(self) -> None:
        if not self._conn.closed:
            self._conn.close()


@dataclass
class _PgQuarantineRecord:
    family: str
    source_key: str
    reason_code: str
    body_hash: str
    body: str


# ---------------------------------------------------------------------------
# Migration application
# ---------------------------------------------------------------------------


def apply_migrations(config: PostgresConfig) -> Dict[str, Any]:
    """Apply the idempotent migration steps to *config.dbname* and record the
    ledger.  Returns evidence of what was applied.

    The ledger table is created FIRST (its own transaction), then each schema
    step runs in its own transaction and records its ledger row.  This avoids
    referencing ``schema_version`` before it exists.
    """
    conn = psycopg.connect(config.dsn(), row_factory=dict_row)
    conn.autocommit = True
    conn.autocommit = False
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER NOT NULL PRIMARY KEY, "
        "applied_at TEXT NOT NULL, "
        "note TEXT)"
    )
    conn.commit()
    conn.autocommit = True
    applied: List[str] = []
    try:
        for name, ddl in MIGRATION_STEPS:
            conn.autocommit = False
            conn.execute(ddl)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at, note) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (version) DO NOTHING",
                (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat(), name),
            )
            conn.commit()
            conn.autocommit = True
            applied.append(name)
    finally:
        conn.close()
    return {"migration_steps": applied, "schema_version": SCHEMA_VERSION}


# ---------------------------------------------------------------------------
# Backend control protocol implementation
# ---------------------------------------------------------------------------


class PostgresBackend:
    """Database-neutral :class:`Backend` adapter over a PostgreSQL database."""

    def __init__(self, config: PostgresConfig) -> None:
        self.config = config
        # Apply idempotent migrations on a bootstrap connection.
        apply_migrations(config)

    @property
    def name(self) -> str:
        return "postgresql_18_4"

    @property
    def postgres_version(self) -> str:
        conn = _connect(self.config)
        try:
            cur = conn.execute("SHOW server_version")
            return cur.fetchone()["server_version"]
        finally:
            conn.close()

    def new_uow(self) -> PgUnitOfWork:
        return PgUnitOfWork(self.config)

    def backup_to(self, dest_path: Path) -> Path:
        """Online backup via real ``pg_dump`` (custom format)."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            dest_path.unlink()
        cmd = [
            _pg_bin("pg_dump"),
            "-h", self.config.host,
            "-p", str(self.config.port),
            "-U", self.config.user,
            "-F", "c",
            "-f", str(dest_path),
            self.config.dbname,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {proc.stderr}")
        return dest_path

    def restore_new(self, backup_path: Path, dest_path: Path) -> "PostgresBackend":
        """Restore *backup_path* into a fresh database at *dest_path* using real
        ``pg_restore``.  Returns a new backend over the restored database."""
        # Derive a safe, unique database name from dest_path.
        target_db = _sanitize_dbname(dest_path)
        maint = psycopg.connect(
            self.config.dsn_for(self.config.maintenance_db), row_factory=dict_row, autocommit=True
        )
        try:
            target_ident = psql.Identifier(target_db).as_string(maint)
            maint.execute(f"DROP DATABASE IF EXISTS {target_ident} WITH (FORCE)")
            maint.execute(f"CREATE DATABASE {target_ident}")
        finally:
            maint.close()
        cmd = [
            _pg_bin("pg_restore"),
            "-h", self.config.host,
            "-p", str(self.config.port),
            "-U", self.config.user,
            "-d", target_db,
            "--no-owner",
            str(backup_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"pg_restore failed: {proc.stderr}")
        restored_config = PostgresConfig(
            host=self.config.host, port=self.config.port,
            dbname=target_db, user=self.config.user,
            maintenance_db=self.config.maintenance_db,
        )
        return PostgresBackend(restored_config)

    def close(self) -> None:
        # No persistent connections held; nothing to close.
        pass

    def spawn_crash_child(self, work_spec: Dict[str, Any], tmp_dir: Path) -> Tuple[Dict[str, Any], "PostgresBackend"]:
        """Launch a subprocess that reconstructs this backend, commits work,
        writes a readiness receipt with fsynced commit-boundary facts, and
        stays alive (busy-loop).  Returns ``(evidence_dict, reopened_backend)``.

        The invariant handles receipt polling, SIGKILL and reopening.  This
        method MUST NOT SIGKILL or kill the child — the invariant controls
        the crash boundary.
        """
        receipt_path = str(tmp_dir / "crash_receipt.json")
        # The child subprocess runs under the same interpreter as the parent
        # (``sys.executable``).  When the parent uses the system Python 3.12
        # with the task venv prepended for psycopg, the child MUST also prepend
        # the task venv site-packages or psycopg will not import.  Pass the
        # venv path through the environment so the child can reconstruct it.
        venv_site = os.environ.get("TASK18_PG_VENV_SITE", "")
        child_code = textwrap.dedent(
            f"""
            import sys, json, time, os
            _venv_site = {venv_site!r}
            if _venv_site:
                sys.path.insert(0, _venv_site)
            sys.path.insert(0, {str(Path('services/api').resolve())!r})
            sys.path.insert(0, {str(Path('.').resolve())!r})
            from pathlib import Path as _Path
            from pocs.protocol_v3.storage.postgres_adapter import PostgresBackend, PostgresConfig
            from pocs.protocol_v3.storage.contract_suite import _crash_child_commit
            _config = PostgresConfig(
                host={self.config.host!r}, port={self.config.port},
                dbname={self.config.dbname!r}, user={self.config.user!r},
                maintenance_db={self.config.maintenance_db!r},
            )
            _db = PostgresBackend(_config)
            _receipt = _Path({receipt_path!r})
            _crash_child_commit(_db, {work_spec!r}, _receipt)
            # Stay alive for parent SIGKILL — do NOT exit.
            while True:
                try:
                    time.sleep(60)
                except (KeyboardInterrupt, SystemExit):
                    pass
            """
        )
        child_path = tmp_dir / "crash_child.py"
        child_path.write_text(child_code, encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, str(child_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(Path(".").resolve()),
        )
        evidence = {
            "receipt_path": receipt_path,
            "child_pid": proc.pid,
        }
        reopened = PostgresBackend(self.config)
        return evidence, reopened

    def open_checkpoint_store(self) -> CheckpointStore:
        conn = _connect(self.config)
        return _PgCheckpointStore(conn)

    def open_quarantine_store(self) -> QuarantineStore:
        conn = _connect(self.config)
        return _PgQuarantineStore(conn)

    def inspect_connection_ids(self, uow: PgUnitOfWork) -> Dict[str, Any]:
        return {
            "connection_identity": uow.connection_identity,
            "backend_pid": uow.connection_identity,
            "postgres_version": self.postgres_version,
        }

    def count_duplicate_semantic_effects(
        self, project_id: str, aggregate_id: str, aggregate_kind: str = "study_definition"
    ) -> int:
        conn = _connect(self.config)
        try:
            cur = conn.execute(
                "SELECT COUNT(*) AS c FROM ("
                "  SELECT revision FROM aggregate_revision "
                "  WHERE aggregate_kind=%s AND project_id=%s AND aggregate_id=%s "
                "  GROUP BY revision HAVING COUNT(*) > 1"
                ") AS dup",
                (aggregate_kind, project_id, aggregate_id),
            )
            return int(cur.fetchone()["c"])
        finally:
            conn.close()


def _sanitize_dbname(path: Path) -> str:
    """Derive a safe PostgreSQL database name from a path stem."""
    stem = path.stem
    # Replace anything not [a-z0-9_] (PostgreSQL identifier rules), lowercase.
    sanitized = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in stem)
    sanitized = sanitized.lower()
    if not sanitized:
        sanitized = "restored"
    if not sanitized[0].isalpha() and sanitized[0] != "_":
        sanitized = "r_" + sanitized
    # Keep it short enough for PostgreSQL name length.
    return sanitized[:40]


def build_postgres_backend(config: PostgresConfig) -> PostgresBackend:
    return PostgresBackend(config)


def new_unit_of_work(backend: PostgresBackend) -> PgUnitOfWork:
    """Open a fresh UoW on an existing :class:`PostgresBackend`."""
    return backend.new_uow()