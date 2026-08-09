import assert from "node:assert/strict";
import {
  normalizeMedicalMonitoringRiskEvidenceContext,
  riskEvidenceContextLineageLabel,
  riskEvidenceContextStateLabel,
} from "./medicalMonitoringRiskEvidenceContext.mjs";

const full = normalizeMedicalMonitoringRiskEvidenceContext({
  riskId: "risk-instance-1",
  riskKey: "AE:subject-1:01",
  scopeLabel: "受试者 subject-1",
  subject: "subject-1",
  site: "site-1",
  snapshotId: "snapshot-1",
  sourceVersion: "batch-1:rev-2",
  batch: "batch-1",
  severity: "high",
  status: "action_required",
  dispositionState: "pending_review",
  evidenceLocators: ["listing:AE:row:1", "protocol:section:4"],
  sourceRefs: [{ source_type: "listing_data_row", locator: "listing:AE:row:1" }],
  sourceEvidenceShape: "valid",
  unread: true,
  needsAction: true,
  safetyPvFlag: false,
});
assert.equal(full.status, "ready");
assert.equal(full.value.riskInstanceId, "risk-instance-1");
assert.equal(full.value.evidence.status, "bound");
assert.equal(full.value.evidence.locatorCount, 2);
assert.equal(full.value.evidence.referenceCount, 1);
assert.equal(full.value.lineage.status, "version_bound");
assert.equal(full.value.unread, true);
assert.equal(full.value.needsAction, true);
assert.equal(full.issues.length, 0);

const referenceOnly = normalizeMedicalMonitoringRiskEvidenceContext({
  riskId: "risk-2",
  riskKey: "risk-key-2",
  sourceRefs: [{ source_id: "source-2" }],
  batch: "batch-2",
});
assert.equal(referenceOnly.status, "partial");
assert.equal(referenceOnly.value.evidence.status, "reference_only");
assert.equal(referenceOnly.value.lineage.status, "batch_only");
assert.equal(referenceOnly.value.subjectId, null);

const missing = normalizeMedicalMonitoringRiskEvidenceContext({
  riskId: "risk-3",
  riskKey: "risk-key-3",
});
assert.equal(missing.status, "partial");
assert.equal(missing.value.evidence.status, "missing");
assert.equal(missing.value.lineage.status, "missing");
assert.ok(missing.issues.length === 0, "absence of optional source fields is visible state, not a shape error");

const malformed = normalizeMedicalMonitoringRiskEvidenceContext({
  riskId: "risk-4",
  riskKey: "risk-key-4",
  evidenceLocators: ["ok", 2],
  sourceRefs: [{ locator: "" }, "bad"],
  unread: "true",
  sourceEvidenceShape: "malformed",
});
assert.equal(malformed.status, "partial");
assert.equal(malformed.value.evidence.status, "malformed");
assert.equal(malformed.value.evidence.locatorCount, null);
assert.ok(malformed.issues.some((item) => item.field === "unread"));

assert.equal(normalizeMedicalMonitoringRiskEvidenceContext(null).status, "malformed");
assert.equal(riskEvidenceContextStateLabel("reference_only"), "仅有来源引用");
assert.equal(riskEvidenceContextLineageLabel("missing"), "来源链路缺失");

console.log("medicalMonitoringRiskEvidenceContext: 24 passed");

