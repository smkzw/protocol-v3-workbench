import { AlertTriangle, Bot, CheckCircle2, Clock3, FileWarning } from "lucide-react";

import {
  medicalMonitoringAiCountLabel,
  medicalMonitoringAiFailureDisplayKey,
  medicalMonitoringAiStatusLabel,
  normalizeMedicalMonitoringDailyAiEvidence,
} from "./medicalMonitoringDailyAiEvidence.mjs";
import "./MedicalMonitoringDailyAiEvidence.css";

function display(value) {
  return value || "待核对";
}

function statusIcon(status) {
  if (status === "ready") return <CheckCircle2 size={14} aria-hidden="true" />;
  if (status === "not_submitted") return <Clock3 size={14} aria-hidden="true" />;
  if (status === "unavailable") return <AlertTriangle size={14} aria-hidden="true" />;
  return <FileWarning size={14} aria-hidden="true" />;
}

function Metric({ label, value, tone = "neutral" }) {
  const displayValue = typeof value === "string"
    ? value
    : medicalMonitoringAiCountLabel(value);
  return (
    <div className={`monitoring-daily-ai-evidence-metric ${tone}`}>
      <span>{label}</span>
      <strong>{displayValue}</strong>
    </div>
  );
}

export default function MedicalMonitoringDailyAiEvidence({ progress, run, submitted }) {
  const view = normalizeMedicalMonitoringDailyAiEvidence({ progress, run, submitted });
  const value = view.value;

  if (view.status === "malformed" || !value) {
    return (
      <section className="monitoring-daily-ai-evidence malformed" aria-label="独立 AI 复核证据">
        <header>
          <strong><Bot size={14} /> 独立 AI 复核证据</strong>
          <FileWarning size={14} aria-hidden="true" />
        </header>
        <p role="alert">AI进度账本格式异常，暂不展示计数；请回到运行详情核对原始账本。</p>
      </section>
    );
  }

  const { counts } = value;
  const isUnavailable = view.status === "unavailable";
  const failureRows = Array.isArray(value.failures) ? value.failures.slice(0, 3) : [];
  const failureRowsOmitted = Array.isArray(value.failures) && value.failures.length > failureRows.length;
  const hasFailureEvidence = (Array.isArray(value.failures) && value.failures.length > 0)
    || counts.failed > 0;
  const progressLabel = value.progressStatus
    ? medicalMonitoringAiStatusLabel(value.progressStatus)
    : view.status === "not_submitted" ? "尚未提交" : "待核对";

  return (
    <section className={`monitoring-daily-ai-evidence ${view.status}`} aria-label="独立 AI 复核证据">
      <header className="monitoring-daily-ai-evidence-head">
        <div>
          <strong><Bot size={14} /> 独立 AI 复核证据</strong>
          <span>只展示 AI 任务账本；候选线索须由医学监查员复核，不构成风险结论。</span>
        </div>
        <span className="monitoring-daily-ai-evidence-status">
          {statusIcon(view.status)} {progressLabel}
        </span>
      </header>

      <div className="monitoring-daily-ai-evidence-meta">
        <span>运行 {display(value.runId)}</span>
        <span>批次 {display(value.batchId)}</span>
        <span>引擎 {display(value.engineVersion)}</span>
        <span>规则修订 {display(value.rulePackRevision || value.ruleResolutionMode)}</span>
      </div>

      {view.status === "not_submitted" ? (
        <p className="monitoring-daily-ai-evidence-note">当前运行尚未提交独立 AI 任务；不把未提交视为无 AI 风险。</p>
      ) : isUnavailable ? (
        <p className="monitoring-daily-ai-evidence-warning" role="alert"><AlertTriangle size={13} />已记录 AI 提交，但进度账本未返回；暂不显示完成或候选计数。</p>
      ) : (
        <>
          <div className="monitoring-daily-ai-evidence-grid">
            <Metric label="任务总数" value={counts.total} />
            <Metric label="已完成" value={counts.completed} tone="positive" />
            <Metric label="排队 / 运行" value={counts.queued !== null && counts.running !== null ? `${counts.queued} / ${counts.running}` : null} />
            <Metric label="失败任务" value={counts.failed} tone={counts.failed > 0 ? "danger" : "neutral"} />
            <Metric label="候选线索" value={counts.candidateCount} tone={counts.candidateCount > 0 ? "attention" : "neutral"} />
          </div>
          <div className="monitoring-daily-ai-evidence-progress" aria-label="AI任务完成进度">
            <div className="monitoring-daily-ai-evidence-progress-label">
              <span>任务完成进度</span>
              <strong>{value.completionPercent === null ? "待核对" : `${value.completionPercent}%`}</strong>
            </div>
            <div className="monitoring-daily-ai-evidence-progress-track">
              <span style={{ width: `${value.completionPercent ?? 0}%` }} />
            </div>
          </div>
          {hasFailureEvidence && (
            <div className="monitoring-daily-ai-evidence-failures">
              <strong>失败任务证据 <small>（仅作账本分类，不代表可重试）</small></strong>
              {failureRows.length > 0 ? failureRows.map((failure, index) => (
                <div key={medicalMonitoringAiFailureDisplayKey(failure, index)}>
                  <code>{failure.jobId}</code>
                  <span className={`monitoring-daily-ai-failure-kind ${failure.failureKind || "unknown"}`}>{failure.failureLabel || "失败原因待核对"}</span>
                  <span>{display(failure.subjectId)} · {display(failure.code)} · {display(failure.message)}</span>
                </div>
              )) : <span>失败任务明细待核对。</span>}
              {failureRowsOmitted && <small>仅显示前 {failureRows.length} 条；其余失败任务仍需处理。</small>}
            </div>
          )}
        </>
      )}

      {view.issues.length > 0 && (
        <p className="monitoring-daily-ai-evidence-warning" role="alert">
          <AlertTriangle size={13} />部分 AI 账本字段待核对；计数与明细不一致时保留失败证据，不补成 0，也不作为无风险依据。
        </p>
      )}
      <small className="monitoring-daily-ai-evidence-source">AI 任务状态来自当前运行的显式进度接口；此卡不执行提交、重试或风险处置。</small>
    </section>
  );
}
