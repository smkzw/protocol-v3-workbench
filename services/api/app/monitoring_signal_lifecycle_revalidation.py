"""Read-only revalidation of persisted signal-lifecycle evidence.

The signal lifecycle contract is intentionally offline.  This boundary protects
the evidence envelope itself: it reconstructs the typed signal/review/decision/
action/recheck chain, reruns the canonical lifecycle validator, and optionally
reopens the JSON artifact through a byte/SHA check.  A fresh envelope only means
that the evidence was replayed without drift; it never means that a signal is
medically confirmed or that an action may be executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .monitoring_signal_lifecycle_contract import (
    MONITORING_SIGNAL_LIFECYCLE_SCHEMA_VERSION,
    MonitoringAction,
    MonitoringDecision,
    MonitoringRecheck,
    MonitoringReview,
    MonitoringSignal,
    assess_monitoring_signal_lifecycle,
)


MONITORING_SIGNAL_LIFECYCLE_REVALIDATION_SCHEMA_VERSION = (
    "medical_monitoring_signal_lifecycle_revalidation_v1"
)
ARTIFACT_SCHEMA_VERSION = "medical-monitoring-signal-lifecycle-evidence-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITY_EXPECTATIONS = {
    "diagnostic_only": True,
    "provider_permitted": False,
    "runtime_write_permitted": False,
    "medical_authority_granted": False,
    "authority_granted": False,
    "release_ready": False,
}
_SIGNAL_FIELDS = {
    "signal_id",
    "project_id",
    "scope",
    "scope_id",
    "source_batch_id",
    "source_revision",
    "evidence_ids",
    "origin",
    "risk_level",
    "trend",
    "rule_or_model_ref",
    "prompt_revision",
    "generated_at",
    "baseline_batch_id",
    "auto_action_forbidden",
}
_REVIEW_FIELDS = {
    "review_id",
    "signal_id",
    "project_id",
    "source_revision",
    "outcome",
    "reason",
    "reviewer_id",
    "reviewed_at",
    "evidence_ids",
}
_DECISION_FIELDS = {
    "decision_id",
    "review_id",
    "signal_id",
    "project_id",
    "source_revision",
    "decision",
    "reason",
    "decided_by",
    "decided_at",
    "evidence_ids",
}
_ACTION_FIELDS = {
    "action_id",
    "decision_id",
    "signal_id",
    "project_id",
    "source_revision",
    "kind",
    "status",
    "proposed_by",
    "reason",
    "target_scope",
    "target_id",
    "proposed_at",
    "confirmed_by",
    "confirmed_at",
    "auto_executed",
}
_RECHECK_FIELDS = {
    "recheck_id",
    "action_id",
    "signal_id",
    "project_id",
    "source_batch_id",
    "source_revision",
    "result",
    "reason",
    "reviewer_id",
    "rechecked_at",
    "evidence_ids",
}


class MonitoringSignalLifecycleRevalidationError(ValueError):
    """Raised when a revalidation request cannot be evaluated safely."""


class MonitoringSignalLifecycleRevalidationIssueCode(str, Enum):
    PAYLOAD_SHAPE_INVALID = "payload_shape_invalid"
    ARTIFACT_SCHEMA_INVALID = "artifact_schema_invalid"
    AUTHORITY_FLAG_MISSING = "authority_flag_missing"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"
    RECORD_SHAPE_INVALID = "record_shape_invalid"
    SIGNAL_RECONSTRUCTION_FAILED = "signal_reconstruction_failed"
    REVIEW_RECONSTRUCTION_FAILED = "review_reconstruction_failed"
    DECISION_RECONSTRUCTION_FAILED = "decision_reconstruction_failed"
    ACTION_RECONSTRUCTION_FAILED = "action_reconstruction_failed"
    RECHECK_RECONSTRUCTION_FAILED = "recheck_reconstruction_failed"
    LIFECYCLE_REPORT_MISSING = "lifecycle_report_missing"
    LIFECYCLE_REPORT_MISMATCH = "lifecycle_report_mismatch"
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
        raise MonitoringSignalLifecycleRevalidationError(
            "signal lifecycle evidence must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _issue(
    issues: list["MonitoringSignalLifecycleRevalidationIssue"],
    code: MonitoringSignalLifecycleRevalidationIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(
        MonitoringSignalLifecycleRevalidationIssue(
            code=code,
            subject=_text(subject) or "payload",
            detail=_text(detail) or "invalid evidence",
        )
    )


@dataclass(frozen=True)
class MonitoringSignalLifecycleRevalidationIssue:
    code: MonitoringSignalLifecycleRevalidationIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise MonitoringSignalLifecycleRevalidationError(
                "revalidation issue subject and detail are required"
            )
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class MonitoringSignalLifecycleRevalidationReport:
    """Evidence-freshness result; all authority flags remain false."""

    status: str
    evidence_fresh: bool
    payload_valid: bool
    lifecycle_report_matches: bool
    file_checked: bool
    file_fresh: bool
    lifecycle_status: str
    lifecycle_closed: bool
    signal_id: str
    project_id: str
    issues: tuple[MonitoringSignalLifecycleRevalidationIssue, ...]
    schema_version: str = MONITORING_SIGNAL_LIFECYCLE_REVALIDATION_SCHEMA_VERSION
    read_only: bool = True
    authority_granted: bool = False
    release_ready: bool = False
    provider_permitted: bool = False
    runtime_write_permitted: bool = False
    medical_authority_granted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version
            != MONITORING_SIGNAL_LIFECYCLE_REVALIDATION_SCHEMA_VERSION
        ):
            raise MonitoringSignalLifecycleRevalidationError(
                "unsupported signal lifecycle revalidation schema"
            )
        if self.status not in {"fresh", "blocked"}:
            raise MonitoringSignalLifecycleRevalidationError(
                "invalid revalidation status"
            )
        if self.read_only is not True:
            raise MonitoringSignalLifecycleRevalidationError(
                "signal lifecycle revalidation must remain read-only"
            )
        for name in (
            "authority_granted",
            "release_ready",
            "provider_permitted",
            "runtime_write_permitted",
            "medical_authority_granted",
        ):
            if getattr(self, name) is not False:
                raise MonitoringSignalLifecycleRevalidationError(
                    f"{name} must remain false"
                )
        for name in (
            "evidence_fresh",
            "payload_valid",
            "lifecycle_report_matches",
            "file_checked",
            "file_fresh",
            "lifecycle_closed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise MonitoringSignalLifecycleRevalidationError(
                    f"{name} must be boolean"
                )
        if self.lifecycle_status not in {"valid", "blocked", "unknown"}:
            raise MonitoringSignalLifecycleRevalidationError(
                "lifecycle_status must be valid, blocked or unknown"
            )
        if self.file_fresh and not self.file_checked:
            raise MonitoringSignalLifecycleRevalidationError(
                "file_fresh cannot be true when file_checked is false"
            )
        issues = tuple(self.issues)
        if any(
            not isinstance(item, MonitoringSignalLifecycleRevalidationIssue)
            for item in issues
        ):
            raise MonitoringSignalLifecycleRevalidationError(
                "issues contain an invalid value"
            )
        expected_fresh = (
            not issues
            and self.payload_valid
            and self.lifecycle_report_matches
            and (not self.file_checked or self.file_fresh)
        )
        if (
            self.evidence_fresh != expected_fresh
            or (self.status == "fresh") != expected_fresh
        ):
            raise MonitoringSignalLifecycleRevalidationError(
                "revalidation status does not match evidence state"
            )
        object.__setattr__(self, "signal_id", _text(self.signal_id))
        object.__setattr__(self, "project_id", _text(self.project_id))
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "evidence_fresh": self.evidence_fresh,
            "payload_valid": self.payload_valid,
            "lifecycle_report_matches": self.lifecycle_report_matches,
            "file_checked": self.file_checked,
            "file_fresh": self.file_fresh,
            "lifecycle_status": self.lifecycle_status,
            "lifecycle_closed": self.lifecycle_closed,
            "signal_id": self.signal_id,
            "project_id": self.project_id,
            "issues": [item.to_dict() for item in self.issues],
            "read_only": self.read_only,
            "authority_granted": self.authority_granted,
            "release_ready": self.release_ready,
            "provider_permitted": self.provider_permitted,
            "runtime_write_permitted": self.runtime_write_permitted,
            "medical_authority_granted": self.medical_authority_granted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
        }


def _datetime(value: Any, field_name: str) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MonitoringSignalLifecycleRevalidationError(
            f"{field_name} must be ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MonitoringSignalLifecycleRevalidationError(
            f"{field_name} must include a timezone"
        )
    return parsed


def _record(
    value: Any,
    *,
    label: str,
    fields: set[str],
    issues: list[MonitoringSignalLifecycleRevalidationIssue],
) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.RECORD_SHAPE_INVALID,
            label,
            "record must be an object",
        )
        return None
    unknown = sorted(set(value) - fields)
    if unknown:
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.RECORD_SHAPE_INVALID,
            label,
            f"unsupported fields: {unknown}",
        )
        return None
    return value


def _list(
    value: Any,
    *,
    label: str,
    issues: list[MonitoringSignalLifecycleRevalidationIssue],
) -> tuple[Any, ...] | None:
    if not isinstance(value, list):
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            label,
            "must be an array",
        )
        return None
    return tuple(value)


def _parse_signal(
    value: Any,
    issues: list[MonitoringSignalLifecycleRevalidationIssue],
) -> MonitoringSignal | None:
    item = _record(value, label="signal", fields=_SIGNAL_FIELDS, issues=issues)
    if item is None:
        return None
    try:
        return MonitoringSignal(
            signal_id=item.get("signal_id", ""),
            project_id=item.get("project_id", ""),
            scope=item.get("scope", ""),
            scope_id=item.get("scope_id", ""),
            source_batch_id=item.get("source_batch_id", ""),
            source_revision=item.get("source_revision", ""),
            evidence_ids=tuple(item.get("evidence_ids") or ()),
            origin=item.get("origin", ""),
            risk_level=item.get("risk_level", ""),
            trend=item.get("trend", ""),
            rule_or_model_ref=item.get("rule_or_model_ref", ""),
            prompt_revision=item.get("prompt_revision", ""),
            generated_at=_datetime(item.get("generated_at"), "signal.generated_at"),  # type: ignore[arg-type]
            baseline_batch_id=item.get("baseline_batch_id", ""),
            auto_action_forbidden=item.get("auto_action_forbidden", False),
        )
    except (TypeError, ValueError, MonitoringSignalLifecycleRevalidationError) as exc:
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.SIGNAL_RECONSTRUCTION_FAILED,
            "signal",
            str(exc),
        )
        return None


def _parse_reviews(
    values: tuple[Any, ...],
    issues: list[MonitoringSignalLifecycleRevalidationIssue],
) -> tuple[MonitoringReview, ...] | None:
    result: list[MonitoringReview] = []
    for index, value in enumerate(values):
        item = _record(
            value,
            label=f"reviews[{index}]",
            fields=_REVIEW_FIELDS,
            issues=issues,
        )
        if item is None:
            continue
        try:
            result.append(
                MonitoringReview(
                    review_id=item.get("review_id", ""),
                    signal_id=item.get("signal_id", ""),
                    project_id=item.get("project_id", ""),
                    source_revision=item.get("source_revision", ""),
                    outcome=item.get("outcome", ""),
                    reason=item.get("reason", ""),
                    reviewer_id=item.get("reviewer_id", ""),
                    reviewed_at=_datetime(
                        item.get("reviewed_at"), f"reviews[{index}].reviewed_at"
                    ),
                    evidence_ids=tuple(item.get("evidence_ids") or ()),
                )
            )
        except (
            TypeError,
            ValueError,
            MonitoringSignalLifecycleRevalidationError,
        ) as exc:
            _issue(
                issues,
                MonitoringSignalLifecycleRevalidationIssueCode.REVIEW_RECONSTRUCTION_FAILED,
                f"reviews[{index}]",
                str(exc),
            )
    return tuple(result) if len(result) == len(values) else None


def _parse_decisions(
    values: tuple[Any, ...],
    issues: list[MonitoringSignalLifecycleRevalidationIssue],
) -> tuple[MonitoringDecision, ...] | None:
    result: list[MonitoringDecision] = []
    for index, value in enumerate(values):
        item = _record(
            value,
            label=f"decisions[{index}]",
            fields=_DECISION_FIELDS,
            issues=issues,
        )
        if item is None:
            continue
        try:
            result.append(
                MonitoringDecision(
                    decision_id=item.get("decision_id", ""),
                    review_id=item.get("review_id", ""),
                    signal_id=item.get("signal_id", ""),
                    project_id=item.get("project_id", ""),
                    source_revision=item.get("source_revision", ""),
                    decision=item.get("decision", ""),
                    reason=item.get("reason", ""),
                    decided_by=item.get("decided_by", ""),
                    decided_at=_datetime(
                        item.get("decided_at"), f"decisions[{index}].decided_at"
                    ),  # type: ignore[arg-type]
                    evidence_ids=tuple(item.get("evidence_ids") or ()),
                )
            )
        except (
            TypeError,
            ValueError,
            MonitoringSignalLifecycleRevalidationError,
        ) as exc:
            _issue(
                issues,
                MonitoringSignalLifecycleRevalidationIssueCode.DECISION_RECONSTRUCTION_FAILED,
                f"decisions[{index}]",
                str(exc),
            )
    return tuple(result) if len(result) == len(values) else None


def _parse_actions(
    values: tuple[Any, ...],
    issues: list[MonitoringSignalLifecycleRevalidationIssue],
) -> tuple[MonitoringAction, ...] | None:
    result: list[MonitoringAction] = []
    for index, value in enumerate(values):
        item = _record(
            value,
            label=f"actions[{index}]",
            fields=_ACTION_FIELDS,
            issues=issues,
        )
        if item is None:
            continue
        try:
            result.append(
                MonitoringAction(
                    action_id=item.get("action_id", ""),
                    decision_id=item.get("decision_id", ""),
                    signal_id=item.get("signal_id", ""),
                    project_id=item.get("project_id", ""),
                    source_revision=item.get("source_revision", ""),
                    kind=item.get("kind", ""),
                    status=item.get("status", ""),
                    proposed_by=item.get("proposed_by", ""),
                    reason=item.get("reason", ""),
                    target_scope=item.get("target_scope", ""),
                    target_id=item.get("target_id", ""),
                    proposed_at=_datetime(
                        item.get("proposed_at"), f"actions[{index}].proposed_at"
                    ),  # type: ignore[arg-type]
                    confirmed_by=item.get("confirmed_by", ""),
                    confirmed_at=_datetime(
                        item.get("confirmed_at"), f"actions[{index}].confirmed_at"
                    ),
                    auto_executed=item.get("auto_executed", False),
                )
            )
        except (
            TypeError,
            ValueError,
            MonitoringSignalLifecycleRevalidationError,
        ) as exc:
            _issue(
                issues,
                MonitoringSignalLifecycleRevalidationIssueCode.ACTION_RECONSTRUCTION_FAILED,
                f"actions[{index}]",
                str(exc),
            )
    return tuple(result) if len(result) == len(values) else None


def _parse_rechecks(
    values: tuple[Any, ...],
    issues: list[MonitoringSignalLifecycleRevalidationIssue],
) -> tuple[MonitoringRecheck, ...] | None:
    result: list[MonitoringRecheck] = []
    for index, value in enumerate(values):
        item = _record(
            value,
            label=f"rechecks[{index}]",
            fields=_RECHECK_FIELDS,
            issues=issues,
        )
        if item is None:
            continue
        try:
            result.append(
                MonitoringRecheck(
                    recheck_id=item.get("recheck_id", ""),
                    action_id=item.get("action_id", ""),
                    signal_id=item.get("signal_id", ""),
                    project_id=item.get("project_id", ""),
                    source_batch_id=item.get("source_batch_id", ""),
                    source_revision=item.get("source_revision", ""),
                    result=item.get("result", ""),
                    reason=item.get("reason", ""),
                    reviewer_id=item.get("reviewer_id", ""),
                    rechecked_at=_datetime(
                        item.get("rechecked_at"), f"rechecks[{index}].rechecked_at"
                    ),  # type: ignore[arg-type]
                    evidence_ids=tuple(item.get("evidence_ids") or ()),
                )
            )
        except (
            TypeError,
            ValueError,
            MonitoringSignalLifecycleRevalidationError,
        ) as exc:
            _issue(
                issues,
                MonitoringSignalLifecycleRevalidationIssueCode.RECHECK_RECONSTRUCTION_FAILED,
                f"rechecks[{index}]",
                str(exc),
            )
    return tuple(result) if len(result) == len(values) else None


def _authority_ok(
    value: Any,
    issues: list[MonitoringSignalLifecycleRevalidationIssue],
) -> bool:
    if not isinstance(value, Mapping):
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "authority",
            "authority must be an object",
        )
        return False
    ok = True
    for name, expected in _AUTHORITY_EXPECTATIONS.items():
        if name not in value:
            ok = False
            _issue(
                issues,
                MonitoringSignalLifecycleRevalidationIssueCode.AUTHORITY_FLAG_MISSING,
                f"authority.{name}",
                "required read-only boundary flag is missing",
            )
        elif value[name] is not expected:
            ok = False
            _issue(
                issues,
                MonitoringSignalLifecycleRevalidationIssueCode.AUTHORITY_FLAG_TRUE,
                f"authority.{name}",
                f"expected {expected!r}, observed {value[name]!r}",
            )
    return ok


def _blocked_report(
    issues: list[MonitoringSignalLifecycleRevalidationIssue],
    *,
    signal_id: str = "",
    project_id: str = "",
    lifecycle_status: str = "unknown",
    lifecycle_closed: bool = False,
    payload_valid: bool = False,
    lifecycle_report_matches: bool = False,
    file_checked: bool = False,
    file_fresh: bool = False,
) -> MonitoringSignalLifecycleRevalidationReport:
    return MonitoringSignalLifecycleRevalidationReport(
        status="blocked",
        evidence_fresh=False,
        payload_valid=payload_valid,
        lifecycle_report_matches=lifecycle_report_matches,
        file_checked=file_checked,
        file_fresh=file_fresh,
        lifecycle_status=lifecycle_status,
        lifecycle_closed=lifecycle_closed,
        signal_id=signal_id,
        project_id=project_id,
        issues=tuple(issues),
    )


def revalidate_signal_lifecycle_payload(
    payload: Mapping[str, Any],
) -> MonitoringSignalLifecycleRevalidationReport:
    """Replay one persisted lifecycle evidence envelope without side effects."""

    issues: list[MonitoringSignalLifecycleRevalidationIssue] = []
    if not isinstance(payload, Mapping):
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "payload",
            "payload must be an object",
        )
        return _blocked_report(issues)
    if payload.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.ARTIFACT_SCHEMA_INVALID,
            "schema_version",
            f"expected {ARTIFACT_SCHEMA_VERSION!r}",
        )
    _authority_ok(payload.get("authority"), issues)
    if (
        payload.get("lifecycle_schema_version")
        != MONITORING_SIGNAL_LIFECYCLE_SCHEMA_VERSION
    ):
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.ARTIFACT_SCHEMA_INVALID,
            "lifecycle_schema_version",
            f"expected {MONITORING_SIGNAL_LIFECYCLE_SCHEMA_VERSION!r}",
        )

    signal = _parse_signal(payload.get("signal"), issues)
    signal_id = (
        signal.signal_id
        if signal is not None
        else _text(
            (payload.get("signal") or {}).get("signal_id")
            if isinstance(payload.get("signal"), Mapping)
            else ""
        )
    )
    project_id = (
        signal.project_id
        if signal is not None
        else _text(
            (payload.get("signal") or {}).get("project_id")
            if isinstance(payload.get("signal"), Mapping)
            else ""
        )
    )
    reviews_raw = _list(payload.get("reviews"), label="reviews", issues=issues)
    decisions_raw = _list(payload.get("decisions"), label="decisions", issues=issues)
    actions_raw = _list(payload.get("actions"), label="actions", issues=issues)
    rechecks_raw = _list(payload.get("rechecks"), label="rechecks", issues=issues)
    reviews = (
        _parse_reviews(reviews_raw or (), issues) if reviews_raw is not None else None
    )
    decisions = (
        _parse_decisions(decisions_raw or (), issues)
        if decisions_raw is not None
        else None
    )
    actions = (
        _parse_actions(actions_raw or (), issues) if actions_raw is not None else None
    )
    rechecks = (
        _parse_rechecks(rechecks_raw or (), issues)
        if rechecks_raw is not None
        else None
    )

    lifecycle_report_matches = False
    lifecycle_status = "unknown"
    lifecycle_closed = False
    if (
        signal is not None
        and reviews is not None
        and decisions is not None
        and actions is not None
        and rechecks is not None
    ):
        lifecycle = assess_monitoring_signal_lifecycle(
            signal,
            reviews=reviews,
            decisions=decisions,
            actions=actions,
            rechecks=rechecks,
        )
        lifecycle_status = lifecycle.status
        lifecycle_closed = lifecycle.closed
        reported = payload.get("report")
        if not isinstance(reported, Mapping):
            _issue(
                issues,
                MonitoringSignalLifecycleRevalidationIssueCode.LIFECYCLE_REPORT_MISSING,
                "report",
                "persisted lifecycle report must be an object",
            )
        else:
            expected = lifecycle.public_dict()
            lifecycle_report_matches = _canonical(reported) == _canonical(expected)
            if not lifecycle_report_matches:
                _issue(
                    issues,
                    MonitoringSignalLifecycleRevalidationIssueCode.LIFECYCLE_REPORT_MISMATCH,
                    "report",
                    "persisted report differs from deterministic lifecycle replay",
                )
    payload_valid = (
        not any(
            issue.code
            in {
                MonitoringSignalLifecycleRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
                MonitoringSignalLifecycleRevalidationIssueCode.ARTIFACT_SCHEMA_INVALID,
                MonitoringSignalLifecycleRevalidationIssueCode.AUTHORITY_FLAG_MISSING,
                MonitoringSignalLifecycleRevalidationIssueCode.AUTHORITY_FLAG_TRUE,
                MonitoringSignalLifecycleRevalidationIssueCode.RECORD_SHAPE_INVALID,
                MonitoringSignalLifecycleRevalidationIssueCode.SIGNAL_RECONSTRUCTION_FAILED,
                MonitoringSignalLifecycleRevalidationIssueCode.REVIEW_RECONSTRUCTION_FAILED,
                MonitoringSignalLifecycleRevalidationIssueCode.DECISION_RECONSTRUCTION_FAILED,
                MonitoringSignalLifecycleRevalidationIssueCode.ACTION_RECONSTRUCTION_FAILED,
                MonitoringSignalLifecycleRevalidationIssueCode.RECHECK_RECONSTRUCTION_FAILED,
                MonitoringSignalLifecycleRevalidationIssueCode.LIFECYCLE_REPORT_MISSING,
            }
            for issue in issues
        )
        and signal is not None
        and reviews is not None
        and decisions is not None
        and actions is not None
        and rechecks is not None
    )
    return MonitoringSignalLifecycleRevalidationReport(
        status="fresh"
        if payload_valid and lifecycle_report_matches and not issues
        else "blocked",
        evidence_fresh=payload_valid and lifecycle_report_matches and not issues,
        payload_valid=payload_valid,
        lifecycle_report_matches=lifecycle_report_matches,
        file_checked=False,
        file_fresh=False,
        lifecycle_status=lifecycle_status,
        lifecycle_closed=lifecycle_closed,
        signal_id=signal_id,
        project_id=project_id,
        issues=tuple(issues),
    )


def revalidate_signal_lifecycle_file(
    artifact_ref: str,
    *,
    expected_bytes: int,
    expected_sha256: str,
    workspace_root: str | Path,
) -> MonitoringSignalLifecycleRevalidationReport:
    """Reopen a workspace-relative artifact and replay its lifecycle payload."""

    issues: list[MonitoringSignalLifecycleRevalidationIssue] = []
    relative = _text(artifact_ref)
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.FILE_PATH_UNSAFE,
            "artifact_ref",
            "artifact path must be relative and cannot contain '..'",
        )
        return _blocked_report(issues, file_checked=True)
    if not _valid_sha(expected_sha256):
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.FILE_SHA256_MISMATCH,
            "expected_sha256",
            "expected_sha256 must be a lowercase SHA-256",
        )
        return _blocked_report(issues, file_checked=True)
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes < 0
    ):
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.FILE_BYTES_MISMATCH,
            "expected_bytes",
            "expected_bytes must be a non-negative integer",
        )
        return _blocked_report(issues, file_checked=True)
    root = Path(workspace_root)
    candidate = root / path
    try:
        resolved_root = root.resolve()
        resolved_candidate = candidate.resolve()
    except OSError as exc:
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.FILE_NOT_REGULAR,
            "artifact_ref",
            str(exc),
        )
        return _blocked_report(issues, file_checked=True)
    if candidate.is_symlink():
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.FILE_SYMLINK_UNSUPPORTED,
            relative,
            "symlink artifacts are not accepted",
        )
        return _blocked_report(issues, file_checked=True)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.FILE_PATH_UNSAFE,
            relative,
            "artifact resolves outside workspace_root",
        )
        return _blocked_report(issues, file_checked=True)
    if not candidate.exists():
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.FILE_MISSING,
            relative,
            "artifact does not exist",
        )
        return _blocked_report(issues, file_checked=True)
    if not candidate.is_file():
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.FILE_NOT_REGULAR,
            relative,
            "artifact is not a regular file",
        )
        return _blocked_report(issues, file_checked=True)
    raw = candidate.read_bytes()
    if len(raw) != expected_bytes:
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.FILE_BYTES_MISMATCH,
            relative,
            f"expected={expected_bytes}, observed={len(raw)}",
        )
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    if observed_sha256 != expected_sha256:
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.FILE_SHA256_MISMATCH,
            relative,
            f"expected={expected_sha256}, observed={observed_sha256}",
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _issue(
            issues,
            MonitoringSignalLifecycleRevalidationIssueCode.FILE_JSON_INVALID,
            relative,
            str(exc),
        )
        return _blocked_report(issues, file_checked=True)
    replay = revalidate_signal_lifecycle_payload(payload)
    if issues:
        return MonitoringSignalLifecycleRevalidationReport(
            status="blocked",
            evidence_fresh=False,
            payload_valid=replay.payload_valid,
            lifecycle_report_matches=replay.lifecycle_report_matches,
            file_checked=True,
            file_fresh=False,
            lifecycle_status=replay.lifecycle_status,
            lifecycle_closed=replay.lifecycle_closed,
            signal_id=replay.signal_id,
            project_id=replay.project_id,
            issues=tuple((*replay.issues, *issues)),
        )
    return MonitoringSignalLifecycleRevalidationReport(
        status=replay.status,
        evidence_fresh=replay.evidence_fresh,
        payload_valid=replay.payload_valid,
        lifecycle_report_matches=replay.lifecycle_report_matches,
        file_checked=True,
        file_fresh=True,
        lifecycle_status=replay.lifecycle_status,
        lifecycle_closed=replay.lifecycle_closed,
        signal_id=replay.signal_id,
        project_id=replay.project_id,
        issues=replay.issues,
    )


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "MONITORING_SIGNAL_LIFECYCLE_REVALIDATION_SCHEMA_VERSION",
    "MonitoringSignalLifecycleRevalidationError",
    "MonitoringSignalLifecycleRevalidationIssue",
    "MonitoringSignalLifecycleRevalidationIssueCode",
    "MonitoringSignalLifecycleRevalidationReport",
    "revalidate_signal_lifecycle_file",
    "revalidate_signal_lifecycle_payload",
]
