import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const apiUrl = process.env.API_URL || "http://127.0.0.1:8910";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/visual_qc_20260713/source_ledger");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9478);

const cases = [
  { projectId: "proj_my009_uc", projectCode: "MY009-UC", width: 1600, height: 1000 },
  { projectId: "proj_rux_03_002", projectCode: "RUX-03-002", width: 1920, height: 1080 },
];

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForJson(url, timeoutMs = 30000) {
  const started = Date.now();
  let error;
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`${response.status}: ${url}`);
      return await response.json();
    } catch (caught) {
      error = caught;
      await wait(200);
    }
  }
  throw error || new Error(`Timed out: ${url}`);
}

function createCdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const target = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) target.reject(new Error(message.error.message));
    else target.resolve(message.result || {});
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
    close() { ws.close(); },
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
    await wait(200);
  }
  throw new Error(`Timed out waiting for ${expression}`);
}

async function selectProject(cdp, projectId, projectCode) {
  await evaluate(cdp, `(() => {
    const select = document.querySelector('.project-switcher select');
    select.value = ${JSON.stringify(projectId)};
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await waitFor(cdp, `document.querySelector('.project-switcher select')?.value === ${JSON.stringify(projectId)} && document.querySelector('.topbar')?.textContent.includes(${JSON.stringify(projectCode)})`);
}

async function openLedger(cdp) {
  await evaluate(cdp, `(() => {
    const button = [...document.querySelectorAll('.nav-item')].find((item) => item.textContent.trim() === '来源台账');
    button?.click();
  })()`);
  await waitFor(cdp, `document.querySelector('.source-ledger-page') && document.querySelectorAll('.source-ledger-list > button').length > 0`);
}

async function inspectCase(cdp, config) {
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: config.width, height: config.height, deviceScaleFactor: 1, mobile: false });
  await selectProject(cdp, config.projectId, config.projectCode);
  await openLedger(cdp);

  await evaluate(cdp, `document.querySelector('.source-ledger-list > button')?.click()`);
  await waitFor(cdp, `document.querySelector('.source-ledger-detail h2')?.textContent.trim().length > 0`);
  const initial = await evaluate(cdp, `(() => {
    const text = document.body.textContent || '';
    const doc = document.documentElement;
    const pendingRow = [...document.querySelectorAll('.source-ledger-list > button')].find((row) => row.textContent.includes('待确认'));
    pendingRow?.click();
    return {
      rowCount: document.querySelectorAll('.source-ledger-list > button').length,
      checkCount: document.querySelectorAll('.source-ledger-checks > div').length,
      historyCount: document.querySelectorAll('.source-ledger-history > div').length,
      hasThreeAxes: text.includes('技术可读') && (text.includes('需确认') || text.includes('匹配')) && (text.includes('待确认') || text.includes('可使用') || text.includes('已确认沿用')),
      hasBoundary: text.includes('确认沿用只改变使用状态，不会把原警告或不一致改为匹配'),
      hasModuleLink: text.includes('前往模块'),
      overflowX: doc.scrollWidth > window.innerWidth + 1,
      leaksPath: text.includes('/Users/'),
      leaksHash: text.includes('file_sha256') || text.includes('expected_context_hash') || text.includes('content_hash'),
      securityScanCopy: text.includes('恶意软件扫描') || text.includes('安全性检查'),
      historicalHidden: ![...document.querySelectorAll('.source-ledger-list .tag')].some((tag) => tag.textContent.trim() === '历史版本'),
    };
  })()`);
  await wait(300);

  const confirmation = await evaluate(cdp, `(() => {
    const form = document.querySelector('.source-ledger-confirmation');
    if (!form) return { present: false };
    const button = form.querySelector('button.primary-button');
    const textarea = form.querySelector('textarea');
    const initiallyDisabled = button.disabled;
    textarea.value = '医学经理已对照当前项目原始资料，确认本次继续沿用。';
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    return new Promise((resolve) => setTimeout(() => resolve({
      present: true,
      initiallyDisabled,
      reasonOnlyDisabled: form.querySelector('button.primary-button').disabled,
      checkboxes: form.querySelectorAll('input[type="checkbox"]').length,
    }), 50));
  })()`);

  const filterWorked = await evaluate(cdp, `(() => {
    const select = document.querySelectorAll('.source-ledger-toolbar select')[1];
    if (!select) return false;
    select.value = 'requires_confirmation';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  await wait(100);
  const filteredRows = await evaluate(cdp, `document.querySelectorAll('.source-ledger-list > button').length`);
  await evaluate(cdp, `(() => {
    const select = document.querySelectorAll('.source-ledger-toolbar select')[1];
    select.value = 'all';
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await wait(100);

  const historyToggle = await evaluate(cdp, `(() => {
    const toggle = document.querySelector('.source-ledger-history-toggle input');
    if (!toggle) return { present: false };
    toggle.click();
    return new Promise((resolve) => setTimeout(() => resolve({
      present: true,
      rowCount: document.querySelectorAll('.source-ledger-list > button').length,
      historicalTagVisible: [...document.querySelectorAll('.source-ledger-list .tag')].some((tag) => tag.textContent.trim() === '历史版本'),
    }), 50));
  })()`);
  await evaluate(cdp, `document.querySelector('.source-ledger-history-toggle input')?.click()`);
  await wait(50);

  const screenshot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
  const screenshotPath = path.join(outputDir, `${config.projectId}_${config.width}x${config.height}.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return { ...config, initial, confirmation, filterWorked, filteredRows, historyToggle, screenshotPath };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  await waitForJson(`${apiUrl}/api/projects/proj_my009_uc/safety-pv/review-workbench?package_id=my009_uc_s1`, 90000);
  await waitForJson(`${apiUrl}/api/projects/proj_rux_03_002/tfl/review-workbench?package_id=rux_03_002`, 90000);
  const userDataDir = await mkdtemp(path.join(tmpdir(), "source-ledger-qc-"));
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
    if (!target?.webSocketDebuggerUrl) throw new Error("No Chrome page target available");
    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Page.navigate", { url: appUrl });
    await waitFor(cdp, `document.body.textContent.includes('项目总看板')`);
    const results = [];
    for (const config of cases) results.push(await inspectCase(cdp, config));
    cdp.close();

    const failures = [];
    for (const result of results) {
      if (result.initial.rowCount < 1) failures.push(`${result.projectId}:no-source-rows`);
      if (result.initial.checkCount < 1) failures.push(`${result.projectId}:no-validation-checks`);
      if (result.initial.historyCount < 1) failures.push(`${result.projectId}:no-history`);
      if (!result.initial.hasThreeAxes) failures.push(`${result.projectId}:three-axes-missing`);
      if (!result.initial.hasBoundary) failures.push(`${result.projectId}:override-boundary-missing`);
      if (!result.initial.hasModuleLink) failures.push(`${result.projectId}:module-link-missing`);
      if (result.initial.overflowX) failures.push(`${result.projectId}:horizontal-overflow`);
      if (result.initial.leaksPath || result.initial.leaksHash) failures.push(`${result.projectId}:source-secret-leak`);
      if (result.initial.securityScanCopy) failures.push(`${result.projectId}:security-scan-copy`);
      if (!result.initial.historicalHidden || !result.historyToggle.present) failures.push(`${result.projectId}:historical-version-default-failed`);
      if (result.projectId === 'proj_my009_uc' && (!result.historyToggle.historicalTagVisible || result.historyToggle.rowCount <= result.initial.rowCount)) failures.push(`${result.projectId}:historical-version-toggle-failed`);
      if (!result.filterWorked || result.filteredRows < 1) failures.push(`${result.projectId}:status-filter-failed`);
      if (result.confirmation.present && (!result.confirmation.initiallyDisabled || !result.confirmation.reasonOnlyDisabled || result.confirmation.checkboxes < 1)) failures.push(`${result.projectId}:confirmation-gate-failed`);
    }
    const metricsPath = path.join(outputDir, "source_ledger_qc.json");
    await writeFile(metricsPath, `${JSON.stringify({ appUrl, results, failures }, null, 2)}\n`);
    console.log(metricsPath);
    if (failures.length) throw new Error(`Source ledger QC failed: ${failures.join(', ')}`);
  } finally {
    chrome.kill("SIGTERM");
    await Promise.race([
      new Promise((resolve) => chrome.once("exit", resolve)),
      wait(2000),
    ]);
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        await rm(userDataDir, { recursive: true, force: true });
        break;
      } catch (error) {
        if (attempt === 2) throw error;
        await wait(300);
      }
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
