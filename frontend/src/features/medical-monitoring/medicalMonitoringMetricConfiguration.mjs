const STATUS_LABELS = Object.freeze({
  context_unavailable: "上下文未绑定",
  loading: "读取中",
  read_error: "读取失败",
  contract_error: "响应不可用",
  candidate_only: "待医学确认",
  issues_only: "需核对",
  empty: "未形成候选",
  idle: "待读取",
});

const STATUS_TONES = Object.freeze({
  context_unavailable: "warning",
  loading: "info",
  read_error: "danger",
  contract_error: "danger",
  candidate_only: "warning",
  issues_only: "warning",
  empty: "info",
  idle: "info",
});

const DIRECTION_LABELS = Object.freeze({
  lower_is_better: "越低越好",
  higher_is_better: "越高越好",
  stable_range: "参考范围内稳定",
});

function cleanText(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

function cleanArray(value) {
  return Array.isArray(value) ? value : [];
}

function normalizeCandidateIdentity(candidate, sourceIndex, identityCounts) {
  const candidateId = cleanText(candidate?.candidate_id);
  const metricKey = cleanText(candidate?.metric_key);
  const identity = candidateId || metricKey;
  const duplicate = Boolean(identity && (identityCounts.get(identity) || 0) > 1);
  return {
    ...candidate,
    sourceIndex,
    identityState: !identity ? "missing" : duplicate ? "duplicate" : "ready",
    identityIssue: !identity
      ? "候选缺少 candidate_id/metric_key；仅可读，暂不能据此确认指标"
      : duplicate
        ? "候选 candidate_id/metric_key 重复；仅可读，暂不能据此确认指标"
        : "",
  };
}

function normalizeCandidates(value) {
  const candidates = cleanArray(value).filter((item) => item && typeof item === "object");
  const identityCounts = new Map();
  candidates.forEach((candidate) => {
    const identity = cleanText(candidate.candidate_id) || cleanText(candidate.metric_key);
    if (identity) identityCounts.set(identity, (identityCounts.get(identity) || 0) + 1);
  });
  return candidates.map((candidate, sourceIndex) => normalizeCandidateIdentity(
    candidate,
    sourceIndex,
    identityCounts,
  ));
}

function errorMessage(error) {
  const message = cleanText(error?.message);
  return message || "指标候选读取失败；当前页面不把读取失败解释为无风险。";
}

/**
 * Builds an explicit project/version/batch context for the read-only candidate
 * endpoint. Display labels are deliberately never treated as identifiers.
 */
export function metricConfigurationContext({
  projectId = "",
  protocolVersionId = "",
  batchId = "",
} = {}) {
  const project = cleanText(projectId);
  const protocolVersion = cleanText(protocolVersionId);
  const batch = cleanText(batchId);
  const missing = [
    !project ? "project_id" : "",
    !protocolVersion ? "protocol_version_id" : "",
    !batch ? "batch_id" : "",
  ].filter(Boolean);
  return Object.freeze({
    projectId: project,
    protocolVersionId: protocolVersion,
    batchId: batch,
    missing,
    ready: missing.length === 0,
  });
}

/**
 * Resolves only explicitly bound identifiers from the monitoring route or
 * module binding. A display batch label is not a safe substitute for batch_id.
 */
export function metricConfigurationContextFromMonitoring({
  projectId = "",
  routeState = {},
  binding = {},
} = {}) {
  const route = routeState && typeof routeState === "object" ? routeState : {};
  const moduleBinding = binding && typeof binding === "object" ? binding : {};
  return metricConfigurationContext({
    projectId,
    protocolVersionId: route.protocol_version_id
      || moduleBinding.protocol_version_id
      || moduleBinding.protocolVersionId,
    batchId: route.batch_id
      || moduleBinding.batch_id
      || moduleBinding.batchId,
  });
}

export function metricConfigurationReviewState({
  context = metricConfigurationContext(),
  payload = null,
  loading = false,
  error = null,
} = {}) {
  const resolvedContext = metricConfigurationContext(context);
  const base = {
    context: resolvedContext,
    candidates: [],
    issues: [],
    medicallyConfirmed: false,
    usableCandidateCount: 0,
    candidateOnly: false,
    requiresMedicalConfirmation: false,
    bundleSha256: "",
    status: "idle",
    tone: STATUS_TONES.idle,
    label: STATUS_LABELS.idle,
    message: "指标候选尚未读取。",
  };

  if (!resolvedContext.ready) {
    return Object.freeze({
      ...base,
      status: "context_unavailable",
      tone: STATUS_TONES.context_unavailable,
      label: STATUS_LABELS.context_unavailable,
      message: "需要明确的方案版本和完整冻结 listing 批次后，才能读取指标候选。当前未绑定上下文，不把空态解释为无风险。",
    });
  }
  if (loading) {
    return Object.freeze({
      ...base,
      status: "loading",
      tone: STATUS_TONES.loading,
      label: STATUS_LABELS.loading,
      message: "正在读取候选配置；仅展示只读候选，不会自动确认或发布。",
    });
  }
  if (error) {
    return Object.freeze({
      ...base,
      status: "read_error",
      tone: STATUS_TONES.read_error,
      label: STATUS_LABELS.read_error,
      message: errorMessage(error),
    });
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return Object.freeze(base);
  }

  const candidates = normalizeCandidates(payload.candidates);
  const issues = cleanArray(payload.issues).filter((item) => item && typeof item === "object");
  const medicallyConfirmed = payload.medically_confirmed === true;
  const status = cleanText(payload.status);
  const candidateOnly = payload.review?.candidate_only === true || status === "candidate_only";
  const requiresMedicalConfirmation = payload.review?.requires_medical_confirmation === true
    || candidates.length > 0;
  const usableCandidateCount = Number.isInteger(payload.usable_candidate_count)
    ? Math.max(0, payload.usable_candidate_count)
    : candidates.filter((item) => !cleanArray(item.review_flags).length).length;

  if (medicallyConfirmed || status !== "candidate_only" || !candidateOnly) {
    return Object.freeze({
      ...base,
      candidates,
      issues,
      medicallyConfirmed,
      usableCandidateCount,
      candidateOnly,
      requiresMedicalConfirmation,
      bundleSha256: cleanText(payload.bundle_sha256),
      status: "contract_error",
      tone: STATUS_TONES.contract_error,
      label: STATUS_LABELS.contract_error,
      message: "候选响应未保持 candidate-only 契约，已停止展示为可用配置；请回到来源和接口证据核对。",
    });
  }

  const reviewStatus = candidates.length ? "candidate_only" : issues.length ? "issues_only" : "empty";
  const message = candidates.length
    ? `${candidates.length} 个指标候选待医学确认；${issues.length ? `${issues.length} 个来源/字段问题需先核对。` : "当前没有医学确认或发布动作。"}`
    : issues.length
      ? `未形成可展示的指标候选，保留 ${issues.length} 个核对问题；当前不把空态解释为无风险。`
      : "当前方案/批次未形成指标候选；请确认来源声明和冻结 listing 是否完整。";
  return Object.freeze({
    ...base,
    candidates,
    issues,
    medicallyConfirmed,
    usableCandidateCount,
    candidateOnly,
    requiresMedicalConfirmation,
    bundleSha256: cleanText(payload.bundle_sha256),
    status: reviewStatus,
    tone: STATUS_TONES[reviewStatus],
    label: STATUS_LABELS[reviewStatus],
    message,
  });
}

export function metricConfigurationStatusLabel(status) {
  return STATUS_LABELS[cleanText(status)] || STATUS_LABELS.idle;
}

export function metricConfigurationDirectionLabel(direction) {
  return DIRECTION_LABELS[cleanText(direction)] || "方向待医学确认";
}

export function metricConfigurationCandidateSource(candidate) {
  if (!candidate || typeof candidate !== "object") return "来源待补充";
  return [candidate.fact_source_locator, candidate.field_profile_batch_id]
    .map(cleanText)
    .filter(Boolean)
    .join(" · ") || "来源定位待补充";
}

/**
 * Display-only key for a read-only metric candidate row. It never becomes a
 * metric identity or confirmation payload; sourceIndex keeps incomplete or
 * duplicate candidate evidence visible instead of allowing React to collapse it.
 */
export function metricConfigurationCandidateDisplayKey(candidate = {}, sourceIndex = 0) {
  const identity = cleanText(candidate.candidate_id) || cleanText(candidate.metric_key) || "missing";
  const index = Number.isInteger(sourceIndex) && sourceIndex >= 0 ? sourceIndex : 0;
  return `metric-candidate:${identity}:${index}`;
}
