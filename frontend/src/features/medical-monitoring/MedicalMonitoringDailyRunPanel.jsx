import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  RefreshCw,
} from "lucide-react";

import {
  MedicalMonitoringApiError,
  createMedicalMonitoringApi,
} from "./medicalMonitoringApi.mjs";
import {
  canStartMonitoringDailyRun,
  monitoringDailyRunRemediation,
} from "./medicalMonitoringDailyRunStartGate.mjs";
import {
  completedDailyRunStep,
  dailyRunBaselineRevision,
  dailyRunAiAssemblyGate,
  dailyRunProgressCount,
  dailyRunRiskCount,
  newestDailyRun,
  normalizeDailyRunAiProgress,
  normalizeDailyRunDetail,
  normalizeDailyRunList,
  normalizeDailyRunReadiness,
} from "./medicalMonitoringDailyRunView.mjs";
import { monitoringModeForDailyRun } from "./medicalMonitoringModeCatalog.mjs";
import MedicalMonitoringDailyDiffSummary from "./MedicalMonitoringDailyDiffSummary.jsx";
import MedicalMonitoringDailyAiEvidence from "./MedicalMonitoringDailyAiEvidence.jsx";
import MedicalMonitoringDailyAiCandidates from "./MedicalMonitoringDailyAiCandidates.jsx";
import MedicalMonitoringDailyRunEvidence from "./MedicalMonitoringDailyRunEvidence.jsx";
import {
  createMedicalMonitoringProjectRequestScope,
} from "./medicalMonitoringProjectRequestScope.mjs";

const RUN_STEPS = [
  { key: "prepare", label: "批次准备" },
  { key: "diff", label: "差异分析" },
  { key: "rules", label: "医学规则" },
  { key: "ai", label: "AI复核" },
  { key: "confirm", label: "风险确认" },
];

const STATUS_STEP = {
  prepared: 0,
  diffing: 1,
  drift_review_required: 1,
  rules_running: 2,
  ai_running: 3,
  analysis_partial: 3,
  risk_review: 4,
  ready_to_confirm: 4,
  confirmed: 5,
  superseded: 0,
};

function requestKey(prefix) {
  const random = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${random}`;
}

function apiErrorMessage(error) {
  if (error instanceof MedicalMonitoringApiError) {
    const detail = error.detail?.detail;
    if (detail && typeof detail === "object" && detail.message) {
      return detail.message;
    }
  }
  return error?.message || "日常医学监查运行失败";
}

export default function MedicalMonitoringDailyRunPanel({
  projectId,
  batch,
  api: suppliedApi,
  onMappingRequired,
  onRulePackRequired,
  onBaselineConfirmed,
}) {
  const dailyMode = monitoringModeForDailyRun();
  const fallbackApi = useMemo(() => createMedicalMonitoringApi(), []);
  const api = suppliedApi || fallbackApi;
  const requestScope = useMemo(
    () => createMedicalMonitoringProjectRequestScope(projectId),
    [projectId],
  );
  const [runList, setRunList] = useState(null);
  const [detail, setDetail] = useState(null);
  const [aiProgress, setAiProgress] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [readinessError, setReadinessError] = useState("");
  const [aiProgressError, setAiProgressError] = useState("");

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!batch?.batch_id) return;
    const request = requestScope.begin("daily-run-state");
    if (!quiet) setBusy(true);
    setError("");
    setReadinessError("");
    setAiProgressError("");
    try {
      const rawList = await api.listDailyRuns(
        projectId,
        { signal: request.signal },
      );
      if (!requestScope.isCurrent(request)) return;
      const normalizedList = normalizeDailyRunList(rawList, { projectId });
      if (!normalizedList.ok) throw new Error(normalizedList.error);
      const list = normalizedList.value;
      const active = list.active_run?.batch_id === batch.batch_id
        && typeof list.active_run.run_id === "string"
        && list.active_run.run_id.trim()
        ? list.active_run
        : null;
      const selected = active || newestDailyRun(list.items, batch.batch_id);
      setRunList(list);
      if (!selected) {
        setDetail(null);
        setAiProgress(null);
        try {
          const rawReadiness = await api.getDailyRunReadiness(
            projectId,
            batch.batch_id,
            { signal: request.signal },
          );
          const normalizedReadiness = normalizeDailyRunReadiness(rawReadiness, {
            projectId,
            batchId: batch.batch_id,
          });
          if (!normalizedReadiness.ok) throw new Error(normalizedReadiness.error);
          setReadiness(normalizedReadiness.value);
        } catch (nextError) {
          if (requestScope.isCurrent(request)) {
            setReadiness(null);
            setReadinessError(apiErrorMessage(nextError, "日常监查就绪状态读取失败"));
          }
        }
        return;
      }
      const rawDetail = await api.getDailyRun(
        projectId,
        selected.run_id,
        { signal: request.signal },
      );
      if (!requestScope.isCurrent(request)) return;
      const normalizedDetail = normalizeDailyRunDetail(rawDetail, {
        projectId,
        runId: selected.run_id,
      });
      if (!normalizedDetail.ok) throw new Error(normalizedDetail.error);
      const nextDetail = normalizedDetail.value;
      setDetail(nextDetail);
      try {
        const rawReadiness = await api.getDailyRunReadiness(
          projectId,
          batch.batch_id,
          { signal: request.signal },
        );
        const normalizedReadiness = normalizeDailyRunReadiness(rawReadiness, {
          projectId,
          batchId: batch.batch_id,
        });
        if (!normalizedReadiness.ok) throw new Error(normalizedReadiness.error);
        setReadiness(normalizedReadiness.value);
      } catch (nextError) {
        if (requestScope.isCurrent(request)) {
          setReadiness(null);
          setReadinessError(apiErrorMessage(nextError, "日常监查就绪状态读取失败"));
        }
      }
      if (
        ["ai_running", "analysis_partial", "risk_review", "ready_to_confirm", "confirmed"]
          .includes(nextDetail.run.status)
        && completedDailyRunStep(nextDetail, "independent_ai_submission")
      ) {
        try {
          const rawAiProgress = await api.getDailyRunAiProgress(
            projectId,
            selected.run_id,
            { signal: request.signal },
          );
          const normalizedAiProgress = normalizeDailyRunAiProgress(rawAiProgress, {
            projectId,
            runId: selected.run_id,
          });
          if (!normalizedAiProgress.ok) throw new Error(normalizedAiProgress.error);
          setAiProgress(normalizedAiProgress.value);
        } catch (nextError) {
          if (requestScope.isCurrent(request)) {
            setAiProgress(null);
            setAiProgressError(apiErrorMessage(nextError, "AI复核进度读取失败"));
          }
        }
      } else {
        setAiProgress(null);
        setAiProgressError("");
      }
    } catch (nextError) {
      if (requestScope.isCurrent(request) && nextError.name !== "AbortError") {
        setDetail(null);
        setAiProgress(null);
        setReadiness(null);
        setReadinessError("");
        setAiProgressError("");
        setError(apiErrorMessage(nextError));
      }
    } finally {
      if (requestScope.isCurrent(request) && !quiet) setBusy(false);
      requestScope.finish(request);
    }
  }, [api, batch?.batch_id, projectId, requestScope]);

  useEffect(() => {
    requestScope.activate();
    return () => requestScope.dispose();
  }, [requestScope]);

  useEffect(() => {
    load();
  }, [load, batch?.active_mapping_revision, batch?.version]);

  const run = detail?.run || null;
  const aiSubmitted = completedDailyRunStep(detail, "independent_ai_submission");
  const aiAssemblyGate = dailyRunAiAssemblyGate(detail, aiProgress);
  const aiStillRunning = run?.status === "ai_running" && aiAssemblyGate.running;
  const aiAssemblyBlocked = run?.status === "ai_running"
    && aiSubmitted
    && !aiStillRunning
    && !aiAssemblyGate.canAssemble;
  const generatedRiskCount = dailyRunRiskCount(detail);
  const currentBaselineRevision = dailyRunBaselineRevision(runList);
  const baselineRevisionUnavailable = run?.status === "ready_to_confirm"
    && currentBaselineRevision === null;
  const aiCompletedCount = dailyRunProgressCount(aiProgress?.completed);
  const aiTotalCount = dailyRunProgressCount(aiProgress?.total);

  useEffect(() => {
    if (!aiStillRunning) return undefined;
    const timer = globalThis.setTimeout(() => load({ quiet: true }), 2500);
    return () => globalThis.clearTimeout(timer);
  }, [aiStillRunning, load, aiProgress?.completed, aiProgress?.running]);

  const execute = async (operation) => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await operation();
      await load({ quiet: true });
    } catch (nextError) {
      setError(apiErrorMessage(nextError));
    } finally {
      setBusy(false);
    }
  };

  const mappingChangedAfterDrift = run?.status === "drift_review_required"
    && batch.active_mapping_revision
    && batch.active_mapping_revision !== run.mapping_revision;

  let action = null;
  const remediation = monitoringDailyRunRemediation(readiness);
  if (!run && !canStartMonitoringDailyRun(readiness)) {
    action = null;
  } else if (
    (!run || run.status === "superseded" || mappingChangedAfterDrift)
    && canStartMonitoringDailyRun(readiness)
  ) {
    action = {
      label: mappingChangedAfterDrift ? "按新映射重新分析" : "开始医学监查",
      run: () => api.prepareDailyRun(projectId, {
        batch_id: batch.batch_id,
        idempotency_key: requestKey("daily-run"),
      }),
    };
  } else if (["prepared", "diffing"].includes(run.status)) {
    action = {
      label: run.baseline_batch_id ? "分析批次差异" : "开始规则分析",
      run: () => api.processDailyRun(projectId, run.run_id, {
        expected_version: run.version,
        owner: "medical_manager",
      }),
    };
  } else if (run.status === "drift_review_required") {
    action = {
      label: "核对批次差异",
      run: async () => onMappingRequired?.(),
      local: true,
    };
  } else if (run.status === "rules_running") {
    action = {
      label: "运行医学规则",
      run: () => api.executeDailyRunRules(projectId, run.run_id, {
        expected_version: run.version,
        owner: "medical_manager",
      }),
    };
  } else if (run.status === "ai_running" && !aiSubmitted) {
    action = {
      label: "启动 AI 复核",
      run: () => api.submitDailyRunAi(projectId, run.run_id, {
        expected_version: run.version,
        owner: "medical_manager",
      }),
    };
  } else if (run.status === "ai_running" && aiAssemblyGate.canAssemble) {
    action = {
      label: "汇总风险项",
      run: () => api.assembleDailyRunRisks(projectId, run.run_id, {
        expected_version: run.version,
        owner: "medical_manager",
      }),
    };
  } else if (run.status === "analysis_partial") {
    action = {
      label: "确认按现有结果继续",
      run: () => api.acknowledgeDailyRunPartial(projectId, run.run_id, {
        expected_version: run.version,
      }),
    };
  } else if (run.status === "risk_review") {
    action = {
      label: "风险项已复核",
      run: () => api.markDailyRunReady(projectId, run.run_id, {
        expected_version: run.version,
      }),
    };
  } else if (run.status === "ready_to_confirm" && currentBaselineRevision !== null) {
    action = {
      label: "确认并设为比较基线",
      run: () => api.confirmDailyRun(projectId, run.run_id, {
        expected_run_version: run.version,
        expected_baseline_revision: currentBaselineRevision,
        confirmed_by: "medical_manager",
      }),
      confirmed: true,
    };
  }
  if (!run && remediation?.key === "mapping") {
    action = {
      label: remediation.label,
      run: async () => onMappingRequired?.(),
      local: true,
    };
  } else if (!run && remediation?.key === "rule_pack") {
    action = {
      label: remediation.label,
      run: async () => onRulePackRequired?.(),
      local: true,
    };
  }

  const currentStep = run ? (STATUS_STEP[run.status] ?? 0) : 0;
  let summary = "冻结批次后运行差异分析、规则识别和 AI 复核。";
  if (!run && readiness && !readiness.ready) {
    summary = readiness.message;
  } else if (mappingChangedAfterDrift) {
    summary = "字段映射已更新，可按新映射重新分析本批次。";
  } else if (run?.status === "drift_review_required") {
    summary = "批次差异存在结构、来源完整性或删除身份阻断，请查看下方差异证据后再继续。";
  } else if (run?.status === "analysis_partial") {
    summary = "部分记录未完成 AI 复核；现有结果可继续审阅，未完成项不会被视为无风险。";
  } else if (run?.status === "risk_review") {
    summary = generatedRiskCount === null
      ? "已生成风险项，但风险计数证据缺失，请打开风险清单核对。"
      : `已生成 ${generatedRiskCount} 条风险项，请完成核对。`;
  } else if (run?.status === "ready_to_confirm") {
    summary = baselineRevisionUnavailable
      ? "当前比较基线版本格式异常，暂不能确认本批次。"
      : "风险项已复核。确认后，本批次才成为下一次比较基线。";
  } else if (run?.status === "confirmed") {
    summary = "本次医学监查已确认，该批次现为项目比较基线。";
  } else if (aiStillRunning) {
    summary = `AI 正在复核：${aiCompletedCount ?? "待确认"}/${aiTotalCount ?? "待确认"} 个受试者已完成。`;
  } else if (aiAssemblyBlocked) {
    summary = "AI 已提交，但当前进度账本缺失或未与提交任务数一致，暂不能汇总风险项。";
  }

  const needsAttention = ["drift_review_required", "analysis_partial"].includes(run?.status);

  return (
    <section className="monitoring-daily-run" aria-label={dailyMode.label}>
      <div className="monitoring-daily-run-head">
        <div>
          <strong>{dailyMode.label}</strong>
          <span>{summary}</span>
        </div>
        <button
          className="icon-button"
          type="button"
          title="刷新运行状态"
          aria-label="刷新运行状态"
          onClick={() => load()}
          disabled={busy}
        >
          <RefreshCw size={15} className={aiStillRunning ? "is-spinning" : ""} />
        </button>
      </div>

      <ol className="monitoring-daily-run-steps">
        {RUN_STEPS.map((step, index) => {
          const completed = currentStep > index;
          const active = currentStep === index && run?.status !== "confirmed";
          return (
            <li
              key={step.key}
              className={`${completed ? "completed" : ""} ${active ? "active" : ""}`}
            >
              {completed
                ? <CheckCircle2 size={16} />
                : <Circle size={16} />}
              <span>{step.label}</span>
            </li>
          );
        })}
      </ol>

      {detail && <MedicalMonitoringDailyDiffSummary diff={detail.diff} />}

      {detail && (
        <MedicalMonitoringDailyAiEvidence
          progress={aiProgress}
          run={run}
          submitted={aiSubmitted}
        />
      )}

      {detail && aiProgress && (
        <MedicalMonitoringDailyAiCandidates
          candidates={aiProgress.candidates}
          candidateCount={aiProgress.candidate_count}
        />
      )}

      {detail && <MedicalMonitoringDailyRunEvidence steps={detail.steps} />}

      {needsAttention && (
        <div className="monitoring-daily-run-attention" role="status">
          <AlertTriangle size={16} />
          <span>{summary}</span>
        </div>
      )}

      <div className="monitoring-daily-run-action">
        <span>
          {run?.status === "confirmed" && run.confirmed_at
            ? `确认时间：${new Date(run.confirmed_at).toLocaleString("zh-CN")}`
            : run?.status === "confirmed"
              ? "本次医学监查已确认。"
            : readiness?.ready
              ? "启动后进入正式日常医学监查状态机。"
              : "请完成上方提示的下一步。"}
        </span>
        {aiStillRunning && (
          <button className="primary-button" type="button" disabled>
            AI 正在复核
          </button>
        )}
        {aiAssemblyBlocked && (
          <button className="primary-button" type="button" disabled>
            等待 AI 任务账本
          </button>
        )}
        {!aiStillRunning && !aiAssemblyBlocked && action && (
          <button
            className="primary-button"
            type="button"
            disabled={busy}
            onClick={() => (
              action.local
                ? action.run()
                : execute(async () => {
                  await action.run();
                  if (action.confirmed) onBaselineConfirmed?.();
                })
            )}
          >
            {busy ? "处理中" : action.label}
          </button>
        )}
      </div>

      {error && <p className="monitoring-daily-run-error">{error}</p>}
      {readinessError && <p className="monitoring-daily-run-error" role="alert">{readinessError}</p>}
      {aiProgressError && <p className="monitoring-daily-run-error" role="alert">{aiProgressError}</p>}
    </section>
  );
}
