import assert from "node:assert/strict";
import {
  assuranceRollupLevelKeys,
  assuranceRollupNumber,
  assuranceRollupRowDisplayKey,
  projectAssuranceRollup,
} from "./medicalMonitoringAssuranceRollup.mjs";

const rollup = {
  risk_snapshot_id: "snapshot-1",
  trial_rollup: {
    total_risk_count: 3,
    open_risk_count: 2,
    open_high_risk_count: 1,
    closed_risk_count: 1,
    closed_risks_lacking_evidence_count: 0,
    safety_pv_risk_count: 1,
    concomitant_medication_risk_count: 1,
    study_treatment_risk_count: 0,
    risk_instance_ids: ["risk-1", "risk-2", "risk-3"],
  },
  site_rollup: [
    { site_id: "10", total_risk_count: 2, open_risk_count: 1, open_high_risk_count: 1, risk_instance_ids: ["risk-1", "risk-2"] },
    { site_id: "06", total_risk_count: 1, open_risk_count: 1, open_high_risk_count: 0, risk_instance_ids: ["risk-3"] },
  ],
  subject_rollup: [
    { subject_id: "10001", site_id: "10", total_risk_count: 1, open_risk_count: 1, risk_instance_ids: ["risk-1"] },
    { subject_id: "10002", site_id: "10", total_risk_count: 1, open_risk_count: 0, risk_instance_ids: ["risk-2"] },
    { subject_id: "06001", site_id: "06", total_risk_count: 1, open_risk_count: 1, risk_instance_ids: ["risk-3"] },
  ],
  distributions: {
    by_severity: { high: 1, medium: 2 },
    by_status: { open: 2, closed: 1 },
    by_disposition: { open: 2, closed: 1 },
  },
  evidence_manifest: [{ risk_instance_id: "risk-1" }],
  remediation_matrix: [{ risk_instance_id: "risk-1" }],
};

const view = projectAssuranceRollup(rollup);
assert.deepEqual(assuranceRollupLevelKeys(), ["trial", "site", "subject"]);
assert.equal(view.available, true);
assert.equal(view.riskSnapshotId, "snapshot-1");
assert.equal(view.trial.openHighRiskCount, 1);
assert.deepEqual(view.sites.map((row) => row.siteId), ["10", "06"]);
assert.deepEqual(view.subjects.map((row) => row.subjectId), ["06001", "10001", "10002"]);
assert.equal(view.distributions.severity[0].label, "medium");
assert.equal(view.evidenceCount, 1);
assert.equal(view.remediationCount, 1);
assert.equal(view.conservation.ok, true);
assert.equal(assuranceRollupNumber(0), "0");
assert.equal(assuranceRollupNumber("bad"), "—");
assert.equal(assuranceRollupNumber(false), "—");
assert.equal(assuranceRollupNumber("  "), "—");

const ambiguous = projectAssuranceRollup({
  ...rollup,
  site_rollup: [
    { site_id: "10", total_risk_count: 1, open_risk_count: 1, risk_instance_ids: ["risk-1"] },
    { site_id: "10", total_risk_count: 1, open_risk_count: 0, risk_instance_ids: ["risk-2"] },
  ],
  subject_rollup: [
    { site_id: "10", total_risk_count: 1, open_risk_count: 1, risk_instance_ids: ["risk-1"] },
    { total_risk_count: 0, open_risk_count: 0, risk_instance_ids: [] },
  ],
});
assert.equal(ambiguous.sites.every((row) => row.identityState === "duplicate"), true);
assert.equal(ambiguous.subjects.at(-1).identityState, "missing");
assert.notEqual(
  assuranceRollupRowDisplayKey(ambiguous.sites[0], "site", 0),
  assuranceRollupRowDisplayKey(ambiguous.sites[1], "site", 1),
);

const tampered = projectAssuranceRollup({
  ...rollup,
  site_rollup: [{ ...rollup.site_rollup[0], risk_instance_ids: ["risk-1"] }],
});
assert.equal(tampered.conservation.ok, false);
assert.equal(tampered.conservation.riskInstanceIdsMatch, false);

const empty = projectAssuranceRollup(null);
assert.equal(empty.available, false);
assert.equal(empty.conservation.ok, false);

console.log("medicalMonitoringAssuranceRollup: 16 passed");
