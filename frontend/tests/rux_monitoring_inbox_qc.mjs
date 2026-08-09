import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5176/";
const apiBase = process.env.API_BASE || "http://127.0.0.1:8920";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "records/visual_qc_20260708/rux_monitoring_inbox");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9375);
const actionsPath = process.env.WORKBENCH_INBOX_ACTIONS_PATH
  || path.resolve(process.cwd(), "../..", "runtime/workbench_inbox_actions.jsonl");
const dispositionActionsPath = process.env.RUX_RISK_DISPOSITION_ACTIONS_PATH
  || path.resolve(process.cwd(), "../..", "runtime/rux_risk_disposition_actions.jsonl");
const approvalRuntimePaths = [
  process.env.APPROVAL_GATES_PATH || path.resolve(process.cwd(), "../..", "runtime/approval_gates.jsonl"),
  process.env.APPROVAL_DECISIONS_PATH || path.resolve(process.cwd(), "../..", "runtime/approval_decisions.jsonl"),
  process.env.APPROVAL_AUDIT_EVENTS_PATH || path.resolve(process.cwd(), "../..", "runtime/approval_audit_events.jsonl"),
];
const targetRiskText = "S01017 ALT/AST >5xULN";
const targetSubjectId = "S01017";
const internalSourceLeakPattern = new RegExp(
  "/Users/|file://|root_path|file_path|absolute_path|allowed_roots|content_hash|preview_hash|storage_key|server_path|source_record_id|rux-risk:|rux_03_002_listing_20250612",
  "i",
);

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
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

async function resetActionStores() {
  await mkdir(path.dirname(actionsPath), { recursive: true });
  await mkdir(path.dirname(dispositionActionsPath), { recursive: true });
  await writeFile(actionsPath, "", "utf8");
  await writeFile(dispositionActionsPath, "", "utf8");
  for (const filePath of approvalRuntimePaths) {
    await mkdir(path.dirname(filePath), { recursive: true });
    await writeFile(filePath, "", "utf8");
  }
}

async function backupFile(filePath) {
  if (!existsSync(filePath)) return { filePath, existed: false, content: "" };
  return { filePath, existed: true, content: await readFile(filePath, "utf8") };
}

async function restoreFile(backup) {
  if (backup.existed) {
    await writeFile(backup.filePath, backup.content, "utf8");
  } else if (existsSync(backup.filePath)) {
    await rm(backup.filePath);
  }
}

function createCdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  const listeners = new Map();

  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result || {});
      return;
    }
    (listeners.get(message.method) || []).forEach((callback) => callback(message.params || {}));
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
    once(method) {
      return new Promise((resolve) => {
        const callback = (params) => {
          const callbacks = listeners.get(method) || [];
          listeners.set(method, callbacks.filter((item) => item !== callback));
          resolve(params);
        };
        listeners.set(method, [...(listeners.get(method) || []), callback]);
      });
    },
    close() {
      ws.close();
    },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.exception?.value || result.exceptionDetails.text;
    throw new Error(detail || "Runtime evaluation failed");
  }
  return result.result?.value;
}

async function waitForText(cdp, text, timeoutMs = 10000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(cdp, `document.body.textContent.includes(${JSON.stringify(text)})`)) return true;
    await wait(250);
  }
  return false;
}

async function waitForCondition(cdp, expression, timeoutMs = 10000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(cdp, expression)) return true;
    await wait(250);
  }
  return false;
}

async function waitForEnabledButton(cdp, text, timeoutMs = 10000) {
  const expression = `
    Array.from(document.querySelectorAll("button"))
      .some((button) => button.textContent.includes(${JSON.stringify(text)}) && !button.disabled)
  `;
  if (!(await waitForCondition(cdp, expression, timeoutMs))) {
    throw new Error(`Enabled button did not appear: ${text}`);
  }
}

async function clickByText(cdp, selector, text) {
  await evaluate(cdp, `
    (() => {
      const target = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
        .find((item) => item.textContent.includes(${JSON.stringify(text)}));
      if (!target) throw new Error("Missing " + ${JSON.stringify(selector)} + " text: " + ${JSON.stringify(text)});
      target.click();
      return true;
    })()
  `);
}

async function navigateToMonitoring(cdp, viewport) {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: viewport.width,
    height: viewport.height,
    deviceScaleFactor: 1,
    mobile: viewport.mobile,
  });
  const loaded = cdp.once("Page.loadEventFired");
  await cdp.send("Page.navigate", { url: appUrl });
  await loaded;
  if (!(await waitForText(cdp, "RUX-03-002", 30000))) throw new Error("Dashboard did not load RUX project");
  await clickByText(cdp, "button", "医学监查");
  if (!(await waitForText(cdp, targetRiskText, 30000))) throw new Error("Monitoring page did not render real RUX inbox risk");
}

async function capturePage(cdp, name, stage) {
  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: true,
  });
  const screenshotPath = path.join(outputDir, `rux_monitoring_inbox_${name}_${stage}.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return screenshotPath;
}

async function runViewport(cdp, name, viewport) {
  await resetActionStores();
  const beforeInbox = await requestJson(`${apiBase}/api/projects/proj_rux_03_002/workbench-inbox?limit=20`);
  const targetItem = beforeInbox.items.find((item) => item.title.includes(targetRiskText));
  if (!targetItem) throw new Error(`API baseline missing target risk ${targetRiskText}`);
  if (!targetItem.unread) throw new Error("Target risk is not unread after action-store reset");
  if (targetItem.status !== "待医学复核") throw new Error(`Unexpected baseline status: ${targetItem.status}`);

  await navigateToMonitoring(cdp, viewport);
  await clickByText(cdp, ".risk-card-row", targetRiskText);
  await waitForText(cdp, "基于已验证规则锚点", 10000);

  const monitoringMetricsBefore = await evaluate(cdp, `
    (() => {
      const text = document.body.textContent || "";
      const topbarText = document.querySelector(".topbar")?.textContent || "";
      const detailText = document.querySelector(".risk-detail")?.textContent || "";
      const detailHtml = document.querySelector(".risk-detail")?.outerHTML || "";
      const pageHtml = document.querySelector(".monitoring-page")?.outerHTML || "";
      const rows = Array.from(document.querySelectorAll(".risk-card-row")).map((row) => row.textContent || "");
      const primaryButtons = Array.from(document.querySelectorAll(".risk-detail button.primary-button")).map((button) => button.textContent || "");
      const sourceLeakPattern = /\\/Users\\/|file:\\/\\/|root_path|file_path|absolute_path|allowed_roots|content_hash|preview_hash|storage_key|server_path|source_record_id/i;
      const doc = document.documentElement;
      const body = document.body;
      return {
        rowCount: rows.length,
        hasRealSubjects: rows.some((row) => row.includes("S01003")) && rows.some((row) => row.includes("S01017")) && rows.some((row) => row.includes("S03040")),
        hasTargetRisk: detailText.includes(${JSON.stringify(targetRiskText)}),
        hasBoundaryNote: detailText.includes("当前RUX P0医学监查风险集仅覆盖已验证规则锚点"),
        hasListingSource: detailText.includes("原始数据 listing 行"),
        hasProtocolSource: detailText.includes("方案条款定位"),
        hasMarkReadButton: Array.from(document.querySelectorAll("button")).some((button) => button.textContent.includes("标记已读")),
        hasDispositionSteps: detailText.includes("待医学复核") && detailText.includes("已医学复核") && detailText.includes("Query草稿") && detailText.includes("已提交内部审批"),
        hasReviewButton: Array.from(document.querySelectorAll("button")).some((button) => button.textContent.includes("标记已复核") && !button.disabled),
        hasQueryDraftButton: Array.from(document.querySelectorAll("button")).some((button) => button.textContent.includes("记录Query草稿")),
        hasSubmitInternalApprovalButton: Array.from(document.querySelectorAll("button")).some((button) => button.textContent.includes("提交内部审批")),
        reviewButtonIsPrimary: primaryButtons.some((text) => text.includes("标记已复核")),
        readButtonIsPrimary: primaryButtons.some((text) => text.includes("标记已读")),
        hasInternalApprovalBoundary: detailText.includes("提交内部审批不代表对外动作、归档动作或医学定稿已经完成"),
        hasForbiddenDispositionOverclaim: /已发中心|正式关闭|正式批准|自动关闭|可直接归档|已完成医学定稿/.test(detailText),
        detailSourceAttrLeak: sourceLeakPattern.test(detailHtml),
        pageSourceAttrLeak: sourceLeakPattern.test(pageHtml),
        topbarReadableBatch: topbarText.includes("RUX-03-002 原始数据 listing 2025-06-12"),
        topbarTechnicalBatchLeak: topbarText.includes("rux_03_002_listing_20250612"),
        demoLeak: /(MG-K10|10008|06021|10021|10045|氯雷他定|抗组胺药洗脱不足|Batch 003 vs Batch 002|Batch 004 demo listing|AESI_FLAG|\\/Users\\/|content_hash|preview_hash|storage_key|server_path|source_record_id)/.test(text),
        overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
      };
    })()
  `);
  const monitoringScreenshot = await capturePage(cdp, name, "monitoring_detail_before_read");

  await clickByText(cdp, "button", "标记已读");
  if (!(await waitForText(cdp, "已标记已读并写入收件箱审计", 10000))) {
    throw new Error("mark_read UI feedback did not appear");
  }
  await wait(500);
  const afterReadInbox = await requestJson(`${apiBase}/api/projects/proj_rux_03_002/workbench-inbox?limit=20`);
  const afterReadItem = afterReadInbox.items.find((item) => item.item_id === targetItem.item_id);

  await waitForEnabledButton(cdp, "标记已复核");
  await clickByText(cdp, "button", "标记已复核");
  if (!(await waitForText(cdp, "已记录医学复核", 10000))) {
    throw new Error("reviewed UI feedback did not appear");
  }
  await waitForEnabledButton(cdp, "记录Query草稿");
  const afterReviewedInbox = await requestJson(`${apiBase}/api/projects/proj_rux_03_002/workbench-inbox?limit=20`);
  const afterReviewedItem = afterReviewedInbox.items.find((item) => item.item_id === targetItem.item_id);

  await clickByText(cdp, "button", "记录Query草稿");
  if (!(await waitForText(cdp, "已记录Query草稿", 10000))) {
    throw new Error("query draft UI feedback did not appear");
  }
  await waitForEnabledButton(cdp, "提交内部审批");
  const afterDraftInbox = await requestJson(`${apiBase}/api/projects/proj_rux_03_002/workbench-inbox?limit=20`);
  const afterDraftItem = afterDraftInbox.items.find((item) => item.item_id === targetItem.item_id);

  await clickByText(cdp, "button", "提交内部审批");
  if (!(await waitForText(cdp, "已提交内部审批", 10000))) {
    throw new Error("submit internal approval UI feedback did not appear");
  }
  await waitForText(cdp, "查看内部审批状态", 10000);
  const afterSubmitInbox = await requestJson(`${apiBase}/api/projects/proj_rux_03_002/workbench-inbox?limit=20`);
  const afterSubmitItem = afterSubmitInbox.items.find((item) => item.item_id === targetItem.item_id);
  const afterSubmitDashboard = await requestJson(`${apiBase}/api/projects/proj_rux_03_002/dashboard`);
  const afterSubmitRuxApproval = (afterSubmitDashboard.pending_approvals || []).find(
    (item) => item.target_type === "medical_monitoring_risk_disposition" && item.target_id === targetItem.source_id
  );

  await clickByText(cdp, "button", "进入 Subject Timeline");
  if (!(await waitForText(cdp, targetSubjectId, 30000))) throw new Error("Subject Timeline did not show selected subject");
  const timelineMetrics = await evaluate(cdp, `
    (() => {
      const text = document.querySelector(".reference-timeline-page")?.textContent || "";
      const doc = document.documentElement;
      const body = document.body;
      return {
        hasSubject: text.includes(${JSON.stringify(targetSubjectId)}),
        hasLabLane: text.includes("实验室/疗效 明细"),
        hasAltAst: text.includes("ALT") || text.includes("AST"),
        overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
      };
    })()
  `);
  const timelineScreenshot = await capturePage(cdp, name, "subject_timeline");

  await clickByText(cdp, "button", "返回医学监查");
  await waitForText(cdp, "进入 Patient Profile", 10000);
  await clickByText(cdp, "button", "进入 Patient Profile");
  if (!(await waitForText(cdp, "疗效指标历时变化", 30000))) throw new Error("Patient Profile did not load");
  const profileMetrics = await evaluate(cdp, `
    (() => {
      const text = document.querySelector(".patient-profile-page")?.textContent || "";
      const doc = document.documentElement;
      const body = document.body;
      return {
        hasSubject: text.includes(${JSON.stringify(targetSubjectId)}),
        hasCoreTrends: text.includes("BSA总受累体表面积") && text.includes("IGA评分") && text.includes("EASI总分") && text.includes("SCORAD总分") && text.includes("中性粒细胞计数") && text.includes("ALT") && text.includes("AST"),
        overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
      };
    })()
  `);
  const profileScreenshot = await capturePage(cdp, name, "patient_profile");

  await clickByText(cdp, "button", "审批中心");
  if (!(await waitForText(cdp, "RUX内部Query草稿审批", 30000))) throw new Error("Approval Center did not show RUX internal approval");
  const approvalMetrics = await evaluate(cdp, `
    (() => {
      const approvalText = document.querySelector(".approval-layout")?.textContent || "";
      const approvalHtml = document.querySelector(".approval-layout")?.outerHTML || "";
      const rows = Array.from(document.querySelectorAll(".approval-list button")).map((button) => button.textContent || "");
      const detail = document.querySelector(".approval-detail")?.textContent || "";
      const buttons = Array.from(document.querySelectorAll(".approval-detail button")).map((button) => ({
        text: button.textContent || "",
        disabled: button.disabled,
        primary: button.classList.contains("primary-button"),
      }));
      const sourceLeakPattern = /\\/Users\\/|file:\\/\\/|root_path|file_path|absolute_path|allowed_roots|content_hash|preview_hash|storage_key|server_path|source_record_id|rux-risk:|rux_03_002_listing_20250612/i;
      const doc = document.documentElement;
      const body = document.body;
      return {
        hasApprovalCenter: document.body.textContent.includes("审批中心"),
        hasRuxApprovalRow: rows.some((text) => /RUX内部Query草稿审批/.test(text) && /S01017/.test(text) && /ALT\\/AST/.test(text)),
        hasClinicalTitle: /RUX内部Query草稿审批/.test(detail) && /S01017/.test(detail) && /ALT\\/AST/.test(detail),
        hasInternalApprovalBoundary: /仅批准内部Query草稿\\/处置建议/.test(detail) && /不代表对外Query已执行、风险关闭或归档/.test(detail),
        hasForbiddenOverclaim: /已发中心|正式批准|自动关闭|可直接归档|已完成医学定稿|电子签名已完成/.test(approvalText),
        leaksInternalSource: sourceLeakPattern.test(approvalText + approvalHtml),
        hasOnlyBoundedActions: buttons.every((button) => /查看质量门|批准|退回修订|驳回|处理中/.test(button.text)),
        approveDisabledWithoutComment: buttons.some((button) => button.text.includes("批准") && button.disabled),
        overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
      };
    })()
  `);
  const approvalScreenshot = await capturePage(cdp, name, "approval_center");
  await clickByText(cdp, "button", "查看质量门");
  if (!(await waitForText(cdp, "已读取后端质量门结果", 10000))) {
    throw new Error("Approval quality-gate feedback did not appear");
  }
  const afterQualityGateDashboard = await requestJson(`${apiBase}/api/projects/proj_rux_03_002/dashboard`);
  const afterQualityGateRuxApproval = (afterQualityGateDashboard.pending_approvals || []).find(
    (item) => item.approval_id === afterSubmitRuxApproval?.approval_id
  );

  return {
    viewport: name,
    targetItemId: targetItem.item_id,
    targetSourceId: targetItem.source_id,
    beforeUnreadCount: beforeInbox.unread_count,
    afterReadUnreadCount: afterReadInbox.unread_count,
    beforeTotalOpenCount: beforeInbox.total_open_count,
    afterReadTotalOpenCount: afterReadInbox.total_open_count,
    afterSubmitTotalOpenCount: afterSubmitInbox.total_open_count,
    afterReadItemStillExists: Boolean(afterReadItem),
    afterReadItemUnread: afterReadItem?.unread,
    afterReadItemStatus: afterReadItem?.status,
    afterReviewedItemStatus: afterReviewedItem?.status,
    afterReviewedItemActionLabel: afterReviewedItem?.action_label,
    afterReviewedItemUnread: afterReviewedItem?.unread,
    afterDraftItemStatus: afterDraftItem?.status,
    afterDraftItemActionLabel: afterDraftItem?.action_label,
    afterDraftItemNeedsAction: afterDraftItem?.needs_action,
    afterSubmitItemStillExists: Boolean(afterSubmitItem),
    afterSubmitItemStatus: afterSubmitItem?.status,
    afterSubmitItemActionLabel: afterSubmitItem?.action_label,
    afterSubmitItemNeedsAction: afterSubmitItem?.needs_action,
    afterSubmitItemUnread: afterSubmitItem?.unread,
    hasAfterSubmitRuxApproval: Boolean(afterSubmitRuxApproval),
    afterSubmitRuxApprovalId: afterSubmitRuxApproval?.approval_id,
    afterSubmitRuxApprovalState: afterSubmitRuxApproval?.state,
    afterSubmitRuxApprovalTargetType: afterSubmitRuxApproval?.target_type,
    afterSubmitRuxApprovalComments: afterSubmitRuxApproval?.review_comments,
    afterQualityGateStillPending: Boolean(afterQualityGateRuxApproval),
    afterQualityGateRuxApprovalState: afterQualityGateRuxApproval?.state,
    monitoringMetricsBefore,
    timelineMetrics,
    profileMetrics,
    approvalMetrics,
    screenshots: { monitoringScreenshot, timelineScreenshot, profileScreenshot, approvalScreenshot },
  };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const actionBackup = await backupFile(actionsPath);
  const dispositionBackup = await backupFile(dispositionActionsPath);
  const approvalBackups = await Promise.all(approvalRuntimePaths.map((filePath) => backupFile(filePath)));
  const userDataDir = await mkdtemp(path.join(tmpdir(), "rux-monitoring-inbox-qc-"));
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
    let targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    let target = targets.find((item) => item.type === "page");
    if (!target) {
      await fetch(`http://127.0.0.1:${debugPort}/json/new?about:blank`, { method: "PUT" });
      targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
      target = targets.find((item) => item.type === "page");
    }
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Chrome page target found.");

    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");

    const results = [];
    results.push(await runViewport(cdp, "desktop", { width: 1440, height: 1200, mobile: false }));
    results.push(await runViewport(cdp, "mobile", { width: 390, height: 1200, mobile: true }));
    cdp.close();

    const metricsPath = path.join(outputDir, "rux_monitoring_inbox_metrics.json");
    await writeFile(metricsPath, `${JSON.stringify({ appUrl, apiBase, targetRiskText, results }, null, 2)}\n`, "utf8");

    const failures = [];
    for (const result of results) {
      const monitor = result.monitoringMetricsBefore;
      if (monitor.rowCount < 4) failures.push(`${result.viewport}: fewer than four RUX monitoring risks`);
      if (!monitor.hasRealSubjects) failures.push(`${result.viewport}: missing expected RUX subjects in risk list`);
      if (!monitor.hasTargetRisk) failures.push(`${result.viewport}: detail did not show target risk`);
      if (!monitor.hasBoundaryNote) failures.push(`${result.viewport}: missing RUX P0 boundary note`);
      if (!monitor.hasListingSource) failures.push(`${result.viewport}: missing listing source refs`);
      if (!monitor.hasProtocolSource) failures.push(`${result.viewport}: missing protocol source refs`);
      if (!monitor.hasMarkReadButton) failures.push(`${result.viewport}: missing mark-read action`);
      if (!monitor.hasDispositionSteps) failures.push(`${result.viewport}: missing disposition state steps`);
      if (!monitor.hasReviewButton) failures.push(`${result.viewport}: missing enabled review action`);
      if (!monitor.hasQueryDraftButton) failures.push(`${result.viewport}: missing query draft action`);
      if (!monitor.hasSubmitInternalApprovalButton) failures.push(`${result.viewport}: missing submit internal approval action`);
      if (!monitor.reviewButtonIsPrimary) failures.push(`${result.viewport}: review action is not primary at pending state`);
      if (monitor.readButtonIsPrimary) failures.push(`${result.viewport}: mark-read should not be primary action`);
      if (!monitor.hasInternalApprovalBoundary) failures.push(`${result.viewport}: missing internal-approval boundary copy`);
      if (monitor.hasForbiddenDispositionOverclaim) failures.push(`${result.viewport}: disposition overclaim text present`);
      if (monitor.detailSourceAttrLeak) failures.push(`${result.viewport}: risk detail source attribute leak`);
      if (monitor.pageSourceAttrLeak) failures.push(`${result.viewport}: monitoring page source attribute leak`);
      if (!monitor.topbarReadableBatch) failures.push(`${result.viewport}: missing readable RUX batch label`);
      if (monitor.topbarTechnicalBatchLeak) failures.push(`${result.viewport}: technical batch id leaked`);
      if (monitor.demoLeak) failures.push(`${result.viewport}: demo/internal text leaked into RUX monitoring page`);
      if (monitor.overflowX) failures.push(`${result.viewport}: monitoring page overflow`);
      if (result.afterReadUnreadCount !== result.beforeUnreadCount - 1) failures.push(`${result.viewport}: unread count did not decrement by one`);
      if (result.afterReadTotalOpenCount !== result.beforeTotalOpenCount) failures.push(`${result.viewport}: mark-read changed total open count`);
      if (!result.afterReadItemStillExists) failures.push(`${result.viewport}: marked item disappeared from inbox`);
      if (result.afterReadItemUnread) failures.push(`${result.viewport}: marked item is still unread after API refetch`);
      if (result.afterReadItemStatus !== "待医学复核") failures.push(`${result.viewport}: mark-read changed disposition status`);
      if (result.afterReviewedItemStatus !== "已医学复核") failures.push(`${result.viewport}: reviewed status not persisted`);
      if (result.afterReviewedItemActionLabel !== "记录Query草稿") failures.push(`${result.viewport}: reviewed action label not persisted`);
      if (result.afterReviewedItemUnread) failures.push(`${result.viewport}: reviewed state reintroduced unread`);
      if (result.afterDraftItemStatus !== "Query草稿") failures.push(`${result.viewport}: query draft status not persisted`);
      if (result.afterDraftItemActionLabel !== "提交内部审批") failures.push(`${result.viewport}: query draft action label not internal approval`);
      if (result.afterDraftItemNeedsAction !== true) failures.push(`${result.viewport}: query draft should still need action`);
      if (!result.afterSubmitItemStillExists) failures.push(`${result.viewport}: submitted item disappeared from inbox`);
      if (result.afterSubmitItemStatus !== "已提交内部审批") failures.push(`${result.viewport}: submitted status not internal approval`);
      if (result.afterSubmitItemActionLabel !== "查看内部审批状态") failures.push(`${result.viewport}: submitted action label not internal status`);
      if (result.afterSubmitItemNeedsAction !== false) failures.push(`${result.viewport}: submitted internal approval should clear direct action`);
      if (result.afterSubmitItemUnread) failures.push(`${result.viewport}: submitted state reintroduced unread`);
      if (result.afterSubmitTotalOpenCount !== result.beforeTotalOpenCount) failures.push(`${result.viewport}: disposition state changed total open count unexpectedly`);
      if (!result.hasAfterSubmitRuxApproval) failures.push(`${result.viewport}: RUX internal approval was not projected to dashboard pending approvals`);
      if (result.afterSubmitRuxApprovalState !== "in_medical_review") failures.push(`${result.viewport}: RUX approval state is not in medical review`);
      if (result.afterSubmitRuxApprovalTargetType !== "medical_monitoring_risk_disposition") failures.push(`${result.viewport}: RUX approval target type mismatch`);
      if (internalSourceLeakPattern.test(result.afterSubmitRuxApprovalComments || "")) failures.push(`${result.viewport}: RUX approval comment leaks internal source config`);
      if (/已发中心|正式批准|自动关闭|可直接归档|已完成医学定稿|电子签名已完成/.test(result.afterSubmitRuxApprovalComments || "")) failures.push(`${result.viewport}: RUX approval comment contains overclaim`);
      if (!result.approvalMetrics.hasApprovalCenter) failures.push(`${result.viewport}: approval center not visible`);
      if (!result.approvalMetrics.hasRuxApprovalRow) failures.push(`${result.viewport}: RUX approval row missing clinical title`);
      if (!result.approvalMetrics.hasClinicalTitle) failures.push(`${result.viewport}: RUX approval detail missing clinical title`);
      if (!result.approvalMetrics.hasInternalApprovalBoundary) failures.push(`${result.viewport}: RUX approval detail missing internal-approval boundary`);
      if (result.approvalMetrics.hasForbiddenOverclaim) failures.push(`${result.viewport}: approval center overclaim text present`);
      if (result.approvalMetrics.leaksInternalSource) failures.push(`${result.viewport}: approval center source/internal leak`);
      if (!result.approvalMetrics.hasOnlyBoundedActions) failures.push(`${result.viewport}: approval center exposed unbounded actions`);
      if (!result.approvalMetrics.approveDisabledWithoutComment) failures.push(`${result.viewport}: approve should be disabled without comment`);
      if (result.approvalMetrics.overflowX) failures.push(`${result.viewport}: approval center overflow`);
      if (!result.afterQualityGateStillPending) failures.push(`${result.viewport}: view quality gate mutated or removed the RUX approval`);
      if (result.afterQualityGateRuxApprovalState !== "in_medical_review") failures.push(`${result.viewport}: quality-gate view changed RUX approval state`);
      if (!result.timelineMetrics.hasSubject || !result.timelineMetrics.hasLabLane || !result.timelineMetrics.hasAltAst) failures.push(`${result.viewport}: Subject Timeline handoff failed`);
      if (result.timelineMetrics.overflowX) failures.push(`${result.viewport}: Subject Timeline overflow`);
      if (!result.profileMetrics.hasSubject || !result.profileMetrics.hasCoreTrends) failures.push(`${result.viewport}: Patient Profile handoff failed`);
      if (result.profileMetrics.overflowX) failures.push(`${result.viewport}: Patient Profile overflow`);
    }
    if (failures.length) throw new Error(`RUX monitoring inbox QC failed: ${failures.join("; ")}. Metrics: ${metricsPath}`);
    console.log(metricsPath);
  } finally {
    chrome.kill("SIGTERM");
    await restoreFile(actionBackup);
    await restoreFile(dispositionBackup);
    for (const backup of approvalBackups) {
      await restoreFile(backup);
    }
  }
}

main().catch(async (error) => {
  console.error(error);
  process.exit(1);
});
