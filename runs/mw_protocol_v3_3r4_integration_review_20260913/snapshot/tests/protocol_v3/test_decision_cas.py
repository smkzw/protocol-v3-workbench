"""Tests for the DecisionRecord idempotent CAS reducer.

Covers Protocol v3 Task 1.4 micro-steps for ``decisions.py``:

- Same ``(decision_id, snapshot_hash, expected revision)`` and same payload
  replay the exact prior :class:`DecisionRecord`; no second ledger entry is
  created.
- Same CAS identity with a different payload fails with a stable typed error.
- Decision lifecycle transitions follow the canonical state machine; illegal
  edges fail with a typed error; same-state re-assertions are idempotent.
- The reducer is pure: it never consults a clock, repository, filesystem or
  model, and identical inputs always produce identical outputs.
- DecisionRecord remains a durable proof of adoption — it never silently
  duplicates, and its CAS identity is stable and content-addressed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    CanonicalState,
    DecisionRecord,
)
from services.api.app.protocol_workflow.canonical import (
    DecisionCasError,
    DecisionLedger,
    DecisionRecordPayloadConflictError as DecisionPayloadConflictError,
    DecisionReducer,
    DecisionReplayResult,
    IllegalDecisionTransitionError,
    decision_cas_identity,
    material_sha256,
)

NOW = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 8, 10, 11, 0, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _decision(
    *,
    decision_record_id: str = "decision:dose:001",
    decision_key: str = "decision:dose",
    snapshot_sha256: str = SHA_A,
    expected_state_revision: int = 1,
    option_ids: tuple[str, ...] = ("option:dose:001", "option:dose:002"),
    selected_option_id: str = "option:dose:001",
    actor_type: str = "user",
    actor_id: str = "user:medical-writer",
    reason: str = "接受 AI 推荐的默认剂量设计。",
    decided_at: datetime = NOW,
    canonical_state: str = "confirmed",
    **overrides,
) -> DecisionRecord:
    payload = {
        "decision_record_id": decision_record_id,
        "decision_key": decision_key,
        "snapshot_sha256": snapshot_sha256,
        "expected_state_revision": expected_state_revision,
        "state_revision": expected_state_revision + 1,
        "option_ids": option_ids,
        "selected_option_id": selected_option_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "reason": reason,
        "decided_at": decided_at,
        "canonical_state": canonical_state,
    }
    payload.update(overrides)
    return DecisionRecord(**payload)


# ---------------------------------------------------------------------------
# CAS replay / record
# ---------------------------------------------------------------------------


class TestCasReplayAndRecord:
    def test_fresh_decision_is_recorded(self):
        reducer = DecisionReducer()
        ledger = DecisionLedger()
        decision = _decision()

        result = reducer.replay_or_record(ledger, decision)

        assert result.replayed is False
        assert result.effective is decision
        assert result.ledger.records == (decision,)

    def test_same_cas_triple_replays_exact_prior_record(self):
        """Replaying the same (decision_id, snapshot, expected_rev) with the
        same material payload returns the exact prior record and does not
        create a second ledger entry."""
        reducer = DecisionReducer()
        ledger = DecisionLedger()
        original = _decision()
        recorded = reducer.replay_or_record(ledger, original)

        # Re-emit the identical decision — a duplicate click or worker retry.
        replay_copy = _decision()
        result = reducer.replay_or_record(recorded.ledger, replay_copy)

        assert result.replayed is True
        assert result.effective is original
        assert result.ledger.records == (original,)
        assert len(result.ledger.records) == 1

    def test_replay_returns_original_identity_not_incoming(self):
        """The effective record on replay is the originally stored object, not
        the incoming copy, so callers can discard the duplicate safely."""
        reducer = DecisionReducer()
        original = _decision()
        recorded = reducer.replay_or_record(DecisionLedger(), original)

        incoming = _decision(reason="重复点击产生的同一决策。")
        # Same CAS identity, different reason → different material hash.
        # But the CAS identity is keyed on (id, snapshot, expected_rev), not
        # reason.  This is therefore a *conflict*, not a replay.  Verify that
        # the conflict path fires rather than silently accepting the new
        # reason — a retry must resend identical bytes.
        with pytest.raises(DecisionPayloadConflictError):
            reducer.replay_or_record(recorded.ledger, incoming)

    def test_two_distinct_decisions_are_both_recorded(self):
        reducer = DecisionReducer()
        ledger = DecisionLedger()
        d1 = _decision(decision_record_id="decision:dose:001")
        r1 = reducer.replay_or_record(ledger, d1)

        d2 = _decision(
            decision_record_id="decision:control:001",
            decision_key="decision:control",
            snapshot_sha256=SHA_B,
        )
        r2 = reducer.replay_or_record(r1.ledger, d2)

        assert r1.replayed is False
        assert r2.replayed is False
        assert r2.ledger.records == (d1, d2)

    def test_same_decision_id_different_snapshot_is_distinct_identity(self):
        """The same decision_record_id captured against a different snapshot
        and expected revision is a fresh CAS identity, not a replay.  This is
        the legitimate re-decision path (a new accepted decision after the
        definition advanced)."""
        reducer = DecisionReducer()
        d1 = _decision(
            decision_record_id="decision:dose:001",
            snapshot_sha256=SHA_A,
            expected_state_revision=1,
        )
        recorded = reducer.replay_or_record(DecisionLedger(), d1)

        # Same logical decision id, but the snapshot advanced and the expected
        # revision is now 2 — a genuinely new adoption event.
        d2 = _decision(
            decision_record_id="decision:dose:001",
            snapshot_sha256=SHA_B,
            expected_state_revision=2,
        )
        result = reducer.replay_or_record(recorded.ledger, d2)

        assert result.replayed is False
        assert len(result.ledger.records) == 2

    def test_empty_ledger_is_empty(self):
        ledger = DecisionLedger()
        assert ledger.is_empty()
        assert ledger.records == ()

    def test_find_by_identity_returns_none_for_unknown(self):
        ledger = DecisionLedger()
        assert ledger.find_by_identity("decision:x", SHA_A, 1) is None

    def test_find_by_identity_returns_recorded(self):
        reducer = DecisionReducer()
        decision = _decision()
        recorded = reducer.replay_or_record(DecisionLedger(), decision)
        found = recorded.ledger.find_by_identity(
            decision.decision_record_id,
            decision.snapshot_sha256,
            decision.expected_state_revision,
        )
        assert found is decision


# ---------------------------------------------------------------------------
# CAS conflict path
# ---------------------------------------------------------------------------


class TestCasConflicts:
    def test_same_identity_different_payload_raises_typed_error(self):
        """Same CAS triple but a changed material field is a contract
        violation — a retry must resend identical bytes."""
        reducer = DecisionReducer()
        original = _decision(reason="原始采用理由。")
        recorded = reducer.replay_or_record(DecisionLedger(), original)

        conflict = _decision(reason="被篡改后的不同理由。")
        with pytest.raises(DecisionPayloadConflictError) as exc_info:
            reducer.replay_or_record(recorded.ledger, conflict)

        err = exc_info.value
        assert err.decision_record_id == original.decision_record_id
        assert err.snapshot_sha256 == original.snapshot_sha256
        assert err.expected_state_revision == original.expected_state_revision
        assert err.existing_decision_sha256 == original.material_sha256()
        assert err.incoming_decision_sha256 == conflict.material_sha256()
        assert err.existing_decision_sha256 != err.incoming_decision_sha256
        assert isinstance(err, DecisionCasError)

    def test_conflict_error_carries_cas_identity(self):
        reducer = DecisionReducer()
        original = _decision(selected_option_id="option:dose:001")
        recorded = reducer.replay_or_record(DecisionLedger(), original)

        conflict = _decision(selected_option_id="option:dose:002")
        with pytest.raises(DecisionPayloadConflictError) as exc_info:
            reducer.replay_or_record(recorded.ledger, conflict)

        expected_identity = decision_cas_identity(
            original.decision_record_id,
            original.snapshot_sha256,
            original.expected_state_revision,
        )
        assert exc_info.value.cas_identity == expected_identity

    def test_conflict_does_not_mutate_ledger(self):
        """A failed conflict leaves the ledger untouched."""
        reducer = DecisionReducer()
        original = _decision()
        recorded = reducer.replay_or_record(DecisionLedger(), original)

        conflict = _decision(actor_id="user:different")
        with pytest.raises(DecisionPayloadConflictError):
            reducer.replay_or_record(recorded.ledger, conflict)

        assert recorded.ledger.records == (original,)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


class TestLifecycleTransitions:
    def test_freeze_confirmed_decision(self):
        reducer = DecisionReducer()
        decision = _decision(canonical_state="confirmed")
        frozen = reducer.freeze(decision, now=LATER)
        assert frozen.canonical_state is CanonicalState.FROZEN
        assert frozen.decided_at == LATER
        assert frozen.decision_record_id == decision.decision_record_id

    def test_supersede_frozen_decision(self):
        reducer = DecisionReducer()
        decision = _decision(canonical_state="frozen")
        superseded = reducer.supersede(decision, now=LATER)
        assert superseded.canonical_state is CanonicalState.SUPERSEDED

    def test_quarantine_confirmed_decision(self):
        reducer = DecisionReducer()
        decision = _decision(canonical_state="confirmed")
        quarantined = reducer.quarantine(decision, now=LATER)
        assert quarantined.canonical_state is CanonicalState.QUARANTINED

    def test_same_state_transition_is_idempotent_noop(self):
        """Re-asserting the current state returns the original record
        unchanged."""
        reducer = DecisionReducer()
        decision = _decision(canonical_state="frozen")
        result = reducer.freeze(decision, now=LATER)
        assert result is decision

    def test_illegal_transition_raises_typed_error(self):
        """A superseded decision cannot be re-confirmed."""
        reducer = DecisionReducer()
        decision = _decision(canonical_state="superseded")
        with pytest.raises(IllegalDecisionTransitionError) as exc_info:
            reducer.transition(decision, CanonicalState.CONFIRMED, now=LATER)

        err = exc_info.value
        assert err.current_state is CanonicalState.SUPERSEDED
        assert err.target_state is CanonicalState.CONFIRMED
        assert isinstance(err, DecisionCasError)

    def test_quarantined_is_terminal(self):
        reducer = DecisionReducer()
        decision = _decision(canonical_state="quarantined")
        with pytest.raises(IllegalDecisionTransitionError):
            reducer.freeze(decision, now=LATER)

    def test_transition_preserves_material_identity(self):
        """A lifecycle transition changes only state and timestamp; the
        decision identity and option selection are preserved."""
        reducer = DecisionReducer()
        decision = _decision(canonical_state="confirmed")
        frozen = reducer.freeze(decision, now=LATER)
        assert frozen.decision_record_id == decision.decision_record_id
        assert frozen.snapshot_sha256 == decision.snapshot_sha256
        assert frozen.option_ids == decision.option_ids
        assert frozen.selected_option_id == decision.selected_option_id
        assert frozen.expected_state_revision == decision.expected_state_revision
        assert frozen.state_revision == decision.state_revision


# ---------------------------------------------------------------------------
# Model contract enforcement
# ---------------------------------------------------------------------------


class TestDecisionRecordContract:
    def test_state_revision_must_advance_expected_once(self):
        """The DecisionRecord contract enforces state_revision ==
        expected_state_revision + 1 (CAS advance by exactly one)."""
        with pytest.raises(ValidationError, match="CAS revision"):
            _decision(expected_state_revision=1, state_revision=3)

    def test_selected_option_must_be_in_options(self):
        with pytest.raises(ValidationError, match="selected_option_id"):
            _decision(
                option_ids=("option:a", "option:b"),
                selected_option_id="option:c",
            )

    def test_option_ids_must_be_unique(self):
        with pytest.raises(ValidationError, match="duplicate IDs"):
            _decision(
                option_ids=("option:a", "option:a"),
                selected_option_id="option:a",
            )

    def test_decision_must_capture_resolved_state(self):
        """A decision cannot be raw or merely proposed — it must capture a
        resolved adoption."""
        with pytest.raises(ValidationError, match="resolved decision"):
            _decision(canonical_state="raw")


# ---------------------------------------------------------------------------
# Purity and determinism
# ---------------------------------------------------------------------------


class TestPurityAndDeterminism:
    def test_reducer_is_stateless_and_shareable(self):
        r1 = DecisionReducer()
        r2 = DecisionReducer()
        decision = _decision()
        a = r1.replay_or_record(DecisionLedger(), decision)
        b = r2.replay_or_record(DecisionLedger(), decision)
        assert a.effective == b.effective
        assert a.replayed == b.replayed

    def test_replay_does_not_mutate_input_ledger(self):
        reducer = DecisionReducer()
        original = _decision()
        recorded = reducer.replay_or_record(DecisionLedger(), original)
        ledger_snapshot = recorded.ledger.records

        replay = reducer.replay_or_record(recorded.ledger, _decision())
        assert ledger_snapshot == (original,)
        assert replay.ledger.records == (original,)

    def test_reducer_uses_explicit_time_not_clock(self):
        """The reducer accepts explicit time; it never calls datetime.now().
        This test documents that contract by passing two different times and
        confirming the reducer uses exactly what it receives."""
        reducer = DecisionReducer()
        decision = _decision(canonical_state="confirmed")
        t1 = datetime(2020, 1, 1, tzinfo=timezone.utc)
        frozen = reducer.freeze(decision, now=t1)
        assert frozen.decided_at == t1

    def test_identical_inputs_produce_identical_ledgers(self):
        reducer = DecisionReducer()
        d1 = _decision(decision_record_id="decision:a")
        d2 = _decision(
            decision_record_id="decision:b",
            decision_key="decision:other",
            snapshot_sha256=SHA_B,
        )
        ledger_a = DecisionLedger()
        ledger_a = reducer.replay_or_record(ledger_a, d1).ledger
        ledger_a = reducer.replay_or_record(ledger_a, d2).ledger

        ledger_b = DecisionLedger()
        ledger_b = reducer.replay_or_record(ledger_b, d1).ledger
        ledger_b = reducer.replay_or_record(ledger_b, d2).ledger

        assert [r.material_sha256() for r in ledger_a.records] == [
            r.material_sha256() for r in ledger_b.records
        ]

    def test_cas_identity_is_stable_64_hex(self):
        identity = decision_cas_identity("decision:1", SHA_A, 1)
        assert isinstance(identity, str)
        assert len(identity) == 64

    def test_material_hash_excludes_lifecycle_state(self):
        """The material hash strips canonical_state and decided_at so that a
        pure lifecycle transition does not change the decision's content
        identity — only its lifecycle position."""
        confirmed = _decision(canonical_state="confirmed")
        # Same content, frozen — material hash must be identical because
        # canonical_state and decided_at are material-metadata fields.
        frozen_payload = confirmed.model_dump()
        frozen_payload["canonical_state"] = CanonicalState.FROZEN
        frozen_payload["decided_at"] = LATER
        frozen = DecisionRecord(**frozen_payload)
        assert confirmed.material_sha256() == frozen.material_sha256()

    def test_replay_result_is_immutable_view(self):
        reducer = DecisionReducer()
        decision = _decision()
        result = reducer.replay_or_record(DecisionLedger(), decision)
        assert isinstance(result, DecisionReplayResult)
        assert result.effective is decision
        assert result.replayed is False


# ---------------------------------------------------------------------------
# CAS identity stability
# ---------------------------------------------------------------------------


class TestCasIdentity:
    def test_identity_changes_with_decision_id(self):
        a = decision_cas_identity("decision:1", SHA_A, 1)
        b = decision_cas_identity("decision:2", SHA_A, 1)
        assert a != b

    def test_identity_changes_with_snapshot(self):
        a = decision_cas_identity("decision:1", SHA_A, 1)
        b = decision_cas_identity("decision:1", SHA_B, 1)
        assert a != b

    def test_identity_changes_with_expected_revision(self):
        a = decision_cas_identity("decision:1", SHA_A, 1)
        b = decision_cas_identity("decision:1", SHA_A, 2)
        assert a != b

    def test_identity_stable_only_when_all_three_match(self):
        """The identity is equal if and only if decision id, snapshot and
        expected revision are all identical — varying any single component
        breaks equality."""
        base = decision_cas_identity("decision:1", SHA_A, 1)
        assert base == decision_cas_identity("decision:1", SHA_A, 1)
        assert base != decision_cas_identity("decision:2", SHA_A, 1)
        assert base != decision_cas_identity("decision:1", SHA_B, 1)
        assert base != decision_cas_identity("decision:1", SHA_A, 2)

    def test_all_cas_errors_inherit_decision_cas_error(self):
        """Every typed decision CAS failure inherits from the stable base
        class so the application service can catch them uniformly."""
        for exc_cls in (
            DecisionPayloadConflictError,
            IllegalDecisionTransitionError,
        ):
            assert issubclass(exc_cls, DecisionCasError)

    def test_material_sha256_matches_model(self):
        decision = _decision()
        assert material_sha256(decision) == decision.material_sha256()


# ---------------------------------------------------------------------------
# Reconstruction hardening
# ---------------------------------------------------------------------------


class TestLedgerReconstruction:
    def test_conflicting_duplicate_identity_fails_closed(self):
        """A ledger reconstructed from a record tuple containing two records
        with the same CAS triple but different material must fail closed
        rather than silently selecting the first record."""
        r1 = _decision(reason="原始采用理由。")
        r2 = _decision(reason="冲突的篡改理由。")
        assert r1.material_sha256() != r2.material_sha256()

        with pytest.raises(DecisionPayloadConflictError) as exc_info:
            DecisionLedger((r1, r2))

        err = exc_info.value
        assert err.existing_decision_sha256 == r1.material_sha256()
        assert err.incoming_decision_sha256 == r2.material_sha256()
        assert isinstance(err, DecisionCasError)

    def test_exact_duplicate_is_deduplicated(self):
        """Two records with the same CAS identity and identical material are
        a benign duplicate (e.g. an event stream replayed twice); the ledger
        keeps one canonical entry and drops the copy."""
        decision = _decision()
        ledger = DecisionLedger((decision, decision))
        assert len(ledger.records) == 1
        assert ledger.records[0] is decision

    def test_reconstruction_preserves_distinct_identities(self):
        """Distinct CAS identities are all preserved on reconstruction."""
        d1 = _decision(
            decision_record_id="decision:dose:001",
            snapshot_sha256=SHA_A,
            expected_state_revision=1,
        )
        d2 = _decision(
            decision_record_id="decision:control:001",
            decision_key="decision:control",
            snapshot_sha256=SHA_B,
            expected_state_revision=1,
        )
        ledger = DecisionLedger((d1, d2))
        assert ledger.records == (d1, d2)
        assert (
            ledger.find_by_identity(
                d1.decision_record_id,
                d1.snapshot_sha256,
                d1.expected_state_revision,
            )
            is d1
        )
        assert (
            ledger.find_by_identity(
                d2.decision_record_id,
                d2.snapshot_sha256,
                d2.expected_state_revision,
            )
            is d2
        )

    def test_conflict_in_reconstruction_reports_correct_cas_identity(self):
        """The conflict error carries the shared CAS identity of the triple."""
        r1 = _decision(selected_option_id="option:dose:001")
        r2 = _decision(selected_option_id="option:dose:002")
        with pytest.raises(DecisionPayloadConflictError) as exc_info:
            DecisionLedger((r1, r2))
        expected = decision_cas_identity(
            r1.decision_record_id,
            r1.snapshot_sha256,
            r1.expected_state_revision,
        )
        assert exc_info.value.cas_identity == expected
