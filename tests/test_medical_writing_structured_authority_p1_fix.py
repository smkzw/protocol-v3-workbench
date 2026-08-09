from __future__ import annotations

import copy
import hashlib
import io
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from xml.etree import ElementTree

from packages.contracts.workbench_contracts import (
    InterventionRulesAuthority,
    InterventionRulesNonIpRuleClass,
    InterventionRulesProductRole,
    MedicalWritingGreenfieldCreateRequest,
    MedicalWritingInterimAnalysisDesign,
    MedicalWritingInterventionRules,
    MedicalWritingStudyFactState,
    MedicalWritingStructuredStudyDesign,
)
from services.api.app.medical_writing_authoring_prefill import (
    map_design_adoption_to_study_updates,
    _materialize_active_comparator_ip_regimen,
    _materialize_background_non_ip_rules,
    _intervention_rules_to_legacy_projection,
)
from services.api.app.medical_writing_protocol_template import (
    DRAFT_TEMPLATE_VERSION,
    M11_TEMPLATE_ID,
    MedicalWritingProtocolTemplateService,
    TEMPLATE_ID,
    TEMPLATE_VERSION,
)

WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _heading_texts_from_ooxml(content: bytes) -> list[str]:
    """Extract all heading text from word/document.xml."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    headings: list[str] = []
    for para in root.findall(".//w:p", WORD_NS):
        style = para.find(".//w:pStyle", WORD_NS)
        if style is not None:
            val = style.get(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val",
                "",
            )
            if val.startswith("Heading"):
                text = "".join(
                    (t.text or "")
                    for t in para.findall(".//w:t", WORD_NS)
                ).strip()
                if text:
                    headings.append(text)
    return headings


def _make_definition(
    *,
    interim_planned: bool | None = None,
    design_pattern: str = "随机、双盲、安慰剂对照",
) -> SimpleNamespace:
    return SimpleNamespace(
        definition_id="mwdef_struct_auth_test",
        revision=1,
        state_sha256="a" * 64,
        synopsis_text="结构化研究摘要",
        framing=SimpleNamespace(
            study_phase="III期",
            document_title="结构化权限测试方案",
            investigational_product="CMS-TEST",
            design_pattern=design_pattern,
            population_intent="目标研究人群",
            intrinsic_objectives=["剂量探索"],
            product_profile=SimpleNamespace(
                technology_type="small_molecule",
                administration_routes=["口服"],
                dosage_forms=["片剂"],
                immunogenicity_relevance="not_expected",
                safety_considerations=[],
                pk_pd_considerations=[],
            ),
            structured_design=MedicalWritingStructuredStudyDesign(
                randomization_mode="randomized",
                blinding_mode="double_blind",
                comparator_type="placebo",
                comparator_intervention="",
                interim_analysis=MedicalWritingInterimAnalysisDesign(
                    planned=interim_planned
                ),
            ),
        ),
        picos=SimpleNamespace(
            design_archetype="",
            population_summary="目标研究人群",
            inclusion_modules=[],
            exclusion_modules=[],
            intervention_summary="试验药物方案",
            intervention_dose_regimen="每日一次口服给药",
            allowed_concomitant_rules=[],
            required_background_rules=[],
            prohibited_concomitant_rules=[],
            comparator_summary="安慰剂",
            primary_endpoint="主要终点及评价时间",
            key_secondary_endpoints=[],
            other_secondary_endpoints=[],
            exploratory_endpoints=[],
            safety_endpoints=["安全性"],
            aesi_definitions=[],
            assessment_instruments=[],
            sample_size_strategy="计划入组约120例参与者。",
            statistical_strategy="采用预先规定的统计分析集进行分析。",
        ),
        field_states={
            "framing.design_pattern": MedicalWritingStudyFactState(
                status="confirmed"
            ),
            "picos.intervention_summary": MedicalWritingStudyFactState(
                status="confirmed"
            ),
            "picos.comparator_summary": MedicalWritingStudyFactState(
                status="confirmed"
            ),
            "picos.primary_endpoint": MedicalWritingStudyFactState(
                status="confirmed"
            ),
        },
    )


class InterimAnalysisHeadingTests(unittest.TestCase):
    """Defect 1: dynamic chapter construction for interim_analysis."""

    def setUp(self):
        self.service = MedicalWritingProtocolTemplateService()

    def test_phase1_false_m11_template_has_zero_interim_headings_in_section_seeds(self):
        """When planned=False, M11 template section seeds contain zero 期中分析 nodes."""
        definition = _make_definition(interim_planned=False)
        m11 = self.service.definition(M11_TEMPLATE_ID, DRAFT_TEMPLATE_VERSION)
        seeds = self.service.section_seeds(definition, m11)
        interim_headings = [s for s in seeds if "期中分析" in s.heading]
        self.assertEqual(0, len(interim_headings))

    def test_phase3_true_m11_template_still_contains_interim_content(self):
        """When planned=True, M11 template section seeds retain interim content."""
        definition = _make_definition(interim_planned=True)
        m11 = self.service.definition(M11_TEMPLATE_ID, DRAFT_TEMPLATE_VERSION)
        seeds = self.service.section_seeds(definition, m11)
        interim_headings = [s for s in seeds if "期中分析" in s.heading]
        self.assertEqual(2, len(interim_headings))
        headings_text = [s.heading for s in interim_headings]
        self.assertIn("期中分析的依据", headings_text)
        self.assertIn("期中分析", headings_text)

    def test_phase1_false_company_template_has_zero_interim_headings(self):
        """Company template also omits interim when planned=False."""
        definition = _make_definition(interim_planned=False)
        company = self.service.definition(TEMPLATE_ID, TEMPLATE_VERSION)
        seeds = self.service.section_seeds(definition, company)
        interim_headings = [s for s in seeds if "期中分析" in s.heading]
        self.assertEqual(0, len(interim_headings))

    def test_phase1_false_m11_module_resolutions_mark_interim_as_not_applicable(self):
        definition = _make_definition(interim_planned=False)
        m11 = self.service.definition(M11_TEMPLATE_ID, DRAFT_TEMPLATE_VERSION)
        resolutions = self.service.module_resolutions(definition, m11)
        # M11 nodes for 4.2.6 and 10.9 have applicability_rules.
        interim_resolutions = [
            r for r in resolutions
            if r.template_node_id in ("ich_m11_4_2_6", "ich_m11_10_9")
        ]
        self.assertGreater(len(interim_resolutions), 0)
        for r in interim_resolutions:
            self.assertEqual("omit", r.render_action)


class ActiveComparatorRegimenTests(unittest.TestCase):
    """Defect 2: active-comparator IP regimen materialization."""

    def test_active_comparator_adoption_creates_exactly_one_ip_regimen(self):
        framing_payload = {"design_pattern": "", "structured_design": {}}
        picos_payload = {}
        _, picos_updates, changed = map_design_adoption_to_study_updates(
            "design.comparator_type",
            {"type": "活性对照", "intervention": "Dupixent"},
            framing_payload=framing_payload,
            picos_payload=picos_payload,
        )
        rules = picos_updates["intervention_rules"]
        active_regimens = [
            r for r in rules["ip_regimens"]
            if r["product_role"] == "active_comparator"
        ]
        self.assertEqual(1, len(active_regimens))
        self.assertEqual("active_comparator_regimen", active_regimens[0]["regimen_id"])
        self.assertEqual("Dupixent", active_regimens[0]["product_name"])
        self.assertEqual("structured", rules["authority"])

    def test_comparator_details_come_from_explicit_candidate_not_generic_ip(self):
        framing_payload = {"design_pattern": "", "structured_design": {}}
        picos_payload = {
            "intervention_dose_regimen": "TEST_IP_DOSE every day"
        }
        _, picos_updates, _ = map_design_adoption_to_study_updates(
            "design.comparator_type",
            {
                "type": "活性对照",
                "intervention": "ActiveDrug",
                "dose_and_frequency": "600mg Q4W",
                "route": "皮下注射",
                "treatment_period": "24周",
            },
            framing_payload=framing_payload,
            picos_payload=picos_payload,
        )
        rules = picos_updates["intervention_rules"]
        active = next(
            r for r in rules["ip_regimens"]
            if r["product_role"] == "active_comparator"
        )
        self.assertEqual("600mg Q4W", active["dose_and_frequency"])
        self.assertEqual("皮下注射", active["route"])
        self.assertEqual("24周", active["treatment_period"])
        # Comparator details must NOT come from generic IP free text.
        self.assertNotIn("TEST_IP_DOSE", active["dose_and_frequency"])

    def test_comparator_details_absent_from_structured_design_regimen_fields(self):
        framing_payload = {"design_pattern": "", "structured_design": {}}
        picos_payload = {}
        framing_updates, picos_updates, _ = map_design_adoption_to_study_updates(
            "design.comparator_type",
            {
                "type": "活性对照",
                "intervention": "ActiveDrug",
                "dose_and_frequency": "300mg Q2W",
                "route": "静脉输注",
                "treatment_period": "12周",
            },
            framing_payload=framing_payload,
            picos_payload=picos_payload,
        )
        sd = framing_updates["structured_design"]
        # Structured design only holds the identity, not the regimen details.
        self.assertEqual("active", sd["comparator_type"])
        self.assertEqual("ActiveDrug", sd["comparator_intervention"])
        self.assertNotIn("dose_and_frequency", sd)
        self.assertNotIn("route", sd)
        self.assertNotIn("treatment_period", sd)

    def test_placebo_adoption_clears_active_comparator_regimen(self):
        framing_payload = {"design_pattern": "", "structured_design": {}}
        picos_payload = {
            "intervention_rules": {
                "schema_version": "medical_writing_intervention_rules_v1",
                "authority": "structured",
                "ip_regimens": [
                    {
                        "regimen_id": "active_comparator_regimen",
                        "product_name": "OldDrug",
                        "product_role": "active_comparator",
                    }
                ],
                "non_ip_treatment_rules": [],
                "ip_action_rules": [],
                "cross_object_links": [],
            }
        }
        _, picos_updates, _ = map_design_adoption_to_study_updates(
            "design.comparator_type",
            {"type": "安慰剂", "intervention": ""},
            framing_payload=framing_payload,
            picos_payload=picos_payload,
        )
        rules = picos_updates["intervention_rules"]
        active = [
            r for r in rules["ip_regimens"]
            if r["product_role"] == "active_comparator"
        ]
        self.assertEqual(0, len(active))

    def test_comparator_adoption_is_idempotent(self):
        """Adopting the same active comparator twice produces the same result."""
        framing_payload = {"design_pattern": "", "structured_design": {}}
        base_picos = {}
        _, picos_updates_1, _ = map_design_adoption_to_study_updates(
            "design.comparator_type",
            {"type": "活性对照", "intervention": "DrugA"},
            framing_payload=framing_payload,
            picos_payload=base_picos,
        )
        rules_1 = picos_updates_1["intervention_rules"]
        # Second adoption from the updated state.
        _, picos_updates_2, _ = map_design_adoption_to_study_updates(
            "design.comparator_type",
            {"type": "活性对照", "intervention": "DrugA"},
            framing_payload=framing_payload,
            picos_payload={"intervention_rules": rules_1},
        )
        rules_2 = picos_updates_2["intervention_rules"]
        active_1 = [r for r in rules_1["ip_regimens"] if r["product_role"] == "active_comparator"]
        active_2 = [r for r in rules_2["ip_regimens"] if r["product_role"] == "active_comparator"]
        self.assertEqual(len(active_1), len(active_2))
        self.assertEqual(active_1[0]["regimen_id"], active_2[0]["regimen_id"])
        self.assertEqual(active_1[0]["product_name"], active_2[0]["product_name"])


class BackgroundRulesTests(unittest.TestCase):
    """Defect 3: structured BACKGROUND non-IP rules."""

    def test_background_strings_create_exactly_one_background_rule_each(self):
        picos_payload = {}
        rules = _materialize_background_non_ip_rules(
            ["允许使用口服抗组胺药", "筛选期前14天稳定使用外用润肤剂"],
            picos_payload=picos_payload,
        )
        bg_rules = [
            r for r in rules["non_ip_treatment_rules"]
            if r["rule_class"] == "background"
        ]
        self.assertEqual(2, len(bg_rules))
        self.assertEqual("background_001", bg_rules[0]["rule_id"])
        self.assertEqual("background_002", bg_rules[1]["rule_id"])
        self.assertEqual("允许使用口服抗组胺药", bg_rules[0]["agent_or_category"])

    def test_background_rules_preserve_source_meaning_losslessly(self):
        text = "受试者在整个研究期间须持续使用指定方案的非药物保湿剂。"
        rules = _materialize_background_non_ip_rules([text], picos_payload={})
        bg = next(
            r for r in rules["non_ip_treatment_rules"]
            if r["rule_class"] == "background"
        )
        self.assertEqual(text, bg["agent_or_category"])

    def test_cm_rescue_dose_adjustment_background_remain_disjoint(self):
        """CM, background, rescue, and dose adjustment must be separate classes."""
        picos_payload = {
            "intervention_rules": {
                "schema_version": "medical_writing_intervention_rules_v1",
                "authority": "structured",
                "ip_regimens": [],
                "ip_action_rules": [
                    {
                        "rule_id": "ip_action_001",
                        "action_kind": "temporary_interruption",
                    }
                ],
                "non_ip_treatment_rules": [
                    {
                        "rule_id": "allowed_cm_001",
                        "rule_class": "allowed_cm",
                        "agent_or_category": "对乙酰氨基酚",
                    },
                    {
                        "rule_id": "prohibited_cm_001",
                        "rule_class": "prohibited_cm",
                        "agent_or_category": "免疫抑制剂",
                    },
                    {
                        "rule_id": "rescue_001",
                        "rule_class": "rescue",
                        "agent_or_category": "紧急使用全身糖皮质激素",
                    },
                ],
                "cross_object_links": [],
            }
        }
        rules = _materialize_background_non_ip_rules(
            ["稳定使用润肤剂"],
            picos_payload=picos_payload,
        )
        non_ip = rules["non_ip_treatment_rules"]
        classes = {r["rule_class"] for r in non_ip}
        # Each class is distinct; no cross-contamination.
        self.assertIn("background", classes)
        self.assertIn("allowed_cm", classes)
        self.assertIn("prohibited_cm", classes)
        self.assertIn("rescue", classes)
        # Background rule count is exactly 1.
        bg_count = sum(1 for r in non_ip if r["rule_class"] == "background")
        self.assertEqual(1, bg_count)
        # Existing non-background rules preserved.
        cm = [r for r in non_ip if r["rule_class"] == "allowed_cm"]
        self.assertEqual(1, len(cm))
        self.assertEqual("对乙酰氨基酚", cm[0]["agent_or_category"])

    def test_background_adoption_via_picos_path_materializes_rules(self):
        framing_payload = {}
        picos_payload = {}
        _, picos_updates, changed = map_design_adoption_to_study_updates(
            "picos.required_background_rules",
            ["允许使用润肤剂", "可使用口服抗组胺药"],
            framing_payload=framing_payload,
            picos_payload=picos_payload,
        )
        self.assertIn("picos.intervention_rules", changed)
        rules = picos_updates["intervention_rules"]
        self.assertEqual("structured", rules["authority"])
        bg = [r for r in rules["non_ip_treatment_rules"] if r["rule_class"] == "background"]
        self.assertEqual(2, len(bg))


class LegacyProjectionAndIdempotencyTests(unittest.TestCase):
    """Defects 4-5: authority=structured, legacy projection, idempotency."""

    def test_intervention_rules_authority_set_to_structured(self):
        framing_payload = {"design_pattern": "", "structured_design": {}}
        picos_payload = {}
        _, picos_updates, _ = map_design_adoption_to_study_updates(
            "design.comparator_type",
            {"type": "活性对照", "intervention": "DrugX"},
            framing_payload=framing_payload,
            picos_payload=picos_payload,
        )
        rules = picos_updates["intervention_rules"]
        self.assertEqual(
            InterventionRulesAuthority.STRUCTURED.value,
            rules["authority"],
        )

    def test_legacy_projection_is_deterministic(self):
        """project_legacy_intervention_fields produces deterministic output."""
        from packages.contracts.workbench_contracts import (
            MedicalWritingPicosDefinition,
        )
        rules = {
            "schema_version": "medical_writing_intervention_rules_v1",
            "authority": "structured",
            "ip_regimens": [
                {
                    "regimen_id": "active_comparator_regimen",
                    "product_name": "DrugA",
                    "product_role": "active_comparator",
                    "dose_and_frequency": "600mg Q4W",
                    "route": "皮下注射",
                    "treatment_period": "24周",
                }
            ],
            "ip_action_rules": [],
            "non_ip_treatment_rules": [
                {
                    "rule_id": "background_001",
                    "rule_class": "background",
                    "agent_or_category": "润肤剂",
                }
            ],
            "cross_object_links": [],
        }
        proj1 = _intervention_rules_to_legacy_projection(rules)
        proj2 = _intervention_rules_to_legacy_projection(rules)
        self.assertEqual(proj1, proj2)
        self.assertIn("DrugA", proj1["intervention_dose_regimen"])
        self.assertEqual(["润肤剂"], proj1["required_background_rules"])

    def test_save_reload_regenerate_is_idempotent(self):
        """Materializing background rules twice produces identical results."""
        strings = ["规则A", "规则B"]
        rules_1 = _materialize_background_non_ip_rules(
            strings, picos_payload={},
        )
        rules_2 = _materialize_background_non_ip_rules(
            strings, picos_payload={},
        )
        self.assertEqual(rules_1, rules_2)

    def test_legacy_payload_from_legacy_fields_is_idempotent(self):
        """from_legacy_fields produces the same result on repeated calls."""
        rules_1 = MedicalWritingInterventionRules.from_legacy_fields(
            intervention_dose_regimen="每日口服",
            required_background_rules=["润肤剂", "抗组胺药"],
            allowed_concomitant_rules=["对乙酰氨基酚"],
            prohibited_concomitant_rules=["免疫抑制剂"],
        )
        rules_2 = MedicalWritingInterventionRules.from_legacy_fields(
            intervention_dose_regimen="每日口服",
            required_background_rules=["润肤剂", "抗组胺药"],
            allowed_concomitant_rules=["对乙酰氨基酚"],
            prohibited_concomitant_rules=["免疫抑制剂"],
        )
        self.assertEqual(
            rules_1.model_dump(mode="json"),
            rules_2.model_dump(mode="json"),
        )
        # Verify class disjointness.
        classes = {r.rule_class for r in rules_1.non_ip_treatment_rules}
        self.assertIn(InterventionRulesNonIpRuleClass.BACKGROUND, classes)
        self.assertIn(InterventionRulesNonIpRuleClass.ALLOWED_CM, classes)
        self.assertIn(InterventionRulesNonIpRuleClass.PROHIBITED_CM, classes)
        # Verify the IP regimen is investigational_product (not active_comparator).
        self.assertEqual(1, len(rules_1.ip_regimens))
        self.assertEqual(
            InterventionRulesProductRole.INVESTIGATIONAL_PRODUCT,
            rules_1.ip_regimens[0].product_role,
        )


if __name__ == "__main__":
    unittest.main()
