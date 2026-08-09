from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from packages.contracts.workbench_contracts import (
    WritingReferenceSearchRequest,
    WritingReferenceSearchSnapshot,
)
from services.api.app.writing_reference import (
    candidate_from_study,
    extract_pdf_sections,
    search_url,
)
from services.api.app.writing_reference_repository import (
    WritingReferenceConflictError,
    WritingReferenceRepository,
    WritingReferenceStaleStateError,
)
from tests.test_writing_reference import study_fixture
from tests.test_writing_reference_extraction import artifact, pdf_fixture


NOW = datetime(2026, 7, 12, 3, 30, tzinfo=timezone.utc)
PROJECT_ID = "proj_rux_03_002"


def snapshot() -> WritingReferenceSearchSnapshot:
    request = WritingReferenceSearchRequest(
        indication="Atopic Dermatitis",
        phases=["PHASE2"],
    )
    return WritingReferenceSearchSnapshot(
        snapshot_id="wref_search_001",
        project_id=PROJECT_ID,
        request=request,
        query_url=search_url(request),
        api_version="2.0.5",
        data_timestamp="2026-07-11T09:00:05Z",
        total_count=1,
        returned_count=1,
        page_count=1,
        candidates=[candidate_from_study(study_fixture())],
        created_at=NOW,
    )


def seed_two_extraction_revisions(
    repo: WritingReferenceRepository,
):
    repo.save_search_snapshot(snapshot(), idempotency_key="two-revisions-search")
    pdf = pdf_fixture()
    source_artifact = artifact(hashlib.sha256(pdf).hexdigest()).model_copy(
        update={"actual_size": len(pdf)}
    )
    repo.save_document_artifact(
        source_artifact,
        storage_relpath="fixtures/wref_doc_extract_001/source.pdf",
        idempotency_key="two-revisions-artifact",
    )
    extracted = extract_pdf_sections(pdf, source_artifact)

    def revision(name: str, spans):
        return extracted.model_copy(
            update={
                "extraction_revision": name,
                "spans": [
                    span.model_copy(
                        update={
                            "span_id": f"{span.span_id}_{name}",
                            "extraction_revision": name,
                        }
                    )
                    for span in spans
                ],
            }
        )

    old_revision = revision("extract_r1", extracted.spans)
    latest_revision = revision("extract_r2", extracted.spans[:3])
    repo.save_extraction(old_revision, idempotency_key="two-revisions-r1")
    repo.save_extraction(latest_revision, idempotency_key="two-revisions-r2")
    return source_artifact, old_revision, latest_revision


class WritingReferenceRepositoryTests(unittest.TestCase):
    def test_legacy_security_status_payload_is_read_as_file_integrity_metadata(self) -> None:
        source = snapshot().candidates[0]
        payload = {
            "artifact_id": "legacy_artifact",
            "project_id": PROJECT_ID,
            "snapshot_id": "wref_search_001",
            "nct_id": source.nct_id,
            "source_document_id": source.public_documents[0].document_id,
            "document_type": "protocol_sap",
            "filename": "Prot_SAP_000.pdf",
            "requested_url": source.public_documents[0].download_url,
            "final_url": source.public_documents[0].download_url,
            "content_type": "application/pdf",
            "actual_size": 100,
            "content_sha256": "a" * 64,
            "security_status": "quarantine_pending_scan",
            "created_by": "medical_manager",
            "created_at": NOW.isoformat(),
        }

        artifact = WritingReferenceRepository._artifact_from_payload(json.dumps(payload))

        self.assertEqual("verified", artifact.file_integrity_status)
        self.assertNotIn("security_status", artifact.model_dump())

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "writing_reference.sqlite3"
        self.repo = WritingReferenceRepository(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_search_snapshot_is_immutable_idempotent_and_survives_restart(self) -> None:
        stored = self.repo.save_search_snapshot(snapshot(), idempotency_key="search-001")
        replay = self.repo.save_search_snapshot(snapshot(), idempotency_key="search-001")

        self.assertEqual(stored.model_dump(), replay.model_dump())
        restarted = WritingReferenceRepository(self.db_path)
        self.assertEqual(
            stored.model_dump(),
            restarted.search_snapshot(PROJECT_ID, "wref_search_001").model_dump(),
        )
        self.assertEqual(8, restarted.health_report()["schema_version"])
        self.assertEqual("ok", restarted.health_report()["status"])

        changed = snapshot().model_copy(update={"total_count": 2})
        with self.assertRaises(WritingReferenceConflictError):
            self.repo.save_search_snapshot(changed, idempotency_key="search-001")

    def test_relevance_decision_requires_reason_and_compare_and_swap(self) -> None:
        self.repo.save_search_snapshot(snapshot(), idempotency_key="search-001")
        decision = self.repo.record_relevance_decision(
            project_id=PROJECT_ID,
            snapshot_id="wref_search_001",
            nct_id="NCT05014438",
            relevance_status="direct_competitor",
            reason="同适应症、同分期且干预机制具有直接方案设计参照价值。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="relevance-001",
        )
        self.assertEqual(1, decision.revision)
        self.assertEqual("direct_competitor", decision.relevance_status)
        replay = self.repo.record_relevance_decision(
            project_id=PROJECT_ID,
            snapshot_id="wref_search_001",
            nct_id="NCT05014438",
            relevance_status="direct_competitor",
            reason="同适应症、同分期且干预机制具有直接方案设计参照价值。",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key="relevance-001",
        )
        self.assertEqual(decision.model_dump(), replay.model_dump())

        with self.assertRaises(WritingReferenceStaleStateError):
            self.repo.record_relevance_decision(
                project_id=PROJECT_ID,
                snapshot_id="wref_search_001",
                nct_id="NCT05014438",
                relevance_status="excluded",
                reason="重新判断。",
                actor="medical_manager",
                expected_revision=0,
                idempotency_key="relevance-002",
            )
        with self.assertRaises(ValueError):
            self.repo.record_relevance_decision(
                project_id=PROJECT_ID,
                snapshot_id="wref_search_001",
                nct_id="NCT05014438",
                relevance_status="indirect_reference",
                reason="",
                actor="medical_manager",
                expected_revision=1,
                idempotency_key="relevance-003",
            )

    def test_unknown_candidate_and_invalid_status_fail_closed(self) -> None:
        self.repo.save_search_snapshot(snapshot(), idempotency_key="search-001")
        for nct_id, status in (
            ("NCT00000000", "direct_competitor"),
            ("NCT05014438", "approved_by_ai"),
        ):
            with self.assertRaises(ValueError):
                self.repo.record_relevance_decision(
                    project_id=PROJECT_ID,
                    snapshot_id="wref_search_001",
                    nct_id=nct_id,
                    relevance_status=status,
                    reason="测试原因。",
                    actor="medical_manager",
                    expected_revision=0,
                    idempotency_key=f"decision-{nct_id}-{status}",
                )

    def test_domain_audit_chain_is_valid_and_immutable(self) -> None:
        self.repo.save_search_snapshot(snapshot(), idempotency_key="search-audit")
        self.assertEqual([], self.repo.verify_audit_chain(PROJECT_ID))
        with sqlite3.connect(self.db_path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE writing_reference_audit_chain SET actor='tampered' WHERE project_id=?",
                    (PROJECT_ID,),
                )

    def test_extraction_revision_queries_preserve_old_spans_and_count_only_latest(self) -> None:
        source_artifact, old_revision, latest_revision = seed_two_extraction_revisions(
            self.repo
        )

        self.assertEqual(
            latest_revision.extraction_revision,
            self.repo.latest_extraction_revision(PROJECT_ID, source_artifact.artifact_id),
        )
        old_spans = self.repo.source_spans(
            PROJECT_ID,
            source_artifact.artifact_id,
            extraction_revision=old_revision.extraction_revision,
        )
        latest_spans = self.repo.source_spans(
            PROJECT_ID,
            source_artifact.artifact_id,
            extraction_revision=latest_revision.extraction_revision,
        )
        self.assertEqual(
            {span.span_id for span in old_revision.spans},
            {span.span_id for span in old_spans},
        )
        self.assertEqual(
            {span.span_id for span in latest_revision.spans},
            {span.span_id for span in latest_spans},
        )
        self.assertTrue(
            {span.span_id for span in old_spans}.isdisjoint(
                {span.span_id for span in latest_spans}
            )
        )

        anchor = latest_revision.spans[0].ich_m11_anchor
        filtered = self.repo.source_spans(
            PROJECT_ID,
            source_artifact.artifact_id,
            extraction_revision=latest_revision.extraction_revision,
            ich_m11_anchor=anchor,
        )
        expected_anchor_counts = Counter(
            span.ich_m11_anchor for span in latest_revision.spans
        )
        self.assertEqual(expected_anchor_counts[anchor], len(filtered))
        self.assertTrue(all(span.ich_m11_anchor == anchor for span in filtered))
        self.assertEqual(
            {source_artifact.artifact_id: len(latest_revision.spans)},
            self.repo.source_span_counts(PROJECT_ID),
        )

    def test_workspace_span_count_indexes_are_present(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            extraction_indexes = {
                row[1]
                for row in connection.execute(
                    "PRAGMA index_list(writing_reference_extractions)"
                ).fetchall()
            }
            span_indexes = {
                row[1]
                for row in connection.execute(
                    "PRAGMA index_list(writing_reference_source_spans)"
                ).fetchall()
            }

        self.assertIn("idx_wref_extractions_latest", extraction_indexes)
        self.assertIn(
            "idx_wref_source_spans_artifact_revision",
            span_indexes,
        )
        with sqlite3.connect(self.db_path) as connection:
            artifact_indexes = {
                row[1]
                for row in connection.execute(
                    "PRAGMA index_list(writing_reference_document_artifacts)"
                ).fetchall()
            }
        self.assertIn("idx_wref_documents_snapshot", artifact_indexes)

    def test_source_span_counts_are_isolated_to_the_requested_snapshot(self) -> None:
        first_artifact, _old_revision, first_latest = seed_two_extraction_revisions(
            self.repo
        )
        second_snapshot = snapshot().model_copy(
            update={
                "snapshot_id": "wref_search_002",
                "created_at": NOW + timedelta(minutes=1),
            }
        )
        self.repo.save_search_snapshot(
            second_snapshot,
            idempotency_key="second-snapshot",
        )
        pdf = pdf_fixture()
        second_artifact = artifact(hashlib.sha256(pdf).hexdigest()).model_copy(
            update={
                "artifact_id": "wref_doc_extract_002",
                "snapshot_id": second_snapshot.snapshot_id,
                "actual_size": len(pdf),
                "created_at": NOW + timedelta(minutes=1),
            }
        )
        self.repo.save_document_artifact(
            second_artifact,
            storage_relpath="fixtures/wref_doc_extract_002/source.pdf",
            idempotency_key="second-artifact",
        )
        second_extraction = extract_pdf_sections(pdf, second_artifact)
        self.repo.save_extraction(
            second_extraction,
            idempotency_key="second-extraction",
        )

        self.assertEqual(
            {first_artifact.artifact_id: len(first_latest.spans)},
            self.repo.source_span_counts(
                PROJECT_ID,
                snapshot_id="wref_search_001",
            ),
        )
        self.assertEqual(
            {second_artifact.artifact_id: len(second_extraction.spans)},
            self.repo.source_span_counts(
                PROJECT_ID,
                snapshot_id="wref_search_002",
            ),
        )

    def test_v6_to_v7_migration_preserves_rows_and_latest_counts(self) -> None:
        source_artifact, _old_revision, latest_revision = seed_two_extraction_revisions(
            self.repo
        )
        expected = {
            source_artifact.artifact_id: len(latest_revision.spans),
        }
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("DELETE FROM schema_migrations WHERE version=7")
            connection.execute("DROP INDEX idx_wref_extractions_latest")
            connection.execute("DROP INDEX idx_wref_source_spans_artifact_revision")
            connection.execute("DROP INDEX idx_wref_documents_snapshot")

        migrated = WritingReferenceRepository(self.db_path)

        self.assertEqual(8, migrated.health_report()["schema_version"])
        self.assertEqual(expected, migrated.source_span_counts(PROJECT_ID))
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
            self.assertEqual([], connection.execute("PRAGMA foreign_key_check").fetchall())

    def test_concurrent_initialization_is_safe_for_fresh_and_v6_databases(self) -> None:
        def initialize_concurrently(db_path: Path) -> list[int]:
            workers = 8
            barrier = threading.Barrier(workers)

            def initialize() -> int:
                barrier.wait()
                return WritingReferenceRepository(db_path).health_report()[
                    "schema_version"
                ]

            with ThreadPoolExecutor(max_workers=workers) as executor:
                return list(executor.map(lambda _index: initialize(), range(workers)))

        fresh_path = Path(self.tmp.name) / "concurrent_fresh.sqlite3"
        self.assertEqual([8] * 8, initialize_concurrently(fresh_path))

        with sqlite3.connect(self.db_path) as connection:
            connection.execute("DELETE FROM schema_migrations WHERE version=7")
            connection.execute("DROP INDEX idx_wref_extractions_latest")
            connection.execute("DROP INDEX idx_wref_source_spans_artifact_revision")
            connection.execute("DROP INDEX idx_wref_documents_snapshot")
        self.assertEqual([8] * 8, initialize_concurrently(self.db_path))


if __name__ == "__main__":
    unittest.main()
