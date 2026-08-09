from __future__ import annotations

import unittest
from types import SimpleNamespace
from pathlib import Path

from services.api.app.monitoring_batch_diff import (
    MONITORING_BATCH_DIFF_ALGORITHM_VERSION,
    diff_monitoring_batches,
    diff_monitoring_rows,
    monitoring_diff_output_sha256,
    normalize_listing_sheets,
)
from services.api.app.listing_file_parser import parse_listing_file


MY009_20260408 = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/S1安全性评价-202604/"
    "MY009-UC-2-01-MM Listing_20260408(已自动还原).xlsx"
)
MY009_20260410 = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/S1安全性评价-202604/"
    "MY009-UC-2-01-MM Listing_20260410_Comparison.xlsx"
)
RUX_20250612 = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/准备阶段/"
    "RUX-03-002_列表_数据集_Excel_20250612_处理后.xlsx"
)
RUX_20250416 = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/"
    "2-RUX-03-002-现场核查项目层面文件目录-20260424/"
    "21.医学监查计划/21.2-医学监查报告/9-第九次/"
    "附件1：RUX-03-002_data listing_20250416_附量表间评分变化比较.xlsx"
)
MGK10_20260120 = Path(
    "/Users/smkzw/Documents/康哲项目资料/MG-K10/SAR/13. CFDI核查/自查/评分SDV/"
    "【锁库后Data Listing】MG-K10-SAR-001_FormExcelAllVersion_202601201126.xlsx"
)
MY008_2_03_20250417 = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/交接资料/"
    "MY008 长期安全性研究/医学监查/"
    "回复_ MY008211A-PNH-2-03项目_34例受试者_数据列表_20250417的全部附件20250421/"
    "MY008211A-PNH-2-03_数据列表_20250417/"
    "MY008211A-PNH-2-03_数据列表_20250417.xlsx"
)
MY008_2_03_20251202 = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/2-03/阶段性数据/"
    "【251202cut】MY008211A-PNH-2-03_冻结后数据列表_20251202_23_22.xlsx"
)


class MonitoringBatchDiffTests(unittest.TestCase):
    def test_initial_batch_uses_persisted_schema_without_rows(self) -> None:
        result = diff_monitoring_batches(
            [],
            [],
            expected_domains={"AE"},
            full_snapshot_proven=True,
            current_schema_fields=[
                ("AE", "USUBJID", "AE"),
                ("AE", "AETERM", "AE"),
            ],
        )

        self.assertEqual([], result.row_diff.missing_current_domains)
        self.assertEqual(
            [
                {
                    "domain": "AE",
                    "added_fields": ["AETERM", "USUBJID"],
                    "removed_fields": [],
                }
            ],
            [
                {
                    "domain": item.domain,
                    "added_fields": item.added_fields,
                    "removed_fields": item.removed_fields,
                }
                for item in result.schema_diffs
            ],
        )
        self.assertEqual(
            MONITORING_BATCH_DIFF_ALGORITHM_VERSION,
            result.algorithm_version,
        )
        self.assertEqual(64, len(result.output_sha256))
        self.assertEqual(result.output_sha256, monitoring_diff_output_sha256(result))

    def test_unchanged_header_only_schema_has_no_schema_drift(self) -> None:
        schema = [
            {"domain": "AE", "field": "USUBJID", "source_sheet": "AE"},
            {"domain": "AE", "field": "AETERM", "source_sheet": "AE"},
        ]

        result = diff_monitoring_batches(
            [],
            [],
            expected_domains={"AE"},
            previous_schema_fields=schema,
            current_schema_fields=list(reversed(schema)),
        )

        self.assertEqual([], result.schema_diffs)
        self.assertEqual([], result.row_diff.missing_current_domains)

    def test_zero_row_header_only_field_rename_is_not_lost(self) -> None:
        result = diff_monitoring_batches(
            [],
            [],
            previous_schema_fields=[
                ("LB", "LBORRES", "LB"),
                ("LB", "LBORRESU", "LB"),
            ],
            current_schema_fields=[
                ("LB", "LBORRES", "LB"),
                ("LB", "LBUNIT", "LB"),
            ],
        )

        self.assertEqual(1, len(result.schema_diffs))
        self.assertEqual("LB", result.schema_diffs[0].domain)
        self.assertEqual(["LBUNIT"], result.schema_diffs[0].added_fields)
        self.assertEqual(["LBORRESU"], result.schema_diffs[0].removed_fields)

    def test_persisted_schema_detects_all_empty_column_across_multiple_domains(self) -> None:
        shared_rows = [
            {
                "domain": "AE",
                "business_key": "AE|S01|1",
                "data": {"USUBJID": "S01", "AETERM": "头痛"},
            },
            {
                "domain": "LB",
                "business_key": "LB|S01|ALT|1",
                "data": {"USUBJID": "S01", "LBTEST": "ALT"},
            },
        ]
        previous_schema = [
            ("AE", "USUBJID", "AE"),
            ("AE", "AETERM", "AE"),
            ("LB", "USUBJID", "LB"),
            ("LB", "LBTEST", "LB"),
        ]
        current_schema = [
            *previous_schema,
            ("LB", "LBCOMM", "LB"),
        ]

        result = diff_monitoring_batches(
            shared_rows,
            shared_rows,
            previous_schema_fields=previous_schema,
            current_schema_fields=current_schema,
        )

        self.assertEqual(["AE|S01|1", "LB|S01|ALT|1"], result.row_diff.persisting_keys)
        self.assertEqual(1, len(result.schema_diffs))
        self.assertEqual("LB", result.schema_diffs[0].domain)
        self.assertEqual(["LBCOMM"], result.schema_diffs[0].added_fields)

    def test_row_and_schema_order_changes_do_not_create_drift_or_change_hash(self) -> None:
        rows = [
            {
                "domain": "AE",
                "business_key": "AE|S01|1",
                "data": {"AETERM": "头痛", "USUBJID": "S01"},
            },
            {
                "domain": "CM",
                "business_key": "CM|S01|1",
                "data": {"CMTRT": "氯雷他定", "USUBJID": "S01"},
            },
        ]
        schema = [
            ("AE", "USUBJID", "AE"),
            ("AE", "AETERM", "AE"),
            ("CM", "USUBJID", "CM"),
            ("CM", "CMTRT", "CM"),
        ]

        forward = diff_monitoring_batches(
            rows,
            rows,
            previous_schema_fields=schema,
            current_schema_fields=schema,
        )
        reversed_order = diff_monitoring_batches(
            list(reversed(rows)),
            list(reversed(rows)),
            previous_schema_fields=list(reversed(schema)),
            current_schema_fields=list(reversed(schema)),
        )

        self.assertEqual([], forward.schema_diffs)
        self.assertEqual([], reversed_order.schema_diffs)
        self.assertEqual(forward, reversed_order)

    def test_diff_classifies_new_changed_persisting_and_removed_rows_by_business_key(self) -> None:
        previous = [
            {"domain": "AE", "business_key": "AE|S01|1", "data": {"term": "头痛", "grade": 1}},
            {"domain": "LB", "business_key": "LB|S01|ALT|W1", "data": {"value": 42, "unit": "U/L"}},
            {"domain": "CM", "business_key": "CM|S01|1", "data": {"drug": "氯雷他定"}},
        ]
        current = [
            {"domain": "AE", "business_key": "AE|S01|1", "data": {"term": "头痛", "grade": 1}},
            {"domain": "LB", "business_key": "LB|S01|ALT|W1", "data": {"value": 48, "unit": "U/L"}},
            {"domain": "PD", "business_key": "PD|S01|1", "data": {"type": "访视窗"}},
        ]

        result = diff_monitoring_rows(previous, current)

        self.assertEqual(["PD|S01|1"], result.new_keys)
        self.assertEqual(["LB|S01|ALT|W1"], result.changed_keys)
        self.assertEqual(["AE|S01|1"], result.persisting_keys)
        self.assertEqual(["CM|S01|1"], result.removed_keys)

    def test_mapping_revision_change_requires_shared_rows_to_be_rereviewed(self) -> None:
        rows = [
            {"domain": "AE", "business_key": "AE|S01|1", "data": {"term": "头痛"}},
            {"domain": "LB", "business_key": "LB|S01|ALT|W1", "data": {"value": 42}},
        ]

        result = diff_monitoring_rows(
            rows,
            rows,
            previous_mapping_revision="mapping-v1",
            current_mapping_revision="mapping-v2",
        )

        self.assertEqual(["AE|S01|1", "LB|S01|ALT|W1"], result.requires_rereview_keys)

    def test_mapping_revision_presence_change_requires_shared_rows_to_be_rereviewed(self) -> None:
        rows = [
            {"domain": "AE", "business_key": "AE|S01|1", "data": {"term": "头痛"}},
            {"domain": "LB", "business_key": "LB|S01|ALT|W1", "data": {"value": 42}},
        ]
        expected = ["AE|S01|1", "LB|S01|ALT|W1"]

        for previous_revision, current_revision in (("mapping-v1", ""), ("", "mapping-v2")):
            with self.subTest(previous_revision=previous_revision, current_revision=current_revision):
                result = diff_monitoring_rows(
                    rows,
                    rows,
                    previous_mapping_revision=previous_revision,
                    current_mapping_revision=current_revision,
                )
                self.assertEqual(expected, result.requires_rereview_keys)

        unchanged = diff_monitoring_rows(rows, rows)
        self.assertEqual([], unchanged.requires_rereview_keys)

    def test_missing_current_domain_blocks_removed_rows_from_being_treated_as_resolved(self) -> None:
        previous = [
            {"domain": "AE", "business_key": "AE|S01|1", "data": {"term": "头痛"}},
            {"domain": "CM", "business_key": "CM|S01|1", "data": {"drug": "氯雷他定"}},
        ]
        current = [
            {"domain": "AE", "business_key": "AE|S01|1", "data": {"term": "头痛"}},
        ]

        result = diff_monitoring_rows(previous, current, expected_domains={"AE", "CM"})

        self.assertEqual(["CM"], result.missing_current_domains)
        self.assertEqual(["CM|S01|1"], result.removed_keys)
        self.assertEqual(["CM|S01|1"], result.removal_resolution_blocked_keys)

    def test_detailed_diff_preserves_old_new_values_locators_and_medical_change_kinds(self) -> None:
        previous = [
            {
                "domain": "LB",
                "business_key": "LB|S01|ALT|W1",
                "source_locator": "LB!row:2",
                "data": {"LBORRES": 42, "LBORRESU": "U/L", "LBORNRHI": 40},
            }
        ]
        current = [
            {
                "domain": "LB",
                "business_key": "LB|S01|ALT|W1",
                "source_locator": "LB!row:7",
                "data": {"LBORRES": 48, "LBORRESU": "IU/L", "LBORNRHI": 45, "LBNRIND": "HIGH"},
            }
        ]

        result = diff_monitoring_batches(
            previous,
            current,
            expected_domains={"LB"},
            full_snapshot_proven=True,
        )

        changes = {change.field_name: change for change in result.field_changes}
        self.assertEqual(42, changes["LBORRES"].previous_value)
        self.assertEqual(48, changes["LBORRES"].current_value)
        self.assertEqual("value", changes["LBORRES"].change_kind)
        self.assertEqual("unit", changes["LBORRESU"].change_kind)
        self.assertEqual("reference_range", changes["LBORNRHI"].change_kind)
        self.assertEqual("LB!row:2", changes["LBORRES"].previous_locator)
        self.assertEqual("LB!row:7", changes["LBORRES"].current_locator)
        self.assertEqual(["LBNRIND"], result.schema_diffs[0].added_fields)

    def test_removed_rows_are_not_resolution_eligible_without_full_snapshot_proof(self) -> None:
        previous = [
            {"domain": "AE", "business_key": "AE|S01|1", "data": {"term": "头痛"}},
        ]

        blocked = diff_monitoring_batches(previous, [], expected_domains={"AE"})
        self.assertEqual(["AE|S01|1"], blocked.removal_blocked_keys)
        self.assertEqual([], blocked.removal_eligible_keys)

        eligible = diff_monitoring_batches(
            previous,
            [],
            expected_domains=set(),
            full_snapshot_proven=True,
        )
        self.assertEqual([], eligible.removal_blocked_keys)
        self.assertEqual(["AE|S01|1"], eligible.removal_eligible_keys)

    def test_listing_normalization_ignores_comparison_flag_and_blank_rows(self) -> None:
        sheets = [
            SimpleNamespace(
                sheet_name="AE",
                rows=[
                    {
                        "状态": "新增",
                        "__STUDYOID": "STUDY-1",
                        "__STUDYEVENTOID": "VISIT-1",
                        "__STUDYEVENTREPEATKEY": "",
                        "DOMAIN": "AE",
                        "USUBJID": "S01001",
                        "PAGE": "AE",
                        "FORM": "AE",
                        "LINE": "1",
                        "AETERM": "头痛",
                    },
                    {"状态": "", "DOMAIN": "", "USUBJID": ""},
                ],
            ),
            SimpleNamespace(sheet_name="报告总结", rows=[{"数据对比报告": "summary"}]),
        ]

        rows = normalize_listing_sheets(sheets)

        self.assertEqual(1, len(rows))
        self.assertEqual("AE", rows[0]["domain"])
        self.assertIn("S01001", rows[0]["business_key"])
        self.assertNotIn("状态", rows[0]["data"])
        self.assertEqual(
            "listing:sheet:AE:parsed_row:1",
            rows[0]["source_locator"]["locator"],
        )

    def test_listing_normalization_preserves_physical_source_row_number(self) -> None:
        sheets = [
            SimpleNamespace(
                sheet_name="LB",
                row_numbers=[7],
                rows=[
                    {
                        "DOMAIN": "LB",
                        "USUBJID": "S01001",
                        "LINE": "1",
                        "LBTEST": "ALT",
                    }
                ],
            )
        ]

        rows = normalize_listing_sheets(sheets)

        self.assertEqual(
            "listing:sheet:LB:row:7",
            rows[0]["source_locator"]["locator"],
        )

    def test_odm_business_key_survives_export_sheet_display_name_changes(self) -> None:
        shared_row = {
            "__STUDYOID": "STUDY-1",
            "__SUBJECTKEY": "S01001",
            "__STUDYEVENTOID": "AE",
            "__STUDYEVENTREPEATKEY": "1",
            "__FORMOID": "AE.AE.AE",
            "__FORMREPEATKEY": "1",
            "__ITEMGROUPOID": "AE",
            "DOMAIN": "AE",
            "USUBJID": "S01001",
            "PAGE": "不良事件",
            "FORM": "不良事件",
            "LINE": "1",
            "AETERM": "头痛",
        }

        previous = normalize_listing_sheets(
            [SimpleNamespace(sheet_name="不良事件", rows=[shared_row])]
        )
        current = normalize_listing_sheets(
            [SimpleNamespace(sheet_name="AE", rows=[shared_row])]
        )

        self.assertEqual(previous[0]["business_key"], current[0]["business_key"])
        result = diff_monitoring_rows(previous, current)
        self.assertEqual([], result.new_keys)
        self.assertEqual([], result.removed_keys)
        self.assertEqual([previous[0]["business_key"]], result.persisting_keys)

    def test_edc_business_key_uses_visit_fallback_only_when_visit_oid_is_missing(
        self,
    ) -> None:
        common = {
            "STUDYID": "STUDY-1",
            "SITEID": "01",
            "SUBJID": "01001",
            "VISTREP": "1",
            "FORMOID": "SV",
            "FORMREP": "",
            "RECREP": "1",
        }
        rows = normalize_listing_sheets(
            [
                SimpleNamespace(
                    sheet_name="SV",
                    rows=[
                        {**common, "VISTOID": "", "VISIT": "筛选期", "VISDAT": "2026-01-01"},
                        {**common, "VISTOID": "", "VISIT": "基线期", "VISDAT": "2026-01-08"},
                    ],
                )
            ]
        )

        self.assertEqual(2, len({row["business_key"] for row in rows}))
        self.assertTrue(all(row["business_key"].endswith(("筛选期", "基线期")) for row in rows))

        oid_rows = normalize_listing_sheets(
            [
                SimpleNamespace(
                    sheet_name="SV",
                    rows=[
                        {**common, "VISTOID": "V1", "VISIT": "筛选期"},
                        {**common, "VISTOID": "V1", "VISIT": "Screening"},
                    ],
                )
            ]
        )
        self.assertEqual(
            oid_rows[0]["source_locator"]["identity_base_key"],
            oid_rows[1]["source_locator"]["identity_base_key"],
        )
        self.assertNotEqual(
            oid_rows[0]["business_key"],
            oid_rows[1]["business_key"],
        )

    def test_edc_multirecord_collision_preserves_all_rows_without_row_number_identity(
        self,
    ) -> None:
        rows = [
            {
                "SITEID": "01",
                "SUBJID": "S01021",
                "FORMNM": "受试者页",
                "FORMREP": "0",
                "RECREP": "0",
                "SUBJSTA": "筛选中",
                "PAGELMDT": "2024-09-19 14:56:19",
            },
            {
                "SITEID": "01",
                "SUBJID": "S01021",
                "FORMNM": "受试者页",
                "FORMREP": "0",
                "RECREP": "0",
                "SUBJSTA": "完成试验",
                "PAGELMDT": "2024-08-30 17:35:42",
            },
        ]
        forward = normalize_listing_sheets(
            [
                SimpleNamespace(
                    sheet_name="SUBJ--受试者页",
                    row_numbers=[23, 24],
                    rows=rows,
                )
            ]
        )
        reversed_rows = normalize_listing_sheets(
            [
                SimpleNamespace(
                    sheet_name="SUBJ--受试者页",
                    row_numbers=[105, 104],
                    rows=list(reversed(rows)),
                )
            ]
        )

        self.assertEqual(2, len(forward))
        self.assertEqual(
            {row["business_key"] for row in forward},
            {row["business_key"] for row in reversed_rows},
        )
        self.assertEqual(2, len({row["business_key"] for row in forward}))
        self.assertTrue(
            all(
                row["source_locator"]["identity_resolution"]
                == "content_variant_multirecord"
                for row in forward
            )
        )
        self.assertTrue(
            all(
                ":row:" in row["source_locator"]["locator"]
                for row in forward
            )
        )

    def test_edc_identity_alias_reconciles_oid_schema_expansion_and_multirecord_removal(
        self,
    ) -> None:
        historical = normalize_listing_sheets(
            [
                SimpleNamespace(
                    sheet_name="SUBJ--受试者页",
                    rows=[
                        {
                            "SITEID": "01",
                            "SUBJID": "S01021",
                            "FORMNM": "受试者页",
                            "FORMREP": "0",
                            "RECREP": "0",
                            "SUBJSTA": "筛选中",
                            "PAGELMDT": "2024-09-19 14:56:19",
                        },
                        {
                            "SITEID": "01",
                            "SUBJID": "S01021",
                            "FORMNM": "受试者页",
                            "FORMREP": "0",
                            "RECREP": "0",
                            "SUBJSTA": "完成试验",
                            "PAGELMDT": "2024-08-30 17:35:42",
                        },
                    ],
                )
            ]
        )
        current = normalize_listing_sheets(
            [
                SimpleNamespace(
                    sheet_name="SUBJ--受试者页",
                    rows=[
                        {
                            "SITEID": "01",
                            "SUBJID": "S01021",
                            "FORMNM": "受试者页",
                            "FORMOID": "subj",
                            "FORMREP": "0",
                            "RECREP": "0",
                            "SUBJSTA": "完成试验",
                            "PAGELMDT": "2024-08-30 17:35:42",
                        }
                    ],
                )
            ]
        )

        result = diff_monitoring_batches(
            historical,
            current,
            expected_domains={"SUBJ"},
            full_snapshot_proven=True,
        )

        self.assertEqual([], result.row_diff.new_keys)
        self.assertEqual([], result.row_diff.changed_keys)
        self.assertEqual(1, len(result.row_diff.persisting_keys))
        self.assertEqual(1, len(result.row_diff.removed_keys))
        self.assertEqual(result.row_diff.removed_keys, result.removal_eligible_keys)
        self.assertEqual([], result.removal_blocked_keys)
        self.assertEqual(
            {"identity_alias_common_payload": 1},
            result.identity_match_counts,
        )
        self.assertEqual(1, len(result.identity_match_samples))
        self.assertEqual(
            "identity_alias_common_payload",
            result.identity_match_samples[0].match_basis,
        )
        self.assertEqual(["FORMOID"], result.schema_diffs[0].added_fields)

    def test_ambiguous_multirecord_alias_fails_closed_for_removal_resolution(
        self,
    ) -> None:
        alias = "edc-display-v1|AE|AE||01|S01|W1|1|不良事件|0|0"

        def row(key: str, term: str) -> dict:
            return {
                "domain": "AE",
                "business_key": key,
                "data": {"AETERM": term},
                "source_locator": {
                    "locator": f"listing:sheet:AE:row:{key[-1]}",
                    "identity_aliases": [alias],
                },
            }

        result = diff_monitoring_batches(
            [row("old-1", "头痛"), row("old-2", "恶心")],
            [row("new-1", "皮疹"), row("new-2", "瘙痒")],
            expected_domains={"AE"},
            full_snapshot_proven=True,
        )

        self.assertEqual(["new-1", "new-2"], result.row_diff.new_keys)
        self.assertEqual(["old-1", "old-2"], result.row_diff.removed_keys)
        self.assertEqual(
            ["old-1", "old-2"],
            result.row_diff.removal_resolution_blocked_keys,
        )
        self.assertEqual([], result.removal_eligible_keys)
        self.assertEqual(["old-1", "old-2"], result.removal_blocked_keys)

    @unittest.skipUnless(RUX_20250612.exists(), "RUX real listing unavailable")
    def test_real_rux_listing_normalizes_with_unique_cross_edc_business_keys(self) -> None:
        rows = normalize_listing_sheets(
            parse_listing_file(RUX_20250612.name, RUX_20250612.read_bytes())
        )

        self.assertGreater(len(rows), 100_000)
        self.assertEqual(len(rows), len({row["business_key"] for row in rows}))
        self.assertTrue(
            all(":row:" in row["source_locator"]["locator"] for row in rows)
        )

    @unittest.skipUnless(
        RUX_20250416.exists() and RUX_20250612.exists(),
        "RUX real historical/current listings unavailable",
    )
    def test_real_rux_legacy_schema_preserves_rows_and_reconciles_identity(self) -> None:
        previous = normalize_listing_sheets(
            parse_listing_file(RUX_20250416.name, RUX_20250416.read_bytes())
        )
        current = normalize_listing_sheets(
            parse_listing_file(RUX_20250612.name, RUX_20250612.read_bytes())
        )

        self.assertEqual(179565, len(previous))
        self.assertEqual(len(previous), len({row["business_key"] for row in previous}))
        result = diff_monitoring_batches(
            previous,
            current,
            expected_domains={row["domain"] for row in previous},
            full_snapshot_proven=True,
        )

        self.assertGreater(sum(result.identity_match_counts.values()), 170000)
        self.assertLessEqual(len(result.identity_match_samples), 50)
        self.assertLess(len(result.row_diff.new_keys), 1000)
        self.assertLess(len(result.row_diff.removed_keys), 500)
        self.assertEqual([], result.row_diff.missing_current_domains)

    @unittest.skipUnless(MGK10_20260120.exists(), "MG-K10 real listing unavailable")
    def test_real_mgk10_listing_uses_unique_visit_fallback_business_keys(self) -> None:
        rows = normalize_listing_sheets(
            parse_listing_file(MGK10_20260120.name, MGK10_20260120.read_bytes())
        )

        self.assertEqual(148727, len(rows))
        self.assertEqual(len(rows), len({row["business_key"] for row in rows}))

    @unittest.skipUnless(
        MY009_20260408.exists() and MY009_20260410.exists(),
        "MY009 real incremental listings unavailable",
    )
    def test_real_my009_20260408_to_20260410_diff_is_computed_from_rows(self) -> None:
        previous = normalize_listing_sheets(
            parse_listing_file(MY009_20260408.name, MY009_20260408.read_bytes())
        )
        current = normalize_listing_sheets(
            parse_listing_file(MY009_20260410.name, MY009_20260410.read_bytes())
        )

        result = diff_monitoring_rows(
            previous,
            current,
            expected_domains={row["domain"] for row in previous},
        )

        self.assertEqual(4023, len(previous))
        self.assertEqual(4287, len(current))
        self.assertEqual(264, len(result.new_keys))
        self.assertEqual(988, len(result.changed_keys))
        self.assertEqual(3035, len(result.persisting_keys))
        self.assertEqual([], result.removed_keys)
        self.assertEqual([], result.missing_current_domains)

    @unittest.skipUnless(
        MY008_2_03_20250417.exists() and MY008_2_03_20251202.exists(),
        "MY008 PNH 2-03 real full listing snapshots unavailable",
    )
    def test_real_my008_2_03_full_snapshots_support_cross_export_odm_diff(self) -> None:
        previous = normalize_listing_sheets(
            parse_listing_file(
                MY008_2_03_20250417.name,
                MY008_2_03_20250417.read_bytes(),
            )
        )
        current = normalize_listing_sheets(
            parse_listing_file(
                MY008_2_03_20251202.name,
                MY008_2_03_20251202.read_bytes(),
            )
        )

        self.assertEqual(8699, len(previous))
        self.assertEqual(33815, len(current))
        self.assertEqual(len(previous), len({row["business_key"] for row in previous}))
        self.assertEqual(len(current), len({row["business_key"] for row in current}))

        result = diff_monitoring_batches(
            previous,
            current,
            previous_mapping_revision="odm-v1",
            current_mapping_revision="odm-v1",
            expected_domains={row["domain"] for row in previous},
            full_snapshot_proven=True,
        )

        self.assertEqual(25156, len(result.row_diff.new_keys))
        self.assertEqual(1258, len(result.row_diff.changed_keys))
        self.assertEqual(7401, len(result.row_diff.persisting_keys))
        self.assertEqual(40, len(result.row_diff.removed_keys))
        self.assertEqual([], result.row_diff.missing_current_domains)
        self.assertEqual(40, len(result.removal_eligible_keys))
        self.assertEqual([], result.removal_blocked_keys)


if __name__ == "__main__":
    unittest.main()
