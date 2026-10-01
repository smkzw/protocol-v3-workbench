"""NEW-17 内容族①（R27 第3轮修订）反例：导出占位符门。

现场：OAB 导出件 82 处【待补齐】与测试标记（【切片闭环0927V1】/【UI编辑0927V1】）
在 draft 模式直接放行、approved_final 也无人拦截。期望：
- 统计器逐章返回占位符与测试标记计数+摘录；
- approved_final 存在占位符即拒绝；
- draft 模式需显式 acknowledge_placeholders=true，否则拒绝并附逐章清单。
"""
from __future__ import annotations

import pytest

from packages.contracts.workbench_contracts import ProtocolDocument, ProtocolSection
from services.api.app.main import (
    _enforce_export_placeholder_gate,
    _export_placeholder_report,
)


def _document_with(body: str) -> ProtocolDocument:
    return ProtocolDocument(
        document_id="doc-1",
        project_id="proj-export-gate",
        protocol_id="PROTO-1",
        version="V1.0",
        sections=[
            ProtocolSection(
                section_id="sec-1",
                document_id="doc-1",
                heading="安全性评价",
                section_number="8",
                content_blocks=[{"block_id": "b1", "text": body}],
            ),
            ProtocolSection(
                section_id="sec-2",
                document_id="doc-1",
                heading="统计分析",
                section_number="9",
                content_blocks=[{"block_id": "b2", "text": "主要终点采用MMRM分析。"}],
            ),
        ],
    )


def test_placeholder_report_counts_by_section_with_excerpts():
    document = _document_with(
        "本研究【待补齐】。历史标记【切片闭环0927V1】与【UI编辑0327V2】留存。"
    )
    report = _export_placeholder_report(document)
    assert report["total_count"] == 3
    by_section = {item["section_number"]: item for item in report["sections"]}
    assert by_section["8"]["count"] == 3
    assert "9" not in by_section  # 无命中的章节不进入清单
    assert any("待补齐" in excerpt for excerpt in by_section["8"]["excerpts"])
    assert any("切片闭环" in excerpt for excerpt in by_section["8"]["excerpts"])


def test_clean_document_reports_zero():
    report = _export_placeholder_report(_document_with("正文完整，无占位。"))
    assert report["total_count"] == 0
    assert report["sections"] == []


def test_approved_final_with_placeholders_is_rejected():
    document = _document_with("【待补齐】安全性随访安排。")
    report = _export_placeholder_report(document)
    with pytest.raises(ValueError, match="正式导出"):
        _enforce_export_placeholder_gate(report, mode="approved_final", acknowledge=False)


def test_draft_requires_explicit_acknowledge_with_chapter_list():
    document = _document_with("【待补齐】安全性随访安排。")
    report = _export_placeholder_report(document)
    with pytest.raises(ValueError, match="acknowledge_placeholders") as refused:
        _enforce_export_placeholder_gate(report, mode="draft_preview", acknowledge=False)
    assert "8" in str(refused.value)


def test_draft_with_acknowledge_passes_and_still_records_report():
    document = _document_with("【待补齐】安全性随访安排。")
    report = _export_placeholder_report(document)
    assert (
        _enforce_export_placeholder_gate(
            report, mode="draft_preview", acknowledge=True
        )
        is None
    )


# NEW-21（R27 第1轮末修订）：导出门文本质量 lint——错字词典（咳嗉→咳嗽）
# 在导出副本替换并留变更注记（不改导入源行），CJK 叠词（如「策略策略」）
# 逐章入清单供人工/AI 复核。
def test_typo_dictionary_is_reported_and_replaced_on_export_copy():
    from services.api.app.main import _apply_export_text_quality_lint

    document = _document_with("受试者出现咳嗉症状。")
    report = _export_placeholder_report(document)
    assert report["total_count"] == 0
    quality = report["text_quality"]
    assert quality["stutter_count"] == 0
    assert any(item["wrong"] == "咳嗉" for item in quality["typo_hits"])

    notes = _apply_export_text_quality_lint(document)
    assert any(note["wrong"] == "咳嗉" and note["correct"] == "咳嗽" for note in notes)
    assert "咳嗽" in document.sections[0].content_blocks[0]["text"]
    assert "咳嗉" not in document.sections[0].content_blocks[0]["text"]
    # 每处替换都有逐章变更注记。
    assert notes[0]["section_number"] == "8"


def test_cjk_stutter_is_reported_per_section_without_autosilence():
    document = _document_with("治疗策略策略需在统计分析章节中说明。")
    report = _export_placeholder_report(document)
    quality = report["text_quality"]
    assert quality["stutter_count"] >= 1
    assert any("策略策略" in item["excerpt"] for item in quality["stutters"])
    assert quality["stutters"][0]["section_number"] == "8"


def test_clean_text_has_empty_text_quality():
    report = _export_placeholder_report(_document_with("正文表述规范，无错字与重复。"))
    quality = report["text_quality"]
    assert quality["typo_hits"] == []
    assert quality["stutters"] == []
    assert quality["stutter_count"] == 0
