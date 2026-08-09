from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.api.app.monitoring_signal_lifecycle_contract import (
    MonitoringAction,
    MonitoringActionKind,
    MonitoringActionStatus,
    MonitoringDecision,
    MonitoringDecisionType,
    MonitoringRecheck,
    MonitoringRecheckResult,
    MonitoringReview,
    MonitoringReviewOutcome,
    MonitoringRiskLevel,
    MonitoringSignal,
    MonitoringSignalLifecycleError,
    MonitoringSignalOrigin,
    MonitoringSignalScope,
    MonitoringSignalTrend,
    assess_monitoring_signal_lifecycle,
)


NOW = datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)
PROJECT = "proj_rux_03_002"
REVISION = "source-revision-001"


def _signal(**overrides: object) -> MonitoringSignal:
    values: dict[str, object] = {
        "signal_id": "signal-001",
        "project_id": PROJECT,
        "scope": MonitoringSignalScope.SUBJECT,
        "scope_id": "subject-001",
        "source_batch_id": "batch-001",
        "source_revision": REVISION,
        "evidence_ids": ("evidence-001",),
        "origin": MonitoringSignalOrigin.AI,
        "risk_level": MonitoringRiskLevel.HIGH,
        "trend": MonitoringSignalTrend.INCREASED,
        "rule_or_model_ref": "model-risk-v1",
        "prompt_revision": "prompt-v1",
        "generated_at": NOW,
    }
    values.update(overrides)
    return MonitoringSignal(**values)  # type: ignore[arg-type]


def _review(signal: MonitoringSignal, **overrides: object) -> MonitoringReview:
    values: dict[str, object] = {
        "review_id": "review-001",
        "signal_id": signal.signal_id,
        "project_id": signal.project_id,
        "source_revision": signal.source_revision,
        "outcome": MonitoringReviewOutcome.ACCEPTED_FOR_DECISION,
        "reason": "evidence reviewed",
        "reviewer_id": "monitor-001",
        "reviewed_at": NOW,
        "evidence_ids": ("evidence-001",),
    }
    values.update(overrides)
    return MonitoringReview(**values)  # type: ignore[arg-type]


def _decision(
    signal: MonitoringSignal, review: MonitoringReview, **overrides: object
) -> MonitoringDecision:
    values: dict[str, object] = {
        "decision_id": "decision-001",
        "review_id": review.review_id,
        "signal_id": signal.signal_id,
        "project_id": signal.project_id,
        "source_revision": signal.source_revision,
        "decision": MonitoringDecisionType.CONFIRM_RISK,
        "reason": "risk requires targeted review",
        "decided_by": "monitor-001",
        "decided_at": NOW,
        "evidence_ids": ("evidence-001",),
    }
    values.update(overrides)
    return MonitoringDecision(**values)  # type: ignore[arg-type]


def _action(
    signal: MonitoringSignal, decision: MonitoringDecision, **overrides: object
) -> MonitoringAction:
    values: dict[str, object] = {
        "action_id": "action-001",
        "decision_id": decision.decision_id,
        "signal_id": signal.signal_id,
        "project_id": signal.project_id,
        "source_revision": signal.source_revision,
        "kind": MonitoringActionKind.TARGETED_REVIEW,
        "status": MonitoringActionStatus.RESOLVED,
        "proposed_by": "ai:model-risk-v1",
        "reason": "review the subject record and site context",
        "target_scope": MonitoringSignalScope.SUBJECT,
        "target_id": "subject-001",
        "proposed_at": NOW,
        "confirmed_by": "monitor-001",
        "confirmed_at": NOW,
        "auto_executed": False,
    }
    values.update(overrides)
    return MonitoringAction(**values)  # type: ignore[arg-type]


def _recheck(
    signal: MonitoringSignal, action: MonitoringAction, **overrides: object
) -> MonitoringRecheck:
    values: dict[str, object] = {
        "recheck_id": "recheck-001",
        "action_id": action.action_id,
        "signal_id": signal.signal_id,
        "project_id": signal.project_id,
        "source_batch_id": "batch-002",
        "source_revision": "source-revision-002",
        "result": MonitoringRecheckResult.RESOLVED,
        "reason": "follow-up batch no longer supports the signal",
        "reviewer_id": "monitor-001",
        "rechecked_at": NOW,
        "evidence_ids": ("evidence-002",),
    }
    values.update(overrides)
    return MonitoringRecheck(**values)  # type: ignore[arg-type]


def test_complete_chain_is_valid_closed_and_diagnostic_only() -> None:
    signal = _signal()
    review = _review(signal)
    decision = _decision(signal, review)
    action = _action(signal, decision)
    report = assess_monitoring_signal_lifecycle(
        signal, (review,), (decision,), (action,), (_recheck(signal, action),)
    )
    assert report.status == "valid"
    assert report.closed is True
    assert report.public_dict()["diagnostic_only"] is True
    assert report.public_dict()["provider_permitted"] is False
    assert report.public_dict()["runtime_write_permitted"] is False


def test_pending_review_cannot_unlock_a_decision() -> None:
    signal = _signal()
    review = _review(
        signal,
        outcome=MonitoringReviewOutcome.PENDING,
        reviewer_id="",
        reviewed_at=None,
    )
    decision = _decision(signal, review)
    report = assess_monitoring_signal_lifecycle(signal, (review,), (decision,))
    assert report.status == "blocked"
    assert "decision_requires_accepted_review:decision-001" in report.issues


def test_revision_and_project_mismatches_fail_closed() -> None:
    signal = _signal()
    review = _review(
        signal, project_id="other-project", source_revision="other-revision"
    )
    report = assess_monitoring_signal_lifecycle(signal, (review,))
    assert report.status == "blocked"
    assert "review_project_mismatch" in report.issues
    assert "review_source_revision_mismatch" in report.issues


def test_auto_action_and_broad_target_are_rejected() -> None:
    signal = _signal(scope=MonitoringSignalScope.SUBJECT)
    review = _review(signal)
    decision = _decision(signal, review)
    with pytest.raises(MonitoringSignalLifecycleError, match="auto_executed"):
        _action(signal, decision, auto_executed=True)
    action = _action(
        signal, decision, target_scope=MonitoringSignalScope.TRIAL, target_id=PROJECT
    )
    report = assess_monitoring_signal_lifecycle(
        signal, (review,), (decision,), (action,)
    )
    assert report.status == "blocked"
    assert "action_target_scope_is_broader:action-001" in report.issues


def test_resolved_recheck_requires_resolved_action() -> None:
    signal = _signal()
    review = _review(signal)
    decision = _decision(signal, review)
    action = _action(signal, decision, status=MonitoringActionStatus.IN_PROGRESS)
    recheck = _recheck(signal, action)
    report = assess_monitoring_signal_lifecycle(
        signal, (review,), (decision,), (action,), (recheck,)
    )
    assert report.status == "blocked"
    assert "resolved_recheck_requires_resolved_action:recheck-001" in report.issues


def test_rejected_signal_can_close_without_action() -> None:
    signal = _signal()
    review = _review(signal)
    decision = _decision(signal, review, decision=MonitoringDecisionType.REJECT_SIGNAL)
    report = assess_monitoring_signal_lifecycle(signal, (review,), (decision,))
    assert report.status == "valid"
    assert report.closed is True


def test_duplicate_cross_stage_ids_are_rejected() -> None:
    signal = _signal()
    review = _review(signal, review_id="same-id")
    decision = _decision(signal, review, decision_id="same-id")
    report = assess_monitoring_signal_lifecycle(signal, (review,), (decision,))
    assert report.status == "blocked"
    assert "cross_stage_event_ids_must_be_unique" in report.issues


def test_ai_signal_requires_prompt_and_auto_action_flag() -> None:
    with pytest.raises(MonitoringSignalLifecycleError, match="prompt_revision"):
        _signal(prompt_revision="")
    with pytest.raises(MonitoringSignalLifecycleError, match="auto_action_forbidden"):
        _signal(auto_action_forbidden=False)
