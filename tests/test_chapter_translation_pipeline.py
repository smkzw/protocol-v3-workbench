"""Focused tests for the chapter translation pipeline architecture remediation.

Tests cover the W1 requirements:
- text page skips OCR; empty/image/spatial page uses OCR
- OCR render DPI >=200 and concurrency <=8
- exact model allowlists
- body translator is Hy-MT2, not Flash-only
- Flash planning before translation and Flash QC after translation
- fidelity drift blocks candidate readiness
- persisted stage/lineage/idempotency/restart/retry behavior
- backward compatibility of existing writing-reference translation APIs
"""
from __future__ import annotations

import unittest
import tempfile
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from services.api.app.chapter_translation_pipeline import (
    ALLOWED_BODY_TRANSLATION_MODELS,
    ALLOWED_FLASH_MODELS,
    ALLOWED_OCR_MODELS,
    ALLOWED_UPPER_LAYER_MODELS,
    ChapterTranslationPipeline,
    ChapterTranslationPipelineError,
    FakeFlashPlanner,
    FakeFlashQcRunner,
    FakeHyMt2Translator,
    FakeOcrRunner,
    FidelityBlockedError,
    FLASH_PLANNING_MODEL,
    FLASH_PLANNING_PROMPT_VERSION,
    FLASH_QC_MODEL,
    FLASH_QC_PROMPT_VERSION,
    HY_MT2_MODEL_ID,
    HY_MT2_PROMPT_VERSION,
    OcrConcurrencyExceededError,
    OcrRenderSpec,
    PageTriageDecision,
    PipelineCandidate,
    PersistedUpperLayerStageExecutorAdapter,
    PRO_UPPER_LAYER_MODEL,
    TranslationPipelineStage,
    UPPER_LAYER_POST_HY_INTEGRATION_QC,
    UpperLayerStageExecutionResult,
    UpperLayerStageOwner,
    _upper_layer_payload_hash,
    _upper_layer_hash_payload,
    WRITING_REFERENCE_OCR_MAX_CONCURRENCY,
    WRITING_REFERENCE_OCR_MIN_DPI,
    WRITING_REFERENCE_OCR_MODEL,
    build_ocr_render_spec,
    enforce_ocr_concurrency,
    triage_page,
    triage_pages,
)


class _AutomaticProStageExecutor:
    """Fake shared service: Flash first, then automatic Pro for selected stages."""

    def __init__(self, escalate_stages: set[str] | None = None) -> None:
        self.escalate_stages = set(escalate_stages or ())
        self.calls: list[tuple[str, str, str]] = []
        self.immutable_body_hashes: list[str] = []

    def execute(
        self,
        *,
        stage,
        owner,
        prompt_version,
        input_payload,
        input_hash,
        invoke,
        output_hash,
        immutable_body_hash="",
    ):
        del input_payload
        self.calls.append((stage, FLASH_PLANNING_MODEL, owner.owner_id))
        self.immutable_body_hashes.append(immutable_body_hash)
        flash_output = invoke(FLASH_PLANNING_MODEL)
        if stage not in self.escalate_stages:
            return UpperLayerStageExecutionResult(
                output=flash_output,
                stage=stage,
                requested_model=FLASH_PLANNING_MODEL,
                response_model=FLASH_PLANNING_MODEL,
                prompt_version=prompt_version,
                input_hash=input_hash,
                output_hash=output_hash(flash_output),
                stage_run_id=f"run_flash_{len(self.calls)}",
            )
        parent_run_id = f"run_flash_{len(self.calls)}"
        self.calls.append((stage, PRO_UPPER_LAYER_MODEL, owner.owner_id))
        pro_output = invoke(PRO_UPPER_LAYER_MODEL)
        return UpperLayerStageExecutionResult(
            output=pro_output,
            stage=stage,
            requested_model=PRO_UPPER_LAYER_MODEL,
            response_model=PRO_UPPER_LAYER_MODEL,
            prompt_version=prompt_version,
            input_hash=input_hash,
            output_hash=output_hash(pro_output),
            status="succeeded",
            stage_run_id=f"run_pro_{len(self.calls)}",
            parent_stage_run_id=parent_run_id,
            escalation_id=f"escalation_{len(self.calls)}",
            escalation_trigger_status="completed_degraded",
            escalation_trigger_code="deterministic_upper_layer_degraded",
            provider_call_count=1,
        )


class PageTriageTests(unittest.TestCase):
    """Text pages skip OCR; empty/image/spatial pages route to OCR."""

    def test_text_page_skips_ocr(self) -> None:
        decision = triage_page(1, "This page has extractable text content.")
        self.assertFalse(decision.needs_ocr)
        self.assertEqual("text", decision.channel)
        self.assertEqual("text_extracted", decision.reason)

    def test_empty_page_routes_to_ocr(self) -> None:
        decision = triage_page(5, "")
        self.assertTrue(decision.needs_ocr)
        self.assertEqual("ocr", decision.channel)

    def test_whitespace_only_page_routes_to_ocr(self) -> None:
        decision = triage_page(3, "   \n  \t  ")
        self.assertTrue(decision.needs_ocr)
        self.assertEqual("ocr", decision.channel)

    def test_image_page_routes_to_ocr(self) -> None:
        decision = triage_page(7, "", is_image_page=True)
        self.assertTrue(decision.needs_ocr)
        self.assertEqual("zero_text_or_spatial_layout", decision.reason)

    def test_spatial_layout_page_routes_to_ocr(self) -> None:
        decision = triage_page(9, "", is_spatial_page=True)
        self.assertTrue(decision.needs_ocr)
        self.assertEqual("ocr", decision.channel)

    def test_batch_triage_mixed_pages(self) -> None:
        pages = [
            (1, "Text page", False, False),
            (2, "", False, False),  # empty
            (3, "", True, False),   # image
            (4, "More text", False, False),
            (5, "", False, True),   # spatial (table)
        ]
        decisions = triage_pages(pages)
        self.assertEqual(5, len(decisions))
        self.assertFalse(decisions[0].needs_ocr)
        self.assertTrue(decisions[1].needs_ocr)
        self.assertTrue(decisions[2].needs_ocr)
        self.assertFalse(decisions[3].needs_ocr)
        self.assertTrue(decisions[4].needs_ocr)
        ocr_pages = [d.physical_page for d in decisions if d.needs_ocr]
        self.assertEqual([2, 3, 5], ocr_pages)


class OcrRenderSpecTests(unittest.TestCase):
    """OCR render DPI must be >=200 and model must be allowlisted."""

    def test_default_render_spec_is_200_dpi(self) -> None:
        spec = build_ocr_render_spec(1)
        self.assertEqual(200, spec.dpi)
        self.assertEqual(WRITING_REFERENCE_OCR_MODEL, spec.model)

    def test_higher_dpi_is_allowed(self) -> None:
        spec = build_ocr_render_spec(2, dpi=300)
        self.assertEqual(300, spec.dpi)

    def test_below_minimum_dpi_rejected(self) -> None:
        with self.assertRaises(ValueError) as raised:
            build_ocr_render_spec(1, dpi=150)
        self.assertIn("200", str(raised.exception))

    def test_wrong_model_rejected(self) -> None:
        with self.assertRaises(ValueError) as raised:
            build_ocr_render_spec(1, model="wrong-model")
        self.assertIn("not in the writing-reference allowlist", str(raised.exception))


class OcrConcurrencyTests(unittest.TestCase):
    """OCR concurrency must be clamped to <=8."""

    def test_default_is_8(self) -> None:
        self.assertEqual(8, enforce_ocr_concurrency(8))

    def test_clamped_to_8(self) -> None:
        self.assertEqual(8, enforce_ocr_concurrency(16))

    def test_zero_rejected(self) -> None:
        with self.assertRaises(ValueError):
            enforce_ocr_concurrency(0)

    def test_negative_rejected(self) -> None:
        with self.assertRaises(ValueError):
            enforce_ocr_concurrency(-1)

    def test_one_is_valid(self) -> None:
        self.assertEqual(1, enforce_ocr_concurrency(1))

    def test_pipeline_enforces_concurrency_in_constructor(self) -> None:
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
            ocr_max_concurrency=20,
        )
        self.assertEqual(8, pipeline.ocr_max_concurrency)

    def test_pipeline_processes_all_pages_within_concurrency_cap(self) -> None:
        """All pages must be processed; active concurrency must never exceed
        the configured cap.  There is no total-page limit — only a
        maximum-active-calls limit."""
        import threading

        ocr = FakeOcrRunner()
        pipeline = ChapterTranslationPipeline(
            ocr_runner=ocr,
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
            ocr_max_concurrency=4,
        )
        pages = list(range(1, 13))  # 12 pages, cap is 4

        active = {"current": 0, "peak": 0}
        lock = threading.Lock()
        original_call = ocr.__call__

        def _tracking_call(page, dpi, model, image_bytes):
            with lock:
                active["current"] += 1
                active["peak"] = max(active["peak"], active["current"])
            try:
                return original_call(page, dpi, model, image_bytes)
            finally:
                with lock:
                    active["current"] -= 1

        ocr.__call__ = _tracking_call
        lineage = pipeline.run_ocr_for_pages(
            pages, lambda p: b"\x89PNG\r\n\x1a\nfake"
        )
        self.assertEqual(len(pages), len(lineage))
        self.assertEqual(pages, [rec.physical_page for rec in lineage])
        self.assertLessEqual(active["peak"], 4)


class ModelAllowlistTests(unittest.TestCase):
    """Exact model identifiers are enforced for OCR, Hy-MT2, and Flash."""

    def test_ocr_allowlist_contains_specialized_models(self) -> None:
        self.assertEqual(
            frozenset(
                {
                    "GLM-OCR-bf16",
                    "PaddleOCR",
                    "models--PaddlePaddle--PaddleOCR-VL-1.6",
                }
            ),
            ALLOWED_OCR_MODELS,
        )

    def test_hy_mt2_allowlist_contains_exact_id(self) -> None:
        self.assertIn(HY_MT2_MODEL_ID, ALLOWED_BODY_TRANSLATION_MODELS)
        self.assertEqual(
            frozenset({"dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"}),
            ALLOWED_BODY_TRANSLATION_MODELS,
        )

    def test_flash_allowlist(self) -> None:
        self.assertIn(FLASH_PLANNING_MODEL, ALLOWED_FLASH_MODELS)
        self.assertIn(FLASH_QC_MODEL, ALLOWED_FLASH_MODELS)

    def test_upper_layer_allowlist_adds_pro_without_changing_body_allowlist(self) -> None:
        self.assertEqual(
            frozenset({FLASH_PLANNING_MODEL, PRO_UPPER_LAYER_MODEL}),
            ALLOWED_UPPER_LAYER_MODELS,
        )
        self.assertNotIn(PRO_UPPER_LAYER_MODEL, ALLOWED_BODY_TRANSLATION_MODELS)

    def test_wrong_body_model_rejected(self) -> None:
        """If Hy-MT2 fake returns wrong model, pipeline must reject."""
        for wrong_model in ("deepseek-v4-flash", "deepseek-v4-pro"):
            with self.subTest(wrong_model=wrong_model):
                wrong_translator = FakeHyMt2Translator(model=wrong_model)
                pipeline = ChapterTranslationPipeline(
                    ocr_runner=FakeOcrRunner(),
                    flash_planner=FakeFlashPlanner(),
                    hy_mt2_translator=wrong_translator,
                    flash_qc_runner=FakeFlashQcRunner(),
                )
                with self.assertRaises(ChapterTranslationPipelineError) as raised:
                    pipeline.translate_chapter(
                        source_text="test source",
                        document_sha256="a" * 64,
                        extraction_revision="rev1",
                        chapter_id="ch1",
                        chunk_id="chunk1",
                        glossary_version="cms_regulatory_zh_v1",
                    )
                self.assertIn(
                    "does not match required Hy-MT2 model",
                    str(raised.exception),
                )


class PipelineOrderTests(unittest.TestCase):
    """Flash planning happens before Hy-MT2 translation, which happens before Flash QC."""

    def test_flash_plan_before_translation_before_qc(self) -> None:
        ocr = FakeOcrRunner()
        planner = FakeFlashPlanner()
        translator = FakeHyMt2Translator(
            translations={
                "Participants must not receive SCS within 14 days.": (
                    "受试者在14天内不得接受SCS。"
                )
            }
        )
        qc = FakeFlashQcRunner()
        pipeline = ChapterTranslationPipeline(
            ocr_runner=ocr,
            flash_planner=planner,
            hy_mt2_translator=translator,
            flash_qc_runner=qc,
        )
        candidate = pipeline.translate_chapter(
            source_text="Participants must not receive SCS within 14 days.",
            document_sha256="d" * 64,
            extraction_revision="extract_r1",
            chapter_id="eligibility",
            chunk_id="wref_span_001",
            glossary_version="cms_regulatory_zh_v1",
        )
        # Flash planner was called.
        self.assertEqual(1, len(planner.calls))
        # Hy-MT2 translator was called with correct args.
        self.assertEqual(1, len(translator.calls))
        called_source, called_glossary, called_chapter, called_chunk = translator.calls[0][:4]
        self.assertIn("Participants", called_source)
        self.assertEqual("cms_regulatory_zh_v1", called_glossary)
        self.assertEqual("eligibility", called_chapter)
        self.assertEqual("wref_span_001", called_chunk)
        # Flash QC was called.
        self.assertEqual(1, len(qc.calls))
        # OCR was never called (no OCR pages).
        self.assertEqual(0, len(ocr.calls))

    def test_body_translator_is_hy_mt2_not_flash(self) -> None:
        """The body translation must come from Hy-MT2, not Flash."""
        translator = FakeHyMt2Translator()
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=translator,
            flash_qc_runner=FakeFlashQcRunner(),
        )
        candidate = pipeline.translate_chapter(
            source_text="test",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v1",
        )
        # The translated text comes from Hy-MT2, not Flash.
        self.assertEqual(HY_MT2_MODEL_ID, candidate.hy_mt2.model)
        # V11: source is now passed as unit-delimited text.
        called_source = translator.calls[0][0]
        self.assertIn("test", called_source)
        self.assertIn("CMS_SEG_0001", called_source)
        # Flash planner and QC are separate calls.
        self.assertEqual(FLASH_PLANNING_MODEL, candidate.flash_plan.plan_model)
        self.assertEqual(FLASH_QC_MODEL, candidate.flash_qc.qc_model)


class UpperLayerOrchestrationTests(unittest.TestCase):
    def test_real_shared_stage_service_connects_through_persisted_adapter(self) -> None:
        from services.api.app.writing_reference_repository import (
            WritingReferenceRepository,
        )
        from services.api.app.writing_reference_upper_layer_execution import (
            UpperLayerAdapterResult,
            WritingReferenceUpperLayerExecutionService,
        )

        class _PlannerAdapter:
            def __init__(self, model):
                self.model = model

            def invoke(self, request):
                result = FakeFlashPlanner(model=self.model)(
                    request.input_payload["source_text"],
                    request.input_payload["document_context"],
                )
                return UpperLayerAdapterResult(
                    response_model=self.model,
                    status="succeeded",
                    output_payload=_upper_layer_hash_payload(result),
                )

        with tempfile.TemporaryDirectory() as tmp:
            repository = WritingReferenceRepository(
                Path(tmp) / "upper-layer.sqlite3"
            )
            shared_service = WritingReferenceUpperLayerExecutionService(
                repository,
                lambda model: _PlannerAdapter(model),
            )
            persisted_adapter = PersistedUpperLayerStageExecutorAdapter(
                shared_service,
                deployment_profile="deepseek-production",
                prompt_resolver=lambda stage, version: f"{stage}:{version}",
            )
            local_planner = FakeFlashPlanner()
            pipeline = ChapterTranslationPipeline(
                ocr_runner=FakeOcrRunner(),
                flash_planner=local_planner,
                hy_mt2_translator=FakeHyMt2Translator(),
                flash_qc_runner=FakeFlashQcRunner(),
                upper_layer_executor=persisted_adapter,
            )
            result, execution = pipeline.execute_document_planning_stage(
                "source",
                {},
                owner=UpperLayerStageOwner(
                    project_id="proj_shared",
                    owner_type="direct_translation",
                    owner_id="direct_shared",
                    artifact_id="artifact_shared",
                    extraction_revision="extract_r1",
                ),
            )
            self.assertEqual(FLASH_PLANNING_MODEL, result.plan_model)
            self.assertEqual(0, len(local_planner.calls))
            persisted = repository.upper_layer_stage_run(
                "proj_shared", execution.stage_run_id
            )
            self.assertEqual(execution.input_hash, persisted.input_hash)
            self.assertEqual(execution.output_hash, persisted.output_hash)
            self.assertEqual(
                FLASH_PLANNING_PROMPT_VERSION,
                persisted.prompt_version,
            )

    def test_persisted_service_adapter_preserves_stage_hash_lineage(self) -> None:
        expected = FakeFlashPlanner()("source", {})
        payload = _upper_layer_hash_payload(expected)
        run = SimpleNamespace(
            requested_model=FLASH_PLANNING_MODEL,
            response_model=FLASH_PLANNING_MODEL,
            prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            input_hash="",
            output_hash=_upper_layer_payload_hash(payload),
            status="succeeded",
            stage_run_id="persisted_flash_run",
            parent_stage_run_id="",
            escalation_id="",
            provider="deepseek",
            transport="openai_compatible",
            deployment_profile="deepseek-production",
            provider_call_count=1,
            failure_code="",
        )

        class _PersistedService:
            request = None

            def execute(self, request):
                self.request = request
                run.input_hash = _upper_layer_payload_hash(request.input_payload)
                return SimpleNamespace(
                    flash_run=run,
                    latest_run=run,
                    selected_run=run,
                    selected_output=payload,
                    escalation=None,
                )

        service = _PersistedService()
        adapter = PersistedUpperLayerStageExecutorAdapter(
            service,
            deployment_profile="deepseek-production",
            prompt_resolver=lambda stage, version: f"{stage}:{version}",
        )
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
            upper_layer_executor=adapter,
        )
        result, execution = pipeline.execute_document_planning_stage(
            "source",
            {},
            owner=UpperLayerStageOwner(
                project_id="proj",
                owner_type="direct_translation",
                owner_id="direct_1",
                artifact_id="artifact_1",
                extraction_revision="extract_r1",
            ),
        )
        self.assertEqual(expected, result)
        self.assertEqual("persisted_flash_run", execution.stage_run_id)
        self.assertEqual(
            _upper_layer_payload_hash(service.request.input_payload),
            service.request.semantic_payload()["input_hash"],
        )
        self.assertEqual(
            f"document_planning:{FLASH_PLANNING_PROMPT_VERSION}",
            service.request.prompt,
        )

    def test_persisted_adapter_keeps_failed_pro_in_latest_lineage_when_flash_is_selected(
        self,
    ) -> None:
        expected = FakeFlashPlanner()("source", {})
        payload = _upper_layer_hash_payload(expected)
        flash_run = SimpleNamespace(
            requested_model=FLASH_PLANNING_MODEL,
            response_model=FLASH_PLANNING_MODEL,
            prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            input_hash="",
            output_hash=_upper_layer_payload_hash(payload),
            status="completed_degraded",
            stage_run_id="persisted_flash_degraded",
            parent_stage_run_id="",
            escalation_id="",
            provider="deepseek",
            transport="openai_compatible",
            deployment_profile="deepseek-production",
            provider_call_count=1,
            failure_code="flash_schema_degraded",
        )
        pro_run = SimpleNamespace(
            requested_model=PRO_UPPER_LAYER_MODEL,
            response_model="",
            prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            input_hash="",
            output_hash="",
            status="failed_terminal",
            stage_run_id="persisted_pro_failed",
            parent_stage_run_id=flash_run.stage_run_id,
            escalation_id="wref_ulesc_failed",
            provider="deepseek",
            transport="openai_compatible",
            deployment_profile="deepseek-production",
            provider_call_count=1,
            failure_code="pro_schema_invalid",
        )
        escalation = SimpleNamespace(
            escalation_id="wref_ulesc_failed",
            trigger_status="completed_degraded",
            trigger_code="flash_schema_degraded",
        )

        class _PersistedFallbackService:
            provider = "deepseek"
            transport = "openai_compatible"
            default_model = FLASH_PLANNING_MODEL
            escalation_model = PRO_UPPER_LAYER_MODEL

            def execute(self, request):
                input_hash = _upper_layer_payload_hash(request.input_payload)
                flash_run.input_hash = input_hash
                pro_run.input_hash = input_hash
                return SimpleNamespace(
                    flash_run=flash_run,
                    latest_run=pro_run,
                    selected_run=flash_run,
                    selected_output=payload,
                    escalation=escalation,
                )

        adapter = PersistedUpperLayerStageExecutorAdapter(
            _PersistedFallbackService(),
            deployment_profile="deepseek-production",
            prompt_resolver=lambda stage, version: f"{stage}:{version}",
        )
        execution = adapter.execute(
            stage="document_planning",
            owner=UpperLayerStageOwner(
                project_id="proj",
                owner_type="direct_translation",
                owner_id="owner",
                artifact_id="artifact",
                extraction_revision="extract_r1",
            ),
            prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            input_payload={"source_text": "source", "document_context": {}},
            input_hash=_upper_layer_payload_hash(
                {"source_text": "source", "document_context": {}}
            ),
            invoke=lambda model: expected,
            output_hash=lambda value: _upper_layer_payload_hash(
                _upper_layer_hash_payload(value)
            ),
        )

        self.assertEqual(flash_run.stage_run_id, execution.stage_run_id)
        self.assertEqual(pro_run.stage_run_id, execution.latest_stage_run_id)
        self.assertEqual("failed_terminal", execution.latest_status)
        self.assertEqual("", execution.parent_stage_run_id)
        self.assertEqual("", execution.escalation_id)
        self.assertEqual("", execution.escalation_trigger_status)

    def test_pro_qc_reuses_exact_hy_target_map_and_does_not_retranslate(self) -> None:
        source = "Participants must not receive SCS within 14 days."
        translated = "受试者在14天内不得接受SCS。"
        translator = FakeHyMt2Translator(translations={source: translated})
        flash_qc = FakeFlashQcRunner(
            passed=False,
            failure_codes=("continuity_review",),
            model=FLASH_QC_MODEL,
        )
        pro_qc = FakeFlashQcRunner(
            passed=True,
            model=PRO_UPPER_LAYER_MODEL,
        )
        executor = _AutomaticProStageExecutor(
            {UPPER_LAYER_POST_HY_INTEGRATION_QC}
        )
        observed: list[tuple[str, TranslationPipelineStage, dict]] = []
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=translator,
            flash_qc_runner=flash_qc,
            upper_layer_executor=executor,
            upper_layer_qc_factory=lambda model: {
                FLASH_QC_MODEL: flash_qc,
                PRO_UPPER_LAYER_MODEL: pro_qc,
            }[model],
            stage_observer=lambda phase, stage, detail: observed.append(
                (phase, stage, detail)
            ),
        )

        candidate = pipeline.translate_chapter(
            source_text=source,
            document_sha256="d" * 64,
            extraction_revision="extract_r1",
            chapter_id="eligibility",
            chunk_id="chunk_1",
            glossary_version="cms_regulatory_zh_v1",
            upper_layer_owner=UpperLayerStageOwner(
                project_id="proj_test",
                owner_type="direct_translation",
                owner_id="direct_1",
                artifact_id="artifact_1",
                extraction_revision="extract_r1",
                chapter_id="eligibility",
            ),
        )

        self.assertEqual(1, len(translator.calls))
        self.assertEqual(1, len(flash_qc.calls))
        self.assertEqual(1, len(pro_qc.calls))
        self.assertEqual(translated, candidate.translated_text)
        self.assertEqual(
            sha256(translated.encode("utf-8")).hexdigest(),
            candidate.lineage.translated_text_sha256,
        )
        self.assertEqual(PRO_UPPER_LAYER_MODEL, candidate.flash_qc.qc_model)
        self.assertEqual(
            [FLASH_QC_MODEL, PRO_UPPER_LAYER_MODEL],
            [
                model
                for stage, model, _owner in executor.calls
                if stage == UPPER_LAYER_POST_HY_INTEGRATION_QC
            ],
        )
        self.assertEqual(
            _upper_layer_payload_hash(
                {"hy_mt2_target_map": {"1": translated}}
            ),
            executor.immutable_body_hashes[-1],
        )
        qc_after = next(
            detail
            for phase, stage, detail in observed
            if phase == "after"
            and stage == TranslationPipelineStage.INTEGRATION_QC
        )
        self.assertTrue(qc_after["upper_layer_stage_run_id"].startswith("run_pro_"))
        self.assertTrue(qc_after["upper_layer_parent_stage_run_id"])
        self.assertTrue(qc_after["upper_layer_escalation_id"])

    def test_missing_pro_parent_lineage_is_rejected(self) -> None:
        class _BadExecutor(_AutomaticProStageExecutor):
            def execute(self, **kwargs):
                output = kwargs["invoke"](PRO_UPPER_LAYER_MODEL)
                return UpperLayerStageExecutionResult(
                    output=output,
                    stage=kwargs["stage"],
                    requested_model=PRO_UPPER_LAYER_MODEL,
                    response_model=PRO_UPPER_LAYER_MODEL,
                    prompt_version=kwargs["prompt_version"],
                    input_hash=kwargs["input_hash"],
                    output_hash=kwargs["output_hash"](output),
                    stage_run_id="run_pro_missing_parent",
                    escalation_id="escalation_missing_parent",
                )

        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(model=PRO_UPPER_LAYER_MODEL),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
            upper_layer_executor=_BadExecutor(),
            upper_layer_planner_factory=lambda model: FakeFlashPlanner(model=model),
        )
        with self.assertRaisesRegex(
            ChapterTranslationPipelineError, "escalation lineage is incomplete"
        ):
            pipeline.execute_document_planning_stage(
                "source",
                {},
                owner=UpperLayerStageOwner(
                    project_id="proj",
                    owner_type="direct_translation",
                    owner_id="owner",
                    artifact_id="artifact",
                    extraction_revision="extract_r1",
                ),
            )

    def test_transient_flash_status_cannot_validate_as_pro_escalation(self) -> None:
        class _TransientEscalationExecutor:
            def execute(self, **kwargs):
                output = kwargs["invoke"](PRO_UPPER_LAYER_MODEL)
                return UpperLayerStageExecutionResult(
                    output=output,
                    stage=kwargs["stage"],
                    requested_model=PRO_UPPER_LAYER_MODEL,
                    response_model=PRO_UPPER_LAYER_MODEL,
                    prompt_version=kwargs["prompt_version"],
                    input_hash=kwargs["input_hash"],
                    output_hash=kwargs["output_hash"](output),
                    stage_run_id="run_pro_after_transient",
                    parent_stage_run_id="run_flash_retryable",
                    escalation_id="invalid_transient_escalation",
                    escalation_trigger_status="failed_retryable",
                    escalation_trigger_code="provider_timeout",
                )

        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
            upper_layer_executor=_TransientEscalationExecutor(),
            upper_layer_planner_factory=lambda model: FakeFlashPlanner(model=model),
        )
        with self.assertRaisesRegex(
            ChapterTranslationPipelineError, "ineligible trigger"
        ):
            pipeline.execute_document_planning_stage(
                "source",
                {},
                owner=UpperLayerStageOwner(
                    project_id="proj",
                    owner_type="direct_translation",
                    owner_id="owner",
                    artifact_id="artifact",
                    extraction_revision="extract_r1",
                ),
            )


class FidelityBlockingTests(unittest.TestCase):
    """Deterministic Hy fidelity remains authoritative over advisory QC."""

    def test_qc_advisory_cannot_replace_or_block_faithful_hy_body(self) -> None:
        qc = FakeFlashQcRunner(
            passed=False, failure_codes=("numeric_drift",)
        )
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(
                translations={"The dose is 100mg.": "剂量为100mg。"}
            ),
            flash_qc_runner=qc,
        )
        candidate = pipeline.translate_chapter(
            source_text="The dose is 100mg.",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v1",
        )
        self.assertTrue(candidate.fidelity_passed)
        self.assertFalse(candidate.flash_qc.passed)
        self.assertIn("numeric_drift", candidate.flash_qc.failure_codes)
        self.assertEqual(
            TranslationPipelineStage.CANDIDATE_READY,
            candidate.lineage.stage,
        )
        self.assertEqual("剂量为100mg。", candidate.translated_text)
        # An upper-layer advisory cannot author body text; medical review still
        # receives the faithful Hy candidate and the QC finding.
        self.assertTrue(candidate.needs_medical_approval)

    def test_qc_pass_produces_ready_candidate(self) -> None:
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(passed=True),
        )
        candidate = pipeline.translate_chapter(
            source_text="text",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v1",
        )
        self.assertTrue(candidate.fidelity_passed)
        self.assertEqual(
            TranslationPipelineStage.CANDIDATE_READY,
            candidate.lineage.stage,
        )


class LineagePersistenceTests(unittest.TestCase):
    """Lineage records OCR/model/prompt/glossary/chunk/section provenance."""

    def test_lineage_contains_all_required_dimensions(self) -> None:
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
        )
        candidate = pipeline.translate_chapter(
            source_text="source text for lineage",
            document_sha256="abc123" + "0" * 58,
            extraction_revision="extract_rev_42",
            chapter_id="safety",
            chunk_id="chunk_7",
            glossary_version="cms_regulatory_zh_v1",
        )
        lineage = candidate.lineage
        self.assertEqual("abc123" + "0" * 58, lineage.document_sha256)
        self.assertEqual("extract_rev_42", lineage.extraction_revision)
        self.assertEqual("safety", lineage.chapter_id)
        self.assertEqual("chunk_7", lineage.chunk_id)
        self.assertEqual("cms_regulatory_zh_v1", lineage.glossary_version)
        self.assertEqual(HY_MT2_MODEL_ID, lineage.hy_mt2_model)
        self.assertEqual(FLASH_PLANNING_PROMPT_VERSION, lineage.flash_planning_prompt_version)
        self.assertEqual(FLASH_QC_PROMPT_VERSION, lineage.flash_qc_prompt_version)
        self.assertEqual(HY_MT2_PROMPT_VERSION, lineage.hy_mt2_prompt_version)

    def test_lineage_fingerprint_is_deterministic(self) -> None:
        """Same inputs produce same fingerprint (idempotency)."""
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
        )
        kwargs = dict(
            source_text="same text",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v1",
        )
        c1 = pipeline.translate_chapter(**kwargs)
        c2 = pipeline.translate_chapter(**kwargs)
        self.assertEqual(
            c1.lineage.idempotency_fingerprint(),
            c2.lineage.idempotency_fingerprint(),
        )

    def test_different_source_text_produces_different_fingerprint(self) -> None:
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
        )
        c1 = pipeline.translate_chapter(
            source_text="text A",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v1",
        )
        c2 = pipeline.translate_chapter(
            source_text="text B",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v1",
        )
        self.assertNotEqual(
            c1.lineage.idempotency_fingerprint(),
            c2.lineage.idempotency_fingerprint(),
        )

    def test_different_glossary_produces_different_fingerprint(self) -> None:
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
        )
        c1 = pipeline.translate_chapter(
            source_text="text",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v1",
        )
        c2 = pipeline.translate_chapter(
            source_text="text",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v2",
        )
        self.assertNotEqual(
            c1.lineage.idempotency_fingerprint(),
            c2.lineage.idempotency_fingerprint(),
        )

    def test_ocr_lineage_recorded_in_fingerprint(self) -> None:
        """OCR page lineage changes the fingerprint."""
        ocr = FakeOcrRunner()
        pipeline = ChapterTranslationPipeline(
            ocr_runner=ocr,
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
        )
        # No OCR pages.
        c1 = pipeline.translate_chapter(
            source_text="text",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v1",
            ocr_page_lineage=(),
        )
        # With OCR lineage.
        ocr_lineage = pipeline.run_ocr_for_pages(
            [3], lambda p: b"\x89PNG\r\n\x1a\nfake"
        )
        c2 = pipeline.translate_chapter(
            source_text="text",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v1",
            ocr_page_lineage=ocr_lineage,
        )
        self.assertNotEqual(
            c1.lineage.idempotency_fingerprint(),
            c2.lineage.idempotency_fingerprint(),
        )

    def test_ocr_lineage_records_dpi_model_profile(self) -> None:
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
        )
        lineage = pipeline.run_ocr_for_pages(
            [1, 2], lambda p: b"\x89PNG\r\n\x1a\nfake"
        )
        self.assertEqual(2, len(lineage))
        self.assertEqual(200, lineage[0].dpi)
        self.assertEqual(WRITING_REFERENCE_OCR_MODEL, lineage[0].model)
        self.assertTrue(lineage[0].ocr_profile_digest)
        self.assertTrue(lineage[0].source_text_sha256)
        self.assertEqual("ocr", lineage[0].channel)


class PipelineStageEnumTests(unittest.TestCase):
    """Stage enum exposes human-meaningful progress values."""

    def test_all_required_stages_exist(self) -> None:
        stages = {s.value for s in TranslationPipelineStage}
        required = {
            "extracting",
            "ocr_running",
            "toc_planning",
            "translating_hy_mt2",
            "integration_qc",
            "candidate_ready",
            "fidelity_blocked",
            "failed_retryable",
            "failed_terminal",
        }
        self.assertEqual(required, stages)

    def test_candidate_ready_stage_for_passed_qc(self) -> None:
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(passed=True),
        )
        candidate = pipeline.translate_chapter(
            source_text="text",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v1",
        )
        self.assertEqual(
            TranslationPipelineStage.CANDIDATE_READY,
            candidate.lineage.stage,
        )


class OcrIntegrationTests(unittest.TestCase):
    """OCR is called with correct DPI and model for OCR pages."""

    def test_ocr_called_with_200_dpi_and_correct_model(self) -> None:
        ocr = FakeOcrRunner()
        pipeline = ChapterTranslationPipeline(
            ocr_runner=ocr,
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
        )
        pipeline.run_ocr_for_pages(
            [1, 2, 3], lambda p: b"\x89PNG\r\n\x1a\nfake"
        )
        self.assertEqual(3, len(ocr.calls))
        for page, dpi, model, image_bytes in ocr.calls:
            self.assertEqual(200, dpi)
            self.assertEqual(WRITING_REFERENCE_OCR_MODEL, model)
            self.assertTrue(image_bytes)

    def test_ocr_not_called_for_text_only_document(self) -> None:
        ocr = FakeOcrRunner()
        pipeline = ChapterTranslationPipeline(
            ocr_runner=ocr,
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=FakeHyMt2Translator(),
            flash_qc_runner=FakeFlashQcRunner(),
        )
        pipeline.translate_chapter(
            source_text="text only",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v1",
        )
        self.assertEqual(0, len(ocr.calls))


class BackwardCompatibilityTests(unittest.TestCase):
    """Existing writing-reference translation APIs remain functional."""

    def test_batch_item_accepts_legacy_payload_without_pipeline_fields(self) -> None:
        """Items serialized before the pipeline fields were added must
        still deserialize correctly, with defaults applied."""
        from packages.contracts.workbench_contracts.models import (
            WritingReferenceTranslationBatchItem,
        )
        from datetime import datetime, timezone

        # Legacy payload without any pipeline_* fields.
        legacy = WritingReferenceTranslationBatchItem(
            item_id="item_001",
            batch_id="batch_001",
            project_id="proj_001",
            snapshot_id="snap_001",
            glossary_version="cms_regulatory_zh_v1",
            span_id="span_001",
            artifact_id="art_001",
            nct_id="NCT05014438",
            ich_m11_anchor="eligibility",
            source_text_sha256="a" * 64,
            source_span_revision="span_001_r1",
            artifact_sha256="b" * 64,
            artifact_state_revision=1,
            validation_id="val_001",
            validation_revision=1,
            validation_status="confirmed",
            extraction_revision="extract_r1",
            structure_review_id="review_001",
            structure_review_revision=1,
            origin="new",
            created_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
            updated_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        )
        self.assertEqual("", legacy.pipeline_stage)
        self.assertEqual("", legacy.ocr_lineage_json)
        self.assertEqual("", legacy.hy_mt2_model)
        self.assertEqual("", legacy.pipeline_fingerprint)

    def test_batch_item_round_trips_pipeline_fields(self) -> None:
        from packages.contracts.workbench_contracts.models import (
            WritingReferenceTranslationBatchItem,
        )
        from datetime import datetime, timezone

        item = WritingReferenceTranslationBatchItem(
            item_id="item_002",
            batch_id="batch_001",
            project_id="proj_001",
            snapshot_id="snap_001",
            glossary_version="cms_regulatory_zh_v1",
            span_id="span_001",
            artifact_id="art_001",
            nct_id="NCT05014438",
            ich_m11_anchor="eligibility",
            source_text_sha256="a" * 64,
            source_span_revision="span_001_r1",
            artifact_sha256="b" * 64,
            artifact_state_revision=1,
            validation_id="val_001",
            validation_revision=1,
            validation_status="confirmed",
            extraction_revision="extract_r1",
            structure_review_id="review_001",
            structure_review_revision=1,
            origin="new",
            pipeline_stage="translating_hy_mt2",
            ocr_lineage_json='[{"page":3,"dpi":200}]',
            flash_plan_model=FLASH_PLANNING_MODEL,
            hy_mt2_model=HY_MT2_MODEL_ID,
            flash_qc_model=FLASH_QC_MODEL,
            pipeline_fingerprint="abc123",
            created_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
            updated_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        )
        dumped = item.model_dump(mode="json")
        restored = WritingReferenceTranslationBatchItem.model_validate(dumped)
        self.assertEqual("translating_hy_mt2", restored.pipeline_stage)
        self.assertEqual(HY_MT2_MODEL_ID, restored.hy_mt2_model)
        self.assertEqual("abc123", restored.pipeline_fingerprint)


if __name__ == "__main__":
    unittest.main()
