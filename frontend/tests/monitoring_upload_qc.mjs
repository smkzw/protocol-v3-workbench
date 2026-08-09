import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/visual_qc_20260707");
const uploadFile = process.env.UPLOAD_FILE || "/tmp/workbench_monitoring_upload_qc.xlsx";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9344);

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
  const listeners = new Map();

  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result || {});
      return;
    }
    const callbacks = listeners.get(message.method) || [];
    callbacks.forEach((callback) => callback(message.params || {}));
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
    once(method) {
      return new Promise((resolve) => {
        const callback = (params) => {
          const callbacks = listeners.get(method) || [];
          listeners.set(method, callbacks.filter((item) => item !== callback));
          resolve(params);
        };
        listeners.set(method, [...(listeners.get(method) || []), callback]);
      });
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

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "monitoring-upload-qc-"));
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
    let targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    let target = targets.find((item) => item.type === "page");
    if (!target) {
      await fetch(`http://127.0.0.1:${debugPort}/json/new?about:blank`, { method: "PUT" });
      targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
      target = targets.find((item) => item.type === "page");
    }
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Chrome page target found.");

    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("DOM.enable");

    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    });
    const loaded = cdp.once("Page.loadEventFired");
    await cdp.send("Page.navigate", { url: appUrl });
    await loaded;
    await wait(900);

    await evaluate(cdp, `
      (() => {
        const clickByText = (text) => {
          const button = Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes(text));
          if (!button) throw new Error("Missing button: " + text);
          button.click();
        };
        clickByText("医学监查");
        return true;
      })()
    `);
    await wait(700);
    await evaluate(cdp, `
      (() => {
        const button = Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("上传新批次"));
        if (!button) throw new Error("Missing button: 上传新批次");
        button.click();
        return true;
      })()
    `);
    await wait(500);

    const documentNode = await cdp.send("DOM.getDocument", { depth: -1 });
    const inputNode = await cdp.send("DOM.querySelector", {
      nodeId: documentNode.root.nodeId,
      selector: 'input[type="file"]',
    });
    if (!inputNode.nodeId) throw new Error("Missing listing file input");
    await cdp.send("DOM.setFileInputFiles", { nodeId: inputNode.nodeId, files: [uploadFile] });
    await wait(700);

    await evaluate(cdp, `
      (() => {
        const button = Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("导入并解析"));
        if (!button) throw new Error("Missing button: 导入并解析");
        if (button.disabled) throw new Error("导入并解析 button is still disabled");
        button.click();
        return true;
      })()
    `);
    await wait(1800);
    await evaluate(cdp, `
      (() => {
        const button = Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("确认解析结果"));
        if (!button) throw new Error("Missing button: 确认解析结果");
        button.click();
        return true;
      })()
    `);
    await wait(700);
    await evaluate(cdp, `
      (() => {
        const checkbox = Array.from(document.querySelectorAll('input[type="checkbox"]')).find(
          (item) => item.parentElement?.textContent?.includes("确认这是本次完整全量 EDC 导出")
        );
        if (!checkbox) throw new Error("Missing full snapshot confirmation");
        checkbox.click();
        const button = Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("确认为比较基线"));
        if (!button) throw new Error("Missing button: 确认为比较基线");
        if (button.disabled) throw new Error("确认为比较基线 button is still disabled");
        button.click();
        return true;
      })()
    `);
    await wait(1300);

    const metrics = await evaluate(cdp, `
      (() => {
        const text = document.body.textContent || "";
        const doc = document.documentElement;
        const body = document.body;
        const docW = Math.max(doc.scrollWidth, body.scrollWidth);
        const innerW = window.innerWidth;
        return {
          uploadFile: ${JSON.stringify(uploadFile)},
          hasFrozenBaseline: text.includes("可比较基线"),
          hasNoAutomaticRuleRun: text.includes("尚未自动运行医学风险规则"),
          hasReadableSourceClass: text.includes("原始全量快照（已确认）"),
          hasExpectedDomains: ["AE", "CM", "EX", "LB"].every((domain) => text.includes(domain)),
          hasLegacyAutomaticRunFlow: text.includes("确认 AESI_FLAG 映射") || text.includes("运行医学规则"),
          overflowX: docW > innerW + 1,
          docW,
          innerW,
        };
      })()
    `);
    if (
      !metrics.hasFrozenBaseline
      || !metrics.hasNoAutomaticRuleRun
      || !metrics.hasReadableSourceClass
      || !metrics.hasExpectedDomains
      || metrics.hasLegacyAutomaticRunFlow
      || metrics.overflowX
    ) {
      throw new Error(`Monitoring upload QC failed: ${JSON.stringify(metrics)}`);
    }

    const screenshot = await cdp.send("Page.captureScreenshot", {
      format: "png",
      fromSurface: true,
      captureBeyondViewport: true,
    });
    const screenshotPath = path.join(outputDir, "monitoring_batch_p2_qc.png");
    await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
    const metricsPath = path.join(outputDir, "monitoring_batch_p2_qc.json");
    await writeFile(metricsPath, `${JSON.stringify({ appUrl, metrics, screenshotPath }, null, 2)}\n`, "utf8");
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
