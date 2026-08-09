"""Focused tests for design projection normalization — Slice A foundation.

Worker 01 — mw_design_projection_unification_20260724 (acceptance remediation 01).

These tests verify:
1. NormalizedDesignProjection contract is correctly constructed.
2. Unresolved Phase I Parts produce precise blockers and block deterministic projection.
3. Non-Phase I studies filter out residual Phase I Parts as applicable design content.
4. Decided structured randomization projects correctly even when picos.design_archetype is empty.
5. Legacy free text is used only when the corresponding structured field is undecided.

Counterexamples (required by Slice A):
a) Unresolved SAD (empty population/cohort_dose) blocks deterministic projection.
b) Phase III with residual phase1_parts does not treat them as applicable.
c) Structured randomization decided while picos.design_archetype empty still projects from structured.
d) Legacy text fallback works when structured is undecided.
e) Phase detection handles all declared cases (I 期，I/II 期，PHASE1, first-in-human).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from packages.contracts.workbench_contracts import (
    MedicalWritingNormalizedDesignProjection,
    MedicalWritingPhase1Part,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyDefinition,
    MedicalWritingStudyFraming,
    MedicalWritingStructuredStudyDesign,
)
from services.api.app.medical_writing_design_projection import (
    normalize_study_design,
    _is_phase_one,
    _PHASE1_BLOCKED_PROJECTIONS,
)


NOW = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)


def _create_definition(
    study_phase: str = "I 期",
    phase1_parts=None,
    randomization_mode: str = "undecided",
    blinding_mode: str = "undecided",
    comparator_type: str = "undecided",
    legacy_design_pattern: str = "",
    design_archetype: str = "",
) -> MedicalWritingStudyDefinition:
    """Create a minimal StudyDefinition for tests."""
    if phase1_parts is None:
        phase1_parts = []

    design = MedicalWritingStructuredStudyDesign(
        randomization_mode=randomization_mode,
        blinding_mode=blinding_mode,
        comparator_type=comparator_type,
        phase1_parts=phase1_parts,
    )

    framing = MedicalWritingStudyFraming(
        protocol_id="PROTO-TEST",
        document_title="Test Protocol",
        indication="Test Indication",
        clinicaltrials_condition_term="Test Condition",
        study_phase=study_phase,
        investigational_product="TEST-IP",
        design_pattern=legacy_design_pattern,
        structured_design=design,
    )

    return MedicalWritingStudyDefinition(
        definition_id="test-def-001",
        project_id="test-proj-001",
        revision=1,
        origin="guided_greenfield",
        framing=framing,
        picos=MedicalWritingPicosDefinition(
            design_archetype=design_archetype,
        ),
        state_sha256="a" * 64,
        created_at=NOW,
        updated_at=NOW,
        updated_by="test",
    )


class TestNormalizedDesignProjectionContract(unittest.TestCase):
    """Slice A Counterexample 1: Unresolved SAD part blocks deterministic projection."""

    def test_unresolved_sad_part_blocks_deterministic_projection(self):
        """Selected but unresolved SAD Part with missing population/cohort_dose must:
        - Produce precise blocker question.
        - Set deterministic_projection_allowed=False.
        - List affected projections.
        """
        # Build Phase I study with unresolved SAD Part.
        unresolved_part = MedicalWritingPhase1Part(
            part_code="SAD",
            part_label="Single Ascending Dose",
            population="",  # Missing!
            cohort_dose="",  # Missing!
            pk_pd="",
            safety="",
            stopping_rules="",
            soa_summary="",
            transition_dependencies="",
        )

        definition = _create_definition(
            study_phase="I 期",
            phase1_parts=[unresolved_part],
            randomization_mode="non_randomized",
            blinding_mode="open_label",
            comparator_type="none_or_dose_escalation",
        )

        projection = normalize_study_design(definition, include_sources=False)

        # Verify projection exists.
        self.assertIsInstance(projection, MedicalWritingNormalizedDesignProjection)

        # Verify unresolved Part produces blockers.
        self.assertTrue(
            len(projection.blockers) > 0,
            "Unresolved SAD Part must produce at least one blocker question.",
        )

        # Verify deterministic_projection_allowed is False.
        self.assertFalse(
            projection.deterministic_projection_allowed,
            "Unresolved Phase I Parts must block deterministic projection.",
        )

        # Verify affected_projections is non-empty.
        self.assertTrue(
            len(projection.affected_projections) > 0,
            "Blockers must specify which projections are affected.",
        )

        # Verify blocker has precise prompt about missing fields.
        blocker_prompt = projection.blockers[0].prompt
        self.assertIn("population", blocker_prompt.lower())
        self.assertIn("cohort_dose", blocker_prompt.lower())

    def test_resolved_sad_part_allows_deterministic_projection(self):
        """Resolved SAD Part with population and cohort_dose must allow projection."""
        resolved_part = MedicalWritingPhase1Part(
            part_code="SAD",
            part_label="Single Ascending Dose",
            population="Healthy adults aged 18-55",
            cohort_dose="3+3 escalation: 10mg, 30mg, 100mg",
            pk_pd="PK sampling at 0, 0.5, 1, 2, 4, 8, 24h post-dose",
            safety="AE monitoring every visit; lab assessments twice weekly",
            stopping_rules="DLT defined as CTCAE grade 3+ AE attributable to drug",
            soa_summary="Screening, Day 1 dose administration, PK sampling, Safety follow-up",
        )

        definition = _create_definition(
            study_phase="I 期",
            phase1_parts=[resolved_part],
            randomization_mode="non_randomized",
            blinding_mode="open_label",
            comparator_type="none_or_dose_escalation",
        )

        projection = normalize_study_design(definition, include_sources=False)

        # Verify no blockers when Part is resolved.
        self.assertEqual(
            len(projection.blockers),
            0,
            "Resolved Part should not produce blockers.",
        )

        # Verify deterministic projection is allowed.
        self.assertTrue(
            projection.deterministic_projection_allowed,
            "Resolved Phase I Parts should allow deterministic projection.",
        )

    def test_population_and_cohort_are_the_only_current_phase1_required_fields(self):
        definition = _create_definition(
            study_phase="I期",
            phase1_parts=[
                MedicalWritingPhase1Part(
                    part_code="SAD",
                    population="健康受试者",
                    cohort_dose="10、30、100 mg剂量递增队列",
                )
            ],
        )
        projection = normalize_study_design(definition)
        self.assertEqual(projection.blockers, [])
        self.assertTrue(projection.deterministic_projection_allowed)


class TestNonPhaseIFiltering(unittest.TestCase):
    """Slice A Counterexample 2: Phase III must not surface Phase I Parts."""

    def test_phase3_filters_out_phase1_parts_from_projection(self):
        """Phase III study with residual Phase I Parts must filter them completely."""
        resolved_part = MedicalWritingPhase1Part(
            part_code="SAD",
            population="Healthy adults",
            cohort_dose="10mg, 30mg, 100mg",
        )

        definition = _create_definition(
            study_phase="III 期",  # Not Phase I!
            phase1_parts=[resolved_part],  # Residual Part should be filtered.
            randomization_mode="randomized",
            blinding_mode="double_blind",
            comparator_type="placebo",
        )

        projection = normalize_study_design(definition, include_sources=False)

        # Verify Phase I Parts are filtered from design_view.
        self.assertEqual(
            len(projection.design_view.phase1_parts),
            0,
            "Phase III must not surface Phase I Parts in normalized design view.",
        )

        # Verify other structured fields are preserved.
        self.assertEqual(projection.design_view.randomization_mode, "randomized")
        self.assertEqual(projection.design_view.blinding_mode, "double_blind")
        self.assertEqual(projection.design_view.comparator_type, "placebo")

    def test_phase3_with_illegal_phase1_exposure_should_not_happen(self):
        """If Phase I Parts somehow remain after normalization, consistency check should catch it."""
        # Note: In current implementation, this is handled by filtering in normalize_study_design().
        # The consistency validation will add a blocker if Phase I Parts leak into non-Phase I projections.
        part = MedicalWritingPhase1Part(part_code="MAD", population="", cohort_dose="")
        
        definition = _create_definition(
            study_phase="III 期",
            phase1_parts=[part],
            randomization_mode="randomized",
            blinding_mode="double_blind",
            comparator_type="active",
        )

        # Normalization filters Phase I Parts for non-Phase I studies.
        projection = normalize_study_design(definition, include_sources=False)

        self.assertEqual(
            len(projection.design_view.phase1_parts),
            0,
            "Normalization service must filter Phase I Parts for Phase III+",
        )


class TestStructuredAuthorityOverLegacy(unittest.TestCase):
    """Slice A Counterexample 3 & 4: Structured fields win over legacy text."""

    def test_structured_randomization_used_when_decided(self):
        """Decided structured randomization must be used even when PICOS archetype is empty/contradictory."""
        definition = _create_definition(
            study_phase="III 期",
            phase1_parts=[],
            randomization_mode="randomized",  # Structured is decided!
            blinding_mode="double_blind",
            comparator_type="placebo",
            legacy_design_pattern="",  # Empty legacy field
        )

        projection = normalize_study_design(definition, include_sources=False)

        # Verify structured value is used.
        self.assertEqual(
            projection.design_view.randomization_mode,
            "randomized",
            "Structured randomization wins over empty PICOS archetype.",
        )

    def test_legacy_text_cannot_override_decided_structured_fields(self):
        definition = _create_definition(
            study_phase="III期",
            randomization_mode="randomized",
            blinding_mode="double_blind",
            comparator_type="placebo",
            legacy_design_pattern="非随机、开放标签、阳性对照研究",
        )
        projection = normalize_study_design(definition)
        self.assertEqual(projection.design_view.randomization_mode, "randomized")
        self.assertEqual(projection.design_view.blinding_mode, "double_blind")
        self.assertEqual(projection.design_view.comparator_type, "placebo")

    def test_legacy_text_used_when_structured_undecided(self):
        definition = _create_definition(
            study_phase="III期",
            legacy_design_pattern="随机、开放标签、阳性对照研究",
        )
        projection = normalize_study_design(definition)
        self.assertEqual(projection.design_view.randomization_mode, "randomized")
        self.assertEqual(projection.design_view.blinding_mode, "open_label")
        self.assertEqual(projection.design_view.comparator_type, "active")


class TestPhaseDetectionHelpers(unittest.TestCase):
    """Helper function tests for phase detection logic."""

    def test_is_phase_one_identifies_I_phase(self):
        """Verify _is_phase_one correctly identifies Phase I studies."""
        self.assertTrue(_is_phase_one("I 期"))
        self.assertTrue(_is_phase_one("I期/II期"))
        self.assertTrue(_is_phase_one("I 期/II 期"))
        self.assertTrue(_is_phase_one("I/II期"))
        self.assertTrue(_is_phase_one("I/II 期"))
        self.assertTrue(_is_phase_one("I期"))
        self.assertTrue(_is_phase_one("phase i"))
        self.assertTrue(_is_phase_one("Phase I"))
        self.assertTrue(_is_phase_one("PHASE1"))
        self.assertTrue(_is_phase_one("FIH"))
        self.assertTrue(_is_phase_one("first-in-human"))
        self.assertTrue(_is_phase_one("first-in-human=true"))
        self.assertTrue(_is_phase_one("fi h"))

    def test_is_phase_one_rejects_non_phase_one(self):
        """Verify _is_phase_one rejects Phase II/III/IV studies."""
        self.assertFalse(_is_phase_one("II 期"))
        self.assertFalse(_is_phase_one("III 期"))
        self.assertFalse(_is_phase_one("IV 期"))
        self.assertFalse(_is_phase_one("II/III期"))
        self.assertFalse(_is_phase_one("PHASE2"))
        self.assertFalse(_is_phase_one("Phase II"))
        self.assertFalse(_is_phase_one("first-in-human=false"))
        self.assertFalse(_is_phase_one(""))
        self.assertFalse(_is_phase_one(None))


class TestAffectedProjections(unittest.TestCase):
    """Verify that all projections are listed as affected when blockers exist."""

    def test_all_projections_blocked_when_phase1_unresolved(self):
        """All 7 projections should be marked as affected when Phase I Parts are unresolved."""
        unresolved_part = MedicalWritingPhase1Part(
            part_code="SAD",
            population="",
            cohort_dose="",
        )

        definition = _create_definition(
            study_phase="I 期",
            phase1_parts=[unresolved_part],
        )

        projection = normalize_study_design(definition, include_sources=False)

        # All 7 projections should be affected.
        expected_projections = set(_PHASE1_BLOCKED_PROJECTIONS)
        actual_projections = set(projection.affected_projections)

        self.assertSetEqual(
            expected_projections,
            actual_projections,
            f"All {len(expected_projections)} projections should be marked as blocked when Phase I Parts are unresolved.",
        )


class TestLegacyTextFallback(unittest.TestCase):
    """Test that legacy text is used ONLY when structured fields are undecided."""

    def test_legacy_randomization_seeds_undecided_structured(self):
        """Structured=randomized wins; only undecided structured uses legacy."""
        definition = _create_definition(
            study_phase="III 期",
            phase1_parts=[],
            randomization_mode="undecided",  # Undecided!
            blinding_mode="double_blind",
            comparator_type="placebo",
            legacy_design_pattern="double-blind randomized placebo-controlled",
        )

        projection = normalize_study_design(definition, include_sources=False)

        # Legacy text should seed randomization from design_pattern.
        self.assertEqual(
            projection.design_view.randomization_mode,
            "randomized",
            "Undecided structured should be seeded from legacy design_pattern.",
        )
        self.assertEqual(
            projection.design_view.blinding_mode,
            "double_blind",
            "Decided structured should win over everything.",
        )

    def test_decided_structured_blocks_legacy_fallback(self):
        """Decided structured values must NOT use legacy even if contradictory."""
        definition = _create_definition(
            study_phase="III 期",
            phase1_parts=[],
            randomization_mode="randomized",  # Decided!
            blinding_mode="open_label",
            comparator_type="active",
            legacy_design_pattern="non-randomized double-blind placebo-controlled",
        )

        projection = normalize_study_design(definition, include_sources=False)

        # Structured decisions win, even if contradictory to legacy.
        self.assertEqual(
            projection.design_view.randomization_mode,
            "randomized",
            "Decided structured value should win over contradictory legacy.",
        )
        self.assertEqual(
            projection.design_view.blinding_mode,
            "open_label",
            "Decided structured blinding should win.",
        )
        self.assertEqual(
            projection.design_view.comparator_type,
            "active",
            "Decided structured comparator should win.",
        )

    def test_empty_legacy_stays_undecided(self):
        """Unsupported free text remains undecided rather than invented."""
        definition = _create_definition(
            study_phase="III 期",
            phase1_parts=[],
            randomization_mode="undecided",
            blinding_mode="undecided",
            comparator_type="undecided",
            legacy_design_pattern="some unsupported gibberish text",
        )

        projection = normalize_study_design(definition, include_sources=False)

        # Unsupported text should stay undecided.
        self.assertEqual(
            projection.design_view.randomization_mode,
            "undecided",
            "Unsupported legacy text should remain undecided.",
        )
        self.assertEqual(
            projection.design_view.blinding_mode,
            "undecided",
        )
        self.assertEqual(
            projection.design_view.comparator_type,
            "undecided",
        )

    def test_chinese_nonrandomized_single_blind_no_control_is_supported(self):
        definition = _create_definition(
            study_phase="II期",
            legacy_design_pattern="非随机、单盲、无对照研究",
        )
        projection = normalize_study_design(definition)
        self.assertEqual(projection.design_view.randomization_mode, "non_randomized")
        self.assertEqual(projection.design_view.blinding_mode, "single_blind")
        self.assertEqual(
            projection.design_view.comparator_type,
            "none_or_dose_escalation",
        )

    def test_picos_archetype_is_used_only_for_undecided_structured_fact(self):
        definition = _create_definition(
            study_phase="III期",
            design_archetype="randomized_exploratory",
        )
        projection = normalize_study_design(definition, include_sources=True)
        self.assertEqual(projection.design_view.randomization_mode, "randomized")
        self.assertEqual(
            projection.design_fact_paths["randomization_mode"],
            "picos.design_archetype",
        )

    def test_conflicting_legacy_semantics_remain_undecided(self):
        definition = _create_definition(
            study_phase="III期",
            legacy_design_pattern="双盲治疗期后进入开放标签延展期",
        )
        projection = normalize_study_design(definition)
        self.assertEqual(projection.design_view.blinding_mode, "undecided")

    def test_design_pattern_and_picos_conflict_remains_undecided(self):
        definition = _create_definition(
            study_phase="III期",
            legacy_design_pattern="非随机研究",
            design_archetype="randomized_exploratory",
        )
        projection = normalize_study_design(definition)
        self.assertEqual(projection.design_view.randomization_mode, "undecided")

    def test_bare_open_and_triple_blind_terms_are_supported(self):
        open_definition = _create_definition(
            study_phase="II期",
            legacy_design_pattern="开放研究",
        )
        triple_definition = _create_definition(
            study_phase="II期",
            legacy_design_pattern="triple-blind study",
        )
        self.assertEqual(
            normalize_study_design(open_definition).design_view.blinding_mode,
            "open_label",
        )
        self.assertEqual(
            normalize_study_design(triple_definition).design_view.blinding_mode,
            "triple_blind",
        )

    def test_include_sources_returns_fact_paths(self):
        """include_sources=True returns MedicalWritingNormalizedDesignProjectionWithSources with valid paths."""
        definition = _create_definition(
            study_phase="I 期",
            phase1_parts=[MedicalWritingPhase1Part(part_code="SAD", population="Healthy", cohort_dose="10mg")],
            randomization_mode="non_randomized",
            blinding_mode="open_label",
            comparator_type="none_or_dose_escalation",
        )

        projection = normalize_study_design(definition, include_sources=True)

        # Verify type.
        from packages.contracts.workbench_contracts import MedicalWritingNormalizedDesignProjectionWithSources
        self.assertIsInstance(projection, MedicalWritingNormalizedDesignProjectionWithSources)

        # Verify fact_paths has semantic -> canonical path mapping.
        self.assertIn("study_phase", projection.design_fact_paths)
        self.assertIn("randomization_mode", projection.design_fact_paths)
        self.assertIn("blinding_mode", projection.design_fact_paths)
        self.assertIn("comparator_type", projection.design_fact_paths)
        
        # Verify values are canonical paths (not values).
        self.assertEqual(projection.design_fact_paths["randomization_mode"], "framing.structured_design.randomization_mode")
        self.assertEqual(projection.design_fact_paths["blinding_mode"], "framing.structured_design.blinding_mode")

    def test_multiple_legacy_semantics_can_share_one_source_path(self):
        definition = _create_definition(
            study_phase="III期",
            legacy_design_pattern="随机、双盲、安慰剂对照研究",
        )
        projection = normalize_study_design(definition, include_sources=True)
        for semantic in (
            "randomization_mode",
            "blinding_mode",
            "comparator_type",
        ):
            self.assertEqual(
                projection.design_fact_paths[semantic],
                "framing.design_pattern",
            )


if __name__ == "__main__":
    unittest.main()
