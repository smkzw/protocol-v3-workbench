import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/visual_qc_20260713/eligibility_source_admission");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9404);
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

async function waitFor(cdp, expression, timeoutMs = 90000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(cdp, expression)) return;
    await wait(250);
  }
  throw new Error(`Timed out waiting for ${expression}`);
}

async function clickByText(cdp, selector, text) {
  const clicked = await evaluate(cdp, `(() => {
    const item = Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find((node) => node.textContent.includes(${JSON.stringify(text)}));
    if (!item) return false;
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

async function openEligibilityProject(cdp, projectId) {
  await selectProject(cdp, projectId);
  await clickByText(cdp, ".nav-item", "入排审核");
  await waitFor(cdp, `document.querySelectorAll(".source-admission-card").length === 2`, 120000);
}

async function screenshot(cdp, filename) {
  await evaluate(cdp, "window.scrollTo(0, 0)");
  const result = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
  const target = path.join(outputDir, filename);
  await writeFile(target, Buffer.from(result.data, "base64"));
  return target;
}

async function metrics(cdp, projectId) {
  return evaluate(cdp, `(() => {
    const text = document.body.textContent || "";
    const doc = document.documentElement;
    const body = document.body;
    const cards = Array.from(document.querySelectorAll(".source-admission-card"));
    const lowerText = document.body.innerText.toLowerCase();
    const writeLabels = ["保存医学判断", "请求补证", "延期审阅"];
    const writeButtons = Array.from(document.querySelectorAll("button")).filter((button) => writeLabels.some((label) => button.textContent.includes(label)));
    return {
      projectId: document.querySelector('select[aria-label="选择临床研究项目"]')?.value,
      sourceCardCount: cards.length,
      hasProtocol: cards.some((card) => card.textContent.includes("研究方案")),
      hasBundle: cards.some((card) => card.textContent.includes("受试者资料包")),
      hasBundleBoundary: text.includes("目录及文件构成核验，不代表已完成逐文件医学内容核验"),
      contentWarningVisible: text.includes("需确认"),
      confirmedVisible: text.includes("已确认沿用"),
      readyVisible: text.includes("来源准入已就绪"),
      confirmSourceButtonCount: Array.from(document.querySelectorAll("button")).filter((button) => button.textContent.includes("确认该来源")).length,
      writeButtonsPresent: writeButtons.length,
      writeButtonsDisabled: writeButtons.length === 0 || writeButtons.every((button) => button.disabled),
      noPageOverflowX: Math.max(doc.scrollWidth, body.scrollWidth) <= window.innerWidth + 1,
      noPathOrHashLeak: !["/users/", "file://", "file_sha256", "expected_context_hash", "server_path"].some((token) => lowerText.includes(token)),
      noSecurityScanCopy: !/恶意软件|病毒扫描|安全扫描/.test(text),
      expectedProject: ${JSON.stringify(projectId)},
    };
  })()`);
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "eligibility-source-admission-qc-"));
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
    await openEligibilityProject(cdp, "proj_d001");
    await waitFor(cdp, `document.body.textContent.includes("来源准入未就绪")`);
    const d001Before = await metrics(cdp, "proj_d001");
    const d001BeforeScreenshot = await screenshot(cdp, "eligibility_d001_admission_before.png");
    if (d001Before.confirmSourceButtonCount !== 1 || !d001Before.hasProtocol || !d001Before.hasBundle || !d001Before.hasBundleBoundary) {
      throw new Error(`D001 source gate mismatch: ${JSON.stringify(d001Before)}`);
    }

    await clickByText(cdp, "button", "确认该来源");
    await waitFor(cdp, `document.body.textContent.includes("确认沿用不代表系统判定已转为匹配")`);
    const disabledInitially = await evaluate(cdp, `Array.from(document.querySelectorAll("button")).find((button) => button.textContent.trim() === "确认沿用")?.disabled`);
    await evaluate(cdp, `(() => {
      const textarea = document.querySelector(".source-admission-band .content-confirmation textarea");
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(textarea, "医学经理已核对目录及文件构成，确认属于D001项目并沿用。 ");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    })()`);
    await wait(100);
    const disabledAfterReason = await evaluate(cdp, `Array.from(document.querySelectorAll("button")).find((button) => button.textContent.trim() === "确认沿用")?.disabled`);
    await evaluate(cdp, `(() => { document.querySelectorAll(".source-admission-band .content-confirmation input[type=checkbox]").forEach((item) => item.click()); return true; })()`);
    await waitFor(cdp, `!Array.from(document.querySelectorAll("button")).find((button) => button.textContent.trim() === "确认沿用")?.disabled`);
    await clickByText(cdp, "button", "确认沿用");
    await waitFor(cdp, `document.body.textContent.includes("来源准入已就绪") && document.body.textContent.includes("已确认沿用")`, 120000);
    const d001After = await metrics(cdp, "proj_d001");
    const d001AfterScreenshot = await screenshot(cdp, "eligibility_d001_admission_after.png");

    await openEligibilityProject(cdp, "proj_my009_uc");
    await waitFor(cdp, `document.body.textContent.includes("来源准入未就绪")`, 120000);
    const my009 = await metrics(cdp, "proj_my009_uc");
    const my009Screenshot = await screenshot(cdp, "eligibility_my009_admission_before.png");
    const d001ReasonLeaked = await evaluate(cdp, `document.body.textContent.includes("确认属于D001项目并沿用")`);

    await openEligibilityProject(cdp, "proj_d001");
    await waitFor(cdp, `document.body.textContent.includes("来源准入已就绪")`, 120000);
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await wait(300);
    const d001Return1920 = await metrics(cdp, "proj_d001");
    const d001ReturnScreenshot = await screenshot(cdp, "eligibility_d001_admission_return_1920.png");

    const result = {
      appUrl,
      disabledInitially,
      disabledAfterReason,
      d001Before,
      d001After,
      my009,
      d001ReasonLeaked,
      d001Return1920,
      screenshots: { d001BeforeScreenshot, d001AfterScreenshot, my009Screenshot, d001ReturnScreenshot },
    };
    const failures = [];
    if (!disabledInitially || !disabledAfterReason) failures.push("confirmation-premature-enable");
    if (!d001After.readyVisible || !d001After.confirmedVisible || d001After.confirmSourceButtonCount !== 0) failures.push("d001-confirmation-not-persisted");
    if (my009.projectId !== "proj_my009_uc" || my009.confirmSourceButtonCount !== 1 || d001ReasonLeaked) failures.push("cross-project-state-leak");
    for (const [name, state] of Object.entries({ d001Before, d001After, my009, d001Return1920 })) {
      if (!state.noPageOverflowX || !state.noPathOrHashLeak || !state.noSecurityScanCopy) failures.push(`${name}-layout-or-privacy`);
    }
    await writeFile(path.join(outputDir, "eligibility_source_admission_qc.json"), `${JSON.stringify({ ...result, failures }, null, 2)}\n`, "utf8");
    if (failures.length) throw new Error(failures.join(", "));
    cdp.close();
  } finally {
    chrome.kill("SIGTERM");
    await wait(300);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch((error) => { console.error(error); process.exit(1); });
