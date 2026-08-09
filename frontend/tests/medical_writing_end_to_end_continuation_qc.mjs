import { spawn, spawnSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (process.env.QC_ISOLATED_RUNTIME !== "1") {
  throw new Error("medical_writing_end_to_end_continuation_qc.mjs mutates runtime state and requires QC_ISOLATED_RUNTIME=1");
}

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const appUrl = process.env.APP_URL || "http://127.0.0.1:5193/";
const projectId = process.env.PROJECT_ID || "proj_ra_greenfield_sandbox";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9569);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(
  scriptDir,
  "../../records/active_slices/medical_writing_end_to_end_authoring_20260716/browser_qc/continuation",
);
const projectSlug = process.env.PROJECT_SLUG || "ra";
const literatureDoi = process.env.LITERATURE_DOI || "10.1093/rheumatology/keab699";
const literatureTitleTerm = process.env.LITERATURE_TITLE_TERM || "SM03";
const manualMarker = process.env.MANUAL_MARKER || "本段已由医学经理结合项目决策完成补充确认。";
const editorAnchorTerm = process.env.EDITOR_ANCHOR_TERM || "ACR20";
const expectedVisualText = process.env.EXPECTED_VISUAL_TEXT || "类风湿关节炎";
const expectedAiTerms = (process.env.EXPECTED_AI_TERMS || "")
  .split(",")
  .map((item) => item.trim())
  .filter(Boolean);
const aiInstruction = process.env.AI_INSTRUCTION
  || "保留全部研究设计事实、研究人群、给药信息、时间点和终点层级，将当前段落整理为中国临床试验方案中可直接采用的规范性设计描述；不得补入未提供的随机、盲法、样本量或统计结论。";
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const workspaceRoot = path.resolve(scriptDir, "../..");
const pythonPath = process.env.WORKSPACE_PYTHON || "/usr/bin/python3";
const visualQcRenderer = path.join(workspaceRoot, "scripts/render_docx_visual_qc.py");
const analysisSetTemplateId = "analysis_sets";

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("json") ? await response.json().catch(() => ({})) : await response.arrayBuffer();
  if (!response.ok) throw new Error(`${response.status} ${url}: ${JSON.stringify(payload)}`);
  return payload;
}

function analysisSetTableBlocks(workingCopy) {
  return (workingCopy?.content_blocks || []).filter((block) => (
    (block?.template_id || block?.structured_table?.word_layout?.template_id) === analysisSetTemplateId
  ));
}

function tableIdentities(blocks) {
  return blocks.map((block) => ({
    block_id: block.block_id || null,
    table_id: block.table_id || block.structured_table?.table_id || null,
  }));
}

function countOccurrences(text, term) {
  if (!term) return 0;
  let count = 0;
  let offset = 0;
  while (true) {
    const next = text.indexOf(term, offset);
    if (next < 0) return count;
    count += 1;
    offset = next + term.length;
  }
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
    on(method, listener) {
      listeners.set(method, [...(listeners.get(method) || []), listener]);
    },
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
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(200);
  }
  throw new Error(`Timed out waiting for condition; last=${JSON.stringify(lastValue)}; expression=${expression}`);
}

async function clickExact(cdp, label, selector = "button") {
  const clicked = await evaluate(cdp, `(() => {
    const node = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
      .find((item) => (item.textContent || '').trim() === ${JSON.stringify(label)} && !item.disabled);
    if (!node) return false;
    node.scrollIntoView({ block: 'center', inline: 'nearest' });
    node.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Enabled control not found: ${selector}/${label}`);
}

async function clickContaining(cdp, label, selector = "button") {
  const clicked = await evaluate(cdp, `(() => {
    const node = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
      .find((item) => (item.textContent || '').includes(${JSON.stringify(label)}) && !item.disabled);
    if (!node) return false;
    node.scrollIntoView({ block: 'center', inline: 'nearest' });
    node.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Enabled control containing text not found: ${selector}/${label}`);
}

async function clickToolbarAction(cdp, label) {
  const clicked = await evaluate(cdp, `(() => {
    const node = Array.from(document.querySelectorAll('.rich-toolbar button'))
      .find((item) => item.getAttribute('aria-label') === ${JSON.stringify(label)} && !item.disabled);
    if (!node) return false;
    node.scrollIntoView({ block: 'center', inline: 'nearest' });
    node.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Enabled toolbar action not found: ${label}`);
}

async function setControlValue(cdp, selector, value) {
  const changed = await evaluate(cdp, `(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    if (!input) return false;
    const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : input instanceof HTMLSelectElement ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error(`Control not found: ${selector}`);
}

async function selectProject(cdp) {
  await waitForCondition(cdp, `(() => {
    const select = document.querySelector('select[aria-label="选择临床研究项目"]');
    return Boolean(select && !select.disabled && Array.from(select.options).some((option) => option.value === ${JSON.stringify(projectId)}));
  })()`);
  await evaluate(cdp, `(() => {
    const select = document.querySelector('select[aria-label="选择临床研究项目"]');
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(select, ${JSON.stringify(projectId)});
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function openSection(cdp, sectionIndex, heading) {
  await clickExact(cdp, "目录", ".writing-title-actions button");
  await waitForCondition(cdp, `Boolean(document.querySelector('.writing-document-map-drawer'))`);
  await waitForCondition(cdp, `document.querySelectorAll('.writing-section-buttons > button').length > ${sectionIndex}`);
  await evaluate(cdp, `document.querySelectorAll('.writing-section-buttons > button')[${sectionIndex}].click()`);
  await waitForCondition(cdp, `!document.querySelector('.writing-document-map-drawer')`);
  await waitForCondition(cdp, `document.querySelector('.rich-editor-meta')?.textContent.includes(${JSON.stringify(heading)})`);
  await waitForCondition(cdp, `Boolean(document.querySelector('.protocol-editor .ProseMirror')) && !document.querySelector('.working-copy-revision')?.textContent.includes('读取中')`);
}

async function ensureEditableCopy(cdp) {
  const revision = await evaluate(cdp, `document.querySelector('.working-copy-revision')?.textContent || ''`);
  if (revision.includes("尚未保存")) {
    await clickExact(cdp, "创建工作副本", ".working-copy-actions button");
    await waitForCondition(cdp, `document.querySelector('.protocol-editor .ProseMirror')?.getAttribute('contenteditable') === 'true'`);
    await waitForCondition(cdp, `document.querySelector('.working-copy-status-main')?.textContent.includes('有未保存修订')`);
    await clickContaining(cdp, "保存工作副本", ".working-copy-actions button");
    await waitForCondition(cdp, `document.querySelector('.working-copy-status-main')?.textContent.includes('已保存')`);
  } else {
    await waitForCondition(cdp, `document.querySelector('.protocol-editor .ProseMirror')?.getAttribute('contenteditable') === 'true'`);
  }
}

async function placeCaretAtEnd(cdp, textTerm = "") {
  const placed = await evaluate(cdp, `(() => {
    const editor = document.querySelector('.protocol-editor .ProseMirror');
    const paragraphs = Array.from(editor?.querySelectorAll('p') || []);
    const target = ${JSON.stringify(textTerm)}
      ? paragraphs.find((item) => (item.textContent || '').includes(${JSON.stringify(textTerm)}))
      : paragraphs.at(-1);
    if (!editor || !target || editor.getAttribute('contenteditable') !== 'true') return false;
    editor.focus();
    const range = document.createRange();
    range.selectNodeContents(target);
    range.collapse(false);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event('selectionchange', { bubbles: true }));
    return true;
  })()`);
  if (!placed) throw new Error("Could not place caret in editable protocol paragraph");
}

async function pressEnter(cdp) {
  const event = { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 };
  await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", ...event });
  await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", ...event });
}

async function screenshot(cdp, filename) {
  const capture = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const outputPath = path.join(outputDir, filename);
  await writeFile(outputPath, Buffer.from(capture.data, "base64"));
  return outputPath;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const initialDocumentResponse = await fetch(new URL(`/api/projects/${projectId}/medical-writing/document-session`, appUrl));
  if (!initialDocumentResponse.ok && initialDocumentResponse.status !== 404) {
    throw new Error(`Could not inspect initial document state: ${initialDocumentResponse.status}`);
  }
  const initialDocumentMissing = initialDocumentResponse.status === 404;
  const gateway = await request(new URL("/api/ai-gateway/status", appUrl));
  if (!gateway.configured || gateway.provider !== "deepseek" || gateway.model !== "deepseek-v4-pro" || gateway.hermes_provider) {
    throw new Error(`Independent AI route is not ready: ${JSON.stringify(gateway)}`);
  }

  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-e2e-continuation-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  const runtimeErrors = [];
  const apiFailures = [];
  let expectedPreDocumentSession404s = initialDocumentMissing ? 1 : 0;
  let cdp;
  const report = { projectId, appUrl, gateway, startedAt: new Date().toISOString() };
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    cdp = createCdp(targets.find((item) => item.type === "page").webSocketDebuggerUrl);
    await cdp.ready;
    cdp.on("Runtime.exceptionThrown", (event) => runtimeErrors.push(event.exceptionDetails?.exception?.description || event.exceptionDetails?.text));
    cdp.on("Network.responseReceived", (event) => {
      const url = event.response?.url || "";
      if (
        event.response.status === 404
        && url.includes(`/api/projects/${projectId}/medical-writing/document-session`)
        && expectedPreDocumentSession404s > 0
      ) {
        expectedPreDocumentSession404s -= 1;
        return;
      }
      if (url.includes("/api/") && event.response.status >= 400) apiFailures.push({ status: event.response.status, url });
    });
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes('项目总看板')`);
    await selectProject(cdp);
    await clickExact(cdp, "医学写作", ".nav-item");
    await waitForCondition(
      cdp,
      `document.body.textContent.includes('研究方案文档编辑与AI修订') || Boolean(document.querySelector('.authoring-journey-shell'))`,
    );
    if (await evaluate(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`)) {
      await waitForCondition(cdp, `(() => {
        const button = Array.from(document.querySelectorAll('.authoring-journey-shell button'))
          .find((item) => (item.textContent || '').trim() === '进入写作平台');
        return Boolean(button && !button.disabled);
      })()`);
      await clickExact(cdp, "进入写作平台", ".authoring-journey-shell button");
    }
    await waitForCondition(cdp, `document.body.textContent.includes('研究方案文档编辑与AI修订')`);
    const session = await request(new URL(`/api/projects/${projectId}/medical-writing/document-session`, appUrl));
    const designIndex = session.sections.findIndex((item) => item.template_node_id === "ich_m11_4_1");
    const analysisIndex = session.sections.findIndex((item) => item.template_node_id === "ich_m11_10_2");
    if (designIndex < 0 || analysisIndex < 0) throw new Error("Required M11 sections are missing from the created document");
    const designSection = session.sections[designIndex];
    const analysisSection = session.sections[analysisIndex];
    report.document = {
      documentId: session.document_id,
      sectionCount: session.sections.length,
      designSectionId: designSection.section_id,
      analysisSectionId: analysisSection.section_id,
    };

    await openSection(cdp, designIndex, designSection.heading);
    await ensureEditableCopy(cdp);

    await setControlValue(cdp, ".revision-form select", "regulatory_tone");
    await setControlValue(
      cdp,
      ".revision-form textarea",
      aiInstruction,
    );
    const threadIdsBefore = new Set(
      (await request(new URL(`/api/projects/${projectId}/revision-threads`, appUrl)))
        .map((thread) => thread.thread_id),
    );
    await clickExact(cdp, "提交AI修订", ".revision-form button");
    await waitForCondition(
      cdp,
      `!document.querySelector('.revision-form')?.innerText.includes('处理中')`,
      360000,
    );
    const revisionMessage = await evaluate(cdp, `Array.from(document.querySelectorAll('.revision-form .revision-message')).at(-1)?.textContent || ''`);
    if (!revisionMessage.includes("AI修订建议已生成")) {
      throw new Error(`AI revision did not complete successfully: ${revisionMessage}`);
    }
    const threads = await request(new URL(`/api/projects/${projectId}/revision-threads`, appUrl));
    const latestThread = [...threads].reverse().find((thread) => !threadIdsBefore.has(thread.thread_id));
    if (!latestThread) throw new Error("No new revision thread was created for the current submission");
    const candidateCount = latestThread.suggestions?.length || 0;
    if (candidateCount < 3 || candidateCount > 5) {
      throw new Error(`Current revision thread returned ${candidateCount} candidates`);
    }
    const candidateText = latestThread.suggestions?.at(-1)?.proposal_text
      || latestThread.suggestions?.[0]?.proposal_text
      || "";
    for (const term of expectedAiTerms) {
      if (!candidateText.includes(term)) {
        throw new Error(`AI candidate did not preserve required project fact: ${term}`);
      }
    }
    await waitForCondition(
      cdp,
      `Array.from(document.querySelectorAll('.writing-ai-candidates article')).some((item) => (item.textContent || '').includes(${JSON.stringify(candidateText.slice(0, 80))}))`,
    );
    const candidateApplied = await evaluate(cdp, `(() => {
      const articles = Array.from(document.querySelectorAll('.writing-ai-candidates article'));
      const article = articles.find((item) => (item.textContent || '').includes(${JSON.stringify(candidateText.slice(0, 80))}));
      const button = Array.from(article?.querySelectorAll('button') || []).find((item) => item.textContent.includes('选用并写入') && !item.disabled);
      button?.click();
      return Boolean(button);
    })()`);
    if (!candidateApplied) throw new Error("AI candidate audited application button was not available");
    await waitForCondition(cdp, `document.body.textContent.includes('已选用并写入工作副本版本')`);
    await waitForCondition(cdp, `document.querySelector('.working-copy-status-main')?.textContent.includes('已保存')`);
    const appliedThreads = await request(new URL(`/api/projects/${projectId}/revision-threads`, appUrl));
    const appliedThread = appliedThreads.find((thread) => thread.thread_id === latestThread.thread_id);
    const appliedWorkingCopy = await request(new URL(`/api/projects/${projectId}/medical-writing/working-copies/${designSection.section_id}`, appUrl));
    if (appliedThread?.status !== "medically_approved") {
      throw new Error(`Selected candidate decision was not persisted: ${appliedThread?.status || "missing"}`);
    }
    if (!appliedWorkingCopy.applied_revision_thread_ids?.includes(latestThread.thread_id)) {
      throw new Error("Selected candidate text was written without revision-thread lineage");
    }
    const aiRun = await request(new URL(`/api/projects/${projectId}/ai-runs/${latestThread.ai_run_id}`, appUrl));
    report.ai = {
      threadId: latestThread.thread_id,
      runId: latestThread.ai_run_id,
      candidateCount,
      candidateText,
      provider: aiRun.provider,
      model: aiRun.model_name || aiRun.model,
      status: aiRun.status,
      codexRuntimeDependency: aiRun.codex_runtime_dependency,
      authorSelectionPersisted: true,
      workingCopyRevision: appliedWorkingCopy.revision,
    };
    report.aiScreenshot = await screenshot(cdp, `01_${projectSlug}_ai_candidates_applied_1920x1080.png`);

    await placeCaretAtEnd(cdp, editorAnchorTerm);
    await pressEnter(cdp);
    await clickToolbarAction(cdp, "加粗");
    await cdp.send("Input.insertText", { text: manualMarker });
    await clickToolbarAction(cdp, "加粗");
    await waitForCondition(cdp, `document.querySelector('.protocol-editor .ProseMirror')?.innerText.includes(${JSON.stringify(manualMarker)})`);
    const paragraphCountAfterEnter = await evaluate(cdp, `document.querySelectorAll('.protocol-editor .ProseMirror p').length`);
    const boldMarkerPresent = await evaluate(cdp, `Array.from(document.querySelectorAll('.protocol-editor .ProseMirror strong')).some((item) => item.textContent.includes(${JSON.stringify(manualMarker)}))`);
    if (paragraphCountAfterEnter < 2 || !boldMarkerPresent) throw new Error("Enter or bold formatting did not change the editor structure");
    await clickContaining(cdp, "保存工作副本", ".working-copy-actions button");
    await waitForCondition(cdp, `document.querySelector('.working-copy-status-main')?.textContent.includes('已保存')`);
    report.editor = { paragraphCountAfterEnter, boldMarkerPresent };

    await placeCaretAtEnd(cdp, editorAnchorTerm);
    await clickExact(cdp, "文献", ".rail-tabs button");
    await setControlValue(cdp, ".medical-literature-import input", literatureDoi);
    await waitForCondition(cdp, `(() => {
      const button = Array.from(document.querySelectorAll('.medical-literature-import button'))
        .find((item) => (item.textContent || '').trim() === '导入');
      return Boolean(button && !button.disabled);
    })()`);
    await clickExact(cdp, "导入", ".medical-literature-import button");
    await waitForCondition(cdp, `document.querySelector('.medical-literature-list')?.textContent.includes(${JSON.stringify(literatureTitleTerm)})`, 120000);
    const referenceInserted = await evaluate(cdp, `(() => {
      const card = Array.from(document.querySelectorAll('.medical-literature-list article')).find((item) => item.textContent.includes(${JSON.stringify(literatureTitleTerm)}));
      const button = Array.from(card?.querySelectorAll('button') || []).find((item) => item.textContent.includes('插入引文') && !item.disabled);
      button?.click();
      return Boolean(button);
    })()`);
    if (!referenceInserted) throw new Error("Imported project reference was not citable");
    await waitForCondition(cdp, `Boolean(document.querySelector('.protocol-citation[data-reference-ids]'))`);
    const citationPlacement = await evaluate(cdp, `(() => {
      const citation = document.querySelector('.protocol-citation[data-reference-ids]');
      return {
        inParagraph: Boolean(citation?.closest('p')),
        inHeading: Boolean(citation?.closest('h1, h2, h3, h4, h5, h6')),
      };
    })()`);
    if (!citationPlacement.inParagraph || citationPlacement.inHeading) {
      throw new Error(`Citation was not inserted into the intended body paragraph: ${JSON.stringify(citationPlacement)}`);
    }
    report.editor.citationPlacement = citationPlacement;
    await clickContaining(cdp, "保存工作副本", ".working-copy-actions button");
    await waitForCondition(cdp, `document.querySelector('.working-copy-status-main')?.textContent.includes('已保存')`);
    const literature = await request(new URL(`/api/projects/${projectId}/medical-writing/literature`, appUrl));
    report.literature = literature.references.find((item) => item.doi?.toLowerCase() === literatureDoi.toLowerCase());

    await openSection(cdp, analysisIndex, analysisSection.heading);
    await ensureEditableCopy(cdp);
    const analysisWorkingCopyUrl = new URL(
      `/api/projects/${projectId}/medical-writing/working-copies/${analysisSection.section_id}`,
      appUrl,
    );
    const analysisWorkingCopyBefore = await request(analysisWorkingCopyUrl);
    const analysisSetTablesBefore = analysisSetTableBlocks(analysisWorkingCopyBefore);
    if (analysisSetTablesBefore.length > 1) {
      throw new Error(
        `Multiple analysis-set tables already exist; refusing to continue: ${JSON.stringify(tableIdentities(analysisSetTablesBefore))}`,
      );
    }
    let analysisSetTableAction;
    if (analysisSetTablesBefore.length === 0) {
      analysisSetTableAction = "inserted";
      await evaluate(cdp, `document.querySelector('button[aria-label="插入结构化表格"]')?.click()`);
      await waitForCondition(cdp, `Boolean(document.querySelector('[role="menu"][aria-label="结构化表格模板"]'))`);
      await clickContaining(cdp, "分析集定义", '[role="menuitem"]');
    } else {
      analysisSetTableAction = "reused";
      const existingBlockId = analysisSetTablesBefore[0].block_id;
      const selected = await evaluate(cdp, `(() => {
        const picker = document.querySelector('select[aria-label="选择当前表格"]');
        if (!picker || !Array.from(picker.options).some((option) => option.value === ${JSON.stringify(existingBlockId)})) return false;
        Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(picker, ${JSON.stringify(existingBlockId)});
        picker.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      })()`);
      if (!selected) throw new Error(`Existing analysis-set table is not available in the editor: ${existingBlockId}`);
      await waitForCondition(
        cdp,
        `document.querySelector('select[aria-label="选择当前表格"]')?.value === ${JSON.stringify(existingBlockId)}`,
      );
      const opened = await evaluate(cdp, `(() => {
        const button = document.querySelector('button.rich-table-designer-button');
        if (!button || button.disabled) return false;
        button.click();
        return true;
      })()`);
      if (!opened) throw new Error(`Existing analysis-set table could not be opened: ${existingBlockId}`);
    }
    await waitForCondition(cdp, `Boolean(document.querySelector('button[aria-label="关闭表格设计器"]'))`, 45000);
    const analysisWorkingCopyAfter = await request(analysisWorkingCopyUrl);
    const analysisSetTablesAfter = analysisSetTableBlocks(analysisWorkingCopyAfter);
    if (analysisSetTablesAfter.length !== 1) {
      throw new Error(
        `Expected exactly one analysis-set table after ${analysisSetTableAction}, found ${analysisSetTablesAfter.length}: ${JSON.stringify(tableIdentities(analysisSetTablesAfter))}`,
      );
    }
    report.analysisSetTable = {
      action: analysisSetTableAction,
      ...tableIdentities(analysisSetTablesAfter)[0],
    };
    const tableText = await evaluate(cdp, `document.querySelector('.structured-table-designer')?.innerText || document.body.innerText`);
    for (const expected of ["全分析集（FAS）", "符合方案集（PPS）", "安全性集（SS）"]) {
      if (!tableText.includes(expected)) throw new Error(`Analysis-set table is missing prefilled row: ${expected}`);
    }
    report.tableScreenshot = await screenshot(cdp, "02_analysis_set_prefilled_table_1920x1080.png");
    await evaluate(cdp, `document.querySelector('button[aria-label="关闭表格设计器"]')?.click()`);
    await waitForCondition(cdp, `!document.querySelector('button[aria-label="关闭表格设计器"]')`);

    const exported = await request(new URL(`/api/projects/${projectId}/medical-writing/document.docx?mode=draft_preview`, appUrl));
    const docxPath = path.join(outputDir, `${projectSlug}_end_to_end_draft_preview.docx`);
    await writeFile(docxPath, Buffer.from(exported));
    const xmlResult = spawnSync("unzip", ["-p", docxPath, "word/document.xml"], { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 });
    if (xmlResult.status !== 0) throw new Error(`DOCX XML inspection failed: ${xmlResult.stderr}`);
    const xml = xmlResult.stdout;
    const docxCounts = {
      tables: (xml.match(/<w:tbl(?:\s|>)/g) || []).length,
      analysisSetTitle: countOccurrences(xml, "分析集定义"),
      fas: countOccurrences(xml, "全分析集（FAS）"),
      pps: countOccurrences(xml, "符合方案集（PPS）"),
      ss: countOccurrences(xml, "安全性集（SS）"),
    };
    const docxChecks = {
      generated: exported.byteLength > 10000,
      manualMarker: xml.includes(manualMarker),
      literatureTitle: xml.includes(literatureTitleTerm),
      numberedCitation: /\[\d+\]/.test(xml),
      hyperlink: xml.includes("w:hyperlink"),
      tableCount: docxCounts.tables === 1,
      analysisSetTitleCount: docxCounts.analysisSetTitle === 1,
      fasCount: docxCounts.fas === 1,
      ppsCount: docxCounts.pps === 1,
      ssCount: docxCounts.ss === 1,
      noRepeatableTemplateMarker: !xml.includes("&lt;#&gt;") && !xml.includes("<#>"),
    };
    if (Object.values(docxChecks).some((value) => !value)) {
      throw new Error(`DOCX verification failed: ${JSON.stringify({ checks: docxChecks, counts: docxCounts })}`);
    }
    const visualQcDir = path.join(outputDir, "docx_visual_qc");
    const visualQcResult = spawnSync(
      pythonPath,
      [
        visualQcRenderer,
        docxPath,
        "--output-dir",
        visualQcDir,
        "--expected-text",
        expectedVisualText,
        "--max-preview-pages",
        "6",
      ],
      {
        encoding: "utf8",
        maxBuffer: 32 * 1024 * 1024,
        env: { ...process.env, PYTHONPATH: workspaceRoot },
      },
    );
    if (visualQcResult.status !== 0) {
      throw new Error(`DOCX visual QC failed: ${visualQcResult.stderr || visualQcResult.stdout}`);
    }
    const visualQc = JSON.parse(
      await readFile(path.join(visualQcDir, "visual_qc_report.json"), "utf8"),
    );
    if (!visualQc.passed) throw new Error(`DOCX visual QC report failed: ${JSON.stringify(visualQc.checks)}`);
    report.docx = {
      path: docxPath,
      bytes: exported.byteLength,
      checks: docxChecks,
      counts: docxCounts,
      visualQc: {
        passed: visualQc.passed,
        pageCount: visualQc.page_count,
        embeddedFonts: visualQc.embedded_fonts,
        chineseSpanCount: visualQc.chinese_span_count,
        visibleChineseSpanCount: visualQc.visible_chinese_span_count,
        reportPath: visualQc.report_path || path.join(visualQcDir, "visual_qc_report.json"),
      },
    };

    await cdp.send("Page.reload", { ignoreCache: true });
    await waitForCondition(cdp, `document.body.textContent.includes('项目总看板')`);
    await selectProject(cdp);
    await clickExact(cdp, "医学写作", ".nav-item");
    await waitForCondition(cdp, `document.body.textContent.includes('研究方案文档编辑与AI修订')`);
    await openSection(cdp, designIndex, designSection.heading);
    await waitForCondition(cdp, `document.querySelector('.protocol-editor .ProseMirror')?.innerText.includes(${JSON.stringify(manualMarker)})`);
    report.reload = {
      manualMarkerRestored: true,
      citationRestored: await evaluate(cdp, `Boolean(document.querySelector('.protocol-citation[data-reference-ids]'))`),
    };
    report.finalScreenshot = await screenshot(cdp, `03_${projectSlug}_saved_reloaded_1920x1080.png`);
    report.runtimeErrors = runtimeErrors;
    report.apiFailures = apiFailures.filter((item) => !item.url.includes("/medical-writing/manifest"));
    report.passed = report.ai.candidateCount >= 3
      && report.ai.candidateCount <= 5
      && report.ai.provider === "deepseek"
      && report.ai.model === "deepseek-v4-pro"
      && report.ai.status === "completed"
      && report.ai.codexRuntimeDependency === false
      && report.editor.citationPlacement?.inParagraph === true
      && report.editor.citationPlacement?.inHeading === false
      && report.reload.citationRestored
      && runtimeErrors.length === 0
      && report.apiFailures.length === 0;
    if (!report.passed) throw new Error(`Continuation QC failed: ${JSON.stringify(report)}`);
    report.completedAt = new Date().toISOString();
  } catch (error) {
    report.error = error.stack || error.message;
    if (cdp) report.failureScreenshot = await screenshot(cdp, "99_failure.png").catch(() => "");
    throw error;
  } finally {
    await writeFile(path.join(outputDir, "report.json"), JSON.stringify(report, null, 2));
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(300);
    await rm(userDataDir, { recursive: true, force: true });
  }
}

await main();
