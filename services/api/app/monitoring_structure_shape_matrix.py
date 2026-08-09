"""Diagnostic contract for the recorded five-project shape matrix.

The matrix is copied from an already reviewed aggregate intake record.  It is
not a second source parser and must never be treated as source admission,
field mapping, semantic AI evidence, or a clinical conclusion.  This module
only validates that the recorded shape evidence remains explicit, isolated by
project identity, and fail-closed for every execution boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping


STRUCTURE_SHAPE_MATRIX_SCHEMA_VERSION = "medical_monitoring_five_project_shape_matrix_v1"
STRUCTURE_SHAPE_MATRIX_CONTRACT_VERSION = "medical_monitoring_structure_shape_matrix_contract_v1"
EXPECTED_PROVENANCE_KIND = "recorded_aggregate_evidence"
EXPECTED_PROJECT_IDS = (
    "proj_mgk10_sar_real",
    "proj_rux_03_002",
    "proj_my008_3_01_candidate",
    "proj_my008_3_02_candidate",
    "proj_my009_uc",
)
EXPECTED_REAL_PROJECT_IDS = frozenset({"proj_mgk10_sar_real", "proj_rux_03_002", "proj_my009_uc"})
EXPECTED_CANDIDATE_PROJECT_IDS = frozenset({"proj_my008_3_01_candidate", "proj_my008_3_02_candidate"})
EXPECTED_IMPLEMENTATION_STATUSES = frozenset({"real_source_slice", "source_manifest_only"})
ALLOWED_IDENTITY_CLASSES = frozenset({"canonical_real", "candidate_only"})
ALLOWED_DOMAINS = frozenset({"AE", "CM", "EFFICACY", "LAB", "MH", "PR", "PD", "STUDY_DRUG", "VISIT"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class StructureShapeMatrixError(ValueError):
    """Raised only for an invalid top-level input or report construction."""


class StructureShapeMatrixIssueCode(str, Enum):
    SCHEMA_VERSION_INVALID = "schema_version_invalid"
    CONTRACT_PROVENANCE_INVALID = "contract_provenance_invalid"
    REFERENCE_INVALID = "reference_invalid"
    AUTHORITY_MAPPING_MISSING = "authority_mapping_missing"
    AUTHORITY_FLAG_INVALID = "authority_flag_invalid"
    RETENTION_MAPPING_MISSING = "retention_mapping_missing"
    RETENTION_FLAG_INVALID = "retention_flag_invalid"
    PROJECT_LIST_INVALID = "project_list_invalid"
    PROJECT_ID_INVALID = "project_id_invalid"
    PROJECT_ID_DUPLICATE = "project_id_duplicate"
    PROJECT_SET_INCOMPLETE = "project_set_incomplete"
    IDENTITY_CLASS_INVALID = "identity_class_invalid"
    IMPLEMENTATION_STATUS_INVALID = "implementation_status_invalid"
    IDENTITY_STATUS_MISMATCH = "identity_status_mismatch"
    SOURCE_REVISION_INVALID = "source_revision_invalid"
    SOURCE_FILENAME_INVALID = "source_filename_invalid"
    SOURCE_BYTES_INVALID = "source_bytes_invalid"
    SOURCE_SHA256_INVALID = "source_sha256_invalid"
    COUNT_INVALID = "count_invalid"
    DOMAIN_LIST_INVALID = "domain_list_invalid"
    DOMAIN_UNKNOWN = "domain_unknown"
    DOMAIN_DUPLICATE = "domain_duplicate"
    UNCLASSIFIED_COUNT_INVALID = "unclassified_count_invalid"
    STRUCTURAL_DISPOSITION_INVALID = "structural_disposition_invalid"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _safe_filename(value: Any) -> bool:
    filename = _text(value)
    return bool(
        _nonempty_text(value)
        and filename not in {".", ".."}
        and "\x00" not in filename
        and "/" not in filename
        and "\\" not in filename
    )


def _relative_reference(value: Any) -> bool:
    reference = _text(value)
    return bool(
        _nonempty_text(value)
        and not reference.startswith(("/", "~"))
        and not re.match(r"^[A-Za-z]:[\\/]", reference)
        and "\x00" not in reference
        and ".." not in re.split(r"[/\\]", reference)
    )


def _digest(value: Any) -> str:
    try:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:  # pragma: no cover - Mapping is JSON-shaped.
        raise StructureShapeMatrixError("shape matrix must be JSON serializable") from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StructureShapeMatrixIssue:
    code: StructureShapeMatrixIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise StructureShapeMatrixError("issue subject and detail are required")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class StructureShapeMatrixReport:
    status: str
    project_ids: tuple[str, ...]
    issues: tuple[StructureShapeMatrixIssue, ...] = ()
    schema_version: str = STRUCTURE_SHAPE_MATRIX_CONTRACT_VERSION
    diagnostic_only: bool = True
    aggregate_only: bool = True
    structure_mapping_permitted: bool = False
    adapter_activation_permitted: bool = False
    provider_call_permitted: bool = False
    runtime_activation_permitted: bool = False
    write_permitted: bool = False
    medical_confirmation_permitted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != STRUCTURE_SHAPE_MATRIX_CONTRACT_VERSION:
            raise StructureShapeMatrixError("unsupported shape matrix contract schema")
        if self.status not in {"blocked", "ready_for_generalization_review"}:
            raise StructureShapeMatrixError("invalid shape matrix contract status")
        if any(not _text(project_id) for project_id in self.project_ids):
            raise StructureShapeMatrixError("project_ids must not contain empty values")
        for name in (
            "diagnostic_only",
            "aggregate_only",
            "structure_mapping_permitted",
            "adapter_activation_permitted",
            "provider_call_permitted",
            "runtime_activation_permitted",
            "write_permitted",
            "medical_confirmation_permitted",
        ):
            if not isinstance(getattr(self, name), bool):
                raise StructureShapeMatrixError(f"{name} must be boolean")
        if not (self.diagnostic_only and self.aggregate_only):
            raise StructureShapeMatrixError("shape matrix must remain diagnostic and aggregate-only")
        if any(
            (
                self.structure_mapping_permitted,
                self.adapter_activation_permitted,
                self.provider_call_permitted,
                self.runtime_activation_permitted,
                self.write_permitted,
                self.medical_confirmation_permitted,
            )
        ):
            raise StructureShapeMatrixError("shape matrix cannot grant execution authority")
        issues = tuple(self.issues)
        expected_status = "ready_for_generalization_review" if not issues else "blocked"
        if self.status != expected_status:
            raise StructureShapeMatrixError("status does not match shape matrix issues")
        if any(not isinstance(item, StructureShapeMatrixIssue) for item in issues):
            raise StructureShapeMatrixError("issues must contain StructureShapeMatrixIssue rows")
        object.__setattr__(self, "issues", tuple(sorted(issues, key=lambda item: (item.subject, item.code.value, item.detail))))
        object.__setattr__(self, "project_ids", tuple(sorted({_text(item) for item in self.project_ids})))
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "project_ids": list(self.project_ids),
            "issues": [item.to_dict() for item in self.issues],
            "diagnostic_only": self.diagnostic_only,
            "aggregate_only": self.aggregate_only,
            "structure_mapping_permitted": self.structure_mapping_permitted,
            "adapter_activation_permitted": self.adapter_activation_permitted,
            "provider_call_permitted": self.provider_call_permitted,
            "runtime_activation_permitted": self.runtime_activation_permitted,
            "write_permitted": self.write_permitted,
            "medical_confirmation_permitted": self.medical_confirmation_permitted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "issue_count": len(self.issues), "report_sha256": self.report_sha256}


def _issue(
    issues: list[StructureShapeMatrixIssue],
    code: StructureShapeMatrixIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(StructureShapeMatrixIssue(code, subject, detail))


def _check_flags(
    value: Any,
    *,
    subject: str,
    expected: Mapping[str, bool],
    missing_code: StructureShapeMatrixIssueCode,
    invalid_code: StructureShapeMatrixIssueCode,
    issues: list[StructureShapeMatrixIssue],
) -> None:
    if not isinstance(value, Mapping):
        _issue(issues, missing_code, subject, "required boundary flags are missing")
        return
    for name, expected_value in expected.items():
        actual = value.get(name)
        if not isinstance(actual, bool) or actual is not expected_value:
            _issue(issues, invalid_code, f"{subject}.{name}", "flag violates the aggregate-only boundary")


def _check_source_revision(value: Any, *, subject: str, issues: list[StructureShapeMatrixIssue]) -> None:
    if not isinstance(value, Mapping):
        _issue(issues, StructureShapeMatrixIssueCode.SOURCE_REVISION_INVALID, subject, "source revision must be an object")
        return
    for field_name in ("listing_filename", "protocol_filename"):
        if not _safe_filename(value.get(field_name)):
            _issue(issues, StructureShapeMatrixIssueCode.SOURCE_FILENAME_INVALID, f"{subject}.{field_name}", "source evidence retains a basename only")
    for field_name in ("listing_bytes", "protocol_bytes"):
        if not _nonnegative_int(value.get(field_name)):
            _issue(issues, StructureShapeMatrixIssueCode.SOURCE_BYTES_INVALID, f"{subject}.{field_name}", "source byte count must be non-negative")
    for field_name in ("listing_sha256", "protocol_sha256"):
        if not _SHA256_RE.fullmatch(_text(value.get(field_name))):
            _issue(issues, StructureShapeMatrixIssueCode.SOURCE_SHA256_INVALID, f"{subject}.{field_name}", "source hash must be lowercase SHA-256")


def _check_project(value: Any, *, index: int, issues: list[StructureShapeMatrixIssue]) -> str:
    subject = f"projects[{index}]"
    if not isinstance(value, Mapping):
        _issue(issues, StructureShapeMatrixIssueCode.PROJECT_LIST_INVALID, subject, "project row must be an object")
        return ""
    project_id = _text(value.get("project_id"))
    if not _nonempty_text(value.get("project_id")) or "/" in project_id or "\\" in project_id or "\x00" in project_id:
        _issue(issues, StructureShapeMatrixIssueCode.PROJECT_ID_INVALID, f"{subject}.project_id", "project identity must be opaque and path-free")
        project_id = f"unknown_{index}"
    identity_class = _text(value.get("identity_class"))
    if identity_class not in ALLOWED_IDENTITY_CLASSES:
        _issue(issues, StructureShapeMatrixIssueCode.IDENTITY_CLASS_INVALID, f"{project_id}.identity_class", "identity class is unsupported")
    status = _text(value.get("implementation_status"))
    if status not in EXPECTED_IMPLEMENTATION_STATUSES:
        _issue(issues, StructureShapeMatrixIssueCode.IMPLEMENTATION_STATUS_INVALID, f"{project_id}.implementation_status", "implementation status is unsupported")
    if project_id in EXPECTED_REAL_PROJECT_IDS and (identity_class, status) != ("canonical_real", "real_source_slice"):
        _issue(issues, StructureShapeMatrixIssueCode.IDENTITY_STATUS_MISMATCH, project_id, "real project identity and source status must remain aligned")
    if project_id in EXPECTED_CANDIDATE_PROJECT_IDS and (identity_class, status) != ("candidate_only", "source_manifest_only"):
        _issue(issues, StructureShapeMatrixIssueCode.IDENTITY_STATUS_MISMATCH, project_id, "candidate identity and source-only status must remain aligned")
    if not _relative_reference(value.get("evidence_locator")):
        _issue(issues, StructureShapeMatrixIssueCode.REFERENCE_INVALID, f"{project_id}.evidence_locator", "evidence locator must be relative and path-safe")
    _check_source_revision(value.get("source_revision"), subject=f"{project_id}.source_revision", issues=issues)

    listing = value.get("listing")
    if not isinstance(listing, Mapping):
        _issue(issues, StructureShapeMatrixIssueCode.PROJECT_LIST_INVALID, f"{project_id}.listing", "listing shape summary is required")
    else:
        for field_name in ("sheet_count", "row_count", "subject_count", "site_count"):
            if not _nonnegative_int(listing.get(field_name)):
                _issue(issues, StructureShapeMatrixIssueCode.COUNT_INVALID, f"{project_id}.listing.{field_name}", "listing count must be non-negative")
    domains = value.get("observed_domains")
    if not isinstance(domains, list) or not domains or any(not _nonempty_text(item) for item in domains):
        _issue(issues, StructureShapeMatrixIssueCode.DOMAIN_LIST_INVALID, f"{project_id}.observed_domains", "observed domains must be a non-empty string list")
    else:
        normalized = [_text(item).upper() for item in domains]
        if len(normalized) != len(set(normalized)):
            _issue(issues, StructureShapeMatrixIssueCode.DOMAIN_DUPLICATE, project_id, "observed domains must be unique")
        for domain in normalized:
            if domain not in ALLOWED_DOMAINS:
                _issue(issues, StructureShapeMatrixIssueCode.DOMAIN_UNKNOWN, f"{project_id}.observed_domains", "observed domain is outside the neutral vocabulary")
    if not _nonnegative_int(value.get("unclassified_sheet_count")):
        _issue(issues, StructureShapeMatrixIssueCode.UNCLASSIFIED_COUNT_INVALID, f"{project_id}.unclassified_sheet_count", "unclassified sheet count must be non-negative")
    if value.get("structural_disposition") != "observed_aggregate_not_semantic_mapping":
        _issue(issues, StructureShapeMatrixIssueCode.STRUCTURAL_DISPOSITION_INVALID, f"{project_id}.structural_disposition", "shape evidence must remain non-semantic")
    return project_id


def assess_structure_shape_matrix(matrix: Mapping[str, Any]) -> StructureShapeMatrixReport:
    """Validate recorded aggregate shape evidence without opening any source."""

    if not isinstance(matrix, Mapping):
        raise StructureShapeMatrixError("shape matrix must be a mapping")
    issues: list[StructureShapeMatrixIssue] = []
    if _text(matrix.get("schema_version")) != STRUCTURE_SHAPE_MATRIX_SCHEMA_VERSION:
        _issue(issues, StructureShapeMatrixIssueCode.SCHEMA_VERSION_INVALID, "matrix.schema_version", "unexpected shape matrix schema")
    if matrix.get("provenance_kind") != EXPECTED_PROVENANCE_KIND:
        _issue(issues, StructureShapeMatrixIssueCode.CONTRACT_PROVENANCE_INVALID, "matrix.provenance_kind", "matrix must declare recorded aggregate provenance")
    for field_name in ("artifact_ref", "source_evidence_ref"):
        if not _relative_reference(matrix.get(field_name)):
            _issue(issues, StructureShapeMatrixIssueCode.REFERENCE_INVALID, f"matrix.{field_name}", "reference must be relative and path-safe")
    _check_flags(
        matrix.get("authority"),
        subject="matrix.authority",
        expected={
            "read_only": True,
            "candidate_only": True,
            "canonical_project_set_changed": False,
            "adapter_activation_permitted": False,
            "provider_call_permitted": False,
            "runtime_activation_permitted": False,
            "write_permitted": False,
            "medical_confirmation_permitted": False,
        },
        missing_code=StructureShapeMatrixIssueCode.AUTHORITY_MAPPING_MISSING,
        invalid_code=StructureShapeMatrixIssueCode.AUTHORITY_FLAG_INVALID,
        issues=issues,
    )
    _check_flags(
        matrix.get("retention"),
        subject="matrix.retention",
        expected={
            "absolute_paths_retained": False,
            "cell_values_retained": False,
            "subject_ids_retained": False,
            "semantic_ai_enabled": False,
            "field_mapping_created": False,
        },
        missing_code=StructureShapeMatrixIssueCode.RETENTION_MAPPING_MISSING,
        invalid_code=StructureShapeMatrixIssueCode.RETENTION_FLAG_INVALID,
        issues=issues,
    )
    projects = matrix.get("projects")
    project_ids: list[str] = []
    if not isinstance(projects, list) or not projects:
        _issue(issues, StructureShapeMatrixIssueCode.PROJECT_LIST_INVALID, "matrix.projects", "five project rows are required")
    else:
        for index, project in enumerate(projects):
            project_ids.append(_check_project(project, index=index, issues=issues))
        known_ids = [project_id for project_id in project_ids if project_id]
        if len(known_ids) != len(set(known_ids)):
            _issue(issues, StructureShapeMatrixIssueCode.PROJECT_ID_DUPLICATE, "matrix.projects", "project identities must be unique")
        if set(known_ids) != set(EXPECTED_PROJECT_IDS):
            _issue(issues, StructureShapeMatrixIssueCode.PROJECT_SET_INCOMPLETE, "matrix.projects", "the declared five-project matrix must not be narrowed or crosswalked")
    return StructureShapeMatrixReport(
        status="ready_for_generalization_review" if not issues else "blocked",
        project_ids=tuple(project_ids),
        issues=tuple(issues),
    )


__all__ = [
    "ALLOWED_DOMAINS",
    "EXPECTED_CANDIDATE_PROJECT_IDS",
    "EXPECTED_IMPLEMENTATION_STATUSES",
    "EXPECTED_PROJECT_IDS",
    "EXPECTED_PROVENANCE_KIND",
    "EXPECTED_REAL_PROJECT_IDS",
    "STRUCTURE_SHAPE_MATRIX_CONTRACT_VERSION",
    "STRUCTURE_SHAPE_MATRIX_SCHEMA_VERSION",
    "StructureShapeMatrixError",
    "StructureShapeMatrixIssue",
    "StructureShapeMatrixIssueCode",
    "StructureShapeMatrixReport",
    "assess_structure_shape_matrix",
]
