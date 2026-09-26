from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from services.api.app.monitoring_structure_shape_matrix import (
    StructureShapeMatrixError,
    StructureShapeMatrixIssueCode,
    assess_structure_shape_matrix,
)


MATRIX_PATH = (
    Path(__file__).resolve().parents[1]
    / "records/active_slices/medical_monitoring_structure_shape_matrix_20260804/"
    "FIVE_PROJECT_STRUCTURE_SHAPE_MATRIX.json"
)

# Same user-local records slice policy as the profile contract tests.
pytestmark = pytest.mark.skipif(
    not MATRIX_PATH.is_file(),
    reason="local five-project structure shape matrix slice absent from this checkout",
)


def _matrix() -> dict:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def _codes(report) -> set[str]:
    return {issue.code.value for issue in report.issues}


def test_recorded_five_project_shape_matrix_is_review_only() -> None:
    report = assess_structure_shape_matrix(_matrix())

    assert report.status == "ready_for_generalization_review"
    assert report.issues == ()
    assert report.project_ids == (
        "proj_mgk10_sar_real",
        "proj_my008_3_01_candidate",
        "proj_my008_3_02_candidate",
        "proj_my009_uc",
        "proj_rux_03_002",
    )
    assert report.diagnostic_only is True
    assert report.aggregate_only is True
    assert report.structure_mapping_permitted is False
    assert report.adapter_activation_permitted is False
    assert report.provider_call_permitted is False
    assert report.runtime_activation_permitted is False
    assert report.write_permitted is False
    assert report.medical_confirmation_permitted is False


def test_matrix_report_is_deterministic_and_does_not_echo_source_names_or_paths() -> None:
    matrix = _matrix()
    first = assess_structure_shape_matrix(matrix).to_dict()
    second = assess_structure_shape_matrix(deepcopy(matrix)).to_dict()

    assert first == second
    encoded = json.dumps(first, ensure_ascii=False)
    assert "/Users/" not in encoded
    assert "MY008211A-PNH" not in encoded
    assert ".xlsx" not in encoded


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda m: m["retention"].__setitem__("semantic_ai_enabled", True),
            StructureShapeMatrixIssueCode.RETENTION_FLAG_INVALID,
        ),
        (
            lambda m: m["projects"].pop(),
            StructureShapeMatrixIssueCode.PROJECT_SET_INCOMPLETE,
        ),
        (
            lambda m: m["projects"][0]["observed_domains"].append("UNSAFE"),
            StructureShapeMatrixIssueCode.DOMAIN_UNKNOWN,
        ),
        (
            lambda m: m["projects"][2].__setitem__("implementation_status", "real_source_slice"),
            StructureShapeMatrixIssueCode.IDENTITY_STATUS_MISMATCH,
        ),
        (
            lambda m: m["projects"][0]["source_revision"].__setitem__("listing_filename", "/tmp/listing.xlsx"),
            StructureShapeMatrixIssueCode.SOURCE_FILENAME_INVALID,
        ),
        (
            lambda m: m.__setitem__("source_evidence_ref", "records/../secret.json"),
            StructureShapeMatrixIssueCode.REFERENCE_INVALID,
        ),
    ],
)
def test_matrix_mutations_fail_closed(mutate, expected) -> None:
    matrix = _matrix()
    mutate(matrix)

    report = assess_structure_shape_matrix(matrix)

    assert report.status == "blocked"
    assert expected.value in _codes(report)
    assert report.provider_call_permitted is False
    assert report.write_permitted is False
    assert report.medical_confirmation_permitted is False


def test_non_mapping_top_level_is_rejected() -> None:
    with pytest.raises(StructureShapeMatrixError):
        assess_structure_shape_matrix([])
