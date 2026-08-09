import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5176/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/visual_qc_20260708/rux_subject_timeline_ip_lane");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9361);

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
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.exception?.value || result.exceptionDetails.text;
    throw new Error(detail || "Runtime evaluation failed");
  }
  return result.result?.value;
}

async function waitForText(cdp, text, timeoutMs = 10000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const found = await evaluate(cdp, `document.body.textContent.includes(${JSON.stringify(text)})`);
    if (found) return true;
    await wait(250);
  }
  return false;
}

async function waitForCondition(cdp, expression, timeoutMs = 10000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const found = await evaluate(cdp, expression);
    if (found) return true;
    await wait(250);
  }
  return false;
}

async function navigateToSubjectTimeline(cdp, viewport, subjectId) {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: viewport.width,
    height: viewport.height,
    deviceScaleFactor: 1,
    mobile: viewport.mobile,
  });
  const loaded = cdp.once("Page.loadEventFired");
  await cdp.send("Page.navigate", { url: appUrl });
  await loaded;
  await wait(1000);
  const dashboardLoaded = await waitForText(cdp, "项目总看板", 30000);
  if (!dashboardLoaded) throw new Error("Dashboard did not render before timeout");
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
  const ruxContextLoaded = await waitForText(cdp, "RUX-03-002", 30000);
  if (!ruxContextLoaded) throw new Error("Medical Monitoring page did not switch to RUX-03-002 context before timeout");
  await waitForText(cdp, "进入 Subject Timeline", 10000);
  await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("进入 Subject Timeline"));
      if (!button) throw new Error("Missing Subject Timeline entry");
      button.click();
      return true;
    })()
  `);
  const laneLoaded = await waitForText(cdp, "试验药物变更", 10000);
  if (!laneLoaded) throw new Error("Subject Timeline did not render trial-drug lane");
  const ruxSelectorLoaded = await waitForCondition(cdp, `
    Boolean(
      document.querySelector(".reference-subject-switch select")
      && Array.from(document.querySelector(".reference-subject-switch select").options).some((option) => option.value === "S01003")
      && Array.from(document.querySelector(".reference-subject-switch select").options).some((option) => option.value === "S01017")
    )
  `, 30000);
  if (!ruxSelectorLoaded) throw new Error("Subject Timeline did not load RUX subject selector before timeout");
  await evaluate(cdp, `
    (() => {
      const select = document.querySelector(".reference-subject-switch select");
      if (!select) throw new Error("Missing Subject Timeline subject selector");
      select.value = ${JSON.stringify(subjectId)};
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  const subjectLoaded = await waitForText(cdp, subjectId, 10000);
  if (!subjectLoaded) throw new Error(`Subject Timeline did not switch to ${subjectId}`);
  const doseAdjustmentLoaded = await waitForText(cdp, "DA1", 30000);
  if (!doseAdjustmentLoaded) throw new Error("Subject Timeline did not render DA dose-adjustment events before timeout");
  if (subjectId === "S01017") {
    const concomitantMedicationLoaded = await waitForText(cdp, "盐酸左西替利嗪片", 30000);
    if (!concomitantMedicationLoaded) throw new Error("Subject Timeline did not render real RUX CM event before timeout");
  }
}

async function capture(cdp, name, viewport, subjectId) {
  await navigateToSubjectTimeline(cdp, viewport, subjectId);
  const metrics = await evaluate(cdp, `
    (() => {
      const doc = document.documentElement;
      const body = document.body;
      const docW = Math.max(doc.scrollWidth, body.scrollWidth);
      const innerW = window.innerWidth;
      const pageText = document.querySelector(".reference-timeline-page")?.textContent || "";
      const detailCards = Array.from(document.querySelectorAll(".timeline-detail-card")).map((card) => ({
        title: card.querySelector(".section-title h2, .section-title h3, h2, h3")?.textContent || "",
        text: card.textContent || "",
      }));
      const cmCard = detailCards.find((card) => card.text.includes("合并用药（非试验用药） 明细")) || { text: "" };
      const ipCard = detailCards.find((card) => card.text.includes("试验药物变更 明细")) || { text: "" };
      const eventBlocks = Array.from(document.querySelectorAll(".reference-svg-event-block"));
      const categoryClassFor = (item) => Array.from(item.classList || []).find((name) => name.startsWith("event-category-")) || "";
      const blockFills = eventBlocks.map((block) => getComputedStyle(block).fill);
      const blockCategories = eventBlocks.map(categoryClassFor);
      const laneClassFor = (item) => Array.from(item.classList || []).find((name) => name.startsWith("lane-")) || "";
      const categoryFillPairs = eventBlocks.map((block) => ({
        lane: laneClassFor(block),
        category: categoryClassFor(block),
        fill: getComputedStyle(block).fill,
      }));
      const laneCategoryMap = {};
      categoryFillPairs.forEach((item) => {
        if (!item.lane || !item.category) return;
        laneCategoryMap[item.lane] = Array.from(new Set([...(laneCategoryMap[item.lane] || []), item.category]));
      });
      const visibleCategoryFillMap = {};
      const categoryFillConflicts = [];
      categoryFillPairs.forEach((item) => {
        if (!item.category) return;
        if (visibleCategoryFillMap[item.category] && visibleCategoryFillMap[item.category] !== item.fill) {
          categoryFillConflicts.push(item.category);
        }
        visibleCategoryFillMap[item.category] = item.fill;
      });
      const legendChips = Array.from(document.querySelectorAll(".timeline-category-chip")).map((chip) => ({
        text: chip.textContent.trim(),
        category: categoryClassFor(chip),
        fill: getComputedStyle(chip).getPropertyValue("--category-fill").trim(),
      }));
      const detailRows = Array.from(document.querySelectorAll(".timeline-detail-row")).map((row) => ({
        category: categoryClassFor(row),
        borderColor: getComputedStyle(row).borderLeftColor,
      }));
      const subjectSelect = document.querySelector(".reference-subject-switch select");
      const subjectOptions = Array.from(subjectSelect?.options || []).map((option) => option.value || option.textContent || "");
      const laneFills = {
        ae: getComputedStyle(document.querySelector(".reference-svg-event-block.lane-ae") || document.body).fill,
        ip: getComputedStyle(document.querySelector(".reference-svg-event-block.lane-ip") || document.body).fill,
        lab: getComputedStyle(document.querySelector(".reference-svg-event-block.lane-lab") || document.body).fill,
      };
      return {
        viewport: ${JSON.stringify(name)},
        subjectId: ${JSON.stringify(subjectId)},
        innerW,
        docW,
        overflowX: docW > innerW + 1,
        hasSubject: pageText.includes(${JSON.stringify(subjectId)}),
        hasRuxHeader: document.body.textContent.includes("RUX-03-002"),
        usesLargeCatalogSelect: Boolean(subjectSelect),
        subjectOptionCount: subjectOptions.length,
        hasRuxSubjectCatalog: subjectOptions.includes("S01017") && subjectOptions.includes("S03040"),
        hasDemoSubjectLeak: subjectOptions.includes("10008") || subjectOptions.includes("06021"),
        hasTrialDrugLane: pageText.includes("试验药物变更"),
        hasCmLane: pageText.includes("合并用药（非试验用药）"),
        hasRealCmMedication: pageText.includes("盐酸左西替利嗪片"),
        cmCardHasRealMedication: cmCard.text.includes("盐酸左西替利嗪片"),
        cmCardHasNonStudyDrugBoundary: cmCard.text.includes("非试验用药"),
        hasDaBlocks: pageText.includes("DA1") && pageText.includes("DA2"),
        hasDoseAdjustmentTitle: pageText.includes("暂停用药") && pageText.includes("重新用药"),
        ipCardHasDoseAdjustment: ipCard.text.includes("暂停用药") && ipCard.text.includes("重新用药"),
        cmCardHasDoseAdjustmentLeak: cmCard.text.includes("暂停用药") || cmCard.text.includes("重新用药") || cmCard.text.includes("试验药物"),
        eventBlocks: eventBlocks.length,
        distinctEventFillCount: new Set(blockFills).size,
        blockCategories: Array.from(new Set(blockCategories)).filter(Boolean),
        missingCategoryClassCount: blockCategories.filter((category) => !category).length,
        categoryFillPairs,
        laneCategoryMap,
        visibleCategoryFillMap,
        distinctVisibleCategoryFillCount: new Set(Object.values(visibleCategoryFillMap)).size,
        categoryFillConflictCount: new Set(categoryFillConflicts).size,
        legendChips,
        legendCategoryCount: legendChips.length,
        detailRowCount: detailRows.length,
        detailRowsMissingCategoryCount: detailRows.filter((row) => !row.category).length,
        detailRowsWithoutColorCount: detailRows.filter((row) => row.borderColor === "rgba(0, 0, 0, 0)" || row.borderColor === "transparent").length,
        laneFills,
        ipColorDistinctFromAeAndLab: Boolean(laneFills.ip) && laneFills.ip !== laneFills.ae && laneFills.ip !== laneFills.lab,
        detailCards: detailCards.map((card) => card.title || card.text.slice(0, 40)),
      };
    })()
  `);
  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: true,
  });
  const screenshotPath = path.join(outputDir, `subject_timeline_ip_lane_${subjectId}_${name}.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return { ...metrics, screenshotPath };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "subject-timeline-ip-lane-qc-"));
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
    results.push(await capture(cdp, "desktop", { width: 1440, height: 1100, mobile: false }, "S01017"));
    results.push(await capture(cdp, "desktop-lab-split", { width: 1440, height: 1100, mobile: false }, "S01003"));
    results.push(await capture(cdp, "mobile-smoke", { width: 390, height: 1200, mobile: true }, "S01017"));

    cdp.close();
    const metricsPath = path.join(outputDir, "subject_timeline_ip_lane_metrics.json");
    await writeFile(metricsPath, `${JSON.stringify({ appUrl, results }, null, 2)}\n`, "utf8");

    const failures = results.flatMap((result) => {
      const failed = [];
      const desktopRequired = result.viewport === "desktop";
      const labDesktopRequired = result.viewport === "desktop-lab-split";
      const cmBoundaryRequired = result.subjectId === "S01017" && result.viewport !== "mobile-smoke";
      if (!result.hasSubject) failed.push(`${result.viewport}: missing ${result.subjectId}`);
      if (!result.hasRuxHeader) failed.push(`${result.viewport}: missing RUX header`);
      if (desktopRequired && !result.usesLargeCatalogSelect) failed.push(`${result.viewport}: large RUX subject catalog is not using a select control`);
      if (desktopRequired && result.subjectOptionCount < 200) failed.push(`${result.viewport}: RUX subject catalog has too few subjects (${result.subjectOptionCount})`);
      if (desktopRequired && !result.hasRuxSubjectCatalog) failed.push(`${result.viewport}: RUX subject catalog is missing S01017/S03040`);
      if (desktopRequired && result.hasDemoSubjectLeak) failed.push(`${result.viewport}: demo subjects leaked into RUX subject catalog`);
      if (desktopRequired && !result.hasTrialDrugLane) failed.push(`${result.viewport}: missing trial-drug lane`);
      if (desktopRequired && !result.hasCmLane) failed.push(`${result.viewport}: missing CM lane`);
      if (cmBoundaryRequired && !result.hasRealCmMedication) failed.push(`${result.viewport}: missing real RUX CM medication event`);
      if (cmBoundaryRequired && !result.cmCardHasRealMedication) failed.push(`${result.viewport}: real RUX CM medication not in CM detail card`);
      if (cmBoundaryRequired && !result.cmCardHasNonStudyDrugBoundary) failed.push(`${result.viewport}: CM detail card lacks non-study-drug boundary text`);
      if (desktopRequired && !result.hasDaBlocks) failed.push(`${result.viewport}: missing DA compact blocks`);
      if (desktopRequired && !result.hasDoseAdjustmentTitle) failed.push(`${result.viewport}: missing dose-adjustment titles`);
      if (desktopRequired && !result.ipCardHasDoseAdjustment) failed.push(`${result.viewport}: dose adjustment not in IP detail card`);
      if (desktopRequired && result.cmCardHasDoseAdjustmentLeak) failed.push(`${result.viewport}: dose adjustment leaked into CM detail card`);
      if (desktopRequired && result.distinctEventFillCount < 3) failed.push(`${result.viewport}: lane event colors are not distinct enough`);
      if (desktopRequired && result.missingCategoryClassCount) failed.push(`${result.viewport}: ${result.missingCategoryClassCount} event blocks are missing category color classes`);
      if (desktopRequired && result.categoryFillConflictCount) failed.push(`${result.viewport}: same event category rendered with conflicting colors`);
      if (desktopRequired && result.distinctVisibleCategoryFillCount !== result.blockCategories.length) {
        failed.push(`${result.viewport}: visible event categories do not have one distinct color per category`);
      }
      if (desktopRequired && result.legendCategoryCount < result.blockCategories.length) failed.push(`${result.viewport}: category legend does not cover visible event categories`);
      if (desktopRequired && !result.blockCategories.includes("event-category-dose-adjustment-paused")) failed.push(`${result.viewport}: missing trial-drug pause category color`);
      if (desktopRequired && !result.blockCategories.includes("event-category-dose-adjustment-resumed")) failed.push(`${result.viewport}: missing trial-drug resume category color`);
      if (desktopRequired && !result.blockCategories.includes("event-category-concomitant-medication")) failed.push(`${result.viewport}: missing CM non-study-drug category color`);
      if (desktopRequired && !result.blockCategories.includes("event-category-adverse-event-review")) failed.push(`${result.viewport}: missing AE review category color`);
      if (labDesktopRequired && !result.blockCategories.includes("event-category-lab-hematology")) failed.push(`${result.viewport}: missing hematology lab category color`);
      if (labDesktopRequired && !result.blockCategories.includes("event-category-lab-chemistry")) failed.push(`${result.viewport}: missing chemistry lab category color`);
      if (desktopRequired && (result.laneCategoryMap?.["lane-ip"] || []).length < 2) failed.push(`${result.viewport}: IP lane does not split pause/resume categories`);
      if (labDesktopRequired && (result.laneCategoryMap?.["lane-lab"] || []).length < 2) failed.push(`${result.viewport}: lab lane does not split hematology/chemistry categories`);
      if (desktopRequired && result.detailRowsMissingCategoryCount) failed.push(`${result.viewport}: ${result.detailRowsMissingCategoryCount} detail rows are missing category color classes`);
      if (desktopRequired && result.detailRowsWithoutColorCount) failed.push(`${result.viewport}: ${result.detailRowsWithoutColorCount} detail rows have no visible category color`);
      if (desktopRequired && !result.ipColorDistinctFromAeAndLab) failed.push(`${result.viewport}: IP lane color is not distinct from AE/LAB`);
      if (desktopRequired && result.overflowX) failed.push(`${result.viewport}: page horizontal overflow`);
      return failed;
    });
    if (failures.length) throw new Error(`Subject Timeline IP lane QC failed: ${failures.join("; ")}. Metrics: ${metricsPath}`);
    console.log(metricsPath);
  } finally {
    chrome.kill("SIGTERM");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
