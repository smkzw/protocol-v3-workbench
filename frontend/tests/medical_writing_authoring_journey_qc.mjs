import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const projectId = process.env.PROJECT_ID || "proj_ra_greenfield_sandbox";
const qcMode = process.env.QC_MODE || "journey";
if (qcMode !== "ready" && process.env.QC_ISOLATED_RUNTIME !== "1") {
  throw new Error("medical_writing_authoring_journey_qc.mjs mutates runtime state and requires QC_ISOLATED_RUNTIME=1");
}
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9396);
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(
  __dirname,
  "..",
  "..",
  "records",
  "visual_qc_20260714",
  qcMode === "ready" ? "medical_writing_normal_corpus_ready" : "medical_writing_authoring_journey",
);
const viewports = [
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1600, height: 1000 },
  { width: 1920, height: 1080 },
];

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function getJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${url}: ${JSON.stringify(payload)}`);
  return payload;
}

async function waitForJson(url, timeoutMs = 10000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await getJson(url);
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

async function waitForCondition(cdp, expression, timeoutMs = 30000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(250);
  }
  throw new Error(`Timed out waiting for condition; last=${JSON.stringify(lastValue)}`);
}

async function navigateToApp(cdp) {
  await cdp.send("Page.navigate", { url: "about:blank" });
  await waitForCondition(cdp, `location.href === 'about:blank' && document.readyState === 'complete'`);
  await cdp.send("Page.navigate", { url: appUrl });
  await waitForCondition(
    cdp,
    `location.href.startsWith(${JSON.stringify(appUrl)}) && document.readyState === 'complete' && Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`,
    45000,
  );
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

async function metrics(cdp) {
  return evaluate(cdp, `(() => {
    const shell = document.querySelector('.authoring-journey-shell');
    const journeyBody = document.querySelector('.authoring-journey-body');
    const footer = document.querySelector('.authoring-journey-footer');
    const body = document.body;
    const doc = document.documentElement;
    const rect = shell?.getBoundingClientRect();
    const footerRect = footer?.getBoundingClientRect();
    const controls = Array.from(document.querySelectorAll('.authoring-journey-shell button, .authoring-journey-shell input, .authoring-journey-shell select, .authoring-journey-shell textarea'));
    const gateChecklistLabels = Array.from(document.querySelectorAll('.authoring-gate-checklist label')).map((node) => {
      const rect = node.getBoundingClientRect();
      const textRect = node.querySelector('span')?.getBoundingClientRect();
      return {
        text: (node.textContent || '').trim(),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        textWidth: Math.round(textRect?.width || 0),
      };
    });
    const incoherent = controls.filter((node) => {
      const item = node.getBoundingClientRect();
      return item.width < 1 || item.height < 1 || item.right > window.innerWidth + 2 || item.left < -2;
    }).map((node) => ({ tag: node.tagName, text: (node.textContent || node.getAttribute('aria-label') || '').trim().slice(0, 60) }));
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      shell: rect ? { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height } : null,
      pageOverflowX: Math.max(body.scrollWidth, doc.scrollWidth) - window.innerWidth,
      shellOverflowX: shell ? shell.scrollWidth - shell.clientWidth : null,
      documentOverflowY: Math.max(body.scrollHeight, doc.scrollHeight) - window.innerHeight,
      journeyBodyOverflowY: journeyBody ? journeyBody.scrollHeight - journeyBody.clientHeight : null,
      footer: footerRect ? { top: footerRect.top, bottom: footerRect.bottom, height: footerRect.height } : null,
      aiRailVisible: Boolean(document.querySelector('.writing-ai-core')),
      documentMapVisible: Array.from(document.querySelectorAll('.writing-title-actions button')).some((button) => (button.textContent || '').trim() === '目录'),
      editorToolbarVisible: Boolean(document.querySelector('.writing-title-actions')),
      gateChecklistLabels,
      incoherentControls: incoherent,
      stage: document.querySelector('.authoring-stage-strip button.active')?.textContent?.trim() || '',
      bodyTextSample: (body.textContent || '').replace(/\s+/g, ' ').slice(0, 500),
    };
  })()`);
}

async function captureViewports(cdp, prefix, { focusSelector = "" } = {}) {
  const result = {};
  for (const viewport of viewports) {
    await setViewport(cdp, viewport);
    await evaluate(cdp, `(() => {
      window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
      const journeyBody = document.querySelector('.authoring-journey-body');
      if (journeyBody) journeyBody.scrollTo({ top: 0, left: 0, behavior: 'instant' });
      const focus = ${JSON.stringify(focusSelector)} ? document.querySelector(${JSON.stringify(focusSelector)}) : null;
      if (focus) focus.scrollIntoView({ block: 'start', inline: 'nearest', behavior: 'instant' });
      return true;
    })()`);
    const key = `${viewport.width}x${viewport.height}`;
    result[key] = {
      screenshot: await capture(cdp, `${prefix}_${key}.png`),
      metrics: await metrics(cdp),
    };
  }
  await setViewport(cdp, viewports[2]);
  return result;
}

function assertPreDocumentMetrics(label, state) {
  for (const [viewport, entry] of Object.entries(state)) {
    const current = entry.metrics;
    if (current.pageOverflowX > 0) {
      throw new Error(`${label} has ${current.pageOverflowX}px horizontal overflow at ${viewport}`);
    }
    if (current.aiRailVisible || current.documentMapVisible || current.editorToolbarVisible) {
      throw new Error(`${label} exposes document-only controls before document creation at ${viewport}`);
    }
    if (current.footer && (current.footer.top < 0 || current.footer.bottom > current.viewport.height + 1)) {
      throw new Error(`${label} footer is outside the desktop viewport at ${viewport}: ${JSON.stringify(current.footer)}`);
    }
    if (current.footer && current.documentOverflowY > 1 && current.journeyBodyOverflowY > 1) {
      throw new Error(`${label} has nested document and journey scrolling at ${viewport}: document=${current.documentOverflowY}px, journey=${current.journeyBodyOverflowY}px`);
    }
  }
}

async function clickButton(cdp, text, { contains = false } = {}) {
  const clicked = await evaluate(cdp, `(() => {
    const button = Array.from(document.querySelectorAll('button')).find((item) => {
      const label = (item.textContent || '').trim();
      return ${contains ? "label.includes(" : "label === ("}${JSON.stringify(text)}${contains ? ")" : ")"};
    });
    if (!button || button.disabled) return false;
    button.scrollIntoView({ block: 'center', inline: 'nearest' });
    button.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Enabled button not found: ${text}`);
}

async function selectProject(cdp) {
  await waitForCondition(
    cdp,
    `(() => { const select = document.querySelector('select[aria-label="选择临床研究项目"]'); return Boolean(select && !select.disabled && Array.from(select.options).some((option) => option.value === ${JSON.stringify(projectId)})); })()`,
    45000,
  );
  const changed = await evaluate(cdp, `(() => {
    const select = document.querySelector('select[aria-label="选择临床研究项目"]');
    if (!select) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
    setter.call(select, ${JSON.stringify(projectId)});
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error("Project switcher not found");
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function setField(cdp, label, value) {
  const changed = await evaluate(cdp, `(() => {
    const field = Array.from(document.querySelectorAll('.authoring-field, .authoring-override label, .writing-reference-actions label, .writing-reference-triage-finalize label, .writing-reference-alignment label')).find((item) => {
      const directText = Array.from(item.childNodes).filter((node) => node.nodeType === Node.TEXT_NODE).map((node) => node.textContent || '').join('').trim();
      const heading = item.querySelector(':scope > span')?.textContent || directText;
      return heading.startsWith(${JSON.stringify(label)});
    });
    const input = field?.querySelector('input, textarea, select');
    if (!input) return false;
    const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : input instanceof HTMLSelectElement ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, 'value').set;
    setter.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error(`Field not found: ${label}`);
}

async function toggleChoice(cdp, label) {
  const toggled = await evaluate(cdp, `(() => {
    const choice = Array.from(document.querySelectorAll('.authoring-choice-grid label'))
      .find((item) => (item.textContent || '').trim() === ${JSON.stringify(label)});
    const input = choice?.querySelector('input[type=checkbox]');
    if (!input) return false;
    input.click();
    return true;
  })()`);
  if (!toggled) throw new Error(`Choice not found: ${label}`);
}

async function chooseDesignArchetype(cdp, label) {
  const chosen = await evaluate(cdp, `(() => {
    const option = Array.from(document.querySelectorAll('.authoring-design-archetypes > label'))
      .find((item) => (item.querySelector('strong')?.textContent || '').trim() === ${JSON.stringify(label)});
    const input = option?.querySelector('input[type=radio]');
    if (!input) return false;
    input.click();
    return true;
  })()`);
  if (!chosen) throw new Error(`Design archetype not found: ${label}`);
}

async function setApplicability(cdp, label, status, reason = "") {
  const changed = await evaluate(cdp, `(() => {
    const row = Array.from(document.querySelectorAll('.authoring-applicability-row'))
      .find((item) => (item.querySelector('strong')?.textContent || '').trim() === ${JSON.stringify(label)});
    const select = row?.querySelector('select');
    if (!select || select.disabled) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
    setter.call(select, ${JSON.stringify(status)});
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error(`Applicability selector not available: ${label}`);
  if (status !== "not_applicable") return;
  await waitForCondition(cdp, `Array.from(document.querySelectorAll('.authoring-applicability-row')).some((item) => (item.querySelector('strong')?.textContent || '').trim() === ${JSON.stringify(label)} && Boolean(item.querySelector('textarea'))) `);
  const completed = await evaluate(cdp, `(() => {
    const row = Array.from(document.querySelectorAll('.authoring-applicability-row'))
      .find((item) => (item.querySelector('strong')?.textContent || '').trim() === ${JSON.stringify(label)});
    const textarea = row?.querySelector('textarea');
    const checkbox = row?.querySelector('input[type=checkbox]');
    if (!textarea || !checkbox) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    setter.call(textarea, ${JSON.stringify(reason)});
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    checkbox.click();
    return true;
  })()`);
  if (!completed) throw new Error(`Applicability reason/confirmation unavailable: ${label}`);
}

async function setReferenceFilter(cdp, label, value) {
  const changed = await evaluate(cdp, `(() => {
    const field = Array.from(document.querySelectorAll('.writing-reference-panel label')).find((item) => {
      const ownText = Array.from(item.childNodes)
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent || '')
        .join('')
        .trim();
      return ownText.startsWith(${JSON.stringify(label)});
    });
    const input = field?.querySelector('input, select');
    if (!input) return false;
    const prototype = input instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, 'value').set;
    setter.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error(`Reference filter not found: ${label}`);
}

function assertReadyWorkspaceMetrics(label, state) {
  for (const [viewport, entry] of Object.entries(state)) {
    const current = entry.metrics;
    if (current.pageOverflowX > 0) {
      throw new Error(`${label} has ${current.pageOverflowX}px horizontal overflow at ${viewport}`);
    }
    if (current.incoherentControls.length) {
      throw new Error(`${label} has clipped or zero-size controls at ${viewport}: ${JSON.stringify(current.incoherentControls)}`);
    }
    if (current.aiRailVisible || current.documentMapVisible || current.editorToolbarVisible) {
      throw new Error(`${label} exposes document-only controls before document creation at ${viewport}`);
    }
  }
}

async function runReadyCorpusQc(cdp, report) {
  const workspaceUrl = new URL(
    `/api/projects/${projectId}/medical-writing/references/workspace?snapshot_id=wref_search_3998701372f95ba40d90`,
    appUrl,
  );
  const workspace = await getJson(workspaceUrl);
  const scheduleBrief = (workspace.approved_evidence_briefs || []).find((item) => item.ich_m11_anchor === "schedule");
  const scheduleTranslation = (workspace.translations || []).find((item) => item.translation_id === scheduleBrief?.translation_id);
  if (!scheduleBrief || !scheduleTranslation) throw new Error("Approved schedule evidence is not available in the bound snapshot");

  await waitForCondition(cdp, `(() => {
    const text = document.body.textContent || '';
    return text.includes('语料已就绪')
      && text.includes('准入条件已满足')
      && document.querySelectorAll('.authoring-gate-checklist label.satisfied').length === 5;
  })()`, 45000);
  const gateState = await evaluate(cdp, `(() => {
    const text = document.body.textContent || '';
    return {
      status: document.querySelector('.authoring-gate-status')?.textContent?.trim() || '',
      satisfiedRequirements: document.querySelectorAll('.authoring-gate-checklist label.satisfied').length,
      overrideActive: text.includes('例外放行 · 语料未就绪'),
      writingEntry: text.includes('可以建立版本化方案工作稿'),
    };
  })()`);
  if (gateState.status !== "语料已就绪" || gateState.satisfiedRequirements !== 5 || gateState.overrideActive || !gateState.writingEntry) {
    throw new Error(`Normal corpus gate is not visibly ready: ${JSON.stringify(gateState)}`);
  }

  await setReferenceFilter(cdp, "", "NCT02833350").catch(async () => {
    const changed = await evaluate(cdp, `(() => {
      const input = document.querySelector('.writing-reference-candidate-filters input');
      if (!input) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, 'NCT02833350');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
    if (!changed) throw new Error("Candidate text filter was not found");
  });
  await evaluate(cdp, `(() => {
    const select = document.querySelector('.writing-reference-candidate-filters select');
    if (!select) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
    setter.call(select, 'direct_competitor');
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  await waitForCondition(cdp, `document.querySelectorAll('.writing-reference-list > button').length === 1 && document.body.textContent.includes('NCT02833350')`);
  const selectedCandidate = await evaluate(cdp, `(() => {
    const button = document.querySelector('.writing-reference-list > button');
    if (!button || !(button.textContent || '').includes('NCT02833350')) return false;
    button.click();
    return true;
  })()`);
  if (!selectedCandidate) throw new Error("Filtered direct competitor could not be selected");
  report.states.readyCandidates = await captureViewports(cdp, "01_ready_candidates");
  assertReadyWorkspaceMetrics("ready candidates", report.states.readyCandidates);

  await clickButton(cdp, "文档与解析");
  await waitForCondition(cdp, `(() => {
    const text = document.body.textContent || '';
    return text.includes('Study Protocol and Statistical Analysis Plan')
      && text.includes('cbdcc2215959')
      && text.includes('结构已确认')
      && text.includes('内容匹配');
  })()`);
  report.states.readyDocuments = await captureViewports(cdp, "02_ready_documents");
  assertReadyWorkspaceMetrics("ready documents", report.states.readyDocuments);

  await clickButton(cdp, "译文审核");
  await waitForCondition(cdp, `(() => {
    const text = document.body.textContent || '';
    return Boolean(document.querySelector('.writing-reference-structure-review.approved'))
      && text.includes('m11map_v4')
      && text.includes('2425 个片段');
  })()`, 45000);
  await setReferenceFilter(cdp, "M11结构筛选", "schedule");
  await waitForCondition(cdp, `(() => {
    const options = Array.from(document.querySelectorAll('.writing-reference-span-controls select:last-of-type option'));
    return options.some((item) => item.value === ${JSON.stringify(scheduleTranslation.span_id)});
  })()`, 45000);
  await setReferenceFilter(cdp, "结构化片段", scheduleTranslation.span_id);
  await waitForCondition(cdp, `(() => {
    const source = document.querySelector('.writing-reference-source');
    const text = source?.textContent || '';
    return text.includes(':p141:') && Boolean(document.querySelector('.writing-reference-translation'));
  })()`);
  const translationState = await evaluate(cdp, `(() => ({
    extractionRevision: document.querySelector('.writing-reference-structure-review code')?.textContent?.trim() || '',
    filteredCount: document.querySelector('.writing-reference-span-pager span')?.textContent?.trim() || '',
    sourceLocator: document.querySelector('.writing-reference-source code')?.textContent?.trim() || '',
    sourceText: document.querySelector('.writing-reference-source p')?.textContent?.trim() || '',
    translationText: document.querySelector('.writing-reference-translation p')?.textContent?.trim() || '',
    reviewState: document.querySelector('.writing-reference-review-state')?.textContent?.trim() || '',
  }))()`);
  if (!translationState.extractionRevision.includes("m11map_v4") || !translationState.filteredCount.includes("342")) {
    throw new Error(`Current extraction revision or schedule count is wrong: ${JSON.stringify(translationState)}`);
  }
  if (!translationState.reviewState.includes("医学已批准")) {
    throw new Error(`Selected schedule translation is not visibly medically approved: ${JSON.stringify(translationState)}`);
  }
  report.translationState = translationState;
  report.states.readyTranslation = await captureViewports(cdp, "03_ready_schedule_translation", { focusSelector: ".writing-reference-review" });
  assertReadyWorkspaceMetrics("ready schedule translation", report.states.readyTranslation);

  await clickButton(cdp, "已批准证据");
  await waitForCondition(cdp, `document.querySelectorAll('.writing-reference-brief:not(.invalid)').length === 4`);
  const approvedState = await evaluate(cdp, `(() => ({
    count: document.querySelectorAll('.writing-reference-brief:not(.invalid)').length,
    briefIds: Array.from(document.querySelectorAll('.writing-reference-brief:not(.invalid) code')).map((item) => item.textContent.trim()),
    text: document.querySelector('.writing-reference-view')?.textContent || '',
  }))()`);
  if (!approvedState.text.includes('已批准证据4 条 · 已选 0 条')) {
    throw new Error(`Approved evidence count is not explicit: ${approvedState.text.slice(0, 120)}`);
  }
  for (const anchor of ["eligibility", "objectives_endpoints", "safety", "schedule"]) {
    if (!approvedState.text.includes(anchor)) throw new Error(`Approved evidence view is missing ${anchor}`);
  }
  report.approvedState = approvedState;
  report.states.readyApproved = await captureViewports(cdp, "04_ready_approved_evidence");
  assertReadyWorkspaceMetrics("ready approved evidence", report.states.readyApproved);

  report.normalGate = gateState;
  report.workspaceSummary = {
    snapshotId: workspace.snapshot?.snapshot_id || "",
    artifactCount: workspace.artifacts?.length || 0,
    translationCount: workspace.translations?.length || 0,
    medicalReviewCount: workspace.medical_reviews?.length || 0,
    approvedBriefIds: (workspace.approved_evidence_briefs || []).map((item) => item.brief_id),
  };
}

async function fillStageOne(cdp) {
  await setField(cdp, "研究分期", "II期");
  await setField(cdp, "试验药物", "CMS-RA-201注射液");
  await setField(cdp, "ClinicalTrials.gov疾病检索词", "Rheumatoid Arthritis");
  await clickButton(cdp, "研究目的");
  await toggleChoice(cdp, "首次患者试验（first-in-patient）");
  await toggleChoice(cdp, "机制验证（PoM）");
  await toggleChoice(cdp, "剂量探索");
  await setField(cdp, "关键科学与开发不确定性", "剂量-效应关系\n第12周主要终点评价时点");
  await clickButton(cdp, "竞品范围");
  await setField(cdp, "靶点/作用机制", "靶向炎症通路的全人源单克隆抗体");
  await setField(cdp, "竞品靶点与机制范围", "同靶点、同机制及同治疗线生物制剂");
  await clickButton(cdp, "总体设计");
  await setField(cdp, "总体设计模式", "开放标签、单臂、多中心、剂量递增的早期患者探索研究");
  await setField(cdp, "目标研究人群意图", "既往csDMARD治疗反应不充分的中重度活动性类风湿关节炎成人试验参与者");
}

async function fillStageTwo(cdp) {
  await chooseDesignArchetype(cdp, "随机对照确证性研究");
  const randomizedLock = await evaluate(cdp, `(() => {
    const rows = Array.from(document.querySelectorAll('.authoring-applicability-row'));
    return rows.length === 2 && rows.every((row) => row.querySelector('select')?.disabled);
  })()`);
  if (!randomizedLock) throw new Error("Randomized confirmatory design did not lock comparator and estimand as required");
  await chooseDesignArchetype(cdp, "单臂早期探索");
  await setApplicability(cdp, "对照组设计", "not_applicable", "本研究为无同期对照的单臂剂量递增设计，不设置安慰剂或阳性对照组。");
  const comparatorReasonAccessibility = await evaluate(cdp, `(() => {
    const textarea = document.querySelector('textarea[aria-label="对照组设计不适用理由"]');
    return { reasonLabelPresent: Boolean(textarea) };
  })()`);
  if (!comparatorReasonAccessibility.reasonLabelPresent) {
    throw new Error(`Authoring accessibility contract is not rendered: ${JSON.stringify(comparatorReasonAccessibility)}`);
  }
  const confirmationReset = await evaluate(cdp, `(() => {
    const row = Array.from(document.querySelectorAll('.authoring-applicability-row'))
      .find((item) => (item.querySelector('strong')?.textContent || '').trim() === '对照组设计');
    const textarea = row?.querySelector('textarea');
    const checkbox = row?.querySelector('input[type=checkbox]');
    if (!textarea || !checkbox || !checkbox.checked) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    setter.call(textarea, '本研究仍为无同期对照的单臂剂量递增设计，医学经理已更新不适用理由。');
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  })()`);
  if (!confirmationReset) throw new Error("Comparator applicability confirmation could not be prepared for reset test");
  await waitForCondition(cdp, `!document.querySelector('textarea[aria-label="对照组设计不适用理由"]')?.closest('.authoring-applicability-row')?.querySelector('input[type=checkbox]')?.checked`);
  await chooseDesignArchetype(cdp, "开放标签延展研究");
  const resetAfterArchetypeChange = await evaluate(cdp, `(() => {
    const rows = Array.from(document.querySelectorAll('.authoring-applicability-row'));
    return rows.length === 2
      && rows.every((row) => row.querySelector('select')?.value === 'applicable')
      && rows.every((row) => !row.querySelector('textarea'))
      && document.querySelectorAll('.authoring-applicability-confirm input:checked').length === 0;
  })()`);
  if (!resetAfterArchetypeChange) throw new Error("Changing design archetype retained stale N/A decisions");
  await chooseDesignArchetype(cdp, "单臂早期探索");
  await setApplicability(cdp, "对照组设计", "not_applicable", "本研究为无同期对照的单臂剂量递增设计，不设置安慰剂或阳性对照组。");
  await setApplicability(cdp, "估计目标策略", "not_applicable", "当前阶段以安全性、耐受性、药代动力学和药效学描述性评价为主，不进行组间治疗效应估计。");
  await clickButton(cdp, "研究人群");
  const requiredControlCount = await evaluate(cdp, `document.querySelectorAll('.authoring-field [aria-required="true"]').length`);
  if (requiredControlCount < 3) throw new Error(`Required PICOS controls are missing aria-required metadata: ${requiredControlCount}`);
  await setField(cdp, "目标人群概述", "18至75岁、既往甲氨蝶呤治疗反应不充分的中重度活动性类风湿关节炎成人试验参与者。");
  await setField(cdp, "入选标准模块", "筛选期与基线期满足疾病活动度阈值\n稳定使用背景甲氨蝶呤\n符合妊娠预防与避孕要求");
  await setField(cdp, "排除标准模块", "活动性感染\n近期使用其他生物制剂且未完成洗脱\n存在方案规定的严重心血管、肝脏或肾脏疾病");
  await setField(cdp, "药物/治疗洗脱规则", "既往生物制剂按药代特征和方案规定完成洗脱");
  await clickButton(cdp, "干预措施");
  await setField(cdp, "试验药物干预概述", "CMS-RA-201低剂量组和高剂量组，皮下注射。");
  await setField(cdp, "试验药物剂量与给药方案", "每4周给药一次，持续24周；剂量调整、中断和恢复规则在干预章节单列。");
  await setField(cdp, "必须使用/背景治疗", "稳定剂量甲氨蝶呤\n按方案补充叶酸");
  await setField(cdp, "允许使用的合并用药/治疗", "稳定剂量非甾体抗炎药\n符合方案限制的对乙酰氨基酚");
  await setField(cdp, "限制/禁止使用的合并用药/治疗", "其他生物制剂\nJAK抑制剂\n超出方案剂量的系统性糖皮质激素");
  await setField(cdp, "访视/评价前用药与治疗限制", "疗效评价前24小时限制救援性镇痛药；急救情况除外并完整记录。");
  await clickButton(cdp, "结局指标");
  await setField(cdp, "主要终点及评价时间", "第12周ACR20应答率。");
  await setField(cdp, "关键次要终点", "第12周DAS28-CRP较基线变化\n第12周HAQ-DI较基线变化");
  await setField(cdp, "其他次要终点", "第24周ACR50和ACR70应答率");
  await setField(cdp, "探索性终点", "炎症生物标志物较基线变化");
  await setField(cdp, "安全性终点", "TEAE、SAE及导致停药的AE发生率\n实验室检查、生命体征和心电图变化");
  await setField(cdp, "AESI定义", "严重感染\n超敏反应");
  await clickButton(cdp, "执行与统计");
  await setField(cdp, "研究时期/阶段", "筛选期\n剂量递增治疗期\n安全性随访期");
  await setField(cdp, "访视策略", "筛选、基线，治疗期每4周访视，末次给药后完成安全性随访。");
  await setField(cdp, "样本量策略", "基于安全性暴露、剂量递增决策需要、PK变异度和可解释性确定各队列例数，并预留不能评价试验参与者的替补空间。");
  await setField(cdp, "统计分析策略", "安全性、PK和PD指标按剂量队列进行描述性汇总；剂量递增决策基于预设可评价集和队列级医学审阅。");
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-authoring-journey-qc-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });

  const report = { projectId, appUrl, qcMode, startedAt: new Date().toISOString(), states: {} };
  let cdp;
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    const target = targets.find((item) => item.type === "page");
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await setViewport(cdp, viewports[2]);
    await navigateToApp(cdp);
    await selectProject(cdp);
    await clickButton(cdp, "医学写作");
    await waitForCondition(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`, 45000);
    if (qcMode === "ready") {
      await runReadyCorpusQc(cdp, report);
      report.journey = await getJson(new URL(`/api/projects/${projectId}/medical-writing/authoring-journey`, appUrl));
      if (report.journey.corpus_gate?.readiness_status !== "ready" || !report.journey.corpus_gate?.access_permitted) {
        throw new Error("Backend corpus gate changed during read-only QC");
      }
      report.completedAt = new Date().toISOString();
      await writeFile(path.join(outputDir, "qc_report.json"), JSON.stringify(report, null, 2));
      process.stdout.write(`${JSON.stringify({ outputDir, report: path.join(outputDir, "qc_report.json"), qcMode }, null, 2)}\n`);
      return;
    }
    if (await evaluate(cdp, `Boolean(document.querySelector('.authoring-entry-mode-options'))`)) {
      await clickButton(cdp, "从零开始", { contains: true });
      await waitForCondition(cdp, `Boolean(document.querySelector('.authoring-stage-strip')) && document.body.textContent.includes('方案标题')`, 45000);
    }
    report.states.initial = await captureViewports(cdp, "01_initial_framing");
    assertPreDocumentMetrics("initial framing", report.states.initial);

    await setField(cdp, "方案标题", "CMS-RA-201单臂早期患者探索研究方案（草稿）");
    await clickButton(cdp, "保存草稿");
    await waitForCondition(cdp, `document.body.textContent.includes('草稿已保存，未完成本阶段')`, 30000);
    const framingDraftBeforeReload = await getJson(new URL(`/api/projects/${projectId}/medical-writing/authoring-journey`, appUrl));
    if (framingDraftBeforeReload.framing_complete || framingDraftBeforeReload.search_plan || !framingDraftBeforeReload.framing_draft) {
      throw new Error("Framing draft changed completion state or generated a search plan");
    }
    await navigateToApp(cdp);
    await selectProject(cdp);
    await clickButton(cdp, "医学写作");
    await waitForCondition(cdp, `Boolean(document.querySelector('.authoring-journey-shell')) && document.body.textContent.includes('草稿已保存但尚未完成本阶段')`, 45000);
    const restoredDraftTitle = await evaluate(cdp, `Array.from(document.querySelectorAll('.authoring-field')).find((item) => item.querySelector(':scope > span')?.textContent.startsWith('方案标题'))?.querySelector('input')?.value || ''`);
    if (!restoredDraftTitle.includes("单臂早期患者探索研究方案")) throw new Error("Framing draft was not restored after full navigation");
    report.states.framingDraftReloaded = await captureViewports(cdp, "01b_framing_draft_reloaded");
    assertPreDocumentMetrics("framing draft reloaded", report.states.framingDraftReloaded);

    await fillStageOne(cdp);
    report.states.stage1Filled = await captureViewports(cdp, "02_stage1_filled");
    await clickButton(cdp, "完成第一步");
    await waitForCondition(cdp, `document.querySelector('.authoring-stage-strip button.active')?.textContent.includes('PICOS设计')`, 30000);
    await waitForCondition(cdp, `(() => { const text = document.body.textContent || ''; return text.includes('已检索') || text.includes('公开研究检索未完成'); })()`, 240000);
    const searchOutcome = await evaluate(cdp, `(() => {
      const text = document.body.textContent || '';
      return text.includes('公开研究检索未完成') ? 'failed' : text.includes('已检索') ? 'completed' : 'unknown';
    })()`);
    report.searchOutcome = searchOutcome;
    report.states.stage2Start = await captureViewports(cdp, "03_stage2_start_after_search");
    if (searchOutcome !== "completed") throw new Error("ClinicalTrials.gov search did not complete");

    await fillStageTwo(cdp);
    report.states.stage2Filled = await captureViewports(cdp, "04_stage2_filled");
    await clickButton(cdp, "保存草稿");
    await waitForCondition(cdp, `document.body.textContent.includes('草稿已保存，未完成本阶段')`, 30000);
    const picosDraftBeforeReload = await getJson(new URL(`/api/projects/${projectId}/medical-writing/authoring-journey`, appUrl));
    if (picosDraftBeforeReload.picos_complete || !picosDraftBeforeReload.picos_draft || picosDraftBeforeReload.current_stage !== "picos") {
      throw new Error("PICOS draft advanced the stage or was not persisted");
    }
    await navigateToApp(cdp);
    await selectProject(cdp);
    await clickButton(cdp, "医学写作");
    await waitForCondition(cdp, `Boolean(document.querySelector('.authoring-design-archetypes')) && document.body.textContent.includes('草稿已保存但尚未完成本阶段')`, 45000);
    const restoredApplicability = await evaluate(cdp, `(() => ({
      archetype: document.querySelector('.authoring-design-archetypes input:checked')?.value || '',
      notApplicable: Array.from(document.querySelectorAll('.authoring-applicability-row select')).filter((item) => item.value === 'not_applicable').length,
      confirmed: document.querySelectorAll('.authoring-applicability-confirm input:checked').length,
    }))()`);
    if (restoredApplicability.archetype !== "single_arm_early_phase" || restoredApplicability.notApplicable !== 2 || restoredApplicability.confirmed !== 2) {
      throw new Error(`PICOS applicability draft was not restored: ${JSON.stringify(restoredApplicability)}`);
    }
    report.restoredApplicability = restoredApplicability;
    report.states.picosDraftReloaded = await captureViewports(cdp, "04b_picos_draft_reloaded");
    assertPreDocumentMetrics("PICOS draft reloaded", report.states.picosDraftReloaded);
    await clickButton(cdp, "完成第二步");
    await waitForCondition(cdp, `document.querySelector('.authoring-stage-strip button.active')?.textContent.includes('语料准备')`, 30000);
    await waitForCondition(cdp, `Boolean(document.querySelector('.writing-reference-panel.authoring-mode .writing-reference-list > button'))`, 45000);
    report.states.corpusGate = await captureViewports(cdp, "05_corpus_gate");
    assertPreDocumentMetrics("corpus gate", report.states.corpusGate);
    for (const [viewport, entry] of Object.entries(report.states.corpusGate)) {
      const labels = entry.metrics.gateChecklistLabels;
      if (labels.length !== 5 || labels.some((item) => !item.text || item.height > 72 || item.textWidth < 100)) {
        throw new Error(`corpus gate checklist is not readable at ${viewport}: ${JSON.stringify(labels)}`);
      }
    }

    await setField(cdp, "医学分类理由", "同适应症、同研究分期，作为真实浏览器链路中的直接竞品进入Protocol深度处理。条目仍需后续医学复核。");
    await clickButton(cdp, "标记为直接竞品");
    await waitForCondition(cdp, `document.body.textContent.includes('医学相关性已记录')`, 30000);
    await setField(cdp, "分诊定稿理由", "当前锁定一项直接竞品用于验证正常语料准入链路；其余候选和全部分诊记录继续保留。 ");
    await clickButton(cdp, "锁定竞品篮子");
    await waitForCondition(cdp, `document.body.textContent.includes('已锁定1项直接竞品/间接参照')`, 30000);
    await waitForCondition(cdp, `document.querySelectorAll('.authoring-gate-checklist label.satisfied').length === 1`, 30000);
    report.states.triageFinalized = await captureViewports(cdp, "05b_triage_finalized");

    await navigateToApp(cdp);
    await selectProject(cdp);
    await clickButton(cdp, "医学写作");
    await waitForCondition(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`, 45000);
    await waitForCondition(cdp, `document.querySelector('.authoring-stage-strip button.active')?.textContent.includes('语料准备')`, 30000);
    const reloadState = await evaluate(cdp, `({
      searchSummary: document.querySelector('.authoring-search-plan p')?.textContent || '',
      status: document.querySelector('.authoring-journey-state strong')?.textContent || '',
      revision: document.querySelector('.authoring-journey-state small')?.textContent || '',
    })`);
    report.reloadState = reloadState;
    if (!reloadState.searchSummary.includes("快照")) throw new Error("Search snapshot summary was not restored after reload");

    await evaluate(cdp, `Array.from(document.querySelectorAll('.authoring-gate-checklist input[type=checkbox]')).forEach((item) => item.click())`);
    await setField(cdp, "医学例外放行理由", "仅用于验证从零方案写作产品链路；医学经理已逐项确认并保留全部语料缺口，后续不得作为正式方案批准依据。");
    await clickButton(cdp, "确认缺口并例外放行");
    await waitForCondition(cdp, `document.body.textContent.includes('例外放行 · 语料未就绪')`, 30000);
    report.states.overrideRecorded = await captureViewports(cdp, "06_override_recorded");
    await clickButton(cdp, "进入写作平台");
    await waitForCondition(cdp, `Boolean(document.querySelector('.protocol-editor .ProseMirror'))`, 45000);
    report.states.editor = await captureViewports(cdp, "07_editor_created_from_journey");
    for (const [viewport, entry] of Object.entries(report.states.editor)) {
      if (entry.metrics.pageOverflowX > 0) {
        throw new Error(`document workspace has ${entry.metrics.pageOverflowX}px horizontal overflow at ${viewport}`);
      }
      if (!entry.metrics.aiRailVisible || !entry.metrics.documentMapVisible || !entry.metrics.editorToolbarVisible) {
        throw new Error(`document workspace controls were not restored at ${viewport}`);
      }
    }

    await setViewport(cdp, viewports[0]);
    await navigateToApp(cdp);
    await selectProject(cdp);
    await clickButton(cdp, "医学写作");
    await waitForCondition(cdp, `Boolean(document.querySelector('.rich-editor-shell')) && Boolean(document.querySelector('.writing-ai-core')) && Boolean(document.querySelector('.writing-title-actions')) && Array.from(document.querySelectorAll('.writing-title-actions button')).some((button) => (button.textContent || '').trim() === '目录') && document.querySelector('.working-copy-status-main')?.textContent.includes('绿地候选基线')`, 45000);
    report.states.editorReload = await captureViewports(cdp, "08_editor_reloaded_after_document_creation");
    for (const [viewport, entry] of Object.entries(report.states.editorReload)) {
      const editorReload = entry.metrics;
      if (editorReload.pageOverflowX > 0 || !editorReload.aiRailVisible || !editorReload.documentMapVisible || !editorReload.editorToolbarVisible) {
        throw new Error(`document workspace did not restore after a full-page reload at ${viewport}`);
      }
    }
    if (await evaluate(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`)) {
      throw new Error("full-page reload incorrectly returned a created document to the authoring journey");
    }

    report.journey = await getJson(new URL(`/api/projects/${projectId}/medical-writing/authoring-journey`, appUrl));
    report.document = await getJson(new URL(`/api/projects/${projectId}/medical-writing/greenfield-document`, appUrl));
    report.completedAt = new Date().toISOString();
    await writeFile(path.join(outputDir, "qc_report.json"), JSON.stringify(report, null, 2));
    process.stdout.write(`${JSON.stringify({ outputDir, report: path.join(outputDir, "qc_report.json"), searchOutcome }, null, 2)}\n`);
  } catch (error) {
    report.error = error.stack || error.message;
    if (cdp) {
      report.failureState = await metrics(cdp).catch(() => null);
      report.failureScreenshot = await capture(cdp, "99_failure.png").catch(() => "");
    }
    await writeFile(path.join(outputDir, "qc_report.json"), JSON.stringify(report, null, 2));
    throw error;
  } finally {
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(250);
    await rm(userDataDir, { recursive: true, force: true });
  }
}

await main();
