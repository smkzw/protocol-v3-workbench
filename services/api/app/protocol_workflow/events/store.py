"""Deterministic event replay engine and checkpoint reconciliation.

This module implements the authoritative replay and recovery layer for
Protocol v3 (design section 18):

* **Deterministic replay** — :meth:`EventReplayEngine.replay_stream` reads an
  append-only event stream, verifies every envelope's integrity and chain
  identity, migrates each payload through the registered upcasters, and folds
  the events through a pure reducer to reconstruct the canonical aggregate.
  The result carries the recomputed ``canonical_revision_sha256`` so callers
  can prove the replayed state matches the originally projected state.

* **Checkpoint / event reconciliation** —
  :meth:`EventReplayEngine.reconcile_checkpoint` enforces the design-section-18
  invariant that a checkpoint claiming completion is worthless without the
  corresponding committed event and artifact.  Two split-brain cases are
  detected and quarantined:

  1. *Event committed, checkpoint missing* — safe: resume from the event
     stream and skip effects already recorded in the inbox.
  2. *Checkpoint committed, event missing* — unsafe: quarantine immediately,
     never advance along the checkpoint.

* **Canonical hash rebuild** — :meth:`EventReplayEngine.rebuild_canonical_hash`
  recomputes the revision hash of a canonical aggregate from its event stream
  alone, proving the event log is sufficient to reconstruct business truth.

The engine is pure and storage-agnostic.  It reads events from any
:class:`EventStreamRepository` and consults the inbox through any
:class:`InboxRepository`, but holds no mutable state of its own and performs
no writes.  The caller (the application service, via the UoW) owns all
writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

from packages.contracts.workbench_contracts.protocol_v3 import (
    DomainEvent,
    JsonValue,
    SemanticDocumentRevision,
    StudyDefinitionV3,
)

from app.protocol_workflow.canonical.document import document_revision_hash
from app.protocol_workflow.canonical.study_definition import study_revision_hash

from app.protocol_workflow.events.models import (
    EventEnvelopeIntegrityError,
    EventTypeRegistry,
    NondeterministicUpcasterError,
    PayloadHashMismatchError,
    QuarantineReason,
    QuarantineReplayResult,
    ReplayOutcome,
    SuccessfulReplayResult,
    UnknownEventTypeError,
    UnknownSchemaVersionError,
    UnknownUpcasterError,
    UpcasterRegistry,
    UpcasterSignature,
    verify_event_integrity,
)

__all__ = [
    "CheckpointClaim",
    "EventReplayEngine",
    "ReducerFn",
    "ReplayReducer",
    "RevisionHashFn",
]


# ---------------------------------------------------------------------------
# Reducer protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReducerApplyResult:
    """Result of folding one migrated event payload through the reducer.

    ``new_state`` is the advanced canonical aggregate.  ``logical_key`` is the
    side-effect idempotency key this event would enqueue, if any (``None`` when
    the event has no side effect).  ``is_effect_completed`` should be ``True``
    when the caller already knows the effect is completed (e.g. from the
    inbox); the engine uses this to skip re-application on resume.
    """

    new_state: Any
    logical_key: Optional[str] = None


@runtime_checkable
class ReplayReducer(Protocol):
    """Pure reducer protocol for folding migrated event payloads.

    Implementations wrap a canonical reducer (e.g.
    :class:`StudyDefinitionReducer`) and adapt its method signature to the
    event-replay fold.  The reducer must be pure: given the same current state
    and the same migrated payload, it must always produce the same new state.
    """

    def initial_state(self) -> Any:
        """Return the canonical empty/initial aggregate for a fresh stream."""
        ...

    def apply(
        self,
        current: Any,
        migrated_payload: Mapping[str, JsonValue],
        event: DomainEvent,
    ) -> Any:
        """Fold *migrated_payload* onto *current* and return the new state."""
        ...

    def canonical_revision_hash(self, state: Any) -> str:
        """Return the canonical revision hash of *state*.

        This is the hash the replay engine compares against the originally
        projected hash to prove deterministic reconstructability.
        """
        ...


#: A callable reducer, as an alternative to the :class:`ReplayReducer`
#: protocol for callers that prefer a function-based fold.
ReducerFn = Callable[
    [Any, Mapping[str, JsonValue], DomainEvent],
    Any,
]

#: A callable that computes the canonical revision hash of a reducer state.
#: Required when a bare ``reducer_fn`` callable is used instead of a full
#: :class:`ReplayReducer`, since the engine cannot infer the correct
#: revision-hash convention from an arbitrary callable.
RevisionHashFn = Callable[[Any], str]


# ---------------------------------------------------------------------------
# Checkpoint claim
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckpointClaim:
    """A scheduler checkpoint's claim about a workflow node.

    ``node_id`` is the semantic node the checkpoint marks as complete.
    ``expected_event_type`` is the domain-event type the checkpoint asserts was
    committed for this node.  ``expected_artifact_sha256`` optionally binds an
    immutable artifact the checkpoint asserts was produced.

    Used by :meth:`EventReplayEngine.reconcile_checkpoint` to detect the
    checkpoint/event split-brain: a checkpoint claiming completion is
    authoritative only when its required event (and optional artifact) are
    present in the event stream.
    """

    node_id: str
    expected_event_type: str
    expected_event_sha256: str
    expected_artifact_sha256: Optional[str] = None
    expected_stream_id: Optional[str] = None


class _CanonicalRevisionHashMismatchError(RuntimeError):
    """Internal signal that replay used the wrong Task 1.4 hash convention."""


# ---------------------------------------------------------------------------
# Replay engine
# ---------------------------------------------------------------------------


class EventReplayEngine:
    """Pure, deterministic event-stream replay and checkpoint reconciliation.

    The engine is stateless and safe to share across threads.  It performs no
    storage writes and no clock reads; all timestamps come from the events
    themselves.  It is constructed with an :class:`UpcasterRegistry`, an
    :class:`EventTypeRegistry` (mandatory closed allow-list), and a
    :class:`ReplayReducer` (or a callable reducer).

    ``event_types`` is **mandatory**: there is no permissive default.  Every
    replayed event's ``event_type`` must be registered; unregistered types
    quarantine with :attr:`QuarantineReason.UNKNOWN_EVENT_TYPE`.

    When a bare ``reducer_fn`` callable is used instead of a full
    :class:`ReplayReducer`, the caller MUST also supply ``revision_hash_fn``
    so the engine computes the correct canonical revision hash.  The engine
    no longer falls back to ``ProtocolV3Model.material_sha256()``, which
    differs from the Task 1.4 ``study_revision_hash`` convention.
    """

    __slots__ = (
        "_upcasters",
        "_reducer",
        "_reducer_fn",
        "_event_types",
        "_revision_hash_fn",
    )

    def __init__(
        self,
        *,
        upcasters: UpcasterRegistry,
        event_types: EventTypeRegistry,
        reducer: Optional[ReplayReducer] = None,
        reducer_fn: Optional[ReducerFn] = None,
        revision_hash_fn: Optional[RevisionHashFn] = None,
    ) -> None:
        if (reducer is None) == (reducer_fn is None):
            raise ValueError("exactly one of reducer/reducer_fn is required")
        if reducer_fn is not None and revision_hash_fn is None:
            raise ValueError(
                "revision_hash_fn is required when reducer_fn is used; "
                "the engine does not fall back to material_sha256"
            )
        self._upcasters = upcasters
        self._reducer = reducer
        self._reducer_fn = reducer_fn
        self._event_types = event_types
        self._revision_hash_fn = revision_hash_fn
        # An engine is a closed-world replay appliance.  Once constructed, its
        # accepted event types and migration implementations cannot change.
        self._upcasters.freeze()
        self._event_types.freeze()

    # ------------------------------------------------------------------
    # Deterministic replay
    # ------------------------------------------------------------------

    def replay_stream(
        self,
        events: Sequence[DomainEvent],
        *,
        completed_logical_keys: Optional[Sequence[str]] = None,
        expected_stream_id: Optional[str] = None,
    ) -> ReplayOutcome:
        """Replay *events* deterministically through the reducer.

        ``completed_logical_keys`` is the set of side-effect logical keys
        already recorded in the inbox (design section 18: resume skips
        completed effects).  Events whose logical key is in this set are
        *counted* but their side effect is not re-dispatched — the reducer is
        still called so the canonical state advances correctly, but the key
        appears in ``skipped_completed_effects`` so the caller knows the
        effect was already applied.

        Returns :class:`ReplayOutcome`.  On success, the outcome's
        ``canonical_revision_sha256`` is the revision hash of the final
        rebuilt state.  On any integrity failure, unknown schema/upcaster, or
        reducer error, the outcome is quarantined with a stable
        :class:`QuarantineReason` and never advances.
        """

        completed_set = frozenset(completed_logical_keys or ())
        skipped: list[str] = []
        migrations: list[Optional[UpcasterSignature]] = []

        try:
            state = self._initial_state()
        except Exception as exc:  # pragma: no cover - defensive
            return ReplayOutcome(
                quarantine=QuarantineReplayResult(
                    reason=QuarantineReason.REPLAYER_ERROR,
                    failing_event_id=None,
                    detail=f"reducer initial_state raised: {exc}",
                )
            )

        previous_sha: Optional[str] = None
        previous_seq: int = 0
        events_replayed = 0
        replay_stream_id = expected_stream_id or (
            events[0].stream_id if events else None
        )

        for event in events:
            if replay_stream_id is not None and event.stream_id != replay_stream_id:
                return ReplayOutcome(
                    quarantine=QuarantineReplayResult(
                        reason=QuarantineReason.STREAM_ID_MISMATCH,
                        failing_event_id=event.domain_event_id,
                        detail=(
                            f"event {event.domain_event_id} belongs to stream "
                            f"{event.stream_id!r}; replay is bound to "
                            f"{replay_stream_id!r}"
                        ),
                        events_replayed_before_failure=events_replayed,
                        partial_state=state,
                    )
                )
            # --- Chain integrity: sequence + predecessor -------------------
            expected_prev: Optional[str]
            if event.sequence == 1:
                expected_prev = None
            else:
                expected_prev = previous_sha
            if event.previous_event_sha256 != expected_prev:
                return self._quarantine_chain(event, events_replayed, state)
            if event.sequence != previous_seq + 1:
                # Sequence must be strictly ascending with no gaps.
                return self._quarantine_chain(event, events_replayed, state)

            # --- Envelope hash verification --------------------------------
            try:
                verify_event_integrity(event)
            except PayloadHashMismatchError as exc:
                return ReplayOutcome(
                    quarantine=QuarantineReplayResult(
                        reason=QuarantineReason.PAYLOAD_HASH_MISMATCH,
                        failing_event_id=event.domain_event_id,
                        detail=str(exc),
                        events_replayed_before_failure=events_replayed,
                        partial_state=state,
                    )
                )
            except EventEnvelopeIntegrityError as exc:
                return ReplayOutcome(
                    quarantine=QuarantineReplayResult(
                        reason=QuarantineReason.EVENT_HASH_MISMATCH,
                        failing_event_id=event.domain_event_id,
                        detail=str(exc),
                        events_replayed_before_failure=events_replayed,
                        partial_state=state,
                    )
                )

            # --- Event-type allow-list (fail closed, always enforced) ------
            try:
                self._event_types.assert_registered(event.event_type)
            except UnknownEventTypeError as exc:
                return ReplayOutcome(
                    quarantine=QuarantineReplayResult(
                        reason=QuarantineReason.UNKNOWN_EVENT_TYPE,
                        failing_event_id=event.domain_event_id,
                        detail=str(exc),
                        events_replayed_before_failure=events_replayed,
                        partial_state=state,
                    )
                )

            # --- Schema / upcaster migration (fail closed) ----------------
            try:
                migrated_payload, applied_sig = self._upcasters.migrate(event)
            except UnknownSchemaVersionError as exc:
                return ReplayOutcome(
                    quarantine=QuarantineReplayResult(
                        reason=QuarantineReason.UNKNOWN_SCHEMA_VERSION,
                        failing_event_id=event.domain_event_id,
                        detail=str(exc),
                        events_replayed_before_failure=events_replayed,
                        partial_state=state,
                    )
                )
            except UnknownUpcasterError as exc:
                return ReplayOutcome(
                    quarantine=QuarantineReplayResult(
                        reason=QuarantineReason.UNKNOWN_UPCASTER,
                        failing_event_id=event.domain_event_id,
                        detail=str(exc),
                        events_replayed_before_failure=events_replayed,
                        partial_state=state,
                    )
                )
            except NondeterministicUpcasterError as exc:
                return ReplayOutcome(
                    quarantine=QuarantineReplayResult(
                        reason=QuarantineReason.NONDETERMINISTIC_UPCASTER,
                        failing_event_id=event.domain_event_id,
                        detail=str(exc),
                        events_replayed_before_failure=events_replayed,
                        partial_state=state,
                    )
                )

            migrations.append(applied_sig)

            # --- Reducer fold ---------------------------------------------
            logical_key = _extract_logical_key(migrated_payload)
            if logical_key is not None and logical_key in completed_set:
                skipped.append(logical_key)

            try:
                state = self._apply(state, migrated_payload, event)
            except Exception as exc:
                return ReplayOutcome(
                    quarantine=QuarantineReplayResult(
                        reason=QuarantineReason.REPLAYER_ERROR,
                        failing_event_id=event.domain_event_id,
                        detail=f"reducer raised while folding event "
                        f"{event.domain_event_id}: {exc}",
                        events_replayed_before_failure=events_replayed,
                        partial_state=state,
                    )
                )

            previous_sha = event.event_sha256
            previous_seq = event.sequence
            events_replayed += 1

        # --- Compute canonical revision hash of the rebuilt state -------
        try:
            revision_hash = self._revision_hash(state)
        except _CanonicalRevisionHashMismatchError as exc:
            return ReplayOutcome(
                quarantine=QuarantineReplayResult(
                    reason=QuarantineReason.REVISION_HASH_MISMATCH,
                    failing_event_id=None,
                    detail=str(exc),
                    events_replayed_before_failure=events_replayed,
                    partial_state=state,
                )
            )
        except Exception as exc:
            return ReplayOutcome(
                quarantine=QuarantineReplayResult(
                    reason=QuarantineReason.REPLAYER_ERROR,
                    failing_event_id=None,
                    detail=f"reducer canonical_revision_hash raised: {exc}",
                    events_replayed_before_failure=events_replayed,
                    partial_state=state,
                )
            )

        return ReplayOutcome(
            success=SuccessfulReplayResult(
                final_state=state,
                canonical_revision_sha256=revision_hash,
                events_replayed=events_replayed,
                skipped_completed_effects=tuple(skipped),
                migrations_applied=tuple(migrations),
            )
        )

    # ------------------------------------------------------------------
    # Checkpoint / event reconciliation
    # ------------------------------------------------------------------

    def reconcile_checkpoint(
        self,
        claim: CheckpointClaim,
        events: Sequence[DomainEvent],
        *,
        artifact_sha256_present: Optional[Callable[[str], bool]] = None,
    ) -> ReplayOutcome:
        """Reconcile a checkpoint's completion claim against the event stream.

        Implements the two split-brain cases from design section 18:

        * **Checkpoint claims complete, event missing → quarantine.**
          The checkpoint alone can never prove business completion.  If the
          required ``expected_event_type`` is absent from the event stream
          (optionally scoped to ``expected_stream_id``), or the required
          artifact is absent, replay is quarantined with
          :attr:`QuarantineReason.CHECKPOINT_EVENT_MISMATCH` and the workflow
          never advances.

        * **Event committed, checkpoint missing → resume.**
          This case is *not* a reconciliation failure; the caller detects it
          by noticing the event is present but no checkpoint exists, and
          simply resumes from the event stream via :meth:`replay_stream`.
          :meth:`reconcile_checkpoint` is only called *when* a checkpoint
          exists.

        Returns a :class:`ReplayOutcome`.  Success means the checkpoint's
        claim is backed by the required event (and optional artifact); the
        outcome's ``final_state`` is ``None``.  Before success, the complete
        event prefix through the backing event is replayed twice and its
        canonical revision hash compared.  This prevents a checkpoint from
        accepting an unreplayable predecessor or a pairwise-stable but
        stateful upcaster.  Quarantine means the checkpoint is untrustworthy
        and must fail closed.
        """

        # A checkpoint can only be reconciled against an intact, single-stream
        # chain.  Type-only matching would let a tampered or unrelated event
        # prove completion, so verify the evidence before selecting the exact
        # backing event.
        previous_sha: Optional[str] = None
        previous_seq = 0
        evidence_stream_id = claim.expected_stream_id or (
            events[0].stream_id if events else None
        )
        for evt in events:
            if evidence_stream_id is not None and evt.stream_id != evidence_stream_id:
                return self._checkpoint_mismatch(
                    claim,
                    f"event {evt.domain_event_id} belongs to stream "
                    f"{evt.stream_id!r}, expected {evidence_stream_id!r}",
                    failing_event_id=evt.domain_event_id,
                )
            if (
                evt.sequence != previous_seq + 1
                or evt.previous_event_sha256 != previous_sha
            ):
                return self._checkpoint_mismatch(
                    claim,
                    f"event {evt.domain_event_id} breaks the checkpoint evidence chain",
                    failing_event_id=evt.domain_event_id,
                )
            try:
                verify_event_integrity(evt)
            except EventEnvelopeIntegrityError as exc:
                return self._checkpoint_mismatch(
                    claim,
                    f"event {evt.domain_event_id} fails envelope integrity: {exc}",
                    failing_event_id=evt.domain_event_id,
                )
            previous_sha = evt.event_sha256
            previous_seq = evt.sequence

        matching = [
            (index, evt)
            for index, evt in enumerate(events)
            if evt.event_type == claim.expected_event_type
            and evt.event_sha256 == claim.expected_event_sha256
            and (
                claim.expected_stream_id is None
                or evt.stream_id == claim.expected_stream_id
            )
        ]
        if not matching:
            return self._checkpoint_mismatch(
                claim,
                f"no exact event type={claim.expected_event_type!r} "
                f"sha256={claim.expected_event_sha256!r} exists in the stream",
            )
        backing_index, backing_event = matching[0]
        try:
            self._event_types.assert_registered(backing_event.event_type)
        except UnknownEventTypeError as exc:
            return self._checkpoint_mismatch(
                claim, str(exc), failing_event_id=backing_event.domain_event_id
            )
        if backing_event.payload.get("node_id") != claim.node_id:
            return self._checkpoint_mismatch(
                claim,
                f"backing event payload is not bound to node {claim.node_id!r}",
                failing_event_id=backing_event.domain_event_id,
            )
        if claim.expected_artifact_sha256 is not None:
            if (
                backing_event.payload.get("artifact_sha256")
                != claim.expected_artifact_sha256
            ):
                return self._checkpoint_mismatch(
                    claim,
                    "backing event payload does not bind the checkpoint artifact "
                    f"{claim.expected_artifact_sha256}",
                    failing_event_id=backing_event.domain_event_id,
                )
            checker = artifact_sha256_present or (lambda _sha: False)
            if not checker(claim.expected_artifact_sha256):
                return self._checkpoint_mismatch(
                    claim,
                    f"artifact {claim.expected_artifact_sha256} is not present "
                    "in the artifact store",
                    failing_event_id=backing_event.domain_event_id,
                )

        # A structurally valid backing event is not enough: every predecessor
        # that produced it must be replayable under the same closed registries
        # and reducer.  Run the immutable prefix twice.  The second pass is a
        # deliberate stability check that exposes stateful upcasters/reducers
        # whose first paired invocation happens to match persisted evidence.
        evidence_prefix = tuple(events[: backing_index + 1])
        first_replay = self.replay_stream(
            evidence_prefix,
            expected_stream_id=evidence_stream_id,
        )
        if first_replay.is_quarantined:
            assert first_replay.quarantine is not None
            return self._checkpoint_mismatch(
                claim,
                "checkpoint evidence prefix cannot be replayed: "
                f"{first_replay.quarantine.reason.value}: "
                f"{first_replay.quarantine.detail}",
                failing_event_id=first_replay.quarantine.failing_event_id,
            )
        second_replay = self.replay_stream(
            evidence_prefix,
            expected_stream_id=evidence_stream_id,
        )
        if second_replay.is_quarantined:
            assert second_replay.quarantine is not None
            return self._checkpoint_mismatch(
                claim,
                "checkpoint evidence prefix is not replay-stable: "
                f"{second_replay.quarantine.reason.value}: "
                f"{second_replay.quarantine.detail}",
                failing_event_id=second_replay.quarantine.failing_event_id,
            )
        assert first_replay.success is not None
        assert second_replay.success is not None
        if (
            first_replay.success.canonical_revision_sha256
            != second_replay.success.canonical_revision_sha256
        ):
            return self._checkpoint_mismatch(
                claim,
                "checkpoint evidence prefix produced different canonical "
                "revision hashes across isolated replays",
                failing_event_id=backing_event.domain_event_id,
            )

        # Checkpoint is backed by its required event/artifact and a stable,
        # fully replayable evidence prefix.
        return ReplayOutcome(
            success=SuccessfulReplayResult(
                final_state=None,
                canonical_revision_sha256=(
                    first_replay.success.canonical_revision_sha256
                ),
                events_replayed=len(evidence_prefix),
            )
        )

    # ------------------------------------------------------------------
    # Canonical hash rebuild
    # ------------------------------------------------------------------

    def rebuild_canonical_hash(
        self,
        events: Sequence[DomainEvent],
        *,
        completed_logical_keys: Optional[Sequence[str]] = None,
    ) -> ReplayOutcome:
        """Rebuild the canonical revision hash from the event stream alone.

        Equivalent to :meth:`replay_stream` but discards the rebuilt state,
        returning only the ``canonical_revision_sha256``.  This proves the
        event log is sufficient to reconstruct business truth (design section
        18: canonical state can be rebuilt from events and immutable
        artifacts).
        """

        return self.replay_stream(
            events,
            completed_logical_keys=completed_logical_keys,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _initial_state(self) -> Any:
        if self._reducer is not None:
            return self._reducer.initial_state()
        # For reducer_fn callers, the initial state is None; the function is
        # expected to handle the None-start case on the first event.
        return None

    def _apply(
        self,
        state: Any,
        migrated_payload: Mapping[str, JsonValue],
        event: DomainEvent,
    ) -> Any:
        if self._reducer is not None:
            return self._reducer.apply(state, migrated_payload, event)
        assert self._reducer_fn is not None
        return self._reducer_fn(state, migrated_payload, event)

    def _revision_hash(self, state: Any) -> str:
        if self._reducer is not None:
            computed = self._reducer.canonical_revision_hash(state)
        else:
            # reducer_fn callers must supply revision_hash_fn at construction
            # time; the engine does not fall back to material_sha256.
            assert self._reducer_fn is not None and self._revision_hash_fn is not None
            computed = self._revision_hash_fn(state)

        authoritative: Optional[str] = None
        if isinstance(state, StudyDefinitionV3):
            authoritative = study_revision_hash(state)
        elif isinstance(state, SemanticDocumentRevision):
            authoritative = document_revision_hash(state)
        if authoritative is not None and computed != authoritative:
            raise _CanonicalRevisionHashMismatchError(
                "replay reducer returned a non-authoritative Task 1.4 revision "
                f"hash: computed={computed} authoritative={authoritative}"
            )
        return computed

    @staticmethod
    def _checkpoint_mismatch(
        claim: CheckpointClaim,
        detail: str,
        *,
        failing_event_id: Optional[str] = None,
    ) -> ReplayOutcome:
        return ReplayOutcome(
            quarantine=QuarantineReplayResult(
                reason=QuarantineReason.CHECKPOINT_EVENT_MISMATCH,
                failing_event_id=failing_event_id,
                detail=f"checkpoint for node {claim.node_id!r}: {detail}",
                expected_logical_keys=(),
            )
        )

    def _quarantine_chain(
        self,
        event: DomainEvent,
        events_replayed: int,
        state: Any,
    ) -> ReplayOutcome:
        return ReplayOutcome(
            quarantine=QuarantineReplayResult(
                reason=QuarantineReason.BROKEN_CHAIN,
                failing_event_id=event.domain_event_id,
                detail=(
                    f"event {event.domain_event_id} (sequence={event.sequence}) "
                    f"breaks the append-only chain: "
                    f"previous_event_sha256={event.previous_event_sha256!r}"
                ),
                events_replayed_before_failure=events_replayed,
                partial_state=state,
            )
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_logical_key(payload: Mapping[str, JsonValue]) -> Optional[str]:
    """Extract the side-effect logical key from a migrated event payload.

    The logical key is the idempotency key under which a side effect is
    recorded in the outbox/inbox.  Events without a side effect have no key.
    The field name follows the domain convention used by the outbox ports.
    """

    value = payload.get("logical_key")
    if isinstance(value, str) and value:
        return value
    return None
