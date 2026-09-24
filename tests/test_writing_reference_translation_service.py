from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from packages.contracts.workbench_contracts import (
    AiTaskArtifact,
    WritingReferenceDocumentArtifact,
    WritingReferenceDocumentValidationCheck,
    WritingReferenceDocumentValidationRecord,
    WritingReferenceExtractedSpan,
    WritingReferenceExtractionResult,
    WritingReferenceTranslationRequest,
    WritingReferenceTranslationRevision,
    WritingReferenceTranslationRevisionRequest,
)
from services.api.app.writing_reference import (
    REGULATORY_TRANSLATION_MODEL_NAME,
    WritingReferenceTranslationService,
    evaluate_translation_fidelity,
)
from services.api.app.writing_reference_repository import (
    WritingReferenceConflictError,
    WritingReferenceRepository,
)
from tests._composite_pipeline_fixture import (
    build_deterministic_pipeline,
)
from tests.test_writing_reference_repository import PROJECT_ID, snapshot


NOW = datetime(2026, 7, 12, 5, 30, tzinfo=timezone.utc)

# Source text seeded into the repository for every test in this module.
SERVICE_TEST_SOURCE_TEXT = "Participants must not receive SCS within 14 days."


class FakeTranslationRunner:
    """Legacy AI task runner fake.

    The composite pipeline now performs translation; the runner is still
    passed positionally to ``WritingReferenceTranslationService`` for audit
    metadata but is not consulted for the body translation path.
    """

    def __init__(self, translated_text: str):
        self.translated_text = translated_text
        self.requests = []
        self.runs = {}

    def get(self, project_id, run_id):
        if run_id not in self.runs:
            raise KeyError(f"{project_id}/{run_id}")
        return self.runs[run_id]

    def submit_internal(self, project_id, request):
        self.requests.append((project_id, request))
        return SimpleNamespace(
            run_id="airun_translation_001",
            status="completed",
            task_type="regulatory_translation_zh",
            prompt_version="regulatory_translation_zh_v0_5",
            schema_version="ai_task_output_v0_1",
            provider="deepseek",
            model_name=REGULATORY_TRANSLATION_MODEL_NAME,
            artifacts=[
                AiTaskArtifact(
                    artifact_id="artifact_translation_001",
                    artifact_type="provider_output",
                    payload={
                        "translation": {
                            "translated_text": self.translated_text,
                            "glossary_version": "cms_regulatory_zh_v1",
                            "rationale": "保留缩写、数字和否定含义。",
                            "evidence_span_ids": ["evidence_001"],
                        }
                    },
                )
            ],
        )


def _build_service(
    repo: WritingReferenceRepository,
    runner: FakeTranslationRunner,
    *,
    translated_text: str | None = None,
):
    """Construct a WritingReferenceTranslationService wired to a deterministic
    composite pipeline that emits ``translated_text`` for the seeded source
    span.  When ``translated_text`` is None, defaults to the runner's value.
    """
    desired = translated_text if translated_text is not None else runner.translated_text
    pipeline, planner, translator, qc = build_deterministic_pipeline(
        translations={SERVICE_TEST_SOURCE_TEXT: desired},
    )
    return (
        WritingReferenceTranslationService(
            repo,
            runner,
            clock=lambda: NOW,
            chapter_pipeline=pipeline,
        ),
        planner,
        translator,
        qc,
    )


class ContractRetryTranslationRunner(FakeTranslationRunner):
    def submit_internal(self, project_id, request):
        self.requests.append((project_id, request))
        if len(self.requests) == 1:
            return SimpleNamespace(
                run_id="airun_translation_failed_contract",
                status="failed",
                validation_errors=[
                    "regulatory translation glossary_version mismatch"
                ],
                artifacts=[],
            )
        return SimpleNamespace(
            run_id="airun_translation_retry_passed",
            status="completed",
            task_type="regulatory_translation_zh",
            prompt_version="regulatory_translation_zh_v0_5",
            schema_version="ai_task_output_v0_1",
            provider="deepseek",
            model_name=REGULATORY_TRANSLATION_MODEL_NAME,
            artifacts=[
                AiTaskArtifact(
                    artifact_id="artifact_translation_retry",
                    artifact_type="provider_output",
                    payload={
                        "translation": {
                            "translated_text": self.translated_text,
                            "glossary_version": "cms_regulatory_zh_v1",
                            "rationale": "仅修正固定合同字段。",
                            "evidence_span_ids": ["evidence_001"],
                        }
                    },
                )
            ],
        )


class ProviderFailureTranslationRunner(FakeTranslationRunner):
    def submit_internal(self, project_id, request):
        self.requests.append((project_id, request))
        return SimpleNamespace(
            run_id="airun_translation_provider_failed",
            status="failed",
            validation_errors=[],
            error_message="provider unavailable",
            artifacts=[],
        )


class WritingReferenceTranslationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = WritingReferenceRepository(Path(self.tmp.name) / "writing_reference.sqlite3")
        self.repo.save_search_snapshot(snapshot(), idempotency_key="search-001")
        artifact = WritingReferenceDocumentArtifact(
            artifact_id="wref_doc_001", project_id=PROJECT_ID,
            snapshot_id="wref_search_001", nct_id="NCT05014438",
            source_document_id="ctgov_NCT05014438_000", document_type="protocol",
            filename="Prot_000.pdf", requested_url="https://clinicaltrials.gov/a.pdf",
            final_url="https://clinicaltrials.gov/a.pdf", content_type="application/pdf",
            actual_size=13, content_sha256="a" * 64, created_by="medical_manager",
            created_at=NOW,
        )
        self.repo.save_document_artifact(artifact, storage_relpath="safe/a.pdf", idempotency_key="artifact-001")
        span = WritingReferenceExtractedSpan(
            span_id="wref_span_001", project_id=PROJECT_ID,
            artifact_id=artifact.artifact_id, extraction_revision="extract_r1",
            physical_page=12, block_index=4,
            source_locator="ctgov:NCT05014438:wref_doc_001:p12:b4",
            ich_m11_anchor="eligibility",
            source_text="Participants must not receive SCS within 14 days.",
            source_text_sha256="b" * 64,
        )
        self.repo.save_extraction(
            WritingReferenceExtractionResult(
                artifact_id=artifact.artifact_id, project_id=PROJECT_ID,
                extraction_revision="extract_r1", parser_name="PyMuPDF",
                parser_version="1.26.5", page_count=20,
                status="pending_visual_and_medical_structure_review", spans=[span],
            ),
            idempotency_key="extract-001",
        )
        self.repo.record_extraction_review(
            project_id=PROJECT_ID,
            artifact_id=artifact.artifact_id,
            extraction_revision="extract_r1",
            decision="approved",
            confirmed_anchor_coverage=["eligibility"],
            unresolved_structure_issues=[],
            comment="已核对抽取页码、章节标题及M11结构映射，可进入监管中文翻译。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="structure-review-001",
        )
        self.repo.save_document_validation(
            WritingReferenceDocumentValidationRecord(
                validation_id="wref_validation_001",
                project_id=PROJECT_ID,
                artifact_id=artifact.artifact_id,
                revision=1,
                status="confirmed",
                document_sha256=artifact.content_sha256,
                extraction_revision="extract_r1",
                source_state_revision=artifact.state_revision,
                expected_context_hash="c" * 64,
                validator_version="content_consistency_v2",
                checks=[
                    WritingReferenceDocumentValidationCheck(
                        check_code="document_type",
                        label="文件类型",
                        expected_value="protocol",
                        observed_value="protocol",
                        outcome="match",
                    )
                ],
                summary="文件内容与当前竞品方案翻译任务一致。",
                actor="system_validator",
                created_at=NOW,
            ),
            expected_revision=0,
            idempotency_key="validation-001",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_independent_ai_translation_is_pinned_fidelity_checked_and_persisted(self) -> None:
        runner = FakeTranslationRunner("受试者在14天内不得接受SCS。")
        service, planner, translator, qc = _build_service(self.repo, runner)
        result = service.translate(
            PROJECT_ID,
            WritingReferenceTranslationRequest(
                span_id="wref_span_001",
                glossary_version="cms_regulatory_zh_v1",
                idempotency_key="translation-001",
            ),
        )
        self.assertEqual("passed", result.fidelity_status)
        self.assertEqual("pending_author_confirmation", result.status)
        self.assertEqual("受试者在14天内不得接受SCS。", result.translated_text)
        # Composite-pipeline contract is pinned on the persisted revision.
        from services.api.app.writing_reference import (
            COMPOSITE_TRANSLATION_BODY_MODEL,
            COMPOSITE_TRANSLATION_CONTRACT_HASH,
            COMPOSITE_TRANSLATION_PROMPT_VERSION,
            COMPOSITE_TRANSLATION_SCHEMA_VERSION,
            COMPOSITE_TRANSLATION_TASK_TYPE,
        )

        self.assertEqual(COMPOSITE_TRANSLATION_TASK_TYPE, result.task_type)
        self.assertEqual(COMPOSITE_TRANSLATION_PROMPT_VERSION, result.prompt_version)
        self.assertEqual(COMPOSITE_TRANSLATION_SCHEMA_VERSION, result.schema_version)
        self.assertEqual(COMPOSITE_TRANSLATION_BODY_MODEL, result.model_name)
        self.assertEqual(COMPOSITE_TRANSLATION_CONTRACT_HASH, result.contract_hash)
        # The pipeline fakes were each invoked exactly once.
        self.assertEqual(1, len(planner.calls))
        self.assertEqual(1, len(translator.calls))
        self.assertEqual(1, len(qc.calls))
        # The rendered glossary contract was forwarded to the body translator
        # (not just the bare glossary version).
        _, body_glossary, _, _ = translator.calls[0][:4]
        self.assertTrue(body_glossary)
        self.assertIn("cms_regulatory_zh", body_glossary)
        replay = service.translate(
            PROJECT_ID,
            WritingReferenceTranslationRequest(
                span_id="wref_span_001",
                glossary_version="cms_regulatory_zh_v1",
                idempotency_key="translation-001",
            ),
        )
        self.assertEqual(result.model_dump(), replay.model_dump())
        # Idempotent replay did not re-invoke the pipeline.
        self.assertEqual(1, len(planner.calls))
        self.assertEqual(1, len(translator.calls))
        self.assertEqual(1, len(qc.calls))

    def test_contract_validation_failure_gets_one_bounded_retry(self) -> None:
        # With the composite pipeline, a contract drift caught by Flash QC is
        # NOT retried silently — the candidate is fidelity_blocked and the
        # legacy runner is never consulted.  This replaces the former
        # single-bounded-retry path, which no longer exists.
        runner = ContractRetryTranslationRunner("受试者在14天内不得接受SCS。")
        # Hy-MT2 produces a drifted body so Flash QC fails it and the
        # deterministic fidelity gate also blocks it.
        pipeline, planner, translator, qc = build_deterministic_pipeline(
            translations={SERVICE_TEST_SOURCE_TEXT: "受试者在7天内接受SCS。"},
        )
        qc.passed = False
        qc.failure_codes = ("numeric_tokens_changed", "negation_signal_missing")
        service = WritingReferenceTranslationService(
            self.repo,
            runner,
            clock=lambda: NOW,
            chapter_pipeline=pipeline,
        )

        result = service.translate(
            PROJECT_ID,
            WritingReferenceTranslationRequest(
                span_id="wref_span_001",
                glossary_version="cms_regulatory_zh_v1",
                idempotency_key="translation-contract-blocked-001",
            ),
        )

        self.assertEqual("blocked", result.fidelity_status)
        self.assertEqual("pending_author_confirmation", result.status)
        self.assertIn(
            "unit_1:numeric_tokens_changed",
            result.fidelity_failure_codes,
        )
        self.assertIn(
            "unit_1:negation_signal_missing",
            result.fidelity_failure_codes,
        )
        # V11 bounded correction: the drifted Hy-MT2 output triggers exactly
        # one corrective retry; the second identical drift stops the chapter
        # as fidelity-blocked before Flash integration is called.
        self.assertEqual(1, len(planner.calls))
        self.assertEqual(2, len(translator.calls))
        self.assertEqual(0, len(qc.calls))
        # The legacy runner was never consulted.
        self.assertEqual(0, len(runner.requests))

    def test_flash_qc_concern_is_advisory_when_hy_fidelity_passes(self) -> None:
        runner = FakeTranslationRunner("受试者在14天内不得接受SCS。")
        pipeline, planner, translator, qc = build_deterministic_pipeline(
            translations={
                SERVICE_TEST_SOURCE_TEXT: "受试者在14天内不得接受SCS。"
            },
        )
        qc.passed = False
        qc.failure_codes = ("chapter_boundary_incoherent",)
        service = WritingReferenceTranslationService(
            self.repo,
            runner,
            clock=lambda: NOW,
            chapter_pipeline=pipeline,
        )

        result = service.translate(
            PROJECT_ID,
            WritingReferenceTranslationRequest(
                span_id="wref_span_001",
                glossary_version="cms_regulatory_zh_v1",
                idempotency_key="translation-qc-blocked-clean-fidelity",
            ),
        )

        self.assertEqual("passed", result.fidelity_status)
        self.assertEqual([], result.fidelity_failure_codes)
        integration = self.repo.chapter_integration_result(
            PROJECT_ID,
            result.document_structure_plan_id,
            result.chapter_id,
        )
        self.assertIsNotNone(integration)
        self.assertEqual("passed", integration.fidelity_status)
        self.assertEqual([], integration.fidelity_failure_codes)
        self.assertIn(
            "flash_qc_advisory:chapter_boundary_incoherent",
            integration.fidelity_advisory_codes,
        )
        self.assertEqual(1, len(planner.calls))
        self.assertEqual(1, len(translator.calls))
        self.assertEqual(1, len(qc.calls))
        self.assertEqual(0, len(runner.requests))

    def test_provider_failure_is_not_blindly_retried(self) -> None:
        # With the composite pipeline, a Hy-MT2 provider failure (RuntimeError)
        # propagates to the caller — the composite path never silently retries
        # or falls back to the legacy Flash-only translator.
        runner = ProviderFailureTranslationRunner("不会被使用")
        pipeline, planner, translator, qc = build_deterministic_pipeline(
            translations={SERVICE_TEST_SOURCE_TEXT: "不会被使用"},
            failures_remaining={"*": 1},
            failure_message="provider unavailable",
        )
        service = WritingReferenceTranslationService(
            self.repo,
            runner,
            clock=lambda: NOW,
            chapter_pipeline=pipeline,
        )

        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            service.translate(
                PROJECT_ID,
                WritingReferenceTranslationRequest(
                    span_id="wref_span_001",
                    glossary_version="cms_regulatory_zh_v1",
                    idempotency_key="translation-provider-failure-001",
                ),
            )

        # The Hy-MT2 body translator was attempted exactly once (no retry),
        # and the Flash QC stage was never reached.
        self.assertEqual(1, len(translator.calls))
        self.assertEqual(0, len(qc.calls))
        # The legacy runner was never consulted.
        self.assertEqual(0, len(runner.requests))

    def test_save_translation_rejects_same_idempotency_key_with_changed_payload(
        self,
    ) -> None:
        runner = FakeTranslationRunner("受试者在14天内不得接受SCS。")
        service, _, _, _ = _build_service(self.repo, runner)
        current = service.translate(
            PROJECT_ID,
            WritingReferenceTranslationRequest(
                span_id="wref_span_001",
                glossary_version="cms_regulatory_zh_v1",
                idempotency_key="translation-seed-for-conflict",
            ),
        )
        with self.repo._connect() as connection:
            row = connection.execute(
                """
                SELECT idempotency_key
                FROM writing_reference_idempotency
                WHERE project_id=? AND operation='save_translation'
                  AND result_id=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (PROJECT_ID, current.translation_id),
            ).fetchone()
        self.assertIsNotNone(row)
        persisted_key = str(row["idempotency_key"])

        with self.assertRaisesRegex(
            WritingReferenceConflictError,
            "idempotency key reused",
        ):
            self.repo.save_translation(
                current.model_copy(update={"translated_text": "被篡改的第二版译文。"}),
                idempotency_key=persisted_key,
            )

    def test_legacy_prompt_contract_is_preserved_but_not_reused_as_current(self) -> None:
        legacy = WritingReferenceTranslationRevision(
            translation_id="wref_translation_legacy_v01",
            project_id=PROJECT_ID,
            span_id="wref_span_001",
            source_span_revision="wref_span_001_r1",
            document_sha256="a" * 64,
            glossary_version="cms_regulatory_zh_v1",
            revision=1,
            translated_text="受试者在14天内不得接受SCS。",
            rationale="历史v0_1候选，仅保留既有记录。",
            fidelity_status="passed",
            ai_run_id="airun_legacy_v01",
            prompt_version="regulatory_translation_zh_v0_1",
            schema_version="ai_task_output_v0_1",
            provider="buddy",
            model_name="deepseek-v4-pro",
            created_at=NOW,
        )
        self.repo.save_translation(
            legacy,
            idempotency_key="translation-legacy-v01-save",
        )
        runner = FakeTranslationRunner("受试者在14天内不得接受SCS。")
        service, planner, translator, qc = _build_service(self.repo, runner)
        current = service.translate(
            PROJECT_ID,
            WritingReferenceTranslationRequest(
                span_id="wref_span_001",
                glossary_version="cms_regulatory_zh_v1",
                idempotency_key="translation-current-contract",
            ),
        )

        self.assertNotEqual(legacy.translation_id, current.translation_id)
        # The current contract is the composite pipeline, not the legacy
        # regulatory_translation_zh_v0_5 prompt.
        from services.api.app.writing_reference import (
            COMPOSITE_TRANSLATION_PROMPT_VERSION,
        )

        self.assertEqual(COMPOSITE_TRANSLATION_PROMPT_VERSION, current.prompt_version)
        # The composite pipeline ran exactly once for the new candidate.
        self.assertEqual(1, len(translator.calls))
        self.assertEqual(2, len(self.repo.translations(PROJECT_ID, "wref_span_001")))

    def test_historical_pro_run_is_not_reused_after_flash_contract_switch(self) -> None:
        historical = WritingReferenceTranslationRevision(
            translation_id="wref_translation_historical_v03",
            project_id=PROJECT_ID,
            span_id="wref_span_001",
            source_span_revision="wref_span_001_r1",
            document_sha256="a" * 64,
            glossary_version="cms_regulatory_zh_v1",
            revision=1,
            translated_text="受试者在14天内不得接受SCS。",
            rationale="升级前生成的当前提示词候选。",
            fidelity_status="passed",
            ai_run_id="airun_historical_v03",
            created_at=NOW,
        )
        self.repo.save_translation(
            historical,
            idempotency_key="translation-historical-v03-save",
        )
        runner = FakeTranslationRunner("受试者在14天内不得接受SCS。")
        runner.runs[historical.ai_run_id] = SimpleNamespace(
            task_type="regulatory_translation_zh",
            prompt_version="regulatory_translation_zh_v0_3",
            schema_version="ai_task_output_v0_1",
            provider="buddy",
            model_name="deepseek-v4-pro",
        )

        replay = WritingReferenceTranslationService(
            self.repo,
            runner,
            clock=lambda: NOW,
            chapter_pipeline=build_deterministic_pipeline(
                translations={SERVICE_TEST_SOURCE_TEXT: "受试者在14天内不得接受SCS。"},
            )[0],
        ).translate(
            PROJECT_ID,
            WritingReferenceTranslationRequest(
                span_id="wref_span_001",
                glossary_version="cms_regulatory_zh_v1",
                idempotency_key="translation-historical-v03-reuse",
            ),
        )

        self.assertNotEqual(historical.translation_id, replay.translation_id)
        # The current contract is the composite pipeline, not the legacy
        # regulatory_translation_zh_v0_5 prompt.
        from services.api.app.writing_reference import (
            COMPOSITE_TRANSLATION_BODY_MODEL,
            COMPOSITE_TRANSLATION_PROMPT_VERSION,
        )

        self.assertEqual(COMPOSITE_TRANSLATION_PROMPT_VERSION, replay.prompt_version)
        self.assertEqual(COMPOSITE_TRANSLATION_BODY_MODEL, replay.model_name)
        self.assertTrue(replay.contract_hash)
        # The legacy runner was never consulted for the body translation.
        self.assertEqual(0, len(runner.requests))

    def test_numeric_and_negation_drift_is_saved_as_blocked_not_admissible(self) -> None:
        runner = FakeTranslationRunner("受试者在7天内接受SCS。")
        service, planner, translator, qc = _build_service(
            self.repo, runner, translated_text="受试者在7天内接受SCS。"
        )
        result = service.translate(
            PROJECT_ID,
            WritingReferenceTranslationRequest(
                span_id="wref_span_001",
                glossary_version="cms_regulatory_zh_v1",
                idempotency_key="translation-drift",
            ),
        )
        self.assertEqual("blocked", result.fidelity_status)
        self.assertIn(
            "unit_1:numeric_tokens_changed",
            result.fidelity_failure_codes,
        )
        self.assertIn(
            "unit_1:negation_signal_missing",
            result.fidelity_failure_codes,
        )

    def test_unconfirmed_content_gate_blocks_before_ai_call(self) -> None:
        current = self.repo.document_validation(PROJECT_ID, "wref_doc_001")
        self.repo.save_document_validation(
            current.model_copy(
                update={
                    "validation_id": "wref_validation_mismatch",
                    "revision": 2,
                    "status": "mismatch",
                    "summary": "文件内容角色仍待医学确认。",
                }
            ),
            expected_revision=1,
            idempotency_key="validation-mismatch-before-translation",
        )
        runner = FakeTranslationRunner("不应调用AI。")
        with self.assertRaisesRegex(ValueError, "current and confirmed"):
            WritingReferenceTranslationService(
                self.repo,
                runner,
                clock=lambda: NOW,
            ).translate(
                PROJECT_ID,
                WritingReferenceTranslationRequest(
                    span_id="wref_span_001",
                    glossary_version="cms_regulatory_zh_v1",
                    idempotency_key="translation-content-gate-blocked",
                ),
            )
        self.assertEqual([], runner.requests)

    def test_latest_extraction_requires_matching_validation_and_approved_structure_review(self) -> None:
        source_text = "Participants should complete the Week 16 assessment."
        span = WritingReferenceExtractedSpan(
            span_id="wref_span_002",
            project_id=PROJECT_ID,
            artifact_id="wref_doc_001",
            extraction_revision="extract_r2",
            physical_page=13,
            block_index=1,
            source_locator="ctgov:NCT05014438:wref_doc_001:p13:b1",
            ich_m11_anchor="schedule",
            source_text=source_text,
            source_text_sha256=__import__("hashlib").sha256(source_text.encode()).hexdigest(),
        )
        self.repo.save_extraction(
            WritingReferenceExtractionResult(
                artifact_id="wref_doc_001",
                project_id=PROJECT_ID,
                extraction_revision="extract_r2",
                parser_name="PyMuPDF",
                parser_version="1.26.5",
                page_count=20,
                status="pending_visual_and_medical_structure_review",
                spans=[span],
            ),
            idempotency_key="extract-002",
        )
        current = self.repo.document_validation(PROJECT_ID, "wref_doc_001")
        self.repo.save_document_validation(
            current.model_copy(
                update={
                    "validation_id": "wref_validation_002",
                    "revision": 2,
                    "extraction_revision": "extract_r2",
                    "summary": "文件内容与最新抽取版本一致，待结构审核。",
                }
            ),
            expected_revision=1,
            idempotency_key="validation-002",
        )
        runner = FakeTranslationRunner("不应调用AI。")

        with self.assertRaisesRegex(ValueError, "structure review must be approved"):
            WritingReferenceTranslationService(
                self.repo,
                runner,
                clock=lambda: NOW,
            ).translate(
                PROJECT_ID,
                WritingReferenceTranslationRequest(
                    span_id="wref_span_002",
                    glossary_version="cms_regulatory_zh_v1",
                    idempotency_key="translation-structure-gate-blocked",
                ),
            )

        self.assertEqual([], runner.requests)

    def test_comparison_direction_and_numeric_binding_drift_are_blocked(self) -> None:
        comparison = evaluate_translation_fidelity(
            "Participants with response >=10% are eligible.",
            "应答率≤10%的受试者符合条件。",
        )
        self.assertFalse(comparison.passed)
        self.assertIn("comparison_direction_changed", comparison.failure_codes)

        binding = evaluate_translation_fidelity(
            "The Week 12 response threshold is 60% and the Week 24 threshold is 50%.",
            "第12周应答阈值为50%，第24周应答阈值为60%。",
        )
        self.assertFalse(binding.passed)
        self.assertIn("numeric_tokens_changed", binding.failure_codes)

    def test_returned_translation_is_revised_in_place_and_requires_current_review(self) -> None:
        runner = FakeTranslationRunner("受试者在14天内不得接受SCS。")
        service, planner, translator, qc = _build_service(self.repo, runner)
        first = service.translate(
            PROJECT_ID,
            WritingReferenceTranslationRequest(
                span_id="wref_span_001",
                glossary_version="cms_regulatory_zh_v1",
                idempotency_key="translation-revision-base",
            ),
        )
        review = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=first.translation_id,
            translation_revision=1,
            decision="returned",
            comment="请将时间窗和否定关系置于同一分句，并统一SCS术语。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="translation-returned-review",
        )

        revised = service.revise(
            PROJECT_ID,
            first.translation_id,
            WritingReferenceTranslationRevisionRequest(
                expected_translation_revision=1,
                medical_review_id=review.review_id,
                idempotency_key="translation-revision-002",
            ),
        )

        self.assertEqual(first.translation_id, revised.translation_id)
        self.assertEqual(2, revised.revision)
        self.assertEqual(2, self.repo.translations(PROJECT_ID, "wref_span_001")[0].revision)
        # Document plan is immutable and reused on medical revise — Flash
        # planning runs once.  Body/integration re-run under the review
        # instruction (Hy-MT2 + Flash QC called again).
        self.assertEqual(1, len(planner.calls))
        self.assertGreaterEqual(len(translator.calls), 2)
        self.assertGreaterEqual(len(qc.calls), 2)
        # Medical-review comment is forwarded on the revise body call.
        revise_glossary = translator.calls[-1][1]
        self.assertIn("医学审核意见", revise_glossary)
        with self.assertRaises(KeyError):
            service.revise(
                PROJECT_ID,
                first.translation_id,
                WritingReferenceTranslationRevisionRequest(
                    expected_translation_revision=3,
                    medical_review_id=review.review_id,
                    idempotency_key="translation-revision-stale",
                ),
            )

    def test_stale_returned_review_cannot_create_revision_after_later_approval(self) -> None:
        runner = FakeTranslationRunner("受试者在14天内不得接受SCS。")
        service, planner, translator, qc = _build_service(self.repo, runner)
        first = service.translate(
            PROJECT_ID,
            WritingReferenceTranslationRequest(
                span_id="wref_span_001",
                glossary_version="cms_regulatory_zh_v1",
                idempotency_key="translation-stale-return-base",
            ),
        )
        returned = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=first.translation_id,
            translation_revision=first.revision,
            decision="returned",
            comment="请调整监管中文措辞。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="translation-stale-return-review",
        )
        self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=first.translation_id,
            translation_revision=first.revision,
            decision="approved",
            comment="复核后确认当前译文可接受。",
            actor="medical_director",
            expected_revision=1,
            idempotency_key="translation-later-approval-review",
        )

        with self.assertRaisesRegex(
            WritingReferenceConflictError,
            "no longer current",
        ):
            service.revise(
                PROJECT_ID,
                first.translation_id,
                WritingReferenceTranslationRevisionRequest(
                    expected_translation_revision=first.revision,
                    medical_review_id=returned.review_id,
                    idempotency_key="translation-stale-return-revision",
                ),
            )
        # Only the initial translate ran through the pipeline; the stale
        # revision was rejected before any pipeline call.
        self.assertEqual(1, len(translator.calls))
        self.assertEqual(
            1,
            self.repo.translations(PROJECT_ID, "wref_span_001")[0].revision,
        )


if __name__ == "__main__":
    unittest.main()


def test_fidelity_accepts_chinese_magnitude_scaled_numerals():
    """0924V2 §5: "116 million … $635 billion" faithfully renders as
    "1.16亿 … 6350亿" — the magnitude moves into 万/亿 suffixes. The bare
    numeric-token check must not label this as numeric drift (R14 live
    false positive). Real semantic drift (a changed count) still fails."""
    from services.api.app.writing_reference import evaluate_translation_fidelity

    ok = evaluate_translation_fidelity(
        "According to an Institute of Medicine report, 116 million Americans "
        "are affected by chronic pain, at an overall annual cost of $635 "
        "billion (1).",
        "根据美国医学研究所的报告，约有1.16亿美国人受到慢性疼痛的困扰，"
        "由此产生的年度总费用高达6350亿美元(1)。",
    )
    assert "numeric_tokens_changed" not in ok.failure_codes

    drift = evaluate_translation_fidelity(
        "According to an Institute of Medicine report, 116 million Americans "
        "are affected by chronic pain, at an overall annual cost of $635 "
        "billion (1).",
        "根据美国医学研究所的报告，约有2.50亿美国人受到慢性疼痛的困扰，"
        "由此产生的年度总费用高达6350亿美元(1)。",
    )
    assert "numeric_tokens_changed" in drift.failure_codes
