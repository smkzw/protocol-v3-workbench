import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const workspaceRoot = path.resolve(scriptDir, "../..");
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.join(workspaceRoot, "records/visual_qc_20260711/evidence_interactions");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9371);

const projects = [
  {
    projectId: "proj_mgk10_crswnp",
    key: "crswnp",
    packageLabel: "CRSwNP竞品证据与方案设计资料包",
    typeLabel: "临床试验",
    searchTerm: "CM310",
    appraisalLabel: "中等质量",
    unfilteredTotal: 138,
  },
  {
    projectId: "proj_my008_pnh_3_01",
    key: "pnh",
    packageLabel: "PNH竞品证据与方案设计资料包",
    typeLabel: "公开发表",
    searchTerm: "eculizumab",
    appraisalLabel: "高质量",
    unfilteredTotal: 134,
  },
];

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function requestJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 12000) {
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
    await wait(180);
  }
  throw new Error(`Timed out waiting for condition. Last value: ${JSON.stringify(lastValue)}\n${expression}`);
}

async function clickByText(cdp, label, rootSelector = "body") {
  const clicked = await evaluate(cdp, `
    (() => {
      const root = document.querySelector(${JSON.stringify(rootSelector)});
      const button = Array.from(root?.querySelectorAll("button") || []).find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)});
      if (!button || button.disabled) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Enabled button not found: ${rootSelector} -> ${label}`);
}

async function clickByTitle(cdp, title, rootSelector = "body") {
  const clicked = await evaluate(cdp, `
    (() => {
      const root = document.querySelector(${JSON.stringify(rootSelector)});
      const button = Array.from(root?.querySelectorAll("button") || []).find((item) => item.title === ${JSON.stringify(title)});
      if (!button || button.disabled) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Enabled button not found by title: ${rootSelector} -> ${title}`);
}

async function setValue(cdp, selector, value) {
  const changed = await evaluate(cdp, `
    (() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element || element.disabled) return false;
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
      setter.call(element, ${JSON.stringify(value)});
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
      return element.value;
    })()
  `);
  if (changed !== value) throw new Error(`Unable to set ${selector}`);
}

async function selectProject(cdp, project) {
  await waitForCondition(cdp, `
    Array.from(document.querySelector('select[aria-label="选择临床研究项目"]')?.options || [])
      .some((item) => item.value === ${JSON.stringify(project.projectId)})
  `);
  const changed = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select || !Array.from(select.options).some((item) => item.value === ${JSON.stringify(project.projectId)})) return false;
      select.value = ${JSON.stringify(project.projectId)};
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Project not available: ${project.projectId}`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(project.projectId)}`);
  await clickByText(cdp, "证据调研与方案设计");
  await waitForCondition(cdp, `
    Boolean(document.querySelector(".evidence-workspace-grid")) &&
    document.body.textContent.includes(${JSON.stringify(project.packageLabel)}) &&
    document.querySelectorAll(".evidence-candidate-table tbody tr").length === 25
  `);
}

async function selectedReviewRevision(cdp) {
  return evaluate(cdp, `Number(document.querySelector(".evidence-candidate-table tbody tr.selected td:last-child")?.textContent || 0)`);
}

async function waitForReviewRevision(cdp, previous) {
  return waitForCondition(cdp, `Number(document.querySelector(".evidence-candidate-table tbody tr.selected td:last-child")?.textContent || 0) > ${Number(previous)}`);
}

async function waitForReviewStatus(cdp, status) {
  return waitForCondition(cdp, `document.querySelector(".evidence-detail-head .tag")?.textContent.trim() === ${JSON.stringify(status)}`);
}

async function reviewAction(cdp, buttonLabel, expectedStatus) {
  const previous = await selectedReviewRevision(cdp);
  await clickByText(cdp, buttonLabel, ".evidence-detail-actions");
  await waitForReviewRevision(cdp, previous);
  if (expectedStatus) await waitForReviewStatus(cdp, expectedStatus);
}

async function exerciseCandidateTable(cdp, project, trace) {
  await clickByTitle(cdp, project.typeLabel, ".evidence-type-chips");
  await waitForCondition(cdp, `document.querySelector(".evidence-type-chips button.active")?.textContent.includes(${JSON.stringify(project.typeLabel)})`);
  trace.push(`candidate_type:${project.typeLabel}`);

  await clickByTitle(cdp, "全部", ".evidence-type-chips");
  await waitForCondition(cdp, `document.querySelector(".evidence-type-chips button.active")?.textContent.includes("全部")`);
  await setValue(cdp, ".evidence-search-row input", project.searchTerm);
  await waitForCondition(cdp, `
    document.querySelectorAll(".evidence-candidate-table tbody tr").length > 0 &&
    !document.querySelector(".evidence-table-range")?.textContent.includes("/ ${project.unfilteredTotal}")
  `);
  trace.push(`search:${project.searchTerm}`);
  await clickByTitle(cdp, "清空搜索", ".evidence-search-row");
  await waitForCondition(cdp, `
    document.querySelectorAll(".evidence-candidate-table tbody tr").length === 25 &&
    document.querySelector(".evidence-table-range")?.textContent.includes("/ ${project.unfilteredTotal}") &&
    !document.querySelector('.evidence-table-paging button[title="下一页"]')?.disabled
  `);

  await clickByTitle(cdp, "下一页", ".evidence-table-paging");
  await waitForCondition(cdp, `
    document.querySelector(".evidence-table-paging span")?.textContent.includes("第 2 页") &&
    !document.querySelector('.evidence-table-paging button[title="上一页"]')?.disabled &&
    document.querySelectorAll(".evidence-candidate-table tbody tr").length > 0
  `);
  await clickByTitle(cdp, "上一页", ".evidence-table-paging");
  await waitForCondition(cdp, `
    document.querySelector(".evidence-table-paging span")?.textContent.includes("第 1 页") &&
    !document.querySelector('.evidence-table-paging button[title="下一页"]')?.disabled &&
    document.querySelectorAll(".evidence-candidate-table tbody tr").length === 25
  `);
  await clickByTitle(cdp, "刷新候选证据");
  await waitForCondition(cdp, `document.querySelectorAll(".evidence-candidate-table tbody tr").length === 25`);
  trace.push("paging_and_refresh");

  await evaluate(cdp, `document.querySelector(".evidence-candidate-table tbody tr")?.click()`);
  await waitForCondition(cdp, `Boolean(document.querySelector(".evidence-detail-head"))`);
  const checkboxBefore = await evaluate(cdp, `Boolean(document.querySelector(".evidence-candidate-table tbody tr.selected input[type=checkbox]")?.checked)`);
  await evaluate(cdp, `document.querySelector(".evidence-candidate-table tbody tr.selected input[type=checkbox]")?.click()`);
  await waitForCondition(cdp, `Boolean(document.querySelector(".evidence-candidate-table tbody tr.selected input[type=checkbox]")?.checked) === ${!checkboxBefore}`);
  await evaluate(cdp, `document.querySelector(".evidence-candidate-table tbody tr.selected input[type=checkbox]")?.click()`);
  await waitForCondition(cdp, `Boolean(document.querySelector(".evidence-candidate-table tbody tr.selected input[type=checkbox]")?.checked) === ${checkboxBefore}`);
  trace.push("candidate_select_and_ai_anchor_toggle");
}

async function exerciseEvidenceReview(cdp, project, trace) {
  const currentStatus = await evaluate(cdp, `document.querySelector(".evidence-detail-head .tag")?.textContent.trim()`);
  if (currentStatus !== "待筛选") await reviewAction(cdp, "重置", "待筛选");

  await reviewAction(cdp, "纳入", "已纳入");
  trace.push("review_include");

  await clickByText(cdp, "+ 添加字段", ".evidence-detail-section");
  await waitForCondition(cdp, `document.querySelectorAll(".evidence-extraction-row").length >= 1`);
  const rowCount = await evaluate(cdp, `document.querySelectorAll(".evidence-extraction-row").length`);
  await setValue(cdp, `.evidence-extraction-row:nth-of-type(${rowCount}) input:nth-of-type(1)`, "QC字段");
  await setValue(cdp, `.evidence-extraction-row:nth-of-type(${rowCount}) input:nth-of-type(2)`, `${project.key}-真实项目按钮回归`);
  await clickByText(cdp, "+ 添加字段", ".evidence-detail-section");
  await waitForCondition(cdp, `document.querySelectorAll(".evidence-extraction-row").length === ${rowCount + 1}`);
  await evaluate(cdp, `Array.from(document.querySelectorAll(".evidence-extraction-row button[title='删除行']")).at(-1)?.click()`);
  await waitForCondition(cdp, `document.querySelectorAll(".evidence-extraction-row").length === ${rowCount}`);
  let previous = await selectedReviewRevision(cdp);
  await clickByText(cdp, "保存结构化提取", ".evidence-detail-section");
  await waitForReviewRevision(cdp, previous);
  trace.push("extraction_add_delete_save");

  await clickByText(cdp, project.appraisalLabel, ".evidence-appraisal-options");
  previous = await selectedReviewRevision(cdp);
  await clickByTitle(cdp, "保存证据质量评价");
  await waitForReviewRevision(cdp, previous);
  trace.push(`appraisal:${project.appraisalLabel}`);

  const reason = `${project.key}真实项目QC：逐项验证排除、暂缓和重复状态机。`;
  await setValue(cdp, ".evidence-detail-reason textarea", reason);
  await reviewAction(cdp, "排除", "已排除");
  await reviewAction(cdp, "重置", "待筛选");
  await setValue(cdp, ".evidence-detail-reason textarea", reason);
  await reviewAction(cdp, "暂缓", "暂缓");
  await reviewAction(cdp, "重置", "待筛选");
  await setValue(cdp, ".evidence-detail-reason textarea", reason);
  await reviewAction(cdp, "重复", "重复");
  await reviewAction(cdp, "重置", "待筛选");
  trace.push("review_exclude_defer_duplicate_reset");
}

async function selectFirstPicosOption(cdp) {
  await evaluate(cdp, `document.querySelector(".evidence-picos-options button")?.click()`);
  await waitForCondition(cdp, `
    Boolean(document.querySelector(".evidence-picos-options button.selected")) &&
    !document.querySelector(".evidence-picos-options button:disabled")
  `);
}

async function preparePicosDomain(cdp, index, project, trace, exerciseReturnReset = false) {
  await evaluate(cdp, `document.querySelectorAll(".evidence-picos-domain-list-left button")[${index}]?.click()`);
  await waitForCondition(cdp, `document.querySelectorAll(".evidence-picos-domain-list-left button")[${index}]?.classList.contains("active")`);
  await selectFirstPicosOption(cdp);
  const rationale = `${project.key}真实项目医学理由：基于当前资料包证据，明确人群、干预、对照、终点或设计边界，并保留医学批准前复核。`;
  await setValue(cdp, ".evidence-picos-rationale textarea", rationale);
  await waitForCondition(cdp, `!Array.from(document.querySelectorAll(".evidence-picos-actions button")).find((item) => item.textContent.includes("保存医学理由"))?.disabled`);
  await clickByText(cdp, "保存医学理由", ".evidence-picos-actions");
  await waitForCondition(cdp, `
    document.querySelector(".evidence-picos-message")?.textContent.includes("PICOS决策已保存") &&
    !Array.from(document.querySelectorAll(".evidence-picos-actions button")).find((item) => item.textContent.includes("标记写作候选"))?.disabled
  `);
  await clickByText(cdp, "标记写作候选", ".evidence-picos-actions");
  await waitForCondition(cdp, `document.querySelector(".evidence-picos-question .tag")?.textContent.trim() === "写作候选"`);

  if (exerciseReturnReset) {
    await clickByText(cdp, "退回补证", ".evidence-picos-actions");
    await waitForCondition(cdp, `document.querySelector(".evidence-picos-question .tag")?.textContent.trim() === "退回补证"`);
    await clickByText(cdp, "重置", ".evidence-picos-actions");
    await waitForCondition(cdp, `document.querySelector(".evidence-picos-question .tag")?.textContent.trim() === "待医学确认"`);
    await selectFirstPicosOption(cdp);
    await setValue(cdp, ".evidence-picos-rationale textarea", rationale);
    await waitForCondition(cdp, `!Array.from(document.querySelectorAll(".evidence-picos-actions button")).find((item) => item.textContent.includes("保存医学理由"))?.disabled`);
    await clickByText(cdp, "保存医学理由", ".evidence-picos-actions");
    await waitForCondition(cdp, `
      document.querySelector(".evidence-picos-message")?.textContent.includes("PICOS决策已保存") &&
      !Array.from(document.querySelectorAll(".evidence-picos-actions button")).find((item) => item.textContent.includes("标记写作候选"))?.disabled
    `);
    await clickByText(cdp, "标记写作候选", ".evidence-picos-actions");
    await waitForCondition(cdp, `document.querySelector(".evidence-picos-question .tag")?.textContent.trim() === "写作候选"`);
    trace.push("picos_return_for_evidence_and_reset");
  }
}

async function exercisePicosAndApproval(cdp, project, trace) {
  await clickByText(cdp, "PICOS方案设计", ".evidence-mode-tabs");
  await waitForCondition(cdp, `document.querySelectorAll(".evidence-picos-domain-list-left button").length === 5`);
  await clickByTitle(cdp, "刷新PICOS方案设计");
  await waitForCondition(cdp, `document.querySelectorAll(".evidence-picos-domain-list-left button").length === 5`);
  for (let index = 0; index < 5; index += 1) {
    await preparePicosDomain(cdp, index, project, trace, index === 0);
  }
  await waitForCondition(cdp, `
    Array.from(document.querySelectorAll(".evidence-picos-domain-list-left .tag"))
      .filter((item) => item.textContent.trim() === "写作候选").length === 5
  `);
  trace.push("five_picos_domains_ready");

  await clickByText(cdp, "提交医学批准", ".evidence-picos-handoff");
  await waitForCondition(cdp, `document.body.textContent.includes("待医学批准内容") && document.body.textContent.includes("PICOS方案设计医学批准")`);
  trace.push("picos_submit_approval_and_route");

  const selected = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".approval-list button")).find((item) => item.textContent.includes("PICOS方案设计医学批准"));
      if (!button) return false;
      button.click();
      return true;
    })()
  `);
  if (!selected) throw new Error(`PICOS approval row not found for ${project.key}`);
  await clickByText(cdp, "查看质量门");
  await waitForCondition(cdp, `
    document.querySelector(".approval-message")?.textContent.includes("已读取后端质量门结果") &&
    !Array.from(document.querySelectorAll("button")).find((item) => item.textContent.trim() === "查看质量门")?.disabled
  `);
  await setValue(cdp, ".approval-detail textarea", `${project.key}真实项目QC：批准当前证据资料包与PICOS版本快照进入写作交接。`);
  await waitForCondition(cdp, `!Array.from(document.querySelectorAll(".button-row button")).find((item) => item.textContent.trim() === "批准")?.disabled`);
  await clickByText(cdp, "批准", ".button-row");
  await waitForCondition(cdp, `document.querySelector(".approval-message")?.textContent.includes("已批准")`);
  trace.push("approval_quality_gate_and_approve");

  await clickByText(cdp, "证据调研与方案设计");
  await waitForCondition(cdp, `document.body.textContent.includes(${JSON.stringify(project.packageLabel)})`);
  await clickByText(cdp, "PICOS方案设计", ".evidence-mode-tabs");
  await waitForCondition(cdp, `document.querySelector(".evidence-picos-handoff button:nth-of-type(2)") && !document.querySelector(".evidence-picos-handoff button:nth-of-type(2)").disabled`);
  await clickByText(cdp, "发起撰写交接", ".evidence-picos-handoff");
  await waitForCondition(cdp, `document.querySelector(".evidence-picos-message")?.textContent.includes("撰写交接已创建")`);
  trace.push("approved_snapshot_writing_handoff");
}

async function captureScreenshot(cdp, fileName) {
  const shot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  });
  const target = path.join(outputDir, fileName);
  await writeFile(target, Buffer.from(shot.data, "base64"));
  return target;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "evidence-interaction-qc-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  const report = { appUrl, viewport: { width: 1600, height: 1000 }, projects: {}, completed: false };

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
      width: 1600,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);

    for (const project of projects) {
      const trace = [];
      await selectProject(cdp, project);
      await exerciseCandidateTable(cdp, project, trace);
      await exerciseEvidenceReview(cdp, project, trace);
      await exercisePicosAndApproval(cdp, project, trace);
      const screenshot = await captureScreenshot(cdp, `${project.key}_handoff_complete.png`);
      report.projects[project.key] = { projectId: project.projectId, trace, screenshot };
      await clickByText(cdp, "项目总看板");
      await waitForCondition(cdp, `document.body.textContent.includes("统一工作收件箱")`);
    }
    report.completed = true;
    cdp.close();
  } finally {
    const reportPath = path.join(outputDir, "evidence_interaction_qc.json");
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    console.log(reportPath);
    chrome.kill("SIGTERM");
    await wait(400);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
