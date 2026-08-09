const ASSURANCE_MODES = new Set(["pre_lock", "pre_inspection"]);
const ASSURANCE_STATUSES = new Set([
  "draft",
  "running",
  "blocked",
  "completed",
  "superseded",
]);
const ASSURANCE_EVIDENCE_PROVENANCE_STATUSES = new Set([
  "server_evidence_run_ledger",
  "signed_manifest_server_revalidated",
]);
const FROZEN_IDENTITY_FIELDS = [
  "batch_id",
  "batch_revision",
  "mapping_revision",
  "protocol_version_id",
  "rule_pack_revision",
  "dictionary_revision",
  "ctcae_revision",
  "model_revision",
  "risk_snapshot_id",
];
const AUDIT_ACTIONS = new Set([
  "read_monitoring",
  "read_source_evidence",
  "read_risk_audit",
  "read_runtime_audit",
  "intake_batch",
  "run_deterministic_rules",
  "review_ai_candidate",
  "change_risk_disposition",
  "draft_query",
  "create_assurance_task",
  "record_assurance_evidence",
  "review_assurance",
  "export_risk_evidence",
  "complete_assurance",
  "confirm_high_risk_close",
  "approve_rule_change",
  "provide_center_context",
  "validate_source_revision",
  "mark_safety_pv_review",
  "confirm_derived_data",
  "administer_runtime",
]);
const AUDIT_TARGET_TYPES = new Set([
  "project",
  "trial",
  "site",
  "subject",
  "risk",
  "batch",
  "source",
  "rule",
  "runtime",
]);
const AUDIT_ROLES = new Set([
  "medical_monitor",
  "medical_manager",
  "medical_director",
  "medical_writer",
  "clinical_operations",
  "data_management",
  "pv",
  "statistics_programming",
  "system_admin",
  "product_engineering",
]);
const SHA256_RE = /^[0-9a-f]{64}$/;

export class MedicalMonitoringAssuranceShapeError extends Error {
  constructor(path, message) {
    super(`${path} ${message}`);
    this.name = "MedicalMonitoringAssuranceShapeError";
  }
}

function fail(path, message) {
  throw new MedicalMonitoringAssuranceShapeError(path, message);
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

function positiveInteger(value, path) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    fail(path, "must be a positive integer");
  }
  return value;
}

function nonNegativeInteger(value, path) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    fail(path, "must be a non-negative integer");
  }
  return value;
}

function strictBoolean(value, path) {
  if (typeof value !== "boolean") fail(path, "must be a boolean");
  return value;
}

function sha256(value, path, { allowEmpty = false } = {}) {
  const text = requiredText(value, path).toLowerCase();
  if (allowEmpty && text === "") return "";
  if (!SHA256_RE.test(text)) fail(path, "must be a lowercase SHA-256 digest");
  return text;
}

function optionalSha256(value, path) {
  if (value === "") return "";
  return sha256(value, path);
}

function roleArray(value, path, { allowEmpty = false } = {}) {
  if (!Array.isArray(value) || (!allowEmpty && value.length === 0)) {
    fail(path, allowEmpty ? "must be an array" : "must be a non-empty array");
  }
  const roles = value.map((item, index) => requiredText(item, `${path}[${index}]`));
  if (new Set(roles).size !== roles.length) fail(path, "must contain unique values");
  const unsupported = roles.find((role) => !AUDIT_ROLES.has(role));
  if (unsupported) fail(path, `contains unsupported role ${unsupported}`);
  return roles;
}

function isoTimestamp(value, path) {
  const text = requiredText(value, path);
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) fail(path, "must be an ISO-8601 timestamp");
  return text;
}

function auditPayloadIsSafe(value, path = "payload") {
  if (value === undefined) return;
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(path, "must be an object");
  for (const [key, nested] of Object.entries(value)) {
    if (["access_token", "authorization", "password", "secret", "session_id", "token"].includes(key.toLowerCase())) {
      fail(`${path}.${key}`, "contains a sensitive field");
    }
    if (nested && typeof nested === "object") {
      if (Array.isArray(nested)) nested.forEach((item, index) => auditPayloadIsSafe(item, `${path}.${key}[${index}]`));
      else auditPayloadIsSafe(nested, `${path}.${key}`);
    }
  }
}

function normalizeAssuranceAuditEvent(raw, { projectId: expectedProjectId, taskId, path }) {
  const event = record(raw, path);
  projectId(event.project_id, expectedProjectId, `${path}.project_id`);
  requiredText(event.audit_id, `${path}.audit_id`);
  requiredText(event.principal_id, `${path}.principal_id`);
  const roleClaims = roleArray(event.role_claims, `${path}.role_claims`);
  const matchedRoles = roleArray(event.matched_roles, `${path}.matched_roles`, { allowEmpty: true });
  if (matchedRoles.some((role) => !roleClaims.includes(role))) fail(`${path}.matched_roles`, "must be a subset of role_claims");
  const action = requiredText(event.action, `${path}.action`);
  if (!AUDIT_ACTIONS.has(action)) fail(`${path}.action`, `has unsupported value ${action}`);
  const targetType = requiredText(event.target_type, `${path}.target_type`);
  if (!AUDIT_TARGET_TYPES.has(targetType)) fail(`${path}.target_type`, `has unsupported value ${targetType}`);
  requiredText(event.target_id, `${path}.target_id`);
  const sourceRevision = sha256(event.source_revision, `${path}.source_revision`);
  const authorizationDecision = sha256(event.authorization_decision_sha256, `${path}.authorization_decision_sha256`);
  strictBoolean(event.decision_allowed, `${path}.decision_allowed`);
  strictBoolean(event.write_permitted, `${path}.write_permitted`);
  strictBoolean(event.mutation_applied, `${path}.mutation_applied`);
  const versionBefore = nonNegativeInteger(event.aggregate_version_before, `${path}.aggregate_version_before`);
  const versionAfter = nonNegativeInteger(event.aggregate_version_after, `${path}.aggregate_version_after`);
  if (event.mutation_applied && versionAfter !== versionBefore + 1) fail(path, "mutation event must advance aggregate version by one");
  if (!event.mutation_applied && versionAfter !== versionBefore) fail(path, "non-mutating event cannot change aggregate version");
  const occurredAt = isoTimestamp(event.occurred_at, `${path}.occurred_at`);
  const prevEventHash = optionalSha256(event.prev_event_hash, `${path}.prev_event_hash`);
  const eventHash = sha256(event.event_hash, `${path}.event_hash`);
  if (taskId && event.payload !== undefined) {
    auditPayloadIsSafe(event.payload, `${path}.payload`);
    if (event.payload?.task_id !== undefined && String(event.payload.task_id) !== taskId) {
      fail(`${path}.payload.task_id`, "does not match the selected task");
    }
  } else {
    auditPayloadIsSafe(event.payload, `${path}.payload`);
  }
  return {
    schema_version: requiredText(event.schema_version, `${path}.schema_version`),
    audit_id: String(event.audit_id).trim(),
    project_id: String(expectedProjectId).trim(),
    principal_id: String(event.principal_id).trim(),
    role_claims: roleClaims,
    matched_roles: matchedRoles,
    action,
    target_type: targetType,
    target_id: String(event.target_id).trim(),
    source_revision: sourceRevision,
    authorization_decision_sha256: authorizationDecision,
    decision_allowed: event.decision_allowed,
    write_permitted: event.write_permitted,
    mutation_applied: event.mutation_applied,
    aggregate_version_before: versionBefore,
    aggregate_version_after: versionAfter,
    occurred_at: occurredAt,
    prev_event_hash: prevEventHash,
    event_hash: eventHash,
  };
}

function projectId(value, expected, path) {
  const actual = requiredText(value, path);
  const wanted = requiredText(expected, "project_id");
  if (actual !== wanted) fail(path, "does not match the active project");
  return actual;
}

function normalizeFrozenIdentity(value, path) {
  const identity = record(value, path);
  for (const field of FROZEN_IDENTITY_FIELDS) {
    requiredText(identity[field], `${path}.${field}`);
  }
  return identity;
}

export function normalizeAssuranceTask(raw, { projectId: expectedProjectId, path = "task" } = {}) {
  const task = record(raw, path);
  projectId(task.project_id, expectedProjectId, `${path}.project_id`);
  requiredText(task.task_id, `${path}.task_id`);
  const mode = requiredText(task.mode, `${path}.mode`);
  if (!ASSURANCE_MODES.has(mode)) fail(`${path}.mode`, `has unsupported value ${mode}`);
  const status = requiredText(task.status, `${path}.status`);
  if (!ASSURANCE_STATUSES.has(status)) fail(`${path}.status`, `has unsupported value ${status}`);
  positiveInteger(task.version, `${path}.version`);
  normalizeFrozenIdentity(task.frozen_identity, `${path}.frozen_identity`);
  requiredText(task.updated_at, `${path}.updated_at`);
  if (task.medical_review_recorded !== undefined) {
    strictBoolean(task.medical_review_recorded, `${path}.medical_review_recorded`);
  }
  return task;
}

function envelope(raw, expectedProjectId, path) {
  const payload = record(raw, path);
  projectId(payload.project_id, expectedProjectId, `${path}.project_id`);
  return payload;
}

export function normalizeAssuranceTaskList(
  raw,
  { projectId: expectedProjectId, mode = "", path = "assurance_task_list" } = {},
) {
  const payload = envelope(raw, expectedProjectId, path);
  const items = array(payload.items, `${path}.items`).map((item, index) => (
    normalizeAssuranceTask(item, {
      projectId: expectedProjectId,
      path: `${path}.items[${index}]`,
    })
  ));
  if (mode && items.some((item) => item.mode !== mode)) {
    fail(`${path}.items`, "contains a task from another assurance mode");
  }
  return { ...payload, project_id: String(expectedProjectId).trim(), items };
}

export function normalizeAssuranceTaskPayload(
  raw,
  { projectId: expectedProjectId, taskId = "", path = "assurance_task" } = {},
) {
  const payload = envelope(raw, expectedProjectId, path);
  const task = normalizeAssuranceTask(payload.task, {
    projectId: expectedProjectId,
    path: `${path}.task`,
  });
  if (taskId && task.task_id !== taskId) fail(`${path}.task.task_id`, "does not match the requested task");
  return { ...payload, project_id: String(expectedProjectId).trim(), task };
}

export function normalizeAssuranceReadinessPayload(
  raw,
  { projectId: expectedProjectId, taskId, expectedVersion = 0, path = "assurance_readiness" } = {},
) {
  const payload = normalizeEvidenceEnvelope(raw, {
    projectId: expectedProjectId,
    taskId,
    path,
  });
  const mode = requiredText(payload.mode, `${path}.mode`);
  if (!ASSURANCE_MODES.has(mode)) fail(`${path}.mode`, `has unsupported value ${mode}`);
  const status = requiredText(payload.status, `${path}.status`);
  if (!ASSURANCE_STATUSES.has(status)) fail(`${path}.status`, `has unsupported value ${status}`);
  const version = positiveInteger(payload.version, `${path}.version`);
  if (expectedVersion > 0 && version !== expectedVersion) fail(`${path}.version`, "does not match the selected task version");
  const gaps = array(payload.gaps, `${path}.gaps`).map((gap, index) => requiredText(gap, `${path}.gaps[${index}]`));
  if (new Set(gaps).size !== gaps.length) fail(`${path}.gaps`, "must contain unique values");
  return {
    ...payload,
    project_id: String(expectedProjectId).trim(),
    task_id: String(taskId).trim(),
    mode,
    status,
    version,
    ready: strictBoolean(payload.ready, `${path}.ready`),
    frozen_identity_ok: strictBoolean(payload.frozen_identity_ok, `${path}.frozen_identity_ok`),
    gaps,
  };
}

function normalizeEvidenceEnvelope(raw, { projectId: expectedProjectId, taskId, path }) {
  const payload = envelope(raw, expectedProjectId, path);
  const actualTaskId = requiredText(payload.task_id, `${path}.task_id`);
  if (actualTaskId !== taskId) fail(`${path}.task_id`, "does not match the selected task");
  return payload;
}

export function normalizeAssuranceProofPayload(
  raw,
  { projectId: expectedProjectId, taskId, path = "assurance_proof" } = {},
) {
  const payload = normalizeEvidenceEnvelope(raw, {
    projectId: expectedProjectId,
    taskId,
    path,
  });
  const proof = record(payload.proof, `${path}.proof`);
  projectId(proof.project_id, expectedProjectId, `${path}.proof.project_id`);
  if (requiredText(proof.task_id, `${path}.proof.task_id`) !== taskId) {
    fail(`${path}.proof.task_id`, "does not match the selected task");
  }
  requiredText(proof.proof_id, `${path}.proof.proof_id`);
  const provenanceStatus = requiredText(proof.provenance_status, `${path}.proof.provenance_status`);
  if (!ASSURANCE_EVIDENCE_PROVENANCE_STATUSES.has(provenanceStatus)) {
    fail(`${path}.proof.provenance_status`, "must be an accepted server evidence authority status");
  }
  for (const field of [
    "failures",
    "skips",
    "open_high_risk_count",
    "closed_risks_lacking_evidence_count",
  ]) {
    nonNegativeInteger(proof[field], `${path}.proof.${field}`);
  }
  for (const field of [
    "subject_reconciliation_ok",
    "site_reconciliation_ok",
    "trial_reconciliation_ok",
  ]) {
    strictBoolean(proof[field], `${path}.proof.${field}`);
  }
  return { ...payload, project_id: String(expectedProjectId).trim(), task_id: taskId, proof };
}

export function normalizeAssuranceRollupPayload(
  raw,
  { projectId: expectedProjectId, taskId, path = "assurance_rollup" } = {},
) {
  const payload = normalizeEvidenceEnvelope(raw, {
    projectId: expectedProjectId,
    taskId,
    path,
  });
  const rollup = record(payload.rollup, `${path}.rollup`);
  projectId(rollup.project_id, expectedProjectId, `${path}.rollup.project_id`);
  if (requiredText(rollup.task_id, `${path}.rollup.task_id`) !== taskId) {
    fail(`${path}.rollup.task_id`, "does not match the selected task");
  }
  requiredText(rollup.risk_snapshot_id, `${path}.rollup.risk_snapshot_id`);
  array(rollup.subject_rollup, `${path}.rollup.subject_rollup`);
  array(rollup.site_rollup, `${path}.rollup.site_rollup`);
  record(rollup.trial_rollup, `${path}.rollup.trial_rollup`);
  record(rollup.distributions, `${path}.rollup.distributions`);
  array(rollup.remediation_matrix, `${path}.rollup.remediation_matrix`);
  array(rollup.evidence_manifest, `${path}.rollup.evidence_manifest`);
  requiredText(rollup.content_sha256, `${path}.rollup.content_sha256`);
  return { ...payload, project_id: String(expectedProjectId).trim(), task_id: taskId, rollup };
}

export function normalizeAssuranceCreateResponse(
  raw,
  { projectId: expectedProjectId, mode = "", path = "assurance_create" } = {},
) {
  const payload = envelope(raw, expectedProjectId, path);
  if (payload.replayed !== undefined) strictBoolean(payload.replayed, `${path}.replayed`);
  const task = normalizeAssuranceTask(payload.task, {
    projectId: expectedProjectId,
    path: `${path}.task`,
  });
  if (mode && task.mode !== mode) fail(`${path}.task.mode`, "does not match the requested assurance mode");
  return { ...payload, project_id: String(expectedProjectId).trim(), task };
}

export function normalizeAssuranceAuditPayload(
  raw,
  { projectId: expectedProjectId, taskId, path = "assurance_audit" } = {},
) {
  const payload = normalizeEvidenceEnvelope(raw, {
    projectId: expectedProjectId,
    taskId,
    path,
  });
  const principalId = requiredText(payload.principal_id, `${path}.principal_id`);
  const items = array(payload.items, `${path}.items`).map((item, index) => (
    normalizeAssuranceAuditEvent(item, {
      projectId: expectedProjectId,
      taskId,
      path: `${path}.items[${index}]`,
    })
  ));
  const auditIds = new Set();
  const eventHashes = new Set();
  for (let index = 1; index < items.length; index += 1) {
    if (items[index].aggregate_version_before !== items[index - 1].aggregate_version_after) {
      fail(`${path}.items[${index}].aggregate_version_before`, "does not continue the returned task version chain");
    }
  }
  items.forEach((item, index) => {
    if (auditIds.has(item.audit_id)) fail(`${path}.items[${index}].audit_id`, "is duplicated");
    if (eventHashes.has(item.event_hash)) fail(`${path}.items[${index}].event_hash`, "is duplicated");
    auditIds.add(item.audit_id);
    eventHashes.add(item.event_hash);
  });
  return {
    ...payload,
    project_id: String(expectedProjectId).trim(),
    task_id: String(taskId).trim(),
    principal_id: principalId,
    items,
  };
}
