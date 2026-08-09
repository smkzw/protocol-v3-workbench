import { spawn } from "node:child_process";
import {
  appendFile,
  copyFile,
  mkdir,
  mkdtemp,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const requiredEnvironment = ["BASE_URL", "PROJECT_ID", "SYNOPSIS_FILE", "OUTPUT_DIR"];
const missingEnvironment = requiredEnvironment.filter((name) => !process.env[name]?.trim());
if (missingEnvironment.length) {
  throw new Error(`Missing required environment variables: ${missingEnvironment.join(", ")}`);
}

const baseUrl = new URL(process.env.BASE_URL.endsWith("/") ? process.env.BASE_URL : `${process.env.BASE_URL}/`);
const projectId = process.env.PROJECT_ID.trim();
const synopsisFile = path.resolve(process.env.SYNOPSIS_FILE);
const outputDir = path.resolve(process.env.OUTPUT_DIR);
const chromePath = process.env.CHROME_PATH
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || (9300 + (process.pid % 500)));
const aiTimeoutMs = Number(process.env.QC_AI_TIMEOUT_MS || 600000);
const viewports = [
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
  { width: 1600, height: 1000 },
  { width: 1920, height: 1080 },
];
const journeyPath = `/api/projects/${encodeURIComponent(projectId)}/medical-writing/authoring-journey`;
const documentPath = `/api/projects/${encodeURIComponent(projectId)}/medical-writing/greenfield-document`;
const journeyUrl = new URL(journeyPath, baseUrl);
const documentUrl = new URL(documentPath, baseUrl);
const expectedOptionalEmptyPaths = new Set([
  documentPath,
  `/api/projects/${encodeURIComponent(projectId)}/medical-writing/document-session`,
  `/api/projects/${encodeURIComponent(projectId)}/medical-writing/manifest`,
  `/api/projects/${encodeURIComponent(projectId)}/medical-writing/tfl-citation-candidates`,
]);
const extension = path.extname(synopsisFile).toLowerCase();

if (!new Set([".pdf", ".docx"]).has(extension)) {
  throw new Error(`SYNOPSIS_FILE must be a real PDF or DOCX file, received: ${synopsisFile}`);
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const timestamp = () => new Date().toISOString();
const safeName = (value) => value.replace(/[^a-zA-Z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");

function createRecorder() {
  const files = {
    actions: path.join(outputDir, "actions.jsonl"),
    states: path.join(outputDir, "states.jsonl"),
    network: path.join(outputDir, "network.jsonl"),
    console: path.join(outputDir, "console.jsonl"),
    errors: path.join(outputDir, "errors.jsonl"),
  };
  let writeChain = Promise.resolve();
  const initialize = async () => {
    await mkdir(outputDir, { recursive: true });
    await Promise.all(Object.values(files).map((file) => writeFile(file, "")));
  };
  const record = (channel, payload) => {
    const line = `${JSON.stringify({ at: timestamp(), ...payload })}\n`;
    writeChain = writeChain.then(() => appendFile(files[channel], line));
    return writeChain;
  };
  return { files, initialize, record, flush: () => writeChain };
}

function createCdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  const listeners = new Map();
  const eventTasks = new Set();
  const eventErrors = [];

  const track = (task) => {
    const observed = task.catch((error) => { eventErrors.push(error); });
    eventTasks.add(observed);
    observed.finally(() => eventTasks.delete(observed));
  };

  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const callback = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) callback.reject(new Error(message.error.message));
      else callback.resolve(message.result || {});
      return;
    }
    for (const listener of listeners.get(message.method) || []) {
      const task = Promise.resolve().then(() => listener(message.params || {}));
      track(task);
    }
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
      if (!listeners.has(method)) listeners.set(method, []);
      listeners.get(method).push(listener);
    },
    async drainEvents() {
      while (eventTasks.size) await Promise.allSettled([...eventTasks]);
      if (eventErrors.length) {
        throw new Error(`CDP event recording failed: ${eventErrors.map((error) => error.message).join("; ")}`);
      }
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

async function waitForChrome(port) {
  let lastError;
  for (let attempt = 0; attempt < 150; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      const pages = await response.json();
      const target = pages.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
      if (target) return target;
    } catch (error) {
      lastError = error;
    }
    await wait(100);
  }
  throw lastError || new Error("Chrome CDP page target did not start");
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
    captureBeyondViewport: false,
  });
  const target = path.join(outputDir, filename);
  await writeFile(target, Buffer.from(screenshot.data, "base64"));
  return target;
}

async function collectState(cdp) {
  return evaluate(cdp, `(() => {
    const body = document.body;
    const doc = document.documentElement;
    const shell = document.querySelector('.authoring-journey-shell');
    const panel = document.querySelector('.synopsis-import-stage') || shell;
    const journeyBody = document.querySelector('.authoring-journey-body');
    const footer = document.querySelector('.authoring-journey-footer');
    const footerRect = footer?.getBoundingClientRect();
    const allControls = Array.from(shell?.querySelectorAll('button, input, select, textarea') || []);
    const visibleControls = allControls.filter((node) => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden'
        && rect.width > 0 && rect.height > 0
        && rect.bottom > 0 && rect.top < innerHeight;
    });
    const clippedControls = visibleControls.filter((node) => {
      const rect = node.getBoundingClientRect();
      return rect.left < -2 || rect.right > innerWidth + 2 || rect.width < 1 || rect.height < 1;
    }).map((node) => {
      const rect = node.getBoundingClientRect();
      return {
        tag: node.tagName,
        type: node.type || '',
        label: (node.textContent || node.getAttribute('aria-label') || node.name || '').trim().replace(/\s+/g, ' ').slice(0, 100),
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
      };
    });
    const footerOverlapControls = footerRect ? visibleControls.filter((node) => {
      if (footer.contains(node)) return false;
      const rect = node.getBoundingClientRect();
      return rect.left < footerRect.right && rect.right > footerRect.left
        && rect.top < footerRect.bottom && rect.bottom > footerRect.top;
    }).map((node) => (node.textContent || node.getAttribute('aria-label') || node.type || '').trim().replace(/\s+/g, ' ').slice(0, 80)) : [];
    const scrollableRegions = Array.from(shell?.querySelectorAll('*') || []).filter((node) => {
      const style = getComputedStyle(node);
      return ['auto', 'scroll'].includes(style.overflowY) && node.scrollHeight - node.clientHeight > 2;
    }).slice(0, 30).map((node) => ({
      tag: node.tagName,
      className: node.className?.baseVal || node.className || '',
      overflowY: node.scrollHeight - node.clientHeight,
      scrollTop: Math.round(node.scrollTop),
    }));
    const buttons = Array.from(shell?.querySelectorAll('button') || []).filter((node) => {
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    }).map((node) => ({
      text: (node.textContent || '').trim().replace(/\s+/g, ' '),
      disabled: node.disabled,
      className: node.className || '',
      ariaSelected: node.getAttribute('aria-selected'),
    }));
    const validations = Array.from(document.querySelectorAll('.synopsis-validation')).map((node) => ({
      text: (node.textContent || '').trim(),
      className: node.className,
    }));
    const pageOverflowX = Math.max(body.scrollWidth, doc.scrollWidth) - innerWidth;
    const panelOverflowX = panel ? panel.scrollWidth - panel.clientWidth : null;
    const documentOverflowY = Math.max(body.scrollHeight, doc.scrollHeight) - innerHeight;
    const journeyBodyOverflowY = journeyBody ? journeyBody.scrollHeight - journeyBody.clientHeight : null;
    return {
      url: location.href,
      title: document.title,
      viewport: { width: innerWidth, height: innerHeight, devicePixelRatio },
      pageOverflowX,
      panelOverflowX,
      documentOverflowY,
      journeyBodyOverflowY,
      nestedVerticalScroll: documentOverflowY > 2 && journeyBodyOverflowY > 2,
      shell: shell ? { width: shell.clientWidth, scrollWidth: shell.scrollWidth, height: shell.clientHeight, scrollHeight: shell.scrollHeight } : null,
      panel: panel ? { width: panel.clientWidth, scrollWidth: panel.scrollWidth, height: panel.clientHeight, scrollHeight: panel.scrollHeight } : null,
      footer: footerRect ? {
        top: Math.round(footerRect.top), bottom: Math.round(footerRect.bottom),
        left: Math.round(footerRect.left), right: Math.round(footerRect.right),
        width: Math.round(footerRect.width), height: Math.round(footerRect.height),
        outsideViewport: footerRect.top < -1 || footerRect.bottom > innerHeight + 1 || footerRect.left < -1 || footerRect.right > innerWidth + 1,
      } : null,
      footerOverlapControls,
      clippedControls,
      scrollableRegions,
      buttons,
      validations,
      entryModeOptions: Array.from(document.querySelectorAll('.authoring-entry-mode-options button strong')).map((node) => node.textContent.trim()),
      importStatus: document.querySelector('.synopsis-import-status')?.textContent?.trim() || '',
      sourceFilename: document.querySelector('.synopsis-source-review dd[title]')?.getAttribute('title') || '',
      warningCount: document.querySelectorAll('.synopsis-validation-review input[type=checkbox]').length,
      warningChecked: document.querySelectorAll('.synopsis-validation-review input[type=checkbox]:checked').length,
      confirmDisabled: document.querySelector('.synopsis-import-footer button')?.disabled ?? null,
      framingVisible: Boolean(document.querySelector('.authoring-stage-strip') && document.querySelector('.authoring-field-section')),
      sourceLabel: document.querySelector('.authoring-journey-state small')?.textContent?.trim() || '',
      bodyTextSample: (body.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 1200),
    };
  })()`);
}

function assertLayout(label, states, { requireFooter = false, requireFooterVisible = false } = {}) {
  for (const [viewport, entry] of Object.entries(states)) {
    const state = entry.metrics;
    if (state.pageOverflowX > 2) {
      throw new Error(`${label} has ${state.pageOverflowX}px page horizontal overflow at ${viewport}`);
    }
    if (state.panelOverflowX !== null && state.panelOverflowX > 2) {
      throw new Error(`${label} has ${state.panelOverflowX}px panel horizontal overflow at ${viewport}`);
    }
    if (state.clippedControls.length) {
      throw new Error(`${label} has clipped visible controls at ${viewport}: ${JSON.stringify(state.clippedControls)}`);
    }
    if (state.nestedVerticalScroll) {
      throw new Error(`${label} has page and journey-body nested vertical scrolling at ${viewport}`);
    }
    if (requireFooter && !state.footer) {
      throw new Error(`${label} is missing its action footer at ${viewport}`);
    }
    if (requireFooterVisible && state.footer?.outsideViewport) {
      throw new Error(`${label} footer is outside the viewport at ${viewport}: ${JSON.stringify(state.footer)}`);
    }
    if (state.footerOverlapControls.length) {
      throw new Error(`${label} footer overlaps visible controls at ${viewport}: ${JSON.stringify(state.footerOverlapControls)}`);
    }
  }
}

async function captureViewports(cdp, recorder, label, { scroll = "top", requireFooter = false } = {}) {
  const states = {};
  for (const viewport of viewports) {
    await setViewport(cdp, viewport);
    await evaluate(cdp, `(() => {
      window.scrollTo({ top: ${scroll === "bottom" ? "document.documentElement.scrollHeight" : "0"}, left: 0, behavior: 'instant' });
      const journeyBody = document.querySelector('.authoring-journey-body');
      if (journeyBody) journeyBody.scrollTo({ top: ${scroll === "bottom" ? "journeyBody.scrollHeight" : "0"}, left: 0, behavior: 'instant' });
      return true;
    })()`);
    await wait(100);
    const viewportLabel = `${viewport.width}x${viewport.height}`;
    const metrics = await collectState(cdp);
    const screenshot = await capture(cdp, `${safeName(label)}_${scroll}_${viewportLabel}.png`);
    states[viewportLabel] = { metrics, screenshot };
    await recorder.record("states", { label, scroll, viewport: viewportLabel, screenshot, metrics });
  }
  await setViewport(cdp, viewports[2]);
  assertLayout(label, states, { requireFooter, requireFooterVisible: requireFooter && scroll === "bottom" });
  return states;
}

async function clickButton(cdp, recorder, text, { scope = "document", contains = false } = {}) {
  const result = await evaluate(cdp, `(() => {
    const root = ${scope};
    if (!root) return { found: false };
    const button = Array.from(root.querySelectorAll('button')).find((item) => {
      const label = (item.textContent || '').trim().replace(/\s+/g, ' ');
      return ${contains ? "label.includes" : "label ==="}(${JSON.stringify(text)});
    });
    if (!button) return { found: false };
    const result = {
      found: true,
      disabled: button.disabled,
      text: (button.textContent || '').trim().replace(/\s+/g, ' '),
      className: button.className || '',
      type: button.type || '',
    };
    if (!button.disabled) {
      button.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
      button.click();
    }
    return result;
  })()`);
  await recorder.record("actions", { kind: "button", requestedText: text, result });
  if (!result.found || result.disabled) {
    throw new Error(`Enabled button not found: ${text}; result=${JSON.stringify(result)}`);
  }
  return result;
}

async function setValue(cdp, recorder, selector, value, actionLabel) {
  const changed = await evaluate(cdp, `(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    if (!input || input.disabled) return false;
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
  await recorder.record("actions", { kind: "field", label: actionLabel, selector, changed, valueLength: String(value).length });
  if (!changed) throw new Error(`Field not found or disabled: ${selector}`);
}

async function setFileInput(cdp, recorder, filePath, label) {
  const selector = ".synopsis-file-picker input[type=file]";
  const documentNode = await cdp.send("DOM.getDocument", { depth: -1, pierce: true });
  const match = await cdp.send("DOM.querySelector", { nodeId: documentNode.root.nodeId, selector });
  if (!match.nodeId) throw new Error(`File input not found: ${selector}`);
  await cdp.send("DOM.setFileInputFiles", { nodeId: match.nodeId, files: [filePath] });
  await recorder.record("actions", { kind: "file", label, selector, filePath, filename: path.basename(filePath) });
}

async function selectProject(cdp, recorder) {
  await setValue(cdp, recorder, 'select[aria-label="选择临床研究项目"]', projectId, "选择项目");
  await waitForCondition(
    cdp,
    `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`,
  );
}

async function navigateToWorkbench(cdp, recorder) {
  await recorder.record("actions", { kind: "navigation", url: baseUrl.href });
  await cdp.send("Page.navigate", { url: baseUrl.href });
  await waitForCondition(
    cdp,
    `document.readyState === 'complete' && Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`,
    90000,
  );
  await selectProject(cdp, recorder);
  await clickButton(cdp, recorder, "项目总看板");
  await waitForCondition(cdp, `!Boolean(document.querySelector('.medical-writing-page'))`, 45000);
  await wait(250);
  await clickButton(cdp, recorder, "医学写作");
  await waitForCondition(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`, 90000);
}

async function emulateLatency(cdp, latency) {
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    latency,
    downloadThroughput: -1,
    uploadThroughput: -1,
    connectionType: "wifi",
  });
}

async function parseSelectedSynopsis(cdp, recorder, report, label, expectedFilename, buttonText) {
  await emulateLatency(cdp, 5000);
  try {
    await clickButton(cdp, recorder, buttonText);
    await waitForCondition(cdp, `Array.from(document.querySelectorAll('.synopsis-upload-bar button')).some((button) => (button.textContent || '').includes('解析中') && button.disabled)`, 10000);
    report.states[`${label}Busy`] = await captureViewports(cdp, recorder, `${label}_parsing_busy`, { requireFooter: label !== "fileA" });
  } finally {
    await emulateLatency(cdp, 0);
  }
  await waitForCondition(cdp, `(() => {
    const source = document.querySelector('.synopsis-source-review dd[title]');
    const button = document.querySelector('.synopsis-upload-bar button');
    const error = document.querySelector('.authoring-journey-message.danger');
    return Boolean(error) || (
      source?.getAttribute('title') === ${JSON.stringify(expectedFilename)}
      && !(button?.textContent || '').includes('解析中')
    );
  })()`, aiTimeoutMs);
  const importError = await evaluate(cdp, `document.querySelector('.authoring-journey-message.danger')?.textContent.trim() || ''`);
  if (importError) throw new Error(`${label} failed: ${importError}`);
  await waitForCondition(cdp, `document.querySelector('.synopsis-import-status')?.textContent.trim() === '待医学确认'`, 30000);
  report.states[`${label}ParsedTop`] = await captureViewports(cdp, recorder, `${label}_parsed`, { requireFooter: true });
  report.states[`${label}ParsedBottom`] = await captureViewports(cdp, recorder, `${label}_parsed`, { scroll: "bottom", requireFooter: true });
}

async function prepareValidationDecision(cdp, recorder, report, label) {
  const initial = await collectState(cdp);
  const warningLabels = await evaluate(cdp, `Array.from(document.querySelectorAll('.synopsis-validation-review label > span > strong')).map((node) => node.textContent.trim())`);
  if (warningLabels.length) {
    if (initial.confirmDisabled !== true) {
      throw new Error(`${label} confirm must remain disabled before warning acknowledgement`);
    }
    const toggled = await evaluate(cdp, `(() => {
      const labels = [];
      document.querySelectorAll('.synopsis-validation-review input[type=checkbox]').forEach((input) => {
        if (!input.checked) input.click();
        labels.push((input.closest('label')?.textContent || '').trim().replace(/\s+/g, ' '));
      });
      return labels;
    })()`);
    for (const warning of toggled) {
      await recorder.record("actions", { kind: "checkbox", label: "确认内容提示", warning });
    }
    await setValue(
      cdp,
      recorder,
      ".synopsis-override-reason textarea",
      "医学经理已核对文件角色、项目适应症及方案摘要原文，确认当前文件可用于本项目研究设计补全。",
      "填写确认沿用理由",
    );
  } else {
    const nonMatched = initial.validations.filter((item) => !item.className.includes("matched"));
    if (nonMatched.length) {
      throw new Error(`${label} has non-matched validation without an override path: ${JSON.stringify(nonMatched)}`);
    }
  }
  await waitForCondition(cdp, `document.querySelector('.synopsis-import-footer button')?.disabled === false`, 30000);
  const decided = await collectState(cdp);
  report.validation[label] = {
    branch: warningLabels.length ? "warning_override" : "matched",
    warnings: warningLabels,
    validations: decided.validations,
    confirmEnabled: decided.confirmDisabled === false,
  };
  report.states[`${label}Decision`] = await captureViewports(cdp, recorder, `${label}_validation_decision`, { scroll: "bottom", requireFooter: true });
  return decided;
}

function installDiagnostics(cdp, recorder, diagnostics) {
  const requests = new Map();
  const responses = new Map();

  cdp.on("Network.requestWillBeSent", async (event) => {
    const request = {
      requestId: event.requestId,
      method: event.request.method,
      url: event.request.url,
      type: event.type || "",
      documentURL: event.documentURL || "",
      initiatedAt: timestamp(),
    };
    requests.set(event.requestId, request);
    await recorder.record("network", { event: "request", ...request });
  });

  cdp.on("Network.responseReceived", async (event) => {
    const request = requests.get(event.requestId) || {};
    const response = {
      requestId: event.requestId,
      method: request.method || "",
      url: event.response.url,
      status: event.response.status,
      statusText: event.response.statusText,
      mimeType: event.response.mimeType,
      protocol: event.response.protocol,
      fromDiskCache: event.response.fromDiskCache,
      fromServiceWorker: event.response.fromServiceWorker,
      type: event.type || request.type || "",
      receivedAt: timestamp(),
    };
    responses.set(event.requestId, response);
    diagnostics.networkResponses.push(response);
    await recorder.record("network", { event: "response", ...response });
  });

  cdp.on("Network.loadingFinished", async (event) => {
    const response = responses.get(event.requestId);
    if (!response) return;
    const isApi = (() => {
      try { return new URL(response.url).pathname.startsWith("/api/"); } catch { return false; }
    })();
    if (!isApi) {
      await recorder.record("network", { event: "complete", requestId: event.requestId, url: response.url, encodedDataLength: event.encodedDataLength });
      return;
    }
    try {
      const payload = await cdp.send("Network.getResponseBody", { requestId: event.requestId });
      const rawBody = payload.base64Encoded
        ? Buffer.from(payload.body, "base64").toString("utf8")
        : payload.body;
      const bodyLimit = 2 * 1024 * 1024;
      const bodyBuffer = Buffer.from(rawBody);
      await recorder.record("network", {
        event: "api_body",
        requestId: event.requestId,
        method: response.method,
        url: response.url,
        status: response.status,
        body: bodyBuffer.subarray(0, bodyLimit).toString("utf8"),
        bodyBytes: bodyBuffer.byteLength,
        bodyTruncated: bodyBuffer.byteLength > bodyLimit,
      });
    } catch (error) {
      await recorder.record("network", { event: "api_body_unavailable", requestId: event.requestId, url: response.url, error: error.message });
    }
  });

  cdp.on("Network.loadingFailed", async (event) => {
    const request = requests.get(event.requestId) || {};
    const failure = { kind: "network", requestId: event.requestId, method: request.method || "", url: request.url || "", errorText: event.errorText, canceled: event.canceled };
    await recorder.record("errors", failure);
    if (!event.canceled && event.errorText !== "net::ERR_ABORTED") diagnostics.pageErrors.push(failure);
  });

  cdp.on("Runtime.consoleAPICalled", async (event) => {
    const entry = {
      kind: "console",
      level: event.type,
      text: event.args.map((arg) => arg.value ?? arg.description ?? arg.unserializableValue ?? "").join(" "),
      stackTrace: event.stackTrace || null,
    };
    diagnostics.consoleEntries.push(entry);
    await recorder.record("console", entry);
    if (["error", "assert"].includes(event.type)) {
      diagnostics.pageErrors.push(entry);
      await recorder.record("errors", entry);
    }
  });

  cdp.on("Runtime.exceptionThrown", async (event) => {
    const entry = {
      kind: "page_exception",
      text: event.exceptionDetails?.exception?.description || event.exceptionDetails?.text || "Runtime exception",
      exceptionDetails: event.exceptionDetails,
    };
    diagnostics.pageErrors.push(entry);
    await recorder.record("errors", entry);
  });

  cdp.on("Log.entryAdded", async (event) => {
    const entry = { kind: "browser_log", level: event.entry.level, source: event.entry.source, text: event.entry.text, url: event.entry.url || "" };
    await recorder.record("console", entry);
    let pathname = "";
    try { pathname = new URL(entry.url).pathname; } catch {}
    const expectedEmptyResourceLog = pathname === journeyPath || expectedOptionalEmptyPaths.has(pathname);
    if (event.entry.level === "error" && !expectedEmptyResourceLog) {
      diagnostics.pageErrors.push(entry);
      await recorder.record("errors", entry);
    }
  });
}

function assertNetworkAndPageErrors(diagnostics) {
  let journeyCreated = false;
  const unexpectedApiFailures = [];
  for (const response of diagnostics.networkResponses) {
    let pathname = "";
    try { pathname = new URL(response.url).pathname; } catch {}
    if (response.method === "POST" && pathname === journeyPath && response.status < 400) journeyCreated = true;
    if (response.status < 400 || !pathname.startsWith("/api/")) continue;
    const expectedEmptyJourney = response.method === "GET" && pathname === journeyPath && response.status === 404 && !journeyCreated;
    const expectedOptionalEmptyResource = response.method === "GET"
      && expectedOptionalEmptyPaths.has(pathname)
      && response.status === 404;
    if (!expectedEmptyJourney && !expectedOptionalEmptyResource) unexpectedApiFailures.push(response);
  }
  if (unexpectedApiFailures.length) {
    throw new Error(`Unexpected API failures: ${JSON.stringify(unexpectedApiFailures)}`);
  }
  if (diagnostics.pageErrors.length) {
    throw new Error(`Console, page, or network errors were recorded: ${JSON.stringify(diagnostics.pageErrors)}`);
  }
}

async function assertDisposableEmptyProject() {
  const [journeyResponse, documentResponse] = await Promise.all([fetch(journeyUrl), fetch(documentUrl)]);
  if (![200, 404].includes(journeyResponse.status)) {
    throw new Error(`PROJECT_ID authoring journey preflight returned HTTP ${journeyResponse.status}`);
  }
  if (journeyResponse.status === 200) {
    const journey = await journeyResponse.json().catch(() => ({}));
    const importState = journey.synopsis_import || {};
    const pinnedEmptyImport = journey.entry_mode === "synopsis_import"
      && importState.status === "not_started"
      && !importState.source;
    if (!pinnedEmptyImport) {
      throw new Error(
        `PROJECT_ID must target an empty synopsis-import project; received ${JSON.stringify({
          entryMode: journey.entry_mode,
          importStatus: importState.status,
          hasSource: Boolean(importState.source),
        })}`,
      );
    }
  }
  if (documentResponse.status !== 404) {
    throw new Error(`PROJECT_ID must not already have a medical-writing document; document returned HTTP ${documentResponse.status}`);
  }
}

async function run(cdp, recorder, report, replacementFile) {
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("DOM.enable");
  await cdp.send("Network.enable", { maxTotalBufferSize: 20 * 1024 * 1024, maxResourceBufferSize: 5 * 1024 * 1024 });
  await cdp.send("Log.enable");
  await setViewport(cdp, viewports[2]);
  await navigateToWorkbench(cdp, recorder);

  const pinnedImportEntry = await evaluate(cdp, `document.querySelector('.synopsis-import-status')?.textContent.trim() === '待导入'`);
  if (pinnedImportEntry) {
    report.entryStartMode = "new_project_preselected_synopsis_import";
    report.states.preselectedImportEntry = await captureViewports(
      cdp,
      recorder,
      "01_preselected_import_entry",
    );
  } else {
    await waitForCondition(cdp, `(() => {
      const options = Array.from(document.querySelectorAll('.authoring-entry-mode-options button strong')).map((node) => node.textContent.trim());
      return options.includes('导入方案摘要') && options.includes('从零开始');
    })()`);
    report.entryStartMode = "empty_project_dual_entry";
    report.states.emptyDualEntry = await captureViewports(cdp, recorder, "01_empty_project_dual_entry");
    await clickButton(cdp, recorder, "导入方案摘要", { contains: true });
  }
  await waitForCondition(cdp, `document.querySelector('.synopsis-import-status')?.textContent.trim() === '待导入'`, 45000);
  report.states.importEntry = await captureViewports(cdp, recorder, "02_import_entry");

  await setFileInput(cdp, recorder, synopsisFile, "选择方案摘要文件A");
  await waitForCondition(cdp, `document.querySelector('.synopsis-file-picker strong')?.textContent.trim() === ${JSON.stringify(path.basename(synopsisFile))}`);
  report.states.fileASelected = await captureViewports(cdp, recorder, "03_file_A_selected");
  await parseSelectedSynopsis(cdp, recorder, report, "fileA", path.basename(synopsisFile), "导入并解析");
  const fileADecision = await prepareValidationDecision(cdp, recorder, report, "fileA");
  if (fileADecision.confirmDisabled !== false) throw new Error("File A was not confirmable after its validation decision");

  await setFileInput(cdp, recorder, replacementFile, "选择替换文件B");
  await waitForCondition(cdp, `document.querySelector('.synopsis-import-status')?.textContent.trim() === '替换待解析'`);
  const replacementState = await collectState(cdp);
  report.replacementGuard = {
    fileAConfirmEnabledBeforeReplacement: fileADecision.confirmDisabled === false,
    fileB: path.basename(replacementFile),
    importStatus: replacementState.importStatus,
    confirmDisabledImmediately: replacementState.confirmDisabled,
    sourceFilenameStillShown: replacementState.sourceFilename,
  };
  if (replacementState.confirmDisabled !== true) {
    throw new Error(`Selecting file B did not immediately disable confirmation: ${JSON.stringify(report.replacementGuard)}`);
  }
  report.states.fileBReplacementPending = await captureViewports(cdp, recorder, "04_file_B_replacement_pending", { requireFooter: true });

  await navigateToWorkbench(cdp, recorder);
  await waitForCondition(cdp, `(() => {
    const source = document.querySelector('.synopsis-source-review dd[title]');
    return source?.getAttribute('title') === ${JSON.stringify(path.basename(synopsisFile))}
      && document.querySelector('.synopsis-import-status')?.textContent.trim() === '待医学确认';
  })()`, 90000);
  const restoredFileA = await collectState(cdp);
  if (restoredFileA.sourceFilename !== path.basename(synopsisFile)) {
    throw new Error(`Reload did not restore the last server-persisted parsed synopsis A: ${JSON.stringify(restoredFileA)}`);
  }
  report.states.fileARestoredAfterReplacementReload = await captureViewports(
    cdp,
    recorder,
    "05_file_A_restored_after_replacement_reload",
    { requireFooter: true },
  );
  await prepareValidationDecision(cdp, recorder, report, "fileARestored");

  const importedBeforeConfirm = await collectState(cdp);
  const protocolIdBeforeConfirm = await evaluate(cdp, `Array.from(document.querySelectorAll('.authoring-field')).find((item) => item.querySelector(':scope > span')?.textContent.startsWith('方案号'))?.querySelector('input')?.value || ''`);
  if (!protocolIdBeforeConfirm) throw new Error("Parsed synopsis did not expose a protocol identifier candidate");
  await clickButton(cdp, recorder, "确认并进入两阶段补全", { contains: true });
  await waitForCondition(cdp, `(() => {
    const source = document.querySelector('.authoring-journey-state small')?.textContent || '';
    return source.includes('来源：导入方案摘要')
      && Boolean(document.querySelector('.authoring-stage-strip'))
      && Boolean(document.querySelector('.authoring-field-section'));
  })()`, 90000);
  report.states.sharedFraming = await captureViewports(cdp, recorder, "06_shared_framing_after_confirmation", { requireFooter: true });
  const sharedFraming = await collectState(cdp);
  if (!sharedFraming.framingVisible || !sharedFraming.sourceLabel.includes("来源：导入方案摘要")) {
    throw new Error(`Confirmation did not enter the shared framing workflow: ${JSON.stringify(sharedFraming)}`);
  }

  await navigateToWorkbench(cdp, recorder);
  await waitForCondition(cdp, `(() => {
    const source = document.querySelector('.authoring-journey-state small')?.textContent || '';
    return source.includes('来源：导入方案摘要')
      && Boolean(document.querySelector('.authoring-stage-strip'))
      && Boolean(document.querySelector('.authoring-field-section'));
  })()`, 90000);
  const protocolIdAfterReload = await evaluate(cdp, `Array.from(document.querySelectorAll('.authoring-field')).find((item) => item.querySelector(':scope > span')?.textContent.startsWith('方案号'))?.querySelector('input')?.value || ''`);
  if (protocolIdAfterReload !== protocolIdBeforeConfirm) {
    throw new Error(`Imported framing did not persist after refresh: before=${protocolIdBeforeConfirm}, after=${protocolIdAfterReload}`);
  }
  report.states.sharedFramingReloaded = await captureViewports(cdp, recorder, "07_shared_framing_reloaded", { requireFooter: true });

  const persistedResponse = await fetch(journeyUrl);
  const persisted = await persistedResponse.json().catch(() => ({}));
  if (!persistedResponse.ok) throw new Error(`Persisted journey GET failed: HTTP ${persistedResponse.status}`);
  if (persisted.entry_mode !== "synopsis_import" || persisted.synopsis_import?.status !== "confirmed" || !persisted.study_definition?.definition_id) {
    throw new Error(`Persisted synopsis journey is incomplete: ${JSON.stringify(persisted)}`);
  }

  report.importedBeforeConfirm = {
    sourceFilename: importedBeforeConfirm.sourceFilename,
    validations: importedBeforeConfirm.validations,
    warningCount: importedBeforeConfirm.warningCount,
    protocolId: protocolIdBeforeConfirm,
  };
  report.persistence = {
    protocolIdBeforeConfirm,
    protocolIdAfterReload,
    entryMode: persisted.entry_mode,
    synopsisStatus: persisted.synopsis_import.status,
    studyDefinitionId: persisted.study_definition.definition_id,
    studyDefinitionRevision: persisted.study_definition.revision,
  };
}

async function main() {
  const recorder = createRecorder();
  await recorder.initialize();
  let sourceStat;
  try {
    sourceStat = await stat(synopsisFile);
    if (!sourceStat.isFile() || sourceStat.size === 0) throw new Error(`SYNOPSIS_FILE is not a readable non-empty file: ${synopsisFile}`);
    await assertDisposableEmptyProject();
  } catch (error) {
    const preflightReport = {
      status: "failed",
      phase: "preflight",
      startedAt: timestamp(),
      failedAt: timestamp(),
      baseUrl: baseUrl.href,
      projectId,
      synopsisFile,
      outputDir,
      error: error.stack || error.message,
      rawEvidence: recorder.files,
    };
    await recorder.record("errors", { kind: "preflight", error: preflightReport.error });
    await writeFile(path.join(outputDir, "qc_report.json"), JSON.stringify(preflightReport, null, 2));
    await recorder.flush();
    throw error;
  }

  const tempRoot = await mkdtemp(path.join(tmpdir(), "mw-synopsis-import-qc-"));
  const replacementFile = path.join(
    tempRoot,
    `${path.basename(synopsisFile, extension)}_replacement_B${extension}`,
  );
  await copyFile(synopsisFile, replacementFile);
  await recorder.record("actions", {
    kind: "fixture",
    label: "由真实方案摘要建立同内容替换文件B",
    source: synopsisFile,
    replacement: replacementFile,
    bytes: sourceStat.size,
  });

  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-synopsis-import-chrome-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });

  const report = {
    startedAt: timestamp(),
    baseUrl: baseUrl.href,
    projectId,
    synopsisFile,
    replacementFile,
    outputDir,
    viewports,
    states: {},
    validation: {},
  };
  const diagnostics = { networkResponses: [], consoleEntries: [], pageErrors: [] };
  let cdp;
  let primaryError;

  try {
    const target = await waitForChrome(debugPort);
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    installDiagnostics(cdp, recorder, diagnostics);
    await run(cdp, recorder, report, replacementFile);
    await cdp.drainEvents();
    assertNetworkAndPageErrors(diagnostics);
    report.diagnostics = {
      networkResponseCount: diagnostics.networkResponses.length,
      consoleEntryCount: diagnostics.consoleEntries.length,
      pageErrorCount: diagnostics.pageErrors.length,
      unexpectedApiFailureCount: 0,
    };
    report.completedAt = timestamp();
    report.status = "passed";
  } catch (error) {
    primaryError = error;
    report.status = "failed";
    report.error = error.stack || error.message;
    report.failedAt = timestamp();
    if (cdp) {
      report.failureState = await collectState(cdp).catch(() => null);
      report.failureScreenshot = await capture(cdp, "99_failure.png").catch(() => "");
      await recorder.record("errors", { kind: "qc_failure", error: report.error, screenshot: report.failureScreenshot });
      await cdp.drainEvents().catch(() => {});
    }
  } finally {
    report.rawEvidence = recorder.files;
    await writeFile(path.join(outputDir, "qc_report.json"), JSON.stringify(report, null, 2));
    await recorder.flush();
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(500);
    await rm(userDataDir, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 }).catch(async (error) => {
      await recorder.record("errors", { kind: "cleanup", target: userDataDir, error: error.message });
    });
    await rm(tempRoot, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 }).catch(async (error) => {
      await recorder.record("errors", { kind: "cleanup", target: tempRoot, error: error.message });
    });
    await recorder.flush();
  }

  process.stdout.write(`${JSON.stringify({ status: report.status, outputDir, report: path.join(outputDir, "qc_report.json") }, null, 2)}\n`);
  if (primaryError) throw primaryError;
}

await main();
