/**
 * Production-imported durable job controller behavior tests.
 * Run: node frontend/src/features/medical-writing/durableJobState.test.mjs
 */
import assert from "node:assert/strict";
import {
  TERMINAL_STATUSES,
  LOCATOR_VERSION,
  GEN_CTX_VERSION,
  isCompletedSuccess,
  isTerminal,
  isValidLocator,
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
  durableJobController,
} from "./durableJobState.mjs";

let passed = 0;
function check(cond, msg) {
  assert.ok(cond, msg);
  passed += 1;
}

// --- basic helpers ---
check(isCompletedSuccess("completed"), "completed success");
check(!isCompletedSuccess("failed"), "failed not success");
check(isTerminal("cancelled"), "cancelled terminal");
check(TERMINAL_STATUSES.has("failed"), "failed in set");

const locator = buildLocator({
  projectId: "p1",
  jobId: "j1",
  operation: "initial",
  sectionId: "sec1",
  jobType: "section_ai_candidate",
});
check(locator.version === LOCATOR_VERSION, "locator version v2");
check(isValidLocator(locator), "valid locator");

// 1. Cancel without domain recon must NOT clear
check(shouldClearLocator("cancelled", false) === false, "cancel without domain retains");
check(shouldClearLocator("cancelled", true) === true, "cancel with domain clears");
check(
  decideLocatorCleanup({ status: "cancelled", domainReconciled: false }).shouldClear === false,
  "decideLocatorCleanup cancel no domain",
);
check(
  classifyPollOutcome("cancelled", false) === "reconcile_failed",
  "cancelled without domain is reconcile_failed",
);

// 2. Stale screen generation
const gen = createScreenGeneration("p1", "sec1");
check(isScreenGenerationCurrent(gen, "p1", "sec1"), "generation current");
check(!isScreenGenerationCurrent(gen, "p2", "sec1"), "project switch stale");
check(!isScreenGenerationCurrent(gen, "p1", "secB"), "section switch stale");
check(isStaleCompletion(locator, "p2", "sec1"), "stale project locator");
check(isStaleCompletion(locator, "p1", "secOther"), "stale section locator");

// 3. v2 exact artifact — no fallback guessing
const v2Result = {
  artifact: {
    thread_id: "th1",
    suggestion_ids: ["s1", "s2"],
    post_thread_hash: "a".repeat(64),
    generation_context_version: GEN_CTX_VERSION,
  },
};
const exactOk = validateRevisionArtifactExact(v2Result, locator);
check(exactOk.ok === true, "v2 exact ok");
check(exactOk.threadId === "th1", "exact thread");

const missingThread = validateRevisionArtifactExact({ artifact: { suggestion_ids: ["s1"] } }, locator);
check(missingThread.ok === false, "v2 missing thread fails");
check(missingThread.reason === "missing_exact_thread_id", "missing thread reason");

const missingSug = validateRevisionArtifactExact({ artifact: { thread_id: "th1" } }, locator);
check(missingSug.ok === false, "v2 missing suggestions fails");

// Legacy fallback only when allowLegacyFallback and non-v2 locator
const legacyLoc = { job_id: "j", project_id: "p", thread_id: "legacy_th" };
const legacy = validateRevisionArtifactExact({}, legacyLoc, { allowLegacyFallback: true });
check(legacy.ok === true && legacy.threadId === "legacy_th", "legacy fallback only when allowed");
const noLegacy = validateRevisionArtifactExact({}, locator, { allowLegacyFallback: true });
check(noLegacy.ok === false, "v2 locator never uses legacy fallback");

// 4. Dual-job map independence
let map = emptyRevisionJobMap();
map = setOperationJob(map, "initial", { job_id: "ji", status: "running", operation: "initial" });
map = setOperationJob(map, "rewrite", { job_id: "jr", status: "queued", operation: "rewrite" });
check(map.initial.job_id === "ji" && map.rewrite.job_id === "jr", "dual ops independent");
check(shouldBlockStartForOperation(map, "initial") === true, "block initial while running");
check(shouldBlockStartForOperation(map, "rewrite") === true, "block rewrite while queued");
const focused = pickFocusedRevisionJob(map);
check(focused.job_id === "jr" || focused.job_id === "ji", "focused picks busy op");
map = clearOperationJob(map, "initial");
check(map.initial === null && map.rewrite.job_id === "jr", "clear one op only");

// 5. Domain recon required for cleanup
const domainOk = acknowledgeRevisionDomain({
  status: "completed",
  resultBody: v2Result,
  locator,
  domainThread: {
    thread_id: "th1",
    suggestions: [{ suggestion_id: "s1" }, { suggestion_id: "s2" }],
  },
  currentProjectId: "p1",
  currentSectionId: "sec1",
  screenGeneration: gen,
});
check(domainOk.domainReconciled === true && domainOk.shouldClear === true, "domain success clears");

const domainNoThread = acknowledgeRevisionDomain({
  status: "completed",
  resultBody: v2Result,
  locator,
  domainThread: null,
  currentProjectId: "p1",
  currentSectionId: "sec1",
  screenGeneration: gen,
});
check(domainNoThread.shouldClear === false, "missing domain thread retains");
check(domainNoThread.outcome === "reconcile_failed", "missing thread reconcile_failed");

const cancelNoResult = acknowledgeRevisionDomain({
  status: "cancelled",
  resultBody: null,
  locator,
  domainThread: null,
  currentProjectId: "p1",
  currentSectionId: "sec1",
  screenGeneration: gen,
});
check(cancelNoResult.shouldClear === false, "cancel without result retains");
check(cancelNoResult.domainReconciled === false, "cancel without result not domain-acked");

const cancelWithResult = acknowledgeRevisionDomain({
  status: "cancelled",
  resultBody: { status: "cancelled" },
  locator,
  domainThread: null,
  currentProjectId: "p1",
  currentSectionId: "sec1",
  screenGeneration: gen,
});
check(cancelWithResult.shouldClear === true, "cancel with result can clear");

// Stale screen suppresses mutation/cleanup
const staleAck = acknowledgeRevisionDomain({
  status: "completed",
  resultBody: v2Result,
  locator,
  domainThread: { thread_id: "th1", suggestions: [{ suggestion_id: "s1" }, { suggestion_id: "s2" }] },
  currentProjectId: "p1",
  currentSectionId: "sec1",
  screenGeneration: createScreenGeneration("p1", "secOLD"),
});
check(staleAck.outcome === "stale_screen" && staleAck.shouldClear === false, "stale screen no clear");

// 6. Retry replacement id + context preserve
const nextId = resolveRetryJobId("old", { job_id: "new_job" });
check(nextId === "new_job", "retry job id");
const nextDurable = resolveRetryJobId("old", { durable_job_id: "d2" });
check(nextDurable === "d2", "retry durable id");
const merged = mergeRetryLocator(locator, "j2", "p1");
check(merged.job_id === "j2", "merged job id");
check(merged.operation === "initial", "merged preserves operation");
check(merged.section_id === "sec1", "merged preserves section");
check(merged.version === LOCATOR_VERSION, "merged remains v2");

// 7. Duplicate prevention
check(shouldBlockStart("running") === true, "block running");
check(shouldBlockStart("queued") === true, "block queued");
check(shouldBlockStart("completed") === false, "allow after completed");
check(shouldBlockStart(null) === false, "allow empty");

// 8. Triage exact run/snapshot
const triageOk = acknowledgeTriageDomain({
  status: "completed",
  resultBody: { artifact: { run_id: "r1", snapshot_id: "snap1" } },
  locator: buildLocator({ projectId: "p1", jobId: "j", runId: "r1", snapshotId: "snap1" }),
  expectedRunId: "r1",
  expectedSnapshotId: "snap1",
});
check(triageOk.shouldClear === true, "triage exact clears");
const triageMismatch = acknowledgeTriageDomain({
  status: "completed",
  resultBody: { artifact: { run_id: "r2" } },
  locator: { run_id: "r1" },
  expectedRunId: "r1",
});
check(triageMismatch.shouldClear === false, "triage run mismatch retains");

// 9. Translation exact batch + cancel without domain
const txOk = acknowledgeTranslationDomain({
  status: "completed",
  resultBody: { artifact: { batch_id: "b1", snapshot_id: "s1" } },
  locator: buildLocator({ projectId: "p1", jobId: "j", batchId: "b1", snapshotId: "s1" }),
  expectedBatchId: "b1",
  expectedSnapshotId: "s1",
});
check(txOk.shouldClear === true, "translation exact clears");
const txCancel = acknowledgeTranslationDomain({
  status: "cancelled",
  resultBody: null,
  locator: { batch_id: "b1" },
});
check(txCancel.shouldClear === false, "translation cancel without result retains");

// 10. Controller export surface
check(typeof durableJobController.acknowledgeRevisionDomain === "function", "controller export");
check(durableJobController.LOCATOR_VERSION === LOCATOR_VERSION, "controller version");

// Transport alone never enough for success cleanup path
check(classifyPollOutcome("completed", false) === "reconcile_failed", "completed without domain not success");
check(shouldClearLocator("completed", false) === false, "completed without domain no clear");

console.log(`${passed} passed, 0 failed`);
