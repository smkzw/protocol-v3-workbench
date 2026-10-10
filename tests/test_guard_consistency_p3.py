"""新纪元第3轮修订·第二步：守卫完整性三方一致性断言（反例先红）。

现场（深度分析·第2轮，NC401 导出件实测）：工件节带守卫标记（6.2 有
'剂量出处：内部IB v2.3'、工件内 9.1 有样本量锚点注记），导出件正文却无
对应标记——守卫只接在 chunk 完成路径，旁路采纳把无标记正文送上纸面。

三方一致性契约（红先修后）：
- 检测器在导出文本上判出的守卫状态必须携带对应标记，缺失即计缺口
  （'守卫标记缺失'→草案-N），不静默：
  ①统计/样本量节声明自洽 → 必须有'（样本量依据：'或'假设未具名溯源'；
  ②声明不一致/要素未齐 → 必须有'样本量复算注记'或'样本量待确认'；
  ③口径混写 → 必须有'口径混写待确认'；
  ④统计章五件套缺件 → 必须有'统计章分节装配待确认'；
  ⑤给药节零剂量 → 必须有'剂量待确认'。
- 骨架节豁免（骨架门另行点名）。
- chunk 完成路径与全稿采纳路径共用统一守卫入口
  apply_full_draft_content_guards（任何采纳路径不得绕过）。
"""
from __future__ import annotations

import unittest

_CONSISTENT_DECLARATION = (
    "样本量按组间差6分、SD 12、双侧α=0.05、把握度80%计算，需每组63例，"
    "本研究计划入组126例受试者。"
)
_INCONSISTENT_DECLARATION = (
    "样本量按组间差6分、SD 12、双侧α=0.05、把握度80%计算，两组各45例，"
    "本研究计划入组90例受试者。"
)
_MIXED_SIDEDNESS = (
    "样本量计算采用双侧α=0.05、把握度90%的假设；推导过程按单侧α=0.05"
    "计算检验把握度，需每组82例。"
)
_STATS_ASSEMBLY_MISSING = (
    "本节说明主要终点检验方法：采用CMH检验比较两组应答者比例。"
    "全部推断基于主要分析人群开展。"
)
_NO_DOSE_TEXT = "KZ-BE204片每日一次晨服，连续给药12周；两臂按1:1随机并全程双盲。"


def _report(sections_spec):
    from services.api.app.main import _export_placeholder_report
    from packages.contracts.workbench_contracts import (
        ProtocolDocument,
        ProtocolSection,
    )

    document = ProtocolDocument(
        document_id="doc_guard_consistency",
        project_id="proj_guard_consistency",
        protocol_id="CMS-GC",
        version="1.0",
        sections=[
            ProtocolSection(
                section_id=section_id,
                document_id="doc_guard_consistency",
                heading=heading,
                section_number=number,
                content_blocks=[
                    {"block_id": f"b_{section_id}", "block_type": "paragraph", "text": text}
                ],
            )
            for section_id, number, heading, text in sections_spec
        ],
    )
    return _export_placeholder_report(document)


def _reasons(report):
    return " ".join(
        str(item.get("reason") or "")
        for item in report.get("gap_sections") or []
    )


class GuardMarkerConsistencyTests(unittest.TestCase):
    def test_consistent_declaration_without_provenance_marker_is_gapped(self) -> None:
        report = _report(
            (("sec_9_1", "9.1", "样本量", _CONSISTENT_DECLARATION),)
        )
        self.assertIn("守卫标记缺失", _reasons(report))
        self.assertIn("样本量溯源注记", _reasons(report))

    def test_consistent_declaration_with_anchor_marker_not_gapped(self) -> None:
        report = _report(
            (
                (
                    "sec_9_1",
                    "9.1",
                    "样本量",
                    _CONSISTENT_DECLARATION
                    + "（样本量依据：先例试验 XYZ-101，N=126）",
                ),
            )
        )
        self.assertNotIn("样本量溯源注记", _reasons(report))

    def test_inconsistent_declaration_uses_existing_gap_not_marker_gate(self) -> None:
        # 口径：不一致/要素未齐由既有导出门点名，标记门不重复计（单缺口）。
        report = _report(
            (("sec_9_1", "9.1", "样本量", _INCONSISTENT_DECLARATION),)
        )
        self.assertEqual(0, _reasons(report).count("守卫标记缺失"))
        self.assertIn("样本量不一致", _reasons(report))

    def test_marker_gate_is_silent_for_mixed_and_assembly_cases(self) -> None:
        # 混写/装配缺件由 E9/E11 导出门负责；标记门不得叠加重复缺口。
        report = _report(
            (
                ("sec_9_1", "9.1", "样本量", _MIXED_SIDEDNESS),
                ("sec_9_2", "9.2", "统计分析数据集", _STATS_ASSEMBLY_MISSING),
            )
        )
        self.assertNotIn("守卫标记缺失", _reasons(report))

    def test_shared_guard_entry_exists_and_covers_all_three(self) -> None:
        import inspect

        from services.api.app.medical_writing_full_draft import (
            apply_full_draft_content_guards,
        )

        source = inspect.getsource(apply_full_draft_content_guards)
        for fn in (
            "apply_sample_size_guard_to_section",
            "apply_dose_presence_guard_to_section",
            "apply_statistics_assembly_guard_to_section",
        ):
            self.assertIn(fn, source)


if __name__ == "__main__":
    unittest.main()
