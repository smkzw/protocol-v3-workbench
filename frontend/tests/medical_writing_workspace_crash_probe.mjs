import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(
  scriptDir,
  "../../records/active_slices/medical_writing_workspace_usability_20260715/crash_probe",
);
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9395);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const projects = [
  { projectId: "proj_ra_greenfield_sandbox", createWorkingCopy: true },
  { projectId: "proj_mgk10_crswnp", createWorkingCopy: false },
  { projectId: "proj_rux_03_002", createWorkingCopy: false },
];

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}: ${JSON.stringify(payload)}`);
  return payload;
}

async function waitForJson(url, timeoutMs = 15000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await request(url);
    } catch (error) {
      lastError = error;
      await wait(200);
    }
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
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
    on(method, callback) {
      const current = listeners.get(method) || [];
      current.push(callback);
      listeners.set(method, current);
    },
    close() {
      ws.close();
    },
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

async function clickText(cdp, selector, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const item = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
        .find((node) => (node.textContent || "").trim() === ${JSON.stringify(label)} && !node.disabled);
      if (!item) return false;
      item.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Control not found: ${selector}/${label}`);
}

async function selectProject(cdp, projectId) {
  await waitForCondition(cdp, `Boolean(document.querySelector('select[aria-label="选择临床研究项目"] option[value=${JSON.stringify(projectId)}]')) && !document.querySelector('select[aria-label="选择临床研究项目"]')?.disabled`);
  const changed = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Project switcher unavailable: ${projectId}`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function screenshot(cdp, filename) {
  const image = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const outputPath = path.join(outputDir, filename);
  await writeFile(outputPath, Buffer.from(image.data, "base64"));
  return outputPath;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "medical-writing-crash-probe-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  const errors = [];
  const apiFailures = [];
  const results = [];
  let cdp;
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    const target = targets.find((item) => item.type === "page");
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    cdp.on("Runtime.exceptionThrown", (event) => errors.push({
      type: "exception",
      text: event.exceptionDetails?.exception?.description || event.exceptionDetails?.text,
    }));
    cdp.on("Runtime.consoleAPICalled", (event) => {
      if (["error", "assert"].includes(event.type)) errors.push({
        type: `console:${event.type}`,
        text: event.args?.map((item) => item.value ?? item.description ?? "").join(" "),
      });
    });
    cdp.on("Network.responseReceived", (event) => {
      const url = event.response?.url || "";
      if (url.includes("/api/") && event.response.status >= 400) apiFailures.push({ status: event.response.status, url });
    });
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);

    for (const project of projects) {
      const errorStart = errors.length;
      const failureStart = apiFailures.length;
      await selectProject(cdp, project.projectId);
      await clickText(cdp, ".nav-item", "医学写作");
      await waitForCondition(cdp, `Boolean(document.querySelector(".protocol-editor .ProseMirror"))`);
      await clickText(cdp, ".writing-title-actions button", "目录");
      await waitForCondition(cdp, `Boolean(document.querySelector(".writing-document-map-drawer"))`);
      const buttons = await evaluate(cdp, `document.querySelectorAll(".writing-section-buttons > button").length`);
      await evaluate(cdp, `document.querySelector('.writing-document-map-drawer .icon-button')?.click()`);
      await waitForCondition(cdp, `!document.querySelector(".writing-document-map-drawer")`);
      await evaluate(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.click()`);
      await wait(500);
      let shellGeometry = null;
      let tableDesigner = null;
      if (project.projectId === "proj_rux_03_002") {
        shellGeometry = await evaluate(cdp, `
          (() => {
            const topbar = document.querySelector('.topbar')?.getBoundingClientRect();
            const meta = document.querySelector('.project-meta')?.getBoundingClientRect();
            const metaChildren = Array.from(document.querySelectorAll('.project-meta > *')).map((item) => item.getBoundingClientRect());
            const sidebar = document.querySelector('.sidebar')?.getBoundingClientRect();
            const brand = document.querySelector('.brand')?.getBoundingClientRect();
            const logo = document.querySelector('.brand img')?.getBoundingClientRect();
            return {
              topbarHeight: topbar?.height || 0,
              metaHeight: meta?.height || 0,
              metaChildCount: metaChildren.length,
              metaChildren: metaChildren.map((item, index) => ({ index, top: item.top, bottom: item.bottom, width: item.width, height: item.height })),
              metaSingleRow: metaChildren.length === 6 && metaChildren.every((item) => Math.abs(item.top - metaChildren[0].top) < 1 && Math.abs(item.bottom - metaChildren[0].bottom) < 1),
              metaInsideTopbar: Boolean(topbar && meta && meta.top >= topbar.top && meta.bottom <= topbar.bottom),
              sidebarWidth: sidebar?.width || 0,
              logoInsideBrand: Boolean(brand && logo && logo.left >= brand.left && logo.right <= brand.right && logo.top >= brand.top && logo.bottom <= brand.bottom),
              viewportOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
            };
          })()
        `);
        const hasDesignerButton = await evaluate(cdp, `Boolean(document.querySelector('.rich-table-designer-button:not(:disabled)'))`);
        if (hasDesignerButton) {
          await evaluate(cdp, `document.querySelector('.rich-table-designer-button:not(:disabled)')?.click()`);
          await waitForCondition(cdp, `Boolean(document.querySelector('.structured-table-designer'))`);
          const beforeDesignerErrors = errors.length;
          const clickedCell = await evaluate(cdp, `
            (() => {
              const cell = document.querySelector('.std-grid-table textarea, .std-grid-table .std-readonly-cell');
              if (!cell) return false;
              cell.click();
              return true;
            })()
          `);
          if (!clickedCell) throw new Error('Structured table designer has no clickable cell');
          await waitForCondition(cdp, `Boolean(document.querySelector('.std-grid-table td.selected, .std-grid-table th.selected'))`);
          await wait(250);
          tableDesigner = {
            clickedCell,
            selectedCellCount: await evaluate(cdp, `document.querySelectorAll('.std-grid-table td.selected, .std-grid-table th.selected').length`),
            newErrors: errors.slice(beforeDesignerErrors),
            screenshot: await screenshot(cdp, 'proj_rux_03_002_table_designer_cell_selected.png'),
          };
          await evaluate(cdp, `document.querySelector('[aria-label="关闭表格设计器"]')?.click()`);
          await waitForCondition(cdp, `!document.querySelector('.structured-table-designer')`);
        }
      }
      if (project.createWorkingCopy) {
        const canCreate = await evaluate(cdp, `Array.from(document.querySelectorAll("button")).some((item) => (item.textContent || "").includes("创建工作副本") && !item.disabled)`);
        if (canCreate) {
          await evaluate(cdp, `Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").includes("创建工作副本") && !item.disabled)?.click()`);
          await wait(1500);
        }
      }
      const metrics = await evaluate(cdp, `
        (() => ({
          bodyTextLength: (document.body.innerText || "").trim().length,
          rootChildCount: document.querySelector("#root")?.childElementCount || 0,
          rootWidth: document.querySelector("#root")?.getBoundingClientRect().width || 0,
          rootHeight: document.querySelector("#root")?.getBoundingClientRect().height || 0,
          editorExists: Boolean(document.querySelector(".protocol-editor .ProseMirror")),
          editorEditable: document.querySelector(".protocol-editor .ProseMirror")?.getAttribute("contenteditable") || "",
          workingCopyStatus: document.querySelector(".working-copy-status-bar")?.innerText || "",
        }))()
      `);
      results.push({
        projectId: project.projectId,
        sectionButtonCount: buttons,
        metrics,
        shellGeometry,
        tableDesigner,
        errors: errors.slice(errorStart),
        apiFailures: apiFailures.slice(failureStart),
        screenshot: await screenshot(cdp, `${project.projectId}.png`),
      });
      await clickText(cdp, ".nav-item", "项目总看板");
      await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);
    }
    await writeFile(path.join(outputDir, "probe_report.json"), JSON.stringify({ appUrl, results, errors, apiFailures }, null, 2), "utf8");
  } finally {
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(500);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
