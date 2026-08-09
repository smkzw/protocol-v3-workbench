from __future__ import annotations

import hashlib
from collections import Counter

from services.api.app.medical_writing_document import MedicalWritingDocumentService
from services.api.app.medical_writing_source_reference_reindex import (
    build_source_reference_manifest,
    decide_source_reference_reindex,
)


def _scan_read_only(project_id: str):
    source_path = MedicalWritingDocumentService().original_protocol_path(project_id)
    before = source_path.read_bytes()
    before_digest = hashlib.sha256(before).hexdigest()
    manifest = build_source_reference_manifest(before)
    decision = decide_source_reference_reindex(manifest)
    after_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert after_digest == before_digest
    return source_path, manifest, decision


def test_real_rux_reference_boundary_excludes_appendix_tables_and_reports_true_blockers():
    source_path, manifest, decision = _scan_read_only("proj_rux_03_002")

    assert source_path.name.endswith("V1.3-clean-20240814.docx")
    assert len(manifest.reference_groups) == 19
    assert [group.source_number for group in manifest.reference_groups] == list(
        range(1, 20)
    )
    assert len(manifest.citations) == 19
    assert Counter(item.binding_kind for item in manifest.citations) == {
        "manager_field": 18,
        "superscript": 1,
    }
    assert all(
        "/w:tbl[16]/" not in locator and "/w:tbl[17]/" not in locator
        for group in manifest.reference_groups
        for locator in group.locators
    )
    assert all(
        group.locators[0].startswith("/w:document/w:body/w:p[")
        for group in manifest.reference_groups
    )
    assert "duplicate_reference_number" not in {issue.code for issue in manifest.issues}
    assert "unsupported_citation_manager_field" not in {
        issue.code for issue in decision.issues
    }
    assert (
        Counter(issue.code for issue in manifest.issues)[
            "citation_manager_field_preserved"
        ]
        == 18
    )
    assert (
        Counter(issue.code for issue in manifest.issues)[
            "citation_manager_metadata_conflict"
        ]
        == 15
    )
    assert decision.action == "block"
    assert {issue.code for issue in decision.issues if issue.blocking} == {
        "citation_manager_rebind_required"
    }
    assert decision.number_mapping[-3:] == ((18, 17), (19, 18), (17, 19))
    assert decision.uncited_source_numbers == (17,)


def test_real_d001_reference_boundary_excludes_appendices_and_is_scan_safe():
    source_path, manifest, decision = _scan_read_only("proj_d001")

    assert source_path.name.endswith("v1.0-2025.12.21.docx")
    assert len(manifest.reference_groups) == 13
    assert [group.source_number for group in manifest.reference_groups] == list(
        range(1, 14)
    )
    assert len(manifest.citations) == 13
    assert {item.binding_kind for item in manifest.citations} == {"superscript"}
    assert all(
        "/w:tbl/" not in locator
        for group in manifest.reference_groups
        for locator in group.locators
    )
    assert "duplicate_reference_number" not in {issue.code for issue in manifest.issues}
    assert not [issue for issue in decision.issues if issue.blocking]
    assert decision.action == "apply"
    assert decision.number_mapping == tuple((number, number) for number in range(1, 14))
    assert decision.uncited_source_numbers == (13,)
