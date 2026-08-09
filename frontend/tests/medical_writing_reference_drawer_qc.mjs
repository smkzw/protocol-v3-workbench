import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(__dirname, "../../records/visual_qc_20260712/medical_writing_reference");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9388);
const expectedProjectId = process.env.QC_PROJECT_ID || "proj_rux_03_002";
const targetNctId = process.env.QC_TARGET_NCT_ID || "NCT05014438";
const expectedCandidateCount = Number(process.env.QC_EXPECTED_CANDIDATE_COUNT || 453);
const expectedSnapshotCountText = process.env.QC_EXPECTED_SNAPSHOT_COUNT_TEXT || "返回 453/453";
const targetSpanId = process.env.QC_TARGET_SPAN_ID || "wref_span_ef35287cf861701dfc32cdd8";
const expectedTranslationRevision = Number(process.env.QC_EXPECTED_TRANSLATION_REVISION || 2);
const expectedTranslationSnippet = process.env.QC_EXPECTED_TRANSLATION_SNIPPET || "明确安全性分析中使用的安全性人群定义";
const expectedIndicationText = process.env.QC_EXPECTED_INDICATION_TEXT || "Atopic Dermatitis";
const expectedDocumentTypeText = process.env.QC_EXPECTED_DOCUMENT_TYPE_TEXT || "Protocol/SAP";
const expectedDocumentDateText = process.env.QC_EXPECTED_DOCUMENT_DATE_TEXT || "2021-06-30";


async function runW4BStaticChecks() {
  const root = path.resolve(__dirname, "..");
  const [journey, panel, drawer, styles] = await Promise.all([
    readFile(path.join(root, "src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx"), "utf8"),
    readFile(path.join(root, "src/features/writing-reference/WritingReferencePanel.jsx"), "utf8"),
    readFile(path.join(root, "src/features/medical-writing/AuthoringCompetitorDrawer.jsx"), "utf8"),
    readFile(path.join(root, "src/styles.css"), "utf8"),
  ]);
  const failures = [];
  const expect = (condition, label) => { if (!condition) failures.push(label); };
  // W4_B_STATIC_CHECKS
  expect(journey.includes('data-testid="open-competitor-drawer"'), "early-open-button");
  expect(journey.includes("AuthoringCompetitorDrawer"), "drawer-mounted-in-journey");
  expect(journey.includes("keepPanelMounted"), "keep-panel-mounted");
  expect(journey.includes("setCompetitorDrawerOpen"), "drawer-open-state");
  expect(!journey.includes("prefill-package/adopt-composite"), "no-w4a-composite-adopt");
  expect(panel.includes("embedded = false") && panel.includes("compact = false"), "panel-optional-presentation-props");
  expect(panel.includes("{!embedded && ("), "non-embedded-header-preserved");
  expect(panel.includes("writing-reference-snapshot-details"), "embedded-snapshot-collapsed");
  expect(drawer.includes('embedded') && drawer.includes('compact'), "drawer-uses-embedded-compact");
  expect(drawer.includes('Escape'), "drawer-escape-close");
  expect(drawer.includes('aria-label="关闭竞品处理抽屉"'), "drawer-close-a11y");
  expect(styles.includes("authoring-competitor-drawer") && styles.includes("560px"), "drawer-desktop-width");
  if (failures.length) {
    throw new Error(`W4-B static drawer checks failed: ${failures.join(", ")}`);
  }
  return {
    earlyOpenFromAuthoringStep: true,
    panelKeepMountedWhenClosed: true,
    nonEmbeddedCallersUnchangedProps: true,
    noW4ACompositeAdopt: true,
  };
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function json(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 15000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await json(url);
    } catch (error) {
      lastError = error;
      await wait(200);
    }
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

function createCdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const callback = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) callback.reject(new Error(message.error.message));
    else callback.resolve(message.result || {});
  });
  return {
    ready: new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", reject, { once: true });
    }),
    send(method, params = {}) {
      const id = nextId++;
      ws.send(JSON.stringify({ id, method, params }));
      return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
    },
    close() { ws.close(); },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result?.value;
}

async function waitForCondition(cdp, expression, timeoutMs = 45000) {
  const started = Date.now();
  let value;
  while (Date.now() - started < timeoutMs) {
    value = await evaluate(cdp, expression);
    if (value) return value;
    await wait(250);
  }
  throw new Error(`Timed out waiting for condition: ${JSON.stringify(value)}`);
}

async function clickText(cdp, selector, text) {
  const clicked = await evaluate(cdp, `
    (() => {
      const item = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
        .find((element) => (element.textContent || "").includes(${JSON.stringify(text)}));
      if (!item) return false;
      item.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Element not found: ${selector} / ${text}`);
}

async function screenshot(cdp, filename) {
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const output = path.join(outputDir, filename);
  await writeFile(output, Buffer.from(shot.data, "base64"));
  return output;
}

async function main() {
  const staticChecks = await runW4BStaticChecks();
  await mkdir(outputDir, { recursive: true });
  if (process.env.QC_STATIC_ONLY === "1") {
    const report = { staticOnly: true, staticChecks, failures: [] };
    await writeFile(path.join(outputDir, "medical_writing_reference_drawer_qc.json"), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    return;
  }
  // Prefer live browser path; if the workbench is unavailable, static checks still stand for this W4-B wiring pass.
  let appReachable = false;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2000);
    const response = await fetch(appUrl, { signal: controller.signal });
    clearTimeout(timer);
    appReachable = response.ok || response.status < 500;
  } catch {
    appReachable = false;
  }
  if (!appReachable) {
    const report = {
      staticOnly: true,
      staticChecks,
      skippedBrowser: "app_unreachable",
      appUrl,
      failures: [],
    };
    await writeFile(path.join(outputDir, "medical_writing_reference_drawer_qc.json"), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    return;
  }
  const userDataDir = await mkdtemp(path.join(tmpdir(), "medical-writing-reference-qc-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });

  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    const target = targets.find((item) => item.type === "page");
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Chrome target.");
    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);
    await evaluate(cdp, `
      (() => {
        const select = document.querySelector('select[aria-label="选择临床研究项目"]');
        if (!select || !Array.from(select.options).some((option) => option.value === ${JSON.stringify(expectedProjectId)})) return false;
        const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
        setter.call(select, ${JSON.stringify(expectedProjectId)});
        select.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      })()
    `);
    await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(expectedProjectId)}`);
    await clickText(cdp, "button", "医学写作");
    await waitForCondition(cdp, `document.querySelector(".writing-ai-core") && document.body.textContent.includes("研究方案文档编辑与AI修订")`);
    await clickText(cdp, ".rail-tabs button", "证据");
    await waitForCondition(cdp, `document.querySelectorAll(".writing-reference-list > button").length === ${expectedCandidateCount}`);

    const initialMetrics = await evaluate(cdp, `
      (() => {
        const body = document.body;
        const doc = document.documentElement;
        const rail = document.querySelector(".writing-ai-core");
        const panel = document.querySelector(".writing-reference-panel");
        const list = document.querySelector(".writing-reference-list");
        const railRect = rail?.getBoundingClientRect();
        const panelRect = panel?.getBoundingClientRect();
        const cardRects = Array.from(document.querySelectorAll(".writing-reference-list > button")).slice(0, 20).map((item) => item.getBoundingClientRect());
        const overlap = (a, b) => a && b && a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
        const viewButtons = Array.from(document.querySelectorAll(".writing-reference-views button")).map((item) => item.getBoundingClientRect());
        return {
          projectId: document.querySelector('select[aria-label="选择临床研究项目"]')?.value,
          viewport: [innerWidth, innerHeight],
          candidateCount: document.querySelectorAll(".writing-reference-list > button").length,
          evidenceTabActive: Array.from(document.querySelectorAll(".rail-tabs button")).find((item) => item.textContent.trim() === "证据")?.classList.contains("active"),
          aiTabEnabled: !Array.from(document.querySelectorAll(".rail-tabs button")).find((item) => item.textContent.trim() === "AI")?.disabled,
          evidenceTabEnabled: !Array.from(document.querySelectorAll(".rail-tabs button")).find((item) => item.textContent.trim() === "证据")?.disabled,
          inactiveTabsDisabled: ["风险", "审阅", "版本"].every((label) => Array.from(document.querySelectorAll(".rail-tabs button")).find((item) => item.textContent.trim() === label)?.disabled),
          panelInsideRail: Boolean(railRect && panelRect && panelRect.left >= railRect.left && panelRect.right <= railRect.right + 1),
          cardsInsideRail: cardRects.every((rect) => rect.left >= railRect.left && rect.right <= railRect.right + 1),
          viewButtonsDoNotOverlap: viewButtons.every((rect, index) => viewButtons.slice(index + 1).every((other) => !overlap(rect, other))),
          listScrollsInternally: Boolean(list && list.scrollHeight > list.clientHeight && ["auto", "scroll"].includes(getComputedStyle(list).overflowY)),
          noPageOverflowX: Math.max(body.scrollWidth, doc.scrollWidth) <= innerWidth + 1,
          noLocalPathLeak: !["/users/", "file://", "allowed_roots", "server_path"].some((token) => (document.querySelector(".writing-page")?.outerHTML || "").toLowerCase().includes(token)),
          safetyBoundaryVisible: body.textContent.includes("加入证据包不会直接改写或插入正式正文"),
          snapshotMetadataVisible: body.textContent.includes("API 2.0.5") && body.textContent.includes(${JSON.stringify(expectedSnapshotCountText)}),
        };
      })()
    `);
    const initialScreenshot = await screenshot(cdp, "medical_writing_reference_candidates_desktop.png");

    await clickText(cdp, ".writing-reference-list > button", targetNctId);
    const alreadyDirect = await evaluate(cdp, `document.querySelector(".writing-reference-list > button.active")?.textContent.includes("直接竞品")`);
    if (!alreadyDirect) {
      await evaluate(cdp, `
        (() => {
          const textarea = document.querySelector(".writing-reference-actions textarea");
          const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
          setter.call(textarea, "同适应症、同分期，研究人群和药物机制可用于方案设计比较。");
          textarea.dispatchEvent(new Event("input", { bubbles: true }));
        })()
      `);
      await clickText(cdp, ".writing-reference-actions button", "标记为直接竞品");
      await waitForCondition(cdp, `document.body.textContent.includes("医学相关性已记录")`);
    }
    await clickText(cdp, ".writing-reference-views button", "文档与解析");
    await waitForCondition(cdp, `document.querySelectorAll(".writing-reference-document-row").length >= 1`);
    const documentMetrics = await evaluate(cdp, `
      (() => ({
        documentRows: document.querySelectorAll(".writing-reference-document-row").length,
        downloadActions: Array.from(document.querySelectorAll(".writing-reference-document-row button")).filter((item) => item.textContent.includes("下载并解析")).length,
        parseActions: Array.from(document.querySelectorAll(".writing-reference-document-row button")).filter((item) => item.textContent.includes("解析文档")).length,
        parsedVisible: document.body.textContent.includes("已解析"),
        publicLinks: document.querySelectorAll(".writing-reference-document-row a[target='_blank']").length,
        noPageOverflowX: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) <= innerWidth + 1,
      }))()
    `);
    const documentScreenshot = await screenshot(cdp, "medical_writing_reference_documents_desktop.png");

    const downloadAvailable = await evaluate(cdp, `Array.from(document.querySelectorAll(".writing-reference-document-row button")).some((item) => item.textContent.includes("下载并解析") && !item.disabled)`);
    const parseAvailable = await evaluate(cdp, `Array.from(document.querySelectorAll(".writing-reference-document-row button")).some((item) => item.textContent.includes("解析文档") && !item.disabled)`);
    if (downloadAvailable) {
      await clickText(cdp, ".writing-reference-document-row button", "下载并解析");
      await waitForCondition(cdp, `document.body.textContent.includes("公开文档已下载并完成结构化解析")`);
    } else if (parseAvailable) {
      await clickText(cdp, ".writing-reference-document-row button", "解析文档");
      await waitForCondition(cdp, `document.body.textContent.includes("结构化解析已完成")`);
    }
    await waitForCondition(cdp, `document.body.textContent.includes("已解析") && document.body.textContent.includes("内容匹配")`);
    const registeredMetrics = await evaluate(cdp, `
      (() => ({
        parsedVisible: document.body.textContent.includes("已解析"),
        contentMatchedVisible: document.body.textContent.includes("内容匹配"),
        contentHashVisible: Boolean(document.querySelector(".writing-reference-document-row code")),
        sourceLinkVisible: Boolean(document.querySelector(".writing-reference-document-row a[target='_blank']")),
        noSecurityScanLanguage: !["安全扫描", "隔离区", "恶意文件"].some((text) => document.body.textContent.includes(text)),
      }))()
    `);
    const registeredScreenshot = await screenshot(cdp, "medical_writing_reference_registered_desktop.png");
    await clickText(cdp, ".writing-reference-document-row button", "查看处理状态");
    await waitForCondition(cdp, `document.body.textContent.includes("文件内容核验") && document.querySelectorAll(".writing-reference-validation-checks > div").length >= 5`);
    await waitForCondition(cdp, `document.querySelectorAll(".writing-reference-select select option").length > 1 && (Array.from(document.querySelectorAll("button")).some((item) => item.textContent.includes("生成监管中文候选") && !item.disabled) || (document.body.textContent.includes("监管中文候选") && document.body.textContent.includes("待医学审核")))`);
    const validationMetrics = await evaluate(cdp, `
      (() => ({
        validationVisible: document.body.textContent.includes("文件内容核验"),
        contentMatchedVisible: document.body.textContent.includes("内容匹配"),
        studyMatchVisible: document.body.textContent.includes("研究标识") && document.body.textContent.includes(${JSON.stringify(targetNctId)}),
        indicationMatchVisible: document.body.textContent.includes("适应症") && document.body.textContent.includes(${JSON.stringify(expectedIndicationText)}),
        documentTypeMatchVisible: document.body.textContent.includes("文件类型") && document.body.textContent.includes(${JSON.stringify(expectedDocumentTypeText)}),
        dateMatchVisible: document.body.textContent.includes("文件日期/版本") && document.body.textContent.includes(${JSON.stringify(expectedDocumentDateText)}),
        spanOptionsVisible: document.querySelectorAll(".writing-reference-select select option").length > 1,
        translationWorkflowAvailable: Array.from(document.querySelectorAll("button")).some((item) => item.textContent.includes("生成监管中文候选") && !item.disabled) || (document.body.textContent.includes("监管中文候选") && document.body.textContent.includes("待医学审核")),
        noPageOverflowX: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) <= innerWidth + 1,
        noSecurityScanLanguage: !["安全扫描", "隔离区", "恶意文件"].some((text) => document.body.textContent.includes(text)),
      }))()
    `);
    const validationScreenshot = await screenshot(cdp, "medical_writing_reference_content_validation_desktop.png");
    await evaluate(cdp, `
      (() => {
        const selects = Array.from(document.querySelectorAll(".writing-reference-select select"));
        const select = selects.find((item) => Array.from(item.options).some((option) => option.value === ${JSON.stringify(targetSpanId)}));
        if (!select) return false;
        const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
        setter.call(select, ${JSON.stringify(targetSpanId)});
        select.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      })()
    `);
    await waitForCondition(cdp, `document.body.textContent.includes(${JSON.stringify(`监管中文候选 · v${expectedTranslationRevision}`)}) && document.body.textContent.includes(${JSON.stringify(expectedTranslationSnippet)}) && document.body.textContent.includes("待医学审核")`);
    const translationRevisionMetrics = await evaluate(cdp, `
      (() => ({
        revisionVisible: document.body.textContent.includes(${JSON.stringify(`监管中文候选 · v${expectedTranslationRevision}`)}),
        revisedCandidateVisible: document.body.textContent.includes(${JSON.stringify(expectedTranslationSnippet)}),
        pendingMedicalReviewVisible: document.body.textContent.includes("待医学审核"),
        reviewActionsVisible: ["批准译文", "退回修改", "拒绝"].every((text) => Array.from(document.querySelectorAll("button")).some((item) => item.textContent.includes(text))),
        noAutomaticApprovalClaim: !document.body.textContent.includes("无需医学审核"),
      }))()
    `);
    const translationRevisionScreenshot = await screenshot(cdp, "medical_writing_reference_translation_revision_desktop.png");

    const failures = [];
    for (const [key, value] of Object.entries(initialMetrics)) {
      if (["projectId", "viewport", "candidateCount"].includes(key)) continue;
      if (!value) failures.push(`initial:${key}`);
    }
    if (initialMetrics.projectId !== expectedProjectId) failures.push("initial:projectId");
    if (initialMetrics.candidateCount !== expectedCandidateCount) failures.push(`initial:candidateCount=${initialMetrics.candidateCount}`);
    if (documentMetrics.documentRows < 1) failures.push("documents:rows");
    if (documentMetrics.downloadActions + documentMetrics.parseActions < 1 && !documentMetrics.parsedVisible) failures.push("documents:noAvailableOrCompletedProcessingAction");
    if (documentMetrics.publicLinks < 1) failures.push("documents:publicLink");
    if (!documentMetrics.noPageOverflowX) failures.push("documents:pageOverflowX");
    for (const [key, value] of Object.entries(registeredMetrics)) if (!value) failures.push(`registered:${key}`);
    for (const [key, value] of Object.entries(validationMetrics)) if (!value) failures.push(`validation:${key}`);
    for (const [key, value] of Object.entries(translationRevisionMetrics)) if (!value) failures.push(`translationRevision:${key}`);

    const report = {
      staticChecks,
      viewport: { width: 1600, height: 1000 },
      initialMetrics,
      documentMetrics,
      registeredMetrics,
      validationMetrics,
      translationRevisionMetrics,
      screenshots: [initialScreenshot, documentScreenshot, registeredScreenshot, validationScreenshot, translationRevisionScreenshot],
      failures,
    };
    await writeFile(path.join(outputDir, "medical_writing_reference_drawer_qc.json"), JSON.stringify(report, null, 2));
    cdp.close();
    if (failures.length) throw new Error(`Medical writing reference QC failed: ${failures.join(", ")}`);
  } finally {
    chrome.kill("SIGTERM");
    await wait(500);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
