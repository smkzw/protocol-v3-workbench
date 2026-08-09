from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from packages.contracts.workbench_contracts import AiTaskSourceRef
from services.api.app.eligibility_ai_packet import (
    EligibilityAiCurrentContext,
    EligibilityAiPacketBuilder,
)
from services.api.app.eligibility_ai_review import EligibilityAiCriterion
from services.api.app.eligibility_artifact_store import (
    ArtifactIntegrityError,
    EligibilityArtifactStore,
)
from services.api.app.eligibility_protocol_rules import eligibility_criterion_text_hash
from services.api.app.eligibility_review_workflow import CriterionKind
from services.api.app.ocr_gateway import ocr_profile_digest
from services.api.app.sqlite_runtime_store import (
    RuntimeStoreIntegrityError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


PROJECT_ID = "proj_eligibility_ai_packet"
SUBJECT_ID = "SUBJECT-001"
SUBJECT_TOKEN = "subject-token-001"
RULE_REVISION = "rule-revision-001"
SUBJECT_SOURCE_REVISION = "subject-source-revision-001"
SOURCE_ID = "source-001"
SOURCE_REVISION = "source-revision-001"
EXTRACTION_REVISION = "extraction-revision-001"
EVIDENCE_ID = "evidence-001"
ARTIFACT_ID = "artifact-001"
JOB_ID = "job-001"


class EligibilityAiPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def _fixture(
        self,
        name: str,
        *,
        text: str = "The subject has no documented diabetes mellitus.",
        schema_version: str = "eligibility_ocr_artifact_v1",
        rule_revision: str = RULE_REVISION,
        extraction_revision: str = EXTRACTION_REVISION,
        payload_extraction_revision: str | None = None,
        qc_result: str = "sampled_pass",
        artifact_source_id: str = SOURCE_ID,
        artifact_source_revision: str = SOURCE_REVISION,
        add_unprocessed_source: bool = False,
        add_unresolved_span: bool = False,
    ) -> dict[str, object]:
        fixture_root = self.root / name
        store = SqliteRuntimeStore(fixture_root / "runtime.sqlite3")
        artifact_store = EligibilityArtifactStore(fixture_root / "artifacts")
        criterion = EligibilityAiCriterion(
            criterion_uid="in-001",
            criterion_kind=CriterionKind.INCLUSION,
            text="No documented diabetes mellitus.",
            source_locator="protocol:section:5.1:criterion:1",
            display_order=1,
        )
        store.replace_eligibility_rule_revision(
            PROJECT_ID,
            rule_revision,
            [
                {
                    "criterion_uid": criterion.criterion_uid,
                    "criterion_kind": criterion.criterion_kind.value,
                    "source_rule_label": "I1",
                    "source_locator": {"locator": criterion.source_locator},
                    "normalized_text_hash": eligibility_criterion_text_hash(
                        criterion.text
                    ),
                    "display_order": criterion.display_order,
                }
            ],
        )
        sources = [
            {
                "source_id": SOURCE_ID,
                "source_revision": SOURCE_REVISION,
                "content_hash": "1" * 64,
                "size_bytes": 512,
                "media_class": "image",
                "processing_unit_kind": "image",
                "expected_unit_count": 1,
            }
        ]
        if artifact_source_id != SOURCE_ID:
            sources.append(
                {
                    "source_id": artifact_source_id,
                    "source_revision": artifact_source_revision,
                    "content_hash": "2" * 64,
                    "size_bytes": 512,
                    "media_class": "image",
                    "processing_unit_kind": "image",
                    "expected_unit_count": 1,
                }
            )
        if add_unprocessed_source:
            sources.append(
                {
                    "source_id": "source-unprocessed",
                    "source_revision": "source-unprocessed-revision",
                    "content_hash": "4" * 64,
                    "size_bytes": 1024,
                    "media_class": "pdf",
                    "processing_unit_kind": "page",
                    "expected_unit_count": 1,
                }
            )
        store.replace_eligibility_subject_sources(
            PROJECT_ID,
            SUBJECT_ID,
            SUBJECT_SOURCE_REVISION,
            sources,
        )
        store.create_eligibility_evidence_job(
            {
                "project_id": PROJECT_ID,
                "subject_id": SUBJECT_ID,
                "job_id": JOB_ID,
                "job_kind": "ocr",
                "profile_version": "ocr-glm-v1",
                "profile_digest": ocr_profile_digest("ocr-glm-v1"),
                "source_id": SOURCE_ID,
                "source_revision": SOURCE_REVISION,
                "subject_source_revision": SUBJECT_SOURCE_REVISION,
                "cache_key": f"cache-{name}",
                "max_attempts": 3,
            },
            idempotency_key=f"create-{name}",
            request_fingerprint=f"fingerprint-{name}",
        )

        artifact_payload = {
            "schema_version": schema_version,
            "extraction_revision": (
                payload_extraction_revision or extraction_revision
            ),
            "text": text,
        }
        artifact_body = json.dumps(
            artifact_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        storage_key = f"{PROJECT_ID}/{SUBJECT_ID}/{JOB_ID}/{name}.json"
        artifact = artifact_store.write(
            storage_key,
            artifact_body,
            "application/json",
        )
        store.add_eligibility_evidence_artifact(
            {
                "project_id": PROJECT_ID,
                "subject_id": SUBJECT_ID,
                "job_id": JOB_ID,
                "artifact_id": ARTIFACT_ID,
                "artifact_kind": "ocr_text",
                "storage_key": artifact.storage_key,
                "content_hash": artifact.content_hash,
                "size_bytes": artifact.size_bytes,
                "media_type": artifact.media_type,
                "source_id": artifact_source_id,
                "source_revision": artifact_source_revision,
                "extraction_revision": extraction_revision,
                "locator": {"page": 1},
                "quality_state": "sampled_pass",
            }
        )
        store.add_eligibility_evidence_span(
            {
                "project_id": PROJECT_ID,
                "subject_id": SUBJECT_ID,
                "evidence_id": EVIDENCE_ID,
                "source_id": SOURCE_ID,
                "source_revision": SOURCE_REVISION,
                "extraction_revision": extraction_revision,
                "locator": {"page": 1, "region": [10, 20, 300, 80]},
                "metadata": {"artifact_id": ARTIFACT_ID},
                "media_class": "image",
                "processing_state": "completed",
                "quality_state": "sampled_pass",
                "extraction_confidence": 0.98,
                "medical_verification_status": "not_reviewed",
            }
        )
        store.commit_eligibility_evidence_visual_qc(
            project_id=PROJECT_ID,
            subject_id=SUBJECT_ID,
            evidence_id=EVIDENCE_ID,
            expected_qc_revision=0,
            expected_source_revision=SOURCE_REVISION,
            expected_extraction_revision=extraction_revision,
            idempotency_key=f"qc-{name}",
            result=qc_result,
            reason_code="fixture_visual_comparison",
            user_reason="The source image and extracted text were compared.",
            sample_plan_id="full-page-v1",
            sample_unit={"page": 1, "region": [10, 20, 300, 80]},
            policy_version="visual-qc-policy-v1",
            actor="test_qc_reviewer",
        )
        if qc_result == "sampled_pass" and artifact_source_id == SOURCE_ID:
            claimed = store.claim_next_eligibility_evidence_job(
                "fixture-worker",
                job_kind="ocr",
                profile_version="ocr-glm-v1",
                profile_digest=ocr_profile_digest("ocr-glm-v1"),
            )
            self.assertIsNotNone(claimed)
            store.complete_eligibility_evidence_job(
                PROJECT_ID,
                JOB_ID,
                worker_id="fixture-worker",
            )
            store.commit_eligibility_source_processing_unit(
                project_id=PROJECT_ID,
                subject_id=SUBJECT_ID,
                source_id=SOURCE_ID,
                source_revision=SOURCE_REVISION,
                subject_source_revision=SUBJECT_SOURCE_REVISION,
                unit_index=1,
                expected_state_revision=0,
                processing_status="evidence_extracted",
                artifact_id=ARTIFACT_ID,
                extraction_revision=extraction_revision,
                evidence_ids=[EVIDENCE_ID],
                reason_code="fixture_full_unit_processed",
                actor="test_worker",
                idempotency_key=f"unit-{name}",
            )
        if add_unresolved_span:
            store.add_eligibility_evidence_span(
                {
                    "project_id": PROJECT_ID,
                    "subject_id": SUBJECT_ID,
                    "evidence_id": "evidence-unresolved",
                    "source_id": SOURCE_ID,
                    "source_revision": SOURCE_REVISION,
                    "extraction_revision": "extraction-unresolved",
                    "locator": {"page": 2},
                    "metadata": {"artifact_id": ARTIFACT_ID},
                    "media_class": "image",
                    "processing_state": "needs_visual_qc",
                    "quality_state": "needs_visual_qc",
                    "extraction_confidence": None,
                    "medical_verification_status": "not_reviewed",
                }
            )

        context = EligibilityAiCurrentContext(
            project_id=PROJECT_ID,
            subject_id=SUBJECT_ID,
            subject_token=SUBJECT_TOKEN,
            rule_revision=rule_revision,
            subject_source_revision=SUBJECT_SOURCE_REVISION,
            criteria=(criterion,),
        )
        builder = EligibilityAiPacketBuilder(
            store,
            artifact_store,
            lambda project_id, subject_id: context,
        )
        return {
            "store": store,
            "artifact_store": artifact_store,
            "artifact": artifact,
            "artifact_path": fixture_root / "artifacts" / storage_key,
            "builder": builder,
            "criterion": criterion,
            "text": text,
        }

    def test_builds_packet_from_current_qc_passed_ocr_artifact(self) -> None:
        fixture = self._fixture("valid-ocr")

        packet = fixture["builder"].build(PROJECT_ID, SUBJECT_ID)

        self.assertEqual(PROJECT_ID, packet.project_id)
        self.assertEqual(SUBJECT_ID, packet.subject_id)
        self.assertEqual(SUBJECT_TOKEN, packet.subject_token)
        self.assertEqual(RULE_REVISION, packet.rule_revision)
        self.assertEqual(SUBJECT_SOURCE_REVISION, packet.subject_source_revision)
        self.assertEqual((fixture["criterion"],), packet.criteria)
        self.assertEqual(1, len(packet.evidence_sources))
        self.assertEqual(EVIDENCE_ID, packet.evidence_sources[0].source_id)
        self.assertEqual(fixture["text"], packet.evidence_sources[0].text_preview)
        self.assertRegex(packet.packet_digest, r"^eligpacket_[0-9a-f]{64}$")

    def test_build_has_no_caller_supplied_evidence_or_body_entry_point(self) -> None:
        fixture = self._fixture("no-caller-body")
        build_parameters = tuple(
            inspect.signature(EligibilityAiPacketBuilder.build).parameters
        )
        forged_source = AiTaskSourceRef(
            source_id="caller-forged-evidence",
            source_type="eligibility_evidence_span",
            title="Caller supplied",
            locator="caller:memory",
            text_preview="Caller-controlled body must never enter the packet.",
            project_id=PROJECT_ID,
            module="eligibility_review",
        )

        self.assertEqual(("self", "project_id", "subject_id"), build_parameters)
        with self.assertRaises(TypeError):
            fixture["builder"].build(PROJECT_ID, SUBJECT_ID, forged_source)

        packet = fixture["builder"].build(PROJECT_ID, SUBJECT_ID)
        self.assertEqual((EVIDENCE_ID,), tuple(x.source_id for x in packet.evidence_sources))
        self.assertNotIn("Caller-controlled", packet.evidence_sources[0].text_preview)

    def test_tampered_artifact_fails_integrity_verification(self) -> None:
        fixture = self._fixture("tampered")
        artifact_path = fixture["artifact_path"]
        original = artifact_path.read_bytes()
        artifact_path.write_bytes(b"x" * len(original))

        with self.assertRaises(ArtifactIntegrityError):
            fixture["builder"].build(PROJECT_ID, SUBJECT_ID)

    def test_rejects_stale_source_unpassed_qc_and_forged_artifact_binding(self) -> None:
        stale = self._fixture("stale-source")
        stale["store"].replace_eligibility_subject_sources(
            PROJECT_ID,
            SUBJECT_ID,
            "subject-source-revision-002",
            [
                {
                    "source_id": SOURCE_ID,
                    "source_revision": "source-revision-002",
                    "content_hash": "3" * 64,
                    "size_bytes": 768,
                    "media_class": "image",
                }
            ],
        )
        with self.subTest("stale source"):
            with self.assertRaises(StaleRuntimeStateError):
                stale["builder"].build(PROJECT_ID, SUBJECT_ID)

        qc_failed = self._fixture("qc-failed", qc_result="sampled_fail")
        with self.subTest("QC not passed"):
            with self.assertRaisesRegex(ValueError, "completed evidence processing"):
                qc_failed["builder"].build(PROJECT_ID, SUBJECT_ID)

        forged = self._fixture(
            "forged-binding",
            artifact_source_id="source-002",
            artifact_source_revision="source-revision-002",
        )
        with self.subTest("forged artifact binding"):
            with self.assertRaises(RuntimeStoreIntegrityError):
                forged["builder"].build(PROJECT_ID, SUBJECT_ID)

    def test_rejects_unapproved_schema_and_extraction_revision_mismatch(self) -> None:
        unsupported = self._fixture(
            "unsupported-schema",
            schema_version="eligibility_uncontrolled_text_v1",
        )
        with self.subTest("schema allowlist"):
            with self.assertRaisesRegex(ValueError, "schema is not allowed"):
                unsupported["builder"].build(PROJECT_ID, SUBJECT_ID)

        mismatch = self._fixture(
            "revision-mismatch",
            payload_extraction_revision="extraction-revision-forged",
        )
        with self.subTest("extraction revision binding"):
            with self.assertRaisesRegex(ValueError, "extraction revision mismatch"):
                mismatch["builder"].build(PROJECT_ID, SUBJECT_ID)

    def test_blocks_when_any_current_source_has_no_qc_passed_evidence(self) -> None:
        fixture = self._fixture(
            "unprocessed-current-source",
            add_unprocessed_source=True,
        )

        with self.assertRaisesRegex(ValueError, "completed evidence processing"):
            fixture["builder"].build(PROJECT_ID, SUBJECT_ID)

    def test_blocks_when_a_current_source_has_any_unresolved_span(self) -> None:
        fixture = self._fixture(
            "unresolved-span",
            add_unresolved_span=True,
        )

        with self.assertRaisesRegex(ValueError, "completed evidence processing"):
            fixture["builder"].build(PROJECT_ID, SUBJECT_ID)

    def test_packet_digest_is_stable_and_changes_with_text_or_revision(self) -> None:
        baseline = self._fixture("digest-baseline")
        changed_text = self._fixture(
            "digest-text-changed",
            text="The subject has documented diabetes mellitus.",
        )
        changed_revision = self._fixture(
            "digest-revision-changed",
            rule_revision="rule-revision-002",
        )

        first = baseline["builder"].build(PROJECT_ID, SUBJECT_ID).packet_digest
        repeated = baseline["builder"].build(PROJECT_ID, SUBJECT_ID).packet_digest
        text_digest = changed_text["builder"].build(
            PROJECT_ID, SUBJECT_ID
        ).packet_digest
        revision_digest = changed_revision["builder"].build(
            PROJECT_ID, SUBJECT_ID
        ).packet_digest

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, text_digest)
        self.assertNotEqual(first, revision_digest)

    def test_public_packet_serialization_excludes_storage_locations(self) -> None:
        fixture = self._fixture("public-serialization")
        packet = fixture["builder"].build(PROJECT_ID, SUBJECT_ID)

        public_payload = asdict(packet)
        serialized = json.dumps(public_payload, default=str, sort_keys=True)
        all_keys = set()

        def collect_keys(value: object) -> None:
            if isinstance(value, dict):
                all_keys.update(str(key) for key in value)
                for child in value.values():
                    collect_keys(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    collect_keys(child)

        collect_keys(public_payload)
        self.assertNotIn("storage_key", all_keys)
        self.assertNotIn("path", all_keys)
        self.assertNotIn(fixture["artifact"].storage_key, serialized)
        self.assertNotIn(str(fixture["artifact_path"]), serialized)
        self.assertNotIn(str(self.root), serialized)


if __name__ == "__main__":
    unittest.main()
