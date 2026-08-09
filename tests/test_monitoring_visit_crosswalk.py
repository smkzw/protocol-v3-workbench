from __future__ import annotations

from services.api.app.monitoring_visit_crosswalk import (
    CrosswalkObservedVisit,
    CrosswalkProtocolVisit,
    ObservedVisitKind,
    VisitCrosswalkBinding,
    VisitCrosswalkBindingState,
    VisitCrosswalkStatus,
    validate_visit_crosswalk,
)


PROTOCOL_SHA = "a" * 64
LISTING_SHA = "b" * 64


def _protocol(**overrides) -> CrosswalkProtocolVisit:
    values = {
        "visit_id": "V1",
        "label": "D1",
        "anchor_day": 1,
        "window_before_days": 0,
        "window_after_days": 2,
        "source_locator": "docx:table:10:row:3",
    }
    values.update(overrides)
    return CrosswalkProtocolVisit(**values)


def _observed(**overrides) -> CrosswalkObservedVisit:
    values = {
        "listing_visit_id": "V1",
        "listing_label": "D1",
        "source_locator": "listing:sheet:SV1:visit:V1",
        "row_count": 10,
    }
    values.update(overrides)
    return CrosswalkObservedVisit(**values)


def _binding(**overrides) -> VisitCrosswalkBinding:
    observed_override = overrides.pop("observed", None)
    observed = (
        observed_override
        if isinstance(observed_override, CrosswalkObservedVisit)
        else _observed(**(observed_override or {}))
    )
    values = {
        "binding_id": "v1-binding",
        "protocol_visit_id": "V1",
        "observed_visit_keys": (observed.key,),
        "state": VisitCrosswalkBindingState.EXPLICIT,
        "source_locator": "review:crosswalk:1",
    }
    values.update(overrides)
    return VisitCrosswalkBinding(**values)


def _report_codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def test_exact_binding_passes_without_activation() -> None:
    report = validate_visit_crosswalk(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        protocol_visits=(_protocol(),),
        observed_visits=(_observed(),),
        bindings=(_binding(),),
    )

    assert report.status is VisitCrosswalkStatus.PASSED
    assert report.activation_allowed is False
    assert report.findings == ()
    assert report.to_dict()["report_sha256"] == report.report_sha256


def test_required_treatment_specific_visit_missing_fails_closed() -> None:
    protocol = _protocol(
        visit_id="V10",
        label="D70±3天",
        anchor_day=70,
        window_after_days=3,
        arm_scope=("eculizumab",),
    )
    observed = _observed(
        listing_visit_id="V11",
        listing_label="D84±3天",
        source_locator="listing:sheet:SV1:visit:V11",
    )
    report = validate_visit_crosswalk(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        protocol_visits=(protocol,),
        observed_visits=(observed,),
        bindings=(),
    )

    assert report.status is VisitCrosswalkStatus.BLOCKED
    assert {
        "required_protocol_visit_binding_missing",
        "scheduled_observed_visit_unbound",
    } <= _report_codes(report)


def test_label_match_surfaces_oid_ordinal_conflict_for_review() -> None:
    observed = _observed(listing_visit_id="V10", listing_label="D84±3天")
    protocol = _protocol(visit_id="V11", label="D84±3天", anchor_day=84)
    binding = _binding(
        protocol_visit_id="V11",
        state=VisitCrosswalkBindingState.LABEL_MATCH,
        observed=observed,
    )
    report = validate_visit_crosswalk(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        protocol_visits=(protocol,),
        observed_visits=(observed,),
        bindings=(binding,),
    )

    assert report.status is VisitCrosswalkStatus.REVIEW_REQUIRED
    assert "listing_visit_oid_ordinal_review" in _report_codes(report)


def test_unplanned_withdrawal_and_non_visit_are_not_scheduled_substitutes() -> None:
    observed = (
        _observed(),
        _observed(
            listing_visit_id="UNS",
            listing_label="计划外访视#1",
            kind=ObservedVisitKind.UNSCHEDULED,
            source_locator="listing:sheet:SV2:visit:UNS-1",
        ),
        _observed(
            listing_visit_id="WITHDRAW",
            listing_label="提前退出研究",
            kind=ObservedVisitKind.WITHDRAWAL,
            source_locator="listing:sheet:SV1:visit:WITHDRAW",
        ),
        _observed(
            listing_visit_id="COMMON",
            listing_label="公共页",
            kind=ObservedVisitKind.NON_VISIT,
            source_locator="listing:sheet:AE:visit:COMMON",
        ),
    )
    report = validate_visit_crosswalk(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        protocol_visits=(_protocol(),),
        observed_visits=observed,
        bindings=(_binding(),),
    )

    assert report.status is VisitCrosswalkStatus.PASSED
    assert report.findings == ()


def test_special_visit_cannot_bind_scheduled_protocol_visit() -> None:
    observed = _observed(
        listing_visit_id="UNS",
        listing_label="计划外访视#1",
        kind=ObservedVisitKind.UNSCHEDULED,
        source_locator="listing:sheet:SV2:visit:UNS-1",
    )
    report = validate_visit_crosswalk(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        protocol_visits=(_protocol(),),
        observed_visits=(observed,),
        bindings=(_binding(observed=observed),),
    )

    assert report.status is VisitCrosswalkStatus.BLOCKED
    assert "special_observed_visit_cannot_bind_protocol" in _report_codes(report)


def test_arm_scope_conflict_blocks_and_unverified_scope_requires_review() -> None:
    protocol = _protocol(arm_scope=("eculizumab",))
    conflicting = _observed(arm_scope=("my008211a",))
    conflict_report = validate_visit_crosswalk(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        protocol_visits=(protocol,),
        observed_visits=(conflicting,),
        bindings=(_binding(observed=conflicting),),
    )
    assert conflict_report.status is VisitCrosswalkStatus.BLOCKED
    assert "visit_arm_scope_conflict" in _report_codes(conflict_report)

    unscoped = _observed()
    review_report = validate_visit_crosswalk(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        protocol_visits=(protocol,),
        observed_visits=(unscoped,),
        bindings=(_binding(observed=unscoped),),
    )
    assert review_report.status is VisitCrosswalkStatus.REVIEW_REQUIRED
    assert "visit_arm_scope_unverified" in _report_codes(review_report)


def test_reordering_inputs_does_not_change_hashes() -> None:
    protocol2 = _protocol(
        visit_id="V2",
        label="D7±2天",
        anchor_day=7,
        window_after_days=2,
        source_locator="docx:table:10:row:5",
    )
    observed2 = _observed(
        listing_visit_id="V2",
        listing_label="D7±2天",
        source_locator="listing:sheet:SV1:visit:V2",
    )
    binding2 = _binding(
        binding_id="v2-binding", protocol_visit_id="V2", observed=observed2
    )
    first = validate_visit_crosswalk(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        protocol_visits=(_protocol(), protocol2),
        observed_visits=(_observed(), observed2),
        bindings=(_binding(), binding2),
    )
    second = validate_visit_crosswalk(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        protocol_visits=(protocol2, _protocol()),
        observed_visits=(observed2, _observed()),
        bindings=(binding2, _binding()),
    )

    assert first.input_sha256 == second.input_sha256
    assert first.report_sha256 == second.report_sha256


def test_invalid_source_hash_is_blocking() -> None:
    report = validate_visit_crosswalk(
        protocol_source_sha256="not-a-hash",
        listing_source_sha256=LISTING_SHA,
        protocol_visits=(_protocol(),),
        observed_visits=(_observed(),),
        bindings=(_binding(),),
    )

    assert report.status is VisitCrosswalkStatus.BLOCKED
    assert "source_hash_invalid" in _report_codes(report)
