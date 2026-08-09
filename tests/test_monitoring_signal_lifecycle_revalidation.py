from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from services.api.app.monitoring_signal_lifecycle_contract import (
    MonitoringActionKind,
    MonitoringActionStatus,
    MonitoringDecisionType,
    MonitoringReviewOutcome,
    MonitoringSignalLifecycleReport,
    MonitoringSignalOrigin,
    MonitoringSignalScope,
    MonitoringSignalTrend,
    MonitoringRiskLevel,
    MonitoringRecheckResult,
    assess_monitoring_signal_lifecycle,
)
from services.api.app.monitoring_signal_lifecycle_revalidation import (
    ARTIFACT_SCHEMA_VERSION,
    MonitoringSignalLifecycleRevalidationIssueCode,
    revalidate_signal_lifecycle_file,
    revalidate_signal_lifecycle_payload,
)


UTC = timezone.utc


def _ts(day: int) -> str:
    return datetime(2026, 8, day, 8, 0, tzinfo=UTC).isoformat()


def _payload() -> dict:
    signal = {
        "signal_id": "signal-001",
        "project_id": "proj-rux",
        "scope": MonitoringSignalScope.SUBJECT.value,
        "scope_id": "SUBJ-001",
        "source_batch_id": "batch-002",
        "source_revision": "source-rev-002",
        "evidence_ids": ["evidence-risk-001"],
        "origin": MonitoringSignalOrigin.DETERMINISTIC.value,
        "risk_level": MonitoringRiskLevel.HIGH.value,
        "trend": MonitoringSignalTrend.NEW.value,
        "rule_or_model_ref": "rule-ae-001",
        "prompt_revision": "",
        "generated_at": _ts(1),
        "baseline_batch_id": "batch-001",
        "auto_action_forbidden": True,
    }
    review = {
        "review_id": "review-001",
        "signal_id": "signal-001",
        "project_id": "proj-rux",
        "source_revision": "source-rev-002",
        "outcome": MonitoringReviewOutcome.ACCEPTED_FOR_DECISION.value,
        "reason": "证据与规则命中已完成医学复核。",
        "reviewer_id": "medical-reviewer-001",
        "reviewed_at": _ts(1),
        "evidence_ids": ["evidence-risk-001"],
    }
    decision = {
        "decision_id": "decision-001",
        "review_id": "review-001",
        "signal_id": "signal-001",
        "project_id": "proj-rux",
        "source_revision": "source-rev-002",
        "decision": MonitoringDecisionType.CONFIRM_RISK.value,
        "reason": "确认进入下一步定向复核。",
        "decided_by": "medical-reviewer-001",
        "decided_at": _ts(1),
        "evidence_ids": ["evidence-risk-001"],
    }
    action = {
        "action_id": "action-001",
        "decision_id": "decision-001",
        "signal_id": "signal-001",
        "project_id": "proj-rux",
        "source_revision": "source-rev-002",
        "kind": MonitoringActionKind.TARGETED_REVIEW.value,
        "status": MonitoringActionStatus.RESOLVED.value,
        "proposed_by": "medical-reviewer-001",
        "reason": "完成受试者原始证据定向复核。",
        "target_scope": MonitoringSignalScope.SUBJECT.value,
        "target_id": "SUBJ-001",
        "proposed_at": _ts(1),
        "confirmed_by": "medical-reviewer-001",
        "confirmed_at": _ts(2),
        "auto_executed": False,
    }
    recheck = {
        "recheck_id": "recheck-001",
        "action_id": "action-001",
        "signal_id": "signal-001",
        "project_id": "proj-rux",
        "source_batch_id": "batch-003",
        "source_revision": "source-rev-003",
        "result": MonitoringRecheckResult.RESOLVED.value,
        "reason": "后续批次复核未再出现该信号。",
        "reviewer_id": "medical-reviewer-001",
        "rechecked_at": _ts(3),
        "evidence_ids": ["evidence-risk-002"],
    }
    from services.api.app.monitoring_signal_lifecycle_contract import (
        MonitoringAction,
        MonitoringDecision,
        MonitoringRecheck,
        MonitoringReview,
        MonitoringSignal,
    )

    signal_obj = MonitoringSignal(
        **{**signal, "generated_at": datetime.fromisoformat(signal["generated_at"])}
    )
    review_obj = MonitoringReview(
        **{
            **review,
            "reviewed_at": datetime.fromisoformat(review["reviewed_at"]),
            "evidence_ids": tuple(review["evidence_ids"]),
        }
    )
    decision_obj = MonitoringDecision(
        **{
            **decision,
            "decided_at": datetime.fromisoformat(decision["decided_at"]),
            "evidence_ids": tuple(decision["evidence_ids"]),
        }
    )
    action_obj = MonitoringAction(
        **{
            **action,
            "proposed_at": datetime.fromisoformat(action["proposed_at"]),
            "confirmed_at": datetime.fromisoformat(action["confirmed_at"]),
        }
    )
    recheck_obj = MonitoringRecheck(
        **{
            **recheck,
            "rechecked_at": datetime.fromisoformat(recheck["rechecked_at"]),
            "evidence_ids": tuple(recheck["evidence_ids"]),
        }
    )
    report = assess_monitoring_signal_lifecycle(
        signal_obj,
        reviews=(review_obj,),
        decisions=(decision_obj,),
        actions=(action_obj,),
        rechecks=(recheck_obj,),
    )
    assert isinstance(report, MonitoringSignalLifecycleReport)
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "lifecycle_schema_version": "monitoring_signal_lifecycle_v1",
        "artifact_ref": "synthetic-signal-lifecycle",
        "observed_at": _ts(3),
        "purpose": "synthetic contract fixture; not a medical outcome",
        "authority": {
            "diagnostic_only": True,
            "provider_permitted": False,
            "runtime_write_permitted": False,
            "medical_authority_granted": False,
            "authority_granted": False,
            "release_ready": False,
        },
        "signal": signal,
        "reviews": [review],
        "decisions": [decision],
        "actions": [action],
        "rechecks": [recheck],
        "report": report.public_dict(),
    }


def _write_payload(path: Path, payload: dict) -> tuple[int, str]:
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    path.write_bytes(raw)
    return len(raw), hashlib.sha256(raw).hexdigest()


def test_payload_revalidation_replays_complete_lifecycle() -> None:
    report = revalidate_signal_lifecycle_payload(_payload())

    assert report.status == "fresh"
    assert report.evidence_fresh is True
    assert report.payload_valid is True
    assert report.lifecycle_report_matches is True
    assert report.lifecycle_status == "valid"
    assert report.lifecycle_closed is True
    assert report.signal_id == "signal-001"
    assert report.project_id == "proj-rux"
    assert report.authority_granted is False


def test_file_revalidation_checks_artifact_bytes_and_sha(tmp_path: Path) -> None:
    artifact = tmp_path / "records" / "signal.json"
    artifact.parent.mkdir()
    expected_bytes, expected_sha = _write_payload(artifact, _payload())

    report = revalidate_signal_lifecycle_file(
        "records/signal.json",
        expected_bytes=expected_bytes,
        expected_sha256=expected_sha,
        workspace_root=tmp_path,
    )

    assert report.status == "fresh"
    assert report.file_checked is True
    assert report.file_fresh is True

    artifact.write_bytes(artifact.read_bytes() + b"drift")
    drifted = revalidate_signal_lifecycle_file(
        "records/signal.json",
        expected_bytes=expected_bytes,
        expected_sha256=expected_sha,
        workspace_root=tmp_path,
    )
    codes = {item.code for item in drifted.issues}
    assert drifted.status == "blocked"
    assert MonitoringSignalLifecycleRevalidationIssueCode.FILE_BYTES_MISMATCH in codes
    assert MonitoringSignalLifecycleRevalidationIssueCode.FILE_SHA256_MISMATCH in codes


@pytest.mark.parametrize("expected_sha_suffix", [" leading", "\n"])
def test_file_expected_sha256_requires_exact_lowercase_bytes(
    tmp_path: Path, expected_sha_suffix: str
) -> None:
    artifact = tmp_path / "records" / "signal.json"
    artifact.parent.mkdir()
    _expected_bytes, expected_sha = _write_payload(artifact, _payload())

    padded = (
        f"{expected_sha}{expected_sha_suffix}"
        if expected_sha_suffix == "\n"
        else f" {expected_sha}"
    )
    report = revalidate_signal_lifecycle_file(
        "records/signal.json",
        expected_bytes=artifact.stat().st_size,
        expected_sha256=padded,
        workspace_root=tmp_path,
    )

    assert report.status == "blocked"
    assert any(
        item.code == MonitoringSignalLifecycleRevalidationIssueCode.FILE_SHA256_MISMATCH
        for item in report.issues
    )


def test_report_tamper_blocks_without_authority(tmp_path: Path) -> None:
    payload = _payload()
    payload["report"]["closed"] = False
    report = revalidate_signal_lifecycle_payload(payload)

    assert report.status == "blocked"
    assert report.evidence_fresh is False
    assert any(
        item.code
        == MonitoringSignalLifecycleRevalidationIssueCode.LIFECYCLE_REPORT_MISMATCH
        for item in report.issues
    )
    assert report.provider_permitted is False
    assert report.runtime_write_permitted is False


def test_authority_drift_blocks_even_when_chain_is_valid() -> None:
    payload = _payload()
    payload["authority"]["medical_authority_granted"] = True

    report = revalidate_signal_lifecycle_payload(payload)

    assert report.status == "blocked"
    assert any(
        item.code == MonitoringSignalLifecycleRevalidationIssueCode.AUTHORITY_FLAG_TRUE
        for item in report.issues
    )
    assert report.medical_authority_granted is False


def test_underlying_blocked_lifecycle_is_not_promoted_to_valid() -> None:
    payload = _payload()
    payload["reviews"][0]["project_id"] = "other-project"
    from services.api.app.monitoring_signal_lifecycle_contract import (
        MonitoringAction,
        MonitoringDecision,
        MonitoringRecheck,
        MonitoringReview,
        MonitoringSignal,
    )

    signal = MonitoringSignal(
        **{
            **payload["signal"],
            "generated_at": datetime.fromisoformat(payload["signal"]["generated_at"]),
        }
    )
    review = MonitoringReview(
        **{
            **payload["reviews"][0],
            "reviewed_at": datetime.fromisoformat(payload["reviews"][0]["reviewed_at"]),
            "evidence_ids": tuple(payload["reviews"][0]["evidence_ids"]),
        }
    )
    decision = MonitoringDecision(
        **{
            **payload["decisions"][0],
            "decided_at": datetime.fromisoformat(payload["decisions"][0]["decided_at"]),
            "evidence_ids": tuple(payload["decisions"][0]["evidence_ids"]),
        }
    )
    action = MonitoringAction(
        **{
            **payload["actions"][0],
            "proposed_at": datetime.fromisoformat(payload["actions"][0]["proposed_at"]),
            "confirmed_at": datetime.fromisoformat(
                payload["actions"][0]["confirmed_at"]
            ),
        }
    )
    recheck = MonitoringRecheck(
        **{
            **payload["rechecks"][0],
            "rechecked_at": datetime.fromisoformat(
                payload["rechecks"][0]["rechecked_at"]
            ),
            "evidence_ids": tuple(payload["rechecks"][0]["evidence_ids"]),
        }
    )
    payload["report"] = assess_monitoring_signal_lifecycle(
        signal,
        reviews=(review,),
        decisions=(decision,),
        actions=(action,),
        rechecks=(recheck,),
    ).public_dict()

    report = revalidate_signal_lifecycle_payload(payload)

    assert report.status == "fresh"
    assert report.lifecycle_status == "blocked"
    assert report.lifecycle_closed is False
    assert report.evidence_fresh is True


def test_file_path_traversal_blocks(tmp_path: Path) -> None:
    report = revalidate_signal_lifecycle_file(
        "../signal.json",
        expected_bytes=0,
        expected_sha256="0" * 64,
        workspace_root=tmp_path,
    )

    assert report.status == "blocked"
    assert any(
        item.code == MonitoringSignalLifecycleRevalidationIssueCode.FILE_PATH_UNSAFE
        for item in report.issues
    )
