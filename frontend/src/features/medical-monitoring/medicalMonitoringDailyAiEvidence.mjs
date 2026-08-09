const STATUS_SET = new Set([
  "not_submitted",
  "running",
  "completed",
  "partial_completed",
  "failed",
]);

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
    issues.push(issue(field, "missing", "计数字段未提供。"));
    return null;
  }
  if (!Number.isSafeInteger(raw) || raw < 0) {
    issues.push(issue(field, "invalid", "计数不是严格非负整数。"));
    return null;
  }
  return raw;
}

export function medicalMonitoringAiFailureKind(code, message) {
  const haystack = `${code || ""} ${message || ""}`.toLowerCase();
  if (/timeout|timed[_ -]?out|超时/.test(haystack)) {
    return { kind: "timeout", label: "超时" };
  }
  if (/rate[_ -]?limit|throttl|限流/.test(haystack)) {
    return { kind: "rate_limit", label: "限流" };
  }
  if (/invalid[_ -]?(ai[_ -]?)?(output|json|structure)|response[_ -]?(invalid|empty)|结构化|无效.?json/.test(haystack)) {
    return { kind: "invalid_structure", label: "结构化输出无效" };
  }
  if (/low[_ -]?confidence|置信度/.test(haystack)) {
    return { kind: "low_confidence", label: "低置信度" };
  }
  if (/not[_ -]?configured|configuration|transport|unavailable|不可用|配置|传输/.test(haystack)) {
    return { kind: "unavailable", label: "配置或传输不可用" };
  }
  if (/stale[_ -]?input|revision[_ -]?(changed|stale)|来源修订|版本过期/.test(haystack)) {
    return { kind: "stale_input", label: "来源修订过期" };
  }
  if (/cancel|blocked|取消|阻断/.test(haystack)) {
    return { kind: "blocked", label: "任务阻断或取消" };
  }
  return { kind: "unknown", label: "失败原因待核对" };
}

function normalizeLineage(run, issues) {
  if (run === undefined || run === null) {
    issues.push(issue("run", "missing", "运行来源未提供。"));
    return {
      runId: null,
      batchId: null,
      engineVersion: null,
      rulePackRevision: null,
      ruleResolutionMode: null,
    };
  }
  if (!isRecord(run)) {
    issues.push(issue("run", "invalid", "运行来源形状异常。"));
    return {
      runId: null,
      batchId: null,
      engineVersion: null,
      rulePackRevision: null,
      ruleResolutionMode: null,
    };
  }
  const runId = readText(run, "run_id", issues, { required: true });
  const batchId = readText(run, "batch_id", issues, { required: true });
  const engineVersion = readText(run, "engine_version", issues, { required: true });
  const rulePackRevision = readText(run, "rule_pack_revision", issues);
  const ruleResolutionMode = readText(run, "rule_resolution_mode", issues);
  return {
    runId,
    batchId,
    engineVersion,
    rulePackRevision,
    ruleResolutionMode,
  };
}

function normalizeFailures(raw, issues) {
  if (raw === undefined || raw === null) {
    issues.push(issue("failures", "missing", "失败任务明细未提供。"));
    return null;
  }
  if (!Array.isArray(raw)) {
    issues.push(issue("failures", "invalid", "失败任务明细不是数组。"));
    return null;
  }
  const failures = [];
  raw.forEach((item, index) => {
    if (!isRecord(item)) {
      issues.push(issue(`failures[${index}]`, "invalid", "失败任务明细不是对象。"));
      return;
    }
    const jobId = readText(item, "job_id", issues, { required: true });
    if (!jobId) return;
    const code = readText(item, "failure_code", issues);
    const message = readText(item, "failure_message", issues);
    const failureKind = medicalMonitoringAiFailureKind(code, message);
    failures.push({
      jobId,
      sourceIndex: index,
      subjectId: readText(item, "subject_id", issues),
      status: readText(item, "status", issues),
      code,
      message,
      failureKind: failureKind.kind,
      failureLabel: failureKind.label,
    });
  });
  const seenJobIds = new Set();
  failures.forEach((failure) => {
    if (seenJobIds.has(failure.jobId)) {
      issues.push(issue("failures", "invalid", "失败任务明细包含重复 job_id；各条失败证据仍需分别核对。"));
    }
    seenJobIds.add(failure.jobId);
  });
  return failures;
}

function normalizeSubmitted(value, issues) {
  if (typeof value !== "boolean") {
    issues.push(issue("submitted", "missing", "AI提交状态未提供严格布尔值。"));
    return null;
  }
  return value;
}

function summarizeIssues(issues) {
  return issues.map(({ field, kind, message }) => ({ field, kind, message }));
}

export function normalizeMedicalMonitoringDailyAiEvidence({
  progress,
  run,
  submitted,
} = {}) {
  const issues = [];
  const submittedValue = normalizeSubmitted(submitted, issues);
  const lineage = normalizeLineage(run, issues);

  if (submittedValue === false) {
    return {
      status: issues.length > 0 ? "partial" : "not_submitted",
      value: {
        ...lineage,
        submitted: false,
        progressStatus: "not_submitted",
        counts: {
          total: null,
          queued: null,
          running: null,
          completed: null,
          failed: null,
          candidateCount: null,
        },
        failures: null,
        completionPercent: null,
      },
      issues: summarizeIssues(issues),
    };
  }

  if (progress === null || progress === undefined) {
    issues.push(issue("progress", "missing", "AI进度账本未返回。"));
    return {
      status: "unavailable",
      value: {
        ...lineage,
        submitted: submittedValue,
        progressStatus: null,
        counts: {
          total: null,
          queued: null,
          running: null,
          completed: null,
          failed: null,
          candidateCount: null,
        },
        failures: null,
        completionPercent: null,
      },
      issues: summarizeIssues(issues),
    };
  }
  if (!isRecord(progress)) {
    issues.push(issue("progress", "invalid", "AI进度账本形状异常。"));
    return {
      status: "malformed",
      value: null,
      issues: summarizeIssues(issues),
    };
  }

  const progressStatus = readText(progress, "status", issues, { required: true });
  if (progressStatus && !STATUS_SET.has(progressStatus)) {
    issues.push(issue("status", "invalid", "AI进度状态不在受支持的账本枚举内。"));
  }
  const counts = {
    total: readCount(progress, "total", issues),
    queued: readCount(progress, "queued", issues),
    running: readCount(progress, "running", issues),
    completed: readCount(progress, "completed", issues),
    failed: readCount(progress, "failed", issues),
    candidateCount: readCount(progress, "candidate_count", issues),
  };
  const failures = normalizeFailures(progress.failures, issues);
  const jobCounts = [counts.queued, counts.running, counts.completed, counts.failed];
  if (counts.total !== null && jobCounts.every((value) => value !== null)) {
    const accounted = jobCounts.reduce((sum, value) => sum + value, 0);
    if (accounted !== counts.total) {
      issues.push(issue("counts", "invalid", "任务分项计数与总任务数不一致。"));
    }
  }
  if (counts.failed !== null && failures !== null && counts.failed !== failures.length) {
    issues.push(issue("failures", "invalid", "失败计数与失败明细数量不一致。"));
  }
  const completionPercent = counts.total !== null && counts.total > 0 && counts.completed !== null
    ? Math.round((counts.completed / counts.total) * 100)
    : counts.total === 0 && counts.completed === 0
      ? 100
      : null;

  return {
    status: issues.length > 0 ? "partial" : "ready",
    value: {
      ...lineage,
      submitted: submittedValue,
      progressStatus: STATUS_SET.has(progressStatus) ? progressStatus : null,
      counts,
      failures,
      completionPercent,
    },
    issues: summarizeIssues(issues),
  };
}

export function medicalMonitoringAiStatusLabel(value) {
  return {
    not_submitted: "尚未提交",
    running: "复核中",
    completed: "已完成",
    partial_completed: "部分完成",
    failed: "全部失败",
  }[String(value || "")] || "待核对";
}

export function medicalMonitoringAiCountLabel(value) {
  return Number.isSafeInteger(value) && value >= 0 ? String(value) : "待核对";
}

export function medicalMonitoringAiFailureDisplayKey(failure, index = 0) {
  const jobId = text(failure?.jobId) || "missing";
  const sourceIndex = Number.isInteger(failure?.sourceIndex) ? failure.sourceIndex : index;
  return `ai-failure:${jobId}:${sourceIndex}`;
}
