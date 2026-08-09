import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const playwrightPath = process.env.PLAYWRIGHT_PATH
  || "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5175/";
const apiUrl = process.env.API_URL || "http://127.0.0.1:8912";
const chromePath = process.env.CHROME_PATH
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const manifestPath = process.env.QC_PROJECT_MANIFEST;
const outputDir = process.env.QC_OUTPUT_DIR;

if (process.env.QC_ISOLATED_RUNTIME !== "1") {
  throw new Error("intervention-rules browser QC requires QC_ISOLATED_RUNTIME=1");
}
if (!manifestPath || !outputDir) {
  throw new Error("QC_PROJECT_MANIFEST and QC_OUTPUT_DIR are required");
}

const { chromium } = await import(playwrightPath);
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
await mkdir(outputDir, { recursive: true });

const projects = Object.fromEntries(
  manifest.projects.map((item) => [item.project_code, item]),
);
const projectSessions = {};
for (const project of manifest.projects) {
  const response = await fetch(`${apiUrl}/api/projects/${project.project_id}/medical-writing/document-session`);
  if (!response.ok) throw new Error(`document session ${response.status}: ${project.project_code}`);
  projectSessions[project.project_code] = await response.json();
}

const errors = [];
const failedResponses = [];
const expectedConflictResponses = [];
const observations = [];
const browser = await chromium.launch({ headless: true, executablePath: chromePath });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
page.on("console", (message) => {
  if (message.type() === "error") errors.push(`console: ${message.text()}`);
});
page.on("response", (response) => {
  if (response.status() === 409 && response.url().includes("/intervention-rules-projection")) {
    expectedConflictResponses.push(`409 ${response.url()}`);
  }
  if (response.status() >= 500) failedResponses.push(`${response.status()} ${response.url()}`);
});

async function selectProject(projectCode) {
  const project = projects[projectCode];
  const selector = page.locator('select[aria-label="选择临床研究项目"]');
  await selector.waitFor({ state: "visible" });
  await selector.selectOption(project.project_id);
  await page.waitForFunction(
    ({ id }) => document.querySelector('select[aria-label="选择临床研究项目"]')?.value === id,
    { id: project.project_id },
  );
  await page.getByText("医学写作", { exact: true }).first().click();
  await page.getByText("研究方案文档编辑与AI修订", { exact: true }).waitFor();
  await page.locator('.writing-title-actions button[title="打开研究方案目录"]').waitFor();
}

function sectionHeading(projectCode, sectionNumber) {
  const section = projectSessions[projectCode].sections.find(
    (item) => item.section_number === sectionNumber,
  );
  if (!section) throw new Error(`missing ${projectCode} section ${sectionNumber}`);
  return section.heading;
}

async function openSection(projectCode, sectionNumber) {
  const heading = sectionHeading(projectCode, sectionNumber);
  await page.locator('.writing-title-actions button[title="打开研究方案目录"]').click();
  const drawer = page.locator('[aria-label="研究方案目录"]');
  await drawer.waitFor();
  await drawer.locator('input[placeholder="搜索章节标题"]').fill(heading);
  await drawer.locator(`button[title=${JSON.stringify(heading)}]`).click();
  await drawer.waitFor({ state: "detached" });
  await page.getByText(`当前章节：${heading}`, { exact: true }).waitFor();
  await page.locator(".working-copy-status-bar").waitFor();
  await page.locator(".protocol-editor .ProseMirror [data-source-block-id]")
    .getByText(heading, { exact: true })
    .first()
    .waitFor();
  return heading;
}

async function applyRules(expectedPhrase) {
  const expectedText = page.locator(".protocol-editor .ProseMirror").getByText(expectedPhrase, { exact: false }).first();
  if (await expectedText.isVisible().catch(() => false)) return;
  const button = page.getByRole("button", { name: /应用规则到正文/ });
  await button.waitFor();
  await button.click();
  await page.locator(".working-copy-revision").filter({ hasText: /版本 [1-9]/ }).waitFor();
  await expectedText.waitFor();
}

async function assertNoApplyButton(projectCode, sectionNumber) {
  const count = await page.getByRole("button", { name: /应用规则到正文/ }).count();
  if (count !== 0) throw new Error(`${projectCode} ${sectionNumber} exposes an empty projection action`);
  observations.push({ projectCode, sectionNumber, emptyProjectionButtonHidden: true });
}

async function visualState(label) {
  const state = await page.evaluate(() => {
    const titleActions = document.querySelector(".writing-title-actions");
    const editorPanel = document.querySelector(".writing-editor-core");
    const rail = document.querySelector(".writing-ai-core");
    const rect = (element) => element ? element.getBoundingClientRect().toJSON() : null;
    return {
      viewport: { width: innerWidth, height: innerHeight },
      bodyTextLength: document.body.innerText.length,
      whiteScreen: document.body.innerText.trim().length < 100,
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      titleActions: rect(titleActions),
      editorPanel: rect(editorPanel),
      rail: rect(rail),
      titleActionsOverflow: Boolean(titleActions && (
        titleActions.scrollWidth > titleActions.clientWidth
        || titleActions.scrollHeight > titleActions.clientHeight + 2
      )),
      editorVisible: Boolean(editorPanel && rect(editorPanel).width > 600),
      railVisible: Boolean(rail && rect(rail).width > 240),
    };
  });
  if (state.whiteScreen || state.horizontalOverflow || state.titleActionsOverflow) {
    throw new Error(`${label} visual state failed: ${JSON.stringify(state)}`);
  }
  observations.push({ label, ...state });
  await page.screenshot({
    path: path.join(outputDir, `${label}.png`),
    fullPage: false,
  });
}

try {
  await page.goto(appUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.getByText("项目总看板", { exact: true }).first().waitFor();

  await selectProject("QC-RUX-IR");
  await openSection("QC-RUX-IR", "6.4");
  await applyRules("开放治疗期IGA为0分");
  await page.locator(".protocol-editor .ProseMirror").getByText("总BSA超过20%", { exact: false }).waitFor();
  await visualState("rux_6_4_projected_1920x1080");

  const manualMarker = "医学经理浏览器人工修订保护验证。";
  const projectionBlock = page.locator('.protocol-editor .ProseMirror [data-source-block-id^="mwgenerated_intervention_"]');
  await projectionBlock.waitFor();
  await projectionBlock.click();
  await page.keyboard.press("End");
  await page.keyboard.type(manualMarker);
  await page.getByText("有未保存修订", { exact: true }).waitFor();
  const saveButton = page.getByRole("button", { name: "保存工作副本" });
  const revisionBeforeSave = await page.locator(".working-copy-revision").textContent();
  await saveButton.click();
  await page.waitForFunction(
    ({ previous }) => document.querySelector(".working-copy-revision")?.textContent !== previous,
    { previous: revisionBeforeSave },
  );
  await page.getByRole("button", { name: /应用规则到正文/ }).click();
  await page.getByText("检测到人工修订", { exact: true }).waitFor();
  await visualState("rux_6_4_manual_edit_conflict_1920x1080");
  await page.getByRole("button", { name: "保留人工修订" }).click();
  await page.getByText("检测到人工修订", { exact: true }).waitFor({ state: "detached" });
  await page.locator(".protocol-editor .ProseMirror").getByText(manualMarker, { exact: false }).waitFor();
  await page.getByRole("button", { name: /应用规则到正文/ }).click();
  await page.getByText("检测到人工修订", { exact: true }).waitFor();
  await page.getByRole("button", { name: "确认覆盖" }).click();
  await page.getByText("检测到人工修订", { exact: true }).waitFor({ state: "detached" });
  if (await page.locator(".protocol-editor .ProseMirror").getByText(manualMarker, { exact: false }).count()) {
    throw new Error("explicit overwrite did not replace the medical edit");
  }

  await openSection("QC-RUX-IR", "6.9");
  await assertNoApplyButton("QC-RUX-IR", "6.9");
  await openSection("QC-RUX-IR", "6.10");
  await assertNoApplyButton("QC-RUX-IR", "6.10");

  await selectProject("QC-D001-IR");
  await openSection("QC-D001-IR", "6.9");
  await applyRules("系统性糖皮质激素");
  if (await page.locator(".protocol-editor .ProseMirror").getByText("方案允许的稳定剂量合并用药", { exact: false }).count()) {
    throw new Error("D001 6.9 leaked allowed CM content");
  }
  await openSection("QC-D001-IR", "6.10");
  await applyRules("方案允许的稳定剂量合并用药");
  if (await page.locator(".protocol-editor .ProseMirror").getByText("系统性糖皮质激素", { exact: false }).count()) {
    throw new Error("D001 6.10 leaked rescue-treatment content");
  }
  await visualState("d001_6_10_cm_boundary_1920x1080");

  await selectProject("QC-PNH-IR");
  await openSection("QC-PNH-IR", "6.4");
  await applyRules("没有计划调整剂量");
  for (const phrase of ["永久停药", "停药前递减", "停药后随访"]) {
    await page.locator(".protocol-editor .ProseMirror").getByText(phrase, { exact: false }).first().waitFor();
  }
  await visualState("pnh_6_4_no_planned_adjustment_1920x1080");
  await openSection("QC-PNH-IR", "6.9");
  await applyRules("替代治疗或支持治疗");
  await openSection("QC-PNH-IR", "6.10");
  await assertNoApplyButton("QC-PNH-IR", "6.10");

  const unexpectedErrors = errors.filter((message) => !(
    message.includes("Failed to load resource")
    && message.includes("409 (Conflict)")
    && expectedConflictResponses.length > 0
  ));
  const report = {
    appUrl,
    apiUrl,
    viewport: { width: 1920, height: 1080 },
    projectCodes: Object.keys(projects),
    observations,
    errors,
    unexpectedErrors,
    expectedConflictResponses,
    failedResponses,
    passed: unexpectedErrors.length === 0
      && failedResponses.length === 0
      && expectedConflictResponses.length >= 2,
  };
  await writeFile(
    path.join(outputDir, "browser_qc_report.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) throw new Error(`browser QC failed: ${JSON.stringify(report)}`);
} finally {
  await browser.close();
}
