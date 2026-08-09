from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from services.api.app.monitoring_aggregate_cas_replay import (
    MonitoringAggregateCasCase,
    MonitoringAggregateCasEvent,
    build_monitoring_aggregate_cas_replay_report,
)
from services.api.app.monitoring_aggregate_cas_revalidation import (
    MonitoringAggregateCasRevalidationIssueCode,
    revalidate_aggregate_cas_file,
    revalidate_aggregate_cas_payload,
)


UTC = timezone.utc


def _ts(second: int) -> str:
    return datetime(2026, 8, 3, 8, 0, second, tzinfo=UTC).isoformat()


def _source(*, expected_versions: bool = False) -> dict:
    chain = [
        {
            "record_id": "disp-001",
            "previous_state": "pending_review",
            "new_state": "reviewed",
            "created_at": _ts(1),
        },
        {
            "record_id": "disp-002",
            "previous_state": "reviewed",
            "new_state": "query_draft",
            "created_at": _ts(2),
        },
    ]
    if expected_versions:
        chain[0]["expected_version"] = 0
        chain[1]["expected_version"] = 1
    return {
        "read_only": True,
        "approved": False,
        "write_permitted": False,
        "requires_medical_and_engineering_review": True,
        "candidate_count": 1,
        "decision_count": 1,
        "decisions": [
            {
                "project_id": "proj-rux",
                "current_risk_key": "risk-key-1",
                "current_risk_instance_id": "risk-instance-1",
                "current_source_revision": "source-rev-1",
                "disposition_chain": chain,
            }
        ],
    }


def _artifact(source: dict, *, expected_versions: bool = False) -> dict:
    decision = source["decisions"][0]
    events = tuple(
        MonitoringAggregateCasEvent(
            record_id=row["record_id"],
            project_id=decision["project_id"],
            risk_key=decision["current_risk_key"],
            risk_instance_id=decision["current_risk_instance_id"],
            source_revision=decision["current_source_revision"],
            previous_state=row["previous_state"],
            new_state=row["new_state"],
            created_at=row["created_at"],
            expected_version=row.get("expected_version"),
        )
        for row in decision["disposition_chain"]
    )
    report = build_monitoring_aggregate_cas_replay_report(
        (
            MonitoringAggregateCasCase(
                project_id=decision["project_id"],
                risk_key=decision["current_risk_key"],
                risk_instance_id=decision["current_risk_instance_id"],
                source_revision=decision["current_source_revision"],
                events=events,
            ),
        )
    ).to_dict()
    source_raw = _raw(source)
    return {
        "input_path": "source.json",
        "input_sha256": hashlib.sha256(source_raw).hexdigest(),
        "input_decision_count": 1,
        "distinct_aggregate_cases": 1,
        "expected_version_source_field": (
            "expected_version" if expected_versions else "absent_in_fixture_chain"
        ),
        "read_only": True,
        "aggregate_write_permitted": False,
        "migration_ready": False,
        "metadata_chain_complete": report["metadata_chain_complete"],
        "cas_replay_complete": report["cas_replay_complete"],
        "issue_count": report["issue_count"],
        "replays": report["replays"],
        "report_sha256": report["report_sha256"],
    }


def _raw(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _write(path: Path, value: dict) -> tuple[int, str]:
    raw = _raw(value)
    path.write_bytes(raw)
    return len(raw), hashlib.sha256(raw).hexdigest()


def test_payload_revalidation_is_fresh_but_preserves_incomplete_cas() -> None:
    source = _source()
    report = revalidate_aggregate_cas_payload(
        _artifact(source), source_payload=source, source_path="source.json"
    )

    assert report.status == "fresh"
    assert report.evidence_fresh is True
    assert report.metadata_chain_complete is True
    assert report.cas_replay_complete is False
    assert report.issue_count == 0
    assert report.replay_issue_count == 2
    assert report.case_count == 1
    assert report.event_count == 2
    assert report.aggregate_write_permitted is False


def test_file_revalidation_checks_artifact_and_source_bytes(tmp_path: Path) -> None:
    source = _source()
    artifact = _artifact(source)
    source_path = tmp_path / "source.json"
    artifact_path = tmp_path / "artifact.json"
    source_bytes, source_sha = _write(source_path, source)
    artifact_bytes, artifact_sha = _write(artifact_path, artifact)

    report = revalidate_aggregate_cas_file(
        "artifact.json",
        expected_bytes=artifact_bytes,
        expected_sha256=artifact_sha,
        expected_source_bytes=source_bytes,
        expected_source_sha256=source_sha,
        workspace_root=tmp_path,
    )
    assert report.status == "fresh"
    assert report.artifact_file_fresh is True
    assert report.source_file_fresh is True

    source_path.write_bytes(source_path.read_bytes() + b"drift")
    drifted = revalidate_aggregate_cas_file(
        "artifact.json",
        expected_bytes=artifact_bytes,
        expected_sha256=artifact_sha,
        expected_source_bytes=source_bytes,
        expected_source_sha256=source_sha,
        workspace_root=tmp_path,
    )
    assert drifted.status == "blocked"
    assert MonitoringAggregateCasRevalidationIssueCode.SOURCE_FILE_BYTES_MISMATCH in {
        item.code for item in drifted.issues
    }


@pytest.mark.parametrize("hash_field", ["expected_sha256", "expected_source_sha256"])
def test_file_expected_hash_requires_exact_lowercase_bytes(
    tmp_path: Path, hash_field: str
) -> None:
    source = _source()
    artifact = _artifact(source)
    artifact_path = tmp_path / "artifact.json"
    source_path = tmp_path / "source.json"
    artifact_bytes, artifact_sha = _write(artifact_path, artifact)
    source_bytes, source_sha = _write(source_path, source)
    arguments = {
        "expected_bytes": artifact_bytes,
        "expected_sha256": artifact_sha,
        "expected_source_bytes": source_bytes,
        "expected_source_sha256": source_sha,
        "workspace_root": tmp_path,
    }
    arguments[hash_field] = f" {arguments[hash_field]}"

    report = revalidate_aggregate_cas_file("artifact.json", **arguments)
    codes = {item.code for item in report.issues}

    assert report.status == "blocked"
    assert MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_FIELD_INVALID in codes


def test_report_tamper_blocks_without_granting_authority() -> None:
    source = _source()
    artifact = _artifact(source)
    artifact["issue_count"] = 0
    report = revalidate_aggregate_cas_payload(
        artifact, source_payload=source, source_path="source.json"
    )

    assert report.status == "blocked"
    assert any(
        item.code == MonitoringAggregateCasRevalidationIssueCode.REPORT_REPLAY_MISMATCH
        for item in report.issues
    )
    assert report.runtime_write_permitted is False
    assert report.medical_authority_granted is False


def test_authority_drift_blocks_even_when_replay_is_deterministic() -> None:
    source = _source(expected_versions=True)
    artifact = _artifact(source, expected_versions=True)
    artifact["aggregate_write_permitted"] = True

    report = revalidate_aggregate_cas_payload(
        artifact, source_payload=source, source_path="source.json"
    )

    assert report.status == "blocked"
    assert any(
        item.code == MonitoringAggregateCasRevalidationIssueCode.AUTHORITY_FLAG_TRUE
        for item in report.issues
    )
    assert report.cas_replay_complete is True
    assert report.aggregate_write_permitted is False


def test_source_review_boundary_drift_blocks() -> None:
    source = _source()
    source["approved"] = True
    report = revalidate_aggregate_cas_payload(
        _artifact(source), source_payload=source, source_path="source.json"
    )

    assert report.status == "blocked"
    assert any(
        item.code
        == MonitoringAggregateCasRevalidationIssueCode.SOURCE_AUTHORITY_FLAG_TRUE
        for item in report.issues
    )


def test_unsafe_artifact_path_blocks_before_file_access(tmp_path: Path) -> None:
    report = revalidate_aggregate_cas_file(
        "../artifact.json",
        expected_bytes=1,
        expected_sha256="0" * 64,
        workspace_root=tmp_path,
    )

    assert report.status == "blocked"
    assert report.artifact_file_checked is True
    assert any(
        item.code == MonitoringAggregateCasRevalidationIssueCode.FILE_PATH_UNSAFE
        for item in report.issues
    )
