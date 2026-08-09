import assert from "node:assert/strict";

import {
  MedicalMonitoringFieldMappingShapeError,
  normalizeFieldMappingRun,
  normalizeFieldMappingStatus,
  normalizeMappingDraft,
  normalizeMappingRevision,
  normalizeSemanticQualityReport,
  medicalMonitoringFieldMappingEvidenceKey,
} from "./medicalMonitoringFieldMappingView.mjs";

const field = {
  domain: "AE",
  source_field: "AETERM",
  recommended_role: "adverse_event_reported_term",
  field_kind: "source_collected",
  confidence: 0.91,
  uncertainty: "需结合项目字典复核编码语义。",
  user_action: "核对原始字段与医学角色。",
  evidence_ids: ["evidence-1"],
};

const job = {
  job_id: "job-1",
  status: "completed",
};

const status = {
  batch_id: "batch-1",
  profile_sha256: "a".repeat(64),
  input_sha256: "b".repeat(64),
  field_count: 1,
  job_count: 1,
  job_details: [
    {
      job,
      candidates: [
        {
          candidate_id: "candidate-1",
          structured_payload: { field_mappings: [field] },
        },
      ],
    },
  ],
  draft: null,
  semantic_quality: null,
  active_mapping: null,
};

const normalizedStatus = normalizeFieldMappingStatus(status);
assert.equal(normalizedStatus.job_details[0].job.job_id, "job-1");
assert.equal(
  normalizedStatus.job_details[0].candidates[0]
    .structured_payload.field_mappings[0].source_field,
  "AETERM",
);

assert.throws(
  () => normalizeFieldMappingStatus({ ...status, job_details: "not-an-array" }),
  MedicalMonitoringFieldMappingShapeError,
);
assert.throws(
  () => normalizeFieldMappingStatus({
    ...status,
    job_details: [{ ...status.job_details[0], candidates: "not-an-array" }],
  }),
  MedicalMonitoringFieldMappingShapeError,
);
assert.throws(
  () => normalizeFieldMappingStatus({
    ...status,
    job_details: [{
      ...status.job_details[0],
      candidates: [{
        candidate_id: "candidate-1",
        structured_payload: { field_mappings: "not-an-array" },
      }],
    }],
  }),
  MedicalMonitoringFieldMappingShapeError,
);
assert.throws(
  () => normalizeFieldMappingStatus({ ...status, field_count: "1" }),
  MedicalMonitoringFieldMappingShapeError,
);
assert.throws(
  () => normalizeFieldMappingRun({
    batch_id: "batch-1",
    profile_sha256: "a".repeat(64),
    input_sha256: "b".repeat(64),
    field_count: 1,
    job_count: 2,
    jobs: [job],
  }),
  MedicalMonitoringFieldMappingShapeError,
);

const draft = normalizeMappingDraft({
  draft_id: "draft-1",
  version: 3,
  status: "draft",
  fields: [field],
});
assert.equal(draft.fields[0].confidence, 0.91);
assert.throws(
  () => normalizeMappingDraft({
    draft_id: "draft-1",
    version: 3,
    status: "draft",
    fields: [{ ...field, confidence: "0.91" }],
  }),
  MedicalMonitoringFieldMappingShapeError,
);

const quality = normalizeSemanticQualityReport({
  status: "pass_with_warnings",
  activation_disposition: "activate_full",
  global_blocker_count: 0,
  capability_blocker_count: 0,
  warning_count: 1,
  finding_groups: [],
  capability_states: [],
});
assert.equal(quality.warning_count, 1);
assert.throws(
  () => normalizeSemanticQualityReport({
    status: "pass_with_warnings",
    activation_disposition: "activate_full",
    global_blocker_count: "0",
    capability_blocker_count: 0,
    warning_count: 0,
    finding_groups: [],
    capability_states: [],
  }),
  MedicalMonitoringFieldMappingShapeError,
);

const revision = normalizeMappingRevision({
  mapping_revision: "revision-1",
  draft_id: "draft-1",
  draft_version: 3,
  fields: [field],
  activation: { mapping_revision: "revision-1", project_version: 4 },
});
assert.equal(revision.activation.project_version, 4);

const evidenceRows = normalizeMappingDraft({
  draft_id: "draft-evidence",
  version: 1,
  status: "draft",
  fields: [{
    ...field,
    evidence_summary: [
      { profile: { non_empty_count: 1, total_rows: 2 } },
      { profile: { non_empty_count: 2, total_rows: 2 } },
    ],
  }],
});
assert.equal(evidenceRows.fields[0].evidence_summary[0].sourceIndex, 0);
assert.notEqual(
  medicalMonitoringFieldMappingEvidenceKey(evidenceRows.fields[0].evidence_summary[0]),
  medicalMonitoringFieldMappingEvidenceKey(evidenceRows.fields[0].evidence_summary[1]),
);
assert.equal(
  medicalMonitoringFieldMappingEvidenceKey({ evidence_id: "e-1" }),
  "evidence:e-1:0",
);

console.log("medicalMonitoringFieldMappingView: 15 passed");
