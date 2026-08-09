from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from services.api.app.listing_file_parser import parse_listing_file
from services.api.app.monitoring_source_classifier import classify_monitoring_listing


MY009_COMPARISON = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/S1安全性评价-202604/"
    "MY009-UC-2-01-MM Listing_20260410_Comparison.xlsx"
)
RUX_PROCESSED = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/准备阶段/"
    "RUX-03-002_列表_数据集_Excel_20250612_处理后.xlsx"
)
RUX_RAW_DIMENSION_DEFECT = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/"
    "RUX-03-002-自查文件包-20260107/1-RUX-03-002_列表_数据集_压缩包_20250612/"
    "RUX-03-002_列表_数据集_Excel_20250612.xlsx"
)


class MonitoringSourceClassifierTests(unittest.TestCase):
    def test_clean_listing_is_candidate_not_automatically_proven_full_snapshot(self):
        result = classify_monitoring_listing(
            "EDC_export_20260729.xlsx",
            [SimpleNamespace(sheet_name="AE", rows=[{"SUBJID": "S01"}], parser_warnings=[])],
        )

        self.assertEqual("raw_full_snapshot_candidate", result.source_class)
        self.assertTrue(result.baseline_eligible_after_confirmation)

    def test_manual_comparison_status_is_not_confused_with_native_uppercase_status(self):
        native = classify_monitoring_listing(
            "EDC_export.xlsx",
            [SimpleNamespace(sheet_name="AE", rows=[{"STATUS": "Active"}], parser_warnings=[])],
        )
        comparison = classify_monitoring_listing(
            "EDC_export.xlsx",
            [
                SimpleNamespace(
                    sheet_name="AE",
                    rows=[{"状态": "Changed", "STATUS": "Active"}],
                    parser_warnings=[],
                )
            ],
        )

        self.assertEqual("raw_full_snapshot_candidate", native.source_class)
        self.assertEqual("comparison_workbook", comparison.source_class)
        self.assertFalse(comparison.baseline_eligible_after_confirmation)

    def test_empty_parse_fails_technical_gate(self):
        result = classify_monitoring_listing("empty.xlsx", [])

        self.assertEqual("failed", result.technical_status)
        self.assertEqual("unknown_blocked", result.source_class)

    def test_derived_scale_attachment_name_is_processed_even_without_comparison_sheet(self):
        result = classify_monitoring_listing(
            "附件1：RUX-03-002_data listing_20250416_附量表间评分变化比较.xlsx",
            [SimpleNamespace(sheet_name="AE", rows=[{"SUBJID": "S01"}], parser_warnings=[])],
        )

        self.assertEqual("processed_full_snapshot", result.source_class)
        self.assertFalse(result.baseline_eligible_after_confirmation)

    def test_physical_comparison_sheet_outranks_derived_attachment_name(self):
        result = classify_monitoring_listing(
            "附件1：RUX-03-002_data listing_20250416_附量表间评分变化比较.xlsx",
            [
                SimpleNamespace(
                    sheet_name="量表间评分变化比较",
                    rows=[{"SUBJID": "S01"}],
                    parser_warnings=[],
                )
            ],
        )

        self.assertEqual("mixed_monitoring_workbook", result.source_class)
        self.assertFalse(result.baseline_eligible_after_confirmation)

    @unittest.skipUnless(MY009_COMPARISON.exists(), "MY009 comparison file unavailable")
    def test_real_my009_comparison_is_non_baseline(self):
        sheets = parse_listing_file(
            MY009_COMPARISON.name,
            MY009_COMPARISON.read_bytes(),
        )
        result = classify_monitoring_listing(MY009_COMPARISON.name, sheets)

        self.assertEqual("comparison_workbook", result.source_class)
        self.assertFalse(result.baseline_eligible_after_confirmation)

    @unittest.skipUnless(RUX_PROCESSED.exists(), "RUX processed file unavailable")
    def test_real_rux_processed_file_requires_lineage(self):
        sheets = parse_listing_file(RUX_PROCESSED.name, RUX_PROCESSED.read_bytes())
        result = classify_monitoring_listing(RUX_PROCESSED.name, sheets)

        self.assertEqual("processed_full_snapshot", result.source_class)
        self.assertFalse(result.baseline_eligible_after_confirmation)

    @unittest.skipUnless(
        RUX_RAW_DIMENSION_DEFECT.exists(),
        "RUX raw dimension-defective file unavailable",
    )
    def test_real_rux_dimension_defect_is_visible_not_silently_raw(self):
        sheets = parse_listing_file(
            RUX_RAW_DIMENSION_DEFECT.name,
            RUX_RAW_DIMENSION_DEFECT.read_bytes(),
        )
        result = classify_monitoring_listing(RUX_RAW_DIMENSION_DEFECT.name, sheets)

        self.assertEqual("raw_snapshot_with_format_defect", result.source_class)
        self.assertFalse(result.baseline_eligible_after_confirmation)
