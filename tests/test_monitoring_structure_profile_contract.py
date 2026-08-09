from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from services.api.app.monitoring_structure_profile_contract import (
    StructureProfileContractError,
    StructureProfileIssueCode,
    assess_structure_profile,
)


PROFILE_PATH = Path(
    "records/active_slices/medical_monitoring_my008_structural_discovery_20260804/"
    "MY008_STRUCTURAL_DISCOVERY_PROFILE.json"
)


def _profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def _codes(report) -> set[str]:
    return {issue.code.value for issue in report.issues}


def test_persisted_candidate_profile_is_ready_for_offline_mapping_only() -> None:
    report = assess_structure_profile(_profile())

    assert report.status == "ready_for_mapping"
    assert report.issues == ()
    assert report.project_ids == (
        "proj_my008_3_01_candidate",
        "proj_my008_3_02_candidate",
    )
    assert report.diagnostic_only is True
    assert report.candidate_only is True
    assert report.offline_only is True
    assert report.structure_parse_permitted is False
    assert report.adapter_activation_permitted is False
    assert report.provider_call_permitted is False
    assert report.runtime_activation_permitted is False
    assert report.write_permitted is False
    assert report.medical_confirmation_permitted is False


def test_report_is_deterministic_and_redacted() -> None:
    profile = _profile()
    first = assess_structure_profile(profile).to_dict()
    second = assess_structure_profile(deepcopy(profile)).to_dict()

    assert first == second
    encoded = json.dumps(first, ensure_ascii=False)
    assert "/Users/" not in encoded
    assert "MY008211A-PNH" not in encoded
    assert "SUBJID" not in encoded


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda p: p["authority"].__setitem__("write_permitted", True),
            StructureProfileIssueCode.AUTHORITY_FLAG_INVALID,
        ),
        (
            lambda p: p["processing"].__setitem__("cell_values_retained", True),
            StructureProfileIssueCode.PROCESSING_FLAG_INVALID,
        ),
        (
            lambda p: p["projects"][0]["listing_summary"]["sheet_row_counts"].__setitem__("AE", 0),
            StructureProfileIssueCode.SHEET_ROW_COUNT_SUM_MISMATCH,
        ),
        (
            lambda p: p["projects"][0]["source_anchor"].__setitem__("listing_filename", "/tmp/leak.xlsx"),
            StructureProfileIssueCode.SOURCE_FILENAME_INVALID,
        ),
        (
            lambda p: p["projects"][0]["domain_groups"]["adverse_event"]["sheet_names"].append("DOES_NOT_EXIST"),
            StructureProfileIssueCode.DOMAIN_GROUP_SHEET_UNKNOWN,
        ),
        (
            lambda p: p["projects"][0]["unclassified_sheet_names"].append("AE"),
            StructureProfileIssueCode.CLASSIFICATION_OVERLAP,
        ),
        (
            lambda p: p["projects"].append(deepcopy(p["projects"][0])),
            StructureProfileIssueCode.PROJECT_ID_DUPLICATE,
        ),
    ],
)
def test_malformed_profile_is_blocked_without_granting_authority(mutate, expected) -> None:
    profile = _profile()
    mutate(profile)

    report = assess_structure_profile(profile)

    assert report.status == "blocked"
    assert expected.value in _codes(report)
    assert report.write_permitted is False
    assert report.provider_call_permitted is False
    assert report.medical_confirmation_permitted is False


def test_classification_partition_detects_removed_unclassified_sheet() -> None:
    profile = _profile()
    profile["projects"][1]["unclassified_sheet_names"].pop()

    report = assess_structure_profile(profile)

    assert report.status == "blocked"
    assert StructureProfileIssueCode.CLASSIFICATION_PARTITION_INCOMPLETE.value in _codes(report)


def test_absolute_evidence_reference_is_blocked() -> None:
    profile = _profile()
    profile["source_descriptor_ref"] = "/private/descriptor.json"

    report = assess_structure_profile(profile)

    assert report.status == "blocked"
    assert StructureProfileIssueCode.SOURCE_DESCRIPTOR_REFERENCE_INVALID.value in _codes(report)


def test_traversal_evidence_reference_and_empty_identifier_fields_are_blocked() -> None:
    profile = _profile()
    profile["source_descriptor_ref"] = "records/../private/descriptor.json"
    profile["projects"][0]["listing_summary"]["site_id_fields"] = []

    report = assess_structure_profile(profile)

    assert report.status == "blocked"
    codes = _codes(report)
    assert StructureProfileIssueCode.SOURCE_DESCRIPTOR_REFERENCE_INVALID.value in codes
    assert StructureProfileIssueCode.IDENTIFIER_FIELDS_INVALID.value in codes


def test_non_mapping_top_level_is_rejected() -> None:
    with pytest.raises(StructureProfileContractError):
        assess_structure_profile([])
