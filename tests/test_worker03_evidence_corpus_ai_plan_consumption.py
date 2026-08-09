"""Worker 03 tests: evidence_intent / ai_candidate_intent / corpus plan consumption.

These tests verify that MedicalWritingRevisionService and the corpus services
consume one confirmed current ProtocolAssemblyPlan revision for evidence
scoping, AI candidate/revision context, and corpus retrieval — and fail
closed when the plan is missing, stale, unconfirmed, or has unresolved
blocking drivers.

Fake providers are used only through test_only_provider_injection.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import (  # noqa: E402
    InterventionRulesAuthority,
    InterventionRulesIpAdjustmentPolicy,
    InterventionRulesNonIpRuleClass,
    InterventionRulesProductRole,
    MedicalWritingInterventionIpRegimen,
    MedicalWritingInterventionNonIpTreatmentRule,
    MedicalWritingInterventionRules,
    MedicalWritingInterimAnalysisDesign,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyDefinition,
    MedicalWritingStudyFraming,
    MedicalWritingStructuredStudyDesign,
)
from services.api.app.ai_execution_policy import AiExecutionPolicyResolver  # noqa: E402
from services.api.app.ai_gateway import AiPromptEnvelope  # noqa: E402
from services.api.app.ai_task_runner import AiTaskRunner, AiTaskStore  # noqa: E402
from services.api.app.medical_writing import MedicalWritingRevisionService  # noqa: E402
from services.api.app.medical_writing_plan_consumption import (  # noqa: E402
    MedicalWritingPlanConsumptionHelper,
    PlanUnconfirmedError,
)
from services.api.app.medical_writing_corpus_policy import (  # noqa: E402
    plan_corpus_facets,
    corpus_text_facet_match,
    plan_not_applicable_module_filter,
    CorpusSourcePolicy,
)
from services.api.app.medical_writing_protocol_assembly_plan import (  # noqa: E402
    MedicalWritingProtocolAssemblyPlanService,
    build_protocol_assembly_plan,
)

NOW = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)


def _definition(
    project_id: str = "proj_w03_test",
    *,
    revision: int = 1,
    definition_hash: str = "a" * 64,
    study_phase: str = "II期",
    phase1_parts: list[str] | None = None,
    interim_planned: bool | None = False,
    comparator_type: str = "active",
    include_active_comparator: bool = True,
    routes: list[str] | None = None,
    dosage_forms: list[str] | None = None,
    exposure_scope: str = "systemic",
) -> MedicalWritingStudyDefinition:
    regimens = [
        MedicalWritingInterventionIpRegimen(
            regimen_id="ip-main",
            product_name="IP-001",
            product_role=InterventionRulesProductRole.INVESTIGATIONAL_PRODUCT,
            dose_and_frequency="authoritative dose",
            route="authoritative route",
            treatment_period="authoritative period",
        )
    ]
    if include_active_comparator:
        regimens.append(
            MedicalWritingInterventionIpRegimen(
                regimen_id="active-main",
                product_name="AC-001",
                product_role=InterventionRulesProductRole.ACTIVE_COMPARATOR,
                dose_and_frequency="authoritative comparator dose",
                route="authoritative comparator route",
                treatment_period="authoritative comparator period",
            )
        )
    intervention_rules = MedicalWritingInterventionRules(
        authority=InterventionRulesAuthority.STRUCTURED,
        ip_regimens=regimens,
        ip_adjustment_policy=(
            InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
        ),
        no_planned_adjustment_statement="No planned IP dose adjustment.",
        non_ip_treatment_rules=[],
    )
    design = MedicalWritingStructuredStudyDesign(
        randomization_mode="randomized",
        blinding_mode="double_blind",
        comparator_type=comparator_type,
        assignment_model="parallel_group",
        adaptive_design_enabled=False,
        sample_size_reestimation_planned=False,
        treatment_switch_planned=False,
        crossover_planned=False,
        open_label_extension_planned=False,
        src_planned=False,
        dmc_planned=False,
        interim_analysis=MedicalWritingInterimAnalysisDesign(planned=interim_planned),
        phase1_parts=list(
            phase1_parts
            if phase1_parts is not None
            else []
        ),
    )
    framing = MedicalWritingStudyFraming(
        protocol_id="PROTO-001",
        document_title="Protocol title",
        indication="Authoritative indication",
        clinicaltrials_condition_term="Authoritative condition",
        study_phase=study_phase,
        investigational_product="IP-001",
        structured_design=design,
        product_profile={
            "technology_type": "small_molecule",
            "administration_routes": list(routes or ["口服"]),
            "dosage_forms": list(dosage_forms or ["片剂"]),
            "exposure_scope": exposure_scope,
            "pk_pd_considerations": [],
        },
    )
    picos = MedicalWritingPicosDefinition(
        population_summary="Authoritative population",
        primary_endpoint="Authoritative primary endpoint",
        intervention_rules=intervention_rules,
        aesi_definitions=[],
        statistical_strategy="",
        visit_strategy="",
    )
    return MedicalWritingStudyDefinition(
        definition_id=f"definition-{project_id}",
        project_id=project_id,
        revision=revision,
        origin="guided_greenfield",
        framing=framing,
        picos=picos,
        state_sha256=definition_hash,
        created_at=NOW,
        updated_at=NOW,
        updated_by="fixture_author",
    )


def _test_only_policy() -> AiExecutionPolicyResolver:
    return AiExecutionPolicyResolver(
        deployment_profile="local_private_clinical",
        provider_name="buddy",
        model_name="deepseek-v4-pro",
        test_only_provider_injection=True,
    )


class FakeRevisionProvider:
    provider_name = "buddy"
    model_name = "deepseek-v4-pro"

    def __init__(self):
        self.envelopes: list[AiPromptEnvelope] = []

    def select_evidence_source(self, allowed_sources):
        return allowed_sources[0]

    def run(self, envelope: AiPromptEnvelope):
        self.envelopes.append(envelope)
        allowed_sources = envelope.payload["allowed_sources"]
        source = self.select_evidence_source(allowed_sources)
        source_id = source["source_id"]
        return {
            "task_id": envelope.task_id,
            "task_type": envelope.task_type.value,
            "provider": self.provider_name,
            "model": self.model_name,
            "prompt_version": envelope.prompt_version,
            "input_source_ids": [item["source_id"] for item in allowed_sources],
            "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
            "findings": [
                {
                    "finding_id": "finding_revision_001",
                    "status": "supported",
                    "title": "候选正文",
                    "source_id": source_id,
                    "evidence_span_ids": ["span_revision_001"],
                }
            ],
            "evidence_spans": [
                {
                    "span_id": "span_revision_001",
                    "source_id": source_id,
                    "locator": source["locator"],
                    "quote": source["text_preview"],
                }
            ],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "revision": {
                "proposal_text": "候选正文内容。",
                "diff_patch": "- 旧\n+ 新",
                "rationale": "修改理由。",
                "evidence_span_ids": ["span_revision_001"],
                "alternatives": [
                    {
                        "proposal_text": "替代版本1。",
                        "diff_patch": "alt1",
                        "rationale": "alt1理由。",
                        "evidence_span_ids": ["span_revision_001"],
                    },
                    {
                        "proposal_text": "替代版本2。",
                        "diff_patch": "alt2",
                        "rationale": "alt2理由。",
                        "evidence_span_ids": ["span_revision_001"],
                    },
                ],
            },
        }


class PlanConsumptionHelperTests(unittest.TestCase):
    """Verify the fail-closed behavior of plan consumption for
    evidence_intent and ai_candidate_intent projections."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "plan.sqlite3"
        self.project_id = "proj_w03_plan"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _service(
        self,
        definition: MedicalWritingStudyDefinition,
    ) -> tuple[
        MedicalWritingProtocolAssemblyPlanService,
        MedicalWritingPlanConsumptionHelper,
    ]:
        svc = MedicalWritingProtocolAssemblyPlanService(
            self.db_path,
            lambda pid: definition if pid == self.project_id else None,
        )
        helper = MedicalWritingPlanConsumptionHelper(svc)
        return svc, helper

    def _confirm(self, svc, definition):
        """Build, refresh, and confirm a plan for the definition."""
        plan = build_protocol_assembly_plan(
            definition,
            plan_id="plan-test",
            revision=1,
            actor="medical_author",
            now=NOW,
        )
        # Persist the plan directly by using refresh.
        from packages.contracts.workbench_contracts import (
            MedicalWritingProtocolAssemblyPlanRefreshRequest,
        )
        svc.refresh(
            self.project_id,
            MedicalWritingProtocolAssemblyPlanRefreshRequest(
                expected_plan_revision=0,
                expected_source_definition_id=definition.definition_id,
                expected_source_definition_revision=definition.revision,
                expected_source_definition_sha256=definition.state_sha256,
                actor="medical_author",
                idempotency_key="key1",
            ),
        )
        from packages.contracts.workbench_contracts import (
            MedicalWritingProtocolAssemblyPlanConfirmRequest,
        )
        svc.confirm(
            self.project_id,
            MedicalWritingProtocolAssemblyPlanConfirmRequest(
                expected_plan_revision=1,
                expected_plan_sha256=svc.current_state(self.project_id).plan.state_sha256,
                actor="medical_author",
                idempotency_key="confirm1",
            ),
        )

    def test_missing_plan_raises_unconfirmed(self):
        definition = _definition(self.project_id)
        svc, helper = self._service(definition)
        with self.assertRaises(PlanUnconfirmedError):
            helper.require_confirmed_projection(
                project_id=self.project_id,
                projection_kind="evidence_intent",
            )

    def test_unconfirmed_plan_raises_unconfirmed(self):
        definition = _definition(self.project_id)
        svc, helper = self._service(definition)
        from packages.contracts.workbench_contracts import (
            MedicalWritingProtocolAssemblyPlanRefreshRequest,
        )
        svc.refresh(
            self.project_id,
            MedicalWritingProtocolAssemblyPlanRefreshRequest(
                expected_plan_revision=0,
                expected_source_definition_id=definition.definition_id,
                expected_source_definition_revision=definition.revision,
                expected_source_definition_sha256=definition.state_sha256,
                actor="medical_author",
                idempotency_key="key1",
            ),
        )
        with self.assertRaises(PlanUnconfirmedError):
            helper.require_confirmed_projection(
                project_id=self.project_id,
                projection_kind="ai_candidate_intent",
            )

    def test_confirmed_plan_returns_state_for_evidence_intent(self):
        definition = _definition(self.project_id)
        svc, helper = self._service(definition)
        self._confirm(svc, definition)
        state = helper.require_confirmed_projection(
            project_id=self.project_id,
            projection_kind="evidence_intent",
        )
        self.assertTrue(state.available)
        self.assertIsNotNone(state.plan)
        self.assertEqual("author_confirmed", state.plan.confirmation_status)

    def test_confirmed_plan_returns_state_for_ai_candidate_intent(self):
        definition = _definition(self.project_id)
        svc, helper = self._service(definition)
        self._confirm(svc, definition)
        state = helper.require_confirmed_projection(
            project_id=self.project_id,
            projection_kind="ai_candidate_intent",
        )
        self.assertTrue(state.available)
        self.assertIsNotNone(state.plan)

    def test_cross_project_isolation(self):
        """Plan for project A must not be available for project B."""
        def_a = _definition("proj_w03_a")
        def_b = _definition("proj_w03_b")
        svc = MedicalWritingProtocolAssemblyPlanService(
            self.db_path,
            lambda pid: {"proj_w03_a": def_a, "proj_w03_b": def_b}.get(pid),
        )
        helper = MedicalWritingPlanConsumptionHelper(svc)
        from packages.contracts.workbench_contracts import (
            MedicalWritingProtocolAssemblyPlanRefreshRequest,
            MedicalWritingProtocolAssemblyPlanConfirmRequest,
        )
        svc.refresh(
            "proj_w03_a",
            MedicalWritingProtocolAssemblyPlanRefreshRequest(
                expected_plan_revision=0,
                expected_source_definition_id=def_a.definition_id,
                expected_source_definition_revision=def_a.revision,
                expected_source_definition_sha256=def_a.state_sha256,
                actor="medical_author",
                idempotency_key="key_a",
            ),
        )
        svc.confirm(
            "proj_w03_a",
            MedicalWritingProtocolAssemblyPlanConfirmRequest(
                expected_plan_revision=1,
                expected_plan_sha256=svc.current_state("proj_w03_a").plan.state_sha256,
                actor="medical_author",
                idempotency_key="confirm_a",
            ),
        )
        with self.assertRaises(PlanUnconfirmedError):
            helper.require_confirmed_projection(
                project_id="proj_w03_b",
                projection_kind="evidence_intent",
            )


class CorpusPlanFacetTests(unittest.TestCase):
    """Verify corpus policy plan facet extraction and matching."""

    def test_plan_corpus_facets_extracts_confirmed_drivers(self):
        drivers = [
            {
                "driver_id": "modality_1",
                "driver_kind": "drug_modality",
                "decision_state": "design_driven",
                "value_summary": "鼻喷",
            },
            {
                "driver_id": "interim_1",
                "driver_kind": "interim_analysis",
                "decision_state": "not_applicable",
                "value_summary": "",
            },
            {
                "driver_id": "unknown_1",
                "driver_kind": "phase",
                "decision_state": "unknown",
                "value_summary": "",
            },
        ]
        facets = plan_corpus_facets(drivers)
        self.assertIn("modality", facets)
        self.assertEqual("鼻喷", facets["modality"])
        self.assertIn("interim", facets)
        self.assertEqual("not_applicable", facets["interim"])

    def test_corpus_text_facet_match_penalizes_oral_for_nasal_plan(self):
        plan_facets = {"modality": "鼻喷", "route": "鼻喷"}
        policy = CorpusSourcePolicy(governance_status="clean_full_protocol")
        adjustment, reasons = corpus_text_facet_match(
            "口服后全身暴露的PK参数",
            "some_source.docx",
            policy,
            plan_facets,
        )
        self.assertLess(adjustment, 0.0)
        self.assertTrue(any("oral_systemic" in r for r in reasons))

    def test_corpus_text_facet_match_no_penalty_for_matching_route(self):
        plan_facets = {"modality": "鼻喷", "route": "鼻喷"}
        policy = CorpusSourcePolicy(governance_status="clean_full_protocol")
        adjustment, reasons = corpus_text_facet_match(
            "鼻喷给药后局部暴露",
            "nasal_source.docx",
            policy,
            plan_facets,
        )
        self.assertEqual(0.0, adjustment)
        self.assertEqual([], reasons)

    def test_corpus_text_facet_match_penalizes_interim_when_not_applicable(self):
        plan_facets = {"interim": "not_applicable"}
        policy = CorpusSourcePolicy(governance_status="clean_full_protocol")
        adjustment, reasons = corpus_text_facet_match(
            "期中分析计划在样本量达到50%时执行",
            "some_source.docx",
            policy,
            plan_facets,
        )
        self.assertLess(adjustment, 0.0)
        self.assertTrue(any("interim" in r for r in reasons))

    def test_corpus_text_facet_match_boosts_active_comparator(self):
        plan_facets = {"active_comparator": "阳性对照"}
        policy = CorpusSourcePolicy(governance_status="clean_full_protocol")
        adjustment, reasons = corpus_text_facet_match(
            "阳性对照药为已获批的生物制剂",
            "some_source.docx",
            policy,
            plan_facets,
        )
        self.assertGreater(adjustment, 0.0)

    def test_plan_not_applicable_module_filter_excludes_interim(self):
        self.assertTrue(
            plan_not_applicable_module_filter(
                "本研究包含期中分析计划。",
                ["design.interim_analysis"],
            )
        )
        self.assertFalse(
            plan_not_applicable_module_filter(
                "本研究为随机双盲对照试验。",
                ["design.interim_analysis"],
            )
        )
        self.assertFalse(
            plan_not_applicable_module_filter(
                "任何文本",
                [],
            )
        )

    def test_plan_not_applicable_module_filter_excludes_adaptive(self):
        self.assertTrue(
            plan_not_applicable_module_filter(
                "适应性设计允许根据中期数据调整样本量。",
                ["design.adaptive_design"],
            )
        )


class RevisionServicePlanContextTests(unittest.TestCase):
    """Verify that MedicalWritingRevisionService consumes plan projections
    for evidence_intent and ai_candidate_intent when the helper is injected."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.provider = FakeRevisionProvider()
        self.runner = AiTaskRunner(
            __import__("services.api.app.main", fromlist=["repo"]).repo,
            AiTaskStore(Path(self.tmpdir.name) / "ai_runs.jsonl"),
            provider_factory=lambda resolution: self.provider,
            policy_resolver=_test_only_policy(),
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_load_plan_context_returns_none_without_helper(self):
        """When no helper is configured, _load_plan_context returns None
        (backward compatibility)."""
        from services.api.app import main as app_main
        svc = MedicalWritingRevisionService(
            app_main.repo,
            self.runner,
        )
        self.assertIsNone(svc.plan_consumption_helper)
        result = svc._load_plan_context("any_project")
        self.assertIsNone(result)

    def test_load_plan_context_fails_closed_on_missing_plan(self):
        """When helper is configured but plan is missing, raises
        PlanUnconfirmedError."""
        from services.api.app import main as app_main
        plan_db = Path(self.tmpdir.name) / "plan.sqlite3"
        plan_svc = MedicalWritingProtocolAssemblyPlanService(
            plan_db,
            lambda pid: None,
        )
        helper = MedicalWritingPlanConsumptionHelper(plan_svc)
        svc = MedicalWritingRevisionService(
            app_main.repo,
            self.runner,
            plan_consumption_helper=helper,
        )
        with self.assertRaises(PlanUnconfirmedError):
            svc._load_plan_context("proj_no_plan")

    def test_merge_plan_context_injects_plan_pin_and_not_applicable(self):
        from services.api.app import main as app_main
        svc = MedicalWritingRevisionService(
            app_main.repo,
            self.runner,
        )
        task_context = {
            "revision_intent": "medical_writing_revision",
            "preservation_rules": ["基础规则。"],
        }
        plan_context = {
            "plan_id": "plan-001",
            "plan_revision": 3,
            "plan_sha256": "abc123",
            "source_definition_id": "def-001",
            "source_definition_revision": 1,
            "source_definition_sha256": "def456",
            "evidence_intent": {
                "required_module_ids": [],
                "not_applicable_module_ids": [],
                "design_drivers": [],
            },
            "ai_candidate_intent": {
                "required_module_ids": [],
                "not_applicable_module_ids": [],
                "design_drivers": [],
            },
            "not_applicable_module_ids": ["design.interim_analysis"],
        }
        merged = svc._merge_plan_context(task_context, plan_context)
        self.assertIn("protocol_assembly_plan", merged)
        self.assertEqual(3, merged["protocol_assembly_plan"]["plan_revision"])
        # Check that not_applicable modules produce a preservation rule.
        rules = merged["preservation_rules"]
        has_interim_rule = any(
            "design.interim_analysis" in r and "不适用" in r
            for r in rules
        )
        self.assertTrue(has_interim_rule)

    def test_merge_plan_context_injects_modality_constraint(self):
        from services.api.app import main as app_main
        svc = MedicalWritingRevisionService(
            app_main.repo,
            self.runner,
        )
        task_context = {
            "revision_intent": "medical_writing_revision",
            "preservation_rules": [],
        }
        plan_context = {
            "plan_id": "plan-001",
            "plan_revision": 1,
            "plan_sha256": "abc",
            "source_definition_id": "def",
            "source_definition_revision": 1,
            "source_definition_sha256": "def",
            "evidence_intent": {
                "required_module_ids": [],
                "not_applicable_module_ids": [],
                "design_drivers": [
                    {
                        "driver_id": "modality_1",
                        "driver_kind": "drug_modality",
                        "decision_state": "design_driven",
                        "value_summary": "鼻喷",
                        "fact_path": "product_profile.administration_routes",
                    },
                ],
            },
            "ai_candidate_intent": {
                "required_module_ids": [],
                "not_applicable_module_ids": [],
                "design_drivers": [],
            },
            "not_applicable_module_ids": [],
        }
        merged = svc._merge_plan_context(task_context, plan_context)
        rules = merged["preservation_rules"]
        has_modality_rule = any(
            "鼻喷" in r and "口服" in r
            for r in rules
        )
        self.assertTrue(has_modality_rule)


class RevisionPromptPlanPinTests(unittest.TestCase):
    """Verify that revision_task_context preserves protocol_assembly_plan pin."""

    def test_plan_pin_is_preserved_through_revision_task_context(self):
        from services.api.app.medical_writing_revision_prompts import (
            revision_task_context,
        )
        ctx = revision_task_context(
            "medical_writing_revision",
            {
                "protocol_assembly_plan": {
                    "plan_id": "plan-001",
                    "plan_revision": 2,
                    "plan_sha256": "def789",
                },
                "preservation_rules": ["额外规则。"],
            },
        )
        self.assertIn("protocol_assembly_plan", ctx)
        self.assertEqual("plan-001", ctx["protocol_assembly_plan"]["plan_id"])
        self.assertEqual(2, ctx["protocol_assembly_plan"]["plan_revision"])
        # preservation_rules should include both base and extra rules.
        self.assertGreater(len(ctx["preservation_rules"]), 1)


if __name__ == "__main__":
    unittest.main()
