"""Functional tests for the Protocol v3 event replay engine, upcaster
registry, checkpoint/event reconciliation and canonical hash rebuild.

These tests verify the design-section-18 authority/recovery contract:

* Event construction recomputes payload/event hashes and enforces chain
  identity.
* Unknown event schema or missing/nondeterministic upcaster fails closed into
  quarantine; replay never guesses.
* Valid replay is deterministic and reconstructs the same canonical revision
  hash.
* A committed event with a missing checkpoint resumes from the event stream
  and skips already-recorded effects.
* A checkpoint claiming completion without its required event/artifact is
  quarantined and never advances.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

import pytest

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    CanonicalState,
    DomainEvent,
    StudyDefinitionV3,
)
from app.protocol_workflow.canonical.hashing import (
    exact_payload_sha256,
)
from app.protocol_workflow.canonical.study_definition import (
    study_revision_hash,
)
from app.protocol_workflow.events.models import (
    EventEnvelopeBuilder,
    EventEnvelopeIntegrityError,
    EventTypeRegistry,
    NondeterministicUpcasterError,
    PayloadHashMismatchError,
    QuarantineReason,
    RegistryFrozenError,
    UnknownEventTypeError,
    UnknownSchemaVersionError,
    UnknownUpcasterError,
    UpcasterRegistry,
    UpcasterSignature,
    compute_event_sha256,
    compute_payload_sha256,
    verify_event_integrity,
)
from app.protocol_workflow.events.store import (
    CheckpointClaim,
    EventReplayEngine,
    ReplayReducer,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
_T2 = datetime(2026, 1, 3, tzinfo=timezone.utc)

_CURRENT_SCHEMA = "mw_protocol_v3_event_v1"
_LEGACY_SCHEMA_V0 = "mw_protocol_v3_event_v0"


def _builder() -> EventEnvelopeBuilder:
    return EventEnvelopeBuilder()


def _registry() -> UpcasterRegistry:
    reg = UpcasterRegistry(current_schema_version=_CURRENT_SCHEMA)
    reg.register_noop(_CURRENT_SCHEMA)
    return reg


def _registry_with_legacy_upcaster() -> UpcasterRegistry:
    """Registry that knows how to migrate ``_LEGACY_SCHEMA_V0`` events."""

    reg = _registry()

    def migrate_v0_to_v1(payload: Mapping[str, Any]) -> Dict[str, Any]:
        # Deterministic rename: old_payload -> payload
        result = dict(payload)
        if "old_revision" in result:
            result["revision"] = result.pop("old_revision")
        return result

    reg.register(
        UpcasterSignature(_LEGACY_SCHEMA_V0, "v0_to_v1:migrate"), migrate_v0_to_v1
    )
    return reg


def _build_stream(
    builder: EventEnvelopeBuilder,
    *,
    stream_id: str = "stream:test:1",
    count: int = 3,
    event_type: str = "study_definition.revised",
    payload_base: Optional[Dict[str, Any]] = None,
) -> List[DomainEvent]:
    """Build a valid chain of *count* events using *builder*."""

    payload_base = payload_base or {}
    events: List[DomainEvent] = []
    prev_sha: Optional[str] = None
    for i in range(1, count + 1):
        payload = {**payload_base, "revision": i}
        if i == 1:
            evt = builder.build(
                domain_event_id=f"evt:{i}",
                stream_id=stream_id,
                sequence=1,
                event_type=event_type,
                payload_schema_version=_CURRENT_SCHEMA,
                upcaster_id="noop:v1",
                actor_type=ActorType.AI,
                actor_id="agent:corpus:1",
                action="revise",
                reason=f"test-revision-{i}",
                payload=payload,
                emitted_at=_T0,
            )
        else:
            evt = builder.continue_chain(
                head_sha256=prev_sha,
                head_sequence=i - 1,
                domain_event_id=f"evt:{i}",
                stream_id=stream_id,
                event_type=event_type,
                payload_schema_version=_CURRENT_SCHEMA,
                upcaster_id="noop:v1",
                actor_type=ActorType.AI,
                actor_id="agent:corpus:1",
                action="revise",
                reason=f"test-revision-{i}",
                payload=payload,
                emitted_at=_T0,
            )
        events.append(evt)
        prev_sha = evt.event_sha256
    return events


class _CounterReducer:
    """Minimal pure reducer for testing: counts events and tracks max revision."""

    def initial_state(self) -> Dict[str, Any]:
        return {"count": 0, "max_revision": 0, "logical_keys": ()}

    def apply(
        self,
        current: Any,
        migrated_payload: Mapping[str, Any],
        event: DomainEvent,
    ) -> Any:
        return {
            "count": current["count"] + 1,
            "max_revision": max(
                current["max_revision"], int(migrated_payload.get("revision", 0))
            ),
            "logical_keys": current["logical_keys"]
            + (migrated_payload.get("logical_key", ""),),
        }

    def canonical_revision_hash(self, state: Any) -> str:
        return exact_payload_sha256(state)


def _event_types(
    extra: Optional[List[str]] = None,
) -> EventTypeRegistry:
    """Build the default test event-type registry.

    Every event type used by the test suite is registered here.  Tests that
    use exotic types can pass *extra* to add them.
    """

    types = [
        "study_definition.revised",
        "test",
        "source.downloaded",
        "node.completed",
        "node.started",
    ]
    if extra:
        types.extend(extra)
    return EventTypeRegistry(types)


def _engine(
    registry: Optional[UpcasterRegistry] = None,
    reducer: Optional[ReplayReducer] = None,
    event_types: Optional[EventTypeRegistry] = None,
) -> EventReplayEngine:
    return EventReplayEngine(
        upcasters=registry or _registry(),
        event_types=event_types or _event_types(),
        reducer=reducer or _CounterReducer(),
    )


# ---------------------------------------------------------------------------
# Event envelope construction and hash verification
# ---------------------------------------------------------------------------


class TestEventEnvelopeHashes:
    """The envelope builder fills canonical payload and event hashes."""

    def test_build_first_event_computes_hashes(self) -> None:
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:test:1",
            sequence=1,
            event_type="study_definition.revised",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="agent:corpus:1",
            action="revise",
            reason="test",
            payload={"revision": 1},
            emitted_at=_T0,
        )
        assert evt.payload_sha256 == compute_payload_sha256({"revision": 1})
        # event_sha256 is non-trivial (not all zeros)
        assert evt.event_sha256 != "0" * 64
        assert len(evt.event_sha256) == 64

    def test_build_verifies_successfully(self) -> None:
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:test:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="system:scheduler:1",
            action="checkpoint",
            reason="test",
            payload={"node": "n1"},
            emitted_at=_T0,
        )
        verify_event_integrity(evt)  # must not raise

    def test_continue_chain_links_predecessor(self) -> None:
        builder = _builder()
        e1 = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:test:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={"node_id": "node:chapter:1"},
            emitted_at=_T0,
        )
        e2 = builder.continue_chain(
            head_sha256=e1.event_sha256,
            head_sequence=1,
            domain_event_id="evt:2",
            stream_id="stream:test:1",
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={},
            emitted_at=_T1,
        )
        assert e2.sequence == 2
        assert e2.previous_event_sha256 == e1.event_sha256
        verify_event_integrity(e2)

    def test_hashing_is_deterministic(self) -> None:
        """The same inputs always produce the same event hashes."""
        builder = _builder()
        kwargs = dict(
            domain_event_id="evt:1",
            stream_id="stream:test:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={"revision": 1},
            emitted_at=_T0,
        )
        e1 = builder.build(**kwargs)
        e2 = builder.build(**kwargs)
        assert e1.event_sha256 == e2.event_sha256
        assert e1.payload_sha256 == e2.payload_sha256

    def test_payload_hash_is_order_invariant(self) -> None:
        """Payload hashing must be invariant to dict insertion order."""
        h1 = compute_payload_sha256({"a": 1, "b": 2})
        h2 = compute_payload_sha256({"b": 2, "a": 1})
        assert h1 == h2

    def test_event_hash_is_timezone_environment_independent(self) -> None:
        """Equivalent aware instants use one fixed UTC representation."""

        builder = _builder()
        kwargs = dict(
            domain_event_id="evt:tz",
            stream_id="stream:tz:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="system:1",
            action="hash",
            reason="timezone-stability",
            payload={"revision": 1},
        )
        utc_event = builder.build(emitted_at=_T0, **kwargs)
        china_event = builder.build(
            emitted_at=_T0.astimezone(timezone(timedelta(hours=8))), **kwargs
        )
        assert utc_event.event_sha256 == china_event.event_sha256

    def test_tampered_payload_is_detected(self) -> None:
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:test:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={"revision": 1},
            emitted_at=_T0,
        )
        tampered = evt.model_copy(update={"payload": {"revision": 999}})
        # payload changed but payload_sha256 still points at the original
        with pytest.raises(PayloadHashMismatchError):
            verify_event_integrity(tampered)

    def test_tampered_event_hash_is_detected(self) -> None:
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:test:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={"revision": 1},
            emitted_at=_T0,
        )
        tampered = evt.model_copy(update={"event_sha256": "f" * 64})
        with pytest.raises(EventEnvelopeIntegrityError):
            verify_event_integrity(tampered)


# ---------------------------------------------------------------------------
# Upcaster registry
# ---------------------------------------------------------------------------


class TestUpcasterRegistry:
    """The upcaster registry accepts known schemas and rejects unknown ones."""

    def test_noop_migrate_at_current_schema(self) -> None:
        reg = _registry()
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={"revision": 1},
            emitted_at=_T0,
        )
        payload, applied = reg.migrate(evt)
        assert payload == {"revision": 1}
        assert applied is None  # no migration needed at current schema

    def test_current_schema_with_non_noop_upcaster_fails(self) -> None:
        reg = _registry()
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="bogus:v1",  # wrong for current schema
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={},
            emitted_at=_T0,
        )
        with pytest.raises(UnknownUpcasterError):
            reg.migrate(evt)

    def test_unknown_schema_version_fails_closed(self) -> None:
        reg = _registry()
        evt = DomainEvent(
            domain_event_id="evt:u",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version="totally_unknown_v9",
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={},
            payload_sha256=compute_payload_sha256({}),
            previous_event_sha256=None,
            event_sha256="0" * 64,
            emitted_at=_T0,
        )
        # Fix the event hash so integrity passes, then migrate should fail
        evt = evt.model_copy(update={"event_sha256": compute_event_sha256(evt)})
        with pytest.raises(UnknownSchemaVersionError):
            reg.migrate(evt)

    def test_legacy_schema_migrates_deterministically(self) -> None:
        reg = _registry_with_legacy_upcaster()
        evt = DomainEvent(
            domain_event_id="evt:l",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_LEGACY_SCHEMA_V0,
            upcaster_id="v0_to_v1:migrate",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={"old_revision": 5},
            payload_sha256=compute_payload_sha256({"old_revision": 5}),
            migrated_payload_sha256=exact_payload_sha256({"revision": 5}),
            previous_event_sha256=None,
            event_sha256="0" * 64,
            emitted_at=_T0,
        )
        evt = evt.model_copy(update={"event_sha256": compute_event_sha256(evt)})
        payload, applied = reg.migrate(evt)
        assert payload == {"revision": 5}
        assert applied is not None
        assert applied.upcaster_id == "v0_to_v1:migrate"

    def test_duplicate_registration_same_fn_is_idempotent(self) -> None:
        reg = _registry()

        def migrate(payload: Mapping[str, Any]) -> Dict[str, Any]:
            return dict(payload)

        sig = UpcasterSignature(_LEGACY_SCHEMA_V0, "idempotent:v1")
        reg.register(sig, migrate)
        reg.register(sig, migrate)  # must not raise

    def test_duplicate_registration_different_fn_rejected(self) -> None:
        reg = _registry()

        def migrate_a(payload: Mapping[str, Any]) -> Dict[str, Any]:
            return dict(payload)

        def migrate_b(payload: Mapping[str, Any]) -> Dict[str, Any]:
            result = dict(payload)
            result["extra"] = True
            return result

        sig = UpcasterSignature(_LEGACY_SCHEMA_V0, "conflict:v1")
        reg.register(sig, migrate_a)
        with pytest.raises(ValueError, match="different implementation"):
            reg.register(sig, migrate_b)


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------


class TestDeterministicReplay:
    """Valid replay reconstructs the same canonical revision hash."""

    def test_replay_three_event_stream(self) -> None:
        builder = _builder()
        events = _build_stream(builder, count=3)
        engine = _engine()
        outcome = engine.replay_stream(events)
        assert not outcome.is_quarantined
        result = outcome.success
        assert result.events_replayed == 3
        assert result.final_state["count"] == 3
        assert result.final_state["max_revision"] == 3

    def test_replay_is_deterministic(self) -> None:
        """Replaying the same event stream twice yields the same hash."""
        builder = _builder()
        events = _build_stream(builder, count=5)
        engine = _engine()
        o1 = engine.replay_stream(events)
        o2 = engine.replay_stream(events)
        assert (
            o1.success.canonical_revision_sha256 == o2.success.canonical_revision_sha256
        )

    def test_replay_empty_stream(self) -> None:
        engine = _engine()
        outcome = engine.replay_stream([])
        assert not outcome.is_quarantined
        assert outcome.success.events_replayed == 0
        assert outcome.success.final_state["count"] == 0

    def test_replay_partial_stream_from_sequence_1(self) -> None:
        """Replaying a prefix of the stream succeeds; the engine does not
        require the stream to be 'complete', only internally consistent."""
        builder = _builder()
        events = _build_stream(builder, count=3)
        engine = _engine()
        # Replay only the first two events (a valid prefix)
        outcome = engine.replay_stream(events[:2])
        assert not outcome.is_quarantined
        assert outcome.success.events_replayed == 2

    def test_replay_suffix_without_head_quarantines(self) -> None:
        """Replaying events starting at sequence 2 without event 1 breaks
        the chain: event 2's previous_event_sha256 points at event 1, which
        is absent.  This is correct fail-closed behavior."""
        builder = _builder()
        events = _build_stream(builder, count=3)
        engine = _engine()
        outcome = engine.replay_stream(events[1:])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.BROKEN_CHAIN


# ---------------------------------------------------------------------------
# Canonical hash rebuild
# ---------------------------------------------------------------------------


class TestCanonicalHashRebuild:
    """The canonical revision hash can be rebuilt from the event stream alone."""

    def test_rebuild_matches_replay(self) -> None:
        builder = _builder()
        events = _build_stream(builder, count=4)
        engine = _engine()
        replay_outcome = engine.replay_stream(events)
        rebuild_outcome = engine.rebuild_canonical_hash(events)
        assert not replay_outcome.is_quarantined
        assert not rebuild_outcome.is_quarantined
        assert (
            replay_outcome.success.canonical_revision_sha256
            == rebuild_outcome.success.canonical_revision_sha256
        )

    def test_rebuild_changes_when_stream_changes(self) -> None:
        builder = _builder()
        events_3 = _build_stream(builder, count=3)
        events_5 = _build_stream(builder, count=5, stream_id="stream:test:2")
        engine = _engine()
        hash_3 = engine.rebuild_canonical_hash(
            events_3
        ).success.canonical_revision_sha256
        hash_5 = engine.rebuild_canonical_hash(
            events_5
        ).success.canonical_revision_sha256
        assert hash_3 != hash_5


# ---------------------------------------------------------------------------
# Quarantine — unknown schema / upcaster
# ---------------------------------------------------------------------------


class TestQuarantineUnknownSchema:
    """Unknown event schema or upcaster fails closed into quarantine."""

    def test_unknown_schema_version_quarantines(self) -> None:
        reg = _registry()
        builder = _builder()
        # Build a valid event at the current schema, then tamper the schema
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={},
            emitted_at=_T0,
        )
        # Change schema version to unknown — need to recompute event hash
        tampered = evt.model_copy(
            update={
                "payload_schema_version": "unknown_v9",
                "upcaster_id": "mystery:v1",
            }
        )
        tampered = tampered.model_copy(
            update={"event_sha256": compute_event_sha256(tampered)}
        )
        engine = _engine(registry=reg)
        outcome = engine.replay_stream([tampered])
        assert outcome.is_quarantined
        q = outcome.quarantine
        assert q.reason in (
            QuarantineReason.UNKNOWN_SCHEMA_VERSION,
            QuarantineReason.UNKNOWN_UPCASTER,
        )
        assert q.failing_event_id == "evt:1"
        assert q.events_replayed_before_failure == 0

    def test_known_schema_unknown_upcaster_quarantines(self) -> None:
        reg = _registry_with_legacy_upcaster()
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={},
            emitted_at=_T0,
        )
        # Change to legacy schema but unknown upcaster
        tampered = evt.model_copy(
            update={
                "payload_schema_version": _LEGACY_SCHEMA_V0,
                "upcaster_id": "nonexistent:v9",
            }
        )
        tampered = tampered.model_copy(
            update={"event_sha256": compute_event_sha256(tampered)}
        )
        engine = _engine(registry=reg)
        outcome = engine.replay_stream([tampered])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.UNKNOWN_UPCASTER


# ---------------------------------------------------------------------------
# Quarantine — broken chain, hash mismatch
# ---------------------------------------------------------------------------


class TestQuarantineBrokenChain:
    """Broken chain integrity, hash mismatch and sequence gaps quarantine."""

    def test_broken_previous_event_chain_quarantines(self) -> None:
        builder = _builder()
        e1 = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={},
            emitted_at=_T0,
        )
        e2_bad = builder.build(
            domain_event_id="evt:2",
            stream_id="stream:t:1",
            sequence=2,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={},
            emitted_at=_T1,
            previous_event_sha256="e" * 64,  # wrong predecessor
        )
        engine = _engine()
        outcome = engine.replay_stream([e1, e2_bad])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.BROKEN_CHAIN
        assert outcome.quarantine.failing_event_id == "evt:2"
        assert outcome.quarantine.events_replayed_before_failure == 1

    def test_sequence_gap_quarantines(self) -> None:
        builder = _builder()
        e1 = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={},
            emitted_at=_T0,
        )
        # Skip sequence 2, jump to 3 with correct predecessor link
        e3 = builder.build(
            domain_event_id="evt:3",
            stream_id="stream:t:1",
            sequence=3,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={},
            emitted_at=_T1,
            previous_event_sha256=e1.event_sha256,
        )
        engine = _engine()
        outcome = engine.replay_stream([e1, e3])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.BROKEN_CHAIN

    def test_payload_hash_mismatch_quarantines(self) -> None:
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={"revision": 1},
            emitted_at=_T0,
        )
        # Tamper the payload but keep the original (now stale) payload_sha256
        tampered = evt.model_copy(update={"payload": {"revision": 999}})
        engine = _engine()
        outcome = engine.replay_stream([tampered])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.PAYLOAD_HASH_MISMATCH

    def test_event_hash_mismatch_quarantines(self) -> None:
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={},
            emitted_at=_T0,
        )
        tampered = evt.model_copy(update={"event_sha256": "d" * 64})
        engine = _engine()
        outcome = engine.replay_stream([tampered])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.EVENT_HASH_MISMATCH


# ---------------------------------------------------------------------------
# Resume — event committed, checkpoint missing
# ---------------------------------------------------------------------------


class TestResumeFromEventStream:
    """A committed event with a missing checkpoint resumes and skips
    completed effects."""

    def test_resume_skips_completed_effect(self) -> None:
        """When a side-effect logical key is in the completed set, replay
        records it as skipped but still advances canonical state."""
        builder = _builder()
        e1 = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="source.downloaded",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="system:1",
            action="download",
            reason="r",
            payload={"revision": 1, "logical_key": "se:download:42"},
            emitted_at=_T0,
        )
        e2 = builder.continue_chain(
            head_sha256=e1.event_sha256,
            head_sequence=1,
            domain_event_id="evt:2",
            stream_id="stream:t:1",
            event_type="source.downloaded",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="system:1",
            action="download",
            reason="r",
            payload={"revision": 2, "logical_key": "se:download:99"},
            emitted_at=_T1,
        )
        engine = _engine()
        outcome = engine.replay_stream(
            [e1, e2],
            completed_logical_keys=["se:download:42"],
        )
        assert not outcome.is_quarantined
        assert outcome.success.events_replayed == 2
        assert "se:download:42" in outcome.success.skipped_completed_effects
        assert "se:download:99" not in outcome.success.skipped_completed_effects

    def test_resume_does_not_skip_uncompleted_effect(self) -> None:
        builder = _builder()
        e1 = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="source.downloaded",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="system:1",
            action="download",
            reason="r",
            payload={"revision": 1, "logical_key": "se:download:1"},
            emitted_at=_T0,
        )
        engine = _engine()
        outcome = engine.replay_stream([e1])
        assert not outcome.is_quarantined
        assert outcome.success.skipped_completed_effects == ()

    def test_resume_advances_canonical_state(self) -> None:
        """Even when effects are skipped, the canonical state still reflects
        all events — the reducer is always called."""
        builder = _builder()
        events = _build_stream(builder, count=3)
        # Add logical keys
        events_with_keys: List[DomainEvent] = []
        prev_sha: Optional[str] = None
        for i, evt in enumerate(events, 1):
            payload = {"revision": i, "logical_key": f"se:effect:{i}"}
            if prev_sha is None:
                new_evt = _builder().build(
                    domain_event_id=f"evt:k{i}",
                    stream_id="stream:t:1",
                    sequence=i,
                    event_type="test",
                    payload_schema_version=_CURRENT_SCHEMA,
                    upcaster_id="noop:v1",
                    actor_type=ActorType.SYSTEM,
                    actor_id="s:1",
                    action="act",
                    reason="r",
                    payload=payload,
                    emitted_at=_T0,
                )
            else:
                new_evt = _builder().continue_chain(
                    head_sha256=prev_sha,
                    head_sequence=i - 1,
                    domain_event_id=f"evt:k{i}",
                    stream_id="stream:t:1",
                    event_type="test",
                    payload_schema_version=_CURRENT_SCHEMA,
                    upcaster_id="noop:v1",
                    actor_type=ActorType.SYSTEM,
                    actor_id="s:1",
                    action="act",
                    reason="r",
                    payload=payload,
                    emitted_at=_T0,
                )
            events_with_keys.append(new_evt)
            prev_sha = new_evt.event_sha256

        engine = _engine()
        outcome = engine.replay_stream(
            events_with_keys,
            completed_logical_keys=["se:effect:1", "se:effect:2"],
        )
        assert not outcome.is_quarantined
        assert outcome.success.final_state["count"] == 3
        assert len(outcome.success.skipped_completed_effects) == 2


# ---------------------------------------------------------------------------
# Checkpoint / event reconciliation
# ---------------------------------------------------------------------------


class TestCheckpointReconciliation:
    """Checkpoint/event split-brain detection."""

    def test_checkpoint_backed_by_event_succeeds(self) -> None:
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:wr:1",
            sequence=1,
            event_type="node.completed",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="scheduler:1",
            action="complete",
            reason="r",
            payload={"node_id": "node:chapter:1"},
            emitted_at=_T0,
        )
        claim = CheckpointClaim(
            node_id="node:chapter:1",
            expected_event_type="node.completed",
            expected_event_sha256=evt.event_sha256,
        )
        engine = _engine()
        outcome = engine.reconcile_checkpoint(claim, [evt])
        assert not outcome.is_quarantined
        assert outcome.success.events_replayed == 1

    def test_checkpoint_without_event_quarantines(self) -> None:
        """Case 2 from the split-brain fixture: checkpoint committed, event
        missing → fail closed."""
        claim = CheckpointClaim(
            node_id="node:chapter:1",
            expected_event_type="node.completed",
            expected_event_sha256="a" * 64,
        )
        engine = _engine()
        outcome = engine.reconcile_checkpoint(claim, [])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.CHECKPOINT_EVENT_MISMATCH
        assert "node:chapter:1" in outcome.quarantine.detail

    def test_checkpoint_with_wrong_event_type_quarantines(self) -> None:
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:wr:1",
            sequence=1,
            event_type="node.started",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="scheduler:1",
            action="start",
            reason="r",
            payload={"node_id": "node:chapter:1"},
            emitted_at=_T0,
        )
        claim = CheckpointClaim(
            node_id="node:chapter:1",
            expected_event_type="node.completed",  # different type
            expected_event_sha256=evt.event_sha256,
        )
        engine = _engine()
        outcome = engine.reconcile_checkpoint(claim, [evt])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.CHECKPOINT_EVENT_MISMATCH

    def test_checkpoint_with_missing_artifact_quarantines(self) -> None:
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:wr:1",
            sequence=1,
            event_type="node.completed",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="scheduler:1",
            action="complete",
            reason="r",
            payload={
                "node_id": "node:chapter:1",
                "artifact_sha256": "a" * 64,
            },
            emitted_at=_T0,
        )
        claim = CheckpointClaim(
            node_id="node:chapter:1",
            expected_event_type="node.completed",
            expected_event_sha256=evt.event_sha256,
            expected_artifact_sha256="a" * 64,
        )
        engine = _engine()
        outcome = engine.reconcile_checkpoint(claim, [evt])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.CHECKPOINT_EVENT_MISMATCH

    def test_checkpoint_with_event_and_artifact_succeeds(self) -> None:
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:wr:1",
            sequence=1,
            event_type="node.completed",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="scheduler:1",
            action="complete",
            reason="r",
            payload={
                "node_id": "node:chapter:1",
                "artifact_sha256": "a" * 64,
            },
            emitted_at=_T0,
        )
        claim = CheckpointClaim(
            node_id="node:chapter:1",
            expected_event_type="node.completed",
            expected_event_sha256=evt.event_sha256,
            expected_artifact_sha256="a" * 64,
        )
        engine = _engine()
        artifacts = {"a" * 64}
        outcome = engine.reconcile_checkpoint(
            claim,
            [evt],
            artifact_sha256_present=lambda sha: sha in artifacts,
        )
        assert not outcome.is_quarantined

    def test_checkpoint_scoped_to_stream(self) -> None:
        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:wr:1",
            sequence=1,
            event_type="node.completed",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="scheduler:1",
            action="complete",
            reason="r",
            payload={"node_id": "node:chapter:1"},
            emitted_at=_T0,
        )
        # Correct stream → success
        claim_ok = CheckpointClaim(
            node_id="node:chapter:1",
            expected_event_type="node.completed",
            expected_event_sha256=evt.event_sha256,
            expected_stream_id="stream:wr:1",
        )
        engine = _engine()
        assert not engine.reconcile_checkpoint(claim_ok, [evt]).is_quarantined

        # Wrong stream → quarantine
        claim_bad = CheckpointClaim(
            node_id="node:chapter:1",
            expected_event_type="node.completed",
            expected_event_sha256=evt.event_sha256,
            expected_stream_id="stream:other:1",
        )
        assert engine.reconcile_checkpoint(claim_bad, [evt]).is_quarantined

    def test_checkpoint_rejects_wrong_node_and_artifact_binding(self) -> None:
        evt = _builder().build(
            domain_event_id="evt:bound",
            stream_id="stream:wr:1",
            sequence=1,
            event_type="node.completed",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="scheduler:1",
            action="complete",
            reason="r",
            payload={"node_id": "node:other", "artifact_sha256": "b" * 64},
            emitted_at=_T0,
        )
        claim = CheckpointClaim(
            node_id="node:chapter:1",
            expected_event_type="node.completed",
            expected_event_sha256=evt.event_sha256,
            expected_artifact_sha256="a" * 64,
            expected_stream_id="stream:wr:1",
        )
        outcome = _engine().reconcile_checkpoint(
            claim, [evt], artifact_sha256_present=lambda _sha: True
        )
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.CHECKPOINT_EVENT_MISMATCH

    def test_checkpoint_rejects_tampered_backing_event(self) -> None:
        evt = _builder().build(
            domain_event_id="evt:tampered",
            stream_id="stream:wr:1",
            sequence=1,
            event_type="node.completed",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="scheduler:1",
            action="complete",
            reason="r",
            payload={"node_id": "node:chapter:1"},
            emitted_at=_T0,
        )
        tampered = evt.model_copy(update={"event_sha256": "f" * 64})
        claim = CheckpointClaim(
            node_id="node:chapter:1",
            expected_event_type="node.completed",
            expected_event_sha256="f" * 64,
            expected_stream_id="stream:wr:1",
        )
        outcome = _engine().reconcile_checkpoint(claim, [tampered])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.CHECKPOINT_EVENT_MISMATCH

    def test_checkpoint_rejects_event_with_unknown_schema(self) -> None:
        """A checkpoint cannot accept evidence that authoritative replay
        would quarantine for an unknown schema."""

        evt = _builder().build(
            domain_event_id="evt:unknown-schema",
            stream_id="stream:wr:1",
            sequence=1,
            event_type="node.completed",
            payload_schema_version="mw_protocol_v3_event_unknown",
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="scheduler:1",
            action="complete",
            reason="r",
            payload={"node_id": "node:chapter:1"},
            emitted_at=_T0,
        )
        claim = CheckpointClaim(
            node_id="node:chapter:1",
            expected_event_type="node.completed",
            expected_event_sha256=evt.event_sha256,
            expected_stream_id="stream:wr:1",
        )
        outcome = _engine().reconcile_checkpoint(claim, [evt])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.CHECKPOINT_EVENT_MISMATCH
        assert "cannot be replayed" in outcome.quarantine.detail

    def test_checkpoint_rejects_unreplayable_predecessor(self) -> None:
        """A valid backing event cannot hide an unknown-schema predecessor."""

        builder = _builder()
        prefix = builder.build(
            domain_event_id="evt:unknown-prefix",
            stream_id="stream:wr:1",
            sequence=1,
            event_type="node.started",
            payload_schema_version="mw_protocol_v3_event_unknown",
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="scheduler:1",
            action="start",
            reason="r",
            payload={"node_id": "node:chapter:1"},
            emitted_at=_T0,
        )
        backing = builder.continue_chain(
            head_sha256=prefix.event_sha256,
            head_sequence=prefix.sequence,
            domain_event_id="evt:completed",
            stream_id="stream:wr:1",
            event_type="node.completed",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="scheduler:1",
            action="complete",
            reason="r",
            payload={"node_id": "node:chapter:1"},
            emitted_at=_T1,
        )
        claim = CheckpointClaim(
            node_id="node:chapter:1",
            expected_event_type="node.completed",
            expected_event_sha256=backing.event_sha256,
            expected_stream_id="stream:wr:1",
        )
        outcome = _engine().reconcile_checkpoint(claim, [prefix, backing])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.CHECKPOINT_EVENT_MISMATCH
        assert "unknown_schema_version" in outcome.quarantine.detail

    def test_checkpoint_rejects_pairwise_stateful_upcaster(self) -> None:
        """Two replay passes expose an upcaster whose output is stable only
        within each pair of calls."""

        calls = {"n": 0}

        def pairwise_stateful(payload: Mapping[str, Any]) -> Dict[str, Any]:
            run = calls["n"] // 2
            calls["n"] += 1
            return {**payload, "migration_run": run}

        registry = UpcasterRegistry(current_schema_version=_CURRENT_SCHEMA)
        registry.register_noop(_CURRENT_SCHEMA)
        registry.register(
            UpcasterSignature(_LEGACY_SCHEMA_V0, "pairwise-checkpoint:v1"),
            pairwise_stateful,
        )
        migrated = {
            "node_id": "node:chapter:1",
            "old_revision": 1,
            "migration_run": 0,
        }
        evt = _builder().build(
            domain_event_id="evt:pairwise-checkpoint",
            stream_id="stream:wr:1",
            sequence=1,
            event_type="node.completed",
            payload_schema_version=_LEGACY_SCHEMA_V0,
            upcaster_id="pairwise-checkpoint:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="scheduler:1",
            action="complete",
            reason="r",
            payload={"node_id": "node:chapter:1", "old_revision": 1},
            migrated_payload_sha256=exact_payload_sha256(migrated),
            emitted_at=_T0,
        )
        claim = CheckpointClaim(
            node_id="node:chapter:1",
            expected_event_type="node.completed",
            expected_event_sha256=evt.event_sha256,
            expected_stream_id="stream:wr:1",
        )
        outcome = _engine(registry=registry).reconcile_checkpoint(claim, [evt])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.CHECKPOINT_EVENT_MISMATCH
        assert "not replay-stable" in outcome.quarantine.detail


# ---------------------------------------------------------------------------
# Reducer error quarantine
# ---------------------------------------------------------------------------


class TestReducerErrorQuarantine:
    """A reducer that raises during fold quarantines the stream."""

    def test_reducer_error_quarantines(self) -> None:
        class ExplodingReducer:
            def initial_state(self) -> Any:
                return {"count": 0}

            def apply(
                self, current: Any, payload: Mapping[str, Any], event: DomainEvent
            ) -> Any:
                raise RuntimeError("boom")

            def canonical_revision_hash(self, state: Any) -> str:
                return exact_payload_sha256(state)

        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={},
            emitted_at=_T0,
        )
        engine = EventReplayEngine(
            upcasters=_registry(),
            event_types=_event_types(),
            reducer=ExplodingReducer(),
        )
        outcome = engine.replay_stream([evt])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.REPLAYER_ERROR
        assert "boom" in outcome.quarantine.detail


# ---------------------------------------------------------------------------
# Integration with StudyDefinitionV3 canonical hash
# ---------------------------------------------------------------------------


class TestStudyDefinitionHashRebuild:
    """The replay engine rebuilds the Task 1.4 ``study_revision_hash`` via a
    ``reducer_fn`` that operates on ``StudyDefinitionV3`` state.

    The engine requires an explicit ``revision_hash_fn`` when a bare
    ``reducer_fn`` is used.  The canonical revision hash is Task 1.4
    ``study_revision_hash``, NOT ``material_sha256``.
    """

    def test_reducer_fn_with_explicit_revision_hash(self) -> None:
        """The engine computes ``study_revision_hash`` when the caller
        supplies ``revision_hash_fn=study_revision_hash``."""

        def _study_definition_reducer(
            current: Optional[StudyDefinitionV3],
            migrated_payload: Mapping[str, Any],
            event: DomainEvent,
        ) -> StudyDefinitionV3:
            revision = int(migrated_payload.get("revision", 1))
            if current is None:
                return _build_study(revision=1)
            return _build_study(
                revision=revision,
                previous_revision_sha256=study_revision_hash(current),
            )

        builder = _builder()
        events = _build_stream(builder, count=3)
        engine = EventReplayEngine(
            upcasters=_registry(),
            event_types=_event_types(),
            reducer_fn=_study_definition_reducer,
            revision_hash_fn=study_revision_hash,
        )
        outcome = engine.replay_stream(events)
        assert not outcome.is_quarantined
        result = outcome.success
        assert result.events_replayed == 3
        assert isinstance(result.final_state, StudyDefinitionV3)
        # The canonical_revision_sha256 must equal study_revision_hash, not
        # material_sha256.
        expected_hash = study_revision_hash(result.final_state)
        assert result.canonical_revision_sha256 == expected_hash
        assert result.canonical_revision_sha256 != result.final_state.material_sha256()

    def test_reducer_fn_without_revision_hash_raises(self) -> None:
        """Supplying ``reducer_fn`` without ``revision_hash_fn`` raises
        ``ValueError`` at construction time."""

        def _reducer(
            current: Any, payload: Mapping[str, Any], event: DomainEvent
        ) -> Any:
            return _build_study(revision=1)

        with pytest.raises(ValueError, match="revision_hash_fn"):
            EventReplayEngine(
                upcasters=_registry(),
                event_types=_event_types(),
                reducer_fn=_reducer,
            )

    def test_wrong_study_revision_hash_function_quarantines(self) -> None:
        """A generic material hash cannot impersonate Task 1.4 authority."""

        def _reducer(
            current: Optional[StudyDefinitionV3],
            payload: Mapping[str, Any],
            event: DomainEvent,
        ) -> StudyDefinitionV3:
            if current is None:
                return _build_study(revision=1)
            return _build_study(
                revision=int(payload.get("revision", 1)),
                previous_revision_sha256=study_revision_hash(current),
            )

        outcome = EventReplayEngine(
            upcasters=_registry(),
            event_types=_event_types(),
            reducer_fn=_reducer,
            revision_hash_fn=lambda state: state.material_sha256(),
        ).replay_stream(_build_stream(_builder(), count=2))
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.REVISION_HASH_MISMATCH

    def test_reducer_fn_deterministic(self) -> None:
        """Replaying the same stream twice yields the same
        ``study_revision_hash``."""

        def _reducer(
            current: Optional[StudyDefinitionV3],
            payload: Mapping[str, Any],
            event: DomainEvent,
        ) -> StudyDefinitionV3:
            if current is None:
                return _build_study(revision=1)
            return _build_study(
                revision=int(payload.get("revision", 1)),
                previous_revision_sha256=study_revision_hash(current),
            )

        builder = _builder()
        events = _build_stream(builder, count=3)
        engine = EventReplayEngine(
            upcasters=_registry(),
            event_types=_event_types(),
            reducer_fn=_reducer,
            revision_hash_fn=study_revision_hash,
        )
        o1 = engine.replay_stream(events)
        o2 = engine.replay_stream(events)
        assert not o1.is_quarantined
        assert not o2.is_quarantined
        assert (
            o1.success.canonical_revision_sha256 == o2.success.canonical_revision_sha256
        )

    def test_rebuild_matches_original_projection(self) -> None:
        """The replay hash equals the hash of a directly-constructed
        ``StudyDefinitionV3`` with the same revision chain."""

        def _reducer(
            current: Optional[StudyDefinitionV3],
            payload: Mapping[str, Any],
            event: DomainEvent,
        ) -> StudyDefinitionV3:
            revision = int(payload.get("revision", 1))
            if current is None:
                return _build_study(revision=1)
            return _build_study(
                revision=revision,
                previous_revision_sha256=study_revision_hash(current),
            )

        builder = _builder()
        events = _build_stream(builder, count=3)
        engine = EventReplayEngine(
            upcasters=_registry(),
            event_types=_event_types(),
            reducer_fn=_reducer,
            revision_hash_fn=study_revision_hash,
        )
        outcome = engine.replay_stream(events)
        assert not outcome.is_quarantined

        # Build the expected final state independently and compare hashes.
        s1 = _build_study(revision=1)
        s2 = _build_study(revision=2, previous_revision_sha256=study_revision_hash(s1))
        s3 = _build_study(revision=3, previous_revision_sha256=study_revision_hash(s2))
        assert outcome.success.canonical_revision_sha256 == study_revision_hash(s3)


def _build_study(
    *,
    revision: int = 1,
    previous_revision_sha256: Optional[str] = None,
) -> StudyDefinitionV3:
    """Build a minimal valid StudyDefinitionV3 for the given revision."""

    return StudyDefinitionV3(
        study_definition_id="sd:test:1",
        project_id="proj:test:1",
        revision=revision,
        previous_revision_sha256=previous_revision_sha256,
        normalized_seed_id="seed:test:1",
        normalized_seed_sha256="a" * 64,
        facts={"therapeutic_area": "oncology"},
        decision_record_ids=(),
        updated_at=_T0,
        canonical_state=CanonicalState.PROPOSED,
    )


# ---------------------------------------------------------------------------
# Regression — nondeterministic upcaster (counterexample 1)
# ---------------------------------------------------------------------------


class TestNondeterministicUpcasterQuarantine:
    """A registered upcaster that returns a different payload on each call
    must fail closed.  Registration-time source fingerprinting does not prove
    runtime determinism; the engine detects divergence at replay time."""

    def test_nondeterministic_upcaster_quarantines_on_replay(self) -> None:
        """The exact counterexample: a registered upcaster that increments a
        counter on each call, producing divergent output, must quarantine."""

        reg = UpcasterRegistry(current_schema_version=_CURRENT_SCHEMA)
        reg.register_noop(_CURRENT_SCHEMA)

        call_count = {"n": 0}

        def nondeterministic_migrate(
            payload: Mapping[str, Any],
        ) -> Dict[str, Any]:
            call_count["n"] += 1
            result = dict(payload)
            result["migration_run"] = call_count["n"]
            return result

        reg.register(
            UpcasterSignature(_LEGACY_SCHEMA_V0, "nondeterministic:v1"),
            nondeterministic_migrate,
        )

        evt = DomainEvent(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_LEGACY_SCHEMA_V0,
            upcaster_id="nondeterministic:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={"old_revision": 5},
            payload_sha256=compute_payload_sha256({"old_revision": 5}),
            migrated_payload_sha256=exact_payload_sha256({"revision": 5}),
            previous_event_sha256=None,
            event_sha256="0" * 64,
            emitted_at=_T0,
        )
        evt = evt.model_copy(update={"event_sha256": compute_event_sha256(evt)})
        engine = _engine(registry=reg)
        outcome = engine.replay_stream([evt])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.NONDETERMINISTIC_UPCASTER
        assert outcome.quarantine.failing_event_id == "evt:1"

    def test_pairwise_equal_but_cross_replay_drift_quarantines(self) -> None:
        """Stateful paired calls cannot drift silently on a later replay."""

        reg = UpcasterRegistry(current_schema_version=_CURRENT_SCHEMA)
        reg.register_noop(_CURRENT_SCHEMA)
        calls = {"n": 0}

        def pairwise_stateful(payload: Mapping[str, Any]) -> Dict[str, Any]:
            run = calls["n"] // 2
            calls["n"] += 1
            return {**payload, "migration_run": run}

        reg.register(
            UpcasterSignature(_LEGACY_SCHEMA_V0, "pairwise-stateful:v1"),
            pairwise_stateful,
        )
        evt = DomainEvent(
            domain_event_id="evt:pairwise",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_LEGACY_SCHEMA_V0,
            upcaster_id="pairwise-stateful:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={"old_revision": 1},
            payload_sha256=compute_payload_sha256({"old_revision": 1}),
            migrated_payload_sha256=exact_payload_sha256(
                {"old_revision": 1, "migration_run": 0}
            ),
            previous_event_sha256=None,
            event_sha256="0" * 64,
            emitted_at=_T0,
        )
        evt = evt.model_copy(update={"event_sha256": compute_event_sha256(evt)})
        first_engine = _engine(registry=reg)
        assert not first_engine.replay_stream([evt]).is_quarantined

        # A fresh registry/engine has no process-local observation cache.  The
        # immutable migrated hash in the event must still expose the drift.
        fresh_reg = UpcasterRegistry(current_schema_version=_CURRENT_SCHEMA)
        fresh_reg.register_noop(_CURRENT_SCHEMA)
        fresh_reg.register(
            UpcasterSignature(_LEGACY_SCHEMA_V0, "pairwise-stateful:v1"),
            pairwise_stateful,
        )
        fresh = _engine(registry=fresh_reg).replay_stream([evt])
        assert fresh.is_quarantined
        assert fresh.quarantine.reason == QuarantineReason.NONDETERMINISTIC_UPCASTER

    def test_verify_determinism_catches_nondeterministic_upcaster(self) -> None:
        """``verify_determinism`` raises ``NondeterministicUpcasterError``
        for a upcaster that returns divergent output."""

        reg = UpcasterRegistry(current_schema_version=_CURRENT_SCHEMA)
        reg.register_noop(_CURRENT_SCHEMA)

        call_count = {"n": 0}

        def bad_migrate(payload: Mapping[str, Any]) -> Dict[str, Any]:
            call_count["n"] += 1
            result = dict(payload)
            result["migration_run"] = call_count["n"]
            return result

        sig = UpcasterSignature(_LEGACY_SCHEMA_V0, "bad:v1")
        reg.register(sig, bad_migrate)

        with pytest.raises(NondeterministicUpcasterError):
            reg.verify_determinism(sig, {"old_revision": 1})

    def test_verify_determinism_passes_for_deterministic_upcaster(self) -> None:
        """``verify_determinism`` passes for a pure upcaster."""

        reg = _registry_with_legacy_upcaster()
        sig = UpcasterSignature(_LEGACY_SCHEMA_V0, "v0_to_v1:migrate")
        reg.verify_determinism(sig, {"old_revision": 1})  # must not raise

    def test_deterministic_legacy_upcaster_replays_successfully(self) -> None:
        """A deterministic legacy upcaster still replays without quarantine."""

        reg = _registry_with_legacy_upcaster()
        evt = DomainEvent(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="test",
            payload_schema_version=_LEGACY_SCHEMA_V0,
            upcaster_id="v0_to_v1:migrate",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={"old_revision": 5},
            payload_sha256=compute_payload_sha256({"old_revision": 5}),
            migrated_payload_sha256=exact_payload_sha256({"revision": 5}),
            previous_event_sha256=None,
            event_sha256="0" * 64,
            emitted_at=_T0,
        )
        evt = evt.model_copy(update={"event_sha256": compute_event_sha256(evt)})
        engine = _engine(registry=reg)
        outcome = engine.replay_stream([evt])
        assert not outcome.is_quarantined

    def test_nondeterministic_upcaster_does_not_mutate_input(self) -> None:
        """``verify_determinism`` rejects upcasters that mutate their input."""

        reg = UpcasterRegistry(current_schema_version=_CURRENT_SCHEMA)
        reg.register_noop(_CURRENT_SCHEMA)

        def mutating_migrate(payload: Mapping[str, Any]) -> Dict[str, Any]:
            result = dict(payload)
            # Mutate the original mapping by casting and popping
            if isinstance(payload, dict):
                payload.pop("old_revision", None)
            return result

        sig = UpcasterSignature(_LEGACY_SCHEMA_V0, "mutating:v1")
        reg.register(sig, mutating_migrate)

        with pytest.raises(NondeterministicUpcasterError, match="mutated"):
            reg.verify_determinism(sig, {"old_revision": 1})


# ---------------------------------------------------------------------------
# Regression — unknown event type (counterexample 2)
# ---------------------------------------------------------------------------


class TestUnknownEventTypeQuarantine:
    """An event whose ``event_type`` is not in the closed event-type registry
    must quarantine.  There is no permissive default."""

    def test_unregistered_event_type_quarantines(self) -> None:
        """The exact counterexample: ``event_type='totally.unregistered.event'``
        quarantines because it is absent from the mandatory registry."""

        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="totally.unregistered.event",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={"revision": 1},
            emitted_at=_T0,
        )
        event_types = EventTypeRegistry(["study_definition.revised", "test"])
        engine = EventReplayEngine(
            upcasters=_registry(),
            reducer=_CounterReducer(),
            event_types=event_types,
        )
        outcome = engine.replay_stream([evt])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.UNKNOWN_EVENT_TYPE
        assert outcome.quarantine.failing_event_id == "evt:1"

    def test_registered_event_type_replays(self) -> None:
        """A registered event type replays successfully."""

        builder = _builder()
        events = _build_stream(builder, count=2, event_type="study_definition.revised")
        event_types = EventTypeRegistry(["study_definition.revised"])
        engine = EventReplayEngine(
            upcasters=_registry(),
            reducer=_CounterReducer(),
            event_types=event_types,
        )
        outcome = engine.replay_stream(events)
        assert not outcome.is_quarantined
        assert outcome.success.events_replayed == 2

    def test_construction_without_event_types_fails(self) -> None:
        """Constructing ``EventReplayEngine`` without ``event_types`` raises
        ``TypeError`` at the Python/API boundary — there is no permissive
        default."""

        with pytest.raises(TypeError, match="event_types"):
            EventReplayEngine(
                upcasters=_registry(),
                reducer=_CounterReducer(),
            )  # type: ignore[call-arg]

    def test_unregistered_type_always_quarantines_via_default_engine(self) -> None:
        """Even the default ``_engine()`` helper (which registers all known
        test types) quarantines a type that was never registered."""

        builder = _builder()
        evt = builder.build(
            domain_event_id="evt:1",
            stream_id="stream:t:1",
            sequence=1,
            event_type="totally.unregistered.event",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.AI,
            actor_id="a:1",
            action="act",
            reason="r",
            payload={"revision": 1},
            emitted_at=_T0,
        )
        engine = _engine()
        outcome = engine.replay_stream([evt])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.UNKNOWN_EVENT_TYPE

    def test_event_type_registry_is_closed(self) -> None:
        """``EventTypeRegistry`` rejects duplicate registration."""

        reg = EventTypeRegistry(["test"])
        with pytest.raises(ValueError, match="already registered"):
            reg.register("test")

    def test_event_type_registry_assert_registered(self) -> None:
        """``assert_registered`` raises for unknown types."""

        reg = EventTypeRegistry(["known.type"])
        reg.assert_registered("known.type")  # must not raise
        with pytest.raises(UnknownEventTypeError):
            reg.assert_registered("unknown.type")

    def test_engine_freezes_both_registries(self) -> None:
        upcasters = _registry()
        event_types = EventTypeRegistry(["test"])
        EventReplayEngine(
            upcasters=upcasters,
            event_types=event_types,
            reducer=_CounterReducer(),
        )
        assert upcasters.is_frozen
        assert event_types.is_frozen
        with pytest.raises(RegistryFrozenError):
            event_types.register("later.type")
        with pytest.raises(RegistryFrozenError):
            upcasters.register(
                UpcasterSignature(_LEGACY_SCHEMA_V0, "later:v1"),
                lambda payload: dict(payload),
            )


class TestStreamIdentityBinding:
    def test_mixed_stream_replay_quarantines(self) -> None:
        first = _builder().build(
            domain_event_id="evt:a",
            stream_id="stream:a",
            sequence=1,
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="system:1",
            action="act",
            reason="r",
            payload={"revision": 1},
            emitted_at=_T0,
        )
        second = _builder().continue_chain(
            head_sha256=first.event_sha256,
            head_sequence=1,
            domain_event_id="evt:b",
            stream_id="stream:b",
            event_type="test",
            payload_schema_version=_CURRENT_SCHEMA,
            upcaster_id="noop:v1",
            actor_type=ActorType.SYSTEM,
            actor_id="system:1",
            action="act",
            reason="r",
            payload={"revision": 2},
            emitted_at=_T1,
        )
        outcome = _engine().replay_stream([first, second])
        assert outcome.is_quarantined
        assert outcome.quarantine.reason == QuarantineReason.STREAM_ID_MISMATCH
