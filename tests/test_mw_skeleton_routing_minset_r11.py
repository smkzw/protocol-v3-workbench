"""第10轮末修订·归位批最小件（P0-05残余/P1-07/P1-12/P1-13 各取最小件）。

反例（BE204/r10-B，example×7、considerations英文残留、AESI悬空引用）：
- 骨架『风险控制计划：…按 AESI 章节执行主动监测』在文档无 AESI 实文章
  节时为悬空引用（P1-12）；
- SAE 骨架把占位邮箱 safety@sponsor.example 印进导出件×7（P1-13）；
  同段还有『应在24小时内…应在24小时内』病句；
- 妊娠/避孕骨架对所有适应症都印 VZV 筛查句（P1-14：第14个适应症错配）
  且句内英文 considerations 直出（P1-07）。

契约（红先修后）：
T1 AESI条件化：aesi_definitions 为空 → 『按安全性监测章节执行主动监测』；
   非空 → 保留『按 AESI 章节执行』；
T2 骨架不再印占位邮箱：改为『药物警戒联系人及邮箱待医学经理按项目
   联络表填写』；病句修复（单次24小时）；
T3 considerations 中文化；VZV 句仅在 VZV/水痘专属标题下出现。
"""

from __future__ import annotations

import unittest


def _block(heading: str, overrides: dict | None = None) -> dict:
    from services.api.app.medical_writing_repository import (
        _gap_placeholder_block,
    )

    return _gap_placeholder_block(
        {"section_id": "sec_skel", "heading": heading}, overrides or {}
    )


class AesiConditionalTests(unittest.TestCase):
    def test_no_aesi_definitions_uses_safety_monitoring_phrase(self) -> None:
        text = _block("14.4 数据监查委员会", {"design_dmc_planned": True})["text"]
        self.assertIn("按安全性监测章节执行主动监测", text)
        self.assertNotIn("按 AESI 章节执行", text)

    def test_with_aesi_definitions_keeps_aesi_reference(self) -> None:
        text = _block(
            "14.4 数据监查委员会",
            {"design_dmc_planned": True, "aesi_definitions": ["严重感染"]},
        )["text"]
        self.assertIn("按 AESI 章节执行主动监测", text)


class ExampleEmailRemovalTests(unittest.TestCase):
    def test_sae_skeleton_has_no_placeholder_email_and_fixed_sentence(self) -> None:
        text = _block("8.6 不良事件的报告")["text"]
        self.assertNotIn("safety@sponsor.example", text)
        self.assertIn("药物警戒联系人及邮箱待医学经理按项目联络表填写", text)
        # 病句修复：单次24小时（旧文『应在获知…24小时内将完整信息…应在
        # 24 小时内通过专用报告表报告』双次出现）。
        self.assertNotIn("）应在 24 小时内", text)

    def test_no_skeleton_carries_placeholder_email(self) -> None:
        for heading in (
            "8.6 不良事件的报告",
            "4.4 紧急揭盲",
            "8.5 妊娠",
            "14.4 数据监查委员会",
        ):
            self.assertNotIn(
                "safety@sponsor.example",
                _block(heading)["text"],
                f"{heading} 骨架仍携带占位邮箱。",
            )


class ConsiderationsAndVzvTests(unittest.TestCase):
    def test_pregnancy_heading_has_no_english_and_no_vzv_sentence(self) -> None:
        text = _block("8.5 妊娠")["text"]
        self.assertNotIn("considerations", text)
        self.assertNotIn("VZV", text)

    def test_vzv_specific_heading_keeps_localized_vzv_sentence(self) -> None:
        text = _block("8.5 VZV/水痘-带状疱疹血清学筛查")["text"]
        self.assertIn("VZV", text)
        self.assertNotIn("considerations", text)
        self.assertIn("说明书接种建议", text)


if __name__ == "__main__":
    unittest.main()
