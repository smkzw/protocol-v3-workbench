from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.api.app import main as app_main
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
    _study_definition_facts_sha256,
)
from services.api.app.medical_writing_study_schema import study_schema_state_sha256
from tests.test_medical_writing_study_schema import _complete_journey, _pnh_schema


class MedicalWritingStudySchemaApiTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "authoring_journey.sqlite3"
        )
        self.service_patch = patch(
            "services.api.app.main.medical_writing_authoring_journey_service",
            self.service,
        )
        self.service_patch.start()
        self.client = TestClient(app_main.app)
        self.project_id = "proj_mgk10_crswnp"
        self.state = _complete_journey(self.service, self.project_id)

    def tearDown(self):
        self.service_patch.stop()
        self.tmpdir.cleanup()

    def _proposal(self):
        facts_sha256 = _study_definition_facts_sha256(
            self.state.framing, self.state.picos
        )
        proposal = _pnh_schema().model_copy(
            update={"source_facts_sha256": facts_sha256}, deep=True
        )
        return proposal.model_copy(
            update={"state_sha256": study_schema_state_sha256(proposal)}, deep=True
        )

    def test_full_api_cycle_is_versioned_idempotent_and_serves_safe_svg(self):
        base = (
            f"/api/projects/{self.project_id}/medical-writing/authoring-journey/"
            "study-schema"
        )
        empty = self.client.get(base)
        self.assertEqual(200, empty.status_code, empty.text)
        self.assertIsNone(empty.json()["study_schema"])
        self.assertFalse(empty.json()["formal_render_allowed"])

        proposal_response = self.client.get(f"{base}/proposal")
        self.assertEqual(200, proposal_response.status_code, proposal_response.text)
        proposal_body = proposal_response.json()
        self.assertEqual("draft", proposal_body["status"])
        self.assertTrue(proposal_body["nodes"])
        self.assertTrue(
            all(node["fact_status"] == "extracted_candidate" for node in proposal_body["nodes"])
        )
        self.assertTrue(
            any(node["node_kind"] == "randomization" for node in proposal_body["nodes"])
        )

        proposal = self._proposal()
        preview = self.client.post(
            f"{base}/impact-preview",
            json={
                "expected_journey_revision": self.state.revision,
                "study_schema": proposal.model_dump(mode="json"),
            },
        )
        self.assertEqual(200, preview.status_code, preview.text)
        self.assertTrue(preview.json()["requires_confirmation"])
        self.assertIn("<svg", preview.json()["svg"])
        self.assertTrue(preview.json()["svg_sha256"])
        self.assertTrue(preview.json()["formal_render_allowed"])

        commit_payload = {
            "expected_journey_revision": self.state.revision,
            "study_schema": proposal.model_dump(mode="json"),
            "impact_preview_id": preview.json()["preview_id"],
            "reason": "医学经理已核对研究分组、随机和随访关系。",
            "actor": "medical_manager_api_test",
            "idempotency_key": "api-commit-study-schema",
        }
        committed = self.client.post(f"{base}/commit", json=commit_payload)
        self.assertEqual(200, committed.status_code, committed.text)
        body = committed.json()
        self.assertTrue(body["formal_render_allowed"])
        self.assertEqual("confirmed", body["study_schema"]["status"])
        clinical_hash = body["study_schema"]["state_sha256"]

        replay = self.client.post(f"{base}/commit", json=commit_payload)
        self.assertEqual(200, replay.status_code, replay.text)
        self.assertEqual(clinical_hash, replay.json()["study_schema"]["state_sha256"])
        self.assertEqual(body["journey_revision"], replay.json()["journey_revision"])

        stale = self.client.post(
            f"{base}/impact-preview",
            json={
                "expected_journey_revision": self.state.revision,
                "study_schema": proposal.model_dump(mode="json"),
            },
        )
        self.assertEqual(409, stale.status_code, stale.text)

        layout = self.client.post(
            f"{base}/layout",
            json={
                "expected_journey_revision": body["journey_revision"],
                "expected_schema_revision": body["study_schema"]["revision"],
                "expected_layout_revision": body["presentation"]["layout_revision"],
                "node_overrides": [{"node_id": "low", "dx": 24, "dy": -8}],
                "actor": "medical_manager_api_test",
                "idempotency_key": "api-layout-study-schema",
            },
        )
        self.assertEqual(200, layout.status_code, layout.text)
        self.assertEqual(clinical_hash, layout.json()["study_schema"]["state_sha256"])
        self.assertGreater(
            layout.json()["presentation"]["layout_revision"],
            body["presentation"]["layout_revision"],
        )

        svg = self.client.get(f"{base}.svg")
        self.assertEqual(200, svg.status_code, svg.text)
        self.assertEqual("image/svg+xml", svg.headers["content-type"])
        self.assertEqual("true", svg.headers["x-study-schema-formal-render"])
        self.assertTrue(svg.headers["etag"].startswith('"'))
        self.assertIn("低剂量组", svg.text)
        self.assertNotIn("<script", svg.text)
        self.assertNotIn("foreignObject", svg.text)


if __name__ == "__main__":
    unittest.main()
