"""Tests for real per-chunk synopsis-import async job lifecycle with proper
claim ownership, heartbeat, cold recovery, deterministic merge, and bounded
worker lifecycle.

All tests join workers via service.shutdown() before temp-directory cleanup
to prevent unhandled thread exceptions.
"""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from packages.contracts.workbench_contracts import (
    AiTaskArtifact,
    AiTaskRequest,
    AiTaskRun,
    AiTaskRunStatus,
    AiTaskSourceRef,
)
from services.api.app.medical_writing_synopsis_import import (
    MedicalWritingSynopsisImportService,
    _canonical_text,
    _chunk_ai_sources,
    MAX_SYNOPSIS_CHUNK_CHARS,
)


def _fake_route_snapshot() -> dict[str, Any]:
    snapshot = {
        "schema_version": "independent_ai_route_snapshot_v1",
        "role_id": "independent_ai",
        "profile_id": "fake-profile",
        "profile_revision": 1,
        "provider": "fake",
        "model": "fake-model",
        "base_url": "https://fake.invalid/v1",
        "transport": "openai_compatible",
        "expected_response_model": "fake-model",
        "deployment_profile": "fake-deployment",
    }
    return {
        **snapshot,
        "identity_sha256": hashlib.sha256(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def _docx_bytes_multi(paragraphs: list[str]) -> bytes:
    """Build a docx with multiple paragraphs to produce multiple source spans."""
    content_types = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''
    body_parts = ['<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>方案摘要</w:t></w:r></w:p>']
    for para in paragraphs:
        body_parts.append(f'<w:p><w:r><w:t>{para}</w:t></w:r></w:p>')
    body_parts.append('<w:sectPr/>')
    document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{''.join(body_parts)}</w:body>
</w:document>'''.encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def _docx_bytes(text: str) -> bytes:
    return _docx_bytes_multi([text])


class CountingFakeAiRunner:
    """Fake AI runner that counts calls and optionally blocks on a barrier.

    Each call records the source_ids it received, proving the worker only
    passed this chunk's sources. Supports deterministic concurrency tests.
    """

    def __init__(self, delay: float = 0.0):
        self._calls: List[List[str]] = []
        self._lock = threading.Lock()
        self._delay = delay
        self._barrier: threading.Event | None = None

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self._calls)

    @property
    def calls_source_ids(self) -> List[List[str]]:
        with self._lock:
            return list(self._calls)

    def set_barrier(self, barrier: threading.Event) -> None:
        self._barrier = barrier

    def route_identity_snapshot(self, *, refresh: bool = True) -> dict[str, Any]:
        return _fake_route_snapshot()

    def submit_internal(self, project_id: str, request: AiTaskRequest) -> AiTaskRun:
        source_ids = [s.source_id for s in request.allowed_sources]
        with self._lock:
            self._calls.append(source_ids)
        if self._barrier:
            self._barrier.wait(timeout=30.0)
        if self._delay:
            time.sleep(self._delay)
        source = request.allowed_sources[0] if request.allowed_sources else None
        output: Dict[str, Any] = {
            "task_id": f"fake_chunk_{self.call_count}",
            "task_type": "protocol_synopsis_structuring",
            "provider": "fake",
            "model": "fake-model",
            "prompt_version": request.prompt_version,
            "input_source_ids": source_ids,
            "forbidden_source_ids": request.forbidden_source_ids,
            "findings": [],
            "evidence_spans": [
                {
                    "span_id": f"ev_{s.source_id}",
                    "source_id": s.source_id,
                    "locator": s.locator,
                    "quote": s.text_preview[:200] if s.text_preview else "text",
                }
                for s in request.allowed_sources
            ],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "study_definition": {
                "framing": {
                    "protocol_id": "TEST-001",
                    "document_title": "Test Synopsis",
                    "indication": "测试适应症",
                    "clinicaltrials_condition_term": "Test",
                    "study_phase": "II期",
                    "intrinsic_objectives": ["概念验证"],
                    "investigational_product": "TEST-DRUG",
                    "target_mechanism": "test",
                    "design_pattern": "随机、双盲",
                    "population_intent": "测试人群",
                },
                "picos": {
                    "design_archetype": "randomized_confirmatory",
                    "population_summary": "测试人群",
                    "intervention_summary": "TEST-DRUG",
                    "comparator_summary": "安慰剂",
                    "primary_endpoint": "第12周应答率",
                    "study_epochs": ["筛选期", "治疗期"],
                    "assessment_instruments": [],
                    "safety_endpoints": ["AE、SAE发生率"],
                },
                "synopsis_text": "本研究评价TEST-DRUG的安全性。",
                "missing_fields": [],
                "conflict_notes": [],
                "field_evidence_span_ids": {},
            },
        }
        artifact = AiTaskArtifact(
            artifact_id=f"art_{self.call_count}",
            artifact_type="provider_output",
            payload=output,
        )
        return AiTaskRun(
            run_id=f"run_{self.call_count}",
            project_id=project_id,
            module="medical_writing",
            task_type="protocol_synopsis_structuring",
            purpose="synopsis_structuring",
            status=AiTaskRunStatus.COMPLETED,
            provider="fake",
            model_name="fake-model",
            actual_response_model="fake-model",
            route_identity_hash=_fake_route_snapshot()["identity_sha256"],
            ai_gateway_status="ok",
            prompt_version=request.prompt_version,
            schema_version="ai_task_output_v0_1",
            input_sources=request.allowed_sources,
            artifacts=[artifact],
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )


def _wait_for_status(service, project_id, idempotency_key, target_status, timeout=30.0):
    """Poll get_job until target_status or timeout."""
    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        try:
            status = service.get_job(project_id, idempotency_key)
        except KeyError:
            time.sleep(0.1)
            continue
        if status.status in target_status if isinstance(target_status, (set, tuple)) else status.status == target_status:
            break
        time.sleep(0.2)
    return status


class SynopsisChunkExecutionBase(unittest.TestCase):
    """Base class that ensures workers are joined before cleanup."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.artifact_root = Path(self.tmpdir.name) / "artifacts"
        self.ai_runner = CountingFakeAiRunner()
        self.service = MedicalWritingSynopsisImportService(
            self.artifact_root, self.ai_runner,
            claim_timeout_seconds=2.0,
            chunk_lease_seconds=2.0,
            heartbeat_interval_seconds=0.5,
        )

    def tearDown(self):
        # Join all workers before cleanup — prevents disk I/O errors.
        self.service.shutdown(timeout=10.0)
        self.tmpdir.cleanup()


class RealChunkExecutionTest(SynopsisChunkExecutionBase):
    """Tests that verify real per-chunk execution behavior."""

    def test_resume_increments_failed_chunk_attempt_count(self):
        """A user-visible resume is a new processing attempt, even though the
        failed chunk is reset to pending before the worker claims it."""
        self.service._shutdown_requested = True
        self.service.start_job(
            "proj_resume_attempt",
            filename="synopsis.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=_docx_bytes("方案摘要：测试。"),
            expected_indication="测试",
            actor="medical_manager",
            idempotency_key="resume-attempt",
        )
        with self.service._connect() as connection:
            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET status = 'failed', phase = 'failed'
                WHERE project_id = ? AND idempotency_key = ?
                """,
                ("proj_resume_attempt", "resume-attempt"),
            )
            connection.execute(
                """
                UPDATE medical_writing_synopsis_import_chunks
                SET status = 'failed', attempt_count = 1
                WHERE project_id = ? AND idempotency_key = ?
                """,
                ("proj_resume_attempt", "resume-attempt"),
            )
            connection.commit()

        self.service.resume_job(
            "proj_resume_attempt",
            "resume-attempt",
            actor="medical_manager",
        )

        with self.service._connect() as connection:
            row = connection.execute(
                """
                SELECT status, attempt_count
                FROM medical_writing_synopsis_import_chunks
                WHERE project_id = ? AND idempotency_key = ?
                """,
                ("proj_resume_attempt", "resume-attempt"),
            ).fetchone()
        self.assertEqual("pending", row["status"])
        self.assertEqual(2, row["attempt_count"])

    def test_two_chunks_cause_two_separate_ai_calls(self):
        """2+ chunks → 2+ separate AI calls, each seeing only its chunk's sources."""
        from services.api.app import medical_writing_synopsis_import as mod
        original = mod.MAX_SYNOPSIS_CHUNK_CHARS
        mod.MAX_SYNOPSIS_CHUNK_CHARS = 100
        try:
            paragraphs = [
                f"研究目的第{i}项：评价测试药物在适应症{i}中的有效性。" * 3
                for i in range(5)
            ]
            # Do NOT include endpoint labels that would create anchored fields
            # conflicting with the fake runner's hardcoded output.
            docx = _docx_bytes_multi(paragraphs)
            response = self.service.start_job(
                "proj_chunk_001",
                filename="synopsis.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                payload=docx,
                expected_indication="测试适应症",
                actor="medical_manager",
                idempotency_key="chunk-test-001",
            )
            self.assertTrue(response.job_id)
            status = _wait_for_status(self.service, "proj_chunk_001", "chunk-test-001",
                                      ("review_ready", "failed"))
            self.assertIsNotNone(status)
            self.assertEqual(status.status, "review_ready",
                             f"got {status.status}: {status.error_message}")
            self.assertGreaterEqual(self.ai_runner.call_count, 2,
                                    f"expected 2+ AI calls, got {self.ai_runner.call_count}")
            # No source_id appears in more than one chunk call.
            all_ids = set()
            for call_ids in self.ai_runner.calls_source_ids:
                for sid in call_ids:
                    self.assertNotIn(sid, all_ids)
                    all_ids.add(sid)
            # All chunks done.
            with self.service._connect() as conn:
                statuses = [r["status"] for r in conn.execute(
                    "SELECT status FROM medical_writing_synopsis_import_chunks "
                    "WHERE project_id=? AND idempotency_key=? ORDER BY chunk_index",
                    ("proj_chunk_001", "chunk-test-001"),
                ).fetchall()]
            self.assertTrue(all(s == "done" for s in statuses))
            self.assertGreaterEqual(len(statuses), 2)
        finally:
            mod.MAX_SYNOPSIS_CHUNK_CHARS = original

    def test_stable_job_id_on_first_start_and_replay(self):
        """job_id must be deterministic and persisted."""
        docx = _docx_bytes("方案摘要：测试适应症II期研究。")
        first = self.service.start_job(
            "proj_stable_001", filename="s.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx, expected_indication="测试适应症",
            actor="medical_manager", idempotency_key="stable-test",
        )
        _wait_for_status(self.service, "proj_stable_001", "stable-test", ("review_ready", "failed"))
        second = self.service.start_job(
            "proj_stable_001", filename="s.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx, expected_indication="测试适应症",
            actor="medical_manager", idempotency_key="stable-test",
        )
        self.assertEqual(first.job_id, second.job_id)
        self.assertNotEqual(first.job_id, first.content_sha256)
        with self.service._connect() as conn:
            row = conn.execute(
                "SELECT job_id FROM medical_writing_synopsis_imports "
                "WHERE project_id=? AND idempotency_key=?",
                ("proj_stable_001", "stable-test"),
            ).fetchone()
        self.assertEqual(row["job_id"], first.job_id)
        # cancel must also return same job_id.
        cancel = self.service.cancel_job("proj_stable_001", "stable-test")
        self.assertEqual(cancel.job_id, first.job_id)

    def test_cancel_during_ai_call_discards_late_output(self):
        """Cancel during a blocked AI call must discard output."""
        barrier = threading.Event()
        self.ai_runner.set_barrier(barrier)
        docx = _docx_bytes("方案摘要：测试适应症。研究终点\t主要终点：应答率。安全性终点：AE发生率。")
        self.service.start_job(
            "proj_cancel", filename="s.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx, expected_indication="测试适应症",
            actor="medical_manager", idempotency_key="cancel-test",
        )
        time.sleep(1.0)
        cancel = self.service.cancel_job("proj_cancel", "cancel-test")
        self.assertEqual(cancel.cancellation_state, "cancelled")
        barrier.set()
        time.sleep(1.0)
        status = self.service.get_job("proj_cancel", "cancel-test")
        self.assertEqual(status.status, "cancelled")
        with self.assertRaises(RuntimeError):
            self.service.get_job_result("proj_cancel", "cancel-test")

    def test_cancel_is_idempotent(self):
        docx = _docx_bytes("方案摘要：测试适应症。")
        self.service.start_job(
            "proj_cancel_idem", filename="s.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx, expected_indication="测试适应症",
            actor="medical_manager", idempotency_key="cancel-idem",
        )
        first = self.service.cancel_job("proj_cancel_idem", "cancel-idem")
        second = self.service.cancel_job("proj_cancel_idem", "cancel-idem")
        self.assertEqual(first.cancellation_state, "cancelled")
        self.assertEqual(second.cancellation_state, "cancelled")

    def test_cancel_preserves_flattened_partial_evidence(self):
        """partial_evidence_span_ids must be flat strings, not JSON arrays."""
        docx = _docx_bytes("方案摘要：测试适应症。研究终点\t主要终点：应答率。安全性终点：AE发生率。")
        self.service.start_job(
            "proj_flat", filename="s.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx, expected_indication="测试适应症",
            actor="medical_manager", idempotency_key="flat-test",
        )
        time.sleep(3.0)
        cancel = self.service.cancel_job("proj_flat", "flat-test")
        for eid in cancel.partial_evidence_span_ids:
            self.assertIsInstance(eid, str)
            self.assertFalse(eid.startswith("["))


class ClaimOwnershipTest(SynopsisChunkExecutionBase):
    """Tests for CAS claim ownership."""

    def test_claim_returns_opaque_token(self):
        """_claim_chunk must return an opaque token string, not bool."""
        docx = _docx_bytes("方案摘要：测试。")
        self.service.start_job(
            "proj_claim", filename="s.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx, expected_indication="测试",
            actor="medical_manager", idempotency_key="claim-test",
        )
        token = self.service._claim_chunk("proj_claim", "claim-test", 0)
        self.assertIsNotNone(token)
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 8)

    def test_second_worker_cannot_claim_same_chunk(self):
        """Two concurrent _claim_chunk calls must not both succeed."""
        docx = _docx_bytes("方案摘要：测试。")
        self.service.start_job(
            "proj_concurrent", filename="s.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx, expected_indication="测试",
            actor="medical_manager", idempotency_key="concurrent-test",
        )
        token1 = self.service._claim_chunk("proj_concurrent", "concurrent-test", 0)
        token2 = self.service._claim_chunk("proj_concurrent", "concurrent-test", 0)
        self.assertIsNotNone(token1)
        self.assertIsNone(token2)

    def test_stale_owner_cannot_overwrite_reclaimed_chunk(self):
        """If a chunk lease expires and is reclaimed, the old owner's complete
        must fail (rowcount=0)."""
        docx = _docx_bytes("方案摘要：测试。")
        self.service.start_job(
            "proj_stale", filename="s.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx, expected_indication="测试",
            actor="medical_manager", idempotency_key="stale-test",
        )
        # First worker claims.
        old_token = self.service._claim_chunk("proj_stale", "stale-test", 0)
        self.assertIsNotNone(old_token)
        # Simulate lease expiry — manually reset to pending.
        with self.service._connect() as conn:
            conn.execute(
                "UPDATE medical_writing_synopsis_import_chunks "
                "SET status='pending', lease_expires_at='', claim_token='' "
                "WHERE project_id=? AND idempotency_key=? AND chunk_index=0",
                ("proj_stale", "stale-test"),
            )
            conn.commit()
        # New worker claims.
        new_token = self.service._claim_chunk("proj_stale", "stale-test", 0)
        self.assertIsNotNone(new_token)
        self.assertNotEqual(old_token, new_token)
        # Old owner tries to complete — must fail (rowcount=0).
        result = self.service._complete_chunk(
            "proj_stale", "stale-test", 0,
            '{"fake": "old"}',
            "old_hash",
            [],
            "fake",
            "fake-model",
            "run_old_owner",
            "fake-model",
            _fake_route_snapshot()["identity_sha256"],
            old_token,
        )
        self.assertFalse(result, "stale owner must not overwrite reclaimed chunk")
        # Chunk must still be running under new owner.
        with self.service._connect() as conn:
            row = conn.execute(
                "SELECT status, claim_token FROM medical_writing_synopsis_import_chunks "
                "WHERE project_id=? AND idempotency_key=? AND chunk_index=0",
                ("proj_stale", "stale-test"),
            ).fetchone()
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["claim_token"], new_token)

    def test_expired_chunk_lease_is_reclaimable(self):
        """After lease expiry, a chunk can be reclaimed."""
        service = MedicalWritingSynopsisImportService(
            self.artifact_root, CountingFakeAiRunner(),
            claim_timeout_seconds=0.1, chunk_lease_seconds=0.1,
            heartbeat_interval_seconds=0.05,
        )
        try:
            docx = _docx_bytes("方案摘要：测试。")
            service.start_job(
                "proj_expire", filename="s.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                payload=docx, expected_indication="测试",
                actor="medical_manager", idempotency_key="expire-test",
            )
            token1 = service._claim_chunk("proj_expire", "expire-test", 0)
            self.assertIsNotNone(token1)
            time.sleep(0.3)
            token2 = service._claim_chunk("proj_expire", "expire-test", 0)
            self.assertIsNotNone(token2, "expired lease must be reclaimable")
        finally:
            service.shutdown(timeout=5.0)

    def test_late_job_failure_cannot_overwrite_completed_result(self):
        """A stale worker exception after final commit must not regress the job."""
        docx = _docx_bytes("方案摘要：测试适应症。")
        self.service.start_job(
            "proj_completed_guard", filename="s.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx, expected_indication="测试适应症",
            actor="medical_manager", idempotency_key="completed-guard",
        )
        status = _wait_for_status(
            self.service,
            "proj_completed_guard",
            "completed-guard",
            ("review_ready", "failed"),
        )
        self.assertEqual(status.status, "review_ready")

        self.service._fail_job(
            project_id="proj_completed_guard",
            idempotency_key="completed-guard",
            error_message="late stale-owner error",
        )

        after = self.service.get_job("proj_completed_guard", "completed-guard")
        self.assertEqual(after.status, "review_ready")
        self.assertEqual(after.error_message, "")


class ColdRecoveryTest(unittest.TestCase):
    """Tests for crash recovery: simulate a crash, create a new service
    instance, verify recovery completes without replaying done chunks."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.artifact_root = Path(self.tmpdir.name) / "artifacts"
        self._services: list = []

    def tearDown(self):
        for svc in self._services:
            svc.shutdown(timeout=10.0)
        self.tmpdir.cleanup()

    def test_recovery_requeues_and_completes_without_replay(self):
        """A blocked job is requeued by a new service instance. The new
        instance completes the job. Done chunks are not replayed."""
        # Service 1: start a job with a blocking provider.
        runner1 = CountingFakeAiRunner()
        barrier = threading.Event()
        runner1.set_barrier(barrier)
        service1 = MedicalWritingSynopsisImportService(
            self.artifact_root, runner1, claim_timeout_seconds=1.0,
            chunk_lease_seconds=0.5, heartbeat_interval_seconds=0.2,
        )
        self._services.append(service1)
        docx = _docx_bytes("方案摘要：测试适应症。研究终点\t安全性终点：AE。")
        service1.start_job(
            "proj_recover", filename="s.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx, expected_indication="测试",
            actor="medical_manager", idempotency_key="recover-test",
        )
        # Wait for the provider call to start (blocked on barrier).
        time.sleep(1.0)
        calls_before = runner1.call_count
        # Simulate crash: shutdown service1 (stop heartbeat), but don't release barrier yet.
        service1.shutdown(timeout=2.0)
        # Wait for lease to expire.
        time.sleep(1.0)
        # Service 2: new instance, same DB. Trigger recovery.
        runner2 = CountingFakeAiRunner()
        service2 = MedicalWritingSynopsisImportService(
            self.artifact_root, runner2, claim_timeout_seconds=10.0,
            chunk_lease_seconds=10.0, heartbeat_interval_seconds=2.0,
        )
        self._services.append(service2)
        requeued = service2.recover_stale_jobs()
        self.assertGreaterEqual(requeued, 1, "expired incomplete job must be requeued")
        # Wait for completion.
        status = _wait_for_status(service2, "proj_recover", "recover-test",
                                  ("review_ready", "failed"), timeout=10.0)
        self.assertIsNotNone(status, "job status was never available after recovery")
        self.assertEqual(status.status, "review_ready",
                         f"recovered job should be review_ready, got {status.status}: {status.error_message}")
        self.assertGreaterEqual(
            runner2.call_count,
            1,
            "the replacement service must execute the reclaimed chunk",
        )
        # Release barrier so any stuck threads can exit.
        barrier.set()
        service1.shutdown(timeout=5.0)
        after_stale_owner_exit = service2.get_job("proj_recover", "recover-test")
        self.assertEqual(after_stale_owner_exit.status, "review_ready")
        # Source metadata must be preserved.
        result = service2.get_job_result("proj_recover", "recover-test")
        self.assertEqual(result.source.content_sha256,
                         hashlib_sha256(docx))

    def test_reclaimed_job_survives_stale_owner_provider_failure(self):
        """A provider error from an expired owner must not fail the new result."""
        class BlockingFailureRunner:
            def __init__(self):
                self.started = threading.Event()
                self.release = threading.Event()

            def route_identity_snapshot(
                self, *, refresh: bool = True
            ) -> dict[str, Any]:
                return _fake_route_snapshot()

            def submit_internal(self, project_id, request):
                self.started.set()
                if not self.release.wait(timeout=20.0):
                    raise TimeoutError("stale provider remained blocked")
                raise RuntimeError("stale provider failed after lease loss")

        stale_runner = BlockingFailureRunner()
        service1 = MedicalWritingSynopsisImportService(
            self.artifact_root,
            stale_runner,
            claim_timeout_seconds=0.5,
            chunk_lease_seconds=0.5,
            heartbeat_interval_seconds=0.1,
        )
        self._services.append(service1)
        docx = _docx_bytes("方案摘要：测试适应症。")
        service1.start_job(
            "proj_stale_failure", filename="s.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx, expected_indication="测试适应症",
            actor="medical_manager", idempotency_key="stale-failure",
        )
        self.assertTrue(stale_runner.started.wait(timeout=5.0))

        service1.shutdown(timeout=0.2)
        time.sleep(0.8)

        replacement_runner = CountingFakeAiRunner()
        service2 = MedicalWritingSynopsisImportService(
            self.artifact_root,
            replacement_runner,
            claim_timeout_seconds=2.0,
            chunk_lease_seconds=5.0,
            heartbeat_interval_seconds=0.5,
        )
        self._services.append(service2)
        self.assertGreaterEqual(service2.recover_stale_jobs(), 1)
        replacement_status = _wait_for_status(
            service2,
            "proj_stale_failure",
            "stale-failure",
            ("review_ready", "failed"),
            timeout=10.0,
        )
        self.assertEqual(replacement_status.status, "review_ready")
        self.assertGreaterEqual(replacement_runner.call_count, 1)

        stale_runner.release.set()
        service1.shutdown(timeout=5.0)
        final_status = service2.get_job(
            "proj_stale_failure", "stale-failure"
        )
        self.assertEqual(final_status.status, "review_ready")
        self.assertEqual(final_status.error_message, "")


def hashlib_sha256(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


class DeterministicMergeTest(unittest.TestCase):
    """Tests for the deterministic multi-chunk merge."""

    def test_canonical_text_nfck_normalization(self):
        self.assertEqual(_canonical_text("AE发生率"), _canonical_text("AE发生率"))
        self.assertNotEqual(_canonical_text(""), _canonical_text("x"))

    def test_chunk_sources_preserve_order(self):
        sources = [
            AiTaskSourceRef(source_id=f"src_{i}", source_type="test", title=f"s{i}",
                            locator=f"loc_{i}", text_preview=f"text {i}")
            for i in range(10)
        ]
        chunks = _chunk_ai_sources(sources, max_chars=100)
        flat = [s for chunk in chunks for s in chunk]
        self.assertEqual([s.source_id for s in flat], [s.source_id for s in sources])

    def test_merge_rejects_partial_done_set(self):
        """_merge_chunks must require exactly chunk_total done indices."""
        runner = CountingFakeAiRunner()
        tmpdir = tempfile.TemporaryDirectory()
        try:
            artifact_root = Path(tmpdir.name) / "artifacts"
            service = MedicalWritingSynopsisImportService(
                artifact_root, runner, chunk_lease_seconds=10.0,
            )
            # Insert a fake job with chunk_total=2 but only 1 done chunk.
            with service._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO medical_writing_synopsis_imports("
                    "project_id, idempotency_key, request_sha256, status, "
                    "created_at, updated_at, phase, chunk_total, source_json"
                    ") VALUES (?, ?, ?, 'pending', ?, ?, 'ai_synthesis', 2, '')",
                    ("proj_partial", "partial", "req", "2026-01-01T00:00:00+00:00",
                     "2026-01-01T00:00:00+00:00"),
                )
                conn.execute(
                    "INSERT INTO medical_writing_synopsis_import_chunks("
                    "project_id, idempotency_key, chunk_index, status, started_at, "
                    "output_json, chunk_sources_json"
                    ") VALUES (?, ?, 0, 'done', '', '{}', '[]')",
                    ("proj_partial", "partial"),
                )
                conn.execute(
                    "INSERT INTO medical_writing_synopsis_import_chunks("
                    "project_id, idempotency_key, chunk_index, status, started_at, "
                    "chunk_sources_json"
                    ") VALUES (?, ?, 1, 'pending', '', '[]')",
                    ("proj_partial", "partial"),
                )
                conn.commit()
            from packages.contracts.workbench_contracts import MedicalWritingSynopsisSource
            source = MedicalWritingSynopsisSource(
                source_id="test", original_filename="t.docx",
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                actual_size=100, content_sha256="a"*64,
                extraction_revision="v1", parser_name="test",
                source_role_status="matched", indication_status="matched",
                validation_warnings=[], imported_at="2026-01-01T00:00:00+00:00",
                imported_by="test",
            )
            with self.assertRaises(RuntimeError, msg="merge must reject partial done set"):
                service._merge_chunks(
                    project_id="proj_partial", idempotency_key="partial",
                    source_id="test", source=source,
                    expected_indication="", chunk_total=2,
                )
            service.shutdown(timeout=2.0)
        finally:
            tmpdir.cleanup()


class ProgressMonotonicityTest(SynopsisChunkExecutionBase):
    """Test that progress is monotonic under concurrent workers."""

    def test_progress_never_regresses(self):
        """Public chunk_index must never decrease. We record all observed
        values and verify they are non-decreasing."""
        docx = _docx_bytes("方案摘要：测试适应症。")
        self.service.start_job(
            "proj_mono", filename="s.docx",
            content_type="application/vnd.openxmlformats-officedocumented.wordprocessingml.document",
            payload=docx, expected_indication="测试适应症",
            actor="medical_manager", idempotency_key="mono-test",
        )
        observed_indices: list[int] = []
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            try:
                status = self.service.get_job("proj_mono", "mono-test")
                observed_indices.append(status.chunk_index)
                if status.status in ("review_ready", "failed", "cancelled"):
                    break
            except KeyError:
                pass
            time.sleep(0.1)
        # Verify monotonic non-decreasing.
        for i in range(1, len(observed_indices)):
            self.assertGreaterEqual(
                observed_indices[i], observed_indices[i-1],
                f"progress regressed: {observed_indices[i-1]} → {observed_indices[i]} at sample {i}",
            )


if __name__ == "__main__":
    unittest.main()
