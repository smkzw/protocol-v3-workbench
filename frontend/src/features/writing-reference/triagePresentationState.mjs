const ACTIVE_JOB_STATUSES = new Set(["starting", "queued", "running", "resuming"]);
const PIPELINE_ACTIVE_STAGES = new Set(["queued", "triaging"]);
const PIPELINE_FAILURE_STAGES = new Set(["failed", "cancelled"]);

export function triageProgress(run, candidateCount = 0) {
  const chunks = Array.isArray(run?.chunks) ? run.chunks : [];
  const counts = chunks.reduce((result, chunk) => {
    const status = String(chunk?.status || "pending");
    result[status] = (result[status] || 0) + 1;
    return result;
  }, { pending: 0, running: 0, succeeded: 0, failed: 0 });
  const resultCount = chunks
    .filter((chunk) => chunk?.status === "succeeded")
    .reduce((sum, chunk) => sum + (Array.isArray(chunk?.results) ? chunk.results.length : 0), 0);
  const totalCandidates = chunks.reduce(
    (sum, chunk) => sum + (Array.isArray(chunk?.nct_ids) ? chunk.nct_ids.length : 0),
    0,
  ) || Number(candidateCount || 0);

  return {
    ...counts,
    totalChunks: chunks.length,
    completedChunks: counts.succeeded + counts.failed,
    resultCount,
    totalCandidates,
  };
}

export function mergeTriageSelections(current, results, { reset = false } = {}) {
  const next = reset ? {} : { ...(current || {}) };
  for (const result of Array.isArray(results) ? results : []) {
    const nctId = String(result?.nct_id || "").trim();
    const classification = String(result?.classification || "").trim();
    if (!nctId || !classification) continue;
    if (reset || !next[nctId]) next[nctId] = classification;
  }
  return next;
}

function pipelineMatchesRun(pipeline, run, snapshotId) {
  if (!pipeline || typeof pipeline !== "object") return false;
  if (snapshotId && pipeline.snapshot_id && pipeline.snapshot_id !== snapshotId) return false;
  if (run?.run_id && pipeline.triage_run_id && pipeline.triage_run_id !== run.run_id) return false;
  return true;
}

function conciseFailureDetail({ run, jobStatus, pipeline, pipelineRelevant, progress }) {
  if (pipelineRelevant && PIPELINE_FAILURE_STAGES.has(pipeline?.stage)) {
    const raw = String(pipeline?.error_summary || "");
    if (raw.includes("分诊超时")) return "分诊未在预期时间内完成";
    return String(pipeline?.detail || "分诊未完成").trim();
  }
  if (jobStatus === "cancelled") return "本次分诊已取消";
  if (jobStatus === "failed") return "后台分诊任务未完成";
  if (run?.error_message) return String(run.error_message).trim();
  if (progress.failed) return `${progress.failed} 个分诊批次未完成`;
  return "分诊未完成";
}

/**
 * Convert the persisted business run, durable job, and parent pipeline into a
 * small operator-facing state. No timeout is inferred locally: a terminal
 * failure is only surfaced when one of the APIs reports it.
 */
export function deriveTriagePresentation({ run, jobStatus = "", hasActiveJob = false, pipeline = null, snapshotId = "", candidateCount = 0 } = {}) {
  const progress = triageProgress(run, candidateCount);
  const runStatus = String(run?.status || "");
  const pipelineRelevant = pipelineMatchesRun(pipeline, run, snapshotId);
  const pipelineStage = pipelineRelevant ? String(pipeline?.stage || "") : "";
  // A retry receives a fresh durable job before the parent pipeline has a
  // reason to clear its earlier failure. The new job is the current authority
  // during that interval; without it the UI would immediately re-report the
  // old parent failure and stop its own refresh loop.
  const hasTerminalPipelineFailure = PIPELINE_FAILURE_STAGES.has(pipelineStage) && !hasActiveJob;
  const hasTerminalJobFailure = jobStatus === "failed" || jobStatus === "cancelled";

  if (runStatus === "confirmed") {
    return { kind: "confirmed", progress, retryable: false, message: "分诊结果已确认并锁定。" };
  }
  if (runStatus === "projection_pending") {
    return { kind: "projection_pending", progress, retryable: false, message: "分诊已确认，正在同步到写作旅程。" };
  }
  if (runStatus === "review_ready") {
    return { kind: "review_ready", progress, retryable: false, message: `AI建议已就绪，共 ${progress.resultCount}/${progress.totalCandidates} 项，确认前可逐项微调。` };
  }
  if (runStatus === "stale") {
    return { kind: "stale", progress, retryable: false, message: "项目框架或检索结果已更新，请按当前信息重新分诊。" };
  }

  const failed = runStatus === "failed"
    || runStatus === "partial_failed"
    || hasTerminalJobFailure
    || hasTerminalPipelineFailure;
  if (failed) {
    return {
      kind: "failed",
      progress,
      retryable: Boolean(run?.run_id),
      message: `${conciseFailureDetail({ run, jobStatus, pipeline, pipelineRelevant, progress })}。可直接重试当前分诊。`,
    };
  }

  const running = runStatus === "queued"
    || runStatus === "running"
    || ACTIVE_JOB_STATUSES.has(jobStatus)
    || (pipelineRelevant && PIPELINE_ACTIVE_STAGES.has(pipelineStage));
  if (running) {
    const progressText = progress.totalChunks
      ? `已完成 ${progress.completedChunks}/${progress.totalChunks} 个分诊批次${progress.totalCandidates ? `；已返回 ${progress.resultCount}/${progress.totalCandidates} 项建议` : ""}`
      : "正在读取分诊任务";
    return { kind: "running", progress, retryable: false, message: `${progressText}。` };
  }

  return { kind: "idle", progress, retryable: false, message: "" };
}
