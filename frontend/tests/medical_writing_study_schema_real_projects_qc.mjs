import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const appUrl = process.env.APP_URL;
const apiUrl = process.env.API_URL;
const reportPath = process.env.QC_API_REPORT;
const outputDir = process.env.QC_OUTPUT_DIR || path.join(
  projectRoot,
  "records/active_slices/medical_writing_study_schema_v1_20260716/browser_qc",
);
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9517);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
if (!appUrl || !apiUrl || !reportPath) throw new Error("APP_URL, API_URL and QC_API_REPORT are required");
if (process.env.QC_ISOLATED_RUNTIME !== "1") throw new Error("study-schema browser QC requires an isolated runtime");

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function json(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${url}: ${JSON.stringify(payload)}`);
  return payload;
}

async function waitForJson(url, timeoutMs = 20000) {
  const started = Date.now();
  let error;
  while (Date.now() - started < timeoutMs) {
    try { return await json(url); } catch (current) { error = current; await wait(200); }
  }
  throw error || new Error(`Timed out waiting for ${url}`);
}

async function waitForLayoutRevision(projectId, minimumRevision, timeoutMs = 45000) {
  const url = `${apiUrl}/api/projects/${projectId}/medical-writing/authoring-journey/study-schema`;
  const started = Date.now();
  let snapshot;
  while (Date.now() - started < timeoutMs) {
    snapshot = await json(url);
    if (snapshot.presentation.layout_revision >= minimumRevision) return snapshot;
    await wait(200);
  }
  throw new Error(
    `Timed out waiting for layout revision ${minimumRevision}; current=${snapshot?.presentation?.layout_revision}`,
  );
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
    on(method, listener) { listeners.set(method, [...(listeners.get(method) || []), listener]); },
    close() { ws.close(); },
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
  throw new Error(`Timed out waiting for: ${expression}`);
}

async function clickText(cdp, text, root = "document") {
  const clicked = await evaluate(cdp, `(() => {
    const scope = ${root};
    const node = Array.from(scope.querySelectorAll('button')).find((item) => (item.textContent || '').trim().includes(${JSON.stringify(text)}));
    node?.click();
    return Boolean(node);
  })()`);
  if (!clicked) throw new Error(`button not found: ${text}`);
}

async function clickTitle(cdp, title) {
  const clicked = await evaluate(cdp, `(() => {
    const node = document.querySelector('button[title=${JSON.stringify(title)}]');
    node?.click();
    return Boolean(node);
  })()`);
  if (!clicked) throw new Error(`button title not found: ${title}`);
}

async function screenshot(cdp, fileName) {
  const image = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
  const target = path.join(outputDir, fileName);
  await writeFile(target, Buffer.from(image.data, "base64"));
  return target;
}

async function metrics(cdp) {
  return evaluate(cdp, `(() => {
    const editor = document.querySelector('.study-schema-editor');
    const canvas = document.querySelector('.study-schema-canvas');
    const image = canvas?.querySelector('img');
    const rect = editor?.getBoundingClientRect();
    const visible = (node) => Boolean(node && node.getBoundingClientRect().width > 0 && node.getBoundingClientRect().height > 0);
    return {
      viewport: { width: innerWidth, height: innerHeight },
      pageOverflowX: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
      editorRect: rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height, right: rect.right, bottom: rect.bottom } : null,
      editorVisible: visible(editor),
      structureVisible: visible(document.querySelector('.study-schema-structure')),
      canvasVisible: visible(canvas),
      inspectorVisible: visible(document.querySelector('.study-schema-inspector')),
      imageVisible: visible(image),
      canvasOverflowX: canvas ? Math.max(0, canvas.scrollWidth - canvas.clientWidth) : -1,
      nodeCount: document.querySelectorAll('.study-schema-list-item').length,
      fullscreen: editor?.classList.contains('is-fullscreen') || false,
      buttons: Array.from(document.querySelectorAll('.study-schema-toolbar-actions button')).map((item) => (item.textContent || '').trim()),
      bodyTextLength: document.body.innerText.length,
    };
  })()`);
}

async function openCase(cdp, item, index, report) {
  report.activePhase = `${item.case_id}:navigate`;
  await cdp.send("Page.navigate", { url: appUrl });
  await waitForCondition(cdp, `document.body.textContent.includes('项目总看板')`);
  await waitForCondition(cdp, `Array.from(document.querySelectorAll('select[aria-label="选择临床研究项目"] option')).some((option) => option.value === ${JSON.stringify(item.project_id)})`);
  await evaluate(cdp, `(() => {
    const select = document.querySelector('select[aria-label="选择临床研究项目"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
    setter.call(select, ${JSON.stringify(item.project_id)});
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(item.project_id)}`);
  await waitForCondition(cdp, `document.querySelector('.project-meta')?.textContent.includes(${JSON.stringify(item.project_code)}) && document.querySelector('.project-meta')?.textContent.includes(${JSON.stringify(item.indication)})`);
  report.activePhase = `${item.case_id}:open-writing`;
  await clickText(cdp, "医学写作");
  await waitForCondition(cdp, `document.body.textContent.includes('研究方案文档编辑与AI修订')`);
  await clickTitle(cdp, "打开研究方案目录");
  await waitForCondition(cdp, `Boolean(document.querySelector('.writing-document-map-drawer'))`);
  await evaluate(cdp, `(() => {
    const input = document.querySelector('.writing-document-map-search input');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, '试验示意图');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await waitForCondition(cdp, `Array.from(document.querySelectorAll('.writing-section-buttons button')).some((node) => (node.textContent || '').includes('试验示意图'))`);
  await clickText(cdp, "试验示意图", "document.querySelector('.writing-section-buttons')");
  await waitForCondition(cdp, `Boolean(document.querySelector('.study-schema-editor')) && Boolean(document.querySelector('.study-schema-canvas img'))`);
  await waitForCondition(cdp, `Array.from(document.querySelectorAll('.study-schema-toolbar-actions button')).some((node) => ['已同步方案', '更新方案'].some((label) => (node.textContent || '').includes(label)))`);
  const recoveredPendingProjection = await evaluate(cdp, `(() => {
    const node = Array.from(document.querySelectorAll('.study-schema-toolbar-actions button')).find((item) => (item.textContent || '').includes('更新方案'));
    if (!node || node.disabled) return false;
    node.click();
    return true;
  })()`);
  if (recoveredPendingProjection) {
    await waitForCondition(cdp, `document.body.textContent.includes('方案中的研究流程图已更新')`);
    await waitForCondition(cdp, `Array.from(document.querySelectorAll('.study-schema-toolbar-actions button')).some((node) => (node.textContent || '').includes('已同步方案'))`);
  }

  report.activePhase = `${item.case_id}:initial-metrics`;
  const result = { caseId: item.case_id, projectId: item.project_id, expectedNodeCount: item.node_count, states: {} };
  result.states.initial = await metrics(cdp);
  result.states.initialScreenshot = await screenshot(cdp, `${index + 1}_${item.case_id}_initial.png`);
  if (result.states.initial.pageOverflowX > 0) throw new Error(`${item.case_id}: page horizontal overflow`);
  if (!result.states.initial.editorVisible || !result.states.initial.structureVisible || !result.states.initial.canvasVisible || !result.states.initial.inspectorVisible || !result.states.initial.imageVisible) {
    throw new Error(`${item.case_id}: primary study-schema panes are not visible`);
  }
  if (result.states.initial.nodeCount !== item.node_count) throw new Error(`${item.case_id}: node count mismatch`);

  report.activePhase = `${item.case_id}:edit-parts`;
  await clickText(cdp, "研究部分", "document.querySelector('.study-schema-editor')");
  await waitForCondition(cdp, `document.querySelector('.study-schema-tabs button.active')?.textContent.includes('研究部分')`);
  const partCount = await evaluate(cdp, `document.querySelectorAll('.study-schema-form-row').length`);
  await clickText(cdp, "新增研究部分", "document.querySelector('.study-schema-editor')");
  await waitForCondition(cdp, `document.querySelectorAll('.study-schema-form-row').length === ${partCount + 1}`);
  await clickTitle(cdp, "重新读取服务器版本");
  await waitForCondition(cdp, `document.querySelectorAll('.study-schema-form-row').length === ${partCount}`);

  report.activePhase = `${item.case_id}:edit-nodes`;
  await clickText(cdp, "节点", "document.querySelector('.study-schema-editor')");
  await waitForCondition(cdp, `document.querySelector('.study-schema-tabs button.active')?.textContent.includes('节点')`);
  await clickText(cdp, "撤回确认", "document.querySelector('.study-schema-inspector')");
  await waitForCondition(cdp, `document.querySelector('.study-schema-fact-state strong')?.textContent.includes('待医学确认')`);
  await clickText(cdp, "确认该节点", "document.querySelector('.study-schema-inspector')");
  await waitForCondition(cdp, `document.querySelector('.study-schema-fact-state strong')?.textContent.includes('医学已确认')`);
  await clickText(cdp, "新增节点", "document.querySelector('.study-schema-editor')");
  await waitForCondition(cdp, `document.querySelectorAll('.study-schema-list-item').length === ${item.node_count + 1}`);
  await waitForCondition(cdp, `document.querySelector('.study-schema-list-item.active')?.textContent.includes('新节点')`);
  await clickText(cdp, "删除节点", "document.querySelector('.study-schema-inspector')");
  await waitForCondition(cdp, `document.querySelectorAll('.study-schema-list-item').length === ${item.node_count}`);

  report.activePhase = `${item.case_id}:edit-edges`;
  await clickText(cdp, "关系", "document.querySelector('.study-schema-editor')");
  const edgeCount = await evaluate(cdp, `document.querySelectorAll('.study-schema-list-item').length`);
  await clickText(cdp, "新增关系", "document.querySelector('.study-schema-editor')");
  await waitForCondition(cdp, `document.querySelectorAll('.study-schema-list-item').length === ${edgeCount + 1}`);
  await waitForCondition(cdp, `(() => { const items = Array.from(document.querySelectorAll('.study-schema-list-item')); return items.indexOf(document.querySelector('.study-schema-list-item.active')) === items.length - 1; })()`);
  await clickText(cdp, "删除关系", "document.querySelector('.study-schema-inspector')");
  await waitForCondition(cdp, `document.querySelectorAll('.study-schema-list-item').length === ${edgeCount}`);

  report.activePhase = `${item.case_id}:layout-and-project`;
  await clickText(cdp, "节点", "document.querySelector('.study-schema-editor')");
  const layoutBeforeNudge = await json(
    `${apiUrl}/api/projects/${item.project_id}/medical-writing/authoring-journey/study-schema`,
  );
  await clickTitle(cdp, "向右微调");
  const layoutAfterNudge = await waitForLayoutRevision(
    item.project_id,
    layoutBeforeNudge.presentation.layout_revision + 1,
  );
  await waitForCondition(cdp, `Array.from(document.querySelectorAll('.study-schema-toolbar-actions button')).some((node) => (node.textContent || '').includes('自动排布') && !node.disabled)`);
  await clickText(cdp, "自动排布", "document.querySelector('.study-schema-toolbar-actions')");
  await waitForLayoutRevision(item.project_id, layoutAfterNudge.presentation.layout_revision + 1);
  await waitForCondition(cdp, `Array.from(document.querySelectorAll('.study-schema-toolbar-actions button')).some((node) => (node.textContent || '').includes('更新方案') && !node.disabled)`);
  await clickText(cdp, "更新方案", "document.querySelector('.study-schema-toolbar-actions')");
  await waitForCondition(cdp, `document.body.textContent.includes('方案中的研究流程图已更新')`);

  report.activePhase = `${item.case_id}:fullscreen`;
  await clickTitle(cdp, "最大化流程图编辑器");
  await waitForCondition(cdp, `document.querySelector('.study-schema-editor')?.classList.contains('is-fullscreen')`);
  result.states.fullscreen = await metrics(cdp);
  result.states.fullscreenScreenshot = await screenshot(cdp, `${index + 1}_${item.case_id}_fullscreen.png`);
  if (!result.states.fullscreen.fullscreen || result.states.fullscreen.editorRect.x < 14 || result.states.fullscreen.editorRect.right > 1922 || result.states.fullscreen.editorRect.bottom > 1082) {
    throw new Error(`${item.case_id}: fullscreen editor is outside the desktop viewport`);
  }
  await clickTitle(cdp, "退出最大化");
  await waitForCondition(cdp, `!document.querySelector('.study-schema-editor')?.classList.contains('is-fullscreen')`);
  report.activePhase = `${item.case_id}:reload`;
  await clickTitle(cdp, "重新读取服务器版本");
  await waitForCondition(cdp, `Array.from(document.querySelectorAll('.study-schema-toolbar-actions button')).some((node) => (node.textContent || '').includes('已同步方案'))`);
  result.states.reloaded = await metrics(cdp);

  const snapshot = await json(`${apiUrl}/api/projects/${item.project_id}/medical-writing/authoring-journey/study-schema`);
  const workingCopy = await json(`${apiUrl}/api/projects/${item.project_id}/medical-writing/working-copies/${item.section_id}`);
  const figure = workingCopy.content_blocks.find((block) => block.figure_kind === "study_schema");
  result.persisted = {
    layoutRevision: snapshot.presentation.layout_revision,
    schemaRevision: snapshot.study_schema.revision,
    workingCopyRevision: workingCopy.revision,
    figureCurrent: Boolean(figure && figure.schema_state_sha256 === snapshot.study_schema.state_sha256 && figure.layout_revision === snapshot.presentation.layout_revision),
    figureCount: workingCopy.content_blocks.filter((block) => block.figure_kind === "study_schema").length,
  };
  if (!result.persisted.figureCurrent || result.persisted.figureCount !== 1 || result.persisted.layoutRevision < 2) {
    throw new Error(`${item.case_id}: persisted layout/figure state is inconsistent`);
  }
  return result;
}

async function main() {
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const apiReport = JSON.parse(await readFile(reportPath, "utf8"));
  const projects = await json(`${apiUrl}/api/projects`);
  const projectById = new Map(projects.map((project) => [project.project_id, project]));
  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-study-schema-browser-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  const report = { passed: false, appUrl, apiUrl, errors: [], runtimeExceptions: [], consoleErrors: [], cases: [], activePhase: "bootstrap" };
  let cdp;
  try {
    await waitForJson(`${apiUrl}/api/health`);
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    cdp = createCdp(targets.find((item) => item.type === "page").webSocketDebuggerUrl);
    await cdp.ready;
    cdp.on("Runtime.exceptionThrown", (event) => report.runtimeExceptions.push({
      phase: report.activePhase,
      description: event.exceptionDetails?.exception?.description || event.exceptionDetails?.text,
      url: event.exceptionDetails?.url || "",
      lineNumber: event.exceptionDetails?.lineNumber,
      columnNumber: event.exceptionDetails?.columnNumber,
      stack: event.exceptionDetails?.stackTrace?.callFrames || [],
      exception: event.exceptionDetails?.exception || null,
    }));
    cdp.on("Runtime.consoleAPICalled", (event) => {
      if (event.type !== "error") return;
      report.consoleErrors.push({
        phase: report.activePhase,
        args: (event.args || []).map((arg) => ({
          type: arg.type,
          value: arg.value,
          description: arg.description,
          preview: arg.preview,
        })),
        stack: event.stackTrace?.callFrames || [],
      });
    });
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    for (const [index, rawItem] of apiReport.cases.entries()) {
      const project = projectById.get(rawItem.project_id);
      if (!project) throw new Error(`project metadata not found: ${rawItem.project_id}`);
      const item = { ...rawItem, project_code: project.project_code, indication: project.indication };
      report.cases.push(await openCase(cdp, item, index, report));
    }
    report.passed = report.cases.length === 2 && report.runtimeExceptions.length === 0;
  } catch (error) {
    report.errors.push(error.stack || error.message);
    if (cdp) report.failureScreenshot = await screenshot(cdp, "99_failure.png").catch(() => "");
  } finally {
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(250);
    await rm(userDataDir, { recursive: true, force: true });
  }
  const target = path.join(outputDir, "browser_qc_report.json");
  await writeFile(target, JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ report: target, passed: report.passed, errors: report.errors, cases: report.cases.map((item) => item.caseId) }, null, 2));
  if (!report.passed) process.exitCode = 1;
}

await main();
