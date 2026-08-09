"""Fail-closed evidence contract for a completed five-project LOOP.

The readiness contract decides whether a controlled run may be entered.  This
module consumes only the evidence produced *after* such a run and checks that
each planned scenario has a traceable, time-window-valid result.  It never
calls a provider, reads a local source, starts a runtime, writes application
state, or treats an AI result as medical acceptance.
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

from .monitoring_real_loop_readiness import (
    REAL_LOOP_MODEL_ROUTES,
    RealLoopReadinessReport,
    RealLoopScenario,
)


REAL_LOOP_EXECUTION_SCHEMA_VERSION = "medical_monitoring_real_loop_execution_v3"
EXECUTION_STATUSES = {"passed", "failed", "blocked"}
UNCERTAINTY_STATES = {
    "confirmed",
    "uncertain",
    "not_assessable",
    "not_applicable",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class RealLoopExecutionError(ValueError):
    """Raised when an execution evidence record is structurally unsafe."""


class RealLoopExecutionIssueCode(str, Enum):
    READINESS_NOT_READY = "readiness_not_ready"
    READINESS_REPORT_HASH_INVALID = "readiness_report_hash_invalid"
    GENERALIZATION_EVIDENCE_HASH_INVALID = "generalization_evidence_hash_invalid"
    SEMANTICS_BINDING_HASH_INVALID = "semantics_binding_hash_invalid"
    EVIDENCE_SET_MISMATCH = "evidence_set_mismatch"
    EVIDENCE_DUPLICATE = "evidence_duplicate"
    SCENARIO_IDENTITY_MISMATCH = "scenario_identity_mismatch"
    SCENARIO_STATUS_MISMATCH = "scenario_status_mismatch"
    BATCH_REFERENCE_MISMATCH = "batch_reference_mismatch"
    OUTPUT_HASH_INVALID = "output_hash_invalid"
    OUTPUT_REFERENCE_MISSING = "output_reference_missing"
    TRACEABILITY_MISSING = "traceability_missing"
    UNCERTAINTY_INVALID = "uncertainty_invalid"
    TIMESTAMP_INVALID = "timestamp_invalid"
    TIME_WINDOW_INVALID = "time_window_invalid"
    FAILURE_DETAIL_MISSING = "failure_detail_missing"
    EXECUTION_NOT_PASSED = "execution_not_passed"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise RealLoopExecutionError(
            "execution evidence must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_id(value: Any, field_name: str) -> str:
    text = _text(value)
    if not _SAFE_ID_RE.fullmatch(text):
        raise RealLoopExecutionError(
            f"{field_name} must be a non-empty opaque identifier"
        )
    return text


def _sha256(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or value != value.lower()
        or not _SHA256_RE.fullmatch(value)
    ):
        raise RealLoopExecutionError(f"{field_name} must be a lowercase SHA-256")
    return value


def _is_canonical_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and value == value.lower()
        and _SHA256_RE.fullmatch(value) is not None
    )


def _ids(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_safe_id(value, field_name) for value in values)
    if not normalized:
        raise RealLoopExecutionError(f"{field_name} must not be empty")
    if len(normalized) != len(set(normalized)):
        raise RealLoopExecutionError(f"{field_name} must not repeat")
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class RealLoopScenarioEvidence:
    """One post-run result bound to one planned scenario."""

    scenario_id: str
    project_id: str
    role: str
    task_type: str
    prompt_sha256: str
    model_route: str
    run_status: str
    started_at: str
    ended_at: str
    batch_ref: str
    evidence_refs: tuple[str, ...]
    uncertainty_state: str
    output_ref: str = ""
    output_sha256: str = ""
    failure_detail: str = ""
    prompt_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "scenario_id", _safe_id(self.scenario_id, "scenario_id")
        )
        object.__setattr__(self, "project_id", _safe_id(self.project_id, "project_id"))
        object.__setattr__(self, "role", _safe_id(self.role, "role"))
        object.__setattr__(self, "task_type", _safe_id(self.task_type, "task_type"))
        object.__setattr__(
            self, "prompt_sha256", _sha256(self.prompt_sha256, "prompt_sha256")
        )
        if self.model_route not in REAL_LOOP_MODEL_ROUTES:
            raise RealLoopExecutionError(
                "model_route is outside the approved real-LOOP routes"
            )
        if self.run_status not in EXECUTION_STATUSES:
            raise RealLoopExecutionError("run_status must be passed, failed or blocked")
        object.__setattr__(self, "started_at", _text(self.started_at))
        object.__setattr__(self, "ended_at", _text(self.ended_at))
        object.__setattr__(self, "batch_ref", _safe_id(self.batch_ref, "batch_ref"))
        output_ref = _text(self.output_ref)
        if output_ref:
            output_ref = _safe_id(output_ref, "output_ref")
        object.__setattr__(self, "output_ref", output_ref)
        if self.output_sha256 is None or self.output_sha256 == "":
            output_sha = ""
        else:
            output_sha = _sha256(self.output_sha256, "output_sha256")
        object.__setattr__(self, "output_sha256", output_sha)
        object.__setattr__(
            self, "evidence_refs", _ids(self.evidence_refs, "evidence_refs")
        )
        uncertainty = _text(self.uncertainty_state)
        if uncertainty not in UNCERTAINTY_STATES:
            raise RealLoopExecutionError("uncertainty_state is not supported")
        object.__setattr__(self, "uncertainty_state", uncertainty)
        object.__setattr__(self, "failure_detail", _text(self.failure_detail))
        prompt_ref = _text(self.prompt_ref)
        if prompt_ref:
            prompt_ref = _safe_id(prompt_ref, "prompt_ref")
        object.__setattr__(self, "prompt_ref", prompt_ref)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "project_id": self.project_id,
            "role": self.role,
            "task_type": self.task_type,
            "prompt_sha256": self.prompt_sha256,
            "model_route": self.model_route,
            "run_status": self.run_status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "batch_ref": self.batch_ref,
            "output_ref": self.output_ref,
            "output_sha256": self.output_sha256,
            "evidence_refs": list(self.evidence_refs),
            "uncertainty_state": self.uncertainty_state,
            "failure_detail": self.failure_detail,
            "prompt_ref": self.prompt_ref,
        }


@dataclass(frozen=True)
class RealLoopExecutionIssue:
    code: RealLoopExecutionIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise RealLoopExecutionError(
                "execution issue subject and detail are required"
            )
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class RealLoopExecutionReport:
    """Structural execution result; never a medical or release decision."""

    status: str
    execution_evidence_complete: bool
    scenario_count: int
    passed_count: int
    failed_count: int
    blocked_count: int
    issues: tuple[RealLoopExecutionIssue, ...]
    readiness_report_sha256: str = ""
    generalization_evidence_sha256: str = ""
    semantics_binding_sha256: str = ""
    medical_confirmation_permitted: bool = False
    runtime_write_permitted: bool = False
    schema_version: str = REAL_LOOP_EXECUTION_SCHEMA_VERSION
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != REAL_LOOP_EXECUTION_SCHEMA_VERSION:
            raise RealLoopExecutionError(
                "unsupported execution evidence schema version"
            )
        if self.status not in {"blocked", "accepted_for_medical_review"}:
            raise RealLoopExecutionError("invalid execution evidence status")
        for name in (
            "execution_evidence_complete",
            "medical_confirmation_permitted",
            "runtime_write_permitted",
        ):
            if not isinstance(getattr(self, name), bool):
                raise RealLoopExecutionError(f"{name} must be a strict boolean")
        if self.medical_confirmation_permitted or self.runtime_write_permitted:
            raise RealLoopExecutionError("execution evidence cannot grant authority")
        for field_name in (
            "readiness_report_sha256",
            "generalization_evidence_sha256",
            "semantics_binding_sha256",
        ):
            raw_value = getattr(self, field_name)
            if raw_value is None or raw_value == "":
                value = ""
            elif not _is_canonical_sha256(raw_value):
                raise RealLoopExecutionError(
                    f"{field_name} must be a lowercase SHA-256"
                )
            else:
                value = raw_value
            object.__setattr__(self, field_name, value)
        if self.execution_evidence_complete and (
            not self.readiness_report_sha256
            or not self.generalization_evidence_sha256
            or not self.semantics_binding_sha256
        ):
            raise RealLoopExecutionError(
                "complete execution evidence requires readiness and generalization hashes plus a semantics binding hash"
            )
        issues = tuple(self.issues)
        expected_complete = not issues and self.status == "accepted_for_medical_review"
        if self.execution_evidence_complete != expected_complete:
            raise RealLoopExecutionError(
                "execution_evidence_complete does not match issues"
            )
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "execution_evidence_complete": self.execution_evidence_complete,
            "scenario_count": self.scenario_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "blocked_count": self.blocked_count,
            "readiness_report_sha256": self.readiness_report_sha256,
            "generalization_evidence_sha256": self.generalization_evidence_sha256,
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


def _route_is_valid_at(route: str, timestamp: datetime) -> bool:
    local = timestamp.astimezone(_SHANGHAI)
    minutes = local.hour * 60 + local.minute
    if route == "pi/opencode-go/deepseek-v4-flash":
        return 7 * 60 + 30 <= minutes < 22 * 60
    if route == "pi/alibaba/qwen3.8-max-preview":
        return minutes >= 22 * 60 or minutes < 7 * 60 + 30
    return False


def assess_real_loop_execution(
    readiness: RealLoopReadinessReport,
    scenarios: Iterable[RealLoopScenario],
    evidence: Iterable[RealLoopScenarioEvidence],
) -> RealLoopExecutionReport:
    """Validate completed scenario evidence without executing or approving it."""

    scenario_rows = tuple(scenarios)
    evidence_rows = tuple(evidence)
    issues: list[RealLoopExecutionIssue] = []
    raw_readiness_hash = getattr(readiness, "report_sha256", "")
    readiness_hash = raw_readiness_hash if isinstance(raw_readiness_hash, str) else ""
    if not _is_canonical_sha256(raw_readiness_hash):
        issues.append(
            RealLoopExecutionIssue(
                RealLoopExecutionIssueCode.READINESS_REPORT_HASH_INVALID,
                "readiness.report_sha256",
                "execution evidence requires the lowercase SHA-256 of the exact readiness report",
            )
        )
        readiness_hash = ""
    raw_generalization_hash = getattr(
        readiness, "generalization_evidence_sha256", ""
    )
    generalization_hash = (
        raw_generalization_hash
        if isinstance(raw_generalization_hash, str)
        else ""
    )
    if not _is_canonical_sha256(raw_generalization_hash):
        issues.append(
            RealLoopExecutionIssue(
                RealLoopExecutionIssueCode.GENERALIZATION_EVIDENCE_HASH_INVALID,
                "readiness.generalization_evidence_sha256",
                "execution evidence requires the upstream generalization profile snapshot SHA-256",
            )
        )
        generalization_hash = ""
    raw_semantics_binding_hash = getattr(
        readiness, "semantics_binding_sha256", ""
    )
    semantics_binding_hash = (
        raw_semantics_binding_hash
        if isinstance(raw_semantics_binding_hash, str)
        else ""
    )
    if not _is_canonical_sha256(raw_semantics_binding_hash):
        issues.append(
            RealLoopExecutionIssue(
                RealLoopExecutionIssueCode.SEMANTICS_BINDING_HASH_INVALID,
                "readiness.semantics_binding_sha256",
                "execution evidence requires the upstream identity-bound semantics snapshot SHA-256",
            )
        )
        semantics_binding_hash = ""
    if not readiness.execution_ready:
        issues.append(
            RealLoopExecutionIssue(
                RealLoopExecutionIssueCode.READINESS_NOT_READY,
                "readiness",
                "the controlled LOOP cannot be accepted while its preflight report is blocked",
            )
        )

    expected: dict[str, RealLoopScenario] = {}
    for scenario in scenario_rows:
        if scenario.scenario_id in expected:
            issues.append(
                RealLoopExecutionIssue(
                    RealLoopExecutionIssueCode.EVIDENCE_SET_MISMATCH,
                    scenario.scenario_id,
                    "the scenario manifest contains a duplicate scenario_id",
                )
            )
        expected[scenario.scenario_id] = scenario

    observed: dict[str, RealLoopScenarioEvidence] = {}
    for row in evidence_rows:
        if row.scenario_id in observed:
            issues.append(
                RealLoopExecutionIssue(
                    RealLoopExecutionIssueCode.EVIDENCE_DUPLICATE,
                    row.scenario_id,
                    "one execution evidence row is required per scenario",
                )
            )
            continue
        observed[row.scenario_id] = row

    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    for scenario_id in missing:
        issues.append(
            RealLoopExecutionIssue(
                RealLoopExecutionIssueCode.EVIDENCE_SET_MISMATCH,
                scenario_id,
                "completed LOOP evidence is missing for this planned scenario",
            )
        )
    for scenario_id in extra:
        issues.append(
            RealLoopExecutionIssue(
                RealLoopExecutionIssueCode.EVIDENCE_SET_MISMATCH,
                scenario_id,
                "execution evidence references a scenario outside the planned manifest",
            )
        )

    for scenario_id in sorted(set(expected) & set(observed)):
        scenario = expected[scenario_id]
        row = observed[scenario_id]
        identity = (
            row.project_id == scenario.project_id
            and row.role == scenario.role
            and row.task_type == scenario.task_type
            and row.prompt_sha256 == scenario.prompt_sha256
            and row.model_route == scenario.model_route
            and row.prompt_ref == scenario.prompt_ref
        )
        if not identity:
            issues.append(
                RealLoopExecutionIssue(
                    RealLoopExecutionIssueCode.SCENARIO_IDENTITY_MISMATCH,
                    scenario_id,
                    "project, role, task, prompt reference, prompt hash and model route must match the planned scenario",
                )
            )
        allowed_batch_refs = {
            project_id: set(refs)
            for project_id, refs in readiness.batch_refs_by_project
        }
        if row.batch_ref not in allowed_batch_refs.get(row.project_id, set()):
            issues.append(
                RealLoopExecutionIssue(
                    RealLoopExecutionIssueCode.BATCH_REFERENCE_MISMATCH,
                    scenario_id,
                    "execution evidence batch_ref must belong to the readiness batch manifest for its project",
                )
            )
        if scenario.run_status not in {"not_run", row.run_status}:
            issues.append(
                RealLoopExecutionIssue(
                    RealLoopExecutionIssueCode.SCENARIO_STATUS_MISMATCH,
                    scenario_id,
                    "execution evidence status does not match the scenario manifest status",
                )
            )
        if row.run_status != "passed":
            issues.append(
                RealLoopExecutionIssue(
                    RealLoopExecutionIssueCode.EXECUTION_NOT_PASSED,
                    scenario_id,
                    "failed or blocked scenarios require repair and a complete rerun before review",
                )
            )
            if not row.failure_detail:
                issues.append(
                    RealLoopExecutionIssue(
                        RealLoopExecutionIssueCode.FAILURE_DETAIL_MISSING,
                        scenario_id,
                        "failed or blocked execution must preserve a failure detail",
                    )
                )
        if row.run_status == "passed" and not row.output_ref:
            issues.append(
                RealLoopExecutionIssue(
                    RealLoopExecutionIssueCode.OUTPUT_REFERENCE_MISSING,
                    scenario_id,
                    "a passed result requires an opaque output artifact reference",
                )
            )
        if row.run_status == "passed" and not row.output_sha256:
            issues.append(
                RealLoopExecutionIssue(
                    RealLoopExecutionIssueCode.OUTPUT_HASH_INVALID,
                    scenario_id,
                    "a passed result requires a lowercase SHA-256 for its output artifact",
                )
            )
        if not row.evidence_refs:
            issues.append(
                RealLoopExecutionIssue(
                    RealLoopExecutionIssueCode.TRACEABILITY_MISSING,
                    scenario_id,
                    "each result requires at least one source/evidence reference",
                )
            )
        if row.uncertainty_state not in UNCERTAINTY_STATES:
            issues.append(
                RealLoopExecutionIssue(
                    RealLoopExecutionIssueCode.UNCERTAINTY_INVALID,
                    scenario_id,
                    "uncertainty must be explicit; an omitted value cannot mean no risk",
                )
            )
        started = _parse_timestamp(row.started_at)
        ended = _parse_timestamp(row.ended_at)
        if started is None or ended is None or ended <= started:
            issues.append(
                RealLoopExecutionIssue(
                    RealLoopExecutionIssueCode.TIMESTAMP_INVALID,
                    scenario_id,
                    "started_at and ended_at require timezone-aware ISO timestamps with ended_at after started_at",
                )
            )
        elif not (
            _route_is_valid_at(row.model_route, started)
            and _route_is_valid_at(row.model_route, ended)
        ):
            issues.append(
                RealLoopExecutionIssue(
                    RealLoopExecutionIssueCode.TIME_WINDOW_INVALID,
                    scenario_id,
                    "the selected model route was not run inside its approved Beijing-time window",
                )
            )

    passed_count = sum(row.run_status == "passed" for row in evidence_rows)
    failed_count = sum(row.run_status == "failed" for row in evidence_rows)
    blocked_count = sum(row.run_status == "blocked" for row in evidence_rows)
    ordered_issues = tuple(
        sorted(
            issues, key=lambda issue: (issue.subject, issue.code.value, issue.detail)
        )
    )
    complete = not ordered_issues and len(evidence_rows) == len(scenario_rows)
    return RealLoopExecutionReport(
        status="accepted_for_medical_review" if complete else "blocked",
        execution_evidence_complete=complete,
        scenario_count=len(scenario_rows),
        passed_count=passed_count,
        failed_count=failed_count,
        blocked_count=blocked_count,
        issues=ordered_issues,
        readiness_report_sha256=readiness_hash,
        generalization_evidence_sha256=generalization_hash,
        semantics_binding_sha256=semantics_binding_hash,
    )


__all__ = [
    "EXECUTION_STATUSES",
    "REAL_LOOP_EXECUTION_SCHEMA_VERSION",
    "RealLoopExecutionError",
    "RealLoopExecutionIssue",
    "RealLoopExecutionIssueCode",
    "RealLoopExecutionReport",
    "RealLoopScenarioEvidence",
    "UNCERTAINTY_STATES",
    "assess_real_loop_execution",
]
