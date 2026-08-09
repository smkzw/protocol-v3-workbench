/**
 * 12-Lane parent harness — E3 (acceptance-05).
 *
 * Fixes:
 * - D3: process.exitCode=1 when report.passed is false.
 * - D4: checkResume rejected → block before services, preserve runtime, emit failure.
 * - D9: QC_TEST_CHILD_SCRIPT env for test-only child injection (fail closed outside dry/test).
 * - D7: Atomic job locator save with project/attempt lineage.
 *
 * @module final_release_12lane_parent
 */

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync as fsExistsSync, readFileSync as fsReadFileSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

import { STABLE_RUNTIME_RELATIVE } from "./cross_indication_e2e_config.mjs";
import { EXPECTED_STUDIES_12LANE, validateLaneCoverage, resolveLanes, CTGOV_SENTINEL_EVIDENCE } from "./final_release_12lane_config.mjs";
import { StableHash, MultiRootStableHash } from "./final_release_12lane_stable_hash.mjs";
import { registerProcess, stopLaneProcesses, writeOwnershipRecord, checkResume, countUnresolvedLocators } from "./final_release_12lane_process_ownership.mjs";
import { allocateLane, releaseLane, releaseHeldPort, validateIsolation, runBoundedConcurrency, parseConcurrencyEnv, atomicWriteFile, cleanupAllocation, getAllocationOwnedDirs } from "./final_release_12lane_runtime_isolation.mjs";

const require = createRequire(import.meta.url);
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");

// Production child script
const childScript = path.join(scriptDir, "final_release_12lane_child.mjs");
// Test-only child injection: only allowed in dry-run mode
const testChildScript = process.env.QC_TEST_CHILD_SCRIPT || null;

const TASK_ROOT = "runs/execution/mw_e3_live_12lane_harness_20260723";
const outputDir = process.env.QC_OUTPUT_DIR || path.join(projectRoot, TASK_ROOT, "lanes");
const taskRuntimeRoot = process.env.QC_TASK_RUNTIME_ROOT || path.join(projectRoot, TASK_ROOT, "runtimes");

function resolveStableRoots() {
  if (process.env.STABLE_RUNTIME_ROOTS) {
    return process.env.STABLE_RUNTIME_ROOTS.split(",")
      .map((pair) => { const idx = pair.indexOf(":"); return idx === -1 ? null : { label: pair.slice(0, idx).trim(), path: pair.slice(idx + 1).trim() }; })
      .filter(Boolean);
  }
  return [
    { label: "workspace_runtime", path: path.resolve(projectRoot, STABLE_RUNTIME_RELATIVE, "runtime") },
    { label: "project_runtime", path: path.join(projectRoot, "runtime") },
  ];
}

const stableRoots = resolveStableRoots();
const DRY_RUN = process.argv.includes("----dry-run") || process.argv.includes("--dry-run");
const lanesArg = process.argv.find((a) => a.startsWith("--lanes="));
const requestedLanes = lanesArg?.slice("--lanes=".length).trim();
const { concurrency: maxConcurrency, error: concurrencyError } = parseConcurrencyEnv(process.env.QC_MAX_CONCURRENCY);

// D9: Test child injection only allowed in dry-run mode
const useTestChild = testChildScript && DRY_RUN;
if (testChildScript && !DRY_RUN) {
  console.error("FATAL: QC_TEST_CHILD_SCRIPT is only allowed in --dry-run mode");
  process.exit(1);
}

function checkAiEnvPresence() {
  const envPath = path.join(process.env.HOME || "", ".config/cms-medical-workbench/ai-runtime.env");
  if (!fsExistsSync(envPath)) return { present: false, keys: [] };
  const keys = [];
  for (const line of fsReadFileSync(envPath, "utf8").split("\n")) {
    const t = line.trim(); if (!t || t.startsWith("#")) continue;
    const eq = t.indexOf("="); if (eq === -1) continue;
    keys.push(t.slice(0, eq).trim());
  }
  return { present: true, keys };
}

function loadAiEnvValues() {
  const envPath = path.join(process.env.HOME || "", ".config/cms-medical-workbench/ai-runtime.env");
  if (!fsExistsSync(envPath)) return {};
  const v = {};
  for (const line of fsReadFileSync(envPath, "utf8").split("\n")) {
    const t = line.trim(); if (!t || t.startsWith("#")) continue;
    const eq = t.indexOf("="); if (eq === -1) continue;
    const k = t.slice(0, eq).trim(), val = t.slice(eq + 1).trim();
    v[k] = (val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'")) ? val.slice(1, -1) : val;
  }
  return v;
}

async function fileSha256(p) {
  const { createReadStream } = await import("node:fs");
  const h = createHash("sha256");
  for await (const c of createReadStream(p)) h.update(c);
  return h.digest("hex");
}

// ─── Listener ancestry verification ─────────────────────────────────────

function getListenerPids(port) {
  try {
    const out = require("child_process").execSync(`lsof -ti:${port} -sTCP:LISTEN`, { encoding: "utf8", timeout: 5000, stdio: ["pipe", "pipe", "pipe"] }).trim();
    return out.split("\n").filter(Boolean).map(Number);
  } catch { return []; }
}

function getDescendants(rootPid) {
  if (!rootPid || rootPid <= 0) return [];
  try {
    const out = require("child_process").execSync(`pgrep -P ${rootPid} 2>/dev/null || true`, { encoding: "utf8", timeout: 5000, stdio: ["pipe", "pipe", "pipe"] }).trim();
    const children = out.split("\n").filter(Boolean).map(Number);
    const all = [...children];
    for (const c of children) all.push(...getDescendants(c));
    return all;
  } catch { return []; }
}

function verifyListenerAncestry(port, spawnedPid) {
  const listeners = getListenerPids(port);
  if (listeners.length === 0) return { verified: false, reason: "no_listener_found", listenerPid: null };
  if (listeners.includes(spawnedPid)) return { verified: true, reason: "direct_listener", listenerPid: spawnedPid };
  const descendants = getDescendants(spawnedPid);
  for (const listener of listeners) {
    if (descendants.includes(listener)) return { verified: true, reason: `descendant:${listener}`, listenerPid: listener };
  }
  return { verified: false, reason: `foreign_listener:[${listeners.join(",")}]`, listenerPid: listeners[0] };
}

// ─── Service-specific readiness ─────────────────────────────────────────

async function waitForApiReady(url, spawnedPid, port, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const resp = await fetch(url, { signal: AbortSignal.timeout(3000) });
      if (resp.ok) {
        const body = await resp.text();
        let valid = false;
        try { const json = JSON.parse(body); valid = json && typeof json === "object" && (json.status || json.health || json.service); } catch {}
        if (valid) {
          const anc = verifyListenerAncestry(port, spawnedPid);
          if (!anc.verified) throw new Error(`api_${anc.reason}`);
          return true;
        }
      }
    } catch (err) { if (err.message?.includes("foreign_listener") || err.message?.includes("api_")) throw err; }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`api_timeout:${url} pid=${spawnedPid}`);
}

async function waitForViteReady(url, spawnedPid, port, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const resp = await fetch(url, { signal: AbortSignal.timeout(3000) });
      if (resp.ok) {
        const body = await resp.text();
        if (body.includes("<html") || body.includes("<!DOCTYPE") || body.includes("<div") || body.includes("<script")) {
          const anc = verifyListenerAncestry(port, spawnedPid);
          if (!anc.verified) throw new Error(`vite_${anc.reason}`);
          return true;
        }
      }
    } catch (err) { if (err.message?.includes("foreign_listener") || err.message?.includes("vite_")) throw err; }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`vite_timeout:${url} pid=${spawnedPid}`);
}

// ─── Service spawn ──────────────────────────────────────────────────────

function spawnServicePgid(command, args, cwd, env) {
  const proc = spawn(command, args, { cwd, env, stdio: ["ignore", "pipe", "pipe"], detached: true });
  return { proc, pid: proc.pid, pgid: proc.pid };
}

// ─── SQLite ─────────────────────────────────────────────────────────────

async function sqliteIntegrityCheck(runtimeDir) {
  const results = {};
  if (!fsExistsSync(runtimeDir)) return results;
  let files; try { files = require("fs").readdirSync(runtimeDir); } catch { return results; }
  for (const file of files) {
    if (file.endsWith(".sqlite3") || file.endsWith(".sqlite")) {
      try { results[file] = require("child_process").execFileSync("sqlite3", [path.join(runtimeDir, file), "PRAGMA integrity_check;"], { encoding: "utf8", timeout: 10000 }).trim(); }
      catch { results[file] = "sqlite3_not_available"; }
    }
  }
  return results;
}

// ─── Child runner ───────────────────────────────────────────────────────

async function runChildAsync({ execPath, args, cwd, env, timeoutMs, stdoutFile, stderrFile, onSpawn }) {
  const { createWriteStream } = require("fs");
  return new Promise((resolve) => {
    const child = spawn(execPath, args, { cwd, env, stdio: ["ignore", "pipe", "pipe"], detached: true });
    let stdout = "", stderr = "", timedOut = false, timer = null;
    let outS = null, errS = null;
    try { outS = createWriteStream(stdoutFile); errS = createWriteStream(stderrFile); } catch {}
    child.stdout?.on("data", (c) => { stdout += c.toString(); outS?.write(c); });
    child.stderr?.on("data", (c) => { stderr += c.toString(); errS?.write(c); });

    let spawnErr = null;
    child.on("error", (err) => {
      spawnErr = err; if (timer) clearTimeout(timer);
      stderr += `\n[child spawn error: ${err.message}]`; outS?.end(); errS?.end();
      resolve({ exitCode: -1, stdout, stderr, timedOut: false, childPid: child.pid || null, spawnError: err.message });
    });
    if (!spawnErr && child.pid && onSpawn) { try { onSpawn(child.pid); } catch {} }

    if (timeoutMs > 0) {
      timer = setTimeout(() => {
        timedOut = true;
        try { if (child.pid) process.kill(-child.pid, "SIGTERM"); } catch {}
        setTimeout(() => { try { if (child.pid && child.exitCode === null) process.kill(-child.pid, "SIGKILL"); } catch {} }, 5000);
      }, timeoutMs);
    }
    child.on("close", (code) => { if (timer) clearTimeout(timer); outS?.end(); errS?.end(); resolve({ exitCode: code, stdout, stderr, timedOut, childPid: child.pid }); });
  });
}

// ─── Lane env ───────────────────────────────────────────────────────────

function buildLaneEnv(baseEnv, lane, iso, aiEnvValues, resumeMode, resumeLocators) {
  return {
    ...baseEnv,
    WORKBENCH_RUNTIME_DIR: iso.runtimeDir, QC_ISOLATED_RUNTIME: "1",
    QC_LANE_KEY: lane.key, QC_INDICATION: lane.indication,
    QC_CLINICALTRIALS_CONDITION_TERM: lane.clinicalTrialsConditionTerm,
    QC_STUDY_PHASE: lane.studyPhase, QC_PRODUCT_NAME: lane.productName,
    QC_ENTRY_MODE: lane.entryMode, QC_DESIGN_PRESSURE: lane.designPressure,
    QC_DESIGN_PRESSURE_LABEL: lane.designPressureLabel,
    QC_INTERVENTION_ROUTE_CLASS: lane.interventionRouteClass,
    QC_STRUCTURED_DESIGN_HINT: JSON.stringify(lane.structuredDesignHint || {}),
    QC_PROJECT_CODE: iso.projectCode, QC_ATTEMPT_ID: iso.attemptId,
    QC_ALLOCATION_ATTEMPT: iso.allocationAttempt || "",
    QC_RUN_ID: iso.runId || "",
    QC_MIN_CHAPTERS: JSON.stringify(lane.minChapters || []),
    QC_TIMEOUT_S: String(lane.timeoutS || 4200),
    QC_OCR_TIMEOUT_S: String(lane.ocrTimeoutS || 600),
    QC_TRANSLATION_TIMEOUT_S: String(lane.translationTimeoutS || 900),
    QC_CANDIDATE_TIMEOUT_S: String(lane.candidateTimeoutS || 900),
    SYNOPSIS_UPLOAD_TIMEOUT_MS: String(lane.synopsisUploadTimeoutMs || 1200000),
    QC_SYNOPSIS_SOURCE_PATH: lane.synopsisSourcePath || "",
    QC_SYNOPSIS_SOURCE_ROLE: lane.synopsisSourceRole || "",
    QC_SYNOPSIS_SOURCE_OVERRIDE_REASON: lane.synopsisSourceOverrideReason || "",
    QC_EXPECTED_NCT_ID: lane.expectedNctId || "",
    QC_EXPECTED_DOCUMENT_FILENAME: lane.expectedDocumentFilename || "",
    QC_EXPECTED_DOCUMENT_ROLE: lane.expectedDocumentRole || "",
    QC_OUTPUT_DIR: iso.evidenceDir, QC_LANE_EVIDENCE_DIR: iso.evidenceDir,
    CHROME_DEBUG_PORT: String(iso.cdpPort), CHROME_PROFILE_DIR: iso.chromeProfileDir,
    APP_URL: iso.appUrl, API_URL: iso.apiBase,
    QC_RESUME_MODE: resumeMode ? "1" : "0",
    QC_RESUME_LOCATORS: resumeLocators ? JSON.stringify(resumeLocators) : "",
    ...(aiEnvValues || {}),
    ...(DRY_RUN ? { QC_DRY_RUN: "1" } : {}),
  };
}

let _stableRuntimeMutated = false;

// ─── Main ───────────────────────────────────────────────────────────────

async function main() {
  if (concurrencyError) { console.error(JSON.stringify({ fatal: concurrencyError })); process.exitCode = 1; return; }
  const coverage = validateLaneCoverage();
  if (!coverage.valid) { console.error(JSON.stringify({ fatal: "coverage_check_failed", missing: coverage.missing })); process.exitCode = 1; return; }
  const selectedLanes = DRY_RUN ? (requestedLanes ? resolveLanes(requestedLanes) : [EXPECTED_STUDIES_12LANE[0]]) : resolveLanes(requestedLanes);
  if (selectedLanes.length === 0) { console.error(JSON.stringify({ fatal: "empty lane selection" })); process.exitCode = 1; return; }

  await mkdir(outputDir, { recursive: true });
  await mkdir(taskRuntimeRoot, { recursive: true });

  const aiEnv = checkAiEnvPresence();
  const aiEnvValues = aiEnv.present ? loadAiEnvValues() : {};
  const stableHasher = new MultiRootStableHash(stableRoots);
  const stableBefore = await stableHasher.snapshotToFile(path.join(outputDir, "stable_runtime_inventory_before.json"));

  const report = {
    schema_version: "mw_e3_parent_v1", mode: DRY_RUN ? "dry-run" : "full",
    started_at: new Date().toISOString(), concurrency: maxConcurrency,
    stableRoots: stableRoots.map((r) => ({ label: r.label, path: r.path })),
    lanesRequested: selectedLanes.map((l) => l.key),
    runtime: {
      isolated: true, perLaneIsolation: true,
      stableRoots: stableRoots.map((r) => ({ label: r.label, path: r.path })),
      stableBeforeAggregateHash: stableBefore.aggregateHash, stableBeforeTotalFiles: stableBefore.totalFileCount,
      stableBeforeIncomplete: stableBefore.incomplete,
      stableBeforeRoots: stableBefore.roots.map((r) => ({ label: r.label, hash: r.canonicalHash, files: r.fileCount, incomplete: r.incomplete })),
      stableAfterAggregateHash: null, stableContentHashUnchanged: null, laneRuntimes: [],
    },
    aiEnvPresent: aiEnv.present, aiEnvKeyNames: aiEnv.keys,
    ctgovSentinelEvidence: { retrieved_at: CTGOV_SENTINEL_EVIDENCE.retrieved_at, source: CTGOV_SENTINEL_EVIDENCE.source },
    sourceSha256: {
      parentHarness: await fileSha256(path.join(scriptDir, "final_release_12lane_parent.mjs")),
      config: await fileSha256(path.join(scriptDir, "final_release_12lane_config.mjs")),
      stableHashHelper: await fileSha256(path.join(scriptDir, "final_release_12lane_stable_hash.mjs")),
      processOwnershipHelper: await fileSha256(path.join(scriptDir, "final_release_12lane_process_ownership.mjs")),
      runtimeIsolationHelper: await fileSha256(path.join(scriptDir, "final_release_12lane_runtime_isolation.mjs")),
    },
    lanes: [], failures: [], stableRuntimeMutated: false,
  };

  const allocations = [];
  for (const lane of selectedLanes) {
    const iso = await allocateLane({ laneKey: lane.key, taskRuntimeRoot, evidenceRoot: outputDir });
    allocations.push({ lane, iso });
  }
  const isoCheck = validateIsolation(allocations.map((a) => a.iso));
  if (!isoCheck.valid) {
    console.error(JSON.stringify({ fatal: "isolation_failed", violations: isoCheck.violations }));
    for (const { iso } of allocations) await releaseLane(iso);
    process.exitCode = 1; return;
  }

  let suiteHalted = false, haltReason = null;
  const { results, incomplete } = await runBoundedConcurrency({
    items: allocations, concurrency: maxConcurrency, shouldStop: () => _stableRuntimeMutated,
    taskFn: async ({ lane, iso }) => {
      try {
        const result = await runLane(lane, iso, aiEnvValues, stableHasher, stableBefore);
        if (result.__haltSuite) { _stableRuntimeMutated = true; suiteHalted = true; haltReason = result.__haltReason; }
        return result;
      } catch (err) {
        return { laneReport: { lane: lane.key, exitCode: -1, exception: err.message, servicesReady: false, runtimeDir: iso.runtimeDir }, failures: [`${lane.key}:exception:${err.message}`], runtimeInfo: { lane: lane.key, runtimeDir: iso.runtimeDir, servicesReady: false } };
      }
    },
  });

  if (incomplete || results.length !== selectedLanes.length)
    report.failures.push(`result_cardinality_mismatch:expected=${selectedLanes.length},got=${results.length}`);

  const stableAfter = await stableHasher.snapshotToFile(path.join(outputDir, "stable_runtime_inventory_after.json"));
  const stableDiff = MultiRootStableHash.diff(stableBefore, stableAfter);
  report.runtime.stableAfterAggregateHash = stableAfter.aggregateHash;
  report.runtime.stableAfterTotalFiles = stableAfter.totalFileCount;
  report.runtime.stableAfterIncomplete = stableAfter.incomplete;
  report.runtime.stableAfterRoots = stableAfter.roots.map((r) => ({ label: r.label, hash: r.canonicalHash, files: r.fileCount, incomplete: r.incomplete }));
  report.runtime.stableContentHashUnchanged = !stableDiff.hasChanges;
  report.runtime.stableDiffSummary = stableDiff.summary;
  if (stableDiff.hasChanges) { report.failures.push(`stable-runtime-content-mutated:${JSON.stringify(stableDiff.changes.slice(0, 20))}`); report.stableRuntimeMutated = true; }
  if (suiteHalted) report.failures.push(`suite-halted:${haltReason}`);

  for (const r of results) {
    if (r.result?.laneReport) report.lanes.push(r.result.laneReport);
    if (r.result?.failures) report.failures.push(...r.result.failures);
    if (r.result?.runtimeInfo) report.runtime.laneRuntimes.push(r.result.runtimeInfo);
  }

  report.completed_at = new Date().toISOString();
  report.suiteHalted = suiteHalted; report.haltReason = haltReason;
  report.laneFailures = report.lanes.filter((l) => l.exitCode !== 0).length;
  report.passed = report.failures.length === 0 && report.laneFailures === 0 && report.runtime.stableContentHashUnchanged && !suiteHalted && results.length === selectedLanes.length;

  // D3: Exit code MUST agree with report.passed
  if (!report.passed) process.exitCode = 1;

  const reportJson = JSON.stringify(report);
  const credPatterns = [/sk-[a-zA-Z0-9]{20,}/g, /(?:api[_-]?key|secret|password|token)\s*[=:]\s*["'][^"']{8,}["']/gi];
  const leaked = credPatterns.flatMap((p) => reportJson.match(p) || []);
  report.credentialLeakageCheck = { scanned: true, leaked: leaked.length === 0 ? "none" : leaked.length, patterns: leaked.length === 0 ? [] : ["redacted"] };

  await atomicWriteFile(path.join(outputDir, "twelve_lane_parent_report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ mode: report.mode, passed: report.passed, failures: report.failures.slice(0, 5), stableContentHashUnchanged: report.runtime.stableContentHashUnchanged, concurrency: report.concurrency, laneCount: report.lanes.length, laneFailures: report.laneFailures, suiteHalted, lanesRun: report.lanes.map((l) => l.lane) }, null, 2));
}

// ─── Per-lane runner ────────────────────────────────────────────────────

async function runLane(lane, iso, aiEnvValues, stableHasher, stableBefore) {
  const failures = [];
  const laneReport = {
    lane: lane.key, entryMode: lane.entryMode, indication: lane.indication,
    studyPhase: lane.studyPhase, designPressure: lane.designPressure,
    interventionRouteClass: lane.interventionRouteClass,
    attemptId: iso.attemptId, projectCode: iso.projectCode,
    servicesReady: false, runtimeDir: iso.runtimeDir, chromeProfileDir: iso.chromeProfileDir,
    evidenceDir: iso.evidenceDir, apiPort: iso.apiPort, vitePort: iso.vitePort, cdpPort: iso.cdpPort,
    exitCode: null, stdoutTail: "", stderrTail: "", artifacts: {},
    sqliteIntegrity: {}, artifactsReadError: null, stableUnchangedDuringLane: null,
    resume: iso.isResume || false, timedOut: false, runtimePreserved: false, childRegisteredWhileAlive: false,
  };

  // D4/D2: checkResume BEFORE any services — uses durable attemptId
  let locatorRejected = false;
  const resumeStatus = await checkResume(lane.key, iso.evidenceDir, iso.projectCode, iso.attemptId);
  if (resumeStatus.rejected) {
    failures.push(`${lane.key}:locator_rejected:malformed_or_mismatched — not starting`);
    locatorRejected = true;
  }

  const resumeMode = !locatorRejected && (resumeStatus.resume || iso.isResume);
  const resumeLocators = !locatorRejected ? (resumeStatus.locators?.locators || null) : null;
  if (resumeMode) { laneReport.resume = true; laneReport.resumedFromAttempt = resumeStatus.attemptId; }

  try {
    if (locatorRejected) {
      laneReport.runtimePreserved = true;
      // Skip services and child — go straight to finally
    } else {
    // ── Release held sockets BEFORE spawn
    releaseHeldPort(iso.apiPort);
    releaseHeldPort(iso.vitePort);
    releaseHeldPort(iso.cdpPort);

    const apiEnv = { ...process.env, WORKBENCH_RUNTIME_DIR: iso.runtimeDir, PYTHONUNBUFFERED: "1", ...(aiEnvValues) };
    const apiSpawn = spawnServicePgid("python3", ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(iso.apiPort)], projectRoot, apiEnv);
    registerProcess({ laneKey: lane.key, role: "api", pid: apiSpawn.pid, executable: "python3", assignedPort: iso.apiPort, runtimeDir: iso.runtimeDir, pgid: apiSpawn.pgid });

    const viteEnv = { ...process.env, VITE_API_PROXY_TARGET: iso.apiBase };
    const viteSpawn = spawnServicePgid("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(iso.vitePort), "--strictPort"], frontendRoot, viteEnv);
    registerProcess({ laneKey: lane.key, role: "vite", pid: viteSpawn.pid, executable: "npm", assignedPort: iso.vitePort, pgid: viteSpawn.pgid });

    let servicesReady = false;
    try {
      // D4/PS-02: deterministic readiness fault injection (dry-run only)
      if (DRY_RUN && process.env.QC_FORCE_READY_FAIL === "1") {
        throw new Error("forced_readiness_failure");
      }
      await waitForApiReady(`${iso.apiBase}/api/health`, apiSpawn.pid, iso.apiPort);
      await waitForViteReady(iso.appUrl, viteSpawn.pid, iso.vitePort);
      servicesReady = true;
    } catch (error) { failures.push(`${lane.key}:service-startup-failed:${error.message}`); }
    laneReport.servicesReady = servicesReady;

    if (servicesReady) {
      // D9: Use test child script in dry-run mode if QC_TEST_CHILD_SCRIPT is set
      const effectiveChildScript = useTestChild ? testChildScript : childScript;
      const childEnv = buildLaneEnv(process.env, lane, iso, aiEnvValues, resumeMode, resumeLocators);
      const stdoutFile = path.join(iso.evidenceDir, "child_stdout.log");
      const stderrFile = path.join(iso.evidenceDir, "child_stderr.log");

      const childResult = await runChildAsync({
        execPath: process.execPath, args: [effectiveChildScript], cwd: projectRoot,
        env: childEnv, timeoutMs: (parseInt(process.env.QC_LANE_TIMEOUT_S, 10) || lane.timeoutS || 4200) * 1000,
        stdoutFile, stderrFile,
        onSpawn: (childPid) => {
          registerProcess({ laneKey: lane.key, role: "child", pid: childPid, executable: process.execPath, childScript: effectiveChildScript, runtimeDir: iso.runtimeDir, pgid: childPid });
          laneReport.childRegisteredWhileAlive = true;
        },
      });

      laneReport.exitCode = childResult.exitCode;
      laneReport.stdoutTail = childResult.stdout.slice(-2000);
      laneReport.stderrTail = childResult.stderr.slice(-2000);
      laneReport.timedOut = childResult.timedOut;
      if (childResult.exitCode !== 0) failures.push(`${lane.key}:child-exit-${childResult.exitCode}`);

      try {
        const ap = path.join(iso.evidenceDir, "lane_artifacts.json");
        if (fsExistsSync(ap)) laneReport.artifacts = JSON.parse(fsReadFileSync(ap, "utf8"));
      } catch (e) { laneReport.artifactsReadError = e.message; }
    }
    } // end else (not locatorRejected)
  } finally {
    // Release any held ports (D7: unified cleanup for all paths)
    releaseHeldPort(iso.apiPort);
    releaseHeldPort(iso.vitePort);
    releaseHeldPort(iso.cdpPort);

    try { await stopLaneProcesses(lane.key); } catch (e) { failures.push(`${lane.key}:cleanup-error:${e.message}`); }
    await new Promise((r) => setTimeout(r, 2000));

    try {
      laneReport.sqliteIntegrity = await sqliteIntegrityCheck(iso.runtimeDir);
      const invalid = Object.entries(laneReport.sqliteIntegrity).filter(([, v]) => v !== "ok");
      if (invalid.length) failures.push(`${lane.key}:sqlite-integrity:${JSON.stringify(invalid)}`);
    } catch (e) { failures.push(`${lane.key}:sqlite-error:${e.message}`); }

    try {
      const stableAfterLane = await stableHasher.snapshotToFile(path.join(iso.evidenceDir, `stable_runtime_inventory_after_lane_${lane.key}.json`));
      const laneDiff = MultiRootStableHash.diff(stableBefore, stableAfterLane);
      laneReport.stableUnchangedDuringLane = !laneDiff.hasChanges;
      if (laneDiff.hasChanges) failures.push(`${lane.key}:stable-runtime-changed:${JSON.stringify(laneDiff.changes.slice(0, 10))}`);
    } catch (e) { failures.push(`${lane.key}:stable-hash-error:${e.message}`); }

    try { await writeOwnershipRecord(lane.key, iso.evidenceDir, [...getAllocationOwnedDirs(lane.key)]); } catch (e) { failures.push(`${lane.key}:ownership-error:${e.message}`); }

    try {
      const inputManifest = {
        schema_version: "mw_e3_input_manifest_v1", laneKey: lane.key, attemptId: iso.attemptId, projectCode: iso.projectCode,
        entryMode: lane.entryMode, indication: lane.indication, studyPhase: lane.studyPhase, designPressure: lane.designPressure,
        synopsisSource: lane.synopsisSourcePath ? { path: lane.synopsisSourcePath, sha256: lane.synopsisSourceSha256, role: lane.synopsisSourceRole } : null,
        runtimeDir: iso.runtimeDir, ports: { api: iso.apiPort, vite: iso.vitePort, cdp: iso.cdpPort },
        chromeProfileDir: iso.chromeProfileDir, resumeMode: laneReport.resume, createdAt: new Date().toISOString(),
      };
      await atomicWriteFile(path.join(iso.evidenceDir, "input_manifest.json"), JSON.stringify(inputManifest, null, 2));
    } catch (e) { failures.push(`${lane.key}:manifest-error:${e.message}`); }

    const anyFailure = failures.length > 0 || (laneReport.exitCode !== null && laneReport.exitCode !== 0) || laneReport.exitCode === null;
    const jobLocatorsExist = fsExistsSync(path.join(iso.evidenceDir, "job_locators.json"));
    let unresolvedFromFile = 0;
    if (jobLocatorsExist) { try { unresolvedFromFile = countUnresolvedLocators(JSON.parse(fsReadFileSync(path.join(iso.evidenceDir, "job_locators.json"), "utf8"))); } catch { unresolvedFromFile = 1; } }
    const shouldPreserve = anyFailure || laneReport.timedOut || unresolvedFromFile > 0;
    laneReport.runtimePreserved = shouldPreserve;

    if (process.env.PRESERVE_QC_RUNTIME !== "1" && !shouldPreserve) {
      try { await cleanupAllocation(iso); } catch (e) { failures.push(`${lane.key}:cleanup-dirs-error:${e.message}`); }
    }
    try { await releaseLane(iso); } catch {}
  }

  const haltSuite = laneReport.stableUnchangedDuringLane === false;
  return {
    laneReport, failures,
    runtimeInfo: { lane: lane.key, attemptId: iso.attemptId, runtimeDir: iso.runtimeDir, apiPort: iso.apiPort, vitePort: iso.vitePort, cdpPort: iso.cdpPort, chromeProfileDir: iso.chromeProfileDir, servicesReady: laneReport.servicesReady, resume: laneReport.resume, childRegisteredWhileAlive: laneReport.childRegisteredWhileAlive, runtimePreserved: laneReport.runtimePreserved },
    ...(haltSuite ? { __haltSuite: true, __haltReason: `${lane.key}:stable-runtime-mutation` } : {}),
  };
}

main().then(() => { process.exit(process.exitCode || 0); }).catch((error) => { console.error(error.stack || error.message); process.exit(1); });
