"""Fixed-SQLite-3.53.1 candidate adapter for the Protocol v3 storage PoC.

This module implements the storage-neutral repository and unit-of-work ports
defined in ``app.protocol_workflow.ports`` plus the database-neutral
:class:`Backend` control protocol consumed by ``contract_suite.py``.  It is a
PoC candidate, NOT a product module.

Architecture for the 8-independent-writer proof: each :class:`SqliteUnitOfWork`
opens its OWN ``sqlite3.Connection`` to the same WAL database file.  There is
no application-side serialization (no shared RLock held across a transaction).
Writer contention is resolved at the database layer by SQLite's WAL
write/lock protocol plus a bounded ``busy_timeout``.  CAS correctness is
enforced inside each connection's ``BEGIN IMMEDIATE`` transaction.

Durability configuration (justified against official SQLite references):

* ``journal_mode=WAL`` — concurrent readers during a writer transaction
  (https://www.sqlite.org/wal.html).
* ``synchronous=FULL`` — every transaction fsyncs the WAL before COMMIT
  returns (https://www.sqlite.org/lockingv3.html), giving committed-event
  RPO=0.
* ``foreign_keys=ON``, ``busy_timeout=100``, ``temp_store=MEMORY``.

``assert_sqlite_version`` fails closed below 3.51.3 (the 3.51.0–3.51.2
multi-connection WAL-reset corruption defect is fixed in 3.51.3+).  The
pinned runtime is Homebrew Python 3.12 / SQLite 3.53.1.
"""

from __future__ import annotations

import json
import shutil
import signal
import sqlite3
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

#: SQLite error message fragments that indicate a retryable lock/busy/deadlock
#: condition (as opposed to a genuine programming/validation error).
_LOCK_ERROR_FRAGMENTS = ("database is locked", "database table is locked", "deadlock", "busy")


def _translate_retryable(exc: Exception) -> None:
    """Re-raise *exc* as :class:`RetryableStorageError` if it is a known
    retryable SQLite lock/busy/deadlock failure; otherwise re-raise unchanged.

    This keeps the adapter's retry classification truthful: only genuine
    contention failures are surfaced as retryable; programming, assertion and
    validation errors propagate and fail the invariant immediately.
    """
    if isinstance(exc, sqlite3.OperationalError):
        msg = str(exc).lower()
        if any(frag in msg for frag in _LOCK_ERROR_FRAGMENTS):
            raise RetryableStorageError(str(exc)) from exc
    raise exc

# ---------------------------------------------------------------------------
# Version gate
# ---------------------------------------------------------------------------

MIN_SQLITE_VERSION: Tuple[int, int, int] = (3, 51, 3)


def parse_sqlite_version(version: str) -> Tuple[int, int, int]:
    parts = version.split(".")
    return tuple(int(p) for p in parts[:3])  # type: ignore[return-value]


def assert_sqlite_version(
    conn: Optional[sqlite3.Connection] = None,
    *,
    min_version: Tuple[int, int, int] = MIN_SQLITE_VERSION,
) -> Tuple[int, int, int]:
    """Fail closed if the linked SQLite is below *min_version*."""
    actual = parse_sqlite_version(
        sqlite3.sqlite_version
        if conn is None
        else conn.execute("select sqlite_version()").fetchone()[0]
    )
    if actual < min_version:
        raise RuntimeError(
            f"linked SQLite {actual} is below the required {min_version}; "
            f"affected runtimes (3.51.0-3.51.2) fail closed for the WAL PoC"
        )
    return actual


# ---------------------------------------------------------------------------
# Schema DDL (frozen benchmark schema)
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS aggregate_revision (
    aggregate_kind   TEXT    NOT NULL,
    project_id       TEXT    NOT NULL,
    aggregate_id     TEXT    NOT NULL,
    revision         INTEGER NOT NULL,
    body_json        TEXT    NOT NULL,
    previous_revision_sha256 TEXT,
    PRIMARY KEY (aggregate_kind, project_id, aggregate_id, revision)
);

CREATE TABLE IF NOT EXISTS event_stream (
    project_id       TEXT    NOT NULL,
    stream_id        TEXT    NOT NULL,
    sequence         INTEGER NOT NULL,
    domain_event_id  TEXT    NOT NULL,
    body_json        TEXT    NOT NULL,
    previous_event_sha256 TEXT,
    event_sha256     TEXT    NOT NULL,
    PRIMARY KEY (project_id, stream_id, sequence),
    UNIQUE (project_id, stream_id, domain_event_id)
);

CREATE TABLE IF NOT EXISTS outbox_message (
    outbox_message_id TEXT    NOT NULL PRIMARY KEY,
    project_id        TEXT    NOT NULL,
    workflow_run_id   TEXT    NOT NULL,
    side_effect_kind  TEXT    NOT NULL,
    logical_key       TEXT    NOT NULL,
    payload_sha256    TEXT    NOT NULL,
    status            TEXT    NOT NULL,
    created_at        TEXT    NOT NULL,
    dispatched_at     TEXT,
    completed_at      TEXT,
    attempt           INTEGER NOT NULL DEFAULT 0,
    error_detail      TEXT,
    UNIQUE (project_id, logical_key)
);

CREATE TABLE IF NOT EXISTS inbox_result (
    inbox_result_id TEXT    NOT NULL PRIMARY KEY,
    project_id      TEXT    NOT NULL,
    logical_key     TEXT    NOT NULL,
    result_sha256   TEXT    NOT NULL,
    status          TEXT    NOT NULL,
    received_at     TEXT    NOT NULL,
    consumed_at     TEXT,
    UNIQUE (project_id, logical_key)
);

CREATE TABLE IF NOT EXISTS execution_reservation (
    execution_reservation_id TEXT    NOT NULL PRIMARY KEY,
    project_id               TEXT    NOT NULL,
    node_execution_contract_id TEXT NOT NULL,
    logical_call_id          TEXT    NOT NULL,
    idempotency_key          TEXT    NOT NULL,
    input_sha256             TEXT    NOT NULL,
    attempt                  INTEGER NOT NULL,
    transport_attempts       INTEGER NOT NULL DEFAULT 0,
    provider_session_id      TEXT,
    status                   TEXT    NOT NULL,
    terminal_state           TEXT,
    output_sha256            TEXT,
    error_code               TEXT,
    reserved_at              TEXT    NOT NULL,
    updated_at               TEXT    NOT NULL,
    UNIQUE (project_id, logical_call_id, idempotency_key),
    UNIQUE (project_id, logical_call_id, attempt)
);

CREATE TABLE IF NOT EXISTS read_chapter_coverage (
    project_id              TEXT NOT NULL,
    semantic_document_revision_id TEXT NOT NULL,
    semantic_node_id        TEXT NOT NULL,
    chapter_contract_sha256 TEXT,
    substantive_content_contract_sha256 TEXT,
    semantic_block_sha256   TEXT,
    is_locked               INTEGER NOT NULL,
    has_substantive_content INTEGER NOT NULL,
    evidence_admitted       INTEGER NOT NULL,
    PRIMARY KEY (project_id, semantic_document_revision_id, semantic_node_id)
);

CREATE TABLE IF NOT EXISTS read_decision_graph (
    project_id        TEXT NOT NULL,
    study_definition_id TEXT NOT NULL,
    decision_key      TEXT NOT NULL,
    decision_record_id TEXT,
    state_revision    INTEGER,
    selected_option_id TEXT,
    canonical_state   TEXT,
    PRIMARY KEY (project_id, study_definition_id, decision_key)
);

CREATE TABLE IF NOT EXISTS read_workflow_run_status (
    project_id       TEXT NOT NULL,
    workflow_run_id  TEXT NOT NULL,
    status           TEXT NOT NULL,
    display_progress REAL NOT NULL,
    journey_counter  INTEGER NOT NULL,
    PRIMARY KEY (project_id, workflow_run_id)
);

CREATE TABLE IF NOT EXISTS checkpoint_record (
    project_id      TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    stream_id       TEXT NOT NULL,
    checkpoint_seq  INTEGER NOT NULL,
    checkpoint_sha  TEXT NOT NULL,
    state           INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, run_id)
);

CREATE TABLE IF NOT EXISTS migration_quarantine (
    quarantine_id    INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    source_kind      TEXT NOT NULL,
    source_key       TEXT NOT NULL,
    reason           TEXT NOT NULL,
    body_json        TEXT NOT NULL,
    quarantined_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quarantine_record (
    family       TEXT NOT NULL,
    source_key   TEXT NOT NULL,
    reason_code  TEXT NOT NULL,
    body_hash    TEXT NOT NULL,
    body         TEXT NOT NULL,
    PRIMARY KEY (family, source_key)
);
"""


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
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _json_to_model(json_str: str, model_cls: type) -> ProtocolV3Model:
    return model_cls.model_validate_json(json_str)


def _conn_for(db_path: Path, synchronous: str = "FULL", busy_timeout_ms: int = 100) -> sqlite3.Connection:
    """Open an independent connection to the WAL database with FULL durability.

    ``journal_mode=WAL`` is NOT set here: it is a persistent database setting
    established once at bootstrap.  Executing ``PRAGMA journal_mode=WAL`` on
    every UoW connection is itself a write operation that contends for the
    database lock; with 8 independent writers this caused avoidable
    ``database is locked`` escalations.

    ``busy_timeout_ms`` defaults to a short 100 ms so that a connection whose
    ``BEGIN IMMEDIATE`` cannot acquire the write lock fails fast; the
    benchmark suite treats ``database is locked`` as a busy retry and retries
    with bounded backoff.  A long 30 s busy_timeout makes each lock wait block
    the writer for 30 s, which is not what the CAS benchmark wants.
    """
    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,  # manual transaction control
        check_same_thread=False,
        timeout=busy_timeout_ms / 1000.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA synchronous={synchronous}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


# ---------------------------------------------------------------------------
# Repository implementations (each bound to ONE connection)
# ---------------------------------------------------------------------------


class _Guard:
    """Per-UoW open/closed guard shared by all repository handles."""

    __slots__ = ("closed",)

    def __init__(self) -> None:
        self.closed = False

    def ensure_open(self) -> None:
        if self.closed:
            raise UnitOfWorkClosedError("unit of work is closed")


class _SqliteCurrentAggregateRepo:
    def __init__(self, conn: sqlite3.Connection, aggregate_kind: str, identity_field: str, model_cls: type, guard: _Guard) -> None:
        self._conn = conn
        self._kind = aggregate_kind
        self._identity_field = identity_field
        self._model_cls = model_cls
        self._guard = guard

    def _row_to_model(self, row: sqlite3.Row) -> ProtocolV3Model:
        return _json_to_model(row["body_json"], self._model_cls)

    def get_current(self, project_id: str, aggregate_id: str):
        row = self._conn.execute(
            "SELECT body_json FROM aggregate_revision "
            "WHERE aggregate_kind=? AND project_id=? AND aggregate_id=? "
            "ORDER BY revision DESC LIMIT 1",
            (self._kind, project_id, aggregate_id),
        ).fetchone()
        return self._row_to_model(row) if row else None

    def get_current_required(self, project_id: str, aggregate_id: str):
        record = self.get_current(project_id, aggregate_id)
        if record is None:
            raise AggregateNotFoundError(project_id, aggregate_id=aggregate_id)
        return record

    def get_at_revision(self, project_id: str, aggregate_id: str, revision: int):
        row = self._conn.execute(
            "SELECT body_json FROM aggregate_revision "
            "WHERE aggregate_kind=? AND project_id=? AND aggregate_id=? AND revision=?",
            (self._kind, project_id, aggregate_id, revision),
        ).fetchone()
        return self._row_to_model(row) if row else None

    def get_current_revision(self, project_id: str, aggregate_id: str) -> Optional[int]:
        row = self._conn.execute(
            "SELECT MAX(revision) AS r FROM aggregate_revision "
            "WHERE aggregate_kind=? AND project_id=? AND aggregate_id=?",
            (self._kind, project_id, aggregate_id),
        ).fetchone()
        if row is None or row["r"] is None:
            return None
        return row["r"]


class _SqliteCasRepo:
    def __init__(self, conn: sqlite3.Connection, aggregate_kind: str, identity_field: str, model_cls: type, guard: _Guard) -> None:
        self._conn = conn
        self._kind = aggregate_kind
        self._identity_field = identity_field
        self._model_cls = model_cls
        self._guard = guard

    def save_with_expected_revision(self, project_id: str, record, expected_revision: int):
        self._guard.ensure_open()
        aggregate_id = getattr(record, self._identity_field)
        new_revision = getattr(record, "revision", None)
        row = self._conn.execute(
            "SELECT MAX(revision) AS r FROM aggregate_revision "
            "WHERE aggregate_kind=? AND project_id=? AND aggregate_id=?",
            (self._kind, project_id, aggregate_id),
        ).fetchone()
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
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self._kind,
                    project_id,
                    aggregate_id,
                    new_revision,
                    _model_to_json(record),
                    getattr(record, "previous_revision_sha256", None),
                ),
            )
        except sqlite3.OperationalError as exc:
            _translate_retryable(exc)
        return record

    def get_current_revision(self, project_id: str, aggregate_id: str) -> Optional[int]:
        row = self._conn.execute(
            "SELECT MAX(revision) AS r FROM aggregate_revision "
            "WHERE aggregate_kind=? AND project_id=? AND aggregate_id=?",
            (self._kind, project_id, aggregate_id),
        ).fetchone()
        if row is None or row["r"] is None:
            return None
        return row["r"]

    def get_current(self, project_id: str, aggregate_id: str):
        row = self._conn.execute(
            "SELECT body_json FROM aggregate_revision "
            "WHERE aggregate_kind=? AND project_id=? AND aggregate_id=? "
            "ORDER BY revision DESC LIMIT 1",
            (self._kind, project_id, aggregate_id),
        ).fetchone()
        return _json_to_model(row["body_json"], self._model_cls) if row else None


class _SqliteEventStreamRepo:
    def __init__(self, conn: sqlite3.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def append_events(self, project_id: str, stream_id: str, events: Sequence[DomainEvent]) -> Tuple[DomainEvent, ...]:
        self._guard.ensure_open()
        if not events:
            return ()
        head_row = self._conn.execute(
            "SELECT sequence, event_sha256, domain_event_id FROM event_stream "
            "WHERE project_id=? AND stream_id=? ORDER BY sequence DESC LIMIT 1",
            (project_id, stream_id),
        ).fetchone()
        last_seq = head_row["sequence"] if head_row else 0
        last_sha: Optional[str] = head_row["event_sha256"] if head_row else None
        seen_ids = {
            r["domain_event_id"]
            for r in self._conn.execute(
                "SELECT domain_event_id FROM event_stream WHERE project_id=? AND stream_id=?",
                (project_id, stream_id),
            )
        }
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
            self._conn.execute(
                "INSERT INTO event_stream "
                "(project_id, stream_id, sequence, domain_event_id, body_json, previous_event_sha256, event_sha256) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, stream_id, evt.sequence, evt.domain_event_id, _model_to_json(evt),
                 evt.previous_event_sha256, evt.event_sha256),
            )
            pending.append(evt)
        return tuple(pending)

    def read_events(self, project_id: str, stream_id: str, *, from_sequence: int = 1) -> Tuple[DomainEvent, ...]:
        rows = self._conn.execute(
            "SELECT body_json FROM event_stream "
            "WHERE project_id=? AND stream_id=? AND sequence >= ? ORDER BY sequence",
            (project_id, stream_id, from_sequence),
        ).fetchall()
        return tuple(_json_to_model(r["body_json"], DomainEvent) for r in rows)  # type: ignore[arg-type]

    def get_stream_head(self, project_id: str, stream_id: str) -> Optional[StreamHead]:
        row = self._conn.execute(
            "SELECT sequence, event_sha256, (SELECT COUNT(*) FROM event_stream "
            "WHERE project_id=? AND stream_id=?) AS cnt FROM event_stream "
            "WHERE project_id=? AND stream_id=? ORDER BY sequence DESC LIMIT 1",
            (project_id, stream_id, project_id, stream_id),
        ).fetchone()
        if row is None:
            return None
        return StreamHead(
            stream_id=stream_id, last_sequence=row["sequence"],
            last_event_sha256=row["event_sha256"], event_count=row["cnt"],
        )


class _SqliteOutboxRepo:
    def __init__(self, conn: sqlite3.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def _row_to_msg(self, row: sqlite3.Row) -> OutboxMessage:
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
        row = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=? AND logical_key=?",
            (project_id, logical_key),
        ).fetchone()
        if row is not None:
            if row["payload_sha256"] == payload_sha256:
                return self._row_to_msg(row)
            raise IdempotencyConflictError(project_id, logical_key, row["payload_sha256"], payload_sha256)
        nxt = int(self._conn.execute("SELECT COALESCE(MAX(rowid),0)+1 FROM outbox_message").fetchone()[0])
        message_id = f"ob-{nxt}-{logical_key}"
        self._conn.execute(
            "INSERT INTO outbox_message "
            "(outbox_message_id, project_id, workflow_run_id, side_effect_kind, logical_key, payload_sha256, status, created_at, attempt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (message_id, project_id, workflow_run_id, str(side_effect_kind), logical_key,
             payload_sha256, OutboxStatus.PENDING.value, _dt_to_iso(created_at)),
        )
        return self._row_to_msg(self._conn.execute("SELECT * FROM outbox_message WHERE outbox_message_id=?", (message_id,)).fetchone())

    def claim_pending(self, project_id: str, *, limit: int, claimed_at: datetime) -> Tuple[OutboxMessage, ...]:
        self._guard.ensure_open()
        rows = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=? AND status=? "
            "ORDER BY created_at, outbox_message_id LIMIT ?",
            (project_id, OutboxStatus.PENDING.value, limit),
        ).fetchall()
        claimed = []
        for row in rows:
            self._conn.execute(
                "UPDATE outbox_message SET status=?, dispatched_at=?, attempt=attempt+1 WHERE outbox_message_id=?",
                (OutboxStatus.DISPATCHED.value, _dt_to_iso(claimed_at), row["outbox_message_id"]),
            )
            claimed.append(self._row_to_msg(self._conn.execute("SELECT * FROM outbox_message WHERE outbox_message_id=?", (row["outbox_message_id"],)).fetchone()))
        return tuple(claimed)

    def mark_completed(self, project_id: str, outbox_message_id: str, completed_at: datetime) -> OutboxMessage:
        self._guard.ensure_open()
        row = self._conn.execute("SELECT * FROM outbox_message WHERE outbox_message_id=? AND project_id=?", (outbox_message_id, project_id)).fetchone()
        if row is None:
            raise AggregateNotFoundError(project_id, aggregate_id=outbox_message_id)
        if row["status"] != OutboxStatus.DISPATCHED.value:
            raise RepositoryStateTransitionError(project_id, outbox_message_id, from_status=row["status"], to_status=OutboxStatus.COMPLETED.value)
        self._conn.execute("UPDATE outbox_message SET status=?, completed_at=? WHERE outbox_message_id=?",
                           (OutboxStatus.COMPLETED.value, _dt_to_iso(completed_at), outbox_message_id))
        return self._row_to_msg(self._conn.execute("SELECT * FROM outbox_message WHERE outbox_message_id=?", (outbox_message_id,)).fetchone())

    def mark_failed(self, project_id: str, outbox_message_id: str, error_detail: str, failed_at: datetime) -> OutboxMessage:
        self._guard.ensure_open()
        row = self._conn.execute("SELECT * FROM outbox_message WHERE outbox_message_id=? AND project_id=?", (outbox_message_id, project_id)).fetchone()
        if row is None:
            raise AggregateNotFoundError(project_id, aggregate_id=outbox_message_id)
        if row["status"] != OutboxStatus.DISPATCHED.value:
            raise RepositoryStateTransitionError(project_id, outbox_message_id, from_status=row["status"], to_status=OutboxStatus.FAILED.value)
        self._conn.execute("UPDATE outbox_message SET status=?, completed_at=?, error_detail=? WHERE outbox_message_id=?",
                           (OutboxStatus.FAILED.value, _dt_to_iso(failed_at), error_detail, outbox_message_id))
        return self._row_to_msg(self._conn.execute("SELECT * FROM outbox_message WHERE outbox_message_id=?", (outbox_message_id,)).fetchone())

    def get(self, project_id: str, outbox_message_id: str) -> Optional[OutboxMessage]:
        row = self._conn.execute("SELECT * FROM outbox_message WHERE outbox_message_id=? AND project_id=?", (outbox_message_id, project_id)).fetchone()
        return self._row_to_msg(row) if row else None

    def find_by_logical_key(self, project_id: str, logical_key: str) -> Optional[OutboxMessage]:
        row = self._conn.execute("SELECT * FROM outbox_message WHERE project_id=? AND logical_key=?", (project_id, logical_key)).fetchone()
        return self._row_to_msg(row) if row else None

    def list_dispatched(self, project_id: str, *, limit: int) -> Tuple[OutboxMessage, ...]:
        rows = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=? AND status=? "
            "ORDER BY created_at, outbox_message_id LIMIT ?",
            (project_id, OutboxStatus.DISPATCHED.value, limit),
        ).fetchall()
        return tuple(self._row_to_msg(r) for r in rows)


class _SqliteInboxRepo:
    def __init__(self, conn: sqlite3.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def _row_to_result(self, row: sqlite3.Row) -> InboxResult:
        return InboxResult(
            inbox_result_id=row["inbox_result_id"], project_id=row["project_id"],
            logical_key=row["logical_key"], result_sha256=row["result_sha256"],
            status=InboxStatus(row["status"]), received_at=_dt_from_iso(row["received_at"]),  # type: ignore[arg-type]
            consumed_at=_dt_from_iso(row["consumed_at"]),
        )

    def record_result(self, project_id: str, logical_key: str, result_sha256: str, received_at: datetime) -> InboxResult:
        self._guard.ensure_open()
        row = self._conn.execute("SELECT * FROM inbox_result WHERE project_id=? AND logical_key=?", (project_id, logical_key)).fetchone()
        if row is not None:
            if row["result_sha256"] == result_sha256:
                return self._row_to_result(row)
            raise IdempotencyConflictError(project_id, logical_key, row["result_sha256"], result_sha256)
        nxt = int(self._conn.execute("SELECT COALESCE(MAX(rowid),0)+1 FROM inbox_result").fetchone()[0])
        result_id = f"ib-{nxt}-{logical_key}"
        self._conn.execute(
            "INSERT INTO inbox_result (inbox_result_id, project_id, logical_key, result_sha256, status, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (result_id, project_id, logical_key, result_sha256, InboxStatus.RECEIVED.value, _dt_to_iso(received_at)),
        )
        return self._row_to_result(self._conn.execute("SELECT * FROM inbox_result WHERE inbox_result_id=?", (result_id,)).fetchone())

    def get_result(self, project_id: str, logical_key: str) -> Optional[InboxResult]:
        row = self._conn.execute("SELECT * FROM inbox_result WHERE project_id=? AND logical_key=?", (project_id, logical_key)).fetchone()
        return self._row_to_result(row) if row else None

    def was_processed(self, project_id: str, logical_key: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM inbox_result WHERE project_id=? AND logical_key=?", (project_id, logical_key)).fetchone()
        return row is not None

    def mark_consumed(self, project_id: str, logical_key: str, consumed_at: datetime) -> InboxResult:
        self._guard.ensure_open()
        row = self._conn.execute("SELECT * FROM inbox_result WHERE project_id=? AND logical_key=?", (project_id, logical_key)).fetchone()
        if row is None:
            raise AggregateNotFoundError(project_id, aggregate_id=logical_key)
        if row["status"] != InboxStatus.RECEIVED.value:
            raise RepositoryStateTransitionError(project_id, logical_key, from_status=row["status"], to_status=InboxStatus.CONSUMED.value)
        self._conn.execute("UPDATE inbox_result SET status=?, consumed_at=? WHERE inbox_result_id=?", (InboxStatus.CONSUMED.value, _dt_to_iso(consumed_at), row["inbox_result_id"]))
        return self._row_to_result(self._conn.execute("SELECT * FROM inbox_result WHERE inbox_result_id=?", (row["inbox_result_id"],)).fetchone())


class _SqliteReservationRepo:
    def __init__(self, conn: sqlite3.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def _row_to_reservation(self, row: sqlite3.Row) -> ExecutionReservation:
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
        row = self._conn.execute(
            "SELECT * FROM execution_reservation WHERE project_id=? AND logical_call_id=? AND idempotency_key=?",
            (project_id, reservation.logical_call_id, reservation.idempotency_key),
        ).fetchone()
        if row is not None:
            existing = self._row_to_reservation(row)
            if existing.input_sha256 != reservation.input_sha256:
                raise IdempotencyConflictError(project_id, reservation.logical_call_id, existing.input_sha256, reservation.input_sha256)
            if existing.status is ReservationStatus.UNKNOWN_OUTCOME:
                raise UnknownOutcomeConflictError(project_id, aggregate_id=reservation.logical_call_id,
                                                  detail="unknown-outcome reservation must be resolved before re-dispatch")
            return existing
        self._conn.execute(
            "INSERT INTO execution_reservation "
            "(execution_reservation_id, project_id, node_execution_contract_id, logical_call_id, idempotency_key, "
            " input_sha256, attempt, transport_attempts, provider_session_id, status, terminal_state, "
            " output_sha256, error_code, reserved_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (reservation.execution_reservation_id, project_id, reservation.node_execution_contract_id,
             reservation.logical_call_id, reservation.idempotency_key, reservation.input_sha256,
             reservation.attempt, reservation.transport_attempts, reservation.provider_session_id,
             reservation.status.value,
             reservation.terminal_state.value if reservation.terminal_state else None,
             reservation.output_sha256, reservation.error_code,
             _dt_to_iso(reservation.reserved_at), _dt_to_iso(reservation.updated_at)),
        )
        return reservation

    def get(self, project_id: str, execution_reservation_id: str) -> Optional[ExecutionReservation]:
        row = self._conn.execute("SELECT * FROM execution_reservation WHERE project_id=? AND execution_reservation_id=?", (project_id, execution_reservation_id)).fetchone()
        return self._row_to_reservation(row) if row else None

    def find_by_logical_call(self, project_id: str, logical_call_id: str, idempotency_key: str) -> Optional[ExecutionReservation]:
        row = self._conn.execute("SELECT * FROM execution_reservation WHERE project_id=? AND logical_call_id=? AND idempotency_key=?", (project_id, logical_call_id, idempotency_key)).fetchone()
        return self._row_to_reservation(row) if row else None

    def transition(self, project_id: str, execution_reservation_id: str, *, to_status: ReservationStatus,
                   terminal_state: Optional[ExecutionTerminalState] = None, output_sha256: Optional[str] = None,
                   error_code: Optional[str] = None, provider_session_id: Optional[str] = None,
                   transport_attempts: Optional[int] = None, updated_at: datetime) -> ExecutionReservation:
        self._guard.ensure_open()
        row = self._conn.execute("SELECT * FROM execution_reservation WHERE project_id=? AND execution_reservation_id=?", (project_id, execution_reservation_id)).fetchone()
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
            "UPDATE execution_reservation SET status=?, terminal_state=?, output_sha256=?, error_code=?, "
            "provider_session_id=?, transport_attempts=?, updated_at=? WHERE execution_reservation_id=?",
            (updated.status.value, updated.terminal_state.value if updated.terminal_state else None,
             updated.output_sha256, updated.error_code, updated.provider_session_id,
             updated.transport_attempts, _dt_to_iso(updated.updated_at), execution_reservation_id),
        )
        return updated

    def list_attempts(self, project_id: str, logical_call_id: str) -> Tuple[ExecutionReservation, ...]:
        rows = self._conn.execute("SELECT * FROM execution_reservation WHERE project_id=? AND logical_call_id=? ORDER BY attempt, execution_reservation_id", (project_id, logical_call_id)).fetchall()
        return tuple(self._row_to_reservation(r) for r in rows)

    def find_unknown_outcome(self, project_id: str) -> Tuple[ExecutionReservation, ...]:
        rows = self._conn.execute("SELECT * FROM execution_reservation WHERE project_id=? AND status=? ORDER BY logical_call_id, attempt", (project_id, ReservationStatus.UNKNOWN_OUTCOME.value)).fetchall()
        return tuple(self._row_to_reservation(r) for r in rows)

    def find_unresolved(self, project_id: str) -> Tuple[ExecutionReservation, ...]:
        rows = self._conn.execute(
            "SELECT * FROM execution_reservation WHERE project_id=? AND status IN (?, ?, ?) "
            "ORDER BY logical_call_id, attempt, execution_reservation_id",
            (project_id, ReservationStatus.RESERVED.value, ReservationStatus.RUNNING.value, ReservationStatus.UNKNOWN_OUTCOME.value),
        ).fetchall()
        return tuple(self._row_to_reservation(r) for r in rows)


class _SqliteReadModelRepo:
    def __init__(self, conn: sqlite3.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def get_chapter_coverage(self, project_id: str, semantic_document_revision_id: str) -> Tuple[ChapterCoverageRecord, ...]:
        rows = self._conn.execute(
            "SELECT * FROM read_chapter_coverage WHERE project_id=? AND semantic_document_revision_id=? ORDER BY semantic_node_id",
            (project_id, semantic_document_revision_id),
        ).fetchall()
        return tuple(
            ChapterCoverageRecord(
                project_id=r["project_id"], semantic_node_id=r["semantic_node_id"],
                chapter_contract_sha256=r["chapter_contract_sha256"],
                substantive_content_contract_sha256=r["substantive_content_contract_sha256"],
                semantic_block_sha256=r["semantic_block_sha256"], is_locked=bool(r["is_locked"]),
                has_substantive_content=bool(r["has_substantive_content"]), evidence_admitted=bool(r["evidence_admitted"]),
            )
            for r in rows
        )

    def get_decision_graph(self, project_id: str, study_definition_id: str) -> Tuple[DecisionGraphRecord, ...]:
        rows = self._conn.execute("SELECT * FROM read_decision_graph WHERE project_id=? AND study_definition_id=? ORDER BY decision_key", (project_id, study_definition_id)).fetchall()
        return tuple(
            DecisionGraphRecord(
                project_id=r["project_id"], decision_key=r["decision_key"], decision_record_id=r["decision_record_id"],
                state_revision=r["state_revision"], selected_option_id=r["selected_option_id"],
                canonical_state=CanonicalState(r["canonical_state"]) if r["canonical_state"] else None,
            )
            for r in rows
        )

    def get_workflow_run_status(self, project_id: str, workflow_run_id: str) -> Optional[WorkflowRunStatusRecord]:
        row = self._conn.execute("SELECT * FROM read_workflow_run_status WHERE project_id=? AND workflow_run_id=?", (project_id, workflow_run_id)).fetchone()
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
            "INSERT OR REPLACE INTO read_chapter_coverage "
            "(project_id, semantic_document_revision_id, semantic_node_id, chapter_contract_sha256, "
            " substantive_content_contract_sha256, semantic_block_sha256, is_locked, has_substantive_content, evidence_admitted) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, revision_id, record.semantic_node_id, record.chapter_contract_sha256,
             record.substantive_content_contract_sha256, record.semantic_block_sha256,
             int(record.is_locked), int(record.has_substantive_content), int(record.evidence_admitted)),
        )

    def upsert_decision_graph(self, project_id: str, study_definition_id: str, record: DecisionGraphRecord) -> None:
        self._guard.ensure_open()
        self._conn.execute(
            "INSERT OR REPLACE INTO read_decision_graph "
            "(project_id, study_definition_id, decision_key, decision_record_id, state_revision, selected_option_id, canonical_state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, study_definition_id, record.decision_key, record.decision_record_id,
             record.state_revision, record.selected_option_id,
             record.canonical_state.value if record.canonical_state else None),
        )

    def upsert_workflow_run_status(self, record: WorkflowRunStatusRecord) -> None:
        self._guard.ensure_open()
        self._conn.execute(
            "INSERT OR REPLACE INTO read_workflow_run_status "
            "(project_id, workflow_run_id, status, display_progress, journey_counter) VALUES (?, ?, ?, ?, ?)",
            (record.project_id, record.workflow_run_id, record.status.value, record.display_progress, record.journey_counter),
        )


# ---------------------------------------------------------------------------
# Unit of work — one independent connection per UoW
# ---------------------------------------------------------------------------


class SqliteUnitOfWork:
    """SQLite implementation of :class:`UnitOfWork`.

    Each instance opens its OWN connection to the WAL database.  ``__enter__``
    issues ``BEGIN IMMEDIATE`` (acquiring the write lock at the DB level);
    ``commit``/``rollback`` issue ``COMMIT``/``ROLLBACK`` and close the
    connection.  There is no application-side lock; independent writers race
    through SQLite's own WAL write protocol with ``busy_timeout``.
    """

    def __init__(self, db_path: Path, *, synchronous: str = "FULL", busy_timeout_ms: int = 100) -> None:
        self._db_path = db_path
        self._busy_timeout_ms = busy_timeout_ms
        self._conn = _conn_for(db_path, synchronous=synchronous, busy_timeout_ms=busy_timeout_ms)
        self._guard = _Guard()
        self._depth = 0
        self._closed = False
        self._conn_identity = self._conn.execute("select hex(randomblob(8))").fetchone()[0]
        self._sd_repo = _SqliteCurrentAggregateRepo(self._conn, "study_definition", "study_definition_id", StudyDefinitionV3, self._guard)
        self._sd_cas = _SqliteCasRepo(self._conn, "study_definition", "study_definition_id", StudyDefinitionV3, self._guard)
        self._sdr_repo = _SqliteCurrentAggregateRepo(self._conn, "semantic_document", "semantic_document_revision_id", SemanticDocumentRevision, self._guard)
        self._sdr_cas = _SqliteCasRepo(self._conn, "semantic_document", "semantic_document_revision_id", SemanticDocumentRevision, self._guard)
        self._events = _SqliteEventStreamRepo(self._conn, self._guard)
        self._outbox = _SqliteOutboxRepo(self._conn, self._guard)
        self._inbox = _SqliteInboxRepo(self._conn, self._guard)
        self._reservations = _SqliteReservationRepo(self._conn, self._guard)
        self._read_models = _SqliteReadModelRepo(self._conn, self._guard)

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
        """Close the underlying connection if present, then drop the reference.

        Idempotent: subsequent calls are no-ops because ``_conn`` is None.
        Always closes a non-None connection regardless of ``_closed`` — the
        caller (commit/rollback/close) may set ``_closed`` before invoking this
        to transition the state machine, but the DB connection must still be
        closed exactly once.
        """
        conn = self._conn
        self._conn = None  # type: ignore[assignment]
        if conn is not None:
            conn.close()

    def commit(self) -> None:
        if self._closed:
            return
        if self._depth > 1:
            self._depth -= 1
            return
        try:
            try:
                self._conn.execute("COMMIT")
            except sqlite3.OperationalError as exc:
                _translate_retryable(exc)
        finally:
            self._closed = True
            self._depth = 0
            self._guard.closed = True
            self._close_conn()

    def rollback(self) -> None:
        if self._closed:
            return
        try:
            self._conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            # no active transaction to roll back
            pass
        finally:
            self._closed = True
            self._depth = 0
            self._guard.closed = True
            self._close_conn()

    def __enter__(self) -> "SqliteUnitOfWork":
        if self._closed or self._conn is None:
            raise RuntimeError("unit of work is closed")
        if self._depth == 0:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
            except Exception as exc:
                # Always close the connection so we never leak, then re-raise.
                # Convert lock/busy/deadlock to RetryableStorageError so the
                # CAS worker retries only on genuine contention.
                self._closed = True
                self._guard.closed = True
                self._close_conn()
                _translate_retryable(exc)
        self._depth += 1
        return self

    def close(self) -> None:
        """Explicitly close the underlying connection (idempotent)."""
        if not self._closed:
            try:
                if self._conn is not None:
                    self._conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
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
# Backend control protocol implementation
# ---------------------------------------------------------------------------


class _SqliteCheckpointStore(CheckpointStore):
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _record_from_row(self, row: sqlite3.Row) -> CheckpointRecord:
        return _SqliteCheckpointRecord(
            project_id=row["project_id"], run_id=row["run_id"], stream_id=row["stream_id"],
            checkpoint_seq=row["checkpoint_seq"], checkpoint_sha=row["checkpoint_sha"],
        )

    def create(self, project_id: str, run_id: str, stream_id: str, checkpoint_seq: int,
               checkpoint_sha: str, *, state: int) -> CheckpointRecord:
        self._conn.execute(
            "INSERT OR REPLACE INTO checkpoint_record "
            "(project_id, run_id, stream_id, checkpoint_seq, checkpoint_sha, state) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, run_id, stream_id, checkpoint_seq, checkpoint_sha, state),
        )
        return self.get(project_id, run_id)  # type: ignore[return-value]

    def update(self, project_id: str, run_id: str, checkpoint_seq: int, checkpoint_sha: str) -> CheckpointRecord:
        self._conn.execute(
            "UPDATE checkpoint_record SET checkpoint_seq=?, checkpoint_sha=? WHERE project_id=? AND run_id=?",
            (checkpoint_seq, checkpoint_sha, project_id, run_id),
        )
        return self.get(project_id, run_id)  # type: ignore[return-value]

    def delete(self, project_id: str, run_id: str) -> None:
        self._conn.execute("DELETE FROM checkpoint_record WHERE project_id=? AND run_id=?", (project_id, run_id))

    def get(self, project_id: str, run_id: str) -> Optional[CheckpointRecord]:
        row = self._conn.execute("SELECT * FROM checkpoint_record WHERE project_id=? AND run_id=?", (project_id, run_id)).fetchone()
        return self._record_from_row(row) if row else None

    def list_runs(self, project_id: str) -> Tuple[str, ...]:
        rows = self._conn.execute("SELECT run_id FROM checkpoint_record WHERE project_id=? ORDER BY run_id", (project_id,)).fetchall()
        return tuple(r["run_id"] for r in rows)

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM checkpoint_record").fetchone()[0])

    def close(self) -> None:
        self._conn.close()


@dataclass
class _SqliteCheckpointRecord:
    project_id: str
    run_id: str
    stream_id: str
    checkpoint_seq: int
    checkpoint_sha: str


class _SqliteQuarantineStore:
    """SQLite implementation of the neutral :class:`QuarantineStore`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def quarantine(self, family: str, source_key: str, reason_code: str, body: str) -> QuarantineRecord:
        body_hash = sha256(body.encode("utf-8")).hexdigest()
        self._conn.execute(
            "INSERT OR REPLACE INTO quarantine_record "
            "(family, source_key, reason_code, body_hash, body) VALUES (?, ?, ?, ?, ?)",
            (family, source_key, reason_code, body_hash, body),
        )
        return _SqliteQuarantineRecord(
            family=family, source_key=source_key, reason_code=reason_code,
            body_hash=body_hash, body=body,
        )

    def list_quarantined(self, family: str) -> Tuple[QuarantineRecord, ...]:
        rows = self._conn.execute(
            "SELECT family, source_key, reason_code, body_hash, body FROM quarantine_record "
            "WHERE family=? ORDER BY source_key",
            (family,),
        ).fetchall()
        return tuple(
            _SqliteQuarantineRecord(
                family=r["family"], source_key=r["source_key"], reason_code=r["reason_code"],
                body_hash=r["body_hash"], body=r["body"],
            )
            for r in rows
        )

    def close(self) -> None:
        self._conn.close()


@dataclass
class _SqliteQuarantineRecord:
    family: str
    source_key: str
    reason_code: str
    body_hash: str
    body: str


class SqliteBackend:
    """Database-neutral :class:`Backend` adapter over a SQLite WAL database."""

    def __init__(self, db_path: Path, *, min_sqlite_version: Tuple[int, int, int] = MIN_SQLITE_VERSION) -> None:
        self.db_path = Path(db_path)
        self.config_min_version = min_sqlite_version
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Verify version + create schema on a bootstrap connection.
        probe = _conn_for(self.db_path)
        try:
            assert_sqlite_version(probe, min_version=min_sqlite_version)
            # Set journal_mode=WAL once here (persistent DB setting).
            probe.execute("PRAGMA journal_mode=WAL")
            probe.executescript(_SCHEMA_SQL)
        finally:
            probe.close()
        self._version = parse_sqlite_version(sqlite3.sqlite_version)

    @property
    def name(self) -> str:
        return "sqlite_3_53_1"

    @property
    def sqlite_version(self) -> str:
        return ".".join(str(v) for v in self._version)

    def new_uow(self) -> SqliteUnitOfWork:
        return SqliteUnitOfWork(self.db_path)

    def backup_to(self, dest_path: Path) -> Path:
        # Open a dedicated connection for a consistent online backup.
        src = _conn_for(self.db_path)
        try:
            src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            dest_path.unlink()
        dest = sqlite3.connect(str(dest_path))
        try:
            src.backup(dest, pages=-1)
            return dest_path
        finally:
            dest.close()
            src.close()

    def restore_new(self, backup_path: Path, dest_path: Path) -> "SqliteBackend":
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            dest_path.unlink()
        for suffix in ("-wal", "-shm"):
            side = Path(str(dest_path) + suffix)
            if side.exists():
                side.unlink()
        shutil.copy2(backup_path, dest_path)
        return SqliteBackend(dest_path, min_sqlite_version=self.config_min_version)

    def close(self) -> None:
        # No persistent connections held; nothing to close.
        pass

    def spawn_crash_child(self, work_spec: Dict[str, Any], tmp_dir: Path) -> Tuple[Dict[str, Any], "SqliteBackend"]:
        """Launch a subprocess that reconstructs this backend, commits work,
        writes a readiness receipt with fsynced commit-boundary facts, and
        stays alive (busy-loop).  Returns ``(evidence_dict, reopened_backend)``.

        The invariant handles receipt polling, SIGKILL and reopening.  This
        method MUST NOT SIGKILL or kill the child — the invariant controls
        the crash boundary.
        """
        import os, signal

        receipt_path = str(tmp_dir / "crash_receipt.json")
        child_code = textwrap.dedent(
            f"""
            import sys, json, time, os
            sys.path.insert(0, {str(Path('services/api').resolve())!r})
            sys.path.insert(0, {str(Path('.').resolve())!r})
            from pathlib import Path as _Path
            from pocs.protocol_v3.storage.sqlite_adapter import SqliteBackend
            from pocs.protocol_v3.storage.contract_suite import _crash_child_commit
            _db = SqliteBackend({str(self.db_path)!r})
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
        # Launch child — do NOT communicate; child stays alive for receipt.
        proc = subprocess.Popen(
            [sys.executable, str(child_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(Path(".").resolve()),
        )
        evidence = {
            "receipt_path": receipt_path,
            "child_pid": proc.pid,
        }
        reopened = SqliteBackend(self.db_path, min_sqlite_version=self.config_min_version)
        return evidence, reopened

    def open_checkpoint_store(self) -> CheckpointStore:
        conn = _conn_for(self.db_path)
        return _SqliteCheckpointStore(conn)

    def open_quarantine_store(self) -> QuarantineStore:
        conn = _conn_for(self.db_path)
        return _SqliteQuarantineStore(conn)

    def inspect_connection_ids(self, uow: SqliteUnitOfWork) -> Dict[str, Any]:
        return {
            "connection_identity": uow.connection_identity,
            "sqlite_version": self.sqlite_version,
            "journal_mode": uow._conn.execute("PRAGMA journal_mode").fetchone()[0] if uow._conn else "closed",
            "synchronous": uow._conn.execute("PRAGMA synchronous").fetchone()[0] if uow._conn else None,
        }

    def count_duplicate_semantic_effects(
        self, project_id: str, aggregate_id: str, aggregate_kind: str = "study_definition"
    ) -> int:
        conn = _conn_for(self.db_path, busy_timeout_ms=100)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM ("
                "  SELECT revision FROM aggregate_revision "
                "  WHERE aggregate_kind=? AND project_id=? AND aggregate_id=? "
                "  GROUP BY revision HAVING COUNT(*) > 1"
                ")",
                (aggregate_kind, project_id, aggregate_id),
            ).fetchone()
            return int(row["c"]) if row else 0
        finally:
            conn.close()


def build_sqlite_backend(db_path: Path, *, min_sqlite_version: Tuple[int, int, int] = MIN_SQLITE_VERSION) -> SqliteBackend:
    return SqliteBackend(db_path, min_sqlite_version=min_sqlite_version)


# ---------------------------------------------------------------------------
# Connection lifecycle probe
# ---------------------------------------------------------------------------


def _connection_is_open(conn: Optional[sqlite3.Connection]) -> bool:
    """Return ``True`` iff *conn* is a live, usable connection.

    A closed sqlite3 connection raises ``ProgrammingError`` on any statement;
    an open one succeeds.  This is a direct probe, independent of GC.
    """
    if conn is None:
        return False
    try:
        conn.execute("SELECT 1").fetchone()
        return True
    except sqlite3.ProgrammingError:
        return False


def run_lifecycle_probe(db_path: Path) -> Dict[str, Any]:
    """Prove commit, rollback, failed ``__enter__`` and explicit close each
    close the underlying connection exactly once / make the UoW unusable.

    Returns a deterministic evidence dict:
      - commit_closes_before_gc: after ``with uow:`` a UoW's connection is
        closed (uow._conn is None) and the UoW raises on reuse.
      - rollback_closes_before_gc: same after an exception-triggered rollback.
      - failed_enter_closes: when ``BEGIN IMMEDIATE`` cannot be issued the
        connection is still closed (no leak).
      - explicit_close_idempotent: calling ``close()`` twice is safe and both
        times the connection is closed.
    Assertions raise on any violation so the probe fails loudly.
    """
    db_path = Path(db_path)
    # The probe is a public executable check and must work on a fresh path;
    # bootstrap the exact candidate schema instead of relying on an undocumented
    # caller-side SqliteBackend construction.
    SqliteBackend(db_path).close()
    evidence: Dict[str, Any] = {}

    # 1. commit path
    uow = SqliteUnitOfWork(db_path, busy_timeout_ms=100)
    with uow:
        uow.study_definition_cas_repository.save_with_expected_revision(
            "p:life", _make_study_model("sd:commit", "p:life", 1), 0,
        )
    closed_after_commit = uow._conn is None
    unusable_after_commit = False
    try:
        with uow:
            pass
    except RuntimeError:
        unusable_after_commit = True
    evidence["commit_closes_before_gc"] = closed_after_commit
    evidence["commit_unusable_after"] = unusable_after_commit
    assert closed_after_commit, "commit did not close the connection"
    assert unusable_after_commit, "committed UoW is still usable (leak)"

    # 2. rollback path (exception through __exit__)
    uow = SqliteUnitOfWork(db_path, busy_timeout_ms=100)
    try:
        with uow:
            uow.study_definition_cas_repository.save_with_expected_revision(
                "p:life", _make_study_model("sd:rollback", "p:life", 1), 0,
            )
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass
    closed_after_rollback = uow._conn is None
    evidence["rollback_closes_before_gc"] = closed_after_rollback
    assert closed_after_rollback, "rollback did not close the connection"

    # 3. failed __enter__ (BEGIN IMMEDIATE must fail). We force it by opening
    #    a write transaction on another connection and holding it, then trying
    #    to enter a UoW with a tiny busy_timeout so BEGIN fails fast.
    holder = _conn_for(db_path, busy_timeout_ms=1)
    holder.execute("BEGIN IMMEDIATE")
    uow_fail = SqliteUnitOfWork(db_path, busy_timeout_ms=1)
    enter_raised = False
    try:
        with uow_fail:
            holder.execute("SELECT 1")
    except (sqlite3.OperationalError, RetryableStorageError):
        enter_raised = True
    finally:
        try:
            holder.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        holder.close()
    closed_after_failed_enter = uow_fail._conn is None
    evidence["failed_enter_raised"] = enter_raised
    evidence["failed_enter_closes"] = closed_after_failed_enter
    assert closed_after_failed_enter, "failed __enter__ leaked its connection"

    # 4. explicit close idempotent
    uow = SqliteUnitOfWork(db_path, busy_timeout_ms=100)
    uow.close()
    closed_first = uow._conn is None
    uow.close()  # second call must be a safe no-op
    closed_second = uow._conn is None
    evidence["explicit_close_closes"] = closed_first
    evidence["explicit_close_idempotent"] = closed_first and closed_second
    assert closed_first and closed_second, "explicit close not idempotent"

    evidence["probe_passed"] = True
    return evidence


def _make_study_model(study_id: str, project_id: str, revision: int) -> StudyDefinitionV3:
    from datetime import datetime, timezone as _tz

    return StudyDefinitionV3(
        study_definition_id=study_id,
        project_id=project_id,
        revision=revision,
        normalized_seed_id=f"seed:{study_id}",
        normalized_seed_sha256=f"{1:064x}",
        facts={"x": "1"},
        updated_at=datetime(2026, 1, 1, tzinfo=_tz.utc),
    )
