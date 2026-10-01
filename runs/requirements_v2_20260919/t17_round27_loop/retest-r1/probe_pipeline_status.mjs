#!/usr/bin/env node
// retest-r1 只读轮询：输出两个自建项目的竞品流水线进度横幅文本。
import { spawn } from "node:child_process";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const APP_URL = "http://127.0.0.1:5186/";
const DEBUG_PORT = 9655;
const CHROME = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PROJECT_KEYS = process.argv.slice(2);

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

const userDataDir = await mkdtemp(path.join(tmpdir(), "retest-r1-status-"));
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
  for (const key of PROJECT_KEYS) {
    const value = await evaluate(cdp, `(() => {
      const el = document.querySelector('select[aria-label="选择临床研究项目"]');
      const opt = Array.from(el.options).find((o) => o.textContent.includes(${JSON.stringify(key)}));
      return opt ? opt.value : null;
    })()`);
    if (!value) { console.log(key, "OPTION_NOT_FOUND"); continue; }
    await evaluate(cdp, `(() => {
      const el = document.querySelector('select[aria-label="选择临床研究项目"]');
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
      setter.call(el, ${JSON.stringify(value)});
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()`);
    await new Promise((r) => setTimeout(r, 2000));
    await evaluate(cdp, `(() => {
      const button = Array.from(document.querySelectorAll("button, a")).find((item) => item.textContent.trim().includes("医学写作"));
      if (button && !button.disabled) button.click();
      return true;
    })()`);
    await new Promise((r) => setTimeout(r, 2500));
    const text = await evaluate(cdp, `(() => {
      const t = document.body.innerText;
      const banner = (t.match(/正在处理竞品文献[^\\n]*/) || [null])[0];
      const status = (t.match(/项目状态\\n([^\\n]*)/) || [null,null])[1];
      const combine = (t.match(/已结合[^\\n]*/) || [null])[0];
      const corpus = (t.match(/语料准备[\\s\\S]{0,160}/) || [""])[0].split("\\n").slice(0,6).join(" | ");
      return JSON.stringify({ banner, status, combine });
    })()`);
    console.log(key, text);
  }
} finally {
  if (cdp) cdp.close();
  chrome.kill();
}
