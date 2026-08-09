const FIELD_KINDS = new Set([
  "source_collected",
  "source_metadata",
  "standardized_coded",
  "deterministic_derived",
  "unmapped",
]);

const JOB_STATES = new Set([
  "queued",
  "leased",
  "running",
  "completed",
  "failed",
  "blocked",
  "stale_input",
  "cancelled",
]);

const DRAFT_STATES = new Set(["draft", "confirmed"]);
const QUALITY_STATES = new Set(["blocked", "pass_with_warnings", "passed"]);
const QUALITY_DISPOSITIONS = new Set([
  "reject",
  "activate_restricted",
  "activate_full",
]);
const QUALITY_FINDING_SEVERITIES = new Set([
  "global_blocker",
  "capability_blocker",
  "review_warning",
  "auto_resolved",
]);
const CAPABILITY_STATES = new Set([
  "ready",
  "limited",
  "blocked_by_quality",
  "disabled_by_design",
]);

export class MedicalMonitoringFieldMappingShapeError extends Error {
  constructor(path, message) {
    super(`${path} ${message}`);
    this.name = "MedicalMonitoringFieldMappingShapeError";
  }
}

function fail(path, message) {
  throw new MedicalMonitoringFieldMappingShapeError(path, message);
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

function nonNegativeInteger(value, path) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    fail(path, "must be a non-negative integer");
  }
  return value;
}

function confidence(value, path) {
  if (
    typeof value !== "number"
    || !Number.isFinite(value)
    || value < 0
    || value > 1
  ) {
    fail(path, "must be a finite number between 0 and 1");
  }
  return value;
}

function optionalRecord(value, path) {
  if (value === undefined || value === null) return null;
  return record(value, path);
}

function stringArray(value, path) {
  return array(value, path).map((item, index) => (
    requiredText(item, `${path}[${index}]`)
  ));
}

function evidenceSummary(value, path) {
  if (value === undefined || value === null) return [];
  return array(value, path).map((item, index) => {
    const row = record(item, `${path}[${index}]`);
    const profile = row.profile === undefined || row.profile === null
      ? null
      : record(row.profile, `${path}[${index}].profile`);
    if (row.evidence_id !== undefined) {
      requiredText(row.evidence_id, `${path}[${index}].evidence_id`);
    }
    if (row.locator !== undefined) text(row.locator, `${path}[${index}].locator`);
    return { ...row, profile, sourceIndex: index };
  });
}

function normalizeField(raw, path) {
  const row = record(raw, path);
  const fieldKind = requiredText(row.field_kind, `${path}.field_kind`);
  if (!FIELD_KINDS.has(fieldKind)) {
    fail(`${path}.field_kind`, `has unsupported value ${fieldKind}`);
  }
  const normalized = {
    ...row,
    domain: requiredText(row.domain, `${path}.domain`),
    source_field: requiredText(row.source_field, `${path}.source_field`),
    recommended_role: requiredText(
      row.recommended_role,
      `${path}.recommended_role`,
    ),
    field_kind: fieldKind,
    confidence: confidence(row.confidence, `${path}.confidence`),
    uncertainty: requiredText(row.uncertainty, `${path}.uncertainty`),
    user_action: requiredText(row.user_action, `${path}.user_action`),
    related_fields: row.related_fields === undefined
      ? []
      : stringArray(row.related_fields, `${path}.related_fields`),
    evidence_ids: row.evidence_ids === undefined
      ? []
      : stringArray(row.evidence_ids, `${path}.evidence_ids`),
    object_identity_evidence_fields: row.object_identity_evidence_fields === undefined
      ? []
      : stringArray(
        row.object_identity_evidence_fields,
        `${path}.object_identity_evidence_fields`,
      ),
    quality_gate_actions: row.quality_gate_actions === undefined
      ? []
      : stringArray(row.quality_gate_actions, `${path}.quality_gate_actions`),
    standards_reference: optionalRecord(
      row.standards_reference,
      `${path}.standards_reference`,
    ),
    derivation_lineage: optionalRecord(
      row.derivation_lineage,
      `${path}.derivation_lineage`,
    ),
    value_constraints: optionalRecord(
      row.value_constraints,
      `${path}.value_constraints`,
    ),
    evidence_summary: evidenceSummary(row.evidence_summary, `${path}.evidence_summary`),
  };
  if (row.validated_treatment_identity_binding !== undefined) {
    normalized.validated_treatment_identity_binding = optionalRecord(
      row.validated_treatment_identity_binding,
      `${path}.validated_treatment_identity_binding`,
    );
  }
  return normalized;
}

function normalizeJob(raw, path) {
  const job = record(raw, path);
  const status = requiredText(job.status, `${path}.status`);
  if (!JOB_STATES.has(status)) fail(`${path}.status`, `has unsupported value ${status}`);
  return {
    ...job,
    job_id: requiredText(job.job_id, `${path}.job_id`),
    status,
  };
}

function normalizeCandidate(raw, path) {
  const candidate = record(raw, path);
  const payload = record(
    candidate.structured_payload,
    `${path}.structured_payload`,
  );
  const mappings = array(
    payload.field_mappings,
    `${path}.structured_payload.field_mappings`,
  ).map((item, index) => normalizeField(item, `${path}.field_mappings[${index}]`));
  return {
    ...candidate,
    candidate_id: requiredText(candidate.candidate_id, `${path}.candidate_id`),
    structured_payload: { ...payload, field_mappings: mappings },
  };
}

function normalizeJobDetail(raw, path) {
  const detail = record(raw, path);
  const candidates = array(detail.candidates, `${path}.candidates`)
    .map((item, index) => normalizeCandidate(item, `${path}.candidates[${index}]`));
  return {
    ...detail,
    job: normalizeJob(detail.job, `${path}.job`),
    candidates,
  };
}

function normalizeFinding(raw, path) {
  const finding = record(raw, path);
  const severity = requiredText(finding.severity, `${path}.severity`);
  if (!QUALITY_FINDING_SEVERITIES.has(severity)) {
    fail(`${path}.severity`, `has unsupported value ${severity}`);
  }
  return {
    ...finding,
    severity,
    title_zh: text(finding.title_zh ?? "", `${path}.title_zh`),
    affected_capability_ids: finding.affected_capability_ids === undefined
      ? []
      : stringArray(
        finding.affected_capability_ids,
        `${path}.affected_capability_ids`,
      ),
    affected_fields: finding.affected_fields === undefined
      ? []
      : array(finding.affected_fields, `${path}.affected_fields`),
  };
}

function normalizeCapabilityState(raw, path) {
  const state = record(raw, path);
  const stateValue = requiredText(state.state, `${path}.state`);
  if (!CAPABILITY_STATES.has(stateValue)) {
    fail(`${path}.state`, `has unsupported value ${stateValue}`);
  }
  return {
    ...state,
    capability_id: requiredText(state.capability_id, `${path}.capability_id`),
    state: stateValue,
    blocking_finding_group_ids: state.blocking_finding_group_ids === undefined
      ? []
      : stringArray(
        state.blocking_finding_group_ids,
        `${path}.blocking_finding_group_ids`,
      ),
    limitation_codes: state.limitation_codes === undefined
      ? []
      : stringArray(state.limitation_codes, `${path}.limitation_codes`),
  };
}

export function normalizeSemanticQualityReport(raw, path = "semantic_quality") {
  if (raw === null || raw === undefined) return null;
  const report = record(raw, path);
  const status = requiredText(report.status, `${path}.status`);
  const disposition = requiredText(
    report.activation_disposition,
    `${path}.activation_disposition`,
  );
  if (!QUALITY_STATES.has(status)) fail(`${path}.status`, `has unsupported value ${status}`);
  if (!QUALITY_DISPOSITIONS.has(disposition)) {
    fail(`${path}.activation_disposition`, `has unsupported value ${disposition}`);
  }
  return {
    ...report,
    status,
    activation_disposition: disposition,
    global_blocker_count: nonNegativeInteger(
      report.global_blocker_count,
      `${path}.global_blocker_count`,
    ),
    capability_blocker_count: nonNegativeInteger(
      report.capability_blocker_count,
      `${path}.capability_blocker_count`,
    ),
    warning_count: nonNegativeInteger(report.warning_count, `${path}.warning_count`),
    finding_groups: array(report.finding_groups, `${path}.finding_groups`)
      .map((item, index) => normalizeFinding(item, `${path}.finding_groups[${index}]`)),
    capability_states: array(report.capability_states, `${path}.capability_states`)
      .map((item, index) => normalizeCapabilityState(item, `${path}.capability_states[${index}]`)),
  };
}

export function normalizeMappingDraft(raw, path = "draft") {
  if (raw === null || raw === undefined) return null;
  const draft = record(raw, path);
  const status = requiredText(draft.status, `${path}.status`);
  if (!DRAFT_STATES.has(status)) fail(`${path}.status`, `has unsupported value ${status}`);
  return {
    ...draft,
    draft_id: requiredText(draft.draft_id, `${path}.draft_id`),
    version: nonNegativeInteger(draft.version, `${path}.version`),
    status,
    fields: array(draft.fields, `${path}.fields`)
      .map((item, index) => normalizeField(item, `${path}.fields[${index}]`)),
    semantic_quality: draft.semantic_quality === undefined
      ? undefined
      : normalizeSemanticQualityReport(draft.semantic_quality, `${path}.semantic_quality`),
  };
}

export function normalizeMappingRevision(raw, path = "mapping_revision") {
  const revision = record(raw, path);
  return {
    ...revision,
    mapping_revision: requiredText(
      revision.mapping_revision,
      `${path}.mapping_revision`,
    ),
    draft_id: requiredText(revision.draft_id, `${path}.draft_id`),
    draft_version: nonNegativeInteger(
      revision.draft_version,
      `${path}.draft_version`,
    ),
    fields: array(revision.fields, `${path}.fields`)
      .map((item, index) => normalizeField(item, `${path}.fields[${index}]`)),
    activation: revision.activation === undefined || revision.activation === null
      ? null
      : record(revision.activation, `${path}.activation`),
  };
}

export function normalizeFieldMappingRun(raw, path = "field_mapping_run") {
  const run = record(raw, path);
  const jobs = array(run.jobs, `${path}.jobs`)
    .map((item, index) => normalizeJob(item, `${path}.jobs[${index}]`));
  const jobCount = nonNegativeInteger(run.job_count, `${path}.job_count`);
  if (jobCount !== jobs.length) fail(`${path}.job_count`, "does not match jobs length");
  return {
    ...run,
    batch_id: requiredText(run.batch_id, `${path}.batch_id`),
    profile_sha256: text(run.profile_sha256, `${path}.profile_sha256`),
    input_sha256: text(run.input_sha256, `${path}.input_sha256`),
    field_count: nonNegativeInteger(run.field_count, `${path}.field_count`),
    job_count: jobCount,
    jobs,
  };
}

export function normalizeFieldMappingStatus(raw, path = "field_mapping_status") {
  const status = record(raw, path);
  const details = array(status.job_details, `${path}.job_details`)
    .map((item, index) => normalizeJobDetail(item, `${path}.job_details[${index}]`));
  const jobCount = nonNegativeInteger(status.job_count, `${path}.job_count`);
  if (jobCount !== details.length) {
    fail(`${path}.job_count`, "does not match job_details length");
  }
  return {
    ...status,
    batch_id: requiredText(status.batch_id, `${path}.batch_id`),
    profile_sha256: text(status.profile_sha256, `${path}.profile_sha256`),
    input_sha256: text(status.input_sha256, `${path}.input_sha256`),
    field_count: nonNegativeInteger(status.field_count, `${path}.field_count`),
    job_count: jobCount,
    job_details: details,
    draft: normalizeMappingDraft(status.draft, `${path}.draft`),
    semantic_quality: normalizeSemanticQualityReport(
      status.semantic_quality,
      `${path}.semantic_quality`,
    ),
    active_mapping: status.active_mapping === undefined || status.active_mapping === null
      ? null
      : record(status.active_mapping, `${path}.active_mapping`),
  };
}

export function medicalMonitoringFieldMappingEvidenceKey(item, index = 0) {
  const evidenceId = typeof item?.evidence_id === "string" ? item.evidence_id.trim() : "";
  const locator = typeof item?.locator === "string" ? item.locator.trim() : "";
  const identity = evidenceId || locator || "missing";
  const sourceIndex = Number.isInteger(item?.sourceIndex) ? item.sourceIndex : index;
  return `evidence:${identity}:${sourceIndex}`;
}
