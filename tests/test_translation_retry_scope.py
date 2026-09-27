"""G5 范围限定恢复命令（0927V1 §3 恢复命令语义：范围是命令的组成部分）。

A511 nct_ids 归一化（去空白/剔除空项）
A512 非法条目（过短）拒绝
A513 空范围 = 全量（过滤助手原样返回）
A514 范围过滤只保留目标研究的失败项
A515 范围入 request_hash：同键不同范围产生不同命令身份
A516 全链路反例（0927V1 目标一）：范围命令在 durable job 排队后，
事务内重校验必须与预检使用同一范围集合——否则范围外失败项的
planning lineage 使 bounded_identity 不一致，命令在 job 已排队后
仍被误报 409 'document-plan contract transition changed after preflight'。
"""

from collections import defaultdict
import json
import tempfile
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from packages.contracts.workbench_contracts.models import (
    WritingReferenceDocumentArtifact,
    WritingReferenceDocumentValidationRecord,
    WritingReferenceExtractedSpan,
    WritingReferenceExtractionResult,
    WritingReferenceTranslationBatchCreateRequest,
    WritingReferenceTranslationBatchRetryRequest,
)
from services.api.app.writing_reference_repository import (
    TENANT_ID,
    WritingReferenceRepository,
)
from services.api.app.writing_reference import (
    WritingReferenceTranslationService,
)
from services.api.app.writing_reference_translation_batch import (
    WritingReferenceTranslationBatchService,
    _filter_items_by_nct_scope,
)
from tests._composite_pipeline_fixture import (
    build_deterministic_pipeline,
)
from tests.test_writing_reference_repository import snapshot
from tests.test_writing_reference_translation_batch import (
    FakeJourneyService,
    FakePreparationService,
    FakeTranslationRunner,
)

NOW = datetime(2026, 7, 16, 1, 30, tzinfo=timezone.utc)
PROJECT_ID = "proj_scope_chain_01"
SNAPSHOT_ID = "wref_search_batch_locked"
GLOSSARY_VERSION = "cms_regulatory_zh_v1"
STRUCTURAL_CODES = [
    "flash_planner_structural_failure",
    "planner_missing_required_boundary",
    "planner_missing_top_level_boundary_segment_2",
]


def _item(nct_id, item_id=None):
    return SimpleNamespace(
        nct_id=nct_id,
        item_id=item_id or ("wref_translation_item_" + nct_id.lower()),
    )


class RetryScopeContractTests(unittest.TestCase):
    def test_a511_nct_ids_normalized(self):
        req = WritingReferenceTranslationBatchRetryRequest(
            idempotency_key="scope-test-key-01",
            nct_ids=[" NCT02176291 ", "", "NCT041"],
        )
        self.assertEqual(req.nct_ids, ["NCT02176291", "NCT041"])

    def test_a512_invalid_entry_rejected(self):
        with self.assertRaises(Exception):
            WritingReferenceTranslationBatchRetryRequest(
                idempotency_key="scope-test-key-02",
                nct_ids=["N1"],
            )


class RetryScopeFilterTests(unittest.TestCase):
    def test_a513_empty_scope_returns_all(self):
        items = [_item("NCT1"), _item("NCT2")]
        self.assertEqual(len(_filter_items_by_nct_scope(items, [])), 2)

    def test_a514_scope_keeps_only_matching(self):
        items = [_item("NCT02176291"), _item("NCT999"), _item("NCT041")]
        kept = _filter_items_by_nct_scope(items, ["NCT02176291"])
        self.assertEqual([i.nct_id for i in kept], ["NCT02176291"])


class RetryScopeHashTests(unittest.TestCase):
    def test_a515_scope_changes_command_identity(self):
        from services.api.app.writing_reference_translation_batch import _payload_hash

        base = {"batch_id": "b", "idempotency_key": "k"}
        scoped = dict(base, nct_ids=["NCT02176291"])
        self.assertNotEqual(_payload_hash(base), _payload_hash(scoped))
        self.assertEqual(
            _payload_hash(scoped),
            _payload_hash({"batch_id": "b", "idempotency_key": "k", "nct_ids": ["NCT02176291"]}),
        )


class RetryScopeCommandChainTests(unittest.TestCase):
    """A516：两条连续范围命令的全链路验收（范围外项需要 planning lineage）。

    两个 artifact 分别绑定不同 nct_id，全部 4 个项都是 parentless
    structural failed_retryable（重试时会分配 synthetic lineage）。
    修复前：事务内重校验读取【全部】失败项，bounded_identity 与预检的
    范围集合不一致 → durable job 已排队仍抛 409（本测试红）。
    修复后：事务内对同一范围集合重校验，两条命令都走 202/running 语义，
    且只有范围内项被写入 lineage（本测试绿）。
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = WritingReferenceRepository(
            Path(self.tmp.name) / "writing_reference.sqlite3"
        )
        source_snapshot = snapshot().model_copy(
            update={"project_id": PROJECT_ID, "snapshot_id": SNAPSHOT_ID},
            deep=True,
        )
        self.repo.save_search_snapshot(
            source_snapshot,
            idempotency_key="scope-chain-search-snapshot",
        )
        self.nct_a = "NCT02176291"
        self.nct_b = "NCT00828097"
        self.journeys = FakeJourneyService()
        self.journeys.lock(PROJECT_ID, SNAPSHOT_ID, [self.nct_a, self.nct_b])
        self.preparation = FakePreparationService()
        self.preparation.set(
            PROJECT_ID, SNAPSHOT_ID, retained_ids=[self.nct_a, self.nct_b]
        )
        self.runner = FakeTranslationRunner()
        self._pipeline, self._planner, self._translator, self._qc = (
            build_deterministic_pipeline()
        )
        self.translation_service = WritingReferenceTranslationService(
            self.repo,
            self.runner,
            clock=lambda: NOW,
            chapter_pipeline=self._pipeline,
        )
        self.service = WritingReferenceTranslationBatchService(
            self.repo,
            self.journeys,
            self.preparation,
            self.translation_service,
            clock=lambda: NOW,
            chapter_pipeline=self._pipeline,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_artifact(
        self, artifact_id: str, nct_id: str, spans: list[tuple[str, str, str]]
    ):
        artifact_hash = sha256(artifact_id.encode("utf-8")).hexdigest()
        artifact = WritingReferenceDocumentArtifact(
            artifact_id=artifact_id,
            project_id=PROJECT_ID,
            snapshot_id=SNAPSHOT_ID,
            nct_id=nct_id,
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
            idempotency_key=f"seed-{artifact_id}-artifact",
        )
        extracted_spans = [
            WritingReferenceExtractedSpan(
                span_id=span_id,
                project_id=PROJECT_ID,
                artifact_id=artifact_id,
                extraction_revision="extract_r1",
                physical_page=index + 1,
                block_index=index,
                source_locator=f"ctgov:{nct_id}:{artifact_id}:p{index + 1}:b{index}",
                ich_m11_anchor=anchor,
                source_text=text,
                source_text_sha256=sha256(text.encode("utf-8")).hexdigest(),
            )
            for index, (span_id, anchor, text) in enumerate(spans)
        ]
        self.repo.save_extraction(
            WritingReferenceExtractionResult(
                artifact_id=artifact_id,
                project_id=PROJECT_ID,
                extraction_revision="extract_r1",
                parser_name="fake_parser",
                parser_version="1",
                page_count=len(spans),
                status="pending_visual_and_medical_structure_review",
                spans=extracted_spans,
            ),
            idempotency_key=f"seed-{artifact_id}-extract_r1",
        )
        self.repo.save_document_validation(
            WritingReferenceDocumentValidationRecord(
                validation_id=f"validation_{artifact_id}",
                project_id=PROJECT_ID,
                artifact_id=artifact_id,
                revision=1,
                status="confirmed",
                document_sha256=artifact_hash,
                extraction_revision="extract_r1",
                source_state_revision=1,
                summary="Current file content was confirmed for scope-chain testing.",
                actor="medical_manager",
                created_at=NOW,
            ),
            expected_revision=0,
            idempotency_key=f"seed-{artifact_id}-validation",
        )
        self.repo.record_extraction_review(
            project_id=PROJECT_ID,
            artifact_id=artifact_id,
            extraction_revision="extract_r1",
            decision="approved",
            confirmed_anchor_coverage=sorted({anchor for _, anchor, _ in spans}),
            unresolved_structure_issues=[],
            comment="Fake medical structure review for scope-chain testing.",
            actor="medical_manager",
            expected_revision=0,
            idempotency_key=f"seed-{artifact_id}-structure-review",
        )
        return artifact

    def _batch_with_both_scopes_failed(self) -> object:
        """One batch spanning two nct_ids; every item structural-failed."""
        self._seed_artifact(
            "artifact_scope_a",
            self.nct_a,
            [
                ("span_scope_a_1", "eligibility", "Adults with moderate asthma may enroll."),
                ("span_scope_a_2", "safety", "Safety assessments run through Week 24."),
            ],
        )
        self._seed_artifact(
            "artifact_scope_b",
            self.nct_b,
            [
                ("span_scope_b_1", "eligibility", "Adults with severe asthma may enroll."),
                ("span_scope_b_2", "safety", "Safety labs are collected at Week 12."),
            ],
        )
        batch = self.service.create(
            PROJECT_ID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SNAPSHOT_ID,
                glossary_version=GLOSSARY_VERSION,
                anchor_filter=[],
                actor="medical_manager",
                idempotency_key="scope-chain-create-01",
            ),
        )
        self.assertEqual(4, len(batch.items))
        by_artifact = defaultdict(list)
        for item in batch.items:
            by_artifact[item.artifact_id].append(item)
        for items in by_artifact.values():
            for index, item in enumerate(items):
                updated = item.model_copy(
                    update={
                        "generation_status": "failed_retryable",
                        "error_code": "document_plan_failed",
                        "document_plan_failure_codes": list(STRUCTURAL_CODES),
                        "document_plan_failure_source_stage_run_id": "",
                        "document_plan_failure_is_derived": index != 0,
                    },
                    deep=True,
                )
                with self.repo._connect() as connection:
                    cursor = connection.execute(
                        """
                        UPDATE writing_reference_translation_batch_items
                        SET generation_status='failed_retryable', payload_json=?
                        WHERE tenant_id=? AND project_id=? AND item_id=?
                        """,
                        (
                            json.dumps(
                                updated.model_dump(mode="json"),
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            TENANT_ID,
                            PROJECT_ID,
                            item.item_id,
                        ),
                    )
                    assert cursor.rowcount == 1
                    connection.commit()
        with self.repo._connect() as connection:
            connection.execute(
                """
                UPDATE writing_reference_translation_batches
                SET status='failed'
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                """,
                (TENANT_ID, PROJECT_ID, batch.batch_id),
            )
            connection.commit()
        return batch

    def test_a516_scoped_commands_converge_without_spurious_conflict(self) -> None:
        batch = self._batch_with_both_scopes_failed()
        items_by_span = {item.span_id: item for item in batch.items}
        scope_a_ids = sorted(
            [
                items_by_span["span_scope_a_1"].item_id,
                items_by_span["span_scope_a_2"].item_id,
            ]
        )
        scope_b_ids = sorted(
            [
                items_by_span["span_scope_b_1"].item_id,
                items_by_span["span_scope_b_2"].item_id,
            ]
        )

        captured_jobs = []

        class _CapturingDurableStore:
            def create_or_reuse(self, durable_request):
                captured_jobs.append(durable_request)
                return SimpleNamespace(
                    job_id=f"durable_scope_job_{len(captured_jobs):03d}"
                )

        self.service.attach_durable_store(_CapturingDurableStore())

        # 命令一：scope=[nct_a]。授权范围内的命令必须走 202/running 语义，
        # 即使范围外的失败项会分配 planning lineage（修复前这里 409）。
        retried_a = self.service.retry(
            PROJECT_ID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="scope-chain-retry-a-01",
                nct_ids=[self.nct_a],
            ),
        )
        # 修复前：上一行 service.retry(...) 直接抛
        # WritingReferenceConflictError("document-plan contract transition
        # changed after preflight") —— 反例红。
        self.assertEqual("running", retried_a.status)
        self.assertEqual(1, len(captured_jobs))
        payload_a = json.loads(captured_jobs[0].payload_json)
        self.assertEqual(scope_a_ids, sorted(payload_a["failed_item_ids"]))
        after_a = self.service.get(PROJECT_ID, batch.batch_id)
        by_id_a = {item.item_id: item for item in after_a.items}
        for item_id in scope_a_ids:
            self.assertEqual(
                2, by_id_a[item_id].document_plan_retry_generation
            )
        for item_id in scope_b_ids:
            self.assertEqual(
                0, by_id_a[item_id].document_plan_retry_generation
            )

        # 命令二：scope=[nct_b]。batch 仍持有多范围失败项（范围外的 A 项
        # 保持 failed_retryable 不被命令一触碰），必须同样收敛。
        with self.repo._connect() as connection:
            connection.execute(
                """
                UPDATE writing_reference_translation_batches
                SET status='failed'
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                """,
                (TENANT_ID, PROJECT_ID, batch.batch_id),
            )
            connection.commit()
        retried_b = self.service.retry(
            PROJECT_ID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="scope-chain-retry-b-01",
                nct_ids=[self.nct_b],
            ),
        )
        self.assertEqual("running", retried_b.status)
        self.assertEqual(2, len(captured_jobs))
        payload_b = json.loads(captured_jobs[1].payload_json)
        self.assertEqual(scope_b_ids, sorted(payload_b["failed_item_ids"]))
        after_b = self.service.get(PROJECT_ID, batch.batch_id)
        by_id_b = {item.item_id: item for item in after_b.items}
        for item_id in scope_b_ids:
            self.assertEqual(
                3, by_id_b[item_id].document_plan_retry_generation
            )
        for item_id in scope_a_ids:
            self.assertEqual(
                2, by_id_b[item_id].document_plan_retry_generation
            )

        # 审计只记录本命令授权的范围集合（两条命令各一条审计）。
        with self.repo._connect() as connection:
            rows = connection.execute(
                """
                SELECT detail_json FROM writing_reference_audit_chain
                WHERE tenant_id=? AND project_id=? AND event_type='translation_batch_retry_requested'
                ORDER BY sequence_no
                """,
                (TENANT_ID, PROJECT_ID),
            ).fetchall()
        self.assertEqual(2, len(rows))
        self.assertEqual(
            scope_a_ids,
            sorted(json.loads(rows[0]["detail_json"])["failed_item_ids"]),
        )
        self.assertEqual(
            scope_b_ids,
            sorted(json.loads(rows[1]["detail_json"])["failed_item_ids"]),
        )

    def test_a517_unscoped_command_still_covers_both_scopes(self) -> None:
        """空范围 = 全量：一条不带 nct_ids 的命令仍覆盖两个研究的失败项。"""
        batch = self._batch_with_both_scopes_failed()
        all_ids = sorted(item.item_id for item in batch.items)
        retried = self.service.retry(
            PROJECT_ID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="scope-chain-retry-all-01",
            ),
        )
        self.assertEqual("running", retried.status)
        by_id = {item.item_id: item for item in retried.items}
        for item_id in all_ids:
            self.assertEqual(
                2, by_id[item_id].document_plan_retry_generation
            )


if __name__ == "__main__":
    unittest.main()
