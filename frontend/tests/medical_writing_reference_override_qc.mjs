import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const outputDir = process.env.QC_OUTPUT_DIR || "records/visual_qc_20260712/medical_writing_reference_override";
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9390);
const projectId = process.env.QC_PROJECT_ID || "proj_rux_03_002";
const overrideReason = "医学经理已逐项核对原文、研究登记和文件首页，确认该文件可用于当前研究方案参照。";
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForJson(url) {
  for (let index = 0; index < 80; index += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return response.json();
    } catch {}
    await wait(200);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function cdpClient(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const handler = pending.get(message.id);
    if (!handler) return;
    pending.delete(message.id);
    if (message.error) handler.reject(new Error(message.error.message));
    else handler.resolve(message.result || {});
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
    close: () => ws.close(),
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result?.value;
}

async function waitFor(cdp, expression, timeoutMs = 30000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const value = await evaluate(cdp, expression);
    if (value) return value;
    await wait(250);
  }
  throw new Error(`Timed out: ${expression}`);
}

async function clickText(cdp, selector, label) {
  const clicked = await evaluate(cdp, `(() => {
    const element = Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find((item) => (item.textContent || "").includes(${JSON.stringify(label)}));
    if (!element) return false;
    element.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Missing control: ${label}`);
}

async function screenshot(cdp, name) {
  const result = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const target = path.resolve(outputDir, name);
  await writeFile(target, Buffer.from(result.data, "base64"));
  return target;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "wref-override-qc-"));
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
    const cdp = cdpClient(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitFor(cdp, `document.body.textContent.includes("项目总看板")`);
    await evaluate(cdp, `(() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
      setter.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
    })()`);
    await clickText(cdp, "button", "医学写作");
    await waitFor(cdp, `Boolean(document.querySelector(".writing-ai-core"))`);
    await clickText(cdp, ".rail-tabs button", "证据");
    await waitFor(cdp, `Boolean(document.querySelector(".writing-reference-panel"))`);
    await clickText(cdp, ".writing-reference-views button", "译文审核");
    await waitFor(cdp, `document.body.textContent.includes("发现不一致") && document.querySelectorAll(".writing-reference-override-check input").length > 0`);

    const initial = await evaluate(cdp, `(() => ({
      mismatchVisible: document.body.textContent.includes("发现不一致"),
      warningVisible: document.body.textContent.includes("确认沿用不代表系统判定已转为匹配"),
      checkboxCount: document.querySelectorAll(".writing-reference-override-check input").length,
      buttonDisabledBeforeReason: Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("确认沿用当前文件"))?.disabled,
      noOverflowX: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) <= innerWidth + 1,
    }))()`);
    const beforeScreenshot = await screenshot(cdp, "medical_writing_reference_override_before.png");

    await evaluate(cdp, `(() => {
      const textarea = document.querySelector(".writing-reference-override textarea");
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      setter.call(textarea, ${JSON.stringify(overrideReason)});
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    const disabledAfterReasonOnly = await evaluate(cdp, `Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("确认沿用当前文件"))?.disabled`);
    await evaluate(cdp, `(() => {
      document.querySelectorAll(".writing-reference-override-check input").forEach((input) => input.click());
    })()`);
    await waitFor(cdp, `!Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("确认沿用当前文件"))?.disabled`);
    await clickText(cdp, "button", "确认沿用当前文件");
    await waitFor(cdp, `document.body.textContent.includes("已确认沿用") && document.body.textContent.includes(${JSON.stringify(overrideReason)})`);
    const after = await evaluate(cdp, `(() => ({
      confirmedAfterWarningVisible: document.body.textContent.includes("已确认沿用"),
      reasonVisible: document.body.textContent.includes(${JSON.stringify(overrideReason)}),
      issueChecklistRemoved: document.querySelectorAll(".writing-reference-override-check input").length === 0,
      noOverflowX: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) <= innerWidth + 1,
    }))()`);
    const afterScreenshot = await screenshot(cdp, "medical_writing_reference_override_after.png");
    const failures = [];
    if (!initial.mismatchVisible) failures.push("mismatch-not-visible");
    if (!initial.warningVisible) failures.push("warning-not-visible");
    if (initial.checkboxCount < 1) failures.push("missing-issue-checkboxes");
    if (!initial.buttonDisabledBeforeReason) failures.push("button-enabled-before-reason");
    if (!disabledAfterReasonOnly) failures.push("button-enabled-without-acknowledgements");
    if (!initial.noOverflowX || !after.noOverflowX) failures.push("horizontal-overflow");
    for (const [key, value] of Object.entries(after)) if (!value) failures.push(`after:${key}`);
    await writeFile(path.resolve(outputDir, "medical_writing_reference_override_qc.json"), JSON.stringify({ initial, disabledAfterReasonOnly, after, screenshots: [beforeScreenshot, afterScreenshot], failures }, null, 2));
    cdp.close();
    if (failures.length) throw new Error(failures.join(", "));
  } finally {
    chrome.kill("SIGTERM");
    await wait(300);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
