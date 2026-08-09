from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from services.api.app import main as app_main
from services.api.app.medical_writing_document_export_jobs import (
    MedicalWritingDocumentExportArtifact,
)
from services.api.app.medical_writing_document_exporter import (
    medical_writing_document_export_snapshot_digest,
)
from services.api.app.medical_writing_word_verification_repository import (
    MedicalWritingWordVerificationRepository,
)
from packages.contracts.workbench_contracts import (
    MedicalWritingWordVerificationPage,
    MedicalWritingWordVerificationReceipt,
    medical_writing_word_verification_manifest_sha256,
)
from services.api.app.medical_writing_pdf_page_hash import canonical_pdf_page_hashes
from services.api.app.medical_writing_document_exporter import MedicalWritingDocumentDocxExportError
from tests.test_medical_writing_pdf_page_hash import _pdf_bytes
from tests.test_medical_writing_word_verification import _document, _receipt


def _canonical_receipt(document):
    pdf_bytes = _pdf_bytes()
    canonical_pages = canonical_pdf_page_hashes(pdf_bytes)
    payload = _receipt(document).model_dump(mode="python")
    payload["pdf_sha256"] = hashlib.sha256(pdf_bytes).hexdigest()
    for page_payload, canonical_page in zip(
        payload["page_evidence"], canonical_pages
    ):
        page_payload["pdf_page_sha256"] = canonical_page.pdf_page_sha256
    page_models = [
        MedicalWritingWordVerificationPage(**page_payload)
        for page_payload in payload["page_evidence"]
    ]
    payload["evidence_manifest_sha256"] = medical_writing_word_verification_manifest_sha256(
        page_models,
        pdf_sha256=payload["pdf_sha256"],
    )
    return MedicalWritingWordVerificationReceipt(**payload), pdf_bytes


def test_word_verification_route_binds_receipt_to_completed_docx_job(tmp_path: Path):
    document = _document()
    receipt, pdf_bytes = _canonical_receipt(document)
    repository = MedicalWritingWordVerificationRepository(tmp_path / "receipts.sqlite3")
    artifact = MedicalWritingDocumentExportArtifact(
        job_id="job-word-001",
        project_id=document.project_id,
        path=tmp_path / "document.docx",
        filename="document.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        sha256=receipt.docx_sha256,
        size_bytes=123,
        metadata={
            "document_id": document.document_id,
            "project_id": document.project_id,
            "mode": "draft_preview",
            "source_snapshot_sha256": medical_writing_document_export_snapshot_digest(
                document
            ),
            "docx_sha256": receipt.docx_sha256,
        },
    )
    prepared = {"exporter_document": document, "front_matter_overrides": {}}
    with (
        patch.object(app_main, "_canonical_module_project_id", return_value=document.project_id),
        patch.object(
            app_main.medical_writing_document_export_job_service,
            "read_artifact",
            return_value=artifact,
        ),
        patch.object(
            app_main,
            "_verify_medical_writing_document_export",
            return_value={"project_id": document.project_id, "mode": "draft_preview"},
        ),
        patch.object(app_main, "_assemble_medical_writing_document_export", return_value={"document": document, "front_matter_overrides": {}}),
        patch.object(app_main, "_process_medical_writing_document_export_sources", return_value=prepared),
        patch.object(app_main, "_medical_writing_word_verification_repository", return_value=repository),
    ):
        response = TestClient(app_main.app).post(
            f"/api/projects/{document.project_id}/medical-writing/document-preview/word-verification",
                json={
                    "export_job_id": artifact.job_id,
                    "receipt": receipt.model_dump(mode="json"),
                    "actor": "medical_manager",
                    "canonical_pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["preview"]["preview_status"] == "word_verified"
    assert payload["receipt"]["verification_id"] == receipt.verification_id
    assert payload["replayed"] is False
    assert payload["canonical_pdf_page_hash"]["contract"] == (
        "medical_writing_pdf_page_hash_v1"
    )
    assert payload["canonical_pdf_page_hash"]["renderer_version"] == "5.12.1"
    audit = repository.audit_events(document.project_id, document.document_id)
    assert audit[0]["detail"]["canonical_pdf_page_hash"]["page_count"] == 2
    with (
        patch.object(app_main, "_canonical_module_project_id", return_value=document.project_id),
        patch.object(
            app_main.medical_writing_document_export_job_service,
            "read_artifact",
            return_value=artifact,
        ),
        patch.object(
            app_main,
            "_verify_medical_writing_document_export",
            return_value={"project_id": document.project_id, "mode": "draft_preview"},
        ),
        patch.object(app_main, "_assemble_medical_writing_document_export", return_value={"document": document, "front_matter_overrides": {}}),
        patch.object(app_main, "_process_medical_writing_document_export_sources", return_value=prepared),
        patch.object(app_main, "_medical_writing_word_verification_repository", return_value=repository),
    ):
        replay = TestClient(app_main.app).post(
            f"/api/projects/{document.project_id}/medical-writing/document-preview/word-verification",
                json={
                    "export_job_id": artifact.job_id,
                    "receipt": receipt.model_dump(mode="json"),
                    "actor": "medical_manager",
                    "canonical_pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                },
        )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True


def test_word_verification_route_fails_closed_without_canonical_pdf(tmp_path: Path):
    document = _document()
    receipt, _pdf_bytes_value = _canonical_receipt(document)
    repository = MedicalWritingWordVerificationRepository(tmp_path / "receipts.sqlite3")
    artifact = MedicalWritingDocumentExportArtifact(
        job_id="job-word-no-pdf",
        project_id=document.project_id,
        path=tmp_path / "document.docx",
        filename="document.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        sha256=receipt.docx_sha256,
        size_bytes=123,
        metadata={
            "document_id": document.document_id,
            "project_id": document.project_id,
            "mode": "draft_preview",
            "source_snapshot_sha256": medical_writing_document_export_snapshot_digest(document),
            "docx_sha256": receipt.docx_sha256,
        },
    )
    prepared = {"exporter_document": document, "front_matter_overrides": {}}
    with (
        patch.object(app_main, "_canonical_module_project_id", return_value=document.project_id),
        patch.object(app_main.medical_writing_document_export_job_service, "read_artifact", return_value=artifact),
        patch.object(app_main, "_verify_medical_writing_document_export", return_value={"project_id": document.project_id, "mode": "draft_preview"}),
        patch.object(app_main, "_assemble_medical_writing_document_export", return_value={"document": document, "front_matter_overrides": {}}),
        patch.object(app_main, "_process_medical_writing_document_export_sources", return_value=prepared),
        patch.object(app_main, "_medical_writing_word_verification_repository", return_value=repository),
    ):
        response = TestClient(app_main.app).post(
            f"/api/projects/{document.project_id}/medical-writing/document-preview/word-verification",
            json={
                "export_job_id": artifact.job_id,
                "receipt": receipt.model_dump(mode="json"),
                "actor": "medical_manager",
            },
        )
    assert response.status_code == 422
    assert "canonical PDF" in response.json()["detail"]
    assert repository.audit_events(document.project_id, document.document_id) == []


def test_canonical_pdf_evidence_rejects_hash_mismatch():
    document = _document()
    receipt, _pdf_bytes_value = _canonical_receipt(document)
    with pytest.raises(MedicalWritingDocumentDocxExportError, match="does not match"):
        app_main._verify_canonical_pdf_page_evidence(
            receipt,
            base64.b64encode(b"not-a-pdf").decode("ascii"),
        )


def test_word_verification_route_rejects_receipt_for_changed_snapshot(tmp_path: Path):
    document = _document()
    receipt = _receipt(document).model_copy(update={"source_snapshot_sha256": "a" * 64})
    artifact = MedicalWritingDocumentExportArtifact(
        job_id="job-word-stale",
        project_id=document.project_id,
        path=tmp_path / "document.docx",
        filename="document.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        sha256="b" * 64,
        size_bytes=1,
        metadata={
            "document_id": document.document_id,
            "project_id": document.project_id,
            "mode": "draft_preview",
            "source_snapshot_sha256": medical_writing_document_export_snapshot_digest(document),
            "docx_sha256": "b" * 64,
        },
    )
    prepared = {"exporter_document": document, "front_matter_overrides": {}}
    with (
        patch.object(app_main, "_canonical_module_project_id", return_value=document.project_id),
        patch.object(app_main.medical_writing_document_export_job_service, "read_artifact", return_value=artifact),
        patch.object(app_main, "_verify_medical_writing_document_export", return_value={"project_id": document.project_id, "mode": "draft_preview"}),
        patch.object(app_main, "_assemble_medical_writing_document_export", return_value={"document": document, "front_matter_overrides": {}}),
        patch.object(app_main, "_process_medical_writing_document_export_sources", return_value=prepared),
    ):
        response = TestClient(app_main.app).post(
            f"/api/projects/{document.project_id}/medical-writing/document-preview/word-verification",
            json={
                "export_job_id": artifact.job_id,
                "receipt": receipt.model_dump(mode="json"),
                "actor": "medical_manager",
            },
        )
    assert response.status_code == 422
    assert "stale" in response.json()["detail"]
