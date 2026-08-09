"""Read-only source-manifest preconditions for future structure parsing.

The public project source manifest is the last safe boundary before a future
structure-driven parser.  This module checks only declarative source identity
and availability.  It never opens a workbook or protocol, registers an
adapter, promotes a source, calls a provider, writes runtime state, or grants
medical authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any, Mapping


MANIFEST_PRECONDITION_SCHEMA_VERSION = "medical_monitoring_manifest_preconditions_v1"
ALLOWED_IMPLEMENTATION_STATUSES = frozenset(
    {"real_source_slice", "source_manifest_only"}
)
LISTING_SOURCE_ROLES = frozenset({"monitoring_listing", "monitoring_locked_dataset"})
PROTOCOL_SOURCE_ROLES = frozenset({"protocol_docx", "clinical_study_protocol"})


class ManifestPreconditionError(ValueError):
    """Raised only when the validator itself receives an invalid top-level type."""


class ManifestPreconditionIssueCode(str, Enum):
    PROJECT_ID_MISSING = "project_id_missing"
    MONITORING_BINDING_MISSING = "monitoring_binding_missing"
    IMPLEMENTATION_STATUS_UNSUPPORTED = "implementation_status_unsupported"
    ROUTE_PROJECT_ID_MISSING = "route_project_id_missing"
    SOURCE_LIST_MISSING = "source_list_missing"
    SOURCE_ID_MISSING = "source_id_missing"
    SOURCE_ID_DUPLICATE = "source_id_duplicate"
    SOURCE_ROLE_MISSING = "source_role_missing"
    SOURCE_AVAILABILITY_INVALID = "source_availability_invalid"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_ID_UNKNOWN = "source_id_unknown"
    PRIMARY_SOURCE_LIST_MISSING = "primary_source_list_missing"
    PRIMARY_LISTING_MISSING = "primary_listing_missing"
    PRIMARY_PROTOCOL_MISSING = "primary_protocol_missing"


def _text(value: Any) -> str:
    """Return only actual text fields; never stringify malformed metadata."""

    if not isinstance(value, str):
        return ""
    return value.strip()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:  # pragma: no cover - guarded by mapping input.
        raise ManifestPreconditionError("manifest precondition payload must be JSON serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ManifestPreconditionIssue:
    code: ManifestPreconditionIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise ManifestPreconditionError("issue subject and detail are required")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "subject": self.subject,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ManifestPreconditionReport:
    """Diagnostic-only result for a future structure-parser handoff."""

    status: str
    project_id: str
    implementation_status: str
    issues: tuple[ManifestPreconditionIssue, ...] = ()
    schema_version: str = MANIFEST_PRECONDITION_SCHEMA_VERSION
    diagnostic_only: bool = True
    structure_parse_permitted: bool = False
    adapter_activation_permitted: bool = False
    provider_call_permitted: bool = False
    write_permitted: bool = False
    medical_confirmation_permitted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != MANIFEST_PRECONDITION_SCHEMA_VERSION:
            raise ManifestPreconditionError("unsupported manifest precondition schema version")
        if self.status not in {"blocked", "ready_for_structure_parse"}:
            raise ManifestPreconditionError("invalid manifest precondition status")
        if not _text(self.project_id):
            raise ManifestPreconditionError("project_id must not be empty")
        if not _text(self.implementation_status):
            raise ManifestPreconditionError("implementation_status must not be empty")
        for name in (
            "diagnostic_only",
            "structure_parse_permitted",
            "adapter_activation_permitted",
            "provider_call_permitted",
            "write_permitted",
            "medical_confirmation_permitted",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ManifestPreconditionError(f"{name} must be boolean")
        if self.diagnostic_only is not True:
            raise ManifestPreconditionError("manifest preconditions must remain diagnostic_only")
        if any(
            (
                self.structure_parse_permitted,
                self.adapter_activation_permitted,
                self.provider_call_permitted,
                self.write_permitted,
                self.medical_confirmation_permitted,
            )
        ):
            raise ManifestPreconditionError("manifest preconditions cannot grant execution authority")
        issues = tuple(self.issues)
        expected_status = "ready_for_structure_parse" if not issues else "blocked"
        if self.status != expected_status:
            raise ManifestPreconditionError("status does not match manifest precondition issues")
        if any(not isinstance(item, ManifestPreconditionIssue) for item in issues):
            raise ManifestPreconditionError("issues must contain ManifestPreconditionIssue rows")
        object.__setattr__(self, "issues", tuple(sorted(issues, key=lambda item: (item.subject, item.code.value, item.detail))))
        object.__setattr__(self, "project_id", _text(self.project_id))
        object.__setattr__(self, "implementation_status", _text(self.implementation_status))
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "project_id": self.project_id,
            "implementation_status": self.implementation_status,
            "issues": [item.to_dict() for item in self.issues],
            "diagnostic_only": self.diagnostic_only,
            "structure_parse_permitted": self.structure_parse_permitted,
            "adapter_activation_permitted": self.adapter_activation_permitted,
            "provider_call_permitted": self.provider_call_permitted,
            "write_permitted": self.write_permitted,
            "medical_confirmation_permitted": self.medical_confirmation_permitted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "issue_count": len(self.issues), "report_sha256": self.report_sha256}


def _issue(
    issues: list[ManifestPreconditionIssue],
    code: ManifestPreconditionIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(ManifestPreconditionIssue(code, subject, detail))


def assess_manifest_preconditions(
    manifest: Mapping[str, Any],
) -> ManifestPreconditionReport:
    """Check a public source manifest without resolving any local path."""

    if not isinstance(manifest, Mapping):
        raise ManifestPreconditionError("manifest must be a mapping")

    issues: list[ManifestPreconditionIssue] = []
    project_id = _text(manifest.get("project_id"))
    if not project_id:
        _issue(
            issues,
            ManifestPreconditionIssueCode.PROJECT_ID_MISSING,
            "manifest.project_id",
            "public manifest must declare an opaque project identity",
        )
        project_id = "unknown"

    bindings = manifest.get("route_bindings")
    monitoring = bindings.get("medical_monitoring") if isinstance(bindings, Mapping) else None
    if not isinstance(monitoring, Mapping):
        _issue(
            issues,
            ManifestPreconditionIssueCode.MONITORING_BINDING_MISSING,
            project_id,
            "medical_monitoring route binding is required before structure parsing",
        )
        monitoring = {}

    implementation_status = _text(monitoring.get("implementation_status"))
    if implementation_status not in ALLOWED_IMPLEMENTATION_STATUSES:
        _issue(
            issues,
            ManifestPreconditionIssueCode.IMPLEMENTATION_STATUS_UNSUPPORTED,
            f"{project_id}:medical_monitoring",
            "implementation_status must be real_source_slice or source_manifest_only",
        )

    if not _text(monitoring.get("route_project_id")):
        _issue(
            issues,
            ManifestPreconditionIssueCode.ROUTE_PROJECT_ID_MISSING,
            f"{project_id}:medical_monitoring",
            "route_project_id is required; aliases must remain explicit",
        )

    sources_value = manifest.get("sources")
    if not isinstance(sources_value, list):
        _issue(
            issues,
            ManifestPreconditionIssueCode.SOURCE_LIST_MISSING,
            project_id,
            "public manifest sources must be a list",
        )
        source_rows: list[Mapping[str, Any]] = []
    else:
        source_rows = [item for item in sources_value if isinstance(item, Mapping)]
        if len(source_rows) != len(sources_value):
            _issue(
                issues,
                ManifestPreconditionIssueCode.SOURCE_LIST_MISSING,
                project_id,
                "every public manifest source row must be an object",
            )

    sources_by_id: dict[str, Mapping[str, Any]] = {}
    for index, source in enumerate(source_rows):
        source_id = _text(source.get("source_id"))
        subject = f"{project_id}:sources[{index}]"
        if not source_id:
            _issue(issues, ManifestPreconditionIssueCode.SOURCE_ID_MISSING, subject, "source_id is required")
            continue
        if source_id in sources_by_id:
            _issue(
                issues,
                ManifestPreconditionIssueCode.SOURCE_ID_DUPLICATE,
                source_id,
                "source_id must be unique in the public manifest",
            )
        else:
            sources_by_id[source_id] = source
        if not _text(source.get("source_role")):
            _issue(
                issues,
                ManifestPreconditionIssueCode.SOURCE_ROLE_MISSING,
                source_id,
                "source_role is required for structure-parser routing",
            )
        availability = source.get("availability")
        if availability not in {"available", "missing"}:
            _issue(
                issues,
                ManifestPreconditionIssueCode.SOURCE_AVAILABILITY_INVALID,
                source_id,
                "availability must be the public value available or missing",
            )
        elif availability == "missing":
            _issue(
                issues,
                ManifestPreconditionIssueCode.SOURCE_UNAVAILABLE,
                source_id,
                "all sources selected for structure parsing must be available",
            )

    def _ids(field_name: str) -> tuple[str, ...]:
        value = monitoring.get(field_name)
        if not isinstance(value, list):
            _issue(
                issues,
                ManifestPreconditionIssueCode.PRIMARY_SOURCE_LIST_MISSING,
                f"{project_id}:medical_monitoring.{field_name}",
                f"{field_name} must be a list",
            )
            return ()
        result = tuple(_text(item) for item in value if _text(item))
        if len(result) != len(set(result)):
            _issue(
                issues,
                ManifestPreconditionIssueCode.SOURCE_ID_DUPLICATE,
                f"{project_id}:medical_monitoring.{field_name}",
                "source IDs must not repeat within or across binding lists",
            )
        return result

    primary_ids = _ids("primary_source_ids")
    supplemental_ids = _ids("supplemental_source_ids")
    if set(primary_ids) & set(supplemental_ids):
        _issue(
            issues,
            ManifestPreconditionIssueCode.SOURCE_ID_DUPLICATE,
            f"{project_id}:medical_monitoring",
            "a source ID cannot be both primary and supplemental",
        )
    for source_id in (*primary_ids, *supplemental_ids):
        source = sources_by_id.get(source_id)
        if source is None:
            _issue(
                issues,
                ManifestPreconditionIssueCode.SOURCE_ID_UNKNOWN,
                source_id,
                "binding references a source ID absent from the public manifest",
            )
        elif source.get("availability") != "available":
            # The source row already carries the more direct unavailable issue;
            # this second issue makes the selected binding failure explicit.
            _issue(
                issues,
                ManifestPreconditionIssueCode.SOURCE_UNAVAILABLE,
                source_id,
                "a referenced primary or supplemental source is not available",
            )

    primary_rows = [sources_by_id[source_id] for source_id in primary_ids if source_id in sources_by_id]
    primary_roles = {_text(source.get("source_role")) for source in primary_rows}
    if not primary_ids:
        _issue(
            issues,
            ManifestPreconditionIssueCode.PRIMARY_SOURCE_LIST_MISSING,
            f"{project_id}:medical_monitoring.primary_source_ids",
            "at least one primary source is required",
        )
    if not primary_roles & LISTING_SOURCE_ROLES:
        _issue(
            issues,
            ManifestPreconditionIssueCode.PRIMARY_LISTING_MISSING,
            f"{project_id}:medical_monitoring.primary_source_ids",
            "primary sources must include a listing or locked-dataset role",
        )
    if not primary_roles & PROTOCOL_SOURCE_ROLES:
        _issue(
            issues,
            ManifestPreconditionIssueCode.PRIMARY_PROTOCOL_MISSING,
            f"{project_id}:medical_monitoring.primary_source_ids",
            "primary sources must include a protocol role",
        )

    return ManifestPreconditionReport(
        status="ready_for_structure_parse" if not issues else "blocked",
        project_id=project_id,
        implementation_status=implementation_status or "unconfirmed",
        issues=tuple(issues),
    )


__all__ = [
    "ALLOWED_IMPLEMENTATION_STATUSES",
    "LISTING_SOURCE_ROLES",
    "MANIFEST_PRECONDITION_SCHEMA_VERSION",
    "ManifestPreconditionError",
    "ManifestPreconditionIssue",
    "ManifestPreconditionIssueCode",
    "ManifestPreconditionReport",
    "PROTOCOL_SOURCE_ROLES",
    "assess_manifest_preconditions",
]
