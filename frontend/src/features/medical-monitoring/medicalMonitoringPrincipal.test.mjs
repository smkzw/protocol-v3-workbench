import assert from "node:assert/strict";
import {
  MedicalMonitoringPrincipalShapeError,
  monitoringPrincipalBlocker,
  monitoringPrincipalReady,
  monitoringPrincipalStatusLabel,
  normalizeMonitoringPrincipal,
} from "./medicalMonitoringPrincipal.mjs";

const PROJECT = "proj_rux_03_002";
const NOW = "2026-08-03T07:00:00Z";
const SHA = "a".repeat(64);

function claims(overrides = {}) {
  return {
    server_verified: true,
    schema_version: "monitoring_runtime_principal_v1",
    principal_id: "user-001",
    tenant_id: "tenant-kangzhe",
    roles: ["medical_manager"],
    project_scope: [PROJECT],
    issued_at: "2026-08-03T06:55:00Z",
    expires_at: "2026-08-03T08:00:00Z",
    authenticated: true,
    authn_method: "local-session",
    session_id_sha256: SHA,
    directory_revision: "directory-v1",
    verification_ref_sha256: SHA,
    assurance: "directory-verified",
    ...overrides,
  };
}

const principal = normalizeMonitoringPrincipal(claims(), { projectId: PROJECT, now: NOW });
assert.equal(principal.principalId, "user-001");
assert.equal(principal.tenantId, "tenant-kangzhe");
assert.equal(principal.validNow, true);
assert.equal(monitoringPrincipalReady(principal, { projectId: PROJECT, now: NOW }), true);
assert.equal(monitoringPrincipalStatusLabel(principal, { now: NOW }), "user-001");
assert.equal(principal.sessionIdSha256, SHA);

assert.throws(
  () => normalizeMonitoringPrincipal(claims({ server_verified: false }), { projectId: PROJECT, now: NOW }),
  MedicalMonitoringPrincipalShapeError,
);
assert.throws(
  () => normalizeMonitoringPrincipal(claims({ project_scope: ["other-project"] }), { projectId: PROJECT, now: NOW }),
  /does not include the active project/,
);
assert.throws(
  () => normalizeMonitoringPrincipal(claims({ project_scope: ["*"] }), { projectId: PROJECT, now: NOW }),
  /must not contain a wildcard/,
);
assert.throws(
  () => normalizeMonitoringPrincipal(claims({ roles: ["medical_manager", "medical_manager"] }), { projectId: PROJECT, now: NOW }),
  /must contain unique values/,
);
assert.throws(
  () => normalizeMonitoringPrincipal(claims({ session_id_sha256: "raw-session" }), { projectId: PROJECT, now: NOW }),
  /exact lowercase SHA-256 digest/,
);
assert.throws(
  () => normalizeMonitoringPrincipal(claims({ session_id_sha256: SHA.toUpperCase() }), { projectId: PROJECT, now: NOW }),
  /exact lowercase SHA-256 digest/,
);
assert.throws(
  () => normalizeMonitoringPrincipal(claims({ verification_ref_sha256: ` ${SHA}` }), { projectId: PROJECT, now: NOW }),
  /exact lowercase SHA-256 digest/,
);

const expired = normalizeMonitoringPrincipal(
  claims({ expires_at: "2026-08-03T06:59:59Z" }),
  { projectId: PROJECT, now: NOW },
);
assert.equal(expired.validNow, false);
assert.equal(monitoringPrincipalReady(expired, { projectId: PROJECT, now: NOW }), false);
assert.equal(monitoringPrincipalStatusLabel(expired, { now: NOW }), "认证已过期");
assert.match(monitoringPrincipalBlocker(expired, "", { now: NOW }), /已过期/);
assert.match(monitoringPrincipalBlocker(null), /未返回服务端认证 principal/);

console.log("medicalMonitoringPrincipal: 17 passed");
