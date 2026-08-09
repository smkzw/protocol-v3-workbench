from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from services.api.app.monitoring_nonfunctional_evidence_revalidation import (
    NONFUNCTIONAL_EVIDENCE_SCHEMA_VERSION,
    NonfunctionalEvidenceRevalidationError,
    REQUIRED_NONFUNCTIONAL_CONTROL_IDS,
    NonfunctionalEvidenceIssueCode,
    revalidate_nonfunctional_evidence,
)
from services.api.app.monitoring_release_dossier import REQUIRED_DOSSIER_CONTROLS


def _manifest(tmp_path: Path) -> dict:
    records = []
    for index, control_id in enumerate(REQUIRED_NONFUNCTIONAL_CONTROL_IDS):
        section_id = next(
            section
            for section, controls in REQUIRED_DOSSIER_CONTROLS.items()
            if control_id in controls
        )
        path = tmp_path / f"evidence-{index}.txt"
        payload = f"synthetic evidence for {control_id}\n".encode("utf-8")
        path.write_bytes(payload)
        records.append(
            {
                "evidence_id": f"evidence-{index}",
                "section_id": section_id,
                "control_id": control_id,
                "path": path.relative_to(tmp_path).as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "status": "passed",
                "summary": f"synthetic evidence for {control_id}",
            }
        )
    return {
        "schema_version": NONFUNCTIONAL_EVIDENCE_SCHEMA_VERSION,
        "mode": "read_only",
        "authority_granted": False,
        "release_ready": False,
        "records": records,
    }


def test_complete_synthetic_manifest_is_fresh_but_never_release_ready(
    tmp_path: Path,
) -> None:
    report = revalidate_nonfunctional_evidence(
        _manifest(tmp_path), workspace_root=tmp_path
    )

    assert report.status == "fresh"
    assert report.evidence_fresh is True
    assert report.record_count == len(REQUIRED_NONFUNCTIONAL_CONTROL_IDS)
    assert report.source_match_count == report.record_count
    assert report.control_count == report.record_count
    assert report.covered_control_ids == REQUIRED_NONFUNCTIONAL_CONTROL_IDS
    assert report.unmet_control_ids == ()
    assert report.issues == ()
    assert report.release_ready is False
    assert report.read_only is True
    assert report.authority_granted is False
    assert len(report.report_sha256) == 64


def test_report_rejects_non_boolean_freshness_flag(tmp_path: Path) -> None:
    report = revalidate_nonfunctional_evidence(
        _manifest(tmp_path), workspace_root=tmp_path
    )

    with pytest.raises(NonfunctionalEvidenceRevalidationError, match="strict boolean"):
        from dataclasses import replace

        replace(report, evidence_fresh="true")


def test_drifted_file_blocks_and_preserves_other_diagnostics(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    first = Path(manifest["records"][0]["path"])
    (tmp_path / first).write_text("drifted", encoding="utf-8")

    report = revalidate_nonfunctional_evidence(manifest, workspace_root=tmp_path)

    assert report.status == "blocked"
    assert report.evidence_fresh is False
    assert any(
        issue.code is NonfunctionalEvidenceIssueCode.SOURCE_BYTES_MISMATCH
        or issue.code is NonfunctionalEvidenceIssueCode.SOURCE_SHA256_MISMATCH
        for issue in report.issues
    )


def test_missing_duplicate_unknown_and_unsafe_controls_fail_closed(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    manifest["records"] = deepcopy(manifest["records"][:-1])
    duplicate = deepcopy(manifest["records"][0])
    duplicate["evidence_id"] = "duplicate-evidence"
    duplicate["control_id"] = manifest["records"][0]["control_id"]
    manifest["records"].append(duplicate)
    unknown = deepcopy(manifest["records"][1])
    unknown["evidence_id"] = "unknown-evidence"
    unknown["control_id"] = "not-a-commercial-control"
    unknown["section_id"] = "nonfunctional_validation"
    manifest["records"].append(unknown)
    unsafe = deepcopy(manifest["records"][2])
    unsafe["evidence_id"] = "unsafe-evidence"
    unsafe["path"] = "../escape.txt"
    manifest["records"].append(unsafe)

    report = revalidate_nonfunctional_evidence(manifest, workspace_root=tmp_path)
    codes = {issue.code for issue in report.issues}

    assert report.status == "blocked"
    assert NonfunctionalEvidenceIssueCode.CONTROL_MISSING in codes
    assert NonfunctionalEvidenceIssueCode.CONTROL_DUPLICATE in codes
    assert NonfunctionalEvidenceIssueCode.CONTROL_UNKNOWN in codes
    assert NonfunctionalEvidenceIssueCode.PATH_UNSAFE in codes


def test_true_authority_or_release_flags_are_rejected(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["authority_granted"] = True
    manifest["release_ready"] = True

    report = revalidate_nonfunctional_evidence(manifest, workspace_root=tmp_path)
    codes = {issue.code for issue in report.issues}

    assert report.status == "blocked"
    assert NonfunctionalEvidenceIssueCode.AUTHORITY_FLAG_TRUE in codes
    assert NonfunctionalEvidenceIssueCode.RELEASE_READY_FLAG_TRUE in codes


def test_typed_record_fields_and_symlink_paths_fail_closed(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["records"][0]["evidence_id"] = 1001
    manifest["records"][1]["path"] = 1001
    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    manifest["records"][2]["path"] = link.relative_to(tmp_path).as_posix()

    report = revalidate_nonfunctional_evidence(manifest, workspace_root=tmp_path)
    codes = {issue.code for issue in report.issues}

    assert report.status == "blocked"
    assert NonfunctionalEvidenceIssueCode.RECORD_FIELD_INVALID in codes
    assert NonfunctionalEvidenceIssueCode.SOURCE_SYMLINK_UNSUPPORTED in codes


def test_uppercase_or_padded_sha_is_not_normalized_into_valid_evidence(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    manifest["records"][0]["sha256"] = manifest["records"][0]["sha256"].upper()
    manifest["records"][1]["sha256"] = f" {manifest['records'][1]['sha256']}"

    report = revalidate_nonfunctional_evidence(manifest, workspace_root=tmp_path)
    invalid_subjects = {
        issue.subject
        for issue in report.issues
        if issue.code is NonfunctionalEvidenceIssueCode.RECORD_FIELD_INVALID
    }

    assert report.status == "blocked"
    assert {"evidence-0", "evidence-1"}.issubset(invalid_subjects)


def test_empty_current_workspace_manifest_is_blocked_without_inventing_evidence(
    tmp_path: Path,
) -> None:
    manifest = {
        "schema_version": NONFUNCTIONAL_EVIDENCE_SCHEMA_VERSION,
        "mode": "read_only",
        "authority_granted": False,
        "records": [],
    }

    report = revalidate_nonfunctional_evidence(manifest, workspace_root=tmp_path)

    assert report.status == "blocked"
    assert report.evidence_fresh is False
    assert report.record_count == 0
    assert report.source_match_count == 0
    assert report.control_count == 0
    assert report.covered_control_ids == ()
    assert report.unmet_control_ids == REQUIRED_NONFUNCTIONAL_CONTROL_IDS
    assert len(report.issues) == len(REQUIRED_NONFUNCTIONAL_CONTROL_IDS)
    assert all(
        issue.code is NonfunctionalEvidenceIssueCode.CONTROL_MISSING
        for issue in report.issues
    )
