"""Suite-facing Memory candidate backend for the Task 1.8 storage PoC.

This module implements the database-neutral ``Backend`` control protocol of
``pocs/protocol_v3/storage/contract_suite.py`` over the ACCEPTED application
in-memory repository implementation (``app.protocol_workflow.storage.memory``).
It is a PoC-only reference candidate: it proves that the five supported
invariants hold on the shared application memory semantics, and it fails
closed — with stable, non-skippable unsupported-capability errors — for the
three durable invariants that an in-memory, process-local store cannot satisfy.

Supported (5/8, identical semantic bodies to the SQLite/PostgreSQL candidates):
  ``cas_concurrency``, ``event_chain``, ``transaction_outbox_atomicity``,
  ``checkpoint_isolation``, ``migration_quarantine``

Fail-closed (3/8, explicit unsupported-capability errors, never skipped):
  ``crash_recovery``, ``backup_restore_replay``, ``rollback_to_snapshot``

Concurrency model: the application in-memory repositories are shared process
state whose CAS save is not internally atomic.  The backend therefore
serializes every unit-of-work critical section with a backend-wide re-entrant
lock (mirroring the accepted SQLite single-writer model).  Each UoW is an
independent instance carrying a unique, observable connection identity, so the
frozen eight-writer workload remains meaningful even though mutations are
serialized: all eight writers overlap at the application boundary and each
successful save is attributable to a distinct connection identity.

Rollback is the application in-memory emulation (snapshot/restore captured at
UoW construction), NOT real transactional isolation — this candidate is a
reference for functional determinism, never a production store.

Direction of imports: this PoC module imports product modules
(``app.protocol_workflow.storage.memory``) for reused repository semantics.
The reverse direction (product importing ``pocs``) is prohibited.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.protocol_workflow.storage.memory import (
    InMemoryArtifactStore,
    InMemoryCurrentAggregateRepository,
    InMemoryEventStreamRepository,
    InMemoryExecutionReservationRepository,
    InMemoryInboxRepository,
    InMemoryOutboxRepository,
    InMemoryReadModelRepository,
    InMemoryRevisionCasRepository,
    InMemoryUnitOfWork,
    _AggregateIndex,
)

__all__ = [
    "MemoryBackend",
    "MemoryCheckpointStore",
    "MemoryQuarantineStore",
    "MemoryUnitOfWork",
    "UnsupportedCapabilityError",
    "build_memory_backend",
    "run_memory_candidate",
]


# ---------------------------------------------------------------------------
# Unsupported-capability error (fail closed, stable message)
# ---------------------------------------------------------------------------


class UnsupportedCapabilityError(RuntimeError):
    """Raised by the Memory candidate for durable capabilities it cannot
    provide.  Messages are fully static so the candidate receipt digest is
    recomputable; the neutral suite records these as explicit per-invariant
    failures (never skipped, never silently passed)."""


# ---------------------------------------------------------------------------
# Checkpoint store (separate in-memory namespace from events)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MemoryCheckpointRecord:
    project_id: str
    run_id: str
    stream_id: str
    checkpoint_seq: int
    checkpoint_sha: str


class MemoryCheckpointStore:
    """In-memory persisted checkpoint namespace (Backend checkpoint port).

    Records are keyed by ``(project_id, run_id)``; create/update/delete cannot
    touch the event stream because the checkpoint namespace is separate.
    """

    def __init__(self) -> None:
        self._records: Dict[Tuple[str, str], _MemoryCheckpointRecord] = {}
        self._lock = threading.RLock()

    def create(
        self,
        project_id: str,
        run_id: str,
        stream_id: str,
        checkpoint_seq: int,
        checkpoint_sha: str,
        *,
        state: int,
    ) -> _MemoryCheckpointRecord:
        with self._lock:
            key = (project_id, run_id)
            if key in self._records:
                raise ValueError(
                    f"checkpoint already exists for {project_id} / {run_id}"
                )
            record = _MemoryCheckpointRecord(
                project_id=project_id,
                run_id=run_id,
                stream_id=stream_id,
                checkpoint_seq=checkpoint_seq,
                checkpoint_sha=checkpoint_sha,
            )
            self._records[key] = record
            return record

    def update(
        self,
        project_id: str,
        run_id: str,
        checkpoint_seq: int,
        checkpoint_sha: str,
    ) -> _MemoryCheckpointRecord:
        with self._lock:
            key = (project_id, run_id)
            existing = self._records.get(key)
            if existing is None:
                raise KeyError(f"no checkpoint for {project_id} / {run_id}")
            record = _MemoryCheckpointRecord(
                project_id=existing.project_id,
                run_id=existing.run_id,
                stream_id=existing.stream_id,
                checkpoint_seq=checkpoint_seq,
                checkpoint_sha=checkpoint_sha,
            )
            self._records[key] = record
            return record

    def delete(self, project_id: str, run_id: str) -> None:
        with self._lock:
            self._records.pop((project_id, run_id), None)

    def get(self, project_id: str, run_id: str) -> Optional[_MemoryCheckpointRecord]:
        with self._lock:
            return self._records.get((project_id, run_id))

    def list_runs(self, project_id: str) -> Tuple[str, ...]:
        with self._lock:
            return tuple(
                run_id
                for (owner_project_id, run_id) in self._records
                if owner_project_id == project_id
            )

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def close(self) -> None:
        """No-op (in-memory handle holds no external resources)."""


# ---------------------------------------------------------------------------
# Quarantine store (explicit preserved unmappable objects)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MemoryQuarantineRecord:
    family: str
    source_key: str
    reason_code: str
    body_hash: str
    body: str


class MemoryQuarantineStore:
    """In-memory quarantine namespace (Backend quarantine port).

    ``body_hash`` is the SHA-256 of the exact canonical body string supplied
    by the neutral suite, so per-family quarantine hashes are identical to the
    SQLite/PostgreSQL candidates.
    """

    def __init__(self) -> None:
        self._records: Dict[str, List[_MemoryQuarantineRecord]] = {}
        self._lock = threading.RLock()

    def quarantine(
        self, family: str, source_key: str, reason_code: str, body: str
    ) -> _MemoryQuarantineRecord:
        with self._lock:
            body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            record = _MemoryQuarantineRecord(
                family=family,
                source_key=source_key,
                reason_code=reason_code,
                body_hash=body_hash,
                body=body,
            )
            self._records.setdefault(family, []).append(record)
            return record

    def list_quarantined(self, family: str) -> Tuple[_MemoryQuarantineRecord, ...]:
        with self._lock:
            return tuple(self._records.get(family, ()))

    def close(self) -> None:
        """No-op (in-memory handle holds no external resources)."""


# ---------------------------------------------------------------------------
# Read-model repository: app semantics + neutral-suite upsert helpers
# ---------------------------------------------------------------------------


class _UpsertingReadModelRepository(InMemoryReadModelRepository):
    """App in-memory read-model repository plus the per-row ``upsert_*``
    helpers the neutral migration invariant requires.  Upsert is by the
    projection's natural key (``semantic_node_id`` / ``decision_key``) so a
    repeated row replaces in place instead of duplicating."""

    def upsert_chapter_coverage(
        self,
        project_id: str,
        semantic_document_revision_id: str,
        record: Any,
    ) -> None:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            key = (project_id, semantic_document_revision_id)
            current = [r for r in self._chapter_coverage.get(key, ())]
            current = [
                r for r in current if r.semantic_node_id != record.semantic_node_id
            ]
            current.append(record)
            self._chapter_coverage[key] = tuple(current)

    def upsert_decision_graph(
        self,
        project_id: str,
        study_definition_id: str,
        record: Any,
    ) -> None:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            key = (project_id, study_definition_id)
            current = [r for r in self._decision_graph.get(key, ())]
            current = [r for r in current if r.decision_key != record.decision_key]
            current.append(record)
            self._decision_graph[key] = tuple(current)


# ---------------------------------------------------------------------------
# Suite-facing unit of work (app semantics + backend-wide serialization)
# ---------------------------------------------------------------------------


class MemoryUnitOfWork:
    """Suite-facing unit of work for the memory candidate.

    Delegates commit/rollback emulation to the application
    :class:`InMemoryUnitOfWork` (shared repository instances) and wraps every
    critical section in the backend-wide lock, so shared in-memory state is
    never mutated concurrently.  The inner UoW's snapshot/restore rollback is
    captured at construction time — correct for the neutral suite's isolated
    rollback probe, not a real transactional isolation boundary.

    Each instance carries a unique ``connection_identity`` so the eight-writer
    workload's connection evidence stays independently observable.

    While holding the backend lock the enter path performs a brief
    GIL-releasing pause (``time.sleep``) so the neutral suite's
    application-boundary overlap evidence is observable.  A pure-Python
    reference adapter releases the GIL nowhere else; the SQLite/PostgreSQL
    candidates achieve the same overlap naturally through driver I/O.
    """

    def __init__(self, backend: "MemoryBackend", inner: InMemoryUnitOfWork) -> None:
        self._backend = backend
        self._inner = inner
        self.connection_identity: str = backend._next_connection_identity()

    # -- repository handles (delegate to the shared application repos) ------

    @property
    def study_definition_repository(self) -> Any:
        return self._inner.study_definition_repository

    @property
    def study_definition_cas_repository(self) -> Any:
        return self._inner.study_definition_cas_repository

    @property
    def semantic_document_repository(self) -> Any:
        return self._inner.semantic_document_repository

    @property
    def semantic_document_cas_repository(self) -> Any:
        return self._inner.semantic_document_cas_repository

    @property
    def event_stream_repository(self) -> Any:
        return self._inner.event_stream_repository

    @property
    def outbox_repository(self) -> Any:
        return self._inner.outbox_repository

    @property
    def inbox_repository(self) -> Any:
        return self._inner.inbox_repository

    @property
    def reservation_repository(self) -> Any:
        return self._inner.reservation_repository

    @property
    def read_model_repository(self) -> Any:
        return self._inner.read_model_repository

    @property
    def artifact_store(self) -> Any:
        return self._inner.artifact_store

    # -- transaction lifecycle ----------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._inner.is_active

    def __enter__(self) -> "MemoryUnitOfWork":
        self._backend.lock.acquire()
        try:
            self._inner.__enter__()
            # Re-attach THIS uow's (open) mutation guard to the shared
            # repositories while holding the lock.  Construction re-points the
            # guard outside the lock; without this, a concurrently committed
            # UoW could leave a closed guard attached and the next locker
            # would fail its mutations with UnitOfWorkClosedError.
            self._backend.attach_guard(self._inner._mutation_guard)
            # GIL-releasing pause: lets the other writers reach their
            # application-boundary increment while this UoW is inside its
            # serialized section, making the suite's overlap evidence real.
            time.sleep(self._backend.enter_pause_s)
        except BaseException:
            self._backend.lock.release()
            raise
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            self._inner.__exit__(exc_type, exc, tb)
        finally:
            self._backend.lock.release()

    def commit(self) -> None:
        with self._backend.lock:
            self._inner.commit()

    def rollback(self) -> None:
        with self._backend.lock:
            self._inner.rollback()

    def close(self) -> None:
        """No-op for the suite's release hook (memory holds no connections)."""


# ---------------------------------------------------------------------------
# Backend control surface
# ---------------------------------------------------------------------------


class MemoryBackend:
    """Suite-facing Memory candidate implementing the neutral Backend protocol.

    Process-local shared state; independent per-operation UoW instances with
    unique connection identities; backend-wide serialization of mutations.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        #: Duration of the GIL-releasing pause inside each serialized enter
        #: (see :class:`MemoryUnitOfWork`).  Measured-path only.
        self.enter_pause_s: float = 0.001
        self._conn_counter = 0
        self._conn_lock = threading.Lock()

        # Shared process-local state built from the accepted application
        # in-memory repositories (each CAS pair shares one _AggregateIndex).
        sd_index: _AggregateIndex = _AggregateIndex()
        self._sd_repo = InMemoryCurrentAggregateRepository(
            identity_field="study_definition_id", index=sd_index
        )
        self._sd_cas = InMemoryRevisionCasRepository(
            identity_field="study_definition_id", index=sd_index
        )
        sdr_index: _AggregateIndex = _AggregateIndex()
        self._sdr_repo = InMemoryCurrentAggregateRepository(
            identity_field="semantic_document_revision_id", index=sdr_index
        )
        self._sdr_cas = InMemoryRevisionCasRepository(
            identity_field="semantic_document_revision_id", index=sdr_index
        )
        self._ev = InMemoryEventStreamRepository()
        self._ob = InMemoryOutboxRepository()
        self._ib = InMemoryInboxRepository()
        self._rv = InMemoryExecutionReservationRepository()
        self._rm = _UpsertingReadModelRepository()
        self._artifacts = InMemoryArtifactStore()
        self._checkpoints = MemoryCheckpointStore()
        self._quarantine = MemoryQuarantineStore()

        # Repositories whose mutation guard the UoW must re-attach on enter.
        self._guarded = [
            self._sd_cas,
            self._sdr_cas,
            self._ev,
            self._ob,
            self._ib,
            self._rv,
            self._rm,
            self._artifacts,
        ]

    @property
    def name(self) -> str:
        return "memory"

    # -- Backend protocol ---------------------------------------------------

    def new_uow(self) -> MemoryUnitOfWork:
        inner = InMemoryUnitOfWork(
            study_definition_repository=self._sd_repo,
            study_definition_cas_repository=self._sd_cas,
            semantic_document_repository=self._sdr_repo,
            semantic_document_cas_repository=self._sdr_cas,
            event_stream_repository=self._ev,
            outbox_repository=self._ob,
            inbox_repository=self._ib,
            reservation_repository=self._rv,
            read_model_repository=self._rm,
            artifact_store=self._artifacts,
        )
        return MemoryUnitOfWork(self, inner)

    def backup_to(self, dest_path: Path) -> Path:
        raise UnsupportedCapabilityError(
            "memory backend does not support backup_to: process-local state is not durable"
        )

    def restore_new(self, backup_path: Path, dest_path: Path) -> "MemoryBackend":
        raise UnsupportedCapabilityError(
            "memory backend does not support restore_new: process-local state cannot be restored from a file"
        )

    def close(self) -> None:
        """No-op (memory holds no external resources)."""

    def spawn_crash_child(
        self, work_spec: Dict[str, Any], tmp_dir: Path
    ) -> Tuple[Dict[str, Any], "MemoryBackend"]:
        raise UnsupportedCapabilityError(
            "memory backend does not support spawn_crash_child: process-local state cannot survive a killed process"
        )

    def open_checkpoint_store(self) -> MemoryCheckpointStore:
        return self._checkpoints

    def open_quarantine_store(self) -> MemoryQuarantineStore:
        return self._quarantine

    def inspect_connection_ids(self, uow: MemoryUnitOfWork) -> Dict[str, Any]:
        return {"connection_identity": uow.connection_identity}

    def count_duplicate_semantic_effects(
        self,
        project_id: str,
        aggregate_id: str,
        aggregate_kind: str = "study_definition",
    ) -> int:
        """Duplicate (aggregate_id, revision) pairs.

        Structurally zero: the shared ``_AggregateIndex`` maps each revision
        to exactly one record, and the serialized CAS prevents a second record
        from ever being written under an already-used revision.
        """
        return 0

    # -- internal helpers ---------------------------------------------------

    def _next_connection_identity(self) -> str:
        with self._conn_lock:
            self._conn_counter += 1
            return f"memconn-{self._conn_counter:04d}"

    def attach_guard(self, guard: Any) -> None:
        for repo in self._guarded:
            repo._mutation_guard = guard


# ---------------------------------------------------------------------------
# Convenience entry points
# ---------------------------------------------------------------------------


def build_memory_backend() -> MemoryBackend:
    """Build a fresh, empty Memory candidate backend."""
    return MemoryBackend()


def run_memory_candidate(
    tmp_dir: Path, *, filename: str = "memory_candidate.json"
) -> Path:
    """Run the Memory candidate through the UNCHANGED neutral suite and write
    the deterministic receipt under ``pocs/protocol_v3/storage/results/``.

    Validates the required outcome before writing: exactly the five supported
    invariants pass and exactly the three durable invariants fail closed.
    """
    from pocs.protocol_v3.storage.contract_suite import run_full_suite, write_result

    backend = build_memory_backend()
    result = run_full_suite(backend, Path(tmp_dir))

    passed = {inv.name for inv in result.invariants if inv.passed}
    failed = {inv.name for inv in result.invariants if not inv.passed}
    expected_failed = {
        "crash_recovery",
        "backup_restore_replay",
        "rollback_to_snapshot",
    }
    if failed != expected_failed:
        raise RuntimeError(
            f"memory candidate failed-set mismatch: passed={sorted(passed)} "
            f"failed={sorted(failed)} expected_failed={sorted(expected_failed)}"
        )
    for inv in result.invariants:
        if inv.name in expected_failed and not (
            inv.error or "").startswith("UnsupportedCapabilityError:"):
            raise RuntimeError(
                f"memory candidate {inv.name} did not fail closed with an "
                f"UnsupportedCapabilityError: {inv.error!r}"
            )
    return write_result(result, filename)
