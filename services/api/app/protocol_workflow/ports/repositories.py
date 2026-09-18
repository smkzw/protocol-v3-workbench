"""Storage-agnostic repository ports for the Protocol v3 authority kernel.

These are abstract persistence contracts (``typing.Protocol``).  They define the
operations the application service, reducers and outbox/inbox dispatchers rely on
without prescribing SQLite, PostgreSQL or any other storage.  Every method
carries explicit project, aggregate, stream and idempotency identities so that
project isolation, revision CAS, append-only event ordering and exactly-once
side-effect semantics are expressible at the interface level.

Repository objects are application-service dependencies.  They MUST NOT be exposed
to ``NodeExecutionContract``, agent input/output, the harness or any worker.  The
unit-of-work port (defined separately) owns transactional commit/rollback and is
the only composition path through which the application service obtains these
repositories.

All return records are immutable (frozen dataclasses or the already-frozen
``ProtocolV3Model`` value contracts).  Mutators return the persisted record so the
caller never holds a stale reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import (
    Literal,
    Optional,
    Protocol,
    Sequence,
    TypeVar,
    runtime_checkable,
)

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    DomainEvent,
    ExecutionReservation,
    ExecutionTerminalState,
    NonEmptyText,
    NonNegativeInt,
    PositiveRevision,
    ProtocolV3Model,
    ReservationStatus,
    Sha256,
    SideEffectKind,
    StableId,
    WorkflowRunStatus,
)

__all__ = [
    # exceptions
    "RepositoryError",
    "AggregateNotFoundError",
    "RevisionConflictError",
    "EventSequenceConflictError",
    "IdempotencyConflictError",
    "RepositoryStateTransitionError",
    "UnknownOutcomeConflictError",
    # enums
    "OutboxStatus",
    "InboxStatus",
    # records
    "StreamHead",
    "OutboxMessage",
    "InboxResult",
    "ChapterCoverageRecord",
    "DecisionGraphRecord",
    "WorkflowRunStatusRecord",
    # ports
    "CurrentAggregateRepository",
    "EventStreamRepository",
    "RevisionCasRepository",
    "OutboxRepository",
    "InboxRepository",
    "ExecutionReservationRepository",
    "ReadModelRepository",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
#
# The repository layer raises these lightweight, storage-agnostic exceptions.
# They carry the identity context that disambiguates the failure.  The
# application service is responsible for translating them into the stable
# ``ProtocolWorkflowError`` types defined in ``protocol_workflow.errors``.


class RepositoryError(RuntimeError):
    """Base class for all repository-layer failures.

    Carries the ``project_id`` and, when relevant, the aggregate/stream identity
    so the application service can attach them to audit context.
    """

    __slots__ = ("project_id", "aggregate_id", "detail")

    def __init__(
        self,
        project_id: str,
        *,
        aggregate_id: Optional[str] = None,
        detail: str = "",
    ) -> None:
        self.project_id = project_id
        self.aggregate_id = aggregate_id
        self.detail = detail
        label = f"project={project_id}"
        if aggregate_id is not None:
            label += f" aggregate={aggregate_id}"
        if detail:
            label += f" detail={detail}"
        super().__init__(label)


class AggregateNotFoundError(RepositoryError):
    """Raised when ``get_current`` is called with ``required=True`` but no
    aggregate exists for the given identity."""


class RevisionConflictError(RepositoryError):
    """Raised when a CAS-save precondition fails.

    ``expected_revision`` is the revision the caller assumed was current;
    ``actual_revision`` is what the store held at commit time.  When the
    aggregate does not yet exist, ``actual_revision`` is ``None``.
    """

    __slots__ = ("expected_revision", "actual_revision")

    def __init__(
        self,
        project_id: str,
        aggregate_id: str,
        expected_revision: Optional[int],
        actual_revision: Optional[int],
    ) -> None:
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            project_id,
            aggregate_id=aggregate_id,
            detail=(
                f"expected_revision={expected_revision} "
                f"actual_revision={actual_revision}"
            ),
        )


class EventSequenceConflictError(RepositoryError):
    """Raised when an appended event breaks the append-only chain.

    The store detects a gap in ``sequence``, a mismatched
    ``previous_event_sha256``, or a duplicate ``domain_event_id`` / ``sequence``
    within the same stream.
    """

    __slots__ = ("stream_id", "expected_sequence", "actual_sequence")

    def __init__(
        self,
        project_id: str,
        stream_id: str,
        expected_sequence: Optional[int],
        actual_sequence: Optional[int],
        detail: str = "",
    ) -> None:
        self.stream_id = stream_id
        self.expected_sequence = expected_sequence
        self.actual_sequence = actual_sequence
        super().__init__(
            project_id,
            aggregate_id=stream_id,
            detail=detail
            or (
                f"expected_sequence={expected_sequence} "
                f"actual_sequence={actual_sequence}"
            ),
        )


class IdempotencyConflictError(RepositoryError):
    """Raised when an outbox enqueue or inbox record receives a different
    payload under a logical key that already has a committed entry.

    Replaying the *same* payload (same content SHA-256) under the same logical
    key MUST return the existing record without error — that is the idempotent
    path.  Supplying *different* bytes under the same logical key is a contract
    violation, not a retry.
    """

    __slots__ = ("logical_key", "existing_sha256", "incoming_sha256")

    def __init__(
        self,
        project_id: str,
        logical_key: str,
        existing_sha256: str,
        incoming_sha256: str,
    ) -> None:
        self.logical_key = logical_key
        self.existing_sha256 = existing_sha256
        self.incoming_sha256 = incoming_sha256
        super().__init__(
            project_id,
            aggregate_id=logical_key,
            detail=(
                f"logical_key={logical_key} "
                f"existing={existing_sha256} incoming={incoming_sha256}"
            ),
        )


class UnknownOutcomeConflictError(RepositoryError):
    """Raised when an operation attempts to treat a reservation whose status is
    ``UNKNOWN_OUTCOME`` as failed/completed, or to re-dispatch the same logical
    call while an unknown-outcome reservation is unresolved.

    Per design section 18, an unknown-outcome reservation MUST be explicitly
    resolved before the graph may retry or mark completion.
    """


class RepositoryStateTransitionError(RepositoryError):
    """Raised when a repository mutator is asked to bypass its state machine."""

    __slots__ = ("from_status", "to_status")

    def __init__(
        self,
        project_id: str,
        aggregate_id: str,
        *,
        from_status: str,
        to_status: str,
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            project_id,
            aggregate_id=aggregate_id,
            detail=f"illegal state transition {from_status!r} -> {to_status!r}",
        )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OutboxStatus(str, Enum):
    """Lifecycle of a transactional-outbox side-effect message."""

    PENDING = "pending"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"


class InboxStatus(str, Enum):
    """Lifecycle of an idempotent external-result inbox entry."""

    RECEIVED = "received"
    CONSUMED = "consumed"
    SUPERSEDED = "superseded"


# ---------------------------------------------------------------------------
# Immutable records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StreamHead:
    """Head-of-chain summary for an append-only event stream."""

    stream_id: StableId
    last_sequence: PositiveRevision
    last_event_sha256: Sha256
    event_count: NonNegativeInt


@dataclass(frozen=True)
class OutboxMessage:
    """A transactional-outbox side-effect task.

    ``logical_key`` is the idempotency key for the side effect (download, model
    call, persistence, export).  ``payload_sha256`` is the content identity of
    the side-effect payload.  Canonical mutation and outbox enqueue MUST be
    committed in the same transaction (design section 18).
    """

    outbox_message_id: StableId
    project_id: StableId
    workflow_run_id: StableId
    side_effect_kind: SideEffectKind
    logical_key: NonEmptyText
    payload_sha256: Sha256
    status: OutboxStatus
    created_at: datetime
    dispatched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    attempt: NonNegativeInt = 0
    error_detail: Optional[str] = None


@dataclass(frozen=True)
class InboxResult:
    """An idempotent external-result entry written back by a side effect.

    ``logical_key`` matches the outbox logical key.  ``result_sha256`` is the
    content identity of the external result.  The same logical key + same result
    hash replays idempotently; a different result hash under the same logical key
    raises :class:`IdempotencyConflictError`.
    """

    inbox_result_id: StableId
    project_id: StableId
    logical_key: NonEmptyText
    result_sha256: Sha256
    status: InboxStatus
    received_at: datetime
    consumed_at: Optional[datetime] = None


@dataclass(frozen=True)
class ChapterCoverageRecord:
    """Read-model projection of one chapter's writing, evidence and lock state
    relative to the current semantic document revision."""

    project_id: StableId
    semantic_node_id: StableId
    chapter_contract_sha256: Optional[Sha256]
    substantive_content_contract_sha256: Optional[Sha256]
    semantic_block_sha256: Optional[Sha256]
    is_locked: bool
    has_substantive_content: bool
    evidence_admitted: bool


@dataclass(frozen=True)
class DecisionGraphRecord:
    """Read-model projection of one decision key and its resolved option."""

    project_id: StableId
    decision_key: StableId
    decision_record_id: Optional[StableId]
    state_revision: Optional[PositiveRevision]
    selected_option_id: Optional[StableId]
    canonical_state: Optional[CanonicalState]

    # Historical confirmation is not proof that its inputs are still current.
    current_validity: Literal["unverified", "current", "stale"] = "unverified"


@dataclass(frozen=True)
class WorkflowRunStatusRecord:
    """Read-model projection of a workflow run's execution status."""

    project_id: StableId
    workflow_run_id: StableId
    status: WorkflowRunStatus
    display_progress: float
    journey_counter: NonNegativeInt


# ---------------------------------------------------------------------------
# Generic aggregate type variable
# ---------------------------------------------------------------------------

#: Bound to the immutable Protocol v3 value-contract base.  All canonical
#: aggregates (StudyDefinitionV3, SemanticDocumentRevision, ApplicabilitySnapshot,
#: WorkflowRun, ChapterContract, ...) extend this base.
AggregateT = TypeVar("AggregateT", bound=ProtocolV3Model)


# ---------------------------------------------------------------------------
# Port 1 — Current aggregate lookup
# ---------------------------------------------------------------------------


@runtime_checkable
class CurrentAggregateRepository(Protocol[AggregateT]):
    """Read access to the *current* revision of a versioned aggregate.

    "Current" means the latest non-superseded revision for the given aggregate
    identity within a project.  Historical revisions are retrievable via
    :meth:`get_at_revision`.

    A concrete store implements this protocol once per aggregate type (e.g.
    ``CurrentAggregateRepository[StudyDefinitionV3]``).
    """

    def list_current(self, project_id: StableId) -> Tuple[AggregateT, ...]:
        """Return one latest revision per identity, ordered by aggregate id."""
        ...

    def get_current(
        self,
        project_id: StableId,
        aggregate_id: StableId,
    ) -> Optional[AggregateT]:
        """Return the current revision, or ``None`` if no aggregate exists."""
        ...

    def get_current_required(
        self,
        project_id: StableId,
        aggregate_id: StableId,
    ) -> AggregateT:
        """Return the current revision; raise :class:`AggregateNotFoundError`
        if it does not exist."""
        ...

    def get_at_revision(
        self,
        project_id: StableId,
        aggregate_id: StableId,
        revision: PositiveRevision,
    ) -> Optional[AggregateT]:
        """Return a specific historical revision, or ``None``."""
        ...

    def get_current_revision(
        self,
        project_id: StableId,
        aggregate_id: StableId,
    ) -> Optional[PositiveRevision]:
        """Return only the current revision number, or ``None``.

        This is the cheap CAS-precondition probe.  Implementations SHOULD avoid
        materialising the full aggregate.
        """
        ...


# ---------------------------------------------------------------------------
# Port 2 — Append-only event stream
# ---------------------------------------------------------------------------


@runtime_checkable
class EventStreamRepository(Protocol):
    """Append-only persistence for :class:`DomainEvent` streams.

    Each stream is scoped by ``(project_id, stream_id)``.  Events MUST be
    appended in strictly ascending ``sequence`` order with a matching
    ``previous_event_sha256`` chain; violations raise
    :class:`EventSequenceConflictError`.  Existing events are never mutated or
    deleted — canonical state is rebuilt by replaying the stream (design
    section 5.2 / 18).
    """

    def append_events(
        self,
        project_id: StableId,
        stream_id: StableId,
        events: Sequence[DomainEvent],
    ) -> tuple[DomainEvent, ...]:
        """Atomically append ``events`` to the stream.

        The batch is committed as a unit.  The returned tuple is the persisted
        event sequence (equal to ``events`` on success).  Raises
        :class:`EventSequenceConflictError` on any chain break or duplicate.
        """
        ...

    def read_events(
        self,
        project_id: StableId,
        stream_id: StableId,
        *,
        from_sequence: PositiveRevision = 1,
    ) -> tuple[DomainEvent, ...]:
        """Replay events from ``from_sequence`` onwards (inclusive)."""
        ...

    def get_stream_head(
        self,
        project_id: StableId,
        stream_id: StableId,
    ) -> Optional[StreamHead]:
        """Return the current chain head, or ``None`` if the stream is empty."""
        ...


# ---------------------------------------------------------------------------
# Port 3 — Revision CAS save
# ---------------------------------------------------------------------------


@runtime_checkable
class RevisionCasRepository(Protocol[AggregateT]):
    """Compare-and-swap persistence for revision-tracked aggregates.

    Aggregates such as ``StudyDefinitionV3`` and ``SemanticDocumentRevision``
    carry ``revision`` and ``previous_revision_sha256``.  Saving a new revision
    is guarded by ``expected_revision``: the caller states the revision it
    believes is current; the store atomically rejects the save if the actual
    current revision differs.  This is the optimistic-concurrency primitive that
    prevents lost updates (design section 6.2, 18).

    Semantics of ``expected_revision``:

    * ``0`` — the aggregate must not yet exist (creating revision 1).
    * ``N`` (``N >= 1``) — the current revision must be exactly ``N``; the new
      record's revision must be ``N + 1``.
    """

    def save_with_expected_revision(
        self,
        project_id: StableId,
        record: AggregateT,
        expected_revision: NonNegativeInt,
    ) -> AggregateT:
        """Persist ``record`` iff the current revision matches
        ``expected_revision``.

        Returns the persisted record.  Raises :class:`RevisionConflictError`
        when the CAS precondition fails.
        """
        ...


# ---------------------------------------------------------------------------
# Port 4 — Transactional outbox
# ---------------------------------------------------------------------------


@runtime_checkable
class OutboxRepository(Protocol):
    """Transactional outbox for exactly-once side-effect dispatch.

    Side effects (downloads, model calls, persistence writes, exports) are
    enqueued in the same transaction as the canonical mutation that produced
    them.  A dispatcher claims pending messages, dispatches them, and writes
    the result back to the :class:`InboxRepository`.  Re-enqueuing the same
    ``logical_key`` with the same ``payload_sha256`` returns the existing
    message idempotently; a different payload under the same logical key raises
    :class:`IdempotencyConflictError` (design section 18).
    """

    def enqueue(
        self,
        project_id: StableId,
        workflow_run_id: StableId,
        side_effect_kind: SideEffectKind,
        logical_key: NonEmptyText,
        payload_sha256: Sha256,
        created_at: datetime,
    ) -> OutboxMessage:
        """Idempotently enqueue a side-effect task.

        If a message with the same ``logical_key`` and ``payload_sha256`` already
        exists, return it unchanged.  If a message exists with a different
        ``payload_sha256``, raise :class:`IdempotencyConflictError`.
        """
        ...

    def claim_pending(
        self,
        project_id: StableId,
        *,
        limit: PositiveRevision,
        claimed_at: datetime,
    ) -> tuple[OutboxMessage, ...]:
        """Atomically claim up to ``limit`` pending messages, transitioning them
        to ``DISPATCHED`` and incrementing ``attempt``."""
        ...

    def mark_completed(
        self,
        project_id: StableId,
        outbox_message_id: StableId,
        completed_at: datetime,
    ) -> OutboxMessage:
        """Transition a dispatched message to ``COMPLETED``."""
        ...

    def mark_failed(
        self,
        project_id: StableId,
        outbox_message_id: StableId,
        error_detail: NonEmptyText,
        failed_at: datetime,
    ) -> OutboxMessage:
        """Transition a dispatched message to ``FAILED``."""
        ...

    def get(
        self,
        project_id: StableId,
        outbox_message_id: StableId,
    ) -> Optional[OutboxMessage]:
        """Return a message by ID, or ``None``."""
        ...

    def find_by_logical_key(
        self,
        project_id: StableId,
        logical_key: NonEmptyText,
    ) -> Optional[OutboxMessage]:
        """Return the message for a logical key, or ``None``."""
        ...

    def list_dispatched(
        self,
        project_id: StableId,
        *,
        limit: PositiveRevision,
    ) -> tuple[OutboxMessage, ...]:
        """Return recoverable ``DISPATCHED`` messages for *project_id* in stable
        order, without mutating state.

        This is the deterministic restart-recovery discovery path: after a
        crash, a process that retained no in-memory ``OutboxMessage`` objects
        can still find dispatched-but-unacknowledged work through the
        repository (design section 18).  The returned messages MUST be:

        * scoped to *project_id* (project isolation);
        * filtered to ``status == DISPATCHED`` only (terminal ``COMPLETED`` /
          ``FAILED`` and not-yet-claimed ``PENDING`` are excluded);
        * ordered deterministically so that repeated recovery sweeps observe
          the same sequence (e.g. by creation timestamp then message id);
        * capped at *limit*.

        The method is read-only: it MUST NOT transition message status or
        increment ``attempt``.  Call :meth:`claim_pending` for state-changing
        dispatch, and the outbox dispatcher's recovery methods for
        re-acknowledgement.
        """


# ---------------------------------------------------------------------------
# Port 5 — Idempotent inbox
# ---------------------------------------------------------------------------


@runtime_checkable
class InboxRepository(Protocol):
    """Idempotent inbox for external side-effect results.

    When a dispatched side effect completes, its result is written back here
    keyed by the same ``logical_key`` used in the outbox.  Replaying the same
    result (same ``result_sha256``) returns the existing entry; a different
    result under the same logical key raises :class:`IdempotencyConflictError`
    (design section 18).
    """

    def record_result(
        self,
        project_id: StableId,
        logical_key: NonEmptyText,
        result_sha256: Sha256,
        received_at: datetime,
    ) -> InboxResult:
        """Idempotently record an external result.

        If an entry with the same ``logical_key`` and ``result_sha256`` already
        exists, return it unchanged.  If an entry exists with a different
        ``result_sha256``, raise :class:`IdempotencyConflictError`.
        """
        ...

    def get_result(
        self,
        project_id: StableId,
        logical_key: NonEmptyText,
    ) -> Optional[InboxResult]:
        """Return the result for a logical key, or ``None``."""
        ...

    def was_processed(
        self,
        project_id: StableId,
        logical_key: NonEmptyText,
    ) -> bool:
        """Return ``True`` iff a result has been recorded for the logical key."""
        ...

    def mark_consumed(
        self,
        project_id: StableId,
        logical_key: NonEmptyText,
        consumed_at: datetime,
    ) -> InboxResult:
        """Transition a received result to ``CONSUMED``."""
        ...


# ---------------------------------------------------------------------------
# Port 6 — Execution reservations
# ---------------------------------------------------------------------------


@runtime_checkable
class ExecutionReservationRepository(Protocol):
    """Persistence for :class:`ExecutionReservation` records.

    Enforces the exactly-once / unknown-outcome discipline from design section
    18: a reservation is idempotent by ``(logical_call_id, idempotency_key,
    input_sha256)``.  An unresolved ``UNKNOWN_OUTCOME`` reservation blocks
    re-dispatch of the same logical call until it is explicitly resolved.
    """

    def reserve(
        self,
        project_id: StableId,
        reservation: ExecutionReservation,
    ) -> ExecutionReservation:
        """Create or idempotently return a reservation.

        If a reservation with the same ``logical_call_id`` and
        ``idempotency_key`` already exists:

        * same ``input_sha256`` — return the existing reservation (idempotent
          retry).
        * different ``input_sha256`` — raise :class:`IdempotencyConflictError`.

        If the existing reservation is in ``UNKNOWN_OUTCOME`` status, raise
        :class:`UnknownOutcomeConflictError` — the graph must resolve it before
        re-dispatching.
        """
        ...

    def get(
        self,
        project_id: StableId,
        execution_reservation_id: StableId,
    ) -> Optional[ExecutionReservation]:
        """Return a reservation by ID, or ``None``."""
        ...

    def find_by_logical_call(
        self,
        project_id: StableId,
        logical_call_id: StableId,
        idempotency_key: NonEmptyText,
    ) -> Optional[ExecutionReservation]:
        """Return the reservation for a logical call + idempotency key, or
        ``None``."""
        ...

    def transition(
        self,
        project_id: StableId,
        execution_reservation_id: StableId,
        *,
        to_status: ReservationStatus,
        terminal_state: Optional[ExecutionTerminalState] = None,
        output_sha256: Optional[Sha256] = None,
        error_code: Optional[StableId] = None,
        provider_session_id: Optional[NonEmptyText] = None,
        transport_attempts: Optional[int] = None,
        updated_at: datetime,
    ) -> ExecutionReservation:
        """Transition a reservation to a new status.

        The resulting record MUST satisfy the ``ExecutionReservation``
        invariants (terminal-state consistency).  A live
        ``RUNNING → COMPLETED`` transition may adopt the provider-issued
        session identity from its receipt.  Once a row is
        ``UNKNOWN_OUTCOME``, recovery MUST retain the already-persisted session
        identity and no implicit re-dispatch is allowed.  A later explicit
        retry is a new append-only attempt and does not mutate or unblock the
        original idempotency key.  Illegal state or recovery-session changes
        fail closed.
        """
        ...

    def list_attempts(
        self,
        project_id: StableId,
        logical_call_id: StableId,
    ) -> tuple[ExecutionReservation, ...]:
        """Return the append-only attempt lineage in deterministic order.

        Attempt numbers are unique within a project/logical call.  Existing
        attempts are never re-keyed or overwritten when a later explicit
        retry is appended.
        """
        ...

    def find_unknown_outcome(
        self,
        project_id: StableId,
    ) -> tuple[ExecutionReservation, ...]:
        """Return all reservations in ``UNKNOWN_OUTCOME`` status for the
        project.  Used by recovery to ensure none are silently re-dispatched."""
        ...

    def find_unresolved(
        self,
        project_id: StableId,
    ) -> tuple[ExecutionReservation, ...]:
        """Return RESERVED, RUNNING and UNKNOWN_OUTCOME work for recovery.

        This includes the crash window where a physical call completed but
        persisting its terminal receipt failed, leaving a RUNNING row that
        must be reconciled rather than redispatched.
        """
        ...


# ---------------------------------------------------------------------------
# Port 7 — Read models (CQRS projections)
# ---------------------------------------------------------------------------


@runtime_checkable
class ReadModelRepository(Protocol):
    """Denormalised query projections rebuilt from authoritative events and
    immutable artifacts.

    These projections are NOT the source of truth; they are read-optimised views
    for the application service and UI.  They may lag behind the canonical state
    by at most one committed transaction.  Any inconsistency detected during
    projection MUST surface as :class:`RepositoryError`, never as silently stale
    data (design section 5.1 / 18).
    """

    def get_chapter_coverage(
        self,
        project_id: StableId,
        semantic_document_revision_id: StableId,
    ) -> tuple[ChapterCoverageRecord, ...]:
        """Return per-chapter coverage for the given document revision."""
        ...

    def get_decision_graph(
        self,
        project_id: StableId,
        study_definition_id: StableId,
    ) -> tuple[DecisionGraphRecord, ...]:
        """Return resolved decision keys for the given study definition."""
        ...

    def get_workflow_run_status(
        self,
        project_id: StableId,
        workflow_run_id: StableId,
    ) -> Optional[WorkflowRunStatusRecord]:
        """Return the status projection for a workflow run, or ``None``."""
        ...
