const ACTIVE_RULE_TEMPLATE_STATES = new Set(["queued", "running"]);
const FAILURE_RULE_TEMPLATE_STATES = new Set([
  "failed",
  "blocked",
  "stale_input",
  "cancelled",
]);

const DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.70;

export function ruleTemplateCandidateConfidenceSummary(candidate) {
  const raw = candidate?.confidence_summary;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {
      status: "not_scored",
      label: "未提供语义置信度，需确认来源",
      confidence_floor: null,
      threshold: DEFAULT_LOW_CONFIDENCE_THRESHOLD,
      claim_count: 0,
      requires_user_review: true,
      requires_additional_evidence: true,
      automation_permitted: false,
      next_step: "medical_manager_confirmation",
    };
  }
  const threshold = typeof raw.threshold === "number"
    && Number.isFinite(raw.threshold)
    && raw.threshold >= 0
    && raw.threshold <= 1
    ? raw.threshold
    : DEFAULT_LOW_CONFIDENCE_THRESHOLD;
  const floor = typeof raw.confidence_floor === "number"
    && Number.isFinite(raw.confidence_floor)
    && raw.confidence_floor >= 0
    && raw.confidence_floor <= 1
    ? raw.confidence_floor
    : null;
  const low = raw.requires_additional_evidence === true
    || floor === null
    || floor < threshold;
  return {
    status: low ? "low" : (raw.status || "review_required"),
    label: typeof raw.label === "string" && raw.label.trim()
      ? raw.label.trim()
      : low
        ? "低置信度，需补充证据或说明"
        : "达到工作台阈值，仍需医学确认",
    confidence_floor: floor,
    threshold,
    claim_count: Number.isInteger(raw.claim_count) ? raw.claim_count : 0,
    requires_user_review: true,
    requires_additional_evidence: low,
    automation_permitted: false,
    next_step: low
      ? "source_review_or_more_data"
      : "medical_manager_confirmation",
  };
}

export const RULE_TEMPLATE_STATUS_LABELS = Object.freeze({
  ready: "可生成规则建议",
  queued: "等待生成",
  running: "正在生成",
  candidate_review: "请选择规则建议",
  reviewed: "建议已处理",
  manual_review: "需人工处理",
  failed: "生成失败",
  blocked: "当前受阻",
  stale_input: "输入已变化",
  cancelled: "已取消",
});

function requireFact(fact) {
  const factRevisionId = String(fact?.fact_revision_id || "").trim();
  const stateVersion = Number(fact?.state_version);
  if (!factRevisionId || !Number.isInteger(stateVersion) || stateVersion < 1) {
    throw new TypeError("方案事实版本不可用，请刷新方案候选后重试。");
  }
  return {
    ...fact,
    fact_revision_id: factRevisionId,
    state_version: stateVersion,
  };
}

function normalizedStringList(value) {
  const items = Array.isArray(value) ? value : [value];
  return items
    .map((item) => String(item || "").trim())
    .filter(Boolean);
}

export function ruleTemplateRecommendationFactKey(fact) {
  return requireFact(fact).fact_revision_id;
}

export function buildRuleTemplateRecommendationStartPayload(fact) {
  const currentFact = requireFact(fact);
  return {
    expected_fact_state_version: currentFact.state_version,
  };
}

export function shouldPollRuleTemplateRecommendation(payload) {
  return ACTIVE_RULE_TEMPLATE_STATES.has(payload?.status);
}

export function buildRuleTemplateRecommendationDecisionPayload({
  decision,
  statusPayload,
  candidate,
  fact,
  reason = "",
}) {
  if (!["accepted", "rejected"].includes(decision)) {
    throw new TypeError("规则建议决定只能为采用或不采用。");
  }
  const currentFact = requireFact(fact || statusPayload?.fact);
  const inputRevision = String(
    statusPayload?.input_revision_sha256 || "",
  ).trim().toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(inputRevision)) {
    throw new TypeError("规则建议输入版本不可用，请刷新后重试。");
  }
  const candidateId = String(candidate?.candidate_id || "").trim();
  if (!candidateId || candidate?.status !== "proposed") {
    throw new TypeError("该规则建议当前不可选择，请刷新后查看。");
  }
  return {
    candidateId,
    payload: {
      decision,
      expected_input_revision_sha256: inputRevision,
      expected_fact_state_version: currentFact.state_version,
      reason: String(reason || "").trim(),
    },
  };
}

export function applyRuleTemplateRecommendationDecision(
  statusPayload,
  candidateId,
  response,
) {
  if (!statusPayload || !candidateId || !response) return statusPayload;
  const responseStatus = response.status;
  const decisionStatus = responseStatus === "rule_template_selected"
    ? "accepted"
    : responseStatus === "user_rejected"
      ? "rejected"
      : "";
  const responseCandidate = response.candidate || {};
  const candidates = (statusPayload.candidates || []).map((candidate) => (
    candidate.candidate_id === candidateId
      ? {
        ...candidate,
        ...responseCandidate,
        ...(decisionStatus ? { status: decisionStatus } : {}),
      }
      : candidate
  ));
  const hasProposed = candidates.some(
    (candidate) => candidate.status === "proposed",
  );
  return {
    ...statusPayload,
    status: responseStatus === "rule_template_selected"
      ? "reviewed"
      : hasProposed
        ? "candidate_review"
        : "reviewed",
    candidates,
    ...(responseStatus === "rule_template_selected"
      ? {
        selected_candidate_id: candidateId,
        compiled_rule: response.compiled_rule || null,
        confirmed_fact: response.confirmed_fact || null,
        next_action: response.next_action || null,
      }
      : {}),
  };
}

export function ruleTemplateCandidateDetails(candidate) {
  if (!candidate) return null;
  return {
    candidateId: String(candidate.candidate_id || "").trim(),
    status: candidate.status || "proposed",
    title: String(candidate.title || "规则建议").trim(),
    summary: String(candidate.summary || "").trim(),
    rationale: String(candidate.rationale || "").trim(),
    tradeoffs: normalizedStringList(candidate.tradeoffs),
    requiredDomains: (candidate.required_domains || [])
      .map((value) => String(value || "").trim())
      .filter(Boolean),
    mappingFields: (candidate.mapping_fields || []).map((item) => ({
      role: String(item?.role || "").trim(),
      domain: String(item?.domain || "").trim(),
      field: String(item?.field || "").trim(),
    })).filter((item) => item.domain && item.field),
    sourceText: String(candidate.source?.text || "").trim(),
    sourceLocator: String(candidate.source?.locator || "").trim(),
    confidenceSummary: ruleTemplateCandidateConfidenceSummary(candidate),
  };
}

export function ruleTemplateRecommendationViewModel({
  payload,
  loading = false,
  busy = false,
  error = "",
} = {}) {
  const status = payload?.status || "";
  const candidates = (payload?.candidates || [])
    .slice(0, 3)
    .map(ruleTemplateCandidateDetails)
    .filter(Boolean);
  const selectedCandidate = candidates.find(
    (candidate) => candidate.status === "accepted",
  );
  const compiled = Boolean(
    payload?.compiled_rule
    || payload?.selected_candidate_id
    || selectedCandidate,
  );
  let mode = "idle";
  if (loading) mode = "loading";
  else if (error) mode = "error";
  else if (compiled) mode = "compiled";
  else if (status === "ready") mode = "ready";
  else if (ACTIVE_RULE_TEMPLATE_STATES.has(status)) mode = "progress";
  else if (status === "manual_review") mode = "manual_review";
  else if (status === "candidate_review") mode = "candidate_review";
  else if (FAILURE_RULE_TEMPLATE_STATES.has(status)) mode = "error";
  else if (status === "reviewed") mode = "reviewed";
  return {
    mode,
    status,
    label: RULE_TEMPLATE_STATUS_LABELS[status] || "",
    message: String(
      payload?.message
      || payload?.failure?.message
      || error
      || "",
    ).trim(),
    candidates,
    canStart: mode === "ready" && !busy,
    shouldPoll: shouldPollRuleTemplateRecommendation(payload),
    compiled,
  };
}
