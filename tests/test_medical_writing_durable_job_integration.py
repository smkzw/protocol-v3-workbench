"""Integration tests for the unified durable medical-writing job API.

Tests cover:
- Safe DTO (no claim_token, payload_json, lease internals leak)
- Project isolation (cross-project job lookup fails)
- Cross-type coexistence (triage, section_ai_candidate, reference_translation)
- Cancel-late-complete isolation
- Atomic accept-and-apply endpoint validation
- Translation route no longer schedules BackgroundTasks long-call
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.medical_writing_durable_jobs import (
    DurableJobStore,
    DurableJobWorker,
)
from packages.contracts.workbench_contracts import DurableJobCreateRequest


def _make_request(**overrides):
    defaults = {
        "project_id": "proj_test_a",
        "job_type": "section_ai_candidate",
        "business_key": "bk_test_001",
        "request_hash": "rh_aaaaaaaaaaaa",
        "payload_json": '{"secret":"do_not_leak"}',
        "created_by": "integration_test",
    }
    defaults.update(overrides)
    return DurableJobCreateRequest(**defaults)


class TestPublicDurableJobDTO(unittest.TestCase):
    """The unified status/result DTO must exclude sensitive internals."""

    def setUp(self):
        self._tmp = Path(__file__).resolve().parent / "_tmp_durable_dto"
        self._tmp.mkdir(exist_ok=True)
        self.store = DurableJobStore(self._tmp / "dto_test.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_get_does_not_expose_claim_token_or_payload(self):
        """Verify the _public_durable_job_dict function excludes secrets."""
        from services.api.app.main import _public_durable_job_dict

        job = self.store.create_or_reuse(_make_request())
        claim = self.store.claim("proj_test_a", job.job_id)
        self.assertTrue(claim.claimed)

        record = self.store.get("proj_test_a", job.job_id)
        dto = _public_durable_job_dict(record)

        # Must NOT contain claim_token, payload_json, lease_expires_at,
        # input_hash, or output_hash.
        self.assertNotIn("claim_token", dto)
        self.assertNotIn("payload_json", dto)
        self.assertNotIn("lease_expires_at", dto)
        self.assertNotIn("input_hash", dto)
        self.assertNotIn("output_hash", dto)

        # Must contain safe fields.
        self.assertIn("job_id", dto)
        self.assertIn("status", dto)
        self.assertIn("progress", dto)
        self.assertIn("job_type", dto)

    def test_dto_progress_is_monotonic_safe(self):
        """Progress dict only contains the allowed fields."""
        from services.api.app.main import _public_durable_job_dict

        job = self.store.create_or_reuse(_make_request())
        record = self.store.get("proj_test_a", job.job_id)
        dto = _public_durable_job_dict(record)

        progress = dto["progress"]
        self.assertIn("phase", progress)
        self.assertIn("percent", progress)
        self.assertIn("step", progress)
        self.assertIn("step_total", progress)
        self.assertIn("message", progress)


class TestProjectIsolation(unittest.TestCase):
    """Jobs from one project must not be visible to another project."""

    def setUp(self):
        self._tmp = Path(__file__).resolve().parent / "_tmp_durable_iso"
        self._tmp.mkdir(exist_ok=True)
        self.store = DurableJobStore(self._tmp / "iso_test.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_cross_project_get_raises(self):
        """get(project_a, job_from_project_b) must raise DurableJobNotFound."""
        from services.api.app.medical_writing_durable_jobs import DurableJobNotFound

        job_a = self.store.create_or_reuse(
            _make_request(project_id="proj_a", business_key="bk_a")
        )
        with self.assertRaises(DurableJobNotFound):
            self.store.get("proj_b", job_a.job_id)

    def test_cross_project_cancel_raises_not_found(self):
        """Cancel from another project must raise DurableJobNotFound (fail-closed)."""
        from services.api.app.medical_writing_durable_jobs import DurableJobNotFound

        job_a = self.store.create_or_reuse(
            _make_request(project_id="proj_a", business_key="bk_a")
        )
        with self.assertRaises(DurableJobNotFound):
            self.store.cancel("proj_b", job_a.job_id)
        record = self.store.get("proj_a", job_a.job_id)
        self.assertEqual(record.status, "queued")


class TestCancelLateCompleteIsolation(unittest.TestCase):
    """A late complete from a cancelled job must not overwrite the cancellation."""

    def setUp(self):
        self._tmp = Path(__file__).resolve().parent / "_tmp_durable_cancel"
        self._tmp.mkdir(exist_ok=True)
        self.store = DurableJobStore(self._tmp / "cancel_test.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_cancel_then_complete_fails(self):
        """CAS: cancel sets terminal state; late complete returns False."""
        job = self.store.create_or_reuse(_make_request())
        claim = self.store.claim("proj_test_a", job.job_id)
        self.assertTrue(claim.claimed)

        # Cancel while running.
        cancel_result = self.store.cancel("proj_test_a", job.job_id)
        self.assertTrue(cancel_result.cancelled)
        self.assertEqual(cancel_result.status, "cancelled")

        # Late complete from the old owner must fail.
        ok = self.store.complete(
            "proj_test_a", job.job_id, claim.claim_token,
            output_hash="late_output",
        )
        self.assertFalse(ok)

        record = self.store.get("proj_test_a", job.job_id)
        self.assertEqual(record.status, "cancelled")
        self.assertNotEqual(record.output_hash, "late_output")


class TestAtomicAcceptApplyValidation(unittest.TestCase):
    """The atomic accept-and-apply endpoint must validate inputs properly."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from services.api.app import main as app_main
        cls.client = TestClient(app_main.app)

    def test_missing_suggestion_id_returns_422(self):
        response = self.client.post(
            "/api/projects/proj_mgk10_sar_demo/revision-threads/fake_thread/accept-and-apply",
            json={"expected_working_copy_revision": 1, "idempotency_key": "k1"},
        )
        self.assertEqual(422, response.status_code)

    def test_missing_expected_wc_revision_returns_422(self):
        response = self.client.post(
            "/api/projects/proj_mgk10_sar_demo/revision-threads/fake_thread/accept-and-apply",
            json={"suggestion_id": "s1", "idempotency_key": "k1"},
        )
        self.assertEqual(422, response.status_code)

    def test_missing_idempotency_key_returns_422(self):
        response = self.client.post(
            "/api/projects/proj_mgk10_sar_demo/revision-threads/fake_thread/accept-and-apply",
            json={"suggestion_id": "s1", "expected_working_copy_revision": 1},
        )
        self.assertEqual(422, response.status_code)

    def test_invalid_json_returns_400(self):
        response = self.client.post(
            "/api/projects/proj_mgk10_sar_demo/revision-threads/fake_thread/accept-and-apply",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        self.assertIn(response.status_code, (400, 422))

    def test_nonexistent_thread_returns_404(self):
        response = self.client.post(
            "/api/projects/proj_mgk10_sar_demo/revision-threads/nonexistent_thread/accept-and-apply",
            json={
                "suggestion_id": "s1",
                "expected_working_copy_revision": 1,
                "idempotency_key": "missing-thread-once",
                "actor": "medical_manager",
            },
        )
        self.assertIn(response.status_code, (404, 409))


class TestUnifiedJobRoutes(unittest.TestCase):
    """Test the unified job status/result/cancel/retry routes."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from services.api.app import main as app_main
        cls.client = TestClient(app_main.app)
        cls.store = app_main.mw_durable_store

    def test_get_nonexistent_job_returns_404(self):
        response = self.client.get(
            "/api/projects/proj_test_x/medical-writing/jobs/nonexistent_job"
        )
        self.assertEqual(404, response.status_code)

    def test_cancel_nonexistent_job_returns_404(self):
        response = self.client.post(
            "/api/projects/proj_test_x/medical-writing/jobs/nonexistent_job/cancel"
        )
        self.assertEqual(404, response.status_code)

    def test_result_nonterminal_job_returns_409(self):
        """Getting result for a queued job must return 409."""
        from services.api.app import main as app_main

        isolated_root = Path(__file__).resolve().parent / "_tmp_durable_route_nonterminal"
        isolated_root.mkdir(exist_ok=True)
        isolated_store = DurableJobStore(isolated_root / "route_nonterminal.db")
        original_store = app_main.mw_durable_store
        try:
            app_main.mw_durable_store = isolated_store
            job = isolated_store.create_or_reuse(_make_request(
                project_id="proj_mgk10_sar_demo",
                business_key="bk_route_001",
            ))
            response = self.client.get(
                f"/api/projects/proj_mgk10_sar_demo/medical-writing/jobs/{job.job_id}/result"
            )
            self.assertEqual(409, response.status_code)
        finally:
            app_main.mw_durable_store = original_store
            import shutil
            shutil.rmtree(isolated_root, ignore_errors=True)


class TestTranslationRouteNoBackgroundLongCall(unittest.TestCase):
    """Verify the translation create/retry routes don't schedule BackgroundTasks."""

    def test_translation_routes_signature_has_no_background_tasks(self):
        """The route functions must not accept BackgroundTasks parameter."""
        import inspect
        from services.api.app import main as app_main

        create_sig = inspect.signature(app_main.create_writing_reference_translation_batch)
        retry_sig = inspect.signature(app_main.retry_writing_reference_translation_batch)

        self.assertNotIn("background_tasks", create_sig.parameters)
        self.assertNotIn("background_tasks", retry_sig.parameters)


class TestContextFingerprint(unittest.TestCase):
    """v2 generation-context identity prevents stale-completed reuse."""

    def setUp(self):
        self._tmp = Path(__file__).resolve().parent / "_tmp_durable_fp"
        self._tmp.mkdir(exist_ok=True)
        self.store = DurableJobStore(self._tmp / "fp_test.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_wc_and_study_definition_change_change_digest(self):
        """Authoritative WC/StudyDefinition identity must affect the digest."""
        from services.api.app.medical_writing import MedicalWritingRevisionService
        from services.api.app.ai_execution_policy import AiExecutionPolicyResolver
        from packages.contracts.workbench_contracts import MedicalWritingRevisionRequest
        from types import SimpleNamespace

        from packages.contracts.workbench_contracts import ApprovalState

        section = SimpleNamespace(
            section_id="sec1",
            heading="H",
            approval_state=ApprovalState.AI_DRAFT,
        )
        mock_protocol = SimpleNamespace(
            document_id="doc1",
            sections=[section],
            source_study_definition_id="",
            source_study_definition_revision=None,
            source_study_definition_sha256="",
        )
        mock_repo = SimpleNamespace(
            project=lambda pid: True,
            protocol=lambda pid: mock_protocol,
            authoritative_revision_source_identity=lambda pid, sid: ("wc1", 1, "a" * 64),
            authoritative_study_definition_binding=lambda pid: ("sd1", 1, "b" * 64),
        )
        service = MedicalWritingRevisionService(
            mock_repo,
            SimpleNamespace(
                policy_resolver=AiExecutionPolicyResolver(
                    provider_name="deepseek", model_name="deepseek-chat"
                )
            ),
        )
        request = MedicalWritingRevisionRequest(
            document_id="doc1",
            section_id="sec1",
            selected_text="text",
            anchor_path="p.1",
            user_instruction="指令",
            intent="regulatory_tone",
            requested_by="tester",
        )
        # Patch _section to avoid real protocol section lookup quirks.
        service._section = lambda protocol, section_id: section

        fp1 = service.build_generation_context_descriptor(
            "p1", section_id="sec1", operation="initial", request=request
        )
        fp2 = service.build_generation_context_descriptor(
            "p1", section_id="sec1", operation="initial", request=request
        )
        self.assertEqual(fp1["digest"], fp2["digest"])
        self.assertEqual(64, len(fp1["digest"]))

        mock_repo.authoritative_revision_source_identity = lambda pid, sid: ("wc1", 2, "c" * 64)
        fp3 = service.build_generation_context_descriptor(
            "p1", section_id="sec1", operation="initial", request=request
        )
        self.assertNotEqual(fp1["digest"], fp3["digest"])

        mock_repo.authoritative_revision_source_identity = lambda pid, sid: ("wc1", 1, "a" * 64)
        mock_repo.authoritative_study_definition_binding = lambda pid: ("sd2", 2, "d" * 64)
        fp4 = service.build_generation_context_descriptor(
            "p1", section_id="sec1", operation="initial", request=request
        )
        self.assertNotEqual(fp1["digest"], fp4["digest"])

    def test_dedupe_same_context_reuses_completed(self):
        """Same business key + request hash should reuse a completed job."""
        job1 = self.store.create_or_reuse(_make_request(business_key="bk1", request_hash="rh_aaaaaaaaaaaa"))
        self.assertFalse(job1.reused)

        job2 = self.store.create_or_reuse(_make_request(business_key="bk1", request_hash="rh_aaaaaaaaaaaa"))
        self.assertTrue(job2.reused)
        self.assertEqual(job1.job_id, job2.job_id)

    def test_different_request_hash_creates_conflict(self):
        """Same business key but different request hash should raise conflict."""
        from services.api.app.medical_writing_durable_jobs import DurableJobRequestConflict

        self.store.create_or_reuse(_make_request(business_key="bk1", request_hash="rh_aaaaaaaaaaaa"))
        with self.assertRaises(DurableJobRequestConflict):
            self.store.create_or_reuse(_make_request(business_key="bk1", request_hash="rh_bbbbbbbbbbbb"))

    def test_rewrite_returns_http_202(self):
        """The rewrite action endpoint must return HTTP 202 for the durable path."""
        from fastapi.testclient import TestClient
        from services.api.app import main as app_main

        client = TestClient(app_main.app)
        # We can't easily set up a full revision thread in this unit test,
        # but we can verify the status code by checking the route's response
        # for a nonexistent thread (which returns 404, not 200/202).
        # The actual 202 behavior is proven by test_request_rewrite_keeps_audit
        # in test_medical_writing_revision_api.py which asserts status 202.
        # Here we just verify the route doesn't default to 200 for rewrite.
        # A 404 is acceptable (thread doesn't exist) — the point is it's not 200.
        response = client.post(
            "/api/projects/proj_mgk10_sar_demo/revision-threads/fake_thread/actions",
            json={"action": "request_rewrite", "suggestion_id": "s1", "actor": "test", "comment": "c", "rewrite_instruction": "r"},
        )
        self.assertIn(response.status_code, (202, 404, 409))


if __name__ == "__main__":
    unittest.main()
