export const MEDICAL_MONITORING_MAX_SCROLL_TOP = 1_000_000;

export function normalizeMedicalMonitoringScrollTop(value) {
  const numeric = typeof value === "number"
    ? value
    : Number.parseInt(String(value ?? "").trim(), 10);
  if (!Number.isFinite(numeric) || numeric < 1) return 0;
  return Math.min(Math.floor(numeric), MEDICAL_MONITORING_MAX_SCROLL_TOP);
}

export function medicalMonitoringScrollRestoreKey({
  projectId = "",
  scope = "",
  siteId = "",
  subjectId = "",
  querySignature = "",
}) {
  return [
    projectId,
    scope,
    siteId,
    subjectId,
    querySignature,
  ].map((value) => String(value ?? "").trim()).join("|");
}
