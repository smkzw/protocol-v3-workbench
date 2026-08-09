from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from services.api.app.monitoring_formal_reviewer_resolution import (
    build_formal_reviewer_resolution_template,
    FormalReviewerResolutionError,
    FormalReviewerResolutionIssueCode,
    FormalReviewerResolutionReport,
    validate_formal_reviewer_resolution,
)


PACKAGE_PATH = Path(
    "records/active_slices/medical_monitoring_formal_reviewer_provenance_package_20260802/"
    "B6_FORMAL_REVIEWER_PROVENANCE_PACKAGE.json"
)


def _package() -> dict:
    return json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))


def _manifest_hash(package: dict, role: str) -> str:
    return next(
        item["sha256"] for item in package["source_manifest"] if item["role"] == role
    )


def _resolution(package: dict) -> dict:
    return {
        "schema_version": "medical_monitoring_formal_reviewer_resolution_v1",
        "package_sha256": package["package_sha256"],
        "reviewer_group": "synthetic_fixture_only",
        "authority": {
            "medical_approval_granted": False,
            "engineering_approval_granted": False,
            "write_authority": False,
            "migration_authority": False,
        },
        "outcomes": [
            {
                "review_id": f"fixture-{candidate['candidate_record_id']}",
                "candidate_record_id": candidate["candidate_record_id"],
                "candidate_fingerprint": candidate["candidate_fingerprint"],
                "b4_package_sha256": _manifest_hash(
                    package, "residual decision package"
                ),
                "b3_report_hash": _manifest_hash(package, "mapping dry-run"),
                "reviewer_identity": "fixture_reviewer",
                "reviewed_at": "2026-08-02T12:00:00+00:00",
                "medical_disposition_outcome": "defer",
                "source_lineage_resolution": "unproven",
                "aggregate_cas_resolution": "needs_aggregate_replay",
                "external_action_decision": "defer pending evidence",
                "source_evidence": [
                    f"fixture:source:{candidate['candidate_record_id']}"
                ],
                "aggregate_evidence": [
                    f"fixture:aggregate:{candidate['aggregate_case_id']}"
                ],
                "observed_expected_versions": [],
                "residual_blockers": ["fixture_blocker"],
                "rationale": "fixture is conservative and does not infer a medical conclusion",
            }
            for candidate in package["candidates"]
        ],
    }


def test_current_package_with_no_resolution_is_invalid_and_non_authoritative() -> None:
    package = _package()
    resolution = _resolution(package)
    resolution["outcomes"] = []
    report = validate_formal_reviewer_resolution(package, resolution)

    assert report.status == "invalid"
    assert report.package_hash_verified is True
    assert report.reviewer_outcomes_complete is False
    assert report.candidate_count == 5
    assert report.outcome_count == 0
    assert report.write_permitted is False
    assert report.migration_ready is False
    assert report.activation_allowed is False
    assert any(
        issue.code is FormalReviewerResolutionIssueCode.OUTCOME_COUNT_MISMATCH
        for issue in report.issues
    )


def test_conservative_hash_bound_resolution_is_structurally_valid_only() -> None:
    package = _package()
    report = validate_formal_reviewer_resolution(package, _resolution(package))

    assert report.status == "valid"
    assert report.reviewer_outcomes_complete is True
    assert report.approve_candidate_record_ids == ()
    assert report.reject_candidate_record_ids == ()
    assert len(report.deferred_candidate_record_ids) == 5
    assert report.write_permitted is False
    assert report.migration_ready is False
    assert report.activation_allowed is False
    assert report.to_dict() == report.to_dict()


def test_package_hash_mismatch_fails_closed() -> None:
    package = _package()
    resolution = _resolution(package)
    resolution["package_sha256"] = "0" * 64
    report = validate_formal_reviewer_resolution(package, resolution)
    assert any(
        issue.code is FormalReviewerResolutionIssueCode.PACKAGE_HASH_MISMATCH
        for issue in report.issues
    )


def test_candidate_and_source_hash_mismatch_are_reported() -> None:
    package = _package()
    resolution = _resolution(package)
    resolution["outcomes"][0]["candidate_fingerprint"] = "f" * 64
    resolution["outcomes"][1]["b4_package_sha256"] = "e" * 64
    report = validate_formal_reviewer_resolution(package, resolution)
    codes = [issue.code for issue in report.issues]
    assert FormalReviewerResolutionIssueCode.CANDIDATE_FINGERPRINT_MISMATCH in codes
    assert FormalReviewerResolutionIssueCode.SOURCE_HASH_MISMATCH in codes


def test_approve_requires_confirmed_lineage_cas_and_explicit_versions() -> None:
    package = _package()
    resolution = _resolution(package)
    candidate = resolution["outcomes"][0]
    candidate["medical_disposition_outcome"] = "approve"
    candidate["source_lineage_resolution"] = "unproven"
    candidate["aggregate_cas_resolution"] = "confirmed"
    candidate["residual_blockers"] = []
    candidate["observed_expected_versions"] = []
    report = validate_formal_reviewer_resolution(package, resolution)
    codes = [issue.code for issue in report.issues]
    assert FormalReviewerResolutionIssueCode.RESIDUAL_BLOCKER_CONTRADICTION in codes
    assert FormalReviewerResolutionIssueCode.CAS_VERSION_MISSING in codes


def test_missing_identity_time_evidence_and_rationale_are_explicit() -> None:
    package = _package()
    resolution = _resolution(package)
    candidate = resolution["outcomes"][0]
    candidate.update(
        {
            "reviewer_identity": "",
            "reviewed_at": "2026-08-02T12:00:00",
            "external_action_decision": "",
            "source_evidence": [],
            "aggregate_evidence": [],
            "rationale": "",
        }
    )
    report = validate_formal_reviewer_resolution(package, resolution)
    codes = [issue.code for issue in report.issues]
    assert FormalReviewerResolutionIssueCode.REVIEWER_IDENTITY_MISSING in codes
    assert FormalReviewerResolutionIssueCode.REVIEWED_AT_INVALID in codes
    assert FormalReviewerResolutionIssueCode.EXTERNAL_ACTION_MISSING in codes
    assert FormalReviewerResolutionIssueCode.EVIDENCE_MISSING in codes
    assert FormalReviewerResolutionIssueCode.RATIONALE_MISSING in codes


def test_reviewer_identity_fields_are_strictly_typed_and_review_id_is_required() -> (
    None
):
    package = _package()
    resolution = _resolution(package)
    candidate = resolution["outcomes"][0]
    candidate.update(
        {
            "review_id": "",
            "reviewer_identity": 123,
            "external_action_decision": {"decision": "defer"},
            "source_evidence": ["valid-locator", 1],
            "aggregate_evidence": [True],
            "residual_blockers": ["valid-blocker", 1],
            "rationale": ["not-a-string"],
        }
    )
    report = validate_formal_reviewer_resolution(package, resolution)
    codes = [issue.code for issue in report.issues]
    assert FormalReviewerResolutionIssueCode.REVIEW_ID_MISSING in codes
    assert FormalReviewerResolutionIssueCode.REVIEWER_IDENTITY_MISSING in codes
    assert FormalReviewerResolutionIssueCode.EXTERNAL_ACTION_MISSING in codes
    assert FormalReviewerResolutionIssueCode.EVIDENCE_MISSING in codes
    assert FormalReviewerResolutionIssueCode.RESIDUAL_BLOCKER_SHAPE in codes
    assert FormalReviewerResolutionIssueCode.RATIONALE_MISSING in codes


def test_duplicate_review_ids_are_rejected_without_merging_candidate_outcomes() -> None:
    package = _package()
    resolution = _resolution(package)
    resolution["outcomes"][1]["review_id"] = resolution["outcomes"][0]["review_id"]
    report = validate_formal_reviewer_resolution(package, resolution)
    assert any(
        issue.code is FormalReviewerResolutionIssueCode.DUPLICATE_REVIEW_ID
        for issue in report.issues
    )
    assert report.reviewer_outcomes_complete is True
    assert report.write_permitted is False


def test_evidence_fields_must_be_non_empty_string_arrays() -> None:
    package = _package()
    resolution = _resolution(package)
    resolution["outcomes"][0]["source_evidence"] = "source-locator"
    resolution["outcomes"][1]["aggregate_evidence"] = [""]
    report = validate_formal_reviewer_resolution(package, resolution)
    assert (
        sum(
            issue.code is FormalReviewerResolutionIssueCode.EVIDENCE_MISSING
            for issue in report.issues
        )
        == 2
    )


def test_true_authority_flag_is_rejected_even_for_valid_hash_bound_input() -> None:
    package = _package()
    resolution = _resolution(package)
    resolution["authority"]["write_authority"] = True
    report = validate_formal_reviewer_resolution(package, resolution)
    assert any(
        issue.code is FormalReviewerResolutionIssueCode.AUTHORITY_FLAG_TRUE
        for issue in report.issues
    )


@pytest.mark.parametrize(
    "field_name,value",
    (
        ("package_hash_verified", 1),
        ("reviewer_outcomes_complete", 0),
        ("write_permitted", 0),
        ("migration_ready", 0),
        ("activation_allowed", 0),
        ("candidate_count", "5"),
        ("outcome_count", 5.0),
    ),
)
def test_resolution_report_rejects_coerced_bool_and_count_shapes(
    field_name: str, value: object
) -> None:
    package = _package()
    base = validate_formal_reviewer_resolution(package, _resolution(package))
    assert isinstance(base, FormalReviewerResolutionReport)

    with pytest.raises(FormalReviewerResolutionError, match="boolean|non-negative integer"):
        replace(base, **{field_name: value})


def test_duplicate_and_unknown_outcomes_do_not_overwrite_candidate_identity() -> None:
    package = _package()
    resolution = _resolution(package)
    duplicate = deepcopy(resolution["outcomes"][0])
    unknown = deepcopy(resolution["outcomes"][1])
    unknown["candidate_record_id"] = "unknown-record"
    resolution["outcomes"] = [*resolution["outcomes"], duplicate, unknown]
    report = validate_formal_reviewer_resolution(package, resolution)
    codes = [issue.code for issue in report.issues]
    assert FormalReviewerResolutionIssueCode.DUPLICATE_OUTCOME in codes
    assert FormalReviewerResolutionIssueCode.UNKNOWN_CANDIDATE in codes


def test_non_mapping_package_is_rejected() -> None:
    with pytest.raises(
        FormalReviewerResolutionError, match="package must be a mapping"
    ):
        validate_formal_reviewer_resolution([], {})


def test_report_hash_is_deterministic() -> None:
    package = _package()
    first = validate_formal_reviewer_resolution(package, _resolution(package))
    second = validate_formal_reviewer_resolution(package, _resolution(package))
    assert first.report_sha256 == second.report_sha256
    assert hashlib.sha256(
        json.dumps(first.to_dict(), ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def test_template_is_hash_bound_blank_and_explicitly_non_authoritative() -> None:
    package = _package()
    template = build_formal_reviewer_resolution_template(package)

    assert (
        template["schema_version"] == "medical_monitoring_formal_reviewer_resolution_v1"
    )
    assert template["template_status"] == "pending_human_input"
    assert template["package_sha256"] == package["package_sha256"]
    assert all(value is False for value in template["authority"].values())
    assert len(template["outcomes"]) == package["candidate_count"]
    assert all(
        outcome["candidate_fingerprint"] == candidate["candidate_fingerprint"]
        and outcome["b4_package_sha256"]
        == _manifest_hash(package, "residual decision package")
        and outcome["b3_report_hash"] == _manifest_hash(package, "mapping dry-run")
        and outcome["medical_disposition_outcome"] == ""
        and outcome["source_lineage_resolution"] == ""
        and outcome["aggregate_cas_resolution"] == ""
        and outcome["source_evidence"] == []
        and outcome["aggregate_evidence"] == []
        for outcome, candidate in zip(template["outcomes"], package["candidates"])
    )

    report = validate_formal_reviewer_resolution(package, template)
    assert report.status == "invalid"
    assert report.write_permitted is False
    assert report.migration_ready is False
    assert report.activation_allowed is False
    assert any(
        issue.code is FormalReviewerResolutionIssueCode.MEDICAL_OUTCOME_MISSING
        for issue in report.issues
    )


def test_template_rejects_package_hash_or_candidate_fingerprint_drift() -> None:
    package = _package()
    tampered = deepcopy(package)
    tampered["candidates"][0]["candidate_fingerprint"] = "f" * 64
    with pytest.raises(FormalReviewerResolutionError, match="package_sha256"):
        build_formal_reviewer_resolution_template(tampered)

    invalid = deepcopy(package)
    invalid["candidates"][0]["candidate_fingerprint"] = "F" * 64
    invalid["package_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in invalid.items() if key != "package_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(FormalReviewerResolutionError, match="fingerprints"):
        build_formal_reviewer_resolution_template(invalid)
