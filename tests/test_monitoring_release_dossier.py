from __future__ import annotations

import pytest

from services.api.app.monitoring_release_dossier import (
    REQUIRED_DOSSIER_CONTROLS,
    REQUIRED_DOSSIER_SECTION_IDS,
    REQUIRED_DOSSIER_SIGNOFF_ROLES,
    MonitoringReleaseDossier,
    MonitoringReleaseDossierError,
    MonitoringReleaseDossierSection,
    MonitoringReleaseDossierSignoff,
    MonitoringResidualRiskDisposition,
    ReleaseDossierSectionStatus,
    ResidualRiskSeverity,
    ResidualRiskStatus,
    bind_release_dossier_evidence,
    release_dossier_gate_evidence,
)
from services.api.app.monitoring_release_gate import (
    REQUIRED_RELEASE_GATE_IDS,
    MonitoringReleaseGateEvidence,
    ReleaseEvidenceStatus,
    ReleaseDecisionStatus,
    evaluate_monitoring_release,
)


HASH = "a" * 64
NOW = "2026-08-02T22:00:00+08:00"


def _section(
    section_id: str,
    *,
    status: ReleaseDossierSectionStatus = ReleaseDossierSectionStatus.PASSED,
    covered: tuple[str, ...] | None = None,
):
    controls = REQUIRED_DOSSIER_CONTROLS[section_id]
    covered = (
        controls
        if covered is None and status == ReleaseDossierSectionStatus.PASSED
        else controls[:1]
        if covered is None
        else covered
    )
    unmet = tuple(control for control in controls if control not in covered)
    return MonitoringReleaseDossierSection(
        section_id=section_id,
        status=status,
        evidence_ids=(f"evidence-{section_id}",),
        evidence_sha256=HASH,
        covered_control_ids=covered,
        unmet_control_ids=unmet,
        summary=f"evidence for {section_id}",
    )


def _signoffs():
    return tuple(
        MonitoringReleaseDossierSignoff(
            role=role,
            actor_id=f"actor-{role}",
            signed_at=NOW,
            evidence_sha256=HASH,
        )
        for role in REQUIRED_DOSSIER_SIGNOFF_ROLES
    )


def _dossier(
    *,
    section_status: ReleaseDossierSectionStatus = ReleaseDossierSectionStatus.PASSED,
    residual_risks: tuple[MonitoringResidualRiskDisposition, ...] = (),
):
    return MonitoringReleaseDossier(
        dossier_id="dossier-v1",
        release_version="release-2026.08.02",
        generated_at=NOW,
        sections=tuple(
            _section(section_id, status=section_status)
            for section_id in REQUIRED_DOSSIER_SECTION_IDS
        ),
        signoffs=_signoffs(),
        residual_risks=residual_risks,
    )


def _generic_gates(*, commercial: MonitoringReleaseGateEvidence | None = None):
    rows = []
    for gate_id in REQUIRED_RELEASE_GATE_IDS:
        if gate_id == "commercial_release_dossier" and commercial is not None:
            rows.append(commercial)
        elif gate_id != "commercial_release_dossier":
            rows.append(
                MonitoringReleaseGateEvidence(
                    gate_id=gate_id,
                    status=ReleaseEvidenceStatus.PASSED,
                    evidence_ids=(f"evidence-{gate_id}",),
                    evidence_sha256=HASH,
                    summary=f"evidence for {gate_id}",
                )
            )
    return tuple(rows)


def test_complete_dossier_is_hash_bound_and_can_feed_the_existing_gate():
    dossier = _dossier(
        residual_risks=(
            MonitoringResidualRiskDisposition(
                risk_id="risk-p2-001",
                severity=ResidualRiskSeverity.P2,
                status=ResidualRiskStatus.ACCEPTED,
                owner_id="owner-medical",
                decision_evidence_sha256=HASH,
                rationale="Accepted with monitoring and a documented follow-up owner.",
            ),
        )
    )
    assert dossier.status == ReleaseDossierSectionStatus.PASSED
    assert dossier.release_ready is True
    assert dossier.authority_granted is False
    assert len(dossier.dossier_sha256) == 64
    gate = release_dossier_gate_evidence(dossier)
    assert gate.status == ReleaseEvidenceStatus.PASSED
    bound = bind_release_dossier_evidence(_generic_gates(), dossier)
    decision = evaluate_monitoring_release(
        bound,
        b6_status="approved",
        b6_write_permitted=True,
        b6_migration_ready=True,
        b6_migration_write_permitted=True,
    )
    assert decision.status == ReleaseDecisionStatus.READY
    assert decision.release_ready is True


def test_partial_dossier_is_not_ready_and_exposes_unmet_controls():
    dossier = _dossier(
        section_status=ReleaseDossierSectionStatus.PARTIAL,
    )
    assert dossier.release_ready is False
    assert dossier.status == ReleaseDossierSectionStatus.PARTIAL
    assert "section:functional_validation:partial" in dossier.blocking_reasons
    assert (
        "control:functional_validation:browser_scientific_acceptance"
        in dossier.blocking_reasons
    )
    assert (
        release_dossier_gate_evidence(dossier).status == ReleaseEvidenceStatus.PARTIAL
    )


def test_all_unproven_sections_preserve_unproven_gate_status():
    dossier = _dossier(section_status=ReleaseDossierSectionStatus.UNPROVEN)
    assert dossier.status == ReleaseDossierSectionStatus.UNPROVEN
    assert dossier.release_ready is False
    assert (
        release_dossier_gate_evidence(dossier).status == ReleaseEvidenceStatus.UNPROVEN
    )


def test_deferred_or_unmitigated_p0_p1_residual_risk_blocks_release():
    deferred = MonitoringResidualRiskDisposition(
        risk_id="risk-p2-deferred",
        severity=ResidualRiskSeverity.P2,
        status=ResidualRiskStatus.DEFERRED,
        owner_id="owner-engineering",
        decision_evidence_sha256=HASH,
        rationale="Deferred pending a controlled remediation window.",
    )
    p1_accepted = MonitoringResidualRiskDisposition(
        risk_id="risk-p1-accepted",
        severity=ResidualRiskSeverity.P1,
        status=ResidualRiskStatus.ACCEPTED,
        owner_id="owner-release",
        decision_evidence_sha256=HASH,
        rationale="Temporary acceptance is documented but not a release closure.",
    )
    for risk in (deferred, p1_accepted):
        dossier = _dossier(residual_risks=(risk,))
        assert dossier.release_ready is False
        assert (
            f"residual_risk:{risk.risk_id}:{risk.status.value}"
            in dossier.blocking_reasons
        )
        assert (
            release_dossier_gate_evidence(dossier).status
            == ReleaseEvidenceStatus.BLOCKED
        )


def test_control_partition_and_required_identity_are_fail_closed():
    with pytest.raises(MonitoringReleaseDossierError, match="control partition"):
        MonitoringReleaseDossierSection(
            section_id="functional_validation",
            status="partial",
            evidence_ids=("evidence",),
            evidence_sha256=HASH,
            covered_control_ids=("real_project_e2e",),
            unmet_control_ids=(),
            summary="missing explicit remainder",
        )

    with pytest.raises(MonitoringReleaseDossierError, match="timezone"):
        MonitoringReleaseDossierSignoff(
            role="engineering",
            actor_id="actor-engineering",
            signed_at="2026-08-02T22:00:00",
            evidence_sha256=HASH,
        )

    with pytest.raises(MonitoringReleaseDossierError, match="string identifier"):
        MonitoringReleaseDossier(
            dossier_id=123,  # type: ignore[arg-type]
            release_version="release-2026.08.02",
            generated_at=NOW,
            sections=_dossier().sections,
            signoffs=_signoffs(),
        )

    with pytest.raises(MonitoringReleaseDossierError, match="string SHA-256"):
        MonitoringReleaseDossierSignoff(
            role="engineering",
            actor_id="actor-engineering",
            signed_at=NOW,
            evidence_sha256=123,  # type: ignore[arg-type]
        )

    sections = list(_dossier().sections)
    sections[-1], sections[-2] = sections[-2], sections[-1]
    with pytest.raises(MonitoringReleaseDossierError, match="canonical order"):
        MonitoringReleaseDossier(
            dossier_id="dossier-v1",
            release_version="release-2026.08.02",
            generated_at=NOW,
            sections=tuple(sections),
            signoffs=_signoffs(),
        )


@pytest.mark.parametrize("malformed", [f" {HASH}", HASH.upper(), 123])
def test_dossier_evidence_hash_shape_is_not_coerced(malformed: object) -> None:
    controls = REQUIRED_DOSSIER_CONTROLS["functional_validation"]
    with pytest.raises(
        MonitoringReleaseDossierError,
        match="string SHA-256",
    ):
        MonitoringReleaseDossierSection(
            section_id="functional_validation",
            status=ReleaseDossierSectionStatus.PASSED,
            evidence_ids=("evidence-functional",),
            evidence_sha256=malformed,
            covered_control_ids=controls,
            unmet_control_ids=(),
            summary="functional evidence",
        )


def test_stale_commercial_gate_cannot_be_silently_rebound():
    dossier = _dossier()
    stale = MonitoringReleaseGateEvidence(
        gate_id="commercial_release_dossier",
        status=ReleaseEvidenceStatus.PASSED,
        evidence_ids=("commercial-dossier:old",),
        evidence_sha256=HASH,
        summary="stale commercial dossier",
    )
    with pytest.raises(MonitoringReleaseDossierError, match="does not match"):
        bind_release_dossier_evidence(_generic_gates(commercial=stale), dossier)


def test_dossier_rows_reject_duplicate_gate_and_authority_flag():
    dossier = _dossier()
    gate = release_dossier_gate_evidence(dossier)
    with pytest.raises(MonitoringReleaseDossierError, match="must not repeat"):
        bind_release_dossier_evidence((gate, gate), dossier)
    with pytest.raises(MonitoringReleaseDossierError, match="cannot grant authority"):
        MonitoringReleaseDossier(
            dossier_id="dossier-v2",
            release_version="release-2026.08.02",
            generated_at=NOW,
            sections=_dossier().sections,
            signoffs=_signoffs(),
            authority_granted=True,
        )
