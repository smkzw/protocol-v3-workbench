import assert from "node:assert/strict";
import {
  MedicalMonitoringAssuranceShapeError,
  normalizeAssuranceCreateResponse,
  normalizeAssuranceAuditPayload,
  normalizeAssuranceProofPayload,
  normalizeAssuranceReadinessPayload,
  normalizeAssuranceRollupPayload,
  normalizeAssuranceTask,
  normalizeAssuranceTaskList,
  normalizeAssuranceTaskPayload,
} from "./medicalMonitoringAssuranceView.mjs";

let passed = 0;
function check(condition, message) {
  assert.ok(condition, message);
  passed += 1;
}
function expectShapeError(fn, message) {
  assert.throws(fn, MedicalMonitoringAssuranceShapeError, message);
  passed += 1;
}

const identity = Object.fromEntries([
  "batch_id",
  "batch_revision",
  "mapping_revision",
  "protocol_version_id",
  "rule_pack_revision",
  "dictionary_revision",
  "ctcae_revision",
  "model_revision",
  "risk_snapshot_id",
].map((field) => [field, `${field}-v1`]));

const task = {
  task_id: "assurance-1",
  project_id: "proj-rux",
  mode: "pre_lock",
  status: "running",
  version: 2,
  frozen_identity: identity,
  updated_at: "2026-08-02T00:00:00Z",
  medical_review_recorded: false,
};
const proof = {
  proof_id: "proof-1",
  project_id: "proj-rux",
  task_id: task.task_id,
  provenance_status: "server_evidence_run_ledger",
  failures: 0,
  skips: 0,
  open_high_risk_count: 1,
  closed_risks_lacking_evidence_count: 0,
  subject_reconciliation_ok: true,
  site_reconciliation_ok: true,
  trial_reconciliation_ok: true,
};
const rollup = {
  task_id: task.task_id,
  project_id: "proj-rux",
  risk_snapshot_id: "risk-snapshot-1",
  subject_rollup: [],
  site_rollup: [],
  trial_rollup: { total_risk_count: 0, risk_instance_ids: [] },
  distributions: { by_severity: {}, by_status: {}, by_disposition: {} },
  remediation_matrix: [],
  evidence_manifest: [],
  content_sha256: "a".repeat(64),
};
const readiness = {
  project_id: "proj-rux",
  task_id: task.task_id,
  mode: task.mode,
  status: task.status,
  version: task.version,
  ready: true,
  gaps: [],
  frozen_identity_ok: true,
};
const auditEvent = {
  schema_version: "monitoring_audit_contract_v1",
  audit_id: "audit-1",
  project_id: "proj-rux",
  principal_id: "medical-manager-1",
  role_claims: ["medical_manager"],
  matched_roles: ["medical_manager"],
  action: "create_assurance_task",
  target_type: "project",
  target_id: "proj-rux",
  source_revision: "b".repeat(64),
  authorization_decision_sha256: "c".repeat(64),
  decision_allowed: true,
  write_permitted: true,
  mutation_applied: true,
  aggregate_version_before: 0,
  aggregate_version_after: 1,
  occurred_at: "2026-08-02T00:00:00Z",
  prev_event_hash: "d".repeat(64),
  payload: { task_id: task.task_id, signature_evidence_sha256: "e".repeat(64) },
  event_hash: "f".repeat(64),
};
const auditEvent2 = {
  ...auditEvent,
  audit_id: "audit-2",
  action: "review_assurance",
  aggregate_version_before: 1,
  aggregate_version_after: 2,
  occurred_at: "2026-08-02T01:00:00Z",
  prev_event_hash: auditEvent.event_hash,
  event_hash: "1".repeat(64),
  payload: { task_id: task.task_id },
};

check(normalizeAssuranceTask(task, { projectId: "proj-rux" }).task_id === task.task_id, "validates a task identity and lifecycle");
check(normalizeAssuranceTaskList({ project_id: "proj-rux", items: [task] }, { projectId: "proj-rux", mode: "pre_lock" }).items.length === 1, "validates a project-scoped task list");
check(normalizeAssuranceTaskPayload({ project_id: "proj-rux", task }, { projectId: "proj-rux", taskId: task.task_id }).task.project_id === "proj-rux", "validates task detail identity");
check(normalizeAssuranceProofPayload({ project_id: "proj-rux", task_id: task.task_id, proof }, { projectId: "proj-rux", taskId: task.task_id }).proof.failures === 0, "validates full-recompute proof evidence");
check(normalizeAssuranceRollupPayload({ project_id: "proj-rux", task_id: task.task_id, rollup }, { projectId: "proj-rux", taskId: task.task_id }).rollup.content_sha256.length === 64, "validates pre-inspection rollup evidence");
check(normalizeAssuranceReadinessPayload({ project_id: "proj-rux", task_id: task.task_id, ...readiness }, { projectId: "proj-rux", taskId: task.task_id, expectedVersion: task.version }).ready, "validates readiness response before state commit");
check(normalizeAssuranceCreateResponse({ project_id: "proj-rux", replayed: false, task }, { projectId: "proj-rux", mode: "pre_lock" }).task.mode === "pre_lock", "validates task-creation response before state commit");
const normalizedAudit = normalizeAssuranceAuditPayload({ project_id: "proj-rux", task_id: task.task_id, principal_id: "medical-manager-1", items: [auditEvent, auditEvent2] }, { projectId: "proj-rux", taskId: task.task_id });
check(normalizedAudit.items.length === 2 && normalizedAudit.items[1].aggregate_version_after === 2, "validates ordered task audit events and version chain");
check(!Object.hasOwn(normalizedAudit.items[0], "payload"), "does not carry audit payload internals into the render model");

expectShapeError(() => normalizeAssuranceTaskList({ project_id: "other", items: [] }, { projectId: "proj-rux" }), "rejects a cross-project task list");
expectShapeError(() => normalizeAssuranceTaskList({ project_id: "proj-rux", items: "malformed" }, { projectId: "proj-rux" }), "rejects a scalar task collection");
expectShapeError(() => normalizeAssuranceTaskList({ project_id: "proj-rux", items: [{ ...task, mode: "pre_inspection" }] }, { projectId: "proj-rux", mode: "pre_lock" }), "rejects a task from another mode");
expectShapeError(() => normalizeAssuranceTask({ ...task, frozen_identity: { ...identity, risk_snapshot_id: "" } }, { projectId: "proj-rux" }), "rejects incomplete frozen identity");
expectShapeError(() => normalizeAssuranceTask({ ...task, version: "2" }, { projectId: "proj-rux" }), "rejects string task version");
expectShapeError(() => normalizeAssuranceTask({ ...task, medical_review_recorded: "false" }, { projectId: "proj-rux" }), "rejects string review flag");
expectShapeError(() => normalizeAssuranceTaskPayload({ project_id: "proj-rux", task: { ...task, task_id: "other" } }, { projectId: "proj-rux", taskId: task.task_id }), "rejects detail task identity drift");
expectShapeError(() => normalizeAssuranceProofPayload({ project_id: "proj-rux", task_id: task.task_id, proof: { ...proof, failures: true } }, { projectId: "proj-rux", taskId: task.task_id }), "rejects boolean proof counts");
expectShapeError(() => normalizeAssuranceProofPayload({ project_id: "proj-rux", task_id: task.task_id, proof: { ...proof, provenance_status: "mixed_provenance" } }, { projectId: "proj-rux", taskId: task.task_id }), "rejects mixed evidence provenance");
expectShapeError(() => normalizeAssuranceProofPayload({ project_id: "proj-rux", task_id: task.task_id, proof: { ...proof, provenance_status: "" } }, { projectId: "proj-rux", taskId: task.task_id }), "rejects missing evidence provenance");
expectShapeError(() => normalizeAssuranceProofPayload({ project_id: "proj-rux", task_id: task.task_id, proof: { ...proof, project_id: "other" } }, { projectId: "proj-rux", taskId: task.task_id }), "rejects cross-project proof");
expectShapeError(() => normalizeAssuranceRollupPayload({ project_id: "proj-rux", task_id: task.task_id, rollup: { ...rollup, site_rollup: "malformed" } }, { projectId: "proj-rux", taskId: task.task_id }), "rejects malformed rollup collections");
expectShapeError(() => normalizeAssuranceReadinessPayload({ project_id: "proj-rux", task_id: task.task_id, ...readiness, ready: "true" }, { projectId: "proj-rux", taskId: task.task_id }), "rejects string readiness flags");
expectShapeError(() => normalizeAssuranceReadinessPayload({ project_id: "proj-rux", task_id: task.task_id, ...readiness, gaps: ["gap-1", "gap-1"] }, { projectId: "proj-rux", taskId: task.task_id }), "rejects duplicate readiness gaps");
expectShapeError(() => normalizeAssuranceReadinessPayload({ project_id: "proj-rux", task_id: task.task_id, ...readiness, version: 3 }, { projectId: "proj-rux", taskId: task.task_id, expectedVersion: task.version }), "rejects readiness version drift");
expectShapeError(() => normalizeAssuranceRollupPayload({ project_id: "proj-rux", task_id: "other", rollup }, { projectId: "proj-rux", taskId: task.task_id }), "rejects rollup task drift");
expectShapeError(() => normalizeAssuranceCreateResponse({ project_id: "proj-rux", replayed: "false", task }, { projectId: "proj-rux", mode: "pre_lock" }), "rejects malformed replay flag");
expectShapeError(() => normalizeAssuranceAuditPayload({ project_id: "other", task_id: task.task_id, principal_id: "medical-manager-1", items: [] }, { projectId: "proj-rux", taskId: task.task_id }), "rejects cross-project audit response");
expectShapeError(() => normalizeAssuranceAuditPayload({ project_id: "proj-rux", task_id: "other", principal_id: "medical-manager-1", items: [auditEvent] }, { projectId: "proj-rux", taskId: task.task_id }), "rejects cross-task audit response");
expectShapeError(() => normalizeAssuranceAuditPayload({ project_id: "proj-rux", task_id: task.task_id, principal_id: "medical-manager-1", items: [{ ...auditEvent, payload: { session_id: "raw-session" } }] }, { projectId: "proj-rux", taskId: task.task_id }), "rejects sensitive audit payload fields");
expectShapeError(() => normalizeAssuranceAuditPayload({ project_id: "proj-rux", task_id: task.task_id, principal_id: "medical-manager-1", items: [{ ...auditEvent, action: "unknown_action" }] }, { projectId: "proj-rux", taskId: task.task_id }), "rejects unknown audit actions");
expectShapeError(() => normalizeAssuranceAuditPayload({ project_id: "proj-rux", task_id: task.task_id, principal_id: "medical-manager-1", items: [auditEvent, { ...auditEvent2, event_hash: auditEvent.event_hash }] }, { projectId: "proj-rux", taskId: task.task_id }), "rejects duplicate audit event hashes");

console.log(`medicalMonitoringAssuranceView: ${passed} passed`);
