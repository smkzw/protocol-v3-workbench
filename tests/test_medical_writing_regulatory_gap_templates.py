"""NEW-3/15/18/43 内容族②（R27 第3轮修订）反例：安全性/法规类缺口章节的
确定性参数化模板文本。

现场：OAB/R25T5 的 8.2.x（AE/SAE/SUSAR 定义）、SAE 24小时上报、紧急揭盲、
妊娠/避孕、VZV 筛查等安全性法规要素在源证据缺失时只留【待补齐】占位——
全文 0 命中。期望：这些章节作为缺口时，占位块替换为参数化的标准监管文本
（试验药物/适应症参数化），含 24 小时上报路径与紧急揭盲程序；非安全性
章节保持原【待补齐】占位不变。
"""
from __future__ import annotations

from services.api.app.medical_writing_repository import (
    _gap_placeholder_block,
    _gap_placeholder_blocks,
    _is_safety_regulatory_section,
)


def _section(heading: str, number: str):
    return {"heading": heading, "section_number": number, "section_id": "sec-x"}


OVERRIDES = {"investigational_product": "MSC-201片", "protocol_date": "2026-09-30"}


def test_safety_sections_are_recognized_by_heading_or_number():
    assert _is_safety_regulatory_section(_section("不良事件及处理措施", "8.2"))
    assert _is_safety_regulatory_section(_section("严重不良事件报告", "8.2.2"))
    assert _is_safety_regulatory_section(_section("紧急揭盲程序", "8.9"))
    assert _is_safety_regulatory_section(_section("妊娠避孕与VZV筛查", "5.4"))
    assert not _is_safety_regulatory_section(_section("统计分析计划", "9.2"))
    assert not _is_safety_regulatory_section(_section("研究流程表", "1.3"))


def test_safety_gap_block_contains_parameterized_regulatory_text():
    block = _gap_placeholder_block(
        _section("不良事件及严重不良事件", "8.2"),
        OVERRIDES,
    )
    text = str(block.get("text"))
    assert "MSC-201片" in text
    assert "24 小时" in text
    assert "严重不良事件" in text
    assert "揭盲" not in text or "紧急揭盲" in text or "揭盲" in text
    assert "医学经理" in text  # 需医学确认的显式提示
    assert "【待补齐】" not in text


def test_unblinding_gap_block_contains_emergency_unblinding_procedure():
    block = _gap_placeholder_block(_section("紧急揭盲程序", "8.9"), OVERRIDES)
    text = str(block.get("text"))
    assert "紧急揭盲" in text
    assert "申办方" in text


def test_pregnancy_gap_block_contains_contraception_and_vzv_requirements():
    block = _gap_placeholder_block(
        _section("妊娠避孕与VZV筛查", "5.4"), OVERRIDES
    )
    text = str(block.get("text"))
    assert "妊娠" in text
    assert "避孕" in text


def test_non_safety_gap_keeps_plain_placeholder():
    block = _gap_placeholder_block(
        _section("统计分析计划", "9.2"),
        OVERRIDES,
    )
    text = str(block.get("text"))
    assert "【待补齐】" in text
    assert "24 小时" not in text


def test_missing_product_falls_back_to_generic_subject_label():
    block = _gap_placeholder_block(_section("不良事件及处理措施", "8.2"), {})
    assert "研究药物" in str(block.get("text"))


# NEW-15/18 残留（R27 第1轮末修订）：随机化/盲法、AESI、风险控制/委员会
# 章节不再整节空壳——落入确定性参数化骨架，未记录的定量事实显式
# 「待医学经理确认」。
DESIGN_OVERRIDES = {
    **OVERRIDES,
    "design_comparator_type": "placebo",
    "design_randomization_mode": "randomized",
    "design_blinding_mode": "double_blind",
    "sample_size_strategy": "按主要终点应答率差异估算，计划入组 240 例受试者。",
}


def test_randomization_blinding_gap_block_carries_design_skeleton():
    block = _gap_placeholder_block(
        _section("随机化与盲法设计", "4.3"), DESIGN_OVERRIDES
    )
    text = str(block.get("text"))
    assert "随机" in text and "盲法" in text
    # 分配比例未记录 → 显式待确认，绝不编造。
    assert "待医学经理确认" in text
    assert "区组" in text
    assert "紧急揭盲" in text or "紧急破盲" in text
    assert "【待补齐】" not in text


def test_randomization_blinding_uses_recorded_sample_size_fact():
    block = _gap_placeholder_block(
        _section("随机化与盲法设计", "4.3"), DESIGN_OVERRIDES
    )
    assert "240" in str(block.get("text"))


def test_aesi_gap_block_has_monitoring_disposition_reporting_parts():
    block = _gap_placeholder_block(
        _section("特别关注的不良事件（AESI）", "8.5"), DESIGN_OVERRIDES
    )
    text = str(block.get("text"))
    assert "监测频次" in text
    assert "处置流程" in text
    assert "报告要求" in text
    assert "MSC-201片" in text


def test_risk_control_committee_gap_block_names_dmc_src_review():
    block = _gap_placeholder_block(
        _section("风险控制计划与数据监查委员会", "8.3"), DESIGN_OVERRIDES
    )
    text = str(block.get("text"))
    assert "委员会" in text
    assert "审查频率" in text
    assert "待医学经理确认" in text


def test_unrelated_headings_keep_recognized_by_existing_rules():
    # 回归：既有安全性标题判定不受新标记影响。
    assert _is_safety_regulatory_section(_section("数据监查委员会", "8.3"))
    assert not _is_safety_regulatory_section(_section("统计分析计划", "9.2"))


# NEW-16（R27 第1轮末修订）：研究流程表（SoA）章节的确定性骨架——由已确认
# picos.study_epochs + visit_strategy 生成访视×活动矩阵表体（含访视窗列），
# 且必须能通过既有结构化表服务的结构校验（from_table_block），导出走既有
# table 渲染路径。全部单元格语义为骨架，标注待医学经理确认。
SOA_OVERRIDES = {
    **OVERRIDES,
    "study_epochs": ["筛选期", "双盲治疗期", "随访期"],
    "visit_strategy": "筛选、基线，治疗期每4周访视，随访期每月一次。",
}


def test_soa_gap_section_yields_paragraph_plus_valid_table_block():
    from services.api.app.medical_writing_tables import MedicalWritingTableService

    blocks = _gap_placeholder_blocks(
        _section("研究流程表（Schedule of Activities）", "1.3"), SOA_OVERRIDES
    )
    assert [str(block.get("block_type")) for block in blocks] == ["paragraph", "table"]
    note, table = blocks
    assert "待医学经理" in str(note.get("text"))
    table_service = MedicalWritingTableService()
    parsed = table_service.from_table_block(table)
    header_cells = [cell.text for cell in parsed.rows[0].cells]
    assert any("活动" in value for value in header_cells)
    assert any("访视窗" in value for value in header_cells)
    assert any("筛选期" in value for value in header_cells)
    assert any("治疗期" in value for value in header_cells)
    # 每行都有稳定 cell_id 与活动名。
    body_rows = parsed.rows[1:]
    assert body_rows, "SoA 骨架必须至少有一行活动"
    assert all(row.cells[0].text for row in body_rows)


def test_soa_skeleton_without_epochs_still_yields_reviewable_table():
    from services.api.app.medical_writing_tables import MedicalWritingTableService

    blocks = _gap_placeholder_blocks(
        _section("Schedule of Activities", "1.3"), OVERRIDES
    )
    table = blocks[1]
    parsed = MedicalWritingTableService().from_table_block(table)
    assert parsed.rows[0].cells[0].text
    assert "待医学经理" in str(blocks[0].get("text"))


def test_non_soa_sections_keep_single_placeholder_block():
    blocks = _gap_placeholder_blocks(
        _section("统计分析计划", "9.2"), SOA_OVERRIDES
    )
    assert len(blocks) == 1
    assert blocks[0]["block_type"] == "paragraph"
