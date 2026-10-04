"""R26 self-check R5 (第1次), P0 counterexample (red-first, then fix).

Field evidence (proj_user_415ce4db48b2, 2026-10-03): the deployed residual
admission path returned 200 (R4's 422 fixed) but was functionally hollow —
all 5 objectives_endpoints blocked translations had translated_text length 0
(DB), so the admitted briefs carried approved_zh_text="" and the corpus
gate's substantive check (>=20 chars) could never pass.

Root cause (code): the composite pipeline's Hy-stage blocked branch persists
degenerate candidate text in BOTH twins:
- batch (writing_reference_translation_batch.py ~5634):
  final_text = chapter_translated_text  (completed chunks ONLY) — a block on
  the FIRST chunk leaves nothing completed and persists an EMPTY candidate;
- direct (writing_reference.py ~1597): final_text = hy_block_text (the
  failing chunk's fragment ONLY) — discards already-completed chunks.

Fixed contract pinned here:
1. A fidelity-blocked chapter with completed chunk text persists exactly that
   completed text (reviewable, span-bound) — unchanged for that case;
2. A block with NO completed chunks falls back to the failing chunk's last
   output fragment (last_output, else raw provider output, markers stripped)
   so the author always has a non-empty candidate to review/admit with the
   per-code acknowledgement flow;
3. If even the fragment is empty (model produced nothing reviewable), the
   item must NOT persist a fidelity_blocked candidate at all — it raises and
   lands as a retryable generation failure;
4. Never, under any path, may a translation row be persisted with empty
   translated_text from the blocked branch.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.api.app.chapter_translation_pipeline import FidelityBlockedError
from tests.test_writing_reference_translation_batch import PROJECT_ID
from tests.test_writing_reference_translation_durable_jobs import (
    _DurableBatchFixture,
)
from tests.test_writing_reference_revise_returned_batch import (
    _run_batch_to_completion,
)

SOURCE_TEXT = "The primary endpoint is assessed at Week 16."
SPAN_ID = "span_blocked_empty_front"
ARTIFACT_ID = "artifact_blocked_empty_front"
FRAGMENT = "主要终点在第16周进行评估（残留片段）。"


class TestBlockedCandidateNeverEmpty(unittest.TestCase, _DurableBatchFixture):
    def setUp(self) -> None:
        self.setup_fixture()
        self.seed_artifact(
            ARTIFACT_ID,
            [(SPAN_ID, "objectives_endpoints", SOURCE_TEXT)],
        )

    def tearDown(self) -> None:
        self.teardown_fixture()

    def _translations(self):
        return self.repo.translations(PROJECT_ID, span_id=SPAN_ID)

    def test_first_chunk_block_with_fragment_persists_the_fragment(self) -> None:
        """No completed chunks + non-empty last_output => fragment persists."""
        from services.api.app import writing_reference_translation_batch as batch_mod

        real = batch_mod.translate_units_with_bounded_correction

        def blocked_with_fragment(translator, **kwargs):
            raise FidelityBlockedError(
                ("unit_1:source_abbreviation_missing",),
                last_output=f"[[CMS_SEG_0001]]\n{FRAGMENT}\n[[/CMS_SEG_0001]]",
                raw_provider_output=FRAGMENT,
            )

        with patch.object(
            batch_mod,
            "translate_units_with_bounded_correction",
            side_effect=blocked_with_fragment,
        ), patch.object(
            # The blocked-lineage diagnostics row also uses the real function;
            # it must tolerate the same raise.
            batch_mod,
            "_blocked_lineage_unit_targets",
            lambda units, last_output, codes: {},
        ):
            del real
            settled = _run_batch_to_completion(
                self.service, self.durable_store, "blocked-fragment-create-001"
            )

        self.assertEqual("fidelity_blocked", settled.items[0].generation_status)
        rows = self._translations()
        self.assertTrue(rows, "the blocked candidate must still be persisted")
        self.assertTrue(
            rows[0].translated_text.strip(),
            "a first-chunk block must persist the reviewable fragment, not empty text",
        )
        self.assertEqual("blocked", rows[0].fidelity_status)

    def test_block_with_no_reviewable_output_fails_retryably_instead_of_empty(self) -> None:
        """Model produced nothing => no fidelity_blocked row may be persisted."""
        from services.api.app import writing_reference_translation_batch as batch_mod

        def blocked_empty(translator, **kwargs):
            raise FidelityBlockedError(
                ("unit_1:numeric_tokens_changed",),
                last_output="",
                raw_provider_output="",
            )

        with patch.object(
            batch_mod,
            "translate_units_with_bounded_correction",
            side_effect=blocked_empty,
        ):
            settled = _run_batch_to_completion(
                self.service, self.durable_store, "blocked-empty-create-001"
            )

        item = settled.items[0]
        self.assertNotEqual(
            "fidelity_blocked",
            item.generation_status,
            "an empty blocked candidate must not be reviewable/admittable",
        )
        self.assertEqual("failed_retryable", item.generation_status)
        self.assertEqual([], self._translations())


if __name__ == "__main__":
    unittest.main()
