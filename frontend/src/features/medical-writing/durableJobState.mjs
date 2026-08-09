/**
 * Durable job state machine + production controller helpers.
 * Imported by useDurableMwJob.js, App.jsx, writing-reference panels, and Node tests.
 *
 * Domain reconciliation is explicit: transport /result HTTP 200 is never enough
 * to clear a locator. Callers must acknowledge exact business artifacts.
 */

export const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
export const LOCATOR_VERSION = "mw_job_locator_v2";
export const GEN_CTX_VERSION = "mw_gen_ctx_v2";

export function isCompletedSuccess(status) {
  return status === "completed";
}

export function isTerminal(status) {
  return TERMINAL_STATUSES.has(status);
}

export function isValidLocator(locator) {
  if (!locator || typeof locator !== "object") return false;
  if (!locator.job_id || typeof locator.job_id !== "string") return false;
  if (!locator.project_id || typeof locator.project_id !== "string") return false;
  return true;
}

export function isV2Locator(locator) {
  return Boolean(locator && locator.version === LOCATOR_VERSION);
}

/**
 * Build a versioned locator before polling starts.
 */
export function buildLocator({
  projectId,
  jobId,
  operation,
  sectionId,
  jobType,
  runId,
  batchId,
  snapshotId,
  suggestionIds,
  threadId,
}) {
  return {
    version: LOCATOR_VERSION,
    project_id: projectId,
    job_id: jobId,
    operation: operation || "",
    section_id: sectionId || "",
    job_type: jobType || "",
    run_id: runId || "",
    batch_id: batchId || "",
    snapshot_id: snapshotId || "",
    thread_id: threadId || "",
    suggestion_ids: Array.isArray(suggestionIds) ? suggestionIds : [],
    persisted_at: Date.now(),
  };
}

/**
 * Only clear after terminal status AND successful domain reconciliation.
 * Transport-level /result success alone is never enough.
 * Cancelled without domain recon must retain the locator.
 */
export function shouldClearLocator(status, domainReconciled) {
  return isTerminal(status) && domainReconciled === true;
}

export function shouldBlockStart(currentJobStatus) {
  if (!currentJobStatus) return false;
  return !isTerminal(currentJobStatus);
}

/**
 * Block start for a specific operation key in a dual-job map.
 */
export function shouldBlockStartForOperation(jobsByOperation, operation) {
  const row = jobsByOperation && jobsByOperation[operation];
  return shouldBlockStart(row?.status);
}

export function extractArtifactThreadId(resultBody) {
  if (!resultBody || typeof resultBody !== "object") return null;
  const artifact = resultBody.artifact;
  if (artifact && artifact.thread_id) return String(artifact.thread_id);
  if (resultBody.thread_id) return String(resultBody.thread_id);
  return null;
}

export function extractArtifactSuggestionIds(resultBody) {
  if (!resultBody || typeof resultBody !== "object") return [];
  const artifact = resultBody.artifact || {};
  const ids = artifact.suggestion_ids || resultBody.suggestion_ids || [];
  return Array.isArray(ids) ? ids.map(String).filter(Boolean) : [];
}

export function extractArtifactPostThreadHash(resultBody) {
  if (!resultBody || typeof resultBody !== "object") return "";
  const artifact = resultBody.artifact || {};
  return String(artifact.post_thread_hash || resultBody.post_thread_hash || "");
}

export function extractArtifactGenerationContextVersion(resultBody) {
  if (!resultBody || typeof resultBody !== "object") return "";
  const artifact = resultBody.artifact || {};
  return String(
    artifact.generation_context_version
      || resultBody.generation_context_version
      || "",
  );
}

export function extractArtifactRunId(resultBody) {
  if (!resultBody || typeof resultBody !== "object") return "";
  const artifact = resultBody.artifact || {};
  return String(artifact.run_id || resultBody.run_id || "");
}

export function extractArtifactBatchId(resultBody) {
  if (!resultBody || typeof resultBody !== "object") return "";
  const artifact = resultBody.artifact || {};
  return String(artifact.batch_id || resultBody.batch_id || "");
}

export function extractArtifactSnapshotId(resultBody) {
  if (!resultBody || typeof resultBody !== "object") return "";
  const artifact = resultBody.artifact || {};
  return String(artifact.snapshot_id || resultBody.snapshot_id || "");
}

/**
 * Transport poll outcome from status + whether /result was fetched.
 * domainReconciled defaults false until domain ack.
 */
export function classifyPollOutcome(status, domainReconciled) {
  if (isCompletedSuccess(status) && domainReconciled) return "success";
  if ((status === "failed" || status === "cancelled") && domainReconciled) {
    return "terminal_failure";
  }
  if (isTerminal(status) && !domainReconciled) return "reconcile_failed";
  return "retain";
}

/**
 * Decide cleanup after transport + domain reconciliation.
 * Never treats cancelled-without-domain as clearable.
 */
export function decideLocatorCleanup({ status, domainReconciled }) {
  const shouldClear = shouldClearLocator(status, domainReconciled === true);
  const outcome = classifyPollOutcome(status, domainReconciled === true);
  return { shouldClear, outcome };
}

export function buildTerminalPayload(status, resultBody, errorSummary) {
  return {
    status,
    result: resultBody,
    error: errorSummary || "",
  };
}

export function isStaleCompletion(locator, currentProjectId, currentSectionId) {
  if (!locator) return false;
  if (locator.project_id !== currentProjectId) return true;
  if (currentSectionId && locator.section_id && locator.section_id !== currentSectionId) {
    return true;
  }
  return false;
}

/**
 * Screen generation token: suppress mutations after project/section switch.
 */
export function createScreenGeneration(projectId, sectionId = "") {
  return {
    projectId: projectId || "",
    sectionId: sectionId || "",
    seq: Date.now(),
  };
}

export function isScreenGenerationCurrent(token, currentProjectId, currentSectionId = "") {
  if (!token) return false;
  if (token.projectId !== currentProjectId) return false;
  if (token.sectionId && currentSectionId && token.sectionId !== currentSectionId) {
    return false;
  }
  return true;
}

/**
 * After durable retry, prefer any replacement job_id from the response body.
 * Preserves full locator context via mergeRetryLocator.
 */
export function resolveRetryJobId(previousJobId, retryBody) {
  if (retryBody && typeof retryBody === "object") {
    const next = retryBody.job_id || retryBody.durable_job_id;
    if (next) return String(next);
  }
  return previousJobId;
}

export function mergeRetryLocator(previousLocator, nextJobId, projectId) {
  const base = previousLocator && typeof previousLocator === "object" ? previousLocator : {};
  return buildLocator({
    projectId: projectId || base.project_id || "",
    jobId: nextJobId,
    operation: base.operation || "",
    sectionId: base.section_id || "",
    jobType: base.job_type || "",
    runId: base.run_id || "",
    batchId: base.batch_id || "",
    snapshotId: base.snapshot_id || "",
    suggestionIds: base.suggestion_ids || [],
    threadId: base.thread_id || "",
  });
}

/**
 * Exact revision/rewrite artifact validation for v2 locators/results.
 * Missing exact lineage is reconciliation failure — no fallback guessing.
 * Legacy (non-v2) locators may use optional thread fallback only when explicitly allowed.
 */
export function validateRevisionArtifactExact(resultBody, locator = null, opts = {}) {
  const requireSuggestions = opts.requireSuggestions !== false;
  const allowLegacyFallback = opts.allowLegacyFallback === true;
  const isV2 = isV2Locator(locator)
    || extractArtifactGenerationContextVersion(resultBody) === GEN_CTX_VERSION
    || (locator && locator.version === LOCATOR_VERSION);

  const threadId = extractArtifactThreadId(resultBody);
  const suggestionIds = extractArtifactSuggestionIds(resultBody);
  const postHash = extractArtifactPostThreadHash(resultBody);

  if (isV2 || !allowLegacyFallback) {
    if (!threadId) {
      return { ok: false, reason: "missing_exact_thread_id", threadId: null, suggestionIds: [], postHash: "" };
    }
    if (requireSuggestions && suggestionIds.length === 0) {
      return { ok: false, reason: "missing_exact_suggestion_ids", threadId, suggestionIds: [], postHash };
    }
    return { ok: true, reason: "", threadId, suggestionIds, postHash };
  }

  // Legacy-only path (unreachable for v2 locators).
  const legacyThread = threadId || (locator && locator.thread_id) || null;
  if (!legacyThread) {
    return { ok: false, reason: "legacy_missing_thread", threadId: null, suggestionIds: [], postHash: "" };
  }
  return { ok: true, reason: "legacy", threadId: String(legacyThread), suggestionIds, postHash };
}

/**
 * Domain reconcile revision thread against exact artifact IDs.
 * domainThread must be the exact loaded business object (or null).
 */
export function acknowledgeRevisionDomain({
  status,
  resultBody,
  locator,
  domainThread,
  currentProjectId,
  currentSectionId,
  screenGeneration,
}) {
  if (screenGeneration && !isScreenGenerationCurrent(screenGeneration, currentProjectId, currentSectionId)) {
    return {
      domainReconciled: false,
      outcome: "stale_screen",
      shouldClear: false,
      reason: "stale_screen",
      threadId: null,
      suggestionIds: [],
    };
  }
  if (locator && isStaleCompletion(locator, currentProjectId, currentSectionId)) {
    return {
      domainReconciled: false,
      outcome: "stale_screen",
      shouldClear: false,
      reason: "stale_locator_context",
      threadId: null,
      suggestionIds: [],
    };
  }

  if (!isTerminal(status)) {
    return {
      domainReconciled: false,
      outcome: "retain",
      shouldClear: false,
      reason: "non_terminal",
      threadId: null,
      suggestionIds: [],
    };
  }

  if (status === "failed" || status === "cancelled") {
    // Terminal failure: domain recon requires transport result body present
    // (caller only passes resultBody when /result succeeded). No exact
    // suggestion required for failed/cancelled, but no clear without body.
    const domainReconciled = resultBody != null && typeof resultBody === "object";
    const { shouldClear, outcome } = decideLocatorCleanup({ status, domainReconciled });
    return {
      domainReconciled,
      outcome,
      shouldClear,
      reason: domainReconciled ? "terminal_failure_acked" : "terminal_without_result",
      threadId: null,
      suggestionIds: [],
    };
  }

  // completed
  const exact = validateRevisionArtifactExact(resultBody, locator, { requireSuggestions: true });
  if (!exact.ok) {
    return {
      domainReconciled: false,
      outcome: "reconcile_failed",
      shouldClear: false,
      reason: exact.reason,
      threadId: null,
      suggestionIds: [],
    };
  }
  if (!domainThread || domainThread.thread_id !== exact.threadId) {
    return {
      domainReconciled: false,
      outcome: "reconcile_failed",
      shouldClear: false,
      reason: "thread_not_found_or_mismatch",
      threadId: exact.threadId,
      suggestionIds: exact.suggestionIds,
    };
  }
  const present = new Set((domainThread.suggestions || []).map((s) => String(s.suggestion_id)));
  if (exact.suggestionIds.some((id) => !present.has(id))) {
    return {
      domainReconciled: false,
      outcome: "reconcile_failed",
      shouldClear: false,
      reason: "suggestion_ids_not_on_thread",
      threadId: exact.threadId,
      suggestionIds: exact.suggestionIds,
    };
  }
  return {
    domainReconciled: true,
    outcome: "success",
    shouldClear: shouldClearLocator(status, true),
    reason: "exact_artifact_ok",
    threadId: exact.threadId,
    suggestionIds: exact.suggestionIds,
  };
}

export function acknowledgeTriageDomain({
  status,
  resultBody,
  locator,
  expectedRunId,
  expectedSnapshotId,
}) {
  if (!isTerminal(status)) {
    return { domainReconciled: false, outcome: "retain", shouldClear: false, reason: "non_terminal" };
  }
  if (status === "failed" || status === "cancelled") {
    const domainReconciled = resultBody != null && typeof resultBody === "object";
    const { shouldClear, outcome } = decideLocatorCleanup({ status, domainReconciled });
    return { domainReconciled, outcome, shouldClear, reason: domainReconciled ? "terminal_failure_acked" : "terminal_without_result" };
  }
  if (!resultBody) {
    return { domainReconciled: false, outcome: "reconcile_failed", shouldClear: false, reason: "missing_result" };
  }
  const runId = extractArtifactRunId(resultBody);
  const snapshotId = extractArtifactSnapshotId(resultBody);
  const expectRun = expectedRunId || locator?.run_id || "";
  const expectSnap = expectedSnapshotId || locator?.snapshot_id || "";
  if (expectRun && runId && expectRun !== runId) {
    return { domainReconciled: false, outcome: "reconcile_failed", shouldClear: false, reason: "run_id_mismatch" };
  }
  if (expectSnap && snapshotId && expectSnap !== snapshotId) {
    return { domainReconciled: false, outcome: "reconcile_failed", shouldClear: false, reason: "snapshot_id_mismatch" };
  }
  // completed: require at least run or snapshot identity when expected
  if (expectRun && !runId) {
    return { domainReconciled: false, outcome: "reconcile_failed", shouldClear: false, reason: "missing_run_id" };
  }
  return {
    domainReconciled: true,
    outcome: "success",
    shouldClear: shouldClearLocator(status, true),
    reason: "triage_exact_ok",
    runId,
    snapshotId,
  };
}

export function acknowledgeTranslationDomain({
  status,
  resultBody,
  locator,
  expectedBatchId,
  expectedSnapshotId,
}) {
  if (!isTerminal(status)) {
    return { domainReconciled: false, outcome: "retain", shouldClear: false, reason: "non_terminal" };
  }
  if (status === "failed" || status === "cancelled") {
    const domainReconciled = resultBody != null && typeof resultBody === "object";
    const { shouldClear, outcome } = decideLocatorCleanup({ status, domainReconciled });
    return { domainReconciled, outcome, shouldClear, reason: domainReconciled ? "terminal_failure_acked" : "terminal_without_result" };
  }
  if (!resultBody) {
    return { domainReconciled: false, outcome: "reconcile_failed", shouldClear: false, reason: "missing_result" };
  }
  const batchId = extractArtifactBatchId(resultBody);
  const snapshotId = extractArtifactSnapshotId(resultBody);
  const expectBatch = expectedBatchId || locator?.batch_id || "";
  const expectSnap = expectedSnapshotId || locator?.snapshot_id || "";
  if (expectBatch && batchId && expectBatch !== batchId) {
    return { domainReconciled: false, outcome: "reconcile_failed", shouldClear: false, reason: "batch_id_mismatch" };
  }
  if (expectSnap && snapshotId && expectSnap !== snapshotId) {
    return { domainReconciled: false, outcome: "reconcile_failed", shouldClear: false, reason: "snapshot_id_mismatch" };
  }
  if (expectBatch && !batchId) {
    return { domainReconciled: false, outcome: "reconcile_failed", shouldClear: false, reason: "missing_batch_id" };
  }
  return {
    domainReconciled: true,
    outcome: "success",
    shouldClear: shouldClearLocator(status, true),
    reason: "translation_exact_ok",
    batchId,
    snapshotId,
  };
}

/**
 * Dual-operation job map helpers (initial + rewrite independent).
 */
export function emptyRevisionJobMap() {
  return { initial: null, rewrite: null };
}

export function setOperationJob(map, operation, jobState) {
  const next = { ...(map || emptyRevisionJobMap()) };
  next[operation] = jobState;
  return next;
}

export function clearOperationJob(map, operation) {
  return setOperationJob(map, operation, null);
}

export function pickFocusedRevisionJob(map) {
  const m = map || emptyRevisionJobMap();
  if (m.rewrite && shouldBlockStart(m.rewrite.status)) return m.rewrite;
  if (m.initial && shouldBlockStart(m.initial.status)) return m.initial;
  if (m.rewrite) return m.rewrite;
  if (m.initial) return m.initial;
  return null;
}

/**
 * Production controller adapter used by Node tests and production callers.
 * Pure decision surface — no React, no fetch.
 */
export const durableJobController = {
  LOCATOR_VERSION,
  GEN_CTX_VERSION,
  buildLocator,
  shouldClearLocator,
  shouldBlockStart,
  shouldBlockStartForOperation,
  classifyPollOutcome,
  decideLocatorCleanup,
  isStaleCompletion,
  createScreenGeneration,
  isScreenGenerationCurrent,
  resolveRetryJobId,
  mergeRetryLocator,
  validateRevisionArtifactExact,
  acknowledgeRevisionDomain,
  acknowledgeTriageDomain,
  acknowledgeTranslationDomain,
  emptyRevisionJobMap,
  setOperationJob,
  clearOperationJob,
  pickFocusedRevisionJob,
  extractArtifactThreadId,
  extractArtifactSuggestionIds,
  extractArtifactPostThreadHash,
  extractArtifactRunId,
  extractArtifactBatchId,
  extractArtifactSnapshotId,
};

export default durableJobController;
