"""Read-only identity revalidation for monitoring project source candidates.

The commercial real-loop contracts intentionally start after project identity
and source lineage have been reconciled.  This module is the earlier, safer
boundary for the five project roots supplied for future testing.  It reopens
the declared protocol/listing files and verifies their bytes without
registering a source, promoting a project, calling a provider, or granting
medical/runtime authority.

In particular, a candidate MY008 project must not borrow the non-monitoring
``proj_my008_pnh_3_01`` identity, and two byte variants of one workbook must
not be silently merged into one baseline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


CANDIDATE_SOURCE_IDENTITY_SCHEMA_VERSION = (
    "medical_monitoring_candidate_source_identity_v1"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{1,239}$")
_ALLOWED_MAPPING_STATUSES = frozenset(
    {"reviewed", "blocked_pending_mapping_review", "not_reviewed"}
)


class CandidateSourceIdentityError(ValueError):
    """Raised when a candidate source identity payload is malformed."""


class CandidateSourceIdentityIssueCode(str, Enum):
    RECORD_INVALID = "record_invalid"
    PROJECT_SET_MISMATCH = "project_set_mismatch"
    PROJECT_DUPLICATE = "project_duplicate"
    PROJECT_IDENTITY_INVALID = "project_identity_invalid"
    CANDIDATE_CANONICAL_CONFLICT = "candidate_canonical_conflict"
    PATH_MISSING = "path_missing"
    PATH_NOT_FILE = "path_not_file"
    PATH_SYMLINK_UNSUPPORTED = "path_symlink_unsupported"
    BYTE_SIZE_MISMATCH = "byte_size_mismatch"
    SHA256_MISMATCH = "sha256_mismatch"
    CONTENT_DUPLICATE = "content_duplicate"
    ADAPTER_IDENTITY_MISMATCH = "adapter_identity_mismatch"
    ADAPTER_MISSING = "adapter_missing"
    NON_MONITORING_ALIAS_REUSE = "non_monitoring_alias_reuse"
    MAPPING_NOT_REVIEWED = "mapping_not_reviewed"
    SOURCE_NOT_CONFIRMED = "source_not_confirmed"
    FULL_SNAPSHOT_UNPROVEN = "full_snapshot_unproven"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_id(value: Any, field_name: str) -> str:
    normalized = _text(value)
    if not _SAFE_ID_RE.fullmatch(normalized):
        raise CandidateSourceIdentityError(
            f"{field_name} must be a non-empty opaque identifier"
        )
    return normalized


def _sha256(value: Any, field_name: str) -> str:
    normalized = _text(value).lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise CandidateSourceIdentityError(f"{field_name} must be a lowercase SHA-256")
    return normalized


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise CandidateSourceIdentityError(
            "candidate source identity payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidateSourceRecord:
    """One project identity with explicit protocol and listing byte anchors."""

    project_id: str
    label: str
    canonical_now: bool
    candidate_only: bool
    listing_path: str
    listing_bytes: int
    listing_sha256: str
    protocol_path: str
    protocol_bytes: int
    protocol_sha256: str
    source_class: str
    source_status: str
    full_snapshot_proven: bool
    adapter_registered: bool
    adapter_project_id: str
    mapping_status: str
    non_monitoring_aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", _safe_id(self.project_id, "project_id"))
        label = _text(self.label)
        if not label:
            raise CandidateSourceIdentityError("label must not be empty")
        object.__setattr__(self, "label", label)
        for field_name in (
            "canonical_now",
            "candidate_only",
            "full_snapshot_proven",
            "adapter_registered",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise CandidateSourceIdentityError(f"{field_name} must be boolean")
        if self.canonical_now and self.candidate_only:
            raise CandidateSourceIdentityError(
                "a record cannot be canonical_now and candidate_only"
            )
        for field_name in ("listing_path", "protocol_path"):
            path = _text(getattr(self, field_name))
            if not path:
                raise CandidateSourceIdentityError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, path)
        for field_name in ("listing_bytes", "protocol_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CandidateSourceIdentityError(
                    f"{field_name} must be a non-negative integer"
                )
        object.__setattr__(
            self, "listing_sha256", _sha256(self.listing_sha256, "listing_sha256")
        )
        object.__setattr__(
            self, "protocol_sha256", _sha256(self.protocol_sha256, "protocol_sha256")
        )
        source_class = _text(self.source_class)
        source_status = _text(self.source_status)
        if not source_class or not source_status:
            raise CandidateSourceIdentityError(
                "source_class and source_status must not be empty"
            )
        object.__setattr__(self, "source_class", source_class)
        object.__setattr__(self, "source_status", source_status)
        adapter_project_id = _text(self.adapter_project_id)
        object.__setattr__(self, "adapter_project_id", adapter_project_id)
        mapping_status = _text(self.mapping_status)
        if mapping_status not in _ALLOWED_MAPPING_STATUSES:
            raise CandidateSourceIdentityError(
                "mapping_status must be one of the closed candidate states"
            )
        object.__setattr__(self, "mapping_status", mapping_status)
        aliases = tuple(
            _safe_id(item, "non_monitoring_alias")
            for item in self.non_monitoring_aliases
        )
        if len(aliases) != len(set(aliases)):
            raise CandidateSourceIdentityError("non_monitoring_aliases must be unique")
        object.__setattr__(self, "non_monitoring_aliases", tuple(sorted(aliases)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "label": self.label,
            "canonical_now": self.canonical_now,
            "candidate_only": self.candidate_only,
            "listing_path": self.listing_path,
            "listing_bytes": self.listing_bytes,
            "listing_sha256": self.listing_sha256,
            "protocol_path": self.protocol_path,
            "protocol_bytes": self.protocol_bytes,
            "protocol_sha256": self.protocol_sha256,
            "source_class": self.source_class,
            "source_status": self.source_status,
            "full_snapshot_proven": self.full_snapshot_proven,
            "adapter_registered": self.adapter_registered,
            "adapter_project_id": self.adapter_project_id,
            "mapping_status": self.mapping_status,
            "non_monitoring_aliases": list(self.non_monitoring_aliases),
        }


def _candidate_file_metadata(
    path_value: str | Path, field_name: str
) -> tuple[str, int, str]:
    """Read only direct-file metadata for a candidate source anchor.

    The constructor intentionally rejects symlinks and non-files so a future
    candidate descriptor cannot silently bind to a generated/redirected
    sibling.  It does not classify the bytes or grant source admission.
    """

    path = Path(path_value)
    if path.is_symlink():
        raise CandidateSourceIdentityError(
            f"{field_name} path must be a direct regular file, not a symlink"
        )
    if not path.exists():
        raise CandidateSourceIdentityError(f"{field_name} path does not exist: {path}")
    if not path.is_file():
        raise CandidateSourceIdentityError(
            f"{field_name} path is not a regular file: {path}"
        )
    return str(path), path.stat().st_size, _file_sha256(path)


def build_candidate_source_record_from_paths(
    *,
    project_id: str,
    label: str,
    listing_path: str | Path,
    protocol_path: str | Path,
    source_class: str = "candidate_source_metadata",
    source_status: str = "candidate",
    mapping_status: str = "blocked_pending_mapping_review",
    non_monitoring_aliases: Iterable[str] = (),
) -> CandidateSourceRecord:
    """Build a diagnostic-only candidate record from two explicit files.

    This helper is deliberately candidate-only: it cannot create a canonical
    row, an executable adapter identity, a confirmed source, or a proven full
    snapshot.  The returned record still requires
    :func:`revalidate_candidate_source_identities` before it is useful as a
    byte anchor, and that report remains permanently non-authorizing.
    """

    listing = _candidate_file_metadata(listing_path, "listing")
    protocol = _candidate_file_metadata(protocol_path, "protocol")
    return CandidateSourceRecord(
        project_id=project_id,
        label=label,
        canonical_now=False,
        candidate_only=True,
        listing_path=listing[0],
        listing_bytes=listing[1],
        listing_sha256=listing[2],
        protocol_path=protocol[0],
        protocol_bytes=protocol[1],
        protocol_sha256=protocol[2],
        source_class=source_class,
        source_status=source_status,
        full_snapshot_proven=False,
        adapter_registered=False,
        adapter_project_id="",
        mapping_status=mapping_status,
        non_monitoring_aliases=tuple(non_monitoring_aliases),
    )


@dataclass(frozen=True)
class CandidateSourceIdentityIssue:
    code: CandidateSourceIdentityIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise CandidateSourceIdentityError("issue subject and detail are required")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "subject": self.subject,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CandidateSourceIdentityReport:
    """Hashable diagnostic result; it can never grant admission authority."""

    status: str
    identity_evidence_complete: bool
    project_ids: tuple[str, ...]
    observed_file_count: int
    issues: tuple[CandidateSourceIdentityIssue, ...]
    schema_version: str = CANDIDATE_SOURCE_IDENTITY_SCHEMA_VERSION
    diagnostic_only: bool = True
    runtime_activation_permitted: bool = False
    provider_call_permitted: bool = False
    write_permitted: bool = False
    medical_confirmation_permitted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != CANDIDATE_SOURCE_IDENTITY_SCHEMA_VERSION:
            raise CandidateSourceIdentityError(
                "unsupported candidate source identity schema version"
            )
        if self.status not in {"blocked", "revalidated_for_next_gate"}:
            raise CandidateSourceIdentityError("invalid candidate identity status")
        for name in (
            "identity_evidence_complete",
            "diagnostic_only",
            "runtime_activation_permitted",
            "provider_call_permitted",
            "write_permitted",
            "medical_confirmation_permitted",
        ):
            if not isinstance(getattr(self, name), bool):
                raise CandidateSourceIdentityError(f"{name} must be a strict boolean")
        if self.diagnostic_only is not True:
            raise CandidateSourceIdentityError(
                "candidate identity reports must remain diagnostic_only"
            )
        if any(
            (
                self.runtime_activation_permitted,
                self.provider_call_permitted,
                self.write_permitted,
                self.medical_confirmation_permitted,
            )
        ):
            raise CandidateSourceIdentityError(
                "candidate identity evidence cannot grant authority"
            )
        if (
            isinstance(self.observed_file_count, bool)
            or not isinstance(self.observed_file_count, int)
            or self.observed_file_count < 0
        ):
            raise CandidateSourceIdentityError(
                "observed_file_count must be a non-negative integer"
            )
        project_ids = tuple(_safe_id(item, "project_id") for item in self.project_ids)
        if len(project_ids) != len(set(project_ids)):
            raise CandidateSourceIdentityError("project_ids must be unique")
        issues = tuple(self.issues)
        expected_complete = not issues and self.status == "revalidated_for_next_gate"
        if self.identity_evidence_complete != expected_complete:
            raise CandidateSourceIdentityError(
                "identity_evidence_complete does not match status/issues"
            )
        object.__setattr__(self, "project_ids", tuple(sorted(project_ids)))
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "identity_evidence_complete": self.identity_evidence_complete,
            "project_ids": list(self.project_ids),
            "observed_file_count": self.observed_file_count,
            "issues": [item.to_dict() for item in self.issues],
            "diagnostic_only": self.diagnostic_only,
            "runtime_activation_permitted": self.runtime_activation_permitted,
            "provider_call_permitted": self.provider_call_permitted,
            "write_permitted": self.write_permitted,
            "medical_confirmation_permitted": self.medical_confirmation_permitted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
        }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _observe_file(
    record: CandidateSourceRecord,
    *,
    path_field: str,
    bytes_field: str,
    sha_field: str,
    issues: list[CandidateSourceIdentityIssue],
) -> bool:
    path = Path(getattr(record, path_field))
    subject = f"{record.project_id}:{path_field}"
    if path.is_symlink():
        issues.append(
            CandidateSourceIdentityIssue(
                CandidateSourceIdentityIssueCode.PATH_SYMLINK_UNSUPPORTED,
                subject,
                "declared source path must be a direct regular file, not a symlink",
            )
        )
        return False
    if not path.exists():
        issues.append(
            CandidateSourceIdentityIssue(
                CandidateSourceIdentityIssueCode.PATH_MISSING,
                subject,
                f"declared source path does not exist: {path}",
            )
        )
        return False
    if not path.is_file():
        issues.append(
            CandidateSourceIdentityIssue(
                CandidateSourceIdentityIssueCode.PATH_NOT_FILE,
                subject,
                f"declared source path is not a regular file: {path}",
            )
        )
        return False
    observed_bytes = path.stat().st_size
    expected_bytes = getattr(record, bytes_field)
    if observed_bytes != expected_bytes:
        issues.append(
            CandidateSourceIdentityIssue(
                CandidateSourceIdentityIssueCode.BYTE_SIZE_MISMATCH,
                subject,
                f"recorded bytes={expected_bytes}, observed bytes={observed_bytes}",
            )
        )
    observed_sha = _file_sha256(path)
    expected_sha = getattr(record, sha_field)
    if observed_sha != expected_sha:
        issues.append(
            CandidateSourceIdentityIssue(
                CandidateSourceIdentityIssueCode.SHA256_MISMATCH,
                subject,
                f"recorded sha256={expected_sha}, observed sha256={observed_sha}",
            )
        )
    return observed_bytes == expected_bytes and observed_sha == expected_sha


def revalidate_candidate_source_identities(
    records: Iterable[CandidateSourceRecord],
    *,
    required_project_ids: Iterable[str],
) -> CandidateSourceIdentityReport:
    """Reopen declared candidate files and fail closed on identity drift.

    This function only observes bytes and declarative fields.  It deliberately
    treats source confirmation, mapping review, adapter registration and full
    snapshot proof as requirements to report, not facts it may infer.
    """

    rows = tuple(records)
    required = tuple(
        sorted({_safe_id(item, "required_project_id") for item in required_project_ids})
    )
    issues: list[CandidateSourceIdentityIssue] = []
    observed_projects = [row.project_id for row in rows]
    if len(observed_projects) != len(set(observed_projects)):
        issues.append(
            CandidateSourceIdentityIssue(
                CandidateSourceIdentityIssueCode.PROJECT_DUPLICATE,
                "project_set",
                "each project identity must appear exactly once",
            )
        )
    if set(observed_projects) != set(required):
        issues.append(
            CandidateSourceIdentityIssue(
                CandidateSourceIdentityIssueCode.PROJECT_SET_MISMATCH,
                "project_set",
                f"required={list(required)}, observed={sorted(set(observed_projects))}",
            )
        )

    seen_content: dict[str, tuple[str, str]] = {}
    observed_file_count = 0
    for row in sorted(rows, key=lambda item: item.project_id):
        if not isinstance(row, CandidateSourceRecord):
            issues.append(
                CandidateSourceIdentityIssue(
                    CandidateSourceIdentityIssueCode.RECORD_INVALID,
                    "records",
                    "all rows must be CandidateSourceRecord instances",
                )
            )
            continue
        if row.canonical_now and row.candidate_only:
            issues.append(
                CandidateSourceIdentityIssue(
                    CandidateSourceIdentityIssueCode.CANDIDATE_CANONICAL_CONFLICT,
                    row.project_id,
                    "a project cannot be both current canonical and candidate-only",
                )
            )
        if row.adapter_registered and row.adapter_project_id != row.project_id:
            issues.append(
                CandidateSourceIdentityIssue(
                    CandidateSourceIdentityIssueCode.ADAPTER_IDENTITY_MISMATCH,
                    row.project_id,
                    "registered adapter identity must equal monitoring project identity",
                )
            )
        if not row.adapter_registered and row.adapter_project_id:
            issues.append(
                CandidateSourceIdentityIssue(
                    CandidateSourceIdentityIssueCode.ADAPTER_IDENTITY_MISMATCH,
                    row.project_id,
                    "an unregistered candidate cannot carry an executable adapter identity",
                )
            )
        if row.canonical_now and not row.adapter_registered:
            issues.append(
                CandidateSourceIdentityIssue(
                    CandidateSourceIdentityIssueCode.ADAPTER_MISSING,
                    row.project_id,
                    "current canonical monitoring projects require an explicit adapter",
                )
            )
        if row.project_id in row.non_monitoring_aliases:
            issues.append(
                CandidateSourceIdentityIssue(
                    CandidateSourceIdentityIssueCode.NON_MONITORING_ALIAS_REUSE,
                    row.project_id,
                    "a monitoring identity cannot reuse itself as a non-monitoring alias",
                )
            )
        if (
            row.adapter_project_id
            and row.adapter_project_id in row.non_monitoring_aliases
        ):
            issues.append(
                CandidateSourceIdentityIssue(
                    CandidateSourceIdentityIssueCode.NON_MONITORING_ALIAS_REUSE,
                    row.project_id,
                    "adapter_project_id reuses a non-monitoring alias",
                )
            )
        if row.mapping_status != "reviewed":
            issues.append(
                CandidateSourceIdentityIssue(
                    CandidateSourceIdentityIssueCode.MAPPING_NOT_REVIEWED,
                    row.project_id,
                    f"mapping_status={row.mapping_status}; protocol/listing mapping remains non-admissible",
                )
            )
        if row.source_status != "confirmed":
            issues.append(
                CandidateSourceIdentityIssue(
                    CandidateSourceIdentityIssueCode.SOURCE_NOT_CONFIRMED,
                    row.project_id,
                    "source_status must be confirmed before controlled admission",
                )
            )
        if row.full_snapshot_proven is not True:
            issues.append(
                CandidateSourceIdentityIssue(
                    CandidateSourceIdentityIssueCode.FULL_SNAPSHOT_UNPROVEN,
                    row.project_id,
                    "full_snapshot_proven must be explicitly true before controlled admission",
                )
            )

        listing_ok = _observe_file(
            row,
            path_field="listing_path",
            bytes_field="listing_bytes",
            sha_field="listing_sha256",
            issues=issues,
        )
        protocol_ok = _observe_file(
            row,
            path_field="protocol_path",
            bytes_field="protocol_bytes",
            sha_field="protocol_sha256",
            issues=issues,
        )
        observed_file_count += int(listing_ok) + int(protocol_ok)
        for content_kind, digest in (
            ("listing", row.listing_sha256),
            ("protocol", row.protocol_sha256),
        ):
            previous = seen_content.get(digest)
            if previous is not None:
                issues.append(
                    CandidateSourceIdentityIssue(
                        CandidateSourceIdentityIssueCode.CONTENT_DUPLICATE,
                        f"{row.project_id}:{content_kind}",
                        f"SHA-256 is already bound to {previous[0]}:{previous[1]}; duplicate paths are not independent project evidence",
                    )
                )
            else:
                seen_content[digest] = (row.project_id, content_kind)

    ordered_issues = tuple(
        sorted(issues, key=lambda item: (item.subject, item.code.value, item.detail))
    )
    complete = not ordered_issues and set(observed_projects) == set(required)
    return CandidateSourceIdentityReport(
        status="revalidated_for_next_gate" if complete else "blocked",
        identity_evidence_complete=complete,
        project_ids=tuple(observed_projects),
        observed_file_count=observed_file_count,
        issues=ordered_issues,
    )


__all__ = [
    "CANDIDATE_SOURCE_IDENTITY_SCHEMA_VERSION",
    "CandidateSourceIdentityError",
    "CandidateSourceIdentityIssue",
    "CandidateSourceIdentityIssueCode",
    "CandidateSourceIdentityReport",
    "CandidateSourceRecord",
    "build_candidate_source_record_from_paths",
    "revalidate_candidate_source_identities",
]
