import { AlertTriangle, ArrowDown, ArrowUp, Minus, Orbit } from "lucide-react";

import {
  medicalMonitoringRiskSeverityTone,
  medicalMonitoringRiskTrendDirectionLabel,
  normalizeMedicalMonitoringRiskHistoryTrend,
} from "./medicalMonitoringRiskHistoryTrend.mjs";
import "./MedicalMonitoringRiskHistoryTrend.css";

function DirectionIcon({ direction }) {
  if (direction === "up") return <ArrowUp size={12} aria-hidden="true" />;
  if (direction === "down") return <ArrowDown size={12} aria-hidden="true" />;
  if (direction === "steady") return <Minus size={12} aria-hidden="true" />;
  return <Orbit size={12} aria-hidden="true" />;
}

export default function MedicalMonitoringRiskHistoryTrend({ instances = [] }) {
  const view = normalizeMedicalMonitoringRiskHistoryTrend(instances);
  if (view.status === "empty") {
    return <div className="monitoring-risk-history-trend empty">当前风险没有可比较的跨批次实例。</div>;
  }
  return (
    <section className={`monitoring-risk-history-trend ${view.status}`} aria-label="风险跨批次变化趋势">
      <header>
        <div>
          <strong>风险级别与批次变化</strong>
          <span>只显示同一风险实例的显式历史；方向不是临床因果结论，也不表示缺失点等于风险消失。</span>
          {view.points.some((point) => point.displayIdentityState !== "ready") && (
            <span>部分历史点身份待核对；原始记录保留，但暂不能确认单点来源。</span>
          )}
        </div>
        {view.summary && <em>{view.summary.transitionCount} 次级别变化</em>}
      </header>
      {view.status === "malformed" && (
        <p className="monitoring-risk-history-trend-warning" role="alert"><AlertTriangle size={13} /> 历史字段形状异常；异常值未用于计算方向，请回到下方原始历史表核对。</p>
      )}
      <ol className="monitoring-risk-history-trend-track">
        {view.points.slice(-8).map((point) => (
          <li key={point.displayKey} className={point.isCurrent ? "current" : ""}>
            <div className={`monitoring-risk-history-trend-dot ${medicalMonitoringRiskSeverityTone(point.severity)}`} title={point.severityLabel} />
            <div className="monitoring-risk-history-trend-point">
              <strong>{point.severityLabel}</strong>
              <span>{point.batchDelta || "批次变化待核对"}</span>
              <small title={point.displayIdentityIssue || undefined}>
                {point.sourceBatchId || point.snapshotId || "快照标识待核对"}
                {point.displayIdentityState !== "ready" ? ` · ${point.displayIdentityState === "duplicate" ? "身份重复" : "身份待核对"}` : ""}
              </small>
              <em className={`direction-${point.direction}`}><DirectionIcon direction={point.direction} />{medicalMonitoringRiskTrendDirectionLabel(point.direction)}</em>
            </div>
          </li>
        ))}
      </ol>
      {view.points.length > 8 && <small className="monitoring-risk-history-trend-more">趋势条仅显示最近 8 个实例；下方历史表保留完整链路。</small>}
      {view.issues.length > 0 && view.status !== "malformed" && <p className="monitoring-risk-history-trend-note">部分历史字段待核对；系统不会把缺失字段补成稳定趋势。</p>}
    </section>
  );
}
