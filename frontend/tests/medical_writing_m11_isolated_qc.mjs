import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, realpath, rm, stat, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const childScript = path.join(scriptDir, "medical_writing_m11_registry_qc.mjs");
const baselineScript = path.join(projectRoot, "scripts/qc/mw_isolated_runtime_baseline.py");
const stableRuntimeDir = process.env.STABLE_RUNTIME_DIR || path.resolve(projectRoot, "../..", "runtime");
const outputDir = process.env.QC_OUTPUT_DIR || path.join(projectRoot, "records/active_slices/medical_writing_authoring_journey_20260715/browser_qc/m11_isolated");
const API_CONTRACT_HEADERS = { "X-Workbench-Api-Contract": "medical-writing-api-2026-07-17.1" };
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function freePort(preferred) {
  const probe = (port) => new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      const selected = server.address().port;
      server.close(() => resolve(selected));
    });
  });
  try {
    return preferred ? await probe(Number(preferred)) : await probe(0);
  } catch {
    return probe(0);
  }
}

function startService(command, args, options) {
  const output = [];
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
  const collect = (chunk) => {
    output.push(String(chunk));
    if (output.length > 300) output.shift();
  };
  child.stdout.on("data", collect);
  child.stderr.on("data", collect);
  return { child, output };
}

async function stopService(service) {
  if (!service?.child || service.child.exitCode !== null) return;
  const exited = new Promise((resolve) => service.child.once("exit", resolve));
  service.child.kill("SIGTERM");
  await Promise.race([exited, wait(5000)]);
  if (service.child.exitCode === null) service.child.kill("SIGKILL");
}

async function waitForHttp(url, timeoutMs = 120000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url, { headers: API_CONTRACT_HEADERS });
      if (response.ok) return;
      lastError = new Error(`${response.status}: ${url}`);
    } catch (error) {
      lastError = error;
    }
    await wait(250);
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
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

async function createProject(apiBase) {
  const projectCode = `QC-M11-${Date.now()}`;
  const response = await fetch(`${apiBase}/api/projects`, {
    method: "POST",
    headers: { ...API_CONTRACT_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({
      project_code: projectCode,
      project_name: "类风湿关节炎II期研究方案 M11 隔离验收",
      indication: "类风湿关节炎",
      product_name: "CMS-RA-201",
      study_phase: "II期",
      protocol_id: projectCode,
      protocol_version: "V0.1",
      entry_mode: "from_zero",
      actor: "medical_manager_qc",
      idempotency_key: `m11-isolated-project-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.project?.project_id) throw new Error(`project create failed: ${response.status} ${JSON.stringify(payload)}`);
  return { project: payload.project, responseStatus: response.status };
}

async function main() {
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const runtimeRoot = await mkdtemp(path.join(await realpath(tmpdir()), "mw-m11-runtime-root-"));
  const runtimeDir = path.join(runtimeRoot, "runtime");
  const baseline = prepareBaseline(runtimeDir, runtimeRoot);
  const apiPort = await freePort(process.env.QC_API_PORT || 8942);
  const vitePort = await freePort(process.env.QC_VITE_PORT || 5202);
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;
  const stableBefore = await directorySnapshot(stableRuntimeDir);
  const runtimeHash = createHash("sha256").update(runtimeDir).digest("hex");
  const api = startService(
    process.env.PYTHON_BIN || "python3",
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
  const vite = startService(
    process.env.NPM_BIN || "npm",
    ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"],
    { cwd: frontendRoot, env: { ...process.env, VITE_API_PROXY_TARGET: apiBase } },
  );
  const report = {
    passed: false,
    appUrl,
    apiBase,
    project: null,
    child: { status: null, stdoutTail: [], stderrTail: [] },
    runtime: { isolated: true, runtimeRoot, runtimeDir, baseline, stableRuntimeDir, stableBefore, stableAfter: {}, stableUnchanged: false, sqliteIntegrity: {} },
    failures: [],
  };
  try {
    await waitForHttp(`${apiBase}/api/health`);
    await waitForHttp(`${apiBase}/api/runtime-readiness`);
    await waitForHttp(appUrl);
    const created = await createProject(apiBase);
    report.project = { projectId: created.project.project_id, projectCode: created.project.project_code, responseStatus: created.responseStatus };
    const childOutputDir = path.join(outputDir, "child");
    await mkdir(childOutputDir, { recursive: true });
    const child = spawnSync(process.execPath, [childScript], {
      cwd: projectRoot,
      encoding: "utf8",
      timeout: process.env.RUN_REAL_AI === "1" ? 900000 : 420000,
      maxBuffer: 32 * 1024 * 1024,
      env: {
        ...process.env,
        APP_URL: appUrl,
        API_BASE: apiBase,
        GREENFIELD_PROJECT_ID: created.project.project_id,
        SKIP_REFERENCE_PROJECT: "1",
        QC_OUTPUT_DIR: childOutputDir,
        CHROME_DEBUG_PORT: String(await freePort(9652)),
      },
    });
    report.child.status = child.status;
    report.child.stdoutTail = String(child.stdout || "").split("\n").slice(-80);
    report.child.stderrTail = String(child.stderr || "").split("\n").slice(-80);
    if (report.project?.projectId) {
      try {
        const sessionResponse = await fetch(
          `${apiBase}/api/projects/${report.project.projectId}/medical-writing/document-session`,
          { headers: API_CONTRACT_HEADERS },
        );
        const sessionPayload = await sessionResponse.json().catch(() => ({}));
        report.child.postRunSession = {
          responseStatus: sessionResponse.status,
          documentId: sessionPayload.document_id || null,
          status: sessionPayload.status || null,
          sectionCount: Array.isArray(sessionPayload.sections) ? sessionPayload.sections.length : null,
          templateId: sessionPayload.template_id || null,
          templateVersion: sessionPayload.template_version || null,
        };
      } catch (error) {
        report.child.postRunSessionError = error.message;
      }
    }
    if (child.status !== 0) report.failures.push(`child-exit:${child.status}`);
    const childReportPath = path.join(childOutputDir, "qc_report.json");
    try {
      report.child.report = JSON.parse(await readFile(childReportPath, "utf8"));
      if (report.child.report.failures?.length) report.failures.push(...report.child.report.failures.map((item) => `child:${item}`));
    } catch (error) {
      report.failures.push(`child-report:${error.message}`);
    }
  } catch (error) {
    report.failures.push(`runner:${error.stack || error.message}`);
  } finally {
    await stopService(vite);
    await stopService(api);
    report.runtime.apiLogTail = api.output.slice(-100);
    report.runtime.viteLogTail = vite.output.slice(-60);
    report.runtime.sqliteIntegrity = sqliteIntegrity(runtimeDir);
    const invalid = Object.entries(report.runtime.sqliteIntegrity).filter(([, value]) => value !== "ok");
    if (invalid.length) report.failures.push(`sqlite-integrity:${JSON.stringify(invalid)}`);
    report.runtime.stableAfter = await directorySnapshot(stableRuntimeDir);
    report.runtime.stableUnchanged = JSON.stringify(report.runtime.stableBefore) === JSON.stringify(report.runtime.stableAfter);
    if (!report.runtime.stableUnchanged) report.failures.push("stable-runtime-changed-during-isolated-m11-qc");
    if (process.env.PRESERVE_QC_RUNTIME !== "1") {
      await rm(runtimeRoot, { recursive: true, force: true });
      report.runtime.runtimeRemoved = true;
    } else report.runtime.runtimeRemoved = false;
  }
  report.passed = report.failures.length === 0 && report.child?.report?.failures?.length === 0 && report.child?.status === 0;
  await writeFile(path.join(outputDir, "medical_writing_m11_isolated_qc.json"), JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify({ passed: report.passed, project: report.project, failures: report.failures, childReport: report.child.report?.greenfield || null }, null, 2));
  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
