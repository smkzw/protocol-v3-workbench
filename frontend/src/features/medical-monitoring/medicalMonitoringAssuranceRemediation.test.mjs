import assert from "node:assert/strict";
import {
  assuranceRemediationDisplayKey,
  assuranceRemediationSeverityLabel,
  assuranceRemediationStatusLabel,
  normalizeMedicalMonitoringAssuranceRemediation,
} from "./medicalMonitoringAssuranceRemediation.mjs";

const matrix = [
  { risk_instance_id: "risk-closed", risk_key: "r-closed", subject_id: "S2", site_id: "02", severity: "low", status: "closed", closure_evidence_present: true },
  { risk_instance_id: "risk-high", risk_key: "r-high", subject_id: "S1", site_id: "01", severity: "high", status: "open", closure_evidence_present: false },
  { risk_instance_id: "risk-critical", risk_key: "r-critical", subject_id: "S3", site_id: "01", severity: "critical", status: "pending_review", closure_evidence_present: false },
];
const view = normalizeMedicalMonitoringAssuranceRemediation(matrix);
assert.equal(view.status, "ready");
assert.equal(view.totalCount, 3);
assert.equal(view.openCount, 2);
assert.equal(view.missingClosureEvidenceCount, 2);
assert.deepEqual(view.rows.map((row) => row.riskInstanceId), ["risk-critical", "risk-high", "risk-closed"]);
assert.equal(view.rows[0].subjectId, "S3");
assert.equal(view.rows[0].closureEvidencePresent, false);
assert.equal(view.rows[0].sourceIndex, 2);
assert.equal(view.rows[0].identityState, "ready");
assert.equal(assuranceRemediationDisplayKey(view.rows[0]), "assurance-remediation:risk-critical:2");
assert.equal(view.issues.length, 0);

assert.equal(normalizeMedicalMonitoringAssuranceRemediation(null).status, "empty");
assert.equal(normalizeMedicalMonitoringAssuranceRemediation("bad").status, "malformed");

const partial = normalizeMedicalMonitoringAssuranceRemediation([
  { risk_instance_id: "risk-partial", severity: "high", status: "open" },
  { risk_instance_id: "risk-partial" },
  "malformed",
]);
assert.equal(partial.status, "partial");
assert.equal(partial.validCount, 2);
assert.equal(partial.invalidCount, 1);
assert.equal(partial.rows[0].closureEvidencePresent, null);
assert.ok(partial.issues.some((item) => item.field.endsWith("closure_evidence_present")));
assert.ok(partial.issues.some((item) => item.field.includes("risk_instance_id")));

const duplicate = normalizeMedicalMonitoringAssuranceRemediation([
  { risk_instance_id: "risk-duplicate", subject_id: "S1", site_id: "01", status: "open", closure_evidence_present: false },
  { risk_instance_id: "risk-duplicate", subject_id: "S2", site_id: "02", status: "closed", closure_evidence_present: true },
]);
assert.equal(duplicate.status, "partial");
assert.equal(duplicate.rows.length, 2);
assert.equal(duplicate.rows[0].identityState, "duplicate");
assert.equal(duplicate.rows[1].identityState, "duplicate");
assert.notEqual(
  assuranceRemediationDisplayKey(duplicate.rows[0]),
  assuranceRemediationDisplayKey(duplicate.rows[1]),
);
assert.ok(duplicate.issues.some((item) => item.message.includes("重复风险实例")));

const invalidBoolean = normalizeMedicalMonitoringAssuranceRemediation([
  { risk_instance_id: "risk-boolean", closure_evidence_present: "false" },
]);
assert.equal(invalidBoolean.status, "partial");
assert.equal(invalidBoolean.rows[0].closureEvidencePresent, null);
assert.equal(assuranceRemediationSeverityLabel("critical"), "紧急");
assert.equal(assuranceRemediationStatusLabel("pending_review"), "待医学复核");

console.log("medicalMonitoringAssuranceRemediation: contract checks passed");
