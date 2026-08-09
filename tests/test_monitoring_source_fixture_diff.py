from __future__ import annotations

from dataclasses import replace

import pytest

from services.api.app.monitoring_adapter_consumer_coverage import build_consumer_coverage_plan
from services.api.app.monitoring_adapter_mapping_plan import (
    StudyAdapterMappingObservation,
    build_review_only_mapping_plan,
)
from services.api.app.monitoring_source_fixture_diff import (
    SourceFixtureDiffError,
    SourceFixtureFieldPresence,
    build_source_fixture_diff_report,
)
from services.api.app.monitoring_source_fixture_validation import (
    SourceFixtureValidationReport,
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


def test_diff_report_marks_schema_only_fields_and_unassessed_clinical_fields() -> None:
    coverage = _coverage()
    fixture_report = validate_source_fixture_records(
        coverage,
        build_schema_only_fixture_manifest(coverage),
    )
    report = build_source_fixture_diff_report(coverage, fixture_report)

    assert report.missing_mapping_ids == ()
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.status == "schema_only_unassessed"
    assert "source_field" in row.present_fields
    assert "event_id" in row.not_assessable_fields
    assert "normalized_value_if_present" in row.not_assessable_fields
    assert report.to_dict()["report_sha256"] == report.report_sha256


def test_diff_report_rejects_hash_or_mapping_drift() -> None:
    coverage = _coverage()
    fixture_report = validate_source_fixture_records(
        coverage,
        build_schema_only_fixture_manifest(coverage),
    )
    with pytest.raises(SourceFixtureDiffError, match="coverage hash"):
        build_source_fixture_diff_report(
            coverage,
            replace(fixture_report, coverage_sha256="wrong-hash"),
        )
    incomplete = build_source_fixture_diff_report(
        coverage,
        SourceFixtureValidationReport(
            adapter_key=fixture_report.adapter_key,
            project_id=fixture_report.project_id,
            trial_id=fixture_report.trial_id,
            coverage_sha256=coverage.coverage_sha256,
            schema_only=True,
            activation_allowed=False,
            expected_mapping_ids=fixture_report.expected_mapping_ids,
            observed_mapping_ids=(),
            missing_mapping_ids=fixture_report.expected_mapping_ids,
            records=(),
        ),
    )
    assert incomplete.missing_mapping_ids == ("my009-ae",)


def test_presence_row_cannot_claim_complete_or_active() -> None:
    with pytest.raises(SourceFixtureDiffError, match="cannot be marked complete"):
        SourceFixtureFieldPresence(
            mapping_id="m1",
            adapter_key="adapter",
            project_id="project",
            trial_id="trial",
            source_sheet="AE",
            source_field="AETERM",
            evidence_locator="fixture:row:1",
            source_revision="rev-1",
            record_id="record-1",
            schema_only=True,
            activation_allowed=False,
            value_status="unknown",
            present_fields=("mapping_id",),
            not_assessable_fields=(),
            status="complete",
        )
