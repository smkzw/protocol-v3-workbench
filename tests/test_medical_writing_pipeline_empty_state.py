"""Regression: empty research_pipeline on journey must not produce a
synthetic 'queued' state that the frontend renders as a perpetual spinner.

Defect: get_state() returned ResearchPipelineState(stage="queued") when
journey.research_pipeline was {} or None.  The banner showed "排队中 0%"
with a spinning icon even though no pipeline had been started, and the
poll effect re-queried every 3 s forever.

Fix: get_state() now returns stage="" for empty/None pipeline dicts.
The banner's guard `if (!pipeline || !pipeline.stage) return null` keeps
it hidden.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.api.app.medical_writing_research_pipeline import (
    MedicalWritingResearchPipelineService,
    ResearchPipelineState,
    authoring_write_blocker_detail,
    authoring_writes_blocked_by_pipeline,
    research_ready_for_design_recommendations,
)

PROJECT_ID = "proj_empty_pipeline_test"


class _StubJourney:
    """Minimal journey stub with configurable research_pipeline."""

    def __init__(self, research_pipeline=None):
        self.research_pipeline = research_pipeline
        self.corpus_gate = None
        self.framing = None
        self.picos = None


class _StubJourneyService:
    def __init__(self, journey):
        self._journey = journey

    def get(self, project_id):
        assert project_id == PROJECT_ID
        return self._journey


class _StubCorpusAi:
    """Minimal stub so the service constructor doesn't try to import."""
    pass


def _make_service(journey):
    return MedicalWritingResearchPipelineService(
        journey_service=_StubJourneyService(journey),
        discovery_service=None,
        triage_service=None,
        preparation_batch_service=None,
        translation_batch_service=None,
        corpus_readiness_service=None,
        china_client_factory=lambda: None,
        durable_store=None,
        durable_worker=None,
        corpus_analysis_ai_service=_StubCorpusAi(),
    )


class TestEmptyPipelineState:
    """get_state() must return empty stage when no pipeline is persisted."""

    def test_none_pipeline_returns_empty_stage(self):
        journey = _StubJourney(research_pipeline=None)
        svc = _make_service(journey)
        state = svc.get_state(PROJECT_ID)
        assert state.stage == ""
        assert state.pipeline_id == ""
        assert state.job_id == ""

    def test_empty_dict_pipeline_returns_empty_stage(self):
        journey = _StubJourney(research_pipeline={})
        svc = _make_service(journey)
        state = svc.get_state(PROJECT_ID)
        assert state.stage == ""
        assert state.pipeline_id == ""

    def test_status_endpoint_returns_empty_stage_for_none(self):
        journey = _StubJourney(research_pipeline=None)
        svc = _make_service(journey)
        result = svc.status(PROJECT_ID)
        assert result["pipeline"]["stage"] == ""
        assert result["design_recommendations_unlocked"] is False

    def test_status_endpoint_returns_empty_stage_for_empty_dict(self):
        journey = _StubJourney(research_pipeline={})
        svc = _make_service(journey)
        result = svc.status(PROJECT_ID)
        assert result["pipeline"]["stage"] == ""

    def test_real_queued_pipeline_preserved(self):
        """A genuinely started pipeline with stage='queued' must not be
        collapsed to empty."""
        journey = _StubJourney(
            research_pipeline={
                "pipeline_id": "mwpipe_real123",
                "stage": "queued",
                "percent": 0,
                "job_id": "mwjob_real456",
            }
        )
        svc = _make_service(journey)
        state = svc.get_state(PROJECT_ID)
        assert state.stage == "queued"
        assert state.pipeline_id == "mwpipe_real123"
        assert state.job_id == "mwjob_real456"

    def test_searching_pipeline_preserved(self):
        journey = _StubJourney(
            research_pipeline={
                "pipeline_id": "mwpipe_search789",
                "stage": "searching",
                "percent": 8,
            }
        )
        svc = _make_service(journey)
        state = svc.get_state(PROJECT_ID)
        assert state.stage == "searching"
        assert state.pipeline_id == "mwpipe_search789"


@pytest.mark.parametrize(
    "stage,blocked",
    [
        ("", False),
        ("queued", True),
        ("searching", True),
        ("triaging", True),
        ("awaiting_triage_confirm", True),
        ("preparing", True),
        ("translating", True),
        ("analyzing_round1", True),
        ("awaiting_document_validation", False),
        ("awaiting_translation_scope", False),
        ("awaiting_corpus_analysis", False),
        ("awaiting_corpus_admission", False),
        ("corpus_ready", False),
        ("failed", False),
        ("cancelled", False),
    ],
)
def test_authoring_writes_block_only_while_pipeline_owns_frozen_inputs(stage, blocked):
    assert authoring_writes_blocked_by_pipeline(stage) is blocked


def test_authoring_write_blocker_detail_is_actionable():
    detail = authoring_write_blocker_detail("triaging")
    assert "triaging" in detail
    assert "不能修改研究框架" in detail


def test_stale_pipeline_scope_does_not_block_current_ready_corpus():
    journey = SimpleNamespace(
        research_pipeline={
            "stage": "awaiting_translation_scope",
            "snapshot_id": "snapshot_old",
        },
        corpus_gate=SimpleNamespace(
            readiness_status="ready",
            bound_snapshot_id="snapshot_current",
            override=SimpleNamespace(active=False),
        ),
    )

    ready, reason = research_ready_for_design_recommendations(journey)

    assert ready is True
    assert reason == "research_pipeline_stale_scope_but_current_corpus_ready"


def test_same_snapshot_pipeline_scope_still_fails_closed():
    journey = SimpleNamespace(
        research_pipeline={
            "stage": "awaiting_translation_scope",
            "snapshot_id": "snapshot_current",
        },
        corpus_gate=SimpleNamespace(
            readiness_status="ready",
            bound_snapshot_id="snapshot_current",
            override=SimpleNamespace(active=False),
        ),
    )

    ready, reason = research_ready_for_design_recommendations(journey)

    assert ready is False
    assert reason == "research_pipeline_in_progress:awaiting_translation_scope"
