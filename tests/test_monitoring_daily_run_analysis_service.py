from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.api.app.medical_risk_repository import MedicalRiskRepository
from services.api.app.monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiClaim,
    MonitoringAiClaimKind,
    MonitoringAiEvidence,
    MonitoringAiTaskType,
)
from services.api.app.monitoring_batch_repository import DiffReadyBatch, NormalizedRow
from services.api.app.monitoring_batch_rule_runner import (
    BatchRuleCandidate,
    BatchRuleDiagnostic,
)
from services.api.app.monitoring_daily_run_ai_service import (
    MonitoringDailyAiProgress,
    MonitoringDailyAiReviewCandidate,
    MonitoringDailyAiSubmission,
)
from services.api.app.monitoring_daily_run_analysis_service import (
    MonitoringDailyRunAnalysisService,
    MonitoringDailyRunAnalysisServiceError,
)
from services.api.app.monitoring_daily_run_repository import (
    DailyRunInput,
    MonitoringDailyRunRepository,
)


PROJECT_ID = "project-analysis"
BATCH_ID = "batch-analysis-001"
MAPPING_REVISION = "mapping-analysis-v1"
RULE_PACK = "rule-pack-analysis-v1"
ENGINE_VERSION = "monitoring-engine-v1"
SOURCE_HASH = "a" * 64
AI_INPUT_HASH = "b" * 64
NOW = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)


def _sha256(value) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class _RuntimeRow:
    raw_record: dict


def _batch(*, native_rows: bool = False) -> DiffReadyBatch:
    raw_rows = (
        {
            "SUBJID": "S001",
            "SITEID": "010",
            "DOMAIN": "CM",
            "CMTRT": "布洛芬",
            "CMSTDAT": "2026-07-20",
        },
        {
            "SUBJID": "S001",
            "SITEID": "010",
            "DOMAIN": "AE",
            "AETERM": "头痛",
            "AESTDAT": "2026-07-20",
        },
        {
            "SUBJID": "S002",
            "SITEID": "010",
            "DOMAIN": "EX",
            "EXTRT": "试验药物",
            "EXDOSE": "20 mg",
        },
    )
    if native_rows:
        rows = tuple(
            NormalizedRow(
                business_key=f"{row['DOMAIN']}|{row['SUBJID']}|{index}",
                domain=row["DOMAIN"],
                data=dict(row),
                source_locator={
                    "source_entry_id": "listing-source",
                    "source_content_sha256": SOURCE_HASH,
                    "locator": f"listing:{row['DOMAIN']}:row:{index}",
                },
                row_fingerprint=_sha256(row),
            )
            for index, row in enumerate(raw_rows, start=1)
        )
    else:
        rows = tuple(_RuntimeRow(dict(row)) for row in raw_rows)
    return DiffReadyBatch(
        batch_id=BATCH_ID,
        project_id=PROJECT_ID,
        state="frozen",
        version=7,
        expected_domains=("AE", "CM", "EX"),
        mapping_revision=MAPPING_REVISION,
        source_bindings=(("listing-source", SOURCE_HASH),),
        source_hashes=(SOURCE_HASH,),
        rows=rows,
        schema_fields=(
            ("AE", "AETERM", "AE"),
            ("CM", "CMTRT", "CM"),
            ("EX", "EXTRT", "EX"),
        ),
    )


def _rule_candidate(
    *,
    candidate_id: str = "rule-candidate-cm",
    domain: str = "CM",
    subject_id: str = "S001",
) -> BatchRuleCandidate:
    raw_data = {
        "SUBJID": subject_id,
        "SITEID": "010",
        "CMTRT" if domain == "CM" else "EXTRT": (
            "布洛芬" if domain == "CM" else "试验药物"
        ),
        "CMSTDAT" if domain == "CM" else "EXDOSE": (
            "2026-07-20" if domain == "CM" else "20 mg"
        ),
    }
    locator = {
        "source_entry_id": "listing-source",
        "source_content_sha256": SOURCE_HASH,
        "sheet": domain,
        "row": 12,
    }
    return BatchRuleCandidate(
        candidate_id=candidate_id,
        project_id=PROJECT_ID,
        batch_id=BATCH_ID,
        batch_version=7,
        mapping_revision=MAPPING_REVISION,
        rule_pack_id=RULE_PACK,
        rule_revision_id="rule-revision-001",
        rule_key=(
            "concomitant.prohibited_medication_review"
            if domain == "CM"
            else "study_treatment.dose_review"
        ),
        subject_id=subject_id,
        current_domain=domain,
        current_business_key=f"{domain}|{subject_id}|1",
        severity="high",
        confidence="deterministic",
        evidence_summary=(
            "2026-07-20 布洛芬 400 mg，需结合方案复核"
            if domain == "CM"
            else "2026-07-20 试验药物 20 mg，需结合方案复核"
        ),
        evaluation={
            "rule_key": "rule",
            "rule_revision_id": "rule-revision-001",
            "matched": True,
            "preconditions_met": True,
            "excluded": False,
            "missing_required_domains": [],
            "evidence": {
                "medical_review_candidate_only": True,
                "current_record": {
                    "raw_data": {
                        **raw_data,
                        "__source_locator__": [locator],
                        "__batch_row__": {"row_fingerprint": "row-fingerprint"},
                    },
                    "source_locators": [locator],
                },
                "previous_record": None,
                "related_records": {},
                "missing_record_queries": [],
            },
            "evidence_summary": "原始记录需复核",
            "protocol_source": {
                "source_entry_id": "protocol-source",
                "source_locator": "docx:paragraph:88",
                "source_text": "按方案规定复核相关用药。",
            },
        },
    )


def _rule_payload(
    *,
    candidates: tuple[BatchRuleCandidate, ...] = (),
    diagnostics: tuple[BatchRuleDiagnostic, ...] = (),
) -> dict:
    payload = {
        "run_id": "batch-rule-run-001",
        "project_id": PROJECT_ID,
        "batch_id": BATCH_ID,
        "batch_version": 7,
        "mapping_revision": MAPPING_REVISION,
        "rule_pack_id": RULE_PACK,
        "rule_revision_ids": ["rule-revision-001"],
        "evaluated_record_count": 3,
        "candidates": [item.to_dict() for item in candidates],
        "diagnostics": [item.to_dict() for item in diagnostics],
    }
    return {**payload, "output_sha256": _sha256(payload)}


def _ai_evidence(
    evidence_id: str,
    domain: str,
    *,
    fields: tuple[tuple[str, object], ...],
) -> MonitoringAiEvidence:
    return MonitoringAiEvidence(
        evidence_id=evidence_id,
        source_entry_id="listing-source",
        source_content_sha256=SOURCE_HASH,
        locator=f"listing:{domain}:row:{20 if domain == 'EX' else 21}",
        quote=f"{domain} 原始记录",
        raw_fields={
            "evidence_kind": "original_data",
            "fields": [
                {"field": "DOMAIN", "value": domain},
                {"field": "SUBJID", "value": "S002"},
                {"field": "SITEID", "value": "010"},
                *(
                    {"field": name, "value": value}
                    for name, value in fields
                ),
            ],
        },
        input_revision_sha256=AI_INPUT_HASH,
    )


def _ai_candidate() -> MonitoringAiCandidate:
    evidence = (
        _ai_evidence(
            "ev-ex",
            "EX",
            fields=(("EXTRT", "试验药物"), ("EXDOSE", "20 mg")),
        ),
        _ai_evidence(
            "ev-ae",
            "AE",
            fields=(("AETERM", "恶心"), ("AESTDAT", "2026-07-21")),
        ),
    )
    return MonitoringAiCandidate(
        candidate_id="ai-candidate-ex-ae",
        job_id="job-analysis-001",
        project_id=PROJECT_ID,
        task_type=MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
        candidate_type="cross_table_clue",
        title="试验药物给药与AE时间关系复核线索",
        text="给药记录与AE记录时间接近，需结合完整上下文复核。",
        structured_payload={
            "subject_id": "S002",
            "domains": ["EX", "AE"],
            "observations": ["试验药物给药后记录AE"],
            "temporal_relationships": ["时间接近不代表因果"],
            "data_gaps": ["缺少研究者因果性判断上下文"],
            "recommended_review": "核对EX、AE与访视记录。",
            "evidence_ids": ["ev-ex", "ev-ae"],
        },
        claims=(
            MonitoringAiClaim(
                claim_id="claim-fact",
                kind=MonitoringAiClaimKind.FACT,
                text="EX记录试验药物20 mg，AE记录恶心。",
                confidence=0.92,
                evidence_ids=("ev-ex", "ev-ae"),
            ),
            MonitoringAiClaim(
                claim_id="claim-inference",
                kind=MonitoringAiClaimKind.INFERENCE,
                text="两项记录的时间关系值得医学复核。",
                confidence=0.70,
                uncertainty="仅凭时间关系不能确认因果。",
                evidence_ids=("ev-ex", "ev-ae"),
            ),
            MonitoringAiClaim(
                claim_id="claim-action",
                kind=MonitoringAiClaimKind.RECOMMENDATION,
                text="建议核对试验药物给药和AE原始记录。",
                confidence=0.75,
                uncertainty="当前证据不足以形成确定性结论。",
                user_action="请医学经理复核相关记录。",
                evidence_ids=("ev-ex", "ev-ae"),
            ),
        ),
        evidence=evidence,
        status=MonitoringAiCandidateStatus.PROPOSED,
        input_revision_sha256=AI_INPUT_HASH,
        prompt_version="monitoring-cross-table-clue-synthesis-v3",
        created_at=NOW,
    )


def _progress(
    *,
    status: str = "completed",
    candidate: MonitoringAiCandidate | None = None,
    failures: tuple[dict[str, str], ...] = (),
) -> MonitoringDailyAiProgress:
    candidates = (
        (
            MonitoringDailyAiReviewCandidate(
                subject_id="S002",
                job_id=candidate.job_id,
                candidate=candidate,
            ),
        )
        if candidate is not None
        else ()
    )
    return MonitoringDailyAiProgress(
        project_id=PROJECT_ID,
        run_id="placeholder-run",
        status=status,
        total=len(candidates) + len(failures),
        queued=0,
        running=0,
        completed=len(candidates),
        failed=len(failures),
        candidates=candidates,
        failures=failures,
    )


class _FakeDailyAiService:
    def __init__(
        self,
        *,
        jobs: int = 1,
        progress: MonitoringDailyAiProgress | None = None,
    ) -> None:
        self.jobs = jobs
        self.progress_value = progress or _progress(status="completed")
        self.submit_calls: list[dict] = []
        self.progress_calls: list[tuple[str, str]] = []

    def submit(self, **kwargs) -> MonitoringDailyAiSubmission:
        self.submit_calls.append(kwargs)
        run_id = kwargs["rule_snapshot"].run_id
        jobs = tuple(
            SimpleNamespace(
                job_id=f"job-analysis-{index}",
                input_revision_sha256=AI_INPUT_HASH,
            )
            for index in range(1, self.jobs + 1)
        )
        return MonitoringDailyAiSubmission(
            project_id=kwargs["project_id"],
            run_id=run_id,
            batch_id=kwargs["batch"].batch_id,
            rule_snapshot_id=kwargs["rule_snapshot"].snapshot_id,
            selected_subject_ids=tuple(
                f"S{index:03d}" for index in range(1, self.jobs + 1)
            ),
            jobs=jobs,
        )

    def progress(self, *, project_id: str, run_id: str) -> MonitoringDailyAiProgress:
        self.progress_calls.append((project_id, run_id))
        return MonitoringDailyAiProgress(
            **{
                **self.progress_value.__dict__,
                "project_id": project_id,
                "run_id": run_id,
            }
        )


@dataclass
class _Harness:
    run_repository: MonitoringDailyRunRepository
    risk_repository: MedicalRiskRepository
    batch_repository: Mock
    ai_service: _FakeDailyAiService
    service: MonitoringDailyRunAnalysisService
    run: object
    wake: Mock


def _harness(
    tmp_path,
    *,
    rule_candidates: tuple[BatchRuleCandidate, ...] = (),
    diagnostics: tuple[BatchRuleDiagnostic, ...] = (),
    ai_jobs: int = 1,
    progress: MonitoringDailyAiProgress | None = None,
    native_rows: bool = False,
    baseline_batch_id: str | None = None,
) -> _Harness:
    run_repository = MonitoringDailyRunRepository(tmp_path / "runs.sqlite3")
    risk_repository = MedicalRiskRepository(tmp_path / "risks.sqlite3")
    batch = _batch(native_rows=native_rows)
    batch_repository = Mock()
    batch_repository.load_diff_ready_batch.return_value = batch
    ai_service = _FakeDailyAiService(jobs=ai_jobs, progress=progress)
    wake = Mock()
    service = MonitoringDailyRunAnalysisService(
        run_repository=run_repository,
        batch_repository=batch_repository,
        ai_service=ai_service,
        risk_repository=risk_repository,
        worker_wake=wake,
    )
    run = run_repository.create_or_get(
        DailyRunInput(
            project_id=PROJECT_ID,
            batch_id=BATCH_ID,
            baseline_batch_id=baseline_batch_id,
            batch_version=7,
            mapping_revision=MAPPING_REVISION,
            rule_pack_revision=RULE_PACK,
            engine_version=ENGINE_VERSION,
            diff_algorithm_version="monitoring-batch-diff-v2",
        ),
        idempotency_key="prepare-analysis",
        actor="medical-manager",
    ).run
    if baseline_batch_id is not None:
        run = run_repository.transition(
            PROJECT_ID,
            run.run_id,
            target_status="diffing",
            expected_version=run.version,
            actor="orchestrator",
        )
        run = run_repository.save_diff_snapshot(
            PROJECT_ID,
            run.run_id,
            input_sha256="d" * 64,
            payload={
                "previous_batch_id": baseline_batch_id,
                "current_batch_id": BATCH_ID,
                "row_diff": {
                    "new_keys": [],
                    "changed_keys": [],
                    "persisting_keys": [],
                    "removed_keys": [],
                    "requires_rereview_keys": [],
                    "missing_current_domains": [],
                    "removal_resolution_blocked_keys": [],
                },
                "schema_diffs": [],
                "removal_blocked_keys": [],
                "full_snapshot_proven": True,
            },
            expected_version=run.version,
            actor="orchestrator",
        ).run
    run = run_repository.transition(
        PROJECT_ID,
        run.run_id,
        target_status="rules_running",
        expected_version=run.version,
        actor="orchestrator",
    )
    run = run_repository.save_rule_snapshot(
        PROJECT_ID,
        run.run_id,
        input_sha256="c" * 64,
        payload=_rule_payload(
            candidates=rule_candidates,
            diagnostics=diagnostics,
        ),
        expected_version=run.version,
        actor="orchestrator",
    ).run
    run = run_repository.transition(
        PROJECT_ID,
        run.run_id,
        target_status="ai_running",
        expected_version=run.version,
        actor="orchestrator",
    )
    return _Harness(
        run_repository=run_repository,
        risk_repository=risk_repository,
        batch_repository=batch_repository,
        ai_service=ai_service,
        service=service,
        run=run,
        wake=wake,
    )


def _submit(harness: _Harness):
    result = harness.service.submit_ai(
        project_id=PROJECT_ID,
        run_id=harness.run.run_id,
        expected_version=harness.run.version,
        owner="analysis-worker",
    )
    harness.run = result.run
    return result


def _snapshot_count(repository: MedicalRiskRepository) -> int:
    with sqlite3.connect(repository.db_path) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM medical_risk_snapshots"
            ).fetchone()[0]
        )


def test_submit_ai_uses_frozen_run_rule_snapshot_wakes_worker_and_replays_idempotently(
    tmp_path,
) -> None:
    harness = _harness(tmp_path, ai_jobs=2)

    first = _submit(harness)
    second = _submit(harness)

    assert first.submission.job_ids == second.submission.job_ids
    assert first.next_action == "wait_for_independent_ai"
    assert len(harness.ai_service.submit_calls) == 2
    assert all(
        call["batch"].state == "frozen"
        and call["rule_snapshot"].run_id == harness.run.run_id
        for call in harness.ai_service.submit_calls
    )
    steps = {
        step.step_name: step
        for step in harness.run_repository.list_steps(harness.run.run_id)
    }
    assert steps["independent_ai_submission"].status == "completed"
    assert steps["independent_ai_submission"].attempt_count == 1
    assert harness.wake.call_count == 2


def test_submit_ai_zero_tasks_skips_worker_wake_and_can_assemble_immediately(
    tmp_path,
) -> None:
    harness = _harness(
        tmp_path,
        ai_jobs=0,
        progress=_progress(status="not_submitted"),
    )

    result = _submit(harness)

    assert result.submission.jobs == ()
    assert result.next_action == "assemble_risk_snapshot"
    harness.wake.assert_not_called()
    assembled = harness.service.assemble_risks(
        project_id=PROJECT_ID,
        run_id=harness.run.run_id,
        expected_version=harness.run.version,
        owner="analysis-worker",
    )
    assert assembled.resolution_complete is True
    assert assembled.run.status == "risk_review"
    assert assembled.snapshot.risk_count == 0


def test_submit_ai_requires_persisted_rule_snapshot_and_releases_lease(
    tmp_path,
    monkeypatch,
) -> None:
    harness = _harness(tmp_path)
    monkeypatch.setattr(
        harness.run_repository,
        "get_rule_snapshot",
        lambda project_id, run_id: None,
    )

    with pytest.raises(MonitoringDailyRunAnalysisServiceError) as raised:
        _submit(harness)

    assert raised.value.code == "monitoring_rule_snapshot_missing"
    assert harness.ai_service.submit_calls == []
    assert harness.run_repository.get(
        PROJECT_ID,
        harness.run.run_id,
    ).lease_owner is None


def test_submit_ai_incremental_requires_a_frozen_diff_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    harness = _harness(
        tmp_path,
        baseline_batch_id="batch-analysis-baseline",
    )
    monkeypatch.setattr(
        harness.run_repository,
        "get_diff_snapshot",
        lambda project_id, run_id: None,
    )

    with pytest.raises(MonitoringDailyRunAnalysisServiceError) as raised:
        _submit(harness)

    assert raised.value.code == "monitoring_diff_snapshot_missing"
    assert harness.ai_service.submit_calls == []
    assert harness.run_repository.get(
        PROJECT_ID,
        harness.run.run_id,
    ).lease_owner is None


@pytest.mark.parametrize("tampered_field", ["previous_batch_id", "algorithm_version"])
def test_submit_ai_incremental_rejects_diff_snapshot_lineage_tampering(
    tmp_path,
    monkeypatch,
    tampered_field,
) -> None:
    harness = _harness(
        tmp_path,
        baseline_batch_id="batch-analysis-baseline",
    )
    original_get = harness.run_repository.get_diff_snapshot
    replacement = (
        "batch-analysis-other"
        if tampered_field == "previous_batch_id"
        else "monitoring-batch-diff-other"
    )
    monkeypatch.setattr(
        harness.run_repository,
        "get_diff_snapshot",
        lambda project_id, run_id: replace(
            original_get(project_id, run_id),
            **{tampered_field: replacement},
        ),
    )

    with pytest.raises(MonitoringDailyRunAnalysisServiceError) as raised:
        _submit(harness)

    assert raised.value.code == "monitoring_diff_lineage_mismatch"
    assert harness.ai_service.submit_calls == []
    assert harness.run_repository.get(
        PROJECT_ID,
        harness.run.run_id,
    ).lease_owner is None


def test_submit_ai_incremental_accepts_exact_diff_lineage(tmp_path) -> None:
    harness = _harness(
        tmp_path,
        baseline_batch_id="batch-analysis-baseline",
    )

    result = _submit(harness)

    assert result.next_action == "wait_for_independent_ai"
    diff_snapshot = harness.run_repository.get_diff_snapshot(
        PROJECT_ID,
        harness.run.run_id,
    )
    assert diff_snapshot is not None
    assert diff_snapshot.previous_batch_id == "batch-analysis-baseline"
    assert harness.ai_service.submit_calls
    assert harness.ai_service.submit_calls[0]["diff_snapshot"] == diff_snapshot


@pytest.mark.parametrize(
    ("payload_update", "expected_code"),
    [
        ({"full_snapshot_proven": False}, "monitoring_diff_not_ready"),
        (
            {"removal_blocked_keys": ["ambiguous-old-row"]},
            "monitoring_diff_not_ready",
        ),
    ],
)
def test_submit_ai_incremental_rejects_unsafe_diff_payload(
    tmp_path,
    monkeypatch,
    payload_update,
    expected_code,
) -> None:
    harness = _harness(
        tmp_path,
        baseline_batch_id="batch-analysis-baseline",
    )
    original_get = harness.run_repository.get_diff_snapshot
    monkeypatch.setattr(
        harness.run_repository,
        "get_diff_snapshot",
        lambda project_id, run_id: replace(
            original_get(project_id, run_id),
            payload={
                **original_get(project_id, run_id).payload,
                **payload_update,
            },
        ),
    )

    with pytest.raises(MonitoringDailyRunAnalysisServiceError) as raised:
        _submit(harness)

    assert raised.value.code == expected_code
    assert harness.ai_service.submit_calls == []
    assert harness.run_repository.get(
        PROJECT_ID,
        harness.run.run_id,
    ).lease_owner is None


def test_submit_ai_rejects_changed_frozen_batch_identity_before_ai_submission(
    tmp_path,
) -> None:
    harness = _harness(tmp_path)
    changed = SimpleNamespace(
        **{
            **_batch().__dict__,
            "version": 8,
        }
    )
    harness.batch_repository.load_diff_ready_batch.return_value = changed

    with pytest.raises(MonitoringDailyRunAnalysisServiceError) as raised:
        _submit(harness)

    assert raised.value.code == "monitoring_run_input_changed"
    assert harness.ai_service.submit_calls == []
    assert harness.run_repository.get(
        PROJECT_ID,
        harness.run.run_id,
    ).lease_owner is None


def test_assemble_complete_binds_one_snapshot_and_preserves_raw_value_and_drug_boundaries(
    tmp_path,
) -> None:
    harness = _harness(
        tmp_path,
        rule_candidates=(_rule_candidate(domain="CM"),),
        progress=_progress(candidate=_ai_candidate()),
    )
    _submit(harness)

    result = harness.service.assemble_risks(
        project_id=PROJECT_ID,
        run_id=harness.run.run_id,
        expected_version=harness.run.version,
        owner="analysis-worker",
    )

    assert result.resolution_complete is True
    assert result.blockers == ()
    assert result.run.status == "risk_review"
    assert result.run.risk_snapshot_id == result.snapshot.snapshot_id
    assert _snapshot_count(harness.risk_repository) == 1
    risks = harness.risk_repository.list_risks(
        PROJECT_ID,
        result.snapshot.snapshot_id,
    )
    cm_risk = next(
        risk
        for risk in risks
        if risk.primary_category == "prohibited_concomitant_medication_pd"
    )
    ex_risk = next(
        risk for risk in risks if risk.primary_category == "other_medical_review"
    )
    assert "non_study_concomitant_medication" in cm_risk.tags
    assert "study_treatment_record" not in cm_risk.tags
    assert "study_treatment_record" in ex_risk.tags
    assert "non_study_concomitant_medication" not in ex_risk.tags
    assert cm_risk.rationale.startswith("原始数据触发摘要")
    assert ex_risk.rationale.startswith("原始数据：DOMAIN=EX")
    assert ex_risk.rationale.index("原始数据：") < ex_risk.rationale.index("事实：")


@pytest.mark.parametrize(
    ("diagnostics", "progress", "expected_code"),
    [
        (
            (
                BatchRuleDiagnostic(
                    diagnostic_id="diagnostic-001",
                    code="missing_required_domain",
                    message="缺少MH域，不能完成AE/MH复核。",
                    batch_id=BATCH_ID,
                    rule_pack_id=RULE_PACK,
                ),
            ),
            _progress(status="completed"),
            "deterministic_rule_diagnostic",
        ),
        (
            (),
            _progress(
                status="partial_completed",
                failures=(
                    {
                        "subject_id": "S002",
                        "status": "failed",
                        "failure_code": "provider_unavailable",
                        "failure_message": "独立AI调用失败",
                    },
                ),
            ),
            "provider_unavailable",
        ),
    ],
)
def test_assemble_rule_diagnostic_or_ai_failure_is_partial_not_complete(
    tmp_path,
    diagnostics,
    progress,
    expected_code,
) -> None:
    harness = _harness(
        tmp_path,
        rule_candidates=(_rule_candidate(),),
        diagnostics=diagnostics,
        progress=progress,
    )
    _submit(harness)

    result = harness.service.assemble_risks(
        project_id=PROJECT_ID,
        run_id=harness.run.run_id,
        expected_version=harness.run.version,
        owner="analysis-worker",
    )

    assert result.resolution_complete is False
    assert result.run.status == "analysis_partial"
    assert result.snapshot.resolution_complete is False
    assert expected_code in {item["code"] for item in result.blockers}
    assert result.next_action == "review_incomplete_analysis"


def test_assemble_crash_after_snapshot_save_reuses_single_snapshot_on_retry(
    tmp_path,
    monkeypatch,
) -> None:
    harness = _harness(
        tmp_path,
        rule_candidates=(_rule_candidate(),),
        progress=_progress(status="completed"),
    )
    _submit(harness)
    original_bind = harness.run_repository.bind_risk_snapshot
    calls = 0

    def crash_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated crash after risk snapshot persistence")
        return original_bind(*args, **kwargs)

    monkeypatch.setattr(
        harness.run_repository,
        "bind_risk_snapshot",
        crash_once,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        harness.service.assemble_risks(
            project_id=PROJECT_ID,
            run_id=harness.run.run_id,
            expected_version=harness.run.version,
            owner="analysis-worker",
        )
    assert _snapshot_count(harness.risk_repository) == 1
    crashed_run = harness.run_repository.get(PROJECT_ID, harness.run.run_id)
    assert crashed_run.status == "ai_running"
    assert crashed_run.risk_snapshot_id is None
    assert crashed_run.lease_owner is None

    recovered = harness.service.assemble_risks(
        project_id=PROJECT_ID,
        run_id=harness.run.run_id,
        expected_version=crashed_run.version,
        owner="analysis-worker",
    )

    assert recovered.run.status == "risk_review"
    assert recovered.run.risk_snapshot_id == recovered.snapshot.snapshot_id
    assert _snapshot_count(harness.risk_repository) == 1
    step = next(
        item
        for item in harness.run_repository.list_steps(harness.run.run_id)
        if item.step_name == "risk_snapshot_assembly"
    )
    assert step.status == "completed"
    assert step.attempt_count == 2


def test_repeated_assembly_after_success_does_not_create_another_snapshot(
    tmp_path,
) -> None:
    harness = _harness(
        tmp_path,
        rule_candidates=(_rule_candidate(),),
        progress=_progress(status="completed"),
    )
    _submit(harness)
    result = harness.service.assemble_risks(
        project_id=PROJECT_ID,
        run_id=harness.run.run_id,
        expected_version=harness.run.version,
        owner="analysis-worker",
    )

    with pytest.raises(MonitoringDailyRunAnalysisServiceError) as raised:
        harness.service.assemble_risks(
            project_id=PROJECT_ID,
            run_id=harness.run.run_id,
            expected_version=result.run.version,
            owner="analysis-worker",
        )

    assert raised.value.code == "monitoring_risk_assembly_not_ready"
    assert _snapshot_count(harness.risk_repository) == 1


def test_acknowledge_partial_moves_existing_snapshot_to_risk_review(tmp_path) -> None:
    harness = _harness(
        tmp_path,
        diagnostics=(
            BatchRuleDiagnostic(
                diagnostic_id="diagnostic-ack",
                code="source_incomplete",
                message="数据域不完整。",
                batch_id=BATCH_ID,
                rule_pack_id=RULE_PACK,
            ),
        ),
        ai_jobs=0,
        progress=_progress(status="not_submitted"),
    )
    _submit(harness)
    partial = harness.service.assemble_risks(
        project_id=PROJECT_ID,
        run_id=harness.run.run_id,
        expected_version=harness.run.version,
        owner="analysis-worker",
    )

    acknowledged = harness.service.acknowledge_partial(
        project_id=PROJECT_ID,
        run_id=harness.run.run_id,
        expected_version=partial.run.version,
        actor="medical-manager",
    )

    assert acknowledged.status == "risk_review"
    assert acknowledged.risk_snapshot_id == partial.snapshot.snapshot_id
    event = harness.run_repository.list_events(harness.run.run_id)[-1]
    assert event.payload["partial_analysis_acknowledged"] is True


def test_assemble_supports_the_repository_normalized_row_contract(tmp_path) -> None:
    """The analysis layer must consume DiffReadyBatch rows without private adapters."""
    harness = _harness(
        tmp_path,
        rule_candidates=(_rule_candidate(),),
        progress=_progress(status="completed"),
        native_rows=True,
    )
    _submit(harness)

    result = harness.service.assemble_risks(
        project_id=PROJECT_ID,
        run_id=harness.run.run_id,
        expected_version=harness.run.version,
        owner="analysis-worker",
    )

    assert result.snapshot.evaluated_subject_count == 2
