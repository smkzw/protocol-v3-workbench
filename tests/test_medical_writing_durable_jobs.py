"""Deterministic tests for the DurableMedicalWritingJob store and worker.

Covers: create/dedupe, hash conflict, claim, heartbeat, lease loss,
stale-owner CAS rejection, CAS complete/fail, cancel isolation, retry,
cold recovery, graceful shutdown, project isolation, monotonic progress.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from packages.contracts.workbench_contracts import (
    DurableJobCreateRequest,
    DurableJobNotFound,
    DurableJobProgressPayload,
    DurableJobRecord,
    DurableJobRequestConflict,
)
from services.api.app.medical_writing_durable_jobs import (
    DurableJobExecutor,
    DurableJobResult,
    DurableJobStore,
    DurableJobWorker,
    _is_newer_progress,
    _lease_is_expired,
    _stable_job_id,
)


def _make_request(
    project_id: str = "proj-A",
    job_type: str = "competitor_triage",
    business_key: str = "snap-001",
    request_hash: str = "rh-aaaaaaaa",
    **kwargs,
) -> DurableJobCreateRequest:
    return DurableJobCreateRequest(
        project_id=project_id,
        job_type=job_type,
        business_key=business_key,
        request_hash=request_hash,
        **kwargs,
    )


class TestCreateDedupe(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self._tmp.name) / "durable.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_returns_queued(self) -> None:
        resp = self.store.create_or_reuse(_make_request())
        self.assertEqual(resp.status, "queued")
        self.assertFalse(resp.reused)
        self.assertTrue(resp.job_id.startswith("mwjob_"))

    def test_dedupe_same_request_reuses(self) -> None:
        req = _make_request()
        first = self.store.create_or_reuse(req)
        second = self.store.create_or_reuse(req)
        self.assertEqual(first.job_id, second.job_id)
        self.assertTrue(second.reused)

    def test_dedupe_different_status_returns_current(self) -> None:
        req = _make_request()
        first = self.store.create_or_reuse(req)
        # Simulate state change.
        claim = self.store.claim(req.project_id, first.job_id)
        self.assertTrue(claim.claimed)
        second = self.store.create_or_reuse(req)
        self.assertTrue(second.reused)
        self.assertEqual(second.status, "running")

    def test_hash_conflict_raises(self) -> None:
        self.store.create_or_reuse(_make_request(request_hash="rh-aaaaaaaa"))
        with self.assertRaises(DurableJobRequestConflict):
            self.store.create_or_reuse(_make_request(request_hash="rh-bbbbbbbb"))

    def test_stable_job_id(self) -> None:
        jid = _stable_job_id("proj-A", "competitor_triage", "snap-001", "rh-aaaaaaaa")
        self.assertTrue(jid.startswith("mwjob_"))
        self.assertEqual(len(jid), 6 + 24)
        # Same inputs → same id.
        self.assertEqual(
            jid,
            _stable_job_id("proj-A", "competitor_triage", "snap-001", "rh-aaaaaaaa"),
        )
        # Different project → different id.
        self.assertNotEqual(
            jid,
            _stable_job_id("proj-B", "competitor_triage", "snap-001", "rh-aaaaaaaa"),
        )


class TestClaimLease(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(
            Path(self._tmp.name) / "durable.db",
            lease_seconds=0.2,
        )
        self.job = self.store.create_or_reuse(_make_request())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_claim_succeeds_for_queued(self) -> None:
        result = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(result.claimed)
        self.assertNotEqual(result.claim_token, "")
        self.assertEqual(result.job.status, "running")

    def test_second_claim_fails_while_lease_live(self) -> None:
        first = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(first.claimed)
        second = self.store.claim("proj-A", self.job.job_id)
        self.assertFalse(second.claimed)

    def test_claim_after_lease_expiry_succeeds(self) -> None:
        first = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(first.claimed)
        time.sleep(0.3)
        second = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(second.claimed)
        self.assertNotEqual(first.claim_token, second.claim_token)

    def test_claim_terminal_returns_not_claimed(self) -> None:
        self.store.cancel("proj-A", self.job.job_id)
        result = self.store.claim("proj-A", self.job.job_id)
        self.assertFalse(result.claimed)


class TestHeartbeat(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(
            Path(self._tmp.name) / "durable.db",
            lease_seconds=1.0,
            heartbeat_interval_seconds=0.1,
        )
        self.job = self.store.create_or_reuse(_make_request())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_heartbeat_renews_lease(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(claim.claimed)
        ok = self.store.heartbeat("proj-A", self.job.job_id, claim.claim_token)
        self.assertTrue(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "running")
        self.assertNotEqual(record.lease_expires_at, "")

    def test_heartbeat_wrong_token_returns_false(self) -> None:
        self.store.claim("proj-A", self.job.job_id)
        ok = self.store.heartbeat("proj-A", self.job.job_id, "wrong-token")
        self.assertFalse(ok)

    def test_heartbeat_with_progress_advances(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        prog = DurableJobProgressPayload(phase="processing", percent=0.5, step=5, step_total=10)
        ok = self.store.heartbeat("proj-A", self.job.job_id, claim.claim_token, prog)
        self.assertTrue(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertAlmostEqual(record.progress.percent, 0.5)

    def test_heartbeat_rejects_backward_progress(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        prog1 = DurableJobProgressPayload(phase="p1", percent=0.5, step=5, step_total=10)
        self.assertTrue(
            self.store.heartbeat("proj-A", self.job.job_id, claim.claim_token, prog1)
        )
        # Try to send backward progress.
        prog2 = DurableJobProgressPayload(phase="p2", percent=0.3, step=3, step_total=10)
        ok = self.store.heartbeat("proj-A", self.job.job_id, claim.claim_token, prog2)
        # Heartbeat still returns True (lease renewed) but progress must not regress.
        self.assertTrue(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertAlmostEqual(record.progress.percent, 0.5)  # unchanged
        self.assertEqual(record.progress.step, 5)


class TestCASCompleteFail(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        self.job = self.store.create_or_reuse(_make_request())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_complete_succeeds_with_valid_token(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        ok = self.store.complete(
            "proj-A", self.job.job_id, claim.claim_token,
            output_hash="oh-1", artifact_locator='{"run_id":"r1"}',
            provider="deepseek", model="deepseek-v4-pro",
        )
        self.assertTrue(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.output_hash, "oh-1")
        self.assertEqual(record.provider, "deepseek")
        self.assertNotEqual(record.finished_at, None)

    def test_complete_fails_with_wrong_token(self) -> None:
        self.store.claim("proj-A", self.job.job_id)
        ok = self.store.complete("proj-A", self.job.job_id, "wrong-token")
        self.assertFalse(ok)

    def test_complete_fails_after_cancel(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.cancel("proj-A", self.job.job_id)
        ok = self.store.complete("proj-A", self.job.job_id, claim.claim_token)
        self.assertFalse(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "cancelled")

    def test_fail_with_retry_sets_retry_wait(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        ok = self.store.fail(
            "proj-A", self.job.job_id, claim.claim_token,
            error_summary="transient", retryable=True,
        )
        self.assertTrue(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "retry_wait")
        self.assertEqual(record.error_summary, "transient")

    def test_fail_exhausted_sets_failed(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        ok = self.store.fail(
            "proj-A", self.job.job_id, claim.claim_token,
            error_summary="permanent", retryable=False,
        )
        self.assertTrue(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "failed")

    def test_fail_exhausts_after_max_attempts(self) -> None:
        # max_attempts=2 → first fail → retry_wait; second fail → failed.
        job = self.store.create_or_reuse(
            _make_request(business_key="snap-002", max_attempts=2)
        )
        claim1 = self.store.claim("proj-A", job.job_id)
        self.store.fail(
            "proj-A", job.job_id, claim1.claim_token,
            error_summary="err1", retryable=True,
        )
        rec1 = self.store.get("proj-A", job.job_id)
        self.assertEqual(rec1.status, "retry_wait")
        # Retry → claim again (attempt_count increments).
        claim2 = self.store.claim("proj-A", job.job_id)
        self.assertTrue(claim2.claimed)
        self.store.fail(
            "proj-A", job.job_id, claim2.claim_token,
            error_summary="err2", retryable=True,
        )
        rec2 = self.store.get("proj-A", job.job_id)
        self.assertEqual(rec2.status, "failed")


class TestStaleOwner(unittest.TestCase):
    """A stale owner (expired lease) must not overwrite a newer owner's result."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(
            Path(self._tmp.name) / "durable.db",
            lease_seconds=0.15,
        )
        self.job = self.store.create_or_reuse(_make_request())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_stale_owner_complete_ignored(self) -> None:
        # Owner 1 claims.
        owner1 = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(owner1.claimed)
        # Lease expires.
        time.sleep(0.2)
        # Owner 2 claims (takes over).
        owner2 = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(owner2.claimed)
        # Owner 2 completes.
        ok2 = self.store.complete(
            "proj-A", self.job.job_id, owner2.claim_token,
            output_hash="oh-owner2",
        )
        self.assertTrue(ok2)
        # Owner 1 tries to complete — must be rejected.
        ok1 = self.store.complete(
            "proj-A", self.job.job_id, owner1.claim_token,
            output_hash="oh-owner1",
        )
        self.assertFalse(ok1)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.output_hash, "oh-owner2")


class TestCancel(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        self.job = self.store.create_or_reuse(_make_request())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cancel_queued(self) -> None:
        result = self.store.cancel("proj-A", self.job.job_id)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.status, "cancelled")
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "cancelled")
        self.assertIsNotNone(record.cancelled_at)

    def test_cancel_running(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(claim.claimed)
        result = self.store.cancel("proj-A", self.job.job_id)
        self.assertTrue(result.cancelled)

    def test_cancel_completed_is_idempotent(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.complete("proj-A", self.job.job_id, claim.claim_token)
        result = self.store.cancel("proj-A", self.job.job_id)
        self.assertFalse(result.cancelled)
        self.assertEqual(result.status, "completed")

    def test_cancelled_job_late_complete_ignored(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.cancel("proj-A", self.job.job_id)
        ok = self.store.complete("proj-A", self.job.job_id, claim.claim_token)
        self.assertFalse(ok)


class TestRetry(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        self.job = self.store.create_or_reuse(_make_request(max_attempts=2))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_retry_failed_job(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.fail(
            "proj-A", self.job.job_id, claim.claim_token,
            error_summary="err", retryable=False,
        )
        result = self.store.retry("proj-A", self.job.job_id)
        self.assertTrue(result.requeued)
        self.assertEqual(result.status, "queued")
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "queued")

    def test_retry_completed_returns_not_requeued(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.complete("proj-A", self.job.job_id, claim.claim_token)
        result = self.store.retry("proj-A", self.job.job_id)
        self.assertFalse(result.requeued)
        self.assertEqual(result.status, "completed")

    def test_retry_cancelled_requeues(self) -> None:
        self.store.cancel("proj-A", self.job.job_id)
        result = self.store.retry("proj-A", self.job.job_id)
        self.assertTrue(result.requeued)
        self.assertEqual(result.status, "queued")


class TestColdRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(
            Path(self._tmp.name) / "durable.db",
            lease_seconds=0.15,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_recover_expired_lease_requeues(self) -> None:
        job = self.store.create_or_reuse(_make_request())
        claim = self.store.claim("proj-A", job.job_id)
        self.assertTrue(claim.claimed)
        # Let lease expire.
        time.sleep(0.2)
        requeued = self.store.requeue_expired_leases()
        self.assertEqual(requeued, 1)
        record = self.store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "queued")

    def test_recover_on_startup_requeues_non_terminal(self) -> None:
        # Job 1: queued (never claimed).
        job1 = self.store.create_or_reuse(
            _make_request(business_key="bk-001")
        )
        # Job 2: running with expired lease.
        job2 = self.store.create_or_reuse(
            _make_request(business_key="bk-002")
        )
        self.store.claim("proj-A", job2.job_id)
        time.sleep(0.2)
        # Job 3: completed (terminal, should NOT be recovered).
        job3 = self.store.create_or_reuse(
            _make_request(business_key="bk-003")
        )
        claim3 = self.store.claim("proj-A", job3.job_id)
        self.store.complete("proj-A", job3.job_id, claim3.claim_token)

        recoverable = self.store.recover_on_startup()
        self.assertGreaterEqual(recoverable, 2)
        rec2 = self.store.get("proj-A", job2.job_id)
        self.assertEqual(rec2.status, "queued")
        rec3 = self.store.get("proj-A", job3.job_id)
        self.assertEqual(rec3.status, "completed")

    def test_cold_recovery_new_store_instance(self) -> None:
        """Simulate process restart: new store opens same DB file."""
        db_path = Path(self._tmp.name) / "durable.db"
        store1 = DurableJobStore(db_path, lease_seconds=0.15)
        job = store1.create_or_reuse(_make_request())
        claim = store1.claim("proj-A", job.job_id)
        self.assertTrue(claim.claimed)
        time.sleep(0.2)
        # Simulate restart — new store instance, same DB.
        store2 = DurableJobStore(db_path, lease_seconds=0.15)
        recoverable = store2.recover_on_startup()
        self.assertGreaterEqual(recoverable, 1)
        record = store2.get("proj-A", job.job_id)
        self.assertEqual(record.status, "queued")


class TestShutdown(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self._tmp.name) / "durable.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_shutdown_sets_flag_and_joins(self) -> None:
        worker = DurableJobWorker(self.store)
        self.assertFalse(worker.is_shutdown)
        worker.shutdown(timeout=1.0)
        self.assertTrue(worker.is_shutdown)

    def test_wake_after_shutdown_is_noop(self) -> None:
        worker = DurableJobWorker(self.store)
        worker.shutdown(timeout=0.5)
        job = self.store.create_or_reuse(_make_request())
        # wake should not raise and should not spawn a thread.
        worker.wake("proj-A", job.job_id)
        self.assertEqual(len(worker._threads), 0)


class TestProjectIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self._tmp.name) / "durable.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cross_project_get_fails_closed(self) -> None:
        job = self.store.create_or_reuse(_make_request(project_id="proj-A"))
        with self.assertRaises(DurableJobNotFound):
            self.store.get("proj-B", job.job_id)

    def test_cross_project_claim_fails_closed(self) -> None:
        job = self.store.create_or_reuse(_make_request(project_id="proj-A"))
        with self.assertRaises(DurableJobNotFound):
            self.store.claim("proj-B", job.job_id)

    def test_cross_project_cancel_fails_closed(self) -> None:
        job = self.store.create_or_reuse(_make_request(project_id="proj-A"))
        with self.assertRaises(DurableJobNotFound):
            self.store.cancel("proj-B", job.job_id)

    def test_list_is_project_scoped(self) -> None:
        self.store.create_or_reuse(_make_request(project_id="proj-A", business_key="bk-1"))
        self.store.create_or_reuse(_make_request(project_id="proj-B", business_key="bk-2"))
        a_jobs = self.store.list_by_project("proj-A")
        b_jobs = self.store.list_by_project("proj-B")
        self.assertEqual(len(a_jobs), 1)
        self.assertEqual(len(b_jobs), 1)
        self.assertNotEqual(a_jobs[0].job_id, b_jobs[0].job_id)

    def test_same_business_key_different_projects(self) -> None:
        """Same business_key under different projects must not conflict."""
        req_a = _make_request(project_id="proj-A", business_key="shared-bk")
        req_b = _make_request(project_id="proj-B", business_key="shared-bk")
        resp_a = self.store.create_or_reuse(req_a)
        resp_b = self.store.create_or_reuse(req_b)
        self.assertNotEqual(resp_a.job_id, resp_b.job_id)


class TestMonotonicProgress(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        self.job = self.store.create_or_reuse(_make_request())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_progress_can_only_increase(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        token = claim.claim_token
        # Advance to 0.4.
        self.store.heartbeat(
            "proj-A", self.job.job_id, token,
            DurableJobProgressPayload(phase="p1", percent=0.4, step=4, step_total=10),
        )
        # Try backward.
        self.store.heartbeat(
            "proj-A", self.job.job_id, token,
            DurableJobProgressPayload(phase="p2", percent=0.2, step=2, step_total=10),
        )
        record = self.store.get("proj-A", self.job.job_id)
        self.assertAlmostEqual(record.progress.percent, 0.4)
        self.assertEqual(record.progress.step, 4)

    def test_complete_with_regression_progress_keeps_higher(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        token = claim.claim_token
        self.store.heartbeat(
            "proj-A", self.job.job_id, token,
            DurableJobProgressPayload(phase="p1", percent=0.8, step=8, step_total=10),
        )
        # Complete with regressed progress.
        self.store.complete(
            "proj-A", self.job.job_id, token,
            final_progress=DurableJobProgressPayload(
                phase="done", percent=0.5, step=5, step_total=10
            ),
        )
        record = self.store.get("proj-A", self.job.job_id)
        self.assertAlmostEqual(record.progress.percent, 0.8)  # kept higher


class TestIsNewerProgressHelper(unittest.TestCase):
    def test_higher_percent_allowed(self) -> None:
        cur = DurableJobProgressPayload(percent=0.3, step=3, step_total=10)
        cand = DurableJobProgressPayload(percent=0.5, step=5, step_total=10)
        self.assertTrue(_is_newer_progress(cur, cand))

    def test_lower_percent_rejected(self) -> None:
        cur = DurableJobProgressPayload(percent=0.5, step=5, step_total=10)
        cand = DurableJobProgressPayload(percent=0.3, step=3, step_total=10)
        self.assertFalse(_is_newer_progress(cur, cand))

    def test_lower_step_rejected_even_if_percent_same(self) -> None:
        cur = DurableJobProgressPayload(percent=0.5, step=5, step_total=10)
        cand = DurableJobProgressPayload(percent=0.5, step=3, step_total=10)
        self.assertFalse(_is_newer_progress(cur, cand))

    def test_equal_progress_allowed(self) -> None:
        cur = DurableJobProgressPayload(percent=0.5, step=5, step_total=10)
        cand = DurableJobProgressPayload(percent=0.5, step=5, step_total=10)
        self.assertTrue(_is_newer_progress(cur, cand))


class TestLeaseExpiredHelper(unittest.TestCase):
    def test_empty_string_is_expired(self) -> None:
        self.assertTrue(_lease_is_expired("", datetime.now(timezone.utc)))

    def test_past_is_expired(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        self.assertTrue(_lease_is_expired(past, datetime.now(timezone.utc)))

    def test_future_is_not_expired(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
        self.assertFalse(_lease_is_expired(future, datetime.now(timezone.utc)))

    def test_malformed_is_expired(self) -> None:
        self.assertTrue(_lease_is_expired("not-a-date", datetime.now(timezone.utc)))

    def test_naive_datetime_treated_as_utc(self) -> None:
        future_naive = (datetime.utcnow() + timedelta(seconds=10)).isoformat()
        self.assertFalse(_lease_is_expired(future_naive, datetime.now(timezone.utc)))


class TestWorkerExecution(unittest.TestCase):
    """Integration test: register a fake executor, wake the worker, verify CAS completion."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(
            Path(self._tmp.name) / "durable.db",
            lease_seconds=5.0,
            heartbeat_interval_seconds=0.05,
        )
        self.worker = DurableJobWorker(self.store, poll_interval_seconds=0.02)

    def tearDown(self) -> None:
        self.worker.shutdown(timeout=2.0)
        self._tmp.cleanup()

    def test_worker_completes_job(self) -> None:
        job = self.store.create_or_reuse(_make_request())

        class FakeExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                # Simulate work with progress.
                heartbeat(DurableJobProgressPayload(phase="working", percent=0.5, step=1, step_total=2))
                return DurableJobResult(
                    output_hash="oh-fake",
                    artifact_locator='{"run_id":"r1"}',
                    provider="deepseek",
                    model="deepseek-v4-pro",
                )

        self.worker.register_executor(FakeExecutor())
        self.worker.wake("proj-A", job.job_id)
        # Wait for completion.
        for _ in range(100):
            record = self.store.get("proj-A", job.job_id)
            if record.status == "completed":
                break
            time.sleep(0.05)
        record = self.store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.output_hash, "oh-fake")
        self.assertEqual(record.provider, "deepseek")

    def test_worker_fails_job_on_executor_error(self) -> None:
        job = self.store.create_or_reuse(
            _make_request(business_key="bk-fail", max_attempts=1)
        )

        class FailingExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                raise RuntimeError("AI provider unavailable")

        self.worker.register_executor(FailingExecutor())
        self.worker.wake("proj-A", job.job_id)
        for _ in range(100):
            record = self.store.get("proj-A", job.job_id)
            if record.status in ("failed", "retry_wait"):
                break
            time.sleep(0.05)
        record = self.store.get("proj-A", job.job_id)
        # max_attempts=1 → fail with retryable=True → failed (attempt_count >= max)
        self.assertEqual(record.status, "failed")
        self.assertIn("AI provider unavailable", record.error_summary)

    def test_worker_cancel_isolation(self) -> None:
        """Cancel during execution: late complete must be ignored."""
        job = self.store.create_or_reuse(_make_request(business_key="bk-cancel"))
        cancel_event = threading.Event()

        class SlowExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                # Wait until cancelled or timeout.
                for _ in range(200):
                    if cancel_check():
                        return DurableJobResult(error="cancelled", retryable=False)
                    time.sleep(0.02)
                return DurableJobResult(output_hash="oh-late")

        self.worker.register_executor(SlowExecutor())
        self.worker.wake("proj-A", job.job_id)
        # Give the worker time to claim.
        time.sleep(0.1)
        # Cancel the job.
        self.store.cancel("proj-A", job.job_id)
        # Wait for the worker to observe cancellation.
        for _ in range(100):
            record = self.store.get("proj-A", job.job_id)
            if record.status == "cancelled":
                break
            time.sleep(0.05)
        record = self.store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "cancelled")

    def test_double_click_dedup(self) -> None:
        """Two rapid create_or_reuse calls return the same job_id."""
        req = _make_request(business_key="bk-double")
        first = self.store.create_or_reuse(req)
        second = self.store.create_or_reuse(req)
        self.assertEqual(first.job_id, second.job_id)
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)


class TestListAndFilter(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self._tmp.name) / "durable.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_list_by_type(self) -> None:
        self.store.create_or_reuse(
            _make_request(job_type="competitor_triage", business_key="bk-1")
        )
        self.store.create_or_reuse(
            _make_request(job_type="section_ai_candidate", business_key="bk-2")
        )
        triage = self.store.list_by_project("proj-A", job_type="competitor_triage")
        candidates = self.store.list_by_project("proj-A", job_type="section_ai_candidate")
        self.assertEqual(len(triage), 1)
        self.assertEqual(len(candidates), 1)

    def test_list_by_status(self) -> None:
        job = self.store.create_or_reuse(_make_request(business_key="bk-1"))
        self.store.cancel("proj-A", job.job_id)
        cancelled = self.store.list_by_project("proj-A", status="cancelled")
        self.assertEqual(len(cancelled), 1)
        queued = self.store.list_by_project("proj-A", status="queued")
        self.assertEqual(len(queued), 0)


class TestExecutorProtocol(unittest.TestCase):
    """Verify the DurableJobExecutor Protocol is documented and usable."""

    def test_protocol_is_defined(self) -> None:
        # Protocol has job_type in annotations and execute as a method.
        self.assertIn("job_type", DurableJobExecutor.__annotations__)
        self.assertTrue(hasattr(DurableJobExecutor, "execute"))
        # DurableJobResult is a concrete usable container.
        result = DurableJobResult(output_hash="test")
        self.assertEqual(result.output_hash, "test")
        self.assertEqual(result.error, "")
        self.assertFalse(result.retryable)


# ===========================================================================
# Follow-up regression tests (worker_01_followup_lease_01)
# ===========================================================================

class TestLeaseExpiryInvalidatesOwner(unittest.TestCase):
    """Fix 1: heartbeat, complete, fail must reject after lease expiry even
    when no replacement owner has claimed yet."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(
            Path(self._tmp.name) / "durable.db",
            lease_seconds=0.15,
        )
        self.job = self.store.create_or_reuse(_make_request())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_heartbeat_rejected_after_expiry_before_takeover(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(claim.claimed)
        time.sleep(0.2)
        # Lease expired — no one has claimed yet.
        ok = self.store.heartbeat("proj-A", self.job.job_id, claim.claim_token)
        self.assertFalse(ok)
        record = self.store.get("proj-A", self.job.job_id)
        # State unchanged — still running with old token, but lease is dead.
        self.assertEqual(record.status, "running")
        self.assertEqual(record.claim_token, claim.claim_token)

    def test_complete_rejected_after_expiry_before_takeover(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(claim.claimed)
        time.sleep(0.2)
        ok = self.store.complete(
            "proj-A", self.job.job_id, claim.claim_token,
            output_hash="oh-late",
        )
        self.assertFalse(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "running")  # not completed
        self.assertNotEqual(record.output_hash, "oh-late")

    def test_fail_rejected_after_expiry_before_takeover(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(claim.claimed)
        time.sleep(0.2)
        ok = self.store.fail(
            "proj-A", self.job.job_id, claim.claim_token,
            error_summary="late-fail", retryable=False,
        )
        self.assertFalse(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "running")  # not failed
        self.assertNotIn("late-fail", record.error_summary)

    def test_progress_not_mutated_after_expiry(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(claim.claimed)
        # Set initial progress.
        prog = DurableJobProgressPayload(percent=0.5, step=5, step_total=10)
        self.store.heartbeat("proj-A", self.job.job_id, claim.claim_token, prog)
        time.sleep(0.2)
        # Try heartbeat with new progress after expiry — must not mutate.
        ok = self.store.heartbeat(
            "proj-A", self.job.job_id, claim.claim_token,
            DurableJobProgressPayload(percent=0.9, step=9, step_total=10),
        )
        self.assertFalse(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertAlmostEqual(record.progress.percent, 0.5)  # unchanged


class TestCheckOwnership(unittest.TestCase):
    """Fix 2: check_ownership must detect lost ownership during execution."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(
            Path(self._tmp.name) / "durable.db",
            lease_seconds=0.15,
        )
        self.job = self.store.create_or_reuse(_make_request())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_check_ownership_true_for_live_claim(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(
            self.store.check_ownership("proj-A", self.job.job_id, claim.claim_token)
        )

    def test_check_ownership_false_for_wrong_token(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.assertFalse(
            self.store.check_ownership("proj-A", self.job.job_id, "wrong-token")
        )

    def test_check_ownership_false_after_takeover(self) -> None:
        owner1 = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(owner1.claimed)
        time.sleep(0.2)
        owner2 = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(owner2.claimed)
        # Old owner must see lost ownership.
        self.assertFalse(
            self.store.check_ownership("proj-A", self.job.job_id, owner1.claim_token)
        )
        # New owner is live.
        self.assertTrue(
            self.store.check_ownership("proj-A", self.job.job_id, owner2.claim_token)
        )

    def test_check_ownership_false_for_non_running(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.cancel("proj-A", self.job.job_id)
        self.assertFalse(
            self.store.check_ownership("proj-A", self.job.job_id, claim.claim_token)
        )

    def test_check_ownership_false_after_lease_expiry(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(claim.claimed)
        time.sleep(0.2)
        self.assertFalse(
            self.store.check_ownership("proj-A", self.job.job_id, claim.claim_token)
        )

    def test_cancel_check_observes_takeover(self) -> None:
        """Integration: executor sees cancellation when a new owner takes over."""
        seen_cancel = threading.Event()

        store = self.store
        job_id = self.job.job_id
        owner1_token = self.store.claim("proj-A", job_id).claim_token

        def cancel_check() -> bool:
            return not store.check_ownership("proj-A", job_id, owner1_token)

        def executor_body() -> None:
            for _ in range(100):
                if cancel_check():
                    seen_cancel.set()
                    return
                time.sleep(0.01)

        t = threading.Thread(target=executor_body, daemon=True)
        t.start()
        time.sleep(0.05)
        # Let lease expire and new owner take over.
        time.sleep(0.2)
        self.store.claim("proj-A", job_id)
        t.join(timeout=2.0)
        self.assertTrue(seen_cancel.is_set())


class TestRetryGuards(unittest.TestCase):
    """Fix 3: retry() must reject queued, running, and completed."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        self.job = self.store.create_or_reuse(_make_request(max_attempts=2))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_retry_queued_rejected(self) -> None:
        result = self.store.retry("proj-A", self.job.job_id)
        self.assertFalse(result.requeued)
        self.assertEqual(result.status, "queued")
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "queued")

    def test_retry_running_rejected(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(claim.claimed)
        result = self.store.retry("proj-A", self.job.job_id)
        self.assertFalse(result.requeued)
        self.assertEqual(result.status, "running")
        # Claim must not be stolen.
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.claim_token, claim.claim_token)

    def test_retry_completed_rejected(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.complete("proj-A", self.job.job_id, claim.claim_token)
        result = self.store.retry("proj-A", self.job.job_id)
        self.assertFalse(result.requeued)
        self.assertEqual(result.status, "completed")

    def test_retry_failed_succeeds(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.fail(
            "proj-A", self.job.job_id, claim.claim_token,
            error_summary="err", retryable=False,
        )
        result = self.store.retry("proj-A", self.job.job_id)
        self.assertTrue(result.requeued)
        self.assertEqual(result.status, "queued")

    def test_retry_retry_wait_succeeds(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.fail(
            "proj-A", self.job.job_id, claim.claim_token,
            error_summary="err", retryable=True,
        )
        result = self.store.retry("proj-A", self.job.job_id)
        self.assertTrue(result.requeued)
        self.assertEqual(result.status, "queued")


class TestShutdownOverallDeadline(unittest.TestCase):
    """Fix 4: shutdown uses one overall deadline; cancel_check observes shutdown."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_shutdown_uses_overall_deadline(self) -> None:
        """Multiple long-running threads must be joined within one overall timeout,
        not timeout per thread.  After graceful shutdown, claims are released
        to queued so a new process can reclaim immediately."""
        store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        worker = DurableJobWorker(store, poll_interval_seconds=0.01)
        # Register an executor that blocks until cancel_check is True.
        started = threading.Event()

        class BlockingExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                started.set()
                while not cancel_check():
                    time.sleep(0.01)
                return DurableJobResult(output_hash="after-cancel")

        worker.register_executor(BlockingExecutor())
        job = store.create_or_reuse(_make_request())
        worker.wake("proj-A", job.job_id)
        self.assertTrue(started.wait(timeout=2.0))
        # Shutdown with a short overall timeout.
        start = time.monotonic()
        worker.shutdown(timeout=1.0)
        elapsed = time.monotonic() - start
        # Must complete well under 2s (one overall deadline for all threads).
        self.assertLess(elapsed, 2.0)
        self.assertTrue(worker.is_shutdown)
        # Job should be released to queued (not running, not completed).
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "queued")

    def test_cancel_check_true_on_shutdown(self) -> None:
        """Well-behaved executors must see cancel_check=True on shutdown."""
        store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        worker = DurableJobWorker(store, poll_interval_seconds=0.01)
        observed_cancel = threading.Event()

        class ObservingExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                for _ in range(500):
                    if cancel_check():
                        observed_cancel.set()
                        return DurableJobResult(output_hash="ok")
                    time.sleep(0.01)
                return DurableJobResult(output_hash="timeout")

        worker.register_executor(ObservingExecutor())
        job = store.create_or_reuse(_make_request())
        worker.wake("proj-A", job.job_id)
        time.sleep(0.05)
        worker.shutdown(timeout=2.0)
        self.assertTrue(observed_cancel.is_set())

    def test_shutdown_job_remains_recoverable(self) -> None:
        """A running job left by shutdown is released to queued immediately
        (graceful release), so no lease-expiry wait is needed."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=0.3,
        )
        worker = DurableJobWorker(store, poll_interval_seconds=0.01)

        class BlockingExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                while not cancel_check():
                    time.sleep(0.01)
                return DurableJobResult(output_hash="never-persisted")

        worker.register_executor(BlockingExecutor())
        job = store.create_or_reuse(_make_request())
        worker.wake("proj-A", job.job_id)
        time.sleep(0.05)
        worker.shutdown(timeout=1.0)
        # Graceful release: job is immediately queued, not running.
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "queued")
        self.assertNotEqual(record.output_hash, "never-persisted")

    def test_negative_shutdown_timeout_rejected(self) -> None:
        store = DurableJobStore(Path(self._tmp.name) / "negative-timeout.db")
        worker = DurableJobWorker(store, enable_sweeper=False)
        with self.assertRaises(ValueError):
            worker.shutdown(timeout=-0.1)
        worker.shutdown(timeout=1.0)


class TestSweeperRecovery(unittest.TestCase):
    """Fix 5: periodic sweeper requeues expired leases without stealing live ones."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_sweeper_requeues_after_expiry(self) -> None:
        """A job with a short lease gets requeued by the sweeper after expiry."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=0.1,
        )
        worker = DurableJobWorker(
            store,
            poll_interval_seconds=0.01,
            sweeper_interval_seconds=0.05,
        )
        job = store.create_or_reuse(_make_request())
        claim = store.claim("proj-A", job.job_id)
        self.assertTrue(claim.claimed)
        # Wait for lease to expire and sweeper to fire.
        time.sleep(0.3)
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "queued")
        worker.shutdown(timeout=1.0)

    def test_sweeper_does_not_steal_live_lease(self) -> None:
        """While lease is still live, sweeper must not requeue."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=1.0,
        )
        worker = DurableJobWorker(
            store,
            poll_interval_seconds=0.01,
            sweeper_interval_seconds=0.05,
        )
        job = store.create_or_reuse(_make_request())
        claim = store.claim("proj-A", job.job_id)
        self.assertTrue(claim.claimed)
        # Within the lease period.
        time.sleep(0.2)
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "running")
        self.assertEqual(record.claim_token, claim.claim_token)
        worker.shutdown(timeout=1.0)

    def test_sweeper_stopped_on_shutdown(self) -> None:
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=0.1,
        )
        worker = DurableJobWorker(
            store,
            poll_interval_seconds=0.01,
            sweeper_interval_seconds=0.05,
        )
        sweeper = worker._sweeper_thread
        self.assertIsNotNone(sweeper)
        worker.shutdown(timeout=1.0)
        self.assertFalse(sweeper.is_alive())

    def test_restart_with_live_lease_recovers_after_expiry(self) -> None:
        """Simulate: process A holds a live lease, crashes; process B starts
        and the sweeper requeues after the original lease expires."""
        db_path = Path(self._tmp.name) / "durable.db"
        store_a = DurableJobStore(db_path, lease_seconds=0.2)
        job = store_a.create_or_reuse(_make_request())
        claim = store_a.claim("proj-A", job.job_id)
        self.assertTrue(claim.claimed)
        # Simulate crash — store_a just stops.  No shutdown; lease is "live" in DB.
        # Process B starts (new store + worker with sweeper).
        store_b = DurableJobStore(db_path, lease_seconds=0.2)
        worker_b = DurableJobWorker(
            store_b,
            poll_interval_seconds=0.01,
            sweeper_interval_seconds=0.05,
        )
        # Wait beyond the original lease expiry.
        time.sleep(0.35)
        record = store_b.get("proj-A", job.job_id)
        self.assertEqual(record.status, "queued")
        worker_b.shutdown(timeout=1.0)

    def test_sweeper_interval_must_be_positive(self) -> None:
        store = DurableJobStore(Path(self._tmp.name) / "invalid-sweeper.db")
        with self.assertRaises(ValueError):
            DurableJobWorker(store, sweeper_interval_seconds=0)

    def test_heartbeat_cadence_is_bounded_by_lease(self) -> None:
        """A short lease remains owned even when the configured heartbeat
        interval is longer than the lease."""
        store = DurableJobStore(
            Path(self._tmp.name) / "short-lease.db",
            lease_seconds=0.12,
            heartbeat_interval_seconds=30.0,
        )
        worker = DurableJobWorker(
            store,
            sweeper_interval_seconds=0.02,
        )
        calls = 0
        calls_lock = threading.Lock()

        class SlowExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                nonlocal calls
                with calls_lock:
                    calls += 1
                time.sleep(0.35)
                return DurableJobResult(output_hash="short-lease-complete")

        worker.register_executor(SlowExecutor())
        job = store.create_or_reuse(_make_request())
        worker.wake("proj-A", job.job_id)
        deadline = time.monotonic() + 2.0
        record = store.get("proj-A", job.job_id)
        while record.status != "completed" and time.monotonic() < deadline:
            time.sleep(0.02)
            record = store.get("proj-A", job.job_id)
        worker.shutdown(timeout=1.0)
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.output_hash, "short-lease-complete")
        self.assertEqual(calls, 1)


class TestNoDeadCode(unittest.TestCase):
    """Fix 6: _build_complete_params removed; wake has no no-op lock block."""

    def test_build_complete_params_removed(self) -> None:
        import services.api.app.medical_writing_durable_jobs as mod

        self.assertFalse(hasattr(mod, "_build_complete_params"))

    def test_wake_no_noop_lock(self) -> None:
        """wake should not contain a no-op 'with self._executor_lock: pass' block."""
        import inspect

        source = inspect.getsource(DurableJobWorker.wake)
        # The no-op block would contain "pass" immediately after acquiring the lock.
        self.assertNotIn("with self._executor_lock:", source)


# ===========================================================================
# Graceful release tests (worker_01_followup_shutdown_release_02)
# ===========================================================================

class TestReleaseClaim(unittest.TestCase):
    """Store-level release_claim CAS semantics."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        self.job = self.store.create_or_reuse(_make_request(max_attempts=3))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_release_running_claim_to_queued(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        ok = self.store.release_claim("proj-A", self.job.job_id, claim.claim_token)
        self.assertTrue(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "queued")
        self.assertEqual(record.claim_token, "")
        self.assertEqual(record.lease_expires_at, "")

    def test_release_wrong_token_fails(self) -> None:
        self.store.claim("proj-A", self.job.job_id)
        ok = self.store.release_claim("proj-A", self.job.job_id, "wrong-token")
        self.assertFalse(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.status, "running")  # unchanged

    def test_release_terminal_fails(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.complete("proj-A", self.job.job_id, claim.claim_token)
        ok = self.store.release_claim("proj-A", self.job.job_id, claim.claim_token)
        self.assertFalse(ok)

    def test_release_cancelled_fails(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.cancel("proj-A", self.job.job_id)
        ok = self.store.release_claim("proj-A", self.job.job_id, claim.claim_token)
        self.assertFalse(ok)

    def test_release_preserves_progress_and_payload(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        prog = DurableJobProgressPayload(percent=0.6, step=6, step_total=10)
        self.store.heartbeat("proj-A", self.job.job_id, claim.claim_token, prog)
        self.store.release_claim("proj-A", self.job.job_id, claim.claim_token)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertAlmostEqual(record.progress.percent, 0.6)
        self.assertEqual(record.progress.step, 6)

    def test_release_decrements_attempt_count(self) -> None:
        """Graceful release must not consume a retry attempt."""
        claim = self.store.claim("proj-A", self.job.job_id)
        # Claim sets attempt_count to 1 (first attempt).
        self.store.release_claim("proj-A", self.job.job_id, claim.claim_token)
        record = self.store.get("proj-A", self.job.job_id)
        # attempt_count decremented from 1 → floor 1.
        self.assertEqual(record.attempt_count, 1)

    def test_release_after_retry_wait_attempt_restores_slot(self) -> None:
        """If the job went to retry_wait (attempt=2), release from a new
        claim restores attempt_count to 1."""
        # First attempt fails → retry_wait, attempt_count becomes 2 after re-claim.
        claim1 = self.store.claim("proj-A", self.job.job_id)
        self.store.fail("proj-A", self.job.job_id, claim1.claim_token,
                         error_summary="transient", retryable=True)
        rec = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(rec.status, "retry_wait")
        self.assertEqual(rec.attempt_count, 1)
        # Re-claim from retry_wait → attempt_count = 2.
        claim2 = self.store.claim("proj-A", self.job.job_id)
        rec = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(rec.attempt_count, 2)
        # Graceful release restores attempt_count to 1.
        self.store.release_claim("proj-A", self.job.job_id, claim2.claim_token)
        rec = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(rec.attempt_count, 1)

    def test_release_then_new_worker_claims_immediately(self) -> None:
        """After release, a new claim succeeds without waiting for lease expiry."""
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.release_claim("proj-A", self.job.job_id, claim.claim_token)
        # Immediate re-claim must succeed.
        claim2 = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(claim2.claimed)

    def test_release_does_not_steal_live_owner(self) -> None:
        """release_claim with the wrong token must not steal a live owner."""
        owner1 = self.store.claim("proj-A", self.job.job_id)
        # Attempt release with a fabricated token.
        ok = self.store.release_claim("proj-A", self.job.job_id, "bogus-token")
        self.assertFalse(ok)
        record = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(record.claim_token, owner1.claim_token)


class TestGracefulShutdownReleasesClaims(unittest.TestCase):
    """Worker shutdown releases active claims so a new process can reclaim
    immediately without waiting for the 600-second default lease."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_graceful_shutdown_releases_running_job(self) -> None:
        """A running job is released to queued on graceful shutdown."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker = DurableJobWorker(store, poll_interval_seconds=0.01,
                                   enable_sweeper=False)
        started = threading.Event()

        class BlockingExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                started.set()
                while not cancel_check():
                    time.sleep(0.01)
                return DurableJobResult(output_hash="never")

        worker.register_executor(BlockingExecutor())
        job = store.create_or_reuse(_make_request())
        worker.wake("proj-A", job.job_id)
        self.assertTrue(started.wait(timeout=2.0))
        # Shutdown releases the claim.
        worker.shutdown(timeout=2.0)
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "queued")
        self.assertEqual(record.claim_token, "")
        self.assertNotEqual(record.output_hash, "never")

    def test_new_worker_claims_immediately_after_graceful_shutdown(self) -> None:
        """Two-worker restart: worker A shuts down gracefully, worker B
        reclaims without waiting for the 600s lease."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker_a = DurableJobWorker(store, poll_interval_seconds=0.01,
                                     enable_sweeper=False)
        started = threading.Event()

        class BlockingExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                started.set()
                while not cancel_check():
                    time.sleep(0.01)
                return DurableJobResult(output_hash="never")

        worker_a.register_executor(BlockingExecutor())
        job = store.create_or_reuse(_make_request())
        worker_a.wake("proj-A", job.job_id)
        self.assertTrue(started.wait(timeout=2.0))
        worker_a.shutdown(timeout=2.0)
        # Worker B should be able to claim immediately.
        claim_b = store.claim("proj-A", job.job_id)
        self.assertTrue(claim_b.claimed)
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "running")
        self.assertEqual(record.claim_token, claim_b.claim_token)

    def test_live_non_shutdown_owner_not_stolen(self) -> None:
        """A live running job (no shutdown) must not be releasable or claimable
        by another worker."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker_a = DurableJobWorker(store, poll_interval_seconds=0.01,
                                     enable_sweeper=False)
        started = threading.Event()
        release_attempted = threading.Event()

        class SlowExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                started.set()
                # Wait longer than the test timeout.
                for _ in range(500):
                    if cancel_check():
                        return DurableJobResult(output_hash="cancelled")
                    time.sleep(0.01)
                return DurableJobResult(output_hash="done")

        worker_a.register_executor(SlowExecutor())
        job = store.create_or_reuse(_make_request())
        worker_a.wake("proj-A", job.job_id)
        self.assertTrue(started.wait(timeout=2.0))
        # Worker B cannot claim while A is live (no shutdown).
        claim_b = store.claim("proj-A", job.job_id)
        self.assertFalse(claim_b.claimed)
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "running")
        # Now shut down A — releases the claim.
        worker_a.shutdown(timeout=2.0)
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "queued")

    def test_late_executor_cannot_overwrite_released(self) -> None:
        """After shutdown release, a late executor result cannot complete/fail
        the requeued job."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker_a = DurableJobWorker(store, poll_interval_seconds=0.01,
                                     enable_sweeper=False)
        executor_token = {"value": ""}
        executor_returned = threading.Event()

        class CapturingExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                executor_token["value"] = claim_token
                while not cancel_check():
                    time.sleep(0.01)
                executor_returned.set()
                return DurableJobResult(output_hash="late-result")

        worker_a.register_executor(CapturingExecutor())
        job = store.create_or_reuse(_make_request())
        worker_a.wake("proj-A", job.job_id)
        # Wait for the executor to start.
        time.sleep(0.1)
        # Shut down A — releases claim.
        worker_a.shutdown(timeout=2.0)
        # Worker B reclaims.
        claim_b = store.claim("proj-A", job.job_id)
        self.assertTrue(claim_b.claimed)
        # Wait for the late executor to return with its result.
        self.assertTrue(executor_returned.wait(timeout=2.0))
        # The late executor's token should no longer be valid.
        ok = store.complete("proj-A", job.job_id, executor_token["value"],
                             output_hash="late-result")
        self.assertFalse(ok)
        ok = store.fail("proj-A", job.job_id, executor_token["value"],
                         error_summary="late-fail")
        self.assertFalse(ok)
        # Worker B's claim is still valid.
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.claim_token, claim_b.claim_token)
        self.assertEqual(record.output_hash, "")

    def test_attempt_accounting_after_graceful_restart(self) -> None:
        """A graceful shutdown+restart cycle does not consume a retry attempt.
        Verify that after restart, the same failure count still has full retries."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker_a = DurableJobWorker(store, poll_interval_seconds=0.01,
                                     enable_sweeper=False)
        started = threading.Event()

        class BlockingExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                started.set()
                while not cancel_check():
                    time.sleep(0.01)
                return DurableJobResult(output_hash="never")

        worker_a.register_executor(BlockingExecutor())
        job = store.create_or_reuse(_make_request(max_attempts=3))
        worker_a.wake("proj-A", job.job_id)
        self.assertTrue(started.wait(timeout=2.0))
        worker_a.shutdown(timeout=2.0)
        record = store.get("proj-A", job.job_id)
        # attempt_count should still be 1 (not consumed by the interruption).
        self.assertEqual(record.attempt_count, 1)
        # After restart, the job should have full 3 retries available.
        self.assertEqual(record.max_attempts, 3)

    def test_multiple_claims_released_on_shutdown(self) -> None:
        """Multiple simultaneous jobs are all released on shutdown."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker = DurableJobWorker(store, poll_interval_seconds=0.01,
                                   enable_sweeper=False)
        all_started = threading.Event()
        start_count = {"n": 0}
        count_lock = threading.Lock()

        class MultiExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                with count_lock:
                    start_count["n"] += 1
                    if start_count["n"] >= 3:
                        all_started.set()
                while not cancel_check():
                    time.sleep(0.01)
                return DurableJobResult(output_hash="never")

        job_a = store.create_or_reuse(_make_request(business_key="bk-a"))
        job_b = store.create_or_reuse(_make_request(business_key="bk-b"))
        job_c = store.create_or_reuse(_make_request(business_key="bk-c"))
        worker.register_executor(MultiExecutor())
        worker.wake("proj-A", job_a.job_id)
        worker.wake("proj-A", job_b.job_id)
        worker.wake("proj-A", job_c.job_id)
        self.assertTrue(all_started.wait(timeout=3.0))
        worker.shutdown(timeout=3.0)
        for job in (job_a, job_b, job_c):
            record = store.get("proj-A", job.job_id)
            self.assertEqual(record.status, "queued")
            self.assertEqual(record.claim_token, "")

    def test_shutdown_timeout_with_slow_executor_releases_anyway(self) -> None:
        """Even if shutdown timeout expires while a slow executor thread is
        still alive, the claim is released."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker = DurableJobWorker(store, poll_interval_seconds=0.01,
                                   enable_sweeper=False)

        class VerySlowExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                # Ignores cancel_check — blocks for a long time.
                time.sleep(10.0)
                return DurableJobResult(output_hash="never")

        worker.register_executor(VerySlowExecutor())
        job = store.create_or_reuse(_make_request())
        worker.wake("proj-A", job.job_id)
        time.sleep(0.1)
        start = time.monotonic()
        worker.shutdown(timeout=0.5)
        elapsed = time.monotonic() - start
        # Shutdown must complete within bounded time.
        self.assertLess(elapsed, 3.0)
        # Claim is released even though the executor thread is still alive.
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "queued")

    def test_idempotent_repeated_shutdown(self) -> None:
        """Repeated shutdown() calls are safe and do not error."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker = DurableJobWorker(store, poll_interval_seconds=0.01,
                                   enable_sweeper=False)
        worker.shutdown(timeout=1.0)
        worker.shutdown(timeout=1.0)
        worker.shutdown(timeout=1.0)
        self.assertTrue(worker.is_shutdown)

    def test_no_release_on_ordinary_completion(self) -> None:
        """Ordinary non-shutdown execution must not release the claim — it
        completes normally."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker = DurableJobWorker(store, poll_interval_seconds=0.01,
                                   enable_sweeper=False)

        class FastExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                return DurableJobResult(output_hash="ok")

        worker.register_executor(FastExecutor())
        job = store.create_or_reuse(_make_request())
        worker.wake("proj-A", job.job_id)
        for _ in range(100):
            record = store.get("proj-A", job.job_id)
            if record.status == "completed":
                break
            time.sleep(0.02)
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.output_hash, "ok")
        worker.shutdown(timeout=1.0)


# ===========================================================================
# Attempt-semantics regression tests (worker_01_followup_attempt_semantics_03)
# ===========================================================================

class TestAttemptAccountingExact(unittest.TestCase):
    """release_claim must restore attempt_count to the exact pre-claim value.
    The next claim from queued must see the same count the interrupted claim saw."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_first_claim_release_reclaim_preserves_count(self) -> None:
        """create(1) → claim(1) → release(1) → reclaim(1): no attempt consumed."""
        store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        job = store.create_or_reuse(_make_request(max_attempts=3))
        pre_claim = store.get("proj-A", job.job_id).attempt_count
        self.assertEqual(pre_claim, 1)
        claim = store.claim("proj-A", job.job_id)
        during_claim = store.get("proj-A", job.job_id).attempt_count
        self.assertEqual(during_claim, 1)
        store.release_claim("proj-A", job.job_id, claim.claim_token)
        after_release = store.get("proj-A", job.job_id).attempt_count
        self.assertEqual(after_release, 1)
        # Reclaim.
        store.claim("proj-A", job.job_id)
        after_reclaim = store.get("proj-A", job.job_id).attempt_count
        self.assertEqual(after_reclaim, 1, "reclaim must equal pre-claim count")

    def test_retry_wait_claim_release_restores_pre_claim(self) -> None:
        """create(1) → claim(1) → fail(retry_wait) → claim(2) → release(1) → reclaim(1)."""
        store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        job = store.create_or_reuse(_make_request(max_attempts=3))
        claim1 = store.claim("proj-A", job.job_id)
        store.fail("proj-A", job.job_id, claim1.claim_token,
                    error_summary="transient", retryable=True)
        # retry_wait, attempt_count still 1.
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)
        claim2 = store.claim("proj-A", job.job_id)
        # claim from retry_wait increments to 2.
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 2)
        store.release_claim("proj-A", job.job_id, claim2.claim_token)
        # Release restores to 1.
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)
        # Reclaim from queued preserves 1.
        store.claim("proj-A", job.job_id)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)

    def test_retry_wait_reclaim_clears_stale_error_summary(self) -> None:
        store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        job = store.create_or_reuse(_make_request(max_attempts=3))
        claim1 = store.claim("proj-A", job.job_id)
        store.fail(
            "proj-A",
            job.job_id,
            claim1.claim_token,
            error_summary="transient upstream error",
            retryable=True,
        )
        self.assertEqual(
            store.get("proj-A", job.job_id).error_summary,
            "transient upstream error",
        )

        claim2 = store.claim("proj-A", job.job_id)

        self.assertTrue(claim2.claimed)
        self.assertEqual(claim2.job.status, "running")
        self.assertEqual(claim2.job.error_summary, "")

    def test_repeated_graceful_restarts_near_max_attempts(self) -> None:
        """Multiple graceful restart cycles must never consume attempts.
        Even after many interruptions, attempt_count stays at 1."""
        store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        job = store.create_or_reuse(_make_request(max_attempts=2))
        for i in range(5):
            claim = store.claim("proj-A", job.job_id)
            self.assertTrue(claim.claimed)
            during = store.get("proj-A", job.job_id).attempt_count
            self.assertEqual(during, 1, f"iteration {i}: attempt consumed")
            store.release_claim("proj-A", job.job_id, claim.claim_token)
            after = store.get("proj-A", job.job_id).attempt_count
            self.assertEqual(after, 1, f"iteration {i}: release did not restore")

    def test_graceful_restart_does_not_reduce_max_failures(self) -> None:
        """After graceful restart, the job still has full failure retries."""
        store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        job = store.create_or_reuse(_make_request(max_attempts=2))
        # Interrupt with graceful release.
        claim1 = store.claim("proj-A", job.job_id)
        store.release_claim("proj-A", job.job_id, claim1.claim_token)
        # Now fail twice — should go to failed, not exhausted early.
        claim2 = store.claim("proj-A", job.job_id)
        store.fail("proj-A", job.job_id, claim2.claim_token,
                    error_summary="err1", retryable=True)
        rec = store.get("proj-A", job.job_id)
        self.assertEqual(rec.status, "retry_wait")
        self.assertEqual(rec.attempt_count, 1)
        claim3 = store.claim("proj-A", job.job_id)
        store.fail("proj-A", job.job_id, claim3.claim_token,
                    error_summary="err2", retryable=True)
        rec = store.get("proj-A", job.job_id)
        self.assertEqual(rec.status, "failed")


class TestReleaseClaimLiveLeaseGuard(unittest.TestCase):
    """release_claim must require a still-live valid lease at the CAS boundary."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=0.15,
        )
        self.job = self.store.create_or_reuse(_make_request())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_release_rejected_after_lease_expiry(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        time.sleep(0.2)
        ok = self.store.release_claim("proj-A", self.job.job_id, claim.claim_token)
        self.assertFalse(ok)
        rec = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(rec.status, "running")  # unchanged
        self.assertEqual(rec.attempt_count, 1)  # unchanged

    def test_release_rejected_for_wrong_token(self) -> None:
        self.store.claim("proj-A", self.job.job_id)
        ok = self.store.release_claim("proj-A", self.job.job_id, "bogus")
        self.assertFalse(ok)

    def test_release_rejected_for_terminal(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        self.store.complete("proj-A", self.job.job_id, claim.claim_token)
        ok = self.store.release_claim("proj-A", self.job.job_id, claim.claim_token)
        self.assertFalse(ok)

    def test_release_rejected_after_replacement_owner(self) -> None:
        """After a new owner claims via lease expiry, old owner release fails."""
        owner1 = self.store.claim("proj-A", self.job.job_id)
        time.sleep(0.2)
        owner2 = self.store.claim("proj-A", self.job.job_id)
        self.assertTrue(owner2.claimed)
        ok = self.store.release_claim("proj-A", self.job.job_id, owner1.claim_token)
        self.assertFalse(ok)
        rec = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(rec.claim_token, owner2.claim_token)

    def test_release_rejected_for_empty_lease(self) -> None:
        """Directly write an empty lease to simulate DB corruption."""
        claim = self.store.claim("proj-A", self.job.job_id)
        with self.store._connect() as conn:
            conn.execute(
                "UPDATE durable_mw_jobs SET lease_expires_at = '' "
                "WHERE project_id = ? AND job_id = ?",
                ("proj-A", self.job.job_id),
            )
            conn.commit()
        ok = self.store.release_claim("proj-A", self.job.job_id, claim.claim_token)
        self.assertFalse(ok)

    def test_release_rejected_for_malformed_lease(self) -> None:
        claim = self.store.claim("proj-A", self.job.job_id)
        with self.store._connect() as conn:
            conn.execute(
                "UPDATE durable_mw_jobs SET lease_expires_at = 'not-a-date' "
                "WHERE project_id = ? AND job_id = ?",
                ("proj-A", self.job.job_id),
            )
            conn.commit()
        ok = self.store.release_claim("proj-A", self.job.job_id, claim.claim_token)
        self.assertFalse(ok)

    def test_release_does_not_mutate_on_failure(self) -> None:
        """Failed release must not change attempt_count, status, or lease."""
        claim = self.store.claim("proj-A", self.job.job_id)
        before = self.store.get("proj-A", self.job.job_id)
        time.sleep(0.2)
        ok = self.store.release_claim("proj-A", self.job.job_id, claim.claim_token)
        self.assertFalse(ok)
        after = self.store.get("proj-A", self.job.job_id)
        self.assertEqual(after.attempt_count, before.attempt_count)
        self.assertEqual(after.status, before.status)


class TestShutdownInterleavingBoundary(unittest.TestCase):
    """The shutdown-vs-completion race must be deterministic: either the
    already-finished executor result completes before shutdown releases,
    or shutdown releases the claim.  The job must not remain live for 600s."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_shutdown_during_completion_no_lost_claim(self) -> None:
        """Executor returns normally; shutdown fires concurrently at the
        boundary.  The job must either complete or be released — never
        stuck running with a dead worker."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker = DurableJobWorker(store, poll_interval_seconds=0.01,
                                   enable_sweeper=False)
        barrier = threading.Event()
        result_produced = threading.Event()

        class BarrierExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                # Produce result immediately but wait at the barrier before
                # returning, so shutdown can fire during the completion path.
                result_produced.set()
                # Wait a short time for shutdown to fire, or return.
                for _ in range(50):
                    if cancel_check():
                        return DurableJobResult(output_hash="shutdown-seen")
                    time.sleep(0.01)
                barrier.set()
                return DurableJobResult(output_hash="completed-normally")

        worker.register_executor(BarrierExecutor())
        job = store.create_or_reuse(_make_request())
        worker.wake("proj-A", job.job_id)
        self.assertTrue(result_produced.wait(timeout=2.0))
        # Fire shutdown concurrently.
        worker.shutdown(timeout=2.0)
        # The job must not be stuck running with a live 600s lease.
        record = store.get("proj-A", job.job_id)
        self.assertIn(record.status, ("queued", "completed", "failed"))
        # If completed, the executor won the race.  If queued, shutdown released.
        # Either way, claim_token must be empty or a new owner's.
        if record.status == "queued":
            self.assertEqual(record.claim_token, "")
        elif record.status == "completed":
            self.assertIn(record.output_hash, ("completed-normally", "shutdown-seen"))

    def test_shutdown_after_active_claim_removal_still_completes(self) -> None:
        """If the executor finishes and removes its claim before shutdown,
        shutdown has nothing to release and the job completes normally."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker = DurableJobWorker(store, poll_interval_seconds=0.01,
                                   enable_sweeper=False)
        completed = threading.Event()

        class FastExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                return DurableJobResult(output_hash="fast-ok")

        worker.register_executor(FastExecutor())
        job = store.create_or_reuse(_make_request())
        worker.wake("proj-A", job.job_id)
        # Wait for completion.
        for _ in range(100):
            rec = store.get("proj-A", job.job_id)
            if rec.status == "completed":
                completed.set()
                break
            time.sleep(0.02)
        # Now shutdown — nothing to release.
        worker.shutdown(timeout=1.0)
        self.assertTrue(completed.is_set())
        rec = store.get("proj-A", job.job_id)
        self.assertEqual(rec.status, "completed")
        self.assertEqual(rec.output_hash, "fast-ok")


# ===========================================================================
# Finalize-race regression tests (worker_01_followup_finalize_race_04)
# ===========================================================================

class TestFinalizeRaceBarrier(unittest.TestCase):
    """Deterministic test that blocks the worker thread immediately before
    complete/fail CAS, starts shutdown, proves bounded shutdown with no live
    orphan, then releases the barrier and proves late finalize cannot overwrite
    a re-claim/new owner."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_shutdown_races_complete_cas(self) -> None:
        """Block before complete CAS; shutdown fires and must return bounded
        with row queued or completed, never running/live."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker = DurableJobWorker(store, poll_interval_seconds=0.01,
                                   enable_sweeper=False)
        executor_done = threading.Event()
        complete_barrier = threading.Event()
        complete_entered = threading.Event()
        original_complete = store.complete

        def blocking_complete(pid, jid, token, **kw):
            complete_entered.set()
            # Block until the test releases the barrier.
            complete_barrier.wait(timeout=5.0)
            return original_complete(pid, jid, token, **kw)

        store.complete = blocking_complete  # type: ignore[assignment]

        class FastExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                executor_done.set()
                return DurableJobResult(output_hash="ok")

        worker.register_executor(FastExecutor())
        job = store.create_or_reuse(_make_request())
        worker.wake("proj-A", job.job_id)
        # Wait for executor to return and worker to enter complete().
        self.assertTrue(executor_done.wait(timeout=2.0))
        self.assertTrue(complete_entered.wait(timeout=2.0))
        # Worker is blocked inside complete().  Fire shutdown with short timeout.
        start = time.monotonic()
        worker.shutdown(timeout=1.0)
        elapsed = time.monotonic() - start
        # Shutdown must return bounded — under 3 seconds.
        self.assertLess(elapsed, 3.0)
        # The row must NOT be running/live — either queued (release won CAS)
        # or still waiting for complete CAS to commit (which is blocked).
        # Since release_claim CAS raced and won (complete is blocked),
        # the row should be queued.
        record = store.get("proj-A", job.job_id)
        self.assertIn(record.status, ("queued", "completed"))
        if record.status == "queued":
            self.assertEqual(record.claim_token, "")
        # Release the barrier so the blocked complete CAS can proceed.
        # It must NOT overwrite the released/queued row.
        complete_barrier.set()
        # Give the worker thread time to finish.
        time.sleep(0.2)
        record = store.get("proj-A", job.job_id)
        # The late complete CAS must have failed (row is queued, not running).
        self.assertIn(record.status, ("queued", "completed"))
        if record.status == "queued":
            # Complete CAS failed because release already set status=queued.
            self.assertEqual(record.output_hash, "")
        # If a new owner re-claims, the late complete must not corrupt it.
        if record.status == "queued":
            new_claim = store.claim("proj-A", job.job_id)
            self.assertTrue(new_claim.claimed)

    def test_shutdown_races_fail_cas(self) -> None:
        """Same race but with retryable-fail finalization."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker = DurableJobWorker(store, poll_interval_seconds=0.01,
                                   enable_sweeper=False)
        executor_done = threading.Event()
        fail_barrier = threading.Event()
        fail_entered = threading.Event()
        original_fail = store.fail

        def blocking_fail(pid, jid, token, **kw):
            fail_entered.set()
            fail_barrier.wait(timeout=5.0)
            return original_fail(pid, jid, token, **kw)

        store.fail = blocking_fail  # type: ignore[assignment]

        class FailingExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                executor_done.set()
                return DurableJobResult(error="transient", retryable=True)

        worker.register_executor(FailingExecutor())
        job = store.create_or_reuse(_make_request())
        worker.wake("proj-A", job.job_id)
        self.assertTrue(executor_done.wait(timeout=2.0))
        self.assertTrue(fail_entered.wait(timeout=2.0))
        start = time.monotonic()
        worker.shutdown(timeout=1.0)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 3.0)
        record = store.get("proj-A", job.job_id)
        self.assertIn(record.status, ("queued", "retry_wait", "failed"))
        # Release barrier so blocked fail CAS can proceed.
        fail_barrier.set()
        time.sleep(0.2)
        record = store.get("proj-A", job.job_id)
        # The late fail CAS must have failed (row was released to queued).
        self.assertIn(record.status, ("queued", "retry_wait", "failed"))
        if record.status == "queued":
            self.assertEqual(record.error_summary, "")
            # New owner can reclaim.
            new_claim = store.claim("proj-A", job.job_id)
            self.assertTrue(new_claim.claimed)

    def test_no_live_orphan_after_shutdown_during_finalize(self) -> None:
        """After shutdown returns during a blocked finalize, the row must never
        be running with a live lease and no active worker."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        worker = DurableJobWorker(store, poll_interval_seconds=0.01,
                                   enable_sweeper=False)
        complete_entered = threading.Event()
        complete_barrier = threading.Event()
        original_complete = store.complete

        def blocking_complete(pid, jid, token, **kw):
            complete_entered.set()
            complete_barrier.wait(timeout=5.0)
            return original_complete(pid, jid, token, **kw)

        store.complete = blocking_complete  # type: ignore[assignment]

        class FastExecutor:
            job_type = "competitor_triage"

            def execute(self, job_record, claim_token, cancel_check, heartbeat):
                return DurableJobResult(output_hash="ok")

        worker.register_executor(FastExecutor())
        job = store.create_or_reuse(_make_request())
        worker.wake("proj-A", job.job_id)
        self.assertTrue(complete_entered.wait(timeout=2.0))
        worker.shutdown(timeout=1.0)
        # At this point the row must NOT be running/live.
        record = store.get("proj-A", job.job_id)
        self.assertNotEqual(record.status, "running")
        # Clean up the blocked thread.
        complete_barrier.set()
        time.sleep(0.2)

    def test_complete_wins_over_release(self) -> None:
        """If complete CAS wins the race, release_claim returns False on
        the terminal row."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        job = store.create_or_reuse(_make_request())
        claim = store.claim("proj-A", job.job_id)
        # Complete wins.
        ok = store.complete("proj-A", job.job_id, claim.claim_token,
                             output_hash="winner")
        self.assertTrue(ok)
        # Release attempts after terminal — must fail.
        ok2 = store.release_claim("proj-A", job.job_id, claim.claim_token)
        self.assertFalse(ok2)
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.output_hash, "winner")

    def test_release_wins_over_complete(self) -> None:
        """If release CAS wins the race, complete returns False on the queued
        row."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=600.0,
        )
        job = store.create_or_reuse(_make_request())
        claim = store.claim("proj-A", job.job_id)
        # Release wins.
        ok = store.release_claim("proj-A", job.job_id, claim.claim_token)
        self.assertTrue(ok)
        # Complete attempts after release — must fail.
        ok2 = store.complete("proj-A", job.job_id, claim.claim_token,
                              output_hash="late")
        self.assertFalse(ok2)
        record = store.get("proj-A", job.job_id)
        self.assertEqual(record.status, "queued")
        self.assertEqual(record.output_hash, "")


# ===========================================================================
# Claim-origin attempt-accounting tests (worker_01_followup_claim_origin_05)
# ===========================================================================

class TestClaimOriginAttemptAccounting(unittest.TestCase):
    """Origin-aware attempt accounting: release_claim decrements only when the
    current claim actually incremented attempt_count (retry_wait origin).
    Queued/expired-running origins preserve the count."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_retry_wait_claim_release_restores_previous_count(self) -> None:
        """create → claim(1) → fail(retry_wait) → claim(2,incremented) → release(1)."""
        store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        job = store.create_or_reuse(_make_request(max_attempts=3))
        claim1 = store.claim("proj-A", job.job_id)
        store.fail("proj-A", job.job_id, claim1.claim_token,
                    error_summary="transient", retryable=True)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)
        claim2 = store.claim("proj-A", job.job_id)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 2)
        store.release_claim("proj-A", job.job_id, claim2.claim_token)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)
        # Reclaim from queued preserves 1.
        store.claim("proj-A", job.job_id)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)

    def test_queued_claim_release_reclaim_preserves_count(self) -> None:
        """First claim from queued does not increment; release preserves."""
        store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        job = store.create_or_reuse(_make_request(max_attempts=3))
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)
        claim = store.claim("proj-A", job.job_id)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)
        store.release_claim("proj-A", job.job_id, claim.claim_token)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)
        store.claim("proj-A", job.job_id)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)

    def test_expired_running_takeover_preserves_count_on_release(self) -> None:
        """The critical defect: expired-running takeover at attempt >1 must NOT
        decrement on release.  The takeover claim did not increment; decrementing
        would refund a prior genuine failed attempt.

        Sequence: create → claim(1) → fail(retry_wait,1) → claim(2,incr) →
        fail(retry_wait,2) → claim(3,incr) → [lease expires] → claim(3,NOT incr,
        expired-running takeover) → release(3, NOT decremented because flag=0).
        """
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=0.15,
        )
        job = store.create_or_reuse(_make_request(max_attempts=5))
        # First attempt: claim from queued → attempt=1.
        claim1 = store.claim("proj-A", job.job_id)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)
        # Fail to retry_wait.
        store.fail("proj-A", job.job_id, claim1.claim_token,
                    error_summary="err1", retryable=True)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)
        # Second attempt: claim from retry_wait → attempt=2 (incremented).
        claim2 = store.claim("proj-A", job.job_id)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 2)
        # Fail again to retry_wait.
        store.fail("proj-A", job.job_id, claim2.claim_token,
                    error_summary="err2", retryable=True)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 2)
        # Third attempt: claim from retry_wait → attempt=3 (incremented).
        claim3 = store.claim("proj-A", job.job_id)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 3)
        # Let lease expire.
        time.sleep(0.2)
        # Takeover: claim from expired-running → attempt stays 3 (NOT incremented).
        claim4 = store.claim("proj-A", job.job_id)
        self.assertTrue(claim4.claimed)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 3)
        # Graceful release: must NOT decrement because this claim did not increment.
        store.release_claim("proj-A", job.job_id, claim4.claim_token)
        # attempt_count must stay at 3, NOT drop to 2.
        self.assertEqual(
            store.get("proj-A", job.job_id).attempt_count, 3,
            "expired-running takeover release must not decrement attempt_count"
        )
        # Reclaim from queued preserves 3.
        store.claim("proj-A", job.job_id)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 3)

    def test_multiple_queued_restarts_do_not_drift(self) -> None:
        """Multiple graceful restart cycles from queued never drift the count."""
        store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        job = store.create_or_reuse(_make_request(max_attempts=3))
        for i in range(10):
            claim = store.claim("proj-A", job.job_id)
            self.assertTrue(claim.claimed)
            during = store.get("proj-A", job.job_id).attempt_count
            self.assertEqual(during, 1, f"iteration {i}: count drifted up")
            store.release_claim("proj-A", job.job_id, claim.claim_token)
            after = store.get("proj-A", job.job_id).attempt_count
            self.assertEqual(after, 1, f"iteration {i}: count drifted down")

    def test_multiple_retry_wait_cycles_with_interruption(self) -> None:
        """Interleave genuine failures with graceful interruptions to verify
        the count correctly tracks genuine attempts only."""
        store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        job = store.create_or_reuse(_make_request(max_attempts=5))
        # Genuine failure 1: claim(1) → fail(retry_wait,1).
        c1 = store.claim("proj-A", job.job_id)
        store.fail("proj-A", job.job_id, c1.claim_token,
                    error_summary="e1", retryable=True)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 1)
        # Genuine failure 2: claim(2,incr) → fail(retry_wait,2).
        c2 = store.claim("proj-A", job.job_id)
        store.fail("proj-A", job.job_id, c2.claim_token,
                    error_summary="e2", retryable=True)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 2)
        # Interrupted attempt 3: claim(3,incr) → release(2,restored).
        c3 = store.claim("proj-A", job.job_id)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 3)
        store.release_claim("proj-A", job.job_id, c3.claim_token)
        # Count restored to 2 (the interruption did not consume an attempt).
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 2)
        # Genuine failure 3: claim from queued(2) → fail(retry_wait,2).
        c4 = store.claim("proj-A", job.job_id)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 2)
        store.fail("proj-A", job.job_id, c4.claim_token,
                    error_summary="e3", retryable=True)
        self.assertEqual(store.get("proj-A", job.job_id).attempt_count, 2)

    def test_token_mismatch_cannot_alter_origin_count(self) -> None:
        """Wrong-token release must not change attempt_count or the flag."""
        store = DurableJobStore(Path(self._tmp.name) / "durable.db")
        job = store.create_or_reuse(_make_request(max_attempts=3))
        claim = store.claim("proj-A", job.job_id)
        ok = store.release_claim("proj-A", job.job_id, "wrong-token")
        self.assertFalse(ok)
        rec = store.get("proj-A", job.job_id)
        self.assertEqual(rec.attempt_count, 1)
        self.assertEqual(rec.status, "running")

    def test_late_owner_cannot_alter_count(self) -> None:
        """After a new owner takes over, the old owner's release must fail
        and must not alter attempt_count."""
        store = DurableJobStore(
            Path(self._tmp.name) / "durable.db", lease_seconds=0.15,
        )
        job = store.create_or_reuse(_make_request(max_attempts=3))
        owner1 = store.claim("proj-A", job.job_id)
        time.sleep(0.2)
        owner2 = store.claim("proj-A", job.job_id)
        self.assertTrue(owner2.claimed)
        ok = store.release_claim("proj-A", job.job_id, owner1.claim_token)
        self.assertFalse(ok)
        rec = store.get("proj-A", job.job_id)
        self.assertEqual(rec.attempt_count, 1)


class TestOldSchemaMigration(unittest.TestCase):
    """Old-schema DB (without claim_incremented_attempt) must migrate
    additively and then support correct claim/release."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_old_schema_migrates_preserves_rows(self) -> None:
        """Create a DB with the old schema (no claim_incremented_attempt),
        insert rows, then open with the new code and verify migration."""
        db_path = Path(self._tmp.name) / "durable.db"
        # Create old-schema table manually.
        with sqlite3.connect(str(db_path)) as old_conn:
            old_conn.execute(
                """
                CREATE TABLE durable_mw_jobs (
                    job_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    business_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    claim_token TEXT NOT NULL DEFAULT '',
                    lease_expires_at TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    progress_json TEXT NOT NULL DEFAULT '{}',
                    error_summary TEXT NOT NULL DEFAULT '',
                    input_hash TEXT NOT NULL DEFAULT '',
                    output_hash TEXT NOT NULL DEFAULT '',
                    artifact_locator TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    payload_json TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT '',
                    finished_at TEXT NOT NULL DEFAULT '',
                    cancelled_at TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT 'system'
                )
                """
            )
            old_conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_durable_mw_business
                ON durable_mw_jobs(project_id, job_type, business_key)
                """
            )
            now_iso = "2026-07-22T00:00:00+00:00"
            # Insert a queued job.
            old_conn.execute(
                """
                INSERT INTO durable_mw_jobs (
                    job_id, project_id, job_type, business_key, request_hash,
                    status, attempt_count, max_attempts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', 1, 3, ?, ?)
                """,
                ("mwjob_oldrow_001", "proj-A", "competitor_triage",
                 "bk-old-1", "rh-old-aaa", now_iso, now_iso),
            )
            # Insert a completed job.
            old_conn.execute(
                """
                INSERT INTO durable_mw_jobs (
                    job_id, project_id, job_type, business_key, request_hash,
                    status, attempt_count, max_attempts, created_at, updated_at,
                    finished_at
                ) VALUES (?, ?, ?, ?, ?, 'completed', 2, 3, ?, ?, ?)
                """,
                ("mwjob_oldrow_002", "proj-A", "competitor_triage",
                 "bk-old-2", "rh-old-bbb", now_iso, now_iso, now_iso),
            )
            old_conn.commit()

        # Now open with new code — should auto-migrate.
        store = DurableJobStore(db_path)
        # Verify the column exists.
        with sqlite3.connect(str(db_path)) as check_conn:
            cols = {row[1] for row in check_conn.execute(
                "PRAGMA table_info(durable_mw_jobs)"
            ).fetchall()}
        self.assertIn("claim_incremented_attempt", cols)
        # Verify both rows preserved.
        rec1 = store.get("proj-A", "mwjob_oldrow_001")
        self.assertEqual(rec1.status, "queued")
        self.assertEqual(rec1.attempt_count, 1)
        rec2 = store.get("proj-A", "mwjob_oldrow_002")
        self.assertEqual(rec2.status, "completed")
        self.assertEqual(rec2.attempt_count, 2)
        # Verify claim/release works correctly on migrated data.
        claim = store.claim("proj-A", "mwjob_oldrow_001")
        self.assertTrue(claim.claimed)
        self.assertEqual(store.get("proj-A", "mwjob_oldrow_001").attempt_count, 1)
        store.release_claim("proj-A", "mwjob_oldrow_001", claim.claim_token)
        self.assertEqual(store.get("proj-A", "mwjob_oldrow_001").attempt_count, 1)


if __name__ == "__main__":
    unittest.main()
