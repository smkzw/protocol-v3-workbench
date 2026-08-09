import assert from "node:assert/strict";

import {
  medicalMonitoringAiCountLabel,
  medicalMonitoringAiFailureKind,
  medicalMonitoringAiFailureDisplayKey,
  medicalMonitoringAiStatusLabel,
  normalizeMedicalMonitoringDailyAiEvidence,
} from "./medicalMonitoringDailyAiEvidence.mjs";

const run = {
  run_id: "run-001",
  batch_id: "batch-002",
  engine_version: "monitoring-engine-3",
  rule_pack_revision: "rules-12",
};

const valid = normalizeMedicalMonitoringDailyAiEvidence({
  submitted: true,
  run,
  progress: {
    status: "partial_completed",
    total: 4,
    queued: 1,
    running: 1,
    completed: 1,
    failed: 1,
    candidate_count: 3,
    failures: [{
      job_id: "job-4",
      subject_id: "SUBJ-004",
      status: "failed",
      failure_code: "source_gap",
      failure_message: "证据不完整",
    }],
  },
});
assert.equal(valid.status, "ready");
assert.equal(valid.value.progressStatus, "partial_completed");
assert.equal(valid.value.counts.candidateCount, 3);
assert.equal(valid.value.failures[0].subjectId, "SUBJ-004");
assert.equal(valid.value.failures[0].failureKind, "unknown");
assert.equal(valid.value.failures[0].failureLabel, "失败原因待核对");
assert.equal(valid.value.failures[0].sourceIndex, 0);
assert.equal(medicalMonitoringAiFailureDisplayKey(valid.value.failures[0]), "ai-failure:job-4:0");
assert.equal(valid.value.completionPercent, 25);
assert.deepEqual(valid.issues, []);

const notSubmitted = normalizeMedicalMonitoringDailyAiEvidence({
  submitted: false,
  run,
  progress: null,
});
assert.equal(notSubmitted.status, "not_submitted");
assert.equal(notSubmitted.value.counts.total, null);
assert.equal(notSubmitted.value.progressStatus, "not_submitted");

const unavailable = normalizeMedicalMonitoringDailyAiEvidence({
  submitted: true,
  run,
  progress: null,
});
assert.equal(unavailable.status, "unavailable");
assert.equal(unavailable.value.counts.total, null);
assert.equal(unavailable.issues[0].field, "progress");

const malformed = normalizeMedicalMonitoringDailyAiEvidence({
  submitted: true,
  run,
  progress: "running",
});
assert.equal(malformed.status, "malformed");
assert.equal(malformed.value, null);

const missing = normalizeMedicalMonitoringDailyAiEvidence({
  submitted: true,
  run,
  progress: {
    status: "completed",
    total: 2,
    queued: 0,
    running: 0,
    completed: 2,
    failed: 0,
    candidate_count: 0,
    failures: [],
  },
});
assert.equal(missing.status, "ready");

const invalid = normalizeMedicalMonitoringDailyAiEvidence({
  submitted: true,
  run,
  progress: {
    status: "completed",
    total: 2,
    queued: 0,
    running: 0,
    completed: 1,
    failed: 0,
    candidate_count: -1,
    failures: "not-an-array",
  },
});
assert.equal(invalid.status, "partial");
assert.equal(invalid.value.counts.candidateCount, null);
assert.ok(invalid.issues.some((item) => item.field === "failures"));
assert.ok(invalid.issues.some((item) => item.field === "counts"));

const detailCountMismatch = normalizeMedicalMonitoringDailyAiEvidence({
  submitted: true,
  run,
  progress: {
    status: "completed",
    total: 1,
    queued: 0,
    running: 0,
    completed: 1,
    failed: 0,
    candidate_count: 0,
    failures: [{
      job_id: "job-1",
      failure_code: "provider_timeout",
      failure_message: "provider request timed out",
    }],
  },
});
assert.equal(detailCountMismatch.status, "partial");
assert.equal(detailCountMismatch.value.failures[0].failureKind, "timeout");
assert.ok(detailCountMismatch.issues.some((item) => item.field === "failures"));

const missingFailureCountWithDetail = normalizeMedicalMonitoringDailyAiEvidence({
  submitted: true,
  run,
  progress: {
    status: "failed",
    total: 1,
    queued: 0,
    running: 0,
    completed: 0,
    failed: null,
    candidate_count: 0,
    failures: [{
      job_id: "job-1",
      failure_code: "invalid_ai_output",
      failure_message: "invalid JSON structure",
    }],
  },
});
assert.equal(missingFailureCountWithDetail.status, "partial");
assert.equal(missingFailureCountWithDetail.value.failures[0].failureKind, "invalid_structure");

const duplicateFailures = normalizeMedicalMonitoringDailyAiEvidence({
  submitted: true,
  run,
  progress: {
    status: "failed",
    total: 2,
    queued: 0,
    running: 0,
    completed: 0,
    failed: 2,
    candidate_count: 0,
    failures: [
      { job_id: "job-dup", failure_message: "first" },
      { job_id: "job-dup", failure_message: "second" },
    ],
  },
});
assert.equal(duplicateFailures.status, "partial");
assert.ok(duplicateFailures.issues.some((item) => item.message.includes("重复 job_id")));
assert.notEqual(
  medicalMonitoringAiFailureDisplayKey(duplicateFailures.value.failures[0]),
  medicalMonitoringAiFailureDisplayKey(duplicateFailures.value.failures[1]),
);

assert.equal(medicalMonitoringAiFailureKind("rate_limit", "HTTP 429").label, "限流");
assert.equal(medicalMonitoringAiFailureKind("monitoring_ai_low_confidence", "confidence below threshold").label, "低置信度");
assert.equal(medicalMonitoringAiFailureKind("ai_not_configured", "disabled").label, "配置或传输不可用");
assert.equal(medicalMonitoringAiFailureKind("stale_input_revision", "source revision changed").label, "来源修订过期");
assert.equal(medicalMonitoringAiFailureKind("cancelled", "blocked").label, "任务阻断或取消");

const unknownStatus = normalizeMedicalMonitoringDailyAiEvidence({
  submitted: true,
  run,
  progress: {
    status: "surprising",
    total: 0,
    queued: 0,
    running: 0,
    completed: 0,
    failed: 0,
    candidate_count: 0,
    failures: [],
  },
});
assert.equal(unknownStatus.status, "partial");
assert.equal(unknownStatus.value.progressStatus, null);

const malformedFailure = normalizeMedicalMonitoringDailyAiEvidence({
  submitted: true,
  run,
  progress: {
    status: "failed",
    total: 1,
    queued: 0,
    running: 0,
    completed: 0,
    failed: 1,
    candidate_count: 0,
    failures: ["bad"],
  },
});
assert.equal(malformedFailure.status, "partial");
assert.deepEqual(malformedFailure.value.failures, []);

const noSubmittedFlag = normalizeMedicalMonitoringDailyAiEvidence({
  run,
  progress: null,
});
assert.equal(noSubmittedFlag.status, "unavailable");
assert.ok(noSubmittedFlag.issues.some((item) => item.field === "submitted"));

const lineageGap = normalizeMedicalMonitoringDailyAiEvidence({
  submitted: false,
  run: { run_id: "run-001" },
  progress: null,
});
assert.equal(lineageGap.status, "partial");
assert.ok(lineageGap.issues.some((item) => item.field === "batch_id"));

assert.equal(medicalMonitoringAiStatusLabel("running"), "复核中");
assert.equal(medicalMonitoringAiStatusLabel("unknown"), "待核对");
assert.equal(medicalMonitoringAiCountLabel(0), "0");
assert.equal(medicalMonitoringAiCountLabel("0"), "待核对");

console.log("medicalMonitoringDailyAiEvidence: 36 passed");
