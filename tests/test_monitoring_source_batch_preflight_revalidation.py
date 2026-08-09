from __future__ import annotations

import hashlib
import json
from pathlib import Path

from services.api.app.monitoring_source_batch_preflight import (
    CANONICAL_MONITORING_PROJECT_IDS,
)
from services.api.app.monitoring_source_batch_preflight_revalidation import (
    SourceBatchPreflightRevalidationIssueCode,
    revalidate_source_batch_preflight_file,
    revalidate_source_batch_preflight_payload,
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _payload(tmp_path: Path) -> dict:
    projects = []
    for project_index, project_id in enumerate(CANONICAL_MONITORING_PROJECT_IDS):
        listing_evidence = []
        for batch_index in range(2):
            content = f"{project_id}-{batch_index}".encode()
            path = tmp_path / f"{project_index}-{batch_index}.txt"
            path.write_bytes(content)
            listing_evidence.append(
                {
                    "batch_ref": f"batch-{project_index}-{batch_index}",
                    "snapshot_date": f"2026-07-{project_index + batch_index + 1:02d}",
                    "path": str(path),
                    "bytes": len(content),
                    "sha256": _sha256(content),
                    "source_class": "raw_full_snapshot",
                    "source_status": "confirmed",
                    "full_snapshot_proven": True,
                    "eligible_for_future_real_loop": True,
                    "reason": "synthetic contract fixture",
                }
            )
        projects.append(
            {
                "project_id": project_id,
                "label": project_id,
                "canonical_now": True,
                "adapter_module": "services.api.app.synthetic_monitoring_service",
                "protocol": {
                    "path": "synthetic-protocol.docx",
                    "bytes": 0,
                    "sha256": "0" * 64,
                    "role": "canonical_protocol",
                },
                "listing_evidence": listing_evidence,
                "distinct_provenance_complete_eligible_full_batch_count": 2,
                "admission_status": "ready_for_next_gate",
                "blockers": [],
            }
        )
    return {
        "schema_version": "medical-monitoring-real-source-batch-preflight-v1",
        "artifact_ref": "synthetic-source-preflight",
        "observed_at": "2026-08-03T04:00:00+08:00",
        "purpose": "synthetic contract fixture",
        "authority": {
            "read_only": True,
            "product_source_write_permitted": False,
            "runtime_write_permitted": False,
            "provider_call_permitted": False,
            "browser_login_permitted": False,
            "medical_confirmation_permitted": False,
            "batch_creation_performed": False,
            "batch_mutation_performed": False,
        },
        "source_policy": {
            "canonical_monitoring_project_ids": list(CANONICAL_MONITORING_PROJECT_IDS),
            "eligible_listing_classes_for_future_real_loop": [
                "raw_full_snapshot",
                "raw_locked_snapshot",
            ],
            "path_existence_is_not_batch_eligibility": True,
            "processed_restored_comparison_or_duplicate_files_do_not_count_as_a_second_batch": True,
        },
        "global_gates_at_observation": {},
        "projects": projects,
        "summary": {
            "projects_with_two_eligible_full_batches": list(
                CANONICAL_MONITORING_PROJECT_IDS
            ),
            "projects_with_at_least_one_eligible_full_batch": list(
                CANONICAL_MONITORING_PROJECT_IDS
            ),
            "real_loop_execution_ready": False,
            "approved_input_ready": False,
            "next_safe_action": "continue upstream gate review",
        },
    }


def test_payload_revalidation_replays_source_contract(tmp_path: Path) -> None:
    report = revalidate_source_batch_preflight_payload(_payload(tmp_path))

    assert report.status == "fresh"
    assert report.evidence_fresh is True
    assert report.payload_valid is True
    assert report.preflight_report_matches is True
    assert report.source_preflight_status == "eligible_for_next_gate"
    assert report.source_evidence_complete is True
    assert report.source_preflight_issue_count == 0
    assert report.eligible_batch_counts == tuple(
        (project_id, 2) for project_id in sorted(CANONICAL_MONITORING_PROJECT_IDS)
    )


def test_file_revalidation_checks_artifact_and_declared_source_bytes(
    tmp_path: Path,
) -> None:
    payload = _payload(tmp_path)
    artifact = tmp_path / "records" / "preflight.json"
    artifact.parent.mkdir()
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    artifact.write_bytes(raw)

    report = revalidate_source_batch_preflight_file(
        "records/preflight.json",
        expected_bytes=len(raw),
        expected_sha256=_sha256(raw),
        workspace_root=tmp_path,
    )

    assert report.status == "fresh"
    assert report.file_checked is True
    assert report.file_fresh is True

    first_source = Path(payload["projects"][0]["listing_evidence"][0]["path"])
    first_source.write_bytes(b"drift")
    drifted = revalidate_source_batch_preflight_payload(payload)
    assert drifted.status == "blocked"
    assert any(
        issue.code == SourceBatchPreflightRevalidationIssueCode.SOURCE_FILE_DRIFT
        for issue in drifted.issues
    )


def test_summary_or_authority_drift_blocks_without_promoting_source(
    tmp_path: Path,
) -> None:
    payload = _payload(tmp_path)
    payload["summary"]["projects_with_two_eligible_full_batches"] = []
    payload["authority"]["runtime_write_permitted"] = True

    report = revalidate_source_batch_preflight_payload(payload)

    assert report.status == "blocked"
    assert report.evidence_fresh is False
    codes = {issue.code for issue in report.issues}
    assert SourceBatchPreflightRevalidationIssueCode.AUTHORITY_FLAG_TRUE in codes
    assert SourceBatchPreflightRevalidationIssueCode.SUMMARY_DERIVED_MISMATCH in codes
    assert report.release_ready is False
    assert report.runtime_write_permitted is False


def test_excluded_candidate_without_batch_ref_is_not_promoted(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    content = b"excluded-comparison"
    path = tmp_path / "excluded.txt"
    path.write_bytes(content)
    payload["projects"][0]["listing_evidence"].append(
        {
            "batch_ref": None,
            "snapshot_date": "2026-07-31",
            "path": str(path),
            "bytes": len(content),
            "sha256": _sha256(content),
            "source_class": "comparison_workbook",
            "source_status": "excluded",
            "full_snapshot_proven": False,
            "eligible_for_future_real_loop": False,
            "reason": "comparison evidence",
        }
    )

    report = revalidate_source_batch_preflight_payload(payload)

    assert report.status == "fresh"
    assert report.batch_count == 10
    assert report.source_preflight_status == "eligible_for_next_gate"


def test_file_path_traversal_is_rejected(tmp_path: Path) -> None:
    report = revalidate_source_batch_preflight_file(
        "../preflight.json",
        expected_bytes=0,
        expected_sha256="0" * 64,
        workspace_root=tmp_path,
    )

    assert report.status == "blocked"
    assert any(
        issue.code == SourceBatchPreflightRevalidationIssueCode.FILE_PATH_UNSAFE
        for issue in report.issues
    )
