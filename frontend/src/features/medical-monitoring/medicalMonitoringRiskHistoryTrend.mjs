const SEVERITY_RANK = Object.freeze({ critical: 4, high: 3, medium: 2, low: 1 });

function isObject(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function text(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function strictBoolean(value) {
  return typeof value === "boolean" ? value : null;
}

function severityLabel(value) {
  return ({ critical: "紧急", high: "高", medium: "中", low: "低" })[value] || "级别未提供";
}

function normalizeInstance(raw, index) {
  if (!isObject(raw)) return { status: "malformed", index, issues: ["实例不是对象"] };
  const risk = isObject(raw.risk) ? raw.risk : null;
  const snapshotId = text(raw.snapshot_id);
  const snapshotCreatedAt = text(raw.snapshot_created_at);
  const sourceBatchId = text(risk?.source_batch_id);
  const severity = text(risk?.severity);
  const batchDelta = text(risk?.batch_delta);
  const status = text(risk?.status);
  const current = strictBoolean(raw.is_current);
  const issues = [];
  if (!snapshotId) issues.push("快照标识缺失");
  if (!snapshotCreatedAt || Number.isNaN(Date.parse(snapshotCreatedAt))) issues.push("快照时间缺失或不可解析");
  if (!risk) issues.push("风险对象缺失");
  if (!severity || !SEVERITY_RANK[severity]) issues.push("风险级别缺失或未知");
  if (!batchDelta) issues.push("批次变化未提供");
  if (!status) issues.push("风险状态未提供");
  if (current === null) issues.push("当前实例标记形状异常");
  return {
    status: issues.length ? (issues.some((issue) => issue.includes("形状异常")) ? "malformed" : "partial") : "ok",
    index,
    snapshotId,
    snapshotCreatedAt,
    sourceBatchId,
    severity,
    severityLabel: severityLabel(severity),
    severityRank: SEVERITY_RANK[severity] || null,
    batchDelta,
    riskStatus: status,
    isCurrent: current === true,
    issues,
  };
}

function direction(previous, current) {
  if (!previous?.severityRank || !current?.severityRank) return "unknown";
  if (current.severityRank > previous.severityRank) return "up";
  if (current.severityRank < previous.severityRank) return "down";
  return "steady";
}

/**
 * Project the explicit cross-batch risk history into a compact visual trend.
 * This is a display aid only: it never describes clinical causality, severity
 * probability, or a risk being resolved merely because a point is absent.
 */
export function normalizeMedicalMonitoringRiskHistoryTrend(instances) {
  if (!Array.isArray(instances)) {
    return { status: "empty", points: [], issues: [], summary: null };
  }
  const normalized = instances.map(normalizeInstance);
  const snapshotIdCounts = new Map();
  normalized.forEach((item) => {
    if (item.status === "malformed" || !item.snapshotId) return;
    snapshotIdCounts.set(item.snapshotId, (snapshotIdCounts.get(item.snapshotId) || 0) + 1);
  });
  const identityRows = normalized.map((item) => {
    const identity = item.snapshotId || "";
    const duplicate = Boolean(identity && (snapshotIdCounts.get(identity) || 0) > 1);
    return {
      ...item,
      displaySourceIndex: item.index,
      displayIdentityState: !identity ? "missing" : duplicate ? "duplicate" : "ready",
      displayIdentityIssue: !identity
        ? "历史点缺少 snapshot_id；保留原始记录，暂不能确认单点来源"
        : duplicate
          ? "历史点 snapshot_id 重复；保留原始记录，暂不能确认单点来源"
          : "",
      displayKey: `risk-history:${identity || "missing"}:${item.index}`,
    };
  });
  const identityIssues = identityRows
    .filter((item) => item.displayIdentityState === "duplicate")
    .map((item) => `第 ${item.index + 1} 个实例：快照标识 ${item.snapshotId} 重复，趋势点保留但单点来源待核对。`);
  const issues = [
    ...identityRows.flatMap((item) => item.issues.map((issue) => `第 ${item.index + 1} 个实例：${issue}`)),
    ...identityIssues,
  ];
  const points = identityRows
    .filter((item) => item.status !== "malformed")
    .sort((left, right) => {
      const leftTime = Date.parse(left.snapshotCreatedAt || "");
      const rightTime = Date.parse(right.snapshotCreatedAt || "");
      if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) return leftTime - rightTime;
      return left.index - right.index;
    })
    .map((item, index, items) => ({
      ...item,
      direction: index ? direction(items[index - 1], item) : "initial",
    }));
  const current = points.find((point) => point.isCurrent) || points.at(-1) || null;
  const status = normalized.some((item) => item.status === "malformed")
    ? "malformed"
    : issues.length ? "partial" : points.length ? "available" : "empty";
  return {
    status,
    points,
    issues,
    summary: current ? {
      currentSeverity: current.severityLabel,
      currentBatchDelta: current.batchDelta,
      currentStatus: current.riskStatus,
      transitionCount: points.filter((point) => ["up", "down"].includes(point.direction)).length,
    } : null,
  };
}

export function medicalMonitoringRiskSeverityTone(severity) {
  if (severity === "critical") return "danger";
  if (severity === "high") return "high";
  if (severity === "medium") return "medium";
  if (severity === "low") return "low";
  return "unknown";
}

export function medicalMonitoringRiskTrendDirectionLabel(directionValue) {
  return ({ initial: "首次", up: "升高", down: "降低", steady: "持平", unknown: "待核对" })[directionValue] || "待核对";
}
