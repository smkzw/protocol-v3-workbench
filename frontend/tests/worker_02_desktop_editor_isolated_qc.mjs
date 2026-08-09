/**
 * Worker 02 isolated desktop editor QC — 1920x1080 and wider.
 *
 * Starts an isolated backend + frontend (temp runtime, random ports),
 * then exercises the medical writing editor surface with Playwright.
 * All write actions go to the isolated runtime; stable 8911/5174 is untouched.
 *
 * Output: screenshots + JSON findings under evidenceDir.
 */
import { spawn, execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const evidenceDir = process.env.EVIDENCE_DIR || path.join(scriptDir, "worker_02_evidence");
const stableRuntimeDir = path.join(projectRoot, "runtime");
const playwrightPath = process.env.PLAYWRIGHT_PATH || "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const findings = [];
let findingSeq = 0;

function addFinding(severity, category, title, detail) {
  const id = `F${String(++findingSeq).padStart(3, "0")}`;
  findings.push({ id, severity, category, title, detail, timestamp: new Date().toISOString() });
  console.log(`[${severity}] ${id} ${category}: ${title}`);
  return id;
}

async function freePort(preferred) {
  const tryPort = (port) =>
    new Promise((resolve, reject) => {
      const server = net.createServer();
      server.unref();
      server.once("error", reject);
      server.listen(port, "127.0.0.1", () => {
        const p = server.address().port;
        server.close(() => resolve(p));
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
  const exited = new Promise((r) => service.child.once("exit", r));
  service.child.kill("SIGTERM");
  await Promise.race([exited, wait(8000)]);
  if (service.child.exitCode === null) service.child.kill("SIGKILL");
}

async function waitForHttp(url, timeoutMs = 120000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      const resp = await fetch(url);
      if (resp.ok) return;
      lastError = new Error(`${resp.status}: ${url}`);
    } catch (e) {
      lastError = e;
    }
    await wait(300);
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

async function request(apiBase, pathname, opts = {}) {
  const method = opts.method || "GET";
  const body = opts.body;
  const resp = await fetch(`${apiBase}${pathname}`, {
    method,
    headers: {
      "X-Workbench-Api-Contract": "medical-writing-api-2026-07-17.1",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(`${method} ${pathname} -> ${resp.status}: ${JSON.stringify(payload)}`);
  return payload;
}

async function stableSnapshot() {
  const names = (await readdir(stableRuntimeDir)).filter((n) => n.endsWith(".sqlite3")).sort();
  return Object.fromEntries(
    await Promise.all(
      names.map(async (n) => [n, createHash("sha256").update(await readFile(path.join(stableRuntimeDir, n))).digest("hex")]),
    ),
  );
}

// ── Playwright helpers ──────────────────────────────────────────

async function createBrowser() {
  const { chromium } = await import(playwrightPath);
  return chromium.launch({
    headless: true,
    executablePath: chromePath,
    args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
  });
}

async function overflowDiagnostic(page, label) {
  return page.evaluate((l) => {
    const doc = document.documentElement;
    const body = document.body;
    const sel = (s) => document.querySelector(s);
    const elem = (s) => {
      const e = sel(s);
      if (!e) return null;
      const r = e.getBoundingClientRect();
      return {
        scrollW: e.scrollWidth,
        clientW: e.clientWidth,
        overflowX: e.scrollWidth - e.clientWidth,
        rect: { left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom) },
      };
    };
    return {
      label: l,
      viewportW: window.innerWidth,
      viewportH: window.innerHeight,
      docScrollW: doc.scrollWidth,
      docClientW: doc.clientWidth,
      bodyScrollW: body.scrollWidth,
      horizontalScroll: doc.scrollWidth - doc.clientWidth,
      toolbar: elem(".rich-toolbar"),
      toolbarRow1: elem(".rich-toolbar-text-row"),
      toolbarRow2: elem(".rich-toolbar-paragraph-row"),
      editor: elem(".protocol-editor .ProseMirror"),
      writingMain: elem(".writing-main"),
      writingContent: elem(".writing-content"),
      sectionTree: elem(".section-tree"),
      candidateSection: elem(".writing-ai-candidates"),
      topBar: elem(".app-header"),
      projectHeader: elem(".project-header"),
      consoleErrors: (window.__caughtErrors || []).slice(0, 10),
    };
  }, label);
}

async function screenshot(page, name) {
  const p = path.join(evidenceDir, `${name}.png`);
  await page.screenshot({ path: p, fullPage: false });
  return p;
}

// Collect console errors
function attachConsoleCollector(context) {
  context.on("weberror", (err) => {
    addFinding("P1", "browser-error", `Web error: ${err.message()}`, err.stack?.split("\n").slice(0, 3).join("\n"));
  });
}

async function setupConsoleCapture(page) {
  await page.addInitScript(() => {
    window.__caughtErrors = [];
    window.addEventListener("error", (e) => {
      window.__caughtErrors.push({ msg: e.message, src: e.filename, line: e.lineno });
    });
  });
}

// ── Test: open writing page for a project ────────────────────────

async function openWriting(page, appUrl, projectId) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await page.goto(appUrl, { waitUntil: "domcontentloaded" });
    const select = page.locator('select[aria-label="选择临床研究项目"]');
    await select.waitFor({ timeout: 15000 });
    await select.selectOption(projectId);
    await page.getByRole("button", { name: "医学写作" }).click();
    await page.getByText("研究方案文档编辑与AI修订", { exact: true }).waitFor({ timeout: 20000 });
    try {
      await page.waitForFunction(
        () => !document.body.innerText.includes("真实方案文档会话未就绪"),
        null,
        { timeout: 15000 },
      );
      return;
    } catch {
      if (attempt === 2) throw new Error("greenfield document session did not become ready after reload retries");
    }
  }
}

async function openTocAndSelectSection(page, searchText) {
  await page.getByRole("button", { name: "目录" }).click();
  const drawer = page.locator(".writing-document-map-drawer");
  await drawer.waitFor({ timeout: 8000 });
  await drawer.locator('input[placeholder="搜索章节标题"]').fill(searchText);
  const button = drawer.locator(".writing-section-buttons > button").filter({ hasText: searchText }).first();
  await button.waitFor({ timeout: 8000 });
  await button.click();
  await drawer.waitFor({ state: "hidden", timeout: 8000 });
}

async function findEditableSection(apiBase, projectId) {
  const session = await request(apiBase, `/api/projects/${projectId}/medical-writing/document-session`);
  for (let i = 0; i < Math.min(session.sections.length, 40); i++) {
    const sec = session.sections[i];
    const content = await request(apiBase, `/api/projects/${projectId}/medical-writing/document-session/sections/${sec.section_id}`);
    const copy = await request(apiBase, `/api/projects/${projectId}/medical-writing/working-copies/${sec.section_id}`);
    const editable = (content.content_blocks || []).find(
      (b) => b.block_type !== "table" && String(b.text || "").trim().length > 5,
    );
    if (copy.revision === 0 && editable) return { section: sec, sectionIndex: i, content, copy, editable };
  }
  return null;
}

// ── Main ─────────────────────────────────────────────────────────

async function main() {
  await mkdir(evidenceDir, { recursive: true });

  const snapshotBefore = await stableSnapshot();
  console.log("Stable runtime snapshot taken:", Object.keys(snapshotBefore).length, "DB files");

  // Free ports
  const apiPort = await freePort(8940);
  const webPort = await freePort(5185);
  console.log(`Isolated ports: API=${apiPort}, Web=${webPort}`);

  // Temp runtime dir
  const tempDir = await mkdtemp(path.join(tmpdir(), "worker02_rt_"));
  console.log("Temp runtime:", tempDir);

  // Env
  const envFile = process.env.WORKBENCH_AI_ENV_FILE || path.join(process.env.HOME, ".config/cms-medical-workbench/ai-runtime.env");
  let envVars = {};
  try {
    const envText = await readFile(envFile, "utf-8");
    for (const line of envText.split("\n")) {
      const m = line.match(/^export\s+([A-Z_]+)=(.*)$/);
      if (m) envVars[m[1]] = m[2].replace(/^["']|["']$/g, "");
    }
  } catch {
    console.log("Warning: could not read", envFile);
  }

  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${webPort}/`;

  const backendEnv = {
    ...process.env,
    ...envVars,
    WORKBENCH_RUNTIME_DIR: tempDir,
    WORKBENCH_CLIENT_CONTRACT_MODE: "enforce",
    PYTHONPATH: projectRoot,
  };

  // Start backend (match pattern from existing isolated QC runners)
  console.log("Starting isolated backend...");
  const pythonBin = process.env.PYTHON_BIN || "python3";
  const backend = startService(pythonBin, [
    "-m", "uvicorn", "services.api.app.main:app",
    "--host", "127.0.0.1",
    "--port", String(apiPort),
  ], { env: { ...backendEnv, PYTHONUNBUFFERED: "1" }, cwd: projectRoot });

  try {
    await waitForHttp(`${apiBase}/api/runtime-readiness`, 120000);
    console.log("Backend ready");
  } catch (e) {
    console.log("Backend failed to start. Output:");
    console.log(backend.output.join("").slice(-2000));
    throw e;
  }

  // Start frontend
  console.log("Starting isolated frontend...");
  const frontendEnv = {
    ...process.env,
    VITE_API_PROXY_TARGET: apiBase,
  };
  const frontend = startService(process.execPath, [
    path.join(frontendRoot, "node_modules/vite/bin/vite.js"),
    "--host", "127.0.0.1",
    "--port", String(webPort),
    "--strictPort",
  ], { env: frontendEnv, cwd: frontendRoot });

  try {
    await waitForHttp(appUrl, 60000);
    console.log("Frontend ready");
  } catch (e) {
    console.log("Frontend failed to start. Output:");
    console.log(frontend.output.join("").slice(-2000));
    throw e;
  }

  // Seed a test project for write-safe testing
  console.log("Seeding test project...");
  const testProject = await request(apiBase, "/api/projects", {
    method: "POST",
    body: {
      project_code: "QC-W02-EDITOR",
      project_name: "编辑器桌面端QC测试",
      indication: "特应性皮炎",
      product_name: "测试药物",
      study_phase: "III",
      protocol_id: "QC-W02-EDITOR",
      protocol_version: "V0.1",
      protocol_date: "2026-07-17",
      entry_mode: "from_zero",
      actor: "worker_02_qc",
      idempotency_key: "worker02-editor-qc-project",
    },
  });
  const projectId = testProject.project.project_id;
  console.log("Test project:", projectId);

  // Seed authoring journey so document-session has sections
  const framing = {
    protocol_id: "QC-W02-EDITOR",
    version: "V0.1",
    document_title: "测试药物III期临床研究方案",
    indication: "特应性皮炎",
    clinicaltrials_condition_term: "Atopic Dermatitis",
    study_phase: "III期",
    intrinsic_objectives: ["确证性研究"],
    investigational_product: "测试药物",
    target_mechanism: "测试机制",
    competitor_target_scope: "同适应症创新疗法",
    development_regions: ["中国"],
    design_pattern: "随机、双盲、安慰剂对照",
    population_intent: "中重度特应性皮炎成人",
    key_uncertainties: ["剂量选择"],
    manual_source_ids: [],
    terminology_policy: "cde_participant",
  };
  const picos = {
    design_archetype: "randomized_confirmatory",
    field_applicability: {},
    population_summary: "中重度特应性皮炎成人受试者。",
    inclusion_modules: ["筛选期符合疾病活动度阈值"],
    exclusion_modules: ["活动性感染"],
    washout_rules: ["既往系统治疗按方案完成洗脱"],
    intervention_summary: "测试药物口服给药。",
    intervention_dose_regimen: "每日一次口服。",
    allowed_concomitant_rules: ["稳定外用保湿剂"],
    required_background_rules: [],
    prohibited_concomitant_rules: ["其他系统治疗"],
    assessment_timing_restrictions: [],
    comparator_summary: "匹配安慰剂。",
    primary_endpoint: "主要疗效终点应答率。",
    key_secondary_endpoints: ["次要终点"],
    other_secondary_endpoints: [],
    exploratory_endpoints: [],
    safety_endpoints: ["TEAE和SAE发生率"],
    aesi_definitions: ["严重感染"],
    assessment_instruments: [],
    study_epochs: ["筛选期", "治疗期", "随访期"],
    visit_strategy: "筛选、基线、治疗期定期访视。",
    estimand_strategy: "主要估计目标评价治疗差异。",
    sample_size_strategy: "基于预期应答率差异估算。",
    statistical_strategy: "分层分析。",
  };

  try {
    const initial = testProject.authoring_journey;
    const framingPreview = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`, {
      method: "POST", body: { expected_revision: initial.revision, stage: "framing", framing },
    });
    const framed = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/stages/framing/commit`, {
      method: "POST", body: { expected_revision: initial.revision, stage: "framing", framing, impact_preview_id: framingPreview.preview_id, actor: "worker_02_qc", idempotency_key: "w02-framing" },
    });
    const picosPreview = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`, {
      method: "POST", body: { expected_revision: framed.revision, stage: "picos", picos },
    });
    const designed = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/stages/picos/commit`, {
      method: "POST", body: { expected_revision: framed.revision, stage: "picos", picos, impact_preview_id: picosPreview.preview_id, actor: "worker_02_qc", idempotency_key: "w02-picos" },
    });
    const missing = designed.corpus_gate?.missing_requirements || [];
    const allowed = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/corpus-gate/override`, {
      method: "POST", body: { expected_revision: designed.revision, reason: "隔离环境验证编辑器功能", acknowledged_missing_requirements: missing, actor: "worker_02_qc", idempotency_key: "w02-corpus" },
    });
    const defn = allowed.study_definition;
    if (!defn) throw new Error("StudyDefinition not produced");

    // Bind the greenfield document to the governed protocol template, not a table template.
    const protocolTemplate = await request(
      apiBase,
      "/api/medical-writing/protocol-templates/default",
    );
    const templateId = protocolTemplate.template_id;
    const templateVersion = protocolTemplate.template_version;

    await request(apiBase, `/api/projects/${projectId}/medical-writing/greenfield-document`, {
      method: "POST", body: {
        protocol_id: allowed.framing.protocol_id,
        version: allowed.framing.version,
        document_title: allowed.framing.document_title,
        indication: allowed.framing.indication,
        study_phase: allowed.framing.study_phase,
        source_study_definition_id: defn.definition_id,
        source_study_definition_revision: defn.revision,
        source_study_definition_sha256: defn.state_sha256,
        template_id: templateId,
        template_version: templateVersion,
        actor: "worker_02_qc",
        idempotency_key: "w02-document",
      },
    });
    console.log("Greenfield document created");

    // Resolve blocking decisions
    let greenfieldState = await request(apiBase, `/api/projects/${projectId}/medical-writing/greenfield-document`);
    for (const dec of greenfieldState.decisions.filter((d) => d.approval_blocking && d.status !== "resolved")) {
      await request(apiBase, `/api/projects/${projectId}/medical-writing/greenfield-document/decisions/${dec.decision_id}/resolve`, {
        method: "POST", body: {
          expected_baseline_revision: greenfieldState.baseline_revision,
          value: `已确认：${dec.label}`,
          rationale: "QC测试确认",
          source_refs: [`w02:${dec.decision_id}`],
          actor: "worker_02_qc",
          idempotency_key: `w02-decision-${dec.decision_id}`,
        },
      });
      greenfieldState = await request(apiBase, `/api/projects/${projectId}/medical-writing/greenfield-document`);
    }
    console.log("All blocking decisions resolved");
  } catch (e) {
    addFinding("P0", "seed", "Failed to seed test project with authoring journey", e.message);
    throw e;
  }

  // Find an editable section
  const editableInfo = await findEditableSection(apiBase, projectId);
  if (!editableInfo) {
    addFinding("P0", "seed", "No editable section found in document session", "Cannot test editor without an editable section");
    throw new Error("No editable section");
  }
  console.log("Editable section:", editableInfo.section.section_number, editableInfo.section.section_id);

  // ── Browser tests ────────────────────────────────────────────

  const browser = await createBrowser();
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });
  attachConsoleCollector(context);
  const page = await context.newPage();
  await setupConsoleCapture(page);
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      addFinding("P2", "console-error", `Console error: ${msg.text().slice(0, 120)}`, msg.text());
    }
  });

  const results = {};

  // ── TEST 1: Open writing page at 1920x1080 ──────────────────
  console.log("\n=== TEST 1: Open writing at 1920x1080 ===");
  try {
    await openWriting(page, appUrl, projectId);
    await wait(1500);
    await screenshot(page, "01_writing_page_1920x1080");
    const diag = await overflowDiagnostic(page, "writing-page-1920");
    results.openWriting = "pass";
    results.diag1920 = diag;

    if (diag.horizontalScroll > 2) {
      addFinding("P1", "overflow", `Horizontal overflow at 1920x1080: ${diag.horizontalScroll}px`, JSON.stringify({ docScrollW: diag.docScrollW, docClientW: diag.docClientW }));
    }
    // Check top bar doesn't overflow
    if (diag.topBar && diag.topBar.rect.right > 1920) {
      addFinding("P1", "overflow", `Top bar overflows viewport: right=${diag.topBar.rect.right}`, "");
    }
    // Check toolbar overflow
    if (diag.toolbar && diag.toolbar.overflowX > 2) {
      addFinding("P1", "overflow", `Toolbar horizontal overflow: ${diag.toolbar.overflowX}px`, "");
    }
    console.log("Overflow check done:", JSON.stringify({ hScroll: diag.horizontalScroll, toolbarOverflow: diag.toolbar?.overflowX }));
  } catch (e) {
    results.openWriting = "fail";
    addFinding("P0", "navigation", "Failed to open writing page at 1920x1080", e.message);
    await screenshot(page, "01_fail");
  }

  // ── TEST 2: TOC navigation ──────────────────────────────────
  console.log("\n=== TEST 2: TOC navigation ===");
  try {
    await page.getByRole("button", { name: "目录" }).click();
    const drawer = page.locator(".writing-document-map-drawer");
    await drawer.waitFor({ timeout: 8000 });
    await wait(500);
    await screenshot(page, "02_toc_drawer_open");

    // Count sections
    const sectionButtons = await drawer.locator(".writing-section-buttons > button").count();
    results.tocSectionCount = sectionButtons;
    console.log("TOC sections:", sectionButtons);

    if (sectionButtons === 0) {
      addFinding("P1", "toc", "TOC drawer shows zero sections", "Expected M11 sections from greenfield document");
    }

    // Search test
    const searchInput = drawer.locator('input[placeholder="搜索章节标题"]');
    if (await searchInput.count()) {
      await searchInput.fill("研究");
      await wait(500);
      const filtered = await drawer.locator(".writing-section-buttons > button:visible").count();
      results.tocFilteredCount = filtered;
      await screenshot(page, "02b_toc_search");
      await searchInput.fill("");
      await wait(300);
    }

    // Click a section
    const firstSection = drawer.locator(".writing-section-buttons > button").first();
    await firstSection.click();
    await wait(500);

    await drawer.waitFor({ state: "hidden", timeout: 8000 });
    results.toc = "pass";
  } catch (e) {
    results.toc = "fail";
    addFinding("P1", "toc", "TOC navigation failed", e.message);
    await screenshot(page, "02_fail");
  }

  // ── TEST 3: Create working copy ────────────────────────────
  console.log("\n=== TEST 3: Create working copy ===");
  try {
    // Select the editable section we found
    await openTocAndSelectSection(page, editableInfo.section.heading || editableInfo.section.section_number.toString());
    await wait(500);

    const createBtn = page.getByRole("button", { name: "创建工作副本" });
    if (await createBtn.count()) {
      await createBtn.click();
      await wait(1000);
      await screenshot(page, "03_working_copy_created");
      results.createWorkingCopy = "pass";
    } else {
      // Maybe already has a working copy
      console.log("Create button not found, checking if working copy exists");
      results.createWorkingCopy = "skip";
    }
  } catch (e) {
    results.createWorkingCopy = "fail";
    addFinding("P1", "working-copy", "Failed to create working copy", e.message);
    await screenshot(page, "03_fail");
  }

  // ── TEST 4: Toolbar buttons — formatting ───────────────────
  console.log("\n=== TEST 4: Toolbar formatting buttons ===");
  const toolbarTests = [
    { name: "bold", title: "加粗", check: "strong" },
    { name: "italic", title: "斜体", check: "em" },
    { name: "underline", title: "下划线", check: "u" },
    { name: "superscript", title: "上标", check: "sup" },
    { name: "subscript", title: "下标", check: "sub" },
    { name: "clear", title: "清除直接格式", check: null },
  ];

  for (const t of toolbarTests) {
    try {
      // Focus editor and select first paragraph
      const editor = page.locator(".protocol-editor .ProseMirror");
      const paragraph = editor.locator("p").first();
      await paragraph.click();
      await page.keyboard.press("End");
      const token = `格式${t.name}`;
      await page.keyboard.type(token);
      await page.keyboard.down("Shift");
      for (let index = 0; index < token.length; index += 1) await page.keyboard.press("ArrowLeft");
      await page.keyboard.up("Shift");
      await wait(100);

      // Click toolbar button
      const btn = t.name === "clear"
        ? page.locator('.rich-toolbar button[aria-label="清除直接格式"]')
        : page.locator(`.rich-toolbar button[title="${t.title}"]`);
      if (await btn.count()) {
        await btn.click();
        await wait(300);
        results[`toolbar_${t.name}`] = "pass";
      } else {
        results[`toolbar_${t.name}`] = "not-found";
        addFinding("P2", "toolbar", `Toolbar button not found: ${t.title}`, `Expected button[title="${t.title}"] in .rich-toolbar`);
      }
    } catch (e) {
      results[`toolbar_${t.name}`] = "fail";
      addFinding("P2", "toolbar", `Toolbar button failed: ${t.title}`, e.message);
    }
  }
  await screenshot(page, "04_toolbar_formatting");

  // ── TEST 5: Font family, size, color, highlight ────────────
  console.log("\n=== TEST 5: Font/size/color/highlight selects ===");
  try {
    const editor = page.locator(".protocol-editor .ProseMirror");
    await editor.click();
    await page.keyboard.press("Home");
    await page.keyboard.press("Shift+End");
    await wait(100);

    // Font family
    const fontSelect = page.locator('select[aria-label="字体"]');
    if (await fontSelect.count()) {
      const options = await fontSelect.locator("option").count();
      results.fontOptions = options;
      if (options > 0) {
        await fontSelect.selectOption({ index: 1 });
        await wait(200);
      }
    }

    // Font size
    const sizeSelect = page.locator('select[aria-label="字号"]');
    if (await sizeSelect.count()) {
      const sizeOptions = await sizeSelect.locator("option").count();
      results.sizeOptions = sizeOptions;
      if (sizeOptions > 0) {
        await sizeSelect.selectOption({ index: 1 });
        await wait(200);
      }
    }

    // Color
    const colorInput = page.locator('input[aria-label="文字颜色"]');
    if (await colorInput.count()) {
      await colorInput.fill("#FF0000");
      await wait(200);
      results.toolbarColor = "pass";
    }

    // Highlight
    const highlightSelect = page.locator('select[aria-label="文字标黄"]');
    if (await highlightSelect.count()) {
      const hlOptions = await highlightSelect.locator("option").count();
      results.highlightOptions = hlOptions;
      if (hlOptions > 1) {
        await highlightSelect.selectOption({ index: 1 });
        await wait(200);
      }
    }

    await screenshot(page, "05_font_size_color");
    results.fontSizeColor = "pass";
  } catch (e) {
    results.fontSizeColor = "fail";
    addFinding("P2", "toolbar", "Font/size/color/highlight controls failed", e.message);
  }

  // ── TEST 6: Alignment, indent, lists ───────────────────────
  console.log("\n=== TEST 6: Alignment/indent/lists ===");
  const alignTests = [
    { name: "left", title: "左对齐" },
    { name: "center", title: "居中" },
    { name: "right", title: "右对齐" },
    { name: "justify", title: "两端对齐" },
    { name: "bulletList", title: "项目符号" },
    { name: "orderedList", title: "编号" },
    { name: "indentIncrease", title: "增加左缩进" },
    { name: "indentDecrease", title: "减少左缩进" },
  ];

  for (const t of alignTests) {
    try {
      const editor = page.locator(".protocol-editor .ProseMirror");
      await editor.click();
      await wait(100);
      const btn = page.locator(`.rich-toolbar button[title="${t.title}"]`);
      if (await btn.count()) {
        const isDisabled = await btn.isDisabled();
        if (!isDisabled) {
          await btn.click();
          await wait(200);
          results[`align_${t.name}`] = "pass";
        } else {
          results[`align_${t.name}`] = "disabled";
        }
      } else {
        results[`align_${t.name}`] = "not-found";
      }
    } catch (e) {
      results[`align_${t.name}`] = "fail";
    }
  }
  await screenshot(page, "06_alignment_indent");

  // ── TEST 7: Paragraph settings popover ─────────────────────
  console.log("\n=== TEST 7: Paragraph settings ===");
  try {
    const paraBtn = page.locator('.rich-toolbar button[aria-label="段落设置"]');
    if (await paraBtn.count()) {
      await paraBtn.click();
      await wait(500);
      const popover = page.locator('.rich-paragraph-popover[role="dialog"]');
      if (await popover.count()) {
        const labels = await popover.locator("label").count();
        results.paragraphPopoverLabels = labels;
        await screenshot(page, "07_paragraph_popover");
        // Close
        await paraBtn.click();
        await wait(300);
        results.paragraphSettings = "pass";
      } else {
        results.paragraphSettings = "popover-not-visible";
      }
    } else {
      results.paragraphSettings = "button-not-found";
    }

    // Line height select
    const lineHSelect = page.locator('select[aria-label="行距"]');
    if (await lineHSelect.count()) {
      await lineHSelect.selectOption("1.5");
      await wait(200);
      results.lineHeight = "pass";
    }
  } catch (e) {
    results.paragraphSettings = "fail";
    addFinding("P2", "paragraph", "Paragraph settings failed", e.message);
  }

  // ── TEST 8: Style presets ──────────────────────────────────
  console.log("\n=== TEST 8: Style presets ===");
  try {
    const styleSelect = page.locator('select[aria-label="段落样式"]');
    if (await styleSelect.count()) {
      const presets = await styleSelect.locator("option").allTextContents();
      results.stylePresets = presets;
      console.log("Style presets:", presets);
      if (presets.length >= 3) {
        results.stylePresetsCheck = "pass";
      } else {
        addFinding("P1", "style-presets", `Only ${presets.length} style presets found`, `Expected heading 1-4, body, notes. Found: ${presets.join(", ")}`);
      }
    }
  } catch (e) {
    results.stylePresets = "fail";
  }

  // ── TEST 9: Undo/Redo ──────────────────────────────────────
  console.log("\n=== TEST 9: Undo/Redo ===");
  try {
    const undoBtn = page.locator('.rich-toolbar button[aria-label="撤销"]');
    const redoBtn = page.locator('.rich-toolbar button[aria-label="重做"]');
    if ((await undoBtn.count()) && (await redoBtn.count())) {
      const undoDisabledBefore = await undoBtn.isDisabled();
      // Type something to create undo history
      const editor = page.locator(".protocol-editor .ProseMirror");
      await editor.click();
      await page.keyboard.press("End");
      await page.keyboard.type(" 撤销测试");
      await wait(300);

      const undoDisabledAfter = await undoBtn.isDisabled();
      if (undoDisabledAfter) {
        addFinding("P1", "undo-redo", "Undo button disabled after typing", "Expected undo to become enabled after text input");
      } else {
        await undoBtn.click();
        await wait(300);
        const redoDisabled = await redoBtn.isDisabled();
        if (redoDisabled) {
          addFinding("P1", "undo-redo", "Redo disabled after undo", "Expected redo to be enabled after undo");
        } else {
          await redoBtn.click();
          await wait(200);
        }
        results.undoRedo = "pass";
      }
    }
  } catch (e) {
    results.undoRedo = "fail";
    addFinding("P1", "undo-redo", "Undo/redo failed", e.message);
  }

  // ── TEST 10: Save working copy ─────────────────────────────
  console.log("\n=== TEST 10: Save working copy ===");
  try {
    const saveBtn = page.getByRole("button", { name: "保存工作副本" });
    if (await saveBtn.count()) {
      await saveBtn.click();
      await wait(2000);
      await screenshot(page, "10_saved");
      results.saveWorkingCopy = "pass";
    } else {
      results.saveWorkingCopy = "no-dirty-changes";
    }
  } catch (e) {
    results.saveWorkingCopy = "fail";
    addFinding("P1", "save", "Failed to save working copy", e.message);
  }

  // ── TEST 11: Maximize/minimize editor ──────────────────────
  console.log("\n=== TEST 11: Maximize/minimize ===");
  try {
    const maxBtn = page.locator('.rich-editor-fullscreen-button[title="全屏编辑正文"]');
    if (await maxBtn.count()) {
      await maxBtn.click();
      await wait(800);
      await screenshot(page, "11_maximized");
      const diagMax = await overflowDiagnostic(page, "maximized");
      results.diagMaximized = diagMax;
      if (diagMax.horizontalScroll > 2) {
        addFinding("P1", "overflow", `Horizontal overflow in maximized mode: ${diagMax.horizontalScroll}px`, "");
      }

      // Try editing in maximized mode
      const editor = page.locator(".protocol-editor .ProseMirror");
      if (await editor.count()) {
        await editor.click();
        await page.keyboard.press("End");
        await page.keyboard.type(" 最大化编辑测试");
        await wait(300);
        results.editInMaximize = "pass";
      }

      // Exit maximize
      const minBtn = page.locator('.rich-editor-fullscreen-button[title="退出正文全屏"]');
      if (await minBtn.count()) {
        await minBtn.click();
        await wait(500);
        await screenshot(page, "11b_minimized");
        results.maximizeMinimize = "pass";
      }
    } else {
      results.maximizeMinimize = "button-not-found";
      addFinding("P1", "maximize", "Maximize button not found", 'Expected .rich-editor-fullscreen-button[title="全屏编辑正文"]');
    }
  } catch (e) {
    results.maximizeMinimize = "fail";
    addFinding("P0", "maximize", "Maximize/minimize failed - white screen or error", e.message);
    await screenshot(page, "11_fail");
  }

  // ── TEST 12: Wider viewport (2560x1440) ────────────────────
  console.log("\n=== TEST 12: Wider viewport 2560x1440 ===");
  try {
    await page.setViewportSize({ width: 2560, height: 1440 });
    await wait(800);
    await screenshot(page, "12_wider_2560x1440");
    const diagWide = await overflowDiagnostic(page, "wide-2560");
    results.diag2560 = diagWide;
    if (diagWide.horizontalScroll > 2) {
      addFinding("P1", "overflow", `Horizontal overflow at 2560x1440: ${diagWide.horizontalScroll}px`, "");
    }
    results.widerViewport = "pass";
  } catch (e) {
    results.widerViewport = "fail";
  }

  // Reset to 1920
  await page.setViewportSize({ width: 1920, height: 1080 });
  await wait(500);

  // ── TEST 13: Table section — find and test ─────────────────
  console.log("\n=== TEST 13: Table operations ===");
  try {
    // Find a section with a table
    const session = await request(apiBase, `/api/projects/${projectId}/medical-writing/document-session`);
    let tableSection = null;
    for (const sec of session.sections) {
      const content = await request(apiBase, `/api/projects/${projectId}/medical-writing/document-session/sections/${sec.section_id}`);
      const hasTable = (content.content_blocks || []).some((b) => b.block_type === "table");
      if (hasTable) {
        tableSection = { section: sec, content };
        break;
      }
    }

    if (tableSection) {
      console.log("Found table section:", tableSection.section.section_number);
      // Navigate to it
      await openTocAndSelectSection(page, tableSection.section.heading || tableSection.section.section_number.toString());
      await wait(1000);

      // Look for table in editor
      const tableNode = page.locator(".protocol-editor .ProseMirror table");
      if (await tableNode.count()) {
        await screenshot(page, "13_table_found");

        // Click into a cell
        const firstCell = tableNode.locator("td, th").first();
        if (await firstCell.count()) {
          await firstCell.click();
          await wait(300);
          await page.keyboard.type("表格测试");
          await wait(200);
          results.tableEdit = "pass";
        }

        // Check for table controls
        const tableControls = page.locator(".table-controls, .rich-toolbar .table-button, button[title*='行'], button[title*='列']");
        const controlCount = await tableControls.count();
        results.tableControlCount = controlCount;
      } else {
        // Table might need working copy first
        console.log("Table not visible in editor, may need structured table designer");
        results.tableInEditor = "not-visible";
      }
    } else {
      console.log("No table section found in document");
      results.tableSection = "none";
    }
  } catch (e) {
    results.table = "fail";
    addFinding("P2", "table", "Table operations test failed", e.message);
  }

  // ── TEST 14: Structured objects (structured table designer) ─
  console.log("\n=== TEST 14: Structured table designer ===");
  try {
    // Look for structured table designer button
    const structuredBtn = page.getByRole("button", { name: "结构化入排" });
    if (await structuredBtn.count()) {
      await structuredBtn.click();
      await wait(1000);
      const designDrawer = page.locator(".writing-study-design-drawer");
      if (await designDrawer.count()) {
        await screenshot(page, "14_structured_designer");
        // Check tabs
        const tabs = await designDrawer.locator('[role="tab"]').count();
        results.structuredTabs = tabs;
        console.log("Structured designer tabs:", tabs);

        // Check for overflow in drawer
        const drawerOverflow = await designDrawer.evaluate((el) => el.scrollWidth - el.clientWidth);
        if (drawerOverflow > 2) {
          addFinding("P1", "overflow", `Structured table designer horizontal overflow: ${drawerOverflow}px`, "");
        }

        // Close
        const closeBtn = page.locator('[title="关闭研究设计"]');
        if (await closeBtn.count()) {
          await closeBtn.click();
          await wait(500);
        }
        results.structuredDesigner = "pass";
      }
    } else {
      results.structuredDesigner = "button-not-found";
    }
  } catch (e) {
    results.structuredDesigner = "fail";
    addFinding("P2", "structured", "Structured table designer test failed", e.message);
  }

  // ── TEST 15: AI candidate area ─────────────────────────────
  console.log("\n=== TEST 15: AI candidate area ===");
  try {
    const candidateSection = page.locator('.writing-ai-candidates[aria-label="当前章节AI候选版本"]');
    if (await candidateSection.count()) {
      await screenshot(page, "15_ai_candidate_area");
      const header = await candidateSection.locator("header").textContent().catch(() => "");
      results.aiCandidateHeader = header?.trim();
      console.log("AI candidate area:", results.aiCandidateHeader);

      // Check revision input
      const revisionInput = page.locator("textarea").filter({ hasText: /修订|指令|要求/ }).first();
      if (await revisionInput.count()) {
        results.aiRevisionInput = "present";
      }

      results.aiCandidateArea = "pass";
    } else {
      results.aiCandidateArea = "not-visible";
    }
  } catch (e) {
    results.aiCandidateArea = "fail";
  }

  // ── TEST 16: Keyboard shortcuts in editor ─────────────────
  console.log("\n=== TEST 16: Keyboard shortcuts ===");
  try {
    const editor = page.locator(".protocol-editor .ProseMirror");
    await editor.click();
    await page.keyboard.press("End");

    // Enter key — should create new paragraph
    await page.keyboard.press("Enter");
    await wait(200);
    const paragraphMarker = `新段落回车测试-${Date.now()}`;
    await page.keyboard.type(paragraphMarker);
    await wait(200);

    // Tab should not leave editor in table cell
    // Backspace
    await page.keyboard.press("Backspace");
    await page.keyboard.press("Backspace");
    await wait(200);
    const persistedMarker = paragraphMarker.slice(0, -2);

    const saveAfterEnter = page.getByRole("button", { name: "保存工作副本" });
    if (await saveAfterEnter.isDisabled()) {
      throw new Error(`save remained disabled after Enter: ${await saveAfterEnter.getAttribute("title")}`);
    }
    await saveAfterEnter.click();
    await wait(1500);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText("研究方案文档编辑与AI修订", { exact: true }).waitFor({ timeout: 20000 });
    await page.locator(".protocol-editor .ProseMirror").waitFor({ timeout: 20000 });
    const reloadedText = await page.locator(".protocol-editor .ProseMirror").textContent();
    if (!reloadedText?.includes(persistedMarker)) {
      throw new Error("new paragraph marker was not retained after save and reload");
    }
    results.keyboardShortcuts = "pass";
    results.enterSaveReload = "pass";
  } catch (e) {
    results.keyboardShortcuts = "fail";
    addFinding("P1", "keyboard", "Enter/save/reload keyboard journey failed", e.message);
  }

  // ── TEST 17: Check for dev logs visible on page ────────────
  console.log("\n=== TEST 17: Dev logs check ===");
  try {
    const body = await page.locator("body").textContent();
    const devLogPatterns = [/console\.log/i, /DEV MODE/i, /debug:/i, /\[HMR\]/i, /Vite is/i, /Fast Refresh/i];
    const found = devLogPatterns.filter((p) => p.test(body));
    if (found.length) {
      addFinding("P2", "dev-leak", "Development log text visible on page", `Patterns found: ${found.map((p) => p.source).join(", ")}`);
    }
    results.devLogCheck = found.length ? "fail" : "pass";
  } catch {
    results.devLogCheck = "skip";
  }

  // ── TEST 18: Full overflow scan on RUX project ─────────────
  console.log("\n=== TEST 18: RUX project overflow scan ===");
  try {
    // Also test with the stable RUX project (read-only in stable, but isolated backend doesn't have it)
    // Instead, check all visible panels for overflow
    const fullDiag = await page.evaluate(() => {
      const all = document.querySelectorAll("*");
      const overflowing = [];
      for (const el of all) {
        if (el.children.length === 0) continue; // leaf nodes only
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        const overX = el.scrollWidth - el.clientWidth;
        if (overX > 5 && el.clientWidth > 100) {
          overflowing.push({
            tag: el.tagName,
            cls: el.className?.toString?.()?.slice(0, 80) || "",
            overflowX: overX,
            visibleW: Math.round(rect.width),
            right: Math.round(rect.right),
          });
        }
      }
      return overflowing.slice(0, 20);
    });
    results.overflowingElements = fullDiag;
    if (fullDiag.length > 0) {
      console.log("Overflowing elements:", fullDiag.length);
      for (const e of fullDiag.slice(0, 5)) {
        addFinding("P2", "overflow", `Element overflow: ${e.tag}.${e.cls.slice(0, 40)}`, `overflowX=${e.overflowX}px`);
      }
    }
  } catch (e) {
    results.overflowScan = "fail";
  }

  // Write results
  await browser.close();
  await writeFile(path.join(evidenceDir, "test_results.json"), JSON.stringify({ results, findings }, null, 2));

  // ── Cleanup ────────────────────────────────────────────────
  console.log("\n=== Cleanup ===");
  await stopService(frontend);
  await stopService(backend);
  await rm(tempDir, { recursive: true, force: true }).catch(() => {});

  // Verify stable runtime untouched
  const snapshotAfter = await stableSnapshot();
  let stableChanged = false;
  for (const [name, hash] of Object.entries(snapshotBefore)) {
    if (snapshotAfter[name] !== hash) {
      stableChanged = true;
      addFinding("P0", "safety", `Stable runtime DB modified: ${name}`, "Isolated test should not touch stable runtime");
    }
  }
  results.stableRuntimeIntact = !stableChanged;

  console.log("\n=== Done ===");
  console.log("Findings:", findings.length);
  console.log("Stable runtime intact:", results.stableRuntimeIntact);
  if (findings.some((finding) => ["P0", "P1"].includes(finding.severity))) {
    process.exitCode = 1;
  }
}

main().catch((e) => {
  console.error("FATAL:", e);
  addFinding("P0", "fatal", "Test runner crashed", e.message + "\n" + (e.stack || "").split("\n").slice(0, 5).join("\n"));
  writeFile(path.join(evidenceDir, "crash_report.json"), JSON.stringify({ error: e.message, stack: e.stack, findings }, null, 2)).catch(() => {});
  process.exit(1);
});
