import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const outputDir = process.env.QC_OUTPUT_DIR
  || path.join(projectRoot, "records/visual_qc_20260711/monitoring_interactions");
const chromePath = process.env.CHROME_PATH
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const mainRuntimeDb = process.env.MAIN_RUNTIME_DB
  || path.resolve(projectRoot, "../../runtime/workbench_runtime.sqlite3");

const projects = [
  {
    projectId: "proj_rux_03_002",
    projectCode: "RUX-03-002",
    judgmentValues: {
      patient_safety_impact: true,
      key_data_impact: true,
      query_required: true,
      lock_or_export_impact: true,
    },
    comment: "RUX-03-002交互QC：已核对原始listing、方案条款、个例时间线及试验药物变更记录。",
    query: "请中心核对该受试者风险相关原始记录、AE/PD及试验药物暂停、重启或剂量调整记录，并补充医学解释。",
  },
  {
    projectId: "proj_my009_uc",
    projectCode: "MY009-UC",
    judgmentValues: {
      patient_safety_impact: true,
      key_data_impact: false,
      query_required: true,
      lock_or_export_impact: false,
    },
    comment: "MY009-UC交互QC：已核对原始listing、方案条款、个例时间线及依从性相关记录。",
    query: "请中心核对该受试者风险相关原始记录、AE/PD、依从性计算及研究者医学解释，并补充必要说明。",
  },
];

const judgmentLabels = [
  ["patient_safety_impact", "患者安全影响"],
  ["key_data_impact", "关键疗效/安全性数据影响"],
  ["query_required", "需要发起Query"],
  ["lock_or_export_impact", "影响锁库/数据导出"],
];
const judgmentConfirmationLabel = "已完成以上四项医学判断";

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  return { response, payload };
}

async function requestJson(url, options = {}) {
  const { response, payload } = await request(url, options);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${url}; ${JSON.stringify(payload)}`);
  }
  return payload;
}

async function waitForJson(url, timeoutMs = 120000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await requestJson(url);
    } catch (error) {
      lastError = error;
      await wait(250);
    }
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

async function freePort(preferred) {
  const tryPort = (port) => new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      const selected = server.address().port;
      server.close(() => resolve(selected));
    });
  });
  if (preferred) {
    try {
      return await tryPort(Number(preferred));
    } catch {
      // Fall through to an OS-assigned port when a configured default is busy.
    }
  }
  return tryPort(0);
}

function startService(command, args, options) {
  const output = [];
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
  const collect = (chunk) => {
    output.push(String(chunk));
    if (output.length > 200) output.shift();
  };
  child.stdout.on("data", collect);
  child.stderr.on("data", collect);
  return { child, output };
}

async function stopService(service) {
  if (!service?.child || service.child.exitCode !== null) return;
  const exited = new Promise((resolve) => service.child.once("exit", resolve));
  service.child.kill("SIGTERM");
  await Promise.race([exited, wait(4000)]);
  if (service.child.exitCode === null) service.child.kill("SIGKILL");
}

async function sha256File(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

function sqliteIntegrity(dbPath) {
  const result = spawnSync(
    process.env.PYTHON_BIN || "python3",
    ["-c", "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()", dbPath],
    { encoding: "utf8" },
  );
  if (result.status !== 0) throw new Error(`SQLite integrity command failed: ${result.stderr || result.stdout}`);
  return result.stdout.trim();
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
    if (!message.id || !pending.has(message.id)) return;
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result);
  });
  return {
    ready,
    send(method, params = {}) {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ id, method, params }));
      });
    },
    close() {
      ws.close();
    },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Runtime.evaluate failed");
  }
  return result.result?.value;
}

async function waitForCondition(cdp, expression, timeoutMs = 120000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(250);
  }
  throw new Error(`Timed out waiting for condition: ${expression}; last=${JSON.stringify(lastValue)}`);
}

async function clickExact(cdp, label, selector = "button") {
  const clicked = await evaluate(cdp, `
    (() => {
      const target = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
        .find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)} && !item.disabled);
      if (!target) return false;
      target.scrollIntoView({ block: "center", inline: "nearest" });
      target.click();
      return true;
    })()
  `);
  if (!clicked) {
    const diagnostic = await evaluate(cdp, `({
      project: document.querySelector('select[aria-label="选择临床研究项目"]')?.value || "",
      buttons: Array.from(document.querySelectorAll(${JSON.stringify(selector)})).map((item) => ({
        label: (item.textContent || "").trim(), disabled: item.disabled, title: item.title,
      })),
      message: document.querySelector(".gate-result")?.textContent || "",
      risk: document.querySelector(".risk-detail")?.textContent?.slice(0, 1800) || "",
    })`);
    throw new Error(`Enabled control not found: ${selector}/${label}; diagnostic=${JSON.stringify(diagnostic)}`);
  }
}

async function setProject(cdp, projectId) {
  await waitForCondition(cdp, `Array.from(document.querySelectorAll('select[aria-label="选择临床研究项目"] option')).some((item) => item.value === ${JSON.stringify(projectId)})`);
  const selected = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!selected) throw new Error(`Project selector unavailable: ${projectId}`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function openMonitoring(cdp, project, riskTitle = "") {
  await setProject(cdp, project.projectId);
  await waitForCondition(cdp, `document.querySelector(".topbar")?.textContent.includes(${JSON.stringify(project.projectCode)})`);
  const navActive = await evaluate(cdp, `document.querySelector(".nav-item.active")?.textContent?.trim() === "医学监查"`);
  if (!navActive) await clickExact(cdp, "医学监查", ".nav-item");
  await waitForCondition(cdp, `Boolean(document.querySelector(".monitoring-page"))`);
  await waitForCondition(cdp, `document.querySelectorAll(".risk-card-row").length > 0`);
  if (riskTitle) {
    await waitForCondition(cdp, `Array.from(document.querySelectorAll(".risk-card-row .risk-card-title strong")).some((item) => (item.textContent || "").trim() === ${JSON.stringify(riskTitle)})`);
    const opened = await evaluate(cdp, `
      (() => {
        const row = Array.from(document.querySelectorAll(".risk-card-row"))
          .find((item) => (item.textContent || "").includes(${JSON.stringify(riskTitle)}));
        if (!row) return false;
        row.scrollIntoView({ block: "center", inline: "nearest" });
        row.click();
        return true;
      })()
    `);
    if (!opened) throw new Error(`${project.projectId}: risk row not found for ${riskTitle}`);
    await waitForCondition(cdp, `document.querySelector(".risk-detail")?.textContent.includes(${JSON.stringify(riskTitle)})`);
  }
}

async function setTextarea(cdp, label, value) {
  const changed = await evaluate(cdp, `
    (() => {
      const field = Array.from(document.querySelectorAll("label.disposition-field"))
        .find((item) => (item.textContent || "").includes(${JSON.stringify(label)}));
      const textarea = field?.querySelector("textarea");
      if (!textarea || textarea.disabled) return false;
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(textarea, ${JSON.stringify(value)});
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Editable textarea not found: ${label}`);
  await waitForCondition(cdp, `Array.from(document.querySelectorAll("label.disposition-field")).find((item) => (item.textContent || "").includes(${JSON.stringify(label)}))?.querySelector("textarea")?.value === ${JSON.stringify(value)}`);
}

async function exerciseJudgments(cdp, expected) {
  const results = [];
  for (const [key, label] of judgmentLabels) {
    const result = await evaluate(cdp, `
      (() => {
        const label = Array.from(document.querySelectorAll(".checklist label"))
          .find((item) => (item.textContent || "").includes(${JSON.stringify(label)}));
        const input = label?.querySelector('input[type="checkbox"]');
        if (!input || input.disabled) return null;
        const initial = input.checked;
        input.click();
        const toggled = input.checked !== initial;
        if (input.checked !== ${JSON.stringify(Boolean(expected[key]))}) input.click();
        return { initial, toggled, final: input.checked, controlled: Boolean(input.dataset.testid || input.name || input.value) };
      })()
    `);
    if (!result) throw new Error(`Medical judgment input unavailable: ${label}`);
    if (!result.toggled || result.final !== Boolean(expected[key])) {
      throw new Error(`Medical judgment did not behave as controlled input: ${key}/${JSON.stringify(result)}`);
    }
    results.push({ key, label, expected: Boolean(expected[key]), ...result });
  }
  const confirmation = await evaluate(cdp, `
    (() => {
      const label = Array.from(document.querySelectorAll(".checklist label"))
        .find((item) => (item.textContent || "").includes(${JSON.stringify(judgmentConfirmationLabel)}));
      const input = label?.querySelector('input[type="checkbox"]');
      if (!input || input.disabled) return null;
      const initial = input.checked;
      if (!input.checked) input.click();
      return { initial, final: input.checked };
    })()
  `);
  if (!confirmation?.final) throw new Error("Medical judgment completion confirmation was not accepted");
  results.push({ key: "review_completed", label: judgmentConfirmationLabel, expected: true, ...confirmation });
  return results;
}

async function readJudgments(cdp) {
  return evaluate(cdp, `
    (() => Object.fromEntries([...${JSON.stringify(judgmentLabels)}, ["review_completed", ${JSON.stringify(judgmentConfirmationLabel)}]].map(([key, labelText]) => {
      const label = Array.from(document.querySelectorAll(".checklist label"))
        .find((item) => (item.textContent || "").includes(labelText));
      return [key, label?.querySelector('input[type="checkbox"]')?.checked ?? null];
    })))()
  `);
}

async function screenshot(cdp, filename) {
  await evaluate(cdp, "window.scrollTo(0, 0)");
  await wait(200);
  const image = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  });
  const outputPath = path.join(outputDir, filename);
  await writeFile(outputPath, Buffer.from(image.data, "base64"));
  return outputPath;
}

async function getPendingRisk(apiBase, projectId) {
  const inbox = await requestJson(`${apiBase}/api/projects/${projectId}/workbench-inbox`);
  const item = (inbox.items || []).find((candidate) => (
    candidate.module === "medical_monitoring"
    && candidate.item_type === "risk"
    && candidate.status === "待医学复核"
  ));
  if (!item) throw new Error(`${projectId}: no pending real-project monitoring risk found`);
  return item;
}

async function staleSourceProof(apiBase, project, risk) {
  const attempt = await request(
    `${apiBase}/api/projects/${project.projectId}/workbench-inbox/${encodeURIComponent(risk.item_id)}/risk-disposition`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "reviewed",
        actor: "medical_manager",
        comment: `${project.projectCode} stale source QC`,
        expected_source_version: `stale-${risk.source_version}`,
        idempotency_key: `stale-${project.projectId}-${Date.now()}`,
        medical_judgments: { ...project.judgmentValues, review_completed: true },
      }),
    },
  );
  return {
    status: attempt.response.status,
    detail: attempt.payload.detail || "",
  };
}

async function delayedCrossProjectReadProof(cdp, apiBase, sourceProject, targetProject, sourceRisk) {
  const targetInbox = await requestJson(`${apiBase}/api/projects/${targetProject.projectId}/workbench-inbox`);
  const targetTitles = (targetInbox.items || [])
    .filter((item) => item.module === "medical_monitoring" && item.item_type === "risk")
    .map((item) => item.title);
  await evaluate(cdp, `
    (() => {
      const originalFetch = window.fetch.bind(window);
      window.__monitoringQcOriginalFetch = originalFetch;
      window.__monitoringQcDelayedReady = false;
      window.__monitoringQcRelease = null;
      window.fetch = async (...args) => {
        const url = String(args[0]?.url || args[0] || "");
        const method = String(args[1]?.method || "GET").toUpperCase();
        const response = await originalFetch(...args);
        if (method === "POST" && url.includes(${JSON.stringify(`/api/projects/${sourceProject.projectId}/workbench-inbox/${encodeURIComponent(sourceRisk.item_id)}/actions`)})) {
          window.__monitoringQcDelayedReady = true;
          await new Promise((resolve) => { window.__monitoringQcRelease = resolve; });
        }
        return response;
      };
      return true;
    })()
  `);
  await clickExact(cdp, "标记已读", ".risk-detail button");
  await waitForCondition(cdp, "window.__monitoringQcDelayedReady === true");
  await openMonitoring(cdp, targetProject);
  await waitForCondition(cdp, `document.querySelector(".monitoring-page")?.textContent.includes(${JSON.stringify(targetProject.projectCode)})`);
  await waitForCondition(cdp, `
    (() => {
      const allowed = new Set(${JSON.stringify(targetTitles)});
      const visible = Array.from(document.querySelectorAll(".risk-card-row .risk-card-title strong"))
        .map((item) => (item.textContent || "").trim())
        .filter(Boolean);
      return visible.length > 0 && visible.every((title) => allowed.has(title));
    })()
  `);
  await evaluate(cdp, `
    (() => {
      const allowed = new Set(${JSON.stringify(targetTitles)});
      window.__monitoringQcForeignTitles = [];
      window.__monitoringQcForeignMessages = [];
      const inspect = () => {
        for (const row of document.querySelectorAll(".risk-card-row")) {
          const title = row.querySelector(".risk-card-title strong")?.textContent?.trim() || "";
          if (title && !allowed.has(title)) window.__monitoringQcForeignTitles.push(title);
        }
        const message = document.querySelector(".gate-result")?.textContent?.trim() || "";
        if (message.includes("已标记已读")) window.__monitoringQcForeignMessages.push(message);
      };
      window.__monitoringQcObserver = new MutationObserver(inspect);
      window.__monitoringQcObserver.observe(document.querySelector(".monitoring-page"), { childList: true, subtree: true, characterData: true });
      inspect();
      window.__monitoringQcRelease();
      return true;
    })()
  `);
  await wait(1500);
  const proof = await evaluate(cdp, `
    (() => {
      window.__monitoringQcObserver?.disconnect();
      const titles = Array.from(document.querySelectorAll(".risk-card-row"))
        .map((row) => row.querySelector(".risk-card-title strong")?.textContent?.trim() || "")
        .filter(Boolean);
      const result = {
        selectedProject: document.querySelector('select[aria-label="选择临床研究项目"]')?.value || "",
        visibleTitles: titles,
        foreignTitles: Array.from(new Set(window.__monitoringQcForeignTitles || [])),
        foreignMessages: Array.from(new Set(window.__monitoringQcForeignMessages || [])),
      };
      window.fetch = window.__monitoringQcOriginalFetch;
      delete window.__monitoringQcOriginalFetch;
      return result;
    })()
  `);
  return {
    ...proof,
    expectedProject: targetProject.projectId,
    allVisibleTitlesBelongToTarget: proof.visibleTitles.every((title) => targetTitles.includes(title)),
  };
}

async function reloadApp(cdp, appUrl) {
  await cdp.send("Page.navigate", { url: `${appUrl}?monitoring-qc=${Date.now()}` });
  await waitForCondition(cdp, `Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`);
}

async function waitForRawIntakeSummary(cdp) {
  await waitForCondition(cdp, `
    (() => {
      const panel = document.querySelector(".monitoring-raw-intake");
      if (!panel || panel.textContent.includes("读取中")) return false;
      const values = Array.from(panel.querySelectorAll(".monitoring-raw-grid strong"))
        .map((item) => (item.textContent || "").trim());
      return values.length === 4 && values.every((value) => value && !value.startsWith("-"));
    })()
  `);
}

async function runProject(cdp, appUrl, apiBase, project, options = {}) {
  const risk = await getPendingRisk(apiBase, project.projectId);
  const stale = await staleSourceProof(apiBase, project, risk);
  if (stale.status !== 409 || !String(stale.detail).includes("stale_source")) {
    throw new Error(`${project.projectId}: stale expected_source_version returned ${stale.status}/${stale.detail}`);
  }

  await openMonitoring(cdp, project, risk.title);
  let crossProject = null;
  if (options.crossProjectTarget) {
    crossProject = await delayedCrossProjectReadProof(cdp, apiBase, project, options.crossProjectTarget, risk);
    if (
      crossProject.selectedProject !== options.crossProjectTarget.projectId
      || !crossProject.allVisibleTitlesBelongToTarget
      || crossProject.foreignTitles.length
      || crossProject.foreignMessages.length
    ) {
      throw new Error(`${project.projectId}: delayed response contaminated ${options.crossProjectTarget.projectId}: ${JSON.stringify(crossProject)}`);
    }
    await openMonitoring(cdp, project, risk.title);
    await waitForCondition(cdp, `Array.from(document.querySelectorAll(".risk-detail button")).some((item) => (item.textContent || "").trim() === "已读")`);
  } else {
    await clickExact(cdp, "标记已读", ".risk-detail button");
    await waitForCondition(cdp, `document.querySelector(".gate-result")?.textContent.includes("已标记已读")`);
    await waitForCondition(cdp, `Array.from(document.querySelectorAll(".risk-detail button")).some((item) => (item.textContent || "").trim() === "已读")`);
  }

  const judgmentInteractions = await exerciseJudgments(cdp, project.judgmentValues);
  await setTextarea(cdp, "医学处置意见", project.comment);
  await setTextarea(cdp, "Query草稿", project.query);
  await clickExact(cdp, "标记已复核", ".risk-detail button");
  await waitForCondition(cdp, `document.querySelector(".risk-meta")?.textContent.includes("已医学复核")`);
  const reviewedInbox = await requestJson(`${apiBase}/api/projects/${project.projectId}/workbench-inbox`);
  const reviewed = reviewedInbox.items.find((item) => item.item_id === risk.item_id);
    if (reviewed?.status !== "已医学复核") throw new Error(`${project.projectId}: reviewed state was not persisted`);
  if (reviewed.medical_judgments?.review_completed !== true) {
    throw new Error(`${project.projectId}: medical judgment completion was not persisted after review`);
  }
  for (const [key] of judgmentLabels) {
    if (reviewed.medical_judgments?.[key] !== project.judgmentValues[key]) {
      throw new Error(`${project.projectId}: medical judgment ${key} was not persisted after review`);
    }
  }

  await clickExact(cdp, "记录Query草稿", ".risk-detail button");
  await waitForCondition(cdp, `document.querySelector(".risk-meta")?.textContent.includes("Query草稿")`);
  await clickExact(cdp, "提交内部审批", ".risk-detail button");
  await waitForCondition(cdp, `document.querySelector(".risk-meta")?.textContent.includes("已提交内部审批")`);
  await waitForRawIntakeSummary(cdp);
  const finalScreenshot = await screenshot(cdp, `monitoring_${project.projectId}_submitted.png`);

  await reloadApp(cdp, appUrl);
  await openMonitoring(cdp, project, risk.title);
  await waitForCondition(cdp, `document.querySelector(".risk-meta")?.textContent.includes("已提交内部审批")`);
  await waitForRawIntakeSummary(cdp);
  const reloadedJudgments = await readJudgments(cdp);
  const finalInbox = await requestJson(`${apiBase}/api/projects/${project.projectId}/workbench-inbox`);
  const finalItem = finalInbox.items.find((item) => item.item_id === risk.item_id);
  const dashboard = await requestJson(`${apiBase}/api/projects/${project.projectId}/dashboard`);
  const approval = (dashboard.pending_approvals || []).find((item) => (
    item.target_type === "medical_monitoring_risk_disposition"
    && item.target_id === risk.source_id
  ));
  const reloadScreenshot = await screenshot(cdp, `monitoring_${project.projectId}_reloaded.png`);

  return {
    projectId: project.projectId,
    projectCode: project.projectCode,
    itemId: risk.item_id,
    riskId: risk.source_id,
    riskTitle: risk.title,
    sourceVersion: risk.source_version,
    staleExpectedSourceVersion: stale,
    crossProject,
    judgmentInteractions,
    reloadedJudgments,
    finalStatus: finalItem?.status || "",
    finalUnread: finalItem?.unread,
    medicalJudgments: finalItem?.medical_judgments || null,
    approvalId: approval?.approval_id || "",
    approvalState: approval?.state || "",
    screenshots: { finalScreenshot, reloadScreenshot },
  };
}

async function main() {
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  const runtimeDir = await mkdtemp(path.join(tmpdir(), "workbench-monitoring-actions-qc-"));
  const chromeUserDataDir = await mkdtemp(path.join(tmpdir(), "workbench-monitoring-chrome-qc-"));
  const apiPort = await freePort(process.env.QC_API_PORT || 8921);
  const vitePort = await freePort(process.env.QC_VITE_PORT || 5181);
  const debugPort = await freePort(process.env.CHROME_DEBUG_PORT || 9385);
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}/`;
  const runtimeDb = path.join(runtimeDir, "workbench_runtime.sqlite3");
  const mainRuntimeHashBefore = await sha256File(mainRuntimeDb);
  const api = startService(
    process.env.PYTHON_BIN || "python3",
    ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)],
    {
      cwd: projectRoot,
      env: { ...process.env, WORKBENCH_RUNTIME_DIR: runtimeDir, PYTHONUNBUFFERED: "1" },
    },
  );
  const vite = startService(
    process.env.NPM_BIN || "npm",
    ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"],
    {
      cwd: frontendRoot,
      env: { ...process.env, VITE_API_PROXY_TARGET: apiBase },
    },
  );
  let chrome;
  let cdp;
  const report = {
    appUrl,
    apiBase,
    viewport: { width: 1600, height: 1000 },
    runtime: {
      isolated: true,
      runtimeDir,
      mainRuntimeDb,
      mainRuntimeHashBefore,
      mainRuntimeHashAfter: "",
      mainRuntimeUnchanged: false,
      sqliteIntegrity: "not-run",
    },
    results: [],
    failures: [],
  };
  try {
    await waitForJson(`${apiBase}/api/health`);
    await waitForJson(appUrl);
    chrome = spawn(chromePath, [
      "--headless=new",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${chromeUserDataDir}`,
      "--window-size=1600,1000",
      "--no-first-run",
      "--no-default-browser-check",
      "about:blank",
    ], { stdio: "ignore" });
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    const target = targets.find((item) => item.type === "page");
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Google Chrome page target found");
    cdp = createCdp(target.webSocketDebuggerUrl);
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
    await waitForCondition(cdp, `Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`);

    for (let index = 0; index < projects.length; index += 1) {
      const project = projects[index];
      try {
        report.results.push(await runProject(cdp, appUrl, apiBase, project, {
          crossProjectTarget: index === 0 ? projects[1] : null,
        }));
      } catch (error) {
        const failureScreenshot = await screenshot(cdp, `monitoring_${project.projectId}_failure.png`).catch(() => "");
        report.results.push({ projectId: project.projectId, error: error.message, failureScreenshot });
        report.failures.push(`${project.projectId}: ${error.message}`);
        await reloadApp(cdp, appUrl).catch(() => undefined);
      }
    }

    report.runtime.sqliteIntegrity = sqliteIntegrity(runtimeDb);
    if (report.runtime.sqliteIntegrity !== "ok") report.failures.push(`sqlite-integrity:${report.runtime.sqliteIntegrity}`);
    for (const result of report.results) {
      if (result.error) continue;
      if (result.finalStatus !== "已提交内部审批") report.failures.push(`${result.projectId}:final-status-${result.finalStatus}`);
      if (result.finalUnread !== false) report.failures.push(`${result.projectId}:final-unread-${result.finalUnread}`);
      if (!result.approvalId || result.approvalState !== "in_medical_review") report.failures.push(`${result.projectId}:approval-not-persisted`);
      if (result.medicalJudgments?.review_completed !== true || result.reloadedJudgments?.review_completed !== true) {
        report.failures.push(`${result.projectId}:judgment-review_completed-not-persisted`);
      }
      for (const [key] of judgmentLabels) {
        const expected = projects.find((item) => item.projectId === result.projectId).judgmentValues[key];
        if (result.medicalJudgments?.[key] !== expected || result.reloadedJudgments?.[key] !== expected) {
          report.failures.push(`${result.projectId}:judgment-${key}-not-persisted`);
        }
      }
    }
  } catch (error) {
    report.failures.push(`harness: ${error.message}`);
  } finally {
    cdp?.close();
    if (chrome?.exitCode === null) {
      const exited = new Promise((resolve) => chrome.once("exit", resolve));
      chrome.kill("SIGTERM");
      await Promise.race([exited, wait(3000)]);
    }
    await stopService(vite);
    await stopService(api);
    report.runtime.mainRuntimeHashAfter = await sha256File(mainRuntimeDb);
    report.runtime.mainRuntimeUnchanged = report.runtime.mainRuntimeHashBefore === report.runtime.mainRuntimeHashAfter;
    if (!report.runtime.mainRuntimeUnchanged) report.failures.push("main-runtime-hash-changed");
    if (report.failures.length) {
      report.serviceLogs = {
        api: api.output.join("").slice(-12000),
        vite: vite.output.join("").slice(-12000),
      };
    }
    const reportPath = path.join(outputDir, "monitoring_interaction_qc.json");
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    await rm(chromeUserDataDir, { recursive: true, force: true }).catch(() => undefined);
    await rm(runtimeDir, { recursive: true, force: true }).catch(() => undefined);
    console.log(reportPath);
    if (report.failures.length) {
      console.error(`Monitoring interaction QC failed: ${report.failures.join("; ")}`);
      process.exitCode = 1;
    }
  }
}

await main();
