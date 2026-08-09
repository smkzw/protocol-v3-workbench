import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(
  scriptDir,
  "../../records/active_slices/medical_writing_content_quality_20260714/browser_qc",
);
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9396);
const viewport = { width: 2048, height: 1024, deviceScaleFactor: 1, mobile: false };
const projects = [
  { projectId: "proj_rux_03_002", projectCode: "RUX-03-002", expectedFindings: 1 },
  { projectId: "proj_d001", projectCode: "CMS-D001", expectedFindings: 0 },
  { projectId: "proj_my008_pnh_3_01", projectCode: "MY008211A-PNH-3-01", expectedFindings: 0 },
];

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function requestJson(url) {
  const response = await fetch(url);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return payload;
}

async function waitForJson(url, timeoutMs = 20000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await requestJson(url);
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
  const ready = new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const callback = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) callback.reject(new Error(message.error.message));
    else callback.resolve(message.result || {});
  });
  return {
    ready,
    send(method, params = {}) {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ id, method, params }));
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
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Runtime.evaluate failed");
  }
  return result.result?.value;
}

async function waitForCondition(cdp, expression, timeoutMs = 45000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(200);
  }
  throw new Error(`Timed out waiting for condition: ${expression}; last=${JSON.stringify(lastValue)}`);
}

async function clickMatching(cdp, selector, label, exact = true) {
  const clicked = await evaluate(cdp, `
    (() => {
      const node = Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find((item) => {
        const text = (item.textContent || "").trim();
        return ${exact ? `text === ${JSON.stringify(label)}` : `text.includes(${JSON.stringify(label)})`} && !item.disabled;
      });
      if (!node) return false;
      node.scrollIntoView({ block: "center", inline: "nearest" });
      node.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Enabled element not found: ${selector}/${label}`);
}

async function selectProject(cdp, projectId) {
  const changed = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select || !Array.from(select.options).some((option) => option.value === ${JSON.stringify(projectId)})) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Project switch failed: ${projectId}`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function openWriting(cdp, project) {
  await selectProject(cdp, project.projectId);
  await clickMatching(cdp, ".nav-item", "医学写作");
  await waitForCondition(cdp, `document.body.textContent.includes("研究方案文档编辑与AI修订")`);
  await waitForCondition(cdp, `document.querySelector(".working-copy-status-bar") && !document.querySelector(".working-copy-revision")?.textContent.includes("读取中")`);
  await waitForCondition(cdp, `Boolean(document.querySelector(".protocol-editor .ProseMirror"))`);
  await waitForCondition(cdp, `!document.querySelector(".content-quality-trigger")?.textContent.includes("…")`);
}

async function selectSection(cdp, projectId, sectionId) {
  const session = await requestJson(new URL(`/api/projects/${projectId}/medical-writing/document-session`, appUrl));
  const index = session.sections.findIndex((section) => section.section_id === sectionId);
  if (index < 0) throw new Error(`Section not found in document session: ${sectionId}`);
  await waitForCondition(cdp, `document.querySelectorAll(".writing-section-buttons > button").length > ${index}`);
  await evaluate(cdp, `document.querySelectorAll(".writing-section-buttons > button")[${index}].click()`);
  await waitForCondition(cdp, `document.querySelectorAll(".writing-section-buttons > button")[${index}].classList.contains("active")`);
}

async function setDispositionForm(cdp, reason, acknowledged) {
  const changed = await evaluate(cdp, `
    (() => {
      const textarea = document.querySelector(".writing-content-disposition-form textarea");
      const checkbox = document.querySelector(".writing-content-acknowledgement input");
      if (!textarea || !checkbox) return false;
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(textarea, ${JSON.stringify(reason)});
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      if (checkbox.checked !== ${acknowledged}) checkbox.click();
      return true;
    })()
  `);
  if (!changed) throw new Error("Content disposition form not available");
}

async function capture(cdp, filename) {
  await evaluate(cdp, `new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
  await wait(500);
  await cdp.send("Page.bringToFront");
  const screenshot = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(path.join(outputDir, filename), Buffer.from(screenshot.data, "base64"));
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-content-quality-qc-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "about:blank",
  ], { stdio: "ignore" });
  let cdp;
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const target = await requestJson(`http://127.0.0.1:${debugPort}/json/new?${encodeURIComponent(appUrl)}`, { method: "PUT" }).catch(async () => {
      const targets = await requestJson(`http://127.0.0.1:${debugPort}/json`);
      return targets.find((item) => item.type === "page");
    });
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", viewport);
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`);

    const apiBaseline = {};
    for (const project of projects) {
      const quality = await requestJson(new URL(`/api/projects/${project.projectId}/medical-writing/content-quality`, appUrl));
      apiBaseline[project.projectId] = {
        findingCount: quality.finding_count,
        blockingCount: quality.approval_blocking_count,
      };
      if (quality.finding_count !== project.expectedFindings) {
        throw new Error(`${project.projectId}: expected ${project.expectedFindings} findings, got ${quality.finding_count}`);
      }
    }

    const ruxQuality = await requestJson(new URL("/api/projects/proj_rux_03_002/medical-writing/content-quality", appUrl));
    const ruxFinding = ruxQuality.findings[0];
    if (!ruxFinding || ruxFinding.source_text !== "对于研究中具有生育能力的女性受试者：<0}") {
      throw new Error(`RUX exact source text mismatch: ${JSON.stringify(ruxFinding?.source_text)}`);
    }
    await openWriting(cdp, projects[0]);
    await selectSection(cdp, projects[0].projectId, ruxFinding.section_id);
    await waitForCondition(cdp, `document.querySelector(".content-quality-trigger")?.textContent.includes("内容核查 1")`);
    await clickMatching(cdp, ".content-quality-trigger", "内容核查", false);
    await waitForCondition(cdp, `document.querySelector('.writing-content-quality-dock mark')?.textContent === "<0}"`);

    const ruxMetrics = await evaluate(cdp, `
      (() => {
        const dock = document.querySelector(".writing-content-quality-dock");
        const evidence = document.querySelector(".writing-content-primary-evidence");
        const trace = document.querySelector(".writing-content-traceability");
        const rect = dock?.getBoundingClientRect();
        const text = evidence?.querySelector("blockquote")?.textContent || "";
        return {
          exactSourceVisible: text === "对于研究中具有生育能力的女性受试者：<0}",
          matchedText: evidence?.querySelector("mark")?.textContent || "",
          sourceBeforeLocator: Boolean(evidence && trace && (evidence.compareDocumentPosition(trace) & Node.DOCUMENT_POSITION_FOLLOWING)),
          traceCollapsed: trace ? !trace.open : false,
          noViewportOverflow: document.documentElement.scrollWidth <= window.innerWidth,
          dock: rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height, right: rect.right, bottom: rect.bottom } : null,
          viewport: { width: window.innerWidth, height: window.innerHeight },
        };
      })()
    `);
    if (!ruxMetrics.exactSourceVisible || ruxMetrics.matchedText !== "<0}" || !ruxMetrics.sourceBeforeLocator || !ruxMetrics.traceCollapsed) {
      throw new Error(`RUX source-first UI contract failed: ${JSON.stringify(ruxMetrics)}`);
    }
    if (!ruxMetrics.noViewportOverflow || !ruxMetrics.dock || ruxMetrics.dock.right > ruxMetrics.viewport.width + 1 || ruxMetrics.dock.bottom > ruxMetrics.viewport.height + 1) {
      throw new Error(`RUX dock geometry failed: ${JSON.stringify(ruxMetrics)}`);
    }
    await capture(cdp, "rux_source_content_open_2048x1024.png");

    if (ruxFinding.disposition_status !== "open") {
      await setDispositionForm(cdp, "浏览器回归前恢复开放状态并保留审计记录", false);
      await clickMatching(cdp, ".writing-content-disposition-actions button", "撤销处置");
      await waitForCondition(cdp, `document.querySelector(".writing-content-primary-evidence .tag")?.textContent.includes("待医学处置")`);
    }
    await setDispositionForm(cdp, "已核对原始方案完整文本，确认本次仅沿用源文档真实内容", true);
    await clickMatching(cdp, ".writing-content-disposition-actions button", "确认沿用");
    await waitForCondition(cdp, `document.querySelector(".writing-content-primary-evidence .tag")?.textContent.includes("已确认沿用")`);
    const confirmedQuality = await requestJson(new URL("/api/projects/proj_rux_03_002/medical-writing/content-quality", appUrl));
    if (confirmedQuality.approval_blocking_count !== 0 || confirmedQuality.confirmed_count !== 1) {
      throw new Error(`RUX confirmation did not clear blocker: ${JSON.stringify(confirmedQuality)}`);
    }
    await capture(cdp, "rux_source_content_confirmed_2048x1024.png");

    await setDispositionForm(cdp, "浏览器回归完成后恢复开放状态以继续验证正式批准阻断", false);
    await clickMatching(cdp, ".writing-content-disposition-actions button", "撤销处置");
    await waitForCondition(cdp, `document.querySelector(".writing-content-primary-evidence .tag")?.textContent.includes("待医学处置")`);
    const reopenedQuality = await requestJson(new URL("/api/projects/proj_rux_03_002/medical-writing/content-quality", appUrl));
    if (reopenedQuality.approval_blocking_count !== 1 || reopenedQuality.open_count !== 1) {
      throw new Error(`RUX finding was not restored to open state: ${JSON.stringify(reopenedQuality)}`);
    }

    const zeroFindingUi = {};
    for (const project of projects.slice(1)) {
      await openWriting(cdp, project);
      await waitForCondition(cdp, `document.querySelector(".content-quality-trigger")?.textContent.includes("内容核查 0")`);
      await clickMatching(cdp, ".content-quality-trigger", "内容核查", false);
      await waitForCondition(cdp, `document.querySelector(".writing-content-quality-clear")?.textContent.includes("当前章节未发现")`);
      zeroFindingUi[project.projectId] = await evaluate(cdp, `({
        trigger: document.querySelector(".content-quality-trigger")?.textContent.trim() || "",
        clearText: document.querySelector(".writing-content-quality-clear")?.textContent.trim() || "",
        traceCount: document.querySelectorAll(".writing-content-traceability").length,
        noViewportOverflow: document.documentElement.scrollWidth <= window.innerWidth,
      })`);
      if (!zeroFindingUi[project.projectId].noViewportOverflow || zeroFindingUi[project.projectId].traceCount !== 0) {
        throw new Error(`${project.projectId}: zero-finding UI contract failed: ${JSON.stringify(zeroFindingUi[project.projectId])}`);
      }
      await capture(cdp, `${project.projectId}_content_quality_clear_2048x1024.png`);
      await clickMatching(cdp, 'button[aria-label="关闭源内容核查"]', "", true);
    }

    const report = {
      passed: true,
      appUrl,
      viewport,
      apiBaseline,
      rux: {
        findingId: ruxFinding.finding_id,
        exactSourceText: ruxFinding.source_text,
        locator: ruxFinding.source_locator,
        metrics: ruxMetrics,
        confirmedThenReopened: true,
      },
      zeroFindingUi,
      screenshots: [
        "rux_source_content_open_2048x1024.png",
        "rux_source_content_confirmed_2048x1024.png",
        "proj_d001_content_quality_clear_2048x1024.png",
        "proj_my008_pnh_3_01_content_quality_clear_2048x1024.png",
      ],
    };
    await writeFile(path.join(outputDir, "medical_writing_content_quality_qc.json"), `${JSON.stringify(report, null, 2)}\n`);
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } finally {
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(300);
    await rm(userDataDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
