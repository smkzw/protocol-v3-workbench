"""新纪元第2轮修订 P0-B：骨架落位批（PV-C 六条裁决的代码化，第一组）。

现场（深度分析·第1轮）：PV-C 实证同一模板逐字进多节（重复7次/引导句
13-14 块）——_gap_placeholder_block 的每条安全模板都以同一段
'本节采用标准监管文本骨架（待医学经理…审核确认）。'开头，跨节逐字相同；
且骨架正文不带任何缺口标记，导出层只有【待补齐】占位计数，骨架节伪装成
成文内容通过空章门。

红用例：
T1 首段差异化——不同标题节的骨架文本首段各自点名本节标题与范围，不再
   共享同一句式开头；
T2 骨架身份元数据——块级 skeleton_review_pending=True + skeleton_scope
   =本节标题（导出缺口元数据，不依赖正文解析）；
T3 导出层骨架节计缺口——整节由骨架块构成的文档在 _export_placeholder_report
   计缺口（'参数化标准文本骨架'点名），草案-N 强制；真实正文节不误伤。
"""
from __future__ import annotations

import unittest


def _block(heading: str, overrides=None):
    from services.api.app.medical_writing_repository import _gap_placeholder_block

    return _gap_placeholder_block(
        {"heading": heading, "section_id": heading.replace(" ", "_")},
        overrides or {},
    )


class SkeletonDifferentiationTests(unittest.TestCase):
    def test_first_paragraph_names_its_own_section(self) -> None:
        stop = _block("6.4 研究性干预剂量调整")["text"]
        self.assertIn("6.4 研究性干预剂量调整", stop.split("。")[0])
        self.assertIn("范围限本节", stop.split("。")[0])

    def test_different_sections_no_longer_share_generic_opener(self) -> None:
        stop = _block("6.3 研究性干预剂量调整")["text"]
        pregnancy = _block("8.4 妊娠期女性与避孕")["text"]
        self.assertNotIn("本节采用标准监管文本骨架", stop)
        self.assertNotIn("本节采用标准监管文本骨架", pregnancy)
        self.assertNotEqual(
            stop.split("。")[0], pregnancy.split("。")[0],
            "两个不同节的骨架首段不得逐字相同。",
        )

    def test_skeleton_block_carries_review_pending_metadata(self) -> None:
        block = _block("7.1 个体受试者试验干预终止")
        self.assertIs(True, block.get("skeleton_review_pending"))
        self.assertEqual("7.1 个体受试者试验干预终止", block.get("skeleton_scope"))
        self.assertEqual("full_draft_gap_marker", block.get("source_kind"))


class SkeletonExportGateTests(unittest.TestCase):
    def _report(self, sections_spec):
        from services.api.app.main import _export_placeholder_report
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )

        document = ProtocolDocument(
            document_id="doc_skel_gate",
            project_id="proj_skel_gate",
            protocol_id="CMS-SKEL",
            version="1.0",
            sections=[
                ProtocolSection(
                    section_id=section_id,
                    document_id="doc_skel_gate",
                    heading=heading,
                    section_number=number,
                    content_blocks=blocks,
                )
                for section_id, number, heading, blocks in sections_spec
            ],
        )
        return _export_placeholder_report(document)

    def test_skeleton_only_section_counts_into_gap(self) -> None:
        block = _block("6.3 研究性干预剂量调整")
        report = self._report(
            (("sec_64", "6.4", "研究性干预剂量调整", [dict(block)]),)
        )
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("参数化标准文本骨架", reasons)
        self.assertGreaterEqual(int(report.get("gap_count") or 0), 1)

    def test_real_content_section_not_flagged_as_skeleton(self) -> None:
        report = self._report(
            (
                (
                    "sec_1",
                    "1",
                    "研究背景",
                    [
                        {
                            "block_id": "b1",
                            "block_type": "paragraph",
                            "text": (
                                "特应性皮炎是一种慢性复发性炎症性皮肤病，"
                                "本研究基于已确认的设计事实撰写研究背景，"
                                "正文内容与来源证据一一对应，供医学审阅。"
                            ),
                        }
                    ],
                ),
            )
        )
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertNotIn("参数化标准文本骨架", reasons)


if __name__ == "__main__":
    unittest.main()
