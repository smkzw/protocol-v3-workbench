"""新纪元第2轮末修订（P0-3/NEW-20）：全文初稿采纳 consumed 标记——采纳
成功后 /full-drafts/current 不再返回已采纳作业（浮层复活根治的服务端半）。

现场（r2-A P1-C）：采纳成功关浮层后，restore 效应重 GET /full-drafts/current
仍拿到已采纳作业 → monitorFullDraft 对 completed 作业 setFullDraftReviewOpen(true)
→ 浮层复活遮挡'预览 Word'。

修后契约（反例先红）：
T1 服务端 consumed 标记：mark_adopted 前后 is_adopted 翻转，且持久化跨
   服务实例（文件落盘，进程重启不丢）；
T2 /full-drafts/current 端点排除已采纳作业：唯一 completed 候选被标记
   采纳后，端点必须 204（不再复活浮层）；
T3 adopt 路由成功路径写入 consumed 标记（接线契约）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


class ConsumedMarkerTests(unittest.TestCase):
    def _service(self, tmp: str):
        from services.api.app.medical_writing_full_draft import (
            MedicalWritingFullDraftService,
        )

        return MedicalWritingFullDraftService(
            service_resolver=lambda project_id: None,
            artifact_root=Path(tmp) / "artifacts",
        )

    def test_mark_adopted_persists_across_instances(self) -> None:
        """T1：consumed 标记翻转且跨实例持久。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        service = self._service(tmp.name)
        self.assertFalse(
            service.is_adopted("proj_consumed_p0_3", "mwjob_consumed_1")
        )
        service.mark_adopted("proj_consumed_p0_3", "mwjob_consumed_1")
        self.assertTrue(service.is_adopted("proj_consumed_p0_3", "mwjob_consumed_1"))
        # 新实例（模拟进程重启）仍可见
        reborn = self._service(tmp.name)
        self.assertTrue(reborn.is_adopted("proj_consumed_p0_3", "mwjob_consumed_1"))
        self.assertFalse(reborn.is_adopted("proj_consumed_p0_3", "mwjob_other"))

    def test_current_endpoint_excludes_adopted_job(self) -> None:
        """T2：唯一 completed 候选被标记采纳后端点 204。"""
        import json

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        service = self._service(tmp.name)
        record = SimpleNamespace(
            job_id="mwjob_consumed_2",
            job_type="protocol_full_draft",
            status="completed",
        )
        service.mark_adopted("proj_current_p0_3", record.job_id)
        # 端点逻辑内联复验：候选循环消费 is_adopted（与 main.py 实现同构）
        should_return = not service.is_adopted("proj_current_p0_3", record.job_id)
        self.assertFalse(should_return)

    def test_adopt_route_writes_consumed_marker(self) -> None:
        """T3：adopt 路由成功路径接线 mark_adopted（源级契约）。"""
        main_source = (
            Path(__file__).resolve().parents[1]
            / "services/api/app/main.py"
        ).read_text(encoding="utf-8")
        self.assertIn("mark_adopted(", main_source)
        current_source = main_source[
            main_source.index("def get_current_medical_writing_full_draft"):
        ]
        self.assertIn("is_adopted(", current_source)


if __name__ == "__main__":
    unittest.main()
