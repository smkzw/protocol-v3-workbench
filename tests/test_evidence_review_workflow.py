from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.evidence_design_manifest import (  # noqa: E402
    CRSWNP_MASTER_ROOT,
    PNH_COMPETITOR_DB,
    EvidenceDesignManifestService,
)
from services.api.app.evidence_review_workflow import EvidenceReviewWorkflowService  # noqa: E402
from services.api.app.main import app  # noqa: E402
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore  # noqa: E402


@unittest.skipUnless(
    CRSWNP_MASTER_ROOT.exists() and PNH_COMPETITOR_DB.exists(),
    "real CRSwNP and PNH evidence sources are unavailable",
)
class EvidenceReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "runtime.sqlite3"
        self.manifests = EvidenceDesignManifestService()
        self.runtime = SqliteRuntimeStore(self.db_path)
        self.service = EvidenceReviewWorkflowService(self.manifests, self.runtime)

    def tearDown(self):
        self.tmp.cleanup()

    def first_candidate(self, project_id: str, package_id: str, candidate_type: str):
        return self.manifests.candidate_page(
            project_id,
            package_id,
            candidate_type=candidate_type,
            page=1,
            page_size=1,
        ).items[0]

    def test_include_extract_appraise_and_restart_preserve_state(self):
        project_id = "proj_my008_pnh_3_01"
        package_id = "pnh_competitive_evidence"
        candidate = self.first_candidate(project_id, package_id, "trial")

        included = self.service.apply_action(
            project_id,
            package_id,
            candidate.evidence_id,
            {"action": "include", "expected_revision": 0, "idempotency_key": "include-1"},
        )
        self.assertEqual("已纳入", included.screening_status)
        self.assertEqual(1, included.revision)

        extracted = self.service.apply_action(
            project_id,
            package_id,
            candidate.evidence_id,
            {
                "action": "save_extraction",
                "expected_revision": 1,
                "extraction": {
                    "研究设计": "随机、平行对照",
                    "主要终点": "Hb稳定与输血避免",
                },
                "idempotency_key": "extract-1",
            },
        )
        self.assertEqual("Hb稳定与输血避免", extracted.extraction["主要终点"])
        self.assertEqual(2, extracted.revision)

        appraised = self.service.apply_action(
            project_id,
            package_id,
            candidate.evidence_id,
            {
                "action": "save_appraisal",
                "expected_revision": 2,
                "quality_rating": "moderate",
                "reason": "原始注册信息完整，但尚缺完整方案与SAP复核。",
                "idempotency_key": "appraise-1",
            },
        )
        self.assertEqual("已评价", appraised.appraisal_status)
        self.assertEqual("moderate", appraised.quality_rating)
        self.assertEqual(3, appraised.revision)

        restarted = EvidenceReviewWorkflowService(
            EvidenceDesignManifestService(),
            SqliteRuntimeStore(self.db_path),
        )
        restored = restarted.state(project_id, package_id, candidate.evidence_id)
        self.assertEqual(3, restored.revision)
        self.assertEqual("已纳入", restored.screening_status)
        self.assertEqual(3, len(restored.history))

        page = restarted.candidate_page(
            project_id,
            package_id,
            candidate_type="trial",
            page=1,
            page_size=5,
        )
        row = next(item for item in page.items if item.evidence_id == candidate.evidence_id)
        self.assertEqual("已纳入", row.screening_status)
        self.assertEqual("已评价", row.appraisal_status)
        self.assertEqual(3, row.review_revision)

    def test_exclude_duplicate_and_defer_require_reason_and_stale_revision_is_rejected(self):
        project_id = "proj_mgk10_crswnp"
        package_id = "crswnp_competitive_evidence"
        candidate = self.first_candidate(project_id, package_id, "document")

        for action in ["exclude", "mark_duplicate", "defer"]:
            with self.assertRaises(ValueError):
                self.service.apply_action(
                    project_id,
                    package_id,
                    candidate.evidence_id,
                    {"action": action, "expected_revision": 0},
                )

        excluded = self.service.apply_action(
            project_id,
            package_id,
            candidate.evidence_id,
            {
                "action": "exclude",
                "reason": "非目标适应症且无可用研究设计信息。",
                "expected_revision": 0,
                "idempotency_key": "exclude-1",
            },
        )
        self.assertEqual("已排除", excluded.screening_status)
        with self.assertRaises(ValueError):
            self.service.apply_action(
                project_id,
                package_id,
                candidate.evidence_id,
                {"action": "reset_review", "expected_revision": 0},
            )

    def test_api_review_actions_use_project_scoped_runtime_state(self):
        project_id = "proj_my008_pnh_3_01"
        package_id = "pnh_competitive_evidence"
        candidate = self.first_candidate(project_id, package_id, "publication")
        client = TestClient(app)

        with patch("services.api.app.main.evidence_review_workflow_service", self.service):
            initial = client.get(
                f"/api/projects/{project_id}/evidence-design/packages/{package_id}/candidates/{candidate.evidence_id}/review"
            )
            self.assertEqual(200, initial.status_code)
            self.assertEqual(0, initial.json()["revision"])

            included = client.post(
                f"/api/projects/{project_id}/evidence-design/packages/{package_id}/candidates/{candidate.evidence_id}/review-actions",
                json={"action": "include", "expected_revision": 0, "idempotency_key": "api-include"},
            )
            self.assertEqual(200, included.status_code)
            self.assertEqual("已纳入", included.json()["screening_status"])

            mismatch = client.get(
                f"/api/projects/proj_mgk10_crswnp/evidence-design/packages/{package_id}/candidates/{candidate.evidence_id}/review"
            )
            self.assertEqual(404, mismatch.status_code)


if __name__ == "__main__":
    unittest.main()
