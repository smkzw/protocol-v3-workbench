import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

if (process.env.QC_ISOLATED_RUNTIME !== "1") {
  throw new Error("PNH corpus ingest QC mutates runtime state and requires QC_ISOLATED_RUNTIME=1");
}

const appUrl = new URL(process.env.APP_URL || "http://127.0.0.1:5194/");
const projectId = process.env.PROJECT_ID || "proj_user_4bc29da4ac72";
const targetNctId = process.env.TARGET_NCT_ID || "NCT03896152";
const outputDir = path.resolve(process.env.QC_OUTPUT_DIR || "records/medical_writing_pnh_corpus_ingest_qc");
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || (9700 + (process.pid % 200)));
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(relativePath) {
  const response = await fetch(new URL(relativePath, appUrl));
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${relativePath}: ${JSON.stringify(payload)}`);
  return payload;
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

async function waitForCondition(cdp, expression, timeoutMs = 90000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(250);
  }
  throw new Error(`Timed out waiting for condition; last=${JSON.stringify(lastValue)}; expression=${expression}`);
}

async function waitForChrome() {
  const endpoint = `http://127.0.0.1:${debugPort}/json/list`;
  const started = Date.now();
  while (Date.now() - started < 30000) {
    try {
      const targets = await fetch(endpoint).then((response) => response.json());
      const page = targets.find((item) => item.type === "page");
      if (page?.webSocketDebuggerUrl) return page;
    } catch {}
    await wait(200);
  }
  throw new Error("Chrome DevTools endpoint did not become ready");
}

async function clickExact(cdp, text, rootSelector = "body") {
  const clicked = await evaluate(cdp, `(() => {
    const root = document.querySelector(${JSON.stringify(rootSelector)});
    const button = Array.from(root?.querySelectorAll('button') || []).find((item) => (item.textContent || '').trim() === ${JSON.stringify(text)});
    if (!button || button.disabled) return false;
    button.scrollIntoView({ block: 'center', inline: 'nearest' });
    button.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Enabled button not found: ${text}`);
}

async function setTextarea(cdp, rootSelector, value) {
  const changed = await evaluate(cdp, `(() => {
    const input = document.querySelector(${JSON.stringify(rootSelector)})?.querySelector('textarea');
    if (!input) return false;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error(`Textarea not found under ${rootSelector}`);
}

async function screenshot(cdp, filename) {
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const target = path.join(outputDir, filename);
  await writeFile(target, Buffer.from(shot.data, "base64"));
  return target;
}

async function openProject(cdp) {
  await cdp.send("Page.navigate", { url: appUrl.href });
  await waitForCondition(cdp, `document.readyState === 'complete' && Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`);
  await waitForCondition(cdp, `Array.from(document.querySelector('select[aria-label="选择临床研究项目"]').options).some((item) => item.value === ${JSON.stringify(projectId)})`);
  await evaluate(cdp, `(() => {
    const select = document.querySelector('select[aria-label="选择临床研究项目"]');
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(select, ${JSON.stringify(projectId)});
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
  await clickExact(cdp, "医学写作");
  await waitForCondition(cdp, `document.querySelector('.authoring-stage-strip button.active')?.textContent.includes('语料准备')`);
  await waitForCondition(cdp, `document.querySelectorAll('.writing-reference-list > button').length === 50`);
}

async function filterAndSelectCandidate(cdp) {
  await evaluate(cdp, `(() => {
    const input = document.querySelector('.writing-reference-candidate-filters input');
    if (!input) return false;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(targetNctId)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  })()`);
  await waitForCondition(cdp, `document.querySelectorAll('.writing-reference-list > button').length === 1 && document.querySelector('.writing-reference-list > button')?.textContent.includes(${JSON.stringify(targetNctId)})`);
  await evaluate(cdp, `document.querySelector('.writing-reference-list > button').click()`);
}

async function run(cdp, report) {
  await openProject(cdp);
  await filterAndSelectCandidate(cdp);
  const alreadyDirect = await evaluate(cdp, `document.querySelector('.writing-reference-list > button.active')?.textContent.includes('直接竞品')`);
  if (!alreadyDirect) {
    await setTextarea(cdp, ".writing-reference-actions", "同为PNH成人补体抑制剂研究，包含随机开放标签剂量探索、Hb/LDH疗效、PK/PD及安全性评价，可直接支持CMS-D017方案结构与关键设计比较。");
    await clickExact(cdp, "标记为直接竞品", ".writing-reference-actions");
    await waitForCondition(cdp, `document.querySelector('.writing-reference-message')?.textContent.includes('医学相关性已记录')`);
  }
  const journeyBeforeTriage = await request(`/api/projects/${projectId}/medical-writing/authoring-journey`);
  if (journeyBeforeTriage.corpus_triage?.status !== "finalized") {
    await setTextarea(cdp, ".writing-reference-triage-finalize", "优先锁定同适应症、同分期、同为补体旁路抑制且具备公开Protocol/SAP的iptacopan研究；其余候选保留在快照中供后续扩展分诊。");
    await clickExact(cdp, "锁定竞品篮子", ".writing-reference-triage-finalize");
    await waitForCondition(cdp, `document.querySelector('.writing-reference-message')?.textContent.includes('已锁定1项直接竞品/间接参照')`);
  }
  report.triageScreenshot = await screenshot(cdp, "01_pnh_direct_competitor_triage.png");

  await clickExact(cdp, "文档与解析", ".writing-reference-views");
  await waitForCondition(cdp, `Array.from(document.querySelectorAll('.writing-reference-document-row')).some((row) => row.textContent.includes('Study Protocol'))`);
  const ingestAvailable = await evaluate(cdp, `(() => {
    const row = Array.from(document.querySelectorAll('.writing-reference-document-row')).find((item) => item.textContent.includes('Study Protocol'));
    return Array.from(row?.querySelectorAll('button') || []).some((button) => button.textContent.includes('下载并解析') && !button.disabled);
  })()`);
  if (ingestAvailable) {
    const clicked = await evaluate(cdp, `(() => {
      const row = Array.from(document.querySelectorAll('.writing-reference-document-row')).find((item) => item.textContent.includes('Study Protocol'));
      const button = Array.from(row?.querySelectorAll('button') || []).find((item) => item.textContent.includes('下载并解析') && !item.disabled);
      button?.click();
      return Boolean(button);
    })()`);
    if (!clicked) throw new Error("Protocol ingest action was not available");
    await waitForCondition(cdp, `document.querySelector('.writing-reference-message')?.textContent.includes('公开文档已下载并完成结构化解析')`, 360000);
  }
  await waitForCondition(cdp, `(() => {
    const row = Array.from(document.querySelectorAll('.writing-reference-document-row')).find((item) => item.textContent.includes('Study Protocol'));
    return Boolean(row && row.textContent.includes('已解析') && row.textContent.includes('内容匹配'));
  })()`, 90000);
  report.parsedScreenshot = await screenshot(cdp, "02_pnh_protocol_parsed.png");

  const opened = await evaluate(cdp, `(() => {
    const row = Array.from(document.querySelectorAll('.writing-reference-document-row')).find((item) => item.textContent.includes('Study Protocol'));
    const button = Array.from(row?.querySelectorAll('button') || []).find((item) => item.textContent.includes('查看处理状态'));
    button?.click();
    return Boolean(button);
  })()`);
  if (!opened) throw new Error("Parsed Protocol processing status could not be opened");
  await waitForCondition(cdp, `document.querySelector('.writing-reference-validation')?.textContent.includes('内容匹配') && Boolean(document.querySelector('.writing-reference-structure-review'))`, 120000);
  const structureAlreadyApproved = await evaluate(cdp, `document.querySelector('.writing-reference-structure-review.approved') !== null`);
  if (!structureAlreadyApproved) {
    await setTextarea(cdp, ".writing-reference-structure-review", "已核对研究标识、适应症、文件角色、章节标题、页码片段边界及ICH M11映射；当前抽取结构可用于关键章节监管中文翻译准备。");
    await clickExact(cdp, "确认结构完整", ".writing-reference-structure-review");
    await waitForCondition(cdp, `document.querySelector('.writing-reference-message')?.textContent.includes('抽取章节与M11结构映射已完成医学确认')`);
  }
  report.structureScreenshot = await screenshot(cdp, "03_pnh_protocol_structure_approved.png");

  const journey = await request(`/api/projects/${projectId}/medical-writing/authoring-journey`);
  const snapshotId = journey.search_plan.latest_snapshot_id;
  const workspace = await request(`/api/projects/${projectId}/medical-writing/references/workspace?snapshot_id=${encodeURIComponent(snapshotId)}`);
  const protocolArtifact = workspace.artifacts.find((item) => item.nct_id === targetNctId && item.filename === "Prot_000.pdf");
  const extractionReview = workspace.extraction_reviews.find((item) => item.artifact_id === protocolArtifact?.artifact_id && item.decision === "approved");
  if (!protocolArtifact || !protocolArtifact.source_current || !extractionReview) {
    throw new Error("Protocol artifact or approved extraction review was not persisted");
  }
  report.artifact = protocolArtifact;
  report.extractionReview = extractionReview;
  report.anchorCounts = workspace.artifact_span_counts?.[protocolArtifact.artifact_id] || {};
  report.journey = { revision: journey.revision, corpusGate: journey.corpus_gate, corpusTriage: journey.corpus_triage };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-pnh-corpus-ingest-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  const report = { status: "running", projectId, targetNctId, startedAt: new Date().toISOString(), httpFailures: [], pageErrors: [] };
  let cdp;
  try {
    const target = await waitForChrome();
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");
    cdp.on("Runtime.exceptionThrown", (event) => report.pageErrors.push(event.exceptionDetails?.exception?.description || event.exceptionDetails?.text || "runtime exception"));
    cdp.on("Network.responseReceived", (event) => {
      const status = event.response?.status || 0;
      if (status >= 400) report.httpFailures.push({ status, url: event.response.url || "", type: event.type || "" });
    });
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await run(cdp, report);
    const expectedEmptyPaths = new Set([
      `/api/projects/${projectId}/medical-writing/manifest`,
      `/api/projects/${projectId}/medical-writing/document-session`,
    ]);
    report.unexpectedHttpFailures = report.httpFailures.filter((failure) => {
      let pathname = "";
      try { pathname = new URL(failure.url).pathname; } catch {}
      return !(failure.status === 404 && expectedEmptyPaths.has(pathname));
    });
    if (report.unexpectedHttpFailures.length) throw new Error(`Unexpected HTTP failures: ${JSON.stringify(report.unexpectedHttpFailures)}`);
    if (report.pageErrors.length) throw new Error(`Page errors: ${JSON.stringify(report.pageErrors)}`);
    report.status = "passed";
    report.completedAt = new Date().toISOString();
  } catch (error) {
    report.status = "failed";
    report.error = error.stack || error.message;
    report.failedAt = new Date().toISOString();
    if (cdp) report.failureScreenshot = await screenshot(cdp, "99_failure.png").catch(() => "");
  } finally {
    await writeFile(path.join(outputDir, "qc_report.json"), JSON.stringify(report, null, 2));
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(500);
    await rm(userDataDir, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
  }
  process.stdout.write(`${JSON.stringify({ status: report.status, report: path.join(outputDir, "qc_report.json") }, null, 2)}\n`);
  if (report.status !== "passed") throw new Error(report.error);
}

await main();
