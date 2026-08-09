const ACTIVE_TOPIC_STATES = new Set(["queued", "running"]);
const TERMINAL_TOPIC_STATES = new Set([
  "candidate_review",
  "reviewed",
  "data_gap",
  "failed",
  "blocked",
  "stale_input",
  "cancelled",
]);

export const MONITORING_AI_LOW_CONFIDENCE_THRESHOLD = 0.70;

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function recordArray(value) {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function stringArray(value) {
  return Array.isArray(value)
    ? value.filter((item) => typeof item === "string" && item.trim())
    : [];
}

function displayText(value) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function invalidStatus(message) {
  return { ok: false, error: message, value: null };
}

export function normalizeProtocolPreparationStatus(payload) {
  if (!isRecord(payload)) {
    return invalidStatus("方案规则准备状态格式异常，暂不展示候选。");
  }
  const rawTopics = payload.topics === undefined ? [] : payload.topics;
  if (!Array.isArray(rawTopics) || rawTopics.some((topic) => !isRecord(topic))) {
    return invalidStatus("方案规则准备主题格式异常，暂不展示候选。");
  }
  const topics = [];
  const seenTopicIds = new Set();
  const seenCandidateIds = new Set();
  for (const [topicIndex, topic] of rawTopics.entries()) {
    const candidates = topic.candidates === undefined ? [] : topic.candidates;
    if (!Array.isArray(candidates) || candidates.some((candidate) => !isRecord(candidate))) {
      return invalidStatus("方案规则准备候选格式异常，暂不展示候选。");
    }
    const factTypes = topic.allowed_fact_types === undefined
      ? []
      : topic.allowed_fact_types;
    if (!Array.isArray(factTypes) || factTypes.some((item) => typeof item !== "string")) {
      return invalidStatus("方案规则准备条款类型格式异常，暂不展示候选。");
    }
    if (topic.job !== null && topic.job !== undefined && !isRecord(topic.job)) {
      return invalidStatus("方案规则准备运行信息格式异常，暂不展示候选。");
    }
    const topicId = displayText(topic.topic_id);
    const topicIdentityState = !topicId
      ? "missing"
      : seenTopicIds.has(topicId)
        ? "duplicate"
        : "ready";
    if (topicId) seenTopicIds.add(topicId);
    const normalizedCandidates = candidates.map((candidate, candidateIndex) => {
      const candidateId = displayText(candidate.candidate_id);
      const identityState = !candidateId
        ? "missing"
        : seenCandidateIds.has(candidateId)
          ? "duplicate"
          : "ready";
      if (candidateId) seenCandidateIds.add(candidateId);
      return {
        ...candidate,
        __displayIndex: candidateIndex,
        __identityState: identityState,
      };
    });
    topics.push({
      ...topic,
      __displayIndex: topicIndex,
      __identityState: topicIdentityState,
      candidates: normalizedCandidates,
      allowed_fact_types: factTypes,
      job: topic.job ?? null,
    });
  }
  return { ok: true, error: "", value: { ...payload, topics } };
}

export const PROTOCOL_PREPARATION_STATUS_LABELS = Object.freeze({
  ready: "可开始",
  queued: "等待处理",
  running: "正在分析",
  candidate_review: "待用户确认",
  reviewed: "已处理",
  data_gap: "未找到相关原文",
  failed: "处理失败",
  blocked: "当前受阻",
  stale_input: "方案版本已变化",
  cancelled: "已取消",
});

export const PROTOCOL_CANDIDATE_FIELD_LABELS = Object.freeze({
  subject_scope: "适用对象",
  conditions: "条件",
  time_windows: "时间窗",
  thresholds: "阈值",
  exceptions: "例外",
  required_actions: "动作",
});

export const PROTOCOL_FACT_TYPE_LABELS = Object.freeze({
  eligibility_inclusion: "入选标准",
  eligibility_exclusion: "排除标准",
  visit_schedule: "访视计划",
  visit_window: "访视时间窗",
  study_treatment_regimen: "试验药物给药方案",
  study_treatment_change: "试验药物变更",
  study_treatment_adherence: "试验药物依从性",
  concomitant_medication_allowed: "允许的合并用药",
  concomitant_medication_restricted: "限制的合并用药",
  concomitant_medication_prohibited: "禁用的合并用药",
  concomitant_medication_rescue: "救援治疗",
  concomitant_medication_washout: "合并用药洗脱",
  safety_assessment: "安全性评估",
  aesi_definition: "AESI 定义",
  efficacy_assessment: "疗效评估",
  early_withdrawal: "提前退出",
  protocol_deviation: "方案偏离",
  data_quality: "数据完整性与质量",
});

export function protocolPreparationVersionDisplayKey(version, index = 0) {
  const identity = displayText(version?.protocol_version_id) || "missing";
  return `protocol-version:${identity}:${index}`;
}

export function confirmedProtocolVersions(payload) {
  const confirmed = recordArray(payload?.items)
    .filter((item) => item?.status === "confirmed");
  const identityCounts = new Map();
  confirmed.forEach((version) => {
    const identity = displayText(version.protocol_version_id);
    if (identity) identityCounts.set(identity, (identityCounts.get(identity) || 0) + 1);
  });
  return confirmed
    .map((version, displaySourceIndex) => {
      const identity = displayText(version.protocol_version_id);
      const duplicate = Boolean(identity && (identityCounts.get(identity) || 0) > 1);
      return {
        ...version,
        displaySourceIndex,
        displayIdentityState: !identity ? "missing" : duplicate ? "duplicate" : "ready",
        displayIdentityIssue: !identity
          ? "方案版本缺少 protocol_version_id；仅可读，暂不能选择"
          : duplicate
            ? "方案版本 protocol_version_id 重复；保留版本但暂不能选择"
            : "",
        displayKey: protocolPreparationVersionDisplayKey(version, displaySourceIndex),
      };
    })
    .sort((left, right) => {
      const dateOrder = String(right.version_date || "")
        .localeCompare(String(left.version_date || ""));
      if (dateOrder) return dateOrder;
      const labelOrder = String(right.version_label || "")
        .localeCompare(String(left.version_label || ""));
      return labelOrder || left.displaySourceIndex - right.displaySourceIndex;
    });
}

export function shouldPollProtocolPreparation(payload) {
  return recordArray(payload?.topics)
    .some((topic) => ACTIVE_TOPIC_STATES.has(topic?.status));
}

export function protocolPreparationProgress(payload) {
  const topics = recordArray(payload?.topics);
  const total = topics.length;
  const completed = topics.filter(
    (topic) => TERMINAL_TOPIC_STATES.has(topic?.status),
  ).length;
  const candidateCount = topics.reduce(
    (sum, topic) => sum + recordArray(topic?.candidates).filter(
      (candidate) => candidate?.status === "proposed",
    ).length,
    0,
  );
  const submitted = topics.some(
    (topic) => topic?.execution_status === "submitted",
  );
  return {
    total,
    completed,
    candidateCount,
    submitted,
    percent: total ? Math.round((completed / total) * 100) : 0,
  };
}

export function protocolPreparationStartAction(payload) {
  const topics = recordArray(payload?.topics);
  const ready = topics.some((topic) => topic?.status === "ready");
  const retryable = topics.some((topic) => (
    ["failed", "blocked", "stale_input", "cancelled"].includes(topic?.status)
  ));
  return {
    available: ready || retryable,
    retry: retryable,
    label: retryable ? "重新生成未完成主题" : "一键准备全部主题",
  };
}

export function candidateStructuredSections(candidate) {
  const payload = candidate?.structured_payload || {};
  return Object.entries(PROTOCOL_CANDIDATE_FIELD_LABELS)
    .map(([key, label]) => {
      const raw = payload[key];
      const values = Array.isArray(raw)
        ? raw.filter((value) => String(value || "").trim())
        : String(raw || "").trim()
          ? [raw]
          : [];
      return {
        key,
        label,
        values: values.map((value) => String(value).trim()),
      };
    })
    .filter((section) => section.values.length > 0);
}

export function candidateReferencedEvidence(candidate) {
  const referencedIds = new Set([
    ...stringArray(candidate?.structured_payload?.evidence_ids),
    ...recordArray(candidate?.claims).flatMap((claim) => stringArray(claim?.evidence_ids)),
  ].map((value) => String(value || "").trim()).filter(Boolean));
  if (referencedIds.size === 0) return [];
  return recordArray(candidate?.evidence).filter((evidence) => (
    referencedIds.has(String(evidence?.evidence_id || "").trim())
  ));
}

export function candidateConfidenceSummary(candidate) {
  const claims = recordArray(candidate?.claims);
  if (claims.length === 0) {
    return {
      status: "not_scored",
      label: "未提供语义置信度，需确认来源",
      confidence_floor: null,
      threshold: MONITORING_AI_LOW_CONFIDENCE_THRESHOLD,
      claim_count: 0,
      requires_user_review: true,
      requires_additional_evidence: false,
      automation_permitted: false,
      next_step: "medical_manager_confirmation",
    };
  }
  const confidences = claims.map((claim) => (
    typeof claim.confidence === "number"
      && Number.isFinite(claim.confidence)
      && claim.confidence >= 0
      && claim.confidence <= 1
      ? claim.confidence
      : null
  ));
  const valid = confidences.filter((value) => value !== null);
  const floor = valid.length > 0 ? Math.min(...valid) : null;
  const low = valid.length !== claims.length
    || floor === null
    || floor < MONITORING_AI_LOW_CONFIDENCE_THRESHOLD;
  return {
    status: low ? "low" : "review_required",
    label: low
      ? "低置信度，需补充证据或说明"
      : "达到工作台阈值，仍需医学确认",
    confidence_floor: floor,
    threshold: MONITORING_AI_LOW_CONFIDENCE_THRESHOLD,
    claim_count: claims.length,
    requires_user_review: true,
    requires_additional_evidence: low,
    automation_permitted: false,
    next_step: low
      ? "source_review_or_more_data"
      : "medical_manager_confirmation",
  };
}

export function protocolPreparationTopicTone(status) {
  if (status === "reviewed") return "success";
  if (status === "candidate_review") return "warning";
  if (ACTIVE_TOPIC_STATES.has(status)) return "info";
  if (status === "data_gap") return "muted";
  if (["failed", "blocked", "stale_input", "cancelled"].includes(status)) {
    return "danger";
  }
  return "neutral";
}

export function protocolFactTypeOptions(topic) {
  return stringArray(topic?.allowed_fact_types).map((value) => ({
    value,
    label: PROTOCOL_FACT_TYPE_LABELS[value] || value,
  }));
}

export function protocolCandidateDecisionLabel(candidate) {
  if (candidate?.status === "accepted") return "已确认事实草稿";
  if (candidate?.status === "rejected") return "已驳回";
  if (candidate?.status === "superseded") return "已被新候选替代";
  return "待确认";
}

export function protocolPreparationTopicDisplayKey(topic, index = 0) {
  const identity = displayText(topic?.topic_id) || "missing";
  const sourceIndex = Number.isInteger(topic?.__displayIndex) ? topic.__displayIndex : index;
  return `protocol-topic:${identity}:${sourceIndex}`;
}

export function protocolPreparationCandidateDisplayKey(candidate, index = 0) {
  const candidateId = displayText(candidate?.candidate_id);
  const identity = candidateId || "missing";
  const sourceIndex = Number.isInteger(candidate?.__displayIndex) ? candidate.__displayIndex : index;
  return `protocol-candidate:${identity}:${sourceIndex}`;
}

export function protocolPreparationEvidenceDisplayKey(evidence, index = 0) {
  const evidenceId = displayText(evidence?.evidence_id);
  const locator = displayText(evidence?.locator);
  const quote = displayText(evidence?.quote);
  const identity = evidenceId || `${locator || "missing"}:${quote || "quote-missing"}`;
  return `protocol-evidence:${identity}:${index}`;
}

export function protocolPreparationCandidateIdentityReady(candidate) {
  return displayText(candidate?.candidate_id).length > 0
    && (candidate?.__identityState === undefined || candidate.__identityState === "ready");
}

export function resolveProtocolCandidateInputRevision(
  topic,
  candidate,
  jobPayload,
) {
  const jobCandidate = recordArray(jobPayload?.candidates)
    .find((item) => item?.candidate_id === candidate?.candidate_id);
  return String(
    candidate?.input_revision_sha256
      || topic?.job?.input_revision_sha256
      || jobCandidate?.input_revision_sha256
      || jobPayload?.job?.input_revision_sha256
      || "",
  ).trim();
}

export function buildProtocolCandidateDecisionPayload({
  decision,
  topic,
  candidate,
  jobPayload,
  factType = "",
  reason = "",
}) {
  if (!["accepted", "rejected"].includes(decision)) {
    throw new TypeError("候选决定只能为接受或驳回。");
  }
  const expectedInputRevision = resolveProtocolCandidateInputRevision(
    topic,
    candidate,
    jobPayload,
  );
  if (!/^[0-9a-f]{64}$/.test(expectedInputRevision)) {
    throw new TypeError("候选输入版本不可用，请刷新后重试。");
  }
  const expectedSourceRevision = String(topic?.source_revision || "").trim();
  if (!expectedSourceRevision) {
    throw new TypeError("方案来源版本不可用，请刷新后重试。");
  }

  const payload = {
    decision,
    reason: String(reason || "").trim(),
    expected_input_revision_sha256: expectedInputRevision,
    expected_source_revision: expectedSourceRevision,
  };
  if (decision === "accepted") {
    const options = protocolFactTypeOptions(topic);
    const selected = String(factType || "").trim();
    if (options.length > 1 && !selected) {
      throw new TypeError("请选择候选对应的条款类型。");
    }
    if (selected && !options.some((option) => option.value === selected)) {
      throw new TypeError("所选条款类型不属于当前监查主题。");
    }
    if (options.length > 1) payload.proposed_fact_type = selected;
  }
  return payload;
}

export function applyProtocolCandidateDecision(status, candidateId, response) {
  const decidedCandidate = response?.candidate;
  if (!isRecord(status) || !candidateId || !isRecord(decidedCandidate)) return status;
  const decidedFact = response?.outcome?.fact || decidedCandidate?.fact || null;
  return {
    ...status,
    topics: recordArray(status.topics).map((topic) => {
      const candidates = recordArray(topic.candidates).map((candidate) => (
        candidate.candidate_id === candidateId
          ? {
            ...candidate,
            ...decidedCandidate,
            ...(decidedFact ? { fact: decidedFact } : {}),
          }
          : candidate
      ));
      const hasProposed = candidates.some(
        (candidate) => candidate.status === "proposed",
      );
      return {
        ...topic,
        candidates,
        status: topic.status === "candidate_review" && !hasProposed
          ? "reviewed"
          : topic.status,
      };
    }),
  };
}

export function acceptedProtocolCandidateFact(candidate) {
  if (candidate?.status !== "accepted") return null;
  const fact = candidate?.fact;
  const factRevisionId = String(fact?.fact_revision_id || "").trim();
  const stateVersion = Number(fact?.state_version);
  if (!factRevisionId || !Number.isInteger(stateVersion) || stateVersion < 1) {
    return null;
  }
  return {
    ...fact,
    fact_revision_id: factRevisionId,
    state_version: stateVersion,
  };
}

export function newlyAcceptedProtocolDecisionFact(response) {
  if (response?.decision !== "accepted") return null;
  return acceptedProtocolCandidateFact({
    status: "accepted",
    fact: response?.outcome?.fact || response?.candidate?.fact || null,
  });
}

export function acceptedProtocolFacts(payload) {
  const seen = new Set();
  return recordArray(payload?.topics).flatMap((topic) => (
    recordArray(topic?.candidates).map((candidate) => ({
      topic,
      candidate,
      fact: acceptedProtocolCandidateFact(candidate),
    }))
  )).filter((item) => {
    if (!item.fact || seen.has(item.fact.fact_revision_id)) return false;
    seen.add(item.fact.fact_revision_id);
    return true;
  });
}
