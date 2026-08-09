import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

if (process.env.QC_ISOLATED_RUNTIME !== "1") {
  throw new Error("imported PNH journey QC mutates runtime state and requires QC_ISOLATED_RUNTIME=1");
}

const appUrl = new URL(process.env.APP_URL || "http://127.0.0.1:5194/");
const projectId = process.env.PROJECT_ID || "proj_user_4bc29da4ac72";
const outputDir = path.resolve(process.env.QC_OUTPUT_DIR || "records/medical_writing_imported_pnh_journey_qc");
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || (9600 + (process.pid % 300)));
const viewports = [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }];
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(relativePath, options) {
  const response = await fetch(new URL(relativePath, appUrl), options);
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
    on(method, listener) {
      listeners.set(method, [...(listeners.get(method) || []), listener]);
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

async function setViewport(cdp, viewport) {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    ...viewport,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await wait(150);
}

async function screenshot(cdp, filename) {
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const target = path.join(outputDir, filename);
  await writeFile(target, Buffer.from(shot.data, "base64"));
  return target;
}

async function clickButton(cdp, text, { contains = false } = {}) {
  const clicked = await evaluate(cdp, `(() => {
    const button = Array.from(document.querySelectorAll('button')).find((item) => {
      const label = (item.textContent || '').trim();
      return ${contains ? "label.includes(" : "label === ("}${JSON.stringify(text)});
    });
    if (!button || button.disabled) return false;
    button.scrollIntoView({ block: 'center', inline: 'nearest' });
    button.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Enabled button not found: ${text}`);
}

async function setField(cdp, label, value) {
  const changed = await evaluate(cdp, `(() => {
    const field = Array.from(document.querySelectorAll('.authoring-field')).find((item) => {
      const heading = item.querySelector(':scope > span')?.textContent || '';
      return heading.startsWith(${JSON.stringify(label)});
    });
    const input = field?.querySelector('input, textarea, select');
    if (!input) return false;
    const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : input instanceof HTMLSelectElement ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error(`Field not found: ${label}`);
}

async function toggleChoice(cdp, label) {
  const toggled = await evaluate(cdp, `(() => {
    const option = Array.from(document.querySelectorAll('.authoring-choice-grid label'))
      .find((item) => (item.textContent || '').trim() === ${JSON.stringify(label)});
    const input = option?.querySelector('input[type=checkbox]');
    if (!input) return false;
    if (!input.checked) input.click();
    return true;
  })()`);
  if (!toggled) throw new Error(`Choice not found: ${label}`);
}

async function selectProjectAndOpenWriting(cdp) {
  await cdp.send("Page.navigate", { url: appUrl.href });
  await waitForCondition(cdp, `document.readyState === 'complete' && Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`, 90000);
  await waitForCondition(cdp, `Array.from(document.querySelector('select[aria-label="选择临床研究项目"]').options).some((item) => item.value === ${JSON.stringify(projectId)})`);
  await evaluate(cdp, `(() => {
    const select = document.querySelector('select[aria-label="选择临床研究项目"]');
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(select, ${JSON.stringify(projectId)});
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
  await clickButton(cdp, "医学写作");
  await waitForCondition(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`, 90000);
}

async function captureState(cdp, label) {
  const result = {};
  for (const viewport of viewports) {
    await setViewport(cdp, viewport);
    const metrics = await evaluate(cdp, `(() => ({
      viewport: { width: innerWidth, height: innerHeight },
      overflowX: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) - innerWidth,
      activeStage: document.querySelector('.authoring-stage-strip button.active')?.textContent.trim() || '',
      activeGroup: document.querySelector('.authoring-group-tabs button.active')?.textContent.trim() || '',
      message: document.querySelector('.authoring-journey-message')?.textContent.trim() || '',
    }))()`);
    if (metrics.overflowX > 1) throw new Error(`${label} has horizontal overflow at ${viewport.width}x${viewport.height}: ${metrics.overflowX}px`);
    const filename = `${label}_${viewport.width}x${viewport.height}.png`;
    result[`${viewport.width}x${viewport.height}`] = { metrics, screenshot: await screenshot(cdp, filename) };
  }
  return result;
}

async function fieldValue(cdp, label) {
  return evaluate(cdp, `(() => {
    const field = Array.from(document.querySelectorAll('.authoring-field')).find((item) =>
      (item.querySelector(':scope > span')?.textContent || '').startsWith(${JSON.stringify(label)})
    );
    return field?.querySelector('input, textarea, select')?.value || '';
  })()`);
}

function unexpectedHttpFailures(failures) {
  const expectedEmptyPaths = new Set([
    `/api/projects/${projectId}/medical-writing/manifest`,
    `/api/projects/${projectId}/medical-writing/document-session`,
  ]);
  return failures.filter((failure) => {
    let pathname = "";
    try { pathname = new URL(failure.url).pathname; } catch {}
    return !(failure.status === 404 && expectedEmptyPaths.has(pathname));
  });
}

async function assertCommittedJourney(report) {
  const journey = await request(`/api/projects/${projectId}/medical-writing/authoring-journey`);
  if (!journey.framing_complete || !journey.picos_complete || journey.current_stage !== "corpus") {
    throw new Error(`PNH two-stage journey did not complete: ${JSON.stringify(journey)}`);
  }
  if (journey.picos.design_archetype !== "randomized_exploratory") {
    throw new Error(`Committed design archetype drifted: ${journey.picos.design_archetype}`);
  }
  if (!journey.framing.target_mechanism?.includes("补体旁路途径")
      || !journey.framing.population_intent?.includes("PNH成人试验参与者")
      || !journey.picos.intervention_dose_regimen?.includes("疗效观察期12周")
      || !journey.picos.estimand_strategy?.includes("D84时Hb")) {
    throw new Error("Committed PNH framing/PICOS facts are incomplete after reload");
  }
  report.journey = journey;
}

async function run(cdp, report) {
  await selectProjectAndOpenWriting(cdp);
  const initialStage = await waitForCondition(cdp, `document.querySelector('.authoring-stage-strip button.active')?.textContent.trim() || ''`);
  if (initialStage.includes("语料准备")) {
    report.resumedFromCompletedJourney = true;
    const restoredCandidateCount = await waitForCondition(cdp, `(() => {
      const failure = document.querySelector('.writing-reference-message.danger')?.textContent.trim();
      if (failure) return { failure };
      const count = document.querySelectorAll('.writing-reference-list > button').length;
      return count > 0 ? { count } : false;
    })()`, 90000);
    if (restoredCandidateCount.failure) throw new Error(restoredCandidateCount.failure);
    if (restoredCandidateCount.count !== 50) {
      throw new Error(`Expected first page of 50 restored candidates, received ${restoredCandidateCount.count}`);
    }
    report.restoredCandidateCount = restoredCandidateCount.count;
    report.states.corpusGateReload = await captureState(cdp, "00_resumed_corpus_gate");
    await assertCommittedJourney(report);
    return;
  }
  if (!initialStage.includes("研究框架")) throw new Error(`Unexpected initial authoring stage: ${initialStage}`);
  report.states.initialFraming = await captureState(cdp, "01_imported_framing_draft");

  await setField(cdp, "研究分期", "II期");
  await setField(cdp, "ClinicalTrials.gov疾病检索词", "Paroxysmal Nocturnal Hemoglobinuria");
  await clickButton(cdp, "研究目的");
  await toggleChoice(cdp, "剂量探索");
  await clickButton(cdp, "竞品范围");
  await setField(cdp, "靶点/作用机制", "补体旁路途径相关机制；具体分子靶点需结合IB及I期药理、PK/PD资料由医学经理确认");
  await setField(cdp, "竞品靶点与机制范围", "补体B因子、D因子及其他补体旁路近邻机制");
  await clickButton(cdp, "总体设计");
  await setField(cdp, "目标研究人群意图", "既往未接受过补体抑制剂治疗、存在活动性溶血和贫血的PNH成人试验参与者");
  report.states.framingCompletedFields = await captureState(cdp, "02_framing_completed_fields");
  await clickButton(cdp, "保存草稿");
  await waitForCondition(cdp, `document.querySelector('.authoring-journey-message')?.textContent.includes('草稿已保存')`);

  await selectProjectAndOpenWriting(cdp);
  await clickButton(cdp, "竞品范围");
  const restoredTarget = await fieldValue(cdp, "靶点/作用机制");
  await clickButton(cdp, "总体设计");
  const restoredPopulation = await fieldValue(cdp, "目标研究人群意图");
  if (!restoredTarget.includes("补体旁路途径") || !restoredPopulation.includes("PNH成人试验参与者")) {
    throw new Error(`Framing draft did not persist after full reload: ${JSON.stringify({ restoredTarget, restoredPopulation })}`);
  }
  report.framingReload = { restoredTarget, restoredPopulation };
  await clickButton(cdp, "完成第一步");
  await waitForCondition(cdp, `document.querySelector('.authoring-stage-strip button.active')?.textContent.includes('PICOS设计')`, 90000);
  await waitForCondition(cdp, `(() => { const text = document.body.textContent || ''; return text.includes('已检索') || text.includes('公开研究检索未完成'); })()`, 300000);
  const searchText = await evaluate(cdp, `document.body.textContent || ''`);
  if (searchText.includes("公开研究检索未完成")) throw new Error("ClinicalTrials.gov search did not complete");
  report.states.picosStart = await captureState(cdp, "03_picos_after_public_search");

  const archetype = await evaluate(cdp, `document.querySelector('.authoring-design-archetypes input:checked')?.value || ''`);
  const applicabilityLocks = await evaluate(cdp, `Array.from(document.querySelectorAll('.authoring-applicability-row')).map((row) => ({ label: row.querySelector('strong')?.textContent.trim(), disabled: row.querySelector('select')?.disabled }))`);
  if (archetype !== "randomized_exploratory") throw new Error(`PNH design archetype was not retained: ${archetype}`);
  if (!applicabilityLocks.find((item) => item.label === "对照组设计")?.disabled) {
    throw new Error(`Randomized exploratory comparator was not locked as required: ${JSON.stringify(applicabilityLocks)}`);
  }
  report.designApplicability = { archetype, applicabilityLocks };

  await clickButton(cdp, "干预措施");
  await setField(cdp, "试验药物剂量与给药方案", "CMS-D017胶囊低剂量组和高剂量组每日口服给药，疗效观察期12周；具体剂量、给药频次及餐食要求待I期SAD/MAD、PK/PD和安全性结果确认后定稿");
  await clickButton(cdp, "执行与统计");
  await setField(cdp, "估计目标策略", "人群为FAS；治疗条件为CMS-D017低剂量组与高剂量组；变量为D84时Hb较基线变化值；红细胞输注、停药及缺失数据等治疗间事件的处理策略待医学与统计共同确认；采用ANCOVA估计组间差异及95%CI");
  report.states.picosCompletedFields = await captureState(cdp, "04_picos_completed_fields");
  await clickButton(cdp, "保存草稿");
  await waitForCondition(cdp, `document.querySelector('.authoring-journey-message')?.textContent.includes('草稿已保存')`);

  await selectProjectAndOpenWriting(cdp);
  await clickButton(cdp, "干预措施");
  const restoredRegimen = await fieldValue(cdp, "试验药物剂量与给药方案");
  await clickButton(cdp, "执行与统计");
  const restoredEstimand = await fieldValue(cdp, "估计目标策略");
  if (!restoredRegimen.includes("疗效观察期12周") || !restoredEstimand.includes("D84时Hb")) {
    throw new Error(`PICOS draft did not persist after full reload: ${JSON.stringify({ restoredRegimen, restoredEstimand })}`);
  }
  report.picosReload = { restoredRegimen, restoredEstimand };
  await clickButton(cdp, "完成第二步");
  await waitForCondition(cdp, `document.querySelector('.authoring-stage-strip button.active')?.textContent.includes('语料准备')`, 90000);
  report.states.corpusGate = await captureState(cdp, "05_corpus_gate_after_picos");

  await assertCommittedJourney(report);
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-imported-pnh-journey-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  const report = { status: "running", projectId, appUrl: appUrl.href, startedAt: new Date().toISOString(), states: {} };
  let cdp;
  try {
    const target = await waitForChrome();
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Log.enable");
    await cdp.send("Network.enable");
    const pageErrors = [];
    const failedResponses = [];
    cdp.on("Runtime.exceptionThrown", (event) => pageErrors.push({
      kind: "runtime_exception",
      text: event.exceptionDetails?.exception?.description || event.exceptionDetails?.text || "runtime exception",
    }));
    cdp.on("Network.responseReceived", (event) => {
      if ((event.response?.status || 0) < 400) return;
      failedResponses.push({
        status: event.response.status,
        url: event.response.url || "",
        type: event.type || "",
        mimeType: event.response.mimeType || "",
      });
    });
    cdp.on("Log.entryAdded", (event) => {
      if (event.entry?.level !== "error") return;
      const text = event.entry.text || "console error";
      if (text.startsWith("Failed to load resource:")) return;
      pageErrors.push({ kind: "browser_log", text, url: event.entry.url || "" });
    });
    await setViewport(cdp, viewports[1]);
    await run(cdp, report);
    report.failedResponses = failedResponses;
    const unexpectedFailures = unexpectedHttpFailures(failedResponses);
    report.unexpectedHttpFailures = unexpectedFailures;
    if (unexpectedFailures.length) throw new Error(`HTTP failures detected: ${JSON.stringify(unexpectedFailures)}`);
    if (pageErrors.length) throw new Error(`Browser errors detected: ${JSON.stringify(pageErrors)}`);
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
