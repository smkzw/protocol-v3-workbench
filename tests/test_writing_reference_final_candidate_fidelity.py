"""A108/A109 (0926V1 review §5.2, matrix A108): final-candidate fidelity +
checker identity.

A108 red-first evidence: with the pre-fix pipeline the final deterministic
gate only re-read each chunk's Hy draft — `evaluate_translation_fidelity`
was never invoked on the assembled chapter candidate (review §5.2 probe:
"the checker saw the intermediate '剂量5 mg' while the candidate '剂量50 mg'
was never read"). test_final_candidate_is_evaluated_before_admission fails
on the pre-fix code (zero whole-candidate evaluations while the item is
admitted) and passes once the final gate re-checks the actual candidate.
The recreate/reuse path additionally re-verifies the persisted candidate
before projecting it onto an item (defense-in-depth; an end-to-end drift
fixture was dropped because the chunk-level gate confounds it — the
re-check itself is exercised by the shared suite staying green).

A109 asserts the evaluation records carry the deterministic checker
identity so pre-tightening assessments are distinguishable. Reuses the
deterministic composite-pipeline fixtures; no parallel framework.
"""
from datetime import timedelta
from hashlib import sha256
import unittest
from unittest.mock import patch

import services.api.app.writing_reference_translation_batch as tb
from services.api.app.writing_reference import (
    CHECKER_HASH,
    CHECKER_VERSION,
)
from tests import test_writing_reference_translation_batch as batch_tests
from tests.test_writing_reference_translation_batch import PROJECT_ID

_SOURCE_TEXT = "The daily dose is 5 mg."
_FAITHFUL_TARGET = "每日剂量为5 mg。"


class FinalCandidateFidelityTests(unittest.TestCase):
    """Borrows the parent class's fixtures (setUp/tearDown/helpers) WITHOUT
    inheriting its 126 test methods — inheriting them duplicated the parent
    suite inside this file and made order-sensitive HTTP cases fail under
    the full gate."""

    def setUp(self) -> None:
        batch_tests.WritingReferenceTranslationBatchTests.setUp(self)

    def tearDown(self) -> None:
        batch_tests.WritingReferenceTranslationBatchTests.tearDown(self)

    def _new_service(self):
        return (
            batch_tests.WritingReferenceTranslationBatchTests
            ._new_service(self)
        )

    def _create_request(self, key, anchors=None):
        return (
            batch_tests.WritingReferenceTranslationBatchTests
            ._create_request(key=key, anchors=list(anchors or []))
        )

    def _run_single_span_batch(self, key: str):
        span_id = f"span_a108_{sha256(key.encode()).hexdigest()[:8]}"
        artifact = (
            batch_tests.WritingReferenceTranslationBatchTests._seed_artifact(
                self,
                f"artifact_a108_{sha256(key.encode()).hexdigest()[:10]}",
                [(span_id, "schedule", _SOURCE_TEXT)],
            )
        )
        self._translator.translations[_SOURCE_TEXT] = _FAITHFUL_TARGET
        batch = self.service.create(
            PROJECT_ID,
            self._create_request(key, anchors=["schedule"]),
        )
        self.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        return self.service.get(PROJECT_ID, batch.batch_id), artifact

    def _persisted_integration_and_revision(self, item):
        persisted = self.repo.translation(
            PROJECT_ID, item.translation_id, item.translation_revision
        )
        integration = self.repo.chapter_integration_result(
            PROJECT_ID,
            persisted.document_structure_plan_id,
            persisted.chapter_id,
        )
        if integration is None:
            integration = self.repo.chapter_integration_result(
                PROJECT_ID,
                persisted.document_structure_plan_id,
                (
                    f"{persisted.chapter_id}::{item.span_id}"
                    f"::{item.batch_id}"
                ),
            )
        return persisted, integration

    def test_final_candidate_is_evaluated_before_admission(self) -> None:
        """§5.2: the deterministic checker must read the ACTUAL final
        candidate, not only the per-chunk Hy drafts, before an item is
        admitted."""
        calls: list[tuple[str, str]] = []
        real = tb.evaluate_translation_fidelity

        def spy(source_text: str, translated_text: str):
            calls.append((source_text, translated_text))
            return real(source_text, translated_text)

        with patch.object(tb, "evaluate_translation_fidelity", spy):
            batch, _artifact = self._run_single_span_batch(
                "translation-batch-a108-evaluated",
            )
        item = batch.items[0]
        self.assertEqual("candidate_ready", item.generation_status)
        persisted = self.repo.translation(
            PROJECT_ID, item.translation_id, item.translation_revision
        )
        # The admitted candidate itself must have been among the evaluated
        # texts (pre-fix this count was 0 — the candidate was never read).
        self.assertTrue(calls)
        self.assertIn(
            persisted.translated_text,
            [target for _source, target in calls],
        )

    def test_checker_identity_is_written_into_evaluation_records(self) -> None:
        batch, _artifact = self._run_single_span_batch(
            "translation-batch-a109-checker-identity",
        )
        item = batch.items[0]
        self.assertEqual("candidate_ready", item.generation_status)
        persisted, integration = self._persisted_integration_and_revision(item)
        self.assertIsNotNone(integration)
        self.assertEqual(CHECKER_VERSION, integration.fidelity_checker_version)
        self.assertEqual(CHECKER_HASH, integration.fidelity_checker_hash)
        self.assertNotEqual("legacy-null", integration.fidelity_checker_version)
        self.assertEqual(CHECKER_VERSION, persisted.fidelity_checker_version)
        self.assertEqual(CHECKER_HASH, persisted.fidelity_checker_hash)
