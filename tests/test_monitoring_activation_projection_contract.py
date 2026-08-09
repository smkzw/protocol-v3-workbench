from __future__ import annotations

from dataclasses import replace

import pytest

from services.api.app.monitoring_activation_projection_contract import (
    ActivationProjectionContractError,
    ActivationProjectionRow,
    build_activation_projection_report,
)
from services.api.app.monitoring_adapter_consumer_coverage import build_consumer_coverage_plan
from services.api.app.monitoring_adapter_fallback_contract import build_adapter_fallback_policy_report
from services.api.app.monitoring_adapter_mapping_plan import (
    StudyAdapterMappingObservation,
    build_review_only_mapping_plan,
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
    fallback = build_adapter_fallback_policy_report(coverage, conservation)
    return coverage, conservation, fallback


def test_activation_route_is_blocked_and_conserves_shared_contracts() -> None:
    coverage, conservation, fallback = _inputs()
    report = build_activation_projection_report(coverage, conservation, fallback)

    assert report.missing_mapping_ids == ()
    assert report.schema_only is True
    assert report.activation_allowed is False
    row = report.rows[0]
    assert row.status == "blocked_pending_approval"
    assert row.event_creation_allowed is False
    assert row.projection_allowed is False
    assert row.consumer_surface_keys == ("timeline", "subjects", "safety_metrics", "risk_links")
    assert row.safety_metric_surface is True
    assert "mapping_review_pending" in row.blockers
    assert report.to_dict()["report_sha256"] == report.report_sha256


def test_activation_route_preserves_missing_candidates() -> None:
    coverage, conservation, fallback = _inputs()
    incomplete_conservation = replace(conservation, rows=(), missing_mapping_ids=("my009-ae",))
    incomplete_fallback = replace(
        fallback,
        conservation_report_sha256=incomplete_conservation.report_sha256,
        policies=(),
        missing_mapping_ids=("my009-ae",),
    )
    report = build_activation_projection_report(coverage, incomplete_conservation, incomplete_fallback)

    assert report.rows == ()
    assert report.missing_mapping_ids == ("my009-ae",)


def test_activation_route_rejects_fallback_identity_or_retirement_drift() -> None:
    coverage, conservation, fallback = _inputs()
    tampered_policy = replace(fallback.policies[0], source_field="DRIFTED")
    tampered_fallback = replace(fallback, policies=(tampered_policy,))
    with pytest.raises(ActivationProjectionContractError, match="fallback identity drift"):
        build_activation_projection_report(coverage, conservation, tampered_fallback)
    unavailable_policy = replace(fallback.policies[0], retirement_status="not_retired")
    active_like = replace(unavailable_policy, default_state="limited")
    active_fallback = replace(fallback, policies=(active_like,))
    with pytest.raises(ActivationProjectionContractError, match="cannot bypass"):
        build_activation_projection_report(coverage, conservation, active_fallback)


def test_activation_row_cannot_claim_event_or_projection_creation() -> None:
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
        event_contract="MonitoringClinicalEvent/MonitoringClinicalObservation",
        projection_contract="MonitoringClinicalReadModel/ClinicalConsumerHandoff",
        consumer_surface_keys=("timeline", "subjects", "risk_links"),
        required_event_fields=("event_id",),
        required_observation_fields=("observation_id",),
        safety_metric_surface=False,
        fallback_default_state="unavailable",
        fallback_retirement_status="not_retired",
    )
    with pytest.raises(ActivationProjectionContractError, match="blocked and schema-only"):
        ActivationProjectionRow(**kwargs, event_creation_allowed=True)
