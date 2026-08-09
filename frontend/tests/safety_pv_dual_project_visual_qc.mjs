import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";


const chromePath = process.env.CHROME_PATH
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5182/";
const apiUrl = process.env.API_URL || "http://127.0.0.1:8912";
const outputDir = process.env.QC_OUTPUT_DIR
  || path.resolve(process.cwd(), "../records/active_slices/safety_pv_dual_project_fullchain_20260714/visual_qc");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9392);
const projects = [
  { projectId: "proj_rux_03_002", projectCode: "RUX-03-002" },
  { projectId: "proj_my009_uc", projectCode: "MY009-UC" },
];


const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));


async function requestJson(url) {
  const response = await fetch(url);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}; ${JSON.stringify(payload)}`);
  return payload;
}


async function waitForJson(url, timeoutMs = 120000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await requestJson(url);
    } catch (error) {
      lastError = error;
      await wait(250);
    }
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}


function createCdp(wsUrl, diagnostics) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
      diagnostics.consoleErrors.push(
        message.params.args.map((item) => item.value || item.description || "").join(" "),
      );
    }
    if (message.method === "Network.responseReceived" && message.params.response.status >= 400) {
      diagnostics.failedResponses.push({
        status: message.params.response.status,
        url: message.params.response.url,
      });
    }
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
    const detail = result.exceptionDetails.exception?.description
      || result.exceptionDetails.exception?.value
      || result.exceptionDetails.text;
    throw new Error(detail || "Runtime evaluation failed");
  }
  return result.result?.value;
}


async function waitForCondition(cdp, expression, timeoutMs = 60000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(250);
  }
  throw new Error(`Timed out waiting for condition: ${expression}; last=${JSON.stringify(lastValue)}`);
}


async function clickButton(cdp, label) {
  await waitForCondition(cdp, `
    Array.from(document.querySelectorAll("button")).some((button) =>
      (button.textContent || "").trim() === ${JSON.stringify(label)} && !button.disabled
    )
  `);
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) =>
        (item.textContent || "").trim() === ${JSON.stringify(label)} && !item.disabled
      );
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Enabled button not found: ${label}`);
}


async function setTextarea(cdp, value) {
  const changed = await evaluate(cdp, `
    (() => {
      const textarea = document.querySelector(".safety-review-comment textarea");
      if (!textarea) return false;
      const oldValue = textarea.value;
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      setter.call(textarea, ${JSON.stringify(value)});
      if (textarea._valueTracker) textarea._valueTracker.setValue(oldValue);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.scrollIntoView({ block: "center" });
      return true;
    })()
  `);
  if (!changed) throw new Error("Safety review textarea not found");
}


async function selectProject(cdp, projectId, projectCode) {
  const changed = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select || !Array.from(select.options).some((option) => option.value === ${JSON.stringify(projectId)})) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
      setter.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Project option not found: ${projectId}`);
  await waitForCondition(cdp, `
    document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)} &&
    (document.body.textContent || "").includes(${JSON.stringify(projectCode)})
  `);
}


async function setViewport(cdp, width, height) {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: false,
  });
}


async function screenshot(cdp, filename) {
  const result = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  });
  const filePath = path.join(outputDir, filename);
  await writeFile(filePath, Buffer.from(result.data, "base64"));
  return filePath;
}


async function safetyRiskMetrics(cdp) {
  return evaluate(cdp, `
    (() => {
      const root = document.documentElement;
      const body = document.body;
      const panel = document.querySelector(".safety-risk-projection");
      const headers = Array.from(panel?.querySelectorAll(".risk-checklist-header > button > span") || [])
        .map((item) => (item.textContent || "").trim());
      const rows = Array.from(panel?.querySelectorAll(".risk-checklist-row") || []);
      const clipped = Array.from(panel?.querySelectorAll("button, [role='cell'], strong, span") || [])
        .filter((item) => {
          const style = getComputedStyle(item);
          return item.clientWidth > 4
            && item.clientHeight > 4
            && style.position !== "absolute"
            && item.scrollWidth > item.clientWidth + 2
            && style.whiteSpace !== "normal";
        })
        .slice(0, 20)
        .map((item) => ({ text: (item.textContent || "").trim().slice(0, 80), className: item.className }));
      return {
        headers,
        rowCount: rows.length,
        filterCount: panel?.querySelectorAll(".risk-checklist-filters select, .risk-checklist-filters input").length || 0,
        sortableHeaderCount: panel?.querySelectorAll(".risk-checklist-header > button").length || 0,
        hasReadOnlyBoundary: (panel?.textContent || "").includes("同一风险编号、来源、状态和审计"),
        globalOverflowX: Math.max(root.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
        clipped,
      };
    })()
  `);
}


async function safetyRiskEvidenceMetrics(cdp) {
  return evaluate(cdp, `
    (() => {
      const dock = document.querySelector('.risk-evidence-dock[aria-label="风险证据工作区"]');
      const tabs = Array.from(dock?.querySelectorAll('.risk-evidence-tabs button') || [])
        .map((button) => (button.textContent || '').trim());
      const rect = dock?.getBoundingClientRect();
      return {
        tabs,
        dockWidth: rect ? Math.round(rect.width) : 0,
        dockHeight: rect ? Math.round(rect.height) : 0,
        dockRightGap: rect ? Math.round(window.innerWidth - rect.right) : null,
        bodyScrollable: Boolean(dock?.querySelector('.risk-evidence-dock-body')?.scrollHeight
          > dock?.querySelector('.risk-evidence-dock-body')?.clientHeight + 1),
      };
    })()
  `);
}


async function safetyDocumentMetrics(cdp) {
  return evaluate(cdp, `
    (() => {
      const root = document.documentElement;
      const body = document.body;
      const gridChildren = Array.from(document.querySelectorAll(".safety-review-grid > *"));
      const overlaps = [];
      for (let leftIndex = 0; leftIndex < gridChildren.length; leftIndex += 1) {
        const left = gridChildren[leftIndex].getBoundingClientRect();
        for (let rightIndex = leftIndex + 1; rightIndex < gridChildren.length; rightIndex += 1) {
          const right = gridChildren[rightIndex].getBoundingClientRect();
          const width = Math.min(left.right, right.right) - Math.max(left.left, right.left);
          const height = Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top);
          if (width > 1 && height > 1) overlaps.push([leftIndex, rightIndex, width, height]);
        }
      }
      const clipped = Array.from(document.querySelectorAll(
        ".safety-review-actions button, .safety-review-candidate-list button, .safety-source-facts > div, .safety-handoff-card"
      )).filter((item) => item.clientWidth > 0 && item.scrollWidth > item.clientWidth + 2)
        .slice(0, 20)
        .map((item) => ({ text: (item.textContent || "").trim().slice(0, 100), className: item.className }));
      const actionButtons = Array.from(document.querySelectorAll(".safety-review-actions button")).map((button) => ({
        label: (button.textContent || "").trim(),
        disabled: button.disabled,
        title: button.title,
      }));
      const reviewGrid = document.querySelector('.safety-review-grid');
      const reviewGridChildren = Array.from(reviewGrid?.children || []);
      const childWidths = reviewGridChildren.map((child) => Math.round(child.getBoundingClientRect().width));
      return {
        sourceFactCount: document.querySelectorAll(".safety-source-facts > div").length,
        locatorDisclosureCount: document.querySelectorAll(".safety-source-locators").length,
        monitoringHandoffCount: document.querySelectorAll(".safety-handoff-card.monitoring").length,
        staleMonitoringHandoffCount: document.querySelectorAll(".safety-handoff-card.monitoring.stale").length,
        handoffGateCount: document.querySelectorAll(".safety-handoff-gates .tag").length,
        auditRecordCount: document.querySelectorAll(".safety-review-record").length,
        candidateCount: document.querySelectorAll(".safety-review-candidate-list button").length,
        reviewGridChildCount: reviewGridChildren.length,
        reviewGridWidth: reviewGrid ? Math.round(reviewGrid.getBoundingClientRect().width) : 0,
        reviewGridChildWidths: childWidths,
        actionButtons,
        overlaps,
        clipped,
        globalOverflowX: Math.max(root.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
        leaksLocalPath: (body.textContent || "").includes("/Users/"),
        hasLifecycleNumber: /第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]/.test(body.textContent || ""),
      };
    })()
  `);
}


async function runProject(cdp, project, index) {
  await selectProject(cdp, project.projectId, project.projectCode);
  await clickButton(cdp, "安全信号与PV协同");
  await waitForCondition(cdp, `document.body.textContent.includes("安全性医学风险只读投影")`);
  await waitForCondition(cdp, `document.querySelectorAll(".safety-risk-projection .risk-checklist-row").length > 0`, 120000);
  const riskMetrics = await safetyRiskMetrics(cdp);
  const riskScreenshot = await screenshot(cdp, `${index + 1}_${project.projectId}_risk_2048x1024.png`);

  const openedRisk = await evaluate(cdp, `
    (() => {
      const row = document.querySelector(".safety-risk-projection .risk-checklist-row");
      if (!row) return false;
      row.scrollIntoView({ block: "center" });
      row.click();
      return true;
    })()
  `);
  if (!openedRisk) throw new Error(`${project.projectId}: no Safety/PV risk row available for deep link`);
  await waitForCondition(cdp, `Boolean(document.querySelector('.risk-evidence-dock[aria-label="风险证据工作区"]'))`);
  const riskEvidenceMetrics = await safetyRiskEvidenceMetrics(cdp);
  const deepLinkScreenshot = await screenshot(cdp, `${index + 1}_${project.projectId}_risk_evidence_dock.png`);

  await clickButton(cdp, "安全信号与PV协同");
  await waitForCondition(cdp, `document.body.textContent.includes("安全性医学风险只读投影")`);
  await clickButton(cdp, "PV文件医学审阅");
  await waitForCondition(cdp, `
    document.body.textContent.includes("医学意见与协同说明") &&
    document.querySelectorAll(".safety-source-facts > div").length > 0 &&
    document.querySelectorAll(".safety-review-actions button").length === 5
  `, 120000);

  await setTextarea(cdp, `${project.projectCode}浏览器QC：已核对当前来源版本、原始listing和PV资料文件。`);
  await clickButton(cdp, "保存医学意见");
  await waitForCondition(cdp, `
    Array.from(document.querySelectorAll(".safety-review-head-actions .tag")).some((tag) =>
      (tag.textContent || "").trim() === "医学已复核"
    ) &&
    !Array.from(document.querySelectorAll(".safety-review-actions button")).some((button) => button.textContent.includes("处理中"))
  `);
  await setTextarea(cdp, `${project.projectCode}浏览器QC：请PV确认报告边界和协作事项。`);
  await clickButton(cdp, "标记PV协同确认");
  await waitForCondition(cdp, `
    Array.from(document.querySelectorAll(".safety-review-head-actions .tag")).some((tag) =>
      (tag.textContent || "").trim() === "PV确认候选"
    ) &&
    document.querySelectorAll(".safety-handoff-card").length > 0 &&
    !Array.from(document.querySelectorAll(".safety-review-actions button")).some((button) => button.textContent.includes("处理中"))
  `);

  await setTextarea(cdp, `${project.projectCode}浏览器QC：撤回PV候选并关闭，保留完整审计。`);
  await setViewport(cdp, 1920, 1080);
  const documentMetrics = await safetyDocumentMetrics(cdp);
  const documentScreenshot = await screenshot(cdp, `${index + 1}_${project.projectId}_documents_1920x1080.png`);

  await clickButton(cdp, "撤回PV候选并关闭");
  await waitForCondition(cdp, `
    Array.from(document.querySelectorAll(".safety-review-head-actions .tag")).some((tag) =>
      (tag.textContent || "").trim() === "关闭为暂无需处理"
    ) &&
    !Array.from(document.querySelectorAll(".safety-review-actions button")).some((button) => button.textContent.includes("处理中"))
  `);
  await setTextarea(cdp, `${project.projectCode}浏览器QC完成，重置为待医学/PV确认。`);
  await clickButton(cdp, "重置处置");
  await waitForCondition(cdp, `
    Array.from(document.querySelectorAll(".safety-review-head-actions .tag")).some((tag) =>
      (tag.textContent || "").trim() === "待医学/PV确认"
    ) &&
    !Array.from(document.querySelectorAll(".safety-review-actions button")).some((button) => button.textContent.includes("处理中"))
  `);
  await setViewport(cdp, 2048, 1024);

  return {
    projectId: project.projectId,
    projectCode: project.projectCode,
    riskMetrics,
    riskEvidenceMetrics,
    documentMetrics,
    screenshots: { riskScreenshot, deepLinkScreenshot, documentScreenshot },
  };
}


function validateResult(result) {
  const failures = [];
  const requiredHeaders = ["受试者编号", "中心编号", "风险级别", "风险类别", "具体风险项", "当前处置", "更新时间"];
  if (JSON.stringify(result.riskMetrics.headers) !== JSON.stringify(requiredHeaders)) failures.push("risk-columns-mismatch");
  if (result.riskMetrics.rowCount < 1) failures.push("risk-rows-missing");
  if (result.riskMetrics.filterCount < 3) failures.push("risk-filters-incomplete");
  if (result.riskMetrics.sortableHeaderCount < 7) failures.push("risk-sorting-incomplete");
  if (!result.riskMetrics.hasReadOnlyBoundary) failures.push("read-only-boundary-missing");
  if (result.riskMetrics.globalOverflowX) failures.push("risk-global-horizontal-overflow");
  if (result.riskMetrics.clipped.length) failures.push(`risk-clipped:${JSON.stringify(result.riskMetrics.clipped)}`);
  const requiredEvidenceTabs = ["风险处置", "Subject Timeline", "Patient Profile", "AE/MH核查", "来源证据", "批次历史"];
  if (JSON.stringify(result.riskEvidenceMetrics.tabs) !== JSON.stringify(requiredEvidenceTabs)) {
    failures.push(`risk-evidence-tabs-mismatch:${JSON.stringify(result.riskEvidenceMetrics.tabs)}`);
  }
  if (result.riskEvidenceMetrics.dockWidth < 900 || result.riskEvidenceMetrics.dockRightGap < 0) {
    failures.push(`risk-evidence-dock-geometry:${JSON.stringify(result.riskEvidenceMetrics)}`);
  }
  if (result.documentMetrics.sourceFactCount < 1) failures.push("source-facts-missing");
  if (result.documentMetrics.locatorDisclosureCount !== 1) failures.push("locator-disclosure-missing");
  if (result.documentMetrics.monitoringHandoffCount < 1) failures.push("monitoring-handoff-missing");
  if (result.documentMetrics.staleMonitoringHandoffCount) failures.push("monitoring-handoff-stale");
  if (result.documentMetrics.handoffGateCount < 4) failures.push("handoff-gates-incomplete");
  if (result.documentMetrics.candidateCount < 1) failures.push("review-candidates-missing");
  if (result.documentMetrics.reviewGridChildCount !== 3) failures.push("review-grid-columns-missing");
  if (result.documentMetrics.reviewGridWidth < 1400 || result.documentMetrics.reviewGridChildWidths.some((width) => width < 250)) {
    failures.push(`review-grid-geometry:${JSON.stringify(result.documentMetrics.reviewGridChildWidths)}`);
  }
  if (result.documentMetrics.actionButtons.length !== 5) failures.push("review-actions-incomplete");
  if (!result.documentMetrics.actionButtons.some((item) => item.label === "撤回PV候选并关闭" && !item.disabled)) {
    failures.push("withdraw-and-close-action-unavailable");
  }
  if (result.documentMetrics.overlaps.length) failures.push(`review-grid-overlap:${JSON.stringify(result.documentMetrics.overlaps)}`);
  if (result.documentMetrics.clipped.length) failures.push(`review-content-clipped:${JSON.stringify(result.documentMetrics.clipped)}`);
  if (result.documentMetrics.globalOverflowX) failures.push("documents-global-horizontal-overflow");
  if (result.documentMetrics.leaksLocalPath) failures.push("local-path-leak");
  if (result.documentMetrics.hasLifecycleNumber) failures.push("forbidden-lifecycle-number");
  return failures;
}


async function main() {
  await mkdir(outputDir, { recursive: true });
  await waitForJson(`${apiUrl}/api/health`);
  await waitForJson(appUrl);
  for (const project of projects) {
    const state = await requestJson(`${apiUrl}/api/projects/${project.projectId}/safety-pv/review-workbench`);
    if (state.current_status !== "待医学/PV确认") {
      throw new Error(`${project.projectId}: visual QC requires reset state, got ${state.current_status}`);
    }
  }

  const userDataDir = await mkdtemp(path.join(tmpdir(), "safety-pv-dual-visual-qc-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--window-size=2048,1024",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  const diagnostics = { consoleErrors: [], failedResponses: [] };
  const report = {
    appUrl,
    apiUrl,
    browser: "Google Chrome headless via CDP",
    desktopViewports: [{ width: 2048, height: 1024 }, { width: 1920, height: 1080 }],
    results: [],
    diagnostics,
    failures: [],
  };
  let cdp;
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    const target = targets.find((item) => item.type === "page");
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Google Chrome page target found");
    cdp = createCdp(target.webSocketDebuggerUrl, diagnostics);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");
    await setViewport(cdp, 2048, 1024);
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`);

    for (let index = 0; index < projects.length; index += 1) {
      try {
        const result = await runProject(cdp, projects[index], index);
        result.failures = validateResult(result);
        report.results.push(result);
        report.failures.push(...result.failures.map((failure) => `${result.projectId}:${failure}`));
      } catch (error) {
        const failureScreenshot = await screenshot(cdp, `${index + 1}_${projects[index].projectId}_failure.png`).catch(() => "");
        report.results.push({ projectId: projects[index].projectId, error: error.message, failureScreenshot });
        report.failures.push(`${projects[index].projectId}:${error.message}`);
      }
    }
    if (diagnostics.consoleErrors.length) report.failures.push(`console-errors:${diagnostics.consoleErrors.join(" | ")}`);
    if (diagnostics.failedResponses.length) report.failures.push(`failed-responses:${JSON.stringify(diagnostics.failedResponses)}`);
  } finally {
    cdp?.close();
    if (chrome.exitCode === null) {
      chrome.kill("SIGTERM");
      await wait(1000);
    }
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
    const reportPath = path.join(outputDir, "safety_pv_dual_project_visual_qc.json");
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    console.log(reportPath);
  }
  if (report.failures.length) throw new Error(report.failures.join("; "));
}


main().catch((error) => {
  console.error(error);
  process.exit(1);
});
