function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function nonNegativeInteger(value) {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : null;
}

const DAILY_AI_PROGRESS_STATUSES = new Set([
  "not_submitted",
  "running",
  "queued",
  "completed",
  "partial_completed",
  "failed",
]);

function dailyRunStep(detail, stepName) {
  return (Array.isArray(detail?.steps) ? detail.steps : []).find(
    (step) => isRecord(step) && step.step_name === stepName && step.status === "completed",
  ) || null;
}

function invalidShape(message) {
  return { ok: false, error: message, value: null };
}

export function normalizeDailyRunList(payload, { projectId } = {}) {
  if (!isRecord(payload)) {
    return invalidShape("日常医学监查运行状态格式异常，暂不展示运行状态。");
  }
  const items = payload.items === undefined ? [] : payload.items;
  if (!Array.isArray(items) || items.some((item) => !isRecord(item))) {
    return invalidShape("日常医学监查运行记录格式异常，暂不展示运行状态。");
  }
  const activeRun = payload.active_run;
  if (activeRun !== null && activeRun !== undefined && !isRecord(activeRun)) {
    return invalidShape("日常医学监查活动运行格式异常，暂不展示运行状态。");
  }
  const currentBaseline = payload.current_baseline;
  if (currentBaseline !== null && currentBaseline !== undefined && !isRecord(currentBaseline)) {
    return invalidShape("日常医学监查比较基线格式异常，暂不展示运行状态。");
  }
  const expectedProjectId = typeof projectId === "string" ? projectId.trim() : "";
  if (!expectedProjectId) {
    return invalidShape("当前日常监查项目身份缺失，暂不写入当前运行列表。");
  }
  const responseProjectId = typeof payload.project_id === "string"
    ? payload.project_id.trim()
    : "";
  if (!responseProjectId) {
    return invalidShape("日常医学监查运行列表缺少项目身份，已阻止写入当前运行列表。");
  }
  if (responseProjectId !== expectedProjectId) {
    return invalidShape("日常医学监查运行列表项目身份不一致，已阻止写入当前运行列表。");
  }
  if (items.some((item) => item.project_id !== expectedProjectId)) {
    return invalidShape("日常医学监查运行记录项目身份不一致，已阻止写入当前运行列表。");
  }
  if (activeRun !== null && activeRun !== undefined && activeRun.project_id !== expectedProjectId) {
    return invalidShape("日常医学监查活动运行项目身份不一致，已阻止写入当前运行列表。");
  }
  if (
    currentBaseline !== null
    && currentBaseline !== undefined
    && currentBaseline.project_id !== expectedProjectId
  ) {
    return invalidShape("日常医学监查比较基线项目身份不一致，已阻止写入当前运行列表。");
  }
  return {
    ok: true,
    error: "",
    value: {
      ...payload,
      items,
      active_run: activeRun ?? null,
      current_baseline: currentBaseline ?? null,
    },
  };
}

export function normalizeDailyRunReadiness(payload, { projectId, batchId } = {}) {
  const expectedProjectId = typeof projectId === "string" ? projectId.trim() : "";
  const expectedBatchId = typeof batchId === "string" ? batchId.trim() : "";
  if (!expectedProjectId || !expectedBatchId) {
    return invalidShape("当前日常监查项目或批次身份缺失，暂不写入就绪状态。");
  }
  if (!isRecord(payload)) {
    return invalidShape("日常医学监查就绪状态格式异常，暂不展示启动条件。");
  }
  const responseProjectId = typeof payload.project_id === "string"
    ? payload.project_id.trim()
    : "";
  const responseBatchId = typeof payload.batch_id === "string"
    ? payload.batch_id.trim()
    : "";
  if (!responseProjectId || !responseBatchId) {
    return invalidShape("日常医学监查就绪状态缺少项目或批次身份，已阻止写入当前运行。");
  }
  if (responseProjectId !== expectedProjectId || responseBatchId !== expectedBatchId) {
    return invalidShape("日常医学监查就绪状态项目或批次身份不一致，已阻止写入当前运行。");
  }
  if (typeof payload.ready !== "boolean") {
    return invalidShape("日常医学监查就绪状态格式异常，暂不展示启动条件。");
  }
  if (typeof payload.next_action !== "string" || !payload.next_action.trim()) {
    return invalidShape("日常医学监查就绪状态缺少下一步动作，暂不展示启动条件。");
  }
  if (typeof payload.message !== "string") {
    return invalidShape("日常医学监查就绪状态缺少说明，暂不展示启动条件。");
  }
  return { ok: true, error: "", value: payload };
}

export function normalizeDailyRunDetail(payload, { projectId, runId } = {}) {
  if (!isRecord(payload) || !isRecord(payload.run)) {
    return invalidShape("日常医学监查运行详情格式异常，暂不展示运行状态。");
  }
  const steps = payload.steps === undefined ? [] : payload.steps;
  if (!Array.isArray(steps) || steps.some((step) => !isRecord(step))) {
    return invalidShape("日常医学监查运行步骤格式异常，暂不展示运行状态。");
  }
  const expectedProjectId = typeof projectId === "string" ? projectId.trim() : "";
  const expectedRunId = typeof runId === "string" ? runId.trim() : "";
  if (!expectedProjectId || !expectedRunId) {
    return invalidShape("当前日常监查项目或运行身份缺失，暂不写入当前运行。");
  }
  const responseProjectId = typeof payload.project_id === "string"
    ? payload.project_id.trim()
    : "";
  const responseRunProjectId = typeof payload.run.project_id === "string"
    ? payload.run.project_id.trim()
    : "";
  const responseRunId = typeof payload.run.run_id === "string"
    ? payload.run.run_id.trim()
    : "";
  if (!responseProjectId || !responseRunProjectId || !responseRunId) {
    return invalidShape("日常医学监查运行详情缺少项目或运行身份，已阻止写入当前运行。");
  }
  if (
    responseProjectId !== expectedProjectId
    || responseRunProjectId !== expectedProjectId
    || responseRunId !== expectedRunId
  ) {
    return invalidShape("日常医学监查运行详情项目或运行身份不一致，已阻止写入当前运行。");
  }
  return { ok: true, error: "", value: { ...payload, steps } };
}

/**
 * Prevent a progress response from another project/run from entering the
 * selected daily-run view. Request cancellation prevents late local writes,
 * but the response identity still has to be checked independently.
 */
export function normalizeDailyRunAiProgress(payload, { projectId, runId } = {}) {
  const expectedProjectId = typeof projectId === "string" ? projectId.trim() : "";
  const expectedRunId = typeof runId === "string" ? runId.trim() : "";
  if (!expectedProjectId || !expectedRunId) {
    return invalidShape("当前日常监查项目或运行身份缺失，暂不写入 AI 进度。");
  }
  if (!isRecord(payload)) {
    return invalidShape("独立 AI 进度响应格式异常，暂不写入当前运行。");
  }
  const responseProjectId = typeof payload.project_id === "string" ? payload.project_id.trim() : "";
  const responseRunId = typeof payload.run_id === "string" ? payload.run_id.trim() : "";
  if (!responseProjectId || !responseRunId) {
    return invalidShape("独立 AI 进度响应缺少项目或运行身份，已阻止写入当前运行。");
  }
  if (responseProjectId !== expectedProjectId || responseRunId !== expectedRunId) {
    return invalidShape("独立 AI 进度响应项目或运行身份不一致，已阻止写入当前运行。");
  }
  return { ok: true, error: "", value: payload };
}

export function newestDailyRun(items, batchId) {
  return (Array.isArray(items) ? items : [])
    .filter((item) => (
      isRecord(item)
      && item.batch_id === batchId
      && typeof item.run_id === "string"
      && item.run_id.trim()
    ))
    .sort((left, right) => (
      String(right.created_at || "").localeCompare(String(left.created_at || ""))
    ))[0] || null;
}

export function completedDailyRunStep(detail, stepName) {
  return Boolean(dailyRunStep(detail, stepName));
}

/**
 * Gate the UI's risk-assembly action on the immutable AI submission step and
 * the explicit progress ledger. A missing or malformed ledger must not be
 * mistaken for a completed/no-job run, even though the backend also rejects
 * inconsistent assembly requests.
 */
export function dailyRunAiAssemblyGate(detail, progress) {
  const submission = dailyRunStep(detail, "independent_ai_submission");
  const jobCount = nonNegativeInteger(submission?.details?.job_count);
  const base = {
    submitted: Boolean(submission),
    jobCount,
    progressStatus: null,
    running: false,
    canAssemble: false,
    reason: "not_submitted",
  };
  if (!submission) return base;
  if (jobCount === null) return { ...base, reason: "submission_job_count_missing" };
  if (!isRecord(progress)) return { ...base, reason: "progress_missing" };

  const status = typeof progress.status === "string" ? progress.status.trim() : "";
  if (!DAILY_AI_PROGRESS_STATUSES.has(status)) {
    return { ...base, progressStatus: status || null, reason: "progress_status_invalid" };
  }
  const counts = ["total", "queued", "running", "completed", "failed"]
    .map((field) => nonNegativeInteger(progress[field]));
  if (counts.some((value) => value === null)) {
    return { ...base, progressStatus: status, reason: "progress_counts_invalid" };
  }
  const [total, queued, running, completed, failed] = counts;
  if (total !== jobCount) {
    return { ...base, progressStatus: status, reason: "job_count_mismatch" };
  }
  if (queued + running + completed + failed !== total) {
    return { ...base, progressStatus: status, reason: "progress_counts_inconsistent" };
  }
  if (status === "running" || status === "queued") {
    return {
      ...base,
      progressStatus: status,
      running: true,
      reason: "progress_running",
    };
  }
  if (status === "not_submitted") {
    return {
      ...base,
      progressStatus: status,
      canAssemble: total === 0 && jobCount === 0,
      reason: total === 0 && jobCount === 0 ? "zero_jobs" : "progress_not_submitted",
    };
  }
  return {
    ...base,
    progressStatus: status,
    canAssemble: true,
    reason: "progress_terminal",
  };
}

export function dailyRunRiskCount(detail) {
  const step = (Array.isArray(detail?.steps) ? detail.steps : []).find(
    (item) => isRecord(item)
      && item.step_name === "risk_snapshot_assembly"
      && item.status === "completed",
  );
  return nonNegativeInteger(step?.details?.risk_count);
}

export function dailyRunBaselineRevision(runList) {
  const baseline = runList?.current_baseline;
  if (baseline === null || baseline === undefined) return 0;
  return isRecord(baseline) ? nonNegativeInteger(baseline.revision) : null;
}

export function dailyRunProgressCount(value) {
  return nonNegativeInteger(value);
}

export function isDailyRunRecord(value) {
  return isRecord(value);
}
