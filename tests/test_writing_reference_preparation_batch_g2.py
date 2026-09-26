"""G2 preparation-batch validation (A201-A206 + concurrency + bypass audit).

Real services, temporary SQLite only (A20): the only fake is the public-
document HTTP download boundary (ControlledDocumentClient, the repo's
documented preparation-batch pattern); every business state change flows
through the product services.

Scenario map:
- A201 clean-store first create;
- A202 exact same-command replay reuses the batch (no duplicated items,
  exactly one idempotency row);
- A203 same idempotency key + CHANGED study facts must raise
  WritingReferenceConflictError — RED on the pre-fix HEAD, which silently
  replayed the stale batch because request_hash only covered
  {snapshot_id, stage_size} (writing_reference_preparation_batch.py:219-229,
  replay checked before _frozen_scope at :231);
- A204 new key + changed facts -> a NEW scope version/batch, old batch and
  audit chain intact;
- A205 _frozen_scope is a one-shot journey read: retained ids and the study
  facts hash always come from the SAME journey revision (no torn scope);
- A206 two preparation batches on one snapshot: a new translation batch binds
  the LATEST preparation batch explicitly; an older translation batch keeps
  its stored binding and its pending items are failed_terminal/stale_lineage
  instead of running under a scope they were never frozen against;
- concurrency: same-key double submit through two connections + a barrier
  yields exactly one batch (BEGIN IMMEDIATE serialization + in-transaction
  replay re-check), never two.
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from packages.contracts.workbench_contracts.models import (
    WritingReferencePreparationBatchCreateRequest,
    WritingReferenceTranslationBatchCreateRequest,
)
from services.api.app.medical_writing_durable_jobs import DurableJobStore
from services.api.app.writing_reference import (
    WritingReferenceDocumentService,
    WritingReferenceExtractionService,
    WritingReferenceTranslationService,
)
from services.api.app.writing_reference_preparation_batch import (
    WritingReferencePreparationBatchService,
)
from services.api.app.writing_reference_repository import (
    TENANT_ID,
    WritingReferenceConflictError,
    WritingReferenceRepository,
)
from services.api.app.writing_reference_translation_batch import (
    TERMINAL_PREPARATION_STATUSES,
    WritingReferenceTranslationBatchService,
)
from tests._composite_pipeline_fixture import (
    build_deterministic_pipeline,
    wire_pipeline_calls_to_runner,
)
from tests.test_writing_reference_preparation_batch import (
    NOW,
    ControlledDocumentClient,
    PNH_NCT_ID,
    PNH_PROJECT_ID,
    PNH_SNAPSHOT_ID,
    confirmed_protocol_pdf,
    project_snapshot,
    public_document,
)
from tests.test_writing_reference_translation_batch import (
    GLOSSARY_VERSION,
    FakeTranslationRunner,
)

from hashlib import sha256


class MutableJourney:
    """Authoring-journey stand-in whose facts/retained set can be advanced.

    get() always returns a FRESH snapshot object built from the current
    mutable fields, so a caller holding an earlier object never observes a
    later flip through it (mirrors real revision semantics).
    """

    def __init__(self, project_id: str, snapshot_id: str, retained: list[str],
                 framing) -> None:
        self.project_id = project_id
        self.snapshot_id = snapshot_id
        self.retained = list(retained)
        self.framing = framing
        self.revision = 7
        self.get_calls = 0

    def advance_facts(self, framing) -> None:
        self.framing = framing
        self.revision += 1  # revision advances with facts, not with reads

    def get(self, project_id: str) -> SimpleNamespace:
        self.get_calls += 1
        return SimpleNamespace(
            revision=self.revision,
            search_plan=SimpleNamespace(latest_snapshot_id=self.snapshot_id),
            corpus_triage=SimpleNamespace(
                status="finalized",
                snapshot_id=self.snapshot_id,
                retained_candidate_ids=list(self.retained),
            ),
            framing=self.framing,
            picos=None,
            framing_draft=None,
            picos_draft=None,
            discovery_basket_projection=None,
        )


def _fact_a_framing():
    from packages.contracts.workbench_contracts.models import MedicalWritingStudyFraming
    return MedicalWritingStudyFraming(
        protocol_id="G2-FIXTURE-01",
        document_title="G2验证起点：研究设计v1",
        investigational_product="G2研究药物v1",
        indication="G2适应症",
        study_phase="III期",
        intrinsic_objectives=["确证性研究"],
        target_mechanism="G2靶点v1",
        design_pattern="随机、双盲、安慰剂对照",
        population_intent="G2目标人群",
    )


def _fact_b_framing():
    framing = _fact_a_framing()
    return framing.model_copy(update={"investigational_product": "G2研究药物v2",
                                      "target_mechanism": "G2靶点v2"})


class G2PreparationBatchValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp_dir)
        self.repo = WritingReferenceRepository(root / "writing_reference.sqlite3")
        self.payload = confirmed_protocol_pdf(PNH_NCT_ID)
        self.client = ControlledDocumentClient(self.payload)
        self.document_service = WritingReferenceDocumentService(
            self.repo, self.client, artifact_root=root / "artifacts",
            clock=lambda: NOW)
        self.extraction_service = WritingReferenceExtractionService(
            self.repo, artifact_root=root / "artifacts")
        self.journeys = MutableJourney(
            PNH_PROJECT_ID, PNH_SNAPSHOT_ID, [PNH_NCT_ID], _fact_a_framing())
        self.service = self._new_service()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @property
    def tmp_dir(self) -> str:
        return self._tmp.name

    def _new_service(self, repo=None) -> WritingReferencePreparationBatchService:
        return WritingReferencePreparationBatchService(
            repo or self.repo,
            self.journeys,
            self.document_service,
            self.extraction_service,
            clock=lambda: NOW,
        )

    def _seed_locked_scope(self) -> None:
        document = public_document(
            PNH_NCT_ID, f"ctgov_{PNH_NCT_ID}_protocol", "protocol",
            f"{PNH_NCT_ID}_Protocol.pdf", len(self.payload))
        source_snapshot = project_snapshot(
            PNH_PROJECT_ID, PNH_SNAPSHOT_ID, PNH_NCT_ID, [document])
        self.repo.save_search_snapshot(
            source_snapshot,
            idempotency_key=f"g2-{PNH_SNAPSHOT_ID}-snapshot")
        self.repo.record_relevance_decision(
            project_id=PNH_PROJECT_ID,
            snapshot_id=PNH_SNAPSHOT_ID,
            nct_id=PNH_NCT_ID,
            relevance_status="direct_competitor",
            reason="G2 fixture: locked direct competitor scope.",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key=f"g2-{PNH_SNAPSHOT_ID}-decision",
        )

    def _create_request(self, key: str) -> WritingReferencePreparationBatchCreateRequest:
        return WritingReferencePreparationBatchCreateRequest(
            snapshot_id=PNH_SNAPSHOT_ID,
            actor="medical_manager",
            idempotency_key=key,
        )

    def _idempotency_rows(self, key: str) -> int:
        with self.repo._connect() as connection:
            rows = connection.execute(
                """
                SELECT COUNT(*) FROM writing_reference_idempotency
                WHERE tenant_id=? AND project_id=? AND operation=?
                  AND idempotency_key=?
                """,
                (TENANT_ID, PNH_PROJECT_ID, "create_preparation_batch", key),
            ).fetchone()
        return int(rows[0])

    def _audit_batch_ids(self) -> set[str]:
        with self.repo._connect() as connection:
            rows = connection.execute(
                """
                SELECT target_id FROM writing_reference_audit_chain
                WHERE tenant_id=? AND project_id=? AND event_type=?
                """,
                (TENANT_ID, PNH_PROJECT_ID, "preparation_batch_created"),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def _seed_translation_input(self) -> None:
        """Seed one extracted, validated span via PUBLIC repository write APIs
        (durable-jobs test precedent) so the translation batch has an eligible
        span whose source text is covered by the deterministic pipeline."""
        from packages.contracts.workbench_contracts.models import (
            WritingReferenceDocumentArtifact,
            WritingReferenceDocumentValidationRecord,
            WritingReferenceExtractedSpan,
            WritingReferenceExtractionResult,
        )

        artifact_id = "artifact_g2_a206"
        text = "The primary endpoint is assessed at Week 16."
        artifact_hash = sha256(artifact_id.encode("utf-8")).hexdigest()
        artifact = WritingReferenceDocumentArtifact(
            artifact_id=artifact_id,
            project_id=PNH_PROJECT_ID,
            snapshot_id=PNH_SNAPSHOT_ID,
            nct_id=PNH_NCT_ID,
            source_document_id=f"source_{artifact_id}",
            document_type="protocol",
            filename=f"{artifact_id}.pdf",
            requested_url=f"https://clinicaltrials.gov/{artifact_id}.pdf",
            final_url=f"https://clinicaltrials.gov/{artifact_id}.pdf",
            content_type="application/pdf",
            actual_size=1024,
            content_sha256=artifact_hash,
            created_by="medical_manager",
            created_at=NOW,
        )
        self.repo.save_document_artifact(
            artifact,
            storage_relpath=f"safe/{artifact_id}.pdf",
            idempotency_key=f"g2-{artifact_id}-artifact",
        )
        span = WritingReferenceExtractedSpan(
            span_id="span_g2_a206",
            project_id=PNH_PROJECT_ID,
            artifact_id=artifact_id,
            extraction_revision="extract_r1",
            physical_page=1,
            block_index=0,
            source_locator=f"ctgov:{PNH_NCT_ID}:{artifact_id}:p1:b0",
            ich_m11_anchor="endpoints",
            source_text=text,
            source_text_sha256=sha256(text.encode("utf-8")).hexdigest(),
        )
        self.repo.save_extraction(
            WritingReferenceExtractionResult(
                artifact_id=artifact_id,
                project_id=PNH_PROJECT_ID,
                extraction_revision="extract_r1",
                parser_name="g2_fixture_parser",
                parser_version="1",
                page_count=1,
                status="pending_visual_and_medical_structure_review",
                spans=[span],
            ),
            idempotency_key=f"g2-{artifact_id}-extract_r1",
        )
        self.repo.save_document_validation(
            WritingReferenceDocumentValidationRecord(
                validation_id=f"validation_{artifact_id}",
                project_id=PNH_PROJECT_ID,
                artifact_id=artifact_id,
                revision=1,
                status="confirmed",
                document_sha256=artifact_hash,
                extraction_revision="extract_r1",
                source_state_revision=1,
                summary="G2 fixture: content confirmed for translation.",
                actor="medical_manager",
                created_at=NOW,
            ),
            expected_revision=0,
            idempotency_key=f"g2-{artifact_id}-validation",
        )
        self.repo.record_extraction_review(
            project_id=PNH_PROJECT_ID,
            artifact_id=artifact_id,
            extraction_revision="extract_r1",
            decision="approved",
            confirmed_anchor_coverage=["endpoints"],
            unresolved_structure_issues=[],
            comment="G2 fixture: structure review through the product API.",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key=f"g2-{artifact_id}-structure-review",
        )

    # ------------------------------------------------------------- A201

    def test_a201_first_create_on_clean_store(self):
        self._seed_locked_scope()
        batch = self.service.create(PNH_PROJECT_ID, self._create_request("g2-a201-001"))
        self.assertEqual("accepted", batch.status)
        self.assertEqual(64, len(batch.scope_sha256))
        self.assertEqual([PNH_NCT_ID], batch.retained_candidate_ids)
        self.assertEqual(1, self._idempotency_rows("g2-a201-001"))

    # ------------------------------------------------------------- A202

    def test_a202_exact_replay_same_key_reuses_batch(self):
        self._seed_locked_scope()
        first = self.service.create(PNH_PROJECT_ID, self._create_request("g2-a202-001"))
        items_after_first = self.service.get(PNH_PROJECT_ID, first.batch_id).item_count
        replay = self.service.create(PNH_PROJECT_ID, self._create_request("g2-a202-001"))
        self.assertEqual(first.batch_id, replay.batch_id)
        self.assertEqual(first.scope_sha256, replay.scope_sha256)
        again = self.service.get(PNH_PROJECT_ID, first.batch_id)
        self.assertEqual(items_after_first, again.item_count)  # no duplicated items
        self.assertEqual(1, self._idempotency_rows("g2-a202-001"))

    # ------------------------------------------------------------- A203 (red pre-fix)

    def test_a203_same_key_changed_facts_conflicts(self):
        self._seed_locked_scope()
        first = self.service.create(PNH_PROJECT_ID, self._create_request("g2-a203-001"))
        self.journeys.advance_facts(_fact_b_framing())  # research design changed
        with self.assertRaises(WritingReferenceConflictError):
            self.service.create(PNH_PROJECT_ID, self._create_request("g2-a203-001"))
        # the original batch is untouched: the stored scope was not mutated
        current = self.service.get(PNH_PROJECT_ID, first.batch_id)
        self.assertEqual(first.scope_sha256, current.scope_sha256)

    # ------------------------------------------------------------- A204

    def test_a204_new_key_changed_facts_new_scope(self):
        self._seed_locked_scope()
        first = self.service.create(PNH_PROJECT_ID, self._create_request("g2-a204-001"))
        self.journeys.advance_facts(_fact_b_framing())
        second = self.service.create(PNH_PROJECT_ID, self._create_request("g2-a204-002"))
        self.assertNotEqual(first.batch_id, second.batch_id)
        self.assertNotEqual(first.scope_sha256, second.scope_sha256)
        self.assertEqual(first.batch_id,
                         self.service.get(PNH_PROJECT_ID, first.batch_id).batch_id)
        self.assertEqual({first.batch_id, second.batch_id}, self._audit_batch_ids())

    # ------------------------------------------------------------- A205

    def test_a205_frozen_scope_one_shot_read_is_tear_free(self):
        self._seed_locked_scope()
        # the journey advances to facts v2 the moment it is read a SECOND
        # time: a torn implementation would mix v1 retained ids with v2 facts
        original_get = self.journeys.get

        def flipping_get(project_id: str):
            snapshot_obj = original_get(project_id)
            self.journeys.advance_facts(_fact_b_framing())
            return snapshot_obj

        self.journeys.get = flipping_get
        facts_v1 = self.service._study_facts_hash(original_get(PNH_PROJECT_ID))
        retained_ids, _entries, study_facts = self.service._frozen_scope(
            PNH_PROJECT_ID, PNH_SNAPSHOT_ID)
        self.assertEqual(facts_v1, study_facts,
                         "scope mixed journey revisions: retained ids and the "
                         "study-facts hash must come from ONE read")
        self.assertEqual([PNH_NCT_ID], retained_ids)

    # ------------------------------------------------------------- A206

    def test_a206_two_preparations_translation_binds_latest_and_old_stays(self):
        from services.api.app.writing_reference_translation_batch import (
            WritingReferenceTranslationBatchItem,
        )
        self._seed_locked_scope()
        prep1 = self.service.create(PNH_PROJECT_ID, self._create_request("g2-a206-prep1"))
        self.service.run_pending(PNH_PROJECT_ID, prep1.batch_id, "medical_manager")
        prep1 = self.service.get(PNH_PROJECT_ID, prep1.batch_id)
        self.assertIn(prep1.status, TERMINAL_PREPARATION_STATUSES)

        runner = FakeTranslationRunner()
        pipeline, _planner, translator, _qc = build_deterministic_pipeline()
        translator.translations = runner.TRANSLATIONS
        wire_pipeline_calls_to_runner(runner, translator)
        translation_service = WritingReferenceTranslationService(
            self.repo, runner, clock=lambda: NOW, chapter_pipeline=pipeline)
        batch_service = WritingReferenceTranslationBatchService(
            self.repo, self.journeys, self.service, translation_service,
            clock=lambda: NOW, chapter_pipeline=pipeline)
        self._seed_translation_input()

        def translation_request(key: str) -> WritingReferenceTranslationBatchCreateRequest:
            return WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                glossary_version=GLOSSARY_VERSION,
                anchor_filter=[],
                actor="medical_manager",
                idempotency_key=key,
            )

        old_batch = batch_service.create(PNH_PROJECT_ID, translation_request("g2-a206-trans-old"))
        self.assertEqual(prep1.batch_id, old_batch.preparation_batch_id)

        # research design changes; a NEW preparation batch becomes the latest
        self.journeys.advance_facts(_fact_b_framing())
        prep2 = self.service.create(PNH_PROJECT_ID, self._create_request("g2-a206-prep2"))
        self.service.run_pending(PNH_PROJECT_ID, prep2.batch_id, "medical_manager")
        prep2 = self.service.get(PNH_PROJECT_ID, prep2.batch_id)
        self.assertIn(prep2.status, TERMINAL_PREPARATION_STATUSES)

        new_batch = batch_service.create(PNH_PROJECT_ID, translation_request("g2-a206-trans-new"))
        self.assertEqual(prep2.batch_id, new_batch.preparation_batch_id,
                         "new translation tasks must bind the latest preparation batch")
        self.assertEqual(prep1.batch_id,
                         batch_service.get(PNH_PROJECT_ID, old_batch.batch_id)
                         .preparation_batch_id)

        # resuming the OLD batch after latest moved: items are failed as
        # stale_lineage, never translated under a scope they were not frozen
        # against
        batch_service.run_pending(PNH_PROJECT_ID, old_batch.batch_id, "medical_manager")
        resumed = batch_service.get(PNH_PROJECT_ID, old_batch.batch_id)
        states = {item.generation_status for item in resumed.items}
        self.assertNotIn("candidate_ready", states,
                         "old batch must not translate under the new preparation scope")
        self.assertTrue(resumed.items, "fixture must yield at least one translatable span")
        stale = [item for item in resumed.items
                 if item.generation_status == "failed_terminal"
                 and item.error_code == "stale_lineage"]
        self.assertTrue(stale, "pending old-batch items must fail as stale_lineage")

    # --------------------------------------------------- concurrency

    def test_concurrent_same_key_double_submit_single_batch(self):
        self._seed_locked_scope()
        root = Path(self.tmp_dir)
        repo_b = WritingReferenceRepository(root / "writing_reference.sqlite3")
        service_b = self._new_service(repo=repo_b)
        request = self._create_request("g2-conc-001")
        barrier = threading.Barrier(2, timeout=60)
        results: dict[str, object] = {}

        def submit(tag: str, svc: WritingReferencePreparationBatchService):
            barrier.wait()
            try:
                results[tag] = svc.create(PNH_PROJECT_ID, request)
            except Exception as exc:  # a conflict is acceptable, silence is not
                results[tag] = exc

        threads = [
            threading.Thread(target=submit, args=("a", self.service)),
            threading.Thread(target=submit, args=("b", service_b)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        self.assertNotIn("a-exc", results)
        first, second = results["a"], results["b"]
        for result in (first, second):
            self.assertFalse(isinstance(result, Exception), repr(result))
        self.assertEqual(first.batch_id, second.batch_id)
        with self.repo._connect() as connection:
            count = connection.execute(
                """
                SELECT COUNT(*) FROM writing_reference_preparation_batches
                WHERE tenant_id=? AND project_id=?
                """,
                (TENANT_ID, PNH_PROJECT_ID),
            ).fetchone()
        self.assertEqual(1, int(count[0]))


if __name__ == "__main__":
    unittest.main()
