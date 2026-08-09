import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const stableRuntimeDir = path.resolve(projectRoot, "../..", "runtime");
const outputDir = path.join(
  projectRoot,
  "records/active_slices/medical_writing_cross_indication_reference_gate_20260718/dynamic_modules_qc",
);
const playwrightPath = process.env.PLAYWRIGHT_PATH
  || "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
const chromePath = process.env.CHROME_PATH
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const study = {
  project: {
    project_code: "QC-RA-DYNAMIC-MODULES",
    project_name: "类风湿关节炎II期动态章节QC",
    indication: "类风湿关节炎",
    product_name: "CMS-RA-201注射液",
    study_phase: "II期",
    protocol_id: "QC-RA-DYNAMIC-MODULES",
    protocol_version: "V0.1",
  },
  framing: {
    protocol_id: "QC-RA-DYNAMIC-MODULES",
    version: "V0.1",
    document_title: "CMS-RA-201注射液治疗类风湿关节炎的II期临床研究方案",
    indication: "类风湿关节炎",
    clinicaltrials_condition_term: "Rheumatoid Arthritis",
    study_phase: "II期",
    intrinsic_objectives: ["概念验证（PoC）", "剂量探索"],
    investigational_product: "CMS-RA-201注射液",
    target_mechanism: "靶向炎症通路的全人源单克隆抗体",
    competitor_target_scope: "同靶点、同机制及同治疗线生物制剂",
    development_regions: ["中国"],
    design_pattern: "随机、双盲、安慰剂对照、平行组、多中心II期剂量探索研究",
    population_intent: "既往甲氨蝶呤治疗反应不充分的中重度活动性类风湿关节炎成人试验参与者",
    key_uncertainties: [],
    manual_source_ids: [],
    terminology_policy: "cde_participant",
  },
  picos: {
    design_archetype: "randomized_confirmatory",
    field_applicability: {},
    population_summary: "18至75岁、既往甲氨蝶呤治疗反应不充分的中重度活动性类风湿关节炎成人试验参与者。",
    inclusion_modules: ["筛选期与基线期满足疾病活动度阈值", "稳定使用背景甲氨蝶呤"],
    exclusion_modules: ["活动性感染", "近期使用其他生物制剂且未完成洗脱"],
    washout_rules: ["既往生物制剂按药代特征和方案规定完成洗脱"],
    intervention_summary: "CMS-RA-201低剂量组和高剂量组，皮下注射。",
    intervention_dose_regimen: "每4周给药一次，持续24周。",
    allowed_concomitant_rules: ["稳定剂量非甾体抗炎药"],
    required_background_rules: ["稳定剂量甲氨蝶呤", "按方案补充叶酸"],
    prohibited_concomitant_rules: ["其他生物制剂", "JAK抑制剂"],
    assessment_timing_restrictions: ["疗效评价前24小时限制救援性镇痛药。"],
    comparator_summary: "匹配安慰剂，每4周皮下注射一次。",
    primary_endpoint: "第12周ACR20应答率。",
    key_secondary_endpoints: ["第12周DAS28-CRP较基线变化。"],
    other_secondary_endpoints: ["第24周ACR50和ACR70应答率。"],
    exploratory_endpoints: ["炎症生物标志物较基线变化。"],
    safety_endpoints: ["TEAE、SAE及导致停药的AE发生率。"],
    aesi_definitions: ["严重感染", "超敏反应"],
    assessment_instruments: [],
    study_epochs: ["筛选期", "双盲治疗期", "安全性随访期"],
    visit_strategy: "筛选、基线，治疗期每4周访视，末次给药后完成安全性随访。",
    estimand_strategy: "主要估计目标评价治疗策略下第12周ACR20应答差异。",
    sample_size_strategy: "基于预期应答率差异、双侧显著性水平、检验效能和脱落率估算。",
    statistical_strategy: "主要终点采用分层分析；本研究不设置正式期中分析。",
  },
};

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
    if (output.length > 240) output.shift();
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

async function request(apiBase, pathname, { method = "GET", body } = {}) {
  const response = await fetch(`${apiBase}${pathname}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`${method} ${pathname} -> ${response.status}: ${JSON.stringify(payload)}`);
  }
  return payload;
}

async function stableSnapshot() {
  const names = (await readdir(stableRuntimeDir))
    .filter((name) => name.endsWith(".sqlite3"))
    .sort();
  return Object.fromEntries(await Promise.all(names.map(async (name) => [
    name,
    createHash("sha256").update(await readFile(path.join(stableRuntimeDir, name))).digest("hex"),
  ])));
}

async function seedProject(apiBase) {
  const template = await request(apiBase, "/api/medical-writing/protocol-templates/default");
  const created = await request(apiBase, "/api/projects", {
    method: "POST",
    body: {
      ...study.project,
      protocol_date: "2026-07-19",
      entry_mode: "from_zero",
      actor: "medical_manager_qc",
      idempotency_key: "dynamic-module-project-ra",
    },
  });
  const projectId = created.project.project_id;
  const initial = created.authoring_journey;
  const framingPreview = await request(
    apiBase,
    `/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`,
    { method: "POST", body: { expected_revision: initial.revision, stage: "framing", framing: study.framing } },
  );
  const framed = await request(
    apiBase,
    `/api/projects/${projectId}/medical-writing/authoring-journey/stages/framing/commit`,
    {
      method: "POST",
      body: {
        expected_revision: initial.revision,
        stage: "framing",
        framing: study.framing,
        impact_preview_id: framingPreview.preview_id,
        actor: "medical_manager_qc",
        idempotency_key: "dynamic-module-framing-ra",
      },
    },
  );
  const picosPreview = await request(
    apiBase,
    `/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`,
    { method: "POST", body: { expected_revision: framed.revision, stage: "picos", picos: study.picos } },
  );
  const designed = await request(
    apiBase,
    `/api/projects/${projectId}/medical-writing/authoring-journey/stages/picos/commit`,
    {
      method: "POST",
      body: {
        expected_revision: framed.revision,
        stage: "picos",
        picos: study.picos,
        impact_preview_id: picosPreview.preview_id,
        actor: "medical_manager_qc",
        idempotency_key: "dynamic-module-picos-ra",
      },
    },
  );
  const allowed = await request(
    apiBase,
    `/api/projects/${projectId}/medical-writing/authoring-journey/corpus-gate/override`,
    {
      method: "POST",
      body: {
        expected_revision: designed.revision,
        reason: "隔离环境验证类风湿关节炎II期方案动态章节、跨文档传播和可恢复历史。",
        acknowledged_missing_requirements: designed.corpus_gate?.missing_requirements || [],
        actor: "medical_manager_qc",
        idempotency_key: "dynamic-module-corpus-ra",
      },
    },
  );
  const definition = allowed.study_definition;
  await request(
    apiBase,
    `/api/projects/${projectId}/medical-writing/greenfield-document`,
    {
      method: "POST",
      body: {
        protocol_id: allowed.framing.protocol_id,
        version: allowed.framing.version,
        document_title: allowed.framing.document_title,
        indication: allowed.framing.indication,
        study_phase: allowed.framing.study_phase,
        source_study_definition_id: definition.definition_id,
        source_study_definition_revision: definition.revision,
        source_study_definition_sha256: definition.state_sha256,
        template_id: template.template_id,
        template_version: template.template_version,
        actor: "medical_manager_qc",
        idempotency_key: "dynamic-module-document-ra",
      },
    },
  );
  return projectId;
}

const synopsisLabels = (contentBlocks) => contentBlocks
  .flatMap((block) => block.structured_table?.rows || [])
  .map((row) => row.label || row.cells?.[0]?.value || row.cells?.[0]?.text || "");

async function synopsisSnapshot(apiBase, projectId, document) {
  const section = document.sections.find((item) => item.node_kind === "protocol_synopsis");
  if (!section) return { labels: [], hasInterim: false };
  const content = await request(
    apiBase,
    `/api/projects/${projectId}/medical-writing/document-session/sections/${section.section_id}`,
  );
  const labels = synopsisLabels(content.content_blocks || []);
  return {
    labels,
    hasInterim: labels.some((label) => String(label).includes("期中分析")),
  };
}

async function main() {
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const runtimeDir = await mkdtemp(path.join(tmpdir(), "mw-dynamic-modules-qc-"));
  const apiPort = await freePort(8961);
  const vitePort = await freePort(5211);
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;
  const stableBefore = await stableSnapshot();
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
    failures: [],
    runtime: { isolated: true, runtimeDir },
    consoleErrors: [],
    pageErrors: [],
    httpFailures: [],
  };
  let browser;
  try {
    await waitForHttp(`${apiBase}/api/health`);
    await waitForHttp(appUrl);
    const projectId = await seedProject(apiBase);
    report.projectId = projectId;
    const before = await request(apiBase, `/api/projects/${projectId}/medical-writing/document-session`);
    const beforeSynopsis = await synopsisSnapshot(apiBase, projectId, before);
    report.before = {
      sectionCount: before.sections.length,
      interimSection: before.sections.some((section) => section.heading === "期中分析"),
      synopsisInterim: beforeSynopsis.hasInterim,
    };
    if (report.before.interimSection || report.before.synopsisInterim) {
      report.failures.push("negative-interim-design-materialized");
    }

    const { chromium } = await import(playwrightPath);
    browser = await chromium.launch({ executablePath: chromePath, headless: true });
    const page = await browser.newPage({ viewport: { width: 1728, height: 1050 } });
    page.on("console", (message) => {
      if (message.type() === "error") report.consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => report.pageErrors.push(error.message));
    page.on("response", (response) => {
      if (response.status() >= 400) {
        report.httpFailures.push({
          method: response.request().method(),
          status: response.status(),
          path: new URL(response.url()).pathname,
        });
      }
    });
    await page.goto(appUrl, { waitUntil: "domcontentloaded" });
    const projectSelect = page.locator('select[aria-label="选择临床研究项目"]');
    await projectSelect.waitFor();
    await projectSelect.selectOption(projectId);
    await page.getByRole("button", { name: "医学写作" }).click();
    await page.getByText("研究方案文档编辑与AI修订", { exact: true }).waitFor();
    await page.getByRole("button", { name: "研究设计" }).click();
    const panel = page.locator(".protocol-module-resolution-panel");
    await panel.waitFor();
    const interimItem = panel.locator(".protocol-module-resolution-list > button")
      .filter({ hasText: "期中分析" });
    await interimItem.click();
    await panel.locator(".protocol-module-resolution-editor select")
      .selectOption("applicable|retain_full");
    await panel.locator(".protocol-module-resolution-editor textarea")
      .fill("医学经理确认本研究设置一次正式期中分析，并同步更新摘要和统计分析章节。");
    await panel.getByRole("button", { name: "应用到方案" }).click();
    await panel.locator(".protocol-module-resolution-message").waitFor();
    const enabledMessage = await panel.locator(".protocol-module-resolution-message").innerText();
    if (!enabledMessage.includes("设计选择已应用")) {
      throw new Error(`unexpected enable message: ${enabledMessage}`);
    }
    await interimItem.getByText("已纳入", { exact: true }).waitFor();
    await page.screenshot({
      path: path.join(outputDir, "ra_interim_enabled_1728x1050.png"),
      fullPage: false,
    });
    const enabled = await request(
      apiBase,
      `/api/projects/${projectId}/medical-writing/document-session`,
    );
    const enabledSynopsis = await synopsisSnapshot(apiBase, projectId, enabled);
    report.enabled = {
      message: enabledMessage,
      sectionCount: enabled.sections.length,
      interimSection: enabled.sections.some((section) => section.heading === "期中分析"),
      synopsisInterim: enabledSynopsis.hasInterim,
      synopsisLabels: enabledSynopsis.labels,
      pageOverflowX: await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
      panelOverflowX: await panel.evaluate((node) => node.scrollWidth - node.clientWidth),
    };
    if (!report.enabled.interimSection || !report.enabled.synopsisInterim) {
      report.failures.push("interim-enable-did-not-propagate");
    }

    await panel.locator(".protocol-module-resolution-list > button")
      .filter({ hasText: "期中分析" })
      .click();
    await panel.locator(".protocol-module-resolution-editor select")
      .selectOption("not_applicable|omit");
    await panel.locator(".protocol-module-resolution-editor textarea")
      .fill("医学经理确认本研究不设置正式期中分析，统计章节和方案摘要均不呈现该内容。");
    await panel.getByRole("button", { name: "应用到方案" }).click();
    await panel.locator(".protocol-module-resolution-message").waitFor();
    const disabledMessage = await panel.locator(".protocol-module-resolution-message").innerText();
    if (!disabledMessage.includes("设计选择已应用")) {
      throw new Error(`unexpected disable message: ${disabledMessage}`);
    }
    const disabled = await request(
      apiBase,
      `/api/projects/${projectId}/medical-writing/document-session`,
    );
    const disabledSynopsis = await synopsisSnapshot(apiBase, projectId, disabled);
    report.disabled = {
      message: disabledMessage,
      sectionCount: disabled.sections.length,
      interimSection: disabled.sections.some((section) => section.heading === "期中分析"),
      synopsisInterim: disabledSynopsis.hasInterim,
    };
    if (report.disabled.interimSection || report.disabled.synopsisInterim) {
      report.failures.push("interim-disable-did-not-propagate");
    }
    if (report.enabled.pageOverflowX > 0 || report.enabled.panelOverflowX > 0) {
      report.failures.push("desktop-horizontal-overflow");
    }
    if (report.consoleErrors.length) report.failures.push(`console-errors:${report.consoleErrors.length}`);
    if (report.pageErrors.length) report.failures.push(`page-errors:${report.pageErrors.length}`);
    if (report.httpFailures.length) {
      report.failures.push(`http-failures:${JSON.stringify(report.httpFailures)}`);
    }
    report.runtime.stableUnchanged = JSON.stringify(stableBefore)
      === JSON.stringify(await stableSnapshot());
    if (!report.runtime.stableUnchanged) report.failures.push("stable-runtime-changed");
  } catch (error) {
    report.failures.push(`runtime-error:${error.message}`);
    report.error = error.stack || error.message;
  } finally {
    await browser?.close();
    await stopService(vite);
    await stopService(api);
    report.runtime.apiLogTail = api.output.slice(-80);
    report.runtime.viteLogTail = vite.output.slice(-40);
    if (process.env.PRESERVE_QC_RUNTIME !== "1") {
      await rm(runtimeDir, { recursive: true, force: true });
      report.runtime.runtimeRemoved = true;
    }
  }
  report.passed = report.failures.length === 0;
  await writeFile(
    path.join(outputDir, "medical_writing_dynamic_modules_isolated_qc.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify({
    passed: report.passed,
    failures: report.failures,
    before: report.before,
    enabled: report.enabled,
    disabled: report.disabled,
  }, null, 2));
  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
