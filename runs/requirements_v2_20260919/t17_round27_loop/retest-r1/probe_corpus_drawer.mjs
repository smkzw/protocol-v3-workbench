#!/usr/bin/env node
// retest-r1 只读探针：查看项目A（MW-II-141FA015）竞品处理抽屉中已准备资料的
// 解析/OCR状态。仅GET导航与抽屉展开，不调用写接口。
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APP_URL = "http://127.0.0.1:5186/";
const DEBUG_PORT = 9654;
const OUT_DIR = path.dirname(fileURLToPath(import.meta.url));
const CHROME = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

function createCdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  const listeners = new Map();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const cb = pending.get(message.id);
      pending.delete(message.id);
      message.error ? cb.reject(new Error(message.error.message)) : cb.resolve(message.result || {});
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
    on(method, cb) { (listeners.get(method) || listeners.set(method, []).get(method)).push(cb); },
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
    if (await evaluate(cdp, expression)) return;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`timeout: ${expression}`);
}

const userDataDir = await mkdtemp(path.join(tmpdir(), "retest-r1-corpus-"));
const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${DEBUG_PORT}`, `--user-data-dir=${userDataDir}`, "--no-first-run", "--no-default-browser-check", "about:blank"], { stdio: "ignore" });
let cdp;
try {
  for (let i = 0; i < 40; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`);
      const targets = await res.json();
      cdp = createCdp(targets.find((item) => item.type === "page").webSocketDebuggerUrl);
      await cdp.ready;
      break;
    } catch { await new Promise((r) => setTimeout(r, 500)); }
  }
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Page.navigate", { url: APP_URL });
  await waitFor(cdp, `document.body.textContent.includes("请选择项目")`);
  const projectValue = await evaluate(cdp, `(() => {
    const el = document.querySelector('select[aria-label="选择临床研究项目"]');
    const opt = Array.from(el.options).find((o) => o.textContent.includes("MW-II-141FA015"));
    return opt ? opt.value : null;
  })()`);
  await evaluate(cdp, `(() => {
    const el = document.querySelector('select[aria-label="选择临床研究项目"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
    setter.call(el, ${JSON.stringify(projectValue)});
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  await waitFor(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectValue)}`);
  await new Promise((r) => setTimeout(r, 1500));
  await evaluate(cdp, `(() => {
    const button = Array.from(document.querySelectorAll("button, a")).find((item) => item.textContent.trim().includes("医学写作"));
    button.click();
    return true;
  })()`);
  await waitFor(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`);
  await new Promise((r) => setTimeout(r, 1000));
  // 打开竞品处理抽屉
  await evaluate(cdp, `(() => {
    const btn = Array.from(document.querySelectorAll("button")).find((b) => ["查看竞品资料","打开竞品处理"].includes(b.textContent.trim()));
    if (!btn) return false;
    btn.click();
    return true;
  })()`);
  await new Promise((r) => setTimeout(r, 3000));
  const drawerText = await evaluate(cdp, `(() => document.body.innerText.slice(0, 6000))()`);
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  await writeFile(path.join(OUT_DIR, "shots", "06-项目A_竞品处理抽屉.png"), Buffer.from(shot.data, "base64"));
  await writeFile(path.join(OUT_DIR, "probe_corpus_drawer_text.txt"), drawerText, "utf8");
  console.log(drawerText);
} finally {
  if (cdp) cdp.close();
  chrome.kill();
}
