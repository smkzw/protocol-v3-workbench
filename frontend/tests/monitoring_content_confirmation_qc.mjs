import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const uploadFile = process.env.UPLOAD_FILE || "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/准备阶段/RUX-03-002_列表_数据集_Excel_20250612_处理后.xlsx";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/visual_qc_20260713/monitoring_content_confirmation");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9402);

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function requestJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 10000) {
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
  const listeners = new Map();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const handler = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) handler.reject(new Error(message.error.message));
      else handler.resolve(message.result || {});
      return;
    }
    for (const callback of listeners.get(message.method) || []) callback(message.params || {});
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
    once(method) {
      return new Promise((resolve) => {
        const callback = (params) => {
          listeners.set(method, (listeners.get(method) || []).filter((item) => item !== callback));
          resolve(params);
        };
        listeners.set(method, [...(listeners.get(method) || []), callback]);
      });
    },
    close() { ws.close(); },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Runtime evaluation failed");
  }
  return result.result?.value;
}

async function waitFor(cdp, expression, timeoutMs = 90000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(cdp, expression)) return;
    await wait(250);
  }
  throw new Error(`Timed out waiting for: ${expression}`);
}

async function clickText(cdp, selector, text) {
  await evaluate(cdp, `(() => {
    const node = Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find((item) => item.textContent.includes(${JSON.stringify(text)}));
    if (!node) throw new Error(${JSON.stringify(`Missing ${selector}: ${text}`)});
    node.click();
    return true;
  })()`);
}

async function screenshot(cdp, filename) {
  const result = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
  const target = path.join(outputDir, filename);
  await writeFile(target, Buffer.from(result.data, "base64"));
  return target;
}

async function layoutMetrics(cdp) {
  return evaluate(cdp, `(() => {
    const doc = document.documentElement;
    const body = document.body;
    const gate = document.querySelector(".content-confirmation");
    const rect = gate?.getBoundingClientRect();
    return {
      innerWidth: window.innerWidth,
      documentWidth: Math.max(doc.scrollWidth, body.scrollWidth),
      overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
      gateLeft: rect?.left || null,
      gateRight: rect?.right || null,
      gateWidth: rect?.width || null,
      viewportHeight: window.innerHeight,
    };
  })()`);
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "monitoring-confirmation-qc-"));
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
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Chrome page target found");
    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("DOM.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    const loaded = cdp.once("Page.loadEventFired");
    await cdp.send("Page.navigate", { url: appUrl });
    await loaded;
    await wait(900);

    await evaluate(cdp, `(() => {
      window.__intakeCalls = 0;
      window.__confirmationCalls = 0;
      const originalFetch = window.fetch.bind(window);
      window.fetch = (...args) => {
        const url = String(args[0]);
        if (url.includes("/monitoring/intake/file")) window.__intakeCalls += 1;
        if (url.includes("/content-validation/confirm")) window.__confirmationCalls += 1;
        return originalFetch(...args);
      };
      return true;
    })()`);
    await clickText(cdp, "button", "医学监查");
    await wait(700);
    await clickText(cdp, "button", "上传新批次");
    await wait(300);

    const documentNode = await cdp.send("DOM.getDocument", { depth: -1 });
    const inputNode = await cdp.send("DOM.querySelector", { nodeId: documentNode.root.nodeId, selector: 'input[type="file"]' });
    if (!inputNode.nodeId) throw new Error("Missing listing file input");
    await cdp.send("DOM.setFileInputFiles", { nodeId: inputNode.nodeId, files: [uploadFile] });
    await wait(1000);
    await clickText(cdp, "button", "确认 AESI_FLAG 映射");
    await clickText(cdp, "button", "运行医学规则");

    await waitFor(cdp, `document.body.textContent.includes("确认沿用不代表系统判定已转为匹配")`);
    const before = await evaluate(cdp, `(() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("确认沿用并重试上传"));
      return {
        buttonDisabledInitially: button?.disabled,
        checkCount: document.querySelectorAll(".content-confirmation-override-check input").length,
        intakeCalls: window.__intakeCalls,
        confirmationCalls: window.__confirmationCalls,
        hasSecurityScanCopy: /恶意软件|病毒扫描|安全扫描/.test(document.body.textContent),
      };
    })()`);
    if (!before.buttonDisabledInitially || before.checkCount < 1 || before.intakeCalls !== 1 || before.confirmationCalls !== 0 || before.hasSecurityScanCopy) {
      throw new Error(`Unexpected pre-confirmation state: ${JSON.stringify(before)}`);
    }

    await evaluate(cdp, `(() => {
      const textarea = document.querySelector(".content-confirmation textarea");
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      setter.call(textarea, "经医学经理核对，确认该真实listing可用于本次兼容性验证。 ");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    })()`);
    await wait(100);
    const disabledAfterReason = await evaluate(cdp, `Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("确认沿用并重试上传"))?.disabled`);
    if (!disabledAfterReason) throw new Error("Confirmation button enabled before all checks were acknowledged");
    await evaluate(cdp, `(() => {
      document.querySelectorAll(".content-confirmation-override-check input").forEach((item) => item.click());
      return true;
    })()`);
    await waitFor(cdp, `!Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("确认沿用并重试上传"))?.disabled`);
    const preConfirmLayout1600 = await layoutMetrics(cdp);
    const preConfirmScreenshot = await screenshot(cdp, "monitoring_content_confirmation_1600_before.png");
    await clickText(cdp, "button", "确认沿用并重试上传");

    await waitFor(cdp, `document.body.textContent.includes("已确认沿用")`, 120000);
    await waitFor(cdp, `window.__intakeCalls >= 2`, 120000);
    await waitFor(
      cdp,
      `document.body.textContent.includes("确认已记录，但后端规则执行未完成") || document.body.textContent.includes("规则生成风险") || document.body.textContent.includes("已生成")`,
      180000,
    );
    const after = await evaluate(cdp, `(() => ({
      intakeCalls: window.__intakeCalls,
      confirmationCalls: window.__confirmationCalls,
      hasConfirmedUse: document.body.textContent.includes("已确认沿用"),
      keepsNonMatchStatus: document.body.textContent.includes("内容状态：需确认") || document.body.textContent.includes("内容状态：不一致"),
      hasFailureState: document.body.textContent.includes("确认已记录，但后端规则执行未完成"),
      hasRuleResult: document.body.textContent.includes("规则生成风险") || document.body.textContent.includes("已生成"),
      hasRelabeledMatch: document.querySelector(".content-confirmation-record")?.textContent.includes("内容状态：匹配") || false,
    }))()`);
    if (after.intakeCalls !== 2 || after.confirmationCalls !== 1 || !after.hasConfirmedUse || !after.keepsNonMatchStatus || after.hasRelabeledMatch || (!after.hasFailureState && !after.hasRuleResult)) {
      throw new Error(`Unexpected post-confirmation state: ${JSON.stringify(after)}`);
    }
    const afterScreenshot1600 = await screenshot(cdp, "monitoring_content_confirmation_1600_after.png");
    const afterLayout1600 = await layoutMetrics(cdp);

    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await wait(400);
    const afterLayout1920 = await layoutMetrics(cdp);
    const afterScreenshot1920 = await screenshot(cdp, "monitoring_content_confirmation_1920_after.png");
    if (preConfirmLayout1600.overflowX || afterLayout1600.overflowX || afterLayout1920.overflowX) {
      throw new Error(`Desktop horizontal overflow: ${JSON.stringify({ preConfirmLayout1600, afterLayout1600, afterLayout1920 })}`);
    }

    const result = {
      appUrl,
      uploadFile,
      before,
      after,
      disabledAfterReason,
      layouts: { preConfirmLayout1600, afterLayout1600, afterLayout1920 },
      screenshots: { preConfirmScreenshot, afterScreenshot1600, afterScreenshot1920 },
    };
    const metricsPath = path.join(outputDir, "monitoring_content_confirmation_qc.json");
    await writeFile(metricsPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
    console.log(metricsPath);
    cdp.close();
  } finally {
    chrome.kill("SIGTERM");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
