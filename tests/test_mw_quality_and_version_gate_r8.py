"""R8 片X-3/X-4：投影一致性并入内容核查（编辑预警）+ 版本门堵『1.0』。

现场：P0-26 的不一致块在『内容核查』里 0 项问题——质检与导出器两套
标准打架；KRX451 以『1.0』正式版本携全要素缺口（保险空/国内法规零/
缩略语空/参考文献空/SoA空）导出，第6轮草案-N策略未覆盖空章缺口路径。

契约（红先修后）：
- T1 内容核查对 rich_text 投影!=text 的块出预警型 finding
  （rule_code=rich_text_projection_mismatch，非阻断——导出已自愈降级，
  核查侧是预警不是新门）；一致块不出；
- T2 版本门：占位/批注/缺口（空章）任一计数>0 → 导出版本标签强制
  『草案-N』（两种模式都适用——堵 approved_final 空『1.0』路径）；
  全零 → 正式版本原样。
"""

from __future__ import annotations

import unittest

from packages.contracts.workbench_contracts import (
    ProtocolDocument,
    ProtocolSection,
)

PROSE = "本研究为随机双盲安慰剂对照研究，两臂按1:1分配，核心期12周，主要终点为第12周应答率。"


def _document(blocks_by_section: dict[str, list[dict]]) -> ProtocolDocument:
    return ProtocolDocument(
        document_id="doc_r8_gate",
        project_id="proj_r8_gate",
        protocol_id="CMS-R8G-T",
        version="1.0",
        sections=[
            ProtocolSection(
                section_id=section_id,
                document_id="doc_r8_gate",
                heading=heading,
                section_number=number,
                content_blocks=blocks,
            )
            for section_id, (heading, number, blocks) in blocks_by_section.items()
        ],
    )


def _rich_block(block_id: str, text: str, rich_text=None) -> dict:
    return {
        "block_id": block_id,
        "block_type": "paragraph",
        "text": text,
        "rich_text": rich_text
        if rich_text is not None
        else {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]},
    }


class ContentQualityProjectionCheckTests(unittest.TestCase):
    def _scan(self, blocks):
        from services.api.app.medical_writing_content_quality import (
            MedicalWritingContentQualityDetector,
        )

        document = _document(
            {"sec_a": ("总体设计", "4.1", blocks)}
        )
        section = document.sections[0]
        return MedicalWritingContentQualityDetector().scan_section(
            document, section, blocks, content_revision=1
        )

    def test_projection_mismatch_yields_warning_finding(self) -> None:
        blocks = [_rich_block("blk_mismatch", PROSE)]  # text==投影（一致）
        blocks[0]["text"] = PROSE + "（与投影不一致的追加。）"
        findings = self._scan(blocks)
        matched = [
            f for f in findings
            if f.rule_code == "rich_text_projection_mismatch"
        ]
        self.assertEqual(1, len(matched), "投影不一致必须在内容核查中预警。")
        self.assertFalse(matched[0].approval_blocking, "预警不新增导出阻断门。")

    def test_consistent_block_yields_no_projection_finding(self) -> None:
        blocks = [_rich_block("blk_ok", PROSE)]
        findings = self._scan(blocks)
        self.assertFalse(
            any(f.rule_code == "rich_text_projection_mismatch" for f in findings)
        )

    def test_plain_block_without_rich_text_not_flagged(self) -> None:
        blocks = [{"block_id": "blk_plain", "block_type": "paragraph", "text": PROSE}]
        findings = self._scan(blocks)
        self.assertFalse(
            any(f.rule_code == "rich_text_projection_mismatch" for f in findings)
        )


class VersionLabelGapGateTests(unittest.TestCase):
    def test_gap_count_forces_draft_label_in_both_modes(self) -> None:
        from services.api.app.main import _export_version_label

        document = _document(
            {
                "sec_a": ("总体设计", "4.1", [_rich_block("b1", PROSE)]),
                "sec_empty": ("保险与知情同意", "14.1", []),
            }
        )
        for mode in ("draft_preview", "approved_final"):
            label = _export_version_label(
                document, total_markers=0, mode=mode, gap_count=1
            )
            self.assertTrue(
                label.startswith("草案-"),
                f"{mode} 下缺口计数>0 必须标草案-N，得到 {label!r}。",
            )

    def test_zero_everything_keeps_formal_version(self) -> None:
        from services.api.app.main import _export_version_label

        document = _document(
            {"sec_a": ("总体设计", "4.1", [_rich_block("b1", PROSE)])}
        )
        label = _export_version_label(
            document, total_markers=0, mode="approved_final", gap_count=0
        )
        self.assertEqual("1.0", label)

    def test_placeholder_report_counts_empty_sections_as_gaps(self) -> None:
        from services.api.app.main import _export_placeholder_report

        document = _document(
            {
                "sec_a": ("总体设计", "4.1", [_rich_block("b1", PROSE)]),
                "sec_gap": ("缩略语", "14.6", []),
                "sec_gap2": ("参考文献", "15", []),
            }
        )
        report = _export_placeholder_report(document)
        self.assertEqual(2, int(report.get("gap_count") or 0))
        self.assertEqual(
            ["14.6", "15"],
            [item.get("section_number") for item in report.get("gap_sections") or []],
        )


if __name__ == "__main__":
    unittest.main()
