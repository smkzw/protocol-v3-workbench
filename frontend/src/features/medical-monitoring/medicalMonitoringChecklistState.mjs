export const RISK_CHECKLIST_COLUMNS = Object.freeze([
  { key: "subject_id", label: "受试者编号", filterKey: "subjectId", kind: "text" },
  { key: "site_id", label: "中心编号", filterKey: "siteId", kind: "text" },
  { key: "severity", label: "风险级别", filterKey: "severity", kind: "severity" },
  {
    key: "risk_category_code",
    label: "风险类别",
    filterKey: "riskCategoryCode",
    kind: "category",
  },
  { key: "risk_item", label: "具体风险项", filterKey: "riskItem", kind: "text" },
  {
    key: "disposition_status",
    label: "当前处置",
    filterKey: "dispositionStatus",
    kind: "disposition",
  },
  { key: "updated_at", label: "更新时间", filterKey: "updatedAt", kind: "date" },
]);

export const DEFAULT_RISK_CHECKLIST_QUERY = Object.freeze({
  subjectId: "",
  siteId: "",
  severity: "",
  riskCategoryCode: "",
  riskItem: "",
  dispositionStatus: "",
  updatedAt: "",
  sortBy: "updated_at",
  sortDirection: "desc",
  page: 1,
  pageSize: 50,
  snapshotId: "",
});

const SORT_FIELDS = new Set(RISK_CHECKLIST_COLUMNS.map((column) => column.key));
const SEVERITIES = new Set(["critical", "high", "medium", "low"]);
const DIRECTIONS = new Set(["asc", "desc"]);

function text(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

function boundedInteger(value, fallback, minimum, maximum) {
  const parsed = Number.parseInt(text(value), 10);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) return fallback;
  return parsed;
}

export function normalizeRiskChecklistQuery(value = {}) {
  const candidate = value && typeof value === "object" ? value : {};
  const severity = text(candidate.severity).toLowerCase();
  const sortBy = text(candidate.sortBy).toLowerCase();
  const sortDirection = text(candidate.sortDirection).toLowerCase();
  return {
    subjectId: text(candidate.subjectId),
    siteId: text(candidate.siteId),
    severity: SEVERITIES.has(severity) ? severity : "",
    riskCategoryCode: text(candidate.riskCategoryCode),
    riskItem: text(candidate.riskItem),
    dispositionStatus: text(candidate.dispositionStatus),
    updatedAt: text(candidate.updatedAt),
    sortBy: SORT_FIELDS.has(sortBy) ? sortBy : DEFAULT_RISK_CHECKLIST_QUERY.sortBy,
    sortDirection: DIRECTIONS.has(sortDirection)
      ? sortDirection
      : DEFAULT_RISK_CHECKLIST_QUERY.sortDirection,
    page: boundedInteger(candidate.page, 1, 1, Number.MAX_SAFE_INTEGER),
    pageSize: boundedInteger(candidate.pageSize, 50, 1, 200),
    snapshotId: text(candidate.snapshotId),
  };
}

export function riskChecklistQueryFromRoute(route = {}) {
  return normalizeRiskChecklistQuery({
    subjectId: route.filter_subject_id,
    siteId: route.filter_site_id,
    severity: route.filter_severity,
    riskCategoryCode: route.filter_risk_category_code,
    riskItem: route.filter_risk_item,
    dispositionStatus: route.filter_disposition_status,
    updatedAt: route.filter_updated_at,
    sortBy: route.risk_sort_by,
    sortDirection: route.risk_sort_direction,
    page: route.risk_page,
    pageSize: route.risk_page_size,
    snapshotId: route.risk_snapshot_id,
  });
}

export function riskChecklistRoutePatch(query = {}) {
  const normalized = normalizeRiskChecklistQuery(query);
  return {
    filter_subject_id: normalized.subjectId,
    filter_site_id: normalized.siteId,
    filter_severity: normalized.severity,
    filter_risk_category_code: normalized.riskCategoryCode,
    filter_risk_item: normalized.riskItem,
    filter_disposition_status: normalized.dispositionStatus,
    filter_updated_at: normalized.updatedAt,
    risk_sort_by: normalized.sortBy === DEFAULT_RISK_CHECKLIST_QUERY.sortBy
      ? ""
      : normalized.sortBy,
    risk_sort_direction:
      normalized.sortBy === DEFAULT_RISK_CHECKLIST_QUERY.sortBy
      && normalized.sortDirection === DEFAULT_RISK_CHECKLIST_QUERY.sortDirection
        ? ""
        : normalized.sortDirection,
    risk_page: normalized.page === 1 ? "" : String(normalized.page),
    risk_page_size: normalized.pageSize === 50 ? "" : String(normalized.pageSize),
    risk_snapshot_id: normalized.snapshotId,
  };
}

export function riskChecklistApiQuery(query = {}, scope = {}) {
  const normalized = normalizeRiskChecklistQuery(query);
  const scopeType = text(scope.scope);
  const scopedSiteId = scopeType === "site" ? text(scope.siteId) : "";
  const scopedSubjectId = scopeType === "subject" ? text(scope.subjectId) : "";
  return {
    snapshotId: normalized.snapshotId,
    siteId: scopedSiteId || normalized.siteId,
    subjectId: scopedSubjectId || normalized.subjectId,
    riskCategoryCode: normalized.riskCategoryCode,
    riskItem: normalized.riskItem,
    severity: normalized.severity,
    dispositionStatus: normalized.dispositionStatus,
    updatedAt: normalized.updatedAt,
    sortBy: normalized.sortBy,
    sortDirection: normalized.sortDirection,
    page: normalized.page,
    pageSize: normalized.pageSize,
  };
}

export function resetRiskChecklistForQueryChange(query, patch) {
  return normalizeRiskChecklistQuery({
    ...query,
    ...patch,
    page: 1,
    snapshotId: "",
  });
}

export function activeRiskChecklistFilters(query = {}) {
  const normalized = normalizeRiskChecklistQuery(query);
  return RISK_CHECKLIST_COLUMNS
    .map((column) => ({
      key: column.filterKey,
      columnKey: column.key,
      label: column.label,
      value: normalized[column.filterKey],
    }))
    .filter((item) => Boolean(item.value));
}

export function riskChecklistQuerySignature(query = {}) {
  const normalized = normalizeRiskChecklistQuery(query);
  return JSON.stringify(normalized);
}
