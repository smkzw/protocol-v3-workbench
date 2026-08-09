import {
  AlertTriangle,
  ArrowUpRight,
  BarChart3,
  MapPin,
  UserRound,
} from "lucide-react";

import {
  medicalMonitoringScopeLabel,
  medicalMonitoringScopeCategoryLabelMap,
  medicalMonitoringScopeNumber,
  medicalMonitoringScopeRowKey,
  normalizeMedicalMonitoringScopeSummary,
} from "./medicalMonitoringScopeSummary.mjs";
import "./MedicalMonitoringScopeSummary.css";

const LEVEL_META = Object.freeze({
  trial: { icon: BarChart3, title: "整个试验", empty: "暂无项目级风险汇总。" },
  site: { icon: MapPin, title: "中心集中度", empty: "暂无中心级风险引用。" },
  subject: { icon: UserRound, title: "个例优先队列", empty: "暂无受试者级风险引用。" },
});

function CountPill({ label, value, tone = "neutral" }) {
  return (
    <span className={`monitoring-scope-count ${tone}`}>
      <b>{medicalMonitoringScopeNumber(value)}</b>
      <small>{label}</small>
    </span>
  );
}

function Distribution({ entries, label, labelMap }) {
  if (!entries?.length) return null;
  const max = Math.max(1, ...entries.map((entry) => entry.count));
  return (
    <div className="monitoring-scope-distribution" aria-label={label}>
      <span className="monitoring-scope-distribution-label">{label}</span>
      {entries.slice(0, 4).map((entry) => (
        <div className="monitoring-scope-distribution-row" key={entry.label}>
          <span title={`代码 ${entry.label}`}>{labelMap?.[entry.label] || entry.label}</span>
          <i><b style={{ width: `${Math.round((entry.count / max) * 100)}%` }} /></i>
          <strong>{entry.count}</strong>
        </div>
      ))}
    </div>
  );
}

function ScopeRow({ row, level, active, onScopeChange }) {
  const canFocus = Boolean(row.scopeId && !row.identityAmbiguous && typeof onScopeChange === "function");
  const Icon = LEVEL_META[level].icon;
  const target = level === "site" ? { siteId: row.scopeId } : { subjectId: row.scopeId };
  const content = (
    <>
      <span className="monitoring-scope-row-icon"><Icon size={14} /></span>
      <span className="monitoring-scope-row-main">
        <strong>{row.label}</strong>
        <small>
          风险 {medicalMonitoringScopeNumber(row.riskCount)} · 待行动 {medicalMonitoringScopeNumber(row.needsActionCount)} · 未读 {medicalMonitoringScopeNumber(row.unreadCount)}
        </small>
      </span>
      {row.identityAmbiguous
        ? <span className="monitoring-scope-row-state">标识重复</span>
        : row.status === "partial" && <span className="monitoring-scope-row-state">部分字段</span>}
      {canFocus && <ArrowUpRight size={14} aria-hidden="true" />}
    </>
  );
  if (!canFocus) {
    const reason = row.identityAmbiguous ? "中心或受试者标识重复" : "中心或受试者标识缺失";
    return <div className={`monitoring-scope-row ${active ? "active" : ""}`} aria-label={`${row.label}，无法聚焦：${reason}`}>{content}</div>;
  }
  return (
    <button
      type="button"
      className={`monitoring-scope-row ${active ? "active" : ""}`}
      aria-current={active ? "true" : undefined}
      title={`聚焦${medicalMonitoringScopeLabel(level)} ${row.label}`}
      onClick={() => onScopeChange(level, target)}
    >
      {content}
    </button>
  );
}

function TrialCard({ row, categoryLabelMap }) {
  if (!row) {
    return <div className="monitoring-scope-trial-empty">暂无项目级风险汇总；当前页面不会用空值推断“无风险”。</div>;
  }
  return (
    <div className="monitoring-scope-trial-card">
      <div className="monitoring-scope-card-title"><BarChart3 size={15} /><strong>{LEVEL_META.trial.title}</strong><span>{row.label}</span></div>
      <div className="monitoring-scope-counts">
        <CountPill label="当前风险" value={row.riskCount} />
        <CountPill label="待行动" value={row.needsActionCount} tone={row.needsActionCount ? "warning" : "neutral"} />
        <CountPill label="未读" value={row.unreadCount} tone={row.unreadCount ? "info" : "neutral"} />
      </div>
      <div className="monitoring-scope-distributions">
        <Distribution entries={row.severityCounts} label="项目风险级别分布" />
        <Distribution entries={row.categoryCounts} label="项目风险类别分布" labelMap={categoryLabelMap} />
        <Distribution entries={row.batchDeltaCounts} label="项目批次变化分布" />
      </div>
      {row.status === "partial" && <p className="monitoring-scope-inline-warning">项目汇总部分字段缺失；缺失不等于无风险。</p>}
    </div>
  );
}

function ScopeList({ level, rows, activeScope, selectedId, onScopeChange }) {
  const meta = LEVEL_META[level];
  const Icon = meta.icon;
  return (
    <div className="monitoring-scope-list-card">
      <div className="monitoring-scope-card-title"><Icon size={15} /><strong>{meta.title}</strong><span>{rows.length} 个</span></div>
      {!rows.length && <p className="monitoring-scope-empty">{meta.empty}</p>}
      {rows.slice(0, 6).map((row, index) => (
        <ScopeRow
          key={medicalMonitoringScopeRowKey(row, index)}
          row={row}
          level={level}
          active={activeScope === level && selectedId && selectedId === row.scopeId}
          onScopeChange={onScopeChange}
        />
      ))}
      {rows.length > 6 && <small className="monitoring-scope-more">仅显示待行动/未读优先的前 6 个；完整清单仍在下方。</small>}
    </div>
  );
}

export default function MedicalMonitoringScopeSummary({
  rollup,
  loading = false,
  error = "",
  activeScope = "trial",
  selectedSiteId = "",
  selectedSubjectId = "",
  taxonomy,
  onScopeChange,
}) {
  const view = normalizeMedicalMonitoringScopeSummary(rollup);
  const categoryLabelMap = medicalMonitoringScopeCategoryLabelMap(taxonomy);
  const selectedId = activeScope === "site" ? selectedSiteId : selectedSubjectId;
  const blocked = view.status === "malformed";
  const readUnavailable = Boolean(error);
  return (
    <section className="monitoring-scope-summary" aria-label="项目中心受试者风险摘要">
      <header className="monitoring-scope-summary-head">
        <div>
          <span className="monitoring-scope-summary-eyebrow"><BarChart3 size={14} /> 风险集中度</span>
          <h2>项目 / 中心 / 个例</h2>
          <p>仅显示当前风险快照返回的显式汇总；点击中心或受试者即可聚焦 Checklist。汇总不替代原始事实和医学复核。</p>
        </div>
        <span className={`monitoring-scope-summary-status ${view.status}`} role="status">
          {loading ? "读取中" : blocked ? "字段形状异常" : view.status === "available" ? "已绑定快照" : "部分可用"}
        </span>
      </header>
      {error && <p className="monitoring-scope-summary-error" role="alert">{error}</p>}
      {blocked && (
        <div className="monitoring-scope-summary-blocker" role="alert">
          <AlertTriangle size={15} />
          <span>风险汇总字段形状异常，已停止用异常值绘图或计数；请回到当前快照和来源状态核对。</span>
        </div>
      )}
      {readUnavailable ? (
        <div className="monitoring-scope-summary-blocker" role="alert">
          <AlertTriangle size={15} />
          <span>项目、中心和个例汇总暂不可用；系统未用空汇总替代当前风险快照。</span>
        </div>
      ) : (
        <div className="monitoring-scope-summary-grid">
          <TrialCard row={view.trial} categoryLabelMap={categoryLabelMap} />
          <ScopeList level="site" rows={view.sites} activeScope={activeScope} selectedId={selectedId} onScopeChange={onScopeChange} />
          <ScopeList level="subject" rows={view.subjects} activeScope={activeScope} selectedId={selectedId} onScopeChange={onScopeChange} />
        </div>
      )}
      {view.issues.length > 0 && !blocked && (
        <p className="monitoring-scope-summary-note" role="note">
          {view.issues.slice(0, 2).join("；")}；缺失/异常不等于无风险，仍需查看原始数据与证据定位。
        </p>
      )}
    </section>
  );
}
