"""新纪元第4轮修订·第二刀①②：守卫多源覆盖 + 导出自带补标（反例先红）。

现场（HA501，E10 唯一回归）：统一守卫入口全仓仅 chunk 完成路径一个调用
点——同一声明文本经非 chunk 路径入工作副本后，导出件全文 '假设待定'=0；
第3轮的导出侧断言只做到'检出计缺口'，草案照发、无回路把标注补上纸。

契约（红先修后）：
T1 保存入口投影层：repository 保存前对统计/样本量/给药章正文过守卫——
   自洽声明无锚点 → 投影后文本携带'假设未具名溯源'标注（HA501 形态）；
   给药章零剂量 → 携带'剂量待确认'前缀；非守卫章节/数字改写型不改写
   （交给导出层缺口）；
T2 save_working_copy 接线投影（源契约：保存路径含投影调用）；
T3 导出自带补标：占位符报告后对'守卫标记缺失…样本量溯源注记'的节在
   导出副本自动追加诚实标注（不回写存储），纸面永远诚实；补标动作入
   报告 guard_annotations。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_CONSISTENT_DECLARATION = (
    "样本量按组间差6分、SD 12、双侧α=0.05、把握度80%计算，需每组63例，"
    "本研究计划入组126例受试者。"
)
_NO_DOSE_TEXT = "KZ-BE204片每日一次晨服，连续给药12周；两臂按1:1随机并全程双盲。"
_PLAIN_BACKGROUND = (
    "本研究基于已确认的适应症与分期陈述研究背景，正文与来源证据一一对应，"
    "供医学审阅确认后写入正式文本。"
)


class SaveProjectionTests(unittest.TestCase):
    def _project(self, heading, number, text):
        from services.api.app.medical_writing_repository import (
            MedicalWritingRuntimeRepository,
        )

        blocks = [{"block_id": "b1", "block_type": "paragraph", "text": text}]
        section = SimpleNamespace(
            section_id="sec_x", heading=heading, section_number=number
        )
        return MedicalWritingRuntimeRepository._project_content_guards_on_save(
            None, section, blocks
        )

    def test_consistent_declaration_gets_provenance_annotation(self) -> None:
        blocks = self._project("9.1 样本量", "9.1", _CONSISTENT_DECLARATION)
        joined = str(blocks[0].get("text") or "")
        self.assertIn("假设未具名溯源", joined, "HA501 形态：非 chunk 路径的声明必须带溯源标注。")

    def test_dosing_zero_dose_gets_suspension_prefix(self) -> None:
        blocks = self._project("6.2 研究治疗与给药", "6.2", _NO_DOSE_TEXT)
        joined = str(blocks[0].get("text") or "")
        self.assertIn("剂量待确认", joined)

    def test_plain_section_untouched(self) -> None:
        blocks = self._project("1.1 研究背景", "1.1", _PLAIN_BACKGROUND)
        self.assertEqual(_PLAIN_BACKGROUND, str(blocks[0].get("text") or ""))

    def test_save_working_copy_wires_projection(self) -> None:
        source = (
            (ROOT / "services" / "api" / "app" / "medical_writing_repository.py")
            .read_text(encoding="utf-8")
        )
        save_start = source.index("    def save_working_copy(")
        save_body = source[save_start: source.index("    def ", save_start + 10)]
        self.assertIn(
            "_project_content_guards_on_save", save_body,
            "保存路径未接线守卫投影——非 chunk 路径仍会绕过守卫。",
        )


ROOT = Path(__file__).resolve().parents[1]


class ExportAutoAnnotationTests(unittest.TestCase):
    def test_marker_missing_gap_gets_auto_annotation_on_export_copy(self) -> None:
        from services.api.app.main import (
            _apply_export_guard_annotations,
            _export_placeholder_report,
        )
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )

        document = ProtocolDocument(
            document_id="doc_auto",
            project_id="proj_auto",
            protocol_id="CMS-AUTO",
            version="1.0",
            sections=[
                ProtocolSection(
                    section_id="sec_9_1",
                    document_id="doc_auto",
                    heading="9.1 样本量",
                    section_number="9.1",
                    content_blocks=[
                        {
                            "block_id": "b1",
                            "block_type": "paragraph",
                            "text": _CONSISTENT_DECLARATION,
                        }
                    ],
                )
            ],
        )
        report = _export_placeholder_report(document)
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("守卫标记缺失", reasons)
        annotations = _apply_export_guard_annotations(document, report)
        self.assertTrue(annotations, "守卫标记缺失必须触发导出副本自动补标。")
        exported_text = str(
            document.sections[0].content_blocks[0].get("text") or ""
        )
        self.assertIn("样本量假设未具名溯源", exported_text)
        self.assertIn(
            "样本量溯源注记",
            " ".join(str(item.get("annotation") or "") for item in annotations),
        )


if __name__ == "__main__":
    unittest.main()
