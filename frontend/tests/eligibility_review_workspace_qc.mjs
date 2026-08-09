import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5176/";
const apiUrl = process.env.API_BASE || "http://127.0.0.1:8921";
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(scriptDir, "../../records/visual_qc_20260711/eligibility_review_workspace");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9394);
const projects = [
  { projectId: "proj_d001", subjectId: "SA07005", expectedIn: 6, expectedEx: 30 },
  { projectId: "proj_my009_uc", subjectId: "S01009", expectedIn: 10, expectedEx: 24 },
];

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function requestJson(url, init) {
  const response = await fetch(url, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status}: ${JSON.stringify(payload)}`);
  return payload;
}

async function waitForJson(url, timeoutMs = 15000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await requestJson(url);
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
  throw new Error(`Timed out waiting for condition: ${expression}\nLast value: ${JSON.stringify(lastValue)}`);
}

async function clickByText(cdp, selector, text) {
  const clicked = await evaluate(cdp, `
    (() => {
      const node = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
        .find((item) => (item.textContent || "").includes(${JSON.stringify(text)}));
      if (!node) return false;
      node.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Unable to click ${selector}: ${text}`);
}

async function setProject(cdp, projectId) {
  const changed = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error("Project selector not found");
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function openSubject(cdp, project) {
  await setProject(cdp, project.projectId);
  await clickByText(cdp, ".nav-item", "入排审核");
  await waitForCondition(cdp, `
    document.body.textContent.includes("受试者逐条标准审阅")
      && Array.from(document.querySelectorAll(".eligibility-subject-table .subject-link"))
        .some((item) => (item.textContent || "").trim() === ${JSON.stringify(project.subjectId)})
  `, 120000);
  await clickByText(cdp, ".eligibility-subject-table .subject-link", project.subjectId);
  await waitForCondition(cdp, `
    document.querySelector(".eligibility-criterion-ledger")?.textContent.includes(${JSON.stringify(project.subjectId)})
      && document.querySelectorAll(".eligibility-criterion-row").length === ${project.expectedIn}
      && document.querySelector(".eligibility-inspector")?.textContent.includes("IN-01")
  `, 120000);
}

async function setTextarea(cdp, value) {
  const changed = await evaluate(cdp, `
    (() => {
      const input = document.querySelector(".eligibility-decision-block textarea");
      if (!input) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      setter.call(input, ${JSON.stringify(value)});
      input.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error("Medical reason textarea not found");
}

async function exerciseActions(cdp, project) {
  await setTextarea(cdp, "当前证据尚未完成结构化处理，请补充可追溯证据后再作医学判断。");
  await clickByText(cdp, ".eligibility-action-grid button", "请求补证");
  await waitForCondition(cdp, `
    document.querySelector(".eligibility-current-state")?.textContent.includes("状态版本：1")
      && document.querySelector(".eligibility-criterion-row.selected")?.textContent.includes("待补充证据")
  `, 30000);

  const review = await requestJson(`${apiUrl}/api/projects/${project.projectId}/eligibility/raw-intake/subjects/${project.subjectId}/review`);
  const criterion = review.criteria.find((item) => item.review_rule_id === "IN-01");
  if (!criterion?.state || criterion.state.state_revision !== 1) throw new Error("Expected IN-01 state revision 1");
  await requestJson(
    `${apiUrl}/api/projects/${project.projectId}/eligibility/raw-intake/subjects/${project.subjectId}/criteria/${criterion.criterion_uid}/actions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        criterion_kind: "inclusion",
        expected_state_revision: 1,
        expected_rule_revision: review.rule_revision,
        expected_subject_source_revision: review.subject_source_revision,
        idempotency_key: `qc-external-${project.projectId}`,
        actor: "medical_manager",
        action: "defer_review",
        reason: "并发复核动作，用于验证前端版本冲突处理。",
        evidence_ids: [],
        evidence_processing_state: "queued",
      }),
    },
  );

  await setTextarea(cdp, "尝试以旧版本延期，用于验证冲突后必须刷新。 ");
  await clickByText(cdp, ".eligibility-action-grid button", "延期审阅");
  await waitForCondition(cdp, `document.querySelector(".eligibility-conflict-banner")?.textContent.includes("刷新后重新确认")`);
  await clickByText(cdp, ".eligibility-conflict-banner button", "刷新审阅状态");
  await waitForCondition(cdp, `document.querySelector(".eligibility-current-state")?.textContent.includes("状态版本：2")`);
  await waitForCondition(cdp, `document.querySelector(".eligibility-decision-block textarea")?.value.includes("尝试以旧版本延期")`);
}

async function collectMetrics(cdp, project) {
  return evaluate(cdp, `
    (() => {
      const doc = document.documentElement;
      const body = document.body;
      const rect = (selector) => {
        const node = document.querySelector(selector);
        if (!node) return null;
        const box = node.getBoundingClientRect();
        return { x: Math.round(box.x), y: Math.round(box.y), width: Math.round(box.width), height: Math.round(box.height) };
      };
      const textNodes = Array.from(document.querySelectorAll(
        ".eligibility-subject-table td, .eligibility-criterion-row, .eligibility-inspector, .eligibility-status > div"
      ));
      const selectedOptionTexts = Array.from(document.querySelectorAll(".eligibility-decision-block option")).map((item) => item.textContent || "");
      return {
        viewport: { width: window.innerWidth, height: window.innerHeight },
        projectId: document.querySelector('select[aria-label="选择临床研究项目"]')?.value,
        selectedSubject: document.querySelector(".eligibility-criterion-ledger .section-title h2")?.textContent || "",
        criterionRows: document.querySelectorAll(".eligibility-criterion-row").length,
        selectedCriterion: document.querySelector(".eligibility-criterion-row.selected .eligibility-criterion-id")?.textContent || "",
        workbenchColumns: getComputedStyle(document.querySelector(".eligibility-workbench")).gridTemplateColumns,
        subjectRect: rect(".eligibility-subjects-panel"),
        ledgerRect: rect(".eligibility-criterion-ledger"),
        inspectorRect: rect(".eligibility-inspector"),
        noPageOverflowX: Math.max(doc.scrollWidth, body.scrollWidth) <= window.innerWidth + 1,
        overflowCount: textNodes.filter((node) => node.scrollWidth > node.clientWidth + 1 && getComputedStyle(node).overflowX === "visible").length,
        subjectListScrolls: (() => {
          const node = document.querySelector(".eligibility-subjects-panel .eligibility-table-wrap");
          return Boolean(node && (
            node.scrollHeight <= node.clientHeight + 1
            || ["auto", "scroll"].includes(getComputedStyle(node).overflowY)
          ));
        })(),
        criterionListScrolls: (() => {
          const node = document.querySelector(".eligibility-criterion-list");
          return Boolean(node && (
            node.scrollHeight <= node.clientHeight + 1
            || ["auto", "scroll"].includes(getComputedStyle(node).overflowY)
          ));
        })(),
        hasBoundary: (document.body.textContent || "").includes("不作出正式资格审核结论或随机化放行"),
        hasAiMedicalSeparation: (document.querySelector(".eligibility-inspector")?.textContent || "").includes("AI 草稿")
          && (document.querySelector(".eligibility-inspector")?.textContent || "").includes("医学判断"),
        hasMandatoryReason: (document.querySelector(".eligibility-inspector")?.textContent || "").includes("医学理由（必填）"),
        saveDisabledWithoutEvidence: document.querySelector(".eligibility-action-grid .primary-button")?.disabled === true,
        hasDistinctDecisionOptions: ${JSON.stringify(project.projectId)} === "proj_d001"
          ? selectedOptionTexts.includes("符合该纳入条件") && !selectedOptionTexts.includes("存在该排除条件")
          : selectedOptionTexts.includes("符合该纳入条件") && !selectedOptionTexts.includes("存在该排除条件"),
        noLifecycleNumbering: !/第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]/.test(document.body.textContent || ""),
      };
    })()
  `);
}

async function capture(cdp, filename) {
  await cdp.send("Runtime.evaluate", { expression: "window.scrollTo(0, 0)" });
  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  });
  const target = path.join(outputDir, filename);
  await writeFile(target, Buffer.from(screenshot.data, "base64"));
  return target;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "eligibility-review-workspace-qc-"));
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
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Chrome target");
    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`, 45000);

    const results = [];
    for (const project of projects) {
      await openSubject(cdp, project);
      if (project.projectId === "proj_d001") await exerciseActions(cdp, project);
      const metrics1600 = await collectMetrics(cdp, project);
      const screenshot1600 = await capture(cdp, `${project.projectId}_1600x1000.png`);
      await cdp.send("Emulation.setDeviceMetricsOverride", { width: 2048, height: 1024, deviceScaleFactor: 1, mobile: false });
      await wait(300);
      const metrics2048 = await collectMetrics(cdp, project);
      const screenshot2048 = await capture(cdp, `${project.projectId}_2048x1024.png`);
      results.push({ project, metrics1600, metrics2048, screenshot1600, screenshot2048 });
      await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    }

    const failures = [];
    for (const result of results) {
      for (const [viewport, metrics] of [["1600", result.metrics1600], ["2048", result.metrics2048]]) {
        if (metrics.projectId !== result.project.projectId) failures.push(`${result.project.projectId}:${viewport}:project`);
        if (!metrics.selectedSubject.includes(result.project.subjectId)) failures.push(`${result.project.projectId}:${viewport}:subject`);
        if (!metrics.noPageOverflowX) failures.push(`${result.project.projectId}:${viewport}:page-overflow`);
        if (metrics.overflowCount > 0) failures.push(`${result.project.projectId}:${viewport}:text-overflow-${metrics.overflowCount}`);
        if (!(metrics.subjectRect.x < metrics.ledgerRect.x && metrics.ledgerRect.x < metrics.inspectorRect.x)) failures.push(`${result.project.projectId}:${viewport}:column-order`);
        for (const key of ["subjectListScrolls", "criterionListScrolls", "hasBoundary", "hasAiMedicalSeparation", "hasMandatoryReason", "saveDisabledWithoutEvidence", "hasDistinctDecisionOptions", "noLifecycleNumbering"]) {
          if (!metrics[key]) failures.push(`${result.project.projectId}:${viewport}:${key}`);
        }
      }
    }
    const report = { completed: failures.length === 0, failures, results };
    await writeFile(path.join(outputDir, "eligibility_review_workspace_qc.json"), `${JSON.stringify(report, null, 2)}\n`);
    cdp.close();
    if (failures.length) throw new Error(`QC failures: ${failures.join(", ")}`);
  } finally {
    chrome.kill("SIGTERM");
    await wait(750);
    await rm(userDataDir, { recursive: true, force: true, maxRetries: 4, retryDelay: 250 }).catch(() => undefined);
  }
}

await main();
