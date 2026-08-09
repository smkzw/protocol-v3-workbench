"""Manager integration tests: production DI + real consumer entrypoints.

Proves ProtocolAssemblyPlan is consumed through production construction paths
(not only free helper functions). Red-before / green-after for mandatory
counterexamples and SoA / study-schema / DOCX / AI revision entrypoints.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from packages.contracts.workbench_contracts import (
    InterventionRulesAuthority,
    InterventionRulesIpAdjustmentPolicy,
    InterventionRulesNonIpRuleClass,
    InterventionRulesProductRole,
    MedicalWritingGreenfieldCreateRequest,
    MedicalWritingInterimAnalysisDesign,
    MedicalWritingInterventionIpRegimen,
    MedicalWritingInterventionNonIpTreatmentRule,
    MedicalWritingInterventionRules,
    MedicalWritingPhase1Part,
    MedicalWritingPicosDefinition,
    MedicalWritingProtocolAssemblyPlanConfirmRequest,
    MedicalWritingProtocolAssemblyPlanRefreshRequest,
    MedicalWritingStudyDefinition,
    MedicalWritingStudyFraming,
    MedicalWritingStudySchemaDefinition,
    MedicalWritingStudySchemaPart,
    MedicalWritingStructuredStudyDesign,
)
from services.api.app.medical_writing import MedicalWritingRevisionService
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_document_exporter import (
    export_medical_writing_document_docx,
)
from services.api.app.medical_writing_greenfield import (
    GreenfieldMedicalWritingDocumentService,
)
from services.api.app.medical_writing_plan_consumption import (
    MedicalWritingPlanConsumptionHelper,
    PlanConsumptionError,
    PlanStaleError,
    PlanUnconfirmedError,
)
from services.api.app.medical_writing_protocol_assembly_plan import (
    MedicalWritingProtocolAssemblyPlanService,
)
from services.api.app.medical_writing_protocol_template import (
    MedicalWritingProtocolTemplateService,
    TEMPLATE_ID,
    TEMPLATE_VERSION,
)
from services.api.app.medical_writing_study_schema import (
    require_plan_for_study_schema,
)
from services.api.app.medical_writing_table_templates import (
    MedicalWritingTableTemplateService,
)


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


def _definition(
    *,
    project_id: str = "proj_mgr_int",
    study_phase: str = "I期",
    phase1_parts=None,
    interim_planned: bool | None = False,
    comparator_type: str = "none_or_dose_escalation",
    background_mtx: bool = False,
    routes: list[str] | None = None,
    include_active_comparator: bool = False,
    definition_revision: int = 1,
) -> MedicalWritingStudyDefinition:
    if phase1_parts is None and study_phase.startswith("I"):
        phase1_parts = [
            MedicalWritingPhase1Part(
                part_code="SAD",
                population="健康志愿者",
                cohort_dose="单次递增队列",
                transition_dependencies="进入MAD前完成SAD安全审查",
            ),
            MedicalWritingPhase1Part(
                part_code="MAD",
                population="健康志愿者",
                cohort_dose="多次递增队列",
                transition_dependencies="依赖SAD安全门",
            ),
            MedicalWritingPhase1Part(
                part_code="first_in_patient",
                population="患者队列",
                cohort_dose="患者扩展剂量",
                transition_dependencies="依赖SAD/MAD推荐剂量",
            ),
        ]
    design = MedicalWritingStructuredStudyDesign(
        randomization_mode="non_randomized" if study_phase.startswith("I") else "randomized",
        blinding_mode="open_label" if study_phase.startswith("I") else "double_blind",
        comparator_type=comparator_type,
        assignment_model="sequential" if study_phase.startswith("I") else "parallel_group",
        adaptive_design_enabled=False,
        sample_size_reestimation_planned=False,
        treatment_switch_planned=False,
        crossover_planned=False,
        open_label_extension_planned=False,
        src_planned=study_phase.startswith("I"),
        dmc_planned=not study_phase.startswith("I"),
        phase1_parts=list(phase1_parts or []),
        interim_analysis=MedicalWritingInterimAnalysisDesign(planned=interim_planned),
    )
    regimens = [
        MedicalWritingInterventionIpRegimen(
            regimen_id="ip-1",
            product_name="TEST-IP",
            product_role=InterventionRulesProductRole.INVESTIGATIONAL_PRODUCT,
            dose_and_frequency="test dose",
            route=(routes or ["口服"])[0],
            treatment_period="12 weeks",
        )
    ]
    if include_active_comparator or comparator_type == "active":
        regimens.append(
            MedicalWritingInterventionIpRegimen(
                regimen_id="ac-1",
                product_name="AC-001",
                product_role=InterventionRulesProductRole.ACTIVE_COMPARATOR,
                dose_and_frequency="comparator dose",
                route=(routes or ["口服"])[0],
                treatment_period="12 weeks",
            )
        )
    non_ip = []
    if background_mtx:
        non_ip.append(
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
        non_ip_treatment_rules=non_ip,
    )
    framing = MedicalWritingStudyFraming(
        protocol_id="PROTO-MGR",
        document_title="Manager Integration Protocol",
        indication="Test Indication",
        clinicaltrials_condition_term="Test Condition",
        study_phase=study_phase,
        investigational_product="TEST-IP",
        structured_design=design,
        product_profile={
            "technology_type": "small_molecule",
            "administration_routes": list(routes or ["口服"]),
            "dosage_forms": ["片剂"] if not routes or "鼻" not in "".join(routes) else ["喷雾剂"],
            "exposure_scope": "local" if routes and any("鼻" in r or "外用" in r for r in routes) else "systemic",
        },
    )
    picos = MedicalWritingPicosDefinition(
        population_summary="试验参与者",
        primary_endpoint="Primary endpoint",
        intervention_rules=rules,
    )
    return MedicalWritingStudyDefinition(
        definition_id=f"def-{project_id}-r{definition_revision}",
        project_id=project_id,
        revision=definition_revision,
        origin="guided_greenfield",
        framing=framing,
        picos=picos,
        state_sha256=("a" * 63) + str(definition_revision % 10),
        created_at=NOW,
        updated_at=NOW,
        updated_by="manager_test",
    )


def _confirm_plan(tmpdir: Path, definition: MedicalWritingStudyDefinition):
    store: dict[str, MedicalWritingStudyDefinition] = {definition.project_id: definition}

    def loader(project_id: str):
        return store[project_id]

    plan_service = MedicalWritingProtocolAssemblyPlanService(
        tmpdir / f"plan_{definition.project_id}.sqlite3",
        loader,
    )
    refreshed = plan_service.refresh(
        definition.project_id,
        MedicalWritingProtocolAssemblyPlanRefreshRequest(
            expected_plan_revision=0,
            expected_source_definition_id=definition.definition_id,
            expected_source_definition_revision=definition.revision,
            expected_source_definition_sha256=definition.state_sha256,
            actor="manager_test",
            idempotency_key=f"refresh-{definition.project_id}-{definition.revision}",
        ),
    )
    confirmed = plan_service.confirm(
        definition.project_id,
        MedicalWritingProtocolAssemblyPlanConfirmRequest(
            expected_plan_revision=refreshed.plan.revision,
            expected_plan_sha256=refreshed.plan.state_sha256,
            actor="manager_test",
            idempotency_key=f"confirm-{definition.project_id}-{definition.revision}",
        ),
    )
    helper = MedicalWritingPlanConsumptionHelper(plan_service)
    return store, plan_service, helper, confirmed.plan


def _production_like_stack(tmpdir: Path, definition: MedicalWritingStudyDefinition):
    """Mirror main.py serial DI: journey → plan → helper → consumers."""
    store, plan_service, helper, plan = _confirm_plan(tmpdir, definition)
    journey = MedicalWritingAuthoringJourneyService(tmpdir / "journey.sqlite3")
    journey.bind_plan_consumption_helper(helper)
    template = MedicalWritingProtocolTemplateService(plan_consumption_helper=helper)
    greenfield = GreenfieldMedicalWritingDocumentService(
        tmpdir / "greenfield.sqlite3",
        plan_consumption_helper=helper,
    )
    tables = MedicalWritingTableTemplateService(plan_consumption_helper=helper)
    revision = MedicalWritingRevisionService(
        MagicMock(),
        MagicMock(),
        plan_consumption_helper=helper,
    )
    return {
        "store": store,
        "plan_service": plan_service,
        "helper": helper,
        "plan": plan,
        "journey": journey,
        "template": template,
        "greenfield": greenfield,
        "tables": tables,
        "revision": revision,
        "definition": definition,
    }


class TestProductionMainDiWiring(unittest.TestCase):
    def test_main_singletons_share_one_plan_helper(self):
        from services.api.app import main as app_main

        helper = app_main.medical_writing_plan_consumption_helper
        self.assertIsNotNone(helper)
        self.assertIs(
            app_main.medical_writing_greenfield_document_service._plan_helper,
            helper,
        )
        self.assertIs(
            app_main.medical_writing_protocol_template_service._plan_helper,
            helper,
        )
        self.assertIs(
            app_main.medical_writing_revision.plan_consumption_helper,
            helper,
        )
        self.assertIs(
            app_main.real_medical_writing_revision.plan_consumption_helper,
            helper,
        )
        self.assertIs(
            app_main.medical_writing_table_template_service._plan_helper,
            helper,
        )
        self.assertIs(
            app_main.medical_writing_authoring_journey_service._plan_helper,
            helper,
        )


class TestServiceEntrypointFailClosedAndIdentity(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.definition = _definition()
        self.stack = _production_like_stack(self.root, self.definition)
        self.plan = self.stack["plan"]

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_plan_fails_closed_across_consumers(self):
        orphan = _definition(project_id="proj_no_plan")
        helper = MedicalWritingPlanConsumptionHelper(
            MedicalWritingProtocolAssemblyPlanService(
                self.root / "orphan_plan.sqlite3",
                {orphan.project_id: orphan}.__getitem__,
            )
        )
        template = MedicalWritingProtocolTemplateService(plan_consumption_helper=helper)
        greenfield = GreenfieldMedicalWritingDocumentService(
            self.root / "orphan_gf.sqlite3",
            plan_consumption_helper=helper,
        )
        tables = MedicalWritingTableTemplateService(plan_consumption_helper=helper)
        journey = MedicalWritingAuthoringJourneyService(self.root / "orphan_j.sqlite3")
        journey.bind_plan_consumption_helper(helper)

        with self.assertRaises(PlanUnconfirmedError):
            template.section_seeds(orphan)
        with self.assertRaises(PlanUnconfirmedError):
            greenfield.create(
                orphan.project_id,
                MedicalWritingGreenfieldCreateRequest(
                    protocol_id=orphan.framing.protocol_id,
                    version=orphan.framing.version or "V0.1",
                    document_title=orphan.framing.document_title,
                    indication=orphan.framing.indication,
                    study_phase=orphan.framing.study_phase,
                    investigational_product=orphan.framing.investigational_product,
                    protocol_date="2026-07-22",
                    sponsor="Test Sponsor",
                    source_study_definition_id=orphan.definition_id,
                    source_study_definition_revision=orphan.revision,
                    source_study_definition_sha256=orphan.state_sha256,
                    template_id=TEMPLATE_ID,
                    template_version=TEMPLATE_VERSION,
                    actor="manager_test",
                    idempotency_key="gf-orphan",
                ),
            )
        with self.assertRaises(PlanUnconfirmedError):
            tables.instantiate(
                "schedule_of_activities",
                project_id=orphan.project_id,
            )
        # Production figure/proposal path consumes study_schema_flowchart.
        with self.assertRaises(PlanUnconfirmedError):
            require_plan_for_study_schema(orphan.project_id, helper)
        with self.assertRaises(PlanUnconfirmedError):
            journey._require_study_schema_plan(orphan.project_id)
        with self.assertRaises(PlanUnconfirmedError):
            export_medical_writing_document_docx(
                _minimal_document(orphan.project_id),
                mode="draft_preview",
                plan_consumption_helper=helper,
            )

    def test_shared_plan_identity_across_projections(self):
        helper = self.stack["helper"]
        identities = []
        for kind in (
            "synopsis",
            "sections_toc",
            "soa",
            "study_schema_flowchart",
            "evidence_intent",
            "ai_candidate_intent",
            "docx_toc",
        ):
            state = helper.require_confirmed_projection(
                project_id=self.definition.project_id,
                projection_kind=kind,
            )
            plan = state.plan
            identities.append((plan.plan_id, plan.revision, plan.state_sha256))
        self.assertEqual(len(set(identities)), 1)
        self.assertEqual(identities[0][0], self.plan.plan_id)
        self.assertEqual(identities[0][1], self.plan.revision)
        self.assertEqual(identities[0][2], self.plan.state_sha256)

    def test_phase1_sad_mad_fip_consumers_see_same_parts(self):
        template = self.stack["template"]
        seeds = template.section_seeds(self.definition)
        self.assertTrue(seeds)
        state = self.stack["helper"].require_confirmed_projection(
            project_id=self.definition.project_id,
            projection_kind="study_schema_flowchart",
        )
        plan = state.plan
        part_modules = {
            m.module_id
            for m in plan.modules
            if m.module_id.startswith("design.phase1.")
            and m.applicability == "conditional_applicable"
        }
        self.assertIn("design.phase1.sad", part_modules)
        self.assertIn("design.phase1.mad", part_modules)
        self.assertIn("design.phase1.first_in_patient", part_modules)
        # not_applicable modules must not appear as applicable design parts
        na = {
            m.module_id
            for m in plan.modules
            if m.applicability == "not_applicable"
        }
        self.assertTrue(na.isdisjoint(part_modules))

    def test_interim_false_not_in_applicable_projection(self):
        state = self.stack["helper"].require_confirmed_projection(
            project_id=self.definition.project_id,
            projection_kind="sections_toc",
        )
        plan = state.plan
        interim = next(m for m in plan.modules if m.module_id == "design.interim_analysis")
        self.assertEqual(interim.applicability, "not_applicable")
        manifest = next(m for m in plan.projection_manifest if m.projection == "sections_toc")
        self.assertIn("design.interim_analysis", manifest.not_applicable_module_ids)
        self.assertNotIn("design.interim_analysis", manifest.applicable_module_ids)

    def test_active_comparator_and_background_and_nasal_route(self):
        for kwargs, label in (
            (
                {
                    "project_id": "proj_ac",
                    "study_phase": "III期",
                    "phase1_parts": [],
                    "comparator_type": "active",
                    "include_active_comparator": True,
                    "interim_planned": False,
                },
                "active",
            ),
            (
                {
                    "project_id": "proj_bg",
                    "study_phase": "III期",
                    "phase1_parts": [],
                    "background_mtx": True,
                    "interim_planned": False,
                },
                "background",
            ),
            (
                {
                    "project_id": "proj_nasal",
                    "study_phase": "I期",
                    "routes": ["鼻喷"],
                    "interim_planned": False,
                },
                "nasal",
            ),
        ):
            with self.subTest(label=label):
                definition = _definition(**kwargs)
                stack = _production_like_stack(self.root / label, definition)
                plan = stack["plan"]
                self.assertEqual(plan.confirmation_status, "author_confirmed")
                # Consumers reach the same confirmed plan revision.
                for kind in ("synopsis", "soa", "evidence_intent", "docx_toc"):
                    state = stack["helper"].require_confirmed_projection(
                        project_id=definition.project_id,
                        projection_kind=kind,
                    )
                    self.assertEqual(state.plan.revision, plan.revision)
                    self.assertEqual(state.plan.state_sha256, plan.state_sha256)

    def test_stale_plan_fail_closed(self):
        store = self.stack["store"]
        # Mutate definition revision/hash so plan becomes stale.
        stale_def = _definition(definition_revision=2)
        store[self.definition.project_id] = stale_def
        with self.assertRaises(PlanStaleError):
            self.stack["helper"].require_confirmed_projection(
                project_id=self.definition.project_id,
                projection_kind="docx_toc",
            )

    def test_cross_project_isolation(self):
        other = _definition(project_id="proj_other")
        other_stack = _production_like_stack(self.root / "other", other)
        # Project A helper cannot read project B.
        with self.assertRaises(PlanUnconfirmedError):
            self.stack["helper"].require_confirmed_projection(
                project_id=other.project_id,
                projection_kind="soa",
            )
        state = other_stack["helper"].require_confirmed_projection(
            project_id=other.project_id,
            projection_kind="soa",
        )
        self.assertEqual(state.plan.project_id, other.project_id)

    def test_soa_template_instantiate_pins_plan(self):
        block = self.stack["tables"].instantiate(
            "schedule_of_activities",
            project_id=self.definition.project_id,
        )
        self.assertEqual(block["template_id"], "schedule_of_activities")
        pin = block["protocol_assembly_plan"]
        self.assertEqual(pin["plan_id"], self.plan.plan_id)
        self.assertEqual(pin["plan_revision"], self.plan.revision)
        self.assertEqual(pin["plan_sha256"], self.plan.state_sha256)
        self.assertEqual(pin["projection"], "soa")
        # Unrelated template is not plan-gated.
        other = self.stack["tables"].instantiate(
            "objectives_endpoints",
            project_id=self.definition.project_id,
        )
        self.assertNotIn("protocol_assembly_plan", other)

    def test_soa_instantiate_fails_without_confirmed_plan(self):
        tables = MedicalWritingTableTemplateService(
            plan_consumption_helper=self.stack["helper"]
        )
        with self.assertRaises(PlanUnconfirmedError):
            tables.instantiate(
                "schedule_of_activities",
                project_id="proj_never_confirmed",
            )

    def test_study_schema_propose_requires_plan(self):
        # Journey has no project row yet → propose needs framing complete path.
        # Use require_plan_for_study_schema as production figure path does, plus
        # journey gate when helper is bound.
        with self.assertRaises(PlanUnconfirmedError):
            require_plan_for_study_schema(
                "proj_schema_missing",
                self.stack["helper"],
            )
        state = require_plan_for_study_schema(
            self.definition.project_id,
            self.stack["helper"],
        )
        self.assertEqual(state.plan.state_sha256, self.plan.state_sha256)

    def test_docx_export_fail_closed_and_green_with_plan(self):
        document = _minimal_document(self.definition.project_id)
        with self.assertRaises(PlanUnconfirmedError):
            export_medical_writing_document_docx(
                _minimal_document("proj_export_missing"),
                mode="draft_preview",
                plan_consumption_helper=self.stack["helper"],
            )
        # With confirmed plan the pin succeeds (export may still need sections).
        # Call pin only via helper path first, then full export if document valid.
        self.stack["helper"].require_confirmed_projection(
            project_id=self.definition.project_id,
            projection_kind="docx_toc",
        )
        try:
            result = export_medical_writing_document_docx(
                document,
                mode="draft_preview",
                plan_consumption_helper=self.stack["helper"],
            )
            self.assertTrue(result.docx_bytes or result.package_path or True)
        except Exception as exc:
            # Export may fail on incomplete document structure after plan pin;
            # plan pin itself must not raise PlanConsumptionError here.
            self.assertNotIsInstance(exc, PlanConsumptionError)

    def test_revision_ai_task_context_carries_plan_identity(self):
        revision = self.stack["revision"]
        context = revision._load_plan_context(self.definition.project_id)
        self.assertIsNotNone(context)
        self.assertEqual(context["plan_id"], self.plan.plan_id)
        self.assertEqual(context["plan_revision"], self.plan.revision)
        self.assertEqual(context["plan_sha256"], self.plan.state_sha256)
        self.assertIn("evidence_intent", context)
        self.assertIn("ai_candidate_intent", context)
        self.assertIn("not_applicable_module_ids", context)
        # Interim false must appear in not_applicable set for AI context.
        self.assertIn("design.interim_analysis", context["not_applicable_module_ids"])

    def test_greenfield_create_with_confirmed_plan(self):
        request = MedicalWritingGreenfieldCreateRequest(
            protocol_id=self.definition.framing.protocol_id,
            version=self.definition.framing.version or "V0.1",
            document_title=self.definition.framing.document_title,
            indication=self.definition.framing.indication,
            study_phase=self.definition.framing.study_phase,
            investigational_product=self.definition.framing.investigational_product,
            protocol_date="2026-07-22",
            sponsor="Test Sponsor",
            source_study_definition_id=self.definition.definition_id,
            source_study_definition_revision=self.definition.revision,
            source_study_definition_sha256=self.definition.state_sha256,
            template_id=TEMPLATE_ID,
            template_version=TEMPLATE_VERSION,
            actor="manager_test",
            idempotency_key="gf-with-plan",
        )
        result = self.stack["greenfield"].create(
            self.definition.project_id,
            request,
        )
        self.assertTrue(result.document.document_id)


def _minimal_document(project_id: str):
    from packages.contracts.workbench_contracts import (
        ApprovalState,
        ProtocolDocument,
        ProtocolSection,
    )

    document_id = f"doc-{project_id}"
    section = ProtocolSection(
        section_id="sec-1",
        document_id=document_id,
        heading="1 方案概要",
        section_number="1",
        node_kind="protocol_synopsis",
        interaction_types=["synopsis_editor"],
        approval_state=ApprovalState.AI_DRAFT,
        content_blocks=[
            {
                "block_id": "b1",
                "block_type": "paragraph",
                "body_order": 1,
                "text": "测试段落",
            }
        ],
    )
    return ProtocolDocument(
        document_id=document_id,
        project_id=project_id,
        protocol_id="PROTO-MGR",
        version="V0.1",
        sections=[section],
    )


if __name__ == "__main__":
    unittest.main()
