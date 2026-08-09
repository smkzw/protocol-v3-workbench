from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendUnifiedRiskWorkbenchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app_source = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
        cls.models_source = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "medicalMonitoringModels.mjs"
        ).read_text(encoding="utf-8")
        cls.checklist_source = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "MedicalMonitoringRiskChecklist.jsx"
        ).read_text(encoding="utf-8")
        cls.checklist_state_source = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "medicalMonitoringChecklistState.mjs"
        ).read_text(encoding="utf-8")
        cls.subject_views_source = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "MedicalMonitoringSubjectViews.jsx"
        ).read_text(encoding="utf-8")
        cls.subject_models_source = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-monitoring"
            / "medicalMonitoringSubjectModels.mjs"
        ).read_text(encoding="utf-8")
        cls.styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    def test_monitoring_page_loads_project_risk_index_and_renders_dense_checklist(self) -> None:
        self.assertIn("getRiskSnapshot", self.app_source)
        self.assertIn("riskIndexControllerRef", self.app_source)
        self.assertIn("cancelRiskIndexLoad", self.app_source)
        self.assertIn("retryRiskIndex", self.app_source)
        self.assertIn("当前页面保留上一份结果", self.app_source)
        self.assertIn("<MedicalMonitoringBatchPanel", self.app_source)
        self.assertIn("intakeBatchFile(projectId, file", (
            ROOT / "frontend" / "src" / "features" / "medical-monitoring" / "MedicalMonitoringBatchPanel.jsx"
        ).read_text(encoding="utf-8"))
        self.assertNotIn('fetch(`/api/projects/${projectId}/monitoring/risks?', self.app_source)
        self.assertIn("riskIndex?.work_items", self.app_source)
        self.assertIn('className="risk-scope-switch"', self.app_source)
        self.assertIn('className="monitoring-command-surface"', self.app_source)
        self.assertIn('className="monitoring-boundary-note"', self.app_source)
        self.assertNotIn('className="mapping-alert"', self.app_source)
        self.assertIn("<MedicalMonitoringRiskChecklist", self.app_source)
        self.assertIn('className="risk-checklist-table"', self.checklist_source)
        for label in (
            "受试者编号",
            "中心编号",
            "风险级别",
            "风险类别",
            "具体风险项",
            "当前处置",
            "更新时间",
        ):
            self.assertIn(label, self.checklist_state_source)
        table_source = self.checklist_source
        for removed_label in ("关键理由", "来源完整度", "批次变化", "触发时间窗", "负责人"):
            self.assertNotIn(removed_label, table_source)
        self.assertIn('className="risk-checklist-filter-popover"', table_source)
        self.assertIn('className="risk-checklist-filter-chips"', table_source)
        self.assertIn("aria-sort", table_source)
        self.assertIn("导出当前筛选风险及证据", table_source)
        self.assertIn("<Download", table_source)
        self.assertIn("risk.dispositionState || risk.disposition_state || risk.status", table_source)
        self.assertIn("riskDispositionStatusLabel", table_source)
        self.assertIn("exportRiskSnapshot", self.app_source)
        self.assertIn("onExport={exportCurrentRiskSnapshot}", self.app_source)
        self.assertIn("onRetry={retryRiskIndex}", self.app_source)
        self.assertIn("重试读取", self.checklist_source)
        self.assertIn(".risk-checklist-table", self.styles)
        self.assertIn(".risk-checklist-actions", self.styles)
        self.assertIn("grid-template-columns", self.styles)

    def test_risk_evidence_dock_and_all_disposition_branches_are_exposed(self) -> None:
        for label in (
            "风险处置",
            "Subject Timeline",
            "Patient Profile",
            "AE/MH核查",
            "来源证据",
        ):
            self.assertIn(label, self.app_source)
        for branch in (
            "explained_no_external_action",
            "center_query",
            "data_correction",
            "follow_up",
            "pd_update",
            "safety_pv_collaboration",
            "continue_observation",
            "duplicate_not_applicable",
        ):
            self.assertIn(branch, self.app_source)
        self.assertIn(".risk-evidence-dock", self.styles)

    def test_non_query_dispositions_render_terminal_status_instead_of_query_dead_end(self) -> None:
        self.assertIn("terminalDispositionLabels", self.app_source)
        self.assertIn("export const terminalDispositionLabels", self.models_source)
        self.assertIn('dispositionKind === "center_query" ? "标记已复核" : "完成医学处置"', self.app_source)
        self.assertIn("[...indexedActionRows, ...realInboxRiskRows]", self.app_source)
        self.assertIn("Array.isArray(riskIndex?.rollup?.sites)", self.app_source)
        self.assertIn("Array.isArray(riskIndex?.rollup?.subjects)", self.app_source)
        self.assertIn("siteRiskRollups.find", self.app_source)
        self.assertIn("subjectRiskRollups.find", self.app_source)
        self.assertIn("riskIndex?.rollup?.trial", self.app_source)
        self.assertIn("待行动 {riskOpenCountDisplay}", self.app_source)
        for status in (
            "已说明，无需外部动作",
            "已转数据更正",
            "已转追加随访",
            "已转PD补充/更新",
            "已转Safety/PV协作",
            "持续观察",
            "重复项/不适用",
        ):
            self.assertIn(status, self.models_source)

    def test_risk_evidence_dock_reuses_full_timeline_and_profile_with_exact_focus(self) -> None:
        self.assertIn("function EmbeddedRiskTimeline", self.app_source)
        self.assertIn("function EmbeddedRiskProfile", self.app_source)
        self.assertIn("focusRiskId={risk.id}", self.app_source)
        self.assertIn("event.related_risk_ids?.includes(focusRiskId)", self.app_source)
        self.assertIn("point.related_risk_ids?.includes(focusRiskId)", self.app_source)
        self.assertIn("risk-focus-event", self.app_source)
        self.assertIn("risk-focus-point", self.subject_views_source)
        self.assertIn(".risk-focus-event", self.styles)
        self.assertIn(".risk-focus-point", self.styles)

    def test_subject_profile_shape_is_normalized_and_visible_before_timeline_or_profile_render(self) -> None:
        self.assertIn("normalizeMonitoringSubjectProfile", self.app_source)
        self.assertIn("const normalizedProfile = normalizeMonitoringSubjectProfile(profile)", self.app_source)
        self.assertIn("profile_shape_warnings", self.subject_views_source)
        self.assertIn("个例数据字段形状异常", self.subject_views_source)
        self.assertIn("profile-data-warning", self.subject_views_source)
        self.assertIn("capability_mode", self.subject_views_source)
        self.assertIn("受限模式", self.subject_views_source)
        self.assertIn("normalizeRecordArray", self.subject_models_source)
        self.assertIn("normalizeMetricArray", self.subject_models_source)
        self.assertIn("normalizeStringMap", self.subject_models_source)
        self.assertIn("profile-data-warning", self.styles)

    def test_source_evidence_is_grouped_by_protocol_and_listing_locator(self) -> None:
        self.assertIn("function riskSourceGroups", self.app_source)
        self.assertIn("方案依据", self.app_source)
        self.assertIn("原始数据", self.app_source)
        self.assertIn("risk.evidenceLocators", self.app_source)
        groups_source = self.app_source[
            self.app_source.index("function riskSourceGroups"):
            self.app_source.index("function canOpenRiskSource")
        ]
        self.assertIn("function riskSourceText", groups_source)
        self.assertIn('typeof value === "string"', groups_source)
        self.assertNotIn("String(locator)", groups_source)
        self.assertLess(groups_source.index('key: "listing"'), groups_source.index('key: "protocol"'))
        self.assertNotIn('"protocol_rule"', groups_source)

    def test_disposition_shows_source_body_without_project_specific_fallback(self) -> None:
        risk_detail = self.app_source[
            self.app_source.index("function RiskDetail"):
            self.app_source.index("const timelineLaneDefs")
        ]
        self.assertIn("<h3>核心证据</h3>", risk_detail)
        self.assertIn("sourcePreviews[ref.locator]", risk_detail)
        self.assertIn("当前风险未绑定可直接展示的原始数据或方案正文", risk_detail)
        self.assertNotIn("抗组胺药随机前需停用 4 天", risk_detail)
        self.assertNotIn("原始 CM listing 行", risk_detail)
        self.assertNotIn("标记已读", risk_detail)
        self.assertIn("{subject && <div className=\"subject-shortcut\">", risk_detail)

    def test_source_completeness_is_not_a_prominent_detail_badge(self) -> None:
        dock_source = self.app_source[
            self.app_source.index("function RiskEvidenceDock"):
            self.app_source.index("function riskQueryDraft")
        ]
        self.assertNotIn("来源完整度", dock_source)

    def test_source_locator_opens_current_risk_bound_read_only_fragment(self) -> None:
        self.assertIn("evidence-fragment?", self.app_source)
        self.assertIn("sourceFragmentRequestId", self.app_source)
        self.assertIn("sourcePreviewRequestId", self.app_source)
        self.assertIn("primary_summary", self.app_source)
        self.assertIn("关联风险：", self.app_source)
        self.assertIn("溯源：", self.app_source)
        self.assertIn("查看原文", self.app_source)
        self.assertIn("只读来源原文片段", self.app_source)
        self.assertIn(".source-fragment-panel", self.styles)
        sources_view = self.app_source[
            self.app_source.index('activeTab === "sources"'):
            self.app_source.index('activeTab === "history"')
        ]
        self.assertLess(sources_view.index("source-fragment-panel"), sources_view.index("risk-source-groups"))
        self.assertIn('aria-live="polite"', sources_view)
        context_rule = self.styles[
            self.styles.index(".source-fragment-context p"):
            self.styles.index(".source-fragment-fields")
        ]
        self.assertIn("grid-column: 2", context_rule)

    def test_risk_evidence_responses_require_canonical_project_identity(self) -> None:
        dock_source = self.app_source[
            self.app_source.index("function RiskEvidenceDock"):
            self.app_source.index("function riskQueryDraft")
        ]
        self.assertIn("canonicalProjectId={expectedMonitoringProjectId}", self.app_source)
        self.assertIn("const expectedEvidenceProjectId = canonicalProjectId || projectId;", dock_source)
        self.assertIn("payload?.project_id !== expectedEvidenceProjectId", dock_source)
        self.assertIn("fragment?.project_id !== expectedEvidenceProjectId", dock_source)
        self.assertIn("批次历史响应项目身份不匹配，已阻止写入当前风险证据视图。", dock_source)
        self.assertIn("来源证据响应项目身份不匹配，已阻止写入当前风险证据视图。", dock_source)
        self.assertIn("原文片段响应项目身份不匹配，已阻止写入当前风险证据视图。", dock_source)
        self.assertIn("setRiskHistory(null);", dock_source)
        self.assertIn("setSourcePreviews({});", dock_source)
        self.assertIn('role="alert"', dock_source)

    def test_malformed_source_shape_is_visible_and_never_treated_as_evidence(self) -> None:
        self.assertIn("sourceEvidenceShape", self.app_source)
        self.assertIn("risk-evidence-shape-warning", self.app_source)
        self.assertIn("未按有效证据展示", self.app_source)
        self.assertIn("Array.isArray(risk.sourceRefs)", self.app_source)
        self.assertIn("Array.isArray(risk.evidenceLocators)", self.app_source)
        self.assertIn(".risk-evidence-shape-warning", self.styles)

    def test_risk_index_fetches_every_page_and_checklist_exposes_column_sort_and_filter(self) -> None:
        self.assertIn("async function fetchCompleteMonitoringRiskIndex", self.app_source)
        self.assertIn("api.getModuleSummary(projectId)", self.app_source)
        self.assertIn("riskPage(page, first.snapshot_id)", self.app_source)
        self.assertIn("items.length !== first.total", self.app_source)
        self.assertIn("riskChecklistCategoryTags", self.checklist_source)
        self.assertIn("toggleSort", self.checklist_source)
        self.assertIn("openFilterKey", self.checklist_source)
        self.assertIn("清除全部", self.checklist_source)
        self.assertIn("resetRiskChecklistForQueryChange", self.checklist_source)
        self.assertIn("riskChecklistApiQuery", self.app_source)
        table_source = self.checklist_source
        for column in ("受试者编号", "中心编号", "风险级别", "风险类别", "具体风险项", "当前处置", "更新时间"):
            self.assertIn(column, self.checklist_state_source)
        for removed_column in ("关键理由", "来源完整度", "负责人", "触发时间窗", "批次变化"):
            self.assertNotIn(removed_column, table_source)

    def test_checklist_fails_closed_on_malformed_rows_taxonomy_counts_and_refresh(self) -> None:
        table_source = self.checklist_source
        self.assertIn("function taxonomyCategoryRows", table_source)
        self.assertIn("Array.isArray(taxonomy?.categories)", table_source)
        self.assertIn("typeof item === \"object\" && !Array.isArray(item)", table_source)
        self.assertIn("const safeRows = Array.isArray(rows)", table_source)
        self.assertIn("const safeTotal = totalIsKnown ? total : 0", table_source)
        self.assertIn("const totalIsKnown = typeof total === \"number\"", table_source)
        self.assertIn("风险数量待读取", table_source)
        self.assertIn("const locked = new Set(Array.isArray(lockedFilterKeys) ? lockedFilterKeys : [])", table_source)
        self.assertIn("loading && safeRows.length === 0", table_source)
        self.assertIn(": safeRows.map((risk) => (", table_source)
        self.assertIn("!loading && !safeRows.length && !error", table_source)
        self.assertIn("onRefreshCurrent?.()", table_source)
        self.assertIn("function riskRowAccessibleLabel", table_source)
        self.assertIn("aria-selected={selectedRiskId === risk.id}", table_source)
        self.assertIn("hasReportedRowsButNoSafeRows", table_source)
        self.assertIn("接口报告 {safeTotal} 条，不能据此判定无风险", table_source)
        self.assertIn("risk-checklist-shape-warning", table_source)
        self.assertIn("aria-label={riskRowAccessibleLabel(risk)}", table_source)
        self.assertIn('event.key !== "Enter" && event.key !== " "', table_source)
        self.assertIn("event.preventDefault();", table_source)

    def test_dashboard_and_safety_are_read_only_monitoring_consumers(self) -> None:
        overview_source = self.app_source[
            self.app_source.index("function OverviewPage"):
            self.app_source.index("function AiGatewayPanel")
        ]
        safety_source = self.app_source[
            self.app_source.index("async function fetchCompleteMonitoringRiskIndex"):
            self.app_source.index("function monitoringRiskQueryErrorText")
        ]
        self.assertIn("dashboard.risk_counts_by_severity", overview_source)
        self.assertNotIn("runMonitoring", overview_source)
        self.assertNotIn("/monitoring/risks", overview_source)
        self.assertIn("api.getModuleSummary(projectId)", safety_source)
        self.assertIn("api.getRiskSnapshot(projectId", safety_source)
        self.assertIn("riskPage(page, first.snapshot_id)", safety_source)
        self.assertNotIn("/monitoring/risks", safety_source)

    def test_checklist_category_uses_one_primary_reason_with_optional_safety_marker(self) -> None:
        category_source = self.models_source[
            self.models_source.index("function riskChecklistCategoryTags"):
            self.models_source.index("function riskChecklistUpdatedDate")
        ]
        self.assertIn("risk.riskCategoryLabel || risk.risk_category_label", category_source)
        self.assertIn('UNKNOWN_RISK_CATEGORY_LABEL = "其他医学复核"', self.models_source)
        self.assertIn("return label || UNKNOWN_RISK_CATEGORY_LABEL;", self.models_source)
        self.assertIn("risk.safetyPvFlag ?? risk.safety_pv_flag", category_source)
        self.assertIn('categories.push("Safety/PV")', category_source)
        for forbidden in ("risk.title", "risk.rationale", "risk.tags", ".match(", ".test("):
            self.assertNotIn(forbidden, category_source)

    def test_risk_dock_reads_cross_batch_history_without_reusing_old_state(self) -> None:
        self.assertIn("function RiskHistoryView", self.app_source)
        self.assertIn('["history", "批次历史"]', self.app_source)
        self.assertIn("risk.riskKey", self.app_source)
        self.assertIn("history.boundary_note", self.app_source)
        self.assertIn("查看当时证据", self.app_source)
        self.assertIn("基于该结论重新评估", self.app_source)
        self.assertIn("已引用历史处置作为可编辑草稿", self.app_source)
        self.assertIn("reassessment_change_reason", self.app_source)
        self.assertIn("该旧快照未冻结原文，系统不会以当前文件内容替代。", self.app_source)
        self.assertIn("entry.transition?.supersedes_risk_instance_id", self.app_source)
        self.assertIn("旧处置仅作历史上下文", self.app_source)
        self.assertIn(".risk-history-table", self.styles)
        self.assertIn(".risk-history-evidence", self.styles)


if __name__ == "__main__":
    unittest.main()
