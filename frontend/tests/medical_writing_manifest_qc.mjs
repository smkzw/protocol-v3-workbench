import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/visual_qc_20260708");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9371);
const scriptDir = path.dirname(new URL(import.meta.url).pathname);
const workspaceRoot = path.resolve(scriptDir, "../..");
const reviewStorePath = path.join(workspaceRoot, "runtime", "tfl_review_actions.jsonl");
let reviewStoreBackup = null;
let reviewStoreExisted = false;

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

async function requestJsonWithBody(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}: ${JSON.stringify(payload)}`);
  return payload;
}

async function waitForJson(url, timeoutMs = 8000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await requestJson(url);
    } catch (error) {
      lastError = error;
      await wait(150);
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
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result || {});
  });

  return {
    ready: new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", reject, { once: true });
    }),
    send(method, params = {}) {
      const id = nextId;
      nextId += 1;
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
    const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.exception?.value || result.exceptionDetails.text;
    throw new Error(detail || "Runtime evaluation failed");
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
  throw new Error(`Timed out waiting for condition. Last value: ${JSON.stringify(lastValue)}`);
}

async function clickButtonByText(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)});
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button not found: ${label}`);
}

async function clickButtonContainingText(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").includes(${JSON.stringify(label)}));
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button containing text not found: ${label}`);
}

async function setValue(cdp, selector, value) {
  const changed = await evaluate(cdp, `
    (() => {
      const input = document.querySelector(${JSON.stringify(selector)});
      if (!input) return false;
      input.scrollIntoView({ block: "center", inline: "nearest" });
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value")?.set;
      if (setter) setter.call(input, ${JSON.stringify(value)});
      else input.value = ${JSON.stringify(value)};
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Input not found: ${selector}`);
}

function apiUrl(pathname) {
  return new URL(pathname, appUrl).toString();
}

async function backupAndClearReviewStore() {
  try {
    reviewStoreBackup = await readFile(reviewStorePath, "utf8");
    reviewStoreExisted = true;
  } catch {
    reviewStoreBackup = null;
    reviewStoreExisted = false;
  }
  await rm(reviewStorePath, { force: true });
}

async function restoreReviewStore() {
  if (reviewStoreExisted) {
    await writeFile(reviewStorePath, reviewStoreBackup || "", "utf8");
  } else {
    await rm(reviewStorePath, { force: true });
  }
}

async function seedTflWritingCandidate() {
  const workbench = await requestJson(apiUrl("/api/projects/proj_mgk10_sar_demo/tfl/review-workbench?package_id=my008_pnh_3_01"));
  const output = (workbench.candidate_outputs || []).find((item) => item.paired_file_id) || workbench.selected_output;
  if (!output?.output_id) throw new Error("No paired MY008 TFL output available for writing QC.");
  const encodedOutput = encodeURIComponent(output.output_id);
  const endpoint = apiUrl(`/api/projects/proj_mgk10_sar_demo/tfl/review-workbench/my008_pnh_3_01/outputs/${encodedOutput}/actions`);
  await requestJsonWithBody(endpoint, {
    action: "mark_reviewed",
    actor: "medical_manager",
    comment: "医学写作QC：已核对TFL对象和配对数据集。",
  });
  await requestJsonWithBody(endpoint, {
    action: "create_writing_candidate",
    actor: "medical_manager",
    comment: "医学写作QC：允许进入医学写作引用候选，正式写入前仍需统计复核。",
  });
}

async function captureWritingMetrics(cdp) {
  return evaluate(cdp, `
    (() => {
      const text = document.body.textContent || "";
      const doc = document.documentElement;
      const body = document.body;
      const editorRect = document.querySelector(".editor-panel")?.getBoundingClientRect();
      const aiRailRect = document.querySelector(".ai-rail")?.getBoundingClientRect();
      const manifestRect = document.querySelector(".writing-manifest-panel")?.getBoundingClientRect();
      const sectionStripRect = document.querySelector(".writing-section-strip")?.getBoundingClientRect();
      const submitAiButtonRect = Array.from(document.querySelectorAll("button"))
        .find((button) => (button.textContent || "").includes("提交AI修订"))
        ?.getBoundingClientRect();
      const writingOuterHtml = document.querySelector(".writing-page")?.outerHTML || "";
      const sourceLeakPattern = /\\/Users\\/|file:\\/\\/|root_path|file_path|absolute_path|allowed_roots|content_hash|preview_hash|storage_key|server_path|source_record_id/i;
      return {
        hasTitle: text.includes("医学写作") && text.includes("研究方案文档编辑与AI修订"),
        hasManifest: text.includes("研究方案写作资料包"),
        hasRuxPackage: text.includes("RUX-03-002研究方案写作资料包"),
        hasD001Package: text.includes("CMS-D001研究方案写作资料包"),
        hasDocxBoundary: text.includes("真实DOCX来源") && text.includes("待医学批准的正式内容候选"),
        hasReviewDocx: text.includes("审阅版 DOCX"),
        hasFormalExportBlock: text.includes("不可生成正式导出包"),
        hasIndependentAiBoundary: text.includes("独立AI provider未配置") && text.includes("独立AI服务未配置"),
        hasTflCitationPanel: text.includes("TFL写作引用候选") && text.includes("来自数据分析与TFL"),
        hasTflCitationCandidate: text.includes("医学写作QC：允许进入医学写作引用候选") && text.includes("正式写入前仍需统计复核"),
        hasTflCitationBoundary: text.includes("不自动生成或改写正式医学写作正文"),
        hasEditor: document.querySelectorAll(".protocol-editor .ProseMirror[contenteditable]").length > 0,
        hasRevisionForm: text.includes("AI修订指令") && Boolean(document.querySelector(".revision-form textarea")) && Boolean(document.querySelector(".revision-form select")),
        editorInFirstViewport: Boolean(editorRect && editorRect.top < window.innerHeight * 0.55),
        aiRailInFirstViewport: Boolean(aiRailRect && aiRailRect.top < window.innerHeight * 0.55),
        submitAiButtonInFirstViewport: Boolean(submitAiButtonRect && submitAiButtonRect.top < window.innerHeight && submitAiButtonRect.bottom <= window.innerHeight),
        editorBeforeSourceManifest: Boolean(editorRect && manifestRect && editorRect.top < manifestRect.top),
        aiRailBeforeSourceManifest: Boolean(aiRailRect && manifestRect && aiRailRect.top < manifestRect.top),
        sourceManifestBelowCore: Boolean(manifestRect && editorRect && aiRailRect && manifestRect.top >= Math.max(editorRect.bottom, aiRailRect.bottom) - 1),
        editorAndAiSameWorkRow: Boolean(editorRect && aiRailRect && Math.abs(editorRect.top - aiRailRect.top) <= 24 && editorRect.left < aiRailRect.left),
        editorWiderThanAi: Boolean(editorRect && aiRailRect && editorRect.width > aiRailRect.width * 1.25),
        documentMapSecondaryRail: Boolean(
          sectionStripRect &&
          editorRect &&
          aiRailRect &&
          Math.abs(sectionStripRect.top - editorRect.top) <= 24 &&
          editorRect.left < aiRailRect.left &&
          aiRailRect.left < sectionStripRect.left
        ),
        documentMapSupportsEditor: Boolean(sectionStripRect && editorRect && sectionStripRect.width < editorRect.width * 0.55),
        hasRevisionThreadList: text.includes("修订线程"),
        hasRevisionBoundary: text.includes("AI修订建议仅为待医学批准内容候选") && text.includes("不自动写入正式正文"),
        hasBlockedRevisionMessage: text.includes("AI修订提交失败：独立AI未配置"),
        hasRevisionSuggestion: text.includes("AI修订建议"),
        hasAcceptedCandidate: text.includes("已接受，仍待医学批准"),
        hasRevisionStubBoundary: text.includes("未接入真实LLM") || text.includes("独立AI provider未配置"),
        editorTextContainsAiSuggestion: (document.querySelector(".protocol-editor .ProseMirror")?.textContent || "").includes("AI修订建议"),
        revisionThreadRows: document.querySelectorAll(".revision-thread-list > button").length,
        citationRows: document.querySelectorAll(".writing-citation-list article").length,
        citationGateRows: document.querySelectorAll(".writing-citation-gates > div").length,
        documentRows: document.querySelectorAll(".writing-doc-table tbody tr").length,
        sectionRows: document.querySelectorAll(".writing-section-table tbody tr").length,
        tableRows: document.querySelectorAll(".writing-table-inventory tbody tr").length,
        gateRows: document.querySelectorAll(".writing-gate-table tbody tr").length,
        approvalButtonDisabled: Array.from(document.querySelectorAll("button")).some((button) => button.textContent.includes("质量门阻断") && button.disabled),
        hasForbiddenLifecycleText: /第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]|Stage\\s+[0-9]/.test(text),
        hasForbiddenOverclaim: /AI 已完成正式方案|自动定稿|可直接提交监管|正式方案已生成|最终医学结论|监管认可|疗效最优|首选方案|竞品证明|无需人工复核/.test(text),
        leaksLocalPath: sourceLeakPattern.test(text),
        leaksSourceConfigInOuterHtml: sourceLeakPattern.test(writingOuterHtml),
        overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
        internalTableScrollCount: Array.from(document.querySelectorAll(".tfl-table-scroll")).filter((item) => item.scrollWidth > item.clientWidth).length,
      };
    })()
  `);
}

async function openWritingPage(cdp) {
  await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);
  await clickButtonByText(cdp, "医学写作");
  await waitForCondition(cdp, `
    document.body.textContent.includes("研究方案写作资料包") &&
    document.body.textContent.includes("TFL写作引用候选") &&
    document.body.textContent.includes("写作质量门") &&
    document.body.textContent.includes("方案章节候选")
  `, 45000);
  await wait(700);
}

async function exerciseRevisionWorkflow(cdp, suffix, aiConfigured) {
  const instruction = `医学写作QC-${suffix}：请将当前终点表述改写为保守的方案正文，并提示证据缺口。`;
  await setValue(cdp, ".revision-form textarea", instruction);
  await clickButtonByText(cdp, "提交AI修订");
  if (!aiConfigured) {
    await waitForCondition(cdp, `
      document.body.textContent.includes(${JSON.stringify(instruction)}) &&
      document.body.textContent.includes("AI修订提交失败：独立AI未配置") &&
      (document.body.textContent.includes("系统未调用独立AI服务") || document.body.textContent.includes("WORKBENCH_AI_BASE_URL"))
    `, 15000);
    return { instruction, mode: "blocked_ai_not_configured" };
  }
  await waitForCondition(cdp, `
    document.body.textContent.includes(${JSON.stringify(instruction)}) &&
    document.body.textContent.includes("AI修订建议") &&
    document.body.textContent.includes("待医学批准")
  `, 15000);
  await waitForCondition(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").trim() === "接受为候选");
      return Boolean(button && !button.disabled);
    })()
  `, 15000);
  await setValue(cdp, ".revision-thread textarea", `QC-${suffix}：接受为候选，正式写入前仍需医学批准。`);
  await clickButtonByText(cdp, "接受为候选");
  await waitForCondition(cdp, `
    document.body.textContent.includes("已接受，仍待医学批准") &&
    document.body.textContent.includes("不自动写入正式正文")
  `, 15000);
  return { instruction, mode: "configured_ai_revision_candidate" };
}

async function exerciseUnmappedSectionGuard(cdp) {
  await clickButtonContainingText(cdp, "研究背景");
  await waitForCondition(cdp, `
    document.body.textContent.includes("当前章节暂无后端章节绑定") &&
    (() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").includes("提交AI修订"));
      return Boolean(button && button.disabled);
    })()
  `, 10000);
  const guardMetrics = await evaluate(cdp, `
    (() => {
      const submitButton = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").includes("提交AI修订"));
      const quickActionEnabled = Array.from(document.querySelectorAll(".writing-title-ai-actions button")).some((item) => !item.disabled);
      const activeThreadText = document.querySelector(".revision-thread")?.textContent || "";
      return {
        hasUnmappedWarning: document.body.textContent.includes("当前章节暂无后端章节绑定"),
        submitDisabled: Boolean(submitButton?.disabled),
        quickActionEnabled,
        leaksOtherSectionThread: activeThreadText.includes("研究目的与终点") || activeThreadText.includes("thread_"),
      };
    })()
  `);
  await clickButtonContainingText(cdp, "研究目的与终点");
  await waitForCondition(cdp, `document.body.textContent.includes("研究目的与终点")`);
  return guardMetrics;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  await backupAndClearReviewStore();
  await seedTflWritingCandidate();
  const aiStatus = await requestJson(apiUrl("/api/ai-gateway/status")).catch(() => ({ configured: false }));
  const userDataDir = await mkdtemp(path.join(tmpdir(), "medical-writing-qc-"));
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

    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await cdp.send("Page.navigate", { url: appUrl });
    await openWritingPage(cdp);
    const desktopUnmappedGuard = await exerciseUnmappedSectionGuard(cdp);
    const desktopRevisionRun = await exerciseRevisionWorkflow(cdp, "desktop", Boolean(aiStatus.configured));
    const desktopMetrics = await captureWritingMetrics(cdp);
    const desktopShot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: true });
    const desktopPath = path.join(outputDir, "medical_writing_manifest_desktop.png");
    await writeFile(desktopPath, Buffer.from(desktopShot.data, "base64"));

    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 390,
      height: 1100,
      deviceScaleFactor: 2,
      mobile: true,
    });
    await cdp.send("Page.navigate", { url: appUrl });
    await openWritingPage(cdp);
    const mobileUnmappedGuard = await exerciseUnmappedSectionGuard(cdp);
    const mobileRevisionRun = await exerciseRevisionWorkflow(cdp, "mobile-smoke", Boolean(aiStatus.configured));
    const mobileMetrics = await captureWritingMetrics(cdp);
    const mobileShot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: true });
    const mobilePath = path.join(outputDir, "medical_writing_manifest_mobile-smoke.png");
    await writeFile(mobilePath, Buffer.from(mobileShot.data, "base64"));

    const failures = [];
    for (const [label, guard] of [["desktop", desktopUnmappedGuard], ["mobile-smoke", mobileUnmappedGuard]]) {
      if (!guard.hasUnmappedWarning) failures.push(`${label}:unmappedGuardWarning`);
      if (!guard.submitDisabled) failures.push(`${label}:unmappedGuardSubmitDisabled`);
      if (guard.quickActionEnabled) failures.push(`${label}:unmappedGuardQuickActionsEnabled`);
      if (guard.leaksOtherSectionThread) failures.push(`${label}:unmappedGuardLeaksOtherSectionThread`);
    }
    for (const [label, metrics] of [["desktop", desktopMetrics], ["mobile-smoke", mobileMetrics]]) {
      const desktopRequired = label === "desktop";
      if (!desktopRequired) {
        for (const key of ["hasTitle", "hasEditor"]) {
          if (!metrics[key]) failures.push(`${label}:${key}`);
        }
        if (metrics.hasForbiddenLifecycleText) failures.push(`${label}:hasForbiddenLifecycleText`);
        if (metrics.hasForbiddenOverclaim) failures.push(`${label}:hasForbiddenOverclaim`);
        if (metrics.leaksLocalPath) failures.push(`${label}:leaksLocalPath`);
        if (metrics.leaksSourceConfigInOuterHtml) failures.push(`${label}:leaksSourceConfigInOuterHtml`);
        continue;
      }
      for (const key of [
        "hasTitle",
        "hasManifest",
        "hasRuxPackage",
        "hasD001Package",
        "hasDocxBoundary",
        "hasReviewDocx",
        "hasFormalExportBlock",
        "hasIndependentAiBoundary",
        "hasTflCitationPanel",
        "hasTflCitationCandidate",
        "hasTflCitationBoundary",
        "hasEditor",
        "hasRevisionForm",
        "editorInFirstViewport",
        "aiRailInFirstViewport",
        "submitAiButtonInFirstViewport",
        "editorBeforeSourceManifest",
        "aiRailBeforeSourceManifest",
        "sourceManifestBelowCore",
        "editorAndAiSameWorkRow",
        "editorWiderThanAi",
        "documentMapSecondaryRail",
        "documentMapSupportsEditor",
        "hasRevisionThreadList",
        "hasRevisionBoundary",
        "hasRevisionStubBoundary",
        "approvalButtonDisabled",
      ]) {
        if (!metrics[key]) failures.push(`${label}:${key}`);
      }
      if (aiStatus.configured) {
        for (const key of ["hasRevisionSuggestion", "hasAcceptedCandidate"]) {
          if (!metrics[key]) failures.push(`${label}:${key}`);
        }
        if (metrics.revisionThreadRows < 1) failures.push(`${label}:revisionThreadRows`);
      } else {
        if (!metrics.hasBlockedRevisionMessage) failures.push(`${label}:hasBlockedRevisionMessage`);
        if (metrics.revisionThreadRows !== 0) failures.push(`${label}:revisionThreadRows`);
      }
      if (metrics.editorTextContainsAiSuggestion) failures.push(`${label}:editorTextContainsAiSuggestion`);
      if (metrics.documentRows < 1) failures.push(`${label}:documentRows`);
      if (metrics.sectionRows < 4) failures.push(`${label}:sectionRows`);
      if (metrics.tableRows < 10) failures.push(`${label}:tableRows`);
      if (metrics.gateRows < 8) failures.push(`${label}:gateRows`);
      if (metrics.citationRows < 1) failures.push(`${label}:citationRows`);
      if (metrics.citationGateRows < 3) failures.push(`${label}:citationGateRows`);
      if (metrics.hasForbiddenLifecycleText) failures.push(`${label}:hasForbiddenLifecycleText`);
      if (metrics.hasForbiddenOverclaim) failures.push(`${label}:hasForbiddenOverclaim`);
      if (metrics.leaksLocalPath) failures.push(`${label}:leaksLocalPath`);
      if (metrics.leaksSourceConfigInOuterHtml) failures.push(`${label}:leaksSourceConfigInOuterHtml`);
      if (desktopRequired && metrics.overflowX) failures.push(`${label}:overflowX`);
    }

    const report = { aiStatus, desktopUnmappedGuard, mobileUnmappedGuard, desktopRevisionRun, mobileRevisionRun, desktopMetrics, mobileMetrics, desktopPath, mobilePath, failures };
    await writeFile(path.join(outputDir, "medical_writing_manifest_qc.json"), JSON.stringify(report, null, 2), "utf8");
    if (failures.length) throw new Error(`Medical writing manifest QC failed: ${failures.join(", ")}`);
    cdp.close();
  } finally {
    chrome.kill("SIGTERM");
    await restoreReviewStore();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
