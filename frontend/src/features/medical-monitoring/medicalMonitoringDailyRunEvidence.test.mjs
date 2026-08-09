import assert from "node:assert/strict";

import {
  medicalMonitoringRunStepCountLabel,
  medicalMonitoringRunStepEvidenceLabel,
  medicalMonitoringRunStepStatusLabel,
  normalizeMedicalMonitoringDailyRunEvidence,
} from "./medicalMonitoringDailyRunEvidence.mjs";

const sha = "a".repeat(64);
const step = (stepName, status = "completed", details = {}) => ({
  step_name: stepName,
  status,
  attempt_count: 1,
  input_sha256: sha,
  output_sha256: status === "completed" ? sha : "",
  details,
  started_at: "2026-08-03T10:00:00+08:00",
  updated_at: "2026-08-03T10:01:00+08:00",
  finished_at: status === "running" ? "" : "2026-08-03T10:01:00+08:00",
});

const ready = normalizeMedicalMonitoringDailyRunEvidence([
  step("initial_baseline", "completed", { batch_id: "batch-1", reason: "无上一基线" }),
  step("deterministic_rules", "completed", {
    candidate_count: 2,
    diagnostic_count: 1,
    evaluated_record_count: 12,
    failed_resolution_count: 0,
  }),
]);
assert.equal(ready.status, "ready");
assert.equal(ready.value.rows[0].status, "completed");
assert.equal(ready.value.rows[1].status, "not_applicable");
assert.equal(ready.value.rows[2].details[0].value, "2");
assert.equal(ready.value.summary.completed, 2);
assert.equal(ready.value.summary.knownRecorded, 2);
assert.deepEqual(ready.issues, []);

const diffReady = normalizeMedicalMonitoringDailyRunEvidence([
  step("batch_diff", "completed", { diff_snapshot_id: "diff-1", algorithm_output_sha256: sha }),
]);
assert.equal(diffReady.value.rows[0].status, "not_applicable");
assert.equal(diffReady.value.rows[1].status, "completed");
assert.equal(medicalMonitoringRunStepEvidenceLabel(diffReady.value.rows[1]), "输出已绑定");

const running = normalizeMedicalMonitoringDailyRunEvidence([
  step("independent_ai_submission", "running", { job_count: 3 }),
]);
assert.equal(running.status, "ready");
assert.equal(running.value.summary.running, 1);
assert.equal(running.value.rows[3].attemptCount, 1);
assert.equal(medicalMonitoringRunStepStatusLabel("running"), "运行中");

const empty = normalizeMedicalMonitoringDailyRunEvidence([]);
assert.equal(empty.status, "empty");
assert.equal(empty.value, null);
assert.equal(medicalMonitoringRunStepEvidenceLabel({ status: "not_started" }), "尚未生成");

const malformed = normalizeMedicalMonitoringDailyRunEvidence("bad");
assert.equal(malformed.status, "malformed");
assert.equal(malformed.value, null);

const invalid = normalizeMedicalMonitoringDailyRunEvidence([
  step("deterministic_rules", "completed", { candidate_count: "2" }),
  { ...step("risk_snapshot_assembly"), attempt_count: -1, output_sha256: "bad" },
]);
assert.equal(invalid.status, "partial");
assert.ok(invalid.issues.some((item) => item.field.includes("attempt_count")));
assert.ok(invalid.issues.some((item) => item.field.includes("output_sha256")));
assert.ok(invalid.issues.some((item) => item.field === "candidate_count"));

const failed = normalizeMedicalMonitoringDailyRunEvidence([
  step("independent_ai_submission", "failed", { job_count: 4 }),
]);
assert.equal(failed.value.summary.failed, 1);
assert.equal(medicalMonitoringRunStepEvidenceLabel(failed.value.rows[3]), "待核对");

const duplicate = normalizeMedicalMonitoringDailyRunEvidence([
  step("deterministic_rules"),
  step("deterministic_rules"),
]);
assert.equal(duplicate.status, "partial");
assert.ok(duplicate.issues.some((item) => item.message.includes("重复")));

const unknown = normalizeMedicalMonitoringDailyRunEvidence([
  step("future_step", "skipped"),
]);
assert.equal(unknown.status, "ready");
assert.equal(unknown.value.summary.unknownRecorded, 1);
assert.equal(unknown.value.rows[5].label, "其他步骤");
assert.equal(medicalMonitoringRunStepStatusLabel("future"), "待核对");

const missingInput = normalizeMedicalMonitoringDailyRunEvidence([
  { ...step("batch_diff"), input_sha256: "" },
]);
assert.equal(missingInput.status, "partial");
assert.ok(missingInput.issues.some((item) => item.field.includes("input_sha256")));

assert.equal(medicalMonitoringRunStepCountLabel(0), "0");
assert.equal(medicalMonitoringRunStepCountLabel("0"), "待核对");

console.log("medicalMonitoringDailyRunEvidence: 31 passed");
