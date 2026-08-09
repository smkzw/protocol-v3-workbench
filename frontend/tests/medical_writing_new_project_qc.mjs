import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const apiUrl = process.env.API_URL || "http://127.0.0.1:8911";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(
  scriptDir,
  "../../records/active_slices/medical_writing_workspace_usability_20260715/browser_loop_1",
);
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9396);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
if (process.env.QC_ISOLATED_RUNTIME !== "1") {
  throw new Error("medical_writing_new_project_qc.mjs mutates runtime state and requires QC_ISOLATED_RUNTIME=1");
}
const entryMode = process.env.QC_ENTRY_MODE || "from_zero";
const projectCode = process.env.QC_PROJECT_CODE || `QC-RA-${entryMode}-${Date.now()}`;
const projectName = process.env.QC_PROJECT_NAME || "类风湿关节炎II期研究方案";
const indication = process.env.QC_INDICATION || "类风湿关节炎";
const studyPhase = ({ I: "I期", "I/II": "I/II期", II: "II期", "II/III": "II/III期", III: "III期" })[process.env.QC_STUDY_PHASE] || process.env.QC_STUDY_PHASE || "II期";
const investigationalProduct = process.env.QC_INVESTIGATIONAL_PRODUCT || "RA-01";
const protocolId = process.env.QC_PROTOCOL_ID || projectCode;
const API_CONTRACT_HEADERS = {
  "X-Workbench-Api-Contract": "medical-writing-api-2026-07-17.1",
};

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function stopChrome(chrome, userDataDir) {
  if (chrome.exitCode === null) {
    const exited = new Promise((resolve) => chrome.once("exit", resolve));
    chrome.kill("SIGTERM");
    await Promise.race([exited, wait(5000)]);
    if (chrome.exitCode === null) {
      chrome.kill("SIGKILL");
      await Promise.race([exited, wait(2000)]);
    }
  }
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      await rm(userDataDir, { recursive: true, force: true });
      return;
    } catch (error) {
      if (error?.code !== "ENOTEMPTY" || attempt === 4) throw error;
      await wait(200 * (attempt + 1));
    }
  }
}

async function json(url) {
  const response = await fetch(url, { headers: API_CONTRACT_HEADERS });
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      return await json(url);
    } catch {
      await wait(200);
    }
  }
  throw new Error(`Timed out waiting for ${url}`);
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
      listeners.set(method, [...(listeners.get(method) || []), callback]);
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
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(cdp, expression)) return;
    await wait(200);
  }
  throw new Error(`Timed out waiting for ${expression}`);
}

async function screenshot(cdp, filename) {
  const image = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  await writeFile(path.join(outputDir, filename), Buffer.from(image.data, "base64"));
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "medical-writing-new-project-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  const errors = [];
  const requests = new Map();
  const projectCreateResponses = [];
  let cdp;
  try {
    await waitForJson(`${apiUrl}/api/health`);
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    cdp = createCdp(targets.find((item) => item.type === "page").webSocketDebuggerUrl);
    await cdp.ready;
    cdp.on("Runtime.exceptionThrown", (event) => errors.push(event.exceptionDetails?.exception?.description || event.exceptionDetails?.text));
    cdp.on("Network.requestWillBeSent", (event) => requests.set(event.requestId, event.request));
    cdp.on("Network.responseReceived", (event) => {
      const request = requests.get(event.requestId);
      if (request?.method === "POST" && new URL(request.url).pathname === "/api/projects") {
        projectCreateResponses.push({ method: request.method, status: event.response.status, url: request.url });
      }
    });
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);

    await evaluate(cdp, `Array.from(document.querySelectorAll('button')).find((node) => node.textContent.includes('新建项目')).click()`);
    await waitForCondition(cdp, `Boolean(document.querySelector('.new-project-dialog'))`);
    await evaluate(cdp, `(() => {
      const modeButton = Array.from(document.querySelectorAll('.new-project-entry-mode button'))
        .find((node) => node.textContent.includes(${JSON.stringify(entryMode === "synopsis_import" ? "导入方案摘要" : "从零开始")}));
      modeButton?.click();
      return Boolean(modeButton);
    })()`);
    if (entryMode === "synopsis_import") {
      await waitForCondition(cdp, `Boolean(document.querySelector('.file-first-synopsis-intake'))`);
      await waitForCondition(cdp, `Boolean(document.querySelector('.file-first-synopsis-intake input[type="file"]'))`);
      await screenshot(cdp, `new_project_${entryMode}_1920x1080.png`);
      const report = await evaluate(cdp, `(() => ({
        selectedProjectId: document.querySelector('select[aria-label="选择临床研究项目"]')?.value || "",
        bodyTextLength: document.body.innerText.length,
        entryModeChooserVisible: Boolean(document.querySelector('.authoring-entry-mode-options')),
        synopsisIntakeVisible: Boolean(document.querySelector('.file-first-synopsis-intake')),
        filePickerVisible: Boolean(document.querySelector('.file-first-synopsis-intake input[type="file"]')),
        synopsisCreateButtonHidden: !Boolean(document.querySelector('.new-project-fields')),
        hasWhiteScreen: document.body.innerText.trim().length < 100,
        hasErrorBoundary: document.body.innerText.includes('当前页面加载失败'),
        horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      }))()`);
      report.requestedEntryMode = entryMode;
      report.persistedJourneyMode = "not_created_until_file_confirmation";
      report.projectCreateResponses = projectCreateResponses;
      report.errors = errors;
      report.passed = report.synopsisIntakeVisible
        && report.filePickerVisible
        && report.synopsisCreateButtonHidden
        && !report.entryModeChooserVisible
        && !report.hasWhiteScreen
        && !report.hasErrorBoundary
        && !report.horizontalOverflow
        && errors.length === 0;
      await writeFile(path.join(outputDir, "new_project_report.json"), JSON.stringify(report, null, 2));
      console.log(JSON.stringify(report, null, 2));
      if (!report.passed) throw new Error(`synopsis-entry QC failed: ${JSON.stringify(report)}`);
      return;
    }
    await evaluate(cdp, `(() => {
      const setValue = (label, value) => {
        const labelNode = Array.from(document.querySelectorAll('.new-project-fields label')).find((node) => node.textContent.includes(label));
        const input = labelNode?.querySelector('input, select');
        if (!input) return false;
        const setter = Object.getOwnPropertyDescriptor(input instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value').set;
        setter.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      };
      return [
        setValue('试验药物', ${JSON.stringify(investigationalProduct)}),
        setValue('适应症', ${JSON.stringify(indication)}),
        setValue('研究分期', ${JSON.stringify(studyPhase)}),
      ].every(Boolean);
    })()`);
    await evaluate(cdp, `Array.from(document.querySelectorAll('.new-project-dialog button')).find((node) => node.textContent.includes('创建并进入写作')).click()`);

    await waitForCondition(cdp, `document.body.textContent.includes('研究方案智能设计与写作')`);
    await waitForCondition(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`);
    await waitForCondition(cdp, entryMode === "synopsis_import"
      ? `document.body.textContent.includes('选择PDF或DOCX方案/方案摘要')`
      : `document.body.textContent.includes('项目与产品')`);
    const selectedProjectId = await evaluate(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value`);
    const journey = await json(`${apiUrl}/api/projects/${selectedProjectId}/medical-writing/authoring-journey`);
    await screenshot(cdp, `new_project_${entryMode}_1920x1080.png`);
    const report = await evaluate(cdp, `(() => ({
      selectedProjectId: document.querySelector('select[aria-label="选择临床研究项目"]')?.value,
      bodyTextLength: document.body.innerText.length,
      entryModeChooserVisible: Boolean(document.querySelector('.authoring-entry-mode-options')),
      framingVisible: document.body.innerText.includes('项目与产品'),
      synopsisUploadVisible: document.body.innerText.includes('选择PDF或DOCX方案/方案摘要'),
      hasWhiteScreen: document.body.innerText.trim().length < 100,
      hasErrorBoundary: document.body.innerText.includes('当前页面加载失败'),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    }))()`);
    report.projectCode = journey.framing.protocol_id.replace(/-DRAFT$/, "");
    report.projectName = journey.framing.document_title;
    report.indication = indication;
    report.studyPhase = studyPhase;
    report.investigationalProduct = investigationalProduct;
    report.protocolId = protocolId;
    report.requestedEntryMode = entryMode;
    report.persistedJourneyMode = journey.entry_mode;
    report.projectCreateResponses = projectCreateResponses;
    report.errors = errors;
    report.passed = !report.entryModeChooserVisible
      && !report.hasWhiteScreen
      && !report.hasErrorBoundary
      && !report.horizontalOverflow
      && projectCreateResponses.some((item) => item.status === 201)
      && journey.entry_mode === (entryMode === "synopsis_import" ? "synopsis_import" : "guided_greenfield")
      && (entryMode === "synopsis_import" ? report.synopsisUploadVisible : report.framingVisible)
      && errors.length === 0;
    await writeFile(path.join(outputDir, "new_project_report.json"), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    if (!report.passed) throw new Error(`new-project QC failed: ${JSON.stringify(report)}`);
  } finally {
    cdp?.close();
    await stopChrome(chrome, userDataDir);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
