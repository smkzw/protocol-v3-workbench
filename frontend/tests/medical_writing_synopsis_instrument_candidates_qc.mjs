import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const outputRoot = path.join(projectRoot, "records/active_slices/medical_writing_scale_registry_20260717/browser_qc_synopsis_candidates");
const reportPath = path.resolve(process.argv[2] || path.join(projectRoot, "records/active_slices/medical_writing_scale_registry_20260717/real_ai_protocol_instrument_candidates_rux_v5.json"));
const playwrightPath = process.env.PLAYWRIGHT_PATH || "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function freePort(preferred) {
  const listen = (port) => new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      const selected = server.address().port;
      server.close(() => resolve(selected));
    });
  });
  try { return await listen(preferred); } catch { return listen(0); }
}

function start(command, args, options) {
  const logs = [];
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
  const collect = (chunk) => { logs.push(String(chunk)); if (logs.length > 100) logs.shift(); };
  child.stdout.on("data", collect);
  child.stderr.on("data", collect);
  return { child, logs };
}

async function stop(service) {
  if (!service?.child || service.child.exitCode !== null) return;
  const exited = new Promise((resolve) => service.child.once("exit", resolve));
  service.child.kill("SIGTERM");
  await Promise.race([exited, wait(5000)]);
  if (service.child.exitCode === null) service.child.kill("SIGKILL");
}

async function waitForHttp(url, timeoutMs = 120000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try { if ((await fetch(url)).ok) return; } catch {}
    await wait(250);
  }
  throw new Error(`Timed out waiting for ${url}`);
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

function completeInstrument(item) {
  return {
    instrument_id: item.instrument_id,
    canonical_name_zh: item.canonical_name_zh,
    canonical_name_en: item.canonical_name_en || "",
    acronym: item.acronym || "",
    version_label: item.version_label || "",
    instrument_kind: item.instrument_kind || "other",
    administration_mode: item.administration_mode || "",
    respondent: item.respondent || "",
    recall_period: item.recall_period || "",
    scoring_range: item.scoring_range || "",
    scoring_direction: item.scoring_direction || "",
    scoring_summary: item.scoring_summary || "",
    study_purpose: item.study_purpose || "",
    endpoint_paths: item.endpoint_paths || [],
    visit_labels: item.visit_labels || [],
    soa_activity_ids: [],
    appendix_locator: item.appendix_locator || "",
    protocol_modified: Boolean(item.protocol_modified),
    source_synopsis_only: true,
    evidence_span_ids: item.evidence_span_ids || [],
    source_bindings: item.source_bindings || [],
    rights: { status: "unknown", full_text_policy: "metadata_only", owner: "", license_reference: "", evidence_url: "", checked_at: null, confirmed_by: "", confirmed_at: null },
    translation: { source_language: "", target_language: "简体中文", status: "unknown", version_label: "", source_url: "", artifact_id: "", reviewed_by: "", reviewed_at: null },
    confirmation_status: "candidate",
    confirmed_by: "",
    confirmed_at: null,
    notes: "",
  };
}

async function main() {
  const realReport = JSON.parse(await readFile(reportPath, "utf8"));
  const realCase = realReport.cases?.find((item) => item.import_status === "review_pending");
  if (!realCase?.instruments?.length || !realCase?.evidence_spans?.length) {
    throw new Error("Real-AI report does not contain reviewable instrument candidates and evidence spans");
  }
  const caseSlug = String(realCase.label || "project").toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
  const outputDir = path.join(outputRoot, caseSlug);
  const sourceStat = await stat(realCase.source_path);
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const runtimeDir = await mkdtemp(path.join(tmpdir(), "mw-synopsis-candidate-qc-"));
  const apiPort = await freePort(8951);
  const vitePort = await freePort(5211);
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;
  const api = start(process.env.PYTHON_BIN || "python3", ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], { cwd: projectRoot, env: { ...process.env, WORKBENCH_RUNTIME_DIR: runtimeDir, PYTHONUNBUFFERED: "1" } });
  const vite = start(process.env.NPM_BIN || "npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"], { cwd: frontendRoot, env: { ...process.env, VITE_API_PROXY_TARGET: apiBase } });
  const qc = { passed: false, reportPath, appUrl, apiBase, projectId: "", candidateCount: realCase.instruments.length, evidenceCount: realCase.evidence_spans.length, checks: {}, errors: [], consoleErrors: [], httpFailures: [], unexpectedHttpFailures: [], screenshots: [] };
  let browser;
  try {
    await waitForHttp(`${apiBase}/api/health`);
    await waitForHttp(appUrl);
    const created = await request(apiBase, "/api/projects", { method: "POST", body: {
      project_code: `${realCase.label}-SYNOPSIS-QC`,
      project_name: `${realCase.label}方案导入候选视觉QC`,
      indication: realCase.indication,
      product_name: "待医学确认试验药物",
      study_phase: "待医学确认",
      protocol_id: realCase.label,
      protocol_version: "待医学确认",
      protocol_date: "",
      entry_mode: "synopsis_import",
      actor: "medical_manager_qc",
      idempotency_key: `create-${caseSlug}-synopsis-candidate-qc-v6`,
    } });
    qc.projectId = created.project.project_id;
    const baseJourney = created.authoring_journey;
    const framing = { ...baseJourney.framing, protocol_id: realCase.label, version: "待医学确认", document_title: `${realCase.label} ${realCase.indication}临床研究方案`, indication: realCase.indication, study_phase: "待医学确认", investigational_product: "待医学确认试验药物" };
    const picos = { ...baseJourney.picos, assessment_instruments: realCase.instruments.map(completeInstrument) };
    const reviewJourney = {
      ...baseJourney,
      entry_mode: "synopsis_import",
      synopsis_import: {
        status: "review_pending",
        source: { source_id: `source_${caseSlug}_qc`, original_filename: path.basename(realCase.source_path), media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", actual_size: sourceStat.size, content_sha256: realCase.source_sha256, extraction_revision: "docx_protocol_v1", parser_name: "docx_protocol_parser", source_role_status: "matched", indication_status: "matched", validation_warnings: [], imported_at: new Date().toISOString(), imported_by: "medical_manager_qc" },
        proposed_framing: framing,
        proposed_picos: picos,
        proposed_synopsis_text: `${realCase.label}${realCase.indication}临床研究方案候选。`,
        missing_fields: [],
        conflict_notes: [],
        field_evidence_span_ids: { "picos.assessment_instruments": [...new Set(realCase.instruments.flatMap((item) => item.evidence_span_ids || []))] },
        evidence_spans: realCase.evidence_spans,
        ai_run_id: realCase.ai_run_id,
      },
    };
    const { chromium } = await import(playwrightPath);
    browser = await chromium.launch({ headless: true, executablePath: chromePath });
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
    page.on("pageerror", (error) => qc.errors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error") qc.consoleErrors.push(message.text()); });
    page.on("response", (response) => {
      if (response.status() < 400) return;
      const failure = { status: response.status(), url: response.url() };
      qc.httpFailures.push(failure);
      const expectedFreshProjectEmptyState = response.status() === 404
        && /\/medical-writing\/(?:manifest|document-session)$/.test(new URL(response.url()).pathname);
      if (!expectedFreshProjectEmptyState) qc.unexpectedHttpFailures.push(failure);
    });
    await page.route(`**/api/projects/${qc.projectId}/medical-writing/authoring-journey`, async (route) => {
      if (route.request().method() === "GET") await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(reviewJourney) });
      else await route.continue();
    });
    await page.goto(appUrl, { waitUntil: "domcontentloaded" });
    await page.locator('select[aria-label="选择临床研究项目"]').selectOption(qc.projectId);
    await page.locator(".nav-item").filter({ hasText: /^医学写作$/ }).click();
    const candidates = page.locator(".synopsis-instrument-candidates");
    await candidates.waitFor({ state: "visible" });
    const visibleText = await candidates.innerText();
    qc.checks.candidateCount = await candidates.locator("article").count();
    qc.checks.originalTextVisible = visibleText.includes("原文");
    qc.checks.locatorVisible = visibleText.includes("synopsis:");
    qc.checks.confirmEnabled = await page.getByRole("button", { name: "确认并进入两阶段补全" }).isEnabled();
    qc.checks.missingEvidenceWarnings = await candidates.locator(".synopsis-instrument-evidence.missing").count();
    const details = candidates.locator("details");
    qc.checks.expandableEvidenceGroups = await details.count();
    if (await details.count()) {
      await details.first().locator("summary").click();
      qc.checks.firstEvidenceGroupExpanded = await details.first().evaluate((node) => node.open);
    }
    qc.checks.desktop1920 = await page.evaluate(() => ({ bodyOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, candidateOverflow: document.querySelector(".synopsis-instrument-candidates")?.scrollWidth - document.querySelector(".synopsis-instrument-candidates")?.clientWidth }));
    const screenshot1920 = path.join(outputDir, `${caseSlug}_synopsis_candidates_1920x1080.png`);
    await page.screenshot({ path: screenshot1920, fullPage: true });
    qc.screenshots.push(screenshot1920);
    await page.setViewportSize({ width: 1440, height: 900 });
    qc.checks.desktop1440 = await page.evaluate(() => ({ bodyOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, candidateOverflow: document.querySelector(".synopsis-instrument-candidates")?.scrollWidth - document.querySelector(".synopsis-instrument-candidates")?.clientWidth }));
    const screenshot1440 = path.join(outputDir, `${caseSlug}_synopsis_candidates_1440x900.png`);
    await page.screenshot({ path: screenshot1440, fullPage: true });
    qc.screenshots.push(screenshot1440);
    qc.passed = qc.errors.length === 0 && qc.unexpectedHttpFailures.length === 0 && qc.checks.candidateCount === qc.candidateCount && qc.checks.originalTextVisible && qc.checks.locatorVisible && qc.checks.confirmEnabled && qc.checks.missingEvidenceWarnings === 0 && qc.checks.desktop1920.bodyOverflow <= 0 && qc.checks.desktop1920.candidateOverflow <= 0 && qc.checks.desktop1440.bodyOverflow <= 0 && qc.checks.desktop1440.candidateOverflow <= 0;
  } catch (error) {
    qc.errors.push(error.stack || error.message);
  } finally {
    await browser?.close();
    await stop(vite);
    await stop(api);
    qc.apiLogTail = api.logs.slice(-30);
    qc.viteLogTail = vite.logs.slice(-20);
    await rm(runtimeDir, { recursive: true, force: true });
  }
  await writeFile(path.join(outputDir, "medical_writing_synopsis_instrument_candidates_qc.json"), JSON.stringify(qc, null, 2));
  console.log(JSON.stringify({ passed: qc.passed, checks: qc.checks, errors: qc.errors, consoleErrors: qc.consoleErrors, httpFailures: qc.httpFailures, unexpectedHttpFailures: qc.unexpectedHttpFailures }, null, 2));
  if (!qc.passed) process.exitCode = 1;
}

main().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
