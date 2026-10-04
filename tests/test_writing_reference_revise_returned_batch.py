"""R26 self-check #2, P0-A counterexample (red-first, then fix).

Field evidence (proj_user_953921d37b47, 2026-10-02): the designed in-product
recovery loop for fidelity-blocked regulatory translations is dead —

  fidelity-blocked batch translation
  -> author records a "returned" medical review (3 landed in DB)
  -> author clicks 按审核意见重新生成 (POST /references/translations/{id}/revisions)
  -> NO new translation revision (DB shows revision 1 only),
     NO durable job, NO persisted upper-layer stage run with
     owner_type=direct_translation, NO error surfaced in the UI.

Root cause: the revise endpoint runs the composite chapter pipeline
(plan reuse -> Hy-MT2 body -> Flash QC) synchronously inside one HTTP
request — a multi-minute model workload with no durable job, no progress
surface, and errors that evaporate on client disconnect, unlike every other
long AI action in this product (triage, translation batch, section
candidates, full draft) which runs as a durable job.

This module pins both halves of the fixed contract:
- service level: a batch-created fidelity-blocked translation with a current
  returned medical review MUST produce revision 2 through
  WritingReferenceTranslationService.revise (used by the durable executor);
- API level: POST /references/translations/{id}/revisions must ACCEPT a
  reference_translation_revise durable job (immediate 4xx only for contract
  violations) and the durable worker must drive it to revision 2.
"""
from __future__ import annotations

import json
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts.models import (
    WritingReferenceTranslationBatchCreateRequest,
    WritingReferenceTranslationRevisionRequest,
)
from services.api.app.main import app
from services.api.app.medical_writing_durable_jobs import (
    DurableJobStore,
    DurableJobWorker,
)
from services.api.app.writing_reference_translation_batch import (
    TranslationBatchDurableExecutor,
)
from tests.test_writing_reference_translation_batch import (
    GLOSSARY_VERSION,
    PROJECT_ID,
    SNAPSHOT_ID,
)
from tests.test_writing_reference_translation_durable_jobs import (
    _DurableBatchFixture,
)

SOURCE_TEXT = "The primary endpoint is assessed at Week 16."
SPAN_ID = "span_revise_returned"
ARTIFACT_ID = "artifact_revise_returned"


def _run_batch_to_completion(service, durable_store, key: str):
    batch = service.create(
        PROJECT_ID,
        WritingReferenceTranslationBatchCreateRequest(
            snapshot_id=SNAPSHOT_ID,
            glossary_version=GLOSSARY_VERSION,
            anchor_filter=["objectives_endpoints"],
            actor="medical_manager",
            idempotency_key=key,
        ),
    )
    job_id = service.ensure_reference_translation_job(
        PROJECT_ID, batch.batch_id, actor="medical_manager"
    )
    assert job_id is not None
    worker = DurableJobWorker(durable_store, enable_sweeper=False)
    worker.register_executor(
        TranslationBatchDurableExecutor(
            service, mode="pending", actor="medical_manager"
        )
    )
    worker.wake(PROJECT_ID, job_id)
    for _ in range(120):
        record = durable_store.get(PROJECT_ID, job_id)
        if record.status in ("completed", "failed"):
            break
        time.sleep(0.5)
    worker.shutdown()
    return service.get(PROJECT_ID, batch.batch_id)


class TestReviseAfterReturnedReviewOnBatchTranslation(
    unittest.TestCase, _DurableBatchFixture
):
    def setUp(self) -> None:
        self.setup_fixture()
        # 1. Seed one protocol artifact whose single span is anchored to the
        #    key objectives_endpoints chapter (the field failure anchor).
        self.seed_artifact(
            ARTIFACT_ID,
            [(SPAN_ID, "objectives_endpoints", SOURCE_TEXT)],
        )
        # 2. Force the Hy-MT2 body to drift so the deterministic fidelity gate
        #    blocks the first candidate — the exact field state.
        self._translator.blocked_spans = {SPAN_ID}
        self.runner.blocked_spans = {SPAN_ID}

    def tearDown(self) -> None:
        self.teardown_fixture()


    def test_revise_after_returned_review_produces_revision_two(self) -> None:
        settled = _run_batch_to_completion(self.service, self.durable_store, "revise-returned-create-001")
        self.assertEqual(
            "fidelity_blocked",
            settled.items[0].generation_status,
            "fixture must reproduce the fidelity-blocked field state",
        )
        translations = self.repo.translations(PROJECT_ID, span_id=SPAN_ID)
        self.assertEqual(1, len(translations))
        blocked = translations[0]
        self.assertEqual(1, blocked.revision)
        self.assertEqual("blocked", blocked.fidelity_status)

        # 3. Author returns the blocked candidate (landed 3x in the field DB).
        review = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=blocked.translation_id,
            translation_revision=blocked.revision,
            decision="returned",
            comment="请按原文修正终点评价时间窗后重新生成。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="revise-returned-review-001",
        )

        # 4. The recovery act itself: what the 按审核意见重新生成 button calls.
        self._translator.blocked_spans.clear()
        self.runner.blocked_spans.clear()
        revised = self.translation_service.revise(
            PROJECT_ID,
            blocked.translation_id,
            WritingReferenceTranslationRevisionRequest(
                expected_translation_revision=blocked.revision,
                medical_review_id=review.review_id,
                idempotency_key="revise-returned-revision-001",
            ),
        )

        # 5. The loop must close: revision 2 exists and is what the workspace
        #    per-span lookup returns to the UI.
        self.assertEqual(2, revised.revision)
        after = self.repo.translations(PROJECT_ID, span_id=SPAN_ID)
        self.assertEqual(1, len(after))
        self.assertEqual(2, after[0].revision)
        self.assertEqual("passed", after[0].fidelity_status)


class TestReviseEndpointAcceptsDurableJob(unittest.TestCase, _DurableBatchFixture):
    """API-level counterexample: the revise act must be a durable job.

    The composite revise is a multi-minute model workload; running it inside
    the HTTP request left the author with a silently dead button (R26
    self-check #2 P0-A: no revision, no durable job, no surfaced error).
    The endpoint must validate the returned-review contract synchronously
    (4xx for real violations) and otherwise ACCEPT a
    reference_translation_revise durable job that the worker completes.
    """

    def setUp(self) -> None:
        self.setup_fixture()
        self.seed_artifact(
            ARTIFACT_ID,
            [(SPAN_ID, "objectives_endpoints", SOURCE_TEXT)],
        )
        self._translator.blocked_spans = {SPAN_ID}
        self.runner.blocked_spans = {SPAN_ID}
        settled = _run_batch_to_completion(self.service, self.durable_store, "revise-returned-api-create-001")
        self.assertEqual("fidelity_blocked", settled.items[0].generation_status)
        translations = self.repo.translations(PROJECT_ID, span_id=SPAN_ID)
        self.assertEqual(1, len(translations))
        self.blocked = translations[0]
        self.review = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=self.blocked.translation_id,
            translation_revision=self.blocked.revision,
            decision="returned",
            comment="请按原文修正终点评价时间窗后重新生成。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="revise-returned-api-review-001",
        )
        # Un-block the deterministic body so the revise attempt can pass.
        self._translator.blocked_spans.clear()
        self.runner.blocked_spans.clear()
        # API surface with the fixture repo/service/store injected, plus a
        # local worker that owns the reference_translation_revise executor
        # once it exists (guarded so the counterexample runs — and fails on
        # assertions — against the current synchronous endpoint too).
        try:
            from services.api.app.writing_reference import (
                TranslationReviseDurableExecutor,
            )
        except ImportError:
            TranslationReviseDurableExecutor = None  # type: ignore[assignment]

        self.revise_worker = DurableJobWorker(self.durable_store, enable_sweeper=False)
        if TranslationReviseDurableExecutor is not None:
            self.revise_worker.register_executor(
                TranslationReviseDurableExecutor(self.translation_service)
            )
        self.client = TestClient(app)
        self.patches = [
            patch("services.api.app.main.writing_reference_repository", self.repo),
            patch(
                "services.api.app.main.writing_reference_translation_service",
                self.translation_service,
            ),
            patch("services.api.app.main.mw_durable_store", self.durable_store),
            patch("services.api.app.main.mw_durable_worker", self.revise_worker),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])
        self.addCleanup(self.revise_worker.shutdown)
        self.addCleanup(self.teardown_fixture)

    def test_revise_returns_accepted_durable_job_and_worker_reaches_revision_two(self) -> None:
        response = self.client.post(
            f"/api/projects/{PROJECT_ID}/medical-writing/references/translations/"
            f"{self.blocked.translation_id}/revisions",
            json={
                "expected_translation_revision": self.blocked.revision,
                "medical_review_id": self.review.review_id,
                "actor": "medical_manager",
                "idempotency_key": "revise-returned-api-post-001",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertTrue(body.get("accepted"), body)
        job_id = body.get("job_id")
        self.assertTrue(job_id, body)
        self.assertEqual("queued", body.get("status"))

        # The durable worker (woken by the endpoint) drives the revise.
        for _ in range(120):
            record = self.durable_store.get(PROJECT_ID, job_id)
            if record.status in ("completed", "failed"):
                break
            time.sleep(0.5)
        record = self.durable_store.get(PROJECT_ID, job_id)
        self.assertEqual("completed", record.status, record.error_summary)
        locator = json.loads(record.artifact_locator or "{}")
        self.assertEqual(self.blocked.translation_id, locator.get("translation_id"))
        self.assertEqual(2, locator.get("revision"))
        after = self.repo.translations(PROJECT_ID, span_id=SPAN_ID)
        self.assertEqual(2, after[0].revision)
        self.assertEqual("passed", after[0].fidelity_status)

    def test_revise_rejects_non_returned_review_contract_immediately(self) -> None:
        response = self.client.post(
            f"/api/projects/{PROJECT_ID}/medical-writing/references/translations/"
            f"{self.blocked.translation_id}/revisions",
            json={
                "expected_translation_revision": self.blocked.revision,
                "medical_review_id": "wref_review_does_not_exist",
                "actor": "medical_manager",
                "idempotency_key": "revise-returned-api-post-bad-001",
            },
        )
        self.assertEqual(404, response.status_code)
        # No job may be created for a contract violation.
        jobs = self.durable_store.list_jobs(PROJECT_ID) if hasattr(
            self.durable_store, "list_jobs"
        ) else []
        self.assertEqual([], [j for j in jobs if j.job_type == "reference_translation_revise"])

    def test_second_regenerate_click_after_terminal_attempt_creates_a_new_job(self) -> None:
        """A failed/cancelled first attempt must not block the author's next click.

        create_or_reuse raises a conflict when one business key arrives with
        different request hashes; the revise business key must therefore be
        per-attempt (the client generates a fresh idempotency key per click).
        A no-op executor isolates this to the enqueueing contract — the real
        execution path is covered by the worker test above.
        """
        from services.api.app.medical_writing_durable_jobs import DurableJobResult
        from services.api.app.writing_reference import (
            REFERENCE_TRANSLATION_REVISE_JOB_TYPE,
        )

        class _NoopReviseExecutor:
            job_type = REFERENCE_TRANSLATION_REVISE_JOB_TYPE

            def execute(self, job, claim_token, cancel_check, heartbeat):
                del job, claim_token, cancel_check, heartbeat
                return DurableJobResult(artifact_locator="noop-revise")

        self.revise_worker.register_executor(_NoopReviseExecutor())
        first = self.client.post(
            f"/api/projects/{PROJECT_ID}/medical-writing/references/translations/"
            f"{self.blocked.translation_id}/revisions",
            json={
                "expected_translation_revision": self.blocked.revision,
                "medical_review_id": self.review.review_id,
                "actor": "medical_manager",
                "idempotency_key": "revise-returned-api-post-first-001",
            },
        )
        self.assertEqual(200, first.status_code, first.text)
        first_job = first.json()["job_id"]

        second = self.client.post(
            f"/api/projects/{PROJECT_ID}/medical-writing/references/translations/"
            f"{self.blocked.translation_id}/revisions",
            json={
                "expected_translation_revision": self.blocked.revision,
                "medical_review_id": self.review.review_id,
                "actor": "medical_manager",
                "idempotency_key": "revise-returned-api-post-second-002",
            },
        )
        self.assertEqual(200, second.status_code, second.text)
        body = second.json()
        self.assertTrue(body.get("accepted"), body)
        self.assertNotEqual(first_job, body["job_id"])


if __name__ == "__main__":
    unittest.main()
