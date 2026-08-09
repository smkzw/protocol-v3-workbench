const EXPECTED_STEPS = Object.freeze([
  { stepName: "initial_baseline", label: "首批基线" },
  { stepName: "batch_diff", label: "批次差异" },
  { stepName: "deterministic_rules", label: "医学规则" },
  { stepName: "independent_ai_submission", label: "AI复核提交" },
  { stepName: "risk_snapshot_assembly", label: "风险汇总" },
]);

const STATUS_SET = new Set(["running", "completed", "failed", "skipped"]);
const DETAIL_SPECS = Object.freeze({
  initial_baseline: [
    ["batch_id", "批次"],
    ["reason", "说明"],
  ],
  batch_diff: [
    ["diff_snapshot_id", "差异快照"],
    ["algorithm_output_sha256", "算法输出"],
  ],
  deterministic_rules: [
    ["candidate_count", "规则候选"],
    ["diagnostic_count", "诊断"],
    ["evaluated_record_count", "评估记录"],
    ["failed_resolution_count", "解析失败"],
  ],
  independent_ai_submission: [
    ["selected_subject_count", "受试者"],
    ["job_count", "任务"],
  ],
  risk_snapshot_assembly: [
    ["risk_snapshot_id", "风险快照"],
    ["risk_count", "风险项"],
    ["blocker_count", "阻断"],
    ["resolution_complete", "解析完整"],
  ],
});

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function text(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function issue(field, kind, message) {
  return { field, kind, message };
}

function readText(record, field, issues, { required = false } = {}) {
  const raw = record?.[field];
  if (raw === undefined || raw === null || raw === "") {
    if (required) issues.push(issue(field, "missing", "字段未提供。"));
    return null;
  }
  const value = text(raw);
  if (!value) {
    issues.push(issue(field, "invalid", "字段不是非空文本。"));
    return null;
  }
  return value;
}

function readCount(record, field, issues) {
  const raw = record?.[field];
  if (raw === undefined || raw === null) {
    issues.push(issue(field, "missing", "尝试次数未提供。"));
    return null;
  }
  if (!Number.isSafeInteger(raw) || raw < 0) {
    issues.push(issue(field, "invalid", "尝试次数不是严格非负整数。"));
    return null;
  }
  return raw;
}

function readBoolean(record, field, issues) {
  const raw = record?.[field];
  if (raw === undefined || raw === null) {
    issues.push(issue(field, "missing", "布尔字段未提供。"));
    return null;
  }
  if (typeof raw !== "boolean") {
    issues.push(issue(field, "invalid", "字段不是严格布尔值。"));
    return null;
  }
  return raw;
}

function readSha256(record, field, issues, { required = false } = {}) {
  const raw = record?.[field];
  if (raw === undefined || raw === null || raw === "") {
    if (required) issues.push(issue(field, "missing", "摘要未提供。"));
    return null;
  }
  if (typeof raw !== "string" || !/^[a-f0-9]{64}$/.test(raw)) {
    issues.push(issue(field, "invalid", "摘要不是小写 SHA-256。"));
    return null;
  }
  return raw;
}

function normalizeDetailValue(raw, field, issues) {
  if (raw === undefined || raw === null || raw === "") return null;
  if (field === "resolution_complete") {
    return typeof raw === "boolean"
      ? (raw ? "是" : "否")
      : (issues.push(issue(field, "invalid", "解析完整字段不是严格布尔值。")), null);
  }
  if ([
    "candidate_count",
    "diagnostic_count",
    "evaluated_record_count",
    "failed_resolution_count",
    "selected_subject_count",
    "job_count",
    "risk_count",
    "blocker_count",
  ].includes(field)) {
    return Number.isSafeInteger(raw) && raw >= 0
      ? String(raw)
      : (issues.push(issue(field, "invalid", "详情计数不是严格非负整数。")), null);
  }
  const value = text(raw);
  if (!value) {
    issues.push(issue(field, "invalid", "详情字段不是非空文本。"));
    return null;
  }
  return value;
}

function normalizeDetails(raw, stepName, issues) {
  if (raw === undefined || raw === null) {
    issues.push(issue(`${stepName}.details`, "missing", "步骤详情未提供。"));
    return [];
  }
  if (!isRecord(raw)) {
    issues.push(issue(`${stepName}.details`, "invalid", "步骤详情形状异常。"));
    return [];
  }
  return (DETAIL_SPECS[stepName] || [])
    .map(([field, label]) => {
      const value = normalizeDetailValue(raw[field], field, issues);
      return value === null ? null : { field, label, value };
    })
    .filter(Boolean)
    .slice(0, 3);
}

function normalizeStep(raw, index, issues) {
  if (!isRecord(raw)) {
    issues.push(issue(`steps[${index}]`, "invalid", "步骤记录不是对象。"));
    return null;
  }
  const stepName = readText(raw, "step_name", issues, { required: true });
  if (!stepName) return null;
  const status = readText(raw, "status", issues, { required: true });
  if (status && !STATUS_SET.has(status)) {
    issues.push(issue(`steps[${index}].status`, "invalid", "步骤状态不在账本枚举内。"));
  }
  const path = `steps[${index}]`;
  const attemptCount = readCount(raw, "attempt_count", issues);
  const startedAt = readText(raw, "started_at", issues, { required: true });
  const updatedAt = readText(raw, "updated_at", issues, { required: true });
  const finishedAt = readText(raw, "finished_at", issues);
  const inputSha256 = readSha256(raw, "input_sha256", issues, { required: true });
  const outputSha256 = readSha256(raw, "output_sha256", issues, {
    required: status === "completed",
  });
  if (stepName && status === "completed" && !outputSha256) {
    // The readSha256 call records the missing/invalid output; keep this explicit
    // field on the normalized row so the UI can show the evidence gap.
  }
  return {
    stepName,
    label: EXPECTED_STEPS.find((item) => item.stepName === stepName)?.label || "其他步骤",
    status: STATUS_SET.has(status) ? status : null,
    attemptCount,
    startedAt,
    updatedAt,
    finishedAt,
    inputSha256,
    outputSha256,
    outputBound: Boolean(outputSha256),
    details: normalizeDetails(raw.details, stepName, issues),
    known: EXPECTED_STEPS.some((item) => item.stepName === stepName),
    sourceIndex: index,
  };
}

function placeholder(item, status = "not_started") {
  return {
    stepName: item.stepName,
    label: item.label,
    status,
    attemptCount: null,
    startedAt: null,
    updatedAt: null,
    finishedAt: null,
    inputSha256: null,
    outputSha256: null,
    outputBound: false,
    details: [],
    known: true,
    sourceIndex: null,
  };
}

function statusSummary(rows) {
  return {
    completed: rows.filter((row) => row.status === "completed").length,
    running: rows.filter((row) => row.status === "running").length,
    failed: rows.filter((row) => row.status === "failed").length,
    skipped: rows.filter((row) => row.status === "skipped").length,
    outputMissing: rows.filter((row) => row.status === "completed" && !row.outputBound).length,
    knownRecorded: rows.filter((row) => row.sourceIndex !== null && row.known).length,
    unknownRecorded: rows.filter((row) => row.sourceIndex !== null && !row.known).length,
  };
}

export function normalizeMedicalMonitoringDailyRunEvidence(steps) {
  if (steps === null || steps === undefined) {
    return { status: "empty", value: null, issues: [] };
  }
  if (!Array.isArray(steps)) {
    return {
      status: "malformed",
      value: null,
      issues: [issue("steps", "invalid", "步骤账本不是数组。")],
    };
  }
  if (steps.length === 0) {
    return { status: "empty", value: null, issues: [] };
  }

  const issues = [];
  const normalized = steps
    .map((raw, index) => normalizeStep(raw, index, issues))
    .filter(Boolean);
  const seen = new Set();
  const deduplicated = normalized.filter((row) => {
    if (seen.has(row.stepName)) {
      issues.push(issue(`steps.${row.stepName}`, "invalid", "步骤账本包含重复步骤。"));
      return false;
    }
    seen.add(row.stepName);
    return true;
  });
  const byName = new Map(deduplicated.map((row) => [row.stepName, row]));
  const initial = byName.get("initial_baseline");
  const diff = byName.get("batch_diff");
  const rows = EXPECTED_STEPS.map((item) => {
    const existing = byName.get(item.stepName);
    if (existing) return existing;
    if (item.stepName === "initial_baseline" && diff?.status === "completed") {
      return placeholder(item, "not_applicable");
    }
    if (item.stepName === "batch_diff" && initial?.status === "completed") {
      return placeholder(item, "not_applicable");
    }
    return placeholder(item);
  });
  const extras = deduplicated
    .filter((row) => !row.known)
    .sort((left, right) => left.sourceIndex - right.sourceIndex);
  const allRows = [...rows, ...extras];
  return {
    status: issues.length > 0 ? "partial" : "ready",
    value: {
      rows: allRows,
      summary: statusSummary(allRows),
    },
    issues: issues.map(({ field, kind, message }) => ({ field, kind, message })),
  };
}

export function medicalMonitoringRunStepStatusLabel(value) {
  return {
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    skipped: "已跳过",
    not_started: "未开始",
    not_applicable: "不适用",
  }[String(value || "")] || "待核对";
}

export function medicalMonitoringRunStepCountLabel(value) {
  return Number.isSafeInteger(value) && value >= 0 ? String(value) : "待核对";
}

export function medicalMonitoringRunStepEvidenceLabel(row) {
  if (row?.status === "not_started") return "尚未生成";
  if (row?.status === "not_applicable") return "不适用";
  if (row?.outputBound) return "输出已绑定";
  return "待核对";
}
