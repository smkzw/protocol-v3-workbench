import assert from "node:assert/strict";

import {
  acceptedProtocolCandidateFact,
  acceptedProtocolFacts,
  applyProtocolCandidateDecision,
  newlyAcceptedProtocolDecisionFact,
} from "./medicalMonitoringProtocolPreparation.mjs";
import {
  applyRuleTemplateRecommendationDecision,
  buildRuleTemplateRecommendationDecisionPayload,
  buildRuleTemplateRecommendationStartPayload,
  ruleTemplateCandidateDetails,
  ruleTemplateCandidateConfidenceSummary,
  ruleTemplateRecommendationViewModel,
  shouldPollRuleTemplateRecommendation,
} from "./medicalMonitoringRuleTemplateRecommendation.mjs";

const revision = "a".repeat(64);
const fact = {
  fact_revision_id: "fact-1",
  state_version: 2,
  fact_type: "safety_assessment",
  title: "肝功能异常复核",
};
const ruleCandidate = {
  candidate_id: "rule-candidate-1",
  status: "proposed",
  title: "肝功能异常与AE复核",
  summary: "发现临床意义实验室异常但无AE记录时形成复核项。",
  rationale: "方案要求持续评估肝功能异常。",
  tradeoffs: [
    "提高敏感性，可能增加医学复核量。",
    "需同时具备LB与AE字段。",
  ],
  required_domains: ["LB", "AE"],
  mapping_fields: [
    { role: "lab_result", domain: "LB", field: "LBSTRESN" },
    { role: "ae_verbatim_term", domain: "AE", field: "AETERM" },
  ],
  source: {
    text: "如肝功能检查异常具有临床意义，应记录为不良事件并随访。",
    locator: "protocol:section:8.2.3",
  },
  confidence_summary: {
    status: "review_required",
    label: "达到工作台阈值，仍需医学确认",
    confidence_floor: 0.86,
    threshold: 0.70,
    claim_count: 1,
    requires_user_review: true,
    requires_additional_evidence: false,
    automation_permitted: false,
    next_step: "medical_manager_confirmation",
  },
};

assert.equal(
  acceptedProtocolCandidateFact({
    status: "accepted",
    fact,
  })?.fact_revision_id,
  "fact-1",
  "restores the accepted fact revision from candidate.fact",
);
assert.equal(
  acceptedProtocolCandidateFact({
    status: "accepted",
    fact,
  })?.state_version,
  2,
  "restores the accepted fact state version from candidate.fact",
);
assert.equal(
  acceptedProtocolCandidateFact({ status: "proposed", fact }),
  null,
  "does not expose an unaccepted candidate as a fact draft",
);
assert.deepEqual(
  acceptedProtocolFacts({
    topics: [
      {
        topic_id: "safety",
        candidates: [
          { candidate_id: "c1", status: "accepted", fact },
          { candidate_id: "c2", status: "accepted", fact },
        ],
      },
    ],
  }).map((item) => item.fact.fact_revision_id),
  ["fact-1"],
  "deduplicates restored facts across topic candidates",
);

const acceptedStatus = applyProtocolCandidateDecision(
  {
    topics: [{
      topic_id: "safety",
      status: "candidate_review",
      candidates: [{ candidate_id: "c1", status: "proposed" }],
    }],
  },
  "c1",
  {
    candidate: { candidate_id: "c1", status: "accepted" },
    outcome: { fact },
  },
);
assert.deepEqual(
  acceptedStatus.topics[0].candidates[0].fact,
  fact,
  "attaches the immediate acceptance outcome fact before status refresh",
);
assert.deepEqual(
  newlyAcceptedProtocolDecisionFact({
    decision: "accepted",
    outcome: { fact },
    candidate: { status: "accepted" },
  }),
  fact,
  "new acceptance resolves the outcome fact for one automatic start",
);
assert.deepEqual(
  newlyAcceptedProtocolDecisionFact({
    decision: "accepted",
    outcome: { fact: null },
    candidate: { status: "accepted", fact },
  }),
  fact,
  "new acceptance falls back to candidate.fact when supplied by the API",
);
assert.equal(
  newlyAcceptedProtocolDecisionFact({
    decision: "rejected",
    candidate: { status: "rejected", fact },
  }),
  null,
  "a rejected decision never starts rule recommendation generation",
);
assert.equal(
  newlyAcceptedProtocolDecisionFact({
    topics: [{ candidates: [{ status: "accepted", fact }] }],
  }),
  null,
  "refresh restoration is read-only and never creates an automatic start intent",
);

assert.deepEqual(
  buildRuleTemplateRecommendationStartPayload(fact),
  { expected_fact_state_version: 2 },
  "starts generation against the exact accepted fact version",
);
assert.deepEqual(
  buildRuleTemplateRecommendationDecisionPayload({
    decision: "accepted",
    statusPayload: {
      input_revision_sha256: revision,
      fact,
    },
    candidate: ruleCandidate,
    fact,
  }),
  {
    candidateId: "rule-candidate-1",
    payload: {
      decision: "accepted",
      expected_input_revision_sha256: revision,
      expected_fact_state_version: 2,
      reason: "",
    },
  },
  "uses both input revision and fact state CAS for adoption",
);
assert.throws(
  () => buildRuleTemplateRecommendationDecisionPayload({
    decision: "accepted",
    statusPayload: { input_revision_sha256: "stale", fact },
    candidate: ruleCandidate,
    fact,
  }),
  /输入版本不可用/,
  "fails closed when the input revision cannot support CAS",
);
assert.throws(
  () => buildRuleTemplateRecommendationDecisionPayload({
    decision: "accepted",
    statusPayload: { input_revision_sha256: revision, fact },
    candidate: { ...ruleCandidate, status: "accepted" },
    fact,
  }),
  /当前不可选择/,
  "does not submit a second decision for a non-proposed candidate",
);

assert.equal(shouldPollRuleTemplateRecommendation({ status: "queued" }), true);
assert.equal(shouldPollRuleTemplateRecommendation({ status: "running" }), true);
assert.equal(
  shouldPollRuleTemplateRecommendation({ status: "candidate_review" }),
  false,
  "polling stops when user review is required",
);

assert.equal(
  ruleTemplateRecommendationViewModel({
    payload: { status: "ready", fact },
  }).canStart,
  true,
  "ready state exposes the single generation action",
);
assert.equal(
  ruleTemplateRecommendationViewModel({
    payload: { status: "running", fact },
  }).mode,
  "progress",
  "running state remains a compact progress view",
);
assert.deepEqual(
  ruleTemplateRecommendationViewModel({
    payload: {
      status: "manual_review",
      message: "该事实没有安全的确定性规则族。",
      fact,
    },
  }),
  {
    mode: "manual_review",
    status: "manual_review",
    label: "需人工处理",
    message: "该事实没有安全的确定性规则族。",
    candidates: [],
    canStart: false,
    shouldPoll: false,
    compiled: false,
  },
  "manual review exposes only the user-facing explanation",
);

const fourCandidates = [1, 2, 3, 4].map((index) => ({
  ...ruleCandidate,
  candidate_id: `rule-candidate-${index}`,
  title: `建议 ${index}`,
}));
const candidateReview = ruleTemplateRecommendationViewModel({
  payload: {
    status: "candidate_review",
    input_revision_sha256: revision,
    fact,
    candidates: fourCandidates,
  },
});
assert.equal(candidateReview.mode, "candidate_review");
assert.equal(candidateReview.candidates.length, 3, "renders at most three safe candidates");
assert.deepEqual(
  ruleTemplateCandidateDetails(ruleCandidate),
  {
    candidateId: "rule-candidate-1",
    status: "proposed",
    title: "肝功能异常与AE复核",
    summary: "发现临床意义实验室异常但无AE记录时形成复核项。",
    rationale: "方案要求持续评估肝功能异常。",
    tradeoffs: [
      "提高敏感性，可能增加医学复核量。",
      "需同时具备LB与AE字段。",
    ],
    requiredDomains: ["LB", "AE"],
    mappingFields: [
      { role: "lab_result", domain: "LB", field: "LBSTRESN" },
      { role: "ae_verbatim_term", domain: "AE", field: "AETERM" },
    ],
    sourceText: "如肝功能检查异常具有临床意义，应记录为不良事件并随访。",
    sourceLocator: "protocol:section:8.2.3",
    confidenceSummary: {
      status: "review_required",
      label: "达到工作台阈值，仍需医学确认",
      confidence_floor: 0.86,
      threshold: 0.70,
      claim_count: 1,
      requires_user_review: true,
      requires_additional_evidence: false,
      automation_permitted: false,
      next_step: "medical_manager_confirmation",
    },
  },
  "keeps source content primary and locator secondary",
);
assert.equal(
  ruleTemplateCandidateConfidenceSummary({}).requires_additional_evidence,
  true,
  "missing confidence evidence fails closed to a required user explanation",
);
assert.equal(
  ruleTemplateCandidateConfidenceSummary({
    confidence_summary: { confidence_floor: 0.42, threshold: 0.70 },
  }).status,
  "low",
  "below-threshold recommendations remain visibly low confidence",
);

const compiled = applyRuleTemplateRecommendationDecision(
  {
    status: "candidate_review",
    input_revision_sha256: revision,
    fact,
    candidates: [ruleCandidate],
  },
  "rule-candidate-1",
  {
    status: "rule_template_selected",
    candidate_id: "rule-candidate-1",
    confirmed_fact: { ...fact, state_version: 3 },
    compiled_rule: { rule_key: "LAB-AE-001" },
    next_action: { code: "create_rule_pack_draft" },
  },
);
assert.equal(compiled.status, "reviewed");
assert.equal(compiled.candidates[0].status, "accepted");
assert.equal(
  ruleTemplateRecommendationViewModel({ payload: compiled }).mode,
  "compiled",
  "successful selection immediately reports deterministic compilation",
);
assert.equal(
  JSON.stringify(compiled).includes("provider"),
  false,
  "component state does not manufacture runtime implementation logs",
);

console.log("medicalMonitoringRuleTemplateRecommendation: 24 passed");
