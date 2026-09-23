from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from packages.contracts.workbench_contracts.models import (
    AiTaskArtifact,
    WritingReferenceDocumentArtifact,
    WritingReferenceDocumentValidationRecord,
    WritingReferenceExtractedSpan,
    WritingReferenceExtractionResult,
    WritingReferenceOcrConsistencyQcRecheck,
    WritingReferenceTranslationBatchCreateRequest,
    WritingReferenceTranslationBatchMedicalReviewRequest,
    WritingReferenceTranslationBatchPreviewRequest,
    WritingReferenceTranslationBatchRetryRequest,
    WritingReferenceTranslationDownstreamTransitionRequest,
    WritingReferenceTranslationRequest,
    WritingReferenceTranslationRevision,
    WritingReferenceTranslationRevisionRequest,
)
from services.api.app.main import app
from services.api.app.writing_reference import (
    COMPOSITE_TRANSLATION_BODY_MODEL,
    COMPOSITE_TRANSLATION_CONTRACT_HASH,
    COMPOSITE_TRANSLATION_PROMPT_VERSION,
    COMPOSITE_TRANSLATION_SCHEMA_VERSION,
    COMPOSITE_TRANSLATION_TASK_TYPE,
    REGULATORY_TRANSLATION_MODEL_NAME,
    REGULATORY_TRANSLATION_PROMPT_VERSION,
    REGULATORY_TRANSLATION_SCHEMA_VERSION,
    REGULATORY_TRANSLATION_TASK_TYPE,
    WritingReferenceTranslationService,
)
from services.api.app.writing_reference_repository import (
    TENANT_ID,
    WritingReferenceConflictError,
    WritingReferenceRepository,
    _payload_hash,
)
from services.api.app.writing_reference_translation_batch import (
    TranslationBatchDurableExecutor,
    WritingReferenceTranslationBatchService,
    _document_plan_semantic_alignment_codes,
)
from services.api.app.chapter_translation_pipeline import (
    DocumentPlanValidationError,
    FLASH_PLANNING_MODEL,
    FLASH_QC_MODEL,
    PRO_UPPER_LAYER_MODEL,
    UPPER_LAYER_POST_HY_INTEGRATION_QC,
    UpperLayerStageExecutionResult,
)
from tests._composite_pipeline_fixture import (
    DeterministicFlashQc,
    build_deterministic_pipeline,
    wire_pipeline_calls_to_runner,
)
from tests.test_writing_reference_repository import snapshot


NOW = datetime(2026, 7, 16, 1, 30, tzinfo=timezone.utc)
PROJECT_ID = "proj_rux_03_002"
SNAPSHOT_ID = "wref_search_batch_locked"
NCT_ID = "NCT05014438"
GLOSSARY_VERSION = "cms_regulatory_zh_v1"
OLD_DOWNSTREAM_FINGERPRINT = "a" * 64
OLD_COMPOSITE_CONTRACT_HASH = "b" * 64
OLD_HY_MT2_PROMPT_VERSION = (
    "hy_mt2_chapter_translation_v0_29_reference_metadata_fidelity"
)


class _BatchAutomaticProExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

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
        del immutable_body_hash
        self.calls.append((stage, FLASH_PLANNING_MODEL))
        flash_output = invoke(FLASH_PLANNING_MODEL)
        if stage != UPPER_LAYER_POST_HY_INTEGRATION_QC:
            return UpperLayerStageExecutionResult(
                output=flash_output,
                stage=stage,
                requested_model=FLASH_PLANNING_MODEL,
                response_model=FLASH_PLANNING_MODEL,
                prompt_version=prompt_version,
                input_hash=input_hash,
                output_hash=output_hash(flash_output),
                stage_run_id=f"stage_flash_{owner.owner_id}",
            )
        parent_id = f"stage_flash_{owner.owner_id}"
        self.calls.append((stage, PRO_UPPER_LAYER_MODEL))
        pro_output = invoke(PRO_UPPER_LAYER_MODEL)
        return UpperLayerStageExecutionResult(
            output=pro_output,
            stage=stage,
            requested_model=PRO_UPPER_LAYER_MODEL,
            response_model=PRO_UPPER_LAYER_MODEL,
            prompt_version=prompt_version,
            input_hash=input_hash,
            output_hash=output_hash(pro_output),
            stage_run_id=f"stage_pro_{owner.owner_id}",
            parent_stage_run_id=parent_id,
            escalation_id=f"escalation_{owner.owner_id}",
            escalation_trigger_status="completed_degraded",
            escalation_trigger_code="deterministic_upper_layer_degraded",
        )


class FakeJourneyService:
    def __init__(self) -> None:
        self.states: dict[str, SimpleNamespace] = {}

    def lock(self, project_id: str, snapshot_id: str, retained_ids: list[str]) -> None:
        self.states[project_id] = SimpleNamespace(
            search_plan=SimpleNamespace(latest_snapshot_id=snapshot_id),
            corpus_triage=SimpleNamespace(
                status="finalized",
                snapshot_id=snapshot_id,
                retained_candidate_ids=list(retained_ids),
            ),
        )

    def get(self, project_id: str) -> SimpleNamespace:
        if project_id not in self.states:
            raise KeyError(project_id)
        return self.states[project_id]


class FakePreparationService:
    def __init__(self) -> None:
        self.batches: dict[tuple[str, str], SimpleNamespace] = {}

    def set(
        self,
        project_id: str,
        snapshot_id: str,
        *,
        status: str = "completed",
        batch_id: str = "wref_prep_translation_ready",
        retained_ids: list[str] | None = None,
    ) -> None:
        self.batches[(project_id, snapshot_id)] = SimpleNamespace(
            batch_id=batch_id,
            project_id=project_id,
            snapshot_id=snapshot_id,
            status=status,
            retained_candidate_ids=list(retained_ids or [NCT_ID]),
        )

    def latest(self, project_id: str, snapshot_id: str) -> SimpleNamespace:
        try:
            return self.batches[(project_id, snapshot_id)]
        except KeyError as exc:
            raise KeyError(f"{project_id}/{snapshot_id}") from exc


class FakeTranslationRunner:
    """Legacy AI task runner fake.

    The composite pipeline now performs translation; this runner retains its
    translation/blocked/failure state and ``calls`` list so the deterministic
    pipeline fixture can mirror the legacy behavior and existing batch test
    assertions keep working.
    """

    # Default source-text -> translated-text mapping used by both the legacy
    # runner path and the deterministic composite pipeline fixture.
    TRANSLATIONS: dict[str, str] = {
        "Participants must not receive SCS within 14 days.": "受试者在14天内不得接受SCS。",
        "The primary endpoint is assessed at Week 16.": "主要终点在第16周进行评估。",
        "Participants are eligible.": "受试者符合条件。",
        "The endpoint is assessed.": "对终点进行评估。",
        "The study uses a randomized parallel-group design.": "本研究采用随机平行组设计。",
    }

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failures_remaining: dict[str, int] = {}
        self.failure_message = "simulated fake AI failure"
        self.blocked_spans: set[str] = set()
        self.runs: dict[str, SimpleNamespace] = {}

    def submit_internal(self, project_id: str, request) -> SimpleNamespace:
        span_id = request.allowed_sources[0].source_id
        self.calls.append(span_id)
        if self.failures_remaining.get(span_id, 0) > 0:
            self.failures_remaining[span_id] -= 1
            raise RuntimeError(self.failure_message)
        source_text = request.allowed_sources[0].text_preview
        translated_text = (
            "Participants receive SCS within 7 days."
            if span_id in self.blocked_spans
            else self.TRANSLATIONS.get(source_text, source_text)
        )
        run_id = f"airun_fake_batch_{len(self.calls):03d}"
        run = SimpleNamespace(
            run_id=run_id,
            status="completed",
            task_type=REGULATORY_TRANSLATION_TASK_TYPE,
            prompt_version=REGULATORY_TRANSLATION_PROMPT_VERSION,
            schema_version=REGULATORY_TRANSLATION_SCHEMA_VERSION,
            provider="fake",
            model_name=REGULATORY_TRANSLATION_MODEL_NAME,
            artifacts=[
                AiTaskArtifact(
                    artifact_id=f"artifact_{run_id}",
                    artifact_type="provider_output",
                    payload={
                        "translation": {
                            "translated_text": translated_text,
                            "rationale": "Fake runner preserves the source contract.",
                        }
                    },
                )
            ],
        )
        self.runs[run_id] = run
        return run

    def get(self, project_id: str, run_id: str) -> SimpleNamespace:
        del project_id
        return self.runs[run_id]


class WritingReferenceTranslationBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = WritingReferenceRepository(
            Path(self.tmp.name) / "writing_reference.sqlite3"
        )
        source_snapshot = snapshot().model_copy(
            update={"project_id": PROJECT_ID, "snapshot_id": SNAPSHOT_ID},
            deep=True,
        )
        self.repo.save_search_snapshot(
            source_snapshot,
            idempotency_key="batch-test-search-snapshot",
        )
        self.journeys = FakeJourneyService()
        self.journeys.lock(PROJECT_ID, SNAPSHOT_ID, [NCT_ID])
        self.preparation = FakePreparationService()
        self.preparation.set(PROJECT_ID, SNAPSHOT_ID)
        self.runner = FakeTranslationRunner()
        # Build a deterministic composite pipeline whose Hy-MT2 body
        # translator mirrors the legacy runner's LIVE state (translations,
        # blocked_spans, failures_remaining, failure_message) so existing
        # batch assertions on runner.calls keep working and per-test mutations
        # to blocked_spans / failures_remaining / failure_message are honored.
        self._pipeline, self._planner, self._translator, self._qc = (
            build_deterministic_pipeline()
        )
        self.planner = self._planner
        # Live-link mutable containers by reference so ``runner.blocked_spans``
        # and ``runner.failures_remaining`` mutations are visible to the
        # translator without re-wiring.
        self._translator.translations = self.runner.TRANSLATIONS
        self._translator.blocked_spans = self.runner.blocked_spans
        self._translator.failures_remaining = self.runner.failures_remaining
        self._translator.failure_message_fn = lambda: self.runner.failure_message
        # Reflect the translator's span call list onto runner.calls so legacy
        # batch assertions (``runner.calls == [...]``, ``runner.calls.count``)
        # keep working without touching the legacy runner path.
        wire_pipeline_calls_to_runner(self.runner, self._translator)
        self.translation_service = WritingReferenceTranslationService(
            self.repo,
            self.runner,
            clock=lambda: NOW,
            chapter_pipeline=self._pipeline,
        )
        self.service = self._new_service()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _new_service(self) -> WritingReferenceTranslationBatchService:
        return WritingReferenceTranslationBatchService(
            self.repo,
            self.journeys,
            self.preparation,
            self.translation_service,
            clock=lambda: NOW,
            chapter_pipeline=self._pipeline,
        )

    def _seed_artifact(
        self,
        artifact_id: str,
        spans: list[tuple[str, str, str]],
        *,
        document_type: str = "protocol",
        validation_status: str | None = "confirmed",
        review_decision: str | None = "approved",
        extraction_revision: str = "extract_r1",
        ocr_consistency_qc: dict | None = None,
    ) -> WritingReferenceDocumentArtifact:
        artifact_hash = sha256(artifact_id.encode("utf-8")).hexdigest()
        artifact = WritingReferenceDocumentArtifact(
            artifact_id=artifact_id,
            project_id=PROJECT_ID,
            snapshot_id=SNAPSHOT_ID,
            nct_id=NCT_ID,
            source_document_id=f"source_{artifact_id}",
            document_type=document_type,
            filename=f"{artifact_id}.pdf",
            requested_url=f"https://clinicaltrials.gov/{artifact_id}.pdf",
            final_url=f"https://clinicaltrials.gov/{artifact_id}.pdf",
            content_type="application/pdf",
            actual_size=1024,
            content_sha256=artifact_hash,
            created_by="medical_manager",
            created_at=NOW,
        )
        self.repo.save_document_artifact(
            artifact,
            storage_relpath=f"safe/{artifact_id}.pdf",
            idempotency_key=f"seed-{artifact_id}-artifact",
        )
        extracted_spans = [
            WritingReferenceExtractedSpan(
                span_id=span_id,
                project_id=PROJECT_ID,
                artifact_id=artifact_id,
                extraction_revision=extraction_revision,
                physical_page=index + 1,
                block_index=index,
                source_locator=f"ctgov:{NCT_ID}:{artifact_id}:p{index + 1}:b{index}",
                ich_m11_anchor=anchor,
                source_text=text,
                source_text_sha256=sha256(text.encode("utf-8")).hexdigest(),
            )
            for index, (span_id, anchor, text) in enumerate(spans)
        ]
        self.repo.save_extraction(
            WritingReferenceExtractionResult(
                artifact_id=artifact_id,
                project_id=PROJECT_ID,
                extraction_revision=extraction_revision,
                parser_name="fake_parser",
                parser_version="1",
                page_count=max(1, len(spans)),
                status="pending_visual_and_medical_structure_review",
                ocr_consistency_qc=ocr_consistency_qc or {},
                spans=extracted_spans,
            ),
            idempotency_key=f"seed-{artifact_id}-{extraction_revision}",
        )
        if validation_status is not None:
            self.repo.save_document_validation(
                WritingReferenceDocumentValidationRecord(
                    validation_id=f"validation_{artifact_id}",
                    project_id=PROJECT_ID,
                    artifact_id=artifact_id,
                    revision=1,
                    status=validation_status,
                    document_sha256=artifact_hash,
                    extraction_revision=extraction_revision,
                    source_state_revision=1,
                    summary="Current file content was confirmed for fake-AI testing.",
                    actor="medical_manager",
                    created_at=NOW,
                ),
                expected_revision=0,
                idempotency_key=f"seed-{artifact_id}-validation",
            )
        if review_decision is not None:
            self.repo.record_extraction_review(
                project_id=PROJECT_ID,
                artifact_id=artifact_id,
                extraction_revision=extraction_revision,
                decision=review_decision,
                confirmed_anchor_coverage=sorted(
                    {anchor for _, anchor, _ in spans if anchor != "unmapped"}
                ),
                unresolved_structure_issues=(
                    [] if review_decision == "approved" else ["mapping needs review"]
                ),
                comment="Fake medical structure review for translation batch testing.",
                actor="medical_manager",
                expected_revision=0,
                idempotency_key=f"seed-{artifact_id}-structure-review",
            )
        return artifact

    def test_standalone_sap_is_excluded_from_protocol_corpus_scope(self) -> None:
        self._seed_artifact(
            "artifact_standalone_sap",
            [
                (
                    "span_sap_analysis",
                    "statistics",
                    "The primary analysis will use a mixed model.",
                )
            ],
            document_type="sap",
        )
        preview = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(
                snapshot_id=SNAPSHOT_ID,
                glossary_version=GLOSSARY_VERSION,
            ),
        )
        self.assertEqual(0, preview.eligible_count)
        self.assertEqual(
            1,
            preview.span_exclusion_reason_counts[
                "standalone_sap_not_corpus_input"
            ],
        )

    def test_combined_file_includes_only_spans_before_explicit_sap_boundary(
        self,
    ) -> None:
        self._seed_artifact(
            "artifact_protocol_sap",
            [
                (
                    "span_protocol_background",
                    "background",
                    "This protocol evaluates treatment in adults.",
                ),
                (
                    "span_protocol_endpoint",
                    "objectives_endpoints",
                    "The primary endpoint is assessed at Week 16.",
                ),
                (
                    "span_sap_cover",
                    "statistics",
                    "STATISTICAL ANALYSIS PLAN\nVersion 1.0",
                ),
                (
                    "span_sap_methods",
                    "statistics",
                    "The analysis population and imputation method are defined.",
                ),
            ],
            document_type="protocol_sap",
        )
        preview = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(
                snapshot_id=SNAPSHOT_ID,
                glossary_version=GLOSSARY_VERSION,
            ),
        )
        self.assertEqual(2, preview.eligible_count)
        self.assertEqual(
            2,
            preview.span_exclusion_reason_counts[
                "sap_section_excluded_from_protocol_corpus"
            ],
        )

    def test_combined_file_without_reliable_boundary_fails_closed(self) -> None:
        self._seed_artifact(
            "artifact_protocol_sap_ambiguous",
            [
                (
                    "span_ambiguous_combined",
                    "statistics",
                    "Analysis methods are described in this document.",
                )
            ],
            document_type="protocol_sap",
        )
        preview = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(
                snapshot_id=SNAPSHOT_ID,
                glossary_version=GLOSSARY_VERSION,
            ),
        )
        self.assertEqual(0, preview.eligible_count)
        self.assertEqual(
            1,
            preview.span_exclusion_reason_counts[
                "combined_protocol_boundary_unresolved"
            ],
        )

    @staticmethod
    def _create_request(
        key: str = "translation-batch-create-001",
        anchors: list[str] | None = None,
    ) -> WritingReferenceTranslationBatchCreateRequest:
        return WritingReferenceTranslationBatchCreateRequest(
            snapshot_id=SNAPSHOT_ID,
            glossary_version=GLOSSARY_VERSION,
            anchor_filter=list(anchors or []),
            actor="medical_manager",
            idempotency_key=key,
        )

    def _r42_like_false_positive_source(
        self,
        *,
        source_text: str = "12. VISIT SCHEDULE",
        translated_text: str = "12. 访视安排",
        key: str = "translation-batch-r42-like-v35",
    ):
        """Create 4 ready + 1 blocked + 15 excluded under a fake old contract."""
        target_span_id = f"span_r42_target_{sha256(key.encode()).hexdigest()[:8]}"
        ready_spans = [
            (
                f"span_r42_ready_{index}_{sha256(key.encode()).hexdigest()[:8]}",
                "schedule",
                f"The assessment occurs at Week {index}.",
            )
            for index in range(1, 5)
        ]
        excluded_spans = [
            (
                f"span_r42_excluded_{index}_{sha256(key.encode()).hexdigest()[:8]}",
                "background",
                f"Background context paragraph {index}.",
            )
            for index in range(1, 16)
        ]
        artifact_id = f"artifact_r42_{sha256(key.encode()).hexdigest()[:10]}"
        self._seed_artifact(
            artifact_id,
            [
                (target_span_id, "schedule", source_text),
                *ready_spans,
                *excluded_spans,
            ],
        )
        self._translator.translations[source_text] = translated_text
        for index in range(1, 5):
            self._translator.translations[
                f"The assessment occurs at Week {index}."
            ] = f"在第{index}周进行评估。"

        from services.api.app import writing_reference as writing_reference_module

        old_stopwords = (
            writing_reference_module._ABBREVIATION_STOPWORDS
            - {"VISIT", "SCHEDULE"}
        )
        with (
            patch(
                "services.api.app.writing_reference._ABBREVIATION_STOPWORDS",
                old_stopwords,
            ),
            patch(
                "services.api.app.writing_reference_translation_batch."
                "TRANSLATION_CONTRACT_FINGERPRINT",
                OLD_DOWNSTREAM_FINGERPRINT,
            ),
            patch(
                "services.api.app.chapter_translation_pipeline."
                "TRANSLATION_CONTRACT_FINGERPRINT",
                OLD_DOWNSTREAM_FINGERPRINT,
            ),
            patch(
                "services.api.app.writing_reference."
                "TRANSLATION_CONTRACT_FINGERPRINT",
                OLD_DOWNSTREAM_FINGERPRINT,
            ),
            patch(
                "services.api.app.writing_reference_translation_batch."
                "COMPOSITE_TRANSLATION_CONTRACT_HASH",
                OLD_COMPOSITE_CONTRACT_HASH,
            ),
            patch(
                "services.api.app.writing_reference_translation_batch."
                "HY_MT2_PROMPT_VERSION",
                OLD_HY_MT2_PROMPT_VERSION,
            ),
            patch(
                "services.api.app.chapter_translation_pipeline."
                "HY_MT2_PROMPT_VERSION",
                OLD_HY_MT2_PROMPT_VERSION,
            ),
            patch(
                "tests._composite_pipeline_fixture.HY_MT2_PROMPT_VERSION",
                OLD_HY_MT2_PROMPT_VERSION,
            ),
        ):
            batch = self.service.create(
                PROJECT_ID,
                self._create_request(
                    key,
                    anchors=["schedule"],
                ),
            )
            self.service.run_pending(
                PROJECT_ID,
                batch.batch_id,
                "deterministic_old_contract_worker",
            )
            batch = self.service.get(PROJECT_ID, batch.batch_id)

        self.assertEqual(4, batch.counts.candidate_ready_count)
        self.assertEqual(1, batch.counts.fidelity_blocked_count)
        self.assertEqual(15, batch.counts.excluded_count)
        target = next(
            item for item in batch.items if item.span_id == target_span_id
        )
        self.assertEqual("fidelity_blocked", target.generation_status)
        self.assertIn(
            "unit_1:source_abbreviation_missing",
            target.fidelity_failure_codes,
        )

        # Match the preserved r42 batch/item attempt boundary in the temporary
        # repository before taking the immutable-source snapshot.
        with self.repo._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE writing_reference_translation_batches
                SET attempt=3
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                """,
                (TENANT_ID, PROJECT_ID, batch.batch_id),
            )
            target_attempt_five = target.model_copy(
                update={"attempt": 5},
                deep=True,
            )
            cursor = self.service._write_item_with(
                connection,
                target_attempt_five,
                expected_status="fidelity_blocked",
                expected_attempt=target.attempt,
            )
            self.assertEqual(1, cursor.rowcount)
            connection.commit()
        batch = self.service.get(PROJECT_ID, batch.batch_id)
        target = next(
            item for item in batch.items if item.span_id == target_span_id
        )
        request = WritingReferenceTranslationDownstreamTransitionRequest(
            actor="medical_manager",
            idempotency_key=f"{key}-transition",
            expected_source_batch_attempt=3,
            expected_source_item_attempt=5,
            expected_source_translation_id=target.translation_id,
            expected_source_translation_revision=target.translation_revision,
            expected_source_ai_run_id=target.ai_run_id,
            expected_source_plan_id=target.document_structure_plan_id,
            expected_source_integration_id=(
                self.repo.current_translation_by_id(
                    PROJECT_ID,
                    target.translation_id,
                ).chapter_integration_result_id
            ),
            expected_source_composite_contract_hash=(
                OLD_COMPOSITE_CONTRACT_HASH
            ),
            expected_source_downstream_fingerprint=(
                OLD_DOWNSTREAM_FINGERPRINT
            ),
            expected_source_hy_mt2_prompt_version=(
                OLD_HY_MT2_PROMPT_VERSION
            ),
            expected_source_failure_code=(
                "unit_1:source_abbreviation_missing"
            ),
        )
        return batch, target, request

    @staticmethod
    def _transition_job(record):
        return SimpleNamespace(
            project_id=PROJECT_ID,
            business_key=record.transition_id,
            payload_json=json.dumps(
                {
                    "batch_id": record.target_batch_id,
                    "actor": "deterministic_transition_worker",
                    "retry": False,
                    "downstream_contract_transition_id": (
                        record.transition_id
                    ),
                    "target_item_id": record.target_item_id,
                },
                sort_keys=True,
            ),
        )

    def test_downstream_transition_is_single_item_new_identity_and_restart_safe(
        self,
    ) -> None:
        source_batch, source_item, request = (
            self._r42_like_false_positive_source()
        )
        immutable_tables = {
            "writing_reference_document_structure_plans": "plan_id",
            "writing_reference_translation_chunks": "chunk_id",
            "writing_reference_chapter_integration_results": "integration_id",
            "writing_reference_composite_pipeline_runs": "run_id",
            "writing_reference_translation_records": "translation_id || ':' || revision",
        }
        with self.repo._connect() as connection:
            source_batch_row_before = dict(
                connection.execute(
                    """
                    SELECT *
                    FROM writing_reference_translation_batches
                    WHERE tenant_id=? AND project_id=? AND batch_id=?
                    """,
                    (TENANT_ID, PROJECT_ID, source_batch.batch_id),
                ).fetchone()
            )
            source_item_rows_before = {
                str(row["item_id"]): str(row["payload_json"])
                for row in connection.execute(
                    """
                    SELECT item_id, payload_json
                    FROM writing_reference_translation_batch_items
                    WHERE tenant_id=? AND project_id=? AND batch_id=?
                    """,
                    (TENANT_ID, PROJECT_ID, source_batch.batch_id),
                ).fetchall()
            }
            immutable_before = {}
            for table, identity_sql in immutable_tables.items():
                immutable_before[table] = {
                    str(row["identity"]): str(row["payload_json"])
                    for row in connection.execute(
                        f"""
                        SELECT {identity_sql} AS identity, payload_json
                        FROM {table}
                        WHERE tenant_id=? AND project_id=?
                        """,
                        (TENANT_ID, PROJECT_ID),
                    ).fetchall()
                }

        record = self.service.create_downstream_contract_transition(
            PROJECT_ID,
            source_batch.batch_id,
            source_item.item_id,
            request,
        )
        replay = self.service.create_downstream_contract_transition(
            PROJECT_ID,
            source_batch.batch_id,
            source_item.item_id,
            request,
        )
        self.assertEqual(record.transition_id, replay.transition_id)
        semantic_replay = self.service.create_downstream_contract_transition(
            PROJECT_ID,
            source_batch.batch_id,
            source_item.item_id,
            request.model_copy(
                update={
                    "idempotency_key": (
                        "translation-batch-r42-like-v35-transition-alias"
                    )
                },
                deep=True,
            ),
        )
        self.assertEqual(record.transition_id, semantic_replay.transition_id)
        target_batch = self.service.get(PROJECT_ID, record.target_batch_id)
        self.assertEqual(1, len(target_batch.items))
        target_item = target_batch.items[0]
        self.assertEqual(record.target_item_id, target_item.item_id)
        self.assertEqual(
            source_item.item_id,
            target_item.downstream_contract_source_item_id,
        )
        self.assertEqual(
            record.target_plan_id,
            target_item.downstream_contract_target_plan_id,
        )
        self.assertNotEqual(
            source_item.document_structure_plan_id,
            record.target_plan_id,
        )
        with self.repo._connect() as connection:
            self.assertEqual(
                1,
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM writing_reference_translation_downstream_transition_records
                    WHERE tenant_id=? AND project_id=?
                    """,
                    (TENANT_ID, PROJECT_ID),
                ).fetchone()[0],
            )
            self.assertEqual(
                1,
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM writing_reference_translation_batches
                    WHERE tenant_id=? AND project_id=? AND batch_id=?
                    """,
                    (TENANT_ID, PROJECT_ID, record.target_batch_id),
                ).fetchone()[0],
            )

        captured_jobs = []

        class _CapturingDurableStore:
            def create_or_reuse(self, durable_request):
                captured_jobs.append(durable_request)
                return SimpleNamespace(job_id="durable_transition_job_001")

        self.service.attach_durable_store(_CapturingDurableStore())
        self.assertEqual(
            "durable_transition_job_001",
            self.service.ensure_reference_translation_job(
                PROJECT_ID,
                record.target_batch_id,
                actor="medical_manager",
            ),
        )
        self.assertEqual(1, len(captured_jobs))
        self.assertEqual(record.transition_id, captured_jobs[0].business_key)
        durable_payload = json.loads(captured_jobs[0].payload_json)
        self.assertEqual(
            record.transition_id,
            durable_payload["downstream_contract_transition_id"],
        )
        self.assertEqual(
            record.target_item_id,
            durable_payload["target_item_id"],
        )

        calls_before_transition = (
            len(self._translator.calls),
            len(self._qc.calls),
            len(self._planner.calls),
        )
        executor = TranslationBatchDurableExecutor(self.service)
        with patch.object(
            self.service,
            "_finish_composite_item",
            return_value=None,
        ):
            interrupted_result = executor.execute(
                self._transition_job(record),
                "claim-transition-1",
                lambda: False,
                lambda *args, **kwargs: True,
            )
        self.assertTrue(interrupted_result.retryable)
        interrupted = self.service.get(
            PROJECT_ID,
            record.target_batch_id,
        ).items[0]
        self.assertEqual("running", interrupted.generation_status)
        calls_after_persisted_output = (
            len(self._translator.calls),
            len(self._qc.calls),
            len(self._planner.calls),
        )
        self.assertEqual(
            (
                calls_before_transition[0] + 1,
                calls_before_transition[1] + 1,
                calls_before_transition[2],
            ),
            calls_after_persisted_output,
        )

        with self.repo._connect() as connection:
            target_counts_before_restart = {
                table: connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {table}
                    WHERE tenant_id=? AND project_id=?
                    """,
                    (TENANT_ID, PROJECT_ID),
                ).fetchone()[0]
                for table in (
                    "writing_reference_document_structure_plans",
                    "writing_reference_translation_chunks",
                    "writing_reference_chapter_integration_results",
                    "writing_reference_composite_pipeline_runs",
                    "writing_reference_translation_records",
                    "writing_reference_translation_downstream_model_call_records",
                )
            }

        restarted_service = self._new_service()
        restarted_executor = TranslationBatchDurableExecutor(
            restarted_service
        )
        completed_result = restarted_executor.execute(
            self._transition_job(record),
            "claim-transition-2",
            lambda: False,
            lambda *args, **kwargs: True,
        )
        self.assertEqual("", completed_result.error)
        completed = restarted_service.get(
            PROJECT_ID,
            record.target_batch_id,
        ).items[0]
        self.assertEqual("candidate_ready", completed.generation_status)
        self.assertEqual("passed", completed.fidelity_status)
        self.assertNotEqual(
            source_item.translation_id,
            completed.translation_id,
        )
        target_translation = self.repo.current_translation_by_id(
            PROJECT_ID,
            completed.translation_id,
        )
        self.assertEqual(
            record.target_plan_id,
            target_translation.document_structure_plan_id,
        )
        self.assertNotEqual(
            request.expected_source_integration_id,
            target_translation.chapter_integration_result_id,
        )
        self.assertEqual(
            calls_after_persisted_output,
            (
                len(self._translator.calls),
                len(self._qc.calls),
                len(self._planner.calls),
            ),
        )

        duplicate_result = restarted_executor.execute(
            self._transition_job(record),
            "claim-transition-3",
            lambda: False,
            lambda *args, **kwargs: True,
        )
        self.assertEqual("", duplicate_result.error)
        self.assertEqual(
            calls_after_persisted_output,
            (
                len(self._translator.calls),
                len(self._qc.calls),
                len(self._planner.calls),
            ),
        )

        with self.repo._connect() as connection:
            target_counts_after_restart = {
                table: connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {table}
                    WHERE tenant_id=? AND project_id=?
                    """,
                    (TENANT_ID, PROJECT_ID),
                ).fetchone()[0]
                for table in target_counts_before_restart
            }
            self.assertEqual(
                target_counts_before_restart,
                target_counts_after_restart,
            )
            call_states = connection.execute(
                """
                SELECT state.status
                FROM writing_reference_translation_downstream_model_call_records AS record
                JOIN writing_reference_translation_downstream_model_call_state AS state
                  ON state.tenant_id=record.tenant_id
                 AND state.project_id=record.project_id
                 AND state.call_id=record.call_id
                WHERE record.tenant_id=? AND record.project_id=?
                  AND record.transition_id=?
                ORDER BY record.stage
                """,
                (TENANT_ID, PROJECT_ID, record.transition_id),
            ).fetchall()
            self.assertEqual(["completed", "completed"], [
                str(row["status"]) for row in call_states
            ])
            source_batch_row_after = dict(
                connection.execute(
                    """
                    SELECT *
                    FROM writing_reference_translation_batches
                    WHERE tenant_id=? AND project_id=? AND batch_id=?
                    """,
                    (TENANT_ID, PROJECT_ID, source_batch.batch_id),
                ).fetchone()
            )
            source_item_rows_after = {
                str(row["item_id"]): str(row["payload_json"])
                for row in connection.execute(
                    """
                    SELECT item_id, payload_json
                    FROM writing_reference_translation_batch_items
                    WHERE tenant_id=? AND project_id=? AND batch_id=?
                    """,
                    (TENANT_ID, PROJECT_ID, source_batch.batch_id),
                ).fetchall()
            }
            self.assertEqual(
                source_batch_row_before,
                source_batch_row_after,
            )
            self.assertEqual(
                source_item_rows_before,
                source_item_rows_after,
            )
            for table, identity_sql in immutable_tables.items():
                current = {
                    str(row["identity"]): str(row["payload_json"])
                    for row in connection.execute(
                        f"""
                        SELECT {identity_sql} AS identity, payload_json
                        FROM {table}
                        WHERE tenant_id=? AND project_id=?
                        """,
                        (TENANT_ID, PROJECT_ID),
                    ).fetchall()
                }
                for identity, payload_json in immutable_before[table].items():
                    self.assertEqual(payload_json, current[identity])

            source_chunk_ids = set(
                immutable_before[
                    "writing_reference_translation_chunks"
                ]
            )
            target_chunk_ids = {
                str(row["chunk_id"])
                for row in connection.execute(
                    """
                    SELECT chunk_id
                    FROM writing_reference_translation_chunks
                    WHERE tenant_id=? AND project_id=? AND plan_id=?
                    """,
                    (TENANT_ID, PROJECT_ID, record.target_plan_id),
                ).fetchall()
            }
            self.assertTrue(target_chunk_ids)
            self.assertTrue(source_chunk_ids.isdisjoint(target_chunk_ids))
        self.assertEqual([], self.repo.verify_audit_chain(PROJECT_ID))

    def test_downstream_transition_unknown_call_outcome_never_repeats_model(
        self,
    ) -> None:
        source_batch, source_item, request = (
            self._r42_like_false_positive_source(
                key="translation-batch-r42-like-v35-unknown",
            )
        )
        record = self.service.create_downstream_contract_transition(
            PROJECT_ID,
            source_batch.batch_id,
            source_item.item_id,
            request,
        )
        self._translator.failures_remaining[source_item.span_id] = 1
        calls_before = len(self._translator.calls)
        executor = TranslationBatchDurableExecutor(self.service)
        first = executor.execute(
            self._transition_job(record),
            "claim-unknown-1",
            lambda: False,
            lambda *args, **kwargs: True,
        )
        self.assertTrue(first.retryable)
        self.assertEqual(calls_before + 1, len(self._translator.calls))

        restarted = TranslationBatchDurableExecutor(self._new_service())
        second = restarted.execute(
            self._transition_job(record),
            "claim-unknown-2",
            lambda: False,
            lambda *args, **kwargs: True,
        )
        self.assertFalse(second.retryable)
        self.assertEqual(
            "model_call_outcome_unknown_after_restart",
            second.error,
        )
        self.assertEqual(calls_before + 1, len(self._translator.calls))
        terminal = self.service.get(
            PROJECT_ID,
            record.target_batch_id,
        ).items[0]
        self.assertEqual("failed_terminal", terminal.generation_status)
        self.assertEqual(
            "model_call_outcome_unknown_after_restart",
            terminal.error_code,
        )

    def test_downstream_transition_takeover_before_intent_commit_calls_model_once(
        self,
    ) -> None:
        source_batch, source_item, request = (
            self._r42_like_false_positive_source(
                key="translation-batch-r42-like-v35-takeover-before-intent",
            )
        )
        record = self.service.create_downstream_contract_transition(
            PROJECT_ID,
            source_batch.batch_id,
            source_item.item_id,
            request,
        )
        calls_before = (
            len(self._translator.calls),
            len(self._qc.calls),
        )
        stale_lost = threading.Event()
        before_intent = threading.Event()
        release_stale = threading.Event()
        paused = False
        original_persist = self.service._persist_pipeline_stage

        def pause_before_intent(item, stage, phase, detail):
            nonlocal paused
            stage_value = stage.value if hasattr(stage, "value") else str(stage)
            if (
                not paused
                and item.downstream_contract_transition_id
                == record.transition_id
                and phase == "before"
                and stage_value == "translating_hy_mt2"
            ):
                paused = True
                before_intent.set()
                if not release_stale.wait(10):
                    raise AssertionError("stale worker barrier timed out")
            return original_persist(item, stage, phase, detail)

        stale_results = []
        stale_executor = TranslationBatchDurableExecutor(self.service)

        def run_stale() -> None:
            stale_results.append(
                stale_executor.execute(
                    self._transition_job(record),
                    "claim-takeover-stale",
                    stale_lost.is_set,
                    lambda *args, **kwargs: True,
                )
            )

        with patch.object(
            self.service,
            "_persist_pipeline_stage",
            side_effect=pause_before_intent,
        ):
            stale_thread = threading.Thread(target=run_stale, daemon=True)
            stale_thread.start()
            self.assertTrue(before_intent.wait(10))
            stale_lost.set()
            replacement = TranslationBatchDurableExecutor(
                self._new_service()
            ).execute(
                self._transition_job(record),
                "claim-takeover-replacement",
                lambda: False,
                lambda *args, **kwargs: True,
            )
            release_stale.set()
            stale_thread.join(10)

        self.assertFalse(stale_thread.is_alive())
        self.assertEqual("", replacement.error)
        self.assertEqual(1, len(stale_results))
        self.assertTrue(stale_results[0].retryable)
        self.assertEqual(
            (calls_before[0] + 1, calls_before[1] + 1),
            (len(self._translator.calls), len(self._qc.calls)),
        )
        with self.repo._connect() as connection:
            hy_rows = connection.execute(
                """
                SELECT state.status
                FROM writing_reference_translation_downstream_model_call_records AS record
                JOIN writing_reference_translation_downstream_model_call_state AS state
                  ON state.tenant_id=record.tenant_id
                 AND state.project_id=record.project_id
                 AND state.call_id=record.call_id
                WHERE record.tenant_id=? AND record.project_id=?
                  AND record.transition_id=?
                  AND record.stage='translating_hy_mt2'
                """,
                (TENANT_ID, PROJECT_ID, record.transition_id),
            ).fetchall()
        self.assertEqual(["completed"], [
            str(row["status"]) for row in hy_rows
        ])

    def test_downstream_transition_takeover_after_intent_commit_fails_closed(
        self,
    ) -> None:
        source_batch, source_item, request = (
            self._r42_like_false_positive_source(
                key="translation-batch-r42-like-v35-takeover-after-intent",
            )
        )
        record = self.service.create_downstream_contract_transition(
            PROJECT_ID,
            source_batch.batch_id,
            source_item.item_id,
            request,
        )
        calls_before = (
            len(self._translator.calls),
            len(self._qc.calls),
        )
        stale_lost = threading.Event()
        intent_committed = threading.Event()
        release_stale = threading.Event()
        paused = False
        original_persist = self.service._persist_pipeline_stage

        def pause_after_intent(item, stage, phase, detail):
            nonlocal paused
            result = original_persist(item, stage, phase, detail)
            stage_value = stage.value if hasattr(stage, "value") else str(stage)
            if (
                not paused
                and item.downstream_contract_transition_id
                == record.transition_id
                and phase == "before"
                and stage_value == "translating_hy_mt2"
            ):
                paused = True
                intent_committed.set()
                if not release_stale.wait(10):
                    raise AssertionError("committed-intent barrier timed out")
            return result

        stale_results = []

        def run_stale() -> None:
            stale_results.append(
                TranslationBatchDurableExecutor(self.service).execute(
                    self._transition_job(record),
                    "claim-intent-stale",
                    stale_lost.is_set,
                    lambda *args, **kwargs: True,
                )
            )

        with patch.object(
            self.service,
            "_persist_pipeline_stage",
            side_effect=pause_after_intent,
        ):
            stale_thread = threading.Thread(target=run_stale, daemon=True)
            stale_thread.start()
            self.assertTrue(intent_committed.wait(10))
            stale_lost.set()
            replacement = TranslationBatchDurableExecutor(
                self._new_service()
            ).execute(
                self._transition_job(record),
                "claim-intent-replacement",
                lambda: False,
                lambda *args, **kwargs: True,
            )
            release_stale.set()
            stale_thread.join(10)

        self.assertFalse(stale_thread.is_alive())
        self.assertFalse(replacement.retryable)
        self.assertEqual(
            "model_call_outcome_unknown_after_restart",
            replacement.error,
        )
        self.assertEqual(1, len(stale_results))
        self.assertTrue(stale_results[0].retryable)
        self.assertEqual(
            calls_before,
            (len(self._translator.calls), len(self._qc.calls)),
        )
        terminal = self.service.get(
            PROJECT_ID,
            record.target_batch_id,
        ).items[0]
        self.assertEqual("failed_terminal", terminal.generation_status)
        self.assertEqual(
            "model_call_outcome_unknown_after_restart",
            terminal.error_code,
        )

    def test_downstream_transition_recovers_persisted_chunk_before_after_observer(
        self,
    ) -> None:
        source_batch, source_item, request = (
            self._r42_like_false_positive_source(
                key="translation-batch-r42-like-v35-recover-chunk",
            )
        )
        record = self.service.create_downstream_contract_transition(
            PROJECT_ID,
            source_batch.batch_id,
            source_item.item_id,
            request,
        )
        calls_before = (
            len(self._translator.calls),
            len(self._qc.calls),
        )
        crashed = False
        original_persist = self.service._persist_pipeline_stage

        def crash_before_hy_after_observer(item, stage, phase, detail):
            nonlocal crashed
            stage_value = stage.value if hasattr(stage, "value") else str(stage)
            if (
                not crashed
                and item.downstream_contract_transition_id
                == record.transition_id
                and phase == "after"
                and stage_value == "translating_hy_mt2"
            ):
                crashed = True
                raise RuntimeError(
                    "simulated interruption after immutable chunk persistence"
                )
            return original_persist(item, stage, phase, detail)

        with patch.object(
            self.service,
            "_persist_pipeline_stage",
            side_effect=crash_before_hy_after_observer,
        ):
            first = TranslationBatchDurableExecutor(self.service).execute(
                self._transition_job(record),
                "claim-recover-chunk-1",
                lambda: False,
                lambda *args, **kwargs: True,
            )
        self.assertTrue(first.retryable)
        self.assertTrue(crashed)
        calls_after_chunk = (
            len(self._translator.calls),
            len(self._qc.calls),
        )
        self.assertEqual(
            (calls_before[0] + 1, calls_before[1]),
            calls_after_chunk,
        )

        completed = TranslationBatchDurableExecutor(
            self._new_service()
        ).execute(
            self._transition_job(record),
            "claim-recover-chunk-2",
            lambda: False,
            lambda *args, **kwargs: True,
        )
        self.assertEqual("", completed.error)
        self.assertEqual(
            (calls_after_chunk[0], calls_after_chunk[1] + 1),
            (len(self._translator.calls), len(self._qc.calls)),
        )
        with self.repo._connect() as connection:
            call_states = connection.execute(
                """
                SELECT state.status
                FROM writing_reference_translation_downstream_model_call_records AS record
                JOIN writing_reference_translation_downstream_model_call_state AS state
                  ON state.tenant_id=record.tenant_id
                 AND state.project_id=record.project_id
                 AND state.call_id=record.call_id
                WHERE record.tenant_id=? AND record.project_id=?
                  AND record.transition_id=?
                ORDER BY record.stage
                """,
                (TENANT_ID, PROJECT_ID, record.transition_id),
            ).fetchall()
        self.assertEqual(["completed", "completed"], [
            str(row["status"]) for row in call_states
        ])

    def test_downstream_transition_pre_dispatch_recovery_and_retry_are_bounded(
        self,
    ) -> None:
        source_batch, source_item, request = (
            self._r42_like_false_positive_source(
                key="translation-batch-r42-like-v35-pre-dispatch-recovery",
            )
        )
        record = self.service.create_downstream_contract_transition(
            PROJECT_ID,
            source_batch.batch_id,
            source_item.item_id,
            request,
        )
        claimed = self.service._claim_item(
            PROJECT_ID,
            record.target_batch_id,
            record.target_item_id,
            {"pending"},
        )
        self.assertIsNotNone(claimed)
        recovered_state = (
            self.service
            .recover_downstream_contract_transition_for_execution(
                PROJECT_ID,
                record.transition_id,
            )
        )
        recovered_item = self.service.get(
            PROJECT_ID,
            record.target_batch_id,
        ).items[0]
        self.assertEqual("failed_retryable", recovered_state.status)
        self.assertEqual(
            "service_restart_interrupted",
            recovered_state.error_code,
        )
        self.assertEqual(
            "service_restart_interrupted",
            recovered_item.error_code,
        )
        with self.assertRaisesRegex(
            ValueError,
            "downstream_contract_transition_child_requires_exact_executor",
        ):
            self.service.retry(
                PROJECT_ID,
                record.target_batch_id,
                WritingReferenceTranslationBatchRetryRequest(
                    actor="medical_manager",
                    idempotency_key="transition-child-ordinary-retry-blocked",
                ),
            )
        self.assertEqual(
            "failed_retryable",
            self.service.get(
                PROJECT_ID,
                record.target_batch_id,
            ).items[0].generation_status,
        )

    def test_downstream_transition_real_abbreviation_preflight_fails_closed(
        self,
    ) -> None:
        source_batch, source_item, request = (
            self._r42_like_false_positive_source(
                source_text="12. VISIT SCHEDULE — ECG",
                key="translation-batch-r42-like-v35-ecg",
            )
        )
        with self.repo._connect() as connection:
            before = {
                "batches": connection.execute(
                    """
                    SELECT COUNT(*) FROM writing_reference_translation_batches
                    WHERE tenant_id=? AND project_id=?
                    """,
                    (TENANT_ID, PROJECT_ID),
                ).fetchone()[0],
                "plans": connection.execute(
                    """
                    SELECT COUNT(*) FROM writing_reference_document_structure_plans
                    WHERE tenant_id=? AND project_id=?
                    """,
                    (TENANT_ID, PROJECT_ID),
                ).fetchone()[0],
            }
        with self.assertRaisesRegex(
            ValueError,
            "downstream_contract_transition_preflight_failed:"
            "unit_1:source_abbreviation_missing",
        ):
            self.service.create_downstream_contract_transition(
                PROJECT_ID,
                source_batch.batch_id,
                source_item.item_id,
                request,
            )
        with self.repo._connect() as connection:
            self.assertEqual(
                0,
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM writing_reference_translation_downstream_transition_records
                    WHERE tenant_id=? AND project_id=?
                    """,
                    (TENANT_ID, PROJECT_ID),
                ).fetchone()[0],
            )
            self.assertEqual(
                before,
                {
                    "batches": connection.execute(
                        """
                        SELECT COUNT(*) FROM writing_reference_translation_batches
                        WHERE tenant_id=? AND project_id=?
                        """,
                        (TENANT_ID, PROJECT_ID),
                    ).fetchone()[0],
                    "plans": connection.execute(
                        """
                        SELECT COUNT(*) FROM writing_reference_document_structure_plans
                        WHERE tenant_id=? AND project_id=?
                        """,
                        (TENANT_ID, PROJECT_ID),
                    ).fetchone()[0],
                },
            )

    def test_downstream_transition_http_contract_is_explicit_single_item(
        self,
    ) -> None:
        route = (
            "/api/projects/{project_id}/medical-writing/references/"
            "translation-batches/{batch_id}/items/{item_id}/"
            "downstream-contract-transition"
        )
        operation = app.openapi()["paths"][route]["post"]
        self.assertIn("202", operation["responses"])
        request_schema = operation["requestBody"]["content"][
            "application/json"
        ]["schema"]
        self.assertEqual(
            "#/components/schemas/"
            "WritingReferenceTranslationDownstreamTransitionRequest",
            request_schema["$ref"],
        )
        response_schema = operation["responses"]["202"]["content"][
            "application/json"
        ]["schema"]
        self.assertEqual(
            "#/components/schemas/"
            "WritingReferenceTranslationDownstreamTransitionResult",
            response_schema["$ref"],
        )

    def test_plan_lookup_never_uses_fingerprint_agnostic_historical_plan(self) -> None:
        self._seed_artifact(
            "artifact_exact_plan_lookup",
            [
                (
                    "span_exact_plan_lookup",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                )
            ],
        )
        batch = self.service.create(
            PROJECT_ID,
            self._create_request("translation-batch-exact-plan-lookup"),
        )
        with patch.object(
            self.repo,
            "any_document_structure_plan",
            side_effect=AssertionError("fingerprint-agnostic plan lookup is forbidden"),
        ):
            self.service.run_pending(
                PROJECT_ID,
                batch.batch_id,
                "medical_manager",
            )

        completed = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("completed", completed.status)
        self.assertEqual("candidate_ready", completed.items[0].generation_status)

    def test_structural_planner_failure_recovers_from_frozen_segments(self) -> None:
        """Only structural planner diagnostics may use the deterministic plan."""
        artifact = self._seed_artifact(
            "artifact_structural_plan_recovery",
            [
                (
                    "span_structural_eligibility",
                    "eligibility",
                    "Adults with chronic spontaneous urticaria may enroll.",
                ),
                (
                    "span_structural_safety",
                    "safety",
                    "Safety assessments are collected through Week 24.",
                ),
            ],
        )
        batch = self.service.create(
            PROJECT_ID,
            self._create_request(
                "translation-batch-structural-plan-recovery",
                anchors=["eligibility", "safety"],
            ),
        )
        item = batch.items[0]
        span = self.repo.source_spans(
            PROJECT_ID,
            artifact.artifact_id,
            extraction_revision="extract_r1",
        )[0]
        with patch.object(
            self.service.chapter_pipeline,
            "execute_document_planning_stage",
            side_effect=DocumentPlanValidationError(
                (
                    "planner_missing_required_boundary",
                    "planner_missing_top_level_boundary_segment_2",
                ),
                source_stage_run_id="stage_structural_attempt_1",
                latest_stage_run_id="stage_structural_retry_2",
            ),
        ):
            plan = self.service._get_or_create_document_plan(
                item,
                artifact,
                span,
                lambda *args, **kwargs: None,
            )
        self.assertEqual("anchor_grouped_structure_fallback", plan.planner_model)
        self.assertIn("planner_structural_retry_exhausted", plan.ambiguity_codes)
        self.assertIn("planner_missing_required_boundary", plan.ambiguity_codes)
        self.assertEqual("stage_structural_retry_2", plan.upper_layer_stage_run_id)
        self.assertGreaterEqual(len(plan.chapters), 2)

    def test_planner_runtime_failure_does_not_use_deterministic_fallback(self) -> None:
        """Provider/runtime failures remain fail-closed for auditability."""
        artifact = self._seed_artifact(
            "artifact_runtime_plan_failure",
            [
                (
                    "span_runtime_eligibility",
                    "eligibility",
                    "Adults with chronic spontaneous urticaria may enroll.",
                ),
                (
                    "span_runtime_safety",
                    "safety",
                    "Safety assessments are collected through Week 24.",
                ),
            ],
        )
        batch = self.service.create(
            PROJECT_ID,
            self._create_request(
                "translation-batch-runtime-plan-failure",
                anchors=["eligibility", "safety"],
            ),
        )
        item = batch.items[0]
        span = self.repo.source_spans(
            PROJECT_ID,
            artifact.artifact_id,
            extraction_revision="extract_r1",
        )[0]
        with patch.object(
            self.service.chapter_pipeline,
            "execute_document_planning_stage",
            side_effect=RuntimeError("provider transport unavailable"),
        ):
            with self.assertRaises(DocumentPlanValidationError) as caught:
                self.service._get_or_create_document_plan(
                    item,
                    artifact,
                    span,
                    lambda *args, **kwargs: None,
                )
        self.assertIn("flash_planner_runtime_failure", caught.exception.codes)
        self.assertFalse(
            any(
                code == "planner_structural_retry_exhausted"
                for code in caught.exception.codes
            )
        )

    def test_structural_retry_without_persisted_parent_is_fresh_and_auditable(self) -> None:
        """A pre-fix structural batch may retry without inventing a stage parent."""
        artifact = self._seed_artifact(
            "artifact_parentless_structural_retry",
            [
                (
                    "span_parentless_eligibility",
                    "eligibility",
                    "Adults with chronic spontaneous urticaria may enroll.",
                ),
                (
                    "span_parentless_safety",
                    "safety",
                    "Safety assessments are collected through Week 24.",
                ),
            ],
        )
        batch = self.service.create(
            PROJECT_ID,
            self._create_request(
                "translation-batch-parentless-structural-retry",
                anchors=["eligibility", "safety"],
            ),
        )
        structural_codes = [
            "flash_planner_structural_failure",
            "planner_missing_required_boundary",
            "planner_missing_top_level_boundary_segment_2",
        ]
        failed_items = [
            item.model_copy(
                update={
                    "generation_status": "failed_retryable",
                    "error_code": "document_plan_failed",
                    "document_plan_failure_codes": structural_codes,
                    "document_plan_failure_source_stage_run_id": "",
                    "document_plan_failure_is_derived": index != 0,
                },
                deep=True,
            )
            for index, item in enumerate(batch.items)
        ]
        with self.repo._connect() as connection:
            prepared = self.service._prepare_document_plan_contract_lineage(
                connection,
                failed_items,
                retry_generation=2,
                created_at=NOW,
                persist_migrations=False,
            )
        self.assertEqual(set(item.item_id for item in failed_items), set(prepared.item_lineage))
        self.assertTrue(
            all(
                lineage["document_plan_retry_generation"] == 0
                and not lineage["document_plan_retry_parent_stage_run_id"]
                and not lineage["document_plan_retry_source_item_id"]
                for lineage in prepared.item_lineage.values()
            )
        )

    def test_unexpected_error_code_without_lineage_retries_as_ordinary(self) -> None:
        """R13: a failed item carrying an unexpected error code with no
        planner lineage used to abort the whole retry as
        "document_plan_contract_source_missing_or_ambiguous". It must route
        through the ordinary fresh-planner recovery path instead."""
        artifact = self._seed_artifact(
            "artifact_unexpected_code_lineage_retry",
            [
                (
                    "span_unexpected_eligibility",
                    "eligibility",
                    "Adults with chronic spontaneous urticaria may enroll.",
                ),
                (
                    "span_unexpected_safety",
                    "safety",
                    "Safety assessments are collected through Week 24.",
                ),
            ],
        )
        batch = self.service.create(
            PROJECT_ID,
            self._create_request(
                "translation-batch-unexpected-code-lineage-retry",
                anchors=["eligibility", "safety"],
            ),
        )
        failed_items = [
            item.model_copy(
                update={
                    "generation_status": "failed_retryable",
                    "error_code": "some_future_unclassified_code",
                    "document_plan_failure_source_stage_run_id": "",
                    "document_plan_failure_is_derived": index != 0,
                },
                deep=True,
            )
            for index, item in enumerate(batch.items)
        ]
        with self.repo._connect() as connection:
            prepared = self.service._prepare_document_plan_contract_lineage(
                connection,
                failed_items,
                retry_generation=2,
                created_at=NOW,
                persist_migrations=False,
            )
        self.assertEqual(set(item.item_id for item in failed_items), set(prepared.item_lineage))

    def test_ambiguous_parents_are_reclassified_not_fatal(self) -> None:
        """R14: several distinct persisted parents used to abort the whole
        retry as document_plan_retry_parent_missing_or_ambiguous (830 items
        stranded with zero translations). The group must reclassify onto the
        parentless structural recovery path instead: all items get lineage,
        exactly one non-derived planner source remains."""
        artifact = self._seed_artifact(
            "artifact_ambiguous_parent_lineage_retry",
            [
                (
                    "span_ambiguous_eligibility",
                    "eligibility",
                    "Adults with chronic spontaneous urticaria may enroll.",
                ),
                (
                    "span_ambiguous_safety",
                    "safety",
                    "Safety assessments are collected through Week 24.",
                ),
            ],
        )
        batch = self.service.create(
            PROJECT_ID,
            self._create_request(
                "translation-batch-ambiguous-parent-lineage-retry",
                anchors=["eligibility", "safety"],
            ),
        )
        parent_ids = ["stage_run_parent_A", "stage_run_parent_B"]
        failed_items = [
            item.model_copy(
                update={
                    "generation_status": "failed_retryable",
                    "error_code": "document_plan_failed",
                    "document_plan_failure_codes": [
                        "document_plan_failed_earlier_in_same_run"
                    ],
                    "document_plan_failure_source_stage_run_id": parent_ids[
                        index % 2
                    ],
                    "document_plan_failure_is_derived": index != 0,
                },
                deep=True,
            )
            for index, item in enumerate(batch.items)
        ]
        with self.repo._connect() as connection:
            prepared = self.service._prepare_document_plan_contract_lineage(
                connection,
                failed_items,
                retry_generation=3,
                created_at=NOW,
                persist_migrations=False,
            )
        self.assertEqual(set(item.item_id for item in failed_items), set(prepared.item_lineage))
        self.assertTrue(
            all(
                lineage["document_plan_retry_generation"] == 0
                and not lineage["document_plan_retry_parent_stage_run_id"]
                for lineage in prepared.item_lineage.values()
            )
        )

    def test_concurrent_integration_winner_drives_translation_lineage(self) -> None:
        self._seed_artifact(
            "artifact_integration_race",
            [
                (
                    "span_integration_race",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                )
            ],
        )
        batch = self.service.create(
            PROJECT_ID,
            self._create_request("translation-batch-integration-race"),
        )
        original_save = self.repo.save_chapter_integration_result
        race_seeded = False

        def save_with_concurrent_winner(result, *, idempotency_key):
            nonlocal race_seeded
            if not race_seeded:
                race_seeded = True
                winner_text = result.integrated_chinese_text
                winner = result.model_copy(
                    update={
                        "integration_id": "integration_concurrent_winner",
                        "integrated_text_sha256": sha256(
                            winner_text.encode("utf-8")
                        ).hexdigest(),
                    },
                    deep=True,
                )
                original_save(
                    winner,
                    idempotency_key=f"{idempotency_key}:concurrent-winner",
                )
            return original_save(result, idempotency_key=idempotency_key)

        with patch.object(
            self.repo,
            "save_chapter_integration_result",
            side_effect=save_with_concurrent_winner,
        ):
            self.service.run_pending(
                PROJECT_ID,
                batch.batch_id,
                "medical_manager",
            )

        completed = self.service.get(PROJECT_ID, batch.batch_id)
        item = completed.items[0]
        persisted = self.repo.translation(
            PROJECT_ID,
            item.translation_id,
            item.translation_revision,
        )
        self.assertEqual(
            "integration_concurrent_winner",
            persisted.chapter_integration_result_id,
        )

    def test_composite_batch_uses_aligned_unit_contract_end_to_end(self) -> None:
        """V11 test 12 (batch half): the batch path uses the same aligned
        contract as the direct path — CMS_SEG markers reach Hy-MT2 and Flash,
        per-unit targets are persisted, the integration carries the current
        translation-contract fingerprint, and no marker reaches the revision.
        """
        from services.api.app.chapter_translation_pipeline import (
            TRANSLATION_CONTRACT_FINGERPRINT,
            contains_unit_markers,
        )

        self._seed_artifact(
            "artifact_aligned_contract",
            [
                (
                    "span_aligned_contract",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                )
            ],
        )
        batch = self.service.create(
            PROJECT_ID, self._create_request("translation-batch-aligned-contract")
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        completed = self.service.get(PROJECT_ID, batch.batch_id)
        item = completed.items[0]
        self.assertEqual("candidate_ready", item.generation_status)
        # Hy-MT2 received stable ASCII unit markers.
        hy_sources = [call[0] for call in self._translator.calls]
        self.assertTrue(any("[[CMS_SEG_0001]]" in src for src in hy_sources))
        # Flash received the aligned marked source/target envelope.
        qc_inputs = [call[0] for call in self._qc.calls]
        self.assertTrue(any("DRAFT_ZH:" in src for src in qc_inputs))
        # Revision text is marker-free.
        persisted = self.repo.translation(
            PROJECT_ID, item.translation_id, item.translation_revision
        )
        self.assertFalse(contains_unit_markers(persisted.translated_text))
        # Per-unit targets are persisted on the chunk record.
        plan_id = persisted.document_structure_plan_id
        chunks = self.repo.translation_chunks_for_plan(PROJECT_ID, plan_id)
        self.assertTrue(chunks)
        self.assertTrue(any(chunk.unit_targets for chunk in chunks))
        # Integration carries the current translation-contract fingerprint.
        integration = self.repo.chapter_integration_result(
            PROJECT_ID,
            plan_id,
            persisted.chapter_id,
            translation_contract_fingerprint=TRANSLATION_CONTRACT_FINGERPRINT,
        )
        self.assertIsNotNone(integration)
        self.assertEqual(
            TRANSLATION_CONTRACT_FINGERPRINT,
            integration.translation_contract_fingerprint,
        )

    def test_time_and_events_schedule_title_matches_schedule_filter(self) -> None:
        plan = SimpleNamespace(
            chapters=[
                SimpleNamespace(
                    chapter_id="ch_schedule",
                    title="8. Time and events schedule and description of assessments",
                    ich_m11_anchor="unmapped",
                )
            ]
        )

        self.assertTrue(
            self.service._chapter_matches_anchor_filter(
                plan,
                "ch_schedule",
                ["schedule"],
            )
        )

    def test_semantically_collapsed_plan_is_detected_before_anchor_gate(self) -> None:
        spans = (
            SimpleNamespace(span_id="s_front", ich_m11_anchor="front_matter"),
            SimpleNamespace(span_id="s_schedule", ich_m11_anchor="schedule"),
            SimpleNamespace(span_id="s_safety", ich_m11_anchor="safety"),
        )
        collapsed = (
            {
                "id": "ch_front",
                "title": "Front matter",
                "ich_m11_anchor": "unmapped",
                "source_span_ids": ["s_front", "s_schedule", "s_safety"],
            },
        )

        codes = _document_plan_semantic_alignment_codes(collapsed, spans)

        self.assertIn(
            "chapter_ch_front_semantic_anchor_mismatch",
            codes,
        )

    def test_semantically_aligned_plan_is_not_rejected(self) -> None:
        spans = (
            SimpleNamespace(span_id="s_population", ich_m11_anchor="eligibility"),
            SimpleNamespace(span_id="s_population_body", ich_m11_anchor="unmapped"),
        )
        aligned = (
            {
                "id": "ch_population",
                "title": "8. Study Population",
                "ich_m11_anchor": "eligibility",
                "source_span_ids": ["s_population", "s_population_body"],
            },
        )

        self.assertEqual(
            (),
            _document_plan_semantic_alignment_codes(aligned, spans),
        )

    def test_pro_integration_reuses_persisted_hy_chunks_and_projects_lineage(self) -> None:
        source = "Participants must not receive SCS within 14 days."
        self._seed_artifact(
            "artifact_upper_layer_pro",
            [("span_upper_layer_pro", "eligibility", source)],
        )
        flash_qc = DeterministicFlashQc(
            model=FLASH_QC_MODEL,
            passed=False,
            failure_codes=("continuity_review",),
        )
        pro_qc = DeterministicFlashQc(model=PRO_UPPER_LAYER_MODEL)
        executor = _BatchAutomaticProExecutor()
        self._pipeline.flash_qc_runner = flash_qc
        self._pipeline.upper_layer_executor = executor
        self._pipeline.upper_layer_qc_factory = lambda model: {
            FLASH_QC_MODEL: flash_qc,
            PRO_UPPER_LAYER_MODEL: pro_qc,
        }[model]

        batch = self.service.create(
            PROJECT_ID,
            self._create_request("translation-batch-upper-layer-pro"),
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")

        completed = self.service.get(PROJECT_ID, batch.batch_id)
        item = completed.items[0]
        self.assertEqual("candidate_ready", item.generation_status)
        self.assertEqual(PRO_UPPER_LAYER_MODEL, item.qc_model)
        self.assertEqual(
            f"stage_pro_{item.item_id}",
            item.latest_upper_layer_stage_run_id,
        )
        self.assertEqual(
            f"escalation_{item.item_id}",
            item.upper_layer_escalation_id,
        )
        self.assertEqual("completed", item.upper_layer_escalation_status)
        self.assertEqual("翻译完成，可核对并使用", item.pipeline_stage_detail)
        self.assertEqual(1, len(self._translator.calls))
        self.assertEqual(1, len(flash_qc.calls))
        self.assertEqual(1, len(pro_qc.calls))

        persisted = self.repo.translation(
            PROJECT_ID, item.translation_id, item.translation_revision
        )
        chunks = self.repo.translation_chunks_for_plan(
            PROJECT_ID, persisted.document_structure_plan_id
        )
        self.assertEqual(1, len(chunks))
        self.assertTrue(chunks[0].unit_targets)
        self.assertEqual(
            self.runner.TRANSLATIONS[source],
            chunks[0].translated_text,
        )
        integration = self.repo.chapter_integration_result(
            PROJECT_ID,
            persisted.document_structure_plan_id,
            persisted.chapter_id,
        )
        self.assertEqual(PRO_UPPER_LAYER_MODEL, integration.flash_model)
        self.assertEqual(
            f"stage_pro_{item.item_id}",
            integration.upper_layer_stage_run_id,
        )
        self.assertTrue(integration.integration_contract_fingerprint)
        self.assertEqual(
            chunks[0].translated_text,
            integration.integrated_chinese_text,
        )

    def test_windowed_integration_does_not_run_unaligned_final_rewrite(self) -> None:
        """Each window is aligned-QC'd exactly once; final assembly is
        deterministic and cannot rewrite the plain chapter a second time.
        """
        source_a = "\n\n".join(["Participants are eligible."] * 70)
        source_b = "\n\n".join(["The endpoint is assessed."] * 70)
        self._seed_artifact(
            "artifact_windowed_alignment",
            [
                ("span_window_a", "eligibility", source_a),
                ("span_window_b", "eligibility", source_b),
            ],
        )
        batch = self.service.create(
            PROJECT_ID, self._create_request("translation-batch-windowed-alignment")
        )
        with patch(
            "services.api.app.writing_reference_translation_batch."
            "INTEGRATION_PROVIDER_INPUT_LIMIT",
            1,
        ):
            self.service.run_pending(
                PROJECT_ID, batch.batch_id, "medical_manager"
            )

        completed = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("candidate_ready", completed.items[0].generation_status)
        persisted = self.repo.translation(
            PROJECT_ID,
            completed.items[0].translation_id,
            completed.items[0].translation_revision,
        )
        integration = self.repo.chapter_integration_result(
            PROJECT_ID,
            persisted.document_structure_plan_id,
            persisted.chapter_id,
        )
        self.assertIsNotNone(integration)
        self.assertTrue(integration.integration_windowed)
        self.assertEqual(2, len(integration.integration_windows))
        self.assertEqual(2, len(integration.chunk_ids))
        self.assertEqual(
            integration.chunk_ids,
            [
                chunk_id
                for window in integration.integration_windows
                for chunk_id in window.chunk_ids
            ],
        )
        self.assertTrue(
            all(len(window.chunk_ids) == 1 for window in integration.integration_windows)
        )
        chapter_chunks = {
            chunk.chunk_id: chunk
            for chunk in self.repo.translation_chunks_for_plan(
                PROJECT_ID, persisted.document_structure_plan_id
            )
            if chunk.chunk_id in integration.chunk_ids
        }
        self.assertEqual(set(integration.chunk_ids), set(chapter_chunks))
        self.assertEqual(
            "\n\n".join(
                chapter_chunks[chunk_id].translated_text
                for chunk_id in integration.chunk_ids
            ),
            integration.integrated_chinese_text,
        )
        # One Flash call per aligned window.  The old unsafe implementation
        # made a third, unmarked full-chapter rewrite call here.
        self.assertEqual(2, len(self._qc.calls))
        self.assertTrue(
            all(
                "[[CMS_SEG_" in translated_text
                and "[[CMS_SEG_" in source_text
                for translated_text, source_text, _ in self._qc.calls
            )
        )
        self.assertTrue(integration.final_envelope_input_hash)
        self.assertEqual(
            integration.integrated_text_sha256,
            integration.final_envelope_output_hash,
        )

    def test_dual_document_gates_and_terminal_preparation_are_required(self) -> None:
        self._seed_artifact(
            "artifact_validation_missing",
            [("span_validation_missing", "eligibility", "Participants are eligible.")],
            validation_status=None,
        )
        self._seed_artifact(
            "artifact_review_missing",
            [("span_review_missing", "endpoints", "The endpoint is assessed.")],
            review_decision=None,
        )
        preview = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(snapshot_id=SNAPSHOT_ID),
        )
        self.assertEqual(0, preview.eligible_count)
        self.assertEqual(1, preview.document_exclusion_reason_counts["validation_missing"])
        self.assertEqual(1, preview.document_exclusion_reason_counts["structure_review_missing"])

        self.preparation.set(PROJECT_ID, SNAPSHOT_ID, status="running")
        with self.assertRaisesRegex(ValueError, "not terminal"):
            self.service.preview(
                PROJECT_ID,
                WritingReferenceTranslationBatchPreviewRequest(
                    snapshot_id=SNAPSHOT_ID
                ),
            )

    def test_missing_preparation_batch_returns_actionable_workflow_error(self) -> None:
        """A locked snapshot before Protocol preparation is a recoverable UI state."""
        self.preparation.batches.pop((PROJECT_ID, SNAPSHOT_ID))
        with self.assertRaisesRegex(ValueError, "start Protocol preparation"):
            self.service.preview(
                PROJECT_ID,
                WritingReferenceTranslationBatchPreviewRequest(
                    snapshot_id=SNAPSHOT_ID
                ),
            )

    def test_document_validation_must_match_latest_extraction_revision(self) -> None:
        artifact = self._seed_artifact(
            "artifact_validation_extraction_stale",
            [("span_extract_r1", "eligibility", "Participants are eligible.")],
        )
        source_text = "The Week 16 assessment is required."
        self.repo.save_extraction(
            WritingReferenceExtractionResult(
                artifact_id=artifact.artifact_id,
                project_id=PROJECT_ID,
                extraction_revision="extract_r2",
                parser_name="fake_parser",
                parser_version="2",
                page_count=1,
                status="pending_visual_and_medical_structure_review",
                spans=[
                    WritingReferenceExtractedSpan(
                        span_id="span_extract_r2",
                        project_id=PROJECT_ID,
                        artifact_id=artifact.artifact_id,
                        extraction_revision="extract_r2",
                        physical_page=1,
                        block_index=0,
                        source_locator=(
                            f"ctgov:{NCT_ID}:{artifact.artifact_id}:p1:b0"
                        ),
                        ich_m11_anchor="schedule",
                        source_text=source_text,
                        source_text_sha256=sha256(source_text.encode("utf-8")).hexdigest(),
                    )
                ],
            ),
            idempotency_key="seed-validation-extraction-stale-r2",
        )

        preview = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(snapshot_id=SNAPSHOT_ID),
        )

        self.assertEqual(0, preview.eligible_count)
        self.assertEqual(
            1,
            preview.document_exclusion_reason_counts["validation_extraction_stale"],
        )

    def test_anchor_filter_and_request_contract_prevent_span_injection(self) -> None:
        self._seed_artifact(
            "artifact_anchor_filter",
            [
                (
                    "span_eligibility",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                ),
                (
                    "span_endpoints",
                    "endpoints",
                    "The primary endpoint is assessed at Week 16.",
                ),
                (
                    "span_endpoints_secondary",
                    "endpoints",
                    "The endpoint is assessed.",
                ),
            ],
        )
        preview = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(
                snapshot_id=SNAPSHOT_ID,
                anchor_filter=["eligibility"],
            ),
        )
        self.assertEqual(1, preview.eligible_count)
        self.assertEqual(2, preview.span_exclusion_reason_counts["anchor_filtered"])
        self.assertEqual(2, preview.excluded_count)
        self.assertEqual(1, len(preview.exclusions))
        self.assertEqual(2, preview.exclusions[0].count)
        self.assertEqual(
            preview.excluded_count,
            sum(item.count for item in preview.exclusions),
        )
        self.assertEqual("eligibility", preview.anchor_summaries[0].ich_m11_anchor)
        with self.assertRaises(ValidationError):
            WritingReferenceTranslationBatchCreateRequest.model_validate(
                {
                    "snapshot_id": SNAPSHOT_ID,
                    "span_ids": ["span_endpoints"],
                    "actor": "medical_manager",
                    "idempotency_key": "injected-span-scope",
                }
            )

    def test_anchor_preview_projects_cached_scope_without_rescanning_documents(self) -> None:
        self._seed_artifact(
            "artifact_preview_cache",
            [
                (
                    "span_cache_eligibility",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                ),
                (
                    "span_cache_endpoints",
                    "endpoints",
                    "The primary endpoint is assessed at Week 16.",
                ),
            ],
        )
        original_source_spans = self.repo.source_spans

        def delayed_source_spans(*args, **kwargs):
            # Make the cold scan observable without asserting a machine-specific
            # absolute latency or sleeping on the cached path.
            time.sleep(0.03)
            return original_source_spans(*args, **kwargs)

        with patch.object(
            self.repo, "source_spans", side_effect=delayed_source_spans
        ) as source_spans:
            cold_started = time.perf_counter()
            unfiltered = self.service.preview(
                PROJECT_ID,
                WritingReferenceTranslationBatchPreviewRequest(
                    snapshot_id=SNAPSHOT_ID,
                    glossary_version=GLOSSARY_VERSION,
                ),
            )
            cold_elapsed = time.perf_counter() - cold_started
            calls_after_cold = source_spans.call_count

            warm_started = time.perf_counter()
            filtered = self.service.preview(
                PROJECT_ID,
                WritingReferenceTranslationBatchPreviewRequest(
                    snapshot_id=SNAPSHOT_ID,
                    glossary_version=GLOSSARY_VERSION,
                    anchor_filter=["eligibility"],
                ),
            )
            warm_elapsed = time.perf_counter() - warm_started

        self.assertEqual(2, unfiltered.eligible_count)
        self.assertEqual(1, filtered.eligible_count)
        self.assertEqual(1, filtered.excluded_count)
        self.assertEqual(calls_after_cold, source_spans.call_count)
        self.assertLess(warm_elapsed, cold_elapsed)

    def test_preview_cache_invalidates_when_validation_lineage_changes(self) -> None:
        artifact = self._seed_artifact(
            "artifact_preview_cache_validation",
            [
                (
                    "span_cache_validation",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                )
            ],
        )
        first = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(snapshot_id=SNAPSHOT_ID),
        )
        self.assertEqual(1, first.eligible_count)
        first_cache_key = self.service._unfiltered_scope_cache_key

        current = self.repo.document_validation(PROJECT_ID, artifact.artifact_id)
        self.repo.save_document_validation(
            current.model_copy(
                update={
                    "validation_id": f"{current.validation_id}_r2",
                    "revision": 2,
                    "status": "needs_review",
                }
            ),
            expected_revision=1,
            idempotency_key="preview-cache-validation-r2",
        )

        second = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(snapshot_id=SNAPSHOT_ID),
        )
        self.assertEqual(0, second.eligible_count)
        self.assertEqual(
            1,
            second.document_exclusion_reason_counts["validation_not_confirmed"],
        )
        self.assertNotEqual(first_cache_key, self.service._unfiltered_scope_cache_key)

    def test_preview_cache_invalidates_when_effective_ocr_lineage_changes(self) -> None:
        qc_payload = {
            "triggered": True,
            "verdict": "review_required",
            "notes": "schedule boundary requires independent review",
        }
        artifact = self._seed_artifact(
            "artifact_preview_cache_ocr",
            [
                (
                    "span_cache_ocr",
                    "schedule",
                    "The primary endpoint is assessed at Week 16.",
                )
            ],
            ocr_consistency_qc=qc_payload,
        )
        extraction_revision = "extract_r1"

        def recheck(revision: int, verdict: str, recheck_id: str):
            return WritingReferenceOcrConsistencyQcRecheck(
                recheck_id=recheck_id,
                project_id=PROJECT_ID,
                artifact_id=artifact.artifact_id,
                extraction_revision=extraction_revision,
                base_qc_identity_hash=_payload_hash(qc_payload),
                stage_version="mixed_ocr_consistency_qc_v2_1",
                schema_version="mixed_ocr_consistency_qc_v2_1",
                provider="deepseek_official",
                model="deepseek-v4-flash",
                prompt_version="mixed_ocr_boundary_v3",
                models=["paddle/PaddleOCR-VL-1.6", "omlx/GLM-OCR-bf16"],
                physical_pages=[1],
                verdict=verdict,
                notes="schedule boundary requires independent review",
                input_hash=("i" * 63) + str(revision),
                output_hash=("o" * 63) + str(revision),
                revision=revision,
                created_at=NOW.replace(minute=revision),
            )

        self.repo.save_ocr_consistency_qc_recheck(
            recheck(1, "pass", "ocr_cache_recheck_r1"),
            expected_revision=0,
            idempotency_key="preview-cache-ocr-r1",
        )
        first = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(snapshot_id=SNAPSHOT_ID),
        )
        self.assertEqual(1, first.eligible_count)
        first_cache_key = self.service._unfiltered_scope_cache_key

        self.repo.save_ocr_consistency_qc_recheck(
            recheck(2, "review_required", "ocr_cache_recheck_r2"),
            expected_revision=1,
            idempotency_key="preview-cache-ocr-r2",
        )
        second = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(snapshot_id=SNAPSHOT_ID),
        )
        self.assertEqual(0, second.eligible_count)
        self.assertEqual(
            1,
            second.document_exclusion_reason_counts[
                "ocr_consistency_pending_confirmation"
            ],
        )
        self.assertNotEqual(first_cache_key, self.service._unfiltered_scope_cache_key)

    def test_batch_contract_rejects_unapproved_metadata_identifiers(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unsupported M11 anchors"):
            WritingReferenceTranslationBatchPreviewRequest(
                snapshot_id=SNAPSHOT_ID,
                anchor_filter=["schedule", "source protocol text"],
            )
        with self.assertRaisesRegex(ValidationError, "approved contract identifier"):
            WritingReferenceTranslationBatchPreviewRequest(
                snapshot_id=SNAPSHOT_ID,
                glossary_version="cms_regulatory_zh_v1 source protocol text",
            )
        with self.assertRaisesRegex(ValidationError, "actor must be an identifier"):
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SNAPSHOT_ID,
                actor="medical manager with source text",
                idempotency_key="translation-batch-invalid-actor",
            )

    def test_retryable_failure_does_not_echo_provider_or_source_text(self) -> None:
        source_text = "Participants must not receive SCS within 14 days."
        self._seed_artifact(
            "artifact_safe_failure_detail",
            [("span_safe_failure_detail", "eligibility", source_text)],
        )
        self.runner.failures_remaining["span_safe_failure_detail"] = 1
        self.runner.failure_message = f"provider echoed prompt: {source_text}"
        batch = self.service.create(
            PROJECT_ID,
            self._create_request("translation-batch-safe-failure-detail"),
        )

        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")

        failed = self.service.get(PROJECT_ID, batch.batch_id).items[0]
        self.assertEqual("failed_retryable", failed.generation_status)
        self.assertEqual("translation_generation_failed", failed.error_code)
        self.assertNotIn("provider echoed", failed.error_detail)
        self.assertNotIn(source_text, failed.error_detail)
        self.assertIn("不回显供应商原始错误", failed.error_detail)

    def test_idempotency_conflict_existing_reuse_and_legacy_contract_regeneration(self) -> None:
        # Separate artifacts so document plans do not mix independent spans:
        # existing/current, legacy Flash-only, and upgraded current each own
        # their own plan identity.
        artifact_existing = self._seed_artifact(
            "artifact_existing",
            [
                (
                    "span_existing",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                ),
            ],
        )
        artifact_legacy = self._seed_artifact(
            "artifact_legacy",
            [
                (
                    "span_legacy",
                    "endpoints",
                    "The primary endpoint is assessed at Week 16.",
                ),
            ],
        )
        artifact_upgrade = self._seed_artifact(
            "artifact_upgrade",
            [
                (
                    "span_upgrade_current",
                    "study_design",
                    "The study uses a randomized parallel-group design.",
                ),
            ],
        )
        existing = self.translation_service.translate(
            PROJECT_ID,
            WritingReferenceTranslationRequest(
                span_id="span_existing",
                glossary_version=GLOSSARY_VERSION,
                idempotency_key="seed-current-contract-translation",
            ),
        )
        legacy = WritingReferenceTranslationRevision(
            translation_id="legacy_translation_id",
            project_id=PROJECT_ID,
            span_id="span_legacy",
            source_span_revision="span_legacy_r1",
            document_sha256=artifact_legacy.content_sha256,
            glossary_version=GLOSSARY_VERSION,
            revision=1,
            translated_text="Legacy candidate.",
            rationale="Old contract without provenance.",
            fidelity_status="passed",
            ai_run_id="legacy_ai_run",
            created_at=NOW,
        )
        self.repo.save_translation(
            legacy,
            idempotency_key="seed-legacy-contract-translation",
        )
        # ``upgraded_current`` models a re-issued composite candidate that
        # carries the current document-plan/chunk/integration lineage and a
        # real composite-run id so the current-contract check reuses it.
        upgraded_current = WritingReferenceTranslationRevision(
            translation_id="upgraded_current_translation_id",
            project_id=PROJECT_ID,
            span_id="span_upgrade_current",
            source_span_revision="span_upgrade_current_r1",
            document_sha256=artifact_upgrade.content_sha256,
            glossary_version=GLOSSARY_VERSION,
            revision=1,
            translated_text="Upgraded current composite candidate.",
            rationale="Re-issued under the composite chapter translation contract.",
            fidelity_status="passed",
            ai_run_id="composite_run_seed_upgraded_current",
            task_type=COMPOSITE_TRANSLATION_TASK_TYPE,
            prompt_version=COMPOSITE_TRANSLATION_PROMPT_VERSION,
            schema_version=COMPOSITE_TRANSLATION_SCHEMA_VERSION,
            provider="composite_pipeline",
            model_name=COMPOSITE_TRANSLATION_BODY_MODEL,
            contract_hash=COMPOSITE_TRANSLATION_CONTRACT_HASH,
            created_at=NOW,
            document_structure_plan_id="docplan_seed_upgrade",
            chapter_id="ch1",
            source_span_ids=["span_upgrade_current"],
            translation_chunk_ids=["chunk_seed_upgrade"],
            chapter_integration_result_id="integration_seed_upgrade",
        )
        self.repo.save_translation(
            upgraded_current,
            idempotency_key="seed-upgraded-current-contract-translation",
        )
        self.runner.runs["composite_run_seed_upgraded_current"] = SimpleNamespace(
            task_type=COMPOSITE_TRANSLATION_TASK_TYPE,
            prompt_version=COMPOSITE_TRANSLATION_PROMPT_VERSION,
            schema_version=COMPOSITE_TRANSLATION_SCHEMA_VERSION,
            model_name=COMPOSITE_TRANSLATION_BODY_MODEL,
        )
        calls_before = list(self.runner.calls)

        preview = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(snapshot_id=SNAPSHOT_ID),
        )
        self.assertEqual(2, preview.existing_candidate_count)
        self.assertEqual(1, preview.eligible_new_count)
        batch = self.service.create(PROJECT_ID, self._create_request())
        by_span = {item.span_id: item for item in batch.items}
        self.assertEqual("existing", by_span["span_existing"].origin)
        self.assertEqual(existing.translation_id, by_span["span_existing"].translation_id)
        self.assertEqual("artifact_existing.pdf", by_span["span_existing"].filename)
        self.assertEqual("protocol", by_span["span_existing"].document_type)
        self.assertEqual("new", by_span["span_legacy"].origin)
        self.assertEqual("existing", by_span["span_upgrade_current"].origin)
        self.assertEqual(
            COMPOSITE_TRANSLATION_CONTRACT_HASH,
            by_span["span_upgrade_current"].contract_hash,
        )
        self.assertEqual(
            COMPOSITE_TRANSLATION_PROMPT_VERSION,
            by_span["span_upgrade_current"].prompt_version,
        )
        self.assertEqual(
            COMPOSITE_TRANSLATION_SCHEMA_VERSION,
            by_span["span_upgrade_current"].schema_version,
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        completed = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("completed", completed.status)
        self.assertEqual(2, completed.counts.reused_count)
        self.assertEqual(calls_before + ["span_legacy"], self.runner.calls)
        regenerated = next(item for item in completed.items if item.span_id == "span_legacy")
        self.assertEqual(COMPOSITE_TRANSLATION_CONTRACT_HASH, regenerated.contract_hash)
        self.assertNotEqual(legacy.translation_id, regenerated.translation_id)

        replay = self.service.create(PROJECT_ID, self._create_request())
        self.assertEqual(completed.batch_id, replay.batch_id)
        with self.assertRaises(WritingReferenceConflictError):
            self.service.create(
                PROJECT_ID,
                self._create_request(
                    key="translation-batch-create-001",
                    anchors=["eligibility"],
                ),
            )

    def test_fidelity_blocked_is_terminal_and_has_no_review_or_admission_side_effect(self) -> None:
        self._seed_artifact(
            "artifact_blocked",
            [
                (
                    "span_blocked",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                )
            ],
        )
        self.runner.blocked_spans.add("span_blocked")
        batch = self.service.create(
            PROJECT_ID, self._create_request("translation-batch-blocked")
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        # The blocked Hy output is only a diagnostic fragment.  It must never
        # be compared with the full chapter because that manufactures
        # chapter-wide omission codes unrelated to the unit-level root cause.
        # The removed flat evaluator is intentionally not patchable here;
        # the persisted codes below must remain unit-localized.
        blocked = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("completed_with_blocked", blocked.status)
        self.assertEqual("fidelity_blocked", blocked.items[0].generation_status)
        self.assertNotIn(
            "no_unit_markers_in_output",
            blocked.items[0].fidelity_failure_codes,
        )
        self.assertTrue(blocked.items[0].fidelity_failure_codes)
        self.assertTrue(
            all(
                code.startswith("unit_1:")
                for code in blocked.items[0].fidelity_failure_codes
            )
        )
        persisted = self.repo.translation(
            PROJECT_ID,
            blocked.items[0].translation_id,
            blocked.items[0].translation_revision,
        )
        integration = self.repo.chapter_integration_result(
            PROJECT_ID,
            persisted.document_structure_plan_id,
            persisted.chapter_id,
        )
        self.assertEqual("", persisted.translated_text)
        self.assertEqual("", integration.integrated_chinese_text)
        self.assertIn(
            "Participants receive SCS within 7 days.",
            integration.blocked_raw_provider_output,
        )
        self.assertEqual([], self.repo.medical_reviews(PROJECT_ID))
        self.assertEqual([], self.repo.evidence_briefs(PROJECT_ID))

        self.service.retry(
            PROJECT_ID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="translation-batch-blocked-retry",
            ),
        )
        self.service.run_failed(PROJECT_ID, batch.batch_id, "medical_manager")
        after_retry = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual(1, after_retry.items[0].attempt)
        # V11 bounded correction: the drifted Hy-MT2 output triggers exactly
        # one corrective retry, then the chapter stops as fidelity-blocked.
        # The blocked terminal state is not re-run by run_failed (it is not a
        # retryable failure).
        self.assertEqual(["span_blocked", "span_blocked"], self.runner.calls)

    def test_partial_failure_retries_only_retryable_item(self) -> None:
        """Chapter-level contract: one failed pending chunk fails the chapter
        items, and retry re-runs only the missing/failed chunk (ok chunk reused).
        """
        self._seed_artifact(
            "artifact_retry",
            [
                (
                    "span_retry_ok",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                ),
                (
                    "span_retry_fail",
                    "endpoints",
                    "The primary endpoint is assessed at Week 16.",
                ),
            ],
        )
        # Force one chapter per span so a failed chunk only blocks its own
        # chapter items (still document-level plan, not per-span planning).
        self.planner.set_chapter_assignments(
            [
                {
                    "id": "ch_ok",
                    "title": "Eligibility",
                    "source_span_ids": ["span_retry_ok"],
                },
                {
                    "id": "ch_fail",
                    "title": "Endpoints",
                    "source_span_ids": ["span_retry_fail"],
                },
            ]
        )
        self.runner.failures_remaining["span_retry_fail"] = 1
        batch = self.service.create(
            PROJECT_ID, self._create_request("translation-batch-partial")
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        partial = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("partial_failure", partial.status)
        by_span = {item.span_id: item for item in partial.items}
        self.assertEqual("candidate_ready", by_span["span_retry_ok"].generation_status)
        self.assertEqual(
            "failed_retryable", by_span["span_retry_fail"].generation_status
        )

        retried = self.service.retry(
            PROJECT_ID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="translation-batch-partial-retry",
            ),
        )
        self.assertEqual("running", retried.status)
        self.service.run_failed(PROJECT_ID, batch.batch_id, "medical_manager")
        completed = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("completed", completed.status)
        by_span = {item.span_id: item for item in completed.items}
        self.assertEqual(1, by_span["span_retry_ok"].attempt)
        self.assertEqual(2, by_span["span_retry_fail"].attempt)
        self.assertEqual(1, self.runner.calls.count("span_retry_ok"))
        self.assertEqual(2, self.runner.calls.count("span_retry_fail"))

    def test_restart_only_recovers_running_and_preserves_pending(self) -> None:
        self._seed_artifact(
            "artifact_restart",
            [
                ("span_restart_running", "eligibility", "Participants are eligible."),
                ("span_restart_pending", "endpoints", "The endpoint is assessed."),
            ],
        )
        batch = self.service.create(
            PROJECT_ID, self._create_request("translation-batch-restart")
        )
        running = next(
            item for item in batch.items if item.span_id == "span_restart_running"
        ).model_copy(
            update={
                "generation_status": "running",
                "attempt": 1,
                "updated_at": NOW,
            },
            deep=True,
        )
        with self.repo._connect() as connection:
            connection.execute(
                """
                UPDATE writing_reference_translation_batch_items
                SET generation_status='running', attempt=1, payload_json=?
                WHERE tenant_id=? AND project_id=? AND item_id=?
                """,
                (
                    json.dumps(
                        running.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "kangzhe_local",
                    PROJECT_ID,
                    running.item_id,
                ),
            )
            connection.execute(
                """
                UPDATE writing_reference_translation_batches
                SET status='running'
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                """,
                ("kangzhe_local", PROJECT_ID, batch.batch_id),
            )

        # Constructor must NOT steal the live running item (Gap 1 fix).
        restarted = self._new_service()
        not_yet_recovered = restarted.get(PROJECT_ID, batch.batch_id)
        by_span_pre = {item.span_id: item for item in not_yet_recovered.items}
        self.assertEqual(
            "running", by_span_pre["span_restart_running"].generation_status
        )
        # Explicit per-batch recovery (as called by the durable executor
        # after claiming the durable job) converts running → failed_retryable.
        restarted.recover_interrupted_items_for_batch(PROJECT_ID, batch.batch_id)
        recovered = restarted.get(PROJECT_ID, batch.batch_id)
        by_span = {item.span_id: item for item in recovered.items}
        self.assertEqual(
            "failed_retryable", by_span["span_restart_running"].generation_status
        )
        self.assertEqual(
            "service_restart_interrupted", by_span["span_restart_running"].error_code
        )
        self.assertEqual("pending", by_span["span_restart_pending"].generation_status)

    def test_stale_lineage_is_terminal_before_fake_ai(self) -> None:
        artifact = self._seed_artifact(
            "artifact_stale",
            [("span_stale_r1", "eligibility", "Participants are eligible.")],
        )
        batch = self.service.create(
            PROJECT_ID, self._create_request("translation-batch-stale")
        )
        new_text = "Participants are eligible after the amendment."
        self.repo.save_extraction(
            WritingReferenceExtractionResult(
                artifact_id=artifact.artifact_id,
                project_id=PROJECT_ID,
                extraction_revision="extract_r2",
                parser_name="fake_parser",
                parser_version="2",
                page_count=1,
                status="pending_visual_and_medical_structure_review",
                spans=[
                    WritingReferenceExtractedSpan(
                        span_id="span_stale_r2",
                        project_id=PROJECT_ID,
                        artifact_id=artifact.artifact_id,
                        extraction_revision="extract_r2",
                        physical_page=1,
                        block_index=0,
                        source_locator="ctgov:stale:p1:b0",
                        ich_m11_anchor="eligibility",
                        source_text=new_text,
                        source_text_sha256=sha256(new_text.encode("utf-8")).hexdigest(),
                    )
                ],
            ),
            idempotency_key="seed-stale-extraction-r2",
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        failed = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("failed", failed.status)
        self.assertEqual("failed_terminal", failed.items[0].generation_status)
        self.assertEqual("stale_lineage", failed.items[0].error_code)
        self.assertEqual([], self.runner.calls)

    def test_ra_zero_preview_is_valid_but_empty_create_is_rejected(self) -> None:
        self._seed_artifact(
            "artifact_ra_unmapped",
            [("span_ra_unmapped", "unmapped", "General protocol narrative.")],
        )
        preview = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(snapshot_id=SNAPSHOT_ID),
        )
        self.assertEqual(0, preview.eligible_count)
        self.assertEqual(1, preview.span_exclusion_reason_counts["unmapped"])
        self.assertEqual(1, preview.excluded_count)
        with self.assertRaisesRegex(ValueError, "no eligible spans"):
            self.service.create(
                PROJECT_ID, self._create_request("translation-batch-ra-empty")
            )

    def test_large_exclusion_groups_return_bounded_examples_and_conserve_counts(self) -> None:
        self._seed_artifact(
            "artifact_many_unmapped",
            [
                (f"span_unmapped_{index}", "unmapped", f"Narrative {index}.")
                for index in range(9)
            ],
        )

        preview = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(snapshot_id=SNAPSHOT_ID),
        )

        self.assertEqual(9, preview.excluded_count)
        self.assertEqual(5, len(preview.exclusions))
        self.assertEqual(4, sum(bool(item.span_id) for item in preview.exclusions))
        self.assertEqual(9, sum(item.count for item in preview.exclusions))

    def test_incomplete_cross_block_sentence_is_excluded_before_translation(self) -> None:
        self._seed_artifact(
            "artifact_incomplete_sentence",
            [
                (
                    "span_incomplete_sentence",
                    "schedule",
                    "When on-site study visits cannot be performed,",
                )
            ],
        )

        preview = self.service.preview(
            PROJECT_ID,
            WritingReferenceTranslationBatchPreviewRequest(snapshot_id=SNAPSHOT_ID),
        )

        self.assertEqual(0, preview.eligible_count)
        self.assertEqual(
            1,
            preview.span_exclusion_reason_counts["semantic_fragment_incomplete"],
        )
        with self.assertRaisesRegex(ValueError, "no eligible spans"):
            self.service.create(
                PROJECT_ID,
                self._create_request("translation-batch-incomplete-sentence"),
            )
        self.assertEqual([], self.runner.calls)

    def test_get_projects_review_and_admission_without_mixing_generation_state(self) -> None:
        self._seed_artifact(
            "artifact_projection",
            [("span_projection", "endpoints", "The endpoint is assessed at Week 16.")],
        )
        batch = self.service.create(
            PROJECT_ID, self._create_request("translation-batch-projection")
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        generated = self.service.get(PROJECT_ID, batch.batch_id).items[0]
        review = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=generated.translation_id,
            translation_revision=generated.translation_revision,
            decision="approved",
            comment="The fake candidate passed medical review.",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="batch-projection-medical-review",
        )
        projected = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("candidate_ready", projected.items[0].generation_status)
        self.assertEqual("approved", projected.items[0].medical_review_status)
        self.assertEqual("confirmed", projected.items[0].author_confirmation_status)
        self.assertEqual("admitted", projected.items[0].admission_status)
        self.assertEqual(1, projected.counts.approved_count)
        self.assertEqual(1, projected.counts.author_confirmed_count)
        self.assertEqual(1, projected.counts.admitted_count)

    def test_invalidated_source_keeps_review_as_history_but_clears_current_author_confirmation(self) -> None:
        artifact = self._seed_artifact(
            "artifact_projection_invalidated",
            [("span_projection_invalidated", "endpoints", "The endpoint is assessed at Week 16.")],
        )
        batch = self.service.create(
            PROJECT_ID,
            self._create_request("translation-batch-projection-invalidated"),
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        generated = self.service.get(PROJECT_ID, batch.batch_id).items[0]
        self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=generated.translation_id,
            translation_revision=generated.translation_revision,
            decision="approved",
            comment="当前来源、抽取与译文均已由作者核对。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="batch-projection-invalidated-review",
        )
        self.repo.invalidate_artifact(
            project_id=PROJECT_ID,
            artifact_id=artifact.artifact_id,
            reason="公开来源发布了替代版本，旧确认仅保留为历史。",
            actor="system_version_monitor",
            expected_revision=1,
            idempotency_key="batch-projection-invalidated-source",
        )

        projected = self.service.get(PROJECT_ID, batch.batch_id)

        self.assertEqual("approved", projected.items[0].medical_review_status)
        self.assertEqual("not_confirmed", projected.items[0].author_confirmation_status)
        self.assertEqual("invalidated", projected.items[0].admission_status)
        self.assertEqual(0, projected.counts.author_confirmed_count)
        self.assertEqual(0, projected.counts.admitted_count)

    def test_superseded_extraction_keeps_review_as_history_but_clears_current_author_confirmation(self) -> None:
        artifact = self._seed_artifact(
            "artifact_projection_extraction_superseded",
            [("span_projection_extraction_r1", "endpoints", "The endpoint is assessed at Week 16.")],
        )
        batch = self.service.create(
            PROJECT_ID,
            self._create_request("translation-batch-projection-extraction-superseded"),
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        generated = self.service.get(PROJECT_ID, batch.batch_id).items[0]
        self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=generated.translation_id,
            translation_revision=generated.translation_revision,
            decision="approved",
            comment="当前结构解析与译文均已由作者核对。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="batch-projection-extraction-superseded-review",
        )
        replacement_text = "The endpoint is assessed at Week 24."
        self.repo.save_extraction(
            WritingReferenceExtractionResult(
                artifact_id=artifact.artifact_id,
                project_id=PROJECT_ID,
                extraction_revision="extract_r2",
                parser_name="fake_parser",
                parser_version="2",
                page_count=1,
                status="pending_visual_and_medical_structure_review",
                spans=[
                    WritingReferenceExtractedSpan(
                        span_id="span_projection_extraction_r2",
                        project_id=PROJECT_ID,
                        artifact_id=artifact.artifact_id,
                        extraction_revision="extract_r2",
                        physical_page=1,
                        block_index=0,
                        source_locator=(
                            f"ctgov:{NCT_ID}:{artifact.artifact_id}:p1:b0"
                        ),
                        ich_m11_anchor="endpoints",
                        source_text=replacement_text,
                        source_text_sha256=sha256(
                            replacement_text.encode("utf-8")
                        ).hexdigest(),
                    )
                ],
            ),
            idempotency_key="batch-projection-extraction-superseded-r2",
        )

        projected = self.service.get(PROJECT_ID, batch.batch_id)

        self.assertEqual("approved", projected.items[0].medical_review_status)
        self.assertEqual("not_confirmed", projected.items[0].author_confirmation_status)
        self.assertEqual("invalidated", projected.items[0].admission_status)
        self.assertEqual(0, projected.counts.author_confirmed_count)
        self.assertEqual(0, projected.counts.admitted_count)

    def test_same_batch_and_translation_ids_are_fully_isolated_across_projects(self) -> None:
        project_b = "proj_cross_project_same_ids"
        artifact_a = self._seed_artifact(
            "artifact_same_ids",
            [("span_same_ids", "endpoints", "The endpoint is assessed at Week 16.")],
        )
        batch_a = self.service.create(
            PROJECT_ID,
            self._create_request("translation-batch-same-ids-a"),
        )
        self.service.run_pending(PROJECT_ID, batch_a.batch_id, "medical_manager")
        batch_a = self.service.get(PROJECT_ID, batch_a.batch_id)
        item_a = batch_a.items[0]
        translation_a = self.repo.translation(
            PROJECT_ID,
            item_a.translation_id,
            item_a.translation_revision,
        )

        snapshot_b = snapshot().model_copy(
            update={"project_id": project_b, "snapshot_id": SNAPSHOT_ID},
            deep=True,
        )
        self.repo.save_search_snapshot(
            snapshot_b,
            idempotency_key="translation-batch-same-ids-search-b",
        )
        artifact_b = artifact_a.model_copy(update={"project_id": project_b})
        self.repo.save_document_artifact(
            artifact_b,
            storage_relpath="safe/project-b/artifact_same_ids.pdf",
            idempotency_key="translation-batch-same-ids-artifact-b",
        )
        span_b = self.repo.source_spans(
            PROJECT_ID,
            artifact_a.artifact_id,
            extraction_revision="extract_r1",
        )[0].model_copy(update={"project_id": project_b})
        self.repo.save_extraction(
            WritingReferenceExtractionResult(
                artifact_id=artifact_b.artifact_id,
                project_id=project_b,
                extraction_revision="extract_r1",
                parser_name="fake_parser",
                parser_version="1",
                page_count=1,
                status="pending_visual_and_medical_structure_review",
                spans=[span_b],
            ),
            idempotency_key="translation-batch-same-ids-extraction-b",
        )
        validation_a = next(
            item
            for item in self.repo.document_validations(PROJECT_ID)
            if item.artifact_id == artifact_a.artifact_id
        )
        self.repo.save_document_validation(
            validation_a.model_copy(update={"project_id": project_b}),
            expected_revision=0,
            idempotency_key="translation-batch-same-ids-validation-b",
        )
        self.repo.record_extraction_review(
            project_id=project_b,
            artifact_id=artifact_b.artifact_id,
            extraction_revision="extract_r1",
            decision="approved",
            confirmed_anchor_coverage=["endpoints"],
            unresolved_structure_issues=[],
            comment="项目B独立确认相同业务ID下的结构解析。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="translation-batch-same-ids-structure-b",
        )
        translation_b = self.repo.save_translation(
            translation_a.model_copy(
                update={
                    "project_id": project_b,
                    "status": "pending_author_confirmation",
                }
            ),
            idempotency_key="translation-batch-same-ids-translation-b",
        )
        self.assertEqual(translation_a.translation_id, translation_b.translation_id)

        item_b = item_a.model_copy(
            update={
                "project_id": project_b,
                "batch_id": batch_a.batch_id,
                "translation_id": translation_b.translation_id,
                "translation_revision": translation_b.revision,
                "ai_run_id": translation_b.ai_run_id,
            },
            deep=True,
        )
        with self.repo._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO writing_reference_translation_batches(
                    tenant_id, project_id, batch_id, snapshot_id, glossary_version,
                    anchor_filter_json, preparation_batch_id, scope_sha256, status,
                    attempt, exclusions_json, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    project_b,
                    batch_a.batch_id,
                    SNAPSHOT_ID,
                    batch_a.glossary_version,
                    json.dumps(batch_a.anchor_filter),
                    batch_a.preparation_batch_id,
                    batch_a.scope_sha256,
                    batch_a.status,
                    batch_a.attempt,
                    json.dumps([]),
                    "medical_manager",
                    NOW.isoformat(),
                    NOW.isoformat(),
                ),
            )
            self.service._insert_item_with(connection, item_b)
            connection.commit()

        self.assertEqual(
            batch_a.batch_id,
            self.service.get(project_b, batch_a.batch_id).batch_id,
        )
        self.assertEqual(
            item_a.translation_id,
            self.service.get(project_b, batch_a.batch_id).items[0].translation_id,
        )

        review_a = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=item_a.translation_id,
            translation_revision=item_a.translation_revision,
            decision="approved",
            comment="项目A作者确认，仅可改变项目A的当前状态。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="translation-batch-same-ids-review-a",
        )
        projected_a = self.service.get(PROJECT_ID, batch_a.batch_id)
        projected_b = self.service.get(project_b, batch_a.batch_id)
        self.assertEqual(1, projected_a.counts.author_confirmed_count)
        self.assertEqual(1, projected_a.counts.admitted_count)
        self.assertEqual(0, projected_b.counts.author_confirmed_count)
        self.assertEqual(0, projected_b.counts.admitted_count)
        with self.assertRaises(KeyError):
            self.repo.medical_review(project_b, review_a.review_id)

        self.repo.invalidate_artifact(
            project_id=PROJECT_ID,
            artifact_id=artifact_a.artifact_id,
            reason="仅使项目A同ID来源失效。",
            actor="system_version_monitor",
            expected_revision=1,
            idempotency_key="translation-batch-same-ids-invalidate-a",
        )
        projected_a = self.service.get(PROJECT_ID, batch_a.batch_id)
        projected_b = self.service.get(project_b, batch_a.batch_id)
        self.assertEqual("invalidated", projected_a.items[0].admission_status)
        self.assertEqual(0, projected_a.counts.author_confirmed_count)
        self.assertEqual("not_admitted", projected_b.items[0].admission_status)
        self.assertEqual(0, projected_b.counts.author_confirmed_count)
        self.assertFalse(
            self.repo.document_artifact(PROJECT_ID, artifact_a.artifact_id).source_current
        )
        self.assertTrue(
            self.repo.document_artifact(project_b, artifact_b.artifact_id).source_current
        )

        self.repo.record_medical_review(
            project_id=project_b,
            translation_id=item_b.translation_id,
            translation_revision=item_b.translation_revision,
            decision="approved",
            comment="项目B作者独立确认，不得恢复项目A的失效状态。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="translation-batch-same-ids-review-b",
        )
        projected_a = self.service.get(PROJECT_ID, batch_a.batch_id)
        projected_b = self.service.get(project_b, batch_a.batch_id)
        self.assertEqual(0, projected_a.counts.author_confirmed_count)
        self.assertEqual("invalidated", projected_a.items[0].admission_status)
        self.assertEqual(1, projected_b.counts.author_confirmed_count)
        self.assertEqual(1, projected_b.counts.admitted_count)
        self.assertEqual([], self.repo.verify_audit_chain(PROJECT_ID))
        self.assertEqual([], self.repo.verify_audit_chain(project_b))

    def test_get_projects_the_current_revision_after_medical_return_and_revision(self) -> None:
        self._seed_artifact(
            "artifact_projection_revision",
            [("span_projection_revision", "endpoints", "The endpoint is assessed.")],
        )
        batch = self.service.create(
            PROJECT_ID,
            self._create_request("translation-batch-projection-revision"),
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        generated = self.service.get(PROJECT_ID, batch.batch_id).items[0]
        returned = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=generated.translation_id,
            translation_revision=generated.translation_revision,
            decision="returned",
            comment="Revise the regulatory Chinese wording before medical approval.",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="batch-projection-returned-review",
        )
        revised = self.translation_service.revise(
            PROJECT_ID,
            generated.translation_id,
            WritingReferenceTranslationRevisionRequest(
                expected_translation_revision=generated.translation_revision,
                medical_review_id=returned.review_id,
                actor="medical_manager",
                idempotency_key="batch-projection-revision-generation",
            ),
        )

        projected = self.service.get(PROJECT_ID, batch.batch_id)

        self.assertEqual(revised.revision, projected.items[0].translation_revision)
        self.assertEqual(revised.ai_run_id, projected.items[0].ai_run_id)
        self.assertEqual("candidate_ready", projected.items[0].generation_status)
        self.assertEqual("not_reviewed", projected.items[0].medical_review_status)
        self.assertEqual("not_confirmed", projected.items[0].author_confirmation_status)
        self.assertEqual(1, projected.counts.pending_medical_review_count)
        self.assertEqual(1, projected.counts.pending_author_confirmation_count)

    def test_batch_operations_append_metadata_only_audit_chain_events(self) -> None:
        self._seed_artifact(
            "artifact_audit",
            [
                (
                    "span_audit",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                )
            ],
        )
        self.runner.failures_remaining["span_audit"] = 1
        batch = self.service.create(
            PROJECT_ID, self._create_request("translation-batch-audit-create")
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        self.service.retry(
            PROJECT_ID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="translation-batch-audit-retry",
            ),
        )
        self.service.run_failed(PROJECT_ID, batch.batch_id, "medical_manager")

        restart_batch = self.service.create(
            PROJECT_ID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SNAPSHOT_ID,
                glossary_version="cms_regulatory_zh_v2",
                actor="medical_manager",
                idempotency_key="translation-batch-audit-restart-create",
            ),
        )
        running = restart_batch.items[0].model_copy(
            update={
                "generation_status": "running",
                "attempt": 1,
                "updated_at": NOW,
            },
            deep=True,
        )
        with self.repo._connect() as connection:
            connection.execute(
                """
                UPDATE writing_reference_translation_batch_items
                SET generation_status='running', attempt=1, payload_json=?
                WHERE tenant_id=? AND project_id=? AND item_id=?
                """,
                (
                    json.dumps(
                        running.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "kangzhe_local",
                    PROJECT_ID,
                    running.item_id,
                ),
            )
            connection.execute(
                """
                UPDATE writing_reference_translation_batches
                SET status='running'
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                """,
                ("kangzhe_local", PROJECT_ID, restart_batch.batch_id),
            )
        # Explicit per-batch recovery (durable executor post-claim path).
        restart_service = self._new_service()
        restart_service.recover_interrupted_items_for_batch(
            PROJECT_ID, restart_batch.batch_id
        )

        with self.repo._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_type, detail_json
                FROM writing_reference_audit_chain
                WHERE tenant_id=? AND project_id=?
                  AND event_type LIKE 'translation_batch_%'
                ORDER BY sequence_no
                """,
                ("kangzhe_local", PROJECT_ID),
            ).fetchall()
        event_types = [str(row["event_type"]) for row in rows]
        self.assertIn("translation_batch_created", event_types)
        self.assertIn("translation_batch_retry_requested", event_types)
        self.assertIn("translation_batch_item_completed", event_types)
        self.assertIn("translation_batch_item_failed", event_types)
        self.assertIn(
            "translation_batch_item_recovered_after_restart",
            event_types,
        )
        audit_payload = "\n".join(str(row["detail_json"]) for row in rows)
        self.assertNotIn("Participants must not receive", audit_payload)
        self.assertNotIn("受试者在14天内不得接受", audit_payload)
        created_detail = next(
            json.loads(row["detail_json"])
            for row in rows
            if row["event_type"] == "translation_batch_created"
        )
        self.assertEqual(SNAPSHOT_ID, created_detail["snapshot_id"])
        self.assertEqual(GLOSSARY_VERSION, created_detail["glossary_version"])
        self.assertEqual(64, len(created_detail["scope_sha256"]))
        self.assertEqual([], self.repo.verify_audit_chain(PROJECT_ID))

    def test_http_core_contract_and_span_injection_rejection(self) -> None:
        self._seed_artifact(
            "artifact_http",
            [("span_http", "eligibility", "Participants are eligible.")],
        )
        with patch(
            "services.api.app.main.writing_reference_translation_batch_service",
            self.service,
        ):
            client = TestClient(app)
            preview = client.get(
                f"/api/projects/{PROJECT_ID}/medical-writing/references/"
                "translation-batches/preview",
                params={"snapshot_id": SNAPSHOT_ID},
            )
            self.assertEqual(200, preview.status_code, preview.text)
            self.assertEqual(1, preview.json()["eligible_count"])

            injected = client.post(
                f"/api/projects/{PROJECT_ID}/medical-writing/references/"
                "translation-batches",
                json={
                    "snapshot_id": SNAPSHOT_ID,
                    "span_ids": ["span_http"],
                    "actor": "medical_manager",
                    "idempotency_key": "http-injected-span",
                },
            )
            self.assertEqual(422, injected.status_code, injected.text)

            created = client.post(
                f"/api/projects/{PROJECT_ID}/medical-writing/references/"
                "translation-batches",
                json={
                    "snapshot_id": SNAPSHOT_ID,
                    "actor": "medical_manager",
                    "idempotency_key": "http-translation-batch-create",
                },
            )
            self.assertEqual(202, created.status_code, created.text)
            batch_id = created.json()["batch_id"]
            # This fixture intentionally has no durable store attached.
            self.service.run_pending(PROJECT_ID, batch_id, "medical_manager")

            latest = client.get(
                f"/api/projects/{PROJECT_ID}/medical-writing/references/"
                "translation-batches/latest",
                params={"snapshot_id": SNAPSHOT_ID},
            )
            self.assertEqual(200, latest.status_code, latest.text)
            self.assertEqual(batch_id, latest.json()["batch_id"])
            self.assertEqual("completed", latest.json()["status"])

            fetched = client.get(
                f"/api/projects/{PROJECT_ID}/medical-writing/references/"
                f"translation-batches/{batch_id}"
            )
            self.assertEqual(200, fetched.status_code, fetched.text)
            self.assertEqual("candidate_ready", fetched.json()["items"][0]["generation_status"])

            retried = client.post(
                f"/api/projects/{PROJECT_ID}/medical-writing/references/"
                f"translation-batches/{batch_id}/retry",
                json={
                    "actor": "medical_manager",
                    "idempotency_key": "http-translation-batch-retry",
                },
            )
            self.assertEqual(202, retried.status_code, retried.text)

    def test_composite_batch_persists_revision_and_merges_fidelity_codes(self) -> None:
        """Round-6 contract: the batch composite path must produce the same
        immutable ``WritingReferenceTranslationRevision`` the direct path
        produces, link the batch item to it, let medical review and corpus
        admission consume it, keep the Flash-integrated text/hash, merge
        Flash-QC and deterministic fidelity codes, and not duplicate the
        revision on an idempotent rerun.
        """
        from services.api.app.writing_reference import (
            COMPOSITE_TRANSLATION_BODY_MODEL,
            COMPOSITE_TRANSLATION_CONTRACT_HASH,
        )
        from services.api.app.chapter_translation_pipeline import HY_MT2_MODEL_ID

        self._seed_artifact(
            "artifact_round6",
            [
                (
                    "span_round6_ok",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                ),
            ],
        )
        batch = self.service.create(
            PROJECT_ID, self._create_request("translation-batch-round6")
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        completed = self.service.get(PROJECT_ID, batch.batch_id)
        item = completed.items[0]

        # 1. Batch item links to a real persisted translation revision.
        self.assertEqual("candidate_ready", item.generation_status)
        self.assertTrue(item.translation_id)
        self.assertGreaterEqual(item.translation_revision, 1)
        persisted = self.repo.translation(
            PROJECT_ID, item.translation_id, item.translation_revision
        )
        self.assertIsNotNone(persisted)
        self.assertEqual(item.span_id, persisted.span_id)
        self.assertEqual(
            COMPOSITE_TRANSLATION_CONTRACT_HASH, persisted.contract_hash
        )
        self.assertEqual(
            COMPOSITE_TRANSLATION_BODY_MODEL, persisted.model_name
        )

        # 2. Medical review and admission can consume the persisted revision.
        review = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=item.translation_id,
            translation_revision=item.translation_revision,
            decision="approved",
            comment="Round-6 medical review approves the composite candidate.",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="round6-medical-review",
        )
        projected = self.service.get(PROJECT_ID, batch.batch_id).items[0]
        self.assertEqual("approved", projected.medical_review_status)
        self.assertEqual("confirmed", projected.author_confirmation_status)
        self.assertEqual("admitted", projected.admission_status)

        # 3. Final text/hash equals the Flash-integrated candidate.  The
        #    deterministic fixture integrates the Hy-MT2 body verbatim, so the
        #    persisted translation text must match the fixture's translation.
        expected_text = self.runner.TRANSLATIONS[
            "Participants must not receive SCS within 14 days."
        ]
        self.assertEqual(expected_text, persisted.translated_text)
        self.assertEqual(
            sha256(expected_text.encode("utf-8")).hexdigest(),
            sha256(persisted.translated_text.encode("utf-8")).hexdigest(),
        )

        # 4. Merged fidelity codes survive (none expected on a clean pass, but
        #    the item and persisted revision must agree and be non-losing).
        self.assertEqual(
            list(persisted.fidelity_failure_codes),
            list(item.fidelity_failure_codes),
        )

    def test_composite_batch_blocked_merges_deterministic_and_flash_qc_codes(self) -> None:
        """When both Flash-QC and deterministic fidelity fail, the merged code
        set on the batch item and persisted revision keeps both sources."""
        self._seed_artifact(
            "artifact_round6_blocked",
            [
                (
                    "span_round6_blocked",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                )
            ],
        )
        self.runner.blocked_spans.add("span_round6_blocked")
        batch = self.service.create(
            PROJECT_ID, self._create_request("translation-batch-round6-blocked")
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        blocked = self.service.get(PROJECT_ID, batch.batch_id)
        item = blocked.items[0]
        self.assertEqual("fidelity_blocked", item.generation_status)
        self.assertEqual("fidelity_blocked", item.pipeline_stage)
        # Deterministic fidelity gate produces non-empty codes for the drifted
        # candidate; they must survive on both the item and persisted revision.
        self.assertGreater(len(item.fidelity_failure_codes), 0)
        self.assertTrue(item.translation_id)
        persisted = self.repo.translation(
            PROJECT_ID, item.translation_id, item.translation_revision
        )
        self.assertEqual(
            sorted(persisted.fidelity_failure_codes),
            sorted(item.fidelity_failure_codes),
        )
        # No medical review or admission side effect for a blocked candidate.
        self.assertEqual([], self.repo.medical_reviews(PROJECT_ID))

    def test_composite_batch_idempotent_rerun_does_not_duplicate_revision(self) -> None:
        """An idempotent batch rerun must not create a second translation
        revision for the same span."""
        self._seed_artifact(
            "artifact_round6_idempotent",
            [
                (
                    "span_round6_idempotent",
                    "endpoints",
                    "The primary endpoint is assessed at Week 16.",
                )
            ],
        )
        batch = self.service.create(
            PROJECT_ID, self._create_request("translation-batch-round6-idempotent")
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        first = self.service.get(PROJECT_ID, batch.batch_id).items[0]
        revisions_before = self.repo.translations(
            PROJECT_ID, "span_round6_idempotent"
        )
        # Idempotent create replay returns the same batch.
        replay = self.service.create(
            PROJECT_ID, self._create_request("translation-batch-round6-idempotent")
        )
        self.assertEqual(batch.batch_id, replay.batch_id)
        revisions_after = self.repo.translations(
            PROJECT_ID, "span_round6_idempotent"
        )
        self.assertEqual(len(revisions_before), len(revisions_after))
        self.assertEqual(first.translation_id, revisions_after[-1].translation_id)

    def _completed_batch(
        self,
        artifacts: list[tuple[str, list[tuple[str, str, str]]]],
        key: str,
        *,
        blocked: tuple[str, list[tuple[str, str, str]], str] | None = None,
    ):
        for artifact_id, spans in artifacts:
            self._seed_artifact(artifact_id, spans)
        if blocked is not None:
            blocked_artifact_id, blocked_spans, blocked_span_id = blocked
            self._seed_artifact(blocked_artifact_id, blocked_spans)
            self.runner.blocked_spans.add(blocked_span_id)
        batch = self.service.create(PROJECT_ID, self._create_request(key))
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        return self.service.get(PROJECT_ID, batch.batch_id)

    def test_batch_medical_review_request_dedupes_targets(self) -> None:
        request = WritingReferenceTranslationBatchMedicalReviewRequest(
            targets=[
                {"translation_id": "trans_a", "translation_revision": 1},
                {"translation_id": "trans_a", "translation_revision": 1},
                {"translation_id": "trans_b", "translation_revision": 2},
            ],
            actor="medical_manager",
            idempotency_key="batch-review-model-dedupe",
        )
        self.assertEqual(
            [("trans_a", 1), ("trans_b", 2)],
            [(target.translation_id, target.translation_revision) for target in request.targets],
        )
        self.assertTrue(request.comment.strip())
        with self.assertRaises(ValidationError):
            WritingReferenceTranslationBatchMedicalReviewRequest(
                targets=[],
                comment="   ",
                actor="medical_manager",
                idempotency_key="batch-review-model-blank",
            )
        with self.assertRaises(ValidationError):
            WritingReferenceTranslationBatchMedicalReviewRequest(
                targets=[],
                actor="medical_manager",
                idempotency_key="batch-review-model-empty-targets",
            )

    def test_batch_medical_review_approves_eligible_rows_and_projects_confirmation(self) -> None:
        completed = self._completed_batch(
            [
                ("artifact_batch_review_a", [("span_batch_review_a", "eligibility", "Participants must not receive SCS within 14 days.")]),
                ("artifact_batch_review_b", [("span_batch_review_b", "endpoints", "The primary endpoint is assessed at Week 16.")]),
            ],
            "translation-batch-review-approve",
            blocked=(
                "artifact_batch_review_blocked",
                [("span_batch_review_blocked", "background", "This protocol evaluates treatment in adults.")],
                "span_batch_review_blocked",
            ),
        )
        eligible = [
            item for item in completed.items if item.generation_status == "candidate_ready"
        ]
        self.assertEqual(2, len(eligible))
        blocked = [
            item for item in completed.items if item.generation_status == "fidelity_blocked"
        ]
        self.assertEqual(1, len(blocked))

        outcomes = self.repo.record_batch_medical_review(
            project_id=PROJECT_ID,
            batch_id=completed.batch_id,
            targets=[(item.translation_id, item.translation_revision) for item in eligible],
            comment="批量作者确认：机器忠实度检查通过。",
            actor="medical_manager",
            idempotency_key="batch-review-approve-eligible",
        )
        self.assertEqual(["approved", "approved"], [item.outcome for item in outcomes])
        self.assertTrue(all(item.review_id for item in outcomes))

        # Blocked rows were never targets and must carry no review side effect.
        reviews = self.repo.medical_reviews(PROJECT_ID)
        self.assertEqual(2, len(reviews))
        self.assertEqual(
            {item.translation_id for item in eligible},
            {review.translation_id for review in reviews},
        )
        self.assertTrue(all(review.decision_type == "author_confirmation" for review in reviews))
        self.assertTrue(all(review.admission_status == "admitted" for review in reviews))

        projected = {
            item.span_id: item
            for item in self.service.get(PROJECT_ID, completed.batch_id).items
        }
        for item in eligible:
            row = projected[item.span_id]
            self.assertEqual("confirmed", row.author_confirmation_status)
            self.assertEqual("admitted", row.admission_status)
        self.assertEqual(
            "not_confirmed",
            projected["span_batch_review_blocked"].author_confirmation_status,
        )
        self.assertEqual([], self.repo.verify_audit_chain(PROJECT_ID))

    def test_batch_medical_review_stale_row_does_not_conceal_remaining_rows(self) -> None:
        completed = self._completed_batch(
            [
                ("artifact_batch_stale_a", [("span_batch_stale_a", "eligibility", "Participants must not receive SCS within 14 days.")]),
                ("artifact_batch_stale_b", [("span_batch_stale_b", "endpoints", "The primary endpoint is assessed at Week 16.")]),
            ],
            "translation-batch-review-stale",
        )
        items = {item.span_id: item for item in completed.items}
        item_a = items["span_batch_stale_a"]
        item_b = items["span_batch_stale_b"]
        outcomes = self.repo.record_batch_medical_review(
            project_id=PROJECT_ID,
            batch_id=completed.batch_id,
            targets=[
                (item_a.translation_id, item_a.translation_revision + 1),
                (item_b.translation_id, item_b.translation_revision),
            ],
            comment="批量作者确认：机器忠实度检查通过。",
            actor="medical_manager",
            idempotency_key="batch-review-stale-partial",
        )
        by_id = {item.translation_id: item for item in outcomes}
        self.assertEqual("stale", by_id[item_a.translation_id].outcome)
        self.assertIn("no longer current", by_id[item_a.translation_id].reason)
        self.assertEqual("approved", by_id[item_b.translation_id].outcome)
        reviews = self.repo.medical_reviews(PROJECT_ID)
        self.assertEqual([item_b.translation_id], [review.translation_id for review in reviews])

    def test_batch_medical_review_idempotent_replay_does_not_duplicate_reviews(self) -> None:
        completed = self._completed_batch(
            [
                ("artifact_batch_replay_a", [("span_batch_replay_a", "eligibility", "Participants must not receive SCS within 14 days.")]),
                ("artifact_batch_replay_b", [("span_batch_replay_b", "endpoints", "The primary endpoint is assessed at Week 16.")]),
            ],
            "translation-batch-review-replay",
        )
        targets = [
            (item.translation_id, item.translation_revision) for item in completed.items
        ]
        first = self.repo.record_batch_medical_review(
            project_id=PROJECT_ID,
            batch_id=completed.batch_id,
            targets=targets,
            comment="批量作者确认：机器忠实度检查通过。",
            actor="medical_manager",
            idempotency_key="batch-review-replay",
        )
        replay = self.repo.record_batch_medical_review(
            project_id=PROJECT_ID,
            batch_id=completed.batch_id,
            targets=targets,
            comment="批量作者确认：机器忠实度检查通过。",
            actor="medical_manager",
            idempotency_key="batch-review-replay",
        )
        self.assertEqual(
            [item.review_id for item in first],
            [item.review_id for item in replay],
        )
        self.assertEqual(2, len(self.repo.medical_reviews(PROJECT_ID)))
        self.assertEqual([], self.repo.verify_audit_chain(PROJECT_ID))

    def test_http_batch_medical_review_reports_per_item_outcomes(self) -> None:
        completed = self._completed_batch(
            [
                ("artifact_http_review_a", [("span_http_review_a", "eligibility", "Participants must not receive SCS within 14 days.")]),
                ("artifact_http_review_b", [("span_http_review_b", "endpoints", "The primary endpoint is assessed at Week 16.")]),
            ],
            "translation-batch-http-review",
            blocked=(
                "artifact_http_batch_review_blocked",
                [("span_http_review_blocked", "background", "This protocol evaluates treatment in adults.")],
                "span_http_review_blocked",
            ),
        )
        with patch(
            "services.api.app.main.writing_reference_translation_batch_service",
            self.service,
        ), patch(
            "services.api.app.main.writing_reference_repository",
            self.repo,
        ):
            client = TestClient(app)
            missing = client.post(
                f"/api/projects/{PROJECT_ID}/medical-writing/references/"
                "translation-batches/batch_missing/medical-review",
                json={
                    "targets": [
                        {
                            "translation_id": "trans_missing",
                            "translation_revision": 1,
                        }
                    ],
                    "actor": "medical_manager",
                    "idempotency_key": "http-batch-review-missing",
                },
            )
            self.assertEqual(404, missing.status_code, missing.text)

            items = {item.span_id: item for item in completed.items}
            eligible_a = items["span_http_review_a"]
            eligible_b = items["span_http_review_b"]
            blocked = items["span_http_review_blocked"]
            response = client.post(
                f"/api/projects/{PROJECT_ID}/medical-writing/references/"
                f"translation-batches/{completed.batch_id}/medical-review",
                json={
                    "targets": [
                        {
                            "translation_id": eligible_a.translation_id,
                            "translation_revision": eligible_a.translation_revision,
                        },
                        {
                            "translation_id": eligible_b.translation_id,
                            "translation_revision": eligible_b.translation_revision + 1,
                        },
                        {
                            "translation_id": blocked.translation_id,
                            "translation_revision": blocked.translation_revision,
                        },
                        {"translation_id": "trans_not_in_batch", "translation_revision": 1},
                    ],
                    "actor": "medical_manager",
                    "idempotency_key": "http-batch-review-targets",
                },
            )
            self.assertEqual(200, response.status_code, response.text)
            payload = response.json()
            self.assertEqual(1, payload["approved_count"])
            self.assertEqual(1, payload["stale_count"])
            self.assertEqual(2, payload["skipped_count"])
            self.assertEqual(0, payload["failed_count"])
            by_id = {item["translation_id"]: item for item in payload["items"]}
            self.assertEqual("approved", by_id[eligible_a.translation_id]["outcome"])
            self.assertEqual("stale", by_id[eligible_b.translation_id]["outcome"])
            self.assertEqual("skipped", by_id[blocked.translation_id]["outcome"])
            self.assertEqual(
                "generation_fidelity_blocked",
                by_id[blocked.translation_id]["reason"],
            )
            self.assertEqual(
                "not_in_batch", by_id["trans_not_in_batch"]["reason"]
            )

            # Empty targets cannot implicitly approve a row the writer did not
            # explicitly review.
            confirm_rest = client.post(
                f"/api/projects/{PROJECT_ID}/medical-writing/references/"
                f"translation-batches/{completed.batch_id}/medical-review",
                json={
                    "targets": [],
                    "actor": "medical_manager",
                    "idempotency_key": "http-batch-review-remaining",
                },
            )
            self.assertEqual(422, confirm_rest.status_code, confirm_rest.text)

            fetched = client.get(
                f"/api/projects/{PROJECT_ID}/medical-writing/references/"
                f"translation-batches/{completed.batch_id}"
            )
            self.assertEqual(200, fetched.status_code, fetched.text)
            projected = {
                item["span_id"]: item for item in fetched.json()["items"]
            }
            self.assertEqual(
                "confirmed",
                projected["span_http_review_a"]["author_confirmation_status"],
            )
            self.assertEqual(
                "not_confirmed",
                projected["span_http_review_b"]["author_confirmation_status"],
            )
            self.assertEqual(
                "not_admitted",
                projected["span_http_review_b"]["admission_status"],
            )
            self.assertEqual(
                "not_confirmed",
                projected["span_http_review_blocked"]["author_confirmation_status"],
            )
            self.assertEqual([], self.repo.verify_audit_chain(PROJECT_ID))

    def test_single_item_medical_review_path_still_rejects_batch_payload(self) -> None:
        completed = self._completed_batch(
            [("artifact_single_review_compat", [("span_single_review_compat", "eligibility", "Participants must not receive SCS within 14 days.")])],
            "translation-batch-single-compat",
        )
        item = completed.items[0]
        with patch(
            "services.api.app.main.writing_reference_translation_batch_service",
            self.service,
        ), patch(
            "services.api.app.main.writing_reference_repository",
            self.repo,
        ):
            client = TestClient(app)
            single = client.post(
                f"/api/projects/{PROJECT_ID}/medical-writing/references/"
                f"translations/{item.translation_id}/medical-review",
                json={
                    "translation_revision": item.translation_revision,
                    "decision": "approved",
                    "comment": "单项医学作者确认。",
                    "actor": "medical_manager",
                    "expected_revision": 0,
                    "idempotency_key": "http-single-review-compat",
                },
            )
            self.assertEqual(200, single.status_code, single.text)
            self.assertEqual("approved", single.json()["decision"])
            self.assertEqual("author_confirmation", single.json()["decision_type"])


class WritingReferenceTranslationBatchDiscoveryProjectionTests(unittest.TestCase):
    """Verify translation accepts the same confirmed discovery basket
    projection authority that preparation already accepts (MW-A1-002 fix).

    These tests do NOT mock the real WritingReferenceTranslationBatchService;
    they build it with a FakeJourneyService configured for the pre-PICOS
    discovery-projection path and verify the effective retained scope.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = WritingReferenceRepository(
            Path(self.tmp.name) / "writing_reference.sqlite3"
        )
        source_snapshot = snapshot().model_copy(
            update={"project_id": PROJECT_ID, "snapshot_id": SNAPSHOT_ID},
            deep=True,
        )
        self.repo.save_search_snapshot(
            source_snapshot,
            idempotency_key="discovery-projection-snapshot",
        )
        self.journeys = _DiscoveryProjectionJourneyService()
        self.journeys.lock_discovery(
            PROJECT_ID, SNAPSHOT_ID, [NCT_ID]
        )
        self.preparation = FakePreparationService()
        self.preparation.set(PROJECT_ID, SNAPSHOT_ID)
        self.runner = FakeTranslationRunner()
        self._pipeline, self._planner, self._translator, self._qc = (
            build_deterministic_pipeline()
        )
        self._translator.translations = self.runner.TRANSLATIONS
        self._translator.blocked_spans = self.runner.blocked_spans
        self._translator.failures_remaining = self.runner.failures_remaining
        self._translator.failure_message_fn = lambda: self.runner.failure_message
        wire_pipeline_calls_to_runner(self.runner, self._translator)
        self.translation_service = WritingReferenceTranslationService(
            self.repo,
            self.runner,
            clock=lambda: NOW,
            chapter_pipeline=self._pipeline,
        )
        self.service = WritingReferenceTranslationBatchService(
            self.repo,
            self.journeys,
            self.preparation,
            self.translation_service,
            clock=lambda: NOW,
            chapter_pipeline=self._pipeline,
        )
        # Seed a validated artifact so preview/create can find spans.
        from tests.test_writing_reference_translation_batch import (
            WritingReferenceTranslationBatchTests,
        )
        self._seed = WritingReferenceTranslationBatchTests.setUp
        # Reuse the artifact seeding from the parent test class by invoking
        # its _seed_artifact with our repo.
        self._seeder = WritingReferenceTranslationBatchTests()
        self._seeder.tmp = self.tmp
        self._seeder.repo = self.repo
        self._seeder.journeys = self.journeys
        self._seeder.preparation = self.preparation
        self._seeder.runner = self.runner
        self._seeder._pipeline = self._pipeline
        self._seeder.planner = self._planner
        self._seeder.translation_service = self.translation_service
        self._seeder.service = self.service
        self._seeder._seed_artifact(
            "artifact_discovery_projection",
            [
                (
                    "span_discovery_eligibility",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                )
            ],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _preview_request() -> WritingReferenceTranslationBatchPreviewRequest:
        return WritingReferenceTranslationBatchPreviewRequest(
            snapshot_id=SNAPSHOT_ID,
            glossary_version=GLOSSARY_VERSION,
            anchor_filter=["eligibility"],
        )

    @staticmethod
    def _create_request(
        key: str = "discovery-translation-create-001",
    ) -> WritingReferenceTranslationBatchCreateRequest:
        return WritingReferenceTranslationBatchCreateRequest(
            snapshot_id=SNAPSHOT_ID,
            glossary_version=GLOSSARY_VERSION,
            anchor_filter=["eligibility"],
            actor="medical_manager",
            idempotency_key=key,
        )

    def test_preview_accepts_confirmed_discovery_projection(self) -> None:
        """Pre-PICOS: confirmed discovery projection satisfies translation scope."""
        preview = self.service.preview(PROJECT_ID, self._preview_request())
        self.assertGreater(preview.eligible_count, 0)

    def test_create_accepts_confirmed_discovery_projection(self) -> None:
        """Translation batch create succeeds with discovery projection authority."""
        batch = self.service.create(PROJECT_ID, self._create_request())
        self.assertEqual("eligibility", batch.anchor_filter[0])
        self.assertGreater(len(batch.items), 0)

    def test_rejects_missing_discovery_confirmation(self) -> None:
        """No finalized triage and no confirmed projection → must fail."""
        self.journeys.clear_confirmation(PROJECT_ID)
        with self.assertRaises(ValueError) as ctx:
            self.service.preview(PROJECT_ID, self._preview_request())
        self.assertIn("confirmed discovery basket projection", str(ctx.exception))

    def test_rejects_wrong_snapshot_discovery_projection(self) -> None:
        """Discovery projection for a different snapshot must not unlock."""
        self.journeys.lock_discovery(
            PROJECT_ID, "wref_search_different_snapshot", [NCT_ID]
        )
        with self.assertRaises(ValueError):
            self.service.preview(PROJECT_ID, self._preview_request())

    def test_prefers_finalized_triage_over_discovery(self) -> None:
        """When both exist, finalized corpus triage takes precedence."""
        self.journeys.promote_to_finalized(PROJECT_ID, SNAPSHOT_ID, [NCT_ID])
        preview = self.service.preview(PROJECT_ID, self._preview_request())
        self.assertGreater(preview.eligible_count, 0)

    def test_ignores_finalized_triage_for_stale_snapshot(self) -> None:
        """Finalized triage on another snapshot must not override discovery."""
        self.journeys.promote_to_finalized(
            PROJECT_ID,
            "wref_search_stale_finalized",
            ["NCT99999999"],
        )
        batch = self.service.create(
            PROJECT_ID, self._create_request("discovery-stale-finalized-create")
        )
        self.assertGreater(len(batch.items), 0)
        self.assertEqual(NCT_ID, batch.items[0].nct_id)


class _DiscoveryProjectionJourneyService:
    """Journey service variant for the pre-PICOS discovery-projection path."""

    def __init__(self) -> None:
        self.states: dict[str, SimpleNamespace] = {}

    def lock_discovery(
        self,
        project_id: str,
        snapshot_id: str,
        retained_ids: list[str],
    ) -> None:
        self.states[project_id] = SimpleNamespace(
            search_plan=SimpleNamespace(latest_snapshot_id=snapshot_id),
            corpus_triage=SimpleNamespace(
                status="pending",
                snapshot_id=snapshot_id,
                retained_candidate_ids=[],
            ),
            discovery_basket_projection=SimpleNamespace(
                confirmation_id="ct_conf_discovery_test",
                snapshot_id=snapshot_id,
                retained_nct_ids=list(retained_ids),
            ),
        )

    def promote_to_finalized(
        self,
        project_id: str,
        snapshot_id: str,
        retained_ids: list[str],
    ) -> None:
        state = self.states.get(project_id)
        if state is None:
            raise KeyError(project_id)
        state.corpus_triage = SimpleNamespace(
            status="finalized",
            snapshot_id=snapshot_id,
            retained_candidate_ids=list(retained_ids),
        )

    def clear_confirmation(self, project_id: str) -> None:
        state = self.states.get(project_id)
        if state is None:
            return
        state.discovery_basket_projection = SimpleNamespace(
            confirmation_id="",
            snapshot_id="",
            retained_nct_ids=[],
        )

    def get(self, project_id: str) -> SimpleNamespace:
        if project_id not in self.states:
            raise KeyError(project_id)
        return self.states[project_id]


if __name__ == "__main__":
    unittest.main()
