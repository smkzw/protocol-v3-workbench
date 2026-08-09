from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    MedicalWritingAdaptiveDesign,
    MedicalWritingCrossoverDesign,
    MedicalWritingInterimAnalysisDesign,
    MedicalWritingOpenLabelExtensionDesign,
    MedicalWritingPicosDefinition,
    MedicalWritingSampleSizeReestimationDesign,
    MedicalWritingStudyDefinition,
    MedicalWritingStudyFraming,
    MedicalWritingStructuredStudyDesign,
    MedicalWritingTreatmentSwitchDesign,
)
from services.api.app.medical_writing_design_projection import (
    normalize_study_design,
)
from services.api.app.medical_writing_protocol_assembly_plan import (
    build_protocol_assembly_plan,
)
from services.api.app.medical_writing_study_consistency import (
    MedicalWritingStudyConsistencyService,
)


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _complete_switch(**overrides):
    payload = {
        "planned": True,
        "trigger_or_timing": "完成双盲治疗24周后",
        "eligible_population": "完成治疗且无不可接受安全性风险的受试者",
        "destination_treatment": "转入研究药物开放治疗",
        "blinding_strategy": "转组后开放标签，转组前保持盲态",
        "analysis_handling": "按随机组和实际治疗分别开展主要及补充分析",
    }
    payload.update(overrides)
    return MedicalWritingTreatmentSwitchDesign(**payload)


def _complete_crossover(**overrides):
    payload = {
        "planned": True,
        "sequences": ["序列AB", "序列BA"],
        "periods": ["治疗期1", "治疗期2"],
        "washout_strategy": "两治疗期之间设置14天洗脱期",
        "carryover_assessment": "基于洗脱充分性和给药前浓度评价残留效应",
        "period_sequence_analysis": "模型纳入治疗、周期和序列效应",
    }
    payload.update(overrides)
    return MedicalWritingCrossoverDesign(**payload)


def _complete_ole(**overrides):
    payload = {
        "planned": True,
        "entry_source": "完成主研究双盲治疗期的受试者",
        "entry_eligibility": "完成主要终点评估且无停药标准",
        "treatment_regimen": "所有受试者接受研究药物推荐剂量",
        "duration": "开放标签延展52周",
        "blind_break_and_transition": "主研究数据库锁定前不揭盲，转入时按独立流程衔接",
        "long_term_objectives": ["长期安全性", "疗效维持", "免疫原性"],
    }
    payload.update(overrides)
    return MedicalWritingOpenLabelExtensionDesign(**payload)


def _complete_ssr(**overrides):
    payload = {
        "planned": True,
        "reestimation_mode": "blinded",
        "timing_or_information": "约50%受试者完成主要终点评估后",
        "reestimated_parameter": "主要终点总体方差",
        "decision_rule": "按预设条件方差区间调整总样本量，上限为计划值的130%",
        "alpha_protection": "不使用组间效应估计，维持原显著性水平",
        "operational_protection": "由独立非盲统计团队执行，仅反馈调整后的总样本量",
    }
    payload.update(overrides)
    return MedicalWritingSampleSizeReestimationDesign(**payload)


def _complete_adaptive(**overrides):
    payload = {
        "planned": True,
        "adaptive_type": "dose_selection",
        "adaptation_timing": "完成预设剂量探索队列后",
        "decision_criteria": "基于疗效、安全性和暴露-反应的预设综合标准",
        "adaptable_elements": ["后续阶段剂量", "入组分配比例"],
        "simulation_operating_characteristics": "通过10000次模拟评价选择概率和功效",
        "type_i_error_control": "采用预设多重性策略控制总体I类错误",
        "operational_control": "由独立委员会访问非盲结果并向执行团队提供受限决策",
    }
    payload.update(overrides)
    return MedicalWritingAdaptiveDesign(**payload)


def _definition(
    design: MedicalWritingStructuredStudyDesign,
) -> MedicalWritingStudyDefinition:
    return MedicalWritingStudyDefinition(
        definition_id="def-complex-design",
        project_id="proj-complex-design",
        revision=1,
        origin="guided_greenfield",
        framing=MedicalWritingStudyFraming(
            protocol_id="CMS-COMPLEX-001",
            document_title="复杂设计测试方案",
            indication="类风湿关节炎",
            clinicaltrials_condition_term="Rheumatoid Arthritis",
            study_phase="III期",
            investigational_product="TEST-IP",
            design_pattern="随机、双盲、安慰剂对照、平行组研究",
            structured_design=design,
        ),
        picos=MedicalWritingPicosDefinition(
            design_archetype="randomized_confirmatory",
            population_summary="活动性类风湿关节炎患者",
            primary_endpoint="第24周ACR50应答率",
        ),
        state_sha256="d" * 64,
        created_at=NOW,
        updated_at=NOW,
        updated_by="test",
    )


@pytest.mark.parametrize(
    ("legacy_field", "typed_field"),
    [
        ("treatment_switch_planned", "treatment_switch"),
        ("crossover_planned", "crossover"),
        ("open_label_extension_planned", "open_label_extension"),
        ("sample_size_reestimation_planned", "sample_size_reestimation"),
        ("adaptive_design_enabled", "adaptive_design"),
    ],
)
@pytest.mark.parametrize("planned", [True, False, None])
def test_legacy_boolean_migration_matrix_is_stable(
    legacy_field: str,
    typed_field: str,
    planned: bool | None,
):
    payload = {
        "schema_version": "medical_writing_structured_study_design_v1",
        legacy_field: planned,
    }
    if legacy_field == "adaptive_design_enabled":
        payload["adaptive_features"] = ["剂量选择"]

    design = MedicalWritingStructuredStudyDesign.model_validate(payload)

    assert getattr(design, typed_field).planned is planned
    serialized = design.model_dump(mode="json")
    assert legacy_field not in serialized
    assert serialized["schema_version"] == "medical_writing_structured_study_design_v2"
    assert (
        MedicalWritingStructuredStudyDesign.model_validate(serialized).model_dump(
            mode="json"
        )
        == serialized
    )


def test_typed_complex_design_wins_over_conflicting_legacy_boolean():
    design = MedicalWritingStructuredStudyDesign.model_validate(
        {
            "treatment_switch": {"planned": False},
            "treatment_switch_planned": True,
        }
    )
    assert design.treatment_switch.planned is False
    assert design.treatment_switch_planned is False
    assert "treatment_switch_planned" not in design.model_dump(mode="json")


@pytest.mark.parametrize(
    ("model", "field_names"),
    [
        (
            MedicalWritingTreatmentSwitchDesign(
                planned=False,
                trigger_or_timing="旧值",
                eligible_population="旧值",
                destination_treatment="旧值",
                blinding_strategy="旧值",
                analysis_handling="旧值",
            ),
            (
                "trigger_or_timing",
                "eligible_population",
                "destination_treatment",
                "blinding_strategy",
                "analysis_handling",
            ),
        ),
        (
            MedicalWritingCrossoverDesign(
                planned=False,
                sequences=["AB"],
                periods=["P1"],
                washout_strategy="旧值",
                carryover_assessment="旧值",
                period_sequence_analysis="旧值",
            ),
            (
                "sequences",
                "periods",
                "washout_strategy",
                "carryover_assessment",
                "period_sequence_analysis",
            ),
        ),
        (
            MedicalWritingOpenLabelExtensionDesign(
                planned=False,
                entry_source="旧值",
                entry_eligibility="旧值",
                treatment_regimen="旧值",
                duration="旧值",
                blind_break_and_transition="旧值",
                long_term_objectives=["旧值"],
            ),
            (
                "entry_source",
                "entry_eligibility",
                "treatment_regimen",
                "duration",
                "blind_break_and_transition",
                "long_term_objectives",
            ),
        ),
        (
            MedicalWritingSampleSizeReestimationDesign(
                planned=False,
                reestimation_mode="unblinded",
                timing_or_information="旧值",
                reestimated_parameter="旧值",
                decision_rule="旧值",
                alpha_protection="旧值",
                operational_protection="旧值",
            ),
            (
                "timing_or_information",
                "reestimated_parameter",
                "decision_rule",
                "alpha_protection",
                "operational_protection",
            ),
        ),
        (
            MedicalWritingAdaptiveDesign(
                planned=False,
                adaptive_type="group_sequential",
                adaptation_timing="旧值",
                decision_criteria="旧值",
                adaptable_elements=["旧值"],
                simulation_operating_characteristics="旧值",
                type_i_error_control="旧值",
                operational_control="旧值",
            ),
            (
                "adaptation_timing",
                "decision_criteria",
                "adaptable_elements",
                "simulation_operating_characteristics",
                "type_i_error_control",
                "operational_control",
            ),
        ),
    ],
)
def test_planned_false_clears_non_applicable_detail(model, field_names):
    for field_name in field_names:
        value = getattr(model, field_name)
        assert value == "" or value == []
    if isinstance(model, MedicalWritingSampleSizeReestimationDesign):
        assert model.reestimation_mode == "undecided"
    if isinstance(model, MedicalWritingAdaptiveDesign):
        assert model.adaptive_type == "undecided"


def test_ssr_mode_and_adaptive_type_are_closed_distinct_semantics():
    assert _complete_ssr(reestimation_mode="blinded").reestimation_mode == "blinded"
    assert (
        _complete_ssr(reestimation_mode="unblinded").reestimation_mode
        == "unblinded"
    )
    assert _complete_adaptive(adaptive_type="group_sequential").adaptive_type == (
        "group_sequential"
    )
    assert _complete_adaptive(
        adaptive_type="sample_size_reestimation"
    ).adaptive_type == "sample_size_reestimation"
    with pytest.raises(ValidationError):
        MedicalWritingSampleSizeReestimationDesign(
            planned=True,
            reestimation_mode="partially_blinded",
        )


def test_normalizer_projects_all_typed_designs_and_precise_related_blockers():
    design = MedicalWritingStructuredStudyDesign(
        randomization_mode="randomized",
        blinding_mode="double_blind",
        comparator_type="placebo",
        treatment_switch=MedicalWritingTreatmentSwitchDesign(planned=True),
        crossover=_complete_crossover(),
        open_label_extension=_complete_ole(),
        sample_size_reestimation=MedicalWritingSampleSizeReestimationDesign(
            planned=True,
            reestimation_mode="blinded",
        ),
        adaptive_design=MedicalWritingAdaptiveDesign(
            planned=True,
            adaptive_type="dose_selection",
        ),
    )
    projection = normalize_study_design(_definition(design), include_sources=True)

    assert projection.design_view.crossover.sequences == ["序列AB", "序列BA"]
    assert projection.design_view.open_label_extension.duration == "开放标签延展52周"
    assert projection.design_fact_paths["treatment_switch"] == (
        "framing.structured_design.treatment_switch"
    )
    assert projection.design_fact_paths["adaptive_design"] == (
        "framing.structured_design.adaptive_design"
    )
    assert projection.deterministic_projection_allowed is False
    blocker_paths = {item.fact_path for item in projection.blockers}
    assert "framing.structured_design.treatment_switch.trigger_or_timing" in (
        blocker_paths
    )
    assert (
        "framing.structured_design.sample_size_reestimation.reestimated_parameter"
        in blocker_paths
    )
    assert (
        "framing.structured_design.adaptive_design.simulation_operating_characteristics"
        in blocker_paths
    )
    assert "soa" in projection.affected_projections
    assert "study_schema_flowchart" in projection.affected_projections


def test_ssr_blockers_do_not_expand_to_soa_or_flowchart():
    design = MedicalWritingStructuredStudyDesign(
        sample_size_reestimation=MedicalWritingSampleSizeReestimationDesign(
            planned=True,
            reestimation_mode="blinded",
        ),
        treatment_switch=MedicalWritingTreatmentSwitchDesign(planned=False),
        crossover=MedicalWritingCrossoverDesign(planned=False),
        open_label_extension=MedicalWritingOpenLabelExtensionDesign(planned=False),
        adaptive_design=MedicalWritingAdaptiveDesign(planned=False),
    )
    projection = normalize_study_design(_definition(design))
    assert projection.blockers
    assert "soa" not in projection.affected_projections
    assert "study_schema_flowchart" not in projection.affected_projections


def test_complete_typed_designs_create_distinct_modules_and_drivers():
    design = MedicalWritingStructuredStudyDesign(
        randomization_mode="randomized",
        blinding_mode="double_blind",
        comparator_type="placebo",
        assignment_model="parallel_group",
        treatment_switch=_complete_switch(),
        crossover=_complete_crossover(),
        open_label_extension=_complete_ole(),
        sample_size_reestimation=_complete_ssr(),
        adaptive_design=_complete_adaptive(),
        src_planned=False,
        dmc_planned=False,
        interim_analysis=MedicalWritingInterimAnalysisDesign(planned=False),
    )
    definition = _definition(design)
    projection = normalize_study_design(definition)
    assert projection.blockers == []
    assert projection.deterministic_projection_allowed is True

    plan = build_protocol_assembly_plan(
        definition,
        plan_id="plan-complex",
        revision=1,
        actor="test",
        now=NOW,
    )

    modules = {item.module_id: item for item in plan.modules}
    drivers = {item.driver_id: item for item in plan.design_drivers}
    expected = {
        "design.treatment_switch",
        "design.crossover",
        "design.open_label_extension",
        "design.sample_size_reestimation",
        "design.adaptive",
    }
    assert expected <= modules.keys()
    assert expected <= drivers.keys()
    assert all(modules[item].deterministic_projection_allowed for item in expected)
    assert {drivers[item].driver_kind for item in expected} == {
        "treatment_switch",
        "crossover",
        "open_label_extension",
        "sample_size_reestimation",
        "adaptive_design",
    }
    assert drivers["design.crossover"].fact_path.endswith(".crossover")
    assert drivers["design.treatment_switch"].fact_path.endswith(
        ".treatment_switch"
    )
    assert drivers["design.open_label_extension"].fact_path.endswith(
        ".open_label_extension"
    )


def test_incomplete_typed_module_blocks_only_related_projection_targets():
    design = MedicalWritingStructuredStudyDesign(
        treatment_switch=MedicalWritingTreatmentSwitchDesign(planned=False),
        crossover=MedicalWritingCrossoverDesign(planned=False),
        open_label_extension=MedicalWritingOpenLabelExtensionDesign(planned=False),
        sample_size_reestimation=MedicalWritingSampleSizeReestimationDesign(
            planned=True,
            reestimation_mode="unblinded",
            timing_or_information="50%信息量时",
        ),
        adaptive_design=MedicalWritingAdaptiveDesign(
            planned=True,
            adaptive_type="dose_selection",
        ),
        interim_analysis=MedicalWritingInterimAnalysisDesign(planned=False),
        src_planned=False,
        dmc_planned=False,
    )
    plan = build_protocol_assembly_plan(
        _definition(design),
        plan_id="plan-incomplete-complex",
        revision=1,
        actor="test",
        now=NOW,
    )
    modules = {item.module_id: item for item in plan.modules}
    ssr = modules["design.sample_size_reestimation"]
    adaptive = modules["design.adaptive"]

    assert not ssr.deterministic_projection_allowed
    assert "soa" not in ssr.projection_targets
    assert "study_schema_flowchart" not in ssr.projection_targets
    assert {
        question.fact_path for question in ssr.unresolved_questions
    } >= {
        "framing.structured_design.sample_size_reestimation.reestimated_parameter",
        "framing.structured_design.sample_size_reestimation.decision_rule",
    }

    assert not adaptive.deterministic_projection_allowed
    assert "study_schema_flowchart" in adaptive.projection_targets
    assert "soa" not in adaptive.projection_targets


def test_false_and_none_map_to_not_applicable_and_unknown_modules():
    design = MedicalWritingStructuredStudyDesign(
        treatment_switch=MedicalWritingTreatmentSwitchDesign(planned=False),
        crossover=MedicalWritingCrossoverDesign(planned=None),
        open_label_extension=MedicalWritingOpenLabelExtensionDesign(planned=False),
        sample_size_reestimation=MedicalWritingSampleSizeReestimationDesign(
            planned=False
        ),
        adaptive_design=MedicalWritingAdaptiveDesign(planned=False),
        interim_analysis=MedicalWritingInterimAnalysisDesign(planned=False),
        src_planned=False,
        dmc_planned=False,
    )
    plan = build_protocol_assembly_plan(
        _definition(design),
        plan_id="plan-false-none",
        revision=1,
        actor="test",
        now=NOW,
    )
    modules = {item.module_id: item for item in plan.modules}
    assert modules["design.treatment_switch"].applicability == "not_applicable"
    assert modules["design.treatment_switch"].deterministic_projection_allowed
    assert modules["design.crossover"].applicability == "conditional_applicable"
    assert not modules["design.crossover"].deterministic_projection_allowed
    assert modules["design.crossover"].unresolved_questions[0].fact_path.endswith(
        ".crossover.planned"
    )


class _Journeys:
    def __init__(self, definition):
        self.definition = definition

    def has_project(self, _project_id):
        return True

    def get(self, _project_id):
        return SimpleNamespace(study_definition=self.definition)


def _consistency_projection(design):
    service = MedicalWritingStudyConsistencyService(
        document_service=object(),
        authoring_journey_service=_Journeys(_definition(design)),
    )
    return service.validate_structured_design_authority("proj-complex-design")


def test_crossover_and_ole_semantics_are_not_accepted_as_treatment_switch():
    crossover_misclassified = MedicalWritingStructuredStudyDesign(
        treatment_switch=_complete_switch(
            trigger_or_timing="受试者按交叉序列进入第2治疗期"
        ),
        crossover=MedicalWritingCrossoverDesign(planned=False),
        open_label_extension=MedicalWritingOpenLabelExtensionDesign(planned=False),
    )
    projection = _consistency_projection(crossover_misclassified)
    assert "crossover_misclassified_as_treatment_switch" in {
        item.code for item in projection.blockers
    }
    assert projection.deterministic_projection_allowed is False

    ole_misclassified = MedicalWritingStructuredStudyDesign(
        treatment_switch=_complete_switch(
            trigger_or_timing="完成双盲期后进入开放标签延展"
        ),
        crossover=MedicalWritingCrossoverDesign(planned=False),
        open_label_extension=MedicalWritingOpenLabelExtensionDesign(planned=False),
    )
    projection = _consistency_projection(ole_misclassified)
    assert "open_label_extension_misclassified_as_treatment_switch" in {
        item.code for item in projection.blockers
    }


def test_adaptive_type_conflicts_are_detected_without_collapsing_ssr_mode():
    group_sequential = MedicalWritingStructuredStudyDesign(
        adaptive_design=_complete_adaptive(adaptive_type="group_sequential"),
        sample_size_reestimation=MedicalWritingSampleSizeReestimationDesign(
            planned=False
        ),
        interim_analysis=MedicalWritingInterimAnalysisDesign(planned=False),
    )
    projection = _consistency_projection(group_sequential)
    assert "group_sequential_interim_analysis_conflict" in {
        item.code for item in projection.blockers
    }

    adaptive_ssr = MedicalWritingStructuredStudyDesign(
        adaptive_design=_complete_adaptive(
            adaptive_type="sample_size_reestimation"
        ),
        sample_size_reestimation=MedicalWritingSampleSizeReestimationDesign(
            planned=False
        ),
        interim_analysis=MedicalWritingInterimAnalysisDesign(planned=True),
    )
    projection = _consistency_projection(adaptive_ssr)
    assert "adaptive_ssr_reestimation_conflict" in {
        item.code for item in projection.blockers
    }
