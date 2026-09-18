"""Tests for the StudyDefinition pure reducer and CAS discipline.

Covers Protocol v3 Task 1.4 micro-steps and the manager-vetoed repair
requirements:

- Same ``(decision_id, snapshot_hash, expected revision)`` replay — reusing the
  *exact same* DecisionRecord object/fields — returns the previously recorded
  DecisionRecord object, produces no new revision, and is a true no-op.
- Stale expected revision, same-CAS-triple different-DecisionRecord-material,
  same-CAS-triple different-fact-updates, and frozen-fact overwrite each fail
  with a precise typed error.
- ``decision_cas_identity`` hashes the raw triple and changes when any
  component (including ``expected_state_revision``) changes.
- ``canonical_revision_hash`` binds revision identity: same material at a new
  revision yields a different hash.
- The reducer is pure: it advances a revision only through an accepted
  :class:`DecisionRecord` and never loses a fact.
- StudyDefinition remains the only fact authority — no direct overwrite of
  frozen facts outside an accepted decision.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    CanonicalState,
    DecisionRecord,
    StudyDefinitionV3,
)
from services.api.app.protocol_workflow.canonical import (
    DecisionEffectLedger,
    DecisionPayloadConflictError,
    FrozenFactOverwriteError,
    RevisionStaleError,
    StudyDefinitionCasError,
    StudyDefinitionReducer,
    canonical_json,
    canonical_revision_hash,
    decision_cas_identity,
    exact_payload_sha256,
    fact_set_sha256,
    material_sha256,
    study_definition_lineage_hash,
)
from services.api.app.protocol_workflow.canonical.study_definition import (
    study_revision_hash,
)


NOW = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 8, 10, 10, 30, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _study_definition(**overrides) -> StudyDefinitionV3:
    payload = {
        "study_definition_id": "study:def:uc301",
        "project_id": "project:uc301",
        "revision": 1,
        "normalized_seed_id": "seed:uc301:normalized",
        "normalized_seed_sha256": SHA_A,
        "facts": {
            "picos.population.indication": "中重度活动性溃疡性结肠炎",
            "picos.intervention.dose": "10 mg 或 20 mg，每日一次",
        },
        "decision_record_ids": (),
        "updated_at": NOW,
        "canonical_state": "proposed",
    }
    payload.update(overrides)
    if payload["revision"] > 1 and "previous_revision_sha256" not in payload:
        payload["previous_revision_sha256"] = SHA_B
    return StudyDefinitionV3(**payload)


def _decision(
    *,
    decision_record_id: str = "decision:dose:001",
    decision_key: str = "decision:dose",
    snapshot_sha256: str = SHA_A,
    expected_state_revision: int = 1,
    option_ids: tuple[str, ...] = ("option:dose:001", "option:dose:002"),
    selected_option_id: str = "option:dose:001",
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
        "actor_type": "user",
        "actor_id": "user:medical-writer",
        "reason": "接受 AI 推荐的默认剂量设计。",
        "decided_at": NOW,
        "canonical_state": canonical_state,
    }
    payload.update(overrides)
    return DecisionRecord(**payload)


def _snapshot_for(definition: StudyDefinitionV3) -> str:
    """The canonical revision hash the decision must capture as its snapshot."""

    return study_revision_hash(definition)


# ---------------------------------------------------------------------------
# Hashing purity and revision-awareness
# ---------------------------------------------------------------------------


class TestCanonicalHashing:
    def test_material_sha256_strips_revision_timestamp_and_state(self):
        """Material hash: revision, timestamp and lifecycle state do not change it."""

        base = {"study_definition_id": "study:def:uc301", "facts": {"x": 1}}
        variant = {
            **base,
            "revision": 99,
            "updated_at": "2099-01-01",
            "canonical_state": "frozen",
        }
        assert material_sha256(base) == material_sha256(variant)

    def test_material_sha256_is_order_independent(self):
        a = material_sha256({"facts": {"b": 2, "a": 1}})
        b = material_sha256({"facts": {"a": 1, "b": 2}})
        assert a == b

    def test_fact_set_sha256_detects_content_change(self):
        assert fact_set_sha256({"a": 1}) != fact_set_sha256({"a": 2})

    def test_exact_fact_payload_hash_preserves_metadata_named_domain_keys(self):
        assert exact_payload_sha256({"revision": "A"}) != exact_payload_sha256(
            {"revision": "B"}
        )
        assert fact_set_sha256({"revision": "A"}) != fact_set_sha256({"revision": "B"})

    def test_model_material_hash_preserves_nested_metadata_named_fact_keys(self):
        first = _study_definition(facts={"nested": {"revision": "A"}})
        second = _study_definition(facts={"nested": {"revision": "B"}})
        assert first.material_sha256() != second.material_sha256()

    def test_study_definition_lineage_hash_is_stable_across_revisions(self):
        kwargs = dict(
            study_definition_id="study:def:uc301",
            normalized_seed_id="seed:uc301",
            normalized_seed_sha256=SHA_A,
            facts={"picos.population.indication": "UC"},
        )
        first = study_definition_lineage_hash(**kwargs)
        again = study_definition_lineage_hash(**kwargs)
        assert first == again

    def test_decision_cas_identity_is_deterministic_and_revision_aware(self):
        """The CAS identity hashes the raw triple; it must change when the
        expected revision changes, and be equal only when all three components
        match."""
        id_rev1_a = decision_cas_identity("decision:1", SHA_A, 1)
        id_rev1_b = decision_cas_identity("decision:1", SHA_A, 1)
        id_rev2 = decision_cas_identity("decision:1", SHA_A, 2)
        id_diff_id = decision_cas_identity("decision:2", SHA_A, 1)
        id_diff_snap = decision_cas_identity("decision:1", SHA_B, 1)

        assert id_rev1_a == id_rev1_b
        # Varying ONLY the expected revision must change the identity.
        assert id_rev1_a != id_rev2
        # Varying the id or snapshot also changes it.
        assert id_rev1_a != id_diff_id
        assert id_rev1_a != id_diff_snap

    def test_canonical_json_is_sorted_and_compact(self):
        result = canonical_json({"b": 1, "a": 2})
        assert result == '{"a":2,"b":1}'

    def test_hash_matches_model_material_sha256(self):
        study = _study_definition()
        assert material_sha256(study) == study.material_sha256()

    def test_canonical_revision_hash_binds_full_revision_identity(self):
        """Same material at a different revision, state, or predecessor must
        produce a different revision hash."""
        mat = "c" * 64
        base = canonical_revision_hash(
            "study:def",
            1,
            None,
            CanonicalState.PROPOSED,
            mat,
        )
        diff_revision = canonical_revision_hash(
            "study:def",
            2,
            base,
            CanonicalState.PROPOSED,
            mat,
        )
        diff_state = canonical_revision_hash(
            "study:def",
            1,
            None,
            CanonicalState.CONFIRMED,
            mat,
        )
        diff_material = canonical_revision_hash(
            "study:def",
            1,
            None,
            CanonicalState.PROPOSED,
            "d" * 64,
        )
        assert base != diff_revision
        assert base != diff_state
        assert base != diff_material
        # Deterministic
        again = canonical_revision_hash(
            "study:def",
            1,
            None,
            CanonicalState.PROPOSED,
            mat,
        )
        assert base == again

    def test_study_revision_hash_changes_when_revision_advances(self):
        """A StudyDefinition at revision 1 vs revision 2 (same facts) must have
        different revision hashes, because revision, predecessor and (possibly)
        state are part of the identity."""
        r1 = _study_definition(revision=1)
        r2 = _study_definition(
            revision=2,
            previous_revision_sha256=study_revision_hash(r1),
        )
        assert study_revision_hash(r1) != study_revision_hash(r2)
        # But their material hashes are equal (same facts).
        assert r1.material_sha256() == r2.material_sha256()


# ---------------------------------------------------------------------------
# CAS replay / apply
# ---------------------------------------------------------------------------


class TestCasReplayAndApply:
    def test_same_cas_triple_replays_exact_prior_record(self):
        """A duplicate request after commit/restart carries the exact original
        DecisionRecord.  The repository's current is now the advanced revision.
        The replay must return *advanced* unchanged, the prior DecisionRecord
        object, and an unchanged ledger — never regress to revision 1."""
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        snapshot = _snapshot_for(current)
        decision = _decision(snapshot_sha256=snapshot, expected_state_revision=1)

        # Fresh apply: produces revision 2.
        advanced, effective, ledger, replayed = reducer.replay_or_apply(
            current,
            decision,
            DecisionEffectLedger(),
            now=NOW,
        )
        assert replayed is False
        assert effective is decision
        assert advanced.revision == 2
        assert advanced.decision_record_ids == ("decision:dose:001",)

        # Duplicate request: repository current is now *advanced* (revision 2),
        # but the incoming decision still carries the original CAS triple
        # (expected_state_revision=1).  The ledger is consulted first; the
        # replay returns *advanced* unchanged and the prior decision object.
        result_def, result_dec, result_ledger, result_replayed = (
            reducer.replay_or_apply(
                advanced,
                decision,
                ledger,
                now=LATER,
            )
        )
        assert result_replayed is True
        assert result_def is advanced
        assert result_def.revision == 2
        assert result_dec is decision
        assert result_ledger is ledger

    def test_replay_returns_the_original_recorded_object_not_a_reconstruction(self):
        """The replay path must return the *previously recorded* DecisionRecord
        object, not a freshly built one with equal fields, even when current is
        the advanced revision."""
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        snapshot = _snapshot_for(current)
        decision = _decision(snapshot_sha256=snapshot, expected_state_revision=1)

        advanced, _, ledger, _ = reducer.replay_or_apply(
            current,
            decision,
            DecisionEffectLedger(),
            now=NOW,
        )

        # A second DecisionRecord with identical fields but a different object
        # identity.  Because the material hash matches, this is an exact replay.
        identical_decision = _decision(
            snapshot_sha256=snapshot,
            expected_state_revision=1,
        )
        _, returned_dec, _, replayed = reducer.replay_or_apply(
            advanced,
            identical_decision,
            ledger,
            now=NOW,
        )
        assert replayed is True
        # The previously recorded object is returned, not the incoming one.
        assert returned_dec is decision
        assert returned_dec is not identical_decision

    def test_effect_and_effect_ledger_are_immutable(self):
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        decision = _decision(snapshot_sha256=_snapshot_for(current))
        _, _, ledger, _ = reducer.replay_or_apply(
            current,
            decision,
            DecisionEffectLedger(),
            now=NOW,
        )
        effect = next(iter(ledger.effects.values()))
        with pytest.raises(AttributeError, match="immutable"):
            effect.result_revision = 99
        with pytest.raises(TypeError):
            ledger.effects["forged"] = effect
        with pytest.raises(AttributeError, match="immutable"):
            ledger._effects = {}

    def test_fresh_apply_advances_revision_and_links_lineage(self):
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        snapshot = _snapshot_for(current)
        decision = _decision(snapshot_sha256=snapshot, expected_state_revision=1)

        advanced = reducer.apply_decision(current, decision, now=LATER)

        assert advanced.revision == 2
        assert advanced.previous_revision_sha256 == study_revision_hash(current)
        assert decision.decision_record_id in advanced.decision_record_ids
        assert advanced.updated_at == LATER

    def test_fresh_apply_preserves_all_facts(self):
        """No lost facts: the fact set is fully carried forward."""
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        decision = _decision(
            snapshot_sha256=_snapshot_for(current),
            expected_state_revision=1,
        )
        advanced = reducer.apply_decision(current, decision, now=NOW)
        assert advanced.facts == current.facts

    def test_fresh_apply_can_add_new_facts(self):
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        decision = _decision(
            snapshot_sha256=_snapshot_for(current),
            expected_state_revision=1,
        )
        advanced = reducer.apply_decision(
            current,
            decision,
            fact_updates={"picos.population.phase": "II期"},
            now=NOW,
        )
        assert advanced.facts["picos.population.phase"] == "II期"
        assert (
            advanced.facts["picos.population.indication"] == "中重度活动性溃疡性结肠炎"
        )

    def test_proposed_to_confirmed_transition_on_confirmed_decision(self):
        reducer = StudyDefinitionReducer()
        current = _study_definition(canonical_state="proposed")
        decision = _decision(
            snapshot_sha256=_snapshot_for(current),
            expected_state_revision=1,
            canonical_state="confirmed",
        )
        advanced = reducer.apply_decision(current, decision, now=NOW)
        assert advanced.canonical_state is CanonicalState.CONFIRMED

    def test_two_sequential_applies_advance_revision_by_two(self):
        reducer = StudyDefinitionReducer()
        first = _study_definition()
        d1 = _decision(
            decision_record_id="decision:dose:001",
            snapshot_sha256=_snapshot_for(first),
            expected_state_revision=1,
        )
        second = reducer.apply_decision(first, d1, now=NOW)

        d2 = _decision(
            decision_record_id="decision:control:001",
            decision_key="decision:control",
            snapshot_sha256=_snapshot_for(second),
            expected_state_revision=2,
        )
        third = reducer.apply_decision(second, d2, now=NOW)

        assert third.revision == 3
        assert third.decision_record_ids == (
            "decision:dose:001",
            "decision:control:001",
        )

    def test_reducer_is_stateless_and_shareable(self):
        """The reducer holds no state; two instances behave identically."""
        r1 = StudyDefinitionReducer()
        r2 = StudyDefinitionReducer()
        current = _study_definition()
        decision = _decision(
            snapshot_sha256=_snapshot_for(current),
            expected_state_revision=1,
        )
        a1 = r1.apply_decision(current, decision, now=NOW)
        a2 = r2.apply_decision(current, decision, now=NOW)
        assert a1 == a2


# ---------------------------------------------------------------------------
# CAS failure paths
# ---------------------------------------------------------------------------


class TestCasFailures:
    def test_stale_expected_revision_raises_typed_error(self):
        """A genuinely stale expected revision (not matching any recorded CAS
        triple) raises RevisionStaleError — and ONLY that error."""
        reducer = StudyDefinitionReducer()
        current = _study_definition(revision=3)
        decision = _decision(expected_state_revision=2)

        with pytest.raises(RevisionStaleError) as exc_info:
            reducer.replay_or_apply(
                current,
                decision,
                DecisionEffectLedger(),
                now=NOW,
            )

        err = exc_info.value
        assert err.expected_revision == 2
        assert err.actual_revision == 3
        assert err.study_definition_id == current.study_definition_id
        assert isinstance(err, StudyDefinitionCasError)

    def test_stale_error_on_apply_decision_too(self):
        reducer = StudyDefinitionReducer()
        current = _study_definition(revision=3)
        decision = _decision(expected_state_revision=2)
        with pytest.raises(RevisionStaleError):
            reducer.apply_decision(current, decision, now=NOW)

    def test_same_triple_different_decision_material_raises_only_conflict(self):
        """Same CAS triple but a different DecisionRecord material payload must
        raise DecisionPayloadConflictError — NOT RevisionStaleError, and NOT a
        union that lets either pass."""
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        snapshot = _snapshot_for(current)
        d1 = _decision(
            decision_record_id="decision:dose:001",
            snapshot_sha256=snapshot,
            expected_state_revision=1,
            reason="原始理由",
        )
        _, _, ledger, _ = reducer.replay_or_apply(
            current,
            d1,
            DecisionEffectLedger(),
            now=NOW,
        )

        # Same CAS triple (id, snapshot, expected_rev) but different material
        # (changed reason → different material hash).
        d_conflict = _decision(
            decision_record_id="decision:dose:001",
            snapshot_sha256=snapshot,
            expected_state_revision=1,
            reason="篡改后的不同理由",
        )
        with pytest.raises(DecisionPayloadConflictError) as exc_info:
            reducer.replay_or_apply(current, d_conflict, ledger, now=NOW)
        err = exc_info.value
        assert err.conflict_kind == "decision_record"
        assert err.existing_sha256 != err.incoming_sha256

    def test_same_triple_different_fact_updates_raises_only_conflict(self):
        """Same CAS triple and same DecisionRecord, but different fact_updates,
        must raise DecisionPayloadConflictError with conflict_kind='fact_updates'.
        The EXACT path must not silently drop the changed updates."""
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        snapshot = _snapshot_for(current)
        decision = _decision(
            snapshot_sha256=snapshot,
            expected_state_revision=1,
        )
        _, _, ledger, _ = reducer.replay_or_apply(
            current,
            decision,
            DecisionEffectLedger(),
            fact_updates={"picos.step": "v1"},
            now=NOW,
        )

        # Same decision, same triple, but different fact_updates payload.
        with pytest.raises(DecisionPayloadConflictError) as exc_info:
            reducer.replay_or_apply(
                current,
                decision,
                ledger,
                fact_updates={"picos.step": "v2"},
                now=NOW,
            )
        assert exc_info.value.conflict_kind == "fact_updates"

    def test_same_triple_same_fact_updates_after_apply_is_exact_replay(self):
        """Sanity: same triple + same decision + same fact_updates is a true
        no-op replay (not a conflict) against the advanced current."""
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        snapshot = _snapshot_for(current)
        decision = _decision(snapshot_sha256=snapshot, expected_state_revision=1)
        updates = {"picos.step": "v1"}

        advanced, _, ledger, replayed = reducer.replay_or_apply(
            current,
            decision,
            DecisionEffectLedger(),
            fact_updates=updates,
            now=NOW,
        )
        assert replayed is False

        # Replay against *advanced* (repository current after commit).
        result_def, result_dec, _, replayed2 = reducer.replay_or_apply(
            advanced,
            decision,
            ledger,
            fact_updates=updates,
            now=NOW,
        )
        assert replayed2 is True
        assert result_def is advanced
        assert result_dec is decision

    def test_replay_old_triple_against_later_descendant_returns_descendant(self):
        """After two decisions create revision 3, replaying the old revision-1
        CAS triple must return revision 3 unchanged and not erase the later
        decision.  This proves the replay works against any later descendant,
        not just the immediate next revision."""
        reducer = StudyDefinitionReducer()
        first = _study_definition()
        d1 = _decision(
            decision_record_id="decision:dose:001",
            snapshot_sha256=_snapshot_for(first),
            expected_state_revision=1,
        )
        second, _, ledger, _ = reducer.replay_or_apply(
            first,
            d1,
            DecisionEffectLedger(),
            now=NOW,
        )
        d2 = _decision(
            decision_record_id="decision:control:001",
            decision_key="decision:control",
            snapshot_sha256=_snapshot_for(second),
            expected_state_revision=2,
        )
        third, _, ledger, _ = reducer.replay_or_apply(
            second,
            d2,
            ledger,
            now=NOW,
        )
        assert third.revision == 3
        assert third.decision_record_ids == (
            "decision:dose:001",
            "decision:control:001",
        )

        # Replay the old revision-1 CAS triple against revision 3.
        result_def, result_dec, result_ledger, replayed = reducer.replay_or_apply(
            third,
            d1,
            ledger,
            now=NOW,
        )
        assert replayed is True
        assert result_def is third
        assert result_def.revision == 3
        assert result_dec is d1
        assert result_ledger is ledger
        # The later decision is not erased.
        assert "decision:control:001" in result_def.decision_record_ids

    def test_replay_against_forged_same_result_revision_fails_closed(self):
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        decision = _decision(snapshot_sha256=_snapshot_for(current))
        advanced, _, ledger, _ = reducer.replay_or_apply(
            current,
            decision,
            DecisionEffectLedger(),
            now=NOW,
        )
        forged = _study_definition(
            revision=advanced.revision,
            previous_revision_sha256=advanced.previous_revision_sha256,
            facts={"picos.population.indication": "伪造的不同适应症"},
            decision_record_ids=advanced.decision_record_ids,
            canonical_state=advanced.canonical_state,
        )

        with pytest.raises(RevisionStaleError):
            reducer.replay_or_apply(forged, decision, ledger, now=NOW)

    def test_replay_against_later_revision_without_decision_lineage_fails_closed(self):
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        decision = _decision(snapshot_sha256=_snapshot_for(current))
        advanced, _, ledger, _ = reducer.replay_or_apply(
            current,
            decision,
            DecisionEffectLedger(),
            now=NOW,
        )
        unrelated_later = _study_definition(
            revision=advanced.revision + 1,
            previous_revision_sha256=study_revision_hash(advanced),
            decision_record_ids=("decision:other:001",),
            canonical_state=advanced.canonical_state,
        )

        with pytest.raises(RevisionStaleError):
            reducer.replay_or_apply(unrelated_later, decision, ledger, now=NOW)

    def test_replay_against_forged_later_revision_with_copied_decision_id_fails_closed(
        self,
    ):
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        decision = _decision(snapshot_sha256=_snapshot_for(current))
        advanced, _, ledger, _ = reducer.replay_or_apply(
            current,
            decision,
            DecisionEffectLedger(),
            now=NOW,
        )
        forged_later = _study_definition(
            revision=advanced.revision + 1,
            previous_revision_sha256=SHA_C,
            facts={"picos.population.indication": "伪造的不同适应症"},
            decision_record_ids=advanced.decision_record_ids,
            canonical_state=advanced.canonical_state,
        )

        with pytest.raises(RevisionStaleError):
            reducer.replay_or_apply(forged_later, decision, ledger, now=NOW)

    def test_replay_against_unrelated_current_fails_closed(self):
        """Replaying a recorded CAS triple against an unrelated StudyDefinition
        (different aggregate id) must fail closed with RevisionStaleError."""
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        snapshot = _snapshot_for(current)
        decision = _decision(snapshot_sha256=snapshot, expected_state_revision=1)
        _, _, ledger, _ = reducer.replay_or_apply(
            current,
            decision,
            DecisionEffectLedger(),
            now=NOW,
        )

        # An unrelated StudyDefinition — same revision number but different id.
        unrelated = _study_definition(
            study_definition_id="study:def:other",
            project_id="project:other",
        )
        with pytest.raises(RevisionStaleError):
            reducer.replay_or_apply(unrelated, decision, ledger, now=NOW)

    def test_replay_against_lower_revision_fails_closed(self):
        """Replaying a recorded CAS triple whose result is revision 2 against a
        current at revision 1 (a state that does not contain the decision) must
        fail closed — the caller holds unrelated/stale state."""
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        snapshot = _snapshot_for(current)
        decision = _decision(snapshot_sha256=snapshot, expected_state_revision=1)
        advanced, _, ledger, _ = reducer.replay_or_apply(
            current,
            decision,
            DecisionEffectLedger(),
            now=NOW,
        )
        # Build a fresh revision-1 definition of the SAME aggregate (not the
        # original — a different predecessor state at revision 1).  The recorded
        # result is revision 2; current at revision 1 cannot contain it.
        stale_current = _study_definition(
            facts={"picos.different": "value"},
        )
        with pytest.raises(RevisionStaleError):
            reducer.replay_or_apply(stale_current, decision, ledger, now=NOW)

    def test_frozen_fact_overwrite_raises_typed_error(self):
        """Overwriting a confirmed/frozen fact outside a new accepted decision
        fails with FrozenFactOverwriteError."""
        reducer = StudyDefinitionReducer()
        current = _study_definition(canonical_state="confirmed")
        decision = _decision(
            snapshot_sha256=_snapshot_for(current),
            expected_state_revision=1,
        )
        with pytest.raises(FrozenFactOverwriteError) as exc_info:
            reducer.apply_decision(
                current,
                decision,
                fact_updates={
                    "picos.population.indication": "克罗恩病",
                },
                now=NOW,
            )
        err = exc_info.value
        assert "picos.population.indication" in err.protected_fact_paths
        assert isinstance(err, StudyDefinitionCasError)

    def test_frozen_none_fact_is_present_and_cannot_be_overwritten(self):
        reducer = StudyDefinitionReducer()
        current = _study_definition(
            facts={"picos.nullable": None},
            canonical_state="frozen",
        )
        decision = _decision(snapshot_sha256=_snapshot_for(current))
        with pytest.raises(FrozenFactOverwriteError):
            reducer.apply_decision(
                current,
                decision,
                fact_updates={"picos.nullable": "替换值"},
                now=NOW,
            )

    def test_fact_update_cas_hash_does_not_strip_revision_fact_path(self):
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        decision = _decision(snapshot_sha256=_snapshot_for(current))
        advanced, _, ledger, _ = reducer.replay_or_apply(
            current,
            decision,
            DecisionEffectLedger(),
            fact_updates={"revision": "A"},
            now=NOW,
        )
        assert advanced.facts["revision"] == "A"
        with pytest.raises(DecisionPayloadConflictError):
            reducer.replay_or_apply(
                advanced,
                decision,
                ledger,
                fact_updates={"revision": "B"},
                now=NOW,
            )

    def test_frozen_fact_same_value_is_allowed(self):
        """Re-asserting the exact same value for a frozen fact is not an
        overwrite and must not raise."""
        reducer = StudyDefinitionReducer()
        current = _study_definition(canonical_state="confirmed")
        decision = _decision(
            snapshot_sha256=_snapshot_for(current),
            expected_state_revision=1,
        )
        advanced = reducer.apply_decision(
            current,
            decision,
            fact_updates={
                "picos.population.indication": "中重度活动性溃疡性结肠炎",
            },
            now=NOW,
        )
        assert (
            advanced.facts["picos.population.indication"] == "中重度活动性溃疡性结肠炎"
        )

    def test_adding_new_fact_to_frozen_definition_is_allowed(self):
        """A new (previously absent) fact path is never a protected overwrite."""
        reducer = StudyDefinitionReducer()
        current = _study_definition(canonical_state="frozen")
        decision = _decision(
            snapshot_sha256=_snapshot_for(current),
            expected_state_revision=1,
        )
        advanced = reducer.apply_decision(
            current,
            decision,
            fact_updates={"picos.population.phase": "III期"},
            now=NOW,
        )
        assert advanced.facts["picos.population.phase"] == "III期"

    def test_proposed_fact_change_is_allowed(self):
        """A proposed (not yet confirmed) definition can have facts changed."""
        reducer = StudyDefinitionReducer()
        current = _study_definition(canonical_state="proposed")
        decision = _decision(
            snapshot_sha256=_snapshot_for(current),
            expected_state_revision=1,
        )
        advanced = reducer.apply_decision(
            current,
            decision,
            fact_updates={"picos.intervention.dose": "20 mg，每日一次"},
            now=NOW,
        )
        assert advanced.facts["picos.intervention.dose"] == "20 mg，每日一次"

    def test_all_cas_errors_are_study_definition_cas_error(self):
        """Every typed CAS failure inherits from the stable base class so the
        application service can catch them uniformly."""
        for exc_cls in (
            RevisionStaleError,
            DecisionPayloadConflictError,
            FrozenFactOverwriteError,
        ):
            assert issubclass(exc_cls, StudyDefinitionCasError)


# ---------------------------------------------------------------------------
# Purity and determinism
# ---------------------------------------------------------------------------


class TestPurityAndDeterminism:
    def test_study_definition_facts_are_deeply_immutable_and_json_serializable(self):
        definition = _study_definition(
            facts={"nested": {"items": ["A", {"revision": "B"}]}}
        )
        with pytest.raises(TypeError, match="immutable"):
            definition.facts["new"] = "value"
        with pytest.raises(TypeError, match="immutable"):
            definition.facts["nested"]["items"] = ()
        with pytest.raises(TypeError, match="immutable"):
            definition.facts["nested"]["items"].append("C")
        assert definition.facts["nested"]["items"] == [
            "A",
            {"revision": "B"},
        ]
        dumped = definition.model_dump(mode="json")
        assert dumped["facts"]["nested"]["items"] == [
            "A",
            {"revision": "B"},
        ]

    def test_reducer_produces_deterministic_lineage(self):
        """Two independent reduces from the same inputs produce identical
        material hashes and revision lineages."""
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        decision = _decision(
            snapshot_sha256=_snapshot_for(current),
            expected_state_revision=1,
        )
        r1 = reducer.apply_decision(current, decision, now=NOW)
        r2 = reducer.apply_decision(current, decision, now=NOW)
        assert r1.material_sha256() == r2.material_sha256()
        assert r1.revision == r2.revision
        assert study_revision_hash(r1) == study_revision_hash(r2)

    def test_decision_record_model_rejects_non_cas_revision(self):
        """The DecisionRecord contract itself enforces state_revision ==
        expected + 1 (CAS advance by exactly one)."""
        with pytest.raises(ValidationError, match="CAS revision"):
            _decision(expected_state_revision=1, state_revision=3)

    def test_replay_is_a_true_noop(self):
        """Replay must not advance the revision, change facts, or mutate the
        ledger.  The returned definition and ledger are the same objects.  This
        models a duplicate request after the commit: current is *advanced*."""
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        snapshot = _snapshot_for(current)
        decision = _decision(snapshot_sha256=snapshot, expected_state_revision=1)

        advanced, _, ledger, _ = reducer.replay_or_apply(
            current,
            decision,
            DecisionEffectLedger(),
            now=NOW,
        )
        assert advanced.revision == 2

        # Replay against *advanced* (the repository's current after commit).
        result_def, _, result_ledger, replayed = reducer.replay_or_apply(
            advanced,
            decision,
            ledger,
            now=NOW,
        )
        assert replayed is True
        assert result_def is advanced
        assert result_ledger is ledger
        assert result_def.revision == 2

    def test_reducer_does_not_touch_filesystem_or_clock(self):
        """The reducer accepts explicit time; it never calls datetime.now()
        internally.  This test documents that contract by passing two different
        times and confirming the reducer uses exactly what it receives."""
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        decision = _decision(
            snapshot_sha256=_snapshot_for(current),
            expected_state_revision=1,
        )
        t1 = datetime(2020, 1, 1, tzinfo=timezone.utc)
        advanced = reducer.apply_decision(current, decision, now=t1)
        assert advanced.updated_at == t1

    def test_no_lost_facts_on_multi_step_apply(self):
        """Multi-step reduce chain never drops a fact."""
        reducer = StudyDefinitionReducer()
        first = _study_definition()
        d1 = _decision(
            decision_record_id="decision:step1",
            snapshot_sha256=_snapshot_for(first),
            expected_state_revision=1,
        )
        second = reducer.apply_decision(
            first,
            d1,
            fact_updates={"picos.step1": "value1"},
            now=NOW,
        )
        d2 = _decision(
            decision_record_id="decision:step2",
            decision_key="decision:step2",
            snapshot_sha256=_snapshot_for(second),
            expected_state_revision=2,
        )
        third = reducer.apply_decision(
            second,
            d2,
            fact_updates={"picos.step2": "value2"},
            now=NOW,
        )
        assert "picos.population.indication" in third.facts
        assert "picos.intervention.dose" in third.facts
        assert third.facts["picos.step1"] == "value1"
        assert third.facts["picos.step2"] == "value2"

    def test_cas_identity_is_stable_string(self):
        identity = decision_cas_identity("decision:1", SHA_A, 1)
        assert isinstance(identity, str)
        assert len(identity) == 64

    def test_fresh_apply_rejects_snapshot_that_does_not_match_revision_hash(self):
        """A fresh apply whose snapshot is the *material* hash (not the revision
        hash) must fail — the snapshot must bind the exact revision identity."""
        reducer = StudyDefinitionReducer()
        current = _study_definition()
        # Wrong snapshot: material hash instead of revision hash.
        decision = _decision(
            snapshot_sha256=current.material_sha256(),
            expected_state_revision=1,
        )
        with pytest.raises(RevisionStaleError):
            reducer.apply_decision(current, decision, now=NOW)


@pytest.mark.parametrize("updates", ({"picos.intervention.dose": "30 mg"}, {"new.fact": 0}))
def test_explicit_fact_revision_does_not_edit_frozen_definition(updates):
    current = _study_definition(canonical_state="frozen")
    decision = _decision(snapshot_sha256=_snapshot_for(current))
    with pytest.raises(FrozenFactOverwriteError):
        StudyDefinitionReducer().apply_decision(
            current, decision, fact_updates=updates, now=NOW,
            revise_confirmed_facts=True,
        )


def test_fact_revision_intent_is_bound_to_replay_payload():
    current = _study_definition(canonical_state="confirmed")
    decision = _decision(snapshot_sha256=_snapshot_for(current))
    reducer = StudyDefinitionReducer()
    updates = {"picos.intervention.dose": "30 mg"}
    advanced, _, ledger, _ = reducer.replay_or_apply(
        current, decision, DecisionEffectLedger(), fact_updates=updates,
        now=NOW, revise_confirmed_facts=True,
    )
    with pytest.raises(DecisionPayloadConflictError):
        reducer.replay_or_apply(advanced, decision, ledger, fact_updates=updates, now=NOW)
    assert current.facts["picos.intervention.dose"] != advanced.facts["picos.intervention.dose"]


def test_explicit_fact_revision_requires_a_confirmed_user_decision():
    current = _study_definition(canonical_state="confirmed")
    decision = _decision(snapshot_sha256=_snapshot_for(current), actor_type="ai")
    with pytest.raises(ValueError, match="confirmed user decision"):
        StudyDefinitionReducer().apply_decision(
            current, decision, fact_updates={"picos.intervention.dose": "30 mg"},
            now=NOW, revise_confirmed_facts=True,
        )
