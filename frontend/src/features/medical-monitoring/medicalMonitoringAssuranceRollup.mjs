const LEVEL_KEYS = Object.freeze(["trial", "site", "subject"]);

function nonNegativeInteger(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return null;
  if (typeof value === "string" && !value.trim()) return null;
  const number = Number(value);
  return Number.isInteger(number) && number >= 0 ? number : null;
}

function text(value, fallback = "") {
  const result = String(value ?? "").trim();
  return result || fallback;
}

function sortedUnique(values) {
  return [...new Set(values.map((value) => text(value)).filter(Boolean))].sort();
}

function idSetFromRows(rows) {
  return sortedUnique(
    rows.flatMap((row) => {
      if (Array.isArray(row?.riskInstanceIds)) return row.riskInstanceIds;
      return Array.isArray(row?.risk_instance_ids) ? row.risk_instance_ids : [];
    }),
  );
}

function sameValues(left, right) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function distributionEntries(distribution) {
  if (!distribution || typeof distribution !== "object" || Array.isArray(distribution)) return [];
  return Object.entries(distribution)
    .map(([label, value]) => ({ label: text(label, "未分类"), value: nonNegativeInteger(value) }))
    .filter((entry) => entry.value !== null)
    .sort((left, right) => right.value - left.value || left.label.localeCompare(right.label));
}

function normalizeSite(row) {
  const identity = text(row?.site_id);
  return {
    siteId: identity || "未标识中心",
    identityState: identity ? "ready" : "missing",
    identityIssue: identity ? "" : "中心缺少 site_id；仅可读，暂不可下钻",
    totalRiskCount: nonNegativeInteger(row?.total_risk_count),
    openRiskCount: nonNegativeInteger(row?.open_risk_count),
    openHighRiskCount: nonNegativeInteger(row?.open_high_risk_count),
    riskInstanceIds: sortedUnique(Array.isArray(row?.risk_instance_ids) ? row.risk_instance_ids : []),
    cluster: row?.cluster && typeof row.cluster === "object" ? row.cluster : null,
  };
}

function normalizeSubject(row) {
  const identity = text(row?.subject_id);
  return {
    subjectId: identity || "未标识受试者",
    identityState: identity ? "ready" : "missing",
    identityIssue: identity ? "" : "个例缺少 subject_id；仅可读，暂不可下钻",
    siteId: text(row?.site_id, "未标识中心"),
    totalRiskCount: nonNegativeInteger(row?.total_risk_count),
    openRiskCount: nonNegativeInteger(row?.open_risk_count),
    riskInstanceIds: sortedUnique(Array.isArray(row?.risk_instance_ids) ? row.risk_instance_ids : []),
  };
}

function normalizeRows(rows, normalize, identityField) {
  const normalized = (Array.isArray(rows) ? rows : [])
    .map((row, sourceIndex) => ({ ...normalize(row), displaySourceIndex: sourceIndex }));
  const identityCounts = new Map();
  normalized.forEach((row) => {
    if (row.identityState !== "ready") return;
    const identity = row[identityField];
    identityCounts.set(identity, (identityCounts.get(identity) || 0) + 1);
  });
  return normalized.map((row) => {
    if (row.identityState !== "ready" || (identityCounts.get(row[identityField]) || 0) <= 1) return row;
    return {
      ...row,
      identityState: "duplicate",
      identityIssue: `${identityField === "siteId" ? "中心" : "个例"}身份重复；仅可读，暂不可下钻`,
    };
  })
    .sort((left, right) => (
      (right.openHighRiskCount ?? -1) - (left.openHighRiskCount ?? -1)
      || (right.openRiskCount ?? -1) - (left.openRiskCount ?? -1)
      || (right.totalRiskCount ?? -1) - (left.totalRiskCount ?? -1)
      || left.siteId?.localeCompare(right.siteId || "")
      || left.subjectId?.localeCompare(right.subjectId || "")
    ));
}

/**
 * Turn the backend's reference-only pre-inspection rollup into a compact UI model.
 * It never invents risk facts or severity; every displayed count is copied from an
 * explicit rollup field and the conservation result is fail-closed on malformed IDs.
 */
export function projectAssuranceRollup(rollup = null) {
  const payload = rollup && typeof rollup === "object" && !Array.isArray(rollup) ? rollup : {};
  const trialPayload = payload.trial_rollup && typeof payload.trial_rollup === "object"
    ? payload.trial_rollup
    : {};
  const sites = normalizeRows(payload.site_rollup, normalizeSite, "siteId");
  const subjects = normalizeRows(payload.subject_rollup, normalizeSubject, "subjectId");
  const trialRiskIds = sortedUnique(
    Array.isArray(trialPayload.risk_instance_ids) ? trialPayload.risk_instance_ids : [],
  );
  const siteRiskIds = idSetFromRows(sites);
  const subjectRiskIds = idSetFromRows(subjects);
  const expectedTotal = nonNegativeInteger(trialPayload.total_risk_count);
  const conservation = {
    riskInstanceIdsMatch: trialRiskIds.length > 0 || expectedTotal === 0
      ? sameValues(trialRiskIds, siteRiskIds) && sameValues(trialRiskIds, subjectRiskIds)
      : false,
    trialCountMatches: expectedTotal !== null && expectedTotal === trialRiskIds.length,
    subjectCountMatches: subjects.every((row) => (
      row.totalRiskCount !== null && row.totalRiskCount === row.riskInstanceIds.length
    )),
    siteCountMatches: sites.every((row) => (
      row.totalRiskCount !== null && row.totalRiskCount === row.riskInstanceIds.length
    )),
  };
  conservation.ok = Object.values(conservation).every(Boolean);

  const distributions = payload.distributions && typeof payload.distributions === "object"
    ? payload.distributions
    : {};
  const trial = {
    totalRiskCount: expectedTotal,
    openRiskCount: nonNegativeInteger(trialPayload.open_risk_count),
    openHighRiskCount: nonNegativeInteger(trialPayload.open_high_risk_count),
    closedRiskCount: nonNegativeInteger(trialPayload.closed_risk_count),
    closedWithoutEvidenceCount: nonNegativeInteger(trialPayload.closed_risks_lacking_evidence_count),
    safetyPvRiskCount: nonNegativeInteger(trialPayload.safety_pv_risk_count),
    concomitantMedicationRiskCount: nonNegativeInteger(trialPayload.concomitant_medication_risk_count),
    studyTreatmentRiskCount: nonNegativeInteger(trialPayload.study_treatment_risk_count),
  };

  return {
    available: Boolean(rollup && typeof rollup === "object"),
    riskSnapshotId: text(payload.risk_snapshot_id),
    trial,
    sites,
    subjects,
    distributions: {
      severity: distributionEntries(distributions.by_severity),
      status: distributionEntries(distributions.by_status),
      disposition: distributionEntries(distributions.by_disposition),
    },
    evidenceCount: Array.isArray(payload.evidence_manifest) ? payload.evidence_manifest.length : 0,
    remediationCount: Array.isArray(payload.remediation_matrix) ? payload.remediation_matrix.length : 0,
    conservation,
  };
}

/**
 * UI-only key for an assurance rollup row. It keeps malformed/duplicate rows
 * visible without turning the source index into a scope or subject identity.
 */
export function assuranceRollupRowDisplayKey(row = {}, level = "row", index = 0) {
  const identity = level === "subject" ? text(row.subjectId) : text(row.siteId);
  const sourceIndex = Number.isInteger(row.displaySourceIndex) && row.displaySourceIndex >= 0
    ? row.displaySourceIndex
    : Number.isInteger(index) && index >= 0 ? index : 0;
  return `assurance:${level}:${identity || "missing"}:${sourceIndex}`;
}

export function assuranceRollupLevelKeys() {
  return [...LEVEL_KEYS];
}

export function assuranceRollupNumber(value, fallback = "—") {
  const number = nonNegativeInteger(value);
  return number === null ? fallback : String(number);
}
