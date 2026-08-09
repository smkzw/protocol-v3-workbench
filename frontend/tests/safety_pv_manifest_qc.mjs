import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/visual_qc_20260707");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9367);
const projectRoot = path.resolve(process.cwd(), "../../..");

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

async function waitForCondition(cdp, expression, timeoutMs = 20000) {
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

async function clickEnabledButtonByText(cdp, label) {
  try {
    await waitForCondition(cdp, `
      Array.from(document.querySelectorAll("button")).some((item) => (item.textContent || "").trim() === ${JSON.stringify(label)} && !item.disabled)
    `, 10000);
  } catch (error) {
    const diagnostic = await evaluate(cdp, `
      (() => ({
        target: ${JSON.stringify(label)},
        textareaValue: document.querySelector(".safety-review-comment textarea")?.value || "",
        actionButtons: Array.from(document.querySelectorAll(".safety-review-actions button")).map((button) => ({
          label: (button.textContent || "").trim(),
          disabled: button.disabled,
        })),
        reviewRecords: document.querySelectorAll(".safety-review-record").length,
        textSample: (document.body.textContent || "").slice(0, 1500),
      }))()
    `);
    throw new Error(`${error.message}; button diagnostic: ${JSON.stringify(diagnostic)}`);
  }
  return clickButtonByText(cdp, label);
}

async function setTextareaValue(cdp, selector, value) {
  const updated = await evaluate(cdp, `
    (() => {
      const textarea = document.querySelector(${JSON.stringify(selector)});
      if (!textarea) return false;
      const previousValue = textarea.value;
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      setter.call(textarea, ${JSON.stringify(value)});
      if (textarea._valueTracker) textarea._valueTracker.setValue(previousValue);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    })()
  `);
  if (!updated) throw new Error(`Textarea not found: ${selector}`);
}

async function captureSafetyMetrics(cdp) {
  return evaluate(cdp, `
    (() => {
      const text = document.body.textContent || "";
      const doc = document.documentElement;
      const body = document.body;
      const buttons = Array.from(document.querySelectorAll("button")).map((button) => button.textContent || "");
      return {
        hasTitle: text.includes("安全信号与PV协同"),
        hasManifest: text.includes("安全信号审阅工作台"),
        hasReviewWorkbench: text.includes("医学意见与协同说明") && text.includes("审计记录"),
        hasReviewActions: ["保存医学意见", "标记PV协同确认", "退回补充资料", "关闭为暂无需处理", "重置处置"].every((label) => buttons.some((button) => button.includes(label))),
        hasHandoffPanel: text.includes("PV协同交接候选"),
        hasReviewedStatus: text.includes("医学已复核"),
        hasPvCandidateStatus: text.includes("PV确认候选"),
        hasBoundary: text.includes("不替代PV系统") && text.includes("待医学/PV确认"),
        hasMy009: text.includes("MY009 UC S1安全资料"),
        hasRux: text.includes("RUX-03-002 PV计划"),
        hasAeCandidate: text.includes("不良事件医学复核候选"),
        hasTeaeGate: text.includes("AE与TEAE口径待核对"),
        hasRuxScopeGate: text.includes("RUX安全总结人群口径待确认"),
        domainRows: document.querySelectorAll(".safety-domain-table tbody tr").length,
        docRows: document.querySelectorAll(".safety-doc-table tbody tr").length,
        candidateRows: document.querySelectorAll(".safety-candidate-table tbody tr").length,
        gateRows: document.querySelectorAll(".safety-gate-table tbody tr").length,
        reviewCandidateButtons: document.querySelectorAll(".safety-review-candidate-list button").length,
        auditRows: document.querySelectorAll(".safety-review-record").length,
        handoffRows: document.querySelectorAll(".safety-handoff-card").length,
        hasForbiddenLifecycleText: /第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]|Stage\\s+[0-9]/.test(text),
        hasForbiddenPvText: /E2B|监管clock|case intake|PV数据库写入|正式PV判定|PV正式判定|PV最终判定|提交PV|批准PV|生成E2B|写入PV|正式安全性结论|正式药物警戒结论/.test(text),
        hasForbiddenPvButton: buttons.some((label) => /提交|批准PV|启动|写入|最终判定|生成E2B/.test(label)),
        leaksLocalPath: text.includes("/Users/"),
        overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
        internalTableScrollCount: Array.from(document.querySelectorAll(".tfl-table-scroll")).filter((item) => item.scrollWidth > item.clientWidth).length,
      };
    })()
  `);
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const reviewStorePath = path.join(projectRoot, "runtime", "safety_review_actions.jsonl");
  let originalReviewStore = null;
  try {
    originalReviewStore = await readFile(reviewStorePath, "utf8");
  } catch {
    originalReviewStore = null;
  }
  await mkdir(path.dirname(reviewStorePath), { recursive: true });
  await writeFile(reviewStorePath, "", "utf8");
  const userDataDir = await mkdtemp(path.join(tmpdir(), "safety-pv-qc-"));
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
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);
    await clickButtonByText(cdp, "安全信号与PV协同");
    await waitForCondition(cdp, `
      document.body.textContent.includes("安全信号审阅工作台") &&
      document.body.textContent.includes("医学意见与协同说明") &&
      document.body.textContent.includes("不良事件医学复核候选") &&
      document.body.textContent.includes("AE与TEAE口径待核对")
    `, 30000);

    await setTextareaValue(cdp, ".safety-review-comment textarea", "医学复核：AE/MH、SAE字段和医学解释需PV协同确认。");
    await clickEnabledButtonByText(cdp, "保存医学意见");
    await waitForCondition(cdp, `
      document.querySelectorAll(".safety-review-record").length >= 1 &&
      document.body.textContent.includes("保存医学意见")
    `, 20000);
    await setTextareaValue(cdp, ".safety-review-comment textarea", "转PV协同确认：请PV确认报告性判断和后续流程。");
    await clickEnabledButtonByText(cdp, "标记PV协同确认");
    await waitForCondition(cdp, `
      document.body.textContent.includes("PV确认候选") &&
      document.querySelectorAll(".safety-review-record").length >= 2 &&
      document.querySelectorAll(".safety-handoff-card").length >= 1
    `, 20000);
    await waitForCondition(cdp, `
      !Array.from(document.querySelectorAll(".safety-review-actions button")).some((button) => (button.textContent || "").includes("处理中"))
    `, 10000);

    const desktopMetrics = await captureSafetyMetrics(cdp);
    await clickButtonByText(cdp, "RUX-03-002 PV计划与临床安全性总结");
    await waitForCondition(cdp, `document.body.textContent.includes("RUX安全总结人群口径待确认")`, 20000);
    const ruxMetrics = await captureSafetyMetrics(cdp);
    await clickButtonByText(cdp, "MY009 UC S1安全资料与医学复核listing");
    await waitForCondition(cdp, `document.body.textContent.includes("AE与TEAE口径待核对")`, 20000);
    const desktopShot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: true });
    const desktopPath = path.join(outputDir, "safety_pv_manifest_desktop.png");
    await writeFile(desktopPath, Buffer.from(desktopShot.data, "base64"));

    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 390,
      height: 1100,
      deviceScaleFactor: 2,
      mobile: true,
    });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);
    await clickButtonByText(cdp, "安全信号与PV协同");
    await waitForCondition(cdp, `
      document.body.textContent.includes("安全信号审阅工作台") &&
      document.body.textContent.includes("医学意见与协同说明") &&
      document.body.textContent.includes("不良事件医学复核候选") &&
      document.querySelectorAll(".safety-review-record").length >= 2 &&
      document.querySelectorAll(".safety-handoff-card").length >= 1
    `, 30000);

    const mobileMetrics = await captureSafetyMetrics(cdp);
    const mobileShot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: true });
    const mobilePath = path.join(outputDir, "safety_pv_manifest_mobile.png");
    await writeFile(mobilePath, Buffer.from(mobileShot.data, "base64"));

    cdp.close();
    const metrics = { appUrl, desktopPath, mobilePath, desktopMetrics, ruxMetrics, mobileMetrics };
    const metricsPath = path.join(outputDir, "safety_pv_manifest_qc.json");
    await writeFile(metricsPath, `${JSON.stringify(metrics, null, 2)}\n`, "utf8");
    console.log(metricsPath);

    const failed = !desktopMetrics.hasTitle ||
      !desktopMetrics.hasManifest ||
      !desktopMetrics.hasReviewWorkbench ||
      !desktopMetrics.hasReviewActions ||
      !desktopMetrics.hasHandoffPanel ||
      !desktopMetrics.hasReviewedStatus ||
      !desktopMetrics.hasPvCandidateStatus ||
      !desktopMetrics.hasBoundary ||
      !desktopMetrics.hasMy009 ||
      !desktopMetrics.hasRux ||
      !desktopMetrics.hasAeCandidate ||
      !desktopMetrics.hasTeaeGate ||
      !ruxMetrics.hasRuxScopeGate ||
      desktopMetrics.hasForbiddenLifecycleText ||
      desktopMetrics.hasForbiddenPvText ||
      desktopMetrics.hasForbiddenPvButton ||
      desktopMetrics.leaksLocalPath ||
      desktopMetrics.overflowX ||
      desktopMetrics.domainRows < 1 ||
      desktopMetrics.docRows < 1 ||
      desktopMetrics.candidateRows < 1 ||
      desktopMetrics.gateRows < 1 ||
      desktopMetrics.reviewCandidateButtons < 1 ||
      desktopMetrics.auditRows < 2 ||
      desktopMetrics.handoffRows < 1 ||
      !mobileMetrics.hasReviewWorkbench ||
      !mobileMetrics.hasReviewActions ||
      mobileMetrics.auditRows < 2 ||
      mobileMetrics.handoffRows < 1 ||
      mobileMetrics.hasForbiddenLifecycleText ||
      mobileMetrics.hasForbiddenPvText ||
      mobileMetrics.leaksLocalPath ||
      mobileMetrics.overflowX;
    if (failed) throw new Error(`Safety PV manifest QC failed: ${JSON.stringify(metrics)}`);
  } finally {
    chrome.kill("SIGTERM");
    if (originalReviewStore === null) {
      await rm(reviewStorePath, { force: true });
    } else {
      await writeFile(reviewStorePath, originalReviewStore, "utf8");
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
