"""Read-only revalidation of persisted source-batch preflight evidence.

``monitoring_source_batch_preflight`` protects a future approved-input step by
re-opening declared listing files.  This module protects the evidence record
itself: it reconstructs the rows from a persisted preflight artifact, reruns
the canonical source contract, compares the derived summary, and optionally
reopens the workspace-relative JSON artifact with byte/SHA checks.

The result describes evidence freshness only.  A ``fresh`` report may still
contain a ``blocked`` source preflight status when the current files do not
meet the two-batch admission rule.  The module never promotes a source,
creates a batch, starts a service, calls a provider, or grants authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .monitoring_source_batch_preflight import (
    CANONICAL_MONITORING_PROJECT_IDS,
    SourceBatchIssueCode,
    SourceBatchPreflightError,
    SourceBatchRecord,
    assess_source_batch_preflight,
)


SOURCE_BATCH_PREFLIGHT_REVALIDATION_SCHEMA_VERSION = (
    "medical_monitoring_source_batch_preflight_revalidation_v1"
)
SOURCE_BATCH_PREFLIGHT_ARTIFACT_SCHEMA_VERSION = (
    "medical-monitoring-real-source-batch-preflight-v1"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_PAYLOAD_KEYS = (
    "schema_version",
    "artifact_ref",
    "observed_at",
    "purpose",
    "authority",
    "source_policy",
    "global_gates_at_observation",
    "projects",
    "summary",
)
_REQUIRED_AUTHORITY_FLAGS = (
    "read_only",
    "product_source_write_permitted",
    "runtime_write_permitted",
    "provider_call_permitted",
    "browser_login_permitted",
    "medical_confirmation_permitted",
    "batch_creation_performed",
    "batch_mutation_performed",
)
_EXPECTED_AUTHORITY_VALUES = {"read_only": True}
_REQUIRED_BATCH_KEYS = (
    "batch_ref",
    "snapshot_date",
    "path",
    "bytes",
    "sha256",
    "source_class",
    "source_status",
    "full_snapshot_proven",
)


class SourceBatchPreflightRevalidationError(ValueError):
    """Raised when a revalidation request cannot be evaluated safely."""


class SourceBatchPreflightRevalidationIssueCode(str, Enum):
    PAYLOAD_SHAPE_INVALID = "payload_shape_invalid"
    SCHEMA_VERSION_INVALID = "schema_version_invalid"
    ARTIFACT_FIELD_INVALID = "artifact_field_invalid"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"
    AUTHORITY_FLAG_MISSING = "authority_flag_missing"
    SOURCE_POLICY_MISMATCH = "source_policy_mismatch"
    PROJECT_SET_MISMATCH = "project_set_mismatch"
    PROJECT_DUPLICATE = "project_duplicate"
    PROJECT_FIELD_INVALID = "project_field_invalid"
    BATCH_RECONSTRUCTION_FAILED = "batch_reconstruction_failed"
    SUMMARY_FIELD_INVALID = "summary_field_invalid"
    SUMMARY_DERIVED_MISMATCH = "summary_derived_mismatch"
    PREFLIGHT_REPORT_MISSING = "preflight_report_missing"
    PREFLIGHT_REPORT_HASH_MISMATCH = "preflight_report_hash_mismatch"
    SOURCE_FILE_DRIFT = "source_file_drift"
    FILE_PATH_UNSAFE = "file_path_unsafe"
    FILE_MISSING = "file_missing"
    FILE_NOT_REGULAR = "file_not_regular"
    FILE_SYMLINK_UNSUPPORTED = "file_symlink_unsupported"
    FILE_BYTES_MISMATCH = "file_bytes_mismatch"
    FILE_SHA256_MISMATCH = "file_sha256_mismatch"
    FILE_JSON_INVALID = "file_json_invalid"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise SourceBatchPreflightRevalidationError(
            "source preflight revalidation payload must be JSON-serializable"
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
class SourceBatchPreflightRevalidationIssue:
    code: SourceBatchPreflightRevalidationIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise SourceBatchPreflightRevalidationError(
                "revalidation issue subject and detail are required"
            )
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class SourceBatchPreflightRevalidationReport:
    """Evidence identity result; it cannot grant runtime or medical authority."""

    status: str
    evidence_fresh: bool
    payload_valid: bool
    preflight_report_matches: bool
    file_checked: bool
    file_fresh: bool
    source_preflight_status: str
    source_evidence_complete: bool
    source_preflight_issue_count: int
    project_count: int
    batch_count: int
    eligible_batch_counts: tuple[tuple[str, int], ...]
    issues: tuple[SourceBatchPreflightRevalidationIssue, ...]
    schema_version: str = SOURCE_BATCH_PREFLIGHT_REVALIDATION_SCHEMA_VERSION
    read_only: bool = True
    authority_granted: bool = False
    release_ready: bool = False
    medical_confirmation_permitted: bool = False
    runtime_write_permitted: bool = False
    provider_call_permitted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != SOURCE_BATCH_PREFLIGHT_REVALIDATION_SCHEMA_VERSION:
            raise SourceBatchPreflightRevalidationError(
                "unsupported source preflight revalidation schema"
            )
        if self.status not in {"fresh", "blocked"}:
            raise SourceBatchPreflightRevalidationError("invalid revalidation status")
        if self.read_only is not True or self.authority_granted is not False:
            raise SourceBatchPreflightRevalidationError(
                "source preflight revalidation must remain read-only"
            )
        for name in (
            "release_ready",
            "medical_confirmation_permitted",
            "runtime_write_permitted",
            "provider_call_permitted",
        ):
            if getattr(self, name) is not False:
                raise SourceBatchPreflightRevalidationError(f"{name} must remain false")
        for name in (
            "evidence_fresh",
            "payload_valid",
            "preflight_report_matches",
            "file_checked",
            "file_fresh",
            "source_evidence_complete",
        ):
            if not isinstance(getattr(self, name), bool):
                raise SourceBatchPreflightRevalidationError(f"{name} must be boolean")
        for name in ("source_preflight_issue_count", "project_count", "batch_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SourceBatchPreflightRevalidationError(
                    f"{name} must be a non-negative integer"
                )
        if self.file_fresh and not self.file_checked:
            raise SourceBatchPreflightRevalidationError(
                "file_fresh cannot be true when file_checked is false"
            )
        if self.source_preflight_status not in {
            "blocked",
            "eligible_for_next_gate",
            "unknown",
        }:
            raise SourceBatchPreflightRevalidationError(
                "source_preflight_status is invalid"
            )
        counts = tuple(self.eligible_batch_counts)
        if any(
            not isinstance(project_id, str)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            for project_id, count in counts
        ):
            raise SourceBatchPreflightRevalidationError(
                "eligible_batch_counts contain invalid values"
            )
        if len({project_id for project_id, _ in counts}) != len(counts):
            raise SourceBatchPreflightRevalidationError(
                "eligible_batch_counts must not repeat project IDs"
            )
        issues = tuple(self.issues)
        if any(
            not isinstance(item, SourceBatchPreflightRevalidationIssue)
            for item in issues
        ):
            raise SourceBatchPreflightRevalidationError(
                "issues contain an invalid value"
            )
        expected_fresh = (
            not issues
            and self.payload_valid
            and self.preflight_report_matches
            and (not self.file_checked or self.file_fresh)
        )
        if (
            self.evidence_fresh != expected_fresh
            or (self.status == "fresh") != expected_fresh
        ):
            raise SourceBatchPreflightRevalidationError(
                "revalidation status does not match evidence state"
            )
        object.__setattr__(self, "eligible_batch_counts", tuple(sorted(counts)))
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "evidence_fresh": self.evidence_fresh,
            "payload_valid": self.payload_valid,
            "preflight_report_matches": self.preflight_report_matches,
            "file_checked": self.file_checked,
            "file_fresh": self.file_fresh,
            "source_preflight_status": self.source_preflight_status,
            "source_evidence_complete": self.source_evidence_complete,
            "source_preflight_issue_count": self.source_preflight_issue_count,
            "project_count": self.project_count,
            "batch_count": self.batch_count,
            "eligible_batch_counts": [
                {"project_id": project_id, "count": count}
                for project_id, count in self.eligible_batch_counts
            ],
            "issues": [issue.to_dict() for issue in self.issues],
            "read_only": self.read_only,
            "authority_granted": self.authority_granted,
            "release_ready": self.release_ready,
            "medical_confirmation_permitted": self.medical_confirmation_permitted,
            "runtime_write_permitted": self.runtime_write_permitted,
            "provider_call_permitted": self.provider_call_permitted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
        }


def _issue(
    issues: list[SourceBatchPreflightRevalidationIssue],
    code: SourceBatchPreflightRevalidationIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(SourceBatchPreflightRevalidationIssue(code, subject, detail))


def _report(
    *,
    issues: list[SourceBatchPreflightRevalidationIssue],
    payload_valid: bool,
    preflight_report_matches: bool,
    file_checked: bool,
    file_fresh: bool,
    source_preflight_status: str = "unknown",
    source_evidence_complete: bool = False,
    source_preflight_issue_count: int = 0,
    project_count: int = 0,
    batch_count: int = 0,
    eligible_batch_counts: Iterable[tuple[str, int]] = (),
) -> SourceBatchPreflightRevalidationReport:
    return SourceBatchPreflightRevalidationReport(
        status="fresh"
        if not issues
        and payload_valid
        and preflight_report_matches
        and (not file_checked or file_fresh)
        else "blocked",
        evidence_fresh=not issues
        and payload_valid
        and preflight_report_matches
        and (not file_checked or file_fresh),
        payload_valid=payload_valid,
        preflight_report_matches=preflight_report_matches,
        file_checked=file_checked,
        file_fresh=file_fresh,
        source_preflight_status=source_preflight_status,
        source_evidence_complete=source_evidence_complete,
        source_preflight_issue_count=source_preflight_issue_count,
        project_count=project_count,
        batch_count=batch_count,
        eligible_batch_counts=tuple(eligible_batch_counts),
        issues=tuple(issues),
    )


def _list(
    value: Any, *, key: str, issues: list[SourceBatchPreflightRevalidationIssue]
) -> tuple[Any, ...] | None:
    if not isinstance(value, list):
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            key,
            f"{key} must be a list",
        )
        return None
    return tuple(value)


def _revalidate_excluded_source_file(
    item: Mapping[str, Any],
    *,
    subject: str,
    issues: list[SourceBatchPreflightRevalidationIssue],
) -> None:
    """Check a declared non-batch candidate without inventing a batch identity."""

    path_text = _text(item.get("path"))
    expected_bytes = item.get("bytes")
    expected_sha = item.get("sha256")
    if (
        not path_text
        or isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes < 0
        or not _valid_sha(expected_sha)
    ):
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.BATCH_RECONSTRUCTION_FAILED,
            subject,
            "excluded source candidate must retain a path, non-negative bytes, and lowercase SHA-256",
        )
        return
    path = Path(path_text)
    if path.is_symlink():
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.SOURCE_FILE_DRIFT,
            subject,
            "excluded source candidate path is a symlink",
        )
        return
    if not path.exists() or not path.is_file():
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.SOURCE_FILE_DRIFT,
            subject,
            f"excluded source candidate path is missing or not a regular file: {path_text}",
        )
        return
    actual_bytes = path.stat().st_size
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_bytes != expected_bytes:
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.SOURCE_FILE_DRIFT,
            subject,
            f"recorded bytes={expected_bytes}, observed bytes={actual_bytes}",
        )
    if actual_sha != expected_sha:
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.SOURCE_FILE_DRIFT,
            subject,
            f"recorded sha256={expected_sha!r}, observed sha256={actual_sha!r}",
        )


def _evaluate_payload(
    payload: Mapping[str, Any],
    *,
    file_checked: bool,
    file_fresh: bool,
    initial_issues: Iterable[SourceBatchPreflightRevalidationIssue] = (),
) -> SourceBatchPreflightRevalidationReport:
    issues = list(initial_issues)
    missing = [key for key in _REQUIRED_PAYLOAD_KEYS if key not in payload]
    if missing:
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "payload",
            f"persisted source preflight evidence is missing required keys: {missing}",
        )
        return _report(
            issues=issues,
            payload_valid=False,
            preflight_report_matches=False,
            file_checked=file_checked,
            file_fresh=file_fresh,
        )

    payload_valid = True
    if payload.get("schema_version") != SOURCE_BATCH_PREFLIGHT_ARTIFACT_SCHEMA_VERSION:
        payload_valid = False
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.SCHEMA_VERSION_INVALID,
            "schema_version",
            "persisted artifact schema_version does not match the source preflight artifact contract",
        )
    for key in ("artifact_ref", "observed_at", "purpose"):
        if not _text(payload.get(key)):
            payload_valid = False
            _issue(
                issues,
                SourceBatchPreflightRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
                key,
                f"{key} must be a non-empty string",
            )

    authority = payload.get("authority")
    if not isinstance(authority, Mapping):
        payload_valid = False
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "authority",
            "authority must be an object",
        )
    else:
        for key in _REQUIRED_AUTHORITY_FLAGS:
            if key not in authority:
                payload_valid = False
                _issue(
                    issues,
                    SourceBatchPreflightRevalidationIssueCode.AUTHORITY_FLAG_MISSING,
                    f"authority.{key}",
                    "source preflight evidence must declare every authority flag",
                )
            elif authority[key] is not _EXPECTED_AUTHORITY_VALUES.get(key, False):
                payload_valid = False
                _issue(
                    issues,
                    SourceBatchPreflightRevalidationIssueCode.AUTHORITY_FLAG_TRUE,
                    f"authority.{key}",
                    "persisted source preflight evidence cannot grant or perform authority",
                )

    required_projects = tuple(
        sorted(
            {_text(item) for item in CANONICAL_MONITORING_PROJECT_IDS if _text(item)}
        )
    )
    policy = payload.get("source_policy")
    if not isinstance(policy, Mapping):
        payload_valid = False
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "source_policy",
            "source_policy must be an object",
        )
    else:
        policy_projects = policy.get("canonical_monitoring_project_ids")
        observed_policy = (
            tuple(sorted(_text(item) for item in policy_projects))
            if isinstance(policy_projects, list)
            else None
        )
        if observed_policy != required_projects:
            payload_valid = False
            _issue(
                issues,
                SourceBatchPreflightRevalidationIssueCode.SOURCE_POLICY_MISMATCH,
                "source_policy.canonical_monitoring_project_ids",
                f"expected={list(required_projects)}, observed={policy_projects!r}",
            )

    raw_projects = _list(payload.get("projects"), key="projects", issues=issues)
    if raw_projects is None:
        return _report(
            issues=issues,
            payload_valid=False,
            preflight_report_matches=False,
            file_checked=file_checked,
            file_fresh=file_fresh,
        )
    rows: list[SourceBatchRecord] = []
    observed_projects: list[str] = []
    for index, project in enumerate(raw_projects):
        subject = f"projects[{index}]"
        if not isinstance(project, Mapping):
            payload_valid = False
            _issue(
                issues,
                SourceBatchPreflightRevalidationIssueCode.PROJECT_FIELD_INVALID,
                subject,
                "project rows must be objects",
            )
            continue
        project_id = _text(project.get("project_id"))
        if not project_id:
            payload_valid = False
            _issue(
                issues,
                SourceBatchPreflightRevalidationIssueCode.PROJECT_FIELD_INVALID,
                subject,
                "project_id must be a non-empty string",
            )
            continue
        if project_id in observed_projects:
            payload_valid = False
            _issue(
                issues,
                SourceBatchPreflightRevalidationIssueCode.PROJECT_DUPLICATE,
                project_id,
                "project_id must occur once in the persisted artifact",
            )
        observed_projects.append(project_id)
        listing = project.get("listing_evidence")
        raw_listing = _list(listing, key=f"{subject}.listing_evidence", issues=issues)
        if raw_listing is None:
            payload_valid = False
            continue
        for row_index, item in enumerate(raw_listing):
            row_subject = f"{project_id}.listing_evidence[{row_index}]"
            if not isinstance(item, Mapping):
                payload_valid = False
                _issue(
                    issues,
                    SourceBatchPreflightRevalidationIssueCode.BATCH_RECONSTRUCTION_FAILED,
                    row_subject,
                    "listing evidence rows must be objects",
                )
                continue
            missing_batch = [key for key in _REQUIRED_BATCH_KEYS if key not in item]
            if missing_batch:
                payload_valid = False
                _issue(
                    issues,
                    SourceBatchPreflightRevalidationIssueCode.BATCH_RECONSTRUCTION_FAILED,
                    row_subject,
                    f"listing evidence row is missing required keys: {missing_batch}",
                )
                continue
            if not _text(item.get("batch_ref")):
                if item.get("eligible_for_future_real_loop") is True:
                    payload_valid = False
                    _issue(
                        issues,
                        SourceBatchPreflightRevalidationIssueCode.BATCH_RECONSTRUCTION_FAILED,
                        row_subject,
                        "an eligible source candidate must have an explicit batch_ref; no identity is synthesized",
                    )
                _revalidate_excluded_source_file(
                    item, subject=row_subject, issues=issues
                )
                continue
            try:
                rows.append(
                    SourceBatchRecord(
                        project_id=project_id,
                        batch_ref=item["batch_ref"],
                        snapshot_date=item["snapshot_date"],
                        listing_path=item["path"],
                        listing_bytes=item["bytes"],
                        listing_sha256=item["sha256"],
                        listing_class=item["source_class"],
                        source_status=item["source_status"],
                        full_snapshot_proven=item["full_snapshot_proven"],
                    )
                )
            except (KeyError, TypeError, ValueError, SourceBatchPreflightError) as exc:
                payload_valid = False
                _issue(
                    issues,
                    SourceBatchPreflightRevalidationIssueCode.BATCH_RECONSTRUCTION_FAILED,
                    row_subject,
                    str(exc),
                )

    if set(observed_projects) != set(required_projects):
        payload_valid = False
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.PROJECT_SET_MISMATCH,
            "projects",
            f"expected={list(required_projects)}, observed={sorted(set(observed_projects))}",
        )

    computed = None
    try:
        computed = assess_source_batch_preflight(
            rows, required_project_ids=required_projects
        )
    except (TypeError, ValueError, SourceBatchPreflightError) as exc:
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.BATCH_RECONSTRUCTION_FAILED,
            "source_batch_preflight",
            str(exc),
        )

    source_status = "unknown"
    source_complete = False
    source_issue_count = 0
    project_count = len(set(observed_projects))
    batch_count = len(rows)
    counts: tuple[tuple[str, int], ...] = ()
    report_matches = computed is not None
    if computed is not None:
        source_status = computed.status
        source_complete = computed.source_evidence_complete
        source_issue_count = len(computed.issues)
        project_count = computed.project_count
        batch_count = computed.batch_count
        counts = computed.eligible_batch_counts
        source_file_drift_codes = {
            SourceBatchIssueCode.PATH_MISSING,
            SourceBatchIssueCode.PATH_NOT_FILE,
            SourceBatchIssueCode.PATH_SYMLINK_UNSUPPORTED,
            SourceBatchIssueCode.BYTE_SIZE_MISMATCH,
            SourceBatchIssueCode.SHA256_MISMATCH,
        }
        for source_issue in computed.issues:
            if source_issue.code in source_file_drift_codes:
                report_matches = False
                _issue(
                    issues,
                    SourceBatchPreflightRevalidationIssueCode.SOURCE_FILE_DRIFT,
                    source_issue.subject,
                    source_issue.detail,
                )

    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        report_matches = False
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.SUMMARY_FIELD_INVALID,
            "summary",
            "summary must be an object",
        )
    elif computed is not None:
        expected_two = sorted(project_id for project_id, count in counts if count >= 2)
        expected_one = sorted(project_id for project_id, count in counts if count >= 1)
        for key, expected in (
            ("projects_with_two_eligible_full_batches", expected_two),
            ("projects_with_at_least_one_eligible_full_batch", expected_one),
        ):
            observed = summary.get(key)
            if not isinstance(observed, list):
                report_matches = False
                _issue(
                    issues,
                    SourceBatchPreflightRevalidationIssueCode.SUMMARY_FIELD_INVALID,
                    f"summary.{key}",
                    f"{key} must be a list",
                )
            elif sorted(_text(item) for item in observed) != expected:
                report_matches = False
                _issue(
                    issues,
                    SourceBatchPreflightRevalidationIssueCode.SUMMARY_DERIVED_MISMATCH,
                    f"summary.{key}",
                    f"expected={expected}, observed={observed!r}",
                )
        for key in ("real_loop_execution_ready", "approved_input_ready"):
            observed = summary.get(key)
            if not isinstance(observed, bool):
                report_matches = False
                _issue(
                    issues,
                    SourceBatchPreflightRevalidationIssueCode.SUMMARY_FIELD_INVALID,
                    f"summary.{key}",
                    f"{key} must be boolean",
                )
            elif observed and not source_complete:
                report_matches = False
                _issue(
                    issues,
                    SourceBatchPreflightRevalidationIssueCode.SUMMARY_DERIVED_MISMATCH,
                    f"summary.{key}",
                    f"{key} cannot be true while source preflight is {source_status}",
                )
        for project in raw_projects:
            if not isinstance(project, Mapping):
                continue
            project_id = _text(project.get("project_id"))
            observed_count = project.get(
                "distinct_provenance_complete_eligible_full_batch_count"
            )
            expected_count = dict(counts).get(project_id, 0)
            if observed_count != expected_count:
                report_matches = False
                _issue(
                    issues,
                    SourceBatchPreflightRevalidationIssueCode.SUMMARY_DERIVED_MISMATCH,
                    f"{project_id}.distinct_provenance_complete_eligible_full_batch_count",
                    f"expected={expected_count}, observed={observed_count!r}",
                )
        declared_report_sha = payload.get("preflight_report_sha256")
        if declared_report_sha is not None:
            if (
                not _valid_sha(declared_report_sha)
                or declared_report_sha != computed.report_sha256
            ):
                report_matches = False
                _issue(
                    issues,
                    SourceBatchPreflightRevalidationIssueCode.PREFLIGHT_REPORT_HASH_MISMATCH,
                    "preflight_report_sha256",
                    f"expected persisted={declared_report_sha!r}, computed={computed.report_sha256!r}",
                )

    return _report(
        issues=issues,
        payload_valid=payload_valid,
        preflight_report_matches=report_matches,
        file_checked=file_checked,
        file_fresh=file_fresh,
        source_preflight_status=source_status,
        source_evidence_complete=source_complete,
        source_preflight_issue_count=source_issue_count,
        project_count=project_count,
        batch_count=batch_count,
        eligible_batch_counts=counts,
    )


def revalidate_source_batch_preflight_payload(
    payload: Mapping[str, Any],
) -> SourceBatchPreflightRevalidationReport:
    """Re-run the persisted source preflight mapping without artifact I/O."""

    if not isinstance(payload, Mapping):
        raise SourceBatchPreflightRevalidationError(
            "source preflight payload must be a mapping"
        )
    return _evaluate_payload(payload, file_checked=False, file_fresh=False)


def _safe_artifact_path(
    raw_path: Any,
    *,
    workspace_root: Path,
    issues: list[SourceBatchPreflightRevalidationIssue],
) -> Path | None:
    text = raw_path.strip() if isinstance(raw_path, str) else ""
    path = Path(text) if text else Path(".")
    if (
        not text
        or path.is_absolute()
        or "\\" in text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.FILE_PATH_UNSAFE,
            "path",
            "artifact path must be a clean workspace-relative POSIX path",
        )
        return None
    root = workspace_root.resolve()
    candidate = workspace_root / path
    current = workspace_root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            _issue(
                issues,
                SourceBatchPreflightRevalidationIssueCode.FILE_SYMLINK_UNSUPPORTED,
                "path",
                "artifact path and parent components must not be symlinks",
            )
            return None
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError:
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.FILE_PATH_UNSAFE,
            "path",
            "artifact path escapes the workspace root",
        )
        return None
    return candidate


def revalidate_source_batch_preflight_file(
    path: str,
    *,
    expected_bytes: int,
    expected_sha256: str,
    workspace_root: str | Path,
) -> SourceBatchPreflightRevalidationReport:
    """Reopen one persisted artifact and revalidate it without side effects."""

    issues: list[SourceBatchPreflightRevalidationIssue] = []
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes < 0
    ):
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
            "expected_bytes",
            "expected_bytes must be a non-negative integer",
        )
    if not _valid_sha(expected_sha256):
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
            "expected_sha256",
            "expected_sha256 must be a lowercase SHA-256",
        )
    try:
        root = Path(workspace_root)
    except TypeError as exc:
        raise SourceBatchPreflightRevalidationError(
            "workspace_root must be path-like"
        ) from exc
    artifact = _safe_artifact_path(path, workspace_root=root, issues=issues)
    if artifact is None:
        return _report(
            issues=issues,
            payload_valid=False,
            preflight_report_matches=False,
            file_checked=True,
            file_fresh=False,
        )
    if artifact.is_symlink():
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.FILE_SYMLINK_UNSUPPORTED,
            "path",
            "artifact path must not be a symlink",
        )
        return _report(
            issues=issues,
            payload_valid=False,
            preflight_report_matches=False,
            file_checked=True,
            file_fresh=False,
        )
    if not artifact.exists():
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.FILE_MISSING,
            "path",
            f"artifact file does not exist: {path}",
        )
        return _report(
            issues=issues,
            payload_valid=False,
            preflight_report_matches=False,
            file_checked=True,
            file_fresh=False,
        )
    if not artifact.is_file():
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.FILE_NOT_REGULAR,
            "path",
            f"artifact path is not a regular file: {path}",
        )
        return _report(
            issues=issues,
            payload_valid=False,
            preflight_report_matches=False,
            file_checked=True,
            file_fresh=False,
        )
    raw = artifact.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    file_fresh = (
        not issues and len(raw) == expected_bytes and actual_sha == expected_sha256
    )
    if len(raw) != expected_bytes:
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.FILE_BYTES_MISMATCH,
            "path",
            f"recorded bytes={expected_bytes}, observed bytes={len(raw)}",
        )
    if actual_sha != expected_sha256:
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.FILE_SHA256_MISMATCH,
            "path",
            f"recorded sha256={expected_sha256}, observed sha256={actual_sha}",
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.FILE_JSON_INVALID,
            "path",
            str(exc),
        )
        return _report(
            issues=issues,
            payload_valid=False,
            preflight_report_matches=False,
            file_checked=True,
            file_fresh=False,
        )
    if not isinstance(payload, Mapping):
        _issue(
            issues,
            SourceBatchPreflightRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "payload",
            "artifact JSON root must be an object",
        )
        return _report(
            issues=issues,
            payload_valid=False,
            preflight_report_matches=False,
            file_checked=True,
            file_fresh=False,
        )
    return _evaluate_payload(
        payload,
        file_checked=True,
        file_fresh=file_fresh,
        initial_issues=issues,
    )


__all__ = [
    "SOURCE_BATCH_PREFLIGHT_ARTIFACT_SCHEMA_VERSION",
    "SOURCE_BATCH_PREFLIGHT_REVALIDATION_SCHEMA_VERSION",
    "SourceBatchPreflightRevalidationError",
    "SourceBatchPreflightRevalidationIssue",
    "SourceBatchPreflightRevalidationIssueCode",
    "SourceBatchPreflightRevalidationReport",
    "revalidate_source_batch_preflight_file",
    "revalidate_source_batch_preflight_payload",
]
