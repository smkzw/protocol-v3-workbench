export const timelineLaneDefs = [
  { key: "AE", label: "AE", types: ["adverse_event"] },
  {
    key: "IP",
    label: "试验药物",
    types: [
      "study_drug_dispensing",
      "study_drug_administration",
      "study_drug_adherence",
      "dose_adjustment",
    ],
  },
  { key: "BACKGROUND", label: "方案背景治疗", types: ["background_treatment"] },
  { key: "CM", label: "合并用药（非试验用药）", types: ["concomitant_medication"] },
  { key: "NON_DRUG", label: "非药物治疗", types: ["non_drug_treatment"] },
  { key: "MH", label: "病史", types: ["medical_history"] },
  { key: "LAB", label: "实验室", types: ["lab"] },
  { key: "EFFICACY", label: "疗效评估", types: ["efficacy_score"] },
  { key: "PD_QUERY", label: "PD / Query", types: ["protocol_deviation", "query"] },
  { key: "OTHER", label: "其他事件", types: [] },
];

export const timelineEventCategoryDefs = {
  adverse_event: { label: "AE记录", className: "event-category-adverse-event" },
  adverse_event_review: { label: "AE复核提示", className: "event-category-adverse-event-review" },
  dose_adjustment: { label: "试验药物变更", className: "event-category-dose-adjustment" },
  dose_adjustment_paused: { label: "试验药物暂停", className: "event-category-dose-adjustment-paused" },
  dose_adjustment_resumed: { label: "试验药物恢复", className: "event-category-dose-adjustment-resumed" },
  study_drug_dispensing: { label: "试验药物发放", className: "event-category-study-drug-dispensing" },
  study_drug_administration: { label: "试验药物给药", className: "event-category-study-drug-administration" },
  study_drug_adherence: { label: "试验药物依从性", className: "event-category-study-drug-adherence" },
  background_treatment: { label: "方案背景治疗", className: "event-category-background-treatment" },
  non_drug_treatment: { label: "非药物治疗", className: "event-category-non-drug-treatment" },
  concomitant_medication: { label: "CM非试验用药", className: "event-category-concomitant-medication" },
  concomitant_medication_risk: { label: "禁限用药/洗脱风险", className: "event-category-concomitant-medication-risk" },
  medical_history: { label: "病史", className: "event-category-medical-history" },
  lab: { label: "实验室", className: "event-category-lab" },
  lab_hematology: { label: "血常规异常", className: "event-category-lab-hematology" },
  lab_chemistry: { label: "血生化异常", className: "event-category-lab-chemistry" },
  efficacy_score: { label: "疗效", className: "event-category-efficacy-score" },
  protocol_deviation: { label: "PD", className: "event-category-protocol-deviation" },
  query: { label: "Query", className: "event-category-query" },
};

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeRecordArray(value, field, warnings) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    warnings.push(field);
    return [];
  }
  return value.flatMap((item, index) => {
    if (isRecord(item)) return [item];
    warnings.push(`${field}[${index}]`);
    return [];
  });
}

function normalizeStringArray(value, field, warnings) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    warnings.push(field);
    return [];
  }
  return value.flatMap((item, index) => {
    if (typeof item === "string" && item.trim()) return [item.trim()];
    warnings.push(`${field}[${index}]`);
    return [];
  });
}

function normalizeOptionalBoolean(value, field, warnings) {
  if (value === undefined || value === null) return value;
  if (typeof value === "boolean") return value;
  warnings.push(field);
  return undefined;
}

function normalizeTimelineArray(value, field, warnings) {
  return normalizeRecordArray(value, field, warnings).map((event, index) => {
    const normalized = { ...event };
    if (event.related_risk_ids !== undefined) {
      normalized.related_risk_ids = normalizeStringArray(event.related_risk_ids, `${field}[${index}].related_risk_ids`, warnings);
    }
    ["is_unscheduled", "ongoing"].forEach((flag) => {
      if (event[flag] !== undefined && event[flag] !== null) {
        normalized[flag] = normalizeOptionalBoolean(event[flag], `${field}[${index}].${flag}`, warnings);
        if (normalized[flag] === undefined) delete normalized[flag];
      }
    });
    return normalized;
  });
}

function normalizeMetricArray(value, field, warnings) {
  return normalizeRecordArray(value, field, warnings).map((metric, index) => {
    let points = metric.points;
    if (points === undefined || points === null) points = [];
    else if (!Array.isArray(points)) {
      warnings.push(`${field}[${index}].points`);
      points = [];
    } else {
      points = points.filter((point, pointIndex) => {
        if (isRecord(point)) return true;
        warnings.push(`${field}[${index}].points[${pointIndex}]`);
        return false;
      });
    }
    points = points.map((point, pointIndex) => {
      const normalizedPoint = { ...point };
      if (point.related_risk_ids !== undefined) {
        normalizedPoint.related_risk_ids = normalizeStringArray(
          point.related_risk_ids,
          `${field}[${index}].points[${pointIndex}].related_risk_ids`,
          warnings,
        );
      }
      ["risk_flag", "is_baseline"].forEach((flag) => {
        if (point[flag] !== undefined && point[flag] !== null) {
          normalizedPoint[flag] = normalizeOptionalBoolean(
            point[flag],
            `${field}[${index}].points[${pointIndex}].${flag}`,
            warnings,
          );
          if (normalizedPoint[flag] === undefined) delete normalizedPoint[flag];
        }
      });
      return normalizedPoint;
    });
    return { ...metric, points };
  });
}

function displayMetricIdentity(metric) {
  const metricKey = typeof metric?.metric_key === "string" ? metric.metric_key.trim() : "";
  const metricLabel = typeof metric?.metric_label === "string" ? metric.metric_label.trim() : "";
  return metricKey || metricLabel;
}

/**
 * Add display-only identity metadata to profile trend metrics. A missing or
 * duplicate key/label remains visible but cannot collide in the chart grid;
 * these fields never replace the source metric identity or enter an API call.
 */
export function metricDisplayRows(metrics = [], namespace = "metric") {
  const rows = Array.isArray(metrics)
    ? metrics.filter(isRecord)
    : [];
  const identityCounts = new Map();
  rows.forEach((metric) => {
    const identity = displayMetricIdentity(metric);
    if (identity) identityCounts.set(identity, (identityCounts.get(identity) || 0) + 1);
  });
  const safeNamespace = typeof namespace === "string" && namespace.trim() ? namespace.trim() : "metric";
  return rows.map((metric, displaySourceIndex) => {
    const identity = displayMetricIdentity(metric);
    const duplicate = Boolean(identity && (identityCounts.get(identity) || 0) > 1);
    return {
      ...metric,
      displaySourceIndex,
      displayIdentityState: !identity ? "missing" : duplicate ? "duplicate" : "ready",
      displayIdentityIssue: !identity
        ? "趋势指标缺少 metric_key/metric_label；仅可读，暂不能据此确认指标"
        : duplicate
          ? "趋势指标 metric_key/metric_label 重复；保留图表但暂不能据此确认指标"
          : "",
      displayKey: `metric:${safeNamespace}:${identity || "missing"}:${displaySourceIndex}`,
    };
  });
}

function displayRiskPromptIdentity(prompt) {
  return typeof prompt?.prompt_id === "string" ? prompt.prompt_id.trim() : "";
}

/**
 * Add display-only identity metadata to Patient Profile risk prompts. A
 * missing or duplicate prompt_id remains visible, but cannot collide with a
 * neighboring React row or be mistaken for an unambiguous prompt identity.
 * These fields never replace the source prompt identity or enter an API call.
 */
export function riskPromptDisplayRows(prompts = []) {
  const rows = Array.isArray(prompts)
    ? prompts.filter(isRecord)
    : [];
  const identityCounts = new Map();
  rows.forEach((prompt) => {
    const identity = displayRiskPromptIdentity(prompt);
    if (identity) identityCounts.set(identity, (identityCounts.get(identity) || 0) + 1);
  });
  return rows.map((prompt, displaySourceIndex) => {
    const identity = displayRiskPromptIdentity(prompt);
    const duplicate = Boolean(identity && (identityCounts.get(identity) || 0) > 1);
    return {
      ...prompt,
      displaySourceIndex,
      displayIdentityState: !identity ? "missing" : duplicate ? "duplicate" : "ready",
      displayIdentityIssue: !identity
        ? "风险提示缺少 prompt_id；仅可读，暂不能据此确认或聚焦"
        : duplicate
          ? "风险提示 prompt_id 重复；保留提示但暂不能据此确认或聚焦"
          : "",
      displayKey: `risk-prompt:${identity || "missing"}:${displaySourceIndex}`,
    };
  });
}

export function riskPromptDisplayKey(prompt, index = 0) {
  if (typeof prompt?.displayKey === "string" && prompt.displayKey.trim()) {
    return prompt.displayKey;
  }
  const identity = displayRiskPromptIdentity(prompt);
  const safeIndex = Number.isInteger(index) && index >= 0 ? index : 0;
  return `risk-prompt:${identity || "missing"}:${safeIndex}`;
}

function displayTrendPointIdentity(point) {
  return typeof point?.point_id === "string" ? point.point_id.trim() : "";
}

/**
 * Add display-only identity metadata to subject trend points. A missing or
 * duplicate point_id remains visible and selectable only by a source-index
 * scoped display key; the source point and its clinical values are unchanged.
 * These fields never replace point_id or enter an API call.
 */
export function trendPointDisplayRows(points = [], metricKey = "metric") {
  const rows = Array.isArray(points)
    ? points.filter(isRecord)
    : [];
  const identityCounts = new Map();
  rows.forEach((point) => {
    const identity = displayTrendPointIdentity(point);
    if (identity) identityCounts.set(identity, (identityCounts.get(identity) || 0) + 1);
  });
  const safeMetricKey = typeof metricKey === "string" && metricKey.trim() ? metricKey.trim() : "metric";
  return rows.map((point, displaySourceIndex) => {
    const identity = displayTrendPointIdentity(point);
    const duplicate = Boolean(identity && (identityCounts.get(identity) || 0) > 1);
    return {
      point,
      displaySourceIndex,
      displayIdentityState: !identity ? "missing" : duplicate ? "duplicate" : "ready",
      displayIdentityIssue: !identity
        ? "趋势数据点缺少 point_id；保留原始事实，暂不能确认单点来源"
        : duplicate
          ? "趋势数据点 point_id 重复；保留原始事实，暂不能确认单点来源"
          : "",
      displayKey: `metric-point:${safeMetricKey}:${identity || "missing"}:${displaySourceIndex}`,
    };
  });
}

function normalizeStringMap(value, field, warnings) {
  if (value === undefined || value === null) return {};
  if (!isRecord(value)) {
    warnings.push(field);
    return {};
  }
  return Object.fromEntries(Object.entries(value).map(([key, raw]) => [
    key,
    normalizeStringArray(raw, `${field}.${key}`, warnings),
  ]));
}

/**
 * Normalize the API's patient-profile payload before it reaches Timeline/Profile views.
 * This is a read-only presentation boundary: malformed arrays are removed and surfaced as
 * shape warnings; no clinical value, date, range, responder flag, or risk is inferred.
 */
export function normalizeMonitoringSubjectProfile(profile) {
  if (profile === undefined || profile === null) return null;
  if (!isRecord(profile)) return null;
  const warnings = Array.isArray(profile.profile_shape_warnings)
    ? profile.profile_shape_warnings.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim())
    : profile.profile_shape_warnings === undefined || profile.profile_shape_warnings === null
      ? []
      : ["profile_shape_warnings"];

  const rawSubject = profile.subject;
  const subject = rawSubject === undefined || rawSubject === null
    ? {}
    : isRecord(rawSubject)
      ? { ...rawSubject }
      : (warnings.push("subject"), {});
  subject.key_medical_context = normalizeStringArray(
    subject.key_medical_context,
    "subject.key_medical_context",
    warnings,
  );

  const normalized = {
    ...profile,
    subject,
    timeline: normalizeTimelineArray(profile.timeline, "timeline", warnings),
    efficacy_trends: normalizeMetricArray(profile.efficacy_trends, "efficacy_trends", warnings),
    safety_trends: normalizeMetricArray(profile.safety_trends, "safety_trends", warnings),
    risk_prompts: normalizeRecordArray(profile.risk_prompts, "risk_prompts", warnings),
    review_focus: normalizeStringArray(profile.review_focus, "review_focus", warnings),
    domain_availability: normalizeRecordArray(profile.domain_availability, "domain_availability", warnings),
    capability_states: isRecord(profile.capability_states) ? { ...profile.capability_states } : {},
    capability_limitations: normalizeStringMap(profile.capability_limitations, "capability_limitations", warnings),
  };
  if (
    profile.capability_states !== undefined
    && profile.capability_states !== null
    && !isRecord(profile.capability_states)
  ) warnings.push("capability_states");
  if (profile.capability_mode === undefined || profile.capability_mode === null) {
    normalized.capability_mode = "full";
  } else if (["full", "restricted"].includes(profile.capability_mode)) {
    normalized.capability_mode = profile.capability_mode;
  } else {
    warnings.push("capability_mode");
    normalized.capability_mode = "restricted";
  }
  normalized.profile_shape_warnings = [...new Set(warnings)];
  return normalized;
}

function explicitSourceLocatorState(record) {
  if (!isRecord(record)) {
    return {
      status: "missing",
      label: "来源定位缺失",
      locator: "",
      locatorCount: 0,
      malformed: false,
      message: "当前记录没有显式来源定位；不能据此判定来源完整或无风险。",
    };
  }
  const fields = [
    ["source_locator", record.source_locator, false],
    ["source_record_id", record.source_record_id, false],
    ["evidence_locator", record.evidence_locator, false],
    ["source_locators", record.source_locators, true],
    ["evidence_locators", record.evidence_locators, true],
    ["evidence_span_ids", record.evidence_span_ids, true],
  ];
  let malformed = false;
  const values = [];
  fields.forEach(([, rawValue, expectsArray]) => {
    if (rawValue === undefined || rawValue === null) return;
    if (expectsArray !== Array.isArray(rawValue)) malformed = true;
    const entries = Array.isArray(rawValue) ? rawValue : [rawValue];
    entries.forEach((value) => {
      if (typeof value !== "string" || !value.trim()) {
        malformed = true;
        return;
      }
      values.push(value.trim());
    });
  });
  const uniqueValues = [...new Set(values)];
  const locator = uniqueValues.join("、");
  if (malformed) {
    return {
      status: "malformed",
      label: "来源定位形状异常",
      locator,
      locatorCount: uniqueValues.length,
      malformed: true,
      message: "来源定位字段形状异常；保留的显式字符串仅供回到来源核对，不能据此证明来源真实性或无风险。",
    };
  }
  if (!locator) {
    return {
      status: "missing",
      label: "来源定位缺失",
      locator: "",
      locatorCount: 0,
      malformed: false,
      message: "当前记录没有显式来源定位；不能据此判定来源完整或无风险。",
    };
  }
  return {
    status: "bound",
    label: "来源定位已提供",
    locator,
    locatorCount: uniqueValues.length,
    malformed: false,
    message: "来源定位来自记录显式字段；定位存在不等于来源真实性或风险已确认。",
  };
}

export function subjectSourceLocator(record) {
  return explicitSourceLocatorState(record).locator;
}

export function subjectSourceLocatorState(record) {
  return explicitSourceLocatorState(record);
}

function explicitStringList(...values) {
  const malformed = values.some((value) => (
    value !== undefined
    && value !== null
    && (!Array.isArray(value)
      || value.some((item) => typeof item !== "string" || !item.trim()))
  ));
  const items = [...new Set(values
    .flatMap((value) => (Array.isArray(value) ? value : typeof value === "string" ? [value] : []))
    .filter((value) => typeof value === "string" && value.trim())
    .map((value) => value.trim()))];
  return { values: items, malformed };
}

function explicitLineageTokenState(value) {
  if (value === undefined || value === null) return { value: "", malformed: false };
  if (typeof value !== "string") return { value: "", malformed: true };
  const text = value.trim();
  if (!text || text === "-" || text === "未提供" || text.toLowerCase() === "legacy") {
    return { value: "", malformed: false };
  }
  return { value: text, malformed: false };
}

/**
 * Summarize only the explicit facts a risk prompt declares as related. An
 * empty relationship is intentionally visible and never upgraded from the
 * prompt's title, date, severity, or prose.
 */
export function riskPromptEvidenceSummary(prompt) {
  if (!isRecord(prompt)) {
    return {
      eventIds: [],
      metricKeys: [],
      riskIds: [],
      evidenceIds: [],
      identifiers: [],
      label: "未绑定关联事实",
      message: "当前提示没有显式关联事件、指标或证据 span；不能据此判定无风险。",
    };
  }
  const eventList = explicitStringList(prompt.related_event_ids, prompt.relatedEventIds);
  const metricList = explicitStringList(prompt.related_metric_keys, prompt.relatedMetricKeys);
  const riskList = explicitStringList(prompt.related_risk_ids, prompt.relatedRiskIds);
  const evidenceList = explicitStringList(prompt.evidence_span_ids, prompt.evidenceSpanIds);
  const eventIds = eventList.values;
  const metricKeys = metricList.values;
  const riskIds = riskList.values;
  const evidenceIds = evidenceList.values;
  const malformed = [eventList, metricList, riskList, evidenceList].some((list) => list.malformed);
  const identifiers = [
    ...eventIds.map((value) => `事件 ${value}`),
    ...metricKeys.map((value) => `指标 ${value}`),
    ...evidenceIds.map((value) => `证据 ${value}`),
  ];
  const counts = [
    eventIds.length ? `事件 ${eventIds.length}` : "",
    metricKeys.length ? `指标 ${metricKeys.length}` : "",
    evidenceIds.length ? `证据 ${evidenceIds.length}` : "",
  ].filter(Boolean);
  return {
    eventIds,
    metricKeys,
    riskIds,
    evidenceIds,
    identifiers,
    label: malformed ? "关联证据形状异常" : counts.length ? `关联${counts.join(" · ")}` : "未绑定关联事实",
    message: malformed
      ? "当前提示的关联事件/指标/风险/证据字段形状异常；已保留可读的显式 ID，但不能据此判定无风险。"
      : counts.length
        ? `显式关联${counts.join("、")}；关联 ID 仅用于回到来源事实核对，不代表已完成医学判断。`
        : "当前提示没有显式关联事件、指标或证据 span；不能据此判定无风险。",
    shapeStatus: malformed ? "malformed" : "valid",
  };
}

/**
 * Describe whether a Patient Profile/Subject Timeline payload is explicitly
 * bound to a source revision and whether its displayed records retain a
 * source locator. Batch labels alone are intentionally insufficient: they do
 * not prove source revision, trend comparability, or completeness.
 */
export function subjectEvidenceLineageSummary(subject) {
  const rawProfile = isRecord(subject?.rawProfile) ? subject.rawProfile : null;
  if (!rawProfile) {
    return {
      status: "empty",
      label: "来源未载入",
      sourceRevision: "",
      sourceBatch: "",
      totalRecords: 0,
      tracedRecords: 0,
      untracedRecords: 0,
      eventCount: 0,
      metricPointCount: 0,
      promptCount: 0,
      message: "未载入个例来源画像；当前空态不代表无风险。",
    };
  }
  const sourceRevisionStates = [
    rawProfile.source_revision,
    rawProfile.source_version,
    rawProfile.subject_source_revision,
  ].map(explicitLineageTokenState);
  const sourceBatchStates = [
    rawProfile.source_batch_id,
    rawProfile.source_batch,
    rawProfile.batch_id,
    rawProfile.batch,
  ].map(explicitLineageTokenState);
  const sourceRevision = sourceRevisionStates.find((state) => state.value)?.value || "";
  const sourceBatch = sourceBatchStates.find((state) => state.value)?.value || "";
  const malformedLineageFields = [
    ...sourceRevisionStates,
    ...sourceBatchStates,
  ].filter((state) => state.malformed).length;
  const events = Array.isArray(rawProfile.timeline) ? rawProfile.timeline.filter(isRecord) : [];
  const metrics = [
    ...(Array.isArray(rawProfile.efficacy_trends) ? rawProfile.efficacy_trends : []),
    ...(Array.isArray(rawProfile.safety_trends) ? rawProfile.safety_trends : []),
  ];
  const metricPoints = metrics.flatMap((metric) => (Array.isArray(metric?.points) ? metric.points : []))
    .filter(isRecord);
  const prompts = Array.isArray(rawProfile.risk_prompts)
    ? rawProfile.risk_prompts.filter(isRecord)
    : [];
  const records = [...events, ...metricPoints, ...prompts];
  const locatorStates = records.map((record) => explicitSourceLocatorState(record));
  const tracedRecords = locatorStates.filter((state) => state.status === "bound").length;
  const totalRecords = records.length;
  const untracedRecords = totalRecords - tracedRecords;
  const malformedLocatorRecords = locatorStates.filter((state) => state.status === "malformed").length;
  const common = {
    sourceRevision,
    sourceBatch,
    malformedLineageFields,
    totalRecords,
    tracedRecords,
    untracedRecords,
    malformedLocatorRecords,
    eventCount: events.length,
    metricPointCount: metricPoints.length,
    promptCount: prompts.length,
  };
  if (malformedLineageFields > 0) {
    return {
      ...common,
      status: "partial",
      label: "来源绑定形状异常",
      message: `来源修订/批次字段有 ${malformedLineageFields} 项形状异常；保留的合法字符串仅供回到来源核对，不能据此证明来源真实性、完整性或趋势可比。`,
    };
  }
  if (sourceRevision && untracedRecords > 0) {
    return {
      ...common,
      status: "partial",
      label: malformedLocatorRecords ? "来源定位需核对" : "来源部分绑定",
      message: malformedLocatorRecords
        ? `来源修订 ${sourceRevision} 已绑定，但 ${malformedLocatorRecords} 条事件/趋势点/风险提示的来源定位字段形状异常；其余未完整定位记录共 ${untracedRecords}/${totalRecords} 条，不能据此证明完整性或趋势可比。`
        : `来源修订 ${sourceRevision} 已绑定，但 ${untracedRecords}/${totalRecords} 条事件/趋势点/风险提示缺少显式来源定位；不能据此证明完整性或趋势可比。`,
    };
  }
  if (sourceRevision) {
    return {
      ...common,
      status: "bound",
      label: "来源已绑定",
      message: totalRecords
        ? `来源修订 ${sourceRevision}；${tracedRecords}/${totalRecords} 条事件/趋势点/风险提示具备显式来源定位。`
        : `来源修订 ${sourceRevision} 已绑定；当前没有事件、趋势点或风险提示，完整性与无风险不能由空态证明。`,
    };
  }
  if (sourceBatch) {
    return {
      ...common,
      status: "partial",
      label: "仅有批次标识",
      message: `仅有来源批次 ${sourceBatch}；缺少明确 source_revision/source_version，不能证明跨批次趋势可比或完整性。`,
    };
  }
  return {
    ...common,
    status: "unbound",
    label: "缺少来源绑定",
    message: "缺少明确 source_revision/source_version；不能证明当前画像与原始 listing 的版本关系，也不能将空态视为无风险。",
  };
}

export function eventTone(event) {
  if (["critical", "high", "严重", "重度", "3级", "4级", "5级"].some((value) => String(event.severity || "").includes(value))) return "critical";
  if (event.related_risk_ids?.length || ["protocol_deviation", "query"].includes(event.event_type)) return "critical";
  if (event.event_type === "lab" && event.clinical_interpretation) return "warning";
  if (event.event_type === "efficacy_score" && event.clinical_interpretation) return "warning";
  if (event.event_type === "efficacy_score") return "good";
  if (event.event_type === "medical_history") return "source";
  return "normal";
}

export function timelineLaneClassName(laneKey) {
  return `lane-${String(laneKey).toLowerCase().replace(/_/g, "-")}`;
}

export function timelineEventCategoryKey(event) {
  const text = [event.title, event.detail, event.clinical_interpretation].filter(Boolean).join(" ");
  if ([
    "study_drug_dispensing",
    "study_drug_administration",
    "study_drug_adherence",
    "background_treatment",
    "non_drug_treatment",
  ].includes(event.event_type)) {
    return event.event_type;
  }
  if (event.event_type === "dose_adjustment") {
    if (event.event_subtype === "study_drug_interruption" || text.includes("暂停用药")) return "dose_adjustment_paused";
    if (event.event_subtype === "study_drug_resumption" || text.includes("重新用药") || text.includes("恢复")) return "dose_adjustment_resumed";
    return "dose_adjustment";
  }
  if (event.event_type === "lab") {
    if (event.source_domain === "LBHEMA") return "lab_hematology";
    if (event.source_domain === "LBCHEM") return "lab_chemistry";
    return "lab";
  }
  if (event.event_type === "concomitant_medication") {
    if (/禁用|限制|洗脱|违背|风险|PD|query/i.test(text)) return "concomitant_medication_risk";
    return "concomitant_medication";
  }
  if (event.event_type === "adverse_event") {
    if (event.related_risk_ids?.length || /复核提示|漏报|给药调整|需医学复核|实验室关联风险/.test(text)) return "adverse_event_review";
    return "adverse_event";
  }
  return event.event_type;
}

export function timelineEventCategoryDef(event) {
  return timelineEventCategoryDefs[timelineEventCategoryKey(event)] || {
    label: event.source_domain || "事件",
    className: "event-category-other",
  };
}

export function eventCategoryClassName(event) {
  return timelineEventCategoryDef(event).className;
}

export function timelineEventCategoryLabel(event) {
  return timelineEventCategoryDef(event).label;
}

export function timelineLegendItems(lanes = []) {
  const seen = new Set();
  return lanes.flatMap((lane) => lane.events.map(({ event }) => {
    const category = timelineEventCategoryDef(event);
    const key = `${lane.key}-${timelineEventCategoryKey(event)}-${category.className}`;
    if (seen.has(key)) return null;
    seen.add(key);
    return { ...category, key, laneLabel: lane.label };
  })).filter(Boolean);
}

export function timelineLegendLabel(item) {
  if (item.laneLabel === item.label) return item.label;
  if (item.laneLabel === "实验室/疗效") return item.label;
  if (item.laneLabel === "合并用药（非试验用药）" && item.label === "CM非试验用药") return item.laneLabel;
  return `${item.laneLabel} · ${item.label}`;
}

export function visitAxisFromEvents(events = []) {
  const visits = events
    .filter((event) => event.event_type === "visit")
    .map((event) => ({
      code: event.visit_code || `D${event.study_day}`,
      label: event.visit_label || event.title,
      day: Number.isFinite(event.study_day) ? event.study_day : null,
      date: event.event_date,
      title: event.title,
      anchorId: event.event_id || event.source_record_id || event.source_locator,
      plannedDay: null,
      isUnscheduled: Boolean(event.is_unscheduled),
      deviationDays: null,
    }));
  if (visits.length) {
    return visits.sort((left, right) => (
      String(left.date || "").localeCompare(String(right.date || ""))
      || (left.day ?? Number.MAX_SAFE_INTEGER) - (right.day ?? Number.MAX_SAFE_INTEGER)
    ));
  }
  const byVisit = new Map();
  for (const event of events) {
    const code = event.visit_code || (Number.isFinite(event.study_day) ? `D${event.study_day}` : "未标注访视");
    if (!byVisit.has(code)) {
      byVisit.set(code, {
        code,
        label: event.visit_label || code,
        day: Number.isFinite(event.study_day) ? event.study_day : null,
        date: event.event_date,
        title: event.visit_label || code,
        anchorId: event.event_id || event.source_record_id || event.source_locator,
        plannedDay: null,
        isUnscheduled: Boolean(event.is_unscheduled),
        deviationDays: null,
      });
    }
  }
  return [...byVisit.values()].sort((left, right) => (
    String(left.date || "").localeCompare(String(right.date || ""))
    || (left.day ?? Number.MAX_SAFE_INTEGER) - (right.day ?? Number.MAX_SAFE_INTEGER)
  ));
}

export function dateAtStudyDay(baselineDate, studyDay) {
  if (!hasActualTimelineDate(baselineDate)) return "";
  const match = String(baselineDate).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return "";
  const parsed = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  if (Number.isNaN(parsed.getTime())) return "";
  parsed.setUTCDate(parsed.getUTCDate() + studyDay - 1);
  return parsed.toISOString().slice(0, 10);
}

function isValidCalendarDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1) return false;
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= daysInMonth[month - 1];
}

/**
 * Return true only for a complete, calendar-valid actual date. Planned study
 * days and partial dates are intentionally excluded from this presentation
 * contract so they cannot be rendered as a false date-axis position.
 */
export function hasActualTimelineDate(value) {
  return isValidCalendarDate(value);
}

function dateCoverageForRows(rows, field) {
  const dated = rows.filter((row) => hasActualTimelineDate(row[field])).length;
  const supplied = rows.filter((row) => String(row[field] || "").trim()).length;
  return {
    total: rows.length,
    dated,
    undated: rows.length - dated,
    invalid: supplied - dated,
  };
}

/**
 * Describe how much actual-date evidence is available for a timeline.
 * This is descriptive only: it never derives an actual date from study day,
 * planned visit, visit code, or a partial date.
 */
export function timelineDataCoverage(visits = [], events = []) {
  const visitRows = Array.isArray(visits) ? visits.filter(isRecord) : [];
  const eventRows = Array.isArray(events) ? events.filter(isRecord) : [];
  const visitCoverage = dateCoverageForRows(visitRows, "date");
  const eventCoverage = dateCoverageForRows(eventRows, "event_date");
  const datedRecords = visitCoverage.dated + eventCoverage.dated;
  const unresolvedRecords = visitCoverage.undated + eventCoverage.undated;
  return {
    totalVisits: visitCoverage.total,
    datedVisits: visitCoverage.dated,
    undatedVisits: visitCoverage.undated,
    invalidVisitDates: visitCoverage.invalid,
    totalEvents: eventCoverage.total,
    datedEvents: eventCoverage.dated,
    undatedEvents: eventCoverage.undated,
    invalidEventDates: eventCoverage.invalid,
    hasDateAxis: datedRecords > 0,
    status: datedRecords === 0 ? "no_actual_dates" : unresolvedRecords ? "partial_dates" : "date_bound",
  };
}

export function plannedVisitAxis(subject, events = []) {
  const anchors = subject.rawProfile?.visit_anchors || subject.visitAnchors || [];
  if (!anchors.length) return visitAxisFromEvents(events);
  return anchors
    .map((anchor) => ({
      anchorId: anchor.anchor_id || anchor.source_record_id || anchor.source_locator,
      code: anchor.visit_code,
      label: anchor.visit_label || anchor.visit_code,
      day: Number.isFinite(anchor.actual_study_day)
        ? anchor.actual_study_day
        : Number.isFinite(anchor.planned_study_day) ? anchor.planned_study_day : null,
      plannedDay: Number.isFinite(anchor.planned_study_day) ? anchor.planned_study_day : null,
      date: anchor.actual_date || "",
      title: anchor.visit_label || anchor.visit_code,
      isUnscheduled: Boolean(anchor.is_unscheduled),
      deviationDays: Number.isFinite(anchor.deviation_days) ? anchor.deviation_days : null,
      windowBeforeDays: anchor.window_before_days,
      windowAfterDays: anchor.window_after_days,
      sourceLocator: anchor.source_locator,
    }))
    .sort((left, right) => (
      String(left.date || "").localeCompare(String(right.date || ""))
      || (left.day ?? Number.MAX_SAFE_INTEGER) - (right.day ?? Number.MAX_SAFE_INTEGER)
      || String(left.anchorId || "").localeCompare(String(right.anchorId || ""))
    ));
}

function displayVisitIdentity(visit) {
  const value = visit?.anchorId;
  return typeof value === "string" ? value.trim() : "";
}

/**
 * Add display-only identity metadata to timeline visits. Missing or duplicate
 * anchor IDs remain visible and retain source order; the display key is never
 * sent to an API and never replaces the visit/source identity.
 */
export function timelineVisitDisplayRows(visits = []) {
  const rows = Array.isArray(visits) ? visits.filter(isRecord) : [];
  const identityCounts = new Map();
  rows.forEach((visit) => {
    const identity = displayVisitIdentity(visit);
    if (identity) identityCounts.set(identity, (identityCounts.get(identity) || 0) + 1);
  });
  return rows.map((visit, displaySourceIndex) => {
    const identity = displayVisitIdentity(visit);
    const duplicate = Boolean(identity && (identityCounts.get(identity) || 0) > 1);
    return {
      visit,
      displaySourceIndex,
      displayIdentityState: !identity ? "missing" : duplicate ? "duplicate" : "ready",
      displayIdentityIssue: !identity
        ? "访视缺少 anchor_id/source identity；保留访视事实，暂不能确认单点来源"
        : duplicate
          ? "访视 anchor_id/source identity 重复；保留访视事实，暂不能确认单点来源"
          : "",
      displayKey: `timeline-visit:${identity || "missing"}:${displaySourceIndex}`,
    };
  });
}

export function laneForEvent(event) {
  return timelineLaneDefs.find((lane) => lane.types.includes(event.event_type))?.key || "OTHER";
}

function displayIdentityPart(value) {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (Number.isSafeInteger(value)) return String(value);
  return "";
}

/**
 * Return a display-only selection identity. This is deliberately namespaced
 * and never replaces event_id, source identity or risk identity. A source
 * record/locator is safer than a positional fallback when a listing omits
 * event_id; the lane builder adds a suffix when even that base is duplicated.
 */
export function timelineEventSelectionKey(event, fallback = "unknown") {
  const candidates = [
    ["event", event?.event_id],
    ["source-record", event?.source_record_id],
    ["source-locator", event?.source_locator],
    ["evidence-locator", event?.evidence_locator],
  ];
  const explicit = candidates
    .map(([prefix, value]) => {
      const part = displayIdentityPart(value);
      return part ? `${prefix}:${part}` : "";
    })
    .find(Boolean);
  return explicit || `fallback:${String(fallback || "unknown")}`;
}

export function shortTimelineEventLabel(event, laneIndex) {
  const prefix = {
    adverse_event: "AE",
    study_drug_dispensing: "IPD",
    study_drug_administration: "IPA",
    study_drug_adherence: "IPA",
    background_treatment: "BG",
    non_drug_treatment: "PR",
    dose_adjustment: "DA",
    concomitant_medication: "CM",
    medical_history: "MH",
    lab: "LB",
    efficacy_score: "QS",
    protocol_deviation: "PD",
    query: "Q",
  }[event.event_type] || event.source_domain || "E";
  return `${prefix}${laneIndex + 1}`;
}

export function referenceTimelineLanes(events = []) {
  const coreLaneKeys = new Set(["AE", "IP", "CM", "MH"]);
  return timelineLaneDefs
    .map((lane) => {
      const usedSelectionKeys = new Set();
      const laneEvents = events
        .filter((event) => laneForEvent(event) === lane.key)
        .sort((left, right) => (
          String(left.event_date || "").localeCompare(String(right.event_date || ""))
          || (left.study_day ?? Number.MAX_SAFE_INTEGER) - (right.study_day ?? Number.MAX_SAFE_INTEGER)
          || String(left.event_id).localeCompare(String(right.event_id))
        ))
        .map((event, index) => {
          const baseKey = timelineEventSelectionKey(event, `${lane.key}:${index}`);
          let selectionKey = baseKey;
          let suffix = 2;
          while (usedSelectionKeys.has(selectionKey)) {
            selectionKey = `${baseKey}#${suffix}`;
            suffix += 1;
          }
          usedSelectionKeys.add(selectionKey);
          return {
            event,
            displayLabel: shortTimelineEventLabel(event, index),
            selectionKey,
          };
        });
      return { ...lane, events: laneEvents };
    })
    .filter((lane) => lane.events.length || coreLaneKeys.has(lane.key));
}

export function referenceEventTooltip(event, label) {
  const precisionLabel = {
    day: "日",
    month: "月",
    year: "年",
    unknown: "未知",
  }[event.date_precision] || event.date_precision;
  const displayStart = event.raw_event_date || event.event_date;
  const displayEnd = event.raw_event_end_date || event.event_end_date;
  const eventWindow = [
    displayStart,
    displayEnd ? `至 ${displayEnd}` : event.ongoing ? "持续中" : "",
    event.date_precision && event.date_precision !== "day" ? `日期精度：${precisionLabel}` : "",
    event.raw_event_date && event.event_date && event.raw_event_date !== event.event_date
      ? `时间轴定位：${event.event_date}`
      : "",
  ].filter(Boolean).join(" ");
  return [
    label,
    eventWindow,
    event.visit_code || `D${event.study_day}`,
    event.title,
    event.detail,
    event.severity ? `严重程度：${event.severity}` : "",
    event.relationship ? `相关性：${event.relationship}` : "",
    event.outcome ? `转归：${event.outcome}` : "",
    event.clinical_interpretation,
    event.source_record_id ? `来源：${event.source_record_id}` : "",
  ].filter(Boolean).join("｜");
}

export function timelineHeaderMeta(subject, events = []) {
  const overview = subject.rawProfile?.subject;
  const anchorDates = (subject.rawProfile?.visit_anchors || [])
    .map((anchor) => anchor.actual_date)
    .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(String(value || "")));
  const visitDates = events
    .filter((event) => event.event_type === "visit")
    .map((event) => event.event_date)
    .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(String(value || "")))
    .concat(anchorDates, [overview?.latest_visit_date])
    .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(String(value || "")))
    .sort();
  const allDates = [
    overview?.first_dose_date,
    overview?.baseline_visit_date,
    overview?.latest_visit_date,
    ...events.map((event) => event.event_date),
  ]
    .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(String(value || "")))
    .sort();
  const eventDates = visitDates.length ? visitDates : allDates;
  const windowStart = eventDates[0] || "";
  const windowEnd = eventDates.at(-1) || windowStart;
  const site = overview?.site_id || subject.site || "-";
  const sex = overview?.sex || overview?.gender || "";
  const age = overview?.age_years ?? overview?.age;
  const demographic = [
    sex || "性别未提供",
    age === undefined || age === null || age === "" ? "年龄未提供" : `${age}岁`,
    overview?.enrollment_status || subject.status || "状态未提供",
  ];
  return {
    subjectId: subject.id,
    arm: overview?.treatment_arm || "治疗组未提供",
    randomization: overview?.randomization_number || overview?.screening_number || "随机号未提供",
    site,
    center: overview?.center_name || overview?.site_name || `中心 ${site}`,
    window: [windowStart, windowEnd].filter(Boolean).join(" ~ "),
    sexAgeStatus: demographic.join(" | "),
  };
}

function displayEvidenceValue(value) {
  if (value === undefined || value === null) return "";
  if (typeof value === "string" || typeof value === "number") return String(value).trim();
  if (Array.isArray(value)) return value.map(displayEvidenceValue).filter(Boolean).join("、");
  if (isRecord(value)) {
    return Object.entries(value)
      .map(([key, item]) => {
        const display = displayEvidenceValue(item);
        return display ? `${key}=${display}` : "";
      })
      .filter(Boolean)
      .join(", ");
  }
  return "";
}

function firstExplicitValue(...values) {
  return values.map(displayEvidenceValue).find(Boolean) || "";
}

function explicitReferenceIdList(...values) {
  const malformed = values.some((value) => (
    value !== undefined
    && value !== null
    && (!Array.isArray(value)
      || value.some((item) => typeof item !== "string" || !item.trim()))
  ));
  const items = [...new Set(values
    .flatMap((value) => (Array.isArray(value) ? value : typeof value === "string" ? [value] : []))
    .filter((value) => typeof value === "string" && value.trim())
    .map((value) => value.trim()))];
  return { values: items, malformed };
}

function explicitReferenceToken(value) {
  if (value === undefined || value === null) return { value: "", malformed: false };
  if (typeof value !== "string") return { value: "", malformed: true };
  const text = value.trim();
  return { value: text, malformed: !text };
}

function linkedEventIdState(event) {
  return explicitReferenceIdList(
    event?.related_event_ids,
    event?.linked_event_ids,
    event?.related_ae_ids,
    event?.linked_ae_ids,
  );
}

function sourceLocatorText(record, label = "来源定位") {
  const locator = firstExplicitValue(
    record?.source_locator,
    record?.evidence_locator,
    record?.source_record_id,
  );
  return locator ? `${label}：${locator}` : "";
}

function subjectAeEvidence(aeEvent, aePrompt, labEvent) {
  const eventEvidence = [
    displayEvidenceValue(aeEvent?.title),
    displayEvidenceValue(aeEvent?.detail),
    aeEvent?.severity ? `严重程度：${displayEvidenceValue(aeEvent.severity)}` : "",
    aeEvent?.relationship ? `相关性：${displayEvidenceValue(aeEvent.relationship)}` : "",
    aeEvent?.outcome ? `转归：${displayEvidenceValue(aeEvent.outcome)}` : "",
    displayEvidenceValue(aeEvent?.clinical_interpretation),
    aeEvent?.event_date ? `日期：${displayEvidenceValue(aeEvent.event_date)}` : "",
    aeEvent?.visit_code ? `访视：${displayEvidenceValue(aeEvent.visit_code)}` : "",
    sourceLocatorText(aeEvent, "AE来源"),
  ].filter(Boolean);
  const promptEvidence = [
    displayEvidenceValue(aePrompt?.prompt_text),
    aePrompt?.recommended_action ? `建议：${displayEvidenceValue(aePrompt.recommended_action)}` : "",
    aePrompt?.status ? `提示状态：${displayEvidenceValue(aePrompt.status)}` : "",
    sourceLocatorText(aePrompt, "提示来源"),
  ].filter(Boolean);
  const suppliedSafetyBasis = firstExplicitValue(
    aeEvent?.safety_topic,
    aeEvent?.safety_reference,
    aeEvent?.safety_basis,
    aePrompt?.safety_topic,
    aePrompt?.safety_reference,
    aePrompt?.evidence_summary,
  );
  const labEvidence = labEvent
    ? [
      `关联实验室：${displayEvidenceValue(labEvent.title)}`,
      displayEvidenceValue(labEvent.detail),
      displayEvidenceValue(labEvent.clinical_interpretation),
      sourceLocatorText(labEvent, "实验室来源"),
    ].filter(Boolean)
    : [];
  if (suppliedSafetyBasis) eventEvidence.push(`安全性依据：${suppliedSafetyBasis}`);
  return [...eventEvidence, ...labEvidence, ...promptEvidence].filter(Boolean).join(" | ");
}

export function referenceRiskCards(subject) {
  const prompts = subject.rawProfile?.risk_prompts || [];
  const events = subject.rawProfile?.timeline || [];
  const cmEvent = events.find((event) => event.source_domain === "CM");
  const pdEvent = events.find((event) => event.source_domain === "PD");
  const aeEvent = events.find((event) => event.source_domain === "AE");
  const washoutPrompt = prompts.find((prompt) => prompt.risk_type?.includes("washout")) || prompts[0];
  const aePrompt = prompts.find((prompt) => prompt.risk_type?.includes("ae") || prompt.risk_type?.includes("lab")) || prompts[1] || prompts[0];
  const linkShapeWarnings = [];
  const aeEventIdState = explicitReferenceToken(aeEvent?.event_id);
  const aeRiskIdState = explicitReferenceIdList(aeEvent?.related_risk_ids);
  if (aeEventIdState.malformed) linkShapeWarnings.push("AE事件 ID");
  if (aeRiskIdState.malformed) linkShapeWarnings.push("AE风险关联");
  const aeEventId = aeEventIdState.malformed ? "" : aeEventIdState.value;
  const aeRiskIds = aeRiskIdState.malformed ? [] : aeRiskIdState.values;
  const labEvent = aeEvent && events.find((event) => {
    if (event.event_type !== "lab") return false;
    const linkedEventState = linkedEventIdState(event);
    const labRiskState = explicitReferenceIdList(event.related_risk_ids);
    if (linkedEventState.malformed || labRiskState.malformed) {
      linkShapeWarnings.push("AE/实验室关联字段");
      return false;
    }
    const relatedIds = linkedEventState.values;
    const labRiskIds = labRiskState.values;
    return (
      (aeEventId && relatedIds.includes(aeEventId))
      || aeRiskIds.some((riskId) => labRiskIds.includes(riskId))
    );
  });
  const linkShapeNotice = linkShapeWarnings.length
    ? `关联实验室未自动合并：${[...new Set(linkShapeWarnings)].join("、")}形状异常；请回到来源核对，不能据此判定无风险。`
    : "";
  const cmTitle = String(cmEvent?.title || "CM事件");
  const cmDetail = String(cmEvent?.detail || "用药详情未提供");
  const cmDate = String(cmEvent?.event_date || "日期未提供");
  return [
    {
      title: "潜在合并用药违背",
      body: cmEvent
        ? `${cmTitle.replace("筛选期使用", "")} | ${cmDetail.replace("用于", "| 用于")} | ${cmDate} | ${pdEvent ? "PD/Query待关闭" : "需医学确认"}`
        : washoutPrompt?.prompt_text || "未提供合并用药证据，暂不能判定。",
      accent: "strong",
    },
    {
      title: "潜在入排违背PD",
      body: pdEvent?.detail || washoutPrompt?.recommended_action || "未提供可用于入排违背判断的 PD/病史证据。",
      accent: "plain",
    },
    {
      title: "潜在AE评估不当",
      body: aeEvent
        ? [subjectAeEvidence(aeEvent, aePrompt, labEvent) || "AE记录存在，需医学复核。", linkShapeNotice]
          .filter(Boolean)
          .join(" | ")
        : aePrompt?.prompt_text || "未提供AE记录或复核依据，暂不能判定。",
      accent: "strong",
    },
  ];
}

export function subjectCenterGroups(items = []) {
  const groups = new Map();
  items.forEach((item) => {
    const center = item.site || "未分中心";
    if (!groups.has(center)) groups.set(center, []);
    groups.get(center).push(item);
  });
  return Array.from(groups.entries())
    .sort(([left], [right]) => String(left).localeCompare(String(right), "zh-CN", { numeric: true }))
    .map(([center, centerSubjects]) => ({
      center,
      subjects: centerSubjects.sort((left, right) => String(left.id).localeCompare(String(right.id), "zh-CN", { numeric: true })),
    }));
}

function subjectCatalogIdentity(item) {
  for (const value of [item?.id, item?.subject_id]) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return "";
}

/**
 * Add display-only identity metadata to the Patient Profile/Subject Timeline
 * subject catalog. Missing or duplicate IDs remain visible, but their rows
 * must not be treated as an unambiguous navigation target. No source ID is
 * rewritten and these fields never enter a request payload.
 */
export function subjectCatalogDisplayRows(subjects = []) {
  const rows = Array.isArray(subjects) ? subjects : [];
  const identityCounts = new Map();
  rows.forEach((item) => {
    const identity = subjectCatalogIdentity(item);
    if (identity) identityCounts.set(identity, (identityCounts.get(identity) || 0) + 1);
  });
  return rows.map((item, displaySourceIndex) => {
    const base = isRecord(item) ? item : {};
    const identity = subjectCatalogIdentity(item);
    const duplicate = Boolean(identity && (identityCounts.get(identity) || 0) > 1);
    return {
      ...base,
      displaySourceIndex,
      displaySubjectId: identity,
      displayIdentityState: !identity ? "missing" : duplicate ? "duplicate" : "ready",
      displayIdentityIssue: !identity
        ? "受试者缺少 subject_id/id；仅可读，暂不能选择"
        : duplicate
          ? "受试者 subject_id/id 重复；保留目录但暂不能选择"
          : "",
      displayKey: `subject-catalog:${identity || "missing"}:${displaySourceIndex}`,
    };
  });
}

export function subjectCatalogSubjectId(item) {
  return item?.displaySubjectId || subjectCatalogIdentity(item);
}

export function profileSubjectMeta(subject) {
  const raw = subject.rawProfile?.subject;
  return [
    { label: "中心", value: raw?.site_id || subject.site },
    { label: "筛选号", value: raw?.screening_number },
    { label: "随机号", value: raw?.randomization_number },
    { label: "治疗组", value: raw?.treatment_arm },
    { label: "入组状态", value: raw?.enrollment_status },
    { label: "基线/随机日期", value: raw?.baseline_visit_date },
    { label: "首次给药", value: raw?.first_dose_date },
    { label: "最近访视", value: [raw?.latest_visit_code, raw?.latest_visit_label, raw?.latest_visit_date].filter(Boolean).join(" / ") },
  ].filter((item) => item.value);
}

export function metricRiskCount(metric) {
  return (metric.points || []).filter((point) => point.risk_flag || ["high", "low"].includes(point.normality)).length;
}

/**
 * Describe which metric points are safe to place on a numeric chart. Raw
 * points remain available to the detail list; non-numeric values are never
 * coerced into a clinical measurement or allowed to produce NaN geometry.
 */
export function metricDataCoverage(metric) {
  const points = Array.isArray(metric?.points)
    ? metric.points.filter(isRecord)
    : [];
  const numericPoints = points.filter((point) => typeof point.value === "number" && Number.isFinite(point.value));
  const datedPoints = points.filter((point) => hasActualTimelineDate(point.assessment_date));
  const drawablePoints = points.filter((point) => (
    typeof point.value === "number"
    && Number.isFinite(point.value)
    && hasActualTimelineDate(point.assessment_date)
  ));
  const status = drawablePoints.length === 0
    ? points.length === 0
      ? "empty"
      : numericPoints.length === 0
        ? "no_numeric_values"
        : datedPoints.length === 0
          ? "no_actual_dates"
          : "no_drawable_values"
    : drawablePoints.length < points.length ? "partial_numeric_or_date" : "numeric_and_date_bound";
  return {
    totalPoints: points.length,
    numericPoints: numericPoints.length,
    drawablePoints: drawablePoints.length,
    invalidValuePoints: points.length - numericPoints.length,
    datedPoints: datedPoints.length,
    undatedDatePoints: points.length - datedPoints.length,
    hasDrawableValues: drawablePoints.length > 0,
    status,
  };
}

/**
 * Keep an empty Profile metric section honest about why it is empty. An empty
 * trend is not evidence of stability or absence of risk; the message only
 * reflects explicit capability/source metadata already present on the subject.
 */
export function profileMetricEmptyStateMessage(subject, metricKind) {
  const kind = metricKind === "safety" ? "安全性" : "疗效";
  const metricField = metricKind === "safety" ? "safetyMetrics" : "efficacyMetrics";
  if (Array.isArray(subject?.[metricField]) && subject[metricField].length) return "";
  const rawProfile = isRecord(subject?.rawProfile) ? subject.rawProfile : null;
  if (!rawProfile) {
    return `当前个例资料尚未载入完整${kind}趋势；不能据此判定${kind}稳定或无风险。`;
  }
  if (rawProfile.capability_mode === "restricted") {
    return `当前字段映射处于受限模式，尚无可展示的${kind}趋势；请先核对来源与字段映射，空态不代表${kind}稳定或无风险。`;
  }
  const domains = Array.isArray(rawProfile.domain_availability)
    ? rawProfile.domain_availability.filter(isRecord)
    : [];
  const tokens = metricKind === "safety"
    ? ["laboratory", "lab", "adverse_event", "ae", "vitals", "ecg"]
    : ["efficacy"];
  const matched = domains.filter((item) => tokens.includes(String(item.domain || "").trim().toLowerCase()));
  if (matched.length && matched.every((item) => String(item.status || "").trim().toLowerCase() !== "available")) {
    return `当前来源未提供可用的${kind}记录；请核对数据域可用性，不能据此判定${kind}稳定或无风险。`;
  }
  return `当前未提供可用的${kind}趋势；请核对来源与字段映射，不能据此判定${kind}稳定或无风险。`;
}

const PROFILE_DOMAIN_LABELS = Object.freeze({
  visit: "访视",
  adverse_event: "AE",
  medical_history: "病史",
  concomitant_medication: "非试验用药",
  study_drug: "试验药物",
  background_treatment: "方案背景治疗",
  non_drug_treatment: "非药物治疗",
  laboratory: "实验室检查",
  efficacy: "疗效评估",
  protocol_deviation: "方案偏离",
  query: "Query",
});

const PROFILE_DOMAIN_STATUS_META = Object.freeze({
  available: { statusLabel: "已提供", tone: "success", detail: "来源/映射声明该域可用" },
  absent: { statusLabel: "未见记录", tone: "info", detail: "来源中未发现该受试者记录" },
  unmapped: { statusLabel: "尚未映射", tone: "warning", detail: "来源域存在，但字段映射尚未确认" },
  unsupported: { statusLabel: "当前不支持", tone: "warning", detail: "当前能力未支持该域的派生展示" },
  unknown: { statusLabel: "状态待核对", tone: "danger", detail: "来源状态值无法识别" },
  malformed: { statusLabel: "声明格式异常", tone: "danger", detail: "数据域覆盖声明形状异常" },
});

const PROFILE_DOMAIN_DISCLAIMER = "覆盖状态仅反映来源/字段映射声明，不代表该域无风险或无需医学复核。";

function profileDomainStatusMeta(rawStatus) {
  const status = typeof rawStatus === "string" ? rawStatus.trim().toLowerCase() : "";
  if (Object.prototype.hasOwnProperty.call(PROFILE_DOMAIN_STATUS_META, status)) {
    return { status, ...PROFILE_DOMAIN_STATUS_META[status] };
  }
  return {
    status: status ? "unknown" : "malformed",
    ...PROFILE_DOMAIN_STATUS_META[status ? "unknown" : "malformed"],
  };
}

/**
 * Turn the explicit API domain-availability declaration into display facts.
 * Missing/empty declarations stay distinct from an explicit `absent` domain;
 * metric arrays are intentionally never consulted, so the view cannot infer
 * coverage or absence from whatever happens to be rendered elsewhere.
 */
export function profileDomainCoverage(profile) {
  const rawProfile = isRecord(profile) ? profile : null;
  const shapeWarnings = Array.isArray(rawProfile?.profile_shape_warnings)
    ? rawProfile.profile_shape_warnings.filter((item) => typeof item === "string")
    : [];
  const domainShapeWarning = shapeWarnings.some((item) => (
    item === "domain_availability" || item.startsWith("domain_availability[")
  ));
  if (!rawProfile || rawProfile.domain_availability === undefined || rawProfile.domain_availability === null) {
    return {
      declarationState: "missing",
      declarationLabel: "未提供覆盖声明",
      declarationMessage: "当前来源未提供数据域覆盖声明；请先核对来源与字段映射。",
      domains: [],
      availableCount: 0,
      declaredCount: 0,
      disclaimer: PROFILE_DOMAIN_DISCLAIMER,
    };
  }
  if (!Array.isArray(rawProfile.domain_availability)) {
    return {
      declarationState: "malformed",
      declarationLabel: "覆盖声明待核对",
      declarationMessage: "数据域覆盖声明格式异常；已停止按域解释，请回到来源证据核查。",
      domains: [{
        key: "malformed:domain_availability",
        domain: "",
        label: "声明格式异常",
        status: "malformed",
        ...PROFILE_DOMAIN_STATUS_META.malformed,
        sourceLocator: "",
      }],
      availableCount: 0,
      declaredCount: 0,
      disclaimer: PROFILE_DOMAIN_DISCLAIMER,
    };
  }
  if (rawProfile.domain_availability.length === 0) {
    if (domainShapeWarning) {
      return {
        declarationState: "malformed",
        declarationLabel: "覆盖声明待核对",
        declarationMessage: "数据域覆盖声明存在形状异常；空列表不代表相关数据域不存在。",
        domains: [{
          key: "malformed:domain_availability",
          domain: "",
          label: "声明格式异常",
          status: "malformed",
          ...PROFILE_DOMAIN_STATUS_META.malformed,
          sourceLocator: "",
        }],
        availableCount: 0,
        declaredCount: 0,
        disclaimer: PROFILE_DOMAIN_DISCLAIMER,
      };
    }
    return {
      declarationState: "empty",
      declarationLabel: "覆盖声明为空",
      declarationMessage: "当前来源未列出任何数据域覆盖状态；空列表不代表相关数据域不存在。",
      domains: [],
      availableCount: 0,
      declaredCount: 0,
      disclaimer: PROFILE_DOMAIN_DISCLAIMER,
    };
  }
  const domains = rawProfile.domain_availability.map((record, index) => {
    if (!isRecord(record)) {
      return {
        key: `malformed:${index}`,
        domain: "",
        label: `声明格式异常 ${index + 1}`,
        status: "malformed",
        ...PROFILE_DOMAIN_STATUS_META.malformed,
        sourceLocator: "",
      };
    }
    const domain = typeof record.domain === "string" ? record.domain.trim().toLowerCase() : "";
    const statusMeta = profileDomainStatusMeta(record.status);
    const label = PROFILE_DOMAIN_LABELS[domain]
      || (typeof record.label === "string" && record.label.trim() ? record.label.trim() : domain || `未标注域 ${index + 1}`);
    return {
      key: `${domain || "unlabeled"}:${index}`,
      domain,
      label,
      ...statusMeta,
      detail: typeof record.detail === "string" && record.detail.trim() ? record.detail.trim() : statusMeta.detail,
      sourceLocator: typeof record.source_locator === "string" ? record.source_locator.trim() : "",
    };
  });
  const displayDomains = domainShapeWarning
    ? [...domains, {
      key: "malformed:domain_availability",
      domain: "",
      label: "声明格式异常",
      status: "malformed",
      ...PROFILE_DOMAIN_STATUS_META.malformed,
      sourceLocator: "",
    }]
    : domains;
  return {
    declarationState: domainShapeWarning ? "declared_with_shape_warning" : "declared",
    declarationLabel: domainShapeWarning ? "部分声明待核对" : "已提供覆盖声明",
    declarationMessage: domainShapeWarning
      ? "部分数据域覆盖声明存在形状异常；以下状态仅限可解析部分。"
      : "以下状态来自来源/字段映射声明。",
    domains: displayDomains,
    availableCount: displayDomains.filter((item) => item.status === "available").length,
    declaredCount: displayDomains.length,
    disclaimer: PROFILE_DOMAIN_DISCLAIMER,
  };
}

export function relatedTimelineEvents(events, types) {
  return events.filter((event) => types.includes(event.event_type));
}

export function monitoringStatusClass(value) {
  if (["critical", "高风险复核", "需行动", "不通过"].includes(value)) return "danger";
  if (["failed"].includes(value)) return "danger";
  if (["high", "中风险复核", "复核中", "待确认", "待补证", "医学审阅中", "溯源提醒", "blocked"].includes(value)) return "warning";
  if (["已关闭", "通过", "已批准", "可进入筛选", "completed"].includes(value)) return "success";
  return "info";
}
