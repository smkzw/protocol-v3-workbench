from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from threading import Barrier, Lock

import pytest
from pydantic import ValidationError

from services.api.app.monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiClaim,
    MonitoringAiClaimKind,
    MonitoringAiEvidence,
    MonitoringAiInputRevision,
    MonitoringAiJobCreate,
    MonitoringAiJobStatus,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
    validate_candidates_for_job,
)
from services.api.app.monitoring_ai_repository import (
    MonitoringAiRepository,
    MonitoringAiRepositoryError,
    MonitoringAiStateConflictError,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


class MutableClock:
    def __init__(self) -> None:
        self._value = datetime(2026, 7, 29, 2, 0, tzinfo=timezone.utc)
        self._lock = Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self._value

    def advance(self, **kwargs: int) -> None:
        with self._lock:
            self._value += timedelta(**kwargs)


def _revision(
    *,
    suffix: str = "001",
    project_id: str = "project-alpha",
) -> MonitoringAiInputRevision:
    return MonitoringAiInputRevision(
        project_id=project_id,
        batch_revision=f"batch-{suffix}",
        mapping_revision=f"mapping-{suffix}",
        protocol_version="protocol-v1",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id="source-listing",
                source_content_sha256=HASH_A,
            ),
            MonitoringAiSourceBinding(
                source_entry_id="source-protocol",
                source_content_sha256=HASH_B,
            ),
        ),
    )


def _request(
    *,
    task_type: MonitoringAiTaskType = MonitoringAiTaskType.LISTING_FIELD_MAPPING,
    suffix: str = "001",
    max_attempts: int = 2,
    project_id: str = "project-alpha",
    business_key: str = "field-mapping",
) -> MonitoringAiJobCreate:
    revision = _revision(suffix=suffix, project_id=project_id)
    return MonitoringAiJobCreate(
        project_id=revision.project_id,
        task_type=task_type,
        input_revision=revision,
        input_payload={
            "batch_id": f"batch-{suffix}",
            "field_profiles": [{"domain": "LB", "field": "LBORRES"}],
        },
        prompt_version="monitoring-field-mapping-v1",
        profile_id="independent-ai-test",
        provider="test-provider",
        requested_model="test-model",
        max_attempts=max_attempts,
        business_key=business_key,
    )


def test_job_create_rejects_boolean_max_attempts() -> None:
    with pytest.raises(ValidationError):
        _request(max_attempts=True)  # type: ignore[arg-type]


def test_claim_rejects_boolean_confidence() -> None:
    with pytest.raises(ValidationError):
        MonitoringAiClaim(
            claim_id="claim-bool-confidence",
            kind=MonitoringAiClaimKind.RECOMMENDATION,
            text="建议结合完整项目上下文复核。",
            confidence=True,  # type: ignore[arg-type]
            uncertainty="尚未完成医学经理确认。",
            user_action="请确认或修订。",
            evidence_ids=("evidence-001",),
        )


def _candidate(job, clock: MutableClock, *, index: int = 1):
    evidence = MonitoringAiEvidence(
        evidence_id=f"evidence-{index}",
        source_entry_id="source-listing",
        source_content_sha256=HASH_A,
        locator=f"batch://LB/LBORRES/{index}",
        raw_fields={"domain": "LB", "field": "LBORRES"},
        input_revision_sha256=job.input_revision_sha256,
    )
    claim = MonitoringAiClaim(
        claim_id=f"claim-{index}",
        kind=MonitoringAiClaimKind.RECOMMENDATION,
        text="建议将该字段作为原始检验结果候选映射。",
        confidence=0.85,
        uncertainty="字段语义仍需结合同域单位和参考范围字段复核。",
        user_action="请确认字段角色。",
        evidence_ids=(evidence.evidence_id,),
    )
    return MonitoringAiCandidate(
        candidate_id=f"candidate-{job.job_id}-{index}",
        job_id=job.job_id,
        project_id=job.project_id,
        task_type=job.task_type,
        candidate_type="field_mapping",
        title=f"字段映射候选 {index}",
        structured_payload={"domain": "LB", "field": "LBORRES"},
        claims=(claim,),
        evidence=(evidence,),
        input_revision_sha256=job.input_revision_sha256,
        prompt_version=job.prompt_version,
        created_at=clock(),
    )


def test_input_revision_preserves_exact_source_hash_binding() -> None:
    revision = _revision()
    assert revision.source_pairs == {
        ("source-listing", HASH_A),
        ("source-protocol", HASH_B),
    }

    with pytest.raises(ValidationError, match="cannot bind multiple hashes"):
        MonitoringAiInputRevision(
            project_id="project-alpha",
            batch_revision="batch-001",
            sources=(
                MonitoringAiSourceBinding(
                    source_entry_id="source-listing",
                    source_content_sha256=HASH_A,
                ),
                MonitoringAiSourceBinding(
                    source_entry_id="source-listing",
                    source_content_sha256=HASH_B,
                ),
            ),
        )


def test_create_is_idempotent_and_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    first_repository = MonitoringAiRepository(path)
    first = first_repository.create_or_get(_request())
    second = first_repository.create_or_get(_request())
    assert first.job_id == second.job_id
    assert first.status == MonitoringAiJobStatus.QUEUED

    reopened = MonitoringAiRepository(path)
    restored = reopened.get(first.project_id, first.job_id)
    assert restored == first


def test_persisted_input_payload_tamper_is_rejected_on_restart_read(
    tmp_path: Path,
) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    created = repository.create_or_get(_request())

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_jobs SET input_payload_json = ? "
            "WHERE job_id = ?",
            ('{"prompt":"tampered"}', created.job_id),
        )
    reopened = MonitoringAiRepository(path)
    with pytest.raises(
        MonitoringAiRepositoryError,
        match="input payload hash mismatch",
    ):
        reopened.get(created.project_id, created.job_id)
    with pytest.raises(
        MonitoringAiRepositoryError,
        match="input payload hash mismatch",
    ):
        reopened.input_payload(created.project_id, created.job_id)


def test_persisted_input_revision_and_job_identity_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    created = repository.create_or_get(_request())
    revision_payload = _request().input_revision.model_dump(mode="json")
    revision_payload["batch_revision"] = "batch-tampered"

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_jobs SET input_revision_json = ? "
            "WHERE job_id = ?",
            (json.dumps(revision_payload), created.job_id),
        )
    reopened = MonitoringAiRepository(path)
    with pytest.raises(
        MonitoringAiRepositoryError,
        match="input revision hash mismatch",
    ):
        reopened.get(created.project_id, created.job_id)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_jobs SET input_revision_json = ?, "
            "business_key = ? WHERE job_id = ?",
            (
                _request().input_revision.model_dump_json(),
                "tampered-business-key",
                created.job_id,
            ),
        )
    with pytest.raises(
        MonitoringAiRepositoryError,
        match="job identity mismatch",
    ):
        reopened.get(created.project_id, created.job_id)


def test_persisted_job_root_rejects_non_integral_attempt_count(
    tmp_path: Path,
) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    created = repository.create_or_get(_request())

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_jobs SET attempt_count = 1.5 "
            "WHERE job_id = ?",
            (created.job_id,),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match="attempt_count must be an integer",
    ):
        repository.get(created.project_id, created.job_id)


def test_persisted_job_root_rejects_invalid_created_at(
    tmp_path: Path,
) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    created = repository.create_or_get(_request())

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_jobs SET created_at = 'not-a-time' "
            "WHERE job_id = ?",
            (created.job_id,),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match="created_at must be an ISO datetime",
    ):
        repository.get(created.project_id, created.job_id)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    (
        ("business_key", "", "business_key must be non-empty text"),
        ("output_sha256", "A" * 64, "output_sha256 must be a lowercase SHA-256"),
        ("output_sha256", f" {'a' * 64}", "output_sha256 must be a lowercase SHA-256"),
    ),
)
def test_persisted_job_root_rejects_missing_identity_or_noncanonical_hash(
    tmp_path: Path,
    column: str,
    value: str,
    message: str,
) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    created = repository.create_or_get(_request())

    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE monitoring_ai_jobs SET {column} = ? WHERE job_id = ?",
            (value, created.job_id),
        )

    with pytest.raises(MonitoringAiRepositoryError, match=message):
        repository.get(created.project_id, created.job_id)


def test_persisted_candidate_parent_binding_tamper_is_rejected_on_read(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path, clock=clock)
    repository.create_or_get(_request())
    running = repository.claim_next("worker-a")
    assert running is not None
    candidate = _candidate(running, clock)
    repository.complete(
        running,
        owner="worker-a",
        response_model="test-model",
        raw_output={"candidates": [candidate.model_dump(mode="json")]},
        candidates=(candidate,),
    )

    tampered = candidate.model_dump(mode="json")
    tampered["task_type"] = MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES.value
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_candidates SET candidate_json = ? "
            "WHERE candidate_id = ?",
            (json.dumps(tampered), candidate.candidate_id),
        )
    with pytest.raises(
        MonitoringAiRepositoryError,
        match="candidate parent binding mismatch",
    ):
        repository.candidates(running.project_id, running.job_id)


def _completed_candidate_repository(tmp_path: Path):
    clock = MutableClock()
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path, clock=clock)
    repository.create_or_get(_request())
    running = repository.claim_next("worker-a")
    assert running is not None
    candidate = _candidate(running, clock)
    repository.complete(
        running,
        owner="worker-a",
        response_model="test-model",
        raw_output={"candidates": [candidate.model_dump(mode="json")]},
        candidates=(candidate,),
    )
    return path, repository, running, candidate


@pytest.mark.parametrize(
    ("column", "value", "message"),
    (
        ("created_at", "not-a-time", "created_at must be an ISO datetime"),
        ("input_revision_sha256", "A" * 64, "lowercase SHA-256"),
        ("input_revision_sha256", f" {'a' * 64}", "lowercase SHA-256"),
    ),
)
def test_candidate_decision_revalidates_persisted_row_shape_before_cas(
    tmp_path: Path,
    column: str,
    value: str,
    message: str,
) -> None:
    path, repository, running, candidate = _completed_candidate_repository(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE monitoring_ai_candidates SET {column} = ? "
            "WHERE candidate_id = ?",
            (value, candidate.candidate_id),
        )

    with pytest.raises(MonitoringAiRepositoryError, match=message):
        repository.decide_candidate(
            running.project_id,
            candidate.candidate_id,
            decision=MonitoringAiCandidateStatus.ACCEPTED,
            actor="medical-manager",
            reason="确认候选",
            current_input_revision_sha256=running.input_revision_sha256,
        )


def test_idempotent_candidate_decision_revalidates_persisted_json_before_replay(
    tmp_path: Path,
) -> None:
    path, repository, running, candidate = _completed_candidate_repository(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_candidates SET candidate_json = ? "
            "WHERE candidate_id = ?",
            ("{", candidate.candidate_id),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match="persisted monitoring AI candidate is invalid",
    ):
        repository.decide_candidate_idempotent_exclusive(
            running.project_id,
            candidate.candidate_id,
            decision=MonitoringAiCandidateStatus.ACCEPTED,
            actor="medical-manager",
            reason="确认候选",
            current_input_revision_sha256=running.input_revision_sha256,
        )


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    ((0, False), (1, True)),
)
def test_persisted_retryable_accepts_only_sqlite_boolean_values(
    tmp_path: Path,
    raw_value: int,
    expected: bool,
) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    created = repository.create_or_get(_request())

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_jobs SET retryable = ? WHERE job_id = ?",
            (raw_value, created.job_id),
        )

    restored = repository.get(created.project_id, created.job_id)
    assert restored.retryable is expected


@pytest.mark.parametrize("raw_value", ("false", 2, -1))
def test_malformed_persisted_retryable_fails_closed(
    tmp_path: Path,
    raw_value: object,
) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    created = repository.create_or_get(_request())

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_jobs SET retryable = ? WHERE job_id = ?",
            (raw_value, created.job_id),
        )

    with pytest.raises(MonitoringAiRepositoryError, match="retryable"):
        repository.get(created.project_id, created.job_id)


def test_only_one_worker_claims_a_job(tmp_path: Path) -> None:
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    repository.create_or_get(_request())
    barrier = Barrier(2)

    def claim(owner: str):
        barrier.wait()
        return repository.claim_next(owner)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ("worker-a", "worker-b")))
    claimed = [item for item in results if item is not None]
    assert len(claimed) == 1
    assert claimed[0].status == MonitoringAiJobStatus.RUNNING
    assert claimed[0].attempt_count == 1


def test_claim_next_balances_running_slots_across_projects(tmp_path: Path) -> None:
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    for index in range(4):
        repository.create_or_get(
            _request(
                project_id="project-alpha",
                business_key=f"alpha-{index}",
            )
        )
    for index in range(4):
        repository.create_or_get(
            _request(
                project_id="project-beta",
                business_key=f"beta-{index}",
            )
        )

    first = repository.claim_next("worker-a")
    second = repository.claim_next("worker-b")
    third = repository.claim_next("worker-c")
    fourth = repository.claim_next("worker-d")

    assert first is not None
    assert second is not None
    assert third is not None
    assert fourth is not None
    assert [first.project_id, second.project_id, third.project_id, fourth.project_id] == [
        "project-alpha",
        "project-beta",
        "project-alpha",
        "project-beta",
    ]


def test_late_worker_cannot_record_or_complete_after_lease_reclaim(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        lease_seconds=10,
        clock=clock,
    )
    repository.create_or_get(_request())
    first = repository.claim_next("worker-a")
    assert first is not None
    clock.advance(seconds=11)
    second = repository.claim_next("worker-b")
    assert second is not None
    assert second.attempt_count == 2

    with pytest.raises(MonitoringAiStateConflictError, match="attempt"):
        repository.record_attempt(
            first,
            owner="worker-a",
            request_payload={"request": 1},
            response_payload={"response": 1},
            outcome="success",
        )
    with pytest.raises(MonitoringAiStateConflictError, match="completion"):
        repository.complete(
            first,
            owner="worker-a",
            response_model="test-model",
            raw_output={"candidates": []},
            candidates=(_candidate(first, clock),),
        )


def test_expired_final_attempt_becomes_explicitly_retryable_terminal(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        lease_seconds=10,
        clock=clock,
    )
    created = repository.create_or_get(_request(max_attempts=1))
    claimed = repository.claim_next("worker-a")
    assert claimed is not None
    assert claimed.attempt_count == claimed.max_attempts == 1

    clock.advance(seconds=11)
    assert repository.claim_next("worker-b") is None
    assert repository.get(created.project_id, created.job_id).status == (
        MonitoringAiJobStatus.RUNNING
    )

    recovered = repository.expire_exhausted_leases(
        project_id=created.project_id,
    )
    assert recovered == 1
    failed = repository.get(created.project_id, created.job_id)
    assert failed.status == MonitoringAiJobStatus.FAILED
    assert failed.failure_code == "worker_lease_expired"
    assert failed.retryable is True
    assert failed.lease_owner == ""
    assert failed.lease_expires_at is None

    retried = repository.retry_terminal(
        created.project_id,
        created.job_id,
        current_input_revision_sha256=created.input_revision_sha256,
    )
    assert retried.status == MonitoringAiJobStatus.QUEUED
    replacement = repository.claim_next("worker-c")
    assert replacement is not None
    assert replacement.attempt_count == 2

    with pytest.raises(MonitoringAiStateConflictError, match="completion"):
        repository.complete(
            claimed,
            owner="worker-a",
            response_model="test-model",
            raw_output={"candidates": []},
            candidates=(_candidate(claimed, clock),),
        )


def test_retry_is_bounded_and_attempt_is_auditable(tmp_path: Path) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    clock = MutableClock()
    repository = MonitoringAiRepository(path, clock=clock)
    repository.create_or_get(_request(max_attempts=2))

    first = repository.claim_next("worker-a")
    assert first is not None
    repository.record_attempt(
        first,
        owner="worker-a",
        request_payload={"request": 1},
        response_payload=None,
        outcome="transport_error",
        failure_code="timeout",
        failure_message="provider timeout",
    )
    queued = repository.fail(
        first,
        owner="worker-a",
        failure_code="timeout",
        failure_message="provider timeout",
        retryable=True,
    )
    assert queued.status == MonitoringAiJobStatus.QUEUED

    second = repository.claim_next("worker-b")
    assert second is not None
    repository.record_attempt(
        second,
        owner="worker-b",
        request_payload={"request": 2},
        response_payload=None,
        outcome="invalid_output",
        failure_code="schema",
        failure_message="invalid JSON",
    )
    failed = repository.fail(
        second,
        owner="worker-b",
        failure_code="schema",
        failure_message="invalid JSON",
        retryable=True,
    )
    assert failed.status == MonitoringAiJobStatus.FAILED
    assert repository.claim_next("worker-c") is None

    with sqlite3.connect(path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM monitoring_ai_attempts"
        ).fetchone()[0]
    assert count == 2


def test_claimed_job_can_transition_to_terminal_stale_input(tmp_path: Path) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    repository.create_or_get(_request())
    job = repository.claim_next("worker-a")
    assert job is not None
    repository.record_attempt(
        job,
        owner="worker-a",
        request_payload={"job_id": job.job_id},
        response_payload=None,
        outcome="stale_input",
        failure_code="stale_input_revision",
        failure_message="input changed during provider call",
    )

    stale = repository.stale_claimed(
        job,
        owner="worker-a",
        reason="input changed during provider call",
    )

    assert stale.status == MonitoringAiJobStatus.STALE_INPUT
    assert stale.failure_code == "stale_input_revision"
    assert stale.retryable is False
    assert repository.claim_next("worker-b") is None


def test_candidate_validation_rejects_cross_bound_source_hash_pair(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    repository.create_or_get(_request())
    job = repository.claim_next("worker-a")
    assert job is not None
    candidate = _candidate(job, clock)
    invalid_evidence = candidate.evidence[0].model_copy(
        update={
            "source_entry_id": "source-listing",
            "source_content_sha256": HASH_B,
        }
    )
    invalid = candidate.model_copy(update={"evidence": (invalid_evidence,)})
    with pytest.raises(ValueError, match="source/hash pair"):
        validate_candidates_for_job(job, (invalid,))


def test_candidate_validation_rejects_source_evidence_when_revision_has_no_sources(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    source_less_revision = MonitoringAiInputRevision(
        project_id="project-alpha",
        batch_revision="batch-without-source-bindings",
    )
    repository.create_or_get(
        _request().model_copy(update={"input_revision": source_less_revision})
    )
    job = repository.claim_next("worker-a")
    assert job is not None
    candidate = _candidate(job, clock)

    with pytest.raises(ValueError, match="source/hash pair"):
        validate_candidates_for_job(job, (candidate,))


def test_completion_decision_and_stale_input_are_fail_closed(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    repository.create_or_get(_request())
    job = repository.claim_next("worker-a")
    assert job is not None
    candidate = _candidate(job, clock)
    repository.record_attempt(
        job,
        owner="worker-a",
        request_payload={"prompt": "mapping"},
        response_payload={"candidates": [candidate.model_dump(mode="json")]},
        response_model="test-model",
        outcome="success",
    )
    completed = repository.complete(
        job,
        owner="worker-a",
        response_model="test-model",
        raw_output={"candidates": [candidate.model_dump(mode="json")]},
        candidates=(candidate,),
    )
    assert completed.status == MonitoringAiJobStatus.COMPLETED
    assert completed.response_model == "test-model"

    accepted = repository.decide_candidate(
        job.project_id,
        candidate.candidate_id,
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        actor="medical-manager",
        reason="映射语义与原始字段一致。",
        current_input_revision_sha256=job.input_revision_sha256,
    )
    assert accepted.status == MonitoringAiCandidateStatus.ACCEPTED
    assert repository.candidates(job.project_id, job.job_id)[0].status == (
        MonitoringAiCandidateStatus.ACCEPTED
    )
    with pytest.raises(MonitoringAiStateConflictError, match="no longer proposed"):
        repository.decide_candidate(
            job.project_id,
            candidate.candidate_id,
            decision=MonitoringAiCandidateStatus.REJECTED,
            actor="medical-manager",
            reason="重复决策",
            current_input_revision_sha256=job.input_revision_sha256,
        )


def test_repository_rejects_response_model_identity_mismatch(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    repository.create_or_get(_request())
    job = repository.claim_next("worker-a")
    assert job is not None
    with pytest.raises(MonitoringAiStateConflictError, match="response model"):
        repository.complete(
            job,
            owner="worker-a",
            response_model="another-model",
            raw_output={"candidate": 1},
            candidates=(_candidate(job, clock),),
        )


def test_new_input_marks_old_proposals_stale_and_blocks_old_conversation(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    repository.create_or_get(_request())
    old_job = repository.claim_next("worker-a")
    assert old_job is not None
    old_candidate = _candidate(old_job, clock)
    repository.complete(
        old_job,
        owner="worker-a",
        response_model="test-model",
        raw_output={"candidates": [old_candidate.model_dump(mode="json")]},
        candidates=(old_candidate,),
    )
    new_job = repository.create_or_get(_request(suffix="002"))
    changed = repository.mark_stale(
        old_job.project_id,
        business_key=old_job.business_key,
        current_input_revision_sha256=new_job.input_revision_sha256,
    )
    assert changed == 1
    assert repository.get(old_job.project_id, old_job.job_id).status == (
        MonitoringAiJobStatus.STALE_INPUT
    )
    assert repository.candidates(old_job.project_id, old_job.job_id)[0].status == (
        MonitoringAiCandidateStatus.SUPERSEDED
    )

    with pytest.raises(MonitoringAiStateConflictError, match="stale"):
        repository.append_turn(
            old_job.project_id,
            old_job.job_id,
            actor="medical-manager",
            message="请解释该字段映射。",
            current_input_revision_sha256=new_job.input_revision_sha256,
        )


def test_conversation_turn_read_rejects_parent_revision_drift(
    tmp_path: Path,
) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    job = repository.create_or_get(_request())
    turn = repository.append_turn(
        job.project_id,
        job.job_id,
        actor="medical-manager",
        message="请解释该字段映射。",
        current_input_revision_sha256=job.input_revision_sha256,
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_conversation_turns "
            "SET input_revision_sha256 = ? WHERE turn_id = ?",
            ("f" * 64, turn.turn_id),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match="conversation turn parent binding mismatch",
    ):
        repository.turns(job.project_id, job.job_id)


def test_conversation_turn_read_rejects_invalid_timestamp(
    tmp_path: Path,
) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    job = repository.create_or_get(_request())
    turn = repository.append_turn(
        job.project_id,
        job.job_id,
        actor="medical-manager",
        message="请解释该字段映射。",
        current_input_revision_sha256=job.input_revision_sha256,
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_conversation_turns "
            "SET created_at = ? WHERE turn_id = ?",
            ("not-a-time", turn.turn_id),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match="conversation turn is invalid",
    ):
        repository.turns(job.project_id, job.job_id)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    (
        ("input_revision_sha256", "A" * 64, "lowercase SHA-256"),
        ("actor", "", "turn.actor must be non-empty text"),
    ),
)
def test_conversation_turn_read_rejects_malformed_persisted_root(
    tmp_path: Path,
    column: str,
    value: str,
    message: str,
) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    job = repository.create_or_get(_request())
    turn = repository.append_turn(
        job.project_id,
        job.job_id,
        actor="medical-manager",
        message="请解释该字段映射。",
        current_input_revision_sha256=job.input_revision_sha256,
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE monitoring_ai_conversation_turns SET {column} = ? "
            "WHERE turn_id = ?",
            (value, turn.turn_id),
        )

    with pytest.raises(MonitoringAiRepositoryError, match=message):
        repository.turns(job.project_id, job.job_id)


def test_new_prompt_contract_supersedes_same_revision_job(tmp_path: Path) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    old_request = _request()
    old_job = repository.create_or_get(old_request)
    old_job = repository.claim_next("worker-a")
    assert old_job is not None
    old_candidate = _candidate(old_job, clock)
    repository.complete(
        old_job,
        owner="worker-a",
        response_model="test-model",
        raw_output={"candidates": [old_candidate.model_dump(mode="json")]},
        candidates=(old_candidate,),
    )
    new_request = old_request.model_copy(
        update={"prompt_version": "monitoring-field-mapping-v2"}
    )
    new_job = repository.create_or_get(new_request)

    changed = repository.supersede_business_key_except(
        old_job.project_id,
        business_key=old_job.business_key,
        current_job_id=new_job.job_id,
        reason="prompt contract changed",
    )

    assert changed == 1
    old_state = repository.get(old_job.project_id, old_job.job_id)
    assert old_state.status == MonitoringAiJobStatus.STALE_INPUT
    assert old_state.failure_code == "superseded_job_contract"
    assert repository.candidates(old_job.project_id, old_job.job_id)[0].status == (
        MonitoringAiCandidateStatus.SUPERSEDED
    )
    assert repository.get(new_job.project_id, new_job.job_id).status == (
        MonitoringAiJobStatus.QUEUED
    )


def test_new_contract_cancels_running_job_and_rejects_late_completion(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    old_request = _request()
    repository.create_or_get(old_request)
    running = repository.claim_next("worker-old")
    assert running is not None
    new_job = repository.create_or_get(
        old_request.model_copy(
            update={"prompt_version": "monitoring-field-mapping-v2"}
        )
    )

    changed = repository.supersede_business_key_except(
        running.project_id,
        business_key=running.business_key,
        current_job_id=new_job.job_id,
        reason="prompt contract changed",
    )

    assert changed == 1
    assert repository.get(running.project_id, running.job_id).status == (
        MonitoringAiJobStatus.STALE_INPUT
    )
    with pytest.raises(MonitoringAiStateConflictError, match="completion"):
        repository.complete(
            running,
            owner="worker-old",
            response_model="test-model",
            raw_output={"candidates": []},
            candidates=(_candidate(running, clock),),
        )


def test_business_key_supersession_preserves_marked_terminal_rows(
    tmp_path: Path,
) -> None:
    """Completed/failed rows that already carry an immutable
    contract-retirement marker keep status, failure evidence, timestamps and
    candidates when a same-business-key supersession runs; unmarked terminal
    rows still retire exactly as before."""
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    completed_request = _request(suffix="201")
    completed_job = repository.create_or_get(completed_request)
    completed_job = repository.claim_next("worker-completed-marked")
    assert completed_job is not None
    completed_candidate = _candidate(completed_job, clock)
    repository.complete(
        completed_job,
        owner="worker-completed-marked",
        response_model="test-model",
        raw_output={
            "candidates": [completed_candidate.model_dump(mode="json")]
        },
        candidates=(completed_candidate,),
    )

    failed_request = _request(suffix="202")
    failed_job = repository.create_or_get(failed_request)
    failed_job = repository.claim_next("worker-failed-marked")
    assert failed_job is not None
    repository.fail(
        failed_job,
        owner="worker-failed-marked",
        failure_code="invalid_ai_output",
        failure_message=(
            "provider output remained invalid after one controlled repair"
        ),
        retryable=False,
    )

    # Startup-style prompt cutover marks both terminal rows while preserving
    # their status, evidence and candidates.
    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        current_prompt_version="monitoring-field-mapping-v2",
        legacy_terminal_prompt_versions=frozenset(
            {"monitoring-field-mapping-v1"}
        ),
    )
    assert changed == 0
    marked_completed = repository.get(
        completed_job.project_id,
        completed_job.job_id,
    )
    assert marked_completed.status == MonitoringAiJobStatus.COMPLETED
    assert marked_completed.contract_retirement_code == (
        "superseded_prompt_contract"
    )
    marked_failed = repository.get(failed_job.project_id, failed_job.job_id)
    assert marked_failed.status == MonitoringAiJobStatus.FAILED
    assert marked_failed.failure_code == "invalid_ai_output"
    assert marked_failed.contract_retirement_code == (
        "superseded_prompt_contract"
    )

    # An unmarked same-key terminal row still retires under the old rules.
    unmarked_request = _request(suffix="203")
    unmarked_job = repository.create_or_get(unmarked_request)
    unmarked_job = repository.claim_next("worker-unmarked-failed")
    assert unmarked_job is not None
    repository.fail(
        unmarked_job,
        owner="worker-unmarked-failed",
        failure_code="provider_timeout",
        failure_message="provider timed out",
        retryable=False,
    )

    newer = repository.create_or_get(
        _request(suffix="204").model_copy(
            update={"prompt_version": "monitoring-field-mapping-v2"}
        )
    )
    clock.advance(minutes=5)
    changed = repository.supersede_business_key_except(
        newer.project_id,
        business_key=newer.business_key,
        current_job_id=newer.job_id,
        reason="prompt contract changed",
    )

    # Only the unmarked terminal row is retired; marked terminal rows keep
    # status, failure evidence, timestamps and candidates.
    assert changed == 1
    preserved_completed = repository.get(
        completed_job.project_id,
        completed_job.job_id,
    )
    assert preserved_completed.status == MonitoringAiJobStatus.COMPLETED
    assert preserved_completed.failure_code == ""
    assert preserved_completed.updated_at == marked_completed.updated_at
    assert preserved_completed.contract_retirement_code == (
        "superseded_prompt_contract"
    )
    assert repository.candidates(
        preserved_completed.project_id,
        preserved_completed.job_id,
    )[0].status == MonitoringAiCandidateStatus.PROPOSED

    preserved_failed = repository.get(failed_job.project_id, failed_job.job_id)
    assert preserved_failed.status == MonitoringAiJobStatus.FAILED
    assert preserved_failed.failure_code == "invalid_ai_output"
    assert preserved_failed.failure_message == (
        "provider output remained invalid after one controlled repair"
    )
    assert preserved_failed.retryable is False
    assert preserved_failed.updated_at == marked_failed.updated_at
    assert preserved_failed.contract_retirement_code == (
        "superseded_prompt_contract"
    )

    retired_unmarked = repository.get(
        unmarked_job.project_id,
        unmarked_job.job_id,
    )
    assert retired_unmarked.status == MonitoringAiJobStatus.STALE_INPUT
    assert retired_unmarked.failure_code == "superseded_job_contract"
    assert retired_unmarked.updated_at != marked_failed.updated_at
    assert repository.get(newer.project_id, newer.job_id).status == (
        MonitoringAiJobStatus.QUEUED
    )


def test_startup_prompt_cutover_retires_only_obsolete_task_contracts(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    old_request = _request()
    old_completed = repository.create_or_get(old_request)
    old_completed = repository.claim_next("worker-completed")
    assert old_completed is not None
    old_candidate = _candidate(old_completed, clock)
    repository.complete(
        old_completed,
        owner="worker-completed",
        response_model="test-model",
        raw_output={"candidates": [old_candidate.model_dump(mode="json")]},
        candidates=(old_candidate,),
    )
    old_running = repository.create_or_get(_request(suffix="002"))
    old_running = repository.claim_next("worker-running")
    assert old_running is not None
    current = repository.create_or_get(
        _request(suffix="003").model_copy(
            update={"prompt_version": "monitoring-field-mapping-v13"}
        )
    )
    other_task = repository.create_or_get(
        _request(
            task_type=MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
            suffix="004",
        )
    )

    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        current_prompt_version="monitoring-field-mapping-v13",
    )

    assert changed == 2
    for retired in (old_completed, old_running):
        state = repository.get(retired.project_id, retired.job_id)
        assert state.status == MonitoringAiJobStatus.STALE_INPUT
        assert state.failure_code == "superseded_prompt_contract"
        assert state.lease_owner == ""
        assert state.lease_expires_at is None
    assert repository.candidates(
        old_completed.project_id,
        old_completed.job_id,
    )[0].status == MonitoringAiCandidateStatus.SUPERSEDED
    assert repository.get(current.project_id, current.job_id).status == (
        MonitoringAiJobStatus.QUEUED
    )
    assert repository.get(other_task.project_id, other_task.job_id).status == (
        MonitoringAiJobStatus.QUEUED
    )


def test_legacy_terminal_prompt_versions_preserve_terminal_audit_only(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    legacy_versions = frozenset(
        {"monitoring-field-mapping-v3", "monitoring-field-mapping-v4"}
    )
    current_prompt_version = "monitoring-field-mapping-v13"

    completed_legacy = repository.create_or_get(
        _request(suffix="100").model_copy(
            update={"prompt_version": "monitoring-field-mapping-v4"}
        )
    )
    completed_legacy = repository.claim_next("worker-completed-legacy")
    assert completed_legacy is not None
    legacy_candidate = _candidate(completed_legacy, clock)
    repository.complete(
        completed_legacy,
        owner="worker-completed-legacy",
        response_model="test-model",
        raw_output={
            "candidates": [legacy_candidate.model_dump(mode="json")]
        },
        candidates=(legacy_candidate,),
    )

    failed_legacy = repository.create_or_get(
        _request(suffix="101").model_copy(
            update={"prompt_version": "monitoring-field-mapping-v3"}
        )
    )
    failed_legacy = repository.claim_next("worker-failed-legacy")
    assert failed_legacy is not None
    repository.fail(
        failed_legacy,
        owner="worker-failed-legacy",
        failure_code="provider_timeout",
        failure_message="provider timed out",
        retryable=False,
    )

    running_legacy = repository.create_or_get(
        _request(suffix="102").model_copy(
            update={"prompt_version": "monitoring-field-mapping-v3"}
        )
    )
    running_legacy = repository.claim_next("worker-running-legacy")
    assert running_legacy is not None
    assert running_legacy.status == MonitoringAiJobStatus.RUNNING

    obsolete_completed = repository.create_or_get(
        _request(suffix="103").model_copy(
            update={"prompt_version": "monitoring-field-mapping-v2"}
        )
    )
    obsolete_completed = repository.claim_next("worker-obsolete-completed")
    assert obsolete_completed is not None
    obsolete_candidate = _candidate(obsolete_completed, clock)
    repository.complete(
        obsolete_completed,
        owner="worker-obsolete-completed",
        response_model="test-model",
        raw_output={
            "candidates": [obsolete_candidate.model_dump(mode="json")]
        },
        candidates=(obsolete_candidate,),
    )

    queued_legacy = repository.create_or_get(
        _request(suffix="104").model_copy(
            update={"prompt_version": "monitoring-field-mapping-v4"}
        )
    )
    blocked_legacy = repository.create_or_get(
        _request(suffix="105").model_copy(
            update={"prompt_version": "monitoring-field-mapping-v4"}
        )
    )
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_jobs SET status = ? WHERE job_id = ?",
            (
                MonitoringAiJobStatus.BLOCKED.value,
                blocked_legacy.job_id,
            ),
        )
    current = repository.create_or_get(
        _request(suffix="106").model_copy(
            update={"prompt_version": current_prompt_version}
        )
    )

    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        current_prompt_version=current_prompt_version,
        legacy_terminal_prompt_versions=legacy_versions,
    )

    assert changed == 4
    preserved = repository.get(
        completed_legacy.project_id,
        completed_legacy.job_id,
    )
    assert preserved.status == MonitoringAiJobStatus.COMPLETED
    assert repository.candidates(
        completed_legacy.project_id,
        completed_legacy.job_id,
    )[0].status == MonitoringAiCandidateStatus.PROPOSED
    failed = repository.get(failed_legacy.project_id, failed_legacy.job_id)
    assert failed.status == MonitoringAiJobStatus.FAILED
    assert failed.failure_code == "provider_timeout"
    for retired in (queued_legacy, running_legacy, blocked_legacy):
        state = repository.get(retired.project_id, retired.job_id)
        assert state.status == MonitoringAiJobStatus.STALE_INPUT
        assert state.failure_code == "superseded_prompt_contract"
        assert state.lease_owner == ""
        assert state.lease_expires_at is None
    retired_obsolete = repository.get(
        obsolete_completed.project_id,
        obsolete_completed.job_id,
    )
    assert retired_obsolete.status == MonitoringAiJobStatus.STALE_INPUT
    assert repository.candidates(
        obsolete_completed.project_id,
        obsolete_completed.job_id,
    )[0].status == MonitoringAiCandidateStatus.SUPERSEDED

    claimed = repository.claim_next("startup-worker")
    assert claimed is not None
    assert claimed.job_id == current.job_id


def test_legacy_terminal_prompt_versions_empty_default_retires_terminal_jobs(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    completed_old = repository.create_or_get(_request(suffix="200"))
    completed_old = repository.claim_next("worker-completed-old")
    assert completed_old is not None
    candidate = _candidate(completed_old, clock)
    repository.complete(
        completed_old,
        owner="worker-completed-old",
        response_model="test-model",
        raw_output={"candidates": [candidate.model_dump(mode="json")]},
        candidates=(candidate,),
    )
    failed_old = repository.create_or_get(_request(suffix="201"))
    failed_old = repository.claim_next("worker-failed-old")
    assert failed_old is not None
    repository.fail(
        failed_old,
        owner="worker-failed-old",
        failure_code="provider_timeout",
        failure_message="provider timed out",
        retryable=False,
    )

    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        current_prompt_version="monitoring-field-mapping-v13",
        legacy_terminal_prompt_versions=(),
    )

    assert changed == 2
    for old in (completed_old, failed_old):
        state = repository.get(old.project_id, old.job_id)
        assert state.status == MonitoringAiJobStatus.STALE_INPUT
        assert state.failure_code == "superseded_prompt_contract"
    assert repository.candidates(
        completed_old.project_id,
        completed_old.job_id,
    )[0].status == MonitoringAiCandidateStatus.SUPERSEDED


def test_prompt_cutover_can_be_scoped_to_one_project(tmp_path: Path) -> None:
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    first = repository.create_or_get(_request())
    second_request = _request(suffix="002")
    second_revision = second_request.input_revision.model_copy(
        update={"project_id": "project-beta"}
    )
    second = repository.create_or_get(
        second_request.model_copy(
            update={
                "project_id": "project-beta",
                "input_revision": second_revision,
            }
        )
    )

    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        current_prompt_version="monitoring-field-mapping-v13",
        project_id="project-alpha",
    )

    assert changed == 1
    assert repository.get(first.project_id, first.job_id).status == (
        MonitoringAiJobStatus.STALE_INPUT
    )
    assert repository.get(second.project_id, second.job_id).status == (
        MonitoringAiJobStatus.QUEUED
    )


def test_query_explanation_requires_two_to_three_candidates(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    repository.create_or_get(
        _request(task_type=MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES)
    )
    job = repository.claim_next("worker-a")
    assert job is not None
    with pytest.raises(ValueError, match="2 to 3"):
        validate_candidates_for_job(job, (_candidate(job, clock),))


def test_job_for_candidate_is_project_scoped(tmp_path: Path) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    repository.create_or_get(_request())
    running = repository.claim_next("worker-a")
    assert running is not None
    candidate = _candidate(running, clock)
    repository.complete(
        running,
        owner="worker-a",
        response_model="test-model",
        raw_output={"candidates": 1},
        candidates=(candidate,),
    )

    assert repository.job_for_candidate(
        running.project_id,
        candidate.candidate_id,
    ).job_id == running.job_id
    with pytest.raises(
        MonitoringAiRepositoryError,
        match="candidate not found",
    ):
        repository.job_for_candidate(
            "another-project",
            candidate.candidate_id,
        )


def test_attempt_audit_preserves_request_and_response_payloads(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    repository.create_or_get(_request())
    running = repository.claim_next("worker-a")
    assert running is not None
    request_payload = {"prompt": {"task": "field-mapping"}}
    response_payload = {"candidates": [{"title": "候选"}]}

    repository.record_attempt(
        running,
        owner="worker-a",
        request_payload=request_payload,
        response_payload=response_payload,
        response_model="test-model",
        outcome="invalid_output",
        failure_code="invalid_ai_output",
        failure_message="schema mismatch",
    )

    attempts = repository.attempts(running.project_id, running.job_id)
    assert len(attempts) == 1
    assert attempts[0]["request"] == request_payload
    assert attempts[0]["response"] == response_payload
    assert attempts[0]["failure_code"] == "invalid_ai_output"
    with pytest.raises(MonitoringAiRepositoryError):
        repository.attempts("another-project", running.job_id)


def test_attempt_read_rejects_request_payload_hash_drift(tmp_path: Path) -> None:
    clock = MutableClock()
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path, clock=clock)
    repository.create_or_get(_request())
    running = repository.claim_next("worker-a")
    assert running is not None
    repository.record_attempt(
        running,
        owner="worker-a",
        request_payload={"prompt": {"task": "field-mapping"}},
        response_payload=None,
        outcome="transport_error",
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_attempts SET request_json = ? "
            "WHERE job_id = ?",
            ('{"prompt":{"task":"tampered"}}', running.job_id),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match="request payload hash mismatch",
    ):
        repository.attempts(running.project_id, running.job_id)


def test_attempt_read_rejects_response_payload_hash_drift(tmp_path: Path) -> None:
    clock = MutableClock()
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path, clock=clock)
    repository.create_or_get(_request())
    running = repository.claim_next("worker-a")
    assert running is not None
    repository.record_attempt(
        running,
        owner="worker-a",
        request_payload={"prompt": {"task": "field-mapping"}},
        response_payload={"candidates": [{"title": "候选"}]},
        outcome="invalid_output",
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_attempts SET response_json = ? "
            "WHERE job_id = ?",
            ('{"candidates":[{"title":"tampered"}]}', running.job_id),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match="response payload hash mismatch",
    ):
        repository.attempts(running.project_id, running.job_id)


@pytest.mark.parametrize("field", ["request_sha256", "response_sha256"])
def test_attempt_read_rejects_noncanonical_payload_hash(
    tmp_path: Path,
    field: str,
) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    repository.create_or_get(_request())
    running = repository.claim_next("worker-a")
    assert running is not None
    request_payload = {"prompt": {"task": "field-mapping"}}
    response_payload = {"candidates": [{"title": "候选"}]}
    repository.record_attempt(
        running,
        owner="worker-a",
        request_payload=request_payload,
        response_payload=response_payload,
        outcome="invalid_output",
    )

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT request_sha256, response_sha256 FROM monitoring_ai_attempts "
            "WHERE job_id = ?",
            (running.job_id,),
        ).fetchone()
        assert row is not None
        original = row[0] if field == "request_sha256" else row[1]
        malformed = f" {original}" if field == "request_sha256" else original.upper()
        connection.execute(
            f"UPDATE monitoring_ai_attempts SET {field} = ? WHERE job_id = ?",
            (malformed, running.job_id),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match=f"{field.removesuffix('_sha256')} payload hash mismatch",
    ):
        repository.attempts(running.project_id, running.job_id)


def test_attempt_read_rejects_malformed_response_payload(tmp_path: Path) -> None:
    clock = MutableClock()
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path, clock=clock)
    repository.create_or_get(_request())
    running = repository.claim_next("worker-a")
    assert running is not None
    repository.record_attempt(
        running,
        owner="worker-a",
        request_payload={"prompt": {"task": "field-mapping"}},
        response_payload={"candidates": []},
        outcome="invalid_output",
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_attempts SET response_json = ? "
            "WHERE job_id = ?",
            ("not-json", running.job_id),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match="response payload is invalid",
    ):
        repository.attempts(running.project_id, running.job_id)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("attempt_number", 1.5, "attempt_number must be an integer"),
        ("owner", "", "owner must be non-empty text"),
        ("outcome", "", "outcome must be non-empty text"),
        ("created_at", "not-a-time", "created_at must be an ISO datetime"),
    ),
)
def test_attempt_read_rejects_root_shape_tamper(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    repository.create_or_get(_request())
    running = repository.claim_next("worker-a")
    assert running is not None
    repository.record_attempt(
        running,
        owner="worker-a",
        request_payload={"prompt": {"task": "field-mapping"}},
        response_payload=None,
        outcome="transport_error",
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE monitoring_ai_attempts SET {field} = ? WHERE job_id = ?",
            (value, running.job_id),
        )

    with pytest.raises(MonitoringAiRepositoryError, match=message):
        repository.attempts(running.project_id, running.job_id)


def test_attempt_read_rejects_nonempty_payload_without_hash(tmp_path: Path) -> None:
    path = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(path)
    repository.create_or_get(_request())
    running = repository.claim_next("worker-a")
    assert running is not None
    repository.record_attempt(
        running,
        owner="worker-a",
        request_payload={"prompt": {"task": "field-mapping"}},
        response_payload=None,
        outcome="transport_error",
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_attempts SET response_sha256 = ? WHERE job_id = ?",
            ("a" * 64, running.job_id),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match="response payload hash mismatch",
    ):
        repository.attempts(running.project_id, running.job_id)


def test_retry_terminal_requeues_only_same_revision_failed_job(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    repository.create_or_get(_request())
    running = repository.claim_next("worker-a")
    assert running is not None
    failed = repository.fail(
        running,
        owner="worker-a",
        failure_code="provider_timeout",
        failure_message="provider timed out",
        retryable=False,
    )
    assert failed.status == MonitoringAiJobStatus.FAILED

    retried = repository.retry_terminal(
        failed.project_id,
        failed.job_id,
        current_input_revision_sha256=failed.input_revision_sha256,
    )

    assert retried.status == MonitoringAiJobStatus.QUEUED
    assert retried.max_attempts == failed.attempt_count + 2
    assert retried.failure_code == ""
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="failed, blocked or stale",
    ):
        repository.retry_terminal(
            retried.project_id,
            retried.job_id,
            current_input_revision_sha256=retried.input_revision_sha256,
        )
    claimed = repository.claim_next("worker-b")
    assert claimed is not None
    repository.fail(
        claimed,
        owner="worker-b",
        failure_code="provider_timeout",
        failure_message="provider timed out again",
        retryable=False,
    )
    with pytest.raises(MonitoringAiStateConflictError, match="input changed"):
        repository.retry_terminal(
            claimed.project_id,
            claimed.job_id,
            current_input_revision_sha256="f" * 64,
        )


def test_retry_terminal_requeues_stale_job_only_for_same_revision(
    tmp_path: Path,
) -> None:
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    repository.create_or_get(_request())
    running = repository.claim_next("worker-stale")
    assert running is not None
    stale = repository.stale_claimed(
        running,
        owner="worker-stale",
        reason="revision schema changed",
    )

    retried = repository.retry_terminal(
        stale.project_id,
        stale.job_id,
        current_input_revision_sha256=stale.input_revision_sha256,
    )

    assert retried.status == MonitoringAiJobStatus.QUEUED


def test_retry_terminal_restores_stale_completed_job_with_candidates(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    repository.create_or_get(_request())
    running = repository.claim_next("worker-a")
    assert running is not None
    candidate = _candidate(running, clock)
    repository.complete(
        running,
        owner="worker-a",
        response_model=running.requested_model,
        raw_output={"candidates": [candidate.model_dump(mode="json")]},
        candidates=(candidate,),
    )

    changed_revision = _revision(suffix="002")
    repository.mark_stale(
        running.project_id,
        business_key=running.business_key,
        current_input_revision_sha256=changed_revision.revision_sha256,
    )
    stale = repository.get(running.project_id, running.job_id)
    assert stale.status == MonitoringAiJobStatus.STALE_INPUT
    assert repository.candidates(running.project_id, running.job_id)[0].status == (
        MonitoringAiCandidateStatus.SUPERSEDED
    )

    restored = repository.retry_terminal(
        stale.project_id,
        stale.job_id,
        current_input_revision_sha256=stale.input_revision_sha256,
    )

    assert restored.status == MonitoringAiJobStatus.COMPLETED
    restored_candidate = repository.candidates(
        running.project_id,
        running.job_id,
    )[0]
    assert restored_candidate.status == MonitoringAiCandidateStatus.PROPOSED
    with sqlite3.connect(tmp_path / "monitoring-ai.sqlite3") as connection:
        decision = connection.execute(
            """
            SELECT decided_at, decided_by, decision_reason
            FROM monitoring_ai_candidates
            WHERE candidate_id = ?
            """,
            (restored_candidate.candidate_id,),
        ).fetchone()
    assert decision == ("", "", "")


def test_retry_terminal_never_revives_superseded_contracts(tmp_path: Path) -> None:
    """Every contract-superseded failure code is terminal for retry.

    A prompt or job contract can be superseded while the input revision is
    unchanged. Those rows must stay frozen as audit history: retry_terminal
    must refuse to re-queue or restore them even when the caller passes the
    same input revision. Ordinary same-revision stale-input retry and
    completed-candidate restoration remain unchanged.
    """
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )

    workflow_job = repository.create_or_get(_request(suffix="wf"))
    changed = repository.supersede_payload_workflows_except(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        business_key_prefix=workflow_job.business_key,
        current_workflow="monitoring_protocol_preparation_v9",
        project_id=workflow_job.project_id,
        reason="workflow contract upgraded",
    )
    assert changed == 1
    state = repository.get(workflow_job.project_id, workflow_job.job_id)
    assert state.status == MonitoringAiJobStatus.STALE_INPUT
    assert state.failure_code == "superseded_workflow_contract"

    prompt_job = repository.create_or_get(_request(suffix="prompt"))
    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        current_prompt_version="monitoring-field-mapping-v13",
        project_id=prompt_job.project_id,
    )
    assert changed == 1
    state = repository.get(prompt_job.project_id, prompt_job.job_id)
    assert state.status == MonitoringAiJobStatus.STALE_INPUT
    assert state.failure_code == "superseded_prompt_contract"

    old_job = repository.create_or_get(_request(suffix="job"))
    new_job = repository.create_or_get(
        _request(suffix="job").model_copy(
            update={"prompt_version": "monitoring-field-mapping-v2"}
        )
    )
    assert new_job.job_id != old_job.job_id
    changed = repository.supersede_business_key_except(
        old_job.project_id,
        business_key=old_job.business_key,
        current_job_id=new_job.job_id,
        reason="job contract upgraded",
    )
    assert changed == 1
    state = repository.get(old_job.project_id, old_job.job_id)
    assert state.status == MonitoringAiJobStatus.STALE_INPUT
    assert state.failure_code == "superseded_job_contract"

    superseded_codes = {
        workflow_job.job_id: "superseded_workflow_contract",
        prompt_job.job_id: "superseded_prompt_contract",
        old_job.job_id: "superseded_job_contract",
    }
    for code_job in (workflow_job, prompt_job, old_job):
        with pytest.raises(
            MonitoringAiStateConflictError,
            match="cannot be retried",
        ):
            repository.retry_terminal(
                code_job.project_id,
                code_job.job_id,
                current_input_revision_sha256=code_job.input_revision_sha256,
            )
        unchanged = repository.get(code_job.project_id, code_job.job_id)
        assert unchanged.status == MonitoringAiJobStatus.STALE_INPUT
        assert unchanged.failure_code == superseded_codes[code_job.job_id]

    # The newer same-revision job remains normally claimable.
    claimed_new = repository.claim_next("worker-new")
    assert claimed_new is not None
    assert claimed_new.job_id == new_job.job_id
    repository.fail(
        claimed_new,
        owner="worker-new",
        failure_code="provider_timeout",
        failure_message="provider timed out",
        retryable=False,
    )

    # Ordinary same-revision stale-input retry stays available.
    ordinary = repository.create_or_get(_request(suffix="ordinary"))
    claimed = repository.claim_next("worker-stale")
    assert claimed is not None
    assert claimed.job_id == ordinary.job_id
    stale = repository.stale_claimed(
        claimed,
        owner="worker-stale",
        reason="revision schema changed",
    )
    retried = repository.retry_terminal(
        stale.project_id,
        stale.job_id,
        current_input_revision_sha256=stale.input_revision_sha256,
    )
    assert retried.status == MonitoringAiJobStatus.QUEUED

    # Completed-candidate restoration after a stale-input mark stays valid.
    claimed = repository.claim_next("worker-ordinary")
    assert claimed is not None
    assert claimed.job_id == ordinary.job_id
    repository.fail(
        claimed,
        owner="worker-ordinary",
        failure_code="provider_timeout",
        failure_message="provider timed out",
        retryable=False,
    )
    completed = repository.create_or_get(_request(suffix="restore"))
    claimed = repository.claim_next("worker-restore")
    assert claimed is not None
    assert claimed.job_id == completed.job_id
    candidate = _candidate(claimed, clock)
    repository.complete(
        claimed,
        owner="worker-restore",
        response_model=claimed.requested_model,
        raw_output={"candidates": [candidate.model_dump(mode="json")]},
        candidates=(candidate,),
    )
    changed_revision = _revision(suffix="002")
    repository.mark_stale(
        completed.project_id,
        business_key=completed.business_key,
        current_input_revision_sha256=changed_revision.revision_sha256,
    )
    restored = repository.retry_terminal(
        completed.project_id,
        completed.job_id,
        current_input_revision_sha256=completed.input_revision_sha256,
    )
    assert restored.status == MonitoringAiJobStatus.COMPLETED
    assert repository.candidates(
        completed.project_id,
        completed.job_id,
    )[0].status == MonitoringAiCandidateStatus.PROPOSED


def test_prompt_cutover_marks_stale_completed_job_and_blocks_old_revision_retry(
    tmp_path: Path,
) -> None:
    """An already-stale completed job is not skipped by prompt supersession.

    The cutover must durably mark the row even though its status is already
    STALE_INPUT, so an old-revision retry cannot restore the job or its
    superseded candidate afterwards.
    """
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    request = _request(
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        suffix="cutover",
        business_key="protocol-prep",
    ).model_copy(
        update={
            "prompt_version": "monitoring-protocol-clause-structuring-v8"
        }
    )
    job = repository.create_or_get(request)
    claimed = repository.claim_next("worker-a")
    assert claimed is not None
    assert claimed.job_id == job.job_id
    candidate = _candidate(claimed, clock)
    repository.complete(
        claimed,
        owner="worker-a",
        response_model=claimed.requested_model,
        raw_output={"candidates": [candidate.model_dump(mode="json")]},
        candidates=(candidate,),
    )

    changed_revision = _revision(suffix="002")
    repository.mark_stale(
        job.project_id,
        business_key=job.business_key,
        current_input_revision_sha256=changed_revision.revision_sha256,
    )
    stale = repository.get(job.project_id, job.job_id)
    assert stale.status == MonitoringAiJobStatus.STALE_INPUT
    assert repository.candidates(job.project_id, job.job_id)[0].status == (
        MonitoringAiCandidateStatus.SUPERSEDED
    )

    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        current_prompt_version="monitoring-protocol-clause-structuring-v9",
        project_id=job.project_id,
    )
    assert changed == 0
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="cannot be retried",
    ):
        repository.retry_terminal(
            job.project_id,
            job.job_id,
            current_input_revision_sha256=job.input_revision_sha256,
        )
    after = repository.get(job.project_id, job.job_id)
    assert after.status == MonitoringAiJobStatus.STALE_INPUT
    assert repository.candidates(job.project_id, job.job_id)[0].status == (
        MonitoringAiCandidateStatus.SUPERSEDED
    )
    assert after.contract_retirement_code == "superseded_prompt_contract"
    assert after.contract_retirement_reason
    assert after.contract_retired_at is not None


def test_stale_claimed_job_is_marked_by_every_supersession_and_stays_non_retryable(
    tmp_path: Path,
) -> None:
    """A stale-claimed row is marked by each supersession and keeps the first
    marker; provider failure text and status stay untouched; retry is refused.
    """
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    job = repository.create_or_get(_request(suffix="stale"))
    claimed = repository.claim_next("worker-stale")
    assert claimed is not None
    stale = repository.stale_claimed(
        claimed,
        owner="worker-stale",
        reason="input changed during provider call",
    )
    assert stale.status == MonitoringAiJobStatus.STALE_INPUT
    assert stale.failure_code == "stale_input_revision"

    repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        current_prompt_version="monitoring-field-mapping-v13",
        project_id=job.project_id,
    )
    state = repository.get(job.project_id, job.job_id)
    assert state.failure_code == "stale_input_revision"

    newer = repository.create_or_get(
        _request(suffix="stale").model_copy(
            update={"prompt_version": "monitoring-field-mapping-v2"}
        )
    )
    repository.supersede_business_key_except(
        job.project_id,
        business_key=job.business_key,
        current_job_id=newer.job_id,
        reason="job contract upgraded",
    )
    state = repository.get(job.project_id, job.job_id)
    assert state.failure_code == "stale_input_revision"

    repository.supersede_payload_workflows_except(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        business_key_prefix=job.business_key,
        current_workflow="monitoring_protocol_preparation_v9",
        project_id=job.project_id,
        reason="workflow contract upgraded",
    )
    state = repository.get(job.project_id, job.job_id)
    assert state.failure_code == "stale_input_revision"

    with pytest.raises(
        MonitoringAiStateConflictError,
        match="cannot be retried",
    ):
        repository.retry_terminal(
            job.project_id,
            job.job_id,
            current_input_revision_sha256=job.input_revision_sha256,
        )
    final = repository.get(job.project_id, job.job_id)
    assert final.status == MonitoringAiJobStatus.STALE_INPUT
    assert final.attempt_count == 1
    assert final.failure_code == "stale_input_revision"
    assert final.contract_retirement_code == "superseded_prompt_contract"
    assert final.contract_retirement_reason
    assert final.contract_retired_at is not None


def test_marker_only_retirement_preserves_updated_at_for_already_stale_row(
    tmp_path: Path,
) -> None:
    """A first retirement marker on an already-stale row is marker-only.

    The supersession must not rewrite updated_at when it only adds the
    immutable contract_retirement_* fields to a row that is already
    STALE_INPUT with its own failure text.
    """
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    job = repository.create_or_get(_request(suffix="stale"))
    claimed = repository.claim_next("worker-stale")
    assert claimed is not None
    stale = repository.stale_claimed(
        claimed,
        owner="worker-stale",
        reason="input changed during provider call",
    )
    assert stale.status == MonitoringAiJobStatus.STALE_INPUT
    before = repository.get(job.project_id, job.job_id)
    assert before.updated_at is not None
    assert before.contract_retirement_code == ""

    clock.advance(minutes=7)
    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        current_prompt_version="monitoring-field-mapping-v13",
        project_id=job.project_id,
    )
    assert changed == 0

    after = repository.get(job.project_id, job.job_id)
    assert after.status == MonitoringAiJobStatus.STALE_INPUT
    assert after.failure_code == "stale_input_revision"
    assert after.contract_retirement_code == "superseded_prompt_contract"
    assert after.contract_retirement_reason
    assert after.contract_retired_at is not None
    assert after.updated_at == before.updated_at


def test_marker_only_retirement_preserves_updated_at_for_legacy_terminal_rows(
    tmp_path: Path,
) -> None:
    """Preserved completed and failed legacy prompt rows keep audit timestamps.

    Prompt-retirement marking of preserved terminal rows must only write the
    immutable marker fields; status, failure text, candidates and updated_at
    stay untouched.
    """
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    legacy_versions = frozenset({"monitoring-field-mapping-v8"})

    completed_legacy = repository.create_or_get(
        _request(suffix="100").model_copy(
            update={"prompt_version": "monitoring-field-mapping-v8"}
        )
    )
    completed_legacy = repository.claim_next("worker-completed-legacy")
    assert completed_legacy is not None
    candidate = _candidate(completed_legacy, clock)
    repository.complete(
        completed_legacy,
        owner="worker-completed-legacy",
        response_model="test-model",
        raw_output={"candidates": [candidate.model_dump(mode="json")]},
        candidates=(candidate,),
    )

    failed_legacy = repository.create_or_get(
        _request(suffix="101").model_copy(
            update={"prompt_version": "monitoring-field-mapping-v8"}
        )
    )
    failed_legacy = repository.claim_next("worker-failed-legacy")
    assert failed_legacy is not None
    repository.fail(
        failed_legacy,
        owner="worker-failed-legacy",
        failure_code="provider_timeout",
        failure_message="provider timed out",
        retryable=False,
    )

    completed_before = repository.get(
        completed_legacy.project_id,
        completed_legacy.job_id,
    )
    failed_before = repository.get(
        failed_legacy.project_id,
        failed_legacy.job_id,
    )
    assert completed_before.updated_at is not None
    assert failed_before.updated_at is not None

    clock.advance(minutes=9)
    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        current_prompt_version="monitoring-field-mapping-v13",
        legacy_terminal_prompt_versions=legacy_versions,
    )
    assert changed == 0

    completed_after = repository.get(
        completed_legacy.project_id,
        completed_legacy.job_id,
    )
    failed_after = repository.get(
        failed_legacy.project_id,
        failed_legacy.job_id,
    )
    assert completed_after.status == MonitoringAiJobStatus.COMPLETED
    assert completed_after.contract_retirement_code == "superseded_prompt_contract"
    assert completed_after.contract_retirement_reason
    assert completed_after.contract_retired_at is not None
    assert completed_after.updated_at == completed_before.updated_at
    assert repository.candidates(
        completed_legacy.project_id,
        completed_legacy.job_id,
    )[0].status == MonitoringAiCandidateStatus.PROPOSED
    assert failed_after.status == MonitoringAiJobStatus.FAILED
    assert failed_after.failure_code == "provider_timeout"
    assert failed_after.contract_retirement_code == "superseded_prompt_contract"
    assert failed_after.contract_retirement_reason
    assert failed_after.contract_retired_at is not None
    assert failed_after.updated_at == failed_before.updated_at


def test_active_queued_and_running_retirement_advances_updated_at(
    tmp_path: Path,
) -> None:
    """Rows actually transitioned to stale_input still advance updated_at.

    The timestamp-preservation corrective applies only to marker-only rows;
    active queued/running retirement must keep recording the retirement time.
    """
    clock = MutableClock()
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        clock=clock,
    )
    running_job = repository.create_or_get(_request(suffix="running"))
    running_job = repository.claim_next("worker-running")
    assert running_job is not None
    assert running_job.status == MonitoringAiJobStatus.RUNNING
    queued_job = repository.create_or_get(_request(suffix="queued"))
    assert queued_job.status == MonitoringAiJobStatus.QUEUED

    running_before = repository.get(
        running_job.project_id,
        running_job.job_id,
    )
    queued_before = repository.get(
        queued_job.project_id,
        queued_job.job_id,
    )
    assert running_before.updated_at is not None
    assert queued_before.updated_at is not None

    clock.advance(minutes=5)
    retirement_time = clock()
    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        current_prompt_version="monitoring-field-mapping-v13",
    )
    assert changed == 2

    for job_id in (running_job.job_id, queued_job.job_id):
        after = repository.get(running_job.project_id, job_id)
        assert after.status == MonitoringAiJobStatus.STALE_INPUT
        assert after.failure_code == "superseded_prompt_contract"
        assert after.contract_retirement_code == "superseded_prompt_contract"
        assert after.updated_at == retirement_time
    assert after.updated_at > running_before.updated_at
    assert after.updated_at > queued_before.updated_at


@pytest.mark.parametrize(
    ("contract_field", "contract_value"),
    [
        ("prompt_version", "monitoring-field-mapping-v2"),
        ("profile_id", "independent-ai-next"),
        ("requested_model", "test-model-next"),
    ],
)
def test_business_key_supersession_preserves_input_only_stale_compatibility(
    tmp_path: Path,
    contract_field: str,
    contract_value: str,
) -> None:
    """Input-only staleness remains recoverable, but a stale row whose
    execution contract differs from the current job is durably retired.
    """
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    old = repository.create_or_get(_request(suffix="old"))
    repository.mark_stale(
        old.project_id,
        business_key=old.business_key,
        current_input_revision_sha256=_revision(suffix="new").revision_sha256,
    )
    current = repository.create_or_get(_request(suffix="new"))

    changed = repository.supersede_business_key_except(
        old.project_id,
        business_key=old.business_key,
        current_job_id=current.job_id,
        reason="input revision changed",
    )

    assert changed == 0
    input_only_stale = repository.get(old.project_id, old.job_id)
    assert input_only_stale.status == MonitoringAiJobStatus.STALE_INPUT
    assert input_only_stale.contract_retirement_code == ""
    retried = repository.retry_terminal(
        old.project_id,
        old.job_id,
        current_input_revision_sha256=old.input_revision_sha256,
    )
    assert retried.status == MonitoringAiJobStatus.QUEUED

    repository.mark_stale(
        old.project_id,
        business_key=old.business_key,
        current_input_revision_sha256=current.input_revision_sha256,
    )
    newer_contract = repository.create_or_get(
        _request(suffix="new").model_copy(
            update={contract_field: contract_value}
        )
    )
    repository.supersede_business_key_except(
        old.project_id,
        business_key=old.business_key,
        current_job_id=newer_contract.job_id,
        reason="execution contract changed",
    )
    retired = repository.get(old.project_id, old.job_id)
    assert retired.contract_retirement_code == "superseded_job_contract"
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="cannot be retried",
    ):
        repository.retry_terminal(
            old.project_id,
            old.job_id,
            current_input_revision_sha256=old.input_revision_sha256,
        )


@pytest.mark.parametrize(
    "legacy_code",
    [
        "superseded_job_contract",
        "superseded_prompt_contract",
        "superseded_workflow_contract",
    ],
)
def test_pre_marker_schema_backfills_legacy_contract_retirement(
    tmp_path: Path,
    legacy_code: str,
) -> None:
    """Opening a pre-marker database keeps historical supersession terminal."""
    database_path = tmp_path / f"{legacy_code}.sqlite3"
    repository = MonitoringAiRepository(database_path)
    clock = MutableClock()
    job = repository.create_or_get(
        _request(suffix=legacy_code, business_key=legacy_code)
    )
    claimed = repository.claim_next("legacy-worker")
    assert claimed is not None
    candidate = _candidate(claimed, clock)
    repository.complete(
        claimed,
        owner="legacy-worker",
        response_model=claimed.requested_model,
        raw_output={"candidates": [candidate.model_dump(mode="json")]},
        candidates=(candidate,),
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE monitoring_ai_jobs
            SET status = ?, failure_code = ?, failure_message = ?,
                retryable = 0
            WHERE job_id = ?
            """,
            (
                MonitoringAiJobStatus.STALE_INPUT.value,
                legacy_code,
                f"historical {legacy_code}",
                job.job_id,
            ),
        )
        connection.execute(
            """
            UPDATE monitoring_ai_candidates
            SET status = ?
            WHERE job_id = ?
            """,
            (MonitoringAiCandidateStatus.SUPERSEDED.value, job.job_id),
        )
        connection.execute(
            "ALTER TABLE monitoring_ai_jobs DROP COLUMN contract_retirement_code"
        )
        connection.execute(
            "ALTER TABLE monitoring_ai_jobs DROP COLUMN contract_retirement_reason"
        )
        connection.execute(
            "ALTER TABLE monitoring_ai_jobs DROP COLUMN contract_retired_at"
        )

    migrated = MonitoringAiRepository(database_path)
    state = migrated.get(job.project_id, job.job_id)
    assert state.status == MonitoringAiJobStatus.STALE_INPUT
    assert state.failure_code == legacy_code
    assert state.failure_message == f"historical {legacy_code}"
    assert state.attempt_count == 1
    assert state.contract_retirement_code == legacy_code
    assert state.contract_retirement_reason == f"historical {legacy_code}"
    assert state.contract_retired_at is not None
    migrated_candidates = migrated.candidates(job.project_id, job.job_id)
    assert len(migrated_candidates) == 1
    assert migrated_candidates[0].status == (
        MonitoringAiCandidateStatus.SUPERSEDED
    )
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="cannot be retried",
    ):
        migrated.retry_terminal(
            job.project_id,
            job.job_id,
            current_input_revision_sha256=job.input_revision_sha256,
        )
