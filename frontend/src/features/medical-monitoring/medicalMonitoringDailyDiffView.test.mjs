import assert from "node:assert/strict";
import {
  dailyDiffCountLabel,
  normalizeMedicalMonitoringDailyDiff,
} from "./medicalMonitoringDailyDiffView.mjs";

const basePayload = {
  row_diff: {
    new_keys: ["new-1"],
    changed_keys: ["changed-1", "changed-2"],
    persisting_keys: ["same-1"],
    removed_keys: ["removed-1"],
    requires_rereview_keys: ["changed-1"],
    missing_current_domains: ["AE"],
    removal_resolution_blocked_keys: ["removed-1"],
  },
  identity_match_counts: { exact: 3, normalized: 2 },
  identity_match_samples: [{
    previous_business_key: "previous-key",
    current_business_key: "current-key",
    match_basis: "exact",
  }],
  field_changes: [{
    domain: "AE",
    business_key: "ae-key",
    field_name: "AESEV",
    change_kind: "changed",
    previous_locator: "listing:sheet:AE:row:2",
    current_locator: "listing:sheet:AE:row:3",
  }],
  schema_diffs: [{ domain: "AE", added_fields: ["AESEV"], removed_fields: [] }],
  removal_eligible_keys: [],
  removal_blocked_keys: ["removed-1"],
  full_snapshot_proven: true,
  output_sha256: "a".repeat(64),
};

const valid = normalizeMedicalMonitoringDailyDiff({
  snapshot_id: "snap-1",
  previous_batch_id: "batch-0",
  current_batch_id: "batch-1",
  algorithm_version: "monitoring_batch_diff.v3",
  output_sha256: "a".repeat(64),
  created_at: "2026-08-03T12:00:00+08:00",
  payload: basePayload,
});
assert.equal(valid.status, "ready");
assert.equal(valid.value.counts.newRows, 1);
assert.equal(valid.value.counts.changedRows, 2);
assert.equal(valid.value.counts.removalBlockedRows, 1);
assert.equal(valid.value.counts.schemaChanges, 1);
assert.equal(valid.value.identityMatchTotal, 5);
assert.equal(valid.value.fullSnapshotProven, true);
assert.equal(valid.value.currentBatchId, "batch-1");
assert.equal(valid.value.details.fieldChanges[0].fieldName, "AESEV");
assert.equal(valid.value.details.schemaDiffs[0].addedFields[0], "AESEV");
assert.equal(valid.value.details.identityMatchSamples[0].matchBasis, "exact");
assert.equal(valid.value.details.removalBlockedKeys[0], "removed-1");
assert.deepEqual(valid.value.safetyReasons.map((item) => item.code), [
  "schema_drift",
  "missing_expected_domain",
  "removal_resolution_blocked",
]);
assert.equal(valid.issues.length, 0);

assert.equal(normalizeMedicalMonitoringDailyDiff(null).status, "empty");
assert.equal(normalizeMedicalMonitoringDailyDiff({ payload: null }).status, "malformed");
assert.equal(normalizeMedicalMonitoringDailyDiff({ payload: {} }).status, "malformed");

const partial = normalizeMedicalMonitoringDailyDiff({
  payload: {
    row_diff: { new_keys: [], changed_keys: [] },
  },
});
assert.equal(partial.status, "partial");
assert.equal(partial.value.counts.newRows, 0);
assert.equal(partial.value.counts.removedRows, null);
assert.equal(partial.value.fullSnapshotProven, null);
assert.deepEqual(partial.value.safetyReasons.map((item) => item.code), ["full_snapshot_unverified"]);
assert.ok(partial.issues.some((item) => item.field === "removed_keys" && item.kind === "missing"));

const malformedOptional = normalizeMedicalMonitoringDailyDiff({
  output_sha256: "b".repeat(64),
  payload: {
    ...basePayload,
    output_sha256: "c".repeat(64),
    row_diff: { ...basePayload.row_diff, changed_keys: ["ok", 2] },
    full_snapshot_proven: "true",
  },
});
assert.equal(malformedOptional.status, "partial");
assert.equal(malformedOptional.value.counts.changedRows, null);
assert.equal(malformedOptional.value.fullSnapshotProven, null);
assert.equal(malformedOptional.value.hasInvalid, true);
assert.ok(malformedOptional.issues.some((item) => item.field === "output_sha256"));

const malformedMap = normalizeMedicalMonitoringDailyDiff({
  payload: { ...basePayload, identity_match_counts: { exact: "3" } },
});
assert.equal(malformedMap.status, "partial");
assert.equal(malformedMap.value.identityMatchTotal, null);
const malformedDetail = normalizeMedicalMonitoringDailyDiff({
  payload: {
    ...basePayload,
    field_changes: [{ domain: "AE", business_key: "key" }],
    schema_diffs: [{ domain: "AE", added_fields: "AESEV", removed_fields: [] }],
  },
});
assert.equal(malformedDetail.status, "partial");
assert.equal(malformedDetail.value.details.fieldChanges.length, 0);
assert.equal(malformedDetail.value.details.schemaDiffs.length, 0);
assert.ok(malformedDetail.issues.some((item) => item.field === "field_changes[0]"));
assert.ok(malformedDetail.issues.some((item) => item.field === "schema_diffs[0]"));
const truncated = normalizeMedicalMonitoringDailyDiff({
  payload: {
    ...basePayload,
    row_diff: {
      ...basePayload.row_diff,
      new_keys: Array.from({ length: 9 }, (_, index) => `new-${index}`),
    },
  },
});
assert.equal(truncated.value.details.newKeys.length, 8);
assert.equal(truncated.value.details.truncated, true);
const invalidDigest = normalizeMedicalMonitoringDailyDiff({
  output_sha256: "not-a-digest",
  payload: basePayload,
});
assert.equal(invalidDigest.status, "partial");
assert.ok(invalidDigest.issues.some((item) => item.field === "output_sha256" && item.kind === "invalid"));
const duplicateMap = normalizeMedicalMonitoringDailyDiff({
  payload: { ...basePayload, identity_match_counts: { " exact ": 1, exact: 2 } },
});
assert.equal(duplicateMap.value.identityMatchTotal, null);
const clean = normalizeMedicalMonitoringDailyDiff({
  output_sha256: "a".repeat(64),
  snapshot_id: "snap-clean",
  previous_batch_id: "batch-0",
  current_batch_id: "batch-1",
  algorithm_version: "monitoring_batch_diff.v3",
  created_at: "2026-08-03T12:00:00+08:00",
  payload: {
    ...basePayload,
    row_diff: {
      ...basePayload.row_diff,
      missing_current_domains: [],
      removal_resolution_blocked_keys: [],
    },
    schema_diffs: [],
    removal_blocked_keys: [],
    full_snapshot_proven: true,
  },
});
assert.deepEqual(clean.value.safetyReasons, []);
assert.equal(dailyDiffCountLabel(0), "0");
assert.equal(dailyDiffCountLabel("0"), "待核对");

console.log("medicalMonitoringDailyDiffView: 27 passed");
