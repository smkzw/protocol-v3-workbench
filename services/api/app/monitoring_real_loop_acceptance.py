"""Fail-closed acceptance contract for the future real-LOOP test matrix.

This module records the evidence required by the requested serial tester loop:
five tester routes, engineer and senior-medical-monitor roles, Playwright-only
user-view login, varied prompts/projects, repair/retest evidence and two final
consecutive rounds with no P0-P4 issues.  It never starts a browser, calls a
provider, logs in, writes application state or grants medical/release authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable
from zoneinfo import ZoneInfo


REAL_LOOP_ACCEPTANCE_SCHEMA_VERSION = "medical_monitoring_real_loop_acceptance_v3"
ACCEPTANCE_ROLES = ("engineer", "senior_medical_monitor")
ACCEPTANCE_PROJECT_IDS = (
    "proj_mgk10_sar_real",
    "proj_rux_03_002",
    "proj_my008_3_02_candidate",
    "proj_my008_3_01_candidate",
    "proj_my009_uc",
)
ACCEPTANCE_TESTER_ROUTES = {
    "pi_opencode_go_deepseek_v4_flash": {
        "route": "pi/opencode-go/deepseek-v4-flash",
        "window": "07:30-22:00 Asia/Shanghai",
    },
    "pi_alibaba_qwen3_8_max_preview": {
        "route": "pi/alibaba/qwen3.8-max-preview",
        "window": "22:00-07:30 Asia/Shanghai",
    },
    "codebuddy_hy3": {
        "route": "codebuddy cli/hy3",
        "window": "route-policy validation required",
    },
    "codebuddy_minimax_m3": {
        "route": "codebuddy cli/minimax-m3",
        "window": "route-policy validation required",
    },
    "codebuddy_glm_5_2": {
        "route": "codebuddy cli/glm-5.2",
        "window": "route-policy validation required",
    },
}
ACCEPTANCE_TESTER_IDS = tuple(ACCEPTANCE_TESTER_ROUTES)
ACCEPTANCE_STATUSES = {"passed", "failed", "blocked"}
ALLOWED_ISSUE_SEVERITIES = {"P0", "P1", "P2", "P3", "P4"}
PLAYWRIGHT_UI_LOGIN = "playwright_ui"
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class RealLoopAcceptanceError(ValueError):
    """Raised when a future acceptance evidence row is structurally unsafe."""


class RealLoopAcceptanceIssueCode(str, Enum):
    TESTER_SET_MISMATCH = "tester_set_mismatch"
    ROLE_SET_MISMATCH = "role_set_mismatch"
    PROJECT_SET_MISMATCH = "project_set_mismatch"
    EXPECTED_TESTER_SET_MISMATCH = "expected_tester_set_mismatch"
    EXPECTED_ROLE_SET_MISMATCH = "expected_role_set_mismatch"
    EXPECTED_PROJECT_SET_MISMATCH = "expected_project_set_mismatch"
    RUN_DUPLICATE = "run_duplicate"
    SERIAL_RUN_OVERLAP = "serial_run_overlap"
    ROUND_DUPLICATE = "round_duplicate"
    ROUND_SEQUENCE_INVALID = "round_sequence_invalid"
    PROMPT_REFERENCE_MISSING = "prompt_reference_missing"
    PROMPT_HASH_INVALID = "prompt_hash_invalid"
    PROMPT_DUPLICATE = "prompt_duplicate"
    PROMPT_MANIFEST_MISSING = "prompt_manifest_missing"
    PROMPT_MANIFEST_MISMATCH = "prompt_manifest_mismatch"
    PROMPT_MANIFEST_DUPLICATE = "prompt_manifest_duplicate"
    PROMPT_MANIFEST_HASH_DUPLICATE = "prompt_manifest_hash_duplicate"
    TESTER_ROUTE_MISMATCH = "tester_route_mismatch"
    ROUTE_NOT_VERIFIED = "route_not_verified"
    TIMESTAMP_INVALID = "timestamp_invalid"
    TIME_WINDOW_INVALID = "time_window_invalid"
    LOGIN_MODE_INVALID = "login_mode_invalid"
    API_LOGIN_USED = "api_login_used"
    BROWSER_EVIDENCE_MISSING = "browser_evidence_missing"
    SCIENTIFIC_EVIDENCE_MISSING = "scientific_evidence_missing"
    STATUS_INVALID = "status_invalid"
    ISSUE_SEVERITY_INVALID = "issue_severity_invalid"
    ISSUE_TRACEABILITY_MISSING = "issue_traceability_missing"
    FAILURE_DETAIL_MISSING = "failure_detail_missing"
    REPAIR_EVIDENCE_MISSING = "repair_evidence_missing"
    EVIDENCE_CHAIN_HASH_INVALID = "evidence_chain_hash_invalid"
    COVERAGE_MISSING = "coverage_missing"
    PROJECT_COVERAGE_MISSING = "project_coverage_missing"
    CLEAN_STREAK_MISSING = "clean_streak_missing"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_id(value: Any, field_name: str) -> str:
    text = _text(value)
    if not _SAFE_ID_RE.fullmatch(text):
        raise RealLoopAcceptanceError(
            f"{field_name} must be a non-empty opaque identifier"
        )
    return text


def _safe_refs(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    refs = tuple(_safe_id(value, field_name) for value in values)
    if len(refs) != len(set(refs)):
        raise RealLoopAcceptanceError(f"{field_name} must not repeat")
    return tuple(sorted(refs))


def _sha256(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or value != value.lower()
        or not _SHA256_RE.fullmatch(value)
    ):
        raise RealLoopAcceptanceError(f"{field_name} must be a lowercase SHA-256")
    return value


def _is_canonical_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and value == value.lower()
        and _SHA256_RE.fullmatch(value) is not None
    )


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise RealLoopAcceptanceError(
            "acceptance evidence must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RealLoopAcceptancePrompt:
    """One exact prompt identity supplied by the frozen prompt manifest."""

    prompt_ref: str
    prompt_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "prompt_ref", _safe_id(self.prompt_ref, "prompt_ref"))
        object.__setattr__(
            self, "prompt_sha256", _sha256(self.prompt_sha256, "prompt_sha256")
        )


@dataclass(frozen=True)
class RealLoopAcceptanceRun:
    """One tester/role/project round observed through the browser UI."""

    run_id: str
    tester_id: str
    role: str
    project_id: str
    round_number: int
    prompt_ref: str
    prompt_sha256: str
    tester_route: str
    route_policy_verified: bool
    route_window_verified: bool
    started_at: str
    ended_at: str
    login_mode: str
    api_login_used: bool
    playwright_session_ref: str
    browser_evidence_ref: str
    scientific_evidence_ref: str
    run_status: str
    issue_severities: tuple[str, ...] = ()
    issue_refs: tuple[str, ...] = ()
    failure_detail: str = ""
    repair_evidence_refs: tuple[str, ...] = ()
    retest_of: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        object.__setattr__(self, "tester_id", _safe_id(self.tester_id, "tester_id"))
        object.__setattr__(self, "role", _safe_id(self.role, "role"))
        object.__setattr__(self, "project_id", _safe_id(self.project_id, "project_id"))
        for field_name in (
            "route_policy_verified",
            "route_window_verified",
            "api_login_used",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise RealLoopAcceptanceError(f"{field_name} must be a boolean")
        if isinstance(self.round_number, bool) or not isinstance(
            self.round_number, int
        ):
            raise RealLoopAcceptanceError("round_number must be an integer")
        if self.round_number < 1:
            raise RealLoopAcceptanceError("round_number must be positive")
        object.__setattr__(self, "prompt_ref", _safe_id(self.prompt_ref, "prompt_ref"))
        object.__setattr__(
            self, "prompt_sha256", _sha256(self.prompt_sha256, "prompt_sha256")
        )
        object.__setattr__(self, "tester_route", _text(self.tester_route))
        object.__setattr__(self, "started_at", _text(self.started_at))
        object.__setattr__(self, "ended_at", _text(self.ended_at))
        object.__setattr__(self, "login_mode", _text(self.login_mode))
        object.__setattr__(
            self,
            "playwright_session_ref",
            _text(self.playwright_session_ref),
        )
        object.__setattr__(
            self, "browser_evidence_ref", _text(self.browser_evidence_ref)
        )
        object.__setattr__(
            self, "scientific_evidence_ref", _text(self.scientific_evidence_ref)
        )
        object.__setattr__(self, "run_status", _text(self.run_status))
        object.__setattr__(
            self,
            "issue_severities",
            tuple(_text(value) for value in self.issue_severities),
        )
        object.__setattr__(self, "issue_refs", _safe_refs(self.issue_refs, "issue_ref"))
        object.__setattr__(self, "failure_detail", _text(self.failure_detail))
        object.__setattr__(
            self,
            "repair_evidence_refs",
            _safe_refs(self.repair_evidence_refs, "repair_evidence_ref"),
        )
        retest_of = _text(self.retest_of)
        if retest_of:
            retest_of = _safe_id(retest_of, "retest_of")
        object.__setattr__(self, "retest_of", retest_of)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "tester_id": self.tester_id,
            "role": self.role,
            "project_id": self.project_id,
            "round_number": self.round_number,
            "prompt_ref": self.prompt_ref,
            "prompt_sha256": self.prompt_sha256,
            "tester_route": self.tester_route,
            "route_policy_verified": self.route_policy_verified,
            "route_window_verified": self.route_window_verified,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "login_mode": self.login_mode,
            "api_login_used": self.api_login_used,
            "playwright_session_ref": self.playwright_session_ref,
            "browser_evidence_ref": self.browser_evidence_ref,
            "scientific_evidence_ref": self.scientific_evidence_ref,
            "run_status": self.run_status,
            "issue_severities": list(self.issue_severities),
            "issue_refs": list(self.issue_refs),
            "failure_detail": self.failure_detail,
            "repair_evidence_refs": list(self.repair_evidence_refs),
            "retest_of": self.retest_of,
        }


@dataclass(frozen=True)
class RealLoopAcceptanceIssue:
    code: RealLoopAcceptanceIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise RealLoopAcceptanceError("issue subject and detail are required")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class RealLoopAcceptanceReport:
    """Acceptance evidence status; never a medical or release decision."""

    status: str
    acceptance_complete: bool
    tester_count: int
    role_count: int
    run_count: int
    clean_streak_by_tester_role: tuple[tuple[str, int], ...]
    issues: tuple[RealLoopAcceptanceIssue, ...]
    readiness_report_sha256: str = ""
    generalization_evidence_sha256: str = ""
    execution_report_sha256: str = ""
    semantics_binding_sha256: str = ""
    medical_confirmation_permitted: bool = False
    runtime_write_permitted: bool = False
    schema_version: str = REAL_LOOP_ACCEPTANCE_SCHEMA_VERSION
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != REAL_LOOP_ACCEPTANCE_SCHEMA_VERSION:
            raise RealLoopAcceptanceError("unsupported acceptance schema version")
        if self.status not in {"blocked", "accepted_for_user_acceptance"}:
            raise RealLoopAcceptanceError("invalid acceptance status")
        for name in (
            "acceptance_complete",
            "medical_confirmation_permitted",
            "runtime_write_permitted",
        ):
            if not isinstance(getattr(self, name), bool):
                raise RealLoopAcceptanceError(f"{name} must be a strict boolean")
        if self.medical_confirmation_permitted or self.runtime_write_permitted:
            raise RealLoopAcceptanceError("acceptance evidence cannot grant authority")
        for field_name in (
            "readiness_report_sha256",
            "generalization_evidence_sha256",
            "execution_report_sha256",
            "semantics_binding_sha256",
        ):
            raw_value = getattr(self, field_name)
            if raw_value is None or raw_value == "":
                value = ""
            elif not _is_canonical_sha256(raw_value):
                raise RealLoopAcceptanceError(
                    f"{field_name} must be a lowercase SHA-256"
                )
            else:
                value = raw_value
            object.__setattr__(self, field_name, value)
        if self.acceptance_complete and any(
            not _text(getattr(self, field_name))
            for field_name in (
                "readiness_report_sha256",
                "generalization_evidence_sha256",
                "execution_report_sha256",
                "semantics_binding_sha256",
            )
        ):
            raise RealLoopAcceptanceError(
                "complete acceptance evidence requires the upstream evidence chain hashes"
            )
        issues = tuple(self.issues)
        expected_complete = not issues and self.status == "accepted_for_user_acceptance"
        if self.acceptance_complete != expected_complete:
            raise RealLoopAcceptanceError("acceptance_complete does not match issues")
        issues = tuple(
            sorted(
                issues,
                key=lambda item: (
                    getattr(item.code, "value", str(item.code)),
                    item.subject,
                    item.detail,
                ),
            )
        )
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "acceptance_complete": self.acceptance_complete,
            "tester_count": self.tester_count,
            "role_count": self.role_count,
            "run_count": self.run_count,
            "clean_streak_by_tester_role": [
                {"tester_role": key, "streak": streak}
                for key, streak in self.clean_streak_by_tester_role
            ],
            "readiness_report_sha256": self.readiness_report_sha256,
            "generalization_evidence_sha256": self.generalization_evidence_sha256,
            "execution_report_sha256": self.execution_report_sha256,
            "semantics_binding_sha256": self.semantics_binding_sha256,
            "issues": [issue.to_dict() for issue in self.issues],
            "medical_confirmation_permitted": self.medical_confirmation_permitted,
            "runtime_write_permitted": self.runtime_write_permitted,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
        }


def _parse_timestamp(value: str) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _route_window_ok(tester_id: str, timestamp: datetime) -> bool:
    route = ACCEPTANCE_TESTER_ROUTES[tester_id]["route"]
    local = timestamp.astimezone(_SHANGHAI)
    minutes = local.hour * 60 + local.minute
    if route == "pi/opencode-go/deepseek-v4-flash":
        return 7 * 60 + 30 <= minutes < 22 * 60
    if route == "pi/alibaba/qwen3.8-max-preview":
        return minutes >= 22 * 60 or minutes < 7 * 60 + 30
    return True


def _issue(
    issues: list[RealLoopAcceptanceIssue],
    code: RealLoopAcceptanceIssueCode,
    run: RealLoopAcceptanceRun | None,
    detail: str,
    subject: str | None = None,
) -> None:
    issues.append(
        RealLoopAcceptanceIssue(
            code,
            subject or (run.run_id if run else "acceptance_matrix"),
            detail,
        )
    )


def _is_clean(run: RealLoopAcceptanceRun, structural_issue_count: int) -> bool:
    return bool(
        structural_issue_count == 0
        and run.run_status == "passed"
        and not run.issue_severities
        and run.login_mode == PLAYWRIGHT_UI_LOGIN
        and not run.api_login_used
        and run.route_policy_verified
        and run.route_window_verified
        and bool(run.playwright_session_ref)
        and bool(run.browser_evidence_ref)
        and bool(run.scientific_evidence_ref)
    )


def assess_real_loop_acceptance(
    runs: Iterable[RealLoopAcceptanceRun],
    *,
    prompt_manifest: Iterable[RealLoopAcceptancePrompt] | None = None,
    expected_testers: Iterable[str] = ACCEPTANCE_TESTER_IDS,
    expected_roles: Iterable[str] = ACCEPTANCE_ROLES,
    allowed_project_ids: Iterable[str] = ACCEPTANCE_PROJECT_IDS,
    required_consecutive_clean_rounds: int = 2,
    readiness_report_sha256: str = "",
    generalization_evidence_sha256: str = "",
    execution_report_sha256: str = "",
    semantics_binding_sha256: str = "",
) -> RealLoopAcceptanceReport:
    """Validate future user-view acceptance evidence without executing it."""

    if (
        isinstance(required_consecutive_clean_rounds, bool)
        or not isinstance(required_consecutive_clean_rounds, int)
        or required_consecutive_clean_rounds < 2
    ):
        raise RealLoopAcceptanceError(
            "required_consecutive_clean_rounds must be an integer >= 2"
        )
    tester_ids = _safe_refs(expected_testers, "expected_tester_id")
    role_ids = _safe_refs(expected_roles, "expected_role")
    project_ids = _safe_refs(allowed_project_ids, "allowed_project_id")
    runs_rows = tuple(runs)
    manifest_rows = tuple(prompt_manifest or ())
    issues: list[RealLoopAcceptanceIssue] = []
    chain_hashes: dict[str, str] = {}
    for field_name, raw_value in (
        ("readiness_report_sha256", readiness_report_sha256),
        ("generalization_evidence_sha256", generalization_evidence_sha256),
        ("execution_report_sha256", execution_report_sha256),
        ("semantics_binding_sha256", semantics_binding_sha256),
    ):
        value = raw_value if isinstance(raw_value, str) else ""
        if not _is_canonical_sha256(raw_value):
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.EVIDENCE_CHAIN_HASH_INVALID,
                None,
                f"{field_name} must carry the exact upstream lowercase SHA-256; missing or malformed values fail closed",
                subject=field_name,
            )
            value = ""
        chain_hashes[field_name] = value
    frozen_sets = (
        (
            tester_ids,
            tuple(sorted(ACCEPTANCE_TESTER_IDS)),
            RealLoopAcceptanceIssueCode.EXPECTED_TESTER_SET_MISMATCH,
            "expected_testers",
        ),
        (
            role_ids,
            tuple(sorted(ACCEPTANCE_ROLES)),
            RealLoopAcceptanceIssueCode.EXPECTED_ROLE_SET_MISMATCH,
            "expected_roles",
        ),
        (
            project_ids,
            tuple(sorted(ACCEPTANCE_PROJECT_IDS)),
            RealLoopAcceptanceIssueCode.EXPECTED_PROJECT_SET_MISMATCH,
            "allowed_project_ids",
        ),
    )
    for observed, expected, code, subject in frozen_sets:
        if observed != expected:
            _issue(
                issues,
                code,
                None,
                f"{subject} must match the frozen acceptance matrix exactly; expected={expected!r}, observed={observed!r}",
                subject=subject,
            )
    prompt_by_ref: dict[str, RealLoopAcceptancePrompt] = {}
    prompt_hashes: set[str] = set()
    if not manifest_rows:
        _issue(
            issues,
            RealLoopAcceptanceIssueCode.PROMPT_MANIFEST_MISSING,
            None,
            "a frozen prompt manifest is required for every acceptance run",
        )
    for prompt in manifest_rows:
        if prompt.prompt_ref in prompt_by_ref:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.PROMPT_MANIFEST_DUPLICATE,
                None,
                "prompt manifest references must be unique",
                subject=prompt.prompt_ref,
            )
        if prompt.prompt_sha256 in prompt_hashes:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.PROMPT_MANIFEST_HASH_DUPLICATE,
                None,
                "prompt manifest hashes must be unique so each round uses different content",
                subject=prompt.prompt_ref,
            )
        prompt_hashes.add(prompt.prompt_sha256)
        prompt_by_ref[prompt.prompt_ref] = prompt
    seen_run_ids: set[str] = set()
    seen_prompt_refs: set[str] = set()
    groups: dict[tuple[str, str], list[RealLoopAcceptanceRun]] = {}
    projects_seen: set[str] = set()
    structural_issue_by_run: dict[str, int] = {}
    valid_intervals: list[tuple[datetime, datetime, RealLoopAcceptanceRun]] = []

    for run in runs_rows:
        before = len(issues)
        if run.run_id in seen_run_ids:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.RUN_DUPLICATE,
                run,
                "run_id must be unique",
            )
        seen_run_ids.add(run.run_id)
        if run.tester_id not in tester_ids:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.TESTER_SET_MISMATCH,
                run,
                "tester is outside the declared acceptance tester matrix",
            )
        if run.role not in role_ids:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.ROLE_SET_MISMATCH,
                run,
                "role is outside the declared acceptance role matrix",
            )
        if run.project_id not in project_ids:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.PROJECT_SET_MISMATCH,
                run,
                "project is outside the declared candidate matrix",
            )
        else:
            projects_seen.add(run.project_id)
        catalog = ACCEPTANCE_TESTER_ROUTES.get(run.tester_id)
        if catalog is None or run.tester_route != catalog["route"]:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.TESTER_ROUTE_MISMATCH,
                run,
                "tester route must match the frozen requested route catalog",
            )
        if not run.route_policy_verified or not run.route_window_verified:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.ROUTE_NOT_VERIFIED,
                run,
                "route policy and route-window verification are required before acceptance",
            )
        started = _parse_timestamp(run.started_at)
        ended = _parse_timestamp(run.ended_at)
        if started is None or ended is None or ended <= started:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.TIMESTAMP_INVALID,
                run,
                "started_at and ended_at must be timezone-aware and ordered",
            )
        elif catalog and not (
            _route_window_ok(run.tester_id, started)
            and _route_window_ok(run.tester_id, ended)
        ):
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.TIME_WINDOW_INVALID,
                run,
                "tester run is outside the declared Beijing-time route window",
            )
        if started is not None and ended is not None and ended > started:
            valid_intervals.append((started, ended, run))
        if run.login_mode != PLAYWRIGHT_UI_LOGIN:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.LOGIN_MODE_INVALID,
                run,
                "acceptance requires Playwright user-view login",
            )
        if run.api_login_used:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.API_LOGIN_USED,
                run,
                "API/backend login cannot substitute for browser evidence",
            )
        if not run.playwright_session_ref or not run.browser_evidence_ref:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.BROWSER_EVIDENCE_MISSING,
                run,
                "Playwright session and browser evidence refs are required",
            )
        if not run.scientific_evidence_ref:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.SCIENTIFIC_EVIDENCE_MISSING,
                run,
                "scientific/medical observation evidence ref is required",
            )
        if run.prompt_ref in seen_prompt_refs:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.PROMPT_DUPLICATE,
                run,
                "each tester round must use a distinct auditable prompt reference",
            )
        seen_prompt_refs.add(run.prompt_ref)
        if not _SHA256_RE.fullmatch(run.prompt_sha256):
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.PROMPT_HASH_INVALID,
                run,
                "prompt_sha256 must be a lowercase SHA-256",
            )
        if manifest_rows:
            manifest_prompt = prompt_by_ref.get(run.prompt_ref)
            if (
                manifest_prompt is None
                or manifest_prompt.prompt_sha256 != run.prompt_sha256
            ):
                _issue(
                    issues,
                    RealLoopAcceptanceIssueCode.PROMPT_MANIFEST_MISMATCH,
                    run,
                    "prompt reference and SHA must match one frozen acceptance prompt-manifest row",
                )
        if run.run_status not in ACCEPTANCE_STATUSES:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.STATUS_INVALID,
                run,
                "run_status must be passed, failed or blocked",
            )
        severity_set = set(run.issue_severities)
        if any(severity not in ALLOWED_ISSUE_SEVERITIES for severity in severity_set):
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.ISSUE_SEVERITY_INVALID,
                run,
                "issue severities must be from P0 through P4",
            )
        if len(severity_set) != len(run.issue_severities):
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.ISSUE_SEVERITY_INVALID,
                run,
                "issue severities must not repeat",
            )
        if run.issue_severities and not run.issue_refs:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.ISSUE_TRACEABILITY_MISSING,
                run,
                "every P0-P4 issue must have an evidence reference",
            )
        if run.run_status in {"failed", "blocked"} and not run.failure_detail:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.FAILURE_DETAIL_MISSING,
                run,
                "failed or blocked rounds require failure detail",
            )
        if (
            run.issue_severities or run.run_status != "passed"
        ) and not run.repair_evidence_refs:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.REPAIR_EVIDENCE_MISSING,
                run,
                "dirty rounds require repair/retest evidence before the next clean streak",
            )
        groups.setdefault((run.tester_id, run.role), []).append(run)
        structural_issue_by_run[run.run_id] = len(issues) - before

    previous_interval: tuple[datetime, datetime, RealLoopAcceptanceRun] | None = None
    for started, ended, run in sorted(
        valid_intervals, key=lambda item: (item[0], item[1], item[2].run_id)
    ):
        if previous_interval is not None and started < previous_interval[1]:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.SERIAL_RUN_OVERLAP,
                run,
                "serial acceptance requires non-overlapping Playwright sessions; this run starts before the preceding run ended",
            )
            structural_issue_by_run[run.run_id] = (
                structural_issue_by_run.get(run.run_id, 0) + 1
            )
        if previous_interval is None or ended > previous_interval[1]:
            previous_interval = (started, ended, run)

    for project_id in project_ids:
        if project_id not in projects_seen:
            _issue(
                issues,
                RealLoopAcceptanceIssueCode.PROJECT_COVERAGE_MISSING,
                None,
                "each candidate project must appear in at least one user-view round",
                subject=project_id,
            )

    streaks: list[tuple[str, int]] = []
    for tester_id in tester_ids:
        for role in role_ids:
            key = (tester_id, role)
            rows = sorted(groups.get(key, ()), key=lambda item: item.round_number)
            if len(rows) < required_consecutive_clean_rounds:
                _issue(
                    issues,
                    RealLoopAcceptanceIssueCode.COVERAGE_MISSING,
                    None,
                    f"each tester/role requires at least {required_consecutive_clean_rounds} rounds",
                    subject=f"{tester_id}:{role}",
                )
                streaks.append((f"{tester_id}:{role}", 0))
                continue
            round_numbers = [row.round_number for row in rows]
            if len(round_numbers) != len(set(round_numbers)):
                _issue(
                    issues,
                    RealLoopAcceptanceIssueCode.ROUND_DUPLICATE,
                    None,
                    "round numbers must be unique within each tester/role stream",
                    subject=f"{tester_id}:{role}",
                )
            if round_numbers != list(range(round_numbers[0], round_numbers[-1] + 1)):
                _issue(
                    issues,
                    RealLoopAcceptanceIssueCode.ROUND_SEQUENCE_INVALID,
                    None,
                    "round numbers must be contiguous; skipped rounds cannot be counted as consecutive",
                    subject=f"{tester_id}:{role}",
                )
            streak = 0
            for row in reversed(rows):
                if _is_clean(row, structural_issue_by_run.get(row.run_id, 0)):
                    streak += 1
                else:
                    break
            streaks.append((f"{tester_id}:{role}", streak))
            if streak < required_consecutive_clean_rounds:
                _issue(
                    issues,
                    RealLoopAcceptanceIssueCode.CLEAN_STREAK_MISSING,
                    None,
                    f"the final stream must contain {required_consecutive_clean_rounds} consecutive clean rounds with no P0-P4",
                    subject=f"{tester_id}:{role}",
                )

    return RealLoopAcceptanceReport(
        status="accepted_for_user_acceptance" if not issues else "blocked",
        acceptance_complete=not issues,
        tester_count=len(tester_ids),
        role_count=len(role_ids),
        run_count=len(runs_rows),
        clean_streak_by_tester_role=tuple(sorted(streaks)),
        issues=tuple(issues),
        readiness_report_sha256=chain_hashes["readiness_report_sha256"],
        generalization_evidence_sha256=chain_hashes[
            "generalization_evidence_sha256"
        ],
        execution_report_sha256=chain_hashes["execution_report_sha256"],
        semantics_binding_sha256=chain_hashes["semantics_binding_sha256"],
    )


__all__ = [
    "ACCEPTANCE_PROJECT_IDS",
    "ACCEPTANCE_ROLES",
    "ACCEPTANCE_STATUSES",
    "ACCEPTANCE_TESTER_IDS",
    "ACCEPTANCE_TESTER_ROUTES",
    "ALLOWED_ISSUE_SEVERITIES",
    "PLAYWRIGHT_UI_LOGIN",
    "REAL_LOOP_ACCEPTANCE_SCHEMA_VERSION",
    "RealLoopAcceptanceError",
    "RealLoopAcceptanceIssue",
    "RealLoopAcceptanceIssueCode",
    "RealLoopAcceptancePrompt",
    "RealLoopAcceptanceReport",
    "RealLoopAcceptanceRun",
    "assess_real_loop_acceptance",
]
