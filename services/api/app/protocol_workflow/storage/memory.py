"""In-memory repository and unit-of-work implementation for Protocol v3.

This module provides a single-process, in-memory realisation of the Protocol v3
repository ports (defined in ``ports.repositories``) and the unit-of-work port
(defined in ``ports.unit_of_work``).  It is the reference implementation for
testing, local development and deterministic functional verification of:

* revision compare-and-swap (CAS) for ``StudyDefinitionV3`` /
  ``SemanticDocumentRevision``;
* append-only event-stream ordering with SHA-256 chain integrity;
* transactional-outbox claim/dispatch lifecycle and idempotent enqueue;
* idempotent inbox result recording;
* execution-reservation exactly-once / unknown-outcome discipline;
* in-memory content-addressed artifact storage.

It is NOT a production store.  It holds no durability, no cross-process safety
and no medical-monitoring state.  Project isolation is enforced by keying every
structure on ``(project_id, ...)``.  Functional CAS, ordering and idempotency
are enforced as ordinary behaviour — they are not security controls.

The implementation reuses the immutable value contracts and the
repository-layer exceptions from ``ports.repositories``; it defines no new
public exception types.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import (
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
)

from packages.contracts.workbench_contracts.protocol_v3 import (
    DomainEvent,
    ExecutionReservation,
    ExecutionTerminalState,
    ProtocolV3Model,
    ReservationStatus,
    SideEffectKind,
)

from app.protocol_workflow.ports.artifacts import (
    ArtifactMetadata,
    ArtifactNotFoundError,
    ArtifactRevision,
    ArtifactStore,
    ContentIntegrityError,
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
    # artifact store
    "InMemoryArtifactStore",
    # repository implementations
    "InMemoryCurrentAggregateRepository",
    "InMemoryRevisionCasRepository",
    "InMemoryEventStreamRepository",
    "InMemoryOutboxRepository",
    "InMemoryInboxRepository",
    "InMemoryExecutionReservationRepository",
    "InMemoryReadModelRepository",
    # unit of work
    "InMemoryUnitOfWork",
]


# ---------------------------------------------------------------------------
# Shared type variables and helpers
# ---------------------------------------------------------------------------

#: Aggregate bound, mirroring ``repositories.AggregateT``.
AggregateT = TypeVar("AggregateT", bound=ProtocolV3Model)

#: The identity field name used to key an aggregate (e.g. ``study_definition_id``).
_AggregateId = str


def _aggregate_id(record: ProtocolV3Model, identity_field: str) -> _AggregateId:
    """Return the aggregate identity string from ``record``.

    Every Protocol v3 aggregate carries a single ``<thing>_id`` primary
    identity field.  The repository is constructed with that field name so it
    can extract the identity without reflection over the whole model.
    """
    value = getattr(record, identity_field, None)
    if not isinstance(value, str) or not value:
        raise TypeError(
            f"aggregate identity field {identity_field!r} is not a non-empty string"
        )
    return value


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass
class _MutationGuard:
    """Shared lifecycle guard for every mutator exposed by one in-memory UoW."""

    closed: bool = False

    def ensure_open(self) -> None:
        if self.closed:
            raise UnitOfWorkClosedError("unit of work is closed")


# ---------------------------------------------------------------------------
# In-memory content-addressed artifact store
# ---------------------------------------------------------------------------


class InMemoryArtifactStore:
    """Pure in-memory content-addressed artifact store.

    Implements :class:`~app.protocol_workflow.ports.artifacts.ArtifactStore`.
    Content identity is the SHA-256 of the bytes, computed inside the store
    (never trusted from the caller).  The same logical key + same bytes return
    the same metadata (idempotent); the same logical key + different bytes
    create a new revision, preserving prior bytes.
    """

    __slots__ = ("_by_key", "_by_sha", "_lock", "_mutation_guard")

    def __init__(self) -> None:
        # logical_key -> list[ArtifactMetadata] ordered by revision ascending
        self._by_key: Dict[str, List[ArtifactMetadata]] = {}
        # content_sha256 -> bytes (deduplicated content address)
        self._by_sha: Dict[str, bytes] = {}
        self._lock = RLock()
        self._mutation_guard: Optional[_MutationGuard] = None

    def _latest(self, logical_key: str) -> Optional[ArtifactMetadata]:
        revisions = self._by_key.get(logical_key)
        if not revisions:
            return None
        return revisions[-1]

    def _find_by_sha_in_key(
        self, logical_key: str, content_sha256: str
    ) -> Optional[ArtifactMetadata]:
        for meta in self._by_key.get(logical_key, ()):
            if meta.content_sha256 == content_sha256:
                return meta
        return None

    def store(
        self,
        logical_key: str,
        content: bytes,
        *,
        media_type: str,
        created_at: datetime,
    ) -> ArtifactMetadata:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        if not isinstance(content, (bytes, bytearray)):
            raise TypeError("content must be bytes")
        content = bytes(content)
        content_sha256 = _sha256(content)
        with self._lock:
            existing = self._find_by_sha_in_key(logical_key, content_sha256)
            if existing is not None:
                return existing
            latest = self._latest(logical_key)
            revision = (latest.revision + 1) if latest is not None else 1
            meta = ArtifactMetadata(
                logical_key=logical_key,
                revision=revision,
                content_sha256=content_sha256,
                media_type=media_type,
                size_bytes=len(content),
                created_at=created_at,
            )
            self._by_key.setdefault(logical_key, []).append(meta)
            self._by_sha.setdefault(content_sha256, content)
            return meta

    def get_metadata(
        self,
        logical_key: str,
        *,
        revision: Optional[int] = None,
    ) -> ArtifactMetadata:
        with self._lock:
            revisions = self._by_key.get(logical_key)
            if not revisions:
                raise ArtifactNotFoundError(logical_key)
            if revision is None:
                return revisions[-1]
            for meta in revisions:
                if meta.revision == revision:
                    return meta
            raise ArtifactNotFoundError(
                logical_key, detail=f"revision {revision} not found"
            )

    def get_current_revision(self, logical_key: str) -> Optional[int]:
        with self._lock:
            latest = self._latest(logical_key)
            return latest.revision if latest is not None else None

    def read(
        self,
        logical_key: str,
        *,
        revision: Optional[int] = None,
    ) -> ArtifactRevision:
        meta = self.get_metadata(logical_key, revision=revision)
        with self._lock:
            content = self._by_sha.get(meta.content_sha256)
            if content is None:
                raise ContentIntegrityError(
                    logical_key,
                    content_sha256=meta.content_sha256,
                    detail="content missing for recorded hash",
                )
            if _sha256(content) != meta.content_sha256:
                raise ContentIntegrityError(
                    logical_key, content_sha256=meta.content_sha256
                )
            return ArtifactRevision(metadata=meta, content=bytes(content))

    def read_by_sha256(self, content_sha256: str) -> ArtifactRevision:
        with self._lock:
            content = self._by_sha.get(content_sha256)
            if content is None:
                raise ArtifactNotFoundError("<by-sha>", content_sha256=content_sha256)
            if _sha256(content) != content_sha256:
                raise ContentIntegrityError("<by-sha>", content_sha256=content_sha256)
            matches = [
                meta
                for revisions in self._by_key.values()
                for meta in revisions
                if meta.content_sha256 == content_sha256
            ]
            if matches:
                meta = min(
                    matches,
                    key=lambda item: (
                        item.created_at,
                        item.logical_key,
                        item.revision,
                    ),
                )
                return ArtifactRevision(metadata=meta, content=bytes(content))
        raise ContentIntegrityError("<by-sha>", content_sha256=content_sha256)

    def list_revisions(self, logical_key: str) -> Sequence[ArtifactMetadata]:
        with self._lock:
            return tuple(self._by_key.get(logical_key, ()))

    def has_content(self, content_sha256: str) -> bool:
        with self._lock:
            return content_sha256 in self._by_sha


# ---------------------------------------------------------------------------
# In-memory current-aggregate + revision-CAS repository
# ---------------------------------------------------------------------------


class _AggregateIndex(Generic[AggregateT]):
    """Internal revision index for one aggregate type within a project.

    Keys: ``(project_id, aggregate_id)`` -> dict mapping revision -> record.
    The dict preserves insertion order so ``current`` is the highest revision
    actually stored, which equals the last inserted under monotonic CAS.
    """

    __slots__ = ("_store",)

    def __init__(self) -> None:
        # (project_id, aggregate_id) -> {revision: record}
        self._store: Dict[Tuple[str, str], Dict[int, AggregateT]] = {}

    def current_revision(self, project_id: str, aggregate_id: str) -> Optional[int]:
        revisions = self._store.get((project_id, aggregate_id))
        if not revisions:
            return None
        return max(revisions)

    def get_current(self, project_id: str, aggregate_id: str) -> Optional[AggregateT]:
        revisions = self._store.get((project_id, aggregate_id))
        if not revisions:
            return None
        return revisions[self.current_revision(project_id, aggregate_id)]

    def get_at_revision(
        self, project_id: str, aggregate_id: str, revision: int
    ) -> Optional[AggregateT]:
        revisions = self._store.get((project_id, aggregate_id))
        if not revisions:
            return None
        return revisions.get(revision)

    def save(
        self,
        project_id: str,
        aggregate_id: str,
        record: AggregateT,
        new_revision: int,
    ) -> None:
        key = (project_id, aggregate_id)
        self._store.setdefault(key, {})[new_revision] = record


@dataclass
class InMemoryCurrentAggregateRepository(Generic[AggregateT]):
    """In-memory implementation of :class:`CurrentAggregateRepository`.

    Constructed with the aggregate's primary identity field name (e.g.
    ``"study_definition_id"``) and a shared :class:`_AggregateIndex` so that
    the companion CAS repository reads/writes the same state.
    """

    identity_field: str
    index: _AggregateIndex = field(default_factory=_AggregateIndex)

    def get_current(self, project_id: str, aggregate_id: str) -> Optional[AggregateT]:
        return self.index.get_current(project_id, aggregate_id)

    def get_current_required(self, project_id: str, aggregate_id: str) -> AggregateT:
        record = self.index.get_current(project_id, aggregate_id)
        if record is None:
            raise AggregateNotFoundError(project_id, aggregate_id=aggregate_id)
        return record

    def get_at_revision(
        self,
        project_id: str,
        aggregate_id: str,
        revision: int,
    ) -> Optional[AggregateT]:
        return self.index.get_at_revision(project_id, aggregate_id, revision)

    def get_current_revision(self, project_id: str, aggregate_id: str) -> Optional[int]:
        return self.index.current_revision(project_id, aggregate_id)


@dataclass
class InMemoryRevisionCasRepository(Generic[AggregateT]):
    """In-memory implementation of :class:`RevisionCasRepository`.

    Shares its :class:`_AggregateIndex` with the companion
    :class:`InMemoryCurrentAggregateRepository`.  Enforces the CAS precondition
    on ``expected_revision``:

    * ``0`` — the aggregate must not yet exist; the record's ``revision`` must
      be ``1``.
    * ``N`` (``N >= 1``) — the current revision must be exactly ``N`` and the
      record's ``revision`` must be ``N + 1``.
    """

    identity_field: str
    index: _AggregateIndex
    _mutation_guard: Optional[_MutationGuard] = field(default=None, repr=False)

    def save_with_expected_revision(
        self,
        project_id: str,
        record: AggregateT,
        expected_revision: int,
    ) -> AggregateT:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        aggregate_id = _aggregate_id(record, self.identity_field)
        actual = self.index.current_revision(project_id, aggregate_id)
        new_revision = getattr(record, "revision", None)
        if expected_revision == 0:
            if actual is not None:
                raise RevisionConflictError(
                    project_id, aggregate_id, expected_revision, actual
                )
            if new_revision != 1:
                raise RevisionConflictError(
                    project_id, aggregate_id, expected_revision, actual
                )
            self.index.save(project_id, aggregate_id, record, 1)
            return record
        # expected_revision >= 1
        if actual is None or actual != expected_revision:
            raise RevisionConflictError(
                project_id, aggregate_id, expected_revision, actual
            )
        if new_revision != expected_revision + 1:
            raise RevisionConflictError(
                project_id, aggregate_id, expected_revision, actual
            )
        self.index.save(project_id, aggregate_id, record, new_revision)
        return record


# ---------------------------------------------------------------------------
# In-memory append-only event stream
# ---------------------------------------------------------------------------


@dataclass
class InMemoryEventStreamRepository:
    """In-memory implementation of :class:`EventStreamRepository`.

    Each stream is scoped by ``(project_id, stream_id)``.  Events are appended
    in strictly ascending ``sequence`` order with a matching
    ``previous_event_sha256`` chain; duplicates of ``domain_event_id`` or
    ``sequence`` within a stream are rejected.  Existing events are never
    mutated or deleted.
    """

    # (project_id, stream_id) -> list[DomainEvent] in append order
    _streams: Dict[Tuple[str, str], List[DomainEvent]] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)
    _mutation_guard: Optional[_MutationGuard] = field(default=None, repr=False)

    def append_events(
        self,
        project_id: str,
        stream_id: str,
        events: Sequence[DomainEvent],
    ) -> Tuple[DomainEvent, ...]:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        if not events:
            return ()
        with self._lock:
            key = (project_id, stream_id)
            stream = self._streams.setdefault(key, [])
            seen_ids = {evt.domain_event_id for evt in stream}
            seen_seqs = {evt.sequence for evt in stream}
            last_sha: Optional[str] = stream[-1].event_sha256 if stream else None
            last_seq = stream[-1].sequence if stream else 0
            pending: List[DomainEvent] = []
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
                expected_prev = (
                    None
                    if (not stream and not pending)
                    else (pending[-1].event_sha256 if pending else last_sha)
                )
                if evt.domain_event_id in seen_ids:
                    raise EventSequenceConflictError(
                        project_id,
                        stream_id,
                        expected_sequence=None,
                        actual_sequence=None,
                        detail=(f"duplicate domain_event_id={evt.domain_event_id}"),
                    )
                if evt.sequence in seen_seqs:
                    raise EventSequenceConflictError(
                        project_id,
                        stream_id,
                        expected_sequence=evt.sequence,
                        actual_sequence=evt.sequence,
                        detail=f"duplicate sequence={evt.sequence}",
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
            stream.extend(pending)
            return tuple(pending)

    def read_events(
        self,
        project_id: str,
        stream_id: str,
        *,
        from_sequence: int = 1,
    ) -> Tuple[DomainEvent, ...]:
        with self._lock:
            stream = self._streams.get((project_id, stream_id), ())
            return tuple(evt for evt in stream if evt.sequence >= from_sequence)

    def get_stream_head(self, project_id: str, stream_id: str) -> Optional[StreamHead]:
        with self._lock:
            stream = self._streams.get((project_id, stream_id))
            if not stream:
                return None
            last = stream[-1]
            return StreamHead(
                stream_id=stream_id,
                last_sequence=last.sequence,
                last_event_sha256=last.event_sha256,
                event_count=len(stream),
            )


# ---------------------------------------------------------------------------
# In-memory transactional outbox
# ---------------------------------------------------------------------------


@dataclass
class InMemoryOutboxRepository:
    """In-memory implementation of :class:`OutboxRepository`."""

    # outbox_message_id -> OutboxMessage
    _messages: Dict[str, OutboxMessage] = field(default_factory=dict)
    # (project_id, logical_key) -> outbox_message_id
    _by_logical_key: Dict[Tuple[str, str], str] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)
    _mutation_guard: Optional[_MutationGuard] = field(default=None, repr=False)

    def enqueue(
        self,
        project_id: str,
        workflow_run_id: str,
        side_effect_kind: SideEffectKind,
        logical_key: str,
        payload_sha256: str,
        created_at: datetime,
    ) -> OutboxMessage:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            key = (project_id, logical_key)
            existing_id = self._by_logical_key.get(key)
            if existing_id is not None:
                existing = self._messages[existing_id]
                if existing.payload_sha256 == payload_sha256:
                    return existing
                raise IdempotencyConflictError(
                    project_id,
                    logical_key,
                    existing.payload_sha256,
                    payload_sha256,
                )
            message_id = f"ob-{len(self._messages) + 1}-{logical_key}"
            message = OutboxMessage(
                outbox_message_id=message_id,
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                side_effect_kind=side_effect_kind,
                logical_key=logical_key,
                payload_sha256=payload_sha256,
                status=OutboxStatus.PENDING,
                created_at=created_at,
            )
            self._messages[message_id] = message
            self._by_logical_key[key] = message_id
            return message

    def claim_pending(
        self,
        project_id: str,
        *,
        limit: int,
        claimed_at: datetime,
    ) -> Tuple[OutboxMessage, ...]:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            claimed: List[OutboxMessage] = []
            for message in self._messages.values():
                if message.project_id != project_id:
                    continue
                if message.status is not OutboxStatus.PENDING:
                    continue
                updated = OutboxMessage(
                    outbox_message_id=message.outbox_message_id,
                    project_id=message.project_id,
                    workflow_run_id=message.workflow_run_id,
                    side_effect_kind=message.side_effect_kind,
                    logical_key=message.logical_key,
                    payload_sha256=message.payload_sha256,
                    status=OutboxStatus.DISPATCHED,
                    created_at=message.created_at,
                    dispatched_at=claimed_at,
                    completed_at=None,
                    attempt=message.attempt + 1,
                    error_detail=None,
                )
                self._messages[message.outbox_message_id] = updated
                claimed.append(updated)
                if len(claimed) >= limit:
                    break
            return tuple(claimed)

    def mark_completed(
        self,
        project_id: str,
        outbox_message_id: str,
        completed_at: datetime,
    ) -> OutboxMessage:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            message = self._messages.get(outbox_message_id)
            if message is None or message.project_id != project_id:
                raise AggregateNotFoundError(project_id, aggregate_id=outbox_message_id)
            if message.status is not OutboxStatus.DISPATCHED:
                raise RepositoryStateTransitionError(
                    project_id,
                    outbox_message_id,
                    from_status=message.status.value,
                    to_status=OutboxStatus.COMPLETED.value,
                )
            updated = OutboxMessage(
                outbox_message_id=message.outbox_message_id,
                project_id=message.project_id,
                workflow_run_id=message.workflow_run_id,
                side_effect_kind=message.side_effect_kind,
                logical_key=message.logical_key,
                payload_sha256=message.payload_sha256,
                status=OutboxStatus.COMPLETED,
                created_at=message.created_at,
                dispatched_at=message.dispatched_at,
                completed_at=completed_at,
                attempt=message.attempt,
                error_detail=None,
            )
            self._messages[outbox_message_id] = updated
            return updated

    def mark_failed(
        self,
        project_id: str,
        outbox_message_id: str,
        error_detail: str,
        failed_at: datetime,
    ) -> OutboxMessage:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            message = self._messages.get(outbox_message_id)
            if message is None or message.project_id != project_id:
                raise AggregateNotFoundError(project_id, aggregate_id=outbox_message_id)
            if message.status is not OutboxStatus.DISPATCHED:
                raise RepositoryStateTransitionError(
                    project_id,
                    outbox_message_id,
                    from_status=message.status.value,
                    to_status=OutboxStatus.FAILED.value,
                )
            updated = OutboxMessage(
                outbox_message_id=message.outbox_message_id,
                project_id=message.project_id,
                workflow_run_id=message.workflow_run_id,
                side_effect_kind=message.side_effect_kind,
                logical_key=message.logical_key,
                payload_sha256=message.payload_sha256,
                status=OutboxStatus.FAILED,
                created_at=message.created_at,
                dispatched_at=message.dispatched_at,
                completed_at=failed_at,
                attempt=message.attempt,
                error_detail=error_detail,
            )
            self._messages[outbox_message_id] = updated
            return updated

    def get(self, project_id: str, outbox_message_id: str) -> Optional[OutboxMessage]:
        with self._lock:
            message = self._messages.get(outbox_message_id)
            if message is None or message.project_id != project_id:
                return None
            return message

    def find_by_logical_key(
        self, project_id: str, logical_key: str
    ) -> Optional[OutboxMessage]:
        with self._lock:
            message_id = self._by_logical_key.get((project_id, logical_key))
            if message_id is None:
                return None
            return self._messages.get(message_id)

    def list_dispatched(
        self,
        project_id: str,
        *,
        limit: int,
    ) -> Tuple[OutboxMessage, ...]:
        """Return recoverable ``DISPATCHED`` messages in stable order.

        Stable order is ``(created_at, outbox_message_id)`` so that repeated
        recovery sweeps observe the same sequence regardless of dict iteration
        order.  Read-only: does not transition status or increment attempt.
        """
        with self._lock:
            candidates = [
                m
                for m in self._messages.values()
                if m.project_id == project_id and m.status is OutboxStatus.DISPATCHED
            ]
            candidates.sort(key=lambda m: (m.created_at, m.outbox_message_id))
            return tuple(candidates[:limit])


# ---------------------------------------------------------------------------
# In-memory idempotent inbox
# ---------------------------------------------------------------------------


@dataclass
class InMemoryInboxRepository:
    """In-memory implementation of :class:`InboxRepository`."""

    # (project_id, logical_key) -> InboxResult
    _results: Dict[Tuple[str, str], InboxResult] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)
    _mutation_guard: Optional[_MutationGuard] = field(default=None, repr=False)

    def record_result(
        self,
        project_id: str,
        logical_key: str,
        result_sha256: str,
        received_at: datetime,
    ) -> InboxResult:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            key = (project_id, logical_key)
            existing = self._results.get(key)
            if existing is not None:
                if existing.result_sha256 == result_sha256:
                    return existing
                raise IdempotencyConflictError(
                    project_id,
                    logical_key,
                    existing.result_sha256,
                    result_sha256,
                )
            result_id = f"ib-{len(self._results) + 1}-{logical_key}"
            result = InboxResult(
                inbox_result_id=result_id,
                project_id=project_id,
                logical_key=logical_key,
                result_sha256=result_sha256,
                status=InboxStatus.RECEIVED,
                received_at=received_at,
            )
            self._results[key] = result
            return result

    def get_result(self, project_id: str, logical_key: str) -> Optional[InboxResult]:
        with self._lock:
            return self._results.get((project_id, logical_key))

    def was_processed(self, project_id: str, logical_key: str) -> bool:
        with self._lock:
            return (project_id, logical_key) in self._results

    def mark_consumed(
        self, project_id: str, logical_key: str, consumed_at: datetime
    ) -> InboxResult:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            key = (project_id, logical_key)
            existing = self._results.get(key)
            if existing is None:
                raise AggregateNotFoundError(project_id, aggregate_id=logical_key)
            if existing.status is not InboxStatus.RECEIVED:
                raise RepositoryStateTransitionError(
                    project_id,
                    logical_key,
                    from_status=existing.status.value,
                    to_status=InboxStatus.CONSUMED.value,
                )
            updated = InboxResult(
                inbox_result_id=existing.inbox_result_id,
                project_id=existing.project_id,
                logical_key=existing.logical_key,
                result_sha256=existing.result_sha256,
                status=InboxStatus.CONSUMED,
                received_at=existing.received_at,
                consumed_at=consumed_at,
            )
            self._results[key] = updated
            return updated


# ---------------------------------------------------------------------------
# In-memory execution reservations
# ---------------------------------------------------------------------------


@dataclass
class InMemoryExecutionReservationRepository:
    """In-memory implementation of :class:`ExecutionReservationRepository`.

    Enforces the exactly-once / unknown-outcome discipline from design section
    18: a reservation is idempotent by ``(logical_call_id, idempotency_key,
    input_sha256)``.  An unresolved ``UNKNOWN_OUTCOME`` reservation blocks
    re-dispatch until explicitly transitioned away.
    """

    # (project_id, execution_reservation_id) -> ExecutionReservation
    _by_id: Dict[Tuple[str, str], ExecutionReservation] = field(default_factory=dict)
    # (project_id, logical_call_id, idempotency_key) -> execution_reservation_id
    _by_logical_call: Dict[Tuple[str, str, str], str] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)
    _mutation_guard: Optional[_MutationGuard] = field(default=None, repr=False)

    def reserve(
        self, project_id: str, reservation: ExecutionReservation
    ) -> ExecutionReservation:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            key = (
                project_id,
                reservation.logical_call_id,
                reservation.idempotency_key,
            )
            existing_id = self._by_logical_call.get(key)
            if existing_id is not None:
                existing = self._by_id[(project_id, existing_id)]
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
            identity_key = (project_id, reservation.execution_reservation_id)
            identity_collision = self._by_id.get(identity_key)
            if identity_collision is not None:
                if identity_collision == reservation:
                    return identity_collision
                raise IdempotencyConflictError(
                    project_id,
                    reservation.execution_reservation_id,
                    identity_collision.input_sha256,
                    reservation.input_sha256,
                )
            self._by_id[identity_key] = reservation
            self._by_logical_call[key] = reservation.execution_reservation_id
            return reservation

    def get(
        self, project_id: str, execution_reservation_id: str
    ) -> Optional[ExecutionReservation]:
        with self._lock:
            return self._by_id.get((project_id, execution_reservation_id))

    def find_by_logical_call(
        self,
        project_id: str,
        logical_call_id: str,
        idempotency_key: str,
    ) -> Optional[ExecutionReservation]:
        with self._lock:
            existing_id = self._by_logical_call.get(
                (project_id, logical_call_id, idempotency_key)
            )
            if existing_id is None:
                return None
            return self._by_id.get((project_id, existing_id))

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
        updated_at: datetime,
    ) -> ExecutionReservation:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            identity_key = (project_id, execution_reservation_id)
            existing = self._by_id.get(identity_key)
            if existing is None:
                raise AggregateNotFoundError(
                    project_id, aggregate_id=execution_reservation_id
                )
            if (
                existing.status is ReservationStatus.UNKNOWN_OUTCOME
                and to_status is ReservationStatus.UNKNOWN_OUTCOME
            ):
                raise UnknownOutcomeConflictError(
                    project_id,
                    aggregate_id=execution_reservation_id,
                    detail="cannot re-dispatch while unknown-outcome unresolved",
                )
            # Build the new immutable record; the contract invariants are
            # enforced by the ExecutionReservation model validator.
            updated = existing.model_copy(
                update={
                    "status": to_status,
                    "terminal_state": terminal_state,
                    "output_sha256": output_sha256,
                    "error_code": error_code,
                    "provider_session_id": provider_session_id
                    if provider_session_id is not None
                    else existing.provider_session_id,
                    "updated_at": updated_at,
                }
            )
            self._by_id[identity_key] = updated
            return updated

    def find_unknown_outcome(self, project_id: str) -> Tuple[ExecutionReservation, ...]:
        with self._lock:
            return tuple(
                reservation
                for (
                    owner_project_id,
                    _reservation_id,
                ), reservation in self._by_id.items()
                if reservation.status is ReservationStatus.UNKNOWN_OUTCOME
                and owner_project_id == project_id
            )


# ---------------------------------------------------------------------------
# In-memory read models
# ---------------------------------------------------------------------------


@dataclass
class InMemoryReadModelRepository:
    """In-memory implementation of :class:`ReadModelRepository`.

    Projections are populated by the application service (or a projector) via
    the mutator helpers below; the read methods return what was stored.  This
    mirrors the CQRS split: projections are views, never the source of truth.
    """

    # (project_id, semantic_document_revision_id) -> tuple[ChapterCoverageRecord]
    _chapter_coverage: Dict[Tuple[str, str], Tuple[ChapterCoverageRecord, ...]] = field(
        default_factory=dict
    )
    # (project_id, study_definition_id) -> tuple[DecisionGraphRecord]
    _decision_graph: Dict[Tuple[str, str], Tuple[DecisionGraphRecord, ...]] = field(
        default_factory=dict
    )
    # (project_id, workflow_run_id) -> WorkflowRunStatusRecord
    _run_status: Dict[Tuple[str, str], WorkflowRunStatusRecord] = field(
        default_factory=dict
    )
    _lock: RLock = field(default_factory=RLock)
    _mutation_guard: Optional[_MutationGuard] = field(default=None, repr=False)

    # -- mutators (used by the projector / application service) -------------

    def replace_chapter_coverage(
        self,
        project_id: str,
        semantic_document_revision_id: str,
        records: Sequence[ChapterCoverageRecord],
    ) -> None:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            self._chapter_coverage[(project_id, semantic_document_revision_id)] = tuple(
                records
            )

    def replace_decision_graph(
        self,
        project_id: str,
        study_definition_id: str,
        records: Sequence[DecisionGraphRecord],
    ) -> None:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            self._decision_graph[(project_id, study_definition_id)] = tuple(records)

    def upsert_workflow_run_status(self, record: WorkflowRunStatusRecord) -> None:
        if self._mutation_guard is not None:
            self._mutation_guard.ensure_open()
        with self._lock:
            self._run_status[(record.project_id, record.workflow_run_id)] = record

    # -- ReadModelRepository ------------------------------------------------

    def get_chapter_coverage(
        self, project_id: str, semantic_document_revision_id: str
    ) -> Tuple[ChapterCoverageRecord, ...]:
        with self._lock:
            return self._chapter_coverage.get(
                (project_id, semantic_document_revision_id), ()
            )

    def get_decision_graph(
        self, project_id: str, study_definition_id: str
    ) -> Tuple[DecisionGraphRecord, ...]:
        with self._lock:
            return self._decision_graph.get((project_id, study_definition_id), ())

    def get_workflow_run_status(
        self, project_id: str, workflow_run_id: str
    ) -> Optional[WorkflowRunStatusRecord]:
        with self._lock:
            return self._run_status.get((project_id, workflow_run_id))


# ---------------------------------------------------------------------------
# In-memory unit of work
# ---------------------------------------------------------------------------


@dataclass
class InMemoryUnitOfWork:
    """In-memory implementation of :class:`UnitOfWork`.

    Because the in-memory repositories commit each mutation immediately to their
    own dicts, the transaction boundary is emulated with a snapshot/restore
    rollback: on rollback, the UoW restores the repository state captured at
    ``__enter__``.  On commit it simply marks the scope closed.  This is
    sufficient for deterministic single-process functional verification; it is
    not a substitute for a real relational transaction.

    The repositories are application-service dependencies.  This class exposes
    them only to the application service that opened the UoW; it must never be
    serialised onto ``NodeExecutionContract`` or agent I/O.
    """

    study_definition_repository: Optional[InMemoryCurrentAggregateRepository] = None
    study_definition_cas_repository: Optional[InMemoryRevisionCasRepository] = None
    semantic_document_repository: Optional[InMemoryCurrentAggregateRepository] = None
    semantic_document_cas_repository: Optional[InMemoryRevisionCasRepository] = None
    event_stream_repository: Optional[InMemoryEventStreamRepository] = None
    outbox_repository: Optional[InMemoryOutboxRepository] = None
    inbox_repository: Optional[InMemoryInboxRepository] = None
    reservation_repository: Optional[InMemoryExecutionReservationRepository] = None
    read_model_repository: Optional[InMemoryReadModelRepository] = None
    artifact_store: Optional[ArtifactStore] = None

    _depth: int = field(default=0, repr=False)
    _closed: bool = field(default=False, repr=False)
    _snapshot: Optional[Callable[[], None]] = field(default=None, repr=False)
    _mutation_guard: _MutationGuard = field(default_factory=_MutationGuard, repr=False)

    def __post_init__(self) -> None:
        guarded_repositories = (
            self.study_definition_cas_repository,
            self.semantic_document_cas_repository,
            self.event_stream_repository,
            self.outbox_repository,
            self.inbox_repository,
            self.reservation_repository,
            self.read_model_repository,
            self.artifact_store,
        )
        for repository in guarded_repositories:
            if repository is not None and hasattr(repository, "_mutation_guard"):
                repository._mutation_guard = self._mutation_guard
        object.__setattr__(self, "_snapshot", self._capture_snapshot())

    # -- snapshot helpers ---------------------------------------------------

    @staticmethod
    def _clone_index(index: "_AggregateIndex") -> "_AggregateIndex":
        clone = _AggregateIndex()
        clone._store = {key: dict(revisions) for key, revisions in index._store.items()}
        return clone

    def _capture_snapshot(self) -> Callable[[], None]:
        """Capture shallow-cloned repository state and return a restorer.

        The restorer, when called, overwrites the live repository state with the
        captured snapshot, realising rollback.
        """

        snapshots: Dict[str, object] = {}

        repo = self.study_definition_repository
        if repo is not None:
            snapshots["sd_index"] = self._clone_index(repo.index)
        repo_cas = self.study_definition_cas_repository
        if repo_cas is not None and "sd_index" not in snapshots:
            snapshots["sd_index"] = self._clone_index(repo_cas.index)
        repo2 = self.semantic_document_repository
        if repo2 is not None:
            snapshots["sdr_index"] = self._clone_index(repo2.index)
        repo2_cas = self.semantic_document_cas_repository
        if repo2_cas is not None and "sdr_index" not in snapshots:
            snapshots["sdr_index"] = self._clone_index(repo2_cas.index)

        ev = self.event_stream_repository
        if ev is not None:
            snapshots["ev_streams"] = {k: list(v) for k, v in ev._streams.items()}
        ob = self.outbox_repository
        if ob is not None:
            snapshots["ob_messages"] = dict(ob._messages)
            snapshots["ob_by_key"] = dict(ob._by_logical_key)
        ib = self.inbox_repository
        if ib is not None:
            snapshots["ib_results"] = dict(ib._results)
        rv = self.reservation_repository
        if rv is not None:
            snapshots["rv_by_id"] = dict(rv._by_id)
            snapshots["rv_by_call"] = dict(rv._by_logical_call)
        rm = self.read_model_repository
        if rm is not None:
            snapshots["rm_coverage"] = dict(rm._chapter_coverage)
            snapshots["rm_decision"] = dict(rm._decision_graph)
            snapshots["rm_run_status"] = dict(rm._run_status)

        def restore() -> None:
            sd = self.study_definition_repository
            sd_cas = self.study_definition_cas_repository
            if "sd_index" in snapshots and sd is not None:
                sd.index = snapshots["sd_index"]  # type: ignore[assignment]
            if sd_cas is not None and "sd_index" in snapshots:
                sd_cas.index = snapshots["sd_index"]  # type: ignore[assignment]
            sdr = self.semantic_document_repository
            sdr_cas = self.semantic_document_cas_repository
            if "sdr_index" in snapshots and sdr is not None:
                sdr.index = snapshots["sdr_index"]  # type: ignore[assignment]
            if sdr_cas is not None and "sdr_index" in snapshots:
                sdr_cas.index = snapshots["sdr_index"]  # type: ignore[assignment]
            if "ev_streams" in snapshots and ev is not None:
                ev._streams = snapshots["ev_streams"]  # type: ignore[assignment]
            if "ob_messages" in snapshots and ob is not None:
                ob._messages = snapshots["ob_messages"]  # type: ignore[assignment]
                ob._by_logical_key = snapshots["ob_by_key"]  # type: ignore[assignment]
            if "ib_results" in snapshots and ib is not None:
                ib._results = snapshots["ib_results"]  # type: ignore[assignment]
            if "rv_by_id" in snapshots and rv is not None:
                rv._by_id = snapshots["rv_by_id"]  # type: ignore[assignment]
                rv._by_logical_call = snapshots["rv_by_call"]  # type: ignore[assignment]
            if "rm_coverage" in snapshots and rm is not None:
                rm._chapter_coverage = snapshots["rm_coverage"]  # type: ignore[assignment]
                rm._decision_graph = snapshots["rm_decision"]  # type: ignore[assignment]
                rm._run_status = snapshots["rm_run_status"]  # type: ignore[assignment]

        return restore

    # -- UnitOfWork ---------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return not self._closed and self._depth > 0

    def commit(self) -> None:
        if self._closed:
            return
        if self._depth > 1:
            object.__setattr__(self, "_depth", self._depth - 1)
            return
        object.__setattr__(self, "_closed", True)
        object.__setattr__(self, "_depth", 0)
        self._mutation_guard.closed = True

    def rollback(self) -> None:
        if self._closed:
            return
        if self._snapshot is not None:
            self._snapshot()
        object.__setattr__(self, "_closed", True)
        object.__setattr__(self, "_depth", 0)
        self._mutation_guard.closed = True

    def __enter__(self) -> "InMemoryUnitOfWork":
        if self._closed:
            raise RuntimeError("unit of work is closed")
        object.__setattr__(self, "_depth", self._depth + 1)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._depth <= 0:
            return
        if exc is not None:
            self.rollback()
            return
        if self._depth == 1:
            self.commit()
        else:
            object.__setattr__(self, "_depth", self._depth - 1)


# ---------------------------------------------------------------------------
# UoW factory
# ---------------------------------------------------------------------------


def build_in_memory_unit_of_work(
    *,
    with_study_definition: bool = True,
    with_semantic_document: bool = True,
    with_events: bool = True,
    with_outbox: bool = True,
    with_inbox: bool = True,
    with_reservations: bool = True,
    with_read_models: bool = True,
    with_artifacts: bool = True,
) -> InMemoryUnitOfWork:
    """Build a fully wired :class:`InMemoryUnitOfWork`.

    Each repository is constructed once and shared between the UoW and the
    current-aggregate/CAS companion handles.  This is the convenience factory
    for functional verification; application wiring may construct the pieces
    individually.
    """
    sd_repo = sd_cas = sdr_repo = sdr_cas = None
    ev = ob = ib = rv = rm = artifacts = None

    if with_study_definition:
        sd_index: _AggregateIndex = _AggregateIndex()
        sd_repo = InMemoryCurrentAggregateRepository(
            identity_field="study_definition_id", index=sd_index
        )
        sd_cas = InMemoryRevisionCasRepository(
            identity_field="study_definition_id", index=sd_index
        )
    if with_semantic_document:
        sdr_index: _AggregateIndex = _AggregateIndex()
        sdr_repo = InMemoryCurrentAggregateRepository(
            identity_field="semantic_document_revision_id", index=sdr_index
        )
        sdr_cas = InMemoryRevisionCasRepository(
            identity_field="semantic_document_revision_id", index=sdr_index
        )
    if with_events:
        ev = InMemoryEventStreamRepository()
    if with_outbox:
        ob = InMemoryOutboxRepository()
    if with_inbox:
        ib = InMemoryInboxRepository()
    if with_reservations:
        rv = InMemoryExecutionReservationRepository()
    if with_read_models:
        rm = InMemoryReadModelRepository()
    if with_artifacts:
        artifacts = InMemoryArtifactStore()

    return InMemoryUnitOfWork(
        study_definition_repository=sd_repo,
        study_definition_cas_repository=sd_cas,
        semantic_document_repository=sdr_repo,
        semantic_document_cas_repository=sdr_cas,
        event_stream_repository=ev,
        outbox_repository=ob,
        inbox_repository=ib,
        reservation_repository=rv,
        read_model_repository=rm,
        artifact_store=artifacts,
    )
