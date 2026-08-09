import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(
  __dirname,
  "..",
  "..",
  "records",
  "visual_qc_20260715",
  "medical_writing_m11_registry_runtime",
);
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9388);
const greenfieldProjectId = process.env.GREENFIELD_PROJECT_ID || "proj_mgk10_crswnp";
const referenceProjectId = process.env.REFERENCE_PROJECT_ID || "proj_rux_03_002";
const expectedTemplateId = "ich_m11_zh_cn";
const expectedTemplateVersion = "ich_m11_zh_cn_step4_cde_consultation_2026_06_12_v1";
const expectedTemplateNodeCount = 159;
const desktopViewports = [
  { width: 1600, height: 1000 },
  { width: 1920, height: 1080 },
  { width: 2048, height: 1024 },
];

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function json(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}: ${JSON.stringify(payload)}`);
  return payload;
}

async function waitForJson(url, timeoutMs = 10000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await json(url);
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
    close() {
      ws.close();
    },
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

async function waitForCondition(cdp, expression, timeoutMs = 30000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(250);
  }
  throw new Error(`Timed out waiting for condition: ${JSON.stringify(lastValue)}`);
}

async function selectProject(cdp, projectId) {
  const changed = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
      setter.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Project switcher not found: ${projectId}`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function clickButton(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button"))
        .find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)});
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button not found: ${label}`);
}

async function clickButtonContaining(cdp, label, selector = "button") {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
        .find((item) => (item.textContent || "").includes(${JSON.stringify(label)}));
      if (!button || button.disabled) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Enabled button not found: ${label}`);
}

async function setTextArea(cdp, selector, value) {
  const changed = await evaluate(cdp, `
    (() => {
      const input = document.querySelector(${JSON.stringify(selector)});
      if (!input) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      setter.call(input, ${JSON.stringify(value)});
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Textarea not found: ${selector}`);
}

async function setDecisionField(cdp, fieldIndex, value) {
  const selector = `.greenfield-decision-review-list > section:first-child textarea:nth-of-type(${fieldIndex + 1})`;
  const changed = await evaluate(cdp, `
    (() => {
      const fields = document.querySelectorAll(".greenfield-decision-review-list > section:first-child textarea");
      const input = fields[${fieldIndex}];
      if (!input) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      setter.call(input, ${JSON.stringify(value)});
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Decision field not found: ${selector}`);
}

async function setViewport(cdp, viewport) {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    ...viewport,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await evaluate(cdp, `window.scrollTo({ top: 0, left: 0, behavior: "instant" })`);
  await wait(150);
}

async function capture(cdp, filename) {
  const screenshot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const outputPath = path.join(outputDir, filename);
  await writeFile(outputPath, Buffer.from(screenshot.data, "base64"));
  return outputPath;
}

async function captureDesktopViewports(cdp, prefix) {
  const screenshots = {};
  for (const viewport of desktopViewports) {
    await setViewport(cdp, viewport);
    const key = `${viewport.width}x${viewport.height}`;
    screenshots[key] = await capture(cdp, `${prefix}_${key}.png`);
  }
  await setViewport(cdp, desktopViewports[0]);
  return screenshots;
}

async function openWriting(cdp, projectId) {
  await selectProject(cdp, projectId);
  await clickButton(cdp, "医学写作");
  await waitForCondition(cdp, `
    document.body.textContent.includes("研究方案文档编辑与AI修订")
      || document.body.textContent.includes("研究方案智能设计与写作")
  `);
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "medical-writing-greenfield-qc-"));
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
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Chrome page target found.");
    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await setViewport(cdp, desktopViewports[0]);
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);

    await openWriting(cdp, referenceProjectId);
    await waitForCondition(cdp, `Boolean(document.querySelector(".protocol-editor .ProseMirror"))`, 45000);
    const referenceScreenshots = await captureDesktopViewports(cdp, "reference_existing_docx_editor");

    await openWriting(cdp, greenfieldProjectId);
    await waitForCondition(cdp, `
      Boolean(document.querySelector(".greenfield-setup-shell"))
        && !document.body.textContent.includes("正在加载研究方案文档会话")
    `, 45000);
    await wait(500);
    const beforeMetrics = await evaluate(cdp, `
      (() => {
        const bodyText = document.body.textContent || "";
        const setup = document.querySelector(".greenfield-setup-shell")?.getBoundingClientRect();
        const editorPanel = document.querySelector(".writing-editor-core")?.getBoundingClientRect();
        const ai = document.querySelector(".writing-ai-core")?.getBoundingClientRect();
        const map = document.querySelector(".writing-document-map")?.getBoundingClientRect();
        const doc = document.documentElement;
        const body = document.body;
        return {
          hasSetup: Boolean(setup),
          hasCandidateBoundary: bodyText.includes("待医学批准候选"),
          hasProjectFields: document.querySelectorAll(".greenfield-project-fields input").length === 5,
          hasNoClientSectionScaffold: document.querySelectorAll(".greenfield-section-options input[type=checkbox]").length === 0,
          hasApprovalBlockingDecisions: document.querySelectorAll(".greenfield-decision-list input").length === 3,
          hasDesignSummary: Boolean(document.querySelector(".greenfield-design-summary textarea")),
          hasAiRail: Boolean(ai),
          editorAiMapOrder: Boolean(setup && ai && map && setup.left < ai.left && ai.left < map.left),
          editorAndAiAligned: Boolean(editorPanel && ai && Math.abs(editorPanel.top - ai.top) <= 24),
          noManifestFailureNoise: !bodyText.includes("研究方案写作资料包生成失败"),
          noLifecycleNumbering: !/第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]/.test(bodyText),
          noPageOverflowX: Math.max(doc.scrollWidth, body.scrollWidth) <= window.innerWidth + 1,
        };
      })()
    `);
    const setupScreenshots = await captureDesktopViewports(cdp, "greenfield_setup");

    await setTextArea(
      cdp,
      ".greenfield-design-summary textarea",
      "随机、双盲、安慰剂对照、多中心III期研究；具体剂量、主要终点和样本量仍待医学及统计确认。",
    );
    await clickButton(cdp, "建立工作稿");
    await waitForCondition(cdp, `Boolean(document.querySelector(".protocol-editor .ProseMirror"))`, 45000);
    await waitForCondition(cdp, `document.body.textContent.includes("绿地候选基线")`, 45000);
    await evaluate(cdp, `window.scrollTo({ top: 0, left: 0, behavior: "instant" })`);
    await wait(300);

    await clickButton(cdp, "创建工作副本");
    await waitForCondition(cdp, `
      document.querySelector(".protocol-editor .ProseMirror")?.getAttribute("contenteditable") === "true"
        && document.body.textContent.includes("有未保存修订")
    `, 30000);
    await clickButton(cdp, "保存工作副本");
    await waitForCondition(cdp, `document.querySelector(".working-copy-revision")?.textContent?.includes("版本 1")`, 30000);

    await evaluate(cdp, `document.querySelector('button[aria-label="插入结构化表格"]')?.click()`);
    await waitForCondition(cdp, `Boolean(document.querySelector('[role="menu"][aria-label="结构化表格模板"]'))`);
    await clickButtonContaining(cdp, "研究目的与终点", '[role="menuitem"]');
    await waitForCondition(cdp, `document.querySelector(".working-copy-revision")?.textContent?.includes("版本 2")`, 30000);
    await waitForCondition(cdp, `Boolean(document.querySelector('.protocol-editor table[data-source-block-id]'))`, 30000);
    await waitForCondition(cdp, `Boolean(document.querySelector('button[aria-label="关闭表格设计器"]'))`, 30000);
    const tableDesignerScreenshots = await captureDesktopViewports(cdp, "greenfield_table_designer");
    await evaluate(cdp, `document.querySelector('button[aria-label="关闭表格设计器"]')?.click()`);
    await waitForCondition(cdp, `!document.querySelector('button[aria-label="关闭表格设计器"]')`, 30000);

    await clickButtonContaining(cdp, "项目决策", ".working-copy-actions button");
    await waitForCondition(cdp, `Boolean(document.querySelector(".greenfield-decision-review"))`);
    await setDecisionField(cdp, 0, "试验药物A，100 mg，每日一次");
    await setDecisionField(cdp, 1, "依据已完成的项目剂量决策会，当前剂量用于方案工作稿并仍需逐节医学批准。");
    await setDecisionField(cdp, 2, "项目剂量决策会纪要 2026-07-14");
    await clickButton(cdp, "确认并解除阻断");
    await waitForCondition(cdp, `
      document.querySelector(".greenfield-decision-review")?.textContent?.includes("版本 2")
        && document.body.textContent.includes("项目决策 2 项未决")
    `, 30000);
    const decisionReviewScreenshots = await captureDesktopViewports(cdp, "greenfield_decision_review");

    await clickButton(cdp, "AI");
    await clickButton(cdp, "预览 Word");
    await waitForCondition(cdp, `document.body.textContent.includes("草稿预览 Word 已按当前已保存工作副本")`, 30000);

    const session = await json(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/document-session`, appUrl));
    const state = await json(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/greenfield-document`, appUrl));
    const selectedSectionId = session.sections[0].section_id;
    const workingCopy = await json(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/working-copies/${selectedSectionId}`, appUrl));
    const draftResponse = await fetch(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/document.docx?mode=draft_preview`, appUrl));
    const draftBytes = new Uint8Array(await draftResponse.arrayBuffer());
    const afterMetrics = await evaluate(cdp, `
      (() => {
        const bodyText = document.body.textContent || "";
        const editor = document.querySelector(".protocol-editor .ProseMirror");
        const editorRect = document.querySelector(".writing-editor-core")?.getBoundingClientRect();
        const aiRect = document.querySelector(".writing-ai-core")?.getBoundingClientRect();
        const mapRect = document.querySelector(".writing-document-map")?.getBoundingClientRect();
        const doc = document.documentElement;
        const body = document.body;
        return {
          hasEditor: Boolean(editor),
          workingCopyIsEditable: editor?.getAttribute("contenteditable") === "true",
          hasGreenfieldDecisionControl: bodyText.includes("项目决策 2 项未决"),
          hasCandidateBoundary: bodyText.includes("待医学批准候选"),
          hasSavedWorkingCopy: document.querySelector(".working-copy-revision")?.textContent?.includes("版本 2"),
          hasInsertedTable: Boolean(document.querySelector('.protocol-editor table[data-source-block-id]')),
          hasTableInsertControl: Boolean(document.querySelector('button[aria-label="插入结构化表格"]')),
          formalWordBlocked: Boolean(Array.from(document.querySelectorAll("button")).find((button) => (button.textContent || "").includes("正式 Word"))?.disabled),
          decisionReviewAvailable: Array.from(document.querySelectorAll("button")).some((button) => (button.textContent || "").includes("项目决策 2 项未决")),
          hasAiRevisionForm: Boolean(document.querySelector(".revision-form textarea")),
          hasDocumentMap: document.querySelectorAll(".writing-section-buttons > button").length === ${expectedTemplateNodeCount},
          hasManifest: bodyText.includes("研究方案写作资料包"),
          editorAiMapOrder: Boolean(editorRect && aiRect && mapRect && editorRect.left < aiRect.left && aiRect.left < mapRect.left),
          noPageOverflowX: Math.max(doc.scrollWidth, body.scrollWidth) <= window.innerWidth + 1,
          noManifestFailureNoise: !bodyText.includes("研究方案写作资料包生成失败"),
        };
      })()
    `);
    const editorScreenshots = await captureDesktopViewports(cdp, "greenfield_editor_with_table");
    const viewportMetrics = {};
    for (const viewport of desktopViewports) {
      await setViewport(cdp, viewport);
      viewportMetrics[`${viewport.width}x${viewport.height}`] = await evaluate(cdp, `
        (() => {
          const editor = document.querySelector(".writing-editor-core")?.getBoundingClientRect();
          const ai = document.querySelector(".writing-ai-core")?.getBoundingClientRect();
          const map = document.querySelector(".writing-document-map")?.getBoundingClientRect();
          return {
            noPageOverflowX: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) <= window.innerWidth + 1,
            editorAiMapOrder: Boolean(editor && ai && map && editor.left < ai.left && ai.left < map.left),
            editorAndAiAligned: Boolean(editor && ai && Math.abs(editor.top - ai.top) <= 24),
          };
        })()
      `);
    }
    await setViewport(cdp, desktopViewports[0]);

    const failures = [];
    for (const [key, value] of Object.entries(beforeMetrics)) if (!value) failures.push(`before:${key}`);
    for (const [key, value] of Object.entries(afterMetrics)) if (!value) failures.push(`after:${key}`);
    if (session.status !== "greenfield_candidate") failures.push("api:sessionStatus");
    if (session.sections.length !== expectedTemplateNodeCount) failures.push("api:sectionCount");
    if (session.template_id !== expectedTemplateId) failures.push("api:templateId");
    if (session.template_version !== expectedTemplateVersion) failures.push("api:templateVersion");
    if (!/^[a-f0-9]{64}$/.test(session.template_definition_sha256 || "")) failures.push("api:templateDigest");
    const synopsisSection = session.sections.find((item) => item.template_node_id === "ich_m11_1_1");
    const designSection = session.sections.find((item) => item.template_node_id === "ich_m11_4_1");
    const doseModificationSection = session.sections.find((item) => item.template_node_id === "ich_m11_6_4");
    const concomitantMedicationSection = session.sections.find((item) => item.template_node_id === "ich_m11_6_10");
    if (!synopsisSection?.content_blocks?.some((block) => (block.source_fact_ids || []).length)) failures.push("api:synopsisProjection");
    if (!designSection?.content_blocks?.some((block) => (block.source_fact_ids || []).length)) failures.push("api:designProjection");
    if (!doseModificationSection?.interaction_types?.includes("dose_modification_builder")) failures.push("api:doseModificationBoundary");
    if (!concomitantMedicationSection?.interaction_types?.includes("concomitant_medication_builder")) failures.push("api:concomitantMedicationBoundary");
    if (doseModificationSection?.interaction_types?.join("|") === concomitantMedicationSection?.interaction_types?.join("|")) failures.push("api:interventionBoundaryCollision");
    if (state.document_id !== session.document_id) failures.push("api:documentIdentity");
    if (state.decisions.filter((item) => item.status === "unresolved").length !== 2) failures.push("api:decisionCount");
    if (state.baseline_revision !== 2) failures.push("api:decisionBaselineRevision");
    if (workingCopy.revision !== 2) failures.push("api:workingCopyRevision");
    if (!workingCopy.content_blocks.some((block) => block.block_type === "table" && block.template_id === "objectives_endpoints")) failures.push("api:insertedTable");
    if (!draftResponse.ok || draftBytes.length < 1000) failures.push("api:draftWordExport");
    for (const [key, metrics] of Object.entries(viewportMetrics)) {
      for (const [metric, value] of Object.entries(metrics)) if (!value) failures.push(`viewport:${key}:${metric}`);
    }

    const report = {
      viewports: desktopViewports,
      referenceProjectId,
      greenfieldProjectId,
      beforeMetrics,
      afterMetrics,
      api: {
        documentId: session.document_id,
        status: session.status,
        sectionCount: session.sections.length,
        templateId: session.template_id,
        templateVersion: session.template_version,
        templateDefinitionSha256: session.template_definition_sha256,
        baselineRevision: state.baseline_revision,
        unresolvedDecisionCount: state.decisions.filter((item) => item.status === "unresolved").length,
        workingCopyRevision: workingCopy.revision,
        structuredTableCount: workingCopy.content_blocks.filter((block) => block.block_type === "table").length,
        draftWordBytes: draftBytes.length,
      },
      viewportMetrics,
      screenshots: {
        referenceScreenshots,
        setupScreenshots,
        tableDesignerScreenshots,
        decisionReviewScreenshots,
        editorScreenshots,
      },
      failures,
    };
    await writeFile(path.join(outputDir, "medical_writing_greenfield_qc.json"), JSON.stringify(report, null, 2), "utf8");
    if (failures.length) throw new Error(`Greenfield medical writing QC failed: ${failures.join(", ")}`);
    cdp.close();
  } finally {
    chrome.kill("SIGTERM");
    await wait(500);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
