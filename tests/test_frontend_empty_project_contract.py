from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend" / "src" / "App.jsx"
STYLE_SOURCE = ROOT / "frontend" / "src" / "styles.css"


def source_between(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index + len(start))
    return source[start_index:end_index]


class FrontendEmptyProjectContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP_SOURCE.read_text(encoding="utf-8")
        cls.styles = STYLE_SOURCE.read_text(encoding="utf-8")
        cls.shell = source_between(cls.source, "function AppShell(", "function Metric(")
        cls.empty_overview = source_between(
            cls.source,
            "function EmptyProjectOverview(",
            "function AppShell(",
        )
        cls.app = cls.source[cls.source.index("export function App()") :]

    def test_empty_catalog_clears_active_project_and_blocks_project_requests(self) -> None:
        self.assertIn('const [activeProjectId, setActiveProjectId] = useState("");', self.app)
        self.assertIn("setActiveProjectId(\"\")", self.app)
        for endpoint in (
            "dashboard",
            "source-manifest",
            "ai-runs",
            "workbench-inbox",
        ):
            request = f"fetch(`/api/projects/${{activeProjectId}}/{endpoint}`)"
            request_index = self.app.index(request)
            guard_index = self.app.rfind("if (!activeProjectId)", 0, request_index)
            self.assertGreater(
                guard_index,
                self.app.rfind("useEffect(() =>", 0, request_index),
                f"{endpoint} request must be guarded by an active project",
            )

    def test_topbar_uses_explicit_empty_values_without_reference_fallbacks(self) -> None:
        for label in ("暂无项目", "暂无项目数据", "未选择项目"):
            self.assertIn(label, self.shell)
        self.assertIn("hasActiveProject", self.shell)
        self.assertIn("<EmptyProjectOverview", self.shell)
        for leaked_reference in ("特应性皮炎", "V1.3", "RUX listing 2025-06-12"):
            self.assertNotIn(leaked_reference, self.shell)
            self.assertNotIn(leaked_reference, self.empty_overview)

    def test_empty_overview_has_zero_state_and_primary_create_action(self) -> None:
        self.assertIn(
            'data-project-state={loading ? "loading" : unavailable ? "unavailable" : "empty"}',
            self.empty_overview,
        )
        self.assertIn("新建项目", self.empty_overview)
        self.assertIn('className="primary-button empty-project-create"', self.empty_overview)
        for metric in ("项目数", "模块进度", "开放风险", "待审批"):
            self.assertIn(metric, self.empty_overview)
        self.assertGreaterEqual(self.empty_overview.count('"0"'), 4)
        self.assertNotIn("module-row", self.empty_overview)
        self.assertNotIn("risk_counts_by_severity", self.empty_overview)
        self.assertIn(".empty-project-overview", self.styles)

    def test_ai_roles_can_be_configured_before_project_creation(self) -> None:
        self.assertIn("<AiGatewayPanel", self.empty_overview)
        self.assertIn("status={aiGatewayStatus}", self.empty_overview)
        self.assertIn("onStatusChange={onAiGatewayStatusChange}", self.empty_overview)
        self.assertIn("compact", self.empty_overview)
        self.assertIn("aiGatewayStatus={aiGatewayStatus}", self.shell)
        self.assertIn("onAiGatewayStatusChange={onAiGatewayStatusChange}", self.shell)
        self.assertIn(".empty-project-actions", self.styles)
        self.assertIn(".ai-gateway-card-compact", self.styles)
        status_request = 'fetch("/api/ai-gateway/status")'
        status_index = self.app.index(status_request)
        status_effect_start = self.app.rfind("useEffect(() =>", 0, status_index)
        status_effect_end = self.app.index("}, []);", status_index)
        status_effect = self.app[status_effect_start:status_effect_end]
        self.assertNotIn("if (!activeProjectId)", status_effect)

    def test_create_modal_keeps_exact_minimum_three_required_fields(self) -> None:
        fields = source_between(
            self.shell,
            '<div className="new-project-fields">',
            "{newProjectMessage &&",
        )
        labels = re.findall(r"<label>([^<]+)", fields)
        self.assertEqual(["试验药物", "适应症", "研究分期"], labels)
        self.assertEqual(3, fields.count(" required "))
        self.assertEqual(3, fields.count('aria-required="true"'))


if __name__ == "__main__":
    unittest.main()
