"""新纪元第1轮修订（E11）：统计章分节装配五件套（规格：
t17_round27_loop/SPEC_statistical_chapter_assembly_20261007.md，P1-49）。

立案（R8 审阅者B DM/Stat 四件差距 + 防火墙，第9轮复核维持）：成型方案
（20261006c 基准轮）已提供全部五件的正向样例（IGA-TS 应答者定义 +
ICH E9(R1) 估计目标矩阵 + MI+双敏感性分析）；系统现状 9.2 零成员定义。

五件：
1. 分析集成员规则（FAS/SS/PP 逐集命中 + 三段式成员规则措辞）；
2. 多重性控制必须指向存在的终点族（生成层按实际终点清单校验，声明
   对象不存在即挂起块——R1-B 反例：3.2 次要终点全空而声明控制对象）；
3. 敏感性分析双法明示（多重填补 MI + 至少一种 tipping/跳转至参考法）；
4. 顺序检验声明（多重性控制下的检验顺序，未声明时不编造检验树）；
5. 非盲统计师防火墙（SAP 执行与揭盲隔离声明位）。

验收（反例先红）：缺件生成层挂起块（含锁定条件）；导出层计缺口
（草案-N 强制）；正例（五件齐）不误伤。
"""
from __future__ import annotations

import unittest

COMPLETE_STATS_TEXT = (
    "9.2 分析集定义：全分析集（FAS）包括所有随机入组且接受至少一次研究"
    "治疗的受试者；安全性分析集（SS）包括接受至少一次给药并具有用药后"
    "安全性评估记录的受试者；符合方案集（PPS/PP）指入组标准符合、无重大"
    "方案偏离且完成主要终点评估的受试者。"
    "多重性控制：主要终点与关键次要终点族采用分层顺序检验"
    "（gatekeeping 策略，按既定检验顺序逐级检验，任一层失败即停止。"
    "缺失数据采用多重填补（MI），并以临界点分析（tipping point）与跳转"
    "至参考（jump to reference）双敏感性分析检验结论稳健性。"
    "SAP 的执行与揭盲相互隔离：非盲统计师独立执行期中分析与揭盲后统计，"
    "防火墙声明在案。"
)

SAMPLE_SIZE_ONLY_TEXT = (
    "样本量按组间差1.5、SD 3.2、双侧α=0.05、把握度90%，复算需每组96例；"
    "考虑15%脱落放大后每组113例，共230例。"
)

EMPTY_SECONDARY_FAMILIES = {
    "主要终点": True,
    "关键次要终点": True,
    "次要终点": False,
    "探索性终点": True,
}
FULL_FAMILIES = {
    "主要终点": True,
    "关键次要终点": True,
    "次要终点": True,
    "探索性终点": True,
}

MULTIPLICITY_ON_EMPTY_FAMILY = (
    "多重性控制：主要终点与次要终点族采用顺序检验（gatekeeping），"
    "按既定检验顺序逐级检验。分析集：全分析集（FAS）、安全性分析集（SS）、"
    "符合方案集（PPS）均含成员规则与无重大方案偏离要求。缺失数据采用多重"
    "填补（MI），敏感性分析含临界点分析（tipping point）与跳转至参考"
    "（jump to reference）。SAP 执行与揭盲隔离，非盲统计师防火墙在案。"
)


def _check(text: str, **kwargs):
    from services.api.app.medical_writing_full_draft import (
        statistics_assembly_check,
    )

    return statistics_assembly_check(text, **kwargs)


class StatisticsAssemblyCheckTests(unittest.TestCase):
    def test_complete_positive_has_no_missing_pieces(self) -> None:
        check = _check(COMPLETE_STATS_TEXT)
        self.assertEqual([], check["missing"])

    def test_sample_size_only_text_misses_all_five(self) -> None:
        check = _check(SAMPLE_SIZE_ONLY_TEXT)
        for piece in (
            "分析集成员规则",
            "多重性终点族",
            "敏感性双法",
            "顺序检验声明",
            "非盲统计师防火墙",
        ):
            self.assertIn(piece, check["missing"])

    def test_multiplicity_reference_validated_against_endpoint_families(self) -> None:
        check = _check(MULTIPLICITY_ON_EMPTY_FAMILY, endpoint_families=EMPTY_SECONDARY_FAMILIES)
        self.assertIn("多重性终点族", check["missing"])
        self.assertIn("次要终点", check.get("invalid_multiplicity_targets") or [])

        ok = _check(MULTIPLICITY_ON_EMPTY_FAMILY, endpoint_families=FULL_FAMILIES)
        self.assertNotIn("多重性终点族", ok["missing"])

    def test_plain_non_statistics_text_returns_no_missing(self) -> None:
        check = _check("本研究为随机双盲安慰剂对照研究。")
        self.assertEqual([], check["missing"])


class GenerationGuardTests(unittest.TestCase):
    def _guard(self, text: str, **kwargs) -> dict:
        from services.api.app.medical_writing_full_draft import (
            apply_statistics_assembly_guard_to_section,
        )

        section = {
            "section_number": "9",
            "heading": "统计学",
            "proposal_text": text,
        }
        apply_statistics_assembly_guard_to_section(section, **kwargs)
        return section

    def test_missing_pieces_get_suspension_block_with_lock_condition(self) -> None:
        section = self._guard(SAMPLE_SIZE_ONLY_TEXT)
        self.assertIn("统计章分节装配待确认", section["proposal_text"])
        self.assertIn("锁定条件", section["proposal_text"])
        self.assertIn("分析集成员规则", section["proposal_text"])
        self.assertIn(SAMPLE_SIZE_ONLY_TEXT[:10], section["proposal_text"])
        self.assertEqual(
            5, len(section["statistics_assembly_check"]["missing"])
        )

    def test_complete_section_untouched(self) -> None:
        section = self._guard(COMPLETE_STATS_TEXT)
        self.assertEqual(COMPLETE_STATS_TEXT, section["proposal_text"])
        self.assertEqual([], section["statistics_assembly_check"]["missing"])

    def test_invalid_multiplicity_target_gets_named_block(self) -> None:
        section = self._guard(
            MULTIPLICITY_ON_EMPTY_FAMILY,
            endpoint_families=EMPTY_SECONDARY_FAMILIES,
        )
        self.assertIn("次要终点", section["proposal_text"])
        self.assertIn("统计章分节装配待确认", section["proposal_text"])


class ExportGateTests(unittest.TestCase):
    def _report(self, text: str):
        from services.api.app.main import _export_placeholder_report
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )

        document = ProtocolDocument(
            document_id="doc_stats_assembly",
            project_id="proj_stats_assembly",
            protocol_id="CMS-STAT-11",
            version="1.0",
            sections=[
                ProtocolSection(
                    section_id="sec_9",
                    document_id="doc_stats_assembly",
                    heading="统计学",
                    section_number="9",
                    content_blocks=[
                        {
                            "block_id": "b9",
                            "block_type": "paragraph",
                            "text": text,
                        }
                    ],
                )
            ],
        )
        return _export_placeholder_report(document)

    def test_incomplete_statistics_chapter_counts_into_gap(self) -> None:
        report = self._report(SAMPLE_SIZE_ONLY_TEXT)
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("统计章分节装配", reasons)
        self.assertGreaterEqual(int(report.get("gap_count") or 0), 1)

    def test_complete_statistics_chapter_not_gapped_by_assembly(self) -> None:
        report = self._report(COMPLETE_STATS_TEXT)
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertNotIn("统计章分节装配", reasons)


if __name__ == "__main__":
    unittest.main()
