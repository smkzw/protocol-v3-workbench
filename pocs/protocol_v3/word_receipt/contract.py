"""Protocol v3 Microsoft Word native receipt contract.

This Phase 0 module is deliberately producer-neutral and side-effect free.  It
validates evidence emitted by a future Word bridge; it never opens Word, edits a
DOCX, renders a PDF, or writes a receipt.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any, Mapping


SCHEMA_VERSION = "mw_protocol_v3_word_native_receipt_v1"
VERIFICATION_ENGINE = "microsoft_word"
VERIFICATION_STATUS = "word_native_verified"
WORKFLOW = (
    "open_without_repair_update_all_story_fields_toc_repaginate_"
    "check_bookmarks_refs_save_reopen_export_pdf"
)
IDEMPOTENCY_PREFIX = "mw-word-receipt-v1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class ReceiptContractError(ValueError):
    """Typed, stable failure emitted by the offline receipt validator."""

    def __init__(self, code: str, path: str, message: str):
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}: {message}")


TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "verification_engine",
        "verification_status",
        "workflow",
        "source_snapshot_sha256",
        "input_artifact_id",
        "input_docx_sha256",
        "semantic_document_revision",
        "template_revision",
        "word_application_version",
        "os_and_font_environment",
        "open_without_repair",
        "field_update_scope",
        "field_update_error_count",
        "field_count_before",
        "field_count_after",
        "toc_count",
        "repaginate_pass",
        "bookmark_checks",
        "cross_reference_checks",
        "saved_artifact_id",
        "saved_docx_sha256",
        "reopen_pass",
        "pdf_artifact_id",
        "pdf_sha256",
        "page_count",
        "page_evidence_producer",
        "page_evidence",
        "page_evidence_manifest_sha256",
        "normalized_ooxml_fingerprint",
        "edit_reimport_export_lineage",
        "started_at",
        "completed_at",
        "producer_identity",
        "idempotency_key",
    }
)

CURRENT_IDENTITY_FIELDS = frozenset(
    {
        "source_snapshot_sha256",
        "input_docx_sha256",
        "semantic_document_revision",
        "template_revision",
    }
)

_ENVIRONMENT_FIELDS = frozenset(
    {
        "os_name",
        "os_version",
        "architecture",
        "locale",
        "font_manifest_sha256",
        "font_count",
        "missing_fonts",
        "substituted_fonts",
    }
)
_PRODUCER_FIELDS = frozenset(
    {"producer_id", "producer_type", "producer_version", "implementation_sha256"}
)
_PAGE_PRODUCER_FIELDS = frozenset(
    {
        "name",
        "version",
        "license_spdx",
        "license_source",
        "license_status",
        "data_egress",
    }
)
_BOOKMARK_FIELDS = frozenset(
    {"bookmark_id", "expected_target", "observed_target", "exists", "target_sha256"}
)
_REFERENCE_FIELDS = frozenset(
    {
        "reference_id",
        "field_code",
        "target_bookmark",
        "rendered_text",
        "resolved",
        "page_number",
    }
)
_PAGE_FIELDS = frozenset(
    {
        "page_number",
        "pdf_page_sha256",
        "image_sha256",
        "width_px",
        "height_px",
        "renderer",
        "visual_qc_status",
    }
)
_OOXML_FIELDS = frozenset(
    {
        "algorithm",
        "sha256",
        "artifact_id",
        "artifact_sha256",
        "ignored_parts_profile",
        "normalizer_version",
        "part_count",
    }
)
_LINEAGE_FIELDS = frozenset(
    {
        "mode",
        "source_artifact_id",
        "source_artifact_sha256",
        "edited_artifact_id",
        "edited_artifact_sha256",
        "reimported_artifact_id",
        "reimported_artifact_sha256",
        "merged_semantic_revision",
        "reexport_artifact_id",
        "reexport_artifact_sha256",
    }
)


def _fail(code: str, path: str, message: str) -> None:
    raise ReceiptContractError(code, path, message)


def _mapping(value: Any, path: str, fields: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("WR_TYPE", path, "must be an object")
    keys = set(value)
    missing = sorted(fields - keys)
    unknown = sorted(keys - fields)
    if missing:
        _fail("WR_MISSING_FIELD", path, f"missing {', '.join(missing)}")
    if unknown:
        _fail("WR_UNKNOWN_FIELD", path, f"unknown {', '.join(unknown)}")
    return value


def _text(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail("WR_TYPE", path, "must be a string")
    if not allow_empty and not value.strip():
        _fail("WR_EMPTY", path, "must not be empty")
    return value


def _hash(value: Any, path: str, *, allow_empty: bool = False) -> str:
    value = _text(value, path, allow_empty=allow_empty)
    if value == "" and allow_empty:
        return value
    if not _SHA256_RE.fullmatch(value):
        _fail("WR_SHA256", path, "must be a lowercase SHA-256")
    return value


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("WR_TYPE", path, "must be an integer")
    if value < minimum:
        _fail("WR_RANGE", path, f"must be >= {minimum}")
    return value


def _true(value: Any, path: str, code: str) -> None:
    if value is not True:
        _fail(code, path, "must be true")


def _timestamp(value: Any, path: str) -> datetime:
    text = _text(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail("WR_TIMESTAMP", path, "must be RFC 3339 compatible")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("WR_TIMESTAMP", path, "must include a timezone")
    return parsed


def _validate_environment(value: Any) -> Mapping[str, Any]:
    env = _mapping(value, "os_and_font_environment", _ENVIRONMENT_FIELDS)
    for name in ("os_name", "os_version", "architecture", "locale"):
        _text(env[name], f"os_and_font_environment.{name}")
    _hash(env["font_manifest_sha256"], "os_and_font_environment.font_manifest_sha256")
    _integer(env["font_count"], "os_and_font_environment.font_count", minimum=1)
    for name in ("missing_fonts", "substituted_fonts"):
        items = env[name]
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            _fail("WR_TYPE", f"os_and_font_environment.{name}", "must be a string list")
    if env["missing_fonts"] or env["substituted_fonts"]:
        _fail("WR_FONT_ENVIRONMENT", "os_and_font_environment", "fonts must resolve without gaps or substitutions")
    return env


def _validate_producer_identity(value: Any) -> Mapping[str, Any]:
    producer = _mapping(value, "producer_identity", _PRODUCER_FIELDS)
    for name in ("producer_id", "producer_type", "producer_version"):
        _text(producer[name], f"producer_identity.{name}")
    _hash(producer["implementation_sha256"], "producer_identity.implementation_sha256")
    return producer


def _validate_page_producer(value: Any) -> Mapping[str, Any]:
    producer = _mapping(value, "page_evidence_producer", _PAGE_PRODUCER_FIELDS)
    for name in ("name", "version", "license_spdx", "license_source"):
        _text(producer[name], f"page_evidence_producer.{name}")
    if producer["license_status"] not in {"verified_compatible", "not_applicable_internal"}:
        _fail("WR_PAGE_PRODUCER_LICENSE", "page_evidence_producer.license_status", "must be independently resolved before use")
    if producer["data_egress"] not in {"none", "documented_and_approved"}:
        _fail("WR_PAGE_PRODUCER_EGRESS", "page_evidence_producer.data_egress", "must be explicit")
    return producer


def _validate_bookmarks(value: Any) -> None:
    if not isinstance(value, list) or not value:
        _fail("WR_BOOKMARK_EVIDENCE", "bookmark_checks", "at least one bookmark check is required")
    seen: set[str] = set()
    for index, raw in enumerate(value):
        path = f"bookmark_checks[{index}]"
        item = _mapping(raw, path, _BOOKMARK_FIELDS)
        bookmark_id = _text(item["bookmark_id"], f"{path}.bookmark_id")
        if bookmark_id in seen:
            _fail("WR_DUPLICATE_ID", f"{path}.bookmark_id", "must be unique")
        seen.add(bookmark_id)
        _true(item["exists"], f"{path}.exists", "WR_BOOKMARK_EVIDENCE")
        expected = _text(item["expected_target"], f"{path}.expected_target")
        observed = _text(item["observed_target"], f"{path}.observed_target")
        if expected != observed:
            _fail("WR_BOOKMARK_TARGET", path, "observed target does not match expected target")
        _hash(item["target_sha256"], f"{path}.target_sha256")


def _validate_references(value: Any) -> None:
    if not isinstance(value, list) or not value:
        _fail("WR_REFERENCE_EVIDENCE", "cross_reference_checks", "at least one cross-reference check is required")
    seen: set[str] = set()
    for index, raw in enumerate(value):
        path = f"cross_reference_checks[{index}]"
        item = _mapping(raw, path, _REFERENCE_FIELDS)
        reference_id = _text(item["reference_id"], f"{path}.reference_id")
        if reference_id in seen:
            _fail("WR_DUPLICATE_ID", f"{path}.reference_id", "must be unique")
        seen.add(reference_id)
        field_code = _text(item["field_code"], f"{path}.field_code")
        field_match = re.match(r"^(REF|PAGEREF)\s+(\S+)", field_code)
        if not field_match:
            _fail("WR_REFERENCE_FIELD", f"{path}.field_code", "must be a REF or PAGEREF field")
        target_bookmark = _text(item["target_bookmark"], f"{path}.target_bookmark")
        if field_match.group(2) != target_bookmark:
            _fail("WR_REFERENCE_TARGET", path, "field code and declared target bookmark differ")
        _text(item["rendered_text"], f"{path}.rendered_text")
        _true(item["resolved"], f"{path}.resolved", "WR_REFERENCE_EVIDENCE")
        _integer(item["page_number"], f"{path}.page_number", minimum=1)


def _validate_pages(value: Any, page_count: int) -> None:
    if not isinstance(value, list) or not value:
        _fail("WR_PAGE_EVIDENCE", "page_evidence", "PDF page evidence is required")
    if len(value) != page_count:
        _fail("WR_PAGE_COUNT", "page_evidence", "length must equal page_count")
    observed: list[int] = []
    for index, raw in enumerate(value):
        path = f"page_evidence[{index}]"
        item = _mapping(raw, path, _PAGE_FIELDS)
        observed.append(_integer(item["page_number"], f"{path}.page_number", minimum=1))
        _hash(item["pdf_page_sha256"], f"{path}.pdf_page_sha256")
        _hash(item["image_sha256"], f"{path}.image_sha256")
        _integer(item["width_px"], f"{path}.width_px", minimum=1)
        _integer(item["height_px"], f"{path}.height_px", minimum=1)
        if item["renderer"] != "microsoft_word_pdf":
            _fail("WR_PAGE_RENDERER", f"{path}.renderer", "must identify the native Word PDF")
        if item["visual_qc_status"] != "pass":
            _fail("WR_PAGE_QC", f"{path}.visual_qc_status", "must be pass")
    if observed != list(range(1, page_count + 1)):
        _fail("WR_PAGE_SEQUENCE", "page_evidence", "pages must be contiguous and ordered")


def _validate_ooxml(value: Any, receipt: Mapping[str, Any]) -> None:
    fingerprint = _mapping(value, "normalized_ooxml_fingerprint", _OOXML_FIELDS)
    if fingerprint["algorithm"] != "mw_ooxml_normalized_v1":
        _fail("WR_OOXML_ALGORITHM", "normalized_ooxml_fingerprint.algorithm", "unsupported algorithm")
    _hash(fingerprint["sha256"], "normalized_ooxml_fingerprint.sha256")
    if fingerprint["artifact_id"] != receipt["saved_artifact_id"]:
        _fail("WR_OOXML_BINDING", "normalized_ooxml_fingerprint.artifact_id", "must bind the Word-saved artifact")
    if fingerprint["artifact_sha256"] != receipt["saved_docx_sha256"]:
        _fail("WR_OOXML_BINDING", "normalized_ooxml_fingerprint.artifact_sha256", "must bind the Word-saved DOCX")
    _text(fingerprint["ignored_parts_profile"], "normalized_ooxml_fingerprint.ignored_parts_profile")
    _text(fingerprint["normalizer_version"], "normalized_ooxml_fingerprint.normalizer_version")
    _integer(fingerprint["part_count"], "normalized_ooxml_fingerprint.part_count", minimum=1)


def _validate_lineage(receipt: Mapping[str, Any]) -> None:
    lineage = _mapping(
        receipt["edit_reimport_export_lineage"],
        "edit_reimport_export_lineage",
        _LINEAGE_FIELDS,
    )
    mode = lineage["mode"]
    if mode not in {"no_external_edit", "edit_reimport_export"}:
        _fail("WR_LINEAGE_MODE", "edit_reimport_export_lineage.mode", "unsupported mode")
    if mode == "no_external_edit":
        if lineage["source_artifact_id"] != receipt["input_artifact_id"]:
            _fail("WR_LINEAGE_SOURCE", "edit_reimport_export_lineage.source_artifact_id", "must bind the input artifact")
        if lineage["source_artifact_sha256"] != receipt["input_docx_sha256"]:
            _fail("WR_LINEAGE_SOURCE", "edit_reimport_export_lineage.source_artifact_sha256", "must bind the input DOCX")
        for name in (
            "edited_artifact_id",
            "edited_artifact_sha256",
            "reimported_artifact_id",
            "reimported_artifact_sha256",
            "merged_semantic_revision",
            "reexport_artifact_id",
            "reexport_artifact_sha256",
        ):
            if lineage[name] != "":
                _fail("WR_LINEAGE_UNEXPECTED_EDIT", f"edit_reimport_export_lineage.{name}", "must be empty without an external edit")
        return

    _text(lineage["source_artifact_id"], "edit_reimport_export_lineage.source_artifact_id")
    _hash(lineage["source_artifact_sha256"], "edit_reimport_export_lineage.source_artifact_sha256")
    ids = [
        lineage["source_artifact_id"],
        _text(lineage["edited_artifact_id"], "edit_reimport_export_lineage.edited_artifact_id"),
        _text(lineage["reimported_artifact_id"], "edit_reimport_export_lineage.reimported_artifact_id"),
        _text(lineage["reexport_artifact_id"], "edit_reimport_export_lineage.reexport_artifact_id"),
    ]
    if len(set(ids)) != len(ids):
        _fail("WR_LINEAGE_IMMUTABILITY", "edit_reimport_export_lineage", "source, edited, reimported and re-exported artifact ids must be distinct")
    _hash(lineage["edited_artifact_sha256"], "edit_reimport_export_lineage.edited_artifact_sha256")
    _hash(lineage["reimported_artifact_sha256"], "edit_reimport_export_lineage.reimported_artifact_sha256")
    _hash(lineage["reexport_artifact_sha256"], "edit_reimport_export_lineage.reexport_artifact_sha256")
    if lineage["reexport_artifact_id"] != receipt["input_artifact_id"]:
        _fail("WR_LINEAGE_REEXPORT", "edit_reimport_export_lineage.reexport_artifact_id", "must bind the DOCX handed to Word verification")
    if lineage["reexport_artifact_sha256"] != receipt["input_docx_sha256"]:
        _fail("WR_LINEAGE_REEXPORT", "edit_reimport_export_lineage.reexport_artifact_sha256", "must bind the DOCX handed to Word verification")
    merged = _text(lineage["merged_semantic_revision"], "edit_reimport_export_lineage.merged_semantic_revision")
    if merged != receipt["semantic_document_revision"]:
        _fail("WR_LINEAGE_REVISION", "edit_reimport_export_lineage.merged_semantic_revision", "must bind the current merged semantic revision")


def compute_idempotency_key(
    *,
    source_snapshot_sha256: str,
    input_docx_sha256: str,
    semantic_document_revision: str,
    template_revision: str,
    producer_identity: Mapping[str, Any],
) -> str:
    """Return the only valid idempotency key for one producer/input identity."""

    _hash(source_snapshot_sha256, "source_snapshot_sha256")
    _hash(input_docx_sha256, "input_docx_sha256")
    _text(semantic_document_revision, "semantic_document_revision")
    _text(template_revision, "template_revision")
    producer = _validate_producer_identity(producer_identity)
    material = {
        "schema_version": SCHEMA_VERSION,
        "source_snapshot_sha256": source_snapshot_sha256,
        "input_docx_sha256": input_docx_sha256,
        "semantic_document_revision": semantic_document_revision,
        "template_revision": template_revision,
        "producer_identity": dict(producer),
    }
    canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{IDEMPOTENCY_PREFIX}:{sha256(canonical.encode('utf-8')).hexdigest()}"


def compute_receipt_id(idempotency_key: str) -> str:
    """Bind a stable receipt id to the immutable idempotency identity."""

    key = _text(idempotency_key, "idempotency_key")
    if not key.startswith(f"{IDEMPOTENCY_PREFIX}:"):
        _fail("WR_IDEMPOTENCY_KEY", "idempotency_key", "unexpected prefix")
    return f"mwwr_v1_{sha256(key.encode('utf-8')).hexdigest()[:32]}"


def compute_page_evidence_manifest(
    *, pdf_sha256: str, page_evidence: list[Mapping[str, Any]]
) -> str:
    """Bind ordered per-page evidence to the exact Word-exported PDF."""

    _hash(pdf_sha256, "pdf_sha256")
    material = {
        "pdf_sha256": pdf_sha256,
        "page_evidence": page_evidence,
    }
    canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def validate_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one full receipt and return an isolated copy.

    Acceptance is intentionally strict.  A historical trace or a preview with
    only a subset of these fields is evidence of work performed, not evidence
    that the native Word gate passed.
    """

    receipt = _mapping(value, "$", TOP_LEVEL_FIELDS)
    if receipt["schema_version"] != SCHEMA_VERSION:
        _fail("WR_SCHEMA_VERSION", "schema_version", "unsupported schema")
    if receipt["verification_engine"] != VERIFICATION_ENGINE:
        _fail("WR_NOT_MICROSOFT_WORD", "verification_engine", "only native Microsoft Word is eligible")
    if receipt["verification_status"] != VERIFICATION_STATUS:
        _fail("WR_STATUS", "verification_status", "must be word_native_verified")
    if receipt["workflow"] != WORKFLOW:
        _fail("WR_WORKFLOW", "workflow", "does not prove the complete native workflow")

    _hash(receipt["source_snapshot_sha256"], "source_snapshot_sha256")
    _hash(receipt["input_docx_sha256"], "input_docx_sha256")
    _hash(receipt["saved_docx_sha256"], "saved_docx_sha256")
    _hash(receipt["pdf_sha256"], "pdf_sha256")
    for name in (
        "input_artifact_id",
        "saved_artifact_id",
        "pdf_artifact_id",
        "semantic_document_revision",
        "template_revision",
        "word_application_version",
    ):
        _text(receipt[name], name)
    artifact_ids = [receipt["input_artifact_id"], receipt["saved_artifact_id"], receipt["pdf_artifact_id"]]
    if len(set(artifact_ids)) != 3:
        _fail("WR_ARTIFACT_IMMUTABILITY", "$", "input, saved DOCX and PDF artifact ids must be distinct")

    _validate_environment(receipt["os_and_font_environment"])
    _true(receipt["open_without_repair"], "open_without_repair", "WR_OPEN_REPAIR")
    if receipt["field_update_scope"] != "all_story_ranges":
        _fail("WR_FIELD_SCOPE", "field_update_scope", "must cover all story ranges")
    if _integer(receipt["field_update_error_count"], "field_update_error_count") != 0:
        _fail("WR_FIELD_UPDATE", "field_update_error_count", "must be zero")
    before = _integer(receipt["field_count_before"], "field_count_before")
    after = _integer(receipt["field_count_after"], "field_count_after")
    if before != after:
        _fail("WR_FIELD_COUNT", "field_count_after", "field identities must survive update")
    _integer(receipt["toc_count"], "toc_count", minimum=1)
    _true(receipt["repaginate_pass"], "repaginate_pass", "WR_REPAGINATE")
    _validate_bookmarks(receipt["bookmark_checks"])
    _validate_references(receipt["cross_reference_checks"])
    _true(receipt["reopen_pass"], "reopen_pass", "WR_REOPEN")

    page_count = _integer(receipt["page_count"], "page_count", minimum=1)
    _validate_page_producer(receipt["page_evidence_producer"])
    _validate_pages(receipt["page_evidence"], page_count)
    _hash(receipt["page_evidence_manifest_sha256"], "page_evidence_manifest_sha256")
    expected_page_manifest = compute_page_evidence_manifest(
        pdf_sha256=receipt["pdf_sha256"],
        page_evidence=receipt["page_evidence"],
    )
    if receipt["page_evidence_manifest_sha256"] != expected_page_manifest:
        _fail("WR_PAGE_MANIFEST", "page_evidence_manifest_sha256", "does not bind the exact PDF and ordered page evidence")
    _validate_ooxml(receipt["normalized_ooxml_fingerprint"], receipt)
    _validate_lineage(receipt)

    started = _timestamp(receipt["started_at"], "started_at")
    completed = _timestamp(receipt["completed_at"], "completed_at")
    if completed <= started:
        _fail("WR_TIMESTAMP_ORDER", "completed_at", "must be later than started_at")
    producer = _validate_producer_identity(receipt["producer_identity"])
    expected_key = compute_idempotency_key(
        source_snapshot_sha256=receipt["source_snapshot_sha256"],
        input_docx_sha256=receipt["input_docx_sha256"],
        semantic_document_revision=receipt["semantic_document_revision"],
        template_revision=receipt["template_revision"],
        producer_identity=producer,
    )
    if receipt["idempotency_key"] != expected_key:
        _fail("WR_IDEMPOTENCY_KEY", "idempotency_key", "does not bind the exact source/revision/producer identity")
    expected_receipt_id = compute_receipt_id(expected_key)
    if receipt["receipt_id"] != expected_receipt_id:
        _fail("WR_RECEIPT_ID", "receipt_id", "does not bind the idempotency key")
    return deepcopy(dict(receipt))


def receipt_staleness(
    receipt: Mapping[str, Any], current_identity: Mapping[str, Any]
) -> tuple[str, ...]:
    """Return typed reasons when a valid receipt no longer matches current truth."""

    validated = validate_receipt(receipt)
    current = _mapping(current_identity, "current_identity", CURRENT_IDENTITY_FIELDS)
    _hash(current["source_snapshot_sha256"], "current_identity.source_snapshot_sha256")
    _hash(current["input_docx_sha256"], "current_identity.input_docx_sha256")
    _text(current["semantic_document_revision"], "current_identity.semantic_document_revision")
    _text(current["template_revision"], "current_identity.template_revision")
    code_by_field = {
        "source_snapshot_sha256": "WR_STALE_SOURCE_SNAPSHOT",
        "input_docx_sha256": "WR_STALE_INPUT_DOCX",
        "semantic_document_revision": "WR_STALE_SEMANTIC_REVISION",
        "template_revision": "WR_STALE_TEMPLATE_REVISION",
    }
    return tuple(
        code_by_field[name]
        for name in (
            "source_snapshot_sha256",
            "input_docx_sha256",
            "semantic_document_revision",
            "template_revision",
        )
        if validated[name] != current[name]
    )


def assert_receipt_current(
    receipt: Mapping[str, Any], current_identity: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a validated copy or fail closed with all staleness reasons."""

    reasons = receipt_staleness(receipt, current_identity)
    if reasons:
        _fail("WR_STALE", "current_identity", ",".join(reasons))
    return validate_receipt(receipt)
