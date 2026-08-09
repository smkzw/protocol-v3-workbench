from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

import pytest

from services.api.app.monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiClaim,
    MonitoringAiClaimKind,
    MonitoringAiEvidence,
    MonitoringAiTaskType,
)
from services.api.app.monitoring_ai_repository import MonitoringAiRepository
from services.api.app.monitoring_ai_service import (
    MonitoringAiRuntimeBinding,
    MonitoringAiService,
)
from services.api.app.monitoring_batch_repository import DiffReadyBatch, NormalizedRow
from services.api.app.monitoring_daily_run_ai_service import (
    MAX_EVIDENCE_PER_SUBJECT,
    MonitoringDailyRunAiService,
    MonitoringDailyRunAiServiceError,
)
from services.api.app.monitoring_daily_run_repository import (
    MonitoringDiffSnapshot,
    MonitoringRuleSnapshot,
)


PROJECT_ID = "project-monitoring-ai"
SOURCE_A = "a" * 64
SOURCE_B = "b" * 64
RULE_INPUT = "c" * 64
RULE_OUTPUT = "d" * 64
DIFF_INPUT = "e" * 64
DIFF_OUTPUT = "f" * 64


def _row(
    subject_id: str,
    domain: str,
    index: int,
    *,
    source_entry_id: str = "listing-a",
    source_hash: str = SOURCE_A,
    extra_fields: dict | None = None,
) -> NormalizedRow:
    data = {
        "SUBJID": subject_id,
        "DOMAIN": domain,
        "VISIT": f"V{index}",
        "RAW_VALUE": f"原始值-{subject_id}-{domain}-{index}",
        **(extra_fields or {}),
    }
    business_key = f"{domain}|{subject_id}|{index:04d}"
    return NormalizedRow(
        business_key=business_key,
        domain=domain,
        data=data,
        source_locator={
            "source_entry_id": source_entry_id,
            "source_content_sha256": source_hash,
            "locator": f"listing:sheet:{domain}:row:{index + 1}",
        },
        row_fingerprint=sha256(
            repr((business_key, data)).encode("utf-8")
        ).hexdigest(),
    )


def _batch(
    rows: tuple[NormalizedRow, ...],
    *,
    source_bindings=(("listing-a", SOURCE_A),),
) -> DiffReadyBatch:
    return DiffReadyBatch(
        batch_id="batch-ai-001",
        project_id=PROJECT_ID,
        state="frozen",
        version=9,
        expected_domains=tuple(sorted({row.domain for row in rows})),
        mapping_revision="mapping-009",
        source_bindings=source_bindings,
        source_hashes=tuple(sorted({item[1] for item in source_bindings})),
        rows=rows,
        schema_fields=tuple(
            sorted(
                {
                    (row.domain, field, row.domain)
                    for row in rows
                    for field in row.data
                }
            )
        ),
    )


def _rule_snapshot(
    batch: DiffReadyBatch,
    *,
    candidates: tuple[dict, ...] = (),
) -> MonitoringRuleSnapshot:
    return MonitoringRuleSnapshot(
        snapshot_id="rulesnap-ai-001",
        run_id="run-ai-001",
        project_id=PROJECT_ID,
        batch_id=batch.batch_id,
        rule_pack_id="rule-pack-009",
        engine_version="monitoring-engine-v1",
        input_sha256=RULE_INPUT,
        output_sha256=RULE_OUTPUT,
        payload={
            "project_id": PROJECT_ID,
            "batch_id": batch.batch_id,
            "mapping_revision": batch.mapping_revision,
            "rule_pack_id": "rule-pack-009",
            "candidates": list(candidates),
            "diagnostics": [],
        },
        created_at=datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
    )


def _diff_snapshot(
    batch: DiffReadyBatch,
    *,
    changed_keys: tuple[str, ...] = (),
    new_keys: tuple[str, ...] = (),
) -> MonitoringDiffSnapshot:
    return MonitoringDiffSnapshot(
        snapshot_id="diffsnap-ai-001",
        run_id="run-ai-001",
        project_id=PROJECT_ID,
        previous_batch_id="batch-ai-000",
        current_batch_id=batch.batch_id,
        algorithm_version="monitoring_batch_diff.v2",
        input_sha256=DIFF_INPUT,
        output_sha256=DIFF_OUTPUT,
        payload={
            "previous_batch_id": "batch-ai-000",
            "current_batch_id": batch.batch_id,
            "row_diff": {
                "new_keys": list(new_keys),
                "changed_keys": list(changed_keys),
                "persisting_keys": [],
                "removed_keys": [],
                "requires_rereview_keys": [],
                "missing_current_domains": [],
                "removal_resolution_blocked_keys": [],
            },
            "field_changes": [],
            "schema_diffs": [],
        },
        created_at=datetime(2026, 7, 29, 8, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def service(tmp_path):
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    runtime = MonitoringAiRuntimeBinding(
        profile_id="independent-ai-test",
        provider="product-ai-test",
        model="product-model-test",
        env={
            "WORKBENCH_AI_PROVIDER": "product-ai-test",
            "WORKBENCH_AI_MODEL": "product-model-test",
            "WORKBENCH_AI_TRANSPORT": "openai_compatible",
            "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": "product-model-test",
        },
    )
    ai_service = MonitoringAiService(
        repository,
        runtime_resolver=lambda: runtime,
    )
    return MonitoringDailyRunAiService(
        ai_service=ai_service,
        ai_repository=repository,
    )


def test_initial_baseline_submits_all_multi_domain_subjects_with_exact_sources(service):
    batch = _batch(
        (
            _row("S001", "AE", 1),
            _row("S001", "CM", 2),
            _row("S002", "LB", 3),
            _row("S003", "EX", 4),
            _row("S003", "VS", 5),
        )
    )

    submission = service.submit(
        project_id=PROJECT_ID,
        batch=batch,
        rule_snapshot=_rule_snapshot(batch),
    )

    assert submission.selected_subject_ids == ("S001", "S003")
    assert len(submission.jobs) == 2
    payload = service.ai_repository.input_payload(
        PROJECT_ID,
        submission.jobs[0].job_id,
    )
    assert payload["subject_context"]["batch_id"] == batch.batch_id
    assert payload["subject_context"]["mapping_revision"] == "mapping-009"
    assert payload["subject_context"]["rule_output_sha256"] == RULE_OUTPUT
    assert {
        (item["source_entry_id"], item["source_content_sha256"])
        for item in payload["evidence_packet"]
    } == {("listing-a", SOURCE_A)}
    assert submission.jobs[0].input_revision.batch_revision == "batch-ai-001:v9"
    assert submission.jobs[0].input_revision.rule_pack_revision.endswith(
        RULE_OUTPUT[:24]
    )


def test_incremental_scope_is_changed_or_rule_candidate_not_untouched(service):
    rows = (
        _row("S001", "AE", 1),
        _row("S001", "CM", 2),
        _row("S002", "AE", 3),
        _row("S002", "MH", 4),
        _row("S003", "AE", 5),
        _row("S003", "LB", 6),
    )
    batch = _batch(rows)
    rules = _rule_snapshot(
        batch,
        candidates=(
            {
                "candidate_id": "rule-candidate-s002",
                "subject_id": "S002",
                "current_business_key": rows[3].business_key,
            },
        ),
    )

    submission = service.submit(
        project_id=PROJECT_ID,
        batch=batch,
        rule_snapshot=rules,
        diff_snapshot=_diff_snapshot(
            batch,
            changed_keys=(rows[0].business_key,),
        ),
    )

    assert submission.selected_subject_ids == ("S001", "S002")
    payloads = [
        service.ai_repository.input_payload(PROJECT_ID, job.job_id)
        for job in submission.jobs
    ]
    reasons = {
        payload["subject_context"]["subject_id"]: payload["subject_context"][
            "selection_reasons"
        ]
        for payload in payloads
    }
    assert reasons == {
        "S001": ["incremental_diff"],
        "S002": ["deterministic_rule_candidate"],
    }


def test_original_values_are_primary_context_and_domain_boundary_is_explicit(service):
    batch = _batch(
        (
            _row("S001", "CM", 1, extra_fields={"CMTRT": "甲氨蝶呤"}),
            _row("S001", "EX", 2, extra_fields={"EXDOSE": "20 mg"}),
        )
    )
    submission = service.submit(
        project_id=PROJECT_ID,
        batch=batch,
        rule_snapshot=_rule_snapshot(batch),
    )
    payload = service.ai_repository.input_payload(
        PROJECT_ID,
        submission.jobs[0].job_id,
    )
    evidence = {
        item["raw_fields"]["domain"]: item for item in payload["evidence_packet"]
    }

    assert "CMTRT=甲氨蝶呤" in evidence["CM"]["quote"]
    assert "EXDOSE=20 mg" in evidence["EX"]["quote"]
    assert (
        evidence["CM"]["raw_fields"]["domain_role"]
        == "non_study_concomitant_medication_or_therapy"
    )
    assert (
        evidence["EX"]["raw_fields"]["domain_role"]
        == "study_treatment_exposure_or_adjustment"
    )
    assert payload["subject_context"]["domain_semantics"] == {
        "CM": "非试验用合并用药或治疗",
        "EX_EC_DA_IP": "试验药物给药、剂量调整、停药、重启或依从性",
    }


def test_context_is_subject_scoped_compact_and_capped_at_200(service):
    many_fields = {f"FIELD_{index:03d}": index for index in range(120)}
    rows = tuple(
        _row(
            "S001",
            "AE" if index % 2 == 0 else "LB",
            index,
            extra_fields=many_fields,
        )
        for index in range(230)
    ) + (
        _row("S999", "AE", 500),
        _row("S999", "CM", 501),
    )
    batch = _batch(rows)
    submission = service.submit(
        project_id=PROJECT_ID,
        batch=batch,
        rule_snapshot=_rule_snapshot(batch),
    )
    s001_job = next(
        job
        for job in submission.jobs
        if service.ai_repository.input_payload(
            PROJECT_ID,
            job.job_id,
        )["subject_context"]["subject_id"]
        == "S001"
    )
    packet = service.ai_repository.input_payload(
        PROJECT_ID,
        s001_job.job_id,
    )["evidence_packet"]

    assert len(packet) == MAX_EVIDENCE_PER_SUBJECT
    assert {item["raw_fields"]["subject_id"] for item in packet} == {"S001"}
    assert {item["raw_fields"]["domain"] for item in packet} == {"AE", "LB"}
    assert all(
        len(item["raw_fields"]["fields"]) <= 80
        and item["raw_fields"]["omitted_non_empty_field_count"] > 0
        for item in packet
    )


def test_repeat_submit_is_idempotent(service):
    batch = _batch((_row("S001", "AE", 1), _row("S001", "CM", 2)))
    snapshot = _rule_snapshot(batch)

    first = service.submit(
        project_id=PROJECT_ID,
        batch=batch,
        rule_snapshot=snapshot,
    )
    second = service.submit(
        project_id=PROJECT_ID,
        batch=batch,
        rule_snapshot=snapshot,
    )

    assert first.job_ids == second.job_ids
    assert len(
        service.ai_repository.list_jobs(
            PROJECT_ID,
            task_type=MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS.value,
        )
    ) == 1


def test_ambiguous_or_mismatched_raw_source_binding_is_rejected(service):
    batch = _batch(
        (
            _row("S001", "AE", 1, source_entry_id="", source_hash=""),
            _row("S001", "CM", 2, source_entry_id="", source_hash=""),
        ),
        source_bindings=(("listing-a", SOURCE_A), ("listing-b", SOURCE_B)),
    )
    with pytest.raises(MonitoringDailyRunAiServiceError) as raised:
        service.submit(
            project_id=PROJECT_ID,
            batch=batch,
            rule_snapshot=_rule_snapshot(batch),
        )
    assert raised.value.code == "monitoring_ai_source_binding_ambiguous"

    mismatched = _batch(
        (
            _row("S001", "AE", 1, source_hash=SOURCE_B),
            _row("S001", "CM", 2, source_hash=SOURCE_B),
        )
    )
    with pytest.raises(MonitoringDailyRunAiServiceError) as raised:
        service.submit(
            project_id=PROJECT_ID,
            batch=mismatched,
            rule_snapshot=_rule_snapshot(mismatched),
        )
    assert raised.value.code == "monitoring_ai_source_binding_mismatch"


@pytest.mark.parametrize(
    "source_hash",
    [
        f" {SOURCE_A}",
        f"{SOURCE_A} ",
        SOURCE_A.upper(),
        SOURCE_A[:-1],
        "g" * 64,
        123,
    ],
)
def test_noncanonical_present_raw_source_hash_is_rejected(service, source_hash):
    rows = (
        _row("S001", "AE", 1, source_hash=source_hash),
        _row("S001", "CM", 2, source_hash=source_hash),
    )
    batch = _batch(rows)

    with pytest.raises(MonitoringDailyRunAiServiceError) as raised:
        service.submit(
            project_id=PROJECT_ID,
            batch=batch,
            rule_snapshot=_rule_snapshot(batch),
        )

    assert raised.value.code == "monitoring_ai_source_binding_malformed"


def test_progress_reports_completed_failed_and_partial_without_promoting_risk(service):
    batch = _batch(
        (
            _row("S001", "AE", 1),
            _row("S001", "CM", 2),
            _row("S002", "AE", 3),
            _row("S002", "LB", 4),
        )
    )
    submission = service.submit(
        project_id=PROJECT_ID,
        batch=batch,
        rule_snapshot=_rule_snapshot(batch),
        max_attempts=1,
    )
    first = service.ai_repository.claim_next("worker-complete")
    assert first is not None
    service.ai_repository.complete(
        first,
        owner="worker-complete",
        response_model=first.requested_model,
        raw_output={"result": "candidate-only"},
        candidates=_completed_candidates(service, first),
    )
    second = service.ai_repository.claim_next("worker-fail")
    assert second is not None
    service.ai_repository.fail(
        second,
        owner="worker-fail",
        failure_code="provider_timeout",
        failure_message="独立 AI 调用超时",
        retryable=False,
    )

    progress = service.progress(project_id=PROJECT_ID, run_id="run-ai-001")

    assert progress.status == "partial_completed"
    assert (progress.total, progress.completed, progress.failed) == (2, 1, 1)
    assert len(progress.candidates) == 2
    assert all(
        item.candidate.status == MonitoringAiCandidateStatus.PROPOSED
        and item.candidate.task_type
        == MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS
        for item in progress.candidates
    )
    assert progress.failures[0]["failure_code"] == "provider_timeout"
    assert all(
        "risk" not in item.candidate.structured_payload
        and "query" not in item.candidate.structured_payload
        for item in progress.candidates
    )


def test_progress_reports_all_failed(service):
    batch = _batch((_row("S001", "AE", 1), _row("S001", "CM", 2)))
    submission = service.submit(
        project_id=PROJECT_ID,
        batch=batch,
        rule_snapshot=_rule_snapshot(batch),
        max_attempts=1,
    )
    claimed = service.ai_repository.claim_next("worker-fail")
    assert claimed is not None
    service.ai_repository.fail(
        claimed,
        owner="worker-fail",
        failure_code="provider_unavailable",
        failure_message="独立 AI 不可用",
        retryable=False,
    )

    progress = service.progress(
        project_id=PROJECT_ID,
        run_id=submission.run_id,
    )
    assert progress.status == "failed"
    assert progress.failed == 1
    assert progress.candidates == ()


def _completed_candidates(
    service: MonitoringDailyRunAiService,
    job,
) -> tuple[MonitoringAiCandidate, ...]:
    packet = service.ai_repository.input_payload(
        PROJECT_ID,
        job.job_id,
    )["evidence_packet"]
    evidence = tuple(
        MonitoringAiEvidence(
            **item,
            input_revision_sha256=job.input_revision_sha256,
        )
        for item in packet[:2]
    )
    evidence_ids = tuple(item.evidence_id for item in evidence)
    subject_id = service.ai_repository.input_payload(
        PROJECT_ID,
        job.job_id,
    )["subject_context"]["subject_id"]
    domains = tuple(item.raw_fields["domain"] for item in evidence)
    now = datetime(2026, 7, 29, 8, 30, tzinfo=timezone.utc)
    return tuple(
        MonitoringAiCandidate(
            candidate_id=f"{job.job_id}-candidate-{index}",
            job_id=job.job_id,
            project_id=PROJECT_ID,
            task_type=MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
            candidate_type="cross_table_clue",
            title=f"跨表复核候选 {index}",
            text="仅供当前医学用户复核，不构成确定性风险或Query。",
            structured_payload={
                "subject_id": subject_id,
                "domains": list(domains),
                "observations": ["原始数据在两个数据域中需要联合复核。"],
                "temporal_relationships": [],
                "data_gaps": [],
                "recommended_review": "核对原始记录与时间关系。",
                "evidence_ids": list(evidence_ids),
            },
            claims=(
                MonitoringAiClaim(
                    claim_id=f"claim-{index}",
                    kind=MonitoringAiClaimKind.RECOMMENDATION,
                    text="建议联合复核两个数据域的原始记录。",
                    confidence=0.8,
                    uncertainty="该候选尚未经过当前医学用户判断。",
                    user_action="核对原始值和时间关系。",
                    evidence_ids=evidence_ids,
                ),
            ),
            evidence=evidence,
            input_revision_sha256=job.input_revision_sha256,
            prompt_version=job.prompt_version,
            created_at=now,
        )
        for index in (1, 2)
    )
