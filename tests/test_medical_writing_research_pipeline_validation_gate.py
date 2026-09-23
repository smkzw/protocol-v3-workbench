from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from services.api.app.medical_writing_research_pipeline import (
    MedicalWritingResearchPipelineService,
    ResearchPipelineDurableExecutor,
    ResearchPipelineConflictError,
    ResearchPipelineError,
    ResearchPipelineState,
)


PROJECT_ID = "proj_validation_gate"
PIPELINE_ID = "mwpipe_validation_gate"
SNAPSHOT_ID = "wref_search_validation_gate"
ARTIFACT_ID = "wref_artifact_validation_gate"
EXTRACTION_REVISION = "wref_extract_validation_gate_r1"
DOCUMENT_SHA256 = "a" * 64


def _check(outcome: str = "mismatch") -> SimpleNamespace:
    return SimpleNamespace(
        check_code="indication_match",
        label="适应症",
        expected_value="类风湿关节炎",
        observed_value="银屑病",
        outcome=outcome,
    )


def _validation(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        validation_id=f"validation_{status}",
        revision=1 if status != "user_overridden" else 2,
        status=status,
        document_sha256=DOCUMENT_SHA256,
        source_state_revision=1,
        extraction_revision=EXTRACTION_REVISION,
        checks=[_check()] if status in {"needs_review", "mismatch"} else [],
    )


def _item() -> SimpleNamespace:
    return SimpleNamespace(
        item_kind="public_document",
        artifact_id=ARTIFACT_ID,
        extraction_revision=EXTRACTION_REVISION,
        nct_id="NCT00000001",
        filename="NCT00000001_Protocol.pdf",
        document_type="protocol",
    )


class _Repository:
    def __init__(self, status: str) -> None:
        self.validation = _validation(status)
        self.reviews: list[SimpleNamespace] = []
        self.override_calls = 0
        self.structure_approval_calls = 0

    def document_validation(self, project_id: str, artifact_id: str):
        assert project_id == PROJECT_ID
        assert artifact_id == ARTIFACT_ID
        return self.validation

    def override_document_validation(self, **_kwargs):
        self.override_calls += 1
        raise AssertionError("research pipeline must never override content validation")

    def document_artifact(self, project_id: str, artifact_id: str):
        assert project_id == PROJECT_ID
        assert artifact_id == ARTIFACT_ID
        return SimpleNamespace(
            source_current=True,
            content_sha256=DOCUMENT_SHA256,
            state_revision=1,
        )

    def source_spans(
        self,
        project_id: str,
        artifact_id: str,
        extraction_revision: str,
    ):
        assert project_id == PROJECT_ID
        assert artifact_id == ARTIFACT_ID
        assert extraction_revision == EXTRACTION_REVISION
        return [
            SimpleNamespace(ich_m11_anchor="objectives_endpoints"),
            SimpleNamespace(ich_m11_anchor="eligibility"),
        ]

    def extraction_reviews(self, project_id: str, *, artifact_id: str):
        assert project_id == PROJECT_ID
        assert artifact_id == ARTIFACT_ID
        return list(self.reviews)

    def record_extraction_review(self, **kwargs):
        self.structure_approval_calls += 1
        review = SimpleNamespace(
            review_id="structure_review_1",
            extraction_revision=kwargs["extraction_revision"],
            decision=kwargs["decision"],
            unresolved_structure_issues=list(
                kwargs["unresolved_structure_issues"]
            ),
            revision=1,
        )
        self.reviews = [review]
        return review


class _PreparationService:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository
        self.batch = SimpleNamespace(
            batch_id="prep_batch_validation_gate",
            items=[_item()],
        )

    def get(self, project_id: str, prep_batch_id: str):
        assert project_id == PROJECT_ID
        assert prep_batch_id == self.batch.batch_id
        return self.batch


def _admission_service(status: str):
    repository = _Repository(status)
    service = object.__new__(MedicalWritingResearchPipelineService)
    service.preparation_batch_service = _PreparationService(repository)
    return service, repository


def test_preparation_stage_waiting_resume_drains_with_no_progress_guard() -> None:
    # Since b14a56a resume_waiting drains bounded preparation stages
    # continuously instead of pausing at every stage gate. The drain must
    # still stop on the no-progress guard when a stage stalls, preserving
    # completed work rather than spinning forever.
    service, _repository = _admission_service("confirmed")
    batch = service.preparation_batch_service.batch
    batch.deferred_item_count = 9
    batch.admission_stage_index = 1
    batch.admission_stage_size = 8
    batch.completed_document_count = 8
    calls = {"admit": 0, "run_pending": 0}

    def admit_next_stage(_project_id, _batch_id, _request):
        calls["admit"] += 1
        batch.admission_stage_index = 2
        # One item remains deferred after the first automatic stage and the
        # stubbed stage never drains further, so the guard must fire.
        batch.deferred_item_count = 1
        return batch

    def run_pending(_project_id, _batch_id, _actor, progress_callback=None):
        calls["run_pending"] += 1

    service.preparation_batch_service.admit_next_stage = admit_next_stage
    service.preparation_batch_service.run_pending = run_pending
    service.journey_service = SimpleNamespace(
        get=lambda _project_id: SimpleNamespace(
            search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID)
        )
    )
    service._lock = threading.RLock()
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_preparation_admission",
        snapshot_id=SNAPSHOT_ID,
        prep_batch_id=batch.batch_id,
    )
    holder = {"state": state}
    service.get_state = lambda _project_id: holder["state"]
    service._persist = lambda _project_id, next_state: holder.__setitem__(
        "state", next_state
    ) or next_state

    with pytest.raises(ResearchPipelineError) as excinfo:
        service.resume_waiting(
            PROJECT_ID,
            actor="medical_manager",
            idempotency_key="resume-preparation-stage-1",
            expected_pipeline_id=PIPELINE_ID,
            expected_stage="awaiting_preparation_admission",
        )

    assert "未产生进展" in str(excinfo.value)
    assert calls == {"admit": 2, "run_pending": 2}


def test_production_waiting_resume_enqueues_one_durable_continuation() -> None:
    service, _repository = _admission_service("confirmed")
    calls = {"create": 0, "wake": 0, "continuation": 0}
    requests = []

    class _DurableStore:
        def create_or_reuse(self, request):
            calls["create"] += 1
            requests.append(request)
            return SimpleNamespace(job_id="mwjob_resume_waiting_1")

    class _DurableWorker:
        def wake(self, project_id, job_id):
            assert project_id == PROJECT_ID
            assert job_id == "mwjob_resume_waiting_1"
            calls["wake"] += 1

    service.durable_store = _DurableStore()
    service.durable_worker = _DurableWorker()
    service._active_resume_projects = set()
    service.journey_service = SimpleNamespace(
        get=lambda _project_id: SimpleNamespace(
            search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID)
        )
    )
    service._lock = threading.RLock()
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_preparation_admission",
        snapshot_id=SNAPSHOT_ID,
        prep_batch_id="prep_batch_validation_gate",
        round1_ai_route={"profile_id": "independent_ai__deepseek_v4_flash"},
    )
    holder = {"state": state}
    service.get_state = lambda _project_id: holder["state"]
    service._persist = lambda _project_id, next_state: (
        holder.__setitem__("state", next_state) or next_state
    )

    def forbidden_sync_continuation(*_args, **_kwargs):
        calls["continuation"] += 1
        raise AssertionError("production resume must not run heavy work in HTTP")

    service._continue_from_prepared_batch = forbidden_sync_continuation

    resumed = service.resume_waiting(
        PROJECT_ID,
        actor="medical_manager",
        idempotency_key="resume-preparation-stage-durable-1",
        expected_pipeline_id=PIPELINE_ID,
        expected_stage="awaiting_preparation_admission",
    )

    assert resumed.stage == "preparing"
    assert resumed.job_id == "mwjob_resume_waiting_1"
    assert resumed.last_resume_started_from_stage == "awaiting_preparation_admission"
    assert resumed.last_resume_result_stage == "preparing"
    assert calls == {"create": 1, "wake": 1, "continuation": 0}
    assert len(requests) == 1
    payload = __import__("json").loads(requests[0].payload_json)
    assert payload["resume_from"] == "awaiting_preparation_admission"
    assert payload["prep_batch_id"] == "prep_batch_validation_gate"
    assert payload["idempotency_key"] == "resume-preparation-stage-durable-1"
    assert service._active_resume_projects == set()


def test_durable_waiting_resume_uses_existing_batch_not_execute_stages() -> None:
    calls = {"continue": 0, "execute_stages": 0, "persist": 0}
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="preparing",
        snapshot_id=SNAPSHOT_ID,
        prep_batch_id="prep_batch_validation_gate",
    )

    service = object.__new__(MedicalWritingResearchPipelineService)
    service.get_state = lambda _project_id: state

    def continue_from_batch(*_args, **kwargs):
        calls["continue"] += 1
        assert kwargs["prep_batch_id"] == "prep_batch_validation_gate"
        assert kwargs["resume_idempotency_key"] == "resume-worker-1"
        state.stage = "awaiting_preparation_admission"
        return state

    service._continue_from_prepared_batch = continue_from_batch
    service._persist = lambda _project_id, next_state: (
        calls.__setitem__("persist", calls["persist"] + 1) or next_state
    )
    service.execute_stages = lambda *_args, **_kwargs: calls.__setitem__(
        "execute_stages", calls["execute_stages"] + 1
    )

    job = SimpleNamespace(
        project_id=PROJECT_ID,
        payload_json=__import__("json").dumps(
            {
                "pipeline_id": PIPELINE_ID,
                "actor": "medical_manager",
                "resume_from": "awaiting_preparation_admission",
                "prep_batch_id": "prep_batch_validation_gate",
                "idempotency_key": "resume-worker-1",
            }
        ),
    )
    executor = ResearchPipelineDurableExecutor(service)
    result = executor.execute(job, "claim-token", lambda: False, lambda _p: True)

    assert result.error == ""
    assert calls == {"continue": 1, "execute_stages": 0, "persist": 1}
    assert state.last_resume_started_from_stage == "awaiting_preparation_admission"
    assert state.last_resume_result_stage == "awaiting_preparation_admission"


def test_status_reconciles_terminal_preparation_left_in_preparing() -> None:
    service, _repository = _admission_service("confirmed")
    service.preparation_batch_service.batch.status = "partial_failure"
    service.preparation_batch_service.batch.failed_count = 2
    service.durable_store = None
    holder = {}
    service._persist = lambda _project_id, state: holder.setdefault("state", state)
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="preparing",
        prep_batch_id="prep_batch_validation_gate",
        detail="正在复核既有原文、解析、OCR与准入状态后继续翻译。",
    )

    reconciled = service._reconcile_stale_preparation_state(PROJECT_ID, state)

    assert reconciled.stage == "failed"
    assert reconciled.error_summary == "stale_preparation_state:partial_failure"
    assert "不会重复下载或OCR" in reconciled.detail
    assert holder["state"] is reconciled


def test_status_does_not_clobber_an_active_resume_during_partial_failure() -> None:
    service, _repository = _admission_service("confirmed")
    service._active_resume_projects = {PROJECT_ID}
    service.preparation_batch_service.batch.status = "partial_failure"
    service.preparation_batch_service.batch.failed_count = 1
    service.preparation_batch_service.batch.prepared_count = 2
    service.preparation_batch_service.batch.completed_document_count = 3
    service.preparation_batch_service.batch.deferred_item_count = 4
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="preparing",
        prep_batch_id="prep_batch_validation_gate",
    )

    reconciled = service._reconcile_stale_preparation_state(PROJECT_ID, state)

    assert reconciled is state
    assert reconciled.stage == "preparing"


def test_status_reconciles_partial_failure_to_next_stage_wait_without_restart() -> None:
    service, _repository = _admission_service("confirmed")
    batch = service.preparation_batch_service.batch
    batch.status = "partial_failure"
    batch.failed_count = 1
    batch.prepared_count = 2
    batch.completed_document_count = 3
    batch.deferred_item_count = 4
    holder = {}
    service._persist = lambda _project_id, state: holder.setdefault("state", state)
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="preparing",
        prep_batch_id=batch.batch_id,
    )

    reconciled = service._reconcile_stale_preparation_state(PROJECT_ID, state)

    assert reconciled.stage == "awaiting_preparation_admission"
    assert reconciled.error_summary == (
        "preparation_partial_failure_stage_admission_required"
    )
    assert "已保留 2 份可用原文" in reconciled.detail
    assert "失败 1 份" in reconciled.detail
    assert "4 份公开Protocol" in reconciled.detail
    assert holder["state"] is reconciled


def test_status_reconciles_awaiting_stage_admission_after_completed_worker() -> None:
    service, _repository = _admission_service("confirmed")
    batch = service.preparation_batch_service.batch
    batch.status = "awaiting_stage_admission"
    batch.failed_count = 0
    batch.prepared_count = 14
    batch.completed_document_count = 16
    batch.deferred_item_count = 51
    holder = {}
    service._persist = lambda _project_id, state: holder.setdefault("state", state)
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="preparing",
        prep_batch_id=batch.batch_id,
        job_id="mwjob_completed_resume",
    )

    reconciled = service._reconcile_stale_preparation_state(PROJECT_ID, state)

    assert reconciled.stage == "awaiting_preparation_admission"
    assert reconciled.error_summary == "preparation_stage_admission_required"
    assert "51 份公开Protocol待下一阶段准入" in reconciled.detail
    assert holder["state"] is reconciled


def test_status_reconciles_partial_failure_without_deferred_to_translation_wait() -> None:
    service, _repository = _admission_service("confirmed")
    batch = service.preparation_batch_service.batch
    batch.status = "partial_failure"
    batch.failed_count = 1
    batch.prepared_count = 2
    batch.completed_document_count = 3
    batch.deferred_item_count = 0
    holder = {}
    service._persist = lambda _project_id, state: holder.setdefault("state", state)
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="preparing",
        prep_batch_id=batch.batch_id,
    )

    reconciled = service._reconcile_stale_preparation_state(PROJECT_ID, state)

    assert reconciled.stage == "awaiting_translation_scope"
    assert reconciled.error_summary == "preparation_partial_failure_review_required"
    assert "已保留 2 份可用原文" in reconciled.detail
    assert holder["state"] is reconciled


def _admit(service: MedicalWritingResearchPipelineService):
    return service._admit_prepared_public_documents(
        PROJECT_ID,
        actor="medical_manager",
        pipeline_id=PIPELINE_ID,
        prep_batch_id="prep_batch_validation_gate",
    )


def test_confirmed_document_passes_without_content_override() -> None:
    service, repository = _admission_service("confirmed")

    result = _admit(service)

    assert result.admitted_count == 1
    assert result.blocked_documents == ()
    assert repository.override_calls == 0
    assert repository.structure_approval_calls == 1


def test_mismatch_document_is_blocked_and_original_checks_are_preserved() -> None:
    service, repository = _admission_service("mismatch")

    result = _admit(service)

    assert result.admitted_count == 0
    assert len(result.blocked_documents) == 1
    blocker = result.blocked_documents[0]
    assert blocker["validation_status"] == "mismatch"
    assert blocker["reason_code"] == "document_validation_not_confirmed"
    assert blocker["checks"] == [
        {
            "check_code": "indication_match",
            "label": "适应症",
            "expected_value": "类风湿关节炎",
            "observed_value": "银屑病",
            "outcome": "mismatch",
        }
    ]
    assert repository.override_calls == 0
    assert repository.structure_approval_calls == 0


def test_user_overridden_document_passes_without_second_override() -> None:
    service, repository = _admission_service("user_overridden")

    result = _admit(service)

    assert result.admitted_count == 1
    assert result.blocked_documents == ()
    assert repository.override_calls == 0
    assert repository.structure_approval_calls == 1


def test_unresolved_structure_review_is_excluded_not_content_overridden() -> None:
    service, repository = _admission_service("confirmed")
    repository.reviews = [
        SimpleNamespace(
            review_id="structure_review_returned",
            extraction_revision=EXTRACTION_REVISION,
            decision="returned",
            unresolved_structure_issues=["研究流程表页码映射待复核"],
            revision=1,
        )
    ]

    result = _admit(service)

    assert result.admitted_count == 0
    assert result.blocked_documents == ()
    assert result.excluded_documents[0]["reason_code"] == "structure_review_required"
    assert repository.structure_approval_calls == 0
    assert repository.override_calls == 0


def test_one_unusable_public_document_is_excluded_when_clean_evidence_remains() -> None:
    service, repository = _admission_service("confirmed")
    unusable_artifact_id = "wref_artifact_without_m11_anchor"
    service.preparation_batch_service.batch.items.append(
        SimpleNamespace(
            item_kind="public_document",
            artifact_id=unusable_artifact_id,
            extraction_revision=EXTRACTION_REVISION,
            nct_id="NCT00000002",
            filename="NCT00000002_Protocol.pdf",
            document_type="protocol",
        )
    )
    repository.document_validation = lambda _project_id, _artifact_id: _validation(
        "confirmed"
    )
    repository.document_artifact = lambda _project_id, _artifact_id: SimpleNamespace(
        source_current=True,
        content_sha256=DOCUMENT_SHA256,
        state_revision=1,
    )
    repository.source_spans = (
        lambda _project_id, artifact_id, extraction_revision: (
            [SimpleNamespace(ich_m11_anchor="unmapped")]
            if artifact_id == unusable_artifact_id
            else [SimpleNamespace(ich_m11_anchor="objectives_endpoints")]
        )
    )
    repository.extraction_reviews = lambda _project_id, *, artifact_id: []

    result = _admit(service)

    assert result.admitted_count == 1
    assert result.blocked_documents == ()
    assert len(result.excluded_documents) == 1
    assert result.excluded_documents[0]["artifact_id"] == unusable_artifact_id
    assert result.excluded_documents[0]["reason_code"] == "structure_anchor_missing"
    assert repository.structure_approval_calls == 1
    assert repository.override_calls == 0


def test_content_mismatch_is_traceable_exclusion_when_clean_evidence_remains() -> None:
    service, repository = _admission_service("mismatch")
    clean_artifact_id = "wref_artifact_clean"
    service.preparation_batch_service.batch.items.append(
        SimpleNamespace(
            item_kind="public_document",
            artifact_id=clean_artifact_id,
            extraction_revision=EXTRACTION_REVISION,
            nct_id="NCT00000002",
            filename="NCT00000002_Protocol.pdf",
            document_type="protocol",
        )
    )
    repository.document_validation = (
        lambda _project_id, artifact_id: (
            _validation("confirmed")
            if artifact_id == clean_artifact_id
            else _validation("mismatch")
        )
    )
    repository.document_artifact = lambda _project_id, _artifact_id: SimpleNamespace(
        source_current=True,
        content_sha256=DOCUMENT_SHA256,
        state_revision=1,
    )
    repository.source_spans = (
        lambda _project_id, _artifact_id, *, extraction_revision: [
            SimpleNamespace(ich_m11_anchor="objectives_endpoints")
        ]
    )
    repository.extraction_reviews = lambda _project_id, *, artifact_id: []

    result = _admit(service)

    assert result.admitted_count == 1
    assert result.blocked_documents == ()
    assert len(result.excluded_documents) == 1
    exclusion = result.excluded_documents[0]
    assert exclusion["artifact_id"] == ARTIFACT_ID
    assert exclusion["reason_code"] == "document_validation_not_confirmed"
    assert exclusion["checks"] == [
        {
            "check_code": "indication_match",
            "label": "适应症",
            "expected_value": "类风湿关节炎",
            "observed_value": "银屑病",
            "outcome": "mismatch",
        }
    ]


def test_pipeline_waits_for_user_override_then_resumes_without_reextracting() -> None:
    service, repository = _admission_service("mismatch")
    journey = SimpleNamespace(
        search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID),
        corpus_gate=SimpleNamespace(readiness_status="ready", override=None),
    )
    service.journey_service = SimpleNamespace(get=lambda _project_id: journey)
    service.corpus_readiness_service = SimpleNamespace(
        recalculate=lambda _project_id, actor: None
    )
    calls = {"confirm": 0, "reuse": 0, "translation": 0}

    def confirm(*_args):
        calls["confirm"] += 1
        return ["NCT00000001"]

    def reuse(*_args, **_kwargs):
        calls["reuse"] += 1
        return service.preparation_batch_service.batch

    holder = {}
    service._confirm_triage_basket = confirm
    service._find_reusable_preparation_batch = reuse

    def persist(_project_id, state):
        holder["state"] = state
        return state

    service._persist = persist
    service.get_state = lambda _project_id: holder["state"]
    service._lock = threading.RLock()

    def start_translation(*_args):
        calls["translation"] += 1
        return {"batch_id": "translation_batch_1"}

    service._start_translation_batch = (
        start_translation
    )
    service._wait_translation = lambda _project_id, _state, _pulse: None

    def run_round1(_project_id, _actor, state):
        state.round1_analysis_id = "analysis_1"
        state.round1_analysis_output_hash = "b" * 64
        return ["brief_1"]

    service._run_round1_analysis = run_round1
    service._notify_corpus_ready = lambda _project_id: None

    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_triage_confirm",
        snapshot_id=SNAPSHOT_ID,
    )
    blocked = service.continue_after_triage(
        PROJECT_ID,
        actor="medical_manager",
        retained_candidate_ids=["NCT00000001"],
        state=state,
    )

    assert blocked.stage == "awaiting_document_validation"
    assert blocked.error_summary == "document_admission_review_required"
    assert len(blocked.document_admission_blockers) == 1
    assert blocked.translation_batch_id == ""
    assert repository.override_calls == 0

    repository.validation = _validation("user_overridden")
    resumed = service.resume_waiting(
        PROJECT_ID,
        actor="medical_manager",
        idempotency_key="resume-validation-1",
        expected_pipeline_id=PIPELINE_ID,
        expected_stage="awaiting_document_validation",
    )
    replayed = service.resume_waiting(
        PROJECT_ID,
        actor="medical_manager",
        idempotency_key="resume-validation-1",
        expected_pipeline_id=PIPELINE_ID,
        expected_stage="awaiting_document_validation",
    )

    assert resumed.stage == "corpus_ready"
    assert replayed.stage == "corpus_ready"
    assert resumed.error_summary == ""
    assert resumed.document_admission_blockers == []
    assert resumed.translation_batch_id == "translation_batch_1"
    assert resumed.prep_batch_id == "prep_batch_validation_gate"
    assert calls == {"confirm": 1, "reuse": 1, "translation": 1}
    assert repository.structure_approval_calls == 1
    assert repository.override_calls == 0


def test_translation_scope_error_waits_and_does_not_run_round1() -> None:
    service, _repository = _admission_service("confirmed")
    journey = SimpleNamespace(
        search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID),
        corpus_gate=SimpleNamespace(readiness_status="not_ready", override=None),
    )
    service.journey_service = SimpleNamespace(get=lambda _project_id: journey)
    service._confirm_triage_basket = (
        lambda _project_id, _actor, _state, _retained: ["NCT00000001"]
    )
    service._find_reusable_preparation_batch = (
        lambda _project_id, snapshot_id, retained_ids: service.preparation_batch_service.batch
    )
    service._persist = lambda _project_id, state: state

    def translation_not_ready(*_args):
        raise ValueError("no eligible confirmed source spans")

    service._start_translation_batch = translation_not_ready
    service._run_round1_analysis = lambda *_args: (_ for _ in ()).throw(
        AssertionError("round-1 must not run without a valid translation scope")
    )

    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_triage_confirm",
        snapshot_id=SNAPSHOT_ID,
    )
    result = service.continue_after_triage(
        PROJECT_ID,
        actor="medical_manager",
        retained_candidate_ids=["NCT00000001"],
        state=state,
    )

    assert result.stage == "awaiting_translation_scope"
    assert result.error_summary.startswith("translation_scope_not_ready:")
    assert result.round1_brief_ids == []
    assert result.round1_analysis_id == ""


def test_confirmed_empty_basket_is_actionable_waiting_state() -> None:
    """No public Protocol is a user-review path, not a terminal pipeline failure."""
    service = object.__new__(MedicalWritingResearchPipelineService)
    service.journey_service = SimpleNamespace(
        get=lambda _project_id: SimpleNamespace(
            search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID)
        )
    )
    service._confirm_triage_basket = (
        lambda _project_id, _actor, _state, _retained: []
    )
    holder = {}

    def persist(_project_id, state):
        holder["state"] = state
        return state

    service._persist = persist
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_triage_confirm",
        snapshot_id=SNAPSHOT_ID,
    )

    result = service.continue_after_triage(
        PROJECT_ID,
        actor="medical_manager",
        retained_candidate_ids=[],
        state=state,
    )

    assert result.stage == "awaiting_corpus_admission"
    assert result.error_summary == "no_retainable_candidates"
    assert result.round1_material_ready is False
    assert result.child_context == {
        "fallback_mode": "shared_corpus_or_manual_upload",
        "confirmed_empty_basket": True,
        "downstream_heavy_stages_started": False,
    }
    assert "未启动下载、OCR或翻译" in result.detail
    assert holder["state"] is result


def test_empty_basket_fallback_is_idempotent_and_does_not_create_heavy_stage() -> None:
    service = object.__new__(MedicalWritingResearchPipelineService)
    service._persist = lambda _project_id, state: state
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_triage_confirm",
        snapshot_id=SNAPSHOT_ID,
    )

    first = service._persist_no_retainable_candidate_fallback(
        PROJECT_ID, state, error="no_retainable_candidates_after_confirm"
    )
    second = service._persist_no_retainable_candidate_fallback(
        PROJECT_ID, first, error="no_retainable_candidates_after_confirm"
    )

    assert first.stage == second.stage == "awaiting_corpus_admission"
    assert first.error_summary == second.error_summary
    assert second.child_context["downstream_heavy_stages_started"] is False
    assert second.child_phase == "corpus_admission"
    assert second.child_completed == 0
    assert second.child_total == 0
    assert second.child_label == "等待医学经理选择语料来源"
    assert second.prep_batch_id == ""
    assert second.translation_batch_id == ""


def test_zero_result_public_search_uses_actionable_corpus_fallback() -> None:
    """A valid empty public search must not strand the writing journey."""
    service = object.__new__(MedicalWritingResearchPipelineService)
    service._persist = lambda _project_id, state: state
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="searching",
        snapshot_id=SNAPSHOT_ID,
    )

    result = service._persist_no_retainable_candidate_fallback(
        PROJECT_ID, state, error="no_public_protocol_results"
    )

    assert result.stage == "awaiting_corpus_admission"
    assert result.error_summary == "no_public_protocol_results"
    assert result.round1_material_ready is False
    assert result.prep_batch_id == ""
    assert result.translation_batch_id == ""
    assert result.child_context["confirmed_empty_basket"] is True
    assert result.child_phase == "corpus_admission"
    assert result.child_total == 0
    assert result.child_label == "等待医学经理选择语料来源"


def test_translation_scope_resume_reuses_prepared_batch() -> None:
    service, repository = _admission_service("confirmed")
    journey = SimpleNamespace(
        search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID),
        corpus_gate=SimpleNamespace(readiness_status="ready", override=None),
    )
    service.journey_service = SimpleNamespace(get=lambda _project_id: journey)
    service.corpus_readiness_service = SimpleNamespace(
        recalculate=lambda _project_id, actor: None
    )
    service._lock = threading.RLock()
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_translation_scope",
        snapshot_id=SNAPSHOT_ID,
        prep_batch_id="prep_batch_validation_gate",
    )
    holder = {"state": state}

    def persist(_project_id, next_state):
        holder["state"] = next_state
        return next_state

    service.get_state = lambda _project_id: holder["state"]
    service._persist = persist
    service._start_translation_batch = lambda *_args: {
        "batch_id": "translation_batch_recovered"
    }
    service._wait_translation = lambda *_args: None

    def run_round1(_project_id, _actor, current):
        current.round1_analysis_id = "analysis_recovered"
        current.round1_analysis_output_hash = "c" * 64
        return ["brief_recovered"]

    service._run_round1_analysis = run_round1
    service._notify_corpus_ready = lambda _project_id: None

    resumed = service.resume_waiting(
        PROJECT_ID,
        actor="medical_manager",
        idempotency_key="resume-translation-1",
        expected_pipeline_id=PIPELINE_ID,
        expected_stage="awaiting_translation_scope",
    )

    assert resumed.stage == "corpus_ready"
    assert resumed.prep_batch_id == "prep_batch_validation_gate"
    assert resumed.translation_batch_id == "translation_batch_recovered"
    assert repository.override_calls == 0
    assert repository.structure_approval_calls == 1


def test_resume_translation_failure_keeps_truthful_retryable_stage() -> None:
    service, repository = _admission_service("user_overridden")
    journey = SimpleNamespace(
        search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID),
        corpus_gate=SimpleNamespace(readiness_status="not_ready", override=None),
    )
    service.journey_service = SimpleNamespace(get=lambda _project_id: journey)
    service._lock = threading.RLock()
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_document_validation",
        snapshot_id=SNAPSHOT_ID,
        prep_batch_id="prep_batch_validation_gate",
    )
    holder = {"state": state}

    def persist(_project_id, next_state):
        holder["state"] = next_state
        return next_state

    service.get_state = lambda _project_id: holder["state"]
    service._persist = persist
    service._start_translation_batch = lambda *_args: {
        "batch_id": "translation_batch_failed"
    }
    service._wait_translation = lambda *_args: (_ for _ in ()).throw(
        ResearchPipelineError(
            "翻译未形成可用关键锚点译文（status=failed，critical_ready=0/4）"
        )
    )

    with pytest.raises(ResearchPipelineError, match="critical_ready=0/4"):
        service.resume_waiting(
            PROJECT_ID,
            actor="medical_manager",
            idempotency_key="resume-translation-failed",
            expected_pipeline_id=PIPELINE_ID,
            expected_stage="awaiting_document_validation",
        )

    failed = holder["state"]
    assert failed.stage == "awaiting_translation_scope"
    assert failed.translation_batch_id == "translation_batch_failed"
    assert failed.last_resume_idempotency_key == ""
    assert failed.last_resume_started_from_stage == "awaiting_document_validation"
    assert failed.last_resume_result_stage == "awaiting_translation_scope"
    assert failed.last_resume_at
    assert failed.error_summary.startswith("resume_failed:ResearchPipelineError:")
    assert repository.override_calls == 0


def test_resume_unexpected_failure_does_not_leave_preparing_stage_stale() -> None:
    service, repository = _admission_service("user_overridden")
    journey = SimpleNamespace(
        search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID),
        corpus_gate=SimpleNamespace(readiness_status="not_ready", override=None),
    )
    service.journey_service = SimpleNamespace(get=lambda _project_id: journey)
    service._lock = threading.RLock()
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_document_validation",
        snapshot_id=SNAPSHOT_ID,
        prep_batch_id="prep_batch_validation_gate",
    )
    holder = {"state": state}

    def persist(_project_id, next_state):
        holder["state"] = next_state
        return next_state

    service.get_state = lambda _project_id: holder["state"]
    service._persist = persist
    service._continue_from_prepared_batch = lambda *_args, **_kwargs: (
        (_ for _ in ()).throw(RuntimeError("unexpected provider response"))
    )

    with pytest.raises(RuntimeError, match="unexpected provider response"):
        service.resume_waiting(
            PROJECT_ID,
            actor="medical_manager",
            idempotency_key="resume-unexpected-failure",
            expected_pipeline_id=PIPELINE_ID,
            expected_stage="awaiting_document_validation",
        )

    failed = holder["state"]
    assert failed.stage == "awaiting_document_validation"
    assert failed.last_resume_idempotency_key == ""
    assert failed.last_resume_started_from_stage == "awaiting_document_validation"
    assert failed.last_resume_result_stage == "awaiting_document_validation"
    assert failed.error_summary.startswith("resume_failed:RuntimeError:")
    assert repository.override_calls == 0


def test_resume_corpus_analysis_failure_keeps_truthful_retryable_stage() -> None:
    service, _repository = _admission_service("confirmed")
    journey = SimpleNamespace(
        search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID),
        corpus_gate=SimpleNamespace(readiness_status="not_ready", override=None),
    )
    service.journey_service = SimpleNamespace(get=lambda _project_id: journey)
    service._lock = threading.RLock()
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_translation_scope",
        snapshot_id=SNAPSHOT_ID,
        prep_batch_id="prep_batch_validation_gate",
    )
    holder = {"state": state}

    def persist(_project_id, next_state):
        holder["state"] = next_state
        return next_state

    service.get_state = lambda _project_id: holder["state"]
    service._persist = persist
    service._start_translation_batch = lambda *_args: {
        "batch_id": "translation_batch_ready"
    }
    service._wait_translation = lambda *_args: None
    service._run_round1_analysis = lambda *_args: (_ for _ in ()).throw(
        ResearchPipelineError("independent AI produced no evidence-bound corpus findings")
    )

    with pytest.raises(ResearchPipelineError, match="no evidence-bound"):
        service.resume_waiting(
            PROJECT_ID,
            actor="medical_manager",
            idempotency_key="resume-analysis-failed",
            expected_pipeline_id=PIPELINE_ID,
            expected_stage="awaiting_translation_scope",
        )

    failed = holder["state"]
    assert failed.stage == "awaiting_corpus_analysis"
    assert failed.translation_batch_id == "translation_batch_ready"
    assert failed.last_resume_idempotency_key == ""
    assert failed.last_resume_started_from_stage == "awaiting_translation_scope"
    assert failed.last_resume_result_stage == "awaiting_corpus_analysis"
    assert failed.last_resume_at


def test_failed_downstream_pipeline_resumes_from_existing_preparation_batch() -> None:
    service, repository = _admission_service("confirmed")
    journey = SimpleNamespace(
        search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID),
        corpus_gate=SimpleNamespace(readiness_status="ready", override=None),
    )
    service.journey_service = SimpleNamespace(get=lambda _project_id: journey)
    service.corpus_readiness_service = SimpleNamespace(
        recalculate=lambda _project_id, actor: None
    )
    service._lock = threading.RLock()
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="failed",
        snapshot_id=SNAPSHOT_ID,
        prep_batch_id="prep_batch_validation_gate",
        translation_batch_id="translation_batch_failed_v1",
        error_summary=(
            "ResearchPipelineError: 翻译未形成可用关键锚点译文"
        ),
    )
    holder = {"state": state}
    translation_calls = []

    def persist(_project_id, next_state):
        holder["state"] = next_state
        return next_state

    def start_translation(*args):
        translation_calls.append(args)
        return {"batch_id": "translation_batch_recovered_v2"}

    service.get_state = lambda _project_id: holder["state"]
    service._persist = persist
    service._start_translation_batch = start_translation
    service._wait_translation = lambda *_args: None

    def run_round1(_project_id, _actor, current):
        current.round1_analysis_id = "analysis_recovered_from_failed"
        current.round1_analysis_output_hash = "d" * 64
        return ["brief_recovered_from_failed"]

    service._run_round1_analysis = run_round1
    service._notify_corpus_ready = lambda _project_id: None

    resumed = service.resume_waiting(
        PROJECT_ID,
        actor="medical_manager",
        idempotency_key="resume-failed-downstream-1",
        expected_pipeline_id=PIPELINE_ID,
        expected_stage="failed",
    )

    assert resumed.stage == "corpus_ready"
    assert resumed.prep_batch_id == "prep_batch_validation_gate"
    assert resumed.translation_batch_id == "translation_batch_recovered_v2"
    assert translation_calls[0][-1] == "translation_batch_failed_v1"
    assert repository.override_calls == 0
    assert repository.structure_approval_calls == 1


def test_automatic_parent_retry_reuses_existing_translation_batch_without_new_ai_call() -> None:
    service = object.__new__(MedicalWritingResearchPipelineService)
    calls = {"get": 0, "ensure": 0, "preview": 0, "create": 0, "wake": 0}

    class _Worker:
        def wake(self, _project_id, _job_id):
            calls["wake"] += 1

    class _Translation:
        def get(self, _project_id, batch_id):
            calls["get"] += 1
            assert batch_id == "translation_batch_already_started"
            return {
                "batch_id": batch_id,
                "status": "running",
                "items": [{"generation_status": "pending"}],
            }

        def ensure_reference_translation_job(self, _project_id, batch_id, *, actor):
            calls["ensure"] += 1
            assert batch_id == "translation_batch_already_started"
            assert actor == "medical_manager"
            return "mwjob_translation_existing"

        def preview(self, *_args, **_kwargs):
            calls["preview"] += 1
            raise AssertionError("automatic retry must not create a new scope")

        def create(self, *_args, **_kwargs):
            calls["create"] += 1
            raise AssertionError("automatic retry must not create a new batch")

    service.translation_batch_service = _Translation()
    service.durable_worker = _Worker()

    result = service._start_translation_batch(
        PROJECT_ID,
        "medical_manager",
        PIPELINE_ID,
        SNAPSHOT_ID,
        "translation_batch_already_started",
    )

    assert result["batch_id"] == "translation_batch_already_started"
    assert result["reused_existing_batch"] is True
    assert result["durable_job_id"] == "mwjob_translation_existing"
    assert calls == {"get": 1, "ensure": 1, "preview": 0, "create": 0, "wake": 1}


def test_explicit_user_retry_is_the_only_path_allowed_to_create_new_translation_batch() -> None:
    service = object.__new__(MedicalWritingResearchPipelineService)
    calls = {"get": 0, "preview": 0, "create": 0, "ensure": 0}

    class _Translation:
        def get(self, *_args):
            calls["get"] += 1
            return {"batch_id": "translation_batch_previous", "status": "failed"}

        def preview(self, *_args, **_kwargs):
            calls["preview"] += 1
            return SimpleNamespace(scope_sha256="scope-hash")

        def create(self, _project_id, _request):
            calls["create"] += 1
            return SimpleNamespace(
                batch_id="translation_batch_explicit_retry",
                model_dump=lambda mode="json": {
                    "batch_id": "translation_batch_explicit_retry",
                    "status": "pending",
                },
            )

        def ensure_reference_translation_job(self, *_args, **_kwargs):
            calls["ensure"] += 1
            return "mwjob_translation_explicit_retry"

    service.translation_batch_service = _Translation()
    service.durable_worker = None

    result = service._start_translation_batch(
        PROJECT_ID,
        "medical_manager",
        PIPELINE_ID,
        SNAPSHOT_ID,
        "translation_batch_previous",
        allow_new_batch=True,
    )

    assert result["batch_id"] == "translation_batch_explicit_retry"
    assert "reused_existing_batch" not in result
    assert calls == {"get": 0, "preview": 1, "create": 1, "ensure": 1}


def test_resume_releases_pipeline_lock_while_downstream_work_is_running() -> None:
    service, _repository = _admission_service("confirmed")
    service._lock = threading.RLock()
    service.preparation_batch_service.batch.status = "partial_failure"
    service.preparation_batch_service.batch.failed_count = 1
    service.preparation_batch_service.batch.prepared_count = 1
    service.preparation_batch_service.batch.completed_document_count = 2
    service.preparation_batch_service.batch.deferred_item_count = 1
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_translation_scope",
        snapshot_id=SNAPSHOT_ID,
        prep_batch_id="prep_batch_validation_gate",
    )
    holder = {"state": state}
    entered = threading.Event()
    release = threading.Event()
    errors = []

    def persist(_project_id, next_state):
        holder["state"] = next_state
        return next_state

    def continue_slow(_project_id, *, actor, state, prep_batch_id):
        entered.set()
        assert service._active_resume_projects == {PROJECT_ID}
        observed = service._reconcile_stale_preparation_state(PROJECT_ID, state)
        assert observed.stage == "preparing"
        assert release.wait(timeout=2)
        return state

    service.get_state = lambda _project_id: holder["state"]
    service._persist = persist
    service._continue_from_prepared_batch = continue_slow

    def run_resume():
        try:
            service.resume_waiting(
                PROJECT_ID,
                actor="medical_manager",
                idempotency_key="resume-lock-release-1",
                expected_pipeline_id=PIPELINE_ID,
                expected_stage="awaiting_translation_scope",
            )
        except Exception as exc:  # pragma: no cover - assertion reports below
            errors.append(exc)

    thread = threading.Thread(target=run_resume)
    thread.start()
    assert entered.wait(timeout=1)
    assert service._lock.acquire(timeout=0.25)
    service._lock.release()
    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert errors == []
    assert service._active_resume_projects == set()


def test_round1_material_accepts_confirmed_pre_picos_discovery_basket() -> None:
    service = object.__new__(MedicalWritingResearchPipelineService)
    service.translation_batch_service = SimpleNamespace(
        get=lambda _project_id, _batch_id: SimpleNamespace(
            items=[
                SimpleNamespace(
                    document_type="protocol",
                    validation_status="confirmed",
                    structure_review_id="structure_review_1",
                    structure_review_revision=1,
                    ich_m11_anchor="eligibility",
                    generation_status="candidate_ready",
                    fidelity_status="passed",
                )
            ]
        )
    )
    journey = SimpleNamespace(
        search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID),
        corpus_triage=SimpleNamespace(
            status="pending",
            snapshot_id="",
            retained_candidate_ids=[],
        ),
        discovery_basket_projection=SimpleNamespace(
            confirmation_id="ct_conf_discovery_1",
            snapshot_id=SNAPSHOT_ID,
            retained_nct_ids=["NCT00000001"],
        ),
        corpus_gate=SimpleNamespace(requirements=[]),
    )
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_corpus_admission",
        snapshot_id=SNAPSHOT_ID,
        translation_batch_id="translation_batch_discovery",
        round1_analysis_id="analysis_discovery",
        round1_analysis_output_hash="e" * 64,
        round1_brief_ids=["brief_discovery"],
        round1_ai_route={"provider": "deepseek", "model": "deepseek-v4-pro"},
    )

    ready, detail = service._round1_material_ready(PROJECT_ID, journey, state)

    assert ready is True
    assert detail == "material_ready"


def test_round1_material_rejects_unconfirmed_scope_and_unreviewed_protocol() -> None:
    service = object.__new__(MedicalWritingResearchPipelineService)
    service.translation_batch_service = SimpleNamespace(
        get=lambda _project_id, _batch_id: SimpleNamespace(
            items=[
                SimpleNamespace(
                    document_type="protocol",
                    validation_status="needs_review",
                    structure_review_id="",
                    structure_review_revision=0,
                    ich_m11_anchor="eligibility",
                    generation_status="candidate_ready",
                    fidelity_status="passed",
                )
            ]
        )
    )
    journey = SimpleNamespace(
        search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID),
        corpus_triage=SimpleNamespace(
            status="pending",
            snapshot_id="",
            retained_candidate_ids=[],
        ),
        discovery_basket_projection=SimpleNamespace(
            confirmation_id="",
            snapshot_id=SNAPSHOT_ID,
            retained_nct_ids=[],
        ),
        corpus_gate=SimpleNamespace(requirements=[]),
    )
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_corpus_admission",
        snapshot_id=SNAPSHOT_ID,
        translation_batch_id="translation_batch_unconfirmed",
        round1_analysis_id="analysis_unconfirmed",
        round1_analysis_output_hash="f" * 64,
        round1_brief_ids=["brief_unconfirmed"],
        round1_ai_route={"provider": "deepseek", "model": "deepseek-v4-pro"},
    )

    ready, detail = service._round1_material_ready(PROJECT_ID, journey, state)

    assert ready is False
    assert "competitor_scope_not_confirmed" in detail
    assert "protocol_structure_not_satisfied" in detail


def test_resume_waiting_rejects_non_user_action_stage() -> None:
    service, _repository = _admission_service("confirmed")
    service._lock = threading.RLock()
    service.get_state = lambda _project_id: ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="translating",
        prep_batch_id="prep_batch_validation_gate",
    )

    with pytest.raises(ResearchPipelineConflictError, match="不允许"):
        service.resume_waiting(
            PROJECT_ID,
            actor="medical_manager",
            idempotency_key="resume-invalid-stage",
            expected_pipeline_id=PIPELINE_ID,
            expected_stage="translating",
        )


def test_orphaned_round1_analysis_rebinds_exact_lineage_without_model_retry() -> None:
    state = ResearchPipelineState(
        project_id=PROJECT_ID,
        pipeline_id=PIPELINE_ID,
        snapshot_id=SNAPSHOT_ID,
        stage="translating",
        round1_ai_route={"identity_hash": "route_exact"},
    )

    class _JourneyService:
        def __init__(self) -> None:
            self.state = state

        def get(self, _project_id: str):
            return SimpleNamespace(research_pipeline=self.state.as_dict())

        def save_research_pipeline(self, _project_id: str, payload):
            self.state = ResearchPipelineState.from_dict(payload)

    calls = {"find": 0, "model": 0}

    class _CorpusAnalysis:
        def find_completed_analysis(self, _project_id: str, **kwargs):
            calls["find"] += 1
            assert kwargs == {
                "pipeline_id": PIPELINE_ID,
                "snapshot_id": SNAPSHOT_ID,
                "route_identity_hash": "route_exact",
            }
            return {
                "analysis_id": "mwca_recovered_exact",
                "pipeline_id": PIPELINE_ID,
                "snapshot_id": SNAPSHOT_ID,
                "status": "completed",
                "output_hash": "e" * 64,
                "evidence_summary_ids": ["finding_1", "finding_2"],
            }

        def analyze(self, **_kwargs):
            calls["model"] += 1
            raise AssertionError("reconciliation must never invoke the model")

    service = object.__new__(MedicalWritingResearchPipelineService)
    journey_service = _JourneyService()
    service.journey_service = journey_service
    service.corpus_analysis_ai_service = _CorpusAnalysis()
    service._lock = threading.RLock()

    recovered = service._reconcile_completed_round1_analysis(PROJECT_ID, state)

    assert recovered.stage == "awaiting_corpus_admission"
    assert recovered.round1_analysis_id == "mwca_recovered_exact"
    assert recovered.round1_analysis_output_hash == "e" * 64
    assert recovered.round1_brief_ids == ["finding_1", "finding_2"]
    assert recovered.round1_material_ready is False
    assert "未重新调用独立AI" in recovered.detail

    replayed = service._reconcile_completed_round1_analysis(
        PROJECT_ID, journey_service.state
    )
    assert replayed.round1_analysis_id == recovered.round1_analysis_id
    assert calls == {"find": 1, "model": 0}


def test_orphaned_round1_analysis_fails_closed_on_wrong_lineage() -> None:
    state = ResearchPipelineState(
        project_id=PROJECT_ID,
        pipeline_id=PIPELINE_ID,
        snapshot_id=SNAPSHOT_ID,
        stage="translating",
        round1_ai_route={"identity_hash": "route_exact"},
    )
    service = object.__new__(MedicalWritingResearchPipelineService)
    service.journey_service = SimpleNamespace(
        get=lambda _project_id: SimpleNamespace(research_pipeline=state.as_dict())
    )
    service.corpus_analysis_ai_service = SimpleNamespace(
        find_completed_analysis=lambda *_args, **_kwargs: {
            "analysis_id": "mwca_wrong_scope",
            "pipeline_id": "different_pipeline",
            "snapshot_id": SNAPSHOT_ID,
            "status": "completed",
            "output_hash": "f" * 64,
            "evidence_summary_ids": ["finding_wrong"],
        }
    )
    service._lock = threading.RLock()

    observed = service._reconcile_completed_round1_analysis(PROJECT_ID, state)

    assert observed is state
    assert observed.round1_analysis_id == ""
    assert observed.stage == "translating"


def test_round1_recovery_materializes_stale_corpus_gate_once_without_ai() -> None:
    state = ResearchPipelineState(
        project_id=PROJECT_ID,
        pipeline_id=PIPELINE_ID,
        snapshot_id=SNAPSHOT_ID,
        stage="awaiting_corpus_admission",
        round1_analysis_id="mwca_recovered_exact",
        round1_analysis_output_hash="e" * 64,
        round1_brief_ids=["finding_1"],
    )
    journey = SimpleNamespace(
        corpus_gate=SimpleNamespace(stale=True),
    )
    calls = {"recalculate": 0}

    def recalculate(_project_id: str, *, actor: str):
        calls["recalculate"] += 1
        assert actor == "research_pipeline_reconciliation"
        journey.corpus_gate.stale = False

    service = object.__new__(MedicalWritingResearchPipelineService)
    service.journey_service = SimpleNamespace(get=lambda _project_id: journey)
    service.corpus_readiness_service = SimpleNamespace(recalculate=recalculate)

    service._recalculate_gate_after_round1_recovery(PROJECT_ID, state)
    service._recalculate_gate_after_round1_recovery(PROJECT_ID, state)

    assert calls == {"recalculate": 1}


def test_triage_failure_predicate_accepts_partial_failed_shape() -> None:
    """R12: honest partial_failed summaries (竞品分诊仅部分完成) must stay
    recoverable from the triage entry instead of 409-deadlocking."""
    from services.api.app.medical_writing_research_pipeline import (
        MedicalWritingResearchPipelineService,
    )

    service = object.__new__(MedicalWritingResearchPipelineService)

    assert service.error_summary_indicates_triage_failure(
        "ResearchPipelineError: 竞品分诊仅部分完成：AI provider request failed: HTTP 400"
    )
    assert service.error_summary_indicates_triage_failure(
        "分诊超时：子任务已完成但分诊结果未达到可审核状态"
    )
    assert service.error_summary_indicates_triage_failure(
        "分诊任务结束为 failed: all chunks failed"
    )
    assert not service.error_summary_indicates_triage_failure(
        "研究流水线失败：文档准备批次未产生进展"
    )
