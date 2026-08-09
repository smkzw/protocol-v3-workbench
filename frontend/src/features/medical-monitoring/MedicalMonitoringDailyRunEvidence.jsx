import { AlertTriangle, CheckCircle2, Circle, Clock3, FileWarning } from "lucide-react";

import {
  medicalMonitoringRunStepCountLabel,
  medicalMonitoringRunStepEvidenceLabel,
  medicalMonitoringRunStepStatusLabel,
  normalizeMedicalMonitoringDailyRunEvidence,
} from "./medicalMonitoringDailyRunEvidence.mjs";
import "./MedicalMonitoringDailyRunEvidence.css";

function display(value) {
  return value || "待核对";
}

function rowIcon(status) {
  if (status === "completed") return <CheckCircle2 size={13} aria-hidden="true" />;
  if (status === "running") return <Clock3 size={13} aria-hidden="true" />;
  if (status === "not_started" || status === "not_applicable") return <Circle size={13} aria-hidden="true" />;
  return <AlertTriangle size={13} aria-hidden="true" />;
}

export default function MedicalMonitoringDailyRunEvidence({ steps }) {
  const view = normalizeMedicalMonitoringDailyRunEvidence(steps);
  if (view.status === "empty") {
    return (
      <section className="monitoring-daily-run-evidence empty" aria-label="运行步骤账本">
        <header><strong><Clock3 size={14} /> 运行步骤账本</strong></header>
        <p>当前运行尚未生成步骤记录；不据此判定任何步骤已完成或无风险。</p>
      </section>
    );
  }
  if (view.status === "malformed" || !view.value) {
    return (
      <section className="monitoring-daily-run-evidence malformed" aria-label="运行步骤账本">
        <header><strong><FileWarning size={14} /> 运行步骤账本</strong></header>
        <p role="alert">步骤账本格式异常，暂不展示步骤状态；请回到运行详情核对原始记录。</p>
      </section>
    );
  }

  const { rows, summary } = view.value;
  return (
    <section className={`monitoring-daily-run-evidence ${view.status}`} aria-label="运行步骤账本">
      <header className="monitoring-daily-run-evidence-head">
        <div>
          <strong><Clock3 size={14} /> 运行步骤账本</strong>
          <span>显示每一步的显式状态、尝试次数和输出证据；未开始不等于已通过。</span>
        </div>
        <div className="monitoring-daily-run-evidence-counts">
          <em>完成 {summary.completed}</em>
          <em className="running">运行中 {summary.running}</em>
          <em className={summary.failed > 0 ? "danger" : ""}>失败 {summary.failed}</em>
        </div>
      </header>

      <div className="monitoring-daily-run-evidence-table" role="table" aria-label="医学监查运行步骤">
        <div className="monitoring-daily-run-evidence-row header" role="row">
          <span>步骤</span><span>状态</span><span>尝试</span><span>更新时间</span><span>输出证据</span><span>详情</span>
        </div>
        {rows.map((row) => (
          <div className="monitoring-daily-run-evidence-row" role="row" key={`${row.stepName}-${row.sourceIndex ?? "missing"}`}>
            <span className="step-label"><span>{rowIcon(row.status)}</span>{row.label}</span>
            <span className={`step-status ${row.status || "unknown"}`}>{medicalMonitoringRunStepStatusLabel(row.status)}</span>
            <span>{medicalMonitoringRunStepCountLabel(row.attemptCount)}</span>
            <span title={display(row.updatedAt)}>{display(row.updatedAt)}</span>
            <span className={row.outputBound ? "evidence-present" : "evidence-missing"}>{medicalMonitoringRunStepEvidenceLabel(row)}</span>
            <span className="step-details">
              {row.details.length > 0
                ? row.details.slice(0, 2).map((detail) => <small key={detail.field}>{detail.label} {detail.value}</small>)
                : row.status === "not_started" || row.status === "not_applicable" ? "—" : "待核对"}
            </span>
          </div>
        ))}
      </div>

      {(summary.outputMissing > 0 || summary.unknownRecorded > 0) && (
        <p className="monitoring-daily-run-evidence-warning" role="alert">
          <AlertTriangle size={13} />{summary.outputMissing > 0 ? `${summary.outputMissing} 个已完成步骤缺少输出摘要；` : ""}{summary.unknownRecorded > 0 ? `${summary.unknownRecorded} 个账本步骤未在标准流程内；` : ""}请核对原始运行证据。
        </p>
      )}
      {view.issues.length > 0 && (
        <p className="monitoring-daily-run-evidence-warning" role="alert">
          <AlertTriangle size={13} />部分步骤字段待核对；异常值未补写，也不作为无风险依据。
        </p>
      )}
      <small className="monitoring-daily-run-evidence-source">步骤账本来自当前运行详情的显式记录；此卡不重试、补写或改变运行状态。</small>
    </section>
  );
}
