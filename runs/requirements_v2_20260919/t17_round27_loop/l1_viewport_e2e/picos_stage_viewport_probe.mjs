#!/usr/bin/env node
// L1/NEW-2 专项探针（实现师 FAST 自查仪器，非测试者任务）：
// 在 1512×814 笔记本视口下，复用 R26-QA 留下的"可供修复验证复用"项目
// （MW-III-730D1531，proj_user_b729f3283029），经真实页面把旅程切到第二步
// PICOS（仅前端状态切换，不保存任何数据），测量：
//   - .authoring-journey-shell clientHeight ≥ 420
//   - .authoring-journey-body  clientHeight ≥ 300
//   - 6 组 PICOS 表标签（设计适用性/研究人群/干预措施/对照/结局指标/执行与统计）可见
// 输出 JSON 测量结果 + 截图到本目录。只读：不调用任何写接口。
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APP_URL = "http://127.0.0.1:5186/";
const DEBUG_PORT = 9652;
const PROJECT_ID = "proj_user_b729f3283029";
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
    on(method, cb) {
      listeners.set(method, [...(listeners.get(method) || []), cb]);
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
    if (await evaluate(cdp, expression)) return;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`timeout: ${expression}`);
}

const userDataDir = await mkdtemp(path.join(tmpdir(), "l1-picos-probe-"));
const chrome = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${DEBUG_PORT}`,
  `--user-data-dir=${userDataDir}`, "--no-first-run", "--no-default-browser-check", "about:blank",
], { stdio: "ignore" });

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
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1512, height: 814, deviceScaleFactor: 1, mobile: false });
  await cdp.send("Page.navigate", { url: APP_URL });
  await waitFor(cdp, `document.body.textContent.includes("项目总看板") || document.body.textContent.includes("请选择项目")`);

  // 选中项目（React 受控 select）
  await evaluate(cdp, `(() => {
    const el = document.querySelector('select[aria-label="选择临床研究项目"]');
    if (!el) throw new Error("project selector not found");
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
    setter.call(el, ${JSON.stringify(PROJECT_ID)});
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  await waitFor(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(PROJECT_ID)}`);

  // 打开医学写作页
  await evaluate(cdp, `(() => {
    const button = Array.from(document.querySelectorAll("button, a")).find((item) => item.textContent.trim().includes("医学写作"));
    if (!button) throw new Error("writing nav not found");
    button.click();
    return true;
  })()`);
  await waitFor(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`);

  // 切到第二步 PICOS（仅前端视图状态，不写库）
  await evaluate(cdp, `(() => {
    const tab = Array.from(document.querySelectorAll('.authoring-stage-strip button')).find((item) => item.textContent.includes("PICOS设计"));
    if (!tab) throw new Error("picos stage button not found");
    if (tab.disabled) throw new Error("picos stage button disabled");
    tab.click();
    return true;
  })()`);
  await waitFor(cdp, `Array.from(document.querySelectorAll('.authoring-group-tabs [role="tab"]')).map(t => t.textContent.trim()).includes("设计适用性")`);

  const measured = await evaluate(cdp, `(() => {
    const shell = document.querySelector('.authoring-journey-shell');
    const body = shell.querySelector('.authoring-journey-body');
    const tabs = Array.from(document.querySelectorAll('.authoring-group-tabs [role="tab"]')).map((tab) => ({
      label: tab.textContent.trim(),
      visible: Boolean(tab.offsetParent) && tab.getBoundingClientRect().height > 0,
    }));
    return {
      shellClientHeight: shell.clientHeight,
      bodyClientHeight: body ? body.clientHeight : null,
      gridTemplateRows: getComputedStyle(shell.closest('.writing-layout') || shell).gridTemplateRows,
      tabs,
    };
  })()`);
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  await writeFile(path.join(OUT_DIR, "1512x814_picos_stage_after_fix.png"), Buffer.from(shot.data, "base64"));

  const expected = ["设计适用性", "研究人群", "干预措施", "对照", "结局指标", "执行与统计"];
  const labels = measured.tabs.map((tab) => tab.label);
  const checks = {
    shell_ge_420: measured.shellClientHeight >= 420,
    body_ge_300: (measured.bodyClientHeight ?? 0) >= 300,
    picos_six_tabs_present: expected.every((item) => labels.includes(item)),
    picos_six_tabs_visible: expected.every((item) => measured.tabs.find((tab) => tab.label === item)?.visible),
  };
  const result = { project_id: PROJECT_ID, viewport: "1512x814", checks, ...measured };
  await writeFile(path.join(OUT_DIR, "picos_stage_measure_after_fix.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
} finally {
  if (cdp) cdp.close();
  chrome.kill();
}
