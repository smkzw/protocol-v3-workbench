from __future__ import annotations

import base64
import hashlib
import io
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.contracts.workbench_contracts import (
    ApprovalState,
    InterventionRulesProductRole,
    MedicalWritingAdaptiveDesign,
    MedicalWritingCrossoverDesign,
    MedicalWritingInterimAnalysisDesign,
    MedicalWritingInterventionIpRegimen,
    MedicalWritingOpenLabelExtensionDesign,
    MedicalWritingPhase1Part,
    MedicalWritingSampleSizeReestimationDesign,
    MedicalWritingStructuredStudyDesign,
    MedicalWritingTreatmentSwitchDesign,
    ProtocolDocument,
    ProtocolSection,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_document_exporter import (
    export_medical_writing_document_docx,
)
from services.api.app.medical_writing_protocol_template import (
    MedicalWritingProtocolTemplateService,
)
from services.api.app.medical_writing_study_schema import (
    render_study_schema_png,
    render_study_schema_svg,
)
from services.api.app.medical_writing_table_templates import (
    MedicalWritingTableTemplateService,
)
from tests.test_manager_plan_consumption_integration import (
    _confirm_plan,
    _definition,
)


def _phase1_part(code: str, label: str, population: str) -> MedicalWritingPhase1Part:
    return MedicalWritingPhase1Part(
        part_code=code,
        part_label=label,
        population=population,
        cohort_dose=f"{label}递增队列",
        pk_pd=f"{label} PK/PD采样",
        safety=f"{label}安全性评价",
        soa_summary=f"{label}访视与采样计划",
        transition_dependencies=f"{label}启动前完成前序安全性审查",
    )


def _base_design(*, phase: str, comparator: str) -> MedicalWritingStructuredStudyDesign:
    phase_one = phase in {"I期", "Phase I"}
    return MedicalWritingStructuredStudyDesign(
        randomization_mode="non_randomized" if phase_one else "randomized",
        randomization_details="" if phase_one else "按1:1比例随机分配",
        blinding_mode="open_label" if phase_one else "double_blind",
        blinding_details="" if phase_one else "受试者、研究者及评价者保持盲态",
        comparator_type=comparator,
        comparator_intervention=(
            "匹配安慰剂"
            if comparator == "placebo"
            else "标准剂量阳性对照药"
            if comparator == "active"
            else ""
        ),
        assignment_model="序贯剂量递增" if phase_one else "平行分组",
        center_model="多中心",
        treatment_switch=MedicalWritingTreatmentSwitchDesign(planned=False),
        crossover=MedicalWritingCrossoverDesign(planned=False),
        open_label_extension=MedicalWritingOpenLabelExtensionDesign(planned=False),
        sample_size_reestimation=MedicalWritingSampleSizeReestimationDesign(
            planned=False
        ),
        adaptive_design=MedicalWritingAdaptiveDesign(planned=False),
        interim_analysis=MedicalWritingInterimAnalysisDesign(planned=False),
        src_planned=False,
        dmc_planned=False,
    )


def _with_comparator_regimen(definition, comparator: str):
    rules = definition.picos.intervention_rules.model_copy(deep=True)
    regimens = list(rules.ip_regimens)
    if comparator == "placebo":
        regimens.append(
            MedicalWritingInterventionIpRegimen(
                regimen_id="placebo-1",
                product_name="匹配安慰剂",
                product_role=InterventionRulesProductRole.PLACEBO,
                dose_and_frequency="与研究药物匹配",
                route="口服",
                treatment_period="双盲治疗期",
            )
        )
    elif comparator == "active" and not any(
        item.product_role == InterventionRulesProductRole.ACTIVE_COMPARATOR
        for item in regimens
    ):
        regimens.append(
            MedicalWritingInterventionIpRegimen(
                regimen_id="active-1",
                product_name="阳性对照药",
                product_role=InterventionRulesProductRole.ACTIVE_COMPARATOR,
                dose_and_frequency="标准剂量",
                route="口服",
                treatment_period="双盲治疗期",
            )
        )
    return rules.model_copy(update={"ip_regimens": regimens}, deep=True)


def _scenario_definition(case_id: str):
    phase = "I期" if case_id.startswith("p1_") else (
        "II/III期" if case_id == "adaptive_seamless" else "III期"
    )
    comparator = (
        "none_or_dose_escalation"
        if case_id.startswith("p1_")
        else "active"
        if case_id == "active_control"
        else "none_or_dose_escalation"
        if case_id == "crossover"
        else "placebo"
    )
    base = _definition(
        project_id=f"slice-c-{case_id}",
        study_phase=phase,
        phase1_parts=[],
        comparator_type=comparator,
        background_mtx=case_id == "background_placebo",
        include_active_comparator=case_id == "active_control",
        interim_planned=False,
    )
    design = _base_design(phase=phase, comparator=comparator)
    epochs = ["筛选期", "基线/随机", "双盲治疗期", "安全性随访期"]
    required_background = []
    if case_id == "p1_sad_mad":
        design = design.model_copy(
            update={
                "phase1_parts": [
                    _phase1_part("sad", "SAD", "健康受试者"),
                    _phase1_part("mad", "MAD", "健康受试者"),
                ],
                "phase1_sequence": "SAD安全性审查后启动MAD",
                "src_planned": True,
            },
            deep=True,
        )
        epochs = ["筛选期", "给药与观察期", "安全性随访期"]
    elif case_id == "p1_sad_mad_fip":
        design = design.model_copy(
            update={
                "phase1_parts": [
                    _phase1_part("sad", "SAD", "健康受试者"),
                    _phase1_part("mad", "MAD", "健康受试者"),
                    _phase1_part(
                        "first_in_patient", "首次患者", "目标适应症患者"
                    ),
                ],
                "phase1_sequence": "SAD、MAD完成后进入首次患者Part",
                "src_planned": True,
            },
            deep=True,
        )
        epochs = ["筛选期", "给药与观察期", "安全性随访期"]
    elif case_id == "background_placebo":
        required_background = ["稳定剂量甲氨蝶呤背景治疗"]
        design = design.model_copy(update={"dmc_planned": True}, deep=True)
    elif case_id == "interim_switch_ole":
        design = design.model_copy(
            update={
                "interim_analysis": MedicalWritingInterimAnalysisDesign(
                    planned=True,
                    purpose="疗效和无效性期中分析",
                    timing="达到50%信息分数时",
                    information_fraction="50%",
                    statistical_boundary="采用预设组序贯边界",
                    alpha_control="采用α消耗函数控制总体I类错误",
                    independent_committee="由独立DMC审阅",
                    operational_firewall="保持申办方盲态和操作隔离",
                ),
                "treatment_switch": MedicalWritingTreatmentSwitchDesign(
                    planned=True,
                    trigger_or_timing="第24周转组",
                    eligible_population="完成第24周评价的安慰剂组受试者",
                    destination_treatment="研究药物",
                    blinding_strategy="完成第24周评价后按方案揭盲",
                    analysis_handling="转组前后按预设估计目标分析",
                ),
                "open_label_extension": MedicalWritingOpenLabelExtensionDesign(
                    planned=True,
                    entry_source="完成双盲期的受试者",
                    entry_eligibility="完成第24周评价并符合延展条件",
                    treatment_regimen="研究药物开放标签治疗",
                    duration="48周",
                    blind_break_and_transition="第24周揭盲后衔接延展期",
                    long_term_objectives=["长期安全性", "疗效维持"],
                ),
                "dmc_planned": True,
            },
            deep=True,
        )
        epochs = ["筛选期", "基线/随机", "双盲治疗期", "安全性随访期"]
    elif case_id == "active_control":
        design = design.model_copy(update={"dmc_planned": True}, deep=True)
    elif case_id == "crossover":
        design = design.model_copy(
            update={
                "randomization_mode": "randomized",
                "blinding_mode": "open_label",
                "blinding_details": "",
                "assignment_model": "2×2交叉序列",
                "crossover": MedicalWritingCrossoverDesign(
                    planned=True,
                    sequences=["序列AB", "序列BA"],
                    periods=["第1周期", "第2周期"],
                    washout_strategy="两个周期之间设置14天洗脱期",
                    carryover_assessment="评估残留效应并预设敏感性分析",
                    period_sequence_analysis="模型纳入周期、序列和治疗效应",
                ),
            },
            deep=True,
        )
        epochs = ["筛选期", "第1周期", "洗脱期", "第2周期", "随访"]
    elif case_id == "blinded_ssr":
        design = design.model_copy(
            update={
                "sample_size_reestimation": (
                    MedicalWritingSampleSizeReestimationDesign(
                        planned=True,
                        reestimation_mode="blinded",
                        timing_or_information="完成约50%受试者主要终点评价时",
                        reestimated_parameter="合并方差",
                        decision_rule="按预设区间调整总样本量",
                        alpha_protection="不使用组间效应，保持总体α水平",
                        operational_protection="由独立统计人员执行并维持盲态",
                    )
                )
            },
            deep=True,
        )
    elif case_id == "adaptive_seamless":
        design = design.model_copy(
            update={
                "adaptive_design": MedicalWritingAdaptiveDesign(
                    planned=True,
                    adaptive_type="seamless_phase",
                    adaptation_timing="II期部分完成后进行无缝过渡决策",
                    decision_criteria="基于预设疗效、安全性和剂量标准",
                    adaptable_elements=["剂量选择", "样本量", "进入III期"],
                    simulation_operating_characteristics="通过模拟评价把握度和错误选择概率",
                    type_i_error_control="采用封闭检验控制总体I类错误",
                    operational_control="由独立DMC执行并保持操作防火墙",
                ),
                "interim_analysis": MedicalWritingInterimAnalysisDesign(
                    planned=True,
                    purpose="无缝过渡决策",
                    timing="II期部分完成时",
                    information_fraction="预设信息量",
                    statistical_boundary="按适应性决策规则执行",
                    alpha_control="总体I类错误受控",
                    independent_committee="独立DMC",
                    operational_firewall="保持申办方盲态",
                ),
                "dmc_planned": True,
            },
            deep=True,
        )
    elif case_id == "committees":
        design = design.model_copy(
            update={"src_planned": True, "dmc_planned": True}, deep=True
        )
    elif case_id == "no_committees":
        design = design.model_copy(
            update={"src_planned": False, "dmc_planned": False}, deep=True
        )

    picos = base.picos.model_copy(
        update={
            "study_epochs": epochs,
            "required_background_rules": required_background,
            "intervention_summary": "研究药物按方案给药",
            "intervention_dose_regimen": "按预设剂量和频次给药",
            "comparator_summary": (
                "匹配安慰剂"
                if comparator == "placebo"
                else "标准治疗阳性对照药"
                if comparator == "active"
                else "无平行对照"
            ),
            "intervention_rules": _with_comparator_regimen(base, comparator),
            "primary_endpoint": "主要疗效终点",
            "sample_size_strategy": "按主要终点假设确定样本量",
            "statistical_strategy": "采用预设统计模型进行分析",
        },
        deep=True,
    )
    framing = base.framing.model_copy(
        update={
            "document_title": f"{case_id}临床试验方案",
            "study_phase": phase,
            "design_pattern": "故意冲突的legacy文本：非随机、开放、无对照",
            "structured_design": design,
        },
        deep=True,
    )
    return base.model_copy(
        update={
            "framing": framing,
            "picos": picos,
            "state_sha256": hashlib.sha256(case_id.encode()).hexdigest(),
        },
        deep=True,
    )


def _flatten_synopsis(seed) -> str:
    values = []
    for row in seed.initial_data["rows"]:
        values.extend(str(item) for item in row.get("values", []))
    return "\n".join(values)


def _flatten_table(block: dict) -> str:
    table = block["structured_table"]
    return "\n".join(
        cell["text"] for row in table["rows"] for cell in row["cells"]
    )


def _document_from_outputs(
    definition,
    synopsis_text: str,
    design_text: str,
    soa_block: dict,
    schema,
    svg: str,
) -> ProtocolDocument:
    document_id = f"doc-{definition.project_id}"
    png = render_study_schema_png(svg, scale=1)
    figure = {
        "block_id": f"figure-{definition.project_id}",
        "block_type": "figure",
        "figure_id": f"figure-{definition.project_id}",
        "figure_kind": "study_schema",
        "title": "研究设计概况",
        "alt_text": "研究流程图：研究设计概况",
        "body_order": 2,
        "source_kind": "medical_writing_study_schema",
        "source_locator": (
            f"generated:medical_writing_study_schema:{schema.schema_id}:r1"
        ),
        "editable": False,
        "schema_id": schema.schema_id,
        "schema_revision": schema.revision,
        "schema_state_sha256": schema.state_sha256,
        "layout_revision": 0,
        "svg": svg,
        "svg_sha256": hashlib.sha256(svg.encode()).hexdigest(),
        "png_base64": base64.b64encode(png).decode(),
        "png_sha256": hashlib.sha256(png).hexdigest(),
        "width_inches": 6.45,
        "bookmark_name": f"mwfig_{hashlib.sha256(definition.project_id.encode()).hexdigest()[:12]}",
    }
    soa_block = dict(soa_block)
    soa_block["body_order"] = 2
    sections = [
        ProtocolSection(
            section_id="synopsis",
            document_id=document_id,
            heading="方案摘要",
            section_number="1.1",
            node_kind="protocol_synopsis",
            approval_state=ApprovalState.AI_DRAFT,
            content_blocks=[
                {
                    "block_id": "synopsis-heading",
                    "block_type": "heading",
                    "text": "1.1 方案摘要",
                    "body_order": 1,
                },
                {
                    "block_id": "synopsis-body",
                    "block_type": "paragraph",
                    "text": synopsis_text,
                    "body_order": 2,
                },
            ],
        ),
        ProtocolSection(
            section_id="schema",
            document_id=document_id,
            heading="研究示意图",
            section_number="1.2",
            node_kind="study_schema",
            content_blocks=[
                {
                    "block_id": "schema-heading",
                    "block_type": "heading",
                    "text": "1.2 研究示意图",
                    "body_order": 1,
                },
                figure,
            ],
        ),
        ProtocolSection(
            section_id="soa",
            document_id=document_id,
            heading="研究流程表",
            section_number="1.3",
            node_kind="schedule_of_activities",
            content_blocks=[
                {
                    "block_id": "soa-heading",
                    "block_type": "heading",
                    "text": "1.3 研究流程表",
                    "body_order": 1,
                },
                soa_block,
            ],
        ),
        ProtocolSection(
            section_id="design",
            document_id=document_id,
            heading="总体设计",
            section_number="4.1",
            approval_state=ApprovalState.AI_DRAFT,
            content_blocks=[
                {
                    "block_id": "design-heading",
                    "block_type": "heading",
                    "text": "4.1 总体设计",
                    "body_order": 1,
                },
                {
                    "block_id": "design-body",
                    "block_type": "paragraph",
                    "text": design_text,
                    "body_order": 2,
                },
            ],
        ),
    ]
    return ProtocolDocument(
        document_id=document_id,
        project_id=definition.project_id,
        protocol_id=definition.framing.protocol_id,
        version=definition.framing.version,
        sections=sections,
        source_study_definition_id=definition.definition_id,
        source_study_definition_revision=definition.revision,
        source_study_definition_sha256=definition.state_sha256,
    )


CASES = (
    ("p1_sad_mad", {"SAD", "MAD"}, {"首次患者"}),
    ("p1_sad_mad_fip", {"SAD", "MAD", "首次患者"}, set()),
    ("background_placebo", {"安慰剂", "背景治疗", "甲氨蝶呤"}, set()),
    (
        "interim_switch_ole",
        {"期中分析", "治疗切换", "开放标签延展", "DMC"},
        set(),
    ),
    ("active_control", {"阳性药对照"}, {"安慰剂对照"}),
    ("crossover", {"交叉", "洗脱", "序列AB", "序列BA"}, {"治疗切换"}),
    ("blinded_ssr", {"盲态样本量再估计"}, {"非盲态样本量再估计"}),
    ("adaptive_seamless", {"无缝II/III期", "适应性决策", "DMC"}, set()),
    ("committees", {"SRC", "DMC"}, set()),
    ("no_committees", set(), {"SRC", "DMC"}),
)

SURFACE_EXPECTATIONS = {
    "p1_sad_mad": {
        "synopsis": {"SAD", "MAD"},
        "sections": {"I期研究组成", "SAD", "MAD"},
        "soa": {"SAD", "MAD", "SRC安全性审查"},
        "flowchart": {"Part A：SAD", "Part B：MAD", "SRC安全性审查"},
        "docx": {"SAD", "MAD"},
    },
    "p1_sad_mad_fip": {
        "synopsis": {"SAD", "MAD", "首次患者"},
        "sections": {"I期研究组成", "SAD", "MAD", "首次患者"},
        "soa": {"SAD", "MAD", "首次患者"},
        "flowchart": {"Part A：SAD", "Part B：MAD", "Part C：首次患者"},
        "docx": {"SAD", "MAD", "首次患者"},
    },
    "background_placebo": {
        "synopsis": {"安慰剂对照", "稳定剂量甲氨蝶呤背景治疗"},
        "sections": {
            "安慰剂对照",
            "必须使用的背景治疗",
            "稳定剂量甲氨蝶呤背景治疗",
        },
        "soa": {"安慰剂对照", "背景治疗", "稳定剂量甲氨蝶呤背景治疗"},
        "flowchart": {"匹配安慰剂", "稳定剂量甲氨蝶呤背景治疗"},
        "docx": {"安慰剂对照", "稳定剂量甲氨蝶呤背景治疗"},
    },
    "interim_switch_ole": {
        "synopsis": {"期中分析", "治疗切换", "开放标签延展"},
        "sections": {"期中分析", "治疗切换", "开放标签延展"},
        "soa": {"期中分析", "治疗切换", "开放标签延展"},
        "flowchart": {"第24周转组", "开放标签延展（48周）", "期中分析"},
        "docx": {"期中分析", "治疗切换", "开放标签延展"},
    },
    "active_control": {
        "synopsis": {"阳性药对照"},
        "sections": {"阳性药对照"},
        "soa": {"阳性药对照"},
        "flowchart": {"标准治疗阳性对照药"},
        "docx": {"阳性药对照"},
    },
    "crossover": {
        "synopsis": {"交叉设计", "序列AB", "序列BA", "洗脱"},
        "sections": {"交叉设计", "序列AB", "序列BA", "洗脱"},
        "soa": {"交叉序列", "序列AB", "序列BA", "洗脱"},
        "flowchart": {"交叉研究流程", "序列AB", "序列BA", "洗脱期"},
        "docx": {"交叉设计", "序列AB", "序列BA", "洗脱"},
    },
    "blinded_ssr": {
        "synopsis": {"盲态样本量再估计"},
        "sections": {"盲态样本量再估计", "合并方差"},
        "soa": {"盲态样本量再估计"},
        "flowchart": {"盲态样本量再估计", "合并方差"},
        "docx": {"盲态样本量再估计"},
    },
    "adaptive_seamless": {
        "synopsis": {"无缝II/III期适应性设计"},
        "sections": {"适应性设计", "无缝过渡决策", "总体I类错误"},
        "soa": {"适应性决策", "无缝过渡决策"},
        "flowchart": {"适应性决策", "无缝过渡决策"},
        "docx": {"无缝II/III期适应性设计"},
    },
    "committees": {
        "synopsis": {"SRC", "DMC"},
        "sections": {"安全性审评/数据监查委员会", "SRC", "DMC"},
        "soa": {"SRC安全性审查", "DMC数据监查"},
        "flowchart": {"SRC安全性审查", "DMC数据监查"},
        "docx": {"SRC", "DMC"},
    },
    "no_committees": {
        "synopsis": {"安慰剂对照"},
        "sections": {"安全性审评/数据监查委员会", "不适用"},
        "soa": {"安慰剂对照"},
        "flowchart": {"安全性随访期"},
        "docx": {"安慰剂对照"},
    },
}


@pytest.mark.parametrize("case_id,required,forbidden", CASES)
def test_slice_c_actual_output_matrix(case_id, required, forbidden):
    definition = _scenario_definition(case_id)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _, _, helper, _ = _confirm_plan(root, definition)
        template_service = MedicalWritingProtocolTemplateService(helper)
        seeds = template_service.section_seeds(definition)
        synopsis_seed = next(
            seed for seed in seeds if seed.node_kind == "protocol_synopsis"
        )
        design_seed = next(
            seed
            for seed in seeds
            if seed.template_node_id == "cms_study_design_overall"
        )
        synopsis_text = _flatten_synopsis(synopsis_seed)
        section_text = "\n".join(
            f"{seed.heading}\n{seed.initial_text}" for seed in seeds
        )

        soa_block = MedicalWritingTableTemplateService(
            plan_consumption_helper=helper
        ).instantiate(
            "schedule_of_activities",
            project_id=definition.project_id,
        )
        soa_text = _flatten_table(soa_block)

        journey = MedicalWritingAuthoringJourneyService(root / "journey.sqlite3")
        journey.bind_plan_consumption_helper(helper)
        journey.get = lambda project_id: SimpleNamespace(
            study_definition=definition,
            framing_complete=True,
            picos_complete=True,
        )
        schema = journey.propose_study_schema(definition.project_id)
        svg = render_study_schema_svg(schema)
        flow_text = " ".join(
            [
                *(part.label for part in schema.parts),
                *(node.label for node in schema.nodes),
                *(line for node in schema.nodes for line in node.detail_lines),
                *(edge.label for edge in schema.edges),
            ]
        )

        document = _document_from_outputs(
            definition,
            synopsis_text,
            design_seed.initial_text,
            soa_block,
            schema,
            svg,
        )
        exported = export_medical_writing_document_docx(
            document,
            mode="draft_preview",
            plan_consumption_helper=helper,
        )
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            document_xml = archive.read("word/document.xml").decode()

        surfaces = {
            "synopsis": synopsis_text,
            "sections": section_text,
            "soa": soa_text,
            "flowchart": flow_text + svg,
            "docx": document_xml,
        }
        combined = "\n".join(surfaces.values())
        assert "故意冲突的legacy文本" not in combined
        for term in required:
            assert term in combined, f"{case_id} missing {term}: {surfaces}"
        for term in forbidden:
            assert term not in combined, f"{case_id} leaked {term}: {surfaces}"
        for surface_name, expected_terms in SURFACE_EXPECTATIONS[case_id].items():
            surface_text = surfaces[surface_name]
            for term in expected_terms:
                assert term in surface_text, (
                    f"{case_id} {surface_name} missing {term}: {surface_text}"
                )

        assert "1.1 方案摘要" in document_xml
        assert "1.2 研究示意图" in document_xml
        assert "1.3 研究流程表" in document_xml
        assert "4.1 总体设计" in document_xml
        assert 'TOC \\o "1-4" \\h \\z \\u' in document_xml
        assert exported.metadata["normalized_design_definition_sha256"] == (
            definition.state_sha256
        )
        assert exported.metadata["table_count"] >= 1
        assert exported.metadata["figure_count"] >= 1


def test_slice_c_all_five_consumers_fail_closed_without_confirmed_plan():
    definition = _scenario_definition("active_control")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        from services.api.app.medical_writing_plan_consumption import (
            MedicalWritingPlanConsumptionHelper,
            PlanUnconfirmedError,
        )
        from services.api.app.medical_writing_protocol_assembly_plan import (
            MedicalWritingProtocolAssemblyPlanService,
        )

        helper = MedicalWritingPlanConsumptionHelper(
            MedicalWritingProtocolAssemblyPlanService(
                root / "missing.sqlite3",
                {definition.project_id: definition}.__getitem__,
            )
        )
        with pytest.raises(PlanUnconfirmedError):
            MedicalWritingProtocolTemplateService(helper).section_seeds(definition)
        with pytest.raises(PlanUnconfirmedError):
            MedicalWritingTableTemplateService(
                plan_consumption_helper=helper
            ).instantiate(
                "schedule_of_activities",
                project_id=definition.project_id,
            )
        journey = MedicalWritingAuthoringJourneyService(root / "journey.sqlite3")
        journey.bind_plan_consumption_helper(helper)
        journey.get = lambda project_id: SimpleNamespace(
            study_definition=definition,
            framing_complete=True,
            picos_complete=True,
        )
        with pytest.raises(PlanUnconfirmedError):
            journey.propose_study_schema(definition.project_id)
        with pytest.raises(PlanUnconfirmedError):
            export_medical_writing_document_docx(
                ProtocolDocument(
                    document_id="missing-plan-doc",
                    project_id=definition.project_id,
                    protocol_id="MISSING",
                    version="V0.1",
                    sections=[
                        ProtocolSection(
                            section_id="s",
                            document_id="missing-plan-doc",
                            heading="总体设计",
                            content_blocks=[
                                {
                                    "block_id": "b",
                                    "block_type": "paragraph",
                                    "body_order": 1,
                                    "text": "不得导出",
                                }
                            ],
                        )
                    ],
                ),
                mode="draft_preview",
                plan_consumption_helper=helper,
            )
