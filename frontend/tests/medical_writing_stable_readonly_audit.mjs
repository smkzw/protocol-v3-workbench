import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(
  scriptDir,
  "../../records/active_slices/medical_writing_authoring_journey_20260715/browser_qc/stable_readonly_audit",
);
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9563);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const projects = ["proj_rux_03_002", "proj_mgk10_crswnp"];
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function json(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status}: ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 20000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try { return await json(url); } catch { await wait(200); }
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function createCdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  const listeners = new Map();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const callback = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) callback.reject(new Error(message.error.message));
      else callback.resolve(message.result || {});
      return;
    }
    for (const listener of listeners.get(message.method) || []) listener(message.params || {});
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
    on(method, callback) { listeners.set(method, [...(listeners.get(method) || []), callback]); },
    close() { ws.close(); },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result?.value;
}

async function waitForCondition(cdp, expression, timeoutMs = 45000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(cdp, expression)) return;
    await wait(200);
  }
  throw new Error(`Timed out waiting for ${expression}`);
}

async function selectProject(cdp, projectId) {
  await waitForCondition(cdp, `(() => {
    const select = document.querySelector('select[aria-label="选择临床研究项目"]');
    return Boolean(select && !select.disabled && Array.from(select.options).some((option) => option.value === ${JSON.stringify(projectId)}));
  })()`);
  await evaluate(cdp, `(() => {
    const select = document.querySelector('select[aria-label="选择临床研究项目"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
    setter.call(select, ${JSON.stringify(projectId)});
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
  await evaluate(cdp, `Array.from(document.querySelectorAll('.nav-item')).find((node) => node.textContent.trim() === '医学写作').click()`);
  await waitForCondition(cdp, `document.body.textContent.includes("研究方案文档编辑与AI修订")`);
  await waitForCondition(cdp, `Boolean(document.querySelector('.writing-title-actions'))`);
  await waitForCondition(cdp, `Boolean(
    document.querySelector('.working-copy-status-bar')
    || document.querySelector('.writing-pre-document-layout')
    || document.body.textContent.includes('真实方案文档会话读取失败')
  )`);
  await wait(400);
}

async function collectProject(cdp, projectId) {
  await selectProject(cdp, projectId);
  const titleActions = await evaluate(cdp, `Array.from(document.querySelectorAll('.writing-title-actions button')).map((node) => ({
    label: node.textContent.trim(),
    disabled: node.disabled,
    title: node.title,
  }))`);
  const workActions = await evaluate(cdp, `Array.from(document.querySelectorAll('.working-copy-actions button')).map((node) => ({
    label: node.textContent.trim(),
    disabled: node.disabled,
    title: node.title,
  }))`);
  await evaluate(cdp, `Array.from(document.querySelectorAll('.writing-title-actions button')).find((node) => node.textContent.includes('目录')).click()`);
  await waitForCondition(cdp, `Boolean(document.querySelector('.writing-document-map-drawer[aria-label="研究方案目录"]'))`);
  const documentMap = await evaluate(cdp, `(() => {
    const drawer = document.querySelector('.writing-document-map-drawer[aria-label="研究方案目录"]');
    const buttons = Array.from(drawer?.querySelectorAll('.writing-section-buttons button') || []);
    return {
      count: buttons.length,
      labels: buttons.map((node) => node.textContent.trim()),
      hasTemplateIdentity: Boolean(document.body.textContent.includes('ICH M11')),
    };
  })()`);
  const screenshot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  await writeFile(path.join(outputDir, `${projectId}_directory_1600x1000.png`), Buffer.from(screenshot.data, "base64"));
  let focusedSection = null;
  if (projectId === "proj_rux_03_002") {
    await evaluate(cdp, `Array.from(document.querySelectorAll('.writing-document-map-drawer .writing-section-buttons button')).find((node) => node.title === '未满足的临床需求').click()`);
    await waitForCondition(cdp, `document.querySelector('.rich-editor-meta strong')?.textContent.trim() === '未满足的临床需求'`);
    await wait(600);
    focusedSection = await evaluate(cdp, `({
      sectionTitle: document.querySelector('.rich-editor-meta strong')?.textContent.trim() || '',
      titleActions: Array.from(document.querySelectorAll('.writing-title-actions button')).map((node) => ({ label: node.textContent.trim(), disabled: node.disabled, title: node.title })),
      workActions: Array.from(document.querySelectorAll('.working-copy-actions button')).map((node) => ({ label: node.textContent.trim(), disabled: node.disabled, title: node.title })),
    })`);
    const focusedScreenshot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
    await writeFile(path.join(outputDir, `${projectId}_focused_section_1600x1000.png`), Buffer.from(focusedScreenshot.data, "base64"));
  } else {
    await evaluate(cdp, `document.querySelector('.writing-document-map-drawer[aria-label="研究方案目录"] .icon-button')?.click()`);
  }
  const bodyMessages = await evaluate(cdp, `Array.from(document.querySelectorAll('.approval-lock, .working-copy-message, .empty-state')).map((node) => node.textContent.trim()).filter(Boolean)`);
  return { projectId, titleActions, workActions, documentMap, focusedSection, bodyMessages };
}

function actionByLabel(actions, label) {
  return actions.find((action) => action.label.includes(label));
}

function validateProject(result, gateway) {
  const failures = [];
  const save = actionByLabel(result.workActions, "保存工作副本");
  const create = actionByLabel(result.workActions, "创建工作副本");
  const preview = actionByLabel(result.workActions, "预览 Word");
  const freeze = actionByLabel(result.titleActions, "确认并冻结")
    || actionByLabel(result.titleActions, "解除冻结");
  if (save && (!save.disabled || save.title !== "当前没有未保存修订")) {
    failures.push("首次进入时工作副本被误判为有未保存修订");
  }
  if (!save && !create) failures.push("既无工作副本操作，也无创建工作副本入口");
  if (!preview || preview.disabled) failures.push("无实际修改时草稿 Word 预览不可用");
  if (save && !freeze) failures.push("已有工作副本时缺少作者冻结操作");
  if (!save && freeze && !freeze.disabled) failures.push("尚无工作副本时冻结操作未被阻止");
  if (result.projectId === "proj_rux_03_002") {
    const focusedSave = actionByLabel(result.focusedSection?.workActions || [], "保存工作副本");
    const focusedAi = actionByLabel(result.focusedSection?.titleActions || [], "AI修订");
    if (!focusedSave?.disabled || focusedSave?.title !== "当前没有未保存修订") {
      failures.push("切换真实文本章节后工作副本被误判为有未保存修订");
    }
    if (gateway.configured && (!focusedAi || focusedAi.disabled)) {
      failures.push("独立AI已配置，但真实文本章节的AI修订入口不可用");
    }
    if (!gateway.configured && (!focusedAi?.disabled || !focusedAi?.title.includes("独立AI未配置"))) {
      failures.push("独立AI未配置时，真实文本章节未显示诚实的禁用状态");
    }
  }
  return failures;
}

async function main() {
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-stable-readonly-audit-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  let cdp;
  const nonGetRequests = [];
  const consoleErrors = [];
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    cdp = createCdp(targets.find((item) => item.type === "page").webSocketDebuggerUrl);
    await cdp.ready;
    cdp.on("Network.requestWillBeSent", (event) => {
      if (event.request.method !== "GET") nonGetRequests.push({ method: event.request.method, url: event.request.url });
    });
    cdp.on("Runtime.exceptionThrown", (event) => consoleErrors.push(event.exceptionDetails?.exception?.description || event.exceptionDetails?.text));
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);
    const gateway = await json(new URL("/api/ai-gateway/status", appUrl).toString());
    const results = [];
    for (const projectId of projects) results.push(await collectProject(cdp, projectId));
    const assertionFailures = results.flatMap((result) => (
      validateProject(result, gateway).map((message) => ({ projectId: result.projectId, message }))
    ));
    const report = {
      viewport: { width: 1600, height: 1000 },
      gateway: {
        configured: gateway.configured,
        provider: gateway.provider,
        model: gateway.model,
        deployment_profile: gateway.deployment_profile,
        disabled_reason: gateway.disabled_reason,
      },
      results,
      nonGetRequests,
      consoleErrors,
      assertionFailures,
    };
    report.passed = nonGetRequests.length === 0
      && consoleErrors.length === 0
      && assertionFailures.length === 0;
    await writeFile(path.join(outputDir, "medical_writing_stable_readonly_audit.json"), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    if (!report.passed) process.exitCode = 1;
  } finally {
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(400);
    await rm(userDataDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
