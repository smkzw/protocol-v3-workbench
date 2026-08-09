from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace

from packages.contracts.workbench_contracts import (
    MedicalWritingStudyFactState,
)
from services.api.app.medical_writing_protocol_template import (
    TEMPLATE_ID,
    TEMPLATE_VERSION,
    MedicalWritingProtocolTemplateService,
)


class MedicalWritingChapterProjectionTests(unittest.TestCase):
    """Tests for deterministic projection of confirmed StudyDefinition facts
    into chapter body drafts, and for empty-chapter governance.

    These tests verify success criteria 4-6 of the
    mw_dynamic_chapter_projection_20260720 context:

    - SC4: required core nodes with no confirmed fact carry an explicit
      ``待补充`` drafting state rather than a clinically invented paragraph.
    - SC5: confirmed facts project to relevant body nodes without changing
      their numeric values, groups, time points, endpoint hierarchy,
      uncertainty, or source fact IDs.
    - SC6: synopsis, body, module resolution, and section selection use the
      same deterministic applicability decision.
    """

    def setUp(self):
        self.service = MedicalWritingProtocolTemplateService()

    # -- SC5: confirmed facts project verbatim to relevant body nodes ----

    def test_confirmed_primary_endpoint_projects_to_statistics_efficacy(self):
        definition = self._definition()
        definition.field_states["picos.primary_endpoint"] = (
            MedicalWritingStudyFactState(status="confirmed")
        )
        definition.field_states["picos.statistical_strategy"] = (
            MedicalWritingStudyFactState(status="confirmed")
        )
        seeds = self.service.section_seeds(definition)
        stats_efficacy = self._seed(seeds, "cms_statistics_efficacy")
        self.assertIn("主要终点及评价时间", stats_efficacy.initial_text)
        self.assertIn("采用预先规定的统计分析集进行分析。", stats_efficacy.initial_text)
        self.assertIn(
            "study_definition:mwdef_test:r3:picos.primary_endpoint",
            stats_efficacy.source_fact_ids,
        )
        self.assertIn(
            "study_definition:mwdef_test:r3:picos.statistical_strategy",
            stats_efficacy.source_fact_ids,
        )

    def test_confirmed_inclusion_modules_project_verbatim_to_population_inclusion(self):
        definition = self._definition()
        definition.picos.inclusion_modules = [
            "年龄18至65岁",
            "体重指数≥18且≤30",
        ]
        definition.field_states["picos.inclusion_modules"] = (
            MedicalWritingStudyFactState(status="confirmed")
        )
        seeds = self.service.section_seeds(definition)
        inclusion = self._seed(seeds, "cms_population_inclusion")
        self.assertIn("年龄18至65岁", inclusion.initial_text)
        self.assertIn("体重指数≥18且≤30", inclusion.initial_text)
        self.assertEqual(
            ["study_definition:mwdef_test:r3:picos.inclusion_modules"],
            inclusion.source_fact_ids,
        )

    def test_confirmed_regimen_projects_verbatim_without_numeric_transformation(self):
        definition = self._definition()
        definition.picos.intervention_dose_regimen = "50 mg每日一次口服给药"
        definition.field_states["picos.intervention_summary"] = (
            MedicalWritingStudyFactState(status="confirmed")
        )
        definition.field_states["picos.intervention_dose_regimen"] = (
            MedicalWritingStudyFactState(status="confirmed")
        )
        seeds = self.service.section_seeds(definition)
        regimen = self._seed(seeds, "cms_intervention_regimen")
        self.assertIn("试验药物方案", regimen.initial_text)
        self.assertIn("50 mg每日一次口服给药", regimen.initial_text)
        self.assertIn(
            "study_definition:mwdef_test:r3:picos.intervention_summary",
            regimen.source_fact_ids,
        )
        self.assertIn(
            "study_definition:mwdef_test:r3:picos.intervention_dose_regimen",
            regimen.source_fact_ids,
        )

    def test_unconfirmed_fields_are_not_projected(self):
        definition = self._definition()
        seeds = self.service.section_seeds(definition)
        aesi = self._seed_or_none(seeds, "cms_safety_aesi")
        if aesi is not None:
            self.assertNotIn("待补充", aesi.initial_text)
            self.assertEqual([], aesi.source_fact_ids)

    # -- SC4: required core nodes carry explicit drafting state ----------

    def test_required_core_node_without_confirmed_fact_carries_drafting_state(self):
        definition = self._definition()
        seeds = self.service.section_seeds(definition)
        background_disease = self._seed(seeds, "cms_background_disease")
        self.assertIn("待补充", background_disease.initial_text)
        self.assertEqual([], background_disease.source_fact_ids)
        # objectives_endpoints.primary has picos.primary_endpoint confirmed in
        # the base fixture, so it projects real text, not 待补充. A required
        # core node that has zero confirmed mapped fields is the one that
        # carries the drafting-state placeholder. statistics.sample_size has
        # picos.sample_size_strategy unconfirmed in the base fixture.
        sample_size = self._seed(seeds, "cms_statistics_sample_size")
        self.assertIn("待补充", sample_size.initial_text)
        self.assertEqual([], sample_size.source_fact_ids)

    def test_required_core_node_gets_real_text_once_fact_is_confirmed(self):
        definition = self._definition()
        definition.framing.indication = "中重度特应性皮炎"
        definition.field_states["framing.indication"] = (
            MedicalWritingStudyFactState(status="confirmed")
        )
        seeds = self.service.section_seeds(definition)
        background_disease = self._seed(seeds, "cms_background_disease")
        self.assertNotIn("待补充", background_disease.initial_text)
        self.assertIn("中重度特应性皮炎", background_disease.initial_text)
        self.assertEqual(
            ["study_definition:mwdef_test:r3:framing.indication"],
            background_disease.source_fact_ids,
        )

    def test_glossary_and_front_matter_do_not_get_drafting_placeholders(self):
        definition = self._definition()
        seeds = self.service.section_seeds(definition)
        glossary = self._seed(seeds, "cms_glossary")
        self.assertEqual("", glossary.initial_text)
        front_matter = self._seed(seeds, "cms_front_matter")
        self.assertEqual("", front_matter.initial_text)

    # -- SC6: synopsis, body, and module resolution share applicability --

    def test_module_resolution_and_section_seeds_share_applicability(self):
        definition = self._definition()
        seeds = self.service.section_seeds(definition)
        resolutions = {
            r.semantic_node_id: r
            for r in self.service.module_resolutions(definition)
        }
        seed_keys = {s.template_node_id for s in seeds}
        for semantic_id, resolution in resolutions.items():
            node_id = resolution.template_node_id
            if resolution.render_action == "omit":
                self.assertNotIn(
                    node_id,
                    seed_keys,
                    f"omitted module {semantic_id} must not appear in section seeds",
                )
            else:
                self.assertIn(
                    node_id,
                    seed_keys,
                    f"retained module {semantic_id} must appear in section seeds",
                )

    def test_not_applicable_aesi_shows_retain_not_applicable_in_seed(self):
        definition = self._definition()
        definition.field_states["picos.aesi_definitions"] = (
            MedicalWritingStudyFactState(status="not_applicable")
        )
        seeds = self.service.section_seeds(definition)
        aesi = self._seed(seeds, "cms_safety_aesi")
        self.assertEqual("not_applicable", aesi.applicability_status)
        self.assertEqual(
            "retain_not_applicable", aesi.applicability_render_action
        )
        self.assertIn("不适用", aesi.initial_text)

    def test_not_applicable_field_does_not_project_stale_value_into_applicable_chapter(
        self,
    ):
        """A not_applicable field must never project its stale clinical value
        into an otherwise applicable chapter body.

        Regression for the state-boundary defect where section_seeds put both
        confirmed and not_applicable paths into confirmed_set, so a stale
        picos.estimand_strategy value leaked into cms_study_design_rationale
        even though field_states marked the path not_applicable. Module-level
        retain_not_applicable (e.g. safety.aesi) remains a separate path.
        """
        definition = self._definition()
        stale_estimand = "采用治疗策略处理事件后数据"
        definition.picos.estimand_strategy = stale_estimand
        definition.field_states["picos.estimand_strategy"] = (
            MedicalWritingStudyFactState(status="not_applicable")
        )
        # Legacy free-text design_pattern is no longer an authoritative body
        # source. Marking it confirmed must not reintroduce a parallel design
        # truth into an otherwise applicable chapter.
        definition.field_states["framing.design_pattern"] = (
            MedicalWritingStudyFactState(status="confirmed")
        )
        seeds = self.service.section_seeds(definition)
        rationale = self._seed(seeds, "cms_study_design_rationale")
        self.assertNotIn(stale_estimand, rationale.initial_text)
        self.assertFalse(
            any(
                "estimand_strategy" in fact_id
                for fact_id in rationale.source_fact_ids
            ),
            f"not_applicable estimand must not appear in source_fact_ids: "
            f"{rationale.source_fact_ids}",
        )
        self.assertNotIn(
            "随机、双盲、安慰剂对照",
            rationale.initial_text,
        )
        self.assertFalse(
            any(
                "design_pattern" in fact_id
                for fact_id in rationale.source_fact_ids
            ),
            f"legacy design_pattern must not appear in source_fact_ids: "
            f"{rationale.source_fact_ids}",
        )
        # Module-level retain_not_applicable policy is preserved and independent.
        definition.field_states["picos.aesi_definitions"] = (
            MedicalWritingStudyFactState(status="not_applicable")
        )
        seeds_with_aesi = self.service.section_seeds(definition)
        aesi = self._seed(seeds_with_aesi, "cms_safety_aesi")
        self.assertEqual("not_applicable", aesi.applicability_status)
        self.assertEqual(
            "retain_not_applicable", aesi.applicability_render_action
        )
        self.assertIn("不适用", aesi.initial_text)

    # -- SC7: project-specific facts do not leak across projects ---------

    def test_project_facts_do_not_leak_into_other_project_definitions(self):
        project_a = self._definition()
        project_a.framing.indication = "特应性皮炎"
        project_a.definition_id = "project_a"
        project_a.field_states["framing.indication"] = (
            MedicalWritingStudyFactState(status="confirmed")
        )

        project_b = copy.deepcopy(self._definition())
        project_b.framing.indication = "类风湿关节炎"
        project_b.definition_id = "project_b"
        project_b.revision = 1
        project_b.field_states = {
            "framing.design_pattern": MedicalWritingStudyFactState(
                status="confirmed"
            ),
        }

        seeds_a = self.service.section_seeds(project_a)
        seeds_b = self.service.section_seeds(project_b)

        disease_a = self._seed(seeds_a, "cms_background_disease")
        disease_b = self._seed(seeds_b, "cms_background_disease")

        self.assertIn("特应性皮炎", disease_a.initial_text)
        self.assertNotIn("特应性皮炎", disease_b.initial_text)
        self.assertNotIn("类风湿关节炎", disease_a.initial_text)
        self.assertIn("待补充", disease_b.initial_text)

    def test_source_fact_ids_carry_correct_project_and_revision(self):
        definition = self._definition()
        definition.definition_id = "leak_test_def"
        definition.revision = 7
        definition.field_states["picos.sample_size_strategy"] = (
            MedicalWritingStudyFactState(status="confirmed")
        )
        seeds = self.service.section_seeds(definition)
        sample_size = self._seed(seeds, "cms_statistics_sample_size")
        self.assertIn(
            "study_definition:leak_test_def:r7:picos.sample_size_strategy",
            sample_size.source_fact_ids,
        )

    # -- Helpers ---------------------------------------------------------

    @staticmethod
    def _seed(seeds, section_key):
        for seed in seeds:
            if seed.section_key == section_key:
                return seed
        raise AssertionError(f"seed not found: {section_key}")

    @staticmethod
    def _seed_or_none(seeds, section_key):
        for seed in seeds:
            if seed.section_key == section_key:
                return seed
        return None

    @staticmethod
    def _definition():
        return SimpleNamespace(
            definition_id="mwdef_test",
            revision=3,
            synopsis_text="结构化研究摘要",
            framing=SimpleNamespace(
                study_phase="II期",
                document_title="测试方案",
                indication="测试适应症",
                investigational_product="CMS-TEST",
                design_pattern="随机、双盲、安慰剂对照",
                population_intent="目标研究人群",
                intrinsic_objectives=["剂量探索"],
                target_mechanism="",
                product_profile=SimpleNamespace(
                    technology_type="small_molecule",
                    administration_routes=["口服"],
                    dosage_forms=["片剂"],
                    immunogenicity_relevance="not_expected",
                    safety_considerations=[],
                    pk_pd_considerations=[],
                ),
                minimum_product_fact_packet=SimpleNamespace(),
            ),
            picos=SimpleNamespace(
                population_summary="目标研究人群",
                inclusion_modules=[],
                exclusion_modules=[],
                washout_rules=[],
                intervention_summary="试验药物方案",
                intervention_dose_regimen="每日一次口服给药",
                allowed_concomitant_rules=[],
                required_background_rules=[],
                prohibited_concomitant_rules=[],
                assessment_timing_restrictions=[],
                comparator_summary="安慰剂",
                primary_endpoint="主要终点及评价时间",
                primary_objectives=[],
                secondary_objectives=[],
                exploratory_objectives=[],
                key_secondary_endpoints=[],
                other_secondary_endpoints=[],
                exploratory_endpoints=[],
                safety_endpoints=[],
                aesi_definitions=[],
                assessment_instruments=[],
                study_epochs=[],
                visit_strategy="",
                estimand_strategy="",
                sample_size_strategy="计划入组约120例参与者。",
                statistical_strategy="采用预先规定的统计分析集进行分析。",
            ),
            field_states={
                "framing.design_pattern": MedicalWritingStudyFactState(
                    status="confirmed"
                ),
                "framing.population_intent": MedicalWritingStudyFactState(
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
            module_resolutions={},
        )


if __name__ == "__main__":
    unittest.main()
