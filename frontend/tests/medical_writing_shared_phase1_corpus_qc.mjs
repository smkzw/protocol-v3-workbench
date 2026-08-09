import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const outputDir = path.join(
  projectRoot,
  "records/active_slices/medical_writing_phase1_shared_corpus_admission_20260717/browser_qc",
);
const stableRuntimeDir = path.resolve(projectRoot, "../..", "runtime");
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

async function fileSha256(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
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

function corpusJourney(base, phase) {
  const isPhase1 = phase === "I期";
  const framing = {
    ...base.framing,
    protocol_id: base.framing.protocol_id,
    version: "V0.1",
    document_title: base.framing.document_title,
    indication: base.framing.indication,
    clinicaltrials_condition_term: isPhase1
      ? "Healthy Volunteers"
      : base.framing.indication.includes("血红蛋白尿")
        ? "Paroxysmal Nocturnal Hemoglobinuria"
        : "Rheumatoid Arthritis",
    study_phase: phase,
    intrinsic_objectives: isPhase1 ? ["首次人体试验（FIH）"] : ["概念验证（PoC）"],
    investigational_product: base.framing.investigational_product,
    target_mechanism: "免疫炎症通路调节",
    design_pattern: "随机、双盲、安慰剂对照研究",
    population_intent: phase === "I期" ? "健康成年参与者" : "活动性类风湿关节炎成人参与者",
  };
  return {
    ...base,
    revision: Math.max(3, Number(base.revision || 0)),
    status: "corpus_not_ready",
    current_stage: "corpus",
    framing,
    picos: base.picos || {},
    framing_draft: null,
    picos_draft: null,
    framing_complete: true,
    picos_complete: true,
    picos_sha256: "qc-picos-sha256",
    search_plan: {
      plan_id: `qc-plan-${phase}`,
      latest_snapshot_id: `qc-snapshot-${phase}`,
      returned_count: 0,
      public_document_count: 0,
      registry_filter: {
        condition_term: framing.clinicaltrials_condition_term,
        phases: [phase],
        study_type: "INTERVENTIONAL",
        intervention_terms: [],
        regions: [],
      },
      triage_criteria: [],
    },
    corpus_gate: {
      readiness_status: "not_ready",
      access_permitted: false,
      missing_requirements: [],
      requirements: [],
    },
  };
}

function emptyWorkspace(snapshotId) {
  return {
    snapshot: {
      snapshot_id: snapshotId,
      api_version: "v2",
      data_timestamp: "2026-07-17T00:00:00Z",
      returned_count: 0,
      total_count: 0,
      candidates: [],
    },
    decisions: [],
    artifacts: [],
    document_validations: [],
    extraction_reviews: [],
    translations: [],
    medical_reviews: [],
    approved_evidence_briefs: [],
    evidence_brief_history: [],
    artifact_span_counts: {},
  };
}

async function createProject(apiBase, { suffix, phase, indication, product, protocolId }) {
  return request(apiBase, "/api/projects", {
    method: "POST",
    body: {
      project_code: `QC-${suffix}`,
      project_name: `QC ${phase} ${indication}`,
      indication,
      product_name: product,
      study_phase: phase,
      protocol_id: protocolId,
      protocol_version: "V0.1",
      protocol_date: "2026-07-17",
      entry_mode: "from_zero",
      actor: "codex_browser_qc",
      idempotency_key: `shared-phase1-qc-${suffix}`,
    },
  });
}

async function selectProjectAndWriting(page, projectId) {
  await page.goto(page.url().split("#")[0], { waitUntil: "domcontentloaded" });
  const projectSelect = page.locator('select[aria-label="选择临床研究项目"]');
  await projectSelect.waitFor();
  await projectSelect.selectOption(projectId);
  await page.getByRole("button", { name: "医学写作" }).click();
  await page.locator(".authoring-journey-shell").waitFor();
}

async function visualMetrics(page) {
  return page.evaluate(() => {
    const workspace = document.querySelector(".shared-phase1-corpus-workspace");
    const compare = document.querySelector(".shared-phase1-text-compare");
    const detail = document.querySelector(".shared-phase1-corpus-detail");
    const bounds = (node) => node ? node.getBoundingClientRect() : null;
    return {
      viewport: { width: innerWidth, height: innerHeight },
      pageOverflowX: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
      workspace: bounds(workspace),
      detail: bounds(detail),
      compare: bounds(compare),
      compareColumns: compare ? getComputedStyle(compare).gridTemplateColumns : "",
      candidateButtons: document.querySelectorAll(".shared-phase1-corpus-workspace > nav > button").length,
      sourceTextLength: document.querySelector('.shared-phase1-text-compare p[lang="en"]')?.textContent.length || 0,
      translatedTextLength: document.querySelector(".shared-phase1-text-compare section:nth-child(2) p")?.textContent.length || 0,
    };
  });
}

async function main() {
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const runtimeDir = await mkdtemp(path.join(tmpdir(), "mw-shared-phase1-qc-"));
  const apiPort = await freePort(8941);
  const vitePort = await freePort(5197);
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;
  const stableBefore = await directorySnapshot(stableRuntimeDir);
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
    appUrl,
    apiBase,
    runtime: { isolated: true, runtimeDir, stableRuntimeDir },
    requests: [],
    httpFailures: [],
    consoleErrors: [],
    pageErrors: [],
    failures: [],
    states: {},
  };
  let browser;
  try {
    await waitForHttp(`${apiBase}/api/health`);
    await waitForHttp(appUrl);
    const phase1 = await createProject(apiBase, {
      suffix: "D017-PH1", phase: "I期", indication: "健康参与者", product: "CMS-D017", protocolId: "D017-01-001",
    });
    const pnhPhase2 = await createProject(apiBase, {
      suffix: "D017-PNH", phase: "II期", indication: "阵发性睡眠性血红蛋白尿症", product: "CMS-D017", protocolId: "D017-02-001",
    });
    const phase2b = await createProject(apiBase, {
      suffix: "RA-IIB", phase: "IIb期", indication: "类风湿关节炎", product: "CMS-RA-001", protocolId: "CMS-RA-001",
    });
    const phase1Id = phase1.project.project_id;
    const pnhPhase2Id = pnhPhase2.project.project_id;
    const phase2bId = phase2b.project.project_id;
    const journeys = new Map([
      [phase1Id, corpusJourney(phase1.authoring_journey, "I期")],
      [pnhPhase2Id, corpusJourney(pnhPhase2.authoring_journey, "II期")],
      [phase2bId, corpusJourney(phase2b.authoring_journey, "IIb期")],
    ]);

    const { chromium } = await import(playwrightPath);
    browser = await chromium.launch({ executablePath: chromePath, headless: true });
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    page.on("console", (message) => {
      if (message.type() === "error") report.consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => report.pageErrors.push(error.message));
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (response.status() >= 400) {
        report.httpFailures.push({ method: response.request().method(), status: response.status(), path: url.pathname });
      }
      if (url.pathname.includes("shared-corpus/phase1")) {
        report.requests.push({ method: response.request().method(), status: response.status(), path: url.pathname });
      }
    });
    await page.route("**/api/projects/*/medical-writing/authoring-journey", async (route) => {
      const requestUrl = new URL(route.request().url());
      const match = requestUrl.pathname.match(/^\/api\/projects\/([^/]+)\/medical-writing\/authoring-journey$/);
      if (route.request().method() !== "GET" || !match || !journeys.has(match[1])) {
        await route.continue();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(journeys.get(match[1])) });
    });
    await page.route("**/api/projects/*/medical-writing/references/workspace*", async (route) => {
      const snapshotId = new URL(route.request().url()).searchParams.get("snapshot_id") || "qc-snapshot";
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(emptyWorkspace(snapshotId)) });
    });

    await page.goto(appUrl, { waitUntil: "domcontentloaded" });
    await selectProjectAndWriting(page, phase1Id);
    await page.getByRole("tab", { name: "I期共享语料" }).click();
    await page.locator(".shared-phase1-corpus-workspace > nav > button").first().waitFor();
    const initialCatalog = await request(apiBase, "/api/medical-writing/shared-corpus/phase1");
    const selected = initialCatalog.items[0];
    report.segmentId = selected.segment_id;
    report.initialMetrics = await visualMetrics(page);
    await page.screenshot({ path: path.join(outputDir, "01_pending_review_1920x1080.png"), fullPage: true });

    const queryInput = page.getByPlaceholder("检索NCT号、申办方、药物或正文");
    await queryInput.fill(selected.nct_id);
    await page.waitForFunction(() => document.querySelectorAll(".shared-phase1-corpus-workspace > nav > button").length < 18);
    report.queryFilteredCount = await page.locator(".shared-phase1-corpus-workspace > nav > button").count();
    await queryInput.fill("");
    await page.waitForFunction(() => document.querySelectorAll(".shared-phase1-corpus-workspace > nav > button").length === 18);
    await page.getByLabel("按药物类型筛选").selectOption("small_molecule");
    await page.waitForFunction(() => document.querySelectorAll(".shared-phase1-corpus-workspace > nav > button").length === 10);
    report.modalityFilteredCount = await page.locator(".shared-phase1-corpus-workspace > nav > button").count();
    await page.getByLabel("按药物类型筛选").selectOption("all");
    await page.waitForFunction(() => document.querySelectorAll(".shared-phase1-corpus-workspace > nav > button").length === 18);

    const firstCandidate = page.locator(".shared-phase1-corpus-workspace > nav > button").first();
    await firstCandidate.click();
    await page.locator(".shared-phase1-review-actions textarea").fill("已核对原文、译文、数字、时序、否定关系及I期适用边界。");
    await page.getByRole("button", { name: "批准译文" }).click();
    await page.getByText("译文已完成医学批准").waitFor();
    await page.getByRole("button", { name: "纳入I期共享语料" }).click();
    await page.getByText("当前医学批准版本已纳入I期共享语料").waitFor();
    const admittedCatalog = await request(apiBase, "/api/medical-writing/shared-corpus/phase1");
    const admittedCandidate = admittedCatalog.items.find((item) => item.admission_status === "admitted");
    if (!admittedCandidate) throw new Error("browser admission action did not create an admitted candidate");
    report.segmentId = admittedCandidate.segment_id;
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForTimeout(150);
    report.admittedMetrics = await visualMetrics(page);
    await page.screenshot({ path: path.join(outputDir, "02_admitted_1440x900.png"), fullPage: true });

    const admittedPhase1 = await request(
      apiBase,
      `/api/medical-writing/shared-corpus/phase1/search?query=${encodeURIComponent(admittedCandidate.corpus_function)}&project_phase=${encodeURIComponent("I期")}&project_indication=${encodeURIComponent("健康参与者")}`,
    );
    const admittedPhase2b = await request(
      apiBase,
      `/api/medical-writing/shared-corpus/phase1/search?query=${encodeURIComponent(admittedCandidate.corpus_function)}&project_phase=${encodeURIComponent("IIb期")}&project_indication=${encodeURIComponent("类风湿关节炎")}`,
    );
    report.phaseSearch = {
      phase1: admittedPhase1.items.map((item) => item.segment_id),
      phase2b: admittedPhase2b.items.map((item) => item.segment_id),
    };

    await page.locator(".shared-phase1-review-actions textarea").fill("复核发现该片段适用边界需补充，撤回后重新修订并审核。");
    await page.getByRole("button", { name: "撤回并退回修订" }).click();
    await page.getByText("审核意见已记录；既有准入已立即失效。").waitFor();
    await page.locator(".shared-phase1-corpus-detail .tag.danger", { hasText: "准入已失效" }).waitFor();
    await page.screenshot({ path: path.join(outputDir, "03_withdrawn_1440x900.png"), fullPage: true });
    const afterWithdrawal = await request(apiBase, "/api/medical-writing/shared-corpus/phase1");
    const withdrawn = afterWithdrawal.items.find((item) => item.segment_id === admittedCandidate.segment_id);
    report.withdrawnState = {
      medicalReviewStatus: withdrawn.medical_review_status,
      admissionStatus: withdrawn.admission_status,
      reviewRevision: withdrawn.medical_review_revision,
    };

    report.nonPhase1TabVisible = {};
    await selectProjectAndWriting(page, pnhPhase2Id);
    report.nonPhase1TabVisible.pnhPhase2 = await page.getByRole("tab", { name: "I期共享语料" }).count();
    await selectProjectAndWriting(page, phase2bId);
    report.nonPhase1TabVisible.raPhase2b = await page.getByRole("tab", { name: "I期共享语料" }).count();
    await page.screenshot({ path: path.join(outputDir, "04_phase2b_no_shared_tab_1440x900.png"), fullPage: true });

    const health = await request(apiBase, "/api/health");
    report.health = health.medical_writing_shared_corpus;
    const expectedEmptyDocumentPaths = new Set([
      `/api/projects/${phase1Id}/medical-writing/manifest`,
      `/api/projects/${phase1Id}/medical-writing/document-session`,
      `/api/projects/${pnhPhase2Id}/medical-writing/manifest`,
      `/api/projects/${pnhPhase2Id}/medical-writing/document-session`,
      `/api/projects/${phase2bId}/medical-writing/manifest`,
      `/api/projects/${phase2bId}/medical-writing/document-session`,
    ]);
    const unexpectedHttpFailures = report.httpFailures.filter((item) => !(
      item.status === 404 && expectedEmptyDocumentPaths.has(item.path)
    ));
    const unexpectedConsoleErrors = report.consoleErrors.filter((item) => !item.includes("404 (Not Found)"));
    report.unexpectedHttpFailures = unexpectedHttpFailures;
    report.unexpectedConsoleErrors = unexpectedConsoleErrors;
    for (const [label, metrics] of Object.entries({ initial: report.initialMetrics, admitted: report.admittedMetrics })) {
      if (metrics.pageOverflowX > 0) report.failures.push(`${label}:horizontal-overflow:${metrics.pageOverflowX}`);
      if (metrics.candidateButtons < 1) report.failures.push(`${label}:no-candidates`);
      if (metrics.sourceTextLength < 40 || metrics.translatedTextLength < 20) report.failures.push(`${label}:source-text-not-visible`);
      if (!metrics.compareColumns.includes(" ")) report.failures.push(`${label}:comparison-not-two-column`);
    }
    if (!(report.queryFilteredCount >= 1 && report.queryFilteredCount < 18)) report.failures.push(`query-filter:${report.queryFilteredCount}`);
    if (!(report.modalityFilteredCount >= 1 && report.modalityFilteredCount < 18)) report.failures.push(`modality-filter:${report.modalityFilteredCount}`);
    if (!report.phaseSearch.phase1.includes(admittedCandidate.segment_id)) report.failures.push("phase1-search-missed-admitted-item");
    if (report.phaseSearch.phase2b.length) report.failures.push("phase2b-search-leaked-phase1-corpus");
    if (report.withdrawnState.medicalReviewStatus !== "returned" || report.withdrawnState.admissionStatus !== "invalidated") report.failures.push("withdrawal-not-persisted");
    if (Object.values(report.nonPhase1TabVisible).some((value) => value !== 0)) report.failures.push("non-phase1-project-shows-phase1-tab");
    if (unexpectedConsoleErrors.length || report.pageErrors.length || unexpectedHttpFailures.length) report.failures.push("browser-runtime-errors");
    if (report.health?.status !== "ok" || report.health?.foreign_key_violations !== 0 || report.health?.audit_chain_violations !== 0) report.failures.push("shared-corpus-health-failed");
  } finally {
    await browser?.close();
    await stopService(vite);
    await stopService(api);
    report.runtime.apiLogTail = api.output.slice(-80);
    report.runtime.viteLogTail = vite.output.slice(-40);
    const stableAfter = await directorySnapshot(stableRuntimeDir);
    report.runtime.stableUnchanged = JSON.stringify(stableBefore) === JSON.stringify(stableAfter);
    if (!report.runtime.stableUnchanged) report.failures.push("stable-runtime-changed-during-isolated-qc");
    await rm(runtimeDir, { recursive: true, force: true });
    report.runtime.runtimeRemoved = true;
  }
  report.passed = report.failures.length === 0;
  await writeFile(path.join(outputDir, "browser_qc_report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: report.passed, failures: report.failures, states: report.states }, null, 2));
  if (!report.passed) process.exitCode = 1;
}

main().catch(async (error) => {
  await mkdir(outputDir, { recursive: true });
  await writeFile(path.join(outputDir, "fatal_error.txt"), error.stack || error.message);
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
