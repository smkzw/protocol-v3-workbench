import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const protocolPanel = readFileSync(
  new URL("./MedicalMonitoringProtocolPreparationPanel.jsx", import.meta.url),
  "utf8",
);
const batchPanel = readFileSync(
  new URL("./MedicalMonitoringBatchPanel.jsx", import.meta.url),
  "utf8",
);
const dailyRunPanel = readFileSync(
  new URL("./MedicalMonitoringDailyRunPanel.jsx", import.meta.url),
  "utf8",
);
const ruleReleasePanel = readFileSync(
  new URL("./MedicalMonitoringRuleReleasePanel.jsx", import.meta.url),
  "utf8",
);
const fieldMappingPanel = readFileSync(
  new URL("./MedicalMonitoringFieldMappingPanel.jsx", import.meta.url),
  "utf8",
);
const assurancePanel = readFileSync(
  new URL("./MedicalMonitoringAssurancePanel.jsx", import.meta.url),
  "utf8",
);

for (const [label, source] of [
  ["protocol preparation", protocolPanel],
  ["batch", batchPanel],
  ["rule release", ruleReleasePanel],
]) {
  assert.match(
    source,
    /key=\{props\.projectId\}/,
    `${label} state is remounted synchronously for each project`,
  );
  assert.match(
    source,
    /createMedicalMonitoringProjectRequestScope\(projectId\)/,
    `${label} requests are bound to the initiating project`,
  );
  assert.match(
    source,
    /requestScope\.dispose\(\)/,
    `${label} aborts outstanding requests when its project unmounts`,
  );
  assert.match(
    source,
    /\{ signal: request\.signal \}/,
    `${label} sends cancellation signals to its API calls`,
  );
}

assert.doesNotMatch(
  batchPanel,
  /setActiveBatch\(await api\.getBatch/,
  "batch selection cannot commit an unguarded late response",
);
assert.match(
  batchPanel,
  /normalizeBatchList\(await api\.listBatches/,
  "batch lists are normalized before selection",
);
assert.match(
  batchPanel,
  /normalizeBatchDetail\(await api\.getBatch/,
  "batch details are normalized before rendering",
);
assert.match(
  batchPanel,
  /normalizeBatchIntakeResult\(await api\.intakeBatchFile/,
  "listing intake responses are normalized before state transitions",
);
assert.match(
  batchPanel,
  /normalizeContentConfirmationDetail\(detail\)/,
  "content confirmation errors are shape-checked before acknowledgment",
);
assert.doesNotMatch(
  batchPanel,
  /payload\.batches \|\| \[\]|detail\.validation\?\.checks \|\| \[\]|result\.batch\?\.batch\?\.batch_id/,
  "batch UI does not silently coerce malformed collections or identities",
);
assert.match(
  protocolPanel,
  /normalizeProtocolPreparationStatus\(payload\)/,
  "protocol preparation status is normalized before rendering",
);
assert.match(
  protocolPanel,
  /normalizeStatusOrThrow\(payload\)/,
  "protocol preparation start responses share the same shape guard",
);
assert.match(
  protocolPanel,
  /normalizeRuleTemplateRecommendationPayload\(/,
  "independent rule-recommendation status and start responses are shape-checked",
);
assert.match(
  protocolPanel,
  /normalizeRuleTemplateDecisionResponse\(/,
  "independent rule-recommendation decisions are shape-checked before state commit",
);
assert.match(
  protocolPanel,
  /MedicalMonitoringRuleTemplateShapeError/,
  "malformed rule-recommendation responses clear the stale payload",
);
assert.match(
  protocolPanel,
  /disabled=\{!view\.canStart \|\| !aiAvailable\}/,
  "rule-template generation is disabled when independent AI is unavailable",
);
assert.match(
  protocolPanel,
  /\(hasReadyTopic \|\| startAction\.available\)[\s\S]*?&& independentAiReady[\s\S]*?&& !starting/,
  "semantic protocol preparation requires explicit independent-AI readiness",
);
assert.match(
  protocolPanel,
  /requestScope\.cancel\("protocol-status"\)/,
  "changing protocol selection cancels the prior status request",
);
assert.match(
  dailyRunPanel,
  /createMedicalMonitoringProjectRequestScope\(projectId\)/,
  "daily-run state requests are bound to the initiating project",
);
assert.match(
  dailyRunPanel,
  /requestScope\.dispose\(\)/,
  "daily-run state requests are aborted when the project unmounts",
);
assert.match(
  dailyRunPanel,
  /getDailyRunReadiness\([\s\S]*\{ signal: request\.signal \}/,
  "daily-run readiness cannot commit a late project response",
);
assert.match(
  dailyRunPanel,
  /normalizeDailyRunReadiness\(rawReadiness, \{[\s\S]*projectId,[\s\S]*batchId: batch\.batch_id,[\s\S]*\}\)/,
  "daily-run readiness identity is validated before state commit",
);
assert.match(
  dailyRunPanel,
  /normalizeDailyRunList\(rawList, \{ projectId \}\)/,
  "daily-run list shape and project identity are validated before state selection",
);
assert.match(
  dailyRunPanel,
  /normalizeDailyRunDetail\(rawDetail, \{[\s\S]*projectId,[\s\S]*runId: selected\.run_id,[\s\S]*\}\)/,
  "daily-run detail shape and project/run identity are validated before rendering",
);
assert.match(
  dailyRunPanel,
  /dailyRunRiskCount\(detail\)/,
  "daily-run risk count is strict and evidence-bound",
);
assert.match(
  dailyRunPanel,
  /dailyRunAiAssemblyGate\(detail, aiProgress\)/,
  "daily-run risk assembly is gated by the explicit AI progress ledger",
);
assert.match(
  dailyRunPanel,
  /run\.status === "ai_running" && aiAssemblyGate\.canAssemble/,
  "daily-run assembly is offered only after a terminal, count-matched AI ledger",
);
assert.match(
  dailyRunPanel,
  /AI 已提交，但当前进度账本缺失或未与提交任务数一致/,
  "missing or inconsistent AI progress is visible instead of treated as ready",
);
assert.doesNotMatch(
  dailyRunPanel,
  /Number\(runList\?\.current_baseline\?\.revision \|\| 0\)/,
  "baseline revision cannot be coerced from malformed values",
);

assert.match(
  ruleReleasePanel,
  /requestScope\.cancel\("rule-release-state"\)/,
  "closing or switching project cancels the release state request",
);
assert.match(
  ruleReleasePanel,
  /api\.runAutomaticShadow\([\s\S]*?\{ signal \}/,
  "automatic shadow submission carries the project-scoped signal",
);
assert.match(
  ruleReleasePanel,
  /shadowLineageEvidenceViewModel/,
  "fresh-load sample restore is driven by the lineage evidence endpoint",
);
assert.match(
  ruleReleasePanel,
  /normalizeRulePackList\(await api\.listRulePacks/,
  "rule-pack lists are shape-checked before selection",
);
assert.match(
  ruleReleasePanel,
  /normalizeRulePackDetail\(await api\.getRulePack/,
  "rule-pack details are shape-checked before rendering",
);
assert.match(
  ruleReleasePanel,
  /normalizeShadowSampleSetList\(await api\.listShadowSampleSets/,
  "shadow sample lists are shape-checked before rendering",
);
assert.match(
  ruleReleasePanel,
  /normalizeShadowRunList\(await api\.listShadowRuns/,
  "shadow run lists are shape-checked before counts are shown",
);
assert.match(
  ruleReleasePanel,
  /normalizeAutomaticShadowResult\(await api\.runAutomaticShadow/,
  "automatic-shadow results are shape-checked before confirmation state",
);
assert.match(
  ruleReleasePanel,
  /normalizeRuleReleaseReadiness\(/,
  "daily-run readiness is shape-checked before the release gate is shown",
);
assert.match(
  ruleReleasePanel,
  /clearLoadedState\(\)/,
  "malformed release state clears stale project data",
);
assert.match(
  ruleReleasePanel,
  /api\.getRulePackShadowLineageEvidence\([\s\S]*?\{ signal: request\.signal \}/,
  "lineage evidence fetch carries the project-scoped signal",
);
assert.doesNotMatch(
  ruleReleasePanel,
  /row_fingerprint|content_sha256|case_ids|capability_manifest/,
  "rule release UI never requests engineering fields",
);
assert.doesNotMatch(
  ruleReleasePanel,
  /shadow_passed|验证通过/,
  "rule release UI never shows trusted pass vocabulary",
);
assert.doesNotMatch(
  ruleReleasePanel,
  /sampleSets\.items \|\| \[\]|runs\.items \|\| \[\]|batchPayload\.batches \|\| \[\]/,
  "rule release UI does not silently coerce malformed collections",
);
assert.match(
  fieldMappingPanel,
  /normalizeFieldMappingStatus\(status\)/,
  "field mapping status is normalized before rendering",
);
assert.match(
  fieldMappingPanel,
  /normalizeFieldMappingRun\(/,
  "field mapping start response is normalized before state commit",
);
assert.match(
  fieldMappingPanel,
  /normalizeMappingDraft\(/,
  "field mapping draft responses are normalized before editing or confirmation",
);
assert.match(
  fieldMappingPanel,
  /candidate\.structured_payload\.field_mappings/,
  "candidate field mappings are consumed only after the nested array guard",
);
assert.doesNotMatch(
  fieldMappingPanel,
  /status\.job_details\?\.length|candidate\.structured_payload\?\.field_mappings \|\| \[\]/,
  "field mapping UI does not silently coerce malformed collection payloads",
);
assert.match(
  assurancePanel,
  /normalizeAssuranceTaskList\(/,
  "assurance task lists are shape-checked before selection",
);
assert.match(
  assurancePanel,
  /normalizeAssuranceTaskPayload\(/,
  "assurance task details are shape-checked before rendering",
);
assert.match(
  assurancePanel,
  /normalizeAssuranceProofPayload\(/,
  "pre-lock proof responses are shape-checked before evidence display",
);
assert.match(
  assurancePanel,
  /evidenceRecorded: Boolean\(proof \|\| rollup\)/,
  "present but non-authoritative proof cannot be offered for silent re-recording",
);
assert.match(
  assurancePanel,
  /evidenceBlockingReason: evidence\.blockingReason/,
  "provenance blockers are carried into the action policy",
);
assert.match(
  assurancePanel,
  /normalizeAssuranceRollupPayload\(/,
  "pre-inspection rollup responses are shape-checked before drilldown",
);
assert.match(
  assurancePanel,
  /normalizeAssuranceAuditPayload\(/,
  "assurance audit responses are shape-checked before rendering",
);
assert.match(
  assurancePanel,
  /normalizeAssuranceReadinessPayload\(/,
  "assurance readiness responses are shape-checked before rendering",
);
assert.match(
  assurancePanel,
  /assuranceActionAvailability\(/,
  "assurance action order is derived from the fail-closed feature policy",
);
assert.match(
  assurancePanel,
  /AssuranceActionStatus/,
  "assurance action blockers are visible without implicit submit controls",
);
assert.match(
  assurancePanel,
  /api\.evaluateReadiness\(projectId, selectedTaskId, assuranceReadinessPayload\(input\)/,
  "assurance readiness is evaluated against the selected project task",
);
assert.match(
  assurancePanel,
  /api\.getAudit\(projectId, taskId, \{ signal: request\.signal \}\)/,
  "assurance audit reads are project/task scoped and cancellable",
);
assert.match(
  assurancePanel,
  /if \(!principalReady\)/,
  "assurance audit reads remain blocked without a valid server principal",
);
assert.match(
  assurancePanel,
  /审计链/,
  "assurance detail renders a compact audit chain state",
);
assert.doesNotMatch(
  assurancePanel,
  /event\.payload/,
  "assurance audit UI does not render raw event payload internals",
);
assert.match(
  assurancePanel,
  /normalizeAssuranceCreateResponse\(/,
  "assurance task creation responses are shape-checked before refresh",
);
assert.match(
  assurancePanel,
  /MedicalMonitoringAssuranceShapeError/,
  "malformed assurance payloads clear stale evidence state",
);
assert.match(
  assurancePanel,
  /clearLoadedState\(\)/,
  "malformed assurance lists clear stale project tasks",
);
assert.doesNotMatch(
  assurancePanel,
  /payload\.items \?\.length|payload\.items \|\| \[\]/,
  "assurance UI does not silently coerce malformed task collections",
);
assert.match(
  assurancePanel,
  /key=\{props\.projectId\}/,
  "assurance state is remounted synchronously for each project",
);
assert.match(
  assurancePanel,
  /createMedicalMonitoringProjectRequestScope\(projectId\)/,
  "assurance requests are bound to the initiating project",
);
assert.match(
  assurancePanel,
  /requestScope\.dispose\(\)/,
  "assurance aborts outstanding requests when its project unmounts",
);
assert.match(
  assurancePanel,
  /requestScope\.isCurrent\(request\)/,
  "assurance cannot commit a late response from another project",
);
assert.match(
  assurancePanel,
  /signal: request\.signal/,
  "assurance API calls carry the project-scoped cancellation signal",
);
assert.match(
  assurancePanel,
  /requestScope\.cancel\("assurance-task-list"\)/,
  "assurance list refresh is cancelled on project or mode change",
);
assert.match(
  assurancePanel,
  /requestScope\.cancel\("assurance-readiness"\)/,
  "assurance readiness refresh is cancelled on project or task change",
);

console.log("medicalMonitoringProjectSwitchIsolation: 69 passed");
