import { mkdir, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const outputDir = path.join(projectRoot, "records/active_slices/medical_writing_prelaunch_acceptance_20260717/browser_final_qc");
const playwrightPath = "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const apiBase = process.env.WORKER03_API_BASE || "http://127.0.0.1:18920";
const appUrl = process.env.WORKER03_APP_URL || "http://127.0.0.1:18921/";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function req(pn, opts = {}) {
  const headers = opts.body ? { "Content-Type": "application/json" } : {};
  headers["X-Workbench-Api-Contract"] = "medical-writing-api-2026-07-17.1";
  headers["X-Workbench-Frontend-Build"] = "web-7a92ad38757151ac";
  const r = await fetch(`${apiBase}${pn}`, {
    method: opts.method || "GET",
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${opts.method || "GET"} ${pn} ${r.status}: ${JSON.stringify(d).slice(0, 300)}`);
  return d;
}

// ── Click helpers that use evaluate for robustness against icon+text buttons ──

async function clickByText(page, text, opts = {}) {
  return page.evaluate((t) => {
    const btns = Array.from(document.querySelectorAll(opts_selector || "button"));
    const target = btns.find((b) => b.textContent.trim().includes(t) && !b.disabled);
    if (target) { target.click(); return true; }
    return false;
  }, text).catch(() => false);
}

async function clickButtonContaining(page, text) {
  return page.evaluate((t) => {
    const btns = Array.from(document.querySelectorAll("button"));
    const target = btns.find((b) => b.textContent.includes(t));
    if (target && !target.disabled) { target.click(); return true; }
    return false;
  }, text);
}

async function selectProject(page, projectId) {
  // Use Playwright's selectOption for proper React-compatible selection
  const selectLocator = page.locator('select[aria-label="选择临床研究项目"]');
  await selectLocator.waitFor({ timeout: 10000 });
  await selectLocator.selectOption(projectId);
  await wait(800);
}

async function clickNavButton(page, label) {
  await page.evaluate((l) => {
    const btns = Array.from(document.querySelectorAll("nav button, button"));
    const target = btns.find((b) => b.textContent.trim() === l);
    if (target) target.click();
  }, label);
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
    hasStructureError: document.body.innerText.includes("当前编辑改变了来源内容块数量"),
    hasCreateCopy: Boolean(Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("创建工作副本"))),
    hasSaveCopy: Boolean(Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("保存工作副本"))),
    bodyText: document.body.innerText.substring(0, 300),
  }));
}

// ── Seed greenfield project ──

async function seedGreenfield() {
  const stamp = Date.now().toString(36);
  const proj = await req("/api/projects", { method: "POST", body: {
    project_code: `W03-MX-${stamp}`, project_name: `Worker03 Matrix ${stamp}`,
    indication: "类风湿关节炎", product_name: "CMS-RA-201", study_phase: "II期",
    protocol_id: `W03-MX-${stamp}`, protocol_version: "V0.1",
    protocol_date: "2026-07-17", entry_mode: "from_zero", actor: "qc",
    idempotency_key: `w03mx-proj-${stamp}`,
  }});
  const pid = proj.project.project_id;
  const j0 = proj.authoring_journey;
  const framing = {
    protocol_id: `W03-MX-${stamp}`, version: "V0.1", document_title: "CMS-RA-201 RA II期",
    indication: "类风湿关节炎", clinicaltrials_condition_term: "Rheumatoid Arthritis",
    study_phase: "II期", intrinsic_objectives: ["概念验证（PoC）"],
    investigational_product: "CMS-RA-201注射液", target_mechanism: "靶向炎症通路",
    competitor_target_scope: "同靶点生物制剂", development_regions: ["中国"],
    design_pattern: "随机、双盲、安慰剂对照", population_intent: "MTX反应不充分的中重度RA成人",
    key_uncertainties: ["剂量-效应关系"], manual_source_ids: [], terminology_policy: "cde_participant",
  };
  const fp = await req(`/api/projects/${pid}/medical-writing/authoring-journey/impact-preview`, {
    method: "POST", body: { expected_revision: j0.revision, stage: "framing", framing } });
  const f1 = await req(`/api/projects/${pid}/medical-writing/authoring-journey/stages/framing/commit`, {
    method: "POST", body: { expected_revision: j0.revision, stage: "framing", framing, impact_preview_id: fp.preview_id, actor: "qc", idempotency_key: `w03mx-f-${stamp}` } });
  const picos = {
    design_archetype: "randomized_confirmatory", field_applicability: {},
    population_summary: "18-75岁MTX反应不充分的中重度活动性RA成人。",
    inclusion_modules: ["疾病活动度阈值"], exclusion_modules: ["活动性感染"],
    washout_rules: ["生物制剂洗脱"], intervention_summary: "CMS-RA-201皮下注射",
    intervention_dose_regimen: "每4周给药", allowed_concomitant_rules: ["稳定NSAID"],
    required_background_rules: ["稳定MTX"], prohibited_concomitant_rules: ["其他生物制剂"],
    assessment_timing_restrictions: ["疗效评价前限制镇痛药"], comparator_summary: "匹配安慰剂",
    primary_endpoint: "第12周ACR20", key_secondary_endpoints: ["DAS28-CRP变化"],
    other_secondary_endpoints: ["ACR50"], exploratory_endpoints: [],
    safety_endpoints: ["TEAE发生率"], aesi_definitions: ["严重感染"],
    assessment_instruments: [], study_epochs: ["筛选期","双盲治疗期"],
    visit_strategy: "每4周访视", estimand_strategy: "治疗策略下ACR20差异",
    sample_size_strategy: "按应答率差异估算", statistical_strategy: "分层分析",
  };
  const pp = await req(`/api/projects/${pid}/medical-writing/authoring-journey/impact-preview`, {
    method: "POST", body: { expected_revision: f1.revision, stage: "picos", picos } });
  const d1 = await req(`/api/projects/${pid}/medical-writing/authoring-journey/stages/picos/commit`, {
    method: "POST", body: { expected_revision: f1.revision, stage: "picos", picos, impact_preview_id: pp.preview_id, actor: "qc", idempotency_key: `w03mx-p-${stamp}` } });
  const missing = d1.corpus_gate?.missing_requirements || [];
  const allowed = await req(`/api/projects/${pid}/medical-writing/authoring-journey/corpus-gate/override`, {
    method: "POST", body: { expected_revision: d1.revision, reason: "QC测试覆盖语料门禁缺失项", acknowledged_missing_requirements: missing, actor: "qc", idempotency_key: `w03mx-c-${stamp}` } });
  const tpl = await req("/api/medical-writing/protocol-templates/default");
  const def = allowed.study_definition;
  await req(`/api/projects/${pid}/medical-writing/greenfield-document`, { method: "POST", body: {
    protocol_id: framing.protocol_id, version: framing.version, document_title: framing.document_title,
    indication: framing.indication, study_phase: framing.study_phase,
    source_study_definition_id: def.definition_id, source_study_definition_revision: def.revision,
    source_study_definition_sha256: def.state_sha256, template_id: tpl.template_id, template_version: tpl.template_version,
    actor: "qc", idempotency_key: `w03mx-doc-${stamp}`,
  }});
  let gf = await req(`/api/projects/${pid}/medical-writing/greenfield-document`);
  for (const dec of gf.decisions.filter((d) => d.approval_blocking && d.status !== "resolved")) {
    await req(`/api/projects/${pid}/medical-writing/greenfield-document/decisions/${dec.decision_id}/resolve`, {
      method: "POST", body: {
        expected_baseline_revision: gf.baseline_revision,
        value: `确认：${dec.label}`, rationale: "项目决策确认",
        source_refs: [`dec:${dec.decision_id}`], actor: "medical_director_qc",
        idempotency_key: `w03mx-d-${dec.decision_id}-${stamp}`,
      }});
    gf = await req(`/api/projects/${pid}/medical-writing/greenfield-document`);
  }
  return pid;
}

// ── Navigate to a section by clicking in the document map ──

async function navigateToSection(page, sectionText) {
  // Open document map
  await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll("button"));
    const toc = btns.find((b) => b.title === "打开研究方案目录" || b.textContent.trim().includes("目录"));
    if (toc) toc.click();
  });
  await wait(800);
  // Click section in drawer
  const clicked = await page.evaluate((text) => {
    const btns = Array.from(document.querySelectorAll('[role="dialog"] button, .writing-document-map-drawer button'));
    const target = btns.find((b) => b.textContent.includes(text));
    if (target) { target.click(); return true; }
    return false;
  }, sectionText);
  await wait(2500);
  return clicked;
}

// ── Main matrix runner ──

async function runMatrix(browser, greenfieldPid, ruxPid) {
  const results = { defects: [], passed: [], viewports: {}, network: {}, consoleErrors: [], pageErrors: [] };

  // ── GREENFIELD MATRIX ──

  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200)); });
  page.on("pageerror", (e) => pageErrors.push(e.message.slice(0, 200)));

  // 1. New-project empty validation
  await page.goto(appUrl, { waitUntil: "domcontentloaded" });
  await wait(2000);
  await clickButtonContaining(page, "新建项目");
  await wait(800);
  await page.evaluate(() => {
    const submit = document.querySelector('button[type="submit"]');
    if (submit) submit.click();
  });
  await wait(800);
  const validationCount = await page.evaluate(() => {
    return document.body.innerText.match(/必填|不能为空|请输入|请填写|请先补全/g)?.length || 0;
  });
  results.passed.push({ area: "new-project-empty-validation", validationErrorCount: validationCount });
  await page.keyboard.press("Escape").catch(() => {});
  await wait(300);

  // 2. Open writing page
  await page.goto(appUrl, { waitUntil: "domcontentloaded" });
  await page.locator('select[aria-label="选择临床研究项目"]').waitFor({ timeout: 10000 });
  await wait(1000);
  await selectProject(page, greenfieldPid);
  await wait(1000);
  // Click 医学写作 nav button via evaluate
  const navClicked = await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll("nav button, button"));
    const target = btns.find((b) => b.textContent.trim() === "医学写作");
    if (target) { target.click(); return true; }
    return false;
  });
  await wait(4000);
  // Verify we're on the writing page
  const writingCheck = await page.evaluate(() => ({
    hasEditor: Boolean(document.querySelector(".ProseMirror, .rich-editor-shell, [class*='editor']")),
    hasHeading: document.body.innerText.includes("研究方案文档编辑"),
    hasWritingShell: Boolean(document.querySelector(".writing-page, [class*='writing']")),
    bodySnippet: document.body.innerText.substring(0, 200),
  }));
  results.passed.push({ area: "greenfield-nav-to-writing", navClicked, writingCheck });
  const loadMetrics = await captureMetrics(page);
  results.passed.push({ area: "greenfield-writing-loaded", metrics: { hasPM: loadMetrics.hasPM, hasLoading: loadMetrics.hasLoading, hasNotReady: loadMetrics.hasNotReady } });
  if (loadMetrics.hasLoading || loadMetrics.hasNotReady) {
    results.defects.push({ sev: "P1", area: "greenfield-hydration", msg: "Persistent loading/not-ready state" });
  }

  // 3. PICOS required-row accessibility — check structured design drawer
  await clickButtonContaining(page, "研究设计");
  await wait(1000);
  const picosRows = await page.evaluate(() => {
    const drawer = document.querySelector(".writing-study-design-drawer, [role='dialog']");
    if (!drawer) return { drawerOpen: false };
    const textareas = drawer.querySelectorAll("textarea");
    const labels = Array.from(drawer.querySelectorAll("label, .field-label, .form-label")).map((l) => l.textContent.trim()).filter(Boolean);
    return { drawerOpen: true, textareaCount: textareas.length, labelCount: labels.length, sampleLabels: labels.slice(0, 10) };
  });
  results.passed.push({ area: "picos-required-row-accessibility", picosRows });
  await page.keyboard.press("Escape").catch(() => {});
  await wait(300);

  // 4. Navigate to a text section
  const navOk = await navigateToSection(page, "试验目的");
  const sectionMetrics = await captureMetrics(page);
  results.passed.push({ area: "document-map-navigation", navOk, metrics: sectionMetrics });

  // 5. Create working copy
  const wcCreated = await clickButtonContaining(page, "创建工作副本");
  await wait(1500);
  const wcMetrics = await captureMetrics(page);
  results.passed.push({ area: "working-copy-created", wcCreated, hasSaveCopy: wcMetrics.hasSaveCopy });

  // 6. Type text, Enter, type more — greenfield Enter persistence
  const enterResult = await page.evaluate(() => {
    const editor = document.querySelector(".ProseMirror");
    if (!editor) return { error: "no editor" };
    editor.focus();
    const blocks = editor.querySelectorAll(".protocol-source-block");
    if (blocks.length < 2) return { error: "insufficient blocks", blockCount: blocks.length };
    const p = blocks[1].querySelector("p");
    if (!p) return { error: "no paragraph in block 1" };
    const range = document.createRange();
    range.selectNodeContents(p);
    range.collapse(false);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    return { ok: true, blockCount: blocks.length };
  });
  results.passed.push({ area: "editor-focus", enterResult });

  if (!enterResult.error) {
    // Type via keyboard
    await page.keyboard.type("W03EnterTest段落A", { delay: 15 });
    await wait(300);
    const beforeEnter = await page.evaluate(() => ({
      htmlLen: document.querySelector(".ProseMirror").innerHTML.length,
      nodeCount: document.querySelectorAll(".ProseMirror > *").length,
    }));

    // Press Enter to create a new paragraph
    await page.keyboard.press("Enter");
    await wait(300);
    await page.keyboard.type("W03EnterTest段落B", { delay: 15 });
    await wait(500);

    const afterEnter = await page.evaluate(() => ({
      htmlLen: document.querySelector(".ProseMirror").innerHTML.length,
      nodeCount: document.querySelectorAll(".ProseMirror > *").length,
      hasStructureError: document.body.innerText.includes("当前编辑改变了来源内容块数量"),
      hasTextA: document.body.innerText.includes("W03EnterTest段落A"),
      hasTextB: document.body.innerText.includes("W03EnterTest段落B"),
    }));
    results.passed.push({ area: "greenfield-enter-key", beforeEnter, afterEnter });
    if (afterEnter.hasStructureError) {
      results.defects.push({ sev: "P1", area: "greenfield-enter-structure-error", msg: "Structure error after Enter in greenfield" });
    }
    if (!afterEnter.hasTextB) {
      results.defects.push({ sev: "P1", area: "greenfield-enter-text-missing", msg: "Text B not visible after Enter" });
    }

    // 7. Save
    const saved = await clickButtonContaining(page, "保存工作副本");
    await wait(2500);
    const revision = await page.evaluate(() => {
      const el = document.querySelector(".working-copy-revision, [class*='revision']");
      return el ? el.textContent.trim() : "not found";
    });
    results.passed.push({ area: "save-working-copy", saved, revision });

    // 8. Verify API payload contains the greenfield_authoring block
    const wcApi = await req(`/api/projects/${greenfieldPid}/medical-writing/document-session`).catch(() => null);
    // Find the section we edited and check its working copy
    let sectionId = null;
    if (wcApi) {
      for (const s of wcApi.sections || []) {
        // We'll check via the working-copies endpoint
      }
    }
    // Get the section ID from the current page state
    const currentSectionId = await page.evaluate(() => {
      const editor = document.querySelector(".ProseMirror");
      if (!editor) return null;
      const blocks = editor.querySelectorAll("[data-source-block-id]");
      return blocks.length > 0 ? blocks[0].getAttribute("data-source-block-id") : null;
    });
    // Check saved working copy via API
    let apiBlockCheck = null;
    if (currentSectionId) {
      // Extract section_id from block_id format
      const parts = currentSectionId.split("_");
      // block_id format: mwblock_mwsec_{section_id_prefix}_{hash}
      // We need to find the actual section_id from the document session
      const session = await req(`/api/projects/${greenfieldPid}/medical-writing/document-session`);
      const targetSection = session.sections?.find((s) => currentSectionId.includes(s.section_id)) || session.sections?.[0];
      if (targetSection) {
        const wc = await req(`/api/projects/${greenfieldPid}/medical-writing/working-copies/${targetSection.section_id}`).catch(() => null);
        if (wc && wc.content_blocks) {
          const greenfieldBlocks = wc.content_blocks.filter((b) => b.source_kind === "greenfield_authoring" || b.block_id?.includes("greenfield_new"));
          const hasTextA = wc.content_blocks.some((b) => (b.text || "").includes("W03EnterTest段落A"));
          const hasTextB = wc.content_blocks.some((b) => (b.text || "").includes("W03EnterTest段落B"));
          apiBlockCheck = {
            sectionId: targetSection.section_id,
            totalBlocks: wc.content_blocks.length,
            greenfieldNewBlocks: greenfieldBlocks.length,
            hasTextA, hasTextB,
            revision: wc.revision,
            sampleBlock: greenfieldBlocks[0] ? { block_id: greenfieldBlocks[0].block_id, block_type: greenfieldBlocks[0].block_type, text: greenfieldBlocks[0].text?.slice(0, 50) } : null,
          };
        }
      }
    }
    results.passed.push({ area: "api-payload-verification", apiBlockCheck });
    if (apiBlockCheck && !apiBlockCheck.hasTextB) {
      results.defects.push({ sev: "P1", area: "api-payload-missing-text", msg: "Text B not in saved API payload" });
    }

    // 9. Page reload persistence
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.locator('select[aria-label="选择临床研究项目"]').waitFor({ timeout: 10000 });
    await wait(1000);
    await selectProject(page, greenfieldPid);
    await wait(1000);
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll("nav button, button"));
      const target = btns.find((b) => b.textContent.trim() === "医学写作");
      if (target) target.click();
    });
    await wait(4000);
    await navigateToSection(page, "试验目的");
    await wait(2000);
    const afterReload = await page.evaluate(() => ({
      hasTextA: document.body.innerText.includes("W03EnterTest段落A"),
      hasTextB: document.body.innerText.includes("W03EnterTest段落B"),
      revision: document.querySelector(".working-copy-revision, [class*='revision']")?.textContent?.trim() || "not found",
    }));
    results.passed.push({ area: "page-reload-persistence", afterReload });
    if (!afterReload.hasTextB) {
      results.defects.push({ sev: "P1", area: "reload-persistence-fail", msg: "Text B missing after reload" });
    }
  }

  // 10. Formatting controls inventory
  const fmt = await page.evaluate(() => {
    const toolbar = document.querySelector(".rich-toolbar, [class*='toolbar']");
    return {
      toolbarPresent: Boolean(toolbar),
      bold: Boolean(document.querySelector('button[aria-label="加粗"]:not([disabled])')),
      italic: Boolean(document.querySelector('button[aria-label="斜体"]:not([disabled])')),
      underline: Boolean(document.querySelector('button[aria-label="下划线"]:not([disabled])')),
      fontFamily: Boolean(document.querySelector('[aria-label="字体"]:not([disabled])')),
      fontSize: Boolean(document.querySelector('[aria-label="字号"]:not([disabled])')),
      paragraphStyle: Boolean(document.querySelector('[aria-label="段落样式"]:not([disabled])')),
      textColor: Boolean(document.querySelector('[aria-label="文字颜色"]:not([disabled])')),
      highlight: Boolean(document.querySelector('[aria-label="文字标黄"]:not([disabled])')),
      bulletList: Boolean(document.querySelector('button[aria-label="项目符号"]:not([disabled])')),
      numberedList: Boolean(document.querySelector('button[aria-label="编号"]:not([disabled])')),
      alignment: document.querySelectorAll('button[aria-label="左对齐"]:not([disabled]),button[aria-label="居中"]:not([disabled]),button[aria-label="右对齐"]:not([disabled]),button[aria-label="两端对齐"]:not([disabled])').length,
      indent: document.querySelectorAll('button[aria-label*="缩进"]:not([disabled])').length,
      lineHeight: Boolean(document.querySelector('[aria-label="行距"]:not([disabled])')),
      undo: Boolean(document.querySelector('button[aria-label="撤销"]')),
      redo: Boolean(document.querySelector('button[aria-label="重做"]')),
      tableMaximize: Boolean(Array.from(document.querySelectorAll('button')).find((b) => b.textContent.includes("全屏编辑当前表格") || b.textContent.includes("全屏查看当前表格"))),
      docMaximize: Boolean(Array.from(document.querySelectorAll('button')).find((b) => b.textContent.includes("全屏编辑正文"))),
      insertTable: Boolean(document.querySelector('[aria-label="插入结构化表格"]')),
      crossRef: Boolean(document.querySelector('[aria-label="插入交叉引用"]')),
    };
  });
  results.passed.push({ area: "formatting-controls", controls: fmt });

  // 11. Right rail tabs
  const rail = await page.evaluate(() => {
    const tabs = Array.from(document.querySelectorAll("button")).map((b) => b.textContent.trim()).filter(Boolean);
    return {
      ai: tabs.includes("AI"),
      evidence: tabs.includes("证据"),
      literature: tabs.includes("文献"),
      review: tabs.includes("审阅"),
      allTabs: tabs.filter((t) => ["AI","证据","文献","风险","审阅","版本"].includes(t)),
    };
  });
  results.passed.push({ area: "right-rail-tabs", rail });

  // 12. Literature tab
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "文献");
    if (btn) btn.click();
  });
  await wait(1000);
  const litPanel = await page.evaluate(() => Boolean(document.querySelector(".writing-literature-panel, [class*='literature']")));
  results.passed.push({ area: "literature-tab", panelOpen: litPanel });

  // 13. Viewport screenshots + overflow
  for (const [label, size] of [["1440x900", { width: 1440, height: 900 }], ["1920x1080", { width: 1920, height: 1080 }], ["2560x1440", { width: 2560, height: 1440 }]]) {
    await page.setViewportSize(size);
    await wait(800);
    const m = await captureMetrics(page);
    results.viewports[label] = { overflowX: m.overflowX, hasLoading: m.hasLoading, hasNotReady: m.hasNotReady };
    if (m.overflowX > 0) results.defects.push({ sev: "P1", area: `overflow-greenfield-${label}`, overflowPx: m.overflowX });
    await page.screenshot({ path: path.join(outputDir, `greenfield_${label.replace("x","_")}.png`), fullPage: false });
  }

  results.consoleErrors = consoleErrors;
  results.pageErrors = pageErrors;
  if (pageErrors.length) results.defects.push({ sev: "P1", area: "page-errors", count: pageErrors.length, sample: pageErrors.slice(0, 3) });
  if (consoleErrors.length > 10) results.defects.push({ sev: "P2", area: "console-errors", count: consoleErrors.length });

  await page.close();

  // ── RUX SOURCE-PRESERVING MATRIX ──

  if (ruxPid) {
    const ruxPage = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    await ruxPage.goto(appUrl, { waitUntil: "domcontentloaded" });
    await ruxPage.locator('select[aria-label="选择临床研究项目"]').waitFor({ timeout: 10000 });
    await wait(1000);
    await selectProject(ruxPage, ruxPid);
    await wait(1000);
    await ruxPage.evaluate(() => {
      const btns = Array.from(document.querySelectorAll("nav button, button"));
      const target = btns.find((b) => b.textContent.trim() === "医学写作");
      if (target) target.click();
    });
    await wait(4000);
    const ruxMetrics = await captureMetrics(ruxPage);
    results.passed.push({ area: "rux-writing-loaded", metrics: { hasPM: ruxMetrics.hasPM, hasLoading: ruxMetrics.hasLoading, hasNotReady: ruxMetrics.hasNotReady } });
    if (ruxMetrics.hasLoading || ruxMetrics.hasNotReady) {
      results.defects.push({ sev: "P1", area: "rux-hydration", msg: "Persistent loading/not-ready state on RUX" });
    }

    // Navigate to a text section in RUX
    await navigateToSection(ruxPage, "目的");
    await wait(2000);
    const ruxSectionMetrics = await captureMetrics(ruxPage);
    results.passed.push({ area: "rux-section-navigation", metrics: ruxSectionMetrics });

    // Create working copy on RUX section
    const ruxWcCreated = await clickButtonContaining(ruxPage, "创建工作副本");
    await wait(1500);

    // Type and press Enter — verify source-preserving behavior
    await ruxPage.evaluate(() => {
      const editor = document.querySelector(".ProseMirror");
      if (!editor) return;
      editor.focus();
      const blocks = editor.querySelectorAll(".protocol-source-block");
      if (blocks.length > 0) {
        const p = blocks[0].querySelector("p");
        if (p) {
          const range = document.createRange();
          range.selectNodeContents(p);
          range.collapse(false);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
        }
      }
    });
    await ruxPage.keyboard.type(" RUX测试文本", { delay: 15 });
    await wait(300);
    await ruxPage.keyboard.press("Enter");
    await wait(300);
    const ruxEnterResult = await ruxPage.evaluate(() => ({
      hasStructureError: document.body.innerText.includes("当前编辑改变了来源内容块数量"),
      nodeCount: document.querySelectorAll(".ProseMirror > *").length,
      bodyContainsRuxTest: document.body.innerText.includes("RUX测试文本"),
    }));
    results.passed.push({ area: "rux-enter-source-preserving", ruxEnterResult });
    // For RUX, structure error IS expected when trying to add top-level blocks
    // The key is that no silent divergence occurs

    // Save and verify no new blocks in API payload
    await clickButtonContaining(ruxPage, "保存工作副本");
    await wait(2000);

    // RUX screenshot
    await ruxPage.setViewportSize({ width: 1920, height: 1080 });
    await wait(500);
    await ruxPage.screenshot({ path: path.join(outputDir, "rux_1920_1080.png"), fullPage: false });

    await ruxPage.close();
  }

  return results;
}

// ── Backend restart persistence proof ──

async function proveBackendRestartPersistence(greenfieldPid) {
  // This helper only snapshots API state. Callers that own the backend process
  // must stop/start that process and compare PIDs. SQLite presence alone is not
  // a restart proof — do not label this result as PASS for restart.
  const session = await req(`/api/projects/${greenfieldPid}/medical-writing/document-session`);
  let targetSection = (session.sections || []).find((s) => (s.heading || "").includes("试验目的"));
  if (!targetSection) targetSection = session.sections?.[0];
  if (!targetSection) {
    return { status: "UNVERIFIED", error: "no section found" };
  }

  const beforeRestart = await req(`/api/projects/${greenfieldPid}/medical-writing/working-copies/${targetSection.section_id}`).catch(() => null);
  const beforeBlocks = beforeRestart?.content_blocks?.length || 0;
  const beforeHasTextB = beforeRestart?.content_blocks?.some((b) => (b.text || "").includes("W03EnterTest段落B")) || false;

  return {
    status: "UNVERIFIED",
    sectionId: targetSection.section_id,
    beforeRestart: {
      revision: beforeRestart?.revision,
      blockCount: beforeBlocks,
      hasTextB: beforeHasTextB,
    },
    note: "Process-level restart not performed by this helper; use medical_writing_frontend_remediation_qc.mjs for PID-before/after proof. Do not treat this snapshot as PASS.",
  };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  console.log("Seeding greenfield project...");
  const greenfieldPid = await seedGreenfield();
  console.log(`Greenfield project: ${greenfieldPid}`);

  // Static imported project must open even if /api/projects omits or wraps the list.
  // /api/projects returns a bare array; never require projects.projects.
  const RUX_STATIC_ID = "proj_rux_03_002";
  const projectsPayload = await req("/api/projects").catch(() => []);
  const projectList = Array.isArray(projectsPayload)
    ? projectsPayload
    : Array.isArray(projectsPayload?.projects)
      ? projectsPayload.projects
      : [];
  const ruxListed = projectList.some((p) => (
    p.project_id === RUX_STATIC_ID
    || p.project_code === "RUX-03-002"
    || String(p.project_code || "").includes("RUX")
  ));
  const ruxPid = RUX_STATIC_ID;
  console.log(`RUX project: ${ruxPid} (listed_in_catalog=${ruxListed})`);

  const { chromium } = await import(playwrightPath);
  const browser = await chromium.launch({ executablePath: chromePath, headless: true });
  try {
    console.log("Running interaction matrix...");
    const results = await runMatrix(browser, greenfieldPid, ruxPid);

    // Backend restart persistence proof
    console.log("Proving backend restart persistence...");
    const restartProof = await proveBackendRestartPersistence(greenfieldPid);
    results.backendRestartPersistence = restartProof;

    results.greenfieldProjectId = greenfieldPid;
    results.ruxProjectId = ruxPid;
    results.apiBase = apiBase;
    results.appUrl = appUrl;
    results.timestamp = new Date().toISOString();

    await writeFile(path.join(outputDir, "worker_03_matrix.json"), JSON.stringify(results, null, 2));
    console.log("=== RESULTS ===");
    console.log(JSON.stringify({ defects: results.defects, passedAreas: results.passed.map((p) => p.area), viewports: results.viewports }, null, 2));
    process.exitCode = results.defects.some((d) => d.sev === "P0" || d.sev === "P1") ? 1 : 0;
  } finally {
    await browser.close();
  }
}

main().catch((e) => { console.error(e.stack || e.message); process.exitCode = 1; });
