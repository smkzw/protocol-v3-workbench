from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from services.api.app.monitoring_candidate_source_identity import (
    CandidateSourceIdentityError,
    CandidateSourceIdentityIssueCode,
    CandidateSourceRecord,
    build_candidate_source_record_from_paths,
    revalidate_candidate_source_identities,
)


REQUIRED = ("proj_rux_03_002", "proj_mgk10_sar_real")


def _file(tmp_path: Path, name: str, payload: bytes) -> tuple[str, int, str]:
    path = tmp_path / name
    path.write_bytes(payload)
    return str(path), len(payload), sha256(payload).hexdigest()


def _record(
    tmp_path: Path, project_id: str = "proj_rux_03_002"
) -> CandidateSourceRecord:
    listing = _file(
        tmp_path, f"{project_id}-listing.xlsx", b"listing-" + project_id.encode()
    )
    protocol = _file(
        tmp_path, f"{project_id}-protocol.docx", b"protocol-" + project_id.encode()
    )
    return CandidateSourceRecord(
        project_id=project_id,
        label=project_id,
        canonical_now=True,
        candidate_only=False,
        listing_path=listing[0],
        listing_bytes=listing[1],
        listing_sha256=listing[2],
        protocol_path=protocol[0],
        protocol_bytes=protocol[1],
        protocol_sha256=protocol[2],
        source_class="raw_locked_snapshot",
        source_status="confirmed",
        full_snapshot_proven=True,
        adapter_registered=True,
        adapter_project_id=project_id,
        mapping_status="reviewed",
    )


def test_revalidation_reopens_both_files_but_remains_diagnostic_only(
    tmp_path: Path,
) -> None:
    first = _record(tmp_path)
    second = _record(tmp_path, "proj_mgk10_sar_real")

    report = revalidate_candidate_source_identities(
        (first, second), required_project_ids=REQUIRED
    )

    assert report.status == "revalidated_for_next_gate"
    assert report.identity_evidence_complete is True
    assert report.observed_file_count == 4
    assert report.issues == ()
    assert report.diagnostic_only is True
    assert report.runtime_activation_permitted is False
    assert report.provider_call_permitted is False
    assert report.write_permitted is False
    assert report.medical_confirmation_permitted is False
    assert report.to_dict()["report_sha256"] == report.report_sha256


def test_report_rejects_non_boolean_completion_and_authority_flags(
    tmp_path: Path,
) -> None:
    first = _record(tmp_path)
    report = revalidate_candidate_source_identities(
        (first,), required_project_ids=(first.project_id,)
    )

    with pytest.raises(CandidateSourceIdentityError, match="strict boolean"):
        replace(report, identity_evidence_complete="true")
    with pytest.raises(CandidateSourceIdentityError, match="strict boolean"):
        replace(report, provider_call_permitted="false")


def test_candidate_mapping_and_source_state_are_explicitly_blocked(
    tmp_path: Path,
) -> None:
    candidate = replace(
        _record(tmp_path),
        canonical_now=False,
        candidate_only=True,
        source_status="candidate",
        full_snapshot_proven=False,
        adapter_registered=False,
        adapter_project_id="",
        mapping_status="blocked_pending_mapping_review",
        non_monitoring_aliases=("proj_my008_pnh_3_01",),
    )

    report = revalidate_candidate_source_identities(
        (candidate,), required_project_ids=(candidate.project_id,)
    )
    codes = {item.code for item in report.issues}

    assert report.status == "blocked"
    assert CandidateSourceIdentityIssueCode.MAPPING_NOT_REVIEWED in codes
    assert CandidateSourceIdentityIssueCode.SOURCE_NOT_CONFIRMED in codes
    assert CandidateSourceIdentityIssueCode.FULL_SNAPSHOT_UNPROVEN in codes


def test_non_monitoring_alias_cannot_be_reused_as_candidate_identity(
    tmp_path: Path,
) -> None:
    candidate = replace(
        _record(tmp_path),
        project_id="proj_my008_3_02_candidate",
        label="MY008-3-02",
        canonical_now=False,
        candidate_only=True,
        adapter_registered=False,
        adapter_project_id="",
        mapping_status="not_reviewed",
        non_monitoring_aliases=("proj_my008_3_02_candidate",),
    )

    report = revalidate_candidate_source_identities(
        (candidate,), required_project_ids=(candidate.project_id,)
    )

    assert any(
        issue.code == CandidateSourceIdentityIssueCode.NON_MONITORING_ALIAS_REUSE
        for issue in report.issues
    )


def test_adapter_cannot_bind_to_non_monitoring_alias(tmp_path: Path) -> None:
    candidate = replace(
        _record(tmp_path),
        project_id="proj_my008_3_02_candidate",
        label="MY008-3-02",
        canonical_now=False,
        candidate_only=True,
        adapter_registered=True,
        adapter_project_id="proj_my008_pnh_3_01",
        mapping_status="not_reviewed",
        non_monitoring_aliases=("proj_my008_pnh_3_01",),
    )

    report = revalidate_candidate_source_identities(
        (candidate,), required_project_ids=(candidate.project_id,)
    )

    assert any(
        issue.code == CandidateSourceIdentityIssueCode.NON_MONITORING_ALIAS_REUSE
        for issue in report.issues
    )


def test_hash_drift_missing_file_and_duplicate_content_fail_closed(
    tmp_path: Path,
) -> None:
    first = _record(tmp_path)
    second = _record(tmp_path, "proj_mgk10_sar_real")
    tampered = first.listing_path
    Path(tampered).write_bytes(b"tampered")
    missing = Path(second.protocol_path)
    missing.unlink()
    duplicate = replace(
        second,
        listing_path=first.listing_path,
        listing_bytes=first.listing_bytes,
        listing_sha256=first.listing_sha256,
    )

    report = revalidate_candidate_source_identities(
        (first, duplicate), required_project_ids=REQUIRED
    )
    codes = {item.code for item in report.issues}

    assert report.status == "blocked"
    assert CandidateSourceIdentityIssueCode.SHA256_MISMATCH in codes
    assert CandidateSourceIdentityIssueCode.PATH_MISSING in codes
    assert CandidateSourceIdentityIssueCode.CONTENT_DUPLICATE in codes


def test_symlink_is_not_an_acceptable_source_path(tmp_path: Path) -> None:
    record = _record(tmp_path)
    link = tmp_path / "listing-link.xlsx"
    Path(record.listing_path).rename(link)
    symlink_record = replace(
        record, listing_path=str(tmp_path / "listing-link-alias.xlsx")
    )
    Path(symlink_record.listing_path).symlink_to(link)

    report = revalidate_candidate_source_identities(
        (symlink_record,), required_project_ids=(record.project_id,)
    )

    assert any(
        issue.code == CandidateSourceIdentityIssueCode.PATH_SYMLINK_UNSUPPORTED
        for issue in report.issues
    )


def test_record_rejects_canonical_candidate_conflict() -> None:
    with pytest.raises(CandidateSourceIdentityError):
        CandidateSourceRecord(
            project_id="proj_example",
            label="Example",
            canonical_now=True,
            candidate_only=True,
            listing_path="listing.xlsx",
            listing_bytes=1,
            listing_sha256="a" * 64,
            protocol_path="protocol.docx",
            protocol_bytes=1,
            protocol_sha256="b" * 64,
            source_class="raw_full_snapshot",
            source_status="confirmed",
            full_snapshot_proven=True,
            adapter_registered=True,
            adapter_project_id="proj_example",
            mapping_status="reviewed",
        )


def test_candidate_builder_reads_explicit_files_but_never_creates_admission_state(
    tmp_path: Path,
) -> None:
    listing = tmp_path / "listing.xlsx"
    protocol = tmp_path / "protocol.docx"
    listing.write_bytes(b"candidate listing")
    protocol.write_bytes(b"candidate protocol")

    record = build_candidate_source_record_from_paths(
        project_id="proj_my008_3_01_candidate",
        label="MY008-3-01",
        listing_path=listing,
        protocol_path=protocol,
        non_monitoring_aliases=("proj_my008_pnh_3_01",),
    )

    assert record.candidate_only is True
    assert record.canonical_now is False
    assert record.adapter_registered is False
    assert record.adapter_project_id == ""
    assert record.source_status == "candidate"
    assert record.full_snapshot_proven is False
    assert record.listing_bytes == listing.stat().st_size
    assert record.protocol_bytes == protocol.stat().st_size
    report = revalidate_candidate_source_identities(
        (record,), required_project_ids=(record.project_id,)
    )
    assert report.status == "blocked"
    assert report.runtime_activation_permitted is False
    assert report.provider_call_permitted is False


def test_candidate_builder_rejects_missing_and_symlinked_files(tmp_path: Path) -> None:
    listing = tmp_path / "listing.xlsx"
    protocol = tmp_path / "protocol.docx"
    listing.write_bytes(b"listing")
    protocol.write_bytes(b"protocol")

    with pytest.raises(CandidateSourceIdentityError, match="does not exist"):
        build_candidate_source_record_from_paths(
            project_id="proj_example_candidate",
            label="Example",
            listing_path=tmp_path / "missing.xlsx",
            protocol_path=protocol,
        )

    symlink = tmp_path / "listing-alias.xlsx"
    symlink.symlink_to(listing)
    with pytest.raises(CandidateSourceIdentityError, match="symlink"):
        build_candidate_source_record_from_paths(
            project_id="proj_example_candidate",
            label="Example",
            listing_path=symlink,
            protocol_path=protocol,
        )
