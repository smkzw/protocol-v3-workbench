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



# ── F3 第三形态堵口批（新纪元修订第1轮末策略，20261016）──────────────────
# 现场（r1-C 10-13件 + 工件实跑）：'要素未齐+无悬置标记'是三方断言（只查
# 自洽溯源）与全文补门（只计不一致）两头都不管的第三形态——声明数字无标记
# 上纸（NEW-17/F3根因②③）。契约：
#   a. 三方断言扩『样本量要素未齐』：正文无『样本量待确认』悬置标记 → 计
#      『守卫标记缺失』缺口（供补标通道点名）；
#   b. 全文补门扩『样本量要素未齐』：无统计编号节的存量件同样清纸面；
#   c. 自动补标扩『要素未齐悬置块』：导出副本追加诚实标注（不回写存储）。


class SampleSizeThirdFormTests(unittest.TestCase):
    _INCOMPLETE_DECLARATION = (
        "本研究计划入组120例受试者（每组40例），样本量依据探索性考量，"
        "详细假设见统计分析计划。"
    )

    def _document(self, number: str, heading: str, text: str):
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )

        return ProtocolDocument(
            document_id="doc_third_form",
            project_id="proj_third_form",
            protocol_id="CMS-THIRD",
            version="1.0",
            sections=[
                ProtocolSection(
                    section_id="sec_t",
                    document_id="doc_third_form",
                    heading=heading,
                    section_number=number,
                    content_blocks=[
                        {"block_id": "b1", "block_type": "paragraph", "text": text}
                    ],
                )
            ],
        )

    def test_a_incomplete_declaration_without_marker_counts_guard_gap(self) -> None:
        """F3①：9.x 声明要素未齐且正文无悬置标记 → 守卫标记缺失缺口。"""
        from services.api.app.main import _export_placeholder_report

        report = _export_placeholder_report(
            self._document("9.1", "9.1 样本量", self._INCOMPLETE_DECLARATION)
        )
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("守卫标记缺失", reasons)
        self.assertIn("要素未齐", reasons)
        self.assertIn("样本量待确认", reasons)

    def test_b_whole_doc_gate_catches_incomplete_in_non_statistics_section(self) -> None:
        """F3②：非统计编号节（5.1）声明要素未齐 → 全文补门计缺口（存量件）。"""
        from services.api.app.main import _export_placeholder_report

        document = self._document(
            "5.1", "5.1 研究人群描述", self._INCOMPLETE_DECLARATION
        )
        report = _export_placeholder_report(document)
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("重导出补门", reasons)
        self.assertIn("要素未齐", reasons)

    def test_c_incomplete_pending_block_gets_auto_annotation(self) -> None:
        """F3③：要素未齐悬置声明 → 导出副本自动追加诚实标注。"""
        from services.api.app.main import (
            _apply_export_guard_annotations,
            _export_placeholder_report,
        )

        document = self._document(
            "9.1", "9.1 样本量", self._INCOMPLETE_DECLARATION
        )
        report = _export_placeholder_report(document)
        annotations = _apply_export_guard_annotations(document, report)
        self.assertTrue(annotations, "要素未齐悬置块必须触发导出副本补标。")
        exported_text = str(
            document.sections[0].content_blocks[0].get("text") or ""
        )
        self.assertIn("未经", exported_text)
        self.assertIn(
            "要素未齐",
            " ".join(str(item.get("annotation") or "") for item in annotations),
        )


if __name__ == "__main__":
    unittest.main()


# ── NEW-44 守卫悬置标记剥离（第2轮末修订策略，20261017）───────────────────
# 现场（r2-A 导出件实测）：【统计章分节装配待确认】×2、【样本量待确认】×1、
# （剂量出处待标注）×2 直接上纸——各标记自述『正式稿不得带此标记』。
# 契约：导出副本剥离三族标记并逐章计入占位符报告『待确认事项』；缺口
# 计数不变（报告在剥离前按存储态算毕）。


class GuardPendingMarkerStripTests(unittest.TestCase):
    def _document(self):
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )

        return ProtocolDocument(
            document_id="doc_nd44",
            project_id="proj_nd44",
            protocol_id="CMS-ND44",
            version="草案-1",
            sections=[
                ProtocolSection(
                    section_id="sec_9",
                    document_id="doc_nd44",
                    heading="9.1 样本量",
                    section_number="9.1",
                    content_blocks=[
                        {
                            "block_id": "b1",
                            "block_type": "paragraph",
                            "text": (
                                "【样本量待确认：当前声明每组45例，假设要素"
                                "不全，系统无法复算。】"
                                "本研究计划入组每组45例。"
                                "（剂量出处待标注：请引用IB版本后确认。）"
                            ),
                        }
                    ],
                ),
                ProtocolSection(
                    section_id="sec_9_2",
                    document_id="doc_nd44",
                    heading="9.2 统计分析",
                    section_number="9.2",
                    content_blocks=[
                        {
                            "block_id": "b2",
                            "block_type": "paragraph",
                            "text": (
                                "【统计章分节装配待确认：分析集等五件套"
                                "缺件。】统计分析采用双侧检验。"
                            ),
                        }
                    ],
                ),
            ],
        )

    def test_guard_pending_markers_stripped_and_counted(self):
        from services.api.app.main import _strip_export_guard_pending_markers

        document = self._document()
        notes = _strip_export_guard_pending_markers(document)
        self.assertEqual(2, len(notes), "两章各命中标记，逐章计数")
        body = str(document.sections[0].content_blocks[0].get("text"))
        self.assertNotIn("【样本量待确认", body)
        self.assertNotIn("剂量出处待标注", body)
        self.assertIn("每组45例", body, "正文实体保留，只剥过程标记")
        body2 = str(document.sections[1].content_blocks[0].get("text"))
        self.assertNotIn("统计章分节装配待确认", body2)
        self.assertIn("双侧检验", body2)

    def test_strip_runs_after_report_so_gap_counting_unchanged(self):
        """缺口计数读存储态（剥离前）：悬置标记所在节仍计要素未齐/守卫缺口。"""
        from services.api.app.main import (
            _apply_export_guard_annotations,
            _export_placeholder_report,
            _strip_export_guard_pending_markers,
        )

        document = self._document()
        report = _export_placeholder_report(document)
        reasons = " ".join(
            str(item.get("reason") or "") for item in report.get("gap_sections") or []
        )
        self.assertIn("要素未齐", reasons, "剥离前报告必须仍按存储态计缺口")
        _apply_export_guard_annotations(document, report)
        pending = _strip_export_guard_pending_markers(document)
        self.assertTrue(pending)
        # r3 复锚：guard_pending_items 由导出流程在报告算毕后挂载
        # （剥离只改导出副本，不反哺缺口计数）——钉接线契约。
        export_flow = (
            (ROOT / "services" / "api" / "app" / "main.py")
            .read_text(encoding="utf-8")
        )
        self.assertIn(
            'placeholder_report["guard_pending_items"] = '
            "_strip_export_guard_pending_markers(",
            export_flow,
            "导出流程必须把待确认事项挂进占位符报告。",
        )
