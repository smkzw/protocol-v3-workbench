from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.api.app.main import app
from services.api.app.writing_reference import (
    WritingReferenceDiscoveryService,
    WritingReferenceDocumentService,
    WritingReferenceExtractionService,
    extract_pdf_sections,
)
from services.api.app.writing_reference_repository import WritingReferenceRepository
from tests.test_writing_reference_discovery_service import FakeCtgovClient, NOW
from tests.test_writing_reference_document_service import FakeDocumentClient
from tests.test_writing_reference_extraction import artifact, pdf_fixture
from tests.test_writing_reference_repository import (
    seed_two_extraction_revisions,
    snapshot,
)


class WritingReferenceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = WritingReferenceRepository(Path(self.tmp.name) / "writing_reference.sqlite3")
        self.service = WritingReferenceDiscoveryService(
            self.repo,
            FakeCtgovClient(),
            clock=lambda: NOW,
        )
        self.document_service = WritingReferenceDocumentService(
            self.repo,
            FakeDocumentClient(payload=b"%PDF-" + b"0" * 1019),
            artifact_root=Path(self.tmp.name) / "artifacts",
            clock=lambda: NOW,
        )
        self.extraction_service = WritingReferenceExtractionService(
            self.repo,
            artifact_root=Path(self.tmp.name) / "artifacts",
        )
        self.client = TestClient(app)
        self.patches = [
            patch("services.api.app.main.writing_reference_repository", self.repo),
            patch("services.api.app.main.writing_reference_discovery_service", self.service),
            patch("services.api.app.main.writing_reference_document_service", self.document_service),
            patch("services.api.app.main.writing_reference_extraction_service", self.extraction_service),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_discovery_and_medical_relevance_endpoints_form_usable_first_flow(self) -> None:
        empty_workspace = self.client.get(
            "/api/projects/proj_rux_03_002/medical-writing/references/workspace"
        )
        self.assertEqual(200, empty_workspace.status_code, empty_workspace.text)
        self.assertFalse(empty_workspace.json()["initialized"])
        self.assertEqual([], empty_workspace.json()["extraction_reviews"])
        self.assertEqual([], empty_workspace.json()["medical_reviews"])
        self.assertEqual([], empty_workspace.json()["evidence_brief_history"])
        self.assertEqual({}, empty_workspace.json()["artifact_span_counts"])

        response = self.client.post(
            "/api/projects/proj_rux_03_002/medical-writing/references/search-snapshots",
            json={
                "search": {
                    "indication": "Atopic Dermatitis",
                    "phases": ["PHASE2"],
                    "study_type": "INTERVENTIONAL",
                    "page_size": 100,
                },
                "actor": "medical_manager",
                "idempotency_key": "api-search-ad-phase2",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        snapshot = response.json()
        self.assertEqual(2, snapshot["returned_count"])
        self.assertEqual("pending_medical_relevance", snapshot["candidates"][0]["relevance_status"])
        self.assertNotIn("/Users/", json.dumps(snapshot, ensure_ascii=False))

        get_response = self.client.get(
            f"/api/projects/proj_rux_03_002/medical-writing/references/search-snapshots/{snapshot['snapshot_id']}"
        )
        self.assertEqual(200, get_response.status_code, get_response.text)
        self.assertEqual(snapshot, get_response.json())

        decision = self.client.post(
            f"/api/projects/proj_rux_03_002/medical-writing/references/search-snapshots/{snapshot['snapshot_id']}/relevance-decisions",
            json={
                "nct_id": "NCT05014438",
                "relevance_status": "direct_competitor",
                "reason": "同适应症、同分期，方案设计具有直接参照价值。",
                "actor": "medical_manager",
                "expected_revision": 0,
                "idempotency_key": "api-relevance-001",
            },
        )
        self.assertEqual(200, decision.status_code, decision.text)
        self.assertEqual("direct_competitor", decision.json()["relevance_status"])
        self.assertEqual(1, decision.json()["revision"])

        ingest = self.client.post(
            "/api/projects/proj_rux_03_002/medical-writing/references/documents/ingest",
            json={
                "snapshot_id": snapshot["snapshot_id"],
                "nct_id": "NCT05014438",
                "document_id": "ctgov_NCT05014438_000",
                "actor": "medical_manager",
                "idempotency_key": "api-ingest-001",
            },
        )
        self.assertEqual(200, ingest.status_code, ingest.text)
        self.assertEqual("verified", ingest.json()["file_integrity_status"])
        self.assertNotIn("/Users/", ingest.text)

        workspace = self.client.get(
            "/api/projects/proj_rux_03_002/medical-writing/references/workspace"
        )
        self.assertEqual(200, workspace.status_code, workspace.text)
        self.assertTrue(workspace.json()["initialized"])
        self.assertEqual(2, len(workspace.json()["snapshot"]["candidates"]))
        self.assertEqual(1, len(workspace.json()["decisions"]))
        self.assertEqual(1, len(workspace.json()["artifacts"]))
        self.assertTrue(workspace.json()["artifacts"][0]["source_current"])
        self.assertEqual(1, workspace.json()["artifacts"][0]["state_revision"])
        self.assertEqual([], workspace.json()["medical_reviews"])
        self.assertEqual([], workspace.json()["evidence_brief_history"])

    def test_manual_protocol_upload_endpoint_reuses_artifact_extraction_and_content_validation_contracts(self) -> None:
        source_snapshot = snapshot()
        self.repo.save_search_snapshot(
            source_snapshot,
            idempotency_key="api-manual-upload-snapshot",
        )
        self.repo.record_relevance_decision(
            project_id="proj_rux_03_002",
            snapshot_id=source_snapshot.snapshot_id,
            nct_id="NCT05014438",
            relevance_status="direct_competitor",
            reason="同适应症、同分期，用户上传的完整方案具有直接参照价值。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="api-manual-upload-relevance",
        )
        payload = pdf_fixture()

        upload = self.client.post(
            "/api/projects/proj_rux_03_002/medical-writing/references/documents/upload",
            data={
                "snapshot_id": source_snapshot.snapshot_id,
                "nct_id": "NCT05014438",
                "document_type": "protocol",
                "document_date": "2026-06-30",
                "actor": "medical_manager",
                "idempotency_key": "api-manual-upload-001",
            },
            files={"file": ("AD_phase2_protocol.pdf", payload, "application/pdf")},
        )

        self.assertEqual(200, upload.status_code, upload.text)
        artifact_payload = upload.json()
        self.assertEqual("user_uploaded", artifact_payload["source_status"])
        self.assertEqual("protocol", artifact_payload["document_type"])
        self.assertTrue(artifact_payload["source_document_id"].startswith("manual_"))
        self.assertNotIn("/Users/", upload.text)

        extract = self.client.post(
            "/api/projects/proj_rux_03_002/medical-writing/references/documents/"
            f"{artifact_payload['artifact_id']}/extract",
            json={
                "actor": "medical_manager",
                "extraction_idempotency_key": "api-manual-extract-001",
            },
        )
        self.assertEqual(200, extract.status_code, extract.text)
        self.assertGreater(len(extract.json()["spans"]), 0)
        self.assertTrue(
            all(item["source_locator"].startswith("upload:") for item in extract.json()["spans"])
        )

        workspace = self.client.get(
            "/api/projects/proj_rux_03_002/medical-writing/references/workspace",
            params={"snapshot_id": source_snapshot.snapshot_id},
        )
        self.assertEqual(200, workspace.status_code, workspace.text)
        manual_artifact = next(
            item for item in workspace.json()["artifacts"]
            if item["artifact_id"] == artifact_payload["artifact_id"]
        )
        self.assertEqual("user_uploaded", manual_artifact["source_status"])
        validation = next(
            item for item in workspace.json()["document_validations"]
            if item["artifact_id"] == artifact_payload["artifact_id"]
        )
        self.assertIn(validation["status"], {"confirmed", "needs_review", "mismatch"})

        invalid_type = self.client.post(
            "/api/projects/proj_rux_03_002/medical-writing/references/documents/upload",
            data={
                "snapshot_id": source_snapshot.snapshot_id,
                "nct_id": "NCT05014438",
                "document_type": "publication",
                "actor": "medical_manager",
                "idempotency_key": "api-manual-upload-invalid-type",
            },
            files={"file": ("publication.pdf", payload, "application/pdf")},
        )
        self.assertEqual(422, invalid_type.status_code, invalid_type.text)

        disguised = self.client.post(
            "/api/projects/proj_rux_03_002/medical-writing/references/documents/upload",
            data={
                "snapshot_id": source_snapshot.snapshot_id,
                "nct_id": "NCT05014438",
                "document_type": "protocol",
                "actor": "medical_manager",
                "idempotency_key": "api-manual-upload-disguised",
            },
            files={"file": ("protocol.pdf", b"not-a-pdf", "application/pdf")},
        )
        self.assertEqual(422, disguised.status_code, disguised.text)

    def test_workspace_snapshot_query_returns_the_exact_bound_snapshot_not_latest(self) -> None:
        project_id = "proj_rux_03_002"
        old_response = self.client.post(
            f"/api/projects/{project_id}/medical-writing/references/search-snapshots",
            json={
                "search": {
                    "indication": "Atopic Dermatitis",
                    "phases": ["PHASE2"],
                    "study_type": "INTERVENTIONAL",
                    "page_size": 100,
                },
                "actor": "medical_manager",
                "idempotency_key": "api-bound-snapshot-old",
            },
        )
        self.assertEqual(200, old_response.status_code, old_response.text)
        old_snapshot = old_response.json()
        old_decision = self.client.post(
            f"/api/projects/{project_id}/medical-writing/references/search-snapshots/"
            f"{old_snapshot['snapshot_id']}/relevance-decisions",
            json={
                "nct_id": "NCT05014438",
                "relevance_status": "direct_competitor",
                "reason": "旧建项快照中已完成医学分诊，必须随绑定快照精确恢复。",
                "actor": "medical_manager",
                "expected_revision": 0,
                "idempotency_key": "api-bound-snapshot-old-decision",
            },
        )
        self.assertEqual(200, old_decision.status_code, old_decision.text)

        self.service.clock = lambda: NOW + timedelta(minutes=1)
        latest_response = self.client.post(
            f"/api/projects/{project_id}/medical-writing/references/search-snapshots",
            json={
                "search": {
                    "indication": "Psoriasis",
                    "phases": ["PHASE3"],
                    "study_type": "INTERVENTIONAL",
                    "page_size": 100,
                },
                "actor": "medical_manager",
                "idempotency_key": "api-bound-snapshot-latest",
            },
        )
        self.assertEqual(200, latest_response.status_code, latest_response.text)
        latest_snapshot = latest_response.json()
        self.assertNotEqual(old_snapshot["snapshot_id"], latest_snapshot["snapshot_id"])
        latest_decision = self.client.post(
            f"/api/projects/{project_id}/medical-writing/references/search-snapshots/"
            f"{latest_snapshot['snapshot_id']}/relevance-decisions",
            json={
                "nct_id": "NCT05014438",
                "relevance_status": "excluded",
                "reason": "新快照中的分诊结论不得覆盖旧建项快照的既有结论。",
                "actor": "medical_manager",
                "expected_revision": 0,
                "idempotency_key": "api-bound-snapshot-latest-decision",
            },
        )
        self.assertEqual(200, latest_decision.status_code, latest_decision.text)

        default_workspace = self.client.get(
            f"/api/projects/{project_id}/medical-writing/references/workspace"
        )
        self.assertEqual(200, default_workspace.status_code, default_workspace.text)
        self.assertEqual(
            latest_snapshot["snapshot_id"],
            default_workspace.json()["snapshot"]["snapshot_id"],
        )
        self.assertEqual(
            "excluded",
            default_workspace.json()["decisions"][0]["relevance_status"],
        )

        with patch.object(
            self.repo,
            "source_span_counts",
            wraps=self.repo.source_span_counts,
        ) as source_span_counts:
            bound_workspace = self.client.get(
                f"/api/projects/{project_id}/medical-writing/references/workspace",
                params={"snapshot_id": old_snapshot["snapshot_id"]},
            )
        source_span_counts.assert_called_once_with(
            project_id,
            snapshot_id=old_snapshot["snapshot_id"],
        )
        self.assertEqual(200, bound_workspace.status_code, bound_workspace.text)
        payload = bound_workspace.json()
        self.assertTrue(payload["initialized"])
        self.assertEqual(old_snapshot["snapshot_id"], payload["snapshot"]["snapshot_id"])
        self.assertEqual("Atopic Dermatitis", payload["snapshot"]["request"]["indication"])
        self.assertEqual(["PHASE2"], payload["snapshot"]["request"]["phases"])
        self.assertEqual(1, len(payload["decisions"]))
        self.assertEqual("direct_competitor", payload["decisions"][0]["relevance_status"])

    def test_extraction_review_endpoint_persists_current_structure_decision_in_workspace(self) -> None:
        source_snapshot = snapshot()
        self.repo.save_search_snapshot(
            source_snapshot,
            idempotency_key="api-extraction-review-snapshot",
        )
        pdf = pdf_fixture()
        source_artifact = artifact(hashlib.sha256(pdf).hexdigest()).model_copy(
            update={"actual_size": len(pdf)}
        )
        self.repo.save_document_artifact(
            source_artifact,
            storage_relpath="fixtures/wref_doc_extract_001/source.pdf",
            idempotency_key="api-extraction-review-artifact",
        )
        extraction = extract_pdf_sections(pdf, source_artifact)
        self.repo.save_extraction(
            extraction,
            idempotency_key="api-extraction-review-extraction",
        )
        mapped_anchors = sorted(
            {
                span.ich_m11_anchor
                for span in extraction.spans
                if span.ich_m11_anchor and span.ich_m11_anchor != "unmapped"
            }
        )

        response = self.client.post(
            "/api/projects/proj_rux_03_002/medical-writing/references/documents/"
            f"{source_artifact.artifact_id}/extraction-reviews",
            json={
                "extraction_revision": extraction.extraction_revision,
                "decision": "approved",
                "confirmed_anchor_coverage": mapped_anchors,
                "unresolved_structure_issues": [],
                "comment": "已核对目标终点与统计章节，结构抽取完整，可进入翻译审核。",
                "actor": "medical_manager",
                "expected_revision": 0,
                "idempotency_key": "api-extraction-review-approved",
            },
        )

        self.assertEqual(200, response.status_code, response.text)
        review = response.json()
        self.assertEqual(source_artifact.artifact_id, review["artifact_id"])
        self.assertEqual(extraction.extraction_revision, review["extraction_revision"])
        self.assertEqual("approved", review["decision"])
        self.assertEqual(mapped_anchors, review["confirmed_anchor_coverage"])
        self.assertEqual(1, review["revision"])

        workspace = self.client.get(
            "/api/projects/proj_rux_03_002/medical-writing/references/workspace",
            params={"snapshot_id": source_snapshot.snapshot_id},
        )
        self.assertEqual(200, workspace.status_code, workspace.text)
        self.assertEqual([review], workspace.json()["extraction_reviews"])

    def test_spans_endpoint_defaults_to_latest_and_keeps_old_revision_auditable(self) -> None:
        source_artifact, old_revision, latest_revision = seed_two_extraction_revisions(
            self.repo
        )
        route = (
            "/api/projects/proj_rux_03_002/medical-writing/references/documents/"
            f"{source_artifact.artifact_id}/spans"
        )

        latest_response = self.client.get(route)
        self.assertEqual(200, latest_response.status_code, latest_response.text)
        latest_payload = latest_response.json()
        self.assertEqual(
            latest_revision.extraction_revision,
            latest_payload["extraction_revision"],
        )
        self.assertEqual(len(latest_revision.spans), latest_payload["total"])
        self.assertEqual(
            {span.span_id for span in latest_revision.spans},
            {span["span_id"] for span in latest_payload["items"]},
        )

        old_response = self.client.get(
            route,
            params={"extraction_revision": old_revision.extraction_revision},
        )
        self.assertEqual(200, old_response.status_code, old_response.text)
        old_payload = old_response.json()
        self.assertEqual(old_revision.extraction_revision, old_payload["extraction_revision"])
        self.assertEqual(len(old_revision.spans), old_payload["total"])
        self.assertEqual(
            {span.span_id for span in old_revision.spans},
            {span["span_id"] for span in old_payload["items"]},
        )

        anchor = latest_revision.spans[0].ich_m11_anchor
        filtered_response = self.client.get(
            route,
            params={"ich_m11_anchor": anchor},
        )
        self.assertEqual(200, filtered_response.status_code, filtered_response.text)
        filtered_payload = filtered_response.json()
        expected_anchor_counts = {
            item: sum(span.ich_m11_anchor == item for span in latest_revision.spans)
            for item in sorted({span.ich_m11_anchor for span in latest_revision.spans})
        }
        self.assertEqual(expected_anchor_counts, filtered_payload["anchor_counts"])
        self.assertEqual(expected_anchor_counts[anchor], filtered_payload["total"])
        self.assertTrue(
            all(item["ich_m11_anchor"] == anchor for item in filtered_payload["items"])
        )

        workspace = self.client.get(
            "/api/projects/proj_rux_03_002/medical-writing/references/workspace",
            params={"snapshot_id": snapshot().snapshot_id},
        )
        self.assertEqual(200, workspace.status_code, workspace.text)
        self.assertEqual(
            {source_artifact.artifact_id: len(latest_revision.spans)},
            workspace.json()["artifact_span_counts"],
        )

    def test_invalid_relevance_and_unknown_snapshot_fail_closed(self) -> None:
        missing = self.client.get(
            "/api/projects/proj_rux_03_002/medical-writing/references/search-snapshots/missing"
        )
        self.assertEqual(404, missing.status_code)


if __name__ == "__main__":
    unittest.main()
