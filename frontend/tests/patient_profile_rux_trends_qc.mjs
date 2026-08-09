import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5176/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "records/visual_qc_20260708/rux_patient_profile_trends");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9362);

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
    (listeners.get(message.method) || []).forEach((callback) => callback(message.params || {}));
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
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.exception?.value || result.exceptionDetails.text;
    throw new Error(detail || "Runtime evaluation failed");
  }
  return result.result?.value;
}

async function waitForText(cdp, text, timeoutMs = 10000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(cdp, `document.body.textContent.includes(${JSON.stringify(text)})`)) return true;
    await wait(250);
  }
  return false;
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
  const dashboardLoaded = await waitForText(cdp, "RUX-03-002", 30000);
  if (!dashboardLoaded) throw new Error("Dashboard header did not switch to RUX-03-002");
  await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("医学监查"));
      if (!button) throw new Error("Missing 医学监查 button");
      button.click();
      return true;
    })()
  `);
  await waitForText(cdp, "进入 Patient Profile", 10000);
  await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("进入 Patient Profile"));
      if (!button) throw new Error("Missing Patient Profile entry");
      button.click();
      return true;
    })()
  `);
  const profileLoaded = await waitForText(cdp, "疗效指标历时变化", 30000);
  if (!profileLoaded) throw new Error("Patient Profile did not render trend section");
  const bsaLoaded = await waitForText(cdp, "BSA总受累体表面积", 30000);
  if (!bsaLoaded) throw new Error("Patient Profile did not render BSA trend");
}

async function capture(cdp, name, viewport) {
  await navigateToPatientProfile(cdp, viewport);
  const metrics = await evaluate(cdp, `
    (() => {
      const doc = document.documentElement;
      const body = document.body;
      const docW = Math.max(doc.scrollWidth, body.scrollWidth);
      const innerW = window.innerWidth;
      const pageText = document.querySelector(".patient-profile-page")?.textContent || "";
      const topbarText = document.querySelector(".topbar")?.textContent || "";
      const selects = Array.from(document.querySelectorAll(".patient-profile-page select"));
      const subjectOptions = selects.flatMap((select) => Array.from(select.options || []).map((option) => option.value || option.textContent || ""));
      const metricTitles = Array.from(document.querySelectorAll(".metric-chart-head strong")).map((item) => item.textContent || "");
      return {
        viewport: ${JSON.stringify(name)},
        innerW,
        docW,
        overflowX: docW > innerW + 1,
        hasRuxHeader: document.body.textContent.includes("RUX-03-002"),
        hasReadableBatchLabel: topbarText.includes("RUX-03-002 原始数据 listing 2025-06-12"),
        hasTechnicalBatchIdInTopbar: topbarText.includes("rux_03_002_listing_20250612"),
        hasSubject: pageText.includes("S01003"),
        subjectOptionCount: subjectOptions.length,
        hasDemoSubjectLeak: subjectOptions.includes("10008") || subjectOptions.includes("06021"),
        metricTitles,
        hasBsa: pageText.includes("BSA总受累体表面积"),
        hasIga: pageText.includes("IGA评分"),
        hasEasi: pageText.includes("EASI总分"),
        hasScorad: pageText.includes("SCORAD总分"),
        hasAnc: pageText.includes("中性粒细胞计数"),
        hasAlt: pageText.includes("ALT"),
        hasAst: pageText.includes("AST"),
        efficacyCountVisible: pageText.includes("4疗效指标") || pageText.includes("4 个指标"),
        safetyCountVisible: pageText.includes("3安全性指标") || pageText.includes("3 个指标"),
      };
    })()
  `);
  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: true,
  });
  const screenshotPath = path.join(outputDir, `patient_profile_rux_trends_${name}.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return { ...metrics, screenshotPath };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "patient-profile-rux-trends-qc-"));
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
    results.push(await capture(cdp, "desktop", { width: 1440, height: 1200, mobile: false }));
    results.push(await capture(cdp, "mobile", { width: 390, height: 1200, mobile: true }));
    cdp.close();

    const metricsPath = path.join(outputDir, "patient_profile_rux_trends_metrics.json");
    await writeFile(metricsPath, `${JSON.stringify({ appUrl, results }, null, 2)}\n`, "utf8");
    const failures = results.flatMap((result) => {
      const failed = [];
      if (!result.hasRuxHeader) failed.push(`${result.viewport}: missing RUX header`);
      if (!result.hasReadableBatchLabel) failed.push(`${result.viewport}: missing reader-friendly RUX batch label`);
      if (result.hasTechnicalBatchIdInTopbar) failed.push(`${result.viewport}: technical batch id leaked into topbar`);
      if (!result.hasSubject) failed.push(`${result.viewport}: missing S01003`);
      if (result.subjectOptionCount < 20) failed.push(`${result.viewport}: RUX center-filtered subject catalog too small (${result.subjectOptionCount})`);
      if (result.hasDemoSubjectLeak) failed.push(`${result.viewport}: demo subjects leaked into Patient Profile selector`);
      for (const key of ["hasBsa", "hasIga", "hasEasi", "hasScorad", "hasAnc", "hasAlt", "hasAst"]) {
        if (!result[key]) failed.push(`${result.viewport}: missing ${key}`);
      }
      if (!result.efficacyCountVisible) failed.push(`${result.viewport}: efficacy metric count not visible as 4`);
      if (!result.safetyCountVisible) failed.push(`${result.viewport}: safety metric count not visible as 3`);
      if (result.overflowX) failed.push(`${result.viewport}: page horizontal overflow`);
      return failed;
    });
    if (failures.length) throw new Error(`Patient Profile RUX trend QC failed: ${failures.join("; ")}. Metrics: ${metricsPath}`);
    console.log(metricsPath);
  } finally {
    chrome.kill("SIGTERM");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
