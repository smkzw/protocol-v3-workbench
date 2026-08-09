import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/visual_qc_20260713/tfl_safety_source_admission");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9412);
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function requestJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status}: ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 10000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try { return await requestJson(url); } catch (error) { lastError = error; await wait(150); }
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

async function waitFor(cdp, expression, timeoutMs = 120000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(cdp, expression)) return;
    await wait(250);
  }
  throw new Error(`Timed out waiting for ${expression}`);
}

async function clickExact(cdp, selector, text) {
  const clicked = await evaluate(cdp, `(() => {
    const item = Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find((node) => node.textContent.trim() === ${JSON.stringify(text)});
    if (!item) return false;
    item.scrollIntoView({ block: "center" });
    item.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Missing ${selector}: ${text}`);
}

async function selectProject(cdp, projectId) {
  const changed = await evaluate(cdp, `(() => {
    const select = document.querySelector('select[aria-label="选择临床研究项目"]');
    if (!select) return false;
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, ${JSON.stringify(projectId)});
    select.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error(`Missing project switcher: ${projectId}`);
  await waitFor(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function openModule(cdp, projectId, navLabel, expectedSourceCount) {
  await selectProject(cdp, projectId);
  await clickExact(cdp, ".nav-item", navLabel);
  await waitFor(cdp, `document.querySelectorAll(".module-source-admission-source").length === ${expectedSourceCount}`);
}

async function screenshot(cdp, filename) {
  const element = await evaluate(cdp, `(() => {
    const node = document.querySelector(".module-source-admission");
    if (!node) return false;
    node.scrollIntoView({ block: "start" });
    return true;
  })()`);
  if (!element) throw new Error("Source admission band missing");
  await wait(150);
  const result = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
  const target = path.join(outputDir, filename);
  await writeFile(target, Buffer.from(result.data, "base64"));
  return target;
}

async function metrics(cdp, protectedActionLabel) {
  return evaluate(cdp, `(() => {
    const text = document.body.innerText;
    const lower = text.toLowerCase();
    const doc = document.documentElement;
    const body = document.body;
    const protectedButton = Array.from(document.querySelectorAll("button")).find((button) => button.textContent.trim() === ${JSON.stringify(protectedActionLabel)});
    return {
      sourceCount: document.querySelectorAll(".module-source-admission-source").length,
      confirmSourceCount: Array.from(document.querySelectorAll("button")).filter((button) => button.textContent.trim() === "确认该来源").length,
      warningVisible: text.includes("需确认") || text.includes("不一致"),
      confirmedVisible: text.includes("已确认沿用"),
      readyVisible: text.includes("可进行医学审阅"),
      protectedButtonDisabled: protectedButton ? protectedButton.disabled : null,
      noPageOverflowX: Math.max(doc.scrollWidth, body.scrollWidth) <= window.innerWidth + 1,
      noPathOrHashLeak: !["/users/", "file://", "file_sha256", "expected_context_hash", "server_path", "朗来项目资料/", "康哲项目资料/"].some((token) => lower.includes(token)),
      noSecurityScanCopy: !/恶意软件|病毒扫描|安全扫描/.test(text),
    };
  })()`);
}

async function confirmFirstSource(cdp, reason) {
  const beforeCount = await evaluate(cdp, `Array.from(document.querySelectorAll("button")).filter((button) => button.textContent.trim() === "确认该来源").length`);
  await clickExact(cdp, "button", "确认该来源");
  await waitFor(cdp, `Boolean(document.querySelector(".module-source-confirmation"))`);
  const initiallyDisabled = await evaluate(cdp, `Array.from(document.querySelectorAll("button")).find((button) => button.textContent.trim() === "确认沿用")?.disabled`);
  await evaluate(cdp, `(() => {
    const textarea = document.querySelector(".module-source-confirmation textarea");
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(textarea, ${JSON.stringify(reason)});
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  })()`);
  const reasonOnlyDisabled = await evaluate(cdp, `Array.from(document.querySelectorAll("button")).find((button) => button.textContent.trim() === "确认沿用")?.disabled`);
  await evaluate(cdp, `(() => { document.querySelectorAll(".module-source-confirmation input[type=checkbox]").forEach((item) => item.click()); return true; })()`);
  await waitFor(cdp, `!Array.from(document.querySelectorAll("button")).find((button) => button.textContent.trim() === "确认沿用")?.disabled`);
  await clickExact(cdp, "button", "确认沿用");
  await waitFor(cdp, `Array.from(document.querySelectorAll("button")).filter((button) => button.textContent.trim() === "确认该来源").length < ${beforeCount}`);
  return { initiallyDisabled, reasonOnlyDisabled };
}

async function fillComment(cdp, selector, value) {
  await evaluate(cdp, `(() => {
    const textarea = document.querySelector(${JSON.stringify(selector)});
    if (!textarea) return false;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(textarea, ${JSON.stringify(value)});
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  })()`);
  await wait(100);
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "tfl-safety-source-admission-qc-"));
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
    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitFor(cdp, `document.body.textContent.includes("项目总看板")`);

    await openModule(cdp, "proj_rux_03_002", "数据分析与TFL", 2);
    const tflBefore = await metrics(cdp, "标记医学已审阅");
    const tflBeforeScreenshot = await screenshot(cdp, "tfl_rux_admission_before_1600.png");
    const tflConfirmChecks = [];
    while ((await metrics(cdp, "标记医学已审阅")).confirmSourceCount > 0) {
      tflConfirmChecks.push(await confirmFirstSource(cdp, "医学经理已核对当前数据集与TFL输出包，确认属于RUX-03-002并沿用。"));
    }
    await fillComment(cdp, ".tfl-review-comment textarea", "已基于当前来源版本完成医学审阅。 ");
    const tflAfter = await metrics(cdp, "标记医学已审阅");
    const tflAfterScreenshot = await screenshot(cdp, "tfl_rux_admission_after_1600.png");

    await openModule(cdp, "proj_my008_pnh_3_01", "数据分析与TFL", 2);
    const tflMy008 = await metrics(cdp, "标记医学已审阅");

    await openModule(cdp, "proj_my009_uc", "安全信号与PV协同", 3);
    const safetyBefore = await metrics(cdp, "保存医学意见");
    const safetyBeforeScreenshot = await screenshot(cdp, "safety_my009_admission_before_1600.png");
    const safetyConfirmChecks = [];
    while ((await metrics(cdp, "保存医学意见")).confirmSourceCount > 0) {
      safetyConfirmChecks.push(await confirmFirstSource(cdp, "医学经理已核对当前安全性listing和资料包，确认属于MY009-UC-2-01并沿用。"));
    }
    await fillComment(cdp, ".safety-review-comment textarea", "已基于当前来源版本完成安全性医学复核。 ");
    const safetyAfter = await metrics(cdp, "保存医学意见");
    const safetyAfterScreenshot = await screenshot(cdp, "safety_my009_admission_after_1600.png");

    await openModule(cdp, "proj_rux_03_002", "安全信号与PV协同", 2);
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await wait(200);
    const safetyRux = await metrics(cdp, "保存医学意见");
    const safetyRuxScreenshot = await screenshot(cdp, "safety_rux_admission_before_1920.png");

    const states = { tflBefore, tflAfter, tflMy008, safetyBefore, safetyAfter, safetyRux };
    const failures = [];
    if (tflBefore.sourceCount !== 2 || !tflBefore.protectedButtonDisabled || tflBefore.confirmSourceCount !== 2) failures.push("tfl-before-gate");
    if (!tflAfter.readyVisible || tflAfter.protectedButtonDisabled || !tflAfter.confirmedVisible) failures.push("tfl-after-confirmation");
    if (tflMy008.confirmSourceCount !== 2 || !tflMy008.protectedButtonDisabled) failures.push("tfl-project-isolation");
    if (safetyBefore.sourceCount !== 3 || safetyBefore.confirmSourceCount !== 2 || !safetyBefore.protectedButtonDisabled) failures.push("safety-before-gate");
    if (!safetyAfter.readyVisible || safetyAfter.protectedButtonDisabled || !safetyAfter.confirmedVisible) failures.push("safety-after-confirmation");
    if (safetyRux.sourceCount !== 2 || safetyRux.confirmSourceCount !== 2 || !safetyRux.protectedButtonDisabled) failures.push("safety-project-isolation");
    for (const [name, state] of Object.entries(states)) {
      if (!state.noPageOverflowX || !state.noPathOrHashLeak || !state.noSecurityScanCopy) failures.push(`${name}-layout-or-privacy`);
    }
    for (const check of [...tflConfirmChecks, ...safetyConfirmChecks]) {
      if (!check.initiallyDisabled || !check.reasonOnlyDisabled) failures.push("confirmation-premature-enable");
    }
    const result = {
      appUrl,
      states,
      tflConfirmChecks,
      safetyConfirmChecks,
      screenshots: { tflBeforeScreenshot, tflAfterScreenshot, safetyBeforeScreenshot, safetyAfterScreenshot, safetyRuxScreenshot },
      failures,
    };
    await writeFile(path.join(outputDir, "tfl_safety_source_admission_qc.json"), `${JSON.stringify(result, null, 2)}\n`, "utf8");
    if (failures.length) throw new Error(failures.join(", "));
    cdp.close();
  } finally {
    chrome.kill("SIGTERM");
    await wait(300);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch((error) => { console.error(error); process.exit(1); });
