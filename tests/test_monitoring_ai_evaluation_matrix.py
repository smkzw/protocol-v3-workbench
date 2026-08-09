from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from services.api.app.monitoring_ai_contracts import (
    MonitoringAiInputRevision,
    MonitoringAiJob,
    MonitoringAiJobStatus,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
)
from services.api.app.monitoring_ai_evaluation_matrix import (
    INDEPENDENT_AI_RELEASE_TASK_TYPES,
    MonitoringAiEvaluationMatrix,
    MonitoringAiEvaluationPair,
    MonitoringAiEvaluationTrack,
    build_evaluation_matrix,
    build_independent_ai_release_matrix,
    evaluation_matrix_payload,
)
from services.api.app.monitoring_ai_quality import (
    MonitoringAiHumanReviewOutcome,
    MonitoringAiQualityObservation,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
OBSERVED_AT = datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc)


def _observation(
    project_id: str,
    task_type: MonitoringAiTaskType,
    *,
    outcome: str = "success",
    reviewed: bool = True,
    attempt_suffix: str = "1",
) -> MonitoringAiQualityObservation:
    revision = MonitoringAiInputRevision(
        project_id=project_id,
        batch_revision=f"batch-{project_id}-v1",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id=f"listing-{project_id}",
                source_content_sha256=HASH_A,
            ),
        ),
    )
    job = MonitoringAiJob(
        job_id=f"monai-{project_id}-{task_type.value}-{attempt_suffix}",
        project_id=project_id,
        task_type=task_type,
        status=(
            MonitoringAiJobStatus.COMPLETED
            if outcome == "success"
            else MonitoringAiJobStatus.FAILED
        ),
        business_key=f"matrix:{project_id}:{task_type.value}:{attempt_suffix}",
        input_revision=revision,
        input_revision_sha256=revision.revision_sha256,
        input_payload_sha256=HASH_B,
        prompt_version="matrix-prompt-v1",
        profile_id="independent_ai__matrix",
        provider="test-provider",
        requested_model="test-model",
        response_model="test-model" if outcome == "success" else "",
        created_at=OBSERVED_AT,
        updated_at=OBSERVED_AT,
    )
    attempt = {
        "attempt_id": f"attempt-{project_id}-{task_type.value}-{attempt_suffix}",
        "attempt_number": 1,
        "request_sha256": HASH_B,
        "response_sha256": HASH_A if outcome == "success" else "",
        "response_model": "test-model" if outcome == "success" else "",
        "outcome": outcome,
        "failure_code": "provider_error" if outcome != "success" else "",
    }
    return MonitoringAiQualityObservation.from_job_attempt(
        job,
        attempt,
        candidate_ids=(f"candidate-{project_id}-{task_type.value}-{attempt_suffix}",)
        if outcome == "success"
        else (),
        human_review_outcome=(
            MonitoringAiHumanReviewOutcome.ACCEPTED
            if reviewed and outcome == "success"
            else MonitoringAiHumanReviewOutcome.NOT_REVIEWED
        ),
        reviewed_by="reviewer_fixture" if reviewed and outcome == "success" else "",
        observed_at=OBSERVED_AT,
    )


def test_matrix_covers_real_projects_and_unseen_project_deterministically() -> None:
    tasks = (
        MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
    )
    observations = [
        _observation(project, task, attempt_suffix=f"{index}")
        for index, project in enumerate(
            ("proj_rux_03_002", "proj_mgk10_sar_demo", "proj_my009_uc"), 1
        )
        for task in tasks
    ] + [
        _observation("proj_unseen", task, attempt_suffix=f"u{index}")
        for index, task in enumerate(tasks, 1)
    ]
    matrix = build_evaluation_matrix(
        reversed(observations),
        real_project_ids=("proj_rux_03_002", "proj_mgk10_sar_demo", "proj_my009_uc"),
        unseen_project_ids=("proj_unseen",),
        required_task_types=tasks,
        evaluator_revision="evaluator-v1",
    )
    same = build_evaluation_matrix(
        observations,
        real_project_ids=("proj_rux_03_002", "proj_mgk10_sar_demo", "proj_my009_uc"),
        unseen_project_ids=("proj_unseen",),
        required_task_types=tasks,
        evaluator_revision="evaluator-v1",
    )

    assert matrix.evidence_matrix_complete is True
    assert matrix.real_project_coverage_complete is True
    assert matrix.unseen_project_coverage_complete is True
    assert matrix.human_review_complete is True
    assert matrix.observation_snapshot_sha256 == same.observation_snapshot_sha256
    assert evaluation_matrix_payload(matrix) == evaluation_matrix_payload(same)
    assert matrix.status == "evidence_matrix_only"


def test_directly_constructed_orphan_matrix_is_not_complete() -> None:
    matrix = MonitoringAiEvaluationMatrix(
        evaluator_revision="evaluator-v1",
        real_project_ids=("proj_rux", "proj_mg", "proj_my009"),
        unseen_project_ids=("proj_unseen",),
        required_task_types=(MonitoringAiTaskType.LISTING_FIELD_MAPPING,),
        observation_ids=("orphan-observation",),
        observation_snapshot_sha256=HASH_A,
        real_pairs=(),
        unseen_pairs=(),
    )

    assert matrix.structurally_complete is False
    assert matrix.evidence_matrix_complete is False


@pytest.mark.parametrize(
    "field_name",
    (
        "observation_count",
        "completed_count",
        "failed_count",
        "repaired_count",
        "reviewed_count",
        "accepted_or_edited_count",
    ),
)
def test_evaluation_pair_rejects_boolean_counts(field_name: str) -> None:
    values = {
        "project_id": "proj_rux",
        "task_type": MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        "track": MonitoringAiEvaluationTrack.REAL_PROJECT,
        "observation_ids": (),
        "observation_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "repaired_count": 0,
        "reviewed_count": 0,
        "accepted_or_edited_count": 0,
    }
    values[field_name] = True
    with pytest.raises(ValidationError):
        MonitoringAiEvaluationPair(**values)


def test_matrix_surfaces_missing_unreviewed_and_failed_only_cells() -> None:
    mapping = MonitoringAiTaskType.LISTING_FIELD_MAPPING
    protocol = MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
    matrix = build_evaluation_matrix(
        (
            _observation("proj_rux", mapping),
            _observation("proj_mg", mapping, reviewed=False),
            _observation(
                "proj_unseen", mapping, outcome="provider_error", reviewed=False
            ),
        ),
        real_project_ids=("proj_rux", "proj_mg"),
        unseen_project_ids=("proj_unseen",),
        required_task_types=(mapping, protocol),
        evaluator_revision="evaluator-v1",
    )

    assert ("proj_rux", protocol) in matrix.missing_real_pairs
    assert ("proj_mg", mapping) in matrix.unreviewed_real_pairs
    assert ("proj_unseen", mapping) in matrix.failed_only_unseen_pairs
    assert ("proj_unseen", protocol) in matrix.missing_unseen_pairs
    assert matrix.evidence_matrix_complete is False


def test_matrix_rejects_unknown_project_or_task_instead_of_ignoring_it() -> None:
    observation = _observation("proj_other", MonitoringAiTaskType.LISTING_FIELD_MAPPING)
    with pytest.raises(ValueError, match="outside matrix"):
        build_evaluation_matrix(
            (observation,),
            real_project_ids=("proj_rux",),
            unseen_project_ids=("proj_unseen",),
            required_task_types=(MonitoringAiTaskType.LISTING_FIELD_MAPPING,),
            evaluator_revision="evaluator-v1",
        )


def test_matrix_rejects_duplicate_observation_ids_and_overlapping_tracks() -> None:
    observation = _observation("proj_rux", MonitoringAiTaskType.LISTING_FIELD_MAPPING)
    with pytest.raises(ValueError, match="unique IDs"):
        build_evaluation_matrix(
            (observation, observation),
            real_project_ids=("proj_rux",),
            unseen_project_ids=("proj_unseen",),
            required_task_types=(MonitoringAiTaskType.LISTING_FIELD_MAPPING,),
            evaluator_revision="evaluator-v1",
        )
    with pytest.raises(ValueError, match="disjoint"):
        build_evaluation_matrix(
            (observation,),
            real_project_ids=("proj_rux",),
            unseen_project_ids=("proj_rux",),
            required_task_types=(MonitoringAiTaskType.LISTING_FIELD_MAPPING,),
            evaluator_revision="evaluator-v1",
        )


def test_release_matrix_keeps_all_four_specification_tasks() -> None:
    matrix = build_independent_ai_release_matrix(
        (
            _observation(
                "proj_rux",
                MonitoringAiTaskType.LISTING_FIELD_MAPPING,
            ),
        ),
        real_project_ids=("proj_rux", "proj_mg", "proj_my009"),
        unseen_project_ids=("proj_unseen",),
        evaluator_revision="evaluator-v1",
    )

    assert matrix.required_task_types == tuple(
        sorted(INDEPENDENT_AI_RELEASE_TASK_TYPES, key=lambda item: item.value)
    )
    assert (
        "proj_rux",
        MonitoringAiTaskType.LISTING_FIELD_MAPPING,
    ) not in matrix.missing_real_pairs
    assert (
        "proj_rux",
        MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
    ) in matrix.missing_real_pairs
    assert matrix.evidence_matrix_complete is False


def test_release_matrix_requires_three_real_projects() -> None:
    with pytest.raises(ValueError, match="at least three real projects"):
        build_independent_ai_release_matrix(
            (),
            real_project_ids=("proj_rux", "proj_mg"),
            unseen_project_ids=("proj_unseen",),
            evaluator_revision="evaluator-v1",
        )
