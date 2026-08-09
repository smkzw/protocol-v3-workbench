import { spawn } from "node:child_process";
import { access, copyFile, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const apiUrl = process.env.API_URL || "http://127.0.0.1:8910";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/visual_qc_20260707");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9355);
const projectRoot = process.env.WORKBENCH_PROJECT_ROOT || "/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台";
const inboxStorePath = process.env.WORKBENCH_INBOX_STORE || path.join(projectRoot, "runtime", "workbench_inbox_actions.jsonl");

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

async function fileExists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function backupAndClearInboxStore() {
  const backupPath = path.join(outputDir, "workbench_inbox_actions.backup.jsonl");
  const existed = await fileExists(inboxStorePath);
  if (existed) {
    await copyFile(inboxStorePath, backupPath);
    await rm(inboxStorePath, { force: true });
  }
  return { existed, backupPath };
}

async function restoreInboxStore(backup) {
  await rm(inboxStorePath, { force: true });
  if (backup?.existed) {
    await mkdir(path.dirname(inboxStorePath), { recursive: true });
    await copyFile(backup.backupPath, inboxStorePath);
  }
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

async function waitForExpression(cdp, expression, timeoutMs = 20000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(300);
  }
  throw new Error(`Timed out waiting for browser expression. Last value: ${JSON.stringify(lastValue)}`);
}

async function captureOverview(cdp, name, viewport) {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: viewport.width,
    height: viewport.height,
    deviceScaleFactor: 1,
    mobile: viewport.mobile,
  });
  const loaded = cdp.once("Page.loadEventFired");
  await cdp.send("Page.navigate", { url: appUrl });
  await loaded;
  await waitForExpression(cdp, `document.querySelectorAll(".workbench-inbox-panel .table-row").length > 0`, 25000);
  await wait(500);

  const metrics = await evaluate(cdp, `
    (() => {
      const text = document.body.textContent || "";
      const doc = document.documentElement;
      const body = document.body;
      const docW = Math.max(doc.scrollWidth, body.scrollWidth);
      const innerW = window.innerWidth;
      const expectedNav = ["项目总看板", "证据调研与方案设计", "入排审核", "医学监查", "数据分析与TFL", "医学写作", "安全信号与PV协同", "审批中心"];
      const unreadMetric = Array.from(document.querySelectorAll(".metric")).find((item) => item.textContent.includes("未读"));
      const inboxRows = Array.from(document.querySelectorAll(".workbench-inbox-panel .table-row"));
      const sourceHealthRows = document.querySelectorAll(".source-health-row").length;
      return {
        viewport: "${name}",
        innerW,
        docW,
        overflowX: docW > innerW + 1,
        navLabelsPresent: expectedNav.every((label) => text.includes(label)),
        hasWorkbenchInbox: text.includes("统一工作收件箱") && inboxRows.length > 0,
        hasSourceHealthPanel: text.includes("来源与数据健康") && (text.includes("来源已接入") || text.includes("重复登记") || text.includes("数据健康")),
        hasHandoffLedger: text.includes("跨模块交接台账"),
        hasDynamicTopMetrics: Boolean(unreadMetric) && Number(unreadMetric.querySelector("strong")?.textContent || "0") >= 0,
        hasApiDrivenItems: text.includes("AI阻断") && text.includes("TFL") && text.includes("安全信号与PV协同") && text.includes("入排审核"),
        hasBoundaryNote: text.includes("不自动形成正式批准结论") || text.includes("待医学确认"),
        hasAiGatewayPanel: text.includes("独立 AI 状态"),
        hasMissingProviderState: text.includes("未配置") && text.includes("语义 AI 任务") && text.includes("工作台执行模式"),
        hasInternalCodexLabel: text.includes("Codex"),
        hasForbiddenLifecycleText: /第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]|Stage\\s+[0-9]/.test(text),
        hasNonMedicalInterfaces: text.includes("EDC构建") || text.includes("临床运营") || text.includes("中心启动") || text.includes("数据采集系统"),
        hasForbiddenSurfaceText: text.includes("/Users/") || text.includes("Source Registry") || text.includes("医学监督"),
        hasForbiddenEdcWording: /\bEDC\b|EDC listing|EDC Data/.test(text),
        moduleRows: document.querySelectorAll(".module-row").length,
        inboxRows: inboxRows.length,
        sourceHealthRows,
        aiGatewayCards: document.querySelectorAll(".ai-gateway-card").length,
      };
    })()
  `);
  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: true,
  });
  const screenshotPath = path.join(outputDir, `overview_ai_gateway_${name}.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return { ...metrics, screenshotPath };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const inboxBackup = await backupAndClearInboxStore();
  const userDataDir = await mkdtemp(path.join(tmpdir(), "overview-ai-gateway-qc-"));
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

    const beforeApi = await requestJson(`${apiUrl}/api/projects/proj_mgk10_sar_demo/workbench-inbox`);
    if (!beforeApi.items?.length || beforeApi.unread_count < 1 || beforeApi.handoff_count < 1) {
      throw new Error(`Workbench inbox API baseline is not ready: ${JSON.stringify({
        items: beforeApi.items?.length || 0,
        unread_count: beforeApi.unread_count,
        handoff_count: beforeApi.handoff_count,
      })}`);
    }
    const beforeTypes = new Set((beforeApi.items || []).map((item) => item.item_type));
    for (const requiredType of ["source_ready", "data_health", "eligibility_action"]) {
      if (!beforeTypes.has(requiredType)) {
        throw new Error(`Workbench inbox API missing required item type ${requiredType}: ${JSON.stringify([...beforeTypes])}`);
      }
    }

    const results = [];
    results.push(await captureOverview(cdp, "desktop", { width: 1440, height: 1000, mobile: false }));
    const clickResult = await evaluate(cdp, `
      (() => {
        const row = document.querySelector(".workbench-inbox-panel .table-row.clickable");
        if (!row) return { clicked: false, text: "" };
        const text = row.textContent || "";
        row.click();
        return { clicked: true, text };
      })()
    `);
    await wait(900);
    const afterClickApi = await requestJson(`${apiUrl}/api/projects/proj_mgk10_sar_demo/workbench-inbox`);
    results.push(await captureOverview(cdp, "mobile", { width: 390, height: 1200, mobile: false }));
    cdp.close();

    const clickedItemStillExists = clickResult.clicked && afterClickApi.items.some((item) => clickResult.text.includes(item.title));
    const readStateUpdated = clickResult.clicked && afterClickApi.unread_count === beforeApi.unread_count - 1 && afterClickApi.total_open_count === beforeApi.total_open_count;
    const failed = results.filter((item) => (
      item.overflowX ||
      !item.navLabelsPresent ||
      !item.hasWorkbenchInbox ||
      !item.hasSourceHealthPanel ||
      !item.hasHandoffLedger ||
      !item.hasDynamicTopMetrics ||
      !item.hasApiDrivenItems ||
      !item.hasBoundaryNote ||
      !item.hasAiGatewayPanel ||
      !item.hasMissingProviderState ||
      item.hasInternalCodexLabel ||
      item.hasForbiddenLifecycleText ||
      item.hasNonMedicalInterfaces ||
      item.hasForbiddenSurfaceText ||
      item.hasForbiddenEdcWording ||
      item.moduleRows !== 8 ||
      item.inboxRows < 1 ||
      item.sourceHealthRows < 1 ||
      item.sourceHealthRows > 4 ||
      item.aiGatewayCards !== 1
    ));
    const metricsPath = path.join(outputDir, "overview_ai_gateway_qc.json");
    await writeFile(metricsPath, `${JSON.stringify({
      appUrl,
      apiUrl,
      beforeApi: {
        total_open_count: beforeApi.total_open_count,
        unread_count: beforeApi.unread_count,
        handoff_count: beforeApi.handoff_count,
        item_type_counts: Array.from(beforeTypes).sort(),
      },
      afterClickApi: {
        total_open_count: afterClickApi.total_open_count,
        unread_count: afterClickApi.unread_count,
        handoff_count: afterClickApi.handoff_count,
      },
      clickResult,
      readStateUpdated,
      clickedItemStillExists,
      results,
    }, null, 2)}\n`, "utf8");
    console.log(metricsPath);
    if (!readStateUpdated || !clickedItemStillExists) {
      throw new Error(`Workbench inbox read-state QC failed: ${JSON.stringify({ clickResult, readStateUpdated, clickedItemStillExists })}`);
    }
    if (failed.length) {
      throw new Error(`Overview AI gateway QC failed: ${JSON.stringify(failed)}`);
    }
  } finally {
    chrome.kill("SIGTERM");
    await restoreInboxStore(inboxBackup);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
