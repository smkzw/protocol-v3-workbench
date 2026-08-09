import {
  monitoringRiskCategoryLabel,
  riskDispositionStatusLabel,
  riskStatusLabel,
  severityLabel,
} from "./medicalMonitoringModels.mjs";

const severityRank = { critical: 0, high: 1, medium: 2, low: 3 };

export class MedicalRiskProjectionError extends Error {}

function required(value, field) {
  if (typeof value !== "string") {
    throw new MedicalRiskProjectionError(`${field} must be a string`);
  }
  const text = value.trim();
  if (!text) throw new MedicalRiskProjectionError(`${field} is required`);
  return text;
}

function optionalText(value, field) {
  if (value === undefined || value === null || value === "") return "";
  if (typeof value !== "string") {
    throw new MedicalRiskProjectionError(`${field} must be a string`);
  }
  return value.trim();
}

function orderedUnique(values = [], field = "value") {
  if (values === undefined || values === null) return [];
  if (!Array.isArray(values)) {
    throw new MedicalRiskProjectionError(`${field} must be a string array`);
  }
  if (values.some((value) => typeof value !== "string" || !value.trim())) {
    throw new MedicalRiskProjectionError(`${field} must contain non-empty strings`);
  }
  return [...new Set(values.map((value) => value.trim()))]
    .sort((left, right) => left.localeCompare(right, "zh-CN", { numeric: true }));
}

function optionalNonNegativeInteger(value, field) {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new MedicalRiskProjectionError(`${field} must be a non-negative integer`);
  }
  return value;
}

function scopeIdentity(row) {
  const scopeType = required(row.scope_type ?? row.scopeType, "scope_type");
  const scopeId = required(row.scope_id ?? row.scopeId, "scope_id");
  const siteId = optionalText(row.site_id ?? row.siteId, "site_id");
  const subjectId = optionalText(row.subject_id ?? row.subjectId, "subject_id");
  if (!["trial", "site", "subject"].includes(scopeType)) {
    throw new MedicalRiskProjectionError(`unsupported scope_type: ${scopeType}`);
  }
  const trialId = optionalText(row.trial_id ?? row.trialId, "trial_id");
  if (scopeType === "trial" && (scopeId !== trialId || siteId || subjectId)) {
    throw new MedicalRiskProjectionError("trial scope identity is inconsistent");
  }
  if (scopeType === "site" && (scopeId !== siteId || subjectId)) {
    throw new MedicalRiskProjectionError("site scope identity is inconsistent");
  }
  if (scopeType === "subject" && (!siteId || scopeId !== subjectId)) {
    throw new MedicalRiskProjectionError("subject scope identity is incomplete");
  }
  return { scopeType, scopeId, siteId, subjectId };
}

function linkedViews(row) {
  const hasSnakeCase = Object.prototype.hasOwnProperty.call(row, "linked_views");
  const hasCamelCase = Object.prototype.hasOwnProperty.call(row, "linkedViews");
  const suppliedLinks = hasSnakeCase ? row.linked_views : hasCamelCase ? row.linkedViews : undefined;
  const links = suppliedLinks === undefined || suppliedLinks === null ? {} : suppliedLinks;
  if (!links || typeof links !== "object" || Array.isArray(links)) {
    throw new MedicalRiskProjectionError("linked_views must be an object");
  }
  return Object.fromEntries([
    ["timelineEventIds", links.timeline_event_ids ?? links.timelineEventIds],
    ["profileFieldIds", links.profile_field_ids ?? links.profileFieldIds],
    ["aeEventIds", links.ae_event_ids ?? links.aeEventIds],
    ["labEventIds", links.lab_event_ids ?? links.labEventIds],
    ["vitalsEventIds", links.vitals_event_ids ?? links.vitalsEventIds],
    ["ecgEventIds", links.ecg_event_ids ?? links.ecgEventIds],
    ["pdEventIds", links.pd_event_ids ?? links.pdEventIds],
  ].map(([key, value]) => [key, orderedUnique(value, `linked_views.${key}`)]));
}

function normalizeCanonicalRisk(row) {
  const riskInstanceId = required(row.risk_instance_id ?? row.riskInstanceId, "risk_instance_id");
  const projectId = required(row.project_id ?? row.projectId, "project_id");
  const trialId = required(row.trial_id ?? row.trialId, "trial_id");
  const identity = scopeIdentity({ ...row, trial_id: trialId });
  const findingClass = required(row.finding_class ?? row.findingClass, "finding_class");
  const categoryValue = row.category ?? row.risk_category_label ?? row.riskCategoryLabel;
  const category = monitoringRiskCategoryLabel(optionalText(categoryValue, "category"));
  const severity = required(row.severity, "severity");
  const status = required(row.status, "status");
  const dispositionState = optionalText(row.disposition_state ?? row.dispositionState, "disposition_state") || "pending_review";
  const sourceRevision = required(row.source_revision ?? row.sourceRevision, "source_revision");
  const ruleId = required(row.rule_id ?? row.ruleId, "rule_id");
  const title = required(row.title, "title");
  const evidenceIds = orderedUnique(row.evidence_ids ?? row.evidenceIds, "evidence_ids");
  const locators = orderedUnique(row.evidence_locators ?? row.evidenceLocators ?? row.source_locators, "evidence_locators");
  if (row.unread !== undefined && typeof row.unread !== "boolean") {
    throw new MedicalRiskProjectionError("unread must be a boolean");
  }
  const needsActionValue = row.needs_action ?? row.needsAction;
  if (needsActionValue !== undefined && typeof needsActionValue !== "boolean") {
    throw new MedicalRiskProjectionError("needs_action must be a boolean");
  }
  const unreadProvided = row.unread !== undefined;
  const needsActionProvided = needsActionValue !== undefined;
  const unread = row.unread === true;
  const needsAction = needsActionValue === true;
  const aggregateVersion = optionalNonNegativeInteger(
    row.aggregate_version ?? row.aggregateVersion,
    "aggregate_version",
  );
  return {
    riskInstanceId,
    riskKey: required(row.risk_key ?? row.riskKey, "risk_key"),
    projectId,
    trialId,
    scopeType: identity.scopeType,
    scopeId: identity.scopeId,
    siteId: identity.siteId,
    subjectId: identity.subjectId,
    category,
    findingClass,
    severity,
    severityLabel: severityLabel(severity),
    detectionStatus: status,
    detectionStatusLabel: riskStatusLabel(status),
    dispositionState,
    dispositionLabel: riskDispositionStatusLabel(dispositionState),
    unread,
    needsAction,
    title,
    rationale: optionalText(row.rationale, "rationale"),
    recommendedAction: optionalText(row.recommended_action ?? row.recommendedAction, "recommended_action"),
    queryDraftText: optionalText(row.query_draft_text ?? row.queryDraftText, "query_draft_text"),
    workflowFieldPresence: { unread: unreadProvided, needsAction: needsActionProvided },
    evidence: {
      sourceRevision,
      ruleProfileRevision: optionalText(row.rule_profile_revision ?? row.ruleProfileRevision, "rule_profile_revision"),
      engineVersion: optionalText(row.engine_version ?? row.engineVersion, "engine_version"),
      ruleId,
      evidenceIds,
      locators,
    },
    linkedViews: linkedViews(row),
    aggregateVersion,
    updatedAt: optionalText(row.updated_at ?? row.updatedAt, "updated_at"),
  };
}

function canonicalIdentity(row) {
  return JSON.stringify({
    riskInstanceId: row.riskInstanceId,
    projectId: row.projectId,
    trialId: row.trialId,
    scopeType: row.scopeType,
    scopeId: row.scopeId,
    siteId: row.siteId,
    subjectId: row.subjectId,
  });
}

function sortRiskRows(rows) {
  return [...rows].sort((left, right) => (
    (severityRank[left.severity] ?? 9) - (severityRank[right.severity] ?? 9)
    || String(left.siteId).localeCompare(String(right.siteId), "zh-CN", { numeric: true })
    || String(left.subjectId).localeCompare(String(right.subjectId), "zh-CN", { numeric: true })
    || left.riskInstanceId.localeCompare(right.riskInstanceId, "zh-CN", { numeric: true })
  ));
}

function countBy(rows, field) {
  return Object.fromEntries(
    [...rows.reduce((counts, row) => {
      const value = String(row[field] || "");
      counts.set(value, (counts.get(value) || 0) + 1);
      return counts;
    }, new Map()).entries()]
      .sort(([left], [right]) => left.localeCompare(right, "zh-CN", { numeric: true })),
  );
}

function rollup(rows) {
  const sorted = sortRiskRows(rows);
  return {
    riskCount: sorted.length,
    riskInstanceIds: sorted.map((row) => row.riskInstanceId),
    unreadCount: sorted.filter((row) => row.unread).length,
    needsActionCount: sorted.filter((row) => row.needsAction).length,
    severityCounts: countBy(sorted, "severity"),
    findingClassCounts: countBy(sorted, "findingClass"),
    dispositionCounts: countBy(sorted, "dispositionState"),
    categoryCounts: countBy(sorted, "category"),
    scopeCounts: countBy(sorted, "scopeType"),
    evidenceCoverage: evidenceCoverage(sorted),
    linkedViewCoverage: linkedViewCoverage(sorted),
  };
}

/**
 * Summarize only explicit evidence fields already normalized on canonical rows.
 * A reference ID is not promoted to a locator: both counts stay visible so a
 * reviewer can distinguish “can open the source” from “has an evidence ID”.
 */
function evidenceCoverage(rows) {
  const riskCount = rows.length;
  const locatorRiskCount = rows.filter((row) => row.evidence.locators.length > 0).length;
  const evidenceIdRiskCount = rows.filter((row) => row.evidence.evidenceIds.length > 0).length;
  const missingRiskCount = rows.filter(
    (row) => row.evidence.locators.length === 0 && row.evidence.evidenceIds.length === 0,
  ).length;
  const locatorCount = rows.reduce((total, row) => total + row.evidence.locators.length, 0);
  const evidenceIdCount = rows.reduce((total, row) => total + row.evidence.evidenceIds.length, 0);
  const status = riskCount === 0
    ? "empty"
    : locatorRiskCount === riskCount
      ? "bound"
      : locatorRiskCount > 0 || evidenceIdRiskCount > 0
        ? "partial"
        : "missing";
  return {
    status,
    riskCount,
    locatorRiskCount,
    evidenceIdRiskCount,
    missingRiskCount,
    locatorCount,
    evidenceIdCount,
  };
}

/**
 * Keep drill-through availability separate from source evidence coverage. A
 * linked view helps navigation, but it is not itself proof of source binding.
 */
function linkedViewCoverage(rows) {
  const linkValues = (row) => Object.values(row.linkedViews).flat();
  return {
    riskCount: rows.length,
    linkedRiskCount: rows.filter((row) => linkValues(row).length > 0).length,
    linkedReferenceCount: rows.reduce((total, row) => total + linkValues(row).length, 0),
  };
}

function groupRows(rows, field) {
  const groups = new Map();
  rows.forEach((row) => {
    const key = row[field];
    if (!key) return;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  return [...groups.entries()]
    .sort(([left], [right]) => String(left).localeCompare(String(right), "zh-CN", { numeric: true }))
    .map(([id, groupedRows]) => ({ id, ...rollup(groupedRows), rows: sortRiskRows(groupedRows) }));
}

/**
 * Normalize canonical authority rows and derive deterministic drilldown projections.
 * This is a read-only view model; it never writes or infers clinical meaning.
 */
export function projectCanonicalMedicalRisks(rows = []) {
  const byRiskInstance = new Map();
  rows.forEach((raw) => {
    const row = normalizeCanonicalRisk(raw);
    const previous = byRiskInstance.get(row.riskInstanceId);
    if (previous && (
      canonicalIdentity(previous) !== canonicalIdentity(row)
      || JSON.stringify(previous) !== JSON.stringify(row)
    )) {
      throw new MedicalRiskProjectionError(`risk_instance_id identity conflict: ${row.riskInstanceId}`);
    }
    if (!previous) byRiskInstance.set(row.riskInstanceId, row);
  });
  const normalized = sortRiskRows([...byRiskInstance.values()]);
  if (normalized.some((row) => row.projectId !== normalized[0]?.projectId || row.trialId !== normalized[0]?.trialId)) {
    throw new MedicalRiskProjectionError("projection cannot mix project or trial identities");
  }
  const projectRows = normalized;
  const sites = groupRows(normalized.filter((row) => row.siteId), "siteId");
  const subjects = groupRows(normalized.filter((row) => row.subjectId), "subjectId");
  const project = {
    ...rollup(projectRows),
    projectId: normalized[0]?.projectId || "",
    trialId: normalized[0]?.trialId || "",
    sites,
    unassignedRiskInstanceIds: normalized.filter((row) => !row.siteId).map((row) => row.riskInstanceId),
  };
  const siteAssignedRiskCount = sites.reduce((total, site) => total + site.riskCount, 0);
  const unassignedRiskCount = project.unassignedRiskInstanceIds.length;
  const sitePartitionRiskCount = siteAssignedRiskCount + unassignedRiskCount;
  const subjectScopedRiskCount = normalized.filter((row) => row.scopeType === "subject").length;
  const subjectProjectionRiskCount = subjects.reduce((total, subject) => total + subject.riskCount, 0);
  const hasRows = normalized.length > 0;
  const limitations = [];
  if (!normalized.length) limitations.push("empty_risk_set");
  if (normalized.some((row) => !row.workflowFieldPresence.needsAction)) {
    limitations.push("needs_action_not_explicitly_provided");
  }
  return {
    projectionStatus: normalized.length ? "ready" : "empty",
    limitations,
    project,
    sites,
    subjects,
    rows: normalized,
    scopeConservation: {
      projectRiskCount: normalized.length,
      siteAssignedRiskCount,
      unassignedRiskCount,
      sitePartitionRiskCount,
      sitePartitionStatus: !hasRows
        ? "empty"
        : sitePartitionRiskCount === normalized.length ? "conserved" : "not_conserved",
      subjectScopedRiskCount,
      subjectProjectionRiskCount,
      subjectProjectionStatus: !hasRows
        ? "empty"
        : subjectProjectionRiskCount === subjectScopedRiskCount ? "conserved" : "not_conserved",
    },
    progressiveDisclosure: {
      defaultVisible: ["title", "severity", "detectionStatus", "dispositionState", "scopeType", "scopeId"],
      evidenceFields: ["sourceRevision", "ruleProfileRevision", "engineVersion", "ruleId", "evidenceIds", "locators"],
      linkedViewFields: ["timelineEventIds", "profileFieldIds", "aeEventIds", "labEventIds", "vitalsEventIds", "ecgEventIds", "pdEventIds"],
    },
  };
}
