import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9511);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const outputDir = process.env.QC_OUTPUT_DIR || "records/active_slices/medical_writing_editor_references_20260715/browser_qc";
const projectId = "proj_rux_03_002";
const sectionId = "mwsec_proj_rux_03_002_8783a740fc05_c848ed4d86b7";
const targetBlockId = "mwblock_mwsec_proj_rux_03_002_8783a740fc05_c848ed4d86b7_bf5c2fa8e722";

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(relative, options = {}) {
  const response = await fetch(new URL(relative, appUrl), options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status}: ${relative}\n${JSON.stringify(payload)}`);
  return payload;
}

async function waitForJson(url, timeoutMs = 20000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      return await (await fetch(url)).json();
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
  const ready = new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const callback = pending.get(message.id);
    if (!callback) return;
    pending.delete(message.id);
    clearTimeout(callback.timer);
    if (message.error) callback.reject(new Error(message.error.message));
    else callback.resolve(message.result || {});
  });
  const rejectPending = (reason) => {
    for (const callback of pending.values()) {
      clearTimeout(callback.timer);
      callback.reject(reason);
    }
    pending.clear();
  };
  ws.addEventListener("close", () => rejectPending(new Error("CDP connection closed")));
  return {
    ready,
    send(method, params = {}) {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error(`CDP command timed out: ${method}`));
        }, 15000);
        pending.set(id, { resolve, reject, timer });
        ws.send(JSON.stringify({ id, method, params }));
      });
    },
    close: () => ws.close(),
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result?.value;
}

async function waitForCondition(cdp, expression, timeoutMs = 45000) {
  const started = Date.now();
  let last;
  while (Date.now() - started < timeoutMs) {
    last = await evaluate(cdp, expression);
    if (last) return last;
    await wait(200);
  }
  throw new Error(`Timed out: ${expression}; last=${JSON.stringify(last)}`);
}

async function clickMatching(cdp, selector, label, occurrence = 0) {
  const clicked = await evaluate(cdp, `(() => {
    const nodes = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
      .filter((node) => (node.textContent || "").includes(${JSON.stringify(label)}) && !node.disabled);
    const node = nodes[${occurrence}];
    if (!node) return false;
    node.scrollIntoView({ block: "center", inline: "nearest" });
    node.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Enabled control not found: ${selector}/${label}/${occurrence}`);
}

async function setProject(cdp) {
  const changed = await evaluate(cdp, `(() => {
    const control = document.querySelector('select[aria-label="选择临床研究项目"]');
    if (!control || control.disabled) return false;
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(control, ${JSON.stringify(projectId)});
    control.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error("Project selector unavailable");
}

async function ensureEditableCopy() {
  const copy = await request(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`);
  if (copy.revision >= 1) return copy;
  return request(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      document_id: copy.document_id,
      expected_revision: copy.revision,
      content_blocks: copy.content_blocks,
      actor: "codex_candidate_replacement_qc",
      idempotency_key: "candidate-replacement-qc-seed-v1",
    }),
  });
}

async function restoreCopy(baseline) {
  const current = await request(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`);
  if (JSON.stringify(current.content_blocks) === JSON.stringify(baseline.content_blocks)) return current;
  return request(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      document_id: baseline.document_id,
      expected_revision: current.revision,
      content_blocks: baseline.content_blocks,
      actor: "codex_candidate_replacement_qc_restore",
      idempotency_key: `candidate-replacement-qc-restore-r${current.revision}`,
    }),
  });
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const baseline = await ensureEditableCopy();
  await writeFile(path.join(outputDir, `candidate_replacement_baseline_r${baseline.revision}.json`), JSON.stringify(baseline, null, 2));
  const section = await request(`/api/projects/${projectId}/medical-writing/document-session`);
  const sectionIndex = section.sections.findIndex((item) => item.section_id === sectionId);
  if (sectionIndex < 0) throw new Error("Target section unavailable");
  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-candidate-qc-"));
  const chrome = spawn(chromePath, [
    "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
    `--remote-debugging-port=${debugPort}`, `--user-data-dir=${userDataDir}`, "about:blank",
  ], { stdio: "ignore" });
  let cdp;
  let result;
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const browserTarget = await (await fetch(`http://127.0.0.1:${debugPort}/json/new?${encodeURIComponent(appUrl)}`, { method: "PUT" })).json();
    cdp = createCdp(browserTarget.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`);
    await setProject(cdp);
    await clickMatching(cdp, ".nav-item", "医学写作");
    await waitForCondition(cdp, `document.body.textContent.includes("研究方案文档编辑与AI修订")`);
    await clickMatching(cdp, ".writing-title-actions button", "目录");
    await waitForCondition(cdp, `document.querySelectorAll(".writing-section-buttons > button").length > ${sectionIndex}`);
    await evaluate(cdp, `document.querySelectorAll(".writing-section-buttons > button")[${sectionIndex}].click()`);
    await waitForCondition(cdp, `Boolean(document.querySelector(${JSON.stringify(`[data-source-block-id="${targetBlockId}"]`)}))`);
    await waitForCondition(cdp, `document.querySelectorAll(".writing-ai-candidates article").length >= 2`);
    const before = await evaluate(cdp, `(() => {
      const card = document.querySelectorAll(".writing-ai-candidates article")[1];
      const followup = Array.from(document.querySelectorAll(".revision-current-action label"))
        .find((label) => (label.textContent || "").includes("下一轮重写要求"))
        ?.querySelector("textarea");
      return {
        proposal: card?.querySelector("p")?.textContent || "",
        targetText: document.querySelector(${JSON.stringify(`[data-source-block-id="${targetBlockId}"]`)})?.innerText || "",
        topLevelBlocks: document.querySelector(".protocol-editor .ProseMirror")?.children.length || 0,
        followupValue: followup?.value ?? null,
        followupPlaceholder: followup?.placeholder || "",
      };
    })()`);
    if (!before.proposal || before.proposal === before.targetText) throw new Error("Second candidate is not a distinct replacement target");
    if (before.followupValue !== "") throw new Error(`Follow-up rewrite input is unexpectedly prefilled: ${before.followupValue}`);
    const intentSpecificFragments = ["需要保留的事实", "义务强度", "待核对的冲突", "本轮已选证据"];
    if (!intentSpecificFragments.some((fragment) => before.followupPlaceholder.includes(fragment))) {
      throw new Error(`Follow-up placeholder is not intent specific: ${before.followupPlaceholder}`);
    }
    if (before.followupPlaceholder.includes("SAP时间窗")) throw new Error(`Legacy fixed follow-up leaked into UI: ${before.followupPlaceholder}`);
    await clickMatching(cdp, ".writing-ai-candidates article button", "选用并写入", 1);
    await waitForCondition(cdp, `document.querySelector(${JSON.stringify(`[data-source-block-id="${targetBlockId}"]`)})?.innerText === ${JSON.stringify(before.proposal)}`);
    await waitForCondition(cdp, `document.body.textContent.includes("已选用并写入工作副本版本")`);
    await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("已保存")`);
    const saved = await request(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`);
    const appliedThreadId = saved.applied_revision_thread_ids
      .find((threadId) => !baseline.applied_revision_thread_ids.includes(threadId));
    const appliedThread = (await request(`/api/projects/${projectId}/revision-threads`))
      .find((thread) => thread.thread_id === appliedThreadId);
    const savedTargetBlock = saved.content_blocks.find((block) => block.block_id === targetBlockId);
    result = {
      passed: savedTargetBlock?.text === before.proposal
        && appliedThread?.status === "medically_approved"
        && appliedThread?.suggestions?.some((item) => (
          item.proposal_text === before.proposal && item.user_decision === "accepted"
        )),
      baselineRevision: baseline.revision,
      savedRevision: saved.revision,
      appliedThreadId,
      targetBlockId,
      proposal: before.proposal,
      savedText: savedTargetBlock?.text || "",
      blockCountPreserved: saved.content_blocks.length === baseline.content_blocks.length,
      topLevelBlockCountBefore: before.topLevelBlocks,
      followupInputInitiallyEmpty: before.followupValue === "",
      followupPlaceholder: before.followupPlaceholder,
    };
    if (!result.passed || !result.blockCountPreserved) throw new Error(`Audited candidate application failed: ${JSON.stringify(result)}`);
  } finally {
    const restored = await restoreCopy(baseline);
    if (result) result.restoredRevision = restored.revision;
    cdp?.close();
    chrome.kill("SIGTERM");
    await rm(userDataDir, { recursive: true, force: true });
  }
  await writeFile(path.join(outputDir, "medical_writing_candidate_replacement_qc.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
