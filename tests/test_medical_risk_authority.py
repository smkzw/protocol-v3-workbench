from __future__ import annotations

from datetime import datetime, timezone

import pytest

from packages.contracts.workbench_contracts.models import RiskCase, RiskSeverity, RiskStatus
from services.api.app.medical_risk_authority import (
    MedicalRiskAggregate,
    MedicalRiskDispositionState,
    MedicalRiskDuplicateEventConflict,
    MedicalRiskEvent,
    MedicalRiskEventType,
    MedicalRiskFindingClass,
    MedicalRiskIdentity,
    MedicalRiskIdentityError,
    MedicalRiskVersionConflict,
    append_medical_risk_event,
)


NOW = datetime(2026, 8, 1, 15, 10, tzinfo=timezone.utc)


def _identity(
    *,
    scope_type: str = "subject",
    scope_id: str = "S001",
    site_id: str | None = "SITE01",
    subject_id: str | None = "S001",
) -> MedicalRiskIdentity:
    return MedicalRiskIdentity(
        risk_key="risk-key-001",
        risk_instance_id="risk-instance-001",
        project_id="proj_rux_03_002",
        trial_id="trial-rux-03-002",
        scope_type=scope_type,  # type: ignore[arg-type]
        scope_id=scope_id,
        site_id=site_id,
        subject_id=subject_id,
    )


def _aggregate() -> MedicalRiskAggregate:
    return MedicalRiskAggregate(
        identity=_identity(),
        category="laboratory_abnormality",
        severity=RiskSeverity.HIGH,
        finding_class=MedicalRiskFindingClass.REGISTERED_FINDING,
        status=RiskStatus.ACTION_REQUIRED,
        source_revision="listing-revision-001",
        rule_profile_revision="rules-r3",
        engine_version="monitoring-engine-v1",
        rule_id="ALT_GT_3_ULN",
        title="ALT升高需医学复核",
        rationale="ALT超过预设阈值，需核对AE、CM及给药记录。",
        recommended_action="医学经理复核并记录处置。",
        evidence_ids=("listing:LB:row:1", "protocol:section:6.5"),
        created_at=NOW,
        updated_at=NOW,
    )


def _event(
    aggregate: MedicalRiskAggregate,
    event_id: str,
    event_type: MedicalRiskEventType,
    expected_version: int,
    payload: dict[str, object] | None = None,
    *,
    occurred_at: datetime = NOW,
) -> MedicalRiskEvent:
    return MedicalRiskEvent.create(
        event_id=event_id,
        event_type=event_type,
        identity=aggregate.identity,
        source_revision=aggregate.source_revision,
        actor="medical_manager",
        expected_version=expected_version,
        payload=payload,
        occurred_at=occurred_at,
    )


def _risk_case() -> RiskCase:
    return RiskCase(
        risk_id="legacy-risk-001",
        risk_key="risk-key-001",
        risk_instance_id="risk-instance-001",
        project_id="proj_rux_03_002",
        module="medical_monitoring",
        risk_type="实验室异常",
        primary_category="laboratory_abnormality",
        title="ALT升高需医学复核",
        subject_id="S001",
        site_id="SITE01",
        scope_type="subject",
        scope_id="S001",
        severity=RiskSeverity.HIGH,
        status=RiskStatus.ACTION_REQUIRED,
        source_batch_id="batch-001",
        source_revision="listing-revision-001",
        rule_profile_revision="rules-r3",
        engine_version="monitoring-engine-v1",
        rule_id="ALT_GT_3_ULN",
        evidence_span_ids=["listing:LB:row:1"],
        rationale="ALT超过预设阈值。",
        recommended_action="医学经理复核。",
        created_at=NOW,
    )


def test_identity_rejects_ambiguous_scope() -> None:
    with pytest.raises(MedicalRiskIdentityError, match="include site_id"):
        _identity(site_id=None)
    with pytest.raises(MedicalRiskIdentityError, match="trial_id as scope_id"):
        _identity(scope_type="trial", scope_id="proj_rux_03_002", site_id=None, subject_id=None)
    with pytest.raises(MedicalRiskIdentityError, match="cannot carry subject"):
        _identity(scope_type="site", scope_id="SITE01", subject_id="S001")


def test_from_risk_case_requires_explicit_trial_identity_and_preserves_scope() -> None:
    aggregate = MedicalRiskAggregate.from_risk_case(
        _risk_case(),
        trial_id="trial-rux-03-002",
        finding_class=MedicalRiskFindingClass.UNCERTAIN,
    )

    assert aggregate.identity.trial_id == "trial-rux-03-002"
    assert aggregate.identity.project_id == "proj_rux_03_002"
    assert aggregate.identity.scope_type == "subject"
    assert aggregate.identity.site_id == "SITE01"
    assert aggregate.finding_class is MedicalRiskFindingClass.UNCERTAIN
    assert aggregate.disposition_state is MedicalRiskDispositionState.PENDING_REVIEW


def test_event_is_immutable_and_hashes_the_full_payload() -> None:
    aggregate = _aggregate()
    event = _event(
        aggregate,
        "event-read-001",
        MedicalRiskEventType.MARK_READ,
        0,
        {"unread": False, "reason": "已打开风险证据"},
    )

    assert event.event_hash == event.public_dict()["event_hash"]
    with pytest.raises(TypeError):
        event.payload["reason"] = "changed"  # type: ignore[index]
    with pytest.raises(ValueError, match="event_hash"):
        MedicalRiskEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            identity=event.identity,
            source_revision=event.source_revision,
            actor=event.actor,
            expected_version=event.expected_version,
            payload=event.payload,
            occurred_at=event.occurred_at,
            event_hash="0" * 64,
        )


def test_cas_rejects_stale_write_and_allows_exact_idempotent_replay() -> None:
    aggregate = _aggregate()
    mark_read = _event(
        aggregate,
        "event-read-001",
        MedicalRiskEventType.MARK_READ,
        0,
        {"unread": False},
    )
    updated = append_medical_risk_event(aggregate, mark_read)
    assert updated.aggregate_version == 1
    assert updated.unread is False
    assert append_medical_risk_event(updated, mark_read) is updated

    stale = _event(
        updated,
        "event-disposition-stale",
        MedicalRiskEventType.DISPOSITION_RECORDED,
        0,
        {"disposition_state": MedicalRiskDispositionState.REVIEWED.value},
    )
    with pytest.raises(MedicalRiskVersionConflict) as conflict:
        append_medical_risk_event(updated, stale)
    assert conflict.value.expected_version == 0
    assert conflict.value.actual_version == 1

    reused_id = _event(
        updated,
        "event-read-001",
        MedicalRiskEventType.MARK_READ,
        0,
        {"unread": False, "reason": "different payload"},
    )
    with pytest.raises(MedicalRiskDuplicateEventConflict):
        append_medical_risk_event(updated, reused_id)


def test_disposition_query_reopen_and_reclassification_are_separate_dimensions() -> None:
    aggregate = _aggregate()
    reviewed = append_medical_risk_event(
        aggregate,
        _event(
            aggregate,
            "event-reviewed-001",
            MedicalRiskEventType.DISPOSITION_RECORDED,
            0,
            {"disposition_state": MedicalRiskDispositionState.REVIEWED.value},
        ),
    )
    drafted = append_medical_risk_event(
        reviewed,
        _event(
            reviewed,
            "event-query-001",
            MedicalRiskEventType.QUERY_DRAFTED,
            1,
            {"query_draft_text": "请中心核对ALT复测与AE记录。"},
            occurred_at=NOW.replace(minute=11),
        ),
    )
    reopened = append_medical_risk_event(
        drafted,
        _event(
            drafted,
            "event-reopen-001",
            MedicalRiskEventType.REOPENED,
            2,
            {},
            occurred_at=NOW.replace(minute=12),
        ),
    )
    reclassified = append_medical_risk_event(
        reopened,
        _event(
            reopened,
            "event-reclassify-001",
            MedicalRiskEventType.RECLASSIFIED,
            3,
            {"finding_class": MedicalRiskFindingClass.UNCERTAIN.value},
            occurred_at=NOW.replace(minute=13),
        ),
    )

    assert reviewed.status is RiskStatus.ACTION_REQUIRED
    assert drafted.disposition_state is MedicalRiskDispositionState.QUERY_DRAFT
    assert drafted.query_draft_text.startswith("请中心")
    assert reopened.disposition_state is MedicalRiskDispositionState.PENDING_REVIEW
    assert reopened.query_draft_text == ""
    assert reclassified.finding_class is MedicalRiskFindingClass.UNCERTAIN
    assert reclassified.status is RiskStatus.ACTION_REQUIRED
    assert reclassified.unread is True
    assert reclassified.aggregate_version == 4


def test_event_identity_and_source_revision_are_bound_to_the_aggregate() -> None:
    aggregate = _aggregate()
    other_identity = _identity(scope_id="S002", subject_id="S002")
    event = MedicalRiskEvent.create(
        event_id="event-other-subject",
        event_type=MedicalRiskEventType.MARK_READ,
        identity=other_identity,
        source_revision=aggregate.source_revision,
        actor="medical_manager",
        expected_version=0,
        payload={"unread": False},
        occurred_at=NOW,
    )
    with pytest.raises(MedicalRiskIdentityError, match="identity"):
        append_medical_risk_event(aggregate, event)

    wrong_source = MedicalRiskEvent.create(
        event_id="event-other-source",
        event_type=MedicalRiskEventType.MARK_READ,
        identity=aggregate.identity,
        source_revision="listing-revision-002",
        actor="medical_manager",
        expected_version=0,
        payload={"unread": False},
        occurred_at=NOW,
    )
    with pytest.raises(MedicalRiskIdentityError, match="source revision"):
        append_medical_risk_event(aggregate, wrong_source)


def test_public_payload_exposes_identity_and_separate_workflow_dimensions() -> None:
    payload = _aggregate().public_dict()

    assert payload["trial_id"] == "trial-rux-03-002"
    assert payload["site_id"] == "SITE01"
    assert payload["subject_id"] == "S001"
    assert payload["finding_class"] == "registered_finding"
    assert payload["status"] == "action_required"
    assert payload["disposition_state"] == "pending_review"
    assert payload["unread"] is True
