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
from services.api.app.monitoring_ai_quality import (
    MonitoringAiHumanReviewOutcome,
    MonitoringAiRepairOutcome,
    MonitoringAiQualityCoverage,
    MonitoringAiQualityObservation,
    quality_observation_payload,
    summarize_quality_coverage,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
OBSERVED_AT = datetime(2026, 8, 2, 3, 0, tzinfo=timezone.utc)


def _job(
    *,
    project_id: str = "proj_quality",
    retryable: object = False,
) -> MonitoringAiJob:
    revision = MonitoringAiInputRevision(
        project_id=project_id,
        batch_revision="monbatch_quality@v1",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id=f"listing-{project_id}",
                source_content_sha256=HASH_A,
            ),
        ),
    )
    return MonitoringAiJob(
        job_id=f"monai-{project_id}",
        project_id=project_id,
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        status=MonitoringAiJobStatus.COMPLETED,
        business_key="quality:field-mapping",
        input_revision=revision,
        input_revision_sha256=revision.revision_sha256,
        input_payload_sha256=HASH_B,
        prompt_version="monitoring-listing-field-mapping-v15",
        profile_id="independent_ai__test",
        provider="test-provider",
        requested_model="test-model",
        response_model="test-model",
        retryable=retryable,
        created_at=OBSERVED_AT,
        updated_at=OBSERVED_AT,
    )


@pytest.mark.parametrize("retryable", (0, 1, "false", "true"))
def test_job_retryable_rejects_bool_like_coercion(retryable: object) -> None:
    with pytest.raises(ValidationError):
        _job(retryable=retryable)


def _attempt(
    *,
    outcome: str = "success",
    response_model: str = "test-model",
    failure_code: str = "",
    attempt_id: str = "monattempt-quality-1",
) -> dict[str, object]:
    return {
        "attempt_id": attempt_id,
        "attempt_number": 1,
        "request_sha256": HASH_B,
        "response_sha256": HASH_A,
        "response_model": response_model,
        "outcome": outcome,
        "failure_code": failure_code,
    }


def test_quality_observation_is_deterministic_and_preserves_source_binding() -> None:
    job = _job()
    first = MonitoringAiQualityObservation.from_job_attempt(
        job,
        _attempt(),
        latency_ms=1_250,
        input_tokens=100,
        output_tokens=40,
        total_tokens=140,
        cost_micros=25,
        candidate_ids=("candidate-1",),
        observed_at=OBSERVED_AT,
    )
    second = MonitoringAiQualityObservation.from_job_attempt(
        job,
        _attempt(),
        latency_ms=1_250,
        input_tokens=100,
        output_tokens=40,
        total_tokens=140,
        cost_micros=25,
        candidate_ids=("candidate-1",),
        observed_at=OBSERVED_AT,
    )

    assert first.observation_id == second.observation_id
    assert first.observation_sha256 == second.observation_sha256
    assert first.attempt_outcome == "success"
    assert first.outcome.value == "completed"
    assert first.source_bindings[0].source_content_sha256 == HASH_A
    assert first.input_revision_sha256 == job.input_revision_sha256
    assert quality_observation_payload(first) == quality_observation_payload(second)


@pytest.mark.parametrize(
    "field_name,declared_hash",
    [
        ("request_sha256", "A" * 64),
        ("response_sha256", " " + HASH_A),
        ("request_sha256", HASH_B + " "),
        ("response_sha256", "g" * 64),
        ("request_sha256", "b" * 63),
    ],
)
def test_quality_attempt_hashes_reject_normalization(
    field_name: str,
    declared_hash: str,
) -> None:
    attempt = _attempt()
    attempt[field_name] = declared_hash

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        MonitoringAiQualityObservation.from_job_attempt(
            _job(),
            attempt,
            observed_at=OBSERVED_AT,
        )


def test_quality_factory_keeps_absent_response_hash_optional() -> None:
    attempt = _attempt(
        outcome="provider_error",
        response_model="",
        failure_code="provider_error",
    )
    attempt.pop("response_sha256")

    observation = MonitoringAiQualityObservation.from_job_attempt(
        _job(),
        attempt,
        observed_at=OBSERVED_AT,
    )

    assert observation.response_sha256 == ""


def test_non_completed_observation_requires_failure_code() -> None:
    with pytest.raises(ValueError, match="requires failure code"):
        MonitoringAiQualityObservation.from_job_attempt(
            _job(),
            _attempt(outcome="invalid_output"),
            observed_at=OBSERVED_AT,
        )


def test_quality_attempt_and_resource_counts_reject_boolean_values() -> None:
    malformed_attempt = _attempt()
    malformed_attempt["attempt_number"] = True
    with pytest.raises(ValueError, match="positive integer"):
        MonitoringAiQualityObservation.from_job_attempt(
            _job(), malformed_attempt, candidate_ids=("candidate-1",), observed_at=OBSERVED_AT
        )

    with pytest.raises(ValidationError):
        MonitoringAiQualityObservation.from_job_attempt(
            _job(), _attempt(), latency_ms=True, candidate_ids=("candidate-1",), observed_at=OBSERVED_AT
        )


@pytest.mark.parametrize(
    "field_name",
    (
        "observation_count",
        "completed_count",
        "failed_count",
        "blocked_count",
        "stale_count",
        "cancelled_count",
        "repaired_count",
        "reviewed_count",
        "accepted_or_edited_count",
    ),
)
def test_quality_coverage_rejects_boolean_counts(field_name: str) -> None:
    values = {
        "observation_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "blocked_count": 0,
        "stale_count": 0,
        "cancelled_count": 0,
        "repaired_count": 0,
        "reviewed_count": 0,
        "accepted_or_edited_count": 0,
    }
    values[field_name] = True
    with pytest.raises(ValidationError):
        MonitoringAiQualityCoverage(**values)


def test_completed_observation_rejects_response_model_drift() -> None:
    with pytest.raises(ValueError, match="does not match request"):
        MonitoringAiQualityObservation.from_job_attempt(
            _job(),
            _attempt(response_model="different-model"),
            candidate_ids=("candidate-1",),
            observed_at=OBSERVED_AT,
        )


def test_unknown_attempt_outcome_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported monitoring AI attempt outcome"):
        MonitoringAiQualityObservation.from_job_attempt(
            _job(),
            _attempt(outcome="provider_looks_ok"),
            observed_at=OBSERVED_AT,
        )


def test_token_total_must_be_complete_and_recomputable() -> None:
    with pytest.raises(ValueError, match="input and output"):
        MonitoringAiQualityObservation.from_job_attempt(
            _job(),
            _attempt(),
            candidate_ids=("candidate-1",),
            input_tokens=10,
            total_tokens=10,
            observed_at=OBSERVED_AT,
        )
    with pytest.raises(ValueError, match="equal input plus output"):
        MonitoringAiQualityObservation.from_job_attempt(
            _job(),
            _attempt(),
            candidate_ids=("candidate-1",),
            input_tokens=10,
            output_tokens=2,
            total_tokens=10,
            observed_at=OBSERVED_AT,
        )


def test_repair_and_human_review_are_separate_auditable_dimensions() -> None:
    observation = MonitoringAiQualityObservation.from_job_attempt(
        _job(),
        _attempt(outcome="success_repaired"),
        repair_outcome=MonitoringAiRepairOutcome.SUCCEEDED,
        repair_ids=("monrepair-quality-1",),
        candidate_ids=("candidate-1",),
        human_review_outcome=MonitoringAiHumanReviewOutcome.EDITED,
        reviewed_by="medical_manager_fixture",
        observed_at=OBSERVED_AT,
    )

    summary = summarize_quality_coverage(
        (observation,),
        expected_project_task_pairs=(("proj_quality", "listing_field_mapping"),),
    )
    assert observation.repair_outcome is MonitoringAiRepairOutcome.SUCCEEDED
    assert observation.human_review_outcome is MonitoringAiHumanReviewOutcome.EDITED
    assert summary.repaired_count == 1
    assert summary.reviewed_count == 1
    assert summary.accepted_or_edited_count == 1
    assert summary.complete is True
    assert summary.review_rate == 1.0


def test_positive_human_review_cannot_be_attached_to_empty_result() -> None:
    with pytest.raises(ValueError, match="requires a candidate"):
        MonitoringAiQualityObservation.from_job_attempt(
            _job(),
            _attempt(),
            human_review_outcome=MonitoringAiHumanReviewOutcome.ACCEPTED,
            reviewed_by="medical_manager_fixture",
            observed_at=OBSERVED_AT,
        )


def test_coverage_reports_missing_project_task_pairs_without_claiming_release() -> None:
    completed = MonitoringAiQualityObservation.from_job_attempt(
        _job(),
        _attempt(),
        candidate_ids=("candidate-1",),
        observed_at=OBSERVED_AT,
    )
    failed = MonitoringAiQualityObservation.from_job_attempt(
        _job(project_id="proj_second"),
        _attempt(
            outcome="provider_error",
            response_model="",
            failure_code="invalid_json",
            attempt_id="monattempt-quality-2",
        ),
        observed_at=OBSERVED_AT,
    )

    summary = summarize_quality_coverage(
        (completed, failed),
        expected_project_task_pairs=(
            ("proj_quality", "listing_field_mapping"),
            ("proj_second", "listing_field_mapping"),
            ("proj_unseen", "listing_field_mapping"),
        ),
    )
    assert summary.observation_count == 2
    assert summary.completed_count == 1
    assert summary.failed_count == 1
    assert summary.missing_project_task_pairs == (
        ("proj_unseen", "listing_field_mapping"),
    )
    assert summary.complete is False


def test_duplicate_observation_ids_are_rejected() -> None:
    observation = MonitoringAiQualityObservation.from_job_attempt(
        _job(),
        _attempt(),
        candidate_ids=("candidate-1",),
        observed_at=OBSERVED_AT,
    )
    with pytest.raises(ValueError, match="unique observation IDs"):
        summarize_quality_coverage((observation, observation))
