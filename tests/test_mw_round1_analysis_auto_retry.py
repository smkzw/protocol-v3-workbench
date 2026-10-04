"""R26 self-check #2, P0-B counterexample (red-first, then fix).

Field evidence (proj_user_953921d37b47, 2026-10-02): the first-round corpus
analysis failed twice with the identical deterministic-looking error —

  "independent AI produced no evidence-bound corpus findings; rejected:
   cross-indication finding contains non-transferable clinical logic" (x3)

— and the pipeline parked at ``awaiting_corpus_analysis`` waiting for a HUMAN
to click 重试后续语料分析.  The third attempt succeeded, proving the failure
is model-output variance, not a configuration error: bounded automatic retry
is the correct recovery, exactly like every other long AI job in this product.

Root cause: ``ResearchPipelineDurableExecutor`` returns ``retryable=False``
for EVERY failure of a waiting-stage resume, so the durable store marks the
job failed immediately (``if retryable and attempts < max_attempts`` in
DurableJobStore) and never consumes the max_attempts=3 budget the resume job
is created with.  The user becomes the retry loop.

Fixed contract pinned here:
- a failure while the pipeline is at ``analyzing_round1`` (all download/OCR/
  translation work complete; only the analysis stage failed; the continuation
  is stage-idempotent) must be ``retryable=True`` so the store auto-retries
  within its bounded attempts — while STILL parking the visible stage
  truthfully at ``awaiting_corpus_analysis`` with the completed-work
  preservation guarantees unchanged;
- a failure while at ``translating`` (``awaiting_translation_scope`` gate)
  remains ``retryable=False`` — that gate genuinely requires user action.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from packages.contracts.workbench_contracts import DurableJobProgressPayload
from services.api.app.medical_writing_research_pipeline import (
    MedicalWritingResearchPipelineService,
    ResearchPipelineDurableExecutor,
    ResearchPipelineError,
    ResearchPipelineState,
)

PROJECT_ID = "proj_round1_auto_retry"
PIPELINE_ID = "mwpipe_round1_auto_retry"
FIELD_ERROR = (
    "independent AI produced no evidence-bound corpus findings; rejected: "
    "cross-indication finding contains non-transferable clinical logic"
)


def _executor_service(stage_at_failure: str):
    service = object.__new__(MedicalWritingResearchPipelineService)
    service._lock = threading.RLock()
    initial = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage=stage_at_failure,
        snapshot_id="wref_search_round1",
        prep_batch_id="prep_batch_round1",
        translation_batch_id="translation_batch_round1",
    )
    holder = {"state": initial}

    def get_state(_project_id):
        return holder["state"]

    def persist(_project_id, next_state):
        holder["state"] = next_state
        return next_state

    def continue_from_prepared_batch(_project_id, **_kwargs):
        raise ResearchPipelineError(FIELD_ERROR)

    service.get_state = get_state
    service._persist = persist
    service._continue_from_prepared_batch = continue_from_prepared_batch
    return service, holder


def _resume_job() -> SimpleNamespace:
    return SimpleNamespace(
        job_id="mwjob_round1_resume",
        project_id=PROJECT_ID,
        job_type="research_pipeline",
        business_key=f"research-pipeline:{PROJECT_ID}:{PIPELINE_ID}:resume-waiting:k1",
        request_hash="abcdef0123456789",
        status="running",
        progress=DurableJobProgressPayload(percent=0.85),
        payload_json=(
            '{"actor":"medical_manager","resume_from":"awaiting_corpus_analysis",'
            '"prep_batch_id":"prep_batch_round1","idempotency_key":"k1",'
            '"corpus_analysis_ai_route":{"provider":"alibaba","model":"qwen3.8-max-preview"}}'
        ),
        created_at="2026-10-02T14:10:00+00:00",
        updated_at="2026-10-02T14:30:00+00:00",
    )


def _execute(service):
    return ResearchPipelineDurableExecutor(service).execute(
        _resume_job(),
        "claim-round1",
        lambda: False,
        lambda _progress: True,
    )


def test_round1_analysis_failure_is_auto_retryable_and_parks_truthfully() -> None:
    service, holder = _executor_service("analyzing_round1")

    result = _execute(service)

    assert FIELD_ERROR[:60] in result.error
    # The recovery must be automatic within the durable job's bounded
    # attempts — the user must not be the retry loop (R26 P0-B).
    assert result.retryable is True
    # Truthful parking and completed-work preservation are unchanged.
    state = holder["state"]
    assert state.stage == "awaiting_corpus_analysis"
    assert state.translation_batch_id == "translation_batch_round1"
    assert state.last_resume_result_stage == "awaiting_corpus_analysis"
    assert "已完成的下载与结构提取仍保留" in state.detail


def test_translation_scope_failure_stays_user_gated_non_retryable() -> None:
    service, holder = _executor_service("translating")

    result = _execute(service)

    assert result.retryable is False
    assert holder["state"].stage == "awaiting_translation_scope"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
