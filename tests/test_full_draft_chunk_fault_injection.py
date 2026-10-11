"""新纪元第1轮末修订（P1-6/E8收臂）：全文初稿批次故障注入——507/空回包
容量类失败下：批次跳过 + 整单续跑 + 退避重试 + 跳过行内可见。

取证口径（收臂）：结构性证据（分类器/跳过分支）已有单测
（test_mw_full_draft_chunk_skip_r6.py）；本文件补端到端注入证据——
mock provider 对指定批次的每次请求都抛 HTTP 507（capacity），对其余
批次正常返回，跑完整 execute：
- 作业完成（不弃单），成功批次的节候选完整入工件；
- 失败批被记入 artifact.skipped_chunks（chunk_index/section_ids/reason/
  failure_class=capacity/attempts），coverage.skipped_section_ids 同步；
- 批次层退避确实发生（time.sleep 调用记录）；
- 心跳进度消息含『已跳过』（UI 跳过行内可见的取数源，P1-45 进度卡消费）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from packages.contracts.workbench_contracts import AiTaskSourceRef
from services.api.app.ai_gateway import AiProviderRuntimeError
from services.api.app.medical_writing_full_draft import (
    FULL_DRAFT_PROMPT_VERSION,
    MedicalWritingFullDraftService,
    ProtocolFullDraftExecutor,
)
from services.api.app.medical_writing_durable_jobs import DurableJobStore
from tests.test_medical_writing_full_draft import (
    _FakeFullDraftRunner,
    _FakeRepo,
)


class _FaultyChunkRunner(_FakeFullDraftRunner):
    """对含指定节的每次提交都抛 HTTP 507（capacity）；其余批次正常返回。"""

    def __init__(self, failing_section: str = "sec_2"):
        super().__init__()
        self.failing_section = failing_section
        self.capacity_calls: list[str] = []

    def submit_internal(self, project_id, request):
        section_ids = list(request.task_context["section_ids"])
        if self.failing_section in section_ids:
            self.capacity_calls.append(",".join(section_ids))
            raise AiProviderRuntimeError(
                "AI provider request failed: HTTP 507",
                diagnostics={
                    "failure_code": "provider_http_error",
                    "http_status": 507,
                },
            )
        return super().submit_internal(project_id, request)


def _service_with(repo, runner):
    policy = {
        "provider_name": "buddy",
        "model_name": "deepseek-v4-pro",
        "route_identity_hash": "b" * 64,
        "prompt_version": FULL_DRAFT_PROMPT_VERSION,
    }
    source = AiTaskSourceRef(
        source_id="study_definition_fake",
        source_type="current_project_study_definition",
        title="已确认研究事实",
        locator="study_definition:sd_fake:revision:1",
        text_preview="适应症：哮喘\n研究分期：II期\n目标研究人群：成年受试者",
        project_id=repo.project_id,
        module="medical_writing",
    )
    service = SimpleNamespace(
        repo=repo,
        ai_task_runner=runner,
        _policy_identity=lambda task_type="medical_writing_revision": dict(policy),
        _current_project_study_definition_source=lambda protocol, section: source,
        _company_corpus_sources=lambda *args: [],
        _shared_corpus_sources=lambda *args: [],
    )
    return service


class FullDraftChunkFaultInjectionTests(unittest.TestCase):
    def test_507_batch_skipped_job_continues_with_evidence(self) -> None:
        import unittest.mock as _mock

        import services.api.app.medical_writing_full_draft as full_draft_module

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = _FakeRepo()
        runner = _FaultyChunkRunner(failing_section="sec_2")
        service = _service_with(repo, runner)
        full = MedicalWritingFullDraftService(
            service_resolver=lambda project_id: service,
            artifact_root=Path(tmpdir.name) / "artifacts",
        )
        store = DurableJobStore(Path(tmpdir.name) / "durable.sqlite3")
        project = repo.project_id
        # 两节分入两个批次（chunk_size=1）：507 只打 sec_2 批，sec_1 批正常
        # ——恰好复现现场'部分批次失败、其余批次继续'的 E8 形态。
        # patch 须覆盖 submit 与 execute 两段（chunk_size 参与 precondition
        # digest，执行期读取 expected["chunk_size"]）。
        sleeps: list[float] = []
        progress_messages: list[str] = []
        original_sleep = full_draft_module.time.sleep
        full_draft_module.time.sleep = lambda seconds: sleeps.append(seconds)
        try:
            with _mock.patch.object(full_draft_module, "FULL_DRAFT_CHUNK_SIZE", 1):
                job_id, _ = full.submit_durable(project, store)
                job = store.get(project, job_id)
                result = ProtocolFullDraftExecutor(full).execute(
                    job,
                    "claim",
                    lambda: False,
                    lambda progress: (
                        progress_messages.append(str(getattr(progress, "message", ""))),
                        True,
                    )[-1],
                )
        finally:
            full_draft_module.time.sleep = original_sleep
        self.assertEqual("", result.error, result)
        # 与真实 worker 一致地落终态（claim→complete），随后读工件取证。
        claim = store.claim(project, job_id)
        self.assertTrue(claim.claimed)
        store.complete(
            project,
            job_id,
            claim.claim_token,
            output_hash=result.output_hash,
            artifact_locator=result.artifact_locator,
            provider=result.provider,
            model=result.model,
            final_progress=result.progress,
        )

        self.assertFalse(getattr(result, "error", None) or result.error, result)
        artifact = full.read_artifact(project, store.get(project, job_id))
        self.assertTrue(artifact.get("sections"))
        surviving = {item["section_id"] for item in artifact["sections"]}
        self.assertIn("sec_1", surviving)
        self.assertNotIn("sec_2", surviving)

        skipped = artifact.get("skipped_chunks") or []
        self.assertEqual(1, len(skipped))
        record = skipped[0]
        self.assertIn("sec_2", record["section_ids"])
        self.assertEqual("capacity", record["failure_class"])
        self.assertIn("507", record["reason"])

        coverage = artifact.get("coverage") or {}
        self.assertIn("sec_2", coverage.get("skipped_section_ids") or [])

        # 批次层退避确实发生（1s/2s 小步退避，不阻塞其他批次）
        self.assertTrue(sleeps, "容量类重试应有批次层退避")
        self.assertTrue(any(seconds <= 2.0 for seconds in sleeps))

        # UI 跳过行内可见取数源：心跳消息点名跳过批次
        self.assertTrue(
            any("已跳过" in message for message in progress_messages),
            progress_messages[-6:],
        )

    def test_empty_provider_response_is_capacity_and_skipped(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            classify_full_draft_chunk_failure,
        )

        error = AiProviderRuntimeError(
            "AI provider returned an empty response",
            diagnostics={"failure_code": "provider_response_empty"},
        )
        self.assertEqual("capacity", classify_full_draft_chunk_failure(error))


if __name__ == "__main__":
    unittest.main()
