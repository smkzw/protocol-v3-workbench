from __future__ import annotations

import io
import json
import multiprocessing
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from services.api.app.sqlite_runtime_store import (
    RuntimeStoreIntegrityError,
    SqliteRuntimeStore,
)
from services.api.app.vlm_gateway import (
    DurableVlmCircuitBreaker,
    LocalVlmGateway,
    VlmCircuitBreakerPolicy,
    VlmCircuitOpenError,
    VlmGatewayConfigurationError,
    VlmGatewayRuntimeError,
    VlmGatewaySettings,
    VlmNormalizationPolicy,
    VlmProfile,
)


START = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, value: datetime = START) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, *, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def circuit_policy(
    *,
    minimum_sample_size: int = 3,
    rolling_window_size: int = 4,
    failure_threshold: float = 2 / 3,
    cooldown_seconds: int = 30,
) -> VlmCircuitBreakerPolicy:
    return VlmCircuitBreakerPolicy(
        minimum_sample_size=minimum_sample_size,
        rolling_window_size=rolling_window_size,
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown_seconds,
    )


def profile(
    *,
    processor_digest: str = "b" * 64,
    policy: VlmCircuitBreakerPolicy | None = None,
) -> VlmProfile:
    return VlmProfile(
        profile_version="synthetic-vlm-profile-v13",
        model="synthetic-vlm-model",
        model_artifact_digest="a" * 64,
        processor="synthetic-processor",
        processor_digest=processor_digest,
        serving_engine="synthetic-engine",
        serving_engine_version="test-only",
        normalization=VlmNormalizationPolicy(
            max_bytes=100_000,
            max_width=64,
            max_height=64,
            max_pixels=4_096,
        ),
        circuit_breaker=policy or circuit_policy(),
        request_timeout_seconds=2,
    )


def image_bytes() -> bytes:
    image = Image.new("RGB", (16, 12), (20, 80, 140))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def completion_bytes() -> bytes:
    descriptor = {
        "schema_version": "eligibility_visual_descriptor_v1",
        "media_class": "document_page",
        "primary_document_type": "medical_record",
        "capture_quality": {
            "overall": "adequate_for_human_qc",
            "flags": ["none"],
        },
        "orientation": "upright",
        "requires_human_attention": ["none"],
    }
    return json.dumps(
        {
            "model": "synthetic-vlm-model",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(descriptor, separators=(",", ":")),
                    },
                }
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def acquire_probe_in_process(
    db_path: str,
    profile_digest: str,
    now_iso: str,
    start_event,
    result_queue,
) -> None:
    store = SqliteRuntimeStore(Path(db_path))
    start_event.wait(timeout=5)
    permit = store.acquire_eligibility_vlm_circuit_permit(
        profile_digest,
        minimum_sample_size=1,
        rolling_window_size=2,
        failure_threshold=1,
        cooldown_seconds=30,
        closed_permit_lease_seconds=32,
        probe_lease_seconds=60,
        now=datetime.fromisoformat(now_iso),
    )
    result_queue.put(bool(permit and permit["half_open_probe"]))


class VlmDurableCircuitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "runtime.sqlite3"
        self.clock = MutableClock()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def breaker(
        self,
        store: SqliteRuntimeStore,
        approved_profile: VlmProfile,
    ) -> DurableVlmCircuitBreaker:
        return DurableVlmCircuitBreaker(
            approved_profile.circuit_breaker,
            profile_digest=approved_profile.profile_digest,
            state_store=store,
            request_timeout_seconds=approved_profile.request_timeout_seconds,
            probe_lease_seconds=60,
            clock=self.clock,
        )

    @staticmethod
    def record(breaker: DurableVlmCircuitBreaker, *, failed: bool) -> None:
        with breaker.call() as call:
            call.complete(failed=failed)

    def gateway(
        self,
        store: SqliteRuntimeStore,
        approved_profile: VlmProfile,
        transport,
    ) -> LocalVlmGateway:
        return LocalVlmGateway(
            VlmGatewaySettings(
                base_url="http://127.0.0.1:8000/v1",
                profile=approved_profile,
                timeout_seconds=2,
            ),
            transport=transport,
            circuit_breaker=self.breaker(store, approved_profile),
        )

    def run_gateway(
        self,
        gateway: LocalVlmGateway,
        approved_profile: VlmProfile,
    ):
        return gateway.run(
            image_bytes=image_bytes(),
            mime_type="image/png",
            expected_profile_digest=approved_profile.profile_digest,
        )

    def downgrade_fixture_to_v12(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_eligibility_vlm_circuit_sample_no_update"
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_eligibility_vlm_circuit_sample_no_delete"
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_eligibility_vlm_circuit_permit_no_update"
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_eligibility_vlm_circuit_permit_no_delete"
            )
            connection.execute("DROP TABLE eligibility_vlm_circuit_samples")
            connection.execute("DROP TABLE eligibility_vlm_circuit_permits")
            connection.execute("DROP TABLE eligibility_vlm_circuit_state")
            connection.execute("DELETE FROM schema_migrations WHERE version >= 13")
            connection.commit()

    def test_rolling_samples_open_per_profile_and_survive_store_reopen(self) -> None:
        approved = profile()
        other = profile(processor_digest="c" * 64)
        first_store = SqliteRuntimeStore(self.db_path)
        first_breaker = self.breaker(first_store, approved)

        for failed in (True, False, True):
            self.record(first_breaker, failed=failed)

        with self.assertRaisesRegex(
            VlmGatewayRuntimeError, "temporarily unavailable"
        ):
            with first_breaker.call():
                pass

        del first_breaker, first_store
        reopened_store = SqliteRuntimeStore(self.db_path)
        reopened_breaker = self.breaker(reopened_store, approved)
        with self.assertRaisesRegex(
            VlmGatewayRuntimeError, "temporarily unavailable"
        ):
            with reopened_breaker.call():
                pass

        self.record(self.breaker(reopened_store, other), failed=False)
        self.assertEqual(
            "open",
            reopened_store.eligibility_vlm_circuit_state(approved.profile_digest)[
                "state"
            ],
        )
        self.assertEqual(
            "closed",
            reopened_store.eligibility_vlm_circuit_state(other.profile_digest)[
                "state"
            ],
        )

    def test_v12_to_v13_migration_preserves_vlm_profile_rows(self) -> None:
        approved = profile()
        store = SqliteRuntimeStore(self.db_path)
        with store._connect() as connection:
            connection.execute(
                """
                INSERT INTO eligibility_vlm_profile_revisions(
                    tenant_id, profile_version, profile_digest,
                    profile_payload_hash, max_attempts_limit, created_at
                ) VALUES ('kangzhe_local', ?, ?, ?, 3, ?)
                """,
                (
                    approved.profile_version,
                    approved.profile_digest,
                    "d" * 64,
                    START.isoformat(),
                ),
            )
        self.downgrade_fixture_to_v12()

        migrated = SqliteRuntimeStore(self.db_path)
        with migrated._connect() as connection:
            version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
            preserved = connection.execute(
                """
                SELECT profile_digest FROM eligibility_vlm_profile_revisions
                WHERE profile_version = ?
                """,
                (approved.profile_version,),
            ).fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertEqual(16, version)
        self.assertEqual(approved.profile_digest, preserved)
        self.assertIn("eligibility_vlm_circuit_state", tables)
        self.assertIn("eligibility_vlm_circuit_permits", tables)
        self.assertIn("eligibility_vlm_circuit_samples", tables)
        self.assertTrue(list(self.db_path.parent.glob("runtime.sqlite3.v12.*.bak")))
        self.assertEqual(16, SqliteRuntimeStore(self.db_path).health_report()["schema_version"])

    def test_v13_rejects_unexpected_preexisting_circuit_schema(self) -> None:
        SqliteRuntimeStore(self.db_path)
        self.downgrade_fixture_to_v12()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "CREATE TABLE eligibility_vlm_circuit_state(unexpected TEXT)"
            )
            connection.commit()
        with self.assertRaisesRegex(
            RuntimeStoreIntegrityError, "unexpected v13 circuit schema"
        ):
            SqliteRuntimeStore(self.db_path)
        with sqlite3.connect(self.db_path) as connection:
            version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
        self.assertEqual(12, version)

    def test_rolling_window_discards_old_failures_before_opening(self) -> None:
        approved = profile(
            policy=circuit_policy(
                minimum_sample_size=3,
                rolling_window_size=3,
                failure_threshold=2 / 3,
            )
        )
        store = SqliteRuntimeStore(self.db_path)
        breaker = self.breaker(store, approved)

        for failed in (True, False, False, True):
            self.record(breaker, failed=failed)
        self.record(breaker, failed=True)

        with self.assertRaisesRegex(
            VlmGatewayRuntimeError, "temporarily unavailable"
        ):
            with breaker.call():
                pass

    def test_closed_permit_outcome_is_idempotent(self) -> None:
        approved = profile()
        store = SqliteRuntimeStore(self.db_path)
        breaker = self.breaker(store, approved)
        permit = breaker._before_call()
        outcome = {
            "generation": permit.generation,
            "half_open_probe": False,
            "permit_token": permit.permit_token,
            "failed": True,
            "now": self.clock(),
        }
        self.assertTrue(
            store.record_eligibility_vlm_circuit_outcome(
                approved.profile_digest, **outcome
            )
        )
        self.assertTrue(
            store.record_eligibility_vlm_circuit_outcome(
                approved.profile_digest, **outcome
            )
        )
        with store._connect() as connection:
            count = connection.execute(
                """
                SELECT COUNT(*) FROM eligibility_vlm_circuit_samples
                WHERE profile_digest = ?
                """,
                (approved.profile_digest,),
            ).fetchone()[0]
        self.assertEqual(1, count)

    def test_evicted_rolling_sample_permit_cannot_be_replayed(self) -> None:
        approved = profile(
            policy=circuit_policy(
                minimum_sample_size=2,
                rolling_window_size=2,
                failure_threshold=0.5,
            )
        )
        store = SqliteRuntimeStore(self.db_path)
        breaker = self.breaker(store, approved)
        first = breaker._before_call()
        breaker._record(first, failed=False)
        self.record(breaker, failed=False)
        self.record(breaker, failed=False)

        self.assertFalse(
            store.record_eligibility_vlm_circuit_outcome(
                approved.profile_digest,
                generation=first.generation,
                half_open_probe=False,
                permit_token=first.permit_token,
                failed=True,
                now=self.clock(),
            )
        )
        self.assertTrue(
            store.record_eligibility_vlm_circuit_outcome(
                approved.profile_digest,
                generation=first.generation,
                half_open_probe=False,
                permit_token=first.permit_token,
                failed=False,
                now=self.clock(),
            )
        )
        self.assertEqual(
            "closed",
            store.eligibility_vlm_circuit_state(approved.profile_digest)["state"],
        )

    def test_naive_and_backward_clock_inputs_fail_closed(self) -> None:
        approved = profile()
        store = SqliteRuntimeStore(self.db_path)
        policy = approved.circuit_breaker
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            store.acquire_eligibility_vlm_circuit_permit(
                approved.profile_digest,
                minimum_sample_size=policy.minimum_sample_size,
                rolling_window_size=policy.rolling_window_size,
                failure_threshold=policy.failure_threshold,
                cooldown_seconds=policy.cooldown_seconds,
                closed_permit_lease_seconds=32,
                probe_lease_seconds=60,
                now=datetime(2026, 7, 12, 8, 0),
            )
        breaker = self.breaker(store, approved)
        permit = breaker._before_call()
        self.clock.value -= timedelta(seconds=1)
        with self.assertRaisesRegex(
            RuntimeStoreIntegrityError, "clock moved backwards"
        ):
            store.record_eligibility_vlm_circuit_outcome(
                approved.profile_digest,
                generation=permit.generation,
                half_open_probe=False,
                permit_token=permit.permit_token,
                failed=False,
                now=self.clock(),
            )
        with self.assertRaisesRegex(
            RuntimeStoreIntegrityError, "clock moved backwards"
        ):
            breaker._before_call()

    def test_forged_closed_permit_token_is_rejected(self) -> None:
        approved = profile()
        store = SqliteRuntimeStore(self.db_path)
        breaker = self.breaker(store, approved)
        permit = breaker._before_call()
        self.assertFalse(
            store.record_eligibility_vlm_circuit_outcome(
                approved.profile_digest,
                generation=permit.generation,
                half_open_probe=False,
                permit_token="forged-permit-token",
                failed=True,
                now=self.clock(),
            )
        )
        with store._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM eligibility_vlm_circuit_samples"
            ).fetchone()[0]
        self.assertEqual(0, count)

    def test_closed_permit_lease_exceeds_request_timeout_with_margin(self) -> None:
        approved = profile()
        store = SqliteRuntimeStore(self.db_path)
        with self.assertRaisesRegex(
            VlmGatewayConfigurationError, "probe lease is invalid"
        ):
            DurableVlmCircuitBreaker(
                approved.circuit_breaker,
                profile_digest=approved.profile_digest,
                state_store=store,
                request_timeout_seconds=approved.request_timeout_seconds,
                probe_lease_seconds=2,
                clock=self.clock,
            )
        breaker = DurableVlmCircuitBreaker(
            approved.circuit_breaker,
            profile_digest=approved.profile_digest,
            state_store=store,
            request_timeout_seconds=approved.request_timeout_seconds,
            clock=self.clock,
        )
        permit = breaker._before_call()
        with store._connect() as connection:
            row = connection.execute(
                """
                SELECT issued_at, expires_at FROM eligibility_vlm_circuit_permits
                WHERE permit_token = ?
                """,
                (permit.permit_token,),
            ).fetchone()
        lease_seconds = (
            datetime.fromisoformat(row["expires_at"])
            - datetime.fromisoformat(row["issued_at"])
        ).total_seconds()
        self.assertEqual(32, lease_seconds)
        self.clock.advance(seconds=3)
        breaker._record(permit, failed=True)
        self.assertEqual(
            "closed",
            store.eligibility_vlm_circuit_state(approved.profile_digest)["state"],
        )

    def test_partial_v13_table_creation_recovers_transactionally(self) -> None:
        SqliteRuntimeStore(self.db_path)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "DROP TRIGGER trg_eligibility_vlm_circuit_sample_no_update"
            )
            connection.execute(
                "DROP TRIGGER trg_eligibility_vlm_circuit_sample_no_delete"
            )
            connection.execute(
                "DROP TRIGGER trg_eligibility_vlm_circuit_permit_no_update"
            )
            connection.execute(
                "DROP TRIGGER trg_eligibility_vlm_circuit_permit_no_delete"
            )
            connection.execute("DROP TABLE eligibility_vlm_circuit_samples")
            connection.execute("DROP TABLE eligibility_vlm_circuit_permits")
            connection.execute("DELETE FROM schema_migrations WHERE version >= 13")
            connection.commit()
        recovered = SqliteRuntimeStore(self.db_path)
        with recovered._connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertEqual(
                16,
                connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0],
            )
        self.assertIn("eligibility_vlm_circuit_permits", tables)
        self.assertIn("eligibility_vlm_circuit_samples", tables)

    def test_two_independent_gateways_admit_exactly_one_half_open_probe(self) -> None:
        approved = profile()
        opening_store = SqliteRuntimeStore(self.db_path)
        opening_breaker = self.breaker(opening_store, approved)
        for _ in range(3):
            self.record(opening_breaker, failed=True)
        self.clock.advance(seconds=31)

        probe_started = threading.Event()
        release_probe = threading.Event()
        first_transport_calls = 0
        second_transport_calls = 0

        def first_transport(request, timeout, limit):
            nonlocal first_transport_calls
            first_transport_calls += 1
            probe_started.set()
            self.assertTrue(release_probe.wait(timeout=2))
            return completion_bytes()

        def second_transport(request, timeout, limit):
            nonlocal second_transport_calls
            second_transport_calls += 1
            return completion_bytes()

        first_gateway = self.gateway(
            SqliteRuntimeStore(self.db_path), approved, first_transport
        )
        second_gateway = self.gateway(
            SqliteRuntimeStore(self.db_path), approved, second_transport
        )
        first_result = []
        first_error = []

        def run_first_probe() -> None:
            try:
                first_result.append(self.run_gateway(first_gateway, approved))
            except Exception as exc:  # pragma: no cover - asserted below
                first_error.append(exc)

        thread = threading.Thread(target=run_first_probe)
        thread.start()
        self.assertTrue(probe_started.wait(timeout=2))
        with self.assertRaisesRegex(
            VlmGatewayRuntimeError, "temporarily unavailable"
        ):
            self.run_gateway(second_gateway, approved)
        release_probe.set()
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual([], first_error)
        self.assertEqual(1, len(first_result))
        self.assertEqual(1, first_transport_calls)
        self.assertEqual(0, second_transport_calls)
        self.assertEqual(
            "closed",
            SqliteRuntimeStore(self.db_path)
            .eligibility_vlm_circuit_state(approved.profile_digest)["state"],
        )

    def test_preadmitted_gateway_call_uses_the_existing_durable_permit(self) -> None:
        approved = profile()
        store = SqliteRuntimeStore(self.db_path)
        transport_calls = 0

        def transport(request, timeout, limit):
            nonlocal transport_calls
            transport_calls += 1
            return completion_bytes()

        gateway = self.gateway(store, approved, transport)
        with gateway.admit() as admission:
            result = gateway.run(
                image_bytes=image_bytes(),
                mime_type="image/png",
                expected_profile_digest=approved.profile_digest,
                circuit_call=admission,
            )
        self.assertEqual("synthetic-vlm-model", result.model)
        self.assertEqual(1, transport_calls)
        with store._connect() as connection:
            permit_count = connection.execute(
                "SELECT COUNT(*) FROM eligibility_vlm_circuit_permits"
            ).fetchone()[0]
            outcome_count = connection.execute(
                "SELECT COUNT(*) FROM eligibility_vlm_circuit_samples"
            ).fetchone()[0]
        self.assertEqual(1, permit_count)
        self.assertEqual(1, outcome_count)

    def test_open_circuit_error_exposes_future_retry_without_transport(self) -> None:
        approved = profile(
            policy=circuit_policy(
                minimum_sample_size=1,
                rolling_window_size=2,
                failure_threshold=1,
            )
        )
        store = SqliteRuntimeStore(self.db_path)
        breaker = self.breaker(store, approved)
        self.record(breaker, failed=True)
        gateway = self.gateway(
            store,
            approved,
            lambda request, timeout, limit: self.fail("transport must not run"),
        )
        with self.assertRaises(VlmCircuitOpenError) as captured:
            with gateway.admit():
                pass
        self.assertEqual(self.clock() + timedelta(seconds=30), captured.exception.retry_at)

    def test_failed_half_open_probe_reopens_for_a_full_cooldown(self) -> None:
        approved = profile()
        store = SqliteRuntimeStore(self.db_path)
        breaker = self.breaker(store, approved)
        for _ in range(3):
            self.record(breaker, failed=True)
        self.clock.advance(seconds=31)

        failing_gateway = self.gateway(
            SqliteRuntimeStore(self.db_path),
            approved,
            lambda request, timeout, limit: (_ for _ in ()).throw(
                TimeoutError("synthetic transport failure")
            ),
        )
        with self.assertRaisesRegex(VlmGatewayRuntimeError, "request failed"):
            self.run_gateway(failing_gateway, approved)

        competing_transport_calls = 0

        def competing_transport(request, timeout, limit):
            nonlocal competing_transport_calls
            competing_transport_calls += 1
            return completion_bytes()

        competing_gateway = self.gateway(
            SqliteRuntimeStore(self.db_path), approved, competing_transport
        )
        with self.assertRaisesRegex(
            VlmGatewayRuntimeError, "temporarily unavailable"
        ):
            self.run_gateway(competing_gateway, approved)
        self.assertEqual(0, competing_transport_calls)

        self.clock.advance(seconds=31)
        self.run_gateway(competing_gateway, approved)
        self.assertEqual(1, competing_transport_calls)
        self.assertEqual(
            "closed",
            store.eligibility_vlm_circuit_state(approved.profile_digest)["state"],
        )

    def test_stale_generation_completion_cannot_close_newly_opened_circuit(self) -> None:
        approved = profile(
            policy=circuit_policy(
                minimum_sample_size=1,
                rolling_window_size=2,
                failure_threshold=1,
            )
        )
        store = SqliteRuntimeStore(self.db_path)
        policy = approved.circuit_breaker
        old_permit = store.acquire_eligibility_vlm_circuit_permit(
            approved.profile_digest,
            minimum_sample_size=policy.minimum_sample_size,
            rolling_window_size=policy.rolling_window_size,
            failure_threshold=policy.failure_threshold,
            cooldown_seconds=policy.cooldown_seconds,
            closed_permit_lease_seconds=32,
            probe_lease_seconds=60,
            now=self.clock(),
        )
        opening_permit = store.acquire_eligibility_vlm_circuit_permit(
            approved.profile_digest,
            minimum_sample_size=policy.minimum_sample_size,
            rolling_window_size=policy.rolling_window_size,
            failure_threshold=policy.failure_threshold,
            cooldown_seconds=policy.cooldown_seconds,
            closed_permit_lease_seconds=32,
            probe_lease_seconds=60,
            now=self.clock(),
        )
        self.assertTrue(
            store.record_eligibility_vlm_circuit_outcome(
                approved.profile_digest,
                **opening_permit,
                failed=True,
                now=self.clock(),
            )
        )

        accepted = store.record_eligibility_vlm_circuit_outcome(
            approved.profile_digest,
            **old_permit,
            failed=False,
            now=self.clock(),
        )

        self.assertFalse(accepted)
        self.assertEqual(
            "open",
            store.eligibility_vlm_circuit_state(approved.profile_digest)["state"],
        )

    def test_stale_half_open_permit_token_is_ignored(self) -> None:
        approved = profile(
            policy=circuit_policy(
                minimum_sample_size=1,
                rolling_window_size=2,
                failure_threshold=1,
            )
        )
        store = SqliteRuntimeStore(self.db_path)
        breaker = self.breaker(store, approved)
        self.record(breaker, failed=True)
        self.clock.advance(seconds=31)
        policy = approved.circuit_breaker
        probe = store.acquire_eligibility_vlm_circuit_permit(
            approved.profile_digest,
            minimum_sample_size=policy.minimum_sample_size,
            rolling_window_size=policy.rolling_window_size,
            failure_threshold=policy.failure_threshold,
            cooldown_seconds=policy.cooldown_seconds,
            closed_permit_lease_seconds=32,
            probe_lease_seconds=60,
            now=self.clock(),
        )
        self.assertTrue(probe["half_open_probe"])

        accepted = store.record_eligibility_vlm_circuit_outcome(
            approved.profile_digest,
            generation=probe["generation"],
            half_open_probe=True,
            permit_token="stale-permit-token",
            failed=False,
            now=self.clock(),
        )

        self.assertFalse(accepted)
        self.assertEqual(
            "half_open",
            store.eligibility_vlm_circuit_state(approved.profile_digest)["state"],
        )
        self.assertTrue(
            store.record_eligibility_vlm_circuit_outcome(
                approved.profile_digest,
                **probe,
                failed=False,
                now=self.clock(),
            )
        )
        self.assertEqual(
            "closed",
            store.eligibility_vlm_circuit_state(approved.profile_digest)["state"],
        )

    def test_abandoned_half_open_probe_is_fenced_and_recoverable(self) -> None:
        approved = profile(
            policy=circuit_policy(
                minimum_sample_size=1,
                rolling_window_size=2,
                failure_threshold=1,
            )
        )
        store = SqliteRuntimeStore(self.db_path)
        breaker = self.breaker(store, approved)
        self.record(breaker, failed=True)
        self.clock.advance(seconds=31)
        abandoned = breaker._before_call()

        self.clock.advance(seconds=61)
        with self.assertRaisesRegex(
            VlmGatewayRuntimeError, "temporarily unavailable"
        ):
            breaker._before_call()

        state = store.eligibility_vlm_circuit_state(approved.profile_digest)
        self.assertEqual("open", state["state"])
        self.assertFalse(
            store.record_eligibility_vlm_circuit_outcome(
                approved.profile_digest,
                generation=abandoned.generation,
                half_open_probe=True,
                permit_token=abandoned.permit_token,
                failed=False,
                now=self.clock(),
            )
        )
        self.clock.advance(seconds=31)
        replacement = breaker._before_call()
        breaker._record(replacement, failed=False)
        self.assertEqual(
            "closed",
            store.eligibility_vlm_circuit_state(approved.profile_digest)["state"],
        )

    def test_expired_probe_completion_is_rejected_without_new_acquisition(self) -> None:
        approved = profile(
            policy=circuit_policy(
                minimum_sample_size=1,
                rolling_window_size=2,
                failure_threshold=1,
            )
        )
        store = SqliteRuntimeStore(self.db_path)
        breaker = self.breaker(store, approved)
        self.record(breaker, failed=True)
        self.clock.advance(seconds=31)
        expired = breaker._before_call()
        self.clock.advance(seconds=61)

        self.assertFalse(
            store.record_eligibility_vlm_circuit_outcome(
                approved.profile_digest,
                generation=expired.generation,
                half_open_probe=True,
                permit_token=expired.permit_token,
                failed=False,
                now=self.clock(),
            )
        )
        self.assertEqual(
            "open",
            store.eligibility_vlm_circuit_state(approved.profile_digest)["state"],
        )

    def test_two_spawned_processes_admit_only_one_half_open_probe(self) -> None:
        approved = profile(
            policy=circuit_policy(
                minimum_sample_size=1,
                rolling_window_size=2,
                failure_threshold=1,
            )
        )
        store = SqliteRuntimeStore(self.db_path)
        breaker = self.breaker(store, approved)
        self.record(breaker, failed=True)
        self.clock.advance(seconds=31)

        context = multiprocessing.get_context("spawn")
        start_event = context.Event()
        result_queue = context.Queue()
        processes = [
            context.Process(
                target=acquire_probe_in_process,
                args=(
                    str(self.db_path),
                    approved.profile_digest,
                    self.clock().isoformat(),
                    start_event,
                    result_queue,
                ),
            )
            for _ in range(2)
        ]
        for process in processes:
            process.start()
        start_event.set()
        results = [result_queue.get(timeout=10) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            self.assertEqual(0, process.exitcode)
        self.assertEqual([False, True], sorted(results))


if __name__ == "__main__":
    unittest.main()
