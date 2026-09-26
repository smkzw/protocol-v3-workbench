"""G3 counterexamples: fidelity re-evaluation must bind the integration row
through the item's PERSISTED TRANSLATION CHAIN
(``translation_id``/``translation_revision`` -> WritingReferenceTranslation-
Revision.chapter_integration_result_id), not through the newest
plan/chapter prefix heuristic.

Evidence (HEAD 5b4c8c1, source read): _find_integration_for_reeval
(writing_reference_translation_batch.py:8862-8902) resolves by exact
(plan, chapter) SQL and falls back to a chapter_id LIKE-prefix heuristic —
while the authoritative chain field exists and is already enforced by the
downstream contract boundary (:1855-1865
``source_translation.chapter_integration_result_id != source_integration.integration_id``).

- G3-R1: a newer, heuristic-preferred impostor integration under the same
  (plan, chapter) must NOT steal the re-check from the translation-chain row.
  Binding is asserted through the reeval audit detail's integration_id.
- G3-R2: a span-scoped item.chapter_id that the exact and LIKE SQL both miss
  must still be re-checked through the chain (outcome: codes persist ->
  rejected, never data_missing).
- Proof fields: the reeval audit detail must carry binding source,
  candidate_hash and checker_version (A19 evidence-with-identity).

Real pipeline produces the blocked items (real translation rows); zero
models (the deterministic composite fixture stands in for the providers,
A16); temporary SQLite only.
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from hashlib import sha256

from packages.contracts.workbench_contracts.models import ChapterIntegrationResult
from tests.test_writing_reference_translation_batch import (
    NOW,
    PROJECT_ID,
    TENANT_ID,
)
import tests.test_writing_reference_translation_batch as _tb


def _helper() -> _tb.WritingReferenceTranslationBatchTests:
    # "runTest" is TestCase's built-in default method: instantiating with it
    # gives a fully initialized TestCase (assertEqual etc.) without running
    # any of the inherited tests.
    helper = _tb.WritingReferenceTranslationBatchTests("runTest")
    helper.setUp()
    return helper


def _real_blocked_batch(helper, label: str):
    """Run the REAL composite pipeline so the blocked item carries a real
    persisted translation revision (with chapter_integration_result_id).
    Drift is forced through a changed translation table entry (numeric
    drift), NOT the Hy-blocked path — a Hy-blocked chapter is data_missing
    by design and would never be re-checkable."""
    helper.runner.TRANSLATIONS[helper._REEVAL_SOURCE] = (
        "受试者必须在7天内接受SCS。")
    helper._seed_artifact(
        f"artifact_{label}",
        [(f"span_{label}", "eligibility", helper._REEVAL_SOURCE)],
    )
    batch = helper.service.create(
        PROJECT_ID, helper._create_request(f"translation-batch-{label}"))
    helper.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
    blocked = helper.service.get(PROJECT_ID, batch.batch_id)
    item = blocked.items[0]
    assert item.generation_status == "fidelity_blocked", item.generation_status
    return batch, item


def _chain_integration_id(helper, item) -> str:
    return helper.repo.translation(
        PROJECT_ID, item.translation_id, item.translation_revision
    ).chapter_integration_result_id


def _latest_reeval_audit(item_id: str, helper) -> tuple[str, dict]:
    with helper.repo._connect() as connection:
        row = connection.execute(
            """
            SELECT event_type, detail_json FROM writing_reference_audit_chain
            WHERE tenant_id=? AND project_id=? AND target_id=?
              AND event_type LIKE 'translation_batch_item_fidelity_reeval_%'
            ORDER BY sequence_no DESC LIMIT 1
            """,
            (TENANT_ID, PROJECT_ID, item_id),
        ).fetchone()
    return (row["event_type"], json.loads(row["detail_json"])) if row else ("", {})


class FidelityReevalBindingTests(unittest.TestCase):
    def test_g3_r1_chain_beats_newest_heuristic_impostor(self):
        from packages.contracts.workbench_contracts.models import (
            TranslationChunkRecord,
            WritingReferenceTranslationRevision,
        )
        helper = _helper()
        self.addCleanup(helper.tearDown)

        # Schema-true theft shape: chapter integrations persist one row per
        # (plan, span-scoped chapter). The item carries the BASE chapter id
        # ("..._g3r1") while its chain row lives under a span suffix and a
        # NEWER complete impostor row under another suffix. The exact
        # (plan, chapter) SQL misses; the LIKE prefix matches both; the
        # pre-fix heuristic prefers the newest impostor.
        plan_id = "plan_g3r1"
        base_chapter = "chapter_g3r1"
        source_text = helper._REEVAL_SOURCE
        good_target = helper._REEVAL_GOOD_TARGET

        helper._seed_artifact(
            "artifact_g3r1",
            [("span_g3r1", "eligibility", source_text)],
        )
        chunk = TranslationChunkRecord(
            chunk_id="chunk_g3r1_chain",
            plan_id=plan_id,
            project_id=PROJECT_ID,
            artifact_id="artifact_g3r1",
            chapter_id=base_chapter + ":span_1",
            chunk_order=1,
            source_span_ids=["span_g3r1"],
            source_text=source_text,
            source_text_sha256=sha256(source_text.encode("utf-8")).hexdigest(),
            chunk_fingerprint="fp_g3r1",
            hy_mt2_model="fake-hy",
            hy_mt2_prompt_version="fake-v1",
            hy_mt2_input_hash="0" * 64,
            translated_text=good_target,
            translated_text_sha256=sha256(
                good_target.encode("utf-8")).hexdigest(),
            unit_targets={"1": good_target},
            status="completed",
            created_at=NOW,
        )
        helper.repo.save_translation_chunk(
            chunk, idempotency_key="g3-r1-chain-chunk")
        chain_integration = ChapterIntegrationResult(
            integration_id="integration_g3r1_chain",
            plan_id=plan_id,
            project_id=PROJECT_ID,
            artifact_id="artifact_g3r1",
            chapter_id=base_chapter + ":span_1",
            chunk_ids=["chunk_g3r1_chain"],
            chunk_hashes=[],
            integrated_chinese_text=good_target,
            integrated_text_sha256=sha256(
                good_target.encode("utf-8")).hexdigest(),
            flash_model="fake-flash",
            flash_prompt_version="fake-v1",
            flash_input_hash="",
            flash_output_hash="",
            fidelity_status="passed",
            fidelity_failure_codes=[],
            blocked_raw_provider_output="",
            status="completed",
            created_at=NOW,
        )
        helper.repo.save_chapter_integration_result(
            chain_integration, idempotency_key="g3-r1-chain-integration")
        impostor = ChapterIntegrationResult(
            integration_id="integration_g3r1_impostor",
            plan_id=plan_id,
            project_id=PROJECT_ID,
            artifact_id="artifact_g3r1",
            chapter_id=base_chapter + ":span_9",
            chunk_ids=["chunk_g3r1_impostor_missing"],
            chunk_hashes=[],
            integrated_chinese_text="冒名顶替候选",
            integrated_text_sha256=sha256("冒名顶替候选".encode("utf-8")).hexdigest(),
            flash_model="fake-flash",
            flash_prompt_version="fake-v1",
            flash_input_hash="",
            flash_output_hash="",
            fidelity_status="completed",
            fidelity_failure_codes=[],
            blocked_raw_provider_output="",
            status="completed",
            created_at=NOW + timedelta(seconds=1),
        )
        helper.repo.save_chapter_integration_result(
            impostor, idempotency_key="g3-r1-impostor")

        # The item's persisted translation chain binds the SPAN row — the
        # exact evidence this item must be re-checked against.
        revision = WritingReferenceTranslationRevision(
            translation_id="trans_g3r1",
            project_id=PROJECT_ID,
            span_id="span_g3r1",
            source_span_revision="span_g3r1_r1",
            document_sha256=sha256("artifact_g3r1".encode("utf-8")).hexdigest(),
            glossary_version="g3",
            revision=1,
            translated_text=good_target,
            rationale="G3 fixture: chain-bound candidate.",
            fidelity_status="blocked",
            fidelity_failure_codes=["unit_1:numbered_criterion_cardinality_changed"],
            fidelity_checker_version="g3-fixture",
            ai_run_id="run_g3r1",
            created_at=NOW,
            document_structure_plan_id=plan_id,
            chapter_id=base_chapter + ":span_1",
            source_span_ids=["span_g3r1"],
            translation_chunk_ids=["chunk_g3r1_chain"],
            chapter_integration_result_id="integration_g3r1_chain",
        )
        helper.repo.save_translation(
            revision, idempotency_key="g3-r1-translation-revision")

        batch = helper.service.create(
            PROJECT_ID, helper._create_request("translation-batch-g3r1"))
        item = helper.service.get(PROJECT_ID, batch.batch_id).items[0]
        retargeted = item.model_copy(update={
            "document_structure_plan_id": plan_id,
            "chapter_id": base_chapter,
            "translation_id": "trans_g3r1",
            "translation_revision": 1,
            "generation_status": "fidelity_blocked",
            "fidelity_status": "blocked",
            "fidelity_failure_codes": [
                "unit_1:numbered_criterion_cardinality_changed"],
        })
        with helper.repo._connect() as connection:
            cursor = helper.service._write_item_with(
                connection, retargeted,
                expected_status=item.generation_status,
                expected_attempt=item.attempt)
            connection.commit()
        self.assertEqual(1, cursor.rowcount)

        summary = helper.service.reevaluate_fidelity_blocked(
            PROJECT_ID, batch.batch_id, "medical_manager")
        event_type, detail = _latest_reeval_audit(item.item_id, helper)
        self.assertEqual(
            "integration_g3r1_chain", detail.get("integration_id"),
            f"re-evaluation must bind the translation-chain integration, "
            f"not the newest heuristic impostor; summary={summary}, "
            f"detail={detail}")
        self.assertEqual("translation_chain", detail.get("binding"), detail)
        self.assertIn("candidate_hash", detail, detail)
        self.assertIn("checker_version", detail, detail)
        self.assertEqual(1, summary["admitted"], summary)

    def test_g3_r2_span_scoped_chapter_reachable_via_chain(self):
        from packages.contracts.workbench_contracts.models import (
            TranslationChunkRecord,
            WritingReferenceTranslationRevision,
        )
        helper = _helper()
        self.addCleanup(helper.tearDown)

        # Same shape as R1 minus the impostor: the item carries the BASE
        # chapter id while its chain row lives under a span suffix — the
        # exact and LIKE SQL both miss, and pre-fix this meant data_missing
        # even though the full re-checkable candidate existed.
        plan_id = "plan_g3r2"
        base_chapter = "chapter_g3r2"
        source_text = helper._REEVAL_SOURCE
        drifted_target = "受试者必须在7天内接受SCS。"
        helper._seed_artifact(
            "artifact_g3r2",
            [("span_g3r2", "eligibility", source_text)],
        )
        chunk = TranslationChunkRecord(
            chunk_id="chunk_g3r2_chain",
            plan_id=plan_id,
            project_id=PROJECT_ID,
            artifact_id="artifact_g3r2",
            chapter_id=base_chapter + ":span_1",
            chunk_order=1,
            source_span_ids=["span_g3r2"],
            source_text=source_text,
            source_text_sha256=sha256(source_text.encode("utf-8")).hexdigest(),
            chunk_fingerprint="fp_g3r2",
            hy_mt2_model="fake-hy",
            hy_mt2_prompt_version="fake-v1",
            hy_mt2_input_hash="0" * 64,
            translated_text=drifted_target,
            translated_text_sha256=sha256(
                drifted_target.encode("utf-8")).hexdigest(),
            unit_targets={"1": drifted_target},
            status="completed",
            created_at=NOW,
        )
        helper.repo.save_translation_chunk(
            chunk, idempotency_key="g3-r2-chain-chunk")
        chain_integration = ChapterIntegrationResult(
            integration_id="integration_g3r2_chain",
            plan_id=plan_id,
            project_id=PROJECT_ID,
            artifact_id="artifact_g3r2",
            chapter_id=base_chapter + ":span_1",
            chunk_ids=["chunk_g3r2_chain"],
            chunk_hashes=[],
            integrated_chinese_text=drifted_target,
            integrated_text_sha256=sha256(
                drifted_target.encode("utf-8")).hexdigest(),
            flash_model="fake-flash",
            flash_prompt_version="fake-v1",
            flash_input_hash="",
            flash_output_hash="",
            fidelity_status="blocked",
            fidelity_failure_codes=["unit_1:numeric_tokens_changed"],
            blocked_raw_provider_output="",
            status="completed",
            created_at=NOW,
        )
        helper.repo.save_chapter_integration_result(
            chain_integration, idempotency_key="g3-r2-chain-integration")
        revision = WritingReferenceTranslationRevision(
            translation_id="trans_g3r2",
            project_id=PROJECT_ID,
            span_id="span_g3r2",
            source_span_revision="span_g3r2_r1",
            document_sha256=sha256("artifact_g3r2".encode("utf-8")).hexdigest(),
            glossary_version="g3",
            revision=1,
            translated_text=drifted_target,
            rationale="G3 fixture: chain-bound drifted candidate.",
            fidelity_status="blocked",
            fidelity_failure_codes=["unit_1:numeric_tokens_changed"],
            fidelity_checker_version="g3-fixture",
            ai_run_id="run_g3r2",
            created_at=NOW,
            document_structure_plan_id=plan_id,
            chapter_id=base_chapter + ":span_1",
            source_span_ids=["span_g3r2"],
            translation_chunk_ids=["chunk_g3r2_chain"],
            chapter_integration_result_id="integration_g3r2_chain",
        )
        helper.repo.save_translation(
            revision, idempotency_key="g3-r2-translation-revision")

        batch = helper.service.create(
            PROJECT_ID, helper._create_request("translation-batch-g3r2"))
        item = helper.service.get(PROJECT_ID, batch.batch_id).items[0]
        retargeted = item.model_copy(update={
            "document_structure_plan_id": plan_id,
            "chapter_id": base_chapter,
            "translation_id": "trans_g3r2",
            "translation_revision": 1,
            "generation_status": "fidelity_blocked",
            "fidelity_status": "blocked",
            "fidelity_failure_codes": ["unit_1:numeric_tokens_changed"],
        })
        with helper.repo._connect() as connection:
            cursor = helper.service._write_item_with(
                connection, retargeted,
                expected_status=item.generation_status,
                expected_attempt=item.attempt)
            connection.commit()
        self.assertEqual(1, cursor.rowcount)

        summary = helper.service.reevaluate_fidelity_blocked(
            PROJECT_ID, batch.batch_id, "medical_manager")
        event_type, detail = _latest_reeval_audit(item.item_id, helper)
        self.assertEqual(
            "integration_g3r2_chain", detail.get("integration_id"),
            f"chain-reachable evidence must stay re-checkable when the "
            f"plan/chapter SQL misses; summary={summary}, detail={detail}")
        self.assertEqual("translation_chain", detail.get("binding"), detail)
        self.assertEqual(
            "translation_batch_item_fidelity_reeval_rejected", event_type,
            "the drifted candidate is re-checked and its codes persist")
        self.assertEqual(1, summary["rejected"], summary)


if __name__ == "__main__":
    unittest.main()
