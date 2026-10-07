"""R27 自检（20261005）节点③残留产品缺陷：翻译条目卡死 running 无自愈。

现场（SMOKE-r2-1Q proj_user_ed22b8071d6b）：批次重试后 1 项悬置
running >30 分钟（attempt 2/3 卡在 20/20 后处理）——worker 早已不存在，
条目仍 generation_status='running'（DB 实读：item 0bb0ba57… 自
2026-10-04T18:46 起 running，pipeline_stage=translating_hy_mt2），后续
重试入口只认 pending/failed_retryable，该条目永远无法被重新认领，
批次也无法回到终态。

根因（生成层16项失败的调度器部分已由主会话 a1268ca 串行根治修复，
本文件只清偿产品侧残留）：条目 claim 后无租约时限、无 stale-running
回收路径。

修复契约（红先修后）：批次读取（service.get）作为确定性自愈边界：
running 条目 updated_at 超过阈值（默认30分钟=最长单条目正常耗时的
数倍冗余）且该批次没有在途 durable 作业时，回退为 failed_retryable
（error_code=reclaimed_stale_running，审计留痕），可被既有『仅重试
失败项』入口重新认领；新鲜 running 条目不动（活worker在跑）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.test_writing_reference_translation_batch import (
    NOW,
    PROJECT_ID,
    WritingReferenceTranslationBatchTests,
)

STALE_RUNNING_SECONDS = 30 * 60


class StaleRunningReclaimTests(WritingReferenceTranslationBatchTests):
    def _force_item_state(
        self,
        batch_id: str,
        item_index: int,
        *,
        status: str,
        updated_at: datetime,
        attempt: int = 1,
        stage: str = "translating_hy_mt2",
    ) -> str:
        batch = self.service.get(PROJECT_ID, batch_id)
        item = batch.items[item_index]
        payload = item.model_dump(mode="json")
        payload["pipeline_stage"] = stage
        payload["generation_status"] = status
        payload["attempt"] = attempt
        with self.repo._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE writing_reference_translation_batch_items
                SET generation_status=?, attempt=?, payload_json=?, updated_at=?
                WHERE tenant_id=? AND project_id=? AND batch_id=? AND item_id=?
                """,
                (
                    status,
                    attempt,
                    __import__("json").dumps(payload, ensure_ascii=False),
                    updated_at.isoformat(),
                    "kangzhe_local",
                    PROJECT_ID,
                    batch_id,
                    item.item_id,
                ),
            )
            connection.commit()
        return item.item_id

    def _seed_batch_with_pending_item(self, key: str) -> str:
        self._seed_artifact(
            f"artifact_reclaim_{key[-6:]}",
            [("span_reclaim_target", "endpoints", "The endpoint is assessed at Week 16.")],
        )
        batch = self.service.create(PROJECT_ID, self._create_request(key))
        return batch.batch_id

    def test_stale_running_item_is_reclaimed_on_batch_read(self):
        batch_id = self._seed_batch_with_pending_item("reclaim-stale-1")
        item_id = self._force_item_state(
            batch_id,
            0,
            status="running",
            # 夹具服务时钟冻结于 NOW：时间基准必须与之一致。
            updated_at=NOW
            - timedelta(seconds=STALE_RUNNING_SECONDS + 600),
        )

        batch = self.service.get(PROJECT_ID, batch_id)

        item = next(i for i in batch.items if i.item_id == item_id)
        self.assertEqual(
            "failed_retryable",
            item.generation_status,
            "卡死 running（>30分钟且无在途作业）的条目必须在批次读取时自愈回"
            "可重试态，否则永远无法被重新认领（现场悬置>30分钟实据）。",
        )
        self.assertEqual("reclaimed_stale_running", item.error_code)

    def test_fresh_running_item_is_left_alone(self):
        batch_id = self._seed_batch_with_pending_item("reclaim-fresh-1")
        item_id = self._force_item_state(
            batch_id,
            0,
            status="running",
            updated_at=NOW - timedelta(seconds=60),
        )

        batch = self.service.get(PROJECT_ID, batch_id)

        item = next(i for i in batch.items if i.item_id == item_id)
        self.assertEqual(
            "running",
            item.generation_status,
            "新鲜 running 条目（活 worker 处理中，单条目正常可达数分钟）"
            "不得被回收。",
        )

    def test_reclaimed_item_is_covered_by_failed_retry(self):
        """回收后『仅重试失败项』入口必须能重新认领该条目。"""
        batch_id = self._seed_batch_with_pending_item("reclaim-retry-1")
        self._force_item_state(
            batch_id,
            0,
            status="running",
            # 夹具服务时钟冻结于 NOW：时间基准必须与之一致。
            updated_at=NOW
            - timedelta(seconds=STALE_RUNNING_SECONDS + 600),
        )
        healed = self.service.get(PROJECT_ID, batch_id)
        self.assertEqual(
            "failed_retryable", healed.items[0].generation_status
        )
        from packages.contracts.workbench_contracts.models import (
            WritingReferenceTranslationBatchRetryRequest,
        )

        self.service.retry(
            PROJECT_ID,
            batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="reclaim-retry-1",
            ),
        )
        self.service.run_failed(PROJECT_ID, batch_id, "medical_manager")
        retried = self.service.get(PROJECT_ID, batch_id)
        self.assertEqual(
            "candidate_ready",
            retried.items[0].generation_status,
            "回收条目经既有『重试+run_failed』入口应完成正常翻译"
            "（fixture 确定性管线；现场同一路径=界面『仅重试失败项』）。",
        )


if __name__ == "__main__":
    unittest.main()
