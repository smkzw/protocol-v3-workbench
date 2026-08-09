from __future__ import annotations

from datetime import datetime, timezone

import pytest

from packages.contracts.workbench_contracts import (
    MedicalWritingWordVerificationPage,
    MedicalWritingWordVerificationReceipt,
    ProtocolDocument,
    ProtocolSection,
    medical_writing_word_verification_manifest_sha256,
)
from services.api.app.medical_writing_document_exporter import (
    MedicalWritingDocumentDocxExportError,
    build_medical_writing_word_verified_preview,
    medical_writing_document_export_snapshot_digest,
)


def _document() -> ProtocolDocument:
    return ProtocolDocument(
        document_id="doc_word_receipt",
        project_id="proj_word_receipt",
        protocol_id="MW-WORD-RECEIPT",
        version="V0.1",
        sections=[
            ProtocolSection(
                section_id="section_one",
                document_id="doc_word_receipt",
                heading="研究设计",
                content_blocks=[
                    {
                        "block_id": "heading_one",
                        "block_type": "heading",
                        "text": "研究设计",
                        "body_order": 0,
                    },
                    {
                        "block_id": "paragraph_one",
                        "block_type": "paragraph",
                        "text": "Word receipt contract test.",
                        "body_order": 1,
                    },
                ],
            )
        ],
    )


def _receipt(document: ProtocolDocument, *, docx_sha256: str = "b" * 64):
    pages = [
        MedicalWritingWordVerificationPage(
            page_number=1,
            orientation="portrait",
            width_twips=12240,
            height_twips=15840,
            pdf_page_sha256="c" * 64,
            screenshot_sha256="d" * 64,
        ),
        MedicalWritingWordVerificationPage(
            page_number=2,
            orientation="portrait",
            width_twips=12240,
            height_twips=15840,
            pdf_page_sha256="e" * 64,
            screenshot_sha256="f" * 64,
            visual_qc_status="pass_with_notes",
            note="页脚域已更新并复核。",
        ),
    ]
    return MedicalWritingWordVerificationReceipt(
        verification_id="word-check-001",
        project_id=document.project_id,
        document_id=document.document_id,
        source_snapshot_sha256=medical_writing_document_export_snapshot_digest(document),
        docx_sha256=docx_sha256,
        pdf_sha256="1" * 64,
        page_count=2,
        page_evidence=pages,
        evidence_manifest_sha256=medical_writing_word_verification_manifest_sha256(
            pages,
            pdf_sha256="1" * 64,
        ),
        verifier_id="medical_manager",
        verifier_role="资深医学写作经理",
        verification_tool_version="Microsoft Word 16.x",
        verified_at=datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc),
        idempotency_key="word-check-001-idempotent",
    )


def test_receipt_promotes_only_exact_current_snapshot_and_docx_hash():
    document = _document()
    receipt = _receipt(document)
    preview = build_medical_writing_word_verified_preview(
        document,
        receipt,
        expected_docx_sha256="b" * 64,
    )

    assert preview.preview_status == "word_verified"
    assert preview.word_verified_snapshot_sha256 == preview.snapshot_sha256
    assert preview.page_count_basis == "microsoft_word_receipt"
    assert preview.page_count == 2
    assert all(page.estimated is False for page in preview.pages)
    assert preview.blocks == []
    assert "Microsoft Word/PDF" in preview.warning


def test_receipt_fails_closed_on_stale_snapshot_or_docx_mismatch():
    document = _document()
    receipt = _receipt(document)
    changed = document.model_copy(deep=True)
    changed.sections[0].content_blocks[1]["text"] = "changed source"
    with pytest.raises(MedicalWritingDocumentDocxExportError, match="stale"):
        build_medical_writing_word_verified_preview(
            changed,
            receipt,
            expected_docx_sha256="b" * 64,
        )
    with pytest.raises(MedicalWritingDocumentDocxExportError, match="DOCX hash"):
        build_medical_writing_word_verified_preview(
            document,
            receipt,
            expected_docx_sha256="a" * 64,
        )


def test_receipt_manifest_and_page_sequence_are_fail_closed():
    document = _document()
    receipt_payload = _receipt(document).model_dump(mode="python")
    receipt_payload["evidence_manifest_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="manifest"):
        MedicalWritingWordVerificationReceipt(**receipt_payload)

    receipt_payload = _receipt(document).model_dump(mode="python")
    receipt_payload["page_evidence"][1]["page_number"] = 3
    receipt_payload["evidence_manifest_sha256"] = medical_writing_word_verification_manifest_sha256(
        [MedicalWritingWordVerificationPage(**page) for page in receipt_payload["page_evidence"]],
        pdf_sha256=receipt_payload["pdf_sha256"],
    )
    with pytest.raises(ValueError, match="contiguous"):
        MedicalWritingWordVerificationReceipt(**receipt_payload)


def test_receipt_requires_timezone_aware_verification_time():
    document = _document()
    payload = _receipt(document).model_dump(mode="python")
    payload["verified_at"] = datetime(2026, 8, 2, 4, 0)
    with pytest.raises(ValueError, match="timezone"):
        MedicalWritingWordVerificationReceipt(**payload)
