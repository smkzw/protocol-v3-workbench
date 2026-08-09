import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const outputDir = path.join(projectRoot, "records/active_slices/medical_writing_scale_registry_20260717/browser_qc");
const stableRuntimeDir = path.resolve(projectRoot, "../..", "runtime");
const playwrightPath = process.env.PLAYWRIGHT_PATH || "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const isolatedDirectAiEnv = {
  WORKBENCH_AI_PROVIDER: "deepseek",
  WORKBENCH_AI_TRANSPORT: "openai_compatible",
  WORKBENCH_AI_BASE_URL: "https://api.deepseek.com/v1",
  WORKBENCH_AI_MODEL: "deepseek-v4-pro",
  DEEPSEEK_API_KEY: "isolated-qc-placeholder",
  WORKBENCH_AI_DEPLOYMENT_PROFILE: "local_private_clinical",
};

async function runW4CStaticAppendixChecks() {
  // W4_C_STATIC_APPENDIX_CHECKS
  const [journey, preview] = await Promise.all([
    readFile(path.join(frontendRoot, "src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx"), "utf8"),
    readFile(path.join(frontendRoot, "src/features/medical-writing/InstrumentAppendixPreview.jsx"), "utf8"),
  ]);
  const failures = [];
  const expect = (condition, label) => { if (!condition) failures.push(label); };
  expect(journey.includes("InstrumentAppendixPreview"), "preview-wired");
  expect(journey.includes("appendixPages"), "pages-state-from-working-copy");
  expect(preview.includes('loading="lazy"'), "lazy-thumbnails");
  expect(preview.includes('data-testid="instrument-appendix-review-image"'), "single-review-image");
  expect(preview.includes("appendix-page-count-mismatch"), "mismatch-notice");
  expect(preview.includes('data-page-count="0"'), "zero-page-state");
  expect(preview.includes("ArrowLeft") && preview.includes("Escape"), "keyboard-nav");
  expect(journey.includes("prefill-package/adopt-composite"), "w4a-composite-preserved");
  expect(journey.includes("只读模式可审阅原始页面"), "readonly-review-copy");
  if (failures.length) throw new Error(`W4-C static appendix checks failed: ${failures.join(", ")}`);
  return { ninePageCapable: true, readonlyReviewPreserved: true, w4ACompositePreserved: true };
}

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
  const collect = (chunk) => { output.push(String(chunk)); if (output.length > 300) output.shift(); };
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
        snapshot[path.relative(root, absolute)] = { bytes: metadata.size, sha256: await fileSha256(absolute) };
      }
    }
  }
  await visit(root);
  return snapshot;
}

function sqliteIntegrity(runtimeDir) {
  const find = spawnSync("find", [runtimeDir, "-maxdepth", "1", "-name", "*.sqlite3", "-print"], { encoding: "utf8" });
  return Object.fromEntries(find.stdout.trim().split("\n").filter(Boolean).map((filePath) => {
    const check = spawnSync("sqlite3", [filePath, "PRAGMA integrity_check;"], { encoding: "utf8" });
    return [path.basename(filePath), check.status === 0 ? check.stdout.trim() : check.stderr.trim()];
  }));
}

const rights = (status = "unknown", owner = "", evidenceUrl = "") => ({
  status, full_text_policy: "metadata_only", owner, license_reference: "", evidence_url: evidenceUrl,
  checked_at: null, confirmed_by: "", confirmed_at: null,
});
const translation = (status = "unknown", versionLabel = "", sourceUrl = "") => ({
  source_language: "英语", target_language: "简体中文", status, version_label: versionLabel,
  source_url: sourceUrl, artifact_id: "", reviewed_by: "", reviewed_at: null,
});
const source = (sourceId, locator, title) => [{
  source_kind: "project_protocol", source_id: sourceId, title, url: "", locator,
  artifact_id: "", evidence_sha256: "", accessed_at: null,
}];

function instrument(overrides) {
  return {
    instrument_id: overrides.instrument_id,
    canonical_name_zh: overrides.canonical_name_zh,
    canonical_name_en: overrides.canonical_name_en || "",
    acronym: overrides.acronym || "",
    version_label: overrides.version_label || "",
    instrument_kind: overrides.instrument_kind || "clinician_reported",
    administration_mode: overrides.administration_mode || "访视现场评估",
    respondent: overrides.respondent || "研究者",
    recall_period: overrides.recall_period || "",
    scoring_range: overrides.scoring_range || "",
    scoring_direction: overrides.scoring_direction || "",
    scoring_summary: overrides.scoring_summary || "",
    study_purpose: overrides.study_purpose || "",
    endpoint_paths: overrides.endpoint_paths || ["picos.other_secondary_endpoints"],
    visit_labels: overrides.visit_labels || ["基线（D1）", "第8周（D57±3天）"],
    soa_activity_ids: [],
    appendix_locator: overrides.appendix_locator || "",
    protocol_modified: Boolean(overrides.protocol_modified),
    source_synopsis_only: Boolean(overrides.source_synopsis_only),
    source_bindings: overrides.source_bindings || [],
    rights: overrides.rights || rights(),
    translation: overrides.translation || translation("not_needed", "项目方案中文表述"),
    confirmation_status: "needs_review",
    confirmed_by: "",
    confirmed_at: null,
    notes: "",
  };
}

const cardiffUrl = "https://www.cardiff.ac.uk/medicine/resources/quality-of-life-questionnaires/dermatology-life-quality-index";
const studies = [
  {
    key: "rux",
    project: { project_code: "RUX-03-002-QC", project_name: "磷酸芦可替尼乳膏AD III期量表QC", indication: "特应性皮炎", product_name: "磷酸芦可替尼乳膏", study_phase: "III期", protocol_id: "RUX-03-002", protocol_version: "V1.3" },
    framing: { protocol_id: "RUX-03-002", version: "V1.3", document_title: "磷酸芦可替尼乳膏治疗特应性皮炎的III期临床研究方案", indication: "特应性皮炎", clinicaltrials_condition_term: "Atopic Dermatitis", study_phase: "III期", intrinsic_objectives: ["确证性研究"], investigational_product: "磷酸芦可替尼乳膏", target_mechanism: "JAK1/JAK2抑制剂", competitor_target_scope: "外用JAK抑制剂及同治疗线创新药", development_regions: ["中国"], design_pattern: "随机、双盲、安慰剂对照、多中心研究", population_intent: "12周岁及以上轻中度特应性皮炎试验参与者", key_uncertainties: [], manual_source_ids: ["RUX-03-002 V1.3"], terminology_policy: "cde_participant" },
    picos: { design_archetype: "randomized_confirmatory", field_applicability: {}, population_summary: "12周岁及以上轻中度特应性皮炎试验参与者。", inclusion_modules: ["IGA评分2-3分"], exclusion_modules: ["活动性感染"], washout_rules: [], intervention_summary: "磷酸芦可替尼乳膏每日两次外用。", intervention_dose_regimen: "每日两次，间隔至少8小时。", allowed_concomitant_rules: [], required_background_rules: [], prohibited_concomitant_rules: [], assessment_timing_restrictions: [], comparator_summary: "匹配安慰剂每日两次外用。", primary_endpoint: "第8周达到IGA-TS的试验参与者比例。", key_secondary_endpoints: ["第8周EASI 75应答率。"], other_secondary_endpoints: ["第8周EASI较基线变化率。", "第8周DLQI较基线变化值。", "第8周PROMIS睡眠相关影响较基线变化值。"], exploratory_endpoints: [], safety_endpoints: ["TEAE和SAE发生率。"], aesi_definitions: [], assessment_instruments: [
      instrument({ instrument_id: "rux_easi", canonical_name_zh: "湿疹面积和严重程度指数", canonical_name_en: "Eczema Area and Severity Index", acronym: "EASI", scoring_range: "0-72", scoring_direction: "分值越高表示特应性皮炎严重程度越高", scoring_summary: "评估四个身体部位的皮损面积及红斑、硬结/丘疹、水肿、抓痕和苔藓样变。", endpoint_paths: ["picos.key_secondary_endpoints", "picos.other_secondary_endpoints"], appendix_locator: "附录2；P01027-P01034", source_bindings: source("rux_protocol_v1_3", "docx:P00589;P00732-P00733;P01027-P01034", "RUX-03-002 V1.3研究方案") }),
      instrument({ instrument_id: "rux_dlqi", canonical_name_zh: "皮肤病生活质量指数", canonical_name_en: "Dermatology Life Quality Index", acronym: "DLQI", instrument_kind: "patient_reported", respondent: "试验参与者（基线年龄≥16周岁）", recall_period: "过去7天", administration_mode: "访视现场填写", scoring_range: "0-30", scoring_direction: "分值越高表示生活质量受影响程度越大", endpoint_paths: ["picos.other_secondary_endpoints"], appendix_locator: "附录4；P01048", source_bindings: source("rux_protocol_v1_3", "docx:P00744;P01048;table_after_P01048", "RUX-03-002 V1.3研究方案"), rights: rights("permission_required", "Cardiff University", cardiffUrl), translation: translation("official_available", "简体中文具体版本待医学确认", cardiffUrl) }),
      instrument({ instrument_id: "rux_promis_8a", canonical_name_zh: "PROMIS简表-睡眠相关影响", canonical_name_en: "PROMIS Sleep-Related Impairment 8a", acronym: "PROMIS 8a", version_label: "8a；方案修改的24小时回忆版", instrument_kind: "patient_reported", respondent: "试验参与者", recall_period: "过去24小时", administration_mode: "每日晚间电子日记", scoring_range: "8-40", scoring_direction: "分值越高表示睡眠相关影响越严重", protocol_modified: true, appendix_locator: "附录7；P01080-P01081", source_bindings: source("rux_protocol_v1_3", "docx:P00750-P00753;P01080-P01081", "RUX-03-002 V1.3研究方案"), rights: rights("permission_required", "HealthMeasures", "https://www.healthmeasures.net/explore-measurement-systems/promis"), translation: translation("unknown") }),
    ], study_epochs: ["筛选期", "双盲治疗期", "开放治疗期"], visit_strategy: "筛选、基线及第2、4、8、12、16、20、24周访视。", estimand_strategy: "评价治疗策略下第8周IGA-TS应答差异。", sample_size_strategy: "依据主要终点应答率差异估算。", statistical_strategy: "主要终点采用分层方法比较。" },
  },
  {
    key: "d001",
    project: { project_code: "CMS-D001-QC", project_name: "CMS-D001银屑病II/III期量表QC", indication: "斑块状银屑病", product_name: "CMS-D001片", study_phase: "II/III期", protocol_id: "CMS-D001", protocol_version: "V1.0" },
    framing: { protocol_id: "CMS-D001", version: "V1.0", document_title: "CMS-D001片治疗斑块状银屑病的II/III期临床研究方案", indication: "斑块状银屑病", clinicaltrials_condition_term: "Plaque Psoriasis", study_phase: "II/III期", intrinsic_objectives: ["剂量探索", "确证性研究"], investigational_product: "CMS-D001片", target_mechanism: "创新小分子免疫调节剂", competitor_target_scope: "同适应症口服创新疗法", development_regions: ["中国"], design_pattern: "随机、双盲、安慰剂对照的II/III期研究", population_intent: "中重度斑块状银屑病成人试验参与者", key_uncertainties: [], manual_source_ids: ["CMS-D001 V1.0"], terminology_policy: "cde_participant" },
    picos: { design_archetype: "randomized_confirmatory", field_applicability: {}, population_summary: "中重度斑块状银屑病成人试验参与者。", inclusion_modules: ["PASI和PGA达到方案规定严重程度"], exclusion_modules: ["活动性感染"], washout_rules: [], intervention_summary: "CMS-D001片按随机分组口服给药。", intervention_dose_regimen: "按II期剂量探索和III期确证方案给药。", allowed_concomitant_rules: [], required_background_rules: [], prohibited_concomitant_rules: [], assessment_timing_restrictions: [], comparator_summary: "匹配安慰剂对照。", primary_endpoint: "方案规定时间点达到PASI 75的试验参与者比例。", key_secondary_endpoints: ["方案规定时间点达到PGA 0/1的试验参与者比例。"], other_secondary_endpoints: ["PASI、PGA、BSA和DLQI较基线变化。"], exploratory_endpoints: [], safety_endpoints: ["TEAE和SAE发生率。"], aesi_definitions: [], assessment_instruments: [
      instrument({ instrument_id: "d001_pasi", canonical_name_zh: "银屑病面积和严重程度指数", canonical_name_en: "Psoriasis Area and Severity Index", acronym: "PASI", scoring_range: "0-72", scoring_direction: "分值越高表示银屑病严重程度越高", endpoint_paths: ["picos.primary_endpoint", "picos.other_secondary_endpoints"], appendix_locator: "方案疗效评价章节；P00652附近", source_bindings: source("d001_protocol_v1_0", "docx:abbreviation_table_row_73;P00652", "CMS-D001 V1.0研究方案") }),
      instrument({ instrument_id: "d001_pga", canonical_name_zh: "研究者总体评估", canonical_name_en: "Physician's Global Assessment", acronym: "PGA", scoring_range: "0-4", scoring_direction: "分值越高表示疾病严重程度越高", endpoint_paths: ["picos.key_secondary_endpoints", "picos.other_secondary_endpoints"], source_bindings: source("d001_protocol_v1_0", "docx:abbreviation_table_row_75;P00653", "CMS-D001 V1.0研究方案") }),
      instrument({ instrument_id: "d001_dlqi", canonical_name_zh: "皮肤病学生活质量指数", canonical_name_en: "Dermatology Life Quality Index", acronym: "DLQI", instrument_kind: "patient_reported", respondent: "试验参与者", recall_period: "过去7天", scoring_range: "0-30", scoring_direction: "分值越高表示生活质量受影响程度越大", appendix_locator: "附录6；P01215-P01257", source_bindings: source("d001_protocol_v1_0", "docx:P00655;P01215-P01257", "CMS-D001 V1.0研究方案"), rights: rights("permission_required", "Cardiff University", cardiffUrl), translation: translation("official_available", "简体中文具体版本待医学确认", cardiffUrl) }),
    ], study_epochs: ["筛选期", "治疗期", "扩展期"], visit_strategy: "按II期与III期研究流程表执行筛选、基线和治疗期访视。", estimand_strategy: "主要估计目标评价随机治疗策略下PASI应答差异。", sample_size_strategy: "依据PASI 75应答率差异估算。", statistical_strategy: "分类终点采用分层方法比较。" },
  },
];

async function seedStudy(apiBase, study) {
  const created = await request(apiBase, "/api/projects", { method: "POST", body: {
    ...study.project, protocol_date: "2026-07-17", entry_mode: "from_zero", actor: "medical_manager_qc",
    idempotency_key: `scale-qc-create-${study.key}-20260717`,
  } });
  const projectId = created.project.project_id;
  const initial = created.authoring_journey;
  const preview = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`, { method: "POST", body: { expected_revision: initial.revision, stage: "framing", framing: study.framing } });
  const committed = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/stages/framing/commit`, { method: "POST", body: {
    expected_revision: initial.revision, stage: "framing", framing: study.framing, impact_preview_id: preview.preview_id,
    actor: "medical_manager_qc", idempotency_key: `scale-qc-framing-${study.key}-20260717`,
  } });
  const drafted = await request(apiBase, `/api/projects/${projectId}/medical-writing/authoring-journey/stages/picos/draft`, { method: "POST", body: {
    expected_revision: committed.revision, stage: "picos", picos: study.picos,
    actor: "medical_manager_qc", idempotency_key: `scale-qc-picos-${study.key}-20260717`,
  } });
  return { ...study, projectId, seededRevision: drafted.revision };
}

async function openInstrumentEditor(page, appUrl, projectId) {
  if (!page.url().startsWith(appUrl)) await page.goto(appUrl, { waitUntil: "domcontentloaded" });
  const selector = page.locator('select[aria-label="选择临床研究项目"]');
  await selector.waitFor({ state: "visible" });
  await selector.selectOption(projectId);
  await page.locator(".nav-item").filter({ hasText: /^医学写作$/ }).click();
  await page.locator(".authoring-journey-shell").waitFor({ state: "visible" });
  await page.locator(".authoring-stage-strip button").filter({ hasText: "PICOS设计" }).click();
  const advanced = page.locator("details.authoring-advanced-refinement");
  await advanced.waitFor({ state: "attached" });
  if (!(await advanced.evaluate((node) => node.open))) {
    await advanced.locator(":scope > summary").click();
  }
  await page.locator(".authoring-group-tabs button").filter({ hasText: /^结局指标$/ }).click();
  const registry = page.locator(".authoring-instrument-registry");
  await registry.waitFor({ state: "visible" });
  const viewport = page.viewportSize();
  await page.mouse.move((viewport?.width || 1440) - 20, 20);
  await page.evaluate(() => document.activeElement?.blur());
  return registry;
}

async function visualMetrics(page) {
  return page.evaluate(() => {
    const registry = document.querySelector(".authoring-instrument-registry");
    const boxes = Array.from(registry?.querySelectorAll("input, textarea, select, button") || []).map((node) => {
      const rect = node.getBoundingClientRect();
      return { text: node.getAttribute("aria-label") || node.textContent?.trim().slice(0, 40) || node.tagName, left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height };
    });
    return {
      viewport: { width: innerWidth, height: innerHeight },
      documentHorizontalOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      registryHorizontalOverflow: registry ? registry.scrollWidth - registry.clientWidth : null,
      zeroSizedControls: boxes.filter((item) => item.width < 8 || item.height < 8),
      controlsOutsideViewport: boxes.filter((item) => item.left < -1 || item.right > innerWidth + 1),
      bodyTextLength: document.body.innerText.length,
    };
  });
}

async function main() {
  const appendixStatic = await runW4CStaticAppendixChecks();
  if (process.env.QC_STATIC_ONLY === "1") {
    await mkdir(outputDir, { recursive: true });
    const report = { passed: true, staticOnly: true, appendixStatic, interactions: ["static-appendix-preview"], errors: [] };
    await writeFile(path.join(outputDir, "medical_writing_assessment_instruments_isolated_qc.json"), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    return;
  }
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const runtimeDir = await mkdtemp(path.join(tmpdir(), "mw-scale-registry-runtime-"));
  const apiPort = await freePort(8941);
  const vitePort = await freePort(5201);
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;
  const stableBefore = await directorySnapshot(stableRuntimeDir);
  const api = startService(process.env.PYTHON_BIN || "python3", ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], {
    cwd: projectRoot,
    env: {
      ...process.env,
      ...isolatedDirectAiEnv,
      WORKBENCH_RUNTIME_DIR: runtimeDir,
      PYTHONUNBUFFERED: "1",
    },
  });
  const vite = startService(process.env.NPM_BIN || "npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"], { cwd: frontendRoot, env: { ...process.env, VITE_API_PROXY_TARGET: apiBase } });
  const report = {
    passed: false,
    appendixStatic,
    startedAt: new Date().toISOString(),
    appUrl,
    apiBase,
    sourceFiles: {
      rux: "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/RUX-03-002-自查文件包-20260107/10-临床试验重要文件/1-临床试验方案/V1.3版-2024.8.14/磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx",
      d001: "/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/CMS-D001 银屑病2、3期临床方案 v1.0-2025.12.21.docx",
    },
    sourceSha256: {
      component: await fileSha256(path.join(frontendRoot, "src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx")),
      contracts: await fileSha256(path.join(projectRoot, "packages/contracts/workbench_contracts/models.py")),
      qc: await fileSha256(fileURLToPath(import.meta.url)),
    },
    runtime: { isolated: true, stableRuntimeDir, stableBefore, stableAfter: {}, stableUnchanged: false },
    studies: [],
    interactions: [],
    errors: [],
    consoleErrors: [],
    httpFailures: [],
    unexpectedHttpFailures: [],
  };
  let browser;
  try {
    await waitForHttp(`${apiBase}/api/health`);
    await waitForHttp(appUrl);
    const seeded = [];
    for (const study of studies) seeded.push(await seedStudy(apiBase, study));
    const { chromium } = await import(playwrightPath);
    browser = await chromium.launch({ headless: true, executablePath: chromePath });
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
    page.on("pageerror", (error) => report.errors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error") report.consoleErrors.push(message.text()); });
    page.on("response", (response) => {
      if (response.status() >= 400) report.httpFailures.push({ status: response.status(), url: response.url() });
    });
    await page.goto(appUrl, { waitUntil: "domcontentloaded" });

    const rux = seeded.find((item) => item.key === "rux");
    let registry = await openInstrumentEditor(page, appUrl, rux.projectId);
    const ruxText = await registry.innerText();
    for (const acronym of ["EASI", "DLQI", "PROMIS 8a"]) {
      if (!ruxText.includes(acronym)) throw new Error(`RUX registry missing ${acronym}`);
    }
    if (ruxText.includes("PASI") || ruxText.includes("PGA")) throw new Error("RUX registry contains D001-only instrument");
    await registry.evaluate((node) => node.scrollIntoView({ block: "start" }));
    await page.screenshot({ path: path.join(outputDir, "rux_registry_1920x1080.png"), fullPage: false });
    await registry.screenshot({ path: path.join(outputDir, "rux_registry_detail.png") });
    report.studies.push({ key: "rux", projectId: rux.projectId, seededInstruments: ["EASI", "DLQI", "PROMIS 8a"], visual: await visualMetrics(page) });

    await registry.getByRole("button", { name: /新增工具/ }).click();
    await registry.getByLabel("中文规范名称").fill("受累体表面积补充评估");
    await registry.getByLabel("英文规范名称").fill("Body Surface Area supplemental assessment");
    await registry.getByLabel("缩写").fill("BSA-QC");
    await registry.getByLabel("工具类型").selectOption("clinician_reported");
    await registry.getByLabel("填写/评估者").fill("研究者");
    await registry.getByLabel("评分范围").fill("0-100%");
    await registry.getByLabel("评分方向").fill("数值越高表示受累体表面积越大");
    await registry.getByLabel("本研究用途").fill("验证新增、保存、重载和删除的完整交互链路");
    await registry.locator(".authoring-instrument-bindings").getByLabel("其他次要终点").check();
    await registry.getByLabel("评价访视/时点（每行一项）").fill("基线（D1）\n第8周（D57±3天）");
    const governance = registry.locator(".authoring-instrument-governance section");
    await governance.nth(0).locator("select").selectOption("not_needed");
    await governance.nth(1).locator("select").selectOption("unknown");
    await registry.getByRole("button", { name: "确认本项目用法" }).click();
    await page.getByRole("button", { name: "保存草稿" }).click();
    await page.locator(".authoring-journey-message").filter({ hasText: "草稿已保存" }).waitFor();
    report.interactions.push("RUX:add-fill-bind-govern-confirm-save");

    await page.reload({ waitUntil: "domcontentloaded" });
    registry = await openInstrumentEditor(page, appUrl, rux.projectId);
    await registry.locator(".authoring-instrument-list button").filter({ hasText: "BSA-QC" }).click();
    if (await registry.getByLabel("评分范围").inputValue() !== "0-100%") throw new Error("RUX added instrument did not persist after reload");
    report.interactions.push("RUX:full-page-reload-persisted");
    await registry.getByRole("button", { name: /删除/ }).click();
    await page.getByRole("button", { name: "保存草稿" }).click();
    await page.locator(".authoring-journey-message").filter({ hasText: "草稿已保存" }).waitFor();
    await page.reload({ waitUntil: "domcontentloaded" });
    registry = await openInstrumentEditor(page, appUrl, rux.projectId);
    if ((await registry.innerText()).includes("BSA-QC")) throw new Error("RUX deleted instrument returned after reload");
    report.interactions.push("RUX:delete-save-reload");

    const d001 = seeded.find((item) => item.key === "d001");
    await page.setViewportSize({ width: 1440, height: 900 });
    registry = await openInstrumentEditor(page, appUrl, d001.projectId);
    const d001Text = await registry.innerText();
    for (const acronym of ["PASI", "PGA", "DLQI"]) {
      if (!d001Text.includes(acronym)) throw new Error(`D001 registry missing ${acronym}`);
    }
    if (d001Text.includes("EASI") || d001Text.includes("PROMIS")) throw new Error("D001 registry contains RUX-only instrument");
    await registry.locator(".authoring-instrument-list button").filter({ hasText: "DLQI" }).click();
    const rightsState = await governance.nth(1).locator("select").inputValue().catch(() => "");
    await registry.evaluate((node) => node.scrollIntoView({ block: "start" }));
    await page.screenshot({ path: path.join(outputDir, "d001_registry_1440x900.png"), fullPage: false });
    await registry.screenshot({ path: path.join(outputDir, "d001_registry_detail.png") });
    report.studies.push({ key: "d001", projectId: d001.projectId, seededInstruments: ["PASI", "PGA", "DLQI"], rightsState, visual: await visualMetrics(page) });
    report.interactions.push("D001:select-project-open-three-instruments-no-cross-project-leak");

    for (const study of seeded) {
      const persisted = await request(apiBase, `/api/projects/${study.projectId}/medical-writing/authoring-journey`);
      report.studies.find((item) => item.key === study.key).persistedInstruments = (persisted.picos_draft?.picos?.assessment_instruments || persisted.picos?.assessment_instruments || []).map((item) => item.acronym);
    }
    report.runtime.sqliteIntegrity = sqliteIntegrity(runtimeDir);
    const invalidDatabases = Object.entries(report.runtime.sqliteIntegrity).filter(([, value]) => value !== "ok");
    if (invalidDatabases.length) report.errors.push(`sqlite-integrity:${JSON.stringify(invalidDatabases)}`);
    const expectedEmptySuffixes = ["/medical-writing/manifest", "/medical-writing/document-session"];
    report.unexpectedHttpFailures = report.httpFailures.filter((item) => !(item.status === 404 && expectedEmptySuffixes.some((suffix) => new URL(item.url).pathname.endsWith(suffix))));
    if (report.unexpectedHttpFailures.length) report.errors.push(`unexpected-http-failures:${JSON.stringify(report.unexpectedHttpFailures)}`);
  } catch (error) {
    report.errors.push(error.stack || error.message);
  } finally {
    await browser?.close();
    await stopService(vite);
    await stopService(api);
    report.runtime.apiLogTail = api.output.slice(-60);
    report.runtime.viteLogTail = vite.output.slice(-30);
    report.runtime.stableAfter = await directorySnapshot(stableRuntimeDir);
    report.runtime.stableUnchanged = JSON.stringify(stableBefore) === JSON.stringify(report.runtime.stableAfter);
    if (!report.runtime.stableUnchanged) report.errors.push("stable-runtime-changed-during-isolated-qc");
    await rm(runtimeDir, { recursive: true, force: true });
    report.runtime.runtimeRemoved = true;
  }
  const visualOk = report.studies.length === 2 && report.studies.every((item) => item.visual.documentHorizontalOverflow <= 0 && item.visual.registryHorizontalOverflow <= 0 && !item.visual.zeroSizedControls.length && !item.visual.controlsOutsideViewport.length);
  const consoleErrorsExpected = report.consoleErrors.every((item) => item === "Failed to load resource: the server responded with a status of 404 (Not Found)") && report.consoleErrors.length === report.httpFailures.length;
  report.passed = report.errors.length === 0 && (report.consoleErrors.length === 0 || consoleErrorsExpected) && report.runtime.stableUnchanged && visualOk && report.interactions.length === 4;
  report.finishedAt = new Date().toISOString();
  await writeFile(path.join(outputDir, "medical_writing_assessment_instruments_isolated_qc.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: report.passed, studies: report.studies, interactions: report.interactions, errors: report.errors, consoleErrors: report.consoleErrors }, null, 2));
  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
