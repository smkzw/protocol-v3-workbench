from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from packages.contracts.workbench_contracts import (
    WritingReferenceDocumentIngestRequest,
    WritingReferenceManualDocumentUploadRequest,
)
from services.api.app.writing_reference import (
    WritingReferenceDocumentService,
    WritingReferenceExtractionService,
    validate_manual_document_payload,
)
from services.api.app.writing_reference_repository import WritingReferenceRepository
from tests.test_writing_reference_extraction import pdf_fixture
from tests.test_writing_reference_repository import PROJECT_ID, snapshot


@dataclass(frozen=True)
class FakeBinaryResponse:
    payload: bytes
    final_url: str
    content_type: str


class FakeDocumentClient:
    def __init__(self, payload: bytes = b"%PDF-1.7\nbody"):
        self.payload = payload
        self.calls = 0

    def fetch_binary(self, url: str, *, accept: str) -> FakeBinaryResponse:
        self.calls += 1
        return FakeBinaryResponse(
            payload=self.payload,
            final_url=url,
            content_type="application/pdf",
        )


class WritingReferenceDocumentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = WritingReferenceRepository(root / "writing_reference.sqlite3")
        source_snapshot = snapshot()
        source_snapshot.candidates[0].public_documents[0] = (
            source_snapshot.candidates[0].public_documents[0].model_copy(
                update={"declared_size": 13}
            )
        )
        self.repo.save_search_snapshot(source_snapshot, idempotency_key="search-001")
        self.repo.record_relevance_decision(
            project_id=PROJECT_ID,
            snapshot_id="wref_search_001",
            nct_id="NCT05014438",
            relevance_status="direct_competitor",
            reason="同适应症同分期，具有直接方案参照价值。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="relevance-001",
        )
        self.client = FakeDocumentClient()
        self.service = WritingReferenceDocumentService(
            self.repo,
            self.client,
            artifact_root=root / "artifacts",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def request(self) -> WritingReferenceDocumentIngestRequest:
        return WritingReferenceDocumentIngestRequest(
            snapshot_id="wref_search_001",
            nct_id="NCT05014438",
            document_id="ctgov_NCT05014438_000",
            actor="medical_manager",
            idempotency_key="ingest-001",
        )

    def test_medically_selected_document_download_is_validated_persisted_and_replayable(self) -> None:
        artifact = self.service.ingest(PROJECT_ID, self.request())

        self.assertEqual("verified", artifact.file_integrity_status)
        self.assertEqual(13, artifact.actual_size)
        self.assertEqual(64, len(artifact.content_sha256))
        self.assertNotIn("/Users/", artifact.model_dump_json())
        self.assertEqual(1, len(list((Path(self.tmp.name) / "artifacts").rglob("*.pdf"))))

        replay = self.service.ingest(PROJECT_ID, self.request())
        self.assertEqual(artifact.model_dump(), replay.model_dump())
        self.assertEqual(1, self.client.calls)

        restarted = WritingReferenceRepository(Path(self.tmp.name) / "writing_reference.sqlite3")
        self.assertEqual(
            artifact.model_dump(),
            restarted.document_artifact(PROJECT_ID, artifact.artifact_id).model_dump(),
        )

    def test_invalid_pdf_and_unreviewed_candidate_fail_without_artifact(self) -> None:
        bad_service = WritingReferenceDocumentService(
            self.repo,
            FakeDocumentClient(payload=b"<html>bad</html>"),
            artifact_root=Path(self.tmp.name) / "bad-artifacts",
        )
        with self.assertRaisesRegex(RuntimeError, "PDF validation failed"):
            bad_service.ingest(PROJECT_ID, self.request().model_copy(update={"idempotency_key": "bad-001"}))
        self.assertEqual([], list((Path(self.tmp.name) / "bad-artifacts").rglob("*.pdf")))

    def manual_request(self) -> WritingReferenceManualDocumentUploadRequest:
        return WritingReferenceManualDocumentUploadRequest(
            snapshot_id="wref_search_001",
            nct_id="NCT05014438",
            document_type="protocol",
            document_date="2026-06-30",
            actor="medical_manager",
            idempotency_key="manual-upload-001",
        )

    def test_manual_pdf_upload_is_hash_bound_replayable_and_enters_shared_validation_flow(self) -> None:
        payload = pdf_fixture()
        artifact = self.service.ingest_manual(
            PROJECT_ID,
            self.manual_request(),
            filename="AD_phase2_protocol.pdf",
            content_type="application/pdf",
            payload=payload,
        )

        self.assertEqual("user_uploaded", artifact.source_status)
        self.assertEqual("protocol", artifact.document_type)
        self.assertEqual(len(payload), artifact.actual_size)
        self.assertTrue(artifact.source_document_id.startswith("manual_"))
        self.assertTrue(artifact.requested_url.startswith("manual-upload:manual_"))
        self.assertNotIn("/Users/", artifact.model_dump_json())
        relative = self.repo.artifact_storage_relpath(PROJECT_ID, artifact.artifact_id)
        self.assertEqual(payload, (Path(self.tmp.name) / "artifacts" / relative).read_bytes())

        replay = self.service.ingest_manual(
            PROJECT_ID,
            self.manual_request(),
            filename="AD_phase2_protocol.pdf",
            content_type="application/pdf",
            payload=payload,
        )
        self.assertEqual(artifact.model_dump(), replay.model_dump())

        extraction = WritingReferenceExtractionService(
            self.repo,
            artifact_root=Path(self.tmp.name) / "artifacts",
        ).extract(
            PROJECT_ID,
            artifact.artifact_id,
            actor="medical_manager",
            extraction_idempotency_key="manual-extract-001",
        )
        self.assertGreater(len(extraction.spans), 0)
        self.assertTrue(all(span.source_locator.startswith("upload:") for span in extraction.spans))
        validation = self.repo.document_validation(PROJECT_ID, artifact.artifact_id)
        self.assertIn(validation.status, {"confirmed", "needs_review", "mismatch"})
        source_check = next(check for check in validation.checks if check.check_code == "source_metadata")
        self.assertEqual("match", source_check.outcome)
        self.assertIn("医学经理手动上传", source_check.observed_value)

    def test_manual_upload_rejects_path_names_disguised_files_unsupported_types_and_unretained_candidates(self) -> None:
        payload = pdf_fixture()
        invalid_cases = (
            ("../protocol.pdf", "application/pdf", payload, "plain PDF or DOCX filename"),
            ("protocol.pdf", "application/pdf", b"not a pdf", "content is not a PDF"),
            ("protocol.txt", "text/plain", b"plain text", "only PDF and DOCX"),
            ("protocol.pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", payload, "does not match"),
        )
        for filename, content_type, invalid_payload, message in invalid_cases:
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(ValueError, message):
                    validate_manual_document_payload(
                        filename=filename,
                        content_type=content_type,
                        payload=invalid_payload,
                    )

        self.repo.record_relevance_decision(
            project_id=PROJECT_ID,
            snapshot_id="wref_search_001",
            nct_id="NCT05014438",
            relevance_status="excluded",
            reason="医学复核后确认不作为当前项目竞品或间接参照。",
            actor="medical_manager",
            expected_revision=1,
            idempotency_key="relevance-excluded-manual-upload",
        )
        with self.assertRaisesRegex(ValueError, "not approved"):
            self.service.ingest_manual(
                PROJECT_ID,
                self.manual_request().model_copy(update={"idempotency_key": "manual-upload-excluded"}),
                filename="protocol.pdf",
                content_type="application/pdf",
                payload=payload,
            )

    def test_concurrent_manual_uploads_return_one_registered_artifact_and_keep_its_file(self) -> None:
        payload = pdf_fixture()

        def upload(_: int):
            return self.service.ingest_manual(
                PROJECT_ID,
                self.manual_request(),
                filename="AD_phase2_protocol.pdf",
                content_type="application/pdf",
                payload=payload,
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            artifacts = list(pool.map(upload, range(8)))

        self.assertEqual(1, len({item.artifact_id for item in artifacts}))
        stored = self.repo.document_artifact(PROJECT_ID, artifacts[0].artifact_id)
        relative = self.repo.artifact_storage_relpath(PROJECT_ID, stored.artifact_id)
        output_path = Path(self.tmp.name) / "artifacts" / relative
        self.assertTrue(output_path.is_file())
        self.assertEqual(payload, output_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
