from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.api.app.monitoring_source_revision import (
    public_monitoring_source_revision,
    read_monitoring_source,
)
from services.api.app.monitoring_project_registry import BoundMonitoringProjectAdapter
from services.api.app.my009_monitoring_service import My009MonitoringService
from services.api.app.rux_monitoring_service import RuxMonitoringService, SUBJ_SHEET


RUX_LISTING_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/准备阶段/"
    "RUX-03-002_列表_数据集_Excel_20250612_处理后.xlsx"
)
RUX_PROTOCOL_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/RUX-03-002-自查文件包-20260107/"
    "10-临床试验重要文件/1-临床试验方案/V1.3版-2024.8.14/"
    "磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx"
)
MY009_LISTING_PATH = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/S1安全性评价-202604/"
    "MY009-UC-2-01-MM Listing_20260408(已自动还原).xlsx"
)
MY009_PROTOCOL_PATH = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/方案及配套资料/3.0/"
    "MY009-UC-Ⅱa期-临床研究方案-V3.0 20250926-clean (1).docx"
)
PUBLIC_REVISION = re.compile(r"^monsrcv_[0-9a-f]{24}$")


class MonitoringSourceRevisionUnitTests(unittest.TestCase):
    def test_public_revision_is_content_derived_path_free_and_not_a_raw_hash(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first_listing = Path(first_dir) / "private-listing-name.xlsx"
            first_protocol = Path(first_dir) / "private-protocol-name.docx"
            second_listing = Path(second_dir) / "renamed.xlsx"
            second_protocol = Path(second_dir) / "renamed.docx"
            for path, content in (
                (first_listing, b"synthetic-listing-v1"),
                (second_listing, b"synthetic-listing-v1"),
                (first_protocol, b"synthetic-protocol-v1"),
                (second_protocol, b"synthetic-protocol-v1"),
            ):
                path.write_bytes(content)

            first = public_monitoring_source_revision(
                read_monitoring_source(first_listing),
                read_monitoring_source(first_protocol),
            )
            second = public_monitoring_source_revision(
                read_monitoring_source(second_listing),
                read_monitoring_source(second_protocol),
            )

            self.assertEqual(first, second)
            self.assertRegex(first, PUBLIC_REVISION)
            self.assertNotIn("/", first)
            self.assertNotIn("listing", first)
            self.assertNotRegex(first, r"[0-9a-f]{64}")

    def test_public_revision_binds_same_content_to_business_batch_context(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            listing = Path(tmp_dir) / "listing.xlsx"
            protocol = Path(tmp_dir) / "protocol.docx"
            listing.write_bytes(b"same-listing")
            protocol.write_bytes(b"same-protocol")
            listing_snapshot = read_monitoring_source(listing)
            protocol_snapshot = read_monitoring_source(protocol)

            first = public_monitoring_source_revision(
                listing_snapshot,
                protocol_snapshot,
                "batch_001",
            )
            replay = public_monitoring_source_revision(
                listing_snapshot,
                protocol_snapshot,
                "batch_001",
            )
            second = public_monitoring_source_revision(
                listing_snapshot,
                protocol_snapshot,
                "batch_002",
            )

            self.assertEqual(first, replay)
            self.assertNotEqual(first, second)

    def test_rux_and_my009_reload_listing_and_protocol_caches_after_synthetic_mutation(self):
        cases = (
            (
                RuxMonitoringService,
                "services.api.app.rux_monitoring_service",
                SUBJ_SHEET,
                "SUBJID",
            ),
            (
                My009MonitoringService,
                "services.api.app.my009_monitoring_service",
                "DS",
                "USUBJID",
            ),
        )
        for service_type, module_name, subject_sheet, subject_field in cases:
            with self.subTest(service=service_type.__name__), tempfile.TemporaryDirectory() as tmp_dir:
                listing_path = Path(tmp_dir) / "synthetic.xlsx"
                protocol_path = Path(tmp_dir) / "synthetic.docx"
                listing_path.write_bytes(b"listing-one")
                protocol_path.write_bytes(b"protocol-one")

                def parse_listing(_filename, content):
                    suffix = "01" if content == b"listing-one" else "02"
                    return [
                        SimpleNamespace(
                            sheet_name=subject_sheet,
                            rows=[{subject_field: f"S000{suffix}"}],
                        )
                    ]

                def parse_protocol(_filename, content):
                    return SimpleNamespace(marker=content.decode("ascii"))

                with (
                    patch(f"{module_name}.parse_listing_file", side_effect=parse_listing) as listing_parser,
                    patch(f"{module_name}.parse_protocol_docx", side_effect=parse_protocol) as protocol_parser,
                ):
                    service = service_type(listing_path, protocol_path)
                    first_revision = service.source_revision()
                    self.assertEqual(["S00001"], service.subject_ids())
                    self.assertEqual(["S00001"], service.subject_ids())
                    self.assertEqual("protocol-one", service._doc().marker)
                    self.assertEqual("protocol-one", service._doc().marker)
                    self.assertEqual(1, listing_parser.call_count)
                    self.assertEqual(1, protocol_parser.call_count)

                    listing_path.write_bytes(b"listing-two-expanded")
                    self.assertEqual(["S00002"], service.subject_ids())
                    self.assertNotEqual(first_revision, service.source_revision())
                    self.assertEqual(2, listing_parser.call_count)

                    listing_revision = service.source_revision()
                    protocol_path.write_bytes(b"protocol-two-expanded")
                    self.assertEqual("protocol-two-expanded", service._doc().marker)
                    self.assertNotEqual(listing_revision, service.source_revision())
                    self.assertEqual(2, protocol_parser.call_count)

    def test_bound_adapter_fails_closed_when_revision_changes_mid_request(self):
        class ChangingService:
            def __init__(self):
                self.revision = "monsrcv_" + "1" * 24

            def source_revision(self):
                return self.revision

            def subject_catalog(self, project_id):
                response = {
                    "project_id": project_id,
                    "source_revision": self.revision,
                    "subjects": [],
                }
                self.revision = "monsrcv_" + "2" * 24
                return response

        binding = BoundMonitoringProjectAdapter(
            project_id="project-real",
            service=ChangingService(),
        )
        with self.assertRaisesRegex(RuntimeError, "changed while the request"):
            binding.subject_catalog()


def _assert_public_drilldown(test: unittest.TestCase, profile, expected_revision: str) -> None:
    test.assertEqual(expected_revision, profile.source_revision)
    test.assertRegex(profile.source_revision, PUBLIC_REVISION)
    for event in profile.timeline:
        test.assertTrue(event.source_locator.startswith("listing:"), event.source_locator)
        test.assertNotIn("/Users/", event.source_locator)
    for metric in [*profile.efficacy_trends, *profile.safety_trends]:
        for point in metric.points:
            test.assertTrue(point.source_locator.startswith("listing:"), point.source_locator)
            test.assertNotIn("/Users/", point.source_locator)


@unittest.skipUnless(
    RUX_LISTING_PATH.exists() and RUX_PROTOCOL_PATH.exists(),
    "RUX raw monitoring sources unavailable",
)
class RuxFullCatalogRevisionTests(unittest.TestCase):
    def test_all_241_catalog_subjects_have_revision_bound_public_drilldowns(self):
        service = RuxMonitoringService(RUX_LISTING_PATH, RUX_PROTOCOL_PATH)
        catalog = service.subject_catalog("proj_rux_03_002")

        self.assertEqual(241, catalog["subject_count"])
        self.assertRegex(catalog["source_revision"], PUBLIC_REVISION)
        self.assertTrue(all(item["source_locator"].startswith("listing:") for item in catalog["subjects"]))
        for item in catalog["subjects"]:
            profile = service.subject_monitoring("proj_rux_03_002", item["id"])
            _assert_public_drilldown(self, profile, catalog["source_revision"])


@unittest.skipUnless(
    MY009_LISTING_PATH.exists() and MY009_PROTOCOL_PATH.exists(),
    "MY009 raw monitoring sources unavailable",
)
class My009FullCatalogRevisionTests(unittest.TestCase):
    def test_all_26_catalog_subjects_have_revision_bound_public_drilldowns(self):
        service = My009MonitoringService(MY009_LISTING_PATH, MY009_PROTOCOL_PATH)
        catalog = service.subject_catalog("proj_my009_uc")

        self.assertEqual(26, catalog["subject_count"])
        self.assertRegex(catalog["source_revision"], PUBLIC_REVISION)
        self.assertTrue(all(item["source_locator"].startswith("listing:") for item in catalog["subjects"]))
        for item in catalog["subjects"]:
            profile = service.subject_monitoring("proj_my009_uc", item["id"])
            _assert_public_drilldown(self, profile, catalog["source_revision"])

    def test_missing_dm_subjects_use_ds_sv_identity_without_invented_demographics(self):
        service = My009MonitoringService(MY009_LISTING_PATH, MY009_PROTOCOL_PATH)
        catalog = service.subject_catalog("proj_my009_uc")

        for subject_id, expected_site in (("S02002", "02"), ("S16001", "16")):
            item = next(item for item in catalog["subjects"] if item["id"] == subject_id)
            self.assertEqual(expected_site, item["site"])
            self.assertIn(":sheet:DS:", item["source_locator"])
            profile = service.subject_monitoring("proj_my009_uc", subject_id)
            self.assertEqual(expected_site, profile.subject.site_id)
            self.assertFalse(
                any(context.startswith(("性别：", "年龄：")) for context in profile.subject.key_medical_context)
            )


if __name__ == "__main__":
    unittest.main()
