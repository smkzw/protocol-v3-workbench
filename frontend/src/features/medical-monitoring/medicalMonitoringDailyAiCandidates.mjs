const CANDIDATE_STATUS_SET = new Set([
  "proposed",
  "accepted",
  "rejected",
  "superseded",
]);
const CONFIDENCE_STATUS_SET = new Set(["not_scored", "low", "review_required"]);

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function text(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function issue(field, kind, message) {
  return { field, kind, message };
}

function requiredText(record, field, issues) {
  const value = text(record?.[field]);
  if (!value) issues.push(issue(field, "missing", "字段未提供非空文本。"));
  return value;
}

function optionalText(record, field, issues) {
  const raw = record?.[field];
  if (raw === undefined || raw === null || raw === "") return null;
  const value = text(raw);
  if (!value) issues.push(issue(field, "invalid", "字段不是非空文本。"));
  return value;
}

function nonNegativeInteger(record, field, issues, { required = true } = {}) {
  const raw = record?.[field];
  if (raw === undefined || raw === null) {
    if (required) issues.push(issue(field, "missing", "计数字段未提供。"));
    return null;
  }
  if (!Number.isSafeInteger(raw) || raw < 0) {
    issues.push(issue(field, "invalid", "计数不是严格非负整数。"));
    return null;
  }
  return raw;
}

function sha256(record, field, issues, { required = true } = {}) {
  const raw = record?.[field];
  if (raw === undefined || raw === null || raw === "") {
    if (required) issues.push(issue(field, "missing", "SHA-256 未提供。"));
    return null;
  }
  if (typeof raw !== "string" || !/^[a-f0-9]{64}$/.test(raw)) {
    issues.push(issue(field, "invalid", "字段不是小写 SHA-256。"));
    return null;
  }
  return raw;
}

function strictBoolean(record, field, issues) {
  const raw = record?.[field];
  if (typeof raw !== "boolean") {
    issues.push(issue(field, "invalid", "字段不是严格布尔值。"));
    return null;
  }
  return raw;
}

function normalizeConfidenceSummary(raw, path, issues) {
  if (!isRecord(raw)) {
    issues.push(issue(path, "missing", "置信度摘要未提供或形状异常。"));
    return null;
  }
  const status = requiredText(raw, "status", issues);
  if (status && !CONFIDENCE_STATUS_SET.has(status)) {
    issues.push(issue(`${path}.status`, "invalid", "置信度状态不受支持。"));
  }
  const label = requiredText(raw, "label", issues);
  const confidenceFloor = raw.confidence_floor === null
    ? null
    : typeof raw.confidence_floor === "number" && Number.isFinite(raw.confidence_floor)
      && raw.confidence_floor >= 0 && raw.confidence_floor <= 1
      ? raw.confidence_floor
      : (issues.push(issue(`${path}.confidence_floor`, "invalid", "置信度下限形状异常。")), null);
  const threshold = typeof raw.threshold === "number" && Number.isFinite(raw.threshold)
    && raw.threshold >= 0 && raw.threshold <= 1
    ? raw.threshold
    : (issues.push(issue(`${path}.threshold`, "invalid", "置信度阈值形状异常。")), null);
  const claimCount = nonNegativeInteger(raw, "claim_count", issues);
  const requiresUserReview = strictBoolean(raw, "requires_user_review", issues);
  const requiresAdditionalEvidence = strictBoolean(raw, "requires_additional_evidence", issues);
  const automationPermitted = strictBoolean(raw, "automation_permitted", issues);
  if (automationPermitted === true) {
    issues.push(issue(`${path}.automation_permitted`, "invalid", "候选自动采纳必须保持关闭。"));
  }
  const nextStep = requiredText(raw, "next_step", issues);
  return {
    status: CONFIDENCE_STATUS_SET.has(status) ? status : null,
    label,
    confidenceFloor,
    threshold,
    claimCount,
    requiresUserReview,
    requiresAdditionalEvidence,
    automationPermitted,
    nextStep,
  };
}

function normalizeEvidence(raw, candidateInputRevision, path, issues) {
  if (!Array.isArray(raw)) {
    issues.push(issue(path, "invalid", "候选证据不是数组。"));
    return [];
  }
  return raw.map((item, index) => {
    const rowPath = `${path}[${index}]`;
    if (!isRecord(item)) {
      issues.push(issue(rowPath, "invalid", "候选证据不是对象。"));
      return null;
    }
    const evidenceId = requiredText(item, "evidence_id", issues);
    const sourceEntryId = requiredText(item, "source_entry_id", issues);
    const sourceContentSha256 = sha256(item, "source_content_sha256", issues);
    const locator = requiredText(item, "locator", issues);
    const inputRevisionSha256 = sha256(item, "input_revision_sha256", issues);
    if (candidateInputRevision && inputRevisionSha256 && candidateInputRevision !== inputRevisionSha256) {
      issues.push(issue(`${rowPath}.input_revision_sha256`, "invalid", "证据输入修订与候选不一致。"));
    }
    return {
      evidenceId,
      sourceEntryId,
      sourceContentSha256,
      locator,
      quote: optionalText(item, "quote", issues),
      inputRevisionSha256,
      sourceIndex: index,
    };
  }).filter(Boolean);
}

function normalizeClaims(raw, path, issues) {
  if (!Array.isArray(raw)) {
    issues.push(issue(path, "invalid", "候选声明不是数组。"));
    return [];
  }
  const normalized = raw.map((item, index) => {
    const rowPath = `${path}[${index}]`;
    if (!isRecord(item)) {
      issues.push(issue(rowPath, "invalid", "候选声明不是对象。"));
      return null;
    }
    const claimId = requiredText(item, "claim_id", issues);
    const kind = requiredText(item, "kind", issues);
    const claimText = requiredText(item, "text", issues);
    const confidence = typeof item.confidence === "number" && Number.isFinite(item.confidence)
      && item.confidence >= 0 && item.confidence <= 1
      ? item.confidence
      : (issues.push(issue(`${rowPath}.confidence`, "invalid", "声明置信度形状异常。")), null);
    const evidenceIds = Array.isArray(item.evidence_ids)
      && item.evidence_ids.every((value) => text(value))
      ? item.evidence_ids.map((value) => value.trim())
      : (issues.push(issue(`${rowPath}.evidence_ids`, "invalid", "声明证据 ID 形状异常。")), []);
    return { claimId, kind, text: claimText, confidence, evidenceIds, sourceIndex: index };
  }).filter(Boolean);
  const claimIdCounts = new Map();
  normalized.forEach((claim) => {
    if (claim.claimId) claimIdCounts.set(claim.claimId, (claimIdCounts.get(claim.claimId) || 0) + 1);
  });
  return normalized.map((claim) => {
    const identityState = !claim.claimId
      ? "missing"
      : claimIdCounts.get(claim.claimId) > 1
        ? "duplicate"
        : "ready";
    if (identityState === "missing") {
      issues.push(issue(`${path}[${claim.sourceIndex}].claim_id`, "missing", "声明 claim_id 缺失；保留声明但暂不可单独定位。"));
    } else if (identityState === "duplicate") {
      issues.push(issue(`${path}[${claim.sourceIndex}].claim_id`, "invalid", "声明 ID 重复；保留声明但暂不可单独定位。"));
    }
    return {
      ...claim,
      identityState,
      identityIssue: identityState === "missing"
        ? "声明 claim_id 缺失；保留声明但暂不可单独定位。"
        : identityState === "duplicate"
          ? "声明 claim_id 重复；保留声明但暂不可单独定位。"
          : null,
    };
  });
}

function normalizeCandidate(raw, index, issues) {
  const path = `candidates[${index}]`;
  if (!isRecord(raw)) {
    issues.push(issue(path, "invalid", "候选包装不是对象。"));
    return null;
  }
  const subjectId = requiredText(raw, "subject_id", issues);
  const jobId = requiredText(raw, "job_id", issues);
  if (!isRecord(raw.candidate)) {
    issues.push(issue(`${path}.candidate`, "invalid", "候选正文形状异常。"));
    return null;
  }
  const candidate = raw.candidate;
  const candidateId = requiredText(candidate, "candidate_id", issues);
  const candidateType = requiredText(candidate, "candidate_type", issues);
  const taskType = requiredText(candidate, "task_type", issues);
  const title = requiredText(candidate, "title", issues);
  const status = requiredText(candidate, "status", issues);
  if (status && !CANDIDATE_STATUS_SET.has(status)) {
    issues.push(issue(`${path}.candidate.status`, "invalid", "候选状态不受支持。"));
  }
  const inputRevisionSha256 = sha256(candidate, "input_revision_sha256", issues);
  const claims = normalizeClaims(candidate.claims, `${path}.candidate.claims`, issues);
  const evidence = normalizeEvidence(candidate.evidence, inputRevisionSha256, `${path}.candidate.evidence`, issues);
  const confidenceSummary = normalizeConfidenceSummary(
    candidate.confidence_summary,
    `${path}.candidate.confidence_summary`,
    issues,
  );
  return {
    subjectId,
    jobId,
    candidateId,
    sourceIndex: index,
    candidateType,
    taskType,
    title,
    text: optionalText(candidate, "text", issues),
    status: CANDIDATE_STATUS_SET.has(status) ? status : null,
    inputRevisionSha256,
    promptVersion: requiredText(candidate, "prompt_version", issues),
    createdAt: requiredText(candidate, "created_at", issues),
    claims,
    evidence,
    confidenceSummary,
  };
}

export function normalizeMedicalMonitoringDailyAiCandidates({ candidates, candidateCount } = {}) {
  const issues = [];
  const count = nonNegativeInteger({ candidate_count: candidateCount }, "candidate_count", issues);
  if (candidates === null || candidates === undefined) {
    const missingCandidates = count === 0
      ? []
      : [issue("candidates", "missing", "候选线索明细未提供。")];
    const allIssues = [...issues, ...missingCandidates];
    return {
      status: allIssues.length > 0 ? (count === 0 ? "partial" : "unavailable") : "empty",
      value: { candidateCount: count, candidates: [] },
      issues: allIssues.map(({ field, kind, message }) => ({ field, kind, message })),
    };
  }
  if (!Array.isArray(candidates)) {
    return {
      status: "malformed",
      value: null,
      issues: [issue("candidates", "invalid", "候选线索不是数组。")],
    };
  }
  const normalized = candidates.map((raw, index) => normalizeCandidate(raw, index, issues)).filter(Boolean);
  const ids = new Set();
  normalized.forEach((candidate, index) => {
    if (candidate.candidateId && ids.has(candidate.candidateId)) {
      issues.push(issue(`candidates[${index}].candidate_id`, "invalid", "候选 ID 重复。"));
    }
    if (candidate.candidateId) ids.add(candidate.candidateId);
  });
  if (count !== null && count !== normalized.length) {
    issues.push(issue("candidate_count", "invalid", "候选计数与明细数量不一致。"));
  }
  return {
    status: issues.length > 0 ? "partial" : "ready",
    value: { candidateCount: count, candidates: normalized },
    issues: issues.map(({ field, kind, message }) => ({ field, kind, message })),
  };
}

export function medicalMonitoringAiCandidateStatusLabel(value) {
  return {
    proposed: "待医学确认",
    accepted: "已采纳",
    rejected: "已驳回",
    superseded: "已替代",
  }[String(value || "")] || "待核对";
}

export function medicalMonitoringAiCandidateReviewStateLabel(candidate) {
  const status = String(candidate?.status || "").trim();
  if (status === "accepted") return "医学已确认 · 当前监查中生效";
  if (status === "rejected") return "已驳回 · 不作为当前结论";
  if (status === "superseded") return "已替代 · 以新候选为准";
  if (status === "proposed") {
    return candidate?.confidenceSummary?.requiresAdditionalEvidence === true
      ? "需补证据"
      : "需医学确认";
  }
  return "状态待核对";
}

export function medicalMonitoringAiCandidateDisplayKey(candidate, index = 0) {
  const candidateId = text(candidate?.candidateId);
  const jobId = text(candidate?.jobId);
  const subjectId = text(candidate?.subjectId);
  const identity = candidateId || `${jobId || "job"}:${subjectId || "subject"}`;
  const sourceIndex = Number.isInteger(candidate?.sourceIndex) ? candidate.sourceIndex : index;
  return `candidate:${identity}:${sourceIndex}`;
}

export function medicalMonitoringAiCandidateEvidenceKey(item, index = 0) {
  const evidenceId = text(item?.evidenceId);
  const sourceEntryId = text(item?.sourceEntryId);
  const locator = text(item?.locator);
  const identity = evidenceId || `${sourceEntryId || "source"}:${locator || "missing"}`;
  const sourceIndex = Number.isInteger(item?.sourceIndex) ? item.sourceIndex : index;
  return `candidate-evidence:${identity}:${sourceIndex}`;
}

export function medicalMonitoringAiCandidateClaimKey(claim, index = 0) {
  const claimId = text(claim?.claimId);
  const sourceIndex = Number.isInteger(claim?.sourceIndex) ? claim.sourceIndex : index;
  return `candidate-claim:${claimId || "missing"}:${sourceIndex}`;
}

export function medicalMonitoringAiClaimKindLabel(value) {
  return {
    fact: "事实声明",
    inference: "推断声明",
    recommendation: "建议声明",
    data_gap: "数据缺口",
  }[String(value || "")] || "声明待核对";
}

export function medicalMonitoringAiCandidateConfidenceTone(summary) {
  if (summary?.status === "low") return "danger";
  if (summary?.status === "review_required") return "warning";
  return "neutral";
}
