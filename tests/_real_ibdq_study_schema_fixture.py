"""Deterministic IBDQ study-schema fixture used by compatibility tests.

The fixture was promoted from a historical active-slice script so tests no
longer depend on process records that are deliberately absent from clean source
worktrees.
"""

from __future__ import annotations

from datetime import datetime, timezone

from packages.contracts.workbench_contracts import (
    MedicalWritingStudySchemaDefinition,
    MedicalWritingStudySchemaEdge,
    MedicalWritingStudySchemaNode,
    MedicalWritingStudySchemaPart,
    MedicalWritingStudySchemaSourceBinding,
)
from services.api.app.medical_writing_study_schema import (
    study_schema_state_sha256,
    validate_study_schema,
)


def build_real_ibdq_study_schema() -> MedicalWritingStudySchemaDefinition:
    source = MedicalWritingStudySchemaSourceBinding(
        source_id="MY009_UC_phase2_protocol",
        locator="docx:section:4:研究设计及安全性驱动的S2停止/转组规则",
    )
    schema = MedicalWritingStudySchemaDefinition(
        schema_id="schema_my009_uc_real_e5_20260724",
        title="MY009212A中重度溃疡性结肠炎研究设计概况",
        source_facts_sha256="a" * 64,
        state_sha256="0" * 64,
        status="confirmed",
        revision=1,
        updated_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        updated_by="medical_manager_real_ibdq_word_e5",
        parts=[
            MedicalWritingStudySchemaPart(
                part_id="main",
                order=0,
                label="随机、双盲、安慰剂对照、剂量递增",
                source_bindings=[source],
            )
        ],
        nodes=[
            MedicalWritingStudySchemaNode(
                node_id="uc_screen",
                part_id="main",
                order=0,
                node_kind="screening",
                label="筛选期",
                detail_lines=["3周筛选访视"],
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaNode(
                node_id="uc_runin",
                part_id="main",
                order=1,
                node_kind="run_in",
                label="单盲安慰剂导入期",
                detail_lines=["1周"],
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaNode(
                node_id="uc_random",
                part_id="main",
                order=2,
                node_kind="randomization",
                label="随机分组",
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaNode(
                node_id="uc_s1",
                part_id="main",
                order=3,
                lane_order=0,
                node_kind="arm",
                label="S1组",
                detail_lines=["160 mg BID或安慰剂"],
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaNode(
                node_id="uc_s2",
                part_id="main",
                order=3,
                lane_order=1,
                node_kind="arm",
                label="S2组",
                detail_lines=["240 mg BID或安慰剂"],
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaNode(
                node_id="uc_gate",
                part_id="main",
                order=4,
                node_kind="decision_gate",
                label="累积安全性评估",
                detail_lines=["S1/S2各前8例完成D7"],
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaNode(
                node_id="uc_continue",
                part_id="main",
                order=5,
                lane_order=0,
                node_kind="treatment",
                label="继续S1与S2入组",
                detail_lines=["安全性可接受"],
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaNode(
                node_id="uc_switch",
                part_id="main",
                order=5,
                lane_order=1,
                node_kind="allocation",
                label="停止S2并调整",
                detail_lines=["后续仅入S1", "S2受试者降至160 mg BID"],
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaNode(
                node_id="uc_follow",
                part_id="main",
                order=6,
                node_kind="follow_up",
                label="治疗、评估与随访",
                fact_status="confirmed",
                source_bindings=[source],
            ),
        ],
        edges=[
            MedicalWritingStudySchemaEdge(
                edge_id="uc_1",
                from_node_id="uc_screen",
                to_node_id="uc_runin",
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="uc_2",
                from_node_id="uc_runin",
                to_node_id="uc_random",
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="uc_3",
                from_node_id="uc_random",
                to_node_id="uc_s1",
                edge_kind="randomization",
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="uc_4",
                from_node_id="uc_random",
                to_node_id="uc_s2",
                edge_kind="randomization",
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="uc_5",
                from_node_id="uc_s1",
                to_node_id="uc_gate",
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="uc_6",
                from_node_id="uc_s2",
                to_node_id="uc_gate",
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="uc_7",
                from_node_id="uc_gate",
                to_node_id="uc_continue",
                edge_kind="conditional",
                label="安全性可接受",
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="uc_8",
                from_node_id="uc_gate",
                to_node_id="uc_switch",
                edge_kind="conditional",
                label="240 mg BID安全性不佳",
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="uc_9",
                from_node_id="uc_continue",
                to_node_id="uc_follow",
                edge_kind="follow_up",
                fact_status="confirmed",
                source_bindings=[source],
            ),
            MedicalWritingStudySchemaEdge(
                edge_id="uc_10",
                from_node_id="uc_switch",
                to_node_id="uc_follow",
                edge_kind="follow_up",
                fact_status="confirmed",
                source_bindings=[source],
            ),
        ],
        annotations=[
            "当S2剂量持续累积数据提示安全性不佳时，停止S2入组，后续受试者仅进入S1。",
            "已接受240 mg BID的受试者在研究者指导下降至160 mg BID并继续完成研究。",
        ],
    )
    schema = schema.model_copy(
        update={"state_sha256": study_schema_state_sha256(schema)}
    )
    blockers = [
        issue.model_dump(mode="json")
        for issue in validate_study_schema(schema)
        if issue.severity == "blocker"
    ]
    if blockers:
        raise RuntimeError(f"real IBDQ study-schema fixture is invalid: {blockers}")
    return schema


__all__ = ["build_real_ibdq_study_schema"]
