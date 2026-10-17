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


# ---------------------------------------------------------------------------
# F1 骨架归位批五处路由（新纪元修订第1轮，20261016）
#
# 规格：收官报告B类『骨架归位批五处路由（8.6/14.x/6.3/6.4/1.3 SoA——AD件
# 14.1避孕节『半接线』新样本佐证机制可行）』+ r11-B/r12-B 挂账⑩⑪⑫：
#   - 1.3 SoA（公司模板「研究流程表」）：NEW-16 矩阵应路由（守卫）；
#   - 6.3 剂量调整、暂停、恢复与永久停药：E12 操作化骨架应路由（守卫）；
#   - 6.4 药物过量与给药错误管理：反例（当前【待补齐】，无确定性骨架）；
#   - 8.6 不良事件的报告：反例（当前落入通用AE定义模板——SUSAR 监管时限
#     未写死、报告途径未列明；r12-B P1-H2『报告时限未写死+报告路径占位』）；
#   - 14.4 安全信息报告途径：反例（当前【待补齐】——挂账⑩『14.3/14.4空、
#     联系人待填写』）；14.1 避孕骨架无显式时限槽（r11-B『避孕无时限』）。
# 机制沿用既有标题关键词路由（按标题命中，兼容模板编号差异）。
# ---------------------------------------------------------------------------


def _company_heading(heading: str):
    return _section(heading, "company-template")


def test_f1_guard_13_schedule_routes_soa_matrix():
    """守卫（半接线佐证）：公司模板1.3研究流程表必须路由SoA矩阵。"""
    blocks = _gap_placeholder_blocks(
        _company_heading("研究流程表"), OVERRIDES
    )
    assert len(blocks) == 2, "1.3 SoA 必须路由为[说明段, 访视×活动矩阵表]"
    assert blocks[1]["block_type"] == "table"
    assert "研究时期" in str(blocks[0].get("text"))


def test_f1_guard_63_dose_modification_routes_stop_rule_skeleton():
    """守卫（半接线佐证）：公司模板6.3必须路由E12停药操作化三段式骨架。"""
    block = _gap_placeholder_block(
        _company_heading("剂量调整、暂停、恢复与永久停药"), OVERRIDES
    )
    text = str(block.get("text"))
    assert "【待补齐】" not in text
    assert "暂停给药" in text and "永久停药" in text
    assert "待医学经理" in text


def test_f1_red_64_overdose_management_needs_deterministic_skeleton():
    """反例：公司模板6.4药物过量与给药错误管理当前整节【待补齐】。"""
    block = _gap_placeholder_block(
        _company_heading("药物过量与给药错误管理"), OVERRIDES
    )
    text = str(block.get("text"))
    assert "【待补齐】" not in text, "6.4不得整节空壳（r11-B：6.4占位）"
    assert "药物过量" in text
    assert "给药错误" in text or "用药错误" in text
    assert "待医学经理" in text  # 未记录的处理细节显式留槽，不编造


def test_f1_red_86_ae_reporting_writes_regulatory_timeframes_and_pathway():
    """反例：公司模板8.6不良事件的报告——监管时限未写死、途径未列明。"""
    block = _gap_placeholder_block(
        _company_heading("不良事件的报告"), OVERRIDES
    )
    text = str(block.get("text"))
    # r12-B P1-H2：SUSAR/SAE 报告时限必须写死（监管标准时限），不得只写
    # 『按法规时限要求』；报告途径必须列明而非占位。
    assert "7" in text and "15" in text, (
        "SUSAR监管时限必须写死（致死/危及生命7日首次、15日随访更新）"
    )
    assert "报告途径" in text or "专用报告表" in text
    assert "药物警戒" in text


def test_f1_red_144_safety_reporting_pathway_routes_contact_skeleton():
    """反例：公司模板14.4安全信息报告途径当前整节【待补齐】（挂账⑩）。"""
    block = _gap_placeholder_block(
        _company_heading("安全信息报告途径"), OVERRIDES
    )
    text = str(block.get("text"))
    assert "【待补齐】" not in text, "14.4不得整节空壳（r12-B：报告路径占位）"
    assert "24 小时" in text or "24小时" in text
    assert "待医学经理" in text  # 联系人/邮箱/电话显式留槽
    assert "药物警戒" in text


def test_f1_red_contraception_skeleton_has_explicit_timing_slot():
    """反例：避孕时限句必须带显式确认槽（r11-B『避孕无时限』——现行文案
    『末次给药后规定时间内』无槽，时限值悬空）。"""
    import re

    block = _gap_placeholder_block(
        _company_heading("避孕的规定与方法"), OVERRIDES
    )
    text = str(block.get("text"))
    assert "末次给药后" in text, "避孕时限必须显式落槽"
    assert re.search(
        r"末次给药后[^。]*(待医学经理|待确认)",
        text,
    ), "时限值未确认前必须显式留槽（不编造天数），现行为『规定时间内』无槽"


# ---------------------------------------------------------------------------
# F1 分化批（新纪元修订第1轮末策略①，20261016）：8.x 安全省逐节定制——
# r1-C 现场：同一段未分化文本贴 8/8.2.1/8.2.2/8.4/8.5/8.6/8.7 共7节
# （NEW-3/NEW-15）。契约：
#   - 8.2 定义族：AE 骨架带收集窗口三分法 + SUSAR 7/15日监管时限数字；
#   - 8.4 采集与记录：记录规则 + 转归分类；
#   - 8.5 评估：CTCAE 分级 + 因果判定；
#   - 8.7 随访：随访至转归。
# ---------------------------------------------------------------------------


def test_f1_ae_definition_carries_collection_window_and_susar_windows():
    block = _gap_placeholder_block(
        _company_heading("不良事件"), OVERRIDES
    )
    text = str(block.get("text"))
    assert "收集窗口" in text, "AE骨架必须写明收集窗口（r1-C：收集窗口0命中）"
    assert "7" in text and "15" in text, "SUSAR监管时限必须带数字（NEW-3）"


def test_f1_collection_record_section_has_rules_and_outcome_classes():
    block = _gap_placeholder_block(
        _company_heading("不良事件的采集与记录"), OVERRIDES
    )
    text = str(block.get("text"))
    assert "转归" in text, "8.4必须含转归分类（NEW-3：转归分类0）"
    assert "记录" in text
    assert "待医学经理" in text


def test_f1_assessment_section_has_ctcae_and_causality():
    block = _gap_placeholder_block(
        _company_heading("不良事件的评估"), OVERRIDES
    )
    text = str(block.get("text"))
    assert "CTCAE" in text, "8.5必须含CTCAE分级（r1-C：CTCAE定义0命中）"
    assert "因果" in text, "8.5必须含因果关系判定"
    assert "严重程度" in text


def test_f1_followup_section_requires_followup_until_resolution():
    block = _gap_placeholder_block(
        _company_heading("不良事件的随访"), OVERRIDES
    )
    text = str(block.get("text"))
    assert "随访" in text
    assert "转归" in text, "8.7必须随访至转归（NEW-3：随访规则缺失）"


# ---------------------------------------------------------------------------
# F1② 去前缀批（新纪元修订第1轮末策略②，20261016）：P0-B『本『X』章节为
# 标准模板草稿，范围限本节』前缀×14上纸（NEW-28/红线人话化）——正文不再
# 印工程身份句；骨架身份由既有结构化元数据（skeleton_review_pending/
# skeleton_scope）与占位符报告（main.py 骨架节逐节点名计缺口）+ 导出版本
# 标签『草案-N』承载。
# ---------------------------------------------------------------------------


def test_f1_prefix_removed_from_body_and_identity_in_metadata():
    block = _gap_placeholder_block(
        _company_heading("剂量调整、暂停、恢复与永久停药"), OVERRIDES
    )
    text = str(block.get("text"))
    assert "标准模板草稿" not in text, "工程身份前缀不得上纸（NEW-28/红线人话化）"
    assert "范围限本节" not in text
    assert block.get("skeleton_review_pending") is True, "身份必须留在结构化元数据"
    assert block.get("skeleton_scope"), "范围必须留在 skeleton_scope 元数据"


def test_f1_generic_opener_allowed_again_but_bodies_stay_differentiated():
    stop = _gap_placeholder_block(
        _company_heading("剂量调整、暂停、恢复与永久停药"), OVERRIDES
    )
    pregnancy = _gap_placeholder_block(
        _company_heading("避孕的规定与方法"), OVERRIDES
    )
    stop_text = str(stop.get("text"))
    pregnancy_text = str(pregnancy.get("text"))
    assert stop_text.split("。")[0] != pregnancy_text.split("。")[0], (
        "去前缀后不同节的骨架首段仍不得逐字相同（P0-B 反回声意图保留）"
    )


# ---------------------------------------------------------------------------
# F1③ 结构化契约节注入（消 NEW-24，20261016）：1.2 研究示意图 / 1.3 研究
# 流程表属受控表节（node_kind=study_schema/schedule_of_activities），不入
# 普通实质正文缺口集合——正文为空时草案预览连占位块都没有（标题下零内容，
# r1-C 提取件 P023→P025 实证）。契约：空的结构化契约节在草案预览注入
# 受控骨架（示意图说明 / SoA 矩阵），装配层接线到两 node_kind。
# ---------------------------------------------------------------------------


def test_f1_schema_blank_section_gets_note_block():
    from services.api.app.medical_writing_repository import (
        _structured_contract_skeleton_blocks,
    )

    blocks = _structured_contract_skeleton_blocks(
        {"section_id": "sec_1_2", "heading": "研究示意图", "section_number": "1.2"},
        "study_schema",
        OVERRIDES,
    )
    assert blocks, "1.2 空节必须注入说明骨架（NEW-24：标题下零内容）"
    text = str(blocks[0].get("text"))
    assert "研究示意图" in text
    assert "待医学经理" in text
    assert blocks[0].get("skeleton_review_pending") is True


def test_f1_schedule_blank_section_gets_soa_matrix():
    from services.api.app.medical_writing_repository import (
        _structured_contract_skeleton_blocks,
    )
    from services.api.app.medical_writing_tables import MedicalWritingTableService

    blocks = _structured_contract_skeleton_blocks(
        {"section_id": "sec_1_3", "heading": "研究流程表", "section_number": "1.3"},
        "schedule_of_activities",
        OVERRIDES,
    )
    table_blocks = [b for b in blocks if b.get("block_type") == "table"]
    assert table_blocks, "1.3 空节必须注入SoA访视×活动矩阵"
    parsed = MedicalWritingTableService().from_table_block(table_blocks[0])
    assert parsed.rows, "SoA矩阵必须可渲染且非空"


def test_f1_assembly_wires_structured_sections_into_draft_preview():
    import inspect

    from services.api.app import medical_writing_repository as repo_module

    source = inspect.getsource(
        repo_module.MedicalWritingRuntimeRepository.assemble_document_for_export
    )
    assert '"study_schema"' in source and '"schedule_of_activities"' in source, (
        "装配层必须把两个结构化契约节接进草案预览注入（NEW-24收口）"
    )


# ---------------------------------------------------------------------------
# F1 新策略①（第2轮末修订，20261017，NEW-11/NEW-4 双口径根治）：6.3 停药
# 骨架的安全随访窗口必须读已确认研究周期事实（study_epochs），不再自造
# 『默认30天』第二口径（现场：研究周期D85-D98（2周） vs 骨架默认30天）。
# ---------------------------------------------------------------------------


def _stop_rule_text(overrides):
    from services.api.app.medical_writing_repository import (
        _gap_placeholder_block,
    )

    return str(
        _gap_placeholder_block(
            {
                "section_id": "sec_6_3",
                "heading": "剂量调整、暂停、恢复与永久停药",
                "section_number": "6.3",
            },
            overrides,
        ).get("text")
    )


def test_f1_stop_rule_injects_confirmed_safety_followup_window():
    overrides = {
        "investigational_product": "MSC-201片",
        "study_epochs": [
            "筛选期（D-28-D1）",
            "双盲治疗期（D1-D84）",
            "安全性随访期（D85-D98，2周）",
        ],
    }
    text = _stop_rule_text(overrides)
    assert "D85-D98" in text, "已确认安全性随访窗口必须注入停药骨架"
    assert "默认30天" not in text, "不得再自造『默认30天』第二口径（NEW-11）"


def test_f1_stop_rule_without_fact_keeps_explicit_slot_no_default_days():
    text = _stop_rule_text(OVERRIDES)
    assert "默认30天" not in text, "无事实时也不得印默认天数（第二口径源头）"
    assert "待医学经理" in text, "无事实时保留显式确认槽"
