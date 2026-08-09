import { AlertTriangle, Database, FileWarning } from "lucide-react";

import {
  dailyDiffCountLabel,
  normalizeMedicalMonitoringDailyDiff,
} from "./medicalMonitoringDailyDiffView.mjs";
import "./MedicalMonitoringDailyDiffSummary.css";

const METRICS = [
  ["newRows", "新增记录", "neutral"],
  ["changedRows", "变更记录", "attention"],
  ["persistingRows", "持续记录", "neutral"],
  ["removedRows", "移除记录", "attention"],
  ["rereviewRows", "需重新复核", "attention"],
  ["fieldChanges", "字段变更", "neutral"],
  ["schemaChanges", "结构变化", "danger"],
  ["identityMatchTotal", "身份匹配", "neutral"],
];

const CHANGE_KIND_LABELS = {
  added: "新增值",
  removed: "移除值",
  changed: "值变更",
  cleared: "清空值",
};

const DETAIL_GROUPS = [
  ["newKeys", "新增记录"],
  ["changedKeys", "变更记录"],
  ["rereviewKeys", "需重新复核"],
  ["removedKeys", "移除记录"],
  ["removalBlockedKeys", "身份阻断的移除"],
  ["missingDomains", "缺失数据域"],
];

function evidenceLabel(value) {
  if (value === true) return "已声明";
  if (value === false) return "未声明";
  return "待核对";
}

function DiffMetric({ field, label, tone, counts }) {
  return (
    <div className={`monitoring-daily-diff-metric ${tone}`}>
      <span>{label}</span>
      <strong>{dailyDiffCountLabel(counts[field])}</strong>
    </div>
  );
}

function clip(value, max = 84) {
  const text = String(value || "");
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function KeyDetailGroup({ label, items }) {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <div className="monitoring-daily-diff-detail-group">
      <strong>{label}</strong>
      <ul>
        {items.map((item) => <li key={`${label}-${item}`} title={item}>{clip(item)}</li>)}
      </ul>
    </div>
  );
}

function DiffDetailDisclosure({ details }) {
  const hasDetails = [
    details?.fieldChanges,
    details?.schemaDiffs,
    details?.identityMatchSamples,
    ...DETAIL_GROUPS.map(([field]) => details?.[field]),
  ].some((items) => Array.isArray(items) && items.length > 0);
  if (!hasDetails && !details?.truncated) return null;

  return (
    <details className="monitoring-daily-diff-details">
      <summary>查看结构、字段与回源核对明细</summary>
      <p className="monitoring-daily-diff-detail-note">
        明细只用于定位差异来源，不是医学风险结论；请回到对应来源行、字段和风险证据完成复核。
      </p>
      {details?.schemaDiffs?.length > 0 && (
        <div className="monitoring-daily-diff-detail-section">
          <strong>结构变化</strong>
          <ul className="monitoring-daily-diff-schema-list">
            {details.schemaDiffs.map((item) => (
              <li key={`schema-${item.domain}`}>
                <span>{item.domain}</span>
                {item.addedFields.length > 0 && <small>新增列：{item.addedFields.join("、")}</small>}
                {item.removedFields.length > 0 && <small>移除列：{item.removedFields.join("、")}</small>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {details?.fieldChanges?.length > 0 && (
        <div className="monitoring-daily-diff-detail-section">
          <strong>字段变化（最多展示 8 条）</strong>
          <ul className="monitoring-daily-diff-field-list">
            {details.fieldChanges.map((item, index) => (
              <li key={`${item.businessKey}-${item.fieldName}-${index}`}>
                <span>{item.domain} · {item.fieldName} · {CHANGE_KIND_LABELS[item.changeKind] || item.changeKind}</span>
                <small title={item.businessKey}>业务键：{clip(item.businessKey)}</small>
                <small>上一批：{item.previousLocator || "定位待核对"}；本批：{item.currentLocator || "定位待核对"}</small>
              </li>
            ))}
          </ul>
        </div>
      )}
      {details?.identityMatchSamples?.length > 0 && (
        <div className="monitoring-daily-diff-detail-section">
          <strong>身份匹配样本（最多展示 8 条）</strong>
          <ul className="monitoring-daily-diff-field-list">
            {details.identityMatchSamples.map((item, index) => (
              <li key={`${item.previousBusinessKey}-${index}`}>
                <span>{item.matchBasis}</span>
                <small>上一批：{clip(item.previousBusinessKey)}</small>
                <small>本批：{clip(item.currentBusinessKey)}</small>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="monitoring-daily-diff-detail-groups">
        {DETAIL_GROUPS.map(([field, label]) => (
          <KeyDetailGroup key={field} label={label} items={details?.[field]} />
        ))}
      </div>
      {details?.truncated && (
        <small className="monitoring-daily-diff-detail-truncated">
          记录较多，仅展示各类前 8 条；计数仍以服务端冻结 diff 快照为准。
        </small>
      )}
    </details>
  );
}

export default function MedicalMonitoringDailyDiffSummary({ diff }) {
  const view = normalizeMedicalMonitoringDailyDiff(diff);
  if (view.status === "empty") {
    return (
      <div className="monitoring-daily-diff-summary empty" role="status">
        <Database size={14} aria-hidden="true" />
        <span>当前运行尚未生成批次差异快照；不把未生成差异视为无变化。</span>
      </div>
    );
  }
  if (view.status === "malformed" || !view.value) {
    return (
      <section className="monitoring-daily-diff-summary malformed" aria-label="批次差异证据">
        <header>
          <strong>批次差异证据</strong>
          <FileWarning size={15} aria-hidden="true" />
        </header>
        <p className="monitoring-daily-diff-warning" role="alert">
          差异快照格式异常，暂不展示计数；请回到源批次与下方运行步骤核对。
        </p>
      </section>
    );
  }

  const { value } = view;
  return (
    <section className={`monitoring-daily-diff-summary ${view.status}`} aria-label="批次差异摘要">
      <header className="monitoring-daily-diff-head">
        <div>
          <strong>本批次与比较基线的显式差异</strong>
          <span>只展示冻结 diff 快照中的计数；差异数量不等于风险数量。</span>
        </div>
        <span className="monitoring-daily-diff-evidence">
          完整快照：{evidenceLabel(value.fullSnapshotProven)}
        </span>
      </header>
      <div className="monitoring-daily-diff-meta">
        <span>{value.previousBatchId || "比较基线待核对"} → {value.currentBatchId || "当前批次待核对"}</span>
        <span>{value.algorithmVersion || "算法版本待核对"}</span>
      </div>
      <div className="monitoring-daily-diff-grid">
        {METRICS.map(([field, label, tone]) => (
          <DiffMetric key={field} field={field} label={label} tone={tone} counts={value.counts} />
        ))}
      </div>
      <div className="monitoring-daily-diff-removal">
        <span>移除处置证据</span>
        <strong>可确认 {dailyDiffCountLabel(value.counts.removalEligibleRows)}</strong>
        <strong>阻断 {dailyDiffCountLabel(value.counts.removalBlockedRows)}</strong>
        <span>缺失域 {dailyDiffCountLabel(value.counts.missingDomains)}</span>
      </div>
      <DiffDetailDisclosure details={value.details} />
      {value.safetyReasons?.length > 0 && (
        <div className="monitoring-daily-diff-safety" role="alert">
          <AlertTriangle size={14} aria-hidden="true" />
          <div>
            <strong>继续规则 / AI 前先处理</strong>
            <ul>
              {value.safetyReasons.map((reason) => (
                <li key={reason.code}>
                  <span>{reason.label}</span>
                  <small>{reason.action}</small>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {view.issues.length > 0 && (
        <p className="monitoring-daily-diff-warning" role="alert">
          <AlertTriangle size={13} aria-hidden="true" />
          部分差异字段待核对；未提供或形状异常的字段保持为“待核对”，不会补成 0。
        </p>
      )}
      <small className="monitoring-daily-diff-source">
        快照 {value.snapshotId || "标识待核对"} · 输出摘要 {value.outputSha256 || "待核对"}
      </small>
    </section>
  );
}
