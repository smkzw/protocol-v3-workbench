from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend" / "src" / "App.jsx"


class FrontendPlannedReadIdentityVisibleUxContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_SOURCE.read_text(encoding="utf-8")
        match = re.search(r"function PlannedModulePage\(.*?function ApprovalPage", cls.source, re.S)
        if match is None:
            raise AssertionError("PlannedModulePage block not found")
        cls.planned = match.group(0)

    def _assert_visible_fail_closed(self, function_name: str, next_function: str, guard: str, message: str, clear_state: str):
        match = re.search(
            rf"{re.escape(function_name)}.*?{re.escape(next_function)}",
            self.planned,
            re.S,
        )
        self.assertIsNotNone(match, function_name)
        block = match.group(0)
        self.assertIn(guard, block)
        self.assertIn(message, block)
        self.assertIn(clear_state, block)

    def test_source_and_evidence_reads_clear_stale_state_and_show_identity_error(self):
        self._assert_visible_fail_closed(
            "const refreshSources =",
            "const refreshEvidenceManifest =",
            "data?.project_id !== plannedModuleProjectIdRef.current",
            "原始资料登记响应项目身份不匹配，已阻止写入当前模块。",
            "setRegistry({ entries: [], spans: [], content_validations: [] });",
        )
        self._assert_visible_fail_closed(
            "const refreshEvidenceManifest =",
            "const refreshTflManifest =",
            "data?.project_id !== plannedModuleProjectIdRef.current",
            "竞品证据清单响应项目身份不匹配，已阻止写入当前模块。",
            "setEvidenceManifest(null);",
        )

    def test_tfl_and_safety_reads_clear_stale_state_and_show_identity_error(self):
        self._assert_visible_fail_closed(
            "const refreshTflManifest =",
            "const refreshTflReviewWorkbench =",
            "data?.project_id !== plannedModuleProjectIdRef.current",
            "TFL清单响应项目身份不匹配，已阻止写入当前模块。",
            "setTflManifest(null);",
        )
        self._assert_visible_fail_closed(
            "const refreshTflReviewWorkbench =",
            "useEffect(() => {\n    if (moduleKey === \"tfl\"",
            "data?.project_id !== plannedModuleProjectIdRef.current",
            "TFL审阅工作台响应项目身份不匹配，已阻止写入当前模块。",
            "setTflReviewWorkbench(null);",
        )
        self._assert_visible_fail_closed(
            "const refreshSafetyManifest =",
            "const refreshSafetyReviewWorkbench =",
            "data?.project_id !== projectId",
            "安全资料清单响应项目身份不匹配，已阻止写入当前模块。",
            "setSafetyManifest(null);",
        )
        self._assert_visible_fail_closed(
            "const refreshSafetyReviewWorkbench =",
            "const refreshSafetyHandoff =",
            "data?.project_id !== plannedModuleProjectIdRef.current",
            "安全信号审阅工作台响应项目身份不匹配，已阻止写入当前模块。",
            "setSafetyReviewWorkbench(null);",
        )
        self._assert_visible_fail_closed(
            "const refreshSafetyHandoff =",
            "useEffect(() => {\n    if (moduleKey === \"safety\"",
            "data?.project_id !== projectId",
            "PV协同交接响应项目身份不匹配，已阻止写入当前模块。",
            "setSafetyHandoffManifest(null);",
        )


if __name__ == "__main__":
    unittest.main()
