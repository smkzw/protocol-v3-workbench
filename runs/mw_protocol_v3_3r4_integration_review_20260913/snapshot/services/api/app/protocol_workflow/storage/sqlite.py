"""Product SQLite storage adapter for the Protocol v3 authority kernel.

This module realises the storage-neutral repository and unit-of-work ports
defined in ``app.protocol_workflow.ports`` on the selected backend (SQLite,
stdlib ``sqlite3`` driver) locked by the Task 1.8 decision record.  It mirrors
the accepted PoC adapter algorithms (``pocs/protocol_v3/storage/`` is evidence
and is NEVER imported by product code) without the PoC benchmark machinery:
no crash child, no checkpoint/quarantine stores, no benchmark retry driver.

Durability configuration (mirrors the accepted PoC evidence):

* ``journal_mode=WAL`` — set once per bootstrap; a persistent database
  setting (https://www.sqlite.org/wal.html).
* ``synchronous=FULL`` — every transaction fsyncs the WAL before COMMIT
  returns; committed-event RPO 0.
* ``foreign_keys=ON``, ``temp_store=MEMORY`` and a validated
  ``busy_timeout`` on every connection.

The engine gate (linked SQLite >= 3.51.3) is asserted at factory build time,
BEFORE any file or directory is created.  Databases are created only at an
explicitly configured path; there is no default runtime directory.

Schema management is explicit and fail-closed:

* a ``schema_version`` table records the applied migration version;
* ordered migrations each run in their own ``BEGIN IMMEDIATE`` transaction,
  together with the version-row insert, so repeated initialization is safe;
* a database written by a *future* product version (higher schema version)
  fails closed and is never rewritten;
* an existing database is verified READ-ONLY before any read-write connection
  is opened: a database without this schema's ``schema_version`` table, with
  a malformed/duplicate/gapped migration history, with missing/incompatible
  owned structures or with unknown extra tables is treated as foreign and is
  never adopted, mutated or renamed — rejection leaves the file byte-identical.

Unit-of-work semantics mirror the ports contract: one connection per UoW,
``BEGIN IMMEDIATE`` on first ``__enter__``, a single transaction spanning
canonical CAS saves, event appends and outbox enqueues, nested ``with``
blocks committing only at the outermost scope, and closed UoWs refusing
further mutations with :class:`UnitOfWorkClosedError`.  Event batches are
validated in full before any row is written, and every compound write (event
batch, projection replacement) additionally runs inside a SAVEPOINT, so even
a row-level SQL failure caught inside a larger transaction can never leak a
partially written compound operation.  Mutators require the active
``with unit_of_work:`` transaction scope — an unentered UoW refuses writes
fail-closed instead of silently autocommitting them.

The physical-dispatch runtime additionally has one narrow committed-operation
surface (:class:`SqliteCommittedOperationReservationRepository`, built by
``build_committed_reservation_repository_factory``): a reservation-repository
handle whose every operation is its own durable transaction, so a reservation
claim is committed BEFORE the transport dispatches physically.  It never
replaces the unit-of-work route and never commits arbitrary caller business
transactions.

Importing this module has NO side effects: no database, directory, worker or
service is created at import time.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple, TypeVar
from urllib.parse import quote

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    DomainEvent,
    ExecutionReservation,
    ExecutionTerminalState,
    ProtocolV3Model,
    ReservationStatus,
    SemanticDocumentRevision,
    SideEffectKind,
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

__all__ = [
    # exceptions
    "SqliteStorageError",
    "SqliteStorageConfigurationError",
    "SqliteSchemaVersionError",
    # version gate
    "MIN_SQLITE_VERSION",
    "assert_sqlite_version",
    "parse_sqlite_version",
    # schema management
    "SCHEMA_VERSION_LATEST",
    # unit of work
    "SqliteUnitOfWork",
    # factory (the AdapterBuilder wired by storage.selected)
    "build_unit_of_work_factory",
    # committed-operation dispatch runtime (Task 1R.4)
    "SqliteCommittedOperationReservationRepository",
    "build_committed_reservation_repository_factory",
    # durable project allowlist (Task 1R.2 mount gate)
    "admit_project",
    "is_project_admitted",
]


# ---------------------------------------------------------------------------
# Exceptions — fail closed
# ---------------------------------------------------------------------------


class SqliteStorageError(RuntimeError):
    """Base class for product SQLite adapter failures."""


class SqliteStorageConfigurationError(SqliteStorageError):
    """Raised when configuration is invalid or the target file is not a
    fresh/compatible product database."""


class SqliteSchemaVersionError(SqliteStorageError):
    """Raised when the target database carries a schema version this adapter
    does not know (a future product version wrote it).  The database is never
    rewritten in that case."""


# ---------------------------------------------------------------------------
# Engine version gate
# ---------------------------------------------------------------------------

#: Minimum linked engine version.  The multi-connection WAL-reset defect is
#: fixed in 3.51.3+; official SQLite documentation notes it may also affect
#: versions earlier than 3.51.0, so the gate requires >= 3.51.3 rather than
#: enumerating affected versions.
MIN_SQLITE_VERSION: Tuple[int, int, int] = (3, 51, 3)


def parse_sqlite_version(version: str) -> Tuple[int, int, int]:
    parts = version.split(".")
    return tuple(int(p) for p in parts[:3])  # type: ignore[return-value]


def assert_sqlite_version(
    *,
    min_version: Tuple[int, int, int] = MIN_SQLITE_VERSION,
) -> Tuple[int, int, int]:
    """Fail closed if the linked SQLite engine is below *min_version*.

    Called at factory build time, before any file or directory is created.
    """
    actual = parse_sqlite_version(sqlite3.sqlite_version)
    if actual < min_version:
        raise SqliteStorageError(
            f"linked SQLite {actual} is below the required minimum {min_version}; "
            "runtimes linking affected versions fail closed (WAL reset defect, "
            "fixed in 3.51.3+). Use the pinned runtime "
            "/opt/homebrew/bin/python3.12."
        )
    return actual


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StoreConfig:
    """Validated adapter configuration (one product database)."""

    path: Path
    busy_timeout_ms: int
    synchronous: str


_DEFAULT_BUSY_TIMEOUT_MS = 5000
_ALLOWED_CONFIG_KEYS = frozenset(
    {"backend", "path", "busy_timeout_ms", "synchronous"}
)


def _validate_config(config: Mapping[str, Any]) -> _StoreConfig:
    """Validate the adapter configuration; fail closed before any I/O."""
    if not isinstance(config, Mapping):
        raise SqliteStorageConfigurationError(
            "sqlite storage config must be a mapping"
        )
    unknown = set(config.keys()) - _ALLOWED_CONFIG_KEYS
    if unknown:
        raise SqliteStorageConfigurationError(
            f"unknown sqlite storage config keys {sorted(unknown)}; "
            f"allowed keys: {sorted(_ALLOWED_CONFIG_KEYS)}"
        )
    backend = config.get("backend")
    if backend != "sqlite":
        raise SqliteStorageConfigurationError(
            f"config must declare backend 'sqlite' (got {backend!r})"
        )
    raw_path = config.get("path")
    if isinstance(raw_path, str):
        raw_path = raw_path.strip()
    if not isinstance(raw_path, (str, Path)) or not raw_path:
        raise SqliteStorageConfigurationError(
            "sqlite storage config requires a non-empty 'path'"
        )
    if str(raw_path) == ":memory:":
        raise SqliteStorageConfigurationError(
            "':memory:' is a volatile in-memory database; the product adapter "
            "requires a real file path so committed state actually persists"
        )
    busy_timeout_ms = config.get("busy_timeout_ms", _DEFAULT_BUSY_TIMEOUT_MS)
    if isinstance(busy_timeout_ms, bool) or not isinstance(busy_timeout_ms, int):
        raise SqliteStorageConfigurationError(
            "busy_timeout_ms must be a positive integer (milliseconds)"
        )
    if busy_timeout_ms <= 0:
        raise SqliteStorageConfigurationError(
            "busy_timeout_ms must be a positive integer (milliseconds)"
        )
    synchronous = config.get("synchronous", "FULL")
    if synchronous != "FULL":
        raise SqliteStorageConfigurationError(
            "synchronous must be 'FULL' (the durability contract); "
            f"got {synchronous!r}"
        )
    return _StoreConfig(
        path=Path(raw_path),
        busy_timeout_ms=busy_timeout_ms,
        synchronous=synchronous,
    )


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------


def _conn_for(config: _StoreConfig) -> sqlite3.Connection:
    """Open an independent connection to the WAL database with FULL durability.

    ``journal_mode=WAL`` is NOT set here: it is a persistent database setting
    established once at bootstrap (executing it per connection would itself be
    a write operation contending for the database lock).
    """
    conn = sqlite3.connect(
        str(config.path),
        isolation_level=None,  # manual transaction control
        check_same_thread=False,
        timeout=config.busy_timeout_ms / 1000.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA synchronous={config.synchronous}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={config.busy_timeout_ms}")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


# ---------------------------------------------------------------------------
# Schema version table and ordered migrations
# ---------------------------------------------------------------------------

_SCHEMA_VERSION_DDL = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version    INTEGER NOT NULL,
        applied_at TEXT NOT NULL
    )
    """,
)

#: Ordered, append-only migration list:
#: ``(version, description, statements, owned_table_fingerprint)``.  Each
#: migration runs inside its own ``BEGIN IMMEDIATE`` transaction together
#: with its ``schema_version`` row insert.  New product schema changes append
#: new entries with strictly increasing versions; applied entries are frozen.
#: The fingerprint records the exact table/column structure each migration
#: owns; adoption preflight verifies it before any mutation.
_MIGRATIONS: Tuple[
    Tuple[int, str, Tuple[str, ...], Dict[str, Tuple[str, ...]]], ...
] = (
    (
        1,
        "base protocol v3 product tables",
        (
            """
            CREATE TABLE IF NOT EXISTS aggregate_revision (
                aggregate_kind   TEXT    NOT NULL,
                project_id       TEXT    NOT NULL,
                aggregate_id     TEXT    NOT NULL,
                revision         INTEGER NOT NULL,
                body_json        TEXT    NOT NULL,
                previous_revision_sha256 TEXT,
                PRIMARY KEY (aggregate_kind, project_id, aggregate_id, revision)
            )
            """,
            """
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
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS outbox_message (
                project_id        TEXT    NOT NULL,
                outbox_message_id TEXT    NOT NULL,
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
                PRIMARY KEY (project_id, outbox_message_id),
                UNIQUE (project_id, logical_key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS inbox_result (
                project_id      TEXT    NOT NULL,
                inbox_result_id TEXT    NOT NULL,
                logical_key     TEXT    NOT NULL,
                result_sha256   TEXT    NOT NULL,
                status          TEXT    NOT NULL,
                received_at     TEXT    NOT NULL,
                consumed_at     TEXT,
                PRIMARY KEY (project_id, inbox_result_id),
                UNIQUE (project_id, logical_key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS execution_reservation (
                project_id                 TEXT    NOT NULL,
                execution_reservation_id   TEXT    NOT NULL,
                node_execution_contract_id TEXT    NOT NULL,
                logical_call_id            TEXT    NOT NULL,
                idempotency_key            TEXT    NOT NULL,
                input_sha256               TEXT    NOT NULL,
                attempt                    INTEGER NOT NULL,
                transport_attempts         INTEGER NOT NULL DEFAULT 0,
                provider_session_id        TEXT,
                status                     TEXT    NOT NULL,
                terminal_state             TEXT,
                output_sha256              TEXT,
                error_code                 TEXT,
                reserved_at                TEXT    NOT NULL,
                updated_at                 TEXT    NOT NULL,
                PRIMARY KEY (project_id, execution_reservation_id),
                UNIQUE (project_id, logical_call_id, idempotency_key),
                UNIQUE (project_id, logical_call_id, attempt)
            )
            """,
            """
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
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS read_decision_graph (
                project_id        TEXT NOT NULL,
                study_definition_id TEXT NOT NULL,
                decision_key      TEXT NOT NULL,
                decision_record_id TEXT,
                state_revision    INTEGER,
                selected_option_id TEXT,
                canonical_state   TEXT,
                PRIMARY KEY (project_id, study_definition_id, decision_key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS read_workflow_run_status (
                project_id       TEXT NOT NULL,
                workflow_run_id  TEXT NOT NULL,
                status           TEXT NOT NULL,
                display_progress REAL NOT NULL,
                journey_counter  INTEGER NOT NULL,
                PRIMARY KEY (project_id, workflow_run_id)
            )
            """,
        ),
        {
            "aggregate_revision": (
                "aggregate_kind", "project_id", "aggregate_id", "revision",
                "body_json", "previous_revision_sha256",
            ),
            "event_stream": (
                "project_id", "stream_id", "sequence", "domain_event_id",
                "body_json", "previous_event_sha256", "event_sha256",
            ),
            "outbox_message": (
                "project_id", "outbox_message_id", "workflow_run_id",
                "side_effect_kind", "logical_key", "payload_sha256", "status",
                "created_at", "dispatched_at", "completed_at", "attempt",
                "error_detail",
            ),
            "inbox_result": (
                "project_id", "inbox_result_id", "logical_key", "result_sha256",
                "status", "received_at", "consumed_at",
            ),
            "execution_reservation": (
                "project_id", "execution_reservation_id",
                "node_execution_contract_id", "logical_call_id",
                "idempotency_key", "input_sha256", "attempt",
                "transport_attempts", "provider_session_id", "status",
                "terminal_state", "output_sha256", "error_code", "reserved_at",
                "updated_at",
            ),
            "read_chapter_coverage": (
                "project_id", "semantic_document_revision_id",
                "semantic_node_id", "chapter_contract_sha256",
                "substantive_content_contract_sha256", "semantic_block_sha256",
                "is_locked", "has_substantive_content", "evidence_admitted",
            ),
            "read_decision_graph": (
                "project_id", "study_definition_id", "decision_key",
                "decision_record_id", "state_revision", "selected_option_id",
                "canonical_state",
            ),
            "read_workflow_run_status": (
                "project_id", "workflow_run_id", "status", "display_progress",
                "journey_counter",
            ),
        },
    ),
    (
        2,
        "durable protocol-workflow project allowlist (Task 1R.2)",
        (
            """
            CREATE TABLE IF NOT EXISTS protocol_workflow_project_allowlist (
                project_id   TEXT NOT NULL PRIMARY KEY,
                admitted_at  TEXT NOT NULL
            )
            """,
        ),
        {
            "protocol_workflow_project_allowlist": (
                "project_id", "admitted_at",
            ),
        },
    ),
    (
        3,
        "consolidated paired-result storage on outbox with inbox compatibility"
        " (Task 1R.4)",
        (
            "ALTER TABLE outbox_message ADD COLUMN result_sha256 TEXT",
            "ALTER TABLE outbox_message ADD COLUMN result_received_at TEXT",
            "ALTER TABLE outbox_message ADD COLUMN result_consumed_at TEXT",
        ),
        {
            "outbox_message": (
                "project_id", "outbox_message_id", "workflow_run_id",
                "side_effect_kind", "logical_key", "payload_sha256", "status",
                "created_at", "dispatched_at", "completed_at", "attempt",
                "error_detail",
                "result_sha256", "result_received_at", "result_consumed_at",
            ),
        },
    ),
)

SCHEMA_VERSION_LATEST: int = _MIGRATIONS[-1][0]

#: Columns of the bootstrap-owned ``schema_version`` table (created outside
#: the migration list on fresh databases).
_OWNED_SCHEMA_VERSION_COLUMNS: Tuple[str, ...] = ("version", "applied_at")


def _read_schema_version(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _user_table_names(conn: sqlite3.Connection) -> set:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r[0] for r in rows}


def _column_signature(conn: sqlite3.Connection, table: str) -> tuple:
    """Ordered per-column constraint semantics from ``PRAGMA table_info``:
    ``(name, declared type, notnull, default, primary-key ordinal)``."""
    return tuple(
        (
            row[1],
            (row[2] or "").strip().upper(),
            row[3],
            row[4],
            row[5],
        )
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    )


def _unique_index_signature(conn: sqlite3.Connection, table: str) -> tuple:
    """Sorted unique-index structure ``(origin, ordered columns)`` — the
    SQLite-native record of PRIMARY KEY and UNIQUE constraint semantics."""
    signature = []
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        index_name, is_unique, origin = row[1], row[2], row[3]
        if not is_unique:
            continue
        columns = tuple(
            info_row[2]
            for info_row in conn.execute(f"PRAGMA index_info({index_name})").fetchall()
        )
        signature.append((origin, columns))
    return tuple(sorted(signature))


def _reference_schema_fingerprint(version: int) -> Dict[str, Tuple[Tuple, Tuple]]:
    """Introspect the DDL applied at the database's version, not the latest.

    This small reference is built only during factory bootstrap. Keeping it
    uncached avoids stale signatures across schema changes. It is not a
    memory-backed product store.
    """
    reference = sqlite3.connect(":memory:")
    try:
        for statement in _SCHEMA_VERSION_DDL:
            reference.execute(statement)
        for mig_version, _description, statements, _fingerprint in _MIGRATIONS:
            if mig_version <= version:
                for statement in statements:
                    reference.execute(statement)
        return {
            table: (_column_signature(reference, table), _unique_index_signature(reference, table))
            for table in _user_table_names(reference)
        }
    finally:
        reference.close()


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="microseconds")


def _safe_rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.OperationalError:
        pass


def _apply_migration(
    conn: sqlite3.Connection,
    *,
    expected_current: Optional[int],
    version: int,
    statements: Sequence[str],
) -> None:
    """Apply one migration atomically with its version-row insert.

    The current version is re-read inside the transaction so concurrent
    initialization cannot double-apply or skip a step.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = _read_schema_version(conn)
        if current != expected_current:
            raise SqliteSchemaVersionError(
                f"schema version changed concurrently during migration to "
                f"{version}: expected {expected_current!r}, found {current!r}"
            )
        for statement in statements:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, _now_iso()),
        )
        conn.execute("COMMIT")
    except BaseException:
        _safe_rollback(conn)
        raise


def _bootstrap_fresh(conn: sqlite3.Connection) -> None:
    """Create the version table and apply all migrations in ONE transaction.

    A process death mid-bootstrap therefore leaves either an empty database
    (retried safely) or the fully initialised schema — never a half-created
    version table without its migrations.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in _SCHEMA_VERSION_DDL:
            conn.execute(statement)
        for version, _description, statements, _fingerprint in _MIGRATIONS:
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, _now_iso()),
            )
        conn.execute("COMMIT")
    except BaseException:
        _safe_rollback(conn)
        raise


def _open_readonly(path: Path) -> sqlite3.Connection:
    """Open an existing database READ-ONLY for adoption preflight.

    Verification of an unknown database must never write to it: even a
    read-write probe close can checkpoint/rewrite a foreign WAL database
    during rejection.  Read-only mode guarantees a byte-untouched rejection.
    (SQLite's read-only open of a WAL database may leave EMPTY runtime
    ``-wal``/``-shm`` sidecars; the main database file itself is never
    modified and no checkpoint content is written.)
    """
    uri = "file:" + quote(str(path)) + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _validate_migration_history(rows: Sequence[object]) -> int:
    """Validate the applied migration history exactly; return its latest
    version.

    The history must be exactly 1..N, each version present once, in
    application order, with no zero/negative, duplicate, gapped or non-integer
    entries.  ``MAX(version)`` alone cannot distinguish an owned database
    from a foreign table that merely carries a plausible version row.
    """
    if not rows:
        raise SqliteStorageConfigurationError(
            "schema_version table has no applied version rows; refusing to "
            "touch a database with empty migration history"
        )
    versions = []
    for value in rows:
        if isinstance(value, bool) or not isinstance(value, int):
            raise SqliteStorageConfigurationError(
                f"schema_version carries a non-integer version row {value!r}"
            )
        versions.append(value)
    latest = max(versions)
    if latest > SCHEMA_VERSION_LATEST:
        raise SqliteSchemaVersionError(
            f"database was written by a newer product version (schema "
            f"{latest} > known {SCHEMA_VERSION_LATEST}); failing closed "
            "without rewriting its contents"
        )
    if sorted(versions) != list(range(1, latest + 1)):
        raise SqliteStorageConfigurationError(
            f"malformed migration history {versions!r}: versions must be "
            f"exactly 1..{SCHEMA_VERSION_LATEST} with no zero, duplicate, "
            "gapped or unknown entries"
        )
    return latest


def _preflight_owned_database(config: _StoreConfig) -> int:
    """Verify on a READ-ONLY connection that the existing database is a
    product-owned database with a complete, known migration history and the
    exact owned schema; return the current schema version (0 = fresh/empty).

    Any foreign, malformed, structurally incompatible or future database is
    rejected here WITHOUT ever opening a read-write connection, so rejection
    cannot mutate or checkpoint the file.
    """
    path = config.path
    try:
        ro = _open_readonly(path)
    except sqlite3.OperationalError as exc:
        raise SqliteStorageConfigurationError(
            f"existing database {str(path)!r} cannot be opened read-only for "
            "verification; refusing to touch it"
        ) from exc
    try:
        try:
            tables = _user_table_names(ro)
        except sqlite3.DatabaseError as exc:
            raise SqliteStorageConfigurationError(
                f"target file {str(path)!r} is not a usable SQLite database; "
                "it was left untouched"
            ) from exc
        if not tables:
            return 0  # empty file: fresh bootstrap
        if "schema_version" not in tables:
            raise SqliteStorageConfigurationError(
                f"target database {str(path)!r} exists but does not carry the "
                "product schema (no schema_version table); refusing to adopt "
                "or rename a foreign/legacy database"
            )
        try:
            rows = [
                r[0]
                for r in ro.execute(
                    "SELECT version FROM schema_version ORDER BY rowid"
                ).fetchall()
            ]
        except sqlite3.DatabaseError as exc:
            raise SqliteStorageConfigurationError(
                f"schema_version table in {str(path)!r} is unreadable or "
                "incompatible; refusing to touch the database"
            ) from exc
        version = _validate_migration_history(rows)
        expected_tables: Dict[str, Tuple[str, ...]] = {
            "schema_version": _OWNED_SCHEMA_VERSION_COLUMNS
        }
        applied = set(rows)
        for mig_version, _description, _statements, fingerprint in _MIGRATIONS:
            if mig_version in applied:
                expected_tables.update(fingerprint)
        if tables != set(expected_tables):
            missing = sorted(set(expected_tables) - tables)
            extra = sorted(tables - set(expected_tables))
            raise SqliteStorageConfigurationError(
                f"database {str(path)!r} is not a compatible product schema: "
                f"missing owned tables {missing}, unrelated/unknown tables "
                f"{extra}; refusing to adopt or rewrite it"
            )
        for table, columns in expected_tables.items():
            info = ro.execute(f"PRAGMA table_info({table})").fetchall()
            actual_columns = {r[1] for r in info}
            if actual_columns != set(columns):
                raise SqliteStorageConfigurationError(
                    f"owned table {table!r} in {str(path)!r} has an "
                    f"incompatible structure {sorted(actual_columns)!r}; "
                    "refusing to touch the database"
                )
        # Names alone are not the owned schema: a same-name/same-column
        # rewrite (e.g. CREATE TABLE ... AS SELECT) silently loses PRIMARY
        # KEY, UNIQUE and NOT NULL semantics.  Compare the full constraint
        # structure against a fingerprint derived from the migration DDL.
        reference = _reference_schema_fingerprint(version)
        for table in sorted(reference):
            expected_column_signature, expected_unique_signature = reference[table]
            if _column_signature(ro, table) != expected_column_signature:
                raise SqliteStorageConfigurationError(
                    f"owned table {table!r} in {str(path)!r} does not carry "
                    "the product column semantics (declared type, NOT NULL, "
                    "DEFAULT or PRIMARY KEY ordinal differ); refusing to "
                    "touch the database"
                )
            if _unique_index_signature(ro, table) != expected_unique_signature:
                raise SqliteStorageConfigurationError(
                    f"owned table {table!r} in {str(path)!r} does not carry "
                    "the product PRIMARY KEY/UNIQUE index structure; "
                    "refusing to touch the database"
                )
        return version
    finally:
        ro.close()


def _bootstrap(config: _StoreConfig) -> None:
    """Assert the engine gate, then verify/create the product schema.

    Fail-closed rules:

    * the engine gate fires BEFORE any file or directory is created;
    * an existing non-empty database is verified READ-ONLY first: foreign,
      malformed, structurally incompatible and future databases are rejected
      without any read-write connection, so rejection never rewrites or
      checkpoints the file;
    * volatile in-memory paths are rejected at configuration time;
    * only a fresh file or a verified-owned database proceeds to the
      read-write phase (atomic create, or ordered pending migrations).
    """
    assert_sqlite_version()
    path = config.path
    if path.is_dir():
        raise SqliteStorageConfigurationError(
            f"configured storage path {str(path)!r} is a directory"
        )
    existing = path.exists() and path.stat().st_size > 0
    if existing:
        if _preflight_owned_database(config) == 0:
            existing = False  # empty file: fresh bootstrap
    # Read-write phase — only fresh or verified-owned databases reach here.
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _conn_for(config)
    try:
        if existing:
            version = _read_schema_version(conn)
            if version is None:
                raise SqliteStorageConfigurationError(
                    f"target database {str(path)!r} lost its migration "
                    "history between verification and write phase; refusing "
                    "to touch it"
                )
            for mig_version, _description, statements, _fingerprint in _MIGRATIONS:
                if mig_version <= version:
                    continue
                _apply_migration(
                    conn, expected_current=version, version=mig_version,
                    statements=statements,
                )
                version = mig_version
        else:
            _bootstrap_fresh(conn)
        # Persistent durability setting, established once per bootstrap.
        conn.execute("PRAGMA journal_mode=WAL")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _dt_to_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(
            f"naive datetime {value!r} rejected: protocol v3 storage requires "
            "timezone-aware timestamps; a naive value would be silently "
            "reinterpreted in the local timezone"
        )
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _dt_from_iso(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _model_to_json(model: ProtocolV3Model) -> str:
    return json.dumps(
        model.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )


def _json_to_model(json_str: str, model_cls: type) -> ProtocolV3Model:
    return model_cls.model_validate_json(json_str)


def _undo_savepoint(conn: sqlite3.Connection, name: str) -> None:
    """Roll back and release a savepoint, preserving the original failure.

    Used by compound writes (event batch, projection replacement) so a SQL
    failure mid-operation cannot leave partially written rows inside the
    caller's larger transaction.
    """
    try:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
    except sqlite3.Error:
        pass


# ---------------------------------------------------------------------------
# Repository implementations (each bound to ONE connection)
# ---------------------------------------------------------------------------


class _Guard:
    """Per-UoW lifecycle guard shared by all repository handles.

    ``ensure_open`` gates reads and diagnostics (which may run before the
    first ``__enter__``).  ``ensure_active`` additionally requires an open
    transaction scope for every mutator, so a write can never silently
    autocommit outside ``with unit_of_work:`` and then survive a rollback.
    """

    __slots__ = ("closed", "_depth_provider")

    def __init__(self) -> None:
        self.closed = False
        self._depth_provider: Optional[Callable[[], int]] = None

    def bind_depth(self, depth_provider: Callable[[], int]) -> None:
        self._depth_provider = depth_provider

    def ensure_open(self) -> None:
        if self.closed:
            raise UnitOfWorkClosedError("unit of work is closed")

    def ensure_active(self) -> None:
        self.ensure_open()
        depth = self._depth_provider() if self._depth_provider is not None else 0
        if depth <= 0:
            raise UnitOfWorkClosedError(
                "unit of work is not inside an active transaction; mutators "
                "require `with unit_of_work:` so writes commit or roll back "
                "as one atomic unit"
            )


class _SqliteCurrentAggregateRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        aggregate_kind: str,
        identity_field: str,
        model_cls: type,
        guard: _Guard,
    ) -> None:
        self._conn = conn
        self._kind = aggregate_kind
        self._identity_field = identity_field
        self._model_cls = model_cls
        self._guard = guard

    def get_current(self, project_id: str, aggregate_id: str):
        self._guard.ensure_open()
        row = self._conn.execute(
            "SELECT body_json FROM aggregate_revision "
            "WHERE aggregate_kind=? AND project_id=? AND aggregate_id=? "
            "ORDER BY revision DESC LIMIT 1",
            (self._kind, project_id, aggregate_id),
        ).fetchone()
        return (
            _json_to_model(row["body_json"], self._model_cls) if row else None
        )

    def get_current_required(self, project_id: str, aggregate_id: str):
        record = self.get_current(project_id, aggregate_id)
        if record is None:
            raise AggregateNotFoundError(project_id, aggregate_id=aggregate_id)
        return record

    def get_at_revision(
        self, project_id: str, aggregate_id: str, revision: int
    ):
        self._guard.ensure_open()
        row = self._conn.execute(
            "SELECT body_json FROM aggregate_revision "
            "WHERE aggregate_kind=? AND project_id=? AND aggregate_id=? AND revision=?",
            (self._kind, project_id, aggregate_id, revision),
        ).fetchone()
        return (
            _json_to_model(row["body_json"], self._model_cls) if row else None
        )

    def get_current_revision(
        self, project_id: str, aggregate_id: str
    ) -> Optional[int]:
        self._guard.ensure_open()
        row = self._conn.execute(
            "SELECT MAX(revision) AS r FROM aggregate_revision "
            "WHERE aggregate_kind=? AND project_id=? AND aggregate_id=?",
            (self._kind, project_id, aggregate_id),
        ).fetchone()
        if row is None or row["r"] is None:
            return None
        return row["r"]


class _SqliteCasRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        aggregate_kind: str,
        identity_field: str,
        model_cls: type,
        guard: _Guard,
    ) -> None:
        self._conn = conn
        self._kind = aggregate_kind
        self._identity_field = identity_field
        self._model_cls = model_cls
        self._guard = guard

    def save_with_expected_revision(
        self, project_id: str, record, expected_revision: int
    ):
        self._guard.ensure_active()
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
                raise RevisionConflictError(
                    project_id, aggregate_id, expected_revision, actual
                )
            if new_revision != 1:
                raise RevisionConflictError(
                    project_id, aggregate_id, expected_revision, actual
                )
        else:
            if actual is None or actual != expected_revision:
                raise RevisionConflictError(
                    project_id, aggregate_id, expected_revision, actual
                )
            if new_revision != expected_revision + 1:
                raise RevisionConflictError(
                    project_id, aggregate_id, expected_revision, actual
                )
        self._conn.execute(
            "INSERT INTO aggregate_revision "
            "(aggregate_kind, project_id, aggregate_id, revision, body_json, "
            " previous_revision_sha256) VALUES (?, ?, ?, ?, ?, ?)",
            (
                self._kind,
                project_id,
                aggregate_id,
                new_revision,
                _model_to_json(record),
                getattr(record, "previous_revision_sha256", None),
            ),
        )
        return record


class _SqliteEventStreamRepository:
    def __init__(self, conn: sqlite3.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def append_events(
        self, project_id: str, stream_id: str, events: Sequence[DomainEvent]
    ) -> Tuple[DomainEvent, ...]:
        self._guard.ensure_active()
        if not events:
            return ()
        head_row = self._conn.execute(
            "SELECT sequence, event_sha256 FROM event_stream "
            "WHERE project_id=? AND stream_id=? ORDER BY sequence DESC LIMIT 1",
            (project_id, stream_id),
        ).fetchone()
        last_seq = head_row["sequence"] if head_row else 0
        last_sha: Optional[str] = head_row["event_sha256"] if head_row else None
        seen_ids = {
            r["domain_event_id"]
            for r in self._conn.execute(
                "SELECT domain_event_id FROM event_stream "
                "WHERE project_id=? AND stream_id=?",
                (project_id, stream_id),
            )
        }
        seen_seqs = {
            r["sequence"]
            for r in self._conn.execute(
                "SELECT sequence FROM event_stream "
                "WHERE project_id=? AND stream_id=?",
                (project_id, stream_id),
            )
        }
        # Validate the WHOLE batch before writing any row, so a repository
        # failure can never leak a partially written batch inside a larger
        # transaction whose caller catches the exception.
        pending = []
        for evt in events:
            if evt.stream_id != stream_id:
                raise EventSequenceConflictError(
                    project_id,
                    stream_id,
                    expected_sequence=last_seq + 1 + len(pending),
                    actual_sequence=evt.sequence,
                    detail=(
                        f"event stream_id={evt.stream_id!r} does not match "
                        f"append target {stream_id!r}"
                    ),
                )
            if evt.domain_event_id in seen_ids:
                raise EventSequenceConflictError(
                    project_id,
                    stream_id,
                    expected_sequence=None,
                    actual_sequence=None,
                    detail=f"duplicate domain_event_id={evt.domain_event_id}",
                )
            if evt.sequence in seen_seqs:
                raise EventSequenceConflictError(
                    project_id,
                    stream_id,
                    expected_sequence=evt.sequence,
                    actual_sequence=evt.sequence,
                    detail=f"duplicate sequence={evt.sequence}",
                )
            expected_prev = (
                None
                if (last_seq == 0 and not pending)
                else (pending[-1].event_sha256 if pending else last_sha)
            )
            if evt.previous_event_sha256 != expected_prev:
                raise EventSequenceConflictError(
                    project_id,
                    stream_id,
                    expected_sequence=last_seq + 1,
                    actual_sequence=evt.sequence,
                    detail="previous_event_sha256 chain mismatch",
                )
            if evt.sequence != last_seq + 1 + len(pending):
                raise EventSequenceConflictError(
                    project_id,
                    stream_id,
                    expected_sequence=last_seq + 1 + len(pending),
                    actual_sequence=evt.sequence,
                    detail="sequence gap",
                )
            seen_ids.add(evt.domain_event_id)
            seen_seqs.add(evt.sequence)
            pending.append(evt)
        # The batch was validated in full, but a row-level SQL failure (e.g.
        # a trigger or constraint violation on a later row) can still abort
        # mid-insert.  The savepoint is the smallest SQLite atomic boundary:
        # on failure the WHOLE batch is rolled back while the caller's larger
        # transaction — including unrelated successful work — stays intact.
        self._conn.execute("SAVEPOINT protocol_v3_event_batch")
        try:
            for evt in pending:
                self._conn.execute(
                    "INSERT INTO event_stream "
                    "(project_id, stream_id, sequence, domain_event_id, body_json, "
                    " previous_event_sha256, event_sha256) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        project_id,
                        stream_id,
                        evt.sequence,
                        evt.domain_event_id,
                        _model_to_json(evt),
                        evt.previous_event_sha256,
                        evt.event_sha256,
                    ),
                )
        except BaseException:
            _undo_savepoint(self._conn, "protocol_v3_event_batch")
            raise
        self._conn.execute("RELEASE SAVEPOINT protocol_v3_event_batch")
        return tuple(pending)

    def read_events(
        self, project_id: str, stream_id: str, *, from_sequence: int = 1
    ) -> Tuple[DomainEvent, ...]:
        self._guard.ensure_open()
        rows = self._conn.execute(
            "SELECT body_json FROM event_stream "
            "WHERE project_id=? AND stream_id=? AND sequence >= ? "
            "ORDER BY sequence",
            (project_id, stream_id, from_sequence),
        ).fetchall()
        return tuple(
            _json_to_model(r["body_json"], DomainEvent) for r in rows
        )

    def get_stream_head(
        self, project_id: str, stream_id: str
    ) -> Optional[StreamHead]:
        self._guard.ensure_open()
        row = self._conn.execute(
            "SELECT sequence, event_sha256, "
            "(SELECT COUNT(*) FROM event_stream "
            " WHERE project_id=? AND stream_id=?) AS cnt "
            "FROM event_stream WHERE project_id=? AND stream_id=? "
            "ORDER BY sequence DESC LIMIT 1",
            (project_id, stream_id, project_id, stream_id),
        ).fetchone()
        if row is None:
            return None
        return StreamHead(
            stream_id=stream_id,
            last_sequence=row["sequence"],
            last_event_sha256=row["event_sha256"],
            event_count=row["cnt"],
        )


class _SqliteOutboxRepository:
    def __init__(self, conn: sqlite3.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def _row_to_msg(self, row: sqlite3.Row) -> OutboxMessage:
        return OutboxMessage(
            outbox_message_id=row["outbox_message_id"],
            project_id=row["project_id"],
            workflow_run_id=row["workflow_run_id"],
            side_effect_kind=SideEffectKind(row["side_effect_kind"]),
            logical_key=row["logical_key"],
            payload_sha256=row["payload_sha256"],
            status=OutboxStatus(row["status"]),
            created_at=_dt_from_iso(row["created_at"]),  # type: ignore[arg-type]
            dispatched_at=_dt_from_iso(row["dispatched_at"]),
            completed_at=_dt_from_iso(row["completed_at"]),
            attempt=row["attempt"],
            error_detail=row["error_detail"],
        )

    def enqueue(
        self,
        project_id: str,
        workflow_run_id: str,
        side_effect_kind: SideEffectKind,
        logical_key: str,
        payload_sha256: str,
        created_at: datetime,
    ) -> OutboxMessage:
        self._guard.ensure_active()
        row = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=? AND logical_key=?",
            (project_id, logical_key),
        ).fetchone()
        if row is not None:
            if row["payload_sha256"] == payload_sha256:
                return self._row_to_msg(row)
            raise IdempotencyConflictError(
                project_id, logical_key, row["payload_sha256"], payload_sha256
            )
        nxt = int(
            self._conn.execute(
                "SELECT COALESCE(MAX(rowid), 0) + 1 FROM outbox_message"
            ).fetchone()[0]
        )
        message_id = f"ob-{nxt}-{logical_key}"
        kind_value = (
            side_effect_kind.value
            if isinstance(side_effect_kind, SideEffectKind)
            else str(side_effect_kind)
        )
        self._conn.execute(
            "INSERT INTO outbox_message "
            "(outbox_message_id, project_id, workflow_run_id, side_effect_kind, "
            " logical_key, payload_sha256, status, created_at, attempt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                message_id,
                project_id,
                workflow_run_id,
                kind_value,
                logical_key,
                payload_sha256,
                OutboxStatus.PENDING.value,
                _dt_to_iso(created_at),
            ),
        )
        return self._row_to_msg(
            self._conn.execute(
                "SELECT * FROM outbox_message WHERE project_id=? AND outbox_message_id=?",
                (project_id, message_id),
            ).fetchone()
        )

    def claim_pending(
        self, project_id: str, *, limit: int, claimed_at: datetime
    ) -> Tuple[OutboxMessage, ...]:
        self._guard.ensure_active()
        rows = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=? AND status=? "
            "ORDER BY created_at, outbox_message_id LIMIT ?",
            (project_id, OutboxStatus.PENDING.value, limit),
        ).fetchall()
        claimed = []
        self._conn.execute("SAVEPOINT protocol_v3_outbox_claim")
        try:
            for row in rows:
                self._conn.execute(
                    "UPDATE outbox_message SET status=?, dispatched_at=?, "
                    "attempt=attempt+1 WHERE project_id=? AND outbox_message_id=?",
                    (
                        OutboxStatus.DISPATCHED.value,
                        _dt_to_iso(claimed_at),
                        project_id,
                        row["outbox_message_id"],
                    ),
                )
                claimed.append(
                    self._row_to_msg(
                        self._conn.execute(
                            "SELECT * FROM outbox_message WHERE project_id=? "
                            "AND outbox_message_id=?",
                            (project_id, row["outbox_message_id"]),
                        ).fetchone()
                    )
                )
        except BaseException:
            _undo_savepoint(self._conn, "protocol_v3_outbox_claim")
            raise
        self._conn.execute("RELEASE SAVEPOINT protocol_v3_outbox_claim")
        return tuple(claimed)

    def mark_completed(
        self, project_id: str, outbox_message_id: str, completed_at: datetime
    ) -> OutboxMessage:
        self._guard.ensure_active()
        row = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=? AND outbox_message_id=?",
            (project_id, outbox_message_id),
        ).fetchone()
        if row is None:
            raise AggregateNotFoundError(project_id, aggregate_id=outbox_message_id)
        if row["status"] != OutboxStatus.DISPATCHED.value:
            raise RepositoryStateTransitionError(
                project_id,
                outbox_message_id,
                from_status=row["status"],
                to_status=OutboxStatus.COMPLETED.value,
            )
        self._conn.execute(
            "UPDATE outbox_message SET status=?, completed_at=? "
            "WHERE project_id=? AND outbox_message_id=?",
            (
                OutboxStatus.COMPLETED.value,
                _dt_to_iso(completed_at),
                project_id,
                outbox_message_id,
            ),
        )
        return self._row_to_msg(
            self._conn.execute(
                "SELECT * FROM outbox_message WHERE project_id=? AND outbox_message_id=?",
                (project_id, outbox_message_id),
            ).fetchone()
        )

    def mark_failed(
        self,
        project_id: str,
        outbox_message_id: str,
        error_detail: str,
        failed_at: datetime,
    ) -> OutboxMessage:
        self._guard.ensure_active()
        row = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=? AND outbox_message_id=?",
            (project_id, outbox_message_id),
        ).fetchone()
        if row is None:
            raise AggregateNotFoundError(project_id, aggregate_id=outbox_message_id)
        if row["status"] != OutboxStatus.DISPATCHED.value:
            raise RepositoryStateTransitionError(
                project_id,
                outbox_message_id,
                from_status=row["status"],
                to_status=OutboxStatus.FAILED.value,
            )
        self._conn.execute(
            "UPDATE outbox_message SET status=?, completed_at=?, error_detail=? "
            "WHERE project_id=? AND outbox_message_id=?",
            (
                OutboxStatus.FAILED.value,
                _dt_to_iso(failed_at),
                error_detail,
                project_id,
                outbox_message_id,
            ),
        )
        return self._row_to_msg(
            self._conn.execute(
                "SELECT * FROM outbox_message WHERE project_id=? AND outbox_message_id=?",
                (project_id, outbox_message_id),
            ).fetchone()
        )

    def get(self, project_id: str, outbox_message_id: str) -> Optional[OutboxMessage]:
        self._guard.ensure_open()
        row = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=? AND outbox_message_id=?",
            (project_id, outbox_message_id),
        ).fetchone()
        return self._row_to_msg(row) if row else None

    def find_by_logical_key(
        self, project_id: str, logical_key: str
    ) -> Optional[OutboxMessage]:
        self._guard.ensure_open()
        row = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=? AND logical_key=?",
            (project_id, logical_key),
        ).fetchone()
        return self._row_to_msg(row) if row else None

    def list_dispatched(
        self, project_id: str, *, limit: int
    ) -> Tuple[OutboxMessage, ...]:
        self._guard.ensure_open()
        rows = self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=? AND status=? "
            "ORDER BY created_at, outbox_message_id LIMIT ?",
            (project_id, OutboxStatus.DISPATCHED.value, limit),
        ).fetchall()
        return tuple(self._row_to_msg(r) for r in rows)


class _SqliteInboxRepository:
    """Idempotent inbox over the consolidated result store (Task 1R.4).

    Authority rule: when an ``outbox_message`` row exists for
    ``(project_id, logical_key)`` *and* the database carries migration 3,
    that outbox row is the single authoritative result store.  Receipts and
    consumption update only its additive result columns
    (``result_sha256``, ``result_received_at``, ``result_consumed_at``) and
    never insert a competing ``inbox_result`` row.  Historical
    ``inbox_result`` rows stay byte-identical as evidence; reads prefer the
    consolidated outbox state once present, and the first post-migration
    write adopts history verbatim (same id/sha/timestamps) instead of
    rewriting it.  Keys with no outbox row keep the legacy ``inbox_result``
    representation, so standalone results never invent a dispatch request.

    Receipt (``RECEIVED``) and business consumption (``CONSUMED``) remain
    distinct columns; neither is synthesised from the outbox dispatch
    ``status`` (``COMPLETED`` only acknowledges dispatch).
    """

    def __init__(self, conn: sqlite3.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard
        self._paired_columns: Optional[bool] = None

    def _row_to_result(self, row: sqlite3.Row) -> InboxResult:
        return InboxResult(
            inbox_result_id=row["inbox_result_id"],
            project_id=row["project_id"],
            logical_key=row["logical_key"],
            result_sha256=row["result_sha256"],
            status=InboxStatus(row["status"]),
            received_at=_dt_from_iso(row["received_at"]),  # type: ignore[arg-type]
            consumed_at=_dt_from_iso(row["consumed_at"]),
        )

    def _has_paired_columns(self) -> bool:
        """Whether this database carries the migration-3 result columns.

        Pre-migration databases (e.g. synthetic older-schema fixtures) fall
        back to the pure legacy ``inbox_result`` path instead of failing on
        a missing column.
        """
        if self._paired_columns is None:
            cols = {
                r[1]
                for r in self._conn.execute(
                    "PRAGMA table_info(outbox_message)"
                ).fetchall()
            }
            self._paired_columns = {
                "result_sha256",
                "result_received_at",
                "result_consumed_at",
            } <= cols
        return self._paired_columns

    def _paired_row(
        self, project_id: str, logical_key: str
    ) -> Optional[sqlite3.Row]:
        """Return the outbox row pairing this key, or ``None``.

        ``None`` means the key is standalone (legacy authority) or the
        database predates migration 3 — never an instruction to invent an
        outbox dispatch row.
        """
        if not self._has_paired_columns():
            return None
        return self._conn.execute(
            "SELECT * FROM outbox_message WHERE project_id=? AND logical_key=?",
            (project_id, logical_key),
        ).fetchone()

    def _legacy_row(
        self, project_id: str, logical_key: str
    ) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM inbox_result WHERE project_id=? AND logical_key=?",
            (project_id, logical_key),
        ).fetchone()

    def _derived_result(
        self, paired: sqlite3.Row, legacy: Optional[sqlite3.Row]
    ) -> InboxResult:
        """Project consolidated outbox columns through the inbox port.

        A preserved historical row keeps its ``inbox_result_id`` so
        pre/post-migration results stay checkable; fresh paired receipts use
        the ``ib-outbox-`` namespace, which never consumes the legacy
        ``inbox_result`` rowid sequence and cannot collide with history.
        """
        result_id = (
            legacy["inbox_result_id"]
            if legacy is not None
            else f"ib-outbox-{paired['outbox_message_id']}"
        )
        consumed_at = _dt_from_iso(paired["result_consumed_at"])
        return InboxResult(
            inbox_result_id=result_id,
            project_id=paired["project_id"],
            logical_key=paired["logical_key"],
            result_sha256=paired["result_sha256"],
            status=(
                InboxStatus.CONSUMED
                if consumed_at is not None
                else InboxStatus.RECEIVED
            ),
            received_at=_dt_from_iso(paired["result_received_at"]),  # type: ignore[arg-type]
            consumed_at=consumed_at,
        )

    def record_result(
        self,
        project_id: str,
        logical_key: str,
        result_sha256: str,
        received_at: datetime,
    ) -> InboxResult:
        self._guard.ensure_active()
        paired = self._paired_row(project_id, logical_key)
        legacy = self._legacy_row(project_id, logical_key)
        existing_sha: Optional[str] = None
        if paired is not None and paired["result_sha256"] is not None:
            existing_sha = paired["result_sha256"]
        elif legacy is not None:
            existing_sha = legacy["result_sha256"]
        if existing_sha is not None:
            if existing_sha != result_sha256:
                raise IdempotencyConflictError(
                    project_id, logical_key, existing_sha, result_sha256
                )
            # A terminal historical result must never be adopted as RECEIVED.
            if legacy is not None and legacy["status"] == InboxStatus.SUPERSEDED.value:
                return self._row_to_result(legacy)
            if paired is not None and paired["result_sha256"] is None:
                # Idempotent replay against pre-consolidation history: adopt
                # the evidence row verbatim so live state matches it exactly.
                assert legacy is not None
                self._conn.execute(
                    "UPDATE outbox_message SET result_sha256=?, "
                    "result_received_at=?, result_consumed_at=? "
                    "WHERE project_id=? AND outbox_message_id=?",
                    (
                        legacy["result_sha256"],
                        legacy["received_at"],
                        legacy["consumed_at"]
                        if legacy["status"] == InboxStatus.CONSUMED.value
                        else None,
                        project_id,
                        paired["outbox_message_id"],
                    ),
                )
                paired = self._paired_row(project_id, logical_key)
                assert paired is not None and paired["result_sha256"] is not None
            if paired is not None and paired["result_sha256"] is not None:
                return self._derived_result(paired, legacy)
            assert legacy is not None
            return self._row_to_result(legacy)
        if paired is not None:
            # Fresh paired receipt: single-authority write to the outbox row
            # only — no competing ``inbox_result`` row is inserted.
            self._conn.execute(
                "UPDATE outbox_message SET result_sha256=?, result_received_at=? "
                "WHERE project_id=? AND outbox_message_id=?",
                (
                    result_sha256,
                    _dt_to_iso(received_at),
                    project_id,
                    paired["outbox_message_id"],
                ),
            )
            stored = self._paired_row(project_id, logical_key)
            assert stored is not None and stored["result_sha256"] is not None
            return self._derived_result(stored, legacy)
        nxt = int(
            self._conn.execute(
                "SELECT COALESCE(MAX(rowid), 0) + 1 FROM inbox_result"
            ).fetchone()[0]
        )
        result_id = f"ib-{nxt}-{logical_key}"
        self._conn.execute(
            "INSERT INTO inbox_result "
            "(inbox_result_id, project_id, logical_key, result_sha256, status, "
            " received_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                result_id,
                project_id,
                logical_key,
                result_sha256,
                InboxStatus.RECEIVED.value,
                _dt_to_iso(received_at),
            ),
        )
        return self._row_to_result(
            self._conn.execute(
                "SELECT * FROM inbox_result WHERE project_id=? AND inbox_result_id=?",
                (project_id, result_id),
            ).fetchone()
        )

    def get_result(
        self, project_id: str, logical_key: str
    ) -> Optional[InboxResult]:
        self._guard.ensure_open()
        paired = self._paired_row(project_id, logical_key)
        legacy = self._legacy_row(project_id, logical_key)
        if paired is not None and paired["result_sha256"] is not None:
            return self._derived_result(paired, legacy)
        if legacy is not None:
            return self._row_to_result(legacy)
        return None

    def was_processed(self, project_id: str, logical_key: str) -> bool:
        self._guard.ensure_open()
        paired = self._paired_row(project_id, logical_key)
        if paired is not None and paired["result_sha256"] is not None:
            return True
        return self._legacy_row(project_id, logical_key) is not None

    def mark_consumed(
        self, project_id: str, logical_key: str, consumed_at: datetime
    ) -> InboxResult:
        self._guard.ensure_active()
        paired = self._paired_row(project_id, logical_key)
        legacy = self._legacy_row(project_id, logical_key)
        if paired is not None and paired["result_sha256"] is not None:
            if paired["result_consumed_at"] is not None:
                raise RepositoryStateTransitionError(
                    project_id,
                    logical_key,
                    from_status=InboxStatus.CONSUMED.value,
                    to_status=InboxStatus.CONSUMED.value,
                )
            self._conn.execute(
                "UPDATE outbox_message SET result_consumed_at=? "
                "WHERE project_id=? AND outbox_message_id=?",
                (
                    _dt_to_iso(consumed_at),
                    project_id,
                    paired["outbox_message_id"],
                ),
            )
            stored = self._paired_row(project_id, logical_key)
            assert stored is not None and stored["result_consumed_at"] is not None
            return self._derived_result(stored, legacy)
        if paired is not None and legacy is not None:
            if legacy["status"] != InboxStatus.RECEIVED.value:
                raise RepositoryStateTransitionError(
                    project_id,
                    logical_key,
                    from_status=legacy["status"],
                    to_status=InboxStatus.CONSUMED.value,
                )
            # Adopt-then-consume: the evidence row is left untouched while
            # the live state moves to the single outbox authority.
            self._conn.execute(
                "UPDATE outbox_message SET result_sha256=?, result_received_at=?, "
                "result_consumed_at=? WHERE project_id=? AND outbox_message_id=?",
                (
                    legacy["result_sha256"],
                    legacy["received_at"],
                    _dt_to_iso(consumed_at),
                    project_id,
                    paired["outbox_message_id"],
                ),
            )
            stored = self._paired_row(project_id, logical_key)
            assert stored is not None and stored["result_sha256"] is not None
            return self._derived_result(stored, legacy)
        if paired is not None:
            raise AggregateNotFoundError(project_id, aggregate_id=logical_key)
        row = legacy
        if row is None:
            raise AggregateNotFoundError(project_id, aggregate_id=logical_key)
        if row["status"] != InboxStatus.RECEIVED.value:
            raise RepositoryStateTransitionError(
                project_id,
                logical_key,
                from_status=row["status"],
                to_status=InboxStatus.CONSUMED.value,
            )
        self._conn.execute(
            "UPDATE inbox_result SET status=?, consumed_at=? "
            "WHERE project_id=? AND inbox_result_id=?",
            (
                InboxStatus.CONSUMED.value,
                _dt_to_iso(consumed_at),
                project_id,
                row["inbox_result_id"],
            ),
        )
        return self._row_to_result(
            self._conn.execute(
                "SELECT * FROM inbox_result WHERE project_id=? AND inbox_result_id=?",
                (project_id, row["inbox_result_id"]),
            ).fetchone()
        )


class _SqliteReservationRepository:
    def __init__(self, conn: sqlite3.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def _row_to_reservation(self, row: sqlite3.Row) -> ExecutionReservation:
        return ExecutionReservation.model_validate(
            {
                "execution_reservation_id": row["execution_reservation_id"],
                "node_execution_contract_id": row["node_execution_contract_id"],
                "logical_call_id": row["logical_call_id"],
                "idempotency_key": row["idempotency_key"],
                "input_sha256": row["input_sha256"],
                "attempt": row["attempt"],
                "transport_attempts": row["transport_attempts"],
                "provider_session_id": row["provider_session_id"],
                "status": ReservationStatus(row["status"]),
                "terminal_state": (
                    ExecutionTerminalState(row["terminal_state"])
                    if row["terminal_state"]
                    else None
                ),
                "output_sha256": row["output_sha256"],
                "error_code": row["error_code"],
                "reserved_at": _dt_from_iso(row["reserved_at"]),  # type: ignore[arg-type]
                "updated_at": _dt_from_iso(row["updated_at"]),  # type: ignore[arg-type]
            }
        )

    def reserve(
        self, project_id: str, reservation: ExecutionReservation
    ) -> ExecutionReservation:
        self._guard.ensure_active()
        row = self._conn.execute(
            "SELECT * FROM execution_reservation "
            "WHERE project_id=? AND logical_call_id=? AND idempotency_key=?",
            (project_id, reservation.logical_call_id, reservation.idempotency_key),
        ).fetchone()
        if row is not None:
            existing = self._row_to_reservation(row)
            if existing.input_sha256 != reservation.input_sha256:
                raise IdempotencyConflictError(
                    project_id,
                    reservation.logical_call_id,
                    existing.input_sha256,
                    reservation.input_sha256,
                )
            if existing.status is ReservationStatus.UNKNOWN_OUTCOME:
                raise UnknownOutcomeConflictError(
                    project_id,
                    aggregate_id=reservation.logical_call_id,
                    detail=(
                        "unknown-outcome reservation must be resolved "
                        "before re-dispatch"
                    ),
                )
            return existing
        identity_row = self._conn.execute(
            "SELECT * FROM execution_reservation "
            "WHERE project_id=? AND execution_reservation_id=?",
            (project_id, reservation.execution_reservation_id),
        ).fetchone()
        if identity_row is not None:
            collision = self._row_to_reservation(identity_row)
            raise IdempotencyConflictError(
                project_id,
                reservation.execution_reservation_id,
                collision.input_sha256,
                reservation.input_sha256,
            )
        attempt_row = self._conn.execute(
            "SELECT * FROM execution_reservation "
            "WHERE project_id=? AND logical_call_id=? AND attempt=?",
            (project_id, reservation.logical_call_id, reservation.attempt),
        ).fetchone()
        if attempt_row is not None:
            collision = self._row_to_reservation(attempt_row)
            raise IdempotencyConflictError(
                project_id,
                f"{reservation.logical_call_id}:attempt:{reservation.attempt}",
                collision.input_sha256,
                reservation.input_sha256,
            )
        self._conn.execute(
            "INSERT INTO execution_reservation "
            "(execution_reservation_id, project_id, node_execution_contract_id, "
            " logical_call_id, idempotency_key, input_sha256, attempt, "
            " transport_attempts, provider_session_id, status, terminal_state, "
            " output_sha256, error_code, reserved_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                reservation.execution_reservation_id,
                project_id,
                reservation.node_execution_contract_id,
                reservation.logical_call_id,
                reservation.idempotency_key,
                reservation.input_sha256,
                reservation.attempt,
                reservation.transport_attempts,
                reservation.provider_session_id,
                reservation.status.value,
                (
                    reservation.terminal_state.value
                    if reservation.terminal_state
                    else None
                ),
                reservation.output_sha256,
                reservation.error_code,
                _dt_to_iso(reservation.reserved_at),
                _dt_to_iso(reservation.updated_at),
            ),
        )
        return reservation

    def get(
        self, project_id: str, execution_reservation_id: str
    ) -> Optional[ExecutionReservation]:
        self._guard.ensure_open()
        row = self._conn.execute(
            "SELECT * FROM execution_reservation "
            "WHERE project_id=? AND execution_reservation_id=?",
            (project_id, execution_reservation_id),
        ).fetchone()
        return self._row_to_reservation(row) if row else None

    def find_by_logical_call(
        self, project_id: str, logical_call_id: str, idempotency_key: str
    ) -> Optional[ExecutionReservation]:
        self._guard.ensure_open()
        row = self._conn.execute(
            "SELECT * FROM execution_reservation "
            "WHERE project_id=? AND logical_call_id=? AND idempotency_key=?",
            (project_id, logical_call_id, idempotency_key),
        ).fetchone()
        return self._row_to_reservation(row) if row else None

    def transition(
        self,
        project_id: str,
        execution_reservation_id: str,
        *,
        to_status: ReservationStatus,
        terminal_state: Optional[ExecutionTerminalState] = None,
        output_sha256: Optional[str] = None,
        error_code: Optional[str] = None,
        provider_session_id: Optional[str] = None,
        transport_attempts: Optional[int] = None,
        updated_at: datetime,
    ) -> ExecutionReservation:
        self._guard.ensure_active()
        row = self._conn.execute(
            "SELECT * FROM execution_reservation "
            "WHERE project_id=? AND execution_reservation_id=?",
            (project_id, execution_reservation_id),
        ).fetchone()
        if row is None:
            raise AggregateNotFoundError(
                project_id, aggregate_id=execution_reservation_id
            )
        existing = self._row_to_reservation(row)
        allowed = {
            ReservationStatus.RESERVED: {
                ReservationStatus.RUNNING,
                ReservationStatus.FAILED,
            },
            ReservationStatus.RUNNING: {
                ReservationStatus.COMPLETED,
                ReservationStatus.FAILED,
                ReservationStatus.UNKNOWN_OUTCOME,
            },
            ReservationStatus.UNKNOWN_OUTCOME: {ReservationStatus.COMPLETED},
            ReservationStatus.COMPLETED: set(),
            ReservationStatus.FAILED: set(),
        }
        if to_status not in allowed[existing.status]:
            raise RepositoryStateTransitionError(
                project_id,
                execution_reservation_id,
                from_status=existing.status.value,
                to_status=to_status.value,
            )
        next_transport = (
            existing.transport_attempts
            if transport_attempts is None
            else transport_attempts
        )
        if next_transport < existing.transport_attempts:
            raise RepositoryStateTransitionError(
                project_id,
                execution_reservation_id,
                from_status=existing.status.value,
                to_status=to_status.value,
            )
        if existing.status is ReservationStatus.RESERVED:
            expected_attempts = (
                existing.transport_attempts + 1
                if to_status is ReservationStatus.RUNNING
                else existing.transport_attempts
            )
            if next_transport != expected_attempts:
                raise RepositoryStateTransitionError(
                    project_id,
                    execution_reservation_id,
                    from_status=existing.status.value,
                    to_status=to_status.value,
                )
        elif next_transport != existing.transport_attempts:
            raise RepositoryStateTransitionError(
                project_id,
                execution_reservation_id,
                from_status=existing.status.value,
                to_status=to_status.value,
            )
        next_session = (
            provider_session_id
            if provider_session_id is not None
            else existing.provider_session_id
        )
        if (
            existing.status is ReservationStatus.UNKNOWN_OUTCOME
            and provider_session_id is not None
            and provider_session_id != existing.provider_session_id
        ):
            raise RepositoryStateTransitionError(
                project_id,
                execution_reservation_id,
                from_status=existing.status.value,
                to_status=to_status.value,
            )
        updated = ExecutionReservation.model_validate(
            {
                **existing.model_dump(),
                "status": to_status,
                "terminal_state": terminal_state,
                "output_sha256": output_sha256,
                "error_code": error_code,
                "provider_session_id": next_session,
                "transport_attempts": next_transport,
                "updated_at": updated_at,
            }
        )
        self._conn.execute(
            "UPDATE execution_reservation SET status=?, terminal_state=?, "
            "output_sha256=?, error_code=?, provider_session_id=?, "
            "transport_attempts=?, updated_at=? "
            "WHERE project_id=? AND execution_reservation_id=?",
            (
                updated.status.value,
                (
                    updated.terminal_state.value
                    if updated.terminal_state
                    else None
                ),
                updated.output_sha256,
                updated.error_code,
                updated.provider_session_id,
                updated.transport_attempts,
                _dt_to_iso(updated.updated_at),
                project_id,
                execution_reservation_id,
            ),
        )
        return updated

    def list_attempts(
        self, project_id: str, logical_call_id: str
    ) -> Tuple[ExecutionReservation, ...]:
        self._guard.ensure_open()
        rows = self._conn.execute(
            "SELECT * FROM execution_reservation "
            "WHERE project_id=? AND logical_call_id=? "
            "ORDER BY attempt, execution_reservation_id",
            (project_id, logical_call_id),
        ).fetchall()
        return tuple(self._row_to_reservation(r) for r in rows)

    def find_unknown_outcome(
        self, project_id: str
    ) -> Tuple[ExecutionReservation, ...]:
        self._guard.ensure_open()
        rows = self._conn.execute(
            "SELECT * FROM execution_reservation "
            "WHERE project_id=? AND status=? ORDER BY logical_call_id, attempt",
            (project_id, ReservationStatus.UNKNOWN_OUTCOME.value),
        ).fetchall()
        return tuple(self._row_to_reservation(r) for r in rows)

    def find_unresolved(self, project_id: str) -> Tuple[ExecutionReservation, ...]:
        self._guard.ensure_open()
        rows = self._conn.execute(
            "SELECT * FROM execution_reservation "
            "WHERE project_id=? AND status IN (?, ?, ?) "
            "ORDER BY logical_call_id, attempt, execution_reservation_id",
            (
                project_id,
                ReservationStatus.RESERVED.value,
                ReservationStatus.RUNNING.value,
                ReservationStatus.UNKNOWN_OUTCOME.value,
            ),
        ).fetchall()
        return tuple(self._row_to_reservation(r) for r in rows)


# ---------------------------------------------------------------------------
# Committed-operation reservation repository — Task 1R.4 dispatch runtime
# ---------------------------------------------------------------------------

_T = TypeVar("_T")


class _AlwaysActiveGuard(_Guard):
    """Guard for a committed-operation repository handle.

    Such a handle is not a unit of work: every operation manages its own
    transaction, so mutators are always inside an active scope while the
    handle is open.
    """

    def ensure_active(self) -> None:
        self.ensure_open()


class SqliteCommittedOperationReservationRepository:
    """Reservation repository handle whose every operation commits durably.

    The physical-dispatch runtime needs each reservation step — the RESERVED
    ownership claim, the RUNNING transition, and the terminal outcome — to be
    committed (and therefore visible to independent connections) BEFORE the
    transport dispatches physically, so a crash can never lose the record of
    an accepted dispatch.  This handle gives the
    :class:`~app.protocol_workflow.runtime.reservations.ReservationCoordinator`
    that boundary: it owns one dedicated connection and wraps the shared
    :class:`_SqliteReservationRepository` row semantics in a per-operation
    ``BEGIN IMMEDIATE ... COMMIT`` (``synchronous=FULL`` durability applies to
    every commit).

    It deliberately does NOT replace the unit-of-work repository: a raw UoW
    reservation repository keeps its business-transaction semantics (writes
    commit or roll back together with the caller's ``with unit_of_work:``
    scope, never autocommitting arbitrary caller events).  Only the dispatch
    runtime wires this committed-operation handle, through
    :func:`build_committed_reservation_repository_factory`.

    One handle per coordinator/thread, mirroring one UoW per unit of work;
    concurrent handles serialise on SQLite's single-writer lock with the
    configured ``busy_timeout``.
    """

    def __init__(self, config: _StoreConfig) -> None:
        self._config = config
        self._conn: Optional[sqlite3.Connection] = None
        self._guard = _AlwaysActiveGuard()
        self._closed = False
        self._dispatch_locks: Dict[Tuple[str, str], Any] = {}

    def _open_dispatch_lock(self, project_id: str, reservation_id: str):
        database = self._config.path.resolve()
        directory = database.with_name(database.name + ".dispatch-locks")
        directory.mkdir(exist_ok=True)
        key = hashlib.sha256(
            json.dumps([project_id, reservation_id]).encode("utf-8")
        ).hexdigest()
        # Never unlink lock files: replacing an inode could admit two owners.
        return (directory / key).open("a+b")

    def has_live_dispatch(self, project_id: str, reservation_id: str) -> bool:
        """Local OS ownership survives threads and is released on process death."""
        with self._open_dispatch_lock(project_id, reservation_id) as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False

    # -- connection ----------------------------------------------------------

    def _connection(self) -> sqlite3.Connection:
        if self._closed or self._guard.closed:
            raise UnitOfWorkClosedError(
                "committed-operation reservation repository is closed"
            )
        if self._conn is None:
            self._conn = _conn_for(self._config)
        return self._conn

    def _commit_operation(
        self, operation: Callable[[_SqliteReservationRepository], _T]
    ) -> _T:
        """Run one repository operation as its own durable transaction."""
        conn = self._connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = operation(
                _SqliteReservationRepository(conn, self._guard)
            )
            conn.execute("COMMIT")
            return result
        except BaseException:
            _safe_rollback(conn)
            raise

    # -- coordinator surface (mutators commit before returning) --------------

    def reserve(
        self, project_id: str, reservation: ExecutionReservation
    ) -> ExecutionReservation:
        key = (project_id, reservation.execution_reservation_id)
        if key in self._dispatch_locks:
            return self._commit_operation(lambda repo: repo.reserve(project_id, reservation))
        handle = self._open_dispatch_lock(*key)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self._commit_operation(lambda repo: repo.reserve(project_id, reservation))
            if result.execution_reservation_id == reservation.execution_reservation_id:
                self._dispatch_locks[key] = handle
            else:
                handle.close()
            return result
        except BaseException:
            handle.close()
            raise

    def transition(
        self,
        project_id: str,
        execution_reservation_id: str,
        *,
        to_status: ReservationStatus,
        terminal_state: Optional[ExecutionTerminalState] = None,
        output_sha256: Optional[str] = None,
        error_code: Optional[str] = None,
        provider_session_id: Optional[str] = None,
        transport_attempts: Optional[int] = None,
        updated_at: datetime,
    ) -> ExecutionReservation:
        result = self._commit_operation(
            lambda repo: repo.transition(
                project_id,
                execution_reservation_id,
                to_status=to_status,
                terminal_state=terminal_state,
                output_sha256=output_sha256,
                error_code=error_code,
                provider_session_id=provider_session_id,
                transport_attempts=transport_attempts,
                updated_at=updated_at,
            )
        )
        if result.terminal_state is not None:
            handle = self._dispatch_locks.pop((project_id, execution_reservation_id), None)
            if handle is not None:
                handle.close()
        return result

    # -- coordinator surface (reads are autocommit snapshots) ----------------

    def get(
        self, project_id: str, execution_reservation_id: str
    ) -> Optional[ExecutionReservation]:
        return _SqliteReservationRepository(
            self._connection(), self._guard
        ).get(project_id, execution_reservation_id)

    def find_by_logical_call(
        self, project_id: str, logical_call_id: str, idempotency_key: str
    ) -> Optional[ExecutionReservation]:
        return _SqliteReservationRepository(
            self._connection(), self._guard
        ).find_by_logical_call(project_id, logical_call_id, idempotency_key)

    def list_attempts(
        self, project_id: str, logical_call_id: str
    ) -> Tuple[ExecutionReservation, ...]:
        return _SqliteReservationRepository(
            self._connection(), self._guard
        ).list_attempts(project_id, logical_call_id)

    def find_unknown_outcome(
        self, project_id: str
    ) -> Tuple[ExecutionReservation, ...]:
        return _SqliteReservationRepository(
            self._connection(), self._guard
        ).find_unknown_outcome(project_id)

    def find_unresolved(self, project_id: str) -> Tuple[ExecutionReservation, ...]:
        return _SqliteReservationRepository(
            self._connection(), self._guard
        ).find_unresolved(project_id)

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        """Close the dedicated connection (idempotent)."""
        self._closed = True
        self._guard.closed = True
        for handle in self._dispatch_locks.values():
            handle.close()
        self._dispatch_locks.clear()
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "SqliteCommittedOperationReservationRepository":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def build_committed_reservation_repository_factory(
    config: Mapping[str, Any],
) -> Callable[[], SqliteCommittedOperationReservationRepository]:
    """Validate *config*, bootstrap the schema and return a factory of
    committed-operation reservation repository handles.

    Validation and bootstrap are exactly :func:`build_unit_of_work_factory`'s
    fail-closed path (engine gate, read-only adoption preflight, ordered
    migrations).  The returned factory yields independent handles for the
    physical-dispatch runtime; each handle commits every reservation
    operation durably before the transport side effects run.  The shared
    unit-of-work factory remains the business-transaction route.
    """
    store_config = _validate_config(config)
    _bootstrap(store_config)

    def factory() -> SqliteCommittedOperationReservationRepository:
        return SqliteCommittedOperationReservationRepository(store_config)

    return factory


class _SqliteReadModelRepository:
    def __init__(self, conn: sqlite3.Connection, guard: _Guard) -> None:
        self._conn = conn
        self._guard = guard

    def replace_chapter_coverage(
        self,
        project_id: str,
        semantic_document_revision_id: str,
        records: Sequence[ChapterCoverageRecord],
    ) -> None:
        """Replace the whole projection for one document revision.

        Replacement (not upsert): rows removed from *records* are deleted so
        stale projections never survive a rebuild.  The DELETE and the
        replacement INSERTs form one savepoint-atomic compound write: a
        failure mid-replacement leaves the previous projection fully intact.
        """
        self._guard.ensure_active()
        self._conn.execute("SAVEPOINT protocol_v3_read_replace")
        try:
            self._conn.execute(
                "DELETE FROM read_chapter_coverage "
                "WHERE project_id=? AND semantic_document_revision_id=?",
                (project_id, semantic_document_revision_id),
            )
            for record in records:
                self._conn.execute(
                    "INSERT INTO read_chapter_coverage "
                    "(project_id, semantic_document_revision_id, semantic_node_id, "
                    " chapter_contract_sha256, substantive_content_contract_sha256, "
                    " semantic_block_sha256, is_locked, has_substantive_content, "
                    " evidence_admitted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        project_id,
                        semantic_document_revision_id,
                        record.semantic_node_id,
                        record.chapter_contract_sha256,
                        record.substantive_content_contract_sha256,
                        record.semantic_block_sha256,
                        int(record.is_locked),
                        int(record.has_substantive_content),
                        int(record.evidence_admitted),
                    ),
                )
        except BaseException:
            _undo_savepoint(self._conn, "protocol_v3_read_replace")
            raise
        self._conn.execute("RELEASE SAVEPOINT protocol_v3_read_replace")

    def replace_decision_graph(
        self,
        project_id: str,
        study_definition_id: str,
        records: Sequence[DecisionGraphRecord],
    ) -> None:
        """Replace the whole projection for one study definition (clears
        stale decision keys removed from *records*).  One savepoint-atomic
        compound write: a failure mid-replacement keeps the previous
        projection.
        """
        self._guard.ensure_active()
        self._conn.execute("SAVEPOINT protocol_v3_read_replace")
        try:
            self._conn.execute(
                "DELETE FROM read_decision_graph "
                "WHERE project_id=? AND study_definition_id=?",
                (project_id, study_definition_id),
            )
            for record in records:
                self._conn.execute(
                    "INSERT INTO read_decision_graph "
                    "(project_id, study_definition_id, decision_key, "
                    " decision_record_id, state_revision, selected_option_id, "
                    " canonical_state) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        project_id,
                        study_definition_id,
                        record.decision_key,
                        record.decision_record_id,
                        record.state_revision,
                        record.selected_option_id,
                        (
                            record.canonical_state.value
                            if record.canonical_state is not None
                            else None
                        ),
                    ),
                )
        except BaseException:
            _undo_savepoint(self._conn, "protocol_v3_read_replace")
            raise
        self._conn.execute("RELEASE SAVEPOINT protocol_v3_read_replace")

    def upsert_workflow_run_status(self, record: WorkflowRunStatusRecord) -> None:
        self._guard.ensure_active()
        self._conn.execute(
            "INSERT OR REPLACE INTO read_workflow_run_status "
            "(project_id, workflow_run_id, status, display_progress, "
            " journey_counter) VALUES (?, ?, ?, ?, ?)",
            (
                record.project_id,
                record.workflow_run_id,
                record.status.value,
                record.display_progress,
                record.journey_counter,
            ),
        )

    def get_chapter_coverage(
        self, project_id: str, semantic_document_revision_id: str
    ) -> Tuple[ChapterCoverageRecord, ...]:
        self._guard.ensure_open()
        rows = self._conn.execute(
            "SELECT * FROM read_chapter_coverage "
            "WHERE project_id=? AND semantic_document_revision_id=? "
            "ORDER BY semantic_node_id",
            (project_id, semantic_document_revision_id),
        ).fetchall()
        return tuple(
            ChapterCoverageRecord(
                project_id=r["project_id"],
                semantic_node_id=r["semantic_node_id"],
                chapter_contract_sha256=r["chapter_contract_sha256"],
                substantive_content_contract_sha256=r[
                    "substantive_content_contract_sha256"
                ],
                semantic_block_sha256=r["semantic_block_sha256"],
                is_locked=bool(r["is_locked"]),
                has_substantive_content=bool(r["has_substantive_content"]),
                evidence_admitted=bool(r["evidence_admitted"]),
            )
            for r in rows
        )

    def get_decision_graph(
        self, project_id: str, study_definition_id: str
    ) -> Tuple[DecisionGraphRecord, ...]:
        self._guard.ensure_open()
        rows = self._conn.execute(
            "SELECT * FROM read_decision_graph "
            "WHERE project_id=? AND study_definition_id=? ORDER BY decision_key",
            (project_id, study_definition_id),
        ).fetchall()
        return tuple(
            DecisionGraphRecord(
                project_id=r["project_id"],
                decision_key=r["decision_key"],
                decision_record_id=r["decision_record_id"],
                state_revision=r["state_revision"],
                selected_option_id=r["selected_option_id"],
                canonical_state=(
                    CanonicalState(r["canonical_state"])
                    if r["canonical_state"]
                    else None
                ),
            )
            for r in rows
        )

    def get_workflow_run_status(
        self, project_id: str, workflow_run_id: str
    ) -> Optional[WorkflowRunStatusRecord]:
        self._guard.ensure_open()
        row = self._conn.execute(
            "SELECT * FROM read_workflow_run_status "
            "WHERE project_id=? AND workflow_run_id=?",
            (project_id, workflow_run_id),
        ).fetchone()
        if row is None:
            return None
        return WorkflowRunStatusRecord(
            project_id=row["project_id"],
            workflow_run_id=row["workflow_run_id"],
            status=WorkflowRunStatus(row["status"]),
            display_progress=row["display_progress"],
            journey_counter=row["journey_counter"],
        )


# ---------------------------------------------------------------------------
# Unit of work — one independent connection per UoW
# ---------------------------------------------------------------------------


class SqliteUnitOfWork:
    """SQLite implementation of :class:`UnitOfWork` over one product database.

    Each instance opens its OWN connection.  ``__enter__`` issues
    ``BEGIN IMMEDIATE`` (acquiring the write lock at the database level);
    ``commit``/``rollback`` issue ``COMMIT``/``ROLLBACK`` and close the
    connection.  All repositories handed out by one UoW share that single
    transaction, so a canonical CAS save, its event append and the outbox
    enqueue commit together or roll back together.
    """

    def __init__(self, config: _StoreConfig) -> None:
        self._config = config
        self._conn = _conn_for(config)
        self._guard = _Guard()
        self._guard.bind_depth(lambda: self._depth)
        self._depth = 0
        self._closed = False
        self._sd_repo = _SqliteCurrentAggregateRepository(
            self._conn, "study_definition", "study_definition_id",
            StudyDefinitionV3, self._guard,
        )
        self._sd_cas = _SqliteCasRepository(
            self._conn, "study_definition", "study_definition_id",
            StudyDefinitionV3, self._guard,
        )
        self._sdr_repo = _SqliteCurrentAggregateRepository(
            self._conn, "semantic_document", "semantic_document_revision_id",
            SemanticDocumentRevision, self._guard,
        )
        self._sdr_cas = _SqliteCasRepository(
            self._conn, "semantic_document", "semantic_document_revision_id",
            SemanticDocumentRevision, self._guard,
        )
        self._events = _SqliteEventStreamRepository(self._conn, self._guard)
        self._outbox = _SqliteOutboxRepository(self._conn, self._guard)
        self._inbox = _SqliteInboxRepository(self._conn, self._guard)
        self._reservations = _SqliteReservationRepository(self._conn, self._guard)
        self._read_models = _SqliteReadModelRepository(self._conn, self._guard)

    # -- repository handles --------------------------------------------------

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

    # -- diagnostics ---------------------------------------------------------

    def connection_pragmas(self) -> dict:
        """Return the durability pragmas of the live connection (diagnostics).

        Fails closed with :class:`UnitOfWorkClosedError` once the UoW is
        closed.
        """
        self._guard.ensure_open()
        conn = self._conn
        return {
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            "synchronous": conn.execute("PRAGMA synchronous").fetchone()[0],
            "foreign_keys": conn.execute("PRAGMA foreign_keys").fetchone()[0],
            "busy_timeout": conn.execute("PRAGMA busy_timeout").fetchone()[0],
        }

    # -- transaction lifecycle ----------------------------------------------

    @property
    def is_active(self) -> bool:
        return not self._closed and self._depth > 0

    def _close_conn(self) -> None:
        conn = self._conn
        self._conn = None  # type: ignore[assignment]
        if conn is not None:
            conn.close()

    def commit(self) -> None:
        if self._closed:
            return
        if self._depth == 0:
            # Never entered: nothing to commit.  Mirror the memory adapter's
            # no-op close instead of a driver error on a missing transaction.
            self._closed = True
            self._guard.closed = True
            self._close_conn()
            return
        if self._depth > 1:
            self._depth -= 1
            return
        try:
            self._conn.execute("COMMIT")
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
            self._conn.execute("BEGIN IMMEDIATE")
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
# Factory (the AdapterBuilder wired by storage.selected)
# ---------------------------------------------------------------------------


def build_unit_of_work_factory(
    config: Mapping[str, Any],
) -> Callable[[], SqliteUnitOfWork]:
    """Validate *config*, assert the engine gate, bootstrap the schema and
    return a unit-of-work factory for the product SQLite database.

    This is the :data:`app.protocol_workflow.storage.selected.AdapterBuilder`
    for the selected backend.  Configuration contract::

        {
            "backend": "sqlite",          # required, exactly "sqlite"
            "path": "<db file path>",     # required, non-empty str/PathLike
            "busy_timeout_ms": 5000,      # optional, positive int
            "synchronous": "FULL",        # optional, only "FULL" accepted
        }

    Invalid configuration and incompatible database files raise typed
    ``SqliteStorageError`` subclasses (fail closed); the builder never
    returns ``None`` and never falls back to another backend.
    """
    store_config = _validate_config(config)
    _bootstrap(store_config)

    def factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(store_config)

    return factory


# ---------------------------------------------------------------------------
# Durable project allowlist — Task 1R.2 mount gate (schema version 2)
# ---------------------------------------------------------------------------

#: Product table (migration 2) holding the explicitly admitted projects.  The
#: empty table admits nothing: every project stays on the legacy chain until
#: an operator admits it out-of-band.  This is deployment state, not domain
#: state — there is deliberately no HTTP activation endpoint and no reuse of
#: any in-memory cutover record (a cutover-transition record is not an
#: admission authority and does not survive restarts).
_ALLOWLIST_TABLE = "protocol_workflow_project_allowlist"

#: Schema version that first carries the allowlist table.
ALLOWLIST_SCHEMA_VERSION = 2


def _validate_project_id(project_id: object) -> str:
    """Return *project_id* unchanged, fail closed on blank/non-string."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise SqliteStorageConfigurationError(
            "allowlist project_id must be a non-empty string"
        )
    return project_id


def is_project_admitted(
    config: Mapping[str, Any],
    project_id: str,
) -> bool:
    """Return whether *project_id* is admitted to the new workflow chain.

    Read-only: a missing or empty database file, or a pre-allowlist (v1)
    product database, simply admits nothing and is left untouched — the
    gate never bootstraps or migrates.  A present-but-foreign/malformed
    file at the configured path raises
    :class:`SqliteStorageConfigurationError` (loud misconfiguration, never
    a silent legacy fallback that would mask corruption).
    """
    project_id = _validate_project_id(project_id)
    store_config = _validate_config(config)
    path = store_config.path
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        ro = _open_readonly(path)
    except sqlite3.OperationalError as exc:
        raise SqliteStorageConfigurationError(
            f"allowlist database {str(path)!r} cannot be opened read-only "
            "for verification; refusing to guess admission"
        ) from exc
    try:
        try:
            tables = _user_table_names(ro)
        except sqlite3.DatabaseError as exc:
            raise SqliteStorageConfigurationError(
                f"target file {str(path)!r} is not a usable SQLite database; "
                "it was left untouched"
            ) from exc
        if "schema_version" not in tables:
            raise SqliteStorageConfigurationError(
                f"target database {str(path)!r} exists but does not carry the "
                "product schema (no schema_version table); refusing to guess "
                "admission"
            )
        try:
            rows = [
                r[0]
                for r in ro.execute(
                    "SELECT version FROM schema_version ORDER BY rowid"
                ).fetchall()
            ]
        except sqlite3.DatabaseError as exc:
            raise SqliteStorageConfigurationError(
                f"schema_version table in {str(path)!r} is unreadable or "
                "incompatible; refusing to guess admission"
            ) from exc
        version = _validate_migration_history(rows)
        if version < ALLOWLIST_SCHEMA_VERSION:
            return False
        if _ALLOWLIST_TABLE not in tables:
            raise SqliteStorageConfigurationError(
                f"database {str(path)!r} at schema version {version} does not "
                f"carry the owned {_ALLOWLIST_TABLE!r} table; refusing to "
                "guess admission"
            )
        row = ro.execute(
            f"SELECT 1 FROM {_ALLOWLIST_TABLE} WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return row is not None
    finally:
        ro.close()


def admit_project(
    config: Mapping[str, Any],
    project_id: str,
    *,
    admitted_at: Optional[str] = None,
) -> bool:
    """Admit *project_id* durably; return True when newly admitted.

    Out-of-band operator/test tooling only — there is no HTTP activation
    endpoint in this phase.  Bootstraps (and migrates) the product database
    through the same fail-closed path as the unit-of-work factory, then
    inserts the allowlist row idempotently (first admission wins; replays
    return False and change nothing).
    """
    project_id = _validate_project_id(project_id)
    if admitted_at is None:
        admitted_at = _now_iso()
    elif not isinstance(admitted_at, str) or not admitted_at.strip():
        raise SqliteStorageConfigurationError(
            "admitted_at must be a non-empty ISO-8601 string"
        )
    store_config = _validate_config(config)
    _bootstrap(store_config)
    conn = _conn_for(store_config)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO {_ALLOWLIST_TABLE} "
                "(project_id, admitted_at) VALUES (?, ?)",
                (project_id, admitted_at),
            )
            inserted = cursor.rowcount == 1
            conn.execute("COMMIT")
        except BaseException:
            _safe_rollback(conn)
            raise
    finally:
        conn.close()
    return inserted
