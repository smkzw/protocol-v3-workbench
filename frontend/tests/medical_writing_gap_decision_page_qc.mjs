import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5180/output/medical-writing-gap-review-20260714/";
const outputDir = process.env.QC_OUTPUT_DIR || "output/playwright/medical_writing_gap_decision_page_20260714";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9401);
const viewports = [
  { width: 1280, height: 900 },
  { width: 1600, height: 1000 },
  { width: 1920, height: 1080 },
  { width: 2048, height: 1024 },
];

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function json(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status}: ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 10000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await json(url);
    } catch (error) {
      lastError = error;
      await wait(200);
    }
  }
  throw lastError || new Error(`Timed out: ${url}`);
}

function createCdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const callback = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) callback.reject(new Error(message.error.message));
    else callback.resolve(message.result || {});
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

async function waitFor(cdp, expression, timeoutMs = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const value = await evaluate(cdp, expression);
    if (value) return value;
    await wait(200);
  }
  throw new Error(`Condition timed out: ${expression}`);
}

async function setViewport(cdp, viewport) {
  await cdp.send("Emulation.setDeviceMetricsOverride", { ...viewport, deviceScaleFactor: 1, mobile: false });
  await evaluate(cdp, `window.scrollTo(0, 0)`);
  await wait(120);
}

async function capture(cdp, filename) {
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const outputPath = path.join(outputDir, filename);
  await writeFile(outputPath, Buffer.from(shot.data, "base64"));
  return outputPath;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const profile = await mkdtemp(path.join(tmpdir(), "medical-writing-gap-qc-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${profile}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });

  const report = { appUrl, viewports, failures: [], screenshots: {}, baseline: null, partialRestored: null, completed: null, restored: null };
  let cdp;
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    const target = targets.find((item) => item.type === "page");
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await setViewport(cdp, viewports[0]);
    await cdp.send("Page.navigate", { url: appUrl });
    await waitFor(cdp, `document.querySelectorAll('.decision-section').length === 8`);
    await waitFor(cdp, `document.querySelector('.brand img')?.complete === true`);

    report.baseline = await evaluate(cdp, `(() => {
      const doc = document.documentElement;
      const body = document.body;
      const logo = document.querySelector('.brand img');
      const headings = [...document.querySelectorAll('.decision-section h2')].map((node) => node.textContent.trim());
      return {
        title: document.title,
        sectionCount: headings.length,
        uniqueHeadingCount: new Set(headings).size,
        recommendedCount: document.querySelectorAll('.choice.recommended').length,
        radioCount: document.querySelectorAll('input[type=radio]').length,
        selectedCount: document.querySelectorAll('input[type=radio]:checked').length,
        summaryRows: document.querySelectorAll('#summary-list li').length,
        logoNaturalWidth: logo?.naturalWidth || 0,
        logoNaturalHeight: logo?.naturalHeight || 0,
        noOverflowX: Math.max(doc.scrollWidth, body.scrollWidth) <= window.innerWidth + 1,
        hasSitesBoundary: body.textContent.includes('完整生产系统暂不直接迁移'),
        hasStableWorkbenchLink: [...document.querySelectorAll('a')].some((a) => a.href === 'http://127.0.0.1:5174/'),
        submitDisabled: document.querySelector('#submit-decisions')?.disabled === true,
      };
    })()`);

    for (const viewport of viewports) {
      await setViewport(cdp, viewport);
      const key = `${viewport.width}x${viewport.height}`;
      report.screenshots[`baseline_${key}`] = await capture(cdp, `baseline_${key}.png`);
      const overflow = await evaluate(cdp, `Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) <= window.innerWidth + 1`);
      if (!overflow) report.failures.push(`horizontal overflow at ${key}`);
    }

    await setViewport(cdp, viewports[1]);
    await evaluate(cdp, `(() => {
      [...document.querySelectorAll('.choice.recommended input')].slice(0, 4).forEach((input) => input.click());
      const note = document.querySelector('#reviewer-note');
      note.value = '部分决策恢复测试：其余选项待医学负责人确认。';
      note.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
    await waitFor(cdp, `document.querySelector('#completion-count')?.textContent?.includes('4 / 8')`);
    await cdp.send("Page.reload", { ignoreCache: true });
    await waitFor(cdp, `document.querySelectorAll('.decision-section').length === 8`);
    await waitFor(cdp, `document.querySelector('#completion-count')?.textContent?.includes('4 / 8')`);
    report.partialRestored = await evaluate(cdp, `(() => ({
      selectedCount: document.querySelectorAll('input[type=radio]:checked').length,
      answeredSections: document.querySelectorAll('.decision-section.answered').length,
      submitDisabled: document.querySelector('#submit-decisions')?.disabled === true,
      note: document.querySelector('#reviewer-note')?.value,
    }))()`);
    report.screenshots.restored_partial_1920x1080 = await capture(cdp, "restored_partial_1920x1080.png");

    await evaluate(cdp, `(() => {
      document.querySelectorAll('.choice.recommended input').forEach((input) => input.click());
      const note = document.querySelector('#reviewer-note');
      note.value = '优先验证类风湿关节炎绿地方案和第二个真实项目；保留项目级术语锁。';
      note.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
    await waitFor(cdp, `document.querySelector('#completion-count')?.textContent?.includes('8 / 8')`);
    report.completed = await evaluate(cdp, `(() => ({
      selectedCount: document.querySelectorAll('input[type=radio]:checked').length,
      progress: document.querySelector('#progress-fill')?.style.width,
      topbarState: document.querySelector('#topbar-state')?.textContent,
      summaryDoneCount: document.querySelectorAll('[data-index-status].done').length,
      submitEnabled: document.querySelector('#submit-decisions')?.disabled === false,
      stored: JSON.parse(localStorage.getItem('cms-medical-writing-gap-decisions-v1') || '{}'),
      payload: buildPayload(),
    }))()`);
    report.screenshots.completed_1920x1080 = await capture(cdp, "completed_1920x1080.png");

    await cdp.send("Page.reload", { ignoreCache: true });
    await waitFor(cdp, `document.querySelectorAll('.decision-section').length === 8`);
    await waitFor(cdp, `document.querySelector('#completion-count')?.textContent?.includes('8 / 8')`);
    report.restored = await evaluate(cdp, `(() => ({
      selectedCount: document.querySelectorAll('input[type=radio]:checked').length,
      note: document.querySelector('#reviewer-note')?.value,
      summaryLabels: [...document.querySelectorAll('#summary-list b')].map((node) => node.textContent.trim()),
    }))()`);
    await evaluate(cdp, `document.querySelector('#d4')?.scrollIntoView({ block: 'start' })`);
    await wait(150);
    report.screenshots.restored_midpage_1920x1080 = await capture(cdp, "restored_midpage_1920x1080.png");

    const expected = {
      sectionCount: 8,
      uniqueHeadingCount: 8,
      recommendedCount: 8,
      radioCount: 24,
      summaryRows: 8,
      logoNaturalWidth: 273,
      logoNaturalHeight: 57,
    };
    Object.entries(expected).forEach(([key, value]) => {
      if (report.baseline[key] !== value) report.failures.push(`${key}: expected ${value}, received ${report.baseline[key]}`);
    });
    if (!report.baseline.noOverflowX) report.failures.push("baseline horizontal overflow");
    if (!report.baseline.hasSitesBoundary) report.failures.push("Sites boundary text missing");
    if (!report.baseline.hasStableWorkbenchLink) report.failures.push("stable workbench link missing");
    if (!report.baseline.submitDisabled) report.failures.push("submit button must be disabled before all decisions are complete");
    if (report.partialRestored.selectedCount !== 4 || report.partialRestored.answeredSections !== 4) report.failures.push("partial localStorage restoration failed");
    if (!report.partialRestored.submitDisabled) report.failures.push("submit must remain disabled for partial decisions");
    if (!report.partialRestored.note.includes("部分决策")) report.failures.push("partial reviewer note restoration failed");
    if (report.completed.selectedCount !== 8) report.failures.push("recommended selection did not complete all decisions");
    if (report.completed.progress !== "100%") report.failures.push(`progress expected 100%, received ${report.completed.progress}`);
    if (report.completed.summaryDoneCount !== 8) report.failures.push("decision index did not mark all choices done");
    if (!report.completed.submitEnabled) report.failures.push("submit button did not enable after all decisions were completed");
    if (report.restored.selectedCount !== 8) report.failures.push("localStorage restoration failed");
    if (!report.restored.note.includes("类风湿关节炎")) report.failures.push("reviewer note restoration failed");
  } finally {
    if (cdp) cdp.close();
    chrome.kill("SIGTERM");
    await wait(250);
    await rm(profile, { recursive: true, force: true });
  }

  const reportPath = path.join(outputDir, "medical_writing_gap_decision_page_qc.json");
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify({ reportPath, failures: report.failures, screenshots: report.screenshots }, null, 2));
  if (report.failures.length) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
