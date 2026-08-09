from __future__ import annotations

from datetime import datetime, timezone

import pytest

from packages.contracts.workbench_contracts.models import RiskCase, RiskSeverity, RiskStatus
from services.api.app.medical_risk_identity_transition import (
    MedicalRiskDispositionLineage,
    MedicalRiskIdentityTransitionKind,
    classify_risk_identity_transition,
)


NOW = datetime(2026, 8, 6, 0, 50, tzinfo=timezone.utc)


def _risk(
    instance_id: str,
    *,
    batch_delta: str,
    status: RiskStatus = RiskStatus.ACTION_REQUIRED,
    project_id: str = "proj_transition",
    risk_key: str = "riskkey_001",
) -> RiskCase:
    return RiskCase(
        risk_id=f"risk_{instance_id}",
        risk_key=risk_key,
        risk_instance_id=instance_id,
        project_id=project_id,
        module="medical_monitoring",
        risk_type="实验室异常",
        primary_category="laboratory_abnormality",
        title="实验室异常需医学复核",
        subject_id="S001",
        site_id="SITE01",
        severity=RiskSeverity.HIGH,
        status=status,
        source_batch_id="batch_002",
        source_revision="source_002",
        rule_profile_revision="rules_001",
        engine_version="engine_001",
        batch_delta=batch_delta,
        rule_id="LAB_001",
        evidence_span_ids=["listing:LB:row:1"],
        rationale="需医学复核。",
        recommended_action="医学复核。",
        created_at=NOW,
    )


def test_first_instance_is_new_without_disposition_lineage() -> None:
    transition = classify_risk_identity_transition(None, _risk("instance-001", batch_delta="baseline"))

    assert transition.kind is MedicalRiskIdentityTransitionKind.NEW
    assert transition.disposition_lineage is MedicalRiskDispositionLineage.NONE
    assert transition.supersedes_risk_instance_id == ""


def test_persisting_instance_is_continuation_and_preserves_context_only_by_contract() -> None:
    transition = classify_risk_identity_transition(
        _risk("instance-001", batch_delta="baseline"),
        _risk("instance-002", batch_delta="persisting"),
    )

    assert transition.kind is MedicalRiskIdentityTransitionKind.CONTINUATION
    assert transition.disposition_lineage is MedicalRiskDispositionLineage.PRESERVE
    assert transition.previous_risk_instance_id == "instance-001"
    assert transition.supersedes_risk_instance_id == ""


def test_reopen_does_not_restore_closed_disposition_to_current_instance() -> None:
    transition = classify_risk_identity_transition(
        _risk("instance-001", batch_delta="baseline", status=RiskStatus.CLOSED),
        _risk("instance-002", batch_delta="reopened"),
    )

    public = transition.public_dict()
    assert transition.kind is MedicalRiskIdentityTransitionKind.REOPEN
    assert transition.disposition_lineage is MedicalRiskDispositionLineage.HISTORY_ONLY
    assert public["reason_code"] == "closed_or_resolved_risk_triggered_again"


def test_changed_instance_exposes_superseded_predecessor_and_history_only_policy() -> None:
    transition = classify_risk_identity_transition(
        _risk("instance-001", batch_delta="baseline"),
        _risk("instance-002", batch_delta="changed"),
    )

    assert transition.kind is MedicalRiskIdentityTransitionKind.SUPERSEDE
    assert transition.supersedes_risk_instance_id == "instance-001"
    assert transition.disposition_lineage is MedicalRiskDispositionLineage.HISTORY_ONLY


def test_transition_rejects_cross_identity_comparison() -> None:
    with pytest.raises(ValueError, match="risk_key mismatch"):
        classify_risk_identity_transition(
            _risk("instance-001", batch_delta="baseline"),
            _risk("instance-002", batch_delta="persisting", risk_key="riskkey_other"),
        )


def test_changed_or_reopened_transition_fails_closed_if_instance_is_reused() -> None:
    previous = _risk("instance-001", batch_delta="baseline")
    with pytest.raises(ValueError, match="new risk_instance_id"):
        classify_risk_identity_transition(
            previous,
            _risk("instance-001", batch_delta="changed"),
        )
    with pytest.raises(ValueError, match="new risk_instance_id"):
        classify_risk_identity_transition(
            previous,
            _risk("instance-001", batch_delta="reopened"),
        )
