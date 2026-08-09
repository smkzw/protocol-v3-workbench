from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from packages.contracts.workbench_contracts.models import (
    WritingReferenceTranslationBatchCreateRequest,
    WritingReferenceTranslationBatchPreviewRequest,
    WritingReferenceTranslationBatchRetryRequest,
    WritingReferenceTranslationRequest,
    WritingReferenceTranslationRevisionRequest,
)
from services.api.app.chapter_translation_pipeline import (
    FLASH_PLANNING_PROMPT_VERSION,
    FLASH_QC_PROMPT_VERSION,
    PRO_UPPER_LAYER_MODEL,
    UPPER_LAYER_DOCUMENT_PLANNING,
    UPPER_LAYER_POST_HY_INTEGRATION_QC,
    ChapterTranslationPipeline,
    DocumentPlannerSegment,
    FakeFlashPlanner,
    FakeFlashQcRunner,
    FakeHyMt2Translator,
    FakeOcrRunner,
    UpperLayerStageOwner,
    _upper_layer_hash_payload,
    extract_draft_map_from_envelope,
)
from services.api.app.ai_gateway import AiProviderRuntimeError
from services.api.app.writing_reference_repository import WritingReferenceRepository
from services.api.app.writing_reference_upper_layer_adapters import (
    PersistentUpperLayerWritingReferenceTranslationService,
    ProductionPersistedUpperLayerStageExecutorAdapter,
    RuntimeRoutedWritingReferenceUpperLayerExecutionService,
    UpperLayerRuntimeRoute,
    build_production_upper_layer_adapter_factory,
    upper_layer_prompt_resolver,
)
from services.api.app.writing_reference_upper_layer_execution import (
    DEFAULT_UPPER_LAYER_MODEL,
    ESCALATED_UPPER_LAYER_MODEL,
    UpperLayerAdapterRequest,
    UpperLayerAdapterResult,
    UpperLayerExecutionRequest,
    UpperLayerTransientError,
    WritingReferenceUpperLayerExecutionService,
)


NOW = datetime(2026, 7, 25, 2, 30, tzinfo=timezone.utc)


class _Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class _FakeDeepSeekProvider:
    provider_name = "deepseek"
    transport_name = "openai_compatible"

    def __init__(
        self,
        model: str,
        responder,
        calls: list[tuple[str, Any]],
        *,
        response_model: str | None = None,
    ) -> None:
        self.model_name = model
        self.response_model = ""
        self._reported_model = response_model or model
        self._responder = responder
        self._calls = calls

    def run(self, envelope):
        self._calls.append((self.model_name, envelope))
        result = self._responder(self.model_name, envelope)
        if isinstance(result, BaseException):
            raise result
        self.response_model = self._reported_model
        return result


def _segments() -> list[dict[str, Any]]:
    return [
        _upper_layer_hash_payload(
            DocumentPlannerSegment(
                ordinal=1,
                heading="Background",
                ich_m11_anchor="background",
                page_start=1,
                page_end=1,
                span_count=1,
                text_sample="Background sample",
                source_span_ids=("span_001",),
            )
        )
    ]


def _segments_for_count(count: int) -> list[dict[str, Any]]:
    return [
        _upper_layer_hash_payload(
            DocumentPlannerSegment(
                ordinal=ordinal,
                heading=f"Protocol section {ordinal}",
                ich_m11_anchor="unmapped",
                page_start=ordinal,
                page_end=ordinal,
                span_count=1,
                text_sample=f"Section {ordinal}",
                source_span_ids=(f"span_{ordinal:04d}",),
            )
        )
        for ordinal in range(1, count + 1)
    ]


def _planning_request(key: str = "production-wiring-planning-001"):
    return UpperLayerExecutionRequest(
        project_id="proj_upper_wiring",
        owner_type="translation_batch_item",
        owner_id="item_001",
        batch_id="batch_001",
        item_id="item_001",
        artifact_id="artifact_001",
        extraction_revision="extract_r1",
        stage=UPPER_LAYER_DOCUMENT_PLANNING,
        prompt_version=FLASH_PLANNING_PROMPT_VERSION,
        prompt=upper_layer_prompt_resolver(
            UPPER_LAYER_DOCUMENT_PLANNING,
            FLASH_PLANNING_PROMPT_VERSION,
        ),
        deployment_profile="approved_private_clinical",
        input_payload={
            "source_text": '{"segments":[{"ordinal":1}]}',
            "document_context": {
                "segment_count": 1,
                "_planner_segments": _segments(),
            },
        },
        idempotency_key=key,
    )


def _scaled_planning_request(
    *,
    nct_id: str,
    locator: str,
    segment_count: int,
    manifest_chars: int,
) -> UpperLayerExecutionRequest:
    return UpperLayerExecutionRequest(
        project_id="proj_upper_scale",
        owner_type="translation_batch_item",
        owner_id=f"item_{nct_id}",
        batch_id="batch_scale",
        item_id=f"item_{nct_id}",
        artifact_id=f"artifact_{nct_id}",
        extraction_revision="extract_r1",
        stage=UPPER_LAYER_DOCUMENT_PLANNING,
        prompt_version=FLASH_PLANNING_PROMPT_VERSION,
        prompt=upper_layer_prompt_resolver(
            UPPER_LAYER_DOCUMENT_PLANNING,
            FLASH_PLANNING_PROMPT_VERSION,
        ),
        deployment_profile="approved_private_clinical",
        input_payload={
            "source_text": "x" * manifest_chars,
            "document_context": {
                "nct_id": nct_id,
                "source_locator": locator,
                "segment_count": segment_count,
                "_planner_segments": _segments_for_count(segment_count),
            },
        },
        idempotency_key=f"production-scale-{nct_id}-{segment_count}",
    )


def _valid_plan_for_segment_count(segment_count: int) -> dict[str, Any]:
    return {
        "document_role": "protocol",
        "chapters": [
            {
                "id": "ch_01",
                "title": "Protocol",
                "ich_m11_anchor": "unmapped",
                "start_segment_ordinal": 1,
                "end_segment_ordinal": segment_count,
            }
        ],
    }


def _valid_plan(_model: str, _envelope: Any) -> dict[str, Any]:
    return {
        "document_role": "protocol",
        "chapters": [
            {
                "id": "ch_01",
                "title": "Background",
                "ich_m11_anchor": "background",
                "start_segment_ordinal": 1,
                "end_segment_ordinal": 1,
            }
        ],
    }


def _marked_draft(envelope: Any) -> str:
    draft_map = extract_draft_map_from_envelope(
        str(envelope.payload["translated_text"])
    )
    return "\n\n".join(
        f"[[CMS_SEG_{ordinal:04d}]]\n{text}\n[[/CMS_SEG_{ordinal:04d}]]"
        for ordinal, text in sorted(draft_map.items())
    )


def test_main_injects_one_persisted_pipeline_into_direct_and_batch() -> None:
    from services.api.app import main

    pipeline = main._chapter_translation_pipeline
    assert isinstance(
        pipeline.upper_layer_executor,
        ProductionPersistedUpperLayerStageExecutorAdapter,
    )
    assert (
        pipeline.upper_layer_executor.service
        is main.writing_reference_upper_layer_execution_service
    )
    assert main.writing_reference_translation_service.chapter_pipeline is pipeline
    assert main.writing_reference_translation_batch_service.chapter_pipeline is pipeline
    assert isinstance(
        main.writing_reference_translation_service,
        PersistentUpperLayerWritingReferenceTranslationService,
    )
    assert pipeline.flash_planner.__self__ is main._direct_upper_layer_callable_bridge
    assert pipeline.flash_qc_runner.__self__ is main._direct_upper_layer_callable_bridge


def test_main_startup_hook_invokes_only_shared_escalation_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.api.app import main

    calls: list[str] = []
    monkeypatch.setattr(
        main.writing_reference_upper_layer_execution_service,
        "resume_pending_escalations",
        lambda: calls.append("recover"),
    )
    main._recover_writing_reference_upper_layer_escalations()
    assert calls == ["recover"]


def test_exact_flash_and_pro_model_identity_and_deterministic_escalation(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Any]] = []

    def responder(model: str, envelope: Any):
        if model == DEFAULT_UPPER_LAYER_MODEL:
            return {"document_role": "protocol", "chapters": []}
        return _valid_plan(model, envelope)

    def providers(model: str):
        return _FakeDeepSeekProvider(model, responder, calls)

    repository = WritingReferenceRepository(tmp_path / "upper.sqlite3")
    service = WritingReferenceUpperLayerExecutionService(
        repository,
        build_production_upper_layer_adapter_factory(provider_factory=providers),
    )
    outcome = service.execute(_planning_request())

    assert [model for model, _ in calls] == [
        DEFAULT_UPPER_LAYER_MODEL,
        DEFAULT_UPPER_LAYER_MODEL,
        ESCALATED_UPPER_LAYER_MODEL,
    ]
    assert outcome.flash_run.status == "failed_escalatable"
    assert outcome.flash_run.failure_code == "planning_chapters_missing"
    assert outcome.flash_run.provider_call_count == 2
    assert outcome.flash_run.planner_attempt_count == 2
    assert [
        envelope.payload["planner_attempt"]
        for model, envelope in calls
        if model == DEFAULT_UPPER_LAYER_MODEL
    ] == [1, 2]
    assert "retry_instruction" not in calls[0][1].payload
    assert calls[1][1].payload["retry_instruction"]
    assert outcome.latest_run.status == "succeeded"
    assert outcome.latest_run.requested_model == ESCALATED_UPPER_LAYER_MODEL
    assert outcome.latest_run.response_model == ESCALATED_UPPER_LAYER_MODEL
    assert outcome.latest_run.parent_stage_run_id == outcome.flash_run.stage_run_id
    assert outcome.escalation is not None
    assert outcome.escalation.trigger_status == "failed_escalatable"


def test_production_adapter_preserves_specific_range_failure_code(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Any]] = []

    def invalid_gap(_model: str, _envelope: Any):
        return {
            "document_role": "protocol",
            "chapters": [
                {
                    "id": "ch_01",
                    "title": "Gap",
                    "start_segment_ordinal": 2,
                    "end_segment_ordinal": 2,
                }
            ],
        }

    outcome = WritingReferenceUpperLayerExecutionService(
        WritingReferenceRepository(tmp_path / "range-code.sqlite3"),
        build_production_upper_layer_adapter_factory(
            provider_factory=lambda model: _FakeDeepSeekProvider(
                model,
                invalid_gap,
                calls,
            )
        ),
    ).execute(
        _scaled_planning_request(
            nct_id="RANGEGAP",
            locator="fixture:planner-range-gap",
            segment_count=3,
            manifest_chars=128,
        )
    )

    assert [model for model, _ in calls] == [
        DEFAULT_UPPER_LAYER_MODEL,
        DEFAULT_UPPER_LAYER_MODEL,
        ESCALATED_UPPER_LAYER_MODEL,
    ]
    assert outcome.flash_run.failure_code == "planner_range_gap"
    assert outcome.latest_run.failure_code == "planner_range_gap"
    assert outcome.escalation is not None
    assert outcome.escalation.trigger_code == "planner_range_gap"


@pytest.mark.parametrize(
    ("nct_id", "locator", "segment_count", "manifest_chars"),
    [
        (
            "NCT04876677",
            "ctgov:NCT04876677:wref_doc_037466e78db6f0a5cbcd:p30:b4",
            124,
            93_210,
        ),
        (
            "NCT02629965",
            "ctgov:NCT02629965:wref_doc_96de204aa4044912627d:p57:b2",
            158,
            110_880,
        ),
        (
            "NCT04078126",
            "ctgov:NCT04078126:wref_doc_feef9cdf57e8fa1fef55:p51:b11",
            198,
            146_031,
        ),
        (
            "NCT03162055",
            "ctgov:NCT03162055:wref_doc_4e900d5a590ac66ad543:p70:b20",
            258,
            196_008,
        ),
    ],
)
def test_real_scale_planner_manifest_uses_corrective_retry_without_size_branch(
    tmp_path: Path,
    nct_id: str,
    locator: str,
    segment_count: int,
    manifest_chars: int,
) -> None:
    calls: list[tuple[str, Any]] = []

    def responder(model: str, envelope: Any):
        assert model == DEFAULT_UPPER_LAYER_MODEL
        if envelope.payload["planner_attempt"] == 1:
            return {"document_role": "protocol", "chapters": []}
        return _valid_plan_for_segment_count(segment_count)

    service = WritingReferenceUpperLayerExecutionService(
        WritingReferenceRepository(tmp_path / f"{nct_id}.sqlite3"),
        build_production_upper_layer_adapter_factory(
            provider_factory=lambda model: _FakeDeepSeekProvider(
                model,
                responder,
                calls,
            )
        ),
    )
    outcome = service.execute(
        _scaled_planning_request(
            nct_id=nct_id,
            locator=locator,
            segment_count=segment_count,
            manifest_chars=manifest_chars,
        )
    )

    assert [model for model, _ in calls] == [
        DEFAULT_UPPER_LAYER_MODEL,
        DEFAULT_UPPER_LAYER_MODEL,
    ]
    assert outcome.flash_run.status == "succeeded"
    assert outcome.flash_run.provider_call_count == 2
    assert outcome.flash_run.planner_attempt_count == 2
    assert outcome.escalation is None
    assert calls[0][1].payload["source_text"] == calls[1][1].payload["source_text"]
    assert (
        calls[0][1].payload["document_context"]
        == calls[1][1].payload["document_context"]
    )


@pytest.mark.parametrize("segment_count", [190, 203, 228, 235, 243])
def test_successful_cross_document_scale_does_not_force_retry(
    tmp_path: Path,
    segment_count: int,
) -> None:
    calls: list[tuple[str, Any]] = []

    service = WritingReferenceUpperLayerExecutionService(
        WritingReferenceRepository(tmp_path / f"success-{segment_count}.sqlite3"),
        build_production_upper_layer_adapter_factory(
            provider_factory=lambda model: _FakeDeepSeekProvider(
                model,
                lambda _model, _envelope: _valid_plan_for_segment_count(
                    segment_count
                ),
                calls,
            )
        ),
    )
    outcome = service.execute(
        _scaled_planning_request(
            nct_id=f"SUCCESS{segment_count}",
            locator=f"fixture:successful:{segment_count}",
            segment_count=segment_count,
            manifest_chars=segment_count * 750,
        )
    )

    assert [model for model, _ in calls] == [DEFAULT_UPPER_LAYER_MODEL]
    assert outcome.flash_run.status == "succeeded"
    assert outcome.flash_run.provider_call_count == 1
    assert outcome.flash_run.planner_attempt_count == 1


def test_duplicate_provider_chapter_ids_are_canonicalized_and_replay_after_restart(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "server-canonical-chapter-ids.sqlite3"
    calls: list[tuple[str, Any]] = []
    request = _scaled_planning_request(
        nct_id="CANONICALIDS",
        locator="fixture:server-canonical-chapter-ids",
        segment_count=2,
        manifest_chars=256,
    )

    def duplicate_provider_ids(_model: str, _envelope: Any) -> dict[str, Any]:
        return {
            "document_role": "protocol",
            "chapters": [
                {
                    "id": "provider-duplicate",
                    "title": "Background",
                    "ich_m11_anchor": "background",
                    "start_segment_ordinal": 1,
                    "end_segment_ordinal": 1,
                },
                {
                    "id": "provider-duplicate",
                    "title": "Objectives",
                    "ich_m11_anchor": "objectives",
                    "start_segment_ordinal": 2,
                    "end_segment_ordinal": 2,
                },
            ],
        }

    first = WritingReferenceUpperLayerExecutionService(
        WritingReferenceRepository(db_path),
        build_production_upper_layer_adapter_factory(
            provider_factory=lambda model: _FakeDeepSeekProvider(
                model,
                duplicate_provider_ids,
                calls,
            )
        ),
    ).execute(request)

    chapters = first.selected_output["chapters"]
    assert [model for model, _ in calls] == [DEFAULT_UPPER_LAYER_MODEL]
    assert first.flash_run.status == "succeeded"
    assert first.flash_run.provider_call_count == 1
    assert first.flash_run.planner_attempt_count == 1
    assert first.escalation is None
    assert len({chapter["id"] for chapter in chapters}) == 2
    assert all(
        chapter["id"].startswith("ch_") and len(chapter["id"]) == 67
        for chapter in chapters
    )
    assert [chapter["title"] for chapter in chapters] == [
        "Background",
        "Objectives",
    ]
    assert [chapter["ich_m11_anchor"] for chapter in chapters] == [
        "background",
        "objectives",
    ]
    assert [chapter["source_span_ids"] for chapter in chapters] == [
        ["span_0001"],
        ["span_0002"],
    ]

    replay_calls: list[tuple[str, Any]] = []

    def unexpected_provider_call(_model: str, _envelope: Any) -> BaseException:
        return AssertionError("persisted replay must not invoke the provider")

    replay = WritingReferenceUpperLayerExecutionService(
        WritingReferenceRepository(db_path),
        build_production_upper_layer_adapter_factory(
            provider_factory=lambda model: _FakeDeepSeekProvider(
                model,
                unexpected_provider_call,
                replay_calls,
            )
        ),
    ).execute(request)

    assert replay_calls == []
    assert replay.selected_output == first.selected_output
    assert replay.flash_run.stage_run_id == first.flash_run.stage_run_id
    assert replay.flash_run.output_hash == first.flash_run.output_hash
    assert replay.latest_run.stage_run_id == first.latest_run.stage_run_id


def test_transient_failure_never_escalates(tmp_path: Path) -> None:
    class _TransientProvider(_FakeDeepSeekProvider):
        def run(self, envelope):
            self._calls.append((self.model_name, envelope))
            raise UpperLayerTransientError("provider_timeout")

    calls: list[tuple[str, Any]] = []
    repository = WritingReferenceRepository(tmp_path / "upper.sqlite3")
    service = WritingReferenceUpperLayerExecutionService(
        repository,
        build_production_upper_layer_adapter_factory(
            provider_factory=lambda model: _TransientProvider(model, _valid_plan, calls)
        ),
        flash_max_attempts=2,
    )
    outcome = service.execute(_planning_request())

    assert outcome.flash_run.status == "failed_retryable"
    assert outcome.escalation is None
    assert [model for model, _ in calls] == [
        DEFAULT_UPPER_LAYER_MODEL,
        DEFAULT_UPPER_LAYER_MODEL,
    ]


@pytest.mark.parametrize(
    ("input_payload", "expected_code"),
    [
        ("not-a-dict", "planning_input_not_structured"),
        (
            {"source_text": "source"},
            "planning_input_not_structured",
        ),
        (
            {
                "source_text": "source",
                "document_context": {"segment_count": 1},
            },
            "planning_segment_manifest_missing",
        ),
    ],
    ids=["non-dict", "missing-context", "missing-segment-manifest"],
)
def test_planning_input_defects_are_terminal_and_do_not_call_pro(
    tmp_path: Path,
    input_payload: Any,
    expected_code: str,
) -> None:
    calls: list[tuple[str, Any]] = []
    request = _planning_request(
        f"planning-input-terminal-{expected_code}"
    )
    request = UpperLayerExecutionRequest(
        **{
            **request.__dict__,
            "input_payload": input_payload,
        }
    )
    outcome = WritingReferenceUpperLayerExecutionService(
        WritingReferenceRepository(
            tmp_path / f"{expected_code}.sqlite3"
        ),
        build_production_upper_layer_adapter_factory(
            provider_factory=lambda model: _FakeDeepSeekProvider(
                model,
                _valid_plan,
                calls,
            )
        ),
    ).execute(request)

    assert outcome.flash_run.status == "failed_terminal"
    assert outcome.flash_run.failure_code == expected_code
    assert outcome.flash_run.provider_call_count == 1
    assert outcome.flash_run.planner_attempt_count == 1
    assert outcome.escalation is None
    assert calls == []


def test_pro_qc_reuses_target_map_and_never_reinvokes_hy_mt2(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Any]] = []

    def responder(model: str, envelope: Any):
        if "document_context" in envelope.payload:
            return _valid_plan(model, envelope)
        integrated = _marked_draft(envelope)
        if model == DEFAULT_UPPER_LAYER_MODEL:
            return {
                "passed": False,
                "failure_codes": ["unit_1:continuity_review"],
                "integrated_text": integrated,
            }
        return {
            "passed": True,
            "failure_codes": [],
            "integrated_text": integrated,
        }

    repository = WritingReferenceRepository(tmp_path / "upper.sqlite3")
    upper_service = WritingReferenceUpperLayerExecutionService(
        repository,
        build_production_upper_layer_adapter_factory(
            provider_factory=lambda model: _FakeDeepSeekProvider(
                model, responder, calls
            )
        ),
    )
    executor = ProductionPersistedUpperLayerStageExecutorAdapter(
        upper_service,
        deployment_profile="approved_private_clinical",
        prompt_resolver=upper_layer_prompt_resolver,
    )
    hy = FakeHyMt2Translator(
        translations={"Participants should rest.": "受试者应休息。"}
    )
    pipeline = ChapterTranslationPipeline(
        ocr_runner=FakeOcrRunner(),
        flash_planner=FakeFlashPlanner(),
        hy_mt2_translator=hy,
        flash_qc_runner=FakeFlashQcRunner(),
        upper_layer_executor=executor,
    )
    candidate = pipeline.translate_chapter(
        source_text="Participants should rest.",
        document_sha256="d" * 64,
        extraction_revision="extract_r1",
        chapter_id="ch_01",
        chunk_id="chunk_01",
        glossary_version="cms_regulatory_zh_v1",
        document_context={
            "segment_count": 1,
            "_planner_segments": tuple(
                DocumentPlannerSegment(
                    ordinal=1,
                    heading="Background",
                    ich_m11_anchor="background",
                    page_start=1,
                    page_end=1,
                    span_count=1,
                    text_sample="Background sample",
                    source_span_ids=("span_001",),
                )
                for _ in range(1)
            ),
        },
        upper_layer_owner=UpperLayerStageOwner(
            project_id="proj_upper_wiring",
            owner_type="direct_translation",
            owner_id="direct_001",
            artifact_id="artifact_001",
            extraction_revision="extract_r1",
            chapter_id="ch_01",
        ),
    )

    assert candidate.translated_text == "受试者应休息。"
    assert len(hy.calls) == 1
    qc_calls = [
        (model, envelope)
        for model, envelope in calls
        if "translated_text" in envelope.payload
    ]
    assert [model for model, _ in qc_calls] == [
        DEFAULT_UPPER_LAYER_MODEL,
        ESCALATED_UPPER_LAYER_MODEL,
    ]
    flash_map = extract_draft_map_from_envelope(
        qc_calls[0][1].payload["translated_text"]
    )
    pro_map = extract_draft_map_from_envelope(qc_calls[1][1].payload["translated_text"])
    assert flash_map == pro_map == {1: "受试者应休息。"}
    with repository._connect() as connection:
        rows = connection.execute(
            """
            SELECT requested_model, hy_mt2_target_map_sha256
            FROM writing_reference_upper_layer_stage_runs
            WHERE project_id=? AND stage=?
            ORDER BY created_at, requested_model
            """,
            ("proj_upper_wiring", UPPER_LAYER_POST_HY_INTEGRATION_QC),
        ).fetchall()
    assert {row["requested_model"] for row in rows} == {
        DEFAULT_UPPER_LAYER_MODEL,
        PRO_UPPER_LAYER_MODEL,
    }
    assert len({row["hy_mt2_target_map_sha256"] for row in rows}) == 1


def test_unconfigured_provider_fails_closed_as_retryable(tmp_path: Path) -> None:
    repository = WritingReferenceRepository(tmp_path / "upper.sqlite3")
    service = WritingReferenceUpperLayerExecutionService(
        repository,
        build_production_upper_layer_adapter_factory(
            env={
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "approved_private_clinical",
            }
        ),
        flash_max_attempts=1,
    )
    outcome = service.execute(_planning_request())

    assert outcome.flash_run.status == "failed_retryable"
    assert outcome.flash_run.failure_code == "deepseek_provider_not_configured"
    assert outcome.flash_run.provider_call_count == 1
    assert outcome.escalation is None


def test_response_model_mismatch_fails_terminal_without_pro(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Any]] = []
    repository = WritingReferenceRepository(tmp_path / "upper.sqlite3")
    service = WritingReferenceUpperLayerExecutionService(
        repository,
        build_production_upper_layer_adapter_factory(
            provider_factory=lambda model: _FakeDeepSeekProvider(
                model,
                _valid_plan,
                calls,
                response_model="wrong-model",
            )
        ),
    )
    outcome = service.execute(_planning_request())

    assert outcome.flash_run.status == "failed_terminal"
    assert outcome.flash_run.failure_code == "response_model_mismatch"
    assert outcome.flash_run.response_model == "wrong-model"
    assert outcome.escalation is None


def test_terminal_provider_request_error_does_not_escalate(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Any]] = []

    def responder(_model: str, _envelope: Any):
        return AiProviderRuntimeError("AI provider request failed: HTTP 400")

    repository = WritingReferenceRepository(tmp_path / "upper.sqlite3")
    service = WritingReferenceUpperLayerExecutionService(
        repository,
        build_production_upper_layer_adapter_factory(
            provider_factory=lambda model: _FakeDeepSeekProvider(
                model, responder, calls
            )
        ),
    )
    outcome = service.execute(_planning_request())

    assert outcome.flash_run.status == "failed_terminal"
    assert outcome.flash_run.failure_code == "deepseek_request_rejected"
    assert outcome.escalation is None
    assert [model for model, _ in calls] == [DEFAULT_UPPER_LAYER_MODEL]


def test_selected_qwen_route_uses_real_identity_and_required_thinking(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Any]] = []

    class _QwenProvider(_FakeDeepSeekProvider):
        provider_name = "alibaba_token_plan"

    repository = WritingReferenceRepository(tmp_path / "upper.sqlite3")
    service = WritingReferenceUpperLayerExecutionService(
        repository,
        build_production_upper_layer_adapter_factory(
            provider_factory=lambda model: _QwenProvider(
                model,
                lambda selected_model, envelope: _valid_plan(
                    selected_model,
                    envelope,
                ),
                calls,
            ),
            provider="alibaba_token_plan",
            transport="openai_compatible",
        ),
        provider="alibaba_token_plan",
        transport="openai_compatible",
        default_model="qwen3.8-max-preview",
        escalation_model="qwen3.8-max-preview",
    )

    outcome = service.execute(_planning_request())

    assert outcome.flash_run.provider == "alibaba_token_plan"
    assert outcome.flash_run.requested_model == "qwen3.8-max-preview"
    assert outcome.flash_run.response_model == "qwen3.8-max-preview"
    assert calls[0][1].thinking == "enabled"
    assert outcome.escalation is None
    assert [model for model, _ in calls] == ["qwen3.8-max-preview"]


def test_runtime_deepseek_flash_route_escalates_to_pro_not_flash() -> None:
    flash_route = UpperLayerRuntimeRoute(
        provider="deepseek",
        transport="openai_compatible",
        model=DEFAULT_UPPER_LAYER_MODEL,
        deployment_profile="local_private_clinical",
    )
    qwen_route = UpperLayerRuntimeRoute(
        provider="alibaba_token_plan",
        transport="openai_compatible",
        model="qwen3.8-max-preview",
        deployment_profile="local_private_clinical",
    )

    assert (
        RuntimeRoutedWritingReferenceUpperLayerExecutionService._escalation_model(
            flash_route
        )
        == ESCALATED_UPPER_LAYER_MODEL
    )
    assert (
        RuntimeRoutedWritingReferenceUpperLayerExecutionService._escalation_model(
            qwen_route
        )
        == "qwen3.8-max-preview"
    )


def test_startup_recovery_resumes_expired_running_but_not_failed_retryable(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    calls: list[UpperLayerAdapterRequest] = []

    class _ScriptAdapter:
        def __init__(self, model: str, transient_pro: bool = False) -> None:
            self.model = model
            self.transient_pro = transient_pro

        def invoke(self, request: UpperLayerAdapterRequest):
            calls.append(request)
            if self.model == DEFAULT_UPPER_LAYER_MODEL:
                return UpperLayerAdapterResult(
                    response_model=self.model,
                    status="failed_escalatable",
                    failure_code="planning_chapters_missing",
                )
            if self.transient_pro:
                raise UpperLayerTransientError("provider_timeout")
            return UpperLayerAdapterResult(
                response_model=self.model,
                status="succeeded",
                output_payload={"result": "recovered"},
            )

    repository = WritingReferenceRepository(tmp_path / "upper.sqlite3")
    service = WritingReferenceUpperLayerExecutionService(
        repository,
        lambda model: _ScriptAdapter(model),
        clock=clock,
        escalation_lease_seconds=30,
    )
    original_claim = repository.claim_upper_layer_escalation
    repository.claim_upper_layer_escalation = lambda *args, **kwargs: None
    queued = service.execute(_planning_request("production-recovery-queued-001"))
    repository.claim_upper_layer_escalation = original_claim
    assert queued.escalation is not None
    assert queued.escalation.status == "queued"

    claimed = repository.claim_upper_layer_escalation(
        queued.flash_run.project_id,
        queued.escalation.escalation_id,
        now=clock(),
        lease_expires_at=clock() + timedelta(seconds=30),
    )
    assert claimed is not None
    clock.advance(31)
    recovered = WritingReferenceUpperLayerExecutionService(
        WritingReferenceRepository(repository.db_path),
        lambda model: _ScriptAdapter(model),
        clock=clock,
        escalation_lease_seconds=30,
    ).resume_pending_escalations()
    assert len(recovered) == 1
    assert recovered[0].latest_run.requested_model == ESCALATED_UPPER_LAYER_MODEL
    assert recovered[0].latest_run.status == "succeeded"

    retry_repository = WritingReferenceRepository(tmp_path / "retry.sqlite3")
    retry_service = WritingReferenceUpperLayerExecutionService(
        retry_repository,
        lambda model: _ScriptAdapter(model, transient_pro=True),
        clock=clock,
        escalation_lease_seconds=30,
    )
    failed_retryable = retry_service.execute(
        _planning_request("production-recovery-retryable-001")
    )
    assert failed_retryable.escalation is not None
    assert failed_retryable.escalation.status == "failed_retryable"
    calls_before = len(calls)
    assert retry_service.resume_pending_escalations() == []
    assert len(calls) == calls_before


def test_translation_api_requests_expose_no_route_controls() -> None:
    forbidden = {
        "provider",
        "model",
        "model_name",
        "base_url",
        "api_key",
        "transport",
    }
    request_models = (
        WritingReferenceTranslationRequest,
        WritingReferenceTranslationRevisionRequest,
        WritingReferenceTranslationBatchPreviewRequest,
        WritingReferenceTranslationBatchCreateRequest,
        WritingReferenceTranslationBatchRetryRequest,
    )
    for model in request_models:
        assert forbidden.isdisjoint(model.model_fields)


@pytest.mark.parametrize(
    ("stage", "version"),
    (
        (UPPER_LAYER_DOCUMENT_PLANNING, FLASH_PLANNING_PROMPT_VERSION),
        (UPPER_LAYER_POST_HY_INTEGRATION_QC, FLASH_QC_PROMPT_VERSION),
    ),
)
def test_production_prompt_resolver_is_stage_and_version_locked(
    stage: str,
    version: str,
) -> None:
    assert upper_layer_prompt_resolver(stage, version).strip()
    with pytest.raises(ValueError):
        upper_layer_prompt_resolver(stage, version + "_client_override")
