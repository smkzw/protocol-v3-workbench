import { AlertTriangle, CheckCircle2, CircleHelp, Link2, ShieldAlert } from "lucide-react";

import {
  normalizeMedicalMonitoringRiskEvidenceContext,
  riskEvidenceContextLineageLabel,
  riskEvidenceContextStateLabel,
} from "./medicalMonitoringRiskEvidenceContext.mjs";
import { riskDispositionStatusLabel, severityLabel } from "./medicalMonitoringModels.mjs";
import "./MedicalMonitoringRiskEvidenceContext.css";

function display(value, fallback = "待核对") {
  return value || fallback;
}

function EvidenceStateIcon({ state }) {
  if (state === "bound") return <CheckCircle2 size={13} aria-hidden="true" />;
  if (state === "malformed") return <ShieldAlert size={13} aria-hidden="true" />;
  return <CircleHelp size={13} aria-hidden="true" />;
}

export default function MedicalMonitoringRiskEvidenceContext({ risk }) {
  const view = normalizeMedicalMonitoringRiskEvidenceContext(risk);
  if (view.status === "malformed" || !view.value) {
    return (
      <section className="monitoring-risk-evidence-context malformed" aria-label="风险上下文">
        <AlertTriangle size={14} aria-hidden="true" />
        <span>风险上下文格式异常；暂不展示身份与证据摘要，请回到风险清单核对。</span>
      </section>
    );
  }

  const { value } = view;
  const evidenceClass = `state-${value.evidence.status}`;
  const lineageClass = `state-${value.lineage.status}`;
  return (
    <section className={`monitoring-risk-evidence-context ${view.status}`} aria-label="风险身份与证据摘要">
      <header>
        <div>
          <strong>风险上下文</strong>
          <span>先核对身份、来源链路与证据状态，再进行医学判断或处置。</span>
        </div>
        {value.needsAction === true && <em className="needs-action">需行动</em>}
        {value.unread === true && <em className="unread">未读</em>}
      </header>
      <div className="monitoring-risk-evidence-context-grid">
        <div><span>范围</span><strong>{display(value.scopeLabel)}</strong></div>
        <div><span>受试者 / 中心</span><strong>{display(value.subjectId, "项目层面")} / {display(value.siteId, "未提供")}</strong></div>
        <div><span>风险级别 / 状态</span><strong>{display(severityLabel(value.severity))} / {display(riskDispositionStatusLabel(value.dispositionState || value.status))}</strong></div>
      </div>
      <div className="monitoring-risk-evidence-context-states">
        <span className={`monitoring-risk-context-state ${evidenceClass}`}>
          <EvidenceStateIcon state={value.evidence.status} />
          {riskEvidenceContextStateLabel(value.evidence.status)}
          <small>{value.evidence.locatorCount === null ? "待核对" : `${value.evidence.locatorCount} 条定位`}</small>
        </span>
        <span className={`monitoring-risk-context-state ${lineageClass}`}>
          <Link2 size={13} aria-hidden="true" />
          {riskEvidenceContextLineageLabel(value.lineage.status)}
          <small>{display(value.sourceVersion || value.snapshotId || value.batch)}</small>
        </span>
        {value.safetyPvFlag === true && <span className="monitoring-risk-context-state safety">Safety/PV 标记</span>}
      </div>
      {view.issues.length > 0 && (
        <p className="monitoring-risk-evidence-context-warning" role="alert">
          <AlertTriangle size={13} aria-hidden="true" />
          部分身份/证据字段形状异常；异常字段未补值，也不表示风险已关闭。
        </p>
      )}
      <small className="monitoring-risk-evidence-context-ids">
        实例 {display(value.riskInstanceId)} · 风险键 {display(value.riskKey)} · 快照 {display(value.snapshotId)}
      </small>
    </section>
  );
}

