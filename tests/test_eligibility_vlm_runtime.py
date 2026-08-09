from __future__ import annotations

import hashlib
import io
import sqlite3
import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from packages.contracts.workbench_contracts.models import (
    EligibilityVlmDescriptor,
    EligibilityVlmGatewayOutcome,
)
from services.api.app.eligibility_artifact_store import EligibilityArtifactStore
from services.api.app.eligibility_evidence_worker import EligibilityEvidenceWorker
from services.api.app.sqlite_runtime_store import (
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)
from services.api.app.vlm_gateway import (
    VlmCircuitOpenError,
    VlmGatewayResult,
    VlmGatewayRuntimeError,
)


NOW = datetime(2026, 7, 11, 14, 0, tzinfo=timezone.utc)
PROFILE_VERSION = "vlm-synthetic-v1"
PROFILE_DIGEST = "a" * 64
SECOND_PROFILE_DIGEST = "b" * 64


def synthetic_png(color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (32, 24), color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def descriptor_payload() -> dict:
    return {
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


class FakeVlmGateway:
    uses_durable_circuit = True

    def __init__(
        self, *, profile_digest: str = PROFILE_DIGEST, fail_runtime: bool = False
    ) -> None:
        self.profile_digest = profile_digest
        self.fail_runtime = fail_runtime
        self.settings = SimpleNamespace(
            profile=SimpleNamespace(
                profile_version=PROFILE_VERSION,
                profile_digest=profile_digest,
                normalization=SimpleNamespace(max_bytes=1_000_000),
            )
        )
        self.calls: list[dict] = []

    def run(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        expected_profile_digest: str,
        circuit_call=None,
    ) -> VlmGatewayResult:
        self.calls.append(
            {
                "image_bytes": image_bytes,
                "mime_type": mime_type,
                "expected_profile_digest": expected_profile_digest,
            }
        )
        if expected_profile_digest != self.profile_digest:
            raise AssertionError("worker called a gateway with the wrong profile digest")
        if self.fail_runtime:
            raise VlmGatewayRuntimeError("private synthetic provider detail")
        return VlmGatewayResult(
            descriptor=EligibilityVlmDescriptor.model_validate(descriptor_payload()),
            outcome=EligibilityVlmGatewayOutcome.DESCRIPTOR_VALID,
            model="synthetic-vlm-model",
            profile_version=PROFILE_VERSION,
            profile_digest=self.profile_digest,
            normalized_width=32,
            normalized_height=24,
            called_at=NOW,
            duration_ms=3.5,
        )

    def admit(self):
        return nullcontext(SimpleNamespace())


class OpenCircuitFakeGateway(FakeVlmGateway):
    def __init__(self, clock) -> None:
        super().__init__()
        self.clock = clock

    def admit(self):
        raise VlmCircuitOpenError(self.clock() + timedelta(seconds=1))


class EligibilityVlmRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "runtime.sqlite3"
        self.policy_state: dict[str, dict] = {}

        def policy_resolver(project_id: str, _subject_id: str, _artifact: dict) -> dict:
            return self.policy_state[project_id]

        self.store = SqliteRuntimeStore(
            self.db_path, controlled_artifact_policy_resolver=policy_resolver
        )
        self.artifact_store = EligibilityArtifactStore(root / "artifacts")
        self.projects = {
            "project_alpha": {
                "subject_id": "SYN-A-001",
                "source_id": "source-alpha",
                "source_revision": "source-alpha-r1",
                "subject_source_revision": "subject-alpha-r1",
                "artifact_id": "artifact-alpha",
                "artifact_revision_token": "artifact-alpha-r1",
                "seed_job_id": "seed-alpha",
                "png": synthetic_png((30, 90, 180)),
            },
            "project_beta": {
                "subject_id": "SYN-B-001",
                "source_id": "source-beta",
                "source_revision": "source-beta-r1",
                "subject_source_revision": "subject-beta-r1",
                "artifact_id": "artifact-beta",
                "artifact_revision_token": "artifact-beta-r1",
                "seed_job_id": "seed-beta",
                "png": synthetic_png((180, 90, 30)),
            },
        }
        for project_id in self.projects:
            self._seed_artifact(project_id)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_artifact(self, project_id: str) -> None:
        fixture = self.projects[project_id]
        body = fixture["png"]
        content_hash = hashlib.sha256(body).hexdigest()
        self.store.replace_eligibility_subject_sources(
            project_id,
            fixture["subject_id"],
            fixture["subject_source_revision"],
            [
                {
                    "source_id": fixture["source_id"],
                    "source_revision": fixture["source_revision"],
                    "content_hash": content_hash,
                    "size_bytes": len(body),
                    "media_class": "image",
                }
            ],
            created_at=NOW,
        )
        self.store.create_eligibility_evidence_job(
            {
                "project_id": project_id,
                "subject_id": fixture["subject_id"],
                "job_id": fixture["seed_job_id"],
                "job_kind": "pdf_page_render",
                "profile_version": "pdf-render-200dpi-v1",
                "source_id": fixture["source_id"],
                "source_revision": fixture["source_revision"],
                "subject_source_revision": fixture["subject_source_revision"],
                "cache_key": f"cache-{fixture['seed_job_id']}",
                "max_attempts": 1,
                "created_at": NOW.isoformat(),
            },
            idempotency_key=f"create-{fixture['seed_job_id']}",
            request_fingerprint=f"fingerprint-{fixture['seed_job_id']}",
        )
        storage_key = f"{project_id}/{fixture['artifact_id']}.png"
        stored = self.artifact_store.write(storage_key, body, "image/png")
        self.store.add_eligibility_evidence_artifact(
            {
                "project_id": project_id,
                "subject_id": fixture["subject_id"],
                "job_id": fixture["seed_job_id"],
                "artifact_id": fixture["artifact_id"],
                "artifact_kind": "synthetic_image",
                "storage_key": stored.storage_key,
                "content_hash": stored.content_hash,
                "size_bytes": stored.size_bytes,
                "media_type": stored.media_type,
                "source_id": fixture["source_id"],
                "source_revision": fixture["source_revision"],
                "extraction_revision": "synthetic-extraction-r1",
                "locator": {"fixture": "generated"},
                "quality_state": "needs_visual_qc",
                "created_at": NOW.isoformat(),
            }
        )

    def _register_profile(self, digest: str = PROFILE_DIGEST) -> dict:
        return self.store.register_eligibility_vlm_profile(
            PROFILE_VERSION,
            digest,
            status="approved",
            created_at=NOW,
        )

    def _register_artifact(
        self,
        project_id: str,
        *,
        authorization_state: str = "authorized",
        artifact_revision_token: str | None = None,
        governance_revision: int | None = 1,
    ) -> dict:
        fixture = self.projects[project_id]
        self.policy_state[project_id] = {
            "data_class": "synthetic_fixture",
            "authorization_ref": f"authorization-{project_id}",
            "authorization_state": authorization_state,
            "retention_policy_id": "synthetic-fixture-ephemeral-v1",
            "legal_hold": False,
        }
        derived_token = self.store.eligibility_controlled_artifact_revision_token(
            project_id, fixture["artifact_id"]
        )
        fixture["artifact_revision_token"] = derived_token
        return self.store.register_eligibility_controlled_artifact(
            project_id=project_id,
            subject_id=fixture["subject_id"],
            artifact_id=fixture["artifact_id"],
            data_class="synthetic_fixture",
            authorization_ref=f"authorization-{project_id}",
            authorization_state=authorization_state,
            retention_policy_id="synthetic-fixture-ephemeral-v1",
            artifact_revision_token=(
                artifact_revision_token or derived_token
            ),
            governance_revision=governance_revision,
            created_at=NOW,
        )

    def _vlm_job(self, project_id: str, *, job_id: str | None = None) -> dict:
        fixture = self.projects[project_id]
        job_id = job_id or f"vlm-{project_id}"
        return {
            "project_id": project_id,
            "subject_id": fixture["subject_id"],
            "job_id": job_id,
            "job_kind": "vlm",
            "profile_version": PROFILE_VERSION,
            "profile_digest": PROFILE_DIGEST,
            "source_id": fixture["source_id"],
            "source_revision": fixture["source_revision"],
            "subject_source_revision": fixture["subject_source_revision"],
            "cache_key": f"cache-{job_id}",
            "max_attempts": 3,
            "input_artifact_id": fixture["artifact_id"],
            "artifact_id": fixture["artifact_id"],
            "artifact_revision_token": fixture["artifact_revision_token"],
            "governance_revision": 1,
            "created_at": NOW.isoformat(),
        }

    def _create_bound_job(self, project_id: str, *, job_id: str | None = None) -> dict:
        job = self._vlm_job(project_id, job_id=job_id)
        return self.store.create_eligibility_vlm_bound_job(
            job,
            idempotency_key=f"create-{job['job_id']}",
            request_fingerprint=f"fingerprint-{job['job_id']}",
        )

    def _worker(self, gateway: FakeVlmGateway) -> EligibilityEvidenceWorker:
        def reject_path_resolution(_job):
            raise AssertionError("VLM worker must not resolve a source path")

        return EligibilityEvidenceWorker(
            store=self.store,
            artifact_store=self.artifact_store,
            source_resolver=reject_path_resolution,
            vlm_gateway=gateway,
            profile_version=PROFILE_VERSION,
            clock=lambda: NOW,
        )

    def _prepare_bound_job(self, project_id: str) -> dict:
        self._register_profile()
        self._register_artifact(project_id)
        return self._create_bound_job(project_id)

    def test_bound_job_rejects_missing_profile_artifact_or_governance(self) -> None:
        self._register_artifact("project_alpha")
        with self.assertRaises(ValueError):
            self._create_bound_job("project_alpha", job_id="vlm-missing-profile")

        self._register_profile()
        missing_artifact = self._vlm_job(
            "project_alpha", job_id="vlm-missing-artifact"
        )
        missing_artifact["artifact_id"] = "artifact-does-not-exist"
        missing_artifact["input_artifact_id"] = "artifact-does-not-exist"
        with self.assertRaises(ValueError):
            self.store.create_eligibility_vlm_bound_job(
                missing_artifact,
                idempotency_key="create-vlm-missing-artifact",
                request_fingerprint="fingerprint-vlm-missing-artifact",
            )

        with self.assertRaises(ValueError):
            self._create_bound_job("project_beta", job_id="vlm-missing-governance")

    def test_worker_rejects_gateway_without_durable_circuit(self) -> None:
        gateway = FakeVlmGateway()
        gateway.uses_durable_circuit = False
        with self.assertRaisesRegex(ValueError, "durable circuit breaker"):
            self._worker(gateway)

    def test_open_circuit_defers_without_consuming_provider_attempts(self) -> None:
        self._prepare_bound_job("project_alpha")
        current = [NOW]
        gateway = OpenCircuitFakeGateway(lambda: current[0])

        def reject_path_resolution(_job):
            raise AssertionError("open circuit must not read a controlled artifact")

        worker = EligibilityEvidenceWorker(
            store=self.store,
            artifact_store=self.artifact_store,
            source_resolver=reject_path_resolution,
            vlm_gateway=gateway,
            profile_version=PROFILE_VERSION,
            clock=lambda: current[0],
        )
        for attempt in range(1, 6):
            result = worker.run_once("circuit-worker")
            self.assertEqual("retry_wait", result["status"])
            self.assertEqual(attempt, result["attempt_count"])
            self.assertEqual(0, result["provider_attempt_count"])
            current[0] += timedelta(seconds=1)
        self.assertEqual([], gateway.calls)
        self.assertEqual(
            [], self.store.eligibility_vlm_audit_events(
                "project_alpha", result["job_id"]
            )
        )

    def test_f19_provider_retry_exhaustion_is_bounded_without_descriptor(self) -> None:
        self._prepare_bound_job("project_alpha")
        current = [NOW]
        gateway = FakeVlmGateway(fail_runtime=True)

        def reject_path_resolution(_job):
            raise AssertionError("VLM worker must use the controlled artifact store")

        worker = EligibilityEvidenceWorker(
            store=self.store,
            artifact_store=self.artifact_store,
            source_resolver=reject_path_resolution,
            vlm_gateway=gateway,
            profile_version=PROFILE_VERSION,
            clock=lambda: current[0],
        )
        for provider_attempt in range(1, 4):
            result = worker.run_once("retry-worker")
            self.assertEqual(provider_attempt, result["provider_attempt_count"])
            self.assertEqual(
                "retry_wait" if provider_attempt < 3 else "failed",
                result["status"],
            )
            current[0] += timedelta(minutes=1)
        self.assertIsNone(worker.run_once("retry-worker"))
        self.assertEqual(3, len(gateway.calls))
        self.assertEqual(
            [], self.store.eligibility_vlm_descriptors(
                "project_alpha", result["job_id"]
            ),
        )
        self.assertEqual(
            3,
            len(self.store.eligibility_vlm_audit_events(
                "project_alpha", result["job_id"]
            )),
        )

    def test_controlled_artifact_governance_cannot_be_caller_spoofed(self) -> None:
        fixture = self.projects["project_alpha"]
        self.policy_state["project_alpha"] = {
            "data_class": "synthetic_fixture",
            "authorization_ref": "authorization-project_alpha",
            "authorization_state": "authorized",
            "retention_policy_id": "synthetic-fixture-ephemeral-v1",
            "legal_hold": False,
        }
        token = self.store.eligibility_controlled_artifact_revision_token(
            "project_alpha", fixture["artifact_id"]
        )
        with self.assertRaisesRegex(ValueError, "server-authoritative"):
            self.store.register_eligibility_controlled_artifact(
                project_id="project_alpha",
                subject_id=fixture["subject_id"],
                artifact_id=fixture["artifact_id"],
                data_class="clinical_restricted",
                authorization_ref="authorization-project_alpha",
                authorization_state="authorized",
                retention_policy_id="unknown-retention-policy",
                artifact_revision_token=token,
                governance_revision=1,
                created_at=NOW,
            )

    def test_cross_project_artifact_binding_is_rejected(self) -> None:
        self._register_profile()
        self._register_artifact("project_alpha")
        job = self._vlm_job("project_beta", job_id="vlm-cross-project")
        job["artifact_id"] = self.projects["project_alpha"]["artifact_id"]
        job["input_artifact_id"] = job["artifact_id"]
        job["artifact_revision_token"] = self.projects["project_alpha"][
            "artifact_revision_token"
        ]
        with self.assertRaises(ValueError):
            self.store.create_eligibility_vlm_bound_job(
                job,
                idempotency_key="create-vlm-cross-project",
                request_fingerprint="fingerprint-vlm-cross-project",
            )

    def test_exact_profile_digest_is_required_at_binding_and_inference(self) -> None:
        self._register_profile()
        self._register_artifact("project_alpha")
        wrong = self._vlm_job("project_alpha", job_id="vlm-wrong-digest")
        wrong["profile_digest"] = SECOND_PROFILE_DIGEST
        with self.assertRaises(ValueError):
            self.store.create_eligibility_vlm_bound_job(
                wrong,
                idempotency_key="create-vlm-wrong-digest",
                request_fingerprint="fingerprint-vlm-wrong-digest",
            )

        self._create_bound_job("project_alpha", job_id="vlm-digest-drift")
        self.store.register_eligibility_vlm_profile(
            PROFILE_VERSION,
            SECOND_PROFILE_DIGEST,
            status="approved",
            created_at=NOW + timedelta(seconds=1),
        )
        gateway = FakeVlmGateway()
        result = self._worker(gateway).run_once("vlm-worker")
        self.assertIsNone(result)
        self.assertEqual([], gateway.calls)

    def test_profile_digest_payload_collision_and_attempt_limit_are_rejected(self) -> None:
        self.store.register_eligibility_vlm_profile(
            PROFILE_VERSION,
            PROFILE_DIGEST,
            profile_payload_hash="c" * 64,
            max_attempts_limit=3,
            created_at=NOW,
        )
        with self.assertRaisesRegex(Exception, "different payload"):
            self.store.register_eligibility_vlm_profile(
                PROFILE_VERSION,
                PROFILE_DIGEST,
                profile_payload_hash="d" * 64,
                max_attempts_limit=3,
                created_at=NOW + timedelta(seconds=1),
            )
        self._register_artifact("project_alpha")
        job = self._vlm_job("project_alpha", job_id="vlm-too-many-attempts")
        job["max_attempts"] = 4
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self.store.create_eligibility_vlm_bound_job(
                job,
                idempotency_key="create-vlm-too-many-attempts",
                request_fingerprint="fingerprint-vlm-too-many-attempts",
            )

    def test_bound_artifact_source_must_match_job_source(self) -> None:
        fixture = self.projects["project_alpha"]
        second_source_id = "source-alpha-second"
        self.store.replace_eligibility_subject_sources(
            "project_alpha",
            fixture["subject_id"],
            "subject-alpha-r2",
            [
                {
                    "source_id": fixture["source_id"],
                    "source_revision": fixture["source_revision"],
                    "content_hash": hashlib.sha256(fixture["png"]).hexdigest(),
                    "size_bytes": len(fixture["png"]),
                    "media_class": "image",
                },
                {
                    "source_id": second_source_id,
                    "source_revision": fixture["source_revision"],
                    "content_hash": "e" * 64,
                    "size_bytes": 1,
                    "media_class": "image",
                },
            ],
            created_at=NOW + timedelta(seconds=1),
        )
        self._register_profile()
        self._register_artifact("project_alpha")
        job = self._vlm_job("project_alpha", job_id="vlm-wrong-source")
        job["source_id"] = second_source_id
        job["subject_source_revision"] = "subject-alpha-r2"
        with self.assertRaisesRegex(ValueError, "source does not match"):
            self.store.create_eligibility_vlm_bound_job(
                job,
                idempotency_key="create-vlm-wrong-source",
                request_fingerprint="fingerprint-vlm-wrong-source",
            )

    def test_source_revision_drift_blocks_gateway_before_byte_read(self) -> None:
        self._prepare_bound_job("project_alpha")
        fixture = self.projects["project_alpha"]
        self.store.replace_eligibility_subject_sources(
            "project_alpha",
            fixture["subject_id"],
            "subject-alpha-r2",
            [
                {
                    "source_id": fixture["source_id"],
                    "source_revision": "source-alpha-r2",
                    "content_hash": "c" * 64,
                    "size_bytes": 1,
                    "media_class": "image",
                }
            ],
            created_at=NOW + timedelta(seconds=1),
        )
        gateway = FakeVlmGateway()
        result = self._worker(gateway).run_once("vlm-worker")
        self.assertIsNone(result)
        self.assertEqual([], gateway.calls)

    def test_artifact_revision_drift_blocks_gateway(self) -> None:
        self._prepare_bound_job("project_alpha")
        self._register_artifact(
            "project_alpha",
            governance_revision=2,
        )
        gateway = FakeVlmGateway()
        result = self._worker(gateway).run_once("vlm-worker")
        self.assertIsNone(result)
        self.assertEqual([], gateway.calls)

    def test_governance_drift_blocks_gateway(self) -> None:
        self._prepare_bound_job("project_alpha")
        self._register_artifact(
            "project_alpha",
            authorization_state="denied",
            governance_revision=2,
        )
        gateway = FakeVlmGateway()
        result = self._worker(gateway).run_once("vlm-worker")
        self.assertIsNone(result)
        self.assertEqual([], gateway.calls)

    def test_generic_completion_rejects_vlm_jobs(self) -> None:
        self._prepare_bound_job("project_alpha")
        claimed = self.store.claim_next_eligibility_evidence_job(
            "vlm-worker",
            now=NOW,
            job_kind="vlm",
            profile_version=PROFILE_VERSION,
        )
        self.assertIsNotNone(claimed)
        with self.assertRaises(ValueError):
            self.store.complete_eligibility_evidence_job(
                "project_alpha",
                claimed["job_id"],
                worker_id="vlm-worker",
                now=NOW,
            )

    def test_worker_success_uses_controlled_bytes_and_creates_no_medical_evidence(self) -> None:
        self._prepare_bound_job("project_alpha")
        gateway = FakeVlmGateway()
        result = self._worker(gateway).run_once("vlm-worker")

        self.assertEqual("succeeded", result["status"])
        self.assertEqual(1, len(gateway.calls))
        self.assertEqual(self.projects["project_alpha"]["png"], gateway.calls[0]["image_bytes"])
        descriptors = self.store.eligibility_vlm_descriptors(
            "project_alpha", result["job_id"]
        )
        audits = self.store.eligibility_vlm_audit_events(
            "project_alpha", result["job_id"]
        )
        self.assertEqual(1, len(descriptors))
        self.assertEqual(1, len(audits))
        self.assertEqual("not_reviewed", descriptors[0]["visual_qc_status"])
        self.assertEqual(
            [],
            self.store.eligibility_subject_evidence_spans(
                "project_alpha", self.projects["project_alpha"]["subject_id"]
            ),
        )

    def test_runtime_failure_is_atomically_audited_without_provider_detail(self) -> None:
        self._prepare_bound_job("project_alpha")
        result = self._worker(FakeVlmGateway(fail_runtime=True)).run_once(
            "vlm-worker"
        )
        self.assertEqual("retry_wait", result["status"])
        self.assertEqual("vlm_runtime_failure", result["error_code"])
        audits = self.store.eligibility_vlm_audit_events(
            "project_alpha", result["job_id"]
        )
        self.assertEqual(1, len(audits))
        self.assertEqual("runtime_failed", audits[0]["gateway_outcome"])
        self.assertEqual("vlm_runtime_failure", audits[0]["error_code"])
        self.assertNotIn("private", repr(audits).lower())
        self.assertEqual(
            [], self.store.eligibility_vlm_descriptors(
                "project_alpha", result["job_id"]
            )
        )

    def test_finalize_is_atomic_and_descriptor_and_audit_are_immutable(self) -> None:
        created = self._prepare_bound_job("project_alpha")
        job_id = created["job"]["job_id"]
        claimed = self.store.claim_next_eligibility_evidence_job(
            "vlm-worker",
            now=NOW,
            job_kind="vlm",
            profile_version=PROFILE_VERSION,
        )
        finalized = self.store.finalize_eligibility_vlm_job(
            "project_alpha",
            job_id,
            worker_id="vlm-worker",
            descriptor=descriptor_payload(),
            outcome="descriptor_valid",
            profile_digest=PROFILE_DIGEST,
            normalized_width=32,
            normalized_height=24,
            duration_ms=3.5,
            attempt_number=claimed["attempt_count"],
            lease_token=claimed["lease_token"],
            now=NOW,
        )
        self.assertEqual("succeeded", finalized["status"])
        descriptors = self.store.eligibility_vlm_descriptors("project_alpha", job_id)
        audits = self.store.eligibility_vlm_audit_events("project_alpha", job_id)
        self.assertEqual(1, len(descriptors))
        self.assertEqual(1, len(audits))

        with sqlite3.connect(self.db_path) as connection:
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    "UPDATE eligibility_vlm_descriptor_records SET orientation='rotated'"
                )
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute("DELETE FROM eligibility_vlm_audit_events")

    def test_stale_lease_rolls_back_descriptor_audit_and_job_completion(self) -> None:
        created = self._prepare_bound_job("project_alpha")
        job_id = created["job"]["job_id"]
        claimed = self.store.claim_next_eligibility_evidence_job(
            "vlm-worker",
            now=NOW,
            lease_seconds=1,
            job_kind="vlm",
            profile_version=PROFILE_VERSION,
        )
        with self.assertRaises(StaleRuntimeStateError):
            self.store.finalize_eligibility_vlm_job(
                "project_alpha",
                job_id,
                worker_id="vlm-worker",
                descriptor=descriptor_payload(),
                outcome="descriptor_valid",
                profile_digest=PROFILE_DIGEST,
                normalized_width=32,
                normalized_height=24,
                duration_ms=3.5,
                attempt_number=claimed["attempt_count"],
                lease_token=claimed["lease_token"],
                now=NOW + timedelta(seconds=2),
            )
        self.assertEqual([], self.store.eligibility_vlm_descriptors("project_alpha", job_id))
        self.assertEqual([], self.store.eligibility_vlm_audit_events("project_alpha", job_id))
        self.assertEqual("running", self.store.eligibility_evidence_job("project_alpha", job_id)["status"])

    def test_old_attempt_token_cannot_finalize_new_same_worker_lease(self) -> None:
        created = self._prepare_bound_job("project_alpha")
        job_id = created["job"]["job_id"]
        first = self.store.claim_next_eligibility_evidence_job(
            "reused-worker", now=NOW, lease_seconds=1,
            job_kind="vlm", profile_version=PROFILE_VERSION,
        )
        second = self.store.claim_next_eligibility_evidence_job(
            "reused-worker", now=NOW + timedelta(seconds=2), lease_seconds=300,
            job_kind="vlm", profile_version=PROFILE_VERSION,
        )
        self.assertNotEqual(first["lease_token"], second["lease_token"])
        with self.assertRaises(StaleRuntimeStateError):
            self.store.finalize_eligibility_vlm_job(
                "project_alpha", job_id, worker_id="reused-worker",
                descriptor=descriptor_payload(), outcome="descriptor_valid",
                profile_digest=PROFILE_DIGEST, normalized_width=32,
                normalized_height=24, duration_ms=3.5,
                attempt_number=first["attempt_count"],
                lease_token=first["lease_token"],
                now=NOW + timedelta(seconds=2),
            )
        finalized = self.store.finalize_eligibility_vlm_job(
            "project_alpha", job_id, worker_id="reused-worker",
            descriptor=descriptor_payload(), outcome="descriptor_valid",
            profile_digest=PROFILE_DIGEST, normalized_width=32,
            normalized_height=24, duration_ms=3.5,
            attempt_number=second["attempt_count"],
            lease_token=second["lease_token"],
            now=NOW + timedelta(seconds=2),
        )
        self.assertEqual("succeeded", finalized["status"])

    def test_untyped_worker_cannot_claim_bound_vlm_job(self) -> None:
        self._prepare_bound_job("project_alpha")
        generic = self.store.claim_next_eligibility_evidence_job(
            "generic-worker", now=NOW
        )
        self.assertIsNotNone(generic)
        self.assertNotEqual("vlm", generic["job_kind"])
        claimed = self.store.claim_next_eligibility_evidence_job(
            "vlm-worker", now=NOW, job_kind="vlm",
            profile_version=PROFILE_VERSION, profile_digest=PROFILE_DIGEST,
        )
        self.assertIsNotNone(claimed)

    def test_public_descriptor_and_audit_exclude_raw_or_storage_details(self) -> None:
        self._prepare_bound_job("project_alpha")
        result = self._worker(FakeVlmGateway()).run_once("vlm-worker")
        payloads = [
            *self.store.eligibility_vlm_descriptors("project_alpha", result["job_id"]),
            *self.store.eligibility_vlm_audit_events("project_alpha", result["job_id"]),
        ]
        serialized = repr(payloads).lower()
        for forbidden in (
            "raw_response",
            "image_bytes",
            "source_path",
            "storage_key",
            "content_hash",
            str(self.artifact_store._root).lower(),
        ):
            self.assertNotIn(forbidden, serialized)

    def test_two_synthetic_projects_are_strictly_isolated(self) -> None:
        self._register_profile()
        for project_id in self.projects:
            self._register_artifact(project_id)
            self._create_bound_job(project_id)

        for project_id in self.projects:
            result = self._worker(FakeVlmGateway()).run_once(
                f"vlm-worker-{project_id}"
            )
            self.assertEqual("succeeded", result["status"])

        alpha_job = "vlm-project_alpha"
        beta_job = "vlm-project_beta"
        self.assertEqual(1, len(self.store.eligibility_vlm_descriptors("project_alpha", alpha_job)))
        self.assertEqual(1, len(self.store.eligibility_vlm_descriptors("project_beta", beta_job)))
        self.assertEqual([], self.store.eligibility_vlm_descriptors("project_alpha", beta_job))
        self.assertEqual([], self.store.eligibility_vlm_audit_events("project_beta", alpha_job))

    def test_legacy_unconfigured_vlm_path_remains_fail_closed(self) -> None:
        fixture = self.projects["project_alpha"]
        legacy_job = {
            "project_id": "project_alpha",
            "subject_id": fixture["subject_id"],
            "job_id": "legacy-vlm-unconfigured",
            "job_kind": "vlm",
            "profile_version": "vlm-minimax-v1",
            "source_id": fixture["source_id"],
            "source_revision": fixture["source_revision"],
            "subject_source_revision": fixture["subject_source_revision"],
            "cache_key": "cache-legacy-vlm-unconfigured",
            "max_attempts": 1,
            "created_at": NOW.isoformat(),
        }
        try:
            self.store.create_eligibility_evidence_job(
                legacy_job,
                idempotency_key="create-legacy-vlm-unconfigured",
                request_fingerprint="fingerprint-legacy-vlm-unconfigured",
            )
        except ValueError:
            return

        worker = EligibilityEvidenceWorker(
            store=self.store,
            artifact_store=self.artifact_store,
            source_resolver=lambda _job: Path("must-not-be-read.png"),
            clock=lambda: NOW,
        )
        result = worker.run_once("legacy-worker")
        self.assertEqual("failed", result["status"])
        self.assertEqual("vlm_gateway_not_configured", result["error_code"])
        self.assertEqual(
            [],
            self.store.eligibility_evidence_artifacts(
                "project_alpha", "legacy-vlm-unconfigured"
            ),
        )


if __name__ == "__main__":
    unittest.main()
