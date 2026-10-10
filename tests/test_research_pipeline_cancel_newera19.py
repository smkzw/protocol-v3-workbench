"""新纪元第3轮修订 P0：NEW-19 研究流水线取消三件套（反例先红）。

现场（r2-A，NEW-19）：点'取消研究流水线'后标签变'已取消56%'但批次继续跑
（租约仍有效、心跳续租），随后取消按钮从 DOM 消失成僵尸态无法再取消。
根因（medical_writing_research_pipeline.py:791-800 旧实现）：cancel() 仅置
cancel_requested + 改 stage='cancelled'，从不吊销 durable 编排作业租约；
且 cancelled 属 TERMINAL_STAGES，二次 cancel() 早退。

三件套契约（红先修后）：
T1 租约吊销——cancel() 必须对 state.job_id 调 durable_store.cancel
   （清空 claim_token → worker cancel_check 失效 → 下一个检查点硬停）；
T2 真实存储收敛——真实 DurableJobStore 上：claim 中的作业在 cancel 后
   check_ownership 必须为 False（worker 停止依据），job 状态收敛为
   cancelled 且不可再被认领；
T3 清理二次入口——已 cancelled 态：不带 force 的 cancel 早退（幂等）；
   force_cleanup=True 的 cancel 幂等重吊销租约并把'确认终止并清理'写进
   detail（僵尸态可消费）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


PROJECT_ID = "proj_cancel_newera19"


class _StubJourney:
    def __init__(self, research_pipeline=None):
        self.research_pipeline = research_pipeline
        self.corpus_gate = None
        self.framing = None
        self.picos = None


class _StubJourneyService:
    def __init__(self, journey):
        self._journey = journey

    def get(self, project_id):
        assert project_id == PROJECT_ID
        return self._journey

    def save_research_pipeline(self, project_id, payload):
        object.__setattr__(self._journey, "research_pipeline", payload)


class _StubCorpusAi:
    pass


def _make_service(journey, durable_store):
    from services.api.app.medical_writing_research_pipeline import (
        MedicalWritingResearchPipelineService,
    )

    return MedicalWritingResearchPipelineService(
        journey_service=_StubJourneyService(journey),
        discovery_service=None,
        triage_service=None,
        preparation_batch_service=None,
        translation_batch_service=None,
        corpus_readiness_service=None,
        china_client_factory=lambda: None,
        durable_store=durable_store,
        durable_worker=None,
        corpus_analysis_ai_service=_StubCorpusAi(),
    )


def _running_journey(job_id: str) -> _StubJourney:
    return _StubJourney(
        research_pipeline={
            "schema_version": "research_pipeline_v6",
            "pipeline_id": "pipe_newera19",
            "project_id": PROJECT_ID,
            "job_id": job_id,
            "stage": "triaging",
            "percent": 56,
            "cancel_requested": False,
        }
    )


class CancelLeaseRevocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from services.api.app.medical_writing_durable_jobs import DurableJobStore

        self.store = DurableJobStore(Path(self.tmp.name) / "durable.sqlite3")
        self.journey = _running_journey("job_newera19_cancel")
        self.service = _make_service(self.journey, self.store)

    def _seed_claimed_job(self):
        from services.api.app.medical_writing_durable_jobs import (
            DurableJobCreateRequest,
        )

        created = self.store.create_or_reuse(
            DurableJobCreateRequest(
                project_id=PROJECT_ID,
                job_type="research_pipeline_orchestrator",
                business_key="research-pipeline:proj_cancel_newera19:pipe_newera19",
                request_hash="a" * 64,
                input_hash="a" * 64,
                payload_json="{}",
                created_by="research_pipeline",
                max_attempts=3,
                provider="workbench",
                model="research_pipeline_orchestrator",
            )
        )
        job_id = created.job_id
        # 把编排作业 id 回填进流水线状态（真实 start() 同款接线）。
        self.journey.research_pipeline["job_id"] = job_id
        claim = self.store.claim(PROJECT_ID, job_id)
        self.assertTrue(claim.claimed)
        return job_id, claim

    def test_cancel_revokes_durable_lease(self) -> None:
        job_id, claim = self._seed_claimed_job()
        self.assertTrue(
            self.store.check_ownership(PROJECT_ID, job_id, claim.claim_token)
        )
        state = self.service.cancel(PROJECT_ID, actor="tester")
        # T1：取消后 worker 的停止依据（check_ownership）必须立即失效。
        self.assertFalse(
            self.store.check_ownership(PROJECT_ID, job_id, claim.claim_token),
            "cancel() 未吊销 durable 编排作业租约——在途批次将继续增长。",
        )
        self.assertTrue(state.cancel_requested)
        self.assertEqual("cancelled", state.stage)

    def test_cancelled_job_converges_and_cannot_be_reclaimed(self) -> None:
        job_id, _claim = self._seed_claimed_job()
        self.service.cancel(PROJECT_ID, actor="tester")
        status = self.store.get(PROJECT_ID, job_id)
        self.assertEqual("cancelled", status.status)
        reclaim = self.store.claim(PROJECT_ID, job_id)
        self.assertFalse(reclaim.claimed, "已取消作业不得再被认领（批次计数必须收敛）。")


class CancelledStateCleanupEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from services.api.app.medical_writing_durable_jobs import DurableJobStore

        self.store = DurableJobStore(Path(self.tmp.name) / "durable.sqlite3")
        self.journey = _running_journey("job_newera19_zombie")
        self.service = _make_service(self.journey, self.store)

    def test_plain_cancel_on_cancelled_state_is_idempotent_noop(self) -> None:
        self.service.cancel(PROJECT_ID, actor="tester")
        before = self.store.count_active_cancels() if hasattr(self.store, "count_active_cancels") else None
        state = self.service.cancel(PROJECT_ID, actor="tester")
        self.assertEqual("cancelled", state.stage)
        self.assertNotIn("确认终止并清理", state.detail or "")

    def test_force_cleanup_consumes_zombie_state(self) -> None:
        self.service.cancel(PROJECT_ID, actor="tester")
        state = self.service.cancel(
            PROJECT_ID, actor="tester", force_cleanup=True
        )
        self.assertEqual("cancelled", state.stage)
        self.assertIn("确认终止并清理", state.detail or "")


if __name__ == "__main__":
    unittest.main()
