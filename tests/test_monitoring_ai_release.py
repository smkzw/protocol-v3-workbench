from datetime import datetime, timezone

import pytest

from services.api.app.monitoring_ai_contracts import (
    MonitoringAiTaskType,
    content_sha256,
)
from services.api.app.monitoring_ai_release import (
    MonitoringAiPromptReleaseStatus,
    activate_prompt_release,
    approve_prompt_release,
    build_prompt_release_candidate,
    prompt_content_sha256,
    release_snapshot_payload,
    rollback_prompt_release,
)


NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)
EVAL_HASH = content_sha256({"dataset": "three-project-shadow", "revision": "eval-v1"})
APPROVAL_HASH = content_sha256(
    {"review": "medical-engineering", "revision": "review-v1"}
)


def candidate(version: str = "monitoring-listing-field-mapping-v17"):
    return build_prompt_release_candidate(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        prompt_version=version,
        prompt_text="exact prompt body\nwith preserved whitespace",
        response_model="monitoring_field_mapping_v1",
        model_revision="model-r5",
        input_contract_revision="input-v3",
        evaluator_revision="eval-v1",
        evaluation_observation_ids=("obs-rux-1", "obs-mgk10-1", "obs-my009-1"),
        evaluation_snapshot_sha256=EVAL_HASH,
        created_at=NOW,
    )


def test_candidate_hashes_exact_prompt_and_is_unapproved():
    release = candidate()
    assert release.status == MonitoringAiPromptReleaseStatus.CANDIDATE
    assert release.prompt_sha256 == prompt_content_sha256(
        "exact prompt body\nwith preserved whitespace"
    )
    assert release.release_id.startswith("mrel_")
    assert release.approved_by == ""


def test_candidate_identity_is_deterministic_and_whitespace_sensitive():
    assert candidate().release_id == candidate().release_id
    assert (
        candidate().release_id
        != build_prompt_release_candidate(
            task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
            prompt_version="monitoring-listing-field-mapping-v17",
            prompt_text="exact prompt body with preserved whitespace",
            response_model="monitoring_field_mapping_v1",
            model_revision="model-r5",
            input_contract_revision="input-v3",
            evaluator_revision="eval-v1",
            evaluation_observation_ids=("obs-rux-1", "obs-mgk10-1", "obs-my009-1"),
            evaluation_snapshot_sha256=EVAL_HASH,
            created_at=NOW,
        ).release_id
    )


def test_approval_requires_candidate_and_evidence():
    approved = approve_prompt_release(
        candidate(),
        approved_by="medical_reviewer",
        approval_evidence_sha256=APPROVAL_HASH,
        approved_at=NOW,
    )
    assert approved.status == MonitoringAiPromptReleaseStatus.APPROVED
    assert approved.approved_by == "medical_reviewer"
    assert approved.approval_evidence_sha256 == APPROVAL_HASH
    with pytest.raises(ValueError, match="only a candidate"):
        approve_prompt_release(
            approved, approved_by="other", approval_evidence_sha256=APPROVAL_HASH
        )


def test_activation_retires_previous_active_without_mutating_inputs():
    previous = approve_prompt_release(
        candidate("monitoring-listing-field-mapping-v16"),
        approved_by="r1",
        approval_evidence_sha256=APPROVAL_HASH,
        approved_at=NOW,
    )
    previous_active, _ = activate_prompt_release(previous)
    approved = approve_prompt_release(
        candidate(),
        approved_by="r2",
        approval_evidence_sha256=APPROVAL_HASH,
        approved_at=NOW,
    )
    active, retired = activate_prompt_release(approved, previous_active=previous_active)
    assert active.status == MonitoringAiPromptReleaseStatus.ACTIVE
    assert active.supersedes_release_id == previous_active.release_id
    assert (
        retired is not None
        and retired.status == MonitoringAiPromptReleaseStatus.RETIRED
    )
    assert previous_active.status == MonitoringAiPromptReleaseStatus.ACTIVE


def test_activation_rejects_cross_task_previous_release():
    approved = approve_prompt_release(
        candidate(),
        approved_by="r",
        approval_evidence_sha256=APPROVAL_HASH,
        approved_at=NOW,
    )
    previous = build_prompt_release_candidate(
        task_type=MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
        prompt_version="risk-summary-v1",
        prompt_text="risk summary",
        response_model="risk_summary_v1",
        model_revision="model-r5",
        input_contract_revision="input-v3",
        evaluator_revision="eval-v1",
        evaluation_observation_ids=("obs-1",),
        evaluation_snapshot_sha256=EVAL_HASH,
        created_at=NOW,
    )
    previous = approve_prompt_release(
        previous,
        approved_by="r",
        approval_evidence_sha256=APPROVAL_HASH,
        approved_at=NOW,
    )
    previous, _ = activate_prompt_release(previous)
    with pytest.raises(ValueError, match="task type"):
        activate_prompt_release(approved, previous_active=previous)


def test_rollback_restores_only_same_task_retired_target():
    first = approve_prompt_release(
        candidate("monitoring-listing-field-mapping-v16"),
        approved_by="r1",
        approval_evidence_sha256=APPROVAL_HASH,
        approved_at=NOW,
    )
    first_active, _ = activate_prompt_release(first)
    second = approve_prompt_release(
        candidate(),
        approved_by="r2",
        approval_evidence_sha256=APPROVAL_HASH,
        approved_at=NOW,
    )
    second_active, retired = activate_prompt_release(
        second, previous_active=first_active
    )
    assert retired is not None
    rolled_back, restored = rollback_prompt_release(second_active, retired)
    assert rolled_back.status == MonitoringAiPromptReleaseStatus.ROLLED_BACK
    assert rolled_back.rollback_target_release_id == retired.release_id
    assert restored.status == MonitoringAiPromptReleaseStatus.ACTIVE


def test_rollback_rejects_candidate_target_and_cross_task_target():
    active_approved = approve_prompt_release(
        candidate(),
        approved_by="r",
        approval_evidence_sha256=APPROVAL_HASH,
        approved_at=NOW,
    )
    active, _ = activate_prompt_release(active_approved)
    with pytest.raises(ValueError, match="retired or approved"):
        rollback_prompt_release(
            active, candidate("monitoring-listing-field-mapping-v16")
        )


def test_release_snapshot_is_deterministic_and_extra_fields_fail_closed():
    release = candidate()
    assert release_snapshot_payload(release) == release_snapshot_payload(release)
    with pytest.raises(ValueError):
        type(release).model_validate(
            {
                **release.model_dump(),
                "approval_evidence_sha256": "not-a-hash",
                "status": MonitoringAiPromptReleaseStatus.APPROVED,
            }
        )


def test_release_requires_observation_ids_and_hash_bound_evaluation():
    with pytest.raises(ValueError, match="at least one evaluation"):
        build_prompt_release_candidate(
            task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
            prompt_version="mapping-v1",
            prompt_text="prompt",
            response_model="model",
            model_revision="model-r1",
            input_contract_revision="input-v1",
            evaluator_revision="eval-v1",
            evaluation_observation_ids=(),
            evaluation_snapshot_sha256=EVAL_HASH,
            created_at=NOW,
        )


@pytest.mark.parametrize(
    "field_name,declared_hash",
    [
        ("prompt_sha256", "A" * 64),
        ("evaluation_snapshot_sha256", " " + EVAL_HASH),
        ("approval_evidence_sha256", APPROVAL_HASH + " "),
    ],
)
def test_release_digest_fields_reject_normalization(field_name: str, declared_hash: str):
    payload = candidate().model_dump()
    payload[field_name] = declared_hash
    if field_name == "approval_evidence_sha256":
        payload["status"] = MonitoringAiPromptReleaseStatus.APPROVED
        payload["approved_by"] = "medical_reviewer"
        payload["approved_at"] = NOW
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        type(candidate()).model_validate(payload)


def test_candidate_keeps_absent_optional_approval_hash_empty():
    release = candidate()
    assert release.approval_evidence_sha256 == ""
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        type(release).model_validate(
            {
                **release.model_dump(),
                "approval_evidence_sha256": " ",
            }
        )
