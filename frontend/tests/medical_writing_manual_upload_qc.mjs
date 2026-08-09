import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const appUrl = process.env.APP_URL || "http://127.0.0.1:5175/";
const apiUrl = process.env.API_URL || "http://127.0.0.1:8921";
const projectId = process.env.PROJECT_ID || "proj_mgk10_crswnp";
const nctId = process.env.NCT_ID || "NCT02898454";
const protocolPath = process.env.PROTOCOL_PATH;
const expectedSha256 = process.env.EXPECTED_SHA256 || "";
const chromePath = process.env.CHROME_PATH
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9405);
const outputDir = process.env.QC_OUTPUT_DIR
  || path.resolve("../records/visual_qc_20260715/medical_writing_manual_upload");
const viewports = [
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1600, height: 1000 },
  { width: 1920, height: 1080 },
];

if (!protocolPath) throw new Error("PROTOCOL_PATH is required");

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function getJson(url) {
  const response = await fetch(url);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${url}: ${JSON.stringify(payload)}`);
  return payload;
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
    close() { ws.close(); },
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

async function waitForCondition(cdp, expression, timeoutMs = 45000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(250);
  }
  throw new Error(`Timed out waiting for condition; last=${JSON.stringify(lastValue)}`);
}

async function clickButton(cdp, text, scope = "document") {
  const clicked = await evaluate(cdp, `(() => {
    const root = ${scope};
    const button = Array.from(root.querySelectorAll('button')).find(
      (item) => (item.textContent || '').trim() === ${JSON.stringify(text)},
    );
    if (!button || button.disabled) return false;
    button.scrollIntoView({ block: 'center', inline: 'nearest' });
    button.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Enabled button not found: ${text}`);
}

async function setValue(cdp, selector, value) {
  const changed = await evaluate(cdp, `(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    if (!input) return false;
    const prototype = input instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : input instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, 'value').set;
    setter.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error(`Field not found: ${selector}`);
}

async function setViewport(cdp, viewport) {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    ...viewport,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await wait(120);
}

async function capture(cdp, filename) {
  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
  });
  const target = path.join(outputDir, filename);
  await writeFile(target, Buffer.from(screenshot.data, "base64"));
  return target;
}

async function captureViewports(cdp, prefix, focusSelector) {
  const result = {};
  for (const viewport of viewports) {
    await setViewport(cdp, viewport);
    await evaluate(cdp, `(() => {
      const focus = document.querySelector(${JSON.stringify(focusSelector)});
      focus?.scrollIntoView({ block: 'start', inline: 'nearest', behavior: 'instant' });
      return true;
    })()`);
    const key = `${viewport.width}x${viewport.height}`;
    const metrics = await evaluate(cdp, `(() => {
      const body = document.body;
      const doc = document.documentElement;
      const panel = document.querySelector('.writing-reference-panel');
      const controls = Array.from(panel?.querySelectorAll('button, input, select, textarea') || []);
      return {
        viewport: { width: innerWidth, height: innerHeight },
        pageOverflowX: Math.max(body.scrollWidth, doc.scrollWidth) - innerWidth,
        panelOverflowX: panel ? panel.scrollWidth - panel.clientWidth : null,
        overflowNodes: Array.from(panel?.querySelectorAll('*') || [])
          .filter((node) => node.scrollWidth - node.clientWidth > 4)
          .slice(0, 30)
          .map((node) => ({
            tag: node.tagName,
            className: node.className?.baseVal || node.className || '',
            overflowX: node.scrollWidth - node.clientWidth,
            text: (node.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 100),
          })),
        clippedControls: controls.filter((node) => {
          const rect = node.getBoundingClientRect();
          return rect.width < 1 || rect.height < 1 || rect.right > innerWidth + 2 || rect.left < -2;
        }).map((node) => {
          const rect = node.getBoundingClientRect();
          return {
            label: (node.textContent || node.getAttribute('aria-label') || node.type || '').trim().slice(0, 80),
            left: Math.round(rect.left),
            right: Math.round(rect.right),
            width: Math.round(rect.width),
          };
        }),
      };
    })()`);
    result[key] = {
      metrics,
      screenshot: await capture(cdp, `${prefix}_${key}.png`),
    };
  }
  return result;
}

async function setFileInput(cdp, selector, filePath) {
  const documentNode = await cdp.send("DOM.getDocument", { depth: -1, pierce: true });
  const match = await cdp.send("DOM.querySelector", {
    nodeId: documentNode.root.nodeId,
    selector,
  });
  if (!match.nodeId) throw new Error(`File input not found: ${selector}`);
  await cdp.send("DOM.setFileInputFiles", {
    nodeId: match.nodeId,
    files: [filePath],
  });
}

async function run(cdp) {
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("DOM.enable");
  await setViewport(cdp, viewports[2]);
  await cdp.send("Page.navigate", { url: "about:blank" });
  await waitForCondition(cdp, `location.href === 'about:blank' && document.readyState === 'complete'`);
  await cdp.send("Page.navigate", { url: appUrl });
  await waitForCondition(
    cdp,
    `document.readyState === 'complete' && Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`,
  );
  await setValue(cdp, 'select[aria-label="选择临床研究项目"]', projectId);
  await waitForCondition(
    cdp,
    `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`,
  );
  await waitForCondition(
    cdp,
    `(() => {
      const meta = document.querySelector('.project-meta')?.textContent || '';
      return meta.includes('MG-K10-CRSwNP') && meta.includes('慢性鼻窦炎伴鼻息肉');
    })()`,
    90000,
  );
  await clickButton(cdp, "医学写作");
  await waitForCondition(cdp, `Boolean(document.querySelector('.writing-ai-core'))`, 90000);
  await clickButton(cdp, "证据", "document.querySelector('.writing-ai-core')");
  await waitForCondition(cdp, `Boolean(document.querySelector('.writing-reference-panel'))`);
  await waitForCondition(
    cdp,
    `Array.from(document.querySelectorAll('.writing-reference-list button'))
      .some((item) => (item.textContent || '').includes(${JSON.stringify(nctId)}))`,
    90000,
  );

  const selected = await evaluate(cdp, `(() => {
    const button = Array.from(document.querySelectorAll('.writing-reference-list button'))
      .find((item) => (item.textContent || '').includes(${JSON.stringify(nctId)}));
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!selected) throw new Error(`Candidate not found: ${nctId}`);
  await setValue(
    cdp,
    ".writing-reference-actions textarea",
    "同适应症、同为III期且研究人群与关键疗效安全性设计具有直接参照价值。",
  );
  await clickButton(cdp, "标记为直接竞品", "document.querySelector('.writing-reference-panel')");
  await waitForCondition(
    cdp,
    `document.querySelector('.writing-reference-message')?.textContent.includes('医学相关性已记录')`,
  );

  await clickButton(cdp, "文档与解析", "document.querySelector('.writing-reference-panel')");
  await waitForCondition(cdp, `Boolean(document.querySelector('.writing-reference-manual-upload'))`);
  await setValue(cdp, ".writing-reference-select select", nctId);
  await setFileInput(
    cdp,
    ".writing-reference-manual-upload input[type=file]",
    protocolPath,
  );
  await waitForCondition(
    cdp,
    `document.querySelector('.writing-reference-manual-upload-state')?.textContent.includes(${JSON.stringify(path.basename(protocolPath))})`,
  );
  await setValue(cdp, ".writing-reference-manual-upload select", "protocol");
  await setValue(cdp, '.writing-reference-manual-upload input[type="date"]', "2017-05-17");
  await clickButton(cdp, "导入并解析", "document.querySelector('.writing-reference-panel')");
  await waitForCondition(
    cdp,
    `document.querySelector('.writing-reference-message')?.textContent.includes('手动导入文件已登记并完成解析')`,
    120000,
  );
  await waitForCondition(
    cdp,
    `Array.from(document.querySelectorAll('.writing-reference-document-row.manual')).some((row) => (row.textContent || '').includes(${JSON.stringify(path.basename(protocolPath))}))`,
  );
  const documentViews = await captureViewports(
    cdp,
    "manual_document",
    ".writing-reference-manual-upload",
  );

  const opened = await evaluate(cdp, `(() => {
    const row = Array.from(document.querySelectorAll('.writing-reference-document-row.manual'))
      .find((item) => (item.textContent || '').includes(${JSON.stringify(path.basename(protocolPath))}));
    const button = Array.from(row?.querySelectorAll('button') || [])
      .find((item) => (item.textContent || '').includes('查看处理状态'));
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!opened) throw new Error("Manual document review button not found");
  await waitForCondition(cdp, `Boolean(document.querySelector('.writing-reference-validation'))`);

  const validationState = await evaluate(cdp, `(() => ({
    text: document.querySelector('.writing-reference-validation')?.textContent || '',
    warningCount: document.querySelectorAll('.writing-reference-override-check input[type=checkbox]').length,
    sourceLocator: document.querySelector('.writing-reference-source code')?.textContent || '',
  }))()`);
  if (!validationState.text.includes("文件内容核验")) {
    throw new Error(`Content validation is not visible: ${JSON.stringify(validationState)}`);
  }
  if (!validationState.sourceLocator.startsWith("upload:")) {
    throw new Error(`Manual source locator is not upload-bound: ${validationState.sourceLocator}`);
  }
  if (validationState.warningCount > 0) {
    await evaluate(cdp, `(() => {
      document.querySelectorAll('.writing-reference-override-check input[type=checkbox]')
        .forEach((input) => { if (!input.checked) input.click(); });
      return true;
    })()`);
    await setValue(
      cdp,
      ".writing-reference-override textarea",
      "医学经理已核对NCT号、CRSwNP适应症、Protocol角色及版本日期，确认该原文适用于当前竞品方案语料处理。",
    );
    await clickButton(cdp, "确认沿用当前文件", "document.querySelector('.writing-reference-panel')");
    await waitForCondition(
      cdp,
      `document.querySelector('.writing-reference-override-record')?.textContent.includes('已确认沿用')`,
    );
  }

  await setValue(
    cdp,
    ".writing-reference-structure-review textarea",
    "已逐项核对页码、章节标题、片段边界及ICH M11结构映射，当前解析可用于后续医学翻译审核。",
  );
  await clickButton(cdp, "确认结构完整", "document.querySelector('.writing-reference-panel')");
  await waitForCondition(
    cdp,
    `document.querySelector('.writing-reference-structure-review')?.textContent.includes('结构已确认')`,
  );
  const reviewViews = await captureViewports(
    cdp,
    "manual_review",
    ".writing-reference-validation",
  );
  await writeFile(
    path.join(outputDir, "qc_diagnostic.json"),
    JSON.stringify({ documentViews, reviewViews }, null, 2),
  );

  const workspace = await getJson(
    `${apiUrl}/api/projects/${projectId}/medical-writing/references/workspace`,
  );
  const artifact = [...(workspace.artifacts || [])].reverse().find(
    (item) => item.nct_id === nctId
      && item.filename === path.basename(protocolPath)
      && item.source_status === "user_uploaded",
  );
  if (!artifact) throw new Error("Manual artifact is missing from persisted workspace");
  if (expectedSha256 && artifact.content_sha256 !== expectedSha256) {
    throw new Error(`Artifact hash mismatch: ${artifact.content_sha256}`);
  }
  const validation = (workspace.document_validations || []).find(
    (item) => item.artifact_id === artifact.artifact_id,
  );
  const extractionReview = (workspace.extraction_reviews || []).find(
    (item) => item.artifact_id === artifact.artifact_id && item.decision === "approved",
  );
  if (!validation || !["confirmed", "user_overridden"].includes(validation.status)) {
    throw new Error(`Manual validation did not reach a usable state: ${validation?.status}`);
  }
  if (!extractionReview) throw new Error("Manual extraction medical approval is missing");

  for (const [label, states] of Object.entries({ documentViews, reviewViews })) {
    for (const [viewport, state] of Object.entries(states)) {
      if (state.metrics.pageOverflowX > 0) {
        throw new Error(`${label} has horizontal page overflow at ${viewport}`);
      }
      if (state.metrics.panelOverflowX > 4) {
        throw new Error(`${label} has ${state.metrics.panelOverflowX}px internal panel overflow at ${viewport}`);
      }
      if (state.metrics.clippedControls.length) {
        throw new Error(`${label} has clipped controls at ${viewport}: ${JSON.stringify(state.metrics.clippedControls)}`);
      }
    }
  }

  return {
    projectId,
    nctId,
    artifactId: artifact.artifact_id,
    contentSha256: artifact.content_sha256,
    validationStatus: validation.status,
    extractionRevision: extractionReview.extraction_revision,
    extractionDecision: extractionReview.decision,
    documentViews,
    reviewViews,
  };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-manual-upload-qc-"));
  const chrome = spawn(chromePath, [
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  let cdp;
  let primaryError;
  try {
    let pages;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      try {
        pages = await fetch(`http://127.0.0.1:${debugPort}/json/list`).then((response) => response.json());
        if (pages?.some((item) => item.type === "page" && item.webSocketDebuggerUrl)) break;
      } catch {}
      await wait(100);
    }
    const target = pages?.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
    if (!target) throw new Error("Chrome CDP page target did not start");
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    const report = await run(cdp);
    await writeFile(
      path.join(outputDir, "qc_report.json"),
      JSON.stringify(report, null, 2),
    );
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(800);
    try {
      await rm(userDataDir, { recursive: true, force: true, maxRetries: 3, retryDelay: 250 });
    } catch (cleanupError) {
      if (!primaryError) throw cleanupError;
      process.stderr.write(`Chrome profile cleanup deferred: ${cleanupError.message}\n`);
    }
  }
}

await main();
