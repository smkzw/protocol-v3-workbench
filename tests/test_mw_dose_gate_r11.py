"""第10轮末修订·剂量与参数门（P0-27）：零剂量全文的三层防线之两层。

现场（BE204 基准轮，r10-C 医学总监判临床不可执行）：6.2 研究治疗给药
仅『KZ-BE204片每日一次晨服』——全文 mg/毫克 0 命中，两臂中试验药臂
剂量无从知晓；现行门只判空白/纯占位，一句话正文即过。

契约（红先修后）：
T1 生成层：给药/研究治疗章（6.2或标题含给药）剂量单位
   （mg/毫克/µg/μg/微克/IU/国际单位）0命中 → dose_check=『剂量缺失』
   +正文附『需IB/立项补剂量方案』悬置提示；有单位不标记；
T2 导出层：同判据计入缺口清单（reason 点名剂量缺失）→ 版本门强制
   草案-N；
T3 非给药章（总体设计等）不误伤。
"""

from __future__ import annotations

import unittest

from packages.contracts.workbench_contracts import (
    ProtocolDocument,
    ProtocolSection,
)

NO_DOSE_TEXT = "KZ-BE204片每日一次晨服，连续给药12周；两臂受试者按1:1随机分配并全程双盲。"
WITH_DOSE_TEXT = "KZ-BE204片25mg每日一次晨服，连续给药12周；匹配安慰剂片外观一致。"


class DosePresenceGenerationTests(unittest.TestCase):
    def test_zero_dose_dosing_section_flagged_with_hint(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_dose_presence_guard_to_section,
        )

        section = {
            "section_id": "sec_62",
            "section_number": "6.2",
            "heading": "研究治疗给药",
            "proposal_text": "6.2 研究治疗给药。" + NO_DOSE_TEXT,
        }
        apply_dose_presence_guard_to_section(section)
        self.assertEqual(
            "剂量缺失",
            section["dose_check"]["status"],
            "给药章无任何剂量单位必须显性标记。",
        )
        self.assertIn("需IB/立项补剂量方案", section["proposal_text"])

    def test_dose_unit_present_not_flagged(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_dose_presence_guard_to_section,
        )

        section = {
            "section_id": "sec_62",
            "section_number": "6.2",
            "heading": "研究治疗给药",
            "proposal_text": "6.2 研究治疗给药。" + WITH_DOSE_TEXT,
        }
        apply_dose_presence_guard_to_section(section)
        self.assertNotIn("dose_check", section)
        self.assertNotIn("需IB/立项补剂量方案", section["proposal_text"])

    def test_non_dosing_section_not_flagged(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_dose_presence_guard_to_section,
        )

        section = {
            "section_id": "sec_41",
            "section_number": "4.1",
            "heading": "总体设计",
            "proposal_text": "4.1 总体设计。本研究为随机双盲安慰剂对照II期研究。",
        }
        apply_dose_presence_guard_to_section(section)
        self.assertNotIn("dose_check", section)


class DosePresenceExportTests(unittest.TestCase):
    def _document(self, blocks_by_section: dict) -> ProtocolDocument:
        sections = [
            ProtocolSection(
                section_id=section_id,
                document_id="doc_dose_gate",
                heading=heading,
                section_number=number,
                content_blocks=blocks,
            )
            for section_id, (heading, number, blocks) in blocks_by_section.items()
        ]
        return ProtocolDocument(
            document_id="doc_dose_gate",
            project_id="proj_dose_gate",
            protocol_id="CMS-DOSE-T",
            version="1.0",
            sections=sections,
        )

    def test_zero_dose_62_counts_into_gap_and_draft_label(self) -> None:
        from services.api.app.main import (
            _export_placeholder_report,
            _export_version_label,
        )

        document = self._document(
            {
                "sec_41": ("总体设计", "4.1", [
                    {"block_id": "b1", "block_type": "paragraph", "text": WITH_DOSE_TEXT},
                ]),
                "sec_62": ("研究治疗给药", "6.2", [
                    {"block_id": "b2", "block_type": "paragraph", "text": NO_DOSE_TEXT},
                ]),
            }
        )
        report = _export_placeholder_report(document)
        dose_gaps = [
            item for item in report.get("gap_sections") or []
            if "剂量" in str(item.get("reason") or "")
        ]
        self.assertEqual(1, len(dose_gaps), f"零剂量给药章必须计入缺口：{report.get('gap_sections')}")
        self.assertIn("6.2", dose_gaps[0].get("section_number") or "")
        label = _export_version_label(
            document,
            total_markers=int(report.get("total_count") or 0),
            mode="approved_final",
            gap_count=int(report.get("gap_count") or 0),
        )
        self.assertTrue(label.startswith("草案-"), f"零剂量必须强制草案-N，得到 {label!r}")

    def test_dose_present_62_not_counted(self) -> None:
        from services.api.app.main import _export_placeholder_report

        document = self._document(
            {
                "sec_62": ("研究治疗给药", "6.2", [
                    {"block_id": "b2", "block_type": "paragraph", "text": WITH_DOSE_TEXT},
                ]),
            }
        )
        report = _export_placeholder_report(document)
        dose_gaps = [
            item for item in report.get("gap_sections") or []
            if "剂量" in str(item.get("reason") or "")
        ]
        self.assertEqual(0, len(dose_gaps))


if __name__ == "__main__":
    unittest.main()
