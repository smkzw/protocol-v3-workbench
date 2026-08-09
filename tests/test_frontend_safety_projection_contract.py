from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendSafetyProjectionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
        cls.styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        cls.checklist = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "MedicalMonitoringRiskChecklist.jsx"
        ).read_text(encoding="utf-8")
        cls.checklist_state = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "medicalMonitoringChecklistState.mjs"
        ).read_text(encoding="utf-8")

    def test_safety_defaults_to_canonical_read_only_risk_projection(self) -> None:
        self.assertIn("function SafetyRiskProjection", self.app)
        self.assertIn(
            "fetchCompleteMonitoringRiskIndex(riskProjectId, { safetyPvOnly: true, expectedProjectId: projectId })",
            self.app,
        )
        self.assertIn("api.getModuleSummary(projectId)", self.app)
        self.assertIn("api.getRiskSnapshot(projectId, {", self.app)
        self.assertIn("riskPage(page, first.snapshot_id)", self.app)
        self.assertIn("risk.safety_pv_flag === true", self.app)

    def test_safety_risk_projection_requires_identity_for_summary_and_every_page(self) -> None:
        self.assertIn("expectedProjectId = projectId", self.app)
        self.assertIn("payload?.project_id !== expectedProjectId", self.app)
        self.assertIn("安全性风险响应项目身份不匹配。", self.app)
        self.assertIn("api.getModuleSummary(projectId).then(requireProjectIdentity)", self.app)
        self.assertIn("}).then(requireProjectIdentity);", self.app)
        self.assertIn(
            "fetchCompleteMonitoringRiskIndex(riskProjectId, { safetyPvOnly: true, expectedProjectId: projectId })",
            self.app,
        )
        self.assertNotIn('fetch(`/api/projects/${riskProjectId}/monitoring/risks', self.app)
        self.assertIn('useState("risks")', self.app)
        self.assertIn("只读投影", self.app)
        self.assertIn("同一风险编号、来源、状态和审计", self.app)

    def test_pv_document_review_remains_a_peer_workspace(self) -> None:
        self.assertIn("安全性医学风险", self.app)
        self.assertIn("PV文件医学审阅", self.app)
        self.assertIn("<SafetyPvManifestPanel", self.app)

    def test_projection_deep_links_exact_risk_to_monitoring(self) -> None:
        self.assertIn("monitoringFocusRiskId", self.app)
        self.assertIn("initialRiskId={monitoringFocusRiskId}", self.app)
        self.assertIn("onOpenMonitoringRisk", self.app)
        self.assertIn("setRiskDockOpen(true)", self.app)
        self.assertIn("const selectedRisk = initialRiskMatch", self.app)
        self.assertIn("requestMonitoringRiskFocus(risk)", self.app)

    def test_projection_reuses_the_same_seven_column_sortable_filterable_checklist(self) -> None:
        for label in ("受试者编号", "中心编号", "风险级别", "风险类别", "具体风险项", "当前处置", "更新时间"):
            self.assertIn(label, self.checklist_state)
        self.assertIn("<MedicalMonitoringRiskChecklist", self.app)
        self.assertIn("onSelect={onOpenMonitoringRisk}", self.app)
        self.assertIn("risk-checklist-filter-popover", self.checklist)
        self.assertIn("risk-checklist-filter-chips", self.checklist)
        self.assertNotIn("safety-risk-projection-row", self.app)

    def test_review_actions_use_backend_state_revision_and_idempotency(self) -> None:
        self.assertIn("reviewWorkbench?.available_actions", self.app)
        self.assertIn("expected_revision: safetyReviewWorkbench?.state_revision || 0", self.app)
        self.assertIn("idempotency_key: globalThis.crypto?.randomUUID?.()", self.app)
        self.assertIn("const needsComment = true;", self.app)
        self.assertIn("expected_source_binding_digest", self.app)
        self.assertIn("撤回PV候选并关闭", self.app)

    def test_monitoring_collaboration_handoff_is_visible_with_stale_state(self) -> None:
        self.assertIn("monitoring_collaborations", self.app)
        self.assertIn("医学监查协作", self.app)
        self.assertIn("需重新复核", self.app)
        self.assertIn("safety-handoff-card monitoring", self.app)

    def test_projection_ignores_stale_project_responses_without_sticking_loading(self) -> None:
        self.assertIn("const safetyRiskRequestId = useRef(0);", self.app)
        self.assertIn("requestId === safetyRiskRequestId.current", self.app)
        self.assertIn("setSafetyRiskLoading(false)", self.app)

    def test_planned_review_workbench_reads_require_current_project_identity(self) -> None:
        self.assertIn("const plannedModuleProjectIdRef = useRef(projectId);", self.app)
        self.assertIn("data?.project_id !== plannedModuleProjectIdRef.current", self.app)
        self.assertIn("if (requestId !== tflReviewRequestId.current) return false;", self.app)
        self.assertIn("if (requestId !== safetyReviewRequestId.current) return false;", self.app)


if __name__ == "__main__":
    unittest.main()
