import assert from "node:assert/strict";
import {
  ASSURANCE_MODES,
  ASSURANCE_EVIDENCE_PROVENANCE_STATUSES,
  FROZEN_IDENTITY_FIELDS,
  assuranceEvidenceState,
  assuranceEvidenceProvenanceState,
  assuranceActionAvailability,
  assuranceReadinessInput,
  assuranceReadinessPayload,
  assuranceReadinessState,
  assuranceModeLabel,
  assuranceModeDescription,
  assuranceModeMonitoringId,
  assuranceStatusLabel,
  assuranceStatusTone,
  assuranceTaskCreationAllowed,
  assuranceTaskDisplayKey,
  assuranceTaskList,
  completeFrozenIdentity,
  missingFrozenIdentityFields,
} from "./medicalMonitoringAssurance.mjs";
import { createMedicalMonitoringAssuranceApi } from "./medicalMonitoringAssuranceApi.mjs";

let passed = 0;
function check(condition, message) {
  assert.ok(condition, message);
  passed += 1;
}

const identity = Object.fromEntries(FROZEN_IDENTITY_FIELDS.map((field) => [field, `${field}-v1`]));
check(ASSURANCE_MODES.join(",") === "pre_lock,pre_inspection", "declares both P8 assurance modes");
check(completeFrozenIdentity(identity), "accepts a complete frozen identity");
check(!completeFrozenIdentity({ ...identity, risk_snapshot_id: "" }), "rejects an incomplete frozen identity");
check(!assuranceTaskCreationAllowed(identity, false), "keeps task creation blocked without explicit authority write permission");
check(assuranceTaskCreationAllowed(identity, true), "allows task creation only with complete identity and explicit authority permission");
check(missingFrozenIdentityFields({ ...identity, rule_pack_revision: "" }).join(",") === "rule_pack_revision", "reports missing identity fields");
check(assuranceModeLabel("pre_lock") === "锁库前保障", "labels pre-lock mode");
check(assuranceModeLabel("pre_inspection") === "核查前保障", "labels pre-inspection mode");
check(assuranceModeMonitoringId("pre_lock") === "pre_lock_total", "binds pre-lock to the commercial total mode");
check(assuranceModeMonitoringId("pre_inspection") === "post_lock_fixed_total", "binds pre-inspection to the fixed-total mode");
check(assuranceModeDescription("pre_inspection").includes("固定总量"), "surfaces fixed-total semantics for pre-inspection");
check(assuranceStatusLabel("running") === "执行中", "labels running status");
check(assuranceStatusTone("blocked") === "danger", "marks blocked status as dangerous");

const tasks = assuranceTaskList([
  {
    task_id: "task-old",
    mode: "pre_inspection",
    status: "draft",
    version: 1,
    updated_at: "2026-08-01T00:00:00Z",
  },
  {
    task_id: "task-new",
    mode: "pre_lock",
    status: "running",
    version: 2,
    updated_at: "2026-08-02T00:00:00Z",
    frozen_identity: identity,
    medical_review_recorded: true,
  },
]);
check(tasks.length === 2 && tasks[0].id === "task-new", "sorts assurance tasks by latest update");
check(tasks[0].identityReady && tasks[0].medicalReviewRecorded, "preserves identity and medical review state");
const duplicateTasks = assuranceTaskList([
  { task_id: "duplicate-task", mode: "pre_lock", status: "draft", version: 1, updated_at: "2026-08-03T00:00:00Z" },
  { task_id: "duplicate-task", mode: "pre_lock", status: "running", version: 2, updated_at: "2026-08-04T00:00:00Z" },
]);
check(duplicateTasks.every((task) => task.identityState === "duplicate"), "marks duplicate assurance task ids as ambiguous");
check(assuranceTaskDisplayKey(duplicateTasks[0], 0) !== assuranceTaskDisplayKey(duplicateTasks[1], 1), "uses source-index display keys for duplicate assurance tasks");
check(
  assuranceEvidenceState({ task: { mode: "pre_lock" }, proof: { provenance_status: ASSURANCE_EVIDENCE_PROVENANCE_STATUSES.SERVER_EVIDENCE_RUN_LEDGER, failures: 0, skips: 0, subject_reconciliation_ok: true, site_reconciliation_ok: true, trial_reconciliation_ok: true } }).ready,
  "accepts a clean pre-lock proof",
);
check(
  !assuranceEvidenceState({ task: { mode: "pre_lock" }, proof: { provenance_status: ASSURANCE_EVIDENCE_PROVENANCE_STATUSES.SERVER_EVIDENCE_RUN_LEDGER, failures: 1, skips: 0, subject_reconciliation_ok: true, site_reconciliation_ok: true, trial_reconciliation_ok: true } }).ready,
  "blocks a pre-lock proof with failures",
);
check(
  !assuranceEvidenceState({ task: { mode: "pre_lock" }, proof: { provenance_status: ASSURANCE_EVIDENCE_PROVENANCE_STATUSES.SERVER_EVIDENCE_RUN_LEDGER, failures: false, skips: 0, subject_reconciliation_ok: true, site_reconciliation_ok: true, trial_reconciliation_ok: true } }).ready,
  "blocks a pre-lock proof with a boolean failure count",
);
check(
  !assuranceEvidenceState({ task: { mode: "pre_lock" }, proof: { provenance_status: ASSURANCE_EVIDENCE_PROVENANCE_STATUSES.SERVER_EVIDENCE_RUN_LEDGER, failures: 0, skips: "", subject_reconciliation_ok: true, site_reconciliation_ok: true, trial_reconciliation_ok: true } }).ready,
  "blocks a pre-lock proof with a blank skip count",
);
check(
  assuranceEvidenceProvenanceState({ provenance_status: ASSURANCE_EVIDENCE_PROVENANCE_STATUSES.SIGNED_MANIFEST_SERVER_REVALIDATED }).ready,
  "accepts the future signed-manifest authority only after server revalidation is declared",
);
check(
  !assuranceEvidenceState({ task: { mode: "pre_lock" }, proof: { provenance_status: "mixed_provenance", failures: 0, skips: 0, subject_reconciliation_ok: true, site_reconciliation_ok: true, trial_reconciliation_ok: true } }).ready,
  "blocks mixed-provenance proof even when counts and reconciliation are clean",
);
check(
  assuranceEvidenceState({ task: { mode: "pre_lock" }, proof: { failures: 0, skips: 0, subject_reconciliation_ok: true, site_reconciliation_ok: true, trial_reconciliation_ok: true } }).blockingReason.includes("权威"),
  "blocks proof with no declared evidence authority",
);
const cleanPreInspectionRollup = {
  risk_snapshot_id: "snapshot-1",
  subject_rollup: [],
  site_rollup: [],
  trial_rollup: {
    total_risk_count: 0,
    closed_risks_lacking_evidence_count: 0,
    risk_instance_ids: [],
  },
  distributions: {},
  remediation_matrix: [],
  evidence_manifest: [],
  content_sha256: "a".repeat(64),
};
check(
  assuranceEvidenceState({ task: { mode: "pre_inspection" }, rollup: cleanPreInspectionRollup }).ready,
  "accepts a conserved pre-inspection rollup with closure evidence counts",
);
check(
  !assuranceEvidenceState({
    task: { mode: "pre_inspection" },
    rollup: {
      ...cleanPreInspectionRollup,
      trial_rollup: { ...cleanPreInspectionRollup.trial_rollup, total_risk_count: 1, risk_instance_ids: ["risk-1"] },
    },
  }).ready,
  "blocks a pre-inspection rollup with non-conserved risk identities",
);
check(
  assuranceEvidenceState({
    task: { mode: "pre_inspection" },
    rollup: {
      ...cleanPreInspectionRollup,
      trial_rollup: { ...cleanPreInspectionRollup.trial_rollup, closed_risks_lacking_evidence_count: 1 },
    },
  }).blockingReason.includes("关闭依据"),
  "reports missing closure evidence instead of promoting the rollup",
);
check(
  !assuranceEvidenceState({ task: { mode: "pre_inspection" }, rollup: { site_rollup: [] } }).ready,
  "blocks an incomplete pre-inspection rollup payload",
);
const readinessInput = assuranceReadinessInput({
  currentSnapshot: {
    subjects_evaluated: 4,
    rollup: { sites: [{ scope_id: "site-1" }, { scope_id: "site-2" }] },
    assurance_readiness: { planned_subjects: 4, planned_sites: 2 },
  },
  currentIdentity: identity,
  task: { version: 2 },
});
check(readinessInput.available && readinessInput.actual_subjects === 4 && readinessInput.actual_sites === 2, "builds readiness counts from explicit snapshot and rollup facts");
check(readinessInput.planned_subjects === 4 && readinessInput.planned_sites === 2, "preserves optional planned coverage counts");
check(!Object.hasOwn(assuranceReadinessPayload(readinessInput), "missingFields") && !Object.hasOwn(assuranceReadinessPayload(readinessInput), "available"), "strips local readiness metadata before the strict backend request");
check(
  assuranceReadinessState({ input: readinessInput, readiness: { ready: true, gaps: [] } }).ready,
  "promotes only a server-returned ready state",
);
const incompleteReadinessInput = assuranceReadinessInput({ task: { version: 2 }, currentIdentity: identity });
check(!incompleteReadinessInput.available && incompleteReadinessInput.missingFields.includes("actual_sites"), "does not guess missing coverage as zero");
check(!assuranceReadinessState({ input: incompleteReadinessInput }).ready, "keeps readiness visibly blocked when coverage is missing");
const actionTask = tasks[1];
const actionBlocked = assuranceActionAvailability({ task: actionTask, evidenceReady: false, readinessReady: false });
check(!actionBlocked.canRecordEvidence && actionBlocked.baseBlockers.includes("服务端认证 principal 未就绪"), "blocks assurance writes without a verified principal");
const actionEvidence = assuranceActionAvailability({
  task: actionTask,
  principalReady: true,
  authorityWritePermitted: true,
  evidenceReady: false,
  readinessReady: false,
});
check(actionEvidence.canRecordEvidence && !actionEvidence.canReview, "allows only evidence generation before evidence exists");
const actionUntrustedEvidence = assuranceActionAvailability({
  task: actionTask,
  principalReady: true,
  authorityWritePermitted: true,
  evidenceReady: false,
  evidenceRecorded: true,
  evidenceBlockingReason: "证据来源混合，不能作为全量重算完成证明。",
  readinessReady: false,
});
check(!actionUntrustedEvidence.canRecordEvidence && actionUntrustedEvidence.evidenceBlocker.includes("来源混合"), "does not offer re-recording for a present but non-authoritative proof");
const actionReview = assuranceActionAvailability({
  task: actionTask,
  principalReady: true,
  authorityWritePermitted: true,
  evidenceReady: true,
  readinessReady: false,
});
check(actionReview.canReview && !actionReview.canComplete, "requires medical review and readiness before completion");
const actionComplete = assuranceActionAvailability({
  task: { ...actionTask, medical_review_recorded: true },
  principalReady: true,
  authorityWritePermitted: true,
  evidenceReady: true,
  readinessReady: true,
});
check(actionComplete.canComplete, "opens completion only after evidence, review and readiness gates");

const calls = [];
const api = createMedicalMonitoringAssuranceApi({
  fetchImpl: async (path, options = {}) => {
    calls.push({ path, options });
    return { ok: true, status: 200, json: async () => ({ project_id: "proj", items: [] }) };
  },
});
await api.listTasks("proj/with space", { mode: "pre_lock" });
await api.getProof("proj", "task-1");
const auditSignal = { aborted: false };
await api.getAudit("proj", "task-1", { signal: auditSignal });
await api.evaluateReadiness("proj", "task-1", { expected_version: 2, current_identity: identity });
await api.recordFullRecomputeProof("proj", "task-1", { expected_version: 2, idempotency_key: "proof-1", actor: "medical_manager", proof_payload: { failures: 0 } });
await api.generateRollups("proj", "task-1", { expected_version: 2, idempotency_key: "rollup-1", actor: "medical_manager" });
await api.recordMedicalReview("proj", "task-1", { expected_version: 2, idempotency_key: "review-1", actor: "medical_manager", review_payload: { conclusion: "confirmed" } });
await api.completeTask("proj", "task-1", { expected_version: 2, idempotency_key: "complete-1", confirmed_by: "medical_manager", reauthenticated: true, signature_evidence_sha256: "a".repeat(64) });
await api.createTask("proj", { mode: "pre_lock", frozen_identity: identity, idempotency_key: "key" });
check(calls[0].path.includes("proj%2Fwith%20space") && calls[0].path.endsWith("?mode=pre_lock"), "encodes project and mode in task listing");
check(calls[1].path.endsWith("/task-1/full-recompute-proof"), "builds proof endpoint path");
check(calls[2].path.endsWith("/task-1/audit") && calls[2].options.signal === auditSignal && !calls[2].options.method, "builds read-only audit endpoint with caller cancellation signal");
const readinessCall = calls.find((call) => call.path.endsWith("/task-1/readiness"));
check(readinessCall?.options.method === "POST" && readinessCall.options.headers["Content-Type"] === "application/json", "uses the read-only readiness contract with explicit JSON POST");
const createCall = calls.find((call) => call.path.endsWith("/monitoring/assurance/tasks"));
check(createCall?.options.method === "POST" && createCall.options.headers["Content-Type"] === "application/json", "uses JSON POST only for explicit task creation");
const actionCalls = calls.filter((call) => call.options.method === "POST" && /\/tasks\/task-1\/(full-recompute-proof|rollups|medical-review|complete)$/.test(call.path));
check(actionCalls.length === 4 && actionCalls.every((call) => call.options.method === "POST"), "exposes all four server-backed assurance action routes as JSON POST");
check(actionCalls.every((call) => !Object.hasOwn(JSON.parse(call.options.body), "actor") && !Object.hasOwn(JSON.parse(call.options.body), "confirmed_by")), "strips client identity fields from assurance action payloads");

console.log(`medicalMonitoringAssurance: ${passed} passed`);
