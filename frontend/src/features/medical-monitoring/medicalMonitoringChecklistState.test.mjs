import assert from "node:assert/strict";
import {
  activeRiskChecklistFilters,
  DEFAULT_RISK_CHECKLIST_QUERY,
  normalizeRiskChecklistQuery,
  resetRiskChecklistForQueryChange,
  riskChecklistApiQuery,
  riskChecklistQueryFromRoute,
  riskChecklistRoutePatch,
} from "./medicalMonitoringChecklistState.mjs";

let passed = 0;
function check(condition, message) {
  assert.ok(condition, message);
  passed += 1;
}

const fromRoute = riskChecklistQueryFromRoute({
  filter_subject_id: "S001",
  filter_site_id: "01",
  filter_severity: "HIGH",
  filter_risk_category_code: "ae_missing_report",
  filter_risk_item: "头痛",
  filter_disposition_status: "pending_review",
  filter_updated_at: "2026-07-29",
  risk_sort_by: "subject_id",
  risk_sort_direction: "asc",
  risk_page: "3",
  risk_page_size: "25",
  risk_snapshot_id: "snap-1",
});
check(fromRoute.subjectId === "S001" && fromRoute.siteId === "01", "restores text filters");
check(fromRoute.severity === "high", "normalizes severity");
check(fromRoute.sortBy === "subject_id" && fromRoute.sortDirection === "asc", "restores sort");
check(fromRoute.page === 3 && fromRoute.pageSize === 25, "restores pagination");
check(fromRoute.snapshotId === "snap-1", "restores pinned snapshot");

const routePatch = riskChecklistRoutePatch(fromRoute);
check(routePatch.filter_risk_category_code === "ae_missing_report", "serializes category");
check(routePatch.risk_page === "3" && routePatch.risk_page_size === "25", "serializes non-default page");
check(routePatch.risk_snapshot_id === "snap-1", "serializes snapshot");

const defaultPatch = riskChecklistRoutePatch(DEFAULT_RISK_CHECKLIST_QUERY);
check(defaultPatch.risk_sort_by === "" && defaultPatch.risk_sort_direction === "", "omits default sort");
check(defaultPatch.risk_page === "" && defaultPatch.risk_page_size === "", "omits default pagination");

const apiQuery = riskChecklistApiQuery(fromRoute, {
  scope: "subject",
  siteId: "02",
  subjectId: "S009",
});
check(apiQuery.subjectId === "S009", "subject scope constrains API query");
check(apiQuery.siteId === "01", "unlocked site filter remains available");
check(apiQuery.riskCategoryCode === "ae_missing_report", "uses closed category code");
check(apiQuery.sortBy === "subject_id" && apiQuery.snapshotId === "snap-1", "pins API query");

const changed = resetRiskChecklistForQueryChange(fromRoute, { severity: "low" });
check(changed.severity === "low", "applies changed filter");
check(changed.page === 1 && changed.snapshotId === "", "filter changes reset page and snapshot");

const invalid = normalizeRiskChecklistQuery({
  severity: "urgent",
  sortBy: "title",
  sortDirection: "sideways",
  page: 0,
  pageSize: 500,
});
check(invalid.severity === "", "rejects unknown severity");
check(invalid.sortBy === "updated_at" && invalid.sortDirection === "desc", "closes sort values");
check(invalid.page === 1 && invalid.pageSize === 50, "bounds pagination");

check(activeRiskChecklistFilters(fromRoute).length === 7, "reports all seven active column filters");

console.log(`medicalMonitoringChecklistState: ${passed} passed`);
