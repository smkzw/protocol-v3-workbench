from datetime import datetime, timezone
from pathlib import Path
import tempfile
from xml.etree import ElementTree

import pytest

from packages.contracts.workbench_contracts import (
    MedicalWritingStudySchemaDefinition,
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingJourneyImpactPreviewRequest,
    MedicalWritingStudySchemaCommitRequest,
    MedicalWritingStudySchemaImpactPreviewRequest,
    MedicalWritingStudySchemaLayoutUpdateRequest,
    MedicalWritingStudySchemaFigureProjectRequest,
    MedicalWritingStudySchemaEdge,
    MedicalWritingStudySchemaLayoutOverride,
    MedicalWritingStudySchemaNode,
    MedicalWritingStudySchemaPart,
    MedicalWritingStudySchemaPresentation,
    MedicalWritingStudySchemaSourceBinding,
    MedicalWritingPhase1Part,
    MedicalWritingStructuredStudyDesign,
    MedicalWritingTreatmentSwitchDesign,
    MedicalWritingOpenLabelExtensionDesign,
)
from services.api.app.medical_writing_study_schema import (
    StudySchemaEdgeLabelLayoutError,
    formal_render_allowed,
    render_study_schema_png,
    render_study_schema_svg,
    study_schema_state_sha256,
    validate_study_schema,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyConflictError,
    MedicalWritingAuthoringJourneyService,
    _study_definition_facts_sha256,
)
from tests.test_medical_writing_authoring_journey import _complete_framing, _complete_picos


SOURCE_HASH = "a" * 64
STATE_HASH = "b" * 64


def _binding(path="picos.study_epochs"):
    return MedicalWritingStudySchemaSourceBinding(study_definition_path=path)


def _pnh_schema(status="confirmed"):
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    schema = MedicalWritingStudySchemaDefinition(
        schema_id="schema_pnh",
        revision=1,
        source_facts_sha256=SOURCE_HASH,
        status=status,
        parts=[
            MedicalWritingStudySchemaPart(
                part_id="main", order=0, label="随机平行剂量探索", source_bindings=[_binding()]
            )
        ],
        nodes=[
            MedicalWritingStudySchemaNode(
                node_id="screening", part_id="main", order=0, node_kind="screening",
                label="筛选期", fact_status="confirmed", source_bindings=[_binding()],
            ),
            MedicalWritingStudySchemaNode(
                node_id="randomize", part_id="main", order=1, node_kind="randomization",
                label="1:1随机", fact_status="confirmed", source_bindings=[_binding("framing.design_pattern")],
            ),
            MedicalWritingStudySchemaNode(
                node_id="low", part_id="main", order=2, lane_order=0, node_kind="arm", label="低剂量组",
                detail_lines=["具体剂量/频次待确认"], fact_status="confirmed", source_bindings=[_binding("picos.intervention_summary")],
            ),
            MedicalWritingStudySchemaNode(
                node_id="high", part_id="main", order=2, lane_order=1, node_kind="arm", label="高剂量组",
                detail_lines=["具体剂量/频次待确认"], fact_status="confirmed", source_bindings=[_binding("picos.intervention_summary")],
            ),
            MedicalWritingStudySchemaNode(
                node_id="followup", part_id="main", order=3, node_kind="follow_up",
                label="安全性随访", fact_status="confirmed", source_bindings=[_binding()],
            ),
        ],
        edges=[
            MedicalWritingStudySchemaEdge(
                edge_id="e1", from_node_id="screening", to_node_id="randomize",
                fact_status="confirmed", source_bindings=[_binding()],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="e2", from_node_id="randomize", to_node_id="low", edge_kind="randomization",
                label="1", fact_status="confirmed", source_bindings=[_binding("framing.design_pattern")],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="e3", from_node_id="randomize", to_node_id="high", edge_kind="randomization",
                label="1", fact_status="confirmed", source_bindings=[_binding("framing.design_pattern")],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="e4", from_node_id="low", to_node_id="followup", edge_kind="follow_up",
                fact_status="confirmed", source_bindings=[_binding()],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="e5", from_node_id="high", to_node_id="followup", edge_kind="follow_up",
                fact_status="confirmed", source_bindings=[_binding()],
            ),
        ],
        annotations=["具体剂量与给药频次须经医学确认后进入正式版本。"],
        state_sha256=STATE_HASH,
        updated_at=now,
        updated_by="medical_manager",
    )
    return schema.model_copy(update={"state_sha256": study_schema_state_sha256(schema)})


def _synthetic_ra_escalation_schema():
    """Synthetic counterexample only; it is not evidence for a real RA protocol."""

    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    binding = _binding("picos.intervention_summary")
    schema = MedicalWritingStudySchemaDefinition(
        schema_id="schema_ra_synthetic",
        revision=1,
        source_facts_sha256=SOURCE_HASH,
        status="confirmed",
        title="类风湿关节炎开放标签单臂剂量递增研究（合成反例）",
        parts=[
            MedicalWritingStudySchemaPart(
                part_id="main",
                order=0,
                label="开放标签、单臂、序贯剂量递增",
                flow_direction="top_to_bottom",
                source_bindings=[binding],
            )
        ],
        nodes=[
            MedicalWritingStudySchemaNode(
                node_id="screening",
                part_id="main",
                order=0,
                node_kind="screening",
                label="筛选期",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaNode(
                node_id="low_cohort",
                part_id="main",
                order=1,
                node_kind="dose_cohort",
                label="低剂量队列",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaNode(
                node_id="high_cohort",
                part_id="main",
                order=2,
                node_kind="dose_cohort",
                label="高剂量队列",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaNode(
                node_id="followup",
                part_id="main",
                order=3,
                node_kind="follow_up",
                label="安全性随访",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
        ],
        edges=[
            MedicalWritingStudySchemaEdge(
                edge_id="screening_to_low",
                from_node_id="screening",
                to_node_id="low_cohort",
                edge_kind="participant_flow",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="low_activates_high",
                from_node_id="low_cohort",
                to_node_id="high_cohort",
                edge_kind="activation_dependency",
                label="安全性审查通过后启用",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="low_to_followup",
                from_node_id="low_cohort",
                to_node_id="followup",
                edge_kind="follow_up",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="high_to_followup",
                from_node_id="high_cohort",
                to_node_id="followup",
                edge_kind="follow_up",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
        ],
        annotations=[
            "合成反例仅用于验证设计维度和边类型，不作为真实项目语料。",
        ],
        state_sha256=STATE_HASH,
        updated_at=now,
        updated_by="medical_manager_test",
    )
    return schema.model_copy(update={"state_sha256": study_schema_state_sha256(schema)})


def test_pnh_schema_renders_deterministically_without_executable_svg():
    schema = _pnh_schema()
    first = render_study_schema_svg(schema)
    second = render_study_schema_svg(schema)
    assert first == second
    assert "低剂量组" in first and "高剂量组" in first
    assert "每日一次" not in first
    assert "'Times New Roman', SimSun, 'Songti SC', serif" in first
    assert "Noto Sans CJK SC" not in first
    assert "Microsoft YaHei" not in first
    assert "<script" not in first and "foreignObject" not in first
    assert formal_render_allowed(schema, validate_study_schema(schema))


def test_long_single_part_flow_wraps_into_two_readable_rows():
    binding = _binding()
    nodes = [
        MedicalWritingStudySchemaNode(
            node_id=f"stage_{index}",
            part_id="main",
            order=index,
            node_kind=("screening" if index == 0 else "follow_up"),
            label=f"研究阶段{index + 1}",
            fact_status="confirmed",
            source_bindings=[binding],
        )
        for index in range(8)
    ]
    edges = [
        MedicalWritingStudySchemaEdge(
            edge_id=f"edge_{index}",
            from_node_id=f"stage_{index}",
            to_node_id=f"stage_{index + 1}",
            label="进入下一阶段",
            fact_status="confirmed",
            source_bindings=[binding],
        )
        for index in range(7)
    ]
    schema = _pnh_schema().model_copy(
        update={"nodes": nodes, "edges": edges},
        deep=True,
    )
    schema = schema.model_copy(
        update={"state_sha256": study_schema_state_sha256(schema)}
    )

    root = ElementTree.fromstring(render_study_schema_svg(schema))
    node_rects = [
        element
        for element in root.iter()
        if element.tag.endswith("rect")
        and element.attrib.get("width") == "168"
        and element.attrib.get("height") == "76"
    ]
    node_y_positions = {float(element.attrib["y"]) for element in node_rects}

    assert len(node_rects) == 8
    assert len(node_y_positions) == 2
    assert float(root.attrib["width"]) < 1600
    assert float(root.attrib["height"]) > 500


def test_pnh_schema_png_fallback_is_deterministic_and_contains_real_pixels():
    svg = render_study_schema_svg(_pnh_schema())
    first = render_study_schema_png(svg)
    second = render_study_schema_png(svg)
    assert first == second
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(first) > 10_000


@pytest.mark.parametrize(
    "payload",
    [
        '<svg width="100" height="100"><script>alert(1)</script></svg>',
        '<svg width="100" height="100"><image href="https://example.com/a.png"/></svg>',
        '<svg width="100" height="100"><foreignObject/></svg>',
    ],
)
def test_png_fallback_rejects_active_or_external_svg(payload):
    with pytest.raises(ValueError):
        render_study_schema_png(payload)


def test_figure_projection_request_and_layout_request_keep_separate_contracts():
    projection = MedicalWritingStudySchemaFigureProjectRequest(
        expected_journey_revision=3,
        expected_schema_revision=1,
        expected_layout_revision=0,
        expected_working_copy_revision=0,
        reason="医学经理确认将当前流程图插入方案第1.2节。",
        idempotency_key="projection-contract",
    )
    assert projection.expected_working_copy_revision == 0
    layout = MedicalWritingStudySchemaLayoutUpdateRequest(
        expected_journey_revision=3,
        expected_schema_revision=1,
        expected_layout_revision=0,
        node_overrides=[],
        idempotency_key="layout-contract",
    )
    assert layout.node_overrides == []


def test_layout_override_changes_position_but_not_clinical_state_hash():
    schema = _pnh_schema()
    presentation = MedicalWritingStudySchemaPresentation(
        schema_id=schema.schema_id,
        schema_revision=schema.revision,
        source_schema_sha256=schema.state_sha256,
        layout_revision=1,
        node_overrides=[MedicalWritingStudySchemaLayoutOverride(node_id="low", dx=24, dy=-8)],
        updated_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        updated_by="medical_manager",
    )
    assert render_study_schema_svg(schema, presentation) != render_study_schema_svg(schema)
    assert study_schema_state_sha256(schema) == schema.state_sha256


def test_semantic_hash_ignores_version_audit_metadata():
    schema = _pnh_schema()
    resaved = schema.model_copy(
        update={
            "revision": schema.revision + 1,
            "updated_at": datetime(2026, 7, 17, tzinfo=timezone.utc),
            "updated_by": "medical_director",
        }
    )
    assert study_schema_state_sha256(resaved) == schema.state_sha256


def test_parallel_arms_share_one_flow_order_but_render_in_distinct_lanes():
    schema = _pnh_schema()
    assert schema.nodes[2].order == schema.nodes[3].order == 2
    assert schema.nodes[2].lane_order != schema.nodes[3].lane_order
    svg = render_study_schema_svg(schema)
    assert svg.count('data-node-id="low"') == 1
    assert svg.count('data-node-id="high"') == 1


def test_long_node_detail_wraps_inside_the_svg_node_instead_of_overlapping():
    schema = _pnh_schema().model_copy(deep=True)
    long_detail = "MG-K10 300 mg 每2周皮下注射，持续24周，并维持稳定背景治疗。"
    schema.nodes[2].detail_lines = [long_detail]

    svg = render_study_schema_svg(schema)
    root = ElementTree.fromstring(svg)
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    node_group = next(
        group
        for group in root.findall(".//svg:g", namespace)
        if group.attrib.get("data-node-id") == "low"
    )
    rendered_lines = [
        element.text or "" for element in node_group.findall("svg:text", namespace)
    ]

    assert long_detail not in rendered_lines
    assert 2 <= len(rendered_lines) <= 4
    assert any("MG-K10 300 mg" in line for line in rendered_lines)


def test_open_label_and_dose_exploration_do_not_imply_single_arm_or_escalation():
    schema = _pnh_schema().model_copy(deep=True)
    schema.parts[0].label = "开放标签、平行、剂量探索"

    assert len([node for node in schema.nodes if node.node_kind == "arm"]) == 2
    assert not any(edge.edge_kind == "activation_dependency" for edge in schema.edges)
    svg = render_study_schema_svg(schema)
    assert "开放标签、平行、剂量探索" in svg
    assert "剂量递增" not in svg


def test_phase1_sad_mad_first_in_patient_proposal_is_multi_part_and_non_fabricating():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = MedicalWritingAuthoringJourneyService(
            Path(temp_dir) / "phase1_journey.sqlite3"
        )
        project_id = "proj_phase1_sad_mad_fip"
        framing = _complete_framing().model_copy(
            update={
                "study_phase": "I期",
                "intrinsic_objectives": [
                    "SAD模块",
                    "MAD模块",
                    "首次患者试验（first-in-patient）",
                ],
                "design_pattern": "开放标签、多部分、SAD序贯MAD并设SRC进入门的I期研究",
                "structured_design": MedicalWritingStructuredStudyDesign(
                    randomization_mode="non_randomized",
                    blinding_mode="open_label",
                    comparator_type="none_or_dose_escalation",
                    assignment_model="序贯剂量递增",
                    src_planned=True,
                    dmc_planned=False,
                    phase1_sequence="SAD完成安全性审查后启动MAD，再进入首次患者Part",
                    phase1_parts=[
                        MedicalWritingPhase1Part(
                            part_code="sad",
                            population="健康志愿者",
                            cohort_dose="SAD递增队列",
                            transition_dependencies="SRC审查后进入后续队列",
                        ),
                        MedicalWritingPhase1Part(
                            part_code="mad",
                            population="健康志愿者",
                            cohort_dose="MAD递增队列",
                            transition_dependencies="SAD安全性审查完成后启动",
                        ),
                        MedicalWritingPhase1Part(
                            part_code="first_in_patient",
                            population="目标适应症患者",
                            cohort_dose="患者剂量队列",
                            transition_dependencies="SAD/MAD审查完成后启动",
                        ),
                    ],
                ),
            },
            deep=True,
        )
        state = service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=framing,
                actor="medical_manager_test",
                idempotency_key="create-phase1-schema",
            ),
        )
        state = service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=state.revision,
                stage="picos",
                    picos=_complete_picos(
                        design_archetype="single_arm_early_phase",
                        comparator_summary="无平行对照；采用剂量递增队列设计。",
                    intervention_summary="研究药物按序贯剂量递增队列给药，具体剂量待确认。",
                    study_epochs=["筛选期", "给药与观察期", "安全性随访期"],
                ),
                actor="medical_manager_test",
                idempotency_key="commit-phase1-picos",
            ),
        )

        proposal = service.propose_study_schema(project_id)

        assert [part.part_id for part in proposal.parts] == [
            "part_sad",
            "part_mad",
            "part_first_in_patient",
        ]
        assert any(
            node.node_kind == "dose_cohort" and "起始剂量队列" in node.label
            for node in proposal.nodes
        )
        assert any(
            node.node_kind == "decision_gate" and node.label == "SRC安全性审查"
            for node in proposal.nodes
        )
        mad_screening = next(
            node for node in proposal.nodes if node.node_id == "mad_screening"
        )
        assert mad_screening.detail_lines == [
            "前一部分审查完成后启动（待确认）"
        ]
        assert not any(
            edge.from_node_id.startswith("sad_")
            and edge.to_node_id.startswith("mad_")
            for edge in proposal.edges
        )
        visible_text = " ".join(
            [
                *(part.label for part in proposal.parts),
                *(node.label for node in proposal.nodes),
                *(line for node in proposal.nodes for line in node.detail_lines),
                *(edge.label for edge in proposal.edges),
            ]
        )
        assert "mg" not in visible_text.lower()
        assert "具体剂量" not in visible_text
        assert "待确认" in visible_text
        assert all(node.fact_status == "extracted_candidate" for node in proposal.nodes)
        assert all(edge.fact_status == "extracted_candidate" for edge in proposal.edges)
        assert proposal.source_facts_sha256 == _study_definition_facts_sha256(
            state.framing, state.picos
        )
        svg = render_study_schema_svg(proposal)
        svg_root = ElementTree.fromstring(svg)
        assert int(svg_root.attrib["width"]) < int(svg_root.attrib["height"]) * 2
        part_title_y = [
            int(float(element.attrib["y"]))
            for element in svg_root.iter()
            if element.tag.endswith("text")
            and (element.text or "").startswith("Part ")
        ]
        assert part_title_y == sorted(part_title_y)
        assert len(set(part_title_y)) == 3


def test_phase1_special_modules_generate_distinct_parts_without_assuming_exact_design():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = MedicalWritingAuthoringJourneyService(
            Path(temp_dir) / "phase1_special.sqlite3"
        )
        project_id = "proj_phase1_special_modules"
        framing = _complete_framing().model_copy(
            update={
                "study_phase": "Phase I",
                "intrinsic_objectives": [
                    "食物影响",
                    "物质平衡",
                    "肝功能不全",
                    "肾功能不全",
                    "DDI模块",
                ],
                "design_pattern": "开放标签、多部分I期研究",
                "structured_design": MedicalWritingStructuredStudyDesign(
                    randomization_mode="non_randomized",
                    blinding_mode="open_label",
                    comparator_type="none_or_dose_escalation",
                    src_planned=False,
                    dmc_planned=False,
                    phase1_parts=[
                        MedicalWritingPhase1Part(
                            part_code=code,
                            population="按模块定义的受试者",
                            cohort_dose="按模块定义的给药队列",
                        )
                        for code in (
                            "food_effect",
                            "mass_balance",
                            "hepatic_impairment",
                            "renal_impairment",
                            "ddi",
                        )
                    ],
                ),
            },
            deep=True,
        )
        state = service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=framing,
                actor="medical_manager_test",
                idempotency_key="create-phase1-special",
            ),
        )
        service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=state.revision,
                stage="picos",
                    picos=_complete_picos(
                        design_archetype="single_arm_early_phase",
                        comparator_summary="无平行对照；采用专项模块设计。",
                    study_epochs=["筛选期", "给药/评价期", "安全性随访期"],
                ),
                actor="medical_manager_test",
                idempotency_key="commit-phase1-special-picos",
            ),
        )

        proposal = service.propose_study_schema(project_id)

        assert [part.part_id for part in proposal.parts] == [
            "part_food_effect",
            "part_mass_balance",
            "part_hepatic_impairment",
            "part_renal_impairment",
            "part_ddi",
        ]
        labels = {node.label for node in proposal.nodes}
        assert "空腹/餐后给药条件（设计待确认）" in labels
        assert "肝功能不全与匹配对照队列" in labels
        assert "肾功能不全与匹配对照队列" in labels
        assert "单药与联用阶段（设计待确认）" in labels
        assert all(node.fact_status == "extracted_candidate" for node in proposal.nodes)


def test_phase3_placebo_switch_and_ole_keep_distinct_transition_semantics():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = MedicalWritingAuthoringJourneyService(
            Path(temp_dir) / "phase3_switch.sqlite3"
        )
        project_id = "proj_phase3_placebo_switch"
        framing = _complete_framing().model_copy(
            update={
                "study_phase": "III期",
                "design_pattern": (
                    "随机、双盲、安慰剂对照；第16周安慰剂组转为研究药物，"
                    "随后进入开放标签延展期"
                ),
                "structured_design": MedicalWritingStructuredStudyDesign(
                    randomization_mode="randomized",
                    blinding_mode="double_blind",
                    comparator_type="placebo",
                    comparator_intervention="匹配安慰剂",
                    assignment_model="平行分组",
                    treatment_switch=MedicalWritingTreatmentSwitchDesign(
                        planned=True,
                        trigger_or_timing="第16周治疗转组",
                        eligible_population="完成双盲期的安慰剂组受试者",
                        destination_treatment="研究药物",
                        blinding_strategy="第16周按方案揭盲后转组",
                        analysis_handling="转组前后按估计目标和治疗策略分析",
                    ),
                    open_label_extension=MedicalWritingOpenLabelExtensionDesign(
                        planned=True,
                        entry_source="完成双盲对照期的受试者",
                        entry_eligibility="完成第16周评价且符合延展入组条件",
                        treatment_regimen="研究药物开放标签治疗",
                        duration="长期延展期",
                        blind_break_and_transition="第16周揭盲并按原分组衔接",
                        long_term_objectives=["长期安全性", "疗效维持"],
                    ),
                    src_planned=False,
                    dmc_planned=True,
                ),
            },
            deep=True,
        )
        state = service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=framing,
                actor="medical_manager_test",
                idempotency_key="create-phase3-switch",
            ),
        )
        service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=state.revision,
                stage="picos",
                picos=_complete_picos(
                    design_archetype="randomized_confirmatory",
                    intervention_summary="研究药物组按方案持续治疗。",
                    comparator_summary="安慰剂组在第16周转为研究药物。",
                    study_epochs=[
                        "筛选期",
                        "双盲安慰剂对照期",
                        "第16周治疗转组",
                        "开放标签延展期",
                        "安全性随访期",
                    ],
                ),
                actor="medical_manager_test",
                idempotency_key="commit-phase3-switch-picos",
            ),
        )

        proposal = service.propose_study_schema(project_id)

        switch_node = next(
            node for node in proposal.nodes if node.node_kind == "treatment_switch"
        )
        extension_node = next(
            node for node in proposal.nodes if node.node_kind == "extension_period"
        )
        comparator_switch = next(
            edge
            for edge in proposal.edges
            if edge.from_node_id == "comparator"
            and edge.to_node_id == switch_node.node_id
        )
        intervention_continuation = next(
            edge
            for edge in proposal.edges
            if edge.from_node_id == "intervention"
            and edge.to_node_id == switch_node.node_id
        )
        assert comparator_switch.edge_kind == "treatment_switch"
        assert comparator_switch.label == "转组治疗"
        assert intervention_continuation.edge_kind == "treatment_continuation"
        assert intervention_continuation.label == "继续治疗"
        assert any(
            edge.from_node_id == switch_node.node_id
            and edge.to_node_id == extension_node.node_id
            and edge.edge_kind == "participant_flow"
            for edge in proposal.edges
        )
        assert not any(
            node.node_kind == "treatment"
            and node.label == "双盲安慰剂对照期"
            for node in proposal.nodes
        )
        assert all(
            "双盲安慰剂对照期" in node.detail_lines
            for node in proposal.nodes
            if node.node_kind == "arm"
        )
        svg = render_study_schema_svg(proposal)
        assert 'data-edge-kind="treatment_switch"' in svg
        assert 'data-edge-kind="treatment_continuation"' in svg
        assert 'stroke="#ea580c"' in svg
        assert 'stroke="#15803d"' in svg
        assert "随后进入开放标签延展期" not in svg


def test_ole_without_explicit_switch_keeps_entry_treatment_as_unresolved():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = MedicalWritingAuthoringJourneyService(
            Path(temp_dir) / "phase3_ole_unspecified.sqlite3"
        )
        project_id = "proj_phase3_ole_unspecified"
        framing = _complete_framing().model_copy(
            update={
                "study_phase": "III期",
                "design_pattern": "随机、双盲、安慰剂对照并设开放标签延展期",
                "structured_design": MedicalWritingStructuredStudyDesign(
                    randomization_mode="randomized",
                    blinding_mode="double_blind",
                    comparator_type="placebo",
                    assignment_model="平行分组",
                    treatment_switch=MedicalWritingTreatmentSwitchDesign(
                        planned=False
                    ),
                    open_label_extension=MedicalWritingOpenLabelExtensionDesign(
                        planned=True,
                        entry_source="完成双盲治疗期的受试者",
                        entry_eligibility="完成规定评价且符合延展条件",
                        treatment_regimen="延展期治疗方案待医学确认",
                        duration="开放标签延展期",
                        blind_break_and_transition="进入延展期的治疗衔接尚待确认",
                        long_term_objectives=["长期安全性"],
                    ),
                    src_planned=False,
                    dmc_planned=True,
                ),
            },
            deep=True,
        )
        state = service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=framing,
                actor="medical_manager_test",
                idempotency_key="create-phase3-ole-unspecified",
            ),
        )
        service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=state.revision,
                stage="picos",
                picos=_complete_picos(
                    design_archetype="randomized_confirmatory",
                    intervention_summary="研究药物组按方案治疗。",
                    comparator_summary="安慰剂对照。",
                    study_epochs=[
                        "筛选期",
                        "双盲治疗期",
                        "开放标签延展期",
                        "安全性随访期",
                    ],
                ),
                actor="medical_manager_test",
                idempotency_key="commit-phase3-ole-unspecified-picos",
            ),
        )

        proposal = service.propose_study_schema(project_id)
        extension_node = next(
            node for node in proposal.nodes if node.node_kind == "extension_period"
        )
        entry_edges = [
            edge
            for edge in proposal.edges
            if edge.to_node_id == extension_node.node_id
        ]
        assert len(entry_edges) == 2
        assert all(edge.edge_kind == "conditional" for edge in entry_edges)
        assert all(edge.fact_status == "missing" for edge in entry_edges)
        assert all(edge.label == "延展期治疗方式待确认" for edge in entry_edges)
        assert not any(edge.edge_kind == "treatment_switch" for edge in proposal.edges)


def test_synthetic_ra_escalation_uses_activation_dependency_not_participant_transfer():
    schema = _synthetic_ra_escalation_schema()
    cohort_edge = next(edge for edge in schema.edges if edge.edge_id == "low_activates_high")

    assert cohort_edge.edge_kind == "activation_dependency"
    assert not any(
        edge.edge_kind == "participant_flow"
        and edge.from_node_id == "low_cohort"
        and edge.to_node_id == "high_cohort"
        for edge in schema.edges
    )
    svg = render_study_schema_svg(schema)
    assert 'data-edge-kind="activation_dependency"' in svg
    assert "安全性审查通过后启用" in svg
    assert "合成反例仅用于验证设计维度和边类型" in svg


def test_unconfirmed_fact_blocks_formal_render():
    schema = _pnh_schema().model_copy(deep=True)
    schema.nodes[2].fact_status = "conflict"
    issues = validate_study_schema(schema)
    assert any(issue.code == "node_conflict" and issue.severity == "blocker" for issue in issues)
    assert not formal_render_allowed(schema, issues)


def test_dose_cohort_progression_cannot_be_mislabeled_as_participant_flow():
    schema = _pnh_schema().model_dump(mode="python")
    schema["nodes"][2]["node_kind"] = "dose_cohort"
    schema["nodes"][3]["node_kind"] = "dose_cohort"
    schema["edges"][2] = {
        "edge_id": "bad",
        "from_node_id": "low",
        "to_node_id": "high",
        "edge_kind": "participant_flow",
        "fact_status": "confirmed",
        "source_bindings": [{"study_definition_path": "picos.intervention_summary"}],
    }
    with pytest.raises(ValueError, match="activation_dependency"):
        MedicalWritingStudySchemaDefinition.model_validate(schema)


def test_edge_labels_have_deterministic_background_and_dependency_kind():
    schema = _pnh_schema().model_copy(deep=True)
    schema.edges[2] = MedicalWritingStudySchemaEdge(
        edge_id="activation",
        from_node_id="low",
        to_node_id="high",
        edge_kind="activation_dependency",
        label="至少72 h安全性评估/SRC",
        fact_status="confirmed",
        source_bindings=[_binding("picos.intervention_summary")],
    )
    svg = render_study_schema_svg(schema)
    assert 'data-edge-kind="activation_dependency"' in svg
    assert svg.count('class="study-schema-edge-label-bg"') == sum(
        bool(edge.label) for edge in schema.edges
    )
    assert 'class="study-schema-edge-label"' in svg
    assert "至少72 h安全性评估/SRC" in svg


def _svg_node_boxes(root: ElementTree.Element) -> dict[str, tuple[float, float, float, float]]:
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for group in root.iter():
        if not str(group.tag).endswith("g"):
            continue
        node_id = group.attrib.get("data-node-id")
        if not node_id:
            continue
        rect = next(
            (
                child
                for child in group
                if str(child.tag).endswith("rect")
            ),
            None,
        )
        if rect is None:
            continue
        boxes[node_id] = (
            float(rect.attrib["x"]),
            float(rect.attrib["y"]),
            float(rect.attrib["width"]),
            float(rect.attrib["height"]),
        )
    return boxes


def _svg_edge_label_boxes(
    root: ElementTree.Element,
) -> list[tuple[float, float, float, float]]:
    boxes: list[tuple[float, float, float, float]] = []
    for element in root.iter():
        if (
            str(element.tag).endswith("rect")
            and element.attrib.get("class") == "study-schema-edge-label-bg"
        ):
            boxes.append(
                (
                    float(element.attrib["x"]),
                    float(element.attrib["y"]),
                    float(element.attrib["width"]),
                    float(element.attrib["height"]),
                )
            )
    return boxes


def _svg_edge_label_texts(root: ElementTree.Element) -> list[str]:
    return [
        element.text or ""
        for element in root.iter()
        if str(element.tag).endswith("text")
        and element.attrib.get("class") == "study-schema-edge-label"
    ]


def _svg_edge_label_groups(
    root: ElementTree.Element,
) -> dict[str, list[str]]:
    """Map data-edge-label-for -> ordered label text lines."""
    groups: dict[str, list[str]] = {}
    for element in root.iter():
        if not str(element.tag).endswith("g"):
            continue
        edge_id = element.attrib.get("data-edge-label-for")
        if not edge_id:
            continue
        lines = [
            child.text or ""
            for child in element
            if str(child.tag).endswith("text")
            and child.attrib.get("class") == "study-schema-edge-label"
        ]
        groups[edge_id] = lines
    return groups


def _normalized_label(value: str) -> str:
    return " ".join(str(value).split())


def _assert_all_edge_labels_clear_of_nodes_and_canvas(root: ElementTree.Element) -> None:
    canvas_w = float(root.attrib["width"])
    canvas_h = float(root.attrib["height"])
    margin = 4.0
    nodes = _svg_node_boxes(root)
    for box in _svg_edge_label_boxes(root):
        left, top, width, height = box
        assert left >= margin - 0.01
        assert top >= margin - 0.01
        assert left + width <= canvas_w - margin + 0.01
        assert top + height <= canvas_h - margin + 0.01
        for node_id, node_box in nodes.items():
            assert not _rects_overlap(*box, node_box, gap=2), (
                f"label {box} overlaps node {node_id} {node_box}"
            )


def _rects_overlap(
    left: float,
    top: float,
    width: float,
    height: float,
    box: tuple[float, float, float, float],
    *,
    gap: float = 0.0,
) -> bool:
    bx, by, bw, bh = box
    return not (
        left + width + gap <= bx
        or bx + bw + gap <= left
        or top + height + gap <= by
        or by + bh + gap <= top
    )


def _conditional_safety_branch_schema(
    *,
    long_label: str = "240 mg BID安全性不佳",
    short_label: str = "安全性可接受",
):
    """Generic branched conditional labels; not a project-specific branch."""
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    binding = _binding("picos.intervention_summary")
    schema = MedicalWritingStudySchemaDefinition(
        schema_id="schema_conditional_label_geometry",
        revision=1,
        source_facts_sha256=SOURCE_HASH,
        status="confirmed",
        title="条件分支标签几何回归",
        parts=[
            MedicalWritingStudySchemaPart(
                part_id="main",
                order=0,
                label="随机对照剂量探索",
                source_bindings=[binding],
            )
        ],
        nodes=[
            MedicalWritingStudySchemaNode(
                node_id="screen",
                part_id="main",
                order=0,
                node_kind="screening",
                label="筛选期",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaNode(
                node_id="randomize",
                part_id="main",
                order=1,
                node_kind="randomization",
                label="随机分组",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaNode(
                node_id="arm_a",
                part_id="main",
                order=2,
                lane_order=0,
                node_kind="arm",
                label="A组",
                detail_lines=["较低剂量或对照"],
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaNode(
                node_id="arm_b",
                part_id="main",
                order=2,
                lane_order=1,
                node_kind="arm",
                label="B组",
                detail_lines=["较高剂量或对照"],
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaNode(
                node_id="gate",
                part_id="main",
                order=3,
                node_kind="decision_gate",
                label="累积安全性评估",
                detail_lines=["前若干例完成关键访视"],
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaNode(
                node_id="continue_arm",
                part_id="main",
                order=4,
                lane_order=0,
                node_kind="treatment",
                label="继续各组入组",
                detail_lines=["安全性可接受"],
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaNode(
                node_id="switch_arm",
                part_id="main",
                order=4,
                lane_order=1,
                node_kind="allocation",
                label="停止高剂量并调整",
                detail_lines=["后续仅入较低剂量组"],
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaNode(
                node_id="follow",
                part_id="main",
                order=5,
                node_kind="follow_up",
                label="治疗、评估与随访",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
        ],
        edges=[
            MedicalWritingStudySchemaEdge(
                edge_id="e1",
                from_node_id="screen",
                to_node_id="randomize",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="e2",
                from_node_id="randomize",
                to_node_id="arm_a",
                edge_kind="randomization",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="e3",
                from_node_id="randomize",
                to_node_id="arm_b",
                edge_kind="randomization",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="e4",
                from_node_id="arm_a",
                to_node_id="gate",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="e5",
                from_node_id="arm_b",
                to_node_id="gate",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="e6",
                from_node_id="gate",
                to_node_id="continue_arm",
                edge_kind="conditional",
                label=short_label,
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="e7",
                from_node_id="gate",
                to_node_id="switch_arm",
                edge_kind="conditional",
                label=long_label,
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="e8",
                from_node_id="continue_arm",
                to_node_id="follow",
                edge_kind="follow_up",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="e9",
                from_node_id="switch_arm",
                to_node_id="follow",
                edge_kind="follow_up",
                fact_status="confirmed",
                source_bindings=[binding],
            ),
        ],
        annotations=["条件标签几何回归夹具。"],
        state_sha256=STATE_HASH,
        updated_at=now,
        updated_by="medical_manager_test",
    )
    return schema.model_copy(update={"state_sha256": study_schema_state_sha256(schema)})


def test_long_mixed_conditional_edge_label_avoids_endpoint_node_rects():
    long_label = "240 mg BID安全性不佳"
    schema = _conditional_safety_branch_schema(long_label=long_label)
    svg = render_study_schema_svg(schema)
    png = render_study_schema_png(svg)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")

    root = ElementTree.fromstring(svg)
    groups = _svg_edge_label_groups(root)
    assert "e7" in groups
    assert "".join(groups["e7"]) == _normalized_label(long_label)
    assert "".join(groups["e6"]) == "安全性可接受"
    assert groups["e7"]  # association via data-edge-label-for
    _assert_all_edge_labels_clear_of_nodes_and_canvas(root)
    assert "累积安全性评估" in svg
    assert "继续各组入组" in svg


def test_long_edge_label_near_canvas_edge_stays_inside_viewbox():
    schema = _pnh_schema().model_copy(deep=True)
    long_label = "超长边缘标签用于画布边界夹具ABCDEFG安全性审查通过后方可启用下一队列"
    schema.edges[1] = MedicalWritingStudySchemaEdge(
        edge_id="e2",
        from_node_id="randomize",
        to_node_id="low",
        edge_kind="randomization",
        label=long_label,
        fact_status="confirmed",
        source_bindings=[_binding("framing.design_pattern")],
    )
    svg = render_study_schema_svg(schema)
    png = render_study_schema_png(svg)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")

    root = ElementTree.fromstring(svg)
    _assert_all_edge_labels_clear_of_nodes_and_canvas(root)
    groups = _svg_edge_label_groups(root)
    assert "".join(groups["e2"]) == _normalized_label(long_label)


def test_short_edge_labels_and_node_text_still_render_with_png():
    schema = _pnh_schema()
    svg = render_study_schema_svg(schema)
    png = render_study_schema_png(svg)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) > 10_000

    root = ElementTree.fromstring(svg)
    groups = _svg_edge_label_groups(root)
    assert groups["e2"] == ["1"]
    assert groups["e3"] == ["1"]
    assert 'data-node-id="low"' in svg
    assert 'data-node-id="high"' in svg
    assert "低剂量组" in svg
    assert "高剂量组" in svg
    assert "筛选期" in svg
    _assert_all_edge_labels_clear_of_nodes_and_canvas(root)

    activation = _synthetic_ra_escalation_schema()
    activation_svg = render_study_schema_svg(activation)
    activation_png = render_study_schema_png(activation_svg)
    assert activation_png.startswith(b"\x89PNG\r\n\x1a\n")
    activation_root = ElementTree.fromstring(activation_svg)
    activation_groups = _svg_edge_label_groups(activation_root)
    assert "".join(activation_groups["low_activates_high"]) == "安全性审查通过后启用"
    assert 'data-edge-kind="activation_dependency"' in activation_svg
    _assert_all_edge_labels_clear_of_nodes_and_canvas(activation_root)


def test_near_max_mixed_edge_label_preserves_full_normalized_text():
    # Edge label contract max_length=300; preserve every normalized character.
    seed = (
        "SRC review after 72h cumulative safety review of 240 mg BID cohort "
        "安全性审查通过后启用下一队列并记录剂量调整与随访计划"
        "A1B2C3安全性门控"
    )
    long_label = seed
    while len(long_label) < 295:
        long_label += "X9全"
    long_label = long_label[:300]
    assert 290 <= len(long_label) <= 300

    schema = _conditional_safety_branch_schema(long_label=long_label)
    svg = render_study_schema_svg(schema)
    png = render_study_schema_png(svg)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    root = ElementTree.fromstring(svg)
    groups = _svg_edge_label_groups(root)
    assert "".join(groups["e7"]) == _normalized_label(long_label)
    assert all(
        element.attrib.get("data-edge-label-for")
        for element in root.iter()
        if str(element.tag).endswith("g")
        and element.attrib.get("class") == "study-schema-edge-label-group"
    )
    _assert_all_edge_labels_clear_of_nodes_and_canvas(root)


def test_edge_labels_carry_data_edge_label_for_association():
    schema = _conditional_safety_branch_schema()
    svg = render_study_schema_svg(schema)
    root = ElementTree.fromstring(svg)
    groups = _svg_edge_label_groups(root)
    labeled_edges = {
        edge.edge_id: _normalized_label(edge.label)
        for edge in schema.edges
        if edge.label
    }
    assert set(groups) == set(labeled_edges)
    for edge_id, expected in labeled_edges.items():
        assert "".join(groups[edge_id]) == expected
        assert f'data-edge-label-for="{edge_id}"' in svg


def test_real_ibdq_fixture_edge_labels_preserve_clip_regression_and_geometry():
    from records.active_slices.medical_writing_real_scale_word_e5_20260724.scripts.run_real_ibdq_docx_gate import (
        my009_uc_schema,
    )

    schema = my009_uc_schema()
    svg = render_study_schema_svg(schema)
    png = render_study_schema_png(svg)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    root = ElementTree.fromstring(svg)
    groups = _svg_edge_label_groups(root)
    assert "".join(groups["uc_8"]) == "240 mg BID安全性不佳"
    assert "".join(groups["uc_7"]) == "安全性可接受"
    _assert_all_edge_labels_clear_of_nodes_and_canvas(root)


def test_dense_edge_labels_reflow_or_fail_closed_never_overlap():
    """Deliberately dense labels: expand/reflow success or explicit error only."""
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    binding = _binding("picos.intervention_summary")
    # Many parallel lanes with long labels on short hops.
    long = (
        "240 mg BID安全性不佳且需要完整保留全部字符的密集布局夹具"
        "SRC cumulative review gate activation dependency switch continuation"
    )
    nodes = [
        MedicalWritingStudySchemaNode(
            node_id="n0",
            part_id="main",
            order=0,
            node_kind="screening",
            label="起点",
            fact_status="confirmed",
            source_bindings=[binding],
        )
    ]
    edges = []
    for index in range(6):
        node_id = f"n{index + 1}"
        nodes.append(
            MedicalWritingStudySchemaNode(
                node_id=node_id,
                part_id="main",
                order=1,
                lane_order=index,
                node_kind="arm",
                label=f"队列{index + 1}",
                detail_lines=["密集布局"],
                fact_status="confirmed",
                source_bindings=[binding],
            )
        )
        edges.append(
            MedicalWritingStudySchemaEdge(
                edge_id=f"dense_{index}",
                from_node_id="n0",
                to_node_id=node_id,
                edge_kind="conditional",
                label=f"{long}-{index}",
                fact_status="confirmed",
                source_bindings=[binding],
            )
        )
    schema = MedicalWritingStudySchemaDefinition(
        schema_id="schema_dense_edge_labels",
        revision=1,
        source_facts_sha256=SOURCE_HASH,
        status="confirmed",
        title="密集边标签布局夹具",
        parts=[
            MedicalWritingStudySchemaPart(
                part_id="main",
                order=0,
                label="密集布局",
                source_bindings=[binding],
            )
        ],
        nodes=nodes,
        edges=edges,
        state_sha256=STATE_HASH,
        updated_at=now,
        updated_by="medical_manager_test",
    )
    schema = schema.model_copy(
        update={"state_sha256": study_schema_state_sha256(schema)}
    )

    try:
        svg = render_study_schema_svg(schema)
    except StudySchemaEdgeLabelLayoutError as exc:
        assert "cannot be placed" in str(exc)
        return

    png = render_study_schema_png(svg)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    root = ElementTree.fromstring(svg)
    groups = _svg_edge_label_groups(root)
    for index in range(6):
        edge_id = f"dense_{index}"
        assert "".join(groups[edge_id]) == _normalized_label(f"{long}-{index}")
    _assert_all_edge_labels_clear_of_nodes_and_canvas(root)


def test_xml_text_is_escaped_in_server_render():
    schema = _pnh_schema().model_copy(deep=True)
    schema.nodes[0].label = "筛选 < D-1 & 合格"
    svg = render_study_schema_svg(schema)
    assert "筛选 &lt; D-1 &amp; 合格" in svg
    assert "筛选 < D-1" not in svg


def _complete_journey(service, project_id="proj_schema_pnh"):
    state = service.create(
        project_id,
        MedicalWritingAuthoringJourneyCreateRequest(
            framing=_complete_framing(),
            actor="medical_manager_test",
            idempotency_key=f"create-{project_id}",
        ),
    )
    return service.commit_stage(
        project_id,
        MedicalWritingAuthoringJourneyCommitRequest(
            expected_revision=state.revision,
            stage="picos",
            picos=_complete_picos(),
            actor="medical_manager_test",
            idempotency_key=f"picos-{project_id}",
        ),
    )


def test_study_schema_commit_and_layout_share_authoring_journey_transaction():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = MedicalWritingAuthoringJourneyService(Path(temp_dir) / "journey.sqlite3")
        state = _complete_journey(service)
        facts_sha = _study_definition_facts_sha256(state.framing, state.picos)
        proposed = _pnh_schema().model_copy(update={"source_facts_sha256": facts_sha})
        proposed = proposed.model_copy(
            update={"state_sha256": study_schema_state_sha256(proposed)}
        )
        preview = service.study_schema_impact_preview(
            state.project_id,
            MedicalWritingStudySchemaImpactPreviewRequest(
                expected_journey_revision=state.revision,
                study_schema=proposed,
            ),
        )
        committed = service.commit_study_schema(
            state.project_id,
            MedicalWritingStudySchemaCommitRequest(
                expected_journey_revision=state.revision,
                study_schema=proposed,
                impact_preview_id=preview.preview_id,
                reason="医学经理已核对研究分组、随机与随访关系。",
                actor="medical_manager_test",
                idempotency_key="commit-schema-pnh",
            ),
        )
        assert committed.formal_render_allowed
        assert committed.study_schema.schema_id.startswith("mwschema_")
        clinical_hash = committed.study_schema.state_sha256
        layout = service.update_study_schema_layout(
            state.project_id,
            MedicalWritingStudySchemaLayoutUpdateRequest(
                expected_journey_revision=committed.journey_revision,
                expected_schema_revision=committed.study_schema.revision,
                expected_layout_revision=committed.presentation.layout_revision,
                node_overrides=[
                    MedicalWritingStudySchemaLayoutOverride(node_id="low", dx=18, dy=-6)
                ],
                actor="medical_manager_test",
                idempotency_key="layout-schema-pnh",
            ),
        )
        assert layout.study_schema.state_sha256 == clinical_hash
        assert layout.presentation.layout_revision == committed.presentation.layout_revision + 1
        reloaded = MedicalWritingAuthoringJourneyService(
            Path(temp_dir) / "journey.sqlite3"
        ).study_schema_snapshot(state.project_id)
        assert reloaded.presentation.node_overrides[0].node_id == "low"
        assert reloaded.svg_sha256 == layout.svg_sha256


def test_stale_layout_and_unbound_schema_writes_fail_closed():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = MedicalWritingAuthoringJourneyService(Path(temp_dir) / "journey.sqlite3")
        state = _complete_journey(service, "proj_schema_stale")
        proposed = _pnh_schema().model_copy(update={"source_facts_sha256": "f" * 64})
        with pytest.raises(
            MedicalWritingAuthoringJourneyConflictError, match="not bound"
        ):
            service.study_schema_impact_preview(
                state.project_id,
                MedicalWritingStudySchemaImpactPreviewRequest(
                    expected_journey_revision=state.revision,
                    study_schema=proposed,
                ),
            )


def test_stale_committed_schema_can_be_reproposed_from_current_study_facts():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = MedicalWritingAuthoringJourneyService(
            Path(temp_dir) / "stale_reproposal.sqlite3"
        )
        state = _complete_journey(service, "proj_schema_reproposal")
        current_facts_sha = _study_definition_facts_sha256(
            state.framing, state.picos
        )
        proposed = _pnh_schema().model_copy(
            update={"source_facts_sha256": current_facts_sha}, deep=True
        )
        proposed = proposed.model_copy(
            update={"state_sha256": study_schema_state_sha256(proposed)}, deep=True
        )
        schema_preview = service.study_schema_impact_preview(
            state.project_id,
            MedicalWritingStudySchemaImpactPreviewRequest(
                expected_journey_revision=state.revision,
                study_schema=proposed,
            ),
        )
        committed = service.commit_study_schema(
            state.project_id,
            MedicalWritingStudySchemaCommitRequest(
                expected_journey_revision=state.revision,
                study_schema=proposed,
                impact_preview_id=schema_preview.preview_id,
                reason="医学经理确认初始研究流程图事实。",
                actor="medical_manager_test",
                idempotency_key="commit-before-reproposal",
            ),
        )
        changed_picos = committed.study_schema and state.picos.model_copy(
            update={"visit_strategy": state.picos.visit_strategy + " 增加一次电话随访。"},
            deep=True,
        )
        assert changed_picos is not None
        journey_preview = service.impact_preview(
            state.project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=committed.journey_revision,
                stage="picos",
                picos=changed_picos,
            ),
        )
        changed = service.commit_stage(
            state.project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=committed.journey_revision,
                stage="picos",
                picos=changed_picos,
                impact_preview_id=journey_preview.preview_id,
                actor="medical_manager_test",
                idempotency_key="change-picos-before-reproposal",
            ),
        )

        stale_snapshot = service.study_schema_snapshot(state.project_id)
        refreshed = service.propose_study_schema(state.project_id)

        assert stale_snapshot.study_schema.status == "stale"
        assert refreshed.status == "draft"
        assert refreshed.source_facts_sha256 == _study_definition_facts_sha256(
            changed.framing, changed.picos
        )
        assert refreshed.source_facts_sha256 != proposed.source_facts_sha256
