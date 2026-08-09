"""Read-only coverage contract for the three commercial monitoring modes.

The real-loop acceptance contract proves browser/scientific tester rounds.  It
does not say which monitoring workflow was exercised.  This module binds
mode-specific evidence to an already accepted user-view run and requires the
three product modes for both requested roles plus candidate-project coverage.

It is diagnostic evidence only: it never executes a mode, calls a provider,
changes runtime state, or grants medical/UAT/release authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable

from .monitoring_real_loop_acceptance import (
    ACCEPTANCE_PROJECT_IDS,
    ACCEPTANCE_ROLES,
    RealLoopAcceptanceReport,
    RealLoopAcceptanceRun,
)


MONITORING_MODE_COVERAGE_SCHEMA_VERSION = "monitoring_real_loop_mode_coverage_v1"
MONITORING_MODE_IDS = (
    "daily_incremental",
    "pre_lock_total",
    "post_lock_fixed_total",
)
MONITORING_MODE_CHECKPOINTS = {
    "daily_incremental": (
        "full_snapshot_confirmed",
        "incremental_diff_reviewed",
        "risk_disposition_recorded",
        "next_baseline_confirmed",
    ),
    "pre_lock_total": (
        "frozen_total_snapshot",
        "full_recompute_completed",
        "subject_site_trial_reconciled",
        "open_risk_evidence_checked",
    ),
    "post_lock_fixed_total": (
        "locked_total_snapshot",
        "subject_site_trial_rollup",
        "closure_evidence_checked",
        "checklist_readiness_confirmed",
    ),
}
_ALLOWED_STATUSES = {"passed", "failed", "blocked"}
_ALLOWED_ISSUE_SEVERITIES = {"P0", "P1", "P2", "P3", "P4"}
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MonitoringModeCoverageError(ValueError):
    """Raised when mode evidence is malformed or unsafe."""


class MonitoringModeCoverageIssueCode(str, Enum):
    ACCEPTANCE_REPORT_MISSING = "acceptance_report_missing"
    ACCEPTANCE_REPORT_TYPE_INVALID = "acceptance_report_type_invalid"
    ACCEPTANCE_REPORT_NOT_COMPLETE = "acceptance_report_not_complete"
    ACCEPTANCE_RUN_DUPLICATE = "acceptance_run_duplicate"
    MODE_EVIDENCE_DUPLICATE = "mode_evidence_duplicate"
    MODE_EVIDENCE_HASH_DUPLICATE = "mode_evidence_hash_duplicate"
    MODE_UNKNOWN = "mode_unknown"
    MODE_SET_MISMATCH = "mode_set_mismatch"
    ACCEPTANCE_RUN_MISSING = "acceptance_run_missing"
    ACCEPTANCE_RUN_NOT_CLEAN = "acceptance_run_not_clean"
    ROLE_SET_MISMATCH = "role_set_mismatch"
    PROJECT_SET_MISMATCH = "project_set_mismatch"
    ROLE_MODE_DUPLICATE = "role_mode_duplicate"
    ROLE_MODE_MISSING = "role_mode_missing"
    PROJECT_COVERAGE_MISSING = "project_coverage_missing"
    STATUS_INVALID = "status_invalid"
    ISSUE_SEVERITY_INVALID = "issue_severity_invalid"
    EVIDENCE_REFERENCE_MISSING = "evidence_reference_missing"
    MODE_CHECKPOINTS_MISSING = "mode_checkpoints_missing"
    FAILURE_DETAIL_MISSING = "failure_detail_missing"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MonitoringModeCoverageError(f"{field_name} must be a string identifier")
    text = value.strip()
    if not _SAFE_ID_RE.fullmatch(text):
        raise MonitoringModeCoverageError(
            f"{field_name} must be a non-empty safe identifier"
        )
    return text


def _safe_refs(values: Iterable[Any], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise MonitoringModeCoverageError(
            f"{field_name} must be a collection of strings"
        )
    refs = tuple(_safe_id(value, f"{field_name} item") for value in values or ())
    if not refs:
        raise MonitoringModeCoverageError(f"{field_name} must not be empty")
    if len(refs) != len(set(refs)):
        raise MonitoringModeCoverageError(f"{field_name} must not repeat")
    return tuple(sorted(refs))


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MonitoringModeCoverageError(f"{field_name} must be a string SHA-256")
    if (
        value != value.strip()
        or value != value.lower()
        or not _SHA256_RE.fullmatch(value)
    ):
        raise MonitoringModeCoverageError(f"{field_name} must be a lowercase SHA-256")
    return value


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise MonitoringModeCoverageError(
            "mode coverage evidence must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MonitoringModeEvidence:
    """One mode-specific observation bound to one clean acceptance run."""

    evidence_id: str
    mode_id: str
    acceptance_run_id: str
    evidence_refs: tuple[str, ...]
    evidence_sha256: str
    summary: str
    checkpoint_ids: tuple[str, ...]
    status: str = "passed"
    issue_severities: tuple[str, ...] = ()
    failure_detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _safe_id(self.evidence_id, "evidence_id")
        )
        mode_id = _text(self.mode_id)
        if mode_id not in MONITORING_MODE_IDS:
            raise MonitoringModeCoverageError(f"unsupported monitoring mode: {mode_id}")
        object.__setattr__(self, "mode_id", mode_id)
        object.__setattr__(
            self,
            "acceptance_run_id",
            _safe_id(self.acceptance_run_id, "acceptance_run_id"),
        )
        object.__setattr__(
            self, "evidence_refs", _safe_refs(self.evidence_refs, "evidence_refs")
        )
        object.__setattr__(
            self,
            "evidence_sha256",
            _sha256(self.evidence_sha256, "evidence_sha256"),
        )
        checkpoints = _safe_refs(self.checkpoint_ids, "checkpoint_ids")
        unsupported = tuple(
            checkpoint
            for checkpoint in checkpoints
            if checkpoint not in MONITORING_MODE_CHECKPOINTS[mode_id]
        )
        if unsupported:
            raise MonitoringModeCoverageError(
                "checkpoint_ids contains unsupported values for the selected mode: "
                + ",".join(unsupported)
            )
        object.__setattr__(self, "checkpoint_ids", checkpoints)
        status = _text(self.status)
        if status not in _ALLOWED_STATUSES:
            raise MonitoringModeCoverageError(
                "status must be passed, failed or blocked"
            )
        object.__setattr__(self, "status", status)
        severities = tuple(_text(value) for value in self.issue_severities)
        if len(severities) != len(set(severities)):
            raise MonitoringModeCoverageError("issue_severities must not repeat")
        if any(value not in _ALLOWED_ISSUE_SEVERITIES for value in severities):
            raise MonitoringModeCoverageError("issue_severities must use P0 through P4")
        object.__setattr__(self, "issue_severities", severities)
        if not isinstance(self.summary, str):
            raise MonitoringModeCoverageError("summary must be a string")
        summary = self.summary.strip()
        if not summary:
            raise MonitoringModeCoverageError("summary is required")
        object.__setattr__(self, "summary", summary)
        failure_detail = _text(self.failure_detail)
        if status in {"failed", "blocked"} and not failure_detail:
            raise MonitoringModeCoverageError(
                "failed or blocked mode evidence requires failure_detail"
            )
        object.__setattr__(self, "failure_detail", failure_detail)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "mode_id": self.mode_id,
            "acceptance_run_id": self.acceptance_run_id,
            "evidence_refs": list(self.evidence_refs),
            "evidence_sha256": self.evidence_sha256,
            "summary": self.summary,
            "checkpoint_ids": list(self.checkpoint_ids),
            "status": self.status,
            "issue_severities": list(self.issue_severities),
            "failure_detail": self.failure_detail,
        }


@dataclass(frozen=True)
class MonitoringModeCoverageIssue:
    code: MonitoringModeCoverageIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise MonitoringModeCoverageError("issue subject and detail are required")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class MonitoringModeCoverageReport:
    """Mode coverage evidence; never a medical/UAT/release decision."""

    status: str
    coverage_complete: bool
    evidence_count: int
    covered_mode_ids: tuple[str, ...]
    uncovered_mode_ids: tuple[str, ...]
    covered_role_mode_keys: tuple[str, ...]
    missing_role_mode_keys: tuple[str, ...]
    covered_project_ids: tuple[str, ...]
    missing_project_ids: tuple[str, ...]
    issues: tuple[MonitoringModeCoverageIssue, ...]
    schema_version: str = MONITORING_MODE_COVERAGE_SCHEMA_VERSION
    read_only: bool = True
    authority_granted: bool = False
    medical_confirmation_permitted: bool = False
    runtime_write_permitted: bool = False
    release_ready: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != MONITORING_MODE_COVERAGE_SCHEMA_VERSION:
            raise MonitoringModeCoverageError("unsupported mode coverage schema")
        if self.status not in {"blocked", "complete_for_mode_acceptance_review"}:
            raise MonitoringModeCoverageError("unsupported mode coverage status")
        if not isinstance(self.coverage_complete, bool):
            raise MonitoringModeCoverageError(
                "coverage_complete must be a strict boolean"
            )
        for name in (
            "read_only",
            "authority_granted",
            "medical_confirmation_permitted",
            "runtime_write_permitted",
            "release_ready",
        ):
            expected = name == "read_only"
            if getattr(self, name) is not expected:
                raise MonitoringModeCoverageError(
                    f"{name} has an unsafe authority value"
                )
        if (
            isinstance(self.evidence_count, bool)
            or not isinstance(self.evidence_count, int)
            or self.evidence_count < 0
        ):
            raise MonitoringModeCoverageError("evidence_count must be non-negative")
        for name in (
            "covered_mode_ids",
            "uncovered_mode_ids",
            "covered_role_mode_keys",
            "missing_role_mode_keys",
            "covered_project_ids",
            "missing_project_ids",
        ):
            raw_values = getattr(self, name)
            if isinstance(raw_values, (str, bytes)):
                raise MonitoringModeCoverageError(f"{name} must be a collection")
            values = tuple(raw_values)
            if any(not isinstance(value, str) for value in values):
                raise MonitoringModeCoverageError(f"{name} must contain strings")
            if len(values) != len(set(values)):
                raise MonitoringModeCoverageError(f"{name} must not repeat")
            object.__setattr__(self, name, values)
        issues = tuple(self.issues)
        if any(not isinstance(item, MonitoringModeCoverageIssue) for item in issues):
            raise MonitoringModeCoverageError("issues contain an invalid value")
        expected_complete = (
            not issues
            and not self.uncovered_mode_ids
            and not self.missing_role_mode_keys
            and not self.missing_project_ids
        )
        if (
            self.coverage_complete != expected_complete
            or (self.status == "complete_for_mode_acceptance_review")
            != expected_complete
        ):
            raise MonitoringModeCoverageError(
                "coverage status does not match the observed evidence"
            )
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "coverage_complete": self.coverage_complete,
            "evidence_count": self.evidence_count,
            "covered_mode_ids": list(self.covered_mode_ids),
            "uncovered_mode_ids": list(self.uncovered_mode_ids),
            "covered_role_mode_keys": list(self.covered_role_mode_keys),
            "missing_role_mode_keys": list(self.missing_role_mode_keys),
            "covered_project_ids": list(self.covered_project_ids),
            "missing_project_ids": list(self.missing_project_ids),
            "issues": [item.to_dict() for item in self.issues],
            "read_only": self.read_only,
            "authority_granted": self.authority_granted,
            "medical_confirmation_permitted": self.medical_confirmation_permitted,
            "runtime_write_permitted": self.runtime_write_permitted,
            "release_ready": self.release_ready,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
        }


def _issue(
    issues: list[MonitoringModeCoverageIssue],
    code: MonitoringModeCoverageIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(MonitoringModeCoverageIssue(code, subject, detail))


def _run_is_clean(run: RealLoopAcceptanceRun) -> bool:
    return bool(
        run.run_status == "passed"
        and not run.issue_severities
        and run.login_mode == "playwright_ui"
        and not run.api_login_used
        and run.route_policy_verified
        and run.route_window_verified
        and run.playwright_session_ref
        and run.browser_evidence_ref
        and run.scientific_evidence_ref
    )


def assess_monitoring_mode_coverage(
    evidence: Iterable[MonitoringModeEvidence],
    *,
    acceptance_report: RealLoopAcceptanceReport | None,
    acceptance_runs: Iterable[RealLoopAcceptanceRun],
    expected_mode_ids: Iterable[str] = MONITORING_MODE_IDS,
    expected_roles: Iterable[str] = ACCEPTANCE_ROLES,
    allowed_project_ids: Iterable[str] = ACCEPTANCE_PROJECT_IDS,
) -> MonitoringModeCoverageReport:
    """Validate mode evidence against an accepted user-view run matrix."""

    modes = tuple(expected_mode_ids)
    roles = tuple(expected_roles)
    projects = tuple(allowed_project_ids)
    issues: list[MonitoringModeCoverageIssue] = []
    if modes != MONITORING_MODE_IDS:
        _issue(
            issues,
            MonitoringModeCoverageIssueCode.MODE_SET_MISMATCH,
            "expected_mode_ids",
            f"mode set must be exactly {MONITORING_MODE_IDS!r}",
        )
    if roles != ACCEPTANCE_ROLES:
        _issue(
            issues,
            MonitoringModeCoverageIssueCode.ROLE_SET_MISMATCH,
            "expected_roles",
            f"role set must be exactly {ACCEPTANCE_ROLES!r}",
        )
    if projects != ACCEPTANCE_PROJECT_IDS:
        _issue(
            issues,
            MonitoringModeCoverageIssueCode.PROJECT_SET_MISMATCH,
            "allowed_project_ids",
            f"project set must be exactly {ACCEPTANCE_PROJECT_IDS!r}",
        )
    if acceptance_report is None:
        _issue(
            issues,
            MonitoringModeCoverageIssueCode.ACCEPTANCE_REPORT_MISSING,
            "acceptance_report",
            "a canonical accepted real-loop report is required before mode coverage can be reviewed",
        )
    elif not isinstance(acceptance_report, RealLoopAcceptanceReport):
        _issue(
            issues,
            MonitoringModeCoverageIssueCode.ACCEPTANCE_REPORT_TYPE_INVALID,
            "acceptance_report",
            "acceptance_report must be a RealLoopAcceptanceReport instance",
        )
    elif (
        acceptance_report.status != "accepted_for_user_acceptance"
        or not acceptance_report.acceptance_complete
        or acceptance_report.issues
    ):
        _issue(
            issues,
            MonitoringModeCoverageIssueCode.ACCEPTANCE_REPORT_NOT_COMPLETE,
            "acceptance_report",
            "mode coverage requires an accepted real-loop report with no structural issues",
        )
    run_rows = tuple(acceptance_runs)
    run_by_id: dict[str, RealLoopAcceptanceRun] = {}
    for run in run_rows:
        if run.run_id in run_by_id:
            _issue(
                issues,
                MonitoringModeCoverageIssueCode.ACCEPTANCE_RUN_DUPLICATE,
                run.run_id,
                "acceptance run IDs must be unique",
            )
        run_by_id[run.run_id] = run
    evidence_rows = tuple(evidence)
    seen_evidence_ids: set[str] = set()
    seen_hashes: set[str] = set()
    seen_role_mode: set[tuple[str, str]] = set()
    covered_modes: set[str] = set()
    covered_projects: set[str] = set()
    covered_role_mode: set[str] = set()
    for row in evidence_rows:
        if row.evidence_id in seen_evidence_ids:
            _issue(
                issues,
                MonitoringModeCoverageIssueCode.MODE_EVIDENCE_DUPLICATE,
                row.evidence_id,
                "mode evidence IDs must be unique",
            )
        seen_evidence_ids.add(row.evidence_id)
        if row.evidence_sha256 in seen_hashes:
            _issue(
                issues,
                MonitoringModeCoverageIssueCode.MODE_EVIDENCE_HASH_DUPLICATE,
                row.evidence_id,
                "mode evidence hashes must be unique; copied evidence cannot satisfy another mode",
            )
        seen_hashes.add(row.evidence_sha256)
        if row.mode_id not in modes:
            _issue(
                issues,
                MonitoringModeCoverageIssueCode.MODE_UNKNOWN,
                row.evidence_id,
                "mode evidence references a mode outside the frozen set",
            )
            continue
        run = run_by_id.get(row.acceptance_run_id)
        if run is None:
            _issue(
                issues,
                MonitoringModeCoverageIssueCode.ACCEPTANCE_RUN_MISSING,
                row.evidence_id,
                "mode evidence must reference an observed acceptance run",
            )
            continue
        if not _run_is_clean(run):
            _issue(
                issues,
                MonitoringModeCoverageIssueCode.ACCEPTANCE_RUN_NOT_CLEAN,
                row.evidence_id,
                "mode evidence must bind to a passed Playwright/scientific run with no P0-P4 issues",
            )
        if run.role not in roles:
            _issue(
                issues,
                MonitoringModeCoverageIssueCode.ROLE_SET_MISMATCH,
                row.evidence_id,
                "acceptance run role is outside the frozen role set",
            )
        if run.project_id not in projects:
            _issue(
                issues,
                MonitoringModeCoverageIssueCode.PROJECT_SET_MISMATCH,
                row.evidence_id,
                "acceptance run project is outside the candidate project set",
            )
        key = (run.role, row.mode_id)
        if key in seen_role_mode:
            _issue(
                issues,
                MonitoringModeCoverageIssueCode.ROLE_MODE_DUPLICATE,
                row.evidence_id,
                "each role/mode pair must have one unambiguous evidence row",
            )
        seen_role_mode.add(key)
        if row.status != "passed" or row.issue_severities:
            _issue(
                issues,
                MonitoringModeCoverageIssueCode.STATUS_INVALID,
                row.evidence_id,
                "mode evidence must be passed with no P0-P4 issue severities",
            )
        if not row.evidence_refs:
            _issue(
                issues,
                MonitoringModeCoverageIssueCode.EVIDENCE_REFERENCE_MISSING,
                row.evidence_id,
                "mode-specific evidence references are required",
            )
        required_checkpoints = set(MONITORING_MODE_CHECKPOINTS[row.mode_id])
        missing_checkpoints = tuple(
            sorted(required_checkpoints - set(row.checkpoint_ids))
        )
        if missing_checkpoints:
            _issue(
                issues,
                MonitoringModeCoverageIssueCode.MODE_CHECKPOINTS_MISSING,
                row.evidence_id,
                "mode evidence is missing required checkpoints: "
                + ",".join(missing_checkpoints),
            )
        covered_modes.add(row.mode_id)
        covered_projects.add(run.project_id)
        covered_role_mode.add(f"{run.role}:{row.mode_id}")
    required_role_mode = {f"{role}:{mode}" for role in roles for mode in modes}
    missing_role_mode = tuple(sorted(required_role_mode - covered_role_mode))
    for key in missing_role_mode:
        _issue(
            issues,
            MonitoringModeCoverageIssueCode.ROLE_MODE_MISSING,
            key,
            "each declared role must have one clean evidence row for every monitoring mode",
        )
    uncovered_modes = tuple(mode for mode in modes if mode not in covered_modes)
    missing_projects = tuple(
        project for project in projects if project not in covered_projects
    )
    for project in missing_projects:
        _issue(
            issues,
            MonitoringModeCoverageIssueCode.PROJECT_COVERAGE_MISSING,
            project,
            "each candidate project must appear in at least one mode evidence row",
        )
    covered_mode_ids = tuple(mode for mode in modes if mode in covered_modes)
    covered_project_ids = tuple(
        project for project in projects if project in covered_projects
    )
    complete = (
        not issues
        and not uncovered_modes
        and not missing_role_mode
        and not missing_projects
    )
    return MonitoringModeCoverageReport(
        status="complete_for_mode_acceptance_review" if complete else "blocked",
        coverage_complete=complete,
        evidence_count=len(evidence_rows),
        covered_mode_ids=covered_mode_ids,
        uncovered_mode_ids=uncovered_modes,
        covered_role_mode_keys=tuple(sorted(covered_role_mode)),
        missing_role_mode_keys=missing_role_mode,
        covered_project_ids=covered_project_ids,
        missing_project_ids=missing_projects,
        issues=tuple(issues),
        read_only=True,
        authority_granted=False,
        medical_confirmation_permitted=False,
        runtime_write_permitted=False,
        release_ready=False,
    )


__all__ = [
    "MONITORING_MODE_COVERAGE_SCHEMA_VERSION",
    "MONITORING_MODE_IDS",
    "MONITORING_MODE_CHECKPOINTS",
    "MonitoringModeCoverageError",
    "MonitoringModeCoverageIssue",
    "MonitoringModeCoverageIssueCode",
    "MonitoringModeCoverageReport",
    "MonitoringModeEvidence",
    "assess_monitoring_mode_coverage",
]
