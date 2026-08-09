from __future__ import annotations

from datetime import datetime, timezone

import pytest

from packages.contracts.workbench_contracts.models import (
    RiskCase,
    RiskSeverity,
    RiskStatus,
    RuxRiskDispositionAction,
    RuxRiskDispositionRecord,
)
from services.api.app.medical_risk_mapping import propose_legacy_risk_mappings
from services.api.app.medical_risk_mapping_approval import (
    MedicalRiskMappingApproval,
    MedicalRiskMappingApprovalDecision,
    MedicalRiskMappingApprovalError,
    approve_mapping_candidate,
    mapping_candidate_fingerprint,
    remap_with_approved_mapping,
)


NOW = datetime(2026, 8, 1, 15, 40, tzinfo=timezone.utc)


def _risk() -> RiskCase:
    return RiskCase(
        risk_id="legacy-risk-001",
        risk_key="risk-key-001",
        risk_instance_id="risk-instance-001",
        project_id="proj_test",
        module="medical_monitoring",
        risk_type="实验室异常",
        primary_category="laboratory_abnormality",
        title="实验室异常需复核",
        subject_id="S001",
        site_id="SITE01",
        scope_type="subject",
        scope_id="S001",
        severity=RiskSeverity.HIGH,
        status=RiskStatus.ACTION_REQUIRED,
        source_revision="source-001",
        rule_profile_revision="rules-001",
        engine_version="engine-001",
        rule_id="LAB-001",
        evidence_span_ids=["listing:LB:row:1"],
        rationale="需复核。",
        recommended_action="医学复核。",
        created_at=NOW,
    )


def _record() -> RuxRiskDispositionRecord:
    return RuxRiskDispositionRecord(
        record_id="disp-001",
        project_id="proj_test",
        item_id="monitoring-risk:legacy-risk-001",
        risk_id="legacy-risk-001",
        snapshot_id="snap-001",
        subject_id="S001",
        rule_id="LAB-001",
        action=RuxRiskDispositionAction.REVIEWED,
        previous_state="pending_review",
        new_state="reviewed",
        source_version="source-token-001",
        created_at=NOW,
    )


def _candidate():
    return propose_legacy_risk_mappings([_record()], [_risk()])[0]


def _approval(candidate, *, decision=MedicalRiskMappingApprovalDecision.APPROVE, blockers=()):
    return MedicalRiskMappingApproval(
        approval_id="approval-001",
        candidate_record_id=candidate.disposition_record_id,
        candidate_fingerprint=mapping_candidate_fingerprint(candidate),
        reviewer="medical_engineering_reviewer",
        reviewed_at=NOW,
        decision=decision,
        source_evidence=("b4:decision:disp-001", "source:snapshot-001"),
        residual_blockers=blockers,
        comment="仅用于受控离线重演，未授权运行库写入。",
    )


def test_approval_requires_hash_bound_candidate_and_preserves_nonwriting_boundary() -> None:
    candidate = _candidate()
    approved = approve_mapping_candidate(candidate, _approval(candidate))
    remapped = remap_with_approved_mapping(_record(), approved)

    assert approved.public_dict()["approved"] is True
    assert approved.public_dict()["write_permitted"] is False
    assert remapped.risk_instance_id == "risk-instance-001"
    assert _record().risk_instance_id == ""


def test_rejected_or_blocked_approval_fails_closed() -> None:
    candidate = _candidate()
    rejected = _approval(candidate, decision=MedicalRiskMappingApprovalDecision.REJECT)
    with pytest.raises(MedicalRiskMappingApprovalError, match="not approved"):
        approve_mapping_candidate(candidate, rejected)
    with pytest.raises(MedicalRiskMappingApprovalError, match="residual blockers"):
        _approval(candidate, blockers=("source lineage review required",))


def test_candidate_fingerprint_change_is_rejected() -> None:
    candidate = _candidate()
    approval = _approval(candidate)
    changed = candidate.__class__(
        **{
            **candidate.__dict__,
            "current_risk_instance_id": "risk-instance-002",
        }
    )

    with pytest.raises(MedicalRiskMappingApprovalError, match="fingerprint"):
        approve_mapping_candidate(changed, approval)


def test_approval_record_id_mismatch_is_rejected_at_apply() -> None:
    candidate = _candidate()
    approved = approve_mapping_candidate(candidate, _approval(candidate))
    other = _record().model_copy(update={"record_id": "disp-other"})

    with pytest.raises(MedicalRiskMappingApprovalError, match="does not match"):
        remap_with_approved_mapping(other, approved)
