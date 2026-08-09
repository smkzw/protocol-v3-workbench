from __future__ import annotations

from datetime import datetime, timezone

from packages.contracts.workbench_contracts.models import (
    RiskCase,
    RiskSeverity,
    RiskStatus,
    RuxRiskDispositionAction,
    RuxRiskDispositionRecord,
)
from services.api.app.medical_risk_mapping import (
    MedicalRiskMappingBasis,
    propose_legacy_risk_mappings,
    remap_disposition_for_dry_run,
)


NOW = datetime(2026, 8, 1, 15, 30, tzinfo=timezone.utc)


def _risk(
    *,
    risk_id: str = "legacy-risk-001",
    risk_key: str = "risk-key-001",
    risk_instance_id: str = "risk-instance-001",
) -> RiskCase:
    return RiskCase(
        risk_id=risk_id,
        risk_key=risk_key,
        risk_instance_id=risk_instance_id,
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


def _record(
    *,
    record_id: str = "disp-001",
    risk_id: str = "legacy-risk-001",
    risk_key: str = "",
    risk_instance_id: str = "",
    item_id: str = "monitoring-risk:legacy-risk-001",
) -> RuxRiskDispositionRecord:
    return RuxRiskDispositionRecord(
        record_id=record_id,
        project_id="proj_test",
        item_id=item_id,
        risk_id=risk_id,
        risk_key=risk_key,
        risk_instance_id=risk_instance_id,
        snapshot_id="snap-001",
        subject_id="S001",
        rule_id="LAB-001",
        action=RuxRiskDispositionAction.REVIEWED,
        previous_state="pending_review",
        new_state="reviewed",
        source_version="source-token-001",
        created_at=NOW,
    )


def test_exact_legacy_risk_id_is_a_review_only_high_confidence_candidate() -> None:
    record = _record()
    candidates = propose_legacy_risk_mappings([record], [_risk()])

    candidate = candidates[0]
    assert candidate.basis is MedicalRiskMappingBasis.EXACT_RISK_ID
    assert candidate.current_risk_instance_id == "risk-instance-001"
    assert candidate.confidence == "high"
    assert candidate.approved is False
    assert candidate.write_permitted is False
    assert candidate.review_required is True


def test_exact_risk_key_can_map_when_legacy_record_has_no_risk_id_match() -> None:
    record = _record(risk_id="old-risk-id", risk_key="risk-key-001", item_id="monitoring-risk:old-risk-id")
    candidate = propose_legacy_risk_mappings([record], [_risk()])[0]

    assert candidate.basis is MedicalRiskMappingBasis.EXACT_RISK_KEY
    assert candidate.current_risk_key == "risk-key-001"


def test_no_candidate_and_ambiguous_candidates_are_not_guessed() -> None:
    no_candidate = propose_legacy_risk_mappings(
        [_record(risk_id="missing", risk_key="missing-key", item_id="monitoring-risk:missing")],
        [_risk()],
    )[0]
    ambiguous = propose_legacy_risk_mappings(
        [_record(risk_id="same-id", item_id="monitoring-risk:same-id")],
        [_risk(risk_id="same-id", risk_key="key-a", risk_instance_id="instance-a"),
         _risk(risk_id="same-id", risk_key="key-b", risk_instance_id="instance-b")],
    )[0]

    assert no_candidate.basis is MedicalRiskMappingBasis.NO_CANDIDATE
    assert no_candidate.has_candidate is False
    assert ambiguous.basis is MedicalRiskMappingBasis.AMBIGUOUS
    assert ambiguous.has_candidate is False


def test_dry_run_remap_returns_deep_copy_and_does_not_approve_candidate() -> None:
    record = _record()
    candidate = propose_legacy_risk_mappings([record], [_risk()])[0]
    remapped = remap_disposition_for_dry_run(record, candidate)

    assert remapped is not record
    assert remapped.risk_instance_id == "risk-instance-001"
    assert remapped.item_id == "monitoring-risk:risk-instance-001"
    assert record.risk_instance_id == ""
    assert candidate.approved is False
    assert candidate.write_permitted is False
