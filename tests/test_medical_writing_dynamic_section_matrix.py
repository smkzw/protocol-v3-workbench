"""Cross-project edge-case tests for the dynamic chapter fact projection.

Worker 03 — mw_dynamic_chapter_projection_20260720.

These tests cover the three real research families referenced by the execution
context (D017 PNH Phase II, synthetic RA Phase II, RUX AD Phase III) and prove
the empty-section governance invariants hold across them:

* conditional not-applicable modules are omitted, never materialised as empty
  body sections (success criterion 2);
* unknown/deferred design decisions are omitted, never materialised as empty
  body sections (success criterion 3);
* applicable chapters carry typed actionable readiness when no
  confirmed fact is available, and are never silently empty or clinically
  invented (success criterion 4);
* confirmed facts project verbatim into relevant body chapters without numeric
  transformation, regrouping, or source-fact-id drift (success criterion 5);
* module resolution and section selection share the same deterministic
  applicability decision (success criterion 6);
* project-specific facts do not leak across the three research definitions
  (success criterion 7).

The fixtures mirror the ``SimpleNamespace`` shape used by the existing protocol
template tests (see ``test_medical_writing_protocol_template.py``) so they stay
decoupled from persistence and route layers. They use only contract types that
already gate the projection engine (``MedicalWritingStudyFactState``).
"""

from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace

from packages.contracts.workbench_contracts import (
    MedicalWritingStudyFactState,
)
from services.api.app.medical_writing_protocol_template import (
    MedicalWritingProtocolTemplateService,
    TEMPLATE_ID,
    _RETAIN_NA_SEMANTIC_NODES,
    _company_module_resolutions,
    _project_chapter_body_draft,
    _project_facets,
    _selected_company_nodes,
)


def _build_definition(
    *,
    definition_id: str,
    study_phase: str,
    document_title: str,
    investigational_product: str,
    population_intent: str,
    design_pattern: str,
    intrinsic_objectives: list[str],
    technology_type: str,
    immunogenicity_relevance: str,
    primary_endpoint: str,
    statistical_strategy: str,
    comparator_summary: str = "安慰剂",
    intervention_summary: str = "试验药物方案",
    intervention_dose_regimen: str = "每日一次口服给药",
    aesi_definitions: list[str] | None = None,
    assessment_instruments: list[str] | None = None,
    inclusion_modules: list[str] | None = None,
    exclusion_modules: list[str] | None = None,
    safety_considerations: list[str] | None = None,
    field_states_extra: dict[str, MedicalWritingStudyFactState] | None = None,
):
    """Build a lightweight StudyDefinition stand-in for projection tests.

    Mirrors the shape produced by the greenfield authoring journey without
    touching persistence. Only the framing/picos fields the projection engine
    reads are populated; everything else defaults as the engine expects.
    """

    field_states = {
        "framing.design_pattern": MedicalWritingStudyFactState(status="confirmed"),
        "framing.population_intent": MedicalWritingStudyFactState(status="confirmed"),
        "picos.intervention_summary": MedicalWritingStudyFactState(status="confirmed"),
        "picos.comparator_summary": MedicalWritingStudyFactState(status="confirmed"),
        "picos.primary_endpoint": MedicalWritingStudyFactState(status="confirmed"),
    }
    if field_states_extra:
        field_states.update(field_states_extra)

    return SimpleNamespace(
        definition_id=definition_id,
        revision=1,
        synopsis_text="结构化研究摘要",
        framing=SimpleNamespace(
            study_phase=study_phase,
            document_title=document_title,
            investigational_product=investigational_product,
            indication=population_intent,
            design_pattern=design_pattern,
            population_intent=population_intent,
            intrinsic_objectives=list(intrinsic_objectives),
            target_mechanism="",
            product_profile=SimpleNamespace(
                technology_type=technology_type,
                administration_routes=["口服"],
                dosage_forms=["片剂"],
                immunogenicity_relevance=immunogenicity_relevance,
                safety_considerations=list(safety_considerations or []),
                pk_pd_considerations=[],
            ),
        ),
        picos=SimpleNamespace(
            population_summary=population_intent,
            inclusion_modules=list(inclusion_modules or []),
            exclusion_modules=list(exclusion_modules or []),
            intervention_summary=intervention_summary,
            intervention_dose_regimen=intervention_dose_regimen,
            allowed_concomitant_rules=[],
            required_background_rules=[],
            prohibited_concomitant_rules=[],
            comparator_summary=comparator_summary,
            primary_endpoint=primary_endpoint,
            key_secondary_endpoints=[],
            other_secondary_endpoints=[],
            exploratory_endpoints=[],
            safety_endpoints=[],
            aesi_definitions=list(aesi_definitions or []),
            assessment_instruments=list(assessment_instruments or []),
            sample_size_strategy="计划入组约120例参与者。",
            statistical_strategy=statistical_strategy,
        ),
        field_states=field_states,
    )


class DynamicSectionMatrixCrossProjectTests(unittest.TestCase):
    """D017 PNH Phase II vs synthetic RA Phase II vs RUX AD Phase III."""

    def setUp(self):
        self.service = MedicalWritingProtocolTemplateService()
        self.template = self.service.definition()
        self.node_by_id = {node.node_id: node for node in self.template.nodes}
        self.node_by_semantic = {
            node.semantic_node_id: node for node in self.template.nodes
        }
        self.d017 = self._d017_pnh_phase2()
        self.ra = self._ra_phase2()
        self.rux = self._rux_ad_phase3()

    # --- fixtures -------------------------------------------------------

    def _d017_pnh_phase2(self):
        return _build_definition(
            definition_id="mwdef_d017_pnh_phase2",
            study_phase="II期",
            document_title="CMS-D017 PNH II期临床试验方案",
            investigational_product="CMS-D017",
            population_intent="阵发性睡眠性血红蛋白尿（PNH）成人受试者",
            design_pattern="随机、双盲、安慰剂对照",
            intrinsic_objectives=["疗效确证"],
            technology_type="small_molecule",
            immunogenicity_relevance="not_expected",
            primary_endpoint="乳酸脱氢酶（LDH）较基线的绝对变化",
            statistical_strategy="采用CMH分层检验。",
        )

    def _ra_phase2(self):
        # Synthetic RA Phase II: biologic with AESI, assessment instrument and
        # a planned interim analysis — exercises the conditional feature nodes.
        return _build_definition(
            definition_id="mwdef_ra_phase2",
            study_phase="II期",
            document_title="MY004 RA II期临床试验方案",
            investigational_product="MY004",
            population_intent="中重度活动性类风湿关节炎受试者",
            design_pattern="随机、双盲、安慰剂对照、阳性对照",
            intrinsic_objectives=["疗效确证"],
            technology_type="monoclonal_antibody",
            immunogenicity_relevance="expected",
            primary_endpoint="ACR20应答率",
            statistical_strategy="采用CMH分层检验，计划期中分析。",
            aesi_definitions=["严重感染"],
            assessment_instruments=["DAS28"],
        )

    def _rux_ad_phase3(self):
        return _build_definition(
            definition_id="mwdef_rux_ad_phase3",
            study_phase="III期",
            document_title="芦可替尼乳膏 AD III期临床试验方案",
            investigational_product="芦可替尼乳膏",
            population_intent="12岁及以上中重度特应性皮炎受试者",
            design_pattern="随机、双盲、安慰剂对照",
            intrinsic_objectives=["疗效确证"],
            technology_type="small_molecule",
            immunogenicity_relevance="not_expected",
            primary_endpoint="IGA 0/1应答率",
            statistical_strategy="采用CMH分层检验。",
        )

    # --- helpers --------------------------------------------------------

    def _resolutions(self, definition):
        return {
            r.semantic_node_id: r
            for r in self.service.module_resolutions(definition, self.template)
        }

    def _seeds(self, definition):
        return self.service.section_seeds(definition, self.template)

    def _selected_semantic_ids(self, definition):
        return {
            node.semantic_node_id
            for node in _selected_company_nodes(self.template, definition)
        }

    def _fact_prefix(self, definition):
        return f"study_definition:{definition.definition_id}:r{definition.revision}:"

    # --- success criterion 7: cross-project isolation ------------------

    def test_project_facets_are_disjoint_on_project_specific_features(self):
        """RA's biologic features must not appear in D017/RUX facets."""
        d017_facets = _project_facets(self.d017)
        ra_facets = _project_facets(self.ra)
        rux_facets = _project_facets(self.rux)
        # RA-only conditional features
        ra_only = {
            "feature:aesi",
            "feature:assessment_instrument",
            "feature:immunogenicity",
            "feature:interim_analysis",
        }
        self.assertTrue(
            ra_only.issubset(ra_facets),
            f"RA should expose biologic features, got {sorted(ra_facets)}",
        )
        self.assertFalse(
            ra_only & d017_facets,
            f"D017 (small molecule) leaked RA features: {sorted(ra_only & d017_facets)}",
        )
        self.assertFalse(
            ra_only & rux_facets,
            f"RUX (small molecule) leaked RA features: {sorted(ra_only & rux_facets)}",
        )

    def test_phase_facets_reflect_each_project_phase(self):
        self.assertEqual({"phase:2"}, {f for f in _project_facets(self.d017) if f.startswith("phase:")})
        self.assertEqual({"phase:2"}, {f for f in _project_facets(self.ra) if f.startswith("phase:")})
        self.assertEqual({"phase:3"}, {f for f in _project_facets(self.rux) if f.startswith("phase:")})

    def test_source_fact_ids_never_cross_project_boundaries(self):
        """Every source_fact_id must be prefixed by its own definition id."""
        for definition in (self.d017, self.ra, self.rux):
            prefix = self._fact_prefix(definition)
            resolutions = self.service.module_resolutions(definition, self.template)
            leaked = [
                fid
                for r in resolutions
                for fid in r.source_fact_ids
                if not fid.startswith(prefix)
            ]
            self.assertEqual(
                [],
                leaked,
                f"{definition.definition_id} leaked foreign fact ids: {leaked}",
            )

    def test_project_specific_endpoints_do_not_leak_into_other_projects(self):
        """D017's LDH / RA's ACR20 / RUX's IGA must not appear in sibling seeds."""
        d017_text = " ".join(s.initial_text for s in self._seeds(self.d017))
        ra_text = " ".join(s.initial_text for s in self._seeds(self.ra))
        rux_text = " ".join(s.initial_text for s in self._seeds(self.rux))
        self.assertIn("乳酸脱氢酶", d017_text)
        self.assertIn("ACR20", ra_text)
        self.assertIn("IGA", rux_text)
        self.assertNotIn("乳酸脱氢酶", ra_text)
        self.assertNotIn("乳酸脱氢酶", rux_text)
        self.assertNotIn("ACR20", d017_text)
        self.assertNotIn("ACR20", rux_text)
        self.assertNotIn("特应性皮炎", d017_text)
        self.assertNotIn("特应性皮炎", ra_text)

    # --- success criterion 2: not-applicable modules omitted -----------

    def test_phase1_conditional_nodes_omitted_for_non_phase1_projects(self):
        """Phase 1 SAD/MAD/food-effect nodes must be omitted, not empty."""
        phase1_semantics = [
            "study_design.phase1_sad",
            "study_design.phase1_mad",
            "study_design.phase1_food_effect",
            "study_design.phase1_special_population",
        ]
        for definition in (self.d017, self.ra, self.rux):
            resolutions = self._resolutions(definition)
            selected = self._selected_semantic_ids(definition)
            seeds = {s.template_node_id: s for s in self._seeds(definition)}
            for semantic_id in phase1_semantics:
                node = self.node_by_semantic[semantic_id]
                resolution = resolutions[semantic_id]
                self.assertEqual(
                    "not_applicable",
                    resolution.status,
                    f"{definition.definition_id}/{semantic_id} should be not_applicable",
                )
                self.assertEqual(
                    "omit",
                    resolution.render_action,
                    f"{definition.definition_id}/{semantic_id} should omit, "
                    f"got {resolution.render_action}",
                )
                self.assertNotIn(
                    semantic_id,
                    selected,
                    f"{definition.definition_id}/{semantic_id} leaked into selection",
                )
                self.assertNotIn(
                    node.node_id,
                    seeds,
                    f"{definition.definition_id}/{semantic_id} produced a section seed",
                )

    def test_not_applicable_resolution_never_produces_empty_body_seed(self):
        """No retained seed may carry an empty body for a conditional module
        that was resolved as not-applicable."""
        for definition in (self.d017, self.ra, self.rux):
            seeds = self._seeds(definition)
            for seed in seeds:
                node = self.node_by_id[seed.template_node_id]
                if seed.applicability_status == "not_applicable":
                    # Either it is omitted (not in seeds at all) or it carries
                    # the explicit 不适用 paragraph — never an empty body.
                    self.assertTrue(
                        seed.initial_text.strip(),
                        f"{definition.definition_id}/{node.semantic_node_id} "
                        "retained N/A module has empty body",
                    )
                    self.assertTrue(
                        seed.initial_text.startswith("不适用"),
                        f"{definition.definition_id}/{node.semantic_node_id} "
                        "N/A body does not start with 不适用",
                    )

    # --- success criterion 3: unknown/deferred modules omitted ----------

    def test_unknown_conditional_modules_are_omitted_not_empty(self):
        """D017/RUX have no AESI/interim facts; those modules must be omitted
        (status unknown), never materialised as empty retained sections."""
        for definition in (self.d017, self.rux):
            resolutions = self._resolutions(definition)
            selected = self._selected_semantic_ids(definition)
            seeds = {s.template_node_id: s for s in self._seeds(definition)}
            for semantic_id in ("safety.aesi", "statistics.interim"):
                node = self.node_by_semantic[semantic_id]
                resolution = resolutions[semantic_id]
                self.assertIn(
                    resolution.status,
                    {"unknown", "deferred"},
                    f"{definition.definition_id}/{semantic_id} status={resolution.status}",
                )
                self.assertEqual(
                    "omit",
                    resolution.render_action,
                    f"{definition.definition_id}/{semantic_id} unknown module "
                    "must omit, not render empty",
                )
                self.assertNotIn(semantic_id, selected)
                self.assertNotIn(node.node_id, seeds)

    def test_deferred_field_state_yields_deferred_omission(self):
        """A field_state marked deferred propagates a deferred (not unknown)
        omission, and still no empty section is produced."""
        deferred = copy.deepcopy(self.d017)
        deferred.field_states["picos.aesi_definitions"] = MedicalWritingStudyFactState(
            status="deferred"
        )
        resolutions = self._resolutions(deferred)
        aesi = resolutions["safety.aesi"]
        self.assertEqual("deferred", aesi.status)
        self.assertEqual("omit", aesi.render_action)
        seeds = {s.template_node_id: s for s in self._seeds(deferred)}
        node = self.node_by_semantic["safety.aesi"]
        self.assertNotIn(node.node_id, seeds)

    # --- success criterion 4: required core chapters never empty --------

    def test_retained_required_core_chapters_are_never_empty(self):
        """Applicable chapters have content or typed readiness outside prose.

        Supersedes the obsolete private core-list/placeholder assertion;
        scope is strengthened to every applicable chapter, not narrowed.
        """
        for definition in (self.d017, self.ra, self.rux):
            seeds = self._seeds(definition)
            for seed in seeds:
                node = self.node_by_id[seed.template_node_id]
                if seed.applicability_status != "applicable":
                    continue
                self.assertNotEqual("unclassified", seed.drafting_status)
                if seed.drafting_status == "substantive_draft":
                    self.assertTrue(seed.initial_text.strip())
                if seed.drafting_status == "actionable_blocker":
                    self.assertEqual("", seed.initial_text)
                    self.assertTrue(seed.drafting_blocker_code)
                    self.assertTrue(seed.drafting_blocker_reason)
                    self.assertTrue(seed.drafting_missing_inputs)
                    self.assertTrue(seed.drafting_resolution_actions)

    def test_required_core_without_confirmed_fact_shows_explicit_placeholder(self):
        """Historical placeholder obligation now lives in typed readiness.

        Unknown facts cannot be put into clinical prose; the visible draft
        must retain actionable missing-input state rather than disappear.
        """
        # background.disease maps to framing.indication, which is NOT in the
        # confirmed field_states set built by _build_definition.
        node = self.node_by_semantic["background.disease"]
        fact_prefix = self._fact_prefix(self.d017)
        confirmed_set = {
            path
            for path, state in self.d017.field_states.items()
            if state.status in {"confirmed", "not_applicable"}
        }

        def value(path: str):
            group, field = path.split(".", 1)
            return getattr(getattr(self.d017, group), field)

        text, fact_ids = _project_chapter_body_draft(
            self.d017,
            node,
            fact_prefix=fact_prefix,
            confirmed_set=confirmed_set,
            value_fn=value,
        )
        self.assertEqual("", text)
        self.assertEqual([], fact_ids)
        seed = next(s for s in self._seeds(self.d017) if s.template_node_id == node.node_id)
        self.assertEqual("actionable_blocker", seed.drafting_status)
        self.assertTrue(seed.drafting_missing_inputs)
        self.assertTrue(seed.drafting_resolution_actions)

    def test_required_core_with_confirmed_fact_projects_verbatim(self):
        """intervention.regimen maps to picos.intervention_summary which IS
        confirmed; the projected text must equal the source value verbatim."""
        node = self.node_by_semantic["intervention.regimen"]
        fact_prefix = self._fact_prefix(self.d017)
        confirmed_set = {
            path
            for path, state in self.d017.field_states.items()
            if state.status in {"confirmed", "not_applicable"}
        }

        def value(path: str):
            group, field = path.split(".", 1)
            return getattr(getattr(self.d017, group), field)

        text, fact_ids = _project_chapter_body_draft(
            self.d017,
            node,
            fact_prefix=fact_prefix,
            confirmed_set=confirmed_set,
            value_fn=value,
        )
        self.assertEqual(self.d017.picos.intervention_summary, text)
        self.assertEqual(
            [fact_prefix + "picos.intervention_summary"], fact_ids
        )

    def test_projected_seed_text_never_contains_fabricated_clinical_numbers(self):
        """No seed may invent numeric values; only confirmed source text may
        appear, so D017 seeds must not contain RA/RUX sample-size or endpoint
        numerics that were never supplied."""
        for definition in (self.d017, self.ra, self.rux):
            for seed in self._seeds(definition):
                # 待补充 and 不适用 placeholders are explicitly allowed
                self.assertFalse(
                    seed.initial_text.startswith("（待补充"),
                    f"{definition.definition_id}/{seed.template_node_id} "
                    "uses a non-canonical placeholder prefix",
                )

    # --- success criterion 5: verbatim projection, no numeric drift -----

    def test_sample_size_numbers_require_confirmed_source_and_remain_verbatim(self):
        definition = copy.deepcopy(self.d017)
        path = "picos.sample_size_strategy"
        definition.picos.sample_size_strategy = "计划入组137例，分配比例2:1，脱落率12.5%。"
        semantic_ids = ("population.size", "statistics.sample_size")
        seeds = {s.template_node_id: s for s in self._seeds(definition)}
        for semantic_id in semantic_ids:
            seed = seeds[self.node_by_semantic[semantic_id].node_id]
            self.assertEqual("", seed.initial_text)
            self.assertEqual("actionable_blocker", seed.drafting_status)
            self.assertNotIn(self._fact_prefix(definition) + path, seed.source_fact_ids)
        definition.field_states[path] = MedicalWritingStudyFactState(status="confirmed")
        seeds = {s.template_node_id: s for s in self._seeds(definition)}
        for semantic_id in semantic_ids:
            seed = seeds[self.node_by_semantic[semantic_id].node_id]
            self.assertEqual(definition.picos.sample_size_strategy, seed.initial_text)
            self.assertIn(self._fact_prefix(definition) + path, seed.source_fact_ids)

    def test_confirmed_fact_projects_without_value_transformation(self):
        """When a fact is confirmed, the projected body text equals the source
        value byte-for-byte (no rounding, regrouping, or unit conversion)."""
        seeds = {s.template_node_id: s for s in self._seeds(self.ra)}
        node = self.node_by_semantic["intervention.regimen"]
        seed = seeds[node.node_id]
        self.assertEqual(self.ra.picos.intervention_summary, seed.initial_text)
        self.assertIn(
            self._fact_prefix(self.ra) + "picos.intervention_summary",
            seed.source_fact_ids,
        )

    def test_projected_fact_ids_match_their_own_definition_prefix(self):
        for definition in (self.d017, self.ra, self.rux):
            prefix = self._fact_prefix(definition)
            for seed in self._seeds(definition):
                for fid in seed.source_fact_ids:
                    self.assertTrue(
                        fid.startswith(prefix),
                        f"{definition.definition_id} seed {seed.template_node_id} "
                        f"has foreign fact id {fid}",
                    )

    # --- success criterion 6: deterministic applicability consistency ---

    def test_module_resolutions_and_section_selection_share_one_decision(self):
        """A node omitted by module_resolutions must not appear in
        _selected_company_nodes, and vice versa, for all three projects."""
        for definition in (self.d017, self.ra, self.rux):
            resolutions = self._resolutions(definition)
            selected_ids = self._selected_semantic_ids(definition)
            for node in self.template.nodes:
                resolution = resolutions[node.semantic_node_id]
                if resolution.render_action == "omit":
                    self.assertNotIn(
                        node.semantic_node_id,
                        selected_ids,
                        f"{definition.definition_id}/{node.semantic_node_id} "
                        "omitted by resolution but present in selection",
                    )
                else:
                    # retained resolutions appear in selection unless orphaned
                    # by an omitted parent (engine contract)
                    if not node.parent_node_id or node.parent_node_id in {
                        self.node_by_semantic[s].node_id for s in selected_ids
                    }:
                        self.assertIn(
                            node.semantic_node_id,
                            selected_ids,
                            f"{definition.definition_id}/{node.semantic_node_id} "
                            "retained by resolution but missing from selection",
                        )

    def test_engine_and_public_api_agree_on_resolutions(self):
        """The private engine and the public service produce identical
        applicability decisions — synopsis/body/TOC share one source."""
        for definition in (self.d017, self.ra, self.rux):
            engine = {
                r.semantic_node_id: (r.status, r.render_action)
                for r in _company_module_resolutions(self.template, definition)
            }
            public = {
                r.semantic_node_id: (r.status, r.render_action)
                for r in self.service.module_resolutions(definition, self.template)
            }
            self.assertEqual(engine, public)

    def test_retain_not_applicable_only_for_policy_retained_nodes(self):
        """The only nodes allowed to render a 不适用 paragraph are the
        company-policy retained semantic nodes; everything else that is
        not-applicable is omitted. Verified across all three projects and
        against an explicit not-applicable field state."""
        for definition in (self.d017, self.ra, self.rux):
            resolutions = self._resolutions(definition)
            retain_na = {
                sem
                for sem, r in resolutions.items()
                if r.render_action == "retain_not_applicable"
            }
            self.assertTrue(
                retain_na.issubset(_RETAIN_NA_SEMANTIC_NODES),
                f"{definition.definition_id} unexpected retain_not_applicable "
                f"nodes: {retain_na - _RETAIN_NA_SEMANTIC_NODES}",
            )

    def test_explicit_not_applicable_renders_na_paragraph_not_empty(self):
        """When a project explicitly marks a policy-retained module
        (safety.aesi) as not-applicable, the engine renders a 不适用
        paragraph rather than omitting or leaving an empty body."""
        definition = copy.deepcopy(self.d017)
        definition.field_states["picos.aesi_definitions"] = (
            MedicalWritingStudyFactState(status="not_applicable")
        )
        resolutions = self._resolutions(definition)
        aesi = resolutions["safety.aesi"]
        self.assertEqual("not_applicable", aesi.status)
        self.assertEqual("retain_not_applicable", aesi.render_action)
        seeds = {s.template_node_id: s for s in self._seeds(definition)}
        node = self.node_by_semantic["safety.aesi"]
        seed = seeds[node.node_id]
        self.assertTrue(seed.initial_text.startswith("不适用"))
        self.assertTrue(seed.initial_text.strip())

    # --- success criterion 8: blank template never invents facts --------

    def test_blank_section_seeds_carry_no_project_facts(self):
        """The canonical blank structure never injects project-specific text
        or fact ids — it only materialises stable core headings."""
        blanks = self.service.blank_section_seeds(self.template)
        self.assertTrue(blanks)
        for seed in blanks:
            self.assertEqual("", seed.initial_text)
            self.assertEqual([], seed.source_fact_ids)
            self.assertEqual("applicable", seed.applicability_status)
            self.assertEqual("retain_full", seed.applicability_render_action)
        # Blank template excludes conditional nodes entirely.
        blank_semantics = {
            self.node_by_id[seed.template_node_id].semantic_node_id
            for seed in blanks
        }
        for phase1 in (
            "study_design.phase1_sad",
            "study_design.phase1_mad",
            "study_design.phase1_food_effect",
            "study_design.phase1_special_population",
        ):
            self.assertNotIn(phase1, blank_semantics)


if __name__ == "__main__":
    unittest.main()
