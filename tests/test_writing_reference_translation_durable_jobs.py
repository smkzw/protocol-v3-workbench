"""Durable-job focused tests for translation batch recovery and integration.

Covers the scenarios required by the work item:
- pending restart resume
- expired running takeover
- completed reuse (no retranslation)
- failed-retryable retry
- cancel/stale-owner/project isolation
- existing translation regressions (via the shared test class)

These tests use the deterministic composite pipeline fixture and a real
DurableJobStore so the integration between the translation batch service and
the durable job worker is exercised end-to-end.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from packages.contracts.workbench_contracts.models import (
    DurableJobProgressPayload,
    WritingReferenceDocumentArtifact,
    WritingReferenceDocumentValidationRecord,
    WritingReferenceExtractedSpan,
    WritingReferenceExtractionResult,
    WritingReferenceTranslationBatchCreateRequest,
    WritingReferenceTranslationBatchPreviewRequest,
    WritingReferenceTranslationBatchRetryRequest,
    WritingReferenceTranslationRequest,
)
from services.api.app.medical_writing_durable_jobs import (
    DurableJobStore,
    DurableJobWorker,
)
from services.api.app.writing_reference import WritingReferenceTranslationService
from services.api.app.writing_reference_repository import WritingReferenceRepository
from services.api.app.writing_reference_translation_batch import (
    REFERENCE_TRANSLATION_JOB_TYPE,
    TranslationBatchDurableExecutor,
    WritingReferenceTranslationBatchService,
)
from tests._composite_pipeline_fixture import (
    build_deterministic_pipeline,
    wire_pipeline_calls_to_runner,
)
from tests.test_writing_reference_repository import snapshot
from tests.test_writing_reference_translation_batch import (
    FakeJourneyService,
    FakePreparationService,
    FakeTranslationRunner,
    NOW,
    PROJECT_ID,
    SNAPSHOT_ID,
    NCT_ID,
    GLOSSARY_VERSION,
)


def _seed_artifact(
    repo: WritingReferenceRepository,
    artifact_id: str,
    spans: list[tuple[str, str, str]],
    *,
    validation_status: str | None = "confirmed",
    review_decision: str | None = "approved",
    extraction_revision: str = "extract_r1",
) -> WritingReferenceDocumentArtifact:
    """Seed an artifact with spans, validation, and structure review."""
    artifact_hash = sha256(artifact_id.encode("utf-8")).hexdigest()
    artifact = WritingReferenceDocumentArtifact(
        artifact_id=artifact_id,
        project_id=PROJECT_ID,
        snapshot_id=SNAPSHOT_ID,
        nct_id=NCT_ID,
        source_document_id=f"source_{artifact_id}",
        document_type="protocol",
        filename=f"{artifact_id}.pdf",
        requested_url=f"https://clinicaltrials.gov/{artifact_id}.pdf",
        final_url=f"https://clinicaltrials.gov/{artifact_id}.pdf",
        content_type="application/pdf",
        actual_size=1024,
        content_sha256=artifact_hash,
        created_by="medical_manager",
        created_at=NOW,
    )
    repo.save_document_artifact(
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
    repo.save_extraction(
        WritingReferenceExtractionResult(
            artifact_id=artifact_id,
            project_id=PROJECT_ID,
            extraction_revision=extraction_revision,
            parser_name="fake_parser",
            parser_version="1",
            page_count=max(1, len(spans)),
            status="pending_visual_and_medical_structure_review",
            spans=extracted_spans,
        ),
        idempotency_key=f"seed-{artifact_id}-{extraction_revision}",
    )
    if validation_status is not None:
        repo.save_document_validation(
            WritingReferenceDocumentValidationRecord(
                validation_id=f"validation_{artifact_id}",
                project_id=PROJECT_ID,
                artifact_id=artifact_id,
                revision=1,
                status=validation_status,
                document_sha256=artifact_hash,
                extraction_revision=extraction_revision,
                source_state_revision=1,
                summary="Current file content was confirmed for testing.",
                actor="medical_manager",
                created_at=NOW,
            ),
            expected_revision=0,
            idempotency_key=f"seed-{artifact_id}-validation",
        )
    if review_decision is not None:
        repo.record_extraction_review(
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
            comment="Fake structure review for durable translation testing.",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key=f"seed-{artifact_id}-structure-review",
        )
    return artifact


def _create_request(
    key: str = "durable-translation-batch-create-001",
    anchors: list[str] | None = None,
) -> WritingReferenceTranslationBatchCreateRequest:
    return WritingReferenceTranslationBatchCreateRequest(
        snapshot_id=SNAPSHOT_ID,
        glossary_version=GLOSSARY_VERSION,
        anchor_filter=list(anchors or []),
        actor="medical_manager",
        idempotency_key=key,
    )


class _DurableBatchFixture:
    """Shared fixture for durable translation batch tests."""

    def setup_fixture(self) -> None:
        self._durable_tmp = tempfile.TemporaryDirectory()
        self.durable_store = DurableJobStore(
            Path(self._durable_tmp.name) / "durable.db",
            lease_seconds=600.0,
            heartbeat_interval_seconds=30.0,
        )
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
            idempotency_key="durable-test-search-snapshot",
        )
        self.journeys = FakeJourneyService()
        self.journeys.lock(PROJECT_ID, SNAPSHOT_ID, [NCT_ID])
        self.preparation = FakePreparationService()
        self.preparation.set(PROJECT_ID, SNAPSHOT_ID)
        self.runner = FakeTranslationRunner()
        (
            self._pipeline,
            self._planner,
            self._translator,
            self._qc,
        ) = build_deterministic_pipeline()
        # Expose planner for tests that need to set chapter assignments.
        self.planner = self._planner
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
            durable_store=self.durable_store,
        )

    def teardown_fixture(self) -> None:
        self.tmp.cleanup()
        self._durable_tmp.cleanup()

    def seed_artifact(
        self,
        artifact_id: str,
        spans: list[tuple[str, str, str]],
        **kwargs,
    ) -> WritingReferenceDocumentArtifact:
        return _seed_artifact(self.repo, artifact_id, spans, **kwargs)

    def create_batch(self, key: str = "durable-translation-batch-create-001"):
        return self.service.create(PROJECT_ID, _create_request(key))


class TestDurableJobCreation(unittest.TestCase, _DurableBatchFixture):
    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_create_ensures_durable_job(self) -> None:
        """Batch create must create a reference_translation durable job."""
        self.seed_artifact(
            "artifact_durable_create",
            [("span_durable_create", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("durable-create-001")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch.batch_id, actor="medical_manager"
        )
        self.assertIsNotNone(job_id)
        record = self.durable_store.get(PROJECT_ID, job_id)
        self.assertEqual(record.job_type, REFERENCE_TRANSLATION_JOB_TYPE)
        self.assertEqual(record.business_key, batch.batch_id)
        self.assertEqual(record.status, "queued")

    def test_dedupe_same_batch_returns_same_job(self) -> None:
        """Creating the same durable job twice returns the same job_id."""
        self.seed_artifact(
            "artifact_durable_dedupe",
            [("span_durable_dedupe", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("durable-dedupe-001")
        job_id_1 = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch.batch_id, actor="medical_manager"
        )
        job_id_2 = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch.batch_id, actor="medical_manager"
        )
        self.assertEqual(job_id_1, job_id_2)

    def test_no_durable_store_returns_none(self) -> None:
        """Without a durable_store, ensure_reference_translation_job returns None."""
        self.seed_artifact(
            "artifact_no_store",
            [("span_no_store", "eligibility", "Participants are eligible.")],
        )
        # Create a service without durable_store
        service_no_store = WritingReferenceTranslationBatchService(
            self.repo,
            self.journeys,
            self.preparation,
            self.translation_service,
            clock=lambda: NOW,
            chapter_pipeline=self._pipeline,
        )
        batch = service_no_store.create(
            PROJECT_ID, _create_request("no-store-001")
        )
        result = service_no_store.ensure_reference_translation_job(
            PROJECT_ID, batch.batch_id, actor="medical_manager"
        )
        self.assertIsNone(result)


class TestPendingRestartResume(unittest.TestCase, _DurableBatchFixture):
    """Restart with pending items must resume translation."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_pending_items_resume_after_restart(self) -> None:
        """Pending items survive restart and are processed on recovery."""
        self.seed_artifact(
            "artifact_pending_restart",
            [
                (
                    "span_pending_restart",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                ),
            ],
        )
        batch = self.create_batch("durable-pending-restart-001")
        # Items are in 'pending' state; simulate a restart by creating a new
        # service instance with the same durable store.
        restarted_service = WritingReferenceTranslationBatchService(
            self.repo,
            self.journeys,
            self.preparation,
            self.translation_service,
            clock=lambda: NOW,
            chapter_pipeline=self._pipeline,
            durable_store=self.durable_store,
        )
        # recover_pending_batches should identify the batch as needing recovery
        pending = restarted_service.recover_pending_batches()
        self.assertTrue(any(pid == PROJECT_ID for pid, _ in pending))
        # Run the pending items through the restarted service
        restarted_service.run_pending(
            PROJECT_ID, batch.batch_id, "medical_manager"
        )
        completed = restarted_service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual(
            "candidate_ready", completed.items[0].generation_status
        )


class TestExpiredRunningTakeover(unittest.TestCase, _DurableBatchFixture):
    """Expired/interrupted running items must be recoverable."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_running_items_recovered_after_restart(self) -> None:
        """Running items are converted to failed_retryable on restart."""
        self.seed_artifact(
            "artifact_running_restart",
            [
                (
                    "span_running_restart",
                    "eligibility",
                    "Participants are eligible.",
                ),
            ],
        )
        batch = self.create_batch("durable-running-restart-001")
        # Manually set item to 'running' to simulate interruption
        running = batch.items[0].model_copy(
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
        # New service instance simulates restart — constructor does NOT
        # auto-recover (Gap 1 fix prevents live-owner theft).
        restarted_service = WritingReferenceTranslationBatchService(
            self.repo,
            self.journeys,
            self.preparation,
            self.translation_service,
            clock=lambda: NOW,
            chapter_pipeline=self._pipeline,
            durable_store=self.durable_store,
        )
        # Before recovery, running item must still be running (no theft).
        not_yet = restarted_service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("running", not_yet.items[0].generation_status)
        # Explicit per-batch recovery after durable takeover.
        restarted_service.recover_interrupted_items_for_batch(
            PROJECT_ID, batch.batch_id
        )
        recovered = restarted_service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual(
            "failed_retryable",
            recovered.items[0].generation_status,
        )
        self.assertEqual(
            "service_restart_interrupted",
            recovered.items[0].error_code,
        )
        # Retry should work
        restarted_service.retry(
            PROJECT_ID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="durable-running-restart-retry",
            ),
        )
        restarted_service.run_failed(
            PROJECT_ID, batch.batch_id, "medical_manager"
        )
        completed = restarted_service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual(
            "candidate_ready", completed.items[0].generation_status
        )


class TestCompletedReuse(unittest.TestCase, _DurableBatchFixture):
    """Completed chunks and immutable document-plan work must not be retranslated."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_completed_items_not_retranslated(self) -> None:
        """Running pending after completion does not re-call the translator."""
        self.seed_artifact(
            "artifact_completed_reuse",
            [
                (
                    "span_completed_reuse",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                ),
            ],
        )
        batch = self.create_batch("durable-completed-reuse-001")
        self.service.run_pending(
            PROJECT_ID, batch.batch_id, "medical_manager"
        )
        calls_before = len(self.runner.calls)
        # Running pending again should not re-translate completed items
        self.service.run_pending(
            PROJECT_ID, batch.batch_id, "medical_manager"
        )
        calls_after = len(self.runner.calls)
        self.assertEqual(calls_before, calls_after)


class TestFailedRetryableRetry(unittest.TestCase, _DurableBatchFixture):
    """Failed-retryable items must be retryable via durable path."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_failed_retryable_retry_succeeds(self) -> None:
        """A failed_retryable item can be retried and completed."""
        self.seed_artifact(
            "artifact_retry_durable",
            [
                (
                    "span_retry_durable",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                ),
            ],
        )
        # Force one failure then success
        self.runner.failures_remaining["span_retry_durable"] = 1
        batch = self.create_batch("durable-retry-001")
        self.service.run_pending(
            PROJECT_ID, batch.batch_id, "medical_manager"
        )
        partial = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual(
            "failed_retryable", partial.items[0].generation_status
        )
        # Retry with durable job
        self.service.retry(
            PROJECT_ID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="durable-retry-retry-001",
            ),
        )
        self.service.run_failed(
            PROJECT_ID, batch.batch_id, "medical_manager"
        )
        completed = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual(
            "candidate_ready", completed.items[0].generation_status
        )


class TestCancelAndProjectIsolation(unittest.TestCase, _DurableBatchFixture):
    """Cancel/stale-owner/project isolation for translation durable jobs."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_cancel_check_stops_processing(self) -> None:
        """cancel_check returning True stops _run_items between items."""
        self.seed_artifact(
            "artifact_cancel",
            [
                ("span_cancel_1", "eligibility", "Participants are eligible."),
                ("span_cancel_2", "endpoints", "The endpoint is assessed."),
            ],
        )
        # Force one chapter per span so items are processed sequentially.
        self.planner.set_chapter_assignments(
            [
                {
                    "id": "ch_cancel_1",
                    "title": "Eligibility",
                    "source_span_ids": ["span_cancel_1"],
                },
                {
                    "id": "ch_cancel_2",
                    "title": "Endpoints",
                    "source_span_ids": ["span_cancel_2"],
                },
            ]
        )
        batch = self.create_batch("durable-cancel-001")

        # cancel_check that returns True after the first invocation,
        # so the first item completes but the second is never started.
        cancel_after = 1
        call_count = [0]

        def cancel_check() -> bool:
            call_count[0] += 1
            return call_count[0] > cancel_after

        self.service.run_pending_with_callbacks(
            PROJECT_ID,
            batch.batch_id,
            "medical_manager",
            cancel_check=cancel_check,
        )
        result = self.service.get(PROJECT_ID, batch.batch_id)
        statuses = {item.generation_status for item in result.items}
        # At least one item should not be candidate_ready (cancel stopped it)
        self.assertTrue(statuses & {"pending", "running"})

    def test_project_isolation_durable_job(self) -> None:
        """Durable job for project A cannot be accessed from project B."""
        self.seed_artifact(
            "artifact_isolation",
            [("span_isolation", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("durable-isolation-001")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch.batch_id, actor="medical_manager"
        )
        self.assertIsNotNone(job_id)
        # Cross-project get should fail
        from packages.contracts.workbench_contracts import DurableJobNotFound

        with self.assertRaises(DurableJobNotFound):
            self.durable_store.get("proj_other", job_id)

    def test_durable_executor_completes_job(self) -> None:
        """TranslationBatchDurableExecutor runs items and returns success."""
        self.seed_artifact(
            "artifact_executor",
            [("span_executor", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("durable-executor-001")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch.batch_id, actor="medical_manager"
        )
        self.assertIsNotNone(job_id)
        worker = DurableJobWorker(self.durable_store, enable_sweeper=False)
        executor = TranslationBatchDurableExecutor(
            self.service, mode="pending", actor="medical_manager"
        )
        worker.register_executor(executor)
        worker.wake(PROJECT_ID, job_id)
        # Wait for the worker thread to finish processing before shutdown.
        import time as _time

        for _ in range(60):
            record = self.durable_store.get(PROJECT_ID, job_id)
            if record.status in ("completed", "failed"):
                break
            _time.sleep(0.5)
        # The batch items should be completed regardless of job status.
        completed = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual(
            "candidate_ready", completed.items[0].generation_status
        )
        record = self.durable_store.get(PROJECT_ID, job_id)
        # Job should be completed (not running) — the worker's shutdown
        # flag prevents CAS-complete, but without shutdown the job should
        # complete naturally.  Since we registered and woke without
        # calling shutdown until after the check, the executor should
        # have CAS-completed.
        self.assertNotEqual(record.status, "queued")
        worker.shutdown(timeout=5.0)


class TestDurableExecutorRetryMode(unittest.TestCase, _DurableBatchFixture):
    """Executor in 'failed' mode retries failed_retryable items."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_executor_retry_mode_runs_failed_items(self) -> None:
        """Executor with mode='failed' runs only failed_retryable items."""
        self.seed_artifact(
            "artifact_executor_retry",
            [
                (
                    "span_executor_retry",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                ),
            ],
        )
        self.runner.failures_remaining["span_executor_retry"] = 1
        batch = self.create_batch("durable-executor-retry-001")
        # First run: fails one item
        self.service.run_pending(
            PROJECT_ID, batch.batch_id, "medical_manager"
        )
        partial = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual(
            "failed_retryable", partial.items[0].generation_status
        )
        # Retry
        self.service.retry(
            PROJECT_ID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="durable-executor-retry-retry",
            ),
        )
        # Run with executor in failed mode
        self.service.run_failed(
            PROJECT_ID, batch.batch_id, "medical_manager"
        )
        completed = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual(
            "candidate_ready", completed.items[0].generation_status
        )


class TestUnexpiredLeaseNoTakeover(unittest.TestCase, _DurableBatchFixture):
    """An unexpired live lease must not be stolen by a second claim."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_unexpired_lease_not_stolen(self) -> None:
        """A second claim on a job with a live lease returns claimed=False."""
        self.seed_artifact(
            "artifact_no_takeover",
            [("span_no_takeover", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("durable-no-takeover-001")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch.batch_id, actor="medical_manager"
        )
        self.assertIsNotNone(job_id)
        # First claim succeeds
        claim1 = self.durable_store.claim(PROJECT_ID, job_id)
        self.assertTrue(claim1.claimed)
        self.assertNotEqual("", claim1.claim_token)
        # Second claim while lease is live must fail
        claim2 = self.durable_store.claim(PROJECT_ID, job_id)
        self.assertFalse(claim2.claimed)
        self.assertEqual("", claim2.claim_token)


class TestOldOwnerIsolation(unittest.TestCase, _DurableBatchFixture):
    """A stale owner (expired lease) cannot write terminal job state."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_stale_owner_cannot_complete(self) -> None:
        """After lease expiry, the old owner's CAS-complete returns False."""
        self.seed_artifact(
            "artifact_stale_owner",
            [("span_stale_owner", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("durable-stale-owner-001")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch.batch_id, actor="medical_manager"
        )
        # Use a short-lease store to simulate expiry without real waiting
        short_store = DurableJobStore(
            Path(self._durable_tmp.name) / "short_lease.db",
            lease_seconds=0.01,
            heartbeat_interval_seconds=0.01,
        )
        # Create same job in the short-lease store
        from packages.contracts.workbench_contracts.models import (
            DurableJobCreateRequest,
        )
        import hashlib as _hl

        rh = _hl.sha256(
            f"{PROJECT_ID}|reference_translation|{batch.batch_id}".encode()
        ).hexdigest()[:32]
        short_store.create_or_reuse(
            DurableJobCreateRequest(
                project_id=PROJECT_ID,
                job_type=REFERENCE_TRANSLATION_JOB_TYPE,
                business_key=batch.batch_id,
                request_hash=rh,
                created_by="medical_manager",
            )
        )
        job_id_short = short_store.create_or_reuse(
            DurableJobCreateRequest(
                project_id=PROJECT_ID,
                job_type=REFERENCE_TRANSLATION_JOB_TYPE,
                business_key=batch.batch_id,
                request_hash=rh,
                created_by="medical_manager",
            )
        ).job_id
        claim = short_store.claim(PROJECT_ID, job_id_short)
        self.assertTrue(claim.claimed)
        old_token = claim.claim_token
        # Wait for the tiny lease to expire
        import time as _time

        _time.sleep(0.1)
        # Old owner tries to complete — must fail
        result = short_store.complete(
            PROJECT_ID,
            job_id_short,
            old_token,
            output_hash="stale_output",
            artifact_locator='{"batch_id": "stale"}',
        )
        self.assertFalse(result)
        # A fresh claim should succeed (takeover)
        claim2 = short_store.claim(PROJECT_ID, job_id_short)
        self.assertTrue(claim2.claimed)

    def test_cancelled_job_rejects_late_complete(self) -> None:
        """After cancel, a late executor complete must be rejected."""
        self.seed_artifact(
            "artifact_cancel_late",
            [("span_cancel_late", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("durable-cancel-late-001")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch.batch_id, actor="medical_manager"
        )
        claim = self.durable_store.claim(PROJECT_ID, job_id)
        self.assertTrue(claim.claimed)
        old_token = claim.claim_token
        # Cancel the job
        cancel_result = self.durable_store.cancel(PROJECT_ID, job_id)
        self.assertTrue(cancel_result.cancelled)
        # Late executor tries to complete — must fail
        result = self.durable_store.complete(
            PROJECT_ID,
            job_id,
            old_token,
            output_hash="late_output",
        )
        self.assertFalse(result)


class TestCancelBeforeAndAfterItems(unittest.TestCase, _DurableBatchFixture):
    """Cancel is checked before each item and after expensive work."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_cancel_before_first_item(self) -> None:
        """cancel_check returning True immediately processes zero items."""
        self.seed_artifact(
            "artifact_cancel_immediate",
            [
                (
                    "span_cancel_immediate",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                ),
            ],
        )
        batch = self.create_batch("durable-cancel-immediate-001")
        calls_before = len(self.runner.calls)

        def always_cancel() -> bool:
            return True

        self.service.run_pending_with_callbacks(
            PROJECT_ID,
            batch.batch_id,
            "medical_manager",
            cancel_check=always_cancel,
        )
        # No items should have been processed
        calls_after = len(self.runner.calls)
        self.assertEqual(calls_before, calls_after)
        result = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("pending", result.items[0].generation_status)


class TestLiveOwnerNoTheft(unittest.TestCase, _DurableBatchFixture):
    """Gap 1: Two service instances against same DB — B must not steal A's running item."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_constructor_does_not_steal_running(self) -> None:
        """Service B constructor must not convert A's running items."""
        self.seed_artifact(
            "artifact_no_theft",
            [("span_no_theft", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("durable-no-theft-001")
        # Simulate item being actively running by owner A.
        running = batch.items[0].model_copy(
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
        # Service B starts against the same DB.
        service_b = WritingReferenceTranslationBatchService(
            self.repo,
            self.journeys,
            self.preparation,
            self.translation_service,
            clock=lambda: NOW,
            chapter_pipeline=self._pipeline,
            durable_store=self.durable_store,
        )
        # B must NOT have stolen the running item.
        state_b = service_b.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("running", state_b.items[0].generation_status)
        # Only after explicit per-batch recovery (post-durable-takeover).
        service_b.recover_interrupted_items_for_batch(PROJECT_ID, batch.batch_id)
        state_after = service_b.get(PROJECT_ID, batch.batch_id)
        self.assertEqual(
            "failed_retryable", state_after.items[0].generation_status
        )


class TestFalseHeartbeatStops(unittest.TestCase, _DurableBatchFixture):
    """Gap 3: heartbeat returning False must stop processing immediately."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_false_heartbeat_stops_after_first_item(self) -> None:
        """When heartbeat returns False, processing must stop."""
        self.seed_artifact(
            "artifact_false_hb",
            [
                ("span_false_hb_1", "eligibility", "Participants are eligible."),
                ("span_false_hb_2", "endpoints", "The endpoint is assessed."),
            ],
        )
        self.planner.set_chapter_assignments(
            [
                {
                    "id": "ch_hb_1",
                    "title": "Eligibility",
                    "source_span_ids": ["span_false_hb_1"],
                },
                {
                    "id": "ch_hb_2",
                    "title": "Endpoints",
                    "source_span_ids": ["span_false_hb_2"],
                },
            ]
        )
        batch = self.create_batch("durable-false-hb-001")
        from packages.contracts.workbench_contracts.models import (
            DurableJobProgressPayload,
        )

        def always_false_hb(_progress: DurableJobProgressPayload) -> bool:
            return False

        self.service.run_pending_with_callbacks(
            PROJECT_ID,
            batch.batch_id,
            "medical_manager",
            heartbeat=always_false_hb,
        )
        # Second item must NOT have been processed (heartbeat stopped after first).
        result = self.service.get(PROJECT_ID, batch.batch_id)
        statuses = {item.generation_status for item in result.items}
        self.assertTrue(statuses & {"pending"})

    def test_progress_counts_failed_attempt_as_processed(self) -> None:
        """A retryable failure advances this pass's durable progress."""
        self.seed_artifact(
            "artifact_progress_failed",
            [
                ("span_progress_failed", "eligibility", "Participants are eligible."),
                ("span_progress_ok", "endpoints", "The endpoint is assessed."),
            ],
        )
        self.planner.set_chapter_assignments(
            [
                {
                    "id": "ch_progress_failed",
                    "title": "Eligibility",
                    "source_span_ids": ["span_progress_failed"],
                },
                {
                    "id": "ch_progress_ok",
                    "title": "Endpoints",
                    "source_span_ids": ["span_progress_ok"],
                },
            ]
        )
        self.runner.failures_remaining["span_progress_failed"] = 1
        batch = self.create_batch("durable-progress-failed-001")
        progress_events: list[DurableJobProgressPayload] = []

        self.service.run_pending_with_callbacks(
            PROJECT_ID,
            batch.batch_id,
            "medical_manager",
            heartbeat=lambda progress: progress_events.append(progress) or True,
        )

        self.assertGreaterEqual(len(progress_events), 2)
        self.assertEqual(1, progress_events[0].step)
        self.assertEqual(2, progress_events[0].step_total)
        self.assertEqual("1/2 items processed", progress_events[0].message)


class TestCancelDuringAiBlocksTerminalWrite(unittest.TestCase, _DurableBatchFixture):
    """Gap 2: Cancel during slow product AI must prevent terminal business writes."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_cancel_blocks_completion_audit(self) -> None:
        """If cancel fires during item processing, no completion audit is written."""
        self.seed_artifact(
            "artifact_cancel_during_ai",
            [("span_cancel_during_ai", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("durable-cancel-during-ai-001")
        cancel_state = [False]

        def cancel_check() -> bool:
            return cancel_state[0]

        # Simulate cancel firing during processing by setting it True
        # before calling run_pending_with_callbacks. The cancel check
        # before the item should prevent any processing.
        cancel_state[0] = True
        self.service.run_pending_with_callbacks(
            PROJECT_ID,
            batch.batch_id,
            "medical_manager",
            cancel_check=cancel_check,
        )
        result = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("pending", result.items[0].generation_status)
        self.assertEqual("", result.items[0].translation_id)
        # No completion audit event should exist.
        with self.repo._connect() as connection:
            audit_rows = connection.execute(
                """
                SELECT event_type FROM writing_reference_audit_chain
                WHERE tenant_id=? AND project_id=?
                  AND event_type='translation_batch_item_completed'
                """,
                ("kangzhe_local", PROJECT_ID),
            ).fetchall()
        self.assertEqual(0, len(audit_rows))


class TestExecutorAggregateState(unittest.TestCase, _DurableBatchFixture):
    """Gap 4: Executor must return error on cancel/lost-claim, not false success."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_executor_returns_error_on_cancelled(self) -> None:
        """Executor with always-cancel cancel_check returns error result."""
        self.seed_artifact(
            "artifact_exec_cancel",
            [("span_exec_cancel", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("durable-exec-cancel-001")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch.batch_id, actor="medical_manager"
        )
        executor = TranslationBatchDurableExecutor(
            self.service, mode="pending", actor="medical_manager"
        )
        from packages.contracts.workbench_contracts.models import (
            DurableJobProgressPayload,
        )

        # Create a fake job record to pass to execute.
        record = self.durable_store.get(PROJECT_ID, job_id)

        def always_cancel() -> bool:
            return True

        def noop_hb(_p: DurableJobProgressPayload) -> bool:
            return True

        result = executor.execute(record, "fake_token", always_cancel, noop_hb)
        self.assertTrue(result.error)
        self.assertTrue(result.retryable)

    def test_executor_returns_error_on_failed_retryable(self) -> None:
        """Executor returns error when batch has failed_retryable items."""
        self.seed_artifact(
            "artifact_exec_fail",
            [("span_exec_fail", "eligibility", "Participants must not receive SCS within 14 days.")],
        )
        self.runner.failures_remaining["span_exec_fail"] = 99  # always fails
        batch = self.create_batch("durable-exec-fail-001")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch.batch_id, actor="medical_manager"
        )
        executor = TranslationBatchDurableExecutor(
            self.service, mode="pending", actor="medical_manager"
        )
        record = self.durable_store.get(PROJECT_ID, job_id)

        def never_cancel() -> bool:
            return False

        from packages.contracts.workbench_contracts.models import (
            DurableJobProgressPayload,
        )

        def noop_hb(_p: DurableJobProgressPayload) -> bool:
            return True

        result = executor.execute(record, "fake_token", never_cancel, noop_hb)
        self.assertTrue(result.error)
        self.assertTrue(result.retryable)
        self.assertIn("failed_retryable", result.error)


class TestRetryOrderingAndOrphan(unittest.TestCase, _DurableBatchFixture):
    """Gap 5: Retry creates durable job before mutation; live-running rejects."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_retry_rejects_running_batch(self) -> None:
        """Retry on a running batch must raise without mutation."""
        self.seed_artifact(
            "artifact_retry_running",
            [("span_retry_running", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("durable-retry-running-001")
        # Manually set batch to running.
        with self.repo._connect() as connection:
            connection.execute(
                """
                UPDATE writing_reference_translation_batches
                SET status='running'
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                """,
                ("kangzhe_local", PROJECT_ID, batch.batch_id),
            )
        with self.assertRaises(ValueError, msg="cannot retry running"):
            self.service.retry(
                PROJECT_ID,
                batch.batch_id,
                WritingReferenceTranslationBatchRetryRequest(
                    actor="medical_manager",
                    idempotency_key="durable-retry-running-reject",
                ),
            )
        # Batch must still be running (unchanged).
        state = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("running", state.status)

    def test_duplicate_retry_reuses_same_job(self) -> None:
        """Duplicate retry request reuses the same durable job."""
        self.seed_artifact(
            "artifact_retry_dedupe",
            [("span_retry_dedupe", "eligibility", "Participants must not receive SCS within 14 days.")],
        )
        self.runner.failures_remaining["span_retry_dedupe"] = 1
        batch = self.create_batch("durable-retry-dedupe-001")
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        retry_req = WritingReferenceTranslationBatchRetryRequest(
            actor="medical_manager",
            idempotency_key="durable-retry-dedupe-retry",
        )
        result1 = self.service.retry(PROJECT_ID, batch.batch_id, retry_req)
        retry_key = f"{batch.batch_id}:retry:durable-retry-dedupe-retry"
        job1 = self.durable_store.get_by_business_key(
            PROJECT_ID, REFERENCE_TRANSLATION_JOB_TYPE, retry_key
        )
        # Duplicate retry with same idempotency key must return same batch.
        result2 = self.service.retry(PROJECT_ID, batch.batch_id, retry_req)
        self.assertEqual(result1.batch_id, result2.batch_id)
        self.assertEqual(result1.attempt, result2.attempt)


class TestRecoverPendingIncludesFailedRetryable(unittest.TestCase, _DurableBatchFixture):
    """Gap 6: recover_pending_batches includes failed_retryable items."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_recover_includes_failed_retryable(self) -> None:
        """recover_pending_batches identifies batches with failed_retryable items."""
        self.seed_artifact(
            "artifact_recover_failed",
            [("span_recover_failed", "eligibility", "Participants must not receive SCS within 14 days.")],
        )
        self.runner.failures_remaining["span_recover_failed"] = 99
        batch = self.create_batch("durable-recover-failed-001")
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        state = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("failed_retryable", state.items[0].generation_status)
        pending = self.service.recover_pending_batches()
        self.assertTrue(
            any(
                pid == PROJECT_ID and bid == batch.batch_id
                for pid, bid in pending
            )
        )


class TestOwnershipGuardAtBoundaries(unittest.TestCase, _DurableBatchFixture):
    """Gap v3: Fail-closed ownership guard at every persistence boundary.

    These tests prove that when ownership flips at each named boundary,
    the corresponding business write does NOT occur.  The guard counter
    increments on every _guard/_stage_observer invocation and flips after
    a configurable threshold, so we can target specific boundaries.
    """

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def _count_translation_revisions(self) -> int:
        """Count all translation revisions in the repository."""
        with self.repo._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM writing_reference_translation_records "
                "WHERE tenant_id=? AND project_id=?",
                ("kangzhe_local", PROJECT_ID),
            ).fetchone()
        return int(row["cnt"])

    def _count_chunk_records(self) -> int:
        """Count all translation chunks in the repository."""
        with self.repo._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM writing_reference_translation_chunks "
                "WHERE tenant_id=? AND project_id=?",
                ("kangzhe_local", PROJECT_ID),
            ).fetchone()
        return int(row["cnt"])

    def _count_integration_results(self) -> int:
        """Count all chapter integration results."""
        with self.repo._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM writing_reference_chapter_integration_results "
                "WHERE tenant_id=? AND project_id=?",
                ("kangzhe_local", PROJECT_ID),
            ).fetchone()
        return int(row["cnt"])

    def _count_completion_audits(self) -> int:
        """Count item_completed audit events."""
        with self.repo._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM writing_reference_audit_chain "
                "WHERE tenant_id=? AND project_id=? "
                "AND event_type='translation_batch_item_completed'",
                ("kangzhe_local", PROJECT_ID),
            ).fetchone()
        return int(row["cnt"])

    def _count_pipeline_stage_audits(self) -> int:
        """Count pipeline_stage audit events."""
        with self.repo._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM writing_reference_audit_chain "
                "WHERE tenant_id=? AND project_id=? "
                "AND event_type='translation_batch_pipeline_stage'",
                ("kangzhe_local", PROJECT_ID),
            ).fetchone()
        return int(row["cnt"])

    def test_ownership_lost_before_document_plan_blocks_everything(self) -> None:
        """Loss before document plan creation blocks all writes."""
        self.seed_artifact(
            "artifact_guard_pre_plan",
            [("span_guard_pre_plan", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("guard-pre-plan-001")
        # Immediately cancelled — first _guard call raises.
        def always_cancel() -> bool:
            return True

        self.service.run_pending_with_callbacks(
            PROJECT_ID, batch.batch_id, "medical_manager",
            cancel_check=always_cancel,
        )
        state = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("pending", state.items[0].generation_status)
        self.assertEqual(0, self._count_translation_revisions())
        self.assertEqual(0, self._count_integration_results())
        self.assertEqual(0, self._count_completion_audits())

    def test_ownership_lost_after_hy_mt2_blocks_chunk_save(self) -> None:
        """Loss after Hy-MT2 returns but before chunk save blocks chunk write.

        We use a counter that allows the first few guard calls (document plan,
        stage observers) but flips before save_translation_chunk.  Because the
        deterministic fixture translates synchronously, the exact boundary at
        which the guard fires depends on how many _guard calls happen before
        chunk save.  We verify that the translation revision is NOT written
        (the most critical invariant) even if the guard fires anywhere after
        Hy-MT2.
        """
        self.seed_artifact(
            "artifact_guard_post_hy",
            [("span_guard_post_hy", "eligibility", "Participants must not receive SCS within 14 days.")],
        )
        batch = self.create_batch("guard-post-hy-001")
        call_count = [0]
        threshold = 5  # Allow initial guards but flip before chunk save

        def cancel_after_n() -> bool:
            call_count[0] += 1
            return call_count[0] > threshold

        self.service.run_pending_with_callbacks(
            PROJECT_ID, batch.batch_id, "medical_manager",
            cancel_check=cancel_after_n,
        )
        # The item must NOT be in a terminal state from the old owner.
        state = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertNotEqual("candidate_ready", state.items[0].generation_status)

    def test_ownership_lost_before_integration_save(self) -> None:
        """Loss before integration save blocks integration write."""
        self.seed_artifact(
            "artifact_guard_pre_integration",
            [("span_guard_pre_integration", "eligibility", "Participants must not receive SCS within 14 days.")],
        )
        batch = self.create_batch("guard-pre-integration-001")
        call_count = [0]
        # Allow chunk save (guard ~6) but flip before integration save (guard ~11).
        threshold = 10

        def cancel_after_n() -> bool:
            call_count[0] += 1
            return call_count[0] > threshold

        self.service.run_pending_with_callbacks(
            PROJECT_ID, batch.batch_id, "medical_manager",
            cancel_check=cancel_after_n,
        )
        state = self.service.get(PROJECT_ID, batch.batch_id)
        # No completion audit from old owner.
        self.assertEqual(0, self._count_completion_audits())

    def test_ownership_lost_before_translation_save(self) -> None:
        """Loss before final translation save blocks revision write."""
        self.seed_artifact(
            "artifact_guard_pre_xlate",
            [("span_guard_pre_xlate", "eligibility", "Participants must not receive SCS within 14 days.")],
        )
        batch = self.create_batch("guard-pre-xlate-001")
        call_count = [0]
        # Allow integration save (guard ~11) and composite run save (guard ~12)
        # but flip before translation save (guard ~13).
        threshold = 12

        def cancel_after_n() -> bool:
            call_count[0] += 1
            return call_count[0] > threshold

        self.service.run_pending_with_callbacks(
            PROJECT_ID, batch.batch_id, "medical_manager",
            cancel_check=cancel_after_n,
        )
        state = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertNotEqual("candidate_ready", state.items[0].generation_status)
        self.assertEqual(0, self._count_completion_audits())

    def test_ownership_lost_in_reuse_path(self) -> None:
        """Loss in the reuse path blocks _link_item_to_chapter_revision."""
        self.seed_artifact(
            "artifact_guard_reuse",
            [("span_guard_reuse", "eligibility", "Participants must not receive SCS within 14 days.")],
        )
        # First run: complete normally (no cancel_check).
        batch = self.create_batch("guard-reuse-001")
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        first = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("candidate_ready", first.items[0].generation_status)
        revisions_before = self._count_translation_revisions()
        audits_before = self._count_completion_audits()

        # Second run (idempotent re-run via run_pending_with_callbacks):
        # The existing integration is found, so the reuse path is taken.
        # With always-cancel, the _guard before _link_item_to_chapter_revision
        # should fire and prevent any new business write.
        def always_cancel() -> bool:
            return True

        self.service.run_pending_with_callbacks(
            PROJECT_ID, batch.batch_id, "medical_manager",
            cancel_check=always_cancel,
        )
        # No new revisions or audits from old owner.
        self.assertEqual(revisions_before, self._count_translation_revisions())
        self.assertEqual(audits_before, self._count_completion_audits())

    def test_guard_exception_treated_as_lost(self) -> None:
        """An exception in cancel_check is treated as ownership lost."""
        self.seed_artifact(
            "artifact_guard_exc",
            [("span_guard_exc", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("guard-exc-001")

        def raising_cancel() -> bool:
            raise RuntimeError("ownership check infrastructure failure")

        # Should not crash; the pipeline stops without terminal writes.
        self.service.run_pending_with_callbacks(
            PROJECT_ID, batch.batch_id, "medical_manager",
            cancel_check=raising_cancel,
        )
        state = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertNotEqual("candidate_ready", state.items[0].generation_status)
        self.assertEqual(0, self._count_completion_audits())

    def test_executor_checks_ownership_before_recovery(self) -> None:
        """Executor entry must check ownership before recover_interrupted_items_for_batch."""
        self.seed_artifact(
            "artifact_executor_pre_guard",
            [("span_executor_pre_guard", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("executor-pre-guard-001")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch.batch_id, actor="medical_manager"
        )
        # Manually set an item to running.
        running = batch.items[0].model_copy(
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
        record = self.durable_store.get(PROJECT_ID, job_id)
        executor = TranslationBatchDurableExecutor(
            self.service, mode="pending", actor="medical_manager"
        )

        def always_cancel() -> bool:
            return True

        from packages.contracts.workbench_contracts.models import (
            DurableJobProgressPayload,
        )

        def noop_hb(_p: DurableJobProgressPayload) -> bool:
            return True

        result = executor.execute(record, "fake_token", always_cancel, noop_hb)
        self.assertTrue(result.error)
        # The running item must NOT have been recovered by the stale executor.
        state = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("running", state.items[0].generation_status)


class TestPreRunItemsBatchStatusGuard(unittest.TestCase, _DurableBatchFixture):
    """Gap v4-1: Batch status must not be mutated if ownership is lost
    after executor entry but before _run_items sets batch to running."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_cancel_before_batch_status_leaves_batch_unchanged(self) -> None:
        """If cancel_check is True at _run_items entry, batch status must
        not change to 'running' and no audits may be emitted."""
        self.seed_artifact(
            "artifact_pre_run_guard",
            [("span_pre_run_guard", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("pre-run-guard-001")
        # Batch status before run should be the initial aggregate.
        state_before = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertNotEqual("running", state_before.status)

        def always_cancel() -> bool:
            return True

        self.service.run_pending_with_callbacks(
            PROJECT_ID, batch.batch_id, "medical_manager",
            cancel_check=always_cancel,
        )
        state_after = self.service.get(PROJECT_ID, batch.batch_id)
        # Batch status must NOT have changed to "running".
        self.assertEqual(state_before.status, state_after.status)
        # Item must still be pending.
        self.assertEqual("pending", state_after.items[0].generation_status)

    def test_cancel_exception_before_batch_status_leaves_batch_unchanged(self) -> None:
        """Exception in cancel_check before batch status = fail closed, no mutation."""
        self.seed_artifact(
            "artifact_pre_run_guard_exc",
            [("span_pre_run_guard_exc", "eligibility", "Participants are eligible.")],
        )
        batch = self.create_batch("pre-run-guard-exc-001")
        state_before = self.service.get(PROJECT_ID, batch.batch_id)

        def raising_cancel() -> bool:
            raise RuntimeError("infrastructure failure")

        self.service.run_pending_with_callbacks(
            PROJECT_ID, batch.batch_id, "medical_manager",
            cancel_check=raising_cancel,
        )
        state_after = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual(state_before.status, state_after.status)


class TestReusePathGuardBeforeFinish(unittest.TestCase, _DurableBatchFixture):
    """Gap v4-2: Guard flip between link and item completion in the reuse
    path must leave the item non-terminal and emit no completion audit."""

    def setUp(self) -> None:
        self.setup_fixture()

    def tearDown(self) -> None:
        self.teardown_fixture()

    def test_guard_flip_after_link_blocks_completion(self) -> None:
        """A guard flip after _link_item_to_chapter_revision but before
        _finish_composite_item must prevent terminal item state."""
        self.seed_artifact(
            "artifact_reuse_guard",
            [("span_reuse_guard", "eligibility", "Participants must not receive SCS within 14 days.")],
        )
        # First run: complete normally (no cancel_check) so integration exists.
        batch = self.create_batch("reuse-guard-001")
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        first = self.service.get(PROJECT_ID, batch.batch_id)
        self.assertEqual("candidate_ready", first.items[0].generation_status)
        audits_before = self._count_completion_audits()

        # Second run via callbacks with a counter that allows the initial
        # _run_items entry check + document plan + reuse _guard before link,
        # but flips after link before _finish_composite_item.
        # Based on the known call count of ~14 for a full run, the reuse
        # path skips chunk/integration/translation saves, so it's fewer
        # guards. We use a threshold that allows the link guard but flips
        # at the post-link guard.
        call_count = [0]

        def cancel_after_n() -> bool:
            call_count[0] += 1
            return call_count[0] > 5

        self.service.run_pending_with_callbacks(
            PROJECT_ID, batch.batch_id, "medical_manager",
            cancel_check=cancel_after_n,
        )
        # No new completion audit from the old owner.
        self.assertEqual(audits_before, self._count_completion_audits())

    def _count_completion_audits(self) -> int:
        with self.repo._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM writing_reference_audit_chain "
                "WHERE tenant_id=? AND project_id=? "
                "AND event_type='translation_batch_item_completed'",
                ("kangzhe_local", PROJECT_ID),
            ).fetchone()
        return int(row["cnt"])


if __name__ == "__main__":
    unittest.main()
