from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from pocs.protocol_v3.word_receipt.contract import (
    ReceiptContractError,
    assert_receipt_current,
    compute_idempotency_key,
    compute_receipt_id,
    receipt_staleness,
    validate_receipt,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures.json"


@pytest.fixture()
def payload() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


@pytest.fixture()
def receipt(payload: dict) -> dict:
    return deepcopy(payload["valid_receipt"])


def _rebind_identity(receipt: dict) -> None:
    key = compute_idempotency_key(
        source_snapshot_sha256=receipt["source_snapshot_sha256"],
        input_docx_sha256=receipt["input_docx_sha256"],
        semantic_document_revision=receipt["semantic_document_revision"],
        template_revision=receipt["template_revision"],
        producer_identity=receipt["producer_identity"],
    )
    receipt["idempotency_key"] = key
    receipt["receipt_id"] = compute_receipt_id(key)


def _roundtrip_receipt(receipt: dict) -> dict:
    result = deepcopy(receipt)
    result["source_snapshot_sha256"] = "d" * 64
    result["input_artifact_id"] = "artifact_roundtrip_reexport_r18"
    result["input_docx_sha256"] = "e" * 64
    result["semantic_document_revision"] = "semantic-document-r18"
    result["edit_reimport_export_lineage"] = {
        "mode": "edit_reimport_export",
        "source_artifact_id": "artifact_initial_export_r17",
        "source_artifact_sha256": "f" * 64,
        "edited_artifact_id": "artifact_external_word_edit_r17",
        "edited_artifact_sha256": "0" * 64,
        "reimported_artifact_id": "artifact_reimport_r17",
        "reimported_artifact_sha256": "0" * 64,
        "merged_semantic_revision": "semantic-document-r18",
        "reexport_artifact_id": "artifact_roundtrip_reexport_r18",
        "reexport_artifact_sha256": "e" * 64,
    }
    _rebind_identity(result)
    return result


def _assert_code(code: str, callable_) -> None:
    with pytest.raises(ReceiptContractError) as raised:
        callable_()
    assert raised.value.code == code


def test_checked_in_fixture_is_a_valid_native_word_receipt(payload: dict):
    validated = validate_receipt(payload["valid_receipt"])
    assert validated == payload["valid_receipt"]
    assert validated is not payload["valid_receipt"]


def test_fixture_identity_is_current(payload: dict):
    assert receipt_staleness(payload["valid_receipt"], payload["current_identity"]) == ()
    assert_receipt_current(payload["valid_receipt"], payload["current_identity"])


@pytest.mark.parametrize(
    "field",
    [
        "receipt_id",
        "source_snapshot_sha256",
        "input_docx_sha256",
        "semantic_document_revision",
        "template_revision",
        "word_application_version",
        "os_and_font_environment",
        "open_without_repair",
        "field_count_before",
        "field_count_after",
        "toc_count",
        "bookmark_checks",
        "cross_reference_checks",
        "saved_docx_sha256",
        "reopen_pass",
        "pdf_sha256",
        "page_evidence",
        "page_evidence_manifest_sha256",
        "normalized_ooxml_fingerprint",
        "edit_reimport_export_lineage",
        "started_at",
        "completed_at",
        "producer_identity",
        "idempotency_key",
    ],
)
def test_every_plan_minimum_field_is_mandatory(receipt: dict, field: str):
    del receipt[field]
    _assert_code("WR_MISSING_FIELD", lambda: validate_receipt(receipt))


def test_unknown_top_level_fields_fail_closed(receipt: dict):
    receipt["legacy_success"] = True
    _assert_code("WR_UNKNOWN_FIELD", lambda: validate_receipt(receipt))


@pytest.mark.parametrize("engine", ["libreoffice", "html_preview", "download_only"])
def test_non_microsoft_word_paths_cannot_upgrade(receipt: dict, engine: str):
    receipt["verification_engine"] = engine
    _assert_code("WR_NOT_MICROSOFT_WORD", lambda: validate_receipt(receipt))


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("open_without_repair", "WR_OPEN_REPAIR"),
        ("repaginate_pass", "WR_REPAGINATE"),
        ("reopen_pass", "WR_REOPEN"),
    ],
)
def test_native_word_boolean_gates_are_required(receipt: dict, field: str, code: str):
    receipt[field] = False
    _assert_code(code, lambda: validate_receipt(receipt))


def test_fields_must_cover_all_story_ranges_without_errors(receipt: dict):
    receipt["field_update_scope"] = "main_story_only"
    _assert_code("WR_FIELD_SCOPE", lambda: validate_receipt(receipt))
    receipt["field_update_scope"] = "all_story_ranges"
    receipt["field_update_error_count"] = 1
    _assert_code("WR_FIELD_UPDATE", lambda: validate_receipt(receipt))


def test_field_identity_and_toc_must_survive_update(receipt: dict):
    receipt["field_count_after"] -= 1
    _assert_code("WR_FIELD_COUNT", lambda: validate_receipt(receipt))
    receipt["field_count_after"] = receipt["field_count_before"]
    receipt["toc_count"] = 0
    _assert_code("WR_RANGE", lambda: validate_receipt(receipt))


def test_font_gaps_or_substitutions_block_receipt(receipt: dict):
    receipt["os_and_font_environment"]["missing_fonts"] = ["方正小标宋简体"]
    _assert_code("WR_FONT_ENVIRONMENT", lambda: validate_receipt(receipt))
    receipt["os_and_font_environment"]["missing_fonts"] = []
    receipt["os_and_font_environment"]["substituted_fonts"] = ["宋体->Arial"]
    _assert_code("WR_FONT_ENVIRONMENT", lambda: validate_receipt(receipt))


def test_bookmark_evidence_must_be_nonempty_resolved_and_unique(receipt: dict):
    receipt["bookmark_checks"] = []
    _assert_code("WR_BOOKMARK_EVIDENCE", lambda: validate_receipt(receipt))

    receipt = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    receipt["bookmark_checks"][0]["exists"] = False
    _assert_code("WR_BOOKMARK_EVIDENCE", lambda: validate_receipt(receipt))

    receipt = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    receipt["bookmark_checks"][0]["observed_target"] = "wrong-target"
    _assert_code("WR_BOOKMARK_TARGET", lambda: validate_receipt(receipt))

    receipt = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    receipt["bookmark_checks"].append(deepcopy(receipt["bookmark_checks"][0]))
    _assert_code("WR_DUPLICATE_ID", lambda: validate_receipt(receipt))


def test_cross_reference_evidence_must_be_real_and_resolved(receipt: dict):
    receipt["cross_reference_checks"] = []
    _assert_code("WR_REFERENCE_EVIDENCE", lambda: validate_receipt(receipt))

    receipt = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    receipt["cross_reference_checks"][0]["resolved"] = False
    _assert_code("WR_REFERENCE_EVIDENCE", lambda: validate_receipt(receipt))

    receipt = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    receipt["cross_reference_checks"][0]["field_code"] = "plain text"
    _assert_code("WR_REFERENCE_FIELD", lambda: validate_receipt(receipt))

    receipt = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    receipt["cross_reference_checks"][0]["target_bookmark"] = "bm_wrong_target"
    _assert_code("WR_REFERENCE_TARGET", lambda: validate_receipt(receipt))


def test_pdf_page_evidence_is_complete_native_and_clean(receipt: dict):
    receipt["page_evidence"] = []
    _assert_code("WR_PAGE_EVIDENCE", lambda: validate_receipt(receipt))

    receipt = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    receipt["page_evidence"][1]["page_number"] = 3
    _assert_code("WR_PAGE_SEQUENCE", lambda: validate_receipt(receipt))

    receipt = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    receipt["page_evidence"][0]["renderer"] = "html_preview"
    _assert_code("WR_PAGE_RENDERER", lambda: validate_receipt(receipt))

    receipt = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    receipt["page_evidence"][0]["visual_qc_status"] = "not_checked"
    _assert_code("WR_PAGE_QC", lambda: validate_receipt(receipt))


def test_page_evidence_dependency_must_have_resolved_provenance(receipt: dict):
    receipt["page_evidence_producer"]["license_status"] = "unverified"
    _assert_code("WR_PAGE_PRODUCER_LICENSE", lambda: validate_receipt(receipt))
    receipt["page_evidence_producer"]["license_status"] = "not_applicable_internal"
    receipt["page_evidence_producer"]["data_egress"] = "unknown"
    _assert_code("WR_PAGE_PRODUCER_EGRESS", lambda: validate_receipt(receipt))


def test_page_manifest_binds_exact_pdf_and_ordered_pages(receipt: dict):
    receipt["page_evidence_manifest_sha256"] = "0" * 64
    _assert_code("WR_PAGE_MANIFEST", lambda: validate_receipt(receipt))


def test_normalized_ooxml_fingerprint_is_mandatory_and_versioned(receipt: dict):
    receipt["normalized_ooxml_fingerprint"]["sha256"] = ""
    _assert_code("WR_EMPTY", lambda: validate_receipt(receipt))
    receipt = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    receipt["normalized_ooxml_fingerprint"]["algorithm"] = "zip_sha256"
    _assert_code("WR_OOXML_ALGORITHM", lambda: validate_receipt(receipt))

    receipt = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    receipt["normalized_ooxml_fingerprint"]["artifact_id"] = "different-docx"
    _assert_code("WR_OOXML_BINDING", lambda: validate_receipt(receipt))


def test_artifact_identities_are_immutable(receipt: dict):
    receipt["saved_artifact_id"] = receipt["input_artifact_id"]
    _assert_code("WR_ARTIFACT_IMMUTABILITY", lambda: validate_receipt(receipt))


def test_no_edit_lineage_cannot_hide_an_external_edit(receipt: dict):
    receipt["edit_reimport_export_lineage"]["edited_artifact_id"] = "hidden-edit"
    _assert_code("WR_LINEAGE_UNEXPECTED_EDIT", lambda: validate_receipt(receipt))


def test_external_edit_roundtrip_requires_new_immutable_artifacts(receipt: dict):
    roundtrip = _roundtrip_receipt(receipt)
    assert validate_receipt(roundtrip)["edit_reimport_export_lineage"]["mode"] == "edit_reimport_export"

    roundtrip["edit_reimport_export_lineage"]["edited_artifact_id"] = roundtrip[
        "edit_reimport_export_lineage"
    ]["source_artifact_id"]
    _assert_code("WR_LINEAGE_IMMUTABILITY", lambda: validate_receipt(roundtrip))


def test_external_edit_roundtrip_binds_current_revision_and_reexport(receipt: dict):
    roundtrip = _roundtrip_receipt(receipt)
    roundtrip["edit_reimport_export_lineage"]["merged_semantic_revision"] = "semantic-document-r19"
    _assert_code("WR_LINEAGE_REVISION", lambda: validate_receipt(roundtrip))

    roundtrip = _roundtrip_receipt(receipt)
    roundtrip["edit_reimport_export_lineage"]["reexport_artifact_id"] = "different-artifact"
    _assert_code("WR_LINEAGE_REEXPORT", lambda: validate_receipt(roundtrip))


def test_idempotency_key_and_receipt_id_are_deterministic(receipt: dict):
    key = compute_idempotency_key(
        source_snapshot_sha256=receipt["source_snapshot_sha256"],
        input_docx_sha256=receipt["input_docx_sha256"],
        semantic_document_revision=receipt["semantic_document_revision"],
        template_revision=receipt["template_revision"],
        producer_identity=receipt["producer_identity"],
    )
    assert key == receipt["idempotency_key"]
    assert compute_receipt_id(key) == receipt["receipt_id"]

    receipt["idempotency_key"] = receipt["idempotency_key"][:-1] + "0"
    _assert_code("WR_IDEMPOTENCY_KEY", lambda: validate_receipt(receipt))


def test_receipt_id_cannot_be_reassigned(receipt: dict):
    receipt["receipt_id"] = "mwwr_v1_reassigned"
    _assert_code("WR_RECEIPT_ID", lambda: validate_receipt(receipt))


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        ("source_snapshot_sha256", "f" * 64, "WR_STALE_SOURCE_SNAPSHOT"),
        ("input_docx_sha256", "e" * 64, "WR_STALE_INPUT_DOCX"),
        ("semantic_document_revision", "semantic-document-r18", "WR_STALE_SEMANTIC_REVISION"),
        ("template_revision", "TP-MA-07-r4", "WR_STALE_TEMPLATE_REVISION"),
    ],
)
def test_exact_identity_changes_make_receipt_stale(
    payload: dict, field: str, replacement: str, reason: str
):
    current = deepcopy(payload["current_identity"])
    current[field] = replacement
    assert receipt_staleness(payload["valid_receipt"], current) == (reason,)
    _assert_code(
        "WR_STALE",
        lambda: assert_receipt_current(payload["valid_receipt"], current),
    )


@pytest.mark.parametrize(
    ("started", "completed", "code"),
    [
        ("2026-08-10T01:20:00", "2026-08-10T01:24:30Z", "WR_TIMESTAMP"),
        ("2026-08-10T01:20:00Z", "2026-08-10T01:20:00Z", "WR_TIMESTAMP_ORDER"),
    ],
)
def test_timestamps_are_timezone_aware_and_ordered(
    receipt: dict, started: str, completed: str, code: str
):
    receipt["started_at"] = started
    receipt["completed_at"] = completed
    _assert_code(code, lambda: validate_receipt(receipt))


def test_historical_word_trace_cannot_be_upgraded(payload: dict):
    _assert_code(
        "WR_MISSING_FIELD",
        lambda: validate_receipt(payload["historical_trace_missing_evidence"]),
    )
