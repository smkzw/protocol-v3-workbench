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
const childScript = path.join(scriptDir, "medical_writing_new_project_qc.mjs");
const baselineScript = path.join(projectRoot, "scripts/qc/mw_isolated_runtime_baseline.py");
const outputDir = process.env.QC_OUTPUT_DIR || path.join(
  projectRoot,
  "records/active_slices/medical_writing_authoring_journey_20260715/browser_qc/new_project_isolated",
);
const stableRuntimeDir = process.env.STABLE_RUNTIME_DIR || path.resolve(projectRoot, "../..", "runtime");
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function freePort(preferred) {
  const tryPort = (port) => new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      const selected = server.address().port;
      server.close(() => resolve(selected));
    });
  });
  try {
    return preferred ? await tryPort(Number(preferred)) : await tryPort(0);
  } catch {
    return tryPort(0);
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
      const response = await fetch(url);
      if (response.ok) return;
      lastError = new Error(`${response.status}: ${url}`);
    } catch (error) {
      lastError = error;
    }
    await wait(250);
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

async function fileSha256(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

function prepareIsolatedAiBaseline(runtimeDir, testRoot) {
  const result = spawnSync(
    process.env.PYTHON_BIN || "python3",
    [baselineScript, "prepare", "--target", runtimeDir, "--test-target-root", testRoot],
    {
      cwd: projectRoot,
      encoding: "utf8",
      maxBuffer: 4 * 1024 * 1024,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    },
  );
  if (result.status !== 0) {
    throw new Error(`isolated AI baseline preparation failed: ${result.stderr || result.stdout || result.status}`);
  }
  return JSON.parse(result.stdout);
}

async function directorySnapshot(root) {
  const snapshot = {};
  async function visit(current) {
    let entries = [];
    try {
      entries = await readdir(current, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
      const absolute = path.join(current, entry.name);
      if (entry.isDirectory()) await visit(absolute);
      else if (entry.isFile()) {
        const metadata = await stat(absolute);
        snapshot[path.relative(root, absolute)] = {
          bytes: metadata.size,
          sha256: await fileSha256(absolute),
        };
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

async function main() {
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const runtimeRoot = await mkdtemp(path.join(await realpath(tmpdir()), "mw-new-project-runtime-root-"));
  const runtimeDir = path.join(runtimeRoot, "runtime");
  const baseline = prepareIsolatedAiBaseline(runtimeDir, runtimeRoot);
  const apiPort = await freePort(process.env.QC_API_PORT || 8932);
  const vitePort = await freePort(process.env.QC_VITE_PORT || 5192);
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;
  const stableBefore = await directorySnapshot(stableRuntimeDir);
  const api = startService(
    process.env.PYTHON_BIN || "python3",
    ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)],
    {
      cwd: projectRoot,
      env: {
        ...process.env,
        WORKBENCH_RUNTIME_DIR: runtimeDir,
        WORKBENCH_RUNTIME_DIR_SHA256: createHash("sha256").update(runtimeDir).digest("hex"),
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
    runtime: { isolated: true, runtimeRoot, runtimeDir, baseline, stableRuntimeDir, stableBefore, stableAfter: {}, stableUnchanged: false },
    sourceSha256: {
      app: await fileSha256(path.join(frontendRoot, "src/App.jsx")),
      authoringJourney: await fileSha256(path.join(frontendRoot, "src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx")),
      backend: await fileSha256(path.join(projectRoot, "services/api/app/main.py")),
      childQc: await fileSha256(childScript),
    },
    results: [],
    failures: [],
  };
  try {
    await waitForHttp(`${apiBase}/api/health`);
    await waitForHttp(appUrl);
    for (const [index, entryMode] of ["from_zero", "synopsis_import"].entries()) {
      const caseOutputDir = path.join(outputDir, entryMode);
      await mkdir(caseOutputDir, { recursive: true });
      const run = spawnSync(process.execPath, [childScript], {
        cwd: projectRoot,
        encoding: "utf8",
        timeout: 180000,
        maxBuffer: 16 * 1024 * 1024,
        env: {
          ...process.env,
          APP_URL: appUrl,
          API_URL: apiBase,
          QC_ISOLATED_RUNTIME: "1",
          QC_ENTRY_MODE: entryMode,
          QC_PROJECT_CODE: `QC-RA-${entryMode}-${Date.now()}-${index}`,
          QC_OUTPUT_DIR: caseOutputDir,
          CHROME_DEBUG_PORT: String(await freePort(9550 + index)),
        },
      });
      if (run.status !== 0) {
        report.failures.push(`${entryMode}:${run.stderr || run.stdout || run.status}`);
        continue;
      }
      report.results.push(JSON.parse(await readFile(path.join(caseOutputDir, "new_project_report.json"), "utf8")));
    }
    report.runtime.sqliteIntegrity = sqliteIntegrity(runtimeDir);
    const invalidDatabases = Object.entries(report.runtime.sqliteIntegrity).filter(([, value]) => value !== "ok");
    if (invalidDatabases.length) report.failures.push(`sqlite-integrity:${JSON.stringify(invalidDatabases)}`);
  } finally {
    await stopService(vite);
    await stopService(api);
    report.runtime.apiLogTail = api.output.slice(-80);
    report.runtime.viteLogTail = vite.output.slice(-40);
    report.runtime.stableAfter = await directorySnapshot(stableRuntimeDir);
    report.runtime.stableUnchanged = JSON.stringify(stableBefore) === JSON.stringify(report.runtime.stableAfter);
    if (!report.runtime.stableUnchanged) report.failures.push("stable-runtime-changed-during-isolated-qc");
    if (process.env.PRESERVE_QC_RUNTIME !== "1") {
      await rm(runtimeRoot, { recursive: true, force: true });
      report.runtime.runtimeRemoved = true;
    } else {
      report.runtime.runtimeRemoved = false;
    }
  }
  report.passed = report.failures.length === 0 && report.results.length === 2 && report.results.every((item) => item.passed);
  await writeFile(path.join(outputDir, "medical_writing_new_project_isolated_qc.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: report.passed, failures: report.failures, results: report.results }, null, 2));
  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
