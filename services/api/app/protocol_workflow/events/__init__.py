"""Event authority kernel for Protocol v3.

This package is the event-sourcing / transactional-outbox authority layer for
Protocol v3 (design section 18).  It bundles four storage-agnostic modules:

* :mod:`events.models` — stable event envelope, canonical hashing, upcaster
  registry and replay-outcome tri-state.
* :mod:`events.store` — deterministic replay engine and checkpoint/event
  reconciliation.
* :mod:`events.outbox` — transactional-outbox dispatcher with crash recovery
  and an explicit idempotent-handler contract.
* :mod:`events.inbox` — idempotent inbox consumer with exactly-once semantic
  effect.
* :mod:`events.unit_of_work` — atomic mutation coordinator that performs CAS
  save, event append and outbox enqueue in one transaction.

The package imports only the frozen contracts, the pure canonical helpers, the
repository/UoW ports and the event-layer modules.  It has no storage-adapter,
network, clock or model dependency.
"""

from __future__ import annotations

from .models import (
    EventEnvelopeBuilder,
    EventEnvelopeError,
    EventEnvelopeIntegrityError,
    EventTypeRegistry,
    NondeterministicUpcasterError,
    PayloadHashMismatchError,
    RegistryFrozenError,
    QuarantineReason,
    QuarantineReplayResult,
    ReplayOutcome,
    SuccessfulReplayResult,
    UnknownEventTypeError,
    UnknownSchemaVersionError,
    UnknownUpcasterError,
    UpcasterRegistry,
    UpcasterSignature,
    compute_event_sha256,
    compute_payload_sha256,
    verify_event_integrity,
)
from .store import (
    CheckpointClaim,
    EventReplayEngine,
    ReducerApplyResult,
    ReducerFn,
    ReplayReducer,
    RevisionHashFn,
)
from .outbox import (
    DispatchOutcome,
    DispatchOutcomeKind,
    DispatchResult,
    IllegalOutboxTransitionError,
    InboxAlreadyRecorded,
    OutboxDispatchError,
    OutboxDispatcher,
    OutboxRecoveryResult,
    OutboxStateMachine,
    SideEffectHandler,
    recover_dispatched_messages,
)
from .inbox import (
    ConsumeOutcome,
    ConsumeOutcomeKind,
    IllegalInboxTransitionError,
    InboxConsumer,
    InboxSemanticHandler,
    InboxStateMachine,
)
from .unit_of_work import (
    AtomicMutationResult,
    EventSourcedUnitOfWork,
    MissingRepositoryError,
    MutationAbortedError,
    SideEffectRequest,
)

__all__ = [
    # models
    "EventEnvelopeBuilder",
    "EventEnvelopeError",
    "EventEnvelopeIntegrityError",
    "EventTypeRegistry",
    "NondeterministicUpcasterError",
    "PayloadHashMismatchError",
    "RegistryFrozenError",
    "QuarantineReason",
    "QuarantineReplayResult",
    "ReplayOutcome",
    "SuccessfulReplayResult",
    "UnknownEventTypeError",
    "UnknownSchemaVersionError",
    "UnknownUpcasterError",
    "UpcasterRegistry",
    "UpcasterSignature",
    "compute_event_sha256",
    "compute_payload_sha256",
    "verify_event_integrity",
    # store
    "CheckpointClaim",
    "EventReplayEngine",
    "ReducerApplyResult",
    "ReducerFn",
    "ReplayReducer",
    "RevisionHashFn",
    # outbox
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
    # inbox
    "ConsumeOutcome",
    "ConsumeOutcomeKind",
    "IllegalInboxTransitionError",
    "InboxConsumer",
    "InboxSemanticHandler",
    "InboxStateMachine",
    # unit_of_work
    "AtomicMutationResult",
    "EventSourcedUnitOfWork",
    "MissingRepositoryError",
    "MutationAbortedError",
    "SideEffectRequest",
]
