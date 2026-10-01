#!/usr/bin/env node
// retest-r1 测试者视口探针（只读）：1512×814 笔记本视口下打开本协调员自己新建的
// 项目B（局灶性癫痫 MW-II-141FA015），测量研究框架表单体是否可见：
//   - .authoring-journey-shell clientHeight ≥ 420
//   - .authoring-journey-body clientHeight ≥ 300
//   - 4 组框架表标签（项目与产品/研究目的/竞品范围/总体设计）可见
//   - 高级微调面板默认展开（summary 不处于折叠态）
// 仅前端视图导航与测量，不调用任何写接口、不改任何数据。
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APP_URL = "http://127.0.0.1:5186/";
const DEBUG_PORT = 9653;
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

const userDataDir = await mkdtemp(path.join(tmpdir(), "retest-r1-probe-"));
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
  await waitFor(cdp, `document.body.textContent.includes("请选择项目")`);

  // 从下拉选项文本中找到本项目 option 的 value（React 受控 select）
  const projectValue = await evaluate(cdp, `(() => {
    const el = document.querySelector('select[aria-label="选择临床研究项目"]');
    if (!el) throw new Error("project selector not found");
    const opt = Array.from(el.options).find((o) => o.textContent.includes("MW-II-141FA015"));
    return opt ? opt.value : null;
  })()`);
  if (!projectValue) throw new Error("project B option not found");

  await evaluate(cdp, `(() => {
    const el = document.querySelector('select[aria-label="选择临床研究项目"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
    setter.call(el, ${JSON.stringify(projectValue)});
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  await waitFor(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectValue)}`);
  await new Promise((r) => setTimeout(r, 1200));

  await evaluate(cdp, `(() => {
    const button = Array.from(document.querySelectorAll("button, a")).find((item) => item.textContent.trim().includes("医学写作"));
    if (!button) throw new Error("writing nav not found");
    button.click();
    return true;
  })()`);
  await waitFor(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`);
  await new Promise((r) => setTimeout(r, 1500));

  const measured = await evaluate(cdp, `(() => {
    const shell = document.querySelector('.authoring-journey-shell');
    const body = shell.querySelector('.authoring-journey-body');
    const framingTabs = Array.from(document.querySelectorAll('.authoring-group-tabs [role="tab"], .authoring-group-tabs button'))
      .map((tab) => ({ label: tab.textContent.trim(), visible: Boolean(tab.offsetParent) && tab.getBoundingClientRect().height > 0 }));
    const layout = shell.closest('.writing-layout') || shell;
    const summary = document.querySelector('.authoring-journey-shell details > summary, details.advanced-refinement > summary');
    const picosBtn = Array.from(document.querySelectorAll('.authoring-stage-strip button')).find((b) => b.textContent.includes("PICOS设计"));
    const visibleTextInputs = Array.from(document.querySelectorAll('.authoring-journey-shell input, .authoring-journey-shell select, .authoring-journey-shell textarea'))
      .filter((el) => el.offsetParent !== null).length;
    return {
      shellClientHeight: shell.clientHeight,
      bodyClientHeight: body ? body.clientHeight : null,
      gridTemplateRows: getComputedStyle(layout).gridTemplateRows,
      framingTabs,
      advancedPanelOpen: summary ? summary.parentElement.open : null,
      picosStageDisabled: picosBtn ? picosBtn.disabled : null,
      visibleFormControls: visibleTextInputs,
      viewport: [window.innerWidth, window.innerHeight],
    };
  })()`);
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  await writeFile(path.join(OUT_DIR, "shots", "05-1512x814_项目A_PICOS表单_探针.png"), Buffer.from(shot.data, "base64"));

  const expectedFraming = ["项目与产品", "研究目的", "竞品范围", "总体设计"];
  const labels = measured.framingTabs.map((tab) => tab.label);
  const checks = {
    shell_ge_420: measured.shellClientHeight >= 420,
    body_ge_300: (measured.bodyClientHeight ?? 0) >= 300,
    framing_tabs_present: expectedFraming.every((item) => labels.includes(item)),
    framing_tabs_visible: expectedFraming.every((item) => measured.framingTabs.find((tab) => tab.label === item)?.visible),
    form_controls_visible: measured.visibleFormControls >= 5,
    advanced_panel_open_by_default: measured.advancedPanelOpen !== false,
  };
  const result = { project: "MW-II-141FA015 (retest-r1 项目B, 本协调员自建)", viewport: "1512x814", checks, ...measured };
  await writeFile(path.join(OUT_DIR, "probe_picos_1512x814.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
} finally {
  if (cdp) cdp.close();
  chrome.kill();
}
