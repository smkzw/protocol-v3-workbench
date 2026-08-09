import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5175/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(
  scriptDir,
  "../../records/active_slices/medical_writing_editor_formatting_20260714/browser_qc",
);
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9397);
const projects = [
  { projectId: "proj_rux_03_002", projectCode: "RUX-03-002" },
  { projectId: "proj_d001", projectCode: "CMS-D001" },
  { projectId: "proj_my008_pnh_3_01", projectCode: "MY008211A-PNH-3-01" },
];

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}\n${JSON.stringify(payload)}`);
  return payload;
}

async function waitForJson(url, timeoutMs = 20000) {
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
  const ready = new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const callback = pending.get(message.id);
    pending.delete(message.id);
    clearTimeout(callback.timer);
    if (message.error) callback.reject(new Error(message.error.message));
    else callback.resolve(message.result || {});
  });
  const rejectPending = (reason) => {
    for (const callback of pending.values()) {
      clearTimeout(callback.timer);
      callback.reject(reason);
    }
    pending.clear();
  };
  ws.addEventListener("close", () => rejectPending(new Error("CDP connection closed")));
  ws.addEventListener("error", () => rejectPending(new Error("CDP connection failed")));
  return {
    ready,
    send(method, params = {}) {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error(`CDP command timed out: ${method}`));
        }, 15000);
        pending.set(id, { resolve, reject, timer });
        ws.send(JSON.stringify({ id, method, params }));
      });
    },
    close() {
      ws.close();
    },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Runtime.evaluate failed");
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
  throw new Error(`Timed out waiting for condition: ${expression}; last=${JSON.stringify(lastValue)}`);
}

async function clickMatching(cdp, selector, label, exact = true) {
  const clicked = await evaluate(cdp, `
    (() => {
      const node = Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find((item) => {
        const text = (item.textContent || "").trim();
        return ${exact ? `text === ${JSON.stringify(label)}` : `text.includes(${JSON.stringify(label)})`} && !item.disabled;
      });
      if (!node) return false;
      node.scrollIntoView({ block: "center", inline: "nearest" });
      node.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Enabled element not found: ${selector}/${label}`);
}

async function clickAria(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const node = document.querySelector('[aria-label=${JSON.stringify(label)}]');
      if (!node || node.disabled) return false;
      node.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Enabled aria control not found: ${label}`);
}

async function setControlValue(cdp, ariaLabel, value) {
  const changed = await evaluate(cdp, `
    (() => {
      const control = document.querySelector('[aria-label=${JSON.stringify(ariaLabel)}]');
      if (!control || control.disabled) return false;
      const prototype = control.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, "value").set.call(control, ${JSON.stringify(value)});
      control.dispatchEvent(new Event("input", { bubbles: true }));
      control.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Control not available: ${ariaLabel}`);
}

async function selectProject(cdp, projectId) {
  await waitForCondition(cdp, `!document.querySelector('select[aria-label="选择临床研究项目"]')?.disabled`);
  await setControlValue(cdp, "选择临床研究项目", projectId);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function selectSection(cdp, projectId, sectionId) {
  const session = await request(new URL(`/api/projects/${projectId}/medical-writing/document-session`, appUrl));
  const index = session.sections.findIndex((section) => section.section_id === sectionId);
  if (index < 0) throw new Error(`Section not found: ${projectId}/${sectionId}`);
  const targetHeading = session.sections[index].heading;
  await waitForCondition(cdp, `document.querySelectorAll(".writing-section-buttons > button").length > ${index}`);
  await evaluate(cdp, `document.querySelectorAll(".writing-section-buttons > button")[${index}].click()`);
  await waitForCondition(cdp, `!document.querySelector(".writing-document-map-drawer")`);
  await waitForCondition(cdp, `document.querySelector(".rich-editor-meta")?.textContent.includes(${JSON.stringify(targetHeading)})`);
}

async function seedWorkingCopy(projectId) {
  const session = await request(new URL(`/api/projects/${projectId}/medical-writing/document-session`, appUrl));
  let selected;
  let sectionPayload;
  for (const section of session.sections) {
    const payload = await request(new URL(`/api/projects/${projectId}/medical-writing/document-session/sections/${section.section_id}`, appUrl));
    if ((payload.content_blocks || []).some((block) => block.block_type === "paragraph" && String(block.text || "").length >= 8)) {
      selected = section;
      sectionPayload = payload;
      break;
    }
  }
  if (!selected) throw new Error(`No editable paragraph section: ${projectId}`);
  const saved = await request(new URL(`/api/projects/${projectId}/medical-writing/working-copies/${selected.section_id}`, appUrl), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      document_id: selected.document_id,
      expected_revision: 0,
      content_blocks: sectionPayload.content_blocks,
      actor: "codex_editor_browser_qc",
      idempotency_key: `editor-format-qc-rich-import-v2-${projectId}`,
    }),
  });
  return { session, section: selected, saved };
}

async function openWriting(cdp, projectId, sectionId) {
  await selectProject(cdp, projectId);
  await clickMatching(cdp, ".nav-item", "医学写作");
  await waitForCondition(cdp, `document.body.textContent.includes("研究方案文档编辑与AI修订")`);
  await clickMatching(cdp, ".writing-title-actions button", "目录");
  await waitForCondition(cdp, `Boolean(document.querySelector(".writing-document-map-drawer"))`);
  await selectSection(cdp, projectId, sectionId);
  await waitForCondition(cdp, `!document.querySelector(".writing-document-map-drawer")`);
  await waitForCondition(cdp, `Boolean(document.querySelector(".protocol-editor .ProseMirror"))`);
  await waitForCondition(cdp, `Array.from(document.querySelectorAll(".protocol-editor .protocol-source-block > p, .protocol-editor .protocol-source-block > h1, .protocol-editor .protocol-source-block > h2, .protocol-editor .protocol-source-block > h3, .protocol-editor .protocol-source-block > h4, .protocol-editor .protocol-source-block > h5, .protocol-editor .protocol-source-block > h6")).some((item) => (item.textContent || "").trim().length >= 8)`);
  await waitForCondition(cdp, `document.querySelector(".working-copy-revision")?.textContent.includes("版本 ")`);
  await waitForCondition(cdp, `document.querySelectorAll(".rich-toolbar-row").length === 2`);
}

async function selectParagraphText(cdp, start, end) {
  const selected = await evaluate(cdp, `
    (() => {
      const paragraph = Array.from(document.querySelectorAll(
        ".protocol-editor .protocol-source-block > p, .protocol-editor .protocol-source-block > h1, .protocol-editor .protocol-source-block > h2, .protocol-editor .protocol-source-block > h3, .protocol-editor .protocol-source-block > h4, .protocol-editor .protocol-source-block > h5, .protocol-editor .protocol-source-block > h6",
      )).find((item) => (item.textContent || "").trim().length >= ${end});
      if (!paragraph) return false;
      const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
      const nodes = [];
      let total = 0;
      while (walker.nextNode()) {
        nodes.push({ node: walker.currentNode, start: total, end: total + walker.currentNode.data.length });
        total += walker.currentNode.data.length;
      }
      if (total < ${end}) return false;
      const locate = (offset) => {
        const item = nodes.find((candidate) => offset >= candidate.start && offset <= candidate.end) || nodes[nodes.length - 1];
        return { node: item.node, offset: Math.min(item.node.data.length, Math.max(0, offset - item.start)) };
      };
      const from = locate(${start});
      const to = locate(${end});
      paragraph.closest(".ProseMirror").focus();
      const range = document.createRange();
      range.setStart(from.node, from.offset);
      range.setEnd(to.node, to.offset);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      document.dispatchEvent(new Event("selectionchange", { bubbles: true }));
      paragraph.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      return selection.toString();
    })()
  `);
  if (!selected) throw new Error(`Paragraph text selection failed: ${start}-${end}`);
  await wait(100);
  return selected;
}

async function dispatchKey(cdp, {
  key,
  code = key,
  modifiers = 0,
  commands = undefined,
  windowsVirtualKeyCode = key.length === 1 ? key.toUpperCase().charCodeAt(0) : 0,
}) {
  await cdp.send("Input.dispatchKeyEvent", {
    type: modifiers ? "rawKeyDown" : "keyDown",
    key,
    code,
    modifiers,
    windowsVirtualKeyCode,
    nativeVirtualKeyCode: windowsVirtualKeyCode,
    ...(commands ? { commands } : {}),
  });
  await cdp.send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key,
    code,
    modifiers,
    windowsVirtualKeyCode,
    nativeVirtualKeyCode: windowsVirtualKeyCode,
  });
}

async function dispatchEditorShortcut(cdp, { key, code, shiftKey = false }) {
  return evaluate(cdp, `(() => {
    const editor = document.querySelector(".protocol-editor .ProseMirror");
    if (!editor) return false;
    editor.focus();
    return editor.dispatchEvent(new KeyboardEvent("keydown", {
      key: ${JSON.stringify(key)},
      code: ${JSON.stringify(code)},
      metaKey: true,
      shiftKey: ${shiftKey},
      bubbles: true,
      cancelable: true,
    }));
  })()`);
}

async function placeCaretAtEditableParagraphEnd(cdp) {
  const prepared = await evaluate(cdp, `
    (() => {
      const paragraph = Array.from(document.querySelectorAll(
        ".protocol-editor .protocol-source-block > p, .protocol-editor .protocol-source-block > h1, .protocol-editor .protocol-source-block > h2, .protocol-editor .protocol-source-block > h3, .protocol-editor .protocol-source-block > h4"
      )).find((item) => (item.textContent || "").trim().length >= 8);
      if (!paragraph) return false;
      paragraph.closest(".ProseMirror")?.focus();
      const range = document.createRange();
      range.selectNodeContents(paragraph);
      range.collapse(false);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      document.dispatchEvent(new Event("selectionchange", { bubbles: true }));
      paragraph.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      return paragraph.closest(".protocol-source-block")?.getAttribute("data-source-block-id") || false;
    })()
  `);
  if (!prepared) throw new Error("Editable paragraph caret could not be prepared");
  return prepared;
}

async function exerciseWordKeyboard(cdp, token) {
  const enterMarker = `[ENTER-${token}]`;
  const softMarker = `[SOFT-${token}]`;
  const boldMarker = `[BOLD-${token}]`;
  const undoMarker = `[UNDO-${token}]`;
  const sourceBlockId = await placeCaretAtEditableParagraphEnd(cdp);
  const sourceBlockSelector = `.protocol-editor [data-source-block-id="${sourceBlockId}"]`;
  await dispatchKey(cdp, { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  await cdp.send("Input.insertText", { text: enterMarker });
  await wait(500);
  const enterState = await evaluate(cdp, `(() => {
    const root = document.querySelector(".protocol-editor .ProseMirror");
    const block = root?.querySelector(${JSON.stringify(`[data-source-block-id="${sourceBlockId}"]`)});
    const selection = window.getSelection();
    return {
      activeElement: document.activeElement?.className || document.activeElement?.tagName,
      selectionAnchor: selection?.anchorNode?.parentElement?.outerHTML?.slice(0, 400) || "",
      sourceBlockHtml: block?.outerHTML?.slice(0, 1200) || "",
      sourceBlockNodeCount: block?.querySelectorAll("p, h1, h2, h3, h4").length || 0,
      structureError: document.querySelector(".working-copy-structure-error")?.innerText || "",
      status: document.querySelector(".working-copy-status-bar")?.innerText || "",
    };
  })()`);
  if (enterState.sourceBlockNodeCount < 2) {
    throw new Error(`Enter did not create a paragraph: ${JSON.stringify(enterState)}`);
  }
  await dispatchKey(cdp, { key: "Enter", code: "Enter", modifiers: 8, windowsVirtualKeyCode: 13 });
  await cdp.send("Input.insertText", { text: softMarker });
  await waitForCondition(cdp, `document.querySelector(${JSON.stringify(sourceBlockSelector)})?.innerText.includes(${JSON.stringify(softMarker)})`);

  await dispatchKey(cdp, { key: "b", code: "KeyB", modifiers: 4, windowsVirtualKeyCode: 66 });
  await cdp.send("Input.insertText", { text: boldMarker });
  await dispatchKey(cdp, { key: "b", code: "KeyB", modifiers: 4, windowsVirtualKeyCode: 66 });
  await waitForCondition(cdp, `Array.from(document.querySelectorAll(".protocol-editor strong")).some((node) => node.textContent.includes(${JSON.stringify(boldMarker)}))`);

  await cdp.send("Input.insertText", { text: "XY" });
  await dispatchKey(cdp, { key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 });
  await waitForCondition(cdp, `document.querySelector(${JSON.stringify(sourceBlockSelector)})?.innerText.includes("X") && !document.querySelector(${JSON.stringify(sourceBlockSelector)})?.innerText.includes("XY")`);

  await wait(700);
  await cdp.send("Input.insertText", { text: undoMarker });
  await wait(700);
  const undoBefore = await evaluate(cdp, `(() => {
    const button = document.querySelector('[aria-label="撤销"]');
    return {
      disabled: Boolean(button?.disabled),
      title: button?.title || "",
      sourceTextHasMarker: document.querySelector(${JSON.stringify(sourceBlockSelector)})?.innerText.includes(${JSON.stringify(undoMarker)}) || false,
    };
  })()`);
  console.log(`QC Word undo state: ${JSON.stringify(undoBefore)}`);
  await dispatchKey(cdp, {
    key: "z",
    code: "KeyZ",
    modifiers: 4,
    windowsVirtualKeyCode: 90,
  });
  await wait(100);
  const nativeUndoApplied = await evaluate(
    cdp,
    `!document.querySelector(${JSON.stringify(sourceBlockSelector)})?.innerText.includes(${JSON.stringify(undoMarker)})`,
  );
  if (!nativeUndoApplied) await dispatchEditorShortcut(cdp, { key: "z", code: "KeyZ" });
  await waitForCondition(
    cdp,
    `!document.querySelector(${JSON.stringify(sourceBlockSelector)})?.innerText.includes(${JSON.stringify(undoMarker)})`,
    3000,
  );
  await dispatchKey(cdp, {
    key: "z",
    code: "KeyZ",
    modifiers: 12,
    windowsVirtualKeyCode: 90,
  });
  await wait(100);
  const nativeRedoApplied = await evaluate(
    cdp,
    `document.querySelector(${JSON.stringify(sourceBlockSelector)})?.innerText.includes(${JSON.stringify(undoMarker)})`,
  );
  if (!nativeRedoApplied) await dispatchEditorShortcut(cdp, { key: "z", code: "KeyZ", shiftKey: true });
  await waitForCondition(
    cdp,
    `document.querySelector(${JSON.stringify(sourceBlockSelector)})?.innerText.includes(${JSON.stringify(undoMarker)})`,
    3000,
  );
  await assertWorkingCopyStructure(cdp, "Word keyboard matrix");
  return {
    enterMarker,
    softMarker,
    boldMarker,
    undoMarker,
    nativeUndoApplied,
    nativeRedoApplied,
  };
}

async function exerciseAnalysisSetTableInput(cdp, token) {
  await clickMatching(cdp, ".rich-table-template-button", "插入表格", false);
  await clickMatching(cdp, ".rich-table-template-popover button", "分析集定义", false);
  await waitForCondition(cdp, `Boolean(document.querySelector(".structured-table-designer"))`);
  const selected = await evaluate(cdp, `
    (() => {
      const cellButton = Array.from(document.querySelectorAll(".std-cell-select-button"))
        .find((button) => button.getAttribute("aria-label")?.includes("第 2 行第 2 列"));
      if (!cellButton) return false;
      cellButton.click();
      return true;
    })()
  `);
  if (!selected) throw new Error("Analysis-set editable cell was not found");
  await waitForCondition(cdp, `document.activeElement?.closest?.(".std-cell-rich-editor") !== null`);
  const initialCellId = await evaluate(
    cdp,
    `document.querySelector(".std-grid-table td.selected, .std-grid-table th.selected")?.getAttribute("data-cell-id") || ""`,
  );
  if (!initialCellId) throw new Error("Analysis-set selected cell identity was not exposed");
  const firstMarker = `[CELL-${token}]`;
  const lineMarker = `[CELL-LINE-${token}]`;
  const nextMarker = `[CELL-NEXT-${token}]`;
  await cdp.send("Input.insertText", { text: firstMarker });
  await dispatchKey(cdp, { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  await cdp.send("Input.insertText", { text: lineMarker });
  await dispatchKey(cdp, { key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
  await waitForCondition(cdp, `(() => {
    const selected = document.querySelector(".std-grid-table td.selected, .std-grid-table th.selected");
    return selected?.getAttribute("data-cell-id") !== ${JSON.stringify(initialCellId)}
      && document.activeElement?.closest?.(".std-cell-rich-editor") !== null;
  })()`);
  await cdp.send("Input.insertText", { text: nextMarker });
  await waitForCondition(cdp, `document.querySelector(".std-cell-rich-editor .ProseMirror")?.innerText.includes(${JSON.stringify(nextMarker)})`);
  await clickAria(cdp, "关闭表格设计器");
  await saveWorkingCopy(cdp);
  return { firstMarker, lineMarker, nextMarker };
}

async function setParagraphPopoverValue(cdp, label, value) {
  const changed = await evaluate(cdp, `
    (() => {
      const field = Array.from(document.querySelectorAll(".rich-paragraph-popover label")).find((item) => item.querySelector("span")?.textContent === ${JSON.stringify(label)});
      const input = field?.querySelector("input");
      if (!input) return false;
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, ${JSON.stringify(String(value))});
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Paragraph field unavailable: ${label}`);
}

async function assertWorkingCopyStructure(cdp, step) {
  const state = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".working-copy-actions button"))
        .find((item) => item.textContent.includes("保存工作副本"));
      return {
        disabled: Boolean(button?.disabled),
        title: button?.title || "",
        message: document.querySelector(".working-copy-message.danger")?.innerText || "",
      };
    })()
  `);
  if (state.title.includes("段落结构发生变化")) {
    throw new Error(`Structure gate failed after ${step}: ${JSON.stringify(state)}`);
  }
}

async function saveWorkingCopy(cdp) {
  await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("有未保存修订")`);
  try {
    await clickMatching(cdp, ".working-copy-actions button", "保存工作副本", false);
  } catch (error) {
    const state = await evaluate(cdp, `
      (() => {
        const button = Array.from(document.querySelectorAll(".working-copy-actions button"))
          .find((item) => item.textContent.includes("保存工作副本"));
        return {
          status: document.querySelector(".working-copy-status-bar")?.innerText || "",
          buttonDisabled: Boolean(button?.disabled),
          buttonTitle: button?.title || "",
          structureError: document.querySelector(".working-copy-structure-error")?.innerText
            || Array.from(document.querySelectorAll("[class*='error']"))
              .map((item) => item.innerText).filter(Boolean).join(" | "),
          editorTopLevelNodes: document.querySelector(".ProseMirror")?.children.length || 0,
        };
      })()
    `);
    throw new Error(`${error.message}; state=${JSON.stringify(state)}`);
  }
  await waitForCondition(cdp, `
    document.querySelector(".working-copy-status-main")?.textContent.includes("已保存")
    || document.querySelector(".working-copy-message")?.textContent.includes("保存被拒绝")
    || document.querySelector(".working-copy-message")?.textContent.includes("保存失败")
  `);
  const result = await evaluate(cdp, `({
    saved: document.querySelector(".working-copy-status-main")?.textContent.includes("已保存") || false,
    message: document.querySelector(".working-copy-message")?.textContent || "",
  })`);
  if (!result.saved) throw new Error(`Working-copy save failed: ${JSON.stringify(result)}`);
}

async function capture(cdp, filename, viewport) {
  await cdp.send("Emulation.setDeviceMetricsOverride", { ...viewport, deviceScaleFactor: 1, mobile: false });
  await evaluate(cdp, `new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
  await wait(500);
  await cdp.send("Page.bringToFront");
  const screenshot = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(path.join(outputDir, filename), Buffer.from(screenshot.data, "base64"));
}

async function exportDocx(projectId, filename) {
  const response = await fetch(new URL(`/api/projects/${projectId}/medical-writing/document.docx?mode=draft_preview`, appUrl));
  if (!response.ok) throw new Error(`DOCX export failed: ${projectId}/${response.status}`);
  await writeFile(path.join(outputDir, filename), Buffer.from(await response.arrayBuffer()));
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const runToken = `RUX-${Date.now().toString(36)}`;
  const seeded = Object.fromEntries(await Promise.all(projects.map(async (project) => [
    project.projectId,
    await seedWorkingCopy(project.projectId),
  ])));
  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-editor-format-qc-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "about:blank",
  ], { stdio: "ignore" });
  let cdp;
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const target = await request(`http://127.0.0.1:${debugPort}/json/new?${encodeURIComponent(appUrl)}`, { method: "PUT" }).catch(async () => {
      const targets = await request(`http://127.0.0.1:${debugPort}/json`);
      return targets.find((item) => item.type === "page");
    });
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 2048, height: 1024, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`);

    const rux = seeded.proj_rux_03_002;
    console.log("QC stage: open RUX writing editor");
    await openWriting(cdp, "proj_rux_03_002", rux.section.section_id);
    await selectParagraphText(cdp, 0, 4);
    await clickAria(cdp, "加粗");
    await assertWorkingCopyStructure(cdp, "bold");
    await clickAria(cdp, "下划线");
    await assertWorkingCopyStructure(cdp, "underline");
    await setControlValue(cdp, "字体", "黑体");
    await assertWorkingCopyStructure(cdp, "font");
    await setControlValue(cdp, "字号", "14pt");
    await assertWorkingCopyStructure(cdp, "font-size");
    await setControlValue(cdp, "文字颜色", "#C00000");
    await assertWorkingCopyStructure(cdp, "color");
    await setControlValue(cdp, "文字标黄", "#FFFF00");
    await assertWorkingCopyStructure(cdp, "highlight");
    await selectParagraphText(cdp, 4, 5);
    await clickAria(cdp, "上标");
    await assertWorkingCopyStructure(cdp, "superscript");
    await selectParagraphText(cdp, 5, 6);
    await clickAria(cdp, "下标");
    await assertWorkingCopyStructure(cdp, "subscript");
    await setControlValue(cdp, "段落样式", "body");
    await assertWorkingCopyStructure(cdp, "style preset");
    for (const alignment of ["居中", "右对齐", "左对齐", "两端对齐"]) await clickAria(cdp, alignment);
    await assertWorkingCopyStructure(cdp, "alignment");
    await clickAria(cdp, "增加左缩进");
    await assertWorkingCopyStructure(cdp, "increase indent");
    await clickAria(cdp, "减少左缩进");
    await assertWorkingCopyStructure(cdp, "decrease indent");
    await setControlValue(cdp, "行距", "1.5");
    await assertWorkingCopyStructure(cdp, "line height");
    await clickAria(cdp, "段落设置");
    await setParagraphPopoverValue(cdp, "首行缩进（字符）", 2);
    await setParagraphPopoverValue(cdp, "段前（磅）", 6);
    await setParagraphPopoverValue(cdp, "段后（磅）", 8);
    await clickAria(cdp, "段落设置");
    await assertWorkingCopyStructure(cdp, "paragraph settings");
    console.log("QC stage: RUX Word keyboard matrix");
    const keyboard = await exerciseWordKeyboard(cdp, runToken);
    console.log("QC stage: save RUX keyboard changes");
    await saveWorkingCopy(cdp);
    await capture(cdp, "rux_rich_editor_2048x1024.png", { width: 2048, height: 1024 });
    await capture(cdp, "rux_rich_editor_1920x1080.png", { width: 1920, height: 1080 });
    await selectParagraphText(cdp, 0, 4);
    await clickAria(cdp, "项目符号");
    await clickAria(cdp, "撤销");
    await waitForCondition(cdp, `!document.querySelector('[aria-label="重做"]')?.disabled`);
    await clickAria(cdp, "重做");
    await clickAria(cdp, "项目符号");
    await clickAria(cdp, "编号");
    await clickAria(cdp, "编号");
    await saveWorkingCopy(cdp);
    console.log("QC stage: RUX analysis-set input");
    const analysisSetInput = await exerciseAnalysisSetTableInput(cdp, runToken);

    console.log("QC stage: RUX custom table designer");
    await clickMatching(cdp, ".rich-table-template-button", "插入表格", false);
    await clickMatching(cdp, ".rich-table-template-popover button", "自定义结构化表格", false);
    await waitForCondition(cdp, `Boolean(document.querySelector(".rich-table-insert-dialog"))`);
    await capture(cdp, "rux_custom_table_dialog_1920x1080.png", { width: 1920, height: 1080 });
    const configured = await evaluate(cdp, `
      (() => {
        const dialog = document.querySelector(".rich-table-insert-dialog");
        const set = (label, value) => {
          const field = Array.from(dialog.querySelectorAll("label")).find((item) => item.querySelector("span")?.textContent === label);
          const input = field?.querySelector("input, select");
          if (!input) return false;
          const proto = input.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto, "value").set.call(input, value);
          input.dispatchEvent(new Event("input", { bubbles: true }));
          input.dispatchEvent(new Event("change", { bubbles: true }));
          return true;
        };
        return set("表题", "RUX浏览器自定义安全性表") && set("总行数", "8") && set("列数", "5") && set("表头行", "2") && set("页面方向", "landscape");
      })()
    `);
    if (!configured) throw new Error("Custom table dialog configuration failed");
    await clickMatching(cdp, ".rich-table-insert-dialog footer button", "插入并打开设计器", false);
    await waitForCondition(cdp, `Boolean(document.querySelector(".structured-table-designer"))`);
    await capture(cdp, "rux_custom_table_designer_1920x1080.png", { width: 1920, height: 1080 });
    await clickAria(cdp, "关闭表格设计器");

    const d001 = seeded.proj_d001;
    console.log("QC stage: open D001 writing editor");
    await openWriting(cdp, "proj_d001", d001.section.section_id);
    await selectParagraphText(cdp, 0, 5);
    await setControlValue(cdp, "段落样式", "heading_3");
    await setControlValue(cdp, "字体", "Arial");
    await setControlValue(cdp, "字号", "12pt");
    await clickAria(cdp, "斜体");
    await clickAria(cdp, "左对齐");
    await saveWorkingCopy(cdp);
    await capture(cdp, "d001_rich_editor_2048x1024.png", { width: 2048, height: 1024 });

    const pnh = seeded.proj_my008_pnh_3_01;
    console.log("QC stage: open PNH writing editor");
    await openWriting(cdp, "proj_my008_pnh_3_01", pnh.section.section_id);
    await capture(cdp, "pnh_rich_editor_2048x1024.png", { width: 2048, height: 1024 });

    const results = {};
    console.log("QC stage: read persisted copies and export DOCX");
    for (const project of projects) {
      const section = seeded[project.projectId].section;
      const copy = await request(new URL(`/api/projects/${project.projectId}/medical-writing/working-copies/${section.section_id}`, appUrl));
      results[project.projectId] = {
        sectionId: section.section_id,
        revision: copy.revision,
        textBlocksWithRichText: copy.content_blocks.filter((block) => block.rich_text).length,
        generatedTables: copy.content_blocks.filter((block) => block.source_kind === "medical_writing_template").map((block) => ({
          templateId: block.template_id,
          title: block.title,
          rows: block.rows?.length,
          columns: block.rows?.[0]?.length,
          headerRows: block.header_row_count,
          orientation: block.structured_table?.word_layout?.orientation,
          notesArea: block.structured_table?.word_layout?.notes_area_enabled,
        })),
      };
      await exportDocx(project.projectId, `${project.projectId}_rich_editor_draft.docx`);
    }
    const geometry = await evaluate(cdp, `
      (() => {
        const toolbar = document.querySelector(".rich-toolbar");
        const rows = Array.from(document.querySelectorAll(".rich-toolbar-row"));
        const rect = toolbar?.getBoundingClientRect();
        return {
          viewport: { width: innerWidth, height: innerHeight },
          toolbar: rect ? { width: rect.width, height: rect.height, right: rect.right } : null,
          rowCount: rows.length,
          rowHeights: rows.map((row) => row.getBoundingClientRect().height),
          noViewportOverflow: document.documentElement.scrollWidth <= innerWidth,
          visibleEditor: Boolean(document.querySelector(".protocol-editor .ProseMirror")),
          visibleAiRail: Boolean(document.querySelector(".ai-rail")),
        };
      })()
    `);
    if (!geometry.noViewportOverflow || geometry.rowCount !== 2 || geometry.toolbar?.height > 86 || !geometry.visibleEditor || !geometry.visibleAiRail) {
      throw new Error(`Desktop geometry failed: ${JSON.stringify(geometry)}`);
    }
    if (results.proj_rux_03_002.textBlocksWithRichText < 1) throw new Error("RUX rich text did not persist");
    const custom = results.proj_rux_03_002.generatedTables.find((item) => item.templateId === "generic_table");
    if (!custom || custom.rows !== 8 || custom.columns !== 5 || custom.headerRows !== 2 || custom.orientation !== "landscape" || !custom.notesArea) {
      throw new Error(`Custom table persistence failed: ${JSON.stringify(custom)}`);
    }
    if (results.proj_d001.textBlocksWithRichText < 1) throw new Error("D001 rich text did not persist");

    const report = {
      passed: true,
      appUrl,
      projects: results,
      keyboard,
      analysisSetInput,
      geometry,
      screenshots: [
        "rux_rich_editor_2048x1024.png",
        "rux_rich_editor_1920x1080.png",
        "rux_custom_table_dialog_1920x1080.png",
        "rux_custom_table_designer_1920x1080.png",
        "d001_rich_editor_2048x1024.png",
        "pnh_rich_editor_2048x1024.png",
      ],
    };
    await writeFile(path.join(outputDir, "medical_writing_editor_formatting_qc.json"), `${JSON.stringify(report, null, 2)}\n`);
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } finally {
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(300);
    await rm(userDataDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
