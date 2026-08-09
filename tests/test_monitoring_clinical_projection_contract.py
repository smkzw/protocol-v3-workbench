from __future__ import annotations

import pytest

from services.api.app.monitoring_clinical_event_contract import (
    ClinicalDatePrecision,
    ClinicalDomain,
    ClinicalEventContractError,
    ClinicalEventKind,
    ClinicalEvidenceRef,
    ClinicalRuleBinding,
    ClinicalValueStatus,
    MonitoringClinicalEvent,
    MonitoringClinicalObservation,
)
from services.api.app.monitoring_clinical_projection_contract import (
    ClinicalPopulationMembership,
    ClinicalPopulationScope,
    ClinicalProjectionContractError,
    ClinicalSubjectProfileProjection,
    ClinicalObservationProjection,
    ClinicalTimelineProjection,
    ClinicalVisitKind,
    MonitoringClinicalProjectionContext,
    MonitoringClinicalProjectionScope,
    MonitoringClinicalReadModel,
    project_monitoring_clinical_read_model,
)


def _evidence(evidence_id: str, sheet: str) -> ClinicalEvidenceRef:
    return ClinicalEvidenceRef(
        evidence_id=evidence_id,
        source_binding_id="listing-v1",
        source_revision="listing-rev-1",
        locator_kind="sheet_row",
        locator=f"listing:study:sheet:{sheet}:row:{evidence_id[-3:]}",
    )


def _event(
    event_id: str,
    domain: ClinicalDomain,
    evidence_id: str,
    *,
    date: str,
    precision: ClinicalDatePrecision,
    subject_id: str = "subject-001",
    site_id: str = "site-001",
    raw_value: str = "value",
    observation_domain: ClinicalDomain | None = None,
    risk_instance_ids: tuple[str, ...] = (),
    with_rule: bool = False,
) -> MonitoringClinicalEvent:
    evidence = _evidence(evidence_id, domain.value.upper())
    observation = MonitoringClinicalObservation(
        observation_id=f"observation-{event_id}",
        event_id=event_id,
        domain=observation_domain or domain,
        field_name="VALUE",
        value_status=ClinicalValueStatus.PRESENT,
        raw_value=raw_value,
        normalized_value=raw_value,
        unit="unit",
        evidence_ids=(evidence_id,),
        rule_binding_ids=(f"rule-binding-{event_id}",) if with_rule else (),
    )
    rules = (
        ClinicalRuleBinding(
            binding_id=f"rule-binding-{event_id}",
            rule_id="lab-or-ae-threshold",
            rule_revision="rules-v1",
            threshold_code="threshold",
            threshold_value="3",
            threshold_unit="grade",
            evidence_ids=(evidence_id,),
        ),
    ) if with_rule else ()
    return MonitoringClinicalEvent(
        event_id=event_id,
        project_id="project-demo",
        trial_id="trial-demo",
        site_id=site_id,
        subject_id=subject_id,
        domain=domain,
        event_kind=ClinicalEventKind.OBSERVATION,
        source_binding_id="listing-v1",
        source_revision="listing-rev-1",
        source_sheet=domain.value.upper(),
        source_row=int(event_id[-1], 36) if event_id[-1].isalnum() else 1,
        source_record_id=f"{domain.value.upper()}:row:{event_id[-1]}",
        event_date=date,
        date_precision=precision,
        date_raw=date,
        visit_label="计划外访视" if domain == ClinicalDomain.LAB else "Week 4",
        visit_number=None if domain == ClinicalDomain.LAB else 4,
        risk_instance_ids=risk_instance_ids,
        evidence=(evidence,),
        rule_bindings=rules,
        observations=(observation,),
    )


def _context(
    event: MonitoringClinicalEvent,
    *,
    membership: ClinicalPopulationMembership = ClinicalPopulationMembership.RANDOMIZED,
    visit_kind: ClinicalVisitKind = ClinicalVisitKind.PLANNED,
) -> MonitoringClinicalProjectionContext:
    evidence_ids = (event.evidence[0].evidence_id,)
    return MonitoringClinicalProjectionContext(
        event=event,
        population_membership=membership,
        visit_kind=visit_kind,
        population_evidence_ids=evidence_ids,
        visit_evidence_ids=evidence_ids,
    )


def _scope(**overrides: object) -> MonitoringClinicalProjectionScope:
    values: dict[str, object] = {
        "project_id": "project-demo",
        "trial_id": "trial-demo",
        "population_scope": ClinicalPopulationScope.ALL_SUBJECTS,
        "include_unplanned": True,
    }
    values.update(overrides)
    return MonitoringClinicalProjectionScope(**values)


@pytest.fixture()
def contexts() -> tuple[MonitoringClinicalProjectionContext, ...]:
    ae = _event(
        "event-ae-001",
        ClinicalDomain.AE,
        "evidence-ae-001",
        date="2026-04-12",
        precision=ClinicalDatePrecision.DAY,
        risk_instance_ids=("risk-001",),
        with_rule=True,
    )
    lab = _event(
        "event-lab-002",
        ClinicalDomain.LAB,
        "evidence-lab-002",
        date="2026-04",
        precision=ClinicalDatePrecision.MONTH,
        subject_id="subject-002",
        raw_value="12.5",
        risk_instance_ids=("risk-001", "risk-002"),
    )
    return (
        _context(ae),
        _context(lab, membership=ClinicalPopulationMembership.NOT_RANDOMIZED, visit_kind=ClinicalVisitKind.UNPLANNED),
    )


def test_projection_conserves_event_observation_and_risk_identity(
    contexts: tuple[MonitoringClinicalProjectionContext, ...],
) -> None:
    model = project_monitoring_clinical_read_model(contexts, _scope())

    assert [item.event_id for item in model.timeline] == ["event-lab-002", "event-ae-001"]
    assert len(model.observations) == 2
    assert model.project_rollup.event_ids == ("event-ae-001", "event-lab-002")
    assert model.project_rollup.observation_ids == (
        "observation-event-ae-001",
        "observation-event-lab-002",
    )
    assert model.project_rollup.risk_instance_ids == ("risk-001", "risk-002")
    assert model.timeline[1].evidence_locators == ("listing:study:sheet:AE:row:001",)
    assert model.timeline[1].rule_bindings[0].threshold_code == "threshold"
    assert model.observations[0].evidence_locators == ("listing:study:sheet:LAB:row:002",)
    assert [item.identity for item in model.site_rollups] == ["site-001"]
    assert [item.subject_id for item in model.subject_profiles] == [
        "subject-001",
        "subject-002",
    ]
    assert model.limitations == ()


def test_projection_excludes_unplanned_only_when_visit_kind_is_explicit(
    contexts: tuple[MonitoringClinicalProjectionContext, ...],
) -> None:
    model = project_monitoring_clinical_read_model(
        contexts,
        _scope(include_unplanned=False),
    )

    assert [item.event_id for item in model.timeline] == ["event-ae-001"]
    assert model.project_rollup.risk_instance_ids == ("risk-001",)

    unknown_visit = MonitoringClinicalProjectionContext(
        event=contexts[0].event,
        population_membership=ClinicalPopulationMembership.RANDOMIZED,
        visit_kind=ClinicalVisitKind.UNKNOWN,
        population_evidence_ids=("evidence-ae-001",),
    )
    with pytest.raises(ClinicalProjectionContractError, match="visit kind"):
        project_monitoring_clinical_read_model((unknown_visit,), _scope(include_unplanned=False))


def test_population_scope_is_explicit_and_never_inferred_from_risk(
    contexts: tuple[MonitoringClinicalProjectionContext, ...],
) -> None:
    randomized = project_monitoring_clinical_read_model(
        contexts,
        _scope(population_scope=ClinicalPopulationScope.RANDOMIZED_ONLY),
    )
    assert [item.subject_id for item in randomized.subject_profiles] == ["subject-001"]

    allowlist = project_monitoring_clinical_read_model(
        contexts,
        _scope(
            population_scope=ClinicalPopulationScope.ALLOWLIST,
            subject_ids=("subject-002",),
        ),
    )
    assert [item.subject_id for item in allowlist.subject_profiles] == ["subject-002"]

    unknown_membership = MonitoringClinicalProjectionContext(
        event=contexts[0].event,
        population_membership=ClinicalPopulationMembership.UNKNOWN,
        visit_kind=ClinicalVisitKind.PLANNED,
        visit_evidence_ids=("evidence-ae-001",),
    )
    with pytest.raises(ClinicalProjectionContractError, match="population membership"):
        project_monitoring_clinical_read_model(
            (unknown_membership,),
            _scope(population_scope=ClinicalPopulationScope.RANDOMIZED_ONLY),
        )


def test_observation_cards_are_limited_to_explicit_safety_domains() -> None:
    medical_history = _event(
        "event-mh-001",
        ClinicalDomain.MH,
        "evidence-mh-001",
        date="2026-03-01",
        precision=ClinicalDatePrecision.DAY,
    )
    model = project_monitoring_clinical_read_model((_context(medical_history),), _scope())

    assert len(model.timeline) == 1
    assert model.timeline[0].domain == ClinicalDomain.MH
    assert model.observations == ()
    assert model.project_rollup.domain_counts == {"mh": 1}


def test_subject_profile_rejects_boolean_domain_counts() -> None:
    with pytest.raises(ClinicalProjectionContractError, match="domain_counts"):
        ClinicalSubjectProfileProjection(
            subject_id="subject-001",
            site_id="site-001",
            event_ids=(),
            observation_ids=(),
            risk_instance_ids=(),
            domain_counts={"ae": True},
            incomplete_event_ids=(),
            uncertain_event_ids=(),
        )


def test_round_trip_and_hash_are_deterministic(
    contexts: tuple[MonitoringClinicalProjectionContext, ...],
) -> None:
    model = project_monitoring_clinical_read_model(contexts, _scope())
    payload = model.to_dict()
    restored = MonitoringClinicalReadModel.from_dict(payload)

    assert restored.to_dict() == payload
    assert restored.read_model_sha256 == model.read_model_sha256
    assert MonitoringClinicalProjectionScope.from_dict(payload["scope"]).scope_sha256 == model.scope.scope_sha256

    payload["timeline"][0]["event_sha256"] = "f" * 64
    with pytest.raises(ClinicalProjectionContractError, match="read_model_sha256"):
        MonitoringClinicalReadModel.from_dict(payload)


def test_duplicate_identical_context_is_idempotent_but_conflicting_context_fails(
    contexts: tuple[MonitoringClinicalProjectionContext, ...],
) -> None:
    model = project_monitoring_clinical_read_model(
        (contexts[0], contexts[0], contexts[1]),
        _scope(),
    )
    assert len(model.timeline) == 2

    conflicting = _context(contexts[0].event, visit_kind=ClinicalVisitKind.UNPLANNED)
    with pytest.raises(ClinicalProjectionContractError, match="context conflict"):
        project_monitoring_clinical_read_model((contexts[0], conflicting), _scope())


def test_projection_rejects_observation_reuse_and_subject_site_drift(
    contexts: tuple[MonitoringClinicalProjectionContext, ...],
) -> None:
    duplicate_payload = contexts[1].event.to_dict()
    duplicate_payload["observations"][0]["observation_id"] = (
        contexts[0].event.observations[0].observation_id
    )
    duplicate_payload.pop("event_sha256")
    duplicate_event = MonitoringClinicalEvent.from_dict(duplicate_payload)
    with pytest.raises(ClinicalProjectionContractError, match="observation_id is reused"):
        project_monitoring_clinical_read_model(
            (contexts[0], _context(duplicate_event, membership=ClinicalPopulationMembership.NOT_RANDOMIZED, visit_kind=ClinicalVisitKind.UNPLANNED)),
            _scope(),
        )

    site_drift_payload = contexts[0].event.to_dict()
    site_drift_payload["event_id"] = "event-ae-site-drift"
    site_drift_payload["site_id"] = "site-999"
    site_drift_payload["observations"][0]["observation_id"] = "observation-site-drift"
    site_drift_payload["observations"][0]["event_id"] = "event-ae-site-drift"
    site_drift_payload.pop("event_sha256")
    site_drift_event = MonitoringClinicalEvent.from_dict(site_drift_payload)
    with pytest.raises(ClinicalProjectionContractError, match="multiple sites"):
        project_monitoring_clinical_read_model(
            (contexts[0], _context(site_drift_event)),
            _scope(),
        )


def test_projection_rejects_mixed_projects_and_tampered_scope() -> None:
    event = _event(
        "event-ae-003",
        ClinicalDomain.AE,
        "evidence-ae-003",
        date="2026-05-01",
        precision=ClinicalDatePrecision.DAY,
    )
    mixed_payload = event.to_dict()
    mixed_payload["event_id"] = "event-ae-004"
    mixed_payload["project_id"] = "project-other"
    mixed_payload["observations"][0]["event_id"] = "event-ae-004"
    mixed_payload.pop("event_sha256")
    mixed = MonitoringClinicalEvent.from_dict(mixed_payload)
    with pytest.raises(ClinicalProjectionContractError, match="project or trial"):
        project_monitoring_clinical_read_model((_context(event), _context(mixed)), _scope())

    payload = _scope().to_dict()
    payload["scope_sha256"] = "f" * 64
    with pytest.raises(ClinicalProjectionContractError, match="scope_sha256"):
        MonitoringClinicalProjectionScope.from_dict(payload)


@pytest.mark.parametrize(
    "declared_hash",
    [
        123,
        "F" * 64,
        "f" * 64 + " ",
        " " + "f" * 64,
        "g" * 64,
        "f" * 63,
    ],
)
def test_optional_projection_hashes_reject_coercion(
    contexts: tuple[MonitoringClinicalProjectionContext, ...],
    declared_hash: object,
) -> None:
    scope_payload = _scope().to_dict()
    scope_payload["scope_sha256"] = declared_hash
    with pytest.raises(ClinicalProjectionContractError, match="lowercase SHA-256"):
        MonitoringClinicalProjectionScope.from_dict(scope_payload)

    context_payload = _context(contexts[0].event).to_dict()
    context_payload["context_sha256"] = declared_hash
    with pytest.raises(ClinicalProjectionContractError, match="lowercase SHA-256"):
        MonitoringClinicalProjectionContext.from_dict(context_payload)

    read_model_payload = project_monitoring_clinical_read_model(contexts, _scope()).to_dict()
    read_model_payload["read_model_sha256"] = declared_hash
    with pytest.raises(ClinicalProjectionContractError, match="lowercase SHA-256"):
        MonitoringClinicalReadModel.from_dict(read_model_payload)


def test_missing_or_empty_projection_hashes_remain_compatible(
    contexts: tuple[MonitoringClinicalProjectionContext, ...],
) -> None:
    scope_payload = _scope().to_dict()
    scope_expected = scope_payload["scope_sha256"]
    scope_payload.pop("scope_sha256")
    assert MonitoringClinicalProjectionScope.from_dict(scope_payload).scope_sha256 == scope_expected

    context_payload = _context(contexts[0].event).to_dict()
    context_expected = context_payload["context_sha256"]
    context_payload["context_sha256"] = ""
    assert MonitoringClinicalProjectionContext.from_dict(context_payload).context_sha256 == context_expected

    model_payload = project_monitoring_clinical_read_model(contexts, _scope()).to_dict()
    model_expected = model_payload["read_model_sha256"]
    model_payload.pop("read_model_sha256")
    assert MonitoringClinicalReadModel.from_dict(model_payload).read_model_sha256 == model_expected


@pytest.mark.parametrize(
    "declared_hash",
    [
        123,
        "F" * 64,
        "f" * 64 + " ",
        " " + "f" * 64,
        "g" * 64,
        "f" * 63,
    ],
)
def test_projection_event_hash_fields_are_exact_lowercase(
    contexts: tuple[MonitoringClinicalProjectionContext, ...],
    declared_hash: object,
) -> None:
    model_payload = project_monitoring_clinical_read_model(contexts, _scope()).to_dict()
    for collection_name in ("timeline", "observations"):
        payload = model_payload[collection_name][0]
        payload["event_sha256"] = declared_hash
        with pytest.raises(ClinicalProjectionContractError, match="lowercase SHA-256"):
            if collection_name == "timeline":
                ClinicalTimelineProjection.from_dict(payload)
            else:
                ClinicalObservationProjection.from_dict(payload)


def test_context_requires_evidence_for_known_classifications() -> None:
    event = _event(
        "event-ae-005",
        ClinicalDomain.AE,
        "evidence-ae-005",
        date="2026-05-02",
        precision=ClinicalDatePrecision.DAY,
    )
    with pytest.raises(ClinicalProjectionContractError, match="population evidence"):
        MonitoringClinicalProjectionContext(
            event=event,
            population_membership=ClinicalPopulationMembership.RANDOMIZED,
            visit_kind=ClinicalVisitKind.UNKNOWN,
        )
    with pytest.raises(ClinicalProjectionContractError, match="visit evidence"):
        MonitoringClinicalProjectionContext(
            event=event,
            population_membership=ClinicalPopulationMembership.UNKNOWN,
            visit_kind=ClinicalVisitKind.PLANNED,
        )
    with pytest.raises(ClinicalProjectionContractError, match="declared by the event"):
        MonitoringClinicalProjectionContext(
            event=event,
            population_membership=ClinicalPopulationMembership.RANDOMIZED,
            visit_kind=ClinicalVisitKind.PLANNED,
            population_evidence_ids=("evidence-unknown",),
            visit_evidence_ids=("evidence-ae-005",),
        )


def test_free_text_cannot_create_risk_or_treatment_links() -> None:
    event = _event(
        "event-ae-006",
        ClinicalDomain.AE,
        "evidence-ae-006",
        date="2026-05-03",
        precision=ClinicalDatePrecision.DAY,
        raw_value="CM and IP are mentioned in raw text",
        risk_instance_ids=(),
    )
    model = project_monitoring_clinical_read_model((_context(event),), _scope())

    assert model.timeline[0].risk_instance_ids == ()
    assert model.observations[0].risk_instance_ids == ()


def test_scope_and_payload_malformed_inputs_fail_closed() -> None:
    with pytest.raises(ClinicalProjectionContractError, match="allowlist"):
        _scope(population_scope=ClinicalPopulationScope.ALLOWLIST)
    with pytest.raises(ClinicalProjectionContractError, match="scope must be an object"):
        MonitoringClinicalProjectionScope.from_dict([])
    with pytest.raises(ClinicalProjectionContractError, match="contexts must be a list"):
        project_monitoring_clinical_read_model("bad", _scope())


def test_projection_does_not_accept_inconsistent_c4_observation_domain() -> None:
    # C4 rejects this before a projection can be built; this protects the
    # projection from becoming a second interpretation of an event.
    with pytest.raises(ClinicalEventContractError, match="observation domain"):
        _event(
            "event-ae-007",
            ClinicalDomain.AE,
            "evidence-ae-007",
            date="2026-05-04",
            precision=ClinicalDatePrecision.DAY,
            observation_domain=ClinicalDomain.LAB,
        )
