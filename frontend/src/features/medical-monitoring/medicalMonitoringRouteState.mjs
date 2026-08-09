export const MEDICAL_MONITORING_SCOPES = Object.freeze(["trial", "site", "subject"]);
export const MEDICAL_MONITORING_VIEWS = Object.freeze([
  "checklist",
  "timeline",
  "profile",
  "ae-mh",
  "evidence",
]);

export const MEDICAL_MONITORING_EVIDENCE_TABS = Object.freeze([
  "disposition",
  "timeline",
  "profile",
  "ae_mh",
  "sources",
  "history",
]);

export const MEDICAL_MONITORING_CHECKLIST_SORT_FIELDS = Object.freeze([
  "subject_id",
  "site_id",
  "severity",
  "risk_category_code",
  "risk_item",
  "disposition_status",
  "updated_at",
]);

export const MEDICAL_MONITORING_ROUTE_KEYS = Object.freeze([
  "project_id",
  "scope",
  "site_id",
  "subject_id",
  "risk_key",
  "risk_instance_id",
  "view",
  "protocol_version_id",
  "batch_id",
  "evidence_tab",
  "filter_subject_id",
  "filter_site_id",
  "filter_severity",
  "filter_risk_category_code",
  "filter_risk_item",
  "filter_disposition_status",
  "filter_updated_at",
  "risk_sort_by",
  "risk_sort_direction",
  "risk_page",
  "risk_page_size",
  "risk_scroll_top",
  "risk_snapshot_id",
]);

export const MEDICAL_MONITORING_RISK_FOCUS_KEYS = Object.freeze([
  "risk_key",
  "risk_instance_id",
  "evidence_tab",
]);

const SCOPE_SET = new Set(MEDICAL_MONITORING_SCOPES);
const VIEW_SET = new Set(MEDICAL_MONITORING_VIEWS);
const EVIDENCE_TAB_SET = new Set(MEDICAL_MONITORING_EVIDENCE_TABS);
const CHECKLIST_SORT_SET = new Set(MEDICAL_MONITORING_CHECKLIST_SORT_FIELDS);
const SEVERITY_SET = new Set(["critical", "high", "medium", "low"]);
const SORT_DIRECTION_SET = new Set(["asc", "desc"]);

function routeParams(input) {
  if (input instanceof URLSearchParams) return new URLSearchParams(input);
  if (input instanceof URL) return new URLSearchParams(input.searchParams);
  if (input && typeof input === "object" && typeof input.search === "string") {
    return new URLSearchParams(input.search);
  }
  const raw = typeof input === "string" ? input.trim() : "";
  if (!raw) return new URLSearchParams();
  if (/^[a-z][a-z\d+.-]*:\/\//i.test(raw)) {
    return new URL(raw).searchParams;
  }
  return new URLSearchParams(raw.startsWith("?") ? raw.slice(1) : raw);
}

function cleanValue(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

function projectIdFromCandidate(candidate) {
  if (typeof candidate === "string") return cleanValue(candidate);
  if (!candidate || typeof candidate !== "object") return "";
  return cleanValue(candidate.project_id);
}

/**
 * Resolve a risk deep link only against records already scoped to the current
 * project.  An absent match is explicit so the UI can explain the boundary
 * instead of silently opening a different risk.
 */
export function resolveMedicalMonitoringRiskRoute(
  requestedRiskId,
  visibleRiskRows = [],
  fetchedRiskRows = [],
) {
  const requested = cleanValue(requestedRiskId);
  if (!requested) return Object.freeze({ status: "none", risk: null, requestedRiskId: "" });
  const candidates = [
    ...(Array.isArray(visibleRiskRows) ? visibleRiskRows : []),
    ...(Array.isArray(fetchedRiskRows) ? fetchedRiskRows : []),
  ];
  const risk = candidates.find((candidate) => (
    [candidate?.id, candidate?.risk_instance_id, candidate?.risk_key, candidate?.riskKey]
      .map(cleanValue)
      .includes(requested)
  )) || null;
  return Object.freeze({
    status: risk ? "matched" : "unavailable",
    risk,
    requestedRiskId: requested,
  });
}

/**
 * Resolve a monitoring deep-link project without ever substituting a
 * different project for an explicitly requested one.  The result is pure so
 * App-level hydration can fail closed before any project-scoped read starts.
 */
export function resolveMedicalMonitoringProjectRoute(
  requestedProjectId,
  projects = [],
  currentProjectId = "",
  fallbackProjectId = "",
) {
  const requested = cleanValue(requestedProjectId);
  const available = [];
  const seen = new Set();
  (Array.isArray(projects) ? projects : []).forEach((candidate) => {
    const projectId = projectIdFromCandidate(candidate);
    if (projectId && !seen.has(projectId)) {
      seen.add(projectId);
      available.push(projectId);
    }
  });
  if (requested) {
    return Object.freeze({
      status: available.includes(requested) ? "matched" : "unavailable",
      projectId: available.includes(requested) ? requested : "",
      requestedProjectId: requested,
    });
  }
  const current = cleanValue(currentProjectId);
  if (current && available.includes(current)) {
    return Object.freeze({ status: "current", projectId: current, requestedProjectId: "" });
  }
  const fallback = cleanValue(fallbackProjectId);
  if (fallback && available.includes(fallback)) {
    return Object.freeze({ status: "fallback", projectId: fallback, requestedProjectId: "" });
  }
  return Object.freeze({
    status: available.length ? "default" : "empty",
    projectId: available[0] || "",
    requestedProjectId: "",
  });
}

function subjectIdFromCandidate(candidate) {
  if (typeof candidate === "string") return cleanValue(candidate);
  if (!candidate || typeof candidate !== "object") return "";
  return cleanValue(candidate.id ?? candidate.subject_id);
}

/**
 * Resolve a subject deep link against the current project's subject catalog.
 * An explicit non-member is unavailable rather than silently replaced by the
 * first subject in the catalog.
 */
export function resolveMedicalMonitoringSubjectRoute(
  requestedSubjectId,
  subjects = [],
  currentSubjectId = "",
  fallbackSubjectId = "",
) {
  const requested = cleanValue(requestedSubjectId);
  const available = [];
  const seen = new Set();
  (Array.isArray(subjects) ? subjects : []).forEach((candidate) => {
    const subjectId = subjectIdFromCandidate(candidate);
    if (subjectId && !seen.has(subjectId)) {
      seen.add(subjectId);
      available.push(subjectId);
    }
  });
  if (requested) {
    return Object.freeze({
      status: available.includes(requested) ? "matched" : "unavailable",
      subjectId: available.includes(requested) ? requested : "",
      requestedSubjectId: requested,
    });
  }
  const current = cleanValue(currentSubjectId);
  if (current && available.includes(current)) {
    return Object.freeze({ status: "current", subjectId: current, requestedSubjectId: "" });
  }
  const fallback = cleanValue(fallbackSubjectId);
  if (fallback && available.includes(fallback)) {
    return Object.freeze({ status: "fallback", subjectId: fallback, requestedSubjectId: "" });
  }
  return Object.freeze({
    status: available.length ? "default" : "empty",
    subjectId: available[0] || "",
    requestedSubjectId: "",
  });
}

function siteIdFromCandidate(candidate) {
  if (!candidate || typeof candidate !== "object") return "";
  return cleanValue(candidate.site_id ?? candidate.site ?? candidate.scope_id);
}

/**
 * Resolve a site deep link against the current project's subject catalog and
 * risk rollups.  Empty candidate lists remain pending so an unready read is
 * not misreported as a missing center.
 */
export function resolveMedicalMonitoringSiteRoute(
  requestedSiteId,
  subjects = [],
  riskRollups = [],
) {
  const requested = cleanValue(requestedSiteId);
  if (!requested) return Object.freeze({ status: "none", siteId: "", requestedSiteId: "" });
  const candidates = [
    ...(Array.isArray(subjects) ? subjects : []),
    ...(Array.isArray(riskRollups) ? riskRollups : []),
  ].map(siteIdFromCandidate).filter(Boolean);
  const unique = [...new Set(candidates)];
  if (unique.includes(requested)) {
    return Object.freeze({ status: "matched", siteId: requested, requestedSiteId: requested });
  }
  return Object.freeze({
    status: unique.length ? "unavailable" : "pending",
    siteId: "",
    requestedSiteId: requested,
  });
}

function setWhenPresent(target, key, value) {
  const clean = cleanValue(value);
  if (clean) target[key] = clean;
}

export function normalizeMedicalMonitoringRouteState(input = {}) {
  const source = input && typeof input === "object" ? input : {};
  const normalized = {};

  setWhenPresent(normalized, "project_id", source.project_id);
  setWhenPresent(normalized, "site_id", source.site_id);
  setWhenPresent(normalized, "subject_id", source.subject_id);
  setWhenPresent(normalized, "risk_key", source.risk_key);
  setWhenPresent(normalized, "risk_instance_id", source.risk_instance_id);
  setWhenPresent(normalized, "protocol_version_id", source.protocol_version_id);
  setWhenPresent(normalized, "batch_id", source.batch_id);
  setWhenPresent(normalized, "filter_subject_id", source.filter_subject_id);
  setWhenPresent(normalized, "filter_site_id", source.filter_site_id);
  setWhenPresent(normalized, "filter_risk_category_code", source.filter_risk_category_code);
  setWhenPresent(normalized, "filter_risk_item", source.filter_risk_item);
  setWhenPresent(normalized, "filter_disposition_status", source.filter_disposition_status);
  setWhenPresent(normalized, "filter_updated_at", source.filter_updated_at);
  setWhenPresent(normalized, "risk_snapshot_id", source.risk_snapshot_id);

  const severity = cleanValue(source.filter_severity).toLowerCase();
  if (SEVERITY_SET.has(severity)) normalized.filter_severity = severity;

  const evidenceTab = cleanValue(source.evidence_tab).toLowerCase();
  if (EVIDENCE_TAB_SET.has(evidenceTab)) normalized.evidence_tab = evidenceTab;

  const sortBy = cleanValue(source.risk_sort_by).toLowerCase();
  if (CHECKLIST_SORT_SET.has(sortBy)) normalized.risk_sort_by = sortBy;
  const sortDirection = cleanValue(source.risk_sort_direction).toLowerCase();
  if (SORT_DIRECTION_SET.has(sortDirection)) {
    normalized.risk_sort_direction = sortDirection;
  }

  const page = Number.parseInt(cleanValue(source.risk_page), 10);
  if (Number.isInteger(page) && page > 1) normalized.risk_page = String(page);
  const pageSize = Number.parseInt(cleanValue(source.risk_page_size), 10);
  if (Number.isInteger(pageSize) && pageSize >= 1 && pageSize <= 200 && pageSize !== 50) {
    normalized.risk_page_size = String(pageSize);
  }
  const scrollTop = Number.parseInt(cleanValue(source.risk_scroll_top), 10);
  if (Number.isInteger(scrollTop) && scrollTop >= 1 && scrollTop <= 1_000_000) {
    normalized.risk_scroll_top = String(scrollTop);
  }

  const requestedScope = cleanValue(source.scope).toLowerCase();
  const requestedView = cleanValue(source.view).toLowerCase();
  const hasValidScope = SCOPE_SET.has(requestedScope);
  const hasValidView = VIEW_SET.has(requestedView);
  const hasFocus = Object.keys(normalized).length > 0 || hasValidScope || hasValidView;
  let scope = hasValidScope ? requestedScope : "";
  if (!scope && hasFocus) {
    scope = normalized.subject_id ? "subject" : normalized.site_id ? "site" : "trial";
  }

  if (scope === "trial") {
    delete normalized.site_id;
    delete normalized.subject_id;
  } else if (scope === "site") {
    delete normalized.subject_id;
    if (!normalized.site_id) scope = "trial";
  } else if (scope === "subject" && !normalized.subject_id) {
    scope = normalized.site_id ? "site" : "trial";
  }
  if (scope) normalized.scope = scope;

  let view = hasValidView ? requestedView : "";
  if (["timeline", "profile"].includes(view) && !normalized.subject_id) {
    view = "checklist";
  }
  if (
    view === "evidence"
    && !normalized.risk_key
    && !normalized.risk_instance_id
  ) {
    view = "checklist";
  }
  if (view) normalized.view = view;

  return normalized;
}

export function parseMedicalMonitoringRouteState(search = "") {
  const params = routeParams(search);
  const candidate = {};
  MEDICAL_MONITORING_ROUTE_KEYS.forEach((key) => {
    if (params.has(key)) candidate[key] = params.get(key);
  });
  return normalizeMedicalMonitoringRouteState(candidate);
}

function replaceMonitoringParams(params, state) {
  MEDICAL_MONITORING_ROUTE_KEYS.forEach((key) => params.delete(key));
  const normalized = normalizeMedicalMonitoringRouteState(state);
  MEDICAL_MONITORING_ROUTE_KEYS.forEach((key) => {
    if (normalized[key]) params.set(key, normalized[key]);
  });
  return params;
}

export function serializeMedicalMonitoringRouteState(state, baseSearch = "") {
  const params = replaceMonitoringParams(routeParams(baseSearch), state);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function mergeMedicalMonitoringRouteState(search, patch = {}) {
  const current = parseMedicalMonitoringRouteState(search);
  return serializeMedicalMonitoringRouteState(
    { ...current, ...(patch || {}) },
    search,
  );
}

export function clearMedicalMonitoringRiskFocusState(input = {}) {
  const next = { ...normalizeMedicalMonitoringRouteState(input) };
  MEDICAL_MONITORING_RISK_FOCUS_KEYS.forEach((key) => delete next[key]);
  return normalizeMedicalMonitoringRouteState(next);
}

export function clearMedicalMonitoringRouteState(search = "") {
  const params = routeParams(search);
  MEDICAL_MONITORING_ROUTE_KEYS.forEach((key) => params.delete(key));
  const query = params.toString();
  return query ? `?${query}` : "";
}
