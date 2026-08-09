from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.enrollment_adapter import EnrollmentReviewAdapter  # noqa: E402
from services.api.app.main import app  # noqa: E402


class EligibilityAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = EnrollmentReviewAdapter()
        cls.client = TestClient(app)

    def test_adapter_reads_real_mgk10_sar_phase3_rules_and_subject_phase_reviews(self):
        dataset = self.adapter.eligibility_dataset("MG-K10-SAR-III")

        self.assertEqual("enrollment-review-app", dataset.source_system)
        self.assertEqual("MG-K10-SAR-III", dataset.source_project_code)
        self.assertEqual("Ⅲ期", dataset.study_stage)
        self.assertGreaterEqual(dataset.project_stats.total_subjects, 10)

        rule_ids = set(dataset.criteria_rule_ids)
        self.assertTrue(any(rule_id.startswith("IN-") for rule_id in rule_ids))
        self.assertTrue(any(rule_id.startswith("EX-") for rule_id in rule_ids))
        self.assertIn("IN-05", rule_ids)
        self.assertIn("EX-07", rule_ids)
        self.assertNotIn("IN-HISTORY-DURATION", rule_ids)

        subject = next(row for row in dataset.subject_rows if row.subject_id == "31001")
        self.assertIn("screening_run_in", subject.phase_reviews)
        self.assertIn("baseline_randomization", subject.phase_reviews)
        self.assertEqual("reviewed", subject.phase_reviews["screening_run_in"].status)
        self.assertEqual("reviewed", subject.phase_reviews["baseline_randomization"].status)
        self.assertTrue(subject.phase_reviews["screening_run_in"].has_report)
        self.assertTrue(subject.phase_reviews["baseline_randomization"].evidence_bundle_exists)

    def test_eligibility_api_returns_selected_subject_rule_reviews_and_audit_summary(self):
        response = self.client.get(
            "/api/projects/MG-K10-SAR-III/eligibility",
            params={"subject_id": "31001", "phase_id": "baseline_randomization"},
        )
        self.assertEqual(200, response.status_code)
        payload = response.json()

        self.assertEqual("MG-K10-SAR-III", payload["source_project_code"])
        self.assertEqual("baseline_randomization", payload["task_entry"]["selected_phase_id"])
        self.assertGreaterEqual(payload["project_stats"]["criteria_rule_count"], 20)

        selected = payload["selected_candidate"]
        self.assertEqual("31001", selected["subject_id"])
        self.assertEqual("enrollment-review-app", selected["source_system"])
        self.assertTrue(selected["rule_reviews"])
        returned_rule_ids = {item["rule_id"] for item in selected["rule_reviews"]}
        returned_verdicts = {item["verdict"] for item in selected["rule_reviews"]}
        self.assertIn("IN-05", returned_rule_ids)
        self.assertIn("pass_verify", returned_verdicts)
        self.assertIn("insufficient", returned_verdicts)
        self.assertTrue(all(rule_id.startswith(("IN-", "EX-")) for rule_id in returned_rule_ids))
        self.assertTrue(selected["phase_reviews"][0]["phase_id"])
        self.assertTrue(selected["missing_information"])
        self.assertGreater(payload["audit_summary"]["event_count"], 0)
        serialized = response.text
        self.assertNotIn("/Users/", serialized)
        for forbidden_key in (
            "source_record_id",
            "source_path",
            "source_project_path",
            "report_path",
            "raw_response_path",
            "evidence_bundle_path",
            "audit_ledger_path",
            "source_report_path",
            "source_raw_path",
        ):
            self.assertNotIn(forbidden_key, serialized)

    def test_eligibility_api_maps_workbench_demo_project_to_original_project(self):
        response = self.client.get("/api/projects/proj_mgk10_sar_demo/eligibility")
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("MG-K10-SAR-III", payload["source_project_code"])
        self.assertTrue(payload["subject_rows"])


if __name__ == "__main__":
    unittest.main()
