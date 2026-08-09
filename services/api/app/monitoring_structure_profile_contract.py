"""Diagnostic contract for a persisted, candidate-only structure profile.

The structure profile is a deliberately small, aggregate artifact produced by
the raw-intake path.  This validator checks its shape and identity boundary
without reopening a workbook or protocol, resolving a path, retaining cell or
subject values, calling an AI provider, registering an adapter, or granting
runtime or medical authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping


STRUCTURE_PROFILE_SCHEMA_VERSION = "medical_monitoring_candidate_structural_discovery_v1"
STRUCTURE_PROFILE_CONTRACT_SCHEMA_VERSION = "medical_monitoring_structure_profile_contract_v1"
EXPECTED_PROFILE_PROCESSING_STATUS = "blocked_external_ai_not_ready"
EXPECTED_ADMISSION_STATE = "candidate_only"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class StructureProfileContractError(ValueError):
    """Raised when the contract itself receives an invalid top-level value."""


class StructureProfileIssueCode(str, Enum):
    SCHEMA_VERSION_INVALID = "schema_version_invalid"
    ARTIFACT_REFERENCE_INVALID = "artifact_reference_invalid"
    SOURCE_DESCRIPTOR_REFERENCE_INVALID = "source_descriptor_reference_invalid"
    AUTHORITY_MAPPING_MISSING = "authority_mapping_missing"
    AUTHORITY_FLAG_INVALID = "authority_flag_invalid"
    PROCESSING_MAPPING_MISSING = "processing_mapping_missing"
    PROCESSING_FLAG_INVALID = "processing_flag_invalid"
    PROCESSING_VALUE_INVALID = "processing_value_invalid"
    PROJECT_LIST_INVALID = "project_list_invalid"
    PROJECT_MAPPING_INVALID = "project_mapping_invalid"
    PROJECT_ID_MISSING = "project_id_missing"
    PROJECT_ID_DUPLICATE = "project_id_duplicate"
    ADMISSION_STATE_INVALID = "admission_state_invalid"
    SOURCE_ANCHOR_INVALID = "source_anchor_invalid"
    SOURCE_FILENAME_INVALID = "source_filename_invalid"
    SOURCE_BYTES_INVALID = "source_bytes_invalid"
    SOURCE_SHA256_INVALID = "source_sha256_invalid"
    LISTING_SUMMARY_INVALID = "listing_summary_invalid"
    LISTING_COUNT_INVALID = "listing_count_invalid"
    SHEET_ROW_COUNTS_INVALID = "sheet_row_counts_invalid"
    SHEET_ROW_COUNT_SUM_MISMATCH = "sheet_row_count_sum_mismatch"
    IDENTIFIER_FIELDS_INVALID = "identifier_fields_invalid"
    DOMAIN_GROUPS_INVALID = "domain_groups_invalid"
    DOMAIN_GROUP_MAPPING_INVALID = "domain_group_mapping_invalid"
    DOMAIN_GROUP_COUNT_INVALID = "domain_group_count_invalid"
    DOMAIN_GROUP_SHEETS_INVALID = "domain_group_sheets_invalid"
    DOMAIN_GROUP_SHEET_UNKNOWN = "domain_group_sheet_unknown"
    DOMAIN_GROUP_SHEET_DUPLICATE = "domain_group_sheet_duplicate"
    DOMAIN_GROUP_COUNT_EXCEEDS_LISTING = "domain_group_count_exceeds_listing"
    UNCLASSIFIED_SHEETS_INVALID = "unclassified_sheets_invalid"
    UNCLASSIFIED_SHEET_UNKNOWN = "unclassified_sheet_unknown"
    UNCLASSIFIED_SHEET_DUPLICATE = "unclassified_sheet_duplicate"
    CLASSIFICATION_PARTITION_INCOMPLETE = "classification_partition_incomplete"
    CLASSIFICATION_OVERLAP = "classification_overlap"
    PROTOCOL_SUMMARY_INVALID = "protocol_summary_invalid"
    PROTOCOL_COUNT_INVALID = "protocol_count_invalid"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:  # pragma: no cover - Mapping input is JSON-shaped.
        raise StructureProfileContractError("structure profile must be JSON serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_safe_filename(value: Any) -> bool:
    filename = _text(value)
    return bool(
        _nonempty_text(value)
        and filename not in {".", ".."}
        and "\x00" not in filename
        and "/" not in filename
        and "\\" not in filename
    )


def _is_relative_reference(value: Any) -> bool:
    reference = _text(value)
    return bool(
        _nonempty_text(value)
        and not reference.startswith(("/", "~"))
        and not re.match(r"^[A-Za-z]:[\\/]", reference)
        and "\x00" not in reference
        and ".." not in re.split(r"[/\\]", reference)
    )


@dataclass(frozen=True)
class StructureProfileIssue:
    code: StructureProfileIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise StructureProfileContractError("issue subject and detail are required")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class StructureProfileContractReport:
    """Stable, redacted, diagnostic-only result for one persisted profile."""

    status: str
    project_ids: tuple[str, ...]
    issues: tuple[StructureProfileIssue, ...] = ()
    schema_version: str = STRUCTURE_PROFILE_CONTRACT_SCHEMA_VERSION
    diagnostic_only: bool = True
    candidate_only: bool = True
    offline_only: bool = True
    structure_parse_permitted: bool = False
    adapter_activation_permitted: bool = False
    provider_call_permitted: bool = False
    runtime_activation_permitted: bool = False
    write_permitted: bool = False
    medical_confirmation_permitted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != STRUCTURE_PROFILE_CONTRACT_SCHEMA_VERSION:
            raise StructureProfileContractError("unsupported structure profile contract schema version")
        if self.status not in {"blocked", "ready_for_mapping"}:
            raise StructureProfileContractError("invalid structure profile contract status")
        if any(not _text(project_id) for project_id in self.project_ids):
            raise StructureProfileContractError("project_ids must not contain empty values")
        for name in (
            "diagnostic_only",
            "candidate_only",
            "offline_only",
            "structure_parse_permitted",
            "adapter_activation_permitted",
            "provider_call_permitted",
            "runtime_activation_permitted",
            "write_permitted",
            "medical_confirmation_permitted",
        ):
            if not isinstance(getattr(self, name), bool):
                raise StructureProfileContractError(f"{name} must be boolean")
        if not (self.diagnostic_only and self.candidate_only and self.offline_only):
            raise StructureProfileContractError("structure profile contract must remain offline and candidate-only")
        if any(
            (
                self.structure_parse_permitted,
                self.adapter_activation_permitted,
                self.provider_call_permitted,
                self.runtime_activation_permitted,
                self.write_permitted,
                self.medical_confirmation_permitted,
            )
        ):
            raise StructureProfileContractError("structure profile contract cannot grant execution authority")
        issues = tuple(self.issues)
        expected_status = "ready_for_mapping" if not issues else "blocked"
        if self.status != expected_status:
            raise StructureProfileContractError("status does not match structure profile issues")
        if any(not isinstance(item, StructureProfileIssue) for item in issues):
            raise StructureProfileContractError("issues must contain StructureProfileIssue rows")
        object.__setattr__(
            self,
            "issues",
            tuple(sorted(issues, key=lambda item: (item.subject, item.code.value, item.detail))),
        )
        object.__setattr__(self, "project_ids", tuple(sorted({_text(item) for item in self.project_ids})))
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "project_ids": list(self.project_ids),
            "issues": [item.to_dict() for item in self.issues],
            "diagnostic_only": self.diagnostic_only,
            "candidate_only": self.candidate_only,
            "offline_only": self.offline_only,
            "structure_parse_permitted": self.structure_parse_permitted,
            "adapter_activation_permitted": self.adapter_activation_permitted,
            "provider_call_permitted": self.provider_call_permitted,
            "runtime_activation_permitted": self.runtime_activation_permitted,
            "write_permitted": self.write_permitted,
            "medical_confirmation_permitted": self.medical_confirmation_permitted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "issue_count": len(self.issues), "report_sha256": self.report_sha256}


def _issue(
    issues: list[StructureProfileIssue],
    code: StructureProfileIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(StructureProfileIssue(code, subject, detail))


def _check_boolean_flags(
    value: Any,
    *,
    subject: str,
    expected: Mapping[str, bool],
    missing_code: StructureProfileIssueCode,
    invalid_code: StructureProfileIssueCode,
    issues: list[StructureProfileIssue],
) -> None:
    if not isinstance(value, Mapping):
        _issue(issues, missing_code, subject, "the profile must declare the required flags")
        return
    for name, expected_value in expected.items():
        actual = value.get(name)
        if not isinstance(actual, bool) or actual is not expected_value:
            _issue(issues, invalid_code, f"{subject}.{name}", "flag does not satisfy the candidate-only boundary")


def _check_count_fields(
    value: Any,
    *,
    subject: str,
    fields: tuple[str, ...],
    issues: list[StructureProfileIssue],
) -> bool:
    if not isinstance(value, Mapping):
        _issue(issues, StructureProfileIssueCode.LISTING_SUMMARY_INVALID, subject, "summary must be an object")
        return False
    valid = True
    for field_name in fields:
        if not _is_nonnegative_int(value.get(field_name)):
            valid = False
            _issue(
                issues,
                StructureProfileIssueCode.LISTING_COUNT_INVALID,
                f"{subject}.{field_name}",
                "count must be a non-negative integer",
            )
    return valid


def _check_identifier_fields(value: Any, *, subject: str, issues: list[StructureProfileIssue]) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(not _nonempty_text(item) for item in value)
        or len(value) != len({item.strip() for item in value if isinstance(item, str)})
    ):
        _issue(
            issues,
            StructureProfileIssueCode.IDENTIFIER_FIELDS_INVALID,
            subject,
            "identifier fields must be a non-empty list of unique names",
        )


def _check_source_anchor(
    value: Any,
    *,
    subject: str,
    issues: list[StructureProfileIssue],
) -> None:
    if not isinstance(value, Mapping):
        _issue(issues, StructureProfileIssueCode.SOURCE_ANCHOR_INVALID, subject, "source anchor must be an object")
        return
    for filename_field in ("listing_filename", "protocol_filename"):
        if not _is_safe_filename(value.get(filename_field)):
            _issue(
                issues,
                StructureProfileIssueCode.SOURCE_FILENAME_INVALID,
                f"{subject}.{filename_field}",
                "source anchor must retain a basename only",
            )
    for bytes_field in ("listing_bytes", "protocol_bytes"):
        if not _is_nonnegative_int(value.get(bytes_field)):
            _issue(
                issues,
                StructureProfileIssueCode.SOURCE_BYTES_INVALID,
                f"{subject}.{bytes_field}",
                "source byte count must be a non-negative integer",
            )
    for hash_field in ("listing_sha256", "protocol_sha256"):
        hash_value = _text(value.get(hash_field))
        if not _SHA256_RE.fullmatch(hash_value):
            _issue(
                issues,
                StructureProfileIssueCode.SOURCE_SHA256_INVALID,
                f"{subject}.{hash_field}",
                "source hash must be a lowercase SHA-256 digest",
            )


def _check_listing_summary(
    value: Any,
    *,
    subject: str,
    issues: list[StructureProfileIssue],
) -> set[str]:
    fields = ("row_count", "sheet_count", "subject_count", "site_count", "supplemental_file_count")
    valid_counts = _check_count_fields(value, subject=subject, fields=fields, issues=issues)
    if not isinstance(value, Mapping):
        return set()
    sheet_row_counts = value.get("sheet_row_counts")
    sheet_names: set[str] = set()
    if not isinstance(sheet_row_counts, Mapping):
        _issue(
            issues,
            StructureProfileIssueCode.SHEET_ROW_COUNTS_INVALID,
            f"{subject}.sheet_row_counts",
            "sheet_row_counts must be an object",
        )
    else:
        for sheet_name, row_count in sheet_row_counts.items():
            name = _text(sheet_name)
            if not name or "\x00" in name:
                _issue(
                    issues,
                    StructureProfileIssueCode.SHEET_ROW_COUNTS_INVALID,
                    f"{subject}.sheet_row_counts",
                    "sheet names must be non-empty and NUL-free",
                )
                continue
            sheet_names.add(name)
            if not _is_nonnegative_int(row_count):
                _issue(
                    issues,
                    StructureProfileIssueCode.SHEET_ROW_COUNTS_INVALID,
                    f"{subject}.sheet_row_counts.{name}",
                    "sheet row count must be a non-negative integer",
                )
        if valid_counts and len(sheet_names) != value.get("sheet_count"):
            _issue(
                issues,
                StructureProfileIssueCode.SHEET_ROW_COUNTS_INVALID,
                f"{subject}.sheet_row_counts",
                "sheet count must equal the number of sheet row-count entries",
            )
        if valid_counts and all(_is_nonnegative_int(row_count) for row_count in sheet_row_counts.values()):
            if sum(sheet_row_counts.values()) != value.get("row_count"):
                _issue(
                    issues,
                    StructureProfileIssueCode.SHEET_ROW_COUNT_SUM_MISMATCH,
                    f"{subject}.sheet_row_counts",
                    "sheet row counts must sum to the listing row count",
                )
    _check_identifier_fields(value.get("subject_id_fields"), subject=f"{subject}.subject_id_fields", issues=issues)
    _check_identifier_fields(value.get("site_id_fields"), subject=f"{subject}.site_id_fields", issues=issues)
    return sheet_names


def _check_protocol_summary(
    value: Any,
    *,
    subject: str,
    issues: list[StructureProfileIssue],
) -> None:
    if not isinstance(value, Mapping):
        _issue(issues, StructureProfileIssueCode.PROTOCOL_SUMMARY_INVALID, subject, "protocol summary must be an object")
        return
    if not _is_safe_filename(value.get("filename")) or not _text(value.get("title")):
        _issue(
            issues,
            StructureProfileIssueCode.PROTOCOL_SUMMARY_INVALID,
            subject,
            "protocol summary requires a basename and a non-empty title",
        )
    for field_name in ("paragraph_count", "table_count", "span_count"):
        if not _is_nonnegative_int(value.get(field_name)):
            _issue(
                issues,
                StructureProfileIssueCode.PROTOCOL_COUNT_INVALID,
                f"{subject}.{field_name}",
                "protocol count must be a non-negative integer",
            )


def _check_project(
    value: Any,
    *,
    index: int,
    issues: list[StructureProfileIssue],
) -> str:
    subject = f"projects[{index}]"
    if not isinstance(value, Mapping):
        _issue(issues, StructureProfileIssueCode.PROJECT_MAPPING_INVALID, subject, "project row must be an object")
        return ""
    project_id = _text(value.get("project_id"))
    if not _nonempty_text(value.get("project_id")) or "/" in project_id or "\\" in project_id or "\x00" in project_id:
        _issue(issues, StructureProfileIssueCode.PROJECT_ID_MISSING, f"{subject}.project_id", "project identity must be opaque and path-free")
        project_id = f"unknown_{index}"
    if value.get("admission_state") != EXPECTED_ADMISSION_STATE:
        _issue(
            issues,
            StructureProfileIssueCode.ADMISSION_STATE_INVALID,
            f"{project_id}.admission_state",
            "structure profiles must remain candidate_only",
        )
    _check_source_anchor(value.get("source_anchor"), subject=f"{project_id}.source_anchor", issues=issues)
    sheet_names = _check_listing_summary(value.get("listing_summary"), subject=f"{project_id}.listing_summary", issues=issues)
    _check_protocol_summary(value.get("protocol_summary"), subject=f"{project_id}.protocol_summary", issues=issues)

    groups_value = value.get("domain_groups")
    classified: set[str] = set()
    group_rows = 0
    if not isinstance(groups_value, Mapping):
        _issue(issues, StructureProfileIssueCode.DOMAIN_GROUPS_INVALID, f"{project_id}.domain_groups", "domain_groups must be an object")
    else:
        for group_key, group in groups_value.items():
            group_name = _text(group_key)
            group_subject = f"{project_id}.domain_groups.{group_name or 'unknown'}"
            if not _nonempty_text(group_key):
                _issue(issues, StructureProfileIssueCode.DOMAIN_GROUPS_INVALID, group_subject, "domain group keys must be non-empty strings")
            if not isinstance(group, Mapping):
                _issue(issues, StructureProfileIssueCode.DOMAIN_GROUP_MAPPING_INVALID, group_subject, "domain group must be an object")
                continue
            for field_name in ("row_count", "subject_count"):
                if not _is_nonnegative_int(group.get(field_name)):
                    _issue(issues, StructureProfileIssueCode.DOMAIN_GROUP_COUNT_INVALID, f"{group_subject}.{field_name}", "domain count must be a non-negative integer")
            if _is_nonnegative_int(group.get("row_count")):
                group_rows += group["row_count"]
            group_sheets = group.get("sheet_names")
            if not isinstance(group_sheets, list) or not group_sheets:
                _issue(issues, StructureProfileIssueCode.DOMAIN_GROUP_SHEETS_INVALID, group_subject, "domain group must declare sheet names")
                continue
            local = [_text(item) for item in group_sheets]
            if any(not _nonempty_text(item) for item in group_sheets) or len(local) != len(set(local)):
                _issue(issues, StructureProfileIssueCode.DOMAIN_GROUP_SHEETS_INVALID, group_subject, "domain sheet names must be non-empty and unique")
            for sheet_name in local:
                if sheet_name in classified:
                    _issue(issues, StructureProfileIssueCode.DOMAIN_GROUP_SHEET_DUPLICATE, sheet_name, "a sheet must belong to one domain group")
                classified.add(sheet_name)
                if sheet_name not in sheet_names:
                    _issue(issues, StructureProfileIssueCode.DOMAIN_GROUP_SHEET_UNKNOWN, sheet_name, "domain group references an unknown sheet")

    listing_value = value.get("listing_summary")
    listing_row_count = listing_value.get("row_count") if isinstance(listing_value, Mapping) else None
    if _is_nonnegative_int(listing_row_count) and group_rows > listing_row_count:
        _issue(issues, StructureProfileIssueCode.DOMAIN_GROUP_COUNT_EXCEEDS_LISTING, project_id, "domain rows cannot exceed listing rows")

    unclassified_value = value.get("unclassified_sheet_names")
    unclassified: set[str] = set()
    if not isinstance(unclassified_value, list):
        _issue(issues, StructureProfileIssueCode.UNCLASSIFIED_SHEETS_INVALID, f"{project_id}.unclassified_sheet_names", "unclassified sheets must be a list")
    else:
        names = [_text(item) for item in unclassified_value]
        if any(not _nonempty_text(item) for item in unclassified_value):
            _issue(issues, StructureProfileIssueCode.UNCLASSIFIED_SHEETS_INVALID, f"{project_id}.unclassified_sheet_names", "unclassified sheet names must be non-empty")
        if len(names) != len(set(names)):
            _issue(issues, StructureProfileIssueCode.UNCLASSIFIED_SHEET_DUPLICATE, f"{project_id}.unclassified_sheet_names", "unclassified sheet names must be unique")
        unclassified = set(names)
        for sheet_name in unclassified:
            if sheet_name not in sheet_names:
                _issue(issues, StructureProfileIssueCode.UNCLASSIFIED_SHEET_UNKNOWN, sheet_name, "unclassified list references an unknown sheet")
        if classified & unclassified:
            _issue(issues, StructureProfileIssueCode.CLASSIFICATION_OVERLAP, project_id, "classified and unclassified sheet sets must be disjoint")
        if sheet_names and (classified | unclassified) != sheet_names:
            _issue(issues, StructureProfileIssueCode.CLASSIFICATION_PARTITION_INCOMPLETE, project_id, "every sheet must be classified or explicitly unclassified")
    return project_id


def assess_structure_profile(profile: Mapping[str, Any]) -> StructureProfileContractReport:
    """Validate a persisted aggregate profile without resolving any source."""

    if not isinstance(profile, Mapping):
        raise StructureProfileContractError("structure profile must be a mapping")

    issues: list[StructureProfileIssue] = []
    if _text(profile.get("schema_version")) != STRUCTURE_PROFILE_SCHEMA_VERSION:
        _issue(issues, StructureProfileIssueCode.SCHEMA_VERSION_INVALID, "profile.schema_version", "unexpected structural profile schema")
    if not _is_relative_reference(profile.get("artifact_ref")):
        _issue(issues, StructureProfileIssueCode.ARTIFACT_REFERENCE_INVALID, "profile.artifact_ref", "artifact reference must be relative and NUL-free")
    if not _is_relative_reference(profile.get("source_descriptor_ref")):
        _issue(issues, StructureProfileIssueCode.SOURCE_DESCRIPTOR_REFERENCE_INVALID, "profile.source_descriptor_ref", "source descriptor reference must be relative and NUL-free")

    _check_boolean_flags(
        profile.get("authority"),
        subject="profile.authority",
        expected={
            "read_only": True,
            "candidate_only": True,
            "canonical_project_set_changed": False,
            "adapter_registration_changed": False,
            "prompt_manifest_changed": False,
            "provider_call_permitted": False,
            "runtime_activation_permitted": False,
            "browser_login_permitted": False,
            "source_registry_write_permitted": False,
            "write_permitted": False,
            "medical_confirmation_permitted": False,
        },
        missing_code=StructureProfileIssueCode.AUTHORITY_MAPPING_MISSING,
        invalid_code=StructureProfileIssueCode.AUTHORITY_FLAG_INVALID,
        issues=issues,
    )
    processing = profile.get("processing")
    _check_boolean_flags(
        processing,
        subject="profile.processing",
        expected={
            "absolute_source_paths_retained": False,
            "ai_provider_configured": False,
            "cell_values_retained": False,
            "legacy_derived_inputs_used": False,
            "semantic_ai_tasks_enabled": False,
            "subject_ids_retained": False,
        },
        missing_code=StructureProfileIssueCode.PROCESSING_MAPPING_MISSING,
        invalid_code=StructureProfileIssueCode.PROCESSING_FLAG_INVALID,
        issues=issues,
    )
    if isinstance(processing, Mapping):
        for field_name in ("service", "source_system"):
            if not _text(processing.get(field_name)):
                _issue(issues, StructureProfileIssueCode.PROCESSING_VALUE_INVALID, f"profile.processing.{field_name}", "processing identity must be declared")
        if processing.get("ai_task_plan_status") != EXPECTED_PROFILE_PROCESSING_STATUS:
            _issue(issues, StructureProfileIssueCode.PROCESSING_VALUE_INVALID, "profile.processing.ai_task_plan_status", "semantic AI task plan must remain blocked")

    projects = profile.get("projects")
    project_ids: list[str] = []
    if not isinstance(projects, list) or not projects:
        _issue(issues, StructureProfileIssueCode.PROJECT_LIST_INVALID, "profile.projects", "profile must contain one or more project rows")
    else:
        for index, project in enumerate(projects):
            project_ids.append(_check_project(project, index=index, issues=issues))
        known_ids = [project_id for project_id in project_ids if project_id]
        if len(known_ids) != len(set(known_ids)):
            _issue(issues, StructureProfileIssueCode.PROJECT_ID_DUPLICATE, "profile.projects", "project identities must be unique")

    return StructureProfileContractReport(
        status="ready_for_mapping" if not issues else "blocked",
        project_ids=tuple(project_ids),
        issues=tuple(issues),
    )


__all__ = [
    "EXPECTED_ADMISSION_STATE",
    "EXPECTED_PROFILE_PROCESSING_STATUS",
    "STRUCTURE_PROFILE_CONTRACT_SCHEMA_VERSION",
    "STRUCTURE_PROFILE_SCHEMA_VERSION",
    "StructureProfileContractError",
    "StructureProfileContractReport",
    "StructureProfileIssue",
    "StructureProfileIssueCode",
    "assess_structure_profile",
]
