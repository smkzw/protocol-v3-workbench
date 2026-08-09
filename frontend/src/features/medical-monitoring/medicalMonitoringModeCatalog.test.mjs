import assert from "node:assert/strict";
import {
  MONITORING_MODE_IDS,
  monitoringModeDefinition,
  monitoringModeForDailyRun,
  monitoringModeFromAssuranceMode,
  monitoringModeLabel,
  monitoringModeShortLabel,
} from "./medicalMonitoringModeCatalog.mjs";

assert.deepEqual(MONITORING_MODE_IDS, [
  "daily_incremental",
  "pre_lock_total",
  "post_lock_fixed_total",
]);

for (const modeId of MONITORING_MODE_IDS) {
  const definition = monitoringModeDefinition(modeId);
  assert.ok(definition, `${modeId} has a definition`);
  assert.equal(monitoringModeLabel(modeId), definition.label);
  assert.equal(monitoringModeShortLabel(modeId), definition.shortLabel);
  assert.ok(definition.source);
  assert.ok(definition.baseline);
  assert.ok(definition.completion);
}

assert.equal(monitoringModeForDailyRun().id, "daily_incremental");
assert.equal(monitoringModeFromAssuranceMode("pre_lock"), "pre_lock_total");
assert.equal(monitoringModeFromAssuranceMode("pre_inspection"), "post_lock_fixed_total");
assert.equal(monitoringModeFromAssuranceMode("unknown"), "");

console.log("medicalMonitoringModeCatalog: 18 passed");
