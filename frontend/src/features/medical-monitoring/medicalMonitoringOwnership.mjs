export const FRONTEND_OWNERSHIP_SCHEMA = "frontend.ownership.v1";

export const FRONTEND_OWNERS = Object.freeze({
  MEDICAL_MONITORING: "medical_monitoring",
  MEDICAL_WRITING: "medical_writing",
  SHARED_SHELL: "shared_shell",
  UNCLASSIFIED: "unclassified",
});

export const FRONTEND_MOUNT_POINTS = Object.freeze([
  Object.freeze({
    key: "medical_monitoring",
    owner: FRONTEND_OWNERS.MEDICAL_MONITORING,
    feature_root: "frontend/src/features/medical-monitoring/",
    import_tokens: Object.freeze(["./features/medical-monitoring/"]),
    route_tokens: Object.freeze(["MedicalMonitoring", "medical-monitoring"]),
  }),
  Object.freeze({
    key: "medical_writing",
    owner: FRONTEND_OWNERS.MEDICAL_WRITING,
    feature_root: "frontend/src/features/medical-writing/",
    import_tokens: Object.freeze([
      "./features/medical-writing/",
      "./features/writing-reference/",
    ]),
    route_tokens: Object.freeze(["MedicalWriting", "medical-writing"]),
  }),
]);

const SHARED_SHELL_PATHS = new Set([
  "frontend/index.html",
  "frontend/package.json",
  "frontend/package-lock.json",
  "frontend/pnpm-lock.yaml",
  "frontend/pnpm-workspace.yaml",
  "frontend/vite.config.mjs",
  "frontend/src/App.jsx",
  "frontend/src/main.jsx",
  "frontend/src/styles.css",
  "frontend/src/runtimeReadiness.js",
]);

const OWNERSHIP_RULES = Object.freeze([
  Object.freeze({
    owner: FRONTEND_OWNERS.MEDICAL_MONITORING,
    area: "medical_monitoring_feature",
    prefix: "frontend/src/features/medical-monitoring/",
    write_policy: "owned_write",
  }),
  Object.freeze({
    owner: FRONTEND_OWNERS.MEDICAL_WRITING,
    area: "medical_writing_feature",
    prefix: "frontend/src/features/medical-writing/",
    write_policy: "protected_from_monitoring",
  }),
  Object.freeze({
    owner: FRONTEND_OWNERS.MEDICAL_WRITING,
    area: "writing_reference_feature",
    prefix: "frontend/src/features/writing-reference/",
    write_policy: "protected_from_monitoring",
  }),
]);

export class FrontendOwnershipError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "FrontendOwnershipError";
    this.code = code;
    this.details = details;
  }
}

function isAbsoluteOrProtocolPath(value) {
  return value.startsWith("/")
    || value.startsWith("\\\\")
    || /^[A-Za-z]:[\\/]/.test(value)
    || /^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(value);
}

export function normalizeFrontendPath(value) {
  if (typeof value !== "string" || !value.trim()) {
    throw new FrontendOwnershipError(
      "invalid_path",
      "Frontend ownership paths must be non-empty strings.",
      { value },
    );
  }
  const raw = value.trim().replaceAll("\\", "/");
  if (isAbsoluteOrProtocolPath(raw)) {
    throw new FrontendOwnershipError(
      "absolute_path_forbidden",
      "Frontend ownership contracts accept repository-relative paths only.",
      { value },
    );
  }
  const segments = raw.split("/");
  if (segments.some((segment) => segment === "..")) {
    throw new FrontendOwnershipError(
      "path_traversal_forbidden",
      "Frontend ownership paths may not traverse outside the repository root.",
      { value },
    );
  }
  const normalized = segments.filter((segment) => segment && segment !== ".").join("/");
  if (!normalized) {
    throw new FrontendOwnershipError(
      "invalid_path",
      "Frontend ownership paths must resolve to a file path.",
      { value },
    );
  }
  return normalized;
}

function pathIsWithin(path, prefix) {
  return path === prefix.slice(0, -1) || path.startsWith(prefix);
}

export function classifyFrontendPath(value) {
  const path = normalizeFrontendPath(value);
  const featureRule = OWNERSHIP_RULES.find((rule) => pathIsWithin(path, rule.prefix));
  if (featureRule) {
    return Object.freeze({
      path,
      owner: featureRule.owner,
      area: featureRule.area,
      write_policy: featureRule.write_policy,
      requires_manifest: false,
      protected: featureRule.owner === FRONTEND_OWNERS.MEDICAL_WRITING,
    });
  }
  if (SHARED_SHELL_PATHS.has(path)) {
    return Object.freeze({
      path,
      owner: FRONTEND_OWNERS.SHARED_SHELL,
      area: "shared_frontend_shell",
      write_policy: "explicit_manifest_and_dual_review",
      requires_manifest: true,
      protected: true,
    });
  }
  return Object.freeze({
    path,
    owner: FRONTEND_OWNERS.UNCLASSIFIED,
    area: "unclassified_frontend_path",
    write_policy: "register_before_write",
    requires_manifest: true,
    protected: true,
  });
}

function assertKnownOwner(owner) {
  if (!Object.values(FRONTEND_OWNERS).includes(owner)
    || owner === FRONTEND_OWNERS.SHARED_SHELL
    || owner === FRONTEND_OWNERS.UNCLASSIFIED) {
    throw new FrontendOwnershipError(
      "invalid_claim_owner",
      "Only a feature owner may claim a frontend write set.",
      { owner },
    );
  }
}

function normalizeExplicitSharedPaths(paths) {
  return new Set((paths || []).map(normalizeFrontendPath));
}

export function assertFrontendOwnership(paths, {
  owner,
  explicit_shared_paths = [],
  shared_review_ref = "",
} = {}) {
  assertKnownOwner(owner);
  const sharedPaths = normalizeExplicitSharedPaths(explicit_shared_paths);
  const entries = (paths || []).map(classifyFrontendPath);
  const sharedEntries = entries.filter((entry) => entry.owner === FRONTEND_OWNERS.SHARED_SHELL);
  const violations = entries.filter((entry) => {
    if (entry.owner === owner) return false;
    if (entry.owner === FRONTEND_OWNERS.SHARED_SHELL) {
      return !sharedPaths.has(entry.path);
    }
    return true;
  });
  if (violations.length) {
    throw new FrontendOwnershipError(
      "ownership_boundary_violation",
      "The proposed frontend write set crosses a protected or unregistered ownership boundary.",
      { owner, violations },
    );
  }
  if (sharedEntries.length && !String(shared_review_ref || "").trim()) {
    throw new FrontendOwnershipError(
      "shared_review_required",
      "A shared-shell write set requires a path-bound dual-review reference.",
      { owner, shared_entries: sharedEntries },
    );
  }
  return Object.freeze({
    owner,
    entries: Object.freeze(entries),
    shared_paths: Object.freeze([...sharedPaths].sort()),
    shared_review_ref: String(shared_review_ref || "").trim(),
  });
}

export function buildFrontendOwnershipManifest({
  session_id,
  owner,
  expected_completion,
  paths = [],
  explicit_shared_paths = [],
  shared_review_ref = "",
} = {}) {
  if (typeof session_id !== "string" || !session_id.trim()) {
    throw new FrontendOwnershipError("invalid_session", "A frontend ownership session id is required.");
  }
  if (typeof expected_completion !== "string" || !expected_completion.trim()) {
    throw new FrontendOwnershipError("invalid_completion", "An expected completion point is required.");
  }
  const checked = assertFrontendOwnership(paths, { owner, explicit_shared_paths, shared_review_ref });
  return Object.freeze({
    schema_version: FRONTEND_OWNERSHIP_SCHEMA,
    session_id: session_id.trim(),
    owner,
    expected_completion: expected_completion.trim(),
    files: Object.freeze([...checked.entries].sort((left, right) => left.path.localeCompare(right.path))),
    explicit_shared_paths: checked.shared_paths,
    shared_review_ref: checked.shared_review_ref,
  });
}

function countTokenOccurrences(source, token) {
  let count = 0;
  let cursor = 0;
  while (cursor < source.length) {
    const index = source.indexOf(token, cursor);
    if (index < 0) break;
    count += 1;
    cursor = index + token.length;
  }
  return count;
}

export function inspectFrontendMountPoints(sourceText) {
  if (typeof sourceText !== "string") {
    throw new FrontendOwnershipError("invalid_mount_source", "Mount inspection requires source text.");
  }
  const mounts = FRONTEND_MOUNT_POINTS.map((mount) => {
    const import_count = mount.import_tokens.reduce(
      (total, token) => total + countTokenOccurrences(sourceText, token),
      0,
    );
    const route_token_hits = mount.route_tokens.filter((token) => sourceText.includes(token));
    return Object.freeze({
      key: mount.key,
      owner: mount.owner,
      feature_root: mount.feature_root,
      import_count,
      import_present: import_count > 0,
      route_token_hits: Object.freeze(route_token_hits),
      route_present: route_token_hits.length === mount.route_tokens.length,
      mounted: import_count > 0 && route_token_hits.length === mount.route_tokens.length,
    });
  });
  return Object.freeze({
    schema_version: FRONTEND_OWNERSHIP_SCHEMA,
    mounts: Object.freeze(mounts),
    mounted: mounts.every((mount) => mount.mounted),
  });
}

export function assertFrontendMountPoints(sourceText) {
  const report = inspectFrontendMountPoints(sourceText);
  const missing = report.mounts.filter((mount) => !mount.mounted);
  if (missing.length) {
    throw new FrontendOwnershipError(
      "mount_point_missing",
      "The shared frontend shell must visibly mount every declared subsystem feature root.",
      { missing, report },
    );
  }
  return report;
}

export const FRONTEND_OWNERSHIP_RULES = Object.freeze(OWNERSHIP_RULES.map((rule) => Object.freeze({ ...rule })));
export const FRONTEND_SHARED_SHELL_PATHS = Object.freeze([...SHARED_SHELL_PATHS].sort());
