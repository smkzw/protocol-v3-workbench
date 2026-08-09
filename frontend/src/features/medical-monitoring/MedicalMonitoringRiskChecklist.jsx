import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownUp,
  ChevronLeft,
  ChevronRight,
  Download,
  Filter,
  RefreshCw,
  RotateCcw,
  X,
} from "lucide-react";
import {
  activeRiskChecklistFilters,
  DEFAULT_RISK_CHECKLIST_QUERY,
  normalizeRiskChecklistQuery,
  resetRiskChecklistForQueryChange,
  RISK_CHECKLIST_COLUMNS,
} from "./medicalMonitoringChecklistState.mjs";
import {
  riskChecklistCategoryTags,
  riskEvidenceCoverageMessage,
  riskEvidenceCoverageSummary,
  riskEvidenceLineageMessage,
  riskEvidenceLineageSummary,
  riskRowEvidenceBadge,
  riskDispositionStatusLabel,
  medicalMonitoringRiskDisplayKey,
  severityLabel,
} from "./medicalMonitoringModels.mjs";

const DISPOSITION_OPTIONS = [
  "pending_review",
  "reviewed",
  "query_draft",
  "submitted_for_approval",
  "explained_no_external_action",
  "data_correction",
  "follow_up",
  "pd_update",
  "safety_pv_collaboration",
  "continue_observation",
  "duplicate_not_applicable",
];

function severityTone(severity) {
  if (severity === "critical") return "danger";
  if (severity === "high" || severity === "medium") return "warning";
  return "neutral";
}

function filterValueLabel(filter, taxonomyByCode) {
  if (filter.key === "severity") return severityLabel(filter.value);
  if (filter.key === "riskCategoryCode") {
    return taxonomyByCode.get(filter.value)?.label || "其他医学复核";
  }
  if (filter.key === "dispositionStatus") {
    return riskDispositionStatusLabel(filter.value);
  }
  return filter.value;
}

function riskRowAccessibleLabel(risk) {
  const categories = riskChecklistCategoryTags(risk).join("、");
  const disposition = riskDispositionStatusLabel(
    risk.dispositionState || risk.disposition_state || risk.status,
  );
  return [
    risk.subject ? `受试者 ${risk.subject}` : "受试者未提供",
    risk.site ? `中心 ${risk.site}` : "中心未提供",
    `级别 ${severityLabel(risk.severity) || "未提供"}`,
    categories ? `类别 ${categories}` : "",
    risk.title || "风险标题未提供",
    `当前处置 ${disposition}`,
    risk.identityAmbiguous ? "风险身份重复，仅可读，暂不可定位" : "",
    risk.unread ? "未读" : "",
  ].filter(Boolean).join("，");
}

function taxonomyCategoryRows(taxonomy) {
  return Array.isArray(taxonomy?.categories)
    ? taxonomy.categories.filter((item) => item && typeof item === "object" && !Array.isArray(item))
    : [];
}

function FilterControl({ column, value, taxonomy, onChange }) {
  if (column.kind === "severity") {
    return (
      <select value={value} onChange={(event) => onChange(event.target.value)} autoFocus>
        <option value="">全部级别</option>
        <option value="critical">紧急</option>
        <option value="high">高</option>
        <option value="medium">中</option>
        <option value="low">低</option>
      </select>
    );
  }
  if (column.kind === "category") {
    return (
      <select value={value} onChange={(event) => onChange(event.target.value)} autoFocus>
        <option value="">全部类别</option>
        {taxonomyCategoryRows(taxonomy).map((category) => (
          <option value={category.code} key={category.code}>{category.label}</option>
        ))}
      </select>
    );
  }
  if (column.kind === "disposition") {
    return (
      <select value={value} onChange={(event) => onChange(event.target.value)} autoFocus>
        <option value="">全部处置</option>
        {DISPOSITION_OPTIONS.map((status) => (
          <option value={status} key={status}>{riskDispositionStatusLabel(status)}</option>
        ))}
      </select>
    );
  }
  return (
    <input
      type={column.kind === "date" ? "date" : "text"}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={column.kind === "date" ? "YYYY-MM-DD" : `输入${column.label}`}
      autoFocus
    />
  );
}

export function MedicalMonitoringRiskChecklist({
  rows = [],
  selectedRiskId = "",
  onSelect,
  query = DEFAULT_RISK_CHECKLIST_QUERY,
  onQueryChange,
  taxonomy = null,
  total = null,
  loading = false,
  error = "",
  isCurrentSnapshot = true,
  onRefreshCurrent,
  onRetry,
  onExport,
  exporting = false,
  lockedFilterKeys = [],
}) {
  const normalizedQuery = normalizeRiskChecklistQuery(query);
  const [openFilterKey, setOpenFilterKey] = useState("");
  const [draftValue, setDraftValue] = useState("");
  const filterLayerRef = useRef(null);
  const safeRows = Array.isArray(rows)
    ? rows.filter((row) => row && typeof row === "object" && !Array.isArray(row))
    : [];
  const riskIdentityCounts = new Map();
  safeRows.forEach((risk) => {
    const identity = typeof risk.id === "string" ? risk.id.trim() : "";
    if (identity) riskIdentityCounts.set(identity, (riskIdentityCounts.get(identity) || 0) + 1);
  });
  const displayRows = safeRows.map((risk, sourceIndex) => {
    const identity = typeof risk.id === "string" ? risk.id.trim() : "";
    const duplicate = Boolean(identity && (riskIdentityCounts.get(identity) || 0) > 1);
    return {
      ...risk,
      sourceIndex: Number.isInteger(risk.sourceIndex) ? risk.sourceIndex : sourceIndex,
      identityAmbiguous: risk.identityAmbiguous === true || duplicate,
      identityIssue: risk.identityIssue || (duplicate
        ? "风险身份重复；保留证据但暂不可定位"
        : ""),
    };
  });
  const safeTaxonomyCategories = useMemo(() => taxonomyCategoryRows(taxonomy), [taxonomy]);
  const totalIsKnown = typeof total === "number" && Number.isInteger(total) && total >= 0;
  const safeTotal = totalIsKnown ? total : 0;
  const taxonomyByCode = useMemo(
    () => new Map(safeTaxonomyCategories.map((item) => [item.code, item])),
    [safeTaxonomyCategories],
  );
  const activeFilters = activeRiskChecklistFilters(normalizedQuery);
  const pageCount = Math.max(1, Math.ceil(safeTotal / normalizedQuery.pageSize));
  const hasReportedRowsButNoSafeRows = !loading && !error && safeTotal > 0 && safeRows.length === 0;
  const lineageSummary = riskEvidenceLineageSummary(displayRows);
  const locked = new Set(Array.isArray(lockedFilterKeys) ? lockedFilterKeys : []);
  const interactive = typeof onQueryChange === "function";
  const evidenceCoverage = riskEvidenceCoverageSummary(displayRows);
  const totalLabel = error
    ? "风险数量未读取"
    : loading
      ? "正在读取风险"
      : !totalIsKnown
        ? "风险数量待读取"
        : `共 ${safeTotal} 条`;

  useEffect(() => {
    if (!openFilterKey) return undefined;
    const closeOnOutsideClick = (event) => {
      if (!filterLayerRef.current?.contains(event.target)) setOpenFilterKey("");
    };
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setOpenFilterKey("");
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [openFilterKey]);

  const updateQuery = (next) => onQueryChange?.(normalizeRiskChecklistQuery(next));
  const applyFilter = (column) => {
    updateQuery(resetRiskChecklistForQueryChange(normalizedQuery, {
      [column.filterKey]: draftValue,
    }));
    setOpenFilterKey("");
  };
  const clearFilter = (filterKey) => {
    updateQuery(resetRiskChecklistForQueryChange(normalizedQuery, {
      [filterKey]: "",
    }));
  };
  const toggleSort = (columnKey) => {
    const direction = normalizedQuery.sortBy === columnKey
      && normalizedQuery.sortDirection === "asc"
      ? "desc"
      : "asc";
    updateQuery(resetRiskChecklistForQueryChange(normalizedQuery, {
      sortBy: columnKey,
      sortDirection: direction,
    }));
  };
  const resetAll = () => updateQuery(DEFAULT_RISK_CHECKLIST_QUERY);
  const hasNonDefaultSort = normalizedQuery.sortBy !== DEFAULT_RISK_CHECKLIST_QUERY.sortBy
    || normalizedQuery.sortDirection !== DEFAULT_RISK_CHECKLIST_QUERY.sortDirection;

  return (
    <div className="risk-checklist-table" role="table" aria-label="项目医学风险Checklist">
      <div className="risk-checklist-column-state">
        <span>
          {totalLabel}
          {activeFilters.length ? ` · 已筛选 ${activeFilters.length} 项` : ""}
        </span>
        {(typeof onExport === "function" || interactive) && (
          <div className="risk-checklist-actions">
            {typeof onExport === "function" && (
              <button
                type="button"
                className="icon-button"
                disabled={loading || exporting}
                aria-label="导出当前筛选风险及证据"
                title={exporting ? "正在生成风险及证据导出包" : "导出当前筛选风险及证据"}
                onClick={onExport}
              >
                <Download size={15} />
              </button>
            )}
            {interactive && (
              <button
                className="icon-text-button"
                disabled={!activeFilters.length && !hasNonDefaultSort}
                title="清除筛选并恢复默认排序"
                onClick={resetAll}
              >
                <RotateCcw size={14} />重置
              </button>
            )}
          </div>
        )}
      </div>
      {lineageSummary.status !== "empty" && (
        <div className="risk-checklist-column-state" role="status" aria-label="风险来源绑定状态">
          <span>{riskEvidenceLineageMessage(lineageSummary)}</span>
        </div>
      )}
      {evidenceCoverage.status !== "empty" && (
        <div className="risk-checklist-column-state" role="status" aria-label="当前页证据覆盖状态">
          <span>{riskEvidenceCoverageMessage(evidenceCoverage)}</span>
        </div>
      )}
      {interactive && activeFilters.length > 0 && (
        <div className="risk-checklist-filter-chips" aria-label="已应用筛选">
          {activeFilters.map((filter) => (
            <button
              type="button"
              key={filter.key}
              onClick={() => clearFilter(filter.key)}
              title={`清除${filter.label}筛选`}
            >
              <span>{filter.label}</span>
              <strong>{filterValueLabel(filter, taxonomyByCode)}</strong>
              <X size={12} />
            </button>
          ))}
          <button type="button" className="clear-all" onClick={resetAll}>清除全部</button>
        </div>
      )}
      {!isCurrentSnapshot && (
        <div className="risk-checklist-stale" role="status">
          <span>当前查看的是较早快照，分页内容仍保持一致。</span>
          <button type="button" onClick={() => onRefreshCurrent?.()}><RefreshCw size={13} />查看最新</button>
        </div>
      )}
      {error && (
        <div className="risk-checklist-error" role="alert">
          <span>{error}</span>
          {typeof onRetry === "function" && (
            <button type="button" onClick={onRetry} disabled={loading}>
              <RefreshCw size={13} />重试读取
            </button>
          )}
        </div>
      )}
      <div className="risk-checklist-header" role="row" ref={filterLayerRef}>
        {RISK_CHECKLIST_COLUMNS.map((column) => {
          const filterActive = Boolean(normalizedQuery[column.filterKey]);
          const filterLocked = locked.has(column.filterKey);
          return (
            <div className="risk-checklist-header-cell" role="columnheader" key={column.key}>
              <button
                type="button"
                className={`risk-checklist-sort ${normalizedQuery.sortBy === column.key ? "active" : ""}`}
                aria-sort={normalizedQuery.sortBy === column.key
                  ? normalizedQuery.sortDirection === "asc" ? "ascending" : "descending"
                  : "none"}
                onClick={() => toggleSort(column.key)}
                title={`按${column.label}排序`}
                disabled={!interactive}
              >
                <span>{column.label}</span><ArrowDownUp size={13} />
              </button>
              {interactive && (
                <button
                  type="button"
                  className={`risk-checklist-filter-trigger ${filterActive ? "active" : ""}`}
                  aria-label={`筛选${column.label}`}
                  title={filterLocked ? `当前范围已限定${column.label}` : `筛选${column.label}`}
                  disabled={filterLocked}
                  onClick={() => {
                    setOpenFilterKey((current) => current === column.key ? "" : column.key);
                    setDraftValue(normalizedQuery[column.filterKey] || "");
                  }}
                >
                  <Filter size={13} />
                </button>
              )}
              {openFilterKey === column.key && (
                <div className="risk-checklist-filter-popover">
                  <strong>{column.label}</strong>
                  <FilterControl
                    column={column}
                    value={draftValue}
                    taxonomy={taxonomy}
                    onChange={setDraftValue}
                  />
                  <div>
                    <button
                      type="button"
                      onClick={() => {
                        setDraftValue("");
                        updateQuery(resetRiskChecklistForQueryChange(normalizedQuery, {
                          [column.filterKey]: "",
                        }));
                        setOpenFilterKey("");
                      }}
                    >
                      清除
                    </button>
                    <button type="button" className="primary" onClick={() => applyFilter(column)}>
                      应用
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="risk-checklist-body" aria-busy={loading}>
        {loading && safeRows.length === 0
          ? Array.from({ length: 6 }, (_, index) => (
            <div className="risk-checklist-row skeleton" role="row" key={`loading-${index}`}>
              {RISK_CHECKLIST_COLUMNS.map((column) => (
                <span role="cell" key={column.key}><i /></span>
              ))}
            </div>
          ))
          : displayRows.map((risk, index) => {
            const selectable = typeof onSelect === "function" && risk.identityAmbiguous !== true;
            return (
            <div
              className={`risk-checklist-row ${selectedRiskId === risk.id && !risk.identityAmbiguous ? "selected" : ""}`}
              key={medicalMonitoringRiskDisplayKey(risk, risk.sourceIndex ?? index)}
              role="row"
              tabIndex={selectable ? 0 : -1}
              aria-selected={selectedRiskId === risk.id && !risk.identityAmbiguous}
              aria-disabled={risk.identityAmbiguous ? "true" : undefined}
              aria-label={riskRowAccessibleLabel(risk)}
              onClick={() => selectable && onSelect?.(risk)}
              onKeyDown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                if (selectable) onSelect?.(risk);
              }}
            >
              <span role="cell"><strong>{risk.subject || "-"}</strong></span>
              <span role="cell">{risk.site || "-"}</span>
              <span role="cell">
                <i className={`tag ${severityTone(risk.severity)}`}>{severityLabel(risk.severity)}</i>
              </span>
              <span className="risk-category-cell" role="cell">
                {riskChecklistCategoryTags(risk).map((category) => (
                  <i className={`tag ${category === "Safety/PV" ? "warning" : "neutral"}`} key={category}>
                    {category}
                  </i>
                ))}
              </span>
              <span className="risk-title-cell" role="cell">
                {risk.unread && <i className="risk-unread-dot" aria-label="未读" title="未读" />}
                <strong>{risk.title}</strong>
                <i
                  className={`tag ${riskRowEvidenceBadge(risk).status === "bound" ? "success" : riskRowEvidenceBadge(risk).status === "partial" ? "warning" : "danger"}`}
                  title={riskRowEvidenceBadge(risk).status === "bound" ? "仅表示有显式定位，不代表医学风险已确认关闭" : "请回到来源证据核对，不能将缺失/异常视为无风险"}
                >
                  {riskRowEvidenceBadge(risk).label}
                </i>
                {risk.identityAmbiguous && (
                  <i
                    className="tag warning"
                    title={risk.identityIssue || "风险身份重复；保留证据但暂不可定位"}
                  >
                    身份重复，仅可读
                  </i>
                )}
              </span>
              <span role="cell">
                <i className="tag neutral">
                  {riskDispositionStatusLabel(
                    risk.dispositionState || risk.disposition_state || risk.status,
                  )}
                </i>
              </span>
              <span role="cell">{risk.age}</span>
            </div>
            );
          })}
        {hasReportedRowsButNoSafeRows ? (
          <div className="empty-state risk-checklist-shape-warning" role="alert">
            当前页没有可安全展示的风险记录；接口报告 {safeTotal} 条，不能据此判定无风险。请刷新或检查快照/数据形状。
          </div>
        ) : !loading && !safeRows.length && !error && (
          <div className="empty-state">当前条件下没有风险项；这不等同于项目无风险。</div>
        )}
      </div>
      {interactive && !error && <div className="risk-checklist-pagination" aria-label="风险列表分页">
        <span>第 {Math.min(normalizedQuery.page, pageCount)} / {pageCount} 页</span>
        <label>
          <span>每页</span>
          <select
            value={normalizedQuery.pageSize}
            onChange={(event) => updateQuery(resetRiskChecklistForQueryChange(normalizedQuery, {
              pageSize: Number(event.target.value),
            }))}
          >
            {[25, 50, 100, 200].map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </label>
        <button
          type="button"
          className="icon-button"
          title="上一页"
          disabled={loading || normalizedQuery.page <= 1}
          onClick={() => updateQuery({ ...normalizedQuery, page: normalizedQuery.page - 1 })}
        >
          <ChevronLeft size={15} />
        </button>
        <button
          type="button"
          className="icon-button"
          title="下一页"
          disabled={loading || normalizedQuery.page >= pageCount}
          onClick={() => updateQuery({ ...normalizedQuery, page: normalizedQuery.page + 1 })}
        >
          <ChevronRight size={15} />
        </button>
      </div>}
    </div>
  );
}

export default MedicalMonitoringRiskChecklist;
