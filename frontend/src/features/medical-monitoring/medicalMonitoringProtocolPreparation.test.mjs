import assert from "node:assert/strict";

import {
  applyProtocolCandidateDecision,
  buildProtocolCandidateDecisionPayload,
  candidateConfidenceSummary,
  candidateReferencedEvidence,
  candidateStructuredSections,
  confirmedProtocolVersions,
  normalizeProtocolPreparationStatus,
  protocolCandidateDecisionLabel,
  protocolFactTypeOptions,
  protocolPreparationCandidateDisplayKey,
  protocolPreparationCandidateIdentityReady,
  protocolPreparationEvidenceDisplayKey,
  protocolPreparationProgress,
  protocolPreparationStartAction,
  protocolPreparationTopicDisplayKey,
  protocolPreparationTopicTone,
  protocolPreparationVersionDisplayKey,
  resolveProtocolCandidateInputRevision,
  shouldPollProtocolPreparation,
} from "./medicalMonitoringProtocolPreparation.mjs";

const versions = confirmedProtocolVersions({
  items: [
    {
      protocol_version_id: "old",
      version_label: "V1.0",
      version_date: "2025-01-01",
      status: "confirmed",
    },
    {
      protocol_version_id: "draft",
      version_label: "V3.0",
      version_date: "2026-03-01",
      status: "draft",
    },
    {
      protocol_version_id: "new",
      version_label: "V2.0",
      version_date: "2026-01-01",
      status: "confirmed",
    },
  ],
});
assert.deepEqual(
  versions.map((item) => item.protocol_version_id),
  ["new", "old"],
  "only confirmed versions are offered, newest first",
);
assert.equal(versions[0].displayIdentityState, "ready");
const ambiguousVersions = confirmedProtocolVersions({
  items: [
    { protocol_version_id: "same", version_label: "V2", version_date: "2026-02-01", status: "confirmed" },
    { protocol_version_id: "same", version_label: "V1", version_date: "2026-01-01", status: "confirmed" },
    { version_label: "未标识版本", version_date: "2025-01-01", status: "confirmed" },
  ],
});
assert.equal(ambiguousVersions[0].displayIdentityState, "duplicate");
assert.equal(ambiguousVersions[1].displayIdentityState, "duplicate");
assert.equal(ambiguousVersions[2].displayIdentityState, "missing");
assert.equal(new Set(ambiguousVersions.map((version) => version.displayKey)).size, 3);
assert.equal(protocolPreparationVersionDisplayKey(ambiguousVersions[2], 2), "protocol-version:missing:2");

const status = {
  topics: [
    {
      status: "candidate_review",
      execution_status: "submitted",
      candidates: [{ status: "proposed" }, { status: "proposed" }],
    },
    {
      status: "reviewed",
      execution_status: "submitted",
      candidates: [{ status: "accepted" }],
    },
    { status: "data_gap", execution_status: "skipped", candidates: [] },
    { status: "running", execution_status: "submitted", candidates: [] },
    { status: "queued", execution_status: "submitted", candidates: [] },
    { status: "ready", execution_status: "not_submitted", candidates: [] },
  ],
};
assert.equal(shouldPollProtocolPreparation(status), true);
assert.deepEqual(protocolPreparationProgress(status), {
  total: 6,
  completed: 3,
  candidateCount: 2,
  submitted: true,
  percent: 50,
});
assert.equal(
  shouldPollProtocolPreparation({
    topics: [{ status: "candidate_review" }, { status: "data_gap" }],
  }),
  false,
  "candidate review is terminal for polling",
);
assert.equal(normalizeProtocolPreparationStatus({ topics: [] }).ok, true);
assert.equal(
  normalizeProtocolPreparationStatus({ topics: [{ candidates: [{ candidate_id: "c1" }] }] }).value.topics[0].candidates.length,
  1,
);
const identityStatus = normalizeProtocolPreparationStatus({
  topics: [{
    topic_id: "topic-1",
    candidates: [
      { candidate_id: "candidate-1" },
      { candidate_id: "candidate-1" },
      {},
    ],
  }],
});
const identityTopic = identityStatus.value.topics[0];
assert.equal(protocolPreparationTopicDisplayKey(identityTopic), "protocol-topic:topic-1:0");
assert.equal(protocolPreparationCandidateIdentityReady(identityTopic.candidates[0]), true);
assert.equal(protocolPreparationCandidateIdentityReady(identityTopic.candidates[1]), false);
assert.equal(protocolPreparationCandidateIdentityReady(identityTopic.candidates[2]), false);
assert.notEqual(
  protocolPreparationCandidateDisplayKey(identityTopic.candidates[1]),
  protocolPreparationCandidateDisplayKey(identityTopic.candidates[2]),
);
assert.equal(
  protocolPreparationEvidenceDisplayKey({ quote: "同一原文" }, 1),
  "protocol-evidence:missing:同一原文:1",
);
assert.equal(normalizeProtocolPreparationStatus("malformed").ok, false);
assert.equal(normalizeProtocolPreparationStatus({ topics: ["malformed"] }).ok, false);
assert.equal(normalizeProtocolPreparationStatus({ topics: [{ candidates: ["malformed"] }] }).ok, false);
assert.equal(normalizeProtocolPreparationStatus({ topics: [{ allowed_fact_types: "not-an-array" }] }).ok, false);
assert.deepEqual(confirmedProtocolVersions({ items: "malformed" }), []);
assert.equal(shouldPollProtocolPreparation({ topics: "malformed" }), false);
assert.deepEqual(protocolPreparationProgress({ topics: "malformed" }), {
  total: 0,
  completed: 0,
  candidateCount: 0,
  submitted: false,
  percent: 0,
});
assert.deepEqual(
  candidateReferencedEvidence({
    structured_payload: { evidence_ids: "malformed" },
    claims: "malformed",
    evidence: "malformed",
  }),
  [],
);
assert.deepEqual(protocolFactTypeOptions({ allowed_fact_types: "malformed" }), []);
assert.equal(
  candidateConfidenceSummary({
    claims: [{ confidence: 0.69 }, { confidence: 0.95 }],
  }).requires_additional_evidence,
  true,
  "below-threshold claims require a visible explanation",
);
assert.equal(
  candidateConfidenceSummary({
    claims: [{ confidence: 0.81 }, { confidence: 0.95 }],
  }).automation_permitted,
  false,
  "even threshold-passing candidates remain user-confirmation gated",
);
assert.equal(
  candidateConfidenceSummary({ claims: [{ confidence: "malformed" }] }).status,
  "low",
  "malformed confidence fails closed",
);

assert.deepEqual(
  candidateStructuredSections({
    structured_payload: {
      subject_scope: "所有随机受试者",
      conditions: ["漏服达到方案阈值", ""],
      time_windows: ["每次访视前"],
      thresholds: [],
      exceptions: ["研究者确认的紧急处理"],
      required_actions: ["记录方案偏离并复核"],
      evidence_ids: ["not-visible-as-a-field"],
    },
  }),
  [
    { key: "subject_scope", label: "适用对象", values: ["所有随机受试者"] },
    { key: "conditions", label: "条件", values: ["漏服达到方案阈值"] },
    { key: "time_windows", label: "时间窗", values: ["每次访视前"] },
    { key: "exceptions", label: "例外", values: ["研究者确认的紧急处理"] },
    { key: "required_actions", label: "动作", values: ["记录方案偏离并复核"] },
  ],
);
assert.deepEqual(
  candidateReferencedEvidence({
    structured_payload: { evidence_ids: ["ev-clause"] },
    claims: [
      { evidence_ids: ["ev-gap"] },
      { evidence_ids: ["ev-clause"] },
    ],
    evidence: [
      { evidence_id: "ev-unrelated", quote: "无关方案片段" },
      { evidence_id: "ev-clause", quote: "当前条款原文" },
      { evidence_id: "ev-gap", quote: "当前数据缺口依据" },
    ],
  }).map((item) => item.evidence_id),
  ["ev-clause", "ev-gap"],
);
assert.deepEqual(
  candidateReferencedEvidence({
    structured_payload: {},
    claims: [],
    evidence: [{ evidence_id: "ev-unbound", quote: "未被候选引用" }],
  }),
  [],
);
assert.equal(protocolPreparationTopicTone("candidate_review"), "warning");
assert.equal(protocolPreparationTopicTone("running"), "info");
assert.equal(protocolPreparationTopicTone("failed"), "danger");
assert.equal(protocolPreparationTopicTone("data_gap"), "muted");
assert.deepEqual(
  protocolPreparationStartAction({
    topics: [{ status: "stale_input" }, { status: "reviewed" }],
  }),
  {
    available: true,
    retry: true,
    label: "重新生成未完成主题",
  },
);
assert.deepEqual(
  protocolPreparationStartAction({
    topics: [{ status: "ready" }],
  }),
  {
    available: true,
    retry: false,
    label: "一键准备全部主题",
  },
);

const inputRevision = "a".repeat(64);
const decisionTopic = {
  topic_id: "study_treatment",
  source_revision: "mpr-current",
  allowed_fact_types: [
    "study_treatment_regimen",
    "study_treatment_change",
  ],
  job: { job_id: "job-1" },
};
const proposedCandidate = {
  candidate_id: "candidate-1",
  status: "proposed",
};
const jobPayload = {
  job: {
    job_id: "job-1",
    input_revision_sha256: inputRevision,
  },
  candidates: [
    {
      candidate_id: "candidate-1",
      input_revision_sha256: inputRevision,
    },
  ],
};

assert.deepEqual(protocolFactTypeOptions(decisionTopic), [
  { value: "study_treatment_regimen", label: "试验药物给药方案" },
  { value: "study_treatment_change", label: "试验药物变更" },
]);
assert.equal(
  resolveProtocolCandidateInputRevision(
    decisionTopic,
    proposedCandidate,
    jobPayload,
  ),
  inputRevision,
);
assert.deepEqual(
  buildProtocolCandidateDecisionPayload({
    decision: "accepted",
    topic: decisionTopic,
    candidate: proposedCandidate,
    jobPayload,
    factType: "study_treatment_change",
  }),
  {
    decision: "accepted",
    reason: "",
    expected_input_revision_sha256: inputRevision,
    expected_source_revision: "mpr-current",
    proposed_fact_type: "study_treatment_change",
  },
);
assert.deepEqual(
  buildProtocolCandidateDecisionPayload({
    decision: "rejected",
    topic: decisionTopic,
    candidate: proposedCandidate,
    jobPayload,
    reason: "不适用于当前方案。",
    factType: "study_treatment_change",
  }),
  {
    decision: "rejected",
    reason: "不适用于当前方案。",
    expected_input_revision_sha256: inputRevision,
    expected_source_revision: "mpr-current",
  },
  "rejection never sends fact draft fields",
);
assert.throws(
  () => buildProtocolCandidateDecisionPayload({
    decision: "accepted",
    topic: decisionTopic,
    candidate: proposedCandidate,
    jobPayload,
  }),
  /请选择候选对应的条款类型/,
);
assert.equal(
  protocolCandidateDecisionLabel({ status: "accepted" }),
  "已确认事实草稿",
);
assert.equal(
  protocolCandidateDecisionLabel({ status: "rejected" }),
  "已驳回",
);
assert.deepEqual(
  applyProtocolCandidateDecision(
    {
      topics: [
        {
          topic_id: "study_treatment",
          status: "candidate_review",
          candidates: [proposedCandidate],
        },
      ],
    },
    "candidate-1",
    {
      candidate: {
        candidate_id: "candidate-1",
        status: "accepted",
        review_status: "user_confirmed",
      },
    },
  ),
  {
    topics: [
      {
        topic_id: "study_treatment",
        status: "reviewed",
        candidates: [
          {
            candidate_id: "candidate-1",
            status: "accepted",
            review_status: "user_confirmed",
          },
        ],
      },
    ],
  },
);

console.log("medicalMonitoringProtocolPreparation: 32 passed");
