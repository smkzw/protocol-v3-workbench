import json

import pytest

from services.api.app.monitoring_manifest_preconditions import (
    ManifestPreconditionError,
    ManifestPreconditionIssueCode,
    assess_manifest_preconditions,
)
from services.api.app.project_source_manifest import ProjectSourceManifestService


FIVE_PROJECTS = (
    "proj_mgk10_sar_real",
    "proj_rux_03_002",
    "proj_my008_pnh_3_02",
    "proj_my008_pnh_3_01",
    "proj_my009_uc",
)


def _manifest(project_id: str) -> dict:
    return ProjectSourceManifestService().public_manifest(project_id)


def test_five_project_public_manifests_are_ready_only_for_future_structure_parse() -> None:
    expected_statuses = {
        "proj_mgk10_sar_real": "real_source_slice",
        "proj_rux_03_002": "real_source_slice",
        "proj_my008_pnh_3_02": "source_manifest_only",
        "proj_my008_pnh_3_01": "source_manifest_only",
        "proj_my009_uc": "real_source_slice",
    }

    for project_id in FIVE_PROJECTS:
        report = assess_manifest_preconditions(_manifest(project_id))

        assert report.status == "ready_for_structure_parse"
        assert report.issues == ()
        assert report.project_id == project_id
        assert report.implementation_status == expected_statuses[project_id]
        assert report.diagnostic_only is True
        assert report.structure_parse_permitted is False
        assert report.adapter_activation_permitted is False
        assert report.provider_call_permitted is False
        assert report.write_permitted is False
        assert report.medical_confirmation_permitted is False


def test_public_report_is_deterministic_and_does_not_expose_paths() -> None:
    first = assess_manifest_preconditions(_manifest("proj_my008_pnh_3_01")).to_dict()
    second = assess_manifest_preconditions(_manifest("proj_my008_pnh_3_01")).to_dict()

    assert first == second
    assert first["report_sha256"]
    serialized = json.dumps(first, ensure_ascii=False)
    assert "/Users/" not in serialized
    assert "internal_path" not in serialized
    assert "server_path" not in serialized


@pytest.mark.parametrize(
    ("mutate", "expected"),
    (
        (
            lambda value: value["route_bindings"].pop("medical_monitoring"),
            ManifestPreconditionIssueCode.MONITORING_BINDING_MISSING,
        ),
        (
            lambda value: value["route_bindings"]["medical_monitoring"].update(
                implementation_status="planned"
            ),
            ManifestPreconditionIssueCode.IMPLEMENTATION_STATUS_UNSUPPORTED,
        ),
        (
            lambda value: value["route_bindings"]["medical_monitoring"].update(
                primary_source_ids=["missing-source"]
            ),
            ManifestPreconditionIssueCode.SOURCE_ID_UNKNOWN,
        ),
        (
            lambda value: value["route_bindings"]["medical_monitoring"].update(
                primary_source_ids=[
                    value["route_bindings"]["medical_monitoring"]["primary_source_ids"][0]
                ]
            ),
            ManifestPreconditionIssueCode.PRIMARY_PROTOCOL_MISSING,
        ),
        (
            lambda value: value["sources"][0].update(availability="missing"),
            ManifestPreconditionIssueCode.SOURCE_UNAVAILABLE,
        ),
    ),
)
def test_invalid_manifest_preconditions_are_visible_and_blocked(mutate, expected) -> None:
    value = _manifest("proj_my008_pnh_3_01")
    mutate(value)

    report = assess_manifest_preconditions(value)

    assert report.status == "blocked"
    assert expected in {item.code for item in report.issues}
    assert report.structure_parse_permitted is False
    assert report.adapter_activation_permitted is False
    assert report.provider_call_permitted is False
    assert report.write_permitted is False
    assert report.medical_confirmation_permitted is False


def test_duplicate_and_unknown_source_references_fail_closed() -> None:
    value = _manifest("proj_my008_pnh_3_02")
    binding = value["route_bindings"]["medical_monitoring"]
    source_id = binding["primary_source_ids"][0]
    binding["supplemental_source_ids"].append(source_id)
    binding["supplemental_source_ids"].append("unknown-source")

    report = assess_manifest_preconditions(value)
    codes = {item.code for item in report.issues}

    assert report.status == "blocked"
    assert ManifestPreconditionIssueCode.SOURCE_ID_DUPLICATE in codes
    assert ManifestPreconditionIssueCode.SOURCE_ID_UNKNOWN in codes


def test_malformed_top_level_type_is_rejected_without_an_execution_path() -> None:
    with pytest.raises(ManifestPreconditionError, match="mapping"):
        assess_manifest_preconditions([])


def test_source_rows_must_be_objects() -> None:
    value = _manifest("proj_my008_pnh_3_02")
    value["sources"].append("not-a-source-row")

    report = assess_manifest_preconditions(value)

    assert report.status == "blocked"
    assert ManifestPreconditionIssueCode.SOURCE_LIST_MISSING in {
        item.code for item in report.issues
    }


@pytest.mark.parametrize(
    ("mutate", "expected"),
    (
        (
            lambda value: value.update(project_id=123),
            ManifestPreconditionIssueCode.PROJECT_ID_MISSING,
        ),
        (
            lambda value: value["route_bindings"]["medical_monitoring"].update(
                route_project_id=b"proj"
            ),
            ManifestPreconditionIssueCode.ROUTE_PROJECT_ID_MISSING,
        ),
        (
            lambda value: value["sources"][0].update(source_id=123),
            ManifestPreconditionIssueCode.SOURCE_ID_MISSING,
        ),
        (
            lambda value: value["sources"][0].update(source_role=123),
            ManifestPreconditionIssueCode.SOURCE_ROLE_MISSING,
        ),
        (
            lambda value: value["route_bindings"]["medical_monitoring"].update(
                primary_source_ids=[123]
            ),
            ManifestPreconditionIssueCode.PRIMARY_SOURCE_LIST_MISSING,
        ),
    ),
)
def test_non_string_manifest_text_is_not_coerced_to_ready(
    mutate, expected
) -> None:
    value = _manifest("proj_my008_pnh_3_01")
    mutate(value)

    report = assess_manifest_preconditions(value)

    assert report.status == "blocked"
    assert expected in {item.code for item in report.issues}
    assert report.structure_parse_permitted is False
    assert report.adapter_activation_permitted is False
    assert report.provider_call_permitted is False
    assert report.write_permitted is False
    assert report.medical_confirmation_permitted is False
