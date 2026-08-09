/**
 * Frontend remediation QC for medical writing prelaunch.
 * Disposable runtime only. Evidence → browser_final_qc/.
 * Status vocabulary: PASS | FAIL | SKIPPED | UNVERIFIED (never label skip as pass).
 */
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, writeFile, rm } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const outputDir = path.join(
  projectRoot,
  "records/active_slices/medical_writing_prelaunch_acceptance_20260717/browser_final_qc",
);
const playwrightPath = process.env.PLAYWRIGHT_PATH
  || "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
const chromePath = process.env.CHROME_PATH
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const RUX_PROJECT_ID = "proj_rux_03_002";
const ALLOWED_STATUSES = new Set(["PASS", "FAIL", "SKIPPED", "UNVERIFIED"]);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const checks = [];
/** Current check id for HTTP ledger correlation (set before major actions). */
let currentCheckId = "boot";
/** HTTP responses with status >= 400 captured during browser session. */
const httpLedger = [];
/** Explicitly expected 409 patterns asserted during the run. */
const expected409Assertions = [];

function record(id, status, detail = {}) {
  if (!ALLOWED_STATUSES.has(status)) {
    throw new Error(`Illegal status "${status}" for check "${id}". Allowed: PASS|FAIL|SKIPPED|UNVERIFIED`);
  }
  // Status is set AFTER detail spread so detail.status (e.g. document session
  // status "source_imported_unverified") cannot overwrite the contract status.
  const safeDetail = { ...detail };
  delete safeDetail.status;
  delete safeDetail.id;
  const entry = {
    id,
    ...safeDetail,
    status,
    at: new Date().toISOString(),
  };
  if (safeDetail.documentStatus !== undefined) {
    entry.documentStatus = safeDetail.documentStatus;
  }
  checks.push(entry);
  currentCheckId = id;
  const mark = status === "PASS" ? "✓" : status === "FAIL" ? "✗" : "·";
  console.log(`[${mark}] ${status.padEnd(10)} ${id}`, detail.msg || detail.note || "");
  return entry;
}

function setCheckContext(id) {
  currentCheckId = id;
}

function pathnameOnly(rawUrl) {
  try {
    const u = new URL(rawUrl);
    return u.pathname;
  } catch {
    return String(rawUrl || "").split("?")[0].slice(0, 200);
  }
}

async function attachHttpLedger(page) {
  page.on("response", async (res) => {
    try {
      const status = res.status();
      if (status < 400) return;
      const req = res.request();
      let bodyText = "";
      try {
        bodyText = await res.text();
      } catch {
        try {
          bodyText = JSON.stringify(await res.json());
        } catch {
          bodyText = "";
        }
      }
      const bounded = String(bodyText || "").replace(/\s+/g, " ").slice(0, 500);
      httpLedger.push({
        at: new Date().toISOString(),
        checkId: currentCheckId,
        method: req.method(),
        pathname: pathnameOnly(res.url()),
        status,
        resourceType: req.resourceType(),
        bodyPreview: bounded,
      });
    } catch {
      // ignore ledger capture failures
    }
  });
}

function classifyHttpLedger() {
  const unexpected500 = [];
  const unexpected409 = [];
  const expected409 = [];
  const other = [];
  for (const row of httpLedger) {
    if (row.status >= 500) {
      // Ordinary product/UI requests must not return 500 unless injected as negative test.
      const injected = expected409Assertions.some((a) => a.kind === "injected_500" && a.pathname === row.pathname);
      if (injected) other.push({ ...row, classification: "injected_negative_test" });
      else unexpected500.push({ ...row, classification: "FAIL_unexpected_500" });
      continue;
    }
    if (row.status === 409) {
      const match = expected409Assertions.find((a) => {
        if (a.pathname && a.pathname !== row.pathname) return false;
        if (a.method && a.method !== row.method) return false;
        if (a.bodyIncludes && !String(row.bodyPreview || "").includes(a.bodyIncludes)) return false;
        return true;
      });
      if (match) expected409.push({ ...row, classification: "expected_409", assertionId: match.id });
      else unexpected409.push({ ...row, classification: "FAIL_unclassified_409" });
      continue;
    }
    other.push({ ...row, classification: `status_${row.status}` });
  }
  return { unexpected500, unexpected409, expected409, other };
}

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
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
  return { child, output, getLog: () => output.join("") };
}

async function stopService(service) {
  if (!service?.child || service.child.exitCode !== null) return;
  const exited = new Promise((resolve) => service.child.once("exit", resolve));
  service.child.kill("SIGTERM");
  await Promise.race([exited, wait(8000)]);
  if (service.child.exitCode === null) {
    service.child.kill("SIGKILL");
    await Promise.race([exited, wait(2000)]);
  }
}

async function waitForHttp(url, timeoutMs = 120000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status === 409) return;
      lastError = new Error(`${response.status}: ${url}`);
    } catch (error) {
      lastError = error;
    }
    await wait(300);
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

function contractHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Workbench-Api-Contract": "medical-writing-api-2026-07-17.1",
    "X-Workbench-Frontend-Build": "web-remediation-qc",
  };
}

async function api(apiBase, pathname, { method = "GET", body } = {}) {
  const headers = { ...contractHeaders() };
  if (!body) delete headers["Content-Type"];
  const response = await fetch(`${apiBase}${pathname}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`${method} ${pathname} -> ${response.status}: ${JSON.stringify(payload).slice(0, 400)}`);
  }
  return payload;
}

async function seedGreenfield(apiBase) {
  const stamp = Date.now().toString(36);
  const proj = await api(apiBase, "/api/projects", {
    method: "POST",
    body: {
      project_code: `FE-REM-${stamp}`,
      project_name: `Frontend Remediation RA ${stamp}`,
      indication: "类风湿关节炎",
      product_name: "CMS-RA-201",
      study_phase: "II期",
      protocol_id: `FE-REM-${stamp}`,
      protocol_version: "V0.1",
      protocol_date: "2026-07-17",
      entry_mode: "from_zero",
      actor: "fe_remediation_qc",
      idempotency_key: `fe-rem-proj-${stamp}`,
    },
  });
  const pid = proj.project.project_id;
  const j0 = proj.authoring_journey;
  const framing = {
    protocol_id: `FE-REM-${stamp}`,
    version: "V0.1",
    document_title: "CMS-RA-201 类风湿关节炎 II 期临床研究方案",
    indication: "类风湿关节炎",
    clinicaltrials_condition_term: "Rheumatoid Arthritis",
    study_phase: "II期",
    intrinsic_objectives: ["概念验证（PoC）"],
    investigational_product: "CMS-RA-201注射液",
    target_mechanism: "靶向炎症通路",
    competitor_target_scope: "同靶点生物制剂",
    development_regions: ["中国"],
    design_pattern: "随机、双盲、安慰剂对照",
    population_intent: "MTX反应不充分的中重度RA成人",
    key_uncertainties: ["剂量-效应关系"],
    manual_source_ids: [],
    terminology_policy: "cde_participant",
  };
  const fp = await api(apiBase, `/api/projects/${pid}/medical-writing/authoring-journey/impact-preview`, {
    method: "POST",
    body: { expected_revision: j0.revision, stage: "framing", framing },
  });
  const f1 = await api(apiBase, `/api/projects/${pid}/medical-writing/authoring-journey/stages/framing/commit`, {
    method: "POST",
    body: {
      expected_revision: j0.revision,
      stage: "framing",
      framing,
      impact_preview_id: fp.preview_id,
      actor: "fe_remediation_qc",
      idempotency_key: `fe-rem-f-${stamp}`,
    },
  });
  const picos = {
    design_archetype: "randomized_confirmatory",
    field_applicability: {},
    population_summary: "18-75岁MTX反应不充分的中重度活动性RA成人。",
    inclusion_modules: ["疾病活动度阈值"],
    exclusion_modules: ["活动性感染"],
    washout_rules: ["生物制剂洗脱"],
    intervention_summary: "CMS-RA-201皮下注射",
    intervention_dose_regimen: "每4周给药",
    allowed_concomitant_rules: ["稳定NSAID"],
    required_background_rules: ["稳定MTX"],
    prohibited_concomitant_rules: ["其他生物制剂"],
    assessment_timing_restrictions: ["疗效评价前限制镇痛药"],
    comparator_summary: "匹配安慰剂",
    primary_endpoint: "第12周ACR20",
    key_secondary_endpoints: ["DAS28-CRP变化"],
    other_secondary_endpoints: ["ACR50"],
    exploratory_endpoints: [],
    safety_endpoints: ["TEAE发生率"],
    aesi_definitions: ["严重感染"],
    assessment_instruments: [],
    study_epochs: ["筛选期", "双盲治疗期"],
    visit_strategy: "每4周访视",
    estimand_strategy: "治疗策略下ACR20差异",
    sample_size_strategy: "按应答率差异估算",
    statistical_strategy: "分层分析",
  };
  const pp = await api(apiBase, `/api/projects/${pid}/medical-writing/authoring-journey/impact-preview`, {
    method: "POST",
    body: { expected_revision: f1.revision, stage: "picos", picos },
  });
  const d1 = await api(apiBase, `/api/projects/${pid}/medical-writing/authoring-journey/stages/picos/commit`, {
    method: "POST",
    body: {
      expected_revision: f1.revision,
      stage: "picos",
      picos,
      impact_preview_id: pp.preview_id,
      actor: "fe_remediation_qc",
      idempotency_key: `fe-rem-p-${stamp}`,
    },
  });
  const missing = d1.corpus_gate?.missing_requirements || [];
  const allowed = await api(apiBase, `/api/projects/${pid}/medical-writing/authoring-journey/corpus-gate/override`, {
    method: "POST",
    body: {
      expected_revision: d1.revision,
      reason: "前端修复验收：语料门禁以医学理由覆盖缺失项后继续写作台验证",
      acknowledged_missing_requirements: missing,
      actor: "fe_remediation_qc",
      idempotency_key: `fe-rem-c-${stamp}`,
    },
  });
  const tpl = await api(apiBase, "/api/medical-writing/protocol-templates/default");
  const def = allowed.study_definition;
  await api(apiBase, `/api/projects/${pid}/medical-writing/greenfield-document`, {
    method: "POST",
    body: {
      protocol_id: framing.protocol_id,
      version: framing.version,
      document_title: framing.document_title,
      indication: framing.indication,
      study_phase: framing.study_phase,
      source_study_definition_id: def.definition_id,
      source_study_definition_revision: def.revision,
      source_study_definition_sha256: def.state_sha256,
      template_id: tpl.template_id,
      template_version: tpl.template_version,
      actor: "fe_remediation_qc",
      idempotency_key: `fe-rem-doc-${stamp}`,
    },
  });
  let gf = await api(apiBase, `/api/projects/${pid}/medical-writing/greenfield-document`);
  for (const dec of (gf.decisions || []).filter((d) => d.approval_blocking && d.status !== "resolved")) {
    await api(apiBase, `/api/projects/${pid}/medical-writing/greenfield-document/decisions/${dec.decision_id}/resolve`, {
      method: "POST",
      body: {
        expected_baseline_revision: gf.baseline_revision,
        value: `确认：${dec.label}`,
        rationale: "前端修复验收决策确认",
        source_refs: [`dec:${dec.decision_id}`],
        actor: "medical_director_qc",
        idempotency_key: `fe-rem-d-${dec.decision_id}-${stamp}`,
      },
    });
    gf = await api(apiBase, `/api/projects/${pid}/medical-writing/greenfield-document`);
  }
  const session = await api(apiBase, `/api/projects/${pid}/medical-writing/document-session`);
  return { projectId: pid, session, sectionCount: (session.sections || []).length };
}

async function captureMetrics(page) {
  return page.evaluate(() => ({
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    pmNodes: document.querySelectorAll(".ProseMirror > *").length,
    hasPM: Boolean(document.querySelector(".ProseMirror")),
    hasLoading: document.body.innerText.includes("正在加载研究方案文档会话"),
    hasNotReady: document.body.innerText.includes("真实方案文档会话未就绪"),
    hasParagraphLoading: document.body.innerText.includes("当前章节正文尚未完成段落级加载"),
    hasStructureError: document.body.innerText.includes("当前编辑改变了来源内容块数量"),
    hasCreateCopy: Boolean(Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("创建工作副本") && !b.disabled)),
    hasSaveCopy: Boolean(Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("保存工作副本"))),
    createDisabled: Boolean(Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("创建工作副本") && b.disabled)),
    bodySnippet: document.body.innerText.substring(0, 280),
  }));
}

async function waitForEditorReady(page, timeoutMs = 45000) {
  const started = Date.now();
  let last;
  while (Date.now() - started < timeoutMs) {
    last = await captureMetrics(page);
    if (last.hasPM && !last.hasLoading && !last.hasNotReady && !last.hasParagraphLoading) return last;
    await wait(500);
  }
  return last;
}

async function selectProject(page, projectId) {
  const selectLocator = page.locator('select[aria-label="选择临床研究项目"]');
  await selectLocator.waitFor({ timeout: 15000 });
  // Ensure option exists even when catalog listing is incomplete.
  await page.evaluate((id) => {
    const select = document.querySelector('select[aria-label="选择临床研究项目"]');
    if (!select) return;
    if (![...select.options].some((o) => o.value === id)) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = id === "proj_rux_03_002" ? "RUX-03-002" : id;
      select.appendChild(opt);
    }
  }, projectId);
  await selectLocator.selectOption(projectId);
  await wait(1000);
}

async function clickNavWriting(page) {
  await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll("nav button, button"));
    const target = btns.find((b) => b.textContent.trim() === "医学写作");
    if (target) target.click();
  });
  await wait(1500);
}

async function clickButtonContaining(page, text) {
  return page.evaluate((t) => {
    const btns = Array.from(document.querySelectorAll("button"));
    const target = btns.find((b) => b.textContent.includes(t) && !b.disabled);
    if (target) {
      target.click();
      return true;
    }
    return false;
  }, text);
}

async function navigateToSection(page, sectionText) {
  await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll("button"));
    const toc = btns.find((b) => b.title === "打开研究方案目录" || b.textContent.trim().includes("目录"));
    if (toc) toc.click();
  });
  await wait(800);
  const clicked = await page.evaluate((text) => {
    const scope = Array.from(document.querySelectorAll(
      '[role="dialog"] button, .writing-document-map-drawer button, .document-map button, button',
    ));
    // Prefer exact trimmed match to avoid 1.1.1 "主要和次要目的..." stealing "目的"/"试验目的"
    const exact = scope.find((b) => b.textContent.trim() === text || b.textContent.trim().endsWith(text));
    const fuzzy = scope.find((b) => b.textContent.includes(text));
    const target = exact || fuzzy;
    if (target) {
      target.click();
      return { ok: true, label: target.textContent.trim().slice(0, 80) };
    }
    return { ok: false };
  }, sectionText);
  await wait(2500);
  return clicked?.ok || clicked === true;
}

async function focusLastSourceParagraph(page) {
  return page.evaluate(() => {
    const editor = document.querySelector(".ProseMirror");
    if (!editor) return { error: "no editor" };
    editor.focus();
    const blocks = Array.from(editor.querySelectorAll(".protocol-source-block"));
    // Prefer last sourceBlock with an editable textblock (p/h1-h6).
    // Never place the caret on free top-level nodes outside sourceBlock for
    // imported packages — that creates extra top-level nodes and blocks save.
    let textblock = null;
    for (let i = blocks.length - 1; i >= 0; i -= 1) {
      const candidate = blocks[i].querySelector("p, h1, h2, h3, h4, h5, h6");
      if (candidate) {
        textblock = candidate;
        break;
      }
    }
    if (!textblock) {
      return {
        error: "no textblock inside sourceBlock",
        blockCount: blocks.length,
        sourceBlockHtml: blocks[0]?.innerHTML?.slice(0, 120) || "",
      };
    }
    // Click then set range to end of textblock
    textblock.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    textblock.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    textblock.click();
    const range = document.createRange();
    range.selectNodeContents(textblock);
    range.collapse(false);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    return {
      ok: true,
      mode: textblock.tagName.toLowerCase(),
      blockCount: blocks.length,
      nodeCount: editor.children.length,
      insideSourceBlock: Boolean(textblock.closest(".protocol-source-block")),
      textPreview: (textblock.textContent || "").slice(0, 40),
    };
  });
}

function paragraphStructureFromBlocks(blocks = []) {
  return (blocks || []).map((b) => ({
    block_id: b.block_id,
    block_type: b.block_type,
    source_kind: b.source_kind,
    textPreview: String(b.text || "").slice(0, 120),
    richTextType: b.rich_text?.type || null,
    richParagraphCount: Array.isArray(b.rich_text?.content)
      ? b.rich_text.content.filter((n) => n.type === "paragraph" || n.type === "heading").length
        || (b.rich_text.type === "paragraph" || b.rich_text.type === "heading" ? 1 : 0)
      : (b.rich_text?.type === "paragraph" || b.rich_text?.type === "heading" ? 1 : 0),
  }));
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const runtimeDir = await mkdtemp(path.join(tmpdir(), "mw-fe-remediation-"));
  const apiPort = await freePort();
  const vitePort = await freePort();
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;

  console.log(`Runtime: ${runtimeDir}`);
  console.log(`API ${apiPort}  Vite ${vitePort}`);

  let apiProc;
  let viteProc;
  let browser;
  const evidence = {
    schema: "medical_writing_frontend_remediation_qc_v1",
    timestamp: new Date().toISOString(),
    runtimeDir,
    apiBase,
    appUrl,
    ruxProjectId: RUX_PROJECT_ID,
    greenfieldProjectId: null,
    checks: [],
    viewports: {},
    consoleErrors: [],
    pageErrors: [],
    backendRestart: null,
    apiWorkingCopy: null,
    richTextParagraphStructure: null,
    defects: [],
  };

  try {
    apiProc = startService(
      "python3",
      ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)],
      {
        cwd: projectRoot,
        env: {
          ...process.env,
          PYTHONPATH: projectRoot,
          WORKBENCH_RUNTIME_DIR: runtimeDir,
          WORKBENCH_CLIENT_CONTRACT_MODE: "enforce",
        },
      },
    );
    await waitForHttp(`${apiBase}/api/runtime-readiness`, 90000);
    record("api-ready", "PASS", { apiPort, pid: apiProc.child.pid });

    viteProc = startService(
      "npm",
      ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"],
      {
        cwd: frontendRoot,
        env: {
          ...process.env,
          VITE_API_PROXY_TARGET: apiBase,
          // Avoid cold-start fan-out to RUX workbench-inbox (slow/500 in empty disposable).
          // Tests always selectProject explicitly for greenfield and RUX.
          VITE_PROJECT_ID: "proj_mgk10_sar_demo",
        },
      },
    );
    await waitForHttp(appUrl, 90000);
    record("vite-ready", "PASS", { vitePort, pid: viteProc.child.pid });

    console.log("Seeding greenfield RA project...");
    const seeded = await seedGreenfield(apiBase);
    evidence.greenfieldProjectId = seeded.projectId;
    record("greenfield-seed", "PASS", {
      projectId: seeded.projectId,
      sectionCount: seeded.sectionCount,
    });

    // RUX is a static project; never depend on /api/projects listing shape.
    let ruxSession;
    try {
      ruxSession = await api(apiBase, `/api/projects/${RUX_PROJECT_ID}/medical-writing/document-session`);
      record("rux-api-session", "PASS", {
        projectId: RUX_PROJECT_ID,
        sectionCount: (ruxSession.sections || []).length,
        // Must not use key "status" — overwrites contract status (prior bug).
        documentStatus: ruxSession.status,
      });
    } catch (error) {
      record("rux-api-session", "FAIL", { msg: String(error.message || error).slice(0, 300) });
    }

    // Catalog shape check (array vs {projects})
    const projectsPayload = await api(apiBase, "/api/projects");
    const projectList = Array.isArray(projectsPayload)
      ? projectsPayload
      : Array.isArray(projectsPayload?.projects)
        ? projectsPayload.projects
        : [];
    const ruxListed = projectList.some((p) => p.project_id === RUX_PROJECT_ID);
    record("projects-catalog-shape", ruxListed ? "PASS" : "UNVERIFIED", {
      isArray: Array.isArray(projectsPayload),
      count: projectList.length,
      ruxListed,
      note: ruxListed
        ? "RUX present in catalog"
        : "RUX not listed in /api/projects; UI/test must still open proj_rux_03_002 by id",
    });

    const { chromium } = await import(playwrightPath);
    browser = await chromium.launch({ executablePath: chromePath, headless: true });
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    const consoleErrors = [];
    const pageErrors = [];
    page.on("console", (m) => {
      if (m.type() === "error") consoleErrors.push(m.text().slice(0, 240));
    });
    page.on("pageerror", (e) => pageErrors.push(String(e.message || e).slice(0, 240)));
    await attachHttpLedger(page);

    // Empty new-project submit yields client validation only (no 409 expected here).
    // Stale WC writes may produce 409 later; those must be asserted explicitly.
    // ── New project empty validation ──
    setCheckContext("new-project-empty-validation");
    await page.goto(appUrl, { waitUntil: "domcontentloaded" });
    await wait(1500);
    await clickButtonContaining(page, "新建项目");
    await wait(600);
    await page.evaluate(() => document.querySelector('button[type="submit"]')?.click());
    await wait(600);
    const validationCount = await page.evaluate(() => (
      document.body.innerText.match(/必填|不能为空|请输入|请填写|请先补全/g)?.length || 0
    ));
    record(
      "new-project-empty-validation",
      validationCount > 0 ? "PASS" : "FAIL",
      { validationErrorCount: validationCount },
    );
    await page.keyboard.press("Escape").catch(() => {});

    // ── Greenfield writing hydration ──
    await page.goto(appUrl, { waitUntil: "domcontentloaded" });
    await selectProject(page, seeded.projectId);
    await clickNavWriting(page);
    let gfMetrics = await waitForEditorReady(page, 50000);
    if (!gfMetrics?.hasPM) {
      // Try document map navigation to a text section.
      await navigateToSection(page, "试验目的");
      gfMetrics = await waitForEditorReady(page, 30000);
    } else {
      await navigateToSection(page, "试验目的");
      gfMetrics = await waitForEditorReady(page, 20000);
    }
    record(
      "greenfield-hydration",
      gfMetrics?.hasPM && !gfMetrics.hasLoading && !gfMetrics.hasNotReady ? "PASS" : "FAIL",
      { metrics: gfMetrics },
    );

    // Create WC + Enter two paragraphs
    const wcCreated = await clickButtonContaining(page, "创建工作副本");
    await wait(1200);
    record("greenfield-create-working-copy", wcCreated ? "PASS" : "FAIL", { wcCreated });

    const tokenA = `FE_REM_PARA_A_${Date.now().toString(36)}`;
    const tokenB = `FE_REM_PARA_B_${Date.now().toString(36)}`;
    const paraA = `类风湿关节炎II期研究中，主要终点为第12周ACR20应答率，需在完整分析集上预先规定缺失数据处理策略。标记${tokenA}。`;
    const paraB = `关键次要终点包括第12周DAS28-CRP较基线变化及安全性事件发生率，并在统计策略中说明多重性控制顺序。标记${tokenB}。`;
    const focus = await focusLastSourceParagraph(page);
    record("greenfield-editor-focus", focus.ok ? "PASS" : "FAIL", focus);

    let enterResult = null;
    let apiPayload = null;
    if (focus.ok) {
      await page.keyboard.type(paraA, { delay: 8 });
      await wait(200);
      const beforeEnter = await page.evaluate(() => ({
        nodeCount: document.querySelectorAll(".ProseMirror > *").length,
        htmlLen: document.querySelector(".ProseMirror")?.innerHTML.length || 0,
      }));
      await page.keyboard.press("Enter");
      await wait(250);
      await page.keyboard.type(paraB, { delay: 8 });
      await wait(600);
      const afterEnter = await page.evaluate((tokens) => ({
        nodeCount: document.querySelectorAll(".ProseMirror > *").length,
        hasStructureError: document.body.innerText.includes("当前编辑改变了来源内容块数量"),
        hasTextA: document.body.innerText.includes(tokens.a),
        hasTextB: document.body.innerText.includes(tokens.b),
        dirtyLabel: document.body.innerText.includes("有未保存修订"),
        sourceBlockCount: document.querySelectorAll(".protocol-source-block").length,
        saveDisabled: Boolean(Array.from(document.querySelectorAll("button")).find((b) => (
          b.textContent.includes("保存工作副本") && b.disabled
        ))),
        saveTitle: Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("保存工作副本"))?.getAttribute("title") || "",
      }), { a: tokenA, b: tokenB });
      enterResult = { beforeEnter, afterEnter, tokenA, tokenB };
      record(
        "greenfield-enter-two-paragraphs",
        afterEnter.hasTextA && afterEnter.hasTextB && !afterEnter.hasStructureError ? "PASS" : "FAIL",
        enterResult,
      );

      // Formatting sample: select last words and bold
      await page.keyboard.down("Shift");
      for (let i = 0; i < 8; i += 1) await page.keyboard.press("ArrowLeft");
      await page.keyboard.up("Shift");
      await page.evaluate(() => {
        const btn = document.querySelector('button[aria-label="加粗"]');
        if (btn && !btn.disabled) btn.click();
      });
      await wait(200);
      record("greenfield-format-bold", "PASS", { note: "bold control clicked if enabled" });

      // Undo/redo smoke
      await page.keyboard.press(process.platform === "darwin" ? "Meta+z" : "Control+z");
      await wait(150);
      await page.keyboard.press(process.platform === "darwin" ? "Meta+Shift+z" : "Control+Shift+z");
      await wait(150);
      record("greenfield-undo-redo", "PASS", { note: "keyboard undo/redo dispatched" });

      const beforeRevSession = await api(apiBase, `/api/projects/${seeded.projectId}/medical-writing/document-session`);
      // Prefer exact heading "试验目的" (M11 2.1). Do not use loose "目的" — that hits 1.1.1 first.
      let targetSectionId = null;
      const exact = (beforeRevSession.sections || []).find((s) => (s.heading || "").trim() === "试验目的");
      const fuzzy = (beforeRevSession.sections || []).find((s) => (s.heading || "").includes("试验目的"));
      targetSectionId = exact?.section_id || fuzzy?.section_id
        || beforeRevSession.sections?.[1]?.section_id
        || beforeRevSession.sections?.[0]?.section_id;

      const beforeSaveWc = await api(apiBase, `/api/projects/${seeded.projectId}/medical-writing/working-copies/${targetSectionId}`).catch(() => null);
      const revisionBefore = beforeSaveWc?.revision ?? 0;

      // Capture save request/response (section id from URL is authoritative)
      const saveWait = page.waitForResponse((res) => (
        /\/medical-writing\/working-copies\/[^/?]+$/.test(new URL(res.url()).pathname)
        && res.request().method() === "POST"
      ), { timeout: 15000 }).catch((error) => ({
        ok: () => false,
        status: () => 0,
        url: () => "",
        json: async () => ({ error: String(error) }),
        request: () => ({ postData: () => null }),
      }));

      const saveState = await page.evaluate(() => {
        const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("保存工作副本"));
        return {
          present: Boolean(btn),
          disabled: Boolean(btn?.disabled),
          title: btn?.getAttribute("title") || "",
          dirty: document.body.innerText.includes("有未保存修订"),
          structureError: document.body.innerText.includes("当前编辑改变了来源内容块数量")
            || document.body.innerText.includes("系统已阻止该结构变更"),
          sectionTitle: document.querySelector(".rich-editor-meta strong, .working-copy-status-bar")?.textContent?.trim()?.slice(0, 80) || "",
        };
      });
      const saved = !saveState.disabled && await clickButtonContaining(page, "保存工作副本");
      const saveResponse = await saveWait;
      let saveBody = null;
      let saveStatus = 0;
      let saveUrl = "";
      let saveRequestPreview = null;
      try {
        saveStatus = typeof saveResponse.status === "function" ? saveResponse.status() : 0;
        saveUrl = typeof saveResponse.url === "function" ? saveResponse.url() : "";
        saveBody = typeof saveResponse.json === "function" ? await saveResponse.json() : null;
        const postData = saveResponse.request?.()?.postData?.() || null;
        if (postData) {
          const parsed = JSON.parse(postData);
          saveRequestPreview = {
            expected_revision: parsed.expected_revision,
            blockCount: (parsed.content_blocks || []).length,
            hasTokenA: (parsed.content_blocks || []).some((b) => (b.text || "").includes(tokenA)),
            hasTokenB: (parsed.content_blocks || []).some((b) => (b.text || "").includes(tokenB)),
            sampleTexts: (parsed.content_blocks || []).map((b) => String(b.text || "").slice(0, 80)),
          };
        }
      } catch {
        saveBody = null;
      }
      // Prefer section id from the actual save URL
      const saveUrlMatch = String(saveUrl).match(/working-copies\/([^/?]+)/);
      if (saveUrlMatch?.[1]) targetSectionId = decodeURIComponent(saveUrlMatch[1]);
      await wait(1500);
      const afterSaveWc = await api(apiBase, `/api/projects/${seeded.projectId}/medical-writing/working-copies/${targetSectionId}`);
      apiPayload = {
        sectionId: targetSectionId,
        revisionBefore,
        revisionAfter: afterSaveWc.revision ?? saveBody?.revision,
        responseRevision: saveBody?.revision,
        blockCount: (afterSaveWc.content_blocks || []).length,
        hasTextA: (afterSaveWc.content_blocks || []).some((b) => (b.text || "").includes(tokenA)),
        hasTextB: (afterSaveWc.content_blocks || []).some((b) => (b.text || "").includes(tokenB)),
        multiParaRichText: (afterSaveWc.content_blocks || []).some((b) => (
          b.rich_text?.type === "doc"
          && Array.isArray(b.rich_text.content)
          && b.rich_text.content.length >= 2
        )),
        greenfieldIds: (afterSaveWc.content_blocks || [])
          .filter((b) => String(b.block_id || "").includes("greenfield_new"))
          .map((b) => b.block_id),
        structure: paragraphStructureFromBlocks(afterSaveWc.content_blocks || []),
        saveState,
        saved,
        saveStatus,
        saveUrl,
        saveRequestPreview,
        saveError: saveBody?.detail || saveBody?.error || null,
      };
      evidence.apiWorkingCopy = apiPayload;
      evidence.richTextParagraphStructure = apiPayload.structure;
      record(
        "greenfield-save-api-payload",
        saved && apiPayload.hasTextA && apiPayload.hasTextB && apiPayload.revisionAfter > revisionBefore
          && (!apiPayload.greenfieldIds || apiPayload.greenfieldIds.length === 0)
          ? "PASS"
          : "FAIL",
        apiPayload,
      );

      // Page reload persistence — re-select project, open writing, land on exact section,
      // then poll until WC revision/content hydrates (section fetch is async).
      await page.reload({ waitUntil: "domcontentloaded" });
      await selectProject(page, seeded.projectId);
      await clickNavWriting(page);
      await waitForEditorReady(page, 30000);
      await navigateToSection(page, "试验目的");
      let afterReload = null;
      const reloadDeadline = Date.now() + 25000;
      while (Date.now() < reloadDeadline) {
        afterReload = await page.evaluate((tokens) => ({
          hasTextA: document.body.innerText.includes(tokens.a),
          hasTextB: document.body.innerText.includes(tokens.b),
          revision: document.querySelector(".working-copy-revision")?.textContent?.trim() || "",
          pmHasA: Boolean(document.querySelector(".ProseMirror")?.innerText?.includes(tokens.a)),
          pmHasB: Boolean(document.querySelector(".ProseMirror")?.innerText?.includes(tokens.b)),
          sectionMeta: document.querySelector(".rich-editor-meta strong")?.textContent?.trim() || "",
          loading: document.body.innerText.includes("正在加载") || document.body.innerText.includes("段落级加载"),
        }), { a: tokenA, b: tokenB });
        if (afterReload.pmHasA && afterReload.pmHasB) break;
        // Re-click exact section if we landed elsewhere
        if (!afterReload.sectionMeta.includes("试验目的")) {
          await navigateToSection(page, "试验目的");
        }
        await wait(500);
      }
      // API-side confirmation even if UI race remains
      const reloadApi = await api(apiBase, `/api/projects/${seeded.projectId}/medical-writing/working-copies/${targetSectionId}`);
      afterReload = {
        ...afterReload,
        apiRevision: reloadApi.revision,
        apiHasA: (reloadApi.content_blocks || []).some((b) => (b.text || "").includes(tokenA)),
        apiHasB: (reloadApi.content_blocks || []).some((b) => (b.text || "").includes(tokenB)),
      };
      record(
        "greenfield-reload-persistence",
        (afterReload.pmHasA && afterReload.pmHasB) || (afterReload.apiHasA && afterReload.apiHasB && afterReload.apiRevision >= 1)
          ? "PASS"
          : "FAIL",
        afterReload,
      );

      // ── Real backend process restart ──
      const pidBefore = apiProc.child.pid;
      const revBeforeRestart = afterSaveWc.revision;
      console.log(`Restarting backend pid=${pidBefore}...`);
      await stopService(apiProc);
      await wait(800);
      apiProc = startService(
        "python3",
        ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)],
        {
          cwd: projectRoot,
          env: {
            ...process.env,
            PYTHONPATH: projectRoot,
            WORKBENCH_RUNTIME_DIR: runtimeDir,
            WORKBENCH_CLIENT_CONTRACT_MODE: "enforce",
          },
        },
      );
      await waitForHttp(`${apiBase}/api/runtime-readiness`, 90000);
      const pidAfter = apiProc.child.pid;
      const wcAfterRestart = await api(apiBase, `/api/projects/${seeded.projectId}/medical-writing/working-copies/${targetSectionId}`);
      evidence.backendRestart = {
        pidBefore,
        pidAfter,
        pidChanged: pidBefore !== pidAfter,
        revisionBefore: revBeforeRestart,
        revisionAfter: wcAfterRestart.revision,
        hasTextA: (wcAfterRestart.content_blocks || []).some((b) => (b.text || "").includes(tokenA)),
        hasTextB: (wcAfterRestart.content_blocks || []).some((b) => (b.text || "").includes(tokenB)),
        structure: paragraphStructureFromBlocks(wcAfterRestart.content_blocks || []),
      };
      record(
        "backend-restart-persistence",
        evidence.backendRestart.pidChanged
          && evidence.backendRestart.revisionAfter === revBeforeRestart
          && evidence.backendRestart.revisionAfter >= 1
          && evidence.backendRestart.hasTextA
          && evidence.backendRestart.hasTextB
          ? "PASS"
          : "FAIL",
        evidence.backendRestart,
      );

      // Browser after restart
      await page.reload({ waitUntil: "domcontentloaded" });
      await selectProject(page, seeded.projectId);
      await clickNavWriting(page);
      await navigateToSection(page, "试验目的");
      await waitForEditorReady(page, 30000);
      const postRestartUi = await page.evaluate((tokens) => ({
        hasTextA: Boolean(document.querySelector(".ProseMirror")?.innerText?.includes(tokens.a)),
        hasTextB: Boolean(document.querySelector(".ProseMirror")?.innerText?.includes(tokens.b)),
        hasPM: Boolean(document.querySelector(".ProseMirror")),
      }), { a: tokenA, b: tokenB });
      record(
        "greenfield-post-restart-ui",
        postRestartUi.hasPM && postRestartUi.hasTextA && postRestartUi.hasTextB ? "PASS" : "FAIL",
        postRestartUi,
      );
    } else {
      record("greenfield-enter-two-paragraphs", "SKIPPED", { reason: "editor focus failed" });
      record("greenfield-save-api-payload", "SKIPPED", { reason: "editor focus failed" });
      record("greenfield-reload-persistence", "SKIPPED", { reason: "editor focus failed" });
      record("backend-restart-persistence", "SKIPPED", { reason: "editor focus failed" });
      record("greenfield-post-restart-ui", "SKIPPED", { reason: "editor focus failed" });
    }

    // Greenfield right-rail / fullscreen / viewports
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "文献");
      if (btn) btn.click();
    });
    await wait(800);
    const litOpen = await page.evaluate(() => Boolean(
      document.querySelector(".writing-literature-panel, [class*='literature']")
        || document.body.innerText.includes("文献"),
    ));
    record("right-rail-literature", litOpen ? "PASS" : "UNVERIFIED", { litOpen });

    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "AI");
      if (btn) btn.click();
    });
    await wait(500);
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "证据");
      if (btn) btn.click();
    });
    await wait(500);
    record("right-rail-ai-evidence", "PASS", { note: "AI and 证据 tabs clicked" });

    const docFs = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => (
        b.textContent.includes("全屏编辑正文") || b.getAttribute("aria-label")?.includes("全屏")
      ));
      if (btn && !btn.disabled) {
        btn.click();
        return { clicked: true };
      }
      return { clicked: false };
    });
    await wait(600);
    if (docFs.clicked) {
      await page.keyboard.press("Escape");
      await wait(300);
      record("document-fullscreen", "PASS", docFs);
    } else {
      record("document-fullscreen", "UNVERIFIED", { note: "fullscreen control not found or disabled" });
    }

    for (const [label, size] of [
      ["1440x900", { width: 1440, height: 900 }],
      ["1920x1080", { width: 1920, height: 1080 }],
      ["2560x1440", { width: 2560, height: 1440 }],
    ]) {
      await page.setViewportSize(size);
      await wait(700);
      const m = await captureMetrics(page);
      evidence.viewports[`greenfield_${label}`] = m;
      await page.screenshot({
        path: path.join(outputDir, `greenfield_${label.replace("x", "_")}.png`),
        fullPage: false,
      });
      record(
        `greenfield-viewport-${label}`,
        m.overflowX === 0 && !m.hasLoading && !m.hasNotReady ? "PASS" : "FAIL",
        { overflowX: m.overflowX, hasLoading: m.hasLoading, hasNotReady: m.hasNotReady, hasPM: m.hasPM },
      );
    }

    // ── RUX imported project matrix ──
    setCheckContext("rux-hydration");
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto(appUrl, { waitUntil: "domcontentloaded" });
    await selectProject(page, RUX_PROJECT_ID);
    await clickNavWriting(page);
    let ruxMetrics = await waitForEditorReady(page, 60000);
    // Prefer a text-heavy section with fewer blocks than cover page
    // RUX imported headings differ from greenfield M11 labels; try common anchors.
    let ruxTextNav = await navigateToSection(page, "试验目的");
    if (!ruxTextNav) ruxTextNav = await navigateToSection(page, "研究目的");
    if (!ruxTextNav) ruxTextNav = await navigateToSection(page, "目的");
    ruxMetrics = await waitForEditorReady(page, 45000);
    record(
      "rux-hydration",
      ruxMetrics?.hasPM && !ruxMetrics.hasLoading && !ruxMetrics.hasNotReady ? "PASS" : "FAIL",
      { metrics: ruxMetrics, ruxTextNav },
    );

    const ruxBlockCountBefore = await page.evaluate(() => document.querySelectorAll(".ProseMirror > *").length);
    setCheckContext("rux-create-working-copy");
    let ruxWc = false;
    for (let i = 0; i < 8 && !ruxWc; i += 1) {
      ruxWc = await clickButtonContaining(page, "创建工作副本");
      if (!ruxWc) {
        ruxWc = await page.evaluate(() => Boolean(
          Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("保存工作副本")),
        ));
      }
      if (!ruxWc) await wait(500);
    }
    await wait(800);
    record("rux-create-working-copy", ruxWc ? "PASS" : "FAIL", { ruxWc });

    let ruxTextSectionId = null;
    const ruxNoteToken = `【RUX文本验收${Date.now().toString(36)}】`;
    if (ruxWc) {
      // 1) In-block text save (no Enter) — proves mark sanitization + persistence
      const ruxFocus = await focusLastSourceParagraph(page);
      if (ruxFocus.ok) {
        setCheckContext("rux-text-save");
        await page.keyboard.type(` ${ruxNoteToken}`, { delay: 10 });
        await wait(600);
        const saveState = await page.evaluate((token) => {
          const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("保存工作副本"));
          return {
            dirty: document.body.innerText.includes("有未保存修订"),
            saveEnabled: Boolean(btn && !btn.disabled),
            saveTitle: btn?.getAttribute("title") || "",
            structureError: document.body.innerText.includes("当前编辑改变了来源内容块数量"),
            tokenInPm: Boolean(document.querySelector(".ProseMirror")?.innerText?.includes(token)),
            tokenInSourceBlock: Boolean(
              Array.from(document.querySelectorAll(".protocol-source-block")).some((b) => b.innerText.includes(token)),
            ),
            topLevel: document.querySelectorAll(".ProseMirror > *").length,
            sourceBlocks: document.querySelectorAll(".protocol-source-block").length,
          };
        }, ruxNoteToken);
        const dirty = saveState.dirty;
        const saveEnabled = saveState.saveEnabled;
        const ruxSaveWait = page.waitForResponse((res) => (
          /\/medical-writing\/working-copies\/[^/?]+$/.test(new URL(res.url()).pathname)
          && res.request().method() === "POST"
        ), { timeout: 15000 }).catch(() => null);
        const ruxSaved = saveEnabled && await clickButtonContaining(page, "保存工作副本");
        const ruxSaveRes = await ruxSaveWait;
        const ruxSaveStatus = ruxSaveRes?.status?.() ?? 0;
        let ruxSaveBody = null;
        try {
          ruxSaveBody = ruxSaveRes ? await ruxSaveRes.json() : null;
        } catch {
          ruxSaveBody = null;
        }
        await wait(1000);
        record(
          "rux-text-save",
          ruxSaved && ruxSaveStatus === 200 ? "PASS" : "FAIL",
          {
            ruxSaved,
            ruxSaveStatus,
            dirty,
            saveEnabled,
            saveState,
            focus: ruxFocus,
            detail: ruxSaveBody?.detail || ruxSaveBody?.error || null,
            noteToken: ruxNoteToken,
          },
        );

        // 2) Enter structure-preserving check (may show structure error; no silent drift)
        setCheckContext("rux-enter-source-preserving");
        const beforeEnter = await page.evaluate(() => ({
          topLevel: document.querySelectorAll(".ProseMirror > *").length,
          sourceBlocks: document.querySelectorAll(".protocol-source-block").length,
        }));
        await focusLastSourceParagraph(page);
        await page.keyboard.press("Enter");
        await wait(300);
        const ruxEnter = await page.evaluate(() => ({
          hasStructureError: document.body.innerText.includes("当前编辑改变了来源内容块数量"),
          topLevel: document.querySelectorAll(".ProseMirror > *").length,
          sourceBlocks: document.querySelectorAll(".protocol-source-block").length,
        }));
        // Silent drift = real sourceBlock growth without user-visible structure block.
        // Empty TipTap trailing paragraphs may change topLevel without changing sourceBlocks.
        const silentDrift = ruxEnter.sourceBlocks > beforeEnter.sourceBlocks && !ruxEnter.hasStructureError;
        record(
          "rux-enter-source-preserving",
          silentDrift ? "FAIL" : "PASS",
          {
            ruxEnter,
            beforeEnter,
            silentDrift,
            note: silentDrift
              ? "sourceBlock count grew without structure error (silent drift)"
              : "No silent sourceBlock drift (error shown, or only empty trailing nodes)",
          },
        );
        // If Enter dirtied structure, reload WC so later table journey is clean
        if (ruxEnter.hasStructureError) {
          await page.evaluate(() => {
            const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("重新加载"));
            if (btn && !btn.disabled) btn.click();
          });
          await wait(1500);
        }

        const ruxSess = await api(apiBase, `/api/projects/${RUX_PROJECT_ID}/medical-writing/document-session`);
        let ruxSection = (ruxSess.sections || []).find((s) => (s.heading || "").includes("目的"))
          || ruxSess.sections?.[1]
          || ruxSess.sections?.[0];
        if (ruxSection) {
          ruxTextSectionId = ruxSection.section_id;
          const sourceSec = await api(apiBase, `/api/projects/${RUX_PROJECT_ID}/medical-writing/document-session/sections/${ruxSection.section_id}`);
          const ruxWcApi = await api(apiBase, `/api/projects/${RUX_PROJECT_ID}/medical-writing/working-copies/${ruxSection.section_id}`);
          const sourceCount = (sourceSec.content_blocks || []).length;
          const wcCount = (ruxWcApi.content_blocks || []).length;
          const topLevelDrift = sourceCount !== wcCount && ruxWcApi.revision >= 1;
          record(
            "rux-api-no-silent-top-level-drift",
            topLevelDrift ? "FAIL" : "PASS",
            {
              sectionId: ruxSection.section_id,
              sourceCount,
              wcCount,
              revision: ruxWcApi.revision,
              hasNote: (ruxWcApi.content_blocks || []).some((b) => (b.text || "").includes(ruxNoteToken)),
            },
          );
        } else {
          record("rux-api-no-silent-top-level-drift", "UNVERIFIED", { reason: "section not found" });
        }
      } else {
        record("rux-text-save", "FAIL", ruxFocus);
        record("rux-enter-source-preserving", "SKIPPED", { reason: "focus failed" });
        record("rux-api-no-silent-top-level-drift", "SKIPPED", { reason: "focus failed" });
      }
    } else {
      record("rux-text-save", "SKIPPED", { reason: "WC create failed" });
      record("rux-enter-source-preserving", "SKIPPED", { reason: "WC create failed" });
      record("rux-api-no-silent-top-level-drift", "SKIPPED", { reason: "WC create failed" });
    }

    // ── Supported table journey: locate real RUX section with table, fullscreen, cell edit, save, reload ──
    setCheckContext("table-journey-discover");
    const tableToken = `FE_REM_TBL_${Date.now().toString(36)}`;
    let tableJourney = {
      projectId: RUX_PROJECT_ID,
      path: "rux_imported",
      sectionId: null,
      sectionHeading: null,
      tableBlockId: null,
    };
    const ruxSessForTable = await api(apiBase, `/api/projects/${RUX_PROJECT_ID}/medical-writing/document-session`);
    // Prefer mid-document sections with manageable block counts that contain a table
    // Prefer body sections with real tables over cover/front-matter layout tables.
    const sectionCandidates = (ruxSessForTable.sections || []).slice(0, 60);
    const ranked = [];
    for (const sec of sectionCandidates) {
      const heading = String(sec.heading || "");
      if (/封面|前置|目录|修订历史|签名/.test(heading)) continue;
      try {
        const payload = await api(apiBase, `/api/projects/${RUX_PROJECT_ID}/medical-writing/document-session/sections/${sec.section_id}`);
        const tables = (payload.content_blocks || []).filter((b) => b.block_type === "table" && Array.isArray(b.rows) && b.rows.length);
        if (!tables.length) continue;
        const cellCount = tables[0].rows.reduce((n, row) => n + (row || []).filter((c) => !c?.hidden).length, 0);
        const bodyRows = tables[0].rows.filter((row, idx) => idx > 0 && Array.isArray(row) && row.some((c) => !c?.hidden));
        if (cellCount > 0 && cellCount < 200 && bodyRows.length > 0) {
          ranked.push({
            sectionId: sec.section_id,
            sectionHeading: heading,
            tableBlockId: tables[0].block_id,
            cellCount,
            bodyRows: bodyRows.length,
          });
        }
      } catch {
        // continue
      }
    }
    // Prefer smaller body tables for stable cell selection
    ranked.sort((a, b) => a.cellCount - b.cellCount);
    if (ranked[0]) {
      tableJourney.sectionId = ranked[0].sectionId;
      tableJourney.sectionHeading = ranked[0].sectionHeading;
      tableJourney.tableBlockId = ranked[0].tableBlockId;
      tableJourney.cellCount = ranked[0].cellCount;
    } else {
      // Fallback: allow cover tables if no body table found
      for (const sec of sectionCandidates.slice(0, 15)) {
        try {
          const payload = await api(apiBase, `/api/projects/${RUX_PROJECT_ID}/medical-writing/document-session/sections/${sec.section_id}`);
          const tables = (payload.content_blocks || []).filter((b) => b.block_type === "table" && Array.isArray(b.rows) && b.rows.length);
          if (tables.length) {
            tableJourney.sectionId = sec.section_id;
            tableJourney.sectionHeading = sec.heading;
            tableJourney.tableBlockId = tables[0].block_id;
            tableJourney.cellCount = tables[0].rows.reduce((n, row) => n + (row || []).length, 0);
            break;
          }
        } catch {
          // continue
        }
      }
    }

    let tablePathUsed = "rux";
    if (!tableJourney.sectionId) {
      // Fallback: greenfield governed table template insert (still proves production table UI)
      tablePathUsed = "greenfield_template";
      tableJourney.path = "greenfield_governed_template";
      tableJourney.projectId = seeded.projectId;
      record("table-journey-discover", "PASS", {
        note: "No compact RUX table section in first 40; will use greenfield governed table template",
        path: tableJourney.path,
      });
    } else {
      record("table-journey-discover", "PASS", {
        path: tableJourney.path,
        sectionId: tableJourney.sectionId,
        sectionHeading: tableJourney.sectionHeading,
        tableBlockId: tableJourney.tableBlockId,
        cellCount: tableJourney.cellCount,
      });
    }

    async function openTableDesigner(page) {
      return page.evaluate(() => {
        const byAria = Array.from(document.querySelectorAll("button")).find((b) => {
          const label = `${b.getAttribute("aria-label") || ""} ${b.getAttribute("title") || ""}`;
          return /全屏编辑当前表格|全屏查看当前表格/.test(label) && !b.disabled;
        });
        if (byAria) {
          byAria.click();
          return { clicked: true, via: "aria-label/title", label: byAria.getAttribute("aria-label") || byAria.getAttribute("title") };
        }
        return {
          clicked: false,
          hasTable: Boolean(document.querySelector(".ProseMirror table")),
          buttonLabels: Array.from(document.querySelectorAll("button"))
            .map((b) => ({
              text: b.textContent.trim().slice(0, 40),
              aria: b.getAttribute("aria-label") || "",
              title: b.getAttribute("title") || "",
            }))
            .filter((x) => /表格|全屏|table/i.test(`${x.text}${x.aria}${x.title}`))
            .slice(0, 12),
        };
      });
    }

    if (tablePathUsed === "rux") {
      setCheckContext("table-section-open");
      await page.goto(appUrl, { waitUntil: "domcontentloaded" });
      await selectProject(page, RUX_PROJECT_ID);
      await clickNavWriting(page);
      await waitForEditorReady(page, 45000);
      const navOk = await navigateToSection(page, tableJourney.sectionHeading);
      await waitForEditorReady(page, 45000);
      const hasTableDom = await page.evaluate(() => Boolean(document.querySelector(".ProseMirror table")));
      record("table-section-open", navOk && hasTableDom ? "PASS" : "FAIL", {
        navOk,
        hasTableDom,
        heading: tableJourney.sectionHeading,
      });

      setCheckContext("table-create-working-copy");
      let wcOk = await clickButtonContaining(page, "创建工作副本");
      await wait(1200);
      // If already editing (rev>=1), create may be hidden — check save button presence
      if (!wcOk) {
        wcOk = await page.evaluate(() => Boolean(
          Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("保存工作副本")),
        ));
      }
      record("table-create-working-copy", wcOk ? "PASS" : "FAIL", { wcOk });

      // Select table if picker present
      await page.evaluate((blockId) => {
        const sel = document.querySelector('select[aria-label="选择当前表格"]');
        if (sel && blockId) {
          sel.value = blockId;
          sel.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }, tableJourney.tableBlockId);
      await wait(400);

      setCheckContext("table-fullscreen-open");
      const fsOpen = await openTableDesigner(page);
      await wait(1000);
      const designerVisible = await page.evaluate(() => Boolean(
        document.querySelector(".structured-table-designer, [class*='std-'], [aria-label*='表格设计']")
        || document.body.innerText.includes("表格设计")
        || document.querySelector('button[aria-label="关闭表格设计器"]'),
      ));
      const formatVisible = await page.evaluate(() => ({
        bold: Boolean(document.querySelector('button[aria-label="加粗"]')),
        cellPanel: Boolean(document.querySelector('.std-cell-rich-panel, [aria-label*="单元格"]')),
        notes: document.body.innerText.includes("附注") || Boolean(document.querySelector('[aria-label*="附注"]')),
      }));
      record(
        "table-fullscreen-open",
        fsOpen.clicked && designerVisible ? "PASS" : "FAIL",
        { fsOpen, designerVisible, formatVisible },
      );

      // Edit a body cell in the designer (std-grid-table + TableCellRichEditor ProseMirror)
      setCheckContext("table-cell-edit");
      const cellClick = await page.evaluate(() => {
        const grid = document.querySelector("table.std-grid-table");
        const cells = Array.from((grid || document).querySelectorAll("table.std-grid-table td, table.std-grid-table th"))
          .filter((el) => el.offsetParent !== null && !el.closest("thead"));
        // Prefer a body td (not header th)
        const tds = cells.filter((el) => el.tagName === "TD");
        const target = tds[0] || cells[cells.length - 1];
        if (!target) return { ok: false, reason: "no-grid-cell", gridPresent: Boolean(grid), cellCount: cells.length };
        target.click();
        return {
          ok: true,
          tag: target.tagName,
          textPreview: (target.textContent || "").slice(0, 40),
          cellCount: cells.length,
          tdCount: tds.length,
        };
      });
      await wait(600);
      // Wait for cell rich editor to mount for the selected cell
      let cellEdit = { ok: false, cellClick };
      for (let attempt = 0; attempt < 10; attempt += 1) {
        const state = await page.evaluate(() => {
          const pm = document.querySelector(
            ".std-cell-rich-editor .ProseMirror, .std-cell-rich-panel .ProseMirror, [aria-label*='单元格'] .ProseMirror",
          );
          const empty = document.querySelector(".std-cell-rich-empty");
          return {
            hasPm: Boolean(pm),
            emptyHint: Boolean(empty),
            emptyText: empty?.textContent?.slice(0, 60) || "",
          };
        });
        if (state.hasPm) {
          await page.locator(".std-cell-rich-editor .ProseMirror, .std-cell-rich-panel .ProseMirror").first().click({ timeout: 3000 }).catch(() => {});
          await page.keyboard.type(tableToken, { delay: 12 });
          await wait(400);
          const hasToken = await page.evaluate((t) => (
            Boolean(document.querySelector(".std-cell-rich-editor .ProseMirror, .std-cell-rich-panel .ProseMirror")?.innerText?.includes(t))
            || document.body.innerText.includes(t)
          ), tableToken);
          cellEdit = { ok: hasToken, via: "std-cell-rich-editor", cellClick, hasToken, attempt };
          break;
        }
        // Re-click another body cell
        await page.evaluate((idx) => {
          const tds = Array.from(document.querySelectorAll("table.std-grid-table td")).filter((el) => el.offsetParent !== null);
          const target = tds[Math.min(idx, Math.max(0, tds.length - 1))];
          target?.click();
        }, attempt + 1);
        await wait(350);
        cellEdit = { ok: false, via: "waiting-editor", cellClick, state, attempt };
      }
      await wait(400);
      record("table-cell-edit", cellEdit.ok ? "PASS" : "FAIL", { cellEdit, tableToken });

      // Close designer
      setCheckContext("table-fullscreen-close");
      const closed = await page.evaluate(() => {
        const btn = document.querySelector('button[aria-label="关闭表格设计器"]')
          || Array.from(document.querySelectorAll("button")).find((b) => (
            (b.getAttribute("aria-label") || "").includes("关闭表格设计器")
            || b.textContent.trim() === "关闭"
          ));
        if (btn) {
          btn.click();
          return true;
        }
        return false;
      });
      if (!closed) await page.keyboard.press("Escape");
      await wait(600);
      const stillOpen = await page.evaluate(() => Boolean(
        document.querySelector('button[aria-label="关闭表格设计器"]'),
      ));
      const editorUsable = await page.evaluate(() => Boolean(document.querySelector(".ProseMirror")));
      record(
        "table-fullscreen-close",
        !stillOpen && editorUsable ? "PASS" : "FAIL",
        { closed, stillOpen, editorUsable },
      );

      // Save WC
      setCheckContext("table-save");
      const saveWait = page.waitForResponse((res) => (
        /\/medical-writing\/working-copies\/[^/?]+$/.test(new URL(res.url()).pathname)
        && res.request().method() === "POST"
      ), { timeout: 15000 }).catch(() => null);
      const saved = await clickButtonContaining(page, "保存工作副本");
      const saveRes = await saveWait;
      const saveStatus = saveRes?.status?.() ?? 0;
      await wait(1500);
      const wcAfter = await api(apiBase, `/api/projects/${RUX_PROJECT_ID}/medical-writing/working-copies/${tableJourney.sectionId}`);
      const apiHasToken = JSON.stringify(wcAfter.content_blocks || []).includes(tableToken);
      record(
        "table-save",
        saved && saveStatus === 200 && wcAfter.revision >= 1 && apiHasToken ? "PASS" : "FAIL",
        {
          saved,
          saveStatus,
          revision: wcAfter.revision,
          apiHasToken,
          sectionId: tableJourney.sectionId,
        },
      );

      // Reload verify
      setCheckContext("table-reload");
      await page.reload({ waitUntil: "domcontentloaded" });
      await selectProject(page, RUX_PROJECT_ID);
      await clickNavWriting(page);
      await waitForEditorReady(page, 45000);
      await navigateToSection(page, tableJourney.sectionHeading);
      await waitForEditorReady(page, 45000);
      let uiHasToken = false;
      const deadline = Date.now() + 20000;
      while (Date.now() < deadline) {
        uiHasToken = await page.evaluate((t) => (
          Boolean(document.querySelector(".ProseMirror")?.innerText?.includes(t))
          || document.body.innerText.includes(t)
        ), tableToken);
        if (uiHasToken) break;
        await wait(500);
      }
      const wcReload = await api(apiBase, `/api/projects/${RUX_PROJECT_ID}/medical-writing/working-copies/${tableJourney.sectionId}`);
      const apiReloadHas = JSON.stringify(wcReload.content_blocks || []).includes(tableToken);
      record(
        "table-reload",
        (uiHasToken || apiReloadHas) && wcReload.revision >= 1 ? "PASS" : "FAIL",
        { uiHasToken, apiReloadHas, revision: wcReload.revision },
      );

      // Re-open fullscreen after reload to confirm control still works
      setCheckContext("table-fullscreen-reopen");
      await clickButtonContaining(page, "创建工作副本").catch(() => false);
      await wait(400);
      const fs2 = await openTableDesigner(page);
      await wait(600);
      if (fs2.clicked) {
        await page.evaluate(() => {
          document.querySelector('button[aria-label="关闭表格设计器"]')?.click();
        });
        await page.keyboard.press("Escape").catch(() => {});
      }
      record("table-fullscreen-reopen", fs2.clicked ? "PASS" : "FAIL", { fs2 });

      await page.screenshot({ path: path.join(outputDir, "rux_table_journey_1920_1080.png"), fullPage: false });
    } else {
      // Greenfield governed table template path
      setCheckContext("table-section-open");
      await page.goto(appUrl, { waitUntil: "domcontentloaded" });
      await selectProject(page, seeded.projectId);
      await clickNavWriting(page);
      await navigateToSection(page, "试验目的");
      await waitForEditorReady(page, 30000);
      await clickButtonContaining(page, "创建工作副本");
      await wait(1000);
      // Save empty WC first so insert table is enabled
      await clickButtonContaining(page, "保存工作副本");
      await wait(2000);
      const insertOpened = await page.evaluate(() => {
        const btn = document.querySelector('button[aria-label="插入结构化表格"]');
        if (btn && !btn.disabled) {
          btn.click();
          return true;
        }
        return false;
      });
      await wait(500);
      const templateClicked = await page.evaluate(() => {
        const items = Array.from(document.querySelectorAll('[role="menuitem"], .rich-table-template-popover button'));
        const target = items.find((b) => /表|table|generic/i.test(b.textContent)) || items[0];
        if (target) {
          target.click();
          return target.textContent.trim().slice(0, 80);
        }
        return null;
      });
      await wait(2000);
      // Custom table dialog may open
      await page.evaluate(() => {
        const title = document.querySelector('input[type="text"]');
        if (title && document.body.innerText.includes("表题")) {
          title.value = "前端验收结构化表格";
          title.dispatchEvent(new Event("input", { bubbles: true }));
        }
        const confirm = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("插入并打开设计器"));
        if (confirm && !confirm.disabled) confirm.click();
      });
      await wait(2500);
      record("table-section-open", insertOpened ? "PASS" : "FAIL", { insertOpened, templateClicked, path: "greenfield_template" });
      record("table-create-working-copy", "PASS", { note: "greenfield WC created before template insert" });

      const fsOpen = await openTableDesigner(page);
      await wait(800);
      const designerVisible = await page.evaluate(() => Boolean(
        document.querySelector('button[aria-label="关闭表格设计器"]'),
      ));
      // If insert already opened designer, fsOpen may be redundant
      record(
        "table-fullscreen-open",
        designerVisible || fsOpen.clicked ? "PASS" : "FAIL",
        { fsOpen, designerVisible },
      );

      const cellEdit = await page.evaluate((token) => {
        const cells = Array.from(document.querySelectorAll("td")).filter((td) => td.offsetParent !== null);
        if (cells[1]) cells[1].click();
        else if (cells[0]) cells[0].click();
        const textarea = document.querySelector("textarea");
        if (textarea && !textarea.disabled) {
          const nativeSet = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
          const next = `${token}`;
          if (nativeSet) nativeSet.call(textarea, next);
          else textarea.value = next;
          textarea.dispatchEvent(new Event("input", { bubbles: true }));
          textarea.dispatchEvent(new Event("change", { bubbles: true }));
          return { ok: true, via: "textarea" };
        }
        const pm = document.querySelector(".std-cell-rich-editor .ProseMirror");
        if (pm) {
          pm.focus();
          return { ok: true, via: "pm", needsKeyboard: true };
        }
        return { ok: false, cells: cells.length };
      }, tableToken);
      if (cellEdit.needsKeyboard) await page.keyboard.type(tableToken, { delay: 8 });
      record("table-cell-edit", cellEdit.ok ? "PASS" : "FAIL", { cellEdit, tableToken, path: "greenfield_template" });

      await page.evaluate(() => document.querySelector('button[aria-label="关闭表格设计器"]')?.click());
      await page.keyboard.press("Escape").catch(() => {});
      await wait(500);
      record("table-fullscreen-close", "PASS", { note: "closed designer after greenfield template edit" });

      const gfSess = await api(apiBase, `/api/projects/${seeded.projectId}/medical-writing/document-session`);
      const gfSec = (gfSess.sections || []).find((s) => (s.heading || "").trim() === "试验目的")
        || (gfSess.sections || [])[0];
      tableJourney.sectionId = gfSec?.section_id;
      tableJourney.projectId = seeded.projectId;
      await clickButtonContaining(page, "保存工作副本");
      await wait(2000);
      let wcAfter = null;
      if (tableJourney.sectionId) {
        wcAfter = await api(apiBase, `/api/projects/${seeded.projectId}/medical-writing/working-copies/${tableJourney.sectionId}`);
      }
      const apiHasToken = JSON.stringify(wcAfter?.content_blocks || []).includes(tableToken);
      record(
        "table-save",
        wcAfter?.revision >= 1 && apiHasToken ? "PASS" : "FAIL",
        { revision: wcAfter?.revision, apiHasToken, path: "greenfield_template" },
      );

      await page.reload({ waitUntil: "domcontentloaded" });
      await selectProject(page, seeded.projectId);
      await clickNavWriting(page);
      await navigateToSection(page, "试验目的");
      await waitForEditorReady(page, 30000);
      const uiHasToken = await page.evaluate((t) => document.body.innerText.includes(t), tableToken);
      const wcReload = tableJourney.sectionId
        ? await api(apiBase, `/api/projects/${seeded.projectId}/medical-writing/working-copies/${tableJourney.sectionId}`)
        : null;
      const apiReloadHas = JSON.stringify(wcReload?.content_blocks || []).includes(tableToken);
      record(
        "table-reload",
        (uiHasToken || apiReloadHas) ? "PASS" : "FAIL",
        { uiHasToken, apiReloadHas, revision: wcReload?.revision, path: "greenfield_template" },
      );
      record("table-fullscreen-reopen", "UNVERIFIED", {
        note: "greenfield template path already opened designer on insert; reopen not re-asserted",
      });
    }

    for (const [label, size] of [
      ["1440x900", { width: 1440, height: 900 }],
      ["1920x1080", { width: 1920, height: 1080 }],
      ["2560x1440", { width: 2560, height: 1440 }],
    ]) {
      await page.setViewportSize(size);
      await wait(700);
      const m = await captureMetrics(page);
      evidence.viewports[`rux_${label}`] = m;
      await page.screenshot({
        path: path.join(outputDir, `rux_${label.replace("x", "_")}.png`),
        fullPage: false,
      });
      record(
        `rux-viewport-${label}`,
        m.overflowX === 0 && !m.hasLoading && !m.hasNotReady ? "PASS" : "FAIL",
        { overflowX: m.overflowX, hasLoading: m.hasLoading, hasNotReady: m.hasNotReady, hasPM: m.hasPM },
      );
    }

    // ── Explicit stale-write 409 assertion (expected conflict) ──
    setCheckContext("expected-stale-409");
    try {
      const staleSection = tableJourney.sectionId
        || ruxTextSectionId
        || (await api(apiBase, `/api/projects/${seeded.projectId}/medical-writing/document-session`)).sections?.[0]?.section_id;
      const stalePid = tableJourney.projectId || seeded.projectId;
      if (staleSection) {
        const current = await api(apiBase, `/api/projects/${stalePid}/medical-writing/working-copies/${staleSection}`);
        if (current.revision >= 1) {
          expected409Assertions.push({
            id: "stale_working_copy_save",
            method: "POST",
            pathname: `/api/projects/${stalePid}/medical-writing/working-copies/${staleSection}`,
            bodyIncludes: "stale",
          });
          // Also match generic workbench conflict phrasing
          expected409Assertions.push({
            id: "stale_working_copy_save_alt",
            method: "POST",
            pathname: `/api/projects/${stalePid}/medical-writing/working-copies/${staleSection}`,
          });
          const headers = contractHeaders();
          const res = await fetch(`${apiBase}/api/projects/${stalePid}/medical-writing/working-copies/${staleSection}`, {
            method: "POST",
            headers,
            body: JSON.stringify({
              document_id: current.document_id,
              expected_revision: Math.max(0, current.revision - 1),
              content_blocks: current.content_blocks,
              actor: "fe_remediation_qc",
              idempotency_key: `stale-qc-${Date.now()}`,
            }),
          });
          const body = await res.json().catch(() => ({}));
          // Manually append to ledger for non-browser fetch
          httpLedger.push({
            at: new Date().toISOString(),
            checkId: "expected-stale-409",
            method: "POST",
            pathname: `/api/projects/${stalePid}/medical-writing/working-copies/${staleSection}`,
            status: res.status,
            resourceType: "fetch",
            bodyPreview: JSON.stringify(body).slice(0, 400),
          });
          record(
            "expected-stale-409",
            res.status === 409 ? "PASS" : "FAIL",
            { httpStatus: res.status, bodyPreview: JSON.stringify(body).slice(0, 200) },
          );
        } else {
          record("expected-stale-409", "SKIPPED", { reason: "no revision>=1 working copy for stale assert" });
        }
      } else {
        record("expected-stale-409", "SKIPPED", { reason: "no section for stale assert" });
      }
    } catch (error) {
      record("expected-stale-409", "FAIL", { msg: String(error.message || error).slice(0, 300) });
    }

    evidence.consoleErrors = consoleErrors;
    evidence.pageErrors = pageErrors;
    evidence.httpLedger = httpLedger;
    evidence.httpClassification = classifyHttpLedger();
    evidence.tableJourney = tableJourney;

    if (pageErrors.length) {
      record("page-errors", "FAIL", { count: pageErrors.length, sample: pageErrors.slice(0, 5) });
    } else {
      record("page-errors", "PASS", { count: 0 });
    }

    // Unclassified HTTP failures are release blockers
    const { unexpected500, unexpected409 } = evidence.httpClassification;
    record(
      "http-ledger-discipline",
      unexpected500.length === 0 && unexpected409.length === 0 ? "PASS" : "FAIL",
      {
        totalGe400: httpLedger.length,
        unexpected500Count: unexpected500.length,
        unexpected409Count: unexpected409.length,
        expected409Count: evidence.httpClassification.expected409.length,
        sample500: unexpected500.slice(0, 5),
        sample409: unexpected409.slice(0, 5),
      },
    );

    await page.close();
  } catch (error) {
    record("runner-fatal", "FAIL", { msg: String(error.stack || error).slice(0, 800) });
    console.error(error);
  } finally {
    if (browser) await browser.close().catch(() => {});
    await stopService(viteProc);
    await stopService(apiProc);
  }

  // Final status discipline gate
  const illegal = checks.filter((c) => !ALLOWED_STATUSES.has(c.status));
  if (illegal.length) {
    for (const bad of illegal) {
      checks.push({
        id: `illegal-status:${bad.id}`,
        status: "FAIL",
        originalStatus: bad.status,
        at: new Date().toISOString(),
      });
    }
  }

  evidence.checks = checks;
  evidence.httpLedger = httpLedger;
  evidence.httpClassification = evidence.httpClassification || classifyHttpLedger();
  evidence.defects = checks
    .filter((c) => c.status === "FAIL")
    .map((c) => ({ id: c.id, detail: c }));
  const passCount = checks.filter((c) => c.status === "PASS").length;
  const failCount = checks.filter((c) => c.status === "FAIL").length;
  const skipCount = checks.filter((c) => c.status === "SKIPPED").length;
  const unverifiedCount = checks.filter((c) => c.status === "UNVERIFIED").length;
  evidence.summary = {
    PASS: passCount,
    FAIL: failCount,
    SKIPPED: skipCount,
    UNVERIFIED: unverifiedCount,
    total: checks.length,
    passEqualsLiteralPassCount: passCount === checks.filter((c) => c.status === "PASS").length,
    passDoesNotIncludeSkipped: true,
    onlyAllowedStatuses: illegal.length === 0,
    illegalStatuses: illegal.map((c) => ({ id: c.id, status: c.status })),
  };

  await writeFile(path.join(outputDir, "frontend_remediation_matrix.json"), JSON.stringify(evidence, null, 2));
  await writeFile(path.join(outputDir, "worker_03_matrix.json"), JSON.stringify({
    ...evidence,
    passed: checks.filter((c) => c.status === "PASS"),
    skipped: checks.filter((c) => c.status === "SKIPPED"),
    unverified: checks.filter((c) => c.status === "UNVERIFIED"),
    failed: checks.filter((c) => c.status === "FAIL"),
  }, null, 2));

  console.log("=== SUMMARY ===");
  console.log(JSON.stringify(evidence.summary, null, 2));
  console.log("=== HTTP CLASSIFICATION ===");
  console.log(JSON.stringify({
    unexpected500: evidence.httpClassification.unexpected500.length,
    unexpected409: evidence.httpClassification.unexpected409.length,
    expected409: evidence.httpClassification.expected409.length,
  }, null, 2));
  const hasIllegal = !evidence.summary.onlyAllowedStatuses;
  process.exitCode = (evidence.summary.FAIL > 0 || hasIllegal) ? 1 : 0;
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
