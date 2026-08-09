from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts import (
    MedicalWritingDocumentPreview,
    MedicalWritingPreviewPage,
    ProtocolDocument,
    ProtocolSection,
)
from services.api.app import main as app_main
from services.api.app.medical_writing_document_exporter import (
    build_medical_writing_fast_preview,
    medical_writing_document_export_snapshot_digest,
)


def _document(*, long_body: bool = False) -> ProtocolDocument:
    body = "临床研究正文。" * (900 if long_body else 2)
    return ProtocolDocument(
        document_id="doc_fast_preview",
        project_id="proj_fast_preview",
        protocol_id="MW-FAST-PREVIEW",
        version="V0.1",
        sections=[
            ProtocolSection(
                section_id="section_design",
                document_id="doc_fast_preview",
                heading="研究设计",
                section_number="1",
                content_blocks=[
                    {
                        "block_id": "heading_design",
                        "block_type": "heading",
                        "outline_level": 0,
                        "body_order": 0,
                        "text": "1 研究设计",
                    },
                    {
                        "block_id": "paragraph_design",
                        "block_type": "paragraph",
                        "body_order": 1,
                        "text": body,
                    },
                    {
                        "block_id": "paragraph_break",
                        "block_type": "paragraph",
                        "body_order": 2,
                        "page_break_before": True,
                        "text": "分页后的正文。",
                    },
                ],
            )
        ],
    )


def test_fast_preview_is_deterministic_and_binds_export_snapshot():
    document = _document(long_body=True)
    first = build_medical_writing_fast_preview(document)
    second = build_medical_writing_fast_preview(document)

    expected_digest = medical_writing_document_export_snapshot_digest(document)
    assert first.model_dump() == second.model_dump()
    assert first.snapshot_sha256 == expected_digest
    assert first.preview_status == "fast_preview"
    assert first.page_count_basis == "style_profile_estimate"
    assert "不等同于 DOCX/ Microsoft Word 原生页数" in first.warning
    assert first.page_count == len(first.pages) >= 2
    assert [page.page_number for page in first.pages] == list(
        range(1, first.page_count + 1)
    )
    assert first.blocks[0].page_start == 1
    assert first.blocks[-1].page_start > first.blocks[0].page_start


def test_fast_preview_digest_changes_with_source_and_preserves_locators():
    document = _document()
    original = build_medical_writing_fast_preview(document)
    changed = document.model_copy(deep=True)
    changed.sections[0].content_blocks[1]["text"] += " 新增受试者安全性说明。"
    updated = build_medical_writing_fast_preview(changed)

    assert updated.snapshot_sha256 != original.snapshot_sha256
    assert [block.block_id for block in updated.blocks] == [
        "heading_design",
        "paragraph_design",
        "paragraph_break",
    ]
    assert all(block.section_id == "section_design" for block in updated.blocks)


def test_fast_preview_accepts_full_protocol_locator_density():
    sections = []
    for index in range(114):
        section_id = f"section_{index:03d}"
        sections.append(
            ProtocolSection(
                section_id=section_id,
                document_id="doc_dense_preview",
                heading=f"第{index + 1}节",
                section_number=str(index + 1),
                content_blocks=[
                    {
                        "block_id": f"heading_{index:03d}",
                        "block_type": "heading",
                        "outline_level": 0,
                        "body_order": 0,
                        "text": f"第{index + 1}节",
                    },
                    {
                        "block_id": f"body_{index:03d}",
                        "block_type": "paragraph",
                        "body_order": 1,
                        "text": "短正文。",
                    },
                ],
            )
        )
    document = ProtocolDocument(
        document_id="doc_dense_preview",
        project_id="proj_dense_preview",
        protocol_id="MW-DENSE-PREVIEW",
        version="V0.1",
        sections=sections,
    )

    preview = build_medical_writing_fast_preview(document)

    assert preview.page_count >= 1
    assert max(len(page.section_ids) for page in preview.pages) > 100
    assert max(len(page.block_ids) for page in preview.pages) > 200


def test_word_verified_status_requires_exact_current_snapshot():
    page = MedicalWritingPreviewPage(
        page_number=1,
        orientation="portrait",
        width_twips=12240,
        height_twips=15840,
    )
    with pytest.raises(ValueError, match="word-verified preview"):
        MedicalWritingDocumentPreview(
            project_id="proj_fast_preview",
            document_id="doc_fast_preview",
            preview_status="word_verified",
            snapshot_sha256="a" * 64,
            word_verified_snapshot_sha256="b" * 64,
            page_count=1,
            pages=[page],
        )
    accepted = MedicalWritingDocumentPreview(
        project_id="proj_fast_preview",
        document_id="doc_fast_preview",
        preview_status="word_verified",
        snapshot_sha256="a" * 64,
        word_verified_snapshot_sha256="a" * 64,
        page_count_basis="microsoft_word_receipt",
        page_count=1,
        pages=[page],
    )
    assert accepted.preview_status == "word_verified"
    stale = MedicalWritingDocumentPreview(
        project_id="proj_fast_preview",
        document_id="doc_fast_preview",
        preview_status="stale",
        snapshot_sha256="a" * 64,
        word_verified_snapshot_sha256="b" * 64,
        page_count=1,
        pages=[page],
        warning="源文档已变化，必须重新执行 Word 验证。",
    )
    assert stale.preview_status == "stale"


def test_preview_page_count_basis_cannot_claim_word_without_receipt():
    page = MedicalWritingPreviewPage(
        page_number=1,
        orientation="portrait",
        width_twips=12240,
        height_twips=15840,
    )
    with pytest.raises(ValueError, match="Microsoft Word receipt"):
        MedicalWritingDocumentPreview(
            project_id="proj_fast_preview",
            document_id="doc_fast_preview",
            preview_status="word_verified",
            snapshot_sha256="a" * 64,
            word_verified_snapshot_sha256="a" * 64,
            page_count_basis="style_profile_estimate",
            page_count=1,
            pages=[page],
        )


def test_fast_preview_route_is_read_only_and_explicit_about_status():
    document = _document()
    prepared = {"exporter_document": document, "front_matter_overrides": {}}
    with (
        patch.object(
            app_main,
            "_canonical_module_project_id",
            return_value="proj_fast_preview",
        ),
        patch.object(
            app_main,
            "_verify_medical_writing_document_export",
            return_value={"project_id": "proj_fast_preview", "mode": "draft_preview"},
        ),
        patch.object(
            app_main,
            "_assemble_medical_writing_document_export",
            return_value={"document": document, "front_matter_overrides": {}},
        ),
        patch.object(
            app_main,
            "_process_medical_writing_document_export_sources",
            return_value=prepared,
        ),
    ):
        response = TestClient(app_main.app).get(
            "/api/projects/proj_fast_preview/medical-writing/document-preview"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["preview_status"] == "fast_preview"
    assert payload["page_count_basis"] == "style_profile_estimate"
    assert payload["snapshot_sha256"] == medical_writing_document_export_snapshot_digest(
        document
    )
    assert "不等同于 DOCX/ Microsoft Word 原生页数" in payload["warning"]
