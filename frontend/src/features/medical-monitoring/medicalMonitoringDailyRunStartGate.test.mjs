import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  canStartMonitoringDailyRun,
  monitoringDailyRunRemediation,
} from "./medicalMonitoringDailyRunStartGate.mjs";

assert.equal(
  canStartMonitoringDailyRun({ ready: true, next_action: "start_daily_run" }),
  true,
);
assert.equal(
  canStartMonitoringDailyRun({ ready: false, next_action: "start_daily_run" }),
  false,
);
assert.deepEqual(
  monitoringDailyRunRemediation({
    ready: false,
    next_action: "confirm_mapping",
  }),
  { key: "mapping", label: "校对字段映射" },
);
assert.deepEqual(
  monitoringDailyRunRemediation({
    ready: false,
    next_action: "prepare_rule_pack",
  }),
  { key: "rule_pack", label: "准备医学规则" },
);
assert.equal(
  monitoringDailyRunRemediation({
    ready: false,
    next_action: "configure_ai",
  }),
  null,
);

const directory = path.dirname(fileURLToPath(import.meta.url));
const apiSource = fs.readFileSync(path.join(directory, "medicalMonitoringApi.mjs"), "utf8");
const appSource = fs.readFileSync(path.join(directory, "../../App.jsx"), "utf8");
assert.equal(
  apiSource.includes("/modules/medical-monitoring/runs"),
  false,
  "API client must not expose the legacy monitoring run command",
);
assert.equal(
  appSource.includes("runRegisteredMonitoringSources"),
  false,
  "Checklist empty state must not call the legacy monitoring run command",
);

console.log("medicalMonitoringDailyRunStartGate: 7 passed");
