import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/visual_qc_20260707");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9365);
const projectRoot = path.resolve(process.cwd(), "../../..");
const runtimeFiles = [
  path.join(projectRoot, "runtime", "source_registry.jsonl"),
  path.join(projectRoot, "runtime", "ai_task_runs.jsonl"),
];

const modules = [
  {
    key: "evidenceDesign",
    label: "证据调研与方案设计",
    expectedTask: "竞品情报整理",
    minCandidates: 4,
  },
  {
    key: "tfl",
    label: "数据分析与TFL",
    expectedTask: "TFL清单与字段映射辅助",
    minCandidates: 3,
  },
  {
    key: "safety",
    label: "安全信号与PV协同",
    expectedTask: "安全个案医学复核建议",
    minCandidates: 5,
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

async function waitForJson(url, timeoutMs = 8000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await requestJson(url);
    } catch (error) {
      lastError = error;
      await wait(150);
    }
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

function createCdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  const listeners = new Map();

  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result || {});
      return;
    }
    const callbacks = listeners.get(message.method) || [];
    callbacks.forEach((callback) => callback(message.params || {}));
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

async function waitForCondition(cdp, expression, timeoutMs = 10000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    lastValue = await evaluate(cdp, expression);
    if (lastValue) return lastValue;
    await wait(200);
  }
  throw new Error(`Timed out waiting for condition. Last value: ${JSON.stringify(lastValue)}`);
}

async function clickButtonByText(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const button = buttons.find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)});
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button not found: ${label}`);
}

async function backupAndClearRuntime() {
  await mkdir(path.join(projectRoot, "runtime"), { recursive: true });
  const backups = [];
  for (const filePath of runtimeFiles) {
    const existed = existsSync(filePath);
    backups.push({
      filePath,
      existed,
      content: existed ? await readFile(filePath, "utf8") : "",
    });
    await writeFile(filePath, "", "utf8");
  }
  return backups;
}

async function restoreRuntime(backups) {
  for (const backup of backups) {
    if (backup.existed) {
      await writeFile(backup.filePath, backup.content, "utf8");
    } else {
      await rm(backup.filePath, { force: true });
    }
  }
}

async function captureModule(cdp, moduleConfig) {
  await clickButtonByText(cdp, moduleConfig.label);
  await waitForCondition(cdp, `document.body.textContent.includes(${JSON.stringify(moduleConfig.label)}) && document.body.textContent.includes("原始资料登记")`);
  await wait(500);

  const before = await evaluate(cdp, `
    (() => {
      const text = document.body.textContent || "";
      const doc = document.documentElement;
      const body = document.body;
      return {
        titlePresent: text.includes(${JSON.stringify(moduleConfig.label)}),
        sourceRegistryPresent: text.includes("原始资料登记"),
        aiPrepPresent: text.includes("独立 AI 任务准备"),
        expectedTaskPresent: text.includes(${JSON.stringify(moduleConfig.expectedTask)}),
        candidateCards: document.querySelectorAll(".source-candidate-card").length,
        registeredRows: document.querySelectorAll(".registered-source-row").length,
        overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
        hasForbiddenLifecycleText: /第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]|Stage\\s+[0-9]/.test(text),
        leaksLocalPath: text.includes("/Users/"),
      };
    })()
  `);

  const registerClicked = await evaluate(cdp, `
    (() => {
      const cards = Array.from(document.querySelectorAll(".source-candidate-card"));
      const button = cards[0]?.querySelector("button");
      if (!button) return false;
      button.scrollIntoView({ block: "center", inline: "nearest" });
      button.click();
      return true;
    })()
  `);
  if (!registerClicked) throw new Error(`Register button not found for ${moduleConfig.label}`);
  const registrationTarget = await evaluate(cdp, `
    (() => document.querySelector(".source-candidate-card h3")?.textContent?.trim() || "")()
  `);
  await waitForCondition(cdp, `
    (() => {
      const message = document.querySelector(".source-registry-message")?.textContent || "";
      return message.includes(${JSON.stringify(registrationTarget)}) && (message.includes("已登记") || message.includes("登记失败"));
    })()
  `, 90000);
  const registrationMessage = await evaluate(cdp, `
    (() => document.querySelector(".source-registry-message")?.textContent || "")()
  `);
  if (registrationMessage.includes("登记失败")) {
    throw new Error(`Registration failed for ${moduleConfig.label}: ${registrationMessage}`);
  }

  await waitForCondition(cdp, `document.querySelectorAll(".registered-source-row").length > ${before.registeredRows}`, 90000);
  await clickButtonByText(cdp, "准备 AI 任务");
  await waitForCondition(cdp, `document.body.textContent.includes("模型服务未配置") || document.body.textContent.includes("AI 任务准备失败")`, 15000);

  const after = await evaluate(cdp, `
    (() => {
      const text = document.body.textContent || "";
      const doc = document.documentElement;
      const body = document.body;
      return {
        registrationOk: text.includes("已登记") && !text.includes("登记失败"),
        blockedRunShown: text.includes("模型服务未配置"),
        registeredRows: document.querySelectorAll(".registered-source-row").length,
        selectedSourceChips: document.querySelectorAll(".selected-source-chips .tag").length,
        overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
        hasForbiddenLifecycleText: /第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]|Stage\\s+[0-9]/.test(text),
        leaksLocalPath: text.includes("/Users/"),
      };
    })()
  `);

  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: true,
  });
  const screenshotPath = path.join(outputDir, `source_registry_${moduleConfig.key}.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return { module: moduleConfig.label, screenshotPath, registrationMessage, before, after };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const backups = await backupAndClearRuntime();
  const userDataDir = await mkdtemp(path.join(tmpdir(), "source-registry-qc-"));
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
    let targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    let target = targets.find((item) => item.type === "page");
    if (!target) {
      await fetch(`http://127.0.0.1:${debugPort}/json/new?about:blank`, { method: "PUT" });
      targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
      target = targets.find((item) => item.type === "page");
    }
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Chrome page target found.");

    const cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);

    const results = [];
    for (const moduleConfig of modules) {
      results.push(await captureModule(cdp, moduleConfig));
    }
    cdp.close();

    const failed = results.filter((item, index) => (
      !item.before.titlePresent ||
      !item.before.sourceRegistryPresent ||
      !item.before.aiPrepPresent ||
      !item.before.expectedTaskPresent ||
      item.before.candidateCards < modules[index].minCandidates ||
      item.before.overflowX ||
      item.before.hasForbiddenLifecycleText ||
      item.before.leaksLocalPath ||
      !item.after.registrationOk ||
      !item.after.blockedRunShown ||
      item.after.registeredRows < 1 ||
      item.after.selectedSourceChips < 1 ||
      item.after.overflowX ||
      item.after.hasForbiddenLifecycleText ||
      item.after.leaksLocalPath
    ));
    const metricsPath = path.join(outputDir, "source_registry_qc.json");
    await writeFile(metricsPath, `${JSON.stringify({ appUrl, results }, null, 2)}\n`, "utf8");
    console.log(metricsPath);
    if (failed.length) {
      throw new Error(`Source registry QC failed: ${JSON.stringify(failed)}`);
    }
  } finally {
    chrome.kill("SIGTERM");
    await restoreRuntime(backups);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
