"""R6 第6轮末修订 片C′（P1-42/P1-30/P2-36）：导出清扫正则族与版本策略。

现场（r5-A/export.docx 第127运行块，存储于 workbench_runtime 的
mwsec_greenfield_proj_user_90faa124c2ad…）：
`…40mg组第1周由20mg起始滴定导入；安（医学审核注：本章与已确认PICOS
事实一致；…表述建议在后续版本与方案摘要口径统一。）慰剂组接受匹配
双模拟安慰剂。…` ——『医学审核注』内联批注随 V1.0 正式导出，且把
「安慰剂」一词从中间剖开（评审读感即“正文截断于『安』”）。
另：r6-D export.docx 保密声明含错字「监管管理部门」。

契约（红先修后）：
- T1 导出副本剥离批注族（医学审核注/医学撰写批注/内部工作流话术/
  legacy-derived-* /【V\\d+】），剥离后正文自然回接（安慰剂不再被
  剖开），逐章注记留档；
- T2 剥离不掉的残段（未闭合）计入占位符报告 total，正式导出仍被拦；
- T3 版本策略：占位/批注计数>0 的 draft 导出，导出副本版本标签必须
  是 草案-N（存储文档版本不动）；V1.0 正式导出要求计数=0（既有门）；
- T4 错字「监管管理部门」→「监督管理部门」。
"""

from __future__ import annotations

import unittest

from packages.contracts.workbench_contracts import (
    ProtocolDocument,
    ProtocolSection,
)


def _document(*block_texts: str) -> ProtocolDocument:
    sections = [
        ProtocolSection(
            section_id=f"sec_{index}",
            document_id="doc_export_annotation_r6",
            heading=f"第{index + 1}章 测试",
            section_number=str(index + 1),
            content_blocks=[
                {
                    "block_id": f"blk_{index}",
                    "type": "paragraph",
                    "text": text,
                    "rich_text": {
                        "content": [
                            {"type": "text", "text": text},
                        ],
                    },
                }
            ],
        )
        for index, text in enumerate(block_texts)
    ]
    return ProtocolDocument(
        document_id="doc_export_annotation_r6",
        project_id="proj_export_annotation_r6",
        protocol_id="CMS-R6C-T",
        version="1.0",
        sections=sections,
    )


LEAKED = (
    "本研究采用三臂平行组设计，三个治疗组均每日一次口服给药，连续治疗8周，"
    "其中40mg组第1周由20mg起始滴定导入；安（医学审核注：本章与已确认PICOS事实一致；"
    "三臂1:1:1、8周双盲及第1周滴定导入表述建议在后续版本与方案摘要口径统一。）"
    "慰剂组接受匹配双模拟安慰剂。本研究不计划自适应设计。"
)


class ExportAnnotationSanitizationTests(unittest.TestCase):
    def test_annotation_family_is_stripped_and_prose_rejoins(self) -> None:
        from services.api.app.main import _apply_export_annotation_sanitization

        cases = [
            LEAKED,
            "本节按医学撰写批注：待与统计确认样本量假设。既定分析集保持不变。",
            "该描述来自内部工作流话术：骨架占位（待医学经理审核确认）。",
            "此段内容来源legacy-derived-block-17，供内部追溯。",
            "剂量调整规则【V3】按既定方案执行。",
        ]
        document = _document(*cases)
        notes = _apply_export_annotation_sanitization(document)

        cleaned = [
            block["text"]
            for section in document.sections
            for block in section.content_blocks
        ]
        for text in cleaned:
            for marker in (
                "医学审核注", "医学撰写批注", "内部工作流话术",
                "legacy-derived", "【V3】", "【V",
            ):
                self.assertNotIn(marker, text, f"导出副本不得再含工程/批注标记：{text}")
        # 剖开的「安慰剂」自然回接（不再截断于『安』）。
        self.assertIn("滴定导入；安慰剂组接受匹配双模拟安慰剂", cleaned[0])
        # rich_text 节点同步剥离（docx 渲染读 rich_text 时同样干净）。
        rich = document.sections[0].content_blocks[0]["rich_text"]["content"][0]["text"]
        self.assertNotIn("医学审核注", rich)
        self.assertIn("安慰剂组接受匹配双模拟安慰剂", rich)
        # 逐章注记留档（含章节号与命中计数）。
        self.assertTrue(notes, "剥离必须留逐章注记。")
        self.assertTrue(any(note.get("count", 0) >= 1 for note in notes))

    def test_unclosed_annotation_fragment_counts_into_placeholder_total(self) -> None:
        from services.api.app.main import (
            _apply_export_annotation_sanitization,
            _export_placeholder_report,
        )

        document = _document(
            "样本量假设尚未固化（医学审核注：待统计复核后补齐",
            "安全性监测计划已按既定方案执行。",
        )
        _apply_export_annotation_sanitization(document)
        report = _export_placeholder_report(document)
        self.assertGreaterEqual(
            int(report.get("total_count") or 0),
            1,
            "未闭合批注残段必须计入占位符 total（V1.0 门依赖该计数）。",
        )


class ExportVersionLabelPolicyTests(unittest.TestCase):
    def test_draft_with_placeholders_gets_cao_an_label_not_v1(self) -> None:
        from services.api.app.main import _export_version_label

        document = _document(LEAKED)
        label = _export_version_label(document, total_markers=2, mode="draft_preview")
        self.assertTrue(
            label.startswith("草案-"),
            f"占位/批注计数>0 的 draft 导出必须是草案-N标签，得到 {label!r}。",
        )
        self.assertNotEqual("1.0", label)

    def test_zero_marker_draft_keeps_formal_version_label(self) -> None:
        from services.api.app.main import _export_version_label

        document = _document("完整正文，无占位。")
        label = _export_version_label(document, total_markers=0, mode="draft_preview")
        self.assertEqual("1.0", label)

    def test_typo_replacement_covers_jianguan_guanli(self) -> None:
        from services.api.app.main import _apply_export_text_quality_lint

        document = _document(
            "本文件仅提供给研究者、伦理委员会、监管管理部门等相关机构审阅。"
        )
        notes = _apply_export_text_quality_lint(document)
        text = document.sections[0].content_blocks[0]["text"]
        self.assertIn("监督管理部门", text)
        self.assertNotIn("监管管理部门", text)
        self.assertTrue(
            any(note.get("wrong") == "监管管理部门" for note in notes),
            "错字替换必须留注记。",
        )


if __name__ == "__main__":
    unittest.main()
