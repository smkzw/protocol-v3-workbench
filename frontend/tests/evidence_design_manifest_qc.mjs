import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const workspaceRoot = path.resolve(scriptDir, "../..");
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.join(workspaceRoot, "records/visual_qc_20260710/evidence_workspace");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9368);

const projects = [
  {
    projectId: "proj_mgk10_crswnp",
    key: "crswnp",
    packageLabel: "CRSwNP竞品证据与方案设计资料包",
    requiredTypes: ["原始资料", "临床试验", "疗效结果", "安全性结果"],
    forbiddenTypes: ["公开发表", "监管资料"],
    forbiddenClinicalTerms: ["补体抑制", "血红蛋白尿", "突破性溶血"],
  },
  {
    projectId: "proj_my008_pnh_3_01",
    key: "pnh",
    packageLabel: "PNH竞品证据与方案设计资料包",
    requiredTypes: ["临床试验", "公开发表", "监管资料"],
    forbiddenTypes: ["原始资料", "疗效结果", "安全性结果"],
    forbiddenClinicalTerms: ["鼻息肉", "SNOT-22", "INCS"],
  },
];

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 12000) {
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
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result || {});
  });

  return {
    ready: new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", reject, { once: true });
    }),
    send(method, params = {}) {
      const id = nextId;
      nextId += 1;
      ws.send(JSON.stringify({ id, method, params }));
      return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
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
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.exception?.value || result.exceptionDetails.text;
    throw new Error(detail || "Runtime evaluation failed");
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
  throw new Error(`Timed out waiting for condition. Last value: ${JSON.stringify(lastValue)}`);
}

async function clickButtonByText(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)});
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button not found: ${label}`);
}

async function selectProject(cdp, projectId) {
  const changed = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select || !Array.from(select.options).some((item) => item.value === ${JSON.stringify(projectId)})) return false;
      select.value = ${JSON.stringify(projectId)};
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Project not available: ${projectId}`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
  await clickButtonByText(cdp, "证据调研与方案设计");
}

async function captureMetrics(cdp, project) {
  return evaluate(cdp, `
    (() => {
      const text = document.body.textContent || "";
      const doc = document.documentElement;
      const body = document.body;
      const grid = document.querySelector(".evidence-workspace-grid");
      const left = document.querySelector(".evidence-left-rail")?.getBoundingClientRect();
      const main = document.querySelector(".evidence-main")?.getBoundingClientRect();
      const right = document.querySelector(".evidence-right-rail")?.getBoundingClientRect();
      const rows = Array.from(document.querySelectorAll(".evidence-candidate-table tbody tr"));
      const range = document.querySelector(".evidence-table-range")?.textContent || "";
      return {
        projectId: ${JSON.stringify(project.projectId)},
        packageLabel: ${JSON.stringify(project.packageLabel)},
        hasWorkspace: Boolean(grid),
        hasPackage: text.includes(${JSON.stringify(project.packageLabel)}),
        hasEvidenceMode: text.includes("候选证据库") && text.includes("证据综合") && text.includes("证据筛选"),
        hasPicosMode: text.includes("PICOS方案设计"),
        requiredTypesPresent: ${JSON.stringify(project.requiredTypes)}.every((label) => text.includes(label)),
        forbiddenTypesAbsent: ${JSON.stringify(project.forbiddenTypes)}.every((label) => !text.includes(label)),
        forbiddenClinicalTermsAbsent: ${JSON.stringify(project.forbiddenClinicalTerms)}.every((label) => !text.includes(label)),
        candidateRows: rows.length,
        pageRange: range.trim(),
        pageIsExplicit: range.includes("-") && range.includes("/"),
        hasNextPageControl: Array.from(document.querySelectorAll(".evidence-table-paging button")).length === 2,
        hasInternalTableScroll: (() => {
          const item = document.querySelector(".evidence-table-scroll");
          return Boolean(item && (item.scrollWidth > item.clientWidth || item.scrollHeight >= item.clientHeight));
        })(),
        stableThreeColumns: Boolean(left && main && right && Math.abs(left.top - main.top) < 2 && Math.abs(main.top - right.top) < 2 && left.right < main.left && main.right < right.left),
        workspaceFitsViewport: Boolean(grid && grid.getBoundingClientRect().bottom <= window.innerHeight + 1),
        overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
        leaksLocalPath: text.includes("/Users/") || text.includes("source_root_label"),
        leaksProvider: /\b(?:deepseek(?:-v4-(?:flash|pro))?|kimi(?:-k2\.7-code)?|minimax(?:-m3)?|buddy|opencode|reasonix)\b/i.test(text),
        hasForbiddenLifecycleText: /第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]|Stage\\s+[0-9]/i.test(text),
        hasForbiddenOverclaim: /最终医学结论|已批准方案|方案定稿|自动定稿|可直接提交监管|无需人工复核|监管认可/.test(text),
      };
    })()
  `);
}

async function capturePicosMetrics(cdp) {
  await clickButtonByText(cdp, "PICOS方案设计");
  await waitForCondition(cdp, `document.querySelectorAll(".evidence-picos-domain-list-left button").length === 5`);
  return evaluate(cdp, `
    (() => {
      const text = document.body.textContent || "";
      const approval = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").trim() === "提交医学批准");
      const handoff = Array.from(document.querySelectorAll("button")).find((item) => (item.textContent || "").trim() === "发起撰写交接");
      return {
        picosDomains: document.querySelectorAll(".evidence-picos-domain-list-left button").length,
        picosOptions: document.querySelectorAll(".evidence-picos-options button").length,
        hasActions: text.includes("保存医学理由") && text.includes("标记写作候选") && text.includes("退回补证"),
        hasAiBoundary: text.includes("AI建议修订") && text.includes("应用到PICOS"),
        hasFailClosedAi: text.includes("独立AI未配置或未获私有化执行许可") || text.includes("获取AI建议"),
        approvalDisabled: Boolean(approval?.disabled),
        handoffDisabled: Boolean(handoff?.disabled),
        overflowX: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) > window.innerWidth + 1,
      };
    })()
  `);
}

async function captureScreenshot(cdp, fileName) {
  const shot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  });
  const target = path.join(outputDir, fileName);
  await writeFile(target, Buffer.from(shot.data, "base64"));
  return target;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "evidence-workspace-qc-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });

  const result = { appUrl, viewport: { width: 1600, height: 1000 }, projects: {} };
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    const target = targets.find((item) => item.type === "page");
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Chrome page target found.");

    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 1600,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);

    for (const project of projects) {
      await selectProject(cdp, project.projectId);
      await waitForCondition(cdp, `
        document.querySelector(".evidence-workspace-grid") &&
        document.body.textContent.includes(${JSON.stringify(project.packageLabel)}) &&
        document.querySelectorAll(".evidence-candidate-table tbody tr").length > 0
      `);
      await evaluate(cdp, `document.querySelector(".evidence-candidate-table tbody tr")?.click()`);
      await waitForCondition(cdp, `Boolean(document.querySelector(".evidence-detail-head"))`);
      const evidence = await captureMetrics(cdp, project);
      const evidenceShot = await captureScreenshot(cdp, `${project.key}_evidence.png`);
      const picos = await capturePicosMetrics(cdp);
      const picosShot = await captureScreenshot(cdp, `${project.key}_picos.png`);
      result.projects[project.key] = { evidence, picos, evidenceShot, picosShot };
      await clickButtonByText(cdp, "项目总看板");
    }
    cdp.close();

    const metricsPath = path.join(outputDir, "evidence_workspace_qc.json");
    await writeFile(metricsPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
    console.log(metricsPath);

    const failures = [];
    for (const [key, item] of Object.entries(result.projects)) {
      const e = item.evidence;
      const p = item.picos;
      for (const [name, passed] of Object.entries({
        hasWorkspace: e.hasWorkspace,
        hasPackage: e.hasPackage,
        hasEvidenceMode: e.hasEvidenceMode,
        hasPicosMode: e.hasPicosMode,
        requiredTypesPresent: e.requiredTypesPresent,
        forbiddenTypesAbsent: e.forbiddenTypesAbsent,
        forbiddenClinicalTermsAbsent: e.forbiddenClinicalTermsAbsent,
        hasRows: e.candidateRows === 25,
        pageIsExplicit: e.pageIsExplicit,
        hasNextPageControl: e.hasNextPageControl,
        hasInternalTableScroll: e.hasInternalTableScroll,
        stableThreeColumns: e.stableThreeColumns,
        workspaceFitsViewport: e.workspaceFitsViewport,
        noOverflow: !e.overflowX,
        noPathLeak: !e.leaksLocalPath,
        noProviderLeak: !e.leaksProvider,
        noLifecycleLeak: !e.hasForbiddenLifecycleText,
        noOverclaim: !e.hasForbiddenOverclaim,
        fivePicosDomains: p.picosDomains === 5,
        picosOptions: p.picosOptions >= 3,
        picosActions: p.hasActions,
        aiBoundary: p.hasAiBoundary,
        failClosedAi: p.hasFailClosedAi,
        approvalGated: p.approvalDisabled,
        handoffGated: p.handoffDisabled,
        picosNoOverflow: !p.overflowX,
      })) {
        if (!passed) failures.push(`${key}:${name}`);
      }
    }
    if (failures.length) throw new Error(`Evidence workspace QC failed: ${failures.join(", ")}`);
  } finally {
    chrome.kill("SIGTERM");
    await rm(userDataDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
