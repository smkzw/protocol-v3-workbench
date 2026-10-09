"""新纪元第1轮修订（E12）：6.3/6.4 停药规则操作化骨架 + 剂量出处标注
（账本：『6.3/6.4停药规则操作化空+SAE报告路径空（内容只在骨架尾部）』
与 E13 的『剂量无出处』件）。

红用例（先红后修）：
T1 停药规则章节（6.3/6.4，标题含 停药/终止治疗/剂量调整）此前落入
   通用AE骨架或【待补齐】——现在必须给操作化三段（暂停给药/减量/
   永久停药各带触发条件）+ 待医学经理确认槽（不编造具体阈值）；
T2 剂量已载明的给药章文本（mg 命中、P0-27 门不触发）此前无出处标注
   ——现在生成层追加『剂量出处』诚实槽（未具名时标注待标注，不拦生成）。
"""
from __future__ import annotations

import unittest


def _block(heading: str, overrides=None):
    from services.api.app.medical_writing_repository import _gap_placeholder_block

    return _gap_placeholder_block(
        {"heading": heading, "section_number": heading.split(" ")[0]},
        overrides or {},
    )


class StopRuleSkeletonTests(unittest.TestCase):
    def test_stop_rule_heading_gets_operationalized_template(self) -> None:
        text = _block("6.3 停药规则与剂量调整")["text"]
        for marker in ("暂停给药", "减量", "永久停药", "待医学经理确认"):
            self.assertIn(marker, text)
        # 操作化：三段各带触发条件语义（毒性分级/恢复条件/停药指征）。
        self.assertIn("毒性", text)
        self.assertIn("恢复", text)
        self.assertIn("随访", text)

    def test_treatment_withdrawal_heading_matches_same_template(self) -> None:
        # 本模板族口径：7.1 个体受试者试验干预终止（ICH E3 编号）。
        text = _block("7.1 个体受试者试验干预终止")["text"]
        self.assertIn("永久停药", text)
        self.assertIn("暂停给药", text)

    def test_canonical_dose_adjustment_heading_matches(self) -> None:
        text = _block("6.4 研究性干预剂量调整")["text"]
        self.assertIn("剂量调整", text)
        self.assertIn("永久停药", text)

    def test_template_does_not_fabricate_thresholds(self) -> None:
        text = _block("6.3 停药规则与剂量调整")["text"]
        # 未确认阈值不得编造为既定事实——阈值处必须带待确认语义。
        self.assertIn("待医学经理确认", text)
        self.assertIn("不得编造", text)


class DoseSourceCitationTests(unittest.TestCase):
    def test_sourced_dose_text_gets_citation(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_dose_presence_guard_to_section,
        )

        section = {
            "section_number": "6.2",
            "heading": "研究治疗与给药",
            "proposal_text": "KZ-BE204片25mg每日一次晨服，连续给药12周。",
        }
        apply_dose_presence_guard_to_section(
            section, source="IB v2.0（2026-03）给药章节"
        )
        self.assertIn("剂量出处：IB v2.0（2026-03）给药章节", section["proposal_text"])
        self.assertNotIn("剂量缺失", section.get("dose_check", {}).get("status", ""))

    def test_unsourced_dose_text_gets_honest_pending_marker(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_dose_presence_guard_to_section,
        )

        section = {
            "section_number": "6.2",
            "heading": "研究治疗与给药",
            "proposal_text": "KZ-BE204片25mg每日一次晨服，连续给药12周。",
        }
        apply_dose_presence_guard_to_section(section)
        self.assertIn("剂量出处待标注", section["proposal_text"])
        self.assertIn("IB", section["proposal_text"])

    def test_zero_dose_block_unchanged(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_dose_presence_guard_to_section,
        )

        section = {
            "section_number": "6.2",
            "heading": "研究治疗与给药",
            "proposal_text": "KZ-BE204片每日一次晨服，连续给药12周。",
        }
        apply_dose_presence_guard_to_section(section)
        self.assertEqual("剂量缺失", section["dose_check"]["status"])


if __name__ == "__main__":
    unittest.main()
