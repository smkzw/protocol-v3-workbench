import assert from "node:assert/strict";

import {
  monitoringSourceImplementationStatuses,
  monitoringSourceReadiness,
} from "./medicalMonitoringSourceReadiness.mjs";

const active = monitoringSourceReadiness({
  implementation_status: monitoringSourceImplementationStatuses.ACTIVE,
});
assert.equal(active.kind, "active");
assert.equal(active.canRead, true);
assert.equal(active.canStart, true);

const sourceOnly = monitoringSourceReadiness({
  implementation_status: monitoringSourceImplementationStatuses.SOURCE_ONLY,
});
assert.equal(sourceOnly.kind, "source_only");
assert.equal(sourceOnly.canRead, false);
assert.equal(sourceOnly.canStart, false);
assert.match(sourceOnly.message, /尚未完成结构解析/);

for (const status of ["demo_available", "legacy_available"]) {
  const state = monitoringSourceReadiness({ implementation_status: status });
  assert.equal(state.kind, "active");
  assert.equal(state.canRead, true);
  assert.equal(state.canStart, true);
}

for (const binding of [null, {}, { implementation_status: "planned" }, { implementation_status: "" }]) {
  const state = monitoringSourceReadiness(binding);
  assert.equal(state.kind, "unconfirmed");
  assert.equal(state.canRead, false);
  assert.equal(state.canStart, false);
}

console.log("medicalMonitoringSourceReadiness: 25 passed");
