"""Transactional-outbox dispatcher with crash recovery and an explicit
state machine.

Design authority: Protocol v3 multi-agent rearchitecture, section 18.

    canonical mutation 与 outbox 在同一事务提交；外部副作用通过
    inbox/idempotency key 回写结果事件。 … 执行语义允许 at-least-once，但
    业务效果按 logical source、DecisionRecord CAS、artifact content address
    和 outbox 实现 exactly-once semantic effect。

This module orchestrates the *dispatch lifecycle* of outbox messages on top of
the storage-agnostic :class:`~app.protocol_workflow.ports.repositories.OutboxRepository`
and :class:`~app.protocol_workflow.ports.repositories.InboxRepository` ports.
It never modifies those ports; it consumes them.

Two responsibilities:

1. **Explicit state machine** — :class:`OutboxStateMachine` encodes the legal
   ``PENDING → DISPATCHED → COMPLETED | FAILED`` edges and rejects every other
   transition with :class:`IllegalOutboxTransitionError`.  The state machine is
   pure: it validates transitions and returns the target state without touching
   storage.

2. **Crash-recovery dispatcher** — :class:`OutboxDispatcher` drives the
   at-least-once dispatch loop.  After a crash that leaves a message in
   ``DISPATCHED`` (dispatched but never acknowledged), the dispatcher:

   * checks the inbox for an already-recorded result under the same
     ``logical_key`` — if present, the semantic effect already happened, so the
     outbox message is completed **without** re-dispatching (exactly-once
     semantic effect);
   * otherwise re-dispatches (at-least-once) and writes the result back to the
     inbox on success.

The dispatcher is the bridge between the outbox and inbox: a side effect is
acknowledged in the outbox only after its result is durable in the inbox, so
that a crash at any point yields a deterministic resume.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import RLock
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)

from app.protocol_workflow.ports.repositories import (
    AggregateNotFoundError,
    IdempotencyConflictError,
    InboxRepository,
    OutboxMessage,
    OutboxRepository,
    OutboxStatus,
    RepositoryStateTransitionError,
)

__all__ = [
    "DispatchOutcome",
    "DispatchOutcomeKind",
    "DispatchResult",
    "IllegalOutboxTransitionError",
    "InboxAlreadyRecorded",
    "OutboxDispatchError",
    "OutboxDispatcher",
    "OutboxRecoveryResult",
    "OutboxStateMachine",
    "SideEffectHandler",
    "recover_dispatched_messages",
]


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class IllegalOutboxTransitionError(RuntimeError):
    """Raised when an outbox state transition violates the legal edges.

    The state machine is explicit: only ``PENDING → DISPATCHED``,
    ``DISPATCHED → COMPLETED`` and ``DISPATCHED → FAILED`` are legal.
    ``PENDING → FAILED`` is permitted for pre-dispatch validation failures.
    Re-completing an already-terminal message is rejected: the caller must
    detect idempotent re-delivery before attempting the transition.
    """

    __slots__ = ("from_status", "to_status", "outbox_message_id", "logical_key")

    def __init__(
        self,
        from_status: OutboxStatus,
        to_status: OutboxStatus,
        *,
        outbox_message_id: str,
        logical_key: str,
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.outbox_message_id = outbox_message_id
        self.logical_key = logical_key
        super().__init__(
            f"illegal outbox transition {from_status.value} → {to_status.value} "
            f"for message {outbox_message_id} (logical_key={logical_key})"
        )


class OutboxDispatchError(RuntimeError):
    """Raised when the side-effect handler reports a dispatch failure.

    ``original`` carries the handler's exception so the dispatcher can surface
    a typed failure without losing the root cause.  The message stays in
    ``DISPATCHED`` (or transitions to ``FAILED`` depending on policy); the
    outbox is never silently advanced past a dispatch failure.
    """

    __slots__ = ("outbox_message_id", "logical_key", "original")

    def __init__(
        self,
        outbox_message_id: str,
        logical_key: str,
        original: Optional[BaseException] = None,
        detail: str = "",
    ) -> None:
        self.outbox_message_id = outbox_message_id
        self.logical_key = logical_key
        self.original = original
        label = f"dispatch failed for outbox message {outbox_message_id}"
        if logical_key:
            label += f" (logical_key={logical_key})"
        if detail:
            label += f": {detail}"
        super().__init__(label)


# ---------------------------------------------------------------------------
# Side-effect handler protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispatchResult:
    """The outcome of executing one side effect.

    ``result_sha256`` is the content identity of the external result.  It is
    written to the inbox so that replay of the same logical key + result is
    idempotent (design section 18).  ``payload`` is an optional opaque mapping
    the handler may return for the caller's own bookkeeping; it is not
    persisted by the dispatcher.
    """

    result_sha256: str
    payload: Optional[Mapping[str, Any]] = None


@runtime_checkable
class SideEffectHandler(Protocol):
    """Callable side-effect handler invoked by the dispatcher.

    Implementations receive the outbox message and MUST be idempotent under
    re-dispatch: the dispatcher may invoke the same handler multiple times for
    the same ``logical_key`` (at-least-once).  The inbox deduplicates result
    identity; the handler must also use the logical key idempotently for an
    exactly-once business effect across a crash before the inbox write.

    On success, return a :class:`DispatchResult` whose ``result_sha256`` is the
    content identity of the result.  On failure, raise an exception; the
    dispatcher records it and transitions the message to ``FAILED``.
    """

    def __call__(
        self, message: OutboxMessage
    ) -> DispatchResult:  # pragma: no cover - protocol
        ...


#: A callable handler, as an alternative to the :class:`SideEffectHandler`
#: protocol for callers that prefer a bare function.
HandlerFn = Callable[[OutboxMessage], DispatchResult]


# ---------------------------------------------------------------------------
# Explicit outbox state machine
# ---------------------------------------------------------------------------


#: Legal forward edges.  The terminal statuses ``COMPLETED`` and ``FAILED``
#: have no outgoing edges.  ``PENDING → FAILED`` is legal for pre-dispatch
#: validation failures (the side effect never ran).
_LEGAL_TRANSITIONS: Dict[OutboxStatus, FrozenSet[OutboxStatus]] = {
    OutboxStatus.PENDING: frozenset({OutboxStatus.DISPATCHED, OutboxStatus.FAILED}),
    OutboxStatus.DISPATCHED: frozenset({OutboxStatus.COMPLETED, OutboxStatus.FAILED}),
    OutboxStatus.COMPLETED: frozenset(),
    OutboxStatus.FAILED: frozenset(),
}

#: Terminal statuses with no legal outgoing transition.
_TERMINAL: FrozenSet[OutboxStatus] = frozenset(
    {OutboxStatus.COMPLETED, OutboxStatus.FAILED}
)


class OutboxStateMachine:
    """Pure validator for outbox message lifecycle transitions.

    The machine encodes the at-least-once dispatch discipline:

    * ``PENDING`` — message is enqueued but not yet claimed for dispatch.
    * ``DISPATCHED`` — a dispatcher has claimed the message and is executing
      (or has executed) the side effect.  A crash may leave a message here
      indefinitely; recovery resumes from this state.
    * ``COMPLETED`` — the side effect's result is durable in the inbox and the
      outbox message is acknowledged.  Terminal.
    * ``FAILED`` — the side effect failed and retry policy is exhausted (or the
      failure is permanent).  Terminal.

    Re-dispatching a ``DISPATCHED`` message (crash recovery) is *not* a state
    transition — the message stays ``DISPATCHED`` until the result is
    acknowledged.  This is what makes crash recovery deterministic: the
    inbox is the authority for "did the effect happen", not the outbox status.
    """

    __slots__ = ()

    @staticmethod
    def is_terminal(status: OutboxStatus) -> bool:
        """Return ``True`` iff *status* has no legal outgoing transition."""
        return status in _TERMINAL

    @staticmethod
    def legal_targets(from_status: OutboxStatus) -> FrozenSet[OutboxStatus]:
        """Return the set of statuses reachable from *from_status* in one edge."""
        return _LEGAL_TRANSITIONS.get(from_status, frozenset())

    @staticmethod
    def check_transition(
        from_status: OutboxStatus,
        to_status: OutboxStatus,
        *,
        outbox_message_id: str,
        logical_key: str,
    ) -> OutboxStatus:
        """Return *to_status* if the edge is legal, else raise.

        Raises
        ------
        IllegalOutboxTransitionError
            If the edge ``from_status → to_status`` is not in
            :data:`_LEGAL_TRANSITIONS`.
        """
        if to_status not in _LEGAL_TRANSITIONS.get(from_status, frozenset()):
            raise IllegalOutboxTransitionError(
                from_status,
                to_status,
                outbox_message_id=outbox_message_id,
                logical_key=logical_key,
            )
        return to_status


# ---------------------------------------------------------------------------
# Dispatch outcomes
# ---------------------------------------------------------------------------


class DispatchOutcomeKind(str, Enum):
    """Why a dispatch attempt resolved the way it did.

    * ``DISPATCHED`` — the side effect was executed and its result written to
      the inbox; the outbox message transitioned ``DISPATCHED → COMPLETED``.
    * ``SKIPPED_ALREADY_COMPLETED`` — the inbox already held a result for this
      logical key (crash between dispatch and ack); the outbox message
      transitioned ``DISPATCHED → COMPLETED`` **without** re-dispatching.
    * ``FAILED`` — the side effect raised and the message transitioned to
      ``FAILED``.
    * ``IDEMPOTENCY_CONFLICT`` — a *different* result hash arrived for the same
      logical key.  Fail closed: the message is marked ``FAILED`` and the
      conflict is surfaced.
    * ``DEFERRED_NO_HANDLER`` — no handler is currently configured.  The
      message remains ``DISPATCHED`` for a later recovery sweep; this is not a
      permanent failure.
    """

    DISPATCHED = "dispatched"
    SKIPPED_ALREADY_COMPLETED = "skipped_already_completed"
    FAILED = "failed"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    DEFERRED_NO_HANDLER = "deferred_no_handler"


@dataclass(frozen=True)
class InboxAlreadyRecorded:
    """Marker that the inbox already has a result for this logical key.

    Returned by the inbox check during crash recovery so the dispatcher can
    short-circuit re-dispatch.
    """

    result_sha256: str


@dataclass(frozen=True)
class DispatchOutcome:
    """The full outcome of one dispatch-and-acknowledge cycle.

    ``kind`` is the tri-state classification.  ``message`` is the final
    outbox message state after the transition.  ``inbox_result_sha256`` is the
    result hash recorded in the inbox (when applicable).
    """

    kind: DispatchOutcomeKind
    message: OutboxMessage
    inbox_result_sha256: Optional[str] = None
    error_detail: Optional[str] = None


# ---------------------------------------------------------------------------
# Recovery result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutboxRecoveryResult:
    """Summary of a crash-recovery sweep over dispatched messages.

    * ``recovered_completed`` — messages that were ``DISPATCHED`` but whose
      result was already in the inbox; completed without re-dispatch.
    * ``re_dispatched`` — messages that were ``DISPATCHED`` with no inbox
      result and were re-dispatched successfully.
    * ``still_dispatched`` — messages still ``DISPATCHED`` after the sweep
      (e.g. no handler supplied, or the handler is deferred to a later cycle).
    * ``failed`` — messages that failed permanently during recovery.
    """

    recovered_completed: Tuple[OutboxMessage, ...] = ()
    re_dispatched: Tuple[OutboxMessage, ...] = ()
    still_dispatched: Tuple[OutboxMessage, ...] = ()
    failed: Tuple[OutboxMessage, ...] = ()


# ---------------------------------------------------------------------------
# Outbox dispatcher
# ---------------------------------------------------------------------------


class OutboxDispatcher:
    """Drives the at-least-once dispatch loop with exactly-once semantic effect.

    The dispatcher claims ``PENDING`` messages from the outbox, executes the
    side effect, writes the result to the inbox, and then acknowledges the
    outbox.  The ordering guarantee (design section 18) is:

        outbox message transitions to ``COMPLETED`` only *after* the result is
        durable in the inbox.

    This means a crash at any point yields a deterministic resume:

    * crash before dispatch → message stays ``PENDING``; re-claimed later.
    * crash during dispatch → message stays ``DISPATCHED``; the inbox has no
      result (or the handler is idempotent); re-dispatched later.
    * crash after dispatch, before inbox write → message ``DISPATCHED``, no
      inbox result; re-dispatched (handler must be idempotent).
    * crash after inbox write, before outbox ack → message ``DISPATCHED``,
      inbox has result; recovery completes the outbox **without** re-dispatch.
    * crash after outbox ack → message ``COMPLETED``; nothing to do.

    Parameters
    ----------
    outbox:
        The transactional outbox repository (storage port).
    inbox:
        The idempotent inbox repository (storage port).
    handler:
        The side-effect handler invoked for each dispatched message.  Must be
        idempotent under re-dispatch.
    clock:
        Callable returning the current aware ``datetime`` for timestamps.  All
        timestamps originate from here; the dispatcher never reads the wall
        clock directly, making it deterministic under a fixed clock.
    """

    __slots__ = ("_outbox", "_inbox", "_handler", "_clock", "_lock")

    def __init__(
        self,
        *,
        outbox: OutboxRepository,
        inbox: InboxRepository,
        handler: Optional[SideEffectHandler] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._outbox = outbox
        self._inbox = inbox
        self._handler: Optional[SideEffectHandler] = handler
        self._clock: Callable[[], datetime] = clock or _default_utc_now
        self._lock = RLock()

    # ------------------------------------------------------------------
    # Claim-and-dispatch one batch
    # ------------------------------------------------------------------

    def dispatch_pending(
        self,
        project_id: str,
        *,
        limit: int = 10,
    ) -> Tuple[DispatchOutcome, ...]:
        """Claim up to *limit* ``PENDING`` messages and dispatch them.

        For each claimed message, the full claim → dispatch → inbox-write →
        ack cycle is executed atomically from the caller's perspective (the
        underlying UoW transaction is managed by the repository adapter).  If
        no handler is configured, claimed messages are returned to
        ``DISPATCHED`` but not executed — use :meth:`recover_dispatched` to
        execute them later once a handler is available.

        Returns a tuple of :class:`DispatchOutcome`, one per dispatched message.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1")
        with self._lock:
            claimed = self._outbox.claim_pending(
                project_id,
                limit=limit,
                claimed_at=self._clock(),
            )
            if not claimed:
                return ()
            outcomes: List[DispatchOutcome] = []
            for message in claimed:
                outcomes.append(self.acknowledge_one(message, project_id))
            return tuple(outcomes)

    # ------------------------------------------------------------------
    # Crash recovery: re-drive DISPATCHED messages
    # ------------------------------------------------------------------

    def recover_dispatched(
        self,
        project_id: str,
        messages: Optional[Sequence[OutboxMessage]] = None,
        *,
        limit: int = 100,
        handler: Optional[SideEffectHandler] = None,
    ) -> OutboxRecoveryResult:
        """Recover ``DISPATCHED`` messages left over from a crash.

        This is the core crash-recovery path.  A message that was dispatched
        but never acknowledged is deterministically resolved: either the
        result is already in the inbox (skip re-dispatch) or the effect is
        re-executed (at-least-once, but the inbox deduplicates).

        Two discovery modes (design section 18 restart recovery):

        * **Repository discovery (default):** when *messages* is ``None``, the
          dispatcher queries ``self._outbox.list_dispatched(project_id,
          limit=limit)`` to find recoverable work.  This is the deterministic
          restart path — a process that retained no in-memory objects can
          still discover and resolve DISPATCHED messages.
        * **Explicit messages:** when *messages* is provided, the dispatcher
          recovers exactly those objects.  This supports callers that retained
          pre-crash objects or that want to target specific messages.

        For each DISPATCHED message:

        1. Check the inbox for an existing result under the same
           ``logical_key``.  If present, the semantic effect already happened;
           complete the outbox **without** re-dispatching (exactly-once
           semantic effect).
        2. Otherwise, re-dispatch via *handler* (or the dispatcher's configured
           handler).  If no handler is available, leave the message
           ``DISPATCHED`` for a later cycle.

        Parameters
        ----------
        messages:
            Optional explicit sequence of messages to recover.  When ``None``
            (default), the dispatcher discovers DISPATCHED messages through
            the repository.
        limit:
            Maximum number of messages to recover in one sweep when
            discovering via the repository.  Ignored when *messages* is
            provided explicitly.
        handler:
            Optional override handler for this recovery sweep.
        """
        active_messages: Sequence[OutboxMessage]
        if messages is None:
            active_messages = self._outbox.list_dispatched(project_id, limit=limit)
        else:
            active_messages = messages

        active_handler = handler or self._handler
        recovered_completed: List[OutboxMessage] = []
        re_dispatched: List[OutboxMessage] = []
        still_dispatched: List[OutboxMessage] = []
        failed: List[OutboxMessage] = []
        processed_ids: set[str] = set()

        with self._lock:
            for message in active_messages:
                if message.project_id != project_id:
                    continue
                if message.status is not OutboxStatus.DISPATCHED:
                    continue

                outcome = self.acknowledge_one(
                    message, project_id, handler=active_handler
                )
                processed_ids.add(message.outbox_message_id)
                if outcome.kind is DispatchOutcomeKind.SKIPPED_ALREADY_COMPLETED:
                    recovered_completed.append(outcome.message)
                elif outcome.kind is DispatchOutcomeKind.DISPATCHED:
                    re_dispatched.append(outcome.message)
                elif outcome.kind is DispatchOutcomeKind.FAILED:
                    failed.append(outcome.message)
                elif outcome.kind is DispatchOutcomeKind.IDEMPOTENCY_CONFLICT:
                    failed.append(outcome.message)
                elif outcome.kind is DispatchOutcomeKind.DEFERRED_NO_HANDLER:
                    still_dispatched.append(outcome.message)
                else:  # pragma: no cover - defensive
                    still_dispatched.append(message)

            # Messages for which no handler was available remain DISPATCHED.
            # Detect by re-checking current stored state for messages we
            # processed but did not transition out of DISPATCHED.
            for message in active_messages:
                if message.outbox_message_id in processed_ids:
                    current = self._outbox.get(project_id, message.outbox_message_id)
                    if (
                        current is not None
                        and current.status is OutboxStatus.DISPATCHED
                        and current.outbox_message_id
                        not in {m.outbox_message_id for m in recovered_completed}
                        and current.outbox_message_id
                        not in {m.outbox_message_id for m in re_dispatched}
                        and current.outbox_message_id
                        not in {m.outbox_message_id for m in failed}
                        and current.outbox_message_id
                        not in {m.outbox_message_id for m in still_dispatched}
                    ):
                        still_dispatched.append(current)

            return OutboxRecoveryResult(
                recovered_completed=tuple(recovered_completed),
                re_dispatched=tuple(re_dispatched),
                still_dispatched=tuple(still_dispatched),
                failed=tuple(failed),
            )

    def recover_from_repository(
        self,
        project_id: str,
        *,
        limit: int = 100,
        handler: Optional[SideEffectHandler] = None,
    ) -> OutboxRecoveryResult:
        """Discover and recover DISPATCHED messages purely through the
        repository.

        This is the explicit restart-recovery entry point for a process that
        retained no in-memory ``OutboxMessage`` objects.  It calls
        ``list_dispatched`` on the outbox repository and then runs the same
        inbox-first acknowledgement cycle as :meth:`recover_dispatched`.

        Equivalent to ``recover_dispatched(project_id, messages=None,
        limit=limit, handler=handler)`` but named for clarity at the call
        site.
        """
        return self.recover_dispatched(project_id, None, limit=limit, handler=handler)

    # ------------------------------------------------------------------
    # Single-message inbox-first acknowledgement (public)
    # ------------------------------------------------------------------

    def acknowledge_one(
        self,
        message: OutboxMessage,
        project_id: str,
        *,
        handler: Optional[SideEffectHandler] = None,
    ) -> DispatchOutcome:
        """Execute the inbox-first dispatch → inbox-write → ack cycle for one
        message.

        This is the public single-message acknowledgement path.  Worker 03's
        unit-of-work integration and the recovery sweep both call this method
        rather than a private helper, so the inbox-first ordering guarantee is
        expressed through a stable public contract.

        The cycle is the same whether the message was just claimed
        (``PENDING → DISPATCHED``) or is being recovered (already
        ``DISPATCHED``):

        1. **Inbox-first short-circuit:** if the inbox already holds a result
           for ``message.logical_key``, the semantic effect already happened.
           The outbox is marked ``COMPLETED`` **without** re-dispatching.
        2. **Dispatch (at-least-once):** otherwise invoke the handler.  If no
           handler is configured, return ``DEFERRED_NO_HANDLER`` and leave the
           message ``DISPATCHED`` for a later recovery cycle.
        3. **Inbox write:** record the result hash.  Same hash is idempotent;
           a different hash raises :class:`IdempotencyConflictError` → fail
           closed.
        4. **Acknowledge:** mark the outbox ``COMPLETED`` only after the inbox
           write is durable.
        """

        # Resolve and validate the repository's authoritative lifecycle state
        # before any handler call or inbox write.  A caller-supplied stale or
        # forged message object must never trigger an external effect.
        persisted = self._outbox.get(project_id, message.outbox_message_id)
        if persisted is None:
            raise AggregateNotFoundError(
                project_id, aggregate_id=message.outbox_message_id
            )
        if persisted.status is not OutboxStatus.DISPATCHED:
            raise RepositoryStateTransitionError(
                project_id,
                persisted.outbox_message_id,
                from_status=persisted.status.value,
                to_status=OutboxStatus.COMPLETED.value,
            )
        message = persisted
        active_handler = handler or self._handler
        logical_key = message.logical_key

        # --- Crash-recovery short-circuit: inbox already has the result ---
        existing = self._inbox.get_result(project_id, logical_key)
        if existing is not None:
            # The semantic effect already happened.  Acknowledge the outbox
            # WITHOUT re-dispatching.  This is the exactly-once guarantee.
            completed = self._outbox.mark_completed(
                project_id,
                message.outbox_message_id,
                completed_at=self._clock(),
            )
            return DispatchOutcome(
                kind=DispatchOutcomeKind.SKIPPED_ALREADY_COMPLETED,
                message=completed,
                inbox_result_sha256=existing.result_sha256,
            )

        # --- No handler: leave DISPATCHED for a later cycle ---
        if active_handler is None:
            return DispatchOutcome(
                kind=DispatchOutcomeKind.DEFERRED_NO_HANDLER,
                message=message,
                error_detail="no side-effect handler configured",
            )

        # --- Dispatch (at-least-once) ---
        try:
            result: DispatchResult = active_handler(message)
        except Exception as exc:
            failed = self._outbox.mark_failed(
                project_id,
                message.outbox_message_id,
                error_detail=str(exc),
                failed_at=self._clock(),
            )
            return DispatchOutcome(
                kind=DispatchOutcomeKind.FAILED,
                message=failed,
                error_detail=str(exc),
            )

        # --- Write result to inbox (idempotent) ---
        # Same result hash → returns existing (idempotent).
        # Different result hash under same logical key → IdempotencyConflictError
        # → fail closed.
        try:
            self._inbox.record_result(
                project_id,
                logical_key,
                result.result_sha256,
                received_at=self._clock(),
            )
        except IdempotencyConflictError as conflict:
            # A different result arrived for the same logical key.  This is a
            # contract violation, not a retry.  Fail closed.
            failed = self._outbox.mark_failed(
                project_id,
                message.outbox_message_id,
                error_detail=(
                    f"idempotency conflict: logical_key={logical_key} "
                    f"existing={conflict.existing_sha256} "
                    f"incoming={conflict.incoming_sha256}"
                ),
                failed_at=self._clock(),
            )
            return DispatchOutcome(
                kind=DispatchOutcomeKind.IDEMPOTENCY_CONFLICT,
                message=failed,
                error_detail=str(conflict),
            )

        # --- Acknowledge outbox AFTER inbox write is durable ---
        completed = self._outbox.mark_completed(
            project_id,
            message.outbox_message_id,
            completed_at=self._clock(),
        )
        return DispatchOutcome(
            kind=DispatchOutcomeKind.DISPATCHED,
            message=completed,
            inbox_result_sha256=result.result_sha256,
        )


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def recover_dispatched_messages(
    *,
    outbox: OutboxRepository,
    inbox: InboxRepository,
    project_id: str,
    messages: Optional[Sequence[OutboxMessage]] = None,
    limit: int = 100,
    handler: Optional[SideEffectHandler] = None,
    clock: Optional[Callable[[], datetime]] = None,
) -> OutboxRecoveryResult:
    """Recover ``DISPATCHED`` outbox messages after a crash.

    Functional shortcut for constructing a one-shot
    :class:`OutboxDispatcher` and calling :meth:`recover_dispatched`.  Useful
    for restart-time recovery sweeps where a long-lived dispatcher is not
    needed.

    When *messages* is ``None`` (default), the function discovers DISPATCHED
    messages through ``outbox.list_dispatched`` — the deterministic restart
    path that requires no retained in-memory objects.
    """

    dispatcher = OutboxDispatcher(
        outbox=outbox,
        inbox=inbox,
        handler=handler,
        clock=clock,
    )
    return dispatcher.recover_dispatched(
        project_id, messages, limit=limit, handler=handler
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _default_utc_now() -> datetime:
    """Default clock: timezone-aware UTC ``datetime``.

    Tests inject a fixed clock for determinism; production wires a real clock.
    """
    from datetime import timezone

    return datetime.now(tz=timezone.utc)
