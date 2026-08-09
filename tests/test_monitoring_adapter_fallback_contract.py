from __future__ import annotations

from dataclasses import replace

import pytest

from services.api.app.monitoring_adapter_consumer_coverage import build_consumer_coverage_plan
from services.api.app.monitoring_adapter_mapping_plan import (
    StudyAdapterMappingObservation,
    build_review_only_mapping_plan,
)
from services.api.app.monitoring_adapter_fallback_contract import (
    AdapterFallbackContractError,
    AdapterFallbackPolicy,
    AdapterFallbackState,
    build_adapter_fallback_policy_report,
)
from services.api.app.monitoring_onboarding_consumer_conservation import (
    build_onboarding_consumer_conservation_report,
)
from services.api.app.monitoring_source_fixture_diff import build_source_fixture_diff_report
from services.api.app.monitoring_source_fixture_validation import (
    build_schema_only_fixture_manifest,
    validate_source_fixture_records,
)


def _inputs():
    mapping_plan = build_review_only_mapping_plan(
        adapter_key="my009-monitoring",
        project_id="proj-my009",
        trial_id="MY009-UC",
        observations=(
            StudyAdapterMappingObservation(
                mapping_id="my009-ae",
                adapter_key="my009-monitoring",
                project_id="proj-my009",
                domain="AE",
                source_sheet="AE",
                source_field="AETERM",
                capability_id="ae_risk_assessment",
                observation_kind="fixed_sheet",
                evidence_locator="my009_monitoring_service.py:12-18",
                recommended_role="ae.reported_term",
            ),
        ),
    )
    coverage = build_consumer_coverage_plan(mapping_plan)
    fixture_report = validate_source_fixture_records(
        coverage,
        build_schema_only_fixture_manifest(coverage),
    )
    diff_report = build_source_fixture_diff_report(coverage, fixture_report)
    conservation = build_onboarding_consumer_conservation_report(coverage, fixture_report, diff_report)
    return coverage, conservation


def test_fallback_policy_is_limited_or_unavailable_and_blocks_risk() -> None:
    coverage, conservation = _inputs()
    report = build_adapter_fallback_policy_report(coverage, conservation)

    assert report.missing_mapping_ids == ()
    assert report.schema_only is True
    assert report.activation_allowed is False
    policy = report.policies[0]
    assert policy.fallback_states == ("limited", "unavailable")
    assert policy.default_state == AdapterFallbackState.UNAVAILABLE.value
    assert policy.payload_policy == "metadata_only_no_clinical_records"
    assert policy.risk_action == "blocked"
    assert policy.retirement_status == "not_retired"
    assert "source_mapping_medically_approved" in policy.retirement_conditions
    assert report.to_dict()["report_sha256"] == report.report_sha256


def test_fallback_report_preserves_missing_mapping_set() -> None:
    coverage, conservation = _inputs()
    incomplete = replace(conservation, rows=(), missing_mapping_ids=("my009-ae",))
    report = build_adapter_fallback_policy_report(coverage, incomplete)

    assert report.policies == ()
    assert report.missing_mapping_ids == ("my009-ae",)


def test_fallback_rejects_identity_drift_or_active_c11_input() -> None:
    coverage, conservation = _inputs()
    tampered_row = replace(conservation.rows[0], source_field="DRIFTED")
    tampered = replace(conservation, rows=(tampered_row,))
    with pytest.raises(AdapterFallbackContractError, match="identity drift"):
        build_adapter_fallback_policy_report(coverage, tampered)


def test_fallback_policy_cannot_claim_active_or_clinical_payload() -> None:
    kwargs = dict(
        mapping_id="m1",
        adapter_key="adapter",
        project_id="project",
        trial_id="trial",
        domain="ae",
        observed_domain="AE",
        source_sheet="AE",
        source_field="AETERM",
        evidence_locator="fixture:row:1",
        source_revision="schema-only-fixture-v1",
        diagnostic_surface_keys=("timeline", "subjects", "risk_links"),
    )
    with pytest.raises(AdapterFallbackContractError, match="cannot expose clinical"):
        AdapterFallbackPolicy(**kwargs, payload_policy="clinical_records")
    with pytest.raises(AdapterFallbackContractError, match="schema_only"):
        AdapterFallbackPolicy(**kwargs, activation_allowed=True)
    with pytest.raises(AdapterFallbackContractError, match="claim retirement"):
        AdapterFallbackPolicy(**kwargs, retirement_status="retired")
