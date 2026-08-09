import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/visual_qc_20260707");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9366);
const scriptDir = path.dirname(new URL(import.meta.url).pathname);
const workspaceRoot = path.resolve(scriptDir, "../..");
const reviewStorePath = path.join(workspaceRoot, "runtime", "tfl_review_actions.jsonl");
let reviewStoreBackup = null;
let reviewStoreExisted = false;

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

async function waitForCondition(cdp, expression, timeoutMs = 20000) {
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
      const button = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)});
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button not found: ${label}`);
}

async function clickButtonContaining(cdp, labelPart) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").includes(${JSON.stringify(labelPart)}));
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button not found containing: ${labelPart}`);
}

async function setReviewComment(cdp, value) {
  const updated = await evaluate(cdp, `
    (() => {
      const textarea = document.querySelector(".tfl-review-comment textarea");
      if (!textarea) return false;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      textarea.focus();
      setter.call(textarea, ${JSON.stringify(value)});
      if (textarea._valueTracker) textarea._valueTracker.setValue("");
      textarea.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: ${JSON.stringify(value)} }));
      textarea.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!updated) throw new Error("TFL review comment textarea not found.");
  await waitForCondition(cdp, `
    (() => {
      const textarea = document.querySelector(".tfl-review-comment textarea");
      return Boolean(textarea && textarea.value.includes(${JSON.stringify(value.slice(0, 12))}));
    })()
  `, 8000);
}

async function waitForButtonEnabled(cdp, label, timeoutMs = 8000) {
  const started = Date.now();
  let detail = null;
  while (Date.now() - started < timeoutMs) {
    detail = await evaluate(cdp, `
      (() => {
        const button = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)});
        const textarea = document.querySelector(".tfl-review-comment textarea");
        const focusCards = Array.from(document.querySelectorAll(".tfl-review-focus strong")).map((item) => item.textContent || "");
        return {
          found: Boolean(button),
          disabled: button ? button.disabled : null,
          textareaLength: textarea ? textarea.value.length : null,
          focusCards,
          message: Array.from(document.querySelectorAll(".source-registry-message")).map((item) => item.textContent || "").join(" | "),
        };
      })()
    `);
    if (detail?.found && !detail.disabled) return;
    await wait(250);
  }
  throw new Error(`Button not enabled: ${label}; detail=${JSON.stringify(detail)}`);
}

async function backupAndClearReviewStore() {
  try {
    reviewStoreBackup = await readFile(reviewStorePath, "utf8");
    reviewStoreExisted = true;
  } catch {
    reviewStoreBackup = null;
    reviewStoreExisted = false;
  }
  await rm(reviewStorePath, { force: true });
}

async function restoreReviewStore() {
  if (reviewStoreExisted) {
    await writeFile(reviewStorePath, reviewStoreBackup || "", "utf8");
  } else {
    await rm(reviewStorePath, { force: true });
  }
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  await backupAndClearReviewStore();
  const userDataDir = await mkdtemp(path.join(tmpdir(), "tfl-manifest-qc-"));
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
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);
    await clickButtonByText(cdp, "数据分析与TFL");
    await waitForCondition(cdp, `
      document.body.textContent.includes("RUX-03-002") &&
      document.body.textContent.includes("表57") &&
      document.body.textContent.includes("ADSL") &&
      document.body.textContent.includes("数据集清单") &&
      document.body.textContent.includes("TFL审阅工作台")
    `, 90000);
    await clickButtonContaining(cdp, "MY008211A-PNH-3-01");
    await waitForCondition(cdp, `
      document.body.textContent.includes("MY008211A-PNH-3-01") &&
      document.body.textContent.includes("候选TFL输出") &&
      document.body.textContent.includes("标记医学已审阅") &&
      document.body.textContent.includes("当前审阅状态") &&
      !Array.from(document.querySelectorAll(".tfl-review-focus strong")).some((item) => (item.textContent || "").includes("未选择")) &&
      !Array.from(document.querySelectorAll("button")).some((button) => (button.textContent || "").trim() === "读取中")
    `, 30000);
    await setReviewComment(cdp, "浏览器QC：医学已核对TFL对象、配对数据集和非正式输出边界。");
    await waitForButtonEnabled(cdp, "标记医学已审阅");
    await clickButtonByText(cdp, "标记医学已审阅");
    await waitForCondition(cdp, `document.body.textContent.includes("已更新审阅状态：医学已审阅")`, 30000);
    await setReviewComment(cdp, "浏览器QC：允许进入医学写作引用候选，正式引用前仍需统计复核。");
    await waitForButtonEnabled(cdp, "标记写作引用候选");
    await clickButtonByText(cdp, "标记写作引用候选");
    await waitForCondition(cdp, `document.body.textContent.includes("已更新审阅状态：写作引用候选")`, 30000);

    const desktopMetrics = await evaluate(cdp, `
      (() => {
        const text = document.body.textContent || "";
        const doc = document.documentElement;
        const body = document.body;
        return {
          hasTitle: text.includes("数据分析与TFL"),
          hasManifest: text.includes("数据集清单与TFL交付清单"),
          hasPackageCounts: (text.includes("表57") && text.includes("Listing31") && text.includes("图3")) ||
            (text.includes("表85") && text.includes("Listing56") && text.includes("图23")),
          hasMy008Tab: text.includes("MY008211A-PNH-3-01"),
          hasReviewWorkbench: text.includes("TFL审阅工作台") && text.includes("当前审阅状态"),
          hasReviewActions: text.includes("标记医学已审阅") && text.includes("发起统计复核") && text.includes("标记写作引用候选"),
          completedReviewChain: text.includes("写作引用候选") && text.includes("浏览器QC：允许进入医学写作引用候选"),
          hasFormalBoundary: text.includes("不生成正式监管TFL") && text.includes("待医学确认"),
          hasNoFormalGenerationButton: !Array.from(document.querySelectorAll("button")).some((button) => /生成正式TFL/.test(button.textContent || "")),
          hasForbiddenLifecycleText: /第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]|Stage\\s+[0-9]/.test(text),
          leaksLocalPath: text.includes("/Users/"),
          overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
          datasetRows: document.querySelectorAll(".tfl-table-block:first-of-type tbody tr").length,
          outputRows: document.querySelectorAll(".tfl-table-block:last-of-type tbody tr").length,
          reviewAuditRows: document.querySelectorAll(".tfl-review-audit > div").length,
        };
      })()
    `);
    const desktopShot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: true });
    const desktopPath = path.join(outputDir, "tfl_manifest_desktop.png");
    await writeFile(desktopPath, Buffer.from(desktopShot.data, "base64"));

    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 390,
      height: 1100,
      deviceScaleFactor: 2,
      mobile: true,
    });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);
    await clickButtonByText(cdp, "数据分析与TFL");
    await waitForCondition(cdp, `document.body.textContent.includes("数据集清单与TFL交付清单") && document.body.textContent.includes("TFL审阅工作台")`, 30000);
    const mobileMetrics = await evaluate(cdp, `
      (() => {
        const doc = document.documentElement;
        const body = document.body;
        return {
          overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
          tableInternalScroll: Array.from(document.querySelectorAll(".tfl-table-scroll")).every((item) => item.scrollWidth >= item.clientWidth),
          hasReviewWorkbench: (document.body.textContent || "").includes("TFL审阅工作台"),
          leaksLocalPath: (document.body.textContent || "").includes("/Users/"),
        };
      })()
    `);
    const mobileShot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: true });
    const mobilePath = path.join(outputDir, "tfl_manifest_mobile.png");
    await writeFile(mobilePath, Buffer.from(mobileShot.data, "base64"));

    cdp.close();
    const metrics = { appUrl, desktopPath, mobilePath, desktopMetrics, mobileMetrics };
    const metricsPath = path.join(outputDir, "tfl_manifest_qc.json");
    await writeFile(metricsPath, `${JSON.stringify(metrics, null, 2)}\n`, "utf8");
    console.log(metricsPath);

    const failed = !desktopMetrics.hasTitle ||
      !desktopMetrics.hasManifest ||
      !desktopMetrics.hasPackageCounts ||
      !desktopMetrics.hasMy008Tab ||
      !desktopMetrics.hasReviewWorkbench ||
      !desktopMetrics.hasReviewActions ||
      !desktopMetrics.completedReviewChain ||
      !desktopMetrics.hasFormalBoundary ||
      !desktopMetrics.hasNoFormalGenerationButton ||
      desktopMetrics.hasForbiddenLifecycleText ||
      desktopMetrics.leaksLocalPath ||
      desktopMetrics.overflowX ||
      desktopMetrics.datasetRows < 1 ||
      desktopMetrics.outputRows < 1 ||
      desktopMetrics.reviewAuditRows < 2 ||
      mobileMetrics.overflowX ||
      !mobileMetrics.hasReviewWorkbench ||
      mobileMetrics.leaksLocalPath;
    if (failed) throw new Error(`TFL manifest QC failed: ${JSON.stringify(metrics)}`);
  } finally {
    chrome.kill("SIGTERM");
    await restoreReviewStore();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
