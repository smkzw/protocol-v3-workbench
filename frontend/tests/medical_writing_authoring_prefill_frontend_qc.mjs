import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const appUrl = process.env.APP_URL || "http://127.0.0.1:5176/";
const apiUrl = process.env.API_URL || "http://127.0.0.1:8912";
const outputDir = process.env.QC_OUTPUT_DIR;
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9571);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
let runtimeExpectation = {};
if (!outputDir || process.env.QC_ISOLATED_RUNTIME !== "1") {
  throw new Error("QC_OUTPUT_DIR and QC_ISOLATED_RUNTIME=1 are required");
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(pathname, options = {}) {
  const response = await fetch(`${apiUrl}${pathname}`, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(runtimeExpectation.clientContractHeader && runtimeExpectation.apiContractVersion
        ? { [runtimeExpectation.clientContractHeader]: runtimeExpectation.apiContractVersion }
        : {}),
      ...(runtimeExpectation.frontendBuildId
        ? { "X-Workbench-Frontend-Build": runtimeExpectation.frontendBuildId }
        : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === "string"
      ? payload.detail
      : JSON.stringify(payload.detail || payload);
    throw new Error(`${response.status} ${pathname}: ${detail}`);
  }
  return payload;
}

async function waitForJson(url, timeoutMs = 30000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) return response.json();
    } catch {}
    await wait(200);
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

async function waitForCondition(cdp, expression, timeoutMs = 60000) {
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

async function selectProjectAndOpenWriting(cdp, projectId) {
  await waitForCondition(cdp, `Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`);
  await waitForCondition(cdp, `Boolean(document.querySelector('select[aria-label="选择临床研究项目"] option[value="${projectId}"]'))`);
  await evaluate(cdp, `(() => {
    const select = document.querySelector('select[aria-label="选择临床研究项目"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
    setter.call(select, ${JSON.stringify(projectId)});
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return select.value;
  })()`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
  await wait(500);
  await evaluate(cdp, `document.querySelector('.nav-item[title="医学写作"]').click()`);
  await waitForCondition(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`, 90000);
}

async function stopChrome(chrome, userDataDir) {
  if (chrome.exitCode === null) {
    chrome.kill("SIGTERM");
    await Promise.race([new Promise((resolve) => chrome.once("exit", resolve)), wait(5000)]);
    if (chrome.exitCode === null) chrome.kill("SIGKILL");
  }
  await rm(userDataDir, { recursive: true, force: true });
}

async function createProject({ indication, productPrefix, studyPhase }) {
  return request("/api/projects", {
    method: "POST",
    body: JSON.stringify({
      indication,
      product_name: `${productPrefix}-${Date.now()}`,
      study_phase: studyPhase,
      entry_mode: "from_zero",
      actor: "medical_manager_qc",
      idempotency_key: `prefill-frontend-qc-${productPrefix}-${Date.now()}`,
    }),
  });
}

async function adoptByApi(projectId, journey, fieldPath) {
  const group = journey.prefill_package.field_candidates[fieldPath];
  const candidate = group.candidates.find((item) => item.candidate_id === group.recommended_candidate_id);
  return request(`/api/projects/${projectId}/medical-writing/authoring-journey/prefill-package/adopt`, {
    method: "POST",
    body: JSON.stringify({
      expected_revision: journey.revision,
      expected_package_revision: journey.prefill_package.package_revision,
      field_path: fieldPath,
      candidate_id: candidate.candidate_id,
      actor: "medical_manager_qc",
      idempotency_key: `prefill-api-adopt-${fieldPath}-${journey.revision}`,
    }),
  });
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  runtimeExpectation = await waitForJson(
    `${appUrl.replace(/\/$/, "")}/runtime-build.json`,
  );
  const raCreated = await createProject({
    indication: "类风湿关节炎",
    productPrefix: "RA-PREFILL-E2E",
    studyPhase: "II期",
  });
  const pnhCreated = await createProject({
    indication: "阵发性睡眠性血红蛋白尿症",
    productPrefix: "PNH-PREFILL-E2E",
    studyPhase: "III期",
  });
  const projectId = raCreated.project.project_id;
  const pnhProjectId = pnhCreated.project.project_id;
  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-prefill-frontend-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  const errors = [];
  let cdp;
  const report = { passed: false, projectId, pnhProjectId, failures: [], evidence: {} };
  try {
    await waitForJson(`${apiUrl}/api/health`);
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    cdp = createCdp(targets.find((item) => item.type === "page").webSocketDebuggerUrl);
    await cdp.ready;
    cdp.on("Runtime.exceptionThrown", (event) => errors.push(event.exceptionDetails?.exception?.description || event.exceptionDetails?.text));
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await selectProjectAndOpenWriting(cdp, projectId);
    await waitForCondition(cdp, `Boolean(document.querySelector('[data-prefill-field="framing.protocol_id"]'))`, 90000);
    let journey = await request(`/api/projects/${projectId}/medical-writing/authoring-journey`);
    report.evidence.initial = {
      revision: journey.revision,
      packageId: journey.prefill_package?.package_id,
      packageStatus: journey.prefill_package?.status,
      availableFields: journey.prefill_package?.progress?.fields_with_recommendation,
      blockedFields: journey.prefill_package?.progress?.fields_blocked_missing_evidence,
      coreCandidateFields: [
        "framing.protocol_id",
        "framing.document_title",
        "framing.clinicaltrials_condition_term",
      ].filter((fieldPath) => journey.prefill_package?.field_candidates?.[fieldPath]?.candidates?.length > 0),
    };
    report.evidence.initialUi = await evaluate(cdp, `({
      recommendationOverviewCount: document.querySelectorAll('.authoring-prefill-panel').length,
      activeSection: document.querySelector('.authoring-prefill-section-tabs button.active')?.innerText,
      advancedRefinementOpen: document.querySelector('.authoring-advanced-refinement')?.open,
      repeatedMinimumInputsVisible: Array.from(document.querySelectorAll('.authoring-field')).filter((node) => ['试验药物', '适应症', '研究分期'].some((label) => node.innerText.startsWith(label)) && node.getBoundingClientRect().height > 0).length,
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    })`);
    await screenshot(cdp, "01_initial_prefill_1920x1080.png");

    const raBeforeConditionAdoption = await request(`/api/projects/${projectId}/medical-writing/authoring-journey`);
    await waitForCondition(cdp, `Boolean(document.querySelector('[data-prefill-field="framing.clinicaltrials_condition_term"] [data-prefill-action="adopt-recommended"]:not(:disabled)'))`);
    await evaluate(cdp, `(() => {
      const button = document.querySelector('[data-prefill-field="framing.clinicaltrials_condition_term"] [data-prefill-action="adopt-recommended"]');
      button.click();
      button.click();
      return true;
    })()`);
    await waitForCondition(cdp, `document.querySelector('[data-prefill-field="framing.clinicaltrials_condition_term"]')?.textContent.includes('已采用')`, 90000);
    await waitForCondition(cdp, `document.querySelector('.authoring-journey-message')?.textContent.includes('检索词已采用；')`, 180000);
    journey = await request(`/api/projects/${projectId}/medical-writing/authoring-journey`);
    report.evidence.raConditionResearch = {
      conditionBefore: raBeforeConditionAdoption.framing.clinicaltrials_condition_term,
      conditionAfter: journey.framing.clinicaltrials_condition_term,
      oldPlanId: raBeforeConditionAdoption.search_plan?.plan_id,
      newPlanId: journey.search_plan?.plan_id,
      snapshotId: journey.search_plan?.latest_snapshot_id,
      returnedCount: journey.search_plan?.returned_count,
      publicDocumentCount: journey.search_plan?.public_document_count,
      packageRevision: journey.prefill_package?.package_revision,
      studyDefinitionConfirmed: journey.study_definition?.field_states?.["framing.clinicaltrials_condition_term"]?.status === "confirmed",
      packageCandidateState: journey.prefill_package.field_candidates["framing.clinicaltrials_condition_term"].candidates
        .find((item) => item.structured_value === journey.framing.clinicaltrials_condition_term)?.state,
      uiShowsAdopted: await evaluate(cdp, `document.querySelector('[data-prefill-field="framing.clinicaltrials_condition_term"]')?.textContent.includes('已采用')`),
      message: await evaluate(cdp, `document.querySelector('.authoring-journey-message')?.innerText`),
      retryVisible: await evaluate(cdp, `Boolean(document.querySelector('.authoring-journey-message button'))`),
    };
    await screenshot(cdp, "01b_ra_condition_research_completed_1920x1080.png");

    // W4-A: sequential low-risk batch removed; single-field adopt remains for true field candidates.
    // Composite package panel is present; pending composite cards disable whole-package adopt.
    report.evidence.compositePanel = await evaluate(cdp, `({
      panelPresent: Boolean(document.querySelector('[data-testid="authoring-candidate-package-panel"]')),
      adoptCompositeButton: Boolean(document.querySelector('[data-testid="adopt-composite-button"]')),
      pendingHintOrDisabled: Boolean(
        document.querySelector('[data-testid="pending-gating-hint"]')
        || document.querySelector('[data-testid="adopt-composite-button"][disabled]')
      ),
      noBatchButton: !document.querySelector('.authoring-prefill-batch-button'),
      noPendingMedicalApprovalPhrase: !(document.body.innerText || '').includes('待医学批准'),
    })`);
    await waitForCondition(cdp, `Boolean(document.querySelector('[data-prefill-field="framing.protocol_id"] [data-prefill-action="adopt-recommended"]:not(:disabled)'))`);
    await evaluate(cdp, `document.querySelector('[data-prefill-field="framing.protocol_id"] [data-prefill-action="adopt-recommended"]').click()`);
    await waitForCondition(cdp, `document.querySelector('[data-prefill-field="framing.protocol_id"]')?.textContent.includes('已采用')`, 90000);
    await waitForCondition(cdp, `Boolean(document.querySelector('[data-prefill-field="framing.document_title"] [data-prefill-action="adopt-recommended"]:not(:disabled)'))`);
    await evaluate(cdp, `document.querySelector('[data-prefill-field="framing.document_title"] [data-prefill-action="adopt-recommended"]').click()`);
    await waitForCondition(cdp, `document.querySelector('[data-prefill-field="framing.document_title"]')?.textContent.includes('已采用')`, 90000);
    journey = await request(`/api/projects/${projectId}/medical-writing/authoring-journey`);
    const protocolGroup = journey.prefill_package.field_candidates["framing.protocol_id"];
    report.evidence.frontendAdoption = {
      revision: journey.revision,
      protocolId: journey.framing.protocol_id,
      confirmedCandidateIds: protocolGroup.candidates.filter((item) => item.state === "user_confirmed").map((item) => item.candidate_id),
      confirmedFieldPaths: Object.entries(journey.prefill_package.field_candidates)
        .filter(([, candidateGroup]) => candidateGroup.candidates.some((item) => item.state === "user_confirmed"))
        .map(([fieldPath]) => fieldPath),
      randomizationStillUnconfirmed: !journey.prefill_package.field_candidates["design.randomization"]?.candidates
        .some((item) => item.state === "user_confirmed"),
      singleFieldAdoptionPreserved: true,
      noLowRiskBatchLoop: true,
    };
    await screenshot(cdp, "02_single_field_identity_adopted_1920x1080.png");

    await cdp.send("Page.reload", { ignoreCache: true });
    await selectProjectAndOpenWriting(cdp, projectId);
    await waitForCondition(cdp, `document.querySelector('[data-prefill-field="framing.protocol_id"]')?.textContent.includes('已采用')`, 90000);
    report.evidence.frontendReload = await evaluate(cdp, `({
      url: location.href,
      protocolCard: document.querySelector('[data-prefill-field="framing.protocol_id"]')?.innerText,
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    })`);

    await evaluate(cdp, `Array.from(document.querySelectorAll('.authoring-prefill-section-tabs button')).find((node) => node.textContent.includes('总体设计')).click()`);
    await waitForCondition(cdp, `Boolean(document.querySelector('[data-prefill-field="design.randomization"]'))`, 90000);
    report.evidence.picosUi = await evaluate(cdp, `({
      recommendedFields: document.querySelectorAll('.authoring-prefill-field').length,
      recommendedCandidates: document.querySelectorAll('.authoring-prefill-candidates > section.recommended').length,
      advancedRefinementOpen: document.querySelector('.authoring-advanced-refinement')?.open,
      openCandidateDrawers: Array.from(document.querySelectorAll('.authoring-prefill-candidate-drawer')).filter((node) => node.open).length,
      visibleInternalEnums: ['randomized_exploratory', 'single_arm_early_phase', 'other'].filter((value) => document.querySelector('.authoring-prefill-panel')?.innerText.includes(value)),
      designArchetypeText: document.querySelector('[data-prefill-field="picos.design_archetype"]')?.innerText,
      randomizationActions: Array.from(document.querySelectorAll('[data-prefill-field="design.randomization"] .authoring-prefill-primary-actions button')).map((node) => {
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        return { text: node.innerText, disabled: node.disabled, x: rect.x, width: rect.width, display: style.display, visibility: style.visibility, background: style.backgroundColor, color: style.color };
      }),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    })`);
    await screenshot(cdp, "03_design_overview_1920x1080.png");

    await waitForCondition(cdp, `Boolean(document.querySelector('[data-prefill-field="design.randomization"] [data-prefill-action="adopt-recommended"]:not(:disabled)'))`);
    await evaluate(cdp, `document.querySelector('[data-prefill-field="design.randomization"] [data-prefill-action="adopt-recommended"]').click()`);
    await waitForCondition(cdp, `document.querySelector('[data-prefill-field="design.randomization"]')?.textContent.includes('已采用')`);
    journey = await request(`/api/projects/${projectId}/medical-writing/authoring-journey`);
    report.evidence.picosAdoption = {
      revision: journey.revision,
      designPattern: journey.framing.design_pattern,
      designArchetype: journey.picos.design_archetype,
      confirmedCandidateIds: journey.prefill_package.field_candidates["design.randomization"].candidates
        .filter((item) => item.state === "user_confirmed")
        .map((item) => item.candidate_id),
    };
    await cdp.send("Page.reload", { ignoreCache: true });
    await selectProjectAndOpenWriting(cdp, projectId);
    await evaluate(cdp, `Array.from(document.querySelectorAll('.authoring-prefill-section-tabs button')).find((node) => node.textContent.includes('总体设计')).click()`);
    await waitForCondition(cdp, `document.querySelector('[data-prefill-field="design.randomization"]')?.textContent.includes('已采用')`, 90000);
    await screenshot(cdp, "04_picos_adoption_after_reload_1920x1080.png");

    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 2560, height: 1440, deviceScaleFactor: 1, mobile: false });
    await wait(300);
    report.evidence.wideDesktop = await evaluate(cdp, `({
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      fieldOverflow: Array.from(document.querySelectorAll('.authoring-prefill-field')).some((node) => node.scrollWidth > node.clientWidth + 1),
      panelWidth: document.querySelector('.authoring-prefill-panel')?.getBoundingClientRect().width,
    })`);
    await screenshot(cdp, "05_design_overview_2560x1440.png");

    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await selectProjectAndOpenWriting(cdp, pnhProjectId);
    await waitForCondition(cdp, `Boolean(document.querySelector('[data-prefill-field="framing.protocol_id"]'))`, 90000);
    let pnhJourney = await request(`/api/projects/${pnhProjectId}/medical-writing/authoring-journey`);
    const pnhPlanBeforeConditionAdoption = pnhJourney.search_plan?.plan_id;
    await waitForCondition(cdp, `Boolean(document.querySelector('[data-prefill-field="framing.clinicaltrials_condition_term"] [data-prefill-action="adopt-recommended"]:not(:disabled)'))`);
    await evaluate(cdp, `(() => {
      const button = document.querySelector('[data-prefill-field="framing.clinicaltrials_condition_term"] [data-prefill-action="adopt-recommended"]');
      button.click();
      button.click();
      return true;
    })()`);
    await waitForCondition(cdp, `document.querySelector('[data-prefill-field="framing.clinicaltrials_condition_term"]')?.textContent.includes('已采用')`, 90000);
    await waitForCondition(cdp, `document.querySelector('.authoring-journey-message')?.textContent.includes('检索词已采用；')`, 180000);
    pnhJourney = await request(`/api/projects/${pnhProjectId}/medical-writing/authoring-journey`);
    report.evidence.pnhConditionResearch = {
      conditionAfter: pnhJourney.framing.clinicaltrials_condition_term,
      oldPlanId: pnhPlanBeforeConditionAdoption,
      newPlanId: pnhJourney.search_plan?.plan_id,
      snapshotId: pnhJourney.search_plan?.latest_snapshot_id,
      returnedCount: pnhJourney.search_plan?.returned_count,
      publicDocumentCount: pnhJourney.search_plan?.public_document_count,
      studyDefinitionConfirmed: pnhJourney.study_definition?.field_states?.["framing.clinicaltrials_condition_term"]?.status === "confirmed",
      packageCandidateState: pnhJourney.prefill_package.field_candidates["framing.clinicaltrials_condition_term"].candidates
        .find((item) => item.structured_value === pnhJourney.framing.clinicaltrials_condition_term)?.state,
      uiShowsAdopted: await evaluate(cdp, `document.querySelector('[data-prefill-field="framing.clinicaltrials_condition_term"]')?.textContent.includes('已采用')`),
      message: await evaluate(cdp, `document.querySelector('.authoring-journey-message')?.innerText`),
      retryVisible: await evaluate(cdp, `Boolean(document.querySelector('.authoring-journey-message button'))`),
    };
    await screenshot(cdp, "05b_pnh_condition_research_completed_1920x1080.png");
    const staleBaseRevision = pnhJourney.revision;
    pnhJourney = await adoptByApi(pnhProjectId, pnhJourney, "framing.document_title");
    await evaluate(cdp, `document.querySelector('[data-prefill-field="framing.protocol_id"] [data-prefill-action="adopt-recommended"]').click()`);
    await waitForCondition(cdp, `document.querySelector('.authoring-journey-message')?.textContent.includes('已重新读取最新版本')`, 90000);
    const conflictUi = await evaluate(cdp, `({
      message: document.querySelector('.authoring-journey-message')?.innerText,
      protocolStillPending: !document.querySelector('[data-prefill-field="framing.protocol_id"]')?.textContent.includes('已采用'),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    })`);
    await evaluate(cdp, `document.querySelector('[data-prefill-field="framing.protocol_id"] [data-prefill-action="adopt-recommended"]').click()`);
    await waitForCondition(cdp, `document.querySelector('[data-prefill-field="framing.protocol_id"]')?.textContent.includes('已采用')`, 90000);
    pnhJourney = await request(`/api/projects/${pnhProjectId}/medical-writing/authoring-journey`);
    report.evidence.pnh = {
      staleBaseRevision,
      revisionAfterExternalAdoption: pnhJourney.revision,
      conflictUi,
      indication: pnhJourney.framing.indication,
      phase: pnhJourney.framing.study_phase,
      protocolConfirmed: pnhJourney.prefill_package.field_candidates["framing.protocol_id"].candidates
        .some((item) => item.state === "user_confirmed"),
    };
    await screenshot(cdp, "06_pnh_conflict_recovered_1920x1080.png");

    const final = await evaluate(cdp, `({
      bodyTextLength: document.body.innerText.length,
      errorBoundary: document.body.innerText.includes('当前页面加载失败'),
      adoptedProtocol: document.querySelector('[data-prefill-field="framing.protocol_id"]')?.textContent.includes('已采用'),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    })`);
    report.evidence.final = final;
    report.failures.push(...errors.map((item) => `runtime:${item}`));
    if (
      !report.evidence.initial.packageId
      || !["ready", "partial"].includes(report.evidence.initial.packageStatus)
      || report.evidence.initial.availableFields < 1
      || !report.evidence.initial.coreCandidateFields.length
    ) report.failures.push("initial-prefill-package-missing");
    if (!report.evidence.frontendAdoption.confirmedCandidateIds.length) report.failures.push("frontend-adoption-not-persisted");
    if (!report.evidence.frontendAdoption.randomizationStillUnconfirmed) report.failures.push("high-risk-randomization-was-unintentionally-adopted");
    if (report.evidence.frontendAdoption.confirmedFieldPaths.some((fieldPath) => fieldPath.startsWith("design.") || fieldPath.startsWith("picos."))) report.failures.push("high-risk-field-was-unintentionally-adopted");
    if (!report.evidence.compositePanel?.panelPresent || !report.evidence.compositePanel?.noBatchButton) report.failures.push("composite-panel-or-batch-removal-missing");
    if (!report.evidence.compositePanel?.noPendingMedicalApprovalPhrase) report.failures.push("pending-medical-approval-phrase-present");
    if (!report.evidence.frontendReload.protocolCard?.includes("已采用")) report.failures.push("frontend-adoption-not-restored");
    if (
      !report.evidence.raConditionResearch.studyDefinitionConfirmed
      || !report.evidence.raConditionResearch.uiShowsAdopted
      || report.evidence.raConditionResearch.packageCandidateState !== "user_confirmed"
      || !/^[\x00-\x7F]+$/.test(report.evidence.raConditionResearch.conditionAfter || "")
      || report.evidence.raConditionResearch.oldPlanId === report.evidence.raConditionResearch.newPlanId
      || !report.evidence.raConditionResearch.snapshotId
      || report.evidence.raConditionResearch.retryVisible
    ) report.failures.push("ra-condition-adoption-research-chain-failed");
    if (
      !report.evidence.pnhConditionResearch.studyDefinitionConfirmed
      || !report.evidence.pnhConditionResearch.uiShowsAdopted
      || report.evidence.pnhConditionResearch.packageCandidateState !== "user_confirmed"
      || !/^[\x00-\x7F]+$/.test(report.evidence.pnhConditionResearch.conditionAfter || "")
      || report.evidence.pnhConditionResearch.oldPlanId === report.evidence.pnhConditionResearch.newPlanId
      || !report.evidence.pnhConditionResearch.snapshotId
      || report.evidence.pnhConditionResearch.retryVisible
    ) report.failures.push("pnh-condition-adoption-research-chain-failed");
    if (report.evidence.initialUi.recommendationOverviewCount !== 1 || report.evidence.initialUi.advancedRefinementOpen || report.evidence.initialUi.repeatedMinimumInputsVisible !== 0) report.failures.push("ai-first-overview-not-primary");
    if (report.evidence.picosUi.recommendedFields < 5 || report.evidence.picosUi.advancedRefinementOpen || report.evidence.picosUi.openCandidateDrawers !== 0) report.failures.push("design-overview-density-invalid");
    if (report.evidence.picosUi.visibleInternalEnums.length) report.failures.push("internal-design-enum-visible");
    if (report.evidence.picosUi.randomizationActions.find((item) => item.text === "采用推荐")?.background === "rgba(0, 0, 0, 0)") report.failures.push("primary-adoption-button-visually-invisible");
    if (report.evidence.wideDesktop.horizontalOverflow || report.evidence.wideDesktop.fieldOverflow) report.failures.push("wide-desktop-overflow");
    if (!report.evidence.pnh.protocolConfirmed || !report.evidence.pnh.conflictUi.message?.includes("已重新读取最新版本")) report.failures.push("pnh-stale-recovery-failed");
    if (!final.adoptedProtocol || final.errorBoundary || final.horizontalOverflow) report.failures.push("final-browser-state-invalid");
    report.passed = report.failures.length === 0;
  } finally {
    cdp?.close();
    await stopChrome(chrome, userDataDir);
    await writeFile(path.join(outputDir, "prefill_frontend_qc.json"), JSON.stringify(report, null, 2));
  }
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
