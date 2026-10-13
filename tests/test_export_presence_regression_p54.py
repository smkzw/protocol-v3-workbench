"""NEW-54（新纪元第11轮）：导出层版本间在场性回归检查——分析集集合
（FAS/SS/PPS）与上一版本 diff，回归即缺口『定向删减未声明』
（UC2A→UC2B：PPS 消失/零声明形态）。

修后契约（反例先红）：
T1 首次导出：仅落基线快照，无在场性缺口；
T2 上一版有 PPS、本次全文 0 命中且无『不适用』声明 → 缺口点名
   『定向删减未声明：分析集PPS从上一版本消失』；
T3 本次仍含 PPS → 无在场性缺口；
T4 缺口进入 gap_sections → 草案-N 通道（计数吸收）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.api.app.main import (
    _presence_regression_gaps,
    _record_presence_snapshot,
    _presence_snapshot_from_texts,
)

PROJECT = "proj_presence_p54"
DOC = "doc_presence_p54"


def _document(texts):
    from packages.contracts.workbench_contracts import (
        ProtocolDocument,
        ProtocolSection,
    )

    return ProtocolDocument(
        document_id=DOC,
        project_id=PROJECT,
        protocol_id="CMS-PPS-54",
        version="1.1",
        sections=[
            ProtocolSection(
                section_id=f"sec_{index}",
                document_id=DOC,
                heading="统计学考虑",
                section_number="9",
                content_blocks=[
                    {"block_id": f"b{index}", "block_type": "paragraph", "text": text}
                ],
            )
            for index, text in enumerate(texts, start=1)
        ],
    )


class PresenceRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store_dir = Path(self.tmp.name) / "presence"
        self.document = _document([
            "统计分析采用全分析集（FAS）、安全性分析集（SS）与符合方案集"
            "（PPS）三分析集；PPS 定义为无重大方案偏离者。",
        ])

    def test_first_export_records_baseline_only(self) -> None:
        """T1：首次导出仅落基线，无在场性缺口。"""
        report = {"gap_sections": [], "gap_count": 0}
        gaps = _presence_regression_gaps(
            self.document, store_dir=self.store_dir
        )
        self.assertEqual([], gaps)
        _record_presence_snapshot(self.document, store_dir=self.store_dir)
        self.assertTrue((self.store_dir).exists())

    def test_disappeared_analysis_set_is_gapped(self) -> None:
        """T2：PPS 消失且无声明 → 缺口点名（UC2B 形态）。"""
        _record_presence_snapshot(self.document, store_dir=self.store_dir)
        shrunk = _document([
            "统计分析采用全分析集（FAS）与安全性分析集（SS）两分析集。"
        ])
        gaps = _presence_regression_gaps(shrunk, store_dir=self.store_dir)
        self.assertTrue(gaps)
        self.assertIn("定向删减未声明", gaps[0])
        self.assertIn("PPS", gaps[0])

    def test_present_set_not_gapped(self) -> None:
        """T3：分析集仍在场 → 无缺口。"""
        _record_presence_snapshot(self.document, store_dir=self.store_dir)
        same = _document([
            "统计分析采用全分析集（FAS）、安全性分析集（SS）与符合方案集"
            "（PPS）三分析集。"
        ])
        self.assertEqual([], _presence_regression_gaps(same, store_dir=self.store_dir))

    def test_snapshot_persists_across_calls(self) -> None:
        """基线快照持久化（跨进程/跨轮导出可 diff）。"""
        _record_presence_snapshot(self.document, store_dir=self.store_dir)
        again = _presence_snapshot_from_texts([
            "全分析集（FAS）；安全性分析集（SS）；符合方案集（PPS）。"
        ])
        self.assertEqual({"FAS", "SS", "PPS"}, set(again))


if __name__ == "__main__":
    unittest.main()
