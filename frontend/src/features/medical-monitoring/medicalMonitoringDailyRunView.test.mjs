import assert from "node:assert/strict";
import {
  completedDailyRunStep,
  dailyRunAiAssemblyGate,
  dailyRunBaselineRevision,
  dailyRunProgressCount,
  dailyRunRiskCount,
  newestDailyRun,
  normalizeDailyRunAiProgress,
  normalizeDailyRunDetail,
  normalizeDailyRunList,
  normalizeDailyRunReadiness,
} from "./medicalMonitoringDailyRunView.mjs";

const validList = normalizeDailyRunList({
  project_id: "project-1",
  active_run: null,
  current_baseline: null,
  items: [
    { project_id: "project-1", run_id: "run-old", batch_id: "batch-1", created_at: "2026-07-01" },
    { project_id: "project-1", run_id: "run-new", batch_id: "batch-1", created_at: "2026-07-02" },
  ],
}, { projectId: "project-1" });
assert.equal(validList.ok, true);
assert.equal(newestDailyRun(validList.value.items, "batch-1").run_id, "run-new");
assert.equal(newestDailyRun(validList.value.items, "batch-other"), null);
assert.equal(normalizeDailyRunList({ items: "not-an-array" }).ok, false);
assert.equal(normalizeDailyRunList({ items: [{ run_id: "ok" }, "malformed"] }).ok, false);
assert.equal(normalizeDailyRunList({ active_run: false, items: [] }).ok, false);
assert.equal(
  normalizeDailyRunList({ project_id: "project-other", items: [] }, { projectId: "project-1" }).error,
  "日常医学监查运行列表项目身份不一致，已阻止写入当前运行列表。",
);
assert.equal(
  normalizeDailyRunList({ project_id: "project-1", items: [{ project_id: "project-other" }] }, {
    projectId: "project-1",
  }).error,
  "日常医学监查运行记录项目身份不一致，已阻止写入当前运行列表。",
);
assert.equal(
  normalizeDailyRunList({ project_id: "project-1", items: [] }).error,
  "当前日常监查项目身份缺失，暂不写入当前运行列表。",
);
const validReadiness = normalizeDailyRunReadiness({
  project_id: "project-1",
  batch_id: "batch-1",
  ready: true,
  next_action: "start_daily_run",
  message: "ready",
}, { projectId: "project-1", batchId: "batch-1" });
assert.equal(validReadiness.ok, true);
assert.equal(
  normalizeDailyRunReadiness({
    project_id: "project-other",
    batch_id: "batch-1",
    ready: true,
    next_action: "start_daily_run",
    message: "ready",
  }, { projectId: "project-1", batchId: "batch-1" }).error,
  "日常医学监查就绪状态项目或批次身份不一致，已阻止写入当前运行。",
);
assert.equal(
  normalizeDailyRunReadiness({ project_id: "project-1", batch_id: "batch-1", ready: true }, {
    projectId: "project-1",
    batchId: "batch-1",
  }).error,
  "日常医学监查就绪状态缺少下一步动作，暂不展示启动条件。",
);
assert.equal(
  normalizeDailyRunReadiness({ project_id: "project-1", batch_id: "batch-1" }, {
    projectId: "project-1",
    batchId: "batch-1",
  }).error,
  "日常医学监查就绪状态格式异常，暂不展示启动条件。",
);
assert.equal(
  normalizeDailyRunReadiness(validReadiness.value, { projectId: "project-1" }).error,
  "当前日常监查项目或批次身份缺失，暂不写入就绪状态。",
);
const validDetail = {
  project_id: "project-1",
  run: { project_id: "project-1", run_id: "run-1" },
  steps: [],
};
assert.equal(
  normalizeDailyRunDetail(validDetail, { projectId: "project-1", runId: "run-1" }).ok,
  true,
);
assert.equal(
  normalizeDailyRunDetail({ ...validDetail, steps: ["malformed"] }, {
    projectId: "project-1",
    runId: "run-1",
  }).ok,
  false,
);
assert.equal(
  normalizeDailyRunDetail(validDetail, { projectId: "project-1", runId: "run-2" }).error,
  "日常医学监查运行详情项目或运行身份不一致，已阻止写入当前运行。",
);
assert.equal(
  normalizeDailyRunDetail({ project_id: "project-1", run: { run_id: "run-1" }, steps: [] }, {
    projectId: "project-1",
    runId: "run-1",
  }).error,
  "日常医学监查运行详情缺少项目或运行身份，已阻止写入当前运行。",
);
assert.equal(
  normalizeDailyRunDetail(validDetail).error,
  "当前日常监查项目或运行身份缺失，暂不写入当前运行。",
);

const aiProgress = normalizeDailyRunAiProgress({
  project_id: "project-1",
  run_id: "run-1",
  status: "completed",
}, { projectId: "project-1", runId: "run-1" });
assert.equal(aiProgress.ok, true);
assert.equal(aiProgress.value.run_id, "run-1");
assert.equal(
  normalizeDailyRunAiProgress({ project_id: "project-1", run_id: "run-other" }, {
    projectId: "project-1",
    runId: "run-1",
  }).error,
  "独立 AI 进度响应项目或运行身份不一致，已阻止写入当前运行。",
);
assert.equal(
  normalizeDailyRunAiProgress({ project_id: "project-1" }, {
    projectId: "project-1",
    runId: "run-1",
  }).ok,
  false,
);
assert.equal(
  normalizeDailyRunAiProgress({ project_id: "project-other", run_id: "run-1" }, {
    projectId: "project-1",
    runId: "run-1",
  }).ok,
  false,
);

const detail = {
  steps: [
    { step_name: "risk_snapshot_assembly", status: "completed", details: { risk_count: 4 } },
    { step_name: "independent_ai_submission", status: "completed", details: { job_count: 2 } },
  ],
};
assert.equal(completedDailyRunStep(detail, "independent_ai_submission"), true);
assert.equal(completedDailyRunStep({ steps: "malformed" }, "independent_ai_submission"), false);
assert.equal(
  dailyRunAiAssemblyGate(detail, {
    status: "running",
    total: 2,
    queued: 1,
    running: 1,
    completed: 0,
    failed: 0,
  }).running,
  true,
);
assert.equal(
  dailyRunAiAssemblyGate(detail, {
    status: "completed",
    total: 2,
    queued: 0,
    running: 0,
    completed: 2,
    failed: 0,
  }).canAssemble,
  true,
);
assert.equal(
  dailyRunAiAssemblyGate(detail, null).reason,
  "progress_missing",
  "missing AI progress blocks risk assembly",
);
assert.equal(
  dailyRunAiAssemblyGate(detail, {
    status: "completed",
    total: 1,
    queued: 0,
    running: 0,
    completed: 1,
    failed: 0,
  }).reason,
  "job_count_mismatch",
  "a progress ledger for a different job count blocks risk assembly",
);
assert.equal(
  dailyRunAiAssemblyGate(detail, {
    status: "completed",
    total: 2,
    queued: 1,
    running: 0,
    completed: 2,
    failed: 0,
  }).reason,
  "progress_counts_inconsistent",
  "inconsistent progress counts block risk assembly",
);
assert.equal(
  dailyRunAiAssemblyGate({
    steps: [{ step_name: "independent_ai_submission", status: "completed", details: { job_count: 0 } }],
  }, {
    status: "not_submitted",
    total: 0,
    queued: 0,
    running: 0,
    completed: 0,
    failed: 0,
  }).canAssemble,
  true,
  "an explicit zero-job ledger remains assemblable",
);
assert.equal(
  dailyRunAiAssemblyGate({
    steps: [{ step_name: "independent_ai_submission", status: "completed", details: { job_count: 1 } }],
  }, {
    status: "not_submitted",
    total: 1,
    queued: 0,
    running: 0,
    completed: 0,
    failed: 1,
  }).canAssemble,
  false,
  "not-submitted progress cannot be used for a non-empty AI submission",
);
assert.equal(dailyRunRiskCount(detail), 4);
assert.equal(dailyRunRiskCount({ steps: [{ step_name: "risk_snapshot_assembly", status: "completed", details: { risk_count: "4" } }] }), null);
assert.equal(dailyRunRiskCount({ steps: [{ step_name: "risk_snapshot_assembly", status: "completed", details: { risk_count: false } }] }), null);
assert.equal(dailyRunBaselineRevision({ current_baseline: null }), 0);
assert.equal(dailyRunBaselineRevision({ current_baseline: { revision: 2 } }), 2);
assert.equal(dailyRunBaselineRevision({ current_baseline: { revision: "2" } }), null);
assert.equal(dailyRunProgressCount(0), 0);
assert.equal(dailyRunProgressCount("0"), null);

console.log("medicalMonitoringDailyRunView: 41 passed");
