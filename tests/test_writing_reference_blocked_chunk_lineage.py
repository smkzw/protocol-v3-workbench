"""A110/A111 counterexamples: fidelity-blocked chapters must leave a
persistent alignment-unit lineage, and offline lineage rebuild must be
append-only, deterministic, and evidence-only.

Shapes proven here (real composite pipeline fixture, zero models,
temporary SQLite only):

- A110-R1 (write side): when the bounded-correction Hy-MT2 path raises
  ``FidelityBlockedError``, the catch block must persist a ``blocked``
  lineage row (``:blocked``-suffixed chunk_id AND chunk_fingerprint so the
  fingerprint-keyed reuse index at the top of the chunk loop can never be
  shadowed) via the standard ``save_translation_chunk`` path — state row,
  idempotency and the ``translation_chunk_saved`` audit included — while
  the integration row's ``chunk_ids`` stay untouched and the blocked main
  flow is unchanged.
- A110-R2 (write side robustness): a lineage-save failure is audited and
  must never break the blocked flow (item still fidelity_blocked,
  integration row still carries the blocked diagnostics).
- A110-R3 (no shadowing): a ``:blocked`` decoy row under an already
  completed plan must not shadow the completed chunk on reuse — the
  completed chunk is reused (no new translator calls) and the item still
  completes with the good translation.
- A111-R1 (offline rebuild): from a legacy blocked integration (no lineage
  row), the zero-model rebuild tool deterministically re-derives the chunk
  from the persisted plan+spans, matches it against the
  ``translating_hy_mt2_blocked`` stage ledger input_hash, and lands the
  lineage row. Running it twice is byte-identical on the second pass:
  net row count +1 exactly once, every pre-existing payload unchanged.
- A111-R2 (evidence-only re-judgment): the tool's re-evaluation reports
  unit-level confirmed/overturned/unverifyable verdicts from the rebuilt
  row and appends an audit event, while every batch item payload stays
  byte-identical (no generation_status flip — disposition stays with the
  human medical gate).
- A110-R4 (gate no-regression): ``reevaluate_fidelity_blocked`` still
  reports ``data_missing`` for an item whose integration carries a
  Hy-blocked raw fragment — lineage rebuild must never open the batch
  admit channel.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from packages.contracts.workbench_contracts.models import TranslationChunkRecord
from services.api.app.chapter_translation_pipeline import (
    normalize_post_hy_unit_output,
    split_source_into_units,
)
from tests.test_writing_reference_translation_batch import (
    NOW,
    PROJECT_ID,
    TENANT_ID,
)
import tests.test_writing_reference_translation_batch as _tb

WORKBENCH_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = WORKBENCH_ROOT / "scripts" / "qc" / "rebuild_blocked_chunk_lineage.py"

# Two-paragraph span -> one chunk with two translation units. Unit 1 will
# translate cleanly; unit 2 carries a numeric drift the deterministic gate
# rejects (mirrors the NCT02176291 sample shape: failed-unit isolation
# raises FidelityBlockedError from the isolation frame, so the persisted
# aligned output covers ONLY the failed unit).
SOURCE_TWO_UNITS = (
    "Participants must not receive SCS within 14 days.\n\n"
    "The primary endpoint is assessed at Week 16."
)
SPAN_ID = "span_a110_lineage"
GOOD_UNIT_2_TARGET = "主要终点在第16周进行评估。"
DEFECTIVE_UNIT_2_TARGET = "受试者在7天内接受SCS。"

_TOOL_MODULE = None


def _tool_module():
    """Import the offline rebuild tool by path (single shared instance)."""
    global _TOOL_MODULE
    if _TOOL_MODULE is None:
        spec = importlib.util.spec_from_file_location(
            "rebuild_blocked_chunk_lineage_under_test", TOOL_PATH
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        _TOOL_MODULE = module
    return _TOOL_MODULE


def _helper() -> _tb.WritingReferenceTranslationBatchTests:
    # "runTest" is TestCase's built-in default method: instantiating with it
    # gives a fully initialized TestCase (assertEqual etc.) without running
    # any of the inherited tests.
    helper = _tb.WritingReferenceTranslationBatchTests("runTest")
    helper.setUp()
    return helper


def _defective_unit2_override(chunk_id: str) -> str | None:
    """Stand-in for the real provider: unit 2 keeps failing numerically.

    The group call returns both units (unit 2 defective); the failed-unit
    isolation call (``...:failed_unit_2``) returns only unit 2, still
    defective — exactly the shape the NCT02176291 sample persisted.
    """
    if chunk_id.endswith(":failed_unit_2"):
        return (
            "[[CMS_SEG_0002]]\n"
            f"{DEFECTIVE_UNIT_2_TARGET}\n"
            "[[/CMS_SEG_0002]]"
        )
    if chunk_id == SPAN_ID:
        return (
            "[[CMS_SEG_0001]]\n受试者在14天内不得接受SCS。\n[[/CMS_SEG_0001]]\n\n"
            "[[CMS_SEG_0002]]\n"
            f"{DEFECTIVE_UNIT_2_TARGET}\n"
            "[[/CMS_SEG_0002]]"
        )
    return None


def _run_blocked_batch(helper, label: str):
    """Seed one two-unit span and run a batch that blocks on unit 2."""
    helper._seed_artifact(f"artifact_{label}", [(SPAN_ID, "eligibility", SOURCE_TWO_UNITS)])
    batch = helper.service.create(
        PROJECT_ID, helper._create_request(f"translation-batch-{label}"))
    helper.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
    item = helper.service.get(PROJECT_ID, batch.batch_id).items[0]
    return batch, item


def _dump_chunk_payloads(repo) -> dict[str, str]:
    with repo._connect() as connection:
        rows = connection.execute(
            """
            SELECT chunk_id, payload_json FROM writing_reference_translation_chunks
            WHERE tenant_id=? AND project_id=?
            ORDER BY chunk_id
            """,
            (TENANT_ID, PROJECT_ID),
        ).fetchall()
    return {row["chunk_id"]: row["payload_json"] for row in rows}


def _dump_item_payloads(repo) -> dict[str, str]:
    with repo._connect() as connection:
        rows = connection.execute(
            """
            SELECT item_id, payload_json FROM writing_reference_translation_batch_items
            WHERE tenant_id=? AND project_id=?
            ORDER BY item_id
            """,
            (TENANT_ID, PROJECT_ID),
        ).fetchall()
    return {row["item_id"]: row["payload_json"] for row in rows}


class BlockedChunkLineageTests(unittest.TestCase):
    def test_a110_r1_write_side_lands_blocked_lineage_row(self):
        helper = _helper()
        self.addCleanup(helper.tearDown)
        helper._translator.set_translate_override(_defective_unit2_override)

        batch, item = _run_blocked_batch(helper, "a110r1")
        self.assertEqual("fidelity_blocked", item.generation_status)
        plan_id = item.document_structure_plan_id

        blocked_rows = [
            chunk
            for chunk in helper.repo.translation_chunks_for_plan(PROJECT_ID, plan_id)
            if chunk.status == "blocked"
        ]
        self.assertEqual(
            1, len(blocked_rows),
            "exactly one blocked lineage row must be persisted")
        row = blocked_rows[0]
        # Derived identity: the lineage row must never collide with a real
        # (completed) chunk identity in the fingerprint-keyed reuse index.
        self.assertTrue(row.chunk_id.endswith(":blocked"), row.chunk_id)
        self.assertTrue(row.chunk_fingerprint.endswith(":blocked"))
        self.assertNotEqual(row.chunk_id, row.chunk_id[: -len(":blocked")])

        # The aligned diagnostic text and the parseable failed-unit target.
        self.assertTrue(row.translated_text.strip())
        self.assertIn("[[CMS_SEG_0002]]", row.translated_text)
        expected_target = normalize_post_hy_unit_output(
            split_source_into_units(SOURCE_TWO_UNITS)[1].text,
            DEFECTIVE_UNIT_2_TARGET,
        )
        self.assertEqual({"2": expected_target}, row.unit_targets)
        self.assertEqual("hy_mt2_blocked_diagnostic", row.translation_strategy)
        self.assertEqual(
            row.hy_mt2_input_hash,
            __import__("hashlib").sha256(
                row.source_text.encode("utf-8")).hexdigest(),
        )

        with helper.repo._connect() as connection:
            state = connection.execute(
                """
                SELECT status FROM writing_reference_translation_chunk_state
                WHERE tenant_id=? AND project_id=? AND chunk_id=?
                """,
                (TENANT_ID, PROJECT_ID, row.chunk_id),
            ).fetchone()
            self.assertIsNotNone(state)
            self.assertEqual("blocked", state["status"])

            audit = connection.execute(
                """
                SELECT COUNT(*) AS hits FROM writing_reference_audit_chain
                WHERE tenant_id=? AND project_id=? AND event_type='translation_chunk_saved'
                  AND target_id=?
                """,
                (TENANT_ID, PROJECT_ID, row.chunk_id),
            ).fetchone()
            self.assertEqual(1, audit["hits"])

            integration_row = connection.execute(
                """
                SELECT payload_json FROM writing_reference_chapter_integration_results
                WHERE tenant_id=? AND project_id=? AND plan_id=?
                  AND fidelity_status='blocked'
                """,
                (TENANT_ID, PROJECT_ID, plan_id),
            ).fetchone()
        self.assertIsNotNone(integration_row)
        integration = json.loads(integration_row["payload_json"])
        # The blocked lineage row is diagnostic lineage only: it must never
        # join the integration's candidate chunk list.
        self.assertNotIn(row.chunk_id, integration["chunk_ids"])
        self.assertTrue((integration.get("blocked_raw_provider_output") or "").strip())

        # Same-payload replay through the repository must not double-insert.
        replayed = helper.repo.save_translation_chunk(
            TranslationChunkRecord.model_validate_json(
                row.model_dump_json()),
            idempotency_key="a110-r1-manual-replay",
        )
        self.assertEqual(row.chunk_id, replayed.chunk_id)
        blocked_again = [
            chunk
            for chunk in helper.repo.translation_chunks_for_plan(PROJECT_ID, plan_id)
            if chunk.status == "blocked"
        ]
        self.assertEqual(1, len(blocked_again))

    def test_a110_r2_lineage_save_failure_does_not_break_blocked_flow(self):
        helper = _helper()
        self.addCleanup(helper.tearDown)
        helper._translator.set_translate_override(_defective_unit2_override)

        original_save = helper.repo.save_translation_chunk

        def _failing_save(chunk, *, idempotency_key):
            if chunk.status == "blocked":
                raise RuntimeError("simulated lineage persistence failure")
            return original_save(chunk, idempotency_key=idempotency_key)

        helper.repo.save_translation_chunk = _failing_save

        batch, item = _run_blocked_batch(helper, "a110r2")
        self.assertEqual(
            "fidelity_blocked", item.generation_status,
            "a lineage-save failure must never change the blocked outcome")
        plan_id = item.document_structure_plan_id

        self.assertEqual(
            [], [
                chunk
                for chunk in helper.repo.translation_chunks_for_plan(
                    PROJECT_ID, plan_id)
                if chunk.status == "blocked"
            ],
            "the failed lineage row must not exist")

        with helper.repo._connect() as connection:
            failure_audit = connection.execute(
                """
                SELECT detail_json FROM writing_reference_audit_chain
                WHERE tenant_id=? AND project_id=?
                  AND event_type='blocked_translation_chunk_save_failed'
                ORDER BY sequence_no DESC LIMIT 1
                """,
                (TENANT_ID, PROJECT_ID),
            ).fetchone()
            integration_row = connection.execute(
                """
                SELECT payload_json FROM writing_reference_chapter_integration_results
                WHERE tenant_id=? AND project_id=? AND plan_id=?
                  AND fidelity_status='blocked'
                """,
                (TENANT_ID, PROJECT_ID, plan_id),
            ).fetchone()
        self.assertIsNotNone(
            failure_audit,
            "the lineage-save failure must be recorded in the audit chain")
        self.assertIsNotNone(integration_row)
        integration = json.loads(integration_row["payload_json"])
        self.assertTrue((integration.get("blocked_aligned_output") or "").strip())

    def test_a110_r3_blocked_decoy_row_never_shadows_completed_reuse(self):
        helper = _helper()
        self.addCleanup(helper.tearDown)
        helper._seed_artifact(
            "artifact_a110r3", [(SPAN_ID, "eligibility", SOURCE_TWO_UNITS)])
        batch = helper.service.create(
            PROJECT_ID, helper._create_request("translation-batch-a110r3"))
        helper.service.run_pending(PROJECT_ID, batch.batch_id, "medical_manager")
        item = helper.service.get(PROJECT_ID, batch.batch_id).items[0]
        self.assertNotEqual("fidelity_blocked", item.generation_status)
        plan_id = item.document_structure_plan_id

        completed = [
            chunk
            for chunk in helper.repo.translation_chunks_for_plan(PROJECT_ID, plan_id)
            if chunk.status == "completed"
        ]
        self.assertEqual(1, len(completed))
        completed_chunk = completed[0]

        # Plant the :blocked decoy with the derived fingerprint suffix — the
        # same shape A110-R1 produces — under the SAME plan.
        helper.repo.save_translation_chunk(
            TranslationChunkRecord(
                chunk_id=completed_chunk.chunk_id + ":blocked",
                plan_id=completed_chunk.plan_id,
                project_id=completed_chunk.project_id,
                artifact_id=completed_chunk.artifact_id,
                chapter_id=completed_chunk.chapter_id,
                chunk_order=completed_chunk.chunk_order,
                source_span_ids=list(completed_chunk.source_span_ids),
                source_text=completed_chunk.source_text,
                source_text_sha256=completed_chunk.source_text_sha256,
                chunk_fingerprint=completed_chunk.chunk_fingerprint + ":blocked",
                hy_mt2_model=completed_chunk.hy_mt2_model,
                hy_mt2_prompt_version=completed_chunk.hy_mt2_prompt_version,
                hy_mt2_input_hash=completed_chunk.hy_mt2_input_hash,
                translated_text="[[CMS_SEG_0001]]\n诊断碎片\n[[/CMS_SEG_0001]]",
                translated_text_sha256=__import__("hashlib").sha256(
                    b"fragment").hexdigest(),
                unit_targets={},
                translation_strategy="hy_mt2_blocked_diagnostic",
                status="blocked",
                created_at=NOW,
            ),
            idempotency_key="a110-r3-decoy",
        )

        calls_before = len(helper._translator.span_calls)
        batch2 = helper.service.create(
            PROJECT_ID, helper._create_request("translation-batch-a110r3-again"))
        helper.service.run_pending(PROJECT_ID, batch2.batch_id, "medical_manager")
        item2 = helper.service.get(PROJECT_ID, batch2.batch_id).items[0]

        self.assertEqual(
            calls_before, len(helper._translator.span_calls),
            "the completed chunk must be reused, not retranslated")
        self.assertNotEqual("fidelity_blocked", item2.generation_status)
        blocked_seen = [
            chunk
            for chunk in helper.repo.translation_chunks_for_plan(PROJECT_ID, plan_id)
            if chunk.status == "blocked"
        ]
        self.assertEqual(1, len(blocked_seen))

    def test_a111_r1_rebuild_is_deterministic_and_append_only(self):
        helper = _helper()
        self.addCleanup(helper.tearDown)
        helper._translator.set_translate_override(_defective_unit2_override)

        # Legacy shape: the write-side lineage landing fails, so only the
        # blocked integration diagnostics exist — exactly the stock the
        # offline rebuild targets.
        original_save = helper.repo.save_translation_chunk

        def _failing_save(chunk, *, idempotency_key):
            if chunk.status == "blocked":
                raise RuntimeError("simulated lineage persistence failure")
            return original_save(chunk, idempotency_key=idempotency_key)

        helper.repo.save_translation_chunk = _failing_save
        batch, item = _run_blocked_batch(helper, "a111r1")
        self.assertEqual("fidelity_blocked", item.generation_status)
        helper.repo.save_translation_chunk = original_save

        before = _dump_chunk_payloads(helper.repo)
        # The blocked scenario never completed a chunk, so the legacy stock
        # may legitimately be empty — the rebuild must add exactly one row.

        tool = _tool_module()
        summary_1 = tool.rebuild_blocked_lineage(
            helper.repo, PROJECT_ID, actor="a111-test")
        self.assertEqual(1, summary_1["rebuilt"], summary_1)
        self.assertEqual(0, summary_1["data_missing"], summary_1)

        after_first = _dump_chunk_payloads(helper.repo)
        self.assertEqual(len(before) + 1, len(after_first))
        new_ids = set(after_first) - set(before)
        self.assertEqual(1, len(new_ids))
        rebuilt = json.loads(after_first[new_ids.pop()])
        self.assertEqual("blocked", rebuilt["status"])
        self.assertEqual(
            "rebuilt_offline_blocked_lineage", rebuilt["translation_strategy"])
        self.assertTrue(rebuilt["chunk_id"].endswith(":blocked"))
        self.assertTrue(rebuilt["chunk_fingerprint"].endswith(":blocked"))
        self.assertEqual(
            {"2": normalize_post_hy_unit_output(
                split_source_into_units(SOURCE_TWO_UNITS)[1].text,
                DEFECTIVE_UNIT_2_TARGET)},
            rebuilt["unit_targets"],
        )

        summary_2 = tool.rebuild_blocked_lineage(
            helper.repo, PROJECT_ID, actor="a111-test-again")
        self.assertEqual(0, summary_2["rebuilt"], summary_2)
        self.assertEqual(1, summary_2["already_present"], summary_2)
        after_second = _dump_chunk_payloads(helper.repo)
        self.assertEqual(after_first, after_second)

    def test_a111_r2_reeval_evidence_never_flips_item_status(self):
        helper = _helper()
        self.addCleanup(helper.tearDown)
        helper._translator.set_translate_override(_defective_unit2_override)

        original_save = helper.repo.save_translation_chunk

        def _failing_save(chunk, *, idempotency_key):
            if chunk.status == "blocked":
                raise RuntimeError("simulated lineage persistence failure")
            return original_save(chunk, idempotency_key=idempotency_key)

        helper.repo.save_translation_chunk = _failing_save
        batch, item = _run_blocked_batch(helper, "a111r2")
        self.assertEqual("fidelity_blocked", item.generation_status)
        helper.repo.save_translation_chunk = original_save

        tool = _tool_module()
        summary = tool.rebuild_blocked_lineage(
            helper.repo, PROJECT_ID, actor="a111-test")
        self.assertEqual(1, summary["rebuilt"], summary)

        items_before = _dump_item_payloads(helper.repo)
        report = tool.reeval_evidence(helper.repo, PROJECT_ID, actor="a111-test")
        self.assertEqual(1, len(report["integrations"]), report)
        entry = report["integrations"][0]
        self.assertEqual("confirmed", entry["unit_verdicts"]["2"], entry)
        self.assertTrue(entry["replayed_codes"], entry)
        self.assertEqual(
            sorted(entry["stored_codes"]), sorted(entry["replayed_codes"]), entry)
        # Unit 1 was never failed, so no verdict is fabricated for it.
        self.assertNotIn("1", entry["unit_verdicts"], entry)

        items_after = _dump_item_payloads(helper.repo)
        self.assertEqual(
            items_before, items_after,
            "evidence-only re-evaluation must not touch any item payload")

        with helper.repo._connect() as connection:
            audit = connection.execute(
                """
                SELECT COUNT(*) AS hits FROM writing_reference_audit_chain
                WHERE tenant_id=? AND project_id=?
                  AND event_type='blocked_fidelity_reeval_evidence'
                """,
                (TENANT_ID, PROJECT_ID),
            ).fetchone()
        self.assertGreaterEqual(audit["hits"], 1)

    def test_a110_r4_reeval_gate_still_data_missing_for_hy_blocked(self):
        helper = _helper()
        self.addCleanup(helper.tearDown)
        helper._translator.set_translate_override(_defective_unit2_override)

        batch, item = _run_blocked_batch(helper, "a110r4")
        self.assertEqual("fidelity_blocked", item.generation_status)
        items_before = _dump_item_payloads(helper.repo)

        summary = helper.service.reevaluate_fidelity_blocked(
            PROJECT_ID, batch.batch_id, "medical_manager")
        self.assertEqual(1, summary["data_missing"], summary)
        self.assertEqual(0, summary["admitted"], summary)
        self.assertEqual(0, summary["rejected"], summary)
        self.assertEqual(
            items_before, _dump_item_payloads(helper.repo),
            "the Hy-blocked raw-fragment gate must stay fail-closed")


if __name__ == "__main__":
    unittest.main()
