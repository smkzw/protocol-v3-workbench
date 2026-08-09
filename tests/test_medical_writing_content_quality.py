from __future__ import annotations

import unittest

from packages.contracts.workbench_contracts import ApprovalState, ProtocolDocument, ProtocolSection
from services.api.app.medical_writing_content_quality import (
    MedicalWritingContentQualityDetector,
)
from services.api.app.medical_writing_document import MedicalWritingDocumentService
from services.api.app.medical_writing_manifest import (
    D001_PROTOCOL_DOCX,
    MY008_PNH_3_01_PROTOCOL_DOCX,
    RUX_PROTOCOL_DOCX,
)


def make_document(text: str) -> ProtocolDocument:
    return ProtocolDocument(
        document_id="mwdoc_content_quality_test",
        project_id="proj_content_quality_test",
        protocol_id="CONTENT-QUALITY-TEST",
        version="V1.0",
        sections=[
            ProtocolSection(
                section_id="mwsec_content_quality_test",
                document_id="mwdoc_content_quality_test",
                heading="研究设计",
                approval_state=ApprovalState.IN_MEDICAL_REVIEW,
                content_blocks=[
                    {
                        "block_id": "block_content_quality_test",
                        "block_type": "paragraph",
                        "text": text,
                        "source_kind": "original_protocol_docx",
                        "source_locator": "docx:paragraph:12",
                    }
                ],
            )
        ],
    )


class MedicalWritingContentQualityDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = MedicalWritingContentQualityDetector()

    def test_mixed_closing_delimiter_is_detected_without_flagging_valid_comparisons(self):
        document = make_document(
            "血红蛋白< 10 g/dL，eGFR <30 mL/min/1.73m2，年龄12≤年龄<18周岁；"
            "对于具有生育能力的女性受试者：<0}"
        )

        findings = self.detector.scan_document(document)

        self.assertEqual(1, len(findings))
        finding = findings[0]
        self.assertEqual("malformed_mixed_delimiter", finding.rule_code)
        self.assertEqual("<0}", finding.matched_text)
        self.assertEqual(document.sections[0].content_blocks[0]["text"], finding.source_text)
        self.assertEqual("docx:paragraph:12", finding.source_locator)
        self.assertTrue(finding.approval_blocking)
        self.assertEqual("open", finding.disposition_status)
        self.assertEqual(64, len(finding.content_fingerprint))

    def test_location_identity_is_stable_but_content_fingerprint_changes(self):
        original = self.detector.scan_document(make_document("避孕要求：<0}"))[0]
        changed = self.detector.scan_document(make_document("避孕要求需确认：<0}"))[0]

        self.assertEqual(original.finding_id, changed.finding_id)
        self.assertNotEqual(original.content_fingerprint, changed.content_fingerprint)

    def test_table_cell_returns_exact_text_and_secondary_cell_locator(self):
        document = make_document("合法正文。")
        document.sections[0].content_blocks = [
            {
                "block_id": "table_block_10",
                "block_type": "table",
                "table_id": "source_table_10",
                "source_kind": "original_protocol_docx",
                "source_locator": "docx:table:10",
                "rows": [
                    [
                        {
                            "cell_id": "source_cell_10_2_0",
                            "text": "对于研究中具有生育能力的女性受试者：<0}",
                            "source_locator": "docx:table:10:row:2:cell:0",
                            "row_index": 2,
                            "cell_index": 0,
                        }
                    ]
                ],
            }
        ]

        findings = self.detector.scan_document(document)

        self.assertEqual(1, len(findings))
        finding = findings[0]
        self.assertEqual("table_cell", finding.location_kind)
        self.assertEqual("对于研究中具有生育能力的女性受试者：<0}", finding.source_text)
        self.assertEqual("docx:table:10:row:2:cell:0", finding.source_locator)
        self.assertEqual("source_table_10", finding.table_id)
        self.assertEqual("source_cell_10_2_0", finding.cell_id)
        self.assertEqual(2, finding.row_index)
        self.assertEqual(0, finding.cell_index)

    def test_internal_transport_vocabulary_is_blocking_and_located(self):
        document = make_document(
            "隔离fixture中的ProtocolAssemblyPlan（SECTION_ID=demo）不应进入方案正文。"
        )

        findings = self.detector.scan_document(document)

        self.assertEqual(3, len(findings))
        self.assertEqual(
            {
                "internal_transport_vocabulary"},
            {finding.rule_code for finding in findings},
        )
        self.assertTrue(all(finding.approval_blocking for finding in findings))
        self.assertEqual(
            {"隔离fixture", "ProtocolAssemblyPlan", "SECTION_ID="},
            {finding.matched_text for finding in findings},
        )
        self.assertTrue(
            all(finding.source_locator == "docx:paragraph:12" for finding in findings)
        )

    def test_unresolved_draft_markers_are_blocking_but_common_visit_terms_are_not(self):
        document = make_document(
            "待医学经理结合证据确认主要终点；尚无直接证据来源支持当前时间窗。"
            "受试者待随访期间记录安全性信息。"
        )

        findings = self.detector.scan_document(document)

        self.assertEqual(2, len(findings))
        self.assertEqual(
            {"unresolved_draft_marker"},
            {finding.rule_code for finding in findings},
        )
        self.assertEqual(
            {"待医学经理结合证据确认", "尚无直接证据来源支持"},
            {finding.matched_text for finding in findings},
        )
        self.assertTrue(all(finding.approval_blocking for finding in findings))

    def test_future_formal_text_and_missing_fact_language_is_blocking(self):
        document = make_document(
            "筛选期时长将在本方案正式文本的相应章节中具体规定；"
            "主要终点的具体数值未提供，参考文献尚未列入正式文献条目。"
        )

        findings = self.detector.scan_document(document)

        self.assertEqual(3, len(findings))
        self.assertTrue(
            all(finding.rule_code == "unresolved_draft_marker" for finding in findings)
        )
        self.assertEqual(
            {
                "将在本方案正式文本的相应章节中具体规定",
                "未提供",
                "尚未列入正式文献条目",
            },
            {finding.matched_text for finding in findings},
        )


@unittest.skipUnless(
    RUX_PROTOCOL_DOCX.exists()
    and D001_PROTOCOL_DOCX.exists()
    and MY008_PNH_3_01_PROTOCOL_DOCX.exists(),
    "real protocol DOCX fixtures are unavailable",
)
class MedicalWritingContentQualityRealProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document_service = MedicalWritingDocumentService()
        cls.detector = MedicalWritingContentQualityDetector()

    def test_rux_positive_and_d001_pnh_cross_project_controls(self):
        findings_by_project = {
            project_id: self.detector.scan_document(
                self.document_service.document_for_revision(project_id)
            )
            for project_id in (
                "proj_rux_03_002",
                "proj_d001",
                "proj_my008_pnh_3_01",
            )
        }

        self.assertEqual(1, len(findings_by_project["proj_rux_03_002"]))
        rux_finding = findings_by_project["proj_rux_03_002"][0]
        self.assertEqual("对于研究中具有生育能力的女性受试者：<0}", rux_finding.source_text)
        self.assertEqual("docx:table:10:row:2:cell:0", rux_finding.source_locator)
        self.assertEqual("malformed_mixed_delimiter", rux_finding.rule_code)
        self.assertEqual([], findings_by_project["proj_d001"])
        self.assertEqual([], findings_by_project["proj_my008_pnh_3_01"])


if __name__ == "__main__":
    unittest.main()
