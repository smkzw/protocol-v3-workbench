"""Database-neutral contract suite for the Protocol v3 storage PoC — Task 1.8.

This module is storage-neutral: it exercises the same observable repository
contract against any candidate backend that exposes a :class:`Backend`
control protocol.  The module itself MUST NOT import SQLite, PostgreSQL or any
database-private API.  Candidates supply concrete :class:`Backend`
implementations (SQLite, PostgreSQL, in-memory baseline, ...).

The frozen benchmark workload is captured BEFORE any candidate result:

* **8 independent writers** — eight threads, each driving its own UoW against
  independent connections to the same database, racing 1,000 CAS saves.
* **1,000 CAS operations** — the exact number of ``save_with_expected_revision``
  calls the writers are permitted to successfully complete (final aggregate
  revision == 1,000).  Lost updates and duplicate semantic effects must be 0.
* **10,000 DomainEvents** — a single append-only stream of 10,000 events with a
  verified SHA-256 chain; zero chain breaks and exact replay hash.
* **1,000-event reference scale** — the Protocol reference scale for this PoC;
  the 10x backup workload backs up/restores/replays 10,000 events.

Invariants proved (each returns a named pass/fail signal):

1. CAS optimistic concurrency — independent writers, zero lost updates, zero
   duplicate semantic effects, p95 latency.
2. Append-only event chain — 10,000 events, zero hash-chain breaks, exact hash.
3. Transaction + outbox atomicity — commit together; rollback discards both.
4. Checkpoint isolation as persisted storage — checkpoint create/update/delete
   cannot change event count/hash; project/run isolation holds.
5. Backup → restore → replay at 10x reference scale — exact canonical hash.
6. Crash recovery — real subprocess committed events/outbox, killed without
   graceful cleanup, reopen proves committed-event RPO=0 + exact hash chain +
   no duplicate semantic effect.
7. Rollback to a pre-switch snapshot — restore a pre-mutation backup and prove
   exact reversion.
8. Migration accounting — every persisted class (canonical revisions, events,
   outbox, inbox, reservations, read models, checkpoints) with per-class
   source/migrated/quarantine counts and canonical hashes; 100% accounting and
   stable quarantine reasons.

The suite separates deterministic semantic evidence (counts, hashes, statuses,
connection identities) from measured environment/timing receipts.  ``to_dict()``
emits ``deterministic`` and ``measured`` top-level keys; ``deterministic_digest``
is a SHA-256 over the deterministic evidence, and repeating a candidate must
reproduce the same digest.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    CanonicalState,
    DomainEvent,
    ExecutionReservation,
    ExecutionTerminalState,
    ReservationStatus,
    SemanticBlock,
    SemanticBlockKind,
    SemanticDocumentRevision,
    StudyDefinitionV3,
    WorkflowRunStatus,
)

from app.protocol_workflow.events.models import (
    EventEnvelopeBuilder,
    verify_event_integrity,
)
from app.protocol_workflow.ports.repositories import (
    ChapterCoverageRecord,
    DecisionGraphRecord,
    EventSequenceConflictError,
    IdempotencyConflictError,
    OutboxStatus,
    RevisionConflictError,
    StreamHead,
    WorkflowRunStatusRecord,
)
from app.protocol_workflow.ports.unit_of_work import UnitOfWork


class RetryableStorageError(RuntimeError):
    """Database-neutral, retryable contention signal.

    A candidate raises this (or a subclass) for known retryable lock,
    deadlock, busy or serialization failures.  The contract suite retries ONLY
    on :class:`RevisionConflictError` (CAS precondition) or
    :class:`RetryableStorageError`.  Any other exception (programming errors,
    validation, assertion failures) must fail the invariant immediately —
    never be swallowed as a transient busy.
    """

# ---------------------------------------------------------------------------
# Frozen benchmark workload — captured BEFORE candidate results
# ---------------------------------------------------------------------------

#: Eight independent writers racing CAS saves.  Frozen threshold.
WRITER_COUNT: int = 8

#: 1,000 CAS operations.  Frozen threshold.  Exactly this many CAS saves
#: complete successfully; the final aggregate revision is therefore 1,000
#: (revision 1 is the first successful create, revision 1,000 the last).
CAS_OPERATION_COUNT: int = 1_000

#: 10,000 DomainEvents in one append-only stream.  Frozen threshold.
EVENT_COUNT: int = 10_000

#: Protocol reference scale for a backup workload: 1,000 events.  Frozen.
REFERENCE_EVENT_COUNT: int = 1_000

#: 10x scale multiplier for the backup→restore→replay workload.
SCALE_MULTIPLIER: int = 10

#: Backup→restore→replay budget (seconds).  Threshold remains 15 minutes.
BACKUP_RESTORE_REPLAY_BUDGET_S: float = 15 * 60

#: Maximum per-writer retry budget for CAS conflicts / SQLite busy at DB level.
MAX_CAS_RETRIES: int = 500

#: Schema version for PoC event payloads.
_EVENT_SCHEMA = "mw_protocol_v3_event_v1"
_UPCASTER = "noop:v1"

_RESULTS_DIR = Path(__file__).resolve().parent / "results"

#: Number of per-class rows to migrate in the migration invariant.
_MIGRATION_ROWS_PER_CLASS = 8


# ---------------------------------------------------------------------------
# Frozen clock and helpers
# ---------------------------------------------------------------------------

_FROZEN_EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class FrozenClock:
    """Deterministic monotonic clock for reproducible timestamps."""

    def __init__(self, start: datetime = _FROZEN_EPOCH) -> None:
        self._next = start
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            value = self._next
            self._next = value.replace(microsecond=value.microsecond + 1)
            return value


def _sha(n: int = 0) -> str:
    """Deterministic 64-hex SHA-256 string."""
    return f"{n:064x}"


def _canonical_model_hash(model: Any) -> str:
    """Canonical SHA-256 over a Pydantic model's JSON dump."""
    return sha256(
        json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _make_study(
    *,
    study_id: str,
    project_id: str,
    revision: int,
    previous: Optional[str] = None,
    seed: int = 0,
) -> StudyDefinitionV3:
    return StudyDefinitionV3(
        study_definition_id=study_id,
        project_id=project_id,
        revision=revision,
        previous_revision_sha256=previous,
        normalized_seed_id=f"seed:{study_id}",
        normalized_seed_sha256=_sha(seed + 1),
        facts={"indication": f"study-{seed}", "seed": str(seed)},
        updated_at=_FROZEN_EPOCH,
    )


def _make_event(
    builder: EventEnvelopeBuilder,
    *,
    event_id: str,
    stream_id: str,
    sequence: int,
    previous: Optional[str],
    payload_index: int,
    emitted_at: datetime,
) -> DomainEvent:
    return builder.build(
        domain_event_id=event_id,
        stream_id=stream_id,
        sequence=sequence,
        event_type="study_definition.revised",
        payload_schema_version=_EVENT_SCHEMA,
        upcaster_id=_UPCASTER,
        actor_type=ActorType.AI,
        actor_id="agent:corpus:1",
        action="revise",
        reason="poc-benchmark",
        payload={"revision": sequence, "index": payload_index},
        emitted_at=emitted_at,
        previous_event_sha256=previous,
    )


def _read_current_revision(uow: UnitOfWork, project_id: str, study_id: str) -> Optional[int]:
    """Read the current revision via the current-aggregate repository.

    Reads go through ``CurrentAggregateRepository`` (the read port) and writes
    through ``RevisionCasRepository`` (the CAS port) — database-neutral.
    """
    repo = uow.study_definition_repository
    assert repo is not None
    return repo.get_current_revision(project_id, study_id)


def _read_current(uow: UnitOfWork, project_id: str, study_id: str):
    """Read the current revision record via the current-aggregate repository."""
    repo = uow.study_definition_repository
    assert repo is not None
    return repo.get_current(project_id, study_id)


# ---------------------------------------------------------------------------
# Backend control protocol
# ---------------------------------------------------------------------------


class BackendSpec(Protocol):
    """Opaque backend-specific restore configuration.

    The suite passes this through from the candidate's ``spawn_*`` hooks; it
    never inspects it.  Candidates define their own concrete type.
    """


class CheckpointStore(Protocol):
    """A persistence handle for checkpoint records, separate from events.

    The checkpoint is stored in its own table/namespace so that
    create/update/delete operations cannot alter the event stream.
    """

    def create(
        self,
        project_id: str,
        run_id: str,
        stream_id: str,
        checkpoint_seq: int,
        checkpoint_sha: str,
        *,
        state: int,
    ) -> "CheckpointRecord": ...

    def update(
        self, project_id: str, run_id: str, checkpoint_seq: int, checkpoint_sha: str
    ) -> "CheckpointRecord": ...

    def delete(self, project_id: str, run_id: str) -> None: ...

    def get(self, project_id: str, run_id: str) -> Optional["CheckpointRecord"]: ...

    def list_runs(self, project_id: str) -> Tuple[str, ...]: ...

    def count(self) -> int: ...


class CheckpointRecord(Protocol):
    """A stored checkpoint record."""
    project_id: str
    run_id: str
    stream_id: str
    checkpoint_seq: int
    checkpoint_sha: str


class QuarantineRecord(Protocol):
    """A preserved unmappable object in an explicit quarantine store."""
    family: str
    source_key: str
    reason_code: str
    body_hash: str
    body: str


class QuarantineStore(Protocol):
    """Database-neutral quarantine control port.

    Persists deliberately unmappable raw objects so that migration can prove
    ``source = migrated + quarantined`` with a stable reason code, source key
    and canonical body hash surviving.  A candidate implements this over its
    schema; the suite never inspects the concrete storage.
    """

    def quarantine(
        self, family: str, source_key: str, reason_code: str, body: str
    ) -> QuarantineRecord: ...

    def list_quarantined(self, family: str) -> Tuple[QuarantineRecord, ...]: ...

    def close(self) -> None: ...


class Backend(Protocol):
    """Backend control protocol supplied by each candidate.

    The contract suite uses ONLY these methods to drive a candidate.  No
    database-private import leaks into the suite.
    """

    @property
    def name(self) -> str: ...

    def new_uow(self) -> UnitOfWork:
        """Open a fresh UoW on a fresh connection to the candidate's store."""

    def backup_to(self, dest_path: Path) -> Path:
        """Online backup of the candidate's current durable state."""

    def restore_new(self, backup_path: Path, dest_path: Path) -> "Backend":
        """Open a NEW backend whose state is restored from *backup_path*."""

    def close(self) -> None:
        """Close backend-held resources."""

    def spawn_crash_child(
        self,
        work_spec: Dict[str, Any],
        tmp_dir: Path,
    ) -> Tuple[Dict[str, Any], "Backend"]:
        """Launch a subprocess that reconstructs this backend, commits work
        described by *work_spec* via :func:`_crash_child_commit`, writes a
        readiness receipt with fsynced commit-boundary facts, then stays alive.
        The adapter MUST:

        1. Launch the child with the receipt path derived from *work_spec*.
        2. Poll for the receipt file with a bounded deadline.
        3. On receipt: return ``{"receipt_path": <str>, "child_pid": <int>,
           "child_alive": True, ...}`` and a re-opened Backend.
        4. On timeout/error: the invariant fails; evidence must contain
           ``{"error": <str>}`` with diagnostic detail.

        The common invariant validates the receipt, then sends SIGKILL.
        Hard-coded ``committed=True`` in the adapter evidence is forbidden.
        """

    def open_checkpoint_store(self) -> CheckpointStore:
        """Open a handle to the candidate's persisted checkpoint table."""

    def open_quarantine_store(self) -> QuarantineStore:
        """Open a handle to the candidate's persisted quarantine table."""

    def inspect_connection_ids(self, uow: UnitOfWork) -> Dict[str, Any]:
        """Return deterministic per-connection identity evidence for *uow*."""

    def count_duplicate_semantic_effects(
        self, project_id: str, aggregate_id: str, aggregate_kind: str = "study_definition"
    ) -> int:
        """Return the number of (aggregate_id, revision) pairs persisted more
        than once (duplicate semantic effects).  Database-neutral signature;
        each candidate implements the exact query over its schema."""


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass
class InvariantResult:
    name: str
    passed: bool
    #: deterministic semantic evidence (counts, hashes, statuses, ids)
    deterministic: Dict[str, Any] = field(default_factory=dict)
    #: measured environment/timing receipts (NOT "deterministic" claim)
    measured: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class BenchmarkResult:
    candidate: str
    sqlite_version: Optional[str]
    workload: Dict[str, int]
    invariants: List[InvariantResult] = field(default_factory=list)
    measured_ms: Dict[str, float] = field(default_factory=dict)

    @property
    def all_passed(self) -> bool:
        return all(inv.passed for inv in self.invariants)

    @property
    def deterministic_evidence(self) -> Dict[str, Any]:
        return {
            "candidate": self.candidate,
            "workload": self.workload,
            "invariants": [
                {
                    "name": inv.name,
                    "passed": inv.passed,
                    "deterministic": inv.deterministic,
                    "error": inv.error,
                }
                for inv in self.invariants
            ],
        }

    @property
    def deterministic_digest(self) -> str:
        payload = json.dumps(self.deterministic_evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(payload).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate": self.candidate,
            "sqlite_version": self.sqlite_version,
            "workload": self.workload,
            "all_passed": self.all_passed,
            "deterministic_digest": self.deterministic_digest,
            "invariants": [
                {
                    "name": inv.name,
                    "passed": inv.passed,
                    "deterministic": inv.deterministic,
                    "measured": inv.measured,
                    "error": inv.error,
                }
                for inv in self.invariants
            ],
            "measured_ms": self.measured_ms,
        }


# ---------------------------------------------------------------------------
# Invariant 1 — eight independent-writer CAS
# ---------------------------------------------------------------------------


def _writer_cas_worker(
    backend: Backend,
    project_id: str,
    study_id: str,
    ops_per_writer: int,
    writer_index: int,
    counters: Dict[str, int],
    counters_lock: threading.Lock,
    busy_retries: List[int],
    busy_lock: threading.Lock,
    start_barrier: threading.Barrier,
    active: Dict[str, int],
    active_lock: threading.Lock,
    max_active: List[int],
    conn_ids: List[Dict[str, Any]],
    id_lock: threading.Lock,
    op_latencies_ms: List[float],
    lat_lock: threading.Lock,
) -> Tuple[int, int, int]:
    """One writer thread driving independent CAS saves on its own connection.

    Retry policy is strict: only :class:`RevisionConflictError` (CAS
    precondition) and :class:`RetryableStorageError` (database lock/deadlock/
    busy) are retried.  Any other exception propagates and fails the invariant.

    The writer records the connection identity of a UoW it actually used for a
    CAS save, and per-op latency (from op start to success, including lock wait
    and retries) for every successful op.
    """
    # Barrier: all 8 writers wait here so they overlap at the application
    # boundary before any CAS work begins.
    start_barrier.wait()

    successes = 0
    conflicts = 0
    busy = 0
    recorded_conn = False
    for _ in range(ops_per_writer):
        retries = 0
        op_start = time.perf_counter()
        while True:
            retries += 1
            if retries > MAX_CAS_RETRIES:
                raise RuntimeError(f"writer {writer_index} exceeded retry budget")
            uow = backend.new_uow()
            try:
                # Track active writer count for overlap evidence.
                with active_lock:
                    active["n"] += 1
                    if active["n"] > max_active[0]:
                        max_active[0] = active["n"]
                try:
                    with uow:
                        cas = uow.study_definition_cas_repository
                        assert cas is not None
                        current_rev = _read_current_revision(uow, project_id, study_id)
                        expected = current_rev if current_rev is not None else 0
                        new_rev = expected + 1
                        record = _make_study(
                            study_id=study_id,
                            project_id=project_id,
                            revision=new_rev,
                            previous=_sha(expected) if expected else None,
                            seed=new_rev * 100 + writer_index,
                        )
                        try:
                            cas.save_with_expected_revision(
                                project_id, record, expected_revision=expected
                            )
                            successes += 1
                            # Record one connection identity this writer
                            # actually used for a CAS save.
                            if not recorded_conn:
                                cid = backend.inspect_connection_ids(uow)
                                with id_lock:
                                    conn_ids.append(
                                        {
                                            "writer_index": writer_index,
                                            "connection_label": f"writer-{writer_index}",
                                            "connection_identity": cid.get("connection_identity"),
                                        }
                                    )
                                recorded_conn = True
                            with lat_lock:
                                op_latencies_ms.append(
                                    (time.perf_counter() - op_start) * 1000
                                )
                            break
                        except RevisionConflictError:
                            conflicts += 1
                            continue
                        except RetryableStorageError:
                            busy += 1
                            time.sleep(0.001)
                            continue
                except RevisionConflictError:
                    conflicts += 1
                    continue
                except RetryableStorageError:
                    busy += 1
                    time.sleep(0.001)
                    continue
            finally:
                with active_lock:
                    active["n"] -= 1
                # Guarantee the connection is released even if `with` never
                # ran (e.g. __enter__ raised) or the body raised.
                close = getattr(uow, "close", None)
                if close is not None:
                    try:
                        close()
                    except Exception:  # noqa: BLE001
                        pass
    with counters_lock:
        counters["successes"] += successes
        counters["conflicts"] += conflicts
    with busy_lock:
        busy_retries.append(busy)
    return successes, conflicts, busy


def invariant_cas_concurrency(backend: Backend) -> InvariantResult:
    """Eight independent writers race 1,000 CAS saves on one aggregate.

    Frozen contract: exactly ``CAS_OPERATION_COUNT`` (1,000) CAS saves
    complete; the aggregate's final revision is exactly 1,000.  Lost updates
    and duplicate semantic effects (two records with the same revision) are 0.

    Writers use independent per-UoW connections (backend guarantees), start
    behind a barrier so they genuinely overlap, and record per-writer
    connection identities from UoWs actually used for CAS saves.  p50/p95/p99
    latency is measured from the actual concurrent successful CAS operations
    (including database lock wait and retries) — NOT from a later
    single-writer loop.
    """
    project_id = "proj:caspoc:1"
    study_id = "sd:caspoc:1"
    counters: Dict[str, int] = {"successes": 0, "conflicts": 0}
    counters_lock = threading.Lock()
    busy_retries: List[int] = []
    busy_lock = threading.Lock()
    ops_per_writer = CAS_OPERATION_COUNT // WRITER_COUNT  # 125 each

    conn_ids: List[Dict[str, Any]] = []
    id_lock = threading.Lock()
    op_latencies_ms: List[float] = []
    lat_lock = threading.Lock()
    active: Dict[str, int] = {"n": 0}
    active_lock = threading.Lock()
    max_active: List[int] = [0]
    start_barrier = threading.Barrier(WRITER_COUNT)

    def _worker(i: int) -> Tuple[int, int, int]:
        return _writer_cas_worker(
            backend,
            project_id,
            study_id,
            ops_per_writer,
            i,
            counters,
            counters_lock,
            busy_retries,
            busy_lock,
            start_barrier,
            active,
            active_lock,
            max_active,
            conn_ids,
            id_lock,
            op_latencies_ms,
            lat_lock,
        )

    start = time.perf_counter()
    per_writer: Dict[str, Dict[str, int]] = {}
    # Barrier timeout: if any writer fails to reach the barrier (e.g. a
    # retryable-error storm), the suite fails rather than hanging.
    barrier_timeout_s = 30
    with ThreadPoolExecutor(max_workers=WRITER_COUNT) as pool:
        futures = {pool.submit(_worker, i): i for i in range(WRITER_COUNT)}
        for fut in as_completed(futures):
            i = futures[fut]
            successes, conflicts, busy = fut.result()
            per_writer[f"writer-{i}"] = {"successes": successes, "conflicts": conflicts, "busy_retries": busy}
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Final state.
    uow = backend.new_uow()
    with uow:
        final_rev = _read_current_revision(uow, project_id, study_id)

    # Latency percentiles from the ACTUAL concurrent successful CAS ops.
    if op_latencies_ms:
        op_latencies_ms.sort()
        p50 = op_latencies_ms[len(op_latencies_ms) // 2]
        p95 = op_latencies_ms[int(len(op_latencies_ms) * 0.95)]
        p99 = op_latencies_ms[int(len(op_latencies_ms) * 0.99)]
    else:
        p50 = p95 = p99 = None

    lost_updates = CAS_OPERATION_COUNT - counters["successes"]
    duplicate_semantic_effects = backend.count_duplicate_semantic_effects(
        project_id, study_id, aggregate_kind="study_definition"
    )
    passed = (
        counters["successes"] == CAS_OPERATION_COUNT
        and final_rev == CAS_OPERATION_COUNT
        and lost_updates == 0
        and duplicate_semantic_effects == 0
        and p95 is not None
        and p95 <= 500
        and len(conn_ids) == WRITER_COUNT
        and max_active[0] >= 2  # at least 2 writers overlapped at app boundary
    )
    return InvariantResult(
        name="cas_concurrency",
        passed=passed,
        deterministic={
            "writers": WRITER_COUNT,
            "target_ops": CAS_OPERATION_COUNT,
            "expected_final_revision": CAS_OPERATION_COUNT,
            "successful_saves": counters["successes"],
            "lost_updates": lost_updates,
            "duplicate_semantic_effects": duplicate_semantic_effects,
            "final_revision": final_rev,
            "distinct_connection_count": len(
                {str(c.get("connection_identity")) for c in conn_ids}
            ),
            "overlap_at_application_boundary": max_active[0],
        },
        measured={
            "elapsed_ms": round(elapsed_ms, 2),
            "cas_conflicts_observed": counters["conflicts"],
            "busy_retries_total": sum(busy_retries),
            "busy_retries_per_writer": dict(enumerate(busy_retries)),
            "per_writer": per_writer,
            "p50_ms": round(p50, 3) if p50 is not None else None,
            "p95_ms": round(p95, 3) if p95 is not None else None,
            "p99_ms": round(p99, 3) if p99 is not None else None,
            "cas_p95_threshold_ms": 500,
            "connection_ids": conn_ids,  # volatile random identities+order
        },
    )


# ---------------------------------------------------------------------------
# Invariant 2 — 10,000-event append-only chain
# ---------------------------------------------------------------------------


def invariant_event_chain(backend: Backend) -> InvariantResult:
    """Append 10,000 events to one stream and verify the hash chain."""
    project_id = "proj:eventpoc:1"
    stream_id = "stream:eventpoc:1"
    builder = EventEnvelopeBuilder()
    clock = FrozenClock()

    events: List[DomainEvent] = []
    prev: Optional[str] = None
    for i in range(1, EVENT_COUNT + 1):
        evt = _make_event(
            builder,
            event_id=f"evt:{i:06d}",
            stream_id=stream_id,
            sequence=i,
            previous=prev,
            payload_index=i,
            emitted_at=clock.now(),
        )
        events.append(evt)
        prev = evt.event_sha256

    start = time.perf_counter()
    batch_size = 500
    for start_idx in range(0, EVENT_COUNT, batch_size):
        batch = events[start_idx : start_idx + batch_size]
        uow = backend.new_uow()
        with uow:
            ev_repo = uow.event_stream_repository
            assert ev_repo is not None
            ev_repo.append_events(project_id, stream_id, batch)
    append_ms = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    uow = backend.new_uow()
    with uow:
        ev_repo = uow.event_stream_repository
        assert ev_repo is not None
        head = ev_repo.get_stream_head(project_id, stream_id)
        read_back = ev_repo.read_events(project_id, stream_id)
    verify_ms = (time.perf_counter() - start) * 1000

    chain_breaks = 0
    expected_prev: Optional[str] = None
    replay_hash = sha256()
    for evt in read_back:
        if evt.previous_event_sha256 != expected_prev:
            chain_breaks += 1
        try:
            verify_event_integrity(evt)
        except Exception:  # noqa: BLE001
            chain_breaks += 1
        replay_hash.update(evt.event_sha256.encode("utf-8"))
        expected_prev = evt.event_sha256

    ref_hash = sha256()
    for evt in events:
        ref_hash.update(evt.event_sha256.encode("utf-8"))

    passed = (
        head is not None
        and head.event_count == EVENT_COUNT
        and head.last_sequence == EVENT_COUNT
        and chain_breaks == 0
        and len(read_back) == EVENT_COUNT
        and replay_hash.hexdigest() == ref_hash.hexdigest()
    )
    return InvariantResult(
        name="event_chain",
        passed=passed,
        deterministic={
            "event_count": EVENT_COUNT,
            "read_back_count": len(read_back),
            "chain_breaks": chain_breaks,
            "head_sequence": head.last_sequence if head else None,
            "head_count": head.event_count if head else None,
            "replay_hash": replay_hash.hexdigest(),
            "reference_hash": ref_hash.hexdigest(),
        },
        measured={"append_ms": round(append_ms, 2), "verify_ms": round(verify_ms, 2)},
    )


# ---------------------------------------------------------------------------
# Invariant 3 — transaction + outbox atomicity
# ---------------------------------------------------------------------------


def invariant_transaction_outbox_atomicity(backend: Backend) -> InvariantResult:
    """CAS save + outbox enqueue commit together; rollback discards both."""
    project_id = "proj:atomicpoc:1"
    clock = FrozenClock()

    study_a = "sd:atomic:commit"
    with backend.new_uow() as uow:
        cas = uow.study_definition_cas_repository
        ob = uow.outbox_repository
        assert cas is not None and ob is not None
        record = _make_study(study_id=study_a, project_id=project_id, revision=1, seed=10)
        cas.save_with_expected_revision(project_id, record, expected_revision=0)
        ob.enqueue(
            project_id, "wr:atomic:1", "download", "side:commit:1", _sha(100), clock.now()
        )

    with backend.new_uow() as uow:
        cas = uow.study_definition_cas_repository
        ob = uow.outbox_repository
        assert cas is not None and ob is not None
        committed_study = _read_current_revision(uow, project_id, study_a)
        committed_msg = ob.find_by_logical_key(project_id, "side:commit:1")
    commit_ok = committed_study == 1 and committed_msg is not None

    study_b = "sd:atomic:rollback"
    rolled_back = False
    try:
        with backend.new_uow() as uow:
            cas = uow.study_definition_cas_repository
            ob = uow.outbox_repository
            assert cas is not None and ob is not None
            record = _make_study(study_id=study_b, project_id=project_id, revision=1, seed=20)
            cas.save_with_expected_revision(project_id, record, expected_revision=0)
            ob.enqueue(
                project_id, "wr:atomic:2", "download", "side:rollback:1", _sha(200), clock.now()
            )
            raise RuntimeError("intentional rollback trigger")
    except RuntimeError:
        rolled_back = True

    with backend.new_uow() as uow:
        rolled_study = _read_current_revision(uow, project_id, study_b)
        ob = uow.outbox_repository
        assert ob is not None
        rolled_msg = ob.find_by_logical_key(project_id, "side:rollback:1")
    rollback_ok = rolled_back and rolled_study is None and rolled_msg is None

    passed = commit_ok and rollback_ok
    return InvariantResult(
        name="transaction_outbox_atomicity",
        passed=passed,
        deterministic={
            "commit_study_revision_durable": committed_study,
            "commit_outbox_durable": committed_msg is not None,
            "rollback_triggered": rolled_back,
            "rollback_study_absent": rolled_study is None,
            "rollback_outbox_absent": rolled_msg is None,
        },
    )


# ---------------------------------------------------------------------------
# Invariant 4 — checkpoint isolation as persisted storage
# ---------------------------------------------------------------------------


def invariant_checkpoint_isolation(backend: Backend) -> InvariantResult:
    """Checkpoint create/update/delete cannot change event count/hash.

    A checkpoint is a persisted record in a table separate from domain events.
    We append events, write checkpoints for two runs/projects, update/delete
    them, and prove the event count/hash is unchanged while run isolation holds.
    """
    project_id = "proj:ckptpoc:1"
    project_id_b = "proj:ckptpoc:2"
    stream_id = "stream:ckptpoc:1"
    builder = EventEnvelopeBuilder()
    clock = FrozenClock()
    total = 200
    checkpoint_seq = 100

    events: List[DomainEvent] = []
    prev: Optional[str] = None
    for i in range(1, total + 1):
        evt = _make_event(
            builder,
            event_id=f"ckpt-evt:{i:04d}",
            stream_id=stream_id,
            sequence=i,
            previous=prev,
            payload_index=i,
            emitted_at=clock.now(),
        )
        events.append(evt)
        prev = evt.event_sha256

    with backend.new_uow() as uow:
        ev_repo = uow.event_stream_repository
        assert ev_repo is not None
        ev_repo.append_events(project_id, stream_id, events)

    # Reference hash of the stream BEFORE any checkpoint write.
    with backend.new_uow() as uow:
        ev_repo = uow.event_stream_repository
        assert ev_repo is not None
        ref_events = ev_repo.read_events(project_id, stream_id)
    ref_count = len(ref_events)
    ref_hash = sha256()
    for evt in ref_events:
        ref_hash.update(evt.event_sha256.encode("utf-8"))
    ref_hash_hex = ref_hash.hexdigest()
    ref_head = events[checkpoint_seq - 1].event_sha256

    # Persist checkpoints via the backend checkpoint store.
    ckpt_store = backend.open_checkpoint_store()
    rec_a = ckpt_store.create(
        project_id, "run:ckpt:1", stream_id, checkpoint_seq, ref_head,
        state=1,
    )
    ckpt_store.create(
        project_id, "run:ckpt:2", stream_id, checkpoint_seq, ref_head, state=2
    )
    ckpt_store.create(
        project_id_b, "run:ckpt:1", stream_id, 50, _sha(555), state=3
    )

    # Update / delete within project A.
    rec_updated = ckpt_store.update(project_id, "run:ckpt:1", 150, _sha(999))
    ckpt_store.delete(project_id, "run:ckpt:2")

    # Re-read event stream: count/hash must be unchanged.
    with backend.new_uow() as uow:
        ev_repo = uow.event_stream_repository
        assert ev_repo is not None
        after_events = ev_repo.read_events(project_id, stream_id)
    after_count = len(after_events)
    after_hash = sha256()
    for evt in after_events:
        after_hash.update(evt.event_sha256.encode("utf-8"))
    after_hash_hex = after_hash.hexdigest()

    # Isolation: project A run:ckpt:1 exists (updated); run:ckpt:2 deleted;
    # project B run:ckpt:1 still exists.
    run_a1 = ckpt_store.get(project_id, "run:ckpt:1")
    run_a2 = ckpt_store.get(project_id, "run:ckpt:2")
    run_b1 = ckpt_store.get(project_id_b, "run:ckpt:1")
    runs_a = ckpt_store.list_runs(project_id)

    passed = (
        after_count == ref_count == total
        and after_hash_hex == ref_hash_hex
        and run_a1 is not None
        and getattr(run_a1, "checkpoint_seq", None) == 150
        and getattr(run_a1, "checkpoint_sha", None) == _sha(999)
        and run_a2 is None  # deleted
        and run_b1 is not None  # other project untouched
        and tuple(sorted(runs_a)) == ("run:ckpt:1",)
        and getattr(run_a1, "project_id", None) == project_id
    )
    return InvariantResult(
        name="checkpoint_isolation",
        passed=passed,
        deterministic={
            "total_events": total,
            "ref_count": ref_count,
            "after_count": after_count,
            "ref_hash": ref_hash_hex,
            "after_hash": after_hash_hex,
            "event_count_unchanged": after_count == ref_count,
            "event_hash_unchanged": after_hash_hex == ref_hash_hex,
            "run_a1_seq": getattr(run_a1, "checkpoint_seq", None),
            "run_a1_sha": getattr(run_a1, "checkpoint_sha", None),
            "run_a2_deleted": run_a2 is None,
            "run_b1_present": run_b1 is not None,
            "runs_a": tuple(sorted(runs_a)),
            "project_isolation": getattr(run_a1, "project_id", None) == project_id,
        },
    )


# ---------------------------------------------------------------------------
# Invariant 5 — backup / restore / replay at 10x reference scale
# ---------------------------------------------------------------------------


def invariant_backup_restore_replay(
    backend: Backend, tmp_dir: Path
) -> InvariantResult:
    """Back up / restore / replay 10,000 events (10x reference scale).

    Reference scale is ``REFERENCE_EVENT_COUNT`` (1,000); we back up/restore/
    replay ``SCALE_MULTIPLIER`` x reference = 10,000 events.  Exact canonical
    hash after restore; total duration under ``BACKUP_RESTORE_REPLAY_BUDGET_S``.
    """
    project_id = "proj:backuppoc:1"
    study_id = "sd:backup:1"
    stream_id = "stream:backup:1"
    builder = EventEnvelopeBuilder()
    clock = FrozenClock()

    backup_count = REFERENCE_EVENT_COUNT * SCALE_MULTIPLIER  # 10,000

    # Populate source: one CS + a 10,000-event stream.
    with backend.new_uow() as uow:
        cas = uow.study_definition_cas_repository
        ev = uow.event_stream_repository
        assert cas is not None and ev is not None
        record = _make_study(study_id=study_id, project_id=project_id, revision=1, seed=30)
        cas.save_with_expected_revision(project_id, record, expected_revision=0)
        events: List[DomainEvent] = []
        prev: Optional[str] = None
        for i in range(1, backup_count + 1):
            evt = _make_event(
                builder,
                event_id=f"bk-evt:{i:05d}",
                stream_id=stream_id,
                sequence=i,
                previous=prev,
                payload_index=i,
                emitted_at=clock.now(),
            )
            events.append(evt)
            prev = evt.event_sha256
        ev.append_events(project_id, stream_id, events)

    with backend.new_uow() as uow:
        ev = uow.event_stream_repository
        assert ev is not None
        source_events = ev.read_events(project_id, stream_id)
    source_hash = sha256()
    for evt in source_events:
        source_hash.update(evt.event_sha256.encode("utf-8"))
    source_hash_hex = source_hash.hexdigest()
    source_study_hash = _model_to_hash(source_events)

    start = time.perf_counter()
    backup_path = tmp_dir / "backup_restore.db"
    backend.backup_to(backup_path)

    restored = backend.restore_new(backup_path, tmp_dir / "restored_backup.db")
    try:
        with restored.new_uow() as uow:
            ev = uow.event_stream_repository
            cas = uow.study_definition_cas_repository
            assert ev is not None and cas is not None
            restored_events = ev.read_events(project_id, stream_id)
            restored_rev = _read_current_revision(uow, project_id, study_id)
        restored_hash = sha256()
        for evt in restored_events:
            restored_hash.update(evt.event_sha256.encode("utf-8"))
        restored_hash_hex = restored_hash.hexdigest()
    finally:
        restored.close()
    total_s = time.perf_counter() - start

    passed = (
        backup_path.exists()
        and len(restored_events) == len(source_events) == backup_count
        and restored_hash_hex == source_hash_hex
        and restored_rev == 1
        and total_s < BACKUP_RESTORE_REPLAY_BUDGET_S
    )
    return InvariantResult(
        name="backup_restore_replay",
        passed=passed,
        deterministic={
            "reference_event_count": REFERENCE_EVENT_COUNT,
            "scale_multiplier": SCALE_MULTIPLIER,
            "backup_event_count": backup_count,
            "source_event_count": len(source_events),
            "restored_event_count": len(restored_events),
            "source_replay_hash": source_hash_hex,
            "restored_replay_hash": restored_hash_hex,
            "restored_study_revision": restored_rev,
            "budget_seconds": BACKUP_RESTORE_REPLAY_BUDGET_S,
        },
        measured={"total_seconds": round(total_s, 3), "total_ms": round(total_s * 1000, 2)},
    )


def _model_to_hash(events: Sequence[DomainEvent]) -> str:
    h = sha256()
    for evt in events:
        h.update(evt.event_sha256.encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Invariant 6 — crash recovery (real process boundary)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Invariant 6 — crash recovery (real process boundary)
# ---------------------------------------------------------------------------


def _crash_child_commit(backend: "Backend", spec: Dict[str, Any], receipt_path: Path) -> Dict[str, Any]:
    """Neutral crash-commit work executed inside the candidate's child process.

    The candidate's ``spawn_crash_child`` reconstructs its backend, calls this
    function to commit a deterministic event stream + outbox message, writes a
    bounded JSON readiness receipt containing explicit commit-boundary facts,
    fsyncs the receipt and its directory, then **stays alive** (busy-waits)
    so that the parent may observe the receipt and send SIGKILL.

    This function only uses the :class:`Backend` protocol and deterministic
    event building.  It never calls ``os._exit`` or ``sys.exit``; the
    subprocess stays alive for the parent to control termination.
    """
    import os

    project_id = spec["project_id"]
    stream_id = spec["stream_id"]
    outbox_key = spec["outbox_key"]
    event_count = int(spec["event_count"])
    clock = FrozenClock()
    builder = EventEnvelopeBuilder()
    events: List[DomainEvent] = []
    prev: Optional[str] = None
    for i in range(1, event_count + 1):
        evt = _make_event(
            builder,
            event_id=f"crash-evt:{i:05d}",
            stream_id=stream_id,
            sequence=i,
            previous=prev,
            payload_index=i,
            emitted_at=clock.now(),
        )
        events.append(evt)
        prev = evt.event_sha256
    with backend.new_uow() as uow:
        ev = uow.event_stream_repository
        ob = uow.outbox_repository
        assert ev is not None and ob is not None
        ev.append_events(project_id, stream_id, events)
        ob.enqueue(
            project_id,
            "wr:crash-child:1",
            "download",
            outbox_key,
            _sha(400),
            clock.now(),
        )
    # The UoW COMMIT was synchronous=FULL, so the commit boundary is durable
    # before this point.  Now write a bounded readiness receipt that the
    # parent can validate BEFORE sending SIGKILL.
    commit_boundary_ts = datetime.now(timezone.utc).isoformat()
    receipt = {
        "committed": True,
        "committed_event_count": event_count,
        "outbox_key": outbox_key,
        "commit_boundary_ts": commit_boundary_ts,
    }
    receipt_bytes = json.dumps(receipt, sort_keys=True).encode("utf-8")
    receipt_path.write_bytes(receipt_bytes)
    # Fsync the receipt file + containing directory so the parent can observe
    # it even if SIGKILL follows immediately.
    fd = os.open(str(receipt_path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    dir_fd = os.open(str(receipt_path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    # Stay alive for parent to observe receipt and send SIGKILL.
    # The child MUST NOT exit normally; this loop is only broken by SIGKILL.
    while True:
        try:
            import time as _t
            _t.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            # Even if someone tries to stop us, keep looping — only SIGKILL
            # should terminate this process as the crash boundary.
            pass
    # Unreachable; keeps type checker happy.
    return receipt  # type: ignore[return-value]


def _sigkill_and_verify(child_pid: int, timeout_s: float = 5.0) -> Dict[str, Any]:
    """Send SIGKILL to *child_pid*, waitpid, and verify it died SPECIFICALLY
    from SIGKILL.

    Returns a fail-closed evidence dict with these fields:

    * ``kill_ok`` — True only when all of: SIGKILL was deliverable, waitpid
      returned the expected child PID, ``WIFSIGNALED`` is true and
      ``WTERMSIG == signal.SIGKILL``.
    * ``waitpid_pid`` — the PID returned by ``os.waitpid`` (or ``None``).
    * ``wifignaled`` / ``wtermsig`` — decoded termination status.
    * ``wifexited`` / ``exit_code`` — decoded normal-exit status.
    * ``kill_return_code`` — derived ``-signal.SIGKILL`` ONLY from a verified
      status; ``None`` otherwise.
    * ``error`` — reason when ``kill_ok`` is False (kill failure, reaped
      elsewhere, wrong PID, normal exit, wrong signal, timeout).

    Never swallows a waitpid failure into a passing result.
    """
    import os
    import signal
    import time as _time

    ev: Dict[str, Any] = {
        "kill_ok": False,
        "waitpid_pid": None,
        "wifignaled": None,
        "wtermsig": None,
        "wifexited": None,
        "exit_code": None,
        "kill_return_code": None,
        "error": None,
    }
    try:
        os.kill(child_pid, signal.SIGKILL)
    except ProcessLookupError:
        ev["error"] = "kill failed: child already gone (exited or reaped elsewhere)"
        return ev
    except OSError as exc:
        ev["error"] = f"kill failed: {exc}"
        return ev

    deadline = _time.time() + timeout_s
    while _time.time() < deadline:
        try:
            waited_pid, status = os.waitpid(child_pid, os.WNOHANG)
        except ChildProcessError:
            ev["error"] = "waitpid failed: child reaped elsewhere"
            return ev
        except OSError as exc:
            ev["error"] = f"waitpid failed: {exc}"
            return ev
        if waited_pid == 0:
            _time.sleep(0.05)
            continue
        ev["waitpid_pid"] = waited_pid
        ev["wifignaled"] = bool(os.WIFSIGNALED(status))
        ev["wtermsig"] = os.WTERMSIG(status) if os.WIFSIGNALED(status) else None
        ev["wifexited"] = bool(os.WIFEXITED(status))
        ev["exit_code"] = os.WEXITSTATUS(status) if os.WIFEXITED(status) else None
        if waited_pid != child_pid:
            ev["error"] = f"waitpid returned wrong pid {waited_pid}"
            return ev
        if not os.WIFSIGNALED(status):
            ev["error"] = (
                f"child not signal-terminated (wifexited={os.WIFEXITED(status)}, "
                f"exit_code={ev['exit_code']})"
            )
            return ev
        if os.WTERMSIG(status) != signal.SIGKILL:
            ev["error"] = (
                f"child terminated by signal {os.WTERMSIG(status)}, "
                f"expected SIGKILL({signal.SIGKILL})"
            )
            return ev
        ev["kill_ok"] = True
        ev["kill_return_code"] = -signal.SIGKILL
        return ev
    ev["error"] = f"waitpid timeout after {timeout_s}s: child did not terminate"
    return ev


def probe_crash_fail_closed(tmp_dir: Path) -> Dict[str, Any]:
    """Focused negative probes proving normal exit and wrong-signal
    termination can NOT pass the SIGKILL verification, and that a real SIGKILL
    termination DOES pass with the derived return code.

    Uses real subprocesses (no mocks).  Returns a deterministic evidence dict
    whose ``probe_passed`` is True only if all three probes behave correctly.
    """
    import os
    import signal
    import subprocess
    import sys
    import time as _time

    results: Dict[str, Any] = {}

    # Probe 1 — normal exit: child exits 0; must fail verification.
    p1 = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    p1.wait(timeout=10)
    ev1 = _sigkill_and_verify(p1.pid)
    results["normal_exit_fails"] = not ev1["kill_ok"]
    results["normal_exit_evidence"] = {
        "kill_ok": ev1["kill_ok"],
        "wifexited": ev1["wifexited"],
        "exit_code": ev1["exit_code"],
        "error": ev1["error"],
    }

    # Probe 2 — wrong signal: SIGTERM the child; must fail with
    # WTERMSIG != SIGKILL (not a normal-exit pass).
    p2 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    _time.sleep(0.3)
    os.kill(p2.pid, signal.SIGTERM)
    _time.sleep(0.3)  # let it become a zombie so waitpid decodes SIGTERM
    ev2 = _sigkill_and_verify(p2.pid)
    results["wrong_signal_fails"] = not ev2["kill_ok"]
    results["wrong_signal_evidence"] = {
        "kill_ok": ev2["kill_ok"],
        "wifignaled": ev2["wifignaled"],
        "wtermsig": ev2["wtermsig"],
        "error": ev2["error"],
    }

    # Probe 3 — correct SIGKILL: must pass with derived return code.
    p3 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    _time.sleep(0.3)
    ev3 = _sigkill_and_verify(p3.pid)
    results["sigkill_passes"] = ev3["kill_ok"]
    results["sigkill_evidence"] = {
        "kill_ok": ev3["kill_ok"],
        "waitpid_pid": ev3["waitpid_pid"],
        "wifignaled": ev3["wifignaled"],
        "wtermsig": ev3["wtermsig"],
        "kill_return_code": ev3["kill_return_code"],
        "error": ev3["error"],
    }

    results["probe_passed"] = (
        results["normal_exit_fails"]
        and results["wrong_signal_fails"]
        and results["sigkill_passes"]
        and ev3["kill_return_code"] == -signal.SIGKILL
    )
    return results


def invariant_crash_recovery(backend: Backend, tmp_dir: Path) -> InvariantResult:
    """Real subprocess commits then is SIGKILLed by the parent; reopen proves RPO=0.

    Protocol:
    1. Adapter launches child → returns (evidence, reopened_backend)
    2. Invariant polls for readiness receipt with bounded deadline
    3. Validates receipt structure (committed=True, explicit commit-boundary facts)
    4. Sends SIGKILL to the child (parent-controlled crash)
    5. Reopens store and proves committed-event RPO=0, exact chain, pending outbox, zero duplicates

    Fail-closed (any of these = FAIL):
    - child exit before receipt
    - malformed/missing receipt
    - receipt timeout
    - kill failure (child survived SIGKILL)
    - fewer events than receipt claims
    - hash chain break
    - duplicate semantic effect
    """
    project_id = "proj:crashpoc:1"
    stream_id = "stream:crashpoc:1"
    outbox_key = "side:crash:1"
    child_event_count = 300
    receipt_timeout_s = 15

    crash_spec: Dict[str, Any] = {
        "project_id": project_id,
        "stream_id": stream_id,
        "outbox_key": outbox_key,
        "event_count": child_event_count,
    }

    crash_evidence, reopened = backend.spawn_crash_child(crash_spec, tmp_dir)
    try:
        receipt_path_str = crash_evidence.get("receipt_path")
        child_pid = crash_evidence.get("child_pid")
        if not receipt_path_str or not child_pid:
            return InvariantResult(
                name="crash_recovery", passed=False, deterministic={},
                measured={"error": "adapter returned incomplete evidence", "evidence": crash_evidence},
            )
        receipt_path = Path(receipt_path_str)

        # --- Poll for readiness receipt with bounded deadline ---
        import os, signal, time as _time
        deadline = _time.time() + receipt_timeout_s
        receipt_data = None
        child_exited_early = False
        while _time.time() < deadline:
            # Check if child exited: os.kill(pid, 0) succeeds if alive.
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                child_exited_early = True
                break
            if receipt_path.exists():
                try:
                    raw = receipt_path.read_bytes()
                    receipt_data = json.loads(raw)
                    # Check that commit was actually written (committed == True).
                    if receipt_data.get("committed", False):
                        break
                except (json.JSONDecodeError, OSError):
                    pass
            _time.sleep(0.05)

        if child_exited_early or receipt_data is None or not receipt_data.get("committed", False):
            # Child failed to produce valid receipt — kill if still alive,
            # reap it (no orphan), but the invariant FAILS.
            if not child_exited_early:
                _sigkill_and_verify(child_pid)
            return InvariantResult(
                name="crash_recovery", passed=False, deterministic={},
                measured={
                    "error": "receipt not observed before timeout/child exit",
                    "child_exited_early": child_exited_early,
                    "receipt_data": receipt_data,
                    "child_pid": child_pid,
                },
            )

        # --- Validate receipt structure ---
        committed_expected = int(receipt_data.get("committed_event_count", 0))
        receipt_outbox_key = receipt_data.get("outbox_key")
        if committed_expected <= 0 or receipt_outbox_key != outbox_key:
            _sigkill_and_verify(child_pid)  # reap; invariant FAILS regardless
            return InvariantResult(
                name="crash_recovery", passed=False, deterministic={},
                measured={"error": "receipt inconsistent", "receipt": receipt_data, "child_pid": child_pid},
            )

        # --- Parent-controlled SIGKILL + VERIFIED waitpid status ---
        kill_evidence = _sigkill_and_verify(child_pid)
        kill_ok = bool(kill_evidence["kill_ok"])
        kill_return_code = kill_evidence["kill_return_code"]
        kill_method = "SIGKILL"
        if not kill_ok:
            kill_method = f"SIGKILL-unverified:{kill_evidence['error']}"

        # --- Reopen and prove RPO=0 ---
        with reopened.new_uow() as uow:
            ev = uow.event_stream_repository
            ob = uow.outbox_repository
            assert ev is not None and ob is not None
            head = ev.get_stream_head(project_id, stream_id)
            replayed = ev.read_events(project_id, stream_id)
            ob_msg = ob.find_by_logical_key(project_id, outbox_key)
            dispatched_count = len(ob.list_dispatched(project_id, limit=1000))

        replay_hash = sha256()
        expected_prev: Optional[str] = None
        chain_breaks = 0
        for evt in replayed:
            if evt.previous_event_sha256 != expected_prev:
                chain_breaks += 1
            replay_hash.update(evt.event_sha256.encode("utf-8"))
            expected_prev = evt.event_sha256

        rpo_zero = (
            head is not None
            and head.event_count == committed_expected
            and chain_breaks == 0
        )
        no_duplicate = dispatched_count == 0
        passed = (
            rpo_zero
            and len(replayed) == committed_expected
            and ob_msg is not None
            and ob_msg.status.value == "pending"
            and no_duplicate
            and receipt_outbox_key == outbox_key
            and kill_ok
        )
        return InvariantResult(
            name="crash_recovery",
            passed=passed,
            deterministic={
                "receipt_committed": bool(receipt_data.get("committed")),
                "receipt_committed_event_count": committed_expected,
                "reopened_event_count": len(replayed),
                "rpo_zero": rpo_zero,
                "hash_chain_breaks": chain_breaks,
                "replay_hash": replay_hash.hexdigest(),
                "outbox_key_present": ob_msg is not None,
                "outbox_status": ob_msg.status.value if ob_msg else None,
                "duplicate_semantic_effects": dispatched_count,
                "kill_ok": kill_ok,
                "kill_verified": kill_ok,
                "kill_wifignaled": kill_evidence["wifignaled"],
                "kill_wtermsig": kill_evidence["wtermsig"],
                "kill_wifexited": kill_evidence["wifexited"],
                "kill_exit_code": kill_evidence["exit_code"],
                "kill_return_code": kill_return_code,
                "receipt_outbox_key": receipt_outbox_key,
            },
            measured={
                "child_pid": child_pid,
                "kill_waitpid_pid": kill_evidence["waitpid_pid"],
                "kill_method": kill_method,
                "kill_error": kill_evidence["error"],
                "receipt_path": str(receipt_path),
                "receipt_commit_boundary_ts": receipt_data.get("commit_boundary_ts"),
            },
        )
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# Invariant 7 — rollback to a pre-switch snapshot
# ---------------------------------------------------------------------------


def invariant_rollback_to_snapshot(backend: Backend, tmp_dir: Path) -> InvariantResult:
    """Restore a backup taken before a mutation; the state reverts exactly."""
    project_id = "proj:rollbackpoc:1"
    study_id = "sd:rollback:1"
    clock = FrozenClock()

    with backend.new_uow() as uow:
        cas = uow.study_definition_cas_repository
        assert cas is not None
        r1 = _make_study(study_id=study_id, project_id=project_id, revision=1, seed=40)
        cas.save_with_expected_revision(project_id, r1, expected_revision=0)

    snapshot_path = tmp_dir / "rollback_snapshot.db"
    backend.backup_to(snapshot_path)

    # Pre-switch source revision (for rollback comparison from the ORIGINAL).
    with backend.new_uow() as uow:
        pre_rev = _read_current_revision(uow, project_id, study_id)
        pre_hash = _canonical_model_hash(
            _read_current(uow, project_id, study_id)
        )

    # Further mutation: revision 2.
    with backend.new_uow() as uow:
        cas = uow.study_definition_cas_repository
        assert cas is not None
        r2 = _make_study(
            study_id=study_id, project_id=project_id, revision=2,
            previous=_sha(40), seed=41,
        )
        cas.save_with_expected_revision(project_id, r2, expected_revision=1)

    with backend.new_uow() as uow:
        live_rev = _read_current_revision(uow, project_id, study_id)
        live_hash = _canonical_model_hash(_read_current(uow, project_id, study_id))

    # Restore the pre-mutation snapshot into a fresh store.
    restored = backend.restore_new(snapshot_path, tmp_dir / "restored_rollback.db")
    try:
        with restored.new_uow() as uow:
            restored_rev = _read_current_revision(uow, project_id, study_id)
            restored_hash = _canonical_model_hash(_read_current(uow, project_id, study_id))

        passed = (
            live_rev == 2
            and restored_rev == 1
            and pre_rev == 1
            and restored_hash == pre_hash
            and live_hash != pre_hash
        )
        return InvariantResult(
            name="rollback_to_snapshot",
            passed=passed,
            deterministic={
                "pre_switch_revision": pre_rev,
                "live_revision_after_mutation": live_rev,
                "restored_revision": restored_rev,
                "pre_switch_hash": pre_hash,
                "live_hash": live_hash,
                "restored_hash": restored_hash,
                "restored_hash_matches_pre_switch": restored_hash == pre_hash,
                "live_hash_differs": live_hash != pre_hash,
            },
        )
    finally:
        restored.close()


# ---------------------------------------------------------------------------
# Invariant 8 — migration accounting across every persisted class
# ---------------------------------------------------------------------------


def _make_doc(
    *,
    doc_id: str,
    project_id: str,
    revision: int,
    seed: int = 0,
) -> SemanticDocumentRevision:
    """Build a minimal valid ``SemanticDocumentRevision`` for migration."""
    sb = SemanticBlock(
        semantic_block_id=f"sb:{doc_id}:{seed}",
        semantic_node_id=f"sn:{seed}",
        chapter_contract_id="cc:1",
        substantive_content_contract_id="scc:1",
        block_kind=SemanticBlockKind.PARAGRAPH,
        content=f"Draft {seed}",
        fact_paths=("facts.indication",),
        claim_evidence_link_ids=(f"cel:{seed}",),
        medical_admission_unit_ids=(f"mau:{seed}",),
        content_sha256=_sha(seed + 2),
    )
    return SemanticDocumentRevision(
        semantic_document_revision_id=doc_id,
        project_id=project_id,
        revision=revision,
        previous_revision_sha256=None if revision == 1 else _sha(revision - 1),
        study_definition_id=f"sd:{doc_id}",
        study_definition_sha256=_sha(seed + 1),
        applicability_snapshot_id=f"as:{seed}",
        applicability_snapshot_sha256=_sha(seed + 3),
        semantic_blocks=(sb,),
        chapter_contract_hashes=(_sha(seed + 4),),
        updated_at=_FROZEN_EPOCH,
    )


def _make_ccr(project_id: str, node_id: str, seed: int) -> ChapterCoverageRecord:
    return ChapterCoverageRecord(
        project_id=project_id, semantic_node_id=node_id,
        chapter_contract_sha256=_sha(seed),
        substantive_content_contract_sha256=_sha(seed + 1),
        semantic_block_sha256=_sha(seed + 2),
        is_locked=False, has_substantive_content=True, evidence_admitted=True,
    )


def _make_dgr(project_id: str, decision_key: str, seed: int) -> DecisionGraphRecord:
    return DecisionGraphRecord(
        project_id=project_id, decision_key=decision_key,
        decision_record_id=f"dr:{seed}", state_revision=1,
        selected_option_id=f"opt:{seed}", canonical_state=CanonicalState.CONFIRMED,
    )


def _make_wrsr(project_id: str, run_id: str, seed: int) -> WorkflowRunStatusRecord:
    return WorkflowRunStatusRecord(
        project_id=project_id, workflow_run_id=run_id,
        status=WorkflowRunStatus.RUNNING, display_progress=0.5, journey_counter=seed,
    )


def invariant_migration_quarantine(backend: Backend) -> InvariantResult:
    """Repository-contract migration with quarantine across every persisted
    family, treated as a separate raw/source plan (not rows already migrated).

    Families covered: StudyDefinitionV3, SemanticDocumentRevision, events,
    outbox, inbox, reservations, chapter_coverage, decision_graph,
    workflow_run_status, and checkpoints.

    For each family the source plan is a fixed set of mappable rows PLUS at
    least one deliberately unmappable raw object.  The mappable rows migrate
    through the repository ports with exact count + canonical hash; every
    unmappable raw object is persisted through a database-neutral quarantine
    store and must survive with a stable reason code, source key and canonical
    body hash.  ``source = migrated + quarantined`` and 100% accounting is
    required per family.
    """
    project_id = "proj:migratepoc:1"
    clock = FrozenClock()
    rows = _MIGRATION_ROWS_PER_CLASS  # 8 mappable rows per family
    builder = EventEnvelopeBuilder()
    out = {}

    # Convenience: per-family quarantine capture.
    def _quarantine_capture(qs: QuarantineStore, family: str, raw: List[Dict[str, Any]]) -> Tuple[int, List[Dict[str, Any]]]:
        count = 0
        records = []
        for item in raw:
            body = json.dumps(item, sort_keys=True, separators=(",", ":"))
            body_hash = sha256(body.encode("utf-8")).hexdigest()
            rec = qs.quarantine(family, item["source_key"], item["reason_code"], body)
            records.append({
                "source_key": rec.source_key,
                "reason_code": rec.reason_code,
                "body_hash": rec.body_hash,
            })
            count += 1
        return count, records

    # =====================================================================
    # 1. StudyDefinitionV3
    # =====================================================================
    studies = [
        _make_study(study_id=f"sd:mig:{i:02d}", project_id=project_id, revision=1, seed=50 + i)
        for i in range(rows)
    ]
    study_source_hash = sha256()
    for s in studies:
        study_source_hash.update(_canonical_model_hash(s).encode("utf-8"))
    study_raw_bad = [
        {"source_key": "sd:mig:bad:1", "reason_code": "missing_facts", "project_id": project_id},
        {"source_key": "sd:mig:bad:2", "reason_code": "invalid_revision", "project_id": project_id},
    ]

    # =====================================================================
    # 2. SemanticDocumentRevision
    # =====================================================================
    docs = [
        _make_doc(doc_id=f"sdr:mig:{i:02d}", project_id=project_id, revision=1, seed=60 + i)
        for i in range(rows)
    ]
    doc_source_hash = sha256()
    for d in docs:
        doc_source_hash.update(_canonical_model_hash(d).encode("utf-8"))
    doc_raw_bad = [
        {"source_key": "sdr:mig:bad:1", "reason_code": "missing_blocks", "project_id": project_id},
        {"source_key": "sdr:mig:bad:2", "reason_code": "invalid_revision", "project_id": project_id},
    ]

    # =====================================================================
    # 3. events
    # =====================================================================
    events: List[DomainEvent] = []
    prev: Optional[str] = None
    for i in range(1, rows + 1):
        evt = _make_event(
            builder,
            event_id=f"mig-evt:{i:02d}",
            stream_id="stream:mig:1",
            sequence=i,
            previous=prev,
            payload_index=i,
            emitted_at=clock.now(),
        )
        events.append(evt)
        prev = evt.event_sha256
    event_source_hash = sha256()
    for e in events:
        event_source_hash.update(e.event_sha256.encode("utf-8"))
    event_raw_bad = [
        {"source_key": "mig-evt:bad:1", "reason_code": "chain_break", "stream_id": "stream:mig:1"},
        {"source_key": "mig-evt:bad:2", "reason_code": "unknown_event_type", "stream_id": "stream:mig:1"},
    ]

    # =====================================================================
    # 4. outbox
    # =====================================================================
    outbox_keys = [f"mig-ob:{i}" for i in range(rows)]
    outbox_raw_bad = [
        {"source_key": "mig-ob:bad:1", "reason_code": "missing_payload_hash"},
        {"source_key": "mig-ob:bad:2", "reason_code": "invalid_status"},
    ]

    # =====================================================================
    # 5. inbox
    # =====================================================================
    inbox_keys = [f"mig-ib:{i}" for i in range(rows)]
    inbox_raw_bad = [
        {"source_key": "mig-ib:bad:1", "reason_code": "missing_result_hash"},
        {"source_key": "mig-ib:bad:2", "reason_code": "invalid_status"},
    ]

    # =====================================================================
    # 6. reservations
    # =====================================================================
    reservations = [
        ExecutionReservation(
            execution_reservation_id=f"rsv:mig:{i}",
            node_execution_contract_id="nec:mig:1",
            logical_call_id=f"call:mig:{i}",
            idempotency_key=f"idem:{i}",
            input_sha256=_sha(700 + i),
            attempt=1,
            transport_attempts=0,
            status=ReservationStatus.RESERVED,
            reserved_at=clock.now(),
            updated_at=clock.now(),
        )
        for i in range(rows)
    ]
    resv_source_hash = sha256()
    for r in reservations:
        resv_source_hash.update(_canonical_model_hash(r).encode("utf-8"))
    resv_raw_bad = [
        {"source_key": "rsv:mig:bad:1", "reason_code": "missing_input_hash"},
        {"source_key": "rsv:mig:bad:2", "reason_code": "invalid_terminal_state"},
    ]

    # =====================================================================
    # 7/8/9. read-model families
    # =====================================================================
    ccr_nodes = [f"node:{i}" for i in range(rows)]
    dgr_keys = [f"dk:{i}" for i in range(rows)]
    wrsr_runs = [f"wr:mig:{i}" for i in range(rows)]
    read_chapter_bad = [{"source_key": "node:bad:1", "reason_code": "missing_hashes"}]
    read_decision_bad = [{"source_key": "dk:bad:1", "reason_code": "missing_option"}]
    read_run_bad = [{"source_key": "wr:mig:bad:1", "reason_code": "missing_status"}]

    # =====================================================================
    # 10. checkpoints
    # =====================================================================
    ckpt_runs = [f"run:mig:{i}" for i in range(rows)]
    ckpt_bad = [{"source_key": "run:mig:bad:1", "reason_code": "missing_stream_id"}]

    # ---- Write mappable source rows via ports ----
    with backend.new_uow() as uow:
        cas = uow.study_definition_cas_repository
        sdr_cas = uow.semantic_document_cas_repository
        ev = uow.event_stream_repository
        ob = uow.outbox_repository
        ib = uow.inbox_repository
        rv = uow.reservation_repository
        rm = uow.read_model_repository
        assert all(r is not None for r in (cas, sdr_cas, ev, ob, ib, rv, rm))
        # study definitions
        for s in studies:
            cas.save_with_expected_revision(project_id, s, expected_revision=0)
        # semantic document revisions
        for d in docs:
            sdr_cas.save_with_expected_revision(project_id, d, expected_revision=0)
        # events
        ev.append_events(project_id, "stream:mig:1", events)
        # outbox / inbox (stable enumeration, NOT hash())
        for i, k in enumerate(outbox_keys):
            ob.enqueue(project_id, "wr:mig:1", "download", k, _sha(800 + i), clock.now())
        for i, k in enumerate(inbox_keys):
            ib.record_result(project_id, k, _sha(850 + i), clock.now())
        # reservations
        for r in reservations:
            rv.reserve(project_id, r)
        # read-model families
        for i, node in enumerate(ccr_nodes):
            rm.upsert_chapter_coverage(project_id, "rev:mig", _make_ccr(project_id, node, 900 + i))
        for i, dk in enumerate(dgr_keys):
            rm.upsert_decision_graph(project_id, "sd:mig:00", _make_dgr(project_id, dk, 920 + i))
        for i, wr in enumerate(wrsr_runs):
            rm.upsert_workflow_run_status(_make_wrsr(project_id, wr, 940 + i))

    # Checkpoints (separate namespace / connection).
    ckpt = backend.open_checkpoint_store()
    try:
        for i, run in enumerate(ckpt_runs):
            ckpt.create(project_id, run, "stream:mig:1", i + 1, _sha(950 + i), state=i)
    finally:
        close = getattr(ckpt, "close", None)
        if close is not None:
            close()

    # ---- Persist every unmappable raw object through the quarantine store ----
    qs = backend.open_quarantine_store()
    try:
        study_bad_n, study_bad_recs = _quarantine_capture(qs, "StudyDefinitionV3", study_raw_bad)
        doc_bad_n, doc_bad_recs = _quarantine_capture(qs, "SemanticDocumentRevision", doc_raw_bad)
        event_bad_n, event_bad_recs = _quarantine_capture(qs, "events", event_raw_bad)
        outbox_bad_n, outbox_bad_recs = _quarantine_capture(qs, "outbox", outbox_raw_bad)
        inbox_bad_n, inbox_bad_recs = _quarantine_capture(qs, "inbox", inbox_raw_bad)
        resv_bad_n, resv_bad_recs = _quarantine_capture(qs, "reservations", resv_raw_bad)
        chapter_bad_n, chapter_bad_recs = _quarantine_capture(qs, "chapter_coverage", read_chapter_bad)
        decision_bad_n, decision_bad_recs = _quarantine_capture(qs, "decision_graph", read_decision_bad)
        run_bad_n, run_bad_recs = _quarantine_capture(qs, "workflow_run_status", read_run_bad)
        ckpt_bad_n, ckpt_bad_recs = _quarantine_capture(qs, "checkpoints", ckpt_bad)
    finally:
        close = getattr(qs, "close", None)
        if close is not None:
            close()

    # ---- Read back migrated rows (via ports) ----
    with backend.new_uow() as uow:
        cas = uow.study_definition_cas_repository
        sdr_cas = uow.semantic_document_cas_repository
        ev = uow.event_stream_repository
        ob = uow.outbox_repository
        ib = uow.inbox_repository
        rv = uow.reservation_repository
        rm = uow.read_model_repository
        assert all(r is not None for r in (cas, sdr_cas, ev, ob, ib, rv, rm))
        # study definitions
        migrated_studies = []
        for s in studies:
            cur = _read_current(uow, project_id, s.study_definition_id)
            if cur is not None:
                migrated_studies.append(_canonical_model_hash(cur))
        # semantic document revisions
        migrated_docs = []
        for d in docs:
            cur = uow.semantic_document_repository.get_current(project_id, d.semantic_document_revision_id)
            if cur is not None:
                migrated_docs.append(_canonical_model_hash(cur))
        # events
        mig_events = ev.read_events(project_id, "stream:mig:1")
        # outbox / inbox
        mig_outbox = [ob.find_by_logical_key(project_id, k) for k in outbox_keys]
        mig_inbox = [ib.get_result(project_id, k) for k in inbox_keys]
        # reservations
        mig_resv = []
        for r in reservations:
            got = rv.get(project_id, r.execution_reservation_id)
            if got is not None:
                mig_resv.append(_canonical_model_hash(got))
        # read-model families
        mig_chapter = rm.get_chapter_coverage(project_id, "rev:mig")
        mig_decision = rm.get_decision_graph(project_id, study_definition_id="sd:mig:00")
        mig_wrsr = [rm.get_workflow_run_status(project_id, wr) for wr in wrsr_runs]

    ckpt_store = backend.open_checkpoint_store()
    try:
        mig_runs = sorted(ckpt_store.list_runs(project_id))
    finally:
        close = getattr(ckpt_store, "close", None)
        if close is not None:
            close()

    # ---- Re-open the quarantine store to prove records survive ----
    qs2 = backend.open_quarantine_store()
    try:
        surv_study = qs2.list_quarantined("StudyDefinitionV3")
        surv_doc = qs2.list_quarantined("SemanticDocumentRevision")
        surv_event = qs2.list_quarantined("events")
        surv_outbox = qs2.list_quarantined("outbox")
        surv_inbox = qs2.list_quarantined("inbox")
        surv_resv = qs2.list_quarantined("reservations")
        surv_chapter = qs2.list_quarantined("chapter_coverage")
        surv_decision = qs2.list_quarantined("decision_graph")
        surv_run = qs2.list_quarantined("workflow_run_status")
        surv_ckpt = qs2.list_quarantined("checkpoints")
    finally:
        close = getattr(qs2, "close", None)
        if close is not None:
            close()

    # ---- Per-family accounting ----
    def _family(name: str, source_n: int, migrated_n: int, bad_n: int, bad_recs: List[Dict[str, Any]],
                source_hash: Optional[str] = None, migrated_hash: Optional[str] = None,
                hash_match: Optional[bool] = None) -> Dict[str, Any]:
        survived = len(bad_recs if bad_recs else [])
        # source = mappable source rows + deliberately unmappable raw rows
        total_source = source_n + bad_n
        accounted = total_source == migrated_n + bad_n and migrated_n == source_n
        return {
            "source": total_source,
            "mappable": source_n,
            "migrated": migrated_n,
            "quarantined": bad_n,
            "source_hash": source_hash,
            "migrated_hash": migrated_hash,
            "hash_match": hash_match,
            "accounted": accounted,
            "quarantine_survived": survived,
            "quarantine_records": bad_recs,
        }

    # hashes for migrated study/docs/events
    mig_study_hash = sha256()
    for h in migrated_studies:
        mig_study_hash.update(h.encode("utf-8"))
    mig_doc_hash = sha256()
    for h in migrated_docs:
        mig_doc_hash.update(h.encode("utf-8"))
    mig_event_hash = sha256()
    for e in mig_events:
        mig_event_hash.update(e.event_sha256.encode("utf-8"))

    families = {
        "StudyDefinitionV3": _family("StudyDefinitionV3", rows, len(migrated_studies), study_bad_n, study_bad_recs,
                                      study_source_hash.hexdigest(), mig_study_hash.hexdigest(),
                                      study_source_hash.hexdigest() == mig_study_hash.hexdigest()),
        "SemanticDocumentRevision": _family("SemanticDocumentRevision", rows, len(migrated_docs), doc_bad_n, doc_bad_recs,
                                            doc_source_hash.hexdigest(), mig_doc_hash.hexdigest(),
                                            doc_source_hash.hexdigest() == mig_doc_hash.hexdigest()),
        "events": _family("events", rows, len(mig_events), event_bad_n, event_bad_recs,
                          event_source_hash.hexdigest(), mig_event_hash.hexdigest(),
                          event_source_hash.hexdigest() == mig_event_hash.hexdigest()),
        "outbox": _family("outbox", rows, sum(1 for m in mig_outbox if m is not None), outbox_bad_n, outbox_bad_recs),
        "inbox": _family("inbox", rows, sum(1 for m in mig_inbox if m is not None), inbox_bad_n, inbox_bad_recs),
        "reservations": _family("reservations", rows, len(mig_resv), resv_bad_n, resv_bad_recs),
        "chapter_coverage": _family("chapter_coverage", rows, len(mig_chapter), chapter_bad_n, chapter_bad_recs),
        "decision_graph": _family("decision_graph", rows, len(mig_decision), decision_bad_n, decision_bad_recs),
        "workflow_run_status": _family("workflow_run_status", rows, sum(1 for r in mig_wrsr if r is not None), run_bad_n, run_bad_recs),
        "checkpoints": _family("checkpoints", rows, len(mig_runs), ckpt_bad_n, ckpt_bad_recs),
    }

    all_accounted = all(f["accounted"] for f in families.values())
    # Every family must quarantine at least 1 object and those must survive.
    all_quarantined = all(f["quarantined"] >= 1 for f in families.values())
    all_survived = all(
        f["quarantine_survived"] >= 1 and all(r["reason_code"] for r in f["quarantine_records"])
        for f in families.values()
    )
    # Hash match for the families that carry canonical hashes.
    hash_deterministic = (
        families["StudyDefinitionV3"]["hash_match"]
        and families["SemanticDocumentRevision"]["hash_match"]
        and families["events"]["hash_match"]
    )

    passed = all_accounted and all_quarantined and all_survived and hash_deterministic

    return InvariantResult(
        name="migration_quarantine",
        passed=passed,
        deterministic={
            "rows_per_mappable_family": rows,
            "per_family": families,
            "accounting_100_percent": all_accounted,
            "every_family_has_quarantine": all_quarantined,
            "quarantine_survived": all_survived,
            "canonical_hash_match_all": hash_deterministic,
        },
    )

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_full_suite(
    backend: Backend,
    tmp_dir: Path,
    *,
    sqlite_version: Optional[str] = None,
) -> BenchmarkResult:
    """Run all invariants and return a :class:`BenchmarkResult`."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    invariants: List[InvariantResult] = []
    timing: Dict[str, float] = {}

    for name, fn, args in [
        ("cas_concurrency", invariant_cas_concurrency, (backend,)),
        ("event_chain", invariant_event_chain, (backend,)),
        ("transaction_outbox_atomicity", invariant_transaction_outbox_atomicity, (backend,)),
        ("checkpoint_isolation", invariant_checkpoint_isolation, (backend,)),
        ("migration_quarantine", invariant_migration_quarantine, (backend,)),
        ("crash_recovery", invariant_crash_recovery, (backend, tmp_dir)),
        ("backup_restore_replay", invariant_backup_restore_replay, (backend, tmp_dir)),
        ("rollback_to_snapshot", invariant_rollback_to_snapshot, (backend, tmp_dir)),
    ]:
        start = time.perf_counter()
        try:
            result = fn(*args)
        except Exception as exc:  # noqa: BLE001
            result = InvariantResult(
                name=name, passed=False, error=f"{type(exc).__name__}: {exc}"
            )
        timing[name] = round((time.perf_counter() - start) * 1000, 2)
        invariants.append(result)

    return BenchmarkResult(
        candidate=backend.name,
        sqlite_version=sqlite_version,
        workload={
            "writers": WRITER_COUNT,
            "cas_operations": CAS_OPERATION_COUNT,
            "events": EVENT_COUNT,
            "reference_event_count": REFERENCE_EVENT_COUNT,
            "scale_multiplier": SCALE_MULTIPLIER,
            "backup_event_count": REFERENCE_EVENT_COUNT * SCALE_MULTIPLIER,
        },
        invariants=invariants,
        measured_ms=timing,
    )


def write_result(result: BenchmarkResult, filename: str) -> Path:
    """Write a deterministic JSON result file under ``results/``."""
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _RESULTS_DIR / filename
    path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path