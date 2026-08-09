from __future__ import annotations

from services.api.app.monitoring_protocol_listing_precheck import (
    ProtocolListingAvailability,
    ProtocolListingFindingSeverity,
    ProtocolListingMappingCandidate,
    ProtocolListingPrecheckStatus,
    ProtocolListingVisitBinding,
    ProtocolVisitRequirement,
    precheck_protocol_listing_mapping,
)


PROTOCOL_SHA = "a" * 64
LISTING_SHA = "b" * 64


def _visits() -> tuple[ProtocolVisitRequirement, ...]:
    return (
        ProtocolVisitRequirement(
            visit_id="V1",
            label="筛选",
            anchor_day=-7,
            window_before_days=7,
            window_after_days=0,
            source_locator="docx:table:10:row:2",
        ),
        ProtocolVisitRequirement(
            visit_id="V2",
            label="D1",
            anchor_day=1,
            window_before_days=0,
            window_after_days=2,
            source_locator="docx:table:10:row:3",
        ),
    )


def _mapping(**overrides) -> ProtocolListingMappingCandidate:
    values = {
        "mapping_id": "ae-term",
        "module": "safety",
        "domain": "AE",
        "source_sheet": "AE",
        "source_field": "AETERM",
        "source_locator": "listing:sheet:AE:header:1:field:AETERM",
        "protocol_fact_key": "safety.assessment.ae",
        "protocol_locator": "docx:table:16:row:4",
        "availability": ProtocolListingAvailability.AVAILABLE,
        "visit_binding": ProtocolListingVisitBinding.EXPLICIT,
        "visit_source_field": "VISIT",
        "protocol_visit_ids": ("V1", "V2"),
    }
    values.update(overrides)
    return ProtocolListingMappingCandidate(**values)


def _report_codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def test_clean_mapping_passes_but_never_authorizes_activation() -> None:
    report = precheck_protocol_listing_mapping(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        visits=_visits(),
        mappings=(_mapping(),),
    )

    assert report.status is ProtocolListingPrecheckStatus.PASSED
    assert report.activation_allowed is False
    assert report.findings == ()
    assert report.to_dict()["report_sha256"] == report.report_sha256


def test_duplicate_headers_and_unresolved_mapping_fail_closed() -> None:
    report = precheck_protocol_listing_mapping(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        visits=_visits(),
        mappings=(_mapping(),),
        duplicate_header_sheets=("AE", "CM6"),
        unresolved_mapping_reasons=("form_to_visit_mapping_unresolved",),
    )

    assert report.status is ProtocolListingPrecheckStatus.BLOCKED
    assert {
        "duplicate_header_sheet_present",
        "mapping_uses_duplicate_header_sheet",
        "unresolved_mapping_reason",
    } <= _report_codes(report)


def test_pk_collection_only_cannot_claim_quantitative_result_or_lloq() -> None:
    report = precheck_protocol_listing_mapping(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        visits=_visits(),
        mappings=(
            _mapping(
                mapping_id="pk-collection",
                module="pk",
                domain="PC1",
                source_sheet="PC1",
                source_field="PKCOLLECT",
                protocol_fact_key="pk.sampling.schedule",
                availability=ProtocolListingAvailability.COLLECTION_ONLY,
                supports_quantitative_result=True,
                result_field="PKCONC",
                lloq_field="LLOQ",
            ),
        ),
    )

    assert report.status is ProtocolListingPrecheckStatus.BLOCKED
    assert "collection_only_quantitative_conflict" in _report_codes(report)


def test_derived_visit_binding_is_review_not_silent_pass() -> None:
    report = precheck_protocol_listing_mapping(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        visits=_visits(),
        mappings=(_mapping(visit_binding=ProtocolListingVisitBinding.DERIVED),),
    )

    assert report.status is ProtocolListingPrecheckStatus.REVIEW_REQUIRED
    finding = next(
        item
        for item in report.findings
        if item.code == "visit_binding_derived_review"
    )
    assert finding.severity is ProtocolListingFindingSeverity.REVIEW_REQUIRED


def test_reordering_inputs_does_not_change_input_or_report_hash() -> None:
    metadata_mapping = _mapping(
        mapping_id="dm-subject",
        domain="DM",
        source_sheet="DM",
        source_field="SUBJID",
        requires_visit=False,
        visit_binding=ProtocolListingVisitBinding.NOT_APPLICABLE,
        protocol_visit_ids=(),
    )
    mappings = (_mapping(), metadata_mapping)
    first = precheck_protocol_listing_mapping(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        visits=_visits(),
        mappings=mappings,
    )
    second = precheck_protocol_listing_mapping(
        protocol_source_sha256=PROTOCOL_SHA,
        listing_source_sha256=LISTING_SHA,
        visits=tuple(reversed(_visits())),
        mappings=tuple(reversed(mappings)),
    )

    assert first.input_sha256 == second.input_sha256
    assert first.report_sha256 == second.report_sha256
