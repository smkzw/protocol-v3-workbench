/**
 * Child harness for one indication lane of the cross-indication E2E gate (Round 4).
 *
 * This harness drives a single indication through the medical writing workflow
 * using REAL product API contracts.  Key principles:
 *
 * - UI is used for visible user actions (project creation, navigation).
 * - API is used for assertions, asynchronous state polling, and immutable
 *   evidence capture — and ONLY for those.  An API-only step is never
 *   described as UI coverage.
 * - Receipts, lineage, hashes, revisions, URLs, bytes, and model identity
 *   are captured EXACTLY as returned by the product.  Missing evidence is
 *   represented as a gate failure or not_observed — NEVER fabricated.
 * - Quality scorecard stays pending_blind_review (real candidates) or
 *   blocked_before_review (upstream gate failure).  Scores are NEVER
 *   self-assigned.
 * - Working-copy invariance requires BOTH before and after records with real
 *   hashes/revisions that match.  Missing records are not_observed, never
 *   pass.
 *
 * DRY_RUN mode: creates one disposable project via UI, verifies core
 * reference-workspace route and selector contracts, then stops before any
 * ClinicalTrials.gov search, download, or production AI.
 *
 * Environment contract (set by parent):
 * - QC_ISOLATED_RUNTIME=1 (required)
 * - QC_DRY_RUN=1 (dry-run mode; stops before search/download/AI)
 * - APP_URL, API_URL (product endpoints)
 * - QC_INDICATION_KEY, QC_INDICATION, QC_STUDY_PHASE, QC_PRODUCT_NAME
 * - QC_PROJECT_CODE, QC_MIN_CHAPTERS (JSON array)
 * - QC_EXPECTED_NCT_ID, QC_EXPECTED_DOCUMENT_FILENAME,
 *   QC_EXPECTED_DOCUMENT_ROLE (full mode only)
 * - QC_OUTPUT_DIR, CHROME_DEBUG_PORT
 */

import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  GATE_CODES,
  ARTIFACT_FILENAMES,
  REPRESENTATIVE_CHAPTERS,
  CHAPTER_TARGET_SECTIONS,
  ALLOWED_DOWNLOAD_HOSTS,
} from "./cross_indication_e2e_config.mjs";

if (process.env.QC_ISOLATED_RUNTIME !== "1") {
  throw new Error(
    "cross_indication_e2e_child.mjs mutates runtime state and requires QC_ISOLATED_RUNTIME=1",
  );
}

const DRY_RUN = process.env.QC_DRY_RUN === "1";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const apiUrl = process.env.API_URL || "http://127.0.0.1:8911";
const outputDir =
  process.env.QC_OUTPUT_DIR ||
  path.join(
    projectRoot,
    "runs/execution/mw_cross_indication_reference_release_gate_20260718/cross_indication_e2e_run/child",
  );
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9650);
const chromePath =
  process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

const indicationKey = process.env.QC_INDICATION_KEY || "AD";
const indication = process.env.QC_INDICATION || "特应性皮炎";
const clinicalTrialsConditionTerm =
  process.env.QC_CLINICALTRIALS_CONDITION_TERM || "Atopic Dermatitis";
const studyPhase = process.env.QC_STUDY_PHASE || "II";
const canonicalStudyPhase = studyPhase.endsWith("期")
  ? studyPhase
  : `${studyPhase}期`;
const productName = process.env.QC_PRODUCT_NAME || "AD-01";
const projectCode = process.env.QC_PROJECT_CODE || `QC-MW-${indicationKey}-${Date.now()}`;
const expectedNctId = process.env.QC_EXPECTED_NCT_ID || "";
const expectedDocumentFilename = process.env.QC_EXPECTED_DOCUMENT_FILENAME || "";
const expectedDocumentRole = process.env.QC_EXPECTED_DOCUMENT_ROLE || "";

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

/**
 * Real API call using the product's actual route contracts.
 * Returns { status, payload } where payload is parsed JSON (or {} on failure).
 */
async function apiJson(method, pathname, { body, allowStatus } = {}) {
  const init = {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  const maxAttempts = ["GET", "HEAD"].includes(method.toUpperCase()) ? 3 : 1;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await fetch(`${apiUrl}${pathname}`, init);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok && response.status !== allowStatus) {
        const error = new Error(
          `${method} ${pathname} -> ${response.status}: ${JSON.stringify(payload).slice(0, 500)}`,
        );
        error.status = response.status;
        error.payload = payload;
        throw error;
      }
      return { status: response.status, payload };
    } catch (error) {
      if (error?.status || attempt === maxAttempts) throw error;
      await wait(250 * attempt);
    }
  }
  throw new Error(`${method} ${pathname} failed without a response`);
}

async function waitForJson(url, timeoutMs = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) return response.json();
    } catch {
      /* retry */
    }
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
    close() {
      ws.close();
    },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails)
    throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
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

async function screenshot(cdp, filename, viewport = "1920x1080") {
  const image = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  await writeFile(
    path.join(outputDir, `${viewport}_${filename}`),
    Buffer.from(image.data, "base64"),
  );
}

function recordGateFailure(report, gateCode, context = {}) {
  const template = GATE_CODES[gateCode];
  if (!template) throw new Error(`unknown gate code ${gateCode}`);
  report.gateFailures.push({
    gate_code: gateCode,
    stage: template.stage,
    severity: template.severity,
    description: template.description,
    indication: indicationKey,
    nct_id: context.nct_id || null,
    evidence_locator: context.evidence_locator || null,
    retry_after_backend_fix: true,
  });
}

/**
 * Create a new project through the UI using the REAL dialog contract:
 *   form.new-project-dialog with fields: project_code, project_name,
 *   indication, study_phase (select), product_name, protocol_id.
 *
 * Uses React-compatible value setters (native setter on prototype) so the
 * onChange handler fires.  Entry mode buttons use "从零开始" text.
 * Submit via the "创建并进入写作" button.
 */
async function createProjectViaUi(cdp, report) {
  // Open the new-project dialog
  await evaluate(cdp, `(() => {
    const trigger = document.querySelector('.new-project-trigger') ||
      Array.from(document.querySelectorAll('button')).find((b) => (b.textContent||'').includes('新建项目'));
    if (trigger) trigger.click();
    return Boolean(trigger);
  })()`);
  await waitForCondition(cdp, `Boolean(document.querySelector('.new-project-dialog'))`);

  // Select "从零开始" entry mode
  await evaluate(cdp, `(() => {
    const buttons = document.querySelectorAll('.new-project-entry-mode button');
    const target = Array.from(buttons).find((b) => (b.textContent||'').includes('从零开始'));
    if (target) target.click();
    return Boolean(target);
  })()`);

  // Fill fields using React-compatible setters
  const reactSetter = (selector, value, isSelect) => `
    (() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) throw new Error('field not found: ' + ${JSON.stringify(selector)});
      const proto = ${isSelect ? "HTMLSelectElement.prototype" : "HTMLInputElement.prototype"};
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, ${JSON.stringify(value)});
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()
  `;

  // Fields are inside .new-project-fields labels
  await evaluate(
    cdp,
    reactSetter(
      '.new-project-fields label:nth-of-type(1) input',
      productName,
      false,
    ),
  );
  await evaluate(
    cdp,
    reactSetter(
      '.new-project-fields label:nth-of-type(2) input',
      indication,
      false,
    ),
  );
  // study_phase is the third and final creation field.
  await evaluate(
    cdp,
    reactSetter(
      '.new-project-fields label:nth-of-type(3) select',
      canonicalStudyPhase,
      true,
    ),
  );

  // Submit via the form (triggers React onSubmit)
  await evaluate(cdp, `(() => {
    const dialog = document.querySelector('.new-project-dialog');
    if (dialog) dialog.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    return true;
  })()`);

  // Wait for the authoring journey shell to appear (real UI state)
  await waitForCondition(
    cdp,
    `Boolean(document.querySelector('.authoring-journey-shell')) ||
     document.body.textContent.includes('研究设计引导') ||
     document.body.textContent.includes('研究方案智能设计与写作')`,
    60000,
  );
  await screenshot(cdp, "new_project_active.png");

  // Read the selected project id from the real project selector
  const selectedProjectId = await evaluate(
    cdp,
    `document.querySelector('select[aria-label="选择临床研究项目"]')?.value || null`,
  );
  if (!selectedProjectId) {
    throw new Error("new project did not produce a selected project id in the UI selector");
  }
  report.projectId = selectedProjectId;
  return selectedProjectId;
}

/**
 * Get the real authoring journey and its revision for optimistic concurrency.
 */
async function getJourney(projectId) {
  const result = await apiJson("GET", `/api/projects/${projectId}/medical-writing/authoring-journey`);
  return result.payload;
}

/**
 * Commit the framing stage using the REAL contract:
 *   MedicalWritingAuthoringJourneyCommitRequest requires:
 *     expected_revision, stage="framing", framing (MedicalWritingStudyFraming),
 *     impact_preview_id, actor, idempotency_key
 *
 * MedicalWritingStudyFraming required fields:
 *   protocol_id, document_title, indication, clinicaltrials_condition_term,
 *   study_phase, investigational_product, target_mechanism, design_pattern
 */
async function commitFraming(projectId, journey, report) {
  const expectedRevision = journey.revision;
  const framing = {
    protocol_id: projectCode,
    version: "V0.1",
    document_title: `${productName}治疗${indication}的${canonicalStudyPhase}临床研究方案`,
    indication,
    clinicaltrials_condition_term: clinicalTrialsConditionTerm,
    study_phase: canonicalStudyPhase,
    intrinsic_objectives: ["剂量探索"],
    investigational_product: productName,
    target_mechanism: "创新疗法",
    competitor_target_scope: "同适应症竞品",
    development_regions: ["中国"],
    design_pattern: "随机、双盲、安慰剂对照研究",
    population_intent: `${indication}成人试验参与者`,
    key_uncertainties: ["剂量选择"],
    manual_source_ids: [],
    terminology_policy: "cde_participant",
  };

  // Impact preview first (real contract)
  const preview = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`,
    {
      body: { expected_revision: expectedRevision, stage: "framing", framing },
    },
  );

  // Commit (real contract)
  const commit = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/authoring-journey/stages/framing/commit`,
    {
      body: {
        expected_revision: expectedRevision,
        stage: "framing",
        framing,
        impact_preview_id: preview.payload.preview_id || "",
        actor: "medical_manager_qc",
        idempotency_key: `cross-indication-framing-${indicationKey}-${Date.now()}`.slice(0, 200),
      },
    },
  );
  report.framingRevision = commit.payload.revision;
  report.searchPlanId = commit.payload.search_plan?.plan_id || null;
  return commit.payload;
}

/**
 * Execute competitor search using the REAL contract:
 *   MedicalWritingCompetitorSearchExecuteRequest requires:
 *     search_plan_id, actor, idempotency_key
 *
 * The search_plan_id comes from the committed framing stage.
 * The execute route returns the updated authoring journey.  Resolve its
 * immutable latest_snapshot_id through the read endpoint before downstream
 * triage; treating the journey payload as a snapshot silently produces an
 * empty candidate list.
 */
async function competitorSearch(projectId, searchPlanId, report) {
  const result = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/authoring-journey/competitor-search`,
    {
      body: {
        search_plan_id: searchPlanId,
        actor: "medical_manager_qc",
        idempotency_key: `cross-indication-search-${indicationKey}-${Date.now()}`.slice(0, 200),
      },
    },
  );
  const journey = result.payload;
  const snapshotId = journey?.search_plan?.latest_snapshot_id;
  if (!snapshotId) {
    throw new Error("competitor search journey did not expose latest_snapshot_id");
  }
  const snapshotResult = await apiJson(
    "GET",
    `/api/projects/${projectId}/medical-writing/references/search-snapshots/${encodeURIComponent(snapshotId)}`,
  );
  report.searchJourneyRevision = journey.revision ?? null;
  report.searchPlanStatus = journey.search_plan?.status || null;
  return {
    journey,
    snapshot: snapshotResult.payload,
  };
}

async function recordExpectedStudyRelevance(projectId, snapshotId, nctId, report) {
  const result = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/references/search-snapshots/${snapshotId}/relevance-decisions`,
    {
      body: {
        nct_id: nctId,
        relevance_status: "direct_competitor",
        reason: `跨适应症生产验收：${nctId}为当前适应症、分期及公开Protocol/SAP目标研究。`,
        actor: "medical_manager_qc",
        expected_revision: 0,
        idempotency_key: `cross-indication-relevance-${indicationKey}-${nctId}`.slice(0, 200),
      },
    },
  );
  report.relevanceDecision = result.payload;
  return result.payload;
}

async function finalizeCompetitorTriage(projectId, journey, snapshotId, nctId, report) {
  const result = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/authoring-journey/corpus-triage/finalize`,
    {
      body: {
        expected_revision: journey.revision,
        snapshot_id: snapshotId,
        retained_candidate_ids: [nctId],
        reason: `锁定${nctId}作为本轮跨适应症公开竞品方案深度处理对象。`,
        actor: "medical_manager_qc",
        idempotency_key: `cross-indication-triage-${indicationKey}-${snapshotId}`.slice(0, 200),
      },
    },
  );
  report.triageRevision = result.payload.revision;
  return result.payload;
}

async function createPreparationBatch(projectId, snapshotId, report) {
  const result = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/references/preparation-batches`,
    {
      body: {
        snapshot_id: snapshotId,
        actor: "medical_manager_qc",
        idempotency_key: `cross-indication-preparation-${indicationKey}-${snapshotId}`.slice(0, 160),
      },
    },
  );
  report.preparationBatchId = result.payload.batch_id || null;
  return result.payload;
}

function matchingPreparationItem(batch, expectedDocument) {
  const items = Array.isArray(batch?.items) ? batch.items : [];
  return items.find(
    (item) =>
      item.document_id === expectedDocument.document_id ||
      (item.nct_id === expectedNctId && item.filename === expectedDocument.filename),
  );
}

async function ensureExtractionReview(projectId, item, workspace, report) {
  const existing = captureRealExtractionRevision(workspace, item.artifact_id);
  if (existing) return existing;
  if (!item.extraction_revision) {
    throw new Error(`preparation item ${item.item_id} has no extraction_revision`);
  }
  const spansResult = await apiJson(
    "GET",
    `/api/projects/${projectId}/medical-writing/references/documents/${item.artifact_id}/spans?extraction_revision=${encodeURIComponent(item.extraction_revision)}&limit=1`,
  );
  const confirmedAnchorCoverage = Object.keys(spansResult.payload?.anchor_counts || {})
    .filter((anchor) => anchor && anchor !== "unmapped")
    .sort();
  if (!confirmedAnchorCoverage.length) {
    throw new Error(
      `extraction ${item.extraction_revision} has no mapped M11 anchors to approve`,
    );
  }
  report.extractionAnchorCoverage = confirmedAnchorCoverage;
  const decision = await createExtractionReview(
    projectId,
    item.artifact_id,
    item.extraction_revision,
    confirmedAnchorCoverage,
    0,
    report,
  );
  return {
    extraction_revision: decision.extraction_revision,
    review_id: decision.review_id,
    review_revision: decision.revision,
  };
}

async function ensureDocumentValidation(projectId, item, workspace, report) {
  const validation = captureRealValidationRevision(workspace, item.artifact_id);
  if (!validation) {
    throw new Error(`no content-validation record for ${item.artifact_id}`);
  }
  if (["confirmed", "user_overridden"].includes(validation.validation_status)) {
    return validation;
  }
  const record = (workspace.document_validations || []).find(
    (entry) => entry.artifact_id === item.artifact_id,
  );
  const warningCodes = (record?.checks || [])
    .filter((check) => ["warning", "mismatch"].includes(check.outcome))
    .map((check) => check.check_code)
    .filter(Boolean);
  if (!warningCodes.length) {
    throw new Error(
      `content validation ${validation.validation_id} is ${validation.validation_status} without overridable warning codes`,
    );
  }
  const override = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/references/documents/${item.artifact_id}/content-validation/override`,
    {
      body: {
        reason:
          `跨适应症生产验收已核对${expectedNctId}、${expectedDocumentFilename}及Protocol/SAP文件角色；医学经理明确确认该公开原文用于本轮语料处理。`,
        acknowledged_warning_codes: warningCodes,
        actor: "medical_manager_qc",
        expected_revision: validation.validation_revision,
        idempotency_key: `cross-indication-validation-override-${indicationKey}-${item.artifact_id}`.slice(0, 200),
      },
    },
  );
  report.validationOverride = {
    validation_id: override.payload.validation_id,
    revision: override.payload.revision,
    acknowledged_warning_codes: warningCodes,
  };
  return {
    validation_id: override.payload.validation_id,
    validation_revision: override.payload.revision,
    validation_status: override.payload.status,
  };
}

function buildPicosPayload() {
  const phase = canonicalStudyPhase;
  const earlyPhase = phase.startsWith("I期");
  const endpointByIndication = {
    AD: "预设评价时点的特应性皮炎临床疗效指标较基线变化或应答率。",
    PNH: "预设评价期内乳酸脱氢酶控制及输血相关临床结局。",
    OBESITY: "预设评价时点体重较基线百分比变化。",
    SLE: "多次给药后的安全性、耐受性及药代动力学特征。",
  };
  return {
    design_archetype: earlyPhase ? "single_arm_early_phase" : "randomized_exploratory",
    field_applicability: earlyPhase
      ? {
          comparator_summary: {
            status: "not_applicable",
            reason: "本生产验收项目按早期剂量递增研究处理，对照设置需由正式项目团队确认。",
            confirmed_by_medical_manager: true,
          },
          estimand_strategy: {
            status: "not_applicable",
            reason: "本生产验收项目以早期安全性和药代评价为主，正式估计目标策略待项目确认。",
            confirmed_by_medical_manager: true,
          },
        }
      : {},
    population_summary: `${indication}${phase}临床研究目标人群，具体严重程度和既往治疗要求以项目方案决策为准。`,
    inclusion_modules: ["符合适应症诊断及项目规定的疾病活动度要求", "完成知情同意并可遵守访视安排"],
    exclusion_modules: ["存在影响安全性评价的活动性严重感染", "既往治疗未完成项目规定洗脱"],
    washout_rules: ["既往治疗按药代特征、作用机制及项目风险完成方案规定洗脱"],
    intervention_summary: `${productName}按项目确认的给药途径和剂量组进行研究。`,
    intervention_dose_regimen: "给药剂量、频次、递增或维持规则由项目医学团队在正式方案中确认。",
    allowed_concomitant_rules: ["允许不影响主要评价且经方案明确规定的稳定合并治疗"],
    required_background_rules: [],
    prohibited_concomitant_rules: ["可能混淆疗效评价或增加不可接受风险的同机制治疗"],
    assessment_timing_restrictions: ["关键疗效或安全性评估前遵守方案规定的药物和操作限制"],
    comparator_summary: earlyPhase ? "" : "对照类型、给药频次及匹配方式由正式项目设计确认。",
    primary_endpoint: endpointByIndication[indicationKey] || "预设主要评价时点的主要临床结局。",
    key_secondary_endpoints: ["预设次要时间点的临床疗效或药效学评价"],
    other_secondary_endpoints: [],
    exploratory_endpoints: ["药代动力学、药效动力学或生物标志物探索"],
    safety_endpoints: ["TEAE、SAE、导致停药的AE及临床实验室检查异常"],
    aesi_definitions: ["基于作用机制和适应症背景确认的特别关注不良事件"],
    study_epochs: earlyPhase
      ? ["筛选期", "剂量递增/治疗期", "安全性随访期"]
      : ["筛选期", "治疗期", "安全性随访期"],
    visit_strategy: "按筛选、基线、治疗期计划访视及末次给药后安全性随访组织访视。",
    estimand_strategy: earlyPhase
      ? ""
      : "正式项目应围绕主要终点明确治疗条件、目标人群、变量、伴发事件策略和汇总指标。",
    sample_size_strategy: earlyPhase
      ? "按早期剂量递增、安全性观察和PK/PD表征需要确定队列及样本量。"
      : "基于预期效应、变异度、显著性水平、把握度和脱落率估算。",
    statistical_strategy: earlyPhase
      ? "以描述性统计总结安全性、耐受性、PK及探索性PD结果。"
      : "按预设分析集和分层因素分析主要终点，并说明多重性和缺失数据处理。",
  };
}

async function commitPicos(projectId, journey, report) {
  const picos = buildPicosPayload();
  const preview = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/authoring-journey/impact-preview`,
    { body: { expected_revision: journey.revision, stage: "picos", picos } },
  );
  const result = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/authoring-journey/stages/picos/commit`,
    {
      body: {
        expected_revision: journey.revision,
        stage: "picos",
        picos,
        impact_preview_id: preview.payload.preview_id || "",
        actor: "medical_manager_qc",
        idempotency_key: `cross-indication-picos-${indicationKey}-${journey.revision}`.slice(0, 200),
      },
    },
  );
  report.picosRevision = result.payload.revision;
  return result.payload;
}

async function ensureWritingAccess(projectId, journey, report) {
  const recalculated = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/authoring-journey/corpus-gate/recalculate`,
  );
  let current = recalculated.payload;
  if (!current.corpus_gate?.access_permitted) {
    const missing = current.corpus_gate?.missing_requirements || [];
    if (!missing.length) throw new Error("corpus gate denied access without explicit missing requirements");
    const override = await apiJson(
      "POST",
      `/api/projects/${projectId}/medical-writing/authoring-journey/corpus-gate/override`,
      {
        body: {
          expected_revision: current.revision,
          reason:
            "跨适应症生产验收已完成目标公开方案的下载、提取、翻译、医学审核和章节准入；其余正式项目语料缺口保留并由医学经理确认。",
          acknowledged_missing_requirements: missing,
          actor: "medical_manager_qc",
          idempotency_key: `cross-indication-corpus-override-${indicationKey}-${current.revision}`.slice(0, 200),
        },
      },
    );
    current = override.payload;
    report.corpusGateOverride = {
      active: true,
      acknowledged_missing_requirements: missing,
    };
  } else {
    report.corpusGateOverride = { active: false, acknowledged_missing_requirements: [] };
  }
  return current;
}

async function createGreenfieldDocument(projectId, journey, report) {
  const definition = journey.study_definition;
  if (!definition?.definition_id || !definition?.revision || !definition?.state_sha256) {
    throw new Error("study definition binding is incomplete before document creation");
  }
  const result = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/greenfield-document`,
    {
      body: {
        protocol_id: journey.framing.protocol_id,
        version: journey.framing.version,
        document_title: journey.framing.document_title,
        indication: journey.framing.indication,
        study_phase: journey.framing.study_phase,
        source_study_definition_id: definition.definition_id,
        source_study_definition_revision: definition.revision,
        source_study_definition_sha256: definition.state_sha256,
        template_id: "ich_m11_zh_cn",
        template_version: "ich_m11_zh_cn_step4_cde_consultation_2026_06_12_v1",
        actor: "medical_manager_qc",
        idempotency_key: `cross-indication-greenfield-${indicationKey}-${definition.definition_id}-${definition.revision}`.slice(0, 200),
      },
    },
  );
  report.documentId = result.payload.document?.document_id || null;
  return result.payload;
}

/**
 * Snapshot must paginate to completion.  The product snapshot includes
 * total_count and returned_count.  If returned_count < total_count, the
 * snapshot is incomplete and we record a gate failure.
 */
function validateSnapshotCompleteness(snapshot, report) {
  const totalCount = snapshot?.total_count || 0;
  const returnedCount = snapshot?.returned_count || 0;
  const candidates = Array.isArray(snapshot?.candidates) ? snapshot.candidates : [];
  report.searchSnapshot = {
    snapshot_id: snapshot?.snapshot_id || null,
    query_url: snapshot?.query_url || null,
    api_version: snapshot?.api_version || null,
    data_timestamp: snapshot?.data_timestamp || null,
    total_count: totalCount,
    returned_count: returnedCount,
    candidate_count: candidates.length,
    page_count: snapshot?.page_count || 0,
  };
  if (returnedCount < totalCount) {
    recordGateFailure(report, "GATE_CTGOV_UNREACHABLE", {
      evidence_locator: `snapshot returned ${returnedCount}/${totalCount} candidates`,
    });
    return false;
  }
  return true;
}

/**
 * Find the expected study in the fresh snapshot.  The lane must prove the
 * product search found the intended NCT, and that the chosen document role
 * matches Protocol or Protocol+SAP.
 */
function findExpectedStudy(snapshot, report) {
  const candidates = Array.isArray(snapshot?.candidates) ? snapshot.candidates : [];
  const expected = candidates.find((c) => c.nct_id === expectedNctId);
  if (!expected) {
    recordGateFailure(report, "GATE_EXPECTED_STUDY_NOT_FOUND", {
      nct_id: expectedNctId,
      evidence_locator: `expected ${expectedNctId} not in snapshot candidates (n=${candidates.length})`,
    });
    return null;
  }
  report.expectedStudyFound = {
    nct_id: expected.nct_id,
    brief_title: expected.brief_title || "",
    phases: expected.phases || [],
    conditions: expected.conditions || [],
  };
  // Find the expected document in public_documents
  const docs = Array.isArray(expected.public_documents) ? expected.public_documents : [];
  const expectedDoc = docs.find((d) => d.filename === expectedDocumentFilename);
  if (!expectedDoc) {
    recordGateFailure(report, "GATE_DOCUMENT_ROLE_MISMATCH", {
      nct_id: expectedNctId,
      evidence_locator: `expected document ${expectedDocumentFilename} not found in ${docs.length} public documents`,
    });
    return null;
  }
  report.expectedDocumentFound = {
    document_id: expectedDoc.document_id,
    filename: expectedDoc.filename,
    document_type: expectedDoc.document_type,
    download_url: expectedDoc.download_url,
    declared_size: expectedDoc.declared_size,
  };
  // Validate document role matches expectation
  const docType = (expectedDoc.document_type || "").toLowerCase();
  const roleOk =
    (expectedDocumentRole === "protocol_sap" &&
      (docType.includes("protocol") && docType.includes("sap"))) ||
    (expectedDocumentRole === "protocol" && docType.includes("protocol"));
  if (!roleOk) {
    recordGateFailure(report, "GATE_DOCUMENT_ROLE_MISMATCH", {
      nct_id: expectedNctId,
      evidence_locator: `document type "${expectedDoc.document_type}" does not match expected role "${expectedDocumentRole}"`,
    });
    return null;
  }
  // Validate download URL host is allowlisted
  let downloadHost = "";
  try {
    downloadHost = new URL(expectedDoc.download_url).hostname;
  } catch {
    downloadHost = "";
  }
  if (!ALLOWED_DOWNLOAD_HOSTS.includes(downloadHost)) {
    recordGateFailure(report, "GATE_DOWNLOAD_HOST_NOT_ALLOWED", {
      nct_id: expectedNctId,
      evidence_locator: `download host "${downloadHost}" not in allowlist`,
    });
    return null;
  }
  return { study: expected, document: expectedDoc };
}

/**
 * Poll the workspace until the artifact reaches a terminal state.
 * The workspace returns artifacts[], translations[], medical_reviews[],
 * approved_evidence_briefs[] arrays — NOT an "items" array.
 */
async function pollWorkspace(projectId, artifactId, timeoutMs, report) {
  const deadline = Date.now() + timeoutMs;
  let workspace;
  while (Date.now() < deadline) {
    const result = await apiJson(
      "GET",
      `/api/projects/${projectId}/medical-writing/references/workspace`,
    );
    workspace = result.payload;
    const artifacts = Array.isArray(workspace?.artifacts) ? workspace.artifacts : [];
    const target = artifacts.find((a) => a.artifact_id === artifactId);
    if (target) {
      const sourceStatus = (target.source_status || "").toLowerCase();
      const integrity = (target.file_integrity_status || "").toLowerCase();
      if (
        ["downloaded", "verified", "failed", "invalid"].includes(sourceStatus) ||
        integrity === "verified" ||
        integrity === "failed"
      ) {
        report.artifactEvidence = target;
        return workspace;
      }
    }
    await wait(3000);
  }
  report.artifactEvidence = null;
  return workspace;
}

/**
 * Capture REAL source receipts from the artifact record.  Never fabricate.
 *
 * validation_revision and extraction_revision are NOT on the artifact — they
 * come from real product records that are created asynchronously:
 *   - validation_revision from workspace.document_validations[] (revision field)
 *   - extraction_revision from workspace.extraction_reviews[] or preparation
 *     batch items (extraction_revision field)
 *
 * This function captures only artifact-level immutable receipt fields.  The
 * caller must separately call captureRealValidationRevision and
 * captureRealExtractionRevision after polling the workspace.
 *
 * Returns null if the artifact is missing required receipt fields.
 */
function captureSourceReceipt(artifact, nctId) {
  if (!artifact) return null;
  const finalUrl = artifact.final_url || "";
  const sha256 = artifact.content_sha256 || "";
  const bytes = artifact.actual_size || 0;
  if (!finalUrl || !sha256 || bytes < 1) return null;
  return {
    nct_id: nctId,
    document_role: artifact.document_type || "protocol",
    final_url: finalUrl,
    sha256,
    bytes,
    // These MUST be filled from real product records by the caller.
    // They start as not_observed and are overwritten by real values.
    validation_revision: null,
    extraction_revision: null,
  };
}

/**
 * Extract the real validation revision/status for an artifact from the
 * workspace's document_validations[] array.  These records are created by
 * the product's preparation batch workflow and carry an immutable revision.
 *
 * Returns { validation_id, validation_revision, validation_status } or null.
 */
/**
 * Poll the preparation batch until all items reach a terminal state.
 * The preparation batch carries items with artifact_id, extraction_revision,
 * validation_id and validation_status after ingest+extract+validate complete.
 */
async function pollPreparationBatch(projectId, snapshotId, timeoutMs, report) {
  const deadline = Date.now() + timeoutMs;
  let batch = null;
  const terminalStatuses = new Set([
    "completed",
    "completed_with_review_required",
    "completed_with_manual_upload_required",
    "partial_failure",
    "failed",
  ]);
  while (Date.now() < deadline) {
    try {
      const result = await apiJson(
        "GET",
        `/api/projects/${projectId}/medical-writing/references/preparation-batches/latest?snapshot_id=${encodeURIComponent(snapshotId)}`,
        { allowStatus: 404 },
      );
      if (result.status === 200) {
        batch = result.payload;
        if (batch && terminalStatuses.has(batch.status)) return batch;
      }
    } catch {
      // not yet created; keep polling
    }
    await wait(3000);
  }
  report.preparationBatchTimeout = true;
  return batch;
}

/**
 * Submit the extraction structure review using the REAL contract.
 * WritingReferenceExtractionReviewRequest requires:
 *   extraction_revision, decision, comment, expected_revision, idempotency_key
 *
 * expected_revision is the current review revision (0 for first review).
 */
async function createExtractionReview(
  projectId,
  artifactId,
  extractionRevision,
  confirmedAnchorCoverage,
  expectedRevision,
  report,
) {
  const result = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/references/documents/${artifactId}/extraction-reviews`,
    {
      body: {
        extraction_revision: extractionRevision,
        decision: "approved",
        confirmed_anchor_coverage: confirmedAnchorCoverage,
        unresolved_structure_issues: [],
        comment: `Cross-indication QC structure review for ${indicationKey}`,
        actor: "medical_manager_qc",
        expected_revision: expectedRevision,
        idempotency_key: `cross-indication-extraction-review-${indicationKey}-${Date.now()}`.slice(0, 200),
      },
    },
  );
  report.extractionReview = {
    review_id: result.payload.review_id || null,
    extraction_revision: result.payload.extraction_revision || null,
    decision: result.payload.decision || null,
    revision: result.payload.revision ?? null,
  };
  return result.payload;
}

/**
 * Preview and create a translation batch using the REAL contract.
 * The preview determines eligible spans; create kicks off background generation.
 */
async function createTranslationBatch(projectId, snapshotId, report) {
  const glossaryVersion = "cms_regulatory_zh_v1";
  const representativeAnchors = REPRESENTATIVE_CHAPTERS[indicationKey] || [];
  if (representativeAnchors.length < 2) {
    throw new Error(
      `at least two translation anchors are required for ${indicationKey}`,
    );
  }
  const anchorQuery = representativeAnchors
    .map((anchor) => `&anchor_filter=${encodeURIComponent(anchor)}`)
    .join("");

  // Preview (GET with query params)
  const previewResult = await apiJson(
    "GET",
    `/api/projects/${projectId}/medical-writing/references/translation-batches/preview?snapshot_id=${encodeURIComponent(snapshotId)}&glossary_version=${encodeURIComponent(glossaryVersion)}${anchorQuery}`,
    { allowStatus: 404 },
  );
  if (previewResult.status === 404 || !previewResult.payload) {
    recordGateFailure(report, "GATE_BACKEND_STAGE_MISSING", {
      evidence_locator: "translation-batch preview -> 404 or empty",
    });
    return null;
  }
  report.translationPreview = {
    eligible_count: previewResult.payload.eligible_count ?? 0,
    eligible_new_count: previewResult.payload.eligible_new_count ?? 0,
    existing_candidate_count: previewResult.payload.existing_candidate_count ?? 0,
    preparation_batch_id: previewResult.payload.preparation_batch_id || null,
    scope_sha256: previewResult.payload.scope_sha256 || null,
  };

  // Create (POST)
  const createResult = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/references/translation-batches`,
    {
      body: {
        snapshot_id: snapshotId,
        glossary_version: glossaryVersion,
        anchor_filter: representativeAnchors,
        actor: "medical_manager_qc",
        idempotency_key: `cross-indication-translation-${indicationKey}-${Date.now()}`.slice(0, 200),
      },
    },
  );
  report.translationBatchId = createResult.payload.batch_id || null;
  return createResult.payload;
}

/**
 * Poll the translation batch until it reaches a terminal state.
 * Terminal states: completed, completed_with_blocked, partial_failure, failed.
 */
async function pollTranslationBatch(projectId, batchId, timeoutMs, report) {
  const translationTimeout = Number(process.env.QC_TRANSLATION_TIMEOUT_S || 900);
  const deadline = Date.now() + timeoutMs;
  const terminalStatuses = new Set([
    "completed",
    "completed_with_blocked",
    "partial_failure",
    "failed",
  ]);
  let batch = null;
  while (Date.now() < deadline) {
    try {
      const result = await apiJson(
        "GET",
        `/api/projects/${projectId}/medical-writing/references/translation-batches/${encodeURIComponent(batchId)}`,
      );
      batch = result.payload;
      if (batch && terminalStatuses.has(batch.status)) return batch;
    } catch {
      // retry
    }
    await wait(5000);
  }
  report.translationBatchTimeout = true;
  return batch;
}

/**
 * Collect candidate-ready translation items from a completed translation batch.
 * Each item carries a real translation_id, translation_revision, and pipeline
 * lineage.  Fidelity-blocked or failed items block downstream review for their
 * associated span.
 */
function collectCandidateReadyItems(batch) {
  if (!batch || !Array.isArray(batch.items)) return [];
  return batch.items.filter(
    (item) =>
      item.generation_status === "candidate_ready" &&
      item.translation_id &&
      item.translation_revision >= 1,
  );
}

function terminalTranslationFailure(batch, artifactId) {
  const items = Array.isArray(batch?.items)
    ? batch.items.filter((item) => item.artifact_id === artifactId)
    : [];
  const summary = {
    status: batch?.status || null,
    item_count: items.length,
    error_codes: [...new Set(items.map((item) => item.error_code).filter(Boolean))],
    pipeline_stages: [
      ...new Set(items.map((item) => item.pipeline_stage).filter(Boolean)),
    ],
    failed_retryable: items.filter(
      (item) => item.generation_status === "failed_retryable",
    ).length,
    failed_terminal: items.filter(
      (item) => item.generation_status === "failed_terminal",
    ).length,
    fidelity_blocked: items.filter(
      (item) => item.generation_status === "fidelity_blocked",
    ).length,
    excluded: items.filter(
      (item) => item.generation_status === "excluded",
    ).length,
  };
  if (summary.error_codes.includes("document_plan_failed")) {
    return { summary, message: "document planner failed the bounded structure contract" };
  }
  if (summary.pipeline_stages.includes("integration_qc")) {
    return { summary, message: "Flash integration QC produced no candidate-ready translation" };
  }
  if (
    summary.pipeline_stages.includes("translating_hy_mt2") ||
    summary.error_codes.includes("translation_generation_failed")
  ) {
    return { summary, message: "Hy-MT2 translation produced no candidate-ready translation" };
  }
  if (summary.fidelity_blocked > 0) {
    return { summary, message: "translation fidelity gate blocked all selected chapters" };
  }
  return { summary, message: "translation pipeline produced no candidate-ready translation" };
}

/**
 * Submit medical review for a translation using the REAL contract.
 * WritingReferenceMedicalReviewRequest requires:
 *   translation_revision, decision, comment, expected_revision, idempotency_key
 *
 * expected_revision is the current review revision (0 for first review).
 */
async function submitMedicalReview(
  projectId,
  translationId,
  translationRevision,
  report,
) {
  const result = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/references/translations/${encodeURIComponent(translationId)}/medical-review`,
    {
      body: {
        translation_revision: translationRevision,
        decision: "approved",
        comment: `Cross-indication QC medical review for ${indicationKey}`,
        actor: "medical_manager_qc",
        expected_revision: 0,
        idempotency_key: `cross-indication-medical-review-${indicationKey}-${translationId}-${Date.now()}`.slice(0, 200),
      },
    },
  );
  return result.payload;
}

/**
 * Admit a translation to the corpus using the REAL contract.
 * WritingReferenceAdmissionRequest requires:
 *   expected_translation_revision, medical_review_id, idempotency_key
 */
async function admitTranslation(
  projectId,
  translationId,
  translationRevision,
  medicalReviewId,
  report,
) {
  const result = await apiJson(
    "POST",
    `/api/projects/${projectId}/medical-writing/references/translations/${encodeURIComponent(translationId)}/admissions`,
    {
      body: {
        expected_translation_revision: translationRevision,
        medical_review_id: medicalReviewId,
        idempotency_key: `cross-indication-admission-${indicationKey}-${translationId}-${Date.now()}`.slice(0, 200),
      },
    },
  );
  return result.payload;
}

/**
 * Fetch evidence briefs from the product.
 * Each brief carries brief_id, ich_m11_anchor, translation_id, span_id.
 */
async function getEvidenceBriefs(projectId) {
  const result = await apiJson(
    "GET",
    `/api/projects/${projectId}/medical-writing/references/evidence-briefs`,
  );
  return Array.isArray(result.payload) ? result.payload : [];
}

/**
 * Fetch a working copy for invariance checking.
 * Returns { section_id, revision, content_sha256 (computed) } or null.
 */
async function getWorkingCopy(projectId, sectionId) {
  const result = await apiJson(
    "GET",
    `/api/projects/${projectId}/medical-writing/working-copies/${encodeURIComponent(sectionId)}`,
    { allowStatus: 404 },
  );
  if (result.status === 404 || !result.payload) return null;
  const wc = result.payload;
  // Compute a canonical content hash from content_blocks for invariance
  const contentHash = createHash("sha256")
    .update(JSON.stringify(wc.content_blocks || []))
    .digest("hex");
  return {
    section_id: sectionId,
    revision: wc.revision ?? null,
    content_sha256: contentHash,
    working_copy_id: wc.working_copy_id || null,
    content_blocks: Array.isArray(wc.content_blocks) ? wc.content_blocks : [],
  };
}

/**
 * Create a revision thread using the REAL MedicalWritingRevisionRequest contract.
 * intent must be a real intent (e.g. "medical_writing_revision"), NOT
 * "generate_candidates".
 *
 * Requires: section_id (real, from document state), user_instruction,
 * evidence_brief_ids (from admitted evidence), requested_by.
 */
async function createRevisionThread(
  projectId,
  sectionId,
  userInstruction,
  evidenceBriefIds,
  anchorPath,
  selectedText,
  report,
) {
  const body = {
    section_id: sectionId,
    anchor_type: "paragraph",
    anchor_path: anchorPath,
    selected_text: selectedText,
    user_instruction: userInstruction,
    intent: "medical_writing_revision",
    evidence_brief_ids: evidenceBriefIds,
    requested_by: "medical_manager_qc",
  };
  try {
    const result = await apiJson(
      "POST",
      `/api/projects/${projectId}/revision-threads`,
      { body },
    );
    return result.payload;
  } catch (error) {
    if (error?.status) throw error;
    const recoveryStarted = Date.now();
    const recoveryTimeoutMs = Number(
      process.env.QC_REVISION_RECOVERY_TIMEOUT_MS
        || (Number(process.env.QC_CANDIDATE_TIMEOUT_S || 900) * 1000),
    );
    while (Date.now() - recoveryStarted < recoveryTimeoutMs) {
      try {
        const existing = await apiJson(
          "GET",
          `/api/projects/${projectId}/revision-threads`,
        );
        const recovered = (Array.isArray(existing.payload) ? existing.payload : [])
          .find((thread) => (
            thread.section_id === sectionId
            && thread.anchor_path === anchorPath
            && thread.user_instruction === userInstruction
            && JSON.stringify([...(thread.evidence_brief_ids || [])].sort())
              === JSON.stringify([...evidenceBriefIds].sort())
          ));
        if (recovered) {
          report.recoveredRevisionRequests = [
            ...(report.recoveredRevisionRequests || []),
            {
              section_id: sectionId,
              thread_id: recovered.thread_id,
              recovery_reason: error.message,
            },
          ];
          return { thread: recovered };
        }
      } catch {
        // The API may still be processing the original request.
      }
      await wait(2_000);
    }
    const retry = await apiJson(
      "POST",
      `/api/projects/${projectId}/revision-threads`,
      { body },
    );
    report.retriedRevisionRequests = [
      ...(report.retriedRevisionRequests || []),
      {
        section_id: sectionId,
        retry_reason: error.message,
      },
    ];
    return retry.payload;
  }
}

function captureRealValidationRevision(workspace, artifactId) {
  const validations = Array.isArray(workspace?.document_validations)
    ? workspace.document_validations
    : [];
  const target = validations.find((v) => v.artifact_id === artifactId);
  if (!target) return null;
  const validationId = target.validation_id || "";
  const revision = typeof target.revision === "number" ? target.revision : null;
  const status = target.status || "";
  if (!validationId || revision === null || !status) return null;
  return {
    validation_id: validationId,
    validation_revision: revision,
    validation_status: status,
  };
}

/**
 * Extract the real extraction revision for an artifact from the workspace's
 * extraction_reviews[] array or artifact_span_counts.  The extraction_reviews
 * carry the reviewed extraction_revision with an immutable review revision.
 *
 * Returns { extraction_revision, review_id, review_revision } or null.
 */
function captureRealExtractionRevision(workspace, artifactId) {
  const reviews = Array.isArray(workspace?.extraction_reviews)
    ? workspace.extraction_reviews
    : [];
  const target = reviews.find((r) => r.artifact_id === artifactId);
  if (!target) return null;
  const extractionRevision = target.extraction_revision || "";
  const reviewId = target.review_id || "";
  const reviewRevision = typeof target.revision === "number" ? target.revision : null;
  if (!extractionRevision || !reviewId || reviewRevision === null) return null;
  return {
    extraction_revision: extractionRevision,
    review_id: reviewId,
    review_revision: reviewRevision,
  };
}

/**
 * Working-copy invariance check using REAL records.
 * Both before and after must exist, have real hashes and revisions, and match.
 * Missing records are not_observed, never pass.
 */
function checkWorkingCopyInvariance(before, after) {
  if (!before || !after) return { observed: false, unchanged: null, reason: "not_observed" };
  const hashBefore = before.content_sha256 || before.hash || null;
  const hashAfter = after.content_sha256 || after.hash || null;
  const revBefore = before.revision ?? null;
  const revAfter = after.revision ?? null;
  if (!hashBefore || !hashAfter || revBefore === null || revAfter === null) {
    return { observed: false, unchanged: null, reason: "missing_hash_or_revision" };
  }
  return {
    observed: true,
    unchanged: hashBefore === hashAfter && revBefore === revAfter,
    hashBefore,
    hashAfter,
    revBefore,
    revAfter,
    reason: hashBefore === hashAfter && revBefore === revAfter ? "unchanged" : "mutated",
  };
}

/**
 * Build a quality_scorecard with the correct lifecycle state:
 * - blocked_before_review: upstream gates prevented real candidate sets.
 * - pending_blind_review: real candidate sets exist but not yet scored.
 * Scores are NEVER self-assigned.
 */
function buildQualityScorecard(report, candidateSets) {
  const hasRealCandidates = candidateSets.some(
    (set) => Array.isArray(set.candidates) && set.candidates.length >= 3,
  );
  const reviewStatus = hasRealCandidates
    ? "pending_blind_review"
    : "blocked_before_review";

  const scorecard = {
    schema_version: "mw_cross_indication_quality_v1",
    review_status: reviewStatus,
    project_id: report.projectId || "",
    indication: report.indicationLabel,
    study_phase: report.studyPhase,
    source_receipts: (report.sourceReceipts || []).filter(
      (receipt) =>
        Number.isInteger(receipt.validation_revision) &&
        receipt.validation_revision >= 1 &&
        typeof receipt.extraction_revision === "string" &&
        receipt.extraction_revision.length > 0,
    ),
    translation_samples: [],
    candidate_sets: candidateSets,
    open_findings: report.gateFailures.map((failure, index) => ({
      finding_id: `${indicationKey}-gate-${index}`,
      severity: failure.severity,
      category: failure.gate_code,
      description: failure.description,
      evidence_locator: failure.evidence_locator || `${failure.stage}:${failure.gate_code}`,
      status: "open",
    })),
    gate: {
      average_score: null,
      open_p0: report.gateFailures.filter((f) => f.severity === "P0").length,
      open_p1: report.gateFailures.filter((f) => f.severity === "P1").length,
      working_copy_unchanged_after_generation: null,
      passed: false,
    },
  };

  // Only compute working_copy_unchanged if all candidate sets were observed
  if (candidateSets.length > 0 && report.candidateInvariance?.observed) {
    scorecard.gate.working_copy_unchanged_after_generation =
      report.candidateInvariance.unchanged;
  }

  return scorecard;
}

function validateQualityScorecardFile(scorecardPath) {
  const schemaPath = path.join(
    projectRoot,
    "records/active_slices/medical_writing_cross_indication_reference_gate_20260718/quality_scorecard.schema.json",
  );
  const validationScript = [
    "import json, sys",
    "from pathlib import Path",
    "from jsonschema import Draft202012Validator, FormatChecker",
    "schema=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))",
    "instance=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))",
    "errors=sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance), key=lambda e:list(e.path))",
    "print(json.dumps([{'path':'/'.join(map(str,e.path)),'message':e.message} for e in errors], ensure_ascii=False))",
    "raise SystemExit(1 if errors else 0)",
  ].join("\n");
  const result = spawnSync(
    process.env.PYTHON_BIN || "python3",
    ["-c", validationScript, schemaPath, scorecardPath],
    { encoding: "utf8", maxBuffer: 4 * 1024 * 1024 },
  );
  if (result.status !== 0) {
    throw new Error(
      `quality scorecard schema validation failed: ${(result.stdout || result.stderr || "").trim()}`,
    );
  }
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "cross-indication-child-"));
  const chrome = spawn(
    chromePath,
    [
      "--headless=new",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${userDataDir}`,
      "--no-first-run",
      "--no-default-browser-check",
      "about:blank",
    ],
    { stdio: "ignore" },
  );

  const pageErrors = [];
  const httpFailures = [];
  let cdp;

  const report = {
    indication: indicationKey,
    indicationLabel: indication,
    studyPhase,
    projectCode,
    productName,
    mode: DRY_RUN ? "dry-run" : "full",
    passed: false,
    projectId: null,
    framingRevision: null,
    searchPlanId: null,
    searchSnapshot: null,
    expectedStudyFound: null,
    expectedDocumentFound: null,
    artifactEvidence: null,
    sourceReceipts: [],
    pipelineLineage: null,
    candidateSets: [],
    docxExported: false,
    gateFailures: [],
    pageErrors,
    httpFailures,
    failures: [],
    screenshots: [],
    // Internal flags for scorecard building
    _invarianceObserved: false,
    _workingCopyUnchanged: null,
  };

  try {
    await waitForJson(`${apiUrl}/api/health`);
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    cdp = createCdp(targets.find((item) => item.type === "page").webSocketDebuggerUrl);
    await cdp.ready;
    cdp.on("Runtime.exceptionThrown", (event) =>
      pageErrors.push(event.exceptionDetails?.exception?.description || event.exceptionDetails?.text),
    );
    cdp.on("Network.responseReceived", (event) => {
      if (event.response.status >= 400) {
        httpFailures.push({ url: event.response.url, status: event.response.status });
      }
    });
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");

    // 1920x1080 primary evidence
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 1920,
      height: 1080,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);
    await screenshot(cdp, "dashboard_loaded.png");

    // --- Step 1: Create project via UI ---
    const projectId = await createProjectViaUi(cdp, report);
    report.projectId = projectId;

    // --- Step 2: Get journey revision for optimistic concurrency ---
    const journey = await getJourney(projectId);
    report.initialRevision = journey.revision;

    // --- Step 3: Verify core reference-workspace route contract ---
    const workspaceCheck = await apiJson(
      "GET",
      `/api/projects/${projectId}/medical-writing/references/workspace`,
      { allowStatus: 404 },
    );
    report.workspaceRoutePresent = workspaceCheck.status !== 404;

    if (DRY_RUN) {
      // Dry-run stops here: verify selector contracts, no external calls.
      // Verify the authoring journey shell is visible (real UI state)
      const shellVisible = await evaluate(
        cdp,
        `Boolean(document.querySelector('.authoring-journey-shell'))`,
      );
      if (!shellVisible) report.failures.push("dry-run:authoring-journey-shell-not-visible");

      // Verify project selector has the new project
      const selectorValue = await evaluate(
        cdp,
        `document.querySelector('select[aria-label="选择临床研究项目"]')?.value || null`,
      );
      if (!selectorValue) report.failures.push("dry-run:project-selector-empty");

      // Verify new-project dialog is closed
      const dialogOpen = await evaluate(
        cdp,
        `Boolean(document.querySelector('.new-project-dialog'))`,
      );
      if (dialogOpen) report.failures.push("dry-run:new-project-dialog-still-open");

      await screenshot(cdp, "dry_run_complete.png");

      report.passed = report.failures.length === 0 && report.gateFailures.length === 0;
      const dryRunEvidence = {
        project_id: projectId,
        workspace_route_present: report.workspaceRoutePresent,
        authoring_journey_shell_visible: shellVisible,
        project_selector_value: selectorValue,
        new_project_dialog_closed: !dialogOpen,
        page_errors: pageErrors,
        http_failures: httpFailures,
        passed: report.passed,
      };
      const dryRunArtifacts = {
        "source_receipts.json": [],
        "pipeline_lineage.json": [],
        "chapter_mapping.json": [],
        "candidate_sets.json": [],
        "quality_scorecard.json": [],
        "browser_qc.json": [
          {
            indication: "DRY",
            page_errors: pageErrors,
            http_failures: httpFailures,
            project_id: projectId,
          },
        ],
        dry_run_evidence: dryRunEvidence,
      };
      await writeFile(
        path.join(outputDir, "lane_artifacts.json"),
        JSON.stringify(dryRunArtifacts, null, 2),
      );
      for (const [name, content] of Object.entries(dryRunArtifacts)) {
        if (!name.endsWith(".json")) continue;
        await writeFile(
          path.join(outputDir, name),
          JSON.stringify(content, null, 2),
        );
      }
      console.log(JSON.stringify(dryRunEvidence, null, 2));
      return;
    }

    // === FULL MODE ===

    // --- Steps 4-6: complete both guided-design stages and fresh search ---
    const framed = await commitFraming(projectId, journey, report);
    if (!report.searchPlanId) {
      throw new Error("framing commit did not return search_plan.plan_id");
    }
    await commitPicos(projectId, framed, report);
    const searchResult = await competitorSearch(projectId, report.searchPlanId, report);
    const snapshot = searchResult.snapshot;
    if (!validateSnapshotCompleteness(snapshot, report)) {
      throw new Error("fresh ClinicalTrials.gov snapshot is incomplete");
    }
    const found = findExpectedStudy(snapshot, report);
    if (!found) throw new Error(`expected study ${expectedNctId} was not found`);

    // --- Steps 7-9: medical relevance, locked basket, real preparation batch ---
    await recordExpectedStudyRelevance(
      projectId,
      snapshot.snapshot_id,
      found.study.nct_id,
      report,
    );
    const triaged = await finalizeCompetitorTriage(
      projectId,
      searchResult.journey,
      snapshot.snapshot_id,
      found.study.nct_id,
      report,
    );
    await createPreparationBatch(projectId, snapshot.snapshot_id, report);
    const preparationBatch = await pollPreparationBatch(
      projectId,
      snapshot.snapshot_id,
      Number(process.env.QC_OCR_TIMEOUT_S || 600) * 1000,
      report,
    );
    report.preparationBatch = preparationBatch;
    if (!preparationBatch || ["failed", "partial_failure"].includes(preparationBatch.status)) {
      throw new Error(
        `preparation batch did not complete cleanly: ${preparationBatch?.status || "missing"}`,
      );
    }
    const preparationItem = matchingPreparationItem(preparationBatch, found.document);
    if (!preparationItem?.artifact_id) {
      throw new Error(`prepared artifact missing for ${found.document.filename}`);
    }
    const artifactId = preparationItem.artifact_id;

    // --- Steps 10-11: content validation and explicit structure review ---
    let workspace = await pollWorkspace(projectId, artifactId, 600000, report);
    let validationReceipt = await ensureDocumentValidation(
      projectId,
      preparationItem,
      workspace,
      report,
    );
    let extractionReceipt = await ensureExtractionReview(
      projectId,
      preparationItem,
      workspace,
      report,
    );
    workspace = await pollWorkspace(projectId, artifactId, 120000, report);
    validationReceipt = captureRealValidationRevision(workspace, artifactId) || validationReceipt;
    extractionReceipt = captureRealExtractionRevision(workspace, artifactId) || extractionReceipt;

    const receipt = captureSourceReceipt(report.artifactEvidence, found.study.nct_id);
    if (!receipt || !validationReceipt || !extractionReceipt) {
      throw new Error("immutable source, validation, or extraction receipt is incomplete");
    }
    receipt.validation_revision = validationReceipt.validation_revision;
    receipt.extraction_revision = extractionReceipt.extraction_revision;
    const extraction = (workspace.extractions || []).find(
      (entry) => entry.artifact_id === artifactId,
    );
    if (Array.isArray(extraction?.ocr_recovery_pages) && extraction.ocr_recovery_pages.length) {
      receipt.ocr_pages = extraction.ocr_recovery_pages
        .map((entry) => Number(entry.physical_page))
        .filter((page) => Number.isInteger(page) && page >= 1);
    }
    report.sourceReceipts.push(receipt);

    // --- Step 12: document-level translation pipeline ---
    const translationBatch = await createTranslationBatch(
      projectId,
      snapshot.snapshot_id,
      report,
    );
    if (!translationBatch?.batch_id) throw new Error("translation batch was not created");
    report.translationBatch = await pollTranslationBatch(
      projectId,
      translationBatch.batch_id,
      Number(process.env.QC_TRANSLATION_TIMEOUT_S || 900) * 1000,
      report,
    );
    if (
      report.translationBatchTimeout ||
      !new Set([
        "completed",
        "completed_with_blocked",
        "partial_failure",
        "failed",
      ]).has(report.translationBatch?.status)
    ) {
      report.translationFailureSummary = terminalTranslationFailure(
        report.translationBatch,
        artifactId,
      ).summary;
      throw new Error(
        `translation batch timed out while status=${
          report.translationBatch?.status || "unknown"
        }`,
      );
    }
    const allReadyItems = collectCandidateReadyItems(report.translationBatch);
    const candidateItems = allReadyItems.filter((item) => item.artifact_id === artifactId);
    if (!candidateItems.length) {
      const terminalFailure = terminalTranslationFailure(
        report.translationBatch,
        artifactId,
      );
      report.translationFailureSummary = terminalFailure.summary;
      throw new Error(terminalFailure.message);
    }
    report.candidateReadyCount = candidateItems.length;
    report.progressEvidence = {
      preparation_status: preparationBatch.status,
      translation_status: report.translationBatch?.status || null,
      document_total: Math.max(...candidateItems.map((item) => Number(item.document_total) || 0)),
      chapter_total: Math.max(...candidateItems.map((item) => Number(item.chapter_total) || 0)),
      chunk_total: candidateItems.reduce((sum, item) => sum + (Number(item.chunk_count) || 0), 0),
      terminal_stage: candidateItems.every((item) => item.pipeline_stage === "candidate_ready")
        ? "candidate_ready"
        : "not_terminal",
    };

    // --- Steps 13-14: two representative anchors, review, and admission ---
    const representativeChapters = REPRESENTATIVE_CHAPTERS[indicationKey] || [];
    if (representativeChapters.length < 2) {
      throw new Error(`at least two representative anchors are required for ${indicationKey}`);
    }
    const uniqueByTranslation = new Map();
    for (const item of candidateItems) {
      if (!uniqueByTranslation.has(item.translation_id)) {
        uniqueByTranslation.set(item.translation_id, item);
      }
    }
    const selectedForAdmission = representativeChapters.map((anchor) => {
      const item = [...uniqueByTranslation.values()].find(
        (candidate) => candidate.ich_m11_anchor === anchor,
      );
      if (!item) throw new Error(`no candidate-ready translation for required anchor ${anchor}`);
      return { anchor, item };
    });

    const chapterMapping = [];
    for (const { anchor, item } of selectedForAdmission) {
      const reviewDecision = await submitMedicalReview(
        projectId,
        item.translation_id,
        item.translation_revision,
        report,
      );
      if (!reviewDecision.review_id) {
        throw new Error(`medical review returned no review_id for ${item.translation_id}`);
      }
      const admission = await admitTranslation(
        projectId,
        item.translation_id,
        item.translation_revision,
        reviewDecision.review_id,
        report,
      );
      if (!admission.brief_id) {
        throw new Error(`corpus admission returned no brief_id for ${item.translation_id}`);
      }
      chapterMapping.push({
        brief_id: admission.brief_id,
        translation_id: item.translation_id,
        translation_revision: item.translation_revision,
        medical_review_id: reviewDecision.review_id,
        nct_id: item.nct_id,
        artifact_id: item.artifact_id,
        span_id: item.span_id,
        ich_m11_anchor: anchor,
        source_locator: item.source_locator || "",
        target_template_node_id: CHAPTER_TARGET_SECTIONS[anchor],
        target_section_id: "",
        target_section_heading: "",
        chapter_selection_reason: `Required ${anchor} evidence for ${indicationKey}`,
      });
    }
    report.chapterMapping = chapterMapping;
    report.admittedBriefIds = chapterMapping.map((item) => item.brief_id);
    report.evidenceBriefCount = (await getEvidenceBriefs(projectId)).length;

    // --- Steps 15-16: create the actual protocol workbench document ---
    const writingJourney = await ensureWritingAccess(projectId, triaged, report);
    const createdDocument = await createGreenfieldDocument(projectId, writingJourney, report);
    const document = createdDocument.document;
    const documentSections = document?.sections || [];
    const documentSectionIds = new Set(
      documentSections.map((section) => section.section_id),
    );
    if (!document?.document_id || documentSectionIds.size === 0) {
      throw new Error("greenfield protocol document or sections were not created");
    }
    const sectionsByTemplateNode = new Map(
      documentSections
        .filter((section) => section.template_node_id && section.section_id)
        .map((section) => [section.template_node_id, section]),
    );
    for (const mapping of chapterMapping) {
      const targetSection = sectionsByTemplateNode.get(
        mapping.target_template_node_id,
      );
      if (!targetSection) {
        throw new Error(
          `target M11 template node ${mapping.target_template_node_id || "missing"} is absent`,
        );
      }
      mapping.target_section_id = targetSection.section_id;
      mapping.target_section_heading = targetSection.heading || "";
    }

    // --- Step 17: one evidence-specific AI candidate set per target section ---
    const candidateSets = [];
    const invarianceResults = [];
    for (const mapping of chapterMapping) {
      const sectionId = mapping.target_section_id;
      if (!sectionId || !documentSectionIds.has(sectionId)) {
        throw new Error(`target M11 section ${sectionId || "missing"} is absent`);
      }
      const before = await getWorkingCopy(projectId, sectionId);
      if (!before) throw new Error(`working copy missing for ${sectionId}`);
      const blankBodyBlocks = before.content_blocks.filter(
        (block) =>
          block?.block_type === "paragraph" &&
          block?.source_kind === "greenfield_scaffold" &&
          String(block?.text || "").trim() === "" &&
          /^greenfield:[^:]+:section:[^:]+:body:\d+$/.test(
            String(block?.source_locator || ""),
          ),
      );
      if (blankBodyBlocks.length !== 1) {
        throw new Error(
          `target section ${sectionId} must expose exactly one blank greenfield body block`,
        );
      }
      const targetBodyBlock = blankBodyBlocks[0];
      const response = await createRevisionThread(
        projectId,
        sectionId,
        `基于已准入的${mapping.ich_m11_anchor}竞品方案证据，为${indication}${canonicalStudyPhase}研究的当前章节生成3-5个可直接审阅的监管中文候选；不得补造剂量、阈值、时点或统计假设。`,
        [mapping.brief_id],
        targetBodyBlock.source_locator,
        "",
        report,
      );
      const thread = response.thread || response;
      const suggestions = Array.isArray(thread.suggestions) ? thread.suggestions : [];
      if (suggestions.length < 3 || suggestions.length > 5) {
        throw new Error(
          `revision thread ${thread.thread_id || "missing"} returned ${suggestions.length} suggestions`,
        );
      }
      const after = await getWorkingCopy(projectId, sectionId);
      const invariance = checkWorkingCopyInvariance(before, after);
      invarianceResults.push(invariance);
      if (!invariance.observed || !invariance.unchanged) {
        recordGateFailure(report, "GATE_WORKING_COPY_MUTATED", {
          evidence_locator: `${sectionId}:${invariance.reason}`,
        });
      }
      candidateSets.push({
        section_id: sectionId,
        working_copy_hash_before: before.content_sha256,
        working_copy_hash_after: after.content_sha256,
        working_copy_revision_before: before.revision,
        working_copy_revision_after: after.revision,
        review_status: "pending_blind_review",
        recommended_candidate_id: null,
        group_passed: null,
        needs_prompt_or_pipeline_repair: null,
        candidates: suggestions.map((suggestion) => ({
          item_id: suggestion.suggestion_id,
          target_section_id: sectionId,
          source_span_ids:
            suggestion.evidence_span_ids?.length > 0
              ? suggestion.evidence_span_ids
              : [mapping.span_id],
          text: suggestion.proposal_text,
          scores: null,
          unsupported_claim_count: null,
          material_defects: [],
          reviewer_role: null,
        })),
      });
    }
    report.candidateSets = candidateSets;
    report.candidateInvariance = {
      observed: invarianceResults.every((item) => item.observed),
      unchanged: invarianceResults.every((item) => item.unchanged),
    };
    report.pipelineLineage = selectedForAdmission.map(({ anchor, item }) => ({
      artifact_id: artifactId,
      nct_id: found.study.nct_id,
      ich_m11_anchor: anchor,
      translation_id: item.translation_id,
      translation_revision: item.translation_revision,
      fidelity_status: item.fidelity_status,
      fidelity_failure_codes: item.fidelity_failure_codes || [],
      pipeline_stage: item.pipeline_stage,
      document_structure_plan_id: item.document_structure_plan_id || null,
      chapter_id: item.chapter_id || null,
      chapter_title: item.chapter_title || null,
      chunk_count: item.chunk_count || null,
      chunk_completed: item.chunk_completed || null,
      flash_plan_model: item.flash_plan_model || null,
      hy_mt2_model: item.hy_mt2_model || null,
      flash_qc_model: item.flash_qc_model || null,
      ocr_lineage_json: item.ocr_lineage_json || null,
      ai_run_id: item.ai_run_id || null,
      extraction_revision: item.extraction_revision,
      validation_revision: item.validation_revision,
      structure_review_id: item.structure_review_id,
      span_id: item.span_id,
    }));

    // Candidate generation is read-only; no action/apply route is invoked.
    await screenshot(cdp, "lane_evidence_captured.png");
    report.passed = report.gateFailures.length === 0 && report.failures.length === 0;
  } catch (error) {
    const detail = `${error.status || "error"}:${error.message}`;
    report.failures.push(detail);
    if (error.status === 404) {
      recordGateFailure(report, "GATE_BACKEND_STAGE_MISSING", {
        evidence_locator: detail,
      });
    } else if (
      /ClinicalTrials|competitor-search|expected study|snapshot/i.test(error.message)
    ) {
      recordGateFailure(report, "GATE_CTGOV_UNREACHABLE", {
        evidence_locator: detail,
      });
    } else if (/translation batch timed out/i.test(error.message)) {
      recordGateFailure(report, "GATE_TRANSLATION_TIMEOUT", {
        evidence_locator: detail,
      });
    } else if (/document planner|bounded structure contract|toc planning/i.test(error.message)) {
      recordGateFailure(report, "GATE_FLASH_PLAN_UNAVAILABLE", {
        evidence_locator: detail,
      });
    } else if (/Flash integration|integration QC/i.test(error.message)) {
      recordGateFailure(report, "GATE_FLASH_QC_UNAVAILABLE", {
        evidence_locator: detail,
      });
    } else if (/fidelity gate blocked/i.test(error.message)) {
      recordGateFailure(report, "GATE_FIDELITY_BLOCKED", {
        evidence_locator: detail,
      });
    } else if (/Hy-MT2|translation batch|translation pipeline/i.test(error.message)) {
      recordGateFailure(report, "GATE_HY_MT2_UNAVAILABLE", {
        evidence_locator: detail,
      });
    } else if (/revision thread|suggestions|candidate/i.test(error.message)) {
      recordGateFailure(report, "GATE_PRO_CANDIDATE_UNAVAILABLE", {
        evidence_locator: detail,
      });
    }
    report.passed = false;
  } finally {
    cdp?.close();
    await stopChrome(chrome, userDataDir);
  }

  // --- Persist lane artifacts ---
  const sourceReceipts = report.sourceReceipts;
  const pipelineLineage = Array.isArray(report.pipelineLineage)
    ? report.pipelineLineage
    : report.pipelineLineage
      ? [report.pipelineLineage]
      : [];
  const candidateSets = report.candidateSets;
  let qualityScorecard = buildQualityScorecard(report, candidateSets);
  const browserQc = [
    {
      indication: indicationKey,
      page_errors: pageErrors,
      http_failures: httpFailures,
      horizontal_overflow_1600x1000: report.failures.includes("horizontal-overflow@1600x1000"),
      aria_busy_at_terminal: report.failures.includes("aria-busy-true-at-terminal-state"),
    },
  ];

  const laneArtifacts = {
    "source_receipts.json": sourceReceipts,
    "pipeline_lineage.json": pipelineLineage,
    "chapter_mapping.json": report.chapterMapping || [],
    "candidate_sets.json": candidateSets,
    "quality_scorecard.json": qualityScorecard,
    "browser_qc.json": browserQc,
  };

  const scorecardPath = path.join(outputDir, "quality_scorecard.json");
  await writeFile(scorecardPath, JSON.stringify(qualityScorecard, null, 2));
  try {
    validateQualityScorecardFile(scorecardPath);
    report.qualityScorecardSchemaValid = true;
  } catch (error) {
    report.qualityScorecardSchemaValid = false;
    report.failures.push(error.message);
    report.passed = false;
    qualityScorecard = buildQualityScorecard(report, candidateSets);
    laneArtifacts["quality_scorecard.json"] = qualityScorecard;
    await writeFile(scorecardPath, JSON.stringify(qualityScorecard, null, 2));
  }

  await writeFile(
    path.join(outputDir, "lane_artifacts.json"),
    JSON.stringify(laneArtifacts, null, 2),
  );
  for (const [name, content] of Object.entries(laneArtifacts)) {
    if (name === "quality_scorecard.json") continue;
    await writeFile(path.join(outputDir, name), JSON.stringify(content, null, 2));
  }
  await writeFile(
    path.join(outputDir, "lane_report.json"),
    JSON.stringify(report, null, 2),
  );

  console.log(
    JSON.stringify(
      {
        indication: indicationKey,
        mode: report.mode,
        passed: report.passed,
        gateFailures: report.gateFailures,
        failures: report.failures,
        sourceReceipts: sourceReceipts.length,
      },
      null,
      2,
    ),
  );

  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
