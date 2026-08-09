from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from services.api.app.monitoring_release_dossier import (
    REQUIRED_DOSSIER_CONTROLS,
    REQUIRED_DOSSIER_SECTION_IDS,
    REQUIRED_DOSSIER_SIGNOFF_ROLES,
    MonitoringReleaseDossier,
    MonitoringReleaseDossierSection,
    MonitoringReleaseDossierSignoff,
    ReleaseDossierSectionStatus,
)
from services.api.app.monitoring_release_dossier_revalidation import (
    ReleaseDossierRevalidationIssueCode,
    revalidate_release_dossier_file,
    revalidate_release_dossier_payload,
)


HASH = "a" * 64
NOW = "2026-08-03T01:45:00+08:00"


def _dossier(*, partial: bool = False) -> MonitoringReleaseDossier:
    sections = []
    for section_id in REQUIRED_DOSSIER_SECTION_IDS:
        controls = REQUIRED_DOSSIER_CONTROLS[section_id]
        covered = controls[:1] if partial else controls
        unmet = tuple(control for control in controls if control not in covered)
        sections.append(
            MonitoringReleaseDossierSection(
                section_id=section_id,
                status=(
                    ReleaseDossierSectionStatus.PARTIAL
                    if partial
                    else ReleaseDossierSectionStatus.PASSED
                ),
                evidence_ids=(f"evidence-{section_id}",),
                evidence_sha256=HASH,
                covered_control_ids=covered,
                unmet_control_ids=unmet,
                summary=f"evidence for {section_id}",
            )
        )
    signoffs = tuple(
        MonitoringReleaseDossierSignoff(
            role=role,
            actor_id=f"actor-{role}",
            signed_at=NOW,
            evidence_sha256=HASH,
        )
        for role in REQUIRED_DOSSIER_SIGNOFF_ROLES
    )
    return MonitoringReleaseDossier(
        dossier_id="dossier-revalidation",
        release_version="release-2026.08.03",
        generated_at=NOW,
        sections=tuple(sections),
        signoffs=signoffs,
    )


def test_canonical_complete_payload_is_fresh_but_not_authoritative() -> None:
    payload = _dossier().to_dict()

    report = revalidate_release_dossier_payload(payload)

    assert report.status == "fresh"
    assert report.evidence_fresh is True
    assert report.payload_valid is True
    assert report.dossier_hash_matches is True
    assert report.derived_fields_match is True
    assert report.file_checked is False
    assert report.file_fresh is False
    assert report.dossier_status == "passed"
    assert report.release_ready_observed is True
    assert report.issues == ()
    assert report.read_only is True
    assert report.authority_granted is False


def test_blocked_dossier_payload_can_be_fresh_without_being_release_ready() -> None:
    payload = _dossier(partial=True).to_dict()

    report = revalidate_release_dossier_payload(payload)

    assert report.status == "fresh"
    assert report.evidence_fresh is True
    assert report.dossier_status == "partial"
    assert report.release_ready_observed is False
    assert report.issues == ()


def test_derived_status_and_hash_drift_fail_closed() -> None:
    payload = _dossier().to_dict()
    payload["status"] = "blocked"
    payload["release_ready"] = False
    payload["dossier_sha256"] = "b" * 64

    report = revalidate_release_dossier_payload(payload)
    codes = {issue.code for issue in report.issues}

    assert report.status == "blocked"
    assert report.evidence_fresh is False
    assert ReleaseDossierRevalidationIssueCode.DOSSIER_HASH_MISMATCH in codes
    assert ReleaseDossierRevalidationIssueCode.DERIVED_STATUS_MISMATCH in codes


def test_authority_and_shape_drift_fail_closed() -> None:
    payload = _dossier().to_dict()
    payload["authority_granted"] = True
    payload["sections"][0]["covered_control_ids"] = ["not-a-control"]

    report = revalidate_release_dossier_payload(payload)
    codes = {issue.code for issue in report.issues}

    assert report.status == "blocked"
    assert ReleaseDossierRevalidationIssueCode.AUTHORITY_FLAG_TRUE in codes
    assert ReleaseDossierRevalidationIssueCode.DOSSIER_RECONSTRUCTION_FAILED in codes


def test_file_identity_and_json_are_revalidated(tmp_path: Path) -> None:
    payload = _dossier().to_dict()
    path = tmp_path / "dossier.json"
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(raw)

    report = revalidate_release_dossier_file(
        "dossier.json",
        expected_bytes=len(raw),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        workspace_root=tmp_path,
    )

    assert report.status == "fresh"
    assert report.file_checked is True
    assert report.file_fresh is True
    assert report.dossier_hash_matches is True


def test_file_drift_missing_and_unsafe_path_fail_closed(tmp_path: Path) -> None:
    payload = _dossier().to_dict()
    path = tmp_path / "dossier.json"
    raw = json.dumps(payload).encode("utf-8")
    path.write_bytes(raw)

    drift = revalidate_release_dossier_file(
        "dossier.json",
        expected_bytes=len(raw),
        expected_sha256="b" * 64,
        workspace_root=tmp_path,
    )
    missing = revalidate_release_dossier_file(
        "missing.json",
        expected_bytes=1,
        expected_sha256=HASH,
        workspace_root=tmp_path,
    )
    unsafe = revalidate_release_dossier_file(
        "../dossier.json",
        expected_bytes=len(raw),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        workspace_root=tmp_path,
    )

    assert drift.status == "blocked"
    assert ReleaseDossierRevalidationIssueCode.FILE_SHA256_MISMATCH in {
        issue.code for issue in drift.issues
    }
    assert missing.status == "blocked"
    assert ReleaseDossierRevalidationIssueCode.FILE_MISSING in {
        issue.code for issue in missing.issues
    }
    assert unsafe.status == "blocked"
    assert ReleaseDossierRevalidationIssueCode.FILE_PATH_UNSAFE in {
        issue.code for issue in unsafe.issues
    }


def test_payload_mutation_is_not_silently_repaired() -> None:
    payload = _dossier().to_dict()
    mutated = deepcopy(payload)
    mutated["signoffs"][0]["actor_id"] = "another-actor"

    report = revalidate_release_dossier_payload(mutated)

    assert report.status == "blocked"
    assert any(
        issue.code is ReleaseDossierRevalidationIssueCode.DOSSIER_HASH_MISMATCH
        for issue in report.issues
    )


def test_symlink_invalid_json_and_typed_file_metadata_fail_closed(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    symlink_report = revalidate_release_dossier_file(
        "link.json",
        expected_bytes=2,
        expected_sha256=hashlib.sha256(b"{}").hexdigest(),
        workspace_root=tmp_path,
    )

    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json", encoding="utf-8")
    invalid_raw = invalid.read_bytes()
    invalid_report = revalidate_release_dossier_file(
        "invalid.json",
        expected_bytes=len(invalid_raw),
        expected_sha256=hashlib.sha256(invalid_raw).hexdigest(),
        workspace_root=tmp_path,
    )

    typed_report = revalidate_release_dossier_file(
        "target.json",
        expected_bytes=True,  # type: ignore[arg-type]
        expected_sha256=hashlib.sha256(b"{}").hexdigest().upper(),
        workspace_root=tmp_path,
    )

    assert symlink_report.status == "blocked"
    assert ReleaseDossierRevalidationIssueCode.FILE_SYMLINK_UNSUPPORTED in {
        issue.code for issue in symlink_report.issues
    }
    assert invalid_report.status == "blocked"
    assert ReleaseDossierRevalidationIssueCode.FILE_JSON_INVALID in {
        issue.code for issue in invalid_report.issues
    }
    assert typed_report.status == "blocked"
    assert ReleaseDossierRevalidationIssueCode.PAYLOAD_SHAPE_INVALID in {
        issue.code for issue in typed_report.issues
    }
