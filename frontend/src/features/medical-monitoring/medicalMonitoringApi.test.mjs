import assert from "node:assert/strict";
import {
  MedicalMonitoringApiError,
  createMedicalMonitoringApi,
} from "./medicalMonitoringApi.mjs";

let passed = 0;
function check(condition, message) {
  assert.ok(condition, message);
  passed += 1;
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function zipResponse(body = "zip-bytes", status = 200) {
  return new Response(body, {
    status,
    headers: {
      "content-type": "application/zip",
      "content-disposition": 'attachment; filename="medical-risk-checklist-test.zip"',
    },
  });
}

const calls = [];
const api = createMedicalMonitoringApi({
  baseUrl: "http://127.0.0.1:8911/",
  fetchImpl: async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ ok: true, url });
  },
});

await api.getModuleSummary("proj/01");
await api.listSubjects("proj/01");
await api.getSubjectMonitoring("proj/01", "S 001");
await api.getRiskSnapshot("proj/01", {
  snapshotId: "snapshot 2",
  siteId: "C01",
  subjectId: "S 001",
  riskKey: "AE/MH-1",
  riskInstanceId: "ri/1",
  riskCategoryCode: "ae_missing_report",
  riskItem: "头痛",
  severity: "high",
  dispositionStatus: "pending_review",
  updatedAt: "2026-07-29",
  sortBy: "subject_id",
  sortDirection: "asc",
  page: 2,
  pageSize: 50,
});
await api.getRiskTaxonomy("proj/01");
await api.getRiskHistory("proj/01", "AE/MH-1");
await api.getRiskEvidence("proj/01", "ri/1", { locator: "LB:row/2" });

check(calls.length === 7, "performs all seven query types");
check(calls.every((call) => call.options.method === "GET"), "query methods remain GET-only");
check(calls.every((call) => call.options.body === undefined), "GET requests have no body");
check(
  calls[0].url === "http://127.0.0.1:8911/api/projects/proj%2F01/modules/medical-monitoring/summary",
  "builds project-neutral module summary path",
);
check(calls[1].url.endsWith("/api/projects/proj%2F01/monitoring/subjects"), "builds subjects path");
check(calls[2].url.endsWith("/subjects/S%20001/monitoring"), "encodes subject path segment");

const snapshotUrl = new URL(calls[3].url);
check(
  snapshotUrl.pathname.endsWith("/modules/medical-monitoring/risk-snapshots/current"),
  "uses side-effect-free snapshot endpoint",
);
check(snapshotUrl.searchParams.get("snapshot_id") === "snapshot 2", "pins the requested snapshot");
check(snapshotUrl.searchParams.get("risk_key") === "AE/MH-1", "passes risk focus");
check(snapshotUrl.searchParams.get("risk_category_code") === "ae_missing_report", "passes canonical category");
check(snapshotUrl.searchParams.get("risk_item") === "头痛", "passes risk item query");
check(snapshotUrl.searchParams.get("disposition_status") === "pending_review", "passes disposition");
check(snapshotUrl.searchParams.get("sort_by") === "subject_id", "passes closed sort field");
check(snapshotUrl.searchParams.get("sort_direction") === "asc", "passes sort direction");
check(snapshotUrl.searchParams.get("page_size") === "50", "passes pagination");
check(!calls[3].url.includes("/monitoring/risks?"), "never uses legacy implicit-run risk GET");

check(calls[4].url.endsWith("/modules/medical-monitoring/risk-taxonomy"), "builds taxonomy path");
check(calls[5].url.includes("/risks/AE%2FMH-1/history"), "encodes history risk key");
check(
  new URL(calls[6].url).searchParams.get("locator") === "LB:row/2",
  "encodes and restores evidence locator",
);

let validationError = null;
try {
  await api.getSubjectMonitoring("p1", " ");
} catch (error) {
  validationError = error;
}
check(validationError instanceof TypeError, "rejects blank identifiers before fetch");
check(calls.length === 7, "invalid identifier does not call fetch");

const failedApi = createMedicalMonitoringApi({
  fetchImpl: async () => jsonResponse({ detail: "current snapshot is unavailable" }, 404),
});
let httpError = null;
try {
  await failedApi.getRiskSnapshot("p1");
} catch (error) {
  httpError = error;
}
check(httpError instanceof MedicalMonitoringApiError, "uses typed API error");
check(httpError.status === 404, "preserves HTTP status");
check(httpError.message === "current snapshot is unavailable", "preserves API detail");

const conflictApi = createMedicalMonitoringApi({
  fetchImpl: async () => jsonResponse({
    detail: {
      code: "medical_monitoring_snapshot_not_found",
      message: "请求的风险快照不存在。",
    },
  }, 409),
});
let conflictError = null;
try {
  await conflictApi.getRiskSnapshot("p1", { snapshotId: "missing" });
} catch (error) {
  conflictError = error;
}
check(conflictError instanceof MedicalMonitoringApiError, "uses typed 409 error");
check(conflictError.status === 409, "preserves snapshot conflict status");
check(conflictError.detail.detail.code === "medical_monitoring_snapshot_not_found", "preserves conflict code");

const invalidQueryApi = createMedicalMonitoringApi({
  fetchImpl: async () => jsonResponse({
    detail: {
      code: "unsupported_risk_category_code",
      message: "不支持的风险类别代码。",
    },
  }, 422),
});
let invalidQueryError = null;
try {
  await invalidQueryApi.getRiskSnapshot("p1", { riskCategoryCode: "free-text" });
} catch (error) {
  invalidQueryError = error;
}
check(invalidQueryError.status === 422, "preserves query validation status");
check(invalidQueryError.detail.detail.code === "unsupported_risk_category_code", "preserves validation code");

const failedCalls = [];
const noFallbackApi = createMedicalMonitoringApi({
  fetchImpl: async (url) => {
    failedCalls.push(url);
    return jsonResponse({ detail: "not implemented yet" }, 404);
  },
});
try {
  await noFallbackApi.getRiskSnapshot("p1");
} catch {
  // Expected: absence of the safe endpoint must not trigger a legacy GET.
}
check(failedCalls.length === 1, "safe snapshot failure has no automatic fallback");
check(failedCalls[0].includes("/risk-snapshots/current"), "failed query remains on safe endpoint");

const exportCalls = [];
const exportApi = createMedicalMonitoringApi({
  baseUrl: "http://127.0.0.1:8911",
  fetchImpl: async (url, options) => {
    exportCalls.push({ url, options });
    return zipResponse();
  },
});
const riskExport = await exportApi.exportRiskSnapshot("proj/01", {
  snapshotId: "snapshot 2",
  siteId: "C01",
  subjectId: "S 001",
  riskCategoryCode: "ae_missing_report",
  riskItem: "头痛",
  severity: "high",
  dispositionStatus: "pending_review",
  updatedAt: "2026-07-29",
  sortBy: "subject_id",
  sortDirection: "asc",
  page: 9,
  pageSize: 25,
});
check(exportCalls.length === 1, "exports the risk checklist and evidence in one request");
check(exportCalls[0].options.method === "GET", "risk export remains read-only");
check(exportCalls[0].options.headers.Accept === "application/zip", "requests the export bundle");
const exportUrl = new URL(exportCalls[0].url);
check(
  exportUrl.pathname.endsWith("/modules/medical-monitoring/risk-snapshots/current/export"),
  "uses the project-scoped snapshot export endpoint",
);
check(exportUrl.searchParams.get("snapshot_id") === "snapshot 2", "pins the viewed snapshot for export");
check(exportUrl.searchParams.get("risk_category_code") === "ae_missing_report", "exports the current category filter");
check(exportUrl.searchParams.get("sort_by") === "subject_id", "exports the current sort");
check(!exportUrl.searchParams.has("page"), "exports all filtered rows rather than the visible page");
check(!exportUrl.searchParams.has("page_size"), "does not leak checklist pagination into export");
check(riskExport.filename === "medical-risk-checklist-test.zip", "uses the server-provided export filename");
check(riskExport.blob.size > 0, "returns downloadable export bytes");

const batchCalls = [];
const batchApi = createMedicalMonitoringApi({
  baseUrl: "http://127.0.0.1:8911",
  fetchImpl: async (url, options) => {
    batchCalls.push({ url, options });
    return jsonResponse({ ok: true });
  },
});
const listingFile = new Blob(["SUBJID,AETERM\nS001,Headache\n"], { type: "text/csv" });
Object.defineProperty(listingFile, "name", { value: "listing 01.csv" });
await batchApi.listBatches("p/1");
await batchApi.getBatch("p/1", "batch 1");
await batchApi.intakeBatchFile("p/1", listingFile, {
  idempotencyKey: "upload 1",
  classificationOverrideReason: "已核对为本次全量EDC导出",
});
await batchApi.confirmSourceContent("p/1", "src/1", {
  reason: "项目医学经理已核对文件基本信息。",
});
await batchApi.recordBatchValidationEvidence("p/1", "batch 1", {
  mapping_revision: "map-v1",
  mapping: { SUBJID: "subject_id" },
  expected_domains: ["AE"],
  full_snapshot_proof: { confirmed_full_export: true },
  expected_version: 4,
  idempotency_key: "evidence-1",
});
await batchApi.transitionBatch("p/1", "batch 1", {
  target_state: "parsed",
  expected_version: 3,
  idempotency_key: "transition-1",
});
await batchApi.getBatchDiff("p/1", "batch old", "batch new", {
  offset: 20,
  limit: 50,
});
await batchApi.getDailyRunReadiness("p/1", "batch 1");
await batchApi.listDailyRuns("p/1");
await batchApi.getDailyRun("p/1", "run 1");
await batchApi.prepareDailyRun("p/1", {
  batch_id: "batch 1",
  idempotency_key: "daily-1",
  actor: "medical_manager",
});
await batchApi.processDailyRun("p/1", "run 1", {
  expected_version: 3,
  owner: "monitoring-worker",
});
await batchApi.executeDailyRunRules("p/1", "run 1", {
  expected_version: 5,
  owner: "monitoring-worker",
});
await batchApi.submitDailyRunAi("p/1", "run 1", {
  expected_version: 6,
  owner: "monitoring-worker",
});
await batchApi.getDailyRunAiProgress("p/1", "run 1");
await batchApi.assembleDailyRunRisks("p/1", "run 1", {
  expected_version: 7,
  owner: "monitoring-worker",
});
await batchApi.acknowledgeDailyRunPartial("p/1", "run 1", {
  expected_version: 8,
  actor: "medical_manager",
});
await batchApi.markDailyRunReady("p/1", "run 1", {
  expected_version: 9,
  actor: "medical_manager",
});
await batchApi.confirmDailyRun("p/1", "run 1", {
  expected_run_version: 10,
  expected_baseline_revision: 2,
  confirmed_by: "medical_manager",
});

check(batchCalls.length === 19, "performs the complete batch and daily-run client surface");
check(batchCalls[0].options.method === "GET", "lists batches without mutation");
check(batchCalls[1].url.endsWith("/monitoring/batches/batch%201"), "encodes batch identifier");
check(batchCalls[2].options.method === "POST", "uploads a batch with POST");
check(batchCalls[2].options.body === listingFile, "uploads original listing bytes");
check(batchCalls[2].options.headers["Content-Type"] === "application/octet-stream", "marks binary listing content");
const intakeUrl = new URL(batchCalls[2].url);
check(intakeUrl.searchParams.get("filename") === "listing 01.csv", "preserves filename");
check(intakeUrl.searchParams.get("idempotency_key") === "upload 1", "passes intake idempotency key");
check(batchCalls[3].url.includes("/sources/src%2F1/content-validation/confirm"), "uses shared source confirmation route");
check(JSON.parse(batchCalls[4].options.body).mapping_revision === "map-v1", "serializes validation evidence");
check(JSON.parse(batchCalls[5].options.body).target_state === "parsed", "serializes explicit state transition");
const diffUrl = new URL(batchCalls[6].url);
check(diffUrl.searchParams.get("previous_batch_id") === "batch old", "passes previous batch");
check(diffUrl.searchParams.get("current_batch_id") === "batch new", "passes current batch");
check(diffUrl.searchParams.get("limit") === "50", "passes diff pagination");
const readinessUrl = new URL(batchCalls[7].url);
check(readinessUrl.pathname.endsWith("/monitoring/daily-runs/readiness"), "reads the formal daily-run start gate");
check(readinessUrl.searchParams.get("batch_id") === "batch 1", "binds readiness to the selected batch");
check(batchCalls[7].options.method === "GET", "readiness projection is read-only");
check(batchCalls[8].url.endsWith("/monitoring/daily-runs"), "lists daily runs");
check(batchCalls[9].url.endsWith("/monitoring/daily-runs/run%201"), "gets encoded daily run");
check(JSON.parse(batchCalls[10].options.body).batch_id === "batch 1", "prepares daily run");
check(batchCalls[11].url.endsWith("/monitoring/daily-runs/run%201/process"), "processes daily run");
check(batchCalls[12].url.endsWith("/monitoring/daily-runs/run%201/execute-rules"), "executes daily rules");
check(batchCalls[13].url.endsWith("/monitoring/daily-runs/run%201/submit-ai"), "submits independent AI review");
check(batchCalls[14].options.method === "GET", "reads AI progress without mutation");
check(batchCalls[14].url.endsWith("/monitoring/daily-runs/run%201/ai-progress"), "reads encoded AI progress path");
check(batchCalls[15].url.endsWith("/monitoring/daily-runs/run%201/assemble-risks"), "assembles the risk snapshot");
check(!("actor" in JSON.parse(batchCalls[16].options.body)), "does not submit a client actor for partial analysis");
check(batchCalls[17].url.endsWith("/monitoring/daily-runs/run%201/ready-to-confirm"), "marks reviewed risks ready");
check(JSON.parse(batchCalls[18].options.body).expected_baseline_revision === 2, "confirms against the current baseline revision");
check(batchCalls[18].url.endsWith("/monitoring/daily-runs/run%201/confirm"), "confirms the run as comparison baseline");

const mappingCalls = [];
const mappingApi = createMedicalMonitoringApi({
  baseUrl: "http://127.0.0.1:8911",
  fetchImpl: async (url, options) => {
    mappingCalls.push({ url, options });
    return jsonResponse({ ok: true });
  },
});
await mappingApi.startFieldMapping("p/1", "batch 1", {
  chunkSize: 10,
  retryFailed: true,
});
await mappingApi.getFieldMappingStatus("p/1", "batch 1");
await mappingApi.listMonitoringAiJobs("p/1", {
  taskType: "listing_field_mapping",
  businessKeyPrefix: "listing-field-mapping:batch 1:",
});
await mappingApi.getMonitoringAiJob("p/1", "job 1");
await mappingApi.decideMonitoringAiCandidate("p/1", "candidate 1", {
  decision: "accepted",
  actor: "medical_manager",
  reason: "采用该建议进入字段映射校对。",
});
await mappingApi.assembleMappingDraft("p/1", {
  batchId: "batch 1",
  fullProfileSha256: "a".repeat(64),
});
await mappingApi.adoptFieldMappingRun("p/1", {
  batchId: "batch 1",
  fullProfileSha256: "a".repeat(64),
  actor: "medical_manager",
  reason: "采用完整建议进入字段映射校对。",
});
await mappingApi.getMappingDraft("p/1", "draft 1");
await mappingApi.getMappingRevision("p/1", "revision 1");
await mappingApi.editMappingDraftField("p/1", "draft 1", {
  domain: "AE",
  source_field: "AETERM",
  patch: { recommended_role: "adverse_event_term" },
  expected_version: 1,
  actor: "medical_manager",
  idempotency_key: "edit-1",
});
await mappingApi.confirmMappingDraft("p/1", "draft 1", {
  expected_version: 2,
  confirmed_by: "medical_manager",
  confirmation_reason: "已核对本批次全部字段映射。",
  idempotency_key: "confirm-1",
});
await mappingApi.confirmBatchFullSnapshot("p/1", "batch 1", {
  expected_version: 3,
  full_snapshot_proof: {
    confirmed: true,
    basis: "完整 EDC 全量导出",
    confirmed_by: "medical_manager",
  },
  actor: "medical_manager",
  idempotency_key: "freeze-1",
});

check(mappingCalls.length === 12, "performs complete field-mapping workflow");
check(mappingCalls[0].options.method === "POST", "starts field mapping with POST");
check(JSON.parse(mappingCalls[0].options.body).chunk_size === 10, "passes bounded chunk size");
check(JSON.parse(mappingCalls[0].options.body).retry_failed === true, "retries only failed mapping jobs");
check(new URL(mappingCalls[1].url).searchParams.get("batch_id") === "batch 1", "restores mapping status by batch");
const jobsUrl = new URL(mappingCalls[2].url);
check(jobsUrl.searchParams.get("task_type") === "listing_field_mapping", "filters AI jobs by task");
check(jobsUrl.searchParams.get("business_key_prefix") === "listing-field-mapping:batch 1:", "filters jobs by batch");
check(mappingCalls[4].url.includes("/candidates/candidate%201/decision"), "encodes candidate decision path");
check(mappingCalls[5].url.endsWith("/mapping-drafts/assemble"), "assembles mapping draft explicitly");
check(mappingCalls[6].url.endsWith("/field-mapping-runs/adopt"), "adopts a complete mapping run in one request");
check(mappingCalls[8].url.endsWith("/mapping-revisions/revision%201"), "reads an active mapping revision");
check(mappingCalls[9].options.method === "PATCH", "edits one mapping field with PATCH");
check(JSON.parse(mappingCalls[10].options.body).expected_version === 2, "confirms an exact draft version");
check(mappingCalls[11].url.endsWith("/confirm-full-snapshot"), "confirms a batch with the active server mapping");

const protocolPreparationCalls = [];
const protocolPreparationApi = createMedicalMonitoringApi({
  baseUrl: "http://127.0.0.1:8911",
  fetchImpl: async (url, options) => {
    protocolPreparationCalls.push({ url, options });
    return jsonResponse({ ok: true });
  },
});
await protocolPreparationApi.listProtocolVersions("p/1");
await protocolPreparationApi.getProtocolPreparationStatus("p/1", "version 1");
await protocolPreparationApi.startProtocolPreparation("p/1", "version 1");
await protocolPreparationApi.startProtocolPreparation("p/1", "version 1", {
  topicIds: ["study_treatment", "safety_assessment"],
});
await protocolPreparationApi.decideProtocolPreparationCandidate(
  "p/1",
  "version 1",
  "candidate/1",
  {
    decision: "accepted",
    actor: "medical_manager",
    reason: "",
    expected_input_revision_sha256: "a".repeat(64),
    expected_source_revision: "mpr-current",
    proposed_fact_type: "study_treatment_change",
  },
);
await protocolPreparationApi.getRuleTemplateRecommendationStatus(
  "p/1",
  "fact revision/1",
  { expectedFactStateVersion: 3 },
);
await protocolPreparationApi.startRuleTemplateRecommendation(
  "p/1",
  "fact revision/1",
  { expected_fact_state_version: 3 },
);
await protocolPreparationApi.decideRuleTemplateRecommendation(
  "p/1",
  "fact revision/1",
  "rule candidate/1",
  {
    decision: "accepted",
    expected_input_revision_sha256: "b".repeat(64),
    expected_fact_state_version: 3,
    actor: "medical_manager",
    reason: "",
  },
);

check(protocolPreparationCalls.length === 8, "performs protocol preparation and rule recommendation clients");
check(protocolPreparationCalls[0].options.method === "GET", "lists protocol versions without mutation");
check(
  protocolPreparationCalls[0].url.endsWith(
    "/api/projects/p%2F1/modules/medical-monitoring/protocol-versions",
  ),
  "uses the project protocol version registry",
);
check(
  protocolPreparationCalls[1].url.endsWith(
    "/protocol-preparation/protocol-versions/version%201/status",
  ),
  "reads compact preparation status",
);
check(protocolPreparationCalls[2].options.method === "POST", "starts preparation explicitly");
check(
  protocolPreparationCalls[2].url.endsWith(
    "/protocol-preparation/protocol-versions/version%201/start",
  ),
  "starts the selected confirmed version",
);
check(
  JSON.parse(protocolPreparationCalls[2].options.body).topic_ids.length === 0,
  "starts all topics by default",
);
check(
  JSON.parse(protocolPreparationCalls[3].options.body).topic_ids.join(",")
    === "study_treatment,safety_assessment",
  "passes an explicit bounded topic subset",
);
check(
  protocolPreparationCalls[4].url.endsWith(
    "/protocol-preparation/protocol-versions/version%201/"
      + "candidates/candidate%2F1/decision",
  ),
  "encodes the candidate decision path",
);
check(
  protocolPreparationCalls[4].options.method === "POST",
  "records a protocol candidate decision with POST",
);
check(
  JSON.parse(protocolPreparationCalls[4].options.body)
    .expected_source_revision === "mpr-current",
  "passes the visible topic source revision unchanged",
);
check(
  JSON.parse(protocolPreparationCalls[4].options.body)
    .expected_input_revision_sha256 === "a".repeat(64),
  "passes the current frozen candidate input revision unchanged",
);
const ruleStatusUrl = new URL(protocolPreparationCalls[5].url);
check(
  ruleStatusUrl.pathname.endsWith(
    "/rule-template-recommendations/facts/fact%20revision%2F1/status",
  ),
  "reads a fact-scoped rule template recommendation status",
);
check(
  ruleStatusUrl.searchParams.get("expected_fact_state_version") === "3",
  "pins the fact state version while restoring recommendation status",
);
check(
  protocolPreparationCalls[6].url.endsWith(
    "/rule-template-recommendations/facts/fact%20revision%2F1/start",
  ),
  "starts recommendation generation for the accepted fact",
);
check(
  JSON.parse(protocolPreparationCalls[6].options.body)
    .expected_fact_state_version === 3,
  "starts against the exact accepted fact state",
);
check(
  protocolPreparationCalls[7].url.endsWith(
    "/rule-template-recommendations/facts/fact%20revision%2F1/"
      + "candidates/rule%20candidate%2F1/decision",
  ),
  "records a fact-scoped rule template decision",
);
check(
  JSON.parse(protocolPreparationCalls[7].options.body)
    .expected_input_revision_sha256 === "b".repeat(64),
  "passes the frozen rule recommendation input revision unchanged",
);
check(
  JSON.parse(protocolPreparationCalls[7].options.body)
    .expected_fact_state_version === 3,
  "passes the accepted fact CAS version unchanged",
);

const rulePackCalls = [];
const rulePackApi = createMedicalMonitoringApi({
  baseUrl: "http://127.0.0.1:8911/",
  fetchImpl: async (url, options) => {
    rulePackCalls.push({ url, options });
    return jsonResponse({ ok: true, url });
  },
});
await rulePackApi.listRulePacks("p/1");
await rulePackApi.getRulePack("p/1", "monpack 1");
await rulePackApi.getRulePackDiff("p/1", "monpack old", "monpack new");
await rulePackApi.createRulePackDraft("p/1", {
  protocol_version_id: "mpv 1",
  fact_revision_ids: ["fact 1", "fact 2"],
  created_by: "medical_manager",
});
await rulePackApi.startRulePackShadow("p/1", "monpack 1", {
  actor: "medical_manager",
  expected_pack_revision: 2,
});
await rulePackApi.runAutomaticShadow("p/1", "monpack 1", {
  batch_id: "batch 7",
  actor: "medical_manager",
  expected_pack_revision: 2,
});
await rulePackApi.listShadowSampleSets("p/1", "monpack 1");
await rulePackApi.listShadowRuns("p/1", "monpack 1");
await rulePackApi.confirmRulePackShadow("p/1", "monpack 1", {
  sample_set_id: "monshset 3",
  confirmed_by: "medical_manager",
  expected_pack_revision: 2,
});
await rulePackApi.publishRulePack("p/1", "monpack 1", {
  actor: "medical_manager",
  expected_pack_revision: 2,
});
await rulePackApi.getRulePackShadowLineageEvidence("p/1", "monpack 1");
check(rulePackCalls.length === 11, "performs the complete rule release chain calls");
check(
  rulePackCalls[0].url.endsWith("/api/projects/p%2F1/modules/medical-monitoring/rule-packs"),
  "lists project rule packs",
);
check(rulePackCalls[0].options.method === "GET", "rule pack listing stays read-only");
check(
  rulePackCalls[1].url.endsWith("/rule-packs/monpack%201"),
  "encodes the rule pack detail path",
);
check(
  rulePackCalls[2].url.endsWith("/rule-packs/monpack%20old/diff/monpack%20new"),
  "builds the pack-to-pack diff path",
);
check(
  rulePackCalls[3].url.endsWith("/rule-packs/drafts")
    && rulePackCalls[3].options.method === "POST",
  "creates the draft pack explicitly",
);
check(
  JSON.parse(rulePackCalls[3].options.body).fact_revision_ids.join(",") === "fact 1,fact 2",
  "passes confirmed fact revision ids unchanged",
);
check(
  rulePackCalls[4].url.endsWith("/rule-packs/monpack%201/start-shadow"),
  "starts the shadow stage explicitly",
);
check(
  rulePackCalls[5].url.endsWith("/rule-packs/monpack%201/automatic-shadow-runs"),
  "runs the server-side automatic shadow inspection",
);
const automaticShadowBody = JSON.parse(rulePackCalls[5].options.body);
check(
  Object.keys(automaticShadowBody).sort().join(",")
    === "batch_id,expected_pack_revision",
  "automatic shadow input carries only the batch choice and CAS token",
);
check(
  !("row_fingerprint" in automaticShadowBody)
    && !("mapping_revision" in automaticShadowBody)
    && !("case_ids" in automaticShadowBody),
  "automatic shadow never submits engineering fields",
);
check(
  rulePackCalls[6].url.endsWith("/rule-packs/monpack%201/shadow-sample-sets")
    && rulePackCalls[6].options.method === "GET",
  "lists frozen provisional sample sets read-only",
);
check(
  rulePackCalls[7].url.endsWith("/rule-packs/monpack%201/shadow-runs")
    && rulePackCalls[7].options.method === "GET",
  "lists trusted shadow runs read-only",
);
check(
  rulePackCalls[8].url.endsWith("/rule-packs/monpack%201/confirm-shadow")
    && rulePackCalls[8].options.method === "POST",
  "confirms shadow samples explicitly",
);
const confirmShadowBody = JSON.parse(rulePackCalls[8].options.body);
check(
  confirmShadowBody.sample_set_id === "monshset 3" && !("shadow_run_id" in confirmShadowBody),
  "confirmation submits the exact frozen sample set only",
);
check(
  rulePackCalls[9].url.endsWith("/rule-packs/monpack%201/publish")
    && rulePackCalls[9].options.method === "POST",
  "publishes the confirmed pack explicitly",
);
check(
  rulePackCalls[10].url.endsWith("/rule-packs/monpack%201/shadow-lineage-evidence")
    && rulePackCalls[10].options.method === "GET",
  "restores lineage-bound shadow evidence read-only",
);
check(
  rulePackCalls[10].options.body === undefined,
  "lineage evidence request carries no body",
);

const metricConfigurationCalls = [];
const metricConfigurationApi = createMedicalMonitoringApi({
  baseUrl: "http://127.0.0.1:8911",
  fetchImpl: async (url, options) => {
    metricConfigurationCalls.push({ url, options });
    return jsonResponse({ status: "candidate_only", candidates: [], issues: [] });
  },
});
await metricConfigurationApi.getMetricConfigurationCandidates(
  "p/1",
  "protocol version/1",
  "batch 1",
);
check(metricConfigurationCalls.length === 1, "reads metric candidates with one request");
check(metricConfigurationCalls[0].options.method === "GET", "metric candidates remain read-only");
const metricConfigurationUrl = new URL(metricConfigurationCalls[0].url);
check(
  metricConfigurationUrl.pathname.endsWith(
    "/modules/medical-monitoring/metric-configuration/protocol-versions/protocol%20version%2F1/candidates",
  ),
  "builds the project/version-scoped metric candidate path",
);
check(metricConfigurationUrl.searchParams.get("batch_id") === "batch 1", "binds metric candidates to the explicit listing batch");
check(metricConfigurationCalls[0].options.body === undefined, "metric candidate query carries no body");
let metricValidationError = null;
try {
  await metricConfigurationApi.getMetricConfigurationCandidates("p/1", "protocol-1", " ");
} catch (error) {
  metricValidationError = error;
}
check(metricValidationError instanceof TypeError, "rejects blank metric candidate batch ids before fetch");
check(metricConfigurationCalls.length === 1, "invalid metric candidate context does not call fetch");

console.log(`medicalMonitoringApi: ${passed} passed`);
