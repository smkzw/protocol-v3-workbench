const BATCH_STATES = new Set([
  "draft",
  "parsed",
  "validated",
  "confirmed",
  "frozen",
]);

const SOURCE_CLASSES = new Set([
  "raw_full_snapshot",
  "raw_full_snapshot_candidate",
  "verified_derived_full_snapshot",
  "comparison_workbook",
  "mixed_monitoring_workbook",
  "raw_snapshot_with_format_defect",
  "restored_transitional",
  "processed_full_snapshot",
  "unknown_blocked",
]);

const VALIDATION_OUTCOMES = new Set([
  "match",
  "warning",
  "mismatch",
  "not_assessed",
]);

export class MedicalMonitoringBatchShapeError extends Error {
  constructor(path, message) {
    super(`${path} ${message}`);
    this.name = "MedicalMonitoringBatchShapeError";
  }
}

function fail(path, message) {
  throw new MedicalMonitoringBatchShapeError(path, message);
}

function record(value, path) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(path, "must be an object");
  }
  return value;
}

function array(value, path) {
  if (!Array.isArray(value)) fail(path, "must be an array");
  return value;
}

function requiredText(value, path) {
  if (typeof value !== "string" || !value.trim()) {
    fail(path, "must be a non-empty string");
  }
  return value.trim();
}

function text(value, path) {
  if (typeof value !== "string") fail(path, "must be a string");
  return value.trim();
}

function optionalText(value, path) {
  if (value === undefined || value === null) return null;
  return text(value, path);
}

function nonNegativeInteger(value, path) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    fail(path, "must be a non-negative integer");
  }
  return value;
}

function stringArray(value, path) {
  return array(value, path).map((item, index) => (
    requiredText(item, `${path}[${index}]`)
  ));
}

function normalizeSourceClass(value, path) {
  const sourceClass = requiredText(value, path);
  if (!SOURCE_CLASSES.has(sourceClass)) {
    fail(path, `has unsupported value ${sourceClass}`);
  }
  return sourceClass;
}

export function normalizeSourceRegistration(raw, path = "source") {
  const source = record(raw, path);
  return {
    ...source,
    source_id: requiredText(source.source_id, `${path}.source_id`),
    source_entry_id: requiredText(source.source_entry_id, `${path}.source_entry_id`),
    source_class: normalizeSourceClass(source.source_class, `${path}.source_class`),
    file_name: requiredText(source.file_name, `${path}.file_name`),
    content_sha256: requiredText(source.content_sha256, `${path}.content_sha256`),
    size_bytes: nonNegativeInteger(source.size_bytes, `${path}.size_bytes`),
    technical_status: requiredText(source.technical_status, `${path}.technical_status`),
    content_warnings: source.content_warnings === undefined
      ? []
      : stringArray(source.content_warnings, `${path}.content_warnings`),
    medical_override_reason: optionalText(
      source.medical_override_reason,
      `${path}.medical_override_reason`,
    ),
    created_at: requiredText(source.created_at, `${path}.created_at`),
  };
}

export function normalizeBatchRecord(raw, path = "batch") {
  const batch = record(raw, path);
  const state = requiredText(batch.state, `${path}.state`);
  if (!BATCH_STATES.has(state)) fail(`${path}.state`, `has unsupported value ${state}`);
  const fullSnapshotProof = batch.full_snapshot_proof === undefined
    || batch.full_snapshot_proof === null
    ? null
    : record(batch.full_snapshot_proof, `${path}.full_snapshot_proof`);
  return {
    ...batch,
    batch_id: requiredText(batch.batch_id, `${path}.batch_id`),
    project_id: requiredText(batch.project_id, `${path}.project_id`),
    state,
    version: nonNegativeInteger(batch.version, `${path}.version`),
    expected_domains: stringArray(batch.expected_domains, `${path}.expected_domains`),
    active_mapping_revision: optionalText(
      batch.active_mapping_revision,
      `${path}.active_mapping_revision`,
    ),
    full_snapshot_proof: fullSnapshotProof,
    created_at: requiredText(batch.created_at, `${path}.created_at`),
    updated_at: requiredText(batch.updated_at, `${path}.updated_at`),
    frozen_at: optionalText(batch.frozen_at, `${path}.frozen_at`),
  };
}

/**
 * Build a UI-only reconciliation key for a batch-list row. The persisted
 * `batch_id` remains the source identity; the source index only prevents
 * duplicate or malformed rows from colliding in the list renderer.
 */
export function batchDisplayKey(batch, index = 0) {
  const identity = typeof batch?.batch_id === "string" && batch.batch_id.trim()
    ? batch.batch_id.trim()
    : "missing";
  return `batch:${identity}:${index}`;
}

export function normalizeBatchList(raw, path = "batch_list") {
  const payload = record(raw, path);
  const projectId = requiredText(payload.project_id, `${path}.project_id`);
  const normalizedBatches = array(payload.batches, `${path}.batches`)
    .map((item, index) => normalizeBatchRecord(item, `${path}.batches[${index}]`));
  if (normalizedBatches.some((batch) => batch.project_id !== projectId)) {
    fail(`${path}.batches`, "contains a batch from another project");
  }
  const identityCounts = new Map();
  normalizedBatches.forEach((batch) => {
    identityCounts.set(batch.batch_id, (identityCounts.get(batch.batch_id) || 0) + 1);
  });
  const batches = normalizedBatches.map((batch, displaySourceIndex) => {
    const duplicate = (identityCounts.get(batch.batch_id) || 0) > 1;
    return {
      ...batch,
      displaySourceIndex,
      displayIdentityState: duplicate ? "duplicate" : "ready",
      displayIdentityIssue: duplicate
        ? "batch_id 重复；保留批次但暂不能选择"
        : "",
      displayKey: batchDisplayKey(batch, displaySourceIndex),
    };
  });
  return { ...payload, project_id: projectId, batches };
}

export function normalizeBatchDetail(raw, path = "batch_detail") {
  const detail = record(raw, path);
  const batch = normalizeBatchRecord(detail, path);
  const sources = array(detail.sources, `${path}.sources`)
    .map((item, index) => normalizeSourceRegistration(item, `${path}.sources[${index}]`));
  const domainCounts = record(detail.domain_counts, `${path}.domain_counts`);
  const normalizedDomainCounts = Object.fromEntries(
    Object.entries(domainCounts).map(([domain, count]) => [
      requiredText(domain, `${path}.domain_counts key`),
      nonNegativeInteger(count, `${path}.domain_counts.${domain}`),
    ]),
  );
  return {
    ...detail,
    ...batch,
    sources,
    row_count: nonNegativeInteger(detail.row_count, `${path}.row_count`),
    domain_counts: normalizedDomainCounts,
  };
}

export function normalizeBatchMutationResult(raw, path = "batch_mutation") {
  const result = record(raw, path);
  if (result.replayed !== undefined && typeof result.replayed !== "boolean") {
    fail(`${path}.replayed`, "must be a boolean");
  }
  return {
    ...result,
    batch: normalizeBatchRecord(result.batch, `${path}.batch`),
  };
}

export function normalizeValidationReport(raw, path = "validation") {
  const validation = record(raw, path);
  const checks = array(validation.checks, `${path}.checks`).map((item, index) => {
    const check = record(item, `${path}.checks[${index}]`);
    const outcome = requiredText(check.outcome, `${path}.checks[${index}].outcome`);
    if (!VALIDATION_OUTCOMES.has(outcome)) {
      fail(`${path}.checks[${index}].outcome`, `has unsupported value ${outcome}`);
    }
    return {
      ...check,
      check_code: requiredText(check.check_code, `${path}.checks[${index}].check_code`),
      outcome,
      label: requiredText(check.label, `${path}.checks[${index}].label`),
      observed_value: optionalText(
        check.observed_value,
        `${path}.checks[${index}].observed_value`,
      ),
    };
  });
  return {
    ...validation,
    validation_id: requiredText(validation.validation_id, `${path}.validation_id`),
    revision: nonNegativeInteger(validation.revision, `${path}.revision`),
    use_status: requiredText(validation.use_status, `${path}.use_status`),
    summary: optionalText(validation.summary, `${path}.summary`),
    checks,
  };
}

export function normalizeClassification(raw, path = "classification") {
  const classification = record(raw, path);
  return {
    ...classification,
    source_class: normalizeSourceClass(
      classification.source_class,
      `${path}.source_class`,
    ),
    technical_status: requiredText(
      classification.technical_status,
      `${path}.technical_status`,
    ),
    content_warnings: classification.content_warnings === undefined
      ? []
      : stringArray(classification.content_warnings, `${path}.content_warnings`),
  };
}

export function normalizeBatchIntakeResult(raw, path = "batch_intake") {
  const result = record(raw, path);
  return {
    ...result,
    source_entry_id: requiredText(result.source_entry_id, `${path}.source_entry_id`),
    validation: normalizeValidationReport(result.validation, `${path}.validation`),
    classification: normalizeClassification(result.classification, `${path}.classification`),
    source: normalizeSourceRegistration(result.source, `${path}.source`),
    batch: normalizeBatchMutationResult(result.batch, `${path}.batch`),
    observed_domains: stringArray(result.observed_domains, `${path}.observed_domains`),
    row_count: nonNegativeInteger(result.row_count, `${path}.row_count`),
  };
}

export function normalizeContentConfirmationDetail(raw, path = "content_confirmation") {
  const detail = record(raw, path);
  return {
    ...detail,
    source_entry_id: requiredText(detail.source_entry_id, `${path}.source_entry_id`),
    validation: normalizeValidationReport(detail.validation, `${path}.validation`),
  };
}

export function normalizeClassificationConfirmationDetail(
  raw,
  path = "classification_confirmation",
) {
  const detail = record(raw, path);
  return {
    ...detail,
    source_entry_id: requiredText(detail.source_entry_id, `${path}.source_entry_id`),
    classification: normalizeClassification(
      detail.classification,
      `${path}.classification`,
    ),
  };
}
