from __future__ import annotations

import unittest

from services.api.app.monitoring_source_fragment import (
    resolve_listing_fragment,
    resolve_protocol_fragment,
)
from services.api.app.protocol_text_extractor import (
    ProtocolParagraph,
    ProtocolTable,
    ProtocolTableCell,
    ProtocolTextDocument,
)


class MonitoringSourceFragmentTests(unittest.TestCase):
    def protocol(self) -> ProtocolTextDocument:
        return ProtocolTextDocument(
            filename="protocol.docx",
            title="Protocol",
            paragraphs=[
                ProtocolParagraph(0, "前文", "docx:paragraph:0"),
                ProtocolParagraph(1, "目标方案原文", "docx:paragraph:1"),
                ProtocolParagraph(2, "后文", "docx:paragraph:2"),
                ProtocolParagraph(
                    3,
                    "单元格内的精确方案条款",
                    "docx:table:0:row:0:cell:1:paragraph:0",
                    is_in_table=True,
                ),
            ],
            tables=[
                ProtocolTable(
                    table_index=0,
                    source_locator="docx:table:0",
                    rows=[
                        [
                            ProtocolTableCell(0, 0, "触发条件", "docx:table:0:row:0:cell:0"),
                            ProtocolTableCell(0, 1, "处理措施", "docx:table:0:row:0:cell:1"),
                        ]
                    ],
                )
            ],
            spans=[],
        )

    def test_protocol_paragraph_and_table_keep_zero_based_locator_and_display_one_based(self) -> None:
        paragraph = resolve_protocol_fragment(self.protocol(), "docx:paragraph:1")
        table = resolve_protocol_fragment(self.protocol(), "docx:table:0:row:0")

        self.assertEqual(0, paragraph["index_base"])
        self.assertEqual("方案段落 2", paragraph["display_locator"])
        self.assertEqual("目标方案原文", paragraph["text"])
        self.assertEqual("方案原文：目标方案原文", paragraph["primary_summary"])
        self.assertEqual(["前文"], paragraph["context_before"])
        self.assertEqual(["后文"], paragraph["context_after"])
        self.assertEqual("方案表 1，第 1 行", table["display_locator"])
        self.assertEqual("触发条件；处理措施", table["text"])

        table_paragraph = resolve_protocol_fragment(
            self.protocol(),
            "docx:table:0:row:0:cell:1:paragraph:0",
        )
        self.assertEqual("table_cell_paragraph", table_paragraph["locator_kind"])
        self.assertEqual(
            "方案表 1，第 1 行，第 2 列，第 1 段",
            table_paragraph["display_locator"],
        )
        self.assertEqual("单元格内的精确方案条款", table_paragraph["text"])

    def test_listing_locator_is_one_based_and_requires_current_public_source_label(self) -> None:
        sheets = {"AE": [{"USUBJID": "S001", "AETERM": "头痛"}]}

        fragment = resolve_listing_fragment(
            "PUBLIC-LISTING",
            sheets,
            "listing:PUBLIC-LISTING:sheet:AE:row:1",
        )

        self.assertEqual(1, fragment["index_base"])
        self.assertEqual("AE · 第 1 条解析数据记录", fragment["display_locator"])
        self.assertEqual(
            [{"field": "USUBJID", "value": "S001"}, {"field": "AETERM", "value": "头痛"}],
            fragment["fields"],
        )
        self.assertEqual("头痛", fragment["primary_summary"])
        with self.assertRaises(KeyError):
            resolve_listing_fragment(
                "CURRENT-LISTING",
                sheets,
                "listing:OLD-LISTING:sheet:AE:row:1",
            )
        with self.assertRaises(KeyError):
            resolve_listing_fragment(
                "PUBLIC-LISTING",
                sheets,
                "listing:PUBLIC-LISTING:sheet:AE:row:0",
            )

    def test_listing_summary_prioritizes_medical_fact_over_locator(self) -> None:
        sheets = {
            "LB": [
                {
                    "USUBJID": "S01017",
                    "VISTOID": "D113",
                    "VISIT": "开放治疗期-16W（D113±7天）",
                    "LBDAT": "2024-12-27",
                    "LBTEST": "丙氨酸氨基转移酶（ALT）",
                    "LBORRES": "128.00",
                    "LBORRESU": "U/L",
                    "LBORNRLO": "0.0",
                    "LBORNRHI": "41.0",
                    "LBCLSIGN": "异常有临床意义",
                }
            ]
        }

        fragment = resolve_listing_fragment(
            "PUBLIC-LISTING",
            sheets,
            "listing:PUBLIC-LISTING:sheet:LB:row:1",
        )

        self.assertEqual(
            "2024-12-27 D113 丙氨酸氨基转移酶（ALT） "
            "128.00U/L ref(0.0, 41.0) ↑ 异常有临床意义",
            fragment["primary_summary"],
        )

    def test_investigational_product_and_cm_summaries_keep_domain_boundary(self) -> None:
        sheets = {
            "EX": [
                {
                    "DOMAIN": "EX2",
                    "__STUDYEVENTOID": "V11",
                    "EX2STDAT": "2025-12-03",
                    "EX2ENDAT": "2025-12-12",
                    "EX2DOSE": "4片",
                    "EX2FRQ": "BID",
                    "EX2DESC": "2025/12/10未服用。",
                }
            ],
            "CM": [
                {
                    "DOMAIN": "CM",
                    "CMSTDAT": "2025-09-02",
                    "CMTRT": "氯雷他定",
                    "CMDOSE": "10",
                    "CMDOSU": "mg",
                    "CMFREQ": "QD",
                    "CMINDC": "过敏性鼻炎",
                }
            ],
        }

        ip_fragment = resolve_listing_fragment(
            "PUBLIC-LISTING",
            sheets,
            "listing:PUBLIC-LISTING:sheet:EX:row:1",
        )
        cm_fragment = resolve_listing_fragment(
            "PUBLIC-LISTING",
            sheets,
            "listing:PUBLIC-LISTING:sheet:CM:row:1",
        )

        self.assertIn("试验药物 4片 BID", ip_fragment["primary_summary"])
        self.assertIn("用药记录：2025/12/10未服用。", ip_fragment["primary_summary"])
        self.assertIn("非试验用合并用药 氯雷他定 10mg QD", cm_fragment["primary_summary"])


if __name__ == "__main__":
    unittest.main()
