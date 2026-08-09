import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5176/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "records/visual_qc_20260708/rux_three_subject_drilldown");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9363);
const subjectIds = ["S01003", "S01017", "S03040"];

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

async function clickByText(cdp, text) {
  await evaluate(cdp, `
    (() => {
      const target = Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes(${JSON.stringify(text)}));
      if (!target) throw new Error("Missing button: " + ${JSON.stringify(text)});
      target.click();
      return true;
    })()
  `);
}

async function selectCurrentPageSubject(cdp, subjectId, pageSelector) {
  await evaluate(cdp, `
    (() => {
      const root = document.querySelector(${JSON.stringify(pageSelector)});
      if (!root) throw new Error("Missing page root: " + ${JSON.stringify(pageSelector)});
      const select = root.querySelector("select");
      if (!select) throw new Error("Missing subject select for " + ${JSON.stringify(pageSelector)});
      select.value = ${JSON.stringify(subjectId)};
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  await waitForText(cdp, subjectId, 30000);
  await wait(500);
}

async function gotoMonitoring(cdp) {
  await clickByText(cdp, "医学监查");
  await waitForText(cdp, "进入 Subject Timeline", 10000);
}

async function openTimeline(cdp, subjectId) {
  await clickByText(cdp, "进入 Subject Timeline");
  await waitForText(cdp, "受试者", 10000);
  await selectCurrentPageSubject(cdp, subjectId, ".reference-timeline-page");
  await waitForText(cdp, "AE 明细", 30000);
}

async function openProfile(cdp, subjectId) {
  await clickByText(cdp, "进入 Patient Profile");
  await waitForText(cdp, "疗效指标历时变化", 30000);
  await waitForText(cdp, subjectId, 30000);
  await waitForText(cdp, "BSA总受累体表面积", 30000);
}

async function capturePageMetrics(cdp, subjectId, pageType) {
  return evaluate(cdp, `
    (() => {
      const doc = document.documentElement;
      const body = document.body;
      const root = document.querySelector(${JSON.stringify(pageType === "timeline" ? ".reference-timeline-page" : ".patient-profile-page")});
      const pageText = root?.textContent || "";
      const topbarText = document.querySelector(".topbar")?.textContent || "";
      const selects = Array.from(root?.querySelectorAll("select") || []);
      const subjectOptions = selects.flatMap((select) => Array.from(select.options || []).map((option) => option.value || option.textContent || ""));
      const categoryClassFor = (item) => Array.from(item.classList || []).find((name) => name.startsWith("event-category-")) || "";
      const eventBlocks = ${JSON.stringify(pageType)} === "timeline" ? Array.from(root?.querySelectorAll(".reference-svg-event-block") || []) : [];
      const blockCategories = eventBlocks.map(categoryClassFor);
      const blockFills = eventBlocks.map((block) => getComputedStyle(block).fill);
      const legendChips = ${JSON.stringify(pageType)} === "timeline" ? Array.from(root?.querySelectorAll(".timeline-category-chip") || []) : [];
      const detailRows = ${JSON.stringify(pageType)} === "timeline" ? Array.from(root?.querySelectorAll(".timeline-detail-row") || []) : [];
      return {
        subjectId: ${JSON.stringify(subjectId)},
        pageType: ${JSON.stringify(pageType)},
        overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
        hasRuxHeader: topbarText.includes("RUX-03-002"),
        hasReadableBatchLabel: topbarText.includes("RUX-03-002 原始数据 listing 2025-06-12"),
        hasTechnicalBatchIdInTopbar: topbarText.includes("rux_03_002_listing_20250612"),
        hasSubject: pageText.includes(${JSON.stringify(subjectId)}),
        subjectOptionCount: subjectOptions.length,
        hasDemoSubjectLeak: subjectOptions.includes("10008") || subjectOptions.includes("06021"),
        hasTimelineLanes: ${JSON.stringify(pageType)} === "timeline" ? pageText.includes("AE 明细") && pageText.includes("实验室/疗效 明细") : true,
        hasProfileTrends: ${JSON.stringify(pageType)} === "profile" ? pageText.includes("BSA总受累体表面积") && pageText.includes("ALT") && pageText.includes("AST") : true,
        timelineEventBlocks: eventBlocks.length,
        timelineBlockCategories: Array.from(new Set(blockCategories)).filter(Boolean),
        timelineMissingCategoryClassCount: blockCategories.filter((category) => !category).length,
        timelineDistinctFillCount: new Set(blockFills).size,
        timelineLegendCategoryCount: legendChips.length,
        timelineDetailRowsMissingCategoryCount: detailRows.filter((row) => !categoryClassFor(row)).length,
      };
    })()
  `);
}

async function runViewport(cdp, name, viewport) {
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
  if (!dashboardLoaded) throw new Error("Dashboard did not load RUX project");
  await gotoMonitoring(cdp);

  const pageResults = [];
  for (const subjectId of subjectIds) {
    await openTimeline(cdp, subjectId);
    pageResults.push(await capturePageMetrics(cdp, subjectId, "timeline"));
    await clickByText(cdp, "返回医学监查");
    await waitForText(cdp, "进入 Patient Profile", 10000);
    await openProfile(cdp, subjectId);
    pageResults.push(await capturePageMetrics(cdp, subjectId, "profile"));
    await clickByText(cdp, "返回医学监查");
    await waitForText(cdp, "进入 Subject Timeline", 10000);
  }

  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: true,
  });
  const screenshotPath = path.join(outputDir, `rux_three_subject_drilldown_${name}.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return { viewport: name, pageResults, screenshotPath };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "rux-three-subject-drilldown-qc-"));
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
    results.push(await runViewport(cdp, "desktop", { width: 1440, height: 1200, mobile: false }));
    results.push(await runViewport(cdp, "mobile", { width: 390, height: 1200, mobile: true }));
    cdp.close();

    const metricsPath = path.join(outputDir, "rux_three_subject_drilldown_metrics.json");
    await writeFile(metricsPath, `${JSON.stringify({ appUrl, subjectIds, results }, null, 2)}\n`, "utf8");

    const failures = [];
    for (const result of results) {
      for (const page of result.pageResults) {
        if (!page.hasRuxHeader) failures.push(`${result.viewport}/${page.subjectId}/${page.pageType}: missing RUX header`);
        if (!page.hasReadableBatchLabel) failures.push(`${result.viewport}/${page.subjectId}/${page.pageType}: missing readable batch label`);
        if (page.hasTechnicalBatchIdInTopbar) failures.push(`${result.viewport}/${page.subjectId}/${page.pageType}: technical batch id leaked`);
        if (!page.hasSubject) failures.push(`${result.viewport}/${page.subjectId}/${page.pageType}: subject id not visible`);
        if (page.hasDemoSubjectLeak) failures.push(`${result.viewport}/${page.subjectId}/${page.pageType}: demo subject leaked`);
        if (page.overflowX) failures.push(`${result.viewport}/${page.subjectId}/${page.pageType}: horizontal overflow`);
        if (!page.hasTimelineLanes) failures.push(`${result.viewport}/${page.subjectId}/${page.pageType}: timeline lanes missing`);
        if (!page.hasProfileTrends) failures.push(`${result.viewport}/${page.subjectId}/${page.pageType}: profile trends missing`);
        if (page.pageType === "timeline") {
          if (page.timelineEventBlocks && page.timelineMissingCategoryClassCount) failures.push(`${result.viewport}/${page.subjectId}: timeline event blocks missing category color classes`);
          if (page.timelineEventBlocks && page.timelineLegendCategoryCount < page.timelineBlockCategories.length) failures.push(`${result.viewport}/${page.subjectId}: timeline legend does not cover visible categories`);
          if (page.timelineEventBlocks && page.timelineDistinctFillCount < Math.min(page.timelineBlockCategories.length, 2)) failures.push(`${result.viewport}/${page.subjectId}: timeline category fills are not distinct`);
          if (page.timelineDetailRowsMissingCategoryCount) failures.push(`${result.viewport}/${page.subjectId}: timeline detail rows missing category color classes`);
        }
      }
    }
    const observedTimelineCategories = new Set(
      results.flatMap((result) => result.pageResults)
        .filter((page) => page.pageType === "timeline")
        .flatMap((page) => page.timelineBlockCategories || [])
    );
    for (const category of [
      "event-category-adverse-event",
      "event-category-dose-adjustment",
      "event-category-lab",
      "event-category-efficacy-score",
    ]) {
      if (!observedTimelineCategories.has(category)) failures.push(`three-subject run: missing observed ${category}`);
    }
    if (failures.length) throw new Error(`RUX three-subject drilldown QC failed: ${failures.join("; ")}. Metrics: ${metricsPath}`);
    console.log(metricsPath);
  } finally {
    chrome.kill("SIGTERM");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
