/**
 * Parent harness for the cross-indication E2E gate (Round 4).
 *
 * Modes:
 *   --dry-run   Start real API + frontend on random ports with an isolated
 *               temporary runtime.  Create exactly one disposable project
 *               through the UI.  Verify core reference-workspace route and
 *               selector contracts.  Stop BEFORE any ClinicalTrials.gov
 *               search, download, or production AI.  Prove stable runtime
 *               hashes are unchanged.  Remove temp runtime.
 *
 *   (default)   Full four-indication run: AD, PNH, obesity, and SLE Phase 1b.
 *
 * Lifecycle:
 *   1. Load the production AI environment file
 *      ($HOME/.config/cms-medical-workbench/ai-runtime.env) into the child
 *      service environments WITHOUT printing credential values.  Record only
 *      the presence of each required key.
 *   2. Allocate random free ports for API, Vite, and CDP.
 *   3. Create a temporary runtime directory and point the API at it.
 *   4. Snapshot the stable runtime directory (every SQLite + WAL/SHM and
 *      immutable files) before and after; fail if anything changed.
 *   5. Start the API and Vite on the isolated ports.
 *   6. In dry-run: drive the child once in DRY_RUN=1 mode.
 *      In full mode: spawn the child once per indication
 *      (AD → PNH → obesity → SLE Phase 1b).
 *   7. Aggregate per-lane artifacts.
 *   8. Run PRAGMA integrity_check on every isolated SQLite file.
 *   9. Remove the temporary runtime and Chrome user-data directories unless
 *      PRESERVE_QC_RUNTIME=1.
 *
 * Stable 5174/8911 is never written.  The stable runtime directory is
 * read-only for this harness.
 */

import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync as fsExistsSync, readFileSync as fsReadFileSync } from "node:fs";
import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { EXPECTED_STUDIES, ARTIFACT_FILENAMES, GATE_CODES, STABLE_RUNTIME_RELATIVE } from "./cross_indication_e2e_config.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const childScript = path.join(scriptDir, "cross_indication_e2e_child.mjs");
const outputDir = process.env.QC_OUTPUT_DIR || path.join(
  projectRoot,
  "runs/execution/mw_cross_indication_reference_release_gate_20260718/cross_indication_e2e_run",
);
const stableRuntimeDir =
  process.env.STABLE_RUNTIME_DIR || path.resolve(projectRoot, STABLE_RUNTIME_RELATIVE, "runtime");

const DRY_RUN = process.argv.includes("--dry-run");
const laneArgument = process.argv.find((argument) => argument.startsWith("--lane="));
const requestedLane = (
  laneArgument?.slice("--lane=".length) ||
  process.env.QC_ONLY_INDICATION ||
  ""
).trim().toUpperCase();
const selectedStudies = requestedLane
  ? EXPECTED_STUDIES.filter((study) => study.key === requestedLane)
  : EXPECTED_STUDIES;
if (!DRY_RUN && requestedLane && selectedStudies.length !== 1) {
  throw new Error(`unknown cross-indication lane: ${requestedLane}`);
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function freePort(preferred) {
  const tryPort = (port) =>
    new Promise((resolve, reject) => {
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
    if (output.length > 400) output.shift();
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
  const find = spawnSync("find", [runtimeDir, "-maxdepth", "1", "-name", "*.sqlite3", "-print"], {
    encoding: "utf8",
  });
  return Object.fromEntries(
    find.stdout
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((filePath) => {
        const check = spawnSync("sqlite3", [filePath, "PRAGMA integrity_check;"], {
          encoding: "utf8",
        });
        return [path.basename(filePath), check.status === 0 ? check.stdout.trim() : check.stderr.trim()];
      }),
  );
}

/**
 * Load the production AI environment file and return a sanitised presence map.
 * Never returns values — only whether each key is present and non-empty.
 */
function loadAiRuntimeEnv() {
  const envPath = path.join(
    process.env.HOME || "",
    ".config",
    "cms-medical-workbench",
    "ai-runtime.env",
  );
  const result = { path: envPath, exists: false, keys: {} };
  if (!fsExistsSync(envPath)) return result;
  result.exists = true;
  const content = fsReadFileSync(envPath, "utf8");
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eqIndex = trimmed.indexOf("=");
    if (eqIndex < 1) continue;
    const key = trimmed.slice(0, eqIndex).trim();
    const value = trimmed.slice(eqIndex + 1).trim();
    result.keys[key] = value.length > 0;
  }
  return result;
}

async function main() {
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });

  const aiEnv = loadAiRuntimeEnv();
  const runtimeDir = await mkdtemp(path.join(tmpdir(), "mw-cross-indication-runtime-"));
  const apiPort = await freePort();
  const vitePort = await freePort();
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;

  const stableBefore = await directorySnapshot(stableRuntimeDir);

  // Build child env: inherit process.env, override runtime dir, add AI env
  // keys (values passed through, never printed in the report).
  const childEnvBase = { ...process.env, WORKBENCH_RUNTIME_DIR: runtimeDir, PYTHONUNBUFFERED: "1" };
  if (aiEnv.exists) {
    try {
      const content = fsReadFileSync(aiEnv.path, "utf8");
      for (const line of content.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) continue;
        const eqIndex = trimmed.indexOf("=");
        if (eqIndex < 1) continue;
        const key = trimmed.slice(0, eqIndex).trim();
        const value = trimmed.slice(eqIndex + 1).trim();
        if (key && value) childEnvBase[key] = value;
      }
    } catch {
      // already recorded as not existing
    }
  }

  const api = startService(
    process.env.PYTHON_BIN || "python3",
    ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)],
    { cwd: projectRoot, env: childEnvBase },
  );
  const vite = startService(
    process.env.NPM_BIN || "npm",
    ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"],
    { cwd: frontendRoot, env: { ...childEnvBase, VITE_API_PROXY_TARGET: apiBase } },
  );

  const report = {
    mode: DRY_RUN ? "dry-run" : "full",
    passed: false,
    appUrl,
    apiBase,
    aiEnvPresent: aiEnv.exists,
    aiEnvKeys: aiEnv.keys,
    runtime: {
      isolated: true,
      runtimeDir,
      stableRuntimeDir,
      stableBefore,
      stableAfter: {},
      stableUnchanged: false,
    },
    sourceSha256: {
      parentHarness: await fileSha256(path.join(scriptDir, "cross_indication_e2e_parent.mjs")),
      childHarness: await fileSha256(childScript),
      config: await fileSha256(path.join(scriptDir, "cross_indication_e2e_config.mjs")),
      backend: await fileSha256(path.join(projectRoot, "services/api/app/main.py")),
    },
    lanes: [],
    gates: Object.keys(GATE_CODES),
    artifacts: {},
    failures: [],
  };

  try {
    await waitForHttp(`${apiBase}/api/health`);
    await waitForHttp(appUrl);

    if (DRY_RUN) {
      // Dry-run: single disposable project, selector checks, no external calls.
      const laneOutputDir = path.join(outputDir, "dry-run");
      await mkdir(laneOutputDir, { recursive: true });

      const run = spawnSync(process.execPath, [childScript], {
        cwd: projectRoot,
        encoding: "utf8",
        timeout: 300000,
        maxBuffer: 32 * 1024 * 1024,
        env: {
          ...childEnvBase,
          APP_URL: appUrl,
          API_URL: apiBase,
          QC_ISOLATED_RUNTIME: "1",
          QC_DRY_RUN: "1",
          QC_INDICATION_KEY: "DRY",
          QC_INDICATION: "dry-run",
          QC_STUDY_PHASE: "II",
          QC_PRODUCT_NAME: "DRY-01",
          QC_PROJECT_CODE: `QC-MW-DRY-${Date.now()}`,
          QC_MIN_CHAPTERS: "[]",
          QC_OUTPUT_DIR: laneOutputDir,
          CHROME_DEBUG_PORT: String(await freePort()),
        },
      });

      const laneReport = {
        indication: "DRY",
        exitCode: run.status,
        stdoutTail: (run.stdout || "").split("\n").slice(-80).join("\n"),
        stderrTail: (run.stderr || "").split("\n").slice(-80).join("\n"),
      };
      try {
        laneReport.artifacts = JSON.parse(
          await readFile(path.join(laneOutputDir, "lane_artifacts.json"), "utf8"),
        );
      } catch (error) {
        laneReport.artifacts = null;
        laneReport.artifactsReadError = error.message;
      }
      report.lanes.push(laneReport);
      if (run.status !== 0) {
        report.failures.push(`dry-run:child-exit-${run.status}`);
      }
      const dryRunEvidence = laneReport.artifacts?.dry_run_evidence;
      if (!dryRunEvidence) {
        report.failures.push("dry-run:lane-evidence-missing");
      } else {
        if (!dryRunEvidence.project_id) {
          report.failures.push("dry-run:project-id-not-observed");
        }
        if (!dryRunEvidence.workspace_route_present) {
          report.failures.push("dry-run:reference-workspace-route-not-observed");
        }
        if (!dryRunEvidence.authoring_journey_shell_visible) {
          report.failures.push("dry-run:authoring-journey-shell-not-observed");
        }
        if (!dryRunEvidence.project_selector_value) {
          report.failures.push("dry-run:project-selector-value-not-observed");
        }
        if (!dryRunEvidence.new_project_dialog_closed) {
          report.failures.push("dry-run:new-project-dialog-not-closed");
        }
        if (!dryRunEvidence.passed) {
          report.failures.push("dry-run:child-evidence-did-not-pass");
        }
      }
    } else {
      for (let index = 0; index < selectedStudies.length; index += 1) {
        const indication = selectedStudies[index];
        const laneOutputDir = path.join(outputDir, indication.key);
        await mkdir(laneOutputDir, { recursive: true });

        const run = spawnSync(process.execPath, [childScript], {
          cwd: projectRoot,
          encoding: "utf8",
          timeout: indication.timeoutS * 1000,
          maxBuffer: 32 * 1024 * 1024,
          env: {
            ...childEnvBase,
            APP_URL: appUrl,
            API_URL: apiBase,
            QC_ISOLATED_RUNTIME: "1",
            QC_INDICATION_KEY: indication.key,
            QC_INDICATION: indication.indication,
            QC_CLINICALTRIALS_CONDITION_TERM: indication.clinicalTrialsConditionTerm,
            QC_STUDY_PHASE: indication.studyPhase,
            QC_PRODUCT_NAME: indication.productName,
            QC_PROJECT_CODE: `QC-MW-${indication.key}-${Date.now()}-${index}`,
            QC_MIN_CHAPTERS: JSON.stringify(indication.minChapters),
            QC_EXPECTED_NCT_ID: indication.expectedNctId,
            QC_EXPECTED_DOCUMENT_FILENAME: indication.expectedDocumentFilename,
            QC_EXPECTED_DOCUMENT_ROLE: indication.expectedDocumentRole,
            QC_OCR_TIMEOUT_S: String(indication.ocrTimeoutS),
            QC_TRANSLATION_TIMEOUT_S: String(indication.translationTimeoutS),
            QC_CANDIDATE_TIMEOUT_S: String(indication.candidateTimeoutS),
            QC_OUTPUT_DIR: laneOutputDir,
            CHROME_DEBUG_PORT: String(await freePort(9600 + index)),
          },
        });

        const laneReport = {
          indication: indication.key,
          exitCode: run.status,
          stdoutTail: (run.stdout || "").split("\n").slice(-60).join("\n"),
          stderrTail: (run.stderr || "").split("\n").slice(-60).join("\n"),
        };
        try {
          laneReport.artifacts = JSON.parse(
            await readFile(path.join(laneOutputDir, "lane_artifacts.json"), "utf8"),
          );
        } catch (error) {
          laneReport.artifacts = null;
          laneReport.artifactsReadError = error.message;
        }
        report.lanes.push(laneReport);
        if (run.status !== 0) {
          report.failures.push(`${indication.key}:child-exit-${run.status}`);
        }
      }
    }

    // Aggregate artifacts across lanes.
    for (const artifact of ARTIFACT_FILENAMES) {
      const merged = [];
      for (const lane of report.lanes) {
        const laneArtifact = lane.artifacts?.[artifact];
        if (Array.isArray(laneArtifact)) merged.push(...laneArtifact);
        else if (laneArtifact && typeof laneArtifact === "object") merged.push(laneArtifact);
      }
      report.artifacts[artifact] = merged;
      await writeFile(path.join(outputDir, artifact), JSON.stringify(merged, null, 2));
    }

    report.runtime.sqliteIntegrity = sqliteIntegrity(runtimeDir);
    const invalidDatabases = Object.entries(report.runtime.sqliteIntegrity).filter(
      ([, value]) => value !== "ok",
    );
    if (invalidDatabases.length) {
      report.failures.push(`sqlite-integrity:${JSON.stringify(invalidDatabases)}`);
    }
  } finally {
    await stopService(vite);
    await stopService(api);
    report.runtime.apiLogTail = api.output.slice(-120);
    report.runtime.viteLogTail = vite.output.slice(-60);
    report.runtime.stableAfter = await directorySnapshot(stableRuntimeDir);
    report.runtime.stableUnchanged =
      JSON.stringify(stableBefore) === JSON.stringify(report.runtime.stableAfter);
    if (!report.runtime.stableUnchanged) {
      report.failures.push("stable-runtime-changed-during-cross-indication-qc");
    }
    if (process.env.PRESERVE_QC_RUNTIME !== "1") {
      await rm(runtimeDir, { recursive: true, force: true });
      report.runtime.runtimeRemoved = true;
    } else {
      report.runtime.runtimeRemoved = false;
    }
  }

  const laneCount = report.lanes.length;
  const laneFailures = report.lanes.filter((lane) => lane.exitCode !== 0).length;
  report.passed = report.failures.length === 0 && laneFailures === 0;

  await writeFile(
    path.join(outputDir, "cross_indication_e2e_parent_report.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(
    JSON.stringify(
      {
        mode: report.mode,
        passed: report.passed,
        failures: report.failures,
        stableUnchanged: report.runtime.stableUnchanged,
        aiEnvPresent: report.aiEnvPresent,
        laneCount,
        laneFailures,
      },
      null,
      2,
    ),
  );

  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
