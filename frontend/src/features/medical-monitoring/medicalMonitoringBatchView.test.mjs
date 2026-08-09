import assert from "node:assert/strict";

import {
  MedicalMonitoringBatchShapeError,
  batchDisplayKey,
  normalizeBatchDetail,
  normalizeBatchIntakeResult,
  normalizeBatchList,
  normalizeBatchMutationResult,
  normalizeClassificationConfirmationDetail,
  normalizeContentConfirmationDetail,
} from "./medicalMonitoringBatchView.mjs";

const batch = {
  batch_id: "batch-1",
  project_id: "project-1",
  state: "parsed",
  version: 2,
  expected_domains: ["AE", "LB"],
  active_mapping_revision: null,
  full_snapshot_proof: null,
  created_at: "2026-08-02T00:00:00+08:00",
  updated_at: "2026-08-02T00:01:00+08:00",
  frozen_at: null,
};

const source = {
  source_id: "source-1",
  source_entry_id: "entry-1",
  source_class: "raw_full_snapshot_candidate",
  file_name: "listing.xlsx",
  content_sha256: "a".repeat(64),
  size_bytes: 100,
  technical_status: "passed",
  content_warnings: [],
  medical_override_reason: null,
  created_at: "2026-08-02T00:00:00+08:00",
};

const validation = {
  validation_id: "validation-1",
  revision: 1,
  use_status: "allowed",
  summary: "文件信息一致。",
  checks: [
    {
      check_code: "filename",
      outcome: "match",
      label: "文件名",
      observed_value: "listing.xlsx",
    },
  ],
};

const classification = {
  source_class: "raw_full_snapshot_candidate",
  technical_status: "passed",
  content_warnings: [],
};

const normalizedList = normalizeBatchList({
  project_id: "project-1",
  batches: [batch],
});
assert.equal(normalizedList.batches[0].batch_id, "batch-1");
assert.equal(normalizedList.batches[0].displayIdentityState, "ready");

const duplicateList = normalizeBatchList({
  project_id: "project-1",
  batches: [batch, { ...batch, version: 3 }],
});
assert.equal(duplicateList.batches[0].displayIdentityState, "duplicate");
assert.equal(duplicateList.batches[1].displayIdentityState, "duplicate");
assert.equal(new Set(duplicateList.batches.map((item) => item.displayKey)).size, 2);
assert.match(duplicateList.batches[0].displayIdentityIssue, /暂不能选择/);
assert.equal(batchDisplayKey(batch, 4), "batch:batch-1:4");

const normalizedDetail = normalizeBatchDetail({
  ...batch,
  sources: [source],
  row_count: 10,
  domain_counts: { AE: 6, LB: 4 },
});
assert.equal(normalizedDetail.sources[0].source_class, "raw_full_snapshot_candidate");
assert.equal(normalizedDetail.domain_counts.AE, 6);

const mutation = normalizeBatchMutationResult({ batch, replayed: false });
assert.equal(mutation.batch.version, 2);

const intake = normalizeBatchIntakeResult({
  source_entry_id: "entry-1",
  validation,
  classification,
  source,
  batch: { batch: { ...batch, state: "draft", version: 1 }, replayed: false },
  observed_domains: ["AE", "LB"],
  row_count: 10,
});
assert.equal(intake.batch.batch.state, "draft");
assert.equal(intake.validation.checks[0].outcome, "match");

const contentDetail = normalizeContentConfirmationDetail({
  source_entry_id: "entry-1",
  validation,
});
assert.equal(contentDetail.validation.revision, 1);

const classificationDetail = normalizeClassificationConfirmationDetail({
  source_entry_id: "entry-1",
  classification: {
    ...classification,
    content_warnings: ["需医学经理确认"],
  },
});
assert.equal(classificationDetail.classification.content_warnings.length, 1);

assert.throws(
  () => normalizeBatchList({ project_id: "project-1", batches: "not-an-array" }),
  MedicalMonitoringBatchShapeError,
);
assert.throws(
  () => normalizeBatchList({
    project_id: "project-1",
    batches: [{ ...batch, project_id: "project-2" }],
  }),
  MedicalMonitoringBatchShapeError,
);
assert.throws(
  () => normalizeBatchDetail({
    ...batch,
    sources: [{ ...source, content_warnings: "not-an-array" }],
    row_count: 10,
    domain_counts: { AE: 6 },
  }),
  MedicalMonitoringBatchShapeError,
);
assert.throws(
  () => normalizeBatchDetail({
    ...batch,
    sources: [source],
    row_count: "10",
    domain_counts: { AE: 6 },
  }),
  MedicalMonitoringBatchShapeError,
);
assert.throws(
  () => normalizeBatchIntakeResult({
    source_entry_id: "entry-1",
    validation: { ...validation, checks: "not-an-array" },
    classification,
    source,
    batch: { batch, replayed: false },
    observed_domains: ["AE"],
    row_count: 1,
  }),
  MedicalMonitoringBatchShapeError,
);
assert.throws(
  () => normalizeContentConfirmationDetail({
    source_entry_id: "entry-1",
    validation: {
      ...validation,
      checks: [{ ...validation.checks[0], outcome: "unexpected" }],
    },
  }),
  MedicalMonitoringBatchShapeError,
);

console.log("medicalMonitoringBatchView: 13 passed");
