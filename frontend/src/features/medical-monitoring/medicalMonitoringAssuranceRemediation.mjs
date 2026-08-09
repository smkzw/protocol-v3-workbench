const SEVERITY_RANK = Object.freeze({ critical: 0, high: 1, medium: 2, low: 3 });
const OPEN_STATUSES = new Set([
  "open",
  "action_required",
  "pending_review",
  "in_review",
  "new",
  "reviewed",
  "query_draft",
  "submitted_for_approval",
]);

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function text(value) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function issue(field, kind, message) {
  return { field, kind, message };
}

function optionalText(raw, field, issues) {
  if (raw === undefined || raw === null || raw === "") return null;
  const value = text(raw);
  if (!value) {
    issues.push(issue(field, "invalid", "字段不是非空文本。"));
    return null;
  }
  return value;
}

function requiredText(raw, field, issues) {
  const value = optionalText(raw, field, issues);
  if (!value) issues.push(issue(field, "missing", "整改项缺少显式风险实例 ID。"));
  return value;
}

function optionalBoolean(raw, field, issues) {
  if (raw === undefined || raw === null) {
    issues.push(issue(field, "missing", "关闭证据状态未提供。"));
    return null;
  }
  if (typeof raw !== "boolean") {
    issues.push(issue(field, "invalid", "关闭证据状态不是严格布尔值。"));
    return null;
  }
  return raw;
}

function rowPriority(row) {
  const openRank = OPEN_STATUSES.has(String(row.status || "").toLowerCase()) ? 0 : 1;
  const severityRank = SEVERITY_RANK[String(row.severity || "").toLowerCase()] ?? 9;
  const evidenceRank = row.closureEvidencePresent === false ? 0 : row.closureEvidencePresent === true ? 1 : 2;
  return [openRank, severityRank, evidenceRank, row.riskInstanceId || "", row.sourceIndex ?? 0];
}

function compareRows(left, right) {
  const leftKey = rowPriority(left);
  const rightKey = rowPriority(right);
  for (let index = 0; index < leftKey.length; index += 1) {
    if (leftKey[index] === rightKey[index]) continue;
    if (typeof leftKey[index] === "number") return leftKey[index] - rightKey[index];
    return String(leftKey[index]).localeCompare(String(rightKey[index]), "zh-CN", { numeric: true });
  }
  return 0;
}

export function normalizeMedicalMonitoringAssuranceRemediation(matrix) {
  if (matrix === null || matrix === undefined) {
    return { status: "empty", rows: [], totalCount: null, issues: [] };
  }
  if (!Array.isArray(matrix)) {
    return {
      status: "malformed",
      rows: [],
      totalCount: null,
      issues: [issue("remediation_matrix", "invalid", "整改矩阵不是数组。")],
    };
  }

  const issues = [];
  const rows = [];
  matrix.forEach((raw, index) => {
    if (!isRecord(raw)) {
      issues.push(issue(`remediation_matrix[${index}]`, "invalid", "整改项不是对象。"));
      return;
    }
    const path = `remediation_matrix[${index}]`;
    const riskInstanceId = requiredText(raw.risk_instance_id, `${path}.risk_instance_id`, issues);
    if (!riskInstanceId) return;
    rows.push({
      riskInstanceId,
      sourceIndex: index,
      riskKey: optionalText(raw.risk_key, `${path}.risk_key`, issues),
      subjectId: optionalText(raw.subject_id, `${path}.subject_id`, issues),
      siteId: optionalText(raw.site_id, `${path}.site_id`, issues),
      severity: optionalText(raw.severity, `${path}.severity`, issues),
      status: optionalText(raw.status, `${path}.status`, issues),
      closureEvidencePresent: optionalBoolean(raw.closure_evidence_present, `${path}.closure_evidence_present`, issues),
    });
  });

  const riskInstanceCounts = new Map();
  rows.forEach((row) => {
    riskInstanceCounts.set(row.riskInstanceId, (riskInstanceCounts.get(row.riskInstanceId) || 0) + 1);
  });
  const normalizedRows = rows.map((row) => {
    const identityState = riskInstanceCounts.get(row.riskInstanceId) > 1 ? "duplicate" : "ready";
    if (identityState === "duplicate") {
      issues.push(issue(`remediation_matrix[${row.sourceIndex}].risk_instance_id`, "invalid", "整改矩阵包含重复风险实例；保留整改项但暂不可单独聚焦。"));
    }
    return {
      ...row,
      identityState,
      identityIssue: identityState === "duplicate"
        ? "风险实例 ID 重复；保留整改项但暂不可单独聚焦。"
        : null,
    };
  });

  const sortedRows = [...normalizedRows].sort(compareRows);
  const openCount = sortedRows.filter((row) => OPEN_STATUSES.has(String(row.status || "").toLowerCase())).length;
  const missingClosureEvidenceCount = sortedRows.filter((row) => row.closureEvidencePresent !== true).length;
  return {
    status: issues.length > 0 ? "partial" : sortedRows.length > 0 ? "ready" : "empty",
    rows: sortedRows,
    totalCount: matrix.length,
    validCount: normalizedRows.length,
    invalidCount: matrix.length - normalizedRows.length,
    openCount,
    missingClosureEvidenceCount,
    issues: issues.map(({ field, kind, message }) => ({ field, kind, message })),
  };
}

export function assuranceRemediationDisplayKey(row, index = 0) {
  const identity = text(row?.riskInstanceId) || "missing";
  const sourceIndex = Number.isInteger(row?.sourceIndex) ? row.sourceIndex : index;
  return `assurance-remediation:${identity}:${sourceIndex}`;
}

export function assuranceRemediationSeverityLabel(value) {
  return { critical: "紧急", high: "高", medium: "中", low: "低" }[String(value || "").toLowerCase()] || value || "待核对";
}

export function assuranceRemediationStatusLabel(value) {
  return {
    open: "开放",
    action_required: "需行动",
    pending_review: "待医学复核",
    in_review: "复核中",
    new: "新识别",
    reviewed: "已医学复核",
    query_draft: "Query草稿",
    submitted_for_approval: "已提交审批",
    closed: "已关闭",
    resolved: "已解决",
  }[String(value || "").toLowerCase()] || value || "待核对";
}
