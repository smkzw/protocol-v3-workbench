const PRINCIPAL_SCHEMA = "monitoring_runtime_principal_v1";
const SHA256_RE = /^[0-9a-f]{64}$/;
const PRINCIPAL_ROLES = new Set([
  "medical_monitor",
  "medical_manager",
  "medical_director",
  "medical_writer",
  "clinical_operations",
  "data_management",
  "pv",
  "statistics_programming",
  "system_admin",
  "product_engineering",
]);

export class MedicalMonitoringPrincipalShapeError extends Error {
  constructor(path, message) {
    super(`${path} ${message}`);
    this.name = "MedicalMonitoringPrincipalShapeError";
  }
}

function fail(path, message) {
  throw new MedicalMonitoringPrincipalShapeError(path, message);
}

function record(value, path) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(path, "must be an object");
  }
  return value;
}

function requiredText(value, path) {
  if (typeof value !== "string" || !value.trim()) {
    fail(path, "must be a non-empty string");
  }
  return value.trim();
}

function strictBoolean(value, path) {
  if (typeof value !== "boolean") fail(path, "must be a boolean");
  return value;
}

function textArray(value, path) {
  if (!Array.isArray(value) || value.length === 0) fail(path, "must be a non-empty array");
  const values = value.map((item, index) => requiredText(item, `${path}[${index}]`));
  if (new Set(values).size !== values.length) fail(path, "must contain unique values");
  return values;
}

function digest(value, path) {
  if (typeof value !== "string" || !SHA256_RE.test(value)) {
    fail(path, "must be an exact lowercase SHA-256 digest");
  }
  return value;
}

function timestamp(value, path) {
  const text = requiredText(value, path);
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) fail(path, "must be an ISO-8601 timestamp");
  return { text, date: parsed };
}

function nowDate(value) {
  if (value === undefined) return new Date();
  const parsed = value instanceof Date ? new Date(value.getTime()) : new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    throw new TypeError("now must be a valid Date or ISO-8601 timestamp");
  }
  return parsed;
}

export function normalizeMonitoringPrincipal(
  raw,
  { projectId = "", path = "monitoring_principal", now } = {},
) {
  const source = record(raw, path);
  const schemaVersion = requiredText(source.schema_version, `${path}.schema_version`);
  if (schemaVersion !== PRINCIPAL_SCHEMA) fail(`${path}.schema_version`, `has unsupported value ${schemaVersion}`);
  if (source.server_verified !== true) fail(`${path}.server_verified`, "must be true");

  const principalId = requiredText(source.principal_id, `${path}.principal_id`);
  const tenantId = requiredText(source.tenant_id, `${path}.tenant_id`);
  const authenticated = strictBoolean(source.authenticated, `${path}.authenticated`);
  const authnMethod = requiredText(source.authn_method, `${path}.authn_method`);
  const directoryRevision = requiredText(source.directory_revision, `${path}.directory_revision`);
  const issuedAt = timestamp(source.issued_at, `${path}.issued_at`);
  const expiresAt = timestamp(source.expires_at, `${path}.expires_at`);
  if (expiresAt.date <= issuedAt.date) fail(`${path}.expires_at`, "must be later than issued_at");
  const sessionIdSha256 = digest(source.session_id_sha256, `${path}.session_id_sha256`);
  const verificationRefSha256 = digest(source.verification_ref_sha256, `${path}.verification_ref_sha256`);
  const roles = textArray(source.roles, `${path}.roles`);
  const unsupportedRole = roles.find((role) => !PRINCIPAL_ROLES.has(role));
  if (unsupportedRole) fail(`${path}.roles`, `contains unsupported role ${unsupportedRole}`);
  const projectScope = textArray(source.project_scope, `${path}.project_scope`);
  if (projectScope.includes("*")) fail(`${path}.project_scope`, "must not contain a wildcard");
  const expectedProjectId = projectId ? requiredText(projectId, "project_id") : "";
  if (expectedProjectId && !projectScope.includes(expectedProjectId)) {
    fail(`${path}.project_scope`, "does not include the active project");
  }
  const identityHash = source.identity_hash === undefined
    ? ""
    : digest(source.identity_hash, `${path}.identity_hash`);
  const current = nowDate(now);
  let validity = "active";
  if (!authenticated) validity = "not_authenticated";
  else if (current < issuedAt.date) validity = "not_yet_valid";
  else if (current >= expiresAt.date) validity = "expired";

  return {
    schemaVersion,
    serverVerified: true,
    principalId,
    tenantId,
    roles,
    projectScope,
    issuedAt: issuedAt.text,
    expiresAt: expiresAt.text,
    authenticated,
    authnMethod,
    sessionIdSha256,
    directoryRevision,
    verificationRefSha256,
    authnContext: typeof source.authn_context === "string" ? source.authn_context.trim() : "",
    assurance: typeof source.assurance === "string" ? source.assurance.trim() : "",
    identityHash,
    validity,
    validNow: validity === "active",
  };
}

export function monitoringPrincipalReady(principal, { projectId = "", now } = {}) {
  if (!principal || typeof principal !== "object") return false;
  const expectedProjectId = projectId ? String(projectId).trim() : "";
  if (!principal.serverVerified || !principal.authenticated || validityAt(principal, now) !== "active") return false;
  if (expectedProjectId && !principal.projectScope?.includes(expectedProjectId)) return false;
  return true;
}

function validityAt(principal, now) {
  if (!principal?.authenticated) return "not_authenticated";
  const issuedAt = new Date(principal.issuedAt).getTime();
  const expiresAt = new Date(principal.expiresAt).getTime();
  if (!Number.isFinite(issuedAt) || !Number.isFinite(expiresAt)) return "invalid_window";
  const current = nowDate(now).getTime();
  if (current < issuedAt) return "not_yet_valid";
  if (current >= expiresAt) return "expired";
  return "active";
}

export function monitoringPrincipalStatusLabel(principal, { now } = {}) {
  if (!principal) return "未接入";
  const validity = validityAt(principal, now);
  if (validity === "active") return principal.principalId;
  if (validity === "expired") return "认证已过期";
  if (validity === "not_yet_valid") return "认证尚未生效";
  if (validity === "invalid_window") return "认证时间无效";
  return "未认证";
}

export function monitoringPrincipalBlocker(principal, error = "", { now } = {}) {
  if (error) return error;
  if (!principal) return "未返回服务端认证 principal；仅有 authority 不能创建保障任务。";
  const validity = validityAt(principal, now);
  if (validity === "expired") return "服务端认证 principal 已过期；请重新登录后再创建保障任务。";
  if (validity === "not_yet_valid") return "服务端认证 principal 尚未生效；当前不允许创建保障任务。";
  if (validity === "not_authenticated") return "当前会话未通过服务端认证；仅有 authority 不能创建保障任务。";
  if (validity === "invalid_window") return "服务端认证 principal 时间窗口无效；当前不允许创建保障任务。";
  return "服务端认证 principal 未覆盖当前项目；当前不允许创建保障任务。";
}

export { PRINCIPAL_ROLES, PRINCIPAL_SCHEMA };
