"""Focused tests for the structured study design contract, interim analysis
dynamic chapter/synopsis projection, active comparator authority bridging and
complex background therapy.

Worker 01 — mw_release_execution_round2_20260720.

These tests prove the structured_design patch survives the full lifecycle
(migration, adopt, save, reload, regenerate) and that the dynamic chapter
matrix and synopsis projection prefer the structured fact while correctly
falling back to legacy text only when the status is undecided.

Coverage areas required by the execution context:
* old JSON migration (legacy payloads without structured_design load cleanly)
* adopt/save/reload/regenerate preserves structured_design
* planned true / false / unknown interim behavior
* synopsis row detail prefers structured facts
* chapter source facts bind to framing.structured_design
* active comparator uses existing IP regimen authority (no second truth source)
* complex background therapy uses existing non-IP background-rule authority
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from packages.contracts.workbench_contracts import (
    AuthoringPrefillAdoptRequest,
    AuthoringPrefillGenerateRequest,
    AuthoringPrefillPackage,
    InterventionRulesNonIpPolicy,
    InterventionRulesNonIpRuleClass,
    InterventionRulesProductRole,
    MedicalWritingAuthoringJourney,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingInterventionIpRegimen,
    MedicalWritingInterventionNonIpTreatmentRule,
    MedicalWritingInterventionRules,
    MedicalWritingInterimAnalysisDesign,
    MedicalWritingStudyFactState,
    MedicalWritingStudyFraming,
    MedicalWritingStructuredStudyDesign,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
    _project_design_synopsis_from_dict,
    _project_interim_synopsis_from_dict,
    _render_protocol_synopsis,
)
from services.api.app.medical_writing_authoring_prefill import (
    map_design_adoption_to_study_updates,
)
from services.api.app.medical_writing_intervention_rules_projection import (
    render_intervention_rules_panel,
)
from services.api.app.medical_writing_protocol_template import (
    MedicalWritingProtocolTemplateService,
    _company_module_resolutions,
    _company_synopsis_data,
    _project_interim_analysis_synopsis_value,
    _project_structured_design_synopsis_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_request(**overrides) -> MedicalWritingAuthoringJourneyCreateRequest:
    framing_fields = {
        "investigational_product": "CMS-D017",
        "indication": "类风湿关节炎",
        "study_phase": "II期",
    }
    request_fields = {
        "actor": "medical_manager_test",
        "idempotency_key": "create-001",
    }
    for key, value in overrides.items():
        if key in framing_fields:
            framing_fields[key] = value
        else:
            request_fields[key] = value
    request_fields["framing"] = MedicalWritingStudyFraming(**framing_fields)
    return MedicalWritingAuthoringJourneyCreateRequest(**request_fields)


def _build_structured_framing_namespace(
    *,
    design_pattern: str = "",
    structured: MedicalWritingStructuredStudyDesign | None = None,
) -> SimpleNamespace:
    """Build a framing SimpleNamespace with structured_design attached."""
    if structured is None:
        structured = MedicalWritingStructuredStudyDesign()
    return SimpleNamespace(
        design_pattern=design_pattern,
        structured_design=structured,
    )


def _build_definition_with_structured(
    *,
    structured: MedicalWritingStructuredStudyDesign | None = None,
    design_pattern: str = "",
    statistical_strategy: str = "",
    required_background_rules: list[str] | None = None,
    intervention_rules: MedicalWritingInterventionRules | None = None,
) -> SimpleNamespace:
    """Build a definition SimpleNamespace for protocol template projection."""
    if structured is None:
        structured = MedicalWritingStructuredStudyDesign()
    framing = SimpleNamespace(
        study_phase="III期",
        document_title="Test Protocol",
        investigational_product="TEST-001",
        indication="测试适应症",
        design_pattern=design_pattern,
        population_intent="目标人群",
        intrinsic_objectives=["疗效确证"],
        target_mechanism="",
        structured_design=structured,
        product_profile=SimpleNamespace(
            technology_type="small_molecule",
            administration_routes=["口服"],
            dosage_forms=["片剂"],
            immunogenicity_relevance="not_expected",
            safety_considerations=[],
            pk_pd_considerations=[],
        ),
    )
    picos = SimpleNamespace(
        design_archetype="",
        population_summary="目标人群",
        inclusion_modules=[],
        exclusion_modules=[],
        intervention_summary="试验药物方案",
        intervention_dose_regimen="每日一次口服给药",
        allowed_concomitant_rules=[],
        required_background_rules=list(required_background_rules or []),
        prohibited_concomitant_rules=[],
        comparator_summary="安慰剂",
        primary_endpoint="主要终点",
        key_secondary_endpoints=[],
        other_secondary_endpoints=[],
        exploratory_endpoints=[],
        safety_endpoints=[],
        aesi_definitions=[],
        assessment_instruments=[],
        sample_size_strategy="计划入组约120例。",
        statistical_strategy=statistical_strategy,
        study_epochs=[],
        visit_strategy="",
        intervention_rules=intervention_rules,
    )
    return SimpleNamespace(
        definition_id="mwdef_structured_test",
        revision=1,
        synopsis_text="结构化研究摘要",
        framing=framing,
        picos=picos,
        field_states={
            "framing.structured_design": MedicalWritingStudyFactState(status="confirmed"),
        },
        module_resolutions={},
    )


# ---------------------------------------------------------------------------
# 1. Legacy JSON migration: framing without structured_design loads cleanly
# ---------------------------------------------------------------------------

class StructuredDesignLegacyMigrationTests(unittest.TestCase):
    """Old framing payloads without structured_design must load without error."""

    def test_framing_without_structured_design_loads_with_defaults(self):
        """A framing JSON dict without structured_design field populates defaults."""
        legacy_payload = {
            "protocol_id": "CMS-001",
            "indication": "类风湿关节炎",
            "study_phase": "II期",
            "investigational_product": "CMS-D017",
            "design_pattern": "随机、双盲、安慰剂对照",
        }
        framing = MedicalWritingStudyFraming.model_validate(legacy_payload)
        self.assertIsNotNone(framing.structured_design)
        self.assertEqual(
            framing.structured_design.randomization_mode, "undecided"
        )
        self.assertEqual(
            framing.structured_design.comparator_type, "undecided"
        )
        # Interim analysis defaults to planned=None (undecided).
        self.assertIsNone(framing.structured_design.interim_analysis.planned)

    def test_journey_payload_without_structured_design_round_trips(self):
        """A journey payload with legacy framing (no structured_design) round-trips."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir) / "test.sqlite3"
            )
            service.create("proj_legacy", _create_request())
            journey = service.get("proj_legacy")
            # Strip structured_design from the serialized framing to simulate legacy.
            raw = json.loads(journey.model_dump_json())
            # The framing is nested inside study_definition.
            if raw.get("study_definition"):
                raw["study_definition"]["framing"].pop("structured_design", None)
            # Re-validate: should load without error and structured_design gets defaults.
            reloaded = MedicalWritingAuthoringJourney.model_validate(raw)
            framing = reloaded.study_definition.framing
            self.assertIsNotNone(framing.structured_design)
            self.assertEqual(
                framing.structured_design.randomization_mode, "undecided"
            )

    def test_framing_with_partial_structured_design_loads(self):
        """A framing JSON with partial structured_design fills missing fields."""
        payload = {
            "indication": "银屑病",
            "study_phase": "III期",
            "investigational_product": "TEST-Psor",
            "design_pattern": "随机、双盲",
            "structured_design": {
                "randomization_mode": "randomized",
                "blinding_mode": "double_blind",
                # comparator_type, interim_analysis etc. omitted → defaults.
            },
        }
        framing = MedicalWritingStudyFraming.model_validate(payload)
        self.assertEqual(
            framing.structured_design.randomization_mode, "randomized"
        )
        self.assertEqual(
            framing.structured_design.blinding_mode, "double_blind"
        )
        self.assertEqual(
            framing.structured_design.comparator_type, "undecided"
        )
        self.assertIsNone(framing.structured_design.interim_analysis.planned)


# ---------------------------------------------------------------------------
# 2. Adopt / save / reload / regenerate preserves structured_design
# ---------------------------------------------------------------------------

class StructuredDesignAdoptSaveReloadTests(unittest.TestCase):
    """Structured design facts survive adopt → save → reload → regenerate."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _create_and_generate(self, project_id: str = "proj_test"):
        self.service.create(project_id, _create_request())
        journey = self.service.get(project_id)
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key=f"gen-{project_id}",
        )
        return self.service.generate_prefill(project_id, request)

    def _adopt(
        self,
        project_id: str,
        field_path: str,
        candidate_index: int = 0,
        structured_key: str = "",
        structured_value=None,
        edited_value=None,
        idempotency_key: str = "adopt-001",
    ):
        """Adopt a user decision for *field_path* through the single-candidate
        endpoint's user-edit channel (``candidate_id=""`` + ``edited_value``).

        Corrective round 2: design cards in the deterministic package are
        pending_decision/manual_only scaffolds and are no longer adoptable as
        candidates on this endpoint; the user's explicit value (defaulting to
        the scaffold's suggested value) is recorded as a user_confirmed
        manual edit.
        """
        journey = self.service.get(project_id)
        package = journey.prefill_package
        group = package.field_candidates[field_path]
        if structured_key:
            candidate = next(
                item
                for item in group.candidates
                if isinstance(item.structured_value, dict)
                and item.structured_value.get(structured_key) == structured_value
            )
        else:
            candidate = group.candidates[candidate_index]
        request = AuthoringPrefillAdoptRequest(
            expected_revision=journey.revision,
            expected_package_revision=package.package_revision,
            field_path=field_path,
            candidate_id="",
            edited_value=(
                edited_value
                if edited_value is not None
                else candidate.structured_value
            ),
            actor="medical_manager_test",
            idempotency_key=idempotency_key,
        )
        return self.service.adopt_prefill_candidate(project_id, request)

    def test_adopt_randomization_persists_structured_design_and_survives_reload(self):
        """Adopting design.randomization persists structured_design to SQLite
        and the fact survives a cold reload."""
        self._create_and_generate()
        self._adopt(
            "proj_test",
            field_path="design.randomization",
            edited_value={"mode": "随机", "details": "医学经理确认采用随机分配。"},
        )
        # Cold reload: new service instance reads from same DB.
        reloaded_service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        journey = reloaded_service.get("proj_test")
        framing = journey.study_definition.framing
        self.assertEqual(
            framing.structured_design.randomization_mode, "randomized"
        )

    def test_adopt_interim_analysis_persists_structured_planned_flag(self):
        """Adopting design.interim_analysis persists the structured planned flag."""
        self._create_and_generate()
        self._adopt(
            "proj_test",
            field_path="design.interim_analysis",
            candidate_index=0,
        )
        journey = self.service.get("proj_test")
        framing = journey.study_definition.framing
        # Phase II default candidate has planned=True for phase2_3/phase3.
        # Phase II bucket for "II期" is phase2 → planned=False.
        self.assertIsNotNone(framing.structured_design.interim_analysis.planned)

    def test_adopt_idempotent_replay_does_not_duplicate_structured_design(self):
        """Replaying the same adopt idempotency key with the exact same request
        returns the cached result without double-applying structured_design."""
        self._create_and_generate()
        # Capture the exact package revision before adopt so we can replay
        # with the same request SHA.
        journey = self.service.get("proj_test")
        package = journey.prefill_package
        group = package.field_candidates["design.comparator_type"]
        candidate = group.candidates[0]
        base_request = AuthoringPrefillAdoptRequest(
            expected_revision=journey.revision,
            expected_package_revision=package.package_revision,
            field_path="design.comparator_type",
            # Round 2: user-edit channel (the comparator card is a
            # pending/manual_only scaffold and fails closed).
            candidate_id="",
            edited_value={
                "type": "安慰剂",
                "intervention": "匹配安慰剂，具体用法用量待方案设计确认。",
            },
            actor="medical_manager_test",
            idempotency_key="adopt-comp-idem",
        )
        first = self.service.adopt_prefill_candidate("proj_test", base_request)
        framing_first = first.study_definition.framing
        self.assertEqual(framing_first.structured_design.comparator_type, "placebo")
        # Replay with the exact same request — should return same result.
        second = self.service.adopt_prefill_candidate("proj_test", base_request)
        self.assertEqual(first.revision, second.revision)
        framing_second = second.study_definition.framing
        self.assertEqual(
            framing_second.structured_design.comparator_type, "placebo"
        )

    def test_regenerate_preserves_confirmed_structured_design(self):
        """Force-regenerating the prefill package preserves already-confirmed
        structured_design fields (no silent overwrite)."""
        self._create_and_generate()
        self._adopt(
            "proj_test",
            field_path="design.randomization",
            edited_value={"mode": "随机", "details": "医学经理确认采用随机分配。"},
        )
        journey_before = self.service.get("proj_test")
        confirmed_randomization = (
            journey_before.study_definition.framing.structured_design.randomization_mode
        )
        self.assertEqual(confirmed_randomization, "randomized")
        # Regenerate.
        regen_request = AuthoringPrefillGenerateRequest(
            expected_revision=journey_before.revision,
            actor="medical_manager_test",
            idempotency_key="gen-regen-001",
        )
        updated = self.service.generate_prefill("proj_test", regen_request)
        # The confirmed structured_design must survive.
        framing = updated.study_definition.framing
        self.assertEqual(
            framing.structured_design.randomization_mode, "randomized"
        )


# ---------------------------------------------------------------------------
# 3. Planned true / false / unknown interim behavior
# ---------------------------------------------------------------------------

class InterimAnalysisPlannedStatesTests(unittest.TestCase):
    """Structured interim_analysis.planned drives chapter and synopsis correctly."""

    def test_planned_true_activates_interim_facet_and_synopsis_row(self):
        """When planned=True, the interim chapter appears and synopsis row
        shows structured detail."""
        interim = MedicalWritingInterimAnalysisDesign(
            planned=True,
            purpose="安全性期中分析",
            timing="入组50%时",
            information_fraction="50%",
        )
        structured = MedicalWritingStructuredStudyDesign(
            comparator_type="placebo",
            interim_analysis=interim,
        )
        definition = _build_definition_with_structured(
            structured=structured,
            design_pattern="随机、双盲、安慰剂对照",
        )
        service = MedicalWritingProtocolTemplateService()
        template = service.definition()
        resolutions = {
            r.semantic_node_id: r
            for r in _company_module_resolutions(template, definition)
        }
        interim_res = resolutions.get("statistics.interim")
        self.assertIsNotNone(interim_res)
        self.assertEqual(interim_res.status, "applicable")
        # Synopsis row.
        framing_ns = _build_structured_framing_namespace(
            design_pattern="随机、双盲、安慰剂对照",
            structured=structured,
        )
        picos_ns = SimpleNamespace(statistical_strategy="")
        value = _project_interim_analysis_synopsis_value(framing_ns, picos_ns)
        self.assertIsNotNone(value)
        self.assertIn("安全性期中分析", value)
        self.assertIn("入组50%时", value)

    def test_planned_false_suppresses_interim_chapter_and_synopsis_row(self):
        """When planned=False, the interim chapter is not-applicable and
        synopsis row is omitted."""
        interim = MedicalWritingInterimAnalysisDesign(planned=False)
        structured = MedicalWritingStructuredStudyDesign(
            interim_analysis=interim,
        )
        definition = _build_definition_with_structured(
            structured=structured,
            design_pattern="随机、双盲、安慰剂对照",
            statistical_strategy="不设置正式期中分析。",
        )
        service = MedicalWritingProtocolTemplateService()
        template = service.definition()
        resolutions = {
            r.semantic_node_id: r
            for r in _company_module_resolutions(template, definition)
        }
        interim_res = resolutions.get("statistics.interim")
        self.assertIsNotNone(interim_res)
        self.assertEqual(interim_res.status, "not_applicable")
        # Synopsis row omitted.
        framing_ns = _build_structured_framing_namespace(
            design_pattern="随机、双盲",
            structured=structured,
        )
        picos_ns = SimpleNamespace(statistical_strategy="不设置正式期中分析。")
        value = _project_interim_analysis_synopsis_value(framing_ns, picos_ns)
        self.assertIsNone(value)

    def test_planned_unknown_falls_back_to_legacy_text_detection(self):
        """When planned=None (undecided), facet/synopsis fall back to legacy
        text detection in statistical_strategy / design_pattern."""
        interim = MedicalWritingInterimAnalysisDesign(planned=None)
        structured = MedicalWritingStructuredStudyDesign(
            interim_analysis=interim,
        )
        definition = _build_definition_with_structured(
            structured=structured,
            design_pattern="计划开展期中分析",
            statistical_strategy="将在50%信息分数时进行期中分析。",
        )
        service = MedicalWritingProtocolTemplateService()
        template = service.definition()
        resolutions = {
            r.semantic_node_id: r
            for r in _company_module_resolutions(template, definition)
        }
        interim_res = resolutions.get("statistics.interim")
        self.assertIsNotNone(interim_res)
        self.assertEqual(interim_res.status, "applicable")
        # Synopsis row uses legacy text.
        framing_ns = _build_structured_framing_namespace(
            design_pattern="计划开展期中分析",
            structured=structured,
        )
        picos_ns = SimpleNamespace(
            statistical_strategy="将在50%信息分数时进行期中分析。"
        )
        value = _project_interim_analysis_synopsis_value(framing_ns, picos_ns)
        self.assertIsNotNone(value)
        self.assertIn("50%信息分数", value)

    def test_planned_false_clears_detail_fields_via_validator(self):
        """The Pydantic validator clears detail fields when planned=False."""
        interim = MedicalWritingInterimAnalysisDesign(
            planned=False,
            purpose="should be cleared",
            timing="should be cleared",
        )
        self.assertEqual(interim.purpose, "")
        self.assertEqual(interim.timing, "")


# ---------------------------------------------------------------------------
# 4. Synopsis row detail prefers structured facts
# ---------------------------------------------------------------------------

class SynopsisStructuredProjectionTests(unittest.TestCase):
    """The synopsis '研究设计' row prefers structured_design facts."""

    def test_structured_design_synopsis_prefers_decided_fields(self):
        """When structured fields are decided, synopsis shows them, not legacy text."""
        structured = MedicalWritingStructuredStudyDesign(
            randomization_mode="randomized",
            blinding_mode="double_blind",
            comparator_type="placebo",
            assignment_model="平行分组",
            center_model="多中心",
        )
        framing = _build_structured_framing_namespace(
            design_pattern="legacy text that should not appear",
            structured=structured,
        )
        text = _project_structured_design_synopsis_text(framing)
        self.assertIn("随机化", text)
        self.assertIn("双盲", text)
        self.assertIn("安慰剂对照", text)
        self.assertIn("平行分组", text)
        self.assertIn("多中心", text)
        self.assertNotIn("legacy text", text)

    def test_structured_design_synopsis_falls_back_to_legacy_when_undecided(self):
        """When all structured fields are undecided, synopsis uses design_pattern."""
        structured = MedicalWritingStructuredStudyDesign()
        framing = _build_structured_framing_namespace(
            design_pattern="随机、双盲、安慰剂对照",
            structured=structured,
        )
        text = _project_structured_design_synopsis_text(framing)
        self.assertEqual(text, "随机、双盲、安慰剂对照")

    def test_dict_synopsis_design_row_prefers_structured(self):
        """The dict-based synopsis renderer also prefers structured_design."""
        framing = {
            "design_pattern": "legacy",
            "structured_design": {
                "randomization_mode": "randomized",
                "blinding_mode": "double_blind",
                "comparator_type": "active",
                "comparator_intervention": "甲氨蝶呤",
            },
        }
        text = _project_design_synopsis_from_dict(framing)
        self.assertIn("随机化", text)
        self.assertIn("双盲", text)
        self.assertIn("活性对照", text)
        self.assertIn("甲氨蝶呤", text)

    def test_dict_synopsis_interim_planned_true_shows_detail(self):
        """Dict synopsis interim row shows structured detail when planned=True."""
        framing = {
            "structured_design": {
                "interim_analysis": {
                    "planned": True,
                    "purpose": "安全性期中",
                    "timing": "入组50%",
                }
            }
        }
        picos = {"statistical_strategy": "legacy stats text"}
        text = _project_interim_synopsis_from_dict(framing, picos)
        self.assertIn("安全性期中", text)
        self.assertIn("入组50%", text)
        self.assertNotIn("legacy stats text", text)

    def test_dict_synopsis_interim_planned_false_omits_row(self):
        """Dict synopsis omits interim row when planned=False."""
        framing = {
            "structured_design": {
                "interim_analysis": {"planned": False}
            }
        }
        picos = {"statistical_strategy": "legacy stats with 期中分析 text"}
        text = _project_interim_synopsis_from_dict(framing, picos)
        self.assertEqual(text, "")

    def test_render_protocol_synopsis_includes_interim_row_when_planned(self):
        """Full synopsis render includes the interim row when structured planned=True."""
        framing = {
            "document_title": "Test",
            "study_phase": "III期",
            "design_pattern": "随机",
            "structured_design": {
                "interim_analysis": {
                    "planned": True,
                    "purpose": "有效性期中分析",
                }
            },
        }
        picos = {"statistical_strategy": ""}
        result = _render_protocol_synopsis(framing, picos)
        self.assertIn("期中分析", result)
        self.assertIn("有效性期中分析", result)


# ---------------------------------------------------------------------------
# 5. Chapter source facts bind to framing.structured_design
# ---------------------------------------------------------------------------

class ChapterSourceFactsBindingTests(unittest.TestCase):
    """Chapter source_fact_ids correctly reference framing.structured_design."""

    def test_interim_chapter_source_facts_include_structured_design(self):
        """The statistics.interim chapter binds source facts to framing.structured_design."""
        service = MedicalWritingProtocolTemplateService()
        template = service.definition()
        interim_node = None
        for node in template.nodes:
            if node.semantic_node_id == "statistics.interim":
                interim_node = node
                break
        self.assertIsNotNone(interim_node)
        # The applicability rules should include feature:interim_analysis.
        self.assertIn("feature:interim_analysis", interim_node.applicability_rules)
        # Source fact paths should include framing.structured_design.
        definition = _build_definition_with_structured(
            structured=MedicalWritingStructuredStudyDesign(
                interim_analysis=MedicalWritingInterimAnalysisDesign(planned=True)
            )
        )
        resolutions = {
            r.semantic_node_id: r
            for r in _company_module_resolutions(template, definition)
        }
        interim_res = resolutions["statistics.interim"]
        self.assertEqual(interim_res.status, "applicable")
        # Source fact IDs should reference the definition prefix + framing.structured_design.
        fact_ids_str = " ".join(interim_res.source_fact_ids)
        self.assertIn("framing.structured_design", fact_ids_str)

    def test_randomization_chapter_source_facts_include_structured_design(self):
        """The study_design.randomization chapter binds to framing.structured_design."""
        service = MedicalWritingProtocolTemplateService()
        template = service.definition()
        rand_node = None
        for node in template.nodes:
            if node.semantic_node_id == "study_design.randomization":
                rand_node = node
                break
        self.assertIsNotNone(rand_node)
        definition = _build_definition_with_structured(
            structured=MedicalWritingStructuredStudyDesign(
                randomization_mode="randomized"
            )
        )
        resolutions = {
            r.semantic_node_id: r
            for r in _company_module_resolutions(template, definition)
        }
        rand_res = resolutions["study_design.randomization"]
        fact_ids_str = " ".join(rand_res.source_fact_ids)
        self.assertIn("framing.structured_design", fact_ids_str)


# ---------------------------------------------------------------------------
# 6. Active comparator authority: no second regimen truth source
# ---------------------------------------------------------------------------

class ActiveComparatorAuthorityTests(unittest.TestCase):
    """Active comparator existence lives in structured_design; regimen details
    live only in the existing IP regimen with product_role=active_comparator."""

    def test_structured_design_active_comparator_does_not_define_regimen_details(self):
        """structured_design.comparator_type=active only declares existence;
        drug/dose/route/frequency belong to IP regimen."""
        structured = MedicalWritingStructuredStudyDesign(
            comparator_type="active",
            comparator_intervention="甲氨蝶呤片",
        )
        # The structured design must NOT have regimen fields like dose, route, frequency.
        self.assertFalse(hasattr(structured, "dose"))
        self.assertFalse(hasattr(structured, "route"))
        self.assertFalse(hasattr(structured, "frequency"))
        self.assertFalse(hasattr(structured, "treatment_period"))

    def test_active_comparator_regimen_uses_existing_ip_regimen_model(self):
        """The IP regimen model already supports product_role=active_comparator."""
        regimen = MedicalWritingInterventionIpRegimen(
            regimen_id="ip_comparator_001",
            product_name="甲氨蝶呤片",
            product_role=InterventionRulesProductRole.ACTIVE_COMPARATOR,
            dose_and_frequency="每周一次7.5mg口服",
            route="口服",
            treatment_period="全程24周",
        )
        rules = MedicalWritingInterventionRules(
            ip_regimens=[
                MedicalWritingInterventionIpRegimen(
                    regimen_id="ip_test_001",
                    product_role=InterventionRulesProductRole.INVESTIGATIONAL_PRODUCT,
                ),
                regimen,
            ]
        )
        # Verify both regimens coexist in the single authority model.
        roles = [r.product_role for r in rules.ip_regimens]
        self.assertIn(InterventionRulesProductRole.INVESTIGATIONAL_PRODUCT, roles)
        self.assertIn(InterventionRulesProductRole.ACTIVE_COMPARATOR, roles)

    def test_prefill_active_comparator_candidate_has_bridge_limitation(self):
        """The active comparator prefill candidate warns that regimen details
        belong to the IP regimen authority, not structured_design."""
        # Simulate the adoption mapping for active comparator.
        framing_payload = {
            "design_pattern": "",
            "structured_design": {
                "schema_version": "medical_writing_structured_study_design_v1"
            },
        }
        picos_payload: dict = {}
        framing_updates, picos_updates, changed = map_design_adoption_to_study_updates(
            "design.comparator_type",
            {"type": "活性对照", "intervention": "甲氨蝶呤"},
            framing_payload=framing_payload,
            picos_payload=picos_payload,
        )
        # structured_design.comparator_type is set to active.
        sd = framing_updates["structured_design"]
        self.assertEqual(sd["comparator_type"], "active")
        self.assertEqual(sd["comparator_intervention"], "甲氨蝶呤")
        # picos.comparator_summary is a text pointer, not regimen detail.
        self.assertIn("甲氨蝶呤", picos_updates["comparator_summary"])
        # structured_design must NOT contain dose/route/frequency keys.
        for regimen_field in ("dose", "route", "frequency", "treatment_period"):
            self.assertNotIn(regimen_field, sd)


# ---------------------------------------------------------------------------
# 7. Complex background therapy uses existing non-IP background-rule authority
# ---------------------------------------------------------------------------

class ComplexBackgroundTherapyTests(unittest.TestCase):
    """Background/rescue/stable-dose/prohibited therapy rules live in the
    existing structured intervention rules, not structured_design."""

    def test_background_therapy_uses_existing_non_ip_rule_model(self):
        """Complex background therapy (e.g. RA stable-dose MTX) uses the
        existing non-IP rule with ALLOWED_IF_STABLE policy."""
        bg_rule = MedicalWritingInterventionNonIpTreatmentRule(
            rule_id="bg_mtx_001",
            rule_class=InterventionRulesNonIpRuleClass.BACKGROUND,
            policy=InterventionRulesNonIpPolicy.ALLOWED_IF_STABLE,
            agent_or_category="甲氨蝶呤",
            washout_or_window="筛选前稳定剂量≥12周",
        )
        rescue_rule = MedicalWritingInterventionNonIpTreatmentRule(
            rule_id="rescue_001",
            rule_class=InterventionRulesNonIpRuleClass.RESCUE,
            policy=InterventionRulesNonIpPolicy.RESCUE_POLICY,
            agent_or_category="补救治疗",
        )
        rules = MedicalWritingInterventionRules(
            non_ip_treatment_rules=[bg_rule, rescue_rule],
            authority="structured",
        )
        # The two rules coexist in the single authority model.
        bg_rules = [
            r
            for r in rules.non_ip_treatment_rules
            if r.rule_class == InterventionRulesNonIpRuleClass.BACKGROUND
        ]
        self.assertEqual(len(bg_rules), 1)
        self.assertEqual(bg_rules[0].policy, InterventionRulesNonIpPolicy.ALLOWED_IF_STABLE)
        rescue_rules = [
            r
            for r in rules.non_ip_treatment_rules
            if r.rule_class == InterventionRulesNonIpRuleClass.RESCUE
        ]
        self.assertEqual(len(rescue_rules), 1)

    def test_structured_design_has_no_background_therapy_fields(self):
        """structured_design must NOT duplicate background therapy rule fields."""
        structured = MedicalWritingStructuredStudyDesign()
        # No background, rescue, stable-dose, or concomitant therapy fields.
        for field in (
            "background_therapy",
            "rescue_therapy",
            "stable_dose_window",
            "prohibited_concomitant",
            "allowed_concomitant",
        ):
            self.assertFalse(hasattr(structured, field))

    def test_structured_design_other_notes_can_mention_background_without_duplicating(self):
        """other_design_notes can mention complex background requirements as a
        design overview without duplicating intervention rule authority."""
        structured = MedicalWritingStructuredStudyDesign(
            other_design_notes="复杂背景治疗要求，详见干预规则。"
        )
        self.assertIn("复杂背景治疗", structured.other_design_notes)
        # The note is a free-text pointer; actual rules live elsewhere.
        self.assertFalse(hasattr(structured, "background_rules"))


if __name__ == "__main__":
    unittest.main()
