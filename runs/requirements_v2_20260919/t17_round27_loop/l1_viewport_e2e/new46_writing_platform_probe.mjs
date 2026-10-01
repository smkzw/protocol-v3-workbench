#!/usr/bin/env node
// NEW-46 修复后浏览器冒烟：打开写作平台 → 106 章节可见 → 选中章节 →
// 「生成本章首稿候选」按钮非全灰（NEW-36/NEW-46 修复面）。
import { spawn } from "node:child_process";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { writeFile } from "node:fs/promises";

const APP_URL = "http://127.0.0.1:5186/";
const DEBUG_PORT = 9654;
const OUT_DIR = path.dirname(fileURLToPath(import.meta.url));
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PROJECT_ID = process.env.PROJ || "proj_user_e824a526a8f3";

function createCdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let id = 1;
  const pending = new Map();
  const listeners = new Map();
  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const cb = pending.get(msg.id); pending.delete(msg.id);
      if (msg.error) cb.reject(new Error(msg.error.message)); else cb.resolve(msg.result || {});
      return;
    }
    for (const l of listeners.get(msg.method) || []) l(msg.params || {});
  });
  return {
    ready: new Promise((res, rej) => { ws.addEventListener("open", res, { once: true }); ws.addEventListener("error", rej, { once: true }); }),
    send(m, p = {}) { const i = id++; ws.send(JSON.stringify({ id: i, method: m, params: p })); return new Promise((res, rej) => pending.set(i, { resolve: res, reject: rej })); },
    on(m, cb) { listeners.set(m, [...(listeners.get(m) || []), cb]); },
    close() { ws.close(); },
  };
}
async function evaluate(cdp, expr) {
  const r = await cdp.send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result?.value;
}
async function waitFor(cdp, expr, ms = 20000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (await evaluate(cdp, expr)) return; await new Promise((r) => setTimeout(r, 300)); }
  throw new Error(`timeout: ${label || expr}`);
}

const dir = await mkdtemp(path.join(tmpdir(), "new46-probe-"));
const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${DEBUG_PORT}`, `--user-data-dir=${dir}`, "--no-first-run", "about:blank"], { stdio: "ignore" });
let cdp;
try {
  for (let i = 0; i < 30; i++) {
    try { const t = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`)).json(); cdp = createCdp(t.find(x => x.type === "page").webSocketDebuggerUrl); await cdp.ready; break; }
    catch { await new Promise(r => setTimeout(r, 400)); }
  }
  await cdp.send("Page.enable"); await cdp.send("Runtime.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1512, height: 814, deviceScaleFactor: 1, mobile: false });
  await cdp.send("Page.navigate", { url: APP_URL });
  await waitFor(cdp, `document.readyState === 'complete'`, 20000, "page load");
  await new Promise(r => setTimeout(r, 2000));
  await evaluate(cdp, `(() => {
    const el = document.querySelector('select[aria-label="选择临床研究项目"]');
    if (!el) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
    setter.call(el, ${JSON.stringify(PROJECT_ID)});
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  await new Promise(r => setTimeout(r, 2000));
  await evaluate(cdp, `(() => {
    const b = Array.from(document.querySelectorAll("button")).find(x => x.textContent.trim() === "医学写作");
    if (b) { b.click(); return true; } return false;
  })()`);
  await new Promise(r => setTimeout(r, 4000));
  const result = await evaluate(cdp, `({
    has500: document.body.textContent.includes("500") && document.body.textContent.includes("失败"),
    hasSessionError: document.body.textContent.includes("真实方案文档会话读取失败"),
    hasEditableSection: Boolean(document.querySelector('.rich-editor-shell, .protocol-editor, [class*="editor"]')),
    sectionCount: document.querySelectorAll('[data-section-id], .section-item, [class*="section-node"]').length,
    chapterBtn: (() => {
      const b = Array.from(document.querySelectorAll("button")).find(x => x.textContent.includes("生成本章首稿候选"));
      return b ? { disabled: b.disabled, title: (b.title || "").slice(0, 80) } : "not-found";
    })(),
  })`);
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  await writeFile(path.join(OUT_DIR, "new46_writing_platform_after_fix.png"), Buffer.from(shot.data, "base64"));
  await writeFile(path.join(OUT_DIR, "new46_probe_result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
} finally {
  if (cdp) cdp.close();
  chrome.kill();
}
