import { spawn, execFile as execFileCallback } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
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
const outputDir = path.join(projectRoot, "records/active_slices/medical_writing_section_interaction_routing_20260717/browser_qc");
const playwrightPath = process.env.PLAYWRIGHT_PATH || "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const studies = [
  {
    key: "ra",
    project: { project_code: "QC-RA-STRUCTURED", project_name: "类风湿关节炎II期结构化方案写作QC", indication: "类风湿关节炎", product_name: "CMS-RA-201注射液", study_phase: "II期", protocol_id: "QC-RA-STRUCTURED", protocol_version: "V0.1" },
    framing: { protocol_id: "QC-RA-STRUCTURED", version: "V0.1", document_title: "CMS-RA-201注射液治疗类风湿关节炎的II期临床研究方案", indication: "类风湿关节炎", clinicaltrials_condition_term: "Rheumatoid Arthritis", study_phase: "II期", intrinsic_objectives: ["概念验证（PoC）", "剂量探索"], investigational_product: "CMS-RA-201注射液", target_mechanism: "靶向炎症通路的全人源单克隆抗体", competitor_target_scope: "同靶点、同机制及同治疗线生物制剂", development_regions: ["中国"], design_pattern: "随机、双盲、安慰剂对照、平行组、多中心II期剂量探索研究", population_intent: "既往甲氨蝶呤治疗反应不充分的中重度活动性类风湿关节炎成人试验参与者", key_uncertainties: ["剂量-效应关系", "第12周主要终点评价时点"], manual_source_ids: [], terminology_policy: "cde_participant" },
    picos: { design_archetype: "randomized_confirmatory", field_applicability: {}, population_summary: "18至75岁、既往甲氨蝶呤治疗反应不充分的中重度活动性类风湿关节炎成人试验参与者。", inclusion_modules: ["筛选期与基线期满足疾病活动度阈值", "稳定使用背景甲氨蝶呤", "符合妊娠预防与避孕要求"], exclusion_modules: ["活动性感染", "近期使用其他生物制剂且未完成洗脱", "存在方案规定的严重心血管、肝脏或肾脏疾病"], washout_rules: ["既往生物制剂按药代特征和方案规定完成洗脱"], intervention_summary: "CMS-RA-201低剂量组和高剂量组，皮下注射。", intervention_dose_regimen: "每4周给药一次，持续24周；剂量调整、中断和恢复规则在干预章节单列。", allowed_concomitant_rules: ["稳定剂量非甾体抗炎药"], required_background_rules: ["稳定剂量甲氨蝶呤", "按方案补充叶酸"], prohibited_concomitant_rules: ["其他生物制剂", "JAK抑制剂"], assessment_timing_restrictions: ["疗效评价前24小时限制救援性镇痛药；急救情况除外并完整记录。"], comparator_summary: "匹配安慰剂，每4周皮下注射一次，并维持与试验组一致的背景甲氨蝶呤治疗。", primary_endpoint: "第12周ACR20应答率。", key_secondary_endpoints: ["第12周DAS28-CRP较基线变化", "第12周HAQ-DI较基线变化"], other_secondary_endpoints: ["第24周ACR50和ACR70应答率"], exploratory_endpoints: ["炎症生物标志物较基线变化"], safety_endpoints: ["TEAE、SAE及导致停药的AE发生率", "实验室检查、生命体征和心电图变化"], aesi_definitions: ["严重感染", "超敏反应"], assessment_instruments: [], study_epochs: ["筛选期", "双盲治疗期", "安全性随访期"], visit_strategy: "筛选、基线，治疗期每4周访视，末次给药后完成安全性随访。", estimand_strategy: "主要估计目标评价治疗策略下第12周ACR20应答差异，并预先规定救援治疗和停药等伴发事件策略。", sample_size_strategy: "基于预期应答率差异、双侧显著性水平、检验效能和脱落率估算。", statistical_strategy: "主要终点采用分层分析；关键次要终点按预设层级进行多重性控制，并设置敏感性分析。" },
    addedRule: "血清CRP高于中心实验室正常值上限，且筛选期与基线期疾病活动度均符合方案阈值。",
  },
  {
    key: "d001",
    project: { project_code: "QC-D001-STRUCTURED", project_name: "CMS-D001银屑病II/III期结构化方案写作QC", indication: "斑块状银屑病", product_name: "CMS-D001片", study_phase: "II/III期", protocol_id: "QC-D001-STRUCTURED", protocol_version: "V0.1" },
    framing: { protocol_id: "QC-D001-STRUCTURED", version: "V0.1", document_title: "CMS-D001片治疗斑块状银屑病的II/III期临床研究方案", indication: "斑块状银屑病", clinicaltrials_condition_term: "Plaque Psoriasis", study_phase: "II/III期", intrinsic_objectives: ["剂量探索", "确证性研究"], investigational_product: "CMS-D001片", target_mechanism: "创新小分子免疫调节剂", competitor_target_scope: "同适应症口服创新疗法", development_regions: ["中国"], design_pattern: "随机、双盲、安慰剂对照的II/III期研究", population_intent: "中重度斑块状银屑病成人试验参与者", key_uncertainties: ["II期剂量选择", "III期确证性终点"], manual_source_ids: ["CMS-D001 V1.0"], terminology_policy: "cde_participant" },
    picos: { design_archetype: "randomized_confirmatory", field_applicability: {}, population_summary: "中重度斑块状银屑病成人试验参与者。", inclusion_modules: ["PASI和PGA达到方案规定严重程度", "适合接受系统治疗或光疗"], exclusion_modules: ["活动性感染", "近期使用禁用生物制剂且未完成洗脱"], washout_rules: ["既往生物制剂和系统治疗按方案规定完成洗脱"], intervention_summary: "CMS-D001片按随机分组口服给药。", intervention_dose_regimen: "按II期剂量探索和III期确证方案给药；剂量调整、中断及恢复规则单列。", allowed_concomitant_rules: ["方案允许的稳定外用保湿剂"], required_background_rules: [], prohibited_concomitant_rules: ["其他系统性银屑病治疗", "方案禁用的光疗"], assessment_timing_restrictions: ["PASI和PGA评价前按方案限制外用治疗。"], comparator_summary: "匹配安慰剂对照。", primary_endpoint: "方案规定时间点达到PASI 75的试验参与者比例。", key_secondary_endpoints: ["方案规定时间点达到PGA 0/1的试验参与者比例。"], other_secondary_endpoints: ["PASI、PGA、BSA和DLQI较基线变化。"], exploratory_endpoints: [], safety_endpoints: ["TEAE和SAE发生率。"], aesi_definitions: ["严重感染"], assessment_instruments: [], study_epochs: ["筛选期", "治疗期", "扩展期"], visit_strategy: "按II期与III期研究流程表执行筛选、基线和治疗期访视。", estimand_strategy: "主要估计目标评价随机治疗策略下PASI应答差异。", sample_size_strategy: "依据PASI 75应答率差异估算。", statistical_strategy: "分类终点采用分层方法比较，并预设多重性控制。" },
    addedRule: "筛选期PASI≥12、受累体表面积≥10%，且研究者总体评估达到方案规定等级。",
  },
];

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

async function request(apiBase, pathname, { method = "GET", body } = {}) {
  const response = await fetch(`${apiBase}${pathname}`, { method, headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${method} ${pathname} -> ${response.status}: ${JSON.stringify(payload)}`);
  return payload;
}

async function stableSnapshot() {
  const names = (await readdir(stableRuntimeDir)).filter((name) => name.endsWith(".sqlite3")).sort();
  return Object.fromEntries(await Promise.all(names.map(async (name) => [name, createHash("sha256").update(await readFile(path.join(stableRuntimeDir, name))).digest("hex")])));
}

async function seedStudy(apiBase, template, study) {
  const created = await request(apiBase, "/api/projects", { method: "POST", body: { ...study.project, protocol_date: "2026-07-17", entry_mode: "from_zero", actor: "medical_manager_qc", idempotency_key: `section-routing-project-${study.key}` } });
  const projectId = created.project.project_id;
  const initial = created.authoring_journey;
  const framingPreview = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`, { method: "POST", body: { expected_revision: initial.revision, stage: "framing", framing: study.framing } });
  const framed = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/stages/framing/commit`, { method: "POST", body: { expected_revision: initial.revision, stage: "framing", framing: study.framing, impact_preview_id: framingPreview.preview_id, actor: "medical_manager_qc", idempotency_key: `section-routing-framing-${study.key}` } });
  const picosPreview = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`, { method: "POST", body: { expected_revision: framed.revision, stage: "picos", picos: study.picos } });
  const designed = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/stages/picos/commit`, { method: "POST", body: { expected_revision: framed.revision, stage: "picos", picos: study.picos, impact_preview_id: picosPreview.preview_id, actor: "medical_manager_qc", idempotency_key: `section-routing-picos-${study.key}` } });
  const missing = designed.corpus_gate?.missing_requirements || [];
  const allowed = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/corpus-gate/override`, { method: "POST", body: { expected_revision: designed.revision, reason: "隔离环境验证真实研究的结构化章节交互、版本一致性和医学批准链路。", acknowledged_missing_requirements: missing, actor: "medical_manager_qc", idempotency_key: `section-routing-corpus-${study.key}` } });
  const definition = allowed.study_definition;
  if (!definition) throw new Error(`${study.key}: StudyDefinition was not produced`);
  await request(apiBase, `/api/projects/${projectId}/medical-writing/greenfield-document`, { method: "POST", body: { protocol_id: allowed.framing.protocol_id, version: allowed.framing.version, document_title: allowed.framing.document_title, indication: allowed.framing.indication, study_phase: allowed.framing.study_phase, source_study_definition_id: definition.definition_id, source_study_definition_revision: definition.revision, source_study_definition_sha256: definition.state_sha256, template_id: template.template_id, template_version: template.template_version, actor: "medical_manager_qc", idempotency_key: `section-routing-document-${study.key}` } });
  let greenfieldState = await request(apiBase, `/api/projects/${projectId}/medical-writing/greenfield-document`);
  for (const decision of greenfieldState.decisions.filter((item) => item.approval_blocking && item.status !== "resolved")) {
    await request(apiBase, `/api/projects/${projectId}/medical-writing/greenfield-document/decisions/${decision.decision_id}/resolve`, { method: "POST", body: {
      expected_baseline_revision: greenfieldState.baseline_revision,
      value: `项目团队已确认：${decision.label}按当前方案框架执行。`,
      rationale: `基于${study.project.indication}项目设计讨论、医学与统计联合评估形成当前决策。`,
      source_refs: [`project_decision:${study.key}:${decision.decision_id}:20260717`],
      actor: "medical_director_qc",
      idempotency_key: `section-routing-decision-${study.key}-${decision.decision_id}`,
    } });
    greenfieldState = await request(apiBase, `/api/projects/${projectId}/medical-writing/greenfield-document`);
  }
  const session = await request(apiBase, `/api/projects/${projectId}/medical-writing/document-session`);
  const section = session.sections.find((item) => item.section_number === "5.2");
  if (!section) throw new Error(`${study.key}: M11 section 5.2 not found`);
  return { ...study, projectId, section, definition };
}

async function poll(fn, predicate, timeoutMs = 30000) {
  const started = Date.now(); let latest;
  while (Date.now() - started < timeoutMs) {
    latest = await fn(); if (predicate(latest)) return latest; await wait(250);
  }
  throw new Error(`Timed out; latest=${JSON.stringify(latest)}`);
}

async function openWriting(page, appUrl, projectId) {
  await page.goto(appUrl, { waitUntil: "domcontentloaded" });
  const select = page.locator('select[aria-label="选择临床研究项目"]');
  await select.waitFor(); await select.selectOption(projectId);
  await page.getByRole("button", { name: "医学写作" }).click();
  await page.getByText("研究方案文档编辑与AI修订", { exact: true }).waitFor();
}

async function selectEligibilitySection(page) {
  await page.getByRole("button", { name: "目录" }).click();
  const drawer = page.locator(".writing-document-map-drawer");
  await drawer.waitFor();
  await drawer.locator('input[placeholder="搜索章节标题"]').fill("入选标准");
  const button = drawer.locator(".writing-section-buttons > button").filter({ hasText: "入选标准" }).first();
  await button.waitFor(); await button.click();
  await page.getByRole("button", { name: "结构化入排" }).waitFor();
}

async function runProjectLoop(page, apiBase, appUrl, outputDirPath, study) {
  await openWriting(page, appUrl, study.projectId);
  await selectEligibilitySection(page);
  const createCopy = page.getByRole("button", { name: "创建工作副本" });
  await createCopy.waitFor(); await createCopy.click();
  const saveCopy = page.getByRole("button", { name: "保存工作副本" });
  await saveCopy.waitFor(); await saveCopy.click();
  await page.getByText("版本 1", { exact: true }).waitFor();
  await page.getByRole("button", { name: "结构化入排" }).click();
  const design = page.locator(".writing-study-design-drawer");
  await design.waitFor();
  await design.getByRole("tab", { name: "研究人群", exact: true }).waitFor();
  const focus = await design.locator(".authoring-focus-context").innerText();
  if (!focus.includes("5.2") || !focus.includes("入排与洗脱规则")) throw new Error(`${study.key}: wrong focused editor ${focus}`);
  const beforeCount = await design.locator('textarea[aria-label^="入选标准 "]').count();
  await design.getByRole("button", { name: "新增入选标准" }).click();
  const inclusionRows = design.locator('textarea[aria-label^="入选标准 "]');
  if (await inclusionRows.count() !== beforeCount + 1) throw new Error(`${study.key}: structured row was not added`);
  await inclusionRows.last().fill(study.addedRule);
  const metrics = await design.evaluate((node) => ({
    pageOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    drawerOverflowX: node.scrollWidth - node.clientWidth,
    activeStage: node.querySelector(".authoring-stage-strip button.active")?.textContent?.trim(),
    activeGroup: node.querySelector(".authoring-group-tabs button.active")?.textContent?.trim(),
    structuredRows: node.querySelectorAll(".authoring-structured-list-row").length,
  }));
  await page.screenshot({ path: path.join(outputDirPath, `${study.key}_01_focused_eligibility_1920x1080.png`), fullPage: false });
  await design.getByRole("button", { name: "完成第二步" }).click();
  const impact = design.locator(".authoring-impact-panel"); await impact.waitFor();
  await impact.getByRole("button", { name: "确认变更并重新核验" }).click();
  const journey = await poll(
    () => request(apiBase, `/api/projects/${study.projectId}/medical-writing/authoring-journey`),
    (value) => value.picos?.inclusion_modules?.includes(study.addedRule) && !value.picos_draft,
  );
  await design.getByTitle("关闭研究设计").click();
  const stale = await poll(
    () => request(apiBase, `/api/projects/${study.projectId}/medical-writing/study-consistency`),
    (value) => value.status === "stale",
  );
  const preview = await request(apiBase, `/api/projects/${study.projectId}/medical-writing/study-consistency/rebind-preview`);
  const rebound = await request(apiBase, `/api/projects/${study.projectId}/medical-writing/study-consistency/rebind`, { method: "POST", body: {
    preview_id: preview.preview_id,
    expected_document_id: preview.document_id,
    expected_baseline_revision: preview.baseline_revision,
    expected_baseline_sha256: preview.baseline_sha256,
    confirm_content_preserved: true,
    confirm_affected_approvals_reset: true,
    reason: `已更新${study.project.indication}入选标准，需保留正文并重新核对受影响章节。`,
    actor: "medical_manager_qc",
    idempotency_key: `section-routing-rebind-${study.key}`,
  } });
  if (rebound.consistency.status !== "reconciliation_required") throw new Error(`${study.key}: rebind did not require reconciliation`);
  const copy = await request(apiBase, `/api/projects/${study.projectId}/medical-writing/working-copies/${study.section.section_id}`);
  const blocks = copy.content_blocks.map((block) => ({ ...block }));
  const paragraph = blocks.find((block) => block.block_type === "paragraph" || block.block_type === "heading");
  if (!paragraph) throw new Error(`${study.key}: no editable paragraph in section 5.2`);
  paragraph.text = `${paragraph.text || "入选标准"}\n${study.addedRule}`;
  const edited = await request(apiBase, `/api/projects/${study.projectId}/medical-writing/working-copies/${study.section.section_id}`, { method: "POST", body: { document_id: rebound.document_id, expected_revision: copy.revision, content_blocks: blocks, actor: "medical_manager_qc", idempotency_key: `section-routing-edit-${study.key}` } });
  const reconciled = await request(apiBase, `/api/projects/${study.projectId}/medical-writing/study-consistency/sections/${study.section.section_id}/confirm`, { method: "POST", body: { document_id: rebound.document_id, expected_working_copy_revision: edited.revision, reason: `已将${study.addedRule}逐项核对并写入5.2入选标准正文。`, acknowledge_content_reconciled: true, actor: "medical_manager_qc", idempotency_key: `section-routing-reconcile-${study.key}` } });
  if (reconciled.consistency.status !== "current") throw new Error(`${study.key}: reconciliation did not restore current status`);
  const reconciledCopy = reconciled.working_copy;
  const frozen = await request(apiBase, `/api/projects/${study.projectId}/medical-writing/working-copies/${study.section.section_id}/freeze-current-version`, { method: "POST", body: {
    document_id: rebound.document_id,
    expected_working_copy_revision: reconciledCopy.revision,
    expected_study_definition_id: reconciledCopy.source_study_definition_id,
    expected_study_definition_revision: reconciledCopy.source_study_definition_revision,
    expected_study_definition_sha256: reconciledCopy.source_study_definition_sha256,
    reason: "医学作者已按当前StudyDefinition复核入选标准章节并确认定稿。",
    actor: "medical_manager_qc",
    idempotency_key: `section-routing-freeze-${study.key}`,
  } });
  if (frozen.working_copy.freeze_status !== "frozen") throw new Error(`${study.key}: chapter freeze failed`);
  const docxResponse = await fetch(`${apiBase}/api/projects/${study.projectId}/medical-writing/document.docx?mode=draft_preview`);
  if (!docxResponse.ok) throw new Error(`${study.key}: DOCX export ${docxResponse.status}`);
  const docxPath = path.join(outputDirPath, `${study.key}_draft_preview.docx`);
  await writeFile(docxPath, Buffer.from(await docxResponse.arrayBuffer()));
  const { stdout } = await execFile(process.env.PYTHON_BIN || "python3", ["-c", "from docx import Document; import sys; d=Document(sys.argv[1]); print('\\n'.join(p.text for p in d.paragraphs))", docxPath]);
  if (!stdout.includes(study.addedRule)) throw new Error(`${study.key}: exported DOCX omitted reconciled rule`);
  await openWriting(page, appUrl, study.projectId);
  await selectEligibilitySection(page);
  await page.locator(".working-copy-revision").filter({ hasText: `版本 ${reconciled.working_copy.revision}` }).waitFor();
  await page.getByText("当前作者确认版本 / 已冻结", { exact: true }).waitFor();
  await page.locator(".protocol-editor").getByText(study.addedRule, { exact: false }).waitFor();
  if (await page.getByText("正在加载研究方案文档会话。", { exact: true }).count()) {
    throw new Error(`${study.key}: final screenshot gate still showed the loading state`);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  const finalMetrics = await page.locator(".writing-editor-core").evaluate((node) => ({
    pageOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    editorOverflowX: node.scrollWidth - node.clientWidth,
    workingCopyRevision: node.querySelector(".working-copy-revision")?.textContent?.trim(),
    freezeLocked: Boolean(node.querySelector(".approval-lock")),
  }));
  await page.screenshot({ path: path.join(outputDirPath, `${study.key}_02_reconciled_frozen_1440x900.png`), fullPage: false });
  await page.setViewportSize({ width: 1920, height: 1080 });
  return { projectId: study.projectId, sectionId: study.section.section_id, focus, metrics, finalMetrics, journeyRevision: journey.revision, staleAffectedSections: stale.affected_sections.map((item) => item.section_number), rebindResetFreezeCount: rebound.reset_approval_count, reconciledRevision: reconciled.working_copy.revision, freezeStatus: frozen.working_copy.freeze_status, docxPath, docxContainsAddedRule: true };
}

async function main() {
  await rm(outputDir, { recursive: true, force: true }); await mkdir(outputDir, { recursive: true });
  const runtimeDir = await mkdtemp(path.join(tmpdir(), "mw-section-routing-qc-"));
  const apiPort = await freePort(8956); const vitePort = await freePort(5206);
  const apiBase = `http://127.0.0.1:${apiPort}`; const appUrl = `http://127.0.0.1:${vitePort}/`;
  const stableBefore = await stableSnapshot();
  const api = startService(process.env.PYTHON_BIN || "python3", ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], { cwd: projectRoot, env: { ...process.env, WORKBENCH_RUNTIME_DIR: runtimeDir, PYTHONUNBUFFERED: "1" } });
  const vite = startService(process.env.NPM_BIN || "npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"], { cwd: frontendRoot, env: { ...process.env, VITE_API_PROXY_TARGET: apiBase } });
  const report = { passed: false, runtime: { isolated: true, runtimeDir, stableRuntimeDir }, apiBase, appUrl, projects: {}, consoleErrors: [], pageErrors: [], httpFailures: [], failures: [] };
  let browser;
  try {
    await waitForHttp(`${apiBase}/api/health`); await waitForHttp(appUrl);
    const template = await request(apiBase, "/api/medical-writing/protocol-templates/default");
    const seeded = [];
    for (const study of studies) seeded.push(await seedStudy(apiBase, template, study));
    const { chromium } = await import(playwrightPath);
    browser = await chromium.launch({ executablePath: chromePath, headless: true });
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    page.on("console", (message) => { if (message.type() === "error") report.consoleErrors.push(message.text()); });
    page.on("pageerror", (error) => report.pageErrors.push(error.message));
    page.on("response", (response) => { if (response.status() >= 400) report.httpFailures.push({ method: response.request().method(), status: response.status(), path: new URL(response.url()).pathname }); });
    for (const study of seeded) report.projects[study.key] = await runProjectLoop(page, apiBase, appUrl, outputDir, study);
    const stableAfter = await stableSnapshot();
    report.runtime.stableUnchanged = JSON.stringify(stableBefore) === JSON.stringify(stableAfter);
    if (!report.runtime.stableUnchanged) report.failures.push("stable-runtime-changed");
    if (report.consoleErrors.length) report.failures.push(`console-errors:${report.consoleErrors.length}`);
    if (report.pageErrors.length) report.failures.push(`page-errors:${report.pageErrors.length}`);
    if (report.httpFailures.length) report.failures.push(`http-failures:${JSON.stringify(report.httpFailures)}`);
    for (const [key, value] of Object.entries(report.projects)) {
      if (value.metrics.pageOverflowX > 0 || value.metrics.drawerOverflowX > 0) report.failures.push(`${key}:horizontal-overflow`);
      if (value.metrics.activeStage !== "PICOS设计" || value.metrics.activeGroup !== "研究人群") report.failures.push(`${key}:wrong-focused-view`);
      if (!value.staleAffectedSections.includes("5.2")) report.failures.push(`${key}:5.2-not-invalidated`);
    }
  } finally {
    await browser?.close(); await stopService(vite); await stopService(api);
    report.runtime.apiLogTail = api.output.slice(-80); report.runtime.viteLogTail = vite.output.slice(-40);
    if (process.env.PRESERVE_QC_RUNTIME !== "1") { await rm(runtimeDir, { recursive: true, force: true }); report.runtime.runtimeRemoved = true; }
  }
  report.passed = report.failures.length === 0 && Object.keys(report.projects).length === studies.length;
  await writeFile(path.join(outputDir, "medical_writing_section_interaction_isolated_qc.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: report.passed, failures: report.failures, projects: report.projects }, null, 2));
  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
