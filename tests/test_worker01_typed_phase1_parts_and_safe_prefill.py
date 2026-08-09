"""Worker 01 focused tests: typed Phase I Parts + safe AI-first prefill.

These tests verify:
1. Legacy ``List[str]`` phase1_parts migrate to typed ``MedicalWritingPhase1Part``
   objects with unresolved fields.
2. Typed Part round-trip preserves population/cohort/dose/PK-PD/safety/stopping/
   SoA/transition dependencies.
3. Deterministic prefill with AI absent/failing produces NO adoptable clinical
   design conclusion (Parts, randomization, blinding, comparator, interim).
4. Plan hash/modules remain consistent with typed selection.
5. The plan consumption helper fails closed on missing/unconfirmed plans.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
import unittest

from packages.contracts.workbench_contracts import (
    AuthoringPrefillGenerateRequest,
    AuthoringPrefillPackage,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingInterimAnalysisDesign,
    MedicalWritingInterventionIpRegimen,
    MedicalWritingInterventionRules,
    MedicalWritingInterventionNonIpTreatmentRule,
    MedicalWritingPhase1Part,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyDefinition,
    MedicalWritingStudyFraming,
    MedicalWritingStructuredStudyDesign,
    InterventionRulesAuthority,
    InterventionRulesIpAdjustmentPolicy,
    InterventionRulesNonIpRuleClass,
    InterventionRulesProductRole,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_authoring_prefill import (
    EXACT_FACT_PATHS,
    generate_prefill_package,
    map_design_adoption_to_study_updates,
    PassthroughPrefillAdapter,
)
from services.api.app.medical_writing_plan_consumption import (
    MedicalWritingPlanConsumptionHelper,
    PlanProjectionMissingError,
    PlanUnconfirmedError,
)
from services.api.app.medical_writing_protocol_assembly_plan import (
    MedicalWritingProtocolAssemblyPlanService,
    build_protocol_assembly_plan,
)


NOW = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)


def _phase1_create_request(**overrides) -> MedicalWritingAuthoringJourneyCreateRequest:
    """Build a create request for a Phase I study."""
    framing_fields = {
        "investigational_product": "CMS-D017",
        "indication": "类风湿关节炎",
        "study_phase": "I期",
    }
    request_fields = {
        "actor": "medical_manager_test",
        "idempotency_key": "create-phase1-w01",
    }
    for key, value in overrides.items():
        if key in framing_fields:
            framing_fields[key] = value
        else:
            request_fields[key] = value
    request_fields["framing"] = MedicalWritingStudyFraming(**framing_fields)
    return MedicalWritingAuthoringJourneyCreateRequest(**request_fields)


def _phase3_create_request(**overrides) -> MedicalWritingAuthoringJourneyCreateRequest:
    """Build a create request for a Phase III study."""
    framing_fields = {
        "investigational_product": "CMS-D017",
        "indication": "类风湿关节炎",
        "study_phase": "III期",
    }
    request_fields = {
        "actor": "medical_manager_test",
        "idempotency_key": "create-phase3-w01",
    }
    for key, value in overrides.items():
        if key in framing_fields:
            framing_fields[key] = value
        else:
            request_fields[key] = value
    request_fields["framing"] = MedicalWritingStudyFraming(**framing_fields)
    return MedicalWritingAuthoringJourneyCreateRequest(**request_fields)


def _build_definition(
    *,
    project_id: str = "proj_plan_test",
    study_phase: str = "I期",
    phase1_parts=None,
    comparator_type: str = "none_or_dose_escalation",
) -> MedicalWritingStudyDefinition:
    """Build a minimal StudyDefinition for plan service tests."""
    if phase1_parts is None:
        phase1_parts = ["SAD", "MAD", "first-in-patient"]
    design = MedicalWritingStructuredStudyDesign(
        randomization_mode="non_randomized",
        blinding_mode="open_label",
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
        structured_design=design,
    )
    regimens = [
        MedicalWritingInterventionIpRegimen(
            regimen_id="ip-1",
            product_name="TEST-IP",
            product_role=InterventionRulesProductRole.INVESTIGATIONAL_PRODUCT,
            dose_and_frequency="test dose",
            route="oral",
            treatment_period="12 weeks",
        )
    ]
    rules = MedicalWritingInterventionRules(
        authority=InterventionRulesAuthority.STRUCTURED,
        ip_regimens=regimens,
        ip_adjustment_policy=InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT,
        no_planned_adjustment_statement="No planned IP dose adjustment.",
    )
    picos = MedicalWritingPicosDefinition(
        primary_endpoint="Test endpoint",
        intervention_rules=rules,
    )
    return MedicalWritingStudyDefinition(
        definition_id=f"def-{project_id}",
        project_id=project_id,
        revision=1,
        origin="guided_greenfield",
        framing=framing,
        picos=picos,
        state_sha256="a" * 64,
        created_at=NOW,
        updated_at=NOW,
        updated_by="test",
    )


# ---------------------------------------------------------------------------
# 1. Legacy string list migrates to typed Parts
# ---------------------------------------------------------------------------


class TestLegacyStringMigration(unittest.TestCase):
    """Legacy ``List[str]`` phase1_parts must load into typed objects."""

    def test_legacy_string_list_migrates_to_typed_parts(self):
        """``["SAD", "MAD"]`` loads as ``[Phase1Part(part_code="SAD"), ...]``."""
        design = MedicalWritingStructuredStudyDesign(
            phase1_parts=["SAD", "MAD", "first-in-patient"]
        )
        self.assertEqual(len(design.phase1_parts), 3)
        for part in design.phase1_parts:
            self.assertIsInstance(part, MedicalWritingPhase1Part)
        codes = [p.part_code for p in design.phase1_parts]
        self.assertEqual(codes, ["SAD", "MAD", "first-in-patient"])

    def test_legacy_parts_have_unresolved_fields(self):
        """Migrated Parts have empty clinical detail and ``unresolved=True``."""
        design = MedicalWritingStructuredStudyDesign(
            phase1_parts=["SAD"]
        )
        part = design.phase1_parts[0]
        self.assertTrue(part.unresolved)
        self.assertEqual(part.population, "")
        self.assertEqual(part.cohort_dose, "")
        self.assertEqual(part.pk_pd, "")
        self.assertEqual(part.safety, "")
        self.assertEqual(part.stopping_rules, "")
        self.assertEqual(part.soa_summary, "")
        self.assertEqual(part.transition_dependencies, "")

    def test_dict_input_also_migrates(self):
        """Dict input ``{"part_code": "SAD"}`` loads as typed Part."""
        design = MedicalWritingStructuredStudyDesign(
            phase1_parts=[{"part_code": "SAD"}, {"part_code": "MAD"}]
        )
        self.assertEqual(len(design.phase1_parts), 2)
        self.assertEqual(design.phase1_parts[0].part_code, "SAD")
        self.assertEqual(design.phase1_parts[1].part_code, "MAD")

    def test_typed_part_round_trip(self):
        """Fully typed Part with clinical detail survives round-trip."""
        part = MedicalWritingPhase1Part(
            part_code="SAD",
            part_label="单次递增剂量",
            population="健康受试者",
            cohort_dose="1mg → 2mg → 4mg cohort",
            pk_pd="PK采样：给药前至72h",
            safety="DLT观察期7天",
            stopping_rules="≥2例DLT停止递增",
            soa_summary="筛选/给药/DLT观察/PK采样",
            transition_dependencies="SAD完成后进入MAD",
        )
        design = MedicalWritingStructuredStudyDesign(
            phase1_parts=[part]
        )
        result = design.phase1_parts[0]
        self.assertEqual(result.part_code, "SAD")
        self.assertEqual(result.population, "健康受试者")
        self.assertEqual(result.cohort_dose, "1mg → 2mg → 4mg cohort")
        self.assertFalse(result.unresolved)

    def test_dedup_by_part_code(self):
        """Duplicate part_codes are deduplicated."""
        design = MedicalWritingStructuredStudyDesign(
            phase1_parts=["SAD", "SAD", "MAD"]
        )
        self.assertEqual(len(design.phase1_parts), 2)
        self.assertEqual(design.phase1_parts[0].part_code, "SAD")
        self.assertEqual(design.phase1_parts[1].part_code, "MAD")

    def test_json_round_trip_preserves_typed_parts(self):
        """model_dump → model_validate preserves typed Parts."""
        design = MedicalWritingStructuredStudyDesign(
            phase1_parts=["SAD", "MAD"]
        )
        dumped = design.model_dump(mode="json")
        restored = MedicalWritingStructuredStudyDesign.model_validate(dumped)
        self.assertEqual(len(restored.phase1_parts), 2)
        for part in restored.phase1_parts:
            self.assertIsInstance(part, MedicalWritingPhase1Part)
        self.assertEqual(restored.phase1_parts[0].part_code, "SAD")


# ---------------------------------------------------------------------------
# 2. Safe deterministic prefill (AI absent)
# ---------------------------------------------------------------------------


class TestSafeDeterministicPrefill(unittest.TestCase):
    """With AI absent/failing, deterministic prefill must not produce
    adoptable clinical design conclusions."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _generate(self, project_id: str = "proj_p1") -> AuthoringPrefillPackage:
        """Create a Phase I journey and generate prefill with no AI adapter."""
        self.service.create(project_id, _phase1_create_request())
        journey = self.service.get(project_id)
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="test",
            idempotency_key=f"prefill-{project_id}",
        )
        updated = self.service.generate_prefill(project_id, request)
        return updated.prefill_package

    def _generate_phase3(self, project_id: str = "proj_p3") -> AuthoringPrefillPackage:
        """Create a Phase III journey and generate prefill with no AI adapter."""
        self.service.create(project_id, _phase3_create_request())
        journey = self.service.get(project_id)
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="test",
            idempotency_key=f"prefill-{project_id}",
        )
        updated = self.service.generate_prefill(project_id, request)
        return updated.prefill_package

    def test_phase1_parts_candidate_is_scaffold_not_conclusion(self):
        """Phase I Parts starts as a no-evidence pending decision, not a fact."""
        package = self._generate()
        self.assertIn("design.phase1_parts", package.field_candidates)
        group = package.field_candidates["design.phase1_parts"]
        self.assertGreater(len(group.candidates), 0)
        primary = group.candidates[0]
        self.assertEqual(
            primary.confidence,
            "none",
            "Phase I Parts pending card must carry no evidence confidence",
        )
        self.assertEqual(primary.recommendation_role, "pending_decision")
        self.assertEqual(primary.adoption_mode, "manual_only")
        self.assertTrue(
            any("不构成可采用的临床设计结论" in lim for lim in primary.limitations),
            "Primary Parts candidate must state it is not an adoptable conclusion",
        )
        # Structured value must use dict-based Parts, not bare strings.
        value = primary.structured_value
        self.assertIsInstance(value, dict)
        parts = value.get("parts", [])
        self.assertTrue(
            all(isinstance(p, dict) and "part_code" in p for p in parts),
            "Parts must be dict-based with part_code, not bare strings",
        )

    def test_interim_analysis_candidate_is_scaffold(self):
        """Interim analysis starts pending and cannot become a fact implicitly."""
        package = self._generate_phase3()
        self.assertIn("design.interim_analysis", package.field_candidates)
        group = package.field_candidates["design.interim_analysis"]
        primary = group.candidates[0]
        self.assertEqual(primary.confidence, "none")
        self.assertEqual(primary.recommendation_role, "pending_decision")
        self.assertEqual(primary.adoption_mode, "manual_only")
        self.assertTrue(
            any("不构成可采用的临床设计结论" in lim or "须由医学经理确认" in lim
                for lim in primary.limitations),
            "Interim candidate must state it requires medical manager confirmation",
        )

    def test_no_ai_adapter_does_not_invent_clinical_facts(self):
        """Without AI, exact fact fields must not have adoptable candidates."""
        package = self._generate()
        for exact_path in EXACT_FACT_PATHS:
            self.assertNotIn(
                exact_path,
                package.field_candidates,
                f"Exact fact path {exact_path} must not have deterministic candidates",
            )

    def test_all_design_fields_are_scaffold_not_conclusion(self):
        """All no-AI design primaries remain pending decisions with no confidence."""
        package = self._generate()
        design_paths = [
            "design.randomization",
            "design.blinding",
            "design.comparator_type",
            "design.assignment_model",
            "design.center_model",
            "design.adaptive_design",
            "design.interim_analysis",
            "design.phase1_parts",
            "design.arms_or_cohorts",
            "picos.design_archetype",
        ]
        for path in design_paths:
            if path not in package.field_candidates:
                continue
            group = package.field_candidates[path]
            primary = group.candidates[0]
            self.assertEqual(
                primary.confidence,
                "none",
                f"{path} primary candidate must carry no evidence confidence",
            )
            self.assertEqual(
                primary.recommendation_role,
                "pending_decision",
                f"{path} primary candidate must remain pending",
            )
            self.assertEqual(
                primary.adoption_mode,
                "manual_only",
                f"{path} primary candidate must require manual handling",
            )
            has_non_adoptable = any(
                "不构成可采用" in lim or "须由医学经理确认" in lim
                for lim in primary.limitations
            )
            self.assertTrue(
                has_non_adoptable,
                f"{path} primary candidate must have explicit non-adoptable limitation",
            )

    def test_phase1_parts_adopt_writes_part_codes_not_clinical_detail(self):
        """Selecting a multi-Part option writes only part codes, not invented detail."""
        package = self._generate()
        group = package.field_candidates["design.phase1_parts"]
        selected = next(
            candidate
            for candidate in group.candidates
            if isinstance(candidate.structured_value, dict)
            and {
                part.get("part_code")
                for part in candidate.structured_value.get("parts", [])
                if isinstance(part, dict)
            }
            == {"SAD", "MAD"}
        )
        framing_payload = self.service.get("proj_p1").framing.model_dump(mode="json")
        picos_payload = self.service.get("proj_p1").picos.model_dump(mode="json")
        framing_updates, picos_updates, changed = map_design_adoption_to_study_updates(
            "design.phase1_parts",
            selected.structured_value,
            framing_payload=framing_payload,
            picos_payload=picos_payload,
        )
        # The adopt must write part_codes (strings) into structured_design.
        sd = framing_updates.get("structured_design", {})
        parts = sd.get("phase1_parts", [])
        self.assertTrue(parts, "Adopt must produce phase1_parts entries")
        # After adopt, parts should be string codes (the model validator will
        # migrate them to typed objects on validation).
        self.assertTrue(
            all(isinstance(p, str) for p in parts),
            "Adopt must write string part_codes, not clinical detail dicts",
        )


# ---------------------------------------------------------------------------
# 3. Plan service reads typed Parts correctly
# ---------------------------------------------------------------------------


class TestPlanServiceTypedParts(unittest.TestCase):
    """Plan service _resolve_phase1_parts must read typed Part codes."""

    def test_plan_builds_with_legacy_string_parts(self):
        """Plan builds correctly when phase1_parts are legacy strings."""
        definition = _build_definition()
        plan = build_protocol_assembly_plan(
            definition,
            plan_id="plan-test-1",
            revision=1,
            actor="test",
            now=NOW,
        )
        # SAD, MAD, first_in_patient modules should be conditional_applicable.
        sad_module = next(
            m for m in plan.modules if m.module_id == "design.phase1.sad"
        )
        self.assertEqual(sad_module.applicability, "conditional_applicable")
        mad_module = next(
            m for m in plan.modules if m.module_id == "design.phase1.mad"
        )
        self.assertEqual(mad_module.applicability, "conditional_applicable")
        fip_module = next(
            m for m in plan.modules if m.module_id == "design.phase1.first_in_patient"
        )
        self.assertEqual(fip_module.applicability, "conditional_applicable")

    def test_plan_hash_consistent_with_typed_selection(self):
        """Plan module applicability is identical for legacy strings vs typed
        Parts that resolve to the same codes."""
        def _build(parts):
            return _build_definition(phase1_parts=parts)

        plan_legacy = build_protocol_assembly_plan(
            _build(["SAD", "MAD"]),
            plan_id="plan-hash-legacy",
            revision=1,
            actor="test",
            now=NOW,
        )
        plan_typed = build_protocol_assembly_plan(
            _build([
                MedicalWritingPhase1Part(part_code="SAD"),
                MedicalWritingPhase1Part(part_code="MAD"),
            ]),
            plan_id="plan-hash-typed",
            revision=1,
            actor="test",
            now=NOW,
        )
        legacy_modules = {m.module_id: m.applicability for m in plan_legacy.modules}
        typed_modules = {m.module_id: m.applicability for m in plan_typed.modules}
        self.assertEqual(legacy_modules, typed_modules)


# ---------------------------------------------------------------------------
# 4. Plan consumption helper fails closed
# ---------------------------------------------------------------------------


class TestPlanConsumptionHelper(unittest.TestCase):
    """The consumption helper must fail closed on missing/unconfirmed plans."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        def _missing_definition(project_id: str):
            raise KeyError(f"StudyDefinition not found: {project_id}")

        self.plan_service = MedicalWritingProtocolAssemblyPlanService(
            Path(self.tmpdir.name) / "plan.sqlite3",
            _missing_definition,
        )
        self.helper = MedicalWritingPlanConsumptionHelper(self.plan_service)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_plan_raises_unconfirmed(self):
        """A project with no plan raises PlanUnconfirmedError."""
        with self.assertRaises(PlanUnconfirmedError):
            self.helper.require_confirmed_projection(
                project_id="nonexistent",
                projection_kind="synopsis",
            )

    def test_unknown_projection_raises(self):
        """An unknown projection kind raises PlanProjectionMissingError."""
        with self.assertRaises(PlanProjectionMissingError):
            self.helper.require_confirmed_projection(
                project_id="nonexistent",
                projection_kind="unknown_projection",
            )


if __name__ == "__main__":
    unittest.main()
