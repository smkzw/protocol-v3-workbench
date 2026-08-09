from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.main import app  # noqa: E402
from services.api.app.tfl_manifest import (  # noqa: E402
    MY008_ROOT,
    RUX_DATASET_ROOT,
    RUX_TFL_SINGLE_ROOT,
    TflManifestService,
    TflPackageConfig,
    _distinct_text_values,
    _domain_check_context,
    _package_content_validation,
    _standard_from_path,
)


class TflContentValidationUnitTests(unittest.TestCase):
    def test_study_id_lookup_is_case_insensitive_and_does_not_truncate_validation_values(self):
        values = [f"STUDY-{index:02d}" for index in range(25)]
        frame = pd.DataFrame({"StudyId": values})

        self.assertEqual(values, _distinct_text_values(frame, "STUDYID"))

    def test_sdtm_directory_takes_precedence_over_ad_prefixed_dataset_name(self):
        with tempfile.TemporaryDirectory(prefix="adam-parent-") as temp_dir:
            root = Path(temp_dir)
            path = root / "sdtm" / "ADHO.xpt"

            self.assertEqual("SDTM", _standard_from_path(path, root))

    def test_supplemental_qualifier_uses_rdomain_and_relrec_is_not_applicable(self):
        self.assertEqual(("RDOMAIN", "AE"), _domain_check_context("SDTM", "SUPPAE", ""))
        self.assertEqual(("", ""), _domain_check_context("SDTM", "RELREC", ""))

    def test_missing_expected_study_or_sap_cannot_be_aggregated_as_matched(self):
        dataset = type(
            "Dataset",
            (),
            {
                "study_identity_status": "not_assessed",
                "domain_consistency_status": "match",
                "parser_status": "parsed",
                "standard": "SDTM",
            },
        )()

        status, notes = _package_content_validation([dataset], (), "")

        self.assertEqual("warning", status)
        self.assertTrue(any("SAP版本尚未绑定" in note for note in notes))

    def test_custom_project_configuration_and_explicit_empty_packages_are_respected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = TflPackageConfig(
                package_id="custom",
                package_label="Custom",
                dataset_root=root,
                tfl_root=root,
                dataset_root_label="Dataset",
                tfl_root_label="TFL",
                expected_study_ids=("CUSTOM-01",),
                project_ids=("proj_custom",),
            )
            manifest = TflManifestService(packages=[config]).build_manifest("proj_custom")
            self.assertEqual(1, manifest.package_count)

        with self.assertRaises(KeyError):
            TflManifestService(packages=[]).build_manifest("proj_rux_03_002")


@unittest.skipUnless(RUX_DATASET_ROOT.exists() and RUX_TFL_SINGLE_ROOT.exists(), "RUX TFL fixture paths are unavailable")
class TflManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        service = TflManifestService()
        cls.manifests = {
            "rux_03_002": service.build_manifest("proj_rux_03_002"),
            "my008_pnh_3_01": service.build_manifest("proj_my008_pnh_3_01"),
        }

    def package(self, package_id: str):
        return self.manifests[package_id].packages[0]

    def test_rux_manifest_reads_xpt_define_and_final_single_tfl_inventory(self):
        package = self.package("rux_03_002")

        self.assertEqual({"ADaM": 12, "SDTM": 48}, package.dataset_count_by_standard)
        self.assertEqual({"adam_xpt": 12, "sdtm_xpt": 48}, package.dataset_count_by_role)
        self.assertEqual(2, package.define_xml_count)
        self.assertEqual(59, package.define_itemgroup_count)
        self.assertEqual({"figure": 3, "listing": 31, "table": 57}, package.tfl_count_by_type)

        adsl = next(dataset for dataset in package.datasets if dataset.dataset_name == "ADSL")
        ae = next(dataset for dataset in package.datasets if dataset.dataset_name == "AE")
        self.assertEqual((241, 91), (adsl.row_count, adsl.column_count))
        self.assertEqual((356, 35), (ae.row_count, ae.column_count))
        self.assertTrue(adsl.define_linked)
        self.assertTrue(ae.define_linked)
        self.assertEqual(["RUX-03-002"], adsl.observed_study_ids)
        self.assertEqual("match", adsl.study_identity_status)
        self.assertEqual(["AE"], ae.observed_domain_values)
        self.assertEqual("match", ae.domain_consistency_status)
        self.assertEqual("warning", package.content_validation_status)
        self.assertEqual("warning", package.sap_version_status)
        self.assertTrue(any("SAP版本" in note for note in package.content_validation_notes))

    @unittest.skipUnless(MY008_ROOT.exists(), "MY008 TFL fixture path is unavailable")
    def test_my008_manifest_separates_dataset_roles_and_tfl_data_pairing(self):
        package = self.package("my008_pnh_3_01")

        self.assertEqual(0, package.define_xml_count)
        self.assertEqual(0, package.define_itemgroup_count)
        self.assertEqual(
            {
                "adam_sas7bdat": 18,
                "adam_xpt": 18,
                "raw_sas7bdat": 55,
                "sdtm_sas7bdat": 45,
                "sdtm_xpt": 45,
                "tfl_data_sas7bdat": 161,
            },
            package.dataset_count_by_role,
        )
        self.assertEqual({"figure": 23, "listing": 56, "table": 85}, package.tfl_count_by_type)
        self.assertTrue(any("未发现define.xml" in warning for warning in package.parser_warnings))

        teae = next(output for output in package.outputs if output.display_id == "t-14-03-02-01-ae-teae")
        self.assertEqual("table", teae.output_type)
        self.assertEqual("AE", teae.domain_hint)
        self.assertTrue(teae.paired_file_id)
        self.assertNotIn("/Users/", teae.relative_path)

    def test_tfl_manifest_endpoint_does_not_expose_local_absolute_paths_or_lifecycle_names(self):
        response = TestClient(app).get("/api/projects/proj_rux_03_002/tfl/manifest")
        self.assertEqual(200, response.status_code)
        payload = response.json()
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertEqual("数据分析与TFL", payload["module_label"])
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("第7环节", serialized)
        self.assertNotIn("阶段7", serialized)
        self.assertEqual(1, payload["package_count"])
        self.assertGreaterEqual(payload["total_datasets"], 60)
        self.assertGreaterEqual(payload["total_outputs"], 90)
