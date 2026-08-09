import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const playwrightPath = process.env.PLAYWRIGHT_PATH
  || "/Users/smkzw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
const chromePath = process.env.CHROME_PATH
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const expected = process.env.EXPECT_RUNTIME_STATE || "ready";
const outputDir = process.env.QC_OUTPUT_DIR
  || path.resolve("../records/active_slices/medical_writing_runtime_readiness_handshake_20260717/browser_qc");

if (!["ready", "blocked"].includes(expected)) {
  throw new Error(`unsupported EXPECT_RUNTIME_STATE: ${expected}`);
}

const { chromium } = await import(playwrightPath);
await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: chromePath });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
const consoleErrors = [];
const medicalWritingRequests = [];
const readinessResponses = [];

page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(`console: ${message.text()}`);
});
page.on("request", (request) => {
  const pathname = new URL(request.url()).pathname;
  if (pathname.startsWith("/api/") && pathname.includes("/medical-writing")) {
    medicalWritingRequests.push(`${request.method()} ${request.url()}`);
  }
});
page.on("response", (response) => {
  if (new URL(response.url()).pathname === "/api/runtime-readiness") {
    readinessResponses.push({ status: response.status(), url: response.url() });
  }
});

try {
  await page.goto(appUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.getByText("项目总看板", { exact: true }).first().waitFor();
  await page.getByText("医学写作", { exact: true }).first().click();

  let observation;
  if (expected === "blocked") {
    const gate = page.getByTestId("medical-writing-runtime-gate");
    await gate.waitFor();
    await gate.getByRole("heading", { name: "当前版本组合不可进入写作工作区" }).waitFor();
    observation = {
      gateVisible: true,
      gateText: (await gate.innerText()).trim(),
      writingWorkspaceVisible: await page.getByText("研究方案文档编辑与AI修订", { exact: true }).isVisible().catch(() => false),
    };
    if (medicalWritingRequests.length) {
      throw new Error(`blocked gate mounted medical-writing API calls: ${medicalWritingRequests.join(", ")}`);
    }
  } else {
    await page.getByText("研究方案文档编辑与AI修订", { exact: true }).waitFor({ timeout: 30000 });
    await page.locator(".working-copy-status-bar").waitFor({ timeout: 30000 });
    await page.waitForFunction(() => !document.body.innerText.includes("正在加载研究方案文档会话"));
    observation = {
      gateVisible: await page.getByTestId("medical-writing-runtime-gate").isVisible().catch(() => false),
      writingWorkspaceVisible: true,
      workspaceTitle: "研究方案文档编辑与AI修订",
      workingCopyStatusVisible: await page.locator(".working-copy-status-bar").isVisible(),
    };
  }

  await page.screenshot({
    path: path.join(outputDir, `runtime_${expected}_1920x1080.png`),
    fullPage: false,
  });
  const report = {
    expected,
    viewport: { width: 1920, height: 1080 },
    observation,
    readinessResponses,
    medicalWritingRequests,
    consoleErrors,
    passed: expected === "blocked"
      ? !consoleErrors.some((message) => message.startsWith("pageerror:"))
        && medicalWritingRequests.length === 0
        && observation.gateVisible
        && !observation.writingWorkspaceVisible
      : !consoleErrors.length
        && !observation.gateVisible
        && observation.writingWorkspaceVisible
        && observation.workingCopyStatusVisible,
  };
  await writeFile(
    path.join(outputDir, `runtime_${expected}.json`),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exitCode = 1;
} finally {
  await browser.close();
}
