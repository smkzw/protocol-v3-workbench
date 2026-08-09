from __future__ import annotations

from dataclasses import replace

import pytest

from services.api.app.monitoring_clinical_event_contract import (
    ClinicalDatePrecision,
    ClinicalDomain,
    ClinicalEventKind,
    ClinicalEvidenceRef,
    ClinicalRuleBinding,
    ClinicalValueStatus,
    MonitoringClinicalEvent,
    MonitoringClinicalObservation,
)
from services.api.app.monitoring_clinical_consumer_handoff import (
    ClinicalConsumerHandoff,
    ClinicalConsumerHandoffError,
    build_clinical_consumer_handoff,
)
from services.api.app.monitoring_clinical_projection_contract import (
    ClinicalPopulationMembership,
    ClinicalProjectionContractError,
    ClinicalVisitKind,
    MonitoringClinicalProjectionContext,
    MonitoringClinicalProjectionScope,
    MonitoringClinicalReadModel,
    project_monitoring_clinical_read_model,
)


def _event(
    event_id: str,
    domain: ClinicalDomain,
    evidence_id: str,
    *,
    event_date: str,
    precision: ClinicalDatePrecision,
    subject_id: str = "subject-001",
    risk_ids: tuple[str, ...] = (),
    with_rule: bool = False,
    evidence: bool = True,
) -> MonitoringClinicalEvent:
    evidence_ref = ClinicalEvidenceRef(
        evidence_id=evidence_id,
        source_binding_id="listing-v1",
        source_revision="listing-rev-1",
        locator_kind="sheet_row",
        locator=f"listing:study:sheet:{domain.value.upper()}:row:{event_id[-3:]}",
    )
    rule_id = f"rule-binding-{event_id}"
    observation = MonitoringClinicalObservation(
        observation_id=f"observation-{event_id}",
        event_id=event_id,
        domain=domain,
        field_name="VALUE",
        value_status=ClinicalValueStatus.PRESENT,
        raw_value="CM and IP are mentioned but not linked" if not risk_ids else "12.5",
        normalized_value="12.5" if risk_ids else "CM and IP are mentioned but not linked",
        unit="unit",
        evidence_ids=(evidence_id,) if evidence else (),
        rule_binding_ids=(rule_id,) if with_rule else (),
    )
    return MonitoringClinicalEvent(
        event_id=event_id,
        project_id="project-demo",
        trial_id="trial-demo",
        site_id="site-001",
        subject_id=subject_id,
        domain=domain,
        event_kind=ClinicalEventKind.OBSERVATION,
        source_binding_id="listing-v1",
        source_revision="listing-rev-1",
        source_sheet=domain.value.upper(),
        source_row=1,
        source_record_id=f"{domain.value.upper()}:row:1",
        event_date=event_date,
        date_precision=precision,
        date_raw=event_date,
        visit_label="计划外访视" if precision == ClinicalDatePrecision.MONTH else "Week 4",
        visit_number=None if precision == ClinicalDatePrecision.MONTH else 4,
        risk_instance_ids=risk_ids,
        evidence=(evidence_ref,) if evidence else (),
        rule_bindings=(
            ClinicalRuleBinding(
                binding_id=rule_id,
                rule_id="threshold-rule",
                rule_revision="rules-v1",
                threshold_code="ctcae_grade",
                threshold_value="3",
                threshold_unit="grade",
                evidence_ids=(evidence_id,),
            ),
        ) if with_rule else (),
        observations=(observation,),
    )


def _context(
    event: MonitoringClinicalEvent,
    *,
    membership: ClinicalPopulationMembership = ClinicalPopulationMembership.RANDOMIZED,
    visit_kind: ClinicalVisitKind = ClinicalVisitKind.PLANNED,
) -> MonitoringClinicalProjectionContext:
    evidence_ids = (event.evidence[0].evidence_id,) if event.evidence else ()
    return MonitoringClinicalProjectionContext(
        event=event,
        population_membership=membership,
        visit_kind=visit_kind,
        population_evidence_ids=evidence_ids,
        visit_evidence_ids=evidence_ids,
    )


def _model(
    *,
    include_unplanned: bool = True,
    missing_evidence: bool = False,
) -> MonitoringClinicalReadModel:
    ae = _event(
        "event-ae-001",
        ClinicalDomain.AE,
        "evidence-ae-001",
        event_date="2026-04-12",
        precision=ClinicalDatePrecision.DAY,
        risk_ids=("risk-001",),
        with_rule=True,
    )
    lab = _event(
        "event-lab-002",
        ClinicalDomain.LAB,
        "evidence-lab-002",
        event_date="2026-04",
        precision=ClinicalDatePrecision.MONTH,
        subject_id="subject-002",
        risk_ids=("risk-001", "risk-002"),
    )
    if missing_evidence:
        lab = _event(
            "event-lab-002",
            ClinicalDomain.LAB,
            "evidence-lab-002",
            event_date="2026-04",
            precision=ClinicalDatePrecision.MONTH,
            subject_id="subject-002",
            evidence=False,
        )
    scope = MonitoringClinicalProjectionScope(
        project_id="project-demo",
        trial_id="trial-demo",
        include_unplanned=include_unplanned,
    )
    return project_monitoring_clinical_read_model(
        (
            _context(ae),
            _context(
                lab,
                membership=(
                    ClinicalPopulationMembership.UNKNOWN
                    if missing_evidence
                    else ClinicalPopulationMembership.NOT_RANDOMIZED
                ),
                visit_kind=(
                    ClinicalVisitKind.UNKNOWN
                    if missing_evidence
                    else ClinicalVisitKind.UNPLANNED
                ),
            ),
        ),
        scope,
    )


def test_handoff_preserves_timeline_profile_metric_and_risk_identity() -> None:
    handoff = build_clinical_consumer_handoff(_model())

    assert [item.event_type for item in handoff.timeline] == ["lab", "adverse_event"]
    assert handoff.timeline[0].is_unscheduled is True
    assert handoff.timeline[1].event_sha256
    assert handoff.timeline[1].evidence_locators == (
        "listing:study:sheet:AE:row:001",
    )
    assert [item.metric_key for item in handoff.safety_metrics] == ["ae:VALUE", "lab:VALUE"]
    assert handoff.safety_metrics[0].points[0].event_id == "event-ae-001"
    assert handoff.safety_metrics[0].points[0].rule_binding_ids == (
        "rule-binding-event-ae-001",
    )
    risk_one = next(item for item in handoff.risk_drilldown if item.risk_instance_id == "risk-001")
    assert risk_one.event_ids == ("event-ae-001", "event-lab-002")
    assert risk_one.observation_ids == (
        "observation-event-ae-001",
        "observation-event-lab-002",
    )
    assert risk_one.evidence_locators == (
        "listing:study:sheet:AE:row:001",
        "listing:study:sheet:LAB:row:002",
    )
    assert [item.subject_id for item in handoff.subjects] == ["subject-001", "subject-002"]
    assert handoff.project_rollup.event_ids == ("event-ae-001", "event-lab-002")


def test_handoff_round_trip_hash_and_source_tamper_fail_closed() -> None:
    handoff = build_clinical_consumer_handoff(_model())
    payload = handoff.to_dict()
    restored = ClinicalConsumerHandoff.from_dict(payload)

    assert restored.to_dict() == payload
    assert restored.handoff_sha256 == handoff.handoff_sha256

    payload["timeline"][0]["evidence_locators"] = ["tampered:locator"]
    with pytest.raises(ClinicalConsumerHandoffError, match="handoff_sha256"):
        ClinicalConsumerHandoff.from_dict(payload)


@pytest.mark.parametrize(
    "bad_hash",
    (None, 123, " " + ("a" * 64), "A" * 64, "a" * 63, "g" * 64),
)
def test_handoff_rejects_noncanonical_digest_shapes(bad_hash: object) -> None:
    handoff = build_clinical_consumer_handoff(_model())

    scope_payload = handoff.to_dict()
    scope_payload["scope_sha256"] = bad_hash
    with pytest.raises(ClinicalConsumerHandoffError, match="lowercase SHA-256"):
        ClinicalConsumerHandoff.from_dict(scope_payload)

    timeline_payload = handoff.to_dict()
    timeline_payload["timeline"][0]["event_sha256"] = bad_hash
    with pytest.raises(ClinicalConsumerHandoffError, match="lowercase SHA-256"):
        ClinicalConsumerHandoff.from_dict(timeline_payload)

    declared_payload = handoff.to_dict()
    declared_payload["handoff_sha256"] = bad_hash
    with pytest.raises(ClinicalConsumerHandoffError, match="lowercase SHA-256"):
        ClinicalConsumerHandoff.from_dict(declared_payload)


def test_projection_rejects_noncanonical_event_hash_before_handoff_build() -> None:
    model = _model()
    with pytest.raises(ClinicalProjectionContractError, match="lowercase SHA-256"):
        replace(model.timeline[0], event_sha256="A" * 64)


def test_handoff_does_not_create_risk_from_free_text() -> None:
    raw_only = _event(
        "event-ae-text",
        ClinicalDomain.AE,
        "evidence-ae-text",
        event_date="2026-05-01",
        precision=ClinicalDatePrecision.DAY,
    )
    model = project_monitoring_clinical_read_model(
        (_context(raw_only),),
        MonitoringClinicalProjectionScope(project_id="project-demo", trial_id="trial-demo"),
    )
    handoff = build_clinical_consumer_handoff(model)

    assert handoff.risk_drilldown == ()
    assert handoff.safety_metrics[0].points[0].related_risk_ids == ()


def test_handoff_rejects_missing_trace_and_event_hash_mismatch() -> None:
    with pytest.raises(ClinicalConsumerHandoffError, match="lacks source traceability"):
        build_clinical_consumer_handoff(_model(missing_evidence=True))

    model = _model()
    bad_observation = replace(model.observations[0], event_sha256="f" * 64)
    bad_model = MonitoringClinicalReadModel(
        scope=model.scope,
        timeline=model.timeline,
        observations=(bad_observation, *model.observations[1:]),
        subject_profiles=model.subject_profiles,
        site_rollups=model.site_rollups,
        project_rollup=model.project_rollup,
        limitations=model.limitations,
    )
    with pytest.raises(ClinicalConsumerHandoffError, match="event hash"):
        build_clinical_consumer_handoff(bad_model)


def test_handoff_keeps_non_safety_timeline_events_without_metric_guessing() -> None:
    history = _event(
        "event-mh-001",
        ClinicalDomain.MH,
        "evidence-mh-001",
        event_date="2026-03-01",
        precision=ClinicalDatePrecision.DAY,
    )
    model = project_monitoring_clinical_read_model(
        (_context(history),),
        MonitoringClinicalProjectionScope(project_id="project-demo", trial_id="trial-demo"),
    )
    handoff = build_clinical_consumer_handoff(model)

    assert handoff.timeline[0].event_type == "medical_history"
    assert handoff.safety_metrics == ()
    assert handoff.risk_drilldown == ()


def test_handoff_respects_c5_scope_without_reintroducing_unplanned_events() -> None:
    model = _model(include_unplanned=False)
    handoff = build_clinical_consumer_handoff(model)

    assert [item.event_id for item in handoff.timeline] == ["event-ae-001"]
    assert [item.metric_key for item in handoff.safety_metrics] == ["ae:VALUE"]


def test_handoff_canonicalizes_set_backed_indexes_and_is_input_order_invariant() -> None:
    specs = (
        ("event-zed", "subject-shared", "site-zeta", ClinicalDomain.AE, "2026-01-08"),
        ("event-alf", "subject-shared", "site-zeta", ClinicalDomain.LAB, "2026-01-01"),
        ("event-kap", "subject-kappa", "site-kappa", ClinicalDomain.AE, "2026-01-07"),
        ("event-bet", "subject-beta", "site-beta", ClinicalDomain.VITALS, "2026-01-02"),
        ("event-the", "subject-theta", "site-theta", ClinicalDomain.AE, "2026-01-06"),
        ("event-gam", "subject-gamma", "site-gamma", ClinicalDomain.LAB, "2026-01-03"),
        ("event-eps", "subject-epsilon", "site-epsilon", ClinicalDomain.AE, "2026-01-05"),
        ("event-del", "subject-delta", "site-delta", ClinicalDomain.VITALS, "2026-01-04"),
    )
    contexts = tuple(
        _context(
            replace(
                _event(
                    event_id,
                    domain,
                    f"evidence-{event_id}",
                    event_date=event_date,
                    precision=ClinicalDatePrecision.DAY,
                    subject_id=subject_id,
                    risk_ids=("risk-main", "risk-secondary"),
                    with_rule=True,
                ),
                site_id=site_id,
            )
        )
        for event_id, subject_id, site_id, domain, event_date in specs
    )
    scope = MonitoringClinicalProjectionScope(
        project_id="project-demo",
        trial_id="trial-demo",
    )
    first = build_clinical_consumer_handoff(
        project_monitoring_clinical_read_model(contexts, scope)
    )
    second = build_clinical_consumer_handoff(
        project_monitoring_clinical_read_model(tuple(reversed(contexts)), scope)
    )

    assert first.to_dict() == second.to_dict()
    assert first.handoff_sha256 == second.handoff_sha256
    risk = next(item for item in first.risk_drilldown if item.risk_instance_id == "risk-main")
    assert risk.event_ids == tuple(sorted(risk.event_ids))
    assert risk.observation_ids == tuple(sorted(risk.observation_ids))
    assert risk.subject_ids == tuple(sorted(risk.subject_ids))
    assert risk.site_ids == tuple(sorted(risk.site_ids))
    assert risk.rule_binding_ids == tuple(sorted(risk.rule_binding_ids))
    shared = next(item for item in first.subjects if item.subject_id == "subject-shared")
    assert shared.safety_metric_keys == ("ae:VALUE", "lab:VALUE")
