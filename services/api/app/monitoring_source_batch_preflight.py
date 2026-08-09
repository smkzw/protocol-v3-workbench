"""Read-only, hash-bound source/batch preflight for medical monitoring.

The real-loop readiness contract validates declared SHA-256 values and batch
metadata, but it intentionally does not open source files.  This module is the
small integrity boundary immediately before a future approved-input admission:
it re-reads the declared files, verifies byte count and SHA-256, rejects
processed/restored/comparison evidence, and requires two distinct full batches
per canonical project.  It never writes, registers a batch, calls a provider,
starts a runtime, or grants medical authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


SOURCE_BATCH_PREFLIGHT_SCHEMA_VERSION = "medical_monitoring_source_batch_preflight_v1"
CANONICAL_MONITORING_PROJECT_IDS = (
    "proj_mgk10_sar_real",
    "proj_rux_03_002",
    "proj_my008_3_02_candidate",
    "proj_my008_3_01_candidate",
    "proj_my009_uc",
)
ELIGIBLE_SOURCE_CLASSES = frozenset({"raw_full_snapshot", "raw_locked_snapshot"})
CONFIRMED_SOURCE_STATUS = "confirmed"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{1,239}$")


class SourceBatchPreflightError(ValueError):
    """Raised when a source/batch preflight payload is structurally unsafe."""


class SourceBatchIssueCode(str, Enum):
    RECORD_INVALID = "record_invalid"
    PROJECT_SET_MISMATCH = "project_set_mismatch"
    PATH_MISSING = "path_missing"
    PATH_NOT_FILE = "path_not_file"
    PATH_SYMLINK_UNSUPPORTED = "path_symlink_unsupported"
    BYTE_SIZE_MISMATCH = "byte_size_mismatch"
    SHA256_MISMATCH = "sha256_mismatch"
    SOURCE_CLASS_INELIGIBLE = "source_class_ineligible"
    SOURCE_STATUS_UNCONFIRMED = "source_status_unconfirmed"
    FULL_SNAPSHOT_UNPROVEN = "full_snapshot_unproven"
    BATCH_DUPLICATE = "batch_duplicate"
    CONTENT_DUPLICATE = "content_duplicate"
    BATCH_COVERAGE_INSUFFICIENT = "batch_coverage_insufficient"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_id(value: Any, field_name: str) -> str:
    normalized = _text(value)
    if not _SAFE_ID_RE.fullmatch(normalized):
        raise SourceBatchPreflightError(
            f"{field_name} must be a non-empty opaque identifier"
        )
    return normalized


def _sha256(value: Any, field_name: str) -> str:
    normalized = _text(value)
    if not _SHA256_RE.fullmatch(normalized):
        raise SourceBatchPreflightError(f"{field_name} must be a lowercase SHA-256")
    return normalized


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise SourceBatchPreflightError(
            "preflight payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceBatchRecord:
    """One explicit listing snapshot whose bytes can be revalidated."""

    project_id: str
    batch_ref: str
    snapshot_date: str
    listing_path: str
    listing_bytes: int
    listing_sha256: str
    listing_class: str
    source_status: str
    full_snapshot_proven: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", _safe_id(self.project_id, "project_id"))
        object.__setattr__(self, "batch_ref", _safe_id(self.batch_ref, "batch_ref"))
        snapshot = _text(self.snapshot_date)
        try:
            date.fromisoformat(snapshot)
        except ValueError as exc:
            raise SourceBatchPreflightError(
                "snapshot_date must be an ISO calendar date"
            ) from exc
        object.__setattr__(self, "snapshot_date", snapshot)
        path = _text(self.listing_path)
        if not path:
            raise SourceBatchPreflightError("listing_path must not be empty")
        object.__setattr__(self, "listing_path", path)
        if isinstance(self.listing_bytes, bool) or not isinstance(
            self.listing_bytes, int
        ):
            raise SourceBatchPreflightError("listing_bytes must be an integer")
        if self.listing_bytes < 0:
            raise SourceBatchPreflightError("listing_bytes must not be negative")
        object.__setattr__(
            self, "listing_sha256", _sha256(self.listing_sha256, "listing_sha256")
        )
        object.__setattr__(self, "listing_class", _text(self.listing_class))
        object.__setattr__(self, "source_status", _text(self.source_status))
        if not isinstance(self.full_snapshot_proven, bool):
            raise SourceBatchPreflightError("full_snapshot_proven must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "batch_ref": self.batch_ref,
            "snapshot_date": self.snapshot_date,
            "listing_path": self.listing_path,
            "listing_bytes": self.listing_bytes,
            "listing_sha256": self.listing_sha256,
            "listing_class": self.listing_class,
            "source_status": self.source_status,
            "full_snapshot_proven": self.full_snapshot_proven,
        }


@dataclass(frozen=True)
class SourceBatchPreflightIssue:
    code: SourceBatchIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise SourceBatchPreflightError("issue subject and detail are required")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class SourceBatchPreflightReport:
    """Diagnostic source evidence; never an activation or medical decision."""

    status: str
    source_evidence_complete: bool
    project_count: int
    batch_count: int
    eligible_batch_counts: tuple[tuple[str, int], ...]
    issues: tuple[SourceBatchPreflightIssue, ...]
    schema_version: str = SOURCE_BATCH_PREFLIGHT_SCHEMA_VERSION
    diagnostic_only: bool = True
    runtime_activation_permitted: bool = False
    provider_call_permitted: bool = False
    write_permitted: bool = False
    medical_confirmation_permitted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != SOURCE_BATCH_PREFLIGHT_SCHEMA_VERSION:
            raise SourceBatchPreflightError(
                "unsupported source preflight schema version"
            )
        if self.status not in {"blocked", "eligible_for_next_gate"}:
            raise SourceBatchPreflightError("invalid source preflight status")
        if isinstance(self.project_count, bool) or not isinstance(
            self.project_count, int
        ):
            raise SourceBatchPreflightError("project_count must be an integer")
        if isinstance(self.batch_count, bool) or not isinstance(self.batch_count, int):
            raise SourceBatchPreflightError("batch_count must be an integer")
        if self.project_count < 0 or self.batch_count < 0:
            raise SourceBatchPreflightError(
                "project_count and batch_count must not be negative"
            )
        for name in (
            "source_evidence_complete",
            "diagnostic_only",
            "runtime_activation_permitted",
            "provider_call_permitted",
            "write_permitted",
            "medical_confirmation_permitted",
        ):
            if not isinstance(getattr(self, name), bool):
                raise SourceBatchPreflightError(f"{name} must be boolean")
        if self.diagnostic_only is not True:
            raise SourceBatchPreflightError(
                "source preflight reports must remain diagnostic_only"
            )
        if any(
            (
                self.runtime_activation_permitted,
                self.provider_call_permitted,
                self.write_permitted,
                self.medical_confirmation_permitted,
            )
        ):
            raise SourceBatchPreflightError("source preflight cannot grant authority")
        issues = tuple(self.issues)
        expected_complete = not issues and self.status == "eligible_for_next_gate"
        if self.source_evidence_complete != expected_complete:
            raise SourceBatchPreflightError(
                "source_evidence_complete does not match status/issues"
            )
        counts: list[tuple[str, int]] = []
        for project_id, count in self.eligible_batch_counts:
            if isinstance(count, bool) or not isinstance(count, int):
                raise SourceBatchPreflightError(
                    "eligible batch counts must be integers"
                )
            counts.append((str(project_id), count))
        if len({project_id for project_id, _ in counts}) != len(counts):
            raise SourceBatchPreflightError(
                "eligible_batch_counts must not repeat project IDs"
            )
        if any(count < 0 for _, count in counts):
            raise SourceBatchPreflightError(
                "eligible batch counts must not be negative"
            )
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "eligible_batch_counts", tuple(sorted(counts)))
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "source_evidence_complete": self.source_evidence_complete,
            "project_count": self.project_count,
            "batch_count": self.batch_count,
            "eligible_batch_counts": [
                {"project_id": project_id, "count": count}
                for project_id, count in self.eligible_batch_counts
            ],
            "issues": [issue.to_dict() for issue in self.issues],
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


def assess_source_batch_preflight(
    records: Iterable[SourceBatchRecord],
    *,
    required_project_ids: Iterable[str] = CANONICAL_MONITORING_PROJECT_IDS,
) -> SourceBatchPreflightReport:
    """Verify source bytes and distinct full-batch coverage without mutation."""

    rows = tuple(records)
    required = tuple(
        sorted({_safe_id(item, "required_project_id") for item in required_project_ids})
    )
    issues: list[SourceBatchPreflightIssue] = []
    observed_projects = {row.project_id for row in rows}
    if observed_projects != set(required):
        issues.append(
            SourceBatchPreflightIssue(
                SourceBatchIssueCode.PROJECT_SET_MISMATCH,
                "project_set",
                f"required={list(required)}, observed={sorted(observed_projects)}",
            )
        )

    seen_batch_refs: set[tuple[str, str]] = set()
    seen_content: dict[str, SourceBatchRecord] = {}
    eligible_counts = {project_id: 0 for project_id in required}
    for row in sorted(
        rows, key=lambda item: (item.project_id, item.batch_ref, item.listing_path)
    ):
        if not isinstance(row, SourceBatchRecord):
            issues.append(
                SourceBatchPreflightIssue(
                    SourceBatchIssueCode.RECORD_INVALID,
                    "records",
                    "all records must be SourceBatchRecord instances",
                )
            )
            continue
        identity = (row.project_id, row.batch_ref)
        if identity in seen_batch_refs:
            issues.append(
                SourceBatchPreflightIssue(
                    SourceBatchIssueCode.BATCH_DUPLICATE,
                    f"{row.project_id}:{row.batch_ref}",
                    "batch_ref must be unique within a project",
                )
            )
        seen_batch_refs.add(identity)
        previous = seen_content.get(row.listing_sha256)
        if previous is not None:
            issues.append(
                SourceBatchPreflightIssue(
                    SourceBatchIssueCode.CONTENT_DUPLICATE,
                    f"{row.project_id}:{row.batch_ref}",
                    f"listing SHA-256 is already used by {previous.project_id}:{previous.batch_ref}; duplicate paths are not a second batch",
                )
            )
        else:
            seen_content[row.listing_sha256] = row

        path = Path(row.listing_path)
        if path.is_symlink():
            issues.append(
                SourceBatchPreflightIssue(
                    SourceBatchIssueCode.PATH_SYMLINK_UNSUPPORTED,
                    f"{row.project_id}:{row.batch_ref}",
                    "source path must be a direct file path, not a symlink",
                )
            )
        elif not path.exists():
            issues.append(
                SourceBatchPreflightIssue(
                    SourceBatchIssueCode.PATH_MISSING,
                    f"{row.project_id}:{row.batch_ref}",
                    f"source path does not exist: {row.listing_path}",
                )
            )
        elif not path.is_file():
            issues.append(
                SourceBatchPreflightIssue(
                    SourceBatchIssueCode.PATH_NOT_FILE,
                    f"{row.project_id}:{row.batch_ref}",
                    f"source path is not a regular file: {row.listing_path}",
                )
            )
        else:
            actual_size = path.stat().st_size
            if actual_size != row.listing_bytes:
                issues.append(
                    SourceBatchPreflightIssue(
                        SourceBatchIssueCode.BYTE_SIZE_MISMATCH,
                        f"{row.project_id}:{row.batch_ref}",
                        f"recorded bytes={row.listing_bytes}, observed bytes={actual_size}",
                    )
                )
            actual_sha = _file_sha256(path)
            if actual_sha != row.listing_sha256:
                issues.append(
                    SourceBatchPreflightIssue(
                        SourceBatchIssueCode.SHA256_MISMATCH,
                        f"{row.project_id}:{row.batch_ref}",
                        f"recorded sha256={row.listing_sha256}, observed sha256={actual_sha}",
                    )
                )

        eligible = True
        if row.listing_class not in ELIGIBLE_SOURCE_CLASSES:
            eligible = False
            issues.append(
                SourceBatchPreflightIssue(
                    SourceBatchIssueCode.SOURCE_CLASS_INELIGIBLE,
                    f"{row.project_id}:{row.batch_ref}",
                    "controlled admission accepts only raw_full_snapshot or raw_locked_snapshot",
                )
            )
        if row.source_status != CONFIRMED_SOURCE_STATUS:
            eligible = False
            issues.append(
                SourceBatchPreflightIssue(
                    SourceBatchIssueCode.SOURCE_STATUS_UNCONFIRMED,
                    f"{row.project_id}:{row.batch_ref}",
                    "source_status must be confirmed",
                )
            )
        if row.full_snapshot_proven is not True:
            eligible = False
            issues.append(
                SourceBatchPreflightIssue(
                    SourceBatchIssueCode.FULL_SNAPSHOT_UNPROVEN,
                    f"{row.project_id}:{row.batch_ref}",
                    "full_snapshot_proven must be explicitly true",
                )
            )
        if eligible and row.project_id in eligible_counts:
            eligible_counts[row.project_id] += 1

    for project_id in required:
        count = eligible_counts[project_id]
        if count < 2:
            issues.append(
                SourceBatchPreflightIssue(
                    SourceBatchIssueCode.BATCH_COVERAGE_INSUFFICIENT,
                    project_id,
                    f"at least two distinct eligible full batches are required; observed {count}",
                )
            )

    return SourceBatchPreflightReport(
        status="eligible_for_next_gate" if not issues else "blocked",
        source_evidence_complete=not issues,
        project_count=len(observed_projects),
        batch_count=len(rows),
        eligible_batch_counts=tuple(eligible_counts.items()),
        issues=tuple(issues),
    )


__all__ = [
    "CANONICAL_MONITORING_PROJECT_IDS",
    "CONFIRMED_SOURCE_STATUS",
    "ELIGIBLE_SOURCE_CLASSES",
    "SOURCE_BATCH_PREFLIGHT_SCHEMA_VERSION",
    "SourceBatchIssueCode",
    "SourceBatchPreflightError",
    "SourceBatchPreflightIssue",
    "SourceBatchPreflightReport",
    "SourceBatchRecord",
    "assess_source_batch_preflight",
]
