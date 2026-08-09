"""Offline signal-to-action lifecycle contract for medical monitoring.

This module turns a detected risk signal into a typed, reviewable chain:
signal -> review -> human decision -> action -> recheck.  It is deliberately
separate from persistence, provider dispatch, source registration and the
runtime audit store.  The report is diagnostic-only and can never grant a
medical, provider or write authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable


MONITORING_SIGNAL_LIFECYCLE_SCHEMA_VERSION = "monitoring_signal_lifecycle_v1"


class MonitoringSignalLifecycleError(ValueError):
    """Malformed or unsafe lifecycle input."""


class MonitoringSignalScope(str, Enum):
    TRIAL = "trial"
    SITE = "site"
    SUBJECT = "subject"


class MonitoringSignalOrigin(str, Enum):
    DETERMINISTIC = "deterministic"
    STATISTICAL = "statistical"
    AI = "ai"


class MonitoringRiskLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class MonitoringSignalTrend(str, Enum):
    NEW = "new"
    INCREASED = "increased"
    DECREASED = "decreased"
    STABLE = "stable"
    UNRESOLVED = "unresolved"


class MonitoringReviewOutcome(str, Enum):
    PENDING = "pending"
    ACCEPTED_FOR_DECISION = "accepted_for_decision"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    SUPERSEDED = "superseded"


class MonitoringDecisionType(str, Enum):
    CONFIRM_RISK = "confirm_risk"
    REJECT_SIGNAL = "reject_signal"
    NO_ACTION = "no_action"
    ESCALATE = "escalate"


class MonitoringActionKind(str, Enum):
    QUERY_CANDIDATE = "query_candidate"
    TARGETED_REVIEW = "targeted_review"
    SITE_FOLLOW_UP = "site_follow_up"
    MEDICAL_ESCALATION = "medical_escalation"
    MONITOR_NEXT_BATCH = "monitor_next_batch"
    NO_ACTION = "no_action"


class MonitoringActionStatus(str, Enum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class MonitoringRecheckResult(str, Enum):
    RESOLVED = "resolved"
    PERSISTS = "persists"
    CHANGED = "changed"
    INCONCLUSIVE = "inconclusive"


def _required(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MonitoringSignalLifecycleError(f"{field_name} is required")
    return text


def _enum(value: Any, enum_type: type[Enum], field_name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise MonitoringSignalLifecycleError(
            f"{field_name} contains an unsupported value: {value}"
        ) from exc


def _ids(
    values: Iterable[Any], field_name: str, *, required: bool = True
) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    cleaned = tuple(_required(value, f"{field_name} item") for value in values or ())
    if required and not cleaned:
        raise MonitoringSignalLifecycleError(f"{field_name} cannot be empty")
    if len(set(cleaned)) != len(cleaned):
        raise MonitoringSignalLifecycleError(f"{field_name} must be unique")
    return cleaned


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MonitoringSignalLifecycleError(f"{field_name} must include a timezone")
    return value.astimezone(timezone.utc)


def _bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise MonitoringSignalLifecycleError(f"{field_name} must be a boolean")
    return value


@dataclass(frozen=True)
class MonitoringSignal:
    """One evidence-bound signal; no automatic medical action is permitted."""

    signal_id: str
    project_id: str
    scope: MonitoringSignalScope
    scope_id: str
    source_batch_id: str
    source_revision: str
    evidence_ids: tuple[str, ...]
    origin: MonitoringSignalOrigin
    risk_level: MonitoringRiskLevel
    trend: MonitoringSignalTrend
    rule_or_model_ref: str
    prompt_revision: str
    generated_at: datetime
    baseline_batch_id: str = ""
    auto_action_forbidden: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "signal_id", _required(self.signal_id, "signal_id"))
        object.__setattr__(self, "project_id", _required(self.project_id, "project_id"))
        object.__setattr__(
            self, "scope", _enum(self.scope, MonitoringSignalScope, "scope")
        )
        object.__setattr__(self, "scope_id", _required(self.scope_id, "scope_id"))
        object.__setattr__(
            self, "source_batch_id", _required(self.source_batch_id, "source_batch_id")
        )
        object.__setattr__(
            self, "source_revision", _required(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self, "evidence_ids", _ids(self.evidence_ids, "evidence_ids")
        )
        object.__setattr__(
            self, "origin", _enum(self.origin, MonitoringSignalOrigin, "origin")
        )
        object.__setattr__(
            self,
            "risk_level",
            _enum(self.risk_level, MonitoringRiskLevel, "risk_level"),
        )
        object.__setattr__(
            self, "trend", _enum(self.trend, MonitoringSignalTrend, "trend")
        )
        object.__setattr__(
            self,
            "rule_or_model_ref",
            _required(self.rule_or_model_ref, "rule_or_model_ref"),
        )
        prompt_revision = str(self.prompt_revision or "").strip()
        if self.origin == MonitoringSignalOrigin.AI and not prompt_revision:
            raise MonitoringSignalLifecycleError("AI signals require prompt_revision")
        object.__setattr__(self, "prompt_revision", prompt_revision)
        object.__setattr__(
            self, "generated_at", _utc(self.generated_at, "generated_at")
        )
        baseline = str(self.baseline_batch_id or "").strip()
        if baseline and baseline == self.source_batch_id:
            raise MonitoringSignalLifecycleError(
                "baseline_batch_id must differ from source_batch_id"
            )
        object.__setattr__(self, "baseline_batch_id", baseline)
        if not _bool(self.auto_action_forbidden, "auto_action_forbidden"):
            raise MonitoringSignalLifecycleError(
                "auto_action_forbidden must remain true"
            )


@dataclass(frozen=True)
class MonitoringReview:
    """A review observation; acceptance for decision requires a human."""

    review_id: str
    signal_id: str
    project_id: str
    source_revision: str
    outcome: MonitoringReviewOutcome
    reason: str
    reviewer_id: str = ""
    reviewed_at: datetime | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "review_id", _required(self.review_id, "review_id"))
        object.__setattr__(self, "signal_id", _required(self.signal_id, "signal_id"))
        object.__setattr__(self, "project_id", _required(self.project_id, "project_id"))
        object.__setattr__(
            self, "source_revision", _required(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self, "outcome", _enum(self.outcome, MonitoringReviewOutcome, "outcome")
        )
        object.__setattr__(self, "reason", _required(self.reason, "reason"))
        reviewer = str(self.reviewer_id or "").strip()
        reviewed_at = self.reviewed_at
        if self.outcome == MonitoringReviewOutcome.PENDING:
            if reviewer or reviewed_at is not None:
                raise MonitoringSignalLifecycleError(
                    "pending review cannot carry a human review timestamp"
                )
        else:
            reviewer = _required(reviewer, "reviewer_id")
            if reviewed_at is None:
                raise MonitoringSignalLifecycleError(
                    "completed review requires reviewed_at"
                )
            reviewed_at = _utc(reviewed_at, "reviewed_at")
        object.__setattr__(self, "reviewer_id", reviewer)
        object.__setattr__(self, "reviewed_at", reviewed_at)
        object.__setattr__(
            self,
            "evidence_ids",
            _ids(self.evidence_ids, "review evidence_ids", required=False),
        )


@dataclass(frozen=True)
class MonitoringDecision:
    """A human decision that may unlock a proportionate action proposal."""

    decision_id: str
    review_id: str
    signal_id: str
    project_id: str
    source_revision: str
    decision: MonitoringDecisionType
    reason: str
    decided_by: str
    decided_at: datetime
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "decision_id",
            "review_id",
            "signal_id",
            "project_id",
            "source_revision",
            "reason",
            "decided_by",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(
            self, "decision", _enum(self.decision, MonitoringDecisionType, "decision")
        )
        object.__setattr__(self, "decided_at", _utc(self.decided_at, "decided_at"))
        object.__setattr__(
            self,
            "evidence_ids",
            _ids(self.evidence_ids, "decision evidence_ids", required=False),
        )


@dataclass(frozen=True)
class MonitoringAction:
    """A proposed or human-confirmed mitigation; never an automatic write."""

    action_id: str
    decision_id: str
    signal_id: str
    project_id: str
    source_revision: str
    kind: MonitoringActionKind
    status: MonitoringActionStatus
    proposed_by: str
    reason: str
    target_scope: MonitoringSignalScope
    target_id: str
    proposed_at: datetime
    confirmed_by: str = ""
    confirmed_at: datetime | None = None
    auto_executed: bool = False

    def __post_init__(self) -> None:
        for name in (
            "action_id",
            "decision_id",
            "signal_id",
            "project_id",
            "source_revision",
            "proposed_by",
            "reason",
            "target_id",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "kind", _enum(self.kind, MonitoringActionKind, "kind"))
        object.__setattr__(
            self, "status", _enum(self.status, MonitoringActionStatus, "status")
        )
        object.__setattr__(
            self,
            "target_scope",
            _enum(self.target_scope, MonitoringSignalScope, "target_scope"),
        )
        object.__setattr__(self, "proposed_at", _utc(self.proposed_at, "proposed_at"))
        confirmed_by = str(self.confirmed_by or "").strip()
        confirmed_at = self.confirmed_at
        if self.status == MonitoringActionStatus.PROPOSED:
            if confirmed_by or confirmed_at is not None:
                raise MonitoringSignalLifecycleError(
                    "proposed action cannot carry confirmation"
                )
        else:
            confirmed_by = _required(confirmed_by, "confirmed_by")
            if confirmed_at is None:
                raise MonitoringSignalLifecycleError(
                    "non-proposed action requires confirmed_at"
                )
            confirmed_at = _utc(confirmed_at, "confirmed_at")
        object.__setattr__(self, "confirmed_by", confirmed_by)
        object.__setattr__(self, "confirmed_at", confirmed_at)
        if _bool(self.auto_executed, "auto_executed") is not False:
            raise MonitoringSignalLifecycleError("auto_executed must remain false")


@dataclass(frozen=True)
class MonitoringRecheck:
    """Human-confirmed recheck against a later or fixed source batch."""

    recheck_id: str
    action_id: str
    signal_id: str
    project_id: str
    source_batch_id: str
    source_revision: str
    result: MonitoringRecheckResult
    reason: str
    reviewer_id: str
    rechecked_at: datetime
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "recheck_id",
            "action_id",
            "signal_id",
            "project_id",
            "source_batch_id",
            "source_revision",
            "reason",
            "reviewer_id",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(
            self, "result", _enum(self.result, MonitoringRecheckResult, "result")
        )
        object.__setattr__(
            self, "rechecked_at", _utc(self.rechecked_at, "rechecked_at")
        )
        object.__setattr__(
            self, "evidence_ids", _ids(self.evidence_ids, "recheck evidence_ids")
        )


@dataclass(frozen=True)
class MonitoringSignalLifecycleReport:
    """Diagnostic result; all authority flags remain false by construction."""

    signal_id: str
    project_id: str
    status: str
    issues: tuple[str, ...]
    current_review_outcome: str
    current_decision: str
    current_action_status: str
    closed: bool
    diagnostic_only: bool = True
    provider_permitted: bool = False
    runtime_write_permitted: bool = False
    medical_authority_granted: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"valid", "blocked"}:
            raise MonitoringSignalLifecycleError("unsupported lifecycle report status")
        if not isinstance(self.diagnostic_only, bool) or not self.diagnostic_only:
            raise MonitoringSignalLifecycleError(
                "lifecycle report must remain diagnostic_only"
            )
        for name in (
            "provider_permitted",
            "runtime_write_permitted",
            "medical_authority_granted",
        ):
            if not isinstance(getattr(self, name), bool) or getattr(self, name):
                raise MonitoringSignalLifecycleError(f"{name} must remain false")

    def public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MONITORING_SIGNAL_LIFECYCLE_SCHEMA_VERSION,
            "signal_id": self.signal_id,
            "project_id": self.project_id,
            "status": self.status,
            "issues": list(self.issues),
            "current_review_outcome": self.current_review_outcome,
            "current_decision": self.current_decision,
            "current_action_status": self.current_action_status,
            "closed": self.closed,
            "diagnostic_only": self.diagnostic_only,
            "provider_permitted": self.provider_permitted,
            "runtime_write_permitted": self.runtime_write_permitted,
            "medical_authority_granted": self.medical_authority_granted,
        }


def _unique_records(records: Iterable[Any], field_name: str) -> tuple[Any, ...]:
    current = tuple(records)
    ids = [str(getattr(item, field_name, "") or "") for item in current]
    if any(not item for item in ids):
        raise MonitoringSignalLifecycleError(
            f"{field_name} is required on every record"
        )
    if len(set(ids)) != len(ids):
        raise MonitoringSignalLifecycleError(f"{field_name} must be unique")
    return current


def assess_monitoring_signal_lifecycle(
    signal: MonitoringSignal,
    reviews: Iterable[MonitoringReview] = (),
    decisions: Iterable[MonitoringDecision] = (),
    actions: Iterable[MonitoringAction] = (),
    rechecks: Iterable[MonitoringRecheck] = (),
) -> MonitoringSignalLifecycleReport:
    """Validate a signal lifecycle without persisting or authorizing it."""

    review_items = _unique_records(reviews, "review_id")
    decision_items = _unique_records(decisions, "decision_id")
    action_items = _unique_records(actions, "action_id")
    recheck_items = _unique_records(rechecks, "recheck_id")
    issues: list[str] = []
    review_by_id = {item.review_id: item for item in review_items}
    decision_by_id = {item.decision_id: item for item in decision_items}
    action_by_id = {item.action_id: item for item in action_items}

    def same_identity(
        item: Any, label: str, *, revision_may_change: bool = False
    ) -> None:
        if item.project_id != signal.project_id:
            issues.append(f"{label}_project_mismatch")
        if item.signal_id != signal.signal_id:
            issues.append(f"{label}_signal_mismatch")
        if not revision_may_change and item.source_revision != signal.source_revision:
            issues.append(f"{label}_source_revision_mismatch")

    for item in review_items:
        same_identity(item, "review")
    terminal_reviews = [
        item
        for item in review_items
        if item.outcome == MonitoringReviewOutcome.ACCEPTED_FOR_DECISION
    ]
    if len(terminal_reviews) > 1:
        issues.append("multiple_reviews_accepted_for_decision")

    for item in decision_items:
        same_identity(item, "decision")
        review = review_by_id.get(item.review_id)
        if review is None:
            issues.append(f"decision_review_missing:{item.decision_id}")
        elif review.outcome != MonitoringReviewOutcome.ACCEPTED_FOR_DECISION:
            issues.append(f"decision_requires_accepted_review:{item.decision_id}")
    if len(decision_items) > 1:
        issues.append("multiple_decisions_for_one_signal")

    confirmed_decision = decision_items[0] if len(decision_items) == 1 else None
    for item in action_items:
        same_identity(item, "action")
        decision = decision_by_id.get(item.decision_id)
        if decision is None:
            issues.append(f"action_decision_missing:{item.action_id}")
        elif (
            decision.decision == MonitoringDecisionType.REJECT_SIGNAL
            and item.kind != MonitoringActionKind.NO_ACTION
        ):
            issues.append(f"rejected_signal_cannot_have_mitigation:{item.action_id}")
        if item.status != MonitoringActionStatus.PROPOSED and decision is None:
            issues.append(f"confirmed_action_requires_decision:{item.action_id}")
        signal_depth = {
            MonitoringSignalScope.TRIAL: 0,
            MonitoringSignalScope.SITE: 1,
            MonitoringSignalScope.SUBJECT: 2,
        }[signal.scope]
        target_depth = {
            MonitoringSignalScope.TRIAL: 0,
            MonitoringSignalScope.SITE: 1,
            MonitoringSignalScope.SUBJECT: 2,
        }[item.target_scope]
        if target_depth < signal_depth:
            issues.append(f"action_target_scope_is_broader:{item.action_id}")

    for item in recheck_items:
        same_identity(item, "recheck", revision_may_change=True)
        action = action_by_id.get(item.action_id)
        if action is None:
            issues.append(f"recheck_action_missing:{item.recheck_id}")
        elif (
            item.result == MonitoringRecheckResult.RESOLVED
            and action.status != MonitoringActionStatus.RESOLVED
        ):
            issues.append(
                f"resolved_recheck_requires_resolved_action:{item.recheck_id}"
            )

    if len(
        {item.review_id for item in review_items}
        | {item.decision_id for item in decision_items}
        | {item.action_id for item in action_items}
        | {item.recheck_id for item in recheck_items}
    ) != len(review_items) + len(decision_items) + len(action_items) + len(
        recheck_items
    ):
        issues.append("cross_stage_event_ids_must_be_unique")

    current_review = (
        terminal_reviews[-1]
        if terminal_reviews
        else (review_items[-1] if review_items else None)
    )
    current_decision = confirmed_decision
    current_action = action_items[-1] if action_items else None
    matching_rechecks = [
        item
        for item in recheck_items
        if current_action and item.action_id == current_action.action_id
    ]
    closed = False
    if (
        current_decision
        and current_decision.decision
        in {
            MonitoringDecisionType.REJECT_SIGNAL,
            MonitoringDecisionType.NO_ACTION,
        }
        and not action_items
    ):
        closed = True
    elif current_action:
        closed = current_action.status == MonitoringActionStatus.CANCELLED or (
            current_action.status == MonitoringActionStatus.RESOLVED
            and any(
                item.result == MonitoringRecheckResult.RESOLVED
                for item in matching_rechecks
            )
        )
    return MonitoringSignalLifecycleReport(
        signal_id=signal.signal_id,
        project_id=signal.project_id,
        status="valid" if not issues else "blocked",
        issues=tuple(dict.fromkeys(issues)),
        current_review_outcome=current_review.outcome.value
        if current_review
        else "none",
        current_decision=current_decision.decision.value
        if current_decision
        else "none",
        current_action_status=current_action.status.value if current_action else "none",
        closed=closed if not issues else False,
    )


__all__ = [
    "MONITORING_SIGNAL_LIFECYCLE_SCHEMA_VERSION",
    "MonitoringAction",
    "MonitoringActionKind",
    "MonitoringActionStatus",
    "MonitoringDecision",
    "MonitoringDecisionType",
    "MonitoringRecheck",
    "MonitoringRecheckResult",
    "MonitoringReview",
    "MonitoringReviewOutcome",
    "MonitoringRiskLevel",
    "MonitoringSignal",
    "MonitoringSignalLifecycleError",
    "MonitoringSignalLifecycleReport",
    "MonitoringSignalOrigin",
    "MonitoringSignalScope",
    "MonitoringSignalTrend",
    "assess_monitoring_signal_lifecycle",
]
