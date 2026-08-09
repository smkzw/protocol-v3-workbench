import assert from "node:assert/strict";
import {
  MEDICAL_MONITORING_RISK_FOCUS_KEYS,
  MEDICAL_MONITORING_ROUTE_KEYS,
  clearMedicalMonitoringRouteState,
  clearMedicalMonitoringRiskFocusState,
  mergeMedicalMonitoringRouteState,
  normalizeMedicalMonitoringRouteState,
  parseMedicalMonitoringRouteState,
  resolveMedicalMonitoringProjectRoute,
  resolveMedicalMonitoringRiskRoute,
  resolveMedicalMonitoringSiteRoute,
  resolveMedicalMonitoringSubjectRoute,
  serializeMedicalMonitoringRouteState,
} from "./medicalMonitoringRouteState.mjs";

let passed = 0;
function check(condition, message) {
  assert.ok(condition, message);
  passed += 1;
}

const parsed = parseMedicalMonitoringRouteState(
  "?project_id=proj%20A&scope=subject&site_id=01&subject_id=S-001"
  + "&risk_key=AE%2FMH-1&risk_instance_id=ri-1&view=evidence"
  + "&protocol_version_id=protocol-2&batch_id=batch-2"
  + "&evidence_tab=history&filter_subject_id=S-002&filter_site_id=02"
  + "&filter_severity=high&filter_risk_category_code=ae_missing_report"
  + "&filter_risk_item=%E5%A4%B4%E7%97%9B&filter_disposition_status=pending_review"
  + "&filter_updated_at=2026-07-29&risk_sort_by=subject_id"
  + "&risk_sort_direction=asc&risk_page=2&risk_page_size=25"
  + "&risk_scroll_top=840"
  + "&risk_snapshot_id=snapshot-1",
);
check(parsed.project_id === "proj A", "parses encoded project id");
check(parsed.scope === "subject" && parsed.site_id === "01", "keeps subject context");
check(parsed.subject_id === "S-001" && parsed.view === "evidence", "parses subject view");
check(
  parsed.risk_key === "AE/MH-1"
    && parsed.protocol_version_id === "protocol-2"
    && parsed.batch_id === "batch-2",
  "parses risk focus and explicit metric context",
);
check(parsed.evidence_tab === "history", "parses evidence tab");
check(parsed.filter_subject_id === "S-002" && parsed.filter_site_id === "02", "parses column filters");
check(parsed.filter_risk_category_code === "ae_missing_report", "parses canonical category filter");
check(parsed.risk_sort_by === "subject_id" && parsed.risk_sort_direction === "asc", "parses checklist sort");
check(parsed.risk_page === "2" && parsed.risk_page_size === "25", "parses checklist page");
check(parsed.risk_scroll_top === "840", "parses checklist scroll position");
check(parsed.risk_snapshot_id === "snapshot-1", "parses pinned snapshot");

const dockClosed = clearMedicalMonitoringRiskFocusState(parsed);
check(
  MEDICAL_MONITORING_RISK_FOCUS_KEYS.every((key) => !dockClosed[key]),
  "dock close clears only risk focus and evidence tab",
);
check(dockClosed.view === "checklist", "dock close exits evidence view after clearing risk focus");
check(dockClosed.scope === "subject" && dockClosed.subject_id === "S-001", "dock close preserves scope");
check(
  dockClosed.filter_subject_id === "S-002"
    && dockClosed.filter_site_id === "02"
    && dockClosed.filter_severity === "high"
    && dockClosed.filter_risk_category_code === "ae_missing_report"
    && dockClosed.filter_risk_item === "头痛"
    && dockClosed.filter_disposition_status === "pending_review"
    && dockClosed.filter_updated_at === "2026-07-29",
  "dock close preserves all seven checklist filters",
);
check(
  dockClosed.risk_sort_by === "subject_id"
    && dockClosed.risk_sort_direction === "asc"
    && dockClosed.risk_page === "2"
    && dockClosed.risk_page_size === "25"
    && dockClosed.risk_scroll_top === "840"
    && dockClosed.risk_snapshot_id === "snapshot-1",
  "dock close preserves sort, pagination, scroll position, and pinned snapshot",
);

const trial = normalizeMedicalMonitoringRouteState({
  project_id: "p1",
  scope: "trial",
  site_id: "site-should-clear",
  subject_id: "subject-should-clear",
  view: "CHECKLIST",
});
check(trial.scope === "trial", "normalizes scope case");
check(!trial.site_id && !trial.subject_id, "trial scope clears narrower focus");
check(trial.view === "checklist", "normalizes supported view");

const inferredSubject = normalizeMedicalMonitoringRouteState({
  project_id: "p1",
  subject_id: "S1",
});
check(inferredSubject.scope === "subject", "subject id infers subject scope");

const invalidSubject = normalizeMedicalMonitoringRouteState({
  project_id: "p1",
  scope: "subject",
  site_id: "C1",
  view: "unknown-view",
});
check(invalidSubject.scope === "site", "missing subject degrades to available site");
check(!invalidSubject.view, "drops unsupported view");

const unsupportedOnly = normalizeMedicalMonitoringRouteState({
  scope: "patient",
  view: "debug-log",
  evidence_tab: "raw-log",
  filter_severity: "urgent",
  risk_sort_by: "title",
  risk_sort_direction: "sideways",
  risk_page: "0",
  risk_page_size: "1000",
  risk_scroll_top: "1000001",
});
check(Object.keys(unsupportedOnly).length === 0, "unsupported values do not create a trial focus");

const validScrollOnly = normalizeMedicalMonitoringRouteState({
  project_id: "p1",
  scope: "trial",
  risk_scroll_top: "120",
});
check(validScrollOnly.risk_scroll_top === "120", "keeps a bounded checklist scroll position");

const timelineWithoutSubject = normalizeMedicalMonitoringRouteState({
  project_id: "p1",
  scope: "trial",
  view: "timeline",
});
check(timelineWithoutSubject.view === "checklist", "subject view degrades without subject focus");

const evidenceWithoutRisk = normalizeMedicalMonitoringRouteState({
  project_id: "p1",
  scope: "trial",
  view: "evidence",
});
check(evidenceWithoutRisk.view === "checklist", "evidence view degrades without risk focus");

const merged = mergeMedicalMonitoringRouteState(
  "?mw_tab=references&section_id=sec-3&project_id=old&scope=site&site_id=C1",
  { scope: "subject", subject_id: "S9", view: "timeline" },
);
const mergedParams = new URLSearchParams(merged.slice(1));
check(mergedParams.get("mw_tab") === "references", "preserves writing tab");
check(mergedParams.get("section_id") === "sec-3", "preserves writing section");
check(mergedParams.get("subject_id") === "S9", "merges subject focus");
check(mergedParams.get("site_id") === "C1", "keeps useful site context");

const serialized = serializeMedicalMonitoringRouteState(
  { project_id: "新项目", scope: "site", site_id: "中心 01", view: "profile" },
  "?citation_id=ref-8&view=stale&subject_id=stale",
);
const serializedParams = new URLSearchParams(serialized.slice(1));
check(serializedParams.get("citation_id") === "ref-8", "serialization preserves unrelated query");
check(serializedParams.get("project_id") === "新项目", "serialization encodes project value");
check(!serializedParams.has("subject_id"), "serialization removes stale monitoring focus");

const cleared = clearMedicalMonitoringRouteState(
  "?project_id=p1&scope=subject&subject_id=S1&view=profile"
  + "&mw_project_id=writing-1&mw_tab=outline&citation_id=ref-2",
);
const clearedParams = new URLSearchParams(cleared.slice(1));
check(MEDICAL_MONITORING_ROUTE_KEYS.every((key) => !clearedParams.has(key)), "clears monitoring keys");
check(clearedParams.get("mw_project_id") === "writing-1", "preserves writing project key");
check(clearedParams.get("mw_tab") === "outline", "preserves writing tab when clearing");
check(clearedParams.get("citation_id") === "ref-2", "preserves unrelated citation");

const projectSwitchSearch = clearMedicalMonitoringRouteState(
  "?scope=subject&site_id=C1&subject_id=S1"
  + "&risk_key=RK1&risk_instance_id=RI1&evidence_tab=sources"
  + "&filter_subject_id=S2&filter_site_id=C2&filter_severity=critical"
  + "&filter_risk_category_code=ae_missing_report&filter_risk_item=headache"
  + "&filter_disposition_status=pending_review&filter_updated_at=2026-07-30"
  + "&risk_sort_by=updated_at&risk_sort_direction=asc"
  + "&risk_page=4&risk_page_size=100&risk_snapshot_id=snap-4"
  + "&mw_tab=references&section_id=sec-8",
);
const projectSwitchParams = new URLSearchParams(projectSwitchSearch.slice(1));
check(
  MEDICAL_MONITORING_ROUTE_KEYS.every((key) => !projectSwitchParams.has(key)),
  "project switch clears every monitoring URL key",
);
check(
  projectSwitchParams.get("mw_tab") === "references"
    && projectSwitchParams.get("section_id") === "sec-8",
  "project switch preserves unrelated module URL state",
);

const clearedAll = clearMedicalMonitoringRouteState("?project_id=p1&view=checklist");
check(clearedAll === "", "returns empty query when only monitoring keys existed");

const sourceUrl = new URL("https://workbench.test/writing?mw_tab=outline&view=profile");
serializeMedicalMonitoringRouteState({ project_id: "p2", view: "timeline" }, sourceUrl);
check(sourceUrl.searchParams.get("view") === "profile", "does not mutate a caller-owned URL");
check(!sourceUrl.searchParams.has("project_id"), "URL input remains unchanged");

const matchedProject = resolveMedicalMonitoringProjectRoute(
  "proj-rux",
  [{ project_id: "proj-my009" }, { project_id: "proj-rux" }],
  "proj-my009",
  "proj-my009",
);
check(
  matchedProject.status === "matched" && matchedProject.projectId === "proj-rux",
  "keeps an explicitly requested available project",
);

const unavailableProject = resolveMedicalMonitoringProjectRoute(
  "proj-no-access",
  [{ project_id: "proj-my009" }, { project_id: "proj-rux" }],
  "proj-my009",
  "proj-my009",
);
check(
  unavailableProject.status === "unavailable"
    && unavailableProject.projectId === ""
    && unavailableProject.requestedProjectId === "proj-no-access",
  "fails closed instead of substituting another project for an unavailable deep link",
);

const fallbackProject = resolveMedicalMonitoringProjectRoute(
  "",
  [{ project_id: "proj-my009" }, { project_id: "proj-rux" }],
  "missing-current",
  "proj-rux",
);
check(
  fallbackProject.status === "fallback" && fallbackProject.projectId === "proj-rux",
  "uses the configured fallback only when no project was requested",
);

const malformedProjects = resolveMedicalMonitoringProjectRoute(
  "",
  [null, { project_id: " " }, { project_id: "proj-my009" }, { project_id: "proj-my009" }],
  "",
  "missing-fallback",
);
check(
  malformedProjects.status === "default" && malformedProjects.projectId === "proj-my009",
  "ignores malformed and duplicate project candidates",
);

const matchedRisk = resolveMedicalMonitoringRiskRoute(
  "risk-002",
  [{ id: "risk-001", risk_key: "AE-001" }],
  [{ risk_instance_id: "risk-002", subject_id: "S-002" }],
);
check(
  matchedRisk.status === "matched" && matchedRisk.risk.subject_id === "S-002",
  "matches an explicitly requested risk within the current project scope",
);

const unavailableRisk = resolveMedicalMonitoringRiskRoute(
  "risk-other-project",
  [{ id: "risk-001", risk_key: "AE-001" }],
  [],
);
check(
  unavailableRisk.status === "unavailable"
    && unavailableRisk.risk === null
    && unavailableRisk.requestedRiskId === "risk-other-project",
  "does not substitute another risk when a deep-linked risk is absent",
);

const noRiskFocus = resolveMedicalMonitoringRiskRoute("", [{ id: "risk-001" }]);
check(noRiskFocus.status === "none", "keeps an unfocused checklist explicit");

const matchedSubject = resolveMedicalMonitoringSubjectRoute(
  "S-002",
  [{ id: "S-001" }, { subject_id: "S-002" }],
  "S-001",
  "S-001",
);
check(
  matchedSubject.status === "matched" && matchedSubject.subjectId === "S-002",
  "matches an explicitly requested subject in the current catalog",
);

const unavailableSubject = resolveMedicalMonitoringSubjectRoute(
  "S-other-project",
  [{ id: "S-001" }, { id: "S-002" }],
  "S-001",
  "S-001",
);
check(
  unavailableSubject.status === "unavailable"
    && unavailableSubject.subjectId === ""
    && unavailableSubject.requestedSubjectId === "S-other-project",
  "does not fall back to another subject for an unavailable deep link",
);

const defaultSubject = resolveMedicalMonitoringSubjectRoute(
  "",
  [{ id: "S-001" }, { id: "S-002" }],
  "missing-current",
  "S-002",
);
check(
  defaultSubject.status === "fallback" && defaultSubject.subjectId === "S-002",
  "uses a default subject only when no subject was requested",
);

const matchedSite = resolveMedicalMonitoringSiteRoute(
  "01",
  [{ id: "S-001", site: "01" }],
  [],
);
check(
  matchedSite.status === "matched" && matchedSite.siteId === "01",
  "matches a site from the current subject catalog",
);

const matchedRollupSite = resolveMedicalMonitoringSiteRoute(
  "02",
  [],
  [{ scope_id: "02" }],
);
check(
  matchedRollupSite.status === "matched" && matchedRollupSite.siteId === "02",
  "matches a site from the current risk rollups",
);

const unavailableSite = resolveMedicalMonitoringSiteRoute(
  "99",
  [{ id: "S-001", site: "01" }],
  [{ scope_id: "02" }],
);
check(
  unavailableSite.status === "unavailable"
    && unavailableSite.siteId === ""
    && unavailableSite.requestedSiteId === "99",
  "does not turn an unknown site deep link into an empty trial result",
);

const pendingSite = resolveMedicalMonitoringSiteRoute("01", [], []);
check(pendingSite.status === "pending", "keeps an unready site catalog pending");

console.log(`medicalMonitoringRouteState: ${passed} passed`);
