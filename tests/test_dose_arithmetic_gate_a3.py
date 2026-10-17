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



# ── F2 臂名形态覆盖批（新纪元修订第1轮末，20261016）──────────────────────
# 现场（r1-C 10-13件实跑）：臂名写成分立形态『160mg BID（候选RP2D）与80mg
# BID』时，配对正则 ARM_LABEL matches: []，算术门静默 return []（今日实跑
# 复现）；同件含 40mg/片 + 每次一片。期望：分立/显式臂名三形态全命中；
# 臂存在而规格/频次/片数信息不全时计『信息不全』缺口，禁止静默放行。


class DisjunctArmFormTests(unittest.TestCase):
    def _gaps(self, text: str) -> list[str]:
        from services.api.app.main import _dose_arithmetic_gaps

        return _dose_arithmetic_gaps(text)

    def test_disjunct_arm_statements_hit_arithmetic_gap(self) -> None:
        """T4：分立形态臂名（160mg BID…与80mg BID）必须命中160mg算术缺口。"""
        reasons = self._gaps(
            "试验组接受研究药物160mg BID（候选RP2D）与80mg BID两剂量臂，"
            "均为每次一片口服。研究药物规格：40mg/片。"
        )
        joined = "\n".join(reasons)
        self.assertTrue(reasons, "分立臂名不得静默短路（r1-C 10-13件同证）")
        self.assertIn("160", joined)
        self.assertIn("算术不平", joined)
        self.assertNotIn("80mg臂按", joined, "80mg臂 40×1×2=80 自洽，不得误报")

    def test_arms_with_missing_spec_count_information_gap(self) -> None:
        """T5：臂存在而规格/频次缺失 → 计信息不全缺口，不得静默 return []。"""
        reasons = self._gaps("本研究设160mg BID与80mg BID两个剂量臂。")
        joined = "\n".join(reasons)
        self.assertTrue(reasons, "臂存在而信息不全必须计缺口")
        self.assertIn("信息不全", joined)
        self.assertIn("160mg", joined)

    def test_arms_with_missing_tablets_count_information_gap(self) -> None:
        """T6：臂存在、有规格频次但无任何片数表述 → 计信息不全缺口。"""
        reasons = self._gaps(
            "本研究设160mg BID与80mg BID两个剂量臂。研究药物规格：40mg/片。"
        )
        joined = "\n".join(reasons)
        self.assertTrue(reasons, "无片数表述不得静默放行")
        self.assertIn("信息不全", joined)


if __name__ == "__main__":
    unittest.main()
