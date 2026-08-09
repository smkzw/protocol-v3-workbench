/**
 * Mock-server behavior tests for E3 12-lane harness — Worker 03 (Acceptance 03).
 *
 * Tests updated for new module APIs: payloadBuilder pattern, canonicalJsonStringify
 * from durable_client, receipts importing from durable_client, etc.
 *
 * @module final_release_12lane_behavior_tests
 */

import { strict as assert } from "node:assert";
import { createServer } from "node:http";
import { mkdtempSync, rmSync, readFileSync, existsSync, writeFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

import {
  DurableMwClient, LaneCheckpoint, extractCandidateArtifact, stableIdempotencyKey,
  LOCATOR_SCHEMA_VERSION, canonicalJsonStringify, computeRawResponseHash,
} from "./final_release_12lane_durable_client.mjs";
import { ReceiptCollector, buildServiceReceipt } from "./final_release_12lane_receipts.mjs";
import {
  SERVICE_RECEIPT_SCHEMA_VERSION, validateServiceReceipt, GATE_CODES_12LANE,
} from "./final_release_12lane_config.mjs";

let passed = 0, failed = 0; const failures = [];
function test(name, fn) { try { fn(); passed++; } catch (e) { failed++; failures.push({ name, message: e.message }); } }
async function testAsync(name, fn) { try { await fn(); passed++; } catch (e) { failed++; failures.push({ name, message: e.message }); } }

function readLocatorFile(dir) { return JSON.parse(readFileSync(join(dir, "job_locators.json"), "utf8")); }

function createMockApi(handlers = {}) {
  return new Promise((resolve) => {
    const server = createServer(async (req, res) => {
      const url = new URL(req.url, "http://localhost"); const path = url.pathname; const method = req.method;
      let body = {};
      if (method === "POST" || method === "PUT") { const chunks = []; for await (const c of req) chunks.push(c); try { body = JSON.parse(Buffer.concat(chunks).toString()); } catch {} }
      res.setHeader("Content-Type", "application/json");
      let postCount = handlers._postCount || 0;

      // IMPORTANT: /result must be matched BEFORE the generic job status matcher
      const resultMatch = path.match(/^\/api\/projects\/test-proj\/medical-writing\/jobs\/(.+)\/result$/);
      if (method === "GET" && resultMatch) {
        const jobId = resultMatch[1];
        const handler = handlers.getResult || (() => ({ status: 200, body: makeFullResultDto(jobId) }));
        const result = handler(jobId, body); res.writeHead(result.status); res.end(JSON.stringify(result.body)); return;
      }
      // Rewrite actions route — must be matched BEFORE generic revision-threads
      const rewriteMatch = path.match(/^\/api\/projects\/test-proj\/revision-threads\/(.+)\/actions$/);
      if (method === "POST" && rewriteMatch) {
        handlers._rewritePostCount = (handlers._rewritePostCount || 0) + 1;
        const handler = handlers.startRewrite || (() => ({ status: 202, body: { job_id: "rewrite-job-001", status: "accepted" } }));
        const result = handler(body); res.writeHead(result.status); res.end(JSON.stringify(result.body)); return;
      }
      // Accept-and-apply — before generic revision-threads match
      const acceptMatch = path.match(/^\/api\/projects\/test-proj\/revision-threads\/(.+)\/accept-and-apply$/);
      if (method === "POST" && acceptMatch) {
        const threadId = acceptMatch[1];
        const handler = handlers.acceptAndApply || (() => ({ status: 200, body: { section_id: "sec-001", working_copy_revision: 2, content_sha256: "new-hash", thread_id: threadId, suggestion_id: body.suggestion_id } }));
        const result = handler(threadId, body); res.writeHead(result.status); res.end(JSON.stringify(result.body)); return;
      }
      if (method === "POST" && path === "/api/projects/test-proj/revision-threads") {
        handlers._postCount = postCount + 1;
        const handler = handlers.startCandidate || (() => ({ status: 202, body: { job_id: "mock-job-001", status: "accepted" } }));
        const result = handler(body); res.writeHead(result.status); res.end(JSON.stringify(result.body)); return;
      }
      const jobMatch = path.match(/^\/api\/projects\/test-proj\/medical-writing\/jobs\/(.+)$/);
      if (method === "GET" && jobMatch) {
        const jobId = jobMatch[1];
        const handler = handlers.pollJob || (() => ({ status: 200, body: makeFullStatusDto(jobId) }));
        const result = handler(jobId, body); res.writeHead(result.status); res.end(JSON.stringify(result.body)); return;
      }
      const retryMatch = path.match(/^\/api\/projects\/test-proj\/medical-writing\/jobs\/(.+)\/retry$/);
      if (method === "POST" && retryMatch) {
        const handler = handlers.retryJob || (() => ({ status: 200, body: { job_id: "mock-job-replaced-002", status: "queued" } }));
        const result = handler(retryMatch[1], body); res.writeHead(result.status); res.end(JSON.stringify(result.body)); return;
      }
      const revThreadMatch = path.match(/^\/api\/projects\/test-proj\/revision-threads$/);
      if (method === "GET" && revThreadMatch) {
        const handler = handlers.getThreads || (() => ({ status: 200, body: [{ thread_id: "thread-001", status: "accepted", suggestions: [{ suggestion_id: "s1", status: "accepted" }] }] }));
        const result = handler(); res.writeHead(result.status); res.end(JSON.stringify(result.body)); return;
      }
      res.writeHead(404); res.end(JSON.stringify({ detail: "not found" }));
    });
    server.listen(0, () => { const port = server.address().port; resolve({ server, port, getPostCount: () => handlers._postCount || 0, getRewritePostCount: () => handlers._rewritePostCount || 0, close: () => new Promise((r) => server.close(r)) }); });
  });
}

function makeFullStatusDto(jobId) {
  return { job_id: jobId, status: "completed", provider: "deepseek", model: "deepseek-v4-pro", started_at: "2026-07-23T00:00:00Z", finished_at: "2026-07-23T00:05:00Z", endpoint_class: "product_api" };
}
function makeFullResultDto(jobId) {
  return { job_id: jobId, status: "completed", provider: "deepseek", model: "deepseek-v4-pro", endpoint_class: "product_api", policy_version: "v1", policy_hash: "ph1", input_hash: "ih", output_hash: "oh", started_at: "2026-07-23T00:00:00Z", finished_at: "2026-07-23T00:05:00Z", artifact: { thread_id: "thread-001", suggestion_ids: ["s1", "s2", "s3"] } };
}

function makeMockApiJson(apiBase) {
  return async function apiJson(method, reqPath, options = {}) {
    const url = reqPath.startsWith("http") ? reqPath : `${apiBase}${reqPath}`;
    const init = { method, headers: { "Content-Type": "application/json", ...options.headers }, signal: AbortSignal.timeout(options.timeout || 10000) };
    if (options.body !== undefined) { init.body = typeof options.body === "string" ? options.body : JSON.stringify(options.body); }
    const response = await fetch(url, init);
    const text = await response.text(); let payload = null; try { payload = text ? JSON.parse(text) : null; } catch { payload = text; }
    if (!response.ok && !options.allowStatus?.includes(response.status)) { const e = new Error(`${method} ${reqPath} -> ${response.status}`); e.status = response.status; throw e; }
    return { status: response.status, payload };
  };
}

// ════════════════════════════════════════════════════════════════════════
// TESTS
// ════════════════════════════════════════════════════════════════════════

// T1-T6: Receipt validation
test("T1-hardcoded-rejected", () => {
  const r = { schema_version: SERVICE_RECEIPT_SCHEMA_VERSION, lane_key: "L", step_id: "s", service_role: "reasoning_generation", provider: "deepseek", model: "deepseek-v4-pro", endpoint_class: "product_api", policy_or_prompt_version: "v1", policy_or_prompt_hash: "ph", product_task_id: "t", product_job_id: "j", product_run_id: "r", request_started_at: "2026-07-23T00:00:00Z", request_ended_at: "2026-07-23T00:05:00Z", terminal_status: "completed", artifact_ids: ["a"], input_redacted_hash: "ih", output_redacted_hash: "oh", source: "server_side_record", hardcoded: true };
  assert.ok(!validateServiceReceipt(r).valid);
});
test("T2-missing-job-id-rejected", () => {
  const r = { schema_version: SERVICE_RECEIPT_SCHEMA_VERSION, lane_key: "L", step_id: "ocr", service_role: "ocr", provider: "omlx", model: "GLM-OCR-bf16", endpoint_class: "local_omlx", policy_or_prompt_version: "v1", policy_or_prompt_hash: "ph", product_task_id: null, product_job_id: null, product_run_id: null, request_started_at: "2026-07-23T00:00:00Z", request_ended_at: "2026-07-23T00:05:00Z", terminal_status: "completed", artifact_ids: ["a"], input_redacted_hash: "ih", output_redacted_hash: "oh", source: "server_side_record", hardcoded: false };
  assert.ok(!validateServiceReceipt(r).valid);
});
test("T3-valid-receipt-accepted", () => {
  const r = { schema_version: SERVICE_RECEIPT_SCHEMA_VERSION, lane_key: "L", step_id: "s", service_role: "reasoning_generation", provider: "deepseek", model: "deepseek-v4-pro", endpoint_class: "product_api", policy_or_prompt_version: "v1", policy_or_prompt_hash: "ph", product_task_id: "t", product_job_id: "j", product_run_id: "r", request_started_at: "2026-07-23T00:00:00Z", request_ended_at: "2026-07-23T00:05:00Z", terminal_status: "completed", artifact_ids: ["a"], input_redacted_hash: "ih", output_redacted_hash: "oh", source: "server_side_record", hardcoded: false };
  assert.ok(validateServiceReceipt(r).valid, validateServiceReceipt(r).errors.join(","));
});
test("T4-builder-derives-identity", () => {
  const jr = makeFullResultDto("job-001");
  const r = buildServiceReceipt({ laneKey: "L", stepId: "s", serviceRole: "reasoning_generation", jobResult: jr });
  assert.ok(r); assert.equal(r.provider, "deepseek"); assert.equal(r.model, "deepseek-v4-pro");
});
test("T5-builder-null-without-job-id", () => {
  assert.equal(buildServiceReceipt({ laneKey: "L", stepId: "ocr", serviceRole: "ocr", jobResult: { status: "completed" } }), null);
});
test("T6-collector-rejects-invalid", () => {
  const c = new ReceiptCollector("L"); const rpt = { gateFailures: [] }; const gr = (r, code, e) => r.gateFailures.push({ gate_code: code, ...e });
  assert.equal(c.add(null, null, rpt, gr), false);
});

// T7: Durable client lifecycle (payloadBuilder pattern)
await testAsync("T7-durable-client-lifecycle", async () => {
  const mock = await createMockApi();
  const tmpDir = mkdtempSync(join(tmpdir(), "e3-"));
  const client = new DurableMwClient({ projectId: "test-proj", laneKey: "L", evidenceDir: tmpDir, apiJson: makeMockApiJson(`http://127.0.0.1:${mock.port}`), pollIntervalMs: 50 });
  await client.loadLocators();
  const result = await client.startAndPoll("test_step", "/api/projects/test-proj/revision-threads", (key) => ({ section_id: "s", user_instruction: "test", requested_by: "u", idempotency_key: key }), { timeoutMs: 5000 });
  assert.ok(result);
  assert.equal(result.status, "completed");
  // D2: result_hash must be present (from /result fetch)
  const locator = client.getLocator("test_step");
  assert.ok(locator.result_hash, "locator must have result_hash from /result fetch");
  await mock.close(); rmSync(tmpDir, { recursive: true, force: true });
});

// T8: Crash resume — locator retained on timeout
await testAsync("T8-crash-resume-timeout", async () => {
  const mock = await createMockApi({ pollJob: () => ({ status: 200, body: { job_id: "j", status: "running" } }) });
  const tmpDir = mkdtempSync(join(tmpdir(), "e3-"));
  const client = new DurableMwClient({ projectId: "test-proj", laneKey: "L", evidenceDir: tmpDir, apiJson: makeMockApiJson(`http://127.0.0.1:${mock.port}`), pollIntervalMs: 50 });
  await client.loadLocators();
  const result = await client.startAndPoll("crash_step", "/api/projects/test-proj/revision-threads", (key) => ({ section_id: "s", user_instruction: "t", requested_by: "u", idempotency_key: key }), { timeoutMs: 200 });
  assert.equal(result, null);
  const wrapper = readLocatorFile(tmpDir);
  assert.equal(wrapper.locators.crash_step.status, "timeout");
  await mock.close(); rmSync(tmpDir, { recursive: true, force: true });
});

// T9: Replacement retry (D4)
await testAsync("T9-replacement-retry", async () => {
  const mock = await createMockApi({ pollJob: () => ({ status: 200, body: { job_id: "j", status: "failed" } }) });
  const tmpDir = mkdtempSync(join(tmpdir(), "e3-"));
  const client = new DurableMwClient({ projectId: "test-proj", laneKey: "L", evidenceDir: tmpDir, apiJson: makeMockApiJson(`http://127.0.0.1:${mock.port}`), pollIntervalMs: 50 });
  await client.loadLocators();
  await client.startAndPoll("retry_step", "/api/projects/test-proj/revision-threads", (key) => ({ section_id: "s", user_instruction: "t", requested_by: "u", idempotency_key: key }), { timeoutMs: 2000 });
  let needsRetry = false;
  try { await client.startAndPoll("retry_step", "/api/projects/test-proj/revision-threads", (key) => ({}), { timeoutMs: 2000 }); } catch (e) { needsRetry = e.needsRetry; }
  assert.ok(needsRetry);
  await client.retry("retry_step", { timeoutMs: 2000 });
  const wrapper = readLocatorFile(tmpDir);
  assert.equal(wrapper.locators.retry_step.job_id, "mock-job-replaced-002");
  await mock.close(); rmSync(tmpDir, { recursive: true, force: true });
});

// T10: Resume never re-fires completed
await testAsync("T10-resume-no-refire", async () => {
  const mock = await createMockApi();
  const tmpDir = mkdtempSync(join(tmpdir(), "e3-"));
  const client = new DurableMwClient({ projectId: "test-proj", laneKey: "L", evidenceDir: tmpDir, apiJson: makeMockApiJson(`http://127.0.0.1:${mock.port}`), pollIntervalMs: 50 });
  await client.loadLocators();
  await client.startAndPoll("resume_step", "/api/projects/test-proj/revision-threads", (key) => ({ section_id: "s", user_instruction: "t", requested_by: "u", idempotency_key: key }), { timeoutMs: 5000 });
  assert.equal(mock.getPostCount(), 1);
  await client.startAndPoll("resume_step", "/api/projects/test-proj/revision-threads", (key) => ({}), { timeoutMs: 5000 });
  assert.equal(mock.getPostCount(), 1, "no re-start on resume");
  await mock.close(); rmSync(tmpDir, { recursive: true, force: true });
});

// T11-T13: extractCandidateArtifact
test("T11-extract-artifact", () => {
  const a = extractCandidateArtifact({ artifact: { thread_id: "t1", suggestion_ids: ["s1", "s2", "s3", "s4"] } });
  assert.equal(a.thread_id, "t1"); assert.equal(a.suggestion_ids.length, 4);
});
test("T12-extract-missing-thread-throws", () => { assert.throws(() => extractCandidateArtifact({ artifact: { suggestions: [{ suggestion_id: "s" }] } }), /thread_id/); });
test("T13-extract-missing-suggestions-throws", () => { assert.throws(() => extractCandidateArtifact({ artifact: { thread_id: "t", suggestions: [] } }), /suggestion_ids/); });

// T14-T26: Source checks
test("T14-pipeline-no-hardcoded-models", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_pipeline.mjs"), "utf8");
  for (const p of [/model:\s*["']deepseek-v4-pro["']/, /model:\s*["']GLM-OCR-bf16["']/, /model:\s*["']product_internal["']/]) assert.ok(!p.test(src), `should not contain ${p}`);
});
test("T15-child-no-slice", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(!src.includes(".slice(0, 2)")); assert.ok(!src.includes(".slice(0, 3)"));
});
test("T16-child-no-spawnSync", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(!src.includes("import { spawnSync }"));
});
test("T17-child-uses-confirm-prefill", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(src.includes("confirmFramingPrefill")); assert.ok(src.includes("confirmPicosPrefill"));
});
test("T18-child-uses-accept-and-apply", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(src.includes("acceptAndApplyCandidate"));
});
test("T19-child-uses-durable-client", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(src.includes("DurableMwClient")); assert.ok(src.includes("ReceiptCollector"));
});
test("T20-dry-run-skips", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(src.includes("skipped_dry_run"));
});
test("T22-all-chapter-loop", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(src.includes("for (const item of candidateItems)"));
  assert.ok(src.includes("for (const incl of expectedIncluded)"));
});
test("T23-source-blocking", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(src.includes("SYNOPSIS_FILE_MISSING"));
});
test("T24-probe-uc-ib", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_contract_probe.mjs"), "utf8");
  assert.ok(src.includes("7a038d8d90908b9a7e1525d32d65a8789c231bf9e04e7031cf879e59f7437267"));
});
test("T25-probe-openapi", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_contract_probe.mjs"), "utf8");
  assert.ok(src.includes("openapi.json"), "probe must fetch /openapi.json");
  assert.ok(src.includes("REQUIRED_ROUTES"), "probe must define REQUIRED_ROUTES");
});
test("T26-probe-dry-mode", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_contract_probe.mjs"), "utf8");
  assert.ok(src.includes('PROBE_DRY_RUN !== "0"'));
});

// ════════════════════════════════════════════════════════════════════════
// ADVERSARIAL TESTS (D1-D14)
// ════════════════════════════════════════════════════════════════════════

await testAsync("D1-one-start-only", async () => {
  const mock = await createMockApi();
  const tmpDir = mkdtempSync(join(tmpdir(), "e3-"));
  const client = new DurableMwClient({ projectId: "test-proj", laneKey: "L", evidenceDir: tmpDir, apiJson: makeMockApiJson(`http://127.0.0.1:${mock.port}`), pollIntervalMs: 50 });
  await client.loadLocators();
  await client.startAndPoll("d1_step", "/api/projects/test-proj/revision-threads", (key) => ({ section_id: "s", user_instruction: "t", requested_by: "u", idempotency_key: key }), { timeoutMs: 5000 });
  assert.equal(mock.getPostCount(), 1, "exactly one POST");
  await mock.close(); rmSync(tmpDir, { recursive: true, force: true });
});

test("D2-stable-idempotency", () => {
  const k1 = stableIdempotencyKey("UC_I_SCRATCH", "proj", "candidate", "sec-1");
  const k2 = stableIdempotencyKey("UC_I_SCRATCH", "proj", "candidate", "sec-1");
  assert.equal(k1, k2);
  assert.notEqual(k1, stableIdempotencyKey("UC_I_SCRATCH", "proj", "candidate", "sec-2"));
});

await testAsync("D3-corrupt-locator-fail-closed", async () => {
  const tmpDir = mkdtempSync(join(tmpdir(), "e3-"));
  writeFileSync(join(tmpDir, "job_locators.json"), "{ corrupt json }}");
  const client = new DurableMwClient({ projectId: "test-proj", laneKey: "L", evidenceDir: tmpDir, apiJson: makeMockApiJson("http://127.0.0.1:1"), pollIntervalMs: 50 });
  await assert.rejects(() => client.loadLocators(), /corrupt/i);
  rmSync(tmpDir, { recursive: true, force: true });
});

await testAsync("D3-schema-mismatch-fail-closed", async () => {
  const tmpDir = mkdtempSync(join(tmpdir(), "e3-"));
  writeFileSync(join(tmpDir, "job_locators.json"), JSON.stringify({ schema_version: "wrong", lane_key: "L", project_id: "test-proj", locators: {} }));
  const client = new DurableMwClient({ projectId: "test-proj", laneKey: "L", evidenceDir: tmpDir, apiJson: makeMockApiJson("http://127.0.0.1:1"), pollIntervalMs: 50 });
  await assert.rejects(() => client.loadLocators(), /schema/i);
  rmSync(tmpDir, { recursive: true, force: true });
});

await testAsync("D4-failed-throws-needsRetry", async () => {
  const mock = await createMockApi({ pollJob: () => ({ status: 200, body: { job_id: "j", status: "failed" } }) });
  const tmpDir = mkdtempSync(join(tmpdir(), "e3-"));
  const client = new DurableMwClient({ projectId: "test-proj", laneKey: "L", evidenceDir: tmpDir, apiJson: makeMockApiJson(`http://127.0.0.1:${mock.port}`), pollIntervalMs: 50 });
  await client.loadLocators();
  await client.startAndPoll("d4_step", "/api/projects/test-proj/revision-threads", (key) => ({ section_id: "s", user_instruction: "t", requested_by: "u", idempotency_key: key }), { timeoutMs: 2000 });
  const postBefore = mock.getPostCount();
  let needsRetry = false;
  try { await client.startAndPoll("d4_step", "/api/projects/test-proj/revision-threads", (key) => ({}), { timeoutMs: 2000 }); } catch (e) { needsRetry = e.needsRetry; }
  assert.ok(needsRetry);
  assert.equal(mock.getPostCount(), postBefore, "no new POST");
  await mock.close(); rmSync(tmpDir, { recursive: true, force: true });
});

await testAsync("D5-checkpoint-resume", async () => {
  const tmpDir = mkdtempSync(join(tmpdir(), "e3-"));
  const cp1 = new LaneCheckpoint({ laneKey: "L", evidenceDir: tmpDir, runtimeDir: "/rt", projectCode: "PC" });
  await cp1.save({ projectId: "p", sourceMode: "m", journeyRevision: 1, allocationAttempt: 1, completedStages: ["project_creation"], stageArtifacts: {} });
  const cp2 = new LaneCheckpoint({ laneKey: "L", evidenceDir: tmpDir, runtimeDir: "/rt", projectCode: "PC" });
  await cp2.load();
  assert.ok(cp2.hasProject()); assert.equal(cp2.getProjectId(), "p");
  rmSync(tmpDir, { recursive: true, force: true });
});

await testAsync("D5-checkpoint-lane-mismatch", async () => {
  const tmpDir = mkdtempSync(join(tmpdir(), "e3-"));
  const cp1 = new LaneCheckpoint({ laneKey: "L1", evidenceDir: tmpDir });
  await cp1.save({ projectId: "p", sourceMode: "m", journeyRevision: 1, allocationAttempt: 1, completedStages: [], stageArtifacts: {} });
  const cp2 = new LaneCheckpoint({ laneKey: "L2", evidenceDir: tmpDir });
  await assert.rejects(() => cp2.load(), /lane/i);
  rmSync(tmpDir, { recursive: true, force: true });
});

test("D6-null-provider-rejected", () => {
  const r = { schema_version: SERVICE_RECEIPT_SCHEMA_VERSION, lane_key: "L", step_id: "s", service_role: "reasoning_generation", provider: null, model: null, endpoint_class: null, policy_or_prompt_version: null, policy_or_prompt_hash: null, product_task_id: "t", product_job_id: "j", product_run_id: "r", request_started_at: null, request_ended_at: null, terminal_status: "completed", artifact_ids: [], input_redacted_hash: null, output_redacted_hash: null, source: "server_side_record", hardcoded: false };
  assert.ok(!validateServiceReceipt(r).valid);
});

test("D6-provider-mismatch-rejected", () => {
  const r = { schema_version: SERVICE_RECEIPT_SCHEMA_VERSION, lane_key: "L", step_id: "s", service_role: "reasoning_generation", provider: "openai", model: "gpt-4", endpoint_class: "product_api", policy_or_prompt_version: "v1", policy_or_prompt_hash: "ph", product_task_id: "t", product_job_id: "j", product_run_id: "r", request_started_at: "2026-07-23T00:00:00Z", request_ended_at: "2026-07-23T00:05:00Z", terminal_status: "completed", artifact_ids: ["a"], input_redacted_hash: "ih", output_redacted_hash: "oh", source: "server_side_record", hardcoded: false };
  assert.ok(!validateServiceReceipt(r).valid);
});

test("D7-forged-provider-rejected", () => {
  const jr = { ...makeFullResultDto("j"), provider: "forged", model: "hacked" };
  assert.equal(buildServiceReceipt({ laneKey: "L", stepId: "s", serviceRole: "reasoning_generation", jobResult: jr }), null);
});

test("D7-job-id-mismatch-rejected", () => {
  const jr = makeFullResultDto("job-result");
  const locator = { job_id: "job-locator" };
  assert.equal(buildServiceReceipt({ laneKey: "L", stepId: "s", serviceRole: "reasoning_generation", jobResult: jr, locator }), null);
});

test("D8-canonical-hash-recursive", () => {
  const obj = { b: 1, a: { d: 4, c: 3 } };
  const h1 = computeRawResponseHash(obj);
  const h2 = computeRawResponseHash({ a: { c: 3, d: 4 }, b: 1 });
  assert.equal(h1, h2, "canonical hash must be order-independent recursively");
});

test("D8-canonical-hash-different-for-nested-difference", () => {
  const h1 = computeRawResponseHash({ a: { x: 1 } });
  const h2 = computeRawResponseHash({ a: { x: 2 } });
  assert.notEqual(h1, h2);
});

test("D9-child-all-chapter-fail-closed", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(src.includes("expectedIncluded"));
  assert.ok(src.includes("included_chapter_has_no_candidate_set"));
  assert.ok(src.includes("atomic_adoption_not_verified"));
});

test("D9-child-verifies-atomic-adoption", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(src.includes("thread_id_match"));
  assert.ok(src.includes("wc_hash_changed"));
  assert.ok(src.includes("wc_revision_match"));
  assert.ok(src.includes("wc_id_match"));
  assert.ok(src.includes("section_id_match"));
  assert.ok(src.includes("reread_thread_exists"));
  assert.ok(src.includes("working_copy"), "child extracts nested working_copy from adopt result");
});

test("D10-locator-retention", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(src.includes("saveReconciliation"));
  assert.ok(src.includes("reconciled"));
  assert.ok(src.includes("deleteLocator"), "child must delete locators only after evidence commit");
});

test("D11-probe-full-mode-skipped", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_contract_probe.mjs"), "utf8");
  assert.ok(src.includes('"skipped"'));
  const section = src.substring(src.indexOf("full_mode_not_run") - 50, src.indexOf("full_mode_not_run") + 200);
  assert.ok(!section.includes('"pass"'), "full_mode_not_run must not use pass");
});

test("D12-child-rewrite-durable", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(src.includes("rewriteStepId"));
  assert.ok(src.includes("no_completed_rewrite_in_full_lane"), "child must fail when no rewrite completes");
});

test("D13-chrome-profile-dir", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_pipeline.mjs"), "utf8");
  assert.ok(src.includes("CHROME_PROFILE_DIR"));
});

test("D13-child-chrome-pid", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_child.mjs"), "utf8");
  assert.ok(src.includes("chromePid"));
});

test("D14-versioned-schema", () => {
  assert.equal(LOCATOR_SCHEMA_VERSION, "mw_e3_locator_v2");
});

await testAsync("D14-atomic-persistence-no-temp", async () => {
  const mock = await createMockApi();
  const tmpDir = mkdtempSync(join(tmpdir(), "e3-"));
  const client = new DurableMwClient({ projectId: "test-proj", laneKey: "L", evidenceDir: tmpDir, apiJson: makeMockApiJson(`http://127.0.0.1:${mock.port}`), pollIntervalMs: 50 });
  await client.loadLocators();
  await client.startAndPoll("d14_step", "/api/projects/test-proj/revision-threads", (key) => ({ section_id: "s", user_instruction: "t", requested_by: "u", idempotency_key: key }), { timeoutMs: 5000 });
  const tempFiles = readdirSync(tmpDir).filter((f) => f.includes(".tmp."));
  assert.equal(tempFiles.length, 0, "no temp files after save");
  await mock.close(); rmSync(tmpDir, { recursive: true, force: true });
});

// D2: Completed requires /result
await testAsync("D2-completed-requires-result: status without result fetch fails artifact gates", async () => {
  let resultCalls = 0;
  const mock = await createMockApi({ getResult: (jobId) => { resultCalls++; return { status: 200, body: makeFullResultDto(jobId) }; } });
  const tmpDir = mkdtempSync(join(tmpdir(), "e3-"));
  const client = new DurableMwClient({ projectId: "test-proj", laneKey: "L", evidenceDir: tmpDir, apiJson: makeMockApiJson(`http://127.0.0.1:${mock.port}`), pollIntervalMs: 50 });
  await client.loadLocators();
  await client.startAndPoll("d2_step", "/api/projects/test-proj/revision-threads", (key) => ({ section_id: "s", user_instruction: "t", requested_by: "u", idempotency_key: key }), { timeoutMs: 5000 });
  assert.ok(resultCalls >= 1, "must fetch /result at least once on completed");
  const locator = client.getLocator("d2_step");
  assert.ok(locator.result_hash, "must have result_hash");
  await mock.close(); rmSync(tmpDir, { recursive: true, force: true });
});

// D4: Candidate artifact with direct suggestion_ids
test("D4-extract-direct-suggestion-ids", () => {
  const a = extractCandidateArtifact({ artifact: { thread_id: "t1", suggestion_ids: ["s1", "s2", "s3"] } });
  assert.deepEqual(a.suggestion_ids, ["s1", "s2", "s3"]);
});

// D1: Route manifest — pipeline uses current routes
test("D1-pipeline-current-routes: no old routes in pipeline source", () => {
  const src = readFileSync(join(import.meta.dirname, "final_release_12lane_pipeline.mjs"), "utf8");
  // Check that old obsolete routes are gone
  assert.ok(!src.includes("authoring-journey/commit\""), "old /commit route gone");
  assert.ok(!src.includes("authoring-journey/search\""), "old /search route gone");
  assert.ok(!src.includes("authoring-journey/prepare\""), "old /prepare route gone");
  assert.ok(!src.includes("authoring-journey/translate\""), "old /translate route gone");
  assert.ok(!src.includes("documents/sections/"), "old /documents/sections/ route gone");
  assert.ok(!src.includes("method.*PUT.*working-copy"), "no PUT working-copy");
  // Verify new routes exist
  assert.ok(src.includes("stages/framing/commit"), "must use stages/framing/commit");
  assert.ok(src.includes("stages/picos/commit"), "must use stages/picos/commit");
  assert.ok(src.includes("competitor-search"), "must use competitor-search");
  assert.ok(src.includes("references/preparation-batches"), "must use references/preparation-batches");
  assert.ok(src.includes("references/translation-batches"), "must use references/translation-batches");
  assert.ok(src.includes("greenfield-document"), "must use greenfield-document");
  assert.ok(src.includes("working-copies/"), "must use working-copies/");
});

// ═════ RESULTS ═════
console.log(`\n${"=".repeat(70)}`);
console.log(`E3 Worker 03 Behavior Tests: ${passed} passed, ${failed} failed`);
if (failed > 0) { console.log("\nFailures:"); for (const f of failures) console.log(`  X ${f.name}: ${f.message}`); }
console.log("=".repeat(70));
process.exit(failed > 0 ? 1 : 0);
