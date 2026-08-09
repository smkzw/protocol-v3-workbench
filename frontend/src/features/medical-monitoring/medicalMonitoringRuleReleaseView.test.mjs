import assert from "node:assert/strict";

import {
  MedicalMonitoringRuleReleaseShapeError,
  normalizeAutomaticShadowResult,
  normalizeRulePackDetail,
  normalizeRulePackDiff,
  normalizeRulePackDraftResult,
  normalizeRulePackList,
  normalizeRulePackMutationResult,
  normalizeRuleReleaseReadiness,
  normalizeShadowConfirmationResult,
  normalizeShadowLineageEvidence,
  normalizeShadowRunList,
  normalizeShadowSampleSetList,
  ruleReleaseSampleDisplayKey,
} from "./medicalMonitoringRuleReleaseView.mjs";

const projectId = "project-1";
const pack = {
  rule_pack_id: "pack-1",
  project_id: projectId,
  protocol_version_id: "protocol-1",
  pack_revision: 1,
  status: "published",
  applicability_status: "version_date_only",
  rule_revision_ids: ["rule-revision-1"],
  content_sha256: "a".repeat(64),
  created_by: "medical_manager",
  retrospective_policy: "open_risks_only",
  published_at: "2026-08-02T00:00:00Z",
};
const rule = {
  project_id: projectId,
  protocol_version_id: "protocol-1",
  rule_revision_id: "rule-revision-1",
  rule_key: "ae_missing_report",
  status: "enabled",
  title: "AE 漏报核查",
  required_domains: ["AE"],
  source_locator: "方案 5.2 节",
  state_version: 1,
};
const sample = {
  project_id: projectId,
  sample_id: "sample-1",
  rule_key: "ae_missing_report",
  rule_revision_id: "rule-revision-1",
  bucket: "positive",
  case_label: "受试者 S001",
  business_key: "S001/AE-1",
  actual_matched: true,
  actual_evaluation_state: "true",
  actual_diagnostic_code: "",
  evidence_summary: "AE 记录未在规定时限内上报。",
};
const inspection = {
  project_id: projectId,
  sample_set_id: "sample-set-1",
  status: "provisional",
  rule_pack_id: "pack-shadow-1",
  batch_id: "batch-1",
  batch_version: 2,
  batch_revision: "batch-rev-2",
  mapping_revision: "mapping-1",
  sample_count: 1,
  samples: [sample],
};
const run = {
  project_id: projectId,
  shadow_run_id: "run-1",
  rule_pack_id: "pack-shadow-1",
  batch_id: "batch-1",
  status: "completed",
  case_count: 1,
  passed_count: 1,
  failed_count: 0,
  diagnostic_case_count: 0,
  diagnostic_passed_count: 0,
  diagnostic_failed_count: 0,
  results: [{
    case_id: "case-1",
    rule_key: "ae_missing_report",
    expected_match: true,
    actual_match: true,
    passed: true,
    evidence_summary: "符合冻结样本判定。",
  }],
  diagnostic_results: [],
};

const detail = normalizeRulePackDetail({
  project_id: projectId,
  pack,
  rules: [rule],
}, projectId);
assert.equal(detail.pack.rule_pack_id, "pack-1");
assert.equal(detail.rules[0].rule_revision_id, "rule-revision-1");

const list = normalizeRulePackList({ project_id: projectId, items: [pack] }, projectId);
assert.equal(list.items[0].pack_revision, 1);
const publicPack = { ...pack };
delete publicPack.content_sha256;
assert.equal(
  normalizeRulePackList({ project_id: projectId, items: [publicPack] }, projectId)
    .items[0].rule_pack_id,
  "pack-1",
);

const mutation = normalizeRulePackMutationResult({ project_id: projectId, pack }, projectId);
assert.equal(mutation.pack.project_id, projectId);

const draft = normalizeRulePackDraftResult({
  project_id: projectId,
  pack: { ...pack, status: "draft" },
  rules: [{ ...rule, status: "confirmed" }],
  reused: false,
}, projectId);
assert.equal(draft.rules.length, 1);

const automatic = normalizeAutomaticShadowResult({
  project_id: projectId,
  pack: { ...pack, status: "shadow" },
  inspection,
  reused: false,
}, projectId);
assert.equal(automatic.inspection.sample_count, 1);

const confirmation = normalizeShadowConfirmationResult({
  project_id: projectId,
  pack: { ...pack, status: "confirmed" },
  confirmation_id: "confirmation-1",
  shadow_run_id: "run-1",
}, projectId);
assert.equal(confirmation.pack.status, "confirmed");

const sampleList = normalizeShadowSampleSetList({
  project_id: projectId,
  items: [inspection],
}, projectId);
assert.equal(sampleList.items[0].samples[0].sample_id, "sample-1");
assert.equal(sampleList.items[0].samples[0].displayIdentityState, "ready");
assert.equal(sampleList.items[0].samples[0].displaySourceIndex, 0);
assert.equal(ruleReleaseSampleDisplayKey(sampleList.items[0].samples[0]), "rule-release-sample:sample-1:0");

const duplicateSampleInspection = normalizeShadowSampleSetList({
  project_id: projectId,
  items: [{
    ...inspection,
    sample_count: 2,
    samples: [sample, { ...sample, case_label: "受试者 S002", business_key: "S002/AE-1" }],
  }],
}, projectId);
assert.equal(duplicateSampleInspection.items[0].samples.length, 2);
assert.equal(duplicateSampleInspection.items[0].samples[0].displayIdentityState, "duplicate");
assert.equal(duplicateSampleInspection.items[0].samples[1].displayIdentityState, "duplicate");
assert.notEqual(
  ruleReleaseSampleDisplayKey(duplicateSampleInspection.items[0].samples[0]),
  ruleReleaseSampleDisplayKey(duplicateSampleInspection.items[0].samples[1]),
);
assert.ok(duplicateSampleInspection.items[0].samples[0].displayIdentityIssue.includes("重复"));
const { project_id: _sampleProject, rule_revision_id: _sampleRevision, ...publicSample } = sample;
const { project_id: _inspectionProject, ...publicInspectionBase } = inspection;
assert.equal(
  normalizeShadowSampleSetList({
    project_id: projectId,
    items: [{ ...publicInspectionBase, samples: [publicSample] }],
  }, projectId).items[0].project_id,
  projectId,
);

const runList = normalizeShadowRunList({ project_id: projectId, items: [run] }, projectId);
assert.equal(runList.items[0].passed_count, 1);
const { project_id: _runProject, rule_pack_id: _runPack, ...publicRun } = run;
assert.equal(
  normalizeShadowRunList({ project_id: projectId, items: [publicRun] }, projectId, "pack-shadow-1")
    .items[0].rule_pack_id,
  "pack-shadow-1",
);

const lineage = normalizeShadowLineageEvidence({
  project_id: projectId,
  rule_pack_id: "pack-1",
  shadow_rule_pack_id: "pack-shadow-1",
  items: [inspection],
  confirmation: {
    confirmation_id: "confirmation-1",
    sample_set_id: "sample-set-1",
    trusted_shadow_run_id: "run-1",
    confirmed_at: "2026-08-02T00:00:00Z",
  },
}, projectId, "pack-1");
assert.equal(lineage.confirmation.sample_set_id, "sample-set-1");

const diff = normalizeRulePackDiff({
  project_id: projectId,
  impact: {
    previous_rule_pack_id: "pack-old",
    current_rule_pack_id: "pack-1",
    added_rule_keys: [],
    changed_rule_keys: ["ae_missing_report"],
    superseded_rule_keys: [],
    unchanged_rule_keys: [],
  },
}, projectId);
assert.equal(diff.impact.changed_rule_keys[0], "ae_missing_report");

const readiness = normalizeRuleReleaseReadiness({
  project_id: projectId,
  batch_id: "batch-1",
  ready: false,
  state_code: "monitoring_rule_pack_required",
  message: "请先准备规则包。",
  next_action: "prepare_rule_pack",
}, projectId, "batch-1");
assert.equal(readiness.ready, false);

assert.throws(
  () => normalizeRulePackList({ project_id: "project-2", items: [pack] }, projectId),
  MedicalMonitoringRuleReleaseShapeError,
);
assert.throws(
  () => normalizeRulePackDetail({ project_id: projectId, pack, rules: [] }, projectId),
  MedicalMonitoringRuleReleaseShapeError,
);
assert.throws(
  () => normalizeAutomaticShadowResult({
    project_id: projectId,
    pack: { ...pack, status: "shadow" },
    inspection: { ...inspection, sample_count: 2 },
  }, projectId),
  MedicalMonitoringRuleReleaseShapeError,
);
assert.throws(
  () => normalizeShadowRunList({
    project_id: projectId,
    items: [{ ...run, passed_count: 0, failed_count: 0 }],
  }, projectId),
  MedicalMonitoringRuleReleaseShapeError,
);
assert.throws(
  () => normalizeShadowLineageEvidence({
    project_id: projectId,
    rule_pack_id: "pack-1",
    shadow_rule_pack_id: "pack-shadow-1",
    items: [inspection],
    confirmation: {
      confirmation_id: "confirmation-1",
      sample_set_id: "missing-set",
      trusted_shadow_run_id: "run-1",
      confirmed_at: "2026-08-02T00:00:00Z",
    },
  }, projectId, "pack-1"),
  MedicalMonitoringRuleReleaseShapeError,
);
assert.throws(
  () => normalizeRuleReleaseReadiness({
    project_id: projectId,
    batch_id: "batch-2",
    ready: true,
    state_code: "ready",
    message: "ok",
    next_action: "start_daily_run",
  }, projectId, "batch-1"),
  MedicalMonitoringRuleReleaseShapeError,
);

console.log("medicalMonitoringRuleReleaseView: 21 passed");
