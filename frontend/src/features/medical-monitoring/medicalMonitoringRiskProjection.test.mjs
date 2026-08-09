import assert from "node:assert/strict";
import {
  MedicalRiskProjectionError,
  projectCanonicalMedicalRisks,
} from "./medicalMonitoringRiskProjection.mjs";

let passed = 0;
function check(condition, message) {
  assert.ok(condition, message);
  passed += 1;
}

const base = {
  project_id: "proj_rux_03_002",
  trial_id: "RUX-03-002",
  risk_key: "risk-key-001",
  risk_instance_id: "riskinst-001",
  scope_type: "subject",
  scope_id: "S01001",
  site_id: "01",
  subject_id: "S01001",
  category: "laboratory_abnormality",
  finding_class: "risk",
  severity: "high",
  status: "action_required",
  disposition_state: "pending_review",
  unread: true,
  needs_action: true,
  source_revision: "source-001",
  rule_profile_revision: "rules-001",
  engine_version: "engine-001",
  rule_id: "LAB-001",
  title: "实验室异常需复核",
  rationale: "原始数据与规则阈值关联。",
  recommended_action: "医学复核。",
  evidence_ids: ["listing:LB:row:1"],
  evidence_locators: ["listing:LB:row:1"],
  linked_views: {
    timeline_event_ids: ["event-lb-1"],
    profile_field_ids: ["profile-lb-1"],
    lab_event_ids: ["event-lb-1"],
  },
};

const secondSubject = {
  ...base,
  risk_key: "risk-key-002",
  risk_instance_id: "riskinst-002",
  scope_id: "S01002",
  subject_id: "S01002",
  severity: "medium",
  status: "in_review",
  disposition_state: "reviewed",
  unread: false,
  needs_action: false,
  title: "访视窗口需复核",
  rule_id: "VISIT-001",
  evidence_ids: ["listing:SV:row:2"],
  evidence_locators: [],
  linked_views: { timeline_event_ids: ["event-sv-2"], pd_event_ids: ["pd-2"] },
};

const siteRisk = {
  ...base,
  risk_key: "risk-key-003",
  risk_instance_id: "riskinst-003",
  scope_type: "site",
  scope_id: "02",
  site_id: "02",
  subject_id: "",
  severity: "low",
  status: "new",
  disposition_state: "pending_review",
  unread: true,
  needs_action: false,
  title: "中心数据完整性待观察",
  rule_id: "DATA-001",
  evidence_ids: ["listing:DM:row:3"],
  evidence_locators: [],
  linked_views: { profile_field_ids: ["site-data-02"] },
};

const projection = projectCanonicalMedicalRisks([
  base,
  { ...base },
  secondSubject,
  siteRisk,
]);

check(projection.rows.length === 3, "exact duplicate risk instance is counted once");
check(projection.project.riskCount === 3, "project rollup counts distinct risk instances");
check(projection.project.unreadCount === 2, "unread remains a workflow field");
check(projection.project.needsActionCount === 1, "needsAction is not inferred from severity");
check(projection.project.severityCounts.high === 1 && projection.project.severityCounts.medium === 1, "severity counts are conserved");
check(projection.sites.map((site) => site.id).join(",") === "01,02", "sites sort deterministically");
check(projection.sites[0].riskCount === 2 && projection.sites[1].riskCount === 1, "site drilldown conserves counts");
check(projection.subjects.map((subject) => subject.id).join(",") === "S01001,S01002", "subject drilldown is explicit and sorted");
check(projection.project.evidenceCoverage.status === "partial", "project evidence coverage distinguishes locators from references");
check(projection.project.evidenceCoverage.locatorRiskCount === 1, "project locator coverage counts only explicit locators");
check(projection.project.evidenceCoverage.evidenceIdRiskCount === 3, "project evidence ID coverage counts explicit references");
check(projection.sites[0].evidenceCoverage.locatorRiskCount === 1, "site rollup carries evidence coverage");
check(projection.subjects[1].evidenceCoverage.missingRiskCount === 0, "subject rollup keeps evidence IDs visible without calling them locators");
check(projection.scopeConservation.sitePartitionStatus === "conserved", "site-assigned plus unassigned risks conserve the project total");
check(projection.scopeConservation.subjectProjectionStatus === "conserved", "subject projection conserves subject-scoped risks");
check(projection.rows[0].findingClass === "risk" && projection.rows[0].dispositionState === "pending_review", "finding and disposition stay separate");
check(projection.rows[0].linkedViews.labEventIds[0] === "event-lb-1", "lab linkage is explicit");
check(projection.rows[1].linkedViews.pdEventIds[0] === "pd-2", "PD linkage is explicit");
check(projection.projectionStatus === "ready" && projection.limitations.length === 0, "complete input is explicitly ready");
check(projection.progressiveDisclosure.defaultVisible.includes("severity"), "default view is concise");
check(projection.progressiveDisclosure.evidenceFields.includes("locators"), "technical evidence is progressive disclosure");

for (const [field, value] of [
  ["risk_instance_id", true],
  ["project_id", 123],
  ["subject_id", false],
  ["evidence_ids", "evidence-scalar"],
  ["linked_views", ["not-an-object"]],
  ["linked_views", false],
  ["aggregate_version", "4"],
]) {
  assert.throws(
    () => projectCanonicalMedicalRisks([{ ...base, [field]: value }]),
    MedicalRiskProjectionError,
    `malformed ${field} is rejected`,
  );
}
assert.throws(
  () => projectCanonicalMedicalRisks([{ ...base, evidence_ids: ["evidence-ok", 2] }]),
  /evidence_ids must contain non-empty strings/,
);
assert.throws(
  () => projectCanonicalMedicalRisks([{ ...base, linked_views: { timeline_event_ids: false } }]),
  /linked_views\.timelineEventIds must be a string array/,
);
assert.throws(
  () => projectCanonicalMedicalRisks([{
    ...base,
    linked_views: false,
    linkedViews: { timeline_event_ids: ["should-not-fallback"] },
  }]),
  /linked_views must be an object/,
);
assert.throws(
  () => projectCanonicalMedicalRisks([{ ...base, needs_action: "false" }]),
  /needs_action must be a boolean/,
);

const limited = projectCanonicalMedicalRisks([{ ...base, needs_action: undefined }]);
check(limited.limitations.includes("needs_action_not_explicitly_provided"), "missing workflow input is visible as a limitation");
check(projectCanonicalMedicalRisks().projectionStatus === "empty", "empty input cannot present as a successful risk state");
check(projectCanonicalMedicalRisks().scopeConservation.sitePartitionStatus === "empty", "empty projection is not reported as conserved data");

const missingEvidence = projectCanonicalMedicalRisks([{
  ...siteRisk,
  risk_instance_id: "riskinst-missing-evidence",
  evidence_ids: [],
  evidence_locators: [],
  title: "来源证据缺失仍需显示风险",
}]);
check(missingEvidence.project.evidenceCoverage.status === "missing", "missing source evidence remains an explicit missing state");
check(missingEvidence.project.evidenceCoverage.missingRiskCount === 1, "missing source evidence is counted without implying no risk");

assert.throws(
  () => projectCanonicalMedicalRisks([{ ...base, risk_instance_id: "" }]),
  MedicalRiskProjectionError,
);
assert.throws(
  () => projectCanonicalMedicalRisks([{ ...base }, { ...base, severity: "critical" }]),
  /identity conflict/,
);
assert.throws(
  () => projectCanonicalMedicalRisks([base, { ...secondSubject, project_id: "proj_other" }]),
  /project or trial identities/,
);
assert.throws(
  () => projectCanonicalMedicalRisks([{ ...base, subject_id: "", site_id: "" }]),
  /subject scope identity is incomplete/,
);

console.log(`medicalMonitoringRiskProjection: ${passed} passed`);
