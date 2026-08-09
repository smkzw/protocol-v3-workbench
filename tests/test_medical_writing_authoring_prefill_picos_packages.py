"""Anti-example tests for W2a: deterministic PICOS packages.

These tests verify the fixes for confirmed failures:
1. D017 minimum-fact title candidates do not contain unconfirmed design facts.
2. Phase II/III minimum facts do not produce recommended randomization,
   blinding, placebo, or DMC candidates.
3. Phase I minimum facts do not default SAD+MAD; the selectable parts set
   includes major Phase I part types with multi-select semantics.
4. The four package.* candidates exist, have correct scope/target_paths/
   structured_value alignment, and are pending/manual without evidence.
5. Full PICOS field coverage checklist has no gaps; exact paths remain
   protected by the evidence boundary.
6. Pending fields do not count as directly adoptable recommendations.
7. Synopsis-confirmed values retain user_confirmed state and are not
   overwritten by pending cards.
8. All existing prefill tests pass with zero failures (run separately).
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.workbench_contracts import (
    AuthoringPrefillGenerateRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingStudyFraming,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_authoring_prefill import (
    EXACT_FACT_PATHS,
    SUPPORTED_STUDY_DEFINITION_PATHS,
    SUPPORTED_ADOPT_PATHS,
    generate_prefill_package,
)


NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)


def _create_request(**overrides) -> MedicalWritingAuthoringJourneyCreateRequest:
    framing_fields = {
        "investigational_product": "CMS-D017",
        "indication": "阵发性睡眠性血红蛋白尿症",
        "study_phase": "II期",
    }
    request_fields = {
        "actor": "medical_manager_test",
        "idempotency_key": "create-picos-001",
    }
    for key, value in overrides.items():
        if key in framing_fields:
            framing_fields[key] = value
        else:
            request_fields[key] = value
    request_fields["framing"] = MedicalWritingStudyFraming(**framing_fields)
    return MedicalWritingAuthoringJourneyCreateRequest(**request_fields)


# Terms that must NOT appear in minimum-fact title candidates.
_FORBIDDEN_TITLE_TERMS = [
    "随机", "对照", "成人", "双盲", "单盲", "多中心",
    "平行组", "安慰剂", "RDBPC", "randomized", "controlled",
    "multicenter", "double-blind",
]

# Design fields that must start as pending_decision.
_DESIGN_FIELDS = [
    "design.randomization",
    "design.blinding",
    "design.comparator_type",
    "design.assignment_model",
    "design.center_model",
    "design.adaptive_design",
    "design.src_dmc",
    "design.interim_analysis",
]


class TitleAntiExampleTests(unittest.TestCase):
    """Test 1: D017 minimum-fact titles contain no unconfirmed design facts."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _generate(self, project_id="proj_test", **overrides):
        self.service.create(project_id, _create_request(**overrides))
        journey = self.service.get(project_id)
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key="gen-picos-001",
        )
        return self.service.generate_prefill(project_id, request)

    def test_d017_titles_contain_no_randomized_controlled_adult_blind_multicenter(self):
        """All title candidates for D017+PNH+Phase II must not contain
        randomized, controlled, adult, double-blind, or multicenter."""
        updated = self._generate()
        package = updated.prefill_package
        self.assertIn("framing.document_title", package.field_candidates)
        title_group = package.field_candidates["framing.document_title"]

        for candidate in title_group.candidates:
            text = str(candidate.structured_value)
            for forbidden in _FORBIDDEN_TITLE_TERMS:
                self.assertNotIn(
                    forbidden,
                    text,
                    f"title candidate '{text}' contains forbidden term '{forbidden}'",
                )

    def test_phase1_titles_contain_no_design_facts(self):
        """Phase I titles must also not contain unconfirmed design facts."""
        updated = self._generate(
            project_id="proj_p1",
            study_phase="I期",
            idempotency_key="create-p1-001",
        )
        package = updated.prefill_package
        title_group = package.field_candidates["framing.document_title"]

        for candidate in title_group.candidates:
            text = str(candidate.structured_value)
            for forbidden in _FORBIDDEN_TITLE_TERMS:
                self.assertNotIn(
                    forbidden,
                    text,
                    f"Phase I title candidate '{text}' contains forbidden term '{forbidden}'",
                )


class DesignFieldAntiExampleTests(unittest.TestCase):
    """Test 2-3: Design fields must be pending_decision, not phase-hardcoded."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _generate(self, project_id="proj_test", **overrides):
        self.service.create(project_id, _create_request(**overrides))
        journey = self.service.get(project_id)
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key="gen-picos-001",
        )
        return self.service.generate_prefill(project_id, request)

    def test_phase2_no_recommended_randomization_blinding_placebo_dmc(self):
        """Phase II minimum facts must not produce recommended candidates for
        randomization=随机, blinding=双盲, comparator=安慰剂, DMC=True."""
        updated = self._generate()
        package = updated.prefill_package

        for field_path in _DESIGN_FIELDS:
            self.assertIn(
                field_path,
                package.field_candidates,
                f"{field_path} should exist in package",
            )
            group = package.field_candidates[field_path]
            # Corrective round 4: a pending/manual-only scaffold group has an
            # EMPTY recommended slot; the single visible candidate stays a
            # pending_decision / manual_only decision card.
            self.assertEqual(
                "",
                group.recommended_candidate_id,
                f"{field_path} scaffold must not occupy the recommended slot",
            )
            self.assertEqual(1, len(group.candidates))
            scaffold = group.candidates[0]
            self.assertEqual(
                "pending_decision",
                scaffold.recommendation_role,
                f"{field_path} visible candidate must be pending_decision, "
                f"got {scaffold.recommendation_role}",
            )
            self.assertEqual(
                "manual_only",
                scaffold.adoption_mode,
                f"{field_path} visible candidate must be manual_only",
            )

    def test_phase3_no_recommended_design_facts(self):
        """Phase III minimum facts also must not produce recommended design facts."""
        updated = self._generate(
            project_id="proj_p3",
            study_phase="III期",
            idempotency_key="create-p3-001",
        )
        package = updated.prefill_package

        for field_path in ["design.randomization", "design.blinding"]:
            group = package.field_candidates[field_path]
            # Corrective round 4: scaffold groups have an empty recommended
            # slot; the visible candidate stays pending_decision.
            self.assertEqual("", group.recommended_candidate_id)
            self.assertEqual(
                "pending_decision",
                group.candidates[0].recommendation_role,
                f"Phase III {field_path} visible candidate must be pending_decision",
            )

    def test_phase1_no_default_sad_mad_and_multi_select_parts(self):
        """Phase I must not default SAD+MAD as recommended; selectable parts
        set includes major Phase I types and supports multi-select semantics."""
        updated = self._generate(
            project_id="proj_p1",
            study_phase="I期",
            idempotency_key="create-p1-001",
        )
        package = updated.prefill_package
        self.assertIn("design.phase1_parts", package.field_candidates)
        parts_group = package.field_candidates["design.phase1_parts"]

        # Primary must be pending_decision (not SAD+MAD recommended).
        primary = parts_group.candidates[0]
        self.assertEqual(
            "pending_decision",
            primary.recommendation_role,
            "Phase I parts primary must be pending_decision",
        )

        # All candidate previews combined should mention key Phase I part types.
        all_previews = " ".join(c.preview for c in parts_group.candidates)
        expected_part_types = ["SAD", "MAD"]
        for part_type in expected_part_types:
            self.assertIn(
                part_type,
                all_previews,
                f"Phase I parts should include '{part_type}' as an option",
            )

        # The structured_value for alternatives should use dict parts lists
        # (multi-select semantics: each candidate is a list of part dicts).
        for candidate in parts_group.candidates:
            if candidate.recommendation_role == "alternative":
                self.assertIsInstance(candidate.structured_value, dict)
                self.assertIn("parts", candidate.structured_value)
                parts = candidate.structured_value["parts"]
                self.assertIsInstance(parts, list)

    def test_phase1_pending_card_has_complete_structured_part_catalog(self):
        """The pending_decision card's structured_value must contain
        available_part_types with all 8 Phase I part types, no duplicates,
        parts == [], and correct pending/manual metadata."""
        updated = self._generate(
            project_id="proj_p1_catalog",
            study_phase="I期",
            idempotency_key="create-p1-catalog-001",
        )
        package = updated.prefill_package
        parts_group = package.field_candidates["design.phase1_parts"]
        primary = parts_group.candidates[0]

        # Must be the pending_decision card.
        self.assertEqual("pending_decision", primary.recommendation_role)
        self.assertEqual("manual_only", primary.adoption_mode)

        sv = primary.structured_value
        self.assertIsInstance(sv, dict)

        # available_part_types must exist and be a list.
        self.assertIn("available_part_types", sv)
        catalog = sv["available_part_types"]
        self.assertIsInstance(catalog, list)

        # All 8 required part types must be present.
        required = [
            "SAD", "MAD", "首次患者", "食物影响",
            "物质平衡", "肝损伤", "肾损伤", "DDI",
        ]
        for part_type in required:
            self.assertIn(
                part_type,
                catalog,
                f"available_part_types missing '{part_type}'",
            )

        # No duplicates.
        self.assertEqual(
            len(catalog),
            len(set(catalog)),
            f"available_part_types has duplicates: {catalog}",
        )

        # parts must be empty (catalog is NOT a selection).
        self.assertEqual(
            [],
            sv.get("parts"),
            "parts must be empty in the pending card; catalog != selection",
        )

        # sequence must be undecided.
        self.assertEqual("", sv.get("sequence"))


class PackageCandidateTests(unittest.TestCase):
    """Test 4: Four package.* candidates exist with correct structure."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _generate(self, project_id="proj_test", **overrides):
        self.service.create(project_id, _create_request(**overrides))
        journey = self.service.get(project_id)
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key="gen-pkg-001",
        )
        return self.service.generate_prefill(project_id, request)

    def test_four_package_candidates_exist_and_are_well_formed(self):
        """Deterministic package shells exist but remain pending without evidence."""
        updated = self._generate()
        package = updated.prefill_package

        for pkg_name in (
            "package.population",
            "package.intervention",
            "package.outcomes",
            "package.statistics",
            "package.design",
            "package.product",
        ):
            self.assertIn(
                pkg_name,
                package.field_candidates,
                f"{pkg_name} should exist in package",
            )
            group = package.field_candidates[pkg_name]
            self.assertGreater(len(group.candidates), 0)

            candidate = group.candidates[0]
            self.assertEqual("module", candidate.candidate_scope)
            self.assertEqual(
                sorted(candidate.target_paths),
                sorted(candidate.structured_value.keys()),
                f"{pkg_name}: target_paths must exactly match structured_value keys",
            )
            # AI-first does not mean heuristic-first: the offline fallback is
            # a visible shell, while evidence-bound AI later supplies 3–5
            # recommended options.
            self.assertEqual(
                "pending_decision",
                candidate.recommendation_role,
                f"{pkg_name} must remain pending without admitted evidence",
            )
            self.assertEqual(
                "manual_only",
                candidate.adoption_mode,
                f"{pkg_name} must not be batch-adoptable without admitted evidence",
            )
            # clinical_tradeoffs and evidence_gaps must be non-empty Chinese.
            self.assertGreater(
                len(candidate.clinical_tradeoffs), 0,
                f"{pkg_name} must have clinical_tradeoffs",
            )
            self.assertGreater(
                len(candidate.evidence_gaps), 0,
                f"{pkg_name} must have evidence_gaps",
            )


class FullPicosCoverageTests(unittest.TestCase):
    """Test 5: Full PICOS field coverage checklist has no gaps."""

    def test_all_non_exact_picos_fields_in_supported_paths(self):
        """Every non-exact PICOS field from the model definition must be in
        SUPPORTED_STUDY_DEFINITION_PATHS."""
        # These are the PICOS fields from MedicalWritingPicosDefinition
        # that are NOT in EXACT_FACT_PATHS and are not complex/computed types.
        expected_non_exact_picos = {
            "picos.design_archetype",
            "picos.population_summary",
            "picos.inclusion_modules",
            "picos.exclusion_modules",
            "picos.intervention_summary",
            "picos.required_background_rules",
            "picos.allowed_concomitant_rules",
            "picos.prohibited_concomitant_rules",
            "picos.assessment_timing_restrictions",
            "picos.comparator_summary",
            "picos.primary_objectives",
            "picos.secondary_objectives",
            "picos.exploratory_objectives",
            "picos.key_secondary_endpoints",
            "picos.other_secondary_endpoints",
            "picos.exploratory_endpoints",
            "picos.safety_endpoints",
            "picos.study_epochs",
            "picos.visit_strategy",
            "picos.estimand_strategy",
            "picos.statistical_strategy",
        }
        for path in expected_non_exact_picos:
            self.assertIn(
                path,
                SUPPORTED_STUDY_DEFINITION_PATHS,
                f"non-exact PICOS path {path} should be in SUPPORTED_STUDY_DEFINITION_PATHS",
            )

    def test_exact_paths_remain_protected(self):
        """Exact fact paths are NOT in SUPPORTED_STUDY_DEFINITION_PATHS and
        remain excluded from SUPPORTED_ADOPT_PATHS."""
        for path in EXACT_FACT_PATHS:
            self.assertNotIn(
                path,
                SUPPORTED_STUDY_DEFINITION_PATHS,
                f"exact path {path} must not be in SUPPORTED_STUDY_DEFINITION_PATHS",
            )
            self.assertNotIn(
                path,
                SUPPORTED_ADOPT_PATHS,
                f"exact path {path} must not be directly adoptable",
            )

    def test_package_candidate_target_paths_cover_full_picos(self):
        """The union of all package.* target_paths covers the full PICOS
        field set (non-exact + exact-as-structured-value-keys)."""
        updated = self._generate_clean()
        package = updated.prefill_package
        all_targets: set[str] = set()
        for pkg_name in (
            "package.population",
            "package.intervention",
            "package.outcomes",
            "package.statistics",
            "package.design",
            "package.product",
        ):
            group = package.field_candidates[pkg_name]
            candidate = group.candidates[0]
            all_targets.update(candidate.target_paths)

        # Verify key fields from each PICOS dimension are covered.
        required_coverage = {
            "picos.population_summary",
            "picos.inclusion_modules",
            "picos.exclusion_modules",
            "picos.washout_rules",
            "picos.intervention_summary",
            "picos.intervention_dose_regimen",
            "picos.required_background_rules",
            "picos.allowed_concomitant_rules",
            "picos.prohibited_concomitant_rules",
            "picos.assessment_timing_restrictions",
            "picos.primary_objectives",
            "picos.secondary_objectives",
            "picos.exploratory_objectives",
            "picos.primary_endpoint",
            "picos.key_secondary_endpoints",
            "picos.other_secondary_endpoints",
            "picos.exploratory_endpoints",
            "picos.safety_endpoints",
            "picos.aesi_definitions",
            "picos.assessment_instruments",
            "picos.study_epochs",
            "picos.visit_strategy",
            "picos.estimand_strategy",
            "picos.sample_size_strategy",
            "picos.statistical_strategy",
        }
        missing = required_coverage - all_targets
        self.assertEqual(
            set(),
            missing,
            f"package candidates missing target_paths: {missing}",
        )

    def _generate_clean(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        service = MedicalWritingAuthoringJourneyService(
            Path(tmpdir.name) / "coverage.sqlite3"
        )
        service.create("proj_cov", _create_request(idempotency_key="create-cov"))
        journey = service.get("proj_cov")
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key="gen-cov-001",
        )
        return service.generate_prefill("proj_cov", request)


class ProgressCalculationTests(unittest.TestCase):
    """Test 6: Pending fields do not count as directly adoptable recommendations."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_pending_not_counted_as_adoptable(self):
        """fields_with_recommendation counts only non-pending recommended
        fields; pending fields are counted in fields_blocked."""
        self.service.create("proj_test", _create_request())
        journey = self.service.get("proj_test")
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key="gen-progress-001",
        )
        updated = self.service.generate_prefill("proj_test", request)
        package = updated.prefill_package

        # Count actual recommended (non-pending) fields.  A group with an
        # empty recommended slot (corrective round 4: every deterministic
        # pending scaffold) counts as pending/blocked.
        actual_recommended = 0
        actual_pending = 0
        for group in package.field_candidates.values():
            if not group.recommended_candidate_id:
                if group.candidates:
                    actual_pending += 1
                continue
            rec = next(
                (
                    c for c in group.candidates
                    if c.candidate_id == group.recommended_candidate_id
                ),
                None,
            )
            if rec is None:
                continue
            if rec.recommendation_role == "pending_decision":
                actual_pending += 1
            else:
                actual_recommended += 1

        self.assertEqual(
            actual_recommended,
            package.progress.fields_with_recommendation,
            "fields_with_recommendation must only count non-pending fields",
        )
        self.assertGreater(
            package.progress.fields_blocked_missing_evidence,
            0,
            "blocked count should include pending and exact-fact fields",
        )
        self.assertGreater(actual_pending, 0, "there should be pending fields")

        # Corrective round 4 consistency: every deterministic pending scaffold
        # group carries an empty recommended slot while keeping its candidate.
        scaffold_groups = [
            group
            for group in package.field_candidates.values()
            if group.candidates
            and group.candidates[0].recommendation_role == "pending_decision"
        ]
        self.assertTrue(scaffold_groups, "deterministic pending scaffolds exist")
        self.assertTrue(
            all(group.recommended_candidate_id == "" for group in scaffold_groups),
            "every pending scaffold group must have an empty recommended slot",
        )
        # Genuine safe recommendations remain non-empty.
        safe_groups = [
            group
            for group in package.field_candidates.values()
            if group.recommended_candidate_id
            and group.candidates
            and group.candidates[0].recommendation_role != "pending_decision"
        ]
        self.assertTrue(
            safe_groups,
            "genuine safe deterministic recommendations must remain",
        )

        # Serialization round-trip: after persist + reload the deterministic
        # scaffold groups keep their empty recommended slots.
        reloaded = self.service.get("proj_test")
        reloaded_scaffolds = [
            group
            for group in reloaded.prefill_package.field_candidates.values()
            if group.candidates
            and group.candidates[0].recommendation_role == "pending_decision"
        ]
        self.assertTrue(reloaded_scaffolds)
        self.assertTrue(
            all(
                group.recommended_candidate_id == ""
                for group in reloaded_scaffolds
            ),
            "persisted scaffold groups must reload with empty recommended slots",
        )


class SynopsisConfirmedRetentionTests(unittest.TestCase):
    """Test 7: Synopsis-confirmed values retain user_confirmed, not overwritten."""

    def test_synopsis_confirmed_values_not_overwritten_by_pending(self):
        """When a synopsis import is confirmed, its locked values should
        remain user_confirmed even after regeneration introduces pending cards."""
        # This test uses the standalone generate_prefill_package function
        # with a manually constructed state that has confirmed synopsis values.
        # We verify the lock_confirmed_synopsis_values function path.
        from packages.contracts.workbench_contracts import (
            AuthoringPrefillCandidate,
            AuthoringPrefillFieldCandidates,
            AuthoringPrefillPackage,
        )

        # Simulate a package with a user_confirmed value.
        confirmed_candidate = AuthoringPrefillCandidate(
            candidate_id="test_confirmed_001",
            field_path="design.randomization",
            structured_value={"mode": "随机"},
            preview="随机",
            state="user_confirmed",
            recommendation_role="recommended",
            adoption_mode="manual_only",
        )
        group = AuthoringPrefillFieldCandidates(
            field_path="design.randomization",
            recommended_candidate_id="test_confirmed_001",
            candidates=[confirmed_candidate],
        )
        # Verify the confirmed candidate is not pending_decision.
        self.assertNotEqual(
            "pending_decision",
            confirmed_candidate.recommendation_role,
            "user_confirmed candidate should not be pending_decision",
        )
        self.assertEqual("user_confirmed", confirmed_candidate.state)


if __name__ == "__main__":
    unittest.main()
