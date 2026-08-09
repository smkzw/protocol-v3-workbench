import assert from "node:assert/strict";

import {
  medicalMonitoringAiCandidateConfidenceTone,
  medicalMonitoringAiCandidateClaimKey,
  medicalMonitoringAiCandidateDisplayKey,
  medicalMonitoringAiCandidateEvidenceKey,
  medicalMonitoringAiClaimKindLabel,
  medicalMonitoringAiCandidateReviewStateLabel,
  medicalMonitoringAiCandidateStatusLabel,
  normalizeMedicalMonitoringDailyAiCandidates,
} from "./medicalMonitoringDailyAiCandidates.mjs";

const sha = "a".repeat(64);
const candidate = (overrides = {}) => ({
  subject_id: "S001",
  job_id: "job-1",
  candidate: {
    candidate_id: "candidate-1",
    project_id: "project-1",
    task_type: "cross_table_clue_synthesis",
    candidate_type: "cross_table_clue",
    title: "跨表线索",
    text: "请医学监查员核对 AE 与给药记录。",
    claims: [{
      claim_id: "claim-1",
      kind: "fact",
      text: "存在显式 AE 记录。",
      confidence: 0.9,
      evidence_ids: ["evidence-1"],
    }],
    evidence: [{
      evidence_id: "evidence-1",
      source_entry_id: "listing-1",
      source_content_sha256: sha,
      locator: "AE!row-2",
      quote: "恶心",
      input_revision_sha256: sha,
    }],
    status: "proposed",
    input_revision_sha256: sha,
    prompt_version: "daily-run-ai-v1",
    created_at: "2026-08-03T12:00:00+08:00",
    confidence_summary: {
      status: "review_required",
      label: "需医学复核",
      confidence_floor: 0.9,
      threshold: 0.7,
      claim_count: 1,
      requires_user_review: true,
      requires_additional_evidence: false,
      automation_permitted: false,
      next_step: "medical_manager_confirmation",
    },
    ...overrides,
  },
});

const ready = normalizeMedicalMonitoringDailyAiCandidates({
  candidateCount: 1,
  candidates: [candidate()],
});
assert.equal(ready.status, "ready");
assert.equal(ready.value.candidates[0].subjectId, "S001");
assert.equal(ready.value.candidates[0].evidence[0].locator, "AE!row-2");
assert.equal(ready.value.candidates[0].evidence[0].quote, "恶心");
assert.equal(ready.value.candidates[0].inputRevisionSha256, sha);
assert.equal(ready.value.candidates[0].promptVersion, "daily-run-ai-v1");
assert.equal(ready.value.candidates[0].createdAt, "2026-08-03T12:00:00+08:00");
assert.equal(ready.value.candidates[0].evidence[0].sourceContentSha256, sha);
assert.equal(ready.value.candidates[0].evidence[0].inputRevisionSha256, sha);
assert.equal(ready.value.candidates[0].sourceIndex, 0);
assert.equal(ready.value.candidates[0].evidence[0].sourceIndex, 0);
assert.equal(medicalMonitoringAiCandidateDisplayKey(ready.value.candidates[0]), "candidate:candidate-1:0");
assert.equal(medicalMonitoringAiCandidateEvidenceKey(ready.value.candidates[0].evidence[0]), "candidate-evidence:evidence-1:0");
assert.equal(ready.value.candidates[0].claims[0].sourceIndex, 0);
assert.equal(ready.value.candidates[0].claims[0].identityState, "ready");
assert.equal(medicalMonitoringAiCandidateClaimKey(ready.value.candidates[0].claims[0]), "candidate-claim:claim-1:0");
assert.equal(ready.value.candidates[0].confidenceSummary.requiresUserReview, true);
assert.equal(
  medicalMonitoringAiCandidateReviewStateLabel(ready.value.candidates[0]),
  "需医学确认",
);
assert.deepEqual(ready.issues, []);

const empty = normalizeMedicalMonitoringDailyAiCandidates({ candidateCount: 0, candidates: [] });
assert.equal(empty.status, "ready");
assert.equal(empty.value.candidates.length, 0);

const unavailable = normalizeMedicalMonitoringDailyAiCandidates({ candidateCount: 2, candidates: null });
assert.equal(unavailable.status, "unavailable");
assert.equal(unavailable.value.candidateCount, 2);

const unavailableMissingCount = normalizeMedicalMonitoringDailyAiCandidates({ candidates: null });
assert.equal(unavailableMissingCount.status, "unavailable");
assert.ok(unavailableMissingCount.issues.some((item) => item.field === "candidate_count"));

const malformed = normalizeMedicalMonitoringDailyAiCandidates({ candidateCount: 1, candidates: "bad" });
assert.equal(malformed.status, "malformed");
assert.equal(malformed.value, null);

const partial = normalizeMedicalMonitoringDailyAiCandidates({
  candidateCount: 1,
  candidates: [candidate({
    input_revision_sha256: "b".repeat(64),
  })],
});
assert.equal(partial.status, "partial");
assert.ok(partial.issues.some((item) => item.field.includes("input_revision_sha256")));

const provenanceGap = normalizeMedicalMonitoringDailyAiCandidates({
  candidateCount: 1,
  candidates: [candidate({ prompt_version: "" })],
});
assert.equal(provenanceGap.status, "partial");
assert.ok(provenanceGap.issues.some((item) => item.field.includes("prompt_version")));

const low = normalizeMedicalMonitoringDailyAiCandidates({
  candidateCount: 1,
  candidates: [candidate({
    confidence_summary: {
      status: "low",
      label: "低置信度",
      confidence_floor: 0.2,
      threshold: 0.7,
      claim_count: 1,
      requires_user_review: true,
      requires_additional_evidence: true,
      automation_permitted: false,
      next_step: "medical_manager_confirmation",
    },
  })],
});
assert.equal(low.status, "ready");
assert.equal(medicalMonitoringAiCandidateConfidenceTone(low.value.candidates[0].confidenceSummary), "danger");

const mismatch = normalizeMedicalMonitoringDailyAiCandidates({ candidateCount: 2, candidates: [candidate()] });
assert.equal(mismatch.status, "partial");
assert.ok(mismatch.issues.some((item) => item.field === "candidate_count"));

const duplicate = normalizeMedicalMonitoringDailyAiCandidates({
  candidateCount: 2,
  candidates: [candidate(), { ...candidate(), job_id: "job-2" }],
});
assert.equal(duplicate.status, "partial");
assert.ok(duplicate.issues.some((item) => item.message.includes("重复")));
assert.notEqual(
  medicalMonitoringAiCandidateDisplayKey(duplicate.value.candidates[0]),
  medicalMonitoringAiCandidateDisplayKey(duplicate.value.candidates[1]),
);

const incompleteEvidence = normalizeMedicalMonitoringDailyAiCandidates({
  candidateCount: 1,
  candidates: [candidate({
    evidence: [
      { source_entry_id: "listing-1", source_content_sha256: sha, locator: "", input_revision_sha256: sha },
      { source_entry_id: "listing-1", source_content_sha256: sha, locator: "", input_revision_sha256: sha },
    ],
  })],
});
assert.equal(incompleteEvidence.status, "partial");
assert.notEqual(
  medicalMonitoringAiCandidateEvidenceKey(incompleteEvidence.value.candidates[0].evidence[0]),
  medicalMonitoringAiCandidateEvidenceKey(incompleteEvidence.value.candidates[0].evidence[1]),
);

const ambiguousClaims = normalizeMedicalMonitoringDailyAiCandidates({
  candidateCount: 1,
  candidates: [candidate({
    claims: [
      { claim_id: "claim-duplicate", kind: "fact", text: "第一条声明", confidence: 0.8, evidence_ids: ["evidence-1"] },
      { claim_id: "claim-duplicate", kind: "inference", text: "第二条声明", confidence: 0.6, evidence_ids: ["evidence-1"] },
      { kind: "data_gap", text: "缺少声明身份", confidence: 0.2, evidence_ids: [] },
    ],
  })],
});
assert.equal(ambiguousClaims.status, "partial");
assert.equal(ambiguousClaims.value.candidates[0].claims[0].identityState, "duplicate");
assert.equal(ambiguousClaims.value.candidates[0].claims[1].identityState, "duplicate");
assert.equal(ambiguousClaims.value.candidates[0].claims[2].identityState, "missing");
assert.notEqual(
  medicalMonitoringAiCandidateClaimKey(ambiguousClaims.value.candidates[0].claims[0]),
  medicalMonitoringAiCandidateClaimKey(ambiguousClaims.value.candidates[0].claims[1]),
);
assert.ok(ambiguousClaims.issues.some((item) => item.field.includes("claims[0].claim_id") && item.message.includes("重复")));
assert.ok(ambiguousClaims.issues.some((item) => item.field.includes("claims[2].claim_id") && item.message.includes("缺失")));

const automation = normalizeMedicalMonitoringDailyAiCandidates({
  candidateCount: 1,
  candidates: [candidate({ confidence_summary: { ...candidate().candidate.confidence_summary, automation_permitted: true } })],
});
assert.equal(automation.status, "partial");
assert.ok(automation.issues.some((item) => item.field.includes("automation_permitted")));

for (const [status, expected] of [
  ["accepted", "医学已确认 · 当前监查中生效"],
  ["rejected", "已驳回 · 不作为当前结论"],
  ["superseded", "已替代 · 以新候选为准"],
]) {
  const result = normalizeMedicalMonitoringDailyAiCandidates({
    candidateCount: 1,
    candidates: [candidate({ status })],
  });
  assert.equal(result.status, "ready");
  assert.equal(
    medicalMonitoringAiCandidateReviewStateLabel(result.value.candidates[0]),
    expected,
  );
}

const needsEvidence = normalizeMedicalMonitoringDailyAiCandidates({
  candidateCount: 1,
  candidates: [candidate({
    confidence_summary: {
      ...candidate().candidate.confidence_summary,
      requires_additional_evidence: true,
    },
  })],
});
assert.equal(needsEvidence.status, "ready");
assert.equal(
  medicalMonitoringAiCandidateReviewStateLabel(needsEvidence.value.candidates[0]),
  "需补证据",
);
assert.equal(
  medicalMonitoringAiCandidateReviewStateLabel({ status: "unknown" }),
  "状态待核对",
);

assert.equal(medicalMonitoringAiCandidateStatusLabel("proposed"), "待医学确认");
assert.equal(medicalMonitoringAiCandidateStatusLabel("unknown"), "待核对");
assert.equal(medicalMonitoringAiClaimKindLabel("inference"), "推断声明");
assert.equal(medicalMonitoringAiClaimKindLabel("unknown"), "声明待核对");
assert.equal(medicalMonitoringAiCandidateConfidenceTone({ status: "review_required" }), "warning");

console.log("medicalMonitoringDailyAiCandidates: contract checks passed");
