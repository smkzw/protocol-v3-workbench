from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from services.api.app.monitoring_real_loop_acceptance import (
    ACCEPTANCE_ROLES,
    assess_real_loop_acceptance,
)
from services.api.app.monitoring_real_loop_mode_coverage import (
    MONITORING_MODE_CHECKPOINTS,
    MONITORING_MODE_IDS,
    MonitoringModeCoverageError,
    MonitoringModeCoverageIssueCode,
    MonitoringModeEvidence,
    assess_monitoring_mode_coverage,
)
from tests.test_monitoring_real_loop_acceptance import (
    EVIDENCE_CHAIN_KWARGS,
    clean_runs,
    prompt_manifest,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _accepted():
    runs = clean_runs()
    report = assess_real_loop_acceptance(
        runs,
        prompt_manifest=prompt_manifest(runs),
        **EVIDENCE_CHAIN_KWARGS,
    )
    return runs, report


def _complete_mode_rows():
    runs, report = _accepted()
    role_rows = {
        role: [row for row in runs if row.role == role] for role in ACCEPTANCE_ROLES
    }
    # The first three rows for each role have distinct projects in the fixture;
    # together they cover all five candidate projects.
    selected = role_rows[ACCEPTANCE_ROLES[0]][:3] + role_rows[ACCEPTANCE_ROLES[1]][:3]
    rows = tuple(
        MonitoringModeEvidence(
            evidence_id=f"mode-evidence:{index}",
            mode_id=MONITORING_MODE_IDS[index % len(MONITORING_MODE_IDS)],
            acceptance_run_id=run.run_id,
            evidence_refs=(f"mode-screen:{index}", f"mode-science:{index}"),
            evidence_sha256=_hash(f"mode-evidence:{index}"),
            summary=f"mode evidence {index}",
            checkpoint_ids=MONITORING_MODE_CHECKPOINTS[
                MONITORING_MODE_IDS[index % len(MONITORING_MODE_IDS)]
            ],
        )
        for index, run in enumerate(selected)
    )
    return runs, report, rows


def test_all_modes_and_roles_are_complete_for_review() -> None:
    runs, report, rows = _complete_mode_rows()

    result = assess_monitoring_mode_coverage(
        rows, acceptance_report=report, acceptance_runs=runs
    )

    assert result.status == "complete_for_mode_acceptance_review"
    assert result.coverage_complete is True
    assert result.covered_mode_ids == MONITORING_MODE_IDS
    assert result.missing_role_mode_keys == ()
    assert result.missing_project_ids == ()
    assert result.issues == ()
    assert result.authority_granted is False
    assert result.medical_confirmation_permitted is False
    assert result.runtime_write_permitted is False
    assert result.release_ready is False


def test_report_rejects_non_boolean_completion_flag() -> None:
    runs, report, rows = _complete_mode_rows()
    result = assess_monitoring_mode_coverage(
        rows, acceptance_report=report, acceptance_runs=runs
    )

    with pytest.raises(MonitoringModeCoverageError, match="strict boolean"):
        replace(result, coverage_complete="true")


def test_no_real_loop_report_or_mode_rows_is_blocked() -> None:
    result = assess_monitoring_mode_coverage(
        (), acceptance_report=None, acceptance_runs=()
    )

    codes = {issue.code for issue in result.issues}
    assert result.status == "blocked"
    assert MonitoringModeCoverageIssueCode.ACCEPTANCE_REPORT_MISSING in codes
    assert MonitoringModeCoverageIssueCode.ROLE_MODE_MISSING in codes
    assert MonitoringModeCoverageIssueCode.PROJECT_COVERAGE_MISSING in codes


def test_dirty_or_non_browser_run_cannot_satisfy_mode() -> None:
    runs, report, rows = _complete_mode_rows()
    dirty_run = replace(runs[0], api_login_used=True)
    dirty_rows = tuple(
        replace(row, acceptance_run_id=dirty_run.run_id) if index == 0 else row
        for index, row in enumerate(rows)
    )
    runs = (dirty_run, *runs[1:])

    result = assess_monitoring_mode_coverage(
        dirty_rows, acceptance_report=report, acceptance_runs=runs
    )

    assert result.status == "blocked"
    assert MonitoringModeCoverageIssueCode.ACCEPTANCE_RUN_NOT_CLEAN in {
        issue.code for issue in result.issues
    }


def test_duplicate_role_mode_and_hash_are_not_counted_twice() -> None:
    runs, report, rows = _complete_mode_rows()
    duplicate = replace(
        rows[0],
        evidence_id="mode-evidence:duplicate",
        evidence_sha256=rows[0].evidence_sha256,
    )

    result = assess_monitoring_mode_coverage(
        (*rows, duplicate), acceptance_report=report, acceptance_runs=runs
    )

    codes = {issue.code for issue in result.issues}
    assert result.status == "blocked"
    assert MonitoringModeCoverageIssueCode.MODE_EVIDENCE_HASH_DUPLICATE in codes
    assert MonitoringModeCoverageIssueCode.ROLE_MODE_DUPLICATE in codes


def test_missing_role_mode_is_explicit() -> None:
    runs, report, rows = _complete_mode_rows()
    rows = tuple(row for row in rows if row.mode_id != MONITORING_MODE_IDS[-1])

    result = assess_monitoring_mode_coverage(
        rows, acceptance_report=report, acceptance_runs=runs
    )

    assert result.status == "blocked"
    assert "engineer:post_lock_fixed_total" in result.missing_role_mode_keys
    assert (
        "senior_medical_monitor:post_lock_fixed_total" in result.missing_role_mode_keys
    )


def test_mode_evidence_requires_a_valid_hash_and_summary() -> None:
    with pytest.raises(MonitoringModeCoverageError, match="evidence_sha256"):
        MonitoringModeEvidence(
            evidence_id="mode-evidence:invalid",
            mode_id=MONITORING_MODE_IDS[0],
            acceptance_run_id="run:1",
            evidence_refs=("screen:1",),
            evidence_sha256="not-a-hash",
            summary="valid summary",
            checkpoint_ids=("full_snapshot_confirmed",),
        )
    with pytest.raises(MonitoringModeCoverageError, match="summary"):
        MonitoringModeEvidence(
            evidence_id="mode-evidence:invalid-summary",
            mode_id=MONITORING_MODE_IDS[0],
            acceptance_run_id="run:1",
            evidence_refs=("screen:1",),
            evidence_sha256=_hash("summary"),
            summary="",
            checkpoint_ids=("full_snapshot_confirmed",),
        )


def test_mode_evidence_hash_rejects_noncanonical_shape() -> None:
    cases = (
        ("uppercase", "A" * 64, "lowercase SHA-256"),
        ("padded", "a" * 64 + " ", "lowercase SHA-256"),
        ("nonstring", ["a" * 64], "string SHA-256"),
    )
    for label, value, message in cases:
        with pytest.raises(
            MonitoringModeCoverageError,
            match=message,
        ):
            MonitoringModeEvidence(
                evidence_id=f"mode-evidence:shape-{label}",
                mode_id=MONITORING_MODE_IDS[0],
                acceptance_run_id="run:shape",
                evidence_refs=("screen:shape",),
                evidence_sha256=value,
                summary="valid summary",
                checkpoint_ids=("full_snapshot_confirmed",),
            )


def test_mode_evidence_requires_all_mode_specific_checkpoints() -> None:
    runs, report, rows = _complete_mode_rows()
    incomplete = replace(rows[0], checkpoint_ids=("full_snapshot_confirmed",))

    result = assess_monitoring_mode_coverage(
        (incomplete, *rows[1:]), acceptance_report=report, acceptance_runs=runs
    )

    assert result.status == "blocked"
    assert MonitoringModeCoverageIssueCode.MODE_CHECKPOINTS_MISSING in {
        issue.code for issue in result.issues
    }


def test_mode_evidence_rejects_checkpoint_from_another_mode() -> None:
    with pytest.raises(MonitoringModeCoverageError, match="unsupported values"):
        MonitoringModeEvidence(
            evidence_id="mode-evidence:unsupported-checkpoint",
            mode_id="daily_incremental",
            acceptance_run_id="run:1",
            evidence_refs=("screen:1",),
            evidence_sha256=_hash("unsupported-checkpoint"),
            summary="valid summary",
            checkpoint_ids=("full_recompute_completed",),
        )


def test_mode_evidence_rejects_non_string_identity_fields() -> None:
    with pytest.raises(MonitoringModeCoverageError, match="evidence_id must be a string"):
        MonitoringModeEvidence(
            evidence_id=123,  # type: ignore[arg-type]
            mode_id=MONITORING_MODE_IDS[0],
            acceptance_run_id="run:1",
            evidence_refs=("screen:1",),
            evidence_sha256=_hash("identity"),
            summary="valid summary",
            checkpoint_ids=("full_snapshot_confirmed",),
        )
    with pytest.raises(MonitoringModeCoverageError, match="evidence_sha256 must be a string"):
        MonitoringModeEvidence(
            evidence_id="mode-evidence:invalid-hash",
            mode_id=MONITORING_MODE_IDS[0],
            acceptance_run_id="run:1",
            evidence_refs=("screen:1",),
            evidence_sha256=123,  # type: ignore[arg-type]
            summary="valid summary",
            checkpoint_ids=("full_snapshot_confirmed",),
        )
    with pytest.raises(MonitoringModeCoverageError, match="summary must be a string"):
        MonitoringModeEvidence(
            evidence_id="mode-evidence:invalid-summary",
            mode_id=MONITORING_MODE_IDS[0],
            acceptance_run_id="run:1",
            evidence_refs=("screen:1",),
            evidence_sha256=_hash("summary"),
            summary=123,  # type: ignore[arg-type]
            checkpoint_ids=("full_snapshot_confirmed",),
        )
    with pytest.raises(MonitoringModeCoverageError, match="collection of strings"):
        MonitoringModeEvidence(
            evidence_id="mode-evidence:scalar-ref",
            mode_id=MONITORING_MODE_IDS[0],
            acceptance_run_id="run:1",
            evidence_refs="screen:1",  # type: ignore[arg-type]
            evidence_sha256=_hash("refs"),
            summary="valid summary",
            checkpoint_ids=("full_snapshot_confirmed",),
        )


def test_mode_report_rejects_scalar_coverage_collections() -> None:
    runs, report, rows = _complete_mode_rows()
    result = assess_monitoring_mode_coverage(
        rows, acceptance_report=report, acceptance_runs=runs
    )

    with pytest.raises(MonitoringModeCoverageError, match="must be a collection"):
        replace(result, covered_mode_ids=MONITORING_MODE_IDS[0])  # type: ignore[arg-type]


def test_mode_set_cannot_be_narrowed_by_caller() -> None:
    runs, report, rows = _complete_mode_rows()

    result = assess_monitoring_mode_coverage(
        rows,
        acceptance_report=report,
        acceptance_runs=runs,
        expected_mode_ids=MONITORING_MODE_IDS[:2],
    )

    assert result.status == "blocked"
    assert MonitoringModeCoverageIssueCode.MODE_SET_MISMATCH in {
        issue.code for issue in result.issues
    }


def test_role_and_project_sets_cannot_be_narrowed_by_caller() -> None:
    runs, report, rows = _complete_mode_rows()

    result = assess_monitoring_mode_coverage(
        rows,
        acceptance_report=report,
        acceptance_runs=runs,
        expected_roles=ACCEPTANCE_ROLES[:1],
        allowed_project_ids=("proj_mgk10_sar_real",),
    )

    codes = {issue.code for issue in result.issues}
    assert result.status == "blocked"
    assert MonitoringModeCoverageIssueCode.ROLE_SET_MISMATCH in codes
    assert MonitoringModeCoverageIssueCode.PROJECT_SET_MISMATCH in codes


def test_report_type_is_not_coerced_from_a_mapping() -> None:
    runs, _, rows = _complete_mode_rows()

    result = assess_monitoring_mode_coverage(
        rows,
        acceptance_report={},
        acceptance_runs=runs,  # type: ignore[arg-type]
    )

    assert result.status == "blocked"
    assert MonitoringModeCoverageIssueCode.ACCEPTANCE_REPORT_TYPE_INVALID in {
        issue.code for issue in result.issues
    }
