import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5175/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "records/visual_qc_20260708/medical_writing_revision_blocked");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9397);

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 8000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await requestJson(url);
    } catch (error) {
      lastError = error;
      await wait(150);
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
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result || {});
  });

  return {
    ready: new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", reject, { once: true });
    }),
    send(method, params = {}) {
      const id = nextId;
      nextId += 1;
      ws.send(JSON.stringify({ id, method, params }));
      return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
    },
    close() {
      ws.close();
    },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.exception?.value || result.exceptionDetails.text;
    throw new Error(detail || "Runtime evaluation failed");
  }
  return result.result?.value;
}

async function waitForCondition(cdp, expression, timeoutMs = 30000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(250);
  }
  throw new Error(`Timed out waiting for condition. Last value: ${JSON.stringify(lastValue)}`);
}

async function clickButtonByText(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").includes(${JSON.stringify(label)}));
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button not found: ${label}`);
}

async function setValue(cdp, selector, value) {
  const changed = await evaluate(cdp, `
    (() => {
      const input = document.querySelector(${JSON.stringify(selector)});
      if (!input) return false;
      input.scrollIntoView({ block: "center", inline: "nearest" });
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value")?.set;
      if (setter) setter.call(input, ${JSON.stringify(value)});
      else input.value = ${JSON.stringify(value)};
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Input not found: ${selector}`);
}

async function captureMetrics(cdp) {
  return evaluate(cdp, `
    (() => {
      const text = document.body.textContent || "";
      const editorText = document.querySelector(".protocol-editor .ProseMirror")?.textContent || "";
      const editorRect = document.querySelector(".editor-panel")?.getBoundingClientRect();
      const aiRailRect = document.querySelector(".ai-rail")?.getBoundingClientRect();
      const sectionStripRect = document.querySelector(".writing-section-strip")?.getBoundingClientRect();
      const supportRect = document.querySelector(".writing-support-zone")?.getBoundingClientRect();
      const submitAiButtonRect = Array.from(document.querySelectorAll("button"))
        .find((button) => (button.textContent || "").includes("提交AI修订"))
        ?.getBoundingClientRect();
      const writingOuterHtml = document.querySelector(".writing-page")?.outerHTML || "";
      const sourceLeakPattern = /\\/Users\\/|file:\\/\\/|root_path|file_path|absolute_path|allowed_roots|content_hash|preview_hash|storage_key|server_path|source_record_id/i;
      const doc = document.documentElement;
      const body = document.body;
      return {
        hasWritingTitle: text.includes("医学写作") && text.includes("研究方案文档编辑与AI修订"),
        hasEditor: Boolean(document.querySelector(".protocol-editor .ProseMirror[contenteditable]")),
        hasAiRail: Boolean(document.querySelector(".ai-rail")),
        hasBlockedAiMessage: text.includes("AI修订提交失败：独立AI未配置"),
        hasNoCodexDependencyBoundary: !text.includes("Codex") && (text.includes("独立AI provider未配置") || text.includes("系统未调用独立AI服务")),
        editorInFirstViewport: Boolean(editorRect && editorRect.top < window.innerHeight * 0.55),
        aiRailInFirstViewport: Boolean(aiRailRect && aiRailRect.top < window.innerHeight * 0.55),
        submitAiButtonInFirstViewport: Boolean(submitAiButtonRect && submitAiButtonRect.top < window.innerHeight && submitAiButtonRect.bottom <= window.innerHeight),
        editorAndAiSameWorkRow: Boolean(editorRect && aiRailRect && Math.abs(editorRect.top - aiRailRect.top) <= 24 && editorRect.left < aiRailRect.left),
        editorWiderThanAi: Boolean(editorRect && aiRailRect && editorRect.width > aiRailRect.width * 1.25),
        sourceManifestBelowCore: Boolean(supportRect && editorRect && aiRailRect && supportRect.top >= Math.max(editorRect.bottom, aiRailRect.bottom) - 1),
        editorTextContainsBlockedMessage: editorText.includes("独立AI未配置") || editorText.includes("AI修订提交失败"),
        documentMapSecondaryRail: Boolean(
          sectionStripRect &&
          editorRect &&
          aiRailRect &&
          Math.abs(sectionStripRect.top - editorRect.top) <= 24 &&
          editorRect.left < aiRailRect.left &&
          aiRailRect.left < sectionStripRect.left
        ),
        documentMapSupportsEditor: Boolean(sectionStripRect && editorRect && sectionStripRect.width < editorRect.width * 0.55),
        revisionThreadRows: document.querySelectorAll(".revision-thread-list > button").length,
        hasLegacyEndpointThread: text.includes("endpoint_001") || text.includes("sug_endpoint_001"),
        hasForbiddenLifecycleText: /第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]|Stage\\s+[0-9]/.test(text),
        hasForbiddenOverclaim: /已医学批准|可正式提交监管|无需人工复核|自动定稿|最终医学结论/.test(text),
        leaksLocalPath: sourceLeakPattern.test(text),
        leaksSourceConfigInOuterHtml: sourceLeakPattern.test(writingOuterHtml),
        overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
      };
    })()
  `);
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "medical-writing-blocked-qc-"));
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
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Chrome page target found.");

    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`, 30000);
    await clickButtonByText(cdp, "医学写作");
    await waitForCondition(cdp, `
      document.body.textContent.includes("研究方案文档编辑与AI修订") &&
      Boolean(document.querySelector(".revision-form textarea")) &&
      Boolean(document.querySelector(".protocol-editor .ProseMirror[contenteditable]")) &&
      Array.from(document.querySelectorAll("button")).some((item) => (item.textContent || "").includes("提交AI修订") && !item.disabled)
    `, 45000);
    await setValue(cdp, ".revision-form textarea", "医学写作BLOCKED-QC：请基于当前方案正文改写主要终点表述。");
    await clickButtonByText(cdp, "提交AI修订");
    await waitForCondition(cdp, `document.body.textContent.includes("AI修订提交失败：独立AI未配置")`, 20000);
    await wait(500);

    const metrics = await captureMetrics(cdp);
    const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: true });
    const screenshotPath = path.join(outputDir, "medical_writing_revision_blocked_desktop.png");
    await writeFile(screenshotPath, Buffer.from(shot.data, "base64"));

    const failures = [];
    for (const key of [
      "hasWritingTitle",
      "hasEditor",
      "hasAiRail",
      "hasBlockedAiMessage",
      "hasNoCodexDependencyBoundary",
      "editorInFirstViewport",
      "aiRailInFirstViewport",
      "submitAiButtonInFirstViewport",
      "editorAndAiSameWorkRow",
      "editorWiderThanAi",
      "documentMapSecondaryRail",
      "documentMapSupportsEditor",
      "sourceManifestBelowCore",
    ]) {
      if (!metrics[key]) failures.push(key);
    }
    if (metrics.editorTextContainsBlockedMessage) failures.push("editorTextContainsBlockedMessage");
    if (metrics.revisionThreadRows !== 0) failures.push("revisionThreadRows");
    if (metrics.hasLegacyEndpointThread) failures.push("hasLegacyEndpointThread");
    if (metrics.hasForbiddenLifecycleText) failures.push("hasForbiddenLifecycleText");
    if (metrics.hasForbiddenOverclaim) failures.push("hasForbiddenOverclaim");
    if (metrics.leaksLocalPath) failures.push("leaksLocalPath");
    if (metrics.leaksSourceConfigInOuterHtml) failures.push("leaksSourceConfigInOuterHtml");
    if (metrics.overflowX) failures.push("overflowX");

    const report = { metrics, screenshotPath, failures };
    await writeFile(path.join(outputDir, "medical_writing_revision_blocked_qc.json"), JSON.stringify(report, null, 2), "utf8");
    if (failures.length) throw new Error(`Medical writing blocked QC failed: ${failures.join(", ")}`);
    cdp.close();
  } finally {
    chrome.kill("SIGTERM");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
