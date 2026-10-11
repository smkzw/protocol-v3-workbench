"""新纪元第4轮末修订（P0-2/NEW-31）：守卫幂等——同节两次过守卫链标记
恰一份。RT3 第6章引言双份连排实证（'（剂量出处待标注：…）'×3 上纸）。

修后契约（反例先红）：同一节两次过 apply_full_draft_content_guards →
各守卫标记恰一份、文本无重复段；二次调用为无操作。
"""
from __future__ import annotations

import unittest


def _guarded_twice(text: str) -> dict:
    from services.api.app.medical_writing_full_draft import (
        apply_full_draft_content_guards,
    )

    section = {
        "section_id": "sec_twice",
        "section_number": "6.2",
        "heading": "研究治疗与给药",
        "proposal_text": text,
    }
    apply_full_draft_content_guards([section])
    apply_full_draft_content_guards([section])
    return section


class GuardIdempotencyTests(unittest.TestCase):
    def test_dose_source_marker_exactly_once_after_double_guard(self) -> None:
        section = _guarded_twice(
            "KZ-BE204片25mg每日一次晨服，连续给药12周；两臂按1:1随机分配并全程双盲。"
        )
        text = section["proposal_text"]
        self.assertEqual(1, text.count("（剂量出处"), text)

    def test_dose_missing_block_not_duplicated(self) -> None:
        section = _guarded_twice("KZ-BE204片每日一次晨服，连续给药12周。")
        text = section["proposal_text"]
        self.assertEqual(1, text.count("【剂量待确认"), text)

    def test_statistics_assembly_block_not_duplicated(self) -> None:
        section = {
            "section_id": "sec_stat",
            "section_number": "9",
            "heading": "统计学",
            "proposal_text": (
                "样本量每组45例；20%vs45%，双侧α=0.05、把握度90%。"
                "本节仅有样本量句，统计章缺分析集与防火墙等件。"
            ),
        }
        from services.api.app.medical_writing_full_draft import (
            apply_full_draft_content_guards,
        )

        apply_full_draft_content_guards([section])
        once = section["proposal_text"]
        apply_full_draft_content_guards([section])
        self.assertEqual(1, once.count("【统计章分节装配待确认"), once)
        self.assertEqual(once, section["proposal_text"])


if __name__ == "__main__":
    unittest.main()
