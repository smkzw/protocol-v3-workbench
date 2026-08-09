/**
 * Bounded API-contract probe for E3 — Worker 03 (Acceptance Remediation 03).
 *
 * D11: Fetches /openapi.json and proves every method/path used by the
 * executable pipeline exists in the OpenAPI spec. A generic 404/422 cannot
 * prove a route because an unknown FastAPI path also returns 404.
 *
 * `dry_run_complete` may pass only the contract probe, never G3/G4/product
 * execution.
 *
 * @module final_release_12lane_contract_probe
 */

import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, existsSync, statSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { spawn } from "node:child_process";

const WORKBENCH_ROOT = join(import.meta.dirname, "..", "..");
const PROBE_DIR = join(WORKBENCH_ROOT, "runs/execution/mw_e3_live_12lane_harness_20260723/w03_contract_probe");
mkdirSync(PROBE_DIR, { recursive: true });

const DEFAULT_SYNOPSIS_PATH = "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/Ib期/MY009212A-UC-Ib-方案摘要-LXN.2024.01.27.docx";
const EXPECTED_UC_IB_SHA256 = "7a038d8d90908b9a7e1525d32d65a8789c231bf9e04e7031cf879e59f7437267";
const PROBE_SYNOPSIS_PATH = process.env.PROBE_SYNOPSIS_PATH || DEFAULT_SYNOPSIS_PATH;
const PROBE_DRY_RUN = process.env.PROBE_DRY_RUN !== "0";

// ─── Isolated runtime ───────────────────────────────────────────────────
const ISO_RUNTIME = mkdtempSync(join(tmpdir(), "e3-probe-"));
const AI_ENV_PATH = join(process.env.HOME || "", ".config/cms-medical-workbench/ai-runtime.env");

function readAiEnv() {
  const env = {};
  if (!existsSync(AI_ENV_PATH)) return env;
  for (const line of readFileSync(AI_ENV_PATH, "utf8").split("\n")) {
    const t = line.trim(); if (!t || t.startsWith("#")) continue;
    const eq = t.indexOf("="); if (eq === -1) continue;
    const k = t.slice(0, eq).trim(); let v = t.slice(eq + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
    env[k] = v;
  }
  return env;
}

const aiEnv = readAiEnv();
const apiEnv = { ...process.env, ...aiEnv, WORKBENCH_RUNTIME_DIR: ISO_RUNTIME, PYTHONUNBUFFERED: "1" };

function pickFreePort() {
  const { spawnSync } = require("node:child_process");
  const r = spawnSync("python3", ["-c", "import socket; s=socket.socket(); s.bind(('',0)); print(s.getsockname()[1]); s.close()"], { encoding: "utf8", env: apiEnv });
  return parseInt(r.stdout.trim()) || 0;
}

const EXTERNAL_API_PORT = parseInt(process.env.PROBE_API_PORT || "0") || 0;
const USE_EXTERNAL_API = EXTERNAL_API_PORT > 0;
const API_PORT = USE_EXTERNAL_API ? EXTERNAL_API_PORT : pickFreePort();
if (!API_PORT) { console.error("[probe] FATAL: no free port"); process.exit(2); }
const API_BASE = `http://127.0.0.1:${API_PORT}`;

let apiProc = null;
if (!USE_EXTERNAL_API) {
  apiProc = spawn("python3", ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(API_PORT)], { cwd: WORKBENCH_ROOT, env: apiEnv, stdio: ["pipe", "pipe", "pipe"] });
}
let apiStderr = "";
if (apiProc) { apiProc.stderr.on("data", (d) => { apiStderr += d.toString(); }); apiProc.stdout.on("data", () => {}); }

const results = {
  probe_dir: PROBE_DIR, probe_mode: PROBE_DRY_RUN ? "dry" : "full", isolated_runtime: ISO_RUNTIME, api_base: API_BASE,
  synopsis_source: { path: PROBE_SYNOPSIS_PATH, expected_sha256: EXPECTED_UC_IB_SHA256 },
  route_contracts: {}, openapi_paths: {}, started_at: new Date().toISOString(), steps: [], fatal_error: null,
};

function logStep(name, status, detail) {
  results.steps.push({ step: name, status, detail, timestamp: new Date().toISOString() });
  console.log(`[probe] ${name}: ${status} ${detail ? JSON.stringify(detail).slice(0, 300) : ""}`);
}

async function waitForApi(maxMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    try { const r = await fetch(`${API_BASE}/api/projects`); if (r.ok) return true; } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

// ─── D11: Exact routes used by the executable pipeline ──────────────────
//
// These are the exact method+path combinations that the child/pipeline
// actually calls. Every one must exist in the OpenAPI spec.
const REQUIRED_ROUTES = [
  ["GET", "/api/projects"],
  ["POST", "/api/projects"],
  ["GET", "/api/projects/{project_id}/medical-writing/authoring-journey"],
  ["POST", "/api/projects/{project_id}/medical-writing/authoring-journey/stages/{stage}/commit"],
  ["POST", "/api/projects/{project_id}/medical-writing/authoring-journey/competitor-search"],
  ["POST", "/api/projects/{project_id}/medical-writing/references/preparation-batches"],
  ["GET", "/api/projects/{project_id}/medical-writing/references/preparation-batches/{batch_id}"],
  ["GET", "/api/projects/{project_id}/medical-writing/references/workspace"],
  ["POST", "/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/extract"],
  ["POST", "/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/extraction-reviews"],
  ["POST", "/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/content-validation/override"],
  ["POST", "/api/projects/{project_id}/medical-writing/references/translation-batches"],
  ["GET", "/api/projects/{project_id}/medical-writing/references/translation-batches/{batch_id}"],
  ["POST", "/api/projects/{project_id}/medical-writing/references/translations/{translation_id}/medical-review"],
  ["POST", "/api/projects/{project_id}/medical-writing/references/translations/{translation_id}/admissions"],
  ["GET", "/api/projects/{project_id}/medical-writing/references/evidence-briefs"],
  ["POST", "/api/projects/{project_id}/medical-writing/greenfield-document"],
  ["GET", "/api/projects/{project_id}/medical-writing/greenfield-document"],
  ["GET", "/api/projects/{project_id}/medical-writing/working-copies/{section_id}"],
  ["POST", "/api/projects/{project_id}/medical-writing/working-copies/{section_id}"],
  ["POST", "/api/projects/{project_id}/revision-threads"],
  ["GET", "/api/projects/{project_id}/revision-threads"],
  ["POST", "/api/projects/{project_id}/revision-threads/{thread_id}/actions"],
  ["POST", "/api/projects/{project_id}/revision-threads/{thread_id}/accept-and-apply"],
  ["GET", "/api/projects/{project_id}/medical-writing/jobs/{job_id}"],
  ["GET", "/api/projects/{project_id}/medical-writing/jobs/{job_id}/result"],
  ["POST", "/api/projects/{project_id}/medical-writing/jobs/{job_id}/retry"],
  ["POST", "/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import"],
  ["GET", "/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/jobs/{idempotency_key}"],
  ["GET", "/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/jobs/{idempotency_key}/result"],
  ["POST", "/api/projects/{project_id}/medical-writing/literature/imports"],
  ["GET", "/api/projects/{project_id}/medical-writing/document.docx"],
];

async function fetchOpenApi() {
  const resp = await fetch(`${API_BASE}/openapi.json`);
  if (!resp.ok) throw new Error(`/openapi.json returned ${resp.status}`);
  return await resp.json();
}

function checkRouteInOpenApi(openapi, method, apiPath) {
  const pathItem = openapi.paths?.[apiPath];
  if (!pathItem) return { found: false, reason: "path_not_in_spec" };
  const methodLower = method.toLowerCase();
  if (!pathItem[methodLower]) return { found: false, reason: "method_not_in_path" };
  return { found: true };
}

async function main() {
  let fatalError = null;
  try {
    const ready = await waitForApi();
    if (!ready) throw new Error(`API not ready on ${API_BASE}. stderr: ${apiStderr.slice(-500)}`);
    logStep("api_ready", "pass", { base: API_BASE });

    // Synopsis source verification
    if (!existsSync(PROBE_SYNOPSIS_PATH)) throw new Error(`synopsis file not found: ${PROBE_SYNOPSIS_PATH}`);
    const fileBuffer = readFileSync(PROBE_SYNOPSIS_PATH);
    const fileSha256 = createHash("sha256").update(fileBuffer).digest("hex");
    const shaMatches = fileSha256 === EXPECTED_UC_IB_SHA256;
    logStep("synopsis_source_verified", shaMatches ? "pass" : "fail", { sha256: fileSha256, expected: EXPECTED_UC_IB_SHA256, sha_matches: shaMatches });
    if (!shaMatches) throw new Error(`UC Ib SHA mismatch: expected ${EXPECTED_UC_IB_SHA256}, got ${fileSha256}`);

    // D11: Fetch /openapi.json and prove every route exists
    const openapi = await fetchOpenApi();
    logStep("openapi_fetched", "pass", { path_count: Object.keys(openapi.paths || {}).length, openapi_version: openapi.openapi });
    results.openapi_version = openapi.openapi;
    results.openapi_path_count = Object.keys(openapi.paths || {}).length;

    let routesOk = 0;
    let routesFailed = 0;
    const routeFailures = [];
    for (const [method, apiPath] of REQUIRED_ROUTES) {
      const check = checkRouteInOpenApi(openapi, method, apiPath);
      results.route_contracts[`${method} ${apiPath}`] = check;
      if (check.found) {
        routesOk++;
      } else {
        routesFailed++;
        routeFailures.push(`${method} ${apiPath}: ${check.reason}`);
      }
    }
    logStep("route_contracts_verified", routesFailed === 0 ? "pass" : "fail", { total: REQUIRED_ROUTES.length, ok: routesOk, failed: routesFailed, failures: routeFailures });

    if (PROBE_DRY_RUN) {
      // D11: Dry-run completion is a real pass — it verified OpenAPI contracts
      logStep("dry_run_complete", "pass", { note: "Contract probe completed. All executable routes verified against /openapi.json. No product AI invoked." });
    } else {
      // D11: Full-mode deferred = skipped/not_run, never pass
      logStep("full_mode_not_run", "skipped", { note: "Full-mode probe not run. Route contracts verified; product AI execution deferred until Codex release." });
    }

  } catch (error) {
    fatalError = error;
    results.fatal_error = { message: error.message, stack: error.stack?.slice(0, 500) };
    logStep("fatal_error", "fail", { message: error.message.slice(0, 300) });
  } finally {
    results.completed_at = new Date().toISOString();
    results.api_stderr_tail = apiStderr.slice(-500);
    writeFileSync(join(PROBE_DIR, "probe_results.json"), JSON.stringify(results, null, 2));
    if (apiProc) { try { apiProc.kill("SIGTERM"); } catch {} await new Promise((r) => setTimeout(r, 2000)); try { apiProc.kill("SIGKILL"); } catch {} }
    if (!process.env.PRESERVE_PROBE_RUNTIME) { try { rmSync(ISO_RUNTIME, { recursive: true, force: true }); } catch {} }
    const passed = results.steps.filter((s) => s.status === "pass").length;
    const skipped = results.steps.filter((s) => s.status === "skipped").length;
    const failed = results.steps.filter((s) => s.status === "fail").length;
    const hasFatal = fatalError !== null;
    console.log(`\n[probe] Steps: ${passed} pass, ${skipped} skipped, ${failed} fail`);
    if (hasFatal) console.log(`[probe] FATAL error occurred`);
    console.log(`[probe] Results: ${join(PROBE_DIR, "probe_results.json")}`);
    process.exit(failed > 0 || hasFatal ? 1 : 0);
  }
}

main();
