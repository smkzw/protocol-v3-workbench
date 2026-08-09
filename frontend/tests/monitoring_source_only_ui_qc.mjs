import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const appSource = readFileSync(resolve(process.cwd(), "src/App.jsx"), "utf8");

for (const fragment of [
  "monitoringSourceReadiness",
  "monitoringExecutionReady",
  "data-monitoring-state={monitoringReadiness.kind}",
  "当前不会读取或写入受试者数据、运行规则或提交 AI 任务。",
  "module-row-source-only",
  "仅来源登记，等待结构解析与激活",
]) {
  assert.ok(appSource.includes(fragment), `missing source-only UI contract: ${fragment}`);
}

const guardedFetchSections = [
  "setMonitoringWorkbenchInbox(null)",
  "setMonitoringSubjectCatalog([])",
  "setRawMonitoring(null)",
  "setRiskIndex(null)",
];
for (const fragment of guardedFetchSections) {
  assert.ok(appSource.includes(fragment), `missing source-only read reset: ${fragment}`);
}

console.log("monitoring_source_only_ui_qc: 10 passed");
