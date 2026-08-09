from __future__ import annotations

from dataclasses import replace

import pytest

from services.api.app.monitoring_adapter_consumer_coverage import build_consumer_coverage_plan
from services.api.app.monitoring_adapter_mapping_plan import (
    StudyAdapterMappingObservation,
    build_review_only_mapping_plan,
)
from services.api.app.monitoring_onboarding_consumer_conservation import (
    OnboardingConsumerConservationError,
    OnboardingConsumerConservationRow,
    build_onboarding_consumer_conservation_report,
)
from services.api.app.monitoring_source_fixture_diff import build_source_fixture_diff_report
from services.api.app.monitoring_source_fixture_validation import (
    build_schema_only_fixture_manifest,
    validate_source_fixture_records,
)


def _coverage():
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
    return build_consumer_coverage_plan(mapping_plan)


def _reports():
    coverage = _coverage()
    fixture_report = validate_source_fixture_records(
        coverage,
        build_schema_only_fixture_manifest(coverage),
    )
    diff_report = build_source_fixture_diff_report(coverage, fixture_report)
    return coverage, fixture_report, diff_report


def test_conservation_joins_source_fixture_diff_and_frontend_surface_bindings() -> None:
    coverage, fixture_report, diff_report = _reports()
    report = build_onboarding_consumer_conservation_report(coverage, fixture_report, diff_report)

    assert report.missing_mapping_ids == ()
    assert report.schema_only is True
    assert report.activation_allowed is False
    row = report.rows[0]
    assert row.consumer_surfaces == ("timeline", "profile", "safety_metric", "risk_link")
    assert row.frontend_consumer_keys == ("timeline", "subjects", "safety_metrics", "risk_links")
    assert row.readiness == "structural_only"
    assert row.status == "schema_only_cross_surface_unassessed"
    assert row.fixture_status == "unknown"
    assert "event_id" in row.not_assessable_fields
    assert report.to_dict()["report_sha256"] == report.report_sha256


def test_conservation_preserves_explicit_missing_fixture_rows() -> None:
    coverage = _coverage()
    fixture_report = validate_source_fixture_records(
        coverage,
        (),
        require_complete=False,
    )
    diff_report = build_source_fixture_diff_report(coverage, fixture_report)
    report = build_onboarding_consumer_conservation_report(coverage, fixture_report, diff_report)

    assert report.rows == ()
    assert report.missing_mapping_ids == ("my009-ae",)


def test_conservation_rejects_identity_or_hash_drift() -> None:
    coverage, fixture_report, diff_report = _reports()
    tampered_record = replace(fixture_report.records[0], source_field="DRIFTED")
    tampered_fixture = replace(fixture_report, records=(tampered_record,))
    with pytest.raises(OnboardingConsumerConservationError, match="C10 fixture hash"):
        build_onboarding_consumer_conservation_report(coverage, tampered_fixture, diff_report)
    tampered_row = replace(diff_report.rows[0], source_field="DRIFTED")
    tampered_diff = replace(diff_report, rows=(tampered_row,))
    with pytest.raises(OnboardingConsumerConservationError, match="diff identity drift"):
        build_onboarding_consumer_conservation_report(coverage, fixture_report, tampered_diff)
    with pytest.raises(OnboardingConsumerConservationError, match="C10 fixture hash"):
        build_onboarding_consumer_conservation_report(
            coverage,
            fixture_report,
            replace(diff_report, fixture_report_sha256="drifted-hash"),
        )


def test_conservation_row_cannot_claim_readiness_or_unknown_surface() -> None:
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
        record_id="record-1",
        fixture_status="unknown",
        diff_status="schema_only_unassessed",
        consumer_surfaces=("timeline", "profile", "risk_link"),
        frontend_consumer_keys=("timeline", "subjects", "risk_links"),
        required_event_fields=("event_id",),
        required_observation_fields=("observation_id",),
        risk_link_policy="explicit_risk_instance_id_only",
        present_fields=("mapping_id",),
        not_assessable_fields=("event_id",),
    )
    with pytest.raises(OnboardingConsumerConservationError, match="clinical readiness"):
        OnboardingConsumerConservationRow(**kwargs, readiness="clinical_ready")
    with pytest.raises(OnboardingConsumerConservationError, match="unknown frontend"):
        OnboardingConsumerConservationRow(
            **{
                **kwargs,
                "consumer_surfaces": ("timeline", "profile", "risk_link", "unsupported"),
                "frontend_consumer_keys": ("timeline", "subjects", "risk_links", "unsupported"),
            },
        )
