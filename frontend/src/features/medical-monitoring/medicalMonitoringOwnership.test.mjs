import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  FRONTEND_OWNERS,
  FRONTEND_OWNERSHIP_SCHEMA,
  assertFrontendMountPoints,
  assertFrontendOwnership,
  buildFrontendOwnershipManifest,
  classifyFrontendPath,
  FrontendOwnershipError,
  inspectFrontendMountPoints,
  normalizeFrontendPath,
} from "./medicalMonitoringOwnership.mjs";

const WORKBENCH_ROOT = new URL("../../../../", import.meta.url);
const APP_SOURCE = readFileSync(new URL("../../../src/App.jsx", import.meta.url), "utf8");

assert.equal(normalizeFrontendPath("./frontend\\src\\features\\medical-monitoring\\Panel.jsx"), "frontend/src/features/medical-monitoring/Panel.jsx");
const absolutePath = ["", "tmp", "workbench", "frontend", "src", "App.jsx"].join("/");
assert.throws(
  () => normalizeFrontendPath(absolutePath),
  (error) => error instanceof FrontendOwnershipError && error.code === "absolute_path_forbidden",
);
assert.throws(
  () => normalizeFrontendPath("frontend/src/../App.jsx"),
  (error) => error instanceof FrontendOwnershipError && error.code === "path_traversal_forbidden",
);

assert.deepEqual(
  classifyFrontendPath("frontend/src/features/medical-monitoring/MedicalMonitoringBatchPanel.jsx"),
  {
    path: "frontend/src/features/medical-monitoring/MedicalMonitoringBatchPanel.jsx",
    owner: FRONTEND_OWNERS.MEDICAL_MONITORING,
    area: "medical_monitoring_feature",
    write_policy: "owned_write",
    requires_manifest: false,
    protected: false,
  },
);
assert.equal(classifyFrontendPath("frontend/src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx").owner, FRONTEND_OWNERS.MEDICAL_WRITING);
assert.equal(classifyFrontendPath("frontend/src/features/writing-reference/WritingReferencePanel.jsx").owner, FRONTEND_OWNERS.MEDICAL_WRITING);
assert.equal(classifyFrontendPath("frontend/src/App.jsx").owner, FRONTEND_OWNERS.SHARED_SHELL);
assert.equal(classifyFrontendPath("frontend/src/unknown/Panel.jsx").owner, FRONTEND_OWNERS.UNCLASSIFIED);

assert.doesNotThrow(() => assertFrontendOwnership([
  "frontend/src/features/medical-monitoring/medicalMonitoringOwnership.mjs",
], { owner: FRONTEND_OWNERS.MEDICAL_MONITORING }));
assert.throws(
  () => assertFrontendOwnership([
    "frontend/src/features/medical-monitoring/Panel.jsx",
    "frontend/src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx",
  ], { owner: FRONTEND_OWNERS.MEDICAL_MONITORING }),
  (error) => error instanceof FrontendOwnershipError
    && error.code === "ownership_boundary_violation"
    && error.details.violations.some((item) => item.owner === FRONTEND_OWNERS.MEDICAL_WRITING),
);
assert.throws(
  () => assertFrontendOwnership(["frontend/src/App.jsx"], { owner: FRONTEND_OWNERS.MEDICAL_MONITORING }),
  (error) => error instanceof FrontendOwnershipError && error.code === "ownership_boundary_violation",
);
assert.throws(
  () => assertFrontendOwnership(
    ["frontend/src/App.jsx"],
    {
      owner: FRONTEND_OWNERS.MEDICAL_MONITORING,
      explicit_shared_paths: ["frontend/src/App.jsx"],
    },
  ),
  (error) => error instanceof FrontendOwnershipError && error.code === "shared_review_required",
);
assert.doesNotThrow(() => assertFrontendOwnership(
  ["frontend/src/App.jsx"],
  {
    owner: FRONTEND_OWNERS.MEDICAL_MONITORING,
    explicit_shared_paths: ["frontend/src/App.jsx"],
    shared_review_ref: "review:shared-shell-dual-review-20260806",
  },
));
assert.throws(
  () => assertFrontendOwnership(["frontend/src/unknown/Panel.jsx"], { owner: FRONTEND_OWNERS.MEDICAL_MONITORING }),
  (error) => error instanceof FrontendOwnershipError && error.code === "ownership_boundary_violation",
);

const manifest = buildFrontendOwnershipManifest({
  session_id: "medical_monitoring_frontend_ownership_contract_20260806",
  owner: FRONTEND_OWNERS.MEDICAL_MONITORING,
  expected_completion: "contract tests and static mount audit complete",
  paths: [
    "frontend/src/features/medical-monitoring/medicalMonitoringOwnership.test.mjs",
    "frontend/src/features/medical-monitoring/medicalMonitoringOwnership.mjs",
  ],
});
assert.equal(manifest.schema_version, FRONTEND_OWNERSHIP_SCHEMA);
assert.deepEqual(manifest.files.map((item) => item.path), [
  "frontend/src/features/medical-monitoring/medicalMonitoringOwnership.mjs",
  "frontend/src/features/medical-monitoring/medicalMonitoringOwnership.test.mjs",
]);

const mountReport = inspectFrontendMountPoints(APP_SOURCE);
assert.equal(mountReport.mounted, true);
assert.deepEqual(mountReport.mounts.map((mount) => mount.key), ["medical_monitoring", "medical_writing"]);
assert.ok(mountReport.mounts.every((mount) => mount.import_present && mount.route_present));
assert.deepEqual(assertFrontendMountPoints(APP_SOURCE), mountReport);
assert.equal(WORKBENCH_ROOT.protocol, "file:");
