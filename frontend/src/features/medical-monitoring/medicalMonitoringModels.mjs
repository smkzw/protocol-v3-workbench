export const UNKNOWN_RISK_CATEGORY_LABEL = "其他医学复核";

export const terminalDispositionLabels = {
  explained_no_external_action: "已说明，无需外部动作",
  data_correction: "已转数据更正",
  follow_up: "已转追加随访",
  pd_update: "已转PD补充/更新",
  safety_pv_collaboration: "已转Safety/PV协作",
  continue_observation: "持续观察",
  duplicate_not_applicable: "重复项/不适用",
};

export function severityLabel(severity) {
  return { critical: "紧急", high: "高", medium: "中", low: "低" }[severity] || severity;
}

export function riskStatusLabel(status) {
  return {
    action_required: "需行动",
    in_review: "复核中",
    triaged: "已分诊",
    new: "新识别",
    accepted_no_action: "接受不处理",
    resolved: "已解决",
    closed: "已关闭",
  }[status] || status;
}

export function monitoringAiReadiness(status = {}) {
  const configured = status?.configured === true;
  const ready = status?.semantic_ai_tasks_enabled === true;
  return {
    configured,
    ready,
    // Keep the backend readiness vocabulary on the normalized object so
    // downstream monitoring panels cannot confuse a generic role `ready`
    // flag with semantic-AI permission.
    semantic_ai_tasks_enabled: ready,
    label: ready ? "独立AI可运行" : configured ? "独立AI已配置但不可运行" : "独立AI待配置",
  };
}

export function monitoringFieldMappingCopy(status = {}) {
  const ready = status?.semantic_ai_tasks_enabled === true;
  return {
    ready,
    entryTitle: ready ? "建立本项目字段映射" : "准备本项目字段映射",
    entryDescription: ready
      ? "独立AI先识别语义字段，您只需校对关键差异并确认。"
      : "独立AI当前不可运行；确定性规则仅处理技术元数据，语义字段需配置后再识别。",
    entryAction: ready ? "AI识别并校对字段" : "打开字段映射工作区",
    headerDescription: ready
      ? "AI先完成全字段建议，您只需校对并确认。"
      : "独立AI当前不可运行；本次仅处理技术元数据，语义字段不会被自动判定。",
    startTitle: ready ? "自动识别全部数据域和字段" : "处理字段识别任务",
    startDescription: ready
      ? "系统会区分来源采集、技术元数据、编码字段、派生字段和暂不映射字段，并单列试验药物相关角色。"
      : "当前仅能处理技术元数据；来源采集、编码、派生和试验药物角色等语义字段不会被自动判定。",
    startAction: ready ? "AI识别字段" : "开始字段识别",
    progressDescription: ready
      ? "系统正在后台按数据域完成识别"
      : "确定性规则与已完成任务正在后台按数据域处理；语义字段需要独立AI",
    completedMessage: ready
      ? "AI字段建议已生成，可直接进入校对。"
      : "确定性技术字段映射已生成；本次未调用独立AI，请继续核对语义字段。",
    runningMessage: ready
      ? "独立AI正在按数据域识别字段；可关闭面板，任务会继续运行。"
      : "独立AI当前不可运行；仅技术元数据可由确定性规则处理，语义字段保持阻断。",
  };
}

export function riskDispositionStatusLabel(status) {
  return {
    pending_review: "待医学复核",
    reviewed: "已医学复核",
    query_draft: "Query草稿",
    submitted_for_approval: "已提交内部审批",
    explained_no_external_action: "已说明，无需外部动作",
    data_correction: "已转数据更正",
    follow_up: "已转追加随访",
    pd_update: "已转PD补充/更新",
    safety_pv_collaboration: "已转Safety/PV协作",
    continue_observation: "持续观察",
    duplicate_not_applicable: "重复项/不适用",
  }[status] || status || "待医学复核";
}

export function ruxDispositionStateFromStatus(status) {
  return {
    "待医学复核": "pending_review",
    "已医学复核": "reviewed",
    "Query草稿": "query_draft",
    "已提交审批": "submitted_for_approval",
    "已提交内部审批": "submitted_for_approval",
    "已说明，无需外部动作": "explained_no_external_action",
    "已转数据更正": "data_correction",
    "已转追加随访": "follow_up",
    "已转PD补充/更新": "pd_update",
    "已转Safety/PV协作": "safety_pv_collaboration",
    "持续观察": "continue_observation",
    "重复项/不适用": "duplicate_not_applicable",
  }[status] || "pending_review";
}

export function ruxDispositionStepTone(state, step) {
  const order = ["pending_review", "reviewed", "query_draft", "submitted_for_approval"];
  const stateIndex = order.indexOf(state);
  const stepIndex = order.indexOf(step);
  if (state === step) return "warning";
  if (stateIndex > stepIndex) return "success";
  return "neutral";
}

export function monitoringRiskCategoryLabel(value) {
  const label = String(value || "").trim();
  return label || UNKNOWN_RISK_CATEGORY_LABEL;
}

export function riskChecklistCategoryTags(risk = {}) {
  const primaryCategory = monitoringRiskCategoryLabel(
    risk.riskCategoryLabel || risk.risk_category_label,
  );
  const categories = [primaryCategory];
  if ((risk.safetyPvFlag ?? risk.safety_pv_flag) === true) {
    categories.push("Safety/PV");
  }
  return categories;
}

export function riskChecklistUpdatedDate(value) {
  const match = String(value || "").match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})/);
  if (!match) return "";
  return `${match[1]}-${match[2].padStart(2, "0")}-${match[3].padStart(2, "0")}`;
}

export function riskChecklistUpdatedSortValue(value) {
  const match = String(value || "").match(
    /^(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?:[ T](\d{1,2}):(\d{1,2}):(\d{1,2}))?/,
  );
  if (!match) return String(value || "");
  return `${match[1]}${match[2].padStart(2, "0")}${match[3].padStart(2, "0")}`
    + `${(match[4] || "0").padStart(2, "0")}${(match[5] || "0").padStart(2, "0")}`
    + `${(match[6] || "0").padStart(2, "0")}`;
}

function monitoringUpdatedAtLabel(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

function monitoringInboxSiteId(item = {}) {
  const explicitSite = [
    item.site_id,
    item.site,
    item.siteId,
    item.scope_type === "site" ? item.scope_id : "",
  ].find((value) => value !== null && value !== undefined && String(value).trim());
  if (explicitSite !== undefined) return String(explicitSite).trim();

  // Legacy workbench items sometimes only carry S<site><subject>. This is a
  // compatibility fallback, never the primary source of site identity.
  const targetId = String(item.target_id || "");
  const encodedSite = targetId.match(/^S(\d{2})/);
  return encodedSite ? encodedSite[1] : "-";
}

function explicitStringArray(value) {
  if (value === undefined || value === null) return { value: [], valid: true };
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !item.trim())) {
    return { value: [], valid: false };
  }
  return { value: value.map((item) => item.trim()), valid: true };
}

function explicitSourceRefs(value) {
  if (value === undefined || value === null) return { value: [], valid: true };
  if (!Array.isArray(value)) {
    return { value: [], valid: false };
  }
  const valid = value.every((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return false;
    return ["source_type", "locator", "label", "source_id"].every((field) => (
      !Object.prototype.hasOwnProperty.call(item, field)
      || (typeof item[field] === "string" && item[field].trim())
    ));
  });
  return valid ? { value, valid: true } : { value: [], valid: false };
}

function explicitIdentity(value) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

/**
 * UI-only key for a risk row. The source risk identity remains `riskId`/`id`;
 * the source index only prevents React from collapsing duplicate or partial
 * rows while the reviewer is inspecting the evidence.
 */
export function medicalMonitoringRiskDisplayKey(risk = {}, index = 0) {
  const identity = explicitIdentity(risk.riskId ?? risk.id ?? risk.risk_instance_id) || "missing";
  const sourceIndex = Number.isInteger(index) && index >= 0 ? index : 0;
  return `risk:${identity}:${sourceIndex}`;
}

function explicitTextState(value) {
  if (value === undefined || value === null) return { value: "", malformed: false };
  if (typeof value !== "string") return { value: "", malformed: true };
  return { value: value.trim(), malformed: false };
}

function sourceTokenShape(...states) {
  if (states.some((state) => state.malformed)) return "malformed";
  return states.some((state) => state.value) ? "valid" : "missing";
}

// Stable read-only projection consumed by both medical monitoring and Safety/PV.
export function monitoringRiskRowsFromInbox(workbenchInbox, displayBatch = "") {
  const items = Array.isArray(workbenchInbox?.items)
    ? workbenchInbox.items.filter((item) => item && typeof item === "object" && !Array.isArray(item))
    : [];
  return items
    .filter((item) => item.module === "medical_monitoring" && item.item_type === "risk")
    .map((item) => {
      const sourceRefs = explicitSourceRefs(item.source_refs);
      const sourceVersionState = explicitTextState(item.source_version);
      const displayBatchState = explicitTextState(displayBatch);
      const batchToken = displayBatchState.value || sourceVersionState.value.split(":")[0] || "";
      const sourceTokenState = sourceTokenShape(sourceVersionState, displayBatchState);
      return {
        id: item.item_id,
        riskId: item.risk_instance_id || item.source_id,
        riskKey: item.risk_key || item.source_id,
        snapshotId: item.snapshot_id || "",
        inboxItemId: item.item_id,
        title: item.title,
        subject: item.target_id || item.source_id || "-",
        site: monitoringInboxSiteId(item),
        type: typeof item.source_type === "string" && item.source_type.includes("monitoring_risk") ? "医学监查规则" : item.source_type,
        severity: item.priority,
        status: item.status,
        batch: batchToken || "-",
        owner: item.owner_role || "医学经理",
        source: [
          sourceRefs.value.some((ref) => ref.source_type === "protocol_rule") ? "方案条款定位" : "",
          sourceRefs.value.some((ref) => ref.source_type === "listing_data_row") ? "原始数据 listing 行" : "",
        ].filter(Boolean).join(" / ") || item.source_id,
        age: monitoringUpdatedAtLabel(item.updated_at),
        unread: item.unread,
        needsAction: item.needs_action,
        rationale: item.summary,
        recommendedAction: item.action_label || "进入医学复核",
        boundaryNote: item.boundary_note,
        sourceRefs: sourceRefs.value,
        sourceEvidenceShape: sourceRefs.valid ? "valid" : "malformed",
        sourceVersion: sourceVersionState.value,
        sourceTokenShape: sourceTokenState,
        dispositionState: ruxDispositionStateFromStatus(item.status),
        dispositionKind: item.disposition_kind || null,
        medicalJudgments: item.medical_judgments || null,
        riskCategoryCode: item.risk_category_code || "",
        riskCategoryLabel: item.risk_category_label || UNKNOWN_RISK_CATEGORY_LABEL,
        safetyPvFlag: item.safety_pv_flag === true,
        taxonomyVersion: item.taxonomy_version || "",
        updatedAt: item.updated_at || "",
      };
    })
    .filter((row) => explicitIdentity(row.id) && explicitIdentity(row.riskId) && explicitIdentity(row.riskKey))
    .sort((left, right) => {
      const severityRank = { critical: 0, high: 1, medium: 2, low: 3 };
      return (severityRank[left.severity] ?? 9) - (severityRank[right.severity] ?? 9)
        || String(left.subject).localeCompare(String(right.subject), "zh-CN", { numeric: true })
        || String(left.id).localeCompare(String(right.id));
    });
}

// Stable read-only projection consumed by both medical monitoring and Safety/PV.
export function riskIndexRowsFromApi(riskIndex, inboxRows = []) {
  const inboxByRiskId = new Map();
  const safeInboxRows = Array.isArray(inboxRows)
    ? inboxRows.filter((row) => row && typeof row === "object" && !Array.isArray(row))
    : [];
  safeInboxRows.forEach((row) => {
    [row.riskId, row.id].filter(Boolean).forEach((id) => inboxByRiskId.set(id, row));
  });
  const riskItems = Array.isArray(riskIndex?.items)
    ? riskIndex.items.filter((risk) => risk && typeof risk === "object" && !Array.isArray(risk))
    : [];
  const riskIdentityCounts = new Map();
  riskItems.forEach((risk) => {
    const riskId = explicitIdentity(risk.risk_instance_id)
      || (risk.risk_instance_id === undefined ? explicitIdentity(risk.risk_id) : "");
    if (riskId) riskIdentityCounts.set(riskId, (riskIdentityCounts.get(riskId) || 0) + 1);
  });
  return riskItems.map((risk, sourceIndex) => {
    const riskId = explicitIdentity(risk.risk_instance_id)
      || (risk.risk_instance_id === undefined ? explicitIdentity(risk.risk_id) : "");
    if (!riskId) return null;
    const riskKey = explicitIdentity(risk.risk_key)
      || (risk.risk_key === undefined ? explicitIdentity(risk.risk_id) : "");
    if (!riskKey) return null;
    const legacyInbox = inboxByRiskId.get(risk.risk_instance_id) || inboxByRiskId.get(risk.risk_id) || {};
    const workItem = risk.work_item || {};
    const sourceBatchState = explicitTextState(risk.source_batch_id);
    const sourceRevisionState = explicitTextState(risk.source_revision);
    const workItemSourceVersionState = explicitTextState(workItem.source_version);
    const legacySourceVersionState = explicitTextState(legacyInbox.sourceVersion);
    const sourceTokenState = sourceTokenShape(
      sourceBatchState,
      sourceRevisionState,
      workItemSourceVersionState,
      legacySourceVersionState,
      legacyInbox.sourceTokenShape === "malformed" ? { value: "", malformed: true } : { value: "", malformed: false },
    );
    const evidenceLocators = explicitStringArray(risk.evidence_span_ids);
    const riskTags = explicitStringArray(risk.tags);
    const workItemSourceRefs = explicitSourceRefs(workItem.source_refs);
    const inboxSourceRefs = explicitSourceRefs(legacyInbox.sourceRefs);
    const inbox = {
      ...legacyInbox,
      ...(workItem.item_id ? {
        id: workItem.item_id,
        inboxItemId: workItem.item_id,
        status: workItem.medical_disposition_status,
        unread: workItem.unread,
        needsAction: workItem.needs_action,
        recommendedAction: workItem.action_label,
        sourceVersion: workItemSourceVersionState.value,
        sourceRefs: workItemSourceRefs.value,
        sourceEvidenceShape: workItemSourceRefs.valid ? legacyInbox.sourceEvidenceShape || "valid" : "malformed",
        dispositionState: workItem.medical_disposition_state,
        dispositionKind: workItem.disposition_kind,
        medicalJudgments: workItem.medical_judgments,
        lastActionAt: workItem.last_action_at,
        queryWorkflowState: workItem.query_workflow_state,
      } : {}),
    };
    const createdAt = risk.created_at ? new Date(risk.created_at) : null;
    const updatedAt = risk.updated_at
      ? new Date(risk.updated_at)
      : inbox.lastActionAt
        ? new Date(inbox.lastActionAt)
        : createdAt;
    return {
      ...inbox,
      id: riskId,
      riskId,
      riskKey,
      sourceIndex,
      identityAmbiguous: (riskIdentityCounts.get(riskId) || 0) > 1,
      identityIssue: (riskIdentityCounts.get(riskId) || 0) > 1
        ? "risk_instance_id 重复；保留证据但暂不可定位"
        : "",
      title: risk.title,
      subject: risk.subject_id || "-",
      site: risk.site_id || "-",
      type: risk.primary_category || risk.risk_type,
      tags: riskTags.value,
      severity: risk.severity,
      status: riskDispositionStatusLabel(
        risk.disposition_status
        || inbox.dispositionState
        || inbox.status
        || risk.status,
      ),
      dispositionStatus: risk.disposition_status || inbox.dispositionState || "",
      batch: sourceBatchState.value.replace("batch_", "") || "-",
      batchDelta: risk.batch_delta,
      owner: risk.owner || inbox.owner || "医学经理",
      source: risk.rule_id,
      age: updatedAt && !Number.isNaN(updatedAt.getTime())
        ? updatedAt.toLocaleString("zh-CN", { hour12: false })
        : "-",
      detectedAt: risk.created_at || "",
      lastActionAt: inbox.lastActionAt || "",
      detectionStatus: risk.detection_status || risk.status,
      rationale: risk.rationale,
      recommendedAction: risk.recommended_action,
      scopeLabel: risk.scope_type === "trial"
        ? "整个试验"
        : risk.scope_type === "site"
          ? `中心 ${risk.scope_id || risk.site_id}`
          : `受试者 ${risk.scope_id || risk.subject_id}`,
      scopeType: risk.scope_type,
      scopeId: risk.scope_id,
      triggerWindow: sourceTokenState === "malformed"
        ? "来源绑定形状异常"
        : sourceBatchState.value || sourceRevisionState.value || "当前来源版本",
      sourceCompleteness: Math.round((risk.confidence ?? 1) * 100),
      sourceRevision: sourceRevisionState.value,
      sourceVersion: workItemSourceVersionState.value || legacySourceVersionState.value || sourceRevisionState.value,
      sourceTokenShape: sourceTokenState,
      sourceRefs: workItem.item_id ? workItemSourceRefs.value : inboxSourceRefs.value,
      sourceEvidenceShape: evidenceLocators.valid && workItemSourceRefs.valid && inboxSourceRefs.valid && inbox.sourceEvidenceShape !== "malformed" ? "valid" : "malformed",
      unread: inbox.unread,
      needsAction: inbox.needsAction,
      dispositionState: inbox.dispositionState,
      dispositionKind: inbox.dispositionKind,
      medicalJudgments: inbox.medicalJudgments,
      queryWorkflowState: inbox.queryWorkflowState,
      evidenceLocators: evidenceLocators.value,
      riskCategoryCode: risk.risk_category_code || "",
      riskCategoryLabel: risk.risk_category_label || UNKNOWN_RISK_CATEGORY_LABEL,
      safetyPvFlag: risk.safety_pv_flag === true,
      taxonomyVersion: risk.taxonomy_version || "",
      updatedAt: risk.updated_at || "",
    };
  }).filter(Boolean);
}

function explicitLineageToken(value) {
  if (typeof value !== "string") return "";
  const text = value.trim();
  return text && text !== "-" && text !== "未提供" ? text : "";
}

function explicitLineageTokenState(value) {
  if (value === undefined || value === null) return { value: "", malformed: false };
  if (typeof value !== "string") return { value: "", malformed: true };
  return { value: explicitLineageToken(value), malformed: false };
}

/**
 * Summarize only explicit source bindings already present on rendered risk rows.
 * This is a presentation guard: it never treats a batch number, title, or row order
 * as proof of freshness, completeness, or clinical validity.
 */
export function riskEvidenceLineageSummary(rows = []) {
  const safeRows = Array.isArray(rows)
    ? rows.filter((row) => row && typeof row === "object" && !Array.isArray(row))
    : [];
  const bindings = new Set();
  const revisionTokens = new Set();
  const batchTokens = new Set();
  let batchOnlyRows = 0;
  let missingBindingRows = 0;
  let malformedBindingRows = 0;
  safeRows.forEach((row) => {
    const sourceRevisionState = explicitLineageTokenState(row.sourceRevision ?? row.source_revision);
    const sourceVersionState = explicitLineageTokenState(row.sourceVersion ?? row.source_version);
    const sourceBatchState = explicitLineageTokenState(row.sourceBatchId ?? row.source_batch_id ?? row.batch);
    const sourceRevision = sourceRevisionState.value;
    const sourceVersion = sourceVersionState.value;
    const sourceBatch = sourceBatchState.value;
    if (row.sourceTokenShape === "malformed"
      || row.source_token_shape === "malformed"
      || sourceRevisionState.malformed
      || sourceVersionState.malformed
      || sourceBatchState.malformed) {
      malformedBindingRows += 1;
    }
    if (!sourceRevision && !sourceVersion && !sourceBatch) {
      missingBindingRows += 1;
      return;
    }
    if (!sourceRevision && !sourceVersion) batchOnlyRows += 1;
    bindings.add([sourceRevision, sourceVersion, sourceBatch].join("|"));
    if (sourceRevision) revisionTokens.add(sourceRevision);
    if (sourceBatch) batchTokens.add(sourceBatch);
  });
  const status = safeRows.length === 0
    ? "empty"
    : bindings.size === 0
      ? "unbound"
      : missingBindingRows > 0 || batchOnlyRows > 0 || malformedBindingRows > 0
        ? "partial"
        : bindings.size > 1
          ? "mixed"
          : "bound";
  return {
    totalRows: safeRows.length,
    boundRows: safeRows.length - missingBindingRows,
    strongBindingRows: safeRows.length - missingBindingRows - batchOnlyRows,
    batchOnlyRows,
    missingBindingRows,
    malformedBindingRows,
    bindingCount: bindings.size,
    revisionCount: revisionTokens.size,
    batchCount: batchTokens.size,
    status,
  };
}

export function riskEvidenceLineageMessage(summary) {
  if (!summary || summary.status === "empty") return "";
  if (summary.status === "bound") return "来源绑定完整；当前页使用 1 个明确来源修订/版本，不代表医学风险已确认关闭。";
  if (summary.status === "mixed") return `来源绑定混合（${summary.bindingCount} 个明确绑定）；请先核对快照/来源版本，再比较风险趋势。`;
  if (summary.status === "partial") {
    const details = [
      summary.batchOnlyRows ? `${summary.batchOnlyRows} 条仅有批次号` : "",
      summary.missingBindingRows ? `${summary.missingBindingRows} 条缺少来源绑定` : "",
      summary.malformedBindingRows ? `${summary.malformedBindingRows} 条来源绑定字段形状异常` : "",
    ].filter(Boolean).join("、");
    return `${details || "部分风险"}；批次号不足以证明来源修订或趋势可比，不能据此判断数据完整或无风险。`;
  }
  return "当前页风险没有可展示的来源修订/批次绑定；不能据此判断数据完整或无风险。";
}

/**
 * Keep per-row evidence status visible in the dense risk checklist. Only
 * explicit locator/reference arrays are accepted; the display never treats a
 * rule title or source label as evidence.
 */
export function riskRowEvidenceBadge(row = {}) {
  const locators = explicitStringArray(row.evidenceLocators ?? row.evidence_locators);
  const sourceRefs = explicitSourceRefs(row.sourceRefs ?? row.source_refs);
  if (!locators.valid || !sourceRefs.valid || row.sourceEvidenceShape === "malformed") {
    return { status: "malformed", label: "来源证据形状异常", count: 0 };
  }
  if (locators.value.length) {
    return { status: "bound", label: `证据定位 ${locators.value.length} 条`, count: locators.value.length };
  }
  if (sourceRefs.value.length) {
    return { status: "partial", label: `来源引用 ${sourceRefs.value.length} 条`, count: sourceRefs.value.length };
  }
  return { status: "missing", label: "来源证据缺失", count: 0 };
}

/**
 * Summarize the explicit evidence shape of the currently rendered page. The
 * summary is intentionally page-scoped: it never turns pagination into a
 * project-total claim and never treats a missing locator as no risk.
 */
export function riskEvidenceCoverageSummary(rows = []) {
  const safeRows = Array.isArray(rows)
    ? rows.filter((row) => row && typeof row === "object" && !Array.isArray(row))
    : [];
  const counts = {
    totalRows: safeRows.length,
    boundRows: 0,
    referenceOnlyRows: 0,
    missingRows: 0,
    malformedRows: 0,
    locatorCount: 0,
    referenceCount: 0,
  };
  safeRows.forEach((row) => {
    const badge = riskRowEvidenceBadge(row);
    if (badge.status === "bound") {
      counts.boundRows += 1;
      counts.locatorCount += badge.count;
    } else if (badge.status === "partial") {
      counts.referenceOnlyRows += 1;
      counts.referenceCount += badge.count;
    } else if (badge.status === "malformed") {
      counts.malformedRows += 1;
    } else {
      counts.missingRows += 1;
    }
  });
  const status = counts.totalRows === 0
    ? "empty"
    : counts.malformedRows > 0
      ? "malformed"
      : counts.boundRows === counts.totalRows
        ? "bound"
        : counts.boundRows > 0 || counts.referenceOnlyRows > 0
          ? "partial"
          : "missing";
  return { ...counts, status };
}

export function riskEvidenceCoverageMessage(summary) {
  if (!summary || summary.status === "empty") return "";
  const page = `当前页 ${summary.totalRows} 条风险：`;
  if (summary.status === "bound") {
    return `${page}证据定位完整（${summary.boundRows}/${summary.totalRows} 条）；定位存在不等于风险已关闭。`;
  }
  const details = [
    summary.boundRows ? `可定位 ${summary.boundRows}` : "",
    summary.referenceOnlyRows ? `仅来源引用 ${summary.referenceOnlyRows}` : "",
    summary.missingRows ? `缺失 ${summary.missingRows}` : "",
    summary.malformedRows ? `形状异常 ${summary.malformedRows}` : "",
  ].filter(Boolean).join(" · ");
  return `${page}${details || "证据状态待核对"}；缺失/异常不等于无风险。`;
}
