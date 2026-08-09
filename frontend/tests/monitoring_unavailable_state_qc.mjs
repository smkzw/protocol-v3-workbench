import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const appPath = new URL("../src/App.jsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);
const checklistPath = new URL("../src/features/medical-monitoring/MedicalMonitoringRiskChecklist.jsx", import.meta.url);
const scopeSummaryPath = new URL("../src/features/medical-monitoring/MedicalMonitoringScopeSummary.jsx", import.meta.url);
const assurancePath = new URL("../src/features/medical-monitoring/MedicalMonitoringAssurancePanel.jsx", import.meta.url);
const batchPath = new URL("../src/features/medical-monitoring/MedicalMonitoringBatchPanel.jsx", import.meta.url);
const protocolPreparationPath = new URL("../src/features/medical-monitoring/MedicalMonitoringProtocolPreparationPanel.jsx", import.meta.url);
const app = await readFile(appPath, "utf8");
const styles = await readFile(stylesPath, "utf8");
const checklist = await readFile(checklistPath, "utf8");
const scopeSummary = await readFile(scopeSummaryPath, "utf8");
const assurance = await readFile(assurancePath, "utf8");
const batch = await readFile(batchPath, "utf8");
const protocolPreparation = await readFile(protocolPreparationPath, "utf8");

assert.match(app, /function readJsonOrThrow\(response\)/);
assert.match(app, /if \(response\.ok\) return response\.json\(\);/);
assert.match(app, /error\.code = detail && typeof detail === "object"/);
assert.match(app, /monitoring_principal_unavailable/);
assert.match(app, /monitoring_read_action_unconfigured/);
assert.match(app, /monitoring_response_project_mismatch/);
assert.match(app, /const transport = error\?\.readSource === "contract"/);
assert.match(app, /function MonitoringReadUnavailable\(\{ surface, error, compact = false \}\)/);
assert.match(app, /data-read-state="unavailable"/);
assert.match(app, /项目总览暂不可用/);
assert.match(app, /当前未显示风险计数、模块进度或待审批数量/);
assert.match(app, /const emptyProjectMetricValue = loading \|\| unavailable \? "—" : "0";/);
assert.match(app, /function OverviewPage\([\s\S]*?\{\n  const \[actionError, setActionError\] = useState\(""\);\n  if \(dashboardError\)/);
assert.match(app, /workbenchInboxError \? \(/);
assert.match(app, /aiRunsError && <MonitoringReadUnavailable/);
assert.match(app, /const shellWorkbenchInboxError = shellUsesMonitoringInbox \? monitoringReadError : workbenchInboxReadError;/);
assert.match(app, /workbenchInbox=\{monitoringWorkbenchInbox\}/);
assert.doesNotMatch(app, /workbenchInbox=\{monitoringWorkbenchInbox \|\| workbenchInbox\}/);
assert.match(app, /const riskReadUnavailable = Boolean\(riskIndexError\);/);
assert.match(app, /const riskCountDisplay = riskReadUnavailable \? "—" : riskIndex\?\.total \?\? 0;/);
assert.match(app, /setRiskIndexError\(`风险分类读取失败：/);
assert.match(app, /setRiskIndexError\(`风险定位读取失败：/);
assert.match(app, /setSourcePreviewsError\(`来源证据片段读取失败：/);
assert.match(app, /const rawMonitoringUnavailable = Boolean\(rawMonitoringError\);/);
assert.match(app, /rawMonitoringUnavailable \? "来源暂不可用"/);
assert.match(app, /className="monitoring-structure-warning-action"/);
assert.match(app, /title="打开批次准备与字段映射工作区"/);
assert.match(app, /onClick=\{toggleBatchWorkspace\}/);
assert.match(app, /打开批次与字段映射/);
assert.match(app, /const \[sourceManifestReadErrors, setSourceManifestReadErrors\] = useState\(\{\}\);/);
assert.match(app, /monitoring_source_manifest/);
assert.match(app, /activeSourceManifestReadError/);
assert.match(app, /来源清单响应项目身份不匹配/);
assert.match(app, /<MonitoringReadUnavailable surface="monitoring_source_manifest" error=\{activeSourceManifestReadError\} \/>/);
assert.match(app, /fetch\(`\/api\/projects\/\$\{monitoringProjectId\}\/monitoring\/raw-intake`\)[\s\S]*?\.then\(\(response\) => readJsonOrThrow\(response\)\)/);
const rawMonitoringEffect = app.match(
  /fetch\(`\/api\/projects\/\$\{monitoringProjectId\}\/monitoring\/raw-intake`\)[\s\S]*?\.catch\(\(error\) => \{[\s\S]*?setRawMonitoringError\([\s\S]*?\}\);/,
);
assert.ok(rawMonitoringEffect, "raw monitoring read should preserve an explicit failure state");
assert.match(rawMonitoringEffect[0], /setRawMonitoring\(null\)/);

const inboxEffect = app.match(
  /fetch\(`\/api\/projects\/\$\{activeProjectId\}\/workbench-inbox`\)[\s\S]*?\.catch\(\(error\) => \{[\s\S]*?setWorkbenchInboxReadError\(error\);[\s\S]*?\}\);/,
);
assert.ok(inboxEffect, "active workbench inbox effect should preserve an explicit failure state");
assert.match(inboxEffect[0], /setWorkbenchInbox\(null\)/);
assert.doesNotMatch(inboxEffect[0], /setWorkbenchInbox\(\{\s*items\s*:/);

const monitoringEffect = app.match(
  /fetch\(`\/api\/projects\/\$\{monitoringRouteProjectId\}\/workbench-inbox`\)[\s\S]*?\.catch\(\(error\) => \{[\s\S]*?setMonitoringReadError\(error\);[\s\S]*?\}\);/,
);
assert.ok(monitoringEffect, "monitoring inbox effect should preserve an explicit failure state");
assert.match(monitoringEffect[0], /setMonitoringWorkbenchInbox\(null\)/);
assert.doesNotMatch(monitoringEffect[0], /setMonitoringWorkbenchInbox\(\{\s*items\s*:/);

assert.match(styles, /\.monitoring-read-unavailable\s*\{/);
assert.match(styles, /\.monitoring-read-unavailable\.is-compact\s*\{/);
assert.match(checklist, /const totalLabel = error \? "风险数量未读取"/);
assert.match(checklist, /interactive && !error && <div className="risk-checklist-pagination"/);
assert.match(scopeSummary, /const readUnavailable = Boolean\(error\);/);
assert.match(scopeSummary, /项目、中心和个例汇总暂不可用/);
assert.match(assurance, /nextError\?\.name !== "AbortError"/);
assert.match(assurance, /clearLoadedState\(\);/);
assert.match(assurance, /保障任务详情读取失败/);
assert.match(batch, /if \(nextError\?\.name !== "AbortError"\) \{\n        clearBatchState\(\);/);
assert.match(batch, /<MedicalMonitoringProtocolPreparationPanel[\s\S]*?aiStatus=\{aiStatus\}/);
assert.match(protocolPreparation, /aiStatus = \{\}/);
assert.match(protocolPreparation, /const independentAiReady = aiStatus\?\.ready === true/);
assert.match(protocolPreparation, /\(hasReadyTopic \|\| startAction\.available\)[\s\S]*?&& independentAiReady[\s\S]*?&& !starting/);
assert.match(protocolPreparation, /独立AI正在分析相关方案原文/);
assert.match(protocolPreparation, /队列\/运行状态不等于已生成语义候选/);
assert.match(protocolPreparation, /方案事实已确认；独立AI当前不可运行，配置后再生成规则建议/);
assert.match(protocolPreparation, /等待独立AI/);
assert.match(protocolPreparation, /已找到相关方案原文；独立AI当前不可运行/);

console.log(JSON.stringify({
  app: "unavailable-state-contract-present",
  activeInbox: "failure-does-not-become-empty-data",
  monitoringInbox: "failure-does-not-become-empty-data",
  protocolPreparation: "queued-running-copy-is-AI-status-aware",
  styles: "unavailable-state-styled",
}));
