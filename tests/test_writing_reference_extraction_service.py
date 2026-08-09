from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.api.app.writing_reference import WritingReferenceExtractionService
from services.api.app.writing_reference_repository import WritingReferenceRepository
from tests.test_writing_reference_extraction import artifact, pdf_fixture
from tests.test_writing_reference_repository import PROJECT_ID, snapshot


class WritingReferenceExtractionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.artifact_root = root / "artifacts"
        self.repo = WritingReferenceRepository(root / "writing_reference.sqlite3")
        self.repo.save_search_snapshot(snapshot(), idempotency_key="search-001")
        payload = pdf_fixture()
        self.payload = payload
        self.artifact = artifact(hashlib.sha256(payload).hexdigest()).model_copy(
            update={"actual_size": len(payload)}
        )
        relative = "safe/wref_doc_extract_001/source.pdf"
        path = self.artifact_root / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        self.repo.save_document_artifact(
            self.artifact,
            storage_relpath=relative,
            idempotency_key="artifact-001",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_registered_document_extracts_without_a_security_scan_gate(self) -> None:
        service = WritingReferenceExtractionService(
            self.repo,
            artifact_root=self.artifact_root,
        )
        result = service.extract(
            PROJECT_ID,
            self.artifact.artifact_id,
            actor="medical_manager",
            extraction_idempotency_key="extract-001",
        )
        self.assertGreaterEqual(len(result.spans), 4)
        restarted = WritingReferenceRepository(Path(self.tmp.name) / "writing_reference.sqlite3")
        self.assertEqual(result.spans[0].source_text, restarted.source_span(PROJECT_ID, result.spans[0].span_id).source_text)

    def test_missing_registered_file_fails_without_creating_spans(self) -> None:
        (self.artifact_root / "safe/wref_doc_extract_001/source.pdf").unlink()
        service = WritingReferenceExtractionService(
            self.repo,
            artifact_root=self.artifact_root,
        )
        with self.assertRaisesRegex(RuntimeError, "artifact is unavailable"):
            service.extract(
                PROJECT_ID,
                self.artifact.artifact_id,
                actor="medical_manager",
                extraction_idempotency_key="extract-blocked",
            )
        with self.assertRaises(KeyError):
            self.repo.source_span(PROJECT_ID, "missing")

    def test_reextraction_refreshes_content_validation_lineage_without_approving_structure(self) -> None:
        service = WritingReferenceExtractionService(
            self.repo,
            artifact_root=self.artifact_root,
        )
        first = service.extract(
            PROJECT_ID,
            self.artifact.artifact_id,
            actor="medical_manager",
            extraction_idempotency_key="extract-v7-first",
        )
        first_validation = self.repo.document_validation(
            PROJECT_ID, self.artifact.artifact_id
        )

        with patch(
            "services.api.app.writing_reference.EXTRACTION_MAPPING_VERSION",
            "m11map_test_r2",
        ):
            second = service.extract(
                PROJECT_ID,
                self.artifact.artifact_id,
                actor="medical_manager",
                extraction_idempotency_key="extract-v7-second",
            )

        second_validation = self.repo.document_validation(
            PROJECT_ID, self.artifact.artifact_id
        )
        self.assertNotEqual(first.extraction_revision, second.extraction_revision)
        self.assertEqual(second.extraction_revision, second_validation.extraction_revision)
        self.assertEqual(first_validation.revision + 1, second_validation.revision)
        self.assertEqual(
            [],
            [
                review
                for review in self.repo.extraction_reviews(
                    PROJECT_ID, artifact_id=self.artifact.artifact_id
                )
                if review.extraction_revision == second.extraction_revision
            ],
        )


if __name__ == "__main__":
    unittest.main()
