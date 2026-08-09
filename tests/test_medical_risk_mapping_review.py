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
from services.api.app.medical_risk_mapping_approval import mapping_candidate_fingerprint
from services.api.app.medical_risk_mapping_review import (
    MedicalRiskMappingReviewDecision,
    MedicalRiskMappingReviewError,
    MedicalRiskMappingReviewOutcome,
    MedicalRiskMappingReviewStatus,
    evaluate_mapping_review_outcomes,
)


NOW = datetime(2026, 8, 1, 15, 50, tzinfo=timezone.utc)
B4_HASH = "a" * 64
B3_HASH = "b" * 64


def _risk(risk_id: str = "legacy-risk-001") -> RiskCase:
    return RiskCase(
        risk_id=risk_id,
        risk_key=f"risk-key-{risk_id}",
        risk_instance_id=f"risk-instance-{risk_id}",
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


def _record(record_id: str = "disp-001") -> RuxRiskDispositionRecord:
    return RuxRiskDispositionRecord(
        record_id=record_id,
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


def _candidates():
    return propose_legacy_risk_mappings(
        [_record("disp-001"), _record("disp-002")],
        [_risk()],
    )


def _outcome(candidate, *, decision=MedicalRiskMappingReviewDecision.APPROVE, blockers=(), resolved=()):
    return MedicalRiskMappingReviewOutcome(
        review_id=f"review-{candidate.disposition_record_id}",
        candidate_record_id=candidate.disposition_record_id,
        candidate_fingerprint=mapping_candidate_fingerprint(candidate),
        b4_package_sha256=B4_HASH,
        b3_report_hash=B3_HASH,
        reviewer="medical_engineering_reviewer",
        reviewed_at=NOW,
        decision=decision,
        source_evidence=(f"b4:decision:{candidate.disposition_record_id}",),
        resolved_blockers=resolved,
        residual_blockers=blockers,
        comment="仅用于受控离线重演。",
    )


def test_no_external_outcomes_remain_pending_and_non_writing() -> None:
    result = evaluate_mapping_review_outcomes(
        _candidates(),
        (),
        b4_package_sha256=B4_HASH,
        b3_report_hash=B3_HASH,
        residual_blockers_by_record={"disp-001": ("source lineage review required",)},
    )

    assert result.status == MedicalRiskMappingReviewStatus.PENDING_REVIEW
    assert result.migration_ready is False
    assert result.write_permitted is False
    assert result.outcome_count == 0
    assert result.missing_candidate_record_ids == ("disp-001", "disp-002")
    assert result.unresolved_blockers == ("source lineage review required",)


def test_all_hash_bound_residual_free_approvals_only_ready_for_in_memory_next_step() -> None:
    candidates = _candidates()
    result = evaluate_mapping_review_outcomes(
        candidates,
        tuple(_outcome(candidate) for candidate in candidates),
        b4_package_sha256=B4_HASH,
        b3_report_hash=B3_HASH,
        residual_blockers_by_record={},
    )

    assert result.status == MedicalRiskMappingReviewStatus.APPROVED_INPUT_READY
    assert result.migration_ready is True
    assert result.write_permitted is False
    assert len(result.accepted_review_ids) == 2
    assert all(candidate.approved is False for candidate in candidates)


def test_approval_requires_explicit_resolution_of_package_blockers() -> None:
    candidate = _candidates()[0]
    with pytest.raises(MedicalRiskMappingReviewError, match="does not resolve residual blockers"):
        evaluate_mapping_review_outcomes(
            (candidate,),
            (_outcome(candidate),),
            b4_package_sha256=B4_HASH,
            b3_report_hash=B3_HASH,
            residual_blockers_by_record={candidate.disposition_record_id: ("lineage",)},
        )


def test_hash_or_fingerprint_mismatch_fails_closed() -> None:
    candidate = _candidates()[0]
    stale = _outcome(candidate)
    with pytest.raises(MedicalRiskMappingReviewError, match="package hash mismatch"):
        evaluate_mapping_review_outcomes(
            (candidate,),
            (stale.__class__(**{**stale.__dict__, "b4_package_sha256": "c" * 64}),),
            b4_package_sha256=B4_HASH,
            b3_report_hash=B3_HASH,
            residual_blockers_by_record={},
        )

    with pytest.raises(MedicalRiskMappingReviewError, match="fingerprint mismatch"):
        evaluate_mapping_review_outcomes(
            (candidate,),
            (stale.__class__(**{**stale.__dict__, "candidate_fingerprint": "d" * 64}),),
            b4_package_sha256=B4_HASH,
            b3_report_hash=B3_HASH,
            residual_blockers_by_record={},
        )


def test_reject_keeps_gate_closed_without_mutating_candidate() -> None:
    candidate = _candidates()[0]
    result = evaluate_mapping_review_outcomes(
        (candidate,),
        (_outcome(candidate, decision=MedicalRiskMappingReviewDecision.REJECT),),
        b4_package_sha256=B4_HASH,
        b3_report_hash=B3_HASH,
        residual_blockers_by_record={},
    )

    assert result.status == MedicalRiskMappingReviewStatus.REJECTED
    assert result.migration_ready is False
    assert result.write_permitted is False
    assert result.rejected_candidate_record_ids == (candidate.disposition_record_id,)
    assert candidate.approved is False
    assert candidate.write_permitted is False
