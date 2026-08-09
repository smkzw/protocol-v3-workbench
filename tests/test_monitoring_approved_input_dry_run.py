from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from services.api.app.monitoring_approved_input_dry_run import (
    ApprovedInputDryRunIssue,
    ApprovedInputDryRunError,
    ApprovedInputDryRunReport,
    ApprovedInputIssueCode,
    ControlledApprovedInputDryRunReport,
    canonical_source_batch_binding_sha256,
    dry_run_approved_input,
    dry_run_approved_input_with_source_preflight,
)
from services.api.app.monitoring_source_batch_preflight import SourceBatchRecord


PACKAGE_PATH = Path(
    "records/active_slices/medical_monitoring_formal_reviewer_provenance_package_20260802/"
    "B6_FORMAL_REVIEWER_PROVENANCE_PACKAGE.json"
)


def _package() -> dict:
    return json.loads(PACKAGE_PATH.read_text())


def _observed_manifest(package: dict) -> dict[str, tuple[int, str]]:
    observed = {}
    for item in package["source_manifest"]:
        path = Path(item["path"])
        observed[item["path"]] = (
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return observed


def _rehash(package: dict) -> dict:
    package = deepcopy(package)
    package.pop("package_sha256", None)
    package["package_sha256"] = hashlib.sha256(
        json.dumps(
            package, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return package


def _make_diagnostic_ready(package: dict) -> dict:
    for candidate in package["candidates"]:
        candidate["source_version_relation"] = "exact_after_identity"
        candidate["legacy_source_version"]["source_token"] = "synthetic-source-token"
        candidate["residual_blockers"] = []
        candidate["required_reviewer_input"] = {
            key: "provided" for key in candidate["required_reviewer_input"]
        }
    for case in package["aggregate_cases"]:
        case["cas_replay_complete"] = True
        case["issue_count"] = 0
        case["issue_codes"] = []
        case["cas_applied_event_ids"] = list(case["event_ids"])
    package["gate_state"]["b6"].update(
        {
            "status": "approved_input_ready",
            "pending_candidate_record_ids": [],
            "missing_candidate_record_ids": [],
            "rejected_candidate_record_ids": [],
            "unresolved_blockers": [],
            "accepted_review_ids": [
                candidate["engineering_defer"]["review_id"]
                for candidate in package["candidates"]
            ],
        }
    )
    return package


def _source_rows(tmp_path: Path) -> tuple[SourceBatchRecord, ...]:
    rows = []
    for batch_ref, content in (("batch-1", b"one"), ("batch-2", b"two")):
        path = tmp_path / f"{batch_ref}.xlsx"
        path.write_bytes(content)
        rows.append(
            SourceBatchRecord(
                project_id="proj",
                batch_ref=batch_ref,
                snapshot_date="2026-01-01",
                listing_path=str(path),
                listing_bytes=len(content),
                listing_sha256=hashlib.sha256(content).hexdigest(),
                listing_class="raw_full_snapshot",
                source_status="confirmed",
                full_snapshot_proven=True,
            )
        )
    return tuple(rows)


def test_current_formal_package_is_blocked_without_inference() -> None:
    package = _package()
    report = dry_run_approved_input(
        package, observed_source_manifest=_observed_manifest(package)
    )

    codes = [issue.code for issue in report.issues]
    assert report.status == "blocked"
    assert report.approved_input_ready is False
    assert report.source_manifest_replay_complete is True
    assert report.reviewer_outcomes_complete is False
    assert report.source_lineage_complete is False
    assert report.aggregate_cas_complete is False
    assert report.residual_blockers_clear is False
    assert report.write_permitted is False
    assert report.migration_ready is False
    assert codes.count(ApprovedInputIssueCode.B6_GATE_NOT_READY) == 1
    assert codes.count(ApprovedInputIssueCode.REVIEW_OUTCOME_MISSING) == 5
    assert codes.count(ApprovedInputIssueCode.SOURCE_LINEAGE_UNPROVEN) == 3
    assert codes.count(ApprovedInputIssueCode.AGGREGATE_CAS_UNPROVEN) == 2
    assert codes.count(ApprovedInputIssueCode.RESIDUAL_BLOCKER) == 3


def test_missing_manifest_observation_is_not_treated_as_verified() -> None:
    report = dry_run_approved_input(_package())
    assert report.status == "blocked"
    assert report.source_manifest_replay_complete is False
    assert any(
        issue.code is ApprovedInputIssueCode.SOURCE_MANIFEST_UNVERIFIED
        for issue in report.issues
    )


def test_source_manifest_rejects_boolean_byte_count() -> None:
    package = _package()
    package["source_manifest"][0]["bytes"] = True
    package = _rehash(package)

    with pytest.raises(
        ApprovedInputDryRunError, match="source_manifest entry path/bytes is invalid"
    ):
        dry_run_approved_input(
            package, observed_source_manifest=_observed_manifest(_package())
        )


def test_package_hash_tampering_fails_closed() -> None:
    package = _package()
    package["candidate_count"] = 4
    with pytest.raises(ApprovedInputDryRunError, match="package_sha256"):
        dry_run_approved_input(
            package, observed_source_manifest=_observed_manifest(_package())
        )


def test_complete_synthetic_package_is_ready_but_never_writable() -> None:
    package = _package()
    for candidate in package["candidates"]:
        candidate["source_version_relation"] = "exact_after_identity"
        candidate["legacy_source_version"]["source_token"] = "synthetic-source-token"
        candidate["residual_blockers"] = []
        candidate["required_reviewer_input"] = {
            key: "provided" for key in candidate["required_reviewer_input"]
        }
    for case in package["aggregate_cases"]:
        case["cas_replay_complete"] = True
        case["issue_count"] = 0
        case["issue_codes"] = []
        case["cas_applied_event_ids"] = list(case["event_ids"])
    package["gate_state"]["b6"].update(
        {
            "status": "approved_input_ready",
            "pending_candidate_record_ids": [],
            "missing_candidate_record_ids": [],
            "rejected_candidate_record_ids": [],
            "unresolved_blockers": [],
            "accepted_review_ids": [
                candidate["engineering_defer"]["review_id"]
                for candidate in package["candidates"]
            ],
        }
    )
    package = _rehash(package)
    report = dry_run_approved_input(
        package, observed_source_manifest=_observed_manifest(package)
    )

    assert report.status == "ready"
    assert report.approved_input_ready is True
    assert report.issues == ()
    assert report.write_permitted is False
    assert report.migration_ready is False
    assert report.to_dict() == report.to_dict()


def test_string_cas_completion_flags_fail_closed() -> None:
    package = _make_diagnostic_ready(_package())
    for case in package["aggregate_cases"]:
        case["metadata_chain_complete"] = "true"
        case["cas_replay_complete"] = "true"
    package = _rehash(package)

    report = dry_run_approved_input(
        package, observed_source_manifest=_observed_manifest(package)
    )

    assert report.status == "blocked"
    assert report.approved_input_ready is False
    assert report.aggregate_cas_complete is False
    assert sum(
        issue.code is ApprovedInputIssueCode.AGGREGATE_CAS_UNPROVEN
        for issue in report.issues
    ) == len(package["aggregate_cases"])


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("pending_candidate_record_ids", "[]"),
        ("missing_candidate_record_ids", "[]"),
        ("rejected_candidate_record_ids", "[]"),
        ("unresolved_blockers", "[]"),
        ("candidate_count", "5"),
    ],
)
def test_b6_ready_requires_typed_empty_blockers_and_integer_counts(
    field_name: str, value: object
) -> None:
    package = _make_diagnostic_ready(_package())
    package["gate_state"]["b6"][field_name] = value
    package = _rehash(package)

    report = dry_run_approved_input(
        package, observed_source_manifest=_observed_manifest(package)
    )

    assert report.status == "blocked"
    assert report.approved_input_ready is False
    assert any(
        issue.code is ApprovedInputIssueCode.B6_GATE_NOT_READY
        for issue in report.issues
    )


def test_true_authority_flag_is_an_issue_even_with_valid_package_hash() -> None:
    package = _package()
    package["authority"]["write_authority"] = True
    package = _rehash(package)
    report = dry_run_approved_input(
        package, observed_source_manifest=_observed_manifest(_package())
    )
    assert any(
        issue.code is ApprovedInputIssueCode.AUTHORITY_FLAG_TRUE
        for issue in report.issues
    )


def test_controlled_entrypoint_requires_hash_bound_source_batches() -> None:
    package = _make_diagnostic_ready(_package())
    package = _rehash(package)

    report = dry_run_approved_input_with_source_preflight(
        package,
        observed_source_manifest=_observed_manifest(package),
        required_project_ids=("proj",),
    )

    assert report.status == "blocked"
    assert report.approved_input_ready is False
    assert report.source_batch_preflight_complete is False
    assert report.write_permitted is False
    assert report.migration_ready is False
    assert any(
        issue.code is ApprovedInputIssueCode.SOURCE_BATCH_BINDING_MISSING
        for issue in report.issues
    )


def test_controlled_entrypoint_reopens_bound_files_and_can_be_diagnostic_ready(
    tmp_path: Path,
) -> None:
    package = _make_diagnostic_ready(_package())
    rows = _source_rows(tmp_path)
    package["source_batch_bindings"] = [row.to_dict() for row in rows]
    package["source_batch_binding_sha256"] = canonical_source_batch_binding_sha256(rows)
    package = _rehash(package)

    report = dry_run_approved_input_with_source_preflight(
        package,
        observed_source_manifest=_observed_manifest(package),
        required_project_ids=("proj",),
    )

    assert report.status == "ready"
    assert report.approved_input_ready is True
    assert report.source_batch_preflight_complete is True
    assert report.source_batch_preflight is not None
    assert report.source_batch_preflight.source_evidence_complete is True
    assert report.issues == ()
    assert report.write_permitted is False
    assert report.migration_ready is False


def test_controlled_entrypoint_blocks_when_bound_file_changes(tmp_path: Path) -> None:
    package = _make_diagnostic_ready(_package())
    rows = _source_rows(tmp_path)
    package["source_batch_bindings"] = [row.to_dict() for row in rows]
    package["source_batch_binding_sha256"] = canonical_source_batch_binding_sha256(rows)
    package = _rehash(package)
    Path(rows[0].listing_path).write_bytes(b"tampered")

    report = dry_run_approved_input_with_source_preflight(
        package,
        observed_source_manifest=_observed_manifest(package),
        required_project_ids=("proj",),
    )

    assert report.status == "blocked"
    assert report.approved_input_ready is False
    assert report.source_batch_preflight is not None
    assert report.source_batch_preflight.source_evidence_complete is False
    assert any(
        issue.code is ApprovedInputIssueCode.SOURCE_BATCH_PREFLIGHT_BLOCKED
        for issue in report.issues
    )


def test_approved_input_report_rejects_non_boolean_readiness_flags() -> None:
    base = dry_run_approved_input(_package())
    with pytest.raises(
        ApprovedInputDryRunError, match="approved_input_ready must be boolean"
    ):
        ApprovedInputDryRunReport(
            status=base.status,
            approved_input_ready="false",
            source_manifest_replay_complete=base.source_manifest_replay_complete,
            reviewer_outcomes_complete=base.reviewer_outcomes_complete,
            source_lineage_complete=base.source_lineage_complete,
            aggregate_cas_complete=base.aggregate_cas_complete,
            residual_blockers_clear=base.residual_blockers_clear,
            write_permitted=base.write_permitted,
            migration_ready=base.migration_ready,
            issues=base.issues,
        )


def test_controlled_approved_input_report_rejects_non_boolean_source_preflight_flag() -> (
    None
):
    base = dry_run_approved_input(_package())
    issue = ApprovedInputDryRunIssue(
        ApprovedInputIssueCode.SOURCE_BATCH_BINDING_MISSING,
        "source_batch_bindings",
        "fixture issue",
    )
    with pytest.raises(
        ApprovedInputDryRunError,
        match="source_batch_preflight_complete must be boolean",
    ):
        ControlledApprovedInputDryRunReport(
            status="blocked",
            approved_input_ready=False,
            base_report=base,
            source_batch_preflight=None,
            source_batch_preflight_complete="false",
            source_batch_binding_sha256="",
            issues=(issue,),
        )
