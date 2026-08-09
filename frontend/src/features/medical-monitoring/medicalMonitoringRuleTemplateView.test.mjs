import assert from "node:assert/strict";

import {
  MedicalMonitoringRuleTemplateShapeError,
  normalizeRuleTemplateDecisionResponse,
  normalizeRuleTemplateRecommendationPayload,
} from "./medicalMonitoringRuleTemplateView.mjs";

const projectId = "project-1";
const factRevisionId = "fact-1";
const inputRevision = "a".repeat(64);
const candidate = {
  candidate_id: "candidate-1",
  status: "proposed",
  title: "肝功能异常与 AE 复核",
  summary: "发现临床意义实验室异常但无 AE 记录时形成复核项。",
  rationale: "方案要求持续评估肝功能异常。",
  tradeoffs: ["提高敏感性，可能增加医学复核量。"],
  required_domains: ["LB", "AE"],
  mapping_fields: [{ role: "lab_result", domain: "LB", field: "LBSTRESN" }],
  source: { text: "方案原文", locator: "protocol:section:8.2.3" },
};
const payload = {
  project_id: projectId,
  status: "candidate_review",
  fact: {
    fact_revision_id: factRevisionId,
    state_version: 2,
    fact_type: "safety_assessment",
    title: "肝功能异常复核",
    source_text: "方案原文",
    source_locator: "protocol:section:8.2.3",
  },
  mapping: {
    revision: "mapping-1",
    activation_disposition: "confirmed",
  },
  input_revision_sha256: inputRevision,
  failure: null,
  message: "",
  candidates: [candidate],
};

const normalized = normalizeRuleTemplateRecommendationPayload(
  payload,
  projectId,
  factRevisionId,
);
assert.equal(normalized.fact.fact_revision_id, factRevisionId);
assert.equal(normalized.candidates[0].mapping_fields[0].field, "LBSTRESN");
assert.equal(normalized.input_revision_sha256, inputRevision);

const ready = normalizeRuleTemplateRecommendationPayload({
  ...payload,
  status: "ready",
  candidates: [],
}, projectId, factRevisionId);
assert.equal(ready.candidates.length, 0);

const manual = normalizeRuleTemplateRecommendationPayload({
  ...payload,
  status: "manual_review",
  message: "当前能力不足。",
  candidates: [],
}, projectId, factRevisionId);
assert.equal(manual.message, "当前能力不足。");

const selectedResponse = normalizeRuleTemplateDecisionResponse({
  status: "rule_template_selected",
  candidate: { ...candidate, status: "accepted" },
  decision_reused: false,
  confirmed_fact: {
    project_id: projectId,
    ...payload.fact,
  },
  compiled_rule: {
    project_id: projectId,
    rule_revision_id: "rule-revision-1",
    rule_key: "LAB-AE-001",
    status: "confirmed",
  },
  next_action: {
    code: "create_rule_pack_draft",
    message: "尚未创建规则包。",
  },
}, projectId, candidate.candidate_id);
assert.equal(selectedResponse.status, "rule_template_selected");
assert.equal(selectedResponse.candidate.status, "accepted");
assert.equal(selectedResponse.compiled_rule.rule_key, "LAB-AE-001");

const rejectedResponse = normalizeRuleTemplateDecisionResponse({
  status: "user_rejected",
  candidate: { ...candidate, status: "rejected" },
  decision_reused: true,
  confirmed_fact: null,
  compiled_rule: null,
}, projectId, candidate.candidate_id);
assert.equal(rejectedResponse.confirmed_fact, null);
assert.equal(rejectedResponse.decision_reused, true);

assert.throws(
  () => normalizeRuleTemplateRecommendationPayload({ ...payload, project_id: "project-2" }, projectId, factRevisionId),
  MedicalMonitoringRuleTemplateShapeError,
);
assert.throws(
  () => normalizeRuleTemplateRecommendationPayload({ ...payload, candidates: "malformed" }, projectId, factRevisionId),
  MedicalMonitoringRuleTemplateShapeError,
);
assert.throws(
  () => normalizeRuleTemplateRecommendationPayload({
    ...payload,
    candidates: [{ ...candidate, mapping_fields: [{ domain: "LB" }] }],
  }, projectId, factRevisionId),
  MedicalMonitoringRuleTemplateShapeError,
);
assert.throws(
  () => normalizeRuleTemplateRecommendationPayload({
    ...payload,
    input_revision_sha256: "stale",
  }, projectId, factRevisionId),
  MedicalMonitoringRuleTemplateShapeError,
);
assert.throws(
  () => normalizeRuleTemplateRecommendationPayload({
    ...payload,
    candidates: [{ ...candidate, candidate_id: "" }],
  }, projectId, factRevisionId),
  MedicalMonitoringRuleTemplateShapeError,
);
assert.throws(
  () => normalizeRuleTemplateDecisionResponse({
    status: "rule_template_selected",
    candidate: { ...candidate, status: "accepted" },
    decision_reused: "false",
    confirmed_fact: null,
    compiled_rule: null,
  }, projectId, candidate.candidate_id),
  MedicalMonitoringRuleTemplateShapeError,
);
assert.throws(
  () => normalizeRuleTemplateDecisionResponse({
    status: "rule_template_selected",
    candidate: { ...candidate, status: "accepted" },
    decision_reused: false,
    confirmed_fact: null,
    compiled_rule: null,
    next_action: { code: "publish_rule_pack" },
  }, projectId, candidate.candidate_id),
  MedicalMonitoringRuleTemplateShapeError,
);
assert.throws(
  () => normalizeRuleTemplateDecisionResponse({
    status: "user_rejected",
    candidate: { ...candidate, status: "rejected" },
    decision_reused: false,
    confirmed_fact: null,
    compiled_rule: null,
  }, projectId, "other-candidate"),
  MedicalMonitoringRuleTemplateShapeError,
);

console.log("medicalMonitoringRuleTemplateView: 13 passed");

