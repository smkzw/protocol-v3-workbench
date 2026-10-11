"""新纪元第4轮末修订（P0-3/NEW-33）：重导出补门——存量45/组旁路件直接
导出必须被全文复核计缺口（三连导出零修订的旁路实证封堵）。"""
from __future__ import annotations

import unittest


class ReexportGateTests(unittest.TestCase):
    def test_legacy_stale_declaration_in_non_stats_section_is_gapped(self) -> None:
        from services.api.app.main import _export_placeholder_report
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )

        document = ProtocolDocument(
            document_id="doc_reexport",
            project_id="proj_reexport",
            protocol_id="CMS-RE-33",
            version="1.0",
            sections=[
                ProtocolSection(
                    section_id="sec_5",
                    document_id="doc_reexport",
                    heading="研究设计",
                    section_number="5",
                    content_blocks=[
                        {
                            "block_id": "b5",
                            "block_type": "paragraph",
                            "text": (
                                "样本量每组45例；基于预期应答率20%对45%，"
                                "双侧α=0.05、把握度90%估算。"
                            ),
                        }
                    ],
                )
            ],
        )
        report = _export_placeholder_report(document)
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("重导出补门", reasons)
        self.assertIn("不一致", reasons)
        self.assertGreaterEqual(int(report.get("gap_count") or 0), 1)


if __name__ == "__main__":
    unittest.main()
