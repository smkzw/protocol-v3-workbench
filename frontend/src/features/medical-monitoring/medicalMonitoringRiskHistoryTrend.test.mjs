import assert from "node:assert/strict";
import {
  medicalMonitoringRiskSeverityTone,
  medicalMonitoringRiskTrendDirectionLabel,
  normalizeMedicalMonitoringRiskHistoryTrend,
} from "./medicalMonitoringRiskHistoryTrend.mjs";

const instances = [
  {
    snapshot_id: "snap-2",
    snapshot_created_at: "2026-07-15T00:00:00Z",
    is_current: true,
    risk: { severity: "high", batch_delta: "persisting", status: "open", source_batch_id: "batch-002" },
  },
  {
    snapshot_id: "snap-1",
    snapshot_created_at: "2026-07-01T00:00:00Z",
    is_current: false,
    risk: { severity: "medium", batch_delta: "new", status: "open", source_batch_id: "batch-001" },
  },
];

const view = normalizeMedicalMonitoringRiskHistoryTrend(instances);
assert.equal(view.status, "available");
assert.deepEqual(view.points.map((point) => point.snapshotId), ["snap-1", "snap-2"]);
assert.deepEqual(view.points.map((point) => point.direction), ["initial", "up"]);
assert.equal(view.summary.currentSeverity, "高");
assert.equal(view.summary.transitionCount, 1);
assert.equal(medicalMonitoringRiskSeverityTone("critical"), "danger");
assert.equal(medicalMonitoringRiskTrendDirectionLabel("down"), "降低");

const partial = normalizeMedicalMonitoringRiskHistoryTrend([
  { snapshot_id: "snap-partial", snapshot_created_at: "bad-date", is_current: true, risk: { severity: "future", status: "open" } },
]);
assert.equal(partial.status, "partial");
assert.equal(partial.points.length, 1);
assert.equal(partial.points[0].severityRank, null);

const identityGuard = normalizeMedicalMonitoringRiskHistoryTrend([
  {
    ...instances[0],
    snapshot_id: "snap-duplicate",
    is_current: false,
  },
  {
    ...instances[1],
    snapshot_id: "snap-duplicate",
    is_current: true,
  },
  {
    ...instances[0],
    snapshot_id: "",
    is_current: false,
  },
]);
assert.equal(identityGuard.status, "partial");
assert.deepEqual(identityGuard.points.map((point) => point.displayIdentityState), ["duplicate", "duplicate", "missing"]);
assert.equal(new Set(identityGuard.points.map((point) => point.displayKey)).size, identityGuard.points.length);
assert.ok(identityGuard.issues.some((issue) => issue.includes("快照标识 snap-duplicate 重复")));
assert.match(identityGuard.points[2].displayIdentityIssue, /缺少 snapshot_id/);

const malformed = normalizeMedicalMonitoringRiskHistoryTrend([
  { snapshot_id: "snap-malformed", snapshot_created_at: "2026-07-01T00:00:00Z", is_current: "true", risk: { severity: "high", batch_delta: "new", status: "open" } },
]);
assert.equal(malformed.status, "malformed");
assert.equal(malformed.points.length, 0);
assert.ok(malformed.issues.some((issue) => issue.includes("形状异常")));

const empty = normalizeMedicalMonitoringRiskHistoryTrend(null);
assert.equal(empty.status, "empty");

console.log("medicalMonitoringRiskHistoryTrend: 23 passed");
