import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/visual_qc_20260707");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9333);

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
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
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Runtime evaluation failed");
  return result.result?.value;
}

async function navigateToPatientProfile(cdp, viewport) {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: viewport.width,
    height: viewport.height,
    deviceScaleFactor: 1,
    mobile: viewport.mobile,
  });
  const loaded = cdp.once("Page.loadEventFired");
  await cdp.send("Page.navigate", { url: appUrl });
  await loaded;
  await wait(800);
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
      const button = Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("进入 Patient Profile"));
      if (!button) throw new Error("Missing Patient Profile entry");
      button.click();
      return true;
    })()
  `);
  await wait(1200);
}

async function capture(cdp, name, viewport) {
  await navigateToPatientProfile(cdp, viewport);
  const metrics = await evaluate(cdp, `
    (() => {
      const doc = document.documentElement;
      const body = document.body;
      const docW = Math.max(doc.scrollWidth, body.scrollWidth);
      const innerW = window.innerWidth;
      const profileText = document.querySelector(".patient-profile-page")?.textContent || "";
      return {
        viewport: "${name}",
        innerW,
        docW,
        overflowX: docW > innerW + 1,
        metricCharts: document.querySelectorAll(".metric-chart").length,
        centerGroups: document.querySelectorAll(".profile-tree-group").length,
        hasBasicInfo: profileText.includes("基本信息"),
        hasEfficacy: profileText.includes("疗效指标历时变化"),
        hasSafety: profileText.includes("安全性历时变化"),
        hasPdQuery: profileText.includes("PD / Query"),
        hasRiskPrompts: profileText.includes("风险提示"),
      };
    })()
  `);
  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: true,
  });
  const screenshotPath = path.join(outputDir, `patient_profile_v10_step_${name}.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return { ...metrics, screenshotPath };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "patient-profile-qc-"));
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

    const results = [];
    results.push(await capture(cdp, "desktop", { width: 1440, height: 1100, mobile: false }));
    results.push(await capture(cdp, "mobile", { width: 390, height: 1200, mobile: true }));

    cdp.close();
    const metricsPath = path.join(outputDir, "patient_profile_v10_step_metrics.json");
    await writeFile(metricsPath, `${JSON.stringify({ appUrl, results }, null, 2)}\n`, "utf8");
    console.log(metricsPath);
  } finally {
    chrome.kill("SIGTERM");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
