import { spawn, execFile as execFileCallback } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";


const execFile = promisify(execFileCallback);
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const stableRuntimeDir = path.resolve(projectRoot, "../..", "runtime");
const outputDir = path.join(
  projectRoot,
  "records/active_slices/medical_writing_m11_template_upgrade_20260717/browser_qc",
);
const playwrightPath = process.env.PLAYWRIGHT_PATH
  || "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));


async function freePort(preferred) {
  const open = (port) => new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      const selected = server.address().port;
      server.close(() => resolve(selected));
    });
  });
  try { return await open(preferred); } catch { return open(0); }
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
    } catch (error) { lastError = error; }
    await wait(250);
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}


async function request(apiBase, pathname, { method = "GET", body } = {}) {
  const response = await fetch(`${apiBase}${pathname}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${method} ${pathname} -> ${response.status}: ${JSON.stringify(payload)}`);
  return payload;
}


async function backupSqlite(source, target) {
  await execFile(process.env.PYTHON_BIN || "python3", [
    "-c",
    "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()",
    source,
    target,
  ]);
}


async function sha256(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}


async function selectProjectAndWriting(page, projectId) {
  await page.goto(page.url().split("#")[0], { waitUntil: "domcontentloaded" });
  const projectSelect = page.locator('select[aria-label="选择临床研究项目"]');
  await projectSelect.waitFor();
  await projectSelect.selectOption(projectId);
  await page.getByRole("button", { name: "医学写作" }).click();
  await page.getByText("研究方案文档编辑与AI修订", { exact: true }).waitFor();
}


function applyBody(preview, idempotencyKey) {
  return {
    expected_baseline_revision: preview.current_baseline_revision,
    expected_baseline_sha256: preview.current_baseline_sha256,
    expected_preview_sha256: preview.preview_sha256,
    target_template_id: preview.target_template_id,
    target_template_version: preview.target_template_version,
    target_template_definition_sha256: preview.target_template_definition_sha256,
    acknowledge_consolidation: true,
    acknowledge_approval_reset: true,
    actor: "codex_browser_qc",
    idempotency_key: idempotencyKey,
  };
}


async function main() {
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const runtimeDir = await mkdtemp(path.join(tmpdir(), "mw-template-upgrade-qc-"));
  const sourceGreenfield = path.join(stableRuntimeDir, "medical_writing_greenfield.sqlite3");
  const sourceRuntime = path.join(stableRuntimeDir, "workbench_runtime.sqlite3");
  const stableBefore = {
    greenfield: await sha256(sourceGreenfield),
    runtime: await sha256(sourceRuntime),
  };
  await backupSqlite(sourceGreenfield, path.join(runtimeDir, "medical_writing_greenfield.sqlite3"));
  await backupSqlite(sourceRuntime, path.join(runtimeDir, "workbench_runtime.sqlite3"));
  const apiPort = await freePort(8948);
  const vitePort = await freePort(5198);
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;
  const api = startService(
    process.env.PYTHON_BIN || "python3",
    ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)],
    { cwd: projectRoot, env: { ...process.env, WORKBENCH_RUNTIME_DIR: runtimeDir, PYTHONUNBUFFERED: "1" } },
  );
  const vite = startService(
    process.env.NPM_BIN || "npm",
    ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"],
    { cwd: frontendRoot, env: { ...process.env, VITE_API_PROXY_TARGET: apiBase } },
  );
  const report = {
    passed: false,
    runtime: { isolated: true, stableRuntimeDir, runtimeDir },
    appUrl,
    apiBase,
    consoleErrors: [],
    pageErrors: [],
    httpFailures: [],
    failures: [],
    projects: {},
  };
  let browser;
  try {
    await waitForHttp(`${apiBase}/api/health`);
    await waitForHttp(appUrl);
    const crswnpPreview = await request(
      apiBase,
      "/api/projects/proj_mgk10_crswnp/medical-writing/greenfield-document/template-upgrade/preview",
    );
    const raPreview = await request(
      apiBase,
      "/api/projects/proj_ra_greenfield_sandbox/medical-writing/greenfield-document/template-upgrade/preview",
    );
    report.projects.crswnp = {
      preview: {
        sourceSections: crswnpPreview.source_section_count,
        targetSections: crswnpPreview.target_section_count,
        mapped: crswnpPreview.mapped_source_section_count,
        workingCopies: crswnpPreview.working_copy_count,
        consolidations: crswnpPreview.consolidation_target_node_ids,
        canApply: crswnpPreview.can_apply,
      },
    };
    report.projects.ra = {
      preview: {
        sourceSections: raPreview.source_section_count,
        targetSections: raPreview.target_section_count,
        mapped: raPreview.mapped_source_section_count,
        workingCopies: raPreview.working_copy_count,
        consolidations: raPreview.consolidation_target_node_ids,
        canApply: raPreview.can_apply,
      },
    };

    const { chromium } = await import(playwrightPath);
    browser = await chromium.launch({ executablePath: chromePath, headless: true });
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    page.on("console", (message) => {
      if (message.type() === "error") report.consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => report.pageErrors.push(error.message));
    page.on("response", (response) => {
      if (response.status() >= 400) {
        const url = new URL(response.url());
        report.httpFailures.push({ method: response.request().method(), status: response.status(), path: url.pathname });
      }
    });
    await page.goto(appUrl, { waitUntil: "domcontentloaded" });
    await selectProjectAndWriting(page, "proj_mgk10_crswnp");
    const upgradeButton = page.getByRole("button", { name: "升级模板" });
    await upgradeButton.waitFor();
    await upgradeButton.click();
    const drawer = page.locator(".writing-template-upgrade-drawer");
    await drawer.waitFor();
    const mappingRows = await drawer.locator("tbody tr").count();
    const drawerMetrics = await drawer.evaluate((node) => {
      const bounds = node.getBoundingClientRect();
      const table = node.querySelector(".writing-template-upgrade-table-wrap")?.getBoundingClientRect();
      return {
        bounds: { left: bounds.left, right: bounds.right, top: bounds.top, bottom: bounds.bottom },
        table: table ? { left: table.left, right: table.right, top: table.top, bottom: table.bottom } : null,
        pageOverflowX: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
      };
    });
    report.projects.crswnp.browserPreview = { mappingRows, drawerMetrics };
    await page.screenshot({ path: path.join(outputDir, "01_crswnp_upgrade_preview_1920x1080.png"), fullPage: true });
    const confirmations = drawer.locator('.writing-template-upgrade-confirmations input[type="checkbox"]');
    for (let index = 0; index < await confirmations.count(); index += 1) await confirmations.nth(index).check();
    await drawer.getByRole("button", { name: "确认升级" }).click();
    await page.getByText("已升级至当前中文M11模板，旧文档历史仍完整保留。").waitFor();
    const crswnpUpgraded = await request(apiBase, "/api/projects/proj_mgk10_crswnp/medical-writing/document-session");
    const crswnpDocxResponse = await fetch(`${apiBase}/api/projects/proj_mgk10_crswnp/medical-writing/document.docx?mode=draft_preview`);
    if (!crswnpDocxResponse.ok) throw new Error(`CRSwNP DOCX export failed: ${crswnpDocxResponse.status}`);
    const crswnpDocxPath = path.join(outputDir, "crswnp_upgraded_preview.docx");
    await writeFile(crswnpDocxPath, Buffer.from(await crswnpDocxResponse.arrayBuffer()));
    const { stdout: crswnpDocxAudit } = await execFile(process.env.PYTHON_BIN || "python3", [
      "-c",
      "from docx import Document; import sys,json; d=Document(sys.argv[1]); print(json.dumps({'paragraphs':len(d.paragraphs),'tables':len(d.tables),'text':'\\n'.join(p.text for p in d.paragraphs)},ensure_ascii=False))",
      crswnpDocxPath,
    ]);
    const crswnpDocxSummary = JSON.parse(crswnpDocxAudit);
    report.projects.crswnp.upgraded = {
      documentId: crswnpUpgraded.document_id,
      sectionCount: crswnpUpgraded.sections.length,
      templateId: crswnpUpgraded.template_id,
      templateVersion: crswnpUpgraded.template_version,
      docx: {
        paragraphs: crswnpDocxSummary.paragraphs,
        tables: crswnpDocxSummary.tables,
        textCharacters: crswnpDocxSummary.text.length,
        preservesDesignText: crswnpDocxSummary.text.includes("随机、双盲、安慰剂对照、多中心III期研究"),
      },
    };
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: path.join(outputDir, "02_crswnp_upgraded_1440x900.png"), fullPage: true });
    const rollbackResponsePromise = page.waitForResponse((response) => (
      response.request().method() === "POST"
      && new URL(response.url()).pathname.endsWith("/medical-writing/greenfield-document/template-upgrade/rollback")
    ));
    await page.getByRole("button", { name: "恢复升级前版本" }).click();
    const rollbackResponse = await rollbackResponsePromise;
    const rollbackPayload = await rollbackResponse.json();
    await page.getByRole("button", { name: "恢复升级前版本" }).waitFor({ state: "detached" });
    const crswnpRestored = await request(apiBase, "/api/projects/proj_mgk10_crswnp/medical-writing/document-session");
    const crswnpRestoredState = await request(apiBase, "/api/projects/proj_mgk10_crswnp/medical-writing/greenfield-document");
    report.projects.crswnp.restored = {
      rollbackStatus: rollbackResponse.status(),
      rollbackEventId: rollbackPayload.rollback_event_id,
      removedDocumentId: rollbackPayload.removed_document_id,
      restoredDocumentId: rollbackPayload.restored_document?.document_id,
      restoredSectionCount: rollbackPayload.restored_document?.sections?.length,
      documentId: crswnpRestored.document_id,
      sectionCount: crswnpRestored.sections.length,
      templateVersion: crswnpRestored.template_version,
      baselineDocumentId: crswnpRestoredState.document_id,
      baselineRevision: crswnpRestoredState.baseline_revision,
      baselineSha256: crswnpRestoredState.baseline_sha256,
    };
    await page.getByText("正在加载研究方案文档会话。", { exact: true }).waitFor({ state: "detached" });
    await page.getByText("方案摘要", { exact: true }).first().waitFor();
    await page.screenshot({ path: path.join(outputDir, "03_crswnp_restored_1440x900.png"), fullPage: true });

    const raApplied = await request(
      apiBase,
      "/api/projects/proj_ra_greenfield_sandbox/medical-writing/greenfield-document/template-upgrade/apply",
      { method: "POST", body: applyBody(raPreview, "ra-template-upgrade-qc") },
    );
    const raSession = await request(apiBase, "/api/projects/proj_ra_greenfield_sandbox/medical-writing/document-session");
    const raDocx = await fetch(`${apiBase}/api/projects/proj_ra_greenfield_sandbox/medical-writing/document.docx?mode=draft_preview`);
    report.projects.ra.upgraded = {
      documentId: raSession.document_id,
      sectionCount: raSession.sections.length,
      templateId: raSession.template_id,
      baselineRevision: raApplied.baseline_revision,
      docxStatus: raDocx.status,
      docxBytes: (await raDocx.arrayBuffer()).byteLength,
    };

    const stableAfter = {
      greenfield: await sha256(sourceGreenfield),
      runtime: await sha256(sourceRuntime),
    };
    report.stableRuntimeUnchanged = JSON.stringify(stableBefore) === JSON.stringify(stableAfter);
    report.stableServices = {
      backend: (await fetch("http://127.0.0.1:8911/api/health")).status,
      frontend: (await fetch("http://127.0.0.1:5174/")).status,
    };
    const expectedOptionalPaths = new Set([
      "/api/projects/proj_mgk10_crswnp/medical-writing/authoring-journey",
    ]);
    const unexpectedHttpFailures = report.httpFailures.filter(
      (failure) => !(failure.status === 404 && expectedOptionalPaths.has(failure.path)),
    );
    const unexpectedConsoleErrors = unexpectedHttpFailures.length > 0
      ? report.consoleErrors
      : report.consoleErrors.filter((message) => !message.includes("Failed to load resource: the server responded with a status of 404"));
    report.expectedOptionalHttpFailures = report.httpFailures.filter(
      (failure) => failure.status === 404 && expectedOptionalPaths.has(failure.path),
    );
    report.unexpectedHttpFailures = unexpectedHttpFailures;
    report.unexpectedConsoleErrors = unexpectedConsoleErrors;
    const checks = {
      crswnpPreview: crswnpPreview.can_apply && mappingRows === 14 && crswnpPreview.mapped_source_section_count === 14,
      crswnpVisual: drawerMetrics.pageOverflowX === 0 && drawerMetrics.bounds.left >= 0 && drawerMetrics.bounds.right <= 1920,
      crswnpUpgrade: crswnpUpgraded.sections.length === 160 && crswnpUpgraded.template_id === "ich_m11_zh_cn",
      crswnpContent: report.projects.crswnp.upgraded.docx.tables >= 1 && report.projects.crswnp.upgraded.docx.preservesDesignText,
      crswnpRollback: crswnpRestored.sections.length === 14 && crswnpRestored.document_id === crswnpPreview.current_document_id,
      raUpgrade: raSession.sections.length === 160 && raDocx.status === 200 && report.projects.ra.upgraded.docxBytes > 20000,
      stableUnchanged: report.stableRuntimeUnchanged,
      stablePorts: report.stableServices.backend === 200 && report.stableServices.frontend === 200,
      noBrowserErrors: unexpectedConsoleErrors.length === 0 && report.pageErrors.length === 0 && unexpectedHttpFailures.length === 0,
    };
    report.checks = checks;
    report.failures = Object.entries(checks).filter(([, passed]) => !passed).map(([name]) => name);
    report.passed = report.failures.length === 0;
  } catch (error) {
    report.failures.push(error?.stack || String(error));
  } finally {
    if (browser) await browser.close();
    await stopService(vite);
    await stopService(api);
    report.runtime.cleaned = true;
    await writeFile(path.join(outputDir, "qc_report.json"), `${JSON.stringify(report, null, 2)}\n`);
    await rm(runtimeDir, { recursive: true, force: true });
  }
  if (!report.passed) {
    process.stderr.write(`${JSON.stringify(report, null, 2)}\n`);
    process.exitCode = 1;
  } else {
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  }
}


await main();
