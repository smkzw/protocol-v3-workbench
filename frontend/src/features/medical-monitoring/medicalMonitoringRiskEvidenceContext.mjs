function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function textValue(value) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function firstPresent(record, fields) {
  for (const field of fields) {
    if (record[field] !== undefined && record[field] !== null) return record[field];
  }
  return undefined;
}

function issue(field, kind, message) {
  return { field, kind, message };
}

function readRequiredText(record, fields, field, issues) {
  const value = firstPresent(record, fields);
  const text = textValue(value);
  if (!text) {
    issues.push(issue(field, "missing", "显式标识未提供。"));
    return null;
  }
  return text;
}

function readOptionalText(record, fields, field, issues) {
  const value = firstPresent(record, fields);
  if (value === undefined || value === null || value === "") return null;
  const text = textValue(value);
  if (!text) {
    issues.push(issue(field, "invalid", "字段不是非空文本。"));
    return null;
  }
  return text;
}

function readOptionalBoolean(record, fields, field, issues) {
  const value = firstPresent(record, fields);
  if (value === undefined || value === null) return null;
  if (typeof value !== "boolean") {
    issues.push(issue(field, "invalid", "字段不是严格布尔值。"));
    return null;
  }
  return value;
}

function readStringList(record, fields, field, issues) {
  const value = firstPresent(record, fields);
  if (value === undefined || value === null) return null;
  if (!Array.isArray(value) || value.some((item) => !textValue(item))) {
    issues.push(issue(field, "invalid", "数组或数组成员形状异常。"));
    return null;
  }
  const values = value.map((item) => item.trim());
  if (new Set(values).size !== values.length) {
    issues.push(issue(field, "invalid", "数组包含重复定位。"));
    return null;
  }
  return values;
}

function readSourceRefs(record, issues) {
  const value = firstPresent(record, ["sourceRefs", "source_refs"]);
  if (value === undefined || value === null) return null;
  if (!Array.isArray(value)) {
    issues.push(issue("source_refs", "invalid", "来源引用不是数组。"));
    return null;
  }
  const refs = [];
  for (const [index, raw] of value.entries()) {
    if (!isRecord(raw)) {
      issues.push(issue(`source_refs[${index}]`, "invalid", "来源引用不是对象。"));
      continue;
    }
    const locator = textValue(raw.locator);
    const sourceId = textValue(raw.source_id);
    const label = textValue(raw.label);
    const sourceType = textValue(raw.source_type);
    if (!locator && !sourceId && !label) {
      issues.push(issue(`source_refs[${index}]`, "invalid", "来源引用缺少定位、来源 ID 或标签。"));
      continue;
    }
    refs.push({ locator, sourceId, label, sourceType });
  }
  return refs;
}

function normalizeDisplayIdentity(value) {
  const text = textValue(value);
  return text && !["-", "未提供", "未标识中心", "未标识受试者"].includes(text) ? text : null;
}

function evidenceState({ locators, refs, malformed }) {
  if (malformed) return "malformed";
  if ((locators?.length || 0) > 0) return "bound";
  if ((refs?.length || 0) > 0) return "reference_only";
  return "missing";
}

function lineageState({ snapshotId, sourceVersion, batch }) {
  if (sourceVersion) return "version_bound";
  if (snapshotId) return "snapshot_bound";
  if (batch) return "batch_only";
  return "missing";
}

export function normalizeMedicalMonitoringRiskEvidenceContext(risk) {
  if (!isRecord(risk)) {
    return {
      status: "malformed",
      value: null,
      issues: [issue("risk", "invalid", "当前风险对象形状异常。")],
    };
  }

  const issues = [];
  const riskInstanceId = readRequiredText(risk, ["riskId", "risk_instance_id"], "risk_instance_id", issues);
  const riskKey = readRequiredText(risk, ["riskKey", "risk_key"], "risk_key", issues);
  const scopeLabel = readOptionalText(risk, ["scopeLabel", "scope_label"], "scope_label", issues);
  const subjectId = normalizeDisplayIdentity(firstPresent(risk, ["subject", "subject_id"]));
  const siteId = normalizeDisplayIdentity(firstPresent(risk, ["site", "site_id"]));
  const snapshotId = readOptionalText(risk, ["snapshotId", "snapshot_id"], "snapshot_id", issues);
  const sourceVersion = readOptionalText(risk, ["sourceVersion", "source_version"], "source_version", issues);
  const batch = readOptionalText(risk, ["batch", "sourceBatchId", "source_batch_id"], "batch", issues);
  const severity = readOptionalText(risk, ["severity"], "severity", issues);
  const status = readOptionalText(risk, ["status"], "status", issues);
  const dispositionState = readOptionalText(risk, ["dispositionState", "disposition_state"], "disposition_state", issues);
  const evidenceLocators = readStringList(risk, ["evidenceLocators", "evidence_locators", "evidence_span_ids"], "evidence_locators", issues);
  const sourceRefs = readSourceRefs(risk, issues);
  const sourceEvidenceShape = firstPresent(risk, ["sourceEvidenceShape", "source_evidence_shape"]);
  const declaredMalformed = sourceEvidenceShape === "malformed";
  if (sourceEvidenceShape !== undefined && sourceEvidenceShape !== null
    && !["valid", "malformed"].includes(sourceEvidenceShape)) {
    issues.push(issue("source_evidence_shape", "invalid", "来源证据形状状态不受支持。"));
  }
  const unread = readOptionalBoolean(risk, ["unread"], "unread", issues);
  const needsAction = readOptionalBoolean(risk, ["needsAction", "needs_action"], "needs_action", issues);
  const safetyPvFlag = readOptionalBoolean(risk, ["safetyPvFlag", "safety_pv_flag"], "safety_pv_flag", issues);
  const evidenceStatus = evidenceState({
    locators: evidenceLocators,
    refs: sourceRefs,
    malformed: declaredMalformed || issues.some((item) => item.field.startsWith("evidence_") || item.field.startsWith("source_refs")),
  });
  const lineageStatus = lineageState({ snapshotId, sourceVersion, batch });
  const statusHasGap = evidenceStatus !== "bound" || ["missing", "batch_only"].includes(lineageStatus);

  return {
    status: issues.length === 0 && !statusHasGap ? "ready" : "partial",
    value: {
      riskInstanceId,
      riskKey,
      scopeLabel,
      subjectId,
      siteId,
      snapshotId,
      sourceVersion,
      batch,
      severity,
      status,
      dispositionState,
      unread,
      needsAction,
      safetyPvFlag,
      evidence: {
        status: evidenceStatus,
        locatorCount: evidenceLocators?.length ?? null,
        referenceCount: sourceRefs?.length ?? null,
      },
      lineage: {
        status: lineageStatus,
        snapshotId,
        sourceVersion,
        batch,
      },
    },
    issues: issues.map(({ field, kind, message }) => ({ field, kind, message })),
  };
}

export function riskEvidenceContextStateLabel(state) {
  return {
    bound: "证据已定位",
    reference_only: "仅有来源引用",
    missing: "证据定位缺失",
    malformed: "证据形状异常",
  }[state] || "证据待核对";
}

export function riskEvidenceContextLineageLabel(state) {
  return {
    version_bound: "来源版本已绑定",
    snapshot_bound: "快照已绑定",
    batch_only: "仅有批次号",
    missing: "来源链路缺失",
  }[state] || "来源链路待核对";
}

