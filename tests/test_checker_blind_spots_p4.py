"""新纪元第4轮修订·第二刀③④：检查器盲区消误报（红先）。

- ③ 顺序检验识别补'Holm递阶/递阶策略/递阶检验'——HA501 9.2 实际写了
  'Holm递阶策略'仍被判缺顺序检验声明（误报喂养悬置块噪音）；
- ④ 分析集成员规则识别补成员判定句式——'所有随机…纳入''接受研究药物
  给药…受试者''FAS/SS/PP 包括/指/定义为'都是规范成员句，此前只认
  方案偏离/入选标准词族，名词句被误判缺成员规则。
"""
from __future__ import annotations

import unittest

_HOLM_TEXT = (
    "9.2 统计分析数据集：全分析集（FAS）包括所有随机入组并接受至少一次研究"
    "治疗的受试者；多重性控制采用Holm递阶策略，按预先设定的检验顺序逐级检验。"
    "缺失数据采用多重填补，敏感性分析含临界点分析与跳转至参考；SAP执行与"
    "揭盲相互隔离，非盲统计师防火墙在案。"
)
_NOUN_ONLY_TEXT = (
    "9.2 统计分析数据集：主要分析集为FAS，PPS用于敏感性分析。"
    "多重性采用Holm递阶策略。敏感性分析见相关章节；揭盲隔离有安排。"
)


class CheckerBlindSpotTests(unittest.TestCase):
    def _assembly(self, text):
        from services.api.app.medical_writing_full_draft import (
            statistics_assembly_check,
        )

        return statistics_assembly_check(text)

    def test_holm_strategy_counts_as_ordered_test_declaration(self) -> None:
        check = self._assembly(_HOLM_TEXT)
        self.assertNotIn(
            "顺序检验声明", check["missing"],
            "写了 Holm 递阶策略仍判缺顺序检验=误报。",
        )

    def test_holm_alone_is_not_member_rule(self) -> None:
        check = self._assembly(_NOUN_ONLY_TEXT)
        self.assertIn(
            "分析集成员规则", check["missing"],
            "名词句（FAS/PPS 用于…）不构成成员规则——不得漏判。",
        )

    def test_member_rule_sentence_patterns_recognized(self) -> None:
        for sentence in (
            "全分析集（FAS）包括所有随机入组的受试者，安全性分析集（SS）"
            "包括接受研究药物给药并有记录的受试者，符合方案集（PP）排除"
            "重大方案偏离者。",
            "FAS定义为所有随机化受试者的集合，SS定义为接受研究药物给药"
            "并完成安全性评估的受试者集合，PP定义为无重大方案偏离且完成"
            "主要终点评估的受试者集合。",
        ):
            check = self._assembly(
                sentence + "多重性控制与敏感性分析安排见后；非盲统计师防火墙在案。"
            )
            self.assertNotIn(
                "分析集成员规则", check["missing"],
                f"规范成员句未被识别：{sentence[:20]}…",
            )


if __name__ == "__main__":
    unittest.main()
