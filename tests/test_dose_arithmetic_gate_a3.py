"""新纪元第3轮末修订（A3①/NEW-27）：给药日剂量算术门——臂名×规格×片数×
频次恒等式。

现场（UC2A，r2 P0-NE2-1 复验未通过、r3 形态变化）：'每次服用4片'双模拟
文字被删（XML 0命中）后，片数冲突的文本规则门静默通过，但算术矛盾仍在——
臂名'160mg/80mg BID' vs '40mg/片×每次一片BID'（=80mg/日）：40mg 片永远
凑不出 160mg 臂，药房不可执行。文本一致性门升级为算术门。

修后契约（反例先红）：
T1 红例：规格40mg/片 + 每次一片 BID + 臂名160mg/80mg BID → 导出缺口
   必须点名 160mg 臂与算术不平（80mg≠160mg）→ 草案-N 通道；
T2 正例：按臂分述片数（160mg组每次两片、80mg组每次一片）→ 无算术缺口；
T3 无臂名/无规格的给药章不算（不误伤泛表述）。
"""
from __future__ import annotations

import unittest


def _report(sections_text):
    from services.api.app.main import _export_placeholder_report
    from packages.contracts.workbench_contracts import (
        ProtocolDocument,
        ProtocolSection,
    )

    document = ProtocolDocument(
        document_id="doc_dose_math",
        project_id="proj_dose_math",
        protocol_id="CMS-DM-27",
        version="1.0",
        sections=[
            ProtocolSection(
                section_id=f"sec_{index}",
                document_id="doc_dose_math",
                heading="研究治疗与给药",
                section_number="6.2",
                content_blocks=[
                    {"block_id": f"b{index}", "block_type": "paragraph", "text": text}
                ],
            )
            for index, text in enumerate(sections_text, start=1)
        ],
    )
    return _export_placeholder_report(document)


class DoseArithmeticGateTests(unittest.TestCase):
    def test_arm_label_vs_tablet_math_mismatch_is_gapped(self) -> None:
        """T1：40mg片×每次一片BID（=80mg/日）凑不出160mg臂 → 缺口点名。"""
        report = _report([
            "试验药物薄膜衣片（规格40mg/片）口服，每次服用一片，每日两次（BID）。"
            "受试者按1:1随机至160mg/80mg BID剂量组。"
        ])
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("日剂量", reasons)
        self.assertIn("160mg", reasons)
        self.assertIn("80", reasons)
        self.assertGreaterEqual(int(report.get("gap_count") or 0), 1)

    def test_per_arm_tablet_text_satisfying_both_arms_not_gapped(self) -> None:
        """T2：按臂分述片数且两臂算平 → 无算术缺口。"""
        report = _report([
            "试验药物薄膜衣片（规格40mg/片）口服，每日两次（BID）。"
            "160mg剂量组每次服用两片（40mg×2片×每日2次=160mg）；"
            "80mg剂量组每次服用一片（40mg×1片×每日2次=80mg）。"
        ])
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertNotIn("日剂量", reasons)

    def test_generic_dosing_without_arm_labels_not_gapped(self) -> None:
        """T3：无臂名剂量标签的给药章不触发算术门。"""
        report = _report([
            "试验药物薄膜衣片（规格40mg/片）口服，每次服用一片，每日两次（BID），"
            "连续给药12周；具体剂量组分配见随机化章节。"
        ])
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertNotIn("日剂量", reasons)


if __name__ == "__main__":
    unittest.main()
