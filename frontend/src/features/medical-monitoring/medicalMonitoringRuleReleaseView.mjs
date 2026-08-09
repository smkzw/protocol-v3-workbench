import {
  RULE_PACK_STATUS_LABELS,
  RULE_STATUS_LABELS,
  SHADOW_SAMPLE_BUCKET_LABELS,
} from "./medicalMonitoringRuleRelease.mjs";

const RULE_PACK_STATUSES = new Set(Object.keys(RULE_PACK_STATUS_LABELS));
const RULE_STATUSES = new Set(Object.keys(RULE_STATUS_LABELS));
const SAMPLE_BUCKETS = new Set(Object.keys(SHADOW_SAMPLE_BUCKET_LABELS));
const SAMPLE_EVALUATION_STATES = new Set(["true", "false", "indeterminate"]);
const SHADOW_RUN_STATUSES = new Set(["completed"]);

export class MedicalMonitoringRuleReleaseShapeError extends Error {
  constructor(path, message) {
    super(`${path} ${message}`);
    this.name = "MedicalMonitoringRuleReleaseShapeError";
  }
}

function fail(path, message) {
  throw new MedicalMonitoringRuleReleaseShapeError(path, message);
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
  if (typeof value !== "string" || !value.trim()) {
    fail(path, "必须是非空字符串");
  }
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

function nonNegativeInteger(value, path) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    fail(path, "必须是非负整数");
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
  if (expectedProjectId !== undefined && expectedProjectId !== null) {
    const expected = requiredText(expectedProjectId, "expected_project_id");
    if (actual !== expected) fail(path, `与当前项目不一致（应为 ${expected}）`);
  }
  return actual;
}

function enumValue(value, values, path) {
  const normalized = requiredText(value, path);
  if (!values.has(normalized)) fail(path, `包含不支持的值 ${normalized}`);
  return normalized;
}

function normalizeRulePackRecord(raw, expectedProjectId, path = "pack") {
  const pack = record(raw, path);
  const project = projectId(pack.project_id, expectedProjectId, `${path}.project_id`);
  const rulePackId = requiredText(pack.rule_pack_id, `${path}.rule_pack_id`);
  const protocolVersionId = requiredText(
    pack.protocol_version_id,
    `${path}.protocol_version_id`,
  );
  const status = enumValue(pack.status, RULE_PACK_STATUSES, `${path}.status`);
  const ruleRevisionIds = stringArray(pack.rule_revision_ids, `${path}.rule_revision_ids`);
  return {
    ...pack,
    project_id: project,
    rule_pack_id: rulePackId,
    protocol_version_id: protocolVersionId,
    pack_revision: positiveInteger(pack.pack_revision, `${path}.pack_revision`),
    status,
    applicability_status: requiredText(
      pack.applicability_status,
      `${path}.applicability_status`,
    ),
    rule_revision_ids: ruleRevisionIds,
    created_by: requiredText(pack.created_by, `${path}.created_by`),
    retrospective_policy: requiredText(
      pack.retrospective_policy,
      `${path}.retrospective_policy`,
    ),
    published_at: text(pack.published_at, `${path}.published_at`),
  };
}

function normalizeRuleRecord(raw, expectedProjectId, expectedProtocolVersionId, path) {
  const rule = record(raw, path);
  const project = projectId(rule.project_id, expectedProjectId, `${path}.project_id`);
  const protocolVersionId = requiredText(
    rule.protocol_version_id,
    `${path}.protocol_version_id`,
  );
  if (protocolVersionId !== expectedProtocolVersionId) {
    fail(`${path}.protocol_version_id`, "与规则包方案版本不一致");
  }
  return {
    ...rule,
    project_id: project,
    protocol_version_id: protocolVersionId,
    rule_revision_id: requiredText(rule.rule_revision_id, `${path}.rule_revision_id`),
    rule_key: requiredText(rule.rule_key, `${path}.rule_key`),
    status: enumValue(rule.status, RULE_STATUSES, `${path}.status`),
    title: requiredText(rule.title, `${path}.title`),
    required_domains: stringArray(rule.required_domains, `${path}.required_domains`),
    source_locator: text(rule.source_locator, `${path}.source_locator`),
    state_version: positiveInteger(rule.state_version, `${path}.state_version`),
  };
}

function normalizeSample(raw, expectedProjectId, path) {
  const sample = record(raw, path);
  const project = sample.project_id === undefined
    ? requiredText(expectedProjectId, "expected_project_id")
    : projectId(sample.project_id, expectedProjectId, `${path}.project_id`);
  const state = enumValue(
    sample.actual_evaluation_state,
    SAMPLE_EVALUATION_STATES,
    `${path}.actual_evaluation_state`,
  );
  const bucket = enumValue(sample.bucket, SAMPLE_BUCKETS, `${path}.bucket`);
  return {
    ...sample,
    project_id: project,
    sample_id: requiredText(sample.sample_id, `${path}.sample_id`),
    rule_key: requiredText(sample.rule_key, `${path}.rule_key`),
    rule_revision_id: optionalText(sample.rule_revision_id, `${path}.rule_revision_id`),
    bucket,
    case_label: requiredText(sample.case_label, `${path}.case_label`),
    business_key: requiredText(sample.business_key, `${path}.business_key`),
    actual_matched: booleanValue(sample.actual_matched, `${path}.actual_matched`),
    actual_evaluation_state: state,
    actual_diagnostic_code: text(
      sample.actual_diagnostic_code,
      `${path}.actual_diagnostic_code`,
    ),
    evidence_summary: requiredText(sample.evidence_summary, `${path}.evidence_summary`),
  };
}

function normalizeShadowInspectionRecord(raw, expectedProjectId, path = "inspection") {
  const inspection = record(raw, path);
  const project = inspection.project_id === undefined
    ? requiredText(expectedProjectId, "expected_project_id")
    : projectId(inspection.project_id, expectedProjectId, `${path}.project_id`);
  const normalizedSamples = array(inspection.samples, `${path}.samples`)
    .map((item, index) => normalizeSample(item, project, `${path}.samples[${index}]`));
  const sampleIdCounts = new Map();
  normalizedSamples.forEach((sample) => {
    sampleIdCounts.set(sample.sample_id, (sampleIdCounts.get(sample.sample_id) || 0) + 1);
  });
  const samples = normalizedSamples.map((sample, index) => {
    const displayIdentityState = sampleIdCounts.get(sample.sample_id) > 1 ? "duplicate" : "ready";
    return {
      ...sample,
      displaySourceIndex: index,
      displayIdentityState,
      displayIdentityIssue: displayIdentityState === "duplicate"
        ? "影子样本 sample_id 重复；保留样本但暂需回源核对。"
        : null,
    };
  });
  const sampleCount = nonNegativeInteger(inspection.sample_count, `${path}.sample_count`);
  if (sampleCount !== samples.length) fail(`${path}.sample_count`, "与 samples 数量不一致");
  return {
    ...inspection,
    project_id: project,
    sample_set_id: requiredText(inspection.sample_set_id, `${path}.sample_set_id`),
    status: enumValue(inspection.status, new Set(["provisional"]), `${path}.status`),
    rule_pack_id: requiredText(inspection.rule_pack_id, `${path}.rule_pack_id`),
    batch_id: requiredText(inspection.batch_id, `${path}.batch_id`),
    batch_version: positiveInteger(inspection.batch_version, `${path}.batch_version`),
    batch_revision: requiredText(inspection.batch_revision, `${path}.batch_revision`),
    mapping_revision: requiredText(inspection.mapping_revision, `${path}.mapping_revision`),
    sample_count: sampleCount,
    samples,
  };
}

export function ruleReleaseSampleDisplayKey(sample, index = 0) {
  const identity = typeof sample?.sample_id === "string" && sample.sample_id.trim()
    ? sample.sample_id.trim()
    : typeof sample?.sampleId === "string" && sample.sampleId.trim()
      ? sample.sampleId.trim()
      : "missing";
  const sourceIndex = Number.isInteger(sample?.displaySourceIndex)
    ? sample.displaySourceIndex
    : index;
  return `rule-release-sample:${identity}:${sourceIndex}`;
}

function normalizeRuleShadowRunRecord(
  raw,
  expectedProjectId,
  expectedRulePackId,
  path = "shadow_run",
) {
  const run = record(raw, path);
  const project = run.project_id === undefined
    ? requiredText(expectedProjectId, "expected_project_id")
    : projectId(run.project_id, expectedProjectId, `${path}.project_id`);
  const caseCount = nonNegativeInteger(run.case_count, `${path}.case_count`);
  const passedCount = nonNegativeInteger(run.passed_count, `${path}.passed_count`);
  const failedCount = nonNegativeInteger(run.failed_count, `${path}.failed_count`);
  const diagnosticCaseCount = nonNegativeInteger(
    run.diagnostic_case_count,
    `${path}.diagnostic_case_count`,
  );
  const diagnosticPassedCount = nonNegativeInteger(
    run.diagnostic_passed_count,
    `${path}.diagnostic_passed_count`,
  );
  const diagnosticFailedCount = nonNegativeInteger(
    run.diagnostic_failed_count,
    `${path}.diagnostic_failed_count`,
  );
  const results = array(run.results, `${path}.results`);
  const diagnosticResults = array(run.diagnostic_results, `${path}.diagnostic_results`);
  if (passedCount + failedCount !== caseCount) fail(path, "标准样本计数不一致");
  if (diagnosticPassedCount + diagnosticFailedCount !== diagnosticCaseCount) {
    fail(path, "诊断样本计数不一致");
  }
  if (results.length !== caseCount) fail(`${path}.results`, "与 case_count 数量不一致");
  if (diagnosticResults.length !== diagnosticCaseCount) {
    fail(`${path}.diagnostic_results`, "与 diagnostic_case_count 数量不一致");
  }
  results.forEach((item, index) => {
    const result = record(item, `${path}.results[${index}]`);
    requiredText(result.case_id, `${path}.results[${index}].case_id`);
    requiredText(result.rule_key, `${path}.results[${index}].rule_key`);
    booleanValue(result.expected_match, `${path}.results[${index}].expected_match`);
    booleanValue(result.actual_match, `${path}.results[${index}].actual_match`);
    booleanValue(result.passed, `${path}.results[${index}].passed`);
    requiredText(result.evidence_summary, `${path}.results[${index}].evidence_summary`);
  });
  diagnosticResults.forEach((item, index) => {
    const result = record(item, `${path}.diagnostic_results[${index}]`);
    requiredText(result.case_id, `${path}.diagnostic_results[${index}].case_id`);
    requiredText(result.rule_key, `${path}.diagnostic_results[${index}].rule_key`);
    requiredText(
      result.expected_diagnostic_category,
      `${path}.diagnostic_results[${index}].expected_diagnostic_category`,
    );
    requiredText(
      result.expected_diagnostic_code,
      `${path}.diagnostic_results[${index}].expected_diagnostic_code`,
    );
    enumValue(
      result.actual_state,
      SAMPLE_EVALUATION_STATES,
      `${path}.diagnostic_results[${index}].actual_state`,
    );
    requiredText(
      result.actual_diagnostic_code,
      `${path}.diagnostic_results[${index}].actual_diagnostic_code`,
    );
    booleanValue(result.passed, `${path}.diagnostic_results[${index}].passed`);
    requiredText(
      result.evidence_summary,
      `${path}.diagnostic_results[${index}].evidence_summary`,
    );
  });
  return {
    ...run,
    project_id: project,
    shadow_run_id: requiredText(run.shadow_run_id, `${path}.shadow_run_id`),
    rule_pack_id: run.rule_pack_id === undefined
      ? requiredText(expectedRulePackId, "expected_rule_pack_id")
      : requiredText(run.rule_pack_id, `${path}.rule_pack_id`),
    batch_id: requiredText(run.batch_id, `${path}.batch_id`),
    status: enumValue(run.status, SHADOW_RUN_STATUSES, `${path}.status`),
    case_count: caseCount,
    passed_count: passedCount,
    failed_count: failedCount,
    diagnostic_case_count: diagnosticCaseCount,
    diagnostic_passed_count: diagnosticPassedCount,
    diagnostic_failed_count: diagnosticFailedCount,
    results,
    diagnostic_results: diagnosticResults,
  };
}

export function normalizeRulePackList(raw, expectedProjectId, path = "rule_pack_list") {
  const payload = record(raw, path);
  const project = projectId(payload.project_id, expectedProjectId, `${path}.project_id`);
  return {
    ...payload,
    project_id: project,
    items: array(payload.items, `${path}.items`).map((item, index) => (
      normalizeRulePackRecord(item, project, `${path}.items[${index}]`)
    )),
  };
}

export function normalizeRulePackDetail(raw, expectedProjectId, path = "rule_pack_detail") {
  const payload = record(raw, path);
  const project = projectId(payload.project_id, expectedProjectId, `${path}.project_id`);
  const pack = normalizeRulePackRecord(payload.pack, project, `${path}.pack`);
  const rules = array(payload.rules, `${path}.rules`).map((item, index) => (
    normalizeRuleRecord(
      item,
      project,
      pack.protocol_version_id,
      `${path}.rules[${index}]`,
    )
  ));
  const ids = new Set(rules.map((rule) => rule.rule_revision_id));
  if (ids.size !== rules.length || ids.size !== pack.rule_revision_ids.length
    || pack.rule_revision_ids.some((id) => !ids.has(id))) {
    fail(`${path}.rules`, "与规则包声明的规则身份不一致");
  }
  return { ...payload, project_id: project, pack, rules };
}

export function normalizeRulePackMutationResult(raw, expectedProjectId, path = "rule_pack_mutation") {
  const payload = record(raw, path);
  const project = projectId(payload.project_id, expectedProjectId, `${path}.project_id`);
  if (payload.reused !== undefined) booleanValue(payload.reused, `${path}.reused`);
  if (payload.replayed !== undefined) booleanValue(payload.replayed, `${path}.replayed`);
  return {
    ...payload,
    project_id: project,
    pack: normalizeRulePackRecord(payload.pack, project, `${path}.pack`),
  };
}

export function normalizeRulePackDraftResult(raw, expectedProjectId) {
  const payload = normalizeRulePackMutationResult(raw, expectedProjectId, "rule_pack_draft");
  const rules = array(payload.rules, "rule_pack_draft.rules").map((item, index) => (
    normalizeRuleRecord(
      item,
      payload.project_id,
      payload.pack.protocol_version_id,
      `rule_pack_draft.rules[${index}]`,
    )
  ));
  return { ...payload, rules };
}

export function normalizeAutomaticShadowResult(raw, expectedProjectId) {
  const payload = normalizeRulePackMutationResult(
    raw,
    expectedProjectId,
    "automatic_shadow",
  );
  return {
    ...payload,
    inspection: normalizeShadowInspectionRecord(
      payload.inspection,
      payload.project_id,
      "automatic_shadow.inspection",
    ),
  };
}

export function normalizeShadowConfirmationResult(raw, expectedProjectId) {
  const payload = normalizeRulePackMutationResult(
    raw,
    expectedProjectId,
    "shadow_confirmation",
  );
  if (payload.confirmation_id !== undefined) {
    requiredText(payload.confirmation_id, "shadow_confirmation.confirmation_id");
  }
  if (payload.shadow_run_id !== undefined) {
    requiredText(payload.shadow_run_id, "shadow_confirmation.shadow_run_id");
  }
  return payload;
}

export function normalizeShadowSampleSetList(raw, expectedProjectId) {
  const payload = record(raw, "shadow_sample_set_list");
  const project = projectId(
    payload.project_id,
    expectedProjectId,
    "shadow_sample_set_list.project_id",
  );
  return {
    ...payload,
    project_id: project,
    items: array(payload.items, "shadow_sample_set_list.items").map((item, index) => (
      normalizeShadowInspectionRecord(
        item,
        project,
        `shadow_sample_set_list.items[${index}]`,
      )
    )),
  };
}

export function normalizeShadowRunList(raw, expectedProjectId, expectedRulePackId) {
  const payload = record(raw, "shadow_run_list");
  const project = projectId(payload.project_id, expectedProjectId, "shadow_run_list.project_id");
  return {
    ...payload,
    project_id: project,
    items: array(payload.items, "shadow_run_list.items").map((item, index) => (
      normalizeRuleShadowRunRecord(
        item,
        project,
        expectedRulePackId,
        `shadow_run_list.items[${index}]`,
      )
    )),
  };
}

export function normalizeShadowLineageEvidence(raw, expectedProjectId, expectedRulePackId) {
  const payload = record(raw, "shadow_lineage_evidence");
  const project = projectId(
    payload.project_id,
    expectedProjectId,
    "shadow_lineage_evidence.project_id",
  );
  const rulePackId = requiredText(payload.rule_pack_id, "shadow_lineage_evidence.rule_pack_id");
  if (expectedRulePackId !== undefined && rulePackId !== expectedRulePackId) {
    fail("shadow_lineage_evidence.rule_pack_id", "与当前规则包不一致");
  }
  const shadowRulePackId = optionalText(
    payload.shadow_rule_pack_id,
    "shadow_lineage_evidence.shadow_rule_pack_id",
  );
  const items = array(payload.items, "shadow_lineage_evidence.items").map((item, index) => (
    normalizeShadowInspectionRecord(
      item,
      project,
      `shadow_lineage_evidence.items[${index}]`,
    )
  ));
  let confirmation = null;
  if (payload.confirmation !== null && payload.confirmation !== undefined) {
    const value = record(payload.confirmation, "shadow_lineage_evidence.confirmation");
    confirmation = {
      ...value,
      confirmation_id: requiredText(
        value.confirmation_id,
        "shadow_lineage_evidence.confirmation.confirmation_id",
      ),
      sample_set_id: requiredText(
        value.sample_set_id,
        "shadow_lineage_evidence.confirmation.sample_set_id",
      ),
      trusted_shadow_run_id: requiredText(
        value.trusted_shadow_run_id,
        "shadow_lineage_evidence.confirmation.trusted_shadow_run_id",
      ),
      confirmed_at: requiredText(
        value.confirmed_at,
        "shadow_lineage_evidence.confirmation.confirmed_at",
      ),
    };
    if (!items.some((item) => item.sample_set_id === confirmation.sample_set_id)) {
      fail(
        "shadow_lineage_evidence.confirmation.sample_set_id",
        "未在谱系样本集中找到",
      );
    }
  }
  return {
    ...payload,
    project_id: project,
    rule_pack_id: rulePackId,
    shadow_rule_pack_id: shadowRulePackId,
    items,
    confirmation,
  };
}

export function normalizeRulePackDiff(raw, expectedProjectId) {
  const payload = record(raw, "rule_pack_diff");
  const project = projectId(payload.project_id, expectedProjectId, "rule_pack_diff.project_id");
  const impact = record(payload.impact, "rule_pack_diff.impact");
  return {
    ...payload,
    project_id: project,
    impact: {
      ...impact,
      previous_rule_pack_id: requiredText(
        impact.previous_rule_pack_id,
        "rule_pack_diff.impact.previous_rule_pack_id",
      ),
      current_rule_pack_id: requiredText(
        impact.current_rule_pack_id,
        "rule_pack_diff.impact.current_rule_pack_id",
      ),
      added_rule_keys: stringArray(impact.added_rule_keys, "rule_pack_diff.impact.added_rule_keys"),
      changed_rule_keys: stringArray(impact.changed_rule_keys, "rule_pack_diff.impact.changed_rule_keys"),
      superseded_rule_keys: stringArray(
        impact.superseded_rule_keys,
        "rule_pack_diff.impact.superseded_rule_keys",
      ),
      unchanged_rule_keys: stringArray(
        impact.unchanged_rule_keys,
        "rule_pack_diff.impact.unchanged_rule_keys",
      ),
    },
  };
}

export function normalizeRuleReleaseReadiness(raw, expectedProjectId, expectedBatchId) {
  const readiness = record(raw, "rule_release_readiness");
  const project = projectId(
    readiness.project_id,
    expectedProjectId,
    "rule_release_readiness.project_id",
  );
  const batchId = requiredText(readiness.batch_id, "rule_release_readiness.batch_id");
  if (expectedBatchId !== undefined && batchId !== expectedBatchId) {
    fail("rule_release_readiness.batch_id", "与当前冻结批次不一致");
  }
  return {
    ...readiness,
    project_id: project,
    batch_id: batchId,
    ready: booleanValue(readiness.ready, "rule_release_readiness.ready"),
    state_code: requiredText(readiness.state_code, "rule_release_readiness.state_code"),
    message: requiredText(readiness.message, "rule_release_readiness.message"),
    next_action: requiredText(readiness.next_action, "rule_release_readiness.next_action"),
  };
}
