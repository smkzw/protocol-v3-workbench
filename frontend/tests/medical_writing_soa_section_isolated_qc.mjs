import { spawn, execFile as execFileCallback } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFile, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

if (process.env.QC_ISOLATED_RUNTIME !== "1") {
  throw new Error("medical_writing_soa_section_isolated_qc.mjs mutates runtime state and requires QC_ISOLATED_RUNTIME=1");
}

const execFile = promisify(execFileCallback);
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const evidenceDir = path.join(projectRoot, "records/active_slices/medical_writing_soa_section_runtime_routing_20260717/browser_qc");
const playwrightPath = process.env.PLAYWRIGHT_PATH || "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const pythonBin = process.env.PYTHON_BIN || "python3";
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const SOA_TEMPLATE_ID = "schedule_of_activities";
const LOADING_TEXTS = ["正在加载研究方案文档会话。", "版本读取中"];
const FORBIDDEN_DOCX_TEXT = ["表格内容略", "未渲染", "|---"];
const VIEWPORTS = [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
];

// Read-only original sources, pinned by real_protocol_table_rendering_validation.json.
const ORIGINAL_SOURCES = {
  d001: {
    key: "d001",
    projectId: "proj_d001",
    docxPath: "/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/CMS-D001 银屑病2、3期临床方案 v1.0-2025.12.21.docx",
    sha256: "362443131f0d384c82c80f6a37396084f7d3301b51162201749c0488b0f2dd98",
    expectedExportedTableCount: 24,
  },
  pnh: {
    key: "pnh",
    projectId: "proj_my008_pnh_3_01",
    docxPath: "/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/3-01（MM外包）/方案/V1.1方案/（缺含研究者签字页方案）MY008211A-PNH-3-01-V1.1-通用版-2024.11.24-clean/研究方案/MY008211A-PNH-3-01_研究方案_V1.1_2025.1.7clean.docx",
    sha256: "265858e23249191d382775882c2d6be539e1e88f084fc0e8c4816cb715460aed",
    expectedExportedTableCount: 24,
  },
};

async function sha256File(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

async function freePort(preferred) {
  const open = (port) => new Promise((resolve, reject) => {
    const server = net.createServer(); server.unref(); server.once("error", reject);
    server.listen(port, "127.0.0.1", () => { const selected = server.address().port; server.close(() => resolve(selected)); });
  });
  try { return await open(preferred); } catch { return open(0); }
}

function startService(command, args, options) {
  const output = [];
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
  const collect = (chunk) => { output.push(String(chunk)); if (output.length > 300) output.shift(); };
  child.stdout.on("data", collect); child.stderr.on("data", collect);
  return { child, output };
}

async function stopService(service) {
  if (!service?.child || service.child.exitCode !== null) return;
  const exited = new Promise((resolve) => service.child.once("exit", resolve));
  service.child.kill("SIGTERM"); await Promise.race([exited, wait(5000)]);
  if (service.child.exitCode === null) service.child.kill("SIGKILL");
}

async function waitForHttp(url, timeoutMs = 120000) {
  const started = Date.now(); let lastError;
  while (Date.now() - started < timeoutMs) {
    try { const response = await fetch(url); if (response.ok) return; lastError = new Error(`${response.status}: ${url}`); }
    catch (error) { lastError = error; }
    await wait(250);
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

async function request(apiBase, pathname, { method = "GET", body, allowStatus } = {}) {
  const response = await fetch(`${apiBase}${pathname}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok && response.status !== allowStatus) {
    throw new Error(`${method} ${pathname} -> ${response.status}: ${JSON.stringify(payload)}`);
  }
  return { status: response.status, payload, headers: response.headers };
}

// Discover the live stable API sqlite files from the actual 8911 process (lsof), never from
// relative-path arithmetic. Union with <workspace>/runtime as a second guard surface.
async function discoverStableDbFiles() {
  const files = new Set();
  try {
    const { stdout: pidOut } = await execFile("sh", ["-c", "lsof -nP -iTCP:8911 -sTCP:LISTEN -t | head -1"]);
    const pid = pidOut.trim();
    if (pid) {
      const { stdout } = await execFile("sh", ["-c", `lsof -a -p ${pid} -d REG -Fn 2>/dev/null | grep -E '\\.sqlite3(-wal|-shm)?$' | sed 's/^n//'`]);
      for (const line of stdout.split("\n")) { const f = line.trim(); if (f) files.add(f); }
    }
  } catch { /* stable process discovery failed; workspace union still applies */ }
  try {
    const wsRuntime = path.join(projectRoot, "runtime");
    for (const name of await readdir(wsRuntime)) {
      if (/\.sqlite3(-wal|-shm)?$/.test(name)) files.add(path.join(wsRuntime, name));
    }
  } catch { /* no workspace runtime dir */ }
  return [...files].sort();
}

async function hashFiles(files) {
  const result = {};
  for (const file of files) {
    try { result[file] = await sha256File(file); } catch { result[file] = "<unreadable>"; }
  }
  return result;
}

async function seedSyntheticSoaProject(apiBase, template, key) {
  const actor = "medical_manager_qc";
  const created = await request(apiBase, "/api/projects", { method: "POST", body: {
    project_code: `QC-SOA-${key.toUpperCase()}`,
    project_name: `QC SoA章节直达隔离验收 ${key}`,
    indication: "斑块状银屑病",
    product_name: "CMS-QC-SOA片",
    study_phase: "II期",
    protocol_id: `QC-SOA-${key.toUpperCase()}`,
    protocol_version: "V0.1",
    protocol_date: "2026-07-17",
    entry_mode: "from_zero",
    actor,
    idempotency_key: `soa-qc-project-${key}`,
  } });
  const projectId = created.payload.project.project_id;
  const initial = created.payload.authoring_journey;
  const framing = {
    protocol_id: `QC-SOA-${key.toUpperCase()}`, version: "V0.1",
    document_title: `CMS-QC-SOA片治疗斑块状银屑病的II期临床研究方案（${key}）`,
    indication: "斑块状银屑病", clinicaltrials_condition_term: "Plaque Psoriasis", study_phase: "II期",
    intrinsic_objectives: ["剂量探索"], investigational_product: "CMS-QC-SOA片",
    target_mechanism: "创新小分子免疫调节剂", competitor_target_scope: "同适应症口服创新疗法",
    development_regions: ["中国"], design_pattern: "随机、双盲、安慰剂对照的II期研究",
    population_intent: "中重度斑块状银屑病成人试验参与者", key_uncertainties: ["剂量选择"],
    manual_source_ids: [], terminology_policy: "cde_participant",
  };
  const picos = {
    design_archetype: "randomized_confirmatory", field_applicability: {},
    population_summary: "中重度斑块状银屑病成人试验参与者。",
    inclusion_modules: ["PASI和PGA达到方案规定严重程度"], exclusion_modules: ["活动性感染"],
    washout_rules: ["既往生物制剂按方案规定完成洗脱"],
    intervention_summary: "CMS-QC-SOA片按随机分组口服给药。",
    intervention_dose_regimen: "按方案给药；剂量调整规则单列。",
    allowed_concomitant_rules: ["方案允许的稳定外用保湿剂"], required_background_rules: [],
    prohibited_concomitant_rules: ["其他系统性银屑病治疗"],
    assessment_timing_restrictions: ["PASI评价前按方案限制外用治疗。"],
    comparator_summary: "匹配安慰剂对照。", primary_endpoint: "方案规定时间点达到PASI 75的试验参与者比例。",
    key_secondary_endpoints: ["方案规定时间点达到PGA 0/1的试验参与者比例。"],
    other_secondary_endpoints: [], exploratory_endpoints: [],
    safety_endpoints: ["TEAE和SAE发生率。"], aesi_definitions: ["严重感染"],
    assessment_instruments: [], study_epochs: ["筛选期", "治疗期", "随访期"],
    visit_strategy: "按研究流程表执行筛选、基线和治疗期访视。",
    estimand_strategy: "主要估计目标评价随机治疗策略下PASI应答差异。",
    sample_size_strategy: "依据PASI 75应答率差异估算。",
    statistical_strategy: "分类终点采用分层方法比较，并预设多重性控制。",
  };
  const framingPreview = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`, { method: "POST", body: { expected_revision: initial.revision, stage: "framing", framing } });
  const framed = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/stages/framing/commit`, { method: "POST", body: { expected_revision: initial.revision, stage: "framing", framing, impact_preview_id: framingPreview.payload.preview_id, actor, idempotency_key: `soa-qc-framing-${key}` } });
  const picosPreview = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`, { method: "POST", body: { expected_revision: framed.payload.revision, stage: "picos", picos } });
  const designed = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/stages/picos/commit`, { method: "POST", body: { expected_revision: framed.payload.revision, stage: "picos", picos, impact_preview_id: picosPreview.payload.preview_id, actor, idempotency_key: `soa-qc-picos-${key}` } });
  const missing = designed.payload.corpus_gate?.missing_requirements || [];
  const allowed = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/corpus-gate/override`, { method: "POST", body: { expected_revision: designed.payload.revision, reason: "隔离环境验证研究流程表章节直达、受控创建、保存重载与DOCX导出链路。", acknowledged_missing_requirements: missing, actor, idempotency_key: `soa-qc-corpus-${key}` } });
  const definition = allowed.payload.study_definition;
  if (!definition) throw new Error(`${key}: StudyDefinition was not produced`);
  await request(apiBase, `/api/projects/${projectId}/medical-writing/greenfield-document`, { method: "POST", body: {
    protocol_id: allowed.payload.framing.protocol_id, version: allowed.payload.framing.version,
    document_title: allowed.payload.framing.document_title, indication: allowed.payload.framing.indication,
    study_phase: allowed.payload.framing.study_phase,
    source_study_definition_id: definition.definition_id,
    source_study_definition_revision: definition.revision,
    source_study_definition_sha256: definition.state_sha256,
    template_id: template.template_id, template_version: template.template_version,
    actor, idempotency_key: `soa-qc-document-${key}`,
  } });
  let greenfieldState = await request(apiBase, `/api/projects/${projectId}/medical-writing/greenfield-document`);
  for (const decision of greenfieldState.payload.decisions.filter((item) => item.approval_blocking && item.status !== "resolved")) {
    await request(apiBase, `/api/projects/${projectId}/medical-writing/greenfield-document/decisions/${decision.decision_id}/resolve`, { method: "POST", body: {
      expected_baseline_revision: greenfieldState.payload.baseline_revision,
      value: `项目团队已确认：${decision.label}按当前方案框架执行。`,
      rationale: "基于隔离QC项目设计讨论、医学与统计联合评估形成当前决策。",
      source_refs: [`project_decision:${key}:${decision.decision_id}:20260717`],
      actor: "medical_director_qc",
      idempotency_key: `soa-qc-decision-${key}-${decision.decision_id}`,
    } });
    greenfieldState = await request(apiBase, `/api/projects/${projectId}/medical-writing/greenfield-document`);
  }
  const session = await request(apiBase, `/api/projects/${projectId}/medical-writing/document-session`);
  const section = session.payload.sections.find((item) => item.section_number === "1.3");
  if (!section) {
    throw new Error(`${key}: M11 section 1.3 not found; sections=${session.payload.sections.map((item) => item.section_number).join(",")}`);
  }
  return { key, projectId, section };
}

// ---------- browser helpers ----------

async function openWriting(page, appUrl, projectId) {
  await page.goto(appUrl, { waitUntil: "domcontentloaded" });
  const select = page.locator('select[aria-label="选择临床研究项目"]');
  await select.waitFor();
  await select.selectOption(projectId);
  await page.getByRole("button", { name: "医学写作" }).click();
  await page.getByText("研究方案文档编辑与AI修订", { exact: true }).waitFor();
}

async function waitEditorIdle(page, timeoutMs = 45000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const busy = await page.evaluate((texts) => {
      const body = document.body.textContent || "";
      return texts.some((text) => body.includes(text));
    }, LOADING_TEXTS);
    if (!busy) return;
    await wait(250);
  }
  throw new Error(`Editor still shows a loading state after ${timeoutMs}ms (${LOADING_TEXTS.join(" / ")})`);
}

async function openSectionViaMap(page, heading) {
  const searchText = String(heading || "").trim();
  await page.getByRole("button", { name: "目录" }).click();
  const drawer = page.locator(".writing-document-map-drawer");
  await drawer.waitFor();
  await drawer.locator('input[placeholder="搜索章节标题"]').fill(searchText);
  const candidates = drawer.locator(".writing-section-buttons > button");
  try {
    await candidates.first().waitFor({ timeout: 15000 });
  } catch (error) {
    const available = (await drawer.innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 400);
    throw new Error(`section map has no entry for heading "${searchText}"; drawer=${available}`);
  }
  let chosen = candidates.first();
  const count = await candidates.count();
  for (let index = 0; index < count; index += 1) {
    const text = await candidates.nth(index).innerText();
    if (text.includes(searchText)) { chosen = candidates.nth(index); break; }
  }
  await chosen.click();
  await waitEditorIdle(page);
}

async function sectionTableCount(page) {
  return page.locator(".protocol-editor table[data-source-block-id]").count();
}

async function assertVisualState(page, evidenceDirPath, name, failures) {
  const shots = {};
  for (const viewport of VIEWPORTS) {
    await page.setViewportSize(viewport);
    await wait(150);
    const metrics = await page.evaluate((texts) => {
      const body = document.body.textContent || "";
      return {
        pageOverflowX: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) - window.innerWidth,
        loading: texts.some((text) => body.includes(text)),
      };
    }, LOADING_TEXTS);
    if (metrics.loading) failures.push(`${name}:loading-state-visible@${viewport.width}x${viewport.height}`);
    if (metrics.pageOverflowX > 0) failures.push(`${name}:horizontal-overflow-${metrics.pageOverflowX}px@${viewport.width}x${viewport.height}`);
    const file = path.join(evidenceDirPath, `${name}_${viewport.width}x${viewport.height}.png`);
    await page.screenshot({ path: file, fullPage: false });
    shots[`${viewport.width}x${viewport.height}`] = { file: path.basename(file), ...metrics };
  }
  return shots;
}

async function clickEntryButton(page) {
  const entry = page.locator("button.writing-structured-design-trigger").filter({ hasText: "研究流程表" });
  await entry.waitFor();
  await entry.click();
}

const createDialog = (page) => page.locator('section.rich-table-insert-dialog[aria-label="创建研究流程表"]');
const chooserDialog = (page) => page.locator('section.rich-table-insert-dialog[aria-label="选择要打开的研究流程表"]');
const duplicateDialog = (page) => page.locator('section.rich-table-insert-dialog[aria-label="确认重复插入结构化表格"]');
const designer = (page) => page.locator("section.structured-table-designer");
const tablePicker = (page) => page.locator('select[aria-label="选择当前表格"]');

async function closeDesigner(page) {
  if (await designer(page).count()) {
    await page.locator('button[aria-label="关闭表格设计器"]').click();
    await designer(page).waitFor({ state: "detached" });
  }
}

async function workingCopyRevisionText(page) {
  return (await page.locator(".working-copy-revision").innerText()).trim();
}

async function soaStructuredBlocks(apiBase, projectId, sectionId) {
  const copy = await request(apiBase, `/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`);
  const blocks = copy.payload.content_blocks || [];
  return {
    revision: copy.payload.revision,
    approvalState: copy.payload.approval_state,
    soaBlocks: blocks.filter((block) => block.block_type === "table"
      && (block.template_id === SOA_TEMPLATE_ID || block.structured_table?.domain === SOA_TEMPLATE_ID)),
    tableBlocks: blocks.filter((block) => block.block_type === "table"),
    blocks,
  };
}

async function docxInspect(docxPath, needles, forbidden) {
  const py = [
    "import json,sys",
    "from docx import Document",
    "d=Document(sys.argv[1])",
    "needles=[n for n in sys.argv[2].split('\\u0001') if n]",
    "forb=[f for f in sys.argv[3].split('\\u0001') if f]",
    "cells='\\n'.join((c.text or '') for t in d.tables for r in t.rows for c in r.cells)",
    "paras='\\n'.join((p.text or '') for p in d.paragraphs)",
    "out={'table_count':len(d.tables),'cell_hits':{n:(n in cells) for n in needles},'para_hits':{n:(n in paras) for n in needles},'forbidden_hits':[f for f in forb if (f in cells or f in paras)]}",
    "print(json.dumps(out))",
  ].join("\n");
  const { stdout } = await execFile(pythonBin, ["-c", py, docxPath, needles.join(""), forbidden.join("")]);
  return JSON.parse(stdout);
}

async function exportDraftDocx(apiBase, projectId, targetPath) {
  const response = await fetch(`${apiBase}/api/projects/${projectId}/medical-writing/document.docx?mode=draft_preview`);
  if (!response.ok) throw new Error(`draft_preview export -> ${response.status}`);
  const tableCount = response.headers.get("x-medical-writing-table-count");
  await writeFile(targetPath, Buffer.from(await response.arrayBuffer()));
  return { path: targetPath, tableCountHeader: tableCount };
}

// ---------- real imported project flow (D001 / PNH) ----------

async function runRealProjectFlow(page, apiBase, appUrl, source, sessionInfo, report, failures) {
  const entry = { branch_source: "real", projectId: source.projectId, screenshots: {}, skipped: [] };
  report.projects[source.key] = entry;
  await openWriting(page, appUrl, source.projectId);
  await page.setViewportSize(VIEWPORTS[0]);
  const soaSection = sessionInfo.soaSection;
  if (!soaSection) {
    entry.skipped.push("no SoA-like section (heading /流程表/ or section_number 1.x) discovered in cold session; discovery evidence recorded");
    return;
  }
  entry.soaSection = soaSection;
  await openSectionViaMap(page, soaSection.heading);
  await waitEditorIdle(page);
  const domTableCount = await sectionTableCount(page);
  entry.domTableCount = domTableCount;
  if (domTableCount !== soaSection.tableBlockCount) {
    failures.push(`${source.key}:dom-table-count ${domTableCount} != api ${soaSection.tableBlockCount}`);
  }
  const bindingPresent = soaSection.interactionTypes.includes("schedule_of_activities_editor");
  entry.interactionBinding = bindingPresent ? "schedule_of_activities_editor" : "absent";
  const entryButton = page.locator("button.writing-structured-design-trigger").filter({ hasText: "研究流程表" });
  if (bindingPresent) {
    await entryButton.waitFor({ state: "visible", timeout: 15000 }).catch(() => {});
  }
  const entryVisible = await entryButton.count();
  entry.entryButtonVisible = Boolean(entryVisible);

  if (bindingPresent && entryVisible && soaSection.tableBlockCount >= 1) {
    // B1/B2 on real data: native tables are class-2 pending-mapping candidates.
    entry.branch = soaSection.tableBlockCount === 1 ? "B1_real" : "B2_real";
    const instantiateBefore = report.instantiateRequests.length;
    await clickEntryButton(page);
    if (soaSection.tableBlockCount === 1) {
      await designer(page).waitFor();
      if (await chooserDialog(page).count()) failures.push(`${source.key}:B1 unexpected chooser dialog`);
      if (await createDialog(page).count()) failures.push(`${source.key}:B1 unexpected create dialog`);
    } else {
      await chooserDialog(page).waitFor();
      const candidateButtons = chooserDialog(page).locator("button[data-soa-candidate-block-id]");
      const candidateCount = await candidateButtons.count();
      entry.chooserCandidateCount = candidateCount;
      if (candidateCount !== soaSection.tableBlockCount) failures.push(`${source.key}:chooser candidates ${candidateCount} != tables ${soaSection.tableBlockCount}`);
      const active = await page.evaluate(() => document.activeElement?.getAttribute?.("data-soa-candidate-block-id"));
      if (active) failures.push(`${source.key}:chooser preselected candidate ${active}`);
      const badges = await chooserDialog(page).locator("button[data-soa-candidate-block-id] span").allInnerTexts();
      entry.chooserBadges = badges;
      if (!badges.some((text) => text.includes("待人工确认映射"))) failures.push(`${source.key}:chooser missing pending-mapping badge`);
      await candidateButtons.nth(candidateCount - 1).click();
      await designer(page).waitFor();
    }
    if (report.instantiateRequests.length !== instantiateBefore) failures.push(`${source.key}:entry open fired instantiate (must be non-mutating)`);
    const pickerValue = await tablePicker(page).inputValue();
    entry.designerFocusedBlockId = pickerValue;
    const pendingBadge = await designer(page).locator(".std-pending").count();
    const buildMappingButton = await designer(page).getByRole("button", { name: "建立待确认映射" }).count();
    entry.pendingMappingEvidence = { pendingBadge, buildMappingButton };
    if (!pendingBadge && !buildMappingButton) failures.push(`${source.key}:designer shows no pending-mapping state for source-native table`);
    entry.screenshots.designer = await assertVisualState(page, evidenceDir, `${source.key}_soa_designer`, failures);
    await closeDesigner(page);
  } else {
    entry.skipped.push(`entry path inapplicable on real data: binding=${bindingPresent} entryVisible=${entryVisible} tables=${soaSection.tableBlockCount}`);
    if (bindingPresent && soaSection.tableBlockCount >= 1 && !entryVisible) {
      failures.push(`${source.key}:schedule_of_activities_editor binding present but section entry button is not visible`);
    }
    if (!bindingPresent) {
      entry.productGap = "imported 1.3-like SoA section lacks schedule_of_activities_editor interaction binding; structured entry button not expected";
    }
    // Read-only picker path evidence: open the first native table in the designer.
    if (domTableCount >= 1) {
      const firstBlockId = await tablePicker(page).locator("option").first().getAttribute("value");
      await tablePicker(page).selectOption(firstBlockId);
      const fullscreen = page.locator('button[aria-label="全屏查看当前表格"], button[aria-label="全屏编辑当前表格结构与附注"]');
      await fullscreen.first().click();
      await designer(page).waitFor();
      entry.pickerDesignerBlockId = firstBlockId;
      entry.domainLabel = (await designer(page).locator(".std-domain-label").innerText().catch(() => "")).trim();
      entry.pendingMappingEvidence = {
        pendingBadge: await designer(page).locator(".std-pending").count(),
        buildMappingButton: await designer(page).getByRole("button", { name: "建立待确认映射" }).count(),
      };
      entry.screenshots.picker_designer = await assertVisualState(page, evidenceDir, `${source.key}_picker_designer`, failures);
      await closeDesigner(page);
    }
  }

  // Working copy create + save + reload persistence.
  const createCopy = page.getByRole("button", { name: "创建工作副本" });
  if (await createCopy.count()) {
    await createCopy.click();
    const saveCopy = page.getByRole("button", { name: "保存工作副本" });
    await saveCopy.waitFor(); await saveCopy.click();
    await page.getByText("版本 1", { exact: true }).waitFor();
    entry.savedRevision = await workingCopyRevisionText(page);
    entry.screenshots.saved = await assertVisualState(page, evidenceDir, `${source.key}_saved_v1`, failures);
    await openWriting(page, appUrl, source.projectId);
    await openSectionViaMap(page, soaSection.heading);
    const restored = await workingCopyRevisionText(page);
    entry.reloadedRevision = restored;
    if (restored !== "版本 1") failures.push(`${source.key}:revision did not persist after reload: ${restored}`);
  } else {
    entry.skipped.push("创建工作副本 button not present (already has working copy or gated)");
  }

  // Draft DOCX export: whole-document source table survival.
  const docxPath = path.join(evidenceDir, `${source.key}_draft_preview.docx`);
  const exported = await exportDraftDocx(apiBase, source.projectId, docxPath);
  const inspection = await docxInspect(docxPath, [], FORBIDDEN_DOCX_TEXT);
  entry.docx = { file: path.basename(docxPath), tableCountHeader: exported.tableCountHeader, tableCount: inspection.table_count, forbiddenHits: inspection.forbidden_hits };
  if (inspection.table_count !== source.expectedExportedTableCount) {
    failures.push(`${source.key}:exported table count ${inspection.table_count} != expected ${source.expectedExportedTableCount}`);
  }
  if (inspection.forbidden_hits.length) failures.push(`${source.key}:forbidden DOCX text ${inspection.forbidden_hits.join(",")}`);
}

// ---------- synthetic greenfield flows (Z create / B1 unique / B2 multiple / duplicate / edit / save / reload / DOCX / 409) ----------

async function dismissDialogAllWays(page, dialogLocator, openAgain, closeAriaLabel, evidence) {
  // the caller may arrive with the dialog already open; close it first so every
  // dismiss case starts from a deterministic closed state.
  if (await dialogLocator.count()) {
    await page.keyboard.press("Escape");
    await dialogLocator.waitFor({ state: "detached" });
    evidence.preclosed = "escape";
  }
  // cancel button
  await openAgain();
  await dialogLocator.waitFor();
  await dialogLocator.getByRole("button", { name: "取消", exact: true }).click();
  await dialogLocator.waitFor({ state: "detached" });
  evidence.cancel = "detached-after-取消";
  // X close button
  await openAgain();
  await dialogLocator.waitFor();
  await page.locator(`button[aria-label="${closeAriaLabel}"]`).click();
  await dialogLocator.waitFor({ state: "detached" });
  evidence.xClose = "detached-after-x";
  // Escape
  await openAgain();
  await dialogLocator.waitFor();
  await page.keyboard.press("Escape");
  await dialogLocator.waitFor({ state: "detached" });
  evidence.escape = "detached-after-escape";
  // overlay backdrop
  await openAgain();
  await dialogLocator.waitFor();
  await page.mouse.click(4, 4);
  await dialogLocator.waitFor({ state: "detached" });
  evidence.overlay = "detached-after-overlay";
}

async function runSyntheticSoaFlow(page, apiBase, appUrl, seeded, report, failures) {
  const key = seeded.key;
  const entry = { branch_source: "synthetic", projectId: seeded.projectId, sectionId: seeded.section.section_id, screenshots: {}, skipped: [] };
  report.synthetic = entry;
  const sectionId = seeded.section.section_id;
  const sectionHeading = seeded.section.heading;
  entry.interactionTypes = seeded.section.interaction_types || [];
  if (!entry.interactionTypes.includes("schedule_of_activities_editor")) {
    failures.push(`${key}:greenfield 1.3 missing schedule_of_activities_editor binding: ${JSON.stringify(entry.interactionTypes)}`);
    entry.skipped.push("synthetic SoA binding absent; Z/B1/B2 cannot run");
    return;
  }
  const QC_NOTE = "QC-SOA-NOTE-20260717-Z 基线访视允许±3天窗口。";

  await openWriting(page, appUrl, seeded.projectId);
  await page.setViewportSize(VIEWPORTS[0]);
  await openSectionViaMap(page, sectionHeading);

  // working copy -> save -> 版本 1
  await page.getByRole("button", { name: "创建工作副本" }).click();
  const saveCopy = page.getByRole("button", { name: "保存工作副本" });
  await saveCopy.waitFor(); await saveCopy.click();
  await page.getByText("版本 1", { exact: true }).waitFor();

  // ---- Z branch: create-confirm dialog ----
  const instantiateBefore = report.instantiateRequests.length;
  const openCreateDialog = async () => { await clickEntryButton(page); };
  await openCreateDialog();
  await createDialog(page).waitFor();
  const createButton = createDialog(page).getByRole("button", { name: "创建并打开" });
  const gateReason = await createButton.getAttribute("data-gate-reason");
  entry.zGateReason = gateReason;
  if (gateReason) failures.push(`${key}:Z create gate unexpectedly blocked: ${gateReason}`);
  if (await createButton.isDisabled()) failures.push(`${key}:Z 创建并打开 disabled despite clean gates`);
  entry.screenshots.create_confirm = await assertVisualState(page, evidenceDir, `${key}_z_create_confirm`, failures);
  const dismissEvidence = {};
  await dismissDialogAllWays(page, createDialog(page), openCreateDialog, "关闭创建研究流程表", dismissEvidence);
  entry.zDismiss = dismissEvidence;
  let state = await soaStructuredBlocks(apiBase, seeded.projectId, sectionId);
  entry.zBlockCountAfterDismiss = state.soaBlocks.length;
  if (state.soaBlocks.length !== 0 || state.revision !== 1) {
    failures.push(`${key}:Z dismiss mutated working copy (soa=${state.soaBlocks.length}, rev=${state.revision})`);
  }

  // confirm -> instantiate -> designer focused on new block
  await openCreateDialog();
  await createDialog(page).waitFor();
  await createDialog(page).getByRole("button", { name: "创建并打开" }).click();
  await designer(page).waitFor();
  await waitEditorIdle(page);
  state = await soaStructuredBlocks(apiBase, seeded.projectId, sectionId);
  entry.zCreatedCount = state.soaBlocks.length;
  if (state.soaBlocks.length !== 1) failures.push(`${key}:Z confirm created ${state.soaBlocks.length} SoA blocks, expected 1`);
  const createdBlockId = state.soaBlocks[0]?.block_id || "";
  const pickerAfterCreate = await tablePicker(page).inputValue();
  entry.zFocusedBlockId = pickerAfterCreate;
  if (pickerAfterCreate !== createdBlockId) failures.push(`${key}:Z designer focus ${pickerAfterCreate} != new block ${createdBlockId}`);
  if (report.instantiateRequests.length !== instantiateBefore + 1) failures.push(`${key}:Z instantiate request count ${report.instantiateRequests.length - instantiateBefore} != 1`);
  const instantiateUrl = report.instantiateRequests[report.instantiateRequests.length - 1]?.url || "";
  entry.zInstantiateUrl = instantiateUrl;
  if (!instantiateUrl.includes("idempotency_key=")) failures.push(`${key}:Z instantiate missing idempotency_key`);
  entry.zRevision = await workingCopyRevisionText(page);
  const designerText = await designer(page).innerText();
  entry.zTemplateLabelsPresent = ["研究活动", "筛选期", "基线/随机", "治疗期访视", "随访", "知情同意", "入排标准", "疗效评估", "安全性评估", "试验用药"]
    .every((label) => designerText.includes(label));
  if (!entry.zTemplateLabelsPresent) failures.push(`${key}:Z template starter labels incomplete in designer`);
  entry.screenshots.designer_created = await assertVisualState(page, evidenceDir, `${key}_z_designer_created`, failures);

  // idempotent replay of the exact instantiate request
  if (instantiateUrl) {
    const replay = await request(apiBase, new URL(instantiateUrl).pathname + new URL(instantiateUrl).search, { method: "POST" });
    const after = await soaStructuredBlocks(apiBase, seeded.projectId, sectionId);
    entry.zIdempotentReplay = { status: replay.status, soaCountAfter: after.soaBlocks.length };
    if (replay.status !== 200 || after.soaBlocks.length !== 1) {
      failures.push(`${key}:idempotent replay status=${replay.status} soaCount=${after.soaBlocks.length}`);
    }
  }

  // ---- B1 branch: unique candidate direct open ----
  await closeDesigner(page);
  const b1InstantiateBefore = report.instantiateRequests.length;
  await clickEntryButton(page);
  await designer(page).waitFor();
  if (await chooserDialog(page).count()) failures.push(`${key}:B1 unexpected chooser`);
  if (await createDialog(page).count()) failures.push(`${key}:B1 unexpected create dialog`);
  const b1Picker = await tablePicker(page).inputValue();
  entry.b1 = { focusedBlockId: b1Picker, instantiateDelta: report.instantiateRequests.length - b1InstantiateBefore };
  if (b1Picker !== createdBlockId) failures.push(`${key}:B1 focus ${b1Picker} != ${createdBlockId}`);
  if (entry.b1.instantiateDelta !== 0) failures.push(`${key}:B1 fired instantiate ${entry.b1.instantiateDelta}x`);

  // ---- duplicate flow via toolbar insert menu (existing duplicate dialog) ----
  await closeDesigner(page);
  const openTemplateMenu = async () => {
    await page.locator('button[aria-label="插入结构化表格"]').click();
    const menu = page.locator('[role="menu"][aria-label="结构化表格模板"]');
    await menu.waitFor();
    await menu.locator('button[role="menuitem"]', { hasText: "研究流程表" }).first().click();
  };
  await openTemplateMenu();
  await duplicateDialog(page).waitFor();
  entry.screenshots.duplicate = await assertVisualState(page, evidenceDir, `${key}_duplicate_dialog`, failures);
  await duplicateDialog(page).getByRole("button", { name: /打开现有表格/ }).first().click();
  await designer(page).waitFor();
  const dupOpenPicker = await tablePicker(page).inputValue();
  state = await soaStructuredBlocks(apiBase, seeded.projectId, sectionId);
  entry.duplicateOpenExisting = { focusedBlockId: dupOpenPicker, soaCount: state.soaBlocks.length };
  if (dupOpenPicker !== createdBlockId) failures.push(`${key}:duplicate 打开现有表格 focus ${dupOpenPicker} != ${createdBlockId}`);
  if (state.soaBlocks.length !== 1) failures.push(`${key}:duplicate 打开现有表格 changed block count to ${state.soaBlocks.length}`);
  await closeDesigner(page);
  await openTemplateMenu();
  await duplicateDialog(page).waitFor();
  await duplicateDialog(page).getByRole("button", { name: "仍插入一张" }).click();
  await designer(page).waitFor();
  await waitEditorIdle(page);
  state = await soaStructuredBlocks(apiBase, seeded.projectId, sectionId);
  entry.duplicateInsert = { soaCount: state.soaBlocks.length, instantiateTotal: report.instantiateRequests.length };
  if (state.soaBlocks.length !== 2) failures.push(`${key}:duplicate 仍插入一张 produced ${state.soaBlocks.length} blocks, expected 2`);
  const lastInstantiate = report.instantiateRequests[report.instantiateRequests.length - 1]?.url || "";
  if (!lastInstantiate.includes("allow_duplicate=true")) failures.push(`${key}:duplicate insert missing allow_duplicate=true (${lastInstantiate})`);
  const secondBlockId = state.soaBlocks.map((block) => block.block_id).find((id) => id !== createdBlockId) || "";
  const dupNewPicker = await tablePicker(page).inputValue();
  if (dupNewPicker !== secondBlockId) failures.push(`${key}:duplicate new block focus ${dupNewPicker} != ${secondBlockId}`);

  // ---- B2 branch: chooser with two candidates ----
  await closeDesigner(page);
  await clickEntryButton(page);
  await chooserDialog(page).waitFor();
  const candidateButtons = chooserDialog(page).locator("button[data-soa-candidate-block-id]");
  const chooserIds = [];
  for (let i = 0; i < await candidateButtons.count(); i += 1) chooserIds.push(await candidateButtons.nth(i).getAttribute("data-soa-candidate-block-id"));
  entry.b2 = { candidateIds: chooserIds };
  if (chooserIds.length !== 2) failures.push(`${key}:B2 chooser shows ${chooserIds.length} candidates, expected 2`);
  const preselected = await page.evaluate(() => document.activeElement?.getAttribute?.("data-soa-candidate-block-id"));
  if (preselected) failures.push(`${key}:B2 preselected ${preselected}`);
  await page.keyboard.press("Tab"); await page.keyboard.press("Tab");
  const focusInside = await page.evaluate(() => Boolean(document.activeElement?.closest?.('section[aria-label="选择要打开的研究流程表"]')));
  if (!focusInside) failures.push(`${key}:B2 focus escaped dialog after Tab`);
  const b2Dismiss = {};
  await dismissDialogAllWays(page, chooserDialog(page), async () => { await clickEntryButton(page); }, "关闭研究流程表选择", b2Dismiss);
  entry.b2.dismiss = b2Dismiss;
  if (await designer(page).count()) failures.push(`${key}:B2 dismiss left designer open`);
  await clickEntryButton(page);
  await chooserDialog(page).waitFor();
  const targetId = chooserIds[1];
  entry.screenshots.chooser = await assertVisualState(page, evidenceDir, `${key}_b2_chooser`, failures);
  await chooserDialog(page).locator(`button[data-soa-candidate-block-id="${targetId}"]`).click();
  await designer(page).waitFor();
  const chosenPicker = await tablePicker(page).inputValue();
  entry.b2.chosenBlockId = chosenPicker;
  if (chosenPicker !== targetId) failures.push(`${key}:B2 chosen ${chosenPicker} != ${targetId}`);
  entry.screenshots.chosenDesigner = await assertVisualState(page, evidenceDir, `${key}_b2_chosen_designer`, failures);

  // ---- edit SoA structure + note, save, reload ----
  const cellSelector = (row, col) => `button.std-cell-select-button[aria-label*="编辑第 ${row} 行第 ${col} 列"]`;
  await designer(page).locator(cellSelector(2, 2)).click();
  await designer(page).locator('button[aria-label="设为条件"]').click();
  await designer(page).locator(cellSelector(3, 3)).click();
  await designer(page).locator('button[aria-label="设为持续"]').click();
  await designer(page).locator('button[role="tab"]', { hasText: "附注" }).click();
  await designer(page).locator("button.std-add-note").click();
  const noteArea = designer(page).locator('textarea[aria-label$="内容"]').last();
  await noteArea.fill(QC_NOTE);
  await closeDesigner(page);
  const revisionBeforeSave = await workingCopyRevisionText(page);
  await page.getByRole("button", { name: "保存工作副本" }).click();
  await page.waitForFunction((previous) => {
    const node = document.querySelector(".working-copy-revision");
    return Boolean(node && !node.textContent.includes("读取中") && node.textContent.trim() !== previous);
  }, revisionBeforeSave);
  await waitEditorIdle(page);
  state = await soaStructuredBlocks(apiBase, seeded.projectId, sectionId);
  entry.editSaveRevision = state.revision;
  const editedBlock = state.soaBlocks.find((block) => block.block_id === targetId) || state.soaBlocks[1] || state.soaBlocks[0];
  const editedCellTexts = (editedBlock?.rows || []).flatMap((row) => row || [])
    .filter((cell) => cell && !cell.hidden && String(cell.text || "").trim())
    .map((cell) => String(cell.text).trim())
    .filter((text) => ["条件", "持续"].includes(text));
  const noteTexts = (editedBlock?.structured_table?.notes || []).map((note) => String(note.text || ""));
  entry.editedCellValues = editedCellTexts;
  entry.notePersisted = noteTexts.some((text) => text.includes("QC-SOA-NOTE-20260717-Z"));
  entry.editedBlockCellEvidence = {
    blockId: editedBlock?.block_id || "",
    topLevelRows: (editedBlock?.rows || []).map((row) => (row || []).map((cell) => ({
      cell_id: cell?.cell_id || "", text: String(cell?.text || ""), hidden: Boolean(cell?.hidden), plan_state: cell?.soa?.plan_state || "",
    }))),
    structuredRows: (editedBlock?.structured_table?.rows || []).map((row) => (row?.cells || []).map((cell) => ({
      cell_id: cell?.cell_id || "", text: String(cell?.text || ""),
    }))),
  };
  if (!editedCellTexts.length) failures.push(`${key}:plan-state cell edits not persisted via API`);
  if (!entry.notePersisted) failures.push(`${key}:QC note not persisted via API`);
  entry.screenshots.saved = await assertVisualState(page, evidenceDir, `${key}_saved_after_edit`, failures);

  // full reload
  await page.goto("about:blank", { waitUntil: "domcontentloaded" });
  await openWriting(page, appUrl, seeded.projectId);
  await openSectionViaMap(page, sectionHeading);
  const restoredRevision = await workingCopyRevisionText(page);
  entry.reloadedRevision = restoredRevision;
  if (restoredRevision !== `版本 ${state.revision}`) failures.push(`${key}:reload shows ${restoredRevision}, expected 版本 ${state.revision}`);
  await tablePicker(page).selectOption(targetId);
  await page.locator('button[aria-label="全屏编辑当前表格结构与附注"]').click();
  await designer(page).waitFor();
  const reloadedDesignerText = await designer(page).innerText();
  entry.reloadDomCellHit = editedCellTexts.some((text) => reloadedDesignerText.includes(text));
  await designer(page).locator('button[role="tab"]', { hasText: "附注" }).click();
  const noteTextareas = designer(page).locator('textarea[aria-label$="内容"]');
  const noteValues = [];
  for (let i = 0; i < await noteTextareas.count(); i += 1) noteValues.push(await noteTextareas.nth(i).inputValue());
  entry.reloadDomNoteHit = noteValues.some((value) => value.includes("QC-SOA-NOTE-20260717-Z"));
  if (!entry.reloadDomCellHit) failures.push(`${key}:edited cell value not visible after reload`);
  if (!entry.reloadDomNoteHit) failures.push(`${key}:QC note not visible after reload`);
  entry.screenshots.reloaded = await assertVisualState(page, evidenceDir, `${key}_reloaded`, failures);
  await closeDesigner(page);

  // ---- draft DOCX ----
  const docxPath = path.join(evidenceDir, `${key}_draft_preview.docx`);
  const exported = await exportDraftDocx(apiBase, seeded.projectId, docxPath);
  const needles = [...editedCellTexts.slice(0, 1), "QC-SOA-NOTE-20260717-Z"];
  const inspection = await docxInspect(docxPath, needles, FORBIDDEN_DOCX_TEXT);
  entry.docx = { file: path.basename(docxPath), tableCountHeader: exported.tableCountHeader, inspection };
  if (editedCellTexts.length && !inspection.cell_hits[editedCellTexts[0]]) failures.push(`${key}:DOCX missing edited cell value ${editedCellTexts[0]}`);
  if (!inspection.para_hits["QC-SOA-NOTE-20260717-Z"]) failures.push(`${key}:DOCX missing QC note paragraph`);
  if (inspection.forbidden_hits.length) failures.push(`${key}:DOCX forbidden text ${inspection.forbidden_hits.join(",")}`);

  // ---- 409 stale revision (API level; UI handler contract is covered by static tests) ----
  const stale = await request(apiBase, `/api/projects/${seeded.projectId}/medical-writing/working-copies/${sectionId}`, {
    method: "POST",
    allowStatus: 409,
    body: {
      document_id: (await request(apiBase, `/api/projects/${seeded.projectId}/medical-writing/document-session`)).payload.document_id,
      expected_revision: state.revision - 1,
      content_blocks: state.blocks,
      actor: "medical_manager_qc",
      idempotency_key: `${key}-stale-409`,
    },
  });
  entry.stale409 = { status: stale.status, detail: typeof stale.payload?.detail === "string" ? stale.payload.detail : JSON.stringify(stale.payload?.detail || "") };
  if (stale.status !== 409) failures.push(`${key}:stale save returned ${stale.status}, expected 409`);
}

async function runSyntheticFreezeFlow(page, apiBase, appUrl, seeded, report, failures) {
  const key = seeded.key;
  const entry = { branch_source: "synthetic", projectId: seeded.projectId, sectionId: seeded.section.section_id, screenshots: {}, skipped: [] };
  report.freeze = entry;
  const sectionId = seeded.section.section_id;
  await openWriting(page, appUrl, seeded.projectId);
  await page.setViewportSize(VIEWPORTS[0]);
  await openSectionViaMap(page, seeded.section.heading);
  await page.getByRole("button", { name: "创建工作副本" }).click();
  const saveCopy = page.getByRole("button", { name: "保存工作副本" });
  await saveCopy.waitFor(); await saveCopy.click();
  await page.getByText("版本 1", { exact: true }).waitFor();
  const session = await request(apiBase, `/api/projects/${seeded.projectId}/medical-writing/document-session`);
  const copy = await request(apiBase, `/api/projects/${seeded.projectId}/medical-writing/working-copies/${sectionId}`);
  const freeze = await request(apiBase, `/api/projects/${seeded.projectId}/medical-writing/working-copies/${sectionId}/freeze-current-version`, {
    method: "POST", allowStatus: 409,
    body: {
      document_id: session.payload.document_id,
      expected_working_copy_revision: copy.payload.revision,
      expected_study_definition_id: copy.payload.source_study_definition_id,
      expected_study_definition_revision: copy.payload.source_study_definition_revision,
      expected_study_definition_sha256: copy.payload.source_study_definition_sha256,
      reason: "隔离QC：医学作者确认1.3章节定稿，验证冻结后的创建门禁。",
      actor: "medical_manager_qc",
      idempotency_key: `soa-qc-freeze-${key}`,
    },
  });
  entry.freezeHttpStatus = freeze.status;
  entry.freezeStatus = freeze.payload?.working_copy?.freeze_status || "";
  if (freeze.status !== 200 || entry.freezeStatus !== "frozen") {
    entry.skipped.push(`freeze returned ${freeze.status} state=${entry.freezeStatus}; freeze-disabled UI check skipped with evidence`);
    return;
  }
  await page.goto("about:blank", { waitUntil: "domcontentloaded" });
  await openWriting(page, appUrl, seeded.projectId);
  await openSectionViaMap(page, seeded.section.heading);
  await page.getByText("当前作者确认版本 / 已冻结", { exact: true }).waitFor();
  await clickEntryButton(page);
  await createDialog(page).waitFor();
  const createButton = createDialog(page).getByRole("button", { name: "创建并打开" });
  const gateReason = await createButton.getAttribute("data-gate-reason");
  const disabled = await createButton.isDisabled();
  entry.lockedGate = { disabled, gateReason };
  if (!disabled) failures.push(`${key}:创建并打开 enabled while current author version is frozen`);
  if (!gateReason || !gateReason.includes("冻结")) failures.push(`${key}:gate reason missing freeze explanation: ${gateReason}`);
  entry.screenshots.locked = await assertVisualState(page, evidenceDir, `${key}_freeze_locked`, failures);
  await page.keyboard.press("Escape");
  await createDialog(page).waitFor({ state: "detached" });
}

// ---------- main ----------

async function main() {
  await rm(evidenceDir, { recursive: true, force: true });
  await mkdir(evidenceDir, { recursive: true });
  const report = {
    passed: false,
    startedAt: new Date().toISOString(),
    runtime: {},
    stable: {},
    sources: {},
    coldSessions: {},
    projects: {},
    instantiateRequests: [],
    requestLog: [],
    consoleErrors: [],
    pageErrors: [],
    httpFailures: [],
    failures: [],
  };

  // H-guards: stable DB discovery + source pins before anything mutates.
  const stableFiles = await discoverStableDbFiles();
  const stableBefore = await hashFiles(stableFiles);
  report.stable.files = stableFiles;
  report.stable.before = stableBefore;
  for (const source of Object.values(ORIGINAL_SOURCES)) {
    const actual = await sha256File(source.docxPath);
    report.sources[source.key] = { path: source.docxPath, pinned: source.sha256, before: actual };
    if (actual !== source.sha256) report.failures.push(`${source.key}:original DOCX hash mismatch before run`);
  }

  const runtimeDir = await mkdtemp(path.join(tmpdir(), "mw-soa-section-qc-"));
  const apiPort = await freePort(8972); const vitePort = await freePort(5214);
  const apiBase = `http://127.0.0.1:${apiPort}`; const appUrl = `http://127.0.0.1:${vitePort}/`;
  let api = startService(pythonBin, ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], { cwd: projectRoot, env: { ...process.env, WORKBENCH_RUNTIME_DIR: runtimeDir, PYTHONUNBUFFERED: "1" } });
  const vite = startService(process.env.NPM_BIN || "npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"], { cwd: frontendRoot, env: { ...process.env, VITE_API_PROXY_TARGET: apiBase } });
  let browser;
  try {
    await waitForHttp(`${apiBase}/api/health`); await waitForHttp(appUrl);
    report.runtime = { isolated: true, runtimeDir, apiBase, appUrl };
    // prove child environment isolation from the process itself
    try {
      const { stdout } = await execFile("sh", ["-c", `ps eww -p ${api.child.pid} | tr ' ' '\\n' | grep '^WORKBENCH_RUNTIME_DIR='`]);
      report.runtime.childEnv = stdout.trim();
      if (!stdout.includes(runtimeDir)) report.failures.push(`isolated API env mismatch: ${stdout.trim()}`);
    } catch (error) { report.failures.push(`isolated API env proof failed: ${error.message}`); }
    const health = await request(apiBase, "/api/health");
    report.runtime.health = health.payload;

    // project registration must be available in the empty isolated runtime
    const projectList = await request(apiBase, "/api/projects");
    const listed = JSON.stringify(projectList.payload);
    const missing = Object.values(ORIGINAL_SOURCES).filter((source) => !listed.includes(source.projectId));
    if (missing.length) {
      // registration-only fallback: copy the user project store (no sessions/working copies exist there)
      const registrationDb = stableFiles.find((file) => file.endsWith("user_projects.sqlite3"));
      report.runtime.registrationFallback = { missing: missing.map((source) => source.projectId), registrationDb };
      if (!registrationDb) throw new Error(`stable projects missing in isolated runtime and no registration DB discovered: ${missing.map((s) => s.projectId)}`);
      await stopService(api);
      await copyFile(registrationDb, path.join(runtimeDir, "user_projects.sqlite3"));
      api = startService(pythonBin, ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], { cwd: projectRoot, env: { ...process.env, WORKBENCH_RUNTIME_DIR: runtimeDir, PYTHONUNBUFFERED: "1" } });
      await waitForHttp(`${apiBase}/api/health`);
      const retry = await request(apiBase, "/api/projects");
      const retryListed = JSON.stringify(retry.payload);
      for (const source of missing) {
        if (!retryListed.includes(source.projectId)) throw new Error(`project still missing after registration fallback: ${source.projectId}`);
      }
    }

    const template = (await request(apiBase, "/api/medical-writing/protocol-templates/default")).payload;

    // Cold source-derived sessions: fresh process + empty runtime => GET document-session must
    // invoke MedicalWritingDocumentService._load() + parse_protocol_docx() on the original bytes.
    for (const source of Object.values(ORIGINAL_SOURCES)) {
      const session = await request(apiBase, `/api/projects/${source.projectId}/medical-writing/document-session`);
      const expectedSuffix = source.sha256.slice(0, 16);
      const documentId = session.payload.document_id || "";
      const info = {
        documentId,
        expectedShaSuffix: expectedSuffix,
        documentIdMatchesSourceHash: documentId.startsWith("mwdoc_") && documentId.endsWith(expectedSuffix),
        sectionCount: session.payload.sections?.length ?? 0,
      };
      if (!info.documentIdMatchesSourceHash) report.failures.push(`${source.key}:document_id ${documentId} not derived from pinned source hash ${expectedSuffix}`);
      const sections = session.payload.sections || [];
      const soaCandidates = sections.filter((item) => /流程表/.test(item.heading || "") || /^1\.3/.test(item.section_number || ""));
      let chosen = soaCandidates.find((item) => /研究流程表/.test(item.heading || "")) || soaCandidates[0] || null;
      if (chosen) {
        const detail = await request(apiBase, `/api/projects/${source.projectId}/medical-writing/document-session/sections/${chosen.section_id}`);
        const blocks = detail.payload.content_blocks || [];
        info.soaSection = {
          section_id: chosen.section_id,
          heading: chosen.heading,
          section_number: chosen.section_number,
          interactionTypes: chosen.interaction_types || [],
          summaryKeys: Object.keys(chosen).sort(),
          tableBlockCount: blocks.filter((block) => block.block_type === "table").length,
          blockCount: blocks.length,
        };
      } else {
        info.soaSection = null;
        info.sectionHeadings = sections.map((item) => item.heading).slice(0, 40);
      }
      report.coldSessions[source.key] = info;
    }

    const { chromium } = await import(playwrightPath);
    browser = await chromium.launch({ executablePath: chromePath, headless: true });
    const page = await browser.newPage({ viewport: VIEWPORTS[0] });
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const text = message.text();
      // network 404 resource noise is asserted separately through the httpFailures whitelist
      if (text.startsWith("Failed to load resource:")) return;
      report.consoleErrors.push(text);
    });
    page.on("pageerror", (error) => report.pageErrors.push(error.message));
    page.on("response", (response) => {
      let parsed;
      try { parsed = new URL(response.url()); } catch { return; }
      const pathName = parsed.pathname;
      if (pathName.includes("/table-templates/") && pathName.endsWith("/instantiate")) {
        report.instantiateRequests.push({ method: response.request().method(), url: response.url(), status: response.status() });
      }
      if (pathName.includes("/medical-writing/")) {
        report.requestLog.push({ method: response.request().method(), path: `${pathName}${parsed.search}`, status: response.status() });
        if (report.requestLog.length > 400) report.requestLog.shift();
      }
      if (response.status() >= 400) {
        const whitelisted = response.status() === 404
          && (pathName.endsWith("/medical-writing/manifest")
            || pathName.endsWith("/medical-writing/document-session")
            || pathName.endsWith("/medical-writing/authoring-journey"));
        if (!whitelisted) report.httpFailures.push({ method: response.request().method(), status: response.status(), path: pathName });
      }
    });

    const runFlow = async (label, fn) => {
      try {
        await fn();
      } catch (error) {
        report.failures.push(`${label}:unhandled:${String(error.message || error).slice(0, 400)}`);
        report[`${label}Crash`] = String(error.stack || error.message || error).slice(0, 1500);
        try { await page.screenshot({ path: path.join(evidenceDir, `${label}_crash.png`), fullPage: false }); } catch { /* browser may be gone */ }
      }
    };
    for (const source of Object.values(ORIGINAL_SOURCES)) {
      await runFlow(source.key, () => runRealProjectFlow(page, apiBase, appUrl, source, report.coldSessions[source.key], report, report.failures));
    }
    await runFlow("z", async () => {
      const seededZ = await seedSyntheticSoaProject(apiBase, template, "z");
      await runSyntheticSoaFlow(page, apiBase, appUrl, seededZ, report, report.failures);
    });
    await runFlow("gate", async () => {
      const seededGate = await seedSyntheticSoaProject(apiBase, template, "gate");
      await runSyntheticFreezeFlow(page, apiBase, appUrl, seededGate, report, report.failures);
    });

    // global guards
    if (report.consoleErrors.length) report.failures.push(`console-errors:${report.consoleErrors.length}`);
    if (report.pageErrors.length) report.failures.push(`page-errors:${report.pageErrors.length}`);
    if (report.httpFailures.length) report.failures.push(`http-failures:${JSON.stringify(report.httpFailures)}`);
  } finally {
    await browser?.close();
    await stopService(vite);
    await stopService(api);
    report.runtime.apiLogTail = api.output.slice(-60);
    report.runtime.viteLogTail = vite.output.slice(-30);
    if (process.env.PRESERVE_QC_RUNTIME !== "1") { await rm(runtimeDir, { recursive: true, force: true }); report.runtime.runtimeRemoved = true; }
  }

  // H-guards after teardown: stable DBs, source pins, stable service health.
  const stableAfter = await hashFiles(stableFiles);
  report.stable.after = stableAfter;
  report.stable.unchanged = stableFiles.every((file) => stableBefore[file] === stableAfter[file]);
  if (!report.stable.unchanged) {
    const changed = stableFiles.filter((file) => stableBefore[file] !== stableAfter[file]);
    report.failures.push(`stable-runtime-changed:${changed.join(",")}`);
  }
  for (const source of Object.values(ORIGINAL_SOURCES)) {
    const after = await sha256File(source.docxPath);
    report.sources[source.key].after = after;
    if (after !== source.sha256) report.failures.push(`${source.key}:original DOCX hash changed during run`);
  }
  try {
    const stableHealth = await fetch("http://127.0.0.1:8911/api/health");
    const viteHealth = await fetch("http://127.0.0.1:5174/", { method: "GET" });
    report.stable.servicesHealthy = stableHealth.ok && viteHealth.ok;
    if (!report.stable.servicesHealthy) report.failures.push(`stable services degraded: api=${stableHealth.status} vite=${viteHealth.status}`);
  } catch (error) { report.failures.push(`stable service health check failed: ${error.message}`); }

  report.passed = report.failures.length === 0;
  report.completedAt = new Date().toISOString();
  await writeFile(path.join(evidenceDir, "medical_writing_soa_section_isolated_qc.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: report.passed, failures: report.failures, evidenceDir }, null, 2));
  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
