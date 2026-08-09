import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const outputDir = process.env.QC_OUTPUT_DIR || path.join(
  projectRoot,
  "records/active_slices/medical_writing_word_indexes_crossrefs_20260716/browser_qc",
);
const stableRuntimeDir = process.env.STABLE_RUNTIME_DIR || path.resolve(projectRoot, "../..", "runtime");
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function freePort(preferred) {
  const listen = (port) => new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      const selected = server.address().port;
      server.close(() => resolve(selected));
    });
  });
  try { return await listen(Number(preferred)); } catch { return listen(0); }
}

function startService(command, args, options) {
  const output = [];
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
  const collect = (chunk) => {
    output.push(String(chunk));
    if (output.length > 300) output.shift();
  };
  child.stdout.on("data", collect);
  child.stderr.on("data", collect);
  return { child, output };
}

async function stopService(service) {
  if (!service?.child || service.child.exitCode !== null) return;
  const exited = new Promise((resolve) => service.child.once("exit", resolve));
  service.child.kill("SIGTERM");
  await Promise.race([exited, wait(5000)]);
  if (service.child.exitCode === null) service.child.kill("SIGKILL");
}

async function waitForJson(url, timeoutMs = 60000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`${response.status} ${url}`);
      return response.json();
    } catch (error) {
      lastError = error;
      await wait(200);
    }
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

async function waitForHttp(url, timeoutMs = 60000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
      lastError = new Error(`${response.status} ${url}`);
    } catch (error) {
      lastError = error;
    }
    await wait(200);
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

async function directorySnapshot(root) {
  const snapshot = {};
  async function visit(current) {
    let entries = [];
    try { entries = await readdir(current, { withFileTypes: true }); } catch { return; }
    for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
      const absolute = path.join(current, entry.name);
      if (entry.isDirectory()) await visit(absolute);
      else if (entry.isFile()) {
        const metadata = await stat(absolute);
        snapshot[path.relative(root, absolute)] = {
          bytes: metadata.size,
          sha256: createHash("sha256").update(await readFile(absolute)).digest("hex"),
        };
      }
    }
  }
  await visit(root);
  return snapshot;
}

async function apiJson(apiBase, route) {
  const response = await fetch(`${apiBase}${route}`);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${route}: ${JSON.stringify(body)}`);
  return body;
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
  const result = await cdp.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  }
  return result.result?.value;
}

async function waitForCondition(cdp, expression, timeoutMs = 45000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(200);
  }
  throw new Error(`Timed out waiting for ${expression}; last=${JSON.stringify(lastValue)}`);
}

async function clickText(cdp, selector, text) {
  const clicked = await evaluate(cdp, `(() => {
    const node = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
      .find((item) => (item.textContent || "").trim().includes(${JSON.stringify(text)}));
    node?.click();
    return Boolean(node);
  })()`);
  if (!clicked) throw new Error(`Could not click ${selector}: ${text}`);
}

async function selectProject(cdp, projectId) {
  await waitForCondition(cdp, `!document.querySelector('select[aria-label="选择临床研究项目"]')?.disabled`);
  const selected = await evaluate(cdp, `(() => {
    const node = document.querySelector('select[aria-label="选择临床研究项目"]');
    if (!node) return false;
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(node, ${JSON.stringify(projectId)});
    node.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  if (!selected) throw new Error(`Project switcher unavailable: ${projectId}`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function openWritingSection(cdp, projectId, sectionIndex, heading) {
  await cdp.send("Page.navigate", { url: globalThis.__appUrl });
  await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);
  await selectProject(cdp, projectId);
  await clickText(cdp, ".nav-item", "医学写作");
  await waitForCondition(cdp, `document.body.textContent.includes("研究方案文档编辑与AI修订")`);
  const opened = await evaluate(cdp, `(() => {
    const button = document.querySelector('button[title="打开研究方案目录"]');
    button?.click();
    return Boolean(button);
  })()`);
  if (!opened) throw new Error("Document directory trigger unavailable");
  await waitForCondition(cdp, `Boolean(document.querySelector(".writing-document-map-drawer"))`);
  const searched = await evaluate(cdp, `(() => {
    const input = document.querySelector(".writing-document-map-search input");
    if (!input) return false;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, ${JSON.stringify(heading)});
    input.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  })()`);
  if (!searched) throw new Error(`Document directory search unavailable: ${heading}`);
  await waitForCondition(cdp, `Array.from(document.querySelectorAll(".writing-section-buttons > button"))
    .some((button) => (button.textContent || "").includes(${JSON.stringify(heading)}))`);
  const clicked = await evaluate(cdp, `(() => {
    const button = Array.from(document.querySelectorAll(".writing-section-buttons > button"))
      .find((item) => (item.textContent || "").includes(${JSON.stringify(heading)}));
    button?.click();
    return Boolean(button);
  })()`);
  if (!clicked) throw new Error(`Section unavailable after search: ${sectionIndex} ${heading}`);
  await waitForCondition(cdp, `document.querySelector(".rich-editor-meta strong")?.textContent?.trim() === ${JSON.stringify(heading)}`);
  await waitForCondition(cdp, `Boolean(document.querySelector(".protocol-editor .ProseMirror"))`);
}

async function ensureEditableWorkingCopy(cdp) {
  const created = await evaluate(cdp, `(() => {
    const button = Array.from(document.querySelectorAll(".working-copy-actions button"))
      .find((item) => (item.textContent || "").includes("创建工作副本"));
    button?.click();
    return Boolean(button);
  })()`);
  if (created) {
    await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("有未保存修订")`);
  }
  await waitForCondition(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.getAttribute("contenteditable") === "true"`);
}

async function placeBodyCaret(cdp) {
  const placed = await evaluate(cdp, `(() => {
    const paragraph = Array.from(document.querySelectorAll(".protocol-editor .protocol-source-block > p"))
      .find((node) => (node.textContent || "").trim().length > 0);
    if (!paragraph) return false;
    paragraph.closest(".ProseMirror")?.focus();
    const range = document.createRange();
    range.selectNodeContents(paragraph);
    range.collapse(false);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange", { bubbles: true }));
    return true;
  })()`);
  if (!placed) throw new Error("No editable body paragraph found");
}

async function chooseCrossReference(cdp, ariaLabel, target) {
  const value = `${target.kind}:${target.object_id}`;
  try {
    await waitForCondition(cdp, `(() => {
      const node = document.querySelector('select[aria-label=${JSON.stringify(ariaLabel)}]');
      return Boolean(node && Array.from(node.options).some((option) => option.value === ${JSON.stringify(value)}));
    })()`, 15000);
  } catch (error) {
    const state = await evaluate(cdp, `(() => {
      const node = document.querySelector('select[aria-label=${JSON.stringify(ariaLabel)}]');
      return {
        present: Boolean(node),
        disabled: node?.disabled ?? null,
        options: Array.from(node?.options || []).map((option) => ({ value: option.value, text: option.textContent })),
        editorTitle: document.querySelector(".rich-editor-meta strong")?.textContent?.trim() || "",
        workingCopy: document.querySelector(".working-copy-status-bar")?.textContent?.trim() || "",
      };
    })()`);
    throw new Error(`${error.message}; crossReferenceState=${JSON.stringify(state)}`);
  }
  const selected = await evaluate(cdp, `(() => {
    const node = document.querySelector('select[aria-label=${JSON.stringify(ariaLabel)}]');
    if (!node || !Array.from(node.options).some((option) => option.value === ${JSON.stringify(value)})) return false;
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(node, ${JSON.stringify(value)});
    node.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  if (!selected) throw new Error(`Cross-reference target missing from ${ariaLabel}: ${value}`);
}

async function saveWorkingCopy(cdp) {
  await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("有未保存修订")`);
  await clickText(cdp, ".working-copy-actions button", "保存工作副本");
  await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("已保存")`);
}

async function screenshot(cdp, name) {
  const capture = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const target = path.join(outputDir, name);
  await writeFile(target, Buffer.from(capture.data, "base64"));
  return target;
}

function crossReferenceMarks(value, matches = []) {
  if (Array.isArray(value)) value.forEach((item) => crossReferenceMarks(item, matches));
  else if (value && typeof value === "object") {
    if (value.type === "crossReference") matches.push(value);
    Object.values(value).forEach((item) => crossReferenceMarks(item, matches));
  }
  return matches;
}

async function projectSections(apiBase, projectId) {
  const session = await apiJson(apiBase, `/api/projects/${projectId}/medical-writing/document-session`);
  const sections = [];
  for (let index = 0; index < session.sections.length; index += 1) {
    const summary = session.sections[index];
    const source = await apiJson(apiBase, `/api/projects/${projectId}/medical-writing/document-session/sections/${summary.section_id}`);
    sections.push({ index, summary, source });
  }
  return { session, sections };
}

async function main() {
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const runtimeDir = await mkdtemp(path.join(tmpdir(), "mw-index-crossref-runtime-"));
  const chromeProfile = await mkdtemp(path.join(tmpdir(), "mw-index-crossref-chrome-"));
  const apiPort = await freePort(process.env.QC_API_PORT || 8936);
  const vitePort = await freePort(process.env.QC_VITE_PORT || 5196);
  const debugPort = await freePort(process.env.CHROME_DEBUG_PORT || 9566);
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;
  globalThis.__appUrl = appUrl;
  const stableBefore = await directorySnapshot(stableRuntimeDir);
  const api = startService("python3", ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], {
    cwd: projectRoot,
    env: { ...process.env, WORKBENCH_RUNTIME_DIR: runtimeDir, PYTHONUNBUFFERED: "1" },
  });
  const vite = startService("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"], {
    cwd: frontendRoot,
    env: { ...process.env, VITE_API_PROXY_TARGET: apiBase },
  });
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${chromeProfile}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  const report = { passed: false, appUrl, apiBase, runtimeDir, projects: [], failures: [] };
  let cdp;
  try {
    await waitForJson(`${apiBase}/api/health`);
    await waitForHttp(appUrl);
    const version = await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    const page = targets.find((item) => item.type === "page");
    if (!page?.webSocketDebuggerUrl || !version.Browser) throw new Error("Chrome CDP unavailable");
    cdp = createCdp(page.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });

    const ruxProjectId = "proj_rux_03_002";
    const rux = await projectSections(apiBase, ruxProjectId);
    const ruxSection = rux.sections.find((item) => item.source.content_blocks.some((block) => block.figure_kind === "source_docx_image"));
    const ruxIndex = await apiJson(apiBase, `/api/projects/${ruxProjectId}/medical-writing/document-index`);
    const ruxTarget = ruxIndex.tables.find((item) => item.title.includes("SCORAD-主观症状评分"));
    if (!ruxSection || !ruxTarget) throw new Error("RUX source image table/index target unavailable");
    await openWritingSection(cdp, ruxProjectId, ruxSection.index, ruxSection.summary.heading);
    await ensureEditableWorkingCopy(cdp);
    await waitForCondition(cdp, `(() => {
      const image = document.querySelector(".source-docx-image img");
      return Boolean(image && image.complete && image.naturalWidth > 0 && image.naturalHeight > 0);
    })()`);
    const ruxImage = await evaluate(cdp, `(() => {
      const figure = document.querySelector(".source-docx-image");
      const image = figure?.querySelector("img");
      return {
        caption: figure?.querySelector("figcaption")?.textContent?.trim() || "",
        naturalWidth: image?.naturalWidth || 0,
        naturalHeight: image?.naturalHeight || 0,
        overflowX: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
      };
    })()`);
    await placeBodyCaret(cdp);
    await chooseCrossReference(cdp, "插入交叉引用", ruxTarget);
    await waitForCondition(cdp, `Boolean(document.querySelector('.protocol-cross-reference[data-cross-reference-id=${JSON.stringify(ruxTarget.object_id)}]'))`);
    await saveWorkingCopy(cdp);
    await evaluate(cdp, `document.querySelector(".source-docx-image")?.scrollIntoView({ block: "center", inline: "nearest", behavior: "auto" })`);
    await waitForCondition(cdp, `(() => {
      const image = document.querySelector(".source-docx-image img");
      const rect = image?.getBoundingClientRect();
      return Boolean(rect && rect.top >= 0 && rect.bottom <= innerHeight);
    })()`);
    const ruxScreenshot = await screenshot(cdp, "rux_source_image_and_crossref_1920x1080.png");
    await openWritingSection(cdp, ruxProjectId, ruxSection.index, ruxSection.summary.heading);
    await waitForCondition(cdp, `Boolean(document.querySelector('.protocol-cross-reference[data-cross-reference-id=${JSON.stringify(ruxTarget.object_id)}]'))`);
    const ruxWorkingCopy = await apiJson(apiBase, `/api/projects/${ruxProjectId}/medical-writing/working-copies/${ruxSection.summary.section_id}`);
    const ruxMarks = crossReferenceMarks(ruxWorkingCopy.content_blocks);
    const ruxDocxResponse = await fetch(`${apiBase}/api/projects/${ruxProjectId}/medical-writing/document.docx?mode=draft_preview`);
    if (!ruxDocxResponse.ok) throw new Error(`RUX DOCX export failed: ${ruxDocxResponse.status}`);
    const ruxDocxPath = path.join(outputDir, "rux_crossref_draft.docx");
    await writeFile(ruxDocxPath, Buffer.from(await ruxDocxResponse.arrayBuffer()));
    report.projects.push({
      projectId: ruxProjectId,
      sectionId: ruxSection.summary.section_id,
      target: ruxTarget,
      image: ruxImage,
      markCount: ruxMarks.length,
      markAttrs: ruxMarks.map((item) => item.attrs),
      screenshot: ruxScreenshot,
      docx: ruxDocxPath,
    });

    const pnhProjectId = "proj_my008_pnh_3_01";
    const pnh = await projectSections(apiBase, pnhProjectId);
    const pnhSection = pnh.sections.find((item) => item.source.content_blocks.some((block) => block.block_type === "table"));
    const pnhIndex = await apiJson(apiBase, `/api/projects/${pnhProjectId}/medical-writing/document-index`);
    const pnhTarget = pnhIndex.tables[0] || pnhIndex.figures[0];
    if (!pnhSection || !pnhTarget) throw new Error("PNH table section/index target unavailable");
    await openWritingSection(cdp, pnhProjectId, pnhSection.index, pnhSection.summary.heading);
    await ensureEditableWorkingCopy(cdp);
    await waitForCondition(cdp, `Boolean(document.querySelector('button[aria-label="全屏编辑当前表格结构与附注"]'))`);
    await evaluate(cdp, `document.querySelector('button[aria-label="全屏编辑当前表格结构与附注"]')?.click()`);
    await waitForCondition(cdp, `Boolean(document.querySelector(".structured-table-designer"))`);
    const selectedCell = await evaluate(cdp, `(() => {
      const button = Array.from(document.querySelectorAll(".std-cell-select-button"))
        .find((node) => !node.disabled && (node.textContent || "").trim().length > 0);
      button?.click();
      return Boolean(button);
    })()`);
    if (!selectedCell) throw new Error("PNH editable table cell unavailable");
    await waitForCondition(cdp, `Boolean(document.querySelector('.std-cell-rich-editor .ProseMirror'))`);
    await evaluate(cdp, `document.querySelector('.std-cell-rich-editor .ProseMirror')?.focus()`);
    await chooseCrossReference(cdp, "单元格插入交叉引用", pnhTarget);
    await waitForCondition(cdp, `Boolean(document.querySelector('.std-cell-rich-editor .protocol-cross-reference[data-cross-reference-id=${JSON.stringify(pnhTarget.object_id)}]'))`);
    const pnhCellScreenshot = await screenshot(cdp, "pnh_table_cell_crossref_1920x1080.png");
    await evaluate(cdp, `document.querySelector('button[aria-label="关闭表格设计器"]')?.click()`);
    await waitForCondition(cdp, `!document.querySelector(".structured-table-designer")`);
    await saveWorkingCopy(cdp);
    await openWritingSection(cdp, pnhProjectId, pnhSection.index, pnhSection.summary.heading);
    await evaluate(cdp, `document.querySelector('button[aria-label="全屏编辑当前表格结构与附注"]')?.click()`);
    await waitForCondition(cdp, `Boolean(document.querySelector(".structured-table-designer"))`);
    await evaluate(cdp, `document.querySelector(".std-cell-select-button")?.click()`);
    await waitForCondition(cdp, `Boolean(document.querySelector('.std-cell-rich-editor .protocol-cross-reference[data-cross-reference-id=${JSON.stringify(pnhTarget.object_id)}]'))`);
    const pnhWorkingCopy = await apiJson(apiBase, `/api/projects/${pnhProjectId}/medical-writing/working-copies/${pnhSection.summary.section_id}`);
    const pnhMarks = crossReferenceMarks(pnhWorkingCopy.content_blocks);
    const pnhDocxResponse = await fetch(`${apiBase}/api/projects/${pnhProjectId}/medical-writing/document.docx?mode=draft_preview`);
    if (!pnhDocxResponse.ok) throw new Error(`PNH DOCX export failed: ${pnhDocxResponse.status}`);
    const pnhDocxPath = path.join(outputDir, "pnh_crossref_draft.docx");
    await writeFile(pnhDocxPath, Buffer.from(await pnhDocxResponse.arrayBuffer()));
    report.projects.push({
      projectId: pnhProjectId,
      sectionId: pnhSection.summary.section_id,
      target: pnhTarget,
      markCount: pnhMarks.length,
      markAttrs: pnhMarks.map((item) => item.attrs),
      screenshot: pnhCellScreenshot,
      docx: pnhDocxPath,
    });

    for (const project of report.projects) {
      if (!project.markCount) report.failures.push(`${project.projectId}:mark-not-persisted`);
      if (project.markAttrs.some((attrs) => Object.keys(attrs || {}).sort().join(",") !== "targetId,targetKind")) {
        report.failures.push(`${project.projectId}:untrusted-mark-attrs`);
      }
    }
    if (ruxImage.caption !== "表 8 SCORAD-主观症状评分") report.failures.push("rux:caption-mismatch");
    if (!ruxImage.naturalWidth || !ruxImage.naturalHeight) report.failures.push("rux:image-not-rendered");
    if (ruxImage.overflowX > 0) report.failures.push(`rux:page-overflow-${ruxImage.overflowX}`);
  } catch (error) {
    report.failures.push(error.stack || error.message);
  } finally {
    cdp?.close();
    if (chrome.exitCode === null) chrome.kill("SIGTERM");
    await stopService(vite);
    await stopService(api);
    report.apiLogTail = api.output.slice(-100);
    report.viteLogTail = vite.output.slice(-60);
    report.stableRuntimeUnchanged = JSON.stringify(stableBefore) === JSON.stringify(await directorySnapshot(stableRuntimeDir));
    if (!report.stableRuntimeUnchanged) report.failures.push("stable-runtime-changed");
    if (process.env.PRESERVE_QC_RUNTIME !== "1") await rm(runtimeDir, { recursive: true, force: true });
    await rm(chromeProfile, { recursive: true, force: true });
  }
  report.passed = report.failures.length === 0 && report.projects.length === 2;
  await writeFile(path.join(outputDir, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: report.passed, projects: report.projects, failures: report.failures }, null, 2));
  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
