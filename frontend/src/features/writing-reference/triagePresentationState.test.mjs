import assert from "node:assert/strict";
import {
  deriveTriagePresentation,
  mergeTriageSelections,
  triageProgress,
} from "./triagePresentationState.mjs";

let passed = 0;
function check(condition, message) {
  assert.ok(condition, message);
  passed += 1;
}

const queuedRun = {
  run_id: "run-1",
  snapshot_id: "snapshot-1",
  status: "queued",
  chunks: [
    { chunk_id: "c1", status: "succeeded", nct_ids: ["NCT1", "NCT2"], results: [{ nct_id: "NCT1" }, { nct_id: "NCT2" }] },
    { chunk_id: "c2", status: "running", nct_ids: ["NCT3"], results: [] },
    { chunk_id: "c3", status: "pending", nct_ids: ["NCT4"], results: [] },
  ],
};

const progress = triageProgress(queuedRun, 4);
check(progress.totalChunks === 3, "reports total chunks from persisted run");
check(progress.completedChunks === 1 && progress.resultCount === 2, "reports completed chunks and returned candidates");
check(progress.totalCandidates === 4, "reports persisted candidate coverage");

const incrementalSelections = mergeTriageSelections(
  { NCT1: "indirect_reference" },
  [
    { nct_id: "NCT1", classification: "excluded" },
    { nct_id: "NCT2", classification: "direct_competitor" },
  ],
);
check(
  incrementalSelections.NCT1 === "indirect_reference",
  "preserves a medical writer override when the same run gains another chunk",
);
check(
  incrementalSelections.NCT2 === "direct_competitor",
  "adds classifications that arrive in a later chunk of the same run",
);
const resetSelections = mergeTriageSelections(
  { OLD: "excluded", NCT1: "indirect_reference" },
  [{ nct_id: "NCT1", classification: "excluded" }],
  { reset: true },
);
check(
  Object.keys(resetSelections).length === 1 && resetSelections.NCT1 === "excluded",
  "replaces selections when a new triage run is adopted",
);

const running = deriveTriagePresentation({
  run: queuedRun,
  jobStatus: "running",
  snapshotId: "snapshot-1",
  candidateCount: 4,
});
check(running.kind === "running", "keeps a normal queued/running run active");
check(!running.retryable, "does not expose retry during a normal active run");
check(running.message.includes("2/4 项建议"), "shows returned candidate coverage while the run is active");

const pipelineFailure = deriveTriagePresentation({
  run: queuedRun,
  jobStatus: "failed",
  snapshotId: "snapshot-1",
  pipeline: {
    stage: "failed",
    snapshot_id: "snapshot-1",
    triage_run_id: "run-1",
    error_summary: "分诊超时",
  },
  candidateCount: 4,
});
check(pipelineFailure.kind === "failed", "surfaces real parent pipeline failure even when run remains queued");
check(pipelineFailure.retryable, "allows same-run recovery after terminal failure");
check(pipelineFailure.message.includes("未在预期时间内完成"), "turns the API timeout into concise operator-facing language");

const unrelatedPipeline = deriveTriagePresentation({
  run: queuedRun,
  jobStatus: "queued",
  snapshotId: "snapshot-1",
  pipeline: { stage: "failed", snapshot_id: "older-snapshot", triage_run_id: "old-run", error_summary: "旧错误" },
});
check(unrelatedPipeline.kind === "running", "does not leak an older pipeline failure into the current snapshot");

const activeRetry = deriveTriagePresentation({
  run: { ...queuedRun, status: "running" },
  jobStatus: "queued",
  hasActiveJob: true,
  snapshotId: "snapshot-1",
  pipeline: { stage: "failed", snapshot_id: "snapshot-1", triage_run_id: "run-1", error_summary: "旧的超时记录" },
});
check(activeRetry.kind === "running", "a newly accepted retry takes precedence over the parent’s previous failure");

const reviewReady = deriveTriagePresentation({
  run: { ...queuedRun, status: "review_ready" },
  jobStatus: "completed",
  snapshotId: "snapshot-1",
  candidateCount: 4,
});
check(reviewReady.kind === "review_ready" && !reviewReady.retryable, "preserves normal review-ready path");

const confirmedWithAdvancingPipeline = deriveTriagePresentation({
  run: { ...queuedRun, status: "confirmed" },
  jobStatus: "completed",
  snapshotId: "snapshot-1",
  pipeline: { stage: "preparing", snapshot_id: "snapshot-1", triage_run_id: "run-1" },
  candidateCount: 4,
});
check(confirmedWithAdvancingPipeline.kind === "confirmed", "confirmed run stays confirmed even when parent pipeline has advanced past the confirm gate");

const confirmedWithOldAwaitingPipeline = deriveTriagePresentation({
  run: { ...queuedRun, status: "confirmed" },
  jobStatus: "completed",
  snapshotId: "snapshot-1",
  pipeline: { stage: "awaiting_triage_confirm", snapshot_id: "snapshot-1", triage_run_id: "run-1" },
  candidateCount: 4,
});
check(confirmedWithOldAwaitingPipeline.kind === "confirmed", "confirmed run stays confirmed even when parent pipeline still shows awaiting_triage_confirm (stale)");

const reconfirmationRequired = deriveTriagePresentation({
  run: { ...queuedRun, status: "confirmed" },
  reconfirmationRequired: true,
  jobStatus: "completed",
  snapshotId: "snapshot-1",
});
check(
  reconfirmationRequired.kind === "reconfirmation_required",
  "shows a human re-review instead of a new AI run when medical facts changed",
);
check(
  reconfirmationRequired.message.includes("不会重复调用AI"),
  "explains that the immutable result is reused",
);

console.log(`triagePresentationState: ${passed} passed`);
