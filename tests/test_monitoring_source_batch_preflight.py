from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from services.api.app.monitoring_source_batch_preflight import (
    SourceBatchIssueCode,
    SourceBatchPreflightError,
    SourceBatchRecord,
    assess_source_batch_preflight,
)


def _write_source(tmp_path: Path, name: str, content: bytes) -> tuple[str, int, str]:
    path = tmp_path / name
    path.write_bytes(content)
    return str(path), len(content), hashlib.sha256(content).hexdigest()


def _record(
    tmp_path: Path, *, project_id: str, batch_ref: str, content: bytes, **overrides
):
    path, size, digest = _write_source(tmp_path, f"{batch_ref}.xlsx", content)
    values = dict(
        project_id=project_id,
        batch_ref=batch_ref,
        snapshot_date="2026-01-01",
        listing_path=path,
        listing_bytes=size,
        listing_sha256=digest,
        listing_class="raw_full_snapshot",
        source_status="confirmed",
        full_snapshot_proven=True,
    )
    values.update(overrides)
    return SourceBatchRecord(**values)


def test_two_distinct_full_batches_are_complete_but_never_authorized(
    tmp_path: Path,
) -> None:
    rows = (
        _record(tmp_path, project_id="proj", batch_ref="batch-1", content=b"one"),
        _record(tmp_path, project_id="proj", batch_ref="batch-2", content=b"two"),
    )

    report = assess_source_batch_preflight(rows, required_project_ids=("proj",))

    assert report.status == "eligible_for_next_gate"
    assert report.source_evidence_complete is True
    assert report.eligible_batch_counts == (("proj", 2),)
    assert report.issues == ()
    assert report.diagnostic_only is True
    assert report.runtime_activation_permitted is False
    assert report.provider_call_permitted is False
    assert report.write_permitted is False
    assert report.medical_confirmation_permitted is False
    assert report.to_dict()["report_sha256"] == report.report_sha256


def test_missing_path_and_hash_mismatch_fail_closed(tmp_path: Path) -> None:
    first = _record(tmp_path, project_id="proj", batch_ref="batch-1", content=b"one")
    second = _record(tmp_path, project_id="proj", batch_ref="batch-2", content=b"two")
    tampered = replace(second, listing_sha256="a" * 64)
    missing = replace(first, listing_path=str(tmp_path / "missing.xlsx"))

    report = assess_source_batch_preflight(
        (missing, tampered), required_project_ids=("proj",)
    )
    codes = {issue.code for issue in report.issues}

    assert report.status == "blocked"
    assert SourceBatchIssueCode.PATH_MISSING in codes
    assert SourceBatchIssueCode.SHA256_MISMATCH in codes


def test_size_and_source_class_status_proof_are_checked(tmp_path: Path) -> None:
    row = _record(
        tmp_path,
        project_id="proj",
        batch_ref="batch-1",
        content=b"one",
        listing_bytes=99,
        listing_class="processed_transitional",
        source_status="passed",
        full_snapshot_proven=False,
    )

    report = assess_source_batch_preflight((row,), required_project_ids=("proj",))
    codes = {issue.code for issue in report.issues}

    assert {
        SourceBatchIssueCode.BYTE_SIZE_MISMATCH,
        SourceBatchIssueCode.SOURCE_CLASS_INELIGIBLE,
        SourceBatchIssueCode.SOURCE_STATUS_UNCONFIRMED,
        SourceBatchIssueCode.FULL_SNAPSHOT_UNPROVEN,
        SourceBatchIssueCode.BATCH_COVERAGE_INSUFFICIENT,
    }.issubset(codes)


def test_duplicate_batch_ref_and_content_cannot_supply_two_batches(
    tmp_path: Path,
) -> None:
    first = _record(tmp_path, project_id="proj", batch_ref="batch-1", content=b"one")
    duplicate_ref = replace(first, listing_path=first.listing_path)
    duplicate_content = _record(
        tmp_path, project_id="proj", batch_ref="batch-2", content=b"one"
    )

    report = assess_source_batch_preflight(
        (first, duplicate_ref, duplicate_content), required_project_ids=("proj",)
    )
    codes = {issue.code for issue in report.issues}

    assert SourceBatchIssueCode.BATCH_DUPLICATE in codes
    assert SourceBatchIssueCode.CONTENT_DUPLICATE in codes
    assert SourceBatchIssueCode.BATCH_COVERAGE_INSUFFICIENT not in codes


def test_project_set_mismatch_and_insufficient_coverage_are_visible(
    tmp_path: Path,
) -> None:
    row = _record(
        tmp_path, project_id="unexpected", batch_ref="batch-1", content=b"one"
    )

    report = assess_source_batch_preflight((row,), required_project_ids=("proj",))
    codes = {issue.code for issue in report.issues}

    assert SourceBatchIssueCode.PROJECT_SET_MISMATCH in codes
    assert SourceBatchIssueCode.BATCH_COVERAGE_INSUFFICIENT in codes


def test_symlink_is_not_admitted(tmp_path: Path) -> None:
    real_path, size, digest = _write_source(tmp_path, "real.xlsx", b"one")
    link = tmp_path / "link.xlsx"
    link.symlink_to(real_path)
    row = SourceBatchRecord(
        project_id="proj",
        batch_ref="batch-1",
        snapshot_date="2026-01-01",
        listing_path=str(link),
        listing_bytes=size,
        listing_sha256=digest,
        listing_class="raw_full_snapshot",
        source_status="confirmed",
        full_snapshot_proven=True,
    )

    report = assess_source_batch_preflight((row,), required_project_ids=("proj",))

    assert SourceBatchIssueCode.PATH_SYMLINK_UNSUPPORTED in {
        issue.code for issue in report.issues
    }


def test_record_rejects_invalid_shape() -> None:
    with pytest.raises(SourceBatchPreflightError):
        SourceBatchRecord(
            project_id="proj",
            batch_ref="batch-1",
            snapshot_date="2026-02-30",
            listing_path="/tmp/listing.xlsx",
            listing_bytes=1,
            listing_sha256="a" * 64,
            listing_class="raw_full_snapshot",
            source_status="confirmed",
            full_snapshot_proven=True,
        )

    with pytest.raises(SourceBatchPreflightError):
        SourceBatchRecord(
            project_id="proj",
            batch_ref="batch-1",
            snapshot_date="2026-01-01",
            listing_path="/tmp/listing.xlsx",
            listing_bytes=True,
            listing_sha256="a" * 64,
            listing_class="raw_full_snapshot",
            source_status="confirmed",
            full_snapshot_proven=True,
        )


def test_report_rejects_non_boolean_completion_flag(tmp_path: Path) -> None:
    rows = (
        _record(tmp_path, project_id="proj", batch_ref="batch-1", content=b"one"),
        _record(tmp_path, project_id="proj", batch_ref="batch-2", content=b"two"),
    )
    report = assess_source_batch_preflight(rows, required_project_ids=("proj",))
    with pytest.raises(SourceBatchPreflightError, match="source_evidence_complete"):
        replace(report, source_evidence_complete="true")
