import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const apiBase = process.env.API_BASE || appUrl;
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(
  __dirname,
  "..",
  "..",
  "records",
  "visual_qc_20260715",
  "medical_writing_m11_registry_runtime",
);
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9394);
const greenfieldProjectId = process.env.GREENFIELD_PROJECT_ID || "proj_ra_greenfield_sandbox";
const referenceProjectId = process.env.REFERENCE_PROJECT_ID || "proj_rux_03_002";
const expectedTemplateId = "ich_m11_zh_cn";
const expectedTemplateVersion = "ich_m11_zh_cn_step4_cde_consultation_2026_06_12_v1";
const expectedTemplateNodeCount = 160;
// Two M11 nodes are deterministically omitted for the randomized,
// non-adaptive fixture; the rendered document and directory therefore contain
// 158 nodes.
const expectedRenderedNodeCount = 158;
const expectedOmittedTemplateNodeIds = ["ich_m11_4_2_6", "ich_m11_10_9"];
const API_CONTRACT_HEADERS = {
  "X-Workbench-Api-Contract": "medical-writing-api-2026-07-17.1",
};
const viewports = [
  { width: 1600, height: 1000 },
  { width: 1920, height: 1080 },
  { width: 2048, height: 1024 },
];

const framing = {
  protocol_id: "CMS-RA-201",
  version: "V0.1",
  document_title: "CMS-RA-201治疗类风湿关节炎的II期临床研究方案",
  indication: "类风湿关节炎",
  clinicaltrials_condition_term: "Rheumatoid Arthritis",
  study_phase: "II期",
  intrinsic_objectives: ["概念验证（PoC）", "剂量探索"],
  investigational_product: "CMS-RA-201注射液",
  product_profile: {
    technology_type: "monoclonal_antibody",
    technology_description: "靶向炎症通路的单克隆抗体",
    administration_routes: ["皮下注射"],
    dosage_forms: ["注射液"],
    exposure_scope: "systemic",
    device_dependency: "none",
    immunogenicity_relevance: "potential",
    pharmacology_considerations: ["靶向炎症通路"],
    safety_considerations: ["严重感染风险", "超敏反应风险"],
    pk_pd_considerations: ["给药间隔内暴露与疗效的关系"],
  },
  structured_design: {
    schema_version: "medical_writing_structured_study_design_v2",
    randomization_mode: "randomized",
    randomization_details: "按中心和基线疾病活动度分层随机",
    blinding_mode: "double_blind",
    blinded_roles: ["受试者", "研究者", "疗效评价者"],
    blinding_details: "试验药与安慰剂外观和给药方式匹配",
    comparator_type: "placebo",
    comparator_intervention: "匹配安慰剂",
    assignment_model: "平行分组，1:1:1分配",
    center_model: "多中心",
    treatment_switch: { planned: false },
    crossover: { planned: false },
    open_label_extension: { planned: false },
    sample_size_reestimation: { planned: false },
    adaptive_design: { planned: false },
    interim_analysis: { planned: false },
    src_planned: false,
    dmc_planned: false,
    arm_or_cohort_kind: "治疗组",
    arm_or_cohort_labels: ["CMS-RA-201低剂量组", "CMS-RA-201高剂量组", "安慰剂组"],
  },
  target_mechanism: "靶向炎症通路的单克隆抗体",
  competitor_target_scope: "同靶点及同机制生物制剂",
  development_regions: ["中国"],
  design_pattern: "随机、双盲、安慰剂对照、平行组、多中心研究",
  population_intent: "既往csDMARD治疗反应不充分的中重度活动性类风湿关节炎成人患者",
  key_uncertainties: ["剂量-效应关系", "第12周主要终点评价时点"],
};

const picos = {
  design_archetype: "randomized_confirmatory",
  population_summary: "18至75岁中重度活动性类风湿关节炎试验参与者。",
  inclusion_modules: ["筛选期与基线期满足疾病活动度阈值", "稳定使用背景甲氨蝶呤"],
  exclusion_modules: ["活动性感染", "近期使用其他生物制剂且未完成洗脱"],
  washout_rules: ["既往生物制剂按药代特征和方案规定完成洗脱"],
  intervention_summary: "CMS-RA-201两个剂量组，皮下注射。",
  intervention_dose_regimen: "每4周给药一次，持续24周。",
  intervention_rules: {
    schema_version: "medical_writing_intervention_rules_v1",
    authority: "structured",
    ip_regimens: [
      {
        regimen_id: "cms-ra-201-low",
        product_name: "CMS-RA-201低剂量",
        product_role: "investigational_product",
        dose_and_frequency: "试验低剂量，每4周一次",
        route: "皮下注射",
        treatment_period: "双盲治疗期24周",
      },
      {
        regimen_id: "cms-ra-201-high",
        product_name: "CMS-RA-201高剂量",
        product_role: "investigational_product",
        dose_and_frequency: "试验高剂量，每4周一次",
        route: "皮下注射",
        treatment_period: "双盲治疗期24周",
      },
      {
        regimen_id: "matched-placebo",
        product_name: "匹配安慰剂",
        product_role: "placebo",
        dose_and_frequency: "每4周一次",
        route: "皮下注射",
        treatment_period: "双盲治疗期24周",
      },
    ],
    ip_adjustment_policy: "no_planned_adjustment",
    no_planned_adjustment_statement: "无计划剂量调整；如发生预设安全性事件，按方案停药规则处理。",
    non_ip_treatment_rules: [
      {
        rule_id: "background-methotrexate",
        rule_class: "background",
        policy: "allowed_if_stable",
        agent_or_category: "稳定剂量甲氨蝶呤",
        phase_applicability: "筛选期至治疗期",
      },
      {
        rule_id: "allowed-folic-acid",
        rule_class: "allowed_cm",
        policy: "allowed",
        agent_or_category: "稳定剂量叶酸",
        phase_applicability: "全研究期",
      },
      {
        rule_id: "prohibited-biologic",
        rule_class: "prohibited_cm",
        policy: "prohibited",
        agent_or_category: "其他生物制剂和JAK抑制剂",
        phase_applicability: "筛选期至治疗期",
      },
    ],
  },
  allowed_concomitant_rules: ["稳定剂量叶酸"],
  required_background_rules: ["稳定剂量甲氨蝶呤"],
  prohibited_concomitant_rules: ["其他生物制剂", "JAK抑制剂"],
  assessment_timing_restrictions: ["疗效评估前限制使用救援性糖皮质激素"],
  comparator_summary: "匹配安慰剂，每4周皮下注射一次。",
  primary_endpoint: "第12周ACR20应答率。",
  key_secondary_endpoints: ["第12周DAS28-CRP较基线变化"],
  other_secondary_endpoints: ["第24周ACR50和ACR70应答率"],
  exploratory_endpoints: ["炎症生物标志物较基线变化"],
  safety_endpoints: ["TEAE、SAE及导致停药的AE发生率"],
  aesi_definitions: ["严重感染", "超敏反应"],
  study_epochs: ["筛选期", "双盲治疗期", "安全性随访期"],
  visit_strategy: "筛选、基线，治疗期每4周访视，末次给药后完成安全性随访。",
  estimand_strategy: "主要估计目标评价治疗策略下第12周ACR20应答差异。",
  sample_size_strategy: "基于预期应答率差异、双侧显著性水平和脱落率估算。",
  statistical_strategy: "主要终点采用分层分析并进行多重性控制。",
};

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function json(url, options) {
  const response = await fetch(url, {
    ...options,
    headers: { ...API_CONTRACT_HEADERS, ...(options?.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}: ${JSON.stringify(payload)}`);
  return payload;
}

// Real-provider workers may commit the durable job just as the isolated API
// process is rotating a connection. Keep this bounded and scoped to the
// real-AI observation path; ordinary fixture failures still fail immediately.
async function jsonEventually(url, options, retryCount = 8) {
  let lastError;
  for (let attempt = 0; attempt <= retryCount; attempt += 1) {
    try {
      return await json(url, options);
    } catch (error) {
      lastError = error;
      if (attempt === retryCount) break;
      await wait(Math.min(1500, 250 * (attempt + 1)));
    }
  }
  throw lastError;
}

async function waitForJson(url, timeoutMs = 10000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await json(url);
    } catch (error) {
      lastError = error;
      await wait(200);
    }
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

function post(pathname, payload) {
  return json(new URL(pathname, appUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function prepareM11Document() {
  let existingJourney = null;
  try {
    existingJourney = await json(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/authoring-journey`, appUrl));
  } catch {
    existingJourney = null;
  }
  try {
    const existing = await json(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/greenfield-document`, appUrl));
    if (existingJourney) {
      return {
        allowed: existingJourney,
        document: { document: { document_id: existing.document_id } },
        reused: true,
      };
    }
  } catch {
    // The project may have a journey but no document yet.
  }
  let created = existingJourney || await post(`/api/projects/${greenfieldProjectId}/medical-writing/authoring-journey`, {
    entry_mode: "guided_greenfield",
    framing,
    actor: "medical_manager_qc",
    idempotency_key: "m11-qc-create-ra-journey",
  });
  if (!created.framing_complete) {
    const framingPreview = await post(`/api/projects/${greenfieldProjectId}/medical-writing/authoring-journey/impact-preview`, {
      expected_revision: created.revision,
      stage: "framing",
      framing,
    });
    created = await post(`/api/projects/${greenfieldProjectId}/medical-writing/authoring-journey/stages/framing/commit`, {
      expected_revision: created.revision,
      stage: "framing",
      framing,
      impact_preview_id: framingPreview.preview_id || framingPreview.payload?.preview_id || "",
      actor: "medical_manager_qc",
      idempotency_key: `m11-qc-commit-ra-framing-${greenfieldProjectId}`,
    });
  }
  const designed = await post(`/api/projects/${greenfieldProjectId}/medical-writing/authoring-journey/stages/picos/commit`, {
    expected_revision: created.revision,
    stage: "picos",
    picos,
    actor: "medical_manager_qc",
    idempotency_key: "m11-qc-commit-ra-picos",
  });
  const missing = designed.corpus_gate?.missing_requirements || [];
  const allowed = await post(`/api/projects/${greenfieldProjectId}/medical-writing/authoring-journey/corpus-gate/override`, {
    expected_revision: designed.revision,
    reason: "浏览器验收中保留全部语料缺口，先验证服务端M11模板与研究事实绑定。",
    acknowledged_missing_requirements: missing,
    actor: "medical_manager_qc",
    idempotency_key: "m11-qc-override-corpus-gate",
  });
  const definition = allowed.study_definition;
  if (!definition) throw new Error("Authoring journey did not produce a StudyDefinition.");
  // A greenfield document is deliberately downstream of an author-confirmed
  // ProtocolAssemblyPlan. Build that plan through the public API so this
  // browser fixture exercises the same fail-closed contract as a user flow.
  const refreshedPlanResult = await post(
    `/api/projects/${greenfieldProjectId}/medical-writing/protocol-assembly-plan/refresh`,
    {
      expected_plan_revision: 0,
      expected_source_definition_id: definition.definition_id,
      expected_source_definition_revision: definition.revision,
      expected_source_definition_sha256: definition.state_sha256,
      actor: "medical_manager_qc",
      idempotency_key: "m11-qc-refresh-assembly-plan",
    },
  );
  const refreshedPlan = refreshedPlanResult.plan || refreshedPlanResult.payload?.plan;
  if (!refreshedPlan) throw new Error("ProtocolAssemblyPlan refresh returned no plan.");
  const confirmedPlanResult = await post(
    `/api/projects/${greenfieldProjectId}/medical-writing/protocol-assembly-plan/confirm`,
    {
      expected_plan_revision: refreshedPlan.revision,
      expected_plan_sha256: refreshedPlan.state_sha256,
      actor: "medical_manager_qc",
      idempotency_key: "m11-qc-confirm-assembly-plan",
    },
  );
  const confirmedPlan = confirmedPlanResult.plan || confirmedPlanResult.payload?.plan;
  if (confirmedPlan?.confirmation_status !== "author_confirmed") {
    throw new Error(`ProtocolAssemblyPlan confirmation failed: ${JSON.stringify(confirmedPlanResult)}`);
  }
  const document = await post(`/api/projects/${greenfieldProjectId}/medical-writing/greenfield-document`, {
    protocol_id: allowed.framing.protocol_id,
    version: allowed.framing.version,
    document_title: allowed.framing.document_title,
    indication: allowed.framing.indication,
    study_phase: allowed.framing.study_phase,
    source_study_definition_id: definition.definition_id,
    source_study_definition_revision: definition.revision,
    source_study_definition_sha256: definition.state_sha256,
    template_id: expectedTemplateId,
    template_version: expectedTemplateVersion,
    actor: "medical_manager_qc",
    idempotency_key: "m11-qc-create-document",
  });
  return { allowed, document, plan: confirmedPlan };
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
    close() {
      ws.close();
    },
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
    await wait(250);
  }
  throw new Error(`Timed out waiting for condition: ${expression}`);
}

async function setViewport(cdp, viewport) {
  await cdp.send("Emulation.setDeviceMetricsOverride", { ...viewport, deviceScaleFactor: 1, mobile: false });
  await evaluate(cdp, `window.scrollTo({ top: 0, left: 0, behavior: "instant" })`);
  await wait(150);
}

async function capture(cdp, filename) {
  const screenshot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const outputPath = path.join(outputDir, filename);
  await writeFile(outputPath, Buffer.from(screenshot.data, "base64"));
  return outputPath;
}

async function captureViewports(cdp, prefix) {
  const screenshots = {};
  for (const viewport of viewports) {
    await setViewport(cdp, viewport);
    const key = `${viewport.width}x${viewport.height}`;
    screenshots[key] = await capture(cdp, `${prefix}_${key}.png`);
  }
  return screenshots;
}

async function selectProject(cdp, projectId) {
  const changed = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Project switcher not found: ${projectId}`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function clickButton(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)});
      if (!button) return false;
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button not found: ${label}`);
}

async function clickSection(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".writing-section-buttons > button"))
        .find((item) => (item.textContent || "").includes(${JSON.stringify(label)}));
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Section button not found: ${label}`);
}

async function appendBrowserReviewMarker(cdp) {
  const prepared = await evaluate(cdp, `
    (() => {
      const root = document.querySelector(".protocol-editor .ProseMirror");
      const block = Array.from(root?.querySelectorAll(".protocol-source-block > p, .protocol-source-block > h1, .protocol-source-block > h2, .protocol-source-block > h3, .protocol-source-block > h4") || [])
        .find((item) => (item.textContent || "").trim().length >= 8);
      if (!root || !block || root.getAttribute("contenteditable") !== "true") return false;
      root.focus();
      const range = document.createRange();
      range.selectNodeContents(block);
      range.collapse(false);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      document.dispatchEvent(new Event("selectionchange", { bubbles: true }));
      return true;
    })()
  `);
  if (!prepared) throw new Error("Editable ProseMirror block not available after creating working copy.");
  await cdp.send("Input.insertText", { text: "（浏览器验收）" });
}

async function selectBrowserText(cdp) {
  const selected = await evaluate(cdp, `
    (() => {
      const root = document.querySelector(".protocol-editor .ProseMirror");
      const block = Array.from(root?.querySelectorAll("p, h1, h2, h3, h4") || [])
        .find((item) => (item.textContent || "").includes("随机化"));
      if (!root || !block) return { ok: false, reason: "design paragraph not found" };
      const text = (block.textContent || "").trim();
      if (text.length < 12) return { ok: false, reason: "design paragraph too short", text };
      root.focus();
      const range = document.createRange();
      const preferred = ${JSON.stringify(process.env.REAL_AI_SELECTION_MODE || "marker")} === "full"
        ? text
        : (text.includes("浏览器验收") ? "浏览器验收" : text);
      const startOffset = text.indexOf(preferred);
      if (startOffset < 0) return { ok: false, reason: "selection target not found", text };
      const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
      let cursor = 0;
      let startNode = null;
      let endNode = null;
      let startNodeOffset = 0;
      let endNodeOffset = 0;
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const nextCursor = cursor + (node.nodeValue || "").length;
        if (!startNode && startOffset >= cursor && startOffset <= nextCursor) {
          startNode = node;
          startNodeOffset = startOffset - cursor;
        }
        const endOffset = startOffset + preferred.length;
        if (endOffset >= cursor && endOffset <= nextCursor) {
          endNode = node;
          endNodeOffset = endOffset - cursor;
          break;
        }
        cursor = nextCursor;
      }
      if (!startNode || !endNode) return { ok: false, reason: "selection range could not be resolved", text, preferred };
      range.setStart(startNode, startNodeOffset);
      range.setEnd(endNode, endNodeOffset);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      document.dispatchEvent(new Event("selectionchange", { bubbles: true }));
      block.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, view: window }));
      return { ok: true, text: (selection.toString() || range.toString()).trim(), blockText: text, preferred };
    })()
  `);
  if (!selected?.ok || !selected.text) {
    throw new Error(`Unable to select a real editor range: ${JSON.stringify(selected)}`);
  }
  await waitForCondition(cdp, `
    (() => {
      const selected = document.querySelector(".selected-text span")?.textContent || "";
      return selected.includes("浏览器验收") || selected.length >= 12;
    })()
  `, 10000);
  return selected;
}

async function setControlledValue(cdp, selector, value) {
  const changed = await evaluate(cdp, `
    (() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element) return false;
      const prototype = element instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
      if (!setter) return false;
      setter.call(element, ${JSON.stringify(value)});
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Controlled field not found: ${selector}`);
}

async function runRealAiFlow(cdp, sectionId) {
  const gateway = await json(new URL("/api/ai-gateway/status", appUrl));
  const roleSettings = await json(new URL("/api/ai-gateway/settings", appUrl));
  const independentRole = (roleSettings.roles || []).find((role) => role.role_id === "independent_ai") || null;
  const route = {
    configured: Boolean(gateway.configured),
    semanticAiTasksEnabled: Boolean(gateway.semantic_ai_tasks_enabled),
    provider: gateway.provider || independentRole?.provider || null,
    model: gateway.model || independentRole?.model || null,
    transport: gateway.transport || null,
    deploymentProfile: gateway.deployment_profile || null,
    roleCurrentRunnable: independentRole?.current_runnable ?? null,
    roleConfigured: independentRole?.role_configured ?? null,
    routeValidationErrors: gateway.route_validation_errors || [],
  };
  if (!route.configured || !route.semanticAiTasksEnabled || route.routeValidationErrors.length || independentRole && independentRole.current_runnable === false) {
    throw new Error(`Independent AI route is not runnable: ${JSON.stringify(route)}`);
  }

  const selection = await selectBrowserText(cdp);
  const instruction = "请仅对本次选中文字做专业医学中文润色，保持随机化、双盲、安慰剂对照、研究阶段、时间点及其他受保护研究事实和术语不变；改善句式和可读性，不补造未提供的事实。";
  await setControlledValue(cdp, ".revision-form textarea", instruction);
  await waitForCondition(cdp, `document.querySelector(".revision-form textarea")?.value === ${JSON.stringify(instruction)}`, 10000);

  const initialThreadCount = (await json(new URL(`/api/projects/${greenfieldProjectId}/revision-threads`, appUrl))).length;
  const submitted = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".revision-form button"))
        .find((item) => (item.textContent || "").trim() === "提交AI修订");
      if (!button || button.disabled) return { ok: false, disabled: button?.disabled ?? null, title: button?.title || "" };
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return { ok: true };
    })()
  `);
  if (!submitted?.ok) throw new Error(`Real AI submit button unavailable: ${JSON.stringify(submitted)}`);
  await waitForCondition(cdp, `document.body.innerText.includes("AI修订已提交") || document.body.innerText.includes("处理中")`, 15000);

  const realAiTimeout = Number(process.env.REAL_AI_TIMEOUT_MS || 600000);
  const initialJobLocator = await (async () => {
    const started = Date.now();
    while (Date.now() - started < 15000) {
      const locator = await evaluate(cdp, `(() => {
        try { return JSON.parse(localStorage.getItem(${JSON.stringify(`mw_revision_job_${greenfieldProjectId}`)}) || "null"); }
        catch { return null; }
      })()`);
      if (locator?.job_id) return locator;
      await wait(250);
    }
    return null;
  })();
  if (!initialJobLocator?.job_id) throw new Error("Real AI submit returned no durable job locator in the browser session.");
  let durableStatus = null;
  const jobWaitStarted = Date.now();
  while (Date.now() - jobWaitStarted < realAiTimeout) {
    durableStatus = await jsonEventually(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/jobs/${initialJobLocator.job_id}`, apiBase));
    if (["completed", "failed", "cancelled"].includes(durableStatus.status)) break;
    await wait(1500);
  }
  if (!durableStatus || !["completed", "failed", "cancelled"].includes(durableStatus.status)) {
    throw new Error(`Real AI durable job did not reach terminal state: ${JSON.stringify({ jobId: initialJobLocator.job_id, durableStatus })}`);
  }
  if (durableStatus.status !== "completed") {
    throw new Error(`Real AI durable job ended ${durableStatus.status}: ${durableStatus.error_summary || "no error summary"}`);
  }
  // Reconcile the completed domain artifact in the same visible browser
  // session before trying any candidate button.  This keeps the proof at the
  // user-facing boundary even when a React render is delayed after the worker
  // commit.
  await evaluate(cdp, `(() => {
    const button = Array.from(document.querySelectorAll(".revision-thread-head button"))
      .find((item) => (item.textContent || "").trim() === "刷新");
    if (!button || button.disabled) return false;
    button.click();
    return true;
  })()`);
  let candidateDiagnostics = null;
  try {
    await waitForCondition(cdp, `document.querySelectorAll(".writing-ai-candidates article").length > 0`, 30000);
  } catch (error) {
    candidateDiagnostics = await evaluate(cdp, `(() => ({
      message: Array.from(document.querySelectorAll(".revision-message")).map((item) => item.innerText).filter(Boolean),
      progress: document.querySelector(".revision-progress")?.innerText || "",
      candidates: document.querySelectorAll(".writing-ai-candidates article").length,
      buttons: Array.from(document.querySelectorAll(".writing-ai-candidates button")).map((item) => ({ text: item.innerText, disabled: item.disabled })),
      bodyTail: (document.body.innerText || "").slice(-3000),
    }))()`);
    throw new Error(`${error.message}; real AI diagnostics=${JSON.stringify(candidateDiagnostics)}`);
  }

  let threadSnapshot = await jsonEventually(new URL(`/api/projects/${greenfieldProjectId}/revision-threads`, apiBase));
  let candidateArticles = await evaluate(cdp, `Array.from(document.querySelectorAll(".writing-ai-candidates article")).map((article) => ({
    text: article.innerText,
    buttons: Array.from(article.querySelectorAll("button")).map((button) => ({ text: button.innerText, disabled: button.disabled })),
  }))`);
  let thread = threadSnapshot.find((item) => item.status === "candidate_ready") || threadSnapshot[threadSnapshot.length - 1] || null;
  if (!thread) throw new Error(`Real AI returned no revision thread: ${JSON.stringify(threadSnapshot)}`);
  let pendingSuggestion = (thread.suggestions || []).find((item) => item.user_decision === "pending") || null;
  if (!pendingSuggestion) throw new Error(`Real AI thread returned no pending suggestion: ${JSON.stringify(thread)}`);

  let rewriteAttempted = false;
  let rewriteThreadId = null;
  let rewriteSuggestionId = null;
  let adopted = await evaluate(cdp, `
    (() => {
      const article = Array.from(document.querySelectorAll(".writing-ai-candidates article"))[0];
      const button = Array.from(article?.querySelectorAll("button") || [])
        .find((item) => (item.textContent || "").trim() === "选用并写入");
      if (!button || button.disabled) return { ok: false, disabled: button?.disabled ?? null, title: button?.title || "" };
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return { ok: true };
    })()
  `);
  // A real provider may conservatively flag a candidate that adds project
  // identifiers to a short selection.  Use the visible same-thread rewrite
  // action once, with an explicit no-new-facts instruction, then re-evaluate
  // the new turn.  This is a bounded proof of the product's fail-closed
  // selected-text rewrite path; it never retries the initial durable job.
  if (!adopted?.ok && String(adopted.title || "").includes("受保护医学标识")) {
    rewriteAttempted = true;
    await setControlledValue(
      cdp,
      ".revision-current-action textarea:nth-of-type(1)",
      "首轮候选新增了源选区未包含的项目标识，医学反馈：不得新增任何数字、单位、缩写、受控术语、研究阶段、适应症或产品名称；仅保留源选区事实。",
    );
    await setControlledValue(
      cdp,
      ".revision-current-action textarea:nth-of-type(2)",
      "请基于首轮候选重写，仅输出与源选区事实集合完全一致的自然中文；不得新增、删除或改变数字、单位、缩写、受控术语、研究阶段、适应症、产品名称及时间点。若无法安全润色，原样返回源选区。",
    );
    const rewriteClicked = await evaluate(cdp, `
      (() => {
        const button = Array.from(document.querySelectorAll(".revision-current-action button"))
          .find((item) => (item.textContent || "").trim() === "生成下一轮");
        if (!button || button.disabled) return { ok: false, disabled: button?.disabled ?? null, title: button?.title || "" };
        button.scrollIntoView({ block: "center", inline: "nearest" });
        button.click();
        return { ok: true };
      })()
    `);
    if (!rewriteClicked?.ok) throw new Error(`Same-thread real AI rewrite button unavailable: ${JSON.stringify(rewriteClicked)}`);
    await waitForCondition(cdp, `document.body.innerText.includes("AI按反馈生成新一轮候选中") || document.body.innerText.includes("处理中")`, 15000);
    await waitForCondition(cdp, `Array.from(document.querySelectorAll(".revision-turn[data-turn-number]")).some((item) => Number(item.getAttribute("data-turn-number")) >= 2)`, realAiTimeout);
    threadSnapshot = await jsonEventually(new URL(`/api/projects/${greenfieldProjectId}/revision-threads`, apiBase));
    thread = threadSnapshot.find((item) => item.thread_id === thread.thread_id) || threadSnapshot[threadSnapshot.length - 1] || thread;
    pendingSuggestion = (thread.suggestions || []).find((item) => item.user_decision === "pending" && Number(item.turn_number || 0) >= 2)
      || (thread.suggestions || []).find((item) => item.user_decision === "pending")
      || null;
    rewriteThreadId = thread.thread_id;
    rewriteSuggestionId = pendingSuggestion?.suggestion_id || null;
    candidateArticles = await evaluate(cdp, `Array.from(document.querySelectorAll(".writing-ai-candidates article")).map((article) => ({
      text: article.innerText,
      buttons: Array.from(article.querySelectorAll("button")).map((button) => ({ text: button.innerText, disabled: button.disabled })),
    }))`);
    adopted = await evaluate(cdp, `
      (() => {
        const articles = Array.from(document.querySelectorAll(".writing-ai-candidates article"));
        const article = articles.find((item) => Array.from(item.querySelectorAll("button"))
          .some((button) => (button.textContent || "").trim() === "选用并写入" && !button.disabled));
        const button = Array.from(article?.querySelectorAll("button") || [])
          .find((item) => (item.textContent || "").trim() === "选用并写入");
        if (!button || button.disabled) return { ok: false, disabled: button?.disabled ?? null, title: button?.title || "" };
        button.scrollIntoView({ block: "center", inline: "nearest" });
        button.click();
        return { ok: true };
      })()
    `);
  }
  const wcBefore = await jsonEventually(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/working-copies/${sectionId}`, apiBase));
  const beforeRevision = Number(wcBefore.revision || 0);
  if (!adopted?.ok) throw new Error(`Real AI candidate adoption button unavailable: ${JSON.stringify({ adopted, candidateArticles, thread: { threadId: thread.thread_id, suggestions: thread.suggestions } })}`);
  await waitForCondition(cdp, `document.body.innerText.includes("已选用并写入工作副本版本")`, 30000);
  const wcAfter = await jsonEventually(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/working-copies/${sectionId}`, apiBase));
  const appliedThreadSnapshot = await jsonEventually(new URL(`/api/projects/${greenfieldProjectId}/revision-threads`, apiBase));
  const appliedThread = appliedThreadSnapshot.find((item) => item.thread_id === thread.thread_id) || null;
  const appliedSuggestion = appliedThread?.suggestions?.find((item) => item.suggestion_id === pendingSuggestion.suggestion_id) || null;
  const persistedText = (wcAfter.content_blocks || []).map((block) => String(block.text || "")).join("\\n");
  const selectedTextStillPresent = persistedText.includes(String(appliedSuggestion?.proposal_text || ""));
  if (Number(wcAfter.revision || 0) <= beforeRevision) {
    throw new Error(`Atomic adoption did not advance working-copy revision: ${beforeRevision} -> ${wcAfter.revision}`);
  }
  if (appliedSuggestion?.user_decision !== "accepted") {
    throw new Error(`Atomic adoption did not persist author decision: ${JSON.stringify(appliedSuggestion)}`);
  }
  if (!selectedTextStillPresent) {
    throw new Error("Atomic adoption response and working-copy readback do not contain the selected candidate text.");
  }
  const finalJobRecords = await json(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/jobs`, appUrl)).catch(() => null);
  return {
    route,
    selection,
    initialJobId: initialJobLocator.job_id,
    initialJobStatus: durableStatus.status,
    initialJobAttemptCount: durableStatus.attempt_count,
    initialThreadCount,
    candidateThreadCount: threadSnapshot.length,
    threadId: thread.thread_id,
    suggestionId: pendingSuggestion.suggestion_id,
    candidateCount: thread.suggestions?.length || 0,
    candidateArticles,
    rewriteAttempted,
    rewriteThreadId,
    rewriteSuggestionId,
    workingCopyBeforeRevision: beforeRevision,
    workingCopyAfterRevision: Number(wcAfter.revision || 0),
    workingCopyId: wcAfter.working_copy_id,
    appliedDecision: appliedSuggestion?.user_decision || null,
    appliedProposalText: appliedSuggestion?.proposal_text || null,
    persistedTextContainsCandidate: selectedTextStillPresent,
    durableJobRecords: Array.isArray(finalJobRecords) ? finalJobRecords.length : null,
    candidateDiagnostics,
  };
}

async function openDocumentMap(cdp) {
  await clickButton(cdp, "目录");
  await waitForCondition(cdp, `Boolean(document.querySelector(".writing-document-map-drawer"))`);
}

async function openWriting(cdp, projectId) {
  await selectProject(cdp, projectId);
  await clickButton(cdp, "医学写作");
  await waitForCondition(cdp, `
    document.body.textContent.includes("研究方案文档编辑与AI修订")
      || document.body.textContent.includes("研究方案智能设计与写作")
  `);
}

async function pageMetrics(cdp) {
  return evaluate(cdp, `
    (() => {
      const editor = document.querySelector(".writing-editor-core")?.getBoundingClientRect();
      const ai = document.querySelector(".writing-ai-core")?.getBoundingClientRect();
      return {
        noPageOverflowX: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) <= window.innerWidth + 1,
        editorAiOrder: Boolean(editor && ai && editor.left < ai.left),
        editorAndAiAligned: Boolean(editor && ai && Math.abs(editor.top - ai.top) <= 24),
        documentMapNotResident: !document.querySelector(".writing-document-map-drawer"),
        hasEditor: Boolean(document.querySelector(".protocol-editor .ProseMirror")),
        sectionButtonCount: document.querySelectorAll(".writing-section-buttons > button").length,
      };
    })()
  `);
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const template = await json(new URL(
    `/api/medical-writing/protocol-templates/${expectedTemplateId}/${expectedTemplateVersion}`,
    appUrl,
  ));
  const userDataDir = await mkdtemp(path.join(tmpdir(), "medical-writing-m11-qc-"));
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
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    const target = targets.find((item) => item.type === "page");
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Chrome page target found.");
    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await setViewport(cdp, viewports[0]);
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);

    let referenceSession = null;
    let referenceScreenshots = {};
    if (process.env.SKIP_REFERENCE_PROJECT !== "1") {
      await openWriting(cdp, referenceProjectId);
      await waitForCondition(cdp, `Boolean(document.querySelector(".protocol-editor .ProseMirror"))`);
      referenceSession = await json(new URL(`/api/projects/${referenceProjectId}/medical-writing/document-session`, appUrl));
      referenceScreenshots = await captureViewports(cdp, "reference_docx_unchanged");
    }

    const prepared = await prepareM11Document();
    const preflightSession = await json(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/document-session`, appUrl));
    const preflightNodeIds = new Set((preflightSession.sections || []).map((item) => item.template_node_id));
    const omittedTemplateNodeIds = (template.nodes || [])
      .map((item) => item.node_id)
      .filter((item) => !preflightNodeIds.has(item));
    await writeFile(
      path.join(outputDir, "m11_preflight_structure.json"),
      JSON.stringify({
        templateNodeCount: template.nodes?.length || 0,
        sessionSectionCount: preflightSession.sections?.length || 0,
        omittedTemplateNodeIds,
        sectionTemplateNodeIds: preflightSession.sections?.map((item) => item.template_node_id) || [],
      }, null, 2),
      "utf8",
    );
    await openWriting(cdp, greenfieldProjectId);
    await openDocumentMap(cdp);
    try {
      await waitForCondition(cdp, `document.querySelectorAll(".writing-section-buttons > button").length === ${expectedRenderedNodeCount}`);
    } catch (error) {
      const diagnostics = await evaluate(cdp, `(() => ({
        bodyText: (document.body.innerText || "").slice(0, 5000),
        mapOpen: Boolean(document.querySelector(".writing-document-map-drawer")),
        mapButtonCount: document.querySelectorAll(".writing-section-buttons > button").length,
        mapText: document.querySelector(".writing-document-map-drawer")?.innerText || "",
        sectionTitle: document.querySelector(".writing-editor-core h2")?.innerText || "",
        url: location.href,
      }))()`);
      await capture(cdp, "m11_section_map_timeout.png");
      throw new Error(`${error.message}; diagnostics=${JSON.stringify(diagnostics)}`);
    }
    const session = await json(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/document-session`, appUrl));
    const state = await json(new URL(`/api/projects/${greenfieldProjectId}/medical-writing/greenfield-document`, appUrl));

    const synopsisSummary = session.sections.find((item) => item.template_node_id === "ich_m11_1_1");
    const designSummary = session.sections.find((item) => item.template_node_id === "ich_m11_4_1");
    const synopsis = await json(new URL(
      `/api/projects/${greenfieldProjectId}/medical-writing/document-session/sections/${synopsisSummary.section_id}`,
      appUrl,
    ));
    const design = await json(new URL(
      `/api/projects/${greenfieldProjectId}/medical-writing/document-session/sections/${designSummary.section_id}`,
      appUrl,
    ));

    await clickSection(cdp, "方案摘要");
    try {
      await waitForCondition(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.innerText?.includes("CMS-RA-201治疗类风湿关节炎的II期临床研究方案")`);
    } catch (error) {
      const diagnostics = await evaluate(cdp, `(() => ({
        editorText: document.querySelector(".protocol-editor .ProseMirror")?.innerText || "",
        editorShell: document.querySelector(".writing-editor-core")?.innerText?.slice(0, 4000) || "",
        selectedButton: document.querySelector(".writing-section-buttons button.active")?.innerText || "",
        url: location.href,
      }))()`);
      await capture(cdp, "m11_synopsis_timeout.png");
      throw new Error(`${error.message}; diagnostics=${JSON.stringify(diagnostics)}`);
    }
    const synopsisUi = await evaluate(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.innerText || ""`);
    const synopsisScreenshots = await captureViewports(cdp, "m11_1_1_synopsis");

    await openDocumentMap(cdp);
    await clickSection(cdp, "试验设计描述");
    try {
      await waitForCondition(cdp, `(() => { const text = document.querySelector(".protocol-editor .ProseMirror")?.innerText || ""; return text.includes("随机化") && text.includes("双盲") && text.includes("安慰剂对照"); })()`);
    } catch (error) {
      const diagnostics = await evaluate(cdp, `(() => ({
        editorText: document.querySelector(".protocol-editor .ProseMirror")?.innerText || "",
        editorShell: document.querySelector(".writing-editor-core")?.innerText?.slice(0, 3500) || "",
        selectedSection: document.querySelector(".writing-editor-core .rich-editor-meta")?.innerText || "",
        url: location.href,
      }))()`);
      await capture(cdp, "m11_design_timeout.png");
      throw new Error(`${error.message}; diagnostics=${JSON.stringify(diagnostics)}`);
    }
    const designUi = await evaluate(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.innerText || ""`);

    // A draft Word export is intentionally gated on a saved working copy. Use
    // the visible author controls so the browser flow covers the same
    // AI-first review boundary a medical manager would use before export.
    await clickButton(cdp, "创建工作副本");
    await waitForCondition(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.getAttribute("contenteditable") === "true"`);
    await appendBrowserReviewMarker(cdp);
    try {
      await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("有未保存修订")`);
    } catch (error) {
      const diagnostics = await evaluate(cdp, `(() => ({
        status: document.querySelector(".working-copy-status-main")?.innerText || "",
        buttons: Array.from(document.querySelectorAll(".working-copy-actions button")).map((item) => ({ text: item.innerText, disabled: item.disabled, title: item.title })),
        messages: Array.from(document.querySelectorAll(".working-copy-message, .approval-lock")).map((item) => item.innerText).filter(Boolean),
      }))()`);
      await capture(cdp, "m11_create_working_copy_timeout.png");
      throw new Error(`${error.message}; diagnostics=${JSON.stringify(diagnostics)}`);
    }
    await clickButton(cdp, "保存工作副本");
    await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("已保存")`);

    const viewportMetrics = {};
    for (const viewport of viewports) {
      await setViewport(cdp, viewport);
      viewportMetrics[`${viewport.width}x${viewport.height}`] = await pageMetrics(cdp);
    }
    const editorScreenshots = await captureViewports(cdp, "m11_4_1_design");
    const draftResponse = await fetch(
      new URL(`/api/projects/${greenfieldProjectId}/medical-writing/document.docx?mode=draft_preview`, appUrl),
      { headers: API_CONTRACT_HEADERS },
    );
    const draftBytes = new Uint8Array(await draftResponse.arrayBuffer());
    await writeFile(path.join(outputDir, "m11_greenfield_draft_preview.docx"), draftBytes);

    let realAi = null;
    let realAiError = "";
    if (process.env.RUN_REAL_AI === "1") {
      try {
        realAi = await runRealAiFlow(cdp, designSummary.section_id);
      } catch (error) {
        realAiError = error.stack || error.message;
      }
    }

    // Export a second receipt only after the real browser has visibly adopted
    // a candidate. This keeps the Word gate tied to the persisted working-copy
    // revision rather than the pre-AI draft export.
    let postAdoptionDraftResponse = null;
    let postAdoptionDraftBytes = null;
    if (realAi?.appliedDecision === "accepted") {
      await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("已保存")`, 30000);
      postAdoptionDraftResponse = await fetch(
        new URL(`/api/projects/${greenfieldProjectId}/medical-writing/document.docx?mode=draft_preview`, appUrl),
        { headers: API_CONTRACT_HEADERS },
      );
      postAdoptionDraftBytes = new Uint8Array(await postAdoptionDraftResponse.arrayBuffer());
      await writeFile(path.join(outputDir, "m11_greenfield_post_adoption_draft_preview.docx"), postAdoptionDraftBytes);
    }

    const dose = session.sections.find((item) => item.template_node_id === "ich_m11_6_4");
    const concomitant = session.sections.find((item) => item.template_node_id === "ich_m11_6_10");
    const failures = [];
    if (realAiError) failures.push(`real-ai:${realAiError}`);
    if (template.template_id !== expectedTemplateId) failures.push("template:id");
    if (template.template_version !== expectedTemplateVersion) failures.push("template:version");
    if (template.nodes?.length !== expectedTemplateNodeCount) failures.push("template:nodeCount");
    if (!/^[a-f0-9]{64}$/.test(template.definition_sha256 || "")) failures.push("template:digest");
    if (session.sections?.length !== expectedRenderedNodeCount) failures.push("session:sectionCount");
    if (session.template_id !== expectedTemplateId || session.template_version !== expectedTemplateVersion) failures.push("session:templateIdentity");
    if (session.template_definition_sha256 !== template.definition_sha256) failures.push("session:templateDigest");
    if (omittedTemplateNodeIds.join("|") !== expectedOmittedTemplateNodeIds.join("|")) failures.push("session:unexpectedApplicabilityOmissions");
    if (!synopsis?.content_blocks?.some((block) => (block.source_fact_ids || []).length)) failures.push("session:synopsisProjection");
    if (!design?.content_blocks?.some((block) => (block.source_fact_ids || []).length)) failures.push("session:designProjection");
    if (!synopsisUi.includes("类风湿关节炎")) failures.push("ui:synopsisProjection");
    if (!(designUi.includes("随机化") && designUi.includes("双盲") && designUi.includes("安慰剂对照"))) failures.push("ui:designProjection");
    if (!dose?.interaction_types?.includes("dose_modification_rule_builder")) failures.push("session:doseBoundary");
    if (!concomitant?.interaction_types?.includes("concomitant_therapy_rule_builder")) failures.push("session:concomitantBoundary");
    if (dose?.interaction_types?.join("|") === concomitant?.interaction_types?.join("|")) failures.push("session:boundaryCollision");
    if (referenceSession?.status === "greenfield_candidate") failures.push("reference:sourceModeChanged");
    if (prepared.document.document?.document_id !== state.document_id) failures.push("journey:documentIdentity");
    if (!draftResponse.ok || draftBytes.length < 1000) failures.push("export:draftWord");
    for (const [key, metrics] of Object.entries(viewportMetrics)) {
      if (!metrics.noPageOverflowX) failures.push(`viewport:${key}:overflowX`);
      if (!metrics.editorAiOrder) failures.push(`viewport:${key}:columnOrder`);
      if (!metrics.editorAndAiAligned) failures.push(`viewport:${key}:alignment`);
      if (!metrics.documentMapNotResident) failures.push(`viewport:${key}:directoryResident`);
      if (!metrics.hasEditor) failures.push(`viewport:${key}:editor`);
      if (metrics.sectionButtonCount !== 0) failures.push(`viewport:${key}:closedDirectoryButtons`);
    }

    const report = {
      template: {
        templateId: template.template_id,
        templateVersion: template.template_version,
        authority: template.authority,
        definitionSha256: template.definition_sha256,
        nodeCount: template.nodes?.length,
      },
      reference: {
        projectId: referenceProjectId,
        documentId: referenceSession?.document_id || null,
        status: referenceSession?.status || "not_loaded_in_clean_runtime",
        templateVersion: referenceSession?.template_version || null,
      },
      greenfield: {
        projectId: greenfieldProjectId,
        createdDocumentId: prepared.document.document?.document_id,
        stateDocumentId: state.document_id,
        documentId: session.document_id,
        status: session.status,
        sectionCount: session.sections.length,
        templateId: session.template_id,
        templateVersion: session.template_version,
        templateDefinitionSha256: session.template_definition_sha256,
        draftWordBytes: draftBytes.length,
        postAdoptionDraftWordBytes: postAdoptionDraftBytes?.length || null,
        postAdoptionDraftResponseOk: postAdoptionDraftResponse?.ok ?? null,
      },
      projections: { synopsisUi, designUi },
      semanticBoundaries: {
        doseModification: dose?.interaction_types || [],
        concomitantMedication: concomitant?.interaction_types || [],
      },
      independentAi: realAi || { enabled: process.env.RUN_REAL_AI === "1", error: realAiError || null },
      structure: {
        registeredTemplateNodeCount: template.nodes?.length || 0,
        renderedSectionCount: session.sections?.length || 0,
        omittedTemplateNodeIds,
      },
      viewports: viewportMetrics,
      screenshots: { referenceScreenshots, synopsisScreenshots, editorScreenshots },
      failures,
    };
    await writeFile(path.join(outputDir, "qc_report.json"), JSON.stringify(report, null, 2), "utf8");
    cdp.close();
    if (failures.length) throw new Error(`M11 registry QC failed: ${failures.join(", ")}`);
  } finally {
    chrome.kill("SIGTERM");
    await wait(500);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
