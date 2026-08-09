from __future__ import annotations

from dataclasses import replace

import pytest

from services.api.app.monitoring_release_gate import (
    REQUIRED_RELEASE_GATE_IDS,
    MonitoringReleaseGateError,
    MonitoringReleaseGateEvidence,
    ReleaseDecisionStatus,
    ReleaseEvidenceStatus,
    evaluate_monitoring_release,
    evaluate_monitoring_release_from_b6_payload,
)


HASH = "a" * 64


def _gates(
    *,
    status: ReleaseEvidenceStatus = ReleaseEvidenceStatus.PASSED,
    replace: dict[str, ReleaseEvidenceStatus] | None = None,
):
    replace = replace or {}
    return tuple(
        MonitoringReleaseGateEvidence(
            gate_id=gate_id,
            status=replace.get(gate_id, status),
            evidence_ids=(f"ev-{gate_id}",),
            evidence_sha256=HASH,
            summary=f"evidence for {gate_id}",
        )
        for gate_id in REQUIRED_RELEASE_GATE_IDS
    )


def test_release_requires_exact_gate_set_and_is_canonical() -> None:
    decision = evaluate_monitoring_release(
        reversed(_gates()),
        b6_status="approved",
        b6_write_permitted=True,
        b6_migration_ready=True,
        b6_migration_write_permitted=True,
    )

    assert decision.status == ReleaseDecisionStatus.READY
    assert decision.release_ready is True
    assert tuple(item.gate_id for item in decision.gate_results) == REQUIRED_RELEASE_GATE_IDS
    assert len(decision.decision_sha256) == 64
    assert decision.to_dict()["decision_sha256"] == decision.decision_sha256


def test_pending_b6_blocks_even_when_all_p0_p10_gates_pass() -> None:
    decision = evaluate_monitoring_release(
        _gates(),
        b6_status="pending_review",
        b6_write_permitted=False,
        b6_migration_ready=False,
        b6_migration_write_permitted=False,
    )

    assert decision.status == ReleaseDecisionStatus.BLOCKED
    assert decision.release_ready is False
    assert decision.unmet_gate_ids == ()
    assert "b6:approved_write_migration_and_migration_write_authority_required" in decision.reasons


def test_partial_gate_is_not_ready_and_blocked_gate_is_blocked() -> None:
    partial = evaluate_monitoring_release(
        _gates(replace={"browser_interaction_matrix": ReleaseEvidenceStatus.PARTIAL}),
        b6_status="approved",
        b6_write_permitted=True,
        b6_migration_ready=True,
        b6_migration_write_permitted=True,
    )
    blocked = evaluate_monitoring_release(
        _gates(replace={"risk_disposition_authority": ReleaseEvidenceStatus.BLOCKED}),
        b6_status="approved",
        b6_write_permitted=True,
        b6_migration_ready=True,
        b6_migration_write_permitted=True,
    )

    assert partial.status == ReleaseDecisionStatus.NOT_READY
    assert partial.unmet_gate_ids == ("browser_interaction_matrix",)
    assert blocked.status == ReleaseDecisionStatus.BLOCKED
    assert blocked.unmet_gate_ids == ("risk_disposition_authority",)


def test_gate_evidence_requires_hash_and_summary() -> None:
    with pytest.raises(MonitoringReleaseGateError, match="evidence_sha256"):
        MonitoringReleaseGateEvidence(
            gate_id="source_authority",
            status="passed",
            evidence_ids=("source",),
            evidence_sha256="missing",
            summary="source evidence",
        )
    with pytest.raises(MonitoringReleaseGateError, match="summary"):
        MonitoringReleaseGateEvidence(
            gate_id="source_authority",
            status="passed",
            evidence_ids=("source",),
            evidence_sha256=HASH,
            summary="",
        )


def test_gate_evidence_rejects_non_string_identity_fields() -> None:
    with pytest.raises(MonitoringReleaseGateError, match="gate_id must be a string"):
        MonitoringReleaseGateEvidence(
            gate_id=123,  # type: ignore[arg-type]
            status="passed",
            evidence_ids=("source",),
            evidence_sha256=HASH,
            summary="source evidence",
        )
    with pytest.raises(MonitoringReleaseGateError, match="evidence_sha256 must be a string"):
        MonitoringReleaseGateEvidence(
            gate_id="source_authority",
            status="passed",
            evidence_ids=("source",),
            evidence_sha256=123,  # type: ignore[arg-type]
            summary="source evidence",
        )
    with pytest.raises(MonitoringReleaseGateError, match="summary must be a string"):
        MonitoringReleaseGateEvidence(
            gate_id="source_authority",
            status="passed",
            evidence_ids=("source",),
            evidence_sha256=HASH,
            summary=123,  # type: ignore[arg-type]
        )
    with pytest.raises(MonitoringReleaseGateError, match="collection of strings"):
        MonitoringReleaseGateEvidence(
            gate_id="source_authority",
            status="passed",
            evidence_ids="source",  # type: ignore[arg-type]
            evidence_sha256=HASH,
            summary="source evidence",
        )


def test_release_evaluation_rejects_non_string_b6_status() -> None:
    with pytest.raises(MonitoringReleaseGateError, match="b6_status must be a non-empty string"):
        evaluate_monitoring_release(
            _gates(),
            b6_status=123,  # type: ignore[arg-type]
            b6_write_permitted=False,
            b6_migration_ready=False,
            b6_migration_write_permitted=False,
        )


def test_release_decision_rejects_non_boolean_ready_flag() -> None:
    decision = evaluate_monitoring_release(
        _gates(),
        b6_status="pending_review",
        b6_write_permitted=False,
        b6_migration_ready=False,
        b6_migration_write_permitted=False,
    )
    with pytest.raises(MonitoringReleaseGateError, match="release_ready must be boolean"):
        replace(decision, release_ready="false")  # type: ignore[arg-type]


def test_gate_set_rejects_missing_duplicate_and_unknown_items() -> None:
    with pytest.raises(MonitoringReleaseGateError, match="missing required"):
        evaluate_monitoring_release(
            _gates()[:-1],
            b6_status="pending_review",
            b6_write_permitted=False,
            b6_migration_ready=False,
            b6_migration_write_permitted=False,
        )

    duplicate = _gates() + (_gates()[0],)
    with pytest.raises(MonitoringReleaseGateError, match="duplicate"):
        evaluate_monitoring_release(
            duplicate,
            b6_status="pending_review",
            b6_write_permitted=False,
            b6_migration_ready=False,
            b6_migration_write_permitted=False,
        )

    unknown = _gates()[:-1] + (
        MonitoringReleaseGateEvidence(
            gate_id="unexpected_gate",
            status="passed",
            evidence_ids=("unexpected",),
            evidence_sha256=HASH,
            summary="unexpected evidence",
        ),
    )
    with pytest.raises(MonitoringReleaseGateError, match="unknown"):
        evaluate_monitoring_release(
            unknown,
            b6_status="pending_review",
            b6_write_permitted=False,
            b6_migration_ready=False,
            b6_migration_write_permitted=False,
        )


def test_b6_authority_flags_must_be_boolean() -> None:
    with pytest.raises(MonitoringReleaseGateError, match="must be boolean"):
        evaluate_monitoring_release(
            _gates(),
            b6_status="approved",
            b6_write_permitted="false",  # type: ignore[arg-type]
            b6_migration_ready=True,
            b6_migration_write_permitted=True,
        )


def test_b6_payload_adapter_is_read_only_and_strict() -> None:
    pending_payload = {
        "migration_write_permitted": False,
        "gate": {
            "status": "pending_review",
            "write_permitted": False,
            "migration_ready": False,
        },
    }
    decision = evaluate_monitoring_release_from_b6_payload(
        _gates(),
        b6_payload=pending_payload,
    )
    assert decision.status == ReleaseDecisionStatus.BLOCKED
    assert decision.b6_migration_write_permitted is False

    tampered = {
        **pending_payload,
        "migration_write_permitted": "false",
    }
    with pytest.raises(MonitoringReleaseGateError, match="must be boolean"):
        evaluate_monitoring_release_from_b6_payload(_gates(), b6_payload=tampered)
