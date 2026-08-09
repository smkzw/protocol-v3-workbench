from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend" / "src" / "App.jsx"


class FrontendProjectScopedActionIdentityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_SOURCE.read_text(encoding="utf-8")

    def test_overview_mark_read_requires_identity_and_surfaces_failure(self):
        match = re.search(r"function OverviewPage\(.*?function AiGatewayPanel", self.source, re.S)
        self.assertIsNotNone(match)
        overview = match.group(0)
        guard = "data?.project_id !== projectId"
        self.assertIn(guard, overview)
        self.assertIn("总览收件箱响应项目身份不匹配，未更新当前收件箱。", overview)
        self.assertIn('className="gate-error overview-action-error"', overview)
        self.assertIn('role="alert"', overview)
        self.assertLess(overview.index(guard), overview.index("refreshWorkbenchInbox?.(data)"))

    def test_source_registration_and_ai_run_require_current_project_before_success(self):
        match = re.search(r"function PlannedModulePage\(.*?function ApprovalPage", self.source, re.S)
        self.assertIsNotNone(match)
        planned = match.group(0)

        registration_guard = "payload?.entry?.project_id !== plannedModuleProjectIdRef.current"
        self.assertIn(registration_guard, planned)
        self.assertIn("原始资料登记响应项目身份不匹配，未更新当前项目登记。", planned)
        self.assertLess(planned.index(registration_guard), planned.index("setMessage(`${candidate.title} 已登记"))

        ai_guard = "payload?.project_id !== plannedModuleProjectIdRef.current"
        self.assertIn(ai_guard, planned)
        self.assertIn("AI任务响应项目身份不匹配，未更新当前项目任务状态。", planned)
        self.assertLess(planned.index(ai_guard), planned.index("AI 任务已建立"))


if __name__ == "__main__":
    unittest.main()
