from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app import eligibility
from services.api.app.eligibility_review_workflow import EvidenceProcessingState
from services.api.app.main import app
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore


class EligibilityReviewApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteRuntimeStore(Path(self.tmp.name) / "runtime.sqlite3")
        eligibility.configure_eligibility_review_workflow(self.store)
        self.previous_source_admission_guard = eligibility.eligibility_source_admission_guard
        eligibility.configure_eligibility_source_admission_guard(
            lambda project_id: {"project_id": project_id, "ready_for_use": True, "sources": []}
        )
        self.client = TestClient(app)

    def tearDown(self):
        eligibility.configure_eligibility_source_admission_guard(
            self.previous_source_admission_guard
        )
        self.tmp.cleanup()

    def test_source_admission_guard_fails_closed_before_write_or_ai_execution(self):
        eligibility.configure_eligibility_source_admission_guard(
            lambda project_id: {
                "project_id": project_id,
                "ready_for_use": False,
                "sources": [],
                "missing_source_kinds": ["protocol_docx", "raw_subject_bundle_inventory"],
            }
        )

        with self.assertRaisesRegex(Exception, "409"):
            eligibility._require_eligibility_source_admission("proj_d001")

    def _real_inputs_available(self, project_id):
        config = eligibility.RAW_INTAKE_PROJECTS[project_id]
        return Path(config.protocol_path).exists() and Path(config.raw_subject_root).exists()

    def test_two_real_projects_return_canonical_versioned_review_packages(self):
        cases = (
            ("d001_raw_intake", "SA07005", "proj_d001", 36),
            ("my009_uc_raw_intake", "S01009", "proj_my009_uc", 34),
        )
        for route_project_id, subject_id, canonical_project_id, criterion_count in cases:
            if not self._real_inputs_available(route_project_id):
                self.skipTest(f"real eligibility inputs unavailable: {route_project_id}")
            with self.subTest(project_id=route_project_id):
                response = self.client.get(
                    f"/api/projects/{route_project_id}/eligibility/raw-intake/"
                    f"subjects/{subject_id}/review"
                )
                self.assertEqual(200, response.status_code, response.text)
                payload = response.json()
                self.assertEqual(canonical_project_id, payload["project_id"])
                self.assertEqual(criterion_count, len(payload["criteria"]))
                self.assertEqual(
                    criterion_count, payload["aggregate"]["criterion_count"]
                )
                self.assertEqual(0, payload["aggregate"]["reviewed_count"])
                self.assertEqual(
                    ["blocked_by_incomplete_review"],
                    payload["aggregate"]["statuses"],
                )
                self.assertTrue(payload["rule_revision"].startswith("eligrulev_"))
                self.assertTrue(
                    payload["subject_source_revision"].startswith("eligsubsrcv_")
                )
                serialized = json.dumps(payload, ensure_ascii=False)
                for forbidden in (
                    "/Users/",
                    "content_hash",
                    "normalized_text_hash",
                    "filename",
                    "eligible\"",
                    "not_eligible",
                    "randomization_release",
                ):
                    self.assertNotIn(forbidden, serialized)

    def test_cross_project_subject_probe_matches_unknown_subject_response(self):
        if not self._real_inputs_available("proj_my009_uc"):
            self.skipTest("MY009 real eligibility inputs unavailable")
        wrong_project = self.client.get(
            "/api/projects/proj_my009_uc/eligibility/raw-intake/subjects/SA07005/review"
        )
        unknown = self.client.get(
            "/api/projects/proj_my009_uc/eligibility/raw-intake/subjects/ZZ99999/review"
        )
        self.assertEqual(404, wrong_project.status_code)
        self.assertEqual(404, unknown.status_code)
        self.assertEqual(unknown.json(), wrong_project.json())

    def test_medical_action_is_evidence_bound_idempotent_and_stale_safe(self):
        if not self._real_inputs_available("proj_d001"):
            self.skipTest("D001 real eligibility inputs unavailable")
        review_url = (
            "/api/projects/proj_d001/eligibility/raw-intake/subjects/"
            "SA07005/review"
        )
        review_response = self.client.get(review_url)
        self.assertEqual(200, review_response.status_code, review_response.text)
        review = review_response.json()
        criterion = next(
            item
            for item in review["criteria"]
            if item["criterion_kind"] == "inclusion"
        )
        subject = eligibility.raw_intake_service.subject_manifest(
            eligibility.RAW_INTAKE_PROJECTS["proj_d001"], "SA07005"
        )
        source = subject.sources[0]
        eligibility.review_workflow.register_evidence_span(
            evidence_id="evidence-api-1",
            project_id="proj_d001",
            subject_id="SA07005",
            source_id=source.source_id,
            source_revision=source.source_revision,
            extraction_revision="api-test-extraction-v1",
            locator={"page": 1, "region": [10, 20, 30, 40]},
            media_class=source.source_type,
            processing_state=EvidenceProcessingState.COMPLETED,
            quality_state="medical_test_verified",
            extraction_confidence=0.99,
            medical_verification_status="verified",
        )
        self.store.commit_eligibility_evidence_visual_qc(
            project_id="proj_d001",
            subject_id="SA07005",
            evidence_id="evidence-api-1",
            expected_qc_revision=0,
            expected_source_revision=source.source_revision,
            expected_extraction_revision="api-test-extraction-v1",
            idempotency_key="api-fixture-qc-pass",
            result="sampled_pass",
            reason_code="api_visual_comparison",
            user_reason="API fixture page and extracted region were compared.",
            sample_plan_id="api-full-page-v1",
            sample_unit={"page": 1, "region": [10, 20, 30, 40]},
            policy_version="visual-qc-policy-v1",
            actor="test_qc_reviewer",
        )
        refreshed = self.client.get(review_url)
        self.assertEqual(200, refreshed.status_code, refreshed.text)
        self.assertEqual("evidence-api-1", refreshed.json()["evidence"][0]["evidence_id"])
        evidence_projection = json.dumps(
            refreshed.json()["evidence"], ensure_ascii=False
        )
        self.assertNotIn("content_hash", evidence_projection)
        self.assertNotIn("metadata", evidence_projection)
        self.assertNotIn("/Users/", evidence_projection)
        action_url = (
            "/api/projects/proj_d001/eligibility/raw-intake/subjects/SA07005/"
            f"criteria/{criterion['criterion_uid']}/actions"
        )
        request = {
            "criterion_kind": "inclusion",
            "expected_state_revision": 0,
            "expected_rule_revision": review["rule_revision"],
            "expected_subject_source_revision": review["subject_source_revision"],
            "idempotency_key": "api-medical-action-1",
            "actor": "medical_manager",
            "action": "revise_decision",
            "decision": "met",
            "reason": "Current versioned evidence was medically reviewed.",
            "evidence_ids": ["evidence-api-1"],
            "evidence_processing_state": "completed",
        }

        first = self.client.post(action_url, json=request)
        replay = self.client.post(action_url, json=request)
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual(200, replay.status_code, replay.text)
        self.assertFalse(first.json()["replayed"])
        self.assertTrue(replay.json()["replayed"])
        self.assertEqual("met", first.json()["state"]["medical_decision"])
        self.assertIsNone(first.json()["state"]["ai_draft_decision"])

        stale_request = dict(request)
        stale_request["idempotency_key"] = "api-medical-action-stale"
        stale = self.client.post(action_url, json=stale_request)
        self.assertEqual(409, stale.status_code, stale.text)
        self.assertEqual(
            "审阅状态或来源版本已更新，请刷新后重试",
            stale.json()["detail"],
        )
        rejection_events = [
            event
            for event in self.store.runtime_audit_records("proj_d001")
            if event["event_type"] == "eligibility_stale_write_rejected"
        ]
        self.assertEqual(1, len(rejection_events))

        invalid = dict(request)
        invalid["idempotency_key"] = "api-invalid-exclusion-decision"
        invalid["decision"] = "present"
        invalid_response = self.client.post(action_url, json=invalid)
        self.assertEqual(422, invalid_response.status_code)

        forged_ai = dict(request)
        forged_ai.update(
            {
                "idempotency_key": "api-forged-ai-draft",
                "actor": "workbench_ai_gateway",
                "action": "save_ai_draft",
            }
        )
        forged_response = self.client.post(action_url, json=forged_ai)
        self.assertEqual(403, forged_response.status_code, forged_response.text)
        self.assertEqual(
            "AI审核草稿只允许由服务端独立AI工作流写入",
            forged_response.json()["detail"],
        )
        self.assertFalse(
            any(
                row["actor"] == "workbench_ai_gateway"
                for row in self.store.eligibility_review_records(
                    "proj_d001", "SA07005"
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
