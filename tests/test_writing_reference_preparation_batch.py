from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf
from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts.models import (
    WritingReferenceDocumentIngestRequest,
    WritingReferencePreparationBatchItem,
    WritingReferencePreparationBatchCreateRequest,
    WritingReferencePreparationBatchStageAdvanceRequest,
    WritingReferencePreparationBatchRetryRequest,
    WritingReferencePublicDocument,
)
from services.api.app.main import app
from services.api.app.paddle_ocr_adapter import PaddleOcrOutcomeUnknownError
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
from tests.test_writing_reference_extraction import pdf_fixture
from tests.test_writing_reference_repository import NOW, snapshot


PNH_PROJECT_ID = "proj_user_4bc29da4ac72"
PNH_NCT_ID = "NCT03896152"
PNH_SNAPSHOT_ID = "wref_search_pnh_locked"
RA_PROJECT_ID = "proj_user_8c78cc4421b6"
RA_NCT_ID = "NCT05306353"
RA_SNAPSHOT_ID = "wref_search_ra_locked"


@dataclass(frozen=True)
class FakeBinaryResponse:
    payload: bytes
    final_url: str
    content_type: str = "application/pdf"


class ControlledDocumentClient:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[str] = []
        self.failures_remaining: dict[str, int] = {}

    def fetch_binary(self, url: str, *, accept: str) -> FakeBinaryResponse:
        self.calls.append(url)
        if self.failures_remaining.get(url, 0) > 0:
            self.failures_remaining[url] -= 1
            raise RuntimeError("simulated public document download failure")
        return FakeBinaryResponse(payload=self.payload, final_url=url)


class FakeJourneyService:
    def __init__(self) -> None:
        self.states: dict[str, SimpleNamespace] = {}

    def lock(self, project_id: str, snapshot_id: str, retained_ids: list[str]) -> None:
        self.states[project_id] = SimpleNamespace(
            search_plan=SimpleNamespace(latest_snapshot_id=snapshot_id),
            corpus_triage=SimpleNamespace(
                status="finalized",
                snapshot_id=snapshot_id,
                retained_candidate_ids=retained_ids,
            ),
        )

    def get(self, project_id: str) -> SimpleNamespace:
        if project_id not in self.states:
            raise KeyError(project_id)
        return self.states[project_id]


def public_document(
    nct_id: str,
    document_id: str,
    document_type: str,
    filename: str,
    payload_size: int,
    document_date: str = "",
) -> WritingReferencePublicDocument:
    return WritingReferencePublicDocument(
        document_id=document_id,
        nct_id=nct_id,
        document_type=document_type,
        label=document_type.upper(),
        filename=filename,
        document_date=document_date,
        declared_size=payload_size,
        download_url=(
            f"https://clinicaltrials.gov/ProvidedDocs/{nct_id[-2:]}/{nct_id}/{filename}"
        ),
    )


def confirmed_protocol_pdf(nct_id: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 60), "STUDY PROTOCOL", fontsize=14)
    page.insert_text((72, 85), nct_id, fontsize=11)
    page.insert_text((72, 105), "Atopic Dermatitis", fontsize=11)
    page.insert_text((72, 130), "5 Study Objectives and Endpoints", fontsize=12)
    page.insert_text((72, 150), "The primary endpoint is assessed at Week 16.", fontsize=10)
    payload = document.tobytes()
    document.close()
    return payload


def project_snapshot(project_id: str, snapshot_id: str, nct_id: str, documents):
    base = snapshot()
    candidate = base.candidates[0].model_copy(
        update={
            "nct_id": nct_id,
            "study_record_url": f"https://clinicaltrials.gov/study/{nct_id}",
            "public_documents": list(documents),
        },
        deep=True,
    )
    return base.model_copy(
        update={
            "project_id": project_id,
            "snapshot_id": snapshot_id,
            "candidates": [candidate],
        },
        deep=True,
    )


class WritingReferencePreparationBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = WritingReferenceRepository(root / "writing_reference.sqlite3")
        self.payload = pdf_fixture()
        self.client = ControlledDocumentClient(self.payload)
        self.document_service = WritingReferenceDocumentService(
            self.repo,
            self.client,
            artifact_root=root / "artifacts",
            clock=lambda: NOW,
        )
        self.extraction_service = WritingReferenceExtractionService(
            self.repo,
            artifact_root=root / "artifacts",
        )
        self.journeys = FakeJourneyService()
        self.service = self._new_service()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _new_service(self) -> WritingReferencePreparationBatchService:
        return WritingReferencePreparationBatchService(
            self.repo,
            self.journeys,
            self.document_service,
            self.extraction_service,
            clock=lambda: NOW,
        )

    def _seed(self, source_snapshot) -> None:
        project_id = source_snapshot.project_id
        nct_id = source_snapshot.candidates[0].nct_id
        self.repo.save_search_snapshot(
            source_snapshot,
            idempotency_key=f"seed-{project_id}-{source_snapshot.snapshot_id}-snapshot",
        )
        self.repo.record_relevance_decision(
            project_id=project_id,
            snapshot_id=source_snapshot.snapshot_id,
            nct_id=nct_id,
            relevance_status="direct_competitor",
            reason="锁定竞品篮子中的直接竞品。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key=f"seed-{project_id}-{source_snapshot.snapshot_id}-decision",
        )
        self.journeys.lock(project_id, source_snapshot.snapshot_id, [nct_id])

    def _pnh_documents(self):
        return [
            public_document(
                PNH_NCT_ID,
                "ctgov_NCT03896152_protocol",
                "protocol",
                "NCT03896152_Protocol.pdf",
                len(self.payload),
            ),
            public_document(
                PNH_NCT_ID,
                "ctgov_NCT03896152_protocol_sap",
                "protocol_sap",
                "NCT03896152_Protocol_SAP.pdf",
                len(self.payload),
            ),
        ]

    def test_pnh_reuses_protocol_and_retries_only_failed_sap(self) -> None:
        documents = self._pnh_documents()
        source_snapshot = project_snapshot(
            PNH_PROJECT_ID,
            PNH_SNAPSHOT_ID,
            PNH_NCT_ID,
            documents,
        )
        self._seed(source_snapshot)

        protocol = self.document_service.ingest(
            PNH_PROJECT_ID,
            WritingReferenceDocumentIngestRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                nct_id=PNH_NCT_ID,
                document_id=documents[0].document_id,
                actor="medical_manager",
                idempotency_key="pnh-existing-protocol-ingest",
            ),
        )
        self.extraction_service.extract(
            PNH_PROJECT_ID,
            protocol.artifact_id,
            actor="medical_manager",
            extraction_idempotency_key="pnh-existing-protocol-extract",
        )
        protocol_validation = self.repo.document_validation(
            PNH_PROJECT_ID,
            protocol.artifact_id,
        )
        warning_codes = sorted(
            check.check_code
            for check in protocol_validation.checks
            if check.outcome in {"warning", "mismatch"}
        )
        overridden = self.repo.override_document_validation(
            project_id=PNH_PROJECT_ID,
            artifact_id=protocol.artifact_id,
            reason="医学经理已核对公开原文，明确确认该Protocol可用于当前竞品准备。",
            acknowledged_warning_codes=warning_codes,
            actor="medical_manager",
            expected_revision=protocol_validation.revision,
            idempotency_key="pnh-existing-protocol-override",
        )
        self.client.calls.clear()
        self.client.failures_remaining[documents[1].download_url] = 1

        request = WritingReferencePreparationBatchCreateRequest(
            snapshot_id=PNH_SNAPSHOT_ID,
            actor="medical_manager",
            idempotency_key="pnh-preparation-create-001",
        )
        accepted = self.service.create(PNH_PROJECT_ID, request)
        self.assertEqual("accepted", accepted.status)
        self.assertEqual(2, accepted.document_item_count)
        self.assertEqual([], self.client.calls)

        self.service.run_pending(PNH_PROJECT_ID, accepted.batch_id, request.actor)
        partial = self.service.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual("partial_failure", partial.status)
        self.assertEqual(1, partial.failed_count)
        by_type = {item.document_type: item for item in partial.items}
        self.assertEqual("prepared", by_type["protocol"].status)
        self.assertEqual("user_overridden", by_type["protocol"].validation_status)
        self.assertEqual(overridden.validation_id, by_type["protocol"].validation_id)
        self.assertEqual("failed", by_type["protocol_sap"].status)
        self.assertEqual(1, by_type["protocol"].attempt)
        self.assertEqual(1, by_type["protocol_sap"].attempt)
        self.assertEqual([documents[1].download_url], self.client.calls)

        replay = self.service.create(PNH_PROJECT_ID, request)
        self.assertEqual(partial.model_dump(), replay.model_dump())
        self.assertEqual([documents[1].download_url], self.client.calls)

        retry_request = WritingReferencePreparationBatchRetryRequest(
            actor="medical_manager",
            idempotency_key="pnh-preparation-retry-001",
        )
        retry_accepted = self.service.retry(
            PNH_PROJECT_ID,
            accepted.batch_id,
            retry_request,
        )
        self.assertEqual("running", retry_accepted.status)
        self.assertEqual(
            "failed",
            {item.document_type: item for item in retry_accepted.items}["protocol_sap"].status,
        )
        with self.repo._connect() as connection:
            retry_row = connection.execute(
                """
                SELECT status, payload_json
                FROM writing_reference_preparation_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND document_type='protocol_sap'
                """,
                (TENANT_ID, PNH_PROJECT_ID, accepted.batch_id),
            ).fetchone()
        self.assertEqual("failed", retry_row["status"])
        self.assertEqual(
            "failed",
            WritingReferencePreparationBatchItem.model_validate_json(
                retry_row["payload_json"]
            ).status,
        )
        self.service.run_failed(PNH_PROJECT_ID, accepted.batch_id, retry_request.actor)
        completed = self.service.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual("completed_with_review_required", completed.status)
        self.assertEqual(0, completed.failed_count)
        self.assertEqual(1, completed.prepared_count)
        self.assertEqual(1, completed.review_required_count)
        by_type = {item.document_type: item for item in completed.items}
        self.assertEqual(1, by_type["protocol"].attempt)
        self.assertEqual(2, by_type["protocol_sap"].attempt)
        self.assertTrue(by_type["protocol"].artifact_id)
        self.assertTrue(by_type["protocol_sap"].artifact_id)
        self.assertTrue(all(item.extraction_revision for item in completed.items))
        self.assertTrue(all(item.validation_id for item in completed.items))
        current_protocol_validation = self.repo.document_validation(
            PNH_PROJECT_ID,
            protocol.artifact_id,
        )
        self.assertEqual(2, current_protocol_validation.revision)
        self.assertEqual("user_overridden", current_protocol_validation.status)
        self.assertEqual(overridden.override_reason, current_protocol_validation.override_reason)

        replayed_retry = self.service.retry(
            PNH_PROJECT_ID,
            accepted.batch_id,
            retry_request,
        )
        self.service.run_failed(PNH_PROJECT_ID, accepted.batch_id, retry_request.actor)
        self.assertEqual(completed.model_dump(), replayed_retry.model_dump())
        self.assertEqual(1, {item.document_type: item for item in replayed_retry.items}["protocol"].attempt)
        self.assertEqual(2, {item.document_type: item for item in replayed_retry.items}["protocol_sap"].attempt)

        restarted = self._new_service()
        self.assertEqual(completed.model_dump(), restarted.get(PNH_PROJECT_ID, accepted.batch_id).model_dump())
        with self.assertRaises(KeyError):
            restarted.get(RA_PROJECT_ID, accepted.batch_id)

    def test_bounded_stage_admission_is_idempotent_and_restart_safe(self) -> None:
        documents = [
            public_document(
                PNH_NCT_ID,
                f"ctgov_{PNH_NCT_ID}_protocol_{index}",
                "protocol",
                f"{PNH_NCT_ID}_Protocol_{index}.pdf",
                len(self.payload),
            )
            for index in range(7)
        ]
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                PNH_SNAPSHOT_ID,
                PNH_NCT_ID,
                documents,
            )
        )
        processed_item_ids: list[str] = []

        def process_item(item, actor, *, progress_callback=None):
            processed_item_ids.append(item.item_id)
            self.service._complete_item(item, "prepared", actor)

        self.service._process_claimed_item = process_item

        accepted = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-bounded-stage-create-001",
                stage_size=3,
            ),
        )
        self.assertEqual(7, accepted.document_item_count)
        self.assertEqual(4, accepted.deferred_item_count)
        self.assertEqual("accepted", accepted.status)
        self.assertEqual(
            3,
            sum(item.status == "pending" for item in accepted.items),
        )
        self.assertEqual(
            4,
            sum(item.status == "deferred" for item in accepted.items),
        )

        self.service.run_pending(PNH_PROJECT_ID, accepted.batch_id, "medical_manager")
        first_stage = self.service.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual("awaiting_stage_admission", first_stage.status)
        self.assertEqual(3, first_stage.prepared_count)
        self.assertEqual(4, first_stage.deferred_item_count)
        self.assertEqual(3, len(processed_item_ids))

        advance = WritingReferencePreparationBatchStageAdvanceRequest(
            actor="medical_manager",
            idempotency_key="pnh-bounded-stage-advance-001",
        )
        second_stage = self.service.admit_next_stage(
            PNH_PROJECT_ID,
            accepted.batch_id,
            advance,
        )
        replay = self.service.admit_next_stage(
            PNH_PROJECT_ID,
            accepted.batch_id,
            advance,
        )
        self.assertEqual(second_stage.model_dump(), replay.model_dump())
        self.assertEqual(1, second_stage.deferred_item_count)
        self.assertEqual(
            3,
            sum(item.status == "pending" for item in second_stage.items),
        )
        self.assertEqual(3, len(processed_item_ids))

        self.service.run_pending(PNH_PROJECT_ID, accepted.batch_id, "medical_manager")
        after_second = self.service.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual("awaiting_stage_admission", after_second.status)
        self.assertEqual(1, after_second.deferred_item_count)
        self.assertEqual(6, len(processed_item_ids))

        restarted = self._new_service()
        restarted._process_claimed_item = process_item
        recovered = restarted.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual("awaiting_stage_admission", recovered.status)
        self.assertEqual(1, recovered.deferred_item_count)
        self.assertEqual(6, len(processed_item_ids))

        restarted.admit_next_stage(
            PNH_PROJECT_ID,
            accepted.batch_id,
            WritingReferencePreparationBatchStageAdvanceRequest(
                actor="medical_manager",
                idempotency_key="pnh-bounded-stage-advance-002",
            ),
        )
        restarted.run_pending(PNH_PROJECT_ID, accepted.batch_id, "medical_manager")
        completed = restarted.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual("completed", completed.status)
        self.assertEqual(0, completed.deferred_item_count)
        self.assertEqual(7, completed.prepared_count)
        self.assertEqual(7, len(processed_item_ids))

        with self.repo._connect() as connection:
            events = connection.execute(
                """
                SELECT event_type, detail_json
                FROM writing_reference_audit_chain
                WHERE project_id=? AND target_id=?
                  AND event_type='preparation_stage_admitted'
                ORDER BY rowid
                """,
                (PNH_PROJECT_ID, accepted.batch_id),
            ).fetchall()
        self.assertEqual(2, len(events))
        self.assertEqual([], self.repo.verify_audit_chain(PNH_PROJECT_ID))
        self.assertEqual([], self.repo.extraction_reviews(PNH_PROJECT_ID))
        self.assertEqual([], self.repo.translations(PNH_PROJECT_ID))
        self.assertEqual([], self.repo.medical_reviews(PNH_PROJECT_ID))
        self.assertEqual([], self.repo.evidence_briefs(PNH_PROJECT_ID))

    def test_restart_excludes_legacy_nonterminal_standalone_sap_without_processing(
        self,
    ) -> None:
        document = public_document(
            PNH_NCT_ID,
            "ctgov_NCT03896152_legacy_sap",
            "protocol",
            "NCT03896152_Legacy_SAP.pdf",
            len(self.payload),
        )
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                PNH_SNAPSHOT_ID,
                PNH_NCT_ID,
                [document],
            )
        )
        accepted = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="legacy-sap-restart-create",
            ),
        )
        legacy_item = accepted.items[0].model_copy(
            update={
                "document_type": "sap",
                "status": "running",
                "filename": "NCT03896152_Legacy_SAP.pdf",
            }
        )
        with self.repo._connect() as connection:
            connection.execute(
                """
                UPDATE writing_reference_preparation_items
                SET document_type='sap', status='running', payload_json=?
                WHERE tenant_id=? AND project_id=? AND item_id=?
                """,
                (
                    legacy_item.model_dump_json(),
                    TENANT_ID,
                    PNH_PROJECT_ID,
                    legacy_item.item_id,
                ),
            )
            connection.execute(
                """
                UPDATE writing_reference_preparation_batches
                SET status='running'
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                """,
                (TENANT_ID, PNH_PROJECT_ID, accepted.batch_id),
            )

        restarted = self._new_service()
        recovered = restarted.get(PNH_PROJECT_ID, accepted.batch_id)
        recovered_item = recovered.items[0]

        self.assertEqual("excluded", recovered_item.status)
        self.assertEqual("standalone_sap_out_of_scope", recovered_item.error_code)
        self.assertEqual(0, recovered_item.attempt)
        self.assertEqual("completed", recovered.status)
        self.assertEqual([], self.client.calls)

    def test_invalidated_existing_artifact_fails_before_extraction(self) -> None:
        document = self._pnh_documents()[0]
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                PNH_SNAPSHOT_ID,
                PNH_NCT_ID,
                [document],
            )
        )
        artifact = self.document_service.ingest(
            PNH_PROJECT_ID,
            WritingReferenceDocumentIngestRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                nct_id=PNH_NCT_ID,
                document_id=document.document_id,
                actor="medical_manager",
                idempotency_key="pnh-invalidated-ingest",
            ),
        )
        self.repo.invalidate_artifact(
            project_id=PNH_PROJECT_ID,
            artifact_id=artifact.artifact_id,
            reason="公开来源版本已失效，必须重新确认来源后再处理。",
            actor="medical_manager",
            expected_revision=1,
            idempotency_key="pnh-invalidated-source",
        )
        accepted = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-invalidated-batch",
            ),
        )
        with patch.object(
            self.extraction_service,
            "extract",
            wraps=self.extraction_service.extract,
        ) as extract:
            self.service.run_pending(PNH_PROJECT_ID, accepted.batch_id, "medical_manager")
        failed = self.service.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual("failed", failed.status)
        self.assertEqual("source_artifact_invalidated", failed.items[0].error_code)
        self.assertEqual(artifact.artifact_id, failed.items[0].artifact_id)
        self.assertEqual("failed", failed.items[0].ingest.status)
        self.assertEqual(0, failed.items[0].extraction.attempt)
        extract.assert_not_called()

    def test_confirmed_validation_is_prepared_without_override(self) -> None:
        confirmed_payload = confirmed_protocol_pdf(PNH_NCT_ID)
        self.client.payload = confirmed_payload
        document = public_document(
            PNH_NCT_ID,
            "ctgov_NCT03896152_confirmed_protocol",
            "protocol",
            "NCT03896152_Confirmed_Protocol.pdf",
            len(confirmed_payload),
            document_date="2026-01-01",
        )
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                PNH_SNAPSHOT_ID,
                PNH_NCT_ID,
                [document],
            )
        )
        accepted = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-confirmed-batch",
            ),
        )
        self.service.run_pending(PNH_PROJECT_ID, accepted.batch_id, "medical_manager")
        completed = self.service.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual("completed", completed.status)
        self.assertEqual(1, completed.prepared_count)
        self.assertEqual("prepared", completed.items[0].status)
        self.assertEqual("confirmed", completed.items[0].validation_status)
        validation = self.repo.document_validation(
            PNH_PROJECT_ID,
            completed.items[0].artifact_id,
        )
        self.assertEqual(1, validation.revision)
        self.assertEqual("", validation.override_reason)

    def test_run_pending_reports_persisted_locked_scope_and_document_progress(self) -> None:
        documents = self._pnh_documents()
        source_snapshot = project_snapshot(
            PNH_PROJECT_ID,
            PNH_SNAPSHOT_ID,
            PNH_NCT_ID,
            documents,
        )
        excluded_nct_id = "NCT99999999"
        excluded_candidate = source_snapshot.candidates[0].model_copy(
            update={
                "nct_id": excluded_nct_id,
                "study_record_url": f"https://clinicaltrials.gov/study/{excluded_nct_id}",
                "public_documents": [
                    public_document(
                        excluded_nct_id,
                        "ctgov_NCT99999999_protocol",
                        "protocol",
                        "NCT99999999_Protocol.pdf",
                        len(self.payload),
                    )
                ],
            },
            deep=True,
        )
        source_snapshot = source_snapshot.model_copy(
            update={"candidates": [source_snapshot.candidates[0], excluded_candidate]},
            deep=True,
        )
        self._seed(source_snapshot)

        accepted = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-progress-callback-batch",
            ),
        )
        self.assertEqual([PNH_NCT_ID], accepted.retained_candidate_ids)
        self.assertEqual(1, accepted.retained_candidate_count)
        self.assertEqual(2, accepted.document_item_count)
        self.assertEqual(2, accepted.pending_document_count)
        self.assertEqual(0, accepted.running_document_count)
        self.assertEqual(0, accepted.completed_document_count)
        self.assertEqual(
            {PNH_NCT_ID},
            {item.nct_id for item in accepted.items},
        )

        progress_snapshots = []
        self.service.run_pending(
            PNH_PROJECT_ID,
            accepted.batch_id,
            "medical_manager",
            progress_callback=lambda batch: progress_snapshots.append(
                batch.model_copy(deep=True)
            ),
        )

        self.assertTrue(progress_snapshots)
        self.assertTrue(
            any(batch.running_document_count == 1 for batch in progress_snapshots)
        )
        self.assertEqual(
            [0, 1, 2],
            sorted(
                {
                    batch.completed_document_count
                    for batch in progress_snapshots
                }
            ),
        )
        self.assertTrue(
            all(
                {item.nct_id for item in batch.items} == {PNH_NCT_ID}
                for batch in progress_snapshots
            )
        )
        completed = self.service.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual(1, completed.retained_candidate_count)
        self.assertEqual(2, completed.document_item_count)
        self.assertEqual(0, completed.pending_document_count)
        self.assertEqual(0, completed.running_document_count)
        self.assertEqual(2, completed.completed_document_count)

    def test_progress_callback_failure_cannot_strand_terminal_batch(self) -> None:
        source_snapshot = project_snapshot(
            PNH_PROJECT_ID,
            PNH_SNAPSHOT_ID,
            PNH_NCT_ID,
            self._pnh_documents(),
        )
        self._seed(source_snapshot)
        accepted = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-callback-failure-batch",
            ),
        )
        callback_calls = 0
        callback_failures = 0

        def failing_progress_callback(batch) -> None:
            nonlocal callback_calls, callback_failures
            callback_calls += 1
            if (
                batch.status == "running"
                and batch.completed_document_count == batch.document_item_count
            ):
                callback_failures += 1
                raise RuntimeError("simulated terminalization observer failure")

        self.service.run_pending(
            PNH_PROJECT_ID,
            accepted.batch_id,
            "medical_manager",
            progress_callback=failing_progress_callback,
        )

        completed = self.service.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertGreater(callback_calls, 0)
        self.assertEqual(1, callback_failures)
        self.assertEqual("completed_with_review_required", completed.status)
        self.assertEqual(0, completed.pending_document_count)
        self.assertEqual(0, completed.running_document_count)
        self.assertEqual(2, completed.completed_document_count)
        self.assertEqual(2, completed.review_required_count)

    def test_ra_without_public_protocol_has_manual_upload_study_item(self) -> None:
        unrelated = public_document(
            RA_NCT_ID,
            "ctgov_NCT05306353_other",
            "other",
            "NCT05306353_Other.pdf",
            len(self.payload),
        )
        source_snapshot = project_snapshot(
            RA_PROJECT_ID,
            RA_SNAPSHOT_ID,
            RA_NCT_ID,
            [unrelated],
        )
        self._seed(source_snapshot)
        batch = self.service.create(
            RA_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=RA_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="ra-preparation-create-001",
            ),
        )
        self.assertEqual("completed_with_manual_upload_required", batch.status)
        self.assertEqual(1, batch.item_count)
        self.assertEqual(0, batch.document_item_count)
        self.assertEqual(1, batch.manual_upload_required_count)
        item = batch.items[0]
        self.assertEqual("study_manual_upload_required", item.item_kind)
        self.assertEqual(RA_NCT_ID, item.nct_id)
        self.assertEqual("manual_upload_required", item.status)
        self.assertEqual("no_public_protocol", item.error_code)
        self.assertEqual(0, item.attempt)
        self.assertEqual("not_applicable", item.ingest.status)
        self.assertEqual("not_applicable", item.extraction.status)
        self.assertEqual("not_applicable", item.validation.status)
        self.assertEqual([], self.client.calls)

    def test_restart_recovers_accepted_items_as_failed_retryable(self) -> None:
        document = self._pnh_documents()[0]
        source_snapshot = project_snapshot(
            PNH_PROJECT_ID,
            PNH_SNAPSHOT_ID,
            PNH_NCT_ID,
            [document],
        )
        self._seed(source_snapshot)
        accepted = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-restart-create-001",
            ),
        )
        self.assertEqual("accepted", accepted.status)

        restarted = self._new_service()
        recovered = restarted.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual("failed", recovered.status)
        self.assertEqual("service_restart_interrupted", recovered.items[0].error_code)
        self.assertEqual("failed", recovered.items[0].ingest.status)

        retry = restarted.retry(
            PNH_PROJECT_ID,
            accepted.batch_id,
            WritingReferencePreparationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="pnh-restart-retry-001",
            ),
        )
        self.assertEqual("running", retry.status)
        restarted.run_failed(PNH_PROJECT_ID, accepted.batch_id, "medical_manager")
        self.assertEqual(
            "completed_with_review_required",
            restarted.get(PNH_PROJECT_ID, accepted.batch_id).status,
        )

    def test_restart_retry_reuses_durable_document_ocr_model_pin(self) -> None:
        document = self._pnh_documents()[0]
        source_snapshot = project_snapshot(
            PNH_PROJECT_ID,
            PNH_SNAPSHOT_ID,
            PNH_NCT_ID,
            [document],
        )
        self._seed(source_snapshot)
        real_extraction = self.extraction_service

        class CrashOnceExtraction:
            def __init__(self) -> None:
                self.current_model = "GLM-OCR-bf16"
                self.calls: list[str] = []
                self.crash = True

            def resolve_ocr_model(self) -> str:
                return self.current_model

            def extract(self, *args, ocr_model_override="", **kwargs):
                self.calls.append(ocr_model_override)
                if self.crash:
                    self.crash = False
                    raise KeyboardInterrupt("simulated process crash")
                return real_extraction.extract(
                    *args,
                    ocr_model_override=ocr_model_override,
                    **kwargs,
                )

        crash_once = CrashOnceExtraction()
        service = WritingReferencePreparationBatchService(
            self.repo,
            self.journeys,
            self.document_service,
            crash_once,
            clock=lambda: NOW,
        )
        accepted = service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-ocr-pin-create-001",
            ),
        )

        with self.assertRaises(KeyboardInterrupt):
            service.run_pending(
                PNH_PROJECT_ID,
                accepted.batch_id,
                "medical_manager",
            )

        pinned_running = service.get(PNH_PROJECT_ID, accepted.batch_id).items[0]
        self.assertEqual("running", pinned_running.status)
        self.assertEqual("GLM-OCR-bf16", pinned_running.ocr_model_pin)

        crash_once.current_model = "PaddleOCR-VL-1.6"
        restarted = WritingReferencePreparationBatchService(
            self.repo,
            self.journeys,
            self.document_service,
            crash_once,
            clock=lambda: NOW,
        )
        recovered = restarted.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual("failed", recovered.items[0].status)
        self.assertEqual("GLM-OCR-bf16", recovered.items[0].ocr_model_pin)

        restarted.retry(
            PNH_PROJECT_ID,
            accepted.batch_id,
            WritingReferencePreparationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="pnh-ocr-pin-retry-001",
            ),
        )
        restarted.run_failed(
            PNH_PROJECT_ID,
            accepted.batch_id,
            "medical_manager",
        )
        completed = restarted.get(PNH_PROJECT_ID, accepted.batch_id)

        self.assertEqual(["GLM-OCR-bf16", "GLM-OCR-bf16"], crash_once.calls)
        self.assertEqual("GLM-OCR-bf16", completed.items[0].ocr_model_pin)
        self.assertNotEqual(crash_once.current_model, completed.items[0].ocr_model_pin)

    def test_glm_restart_after_extraction_commit_replays_without_second_ocr_call(
        self,
    ) -> None:
        document = pymupdf.open()
        document.new_page()
        scanned_payload = document.tobytes()
        document.close()
        self.client.payload = scanned_payload
        source_document = public_document(
            PNH_NCT_ID,
            "ctgov_NCT03896152_glm_commit_crash",
            "protocol",
            "NCT03896152_GLM_Commit_Crash.pdf",
            len(scanned_payload),
        )
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                PNH_SNAPSHOT_ID,
                PNH_NCT_ID,
                [source_document],
            )
        )
        ocr_calls: list[tuple[int, int, str]] = []
        durable_extraction = WritingReferenceExtractionService(
            self.repo,
            artifact_root=Path(self.tmp.name) / "artifacts",
            ocr_runner=lambda page, dpi, model, image: (
                ocr_calls.append((page, dpi, model))
                or "STUDY PROTOCOL NCT03896152 Study Objectives and Endpoints"
            ),
        )

        class CrashAfterExtractionCommit:
            def __init__(self) -> None:
                self.crash = True

            def resolve_ocr_model(self) -> str:
                return "GLM-OCR-bf16"

            def extract(self, *args, **kwargs):
                result = durable_extraction.extract(*args, **kwargs)
                if self.crash:
                    self.crash = False
                    raise KeyboardInterrupt(
                        "simulated crash after extraction persistence"
                    )
                return result

        extraction = CrashAfterExtractionCommit()
        service = WritingReferencePreparationBatchService(
            self.repo,
            self.journeys,
            self.document_service,
            extraction,
            clock=lambda: NOW,
        )
        accepted = service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-glm-commit-crash-create-001",
            ),
        )

        with self.assertRaises(KeyboardInterrupt):
            service.run_pending(
                PNH_PROJECT_ID,
                accepted.batch_id,
                "medical_manager",
            )
        self.assertEqual(1, len(ocr_calls))

        restarted = WritingReferencePreparationBatchService(
            self.repo,
            self.journeys,
            self.document_service,
            extraction,
            clock=lambda: NOW,
        )
        recovered = restarted.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual("service_restart_interrupted", recovered.items[0].error_code)
        restarted.retry(
            PNH_PROJECT_ID,
            accepted.batch_id,
            WritingReferencePreparationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="pnh-glm-commit-crash-retry-001",
            ),
        )
        restarted.run_failed(
            PNH_PROJECT_ID,
            accepted.batch_id,
            "medical_manager",
        )

        completed = restarted.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertIn(
            completed.status,
            {"completed", "completed_with_review_required"},
        )
        self.assertEqual("GLM-OCR-bf16", completed.items[0].ocr_model_pin)
        self.assertEqual(1, len(ocr_calls))

    def test_paddle_crash_restart_is_outcome_unknown_and_not_resubmitted(self) -> None:
        document = self._pnh_documents()[0]
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                PNH_SNAPSHOT_ID,
                PNH_NCT_ID,
                [document],
            )
        )
        real_extraction = self.extraction_service

        class CrashAfterPaddlePin:
            def __init__(self) -> None:
                self.calls = 0

            def resolve_ocr_model(self) -> str:
                return "PaddleOCR-VL-1.6"

            def extract(self, *args, **kwargs):
                self.calls += 1
                raise KeyboardInterrupt("simulated crash after Paddle submit")

        crash = CrashAfterPaddlePin()
        service = WritingReferencePreparationBatchService(
            self.repo,
            self.journeys,
            self.document_service,
            crash,
            clock=lambda: NOW,
        )
        accepted = service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-paddle-crash-create-001",
            ),
        )

        with self.assertRaises(KeyboardInterrupt):
            service.run_pending(
                PNH_PROJECT_ID,
                accepted.batch_id,
                "medical_manager",
            )

        restarted = WritingReferencePreparationBatchService(
            self.repo,
            self.journeys,
            self.document_service,
            real_extraction,
            clock=lambda: NOW,
        )
        recovered = restarted.get(PNH_PROJECT_ID, accepted.batch_id).items[0]
        self.assertEqual("paddle_ocr_outcome_unknown", recovered.error_code)
        self.assertEqual("PaddleOCR-VL-1.6", recovered.ocr_model_pin)

        restarted.retry(
            PNH_PROJECT_ID,
            accepted.batch_id,
            WritingReferencePreparationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="pnh-paddle-crash-retry-001",
            ),
        )
        restarted.run_failed(
            PNH_PROJECT_ID,
            accepted.batch_id,
            "medical_manager",
        )

        unchanged = restarted.get(PNH_PROJECT_ID, accepted.batch_id).items[0]
        self.assertEqual("paddle_ocr_outcome_unknown", unchanged.error_code)
        self.assertEqual(1, crash.calls)

    def test_submit_outcome_unknown_is_classified_and_not_retried(self) -> None:
        document = self._pnh_documents()[0]
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                PNH_SNAPSHOT_ID,
                PNH_NCT_ID,
                [document],
            )
        )

        class SubmitOutcomeUnknown:
            def __init__(self) -> None:
                self.calls = 0

            def resolve_ocr_model(self) -> str:
                return "PaddleOCR-VL-1.6"

            def extract(self, *args, **kwargs):
                self.calls += 1
                raise PaddleOcrOutcomeUnknownError(
                    "Paddle OCR submit request failed: HTTP 503"
                )

        extraction = SubmitOutcomeUnknown()
        service = WritingReferencePreparationBatchService(
            self.repo,
            self.journeys,
            self.document_service,
            extraction,
            clock=lambda: NOW,
        )
        accepted = service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-paddle-submit-unknown-create-001",
            ),
        )
        service.run_pending(
            PNH_PROJECT_ID,
            accepted.batch_id,
            "medical_manager",
        )
        failed = service.get(PNH_PROJECT_ID, accepted.batch_id).items[0]
        self.assertEqual("paddle_ocr_outcome_unknown", failed.error_code)

        service.retry(
            PNH_PROJECT_ID,
            accepted.batch_id,
            WritingReferencePreparationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="pnh-paddle-submit-unknown-retry-001",
            ),
        )
        service.run_failed(
            PNH_PROJECT_ID,
            accepted.batch_id,
            "medical_manager",
        )
        self.assertEqual(1, extraction.calls)

    def test_retry_claim_resets_stale_progress_from_failed_attempt(self) -> None:
        document = self._pnh_documents()[0]
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                PNH_SNAPSHOT_ID,
                PNH_NCT_ID,
                [document],
            )
        )
        accepted = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-stale-progress-create-001",
            ),
        )
        item = accepted.items[0].model_copy(
            update={
                "status": "failed",
                "error_code": "service_restart_interrupted",
                "error_detail": "interrupted after OCR",
                "progress": accepted.items[0].progress.model_copy(
                    update={
                        "phase": "failed",
                        "current_substep": "上次尝试中断",
                        "completed": 1,
                        "total": 1,
                        "percent": 100,
                        "unit": "file",
                    }
                ),
            },
            deep=True,
        )
        self.service._write_item(item)

        claimed = self.service._claim_item(
            PNH_PROJECT_ID,
            accepted.batch_id,
            item.item_id,
            {"failed"},
        )

        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual("running", claimed.status)
        self.assertEqual("queued", claimed.progress.phase)
        self.assertEqual("正在开始本次重试", claimed.progress.current_substep)
        self.assertEqual(0, claimed.progress.percent)
        self.assertEqual(0, claimed.progress.completed)
        self.assertEqual(1, claimed.progress.total)

    def test_retry_does_not_resubmit_paddle_outcome_unknown_item(self) -> None:
        document = self._pnh_documents()[0]
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                PNH_SNAPSHOT_ID,
                PNH_NCT_ID,
                [document],
            )
        )
        accepted = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-paddle-unknown-create-001",
            ),
        )
        failed = accepted.items[0].model_copy(
            update={
                "status": "failed",
                "error_code": "paddle_ocr_outcome_unknown",
                "error_detail": (
                    "Paddle OCR job job_accepted poll request failed: HTTP 503"
                ),
            },
            deep=True,
        )
        self.service._write_item(failed)

        self.service.retry(
            PNH_PROJECT_ID,
            accepted.batch_id,
            WritingReferencePreparationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="pnh-paddle-unknown-retry-001",
            ),
        )
        self.service.run_failed(
            PNH_PROJECT_ID,
            accepted.batch_id,
            "medical_manager",
        )
        unchanged = self.service.get(PNH_PROJECT_ID, accepted.batch_id).items[0]

        self.assertEqual("failed", unchanged.status)
        self.assertEqual("paddle_ocr_outcome_unknown", unchanged.error_code)
        self.assertEqual(0, unchanged.attempt)
        self.assertEqual([], self.client.calls)

    def test_api_create_get_and_retry_use_202_contract(self) -> None:
        unrelated = public_document(
            RA_NCT_ID,
            "ctgov_NCT05306353_other",
            "other",
            "NCT05306353_Other.pdf",
            len(self.payload),
        )
        self._seed(project_snapshot(RA_PROJECT_ID, RA_SNAPSHOT_ID, RA_NCT_ID, [unrelated]))
        client = TestClient(app)
        with (
            patch(
                "services.api.app.main.writing_reference_preparation_batch_service",
                self.service,
            ),
            patch(
                "services.api.app.main._canonical_module_project_id",
                side_effect=lambda project_id, module: project_id,
            ),
        ):
            created = client.post(
                f"/api/projects/{RA_PROJECT_ID}/medical-writing/references/preparation-batches",
                json={
                    "snapshot_id": RA_SNAPSHOT_ID,
                    "actor": "medical_manager",
                    "idempotency_key": "ra-api-preparation-create-001",
                },
            )
            self.assertEqual(202, created.status_code, created.text)
            batch_id = created.json()["batch_id"]
            fetched = client.get(
                f"/api/projects/{RA_PROJECT_ID}/medical-writing/references/preparation-batches/{batch_id}"
            )
            self.assertEqual(200, fetched.status_code, fetched.text)
            fetched_payload = fetched.json()
            self.assertEqual(1, fetched_payload["retained_candidate_count"])
            self.assertEqual(0, fetched_payload["document_item_count"])
            self.assertEqual(0, fetched_payload["pending_document_count"])
            self.assertEqual(0, fetched_payload["running_document_count"])
            self.assertEqual(0, fetched_payload["completed_document_count"])
            self.assertEqual(1, fetched_payload["manual_upload_required_count"])
            self.assertEqual(
                "manual_upload_required",
                fetched_payload["items"][0]["status"],
            )
            latest = client.get(
                f"/api/projects/{RA_PROJECT_ID}/medical-writing/references/preparation-batches/latest",
                params={"snapshot_id": RA_SNAPSHOT_ID},
            )
            self.assertEqual(200, latest.status_code, latest.text)
            self.assertEqual(batch_id, latest.json()["batch_id"])
            missing = client.get(
                f"/api/projects/{RA_PROJECT_ID}/medical-writing/references/preparation-batches/latest",
                params={"snapshot_id": "missing_snapshot"},
            )
            self.assertEqual(404, missing.status_code, missing.text)
            retried = client.post(
                f"/api/projects/{RA_PROJECT_ID}/medical-writing/references/preparation-batches/{batch_id}/retry",
                json={
                    "actor": "medical_manager",
                    "idempotency_key": "ra-api-preparation-retry-001",
                },
            )
            self.assertEqual(202, retried.status_code, retried.text)
            self.assertEqual(1, retried.json()["manual_upload_required_count"])

    def test_latest_batch_is_strictly_scoped_by_project_and_snapshot(self) -> None:
        pnh_document = self._pnh_documents()[0]
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                PNH_SNAPSHOT_ID,
                PNH_NCT_ID,
                [pnh_document],
            )
        )
        pnh_first = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-latest-first",
            ),
        )

        second_snapshot_id = "wref_search_pnh_locked_v2"
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                second_snapshot_id,
                PNH_NCT_ID,
                [pnh_document],
            )
        )
        pnh_second = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=second_snapshot_id,
                actor="medical_manager",
                idempotency_key="pnh-latest-second",
            ),
        )

        ra_snapshot = project_snapshot(
            RA_PROJECT_ID,
            PNH_SNAPSHOT_ID,
            RA_NCT_ID,
            [],
        )
        self._seed(ra_snapshot)
        ra_batch = self.service.create(
            RA_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-latest-first",
            ),
        )

        self.assertEqual(
            pnh_first.batch_id,
            self.service.latest(PNH_PROJECT_ID, PNH_SNAPSHOT_ID).batch_id,
        )
        self.assertEqual(
            pnh_second.batch_id,
            self.service.latest(PNH_PROJECT_ID, second_snapshot_id).batch_id,
        )
        self.assertEqual(
            ra_batch.batch_id,
            self.service.latest(RA_PROJECT_ID, PNH_SNAPSHOT_ID).batch_id,
        )
        with self.assertRaises(KeyError):
            self.service.latest(RA_PROJECT_ID, second_snapshot_id)


    def test_progress_is_persisted_at_real_boundaries_and_survives_refresh(self) -> None:
        documents = self._pnh_documents()[:1]
        source_snapshot = project_snapshot(
            PNH_PROJECT_ID,
            PNH_SNAPSHOT_ID,
            PNH_NCT_ID,
            documents,
        )
        self._seed(source_snapshot)
        accepted = self.service.create(
            PNH_PROJECT_ID,
            WritingReferencePreparationBatchCreateRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                actor="medical_manager",
                idempotency_key="pnh-fine-progress-create-001",
            ),
        )
        snapshots = []
        self.service.run_pending(
            PNH_PROJECT_ID,
            accepted.batch_id,
            "medical_manager",
            progress_callback=lambda batch: snapshots.append(batch.model_copy(deep=True)),
        )

        phases = [snapshot.progress.phase for snapshot in snapshots]
        for phase in (
            "downloading",
            "native_extracting",
            "extraction_persisting",
            "content_validating",
            "completed",
        ):
            self.assertIn(phase, phases)
        self.assertEqual(
            sorted(snapshot.progress.percent for snapshot in snapshots),
            [snapshot.progress.percent for snapshot in snapshots],
        )
        refreshed = self.service.get(PNH_PROJECT_ID, accepted.batch_id)
        self.assertEqual("completed", refreshed.items[0].progress.phase)
        self.assertIn(
            refreshed.items[0].progress.current_substep,
            {"文件准备完成", "文件已准备，等待人工内容确认"},
        )
        self.assertEqual(100, refreshed.progress.percent)

    def test_ocr_progress_reports_render_and_completion_page_units(self) -> None:
        document = pymupdf.open()
        for _ in range(3):
            document.new_page()
        scanned_payload = document.tobytes()
        document.close()
        self.client.payload = scanned_payload
        source_document = public_document(
            PNH_NCT_ID,
            "ctgov_NCT03896152_scanned_protocol",
            "protocol",
            "NCT03896152_Scanned_Protocol.pdf",
            len(scanned_payload),
        )
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                PNH_SNAPSHOT_ID,
                PNH_NCT_ID,
                [source_document],
            )
        )
        artifact = self.document_service.ingest(
            PNH_PROJECT_ID,
            WritingReferenceDocumentIngestRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                nct_id=PNH_NCT_ID,
                document_id=source_document.document_id,
                actor="medical_manager",
                idempotency_key="pnh-ocr-progress-ingest-001",
            ),
        )
        extraction_service = WritingReferenceExtractionService(
            self.repo,
            artifact_root=Path(self.tmp.name) / "artifacts",
            ocr_runner=lambda page, dpi, model, image: f"OCR page {page}",
        )
        events = []
        extraction_service.extract(
            PNH_PROJECT_ID,
            artifact.artifact_id,
            actor="medical_manager",
            extraction_idempotency_key="pnh-ocr-progress-extract-001",
            progress_callback=events.append,
        )
        rendering = [event for event in events if event["phase"] == "ocr_rendering"]
        completion = [event for event in events if event["phase"] == "ocr_completing"]
        self.assertEqual([0, 1, 2, 3], [event["completed"] for event in rendering])
        self.assertEqual([0, 1, 2, 3], [event["completed"] for event in completion])
        self.assertTrue(all(event["total"] == 3 for event in rendering + completion))

    def test_ocr_progress_separates_physical_page_from_selected_ocr_count(self) -> None:
        payload = pdf_fixture()
        source_document = public_document(
            PNH_NCT_ID,
            "ctgov_NCT03896152_sparse_ocr",
            "protocol",
            "NCT03896152_Sparse_OCR.pdf",
            len(payload),
        )
        self.client.payload = payload
        self._seed(
            project_snapshot(
                PNH_PROJECT_ID,
                PNH_SNAPSHOT_ID,
                PNH_NCT_ID,
                [source_document],
            )
        )
        artifact = self.document_service.ingest(
            PNH_PROJECT_ID,
            WritingReferenceDocumentIngestRequest(
                snapshot_id=PNH_SNAPSHOT_ID,
                nct_id=PNH_NCT_ID,
                document_id=source_document.document_id,
                actor="medical_manager",
                idempotency_key="pnh-sparse-ocr-ingest-001",
            ),
        )
        events = []
        extraction_service = WritingReferenceExtractionService(
            self.repo,
            artifact_root=Path(self.tmp.name) / "artifacts",
            ocr_runner=lambda page, dpi, model, image: (
                f"{page} Study Objectives and Endpoints"
            ),
        )
        with patch(
            "services.api.app.writing_reference.detect_anomaly_pages",
            return_value=[
                {"physical_page": 2, "reason": "anomaly"},
                {"physical_page": 5, "reason": "anomaly"},
            ],
        ):
            extraction_service.extract(
                PNH_PROJECT_ID,
                artifact.artifact_id,
                actor="medical_manager",
                extraction_idempotency_key="pnh-sparse-ocr-extract-001",
                progress_callback=events.append,
            )

        completion = [
            event
            for event in events
            if event["phase"] == "ocr_completing" and event["completed"] > 0
        ]
        page_five = next(
            event
            for event in completion
            if event["context"]["physical_page"] == 5
        )
        self.assertIn("第 5 页", page_five["current_substep"])
        self.assertIn("全文共 5 页", page_five["current_substep"])
        self.assertNotIn("5/2", page_five["current_substep"])
        self.assertEqual(2, page_five["context"]["ocr_page_total"])
        self.assertEqual(5, page_five["context"]["document_page_total"])
        self.assertLessEqual(
            page_five["context"]["completed_ocr_pages"],
            page_five["context"]["ocr_page_total"],
        )


class WritingReferencePreparationErrorCodeTests(unittest.TestCase):
    """Focused tests for the _error_code failure mapping in the preparation service."""

    def test_network_url_error_maps_to_download_failed(self) -> None:
        import urllib.error

        error = urllib.error.URLError("connection refused")
        code = WritingReferencePreparationBatchService._error_code("ingest", error)
        self.assertEqual("public_document_download_failed", code)

    def test_http_error_maps_to_download_failed(self) -> None:
        import urllib.error

        error = urllib.error.HTTPError(
            "https://clinicaltrials.gov/missing.pdf", 404, "Not Found", {}, None
        )
        code = WritingReferencePreparationBatchService._error_code("ingest", error)
        self.assertEqual("public_document_download_failed", code)

    def test_timeout_error_maps_to_download_failed(self) -> None:
        code = WritingReferencePreparationBatchService._error_code(
            "ingest", TimeoutError("read timed out")
        )
        self.assertEqual("public_document_download_failed", code)

    def test_connection_reset_maps_to_download_failed(self) -> None:
        code = WritingReferencePreparationBatchService._error_code(
            "ingest", ConnectionResetError("connection reset")
        )
        self.assertEqual("public_document_download_failed", code)

    def test_local_file_not_found_is_not_misreported_as_download_failed(self) -> None:
        code = WritingReferencePreparationBatchService._error_code(
            "ingest", FileNotFoundError("artifact path is missing")
        )
        self.assertEqual("ingest_failed", code)

    def test_local_permission_error_is_not_misreported_as_download_failed(self) -> None:
        code = WritingReferencePreparationBatchService._error_code(
            "ingest", PermissionError("artifact path is not writable")
        )
        self.assertEqual("ingest_failed", code)

    def test_exceeds_size_limit_maps_to_download_failed(self) -> None:
        code = WritingReferencePreparationBatchService._error_code(
            "ingest", RuntimeError("ClinicalTrials.gov document exceeds size limit")
        )
        self.assertEqual("public_document_download_failed", code)

    def test_generic_runtime_error_from_client_maps_to_download_failed(self) -> None:
        """A generic RuntimeError raised by the document client during fetch
        (the pattern produced by a simulated download failure) must map to
        the specific download-failed code, not the generic stage_failed code.
        """
        code = WritingReferencePreparationBatchService._error_code(
            "ingest", RuntimeError("simulated public document download failure")
        )
        self.assertEqual("public_document_download_failed", code)

    def test_pdf_validation_failure_still_maps_to_content_invalid(self) -> None:
        code = WritingReferencePreparationBatchService._error_code(
            "ingest", RuntimeError("PDF validation failed: magic=False")
        )
        self.assertEqual("public_document_content_invalid", code)

    def test_redirect_not_allowed_still_maps_to_redirect_code(self) -> None:
        code = WritingReferencePreparationBatchService._error_code(
            "ingest",
            RuntimeError("download final URL is outside the ClinicalTrials.gov allowlist"),
        )
        self.assertEqual("public_document_redirect_not_allowed", code)

    def test_preparation_item_error_keeps_its_own_code(self) -> None:
        from services.api.app.writing_reference_preparation_batch import (
            WritingReferencePreparationItemError,
        )

        error = WritingReferencePreparationItemError(
            "source_artifact_invalidated", "test"
        )
        code = WritingReferencePreparationBatchService._error_code("ingest", error)
        self.assertEqual("source_artifact_invalidated", code)
