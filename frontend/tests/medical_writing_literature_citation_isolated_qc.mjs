import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { access, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const childScript = path.join(scriptDir, "medical_writing_literature_citation_qc.mjs");
const outputDir = process.env.QC_OUTPUT_DIR
  || path.join(
    projectRoot,
    "records/active_slices/medical_writing_editor_references_20260715/browser_qc/isolated",
  );
const stableRuntimeDir = process.env.STABLE_RUNTIME_DIR
  || path.resolve(projectRoot, "../..", "runtime");

const cases = [
  {
    projectId: "proj_rux_03_002",
    sectionId: "mwsec_proj_rux_03_002_8783a740fc05_c848ed4d86b7",
    targetBlockId: "mwblock_mwsec_proj_rux_03_002_8783a740fc05_c848ed4d86b7_bf5c2fa8e722",
    doi: "10.1016/j.jaad.2021.04.085",
    expectedTitleTerms: "ruxolitinib|atopic dermatitis",
  },
  {
    projectId: "proj_my008_pnh_3_01",
    sectionId: "mwsec_proj_my008_pnh_3_01_265858e23249_a8ae2e9a5150",
    targetBlockId: "mwblock_mwsec_proj_my008_pnh_3_01_265858e23249_a8ae2e9a5150_ec2e09c70cb1",
    doi: "10.1182/blood.2021011388",
    expectedTitleTerms: "danicopan|paroxysmal nocturnal hemoglobinuria|eculizumab",
  },
];

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
  if (preferred) {
    try {
      return await tryPort(Number(preferred));
    } catch {
      // Use an OS-assigned port when the preferred QC port is occupied.
    }
  }
  return tryPort(0);
}

function startService(command, args, options) {
  const output = [];
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
  const collect = (chunk) => {
    output.push(String(chunk));
    if (output.length > 200) output.shift();
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
      if (response.ok) return response;
      lastError = new Error(`${response.status}: ${url}`);
    } catch (error) {
      lastError = error;
    }
    await wait(250);
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

async function sha256File(filePath) {
  try {
    await access(filePath);
  } catch {
    return "missing";
  }
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

async function stableRuntimeSnapshot() {
  const names = [
    "workbench_runtime.sqlite3",
    "medical_writing_literature.sqlite3",
    "medical_writing_greenfield.sqlite3",
  ];
  return Object.fromEntries(await Promise.all(names.map(async (name) => (
    [name, await sha256File(path.join(stableRuntimeDir, name))]
  ))));
}

function sqliteIntegrity(runtimeDir) {
  const files = spawnSync("find", [runtimeDir, "-maxdepth", "1", "-name", "*.sqlite3", "-print"], {
    encoding: "utf8",
  }).stdout.trim().split("\n").filter(Boolean);
  return Object.fromEntries(files.map((filePath) => {
    const check = spawnSync("sqlite3", [filePath, "PRAGMA integrity_check;"], { encoding: "utf8" });
    return [path.basename(filePath), check.status === 0 ? check.stdout.trim() : check.stderr.trim()];
  }));
}

async function main() {
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const runtimeDir = await mkdtemp(path.join(tmpdir(), "mw-citation-runtime-"));
  const apiPort = await freePort(process.env.QC_API_PORT || 8931);
  const vitePort = await freePort(process.env.QC_VITE_PORT || 5191);
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;
  const stableBefore = await stableRuntimeSnapshot();
  const api = startService(
    process.env.PYTHON_BIN || "python3",
    ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)],
    {
      cwd: projectRoot,
      env: { ...process.env, WORKBENCH_RUNTIME_DIR: runtimeDir, PYTHONUNBUFFERED: "1" },
    },
  );
  const vite = startService(
    process.env.NPM_BIN || "npm",
    ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"],
    {
      cwd: frontendRoot,
      env: { ...process.env, VITE_API_PROXY_TARGET: apiBase },
    },
  );
  const report = {
    passed: false,
    appUrl,
    apiBase,
    runtime: {
      isolated: true,
      runtimeDir,
      stableRuntimeDir,
      stableBefore,
      stableAfter: {},
      stableUnchanged: false,
      sqliteIntegrity: {},
    },
    results: [],
    failures: [],
  };
  try {
    await waitForHttp(`${apiBase}/api/health`);
    await waitForHttp(appUrl);
    for (let index = 0; index < cases.length; index += 1) {
      const item = cases[index];
      const debugPort = await freePort(9540 + index);
      const run = spawnSync(process.execPath, [childScript], {
        cwd: projectRoot,
        encoding: "utf8",
        timeout: 240000,
        maxBuffer: 16 * 1024 * 1024,
        env: {
          ...process.env,
          APP_URL: appUrl,
          QC_ISOLATED_RUNTIME: "1",
          QC_OUTPUT_DIR: outputDir,
          CHROME_DEBUG_PORT: String(debugPort),
          QC_PROJECT_ID: item.projectId,
          QC_SECTION_ID: item.sectionId,
          QC_TARGET_BLOCK_ID: item.targetBlockId,
          QC_DOI: item.doi,
          QC_EXPECTED_TITLE_TERMS: item.expectedTitleTerms,
        },
      });
      if (run.status !== 0) {
        report.failures.push(`${item.projectId}: ${run.stderr || run.stdout || run.status}`);
        continue;
      }
      const resultPath = path.join(
        outputDir,
        `medical_writing_literature_citation_${item.projectId}_qc.json`,
      );
      report.results.push(JSON.parse(await readFile(resultPath, "utf8")));
    }
    report.runtime.sqliteIntegrity = sqliteIntegrity(runtimeDir);
    const badIntegrity = Object.entries(report.runtime.sqliteIntegrity)
      .filter(([, value]) => value !== "ok");
    if (badIntegrity.length) report.failures.push(`sqlite-integrity:${JSON.stringify(badIntegrity)}`);
  } finally {
    await stopService(vite);
    await stopService(api);
    report.runtime.stableAfter = await stableRuntimeSnapshot();
    report.runtime.stableUnchanged = (
      JSON.stringify(report.runtime.stableBefore) === JSON.stringify(report.runtime.stableAfter)
    );
    if (!report.runtime.stableUnchanged) {
      report.failures.push("stable-runtime-changed-during-isolated-qc");
    }
    if (process.env.PRESERVE_QC_RUNTIME !== "1") {
      await rm(runtimeDir, { recursive: true, force: true });
      report.runtime.runtimeRemoved = true;
    } else {
      report.runtime.runtimeRemoved = false;
    }
  }
  report.passed = report.failures.length === 0
    && report.results.length === cases.length
    && report.results.every((item) => item.passed);
  await writeFile(
    path.join(outputDir, "medical_writing_literature_citation_isolated_qc.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
