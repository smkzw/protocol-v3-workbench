from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend" / "src" / "App.jsx"
STYLE_SOURCE = ROOT / "frontend" / "src" / "styles.css"
SUBJECT_MODEL_SOURCE = (
    ROOT / "frontend" / "src" / "features" / "medical-monitoring" / "medicalMonitoringSubjectModels.mjs"
)
SUBJECT_VIEW_SOURCE = (
    ROOT / "frontend" / "src" / "features" / "medical-monitoring" / "MedicalMonitoringSubjectViews.jsx"
)


class FrontendTimelineContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_SOURCE.read_text(encoding="utf-8")
        cls.styles = STYLE_SOURCE.read_text(encoding="utf-8")
        cls.subject_models = SUBJECT_MODEL_SOURCE.read_text(encoding="utf-8")
        cls.subject_views = SUBJECT_VIEW_SOURCE.read_text(encoding="utf-8")

    def _lane_def(self, key: str) -> str:
        match = re.search(rf'\{{\s*key:\s*"{re.escape(key)}".*?\}}', self.subject_models, re.S)
        self.assertIsNotNone(match, f"missing timeline lane {key}")
        return match.group(0)

    def test_dose_adjustment_uses_separate_investigational_product_lane(self):
        ip_lane = self._lane_def("IP")

        self.assertIn('label: "试验药物"', ip_lane)
        self.assertIn('"dose_adjustment"', ip_lane)
        self.assertIn('"study_drug_dispensing"', ip_lane)
        self.assertIn('"study_drug_administration"', ip_lane)
        self.assertIn('"study_drug_adherence"', ip_lane)

    def test_concomitant_medication_lane_excludes_investigational_product_changes(self):
        cm_lane = self._lane_def("CM")

        self.assertIn('label: "合并用药（非试验用药）"', cm_lane)
        self.assertIn('"concomitant_medication"', cm_lane)
        self.assertNotIn("dose_adjustment", cm_lane)
        self.assertNotIn("试验药物", cm_lane)
        self.assertNotIn("给药调整", cm_lane)

    def test_dose_adjustment_has_compact_da_prefix(self):
        prefix_map = re.search(r"const prefix = \{(?P<body>.*?)\}\[event\.event_type\]", self.subject_models, re.S)
        self.assertIsNotNone(prefix_map, "shortTimelineEventLabel prefix map not found")

        self.assertIn('dose_adjustment: "DA"', prefix_map.group("body"))

    def test_core_timeline_lanes_keep_trial_drug_lane_visible_when_present(self):
        self.assertIn('const coreLaneKeys = new Set(["AE", "IP", "CM", "MH"])', self.subject_models)

    def test_feature_timeline_lane_model_keeps_trial_drug_changes_out_of_cm(self):
        model = self.subject_models
        self.assertIn("export function referenceTimelineLanes", model)
        self.assertIn("filter((event) => laneForEvent(event) === lane.key)", model)
        self.assertIn('const coreLaneKeys = new Set(["AE", "IP", "CM", "MH"])', model)
        ip_lane = self._lane_def("IP")
        cm_lane = self._lane_def("CM")
        self.assertIn('"dose_adjustment"', ip_lane)
        self.assertNotIn('"concomitant_medication"', ip_lane)
        self.assertIn('"concomitant_medication"', cm_lane)
        self.assertNotIn("dose_adjustment", cm_lane)
        self.assertNotIn("试验药物", cm_lane)
        self.assertNotIn("给药调整", cm_lane)

    def test_legacy_subject_view_maps_real_event_types_to_product_lanes(self):
        build_subject_view = re.search(
            r"function buildSubjectView\(.*?function formatBatchDisplay",
            self.source,
            re.S,
        )
        self.assertIsNotNone(build_subject_view, "buildSubjectView not found")
        view_source = build_subject_view.group(0)

        self.assertIn("lane: laneForEvent(event)", view_source)
        self.assertNotIn("lane: event.source_domain || event.event_type", view_source)

    def test_subject_view_loading_fallback_keeps_patient_profile_collection_contracts(self):
        build_subject_view = re.search(
            r"function buildSubjectView\(.*?function formatBatchDisplay",
            self.source,
            re.S,
        )
        self.assertIsNotNone(build_subject_view, "buildSubjectView not found")
        view_source = build_subject_view.group(0)

        self.assertIn("...local", view_source)
        for collection in ["efficacyMetrics", "safetyMetrics", "labs", "queries", "prompts", "reviewFocus"]:
            self.assertRegex(view_source, rf"{collection}:\s*\[\]")
        self.assertRegex(view_source, r"timeline:\s*\[\]")
        self.assertIn('timelineUnavailableReason: "个例资料尚未载入；当前未生成 Subject Timeline 事件。"', view_source)
        self.assertNotIn('label: "暂无 Subject Timeline"', view_source)
        self.assertIn("risks: risk ? [risk.title] : []", view_source)
        self.assertIn("当前暂无风险提示。", self.subject_views)

    def test_sparse_subject_pages_distinguish_unloaded_profile_from_empty_clinical_data(self):
        self.assertIn("const profileUnavailable = !rawProfile;", self.subject_views)
        self.assertIn("Timeline 事件集合保持为空，不能据此判定无风险", self.subject_views)
        self.assertIn("各数据域保持为空，不能据此判定疗效稳定、安全性稳定或无风险", self.subject_views)
        self.assertIn("不能据此判定没有开放 PD / Query", self.subject_views)
        self.assertIn("不能据此判定暂无风险提示", self.subject_views)
        self.assertIn("不能据此判定没有可索引事件", self.subject_views)
        self.assertIn("空态不代表无风险", self.subject_views)

    def test_reference_timeline_events_are_colored_by_lane_category(self):
        self.assertIn("function timelineLaneClassName", self.subject_models)
        self.assertIn("${timelineLaneClassName(lane.key)}", self.subject_views)

        lane_colors = {}
        for lane in ["ae", "ip", "cm", "mh", "lab", "pd-query"]:
            match = re.search(
                rf"\.reference-svg-event-block\.lane-{lane}\s*\{{(?P<body>.*?)\}}",
                self.styles,
                re.S,
            )
            self.assertIsNotNone(match, f"missing CSS color rule for lane {lane}")
            fill = re.search(r"--lane-fill:\s*(?P<value>#[0-9a-fA-F]{6})", match.group("body"))
            self.assertIsNotNone(fill, f"missing fill token for lane {lane}")
            lane_colors[lane] = fill.group("value").lower()

        self.assertEqual(len(lane_colors), len(set(lane_colors.values())), lane_colors)

    def test_timeline_zoom_enlarges_rendered_canvas_without_expanding_viewbox(self):
        self.assertIn(
            "const width = Math.round(Math.max(1500, Math.min(3200, 420 + spanDays * 7)));",
            self.subject_views,
        )
        self.assertNotIn("spanDays * 7)) * zoom", self.subject_views)
        self.assertIn(
            'style={{ width: `${Math.round(width * zoom)}px`, maxWidth: "none" }}',
            self.subject_views,
        )
        self.assertIn("const minimumEventWidth = 16;", self.subject_views)
        self.assertIn("tracks.push(packedEndX);", self.subject_views)
        self.assertIn("Math.max(16,", self.subject_views)

    def test_timeline_event_categories_have_distinct_colors_in_graph_legend_and_details(self):
        self.assertIn("function eventCategoryClassName", self.subject_models)
        self.assertIn("function timelineEventCategoryLabel", self.subject_models)
        self.assertIn("function timelineEventCategoryKey", self.subject_models)
        self.assertIn("timelineLegendItems(displayLanes)", self.subject_views)
        self.assertIn("function timelineLegendLabel", self.subject_models)
        self.assertIn("timelineLegendLabel(item)", self.subject_views)
        self.assertIn('className="timeline-category-legend"', self.subject_views)
        self.assertIn("${eventCategoryClassName(event)}", self.subject_views)
        self.assertIn("timeline-detail-row ${eventCategoryClassName(event)}", self.subject_views)

        category_colors = {}
        for category in [
            "adverse-event",
            "dose-adjustment",
            "concomitant-medication",
            "medical-history",
            "lab",
            "efficacy-score",
            "protocol-deviation",
            "query",
        ]:
            match = re.search(
                rf"\.event-category-{category}\s*\{{(?P<body>.*?)\}}",
                self.styles,
                re.S,
            )
            self.assertIsNotNone(match, f"missing category color rule for {category}")
            fill = re.search(r"--category-fill:\s*(?P<value>#[0-9a-fA-F]{6})", match.group("body"))
            self.assertIsNotNone(fill, f"missing category fill token for {category}")
            category_colors[category] = fill.group("value").lower()

        self.assertEqual(len(category_colors), len(set(category_colors.values())), category_colors)

    def test_timeline_event_visual_categories_split_real_subtypes_inside_lanes(self):
        category_key_function = re.search(
            r"function timelineEventCategoryKey\(event\) \{(?P<body>.*?)\n\}",
            self.subject_models,
            re.S,
        )
        self.assertIsNotNone(category_key_function, "timelineEventCategoryKey not found")
        body = category_key_function.group("body")

        self.assertIn('event.event_type === "dose_adjustment"', body)
        self.assertIn("暂停用药", body)
        self.assertIn("重新用药", body)
        self.assertIn('event.source_domain === "LBHEMA"', body)
        self.assertIn('event.source_domain === "LBCHEM"', body)

        lane_subtype_categories = {
            "dose-adjustment-paused",
            "dose-adjustment-resumed",
            "lab-hematology",
            "lab-chemistry",
            "concomitant-medication-risk",
            "adverse-event-review",
        }
        subtype_colors = {}
        for category in lane_subtype_categories:
            match = re.search(
                rf"\.event-category-{category}\s*\{{(?P<body>.*?)\}}",
                self.styles,
                re.S,
            )
            self.assertIsNotNone(match, f"missing lane subtype category color rule for {category}")
            fill = re.search(r"--category-fill:\s*(?P<value>#[0-9a-fA-F]{6})", match.group("body"))
            self.assertIsNotNone(fill, f"missing category fill token for {category}")
            subtype_colors[category] = fill.group("value").lower()

        self.assertEqual(len(subtype_colors), len(set(subtype_colors.values())), subtype_colors)

    def test_timeline_detail_rows_reserve_space_for_long_medical_tags(self):
        row_rule = re.search(r"\.timeline-detail-row\s*\{(?P<body>.*?)\}", self.styles, re.S)
        self.assertIsNotNone(row_rule, "timeline-detail-row CSS rule not found")
        self.assertIn("minmax(104px, max-content)", row_rule.group("body"))

        tag_rule = re.search(r"\.timeline-detail-row > \.tag\s*\{(?P<body>.*?)\}", self.styles, re.S)
        self.assertIsNotNone(tag_rule, "timeline detail tag CSS rule not found")
        self.assertIn("white-space: normal", tag_rule.group("body"))
        self.assertIn("max-width: 150px", tag_rule.group("body"))

    def test_rux_subject_switchers_use_project_monitoring_subject_catalog(self):
        self.assertIn('fetch(`/api/projects/${monitoringRouteProjectId}/monitoring/subjects`)', self.source)
        self.assertIn('fetch(`/api/projects/${monitoringRouteProjectId}/subjects/${selectedSubject}/monitoring`)', self.source)
        self.assertIn("if (!monitoringRouteProjectId || !selectedSubject || !monitoringExecutionReady)", self.source)
        self.assertIn("if (selectedSubjectProfile)", self.source)
        self.assertIn('`${monitoringRouteProjectId}::${selectedSubject}`', self.source)
        self.assertIn("[requestedProfileKey]: data", self.source)
        self.assertIn("data?.project_id !== monitoringResponseProjectIdRef.current", self.source)
        self.assertIn("data?.subject_id !== selectedSubject", self.source)
        self.assertIn("activeManifest?.route_bindings?.medical_monitoring?.route_project_id", self.source)
        self.assertIn("monitoringSubjectCatalog", self.source)
        self.assertIn("subjectCatalog={monitoringSubjectCatalog}", self.source)
        self.assertIn("MedicalMonitoringSubjectTimelinePage", self.source)
        self.assertIn("MedicalMonitoringPatientProfilePage", self.source)
        self.assertIn("onNavigate={requestMonitoringWorkspace}", self.source)

        timeline_page = re.search(
            r"function SubjectTimelinePage\(.*?function PatientProfilePage",
            self.subject_views,
            re.S,
        )
        self.assertIsNotNone(timeline_page, "Subject Timeline page not found")
        self.assertNotIn("subjects.map", timeline_page.group(0))

    def test_topbar_prefers_reader_friendly_batch_label_over_technical_batch_id(self):
        app_shell = re.search(
            r"function AppShell\(.*?function Metric",
            self.source,
            re.S,
        )
        self.assertIsNotNone(app_shell, "AppShell not found")
        source = app_shell.group(0)

        self.assertIn("formatBatchDisplay(activeBatch)", source)
        self.assertRegex(
            source,
            (
                r"const activeBatch = hasActiveProject && "
                r"sourceContext\.displayBatch\?\.batch_label\s*"
                r"\?\s*sourceContext\.displayBatch\s*:\s*latestBatch;"
            ),
        )
        self.assertNotIn('latestBatch?.batch_id?.replace("batch_", "Batch ")', source)

    def test_patient_profile_resets_cross_project_filter_state_and_compacts_many_centers(self):
        self.assertIn('const profileContextKey = `${rawProfile?.project_id || ""}:${subject.id}`;', self.subject_views)
        self.assertIn("setSelectedCenter(subjectCenter || \"all\")", self.subject_views)
        self.assertIn("const useCenterSelect = centers.length > 8", self.subject_views)
        self.assertIn('className="profile-center-select"', self.subject_views)
        self.assertIn(".profile-center-select", self.styles)

    def test_timeline_context_distinguishes_actual_planned_and_unscheduled_visits(self):
        self.assertIn("const timelineCoverage = timelineDataCoverage(visits, nonVisitEvents);", self.subject_views)
        self.assertIn("const actualVisitCount = timelineCoverage.datedVisits;", self.subject_views)
        self.assertIn("hasActualTimelineDate(visit.date)", self.subject_views)
        self.assertIn("const plannedOnlyVisitCount = visits.filter((visit) => (", self.subject_views)
        self.assertIn("visit.plannedDay !== null && visit.plannedDay !== undefined", self.subject_views)
        self.assertIn("const unscheduledVisitCount = visits.filter((visit) => visit.isUnscheduled).length;", self.subject_views)
        self.assertIn("个计划访视待匹配", self.subject_views)
        self.assertIn("个访视日期缺失或无效", self.subject_views)
        self.assertIn("个计划外访视", self.subject_views)
        self.assertNotIn("个实际访视锚点", self.subject_views)

    def test_timeline_date_axis_fails_closed_when_actual_date_evidence_is_missing(self):
        self.assertIn("export function hasActualTimelineDate", self.subject_models)
        self.assertIn("export function timelineDataCoverage", self.subject_models)
        self.assertIn('status: datedRecords === 0 ? "no_actual_dates"', self.subject_models)
        self.assertIn('timelineCoverage.status === "no_actual_dates"', self.subject_views)
        self.assertIn('timelineCoverage.status === "partial_dates"', self.subject_views)
        self.assertIn("计划日/研究日不替代实际日期", self.subject_views)
        self.assertIn("缺失日期记录保留在明细", self.subject_views)
        self.assertIn("events: lane.events.filter(({ event }) => hasActualTimelineDate(event.event_date))", self.subject_views)

    def test_patient_profile_exposes_baseline_rule_without_expanding_all_measurements(self):
        self.assertIn("baseline_expected_count", self.subject_views)
        self.assertIn("baseline_observed_count", self.subject_views)
        self.assertIn('className="metric-baseline-note"', self.subject_views)
        self.assertIn("查看全部 {points.length} 个原始测量点", self.subject_views)
        self.assertIn(".metric-chart-head .metric-baseline-note", self.styles)

    def test_patient_profile_metric_chart_fails_closed_on_non_numeric_points(self):
        self.assertIn("export function metricDataCoverage", self.subject_models)
        self.assertIn("const chartPointEntries = pointEntries.filter(({ point }) => (", self.subject_views)
        self.assertIn("const chartPoints = chartPointEntries.map(({ point }) => point);", self.subject_views)
        self.assertIn("hasActualTimelineDate(point.assessment_date)", self.subject_views)
        self.assertIn("coverage.invalidValuePoints", self.subject_views)
        self.assertIn("coverage.undatedDatePoints", self.subject_views)
        self.assertIn("数值未提供", self.subject_views)
        self.assertIn("暂无可绘制的", self.subject_views)
        self.assertIn("原始测量点仍保留在下方明细", self.subject_views)
        self.assertIn("profileMetricEmptyStateMessage", self.subject_views)
        self.assertIn("空态不代表", self.subject_models)

    def test_full_subject_views_return_to_the_same_risk_instance(self):
        route_callback = re.search(
            r"const requestMonitoringWorkspace = useCallback\(\(nextPage\) => \{(?P<body>.*?)\n  \}, \[[^\]]+\]\);",
            self.source,
            re.S,
        )
        self.assertIsNotNone(route_callback, "monitoring return callback not found")
        body = route_callback.group("body")
        self.assertIn("const returnRiskId = subjectViewFocusRiskId", body)
        self.assertIn("const returnScope = monitoringReturnScopeRef.current", body)
        self.assertIn("monitoringReturnSiteIdRef.current", body)
        self.assertIn("risk_instance_id: returnRiskId", body)
        self.assertIn("setMonitoringFocusRiskId(returnRiskId)", body)


if __name__ == "__main__":
    unittest.main()
