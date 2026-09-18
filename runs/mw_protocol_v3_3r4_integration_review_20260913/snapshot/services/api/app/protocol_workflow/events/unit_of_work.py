"""Atomic mutation coordinator for the Protocol v3 event authority kernel.

Design authority: Protocol v3 multi-agent rearchitecture, section 18.

    canonical mutation 与 outbox 在同一事务提交；外部副作用通过
    inbox/idempotency key 回写结果事件。

This module provides :class:`EventSourcedUnitOfWork`, the *only* composition
helper that performs a canonical CAS save, a domain-event append and a
transactional-outbox enqueue within a single :class:`~app.protocol_workflow.ports.unit_of_work.UnitOfWork`
scope.  The three operations either commit together or roll back together —
this is the design-section-18 atomicity invariant.

Responsibilities:

1. **Atomic canonical mutation** — :meth:`EventSourcedUnitOfWork.apply_mutation`
   saves the aggregate revision (CAS-guarded), appends the domain event(s) that
   record the mutation, and enqueues any side-effect outbox message, all through
   the UoW's transaction-bound repository handles.  If any step raises, the
   caller's ``with uow:`` block rolls back every prior step's writes.

2. **Inbox-first acknowledgement** — :meth:`EventSourcedUnitOfWork.acknowledge_side_effect`
   drives one outbox message through the dispatch → inbox-write → ack cycle,
   acknowledging the outbox *only after* the result is durable in the inbox.
   On crash recovery, a message left ``DISPATCHED`` is resolved deterministically
   via :meth:`EventSourcedUnitOfWork.recover_dispatched`.

The coordinator never opens a UoW itself and never holds mutable transaction
state.  It borrows the caller's UoW handles for the duration of one call.  It
imports no storage adapter — only the ports and the event-layer helpers
(:mod:`events.models`, :mod:`events.outbox`, :mod:`events.inbox`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import (
    Any,
    Callable,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from packages.contracts.workbench_contracts.protocol_v3 import (
    DomainEvent,
    ProtocolV3Model,
    SideEffectKind,
)
from app.protocol_workflow.ports.repositories import (
    IdempotencyConflictError,
    OutboxMessage,
    OutboxRepository,
    RevisionConflictError,
)
from app.protocol_workflow.ports.unit_of_work import (
    UnitOfWork,
    UnitOfWorkClosedError,
)

from app.protocol_workflow.events.models import (
    EventEnvelopeBuilder,
)
from app.protocol_workflow.events.outbox import (
    DispatchOutcome,
    OutboxDispatcher,
    OutboxRecoveryResult,
    SideEffectHandler,
)
from app.protocol_workflow.events.inbox import (
    ConsumeOutcome,
    InboxConsumer,
    InboxSemanticHandler,
)

__all__ = [
    "AtomicMutationResult",
    "EventSourcedUnitOfWork",
    "MissingRepositoryError",
    "MutationAbortedError",
]


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class MissingRepositoryError(RuntimeError):
    """Raised when the UoW scope lacks a required repository handle.

    The UoW port allows a concrete adapter to scope a UoW to a subset of
    aggregates (e.g. a document-scoped UoW without a study-definition handle).
    When the coordinator is asked to perform a mutation that requires a handle
    the scope does not provide, it fails fast with this error rather than
    silently skipping the step — silently skipping would break the atomicity
    invariant (a CAS save without its event, or an event without its outbox
    enqueue, is a split-brain).
    """

    __slots__ = ("handle_name",)

    def __init__(self, handle_name: str) -> None:
        self.handle_name = handle_name
        super().__init__(
            f"unit of work scope is missing required repository handle: {handle_name}"
        )


class MutationAbortedError(RuntimeError):
    """Raised when a mutation step fails and the transaction must roll back.

    ``step`` identifies which phase of the atomic mutation failed
    (``"cas_save"``, ``"event_append"`` or ``"outbox_enqueue"``).  ``original``
    carries the repository-layer exception so the caller can surface a typed
    error without losing the root cause.  The caller's ``with uow:`` block
    rolls back all writes performed before the failure.
    """

    __slots__ = ("step", "original")

    def __init__(self, step: str, original: Optional[BaseException] = None) -> None:
        self.step = step
        self.original = original
        label = f"atomic mutation aborted at step {step!r}"
        if original is not None:
            label += f": {original}"
        super().__init__(label)


# ---------------------------------------------------------------------------
# Mutation result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AtomicMutationResult:
    """Outcome of an atomic canonical-mutation transaction.

    ``saved_aggregate`` is the persisted aggregate returned by the CAS
    repository (its ``revision`` is advanced).  ``appended_events`` is the
    tuple of domain events durably appended to the event stream.
    ``enqueued_outbox`` is the outbox message enqueued in the same transaction
    (``None`` when the mutation produced no side effect).
    """

    saved_aggregate: ProtocolV3Model
    appended_events: Tuple[DomainEvent, ...]
    enqueued_outbox: Optional[OutboxMessage] = None


# ---------------------------------------------------------------------------
# Side-effect enqueue request
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SideEffectRequest:
    """A side effect to enqueue atomically with a canonical mutation.

    ``workflow_run_id`` scopes the outbox message to the run that produced it.
    ``side_effect_kind`` classifies the effect for dispatch routing.
    ``logical_key`` is the idempotency key under which the result is recorded
    in the inbox.  ``payload_sha256`` is the content identity of the effect
    payload.
    """

    workflow_run_id: str
    side_effect_kind: SideEffectKind
    logical_key: str
    payload_sha256: str


# ---------------------------------------------------------------------------
# Event-sourced unit of work coordinator
# ---------------------------------------------------------------------------


@dataclass
class EventSourcedUnitOfWork:
    """Composition helper for atomic canonical mutations and side-effect
    acknowledgement.

    The coordinator is constructed once with the event-building and
    dispatch/consume collaborators.  Each mutation call borrows a caller-opened
    :class:`UnitOfWork` and performs the CAS save + event append + outbox
    enqueue through its transaction-bound handles.  The caller owns the
    transaction boundary (the ``with uow:`` block); the coordinator owns the
    *ordering* and *atomicity intent*.

    Construction parameters
    -----------------------
    builder:
        The :class:`EventEnvelopeBuilder` used to construct domain events with
        canonical hashes.  Shared and stateless.
    clock:
        Callable returning the current aware ``datetime`` for outbox enqueue
        and dispatch timestamps.  Tests inject a fixed clock for determinism.
    """

    builder: EventEnvelopeBuilder = field(default_factory=EventEnvelopeBuilder)
    clock: Callable[[], datetime] = field(default_factory=lambda: _default_utc_now)

    # ------------------------------------------------------------------
    # Atomic canonical mutation
    # ------------------------------------------------------------------

    def apply_mutation(
        self,
        uow: UnitOfWork,
        *,
        project_id: str,
        stream_id: str,
        aggregate: ProtocolV3Model,
        cas_repository_handle_name: str,
        events: Sequence[DomainEvent],
        side_effect: Optional[SideEffectRequest] = None,
        expected_revision: int = 0,
    ) -> AtomicMutationResult:
        """Atomically save *aggregate*, append *events* and enqueue *side_effect*.

        All three operations execute through *uow*'s transaction-bound
        repository handles.  The ordering is:

        1. **CAS save** — persist *aggregate* at ``expected_revision``.
        2. **Event append** — append *events* to the event stream
           ``(project_id, stream_id)``.
        3. **Outbox enqueue** — if *side_effect* is given, enqueue the
           side-effect message in the same transaction.

        If any step raises, the resulting :class:`MutationAbortedError`
        propagates out of the ``with uow:`` block, triggering rollback.
        Nothing the caller did not authorise is left durable.

        Parameters
        ----------
        uow:
            The caller-opened unit of work.  Must expose non-``None``
            ``event_stream_repository`` and, when *side_effect* is given,
            ``outbox_repository``.  The CAS repository is resolved by
            *cas_repository_handle_name* (e.g. ``"study_definition_cas_repository"``).
        project_id:
            Project scope for all three operations.
        stream_id:
            The append-only event stream the events are appended to.
        aggregate:
            The canonical aggregate to CAS-save.
        cas_repository_handle_name:
            The name of the UoW property yielding the
            :class:`~app.protocol_workflow.ports.repositories.RevisionCasRepository`
            for *aggregate* (e.g. ``"study_definition_cas_repository"``).
        events:
            The domain events recording the mutation.  Must form a valid chain
            continuing the stream's current head.
        side_effect:
            Optional side effect to enqueue atomically with the mutation.
        expected_revision:
            The CAS precondition: the revision the caller believes is current.
            ``0`` means the aggregate must not yet exist.

        Raises
        ------
        MissingRepositoryError
            If *uow* lacks a required handle.
        MutationAbortedError
            If any step fails; wraps the repository-layer exception.
        """

        self._require_active_transaction(uow)
        if not events:
            raise MutationAbortedError(
                "event_required",
                ValueError("canonical mutation requires at least one domain event"),
            )

        cas_repo = self._resolve_cas_repository(uow, cas_repository_handle_name)
        event_repo = uow.event_stream_repository
        if event_repo is None:
            raise MissingRepositoryError("event_stream_repository")
        outbox_repo: Optional[OutboxRepository] = None
        if side_effect is not None:
            outbox_repo = uow.outbox_repository
            if outbox_repo is None:
                raise MissingRepositoryError("outbox_repository")

        # --- Step 1: CAS save ------------------------------------------------
        try:
            saved = cas_repo.save_with_expected_revision(
                project_id,
                aggregate,
                expected_revision,
            )
        except RevisionConflictError as exc:
            raise MutationAbortedError("cas_save", exc) from exc
        except UnitOfWorkClosedError as exc:
            raise MutationAbortedError("cas_save", exc) from exc

        # --- Step 2: Event append -------------------------------------------
        try:
            appended = event_repo.append_events(project_id, stream_id, events)
        except Exception as exc:  # EventSequenceConflictError, etc.
            raise MutationAbortedError("event_append", exc) from exc

        # --- Step 3: Outbox enqueue (optional) ------------------------------
        enqueued: Optional[OutboxMessage] = None
        if side_effect is not None:
            assert outbox_repo is not None  # narrowed above
            try:
                enqueued = outbox_repo.enqueue(
                    project_id,
                    side_effect.workflow_run_id,
                    side_effect.side_effect_kind,
                    side_effect.logical_key,
                    side_effect.payload_sha256,
                    self.clock(),
                )
            except IdempotencyConflictError as exc:
                raise MutationAbortedError("outbox_enqueue", exc) from exc
            except UnitOfWorkClosedError as exc:
                raise MutationAbortedError("outbox_enqueue", exc) from exc

        return AtomicMutationResult(
            saved_aggregate=saved,
            appended_events=tuple(appended),
            enqueued_outbox=enqueued,
        )

    # ------------------------------------------------------------------
    # Build-and-apply convenience
    # ------------------------------------------------------------------

    def build_and_apply(
        self,
        uow: UnitOfWork,
        *,
        project_id: str,
        stream_id: str,
        aggregate: ProtocolV3Model,
        cas_repository_handle_name: str,
        expected_revision: int,
        event: Mapping[str, Any],
        side_effect: Optional[SideEffectRequest] = None,
    ) -> AtomicMutationResult:
        """Build one domain event from *event* params and apply the mutation.

        *event* is a mapping with the builder keyword arguments (excluding
        ``previous_event_sha256`` and ``sequence``, which are derived from the
        stream head).  This is the common single-event-mutation path.
        """

        self._require_active_transaction(uow)

        event_repo = uow.event_stream_repository
        if event_repo is None:
            raise MissingRepositoryError("event_stream_repository")
        head = event_repo.get_stream_head(project_id, stream_id)
        if head is None:
            built = self.builder.build(
                sequence=1,
                previous_event_sha256=None,
                **event,
            )
        else:
            built = self.builder.continue_chain(
                head_sha256=head.last_event_sha256,
                head_sequence=head.last_sequence,
                **event,
            )
        return self.apply_mutation(
            uow,
            project_id=project_id,
            stream_id=stream_id,
            aggregate=aggregate,
            cas_repository_handle_name=cas_repository_handle_name,
            events=(built,),
            side_effect=side_effect,
            expected_revision=expected_revision,
        )

    # ------------------------------------------------------------------
    # Inbox-first side-effect acknowledgement
    # ------------------------------------------------------------------

    def dispatch_pending_side_effects(
        self,
        uow: UnitOfWork,
        *,
        project_id: str,
        handler: SideEffectHandler,
        limit: int = 10,
    ) -> Tuple[DispatchOutcome, ...]:
        """Claim and dispatch ``PENDING`` outbox messages inbox-first.

        Each claimed message goes through the full claim → dispatch →
        inbox-write → ack cycle.  The outbox message is acknowledged
        (``COMPLETED``) only after the side-effect result is durable in the
        inbox — the exactly-once-semantic-effect guarantee from design
        section 18.

        Returns one :class:`DispatchOutcome` per claimed message.  If no
        messages are pending, returns an empty tuple.
        """

        outbox = uow.outbox_repository
        inbox = uow.inbox_repository
        if outbox is None:
            raise MissingRepositoryError("outbox_repository")
        if inbox is None:
            raise MissingRepositoryError("inbox_repository")
        dispatcher = OutboxDispatcher(
            outbox=outbox,
            inbox=inbox,
            handler=handler,
            clock=self.clock,
        )
        return dispatcher.dispatch_pending(project_id, limit=limit)

    def acknowledge_side_effect(
        self,
        uow: UnitOfWork,
        *,
        project_id: str,
        outbox_message: OutboxMessage,
        handler: SideEffectHandler,
    ) -> DispatchOutcome:
        """Dispatch one already-``DISPATCHED`` message and acknowledge it
        inbox-first.

        This is the crash-recovery single-message path: the message was
        dispatched (``PENDING → DISPATCHED``) but never acknowledged, because
        a crash occurred.  The side effect is executed via *handler*, its
        result is written to the inbox (idempotent), and the outbox message is
        acknowledged *only after* the inbox write is durable.

        If the inbox already holds a result for this logical key (crash
        between inbox-write and outbox-ack), the outbox is completed
        **without** re-dispatching — exactly-once semantic effect.

        For fresh ``PENDING`` messages, use
        :meth:`dispatch_pending_side_effects` instead.
        """

        outbox = uow.outbox_repository
        inbox = uow.inbox_repository
        if outbox is None:
            raise MissingRepositoryError("outbox_repository")
        if inbox is None:
            raise MissingRepositoryError("inbox_repository")
        dispatcher = OutboxDispatcher(
            outbox=outbox,
            inbox=inbox,
            handler=handler,
            clock=self.clock,
        )
        return dispatcher.acknowledge_one(outbox_message, project_id)

    def recover_dispatched(
        self,
        uow: UnitOfWork,
        *,
        project_id: str,
        messages: Optional[Sequence[OutboxMessage]] = None,
        limit: int = 100,
        handler: Optional[SideEffectHandler] = None,
    ) -> OutboxRecoveryResult:
        """Recover ``DISPATCHED`` outbox messages after a crash.

        Two discovery modes (design section 18 restart recovery):

        * **Repository discovery (default):** when *messages* is ``None``, the
          dispatcher queries the outbox repository's ``list_dispatched`` to
          find recoverable work.  This is the deterministic restart path — a
          process that retained no in-memory objects can still discover and
          resolve DISPATCHED messages.  Prefer :meth:`recover_dispatched_from_repository`
          for an explicit, self-documenting restart entry point.
        * **Explicit messages:** when *messages* is provided, the dispatcher
          recovers exactly those objects.  Use this only when the caller
          legitimately retained pre-crash objects.

        For each message, the inbox is checked first: if a result is already
        recorded, the outbox is completed *without* re-dispatching
        (exactly-once semantic effect).  Otherwise the message is re-dispatched
        via *handler*.
        """

        outbox = uow.outbox_repository
        inbox = uow.inbox_repository
        if outbox is None:
            raise MissingRepositoryError("outbox_repository")
        if inbox is None:
            raise MissingRepositoryError("inbox_repository")
        dispatcher = OutboxDispatcher(
            outbox=outbox,
            inbox=inbox,
            handler=handler,
            clock=self.clock,
        )
        return dispatcher.recover_dispatched(
            project_id, messages, limit=limit, handler=handler
        )

    def recover_dispatched_from_repository(
        self,
        uow: UnitOfWork,
        *,
        project_id: str,
        limit: int = 100,
        handler: Optional[SideEffectHandler] = None,
    ) -> OutboxRecoveryResult:
        """Discover and recover ``DISPATCHED`` messages purely through the
        repository — the deterministic restart-recovery path.

        This is the entry point a *restarted process* calls when it retained no
        in-memory ``OutboxMessage`` objects from before the crash.  It asks the
        outbox repository to list ``DISPATCHED`` messages
        (``list_dispatched``) and then runs the same inbox-first
        acknowledgement cycle as :meth:`recover_dispatched`.

        Design section 18: recovery must not depend on caller-retained state.
        The repository is the authority for what work is outstanding; the
        caller supplies only the project scope and a handler.
        """

        outbox = uow.outbox_repository
        inbox = uow.inbox_repository
        if outbox is None:
            raise MissingRepositoryError("outbox_repository")
        if inbox is None:
            raise MissingRepositoryError("inbox_repository")
        dispatcher = OutboxDispatcher(
            outbox=outbox,
            inbox=inbox,
            handler=handler,
            clock=self.clock,
        )
        return dispatcher.recover_from_repository(
            project_id, limit=limit, handler=handler
        )

    def consume_inbox_result(
        self,
        uow: UnitOfWork,
        *,
        project_id: str,
        logical_key: str,
        handler: InboxSemanticHandler,
    ) -> ConsumeOutcome:
        """Apply the semantic effect of an inbox result exactly once.

        Delegates to :class:`InboxConsumer`.  The inbox handle is read from
        *uow*.
        """

        inbox = uow.inbox_repository
        if inbox is None:
            raise MissingRepositoryError("inbox_repository")
        consumer = InboxConsumer(inbox=inbox, handler=handler, clock=self.clock)
        return consumer.consume(project_id, logical_key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_cas_repository(uow: UnitOfWork, handle_name: str) -> Any:
        """Return the CAS repository named by *handle_name* from *uow*.

        Falls back to ``getattr`` so the coordinator works with any concrete
        UoW adapter, not just :class:`InMemoryUnitOfWork`.
        """

        repo = getattr(uow, handle_name, None)
        if repo is None:
            raise MissingRepositoryError(handle_name)
        return repo

    @staticmethod
    def _require_active_transaction(uow: UnitOfWork) -> None:
        """Fail before any write unless *uow* is inside ``with uow:``."""

        if not getattr(uow, "is_active", False):
            raise MutationAbortedError(
                "unit_of_work_inactive",
                UnitOfWorkClosedError(
                    "atomic mutation requires an active `with uow:` transaction"
                ),
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _default_utc_now() -> datetime:
    """Default clock: timezone-aware UTC ``datetime``."""

    from datetime import timezone

    return datetime.now(tz=timezone.utc)
