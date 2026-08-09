from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from packages.contracts.workbench_contracts.models import (
    MonitoringRiskDispositionKind,
    RiskCase,
    RiskSeverity,
    RiskStatus,
    RuxRiskDispositionAction,
    RuxRiskDispositionRecord,
)
from services.api.app.medical_risk_authority import (
    MedicalRiskAggregate,
    MedicalRiskDispositionState,
)
from services.api.app.medical_risk_reconciliation import (
    MedicalRiskReconciliationIssueCode,
    reconcile_medical_risk_records,
)


NOW = datetime(2026, 8, 1, 15, 20, tzinfo=timezone.utc)


def _risk_case(*, source_revision: str = "listing-revision-001") -> RiskCase:
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
        source_revision=source_revision,
        rule_profile_revision="rules-r3",
        engine_version="monitoring-engine-v1",
        rule_id="ALT_GT_3_ULN",
        evidence_span_ids=["listing:LB:row:1"],
        rationale="ALT超过预设阈值。",
        recommended_action="医学经理复核。",
        created_at=NOW,
    )


def _aggregate(*, disposition_state: MedicalRiskDispositionState = MedicalRiskDispositionState.PENDING_REVIEW) -> MedicalRiskAggregate:
    return replace(
        MedicalRiskAggregate.from_risk_case(
            _risk_case(),
            trial_id="trial-rux-03-002",
        ),
        disposition_state=disposition_state,
    )


def _record(
    *,
    record_id: str,
    risk_instance_id: str = "risk-instance-001",
    risk_key: str = "risk-key-001",
    source_version: str = "source-token-001",
    previous_state: str = "pending_review",
    new_state: str = "reviewed",
    subject_id: str = "S001",
    created_at: datetime = NOW,
    comment: str = "已完成医学复核。",
) -> RuxRiskDispositionRecord:
    return RuxRiskDispositionRecord(
        record_id=record_id,
        project_id="proj_rux_03_002",
        item_id=f"monitoring-risk:{risk_instance_id}",
        risk_id=risk_instance_id,
        risk_key=risk_key,
        risk_instance_id=risk_instance_id,
        snapshot_id="risksnap-001",
        subject_id=subject_id,
        rule_id="ALT_GT_3_ULN",
        action=RuxRiskDispositionAction.REVIEWED,
        disposition_kind=MonitoringRiskDispositionKind.CONTINUE_OBSERVATION,
        previous_state=previous_state,
        new_state=new_state,
        actor="medical_manager",
        comment=comment,
        source_version=source_version,
        created_at=created_at,
    )


def _source_map() -> dict[tuple[str, str], str]:
    return {("proj_rux_03_002", "risk-instance-001"): "source-token-001"}


def test_clean_aggregate_and_disposition_are_migration_ready_and_hash_stable() -> None:
    aggregate = _aggregate(disposition_state=MedicalRiskDispositionState.REVIEWED)
    record = _record(record_id="disp-001")
    report = reconcile_medical_risk_records(
        [aggregate],
        [record],
        expected_source_versions=_source_map(),
    )

    reversed_report = reconcile_medical_risk_records(
        [aggregate],
        [record],
        expected_source_versions=_source_map(),
    )
    assert report.migration_ready is True
    assert report.issue_count == 0
    assert report.matched_disposition_count == 1
    assert report.report_hash == reversed_report.report_hash
    assert report.public_dict()["migration_ready"] is True


def test_legacy_risk_identity_gap_is_reported_instead_of_inferred() -> None:
    report = reconcile_medical_risk_records(
        [_risk_case(source_revision="")],
        [],
        trial_ids_by_project={},
    )

    assert report.migration_ready is False
    assert report.issue_count == 1
    assert report.issues[0].code is MedicalRiskReconciliationIssueCode.RISK_IDENTITY_GAP
    assert "required" in report.issues[0].detail


def test_orphan_and_instance_mismatch_are_distinct() -> None:
    records = [
        _record(record_id="disp-orphan", risk_instance_id="risk-missing", risk_key="missing-key"),
        _record(record_id="disp-mismatch", risk_instance_id="risk-other", risk_key="risk-key-001"),
    ]
    report = reconcile_medical_risk_records(
        [_aggregate()],
        records,
        expected_source_versions={
            ("proj_rux_03_002", "risk-other"): "source-token-001",
            ("proj_rux_03_002", "risk-missing"): "source-token-001",
        },
    )

    codes = {issue.code for issue in report.issues}
    assert MedicalRiskReconciliationIssueCode.ORPHAN_DISPOSITION in codes
    assert MedicalRiskReconciliationIssueCode.DISPOSITION_IDENTITY_MISMATCH in codes
    assert report.matched_disposition_count == 0


def test_source_version_mapping_is_explicit_and_fail_closed() -> None:
    record = _record(record_id="disp-source")
    missing = reconcile_medical_risk_records([_aggregate()], [record])
    wrong = reconcile_medical_risk_records(
        [_aggregate()],
        [record],
        expected_source_versions={
            ("proj_rux_03_002", "risk-instance-001"): "source-token-002"
        },
    )

    assert any(
        issue.code is MedicalRiskReconciliationIssueCode.SOURCE_VERSION_MAPPING_MISSING
        for issue in missing.issues
    )
    assert any(
        issue.code is MedicalRiskReconciliationIssueCode.DISPOSITION_SOURCE_VERSION_MISMATCH
        for issue in wrong.issues
    )


def test_duplicate_business_event_and_chain_gap_are_separate_issues() -> None:
    first = _record(record_id="disp-001")
    duplicate = _record(record_id="disp-002")
    chain_gap = _record(
        record_id="disp-003",
        previous_state="pending_review",
        new_state="query_draft",
        created_at=NOW.replace(minute=21),
    )
    report = reconcile_medical_risk_records(
        [_risk_case()],
        [first, duplicate, chain_gap],
        trial_ids_by_project={"proj_rux_03_002": "trial-rux-03-002"},
        expected_source_versions=_source_map(),
    )

    codes = {issue.code for issue in report.issues}
    assert MedicalRiskReconciliationIssueCode.DUPLICATE_DISPOSITION_EVENT in codes
    assert MedicalRiskReconciliationIssueCode.DISPOSITION_CHAIN_GAP in codes


def test_aggregate_state_drift_is_reported_without_mutating_aggregate() -> None:
    aggregate = _aggregate(disposition_state=MedicalRiskDispositionState.REVIEWED)
    report = reconcile_medical_risk_records(
        [aggregate],
        [_record(record_id="disp-drift", new_state="query_draft")],
        expected_source_versions=_source_map(),
    )

    assert any(
        issue.code is MedicalRiskReconciliationIssueCode.AGGREGATE_STATE_DRIFT
        for issue in report.issues
    )
    assert aggregate.disposition_state is MedicalRiskDispositionState.REVIEWED


def test_subject_mismatch_is_identity_mismatch_even_when_instance_matches() -> None:
    report = reconcile_medical_risk_records(
        [_aggregate()],
        [_record(record_id="disp-subject", subject_id="S999")],
        expected_source_versions=_source_map(),
    )

    assert any(
        issue.code is MedicalRiskReconciliationIssueCode.DISPOSITION_IDENTITY_MISMATCH
        and "subject_id" in issue.detail
        for issue in report.issues
    )
