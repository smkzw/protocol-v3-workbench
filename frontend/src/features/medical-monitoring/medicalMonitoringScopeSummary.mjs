const LEVELS = Object.freeze(["trial", "site", "subject"]);

function isObject(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function nonNegativeInteger(value) {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : null;
}

function nonEmptyString(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function countMap(value) {
  if (!isObject(value)) return null;
  const entries = Object.entries(value).map(([label, count]) => ({
    label: nonEmptyString(label) || "未分类",
    count: nonNegativeInteger(count),
  }));
  if (entries.some((entry) => entry.count === null)) return null;
  return entries
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label))
    .filter((entry) => entry.count > 0);
}

function categoryLabelMap(value) {
  if (!isObject(value) || !Array.isArray(value.categories)) return Object.freeze({});
  const labels = {};
  const conflicts = new Set();
  value.categories.forEach((item) => {
    if (!isObject(item)) return;
    const code = nonEmptyString(item.code);
    const label = nonEmptyString(item.label);
    if (!code || !label || conflicts.has(code)) return;
    if (Object.prototype.hasOwnProperty.call(labels, code) && labels[code] !== label) {
      delete labels[code];
      conflicts.add(code);
      return;
    }
    labels[code] = label;
  });
  return Object.freeze(labels);
}

function levelLabel(level) {
  return level === "trial" ? "整个试验" : level === "site" ? "中心" : "受试者";
}

function normalizeRow(raw, level, index) {
  if (!isObject(raw)) {
    return {
      status: "malformed",
      level,
      index,
      reason: `${levelLabel(level)}第 ${index + 1} 行不是对象。`,
    };
  }
  const scopeId = nonEmptyString(raw.scope_id);
  const riskCount = nonNegativeInteger(raw.risk_count);
  const needsActionCount = nonNegativeInteger(raw.needs_action_count);
  const unreadCount = nonNegativeInteger(raw.unread_count);
  const countFields = { risk_count: riskCount, needs_action_count: needsActionCount, unread_count: unreadCount };
  const malformedFields = Object.entries(countFields)
    .filter(([field, count]) => raw[field] !== undefined && count === null)
    .map(([field]) => field);
  const missingFields = Object.entries(countFields)
    .filter(([field, count]) => raw[field] === undefined || count === null)
    .map(([field]) => field);
  const severityCounts = raw.severity_counts === undefined ? [] : countMap(raw.severity_counts);
  const categoryCounts = raw.category_counts === undefined ? [] : countMap(raw.category_counts);
  const batchDeltaCounts = raw.batch_delta_counts === undefined ? [] : countMap(raw.batch_delta_counts);
  if (raw.severity_counts !== undefined && severityCounts === null) malformedFields.push("severity_counts");
  if (raw.category_counts !== undefined && categoryCounts === null) malformedFields.push("category_counts");
  if (raw.batch_delta_counts !== undefined && batchDeltaCounts === null) malformedFields.push("batch_delta_counts");
  return {
    status: malformedFields.length ? "malformed" : missingFields.length || !scopeId ? "partial" : "ok",
    level,
    scopeId,
    sourceIndex: index,
    identityAmbiguous: false,
    label: scopeId || `${levelLabel(level)}标识缺失`,
    riskCount,
    needsActionCount,
    unreadCount,
    severityCounts: severityCounts || [],
    categoryCounts: categoryCounts || [],
    batchDeltaCounts: batchDeltaCounts || [],
    malformedFields,
    missingFields,
  };
}

function normalizeLevel(raw, level) {
  if (level === "trial") {
    return raw === undefined
      ? { status: "missing", rows: [] }
      : { status: "ok", rows: [normalizeRow(raw, level, 0)] };
  }
  if (raw === undefined) return { status: "missing", rows: [] };
  if (!Array.isArray(raw)) {
    return { status: "malformed", rows: [], reason: `${levelLabel(level)}汇总不是数组。` };
  }
  const rows = raw.map((item, index) => normalizeRow(item, level, index));
  const seenScopeIds = new Map();
  const identityIssues = [];
  rows.forEach((row, index) => {
    if (!row.scopeId) return;
    const previousIndex = seenScopeIds.get(row.scopeId);
    if (previousIndex === undefined) {
      seenScopeIds.set(row.scopeId, index);
      return;
    }
    rows[index].identityAmbiguous = true;
    rows[previousIndex].identityAmbiguous = true;
    const issue = `${levelLabel(level)}标识 ${row.scopeId} 重复，已阻止歧义行聚焦。`;
    if (!identityIssues.includes(issue)) identityIssues.push(issue);
  });
  const status = rows.some((row) => row.status === "malformed")
    ? "malformed"
    : rows.some((row) => row.status === "partial" || row.identityAmbiguous)
      ? "partial"
      : "ok";
  return { status, rows, identityIssues };
}

function sortRows(rows) {
  return [...rows].sort((left, right) => (
    (right.needsActionCount ?? -1) - (left.needsActionCount ?? -1)
    || (right.unreadCount ?? -1) - (left.unreadCount ?? -1)
    || (right.riskCount ?? -1) - (left.riskCount ?? -1)
    || left.label.localeCompare(right.label)
  ));
}

/**
 * Normalize the explicit risk-index rollup for the compact main-page summary.
 * Missing/invalid values remain null or a blocked level; the UI must not turn
 * them into zero, infer identities from free text, or call an empty level safe.
 */
export function normalizeMedicalMonitoringScopeSummary(rollup) {
  if (!isObject(rollup)) {
    return {
      status: "empty",
      levels: Object.fromEntries(LEVELS.map((level) => [level, { status: "missing", rows: [] }])),
      trial: null,
      sites: [],
      subjects: [],
      issues: [],
    };
  }
  const levels = {
    trial: normalizeLevel(rollup.trial, "trial"),
    site: normalizeLevel(rollup.sites, "site"),
    subject: normalizeLevel(rollup.subjects, "subject"),
  };
  const issues = LEVELS.flatMap((level) => {
    const state = levels[level];
    const reasons = [];
    if (state.status === "missing") reasons.push(`${levelLabel(level)}汇总未提供。`);
    if (state.status === "malformed") reasons.push(state.reason || `${levelLabel(level)}汇总字段形状异常。`);
    reasons.push(...(state.identityIssues || []));
    state.rows.forEach((row) => {
      if (row.status === "malformed") reasons.push(`${row.label}：字段形状异常。`);
      else if (row.status === "partial") reasons.push(`${row.label}：部分计数或身份缺失。`);
    });
    return reasons;
  });
  const hasAnyRow = Boolean(levels.trial.rows.length || levels.site.rows.length || levels.subject.rows.length);
  const status = !hasAnyRow && issues.length ? "partial"
    : issues.some((issue) => issue.includes("形状异常")) ? "malformed"
      : issues.length ? "partial" : "available";
  return {
    status,
    levels,
    trial: levels.trial.rows[0] || null,
    sites: sortRows(levels.site.rows.filter((row) => row.status !== "malformed")),
    subjects: sortRows(levels.subject.rows.filter((row) => row.status !== "malformed")),
    issues,
  };
}

export function medicalMonitoringScopeLabel(level) {
  return LEVELS.includes(level) ? levelLabel(level) : "风险范围";
}

export function medicalMonitoringScopeNumber(value, fallback = "—") {
  return nonNegativeInteger(value) === null ? fallback : String(value);
}

export function medicalMonitoringScopeRowKey(row, index = 0) {
  const level = LEVELS.includes(row?.level) ? row.level : "scope";
  const identity = nonEmptyString(row?.scopeId) || "missing";
  const sourceIndex = Number.isInteger(row?.sourceIndex) ? row.sourceIndex : index;
  return `${level}:${identity}:${sourceIndex}`;
}

export function medicalMonitoringScopeCategoryLabelMap(taxonomy) {
  return categoryLabelMap(taxonomy);
}

export function medicalMonitoringScopeLevels() {
  return [...LEVELS];
}
