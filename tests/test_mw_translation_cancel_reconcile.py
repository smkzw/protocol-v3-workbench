"""自检第1次红节点④根因修复（20261015）：翻译批次与durable作业状态不对账。

现场实据（proj_user_333afc0399e6 / SMOKE-r1-1 口服sGC刺激剂·HFrEF·II期）：
运维帽合法 cancel（POST /jobs/mwjob_669db92acc908aeb07ee1393/cancel →
200 cancelled；DB 实读 durable_mw_jobs.status='cancelled'），但批次记录
wref_translation_batch_16f18ac94eeb2388d33dca80 的
writing_reference_translation_batches.status 恒为 'running'（135 pending +
1 running 悬置，updated_at 冻结在 cancel 之前）。后果链：
  1. 前端按 active（accepted/running）永久轮询"生成中"，永不收敛；
  2. 一键确认/仅重试失败项全部被 active 门禁禁用——10 条合格候选
     （pending_author_confirmation_count=10 实读）无法处置，死路；
  3. 后端日志（t17_round27_loop/backend_5301_restart_after_selfcheck4_
     fixes.log 尾部）只有该批次的无限 GET 轮询，没有任何 POST 到达。

修复契约（反例先证红再修；修链路功能，不是测试绕过）：
批次读取（service.get，与既有 stale-running 回收同一边界）作为对账点——
主作业已 cancelled 且该批次无任何在途作业（重试/下游迁移）时：
  - 未完成条目（pending/running）回退 failed_retryable
    （error_code=cancelled_by_user，人话 error_detail）；
  - 批次聚合回终态（partial_failure/failed/completed…），UI 停止轮询；
  - 已生成候选保持可确认，『仅重试失败项』即恢复生成；
  - 审计留痕 translation_batch_cancelled_reconcile。
作业在途（queued/running/retry_wait）时绝不对账（活worker负责终态）。
"""

from __future__ import annotations

import json
from pathlib import Path

from packages.contracts.workbench_contracts.models import (
    WritingReferenceTranslationBatchRetryRequest,
)
from services.api.app.medical_writing_durable_jobs import (
    DurableJobStore,
)
from tests.test_writing_reference_translation_batch import (
    NOW,
    PROJECT_ID,
    WritingReferenceTranslationBatchTests,
)

TERMINAL_BATCH_STATUSES = {
    "completed",
    "completed_with_blocked",
    "partial_failure",
    "failed",
}


class CancelReconcileTests(WritingReferenceTranslationBatchTests):
    def setUp(self) -> None:
        super().setUp()
        self.durable = DurableJobStore(
            Path(self.tmp.name) / "durable_mw_jobs.sqlite3"
        )
        self.service.attach_durable_store(self.durable)

    def _seed_batch_with_pending_item(self, key: str) -> str:
        self._seed_artifact(
            f"artifact_cancel_{key[-6:]}",
            [
                (
                    f"span_cancel_target_{key[-6:]}",
                    "endpoints",
                    "The endpoint is assessed at Week 16.",
                )
            ],
        )
        batch = self.service.create(PROJECT_ID, self._create_request(key))
        return batch.batch_id

    def _batch_item_statuses(self, batch_id: str) -> list[str]:
        return [
            item.generation_status
            for item in self.service.get(PROJECT_ID, batch_id).items
        ]

    # -- 反例1（红）：cancel 后批次必须经读取对账回终态 -------------------

    def test_cancelled_job_reconciles_batch_on_read(self):
        batch_id = self._seed_batch_with_pending_item("cancel-reconcile-1")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch_id, actor="medical_manager"
        )
        cancel_result = self.durable.cancel(PROJECT_ID, job_id)
        self.assertTrue(cancel_result.cancelled)

        batch = self.service.get(PROJECT_ID, batch_id)

        self.assertIn(
            batch.status,
            TERMINAL_BATCH_STATUSES,
            "主作业已 cancelled 且无在途作业时，批次读取必须对账回终态；"
            "现场实据：批次恒 running，UI 永久轮询生成中（死路）。",
        )
        for item in batch.items:
            if item.generation_status == "excluded":
                continue
            self.assertEqual(
                "failed_retryable",
                item.generation_status,
                "取消后未完成条目必须回退可重试态，否则既不能确认也不能重试。",
            )
            self.assertEqual("cancelled_by_user", item.error_code)

    def test_cancel_reconcile_is_idempotent_and_audited(self):
        batch_id = self._seed_batch_with_pending_item("cancel-reconcile-idem")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch_id, actor="medical_manager"
        )
        self.durable.cancel(PROJECT_ID, job_id)

        first = self.service.get(PROJECT_ID, batch_id)
        second = self.service.get(PROJECT_ID, batch_id)

        self.assertEqual(first.status, second.status)
        self.assertEqual(
            self._batch_item_statuses(batch_id),
            [item.generation_status for item in second.items],
            "对账必须幂等：反复读取不得反复改写条目。",
        )
        with self.repo._connect() as connection:
            rows = connection.execute(
                """
                SELECT COUNT(*) AS n FROM writing_reference_audit_chain
                WHERE project_id=? AND event_type='translation_batch_cancelled_reconcile'
                  AND target_id=?
                """,
                (PROJECT_ID, batch_id),
            ).fetchone()
        self.assertGreaterEqual(rows["n"], 1, "对账必须留审计痕迹。")

    # -- 反例2（红）：对账后既有『仅重试失败项』链路必须能恢复生成 --------

    def test_reconciled_items_resume_via_failed_retry(self):
        batch_id = self._seed_batch_with_pending_item("cancel-resume-1")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch_id, actor="medical_manager"
        )
        self.durable.cancel(PROJECT_ID, job_id)
        healed = self.service.get(PROJECT_ID, batch_id)
        self.assertIn(healed.status, TERMINAL_BATCH_STATUSES)

        self.service.retry(
            PROJECT_ID,
            batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="cancel-resume-1",
            ),
        )
        self.service.run_failed(PROJECT_ID, batch_id, "medical_manager")

        resumed = self.service.get(PROJECT_ID, batch_id)
        self.assertEqual(
            "candidate_ready",
            resumed.items[0].generation_status,
            "对账回退的条目必须能经既有『重试+run_failed』链路恢复生成"
            "（fixture 确定性管线；现场同型=界面『仅重试失败项』）。",
        )

    # -- 守卫（设计即绿）：在途作业存在时绝不对账 -------------------------

    def test_active_retry_job_blocks_reconcile(self):
        batch_id = self._seed_batch_with_pending_item("cancel-guard-retry")
        job_id = self.service.ensure_reference_translation_job(
            PROJECT_ID, batch_id, actor="medical_manager"
        )
        self.durable.cancel(PROJECT_ID, job_id)
        # 模拟用户已点了『仅重试失败项』：批次的重试作业仍在途（queued）。
        from packages.contracts.workbench_contracts.models import (
            DurableJobCreateRequest,
        )

        self.durable.create_or_reuse(
            DurableJobCreateRequest(
                project_id=PROJECT_ID,
                job_type="reference_translation",
                business_key=f"{batch_id}:retry:guard-key",
                request_hash="guard-hash",
                payload_json=json.dumps({"batch_id": batch_id, "retry": True}),
                created_by="medical_manager",
            )
        )

        batch = self.service.get(PROJECT_ID, batch_id)

        self.assertNotIn(
            "failed_retryable",
            self._batch_item_statuses(batch_id),
            "存在在途重试作业时不得对账改写条目（活worker负责终态）。",
        )

    def test_running_main_job_never_reconciles(self):
        batch_id = self._seed_batch_with_pending_item("cancel-guard-running")
        self.service.ensure_reference_translation_job(
            PROJECT_ID, batch_id, actor="medical_manager"
        )

        batch = self.service.get(PROJECT_ID, batch_id)

        self.assertIn("pending", self._batch_item_statuses(batch_id))
        self.assertNotIn(batch.status, TERMINAL_BATCH_STATUSES)


if __name__ == "__main__":
    import unittest

    unittest.main()
