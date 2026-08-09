// Final-matrix child QC: parameterized by SCENARIO_ID env var.
// Drives the full AI-first Protocol path from minimal facts to complete draft,
// exercises document map, synopsis/design projections, selected-text AI
// revision, candidate review, save/reload, export, and records evidence.
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SCENARIOS } from "./final_matrix_scenarios.mjs";
import { terminateProcessGroup } from "./final_matrix_process.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const apiBase = process.env.API_BASE || appUrl;
const outputDir = process.env.QC_OUTPUT_DIR || path.join(__dirname, "..", "..", "records", "active_slices", "medical_writing_authoring_journey_20260715", "browser_qc", "final_matrix");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9394);
let projectId = process.env.GREENFIELD_PROJECT_ID || "";
const scenarioId = process.env.SCENARIO_ID || "ra_p2";
const role = process.env.MATRIX_ROLE || "engineer";
const scenario = SCENARIOS[scenarioId];
if (!scenario) throw new Error(`Unknown scenario: ${scenarioId}`);

const expectedTemplateId = "ich_m11_zh_cn";
const expectedTemplateVersion = "ich_m11_zh_cn_step4_cde_consultation_2026_06_12_v1";
const expectedTemplateNodeCount = 160;
const API_CONTRACT_HEADERS = { "X-Workbench-Api-Contract": "medical-writing-api-2026-07-17.1" };
const viewports = [
  { width: 1920, height: 1080 },
  { width: 1600, height: 1000 },
  { width: 2048, height: 1024 },
];

// Only populated when CDP_TRACE=1. This keeps normal matrix runs unchanged
// while allowing a failed browser reconciliation to carry terminal response
// evidence into its fatal report.
let activeCdp = null;
let lastBrowserFetchTrace = [];
let userFlowLedger = [];

function wait(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function json(url, options) {
  const response = await fetch(url, { ...options, headers: { ...API_CONTRACT_HEADERS, ...(options?.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`HTTP ${response.status} ${url.pathname}: ${JSON.stringify(payload).slice(0, 500)}`);
  return payload;
}

async function jsonEventually(url, options, retryCount = 8) {
  for (let i = 0; i < retryCount; i++) {
    try { return await json(url, options); }
    catch (error) { if (i === retryCount - 1) throw error; await wait(1500); }
  }
}

async function post(pathname, payload) {
  return json(new URL(pathname, apiBase), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// --- Document preparation (API-driven, same contract as user flow) ---
async function prepareDocument() {
  const framing = scenario.framing;
  const picos = scenario.picos;
  // The orchestrator creates the project with entry_mode "from_zero", which
  // auto-creates a journey. GET it first; only POST if absent.
  let created = null;
  try {
    created = await json(new URL(`/api/projects/${projectId}/medical-writing/authoring-journey`, appUrl));
  } catch {
    created = await post(`/api/projects/${projectId}/medical-writing/authoring-journey`, {
      entry_mode: "guided_greenfield", framing, actor: "final_matrix_qc",
      idempotency_key: `fm-${scenarioId}-${role}-journey`,
    });
  }
  if (!created.framing_complete) {
    const preview = await post(`/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`, {
      expected_revision: created.revision, stage: "framing", framing,
    });
    created = await post(`/api/projects/${projectId}/medical-writing/authoring-journey/stages/framing/commit`, {
      expected_revision: created.revision, stage: "framing", framing,
      impact_preview_id: preview.preview_id || preview.payload?.preview_id || "",
      actor: "final_matrix_qc", idempotency_key: `fm-${scenarioId}-${role}-framing`,
    });
  }
  const designed = await post(`/api/projects/${projectId}/medical-writing/authoring-journey/stages/picos/commit`, {
    expected_revision: created.revision, stage: "picos", picos,
    actor: "final_matrix_qc", idempotency_key: `fm-${scenarioId}-${role}-picos`,
  });
  const missing = designed.corpus_gate?.missing_requirements || [];
  const allowed = await post(`/api/projects/${projectId}/medical-writing/authoring-journey/corpus-gate/override`, {
    expected_revision: designed.revision,
    reason: "最终矩阵隔离验收：保留语料缺口，验证M11模板与研究事实绑定。",
    acknowledged_missing_requirements: missing,
    actor: "final_matrix_qc", idempotency_key: `fm-${scenarioId}-${role}-corpus`,
  });
  const definition = allowed.study_definition;
  if (!definition) throw new Error("No StudyDefinition produced.");
  const refreshed = await post(`/api/projects/${projectId}/medical-writing/protocol-assembly-plan/refresh`, {
    expected_plan_revision: 0,
    expected_source_definition_id: definition.definition_id,
    expected_source_definition_revision: definition.revision,
    expected_source_definition_sha256: definition.state_sha256,
    actor: "final_matrix_qc", idempotency_key: `fm-${scenarioId}-${role}-plan-refresh`,
  });
  const plan = refreshed.plan || refreshed.payload?.plan;
  if (!plan) throw new Error("Assembly plan refresh returned no plan.");
  const confirmed = await post(`/api/projects/${projectId}/medical-writing/protocol-assembly-plan/confirm`, {
    expected_plan_revision: plan.revision, expected_plan_sha256: plan.state_sha256,
    actor: "final_matrix_qc", idempotency_key: `fm-${scenarioId}-${role}-plan-confirm`,
  });
  const confirmedPlan = confirmed.plan || confirmed.payload?.plan;
  if (confirmedPlan?.confirmation_status !== "author_confirmed") {
    throw new Error(`Plan confirmation failed: ${JSON.stringify(confirmed).slice(0, 500)}`);
  }
  const document = await post(`/api/projects/${projectId}/medical-writing/greenfield-document`, {
    protocol_id: framing.protocol_id, version: framing.version,
    document_title: framing.document_title, indication: framing.indication,
    study_phase: framing.study_phase,
    source_study_definition_id: definition.definition_id,
    source_study_definition_revision: definition.revision,
    source_study_definition_sha256: definition.state_sha256,
    template_id: expectedTemplateId, template_version: expectedTemplateVersion,
    actor: "final_matrix_qc", idempotency_key: `fm-${scenarioId}-${role}-doc`,
  });
  return { allowed, document, plan: confirmedPlan, definition };
}

// --- Disposable, visible user-flow preparation ---------------------------------
// This path deliberately uses only the browser UI for state-changing actions.
// GETs below are read-only reconciliation so the report can explain which
// durable stage the visible action reached.  The legacy prepareDocument()
// above remains available for historical API-fixture runs and is not used when
// REAL_USER_FLOW=1.
async function readJourney(project) {
  return json(new URL(`/api/projects/${project}/medical-writing/authoring-journey`, apiBase));
}

async function readPipeline(project) {
  try {
    const payload = await json(new URL(`/api/projects/${project}/medical-writing/research-pipeline/status`, apiBase));
    return payload?.pipeline || payload;
  } catch (error) {
    if (String(error?.message || error).includes("HTTP 404")) return null;
    throw error;
  }
}

async function waitForPipelineStable(project, timeoutMs = 3600000) {
  const stable = new Set([
    "awaiting_triage_confirm", "awaiting_preparation_admission", "awaiting_document_validation",
    "awaiting_translation_scope", "awaiting_corpus_analysis", "awaiting_corpus_admission",
    "corpus_ready", "round2_ready", "failed", "cancelled",
  ]);
  const started = Date.now();
  let last = null;
  while (Date.now() - started < timeoutMs) {
    last = await readPipeline(project);
    if (last?.stage && stable.has(last.stage)) return last;
    await wait(2000);
  }
  throw new Error(`Timed out waiting for pipeline to reach a user-actionable stage: ${last?.stage || "missing"}`);
}

function recordUserAction(label, details = {}) {
  userFlowLedger.push({ at: new Date().toISOString(), label, ...details });
}

async function setUiField(cdp, label, value) {
  const result = await evaluate(cdp, `
    (() => {
      const target = ${JSON.stringify(label)};
      const labels = Array.from(document.querySelectorAll("label.authoring-field"));
      const field = labels.find((item) => {
        const text = (item.querySelector(":scope > span")?.textContent || "")
          .replace(/\\*/g, "").trim();
        return text === target || text.startsWith(target) || text.includes(target);
      });
      const control = field?.querySelector("input:not([type=checkbox]):not([type=radio]), textarea, select");
      if (!control) return { ok: false, reason: "field_not_found", label: target };
      const tag = control.tagName.toLowerCase();
      if (control.disabled) return { ok: false, reason: "field_disabled", label: target };
      if (tag === "select") {
        const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
        if (!setter) return { ok: false, reason: "native_setter_missing", label: target };
        setter.call(control, ${JSON.stringify(Array.isArray(value) ? value.join("\\n") : String(value ?? ""))});
        control.dispatchEvent(new Event("input", { bubbles: true }));
        control.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        control.focus();
        control.select?.();
      }
      control.scrollIntoView({ block: "center" });
      return { ok: true, label: target, tag, value: control.value };
    })()
  `);
  if (!result?.ok) throw new Error(`UI field unavailable: ${JSON.stringify(result)}`);
  if (result.tag !== "select") {
    await cdp.send("Input.insertText", { text: Array.isArray(value) ? value.join("\n") : String(value ?? "") });
    await waitForCondition(cdp, `document.activeElement?.value === ${JSON.stringify(Array.isArray(value) ? value.join("\n") : String(value ?? ""))}`, 10000);
  }
  recordUserAction("填入字段", { field: label });
  await wait(120);
  return result;
}

async function setUiAriaField(cdp, ariaLabel, value) {
  const result = await evaluate(cdp, `
    (() => {
      const control = document.querySelector(${JSON.stringify(`[aria-label="${ariaLabel.replaceAll('"', '\\"')}"]`)});
      if (!control) return { ok: false, reason: "aria_field_not_found", label: ${JSON.stringify(ariaLabel)} };
      if (control.disabled) return { ok: false, reason: "field_disabled", label: ${JSON.stringify(ariaLabel)} };
      control.focus();
      control.select?.();
      control.scrollIntoView({ block: "center" });
      return { ok: true, value: control.value };
    })()
  `);
  if (!result?.ok) throw new Error(`UI aria field unavailable: ${JSON.stringify(result)}`);
  await cdp.send("Input.insertText", { text: String(value ?? "") });
  await waitForCondition(cdp, `document.activeElement?.value === ${JSON.stringify(String(value ?? ""))}`, 10000);
  recordUserAction("填入结构化字段", { field: ariaLabel });
  await wait(120);
  return result;
}

async function clickUiChoice(cdp, text, scope = ".authoring-choice-grid") {
  const clicked = await evaluate(cdp, `
    (() => {
      const target = ${JSON.stringify(text)};
      const label = Array.from(document.querySelectorAll(${JSON.stringify(`${scope} label`)}))
        .find((item) => (item.querySelector(":scope > span")?.textContent || item.textContent || "").trim() === target);
      const input = label?.querySelector("input[type=checkbox]");
      if (!input) return { ok: false, reason: "choice_not_found", text: target };
      if (!input.checked) { label.scrollIntoView({ block: "center" }); label.click(); }
      return { ok: true, checked: input.checked };
    })()
  `);
  if (!clicked?.ok) throw new Error(`UI choice unavailable: ${JSON.stringify(clicked)}`);
  recordUserAction("勾选选项", { option: text });
  await wait(160);
}

async function clickAuthoringGroup(cdp, label) {
  const openedDetails = await evaluate(cdp, `
    (() => {
      const details = document.querySelector("details.authoring-advanced-refinement");
      if (!details) return { ok: false, reason: "details_missing" };
      if (!details.open) {
        const summary = details.querySelector("summary");
        if (!summary) return { ok: false, reason: "summary_missing" };
        summary.scrollIntoView({ block: "center" }); summary.click();
      }
      return { ok: true, open: details.open };
    })()
  `);
  if (!openedDetails?.ok || !openedDetails.open) throw new Error(`Advanced refinement panel unavailable: ${JSON.stringify(openedDetails)}`);
  if (!userFlowLedger.some((item) => item.label === "展开高级微调")) recordUserAction("展开高级微调");
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".authoring-group-tabs button"))
        .find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)} && !item.disabled);
      if (!button) return false;
      button.scrollIntoView({ block: "center" }); button.click(); return true;
    })()
  `);
  if (!clicked) throw new Error(`Authoring group unavailable: ${label}`);
  recordUserAction("打开字段组", { group: label });
  await wait(350);
}

async function setUiSelectByAria(cdp, ariaLabel, value) {
  const result = await evaluate(cdp, `
    (() => {
      const select = document.querySelector(${JSON.stringify(`[aria-label="${ariaLabel.replaceAll('"', '\\"')}"]`)});
      if (!select) return { ok: false, reason: "select_not_found", label: ${JSON.stringify(ariaLabel)} };
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
      if (!setter) return { ok: false, reason: "native_setter_missing" };
      setter.call(select, ${JSON.stringify(String(value))});
      select.dispatchEvent(new Event("input", { bubbles: true }));
      select.dispatchEvent(new Event("change", { bubbles: true }));
      select.scrollIntoView({ block: "center" });
      return { ok: true, value: select.value };
    })()
  `);
  if (!result?.ok || result.value !== String(value)) throw new Error(`UI select unavailable: ${JSON.stringify(result)}`);
  recordUserAction("选择下拉项", { field: ariaLabel, value });
  await wait(160);
}

async function setUiRadio(cdp, name, value) {
  const clicked = await evaluate(cdp, `
    (() => {
      const input = document.querySelector(${JSON.stringify(`input[type="radio"][name="${name}"][value="${value}"]`)});
      if (!input) return { ok: false, reason: "radio_not_found" };
      if (!input.checked) { input.scrollIntoView({ block: "center" }); input.click(); }
      return { ok: true, checked: input.checked };
    })()
  `);
  if (!clicked?.ok) throw new Error(`UI radio unavailable: ${JSON.stringify(clicked)}`);
  recordUserAction("选择研究设计", { value });
  await wait(240);
}

async function ensureUiStructuredList(cdp, label, values) {
  const wanted = (Array.isArray(values) ? values : [values]).map((item) => String(item || "").trim()).filter(Boolean);
  if (!wanted.length) return;
  const count = await evaluate(cdp, `Array.from(document.querySelectorAll("fieldset.authoring-structured-list"))
    .find((item) => (item.querySelector("legend")?.textContent || "").replace(/\\*/g, "").trim().startsWith(${JSON.stringify(label)}))
    ?.querySelectorAll("textarea").length || 0`);
  for (let i = count; i < wanted.length; i++) {
    const clicked = await evaluate(cdp, `
      (() => {
        const fieldset = Array.from(document.querySelectorAll("fieldset.authoring-structured-list"))
          .find((item) => (item.querySelector("legend")?.textContent || "").replace(/\\*/g, "").trim().startsWith(${JSON.stringify(label)}));
        const button = Array.from(fieldset?.querySelectorAll("button") || []).find((item) => (item.textContent || "").includes(${JSON.stringify(`新增${label}`)}));
        if (!button || button.disabled) return false;
        button.scrollIntoView({ block: "center" }); button.click(); return true;
      })()
    `);
    if (!clicked) throw new Error(`Structured list add unavailable: ${label}`);
    await wait(120);
  }
  for (let i = 0; i < wanted.length; i++) await setUiAriaField(cdp, `${label} ${i + 1}`, wanted[i]);
  recordUserAction("填写结构化列表", { field: label, count: wanted.length });
}

async function createProjectViaVisibleUi(cdp) {
  const opened = await evaluate(cdp, `
    (() => {
      const button = document.querySelector(".new-project-trigger")
        || Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").includes("新建项目"));
      if (!button) return false;
      button.scrollIntoView({ block: "center" }); button.click(); return true;
    })()
  `);
  if (!opened) throw new Error("New project trigger unavailable");
  recordUserAction("点击新建项目");
  await waitForCondition(cdp, `Boolean(document.querySelector(".new-project-dialog"))`, 15000);
  const entry = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".new-project-entry-mode button"))
        .find((item) => (item.textContent || "").includes("从零开始"));
      if (!button) return false; button.click(); return true;
    })()
  `);
  if (!entry) throw new Error("From-zero project entry unavailable");
  recordUserAction("选择从零开始");
  const values = [scenario.product, scenario.indication, scenario.phase];
  for (let i = 0; i < values.length; i++) {
    const selector = i === 2 ? ".new-project-fields label:nth-of-type(3) select" : `.new-project-fields label:nth-of-type(${i + 1}) input`;
    const ok = await evaluate(cdp, `
      (() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return false;
        const proto = el.tagName.toLowerCase() === "select" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
        if (!setter) return false;
        setter.call(el, ${JSON.stringify(values[i])});
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      })()
    `);
    if (!ok) throw new Error(`New project field unavailable: ${selector}`);
    recordUserAction("填写建项最小信息", { fieldIndex: i + 1 });
  }
  await clickButton(cdp, "创建并进入写作");
  await waitForCondition(cdp, `Boolean(document.querySelector(".authoring-journey-shell")) || document.body.innerText.includes("研究设计引导")`, 60000);
  projectId = await evaluate(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value || ""`);
  if (!projectId) throw new Error("Visible project creation did not select a project");
  recordUserAction("建项完成", { projectId });
  return projectId;
}

async function fillFramingViaVisibleUi(cdp) {
  await clickAuthoringGroup(cdp, "项目与产品");
  const framing = scenario.framing;
  await setUiField(cdp, "方案号", framing.protocol_id);
  await setUiField(cdp, "版本", framing.version);
  await setUiField(cdp, "研究分期", framing.study_phase);
  await setUiField(cdp, "开发区域", framing.development_regions || ["中国"]);
  await setUiField(cdp, "方案标题", framing.document_title);
  await setUiField(cdp, "适应症", framing.indication);
  await setUiField(cdp, "试验药物", framing.investigational_product);
  await setUiSelectByAria(cdp, "药物技术类型", framing.product_profile?.technology_type || "other");
  await setUiSelectByAria(cdp, "暴露范围", framing.product_profile?.exposure_scope || "systemic");
  for (const route of framing.product_profile?.administration_routes || []) await clickUiChoice(cdp, route);
  if (framing.clinicaltrials_condition_term) await setUiField(cdp, "ClinicalTrials.gov疾病检索词", framing.clinicaltrials_condition_term);

  await clickAuthoringGroup(cdp, "研究目的");
  for (const objective of framing.intrinsic_objectives || []) {
    try { await clickUiChoice(cdp, objective); } catch { /* AI may have already selected it; verify by text below. */ }
  }
  await setUiField(cdp, "关键科学与开发不确定性", framing.key_uncertainties || ["关键终点和安全性边界需由公开证据复核"]);

  await clickAuthoringGroup(cdp, "竞品范围");
  if (framing.target_mechanism) await setUiField(cdp, "靶点/作用机制", framing.target_mechanism);
  if (framing.competitor_target_scope) await setUiField(cdp, "竞品靶点与机制范围", framing.competitor_target_scope);

  await clickAuthoringGroup(cdp, "总体设计");
  await setUiField(cdp, "总体设计模式", framing.design_pattern);
  await setUiAriaField(cdp, "目标研究人群补充说明", framing.population_intent);
  await waitForCondition(cdp, `(() => { const b = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").trim() === "完成第一步"); return Boolean(b && !b.disabled); })()`, 30000);
  await clickButton(cdp, "完成第一步");
  await wait(800);
  const impact = await evaluate(cdp, `Boolean(document.querySelector(".authoring-impact-panel"))`);
  if (impact) {
    recordUserAction("确认研究框架下游影响");
    await clickButton(cdp, "确认变更并重新核验");
    await wait(1200);
  }
  await waitForCondition(cdp, `Boolean(document.body.innerText.includes("第一步已完成") || document.querySelector('button.authoring-stage-strip button.done'))`, 30000).catch(() => undefined);
  await wait(1000);
}

async function fillPicosViaVisibleUi(cdp) {
  const picos = scenario.picos;
  const stage = await evaluate(cdp, `Array.from(document.querySelectorAll(".authoring-stage-strip button")).find((item) => (item.textContent || "").includes("PICOS设计"))?.disabled === false`);
  if (!stage) throw new Error("PICOS stage is not enabled after framing completion");
  const stageClicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".authoring-stage-strip button"))
        .find((item) => (item.textContent || "").includes("PICOS设计") && !item.disabled);
      if (!button) return false;
      button.scrollIntoView({ block: "center" }); button.click(); return true;
    })()
  `);
  if (!stageClicked) throw new Error("PICOS stage button became disabled before the visible click");
  recordUserAction("点击阶段", { stage: "PICOS设计" });
  await wait(500);
  await clickAuthoringGroup(cdp, "设计适用性");
  await setUiRadio(cdp, "picos-design-archetype", picos.design_archetype);

  await clickAuthoringGroup(cdp, "研究人群");
  await setUiField(cdp, "目标人群概述", picos.population_summary);
  await ensureUiStructuredList(cdp, "入选标准", picos.inclusion_modules);
  await ensureUiStructuredList(cdp, "排除标准", picos.exclusion_modules);
  await ensureUiStructuredList(cdp, "药物/治疗洗脱规则", picos.washout_rules || []);

  await clickAuthoringGroup(cdp, "干预措施");
  await setUiField(cdp, "试验药物干预概述", picos.intervention_summary);
  await setUiField(cdp, "试验药物常规用法用量", picos.intervention_dose_regimen);
  await ensureUiStructuredList(cdp, "必须使用/背景治疗", picos.required_background_rules || []);
  await ensureUiStructuredList(cdp, "允许使用的合并用药/治疗", picos.allowed_concomitant_rules || []);
  await ensureUiStructuredList(cdp, "限制/禁止使用的合并用药/治疗", picos.prohibited_concomitant_rules || []);
  await ensureUiStructuredList(cdp, "访视/评价前用药与治疗限制", picos.assessment_timing_restrictions || []);

  await clickAuthoringGroup(cdp, "对照");
  await setUiField(cdp, "对照/组间比较设计", picos.comparator_summary);

  await clickAuthoringGroup(cdp, "结局指标");
  await setUiField(cdp, "主要终点及评价时间", picos.primary_endpoint);
  await setUiField(cdp, "关键次要终点", picos.key_secondary_endpoints || []);
  await setUiField(cdp, "其他次要终点", picos.other_secondary_endpoints || []);
  await setUiField(cdp, "探索性终点", picos.exploratory_endpoints || []);
  await setUiField(cdp, "安全性终点", picos.safety_endpoints || []);
  await setUiField(cdp, "AESI定义", picos.aesi_definitions || []);

  await clickAuthoringGroup(cdp, "执行与统计");
  await setUiField(cdp, "研究时期/阶段", picos.study_epochs || []);
  await setUiField(cdp, "访视策略", picos.visit_strategy);
  await setUiField(cdp, "估计目标策略", picos.estimand_strategy);
  await setUiField(cdp, "样本量策略", picos.sample_size_strategy);
  await setUiField(cdp, "统计分析策略", picos.statistical_strategy);
  await waitForCondition(cdp, `(() => { const b = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").trim() === "完成第二步"); return Boolean(b && !b.disabled); })()`, 30000);
  await clickButton(cdp, "完成第二步");
  // PICOS changes invalidate downstream corpus/document state just like
  // framing changes.  The product therefore presents the same visible
  // impact-confirmation panel; complete it through the browser rather than
  // treating the first 409 as a reason to resubmit the same unconfirmed
  // preview.
  await wait(1000);
  const impact = await evaluate(cdp, `Boolean(document.querySelector(".authoring-impact-panel"))`);
  if (impact) {
    recordUserAction("确认PICOS下游影响");
    await clickButton(cdp, "确认变更并重新核验");
    await wait(1200);
  }
  await wait(500);
}

async function clickTab(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const tab = Array.from(document.querySelectorAll('[role="tab"]')).find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)});
      if (!tab) return false; tab.scrollIntoView({ block: "center" }); tab.click(); return true;
    })()
  `);
  if (!clicked) throw new Error(`Reference panel tab unavailable: ${label}`);
  recordUserAction("切换证据面板", { tab: label });
  await wait(600);
}

async function processVisibleReferenceFiles(cdp) {
  await clickTab(cdp, "文档与解析");
  const batchStart = await clickIfEnabled(cdp, "开始批量准备");
  if (batchStart?.clicked) recordUserAction("开始批量准备公开方案");
  const ocrContinue = await clickIfEnabled(cdp, "批量确认并继续");
  if (ocrContinue?.clicked) recordUserAction("确认OCR衔接并继续");
  for (let i = 0; i < 8; i++) {
    const download = await clickIfEnabled(cdp, "下载并解析");
    const parse = await clickIfEnabled(cdp, "解析文档");
    if (!download?.clicked && !parse?.clicked) break;
    recordUserAction(download?.clicked ? "下载并解析公开方案" : "解析公开方案");
    await wait(1000);
  }
  await wait(1200);
}

async function processVisibleTranslation(cdp) {
  await clickTab(cdp, "结构与译文确认");
  const structure = await evaluate(cdp, `Boolean(Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").trim() === "确认结构完整"))`);
  if (structure) {
    await setUiLabelField(cdp, "结构审核说明", "已逐页核对原文章节标题、页码、片段边界及M11结构映射，确认当前结构完整。");
    const clicked = await clickIfEnabled(cdp, "确认结构完整");
    if (clicked?.clicked) recordUserAction("确认原文结构完整");
  }
  const generate = await clickIfEnabled(cdp, "生成监管中文候选");
  if (generate?.clicked) {
    recordUserAction("生成监管中文候选");
    await waitForCondition(cdp, `Boolean(document.querySelector("textarea") && document.body.innerText.includes("作者核对意见"))`, 900000).catch(() => undefined);
  }
  const review = await evaluate(cdp, `Boolean(Array.from(document.querySelectorAll("textarea")).find((item) => (item.parentElement?.textContent || "").includes("作者核对意见")))`);
  if (review) {
    await setUiLabelField(cdp, "作者核对意见", "已对照当前原文核对医学含义、数字、时间窗、否定关系和监管中文表达，确认候选可准入。");
    const approved = await clickIfEnabled(cdp, "确认译文并准入");
    if (approved?.clicked) recordUserAction("确认译文并准入");
  }
  const batchGenerate = await clickIfEnabled(cdp, "生成候选");
  if (batchGenerate?.clicked) recordUserAction("提交监管中文候选批次");
  await wait(1200);
  const batchConfirm = await evaluate(cdp, `Array.from(document.querySelectorAll("button"))
    .find((item) => (item.getAttribute("data-action") || "") === "batch-confirm-eligible-translations" && !item.disabled)?.textContent || ""`);
  if (batchConfirm) {
    await clickIfEnabled(cdp, batchConfirm.trim());
    recordUserAction("一键确认合格翻译候选");
  }
}

async function completeVisibleAiTriageReview(cdp) {
  // A run can be idle, partially failed, or stale after an upstream design
  // commit.  All three recovery actions are visible user actions; never
  // manufacture a retry through an API call in this browser proof.
  const retryLabels = ["启动AI分诊", "按当前信息重新分诊", "重试当前分诊"];
  const triageReadyOrRetryable = `Boolean(document.querySelector('[data-action="confirm-ai-triage"]')) || document.body.innerText.includes("AI建议已就绪") || document.body.innerText.includes("AI建议待确认") || Boolean(document.querySelector('[data-action="retry-ai-triage"]'))`;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    let launched = null;
    for (const label of retryLabels) {
      const candidate = await clickIfEnabled(cdp, label);
      if (candidate?.clicked) {
        launched = label;
        break;
      }
    }
    if (!launched) break;
    recordUserAction(launched, { attempt: attempt + 1 });
    await waitForCondition(cdp, triageReadyOrRetryable, 900000);
    const retryable = await evaluate(cdp, `Boolean(document.querySelector('[data-action="retry-ai-triage"]')) && !document.querySelector('[data-action="confirm-ai-triage"]')`);
    if (!retryable) break;
    if (attempt === 2) throw new Error("Visible AI triage remained retryable after three bounded user retries");
    await wait(600);
  }

  // Keep a single representative public protocol in the disposable PNH
  // proof cell.  The select changes and the final confirmation are genuine
  // browser-visible user actions; no API seed or hidden state mutation is
  // used.  Other scenarios retain the AI classification set as presented.
  const triageDetails = await clickIfEnabled(cdp, "展开明细修订");
  if (triageDetails?.clicked) {
    const keepNct = scenarioId === "pnh_p3" ? "NCT03406507" : "";
    if (keepNct) {
      const selection = await evaluate(cdp, `(() => {
        const selects = Array.from(document.querySelectorAll('select[aria-label$="最终分类"]'));
        if (!selects.length) return { ok: false, count: 0 };
        const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
        if (!setter) return { ok: false, count: selects.length };
        let kept = 0;
        for (const select of selects) {
          const nct = select.getAttribute("aria-label")?.replace(/最终分类$/, "") || "";
          const value = nct === ${JSON.stringify(keepNct)} ? "direct_competitor" : "excluded";
          if (value === "direct_competitor") kept += 1;
          setter.call(select, value);
          select.dispatchEvent(new Event("input", { bubbles: true }));
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
        return { ok: kept === 1, count: selects.length, kept };
      })()`);
      if (!selection?.ok) throw new Error(`Visible triage selection did not cover the candidate basket: ${JSON.stringify(selection)}`);
      recordUserAction("按医学审核缩小竞品篮子", { retained_nct_id: keepNct, excluded_count: Math.max(0, Number(selection.count || 0) - 1) });
    }
  }
  const confirmTriage = await evaluate(cdp, `document.querySelector('[data-action="confirm-ai-triage"]:not([disabled])')?.textContent || ""`);
  if (confirmTriage) {
    await evaluate(cdp, `document.querySelector('[data-action="confirm-ai-triage"]:not([disabled])').click()`);
    recordUserAction("确认并锁定AI分诊");
    await wait(1200);
  }
  await evaluate(cdp, `document.querySelector('[data-action="close-competitor-drawer"]')?.click()`);
  await wait(800);
}

async function reviewAiTriageBeforePipeline(cdp) {
  // The research pipeline's awaiting_triage_confirm gate is visible while
  // the journey is still on the framing/PICOS surface.  The competitor
  // toolbar is mounted there; once the user switches to the corpus stage it
  // is intentionally hidden and the reference panel is rendered inline.
  const opened = await clickIfEnabled(cdp, "查看竞品资料");
  if (!opened?.clicked) {
    throw new Error(`Visible AI triage drawer unavailable before pipeline continuation: ${JSON.stringify(opened)}`);
  }
  recordUserAction("打开竞品资料抽屉");
  await waitForCondition(cdp, `Boolean(document.querySelector('.authoring-competitor-drawer-host[data-open="true"] [data-testid="authoring-competitor-drawer"]'))`, 30000);
  await completeVisibleAiTriageReview(cdp);
}

async function ensureCorpusTriageViaVisibleAi(cdp) {
  let journey = await readJourney(projectId);
  if (journey?.corpus_triage?.status === "finalized") return journey;

  // A confirmed run can be left in projection_pending after PICOS changes.
  // Retry only the visible, idempotent projection first; no second approval
  // or new model call is needed on this path.
  const projectionRetry = await clickIfEnabled(cdp, "重试同步");
  if (projectionRetry?.clicked) {
    recordUserAction("重试分诊结果同步");
    await wait(1500);
    journey = await readJourney(projectId);
    if (journey?.corpus_triage?.status === "finalized") return journey;
  }

  await waitForCondition(cdp, `Boolean(document.querySelector(".writing-reference-ai-triage"))`, 30000);
  await waitForCondition(cdp, `Array.from(document.querySelectorAll('.writing-reference-ai-triage button, [data-action="confirm-ai-triage"]')).some((button) => !button.disabled)`, 30000);
  await completeVisibleAiTriageReview(cdp);
  await wait(1500);
  return readJourney(projectId);
}

async function finalizeCorpusTriageViaUi(cdp) {
  // After PICOS is committed, the inline reference panel exposes the second
  // visible decision needed to unlock batch document preparation.  This is
  // deliberately separate from the pre-PICOS AI triage confirmation.
  await clickTab(cdp, "候选研究");
  const reasonField = await evaluate(cdp, `Boolean(Array.from(document.querySelectorAll("label")).find((item) => (item.textContent || "").trim().startsWith("分诊定稿理由")))`);
  if (reasonField) {
    await setUiLabelField(cdp, "分诊定稿理由", "已整体核对AI分诊结果及当前PICOS，锁定代表性公开Protocol进入深度处理。");
  }
  let journey = await ensureCorpusTriageViaVisibleAi(cdp);
  if (journey?.corpus_triage?.status === "finalized") return;
  const finalize = await clickIfEnabled(cdp, "锁定竞品篮子");
  if (finalize?.clicked) {
    recordUserAction("锁定竞品篮子");
    await wait(1500);
    journey = await readJourney(projectId);
    if (journey?.corpus_triage?.status !== "finalized") {
      throw new Error(`Visible corpus triage finalization did not persist: ${JSON.stringify(journey?.corpus_triage || null)}`);
    }
  } else {
    const journey = await readJourney(projectId);
    if (journey?.corpus_triage?.status !== "finalized") {
      throw new Error(`Visible corpus triage finalization unavailable: ${JSON.stringify(journey?.corpus_triage || null)}`);
    }
  }
}

async function runVisiblePipelineControls(cdp) {
  const history = [];
  const started = Date.now();
  let lastStage = "";
  let triageRetries = 0;
  let downstreamRetries = 0;
  while (Date.now() - started < Number(process.env.PIPELINE_TIMEOUT_MS || 3600000)) {
    const pipeline = await readPipeline(projectId);
    const stage = pipeline?.stage || "missing";
    history.push({ at: new Date().toISOString(), stage, percent: pipeline?.percent ?? null });
    if (stage !== lastStage) { recordUserAction("研究流水线阶段", { stage }); lastStage = stage; }
    if (["corpus_ready", "round2_ready"].includes(stage)) return { history, terminal: stage };
    // The product deliberately exposes a conservative round-1 writing gate:
    // `awaiting_corpus_admission` plus `round1_material_ready` unlocks the
    // evidence-bound design/document path while full medical admission and
    // PICOS alignment remain visible as a later corpus gate.  There is no
    // separate banner button for this state; waiting here would turn a valid
    // user-continuation boundary into an infinite status loop.  Return the
    // truthful boundary so the subsequent visible writing journey can test
    // the same access contract instead of manufacturing a hidden admission.
    if (stage === "awaiting_corpus_admission" && pipeline?.round1_material_ready) {
      recordUserAction("第一轮研究材料可继续写作", { full_corpus_ready: false });
      return { history, terminal: "round1_ready", fullCorpusReady: false };
    }
    if (stage === "failed") {
      // A transient provider timeout leaves a stale/partial triage run and a
      // visible, idempotent recovery action.  Exercise that real user path
      // once before treating the failure as terminal; translation/preparation
      // failures have no such button and still fail closed.
      if (triageRetries < 1) {
        await wait(800);
        const retryTriage = await clickIfEnabled(cdp, "继续未完成分诊");
        if (retryTriage?.clicked) {
          triageRetries += 1;
          recordUserAction("继续未完成分诊", { attempt: triageRetries });
          await wait(1500);
          continue;
        }
      }
      if (downstreamRetries < 1) {
        await wait(800);
        const retryDownstream = await clickIfEnabled(cdp, "从已完成原文继续");
        if (retryDownstream?.clicked) {
          downstreamRetries += 1;
          recordUserAction("从已完成原文继续", { attempt: downstreamRetries });
          await wait(1500);
          continue;
        }
      }
      throw new Error(`Research pipeline terminal ${stage}: ${pipeline?.detail || ""}`);
    }
    if (stage === "cancelled") throw new Error(`Research pipeline terminal ${stage}: ${pipeline?.detail || ""}`);

    if (stage === "awaiting_triage_confirm") {
      const continueButton = await clickIfEnabled(cdp, "确认分诊后继续");
      if (continueButton?.clicked) recordUserAction("确认分诊后继续研究流水线");
      await wait(1200); continue;
    }
    if (["awaiting_preparation_admission", "awaiting_document_validation", "awaiting_translation_scope"].includes(stage)) {
      const inlineCorpus = await evaluate(cdp, `Boolean(document.querySelector(".authoring-corpus-stage"))`);
      if (!inlineCorpus) {
        const opened = await clickIfEnabled(cdp, "查看竞品资料");
        if (opened?.clicked) recordUserAction("打开竞品资料抽屉");
        if (!opened?.clicked) throw new Error(`Visible competitor drawer unavailable at pipeline stage ${stage}: ${JSON.stringify(opened)}`);
        await waitForCondition(cdp, `Boolean(document.querySelector('.authoring-competitor-drawer-host[data-open="true"] [data-testid="authoring-competitor-drawer"]'))`, 30000);
      }
      await wait(500);
      try {
        await processVisibleReferenceFiles(cdp);
        await processVisibleTranslation(cdp);
      } catch (error) {
        recordUserAction("证据面板处理受阻", { error: String(error.message || error).slice(0, 400) });
      }
      const resume = await clickIfEnabled(cdp, "已处理，继续流水线");
      if (resume?.clicked) recordUserAction("已处理文件并继续流水线");
      const admitted = await clickIfEnabled(cdp, "准入下一批原文");
      if (admitted?.clicked) recordUserAction("准入下一批原文");
      await evaluate(cdp, `document.querySelector('[data-action="close-competitor-drawer"]')?.click()`);
      await wait(1500); continue;
    }
    if (["awaiting_corpus_analysis", "awaiting_corpus_admission"].includes(stage)) {
      const inlineCorpus = await evaluate(cdp, `Boolean(document.querySelector(".authoring-corpus-stage"))`);
      if (!inlineCorpus) {
        const opened = await clickIfEnabled(cdp, "查看竞品资料");
        if (opened?.clicked) recordUserAction("打开准入证据抽屉");
        if (!opened?.clicked) throw new Error(`Visible competitor drawer unavailable at pipeline stage ${stage}: ${JSON.stringify(opened)}`);
        await waitForCondition(cdp, `Boolean(document.querySelector('.authoring-competitor-drawer-host[data-open="true"] [data-testid="authoring-competitor-drawer"]'))`, 30000);
      }
      await wait(500);
      try {
        await clickTab(cdp, "已准入证据");
        const alignment = await evaluate(cdp, `Boolean(Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").trim() === "记录PICOS核对结论"))`);
        if (alignment) {
          await setUiLabelField(cdp, "核对与处置说明", "已逐项核对研究人群、干预、对照、主要终点和评价时间点与当前准入语料，未发现未处置冲突。");
          const clicked = await clickIfEnabled(cdp, "记录PICOS核对结论");
          if (clicked?.clicked) recordUserAction("记录PICOS核对结论");
        }
      } catch (error) { recordUserAction("准入证据核对受阻", { error: String(error.message || error).slice(0, 400) }); }
      await evaluate(cdp, `document.querySelector('[data-action="close-competitor-drawer"]')?.click()`);
      const resume = await clickIfEnabled(cdp, "已处理，继续流水线");
      if (resume?.clicked) recordUserAction("完成语料处理并继续");
      await wait(1500); continue;
    }
    await wait(2500);
  }
  throw new Error(`Visible pipeline controls timed out at ${lastStage || "missing"}`);
}

async function setUiLabelField(cdp, label, value) {
  const result = await evaluate(cdp, `
    (() => {
      const target = ${JSON.stringify(label)};
      const labels = Array.from(document.querySelectorAll("label"));
      const field = labels.find((item) => (item.textContent || "").trim().startsWith(target));
      const control = field?.querySelector("textarea, input");
      if (!control) return { ok: false, reason: "label_control_not_found", label: target };
      if (control.disabled) return { ok: false, reason: "field_disabled" };
      control.focus();
      control.select?.();
      control.scrollIntoView({ block: "center" });
      return { ok: true };
    })()
  `);
  if (!result?.ok) throw new Error(`UI label field unavailable: ${JSON.stringify(result)}`);
  await cdp.send("Input.insertText", { text: String(value) });
  await waitForCondition(cdp, `document.activeElement?.value === ${JSON.stringify(String(value))}`, 10000);
  recordUserAction("填写审核意见", { field: label });
  await wait(120);
}

async function prepareDocumentViaUi(cdp) {
  userFlowLedger = [];
  const createdProjectId = await createProjectViaVisibleUi(cdp);
  projectId = createdProjectId;
  const firstStable = await waitForPipelineStable(projectId);
  recordUserAction("首次等待研究流水线可操作", { stage: firstStable?.stage || null });
  // The first minimum-facts search may attach a second snapshot while the
  // browser still holds the pre-pipeline journey revision.  A visible page
  // reload is the same recoverable action a manager can take; it rehydrates
  // the authoritative revision before any design commit and prevents a stale
  // impact-preview request from masquerading as a field-validation failure.
  await cdp.send("Page.reload", { ignoreCache: true });
  await waitForCondition(cdp, `document.body.textContent.includes("项目总看板") || Boolean(document.querySelector(".authoring-journey-shell"))`, 30000);
  await wait(1000);
  if (!(await evaluate(cdp, `Boolean(document.querySelector(".authoring-journey-shell"))`))) {
    await selectProject(cdp, projectId);
    await clickButton(cdp, "医学写作");
    await waitForCondition(cdp, `Boolean(document.querySelector(".authoring-journey-shell"))`, 30000);
  }
  await installBrowserFetchTrace(cdp);
  recordUserAction("刷新页面重载最新建项版本", { stage: firstStable?.stage || null });
  await waitForCondition(cdp, `(() => {
    const fieldset = document.querySelector(".authoring-journey-fieldset");
    return Boolean(fieldset && !fieldset.disabled && !document.body.innerText.includes("检索中…"));
  })()`, 30000);
  await wait(1000);
  await fillFramingViaVisibleUi(cdp);
  const framingJourney = await readJourney(projectId);
  if (!framingJourney?.framing_complete) throw new Error("Visible UI framing submission did not persist framing_complete");
  const postFramingStable = await waitForPipelineStable(projectId);
  recordUserAction("研究框架提交后等待流水线可操作", { stage: postFramingStable?.stage || null });
  await cdp.send("Page.reload", { ignoreCache: true });
  await waitForCondition(cdp, `document.body.textContent.includes("项目总看板") || Boolean(document.querySelector(".authoring-journey-shell"))`, 30000);
  await wait(800);
  if (!(await evaluate(cdp, `Boolean(document.querySelector(".authoring-journey-shell"))`))) {
    await selectProject(cdp, projectId);
    await clickButton(cdp, "医学写作");
    await waitForCondition(cdp, `Boolean(document.querySelector(".authoring-journey-shell"))`, 30000);
  }
  await installBrowserFetchTrace(cdp);
  recordUserAction("刷新页面重载研究框架提交版本", { stage: postFramingStable?.stage || null });
  // The parent pipeline freezes the framing snapshot while AI triage is
  // awaiting the manager's decision. A real user must confirm that visible
  // triage gate before PICOS becomes writable; otherwise the API correctly
  // returns a 409 even if the form looks editable.
  if (postFramingStable?.stage === "awaiting_triage_confirm") {
    await reviewAiTriageBeforePipeline(cdp);
    await wait(1200);
    const afterTriageStable = await waitForPipelineStable(projectId);
    // In the current product contract, confirming the AI basket may already
    // advance the parent pipeline asynchronously.  Only click the separate
    // banner gate when it remains visible; never duplicate a continuation
    // request after the confirmed basket has started preparation.
    if (afterTriageStable?.stage === "awaiting_triage_confirm") {
      const triageContinue = await clickIfEnabled(cdp, "确认分诊后继续");
      if (triageContinue?.clicked) {
        recordUserAction("确认分诊后继续");
        await wait(1200);
        await waitForPipelineStable(projectId);
      } else {
        throw new Error(`Visible pipeline triage continuation unavailable: ${JSON.stringify(triageContinue)}`);
      }
    } else {
      recordUserAction("AI分诊确认后流水线已自动继续", { stage: afterTriageStable?.stage || null });
    }
  }
  await waitForCondition(cdp, `(() => { const f = document.querySelector(".authoring-journey-fieldset"); return Boolean(f && !f.disabled); })()`, 30000);
  await wait(800);
  await fillPicosViaVisibleUi(cdp);
  let picosJourney = await readJourney(projectId);
  if (!picosJourney?.picos_complete) {
    // A research-pipeline snapshot can advance the journey revision between
    // the visible impact preview and the commit.  Rehydrate the authoritative
    // version and repeat the same visible PICOS flow once; no API commit or
    // hidden state mutation is used as a shortcut.
    recordUserAction("PICOS提交冲突后刷新并重试", { reason: "journey_revision_changed" });
    await cdp.send("Page.reload", { ignoreCache: true });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板") || Boolean(document.querySelector(".authoring-journey-shell"))`, 30000);
    await wait(800);
    if (!(await evaluate(cdp, `Boolean(document.querySelector(".authoring-journey-shell"))`))) {
      await selectProject(cdp, projectId);
      await clickButton(cdp, "医学写作");
      await waitForCondition(cdp, `Boolean(document.querySelector(".authoring-journey-shell"))`, 30000);
    }
    await installBrowserFetchTrace(cdp);
    await waitForCondition(cdp, `(() => { const f = document.querySelector(".authoring-journey-fieldset"); return Boolean(f && !f.disabled); })()`, 30000);
    await fillPicosViaVisibleUi(cdp);
    picosJourney = await readJourney(projectId);
  }
  if (!picosJourney?.picos_complete) throw new Error("Visible UI PICOS submission did not persist picos_complete");
  await cdp.send("Page.reload", { ignoreCache: true });
  await waitForCondition(cdp, `document.body.textContent.includes("项目总看板") || Boolean(document.querySelector(".authoring-journey-shell"))`, 30000);
  await wait(800);
  if (!(await evaluate(cdp, `Boolean(document.querySelector(".authoring-journey-shell"))`))) {
    await selectProject(cdp, projectId);
    await clickButton(cdp, "医学写作");
    await waitForCondition(cdp, `Boolean(document.querySelector(".authoring-journey-shell"))`, 30000);
  }
  await installBrowserFetchTrace(cdp);
  const stageClicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".authoring-stage-strip button"))
        .find((item) => (item.textContent || "").includes("语料准备") && !item.disabled);
      if (!button) return false;
      button.scrollIntoView({ block: "center" }); button.click(); return true;
    })()
  `);
  if (!stageClicked) throw new Error("Corpus stage did not become enabled after visible PICOS completion");
  recordUserAction("点击阶段", { stage: "语料准备" });
  await wait(900);
  await finalizeCorpusTriageViaUi(cdp);
  await wait(700);
  const pipeline = await runVisiblePipelineControls(cdp);
  const journey = await readJourney(projectId);
  const planPayload = await json(new URL(`/api/projects/${projectId}/medical-writing/protocol-assembly-plan`, apiBase)).catch(() => null);
  const session = await json(new URL(`/api/projects/${projectId}/medical-writing/document-session`, apiBase)).catch(() => null);
  const document = session?.document ? { document: session.document } : { document: session };
  return {
    allowed: journey,
    document,
    plan: planPayload?.plan || null,
    definition: journey?.study_definition || null,
    userFlow: { ledger: userFlowLedger, firstStableStage: firstStable?.stage || null, pipeline },
  };
}

// --- CDP helpers ---
function createCdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (!msg.id || !pending.has(msg.id)) return;
    const cb = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) cb.reject(new Error(msg.error.message));
    else cb.resolve(msg.result || {});
  });
  return {
    ready: new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", reject, { once: true });
    }),
    send(method, params = {}, timeoutMs = 30000) {
      const id = nextId++;
      ws.send(JSON.stringify({ id, method, params }));
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error(`CDP timeout (${timeoutMs}ms): ${method}`));
        }, timeoutMs);
        pending.set(id, {
          resolve: (v) => { clearTimeout(timer); resolve(v); },
          reject: (e) => { clearTimeout(timer); reject(e); },
        });
      });
    },
    close() { ws.close(); },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(`JS: ${result.exceptionDetails.text} ${result.exceptionDetails.exception?.description || ""}`);
  return result.result?.value;
}

async function installBrowserFetchTrace(cdp) {
  if (process.env.CDP_TRACE !== "1") return;
  await evaluate(cdp, `
    (() => {
      if (window.__fmFetchTraceInstalled) return true;
      const original = window.fetch.bind(window);
      window.__fmFetchTrace = [];
      window.__fmFetchTraceInstalled = true;
      window.fetch = async (...args) => {
        const input = args[0];
        const url = typeof input === "string" ? input : (input?.url || String(input || ""));
        const relevant = String(url).includes("/medical-writing/jobs/")
          || String(url).includes("/revision-threads")
          || String(url).includes("/medical-writing/authoring-journey");
        const started = Date.now();
        try {
          const response = await original(...args);
          if (relevant) {
            let body = null;
            try { body = await response.clone().json(); } catch {}
            window.__fmFetchTrace.push({
              url: String(url), status: response.status,
              body: body && typeof body === "object"
                ? {
                    status: body.status,
                    job_id: body.job_id,
                    artifact: body.artifact,
                    detail: body.detail,
                    revision: body.revision,
                    framing_complete: body.framing_complete,
                    picos_complete: body.picos_complete,
                    current_stage: body.current_stage,
                  }
                : null,
              elapsed_ms: Date.now() - started,
            });
            if (window.__fmFetchTrace.length > 300) window.__fmFetchTrace.shift();
          }
          return response;
        } catch (error) {
          if (relevant) window.__fmFetchTrace.push({ url: String(url), error: String(error), elapsed_ms: Date.now() - started });
          throw error;
        }
      };
      return true;
    })()
  `);
}

async function readBrowserFetchTrace(cdp) {
  if (!cdp || process.env.CDP_TRACE !== "1") return [];
  try { return await evaluate(cdp, "window.__fmFetchTrace || []"); } catch { return []; }
}

async function writeTerminalBrowserDiagnostic(cdp, durableStatus, jobId) {
  if (process.env.CDP_TRACE !== "1") return;
  const diagnostic = {
    jobId,
    durableStatus,
    capturedAt: new Date().toISOString(),
    browserFetchTrace: await readBrowserFetchTrace(cdp),
    browserState: await evaluate(cdp, `(() => ({
      revisionMessage: document.querySelector(".writing-ai-core")?.innerText?.slice(0, 1000) || "",
      revisionLoading: Boolean(document.querySelector(".revision-thread-head button")?.disabled),
      candidateCount: document.querySelectorAll(".writing-ai-candidates article").length,
      revisionThreadCount: document.querySelectorAll(".revision-turn[data-turn-number]").length,
      localStorageLocator: (() => { try { return JSON.parse(localStorage.getItem(${JSON.stringify(`mw_revision_job_${projectId}`)}) || "null"); } catch { return null; } })(),
    }))()`),
  };
  await writeFile(path.join(outputDir, `${scenarioId}_${role}_terminal_browser_diagnostic.json`), JSON.stringify(diagnostic, null, 2), "utf8");
}

async function waitForCondition(cdp, expression, timeoutMs = 45000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const value = await evaluate(cdp, expression);
    if (value) return value;
    await wait(500);
  }
  throw new Error(`Timeout waiting for: ${expression.slice(0, 120)}`);
}

async function setViewport(cdp, vp) {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: vp.width, height: vp.height, deviceScaleFactor: 1, mobile: false,
  });
}

async function capture(cdp, filename) {
  const result = await cdp.send("Page.captureScreenshot", { format: "png" });
  const buffer = Buffer.from(result.data, "base64");
  const filePath = path.join(outputDir, filename);
  await writeFile(filePath, buffer);
  return filePath;
}

async function captureViewports(cdp, prefix) {
  const shots = {};
  for (const vp of viewports) {
    await setViewport(cdp, vp);
    await wait(300);
    shots[`${vp.width}x${vp.height}`] = await capture(cdp, `${prefix}_${vp.width}x${vp.height}.png`);
  }
  return shots;
}

async function clickButton(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button"))
        .find((b) => (b.textContent || "").trim() === ${JSON.stringify(label)} && !b.disabled);
      if (!button) return false;
      button.scrollIntoView({ block: "center" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button not found or disabled: ${label}`);
  recordUserAction("点击按钮", { button: label });
  await wait(500);
}

async function clickSection(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".writing-section-buttons > button"))
        .find((b) => (b.textContent || "").includes(${JSON.stringify(label)}));
      if (!button) return false;
      button.scrollIntoView({ block: "center" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Section button not found: ${label}`);
  await wait(800);
}

async function selectProject(cdp, pid) {
  const changed = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, ${JSON.stringify(pid)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Project switcher not found: ${pid}`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(pid)}`);
}

async function openDocumentMap(cdp) {
  await clickButton(cdp, "目录");
  await waitForCondition(cdp, `Boolean(document.querySelector(".writing-document-map-drawer"))`);
}

async function openWriting(cdp, pid) {
  await selectProject(cdp, pid);
  await clickButton(cdp, "医学写作");
  await waitForCondition(cdp, `
    document.body.textContent.includes("研究方案文档编辑与AI修订")
      || document.body.textContent.includes("研究方案智能设计与写作")
  `, 30000);
}

async function appendBrowserReviewMarker(cdp) {
  await evaluate(cdp, `
    (() => {
      const editor = document.querySelector(".protocol-editor .ProseMirror");
      if (!editor) return false;
      editor.focus();
      const sel = window.getSelection();
      sel.selectAllChildren(editor);
      sel.collapseToEnd();
      document.execCommand("insertText", false, "\\n【最终矩阵浏览器验收标记 ${scenarioId} ${role}】");
      return true;
    })()
  `);
  await wait(500);
}

async function selectBrowserText(cdp) {
  // Prefer the full design paragraph (contains 随机化) so protected-token
  // adoption can succeed without inventing facts, matching the accepted
  // m11_real_ai_full path. Fall back to the longest paragraph only if needed.
  return evaluate(cdp, `
    (() => {
      const editor = document.querySelector(".protocol-editor .ProseMirror");
      if (!editor) return { ok: false, reason: "no editor" };
      const paragraphs = Array.from(editor.querySelectorAll("p, h1, h2, h3, h4, li, td"));
      const target = paragraphs.find((p) => (p.textContent || "").includes("随机化"))
        || paragraphs.find((p) => (p.textContent || "").trim().length > 40)
        || paragraphs[0];
      if (!target) return { ok: false, reason: "no paragraph" };
      editor.focus();
      const range = document.createRange();
      range.selectNodeContents(target);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      document.dispatchEvent(new Event("selectionchange", { bubbles: true }));
      target.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, view: window }));
      return { ok: true, text: target.textContent.trim().slice(0, 500), mode: "full_design_paragraph" };
    })()
  `);
}

async function setControlledValue(cdp, selector, value) {
  await evaluate(cdp, `
    (() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return false;
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, "value"
      )?.set || Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
      if (nativeInputValueSetter) nativeInputValueSetter.call(el, ${JSON.stringify(value)});
      else el.value = ${JSON.stringify(value)};
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
}

async function clickIfEnabled(cdp, label) {
  return evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button"))
        .find((b) => (b.textContent || "").trim() === ${JSON.stringify(label)});
      if (!button) return { clicked: false, reason: "missing" };
      if (button.disabled) return { clicked: false, reason: "disabled", title: button.title || "" };
      button.scrollIntoView({ block: "center" });
      button.click();
      return { clicked: true, label: ${JSON.stringify(label)} };
    })()
  `);
}

async function exerciseRevisionIntents(cdp) {
  // These are visible options in the revision-intent <select>, not buttons.
  // Select each option through the browser DOM contract and read the controlled
  // value back after React re-renders.  This proves the user-facing option is
  // reachable without submitting four duplicate AI jobs.
  const intents = [
    { label: "改写", value: "medical_writing_revision" },
    { label: "监管语气", value: "regulatory_tone" },
    { label: "查一致性", value: "consistency_check" },
    { label: "补证据", value: "evidence_gap" },
  ];
  const selections = [];
  for (const intent of intents) {
    const result = await evaluate(cdp, `
      (() => {
        const select = document.querySelector(".revision-form select");
        if (!select) return { ok: false, reason: "missing_select", label: ${JSON.stringify(intent.label)} };
        const option = Array.from(select.options).find((item) => item.textContent.trim() === ${JSON.stringify(intent.label)});
        if (!option) return { ok: false, reason: "missing_option", label: ${JSON.stringify(intent.label)} };
        const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
        if (!setter) return { ok: false, reason: "missing_native_setter", label: ${JSON.stringify(intent.label)} };
        setter.call(select, option.value);
        select.dispatchEvent(new Event("input", { bubbles: true }));
        select.dispatchEvent(new Event("change", { bubbles: true }));
        return { ok: true, label: ${JSON.stringify(intent.label)}, value: select.value, optionValue: option.value };
      })()
    `);
    await wait(200);
    const observed = await evaluate(cdp, `document.querySelector(".revision-form select")?.value || ""`);
    selections.push({ ...result, observedValue: observed, matched: Boolean(result?.ok && observed === intent.value) });
  }
  return selections;
}

async function captureManagerUxReview(cdp) {
  return evaluate(cdp, `
    (() => {
      const visible = (element) => {
        if (!element) return false;
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
      };
      const editor = document.querySelector(".writing-editor-core");
      const ai = document.querySelector(".writing-ai-core");
      const editorRect = editor?.getBoundingClientRect();
      const aiRect = ai?.getBoundingClientRect();
      const bodyText = document.body.innerText || "";
      const candidate = document.querySelector(".writing-ai-candidates article");
      const visibleButtons = Array.from(document.querySelectorAll("button"))
        .filter(visible)
        .map((button) => ({ label: (button.innerText || button.getAttribute("aria-label") || "").trim(), disabled: button.disabled }))
        .filter((item) => item.label);
      return {
        editorPresent: visible(editor),
        aiRailPresent: visible(ai),
        editorBeforeAi: Boolean(editorRect && aiRect && editorRect.left < aiRect.left),
        noHorizontalOverflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) <= window.innerWidth + 1,
        recommendationFirst: bodyText.includes("独立AI") && bodyText.includes("可直接采用的版本") && bodyText.includes("推荐版本"),
        candidateActionVisible: visible(candidate) && Array.from(candidate.querySelectorAll("button")).some((button) => (button.innerText || "").includes("选用并写入")),
        calmStatusVisible: Boolean(document.querySelector(".working-copy-status-main")),
        visibleButtonCount: visibleButtons.length,
        visibleButtonLabels: visibleButtons.map((item) => item.label).slice(0, 80),
        instructionTextareaCount: document.querySelectorAll(".writing-ai-core textarea").length,
      };
    })()
  `);
}

async function captureWordReceipt(docxPath, receiptDir) {
  // Disposable Word open + field refresh + page count. Never saves the DOCX.
  // Auto-dismiss the external-field update prompt with Yes so TOC/fields refresh.
  await mkdir(receiptDir, { recursive: true });
  const receiptJson = path.join(receiptDir, "word_receipt.json");
  const script = `
on run argv
  set docPath to item 1 of argv
  set outPath to item 2 of argv
  set posixDoc to POSIX file docPath
  tell application "Microsoft Word"
    activate
    -- Hold the document reference from the open command; do not rely on
    -- "active document" later, which can be missing value while Word is
    -- still initializing the window after a fresh launch.
    set theDoc to open file name posixDoc without confirm conversions
  end tell
  delay 2
  try
    tell application "System Events"
      tell process "Microsoft Word"
        if exists (sheet 1 of window 1) then
          try
            click button 1 of sheet 1 of window 1
          end try
        end if
      end tell
    end tell
  end try
  delay 2
  tell application "Microsoft Word"
    -- Resolve a live document reference: prefer the one returned by open,
    -- fall back to active document, and wait until one is addressable.
    set theDoc to theDoc
    try
      set docName to name of theDoc
    on error
      set theDoc to missing value
    end try
    if theDoc is missing value then
      repeat 10 times
        delay 1
        try
          set theDoc to active document
          set docName to name of theDoc
          exit repeat
        end try
      end repeat
    end if
    if theDoc is missing value then
      error "no addressable Word document after open"
    end if
    try
      update fields of theDoc
    end try
    -- Wait for pagination to settle; ComputeStatistics can return 0 until
    -- Word has laid out the document. Retry until a positive page count.
    set pageCount to 0
    repeat 12 times
      try
        set pageCount to (compute statistics theDoc statistic statistic pages)
      on error
        try
          set pageCount to (count of pages of theDoc)
        on error
          set pageCount to 0
        end try
      end try
      if pageCount > 0 then exit repeat
      delay 1
    end repeat
    set wordCount to 0
    try
      set wordCount to (count of words of theDoc)
    end try
    set docName to name of theDoc
    close theDoc saving no
    set payload to "{" & quote & "document" & quote & ":" & quote & docName & quote & "," & quote & "page_count" & quote & ":" & pageCount & "," & quote & "word_count" & quote & ":" & wordCount & "," & quote & "field_refresh" & quote & ":true," & quote & "saved" & quote & ":false," & quote & "basis" & quote & ":" & quote & "microsoft_word_receipt" & quote & "}"
    set fRef to open for access (POSIX file outPath) with write permission
    set eof of fRef to 0
    write payload to fRef as «class utf8»
    close access fRef
  end tell
  return outPath
end run
`;
  const scriptPath = path.join(receiptDir, "word_receipt.applescript");
  await writeFile(scriptPath, script, "utf8");
  const result = spawnSync("osascript", [scriptPath, docxPath, receiptJson], {
    encoding: "utf8",
    timeout: 120000,
  });
  if (result.status !== 0) {
    return {
      ok: false,
      error: (result.stderr || result.stdout || `exit:${result.status}`).slice(0, 500),
      path: receiptJson,
      timedOut: result.signal === "SIGTERM" || result.error?.code === "ETIMEDOUT",
    };
  }
  try {
    const payload = JSON.parse(await readFile(receiptJson, "utf8"));
    return { ok: true, ...payload, path: receiptJson };
  } catch (error) {
    return { ok: false, error: error.message, path: receiptJson };
  }
}

async function sha256File(filePath) {
  const data = await readFile(filePath);
  return { bytes: data.length, sha256: createHash("sha256").update(data).digest("hex") };
}

// --- Real AI flow ---
async function runRealAiFlow(cdp, sectionId) {
  const gateway = await json(new URL("/api/ai-gateway/status", appUrl));
  const roleSettings = await json(new URL("/api/ai-gateway/settings", appUrl));
  const independentRole = (roleSettings.roles || []).find((r) => r.role_id === "independent_ai") || null;
  const route = {
    configured: Boolean(gateway.configured),
    semanticAiTasksEnabled: Boolean(gateway.semantic_ai_tasks_enabled),
    provider: gateway.provider || independentRole?.provider || null,
    model: gateway.model || independentRole?.model || null,
    transport: gateway.transport || null,
    deploymentProfile: gateway.deployment_profile || null,
    routeValidationErrors: gateway.route_validation_errors || [],
  };
  if (!route.configured || !route.semanticAiTasksEnabled || route.routeValidationErrors.length) {
    throw new Error(`AI route not runnable: ${JSON.stringify(route)}`);
  }

  const selection = await selectBrowserText(cdp);
  const instruction = scenario.aiInstruction;
  await setControlledValue(cdp, ".revision-form textarea", instruction);
  // Cold Vite dev-mount of the revision form can exceed 10s on a loaded machine; this is UI latency, not a contract failure.
  await waitForCondition(cdp, `document.querySelector(".revision-form textarea")?.value === ${JSON.stringify(instruction)}`, 30000);

  const initialThreadCount = (await json(new URL(`/api/projects/${projectId}/revision-threads`, appUrl))).length;
  const submitted = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".revision-form button"))
        .find((b) => (b.textContent || "").trim() === "提交AI修订");
      if (!button || button.disabled) return { ok: false, disabled: button?.disabled ?? null, title: button?.title || "" };
      button.scrollIntoView({ block: "center" });
      button.click();
      return { ok: true };
    })()
  `);
  if (!submitted?.ok) throw new Error(`AI submit unavailable: ${JSON.stringify(submitted)}`);
  await waitForCondition(cdp, `document.body.innerText.includes("AI修订已提交") || document.body.innerText.includes("处理中")`, 15000);

  const realAiTimeout = Number(process.env.REAL_AI_TIMEOUT_MS || 600000);
  let jobLocator = null;
  const locStart = Date.now();
  while (Date.now() - locStart < 15000) {
    jobLocator = await evaluate(cdp, `(() => {
      try { return JSON.parse(localStorage.getItem(${JSON.stringify(`mw_revision_job_${projectId}`)}) || "null"); }
      catch { return null; }
    })()`);
    if (jobLocator?.job_id) break;
    await wait(250);
  }
  if (!jobLocator?.job_id) throw new Error("No durable job locator after AI submit.");

  let durableStatus = null;
  const jobStart = Date.now();
  while (Date.now() - jobStart < realAiTimeout) {
    durableStatus = await jsonEventually(new URL(`/api/projects/${projectId}/medical-writing/jobs/${jobLocator.job_id}`, apiBase));
    if (["completed", "failed", "cancelled"].includes(durableStatus.status)) break;
    await wait(1500);
  }
  if (!durableStatus || durableStatus.status !== "completed") {
    throw new Error(`AI job not completed: ${JSON.stringify(durableStatus?.status)} ${durableStatus?.error_summary || ""}`);
  }

  // Reconcile the durable result before relying on a browser refresh. A
  // completed job without its declared thread/suggestions is a contract
  // failure and must fail fast with an actionable error instead of hanging in
  // the visible candidate panel. This is a read-only harness check; the
  // product UI remains the only surface that performs adoption.
  const terminalResult = await jsonEventually(
    new URL(`/api/projects/${projectId}/medical-writing/jobs/${jobLocator.job_id}/result`, apiBase),
    undefined,
    12,
  );
  const artifact = terminalResult.artifact || {};
  const artifactThreadId = String(artifact.thread_id || "");
  const artifactSuggestionIds = Array.isArray(artifact.suggestion_ids)
    ? artifact.suggestion_ids.map((value) => String(value)).filter(Boolean)
    : [];
  if (!artifactThreadId || !artifactSuggestionIds.length) {
    throw new Error(`completed-job-artifact-missing: ${JSON.stringify({
      job_id: jobLocator.job_id,
      status: terminalResult.status,
      artifact,
    }).slice(0, 1000)}`);
  }
  let artifactThread = null;
  let artifactSnapshot = null;
  const artifactStart = Date.now();
  const artifactTimeout = Number(process.env.ARTIFACT_RECONCILE_TIMEOUT_MS || 45000);
  while (Date.now() - artifactStart < artifactTimeout) {
    artifactSnapshot = await jsonEventually(new URL(`/api/projects/${projectId}/revision-threads`, apiBase), undefined, 3);
    artifactThread = artifactSnapshot.find((item) => item.thread_id === artifactThreadId) || null;
    const observedSuggestionIds = new Set((artifactThread?.suggestions || []).map((item) => String(item.suggestion_id)));
    const allSuggestionsPresent = artifactSuggestionIds.every((id) => observedSuggestionIds.has(id));
    if (artifactThread?.status === "candidate_ready" && allSuggestionsPresent) break;
    await wait(1000);
  }
  if (!artifactThread || artifactThread.status !== "candidate_ready") {
    throw new Error(`completed-job-artifact-thread-not-ready: ${JSON.stringify({
      job_id: jobLocator.job_id,
      artifactThreadId,
      observedStatus: artifactThread?.status || null,
      artifactSuggestionIds,
      observedSuggestionIds: (artifactThread?.suggestions || []).map((item) => item.suggestion_id),
    }).slice(0, 1200)}`);
  }

  // Persist the terminal browser state before any refresh/readback step. This
  // survives a later child timeout and distinguishes a completed backend job
  // from a UI reconciliation stall.
  await writeTerminalBrowserDiagnostic(cdp, durableStatus, jobLocator.job_id);

  // Refresh thread in browser
  await evaluate(cdp, `(() => {
    const button = Array.from(document.querySelectorAll(".revision-thread-head button"))
      .find((b) => (b.textContent || "").trim() === "刷新");
    if (button && !button.disabled) { button.click(); return true; }
    return false;
  })()`);

  // Completed job + reconciled thread: candidate cards may lag on a cold dev mount; wait generously before judging the UI.
  await waitForCondition(cdp, `document.querySelectorAll(".writing-ai-candidates article").length > 0`, 60000);

  // Make the selected candidate explicit through the visible writing-surface
  // control before probing the current-turn action area. React may render the
  // candidate cards before the detail/action panel has been selected; treating
  // that transient state as an API/readback failure makes the harness report a
  // false product defect.
  await evaluate(cdp, `
    (() => {
      const article = document.querySelector(".writing-ai-candidates article");
      const button = Array.from(article?.querySelectorAll("button") || [])
        .find((b) => (b.textContent || "").trim() === "查看详情" && !b.disabled);
      if (!button) return false;
      button.scrollIntoView({ block: "center" });
      button.click();
      return true;
    })()
  `);
  await waitForCondition(cdp, `Boolean(document.querySelector(".revision-current-action"))`, 15000);

  let threadSnapshot = await jsonEventually(new URL(`/api/projects/${projectId}/revision-threads`, apiBase));
  let thread = threadSnapshot.find((t) => t.thread_id === artifactThreadId)
    || artifactThread
    || threadSnapshot.find((t) => t.status === "candidate_ready")
    || threadSnapshot[threadSnapshot.length - 1]
    || null;
  if (!thread) throw new Error("No revision thread found.");
  let pendingSuggestion = (thread.suggestions || []).find((s) => s.user_decision === "pending") || null;
  if (!pendingSuggestion) throw new Error("No pending suggestion.");

  let candidateArticles = await evaluate(cdp, `Array.from(document.querySelectorAll(".writing-ai-candidates article")).map((a) => ({
    text: a.innerText.slice(0, 300),
    buttons: Array.from(a.querySelectorAll("button")).map((b) => ({ text: b.innerText, disabled: b.disabled })),
  }))`);

  // Attempt adoption
  let adopted = await evaluate(cdp, `
    (() => {
      const articles = Array.from(document.querySelectorAll(".writing-ai-candidates article"));
      const selected = articles
        .map((article, index) => ({ article, index, button: Array.from(article.querySelectorAll("button"))
          .find((b) => (b.textContent || "").trim() === "选用并写入") }))
        .find((item) => item.button && !item.button.disabled)
        || { article: articles[0], index: 0, button: Array.from(articles[0]?.querySelectorAll("button") || [])
          .find((b) => (b.textContent || "").trim() === "选用并写入") };
      const article = selected.article;
      const button = selected.button;
      if (!button || button.disabled) return { ok: false, disabled: button?.disabled ?? null, title: button?.title || "", selectedIndex: selected.index };
      button.scrollIntoView({ block: "center" });
      button.click();
      return { ok: true, selectedIndex: selected.index };
    })()
  `);

  // If protected-token blocked, try same-thread rewrite
  let rewriteAttempted = false;
  if (!adopted?.ok && String(adopted?.title || "").includes("受保护医学标识")) {
    rewriteAttempted = true;
    // Product markup nests textareas inside labels; nth-of-type on label+textarea
    // fails closed. Use direct textarea:nth-of-type selectors proven in M11 QC.
    await setControlledValue(cdp, ".revision-current-action textarea:nth-of-type(1)",
      "首轮候选新增了源选区未包含的项目标识，医学反馈：不得新增任何数字、单位、缩写、受控术语、研究阶段、适应症或产品名称；仅保留源选区事实。");
    await setControlledValue(cdp, ".revision-current-action textarea:nth-of-type(2)",
      "请基于首轮候选重写，仅输出与源选区事实集合完全一致的自然中文；不得新增、删除或改变数字、单位、缩写、受控术语、研究阶段、适应症、产品名称及时间点。若无法安全润色，原样返回源选区。");
    await waitForCondition(cdp, `
      (() => {
        const areas = Array.from(document.querySelectorAll(".revision-current-action textarea"));
        return areas.length >= 2 && (areas[1].value || "").trim().length > 10;
      })()
    `, 10000);
    const rewriteClicked = await evaluate(cdp, `
      (() => {
        const button = Array.from(document.querySelectorAll(".revision-current-action button"))
          .find((b) => (b.textContent || "").trim() === "生成下一轮");
        if (!button || button.disabled) return { ok: false, disabled: button?.disabled ?? null, title: button?.title || "" };
        button.scrollIntoView({ block: "center" });
        button.click();
        return { ok: true };
      })()
    `);
    if (!rewriteClicked?.ok) throw new Error(`Rewrite button unavailable: ${JSON.stringify(rewriteClicked)}`);
    await waitForCondition(cdp, `document.body.innerText.includes("AI按反馈生成新一轮候选中") || document.body.innerText.includes("处理中")`, 15000);
    await waitForCondition(cdp, `Array.from(document.querySelectorAll(".revision-turn[data-turn-number]")).some((t) => Number(t.getAttribute("data-turn-number")) >= 2)`, realAiTimeout);
    threadSnapshot = await jsonEventually(new URL(`/api/projects/${projectId}/revision-threads`, apiBase));
    thread = threadSnapshot.find((t) => t.thread_id === thread.thread_id) || threadSnapshot[threadSnapshot.length - 1] || thread;
    pendingSuggestion = (thread.suggestions || []).find((s) => s.user_decision === "pending" && Number(s.turn_number || 0) >= 2)
      || (thread.suggestions || []).find((s) => s.user_decision === "pending") || null;
    candidateArticles = await evaluate(cdp, `Array.from(document.querySelectorAll(".writing-ai-candidates article")).map((a) => ({
      text: a.innerText.slice(0, 300),
      buttons: Array.from(a.querySelectorAll("button")).map((b) => ({ text: b.innerText, disabled: b.disabled })),
    }))`);
    adopted = await evaluate(cdp, `
      (() => {
        const articles = Array.from(document.querySelectorAll(".writing-ai-candidates article"));
        const article = articles.find((a) => Array.from(a.querySelectorAll("button"))
          .some((b) => (b.textContent || "").trim() === "选用并写入" && !b.disabled));
        const button = Array.from(article?.querySelectorAll("button") || [])
          .find((b) => (b.textContent || "").trim() === "选用并写入");
        if (!button || button.disabled) return { ok: false, title: button?.title || "" };
        button.scrollIntoView({ block: "center" });
        button.click();
        return { ok: true };
      })()
    `);
  }

  const wcBefore = await jsonEventually(new URL(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`, apiBase));
  const beforeRevision = Number(wcBefore.revision || 0);
  if (!adopted?.ok) throw new Error(`Adoption failed: ${JSON.stringify({ adopted, candidateArticles })}`);
  await waitForCondition(cdp, `document.body.innerText.includes("已选用并写入工作副本版本")`, 30000);
  const wcAfter = await jsonEventually(new URL(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`, apiBase));
  const appliedSnapshot = await jsonEventually(new URL(`/api/projects/${projectId}/revision-threads`, apiBase));
  const appliedThread = appliedSnapshot.find((t) => t.thread_id === thread.thread_id) || null;
  // The visible user click may intentionally choose a later candidate when
  // an earlier card is fail-closed for protected-token changes.  Reconcile
  // against the actual accepted suggestion rather than assuming the first
  // pending card was selected.
  const appliedSuggestion = appliedThread?.suggestions?.find((s) => s.user_decision === "accepted")
    || appliedThread?.suggestions?.find((s) => s.suggestion_id === pendingSuggestion.suggestion_id)
    || null;

  if (Number(wcAfter.revision || 0) <= beforeRevision) throw new Error(`Working copy did not advance: ${beforeRevision} -> ${wcAfter.revision}`);
  if (appliedSuggestion?.user_decision !== "accepted") throw new Error(`Decision not persisted: ${JSON.stringify(appliedSuggestion)}`);

  return {
    route, selection, jobId: jobLocator.job_id, jobStatus: durableStatus.status,
    artifactThreadId, artifactSuggestionIds, artifactReconciled: true,
    attemptCount: durableStatus.attempt_count, initialThreadCount,
    threadId: thread.thread_id, suggestionId: appliedSuggestion?.suggestion_id || pendingSuggestion.suggestion_id,
    candidateCount: thread.suggestions?.length || 0, candidateArticles,
    rewriteAttempted,
    workingCopyBefore: beforeRevision, workingCopyAfter: Number(wcAfter.revision || 0),
    appliedDecision: appliedSuggestion?.user_decision || null,
    appliedProposalText: (appliedSuggestion?.proposal_text || "").slice(0, 500),
  };
}

// --- Main ---
async function main() {
  await mkdir(outputDir, { recursive: true });
  const template = await json(new URL(`/api/medical-writing/protocol-templates/${expectedTemplateId}/${expectedTemplateVersion}`, appUrl));
  const userDataDir = await mkdtemp(path.join(tmpdir(), "fm-matrix-qc-"));
  const chrome = spawn(chromePath, [
    "--headless=new", `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`, "--no-first-run", "--no-default-browser-check", "about:blank",
  ], { detached: true, stdio: "ignore" });

  try {
    await wait(2000);
    const versionResponse = await fetch(`http://127.0.0.1:${debugPort}/json/version`);
    if (!versionResponse.ok) throw new Error("Chrome debug port not ready.");
    const targetsResponse = await fetch(`http://127.0.0.1:${debugPort}/json/list`);
    const targets = await targetsResponse.json();
    const target = targets.find((t) => t.type === "page");
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable page target.");
    const cdp = createCdp(target.webSocketDebuggerUrl);
    activeCdp = cdp;
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await setViewport(cdp, viewports[0]);
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`, 30000);
    await installBrowserFetchTrace(cdp);

    // In REAL_USER_FLOW mode every state-changing preparation action is a
    // visible browser click/fill.  The API-driven fixture remains available
    // only for the historical matrix lane.
    const prepared = process.env.REAL_USER_FLOW === "1"
      ? await prepareDocumentViaUi(cdp)
      : await prepareDocument();

    // Open writing surface
    await openWriting(cdp, projectId);
    await openDocumentMap(cdp);
    await waitForCondition(cdp, `document.querySelectorAll(".writing-section-buttons > button").length > 0`, 30000);

    // Verify section count
    const session = await json(new URL(`/api/projects/${projectId}/medical-writing/document-session`, appUrl));
    const renderedCount = session.sections?.length || 0;

    // Check synopsis projection
    await clickSection(cdp, "方案摘要");
    // Cold dev-server section mount can exceed 15s; the API log proves content delivery, so bound the UI wait generously.
    await waitForCondition(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.innerText?.includes(${JSON.stringify(scenario.synopsisToken)})`, 60000);
    const synopsisUi = await evaluate(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.innerText || ""`);
    const synopsisScreenshots = await captureViewports(cdp, `${scenarioId}_synopsis`);

    // Check design projection
    await openDocumentMap(cdp);
    await waitForCondition(cdp, `document.querySelectorAll(".writing-section-buttons > button").length > 0`, 30000);
    await clickSection(cdp, "试验设计描述");
    const designCheckExpr = scenario.designTokens.map((t) => `text.includes(${JSON.stringify(t)})`).join(" && ");
    await waitForCondition(cdp, `(() => { const text = document.querySelector(".protocol-editor .ProseMirror")?.innerText || ""; return ${designCheckExpr}; })()`, 60000);
    const designUi = await evaluate(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.innerText || ""`);

    // Create working copy, save
    await clickButton(cdp, "创建工作副本");
    await waitForCondition(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.getAttribute("contenteditable") === "true"`, 15000);
    await appendBrowserReviewMarker(cdp);
    await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("有未保存修订")`, 15000);
    await clickButton(cdp, "保存工作副本");
    await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("已保存")`, 15000);

    // Reachable writing-surface actions for the user path. Re-select a visible
    // paragraph before probing the controlled intent selector so the option
    // contract is tested in the same state a manager would use it.
    await selectBrowserText(cdp);
    const intentClicks = await exerciseRevisionIntents(cdp);
    const previewEstimateClick = await clickIfEnabled(cdp, "版式估算");
    await wait(800);
    const previewWordClick = await clickIfEnabled(cdp, "预览 Word");
    await wait(1500);
    const reloadClick = await clickIfEnabled(cdp, "重新加载");
    await wait(800);

    // Viewport metrics
    const viewportMetrics = {};
    for (const vp of viewports) {
      await setViewport(cdp, vp);
      await wait(300);
      viewportMetrics[`${vp.width}x${vp.height}`] = await evaluate(cdp, `
        (() => {
          const editor = document.querySelector(".writing-editor-core")?.getBoundingClientRect();
          const ai = document.querySelector(".writing-ai-core")?.getBoundingClientRect();
          return {
            noPageOverflowX: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) <= window.innerWidth + 1,
            editorAiOrder: Boolean(editor && ai && editor.left < ai.left),
            hasEditor: Boolean(document.querySelector(".protocol-editor .ProseMirror")),
          };
        })()
      `);
    }
    const editorScreenshots = await captureViewports(cdp, `${scenarioId}_design`);

    // Formal Word remains intentionally disabled until every required section
    // has an author-frozen snapshot; record the visible gate rather than
    // re-clicking the already exercised draft-preview button.
    const exportButtonClick = await clickIfEnabled(cdp, "正式 Word");
    await wait(300);
    const draftResponse = await fetch(
      new URL(`/api/projects/${projectId}/medical-writing/document.docx?mode=draft_preview`, appUrl),
      { headers: API_CONTRACT_HEADERS },
    );
    const draftBytes = new Uint8Array(await draftResponse.arrayBuffer());
    const draftPath = path.join(outputDir, `${scenarioId}_draft_preview.docx`);
    await writeFile(draftPath, draftBytes);
    const draftHash = await sha256File(draftPath);

    // Real AI flow
    const designSection = session.sections.find((s) => s.template_node_id === "ich_m11_4_1");
    let realAi = null;
    let realAiError = "";
    if (process.env.RUN_REAL_AI === "1") {
      try {
        realAi = await runRealAiFlow(cdp, designSection.section_id);
      } catch (error) {
        realAiError = error.stack || error.message;
      }
    }

    // Post-adoption DOCX export
    let postAdoptionBytes = null;
    let postAdoptionPath = null;
    let postAdoptionHash = null;
    let wordReceipt = null;
    const skipWord = process.env.SKIP_WORD_RECEIPT === "1";
    if (realAi?.appliedDecision === "accepted") {
      await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("已保存")`, 30000);
      const postResponse = await fetch(
        new URL(`/api/projects/${projectId}/medical-writing/document.docx?mode=draft_preview`, appUrl),
        { headers: API_CONTRACT_HEADERS },
      );
      postAdoptionBytes = new Uint8Array(await postResponse.arrayBuffer());
      postAdoptionPath = path.join(outputDir, `${scenarioId}_post_adoption_preview.docx`);
      await writeFile(postAdoptionPath, postAdoptionBytes);
      postAdoptionHash = await sha256File(postAdoptionPath);
      if (!skipWord) {
        wordReceipt = await captureWordReceipt(postAdoptionPath, path.join(outputDir, "word_receipt"));
      } else {
        wordReceipt = { ok: false, skipped: true, reason: "SKIP_WORD_RECEIPT=1" };
      }
    } else if (draftResponse.ok && draftBytes.length >= 1000) {
      if (!skipWord) {
        wordReceipt = await captureWordReceipt(draftPath, path.join(outputDir, "word_receipt"));
      } else {
        wordReceipt = { ok: false, skipped: true, reason: "SKIP_WORD_RECEIPT=1" };
      }
    }

    // Save/reload verification
    const reloadSession = await json(new URL(`/api/projects/${projectId}/medical-writing/document-session`, appUrl));
    const wcReload = await jsonEventually(new URL(`/api/projects/${projectId}/medical-writing/working-copies/${designSection.section_id}`, apiBase));

    const managerUx = role === "manager" ? await captureManagerUxReview(cdp) : null;

    // Failures
    const failures = [];
    if (realAiError) failures.push(`real-ai:${realAiError}`);
    if (template.template_id !== expectedTemplateId) failures.push("template:id");
    if (template.nodes?.length !== expectedTemplateNodeCount) failures.push("template:nodeCount");
    if (!synopsisUi.includes(scenario.indication)) failures.push("ui:synopsisProjection");
    if (!scenario.designTokens.every((t) => designUi.includes(t))) failures.push("ui:designProjection");
    if (!draftResponse.ok || draftBytes.length < 1000) failures.push("export:draftWord");
    if (!skipWord && !wordReceipt?.ok) failures.push(`word-receipt:${wordReceipt?.error || "missing"}`);
    if (!skipWord && wordReceipt?.ok && Number(wordReceipt.page_count || 0) <= 0) failures.push("word-receipt:invalid-page-count");
    if (skipWord) failures.push("word-receipt:skipped_unverified");
    if (!intentClicks.every((item) => item.matched)) failures.push("revision-intent:select-option-unreachable");
    if (role === "manager") {
      if (!managerUx?.editorPresent) failures.push("manager-ux:editor-missing");
      if (!managerUx?.aiRailPresent) failures.push("manager-ux:ai-rail-missing");
      if (!managerUx?.editorBeforeAi) failures.push("manager-ux:editor-ai-order");
      if (!managerUx?.noHorizontalOverflow) failures.push("manager-ux:overflow");
      if (!managerUx?.recommendationFirst) failures.push("manager-ux:recommendation-hierarchy");
      if (!managerUx?.candidateActionVisible) failures.push("manager-ux:candidate-action");
      if (!managerUx?.calmStatusVisible) failures.push("manager-ux:status-bar");
    }
    for (const [key, m] of Object.entries(viewportMetrics)) {
      if (!m.noPageOverflowX) failures.push(`viewport:${key}:overflowX`);
      if (!m.hasEditor) failures.push(`viewport:${key}:editor`);
    }

    const report = {
      scenarioId, role, projectId,
      template: { templateId: template.template_id, templateVersion: template.template_version, nodeCount: template.nodes?.length, definitionSha256: template.definition_sha256 },
      document: { documentId: prepared.document.document?.document_id, sectionCount: renderedCount, status: session.status },
      plan: { revision: prepared.plan?.revision, confirmationStatus: prepared.plan?.confirmation_status, stateSha256: prepared.plan?.state_sha256 },
      definition: { definitionId: prepared.definition?.definition_id, revision: prepared.definition?.revision, stateSha256: prepared.definition?.state_sha256 },
      projections: { synopsisUi: synopsisUi.slice(0, 500), designUi: designUi.slice(0, 500) },
      draftExport: { ok: draftResponse.ok, ...draftHash, path: draftPath },
      postAdoptionExport: postAdoptionBytes ? { ...postAdoptionHash, path: postAdoptionPath } : null,
      wordReceipt,
      buttonClicks: {
        intentClicks,
        previewEstimateClick,
        previewWordClick,
        reloadClick,
        exportButtonClick,
        note: process.env.REAL_USER_FLOW === "1"
          ? "建项、研究框架、PICOS、AI分诊、下载/解析/OCR/翻译/准入控制均由隔离项目的可见CDP浏览器动作驱动；API仅作只读状态、结果和文档回读。"
          : "framing/PICOS/plan/greenfield prep remains an isolated API-seeded fixture; writing-surface actions below are visible CDP browser interactions",
      },
      userFlowPreparation: prepared.userFlow || null,
      managerUx,
      realAi: realAi || { enabled: process.env.RUN_REAL_AI === "1", error: realAiError || null },
      saveReload: { sessionStatus: reloadSession.status, wcRevision: wcReload.revision },
      viewports: viewportMetrics,
      screenshots: { synopsisScreenshots, editorScreenshots },
      failures,
    };
    await writeFile(path.join(outputDir, `${scenarioId}_${role}_qc_report.json`), JSON.stringify(report, null, 2), "utf8");
    lastBrowserFetchTrace = await readBrowserFetchTrace(cdp);
    cdp.close();
    activeCdp = null;
    if (failures.length) throw new Error(`QC failed: ${failures.join(", ")}`);
    console.log(JSON.stringify({ passed: true, scenarioId, role, projectId, failures: [], wordReceipt }));
  } finally {
    lastBrowserFetchTrace = await readBrowserFetchTrace(activeCdp);
    if (activeCdp) activeCdp.close();
    activeCdp = null;
    terminateProcessGroup(chrome.pid, "SIGTERM");
    await wait(500);
    // Chrome may keep helper processes alive briefly after the browser
    // process exits. Force only this disposable user-data-dir group after the
    // bounded grace period; never use a name-based/global kill.
    terminateProcessGroup(chrome.pid, "SIGKILL");
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch(async (error) => {
  console.error(error);
  try {
    await mkdir(outputDir, { recursive: true });
    await writeFile(
      path.join(outputDir, `${scenarioId}_${role}_qc_report.json`),
      JSON.stringify({
        scenarioId,
        role,
        projectId,
        userFlowPreparation: { ledger: userFlowLedger },
        failures: [`fatal:${error.stack || error.message}`],
        browserFetchTrace: lastBrowserFetchTrace,
        fatal: true,
      }, null, 2),
      "utf8",
    );
  } catch {}
  process.exit(1);
});
