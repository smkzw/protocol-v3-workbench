"""G4 counterexamples: item persistence is a validation boundary and
synthetic recovery parents must be auditable.

- G4-R1: ``model_copy(update=...)`` bypasses pydantic validation; the write
  helpers (_insert_item_with / _write_item_with, translation AND preparation
  batches) must re-validate the full payload (``model_validate``) before any
  row is written, so an illegal field combination fails loudly instead of
  silently persisting.
- G4-R2: ``synthetic_recovery_*`` retry parents are allocated without a
  stage-run existence check (writing_reference_translation_batch.py:2556-2560
  "don't exist as stage runs — allocate directly"). A string prefix is not a
  permission proof: minting must write an auditable recovery record
  (audit event ``document_plan_synthetic_recovery_parent``) and allocating an
  unrecorded parent must be refused.
- Round-trip: status transition -> save -> read must be field-for-field equal.
- CAS: two writers on the same item with the same expected status/attempt ->
  exactly one success (sequential double-connection proof, no sleeps).

Zero models, zero network (A16); temporary SQLite only.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from packages.contracts.workbench_contracts.models import (
    MedicalWritingStudyFraming,
    WritingReferencePreparationBatchCreateRequest,
)
from services.api.app.writing_reference import (
    WritingReferenceDocumentService,
    WritingReferenceExtractionService,
)
from services.api.app.writing_reference_preparation_batch import (
    WritingReferencePreparationBatchService,
)
from services.api.app.writing_reference_repository import (
    TENANT_ID,
    WritingReferenceRepository,
)
from tests.test_writing_reference_preparation_batch import (
    NOW,
    PNH_NCT_ID,
    PNH_PROJECT_ID,
    PNH_SNAPSHOT_ID,
    confirmed_protocol_pdf,
    project_snapshot,
    public_document,
    ControlledDocumentClient,
)
from tests.test_writing_reference_translation_batch import PROJECT_ID
import tests.test_writing_reference_translation_batch as _tb


def _translation_helper() -> _tb.WritingReferenceTranslationBatchTests:
    # "runTest" is TestCase's built-in default method: fully initialized
    # instance without running any inherited test.
    helper = _tb.WritingReferenceTranslationBatchTests("runTest")
    helper.setUp()
    return helper


class TranslationItemPersistenceBoundaryTests(unittest.TestCase):
    def _blocked_batch(self, helper, label: str):
        batch = helper._seed_fidelity_blocked_item(
            label,
            codes=["unit_1:numbered_criterion_cardinality_changed"],
            translated_text=helper._REEVAL_GOOD_TARGET,
            unit_targets={"1": helper._REEVAL_GOOD_TARGET},
        )
        return helper.service.get(PROJECT_ID, batch.batch_id)

    def test_g4_r1_insert_rejects_illegal_model_copy_payload(self):
        helper = _translation_helper()
        self.addCleanup(helper.tearDown)
        batch = self._blocked_batch(helper, "g4r1")
        item = batch.items[0]
        # a fresh item id/span: the UNIQUE constraint must not be the gate —
        # payload validation is the boundary under test
        forged = item.model_copy(update={
            "generation_status": "bogus_status",
            "item_id": item.item_id + "_forged",
            "span_id": item.span_id + "_forged",
        })
        with self.assertRaises(ValidationError):
            with helper.repo._connect() as connection:
                helper.service._insert_item_with(connection, forged)

    def test_g4_r1b_write_rejects_illegal_model_copy_payload(self):
        helper = _translation_helper()
        self.addCleanup(helper.tearDown)
        batch = self._blocked_batch(helper, "g4r1b")
        item = batch.items[0]
        forged = item.model_copy(update={"generation_status": "bogus_status"})
        with self.assertRaises(ValidationError):
            with helper.repo._connect() as connection:
                helper.service._write_item_with(
                    connection, forged,
                    expected_status=item.generation_status,
                    expected_attempt=item.attempt)

    def test_g4_roundtrip_status_transition_is_field_exact(self):
        helper = _translation_helper()
        self.addCleanup(helper.tearDown)
        batch = self._blocked_batch(helper, "g4rt")
        item = batch.items[0]
        admitted = item.model_copy(update={
            "generation_status": "candidate_ready",
            "fidelity_status": "passed",
            "fidelity_failure_codes": [],
            "blocker_kind": "",
            "blocker_message": "",
            "pipeline_stage": "candidate_ready",
            "attempt": item.attempt + 1,
        })
        with helper.repo._connect() as connection:
            cursor = helper.service._write_item_with(
                connection, admitted,
                expected_status=item.generation_status,
                expected_attempt=item.attempt)
            connection.commit()
        self.assertEqual(1, cursor.rowcount)
        reread = helper.service.get(PROJECT_ID, admitted.batch_id).items[0]
        self.assertEqual(admitted.model_dump(mode="json"),
                         reread.model_dump(mode="json"))

    def test_g4_cas_double_writer_exactly_one_success(self):
        helper = _translation_helper()
        self.addCleanup(helper.tearDown)
        batch = self._blocked_batch(helper, "g4cas")
        item = batch.items[0]
        winner = item.model_copy(update={
            "generation_status": "candidate_ready",
            "attempt": item.attempt + 1,
        })
        loser = item.model_copy(update={
            "generation_status": "failed_terminal",
            "error_code": "cas_loser",
            "attempt": item.attempt + 1,
        })
        with helper.repo._connect() as conn_a, helper.repo._connect() as conn_b:
            cursor_a = helper.service._write_item_with(
                conn_a, winner,
                expected_status=item.generation_status,
                expected_attempt=item.attempt)
            conn_a.commit()  # first writer wins and releases the write lock
            cursor_b = helper.service._write_item_with(
                conn_b, loser,
                expected_status=item.generation_status,
                expected_attempt=item.attempt)
            conn_b.rollback()
        self.assertEqual(1, cursor_a.rowcount)
        self.assertEqual(0, cursor_b.rowcount)

    def test_g4_r2_synthetic_mint_writes_auditable_record(self):
        helper = _translation_helper()
        self.addCleanup(helper.tearDown)
        helper._seed_artifact(
            "artifact_g4r2",
            [("span_g4r2", "eligibility", helper._REEVAL_SOURCE)],
        )
        batch = helper.service.create(
            PROJECT_ID, helper._create_request("translation-batch-g4r2"))
        item = helper.service.get(PROJECT_ID, batch.batch_id).items[0]
        failed = item.model_copy(update={
            "error_code": "document_plan_failed",
            "document_plan_failure_codes": [
                "document_plan_failed_earlier_in_same_run"],
        })
        with helper.repo._connect() as connection:
            helper.service._prepare_document_plan_contract_lineage(
                connection, [failed],
                retry_generation=3, created_at=NOW, persist_migrations=True)
        with helper.repo._connect() as connection:
            row = connection.execute(
                """
                SELECT target_id FROM writing_reference_audit_chain
                WHERE tenant_id=? AND project_id=?
                  AND event_type='document_plan_synthetic_recovery_parent'
                """,
                (TENANT_ID, PROJECT_ID),
            ).fetchone()
        self.assertIsNotNone(
            row, "minting a synthetic_recovery_ parent must write an auditable "
                 "recovery record, not just a string prefix")

    def test_g4_r2b_unrecorded_parent_refused(self):
        helper = _translation_helper()
        self.addCleanup(helper.tearDown)
        with helper.repo._connect() as connection:
            with self.assertRaises(ValueError):
                helper.service._allocate_synthetic_recovery_parent_if_recorded(
                    connection, PROJECT_ID, "synthetic_recovery_999",
                    item_lineages={"item_x": {"k": "v"}})


class _LockedJourneyForTests:
    """Finalized-corpus-triage journey stand-in with a REAL framing object
    (the preparation study-facts hash reads framing fields directly)."""

    def __init__(self, project_id: str, snapshot_id: str,
                 retained: list[str]) -> None:
        self.project_id = project_id
        self.snapshot_id = snapshot_id
        self.retained = list(retained)
        self.framing = MedicalWritingStudyFraming(
            protocol_id="G4-FIXTURE-01",
            document_title="G4写入边界验证",
            investigational_product="G4研究药物",
            indication="G4适应症",
            study_phase="III期",
            intrinsic_objectives=["确证性研究"],
            target_mechanism="G4靶点",
            design_pattern="随机、双盲、安慰剂对照",
            population_intent="G4目标人群",
        )

    def lock(self, project_id: str, snapshot_id: str,
             retained_ids: list[str]) -> None:
        self.retained = list(retained_ids)

    def get(self, project_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            revision=7,
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


class PreparationItemPersistenceBoundaryTests(unittest.TestCase):
    """Same write-boundary guarantee for the preparation batch helpers."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.repo = WritingReferenceRepository(root / "writing_reference.sqlite3")
        payload = confirmed_protocol_pdf(PNH_NCT_ID)
        document_service = WritingReferenceDocumentService(
            self.repo, ControlledDocumentClient(payload),
            artifact_root=root / "artifacts", clock=lambda: NOW)
        extraction_service = WritingReferenceExtractionService(
            self.repo, artifact_root=root / "artifacts")
        journeys = _LockedJourneyForTests(PNH_PROJECT_ID, PNH_SNAPSHOT_ID,
                                          [PNH_NCT_ID])
        self.service = WritingReferencePreparationBatchService(
            self.repo, journeys, document_service, extraction_service,
            clock=lambda: NOW)
        document = public_document(
            PNH_NCT_ID, f"ctgov_{PNH_NCT_ID}_protocol", "protocol",
            f"{PNH_NCT_ID}_Protocol.pdf", len(payload))
        self.repo.save_search_snapshot(
            project_snapshot(PNH_PROJECT_ID, PNH_SNAPSHOT_ID, PNH_NCT_ID,
                             [document]),
            idempotency_key="g4-prep-snapshot")
        self.repo.record_relevance_decision(
            project_id=PNH_PROJECT_ID, snapshot_id=PNH_SNAPSHOT_ID,
            nct_id=PNH_NCT_ID, relevance_status="direct_competitor",
            reason="G4 fixture: locked direct competitor scope.",
            actor="medical_manager", expected_revision=0,
            idempotency_key="g4-prep-decision")
        journeys.lock(PNH_PROJECT_ID, PNH_SNAPSHOT_ID, [PNH_NCT_ID])
        batch = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID, actor="medical_manager",
                idempotency_key="g4-prep-create-001"))
        self.item = self.service.get(PNH_PROJECT_ID, batch.batch_id).items[0]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_g4_r1c_prep_insert_rejects_illegal_model_copy_payload(self):
        # different item_kind keeps the UNIQUE key and the document FK
        # satisfied, so payload validation is the only gate under test
        forged = self.item.model_copy(update={
            "item_kind": "study_manual_upload_required",
            "item_id": self.item.item_id + "_manual",
            "status": "bogus_status",
        })
        with self.assertRaises(ValidationError):
            with self.repo._connect() as connection:
                self.service._insert_item_with(connection, forged)

    def test_g4_r1d_prep_write_rejects_illegal_model_copy_payload(self):
        forged = self.item.model_copy(update={"status": "bogus_status"})
        with self.assertRaises(ValidationError):
            with self.repo._connect() as connection:
                self.service._write_item_with(connection, forged)


if __name__ == "__main__":
    unittest.main()
