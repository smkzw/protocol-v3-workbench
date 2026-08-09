import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const playwrightPath = process.env.PLAYWRIGHT_PATH
  || "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
const chromePath = process.env.CHROME_PATH
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(
  scriptDir,
  "../../records/active_slices/medical_writing_front_matter_synopsis_objects_20260717/browser_qc",
);
const cases = [
  { projectId: "proj_d001", projectCode: "CMS-D001", synopsisHeading: "概要" },
  { projectId: "proj_my008_pnh_3_01", projectCode: "MY008211A-PNH-3-01", synopsisHeading: "方案摘要" },
  { projectId: "proj_rux_03_002", projectCode: "RUX-03-002", synopsisHeading: "概要" },
];

const { chromium } = await import(playwrightPath);
await mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true, executablePath: chromePath });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
const consoleErrors = [];
const failedResponses = [];
const nonGetRequests = [];
const observations = [];

page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(`console: ${message.text()}`);
});
page.on("response", (response) => {
  if (response.status() >= 400) failedResponses.push(`${response.status()} ${response.url()}`);
});
page.on("request", (request) => {
  if (request.method() !== "GET") nonGetRequests.push(`${request.method()} ${request.url()}`);
});

async function selectProject(projectId) {
  const selector = page.locator('select[aria-label="选择临床研究项目"]');
  await selector.waitFor({ state: "visible" });
  await selector.selectOption(projectId);
  await page.waitForFunction(
    (id) => document.querySelector('select[aria-label="选择临床研究项目"]')?.value === id,
    projectId,
  );
  await page.getByText("医学写作", { exact: true }).first().click();
  await page.getByText("研究方案文档编辑与AI修订", { exact: true }).waitFor();
  await page.locator(".working-copy-status-bar").waitFor();
}

async function openSection(heading) {
  await page.locator('.writing-title-actions button[title="打开研究方案目录"]').click();
  const drawer = page.locator('[aria-label="研究方案目录"]');
  await drawer.waitFor();
  await drawer.locator('input[placeholder="搜索章节标题"]').fill(heading);
  await drawer.locator(`button[title=${JSON.stringify(heading)}]`).first().click();
  await drawer.waitFor({ state: "detached" });
  await page.locator(".rich-editor-meta strong").filter({ hasText: heading }).waitFor();
}

async function visualState(label, expectedRole) {
  const state = await page.evaluate((role) => {
    const designer = document.querySelector(`.structured-table-designer.document-object.${role}`);
    const rect = designer?.getBoundingClientRect();
    const roleLabel = designer?.querySelector(".std-domain-label")?.textContent?.trim() || "";
    const overflowElements = Array.from(designer?.querySelectorAll("*") || [])
      .filter((node) => node.scrollWidth > node.clientWidth + 2 && getComputedStyle(node).overflowX === "visible")
      .slice(0, 10)
      .map((node) => ({
        className: String(node.className || ""),
        text: String(node.textContent || "").trim().slice(0, 80),
        scrollWidth: node.scrollWidth,
        clientWidth: node.clientWidth,
      }));
    return {
      role,
      roleLabel,
      designerVisible: Boolean(rect && rect.width > 1100 && rect.height > 700),
      pageHorizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1,
      domainSelectorPresent: Boolean(designer?.querySelector('select[aria-label="结构化表格类型"]')),
      genericDomainLabelPresent: roleLabel === "通用结构化表格",
      overflowElements,
      whiteScreen: document.body.innerText.trim().length < 200,
    };
  }, expectedRole);
  observations.push({ label, ...state });
  await page.screenshot({ path: path.join(outputDir, `${label}.png`), fullPage: false });
  if (
    !state.designerVisible
    || state.pageHorizontalOverflow
    || state.domainSelectorPresent
    || state.genericDomainLabelPresent
    || state.whiteScreen
    || state.overflowElements.length
  ) {
    throw new Error(`${label} visual contract failed: ${JSON.stringify(state)}`);
  }
}

async function openFrontMatter(projectCode) {
  const button = page.getByRole("button", { name: "方案首页", exact: true });
  await button.waitFor();
  await page.waitForFunction(() => {
    const target = Array.from(document.querySelectorAll("button"))
      .find((item) => item.textContent?.trim().endsWith("方案首页"));
    return Boolean(target && !target.disabled);
  });
  await button.click();
  const picker = page.locator('[aria-label="选择要打开的方案首页排版对象"]');
  await page.waitForFunction(() => Boolean(
    document.querySelector('[aria-label="选择要打开的方案首页排版对象"]')
    || document.querySelector(".structured-table-designer.document-object.layout")
  ));
  const pickerVisible = await picker.isVisible().catch(() => false);
  let candidateCount = 1;
  if (pickerVisible) {
    candidateCount = await picker.locator("[data-document-object-block-id]").count();
    if (candidateCount < 2) throw new Error(`${projectCode} front matter picker has fewer than two choices`);
    await picker.locator("[data-document-object-block-id]").first().click();
  }
  await page.locator(".structured-table-designer.document-object.layout").waitFor();
  await visualState(`${projectCode}_front_matter_1920x1080`, "layout");
  await page.getByRole("button", { name: "关闭表格设计器" }).click();
  await page.locator(".structured-table-designer").waitFor({ state: "detached" });
  return candidateCount;
}

async function openSynopsis(projectCode, heading) {
  await openSection(heading);
  const button = page.getByRole("button", { name: "方案摘要", exact: true });
  await button.waitFor();
  await page.waitForFunction(() => {
    const target = Array.from(document.querySelectorAll("button"))
      .find((item) => item.textContent?.trim().endsWith("方案摘要"));
    return Boolean(target && !target.disabled);
  });
  await button.click();
  await page.locator(".structured-table-designer.document-object.protocol_synopsis").waitFor();
  await visualState(`${projectCode}_synopsis_1920x1080`, "protocol_synopsis");
  const synopsisText = await page.locator(".std-grid-table").innerText();
  if (synopsisText.trim().length < 80) throw new Error(`${projectCode} synopsis density is too low`);
  await page.getByRole("button", { name: "关闭表格设计器" }).click();
  await page.locator(".structured-table-designer").waitFor({ state: "detached" });
  return synopsisText.trim().length;
}

try {
  await page.goto(appUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.getByText("项目总看板", { exact: true }).first().waitFor();
  for (const item of cases) {
    await selectProject(item.projectId);
    const frontMatterCandidateCount = await openFrontMatter(item.projectCode);
    const synopsisTextLength = await openSynopsis(item.projectCode, item.synopsisHeading);
    observations.push({
      projectId: item.projectId,
      projectCode: item.projectCode,
      frontMatterCandidateCount,
      synopsisTextLength,
    });
  }
  const report = {
    viewport: { width: 1920, height: 1080 },
    observations,
    consoleErrors,
    failedResponses,
    nonGetRequests,
    passed: !consoleErrors.length && !failedResponses.length && !nonGetRequests.length,
  };
  await writeFile(
    path.join(outputDir, "medical_writing_document_objects_stable_qc.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exitCode = 1;
} finally {
  await browser.close();
}
