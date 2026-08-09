import assert from "node:assert/strict";
import {
  MEDICAL_MONITORING_MAX_SCROLL_TOP,
  medicalMonitoringScrollRestoreKey,
  normalizeMedicalMonitoringScrollTop,
} from "./medicalMonitoringScrollState.mjs";

assert.equal(normalizeMedicalMonitoringScrollTop(undefined), 0);
assert.equal(normalizeMedicalMonitoringScrollTop("0"), 0);
assert.equal(normalizeMedicalMonitoringScrollTop("-4"), 0);
assert.equal(normalizeMedicalMonitoringScrollTop("not-a-number"), 0);
assert.equal(normalizeMedicalMonitoringScrollTop("125.9"), 125);
assert.equal(
  normalizeMedicalMonitoringScrollTop(MEDICAL_MONITORING_MAX_SCROLL_TOP + 100),
  MEDICAL_MONITORING_MAX_SCROLL_TOP,
);
assert.equal(
  medicalMonitoringScrollRestoreKey({
    projectId: "proj-1",
    scope: "site",
    siteId: "C01",
    subjectId: "",
    querySignature: "risk-query-a",
  }),
  "proj-1|site|C01||risk-query-a",
);
assert.equal(
  medicalMonitoringScrollRestoreKey({ projectId: "proj-1", querySignature: "risk-query-a" }),
  "proj-1||||risk-query-a",
);
console.log("medicalMonitoringScrollState: 8 passed");
