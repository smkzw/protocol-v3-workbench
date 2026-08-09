// Final-matrix orchestrator: runs scenarios serially with clean isolated runtimes.
// Usage: node frontend/tests/final_matrix_orchestrator.mjs [scenarioId|all] [--role=engineer|manager] [--round=1|2]
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, realpath, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SCENARIOS, ROUND1_IDS, ROUND2_IDS } from "./final_matrix_scenarios.mjs";
import { runChildWithTimeout, terminateProcessGroup } from "./final_matrix_process.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const childScript = path.join(scriptDir, "final_matrix_child_qc.mjs");
const baselineScript = path.join(projectRoot, "scripts/qc/mw_isolated_runtime_baseline.py");
const stableRuntimeDir = process.env.STABLE_RUNTIME_DIR || path.resolve(projectRoot, "../..", "runtime");
const evidenceRoot = process.env.QC_OUTPUT_DIR || path.join(projectRoot, "records/active_slices/medical_writing_authoring_journey_20260715/browser_qc/final_matrix_20260802");
const API_CONTRACT_HEADERS = { "X-Workbench-Api-Contract": "medical-writing-api-2026-07-17.1" };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function freePort(preferred) {
  const probe = (port) => new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => { const p = server.address().port; server.close(() => resolve(p)); });
  });
  try { return preferred ? await probe(Number(preferred)) : await probe(0); }
  catch { return probe(0); }
}

function startService(command, args, options) {
  const child = spawn(command, args, { ...options, detached: true, stdio: ["ignore", "pipe", "pipe"] });
  const output = [];
  child.stdout?.on("data", (d) => output.push(d.toString()));
  child.stderr?.on("data", (d) => output.push(d.toString()));
  return { child, output, kill: () => terminateProcessGroup(child.pid, "SIGTERM") };
}

async function waitForHttp(url, timeoutMs = 120000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try { const r = await fetch(url); if (r.ok) return; } catch {}
    await wait(1000);
  }
  throw new Error(`Timeout waiting for ${url}`);
}

function prepareBaseline(runtimeDir, testRoot) {
  const result = spawnSync(
    process.env.PYTHON_BIN || "python3",
    [baselineScript, "prepare", "--target", runtimeDir, "--test-target-root", testRoot],
    { cwd: projectRoot, encoding: "utf8", maxBuffer: 4 * 1024 * 1024, env: { ...process.env, PYTHONUNBUFFERED: "1" } },
  );
  if (result.status !== 0) throw new Error(`isolated baseline failed: ${result.stderr || result.stdout || result.status}`);
  return JSON.parse(result.stdout);
}

async function directorySnapshot(root) {
  const snapshot = {};
  async function visit(current) {
    let entries = [];
    try { entries = await readdir(current, { withFileTypes: true }); } catch { return; }
    for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
      const absolute = path.join(current, entry.name);
      if (entry.isDirectory()) await visit(absolute);
      else if (entry.isFile()) {
        const data = await readFile(absolute);
        snapshot[path.relative(root, absolute)] = { bytes: data.length, sha256: createHash("sha256").update(data).digest("hex") };
      }
    }
  }
  await visit(root);
  return snapshot;
}

function sqliteIntegrity(runtimeDir) {
  const find = spawnSync("find", [runtimeDir, "-maxdepth", "1", "-name", "*.sqlite3", "-print"], { encoding: "utf8" });
  return Object.fromEntries(find.stdout.trim().split("\n").filter(Boolean).map((filePath) => {
    const check = spawnSync("sqlite3", [filePath, "PRAGMA integrity_check;"], { encoding: "utf8" });
    return [path.basename(filePath), check.status === 0 ? check.stdout.trim() : check.stderr.trim()];
  }));
}

async function createProject(apiBase, scenario) {
  const projectCode = `${scenario.projectCode}-${Date.now()}`;
  const response = await fetch(`${apiBase}/api/projects`, {
    method: "POST",
    headers: { ...API_CONTRACT_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({
      project_code: projectCode,
      project_name: scenario.projectName,
      indication: scenario.indication,
      product_name: scenario.product,
      study_phase: scenario.phase,
      protocol_id: scenario.protocolId,
      protocol_version: "V0.1",
      entry_mode: "from_zero",
      actor: "final_matrix_qc",
      idempotency_key: `fm-${scenario.id}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.project?.project_id) throw new Error(`Project create failed: ${response.status} ${JSON.stringify(payload).slice(0, 300)}`);
  return payload.project;
}

async function runScenario(scenarioId, role) {
  const scenario = SCENARIOS[scenarioId];
  if (!scenario) throw new Error(`Unknown scenario: ${scenarioId}`);
  const scenarioOutputDir = path.join(evidenceRoot, `${role}_r${scenario.round}`, scenarioId);
  await rm(scenarioOutputDir, { recursive: true, force: true });
  await mkdir(scenarioOutputDir, { recursive: true });

  const runtimeRoot = await mkdtemp(path.join(await realpath(tmpdir()), `fm-${scenarioId}-${role}-`));
  const runtimeDir = path.join(runtimeRoot, "runtime");
  const baseline = prepareBaseline(runtimeDir, runtimeRoot);
  const apiPort = await freePort(0);
  const vitePort = await freePort(0);
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;
  const stableBefore = await directorySnapshot(stableRuntimeDir);
  const runtimeHash = createHash("sha256").update(runtimeDir).digest("hex");

  const api = startService(process.env.PYTHON_BIN || "python3",
    ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)],
    {
      cwd: projectRoot,
      env: {
        ...process.env,
        WORKBENCH_RUNTIME_DIR: runtimeDir,
        WORKBENCH_RUNTIME_DIR_SHA256: runtimeHash,
        WORKBENCH_INCLUDE_REFERENCE_PROJECTS: "false",
        WORKBENCH_CLIENT_CONTRACT_MODE: "enforce",
        PYTHONUNBUFFERED: "1",
      },
    },
  );
  const vite = startService(process.env.NPM_BIN || "npm",
    ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"],
    { cwd: frontendRoot, env: { ...process.env, VITE_API_PROXY_TARGET: apiBase } },
  );

  const result = { scenarioId, role, passed: false, failures: [], projectId: null };
  try {
    await waitForHttp(`${apiBase}/api/health`);
    await waitForHttp(`${apiBase}/api/runtime-readiness`);
    await waitForHttp(appUrl);
    let project = null;
    if (process.env.REAL_USER_FLOW !== "1") {
      project = await createProject(apiBase, scenario);
      result.projectId = project.project_id;
    }

    const child = await runChildWithTimeout(process.execPath, [childScript], {
      cwd: projectRoot,
      // Keep the production-like 30-minute ceiling by default, but allow a
      // focused diagnostic run to fail faster after it has persisted its
      // terminal browser evidence. Matrix routes can raise this explicitly.
      env: {
        ...process.env,
        APP_URL: appUrl,
        API_BASE: apiBase,
        GREENFIELD_PROJECT_ID: project?.project_id || "",
        REAL_USER_FLOW: process.env.REAL_USER_FLOW || "0",
        SCENARIO_ID: scenarioId,
        MATRIX_ROLE: role,
        QC_OUTPUT_DIR: scenarioOutputDir,
        CHROME_DEBUG_PORT: String(await freePort(0)),
        SKIP_REFERENCE_PROJECT: "1",
      },
    }, Number(process.env.CHILD_TIMEOUT_MS || (process.env.RUN_REAL_AI === "1" ? 1_800_000 : 420000)));
    result.childStatus = child.status;
    result.childSignal = child.signal;
    result.childTimedOut = Boolean(child.timedOut);
    result.childTimeoutSignal = child.timeoutSignal || null;
    result.childStdoutTail = String(child.stdout || "").split("\n").slice(-30);
    result.childStderrTail = String(child.stderr || "").split("\n").slice(-30);
    if (child.status !== 0) result.failures.push(`child-exit:${child.status}`);
    if (child.timedOut) result.failures.push(`child-timeout:${child.timeoutSignal || "SIGTERM"}`);

    // Read child report
    try {
      const reportPath = path.join(scenarioOutputDir, `${scenarioId}_${role}_qc_report.json`);
      const childReport = JSON.parse(await readFile(reportPath, "utf8"));
      result.childReport = childReport;
      if (childReport.failures?.length) result.failures.push(...childReport.failures.map((f) => `child:${f}`));
    } catch (e) {
      result.failures.push(`child-report:${e.message}`);
    }
  } catch (error) {
    result.failures.push(`runner:${error.message}`);
  } finally {
    vite.kill();
    api.kill();
    await wait(1000);
    // Preserve service diagnostics in the disposable scenario evidence. This
    // is intentionally harness-only: it makes a transient post-AI readback
    // stall auditable without changing the product runtime or stable logs.
    await writeFile(path.join(scenarioOutputDir, "api_service.log"), api.output.join(""), "utf8");
    await writeFile(path.join(scenarioOutputDir, "vite_service.log"), vite.output.join(""), "utf8");
    result.sqliteIntegrity = sqliteIntegrity(runtimeDir);
    const invalid = Object.entries(result.sqliteIntegrity).filter(([, v]) => v !== "ok");
    if (invalid.length) result.failures.push(`sqlite:${JSON.stringify(invalid)}`);
    const stableAfter = await directorySnapshot(stableRuntimeDir);
    result.stableUnchanged = JSON.stringify(stableBefore) === JSON.stringify(stableAfter);
    if (!result.stableUnchanged) result.failures.push("stable-runtime-changed");
    // Preserve runtime for evidence
    result.runtimeRoot = runtimeRoot;
  }
  result.passed = result.failures.length === 0;
  await writeFile(path.join(scenarioOutputDir, `${scenarioId}_${role}_orchestrator.json`), JSON.stringify(result, null, 2), "utf8");
  return result;
}

// --- CLI ---
const args = process.argv.slice(2);
const roleArg = args.find((a) => a.startsWith("--role="))?.split("=")[1] || "engineer";
const roundArg = args.find((a) => a.startsWith("--round="))?.split("=")[1] || null;
const scenarioArg = args.find((a) => !a.startsWith("--")) || "all";

let scenarioIds;
if (scenarioArg === "all") {
  scenarioIds = roundArg === "1" ? ROUND1_IDS : roundArg === "2" ? ROUND2_IDS : [...ROUND1_IDS, ...ROUND2_IDS];
} else {
  scenarioIds = [scenarioArg];
}

await mkdir(evidenceRoot, { recursive: true });
const results = [];
for (const id of scenarioIds) {
  console.log(`\n=== Running ${id} / ${roleArg} ===`);
  const r = await runScenario(id, roleArg);
  results.push(r);
  console.log(JSON.stringify({ scenarioId: id, role: roleArg, passed: r.passed, failures: r.failures }, null, 2));
}

const summaryPath = path.join(evidenceRoot, `${roleArg}_summary.json`);
await writeFile(summaryPath, JSON.stringify({ role: roleArg, results, timestamp: new Date().toISOString() }, null, 2), "utf8");
console.log(`\nSummary: ${summaryPath}`);
const allPassed = results.every((r) => r.passed);
console.log(`Overall: ${allPassed ? "PASS" : "FAIL"}`);
if (!allPassed) process.exitCode = 1;
