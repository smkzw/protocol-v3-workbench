from __future__ import annotations

from copy import deepcopy

import pytest

from services.api.app.monitoring_clinical_event_contract import (
    ClinicalCompleteness,
    ClinicalCompletenessStatus,
    ClinicalDatePrecision,
    ClinicalDomain,
    ClinicalEventContractError,
    ClinicalEventKind,
    ClinicalEvidenceRef,
    ClinicalRuleBinding,
    ClinicalUncertainty,
    ClinicalUncertaintyState,
    ClinicalValueStatus,
    MonitoringClinicalEvent,
    MonitoringClinicalObservation,
)


def _evidence(
    evidence_id: str = "evidence-ae-001",
    *,
    source_binding_id: str = "listing-v1",
) -> ClinicalEvidenceRef:
    return ClinicalEvidenceRef(
        evidence_id=evidence_id,
        source_binding_id=source_binding_id,
        source_revision="listing-rev-1",
        locator_kind="sheet_row",
        locator=f"listing:study:sheet:AE:row:{evidence_id[-3:]}",
    )


def _rule(
    binding_id: str = "rule-binding-1",
    *,
    evidence_ids: tuple[str, ...] = ("evidence-ae-001",),
) -> ClinicalRuleBinding:
    return ClinicalRuleBinding(
        binding_id=binding_id,
        rule_id="ae-grade-threshold",
        rule_revision="rules-v1",
        threshold_code="ctcae_grade",
        threshold_value=3,
        threshold_unit="grade",
        evidence_ids=evidence_ids,
    )


def _event(**overrides: object) -> MonitoringClinicalEvent:
    defaults: dict[str, object] = {
        "event_id": "event-ae-001",
        "project_id": "project-demo",
        "trial_id": "trial-demo",
        "site_id": "site-001",
        "subject_id": "subject-001",
        "domain": ClinicalDomain.AE,
        "event_kind": ClinicalEventKind.EVENT,
        "source_binding_id": "listing-v1",
        "source_revision": "listing-rev-1",
        "source_sheet": "AE",
        "source_row": 12,
        "source_record_id": "AE:row:12",
        "event_date": "2026-04-12",
        "date_precision": ClinicalDatePrecision.DAY,
        "date_raw": "12APR2026",
        "visit_label": "Week 4",
        "visit_number": 4,
        "ae_ids": ("ae-001",),
        "risk_instance_ids": ("risk-001",),
        "evidence": (_evidence(),),
        "rule_bindings": (),
        "observations": (),
    }
    defaults.update(overrides)
    return MonitoringClinicalEvent(**defaults)


def test_adverse_event_round_trip_preserves_explicit_links_and_hash() -> None:
    observation = MonitoringClinicalObservation(
        observation_id="observation-ae-001",
        event_id="event-ae-001",
        domain=ClinicalDomain.AE,
        field_name="AETERM",
        raw_value="Rash",
        normalized_value="rash",
        evidence_ids=("evidence-ae-001",),
        rule_binding_ids=("rule-binding-1",),
    )
    event = _event(
        cm_ids=("cm-001",),
        finding_ids=("finding-001",),
        rule_bindings=(_rule(),),
        observations=(observation,),
        completeness=ClinicalCompleteness(
            ClinicalCompletenessStatus.COMPLETE,
            source_coverage=("listing-v1",),
        ),
    )

    payload = event.to_dict()
    restored = MonitoringClinicalEvent.from_dict(payload)

    assert payload["event_sha256"] == event.event_sha256
    assert restored.to_dict() == payload
    assert restored.ae_ids == ("ae-001",)
    assert restored.cm_ids == ("cm-001",)
    assert restored.finding_ids == ("finding-001",)
    assert restored.risk_instance_ids == ("risk-001",)
    assert restored.observations[0].normalized_value == "rash"


def test_partial_lab_event_keeps_numeric_zero_and_uncertainty_visible() -> None:
    observation = MonitoringClinicalObservation(
        observation_id="observation-lab-001",
        event_id="event-lab-001",
        domain=ClinicalDomain.LAB,
        field_name="LBSTRESN",
        raw_value=0,
        normalized_value=0,
        reference_range={"low": 0, "high": 5, "comparator": "inclusive"},
        completeness=ClinicalCompleteness(
            ClinicalCompletenessStatus.PARTIAL,
            missing_fields=("unit",),
            source_coverage=("listing-v1",),
        ),
        uncertainty=ClinicalUncertainty(
            ClinicalUncertaintyState.PARTIAL_DATE,
            codes=("date_partial",),
        ),
    )
    event = _event(
        event_id="event-lab-001",
        domain=ClinicalDomain.LAB,
        event_kind=ClinicalEventKind.OBSERVATION,
        source_sheet="LB",
        source_record_id="LB:row:8",
        event_date="2026-04",
        date_precision=ClinicalDatePrecision.MONTH,
        date_raw="APR2026",
        ae_ids=(),
        risk_instance_ids=(),
        observations=(observation,),
        completeness=ClinicalCompleteness(
            ClinicalCompletenessStatus.PARTIAL,
            missing_fields=("unit",),
            source_coverage=("listing-v1",),
        ),
        uncertainty=ClinicalUncertainty(
            ClinicalUncertaintyState.PARTIAL_DATE,
            codes=("date_partial",),
        ),
    )

    assert event.observations[0].raw_value == "0"
    assert event.observations[0].normalized_value == "0"
    assert event.completeness.status == ClinicalCompletenessStatus.PARTIAL
    assert event.uncertainty.state == ClinicalUncertaintyState.PARTIAL_DATE
    assert MonitoringClinicalEvent.from_dict(event.to_dict()).event_sha256 == event.event_sha256


def test_hash_is_order_independent_for_explicit_collections() -> None:
    evidence_one = _evidence("evidence-ae-001")
    evidence_two = _evidence("evidence-ae-002")
    rule_one = _rule("rule-binding-1")
    rule_two = _rule("rule-binding-2", evidence_ids=("evidence-ae-002",))
    observation_one = MonitoringClinicalObservation(
        observation_id="observation-ae-001",
        event_id="event-ae-001",
        domain=ClinicalDomain.AE,
        field_name="AETERM",
        raw_value="Rash",
        evidence_ids=("evidence-ae-001",),
        rule_binding_ids=("rule-binding-1",),
    )
    observation_two = MonitoringClinicalObservation(
        observation_id="observation-ae-002",
        event_id="event-ae-001",
        domain=ClinicalDomain.AE,
        field_name="AESEV",
        raw_value="Severe",
        evidence_ids=("evidence-ae-002",),
        rule_binding_ids=("rule-binding-2",),
    )

    first = _event(
        evidence=(evidence_two, evidence_one),
        rule_bindings=(rule_two, rule_one),
        observations=(observation_two, observation_one),
    )
    second = _event(
        evidence=(evidence_one, evidence_two),
        rule_bindings=(rule_one, rule_two),
        observations=(observation_one, observation_two),
    )

    assert first.event_sha256 == second.event_sha256
    assert first.to_dict() == second.to_dict()


@pytest.mark.parametrize(
    ("date_precision", "event_date"),
    [
        (ClinicalDatePrecision.DAY, "2026-02-30"),
        (ClinicalDatePrecision.MONTH, "2026-13"),
        (ClinicalDatePrecision.UNKNOWN, "2026"),
    ],
)
def test_date_precision_rejects_invalid_or_ambiguous_dates(
    date_precision: ClinicalDatePrecision,
    event_date: str,
) -> None:
    with pytest.raises(ClinicalEventContractError, match="event_date"):
        _event(date_precision=date_precision, event_date=event_date)


@pytest.mark.parametrize("field_name", ["/tmp/AE", "../AE", "AE/../row"])
def test_evidence_and_source_locators_reject_local_paths(field_name: str) -> None:
    with pytest.raises(ClinicalEventContractError, match="local path"):
        ClinicalEvidenceRef(
            evidence_id="evidence-path",
            source_binding_id="listing-v1",
            source_revision="listing-rev-1",
            locator_kind="sheet_row",
            locator=field_name,
        )


@pytest.mark.parametrize(
    ("source_sheet", "source_record_id"),
    [("/tmp/AE", "AE:row:1"), ("AE", "../AE:row:1")],
)
def test_event_source_identity_rejects_local_paths(
    source_sheet: str,
    source_record_id: str,
) -> None:
    with pytest.raises(ClinicalEventContractError, match="local path"):
        _event(source_sheet=source_sheet, source_record_id=source_record_id)


def test_observation_links_are_explicit_and_must_be_declared_by_the_event() -> None:
    wrong_event = MonitoringClinicalObservation(
        observation_id="observation-wrong-event",
        event_id="event-other",
        domain=ClinicalDomain.AE,
        field_name="AETERM",
        raw_value="The text mentions CM and IP, but creates no links",
    )
    with pytest.raises(ClinicalEventContractError, match="event_id"):
        _event(observations=(wrong_event,))

    wrong_domain = MonitoringClinicalObservation(
        observation_id="observation-wrong-domain",
        event_id="event-ae-001",
        domain=ClinicalDomain.LAB,
        field_name="LBTEST",
        raw_value="ALT",
    )
    with pytest.raises(ClinicalEventContractError, match="domain"):
        _event(observations=(wrong_domain,))

    undeclared_evidence = MonitoringClinicalObservation(
        observation_id="observation-undeclared-evidence",
        event_id="event-ae-001",
        domain=ClinicalDomain.AE,
        field_name="AETERM",
        raw_value="Rash",
        evidence_ids=("evidence-unknown",),
    )
    with pytest.raises(ClinicalEventContractError, match="evidence"):
        _event(observations=(undeclared_evidence,))


def test_cm_and_ip_links_cannot_alias_each_other() -> None:
    with pytest.raises(ClinicalEventContractError, match="CM event"):
        _event(domain=ClinicalDomain.CM, cm_ids=("cm-001",), ip_ids=("ip-001",))
    with pytest.raises(ClinicalEventContractError, match="IP event"):
        _event(domain=ClinicalDomain.IP, cm_ids=("cm-001",), ip_ids=("ip-001",))


def test_completeness_and_uncertainty_fail_closed_when_malformed() -> None:
    with pytest.raises(ClinicalEventContractError, match="missing_fields"):
        ClinicalCompleteness(
            ClinicalCompletenessStatus.COMPLETE,
            missing_fields=("unit",),
        )
    with pytest.raises(ClinicalEventContractError, match="missing_fields"):
        ClinicalCompleteness(ClinicalCompletenessStatus.MISSING_REQUIRED)
    with pytest.raises(ClinicalEventContractError, match="codes"):
        ClinicalUncertainty(ClinicalUncertaintyState.NONE, codes=("source_conflict",))
    with pytest.raises(ClinicalEventContractError, match="codes"):
        ClinicalUncertainty(ClinicalUncertaintyState.UNMAPPED)
    with pytest.raises(ClinicalEventContractError, match="object"):
        ClinicalCompleteness.from_dict([])
    with pytest.raises(ClinicalEventContractError, match="object"):
        ClinicalUncertainty.from_dict("not-an-object")


def test_non_present_observation_cannot_smuggle_a_normalized_value() -> None:
    with pytest.raises(ClinicalEventContractError, match="normalized_value"):
        MonitoringClinicalObservation(
            observation_id="observation-missing-value",
            event_id="event-ae-001",
            domain=ClinicalDomain.AE,
            field_name="AETERM",
            value_status=ClinicalValueStatus.MISSING,
            normalized_value="inferred-term",
        )

    observation = MonitoringClinicalObservation(
        observation_id="observation-not-applicable",
        event_id="event-ae-001",
        domain=ClinicalDomain.AE,
        field_name="AEENDTC",
        value_status=ClinicalValueStatus.NOT_APPLICABLE,
    )
    assert observation.raw_value == ""
    assert observation.normalized_value == ""


def test_event_evidence_must_bind_to_the_event_source() -> None:
    with pytest.raises(ClinicalEventContractError, match="event source binding"):
        _event(evidence=(_evidence(source_binding_id="protocol-v1"),))


def test_tampered_hash_and_malformed_nested_lists_fail_closed() -> None:
    payload = _event().to_dict()
    tampered = deepcopy(payload)
    tampered["event_sha256"] = "f" * 64
    with pytest.raises(ClinicalEventContractError, match="does not match"):
        MonitoringClinicalEvent.from_dict(tampered)

    malformed = deepcopy(payload)
    malformed["evidence"] = "not-a-list"
    with pytest.raises(ClinicalEventContractError, match="evidence must be a list"):
        MonitoringClinicalEvent.from_dict(malformed)


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
def test_declared_event_hash_shape_is_not_coerced(declared_hash: object) -> None:
    payload = _event().to_dict()
    payload["event_sha256"] = declared_hash

    with pytest.raises(ClinicalEventContractError, match="lowercase SHA-256"):
        MonitoringClinicalEvent.from_dict(payload)


def test_missing_or_empty_declared_event_hash_is_recomputed() -> None:
    payload = _event().to_dict()
    expected = payload["event_sha256"]

    omitted = deepcopy(payload)
    omitted.pop("event_sha256")
    empty = deepcopy(payload)
    empty["event_sha256"] = ""

    assert MonitoringClinicalEvent.from_dict(omitted).event_sha256 == expected
    assert MonitoringClinicalEvent.from_dict(empty).event_sha256 == expected


def test_free_text_does_not_create_treatment_or_risk_links() -> None:
    observation = MonitoringClinicalObservation(
        observation_id="observation-free-text",
        event_id="event-ae-001",
        domain=ClinicalDomain.AE,
        field_name="AETERM",
        raw_value="Concomitant medication and investigational product are mentioned",
    )
    event = _event(observations=(observation,), cm_ids=(), ip_ids=(), risk_instance_ids=())

    assert event.cm_ids == ()
    assert event.ip_ids == ()
    assert event.risk_instance_ids == ()
