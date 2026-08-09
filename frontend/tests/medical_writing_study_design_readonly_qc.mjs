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
  "../../records/active_slices/medical_writing_authoring_journey_20260715/browser_qc/study_design_readonly",
);
const projectId = process.env.QC_PROJECT_ID || "proj_ra_greenfield_sandbox";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9562);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function json(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status}: ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 20000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try { return await json(url); } catch { await wait(200); }
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
    on(method, callback) { listeners.set(method, [...(listeners.get(method) || []), callback]); },
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

async function main() {
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-study-design-readonly-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  let cdp;
  const nonGetRequests = [];
  const consoleErrors = [];
  try {
    const journey = await json(`${apiUrl}/api/projects/${projectId}/medical-writing/authoring-journey`);
    const searchPlan = journey.search_plan;
    if (!searchPlan?.latest_snapshot_id) throw new Error("Stable QC project has no locked competitor-search snapshot");
    const snapshot = await json(`${apiUrl}/api/projects/${projectId}/medical-writing/references/search-snapshots/${searchPlan.latest_snapshot_id}`);
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    cdp = createCdp(targets.find((item) => item.type === "page").webSocketDebuggerUrl);
    await cdp.ready;
    cdp.on("Network.requestWillBeSent", (event) => {
      if (event.request.method !== "GET") nonGetRequests.push({ method: event.request.method, url: event.request.url });
    });
    cdp.on("Runtime.exceptionThrown", (event) => consoleErrors.push(event.exceptionDetails?.exception?.description || event.exceptionDetails?.text));
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);
    await waitForCondition(cdp, `(() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      return Boolean(
        select
        && !select.disabled
        && Array.from(select.options).some((option) => option.value === ${JSON.stringify(projectId)})
      );
    })()`);
    await evaluate(cdp, `(() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
      setter.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
    await evaluate(cdp, `Array.from(document.querySelectorAll('.nav-item')).find((node) => node.textContent.trim() === '医学写作').click()`);
    await waitForCondition(cdp, `document.body.textContent.includes("研究方案文档编辑与AI修订")`);
    await waitForCondition(cdp, `Array.from(document.querySelectorAll('.writing-title-actions button')).some((node) => node.textContent.includes('研究设计'))`);
    await evaluate(cdp, `Array.from(document.querySelectorAll('.writing-title-actions button')).find((node) => node.textContent.includes('研究设计')).click()`);
    await waitForCondition(cdp, `Boolean(document.querySelector('.writing-study-design-drawer[aria-label="研究设计基线"]'))`);
    await waitForCondition(cdp, `(() => {
      const drawer = document.querySelector('.writing-study-design-drawer[aria-label="研究设计基线"]');
      return Boolean(
        drawer?.querySelector('.authoring-stage-strip')
        && drawer?.querySelector('.authoring-journey-fieldset')?.disabled
      );
    })()`);
    await waitForCondition(cdp, `document.body.textContent.includes("实际发送到注册库的条件")`);
    await waitForCondition(cdp, `document.body.textContent.includes("检索后医学分诊线索")`);
    await waitForCondition(cdp, `(() => {
      const count = document.querySelector('.writing-reference-candidate-filters > span');
      const rows = document.querySelectorAll('.writing-reference-list > button');
      return count?.textContent.trim() === ${JSON.stringify(`${snapshot.returned_count}项`)}
        && rows.length === Math.min(50, ${snapshot.returned_count})
        && !document.querySelector('.writing-reference-empty');
    })()`);
    const metrics = await evaluate(cdp, `(() => {
      const drawer = document.querySelector('.writing-study-design-drawer[aria-label="研究设计基线"]');
      const fieldset = drawer?.querySelector('.authoring-journey-fieldset');
      const rect = drawer?.getBoundingClientRect();
      const firstCandidate = drawer?.querySelector('.writing-reference-list > button');
      const firstCandidateTitle = firstCandidate?.querySelector('strong');
      const stageLabels = Array.from(drawer?.querySelectorAll('.authoring-stage-strip button') || []).map((node) => node.textContent.trim());
      return {
        drawerVisible: Boolean(drawer),
        fieldsetDisabled: Boolean(fieldset?.disabled),
        hasFramingStage: stageLabels.some((label) => label.includes('研究框架')),
        hasPicosStage: stageLabels.some((label) => label.includes('PICOS设计')),
        hasCorpusStage: stageLabels.some((label) => label.includes('语料准备')),
        hasControlledChangeBoundary: drawer?.textContent.includes('受控变更流程'),
        hasRegistryContract: drawer?.textContent.includes('实际发送到注册库的条件'),
        hasTriageContract: drawer?.textContent.includes('检索后医学分诊线索'),
        hasCondition: drawer?.textContent.includes('Rheumatoid Arthritis'),
        hasPhase: drawer?.textContent.includes('PHASE2'),
        hasStudyType: drawer?.textContent.includes('INTERVENTIONAL'),
        hasUnrestrictedIntervention: drawer?.textContent.includes('干预名称不限'),
        hasUnrestrictedRegion: drawer?.textContent.includes('研究地区不限'),
        hasTargetTriage: drawer?.textContent.includes('靶点/作用机制相近'),
        hasObjectiveTriage: drawer?.textContent.includes('内在研究目的相近'),
        noLegacyPseudoQuery: !drawer?.textContent.includes('Rheumatoid Arthritis 同靶点、同机制及同治疗线生物制剂 II期'),
        noContractError: !drawer?.textContent.includes('检索合同版本过旧'),
        candidateCountMatchesSnapshot: drawer?.querySelector('.writing-reference-candidate-filters > span')?.textContent.trim() === ${JSON.stringify(`${snapshot.returned_count}项`)},
        candidateFirstPageComplete: drawer?.querySelectorAll('.writing-reference-list > button').length === Math.min(50, ${snapshot.returned_count}),
        candidateEmptyStateAbsent: !drawer?.querySelector('.writing-reference-empty'),
        candidateTextReadable: Boolean(firstCandidate && firstCandidateTitle && Number(getComputedStyle(firstCandidate).opacity) >= 0.99 && getComputedStyle(firstCandidateTitle).color === 'rgb(32, 36, 42)'),
        withinViewport: Boolean(rect && rect.left >= 0 && rect.right <= window.innerWidth + 1 && rect.top >= 0 && rect.bottom <= window.innerHeight + 1),
        noPageOverflowX: document.documentElement.scrollWidth <= window.innerWidth + 1,
      };
    })()`);
    const image = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
    await writeFile(path.join(outputDir, "study_design_readonly_1600x1000.png"), Buffer.from(image.data, "base64"));
    const registryFilter = searchPlan.registry_filter;
    const snapshotRequest = snapshot.request;
    const decodedQueryUrl = decodeURIComponent(snapshot.query_url || "");
    const apiContract = {
      schemaV4: journey.schema_version === "medical_writing_authoring_journey_v4",
      registryFilterPresent: Boolean(registryFilter),
      conditionMatchesSnapshot: registryFilter?.condition_term === snapshotRequest.indication,
      phasesMatchSnapshot: JSON.stringify(registryFilter?.phases || []) === JSON.stringify(snapshotRequest.phases || []),
      studyTypeMatchesSnapshot: registryFilter?.study_type === snapshotRequest.study_type,
      interventionsMatchSnapshot: JSON.stringify(registryFilter?.intervention_terms || []) === JSON.stringify(snapshotRequest.intervention_terms || []),
      regionsMatchSnapshot: JSON.stringify(registryFilter?.regions || []) === JSON.stringify(snapshotRequest.regions || []),
      triageSeparatedFromQueryUrl: !['同靶点', '概念验证', 'PoC', '剂量探索', '随机', '安慰剂'].some((term) => decodedQueryUrl.includes(term)),
      canonicalQueriesOnly: (searchPlan.queries || []).every((query) => /^(疾病\/适应症|研究分期|研究类型)：/.test(query)),
    };
    const report = { projectId, viewport: { width: 1600, height: 1000 }, metrics, apiContract, nonGetRequests, consoleErrors };
    report.passed = Object.values(metrics).every(Boolean) && Object.values(apiContract).every(Boolean) && nonGetRequests.length === 0 && consoleErrors.length === 0;
    await writeFile(path.join(outputDir, "medical_writing_study_design_readonly_qc.json"), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    if (!report.passed) process.exitCode = 1;
  } finally {
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(400);
    await rm(userDataDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
