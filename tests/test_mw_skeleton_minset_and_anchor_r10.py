"""第9轮末修订·收口片（P0-05/06骨架最小集）+ P1-48锚点字段。

反例三件（r9-B:63 实证，ID701）：
- 骨架『计划入组96例』vs 设计总数230——现行正则抓 sample_size_strategy
  首个『N例』（96=放大前每组数），『共N例』总数永不入骨架；
- 骨架『未记录比例』vs 正文1:1——assignment_model 已确认但未注入；
- 骨架4.5区设独立DMC vs 正文『DMC不适用』——模板无设计事实分支。

契约（红先修后）：
T1 总数优先：『共N例』命中即用（ID701→计划入组230例）；未命中回落
   首数字（每组45例→45）；
T2 分配比例：structured_design.assignment_model 非空时骨架写
   『按{比例}随机分配』，空时保留『未记录具体比例』占位；
T3 DMC分支：dmc_planned=False → 『不设立独立的数据监查委员会』；
   True/未记录 → 设立表述保留；
T4 锚点字段：PicosDefinition.sample_size_anchor 可选自由文本；
   生成层有锚点时统计章附『（样本量依据：{锚点}）』，无锚点且含
   样本量声明时附『假设未具名溯源，建议引用外部先例』。
"""

from __future__ import annotations

import unittest

from packages.contracts.workbench_contracts import (
    MedicalWritingPicosDefinition,
)

RANDOM_OVERRIDES = {
    "design_comparator_type": "placebo",
    "design_randomization_mode": "randomized",
    "design_blinding_mode": "double_blind",
}


def _section(heading: str) -> dict:
    return {"section_id": "sec_skel", "heading": heading}


def _block(heading: str, overrides: dict) -> dict:
    from services.api.app.medical_writing_repository import (
        _gap_placeholder_block,
    )

    return _gap_placeholder_block(_section(heading), overrides)


class SkeletonTotalFirstTests(unittest.TestCase):
    def test_total_takes_precedence_over_per_group(self) -> None:
        overrides = {
            **RANDOM_OVERRIDES,
            # ID701 现场形态：正文推导链带『每组96…共230』。
            "sample_size_strategy": (
                "按组间差1.5、SD 3.2、双侧α=0.05、把握度90%，复算需每组96例；"
                "考虑15%脱落每组113例、共230例。"
            ),
        }
        text = _block("4.3 随机化与盲法", overrides)["text"]
        self.assertIn("计划入组230例受试者", text)
        self.assertNotIn("计划入组96例", text)

    def test_fallback_keeps_first_number_without_total(self) -> None:
        overrides = {
            **RANDOM_OVERRIDES,
            "sample_size_strategy": "每组45例；按组间差4.5%、SD 6.5%设定。",
        }
        text = _block("4.3 随机化与盲法", overrides)["text"]
        self.assertIn("计划入组45例受试者", text)

    def test_no_declaration_keeps_pending_placeholder(self) -> None:
        overrides = {**RANDOM_OVERRIDES, "sample_size_strategy": ""}
        text = _block("4.3 随机化与盲法", overrides)["text"]
        self.assertIn("既定样本量", text)


class AllocationRatioTests(unittest.TestCase):
    def test_assignment_model_injected_into_randomization_sentence(self) -> None:
        overrides = {
            **RANDOM_OVERRIDES,
            "design_assignment_model": "1:1",
            "sample_size_strategy": "",
        }
        text = _block("4.3 随机化与盲法", overrides)["text"]
        self.assertIn("按1:1比例随机分配", text)
        self.assertNotIn("未记录具体比例", text)

    def test_unrecorded_ratio_keeps_pending_placeholder(self) -> None:
        overrides = {**RANDOM_OVERRIDES, "sample_size_strategy": ""}
        text = _block("4.3 随机化与盲法", overrides)["text"]
        self.assertIn("未记录具体比例", text)


class DmcBranchTests(unittest.TestCase):
    def test_dmc_false_says_not_established(self) -> None:
        overrides = {"design_dmc_planned": False}
        text = _block("14.4 数据监查委员会", overrides)["text"]
        self.assertIn("不设立独立的数据监查委员会", text)
        self.assertNotIn("设立独立的 数据监查委员会", text)

    def test_dmc_true_keeps_established_template(self) -> None:
        overrides = {"design_dmc_planned": True}
        text = _block("14.4 数据监查委员会", overrides)["text"]
        self.assertIn("设立独立的 数据监查委员会", text)

    def test_dmc_unrecorded_keeps_pending_review_wording(self) -> None:
        overrides = {}
        text = _block("14.4 数据监查委员会", overrides)["text"]
        self.assertIn("设立独立的 数据监查委员会", text)
        self.assertIn("待医学经理", text)


class SampleSizeAnchorTests(unittest.TestCase):
    def test_contract_accepts_optional_anchor_field(self) -> None:
        picos = MedicalWritingPicosDefinition(
            sample_size_strategy="按组间差6分、SD 12、双侧α=0.05、把握度80%，需63例/组。",
            sample_size_anchor="INCB 18424-304（既往JAK抑制剂III期，同推导口径）",
        )
        self.assertIn("INCB 18424-304", picos.sample_size_anchor)

    def test_guard_appends_anchor_citation_when_present(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_sample_size_guard_to_section,
        )

        section = {
            "section_id": "sec_stat",
            "section_number": "9.1",
            "heading": "样本量",
            "proposal_text": "9.1 样本量。按组间差6分、SD 12、双侧α=0.05、把握度80%，需63例/组。",
        }
        apply_sample_size_guard_to_section(section, anchor="INCB 18424-304")
        self.assertIn("（样本量依据：INCB 18424-304）", section["proposal_text"])

    def test_guard_notes_missing_provenance_when_anchor_absent(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_sample_size_guard_to_section,
        )

        section = {
            "section_id": "sec_stat",
            "section_number": "9.1",
            "heading": "样本量",
            "proposal_text": "9.1 样本量。按组间差6分、SD 12、双侧α=0.05、把握度80%，需63例/组。",
        }
        apply_sample_size_guard_to_section(section, anchor="")
        self.assertIn("假设未具名溯源", section["proposal_text"])
        self.assertIn("建议引用外部先例", section["proposal_text"])

    def test_non_statistical_section_untouched(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_sample_size_guard_to_section,
        )

        original = "4.1 总体设计。本研究采用随机双盲安慰剂对照设计，共90例。"
        section = {
            "section_id": "sec_design",
            "section_number": "4.1",
            "heading": "总体设计",
            "proposal_text": original,
        }
        apply_sample_size_guard_to_section(section, anchor="")
        self.assertEqual(original, section["proposal_text"])


if __name__ == "__main__":
    unittest.main()
