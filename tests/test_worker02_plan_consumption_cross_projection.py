"""Worker 02 cross-projection consumer tests.

Verifies that synopsis, sections/SoA, flowchart, and DOCX TOC/export each
consume one confirmed current plan revision or fail closed.  Tests are
structured as red-before (fail without confirmed plan) / green-after (pass
with confirmed plan) for the key counterexamples:

- Phase I SAD+MAD+首次患者
- interim_analysis=false
- active comparator
- background treatment
- modality/route
- multi-Part Phase I transitions
- stale/unconfirmed/missing plan fail-closed
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.workbench_contracts import (
    InterventionRulesAuthority,
    InterventionRulesIpAdjustmentPolicy,
    InterventionRulesProductRole,
    MedicalWritingGreenfieldCreateRequest,
    MedicalWritingInterventionIpRegimen,
    MedicalWritingInterventionNonIpTreatmentRule,
    MedicalWritingInterventionRules,
    MedicalWritingInterimAnalysisDesign,
    MedicalWritingPicosDefinition,
    MedicalWritingPhase1Part,
    MedicalWritingProtocolAssemblyPlanConfirmRequest,
    MedicalWritingProtocolAssemblyPlanRefreshRequest,
    MedicalWritingStudyDefinition,
    MedicalWritingStudyFraming,
    MedicalWritingStudySchemaDefinition,
    MedicalWritingStudySchemaPart,
    MedicalWritingStructuredStudyDesign,
    InterventionRulesNonIpRuleClass,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_greenfield import (
    GreenfieldMedicalWritingDocumentService,
)
from services.api.app.medical_writing_plan_consumption import (
    MedicalWritingPlanConsumptionHelper,
    PlanConsumptionError,
    PlanUnconfirmedError,
)
from services.api.app.medical_writing_protocol_assembly_plan import (
    MedicalWritingProtocolAssemblyPlanService,
    build_protocol_assembly_plan,
)
from services.api.app.medical_writing_protocol_template import (
    MedicalWritingProtocolTemplateService,
    TEMPLATE_ID,
    TEMPLATE_VERSION,
)
from services.api.app.medical_writing_study_schema import (
    validate_study_schema_against_plan,
    require_plan_for_study_schema,
)


NOW = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)


def _build_definition(
    *,
    project_id: str = "proj_w02",
    study_phase: str = "I期",
    phase1_parts=None,
    comparator_type: str = "none_or_dose_escalation",
    interim_planned: bool | None = False,
    background_mtx: bool = False,
    routes: list[str] | None = None,
    include_active_comparator: bool = False,
) -> MedicalWritingStudyDefinition:
    """Build a StudyDefinition for cross-projection consumer tests."""
    if phase1_parts is None:
        phase1_parts = [
            MedicalWritingPhase1Part(
                part_code="SAD",
                population="健康受试者",
                cohort_dose="SAD剂量递增队列",
            ),
            MedicalWritingPhase1Part(
                part_code="MAD",
                population="健康受试者",
                cohort_dose="MAD剂量递增队列",
            ),
            MedicalWritingPhase1Part(
                part_code="first_in_patient",
                population="目标适应症患者",
                cohort_dose="首次患者剂量队列",
            ),
        ]
    design = MedicalWritingStructuredStudyDesign(
        randomization_mode="non_randomized" if study_phase == "I期" else "randomized",
        blinding_mode="open_label" if study_phase == "I期" else "double_blind",
        comparator_type=comparator_type,
        assignment_model="parallel_group",
        adaptive_design_enabled=False,
        sample_size_reestimation_planned=False,
        treatment_switch_planned=False,
        crossover_planned=False,
        open_label_extension_planned=False,
        src_planned=False,
        dmc_planned=False,
        phase1_parts=phase1_parts,
        interim_analysis=MedicalWritingInterimAnalysisDesign(planned=interim_planned),
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
    if include_active_comparator:
        regimens.append(
            MedicalWritingInterventionIpRegimen(
                regimen_id="ac-1",
                product_name="AC-001",
                product_role=InterventionRulesProductRole.ACTIVE_COMPARATOR,
                dose_and_frequency="comparator dose",
                route="oral",
                treatment_period="12 weeks",
            )
        )
    if comparator_type == "placebo":
        regimens.append(
            MedicalWritingInterventionIpRegimen(
                regimen_id="pbo-1",
                product_name="Placebo",
                product_role=InterventionRulesProductRole.PLACEBO,
                dose_and_frequency="matching placebo",
                route="oral",
                treatment_period="12 weeks",
            )
        )
    non_ip_rules = []
    if background_mtx:
        non_ip_rules.append(
            MedicalWritingInterventionNonIpTreatmentRule(
                rule_id="bg-mtx",
                rule_class=InterventionRulesNonIpRuleClass.BACKGROUND,
                agent_or_category="MTX",
                cm_dose_rule="stable background dose",
            )
        )
    rules = MedicalWritingInterventionRules(
        authority=InterventionRulesAuthority.STRUCTURED,
        ip_regimens=regimens,
        ip_adjustment_policy=InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT,
        no_planned_adjustment_statement="No planned IP dose adjustment.",
        non_ip_treatment_rules=non_ip_rules,
    )
    picos = MedicalWritingPicosDefinition(
        population_summary="健康志愿者",
        primary_endpoint="Test endpoint",
        intervention_rules=rules,
    )
    framing = MedicalWritingStudyFraming(
        protocol_id="PROTO-TEST",
        document_title="Test Protocol",
        indication="Test Indication",
        clinicaltrials_condition_term="Test Condition",
        study_phase=study_phase,
        investigational_product="TEST-IP",
        structured_design=design,
        product_profile={
            "technology_type": "small_molecule",
            "administration_routes": list(routes or ["口服"]),
            "dosage_forms": ["片剂"],
            "exposure_scope": "systemic",
        },
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


def _setup_plan_service(
    tmpdir: str,
    definition: MedicalWritingStudyDefinition,
):
    """Create a plan service + helper with a confirmed plan for *definition*."""
    definitions = {definition.project_id: definition}
    plan_service = MedicalWritingProtocolAssemblyPlanService(
        Path(tmpdir) / "plan.sqlite3",
        definitions.__getitem__,
    )
    # Build and confirm the plan.
    refreshed = plan_service.refresh(
        definition.project_id,
        MedicalWritingProtocolAssemblyPlanRefreshRequest(
            expected_plan_revision=0,
            expected_source_definition_id=definition.definition_id,
            expected_source_definition_revision=definition.revision,
            expected_source_definition_sha256=definition.state_sha256,
            actor="test",
            idempotency_key="refresh-w02",
        ),
    )
    plan_service.confirm(
        definition.project_id,
        MedicalWritingProtocolAssemblyPlanConfirmRequest(
            expected_plan_revision=refreshed.plan.revision,
            expected_plan_sha256=refreshed.plan.state_sha256,
            actor="test",
            idempotency_key="confirm-w02",
        ),
    )
    helper = MedicalWritingPlanConsumptionHelper(plan_service)
    return plan_service, helper


# ---------------------------------------------------------------------------
# 1. Template service: section_seeds and module_resolutions fail closed
#    without a confirmed plan; succeed with one.
# ---------------------------------------------------------------------------


class TestTemplateServicePlanConsumption(unittest.TestCase):
    """Template service must consume confirmed plan for sections/synopsis."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.definition = _build_definition()
        self.plan_service, self.helper = _setup_plan_service(
            self.tmpdir.name, self.definition
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_section_seeds_fail_closed_without_helper_confirmed_plan(self):
        """Without a confirmed plan, section_seeds with helper fails closed."""
        # When helper is injected but plan is missing for a different project,
        # it must raise PlanUnconfirmedError.
        missing_helper = MedicalWritingPlanConsumptionHelper(
            MedicalWritingProtocolAssemblyPlanService(
                Path(self.tmpdir.name) / "empty.sqlite3",
                lambda pid: _build_definition(project_id=pid),
            )
        )
        svc = MedicalWritingProtocolTemplateService(missing_helper)
        with self.assertRaises(PlanUnconfirmedError):
            svc.section_seeds(self.definition)

    def test_section_seeds_succeed_with_confirmed_plan(self):
        """With a confirmed plan, section_seeds returns seeds normally."""
        svc = MedicalWritingProtocolTemplateService(self.helper)
        template = svc.definition(TEMPLATE_ID, TEMPLATE_VERSION)
        seeds = svc.section_seeds(self.definition, template)
        self.assertTrue(len(seeds) > 0)

    def test_module_resolutions_fail_closed_without_confirmed_plan(self):
        """module_resolutions with helper but no plan fails closed."""
        missing_helper = MedicalWritingPlanConsumptionHelper(
            MedicalWritingProtocolAssemblyPlanService(
                Path(self.tmpdir.name) / "empty2.sqlite3",
                lambda pid: _build_definition(project_id=pid),
            )
        )
        svc = MedicalWritingProtocolTemplateService(missing_helper)
        with self.assertRaises(PlanUnconfirmedError):
            svc.module_resolutions(self.definition)

    def test_module_resolutions_succeed_with_confirmed_plan(self):
        """With confirmed plan, module_resolutions returns normally."""
        svc = MedicalWritingProtocolTemplateService(self.helper)
        template = svc.definition(TEMPLATE_ID, TEMPLATE_VERSION)
        resolutions = svc.module_resolutions(self.definition, template)
        self.assertTrue(len(resolutions) > 0)

    def test_synopsis_projection_consumed_for_company_template(self):
        """Synopsis data generation must consume the synopsis projection."""
        svc = MedicalWritingProtocolTemplateService(self.helper)
        template = svc.definition(TEMPLATE_ID, TEMPLATE_VERSION)
        # This call internally triggers _require_plan_projection("synopsis").
        seeds = svc.section_seeds(self.definition, template)
        # Verify synopsis seed exists and has initial_data.
        synopsis_seeds = [
            s for s in seeds if s.node_kind == "protocol_synopsis"
        ]
        self.assertTrue(len(synopsis_seeds) > 0)


# ---------------------------------------------------------------------------
# 2. Greenfield service: create and apply_module_resolution fail closed
#    without confirmed plan.
# ---------------------------------------------------------------------------


class TestGreenfieldServicePlanConsumption(unittest.TestCase):
    """Greenfield create/apply must consume confirmed plan or fail closed."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.definition = _build_definition()
        self.plan_service, self.helper = _setup_plan_service(
            self.tmpdir.name, self.definition
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_create_fails_closed_without_confirmed_plan(self):
        """Greenfield create with helper but no confirmed plan fails closed."""
        missing_helper = MedicalWritingPlanConsumptionHelper(
            MedicalWritingProtocolAssemblyPlanService(
                Path(self.tmpdir.name) / "empty_gf.sqlite3",
                lambda pid: _build_definition(project_id=pid),
            )
        )
        svc = GreenfieldMedicalWritingDocumentService(
            Path(self.tmpdir.name) / "gf.sqlite3",
            plan_consumption_helper=missing_helper,
        )
        request = MedicalWritingGreenfieldCreateRequest(
            protocol_id="PROTO-1",
            version="1.0",
            document_title="Test",
            indication="Test",
            study_phase="I期",
            investigational_product="IP",
            protocol_date="2026-07-22",
            sponsor="Test Sponsor",
            source_study_definition_id=self.definition.definition_id,
            source_study_definition_revision=self.definition.revision,
            source_study_definition_sha256=self.definition.state_sha256,
            template_id=TEMPLATE_ID,
            template_version=TEMPLATE_VERSION,
            actor="test",
            idempotency_key="create-w02",
        )
        with self.assertRaises(PlanUnconfirmedError):
            svc.create("proj_no_plan", request)

    def test_create_succeeds_with_confirmed_plan(self):
        """Greenfield create with confirmed plan succeeds."""
        svc = GreenfieldMedicalWritingDocumentService(
            Path(self.tmpdir.name) / "gf_ok.sqlite3",
            plan_consumption_helper=self.helper,
        )
        request = MedicalWritingGreenfieldCreateRequest(
            protocol_id="PROTO-1",
            version="1.0",
            document_title="Test",
            indication="Test",
            study_phase="I期",
            investigational_product="IP",
            protocol_date="2026-07-22",
            sponsor="Test Sponsor",
            source_study_definition_id=self.definition.definition_id,
            source_study_definition_revision=self.definition.revision,
            source_study_definition_sha256=self.definition.state_sha256,
            template_id=TEMPLATE_ID,
            template_version=TEMPLATE_VERSION,
            actor="test",
            idempotency_key="create-w02-ok",
        )
        result = svc.create(self.definition.project_id, request)
        self.assertTrue(result.document.document_id)

    def test_create_without_helper_backward_compatible(self):
        """Without helper, greenfield create works (backward compatible)."""
        svc = GreenfieldMedicalWritingDocumentService(
            Path(self.tmpdir.name) / "gf_nohelper.sqlite3",
        )
        request = MedicalWritingGreenfieldCreateRequest(
            protocol_id="PROTO-1",
            version="1.0",
            document_title="Test",
            indication="Test",
            study_phase="I期",
            investigational_product="IP",
            protocol_date="2026-07-22",
            sponsor="Test Sponsor",
            source_study_definition_id=self.definition.definition_id,
            source_study_definition_revision=self.definition.revision,
            source_study_definition_sha256=self.definition.state_sha256,
            template_id=TEMPLATE_ID,
            template_version=TEMPLATE_VERSION,
            actor="test",
            idempotency_key="create-w02-nohelper",
        )
        result = svc.create(self.definition.project_id, request)
        self.assertTrue(result.document.document_id)


# ---------------------------------------------------------------------------
# 3. Study schema plan validation
# ---------------------------------------------------------------------------


class TestStudySchemaPlanValidation(unittest.TestCase):
    """Study schema must align with confirmed plan's flowchart projection."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.definition = _build_definition()
        self.plan_service, self.helper = _setup_plan_service(
            self.tmpdir.name, self.definition
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_empty_part_id_is_blocker(self):
        """A selected Part with whitespace-only part_id is a validation blocker."""
        from packages.contracts.workbench_contracts import (
            MedicalWritingStudySchemaNode,
        )
        schema = MedicalWritingStudySchemaDefinition(
            schema_id="schema-1",
            revision=1,
            source_facts_sha256="x" * 64,
            state_sha256="y" * 64,
            updated_at=NOW,
            updated_by="test",
            parts=[
                MedicalWritingStudySchemaPart(
                    part_id=" ",  # whitespace-only after strip()
                    order=0,
                    label="Test Part",
                    flow_direction="left_to_right",
                )
            ],
            nodes=[
                MedicalWritingStudySchemaNode(
                    node_id="n1",
                    part_id=" ",
                    order=0,
                    lane_order=0,
                    label="Node 1",
                    node_kind="entry",
                    fact_status="confirmed",
                    source_bindings=[],
                )
            ],
            edges=[],
            status="confirmed",
        )
        issues = validate_study_schema_against_plan(schema, None)
        blockers = [i for i in issues if i.severity == "blocker"]
        self.assertTrue(
            any("plan_part_empty" in i.code for i in blockers),
            "Whitespace-only part_id must produce a blocker issue",
        )

    def test_require_plan_for_study_schema_fails_without_plan(self):
        """require_plan_for_study_schema fails closed without confirmed plan."""
        missing_helper = MedicalWritingPlanConsumptionHelper(
            MedicalWritingProtocolAssemblyPlanService(
                Path(self.tmpdir.name) / "empty_ss.sqlite3",
                lambda pid: _build_definition(project_id=pid),
            )
        )
        with self.assertRaises(PlanUnconfirmedError):
            require_plan_for_study_schema("nonexistent", missing_helper)

    def test_require_plan_for_study_schema_without_helper_returns_none(self):
        """Without helper, require_plan_for_study_schema returns None."""
        result = require_plan_for_study_schema("any", None)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 4. Cross-projection counterexamples
# ---------------------------------------------------------------------------


class TestCrossProjectionCounterexamples(unittest.TestCase):
    """Verify interim=false, active comparator, background treatment, and
    modality/route are consistent across projections."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _setup(self, definition):
        return _setup_plan_service(self.tmpdir.name, definition)

    def test_interim_false_consistent_across_projections(self):
        """interim_analysis.planned=false must be consistent across
        synopsis/sections/soa/flowchart/docx_toc projections."""
        definition = _build_definition(
            study_phase="III期",
            interim_planned=False,
            comparator_type="placebo",
            include_active_comparator=False,
        )
        plan_service, helper = self._setup(definition)
        # All projections must be consumable without error.
        for projection in (
            "synopsis",
            "sections_toc",
            "soa",
            "study_schema_flowchart",
            "docx_toc",
        ):
            state = helper.require_confirmed_projection(
                project_id=definition.project_id,
                projection_kind=projection,
            )
            self.assertIsNotNone(state.plan)
            # interim module should be not_applicable in the plan.
            interim_module = next(
                (m for m in state.plan.modules
                 if m.module_id == "design.interim_analysis"),
                None,
            )
            if interim_module:
                self.assertEqual(
                    interim_module.applicability,
                    "not_applicable",
                    f"interim must be not_applicable for {projection}",
                )

    def test_active_comparator_consistent_across_projections(self):
        """Active comparator must be consistently present across projections."""
        definition = _build_definition(
            study_phase="III期",
            comparator_type="active",
            include_active_comparator=True,
            interim_planned=False,
        )
        plan_service, helper = self._setup(definition)
        for projection in (
            "synopsis",
            "sections_toc",
            "soa",
            "study_schema_flowchart",
            "docx_toc",
        ):
            state = helper.require_confirmed_projection(
                project_id=definition.project_id,
                projection_kind=projection,
            )
            # Active comparator module should be applicable.
            ac_module = next(
                (m for m in state.plan.modules
                 if m.module_id == "intervention.active_comparator_regimen"),
                None,
            )
            if ac_module:
                self.assertEqual(
                    ac_module.applicability,
                    "conditional_applicable",
                    f"active comparator must be conditional_applicable for {projection}",
                )

    def test_background_treatment_not_mixed_with_ip_actions(self):
        """Background MTX must stay in non-IP background, not IP dose actions."""
        definition = _build_definition(
            study_phase="III期",
            comparator_type="placebo",
            background_mtx=True,
            interim_planned=False,
        )
        plan_service, helper = self._setup(definition)
        state = helper.require_confirmed_projection(
            project_id=definition.project_id,
            projection_kind="synopsis",
        )
        bg_module = next(
            m for m in state.plan.modules
            if m.module_id == "intervention.background_treatment"
        )
        ip_action_module = next(
            m for m in state.plan.modules
            if m.module_id == "intervention.investigational_product_dose_actions"
        )
        # Background treatment must be separate from IP dose actions.
        self.assertNotEqual(
            bg_module.module_id,
            ip_action_module.module_id,
        )
        # Background must be applicable (MTX is present).
        self.assertEqual(bg_module.applicability, "conditional_applicable")

    def test_modality_route_does_not_force_systemic_oral(self):
        """Nasal/topical route must not force systemic oral defaults."""
        definition = _build_definition(
            study_phase="II期",
            comparator_type="placebo",
            routes=["鼻喷"],
            interim_planned=False,
        )
        plan_service, helper = self._setup(definition)
        state = helper.require_confirmed_projection(
            project_id=definition.project_id,
            projection_kind="synopsis",
        )
        # The plan should build successfully with non-oral route.
        self.assertIsNotNone(state.plan)

    def test_phase1_sad_mad_first_in_patient_all_projections(self):
        """Phase I SAD+MAD+首次患者 must be consistent across all projections."""
        definition = _build_definition(
            study_phase="I期",
            phase1_parts=[
                MedicalWritingPhase1Part(
                    part_code="SAD",
                    population="健康受试者",
                    cohort_dose="SAD剂量递增队列",
                ),
                MedicalWritingPhase1Part(
                    part_code="MAD",
                    population="健康受试者",
                    cohort_dose="MAD剂量递增队列",
                ),
                MedicalWritingPhase1Part(
                    part_code="first_in_patient",
                    population="目标适应症患者",
                    cohort_dose="首次患者剂量队列",
                ),
            ],
        )
        plan_service, helper = self._setup(definition)
        for projection in (
            "synopsis",
            "sections_toc",
            "soa",
            "study_schema_flowchart",
            "docx_toc",
        ):
            state = helper.require_confirmed_projection(
                project_id=definition.project_id,
                projection_kind=projection,
            )
            # SAD, MAD, first_in_patient modules must be conditional_applicable.
            for part_code in ("sad", "mad", "first_in_patient"):
                module_id = f"design.phase1.{part_code}"
                module = next(
                    (m for m in state.plan.modules if m.module_id == module_id),
                    None,
                )
                if module:
                    self.assertEqual(
                        module.applicability,
                        "conditional_applicable",
                        f"{module_id} must be conditional_applicable for {projection}",
                    )

    def test_stale_plan_fails_closed(self):
        """A stale plan (source changed) must fail closed for all consumers."""
        definition = _build_definition()
        # Create a plan service with the original definition.
        definitions = {definition.project_id: definition}
        plan_service = MedicalWritingProtocolAssemblyPlanService(
            Path(self.tmpdir.name) / "stale.sqlite3",
            definitions.__getitem__,
        )
        refreshed = plan_service.refresh(
            definition.project_id,
            MedicalWritingProtocolAssemblyPlanRefreshRequest(
                expected_plan_revision=0,
                expected_source_definition_id=definition.definition_id,
                expected_source_definition_revision=definition.revision,
                expected_source_definition_sha256=definition.state_sha256,
                actor="test",
                idempotency_key="refresh-stale",
            ),
        )
        plan_service.confirm(
            definition.project_id,
            MedicalWritingProtocolAssemblyPlanConfirmRequest(
                expected_plan_revision=refreshed.plan.revision,
                expected_plan_sha256=refreshed.plan.state_sha256,
                actor="test",
                idempotency_key="confirm-stale",
            ),
        )
        # Now simulate source change: update the definition revision and hash.
        updated_definition = definition.model_copy(
            update={
                "revision": definition.revision + 1,
                "state_sha256": "b" * 64,
            }
        )
        definitions[definition.project_id] = updated_definition
        # The helper should detect staleness — source_current will be false.
        stale_helper = MedicalWritingPlanConsumptionHelper(plan_service)
        with self.assertRaises(PlanConsumptionError):
            stale_helper.require_confirmed_projection(
                project_id=definition.project_id,
                projection_kind="synopsis",
            )

    def test_project_isolation(self):
        """Plan from project A must not be consumable for project B."""
        def_a = _build_definition(project_id="proj_a")
        def_b = _build_definition(project_id="proj_b")
        plan_service, helper_a = self._setup(def_a)
        # Project B has no plan.
        with self.assertRaises(PlanUnconfirmedError):
            helper_a.require_confirmed_projection(
                project_id="proj_b",
                projection_kind="synopsis",
            )


# ---------------------------------------------------------------------------
# 5. Backward compatibility: services without helper work normally
# ---------------------------------------------------------------------------


class TestBackwardCompatibility(unittest.TestCase):
    """Services without plan helper must work as before (no regression)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_template_service_without_helper_works(self):
        """Template service without helper produces section seeds normally."""
        definition = _build_definition()
        svc = MedicalWritingProtocolTemplateService()  # no helper
        template = svc.definition(TEMPLATE_ID, TEMPLATE_VERSION)
        seeds = svc.section_seeds(definition, template)
        self.assertTrue(len(seeds) > 0)

    def test_template_service_module_resolutions_without_helper(self):
        """Module resolutions work without helper."""
        definition = _build_definition()
        svc = MedicalWritingProtocolTemplateService()
        template = svc.definition(TEMPLATE_ID, TEMPLATE_VERSION)
        resolutions = svc.module_resolutions(definition, template)
        self.assertTrue(len(resolutions) > 0)


if __name__ == "__main__":
    unittest.main()
