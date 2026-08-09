from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.main import app  # noqa: E402
from services.api.app.monitoring_identity_authorization import MonitoringRole  # noqa: E402
from services.api.app.monitoring_runtime_principal import (  # noqa: E402
    MonitoringAuthenticatedPrincipal,
)
from services.api.app.mgk10_sar_monitoring_service import (  # noqa: E402
    MGK10_SAR_PROJECT_ID,
    Mgk10SarMonitoringService,
)


LISTING_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/MG-K10/SAR/13. CFDI核查/自查/评分SDV/"
    "【锁库后Data Listing】MG-K10-SAR-001_FormExcelAllVersion_202601201126.xlsx"
)
PROTOCOL_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/MG-K10/SAR/4. Protocol/"
    "MG-K10-SAR-001_临床研究方案_ V2.1_20250919_clean版 .docx"
)


@unittest.skipUnless(LISTING_PATH.exists() and PROTOCOL_PATH.exists(), "MG-K10-SAR raw sources unavailable")
class Mgk10SarMonitoringServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = Mgk10SarMonitoringService(LISTING_PATH, PROTOCOL_PATH)

    @staticmethod
    def _principal() -> MonitoringAuthenticatedPrincipal:
        return MonitoringAuthenticatedPrincipal(
            principal_id="mgk10-monitoring-test",
            tenant_id="tenant-kangzhe",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=("proj_mgk10_sar_real",),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="mgk10-monitoring-test-session",
            directory_revision="mgk10-monitoring-test-v1",
            verification_ref_sha256="b" * 64,
        )

    def test_catalog_is_derived_from_365_real_subjects_without_private_path_leakage(self):
        catalog = self.service.subject_catalog(MGK10_SAR_PROJECT_ID)

        self.assertEqual(365, catalog["subject_count"])
        self.assertEqual(25, len(self.service.site_ids()))
        self.assertTrue({"10008", "01003", "04004"}.issubset({item["id"] for item in catalog["subjects"]}))
        self.assertTrue(
            all(item["source_locator"].startswith("listing:MG-K10-SAR-Listing:sheet:DM:row:") for item in catalog["subjects"])
        )
        serialized = json.dumps(catalog, ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("FormExcelAllVersion", serialized)

    def test_visit_axis_uses_actual_planned_and_unscheduled_source_rows(self):
        profile = self.service.subject_monitoring(MGK10_SAR_PROJECT_ID, "10008")

        self.assertEqual(8, len(profile.visit_anchors))
        self.assertEqual(
            ["V1D-7~D-1", "V2D1", "V3D8", "V4D15", "V5D29", "V6D57", "V7D85"],
            [item.visit_code for item in profile.visit_anchors if not item.is_unscheduled],
        )
        unscheduled = next(item for item in profile.visit_anchors if item.is_unscheduled)
        self.assertEqual("UNS", unscheduled.visit_code)
        self.assertEqual("2025-12-04", unscheduled.actual_date)
        self.assertTrue(unscheduled.source_locator.endswith("sheet:UNS:row:11"))

    def test_cm_and_study_drug_lanes_are_strictly_separated_and_blind_is_protected(self):
        profile = self.service.subject_monitoring(MGK10_SAR_PROJECT_ID, "10008")
        cm = [event for event in profile.timeline if event.source_domain == "CM"]
        study_drug = [event for event in profile.timeline if event.source_domain == "EX"]
        background = [
            event
            for event in profile.timeline
            if event.source_domain in {"EX1", "EX2", "EX4", "EX5", "EX7"}
        ]

        self.assertTrue(cm)
        self.assertTrue(study_drug)
        self.assertTrue(background)
        self.assertTrue(all(event.event_type.value == "concomitant_medication" for event in cm))
        self.assertTrue(all(event.event_subtype.value == "non_study_medication" for event in cm))
        self.assertTrue(all(event.event_type.value == "study_drug_administration" for event in study_drug))
        self.assertTrue(all(event.event_type.value == "background_treatment" for event in background))
        self.assertTrue(all(event.event_subtype.value == "protocol_background_treatment" for event in background))
        self.assertFalse(any(event.event_type.value == "dose_adjustment" for event in cm + study_drug + background))
        self.assertEqual("待解盲", profile.subject.treatment_arm)
        self.assertTrue(profile.subject.blinded)
        self.assertTrue(profile.subject.treatment_arm_masked)

    def test_patient_profile_preserves_repeated_measurements_and_point_specific_lab_context(self):
        profile = self.service.subject_monitoring(MGK10_SAR_PROJECT_ID, "10008")
        efficacy = {metric.metric_key: metric for metric in profile.efficacy_trends}
        safety = {metric.metric_key: metric for metric in profile.safety_trends}

        self.assertGreaterEqual(len(efficacy["rtnss"].points), 100)
        self.assertEqual(7, efficacy["rtnss"].points[0].baseline_expected_count)
        self.assertEqual(7, efficacy["rtnss"].points[0].baseline_observed_count)
        self.assertEqual(7, len(efficacy["rtnss"].points[0].baseline_component_source_locators))
        self.assertIn("导入期最后6个时间点", efficacy["rtnss"].points[0].baseline_rule)
        self.assertEqual(4, efficacy["itnss"].points[0].baseline_expected_count)
        same_day = [point for point in efficacy["rtnss"].points if point.assessment_date == "2025-08-19"]
        self.assertGreaterEqual(len(same_day), 2)
        self.assertEqual(len(same_day), len({point.point_id for point in same_day}))
        self.assertTrue(all(point.assessment_sequence for point in same_day))

        eos_context = [
            event
            for event in profile.timeline
            if event.source_domain == "LB_HEM" and "嗜酸性粒细胞计数" in event.title
        ]
        self.assertTrue(eos_context)
        self.assertIn("10^9/L", eos_context[0].detail)
        for metric_key in {"wbc", "anc", "hemoglobin", "platelet", "alt", "ast"}:
            self.assertIn(metric_key, safety)
            self.assertTrue(all(point.unit for point in safety[metric_key].points))
            self.assertTrue(all(point.reference_range_source for point in safety[metric_key].points))
        self.assertLessEqual(len(safety), 10)
        labels = {metric.metric_label for metric in safety.values()}
        self.assertIn("嗜酸性粒细胞计数（EO）", labels)
        self.assertIn("甘油三酯（TG）", labels)

    def test_unscheduled_assessments_preserve_each_original_record_and_medical_context(self):
        profile = self.service.subject_monitoring(MGK10_SAR_PROJECT_ID, "26007")
        unscheduled = [event for event in profile.timeline if event.source_domain == "USV"]

        self.assertEqual(30, len(unscheduled))
        self.assertEqual(30, len({event.event_id for event in unscheduled}))
        same_day = [event for event in unscheduled if event.event_date == "2025-09-02"]
        self.assertEqual(9, len(same_day))
        self.assertEqual(9, len({event.event_id for event in same_day}))
        self.assertTrue(all(event.raw_event_date == event.event_date for event in unscheduled))
        self.assertTrue(all(event.is_unscheduled for event in unscheduled))
        uric_acid = next(event for event in unscheduled if "尿酸" in event.title)
        self.assertEqual("372 umol/L", uric_acid.result_value)
        self.assertIn("参考范围 [155, 357]", uric_acid.detail)
        self.assertIn("异常有临床意义", uric_acid.clinical_interpretation)
        self.assertIn("MH (2) 高尿酸血症", uric_acid.clinical_interpretation)
        laboratory = next(item for item in profile.domain_availability if item.domain == "laboratory")
        self.assertEqual("available", laboratory.status.value)

    def test_subject_source_fragment_resolves_to_original_listing_row_content(self):
        profile = self.service.subject_monitoring(MGK10_SAR_PROJECT_ID, "10008")
        event = next(item for item in profile.timeline if item.source_domain == "AE")
        fragment = self.service.resolve_source_fragment(event.source_locator)

        self.assertEqual("listing", fragment["source_type"])
        self.assertEqual(event.source_locator, fragment["locator"])
        values = {item["field"]: item["value"] for item in fragment["fields"]}
        self.assertEqual("10008", values["SUBJID"])
        self.assertTrue(values["AETERM"])

    def test_api_routes_the_real_project_through_the_shared_monitoring_contract(self):
        client = TestClient(app)
        with patch(
            "services.api.app.main.resolve_monitoring_principal_from_request",
            return_value=self._principal(),
        ):
            catalog = client.get(f"/api/projects/{MGK10_SAR_PROJECT_ID}/monitoring/subjects")
            profile = client.get(f"/api/projects/{MGK10_SAR_PROJECT_ID}/subjects/10008/monitoring")

        self.assertEqual(200, catalog.status_code)
        self.assertEqual(365, catalog.json()["subject_count"])
        self.assertEqual(200, profile.status_code)
        payload = profile.json()
        self.assertEqual(MGK10_SAR_PROJECT_ID, payload["project_id"])
        self.assertEqual("10008", payload["subject_id"])
        self.assertTrue(payload["visit_anchors"])
        self.assertTrue(payload["efficacy_trends"])
        self.assertTrue(payload["safety_trends"])


if __name__ == "__main__":
    unittest.main()
