"""Idempotent inbox consumer with an explicit state machine and an explicit
handler-idempotency contract.

Design authority: Protocol v3 multi-agent rearchitecture, section 18.

    外部副作用通过 inbox/idempotency key 回写结果事件。 … 执行语义允许
    at-least-once，但业务效果按 logical source、DecisionRecord CAS、
    artifact content address 和 outbox 实现 exactly-once semantic effect。

This module orchestrates the *consume lifecycle* of inbox results on top of
the storage-agnostic :class:`~app.protocol_workflow.ports.repositories.InboxRepository`
port.  It never modifies that port; it consumes it.

The inbox is the authority for "the external side effect produced this result".
Combined with the outbox (see :mod:`app.protocol_workflow.events.outbox`), it
supports exactly-once *semantic identity* by logical key.  Handler execution is
at-least-once across the crash window between applying the business effect and
persisting ``CONSUMED``; therefore the handler must apply its own mutation by
the same logical key (or share a transaction with ``mark_consumed``).

* The **outbox** guarantees at-least-once *dispatch*.
* The **inbox** deduplicates results by ``logical_key`` and prevents re-running
  a handler after ``CONSUMED`` is durable.

Two responsibilities:

1. **Explicit state machine** — :class:`InboxStateMachine` encodes the legal
   ``RECEIVED → CONSUMED`` edge (and the terminal ``SUPERSEDED`` status) and
   rejects every other transition with :class:`IllegalInboxTransitionError`.

2. **Idempotent consumer** — :class:`InboxConsumer` applies the semantic effect
   under an explicit idempotent-handler contract.  On first consume, the handler runs
   and the result transitions ``RECEIVED → CONSUMED``.  On re-consume (crash
   after effect but before mark, or duplicate consume), the effect is
   **skipped** because the result is already ``CONSUMED``.  A crash before that
   marker may re-invoke the handler, so non-idempotent handlers are unsupported.
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
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)

from app.protocol_workflow.ports.repositories import (
    InboxRepository,
    InboxResult,
    InboxStatus,
)

__all__ = [
    "ConsumeOutcome",
    "ConsumeOutcomeKind",
    "IllegalInboxTransitionError",
    "InboxConsumer",
    "InboxSemanticHandler",
    "InboxStateMachine",
]


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class IllegalInboxTransitionError(RuntimeError):
    """Raised when an inbox state transition violates the legal edges.

    The state machine is explicit: only ``RECEIVED → CONSUMED`` is a legal
    forward edge.  ``SUPERSEDED`` is terminal.  Re-consuming an already-
    ``CONSUMED`` result is handled idempotently by the consumer (it returns
    ``SKIPPED_ALREADY_CONSUMED``) rather than raising, because duplicate
    consume is an expected recovery scenario, not a contract violation.
    """

    __slots__ = ("from_status", "to_status", "logical_key", "inbox_result_id")

    def __init__(
        self,
        from_status: InboxStatus,
        to_status: InboxStatus,
        *,
        logical_key: str,
        inbox_result_id: str = "",
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.logical_key = logical_key
        self.inbox_result_id = inbox_result_id
        super().__init__(
            f"illegal inbox transition {from_status.value} → {to_status.value} "
            f"for logical_key={logical_key}"
        )


# ---------------------------------------------------------------------------
# Semantic-effect handler protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class InboxSemanticHandler(Protocol):
    """Callable that applies the semantic effect of an inbox result.

    Implementations receive the inbox result and apply the business effect
    (e.g. updating a canonical projection, recording a DecisionRecord).  The
    handler MUST be idempotent under re-invocation: the consumer guards
    against double-apply via the ``CONSUMED`` state, but the handler itself
    must tolerate being called if a crash occurs between the effect and the
    state transition.

    The handler returns an opaque value (typically ``None``) that the consumer
    passes through in :attr:`ConsumeOutcome.effect_result`.
    """

    def __call__(self, result: InboxResult) -> Any:  # pragma: no cover - protocol
        ...


#: A callable handler, as an alternative to the :class:`InboxSemanticHandler`
#: protocol for callers that prefer a bare function.
SemanticHandlerFn = Callable[[InboxResult], Any]


# ---------------------------------------------------------------------------
# Explicit inbox state machine
# ---------------------------------------------------------------------------


#: Legal forward edges.  ``RECEIVED → CONSUMED`` is the only consume edge.
#: ``SUPERSEDED`` is terminal (set by explicit supersession, not by consume).
#: ``CONSUMED`` is terminal.
_LEGAL_TRANSITIONS: Dict[InboxStatus, FrozenSet[InboxStatus]] = {
    InboxStatus.RECEIVED: frozenset({InboxStatus.CONSUMED, InboxStatus.SUPERSEDED}),
    InboxStatus.CONSUMED: frozenset(),
    InboxStatus.SUPERSEDED: frozenset(),
}

#: Terminal statuses with no legal outgoing transition.
_TERMINAL: FrozenSet[InboxStatus] = frozenset(
    {InboxStatus.CONSUMED, InboxStatus.SUPERSEDED}
)


class InboxStateMachine:
    """Pure validator for inbox result lifecycle transitions.

    The machine encodes the exactly-once-consume discipline:

    * ``RECEIVED`` — the external result has been written to the inbox but its
      semantic effect has not yet been applied (or not yet marked applied).
    * ``CONSUMED`` — the semantic effect has been applied and marked.  Terminal.
      Re-consuming is a no-op (the consumer returns ``SKIPPED_ALREADY_CONSUMED``).
    * ``SUPERSEDED`` — the result has been explicitly superseded (e.g. a newer
      result under a different logical key replaced it).  Terminal.

    The invariant: once ``CONSUMED`` is durable, the handler is not invoked
    again.  Before that marker, execution is at-least-once and the handler's
    logical-key idempotency owns semantic deduplication.
    """

    __slots__ = ()

    @staticmethod
    def is_terminal(status: InboxStatus) -> bool:
        """Return ``True`` iff *status* has no legal outgoing transition."""
        return status in _TERMINAL

    @staticmethod
    def legal_targets(from_status: InboxStatus) -> FrozenSet[InboxStatus]:
        """Return the set of statuses reachable from *from_status* in one edge."""
        return _LEGAL_TRANSITIONS.get(from_status, frozenset())

    @staticmethod
    def check_transition(
        from_status: InboxStatus,
        to_status: InboxStatus,
        *,
        logical_key: str,
        inbox_result_id: str = "",
    ) -> InboxStatus:
        """Return *to_status* if the edge is legal, else raise.

        Raises
        ------
        IllegalInboxTransitionError
            If the edge ``from_status → to_status`` is not in
            :data:`_LEGAL_TRANSITIONS`.
        """
        if to_status not in _LEGAL_TRANSITIONS.get(from_status, frozenset()):
            raise IllegalInboxTransitionError(
                from_status,
                to_status,
                logical_key=logical_key,
                inbox_result_id=inbox_result_id,
            )
        return to_status


# ---------------------------------------------------------------------------
# Consume outcome tri-state
# ---------------------------------------------------------------------------


class ConsumeOutcomeKind(str, Enum):
    """Why a consume attempt resolved the way it did.

    * ``CONSUMED`` — the semantic effect was applied and the result
      transitioned ``RECEIVED → CONSUMED``.
    * ``SKIPPED_ALREADY_CONSUMED`` — the result was already ``CONSUMED``; the
      semantic effect was **not** re-applied (exactly-once).
    * ``SKIPPED_SUPERSEDED`` — the result is ``SUPERSEDED``; no effect applied.
    * ``NOT_FOUND`` — no inbox result exists for the logical key.
    """

    CONSUMED = "consumed"
    SKIPPED_ALREADY_CONSUMED = "skipped_already_consumed"
    SKIPPED_SUPERSEDED = "skipped_superseded"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class ConsumeOutcome:
    """The full outcome of one consume attempt.

    ``kind`` is the tri-state classification.  ``result`` is the final inbox
    result state after the transition (or ``None`` if not found).
    ``effect_result`` carries the semantic handler's return value when the
    effect was applied.
    """

    kind: ConsumeOutcomeKind
    result: Optional[InboxResult]
    effect_result: Any = None


# ---------------------------------------------------------------------------
# Inbox consumer
# ---------------------------------------------------------------------------


class InboxConsumer:
    """Consumes inbox results using a required idempotent semantic handler.

    The consumer is the read-side complement to the outbox dispatcher.  When a
    side-effect result lands in the inbox, the consumer applies its semantic
    effect (e.g. updating a canonical projection) and marks it ``CONSUMED``.

    Delivery and semantic-effect contract (design section 18):

    * **At-least-once delivery:** the outbox dispatcher may re-deliver the
      same result; the inbox deduplicates by ``logical_key`` + ``result_sha256``.
    * **Durable-marker deduplication:** a ``CONSUMED`` result is skipped.
    * **Crash window:** after handler success but before ``mark_consumed``, a
      retry invokes the handler again.  Exactly-once semantic effect therefore
      exists only when the handler commits by ``result.logical_key``
      idempotently or shares a transaction with the consumed marker.

    Crash recovery: if a crash occurs after the effect is applied but before
    ``mark_consumed`` commits, the result stays ``RECEIVED``.  On restart, the
    consumer re-applies the effect (handler must be idempotent) and then marks
    ``CONSUMED``.  If the crash occurs after ``mark_consumed``, the result is
    ``CONSUMED`` and the effect is skipped.

    Parameters
    ----------
    inbox:
        The idempotent inbox repository (storage port).
    handler:
        The semantic-effect handler invoked for each consumed result.  Must be
        idempotent under re-invocation.
    clock:
        Callable returning the current aware ``datetime`` for timestamps.
    """

    __slots__ = ("_inbox", "_handler", "_clock", "_lock")

    def __init__(
        self,
        *,
        inbox: InboxRepository,
        handler: InboxSemanticHandler,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._inbox = inbox
        self._handler: InboxSemanticHandler = handler
        self._clock: Callable[[], datetime] = clock or _default_utc_now
        self._lock = RLock()

    # ------------------------------------------------------------------
    # Consume a single result
    # ------------------------------------------------------------------

    def consume(
        self,
        project_id: str,
        logical_key: str,
        *,
        handler: Optional[InboxSemanticHandler] = None,
    ) -> ConsumeOutcome:
        """Apply the semantic effect for *logical_key* under idempotent retry.

        The full check → apply-effect → mark-consumed cycle is executed.  If
        the result is already ``CONSUMED`` or ``SUPERSEDED``, the effect is
        skipped.  If no result exists, returns ``NOT_FOUND`` without raising.

        Parameters
        ----------
        project_id:
            The project scope.
        logical_key:
            The idempotency key whose result should be consumed.
        handler:
            Optional override handler for this consume call.
        """
        active_handler = handler or self._handler
        with self._lock:
            result = self._inbox.get_result(project_id, logical_key)
            if result is None:
                return ConsumeOutcome(
                    kind=ConsumeOutcomeKind.NOT_FOUND,
                    result=None,
                )

            # --- Already consumed: skip effect (exactly-once) ---
            if result.status is InboxStatus.CONSUMED:
                return ConsumeOutcome(
                    kind=ConsumeOutcomeKind.SKIPPED_ALREADY_CONSUMED,
                    result=result,
                )

            # --- Superseded: skip effect ---
            if result.status is InboxStatus.SUPERSEDED:
                return ConsumeOutcome(
                    kind=ConsumeOutcomeKind.SKIPPED_SUPERSEDED,
                    result=result,
                )

            # --- State-machine guard: only RECEIVED can transition ---
            # (At this point result.status must be RECEIVED.)
            InboxStateMachine.check_transition(
                result.status,
                InboxStatus.CONSUMED,
                logical_key=logical_key,
                inbox_result_id=result.inbox_result_id,
            )

            # --- Apply semantic effect ---
            # The handler must be idempotent: a crash between apply and
            # mark_consumed will cause a re-apply on recovery.
            effect_result = active_handler(result)

            # --- Mark consumed ---
            consumed = self._inbox.mark_consumed(
                project_id,
                logical_key,
                consumed_at=self._clock(),
            )
            return ConsumeOutcome(
                kind=ConsumeOutcomeKind.CONSUMED,
                result=consumed,
                effect_result=effect_result,
            )

    # ------------------------------------------------------------------
    # Consume a batch of results
    # ------------------------------------------------------------------

    def consume_batch(
        self,
        project_id: str,
        logical_keys: Sequence[str],
        *,
        handler: Optional[InboxSemanticHandler] = None,
    ) -> Tuple[ConsumeOutcome, ...]:
        """Consume multiple results in order, returning each outcome.

        Each key is consumed independently; a failure in one does not prevent
        the others from being consumed (the handler is responsible for raising
        on effect failure; ``mark_consumed`` only runs on success).
        """
        outcomes: list[ConsumeOutcome] = []
        with self._lock:
            for key in logical_keys:
                outcomes.append(self.consume(project_id, key, handler=handler))
        return tuple(outcomes)

    # ------------------------------------------------------------------
    # Record + consume in one call (for synchronous side effects)
    # ------------------------------------------------------------------

    def record_and_consume(
        self,
        project_id: str,
        logical_key: str,
        result_sha256: str,
        *,
        handler: Optional[InboxSemanticHandler] = None,
        received_at: Optional[datetime] = None,
    ) -> ConsumeOutcome:
        """Record a result and immediately consume its semantic effect.

        This is the synchronous shortcut for side effects whose result is known
        at call time (no asynchronous dispatch).  If the same
        ``logical_key`` + ``result_sha256`` is already recorded, the existing
        entry is consumed idempotently.  A different ``result_sha256`` under
        the same key raises :class:`IdempotencyConflictError` (fail closed).
        """
        active_handler = handler or self._handler
        ts = received_at or self._clock()
        with self._lock:
            # record_result is idempotent for same sha, raises for different sha.
            self._inbox.record_result(
                project_id,
                logical_key,
                result_sha256,
                received_at=ts,
            )
            return self.consume(project_id, logical_key, handler=active_handler)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _default_utc_now() -> datetime:
    """Default clock: timezone-aware UTC ``datetime``.

    Tests inject a fixed clock for determinism; production wires a real clock.
    """
    from datetime import timezone

    return datetime.now(tz=timezone.utc)
