"""Read-only revalidation for commercial nonfunctional control evidence.

The commercial dossier contract defines the controls that must eventually be
proved.  This module adds the filesystem boundary for the controls that are
not yet backed by a reusable runtime contract: it reopens a declared manifest,
checks safe workspace-relative paths, bytes, SHA-256 and one-to-one control
coverage, and reports the result without granting release or operational
authority.

It is deliberately diagnostic.  A fresh manifest proves only that the
declared evidence files are still the files that were recorded; it does not
prove that an installation, rollback, backup restore, security review or
training exercise actually happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .monitoring_release_dossier import REQUIRED_DOSSIER_CONTROLS


NONFUNCTIONAL_EVIDENCE_SCHEMA_VERSION = (
    "medical_monitoring_nonfunctional_evidence_revalidation_v1"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_SECTIONS = (
    "nonfunctional_validation",
    "installation_upgrade_rollback",
    "security_privacy_sbom",
    "audit_and_data_retention",
    "operations_support_training",
)
REQUIRED_NONFUNCTIONAL_CONTROL_IDS = tuple(
    control_id
    for section_id in _ALLOWED_SECTIONS
    for control_id in REQUIRED_DOSSIER_CONTROLS[section_id]
)
_CONTROL_TO_SECTION = {
    control_id: section_id
    for section_id in _ALLOWED_SECTIONS
    for control_id in REQUIRED_DOSSIER_CONTROLS[section_id]
}
_ALLOWED_STATUSES = {"passed", "partial", "unproven", "blocked"}


class NonfunctionalEvidenceRevalidationError(ValueError):
    """Raised when the revalidation request cannot be evaluated safely."""


class NonfunctionalEvidenceIssueCode(str, Enum):
    PAYLOAD_SHAPE_INVALID = "payload_shape_invalid"
    SCHEMA_VERSION_INVALID = "schema_version_invalid"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"
    RELEASE_READY_FLAG_TRUE = "release_ready_flag_true"
    RECORD_FIELD_INVALID = "record_field_invalid"
    RECORD_DUPLICATE = "record_duplicate"
    CONTROL_UNKNOWN = "control_unknown"
    CONTROL_SECTION_MISMATCH = "control_section_mismatch"
    CONTROL_DUPLICATE = "control_duplicate"
    CONTROL_MISSING = "control_missing"
    STATUS_INVALID = "status_invalid"
    PATH_UNSAFE = "path_unsafe"
    SOURCE_MISSING = "source_missing"
    SOURCE_NOT_FILE = "source_not_file"
    SOURCE_SYMLINK_UNSUPPORTED = "source_symlink_unsupported"
    SOURCE_BYTES_MISMATCH = "source_bytes_mismatch"
    SOURCE_SHA256_MISMATCH = "source_sha256_mismatch"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise NonfunctionalEvidenceRevalidationError(
            "revalidation payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and bool(_SHA256_RE.fullmatch(value))
    )


@dataclass(frozen=True)
class NonfunctionalEvidenceIssue:
    code: NonfunctionalEvidenceIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise NonfunctionalEvidenceRevalidationError(
                "issue subject and detail are required"
            )
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class NonfunctionalEvidenceRevalidationReport:
    """Immutable evidence identity result; never a release decision."""

    status: str
    evidence_fresh: bool
    record_count: int
    source_match_count: int
    control_count: int
    covered_control_ids: tuple[str, ...]
    unmet_control_ids: tuple[str, ...]
    control_statuses: tuple[tuple[str, str], ...]
    issues: tuple[NonfunctionalEvidenceIssue, ...]
    schema_version: str = NONFUNCTIONAL_EVIDENCE_SCHEMA_VERSION
    read_only: bool = True
    authority_granted: bool = False
    release_ready: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != NONFUNCTIONAL_EVIDENCE_SCHEMA_VERSION:
            raise NonfunctionalEvidenceRevalidationError(
                "unsupported nonfunctional evidence schema"
            )
        if self.status not in {"fresh", "blocked"}:
            raise NonfunctionalEvidenceRevalidationError("invalid revalidation status")
        if not isinstance(self.evidence_fresh, bool):
            raise NonfunctionalEvidenceRevalidationError(
                "evidence_fresh must be a strict boolean"
            )
        if self.read_only is not True or self.authority_granted is not False:
            raise NonfunctionalEvidenceRevalidationError(
                "revalidation reports must remain read-only and non-authoritative"
            )
        if self.release_ready is not False:
            raise NonfunctionalEvidenceRevalidationError(
                "nonfunctional revalidation cannot declare release readiness"
            )
        for name in ("record_count", "source_match_count", "control_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise NonfunctionalEvidenceRevalidationError(
                    f"{name} must be a non-negative integer"
                )
        covered = tuple(self.covered_control_ids)
        unmet = tuple(self.unmet_control_ids)
        if len(covered) != len(set(covered)) or len(unmet) != len(set(unmet)):
            raise NonfunctionalEvidenceRevalidationError(
                "control ID lists must not contain duplicates"
            )
        if set(covered) & set(unmet):
            raise NonfunctionalEvidenceRevalidationError(
                "covered and unmet control IDs must not overlap"
            )
        statuses = tuple(self.control_statuses)
        status_ids = tuple(item[0] for item in statuses)
        if len(status_ids) != len(set(status_ids)):
            raise NonfunctionalEvidenceRevalidationError(
                "control statuses must not contain duplicate IDs"
            )
        if tuple(status_ids) != tuple(
            item for item in REQUIRED_NONFUNCTIONAL_CONTROL_IDS if item in status_ids
        ):
            raise NonfunctionalEvidenceRevalidationError(
                "control statuses must use canonical control order"
            )
        if any(status not in _ALLOWED_STATUSES for _, status in statuses):
            raise NonfunctionalEvidenceRevalidationError(
                "control status is unsupported"
            )
        issues = tuple(self.issues)
        if any(not isinstance(item, NonfunctionalEvidenceIssue) for item in issues):
            raise NonfunctionalEvidenceRevalidationError(
                "issues contain an invalid value"
            )
        expected_fresh = not issues and set(covered) | set(unmet) == set(
            REQUIRED_NONFUNCTIONAL_CONTROL_IDS
        )
        if (
            self.evidence_fresh != expected_fresh
            or (self.status == "fresh") != expected_fresh
        ):
            raise NonfunctionalEvidenceRevalidationError(
                "revalidation status does not match issues/control coverage"
            )
        if self.control_count != len(statuses):
            raise NonfunctionalEvidenceRevalidationError(
                "control_count does not match control statuses"
            )
        object.__setattr__(self, "covered_control_ids", covered)
        object.__setattr__(self, "unmet_control_ids", unmet)
        object.__setattr__(self, "control_statuses", statuses)
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "evidence_fresh": self.evidence_fresh,
            "record_count": self.record_count,
            "source_match_count": self.source_match_count,
            "control_count": self.control_count,
            "covered_control_ids": list(self.covered_control_ids),
            "unmet_control_ids": list(self.unmet_control_ids),
            "control_statuses": [
                {"control_id": control_id, "status": status}
                for control_id, status in self.control_statuses
            ],
            "issues": [item.to_dict() for item in self.issues],
            "read_only": self.read_only,
            "authority_granted": self.authority_granted,
            "release_ready": self.release_ready,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "required_control_count": len(REQUIRED_NONFUNCTIONAL_CONTROL_IDS),
            "report_sha256": self.report_sha256,
        }


def _issue(
    issues: list[NonfunctionalEvidenceIssue],
    code: NonfunctionalEvidenceIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(NonfunctionalEvidenceIssue(code, subject, detail))


def _safe_relative_path(
    raw: Any,
    *,
    root: Path,
    issues: list[NonfunctionalEvidenceIssue],
    subject: str,
) -> Path | None:
    path_text = raw.strip() if isinstance(raw, str) else ""
    if not path_text:
        _issue(
            issues,
            NonfunctionalEvidenceIssueCode.PATH_UNSAFE,
            subject,
            "path is required",
        )
        return None
    path = Path(path_text)
    if (
        path.is_absolute()
        or "\\" in path_text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _issue(
            issues,
            NonfunctionalEvidenceIssueCode.PATH_UNSAFE,
            subject,
            "path must be a clean workspace-relative POSIX path without traversal",
        )
        return None
    root_resolved = root.resolve()
    candidate = root / path
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            _issue(
                issues,
                NonfunctionalEvidenceIssueCode.SOURCE_SYMLINK_UNSUPPORTED,
                subject,
                "declared evidence path and its parent components must not be symlinks",
            )
            return None
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        _issue(
            issues,
            NonfunctionalEvidenceIssueCode.PATH_UNSAFE,
            subject,
            "resolved evidence path escapes the workspace root",
        )
        return None
    return candidate


def revalidate_nonfunctional_evidence(
    manifest: Mapping[str, Any],
    *,
    workspace_root: str | Path,
) -> NonfunctionalEvidenceRevalidationReport:
    """Reopen a declared manifest without side effects or authority."""

    if not isinstance(manifest, Mapping):
        raise NonfunctionalEvidenceRevalidationError("manifest must be a mapping")
    root = Path(workspace_root)
    issues: list[NonfunctionalEvidenceIssue] = []
    if manifest.get("schema_version") != NONFUNCTIONAL_EVIDENCE_SCHEMA_VERSION:
        _issue(
            issues,
            NonfunctionalEvidenceIssueCode.SCHEMA_VERSION_INVALID,
            "schema_version",
            "manifest schema_version does not match the revalidation contract",
        )
    if manifest.get("mode") != "read_only":
        _issue(
            issues,
            NonfunctionalEvidenceIssueCode.PAYLOAD_SHAPE_INVALID,
            "mode",
            "manifest must declare mode=read_only",
        )
    if manifest.get("authority_granted") is not False:
        _issue(
            issues,
            NonfunctionalEvidenceIssueCode.AUTHORITY_FLAG_TRUE,
            "authority_granted",
            "manifest cannot grant authority",
        )
    if manifest.get("release_ready") is True:
        _issue(
            issues,
            NonfunctionalEvidenceIssueCode.RELEASE_READY_FLAG_TRUE,
            "release_ready",
            "manifest cannot declare release readiness",
        )

    raw_records = manifest.get("records")
    records = raw_records if isinstance(raw_records, list) else []
    if not isinstance(raw_records, list):
        _issue(
            issues,
            NonfunctionalEvidenceIssueCode.PAYLOAD_SHAPE_INVALID,
            "records",
            "manifest records must be a list",
        )

    evidence_ids: set[str] = set()
    control_ids: set[str] = set()
    clean_control_ids: set[str] = set()
    matched = 0
    statuses: dict[str, str] = {}
    for index, record in enumerate(records):
        subject = f"record[{index}]"
        if not isinstance(record, Mapping):
            _issue(
                issues,
                NonfunctionalEvidenceIssueCode.RECORD_FIELD_INVALID,
                subject,
                "record must be an object",
            )
            continue
        record_issue_count = len(issues)
        evidence_id = _text(record.get("evidence_id"))
        control_id = _text(record.get("control_id"))
        section_id = _text(record.get("section_id"))
        record_subject = evidence_id or control_id or subject
        expected_bytes = record.get("bytes")
        expected_sha = (
            record.get("sha256") if isinstance(record.get("sha256"), str) else ""
        )
        status = _text(record.get("status")).lower()
        summary = _text(record.get("summary"))
        valid = True
        if (
            not isinstance(record.get("evidence_id"), str)
            or not isinstance(record.get("control_id"), str)
            or not isinstance(record.get("section_id"), str)
            or not isinstance(record.get("status"), str)
            or not isinstance(record.get("summary"), str)
            or not evidence_id
            or not control_id
            or not section_id
            or not summary
        ):
            valid = False
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
        ):
            valid = False
        if not _valid_sha(expected_sha):
            valid = False
        if not valid:
            _issue(
                issues,
                NonfunctionalEvidenceIssueCode.RECORD_FIELD_INVALID,
                record_subject,
                "record requires evidence_id, section_id, control_id, summary, non-negative integer bytes and lowercase SHA-256",
            )
            continue
        if evidence_id in evidence_ids:
            _issue(
                issues,
                NonfunctionalEvidenceIssueCode.RECORD_DUPLICATE,
                evidence_id,
                "evidence IDs must be unique",
            )
        evidence_ids.add(evidence_id)
        if control_id not in _CONTROL_TO_SECTION:
            _issue(
                issues,
                NonfunctionalEvidenceIssueCode.CONTROL_UNKNOWN,
                control_id,
                "control ID is outside the closed commercial nonfunctional vocabulary",
            )
            continue
        expected_section = _CONTROL_TO_SECTION[control_id]
        if section_id != expected_section:
            _issue(
                issues,
                NonfunctionalEvidenceIssueCode.CONTROL_SECTION_MISMATCH,
                control_id,
                f"control belongs to section {expected_section}, observed {section_id}",
            )
        if control_id in control_ids:
            _issue(
                issues,
                NonfunctionalEvidenceIssueCode.CONTROL_DUPLICATE,
                control_id,
                "each required control must have exactly one evidence record",
            )
        control_ids.add(control_id)
        if status not in _ALLOWED_STATUSES:
            _issue(
                issues,
                NonfunctionalEvidenceIssueCode.STATUS_INVALID,
                control_id,
                f"unsupported control status: {status!r}",
            )
        else:
            statuses[control_id] = status

        path = _safe_relative_path(
            record.get("path"), root=root, issues=issues, subject=record_subject
        )
        if path is None:
            continue
        if not path.exists():
            _issue(
                issues,
                NonfunctionalEvidenceIssueCode.SOURCE_MISSING,
                record_subject,
                f"declared evidence file does not exist: {record.get('path')}",
            )
            continue
        if not path.is_file():
            _issue(
                issues,
                NonfunctionalEvidenceIssueCode.SOURCE_NOT_FILE,
                record_subject,
                f"declared evidence path is not a regular file: {record.get('path')}",
            )
            continue
        observed_bytes = path.stat().st_size
        observed_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        matched_record = True
        if observed_bytes != expected_bytes:
            matched_record = False
            _issue(
                issues,
                NonfunctionalEvidenceIssueCode.SOURCE_BYTES_MISMATCH,
                record_subject,
                f"expected bytes={expected_bytes}, observed bytes={observed_bytes}",
            )
        if observed_sha != expected_sha:
            matched_record = False
            _issue(
                issues,
                NonfunctionalEvidenceIssueCode.SOURCE_SHA256_MISMATCH,
                record_subject,
                f"expected sha256={expected_sha}, observed sha256={observed_sha}",
            )
        matched += int(matched_record)
        if matched_record and len(issues) == record_issue_count:
            clean_control_ids.add(control_id)

    missing = tuple(
        control_id
        for control_id in REQUIRED_NONFUNCTIONAL_CONTROL_IDS
        if control_id not in control_ids
    )
    for control_id in missing:
        _issue(
            issues,
            NonfunctionalEvidenceIssueCode.CONTROL_MISSING,
            control_id,
            "required commercial nonfunctional control has no evidence record",
        )
    covered = tuple(
        control_id
        for control_id in REQUIRED_NONFUNCTIONAL_CONTROL_IDS
        if statuses.get(control_id) == "passed" and control_id in clean_control_ids
    )
    unmet = tuple(
        control_id
        for control_id in REQUIRED_NONFUNCTIONAL_CONTROL_IDS
        if control_id not in covered
    )
    ordered_statuses = tuple(
        (control_id, statuses[control_id])
        for control_id in REQUIRED_NONFUNCTIONAL_CONTROL_IDS
        if control_id in statuses
    )
    complete = not issues and set(control_ids) == set(
        REQUIRED_NONFUNCTIONAL_CONTROL_IDS
    )
    return NonfunctionalEvidenceRevalidationReport(
        status="fresh" if complete else "blocked",
        evidence_fresh=complete,
        record_count=len(records),
        source_match_count=matched,
        control_count=len(ordered_statuses),
        covered_control_ids=covered,
        unmet_control_ids=unmet,
        control_statuses=ordered_statuses,
        issues=tuple(issues),
        read_only=True,
        authority_granted=False,
        release_ready=False,
    )


__all__ = [
    "NONFUNCTIONAL_EVIDENCE_SCHEMA_VERSION",
    "REQUIRED_NONFUNCTIONAL_CONTROL_IDS",
    "NonfunctionalEvidenceIssue",
    "NonfunctionalEvidenceIssueCode",
    "NonfunctionalEvidenceRevalidationError",
    "NonfunctionalEvidenceRevalidationReport",
    "revalidate_nonfunctional_evidence",
]
