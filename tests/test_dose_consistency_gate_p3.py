"""新纪元第3轮修订·第五步：给药方案跨节一致性门（NEW-20，反例先红）。

现场（NEW-20，B/C 独立同判 P0）：UC 导出件 6.1/6.2/摘要表三处'每日两次、
每次一片'（80mg BID）与 4.4 双模拟'每次4片活性+2片安慰剂'直接冲突——药房
不可执行。根因=只有重复门没有矛盾门，剂量-频次-片数无跨节一致性检查。

契约（红先修后，走缺口→草案-N 既有通道）：
T1 跨节片数冲突：'每次一片/每次1片' 与 '每次N片(N≥2)' 分现不同节 → 缺口
   点名两节与两种表述；
T2 跨节频次冲突：'每日两次' 与 '每日一次' 分现不同节 → 缺口；
T3 同节内带臂限定（如'A组每次1片、B组每次2片'）不误伤；单节单一表述
   不误伤。
"""
from __future__ import annotations

import unittest


def _report(sections_spec):
    from services.api.app.main import _export_placeholder_report
    from packages.contracts.workbench_contracts import (
        ProtocolDocument,
        ProtocolSection,
    )

    document = ProtocolDocument(
        document_id="doc_dose_consistency",
        project_id="proj_dose_consistency",
        protocol_id="CMS-DOSE",
        version="1.0",
        sections=[
            ProtocolSection(
                section_id=section_id,
                document_id="doc_dose_consistency",
                heading=heading,
                section_number=number,
                content_blocks=[
                    {"block_id": f"b_{section_id}", "block_type": "paragraph", "text": text}
                ],
            )
            for section_id, number, heading, text in sections_spec
        ],
    )
    return _export_placeholder_report(document)


def _reasons(report):
    return " ".join(
        str(item.get("reason") or "")
        for item in report.get("gap_sections") or []
    )


class DoseConsistencyGateTests(unittest.TestCase):
    def test_tablet_count_conflict_across_sections_is_gapped(self) -> None:
        report = _report(
            (
                ("sec_6_1", "6.1", "研究性干预描述", "研究药物为每日两次、每次一片口服给药。"),
                (
                    "sec_4_4",
                    "4.4",
                    "盲态设计",
                    "双盲双模拟设计下，160mg组每次4片活性药物联合2片安慰剂口服。",
                ),
            )
        )
        reasons = _reasons(report)
        self.assertIn("给药方案片数表述冲突", reasons)
        self.assertIn("6.1", reasons)
        self.assertIn("4.4", reasons)

    def test_frequency_conflict_across_sections_is_gapped(self) -> None:
        report = _report(
            (
                ("sec_6_1", "6.1", "研究性干预描述", "研究药物每日两次口服给药。"),
                ("sec_5_1", "5.1", "研究干预总体描述", "研究药物每日一次口服给药。"),
            )
        )
        reasons = _reasons(report)
        self.assertIn("给药方案频次表述冲突", reasons)

    def test_arm_scoped_variants_within_one_section_not_flagged(self) -> None:
        report = _report(
            (
                (
                    "sec_6_1",
                    "6.1",
                    "研究性干预描述",
                    "低剂量组每次1片口服，高剂量组每次2片口服，均为每日两次。",
                ),
                (
                    "sec_6_2",
                    "6.2",
                    "研究性干预剂量和方案的依据",
                    "两臂均每日两次给药，片数按各臂方案执行。",
                ),
            )
        )
        self.assertNotIn("给药方案片数表述冲突", _reasons(report))
        self.assertNotIn("给药方案频次表述冲突", _reasons(report))

    def test_consistent_statements_not_flagged(self) -> None:
        report = _report(
            (
                ("sec_6_1", "6.1", "研究性干预描述", "研究药物为每日两次、每次一片口服。"),
                ("sec_6_2", "6.2", "给药方案依据", "按每日两次、每次一片的方案设计。"),
            )
        )
        self.assertNotIn("给药方案", _reasons(report))


if __name__ == "__main__":
    unittest.main()
