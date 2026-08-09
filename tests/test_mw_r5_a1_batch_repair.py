from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from packages.contracts.workbench_contracts import (
    CompetitorTriageChunkStatus,
    WritingReferencePublicDocument,
    WritingReferenceSearchRequest,
    WritingReferenceSearchSnapshot,
    WritingReferenceTrialCandidate,
)
from services.api.app.medical_writing_competitor_triage import (
    _build_chunk_input,
    _candidate_indication_matches_project,
    _candidate_indication_relation,
    _derive_document_suitability,
    _snapshot_hash,
    _triage_retry_business_key,
)
from services.api.app.medical_writing_research_pipeline import (
    MedicalWritingResearchPipelineService,
    ResearchPipelineState,
)


COPD_PROJECT_FACTS = {
    "indication": "慢性阻塞性肺疾病（COPD）",
    "clinicaltrials_condition_term": "",
}


@pytest.mark.parametrize(
    "condition",
    [
        "Chronic Obstructive Pulmonary Disease",
        "Chronic Obstructive Pulmonary Disease (COPD)",
        "COPD",
        "慢性阻塞性肺疾病",
    ],
)
def test_copd_chinese_english_equivalence_is_exact(condition: str) -> None:
    candidate = {"conditions": [condition]}

    assert _candidate_indication_matches_project(candidate, COPD_PROJECT_FACTS)
    assert _candidate_indication_relation(candidate, COPD_PROJECT_FACTS) == "exact"


@pytest.mark.parametrize(
    "condition",
    [
        "Asthma",
        "Bronchiectasis",
        "Chronic Bronchitis",
        "Emphysema",
        "Chronic Obstructive Pulmonary Symptoms",
        "Acute Exacerbation of Chronic Obstructive Pulmonary Disease",
        "COPD-like respiratory disease",
    ],
)
def test_copd_equivalence_does_not_fuzzily_match_other_disease_labels(
    condition: str,
) -> None:
    candidate = {"conditions": [condition]}

    assert not _candidate_indication_matches_project(candidate, COPD_PROJECT_FACTS)
    assert _candidate_indication_relation(candidate, COPD_PROJECT_FACTS) == "none"


def test_large_triage_retry_identity_is_bounded_and_chunk_set_specific() -> None:
    chunk_ids = [f"ct_chunk_{index:03d}_{'a' * 20}" for index in range(80)]
    first = _triage_retry_business_key(
        "snapshot-001:run-001",
        "retry-a1-large-basket-001",
        chunk_ids,
    )
    reordered = _triage_retry_business_key(
        "snapshot-001:run-001",
        "retry-a1-large-basket-001",
        list(reversed(chunk_ids)),
    )
    changed = _triage_retry_business_key(
        "snapshot-001:run-001",
        "retry-a1-large-basket-001",
        [*chunk_ids, "ct_chunk_extra"],
    )

    assert len(first) <= 300
    assert reordered == first
    assert changed != first


def _public_document(*, upload_date: str) -> WritingReferencePublicDocument:
    return WritingReferencePublicDocument(
        document_id="ctgov_NCT02164513_000",
        nct_id="NCT02164513",
        document_type="protocol_sap",
        label="Protocol and SAP",
        filename="Prot_SAP_000.pdf",
        document_date="2018-01-10",
        upload_date=upload_date,
        declared_size=2048,
        download_url=(
            "https://clinicaltrials.gov/ProvidedDocs/13/"
            "NCT02164513/Prot_SAP_000.pdf"
        ),
        source_status="discovered",
        rights_status="pending_review",
    )


def _snapshot(document: WritingReferencePublicDocument) -> WritingReferenceSearchSnapshot:
    candidate = WritingReferenceTrialCandidate(
        nct_id="NCT02164513",
        brief_title="COPD protocol trial",
        official_title="A COPD Protocol Trial",
        conditions=["Chronic Obstructive Pulmonary Disease"],
        phases=["PHASE3"],
        study_type="INTERVENTIONAL",
        study_record_url="https://clinicaltrials.gov/study/NCT02164513",
        public_documents=[document],
    )
    request = WritingReferenceSearchRequest(
        indication="Chronic Obstructive Pulmonary Disease",
        phases=["PHASE3"],
    )
    return WritingReferenceSearchSnapshot(
        snapshot_id="wref_search_copd_lineage",
        project_id="proj_copd_lineage",
        request=request,
        query_url="https://clinicaltrials.gov/api/v2/studies",
        api_version="2.0",
        data_timestamp="2026-07-28",
        total_count=1,
        returned_count=1,
        page_count=1,
        candidates=[candidate],
        created_by="test",
        created_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )


def test_protocol_sap_lineage_changes_snapshot_identity_and_drives_triage() -> None:
    first = _snapshot(_public_document(upload_date="2024-01-01"))
    updated = _snapshot(_public_document(upload_date="2024-02-01"))
    candidate_payload = first.candidates[0].model_dump(mode="json")

    assert _snapshot_hash(first) != _snapshot_hash(updated)
    suitability = _derive_document_suitability(candidate_payload, "")
    assert suitability == {
        "has_public_protocol": True,
        "has_public_sap": True,
        "document_role": "已提供公开方案与统计分析计划",
    }
    assert candidate_payload["public_documents"][0]["document_id"].startswith(
        "ctgov_"
    )
    assert candidate_payload["public_documents"][0]["download_url"].startswith(
        "https://clinicaltrials.gov/ProvidedDocs/"
    )


def test_triage_payload_retains_ctgov_public_document_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(_public_document(upload_date="2024-01-01"))
    product_profile = SimpleNamespace(
        technology_type="small_molecule",
        administration_routes=["inhaled"],
        dosage_forms=["inhalation"],
        exposure_scope="local",
    )
    framing = SimpleNamespace(
        investigational_product="COPD-001",
        indication="慢性阻塞性肺疾病（COPD）",
        clinicaltrials_condition_term="",
        study_phase="III期",
        intrinsic_objectives="",
        design_pattern="",
        target_mechanism="",
        competitor_target_scope="",
        product_profile=product_profile,
        population_intent="",
    )
    journey = SimpleNamespace(
        framing=framing,
        search_plan=SimpleNamespace(
            registry_filter=SimpleNamespace(
                condition_term="Chronic Obstructive Pulmonary Disease"
            )
        ),
    )
    monkeypatch.setattr(
        "services.api.app.medical_writing_competitor_triage.effective_authoring_values",
        lambda _journey: (framing, None),
    )

    payload = _build_chunk_input(journey, snapshot.candidates, 0)
    document = payload["candidates"][0]["public_documents"][0]

    assert document == {
        "document_id": "ctgov_NCT02164513_000",
        "nct_id": "NCT02164513",
        "document_type": "protocol_sap",
        "label": "Protocol and SAP",
        "filename": "Prot_SAP_000.pdf",
        "document_date": "2018-01-10",
        "upload_date": "2024-01-01",
        "declared_size": 2048,
        "download_url": (
            "https://clinicaltrials.gov/ProvidedDocs/13/"
            "NCT02164513/Prot_SAP_000.pdf"
        ),
        "source_status": "discovered",
        "rights_status": "pending_review",
    }
    assert payload["candidates"][0]["project_indication_relation"] == "exact"


class _JourneyService:
    def __init__(self, state: ResearchPipelineState) -> None:
        self.state = state
        self.save_count = 0

    def get(self, project_id: str):
        assert project_id == self.state.project_id
        return SimpleNamespace(
            research_pipeline=self.state.as_dict(),
            corpus_gate=None,
        )

    def save_research_pipeline(self, project_id: str, payload: dict) -> None:
        assert project_id == self.state.project_id
        self.state = ResearchPipelineState.from_dict(payload)
        self.save_count += 1


def _pipeline_service(
    state: ResearchPipelineState,
    triage_run: SimpleNamespace,
) -> tuple[MedicalWritingResearchPipelineService, _JourneyService]:
    journey_service = _JourneyService(state)
    service = object.__new__(MedicalWritingResearchPipelineService)
    service.journey_service = journey_service
    service.triage_service = SimpleNamespace(
        repository=SimpleNamespace(
            triage_run=lambda project_id, run_id: (
                triage_run
                if project_id == state.project_id and run_id == state.triage_run_id
                else None
            )
        )
    )
    import threading

    service._lock = threading.RLock()
    return service, journey_service


def test_review_ready_triage_reconciliation_is_safe_and_idempotent() -> None:
    state = ResearchPipelineState(
        pipeline_id="mwpipe_copd",
        project_id="proj_copd",
        stage="failed",
        percent=100,
        error_summary="ResearchPipelineError: 分诊超时",
        snapshot_id="wref_search_copd",
        triage_run_id="triage_copd",
        created_at="2026-07-28T00:00:00+00:00",
        updated_at="2026-07-28T00:00:00+00:00",
    )
    triage_run = SimpleNamespace(
        run_id="triage_copd",
        snapshot_id="wref_search_copd",
        status="review_ready",
    )
    service, journey_service = _pipeline_service(state, triage_run)

    first = service.status("proj_copd")["pipeline"]
    second = service.status("proj_copd")["pipeline"]

    assert first["stage"] == "awaiting_triage_confirm"
    assert first["error_summary"] == ""
    assert first["prep_batch_id"] == ""
    assert second == first
    assert journey_service.save_count == 1


@pytest.mark.parametrize(
    ("error_summary", "run_snapshot", "run_status"),
    [
        ("ValueError: unrelated failure", "wref_search_copd", "review_ready"),
        ("ResearchPipelineError: 分诊超时", "wref_search_other", "review_ready"),
        ("ResearchPipelineError: 分诊超时", "wref_search_copd", "partial_failed"),
    ],
)
def test_triage_reconciliation_fails_closed(
    error_summary: str,
    run_snapshot: str,
    run_status: str,
) -> None:
    state = ResearchPipelineState(
        pipeline_id="mwpipe_copd",
        project_id="proj_copd",
        stage="failed",
        error_summary=error_summary,
        snapshot_id="wref_search_copd",
        triage_run_id="triage_copd",
    )
    triage_run = SimpleNamespace(
        run_id="triage_copd",
        snapshot_id=run_snapshot,
        status=run_status,
    )
    service, journey_service = _pipeline_service(state, triage_run)

    result = service.reconcile_review_ready_triage("proj_copd")

    assert result.stage == "failed"
    assert journey_service.save_count == 0


def test_failed_parent_retries_only_incomplete_triage_chunks_idempotently() -> None:
    state = ResearchPipelineState(
        pipeline_id="mwpipe_copd",
        project_id="proj_copd",
        stage="failed",
        error_summary="ResearchPipelineError: 分诊超时",
        snapshot_id="wref_search_copd",
        triage_run_id="triage_copd",
    )
    chunks = [
        SimpleNamespace(
            chunk_id="chunk-ok",
            status=CompetitorTriageChunkStatus.SUCCEEDED,
        ),
        SimpleNamespace(
            chunk_id="chunk-pending",
            status=CompetitorTriageChunkStatus.PENDING,
        ),
        SimpleNamespace(
            chunk_id="chunk-failed",
            status=CompetitorTriageChunkStatus.FAILED,
        ),
    ]
    triage_run = SimpleNamespace(
        run_id="triage_copd",
        snapshot_id="wref_search_copd",
        status="partial_failed",
        chunks=chunks,
    )
    service, journey_service = _pipeline_service(state, triage_run)
    retry_calls = []

    def retry_run(project_id, run_id, request, provider):
        retry_calls.append((project_id, run_id, request, provider))
        return SimpleNamespace(
            job_id="job-triage-retry",
            reused=False,
        )

    service.triage_service.retry_run = retry_run
    service.triage_provider_factory = lambda: object()

    first = service.retry_triage(
        "proj_copd",
        actor="medical_manager",
        idempotency_key="retry-triage-copd-001",
        expected_pipeline_id="mwpipe_copd",
        expected_triage_run_id="triage_copd",
    )
    second = service.retry_triage(
        "proj_copd",
        actor="medical_manager",
        idempotency_key="retry-triage-copd-001",
        expected_pipeline_id="mwpipe_copd",
        expected_triage_run_id="triage_copd",
    )

    assert first["pipeline"]["stage"] == "triaging"
    assert first["pipeline"]["snapshot_id"] == "wref_search_copd"
    assert first["pipeline"]["triage_run_id"] == "triage_copd"
    assert first["triage_job_id"] == "job-triage-retry"
    assert second["reused"] is True
    assert len(retry_calls) == 1
    request = retry_calls[0][2]
    assert request.chunk_ids == ["chunk-pending", "chunk-failed"]
    assert "chunk-ok" not in request.chunk_ids
    assert journey_service.save_count == 1


def test_retrying_parent_reconciles_after_same_triage_run_becomes_ready() -> None:
    state = ResearchPipelineState(
        pipeline_id="mwpipe_copd",
        project_id="proj_copd",
        stage="triaging",
        snapshot_id="wref_search_copd",
        triage_run_id="triage_copd",
        last_triage_retry_idempotency_key="retry-triage-copd-001",
        last_triage_retry_job_id="job-triage-retry",
    )
    triage_run = SimpleNamespace(
        run_id="triage_copd",
        snapshot_id="wref_search_copd",
        status="review_ready",
        chunks=[
            SimpleNamespace(
                chunk_id="chunk-ok",
                status=CompetitorTriageChunkStatus.SUCCEEDED,
            )
        ],
    )
    service, journey_service = _pipeline_service(state, triage_run)

    payload = service.status("proj_copd")

    assert payload["pipeline"]["stage"] == "awaiting_triage_confirm"
    assert payload["pipeline"]["error_summary"] == ""
    expected_progress = {
        "run_id": "triage_copd",
        "snapshot_id": "wref_search_copd",
        "status": "review_ready",
        "completed_chunks": 1,
        "total_chunks": 1,
        "pending_chunks": 0,
        "running_chunks": 0,
        "failed_chunks": 0,
        "percent": 100,
        "label": "竞品分诊已完成",
    }
    assert {
        key: payload["triage_progress"][key] for key in expected_progress
    } == expected_progress
    assert payload["triage_progress"]["context"]["chunk_total"] == 1
    assert journey_service.save_count == 1
