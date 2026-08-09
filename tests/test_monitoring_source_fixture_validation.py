from __future__ import annotations

from dataclasses import replace

import pytest

from services.api.app.monitoring_adapter_consumer_coverage import build_consumer_coverage_plan
from services.api.app.monitoring_adapter_mapping_plan import (
    StudyAdapterMappingObservation,
    build_review_only_mapping_plan,
)
from services.api.app.monitoring_source_fixture_validation import (
    SourceFixtureDatePrecision,
    SourceFixtureValidationError,
    SourceFixtureValueStatus,
    build_schema_only_fixture_manifest,
    validate_source_fixture_records,
)


def _coverage_plan():
    mapping_plan = build_review_only_mapping_plan(
        adapter_key="rux-monitoring",
        project_id="proj-rux",
        trial_id="RUX-03-002",
        observations=(
            StudyAdapterMappingObservation(
                mapping_id="rux-lab",
                adapter_key="rux-monitoring",
                project_id="proj-rux",
                domain="LAB",
                source_sheet="LB--实验室",
                source_field="ALT",
                capability_id="lab_ctcae_rules",
                observation_kind="fixed_sheet",
                evidence_locator="rux_monitoring_service.py:36-47",
                recommended_role="lab.value",
            ),
            StudyAdapterMappingObservation(
                mapping_id="rux-source",
                adapter_key="rux-monitoring",
                project_id="proj-rux",
                domain="SOURCE",
                source_sheet="SUBJ--受试者页",
                source_field="SUBJID",
                capability_id="patient_profile",
                observation_kind="fixed_sheet",
                evidence_locator="rux_monitoring_service.py:36-47",
                recommended_role="source.subject_id",
            ),
        ),
    )
    return build_consumer_coverage_plan(mapping_plan)


def test_schema_only_manifest_is_complete_and_inactive() -> None:
    coverage = _coverage_plan()
    records = build_schema_only_fixture_manifest(coverage)
    report = validate_source_fixture_records(coverage, records)

    assert len(records) == 2
    assert report.schema_only is True
    assert report.activation_allowed is False
    assert report.missing_mapping_ids == ()
    assert report.observed_mapping_ids == ("rux-lab", "rux-source")
    assert all(record.value_status is SourceFixtureValueStatus.UNKNOWN for record in records)
    assert all(record.normalized_value is None for record in records)
    assert report.to_dict()["report_sha256"] == report.report_sha256


def test_source_fixture_preserves_numeric_zero_and_rejects_normalization() -> None:
    coverage = _coverage_plan()
    record = build_schema_only_fixture_manifest(coverage)[0]
    present = replace(
        record,
        record_id="fixture:rux-lab:row-1",
        value_status=SourceFixtureValueStatus.PRESENT,
        raw_value=0,
        date_raw="2026-04-12",
        date_precision=SourceFixtureDatePrecision.DAY,
        subject_id="S001",
        site_id="01",
    )
    report = validate_source_fixture_records(coverage, [present], require_complete=False)
    assert report.missing_mapping_ids == ("rux-source",)
    assert report.records[0].raw_value == 0

    with pytest.raises(SourceFixtureValidationError, match="cannot invent or normalize"):
        replace(present, normalized_value="0")


def test_source_fixture_identity_date_and_path_mismatch_fail_closed() -> None:
    coverage = _coverage_plan()
    record = build_schema_only_fixture_manifest(coverage)[0]
    with pytest.raises(SourceFixtureValidationError, match="source_field mismatch"):
        validate_source_fixture_records(coverage, [replace(record, source_field="AST")])
    with pytest.raises(SourceFixtureValidationError, match="real calendar date"):
        replace(record, date_raw="2026-02-30", date_precision="day")
    with pytest.raises(SourceFixtureValidationError, match="must not be a local path"):
        replace(record, evidence_locator="/tmp/unsafe")
    with pytest.raises(SourceFixtureValidationError, match="incomplete"):
        validate_source_fixture_records(coverage, [record])
