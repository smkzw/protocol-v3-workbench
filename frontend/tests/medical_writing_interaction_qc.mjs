import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(scriptDir, "../../records/visual_qc_20260711/medical_writing_interactions");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9382);
const projects = [
  { projectId: "proj_rux_03_002", projectCode: "RUX-03-002" },
  { projectId: "proj_d001", projectCode: "CMS-D001" },
];

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  return { response, payload };
}

async function requestJson(url) {
  const { response, payload } = await request(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return payload;
}

async function waitForJson(url, timeoutMs = 15000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await requestJson(url);
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
  const ready = new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result);
  });
  return {
    ready,
    send(method, params = {}) {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ id, method, params }));
      });
    },
    close() {
      ws.close();
    },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Runtime.evaluate failed");
  return result.result.value;
}

async function waitForCondition(cdp, expression, timeoutMs = 45000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(200);
  }
  throw new Error(`Timed out waiting for condition: ${expression}; last=${JSON.stringify(lastValue)}`);
}

async function clickExact(cdp, label, selector = "button") {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
        .find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)} && !item.disabled);
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) {
    const diagnostic = await evaluate(cdp, `({
      buttons: Array.from(document.querySelectorAll(${JSON.stringify(selector)})).map((item) => ({
        label: (item.textContent || "").trim(),
        disabled: item.disabled,
        title: item.title,
      })),
      workingCopy: document.querySelector(".working-copy-status-bar")?.textContent || "",
      message: document.querySelector(".working-copy-message")?.textContent || "",
      structureError: document.querySelector(".working-copy-message.danger")?.textContent || "",
    })`);
    throw new Error(`Enabled button not found: ${selector}/${label}; diagnostic=${JSON.stringify(diagnostic)}`);
  }
}

async function clickIncludes(cdp, label, selector = "button") {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
        .find((item) => (item.textContent || "").includes(${JSON.stringify(label)}) && !item.disabled);
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Enabled button not found containing: ${selector}/${label}`);
}

async function selectProject(cdp, projectId) {
  const selected = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select || !Array.from(select.options).some((option) => option.value === ${JSON.stringify(projectId)})) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!selected) throw new Error(`Project switch failed: ${projectId}`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function findFreshEditableSection(projectId) {
  const session = await requestJson(new URL(`/api/projects/${projectId}/medical-writing/document-session`, appUrl));
  for (let index = 0; index < Math.min(session.sections.length, 60); index += 1) {
    const section = session.sections[index];
    const content = await requestJson(new URL(`/api/projects/${projectId}/medical-writing/document-session/sections/${section.section_id}`, appUrl));
    const copy = await requestJson(new URL(`/api/projects/${projectId}/medical-writing/working-copies/${section.section_id}`, appUrl));
    const editable = (content.content_blocks || []).find((block) => block.block_type !== "table" && String(block.text || "").trim());
    if (copy.revision === 0 && editable) return { session, section, sectionIndex: index, content, copy, editable };
  }
  throw new Error(`No fresh editable section found for ${projectId}`);
}

async function selectWritingSection(cdp, sectionIndex, heading) {
  await waitForCondition(cdp, `document.querySelectorAll(".writing-section-buttons > button").length > ${sectionIndex}`);
  await evaluate(cdp, `document.querySelectorAll(".writing-section-buttons > button")[${sectionIndex}].click()`);
  await waitForCondition(cdp, `document.querySelector(".writing-section-strip-head strong")?.textContent?.trim() === ${JSON.stringify(heading)}`);
  await waitForCondition(cdp, `document.querySelector(".protocol-editor .ProseMirror") && !document.querySelector(".working-copy-revision")?.textContent.includes("读取中")`);
}

async function prepareEditorCaret(cdp) {
  const prepared = await evaluate(cdp, `
    (() => {
      const root = document.querySelector(".protocol-editor .ProseMirror");
      const block = root?.querySelector("p, h1, h2, h3, h4, h5, h6");
      if (!root || !block || root.getAttribute("contenteditable") !== "true") return false;
      root.focus();
      const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
      let textNode;
      let candidate;
      while ((candidate = walker.nextNode())) textNode = candidate;
      if (!textNode) return false;
      const range = document.createRange();
      range.setStart(textNode, textNode.textContent.length);
      range.collapse(true);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      return selection.anchorNode === textNode
        && selection.anchorOffset === textNode.textContent.length;
    })()
  `);
  if (!prepared) throw new Error("Editable ProseMirror block not available");
}

async function insertEditorSuffix(cdp, suffix) {
  await prepareEditorCaret(cdp);
  await cdp.send("Input.insertText", { text: suffix });
  await waitForCondition(cdp, `document.querySelector(".working-copy-status-bar")?.textContent.includes("有未保存修订")`);
}

async function exerciseDiscardReloadHydration(cdp, projectId, sectionId, persistedMarker, token) {
  const baseline = await requestJson(
    new URL(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`, appUrl),
  );
  const unsavedMarker = `[UNSAVED-HEADING-${token}]`;
  const beforeIdentity = await evaluate(cdp, `({
    tables: Array.from(document.querySelectorAll(".protocol-editor table[data-source-block-id]"))
      .map((table) => table.getAttribute("data-source-block-id")),
    cells: Array.from(document.querySelectorAll(".protocol-editor [data-cell-id]"))
      .map((cell) => cell.getAttribute("data-cell-id")),
  })`);
  const headingPrepared = await evaluate(cdp, `
    (() => {
      const root = document.querySelector(".protocol-editor .ProseMirror");
      const heading = root?.querySelector(".protocol-source-block h1, .protocol-source-block h2, .protocol-source-block h3, .protocol-source-block h4, .protocol-source-block h5, .protocol-source-block h6");
      if (!root || !heading || root.getAttribute("contenteditable") !== "true") return false;
      root.focus();
      const walker = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
      let textNode;
      let candidate;
      while ((candidate = walker.nextNode())) textNode = candidate;
      if (!textNode) return false;
      const range = document.createRange();
      range.setStart(textNode, textNode.textContent.length);
      range.collapse(true);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      return selection.anchorNode === textNode
        && selection.anchorOffset === textNode.textContent.length;
    })()
  `);
  if (!headingPrepared) throw new Error("Reload hydration QC requires an editable source heading");
  await wait(150);
  await cdp.send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
  });
  await cdp.send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
  });
  await cdp.send("Input.insertText", { text: unsavedMarker });
  await waitForCondition(
    cdp,
    `document.querySelector(".protocol-editor .ProseMirror")?.innerText.includes(${JSON.stringify(unsavedMarker)})
      && document.querySelector(".working-copy-status-bar")?.textContent.includes("有未保存修订")`,
  );

  await clickExact(cdp, "重新加载", ".working-copy-actions button");
  await waitForCondition(cdp, `Boolean(document.querySelector('[aria-label="未保存修订处理"]'))`);
  await clickExact(cdp, "丢弃并重新加载", '[aria-label="未保存修订处理"] button');
  await waitForCondition(
    cdp,
    `!document.querySelector(".protocol-editor .ProseMirror")?.innerText.includes(${JSON.stringify(unsavedMarker)})
      && document.querySelector(".protocol-editor .ProseMirror")?.innerText.includes(${JSON.stringify(persistedMarker)})
      && !document.querySelector(".working-copy-status-bar")?.textContent.includes("有未保存修订")`,
  );

  const reloaded = await requestJson(
    new URL(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`, appUrl),
  );
  const afterState = await evaluate(cdp, `(() => {
    const selection = window.getSelection();
    return {
      tables: Array.from(document.querySelectorAll(".protocol-editor table[data-source-block-id]"))
        .map((table) => table.getAttribute("data-source-block-id")),
      cells: Array.from(document.querySelectorAll(".protocol-editor [data-cell-id]"))
        .map((cell) => cell.getAttribute("data-cell-id")),
      selectionConnected: !selection?.anchorNode || selection.anchorNode.isConnected,
      dirty: document.querySelector(".working-copy-status-bar")?.textContent.includes("有未保存修订") || false,
      structureError: document.querySelector(".working-copy-structure-error, .working-copy-message.danger")?.textContent || "",
      domHasUnsavedMarker: document.querySelector(".protocol-editor .ProseMirror")?.innerText.includes(${JSON.stringify(unsavedMarker)}) || false,
    };
  })()`);
  if (reloaded.revision !== baseline.revision || reloaded.content_sha256 !== baseline.content_sha256) {
    throw new Error(`Server working copy changed during discard reload: ${JSON.stringify({
      beforeRevision: baseline.revision,
      afterRevision: reloaded.revision,
      beforeHash: baseline.content_sha256,
      afterHash: reloaded.content_sha256,
    })}`);
  }
  if (JSON.stringify(reloaded.content_blocks).includes(unsavedMarker)) {
    throw new Error("Unsaved heading marker reached the server working copy");
  }
  if (
    afterState.domHasUnsavedMarker
    || afterState.dirty
    || !afterState.selectionConnected
    || JSON.stringify(afterState.tables) !== JSON.stringify(beforeIdentity.tables)
    || JSON.stringify(afterState.cells) !== JSON.stringify(beforeIdentity.cells)
  ) {
    throw new Error(`Discard reload hydration failed: ${JSON.stringify({ beforeIdentity, afterState })}`);
  }
  return {
    baselineRevision: baseline.revision,
    reloadedRevision: reloaded.revision,
    serverHashUnchanged: reloaded.content_sha256 === baseline.content_sha256,
    tableIdentityPreserved: JSON.stringify(afterState.tables) === JSON.stringify(beforeIdentity.tables),
    cellIdentityPreserved: JSON.stringify(afterState.cells) === JSON.stringify(beforeIdentity.cells),
    selectionConnected: afterState.selectionConnected,
    dirty: afterState.dirty,
    structureError: afterState.structureError,
  };
}

async function clickToolbar(cdp, title) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".rich-toolbar button")).find((item) => item.title === ${JSON.stringify(title)});
      if (!button || button.disabled) return false;
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Rich toolbar button unavailable: ${title}`);
  await wait(100);
}

async function exerciseRichToolbar(cdp, token) {
  const results = [];
  await prepareEditorCaret(cdp);
  const initialTag = await evaluate(cdp, `document.querySelector(".protocol-editor .ProseMirror > :first-child")?.tagName`);
  await clickToolbar(cdp, "H1");
  const toggledTag = await evaluate(cdp, `document.querySelector(".protocol-editor .ProseMirror > :first-child")?.tagName`);
  if (toggledTag === initialTag) throw new Error("Rich toolbar heading command had no DOM effect");
  await clickToolbar(cdp, "H1");
  const restoredTag = await evaluate(cdp, `document.querySelector(".protocol-editor .ProseMirror > :first-child")?.tagName`);
  if (restoredTag !== initialTag) throw new Error("Rich toolbar heading command did not restore");
  results.push({ title: "H1", toggled: true, restored: true });

  for (const [title, selector, marker] of [
    ["B", "strong", `[B-${token}]`],
    ["I", "em", `[I-${token}]`],
  ]) {
    await prepareEditorCaret(cdp);
    await clickToolbar(cdp, title);
    await cdp.send("Input.insertText", { text: marker });
    await waitForCondition(cdp, `Array.from(document.querySelectorAll(${JSON.stringify(`.protocol-editor .ProseMirror ${selector}`)})).some((item) => item.textContent.includes(${JSON.stringify(marker)}))`);
    await clickToolbar(cdp, title);
    results.push({ title, toggled: true, restored: true, marker });
  }

  for (const [title, selector] of [["列表", "ul"], ["编号", "ol"]]) {
    await prepareEditorCaret(cdp);
    await clickToolbar(cdp, title);
    await waitForCondition(cdp, `Boolean(document.querySelector(${JSON.stringify(`.protocol-editor .ProseMirror ${selector}`)}))`);
    await clickToolbar(cdp, title);
    await waitForCondition(cdp, `!document.querySelector(${JSON.stringify(`.protocol-editor .ProseMirror ${selector}`)})`);
    results.push({ title, toggled: true, restored: true });
  }
  return results;
}

async function runProject(cdp, project) {
  await selectProject(cdp, project.projectId);
  await clickExact(cdp, "医学写作", ".nav-item");
  await waitForCondition(cdp, `document.body.textContent.includes("研究方案文档编辑与AI修订")`);
  const target = await findFreshEditableSection(project.projectId);
  await selectWritingSection(cdp, target.sectionIndex, target.section.heading);

  await clickExact(cdp, "刷新", ".revision-thread-head button");
  await waitForCondition(cdp, `!document.querySelector(".revision-thread-head button")?.textContent.includes("读取中")`);
  await clickExact(cdp, "创建工作副本", ".working-copy-actions button");
  await waitForCondition(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.getAttribute("contenteditable") === "true"`);

  const scenarioToken = `${project.projectId}-author-freeze`;
  const richToolbar = await exerciseRichToolbar(cdp, scenarioToken);
  const suffix = ` [QC-${scenarioToken}-可审计修订]`;
  await insertEditorSuffix(cdp, suffix);
  await clickExact(cdp, "保存工作副本", ".working-copy-actions button");
  await waitForCondition(cdp, `document.querySelector(".working-copy-revision")?.textContent.trim() === "版本 1"`);

  const saved = await requestJson(new URL(`/api/projects/${project.projectId}/medical-writing/working-copies/${target.section.section_id}`, appUrl));
  const staleAttempt = await request(new URL(`/api/projects/${project.projectId}/medical-writing/working-copies/${target.section.section_id}`, appUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_id: saved.document_id,
      expected_revision: 0,
      content_blocks: saved.content_blocks,
      actor: "medical_manager",
      idempotency_key: `stale-qc-${scenarioToken}-${Date.now()}`,
    }),
  });
  if (staleAttempt.response.status !== 409) throw new Error(`${project.projectId}: stale save returned ${staleAttempt.response.status}`);

  await clickExact(cdp, "重新加载", ".working-copy-actions button");
  await waitForCondition(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.textContent.includes(${JSON.stringify(suffix)})`);
  const discardReloadHydration = await exerciseDiscardReloadHydration(
    cdp,
    project.projectId,
    target.section.section_id,
    suffix,
    scenarioToken,
  );

  await clickExact(cdp, "刷新资料包");
  await waitForCondition(cdp, `!Array.from(document.querySelectorAll("button")).some((button) => (button.textContent || "").trim() === "生成中")`);
  await waitForCondition(cdp, `Array.from(document.querySelectorAll("button")).some((button) => (button.textContent || "").trim() === "刷新引用候选" && !button.disabled)`);
  await clickExact(cdp, "刷新引用候选");
  await waitForCondition(cdp, `Array.from(document.querySelectorAll("button")).some((button) => (button.textContent || "").trim() === "刷新引用候选" && !button.disabled)`);

  await clickExact(cdp, "确认并冻结");
  await waitForCondition(cdp, `document.querySelector(".working-copy-status-bar")?.textContent.includes("当前作者确认版本 / 已冻结")`);
  const frozen = await requestJson(new URL(`/api/projects/${project.projectId}/medical-writing/working-copies/${target.section.section_id}`, appUrl));
  if (frozen.freeze_status !== "frozen") throw new Error(`${project.projectId}: working copy was not frozen`);
  const freezeScreenshot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
  const freezeScreenshotPath = path.join(outputDir, `${project.projectId}_author_frozen.png`);
  await writeFile(freezeScreenshotPath, Buffer.from(freezeScreenshot.data, "base64"));

  await clickExact(cdp, "解除冻结");
  await waitForCondition(cdp, `document.querySelector(".working-copy-status-bar")?.textContent.includes("编辑中") && document.querySelector(".protocol-editor .ProseMirror")?.getAttribute("contenteditable") === "true"`);
  const postAction = await requestJson(new URL(`/api/projects/${project.projectId}/medical-writing/working-copies/${target.section.section_id}`, appUrl));
  if (postAction.freeze_status !== "editable") throw new Error(`${project.projectId}: working copy was not unfrozen`);
  const screenshot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
  const screenshotPath = path.join(outputDir, `${project.projectId}_author_unfrozen.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return {
    projectId: project.projectId,
    sectionId: target.section.section_id,
    sectionHeading: target.section.heading,
    suffixPersisted: JSON.stringify(postAction.content_blocks).includes(suffix),
    revision: postAction.revision,
    freezeStatusBeforeUnfreeze: frozen.freeze_status,
    freezeStatusAfterUnfreeze: postAction.freeze_status,
    staleSaveStatus: staleAttempt.response.status,
    discardReloadHydration,
    richToolbar,
    aiGatewayConfigured: (await requestJson(new URL("/api/ai-gateway/status", appUrl))).configured,
    freezeScreenshotPath,
    screenshotPath,
  };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "medical-writing-interaction-qc-"));
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
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Chrome page target found");
    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);

    const results = [];
    for (const project of projects) results.push(await runProject(cdp, project));
    const failures = [];
    for (const result of results) {
      if (!result.suffixPersisted) failures.push(`${result.projectId}:suffix-not-persisted`);
      if (result.revision !== 1) failures.push(`${result.projectId}:revision-${result.revision}`);
      if (result.staleSaveStatus !== 409) failures.push(`${result.projectId}:stale-${result.staleSaveStatus}`);
      if (result.aiGatewayConfigured) failures.push(`${result.projectId}:unexpected-ai-provider`);
      if (result.richToolbar.length !== 5) failures.push(`${result.projectId}:toolbar-count`);
      if (result.richToolbar.some((item) => !item.toggled || !item.restored)) failures.push(`${result.projectId}:toolbar-action`);
    }
    const report = { appUrl, viewport: { width: 1600, height: 1000 }, results, failures };
    const reportPath = path.join(outputDir, "medical_writing_interaction_qc.json");
    await writeFile(reportPath, JSON.stringify(report, null, 2), "utf8");
    if (failures.length) throw new Error(`Medical writing interaction QC failed: ${failures.join(", ")}`);
    console.log(reportPath);
    cdp.close();
  } finally {
    chrome.kill("SIGTERM");
    await wait(300);
    await rm(userDataDir, { recursive: true, force: true });
  }
}

await main();
