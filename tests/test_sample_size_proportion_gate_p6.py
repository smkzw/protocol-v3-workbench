"""新纪元第2轮末修订（P1-6/NEW-BENCH-8/E9第四例）：样本量比例复算门。

现场（HS501，r2-B/r2-C 独立复算）：声明 20% vs 45%（Δ=25 个百分点）、
双侧 α=0.05、把握度 90% → 两比例 z 公式需约 69 例/组；正文写 45 例/组
（实际把握度 74.8%）——输入层与生成层同此 checker 故双层皆漏（门是连续
量专属）。修后比例分支与连续量同语义贯通：不一致→生成层改写+输入层阻断。

红例（先红后修）：
T1 声明形态 A：『每组45例；…预期应答率20%对45%，双侧α=0.05、把握度90%』
   → 判『不一致』，required_per_group==69；
T2 声明形态 B：『20%vs45%』紧凑形态 → 同判不一致；
T3 自洽正例：声明 69 例/组 → 『自洽』不误伤；
T4 口径指纹覆盖比例要素：p1 变化 → 指纹必变（按80算写90解耦的前置）；
T5 连续量行为不回退（GER601 形态仍 63 例/组）。
"""
from __future__ import annotations

import unittest

_HS501_DECLARED = (
    "样本量每组45例；基于预期应答率20%对45%（差值25个百分点），"
    "双侧α=0.05、把握度90%估算。"
)
_HS501_COMPACT = "每组45例；20%vs45%，双侧α=0.05、把握度90%。"
_HS501_CONSISTENT = (
    "样本量每组69例；基于预期应答率20%对45%，双侧α=0.05、把握度90%估算。"
)
_GER601 = "两组各45例共90例；按GERD-HRQL组间差6分、SD 12、α=0.05双侧、80%把握度探索性设定。"


def _check(text: str):
    from services.api.app.medical_writing_full_draft import (
        sample_size_declaration_check,
    )

    return sample_size_declaration_check(text)


class ProportionGateTests(unittest.TestCase):
    def test_hs501_declared_45_requires_69(self) -> None:
        """T1：HS501 形态——45/组必须判不一致（约69/组）。"""
        check = _check(_HS501_DECLARED)
        self.assertIsNotNone(check)
        self.assertEqual("不一致", check["status"])
        self.assertEqual(45, check["declared_per_group"])
        self.assertEqual(69, check["required_per_group"])

    def test_compact_vs_form_also_gated(self) -> None:
        """T2：紧凑 '20%vs45%' 形态同判。"""
        check = _check(_HS501_COMPACT)
        self.assertEqual("不一致", check["status"])
        self.assertEqual(69, check["required_per_group"])

    def test_consistent_proportion_declaration_passes(self) -> None:
        """T3：声明 69/组 → 自洽，不误伤。"""
        check = _check(_HS501_CONSISTENT)
        self.assertEqual("自洽", check["status"])
        self.assertEqual(69, check["required_per_group"])

    def test_proportion_assumptions_change_fingerprint(self) -> None:
        """T4：比例要素入指纹——假设修订必须改指纹（治'按80算写90'）。"""
        from services.api.app.medical_writing_full_draft import (
            sample_size_fingerprint,
        )

        base = sample_size_fingerprint(_HS501_DECLARED)
        revised = sample_size_fingerprint(
            _HS501_DECLARED.replace("20%对45%", "20%对48%")
        )
        self.assertIsNotNone(base)
        self.assertNotEqual(base, revised)

    def test_continuous_craft_unchanged(self) -> None:
        """T5：连续量形态不回退（GER601 仍 63 例/组不一致）。"""
        check = _check(_GER601)
        self.assertEqual("不一致", check["status"])
        self.assertEqual(63, check["required_per_group"])


if __name__ == "__main__":
    unittest.main()
