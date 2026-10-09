"""新纪元第2轮修订 P1 内容族（NEW-17 / NEW-BENCH-3 / NEW-16 禁语半边）
反例先红。

- NEW-17：编号节零实质正文且无合规『不适用+理由』声明 → 导出缺口
  （空标题不得上纸；N/A 声明必须带理由，光写'不适用'不算数）；
- NEW-17 骨架层：外用药（给药途径含'外用/局部'）项目的 PK/PD 类节由
  设计事实推理由，自动落『不适用+理由』声明，不再留【待补齐】；
- NEW-BENCH-3/NEW-16 导出禁语：法规版本悬置句（'以方案定稿时确认的
  版本为准'）、术语错（'单侧把握度'）、推空句（'在统计分析计划中统一
  规定'）各计缺口并点名。
"""
from __future__ import annotations

import unittest


def _block(heading: str, overrides=None):
    from services.api.app.medical_writing_repository import _gap_placeholder_block

    return _gap_placeholder_block(
        {"heading": heading, "section_id": heading.replace(" ", "_")},
        overrides or {},
    )


class NotApplicableDeclarationTests(unittest.TestCase):
    PK_HEADING = "7.4 药代动力学评估"

    def test_topical_route_gets_not_applicable_with_reason(self) -> None:
        block = _block(self.PK_HEADING, {"administration_route": "外用"})
        text = str(block.get("text") or "")
        self.assertIn("不适用", text)
        self.assertIn("理由", text)
        self.assertIn("外用", text)
        self.assertNotIn("【待补齐】", text)
        self.assertIs(True, block.get("skeleton_review_pending"))

    def test_non_topical_route_keeps_placeholder(self) -> None:
        block = _block(self.PK_HEADING, {"administration_route": "口服"})
        self.assertIn("【待补齐】", str(block.get("text") or ""))

    def test_missing_route_keeps_placeholder(self) -> None:
        block = _block(self.PK_HEADING, {})
        self.assertIn("【待补齐】", str(block.get("text") or ""))

    def test_pd_heading_also_covered(self) -> None:
        block = _block("7.5 药效动力学评估", {"administration_route": "局部给药"})
        self.assertIn("不适用", str(block.get("text") or ""))

    def test_unrelated_heading_untouched_by_route(self) -> None:
        block = _block("6.4 研究性干预剂量调整", {"administration_route": "外用"})
        self.assertNotIn("不适用", str(block.get("text") or ""))


class NaDeclarationExportGateTests(unittest.TestCase):
    def _report(self, section_number, heading, blocks):
        from services.api.app.main import _export_placeholder_report
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )

        document = ProtocolDocument(
            document_id="doc_na_gate",
            project_id="proj_na_gate",
            protocol_id="CMS-NA",
            version="1.0",
            sections=[
                ProtocolSection(
                    section_id="sec_na",
                    document_id="doc_na_gate",
                    heading=heading,
                    section_number=section_number,
                    content_blocks=blocks,
                )
            ],
        )
        return _export_placeholder_report(document)

    def test_numbered_empty_section_gapped_with_na_reason(self) -> None:
        report = self._report(
            "7.4",
            "药代动力学评估",
            [{"block_id": "b1", "block_type": "paragraph", "text": ""}],
        )
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("零实质正文", reasons)
        self.assertIn("不适用+理由", reasons)

    def test_na_without_reason_still_gapped(self) -> None:
        report = self._report(
            "7.4",
            "药代动力学评估",
            [
                {
                    "block_id": "b1",
                    "block_type": "paragraph",
                    "text": "不适用。",
                }
            ],
        )
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("零实质正文", reasons)

    def test_na_with_reason_passes_gate(self) -> None:
        report = self._report(
            "7.4",
            "药代动力学评估",
            [
                {
                    "block_id": "b1",
                    "block_type": "paragraph",
                    "text": (
                        "本节不适用。理由：本研究药物为外用（局部给药）乳膏制剂，"
                        "全身暴露量极低，不设药代动力学评估；该安排与方案设计"
                        "事实一致并经医学经理确认。"
                    ),
                }
            ],
        )
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertNotIn("零实质正文", reasons)


class ForbiddenPhraseExportGateTests(unittest.TestCase):
    def _report(self, text):
        from services.api.app.main import _export_placeholder_report
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )

        document = ProtocolDocument(
            document_id="doc_forbidden",
            project_id="proj_forbidden",
            protocol_id="CMS-FORB",
            version="1.0",
            sections=[
                ProtocolSection(
                    section_id="sec_1",
                    document_id="doc_forbidden",
                    heading="研究背景",
                    section_number="1",
                    content_blocks=[
                        {"block_id": "b1", "block_type": "paragraph", "text": text}
                    ],
                )
            ],
        )
        return _export_placeholder_report(document)

    def test_regulatory_version_deferral_is_gapped(self) -> None:
        report = self._report(
            "毒性分级将采用CTCAE分级标准，具体版本以方案定稿时确认的版本为准，"
            "并按既定流程记录全部不良事件。"
        )
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("禁语", reasons)
        self.assertIn("以方案定稿时确认的版本为准", reasons)

    def test_one_sided_power_misnomer_is_gapped(self) -> None:
        report = self._report(
            "样本量按单侧把握度90%计算，共需例数如后续章节所述。"
        )
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("禁语", reasons)
        self.assertIn("单侧把握度", reasons)

    def test_sap_deferral_is_gapped(self) -> None:
        report = self._report(
            "起效时间的采集细节将在统计分析计划中统一规定，本节不再赘述。"
        )
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("禁语", reasons)

    def test_clean_text_not_gapped(self) -> None:
        report = self._report(
            "毒性分级采用CTCAE 5.0版标准，不良事件编码采用MedDRA 28.0版"
            "术语集，全部判定按既定流程记录。"
        )
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertNotIn("禁语", reasons)


class E14PpMembershipInstructionTests(unittest.TestCase):
    """E14：统计章指令钉一句 PP 成员=方案偏离排除条款（NEW-BENCH-4 的
    指令侧动作：mITT/PP 只有名词无定义的根因之一是生成指令未钉概念）。"""

    def test_instruction_pins_pp_membership_rule(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            MedicalWritingFullDraftService,
        )

        instruction = MedicalWritingFullDraftService._instruction(
            [{"section_id": "sec_9_2", "heading": "统计分析", "section_number": "9.2",
              "node_kind": "section", "body_text": ""}],
            {"minimum_body_chars": 80, "decision_path_owners": {}, "digest": "d"},
        )
        self.assertIn("符合方案集", instruction)
        self.assertIn("方案偏离", instruction)
        self.assertIn("排除", instruction)
        self.assertIn("全分析集", instruction)


if __name__ == "__main__":
    unittest.main()
