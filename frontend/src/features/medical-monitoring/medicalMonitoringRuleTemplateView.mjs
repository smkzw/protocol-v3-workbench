const RECOMMENDATION_STATUSES = new Set([
  "ready",
  "queued",
  "running",
  "candidate_review",
  "reviewed",
  "manual_review",
  "failed",
  "blocked",
  "stale_input",
  "cancelled",
]);

const DECISION_RESPONSE_STATUSES = new Set([
  "rule_template_selected",
  "user_rejected",
]);

const CANDIDATE_STATUSES = new Set([
  "proposed",
  "accepted",
  "rejected",
  "superseded",
]);

export class MedicalMonitoringRuleTemplateShapeError extends Error {
  constructor(path, message) {
    super(`${path} ${message}`);
    this.name = "MedicalMonitoringRuleTemplateShapeError";
  }
}

function fail(path, message) {
  throw new MedicalMonitoringRuleTemplateShapeError(path, message);
}

function record(value, path) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(path, "必须是对象");
  }
  return value;
}

function array(value, path) {
  if (!Array.isArray(value)) fail(path, "必须是数组");
  return value;
}

function requiredText(value, path) {
  if (typeof value !== "string" || !value.trim()) fail(path, "必须是非空字符串");
  return value.trim();
}

function text(value, path) {
  if (typeof value !== "string") fail(path, "必须是字符串");
  return value.trim();
}

function optionalText(value, path) {
  if (value === undefined || value === null) return "";
  return text(value, path);
}

function positiveInteger(value, path) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    fail(path, "必须是正整数");
  }
  return value;
}

function booleanValue(value, path) {
  if (typeof value !== "boolean") fail(path, "必须是布尔值");
  return value;
}

function stringArray(value, path) {
  return array(value, path).map((item, index) => (
    requiredText(item, `${path}[${index}]`)
  ));
}

function projectId(value, expectedProjectId, path) {
  const actual = requiredText(value, path);
  const expected = requiredText(expectedProjectId, "expected_project_id");
  if (actual !== expected) fail(path, `与当前项目不一致（应为 ${expected}）`);
  return actual;
}

function sha256(value, path) {
  const normalized = requiredText(value, path).toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(normalized)) fail(path, "必须是 64 位十六进制摘要");
  return normalized;
}

function normalizeSource(raw, path) {
  const source = record(raw, path);
  return {
    ...source,
    text: text(source.text, `${path}.text`),
    locator: requiredText(source.locator, `${path}.locator`),
  };
}

function normalizeMappingField(raw, path) {
  const field = record(raw, path);
  return {
    ...field,
    role: optionalText(field.role, `${path}.role`),
    domain: requiredText(field.domain, `${path}.domain`),
    field: requiredText(field.field, `${path}.field`),
  };
}

function normalizeCandidate(raw, path) {
  const candidate = record(raw, path);
  const candidateId = requiredText(candidate.candidate_id, `${path}.candidate_id`);
  const status = requiredText(candidate.status, `${path}.status`);
  if (!CANDIDATE_STATUSES.has(status)) fail(`${path}.status`, `包含不支持的值 ${status}`);
  return {
    ...candidate,
    candidate_id: candidateId,
    status,
    title: requiredText(candidate.title, `${path}.title`),
    summary: text(candidate.summary, `${path}.summary`),
    rationale: text(candidate.rationale, `${path}.rationale`),
    tradeoffs: stringArray(candidate.tradeoffs, `${path}.tradeoffs`),
    required_domains: stringArray(candidate.required_domains, `${path}.required_domains`),
    mapping_fields: array(candidate.mapping_fields, `${path}.mapping_fields`)
      .map((item, index) => normalizeMappingField(item, `${path}.mapping_fields[${index}]`)),
    source: normalizeSource(candidate.source, `${path}.source`),
  };
}

function normalizeFact(raw, expectedProjectId, expectedFactRevisionId, path) {
  const fact = record(raw, path);
  if (fact.project_id !== undefined) {
    projectId(fact.project_id, expectedProjectId, `${path}.project_id`);
  }
  const factRevisionId = requiredText(fact.fact_revision_id, `${path}.fact_revision_id`);
  if (expectedFactRevisionId !== undefined && factRevisionId !== expectedFactRevisionId) {
    fail(`${path}.fact_revision_id`, "与当前方案事实不一致");
  }
  return {
    ...fact,
    project_id: expectedProjectId,
    fact_revision_id: factRevisionId,
    state_version: positiveInteger(fact.state_version, `${path}.state_version`),
    fact_type: requiredText(fact.fact_type, `${path}.fact_type`),
    title: requiredText(fact.title, `${path}.title`),
    source_text: text(fact.source_text, `${path}.source_text`),
    source_locator: requiredText(fact.source_locator, `${path}.source_locator`),
  };
}

function normalizeCompiledRule(raw, expectedProjectId, path) {
  if (raw === null || raw === undefined) return null;
  const rule = record(raw, path);
  if (rule.project_id !== undefined) {
    projectId(rule.project_id, expectedProjectId, `${path}.project_id`);
  }
  return {
    ...rule,
    rule_revision_id: optionalText(rule.rule_revision_id, `${path}.rule_revision_id`),
    rule_key: requiredText(rule.rule_key, `${path}.rule_key`),
    status: optionalText(rule.status, `${path}.status`),
  };
}

function normalizeDecisionCandidate(raw, path) {
  if (raw === null || raw === undefined) return null;
  return normalizeCandidate(raw, path);
}

export function normalizeRuleTemplateRecommendationPayload(
  raw,
  expectedProjectId,
  expectedFactRevisionId,
  path = "rule_template_recommendation",
) {
  const payload = record(raw, path);
  const project = projectId(payload.project_id, expectedProjectId, `${path}.project_id`);
  const status = requiredText(payload.status, `${path}.status`);
  if (!RECOMMENDATION_STATUSES.has(status)) fail(`${path}.status`, `包含不支持的值 ${status}`);
  const fact = normalizeFact(payload.fact, project, expectedFactRevisionId, `${path}.fact`);
  const mapping = record(payload.mapping, `${path}.mapping`);
  const candidates = array(payload.candidates, `${path}.candidates`)
    .map((item, index) => normalizeCandidate(item, `${path}.candidates[${index}]`));
  const candidateIds = new Set(candidates.map((candidate) => candidate.candidate_id));
  if (candidateIds.size !== candidates.length) fail(`${path}.candidates`, "候选身份重复");
  let failure = null;
  if (payload.failure !== null && payload.failure !== undefined) {
    const rawFailure = record(payload.failure, `${path}.failure`);
    failure = {
      ...rawFailure,
      code: requiredText(rawFailure.code, `${path}.failure.code`),
      message: requiredText(rawFailure.message, `${path}.failure.message`),
    };
  }
  return {
    ...payload,
    project_id: project,
    status,
    fact,
    mapping: {
      ...mapping,
      revision: requiredText(mapping.revision, `${path}.mapping.revision`),
      activation_disposition: requiredText(
        mapping.activation_disposition,
        `${path}.mapping.activation_disposition`,
      ),
    },
    input_revision_sha256: sha256(
      payload.input_revision_sha256,
      `${path}.input_revision_sha256`,
    ),
    failure,
    message: optionalText(payload.message, `${path}.message`),
    candidates,
  };
}

export function normalizeRuleTemplateDecisionResponse(
  raw,
  expectedProjectId,
  expectedCandidateId,
  path = "rule_template_decision",
) {
  const response = record(raw, path);
  const status = requiredText(response.status, `${path}.status`);
  if (!DECISION_RESPONSE_STATUSES.has(status)) {
    fail(`${path}.status`, `包含不支持的值 ${status}`);
  }
  const candidate = normalizeDecisionCandidate(response.candidate, `${path}.candidate`);
  if (!candidate) fail(`${path}.candidate`, "不能为空");
  if (expectedCandidateId !== undefined && candidate.candidate_id !== expectedCandidateId) {
    fail(`${path}.candidate.candidate_id`, "与当前候选不一致");
  }
  const confirmedFact = response.confirmed_fact === null || response.confirmed_fact === undefined
    ? null
    : normalizeFact(response.confirmed_fact, expectedProjectId, undefined, `${path}.confirmed_fact`);
  const compiledRule = normalizeCompiledRule(
    response.compiled_rule,
    expectedProjectId,
    `${path}.compiled_rule`,
  );
  const nextAction = response.next_action === null || response.next_action === undefined
    ? null
    : record(response.next_action, `${path}.next_action`);
  if (nextAction && requiredText(nextAction.code, `${path}.next_action.code`) !== "create_rule_pack_draft") {
    fail(`${path}.next_action.code`, "包含不支持的下一步");
  }
  return {
    ...response,
    status,
    candidate,
    decision_reused: booleanValue(response.decision_reused, `${path}.decision_reused`),
    confirmed_fact: confirmedFact,
    compiled_rule: compiledRule,
    next_action: nextAction,
  };
}
