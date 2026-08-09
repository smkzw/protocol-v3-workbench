import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

if (process.env.QC_ISOLATED_RUNTIME !== "1") {
  throw new Error("PNH corpus translation QC mutates runtime state and requires QC_ISOLATED_RUNTIME=1");
}

const appUrl = new URL(process.env.APP_URL || "http://127.0.0.1:5194/");
const projectId = process.env.PROJECT_ID || "proj_user_4bc29da4ac72";
const artifactId = process.env.ARTIFACT_ID || "wref_doc_75bbcd4e429345e6ab65";
const outputDir = path.resolve(process.env.QC_OUTPUT_DIR || "records/medical_writing_pnh_corpus_translation_qc");
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || (9720 + (process.pid % 150)));
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const selectedSpans = [
  {
    anchor: "objectives_endpoints",
    spanId: "wref_span_13b438905bc109bc99a244cc",
    sourceNeedle: "Data analysis The primary efficacy variable",
    review: "已逐句核对完整主要疗效变量、应答者定义、LDH阈值、较基线下降比例、观察至第12周及PoC成功判据；译文为完整句且医学含义与原文一致。",
    rejectPatterns: ["缓解率", "缓解者"],
    repair: "按同适应症公司中文语料统一术语：PNH疗效语境下response rate译为应答率，responder译为应答者，不得使用缓解率/缓解者。保留完整的LDH阈值、较基线下降比例、第12周观察终点及PoC成功判据。",
  },
  {
    anchor: "eligibility",
    spanId: "wref_span_3b3f2d35a1ea33b9df0941de",
    sourceNeedle: "Written informed consent",
    review: "已逐项核对知情同意、成人年龄、PNH诊断、克隆比例阈值及流式细胞术限定；译文未增加CMS-D017项目事实。",
    rejectPatterns: ["克隆大小", "基于记录到的通过", "经RBCs和/或粒细胞检测到的"],
    repair: "使用中文方案入选标准句式：确诊为活动性PNH，依据为经流式细胞术检测的红细胞（RBCs）和/或粒细胞GPI缺失克隆比例≥10%；筛选期或病史资料均可接受。必须保留RBCs、GPI和全部原文限定，不得使用克隆大小或英文直译句式。",
  },
  {
    anchor: "schedule",
    spanId: "wref_span_e016c0af8e349dc8fb641431",
    sourceNeedle: "Missed or rescheduled visits",
    review: "已核对访视应尽量按计划日实施、漏访或改期不自动导致退出及对应停药/退出章节引用；译文保留操作边界。",
    rejectPatterns: ["评估访视受试者", "自动终止", "错过的或重新安排的访视"],
    repair: "当前中文句法和临床试验术语不合格。请明确表达：受试者应按评估计划完成所有访视/评估，或尽可能在接近规定日期/时间的时点完成；漏访或改期不应自动导致退出研究；有关停止治疗和/或退出研究的处理参见第9.1节。必须忠实原文，不得照抄本指令中原文未支持的内容。",
  },
  {
    anchor: "safety",
    spanId: "wref_span_b8593fa6b8fb533a2a8c570f",
    sourceNeedle: "An adverse event",
    review: "已核对AE定义、异常实验室结果、签署知情同意后的时间边界，以及与试验药物不要求存在时间或因果关联的表述。",
    rejectPatterns: ["e.g.", "i.e.", "药用（研究用）产品", "药物（研究）产品", "试验用药品（研究用药品）", "药品（试验用药品）", "也可能没有"],
    repair: "请使用中国临床试验方案常用监管中文：medicinal (investigational) product应表述为药品（试验用药品）；may or may not be temporally or causally associated应明确表述为可能存在、也可能不存在时间或因果关联。其余AE定义、异常实验室检查和知情同意时间边界保持不变。",
  },
];

async function request(relativePath) {
  const response = await fetch(new URL(relativePath, appUrl));
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
    on(method, listener) { listeners.set(method, [...(listeners.get(method) || []), listener]); },
    close() { ws.close(); },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result?.value;
}

async function waitForCondition(cdp, expression, timeoutMs = 90000) {
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

async function clickExact(cdp, text, rootSelector = "body") {
  const clicked = await evaluate(cdp, `(() => {
    const root = document.querySelector(${JSON.stringify(rootSelector)});
    const button = Array.from(root?.querySelectorAll('button') || []).find((item) => (item.textContent || '').trim() === ${JSON.stringify(text)});
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
    const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : input instanceof HTMLSelectElement ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error(`Control not found: ${selector}`);
}

async function typeText(cdp, selector, value) {
  const focused = await evaluate(cdp, `(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    if (!input) return false;
    input.focus();
    input.select();
    return document.activeElement === input;
  })()`);
  if (!focused) throw new Error(`Control could not receive focus: ${selector}`);
  await cdp.send("Input.insertText", { text: value });
  await waitForCondition(cdp, `document.querySelector(${JSON.stringify(selector)})?.value === ${JSON.stringify(value)}`);
}

async function screenshot(cdp, filename) {
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const target = path.join(outputDir, filename);
  await writeFile(target, Buffer.from(shot.data, "base64"));
  return target;
}

async function openTranslations(cdp) {
  await cdp.send("Page.navigate", { url: appUrl.href });
  await waitForCondition(cdp, `document.readyState === 'complete' && Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`);
  await evaluate(cdp, `(() => {
    const select = document.querySelector('select[aria-label="选择临床研究项目"]');
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(select, ${JSON.stringify(projectId)});
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
  await clickExact(cdp, "医学写作");
  await waitForCondition(cdp, `document.querySelector('.authoring-stage-strip button.active')?.textContent.includes('语料准备')`);
  await waitForCondition(cdp, `document.querySelectorAll('.writing-reference-list > button').length > 0`);
  await clickExact(cdp, "译文审核", ".writing-reference-views");
  await waitForCondition(cdp, `Boolean(document.querySelector('.writing-reference-structure-review.approved'))`);
  await setValue(cdp, ".writing-reference-view > .writing-reference-select select", artifactId);
  await waitForCondition(cdp, `document.querySelector('.writing-reference-view > .writing-reference-select select')?.value === ${JSON.stringify(artifactId)}`);
}

async function selectSpan(cdp, item) {
  const controls = ".writing-reference-span-controls";
  await setValue(cdp, `${controls} .writing-reference-select:first-child select`, item.anchor);
  await waitForCondition(cdp, `Array.from(document.querySelectorAll(${JSON.stringify(`${controls} .writing-reference-select:last-of-type select option`)})).some((option) => option.value === ${JSON.stringify(item.spanId)})`);
  await setValue(cdp, `${controls} .writing-reference-select:last-of-type select`, item.spanId);
  await waitForCondition(cdp, `document.querySelector('.writing-reference-source p')?.textContent.includes(${JSON.stringify(item.sourceNeedle)})`);
}

async function processSpan(cdp, item, report, index) {
  await selectSpan(cdp, item);
  let alreadyAdmitted = await evaluate(cdp, `document.querySelector('.writing-reference-admitted') !== null`);
  const existingTranslation = await evaluate(cdp, `document.querySelector('.writing-reference-translation p')?.textContent.trim() || ''`);
  let qualityFailure = /\b(?:and\/or|and|or|whether)\b/i.test(existingTranslation)
    || (item.rejectPatterns || []).some((pattern) => existingTranslation.includes(pattern));
  if (alreadyAdmitted && qualityFailure) {
    await clickExact(cdp, "发现问题，撤回译文", ".writing-reference-review");
    await setValue(cdp, ".writing-reference-review > label textarea", "复核发现监管中文译文残留未翻译英文连接词，当前版本不得继续作为写作语料，请完整翻译后重新审核。");
    await clickExact(cdp, "确认撤回", ".writing-reference-review");
    await waitForCondition(cdp, `document.querySelector('.writing-reference-review-state')?.textContent.includes('已退回') && !document.querySelector('.writing-reference-admitted')`);
    alreadyAdmitted = false;
  }
  if (!alreadyAdmitted) {
    const hasTranslation = await evaluate(cdp, `document.querySelector('.writing-reference-translation') !== null`);
    if (!hasTranslation) {
      await clickExact(cdp, "生成监管中文候选", ".writing-reference-review");
      await waitForCondition(cdp, `document.querySelector('.writing-reference-message')?.textContent.includes('监管中文候选已生成') || document.querySelector('.writing-reference-message.danger')`, 360000);
      const failure = await evaluate(cdp, `document.querySelector('.writing-reference-message.danger')?.textContent.trim() || ''`);
      if (failure) throw new Error(`${item.anchor} translation failed: ${failure}`);
      const generatedText = await evaluate(cdp, `document.querySelector('.writing-reference-translation p')?.textContent.trim() || ''`);
      qualityFailure = /\b(?:and\/or|and|or|whether|e\.g\.|i\.e\.)\b/i.test(generatedText)
        || (item.rejectPatterns || []).some((pattern) => generatedText.includes(pattern));
    }
    const reviewState = await evaluate(cdp, `document.querySelector('.writing-reference-review-state')?.textContent.trim() || ''`);
    if (!reviewState.includes("医学已批准")) {
      let fidelityFailures = await evaluate(cdp, `document.querySelector('.writing-reference-translation small')?.textContent.trim() || ''`);
      if (fidelityFailures || reviewState.includes("已退回") || qualityFailure) {
        if (!reviewState.includes("已退回")) {
          await setValue(cdp, ".writing-reference-review > label textarea", item.repair || `当前译文未通过来源完整性校验：${fidelityFailures}。请完整保留原文缩写、数字、比较符号、时间点、否定关系和限定语。`);
          await clickExact(cdp, "退回修改", ".writing-reference-review");
          await waitForCondition(cdp, `document.querySelector('.writing-reference-message')?.textContent.includes('译文审核处置已记录')`);
        }
        await waitForCondition(cdp, `Array.from(document.querySelectorAll('.writing-reference-review button')).some((button) => button.textContent.trim() === '按审核意见重新生成' && !button.disabled)`);
        await clickExact(cdp, "按审核意见重新生成", ".writing-reference-review");
        await waitForCondition(cdp, `document.querySelector('.writing-reference-message')?.textContent.includes('已按医学审核意见生成新译文版本') || document.querySelector('.writing-reference-message.danger')`, 360000);
        const repairFailure = await evaluate(cdp, `document.querySelector('.writing-reference-message.danger')?.textContent.trim() || ''`);
        if (repairFailure) throw new Error(`${item.anchor} translation repair failed: ${repairFailure}`);
        fidelityFailures = await evaluate(cdp, `document.querySelector('.writing-reference-translation small')?.textContent.trim() || ''`);
        if (fidelityFailures) throw new Error(`${item.anchor} translation v2 still failed fidelity: ${fidelityFailures}`);
        const repairedText = await evaluate(cdp, `document.querySelector('.writing-reference-translation p')?.textContent.trim() || ''`);
        qualityFailure = /\b(?:and\/or|and|or|whether)\b/i.test(repairedText)
          || (item.rejectPatterns || []).some((pattern) => repairedText.includes(pattern));
        if (qualityFailure) throw new Error(`${item.anchor} repaired translation still failed Chinese usability review: ${repairedText}`);
      }
      await setValue(cdp, ".writing-reference-review > label textarea", item.review);
      await clickExact(cdp, "批准译文", ".writing-reference-review");
      await waitForCondition(cdp, `document.querySelector('.writing-reference-message')?.textContent.includes('译文已完成医学批准')`);
    }
    const nowAdmitted = await evaluate(cdp, `document.querySelector('.writing-reference-admitted') !== null`);
    if (!nowAdmitted) {
      await clickExact(cdp, "纳入写作参考库", ".writing-reference-review");
      await waitForCondition(cdp, `document.querySelector('.writing-reference-message')?.textContent.includes('医学已批准译文已纳入写作参考库')`);
    }
  }
  const state = await evaluate(cdp, `(() => ({
    source: document.querySelector('.writing-reference-source p')?.textContent.trim() || '',
    translation: document.querySelector('.writing-reference-translation p')?.textContent.trim() || '',
    review: document.querySelector('.writing-reference-review-state')?.textContent.trim() || '',
    admitted: document.querySelector('.writing-reference-admitted')?.textContent.trim() || '',
    fidelityFailures: document.querySelector('.writing-reference-translation small')?.textContent.trim() || '',
  }))()`);
  if (!state.translation || !state.review.includes("医学已批准") || !state.admitted.includes("已纳入写作参考库") || state.fidelityFailures) {
    throw new Error(`${item.anchor} translation/admission state invalid: ${JSON.stringify(state)}`);
  }
  report.translations[item.anchor] = { spanId: item.spanId, ...state };
  report.screenshots.push(await screenshot(cdp, `${String(index + 1).padStart(2, "0")}_${item.anchor}_approved.png`));
}

async function run(cdp, report) {
  await openTranslations(cdp);
  for (let index = 0; index < selectedSpans.length; index += 1) {
    await processSpan(cdp, selectedSpans[index], report, index);
  }

  await clickExact(cdp, "已批准证据", ".writing-reference-views");
  await waitForCondition(cdp, `document.querySelectorAll('.writing-reference-brief:not(.invalid)').length >= 4`);
  await typeText(cdp, ".writing-reference-alignment textarea", "已按当前CMS-D017 PNH随机开放标签剂量探索PICOS逐项核对iptacopan竞品原文：人群、补体抑制剂既往治疗边界、主要终点、访视执行和AE定义存在可解释的项目差异，未发现需要改写当前PICOS的直接冲突；竞品数值不作为本项目事实直接继承。");
  try {
    await waitForCondition(cdp, `Array.from(document.querySelectorAll('.writing-reference-alignment button')).some((button) => button.textContent.trim() === '记录PICOS核对结论' && !button.disabled)`, 15000);
  } catch (error) {
    const buttonState = await evaluate(cdp, `(() => { const button = document.querySelector('.writing-reference-alignment button'); return { disabled: button?.disabled, title: button?.title, text: button?.textContent, summaryLength: document.querySelector('.writing-reference-alignment textarea')?.value.length }; })()`);
    throw new Error(`PICOS alignment button unavailable: ${JSON.stringify(buttonState)}; ${error.message}`);
  }
  await clickExact(cdp, "记录PICOS核对结论", ".writing-reference-alignment");
  await waitForCondition(cdp, `document.querySelector('.writing-reference-message')?.textContent.includes('PICOS与当前准入语料的核对结论已记录')`);
  await waitForCondition(cdp, `document.querySelectorAll('.authoring-gate-checklist label.satisfied').length === 5 && document.body.textContent.includes('语料已就绪')`);
  report.screenshots.push(await screenshot(cdp, "05_pnh_corpus_gate_ready.png"));

  const journey = await request(`/api/projects/${projectId}/medical-writing/authoring-journey`);
  const workspace = await request(`/api/projects/${projectId}/medical-writing/references/workspace?snapshot_id=${encodeURIComponent(journey.search_plan.latest_snapshot_id)}`);
  const currentBriefs = workspace.approved_evidence_briefs.filter((item) => item.artifact_id === artifactId);
  const anchors = [...new Set(currentBriefs.map((item) => item.ich_m11_anchor))].sort();
  const expectedAnchors = selectedSpans.map((item) => item.anchor).sort();
  if (JSON.stringify(anchors) !== JSON.stringify(expectedAnchors)) {
    throw new Error(`Approved evidence anchors mismatch: ${JSON.stringify(anchors)}`);
  }
  if (journey.corpus_gate.readiness_status !== "ready" || !journey.corpus_gate.access_permitted) {
    throw new Error(`Corpus gate did not become ready: ${JSON.stringify(journey.corpus_gate)}`);
  }
  report.journey = journey;
  report.approvedEvidenceBriefs = currentBriefs;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-pnh-corpus-translation-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  const report = { status: "running", projectId, artifactId, startedAt: new Date().toISOString(), translations: {}, screenshots: [], httpFailures: [], pageErrors: [] };
  let cdp;
  try {
    const target = await waitForChrome();
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");
    cdp.on("Runtime.exceptionThrown", (event) => report.pageErrors.push(event.exceptionDetails?.exception?.description || event.exceptionDetails?.text || "runtime exception"));
    cdp.on("Network.responseReceived", (event) => {
      const status = event.response?.status || 0;
      if (status >= 400) report.httpFailures.push({ status, url: event.response.url || "", type: event.type || "" });
    });
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await run(cdp, report);
    const expectedEmptyPaths = new Set([
      `/api/projects/${projectId}/medical-writing/manifest`,
      `/api/projects/${projectId}/medical-writing/document-session`,
    ]);
    report.unexpectedHttpFailures = report.httpFailures.filter((failure) => {
      let pathname = "";
      try { pathname = new URL(failure.url).pathname; } catch {}
      return !(failure.status === 404 && expectedEmptyPaths.has(pathname));
    });
    if (report.unexpectedHttpFailures.length) throw new Error(`Unexpected HTTP failures: ${JSON.stringify(report.unexpectedHttpFailures)}`);
    if (report.pageErrors.length) throw new Error(`Page errors: ${JSON.stringify(report.pageErrors)}`);
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
