import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const outputDir = process.env.QC_OUTPUT_DIR || "records/visual_qc_20260712/medical_writing_reference_approved";
const projectId = process.env.QC_PROJECT_ID || "proj_my008_pnh_3_01";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9393);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForJson(url) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return response.json();
    } catch {}
    await wait(200);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function client(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let id = 1;
  const pending = new Map();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const handler = pending.get(message.id);
    if (!handler) return;
    pending.delete(message.id);
    if (message.error) handler.reject(new Error(message.error.message));
    else handler.resolve(message.result || {});
  });
  return {
    ready: new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", reject, { once: true });
    }),
    send(method, params = {}) {
      const requestId = id++;
      ws.send(JSON.stringify({ id: requestId, method, params }));
      return new Promise((resolve, reject) => pending.set(requestId, { resolve, reject }));
    },
    close: () => ws.close(),
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
    const result = await evaluate(cdp, expression);
    if (result) return result;
    await wait(250);
  }
  throw new Error(`Timed out: ${expression}`);
}

async function clickText(cdp, selector, text) {
  const clicked = await evaluate(cdp, `(() => {
    const item = Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find((element) => (element.textContent || "").includes(${JSON.stringify(text)}));
    if (!item) return false;
    item.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Missing control: ${text}`);
}

async function screenshot(cdp, name) {
  const result = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const target = path.resolve(outputDir, name);
  await writeFile(target, Buffer.from(result.data, "base64"));
  return target;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "wref-approved-qc-"));
  const chrome = spawn(chromePath, ["--headless=new", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${userDataDir}`, "--no-first-run", "--no-default-browser-check", "about:blank"], { stdio: "ignore" });
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const target = (await waitForJson(`http://127.0.0.1:${debugPort}/json/list`)).find((item) => item.type === "page");
    const cdp = client(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitFor(cdp, `document.body.textContent.includes("项目总看板")`);
    await evaluate(cdp, `(() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
      setter.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
    })()`);
    await clickText(cdp, "button", "医学写作");
    await waitFor(cdp, `document.body.textContent.includes("研究方案文档编辑与AI修订") && Boolean(document.querySelector(".protocol-editor .ProseMirror"))`);
    const editorTextBefore = await evaluate(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.textContent || ""`);
    await clickText(cdp, ".rail-tabs button", "证据");
    await waitFor(cdp, `Boolean(document.querySelector(".writing-reference-panel"))`);
    await clickText(cdp, ".writing-reference-views button", "已批准证据");
    await waitFor(cdp, `document.querySelectorAll(".writing-reference-brief input[type=checkbox]").length === 1`);
    const initial = await evaluate(cdp, `(() => ({
      approvedVisible: document.body.textContent.includes("医学已批准"),
      traceableLocatorVisible: (document.querySelector(".writing-reference-brief code")?.textContent || "").startsWith("ctgov:"),
      unchecked: !document.querySelector(".writing-reference-brief input")?.checked,
      returnButtonDisabled: Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("返回AI修订并使用所选证据"))?.disabled,
      noDirectInsertionClaim: document.body.textContent.includes("加入证据包不会直接改写或插入正式正文"),
      noOverflowX: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) <= innerWidth + 1,
    }))()`);
    const beforeScreenshot = await screenshot(cdp, "medical_writing_reference_approved_before.png");
    await evaluate(cdp, `document.querySelector(".writing-reference-brief input").click()`);
    await waitFor(cdp, `!Array.from(document.querySelectorAll("button")).find((item) => item.textContent.includes("返回AI修订并使用所选证据"))?.disabled`);
    await clickText(cdp, "button", "返回AI修订并使用所选证据");
    await waitFor(cdp, `Array.from(document.querySelectorAll(".rail-tabs button")).find((item) => item.textContent.trim() === "AI")?.classList.contains("active") && document.body.textContent.includes("1 条竞品方案证据")`);
    const after = await evaluate(cdp, `(() => ({
      aiTabActive: Array.from(document.querySelectorAll(".rail-tabs button")).find((item) => item.textContent.trim() === "AI")?.classList.contains("active"),
      selectedEvidenceCountVisible: document.body.textContent.includes("1 条竞品方案证据"),
      editorUnchanged: (document.querySelector(".protocol-editor .ProseMirror")?.textContent || "") === ${JSON.stringify(editorTextBefore)},
      submitStillExplicit: Array.from(document.querySelectorAll("button")).some((item) => item.textContent.includes("提交AI修订")),
      noOverflowX: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) <= innerWidth + 1,
    }))()`);
    const afterScreenshot = await screenshot(cdp, "medical_writing_reference_approved_after.png");
    const failures = [];
    for (const [key, value] of Object.entries(initial)) if (!value) failures.push(`initial:${key}`);
    for (const [key, value] of Object.entries(after)) if (!value) failures.push(`after:${key}`);
    await writeFile(path.resolve(outputDir, "medical_writing_reference_approved_qc.json"), JSON.stringify({ initial, after, screenshots: [beforeScreenshot, afterScreenshot], failures }, null, 2));
    cdp.close();
    if (failures.length) throw new Error(failures.join(", "));
  } finally {
    chrome.kill("SIGTERM");
    await wait(300);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
