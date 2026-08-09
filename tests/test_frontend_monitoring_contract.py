from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend" / "src" / "App.jsx"
MONITORING_MODELS_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringModels.mjs"
)
MONITORING_FIXTURES_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringFixtures.mjs"
)
MONITORING_BATCH_PANEL_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringBatchPanel.jsx"
)
MONITORING_FIELD_MAPPING_PANEL_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringFieldMappingPanel.jsx"
)
MONITORING_FIELD_MAPPING_VIEW_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringFieldMappingView.mjs"
)
MONITORING_PROTOCOL_PREPARATION_PANEL_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringProtocolPreparationPanel.jsx"
)
MONITORING_PROTOCOL_PREPARATION_MODEL_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringProtocolPreparation.mjs"
)
MONITORING_ASSURANCE_PANEL_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringAssurancePanel.jsx"
)
MONITORING_ASSURANCE_PANEL_STYLES_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringAssurancePanel.css"
)
MONITORING_ASSURANCE_MODEL_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringAssurance.mjs"
)
MONITORING_ASSURANCE_REMEDIATION_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringAssuranceRemediation.jsx"
)
MONITORING_ASSURANCE_REMEDIATION_MODEL_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringAssuranceRemediation.mjs"
)
MONITORING_RULE_RELEASE_PANEL_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringRuleReleasePanel.jsx"
)
MONITORING_RULE_RELEASE_VIEW_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringRuleReleaseView.mjs"
)
MONITORING_MODE_CATALOG_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringModeCatalog.mjs"
)
MONITORING_DAILY_RUN_PANEL_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringDailyRunPanel.jsx"
)
MONITORING_DAILY_RUN_VIEW_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringDailyRunView.mjs"
)
MONITORING_DAILY_DIFF_VIEW_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringDailyDiffView.mjs"
)
MONITORING_DAILY_DIFF_SUMMARY_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringDailyDiffSummary.jsx"
)
MONITORING_DAILY_AI_CANDIDATES_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringDailyAiCandidates.jsx"
)
MONITORING_DAILY_AI_CANDIDATES_STYLES_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringDailyAiCandidates.css"
)
MONITORING_DAILY_AI_EVIDENCE_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringDailyAiEvidence.jsx"
)
MONITORING_DAILY_AI_EVIDENCE_MODEL_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringDailyAiEvidence.mjs"
)
MONITORING_DAILY_AI_EVIDENCE_STYLES_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringDailyAiEvidence.css"
)
MONITORING_MODE_COVERAGE_SOURCE = (
    ROOT
    / "services"
    / "api"
    / "app"
    / "monitoring_real_loop_mode_coverage.py"
)
MONITORING_PRINCIPAL_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringPrincipal.mjs"
)
MONITORING_SUBJECT_VIEWS_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringSubjectViews.jsx"
)
MONITORING_SUBJECT_MODELS_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringSubjectModels.mjs"
)
MONITORING_METRIC_CONFIGURATION_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringMetricConfiguration.mjs"
)
MONITORING_SCOPE_SUMMARY_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "MedicalMonitoringScopeSummary.jsx"
)
MONITORING_SCOPE_SUMMARY_MODEL_SOURCE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-monitoring"
    / "medicalMonitoringScopeSummary.mjs"
)


class FrontendMonitoringContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_SOURCE.read_text(encoding="utf-8")
        cls.models_source = MONITORING_MODELS_SOURCE.read_text(encoding="utf-8")
        cls.fixtures_source = MONITORING_FIXTURES_SOURCE.read_text(encoding="utf-8")
        cls.batch_panel_source = MONITORING_BATCH_PANEL_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.field_mapping_panel_source = MONITORING_FIELD_MAPPING_PANEL_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.field_mapping_view_source = MONITORING_FIELD_MAPPING_VIEW_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.protocol_preparation_panel_source = MONITORING_PROTOCOL_PREPARATION_PANEL_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.protocol_preparation_model_source = MONITORING_PROTOCOL_PREPARATION_MODEL_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.assurance_panel_source = MONITORING_ASSURANCE_PANEL_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.assurance_panel_styles_source = MONITORING_ASSURANCE_PANEL_STYLES_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.assurance_model_source = MONITORING_ASSURANCE_MODEL_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.assurance_remediation_source = MONITORING_ASSURANCE_REMEDIATION_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.assurance_remediation_model_source = MONITORING_ASSURANCE_REMEDIATION_MODEL_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.rule_release_panel_source = MONITORING_RULE_RELEASE_PANEL_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.rule_release_view_source = MONITORING_RULE_RELEASE_VIEW_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.mode_catalog_source = MONITORING_MODE_CATALOG_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.daily_run_panel_source = MONITORING_DAILY_RUN_PANEL_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.daily_run_view_source = MONITORING_DAILY_RUN_VIEW_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.daily_diff_view_source = MONITORING_DAILY_DIFF_VIEW_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.daily_diff_summary_source = MONITORING_DAILY_DIFF_SUMMARY_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.daily_ai_candidates_source = MONITORING_DAILY_AI_CANDIDATES_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.daily_ai_candidates_styles_source = MONITORING_DAILY_AI_CANDIDATES_STYLES_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.daily_ai_evidence_source = MONITORING_DAILY_AI_EVIDENCE_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.daily_ai_evidence_model_source = MONITORING_DAILY_AI_EVIDENCE_MODEL_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.daily_ai_evidence_styles_source = MONITORING_DAILY_AI_EVIDENCE_STYLES_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.mode_coverage_source = MONITORING_MODE_COVERAGE_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.principal_source = MONITORING_PRINCIPAL_SOURCE.read_text(encoding="utf-8")
        cls.subject_views_source = MONITORING_SUBJECT_VIEWS_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.subject_models_source = MONITORING_SUBJECT_MODELS_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.metric_configuration_source = MONITORING_METRIC_CONFIGURATION_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.scope_summary_source = MONITORING_SCOPE_SUMMARY_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.scope_summary_model_source = MONITORING_SCOPE_SUMMARY_MODEL_SOURCE.read_text(
            encoding="utf-8"
        )

    def _monitoring_page(self) -> str:
        match = re.search(
            r"function MonitoringPage\(.*?function RiskDetail",
            self.source,
            re.S,
        )
        self.assertIsNotNone(match, "MonitoringPage source not found")
        return match.group(0)

    def _risk_detail(self) -> str:
        match = re.search(
            r"function RiskDetail\(.*?const timelineLaneDefs",
            self.source,
            re.S,
        )
        self.assertIsNotNone(match, "RiskDetail source not found")
        return match.group(0)

    def test_monitoring_page_prefers_real_workbench_inbox_risks_over_demo_rows(self):
        monitoring = self._monitoring_page()

        self.assertIn("workbenchInbox", monitoring)
        self.assertIn(
            "monitoringRiskRowsFromInbox(workbenchInbox, monitoringBatchDisplay)",
            monitoring,
        )
        self.assertIn("monitoringBinding?.display_batch?.extract_date", monitoring)
        self.assertIn("monitoringBatchDisplay", monitoring)
        self.assertIn("const visibleRiskRows = indexedRiskRows;", monitoring)
        self.assertIn("riskIndexRowsFromApi(riskIndex", monitoring)
        self.assertIn("getRiskSnapshot(", monitoring)
        self.assertNotIn(
            "const visibleRiskRows = [...generatedRiskRows, ...demoRiskRows];",
            monitoring,
        )

    def test_rux_monitoring_rows_map_inbox_target_source_refs_and_unread_state(self):
        self.assertIn("monitoringRiskRowsFromInbox,", self.source)
        self.assertIn("function monitoringRiskRowsFromInbox", self.models_source)
        self.assertIn('item.module === "medical_monitoring"', self.models_source)
        self.assertIn('item.item_type === "risk"', self.models_source)
        self.assertIn("item.target_id", self.models_source)
        self.assertIn("item.source_refs", self.models_source)
        self.assertIn("item.unread", self.models_source)
        self.assertIn("sourceRefs", self.models_source)

    def test_monitoring_page_receives_inbox_and_can_refresh_after_actions(self):
        app_page = re.search(
            r'if \(activePage === "monitoring"\).*?<MonitoringPage.*?/>',
            self.source,
            re.S,
        )
        self.assertIsNotNone(app_page, "MonitoringPage invocation not found")
        invocation = app_page.group(0)

        self.assertIn("monitoringProjectId={monitoringRouteProjectId}", invocation)
        self.assertIn("sourceManifest={activeManifest}", invocation)
        self.assertIn("workbenchInbox={monitoringWorkbenchInbox}", invocation)
        self.assertNotIn(
            "workbenchInbox={monitoringWorkbenchInbox || workbenchInbox}", invocation
        )
        self.assertIn(
            "refreshWorkbenchInbox={refreshMonitoringWorkbenchInbox}", invocation
        )
        self.assertIn("refreshDashboard={refreshDashboard}", invocation)
        self.assertIn(
            'initialRiskView={monitoringRouteState.view || "checklist"}', invocation
        )
        self.assertIn(
            'initialRiskScope={monitoringRouteState.scope || "trial"}', invocation
        )
        self.assertIn(
            'initialRiskSiteId={monitoringRouteState.site_id || ""}', invocation
        )
        self.assertIn("onRiskScopeChange={requestMonitoringRiskScope}", invocation)

    def test_evidence_and_ae_mh_deep_links_restore_the_matching_dock_tab(self):
        self.assertIn('if (view === "evidence") return "sources";', self.source)
        self.assertIn('if (view === "ae-mh") return "ae_mh";', self.source)
        self.assertIn("setActiveTab(initialTab)", self.source)
        self.assertIn("[risk.id, initialTab, expectedEvidenceProjectId]", self.source)

    def test_subject_views_return_through_protected_monitoring_workspace_reset(self):
        self.assertIn("const requestMonitoringWorkspace = useCallback", self.source)
        self.assertIn("const returnRiskId = subjectViewFocusRiskId", self.source)
        self.assertIn(
            "const returnScope = monitoringReturnScopeRef.current", self.source
        )
        self.assertIn("monitoringReturnSiteIdRef.current", self.source)
        self.assertIn("risk_instance_id: returnRiskId", self.source)
        self.assertIn("setMonitoringFocusRiskId(returnRiskId)", self.source)
        self.assertIn('view: "checklist"', self.source)
        self.assertIn("requestActivePage(nextPage)", self.source)
        self.assertIn("onNavigate={requestMonitoringWorkspace}", self.source)
        self.assertNotIn("onNavigate={setActivePage}", self.source)
        self.assertIn('onOpenSubjectView?.("subjectTimeline", risk.id)', self.source)
        self.assertIn('onOpenSubjectView?.("patientProfile", risk.id)', self.source)
        self.assertNotIn('setActivePage("subjectTimeline")', self._risk_detail())
        self.assertNotIn('setActivePage("patientProfile")', self._risk_detail())

    def test_sidebar_monitoring_navigation_cannot_leave_a_profile_view_in_the_url(self):
        self.assertIn(
            'if (activePage === "monitoring") return "checklist";',
            self.source,
        )
        self.assertNotIn(
            'if (activePage === "monitoring") return fallback || "checklist";',
            self.source,
        )

    def test_risk_scope_is_not_inferred_from_the_selected_subject(self):
        self.assertIn("const monitoringReturnScopeRef = useRef(", self.source)
        self.assertIn("const monitoringReturnSiteIdRef = useRef(", self.source)
        self.assertIn(
            'const isSubjectView = ["subjectTimeline", "patientProfile"].includes(activePage);',
            self.source,
        )
        self.assertIn('monitoringRouteState.scope || "trial"', self.source)
        self.assertNotIn(
            'const nextScope = selectedSubject\\n      ? "subject"', self.source
        )
        self.assertIn('scope: "subject"', self.source)
        self.assertIn(
            'view: nextPage === "subjectTimeline" ? "timeline" : "profile"', self.source
        )

    def test_scope_switch_filters_the_visible_risk_rows_and_updates_the_route(self):
        monitoring = self._monitoring_page()
        self.assertIn('riskScope === "subject" && selectedSubject', monitoring)
        self.assertIn('riskScope === "site" && riskScopeSiteId', monitoring)
        self.assertIn("const scopeSubjectId = selectedRisk?.subject", monitoring)
        self.assertIn("setSelectedSubject(scopeSubjectId)", monitoring)
        self.assertIn("onRiskScopeChange?.(value", monitoring)
        self.assertIn("受试者 {selectedSubject}", monitoring)
        self.assertIn("中心 {riskScopeSiteId}", monitoring)

    def test_unclassified_listing_sheets_are_visible_and_fail_closed_for_risk_summary(self):
        monitoring = self._monitoring_page()

        self.assertIn("unclassifiedMonitoringSheets", monitoring)
        self.assertIn("rawMonitoring?.unclassified_sheet_names", monitoring)
        self.assertIn('aria-label="未分类数据表"', monitoring)
        self.assertIn("尚未归入监查数据域", monitoring)
        self.assertIn("不会把这些表自动纳入风险结论", monitoring)
        self.assertIn("完成字段结构映射并由医学监察员确认", monitoring)

    def test_monitoring_page_writes_to_monitoring_source_project_not_global_demo_project(
        self,
    ):
        monitoring = self._monitoring_page()

        self.assertIn("monitoringProjectId", monitoring)
        self.assertIn("sourceManifest", monitoring)
        self.assertIn("monitoringSourceLabel", monitoring)
        self.assertIn(
            "fetch(`/api/projects/${monitoringProjectId}/monitoring/raw-intake`)",
            monitoring,
        )
        self.assertIn("<MedicalMonitoringBatchPanel", monitoring)
        self.assertIn("projectId={monitoringProjectId}", monitoring)
        self.assertNotIn("/monitoring/intake", monitoring)
        self.assertIn(
            "fetch(`/api/projects/${monitoringProjectId}/workbench-inbox/${encodeURIComponent(risk.inboxItemId)}/actions`",
            monitoring,
        )
        self.assertIn(
            "fetch(`/api/projects/${monitoringProjectId}/workbench-inbox/${encodeURIComponent(risk.inboxItemId)}/risk-disposition`",
            monitoring,
        )
        self.assertNotIn(
            "fetch(`/api/projects/${PROJECT_ID}/monitoring/intake", monitoring
        )

    def test_real_project_monitoring_never_falls_back_to_demo_listing_or_demo_risks(
        self,
    ):
        monitoring = self._monitoring_page()

        self.assertNotIn("demoRiskRows", self.source)
        self.assertNotIn("import { demoSubjects }", self.source)
        self.assertIn("MedicalMonitoringSubjectViews", self.source)
        self.assertIn("export const demoRiskRows = [", self.fixtures_source)
        self.assertIn("export const demoSubjects = [", self.fixtures_source)
        self.assertNotIn("demoSubjects", monitoring)
        self.assertNotIn("const demoRiskRows = [", self.source)
        self.assertNotIn("const demoSubjects = [", self.source)
        self.assertNotIn("const riskRows = [", self.source)
        self.assertNotIn("const subjects = [", self.source)
        self.assertIn('if (!batch) return "未登记批次";', self.source)
        self.assertNotIn("demoListingSheets", monitoring)
        self.assertIn("<MedicalMonitoringBatchPanel", monitoring)
        self.assertIn("projectId={monitoringProjectId}", monitoring)
        self.assertNotIn("proj_mgk10_sar_demo", self.batch_panel_source)
        self.assertNotIn("demoRiskRows", self.batch_panel_source)
        self.assertNotIn("demoSubjects", self.batch_panel_source)
        self.assertIn("尚未运行医学风险规则", self.batch_panel_source)

    def test_monitoring_risk_subject_view_uses_fetched_subject_catalog(self):
        monitoring = self._monitoring_page()
        self.assertIn("subjectCatalog = []", monitoring)
        self.assertIn(
            "buildSubjectView(subjectProfile, selectedSubject, selectedRisk, subjectCatalog)",
            monitoring,
        )
        invocation = re.search(
            r'if \(activePage === "monitoring"\).*?<MonitoringPage.*?/>',
            self.source,
            re.S,
        )
        self.assertIsNotNone(invocation, "MonitoringPage invocation not found")
        self.assertIn("subjectCatalog={monitoringSubjectCatalog}", invocation.group(0))

    def test_subject_view_builder_has_no_implicit_demo_catalog_fallback(self):
        match = re.search(
            r"function buildSubjectView\(profile, subjectId, risk, subjectCatalog = (.*?)\) \{",
            self.source,
        )
        self.assertIsNotNone(match, "buildSubjectView source not found")
        self.assertEqual(match.group(1), "[]")
        self.assertNotIn(
            "function buildSubjectView(profile, subjectId, risk, subjectCatalog = demoSubjects)",
            self.source,
        )

    def test_active_subject_routes_do_not_reenter_legacy_app_pages(self):
        self.assertIn("<MedicalMonitoringSubjectTimelinePage", self.source)
        self.assertIn("<MedicalMonitoringPatientProfilePage", self.source)
        self.assertNotIn("<SubjectTimelinePage", self.source)
        self.assertNotIn("<PatientProfilePage", self.source)
        self.assertNotIn("function SubjectTimelinePage(", self.source)
        self.assertNotIn("function PatientProfilePage(", self.source)

    def test_subject_views_fail_closed_when_monitoring_source_is_not_execution_ready(self):
        timeline = re.search(
            r'const page = useMemo\(\(\) => \{.*?if \(activePage === "subjectTimeline"\).*?if \(activePage === "patientProfile"\)',
            self.source,
            re.S,
        )
        self.assertIsNotNone(timeline, "subject Timeline/Profile dispatch not found")
        dispatch = timeline.group(0)
        self.assertIn("!monitoringRouteProjectId || !monitoringExecutionReady", dispatch)
        self.assertIn("monitoringReadiness.message", dispatch)
        self.assertIn("当前项目医学监查来源尚未达到可读取条件", dispatch)
        self.assertIn("<MedicalMonitoringSubjectTimelinePage", dispatch)
        self.assertNotIn("<MedicalMonitoringPatientProfilePage", dispatch)

        profile = re.search(
            r'if \(activePage === "patientProfile"\).*?if \(activePage === "tfl"\)',
            self.source,
            re.S,
        )
        self.assertIsNotNone(profile, "patient Profile dispatch not found")
        profile_dispatch = profile.group(0)
        self.assertIn("!monitoringRouteProjectId || !monitoringExecutionReady", profile_dispatch)
        self.assertIn("monitoringReadiness.message", profile_dispatch)
        self.assertIn("<MedicalMonitoringPatientProfilePage", profile_dispatch)

    def test_processed_full_snapshot_requires_explicit_grade_b_proof(self):
        source = self.batch_panel_source
        self.assertIn('source?.source_class === "processed_full_snapshot"', source)
        self.assertIn("source?.medical_override_reason?.trim()", source)
        self.assertIn('source_authority_grade: "B"', source)
        self.assertIn("processed_source_acknowledged: true", source)
        self.assertIn("B级处理后来源", source)
        self.assertIn("不能作为原始 EDC 权威证据", source)
        self.assertNotIn('processed_full_snapshot: "处理后快照（不可作基线）"', source)

    def test_assurance_panel_does_not_turn_missing_counts_into_zero(self):
        source = self.assurance_panel_source
        self.assertIn("function explicitArrayCount(value)", source)
        self.assertIn("assuranceRollupNumber(proof.failures)", source)
        self.assertIn("assuranceRollupNumber(proof.skips)", source)
        self.assertIn("assuranceRollupNumber(proof.open_high_risk_count)", source)
        self.assertIn(
            "assuranceRollupNumber(proof.closed_risks_lacking_evidence_count)", source
        )
        self.assertIn("explicitArrayCount(rollup.subject_rollup)", source)
        self.assertNotIn("proof.failures ?? 0", source)
        self.assertNotIn("proof.skips ?? 0", source)
        self.assertNotIn("proof.open_high_risk_count ?? 0", source)
        self.assertNotIn("proof.closed_risks_lacking_evidence_count ?? 0", source)
        self.assertIn("evidence.blockingReason", source)
        self.assertIn("projectAssuranceRollup", self.assurance_model_source)

    def test_assurance_panel_explains_mixed_provenance_without_unlocking_completion(self):
        source = self.assurance_panel_source
        styles = self.assurance_panel_styles_source
        self.assertIn("function AssuranceProvenanceDisclosure", source)
        self.assertIn('provenanceStatus !== "mixed_provenance"', source)
        self.assertIn("不能作为完成证据", source)
        self.assertIn("只读诊断", source)
        self.assertIn("待选择并实现一种证据权威路线后", source)
        self.assertIn("visibleEvidence.provenanceStatus || proofProvenanceStatus", source)
        self.assertIn("<details className=\"monitoring-assurance-provenance\">", source)
        self.assertIn(".monitoring-assurance-provenance", styles)
        self.assertIn("monitoring-assurance-provenance-grid", styles)

    def test_three_monitoring_modes_have_one_explicit_user_facing_catalog(self):
        catalog = self.mode_catalog_source
        for mode_id in (
            '"daily_incremental"',
            '"pre_lock_total"',
            '"post_lock_fixed_total"',
        ):
            self.assertIn(mode_id, catalog)
            self.assertIn(mode_id.strip('"'), self.mode_coverage_source)
        self.assertIn("最新全量 EDC listing", catalog)
        self.assertIn("上一已确认批次", catalog)
        self.assertIn("全量重算，不以日常增量结果简单累加", catalog)
        self.assertIn("固定总量，不再追加日常批次", catalog)
        self.assertIn("monitoringModeForDailyRun", self.daily_run_panel_source)
        self.assertIn("aria-label={dailyMode.label}", self.daily_run_panel_source)
        self.assertIn("assuranceModeDescription", self.assurance_panel_source)
        self.assertIn("<small>{assuranceModeDescription(value)}</small>", self.assurance_panel_source)
        self.assertIn("MONITORING_MODE_CHECKPOINTS", self.mode_coverage_source)

    def test_incremental_diff_details_stay_read_only_and_fail_closed(self):
        view = self.daily_diff_view_source
        summary = self.daily_diff_summary_source
        self.assertIn("DETAIL_SAMPLE_LIMIT = 8", view)
        self.assertIn("summarizeFieldChanges", view)
        self.assertIn("summarizeSchemaDiffs", view)
        self.assertIn("summarizeIdentitySamples", view)
        self.assertIn("details", view)
        self.assertIn("明细只用于定位差异来源，不是医学风险结论", summary)
        self.assertIn("查看结构、字段与回源核对明细", summary)
        self.assertIn("计数仍以服务端冻结 diff 快照为准", summary)
        self.assertNotIn("confirm", summary.lower())
        self.assertNotIn("fetch(", summary)

    def test_daily_ai_candidate_provenance_is_collapsed_and_read_only(self):
        source = self.daily_ai_candidates_source
        styles = self.daily_ai_candidates_styles_source
        self.assertIn("function provenanceReady(candidate)", source)
        self.assertIn('<details className="monitoring-daily-ai-candidate-provenance">', source)
        self.assertIn("候选输入修订", source)
        self.assertIn("提示词版本", source)
        self.assertIn("源哈希", source)
        self.assertIn("来源身份只用于版本与回源核对，不是医学风险结论", source)
        self.assertIn("来源身份不完整或异常时，不得确认或作为无风险依据", source)
        self.assertIn("monitoring-daily-ai-candidate-provenance", styles)
        self.assertNotIn("onClick", source)
        self.assertNotIn("fetch(", source)

    def test_daily_ai_candidate_shows_explicit_fact_before_locator(self):
        source = self.daily_ai_candidates_source
        styles = self.daily_ai_candidates_styles_source
        self.assertIn('aria-label="候选引用的来源事实"', source)
        self.assertIn('item.quote || "来源事实正文待核对"', source)
        self.assertIn("引用只反映显式来源片段，不等于医学风险确认", source)
        self.assertLess(
            source.index('aria-label="候选引用的来源事实"'),
            source.index('<p>{display(candidate.text)}</p>'),
        )
        self.assertIn("monitoring-daily-ai-candidate-facts", styles)
        self.assertNotIn("risk.title", source)

    def test_daily_ai_candidate_display_keys_fail_closed_on_missing_or_duplicate_ids(self):
        source = self.daily_ai_candidates_source
        model = MONITORING_DAILY_AI_CANDIDATES_SOURCE.with_name(
            "medicalMonitoringDailyAiCandidates.mjs"
        ).read_text(encoding="utf-8")
        self.assertIn("medicalMonitoringAiCandidateDisplayKey", source)
        self.assertIn("medicalMonitoringAiCandidateEvidenceKey", source)
        self.assertIn("medicalMonitoringAiCandidateClaimKey", source)
        self.assertIn("sourceIndex: index", model)
        self.assertIn("candidate:${identity}:${sourceIndex}", model)
        self.assertIn("candidate-evidence:${identity}:${sourceIndex}", model)
        self.assertIn("candidate-claim:${claimId || \"missing\"}:${sourceIndex}", model)
        self.assertIn('identityState !== "ready"', source)
        self.assertNotIn("key={candidate.candidateId}", source)
        self.assertNotIn("key={item.evidenceId}", source)
        self.assertNotIn("key={claim.claimId}", source)

    def test_daily_ai_candidate_review_state_does_not_relabel_terminal_status_as_pending(self):
        source = self.daily_ai_candidates_source
        model = MONITORING_DAILY_AI_CANDIDATES_SOURCE.with_name(
            "medicalMonitoringDailyAiCandidates.mjs"
        ).read_text(encoding="utf-8")
        self.assertIn("medicalMonitoringAiCandidateReviewStateLabel", model)
        self.assertIn("medicalMonitoringAiCandidateReviewStateLabel", source)
        self.assertIn("<span>{medicalMonitoringAiCandidateReviewStateLabel(candidate)}</span>", source)
        self.assertNotIn('confidence?.requiresAdditionalEvidence ? "需补证据" : "需医学确认"', source)
        self.assertIn('status === "accepted"', model)
        self.assertIn('status === "rejected"', model)
        self.assertIn('status === "superseded"', model)

    def test_daily_ai_failure_details_are_visible_when_counts_disagree(self):
        source = self.daily_ai_evidence_source
        model = self.daily_ai_evidence_model_source
        styles = self.daily_ai_evidence_styles_source
        self.assertIn("medicalMonitoringAiFailureKind", model)
        self.assertIn("counts.failed !== failures.length", model)
        self.assertIn("const hasFailureEvidence", source)
        self.assertIn('failureLabel || "失败原因待核对"', source)
        self.assertIn("仅作账本分类，不代表可重试", source)
        self.assertIn("保留失败证据，不补成 0", source)
        self.assertIn("monitoring-daily-ai-failure-kind", styles)
        self.assertNotIn("retry(", source)
        self.assertNotIn("fetch(", source)

    def test_daily_ai_failure_rows_keep_duplicate_job_evidence_visible(self):
        source = self.daily_ai_evidence_source
        model = self.daily_ai_evidence_model_source
        self.assertIn("medicalMonitoringAiFailureDisplayKey", source)
        self.assertIn("sourceIndex: index", model)
        self.assertIn("重复 job_id", model)
        self.assertIn("ai-failure:${jobId}:${sourceIndex}", model)
        self.assertNotIn("key={failure.jobId}", source)

    def test_risk_checklist_keeps_duplicate_risk_evidence_visible_but_not_selectable(self):
        checklist = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "MedicalMonitoringRiskChecklist.jsx"
        ).read_text(encoding="utf-8")
        self.assertIn("medicalMonitoringRiskDisplayKey", self.models_source)
        self.assertIn("identityAmbiguous", self.models_source)
        self.assertIn("sourceIndex", self.models_source)
        self.assertIn("风险身份重复；保留证据但暂不可定位", checklist)
        self.assertIn("身份重复，仅可读", checklist)
        self.assertIn("risk.identityAmbiguous !== true", checklist)
        self.assertIn("aria-disabled={risk.identityAmbiguous ? \"true\" : undefined}", checklist)
        self.assertNotIn("key={risk.id}", checklist)

    def test_assurance_remediation_keeps_duplicate_risk_rows_visible_but_not_focusable(self):
        source = self.assurance_remediation_source
        model = self.assurance_remediation_model_source
        self.assertIn("assuranceRemediationDisplayKey", source)
        self.assertIn("sourceIndex: index", model)
        self.assertIn('identityState = riskInstanceCounts.get(row.riskInstanceId) > 1 ? "duplicate" : "ready"', model)
        self.assertIn("assurance-remediation:${identity}:${sourceIndex}", model)
        self.assertIn('row.identityState !== "ready"', source)
        self.assertIn("身份重复，仅可读", source)
        self.assertNotIn("key={row.riskInstanceId}", source)

    def test_rule_release_samples_keep_duplicate_identity_visible(self):
        source = self.rule_release_panel_source
        model = self.rule_release_view_source
        self.assertIn("ruleReleaseSampleDisplayKey", source)
        self.assertIn("displaySourceIndex", model)
        self.assertIn('displayIdentityState = sampleIdCounts.get(sample.sample_id) > 1 ? "duplicate" : "ready"', model)
        self.assertIn("rule-release-sample:${identity}:${sourceIndex}", model)
        self.assertIn("身份待核对", source)
        self.assertNotIn("key={sample.sampleId}", source)

    def test_rule_release_pack_picker_keeps_duplicate_pack_identity_read_only(self):
        source = self.rule_release_panel_source
        release_model = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "medicalMonitoringRuleRelease.mjs"
        ).read_text(encoding="utf-8")
        self.assertIn("rulePackDisplayKey", source)
        self.assertIn("displayIdentityState", release_model)
        self.assertIn("rule-pack:${identity}:${sourceIndex}", release_model)
        self.assertIn('pack.displayIdentityState === "ready"', source)
        self.assertIn('disabled={item.displayIdentityState !== "ready"}', source)
        self.assertIn("身份重复，仅可读", source)
        self.assertNotIn("key={item.rulePackId}", source)

    def test_rule_release_frozen_batch_picker_keeps_duplicate_batch_identity_read_only(self):
        source = self.rule_release_panel_source
        model = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "medicalMonitoringRuleRelease.mjs"
        ).read_text(encoding="utf-8")
        self.assertIn("frozenShadowBatches", model)
        self.assertIn("displayIdentityState", model)
        self.assertIn("displaySourceIndex", model)
        self.assertIn("冻结批次 batch_id 重复", model)
        self.assertIn("batch:${batchId || \"missing\"}:${sourceIndex}", model)
        self.assertIn("selectedBatchReady", source)
        self.assertIn('disabled={batch.displayIdentityState !== "ready"}', source)
        self.assertIn("身份待核对", source)
        self.assertNotIn("key={batch.batchId}", source)

    def test_profile_metric_candidates_keep_missing_or_duplicate_identity_visible(self):
        source = self.subject_views_source
        model = self.metric_configuration_source
        self.assertIn("metricConfigurationCandidateDisplayKey", source)
        self.assertIn("identityState", model)
        self.assertIn("sourceIndex", model)
        self.assertIn("metric-candidate:${identity}:${index}", model)
        self.assertIn("身份待核对", source)
        self.assertIn("身份重复", source)
        self.assertIn("candidate.identityState !== \"ready\"", source)
        self.assertNotIn("key={candidate.candidate_id || candidate.metric_key}", source)

    def test_profile_trend_metrics_keep_missing_or_duplicate_identity_visible(self):
        source = self.subject_views_source
        model = self.subject_models_source
        self.assertIn("metricDisplayRows", source)
        self.assertIn("displayIdentityState", model)
        self.assertIn("displaySourceIndex", model)
        self.assertIn("metric:${safeNamespace}:${identity || \"missing\"}:${displaySourceIndex}", model)
        self.assertIn("趋势指标缺少 metric_key/metric_label", model)
        self.assertIn("趋势指标 metric_key/metric_label 重复", model)
        self.assertIn("key={metric.displayKey}", source)
        self.assertIn("metric.displayIdentityState !== \"ready\"", source)
        self.assertNotIn("key={metric.metric_key || metric.metric_label}", source)

    def test_profile_trend_points_keep_missing_or_duplicate_identity_visible(self):
        source = self.subject_views_source
        model = self.subject_models_source
        self.assertIn("trendPointDisplayRows", source)
        self.assertIn("displayIdentityState", model)
        self.assertIn("displaySourceIndex", model)
        self.assertIn("metric-point:${safeMetricKey}:${identity || \"missing\"}:${displaySourceIndex}", model)
        self.assertIn("趋势数据点缺少 point_id", model)
        self.assertIn("趋势数据点 point_id 重复", model)
        self.assertIn("pointIdentityWarningCount", source)
        self.assertIn("身份待核对", source)
        self.assertIn("身份重复", source)
        self.assertIn("key={`reference-${key}`}", source)
        self.assertNotIn("key={`reference-${point.point_id || index}`}", source)

    def test_risk_history_points_keep_missing_or_duplicate_snapshot_identity_visible(self):
        view = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "MedicalMonitoringRiskHistoryTrend.jsx"
        ).read_text(encoding="utf-8")
        model = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "medicalMonitoringRiskHistoryTrend.mjs"
        ).read_text(encoding="utf-8")
        self.assertIn("displayIdentityState", model)
        self.assertIn("displaySourceIndex", model)
        self.assertIn("risk-history:${identity || \"missing\"}:${item.index}", model)
        self.assertIn("快照标识 ${item.snapshotId} 重复", model)
        self.assertIn("point.displayKey", view)
        self.assertIn("身份待核对", view)
        self.assertIn("身份重复", view)
        self.assertNotIn('key={`${point.snapshotId || "unknown"}-${point.index}`}', view)

    def test_timeline_visits_keep_missing_or_duplicate_identity_visible(self):
        view = self.subject_views_source
        model = self.subject_models_source
        self.assertIn("timelineVisitDisplayRows", view)
        self.assertIn("displayIdentityState", model)
        self.assertIn("displaySourceIndex", model)
        self.assertIn("timeline-visit:${identity || \"missing\"}:${displaySourceIndex}", model)
        self.assertIn("访视缺少 anchor_id/source identity", model)
        self.assertIn("访视 anchor_id/source identity 重复", model)
        self.assertIn("ambiguousVisitCount", view)
        self.assertIn("访视身份待核对", view)
        self.assertIn("key={item.displayKey}", view)
        self.assertNotIn("key={item.visit.anchorId ||", view)

    def test_profile_risk_prompts_keep_missing_or_duplicate_identity_visible(self):
        source = self.subject_views_source
        model = self.subject_models_source
        self.assertIn("riskPromptDisplayRows", source)
        self.assertIn("riskPromptDisplayKey", source)
        self.assertIn("displayIdentityState", model)
        self.assertIn("displaySourceIndex", model)
        self.assertIn("risk-prompt:${identity || \"missing\"}:${displaySourceIndex}", model)
        self.assertIn("风险提示缺少 prompt_id", model)
        self.assertIn("风险提示 prompt_id 重复", model)
        self.assertIn("身份待核对", source)
        self.assertIn("身份重复", source)
        self.assertNotIn("key={prompt.prompt_id || prompt.title}", source)

    def test_assurance_rollup_keeps_missing_or_duplicate_scope_identity_read_only(self):
        source = self.assurance_panel_source
        model = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "medicalMonitoringAssuranceRollup.mjs"
        ).read_text(encoding="utf-8")
        self.assertIn("assuranceRollupRowDisplayKey", source)
        self.assertIn("identityState", model)
        self.assertIn("displaySourceIndex", model)
        self.assertIn("assurance:${level}:${identity || \"missing\"}:${sourceIndex}", model)
        self.assertIn("身份待核对，仅可读", source)
        self.assertIn('row.identityState === "ready"', source)
        self.assertNotIn("key={row.siteId}", source)
        self.assertNotIn("key={row.subjectId}", source)

    def test_assurance_task_list_keeps_duplicate_task_ids_read_only(self):
        source = self.assurance_panel_source
        model = self.assurance_model_source
        self.assertIn("assuranceTaskDisplayKey", source)
        self.assertIn("identityState", model)
        self.assertIn("sourceIndex", model)
        self.assertIn("assurance-task:${identity}:${sourceIndex}", model)
        self.assertIn("身份重复，仅可读", source)
        self.assertIn('disabled={task.identityState !== "ready"}', source)
        self.assertIn('task.identityState === "ready"', source)
        self.assertNotIn("key={task.id}", source)

    def test_daily_ai_progress_requires_current_project_and_run_identity(self):
        panel = self.daily_run_panel_source
        view = self.daily_run_view_source
        self.assertIn("normalizeDailyRunAiProgress", view)
        self.assertIn("responseProjectId !== expectedProjectId", view)
        self.assertIn("responseRunId !== expectedRunId", view)
        self.assertIn("normalizeDailyRunAiProgress(rawAiProgress", panel)
        self.assertIn("runId: selected.run_id", panel)
        self.assertIn("已阻止写入当前运行", view)

    def test_daily_run_detail_requires_current_project_and_run_identity(self):
        panel = self.daily_run_panel_source
        view = self.daily_run_view_source
        self.assertIn("responseRunProjectId", view)
        self.assertIn("responseRunId !== expectedRunId", view)
        self.assertIn("normalizeDailyRunDetail(rawDetail, {", panel)
        self.assertIn("runId: selected.run_id", panel)
        self.assertIn("运行详情项目或运行身份不一致，已阻止写入当前运行", view)
        self.assertIn("运行详情缺少项目或运行身份，已阻止写入当前运行", view)

    def test_daily_run_list_requires_current_project_identity(self):
        panel = self.daily_run_panel_source
        view = self.daily_run_view_source
        self.assertIn("responseProjectId !== expectedProjectId", view)
        self.assertIn("item.project_id !== expectedProjectId", view)
        self.assertIn("currentBaseline.project_id !== expectedProjectId", view)
        self.assertIn("normalizeDailyRunList(rawList, { projectId })", panel)
        self.assertIn("运行列表项目身份不一致，已阻止写入当前运行列表", view)
        self.assertIn("运行记录项目身份不一致，已阻止写入当前运行列表", view)

    def test_daily_run_readiness_requires_current_project_and_batch_identity(self):
        panel = self.daily_run_panel_source
        view = self.daily_run_view_source
        self.assertIn("normalizeDailyRunReadiness", view)
        self.assertIn("responseBatchId !== expectedBatchId", view)
        self.assertIn("normalizeDailyRunReadiness(rawReadiness, {", panel)
        self.assertIn("batchId: batch.batch_id", panel)
        self.assertIn("就绪状态项目或批次身份不一致，已阻止写入当前运行", view)
        self.assertIn("就绪状态缺少下一步动作，暂不展示启动条件", view)

    def test_monitoring_counts_do_not_turn_an_unread_snapshot_into_zero(self):
        monitoring = self._monitoring_page()
        self.assertIn("const riskDataPending = !riskIndex && !riskIndexError;", monitoring)
        self.assertIn('riskReadUnavailable || riskDataPending', monitoring)
        self.assertIn('total={riskIndex ? riskIndex.total : null}', monitoring)
        self.assertNotIn('total={riskIndex?.total || 0}', monitoring)
        self.assertIn('当前条件展示 ${riskCountDisplay} 条医学风险', self.source)
        checklist = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "MedicalMonitoringRiskChecklist.jsx"
        ).read_text(encoding="utf-8")
        self.assertIn("const totalIsKnown = typeof total === \"number\"", checklist)
        self.assertIn("风险数量待读取", checklist)

    def test_overview_counts_wait_for_project_identity_and_missing_severity_values(self):
        overview = re.search(
            r"function OverviewPage\(.*?function AiGatewayPanel",
            self.source,
            re.S,
        )
        self.assertIsNotNone(overview, "overview page source not found")
        source = overview.group(0)
        self.assertIn("const dashboardReady = dashboard?.project?.project_id === projectId;", source)
        self.assertIn('data-dashboard-state="pending"', source)
        self.assertIn("当前不以初始化空值代替真实项目数据", source)
        self.assertIn("const riskCountValue = (severity) =>", source)
        self.assertIn('return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : "—";', source)
        self.assertIn("<strong>{riskCountValue(severity)}</strong>", source)
        self.assertNotIn("dashboard.risk_counts_by_severity?.[severity] ?? 0", source)

    def test_shared_ai_gateway_card_does_not_call_a_configured_but_blocked_route_ready(self):
        gateway = re.search(
            r"function AiGatewayPanel\(.*?function SourceHealthList",
            self.source,
            re.S,
        )
        self.assertIsNotNone(gateway, "AI gateway panel source not found")
        source = gateway.group(0)
        self.assertIn("status?.configured === true", source)
        self.assertIn("status?.semantic_ai_tasks_enabled === true", source)
        self.assertIn("const gatewayReady = configured && semanticAiReady;", source)
        self.assertIn('"已配置但不可运行"', source)
        self.assertIn("独立AI已配置，但未满足批准部署边界；医学监查语义任务保持阻断。", source)
        self.assertNotIn('{configured ? "已接入" : "未配置"}', source)

    def test_semantic_ai_readiness_is_not_inferred_from_generic_role_ready(self):
        self.assertIn("semantic_ai_tasks_enabled: ready", self.models_source)
        self.assertIn(
            "const ready = status?.semantic_ai_tasks_enabled === true;",
            self.models_source,
        )
        self.assertNotIn(
            "status?.ready === true || status?.semantic_ai_tasks_enabled === true",
            self.models_source,
        )
        protocol = self.protocol_preparation_panel_source
        self.assertIn(
            "const independentAiReady = aiStatus?.semantic_ai_tasks_enabled === true;",
            protocol,
        )
        self.assertNotIn("aiStatus?.ready === true", protocol)

    def test_assurance_task_creation_requires_server_verified_project_principal(self):
        source = self.assurance_panel_source
        self.assertIn("readPrincipal", source)
        self.assertIn("normalizeMonitoringPrincipal", source)
        self.assertIn("monitoringPrincipalReady", source)
        self.assertIn("&& principalReady", source)
        self.assertIn("monitoring_principal", source)
        self.assertIn("source.server_verified !== true", self.principal_source)
        self.assertIn("source.schema_version", self.principal_source)
        self.assertIn("does not include the active project", self.principal_source)
        self.assertIn("未返回服务端认证 principal", self.principal_source)
        self.assertIn("仅有 authority 不能创建保障任务", self.principal_source)

    def test_assurance_task_creation_does_not_send_client_actor(self):
        self.assertNotIn('actor: "medical_manager"', self.assurance_panel_source)

    def test_reselecting_the_same_listing_creates_a_fresh_intake_request(self):
        source = self.batch_panel_source
        self.assertIn('fileInputRef.current.value = "";', source)
        self.assertIn(
            'setIntakeKey(nextFile ? requestKey("monitoring-intake") : "");',
            source,
        )

    def test_field_mapping_panel_is_project_bound_and_cancels_stale_requests(self):
        source = self.field_mapping_panel_source
        self.assertIn("createMedicalMonitoringProjectRequestScope", source)
        self.assertIn('requestScope.begin("field-mapping-status")', source)
        self.assertIn('requestScope.begin("field-mapping-start")', source)
        self.assertIn('requestScope.begin("field-mapping-adopt")', source)
        self.assertIn('requestScope.begin("field-mapping-edit")', source)
        self.assertIn('requestScope.begin("field-mapping-confirm")', source)
        self.assertIn("requestScope.activate();", source)
        self.assertIn("return () => requestScope.dispose();", source)
        self.assertIn('requestScope.cancel("field-mapping-status");', source)
        self.assertIn("{ signal: request.signal }", source)
        self.assertIn("if (!requestScope.isCurrent(request)) return;", source)
        activation = source.index("useEffect(() => {\n    requestScope.activate();")
        initial_status = source.index(
            'useEffect(() => {\n    const request = requestScope.begin("field-mapping-status");',
        )
        self.assertLess(activation, initial_status)

    def test_field_mapping_evidence_rows_keep_display_keys_and_fail_closed_identity(self):
        source = self.field_mapping_panel_source
        model = self.field_mapping_view_source
        self.assertIn("medicalMonitoringFieldMappingEvidenceKey", source)
        self.assertIn("来源定位待核对", source)
        self.assertIn("来源证据身份缺失；不可据此确认映射", source)
        self.assertIn("sourceIndex: index", model)
        self.assertIn("evidence:${identity}:${sourceIndex}", model)
        self.assertNotIn("key={item.evidence_id}", source)

    def test_protocol_candidates_block_ambiguous_identity_decisions_and_use_display_keys(self):
        source = self.protocol_preparation_panel_source
        model = self.protocol_preparation_model_source
        self.assertIn("protocolPreparationCandidateIdentityReady", source)
        self.assertIn("!candidateIdentityReady", source)
        self.assertIn("候选身份缺失或重复，暂不能提交接受/驳回", source)
        self.assertIn("protocolPreparationTopicDisplayKey", source)
        self.assertIn("protocolPreparationCandidateDisplayKey", source)
        self.assertIn("protocolPreparationEvidenceDisplayKey", source)
        self.assertIn("seenCandidateIds", model)
        self.assertIn('"duplicate"', model)
        self.assertIn("protocolPreparationCandidateIdentityReady", model)
        self.assertNotIn("key={candidate.candidate_id}", source)
        self.assertNotIn(
            "key={evidence.evidence_id || `${evidence.locator}-${evidence.quote}`}",
            source,
        )

    def test_risk_detail_uses_backend_routes_and_state_aware_disposition_controls(self):
        detail = self._risk_detail()

        self.assertNotIn("onMarkRead", detail)
        self.assertNotIn("标记已读", detail)
        self.assertIn("onApplyDisposition", detail)
        self.assertIn("标记已复核", detail)
        self.assertIn("记录Query草稿", detail)
        self.assertIn("提交内部审批", detail)
        self.assertIn("expected_source_version", detail)
        self.assertIn("query_draft", detail)
        self.assertIn("submitted_for_approval", detail)
        self.assertIn("safeSourceRefLabel", self.source)
        self.assertIn("sourcePreviews", detail)
        self.assertIn("riskSourceGroups", detail)
        self.assertNotIn("title={ref.locator", detail)
        self.assertNotIn("接受不处理", detail)
        self.assertNotIn("正式关闭", detail)
        self.assertNotIn("已发中心", detail)
        self.assertNotIn("正式批准", detail)

    def test_medical_judgments_are_controlled_persisted_and_required_before_review(
        self,
    ):
        detail = self._risk_detail()

        self.assertIn("medicalJudgments", detail)
        self.assertIn("checked={Boolean(medicalJudgments[key])}", detail)
        self.assertIn("review_completed", detail)
        self.assertIn("medical_judgments", detail)
        self.assertIn("已完成以上四项医学判断", detail)
        self.assertNotIn("defaultChecked", detail)

    def test_read_actions_use_source_version_and_project_response_guards(self):
        monitoring = self._monitoring_page()

        self.assertIn("expected_source_version: risk.sourceVersion", monitoring)
        self.assertIn("expected_source_version: item.source_version", self.source)
        self.assertIn("activeProjectIdRef.current", self.source)
        self.assertIn("monitoringResponseProjectIdRef.current", self.source)
        self.assertIn(
            "payload.project_id === monitoringResponseProjectIdRef.current", self.source
        )
        self.assertIn(
            "const expectedMonitoringProjectId = sourceManifest?.project_id || monitoringProjectId;",
            monitoring,
        )
        self.assertIn("data?.project_id !== expectedMonitoringProjectId", monitoring)
        self.assertIn("payload?.project_id !== expectedMonitoringProjectId", monitoring)

    def test_batch_intake_is_delegated_to_project_bound_api_surface(self):
        monitoring = self._monitoring_page()
        self.assertIn("<MedicalMonitoringBatchPanel", monitoring)
        self.assertNotIn("/monitoring/intake", monitoring)
        self.assertIn("intakeBatchFile(projectId, file", self.batch_panel_source)
        self.assertIn("normalizeBatchIntakeResult", self.batch_panel_source)

    def test_content_confirmation_is_delegated_to_project_bound_api_surface(self):
        monitoring = self._monitoring_page()
        self.assertNotIn("content-validation/confirm", monitoring)
        self.assertIn("confirmSourceContent(projectId, pending.sourceEntryId", self.batch_panel_source)
        self.assertIn("normalizeContentConfirmationDetail", self.batch_panel_source)

    def test_identity_mismatch_is_visible_and_clears_affected_monitoring_state(self):
        monitoring = self._monitoring_page()
        for message in (
            "风险快照响应项目身份不匹配，已阻止写入当前监查视图。",
            "风险分类响应项目身份不匹配，已阻止写入当前监查视图。",
            "风险定位响应项目身份不匹配，已阻止写入当前监查视图。",
            "原始监查响应项目身份不匹配，已阻止写入当前项目数据。",
        ):
            self.assertIn(message, monitoring)
        self.assertIn("setRiskIndex(null);", monitoring)
        self.assertIn("setRiskTaxonomy(null);", monitoring)
        self.assertIn("setFocusedRiskRow(null);", monitoring)
        self.assertIn("setRawMonitoring(null);", monitoring)

    def test_monitoring_action_responses_require_current_project_identity(self):
        monitoring = self._monitoring_page()
        self.assertIn("payload?.project_id !== expectedMonitoringProjectId", monitoring)
        self.assertIn("result?.project_id !== expectedMonitoringProjectId", monitoring)
        self.assertIn("已读动作响应项目身份不匹配，未更新当前收件箱。", monitoring)
        self.assertIn("医学处置响应项目身份不匹配，未更新当前风险状态。", monitoring)

    def test_monitoring_internal_approval_refreshes_dashboard_and_uses_project_copy(
        self,
    ):
        monitoring = self._monitoring_page()

        self.assertIn(
            'if (action === "submitted_for_approval") refreshDashboard?.();', monitoring
        )
        self.assertIn(
            'item.target_type === "medical_monitoring_risk_disposition"', self.source
        )
        self.assertIn("approvalTitle(item, projectLabel)", self.source)
        self.assertIn("dashboard.project?.project_code", self.source)
        self.assertIn("item.display_title", self.source)
        self.assertIn("isMonitoringDisposition", self.source)
        self.assertNotIn("RUX内部Query草稿审批", self.source)
        self.assertNotIn("isRuxDisposition", self.source)
        self.assertIn("仅批准内部Query草稿/处置建议", self.source)
        self.assertNotIn("已完成医学批准并写入审计", self.source)

    def test_project_switch_clears_only_monitoring_project_state(self):
        self.assertIn(
            "const resetMedicalMonitoringProjectState = useCallback", self.source
        )
        self.assertIn("setMonitoringRouteState({});", self.source)
        self.assertIn('setMonitoringFocusRiskId("");', self.source)
        self.assertIn('setSubjectViewFocusRiskId("");', self.source)
        self.assertIn('setSelectedSubject("");', self.source)
        self.assertIn(
            "clearMedicalMonitoringRouteState(window.location.search)", self.source
        )
        self.assertIn("resetMedicalMonitoringProjectState(nextPage);", self.source)
        self.assertIn("key={monitoringRouteProjectId}", self.source)

    def test_dock_close_clears_risk_focus_without_resetting_the_checklist(self):
        monitoring = self._monitoring_page()
        self.assertIn("const closeRiskEvidenceDock = () =>", monitoring)
        self.assertIn('setSelectedRiskId("");', monitoring)
        self.assertIn("onRiskFocusClear?.();", monitoring)
        self.assertIn("onClose={closeRiskEvidenceDock}", monitoring)
        self.assertIn("clearMedicalMonitoringRiskFocusState(current)", self.source)
        self.assertNotIn("onClose={() => setRiskDockOpen(false)}", monitoring)

    def test_opening_batch_workspace_closes_the_risk_evidence_dock(self):
        monitoring = self._monitoring_page()
        self.assertIn("const toggleBatchWorkspace = () =>", monitoring)
        self.assertIn("if (riskDockOpen) closeRiskEvidenceDock();", monitoring)
        self.assertIn("setUploadGateOpen(true);", monitoring)
        self.assertIn("onClick={toggleBatchWorkspace}", monitoring)
        self.assertNotIn(
            "onClick={() => setUploadGateOpen((open) => !open)}",
            monitoring,
        )

    def test_monitoring_content_confirmation_preserves_source_file_and_mismatch_state(
        self,
    ):
        panel = self.batch_panel_source

        self.assertIn("if (!file) return;", panel)
        self.assertIn("intakeBatchFile(projectId, file", panel)
        self.assertNotIn("setFile(null)", panel)
        self.assertIn("validation: contentDetail.validation", panel)
        self.assertIn("normalizeContentConfirmationDetail(detail)", panel)
        self.assertIn("idempotencyKey: currentKey", panel)
        self.assertIn("acknowledged_check_codes: acknowledgedCodes", panel)
        self.assertIn("expected_revision: pending.validation.revision", panel)
        self.assertIn("await retryIntake();", panel)
        self.assertIn("确认并继续", panel)

    def test_monitoring_content_confirmation_is_full_width_and_reset_on_file_change_or_close(
        self,
    ):
        monitoring = self._monitoring_page()
        panel = self.batch_panel_source
        styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("setPendingConfirmation(null);", panel)
        self.assertIn('setOverrideReason("");', panel)
        self.assertIn("setAcknowledgedCodes([]);", panel)
        self.assertIn('className="monitoring-batch-confirmation"', panel)
        self.assertIn("onClose={() => setUploadGateOpen(false)}", monitoring)
        self.assertRegex(
            styles,
            r"\.monitoring-batch-workspace\s*\{[^}]*display:\s*grid",
            re.S,
        )

    def test_batch_panel_initial_load_does_not_split_request_slot_or_leave_busy_stuck(self):
        panel = self.batch_panel_source

        self.assertNotIn('requestScope.begin("initial-batch-load")', panel)
        self.assertIn("let mounted = true;", panel)
        self.assertIn("loadBatches()", panel)
        self.assertIn("if (mounted) setBusy(false);", panel)
        self.assertIn('requestScope.cancel("batch-view");', panel)

    def test_batch_panel_activates_request_scope_before_initial_batch_load(self):
        panel = self.batch_panel_source

        activate_index = panel.index("requestScope.activate();")
        load_index = panel.index("loadBatches()")
        self.assertLess(
            activate_index,
            load_index,
            "strict-mode remounts must reactivate the scope before loading batches",
        )

    def test_assurance_panel_activates_request_scope_before_open_task_load(self):
        panel = self.assurance_panel_source

        activate_index = panel.index("requestScope.activate();")
        task_load_index = panel.index("loadTasks(mode);")
        self.assertLess(
            activate_index,
            task_load_index,
            "assurance task loading must follow request-scope activation",
        )

    def test_patient_profile_trend_points_open_bound_raw_fact_inspector(self):
        views = self.subject_views_source

        for token in (
            "trendPointRawValue",
            "trendPointReferenceRange",
            "trendPointClinicalSignificance",
            "trendPointSourceText",
            "trendPointRiskLabel",
            "role=\"group\"",
            "role=\"button\"",
            "aria-pressed={selectedPointKey === key}",
            "subjectSourceLocatorState(selectedPoint).locator",
            "来源定位存在不等于来源真实性或风险已确认",
        ):
            self.assertIn(token, views)
        self.assertIn("数据点原始事实", views)
        self.assertIn("原始值", views)
        self.assertIn("来源正文", views)
        self.assertIn("关联风险", views)

    def test_subject_timeline_selection_uses_display_only_stable_keys(self):
        views = self.subject_views_source
        model = self.subject_models_source
        timeline = re.search(
            r"export function SubjectTimelinePage\(.*?function ProfileDomainCoverage",
            views,
            re.S,
        )
        self.assertIsNotNone(timeline, "SubjectTimelinePage source not found")
        timeline_source = timeline.group(0)
        self.assertIn("timelineEventSelectionKey", model)
        self.assertIn("selectionKey", model)
        self.assertIn("const usedSelectionKeys = new Set()", model)
        self.assertIn("selectedEventId === selectionKey", timeline_source)
        self.assertIn("find(({ selectionKey }) => selectionKey === selectedEventId)", timeline_source)
        self.assertNotIn("selectedEventId === event.event_id", timeline_source)
        self.assertNotIn("key={event.event_id}", timeline_source)
        self.assertIn("来源定位", views)

    def test_subject_timeline_events_open_bound_raw_fact_inspector(self):
        views = self.subject_views_source

        for token in (
            "selectedEventId",
            "onEventSelect",
            "timeline-event-interactive",
            "aria-pressed={isSelected}",
            "timelineEventSourceText",
            "timelineEventRiskLabel",
            "timeline-event-inspector",
            "来源定位存在不等于来源真实性或风险已确认",
        ):
            self.assertIn(token, views)
        self.assertIn("事件类别", views)
        self.assertIn("原始事实", views)
        self.assertIn("来源正文", views)
        self.assertIn("关联风险", views)

    def test_patient_profile_event_indexes_use_display_only_event_keys(self):
        views = self.subject_views_source
        self.assertIn("timelineEventSelectionKey", views)
        self.assertIn("profile-query:${timelineEventSelectionKey", views)
        self.assertIn("profile-index:${timelineEventSelectionKey", views)
        self.assertNotIn("key={event.event_id}", views)

    def test_subject_catalog_keeps_missing_or_duplicate_identity_visible_but_not_selectable(self):
        views = self.subject_views_source
        model = self.subject_models_source
        self.assertIn("subjectCatalogDisplayRows", views)
        self.assertIn("subjectCatalogSubjectId", views)
        self.assertIn("displayIdentityState", model)
        self.assertIn("displaySourceIndex", model)
        self.assertIn("subject-catalog:${identity || \"missing\"}:${displaySourceIndex}", model)
        self.assertIn("受试者缺少 subject_id/id", model)
        self.assertIn("受试者 subject_id/id 重复", model)
        self.assertIn("disabled={ambiguous}", views)
        self.assertIn("aria-disabled={ambiguous ? \"true\" : undefined}", views)
        self.assertIn("if (!ambiguous) setSelectedSubject(subjectId)", views)
        self.assertNotIn("<option key={item.id}", views)
        self.assertNotIn("<button key={item.id}", views)

    def test_batch_catalog_keeps_duplicate_batch_identity_visible_but_not_selectable(self):
        panel = self.batch_panel_source
        model = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "medicalMonitoringBatchView.mjs"
        ).read_text(encoding="utf-8")
        self.assertIn("batchDisplayKey", model)
        self.assertIn("displaySourceIndex", model)
        self.assertIn("displayIdentityState", model)
        self.assertIn("batch_id 重复", model)
        self.assertIn("batch:${identity}:${index}", model)
        self.assertIn("displayIdentityState === \"ready\"", panel)
        self.assertIn("disabled={ambiguous}", panel)
        self.assertIn("aria-disabled={ambiguous ? \"true\" : undefined}", panel)
        self.assertIn("if (!ambiguous) selectBatch(batch.batch_id)", panel)
        self.assertNotIn("key={batch.batch_id}", panel)

    def test_protocol_version_selector_keeps_missing_or_duplicate_identity_read_only(self):
        panel = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "MedicalMonitoringProtocolPreparationPanel.jsx"
        ).read_text(encoding="utf-8")
        model = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "medicalMonitoringProtocolPreparation.mjs"
        ).read_text(encoding="utf-8")
        self.assertIn("protocolPreparationVersionDisplayKey", model)
        self.assertIn("displayIdentityState", model)
        self.assertIn("displaySourceIndex", model)
        self.assertIn("protocol-version:${identity}:${index}", model)
        self.assertIn("方案版本缺少 protocol_version_id", model)
        self.assertIn("方案版本 protocol_version_id 重复", model)
        self.assertIn("version.displayIdentityState === \"ready\"", panel)
        self.assertIn("disabled={ambiguous}", panel)
        self.assertNotIn("key={version.protocol_version_id}", panel)

    def test_scope_summary_blocks_ambiguous_scope_identity_before_focus(self):
        source = self.scope_summary_source
        model = self.scope_summary_model_source
        self.assertIn("medicalMonitoringScopeRowKey", source)
        self.assertIn("!row.identityAmbiguous", source)
        self.assertIn("中心或受试者标识重复", source)
        self.assertIn("标识重复", source)
        self.assertIn("seenScopeIds", model)
        self.assertIn("identityIssues", model)
        self.assertIn("已阻止歧义行聚焦", model)
        self.assertNotIn('key={`${level}-${row.scopeId || row.label}`}', source)


if __name__ == "__main__":
    unittest.main()
