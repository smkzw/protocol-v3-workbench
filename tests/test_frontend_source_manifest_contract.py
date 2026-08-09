from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend" / "src" / "App.jsx"
STYLE_SOURCE = ROOT / "frontend" / "src" / "styles.css"


class FrontendSourceManifestContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_SOURCE.read_text(encoding="utf-8")
        cls.styles = STYLE_SOURCE.read_text(encoding="utf-8")

    def test_app_loads_canonical_project_catalog_and_active_manifest(self):
        self.assertIn('fetch("/api/projects")', self.source)
        self.assertIn("const [projects, setProjects] = useState([]);", self.source)
        self.assertIn("const [activeProjectId, setActiveProjectId]", self.source)
        self.assertIn("const [sourceManifests, setSourceManifests] = useState({});", self.source)
        self.assertIn("fetch(`/api/projects/${activeProjectId}/source-manifest`)", self.source)
        self.assertIn("[activeProjectId]: manifest", self.source)
        self.assertIn("manifest?.project_id !== activeProjectIdRef.current", self.source)
        self.assertNotIn("RAW_ELIGIBILITY_PROJECT_ID", self.source)
        self.assertNotIn("RAW_MONITORING_PROJECT_ID", self.source)

    def test_vite_project_override_is_initial_selection_only(self):
        self.assertEqual(1, self.source.count("VITE_PROJECT_ID"))
        self.assertIn('const INITIAL_PROJECT_ID = import.meta.env.VITE_PROJECT_ID || "";', self.source)
        self.assertNotIn('INITIAL_PROJECT_ID = import.meta.env.VITE_PROJECT_ID || "proj_rux_03_002"', self.source)
        self.assertNotRegex(self.source, r"fetch\([^\n]*VITE_PROJECT_ID")

    def test_app_shell_displays_current_module_source_context(self):
        app_shell = re.search(r"function AppShell\(.*?function Metric", self.source, re.S)
        self.assertIsNotNone(app_shell, "AppShell not found")
        shell_source = app_shell.group(0)

        self.assertIn("sourceContextForPage(activePage, sourceManifests, activeProjectId)", shell_source)
        self.assertIn('aria-label="选择临床研究项目"', shell_source)
        self.assertIn("当前来源", shell_source)
        self.assertIn("sourceContext.label", shell_source)
        self.assertIn("sourceContext.sourceCode", shell_source)
        self.assertIn("sourceContext.configured", shell_source)
        self.assertIn("sourceContext.displayBatch", shell_source)
        self.assertIn("activeBatch", shell_source)
        self.assertNotIn("跨项目源", shell_source)

    def test_source_context_uses_selected_canonical_project_and_module_route_binding(self):
        self.assertIn("function sourceContextForPage", self.source)
        self.assertIn("sourceManifests?.[activeProjectId]", self.source)
        self.assertIn("routeProjectId = binding?.route_project_id", self.source)
        self.assertIn("displayBatch: binding?.display_batch || null", self.source)
        self.assertIn("hasActiveProject && sourceContext.displayBatch?.batch_label", self.source)
        self.assertIn("? sourceContext.displayBatch", self.source)
        self.assertIn(": latestBatch", self.source)
        self.assertNotIn("pageSourceProjectIds", self.source)
        self.assertNotIn("const PROJECT_ID", self.source)

    def test_project_scoped_dashboard_and_inbox_reads_fail_closed_on_identity(self):
        self.assertIn("data?.project?.project_id !== activeProjectIdRef.current", self.source)
        self.assertIn("data?.project_id !== activeProjectIdRef.current", self.source)
        self.assertIn("data?.project_id !== monitoringResponseProjectIdRef.current", self.source)

    def test_project_scoped_ai_run_list_requires_each_run_identity(self):
        self.assertIn("data.some((run) => run?.project_id !== activeProjectIdRef.current)", self.source)

    def test_subject_identity_mismatch_is_visible_without_relaxing_fail_closed_guards(self):
        self.assertIn('const [monitoringDataError, setMonitoringDataError] = useState("");', self.source)
        self.assertIn("data?.project_id !== monitoringResponseProjectIdRef.current", self.source)
        self.assertIn("data?.subject_id !== selectedSubject", self.source)
        self.assertIn("受试者目录响应项目身份不匹配，已阻止写入当前项目。", self.source)
        self.assertIn("受试者画像响应项目或受试者身份不匹配，已阻止写入当前个例。", self.source)
        self.assertIn("monitoringDataError={monitoringDataError}", self.source)
        self.assertIn('className="gate-error monitoring-data-identity-error"', self.source)
        self.assertIn('role="alert"', self.source)
        self.assertIn("setMonitoringSubjectCatalog([]);", self.source)
        self.assertIn("setMonitoringDataError(\"\");", self.source)

    def test_source_context_css_is_desktop_dense_and_no_path_leak_tokens(self):
        self.assertIn(
            "grid-template-columns: 118px 112px 130px 105px 145px minmax(150px, 180px);",
            self.styles,
        )
        self.assertIn(".project-meta .source-context-unconfigured", self.styles)
        self.assertIn(".project-switcher select", self.styles)
        self.assertIn("text-overflow: ellipsis;", self.styles)

        source_context = re.search(r"function sourceContextForPage\(.*?function AppShell", self.source, re.S)
        self.assertIsNotNone(source_context, "source context helper block not found")
        context_source = source_context.group(0)
        self.assertNotIn("/Users/", context_source)
        self.assertNotIn("server_path", context_source)
        self.assertNotIn("source_path", context_source)


if __name__ == "__main__":
    unittest.main()
