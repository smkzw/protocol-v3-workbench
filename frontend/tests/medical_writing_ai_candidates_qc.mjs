import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(
  scriptDir,
  "../../records/active_slices/medical_writing_workspace_usability_20260715/ai_candidates_browser_qc",
);
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9399);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const projectId = "proj_rux_03_002";
const sectionId = "mwsec_proj_rux_03_002_8783a740fc05_b0077f254a3a";
const sourceText = "评价磷酸芦可替尼乳膏治疗特应性皮炎（AD）的有效性。";

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}: ${JSON.stringify(payload)}`);
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
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(200);
  }
  throw new Error(`Timed out waiting for ${expression}; last=${JSON.stringify(lastValue)}`);
}

async function clickMatching(cdp, selector, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const node = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
        .find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)} && !item.disabled);
      if (!node) return false;
      node.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Enabled control not found: ${selector}/${label}`);
}

async function selectProject(cdp) {
  const changed = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select || select.disabled) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error("Project switcher unavailable");
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function selectSection(cdp, sectionIndex) {
  await clickMatching(cdp, ".writing-title-actions button", "目录");
  await waitForCondition(cdp, "Boolean(document.querySelector('.writing-document-map-drawer'))");
  await waitForCondition(cdp, `document.querySelectorAll('.writing-section-buttons > button').length > ${sectionIndex}`);
  await evaluate(cdp, `document.querySelectorAll('.writing-section-buttons > button')[${sectionIndex}].click()`);
  await waitForCondition(cdp, "!document.querySelector('.writing-document-map-drawer')");
  await waitForCondition(cdp, `document.querySelector('.rich-editor-meta')?.textContent.includes('主要试验目的')`);
}

async function selectExactText(cdp, text) {
  const selected = await evaluate(cdp, `
    (() => {
      const root = document.querySelector('.protocol-editor .ProseMirror');
      if (!root) return '';
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const index = node.data.indexOf(${JSON.stringify(text)});
        if (index < 0) continue;
        root.focus();
        const range = document.createRange();
        range.setStart(node, index);
        range.setEnd(node, index + ${JSON.stringify(text)}.length);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        document.dispatchEvent(new Event('selectionchange', { bubbles: true }));
        node.parentElement?.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
        return selection.toString();
      }
      return '';
    })()
  `);
  if (selected !== text) throw new Error(`Could not select exact source text; selected=${selected}`);
}

async function screenshot(cdp, filename) {
  const image = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const outputPath = path.join(outputDir, filename);
  await writeFile(outputPath, Buffer.from(image.data, "base64"));
  return outputPath;
}

async function ensureWorkingCopy(sectionPayload) {
  const endpoint = new URL(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`, appUrl);
  let current = await request(endpoint);
  if ((current.revision || 0) < 1) {
    current = await request(endpoint, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        document_id: sectionPayload.document_id,
        expected_revision: 0,
        content_blocks: sectionPayload.content_blocks,
        actor: "codex_ai_candidate_browser_qc",
        idempotency_key: "ai-candidate-browser-qc-create-v1",
      }),
    });
  }
  return current;
}

async function restoreWorkingCopy(contentBlocks) {
  const endpoint = new URL(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`, appUrl);
  const latest = await request(endpoint);
  const restored = await request(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      document_id: latest.document_id,
      expected_revision: latest.revision,
      content_blocks: contentBlocks,
      actor: "codex_ai_candidate_browser_qc_restore",
      idempotency_key: `ai-candidate-browser-qc-restore-v1-r${latest.revision}`,
    }),
  });
  return restored;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const session = await request(new URL(`/api/projects/${projectId}/medical-writing/document-session`, appUrl));
  const sectionIndex = session.sections.findIndex((item) => item.section_id === sectionId);
  if (sectionIndex < 0) throw new Error(`Section missing: ${sectionId}`);
  const sectionPayload = await request(new URL(`/api/projects/${projectId}/medical-writing/document-session/sections/${sectionId}`, appUrl));
  const baseline = await ensureWorkingCopy(sectionPayload);
  const backupBlocks = structuredClone(baseline.content_blocks);
  const userDataDir = await mkdtemp(path.join(tmpdir(), "medical-writing-ai-candidates-"));
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
  let cdp;
  let report;
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    const target = targets.find((item) => item.type === "page");
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    cdp.on("Runtime.exceptionThrown", (event) => errors.push(event.exceptionDetails?.exception?.description || event.exceptionDetails?.text));
    cdp.on("Network.responseReceived", (event) => {
      const url = event.response?.url || "";
      if (url.includes("/api/") && event.response.status >= 400) apiFailures.push({ status: event.response.status, url });
    });
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes('项目总看板')`);
    await selectProject(cdp);
    await clickMatching(cdp, ".nav-item", "医学写作");
    await waitForCondition(cdp, `document.body.textContent.includes('研究方案文档编辑与AI修订')`);
    await selectSection(cdp, sectionIndex);
    await waitForCondition(cdp, "document.querySelector('.protocol-editor .ProseMirror')?.getAttribute('contenteditable') === 'true'");
    const candidateCount = await waitForCondition(cdp, "document.querySelectorAll('.writing-ai-candidates article').length >= 4 && document.querySelectorAll('.writing-ai-candidates article').length");
    const candidateText = await evaluate(cdp, "document.querySelectorAll('.writing-ai-candidates article p')[1]?.textContent?.trim() || ''");
    await selectExactText(cdp, sourceText);
    await evaluate(cdp, "document.querySelectorAll('.writing-ai-candidates article button')[1]?.click()");
    await waitForCondition(cdp, `document.querySelector('.working-copy-message, .revision-message')?.textContent?.includes('候选文本已写入') || document.body.textContent.includes('候选文本已写入当前工作副本')`);
    await waitForCondition(cdp, `document.querySelector('.protocol-editor .ProseMirror')?.innerText.includes(${JSON.stringify(candidateText)})`);
    const afterInsertText = await evaluate(cdp, "document.querySelector('.protocol-editor .ProseMirror')?.innerText || ''");
    const saveEnabled = await waitForCondition(cdp, `Array.from(document.querySelectorAll('.working-copy-actions button')).some((item) => item.textContent.includes('保存工作副本') && !item.disabled)`);
    await evaluate(cdp, `Array.from(document.querySelectorAll('.working-copy-actions button')).find((item) => item.textContent.includes('保存工作副本') && !item.disabled)?.click()`);
    await waitForCondition(cdp, `document.querySelector('.working-copy-status-bar')?.textContent.includes('已保存') && !document.querySelector('.working-copy-status-bar')?.textContent.includes('有未保存修订')`, 45000);
    const saved = await request(new URL(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`, appUrl));
    await evaluate(cdp, `Array.from(document.querySelectorAll('.working-copy-actions button')).find((item) => item.textContent.includes('重新加载') && !item.disabled)?.click()`);
    await waitForCondition(cdp, `document.querySelector('.protocol-editor .ProseMirror')?.innerText.includes(${JSON.stringify(candidateText)})`);
    const screenshotPath = await screenshot(cdp, "rux_ai_candidates_inserted_1920x1080.png");
    report = {
      appUrl,
      projectId,
      sectionId,
      baselineRevision: baseline.revision,
      savedRevision: saved.revision,
      candidateCount,
      candidateText,
      sourceTextStillPresent: afterInsertText.includes(sourceText),
      candidatePresentAfterInsert: afterInsertText.includes(candidateText),
      saveEnabled,
      errors,
      apiFailures,
      screenshotPath,
    };
  } finally {
    const restored = await restoreWorkingCopy(backupBlocks).catch((error) => ({ restore_error: String(error) }));
    report = { ...(report || {}), restoredRevision: restored.revision, restoreError: restored.restore_error || "" };
    await writeFile(path.join(outputDir, "report.json"), JSON.stringify(report, null, 2), "utf8");
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(500);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
  if (errors.length || apiFailures.length || report.restoreError) {
    throw new Error(JSON.stringify(report));
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
