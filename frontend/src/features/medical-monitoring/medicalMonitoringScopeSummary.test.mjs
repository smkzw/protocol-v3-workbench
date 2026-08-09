import assert from "node:assert/strict";
import {
  medicalMonitoringScopeLabel,
  medicalMonitoringScopeCategoryLabelMap,
  medicalMonitoringScopeLevels,
  medicalMonitoringScopeNumber,
  medicalMonitoringScopeRowKey,
  normalizeMedicalMonitoringScopeSummary,
} from "./medicalMonitoringScopeSummary.mjs";

const rollup = {
  trial: {
    scope_id: "proj-rux",
    risk_count: 7,
    needs_action_count: 3,
    unread_count: 2,
    severity_counts: { high: 2, medium: 5 },
    category_counts: { safety: 4, efficacy: 3 },
    batch_delta_counts: { new: 3, persisting: 4 },
  },
  sites: [
    { scope_id: "site-02", risk_count: 4, needs_action_count: 2, unread_count: 1 },
    { scope_id: "site-01", risk_count: 3, needs_action_count: 1, unread_count: 1 },
  ],
  subjects: [
    { scope_id: "SUBJ-002", risk_count: 2, needs_action_count: 2, unread_count: 1 },
    { scope_id: "SUBJ-001", risk_count: 1, needs_action_count: 0, unread_count: 0 },
  ],
};

const view = normalizeMedicalMonitoringScopeSummary(rollup);
assert.equal(view.status, "available");
assert.equal(view.trial.riskCount, 7);
assert.equal(view.trial.severityCounts[0].label, "medium");
assert.deepEqual(view.trial.categoryCounts, [
  { label: "efficacy", count: 3 },
  { label: "safety", count: 4 },
].sort((left, right) => right.count - left.count || left.label.localeCompare(right.label)));
assert.deepEqual(view.sites.map((row) => row.scopeId), ["site-02", "site-01"]);
assert.deepEqual(view.subjects.map((row) => row.scopeId), ["SUBJ-002", "SUBJ-001"]);
assert.deepEqual(medicalMonitoringScopeLevels(), ["trial", "site", "subject"]);
assert.equal(medicalMonitoringScopeLabel("site"), "中心");
assert.equal(medicalMonitoringScopeNumber(0), "0");
assert.equal(medicalMonitoringScopeNumber("0"), "—");
assert.equal(medicalMonitoringScopeRowKey(view.sites[0]), "site:site-02:0");
assert.deepEqual(medicalMonitoringScopeCategoryLabelMap({
  categories: [
    { code: "safety", label: "安全性" },
    { code: "efficacy", label: "疗效" },
    { code: "safety", label: "冲突标签" },
    { code: "ignored", label: 100 },
  ],
}), { efficacy: "疗效" });
assert.deepEqual(medicalMonitoringScopeCategoryLabelMap({ categories: "malformed" }), {});

const malformed = normalizeMedicalMonitoringScopeSummary({
  trial: { scope_id: "proj-rux", risk_count: "7", needs_action_count: 1, unread_count: 0, category_counts: { safety: "4" } },
  sites: "not-an-array",
  subjects: [{ scope_id: 1001, risk_count: 1, needs_action_count: 0, unread_count: 0 }],
});
assert.equal(malformed.status, "malformed");
assert.equal(malformed.sites.length, 0);
assert.equal(malformed.subjects[0].status, "partial");
assert.equal(malformed.subjects[0].scopeId, null);
assert.equal(malformed.trial.riskCount, null);
assert.equal(malformed.trial.categoryCounts.length, 0);

const missing = normalizeMedicalMonitoringScopeSummary({ trial: undefined, sites: [], subjects: [] });
assert.equal(missing.status, "partial");
assert.equal(missing.trial, null);
assert.deepEqual(missing.sites, []);

const duplicate = normalizeMedicalMonitoringScopeSummary({
  sites: [
    { scope_id: "site-01", risk_count: 2, needs_action_count: 1, unread_count: 0 },
    { scope_id: "site-01", risk_count: 1, needs_action_count: 0, unread_count: 0 },
  ],
  subjects: [],
});
assert.equal(duplicate.status, "partial");
assert.ok(duplicate.sites.every((row) => row.identityAmbiguous));
assert.match(duplicate.issues.join(" "), /中心标识 site-01 重复/);
assert.notEqual(
  medicalMonitoringScopeRowKey(duplicate.sites[0]),
  medicalMonitoringScopeRowKey(duplicate.sites[1]),
);

console.log("medicalMonitoringScopeSummary: 29 passed");
