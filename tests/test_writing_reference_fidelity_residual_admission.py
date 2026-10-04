"""R26 self-check #3, P0-A counterexample (red-first, then fix).

Field evidence (proj_user_3ea77adeef20, 2026-10-02): the objectives_endpoints
anchor had 0/5 translation candidates pass the fidelity gate; regeneration
(rev2) deterministically re-blocked; the ONLY escape was the project-level
corpus-gate exception ("确认例外并放行") — the per-translation author review
loop has no designed exit, because:

- the UI disables 确认译文并准入 whenever fidelity_status != "passed", and
- record_medical_review("approved") calls admit_translation inline, which
  hard-rejects any translation with fidelity_status != "passed"
  (writing_reference_repository.py:3719 "translation is not eligible for
  corpus admission").

The testers' own returned-review comments prove the author HAS verified the
content against the original ("已对照原文：终点定义、评价时间窗与计量单位与原
文一致…").  The product already has two precedents for author-confirmed
residual issues (document content-validation override, OCR medical
disposition "medical_confirmed_with_residual_issue").  Fixed contract:

- an author may approve-and-admit a fidelity-blocked translation ONLY by
  acknowledging EVERY fidelity failure code on it (raw or unit-prefixed
  codes both accepted; comparison is on the normalized code suffix);
- the review records the acknowledged codes; the evidence brief records
  admission_basis="author_confirmed_with_fidelity_residual" plus the codes
  and the fidelity status at admission;
- partial acknowledgement is rejected with the missing codes named;
- a machine-passed translation keeps the existing one-click approve path
  (no acknowledgement required) — unchanged.
"""
from __future__ import annotations

import unittest

from tests.test_writing_reference_translation_batch import (
    PROJECT_ID,
    SNAPSHOT_ID,
)
from tests.test_writing_reference_translation_durable_jobs import (
    _DurableBatchFixture,
)
from tests.test_writing_reference_revise_returned_batch import (
    _run_batch_to_completion,
)

SOURCE_TEXT = "The primary endpoint is assessed at Week 16."
SPAN_ID = "span_residual_admission"
ARTIFACT_ID = "artifact_residual_admission"


class TestFidelityResidualAuthorAdmission(unittest.TestCase, _DurableBatchFixture):
    def setUp(self) -> None:
        self.setup_fixture()
        self.seed_artifact(
            ARTIFACT_ID,
            [(SPAN_ID, "objectives_endpoints", SOURCE_TEXT)],
        )
        self._translator.blocked_spans = {SPAN_ID}
        self.runner.blocked_spans = {SPAN_ID}
        settled = _run_batch_to_completion(
            self.service, self.durable_store, "residual-admission-create-001"
        )
        self.assertEqual("fidelity_blocked", settled.items[0].generation_status)
        self.blocked = self.repo.translations(PROJECT_ID, span_id=SPAN_ID)[0]
        self.assertEqual("blocked", self.blocked.fidelity_status)

    def tearDown(self) -> None:
        self.teardown_fixture()

    def _approve(self, codes, key, comment="已逐项对照原文核实，残留码均为格式性问题。"):
        return self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=self.blocked.translation_id,
            translation_revision=self.blocked.revision,
            decision="approved",
            comment=comment,
            actor="medical_manager",
            expected_revision=0,
            idempotency_key=key,
            acknowledged_fidelity_failure_codes=list(codes),
        )

    def test_full_acknowledgement_admits_blocked_translation_with_residual_basis(self) -> None:
        review = self._approve(self.blocked.fidelity_failure_codes, "residual-approve-001")

        self.assertEqual("approved", review.decision)
        self.assertEqual(
            sorted(self.blocked.fidelity_failure_codes),
            sorted(review.acknowledged_fidelity_failure_codes),
        )
        briefs = self.repo.evidence_brief_history(PROJECT_ID)
        self.assertTrue(briefs, "author approval must admit the blocked translation")
        brief = briefs[0]
        self.assertEqual(
            "author_confirmed_with_fidelity_residual", brief.admission_basis
        )
        self.assertEqual("blocked", brief.fidelity_status_at_admission)
        self.assertTrue(brief.acknowledged_fidelity_failure_codes)

    def test_unit_prefixed_codes_are_accepted_for_unit_prefixed_failures(self) -> None:
        # The composite pipeline records per-unit codes such as
        # "unit_2:source_abbreviation_missing"; the fixture's deterministic
        # gate may record the bare form.  Acknowledging either the raw code
        # or its unit-prefixed variant satisfies the same normalized code.
        codes = [
            f"unit_1:{code}" if not code.startswith("unit_") else code
            for code in self.blocked.fidelity_failure_codes
        ]
        review = self._approve(codes, "residual-approve-prefixed-001")
        self.assertEqual("approved", review.decision)
        self.assertTrue(self.repo.evidence_brief_history(PROJECT_ID))

    def test_missing_or_empty_acknowledgement_is_rejected_with_codes_named(self) -> None:
        def _normalized(code: str) -> str:
            return code.split(":", 1)[1] if code.startswith("unit_") else code

        with self.assertRaises(ValueError) as missing_all:
            self._approve([], "residual-approve-empty-001")
        self.assertIn("忠实度", str(missing_all.exception))
        self.assertTrue(
            self.blocked.fidelity_failure_codes,
            "rejection must name the unacknowledged codes",
        )
        for code in self.blocked.fidelity_failure_codes:
            self.assertIn(_normalized(code), str(missing_all.exception))

        if len(self.blocked.fidelity_failure_codes) >= 2:
            with self.assertRaises(ValueError) as partial:
                self._approve(
                    self.blocked.fidelity_failure_codes[:1],
                    "residual-approve-partial-001",
                )
            self.assertIn(
                _normalized(self.blocked.fidelity_failure_codes[1]),
                str(partial.exception),
            )

    def test_machine_passed_translation_keeps_one_click_approve(self) -> None:
        """A passed translation needs no acknowledgement — regression guard."""
        # Second span on a fresh artifact under the same anchor (the batch
        # helper filters to objectives_endpoints), not blocked.
        self.seed_artifact(
            "artifact_residual_passed",
            [("span_residual_passed", "objectives_endpoints", "Participants are eligible.")],
        )
        _run_batch_to_completion(
            self.service, self.durable_store, "residual-admission-create-passed"
        )
        passed = self.repo.translations(
            PROJECT_ID, span_id="span_residual_passed"
        )[0]
        self.assertEqual("passed", passed.fidelity_status)
        review = self.repo.record_medical_review(
            project_id=PROJECT_ID,
            translation_id=passed.translation_id,
            translation_revision=passed.revision,
            decision="approved",
            comment="机器忠实度通过，作者确认准入。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="residual-approve-passed-001",
        )
        self.assertEqual("approved", review.decision)
        self.assertTrue(self.repo.evidence_brief_history(PROJECT_ID))


if __name__ == "__main__":
    unittest.main()
