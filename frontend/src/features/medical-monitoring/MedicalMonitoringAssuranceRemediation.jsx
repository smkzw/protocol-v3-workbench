import { AlertTriangle, ArrowUpRight, ClipboardList } from "lucide-react";

import {
  assuranceRemediationDisplayKey,
  assuranceRemediationSeverityLabel,
  assuranceRemediationStatusLabel,
  normalizeMedicalMonitoringAssuranceRemediation,
} from "./medicalMonitoringAssuranceRemediation.mjs";
import "./MedicalMonitoringAssuranceRemediation.css";

function display(value) {
  return value || "待核对";
}

function evidenceLabel(value) {
  if (value === true) return "已提供";
  if (value === false) return "缺失";
  return "待核对";
}

export default function MedicalMonitoringAssuranceRemediation({ matrix, onFocusRow }) {
  const view = normalizeMedicalMonitoringAssuranceRemediation(matrix);
  if (view.status === "empty") {
    return (
      <section className="monitoring-assurance-remediation empty" aria-label="整改清单">
        <div className="monitoring-assurance-mini-title"><ClipboardList size={14} /> 现场自查优先项</div>
        <p>当前任务未返回整改矩阵；不能据此判定没有待核对风险。</p>
      </section>
    );
  }
  if (view.status === "malformed") {
    return (
      <section className="monitoring-assurance-remediation malformed" aria-label="整改清单">
        <div className="monitoring-assurance-mini-title"><AlertTriangle size={14} /> 整改矩阵形状异常</div>
        <p role="alert">暂不展示整改项；请回到任务证据核对原始矩阵。</p>
      </section>
    );
  }

  const rows = view.rows.slice(0, 8);
  return (
    <section className={`monitoring-assurance-remediation ${view.status}`} aria-label="现场自查整改清单">
      <header>
        <div>
          <strong><ClipboardList size={14} /> 现场自查优先项</strong>
          <span>按开放状态、显式严重度和关闭证据缺失排序；不代表未显示项已完成。</span>
        </div>
        <div className="monitoring-assurance-remediation-counts">
          <em>矩阵 {view.totalCount ?? "待核对"}</em>
          <em className="open">开放 {view.openCount}</em>
          <em className="missing">缺关闭证据 {view.missingClosureEvidenceCount}</em>
        </div>
      </header>
      <div className="monitoring-assurance-remediation-table" role="table" aria-label="优先整改项">
        <div className="monitoring-assurance-remediation-row header" role="row">
          <span>风险级别 / 状态</span><span>个例 / 中心</span><span>关闭证据</span><span>实例</span><span />
        </div>
        {rows.map((row, index) => {
          const identityAmbiguous = row.identityState !== "ready";
          return (
            <div className="monitoring-assurance-remediation-row" role="row" key={assuranceRemediationDisplayKey(row, index)}>
              <span><strong className={`severity-${row.severity || "unknown"}`}>{assuranceRemediationSeverityLabel(row.severity)}</strong><small>{assuranceRemediationStatusLabel(row.status)}</small></span>
              <span>{display(row.subjectId)} / {display(row.siteId)}</span>
              <span className={row.closureEvidencePresent === true ? "evidence-present" : "evidence-missing"}>{evidenceLabel(row.closureEvidencePresent)}</span>
              <code title={row.identityIssue || row.riskInstanceId}>{display(row.riskInstanceId)}{identityAmbiguous ? " · 身份待核对" : ""}</code>
              <button type="button" title={identityAmbiguous ? "身份重复，仅可读" : "聚焦该整改项的个例或中心"} onClick={() => !identityAmbiguous && onFocusRow?.(row)} disabled={identityAmbiguous || (!row.subjectId && !row.siteId)}><ArrowUpRight size={13} /></button>
            </div>
          );
        })}
      </div>
      {view.rows.length > rows.length && <small className="monitoring-assurance-remediation-more">仅显示前 {rows.length} 项；其余 {view.rows.length - rows.length} 项仍在当前矩阵中。</small>}
      {view.issues.length > 0 && <p className="monitoring-assurance-remediation-warning" role="alert"><AlertTriangle size={13} />部分矩阵字段待核对；异常项未用于排序或补值。</p>}
    </section>
  );
}
